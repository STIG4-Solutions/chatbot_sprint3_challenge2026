"""
Validação de escopo GoodWe, na entrada e na saída.

Na entrada, confere se a consulta pertence ao domínio de gestão comercial de
eletropostos declarado no `<escopo_permitido>` do system prompt. Na saída,
verifica a exigência específica do §6.3: o assistente não pode afirmar
especificação de produto que não esteja na base de conhecimento.

A verificação de saída é deliberadamente conservadora. Ela não tenta julgar a
correção factual da resposta, o que exigiria uma fonte de verdade externa. O que
ela detecta é o caso concreto de alucinação que importa nesta operação: atribuir
número de especificação a um equipamento cujo nome sequer aparece na base
técnica do projeto.
"""

from __future__ import annotations

import re

from src.guardrails import CategoriaBloqueio, Veredito, montar_recusa
from src.guardrails.moderation import normalizar
from src.rag.knowledge_base import carregar_documentos
from src.schemas.consulta_recarga import ConsultaRecarga

# ---------------------------------------------------------------------------
# Escopo de entrada
# ---------------------------------------------------------------------------

PADROES_FORA_DE_ESCOPO = {
    "entretenimento_ou_pessoal": [
        r"\b(restaurante|lanchonete|cardapio|receita de (bolo|comida)|filme|serie|novela|futebol|jogo do|piada|horoscopo|musica)\b",
        r"\b(como voce esta|qual seu nome|voce tem (namorad|sentiment))\w*\b",
        r"\b(previsao do tempo|vai chover|temperatura hoje)\b",
    ],
    "suporte_de_hardware": [
        r"\b(conserto|consertar|conserta|reparo|reparar|desmonto|desmontar|soldar)\b.{0,30}\b(placa|fonte|cabo|conector|carregador|equipamento|estacao|gabinete)\b",
        r"\b(trocar|substituir) a (peca|placa|fonte|fonte de alimentacao)\b",
        r"\babrir o (equipamento|gabinete|carregador)\b",
        r"\bassistencia tecnica\b",
        r"\b(manutencao (preventiva|corretiva))\b.{0,25}\b(equipamento|carregador|estacao)\b",
        r"\b(numero de serie|garantia do fabricante|rma)\b",
    ],
    "dados_de_usuario_final": [
        r"\b(lgpd|dados pessoais|cpf|telefone|email|endereco)\b.{0,30}\b(motorista|cliente|usuario final|condutor)\b",
        r"\b(quem (foi|esteve)|identifique|me diga quem)\b.{0,30}\b(carregou|utilizou o carregador)\b",
        r"\b(historico de localizacao|rastrear o (veiculo|motorista))\b",
    ],
    "comparacao_com_concorrentes": [
        r"\b(chargegrid|nosso sistema|essa solucao)\b.{0,40}\b(melhor|pior|superior|inferior)\b.{0,30}\b(que|a|do que)\b",
        r"\b(comparado|versus|vs)\b.{0,25}\b(concorrente|tupi|wallbox|enel x|voltbras|neocharge)\b",
        r"\b(por que|porque)\b.{0,30}\bescolher\b.{0,30}\bem vez d\w+\b.{0,25}\bconcorrente\b",
    ],
}

RECUSA_FORA_DE_ESCOPO = (
    "Esta consulta está fora do escopo do ChargeGrid Intelligence.",
    "O assistente cobre gestão de demanda de potência, faturamento e tarifação, base "
    "regulatória da recarga comercial, dados operacionais OCPP e MODBUS, e "
    "interoperabilidade entre carregadores homologados.",
    "Nenhuma consulta foi encaminhada ao modelo. Reformule dentro desses temas e eu "
    "sigo com a análise.",
)


def validar_entrada(pergunta: str) -> Veredito:
    """Bloqueia consultas que não pertencem ao domínio de gestão de eletropostos."""
    texto = normalizar(pergunta)
    if not texto:
        return Veredito.liberado()

    for assunto, padroes in PADROES_FORA_DE_ESCOPO.items():
        for padrao in padroes:
            ocorrencia = re.search(padrao, texto)
            if ocorrencia:
                direta, fundamento, acao = RECUSA_FORA_DE_ESCOPO
                return Veredito(
                    bloqueado=True,
                    categoria=CategoriaBloqueio.FORA_DE_ESCOPO,
                    motivo=f"{direta} (assunto detectado: {assunto})",
                    gatilho=ocorrencia.group(0),
                    resposta=montar_recusa(
                        CategoriaBloqueio.FORA_DE_ESCOPO, direta, fundamento, acao
                    ),
                )
    return Veredito.liberado()


