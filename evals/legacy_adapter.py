"""
Adaptador do núcleo das Sprints 1 e 2 para medição comparativa.

O objetivo do comparativo antes/depois é medir o efeito da **arquitetura**, não
o de uma troca de modelo. Por isso o baseline não roda no provedor original: ele
roda exatamente no mesmo modelo, com os mesmos parâmetros e sobre a mesma base
de conhecimento que a versão refatorada. Tudo o que muda entre as duas colunas
da tabela é o desenho do núcleo conversacional.

O arquivo `legacy/chatbot_sprint2.py` não é modificado. Deste adaptador ele
fornece, por importação, o system prompt, os exemplos few-shot e a política de
histórico originais. A montagem manual de mensagens é reproduzida aqui na mesma
ordem e com a mesma delimitação de contexto que a implementação entregue na
Sprint 2: lista Python, corte por número de turnos, saída em texto livre.
"""

from __future__ import annotations

import sys
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from src.rag.knowledge_base import _importar_modulo_legado, construir_indice  # noqa: E402
from src.telemetry.tokens import CONTADOR, Medicao, cronometrar  # noqa: E402

_LEGADO = _importar_modulo_legado()

SYSTEM_PROMPT_LEGADO = _LEGADO.SYSTEM_PROMPT
FEW_SHOT_LEGADO = _LEGADO.FEW_SHOT
MAX_TURNS_LEGADO = _LEGADO.MAX_TURNS
DOCUMENTOS_POR_CONSULTA = 3


class ChatbotLegadoAdaptado:
    """Reprodução do núcleo manual da Sprint 2, instrumentada para medição."""

    def __init__(self, llm) -> None:
        self.llm = llm
        self.historico: list[dict] = []

    def _recuperar_contexto(self, pergunta: str, k: int = DOCUMENTOS_POR_CONSULTA) -> str:
        """Recuperação idêntica à da Sprint 2: concatenação simples dos trechos."""
        documentos = construir_indice().similarity_search(pergunta, k=k)
        return "\n\n".join(documento.page_content for documento in documentos)

    def _montar_mensagens(self, pergunta: str) -> list:
        """Montagem manual da lista de mensagens, na ordem original."""
        contexto_rag = self._recuperar_contexto(pergunta)

        conteudo_system = SYSTEM_PROMPT_LEGADO
        if contexto_rag:
            conteudo_system += f"\n\n<contexto_rag>\n{contexto_rag}\n</contexto_rag>"

        mensagens = [SystemMessage(content=conteudo_system)]

        for exemplo in FEW_SHOT_LEGADO:
            classe = HumanMessage if exemplo["role"] == "user" else AIMessage
            mensagens.append(classe(content=exemplo["content"]))

        for mensagem in self.historico[-(MAX_TURNS_LEGADO * 2):]:
            classe = HumanMessage if mensagem["role"] == "user" else AIMessage
            mensagens.append(classe(content=mensagem["content"]))

        mensagens.append(HumanMessage(content=pergunta))
        return mensagens

    def conversar(self, pergunta: str) -> tuple[str, Medicao]:
        mensagens = self._montar_mensagens(pergunta)
        medicao = Medicao(tokens_entrada=CONTADOR.contar_mensagens(mensagens))

        with cronometrar(medicao):
            resposta = self.llm.invoke(mensagens)

        texto = resposta.content or ""
        medicao.tokens_saida = CONTADOR.contar_texto(texto)

        self.historico.append({"role": "user", "content": pergunta})
        self.historico.append({"role": "assistant", "content": texto})
        return texto, medicao

    def resetar(self) -> None:
        self.historico.clear()
