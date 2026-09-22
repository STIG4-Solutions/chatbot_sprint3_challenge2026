"""
Camada de aplicação: composição da chain com guardrails, memória e telemetria.

Ordem de execução de um turno:

    entrada → moderação → validação de escopo → chain LCEL (com memória)
            → validação da resposta → resultado instrumentado

Os dois estágios de guardrail que precedem a chain evitam a chamada ao modelo
quando a consulta já está decidida, o que elimina custo e, mais importante,
torna a recusa independente da disposição do modelo em obedecer à instrução.
O estágio posterior confere a saída contra a exigência de não afirmar
especificação de produto ausente da base.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, HumanMessage

from src.chain.builder import VERSAO_PROMPT_PADRAO, construir_chain, criar_llm
from src.chain.memoria import (
    CHAVE_SAIDA_ESTRUTURADA,
    CHAVE_SAIDA_TEXTO,
    LIMITE_TOKENS_PADRAO,
    adicionar_memoria,
)
from src.config import Configuracao, ParametrosModelo, carregar_configuracao
from src.guardrails import Veredito
from src.guardrails.moderation import avaliar_entrada
from src.guardrails.scope_validator import validar_entrada, validar_resposta
from src.rag.knowledge_base import recuperar_contexto
from src.schemas.consulta_recarga import ConsultaRecarga
from src.telemetry.tokens import CONTADOR, Medicao, RegistradorDeTokens, cronometrar

SESSAO_PADRAO = "operador-local"


@dataclass
class Resultado:
    """Retorno de um turno, com resposta e instrumentação."""

    texto: str
    estruturado: ConsultaRecarga | None
    medicao: Medicao
    veredito: Veredito
    interceptado: bool = False
    erro_de_schema: str | None = None
    estagio: str = "chain"
    metadados: dict = field(default_factory=dict)

    @property
    def saida_valida(self) -> bool:
        """Verdadeiro quando o turno produziu objeto aderente ao schema."""
        return self.estruturado is not None and self.erro_de_schema is None

    def como_dicionario(self) -> dict:
        return {
            "texto": self.texto,
            "estruturado": self.estruturado.model_dump(mode="json") if self.estruturado else None,
            "saida_valida": self.saida_valida,
            "erro_de_schema": self.erro_de_schema,
            "interceptado": self.interceptado,
            "estagio": self.estagio,
            "guardrail": self.veredito.como_dicionario(),
            **self.medicao.como_dicionario(),
        }


class ChargeGridAssistente:
    """Assistente do operador comercial, com núcleo LCEL com guardrails e memória."""

    def __init__(
        self,
        versao_prompt: str = VERSAO_PROMPT_PADRAO,
        parametros: ParametrosModelo | None = None,
        configuracao: Configuracao | None = None,
        limite_tokens_memoria: int = LIMITE_TOKENS_PADRAO,
        com_recuperacao: bool = True,
        com_guardrails: bool = True,
    ) -> None:
        self.configuracao = configuracao or carregar_configuracao()
        self.parametros = parametros or ParametrosModelo(modelo=self.configuracao.modelo_primario)
        self.versao_prompt = versao_prompt
        self.com_recuperacao = com_recuperacao
        # Desligar a camada permite medir o que o system prompt sustenta
        # sozinho. É o que isola o ganho de cada versão em `prompts/VERSIONS.md`.
        self.com_guardrails = com_guardrails

        self.chain = construir_chain(
            versao_prompt=versao_prompt,
            parametros=self.parametros,
            configuracao=self.configuracao,
            com_recuperacao=com_recuperacao,
        )
        self._llm_para_memoria = criar_llm(self.parametros, self.configuracao)
        self.chain_com_memoria, self.sessoes = adicionar_memoria(
            self.chain, self._llm_para_memoria, limite_tokens_memoria
        )

    # -- turno ---------------------------------------------------------------

    def responder(self, pergunta: str, session_id: str = SESSAO_PADRAO) -> Resultado:
        medicao = Medicao()

        if self.com_guardrails:
            for estagio, avaliar in (("moderacao", avaliar_entrada), ("escopo", validar_entrada)):
                veredito = avaliar(pergunta)
                if veredito.bloqueado:
                    return self._resultado_interceptado(
                        pergunta, veredito, estagio, session_id, medicao
                    )

        registrador = RegistradorDeTokens(CONTADOR)
        erro_de_schema = None
        estruturado = None
        texto = ""

        try:
            with cronometrar(medicao):
                saida = self.chain_com_memoria.invoke(
                    {"pergunta": pergunta},
                    config={
                        "configurable": {"session_id": session_id},
                        "callbacks": [registrador],
                    },
                )
            texto = saida[CHAVE_SAIDA_TEXTO]
            estruturado = saida[CHAVE_SAIDA_ESTRUTURADA]
        except Exception as excecao:  # falha de parsing ou de transporte
            erro_de_schema = f"{type(excecao).__name__}: {excecao}"
            texto = (
                "Não foi possível produzir uma resposta aderente ao contrato de saída "
                "para esta consulta."
            )

        medicao.tokens_entrada = registrador.tokens_entrada
        medicao.tokens_saida = CONTADOR.contar_texto(texto)

        if estruturado is not None and self.com_guardrails:
            contexto = recuperar_contexto(pergunta) if self.com_recuperacao else ""
            veredito_saida = validar_resposta(estruturado, contexto)
            if veredito_saida.bloqueado:
                self._registrar_no_historico(session_id, pergunta, veredito_saida.resposta)
                return Resultado(
                    texto=veredito_saida.resposta.como_texto(),
                    estruturado=veredito_saida.resposta,
                    medicao=medicao,
                    veredito=veredito_saida,
                    interceptado=True,
                    estagio="validacao_da_resposta",
                )

        return Resultado(
            texto=texto,
            estruturado=estruturado,
            medicao=medicao,
            veredito=Veredito.liberado(),
            erro_de_schema=erro_de_schema,
        )

    # -- interceptação -------------------------------------------------------

    def _resultado_interceptado(
        self,
        pergunta: str,
        veredito: Veredito,
        estagio: str,
        session_id: str,
        medicao: Medicao,
    ) -> Resultado:
        """Produz o resultado de uma recusa determinística, sem chamar o modelo.

        A recusa é gravada no histórico da sessão para que o turno seguinte
        tenha contexto do que foi negado e por quê.
        """
        resposta = veredito.resposta
        texto = resposta.como_texto()
        medicao.tokens_entrada = CONTADOR.contar_texto(pergunta)
        medicao.tokens_saida = CONTADOR.contar_texto(texto)
        self._registrar_no_historico(session_id, pergunta, resposta)
        return Resultado(
            texto=texto,
            estruturado=resposta,
            medicao=medicao,
            veredito=veredito,
            interceptado=True,
            estagio=estagio,
        )

    def _registrar_no_historico(
        self, session_id: str, pergunta: str, resposta: ConsultaRecarga
    ) -> None:
        historico = self.sessoes.obter(session_id)
        historico.add_messages(
            [HumanMessage(content=pergunta), AIMessage(content=resposta.como_texto())]
        )

    # -- sessão --------------------------------------------------------------

    def estado_da_sessao(self, session_id: str = SESSAO_PADRAO) -> dict:
        historico = self.sessoes.obter(session_id)
        return {
            "session_id": session_id,
            "mensagens": len(historico.messages),
            "tokens_em_uso": historico.tokens_em_uso(),
            "limite_tokens": historico.limite_tokens,
        }

    def reiniciar_sessao(self, session_id: str = SESSAO_PADRAO) -> None:
        self.sessoes.obter(session_id).clear()
