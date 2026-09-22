"""
Memória conversacional por sessão com limite de tokens (Aula 02).

Nas Sprints 1 e 2 o histórico era uma lista Python cortada por quantidade fixa
de turnos (`historico[-20:]`). O critério ignorava o tamanho das mensagens: vinte
turnos curtos ocupavam uma fração da janela, enquanto vinte turnos longos podiam
estourá-la. O custo por chamada era, na prática, imprevisível.

Aqui o histórico passa a ser governado por orçamento de tokens. O descarte é
feito pela política do `ConversationTokenBufferMemory`, que remove as mensagens
mais antigas até o buffer caber no limite, e a conversa é isolada por
`session_id` através do `RunnableWithMessageHistory`, o que permite atender
múltiplos operadores no mesmo processo sem vazamento de contexto entre eles.
"""

from __future__ import annotations

import warnings
from typing import Any

# `ConversationTokenBufferMemory` é a implementação de referência do Módulo 1 e
# permanece funcional na faixa 0.3.x do LangChain. O aviso de depreciação aponta
# para o guia de migração de memória e é silenciado apenas aqui, para não poluir
# a saída da interface; a política de poda continua sendo a da classe original.
warnings.filterwarnings(
    "ignore",
    message=".*migrating_memory.*",
    category=DeprecationWarning,
)

from langchain.memory import ConversationTokenBufferMemory
from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.language_models import BaseLanguageModel
from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_core.runnables.history import RunnableWithMessageHistory

from src.chain.builder import CHAVE_HISTORICO, CHAVE_PERGUNTA
from src.schemas.consulta_recarga import ConsultaRecarga

CHAVE_SAIDA_TEXTO = "texto"
CHAVE_SAIDA_ESTRUTURADA = "estruturado"
LIMITE_TOKENS_PADRAO = 1200


# ---------------------------------------------------------------------------
# Histórico limitado por orçamento de tokens
# ---------------------------------------------------------------------------

class HistoricoPorTokens(BaseChatMessageHistory):
    """Histórico de sessão podado por contagem de tokens.

    Encapsula um `ConversationTokenBufferMemory` e expõe a interface
    `BaseChatMessageHistory` exigida pelo `RunnableWithMessageHistory`. A poda
    reproduz a política da memória encapsulada: enquanto o buffer exceder
    `max_token_limit`, a mensagem mais antiga é descartada.

    A contagem usa o tokenizador declarado pelo cliente de inferência
    (`tiktoken`, encoding `o200k_harmony`), e não uma estimativa por caracteres.
    """

    def __init__(self, llm: BaseLanguageModel, limite_tokens: int = LIMITE_TOKENS_PADRAO) -> None:
        self._memoria = ConversationTokenBufferMemory(
            llm=llm,
            max_token_limit=limite_tokens,
            return_messages=True,
        )

    @property
    def messages(self) -> list[BaseMessage]:
        return list(self._memoria.chat_memory.messages)

    @property
    def limite_tokens(self) -> int:
        return self._memoria.max_token_limit

    def tokens_em_uso(self) -> int:
        return self._memoria.llm.get_num_tokens_from_messages(
            self._memoria.chat_memory.messages
        )

    def add_messages(self, messages: list[BaseMessage]) -> None:
        self._memoria.chat_memory.add_messages(list(messages))
        self._aplicar_limite()

    def _aplicar_limite(self) -> None:
        buffer = self._memoria.chat_memory.messages
        while len(buffer) > 1 and self.tokens_em_uso() > self.limite_tokens:
            buffer.pop(0)

    def clear(self) -> None:
        self._memoria.clear()


# ---------------------------------------------------------------------------
# Registro de sessões
# ---------------------------------------------------------------------------

class RegistroDeSessoes:
    """Mapeia `session_id` para o histórico correspondente."""

    def __init__(self, llm: BaseLanguageModel, limite_tokens: int = LIMITE_TOKENS_PADRAO) -> None:
        self._llm = llm
        self._limite = limite_tokens
        self._sessoes: dict[str, HistoricoPorTokens] = {}

    def obter(self, session_id: str) -> BaseChatMessageHistory:
        if session_id not in self._sessoes:
            self._sessoes[session_id] = HistoricoPorTokens(self._llm, self._limite)
        return self._sessoes[session_id]

    def encerrar(self, session_id: str) -> None:
        self._sessoes.pop(session_id, None)

    def sessoes_ativas(self) -> list[str]:
        return sorted(self._sessoes)


# ---------------------------------------------------------------------------
# Adaptação da saída
# ---------------------------------------------------------------------------

def _normalizar_saida(resposta: Any) -> dict:
    """Uniformiza a saída da chain em texto e objeto estruturado.

    O `RunnableWithMessageHistory` grava no histórico o valor apontado por
    `output_messages_key`, que precisa ser textual. As versões de prompt que
    produzem `ConsultaRecarga` têm o texto derivado do próprio objeto, de modo
    que o histórico registre exatamente o que foi apresentado ao operador.
    """
    if isinstance(resposta, ConsultaRecarga):
        return {
            CHAVE_SAIDA_TEXTO: resposta.como_texto(),
            CHAVE_SAIDA_ESTRUTURADA: resposta,
        }
    return {
        CHAVE_SAIDA_TEXTO: str(resposta),
        CHAVE_SAIDA_ESTRUTURADA: None,
    }


# ---------------------------------------------------------------------------
# Composição
# ---------------------------------------------------------------------------

def adicionar_memoria(
    chain: Runnable,
    llm: BaseLanguageModel,
    limite_tokens: int = LIMITE_TOKENS_PADRAO,
) -> tuple[RunnableWithMessageHistory, RegistroDeSessoes]:
    """Envolve a chain com memória por sessão.

    Devolve a chain com memória e o registro de sessões, este último usado pela
    interface e pelos testes para inspecionar o estado do histórico.
    """
    registro = RegistroDeSessoes(llm, limite_tokens)

    chain_com_saida_normalizada = chain | RunnableLambda(_normalizar_saida)

    chain_com_memoria = RunnableWithMessageHistory(
        chain_com_saida_normalizada,
        registro.obter,
        input_messages_key=CHAVE_PERGUNTA,
        history_messages_key=CHAVE_HISTORICO,
        output_messages_key=CHAVE_SAIDA_TEXTO,
    )
    return chain_com_memoria, registro
