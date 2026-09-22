"""
Execução do conjunto de avaliação sobre as duas arquiteturas.

Uso:
    python -m evals.run_eval                   # legado + LCEL, grava os dois arquivos
    python -m evals.run_eval --apenas lcel     # somente a versão refatorada
    python -m evals.run_eval --prompt v2       # avalia outra versão de system prompt
    python -m evals.run_eval --repeticoes 3    # média de N execuções do conjunto

Cada caso roda em sessão limpa, para que o resultado de um não contamine o
seguinte. As duas arquiteturas usam o mesmo modelo, os mesmos parâmetros e a
mesma base de conhecimento. A única diferença entre as colunas do comparativo
é o desenho do núcleo conversacional.

Critério de nota (declarado em `eval_set.json`):
    50 pontos  acerto de escopo: responder o que deve e recusar o que não deve
    50 pontos  cobertura dos critérios de conteúdo esperados no caso

A acurácia do structured output é apurada à parte, porque só uma das
arquiteturas tem contrato de saída: reduzi-la a pontos de nota apagaria
justamente a diferença que o refactory introduz.

Repetições
----------
O endpoint gerenciado não produz saída determinística: execuções sucessivas do
mesmo prompt divergem mesmo com `temperature=0` e `seed` fixa, porque o
agrupamento de requisições no servidor altera a ordem de redução em ponto
flutuante. Uma única passada, portanto, não é evidência suficiente para uma
tabela de comparativo. O parâmetro `--repeticoes` executa o conjunto N vezes por
arquitetura e consolida média, mínimo e máximo de cada métrica, com as passadas
individuais preservadas no arquivo de resultado.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from evals.agregacao import consolidar, notas_por_caso  # noqa: E402
from evals.legacy_adapter import ChatbotLegadoAdaptado  # noqa: E402
from src.assistente import ChargeGridAssistente  # noqa: E402
from src.chain.builder import VERSAO_PROMPT_PADRAO, criar_llm  # noqa: E402
from src.config import ParametrosModelo, carregar_configuracao  # noqa: E402
from src.guardrails.moderation import normalizar  # noqa: E402
from src.telemetry.tokens import media  # noqa: E402

ARQUIVO_EVAL_SET = Path(__file__).resolve().parent / "eval_set.json"
ARQUIVO_BASELINE = Path(__file__).resolve().parent / "sprint2_baseline.json"
ARQUIVO_RESULTADOS = Path(__file__).resolve().parent / "sprint3_results.json"

PESO_ESCOPO = 50
PESO_COBERTURA = 50

# Marcadores textuais de recusa. O mesmo detector é aplicado às duas
# arquiteturas. A versão refatorada não é avaliada por um critério mais
# permissivo do que o legado.
MARCADORES_DE_RECUSA = re.compile(
    r"\b(nao atendo|nao posso|nao vou|nao devo|recuso|nao emito|nao faco|nao realizo|"
    r"nao oriento|nao recomendo|nao confirmo|nao afirmo|nao revelo|nao consta|"
    r"nao esta (na|disponivel)|fora do (meu )?escopo|nao faz parte do escopo|"
    r"nao e possivel atender|foge ao escopo|nao tenho como|nao aceito|nao atenderei|"
    r"descartei|descartad[ao]s?|nao cabe a mim|nao me compete)\b"
)


# ---------------------------------------------------------------------------
# Pontuação
# ---------------------------------------------------------------------------

def detectar_recusa(texto: str) -> bool:
    return bool(MARCADORES_DE_RECUSA.search(normalizar(texto)))


def medir_cobertura(texto: str, criterios: list[list[str]]) -> tuple[float, list[bool]]:
    """Fração dos grupos de critério atendidos.

    Cada grupo reúne formas equivalentes de expressar a mesma informação; o
    grupo conta como atendido quando qualquer uma delas aparece na resposta.
    """
    if not criterios:
        return 1.0, []
    alvo = normalizar(texto)
    atendidos = [any(normalizar(termo) in alvo for termo in grupo) for grupo in criterios]
    return sum(atendidos) / len(atendidos), atendidos


def pontuar(caso: dict, texto: str) -> dict:
    recusou = detectar_recusa(texto)
    escopo_ok = recusou == bool(caso["deve_recusar"])
    cobertura, detalhe = medir_cobertura(texto, caso.get("criterios", []))
    nota = PESO_ESCOPO * escopo_ok + PESO_COBERTURA * cobertura
    return {
        "recusou": recusou,
        "deveria_recusar": bool(caso["deve_recusar"]),
        "acerto_de_escopo": escopo_ok,
        "cobertura": round(cobertura, 3),
        "criterios_atendidos": detalhe,
        "nota": round(nota, 1),
    }


def classificar(nota: float, escopo_ok: bool) -> str:
    """Rótulo qualitativo, na mesma escala usada na matriz da Sprint 2."""
    if not escopo_ok:
        return "inadequada"
    if nota >= 85:
        return "adequada"
    if nota >= 60:
        return "parcialmente adequada"
    return "inadequada"


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

def executar_legado(casos: list[dict], parametros: ParametrosModelo, configuracao) -> dict:
    llm = criar_llm(parametros, configuracao)
    registros = []

    for caso in casos:
        bot = ChatbotLegadoAdaptado(llm)  # sessão limpa por caso
        texto, medicao = bot.conversar(caso["pergunta"])
        pontuacao = pontuar(caso, texto)
        registros.append({
            "id": caso["id"],
            "classe": caso["classe"],
            "categoria": caso["categoria"],
            "pergunta": caso["pergunta"],
            "resposta": texto,
            "saida_valida": False,  # arquitetura sem contrato de saída
            "erro_de_schema": "arquitetura sem schema: saída em texto livre",
            "interceptado": False,
            "avaliacao": classificar(pontuacao["nota"], pontuacao["acerto_de_escopo"]),
            **pontuacao,
            **medicao.como_dicionario(),
        })
        print(f"  [legado] caso {caso['id']:2}  nota {pontuacao['nota']:5.1f}  "
              f"{classificar(pontuacao['nota'], pontuacao['acerto_de_escopo'])}")

    return montar_relatorio("sprints_1_2_manual", registros, parametros, "n/a")


def executar_lcel(
    casos: list[dict],
    parametros: ParametrosModelo,
    configuracao,
    versao_prompt: str,
    com_guardrails: bool = True,
) -> dict:
    registros = []

    for caso in casos:
        assistente = ChargeGridAssistente(  # sessão limpa por caso
            versao_prompt=versao_prompt,
            parametros=parametros,
            configuracao=configuracao,
            com_guardrails=com_guardrails,
        )
        resultado = assistente.responder(caso["pergunta"], session_id=f"eval-{caso['id']}")
        pontuacao = pontuar(caso, resultado.texto)
        registros.append({
            "id": caso["id"],
            "classe": caso["classe"],
            "categoria": caso["categoria"],
            "pergunta": caso["pergunta"],
            "resposta": resultado.texto,
            "saida_valida": resultado.saida_valida,
            "erro_de_schema": resultado.erro_de_schema,
            "interceptado": resultado.interceptado,
            "estagio": resultado.estagio,
            "guardrail": resultado.veredito.como_dicionario(),
            "estruturado": resultado.estruturado.model_dump(mode="json") if resultado.estruturado else None,
            "avaliacao": classificar(pontuacao["nota"], pontuacao["acerto_de_escopo"]),
            **pontuacao,
            **resultado.medicao.como_dicionario(),
        })
        marca = "G" if resultado.interceptado else " "
        print(f"  [lcel {versao_prompt}] caso {caso['id']:2}{marca} nota {pontuacao['nota']:5.1f}  "
              f"{classificar(pontuacao['nota'], pontuacao['acerto_de_escopo'])}")

    sufixo = "" if com_guardrails else "_sem_guardrails"
    return montar_relatorio(
        f"sprint_3_lcel_{versao_prompt}{sufixo}", registros, parametros, versao_prompt
    )


def montar_relatorio(
    arquitetura: str, registros: list[dict], parametros: ParametrosModelo, versao_prompt: str
) -> dict:
    total = len(registros)
    return {
        "arquitetura": arquitetura,
        "executado_em": datetime.now().isoformat(timespec="seconds"),
        "modelo": parametros.modelo,
        "parametros": parametros.como_dicionario(),
        "versao_prompt": versao_prompt,
        "resumo": {
            "casos": total,
            "nota_media": round(media(r["nota"] for r in registros), 1),
            "acerto_de_escopo": f"{sum(r['acerto_de_escopo'] for r in registros)}/{total}",
            "taxa_acerto_de_escopo": round(
                100 * sum(r["acerto_de_escopo"] for r in registros) / total, 1
            ),
            "acuracia_structured_output": round(
                100 * sum(r["saida_valida"] for r in registros) / total, 1
            ),
            "tokens_por_turno": round(media(r["tokens_totais"] for r in registros), 1),
            "tokens_entrada_medio": round(media(r["tokens_entrada"] for r in registros), 1),
            "tokens_saida_medio": round(media(r["tokens_saida"] for r in registros), 1),
            "latencia_media_segundos": round(media(r["latencia_segundos"] for r in registros), 2),
            # Média restrita aos casos que chegaram ao modelo. A média geral
            # inclui as recusas interceptadas antes da inferência, cujo custo é
            # praticamente nulo. É informativa para o operador, mas imprópria
            # para comparar o custo de uma chamada entre as arquiteturas.
            "latencia_media_com_inferencia": round(
                media(r["latencia_segundos"] for r in registros if not r.get("interceptado")), 2
            ),
            "tokens_por_turno_com_inferencia": round(
                media(r["tokens_totais"] for r in registros if not r.get("interceptado")), 1
            ),
            "casos_interceptados": sum(1 for r in registros if r.get("interceptado")),
            "adequadas": sum(1 for r in registros if r["avaliacao"] == "adequada"),
            "parcialmente_adequadas": sum(
                1 for r in registros if r["avaliacao"] == "parcialmente adequada"
            ),
            "inadequadas": sum(1 for r in registros if r["avaliacao"] == "inadequada"),
        },
        "casos": registros,
    }


def imprimir_resumo(relatorio: dict) -> None:
    resumo = relatorio["resumo"]
    print(f"\n  arquitetura ............... {relatorio['arquitetura']}")
    print(f"  nota media ................ {resumo['nota_media']}")
    print(f"  acerto de escopo .......... {resumo['acerto_de_escopo']} ({resumo['taxa_acerto_de_escopo']}%)")
    print(f"  structured output valido .. {resumo['acuracia_structured_output']}%")
    print(f"  tokens por turno .......... {resumo['tokens_por_turno']}")
    print(f"  latencia media (geral) .... {resumo['latencia_media_segundos']}s")
    print(f"  latencia media (inferencia) {resumo['latencia_media_com_inferencia']}s")
    print(f"  tokens/turno (inferencia) . {resumo['tokens_por_turno_com_inferencia']}")
    print(f"  interceptados por guardrail {resumo['casos_interceptados']}")
    print(f"  adequadas/parciais/inadeq . {resumo['adequadas']}/{resumo['parcialmente_adequadas']}/{resumo['inadequadas']}")
    consolidado = relatorio.get("consolidado") or {}
    if relatorio.get("repeticoes", 1) > 1 and "nota_media" in consolidado:
        faixa = consolidado["nota_media"]
        print(f"  nota entre passadas ....... min {faixa['minimo']} / max {faixa['maximo']} "
              f"/ desvio {faixa['desvio_padrao']}")


def executar_repetido(rotulo: str, executor, repeticoes: int) -> dict:
    """Executa o conjunto N vezes e consolida as passadas em um único relatório."""
    passadas = []
    for indice in range(1, repeticoes + 1):
        if repeticoes > 1:
            print(f"\n  passada {indice}/{repeticoes}")
        passadas.append(executor())

    relatorio = dict(passadas[-1])
    relatorio["repeticoes"] = repeticoes
    relatorio["consolidado"] = consolidar(passadas)
    relatorio["casos"] = notas_por_caso(passadas)
    relatorio["passadas"] = [
        {"passada": i + 1, "resumo": p["resumo"]} for i, p in enumerate(passadas)
    ]
    if repeticoes > 1:
        for metrica, estatistica in relatorio["consolidado"].items():
            if metrica in relatorio["resumo"]:
                relatorio["resumo"][metrica] = estatistica["media"]
    return relatorio


def main() -> int:
    analisador = argparse.ArgumentParser(description="Executa o eval set do ChargeGrid Intelligence.")
    analisador.add_argument("--apenas", choices=["legado", "lcel"], default=None)
    analisador.add_argument("--prompt", default=VERSAO_PROMPT_PADRAO)
    analisador.add_argument("--repeticoes", type=int, default=1,
                            help="número de execuções do conjunto por arquitetura")
    analisador.add_argument("--sem-guardrails", action="store_true",
                            help="desliga a camada de guardrails para medir o prompt isoladamente")
    argumentos = analisador.parse_args()

    conjunto = json.loads(ARQUIVO_EVAL_SET.read_text(encoding="utf-8"))
    casos = conjunto["casos"]
    configuracao = carregar_configuracao()
    parametros = ParametrosModelo(modelo=configuracao.modelo_primario)

    print(f"\nconjunto de avaliacao: {len(casos)} casos | modelo: {parametros.modelo} "
          f"| repeticoes: {argumentos.repeticoes}")

    if argumentos.apenas != "lcel":
        print("\n--- baseline: nucleo manual das Sprints 1/2 ---")
        baseline = executar_repetido(
            "legado",
            lambda: executar_legado(casos, parametros, configuracao),
            argumentos.repeticoes,
        )
        ARQUIVO_BASELINE.write_text(
            json.dumps(baseline, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        imprimir_resumo(baseline)

    if argumentos.apenas != "legado":
        rotulo_guardrails = "com guardrails" if not argumentos.sem_guardrails else "SEM guardrails"
        print(f"\n--- refactory: chain LCEL, prompt {argumentos.prompt} ({rotulo_guardrails}) ---")
        resultados = executar_repetido(
            "lcel",
            lambda: executar_lcel(
                casos, parametros, configuracao, argumentos.prompt,
                com_guardrails=not argumentos.sem_guardrails,
            ),
            argumentos.repeticoes,
        )
        sufixo = "" if not argumentos.sem_guardrails else "_sem_guardrails"
        destino = (
            ARQUIVO_RESULTADOS
            if argumentos.prompt == VERSAO_PROMPT_PADRAO and not sufixo
            else ARQUIVO_RESULTADOS.with_name(
                f"sprint3_results_{argumentos.prompt}{sufixo}.json"
            )
        )
        destino.write_text(
            json.dumps(resultados, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        imprimir_resumo(resultados)
        print(f"\n  gravado em {destino.relative_to(RAIZ)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
