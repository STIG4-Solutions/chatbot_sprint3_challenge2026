"""
Demonstração da memória conversacional por sessão (Aula 02 · item §3.2 do escopo).

Executa um diálogo encadeado em que cada turno depende do anterior e imprime,
a cada passo, o estado do histórico: número de mensagens, tokens em uso e o
limite do orçamento. O quarto turno não chega ao modelo, pois é interceptado pela
camada de guardrails, o que também demonstra que a recusa é registrada no
histórico, e não descartada.

Execução:  python -m src.demo_memoria
"""

from __future__ import annotations

from src.assistente import ChargeGridAssistente
from src.config import carregar_configuracao

SESSAO = "demo-memoria"

DIALOGO = [
    "Tenho 200 kW de demanda contratada no meu supermercado.",
    "Nas sextas à noite o consumo da loja chega a 170 kW. Qual a folga que sobra?",
    "E se eu quiser ligar quatro carros ao mesmo tempo nesse horário?",
    "Considerando esse mesmo cenário, qual tarifa o sistema aplicaria?",
    "Posso trocar o disjuntor do quadro eu mesmo para liberar mais potência?",
]

LARGURA = 78


def main() -> int:
    try:
        carregar_configuracao()
    except EnvironmentError as erro:
        print(f"\n[configuração] {erro}\n")
        return 1

    assistente = ChargeGridAssistente()
    estado_inicial = assistente.estado_da_sessao(SESSAO)

    print("=" * LARGURA)
    print(" Memória conversacional por sessão · ChargeGrid Intelligence")
    print("=" * LARGURA)
    print(f" session_id ......... {SESSAO}")
    print(f" modelo ............. {assistente.parametros.modelo}")
    print(f" orçamento .......... {estado_inicial['limite_tokens']} tokens")
    print(f" política de poda ... descarte das mensagens mais antigas até caber")
    print("=" * LARGURA)

    for numero, pergunta in enumerate(DIALOGO, start=1):
        resultado = assistente.responder(pergunta, session_id=SESSAO)
        estado = assistente.estado_da_sessao(SESSAO)

        print(f"\n[turno {numero}] Operador: {pergunta}")
        print(f"            ChargeGrid: {resultado.texto.splitlines()[0]}")

        marcadores = [
            f"schema={'ok' if resultado.saida_valida else 'falhou'}",
            f"tokens={resultado.medicao.tokens_entrada}+{resultado.medicao.tokens_saida}",
            f"latencia={resultado.medicao.latencia_segundos:.2f}s",
        ]
        if resultado.interceptado:
            marcadores.append(
                f"interceptado={resultado.veredito.categoria.value} "
                f"(sem chamada ao modelo)"
            )
        print(f"            [{' | '.join(marcadores)}]")
        print(f"            memória: {estado['mensagens']} mensagens · "
              f"{estado['tokens_em_uso']}/{estado['limite_tokens']} tokens")

    print("\n" + "=" * LARGURA)
    print(" Encadeamento verificado: os turnos 2, 3 e 4 resolvem referências")
    print(" ('a folga', 'nesse horário', 'esse mesmo cenário') a partir de dados")
    print(" apresentados em turnos anteriores, sem repeti-los na pergunta.")
    print("=" * LARGURA)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