# ---------------------------------------------------------------------------
# Especificações de produto na saída
# ---------------------------------------------------------------------------

# Fabricantes e linhas de produto com presença no mercado brasileiro de recarga.
# A lista existe para reconhecer a *menção*; o que decide o bloqueio é se o nome
# mencionado consta da base de conhecimento do projeto.
FABRICANTES_CONHECIDOS = [
    "goodwe", "abb", "terra", "schneider", "evlink", "webasto", "unite", "efacec",
    "tesla", "siemens", "delta", "tritium", "alfen", "wallbox", "kempower",
    "byd", "bmw", "volvo", "chargepoint", "enel x", "tupi", "voltbras", "neocharge",
    "circontrol", "ingeteam", "phihong", "star charge", "autel",
]

# Verbos e substantivos que caracterizam afirmação de especificação técnica.
MARCADORES_DE_ESPECIFICACAO = (
    r"(suporta|entrega|fornece|possui|tem|opera (a|com)|potencia de|capacidade de|"
    r"limitado a|ate|maximo de|corrente de|tensao de)"
)

PADRAO_GRANDEZA = r"\d+[\.,]?\d*\s*(kw|kwh|a\b|v\b|amperes?|volts?|quilowatts?)"

RECUSA_ESPECIFICACAO = (
    "Não confirmo essa especificação: ela não consta da base técnica do sistema.",
    "A base de conhecimento do ChargeGrid cobre os protocolos OCPP e MODBUS, o "
    "algoritmo de gerenciamento de demanda, o modelo de precificação, a Resolução "
    "Normativa ANEEL nº 1.000/2021 e a lista de fabricantes homologados. "
    "Especificação de equipamento fora desse conjunto não é afirmada.",
    "A resposta gerada foi descartada. Consulte a ficha técnica do fabricante ou o "
    "registro de homologação do equipamento; posso seguir com os dados de operação "
    "efetivamente medidos no ponto de entrega.",
)


def _vocabulario_da_base() -> str:
    return normalizar(" ".join(documento.page_content for documento in carregar_documentos()))


def _fabricantes_fundamentados() -> set[str]:
    base = _vocabulario_da_base()
    return {nome for nome in FABRICANTES_CONHECIDOS if nome in base}


def validar_resposta(resposta: ConsultaRecarga | str, contexto_recuperado: str = "") -> Veredito:
    """Verifica se a resposta afirmou especificação de equipamento sem fundamento.

    O bloqueio exige a conjunção de três sinais na mesma frase: um fabricante ou
    linha de produto ausente da base, um marcador de afirmação de especificação e
    uma grandeza numérica com unidade elétrica. Sinais isolados não bloqueiam:
    citar um fabricante, por si só, é legítimo.
    """
    texto_original = resposta.como_texto() if isinstance(resposta, ConsultaRecarga) else str(resposta)
    texto = normalizar(texto_original)
    fundamentados = _fabricantes_fundamentados() | set(
        nome for nome in FABRICANTES_CONHECIDOS if nome in normalizar(contexto_recuperado)
    )

    for frase in re.split(r"[.;\n]", texto):
        if not re.search(MARCADORES_DE_ESPECIFICACAO, frase):
            continue
        if not re.search(PADRAO_GRANDEZA, frase):
            continue
        for fabricante in FABRICANTES_CONHECIDOS:
            if fabricante in frase and fabricante not in fundamentados:
                direta, fundamento, acao = RECUSA_ESPECIFICACAO
                return Veredito(
                    bloqueado=True,
                    categoria=CategoriaBloqueio.ESPECIFICACAO_NAO_FUNDAMENTADA,
                    motivo=direta,
                    gatilho=f"{fabricante}: {frase.strip()[:80]}",
                    resposta=montar_recusa(
                        CategoriaBloqueio.ESPECIFICACAO_NAO_FUNDAMENTADA,
                        direta, fundamento, acao,
                    ),
                )

    return Veredito.liberado()
