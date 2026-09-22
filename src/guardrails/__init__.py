"""
Camada de guardrails do ChargeGrid Intelligence.

O system prompt declara o que o assistente deve recusar, mas instrução em
linguagem natural é persuasível: basta uma formulação suficientemente insistente
para que o modelo negocie a própria regra. Esta camada torna determinísticas as
recusas que não podem depender da boa vontade do modelo.

São dois estágios independentes:

`moderation`      : inspeciona a entrada antes da inferência e intercepta
                    tentativas de subverter as instruções (jailbreak e injeção de
                    prompt) e pedidos que exigem profissional habilitado
                    (jurídico, financeiro e segurança elétrica).
`scope_validator` : verifica a aderência ao domínio GoodWe na entrada e, depois
                    da inferência, confere se a resposta não afirmou
                    especificação de produto ausente da base de conhecimento.

Quando um estágio bloqueia, a recusa já sai no formato contratual
`ConsultaRecarga`, de modo que o consumidor da chain não precise distinguir
resposta gerada de resposta interceptada.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.schemas.consulta_recarga import CategoriaConsulta, ConsultaRecarga


class CategoriaBloqueio(str, Enum):
    """Motivos pelos quais uma interação é interrompida antes ou depois da inferência."""

    JAILBREAK = "jailbreak"
    INJECAO_DE_PROMPT = "injecao_de_prompt"
    ACONSELHAMENTO_JURIDICO = "aconselhamento_juridico"
    ACONSELHAMENTO_FINANCEIRO = "aconselhamento_financeiro"
    SEGURANCA_ELETRICA = "seguranca_eletrica"
    FORA_DE_ESCOPO = "fora_de_escopo"
    ESPECIFICACAO_NAO_FUNDAMENTADA = "especificacao_nao_fundamentada"


# Categorias que representam encaminhamento a profissional habilitado, e não
# simples recusa de assunto.
CATEGORIAS_DE_DOMINIO = {
    CategoriaBloqueio.ACONSELHAMENTO_JURIDICO,
    CategoriaBloqueio.ACONSELHAMENTO_FINANCEIRO,
    CategoriaBloqueio.SEGURANCA_ELETRICA,
}


@dataclass(frozen=True)
class Veredito:
    """Resultado da avaliação de um estágio de guardrail."""

    bloqueado: bool
    categoria: CategoriaBloqueio | None = None
    motivo: str = ""
    gatilho: str = ""
    resposta: ConsultaRecarga | None = None

    @staticmethod
    def liberado() -> "Veredito":
        return Veredito(bloqueado=False)

    def como_dicionario(self) -> dict:
        return {
            "bloqueado": self.bloqueado,
            "categoria": self.categoria.value if self.categoria else None,
            "motivo": self.motivo,
            "gatilho": self.gatilho,
        }


def montar_recusa(
    categoria: CategoriaBloqueio,
    resposta_direta: str,
    fundamentacao_tecnica: str,
    acao_do_sistema: str,
) -> ConsultaRecarga:
    """Constrói a recusa já no contrato de saída do projeto.

    Recusa não carrega métrica operacional nem projeção de impacto: o próprio
    schema rejeitaria o objeto se carregasse.
    """
    categoria_consulta = (
        CategoriaConsulta.RECUSA_DOMINIO
        if categoria in CATEGORIAS_DE_DOMINIO
        else CategoriaConsulta.FORA_DE_ESCOPO
    )
    return ConsultaRecarga(
        resposta_direta=resposta_direta,
        fundamentacao_tecnica=fundamentacao_tecnica,
        acao_do_sistema=acao_do_sistema,
        impacto_no_negocio=None,
        categoria=categoria_consulta,
        dentro_do_escopo=False,
        fontes=["guardrails/" + categoria.value],
    )
