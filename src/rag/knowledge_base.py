"""
Base de conhecimento técnico: recuperação de contexto.

Os seis documentos técnicos são os mesmos das Sprints 1 e 2, importados de
`legacy/chatbot_sprint2.py` sem reescrita, para que legado e refactory operem
sobre exatamente o mesmo material e o comparativo antes/depois não seja
contaminado por diferença de base.

A camada de embeddings, no entanto, foi trocada: a implementação original
dependia de um serviço proprietário de embeddings, o que acoplava o caminho
crítico a um provedor externo e impedia executar as duas versões sob o mesmo
modelo de inferência. A substituição por um modelo multilíngue local remove a
dependência de rede nessa etapa e torna o experimento reproduzível offline.
"""

from __future__ import annotations

import importlib.util
import sys
from functools import lru_cache
from pathlib import Path

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

RAIZ_PROJETO = Path(__file__).resolve().parent.parent.parent
ARQUIVO_LEGADO = RAIZ_PROJETO / "legacy" / "chatbot_sprint2.py"

MODELO_EMBEDDINGS = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
TAMANHO_CHUNK = 500
SOBREPOSICAO_CHUNK = 50
DOCUMENTOS_POR_CONSULTA = 3


def _importar_modulo_legado():
    """Importa o módulo legado sem executar a interface de linha de comando.

    O arquivo é protegido por `if __name__ == "__main__"`, portanto a importação
    carrega apenas as constantes: documentos, system prompt e exemplos few-shot.
    """
    if not ARQUIVO_LEGADO.exists():
        raise FileNotFoundError(f"núcleo legado não encontrado em {ARQUIVO_LEGADO}")

    especificacao = importlib.util.spec_from_file_location("chatbot_sprint2", ARQUIVO_LEGADO)
    modulo = importlib.util.module_from_spec(especificacao)
    sys.modules["chatbot_sprint2"] = modulo
    especificacao.loader.exec_module(modulo)
    return modulo


@lru_cache(maxsize=1)
def carregar_documentos() -> tuple[Document, ...]:
    """Devolve os seis documentos técnicos herdados das Sprints 1 e 2."""
    return tuple(_importar_modulo_legado().DOCUMENTOS)


@lru_cache(maxsize=1)
def construir_indice() -> FAISS:
    """Constrói o índice FAISS com embeddings locais."""
    divisor = RecursiveCharacterTextSplitter(
        chunk_size=TAMANHO_CHUNK, chunk_overlap=SOBREPOSICAO_CHUNK
    )
    fragmentos = divisor.split_documents(list(carregar_documentos()))
    embeddings = HuggingFaceEmbeddings(
        model_name=MODELO_EMBEDDINGS,
        encode_kwargs={"normalize_embeddings": True},
    )
    return FAISS.from_documents(fragmentos, embeddings)


def recuperar_contexto(pergunta: str, k: int = DOCUMENTOS_POR_CONSULTA) -> str:
    """Recupera os trechos mais próximos da pergunta, já rotulados por fonte."""
    if not pergunta or not pergunta.strip():
        return ""

    encontrados = construir_indice().similarity_search(pergunta, k=k)
    blocos = []
    for documento in encontrados:
        fonte = documento.metadata.get("fonte", "desconhecida")
        blocos.append(f"[fonte: {fonte}]\n{documento.page_content}")
    return "\n\n".join(blocos)
