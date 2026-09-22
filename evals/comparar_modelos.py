"""
Comparativo de modelos e parâmetros, insumo do `docs/relatorio_modelos.md`.

Cobre dois itens do escopo:

§6.2  comparar dois ou mais modelos e documentar `temperature`, `top_p` e
      `max_tokens` com base em medição, não em preferência declarada. São três
      modelos: dois da mesma família em portes diferentes, o que isola o efeito
      do tamanho, e um de família distinta, o que expõe o efeito da arquitetura
      do modelo.
§6.5  bônus de chamada multi-provider: o mesmo conjunto é submetido a mais de um
      modelo e a mais de uma versão de system prompt, formando uma matriz.

Uso:
    python -m evals.comparar_modelos                 # matriz modelos x prompts
    python -m evals.comparar_modelos --temperatura   # inclui a varredura de temperature
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from evals.run_eval import ARQUIVO_EVAL_SET, executar_lcel  # noqa: E402
from src.config import ParametrosModelo, carregar_configuracao  # noqa: E402

ARQUIVO_SAIDA = Path(__file__).resolve().parent / "comparativo_modelos.json"

PROMPTS_COMPARADOS = ("v2", "v3")
TEMPERATURAS_AVALIADAS = (0.0, 0.2, 0.7)


def _linha(relatorio: dict, modelo: str, prompt: str) -> dict:
    resumo = relatorio["resumo"]
    return {
        "modelo": modelo,
        "prompt": prompt,
        "nota_media": resumo["nota_media"],
        "acerto_de_escopo_pct": resumo["taxa_acerto_de_escopo"],
        "structured_output_pct": resumo["acuracia_structured_output"],
        "tokens_por_turno": resumo["tokens_por_turno"],
        "tokens_com_inferencia": resumo["tokens_por_turno_com_inferencia"],
        "latencia_media_s": resumo["latencia_media_segundos"],
        "latencia_com_inferencia_s": resumo["latencia_media_com_inferencia"],
        "adequadas": resumo["adequadas"],
        "inadequadas": resumo["inadequadas"],
    }


def matriz_modelos_x_prompts(casos, configuracao) -> list[dict]:
    """Executa o conjunto para cada combinação de modelo e versão de prompt.

    A camada de guardrails fica desligada aqui. Ela é determinística e responde
    de forma idêntica sob qualquer modelo: mantê-la ligada uniformizaria mais da
    metade dos casos e esconderia justamente a diferença que esta matriz precisa
    medir. Os números abaixo representam, portanto, o que cada modelo sustenta
    por conta própria, e não o comportamento do sistema em produção, medido em
    `evals/sprint3_results.json`.
    """
    modelos = (
        configuracao.modelo_primario,
        configuracao.modelo_alternativo,
        configuracao.modelo_terceiro,
    )
    linhas = []

    for modelo in modelos:
        for prompt in PROMPTS_COMPARADOS:
            print(f"\n--- {modelo} | prompt {prompt} ---")
            parametros = ParametrosModelo(modelo=modelo)
            relatorio = executar_lcel(
                casos, parametros, configuracao, prompt, com_guardrails=False
            )
            linha = _linha(relatorio, modelo, prompt)
            linha["parametros"] = parametros.como_dicionario()
            linhas.append(linha)
            print(f"    nota {linha['nota_media']} | escopo {linha['acerto_de_escopo_pct']}% "
                  f"| schema {linha['structured_output_pct']}% "
                  f"| {linha['latencia_com_inferencia_s']}s")
    return linhas


def varredura_de_temperatura(casos, configuracao) -> list[dict]:
    """Mede o efeito de `temperature` no modelo primário com o prompt de produção."""
    linhas = []
    for temperatura in TEMPERATURAS_AVALIADAS:
        print(f"\n--- {configuracao.modelo_primario} | temperature {temperatura} ---")
        parametros = ParametrosModelo(
            modelo=configuracao.modelo_primario, temperature=temperatura
        )
        relatorio = executar_lcel(
            casos, parametros, configuracao, "v3", com_guardrails=False
        )
        linha = _linha(relatorio, configuracao.modelo_primario, "v3")
        linha["parametros"] = parametros.como_dicionario()
        linha["temperature"] = temperatura
        linhas.append(linha)
        print(f"    nota {linha['nota_media']} | schema {linha['structured_output_pct']}%")
    return linhas


def main() -> int:
    analisador = argparse.ArgumentParser(description="Comparativo de modelos e parâmetros.")
    analisador.add_argument("--temperatura", action="store_true",
                            help="inclui a varredura de temperature")
    argumentos = analisador.parse_args()

    conjunto = json.loads(ARQUIVO_EVAL_SET.read_text(encoding="utf-8"))
    casos = conjunto["casos"]
    configuracao = carregar_configuracao()

    saida = {
        "executado_em": datetime.now().isoformat(timespec="seconds"),
        "casos_por_execucao": len(casos),
        "modelos": [configuracao.modelo_primario, configuracao.modelo_alternativo],
        "prompts": list(PROMPTS_COMPARADOS),
        "matriz": matriz_modelos_x_prompts(casos, configuracao),
    }

    if argumentos.temperatura:
        saida["varredura_temperatura"] = varredura_de_temperatura(casos, configuracao)

    ARQUIVO_SAIDA.write_text(json.dumps(saida, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\ngravado em {ARQUIVO_SAIDA.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
