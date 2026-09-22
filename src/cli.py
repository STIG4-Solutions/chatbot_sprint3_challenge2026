"""
Interface de linha de comando do ChargeGrid Intelligence, Sprint 3.

Execução:  python -m src.cli

Comandos da sessão:
    sessao   estado do histórico (mensagens, tokens em uso, limite)
    json     objeto estruturado completo do último turno
    reset    limpa o histórico da sessão corrente
    sair     encerra
"""

from __future__ import annotations

import json
import sys

from src.assistente import SESSAO_PADRAO, ChargeGridAssistente, Resultado
from src.chain.builder import VERSAO_PROMPT_PADRAO
from src.config import carregar_configuracao

LARGURA = 74


def _cabecalho(assistente: ChargeGridAssistente) -> None:
    print("=" * LARGURA)
    print(" ChargeGrid Intelligence · Assistente do Operador Comercial")
    print(" Sprint 3 · refactory LCEL · EV Challenge 2026 | GoodWe x FIAP")
    print("=" * LARGURA)
    print(f" modelo       : {assistente.parametros.modelo}")
    print(f" prompt       : {assistente.versao_prompt}")
    print(f" parametros   : temperature={assistente.parametros.temperature} "
          f"top_p={assistente.parametros.top_p} max_tokens={assistente.parametros.num_predict}")
    print(f" memoria      : orcamento de "
          f"{assistente.estado_da_sessao()['limite_tokens']} tokens por sessao")
    print("=" * LARGURA)
    print(" comandos: sessao | json | reset | sair")
    print("=" * LARGURA)


def _imprimir(resultado: Resultado) -> None:
    print(f"\nChargeGrid: {resultado.texto}")

    rodape = [
        f"tokens {resultado.medicao.tokens_entrada}+{resultado.medicao.tokens_saida}",
        f"{resultado.medicao.latencia_segundos:.2f}s",
    ]
    if resultado.estruturado is not None:
        rodape.append(f"categoria={resultado.estruturado.categoria.value}")
    if resultado.interceptado:
        rodape.append(f"guardrail={resultado.veredito.categoria.value} ({resultado.estagio})")
    if resultado.erro_de_schema:
        rodape.append(f"schema=FALHOU ({resultado.erro_de_schema[:60]})")
    print(f"   [{' | '.join(rodape)}]")


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    versao_prompt = argv[0] if argv else VERSAO_PROMPT_PADRAO

    try:
        carregar_configuracao()
    except EnvironmentError as erro:
        print(f"\n[configuração] {erro}\n")
        return 1

    assistente = ChargeGridAssistente(versao_prompt=versao_prompt)
    _cabecalho(assistente)

    ultimo: Resultado | None = None

    while True:
        try:
            entrada = input("\nOperador: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSistema encerrado.")
            return 0

        if not entrada:
            continue

        comando = entrada.lower()
        if comando == "sair":
            print("Sistema encerrado.")
            return 0
        if comando == "reset":
            assistente.reiniciar_sessao()
            print("Histórico da sessão limpo.")
            continue
        if comando == "sessao":
            print(json.dumps(assistente.estado_da_sessao(), indent=2, ensure_ascii=False))
            continue
        if comando == "json":
            if ultimo is None or ultimo.estruturado is None:
                print("Nenhum objeto estruturado disponível.")
            else:
                print(json.dumps(
                    ultimo.estruturado.model_dump(mode="json"), indent=2, ensure_ascii=False
                ))
            continue

        ultimo = assistente.responder(entrada, session_id=SESSAO_PADRAO)
        _imprimir(ultimo)


if __name__ == "__main__":
    raise SystemExit(main())
