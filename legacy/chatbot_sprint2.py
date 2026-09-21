"""
ChargeGrid Intelligence — Assistente Gerencial
Sprint 2 — EV Challenge 2026 | GoodWe x FIAP

Integrantes:
    Gabriel Fagundes  RM 569074
    Gabriel Freitas   RM 572943
    Giovanni Merlotti RM 573721
    Glauco Kelly      RM 572840
    Sergio Amaral     RM 570184
    Thiago Renatino   RM 569073

Técnicas implementadas:
    - RAG  (Retrieval-Augmented Generation) com base de conhecimento técnico
    - Few-shot prompting com exemplos validados na Sprint 1
    - Memória de conversa via histórico de mensagens
"""

import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage


# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

def carregar_api_key() -> None:
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        raise EnvironmentError(
            "OPENAI_API_KEY não encontrada. "
            "Crie um arquivo .env com base no .env.example."
        )


# ---------------------------------------------------------------------------
# Base de conhecimento para RAG
# ---------------------------------------------------------------------------

DOCUMENTOS = [
    Document(
        page_content=(
            "ANEEL Resolução Normativa nº 1.000/2021 — Recarga de Veículos Elétricos\n\n"
            "A Resolução Normativa ANEEL nº 1.000/2021 classifica a atividade de recarga "
            "pública e semi-pública como serviço de valor adicionado ao fornecimento de "
            "energia elétrica. O operador comercial pode praticar preços livremente "
            "negociados, sem tabelamento. Isso torna legal e viável a tarifação dinâmica "
            "baseada em horário de pico, demanda de potência disponível e condições de "
            "mercado. Ultrapassagens de demanda contratada geram multas de até 3x a tarifa "
            "normal por kW excedente."
        ),
        metadata={"fonte": "ANEEL_RN_1000_2021", "topico": "regulatorio"},
    ),
    Document(
        page_content=(
            "Protocolo OCPP — Open Charge Point Protocol\n\n"
            "O OCPP é o protocolo industrial para comunicação entre controladores de "
            "eletropostos (Charge Points) e o sistema de gestão central (CSMS). "
            "Versões em uso: OCPP 1.6 (JSON/SOAP) e OCPP 2.0.1 (JSON).\n"
            "Eventos registrados em cada sessão:\n"
            "- StartTransaction: início de recarga com timestamp e leitura kWh inicial\n"
            "- StopTransaction: fim de recarga com energia total entregue em kWh\n"
            "- MeterValues: leituras periódicas de consumo em tempo real\n"
            "- StatusNotification: estado do conector (Available, Charging, Faulted)\n"
            "- SetChargingProfile: comando para limitar ou ajustar potência por conector\n"
            "Cada evento carrega timestamp UTC e ID de transação único para rastreabilidade "
            "completa de faturamento e auditoria."
        ),
        metadata={"fonte": "OCPP_spec", "topico": "protocolo"},
    ),
    Document(
        page_content=(
            "Protocolo MODBUS — Medição Física de Energia\n\n"
            "O MODBUS é protocolo serial para leitura direta de medidores de energia "
            "instalados nos eletropostos. Modos: MODBUS RTU (RS-485) e MODBUS TCP/IP.\n"
            "Registros típicos lidos nos medidores:\n"
            "- 0x0000: Tensão de fase (V)\n"
            "- 0x0006: Corrente de fase (A)\n"
            "- 0x000C: Potência ativa instantânea (kW)\n"
            "- 0x0046: Energia ativa acumulada (kWh)\n"
            "A dupla validação MODBUS + OCPP garante precisão metrológica no faturamento: "
            "o MODBUS mede fisicamente, o OCPP registra e transmite. "
            "A diferença entre leitura inicial e final de kWh determina o valor cobrado."
        ),
        metadata={"fonte": "MODBUS_spec", "topico": "protocolo"},
    ),
    Document(
        page_content=(
            "Gerenciamento Inteligente de Demanda — Smart Charging\n\n"
            "O DSM (Demand Side Management) protege a infraestrutura elétrica do "
            "estabelecimento regulando a potência total dos carregadores em tempo real.\n"
            "Algoritmo de operação:\n"
            "1. Monitoramento: leitura do quadro elétrico via MODBUS a cada 15 segundos\n"
            "2. Cálculo de headroom: potência disponível = limite contratado - consumo da loja\n"
            "3. Distribuição: headroom dividido entre sessões ativas via SetChargingProfile\n"
            "4. Proteção: quando consumo ultrapassa 85% do limite, potência dos carregadores "
            "é reduzida automaticamente em até 70% para evitar ultrapassagem.\n"
            "Exemplo: loja com 200 kW contratados consumindo 160 kW (80%) deixa apenas "
            "40 kW para os carregadores. Com 4 sessões ativas, cada carro recebe até 10 kW."
        ),
        metadata={"fonte": "DSM_spec", "topico": "operacao"},
    ),
    Document(
        page_content=(
            "Tarifação Dinâmica em Eletropostos Comerciais\n\n"
            "O sistema ajusta automaticamente o preço por kWh com base em múltiplos fatores.\n"
            "Fatores de precificação:\n"
            "- Horário de pico: tarifa +30% entre 18h e 21h\n"
            "- Escassez de conectores: quanto menos vagas disponíveis, maior a tarifa\n"
            "- Tipo de carregador: DC Fast Charging cobra tarifa premium\n"
            "- Demanda da loja: alta ocupação elétrica eleva o preço para controlar demanda\n"
            "Referência de preços: R$ 2,20/kWh base | R$ 2,86/kWh horário de pico | "
            "R$ 3,30/kWh DC Fast. A tarifação dinâmica maximiza receita do operador "
            "respeitando os limites elétricos do estabelecimento."
        ),
        metadata={"fonte": "modelo_precificacao", "topico": "faturamento"},
    ),
    Document(
        page_content=(
            "Interoperabilidade de Hardware — Padrões Abertos\n\n"
            "O ChargeGrid Intelligence suporta carregadores de diferentes fabricantes "
            "por meio dos protocolos industriais abertos OCPP e MODBUS.\n"
            "Conectores suportados: Tipo 2 (IEC 62196), CCS2, CHAdeMO, GB/T.\n"
            "Fabricantes homologados no ecossistema OCPP 2.0.1: GoodWe EV Charger "
            "(parceiro principal FIAP EV Challenge 2026), ABB Terra, Schneider EVlink, "
            "Webasto Unite, Efacec QC45.\n"
            "Certificação OCA (Open Charge Alliance): qualquer carregador certificado OCPP "
            "opera com o CSMS do ChargeGrid Intelligence sem customizações adicionais."
        ),
        metadata={"fonte": "interoperabilidade", "topico": "hardware"},
    ),
]


# ---------------------------------------------------------------------------
# System Prompt — corrigido com escopo proibido e formato de saída (C1 Sprint 1)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
Você é a Inteligência Artificial Especialista em Gestão Comercial do sistema \
ChargeGrid Intelligence, módulo do Núcleo de IA do ecossistema GoodWe e FIAP. \
Seu usuário é o operador comercial responsável pela gestão de eletropostos em \
estabelecimentos como shoppings, supermercados e estacionamentos.

FUNÇÃO PRINCIPAL
Traduzir dados brutos de sessão de recarga em orientações diretas para o gestor, \
justificando faturamento e decisões autônomas do sistema.

DIRETRIZES OPERACIONAIS OBRIGATÓRIAS
- Faturamento: justifique tarifas com base na precificação dinâmica e na \
Resolução Normativa ANEEL nº 1.000/2021 (preços livremente negociados).
- Infraestrutura: explique que o sistema gerencia demanda de potência em tempo real, \
mantendo sincronia entre limites elétricos do hardware e lógica do software.
- Dados: fundamente análises na decodificação de eventos via OCPP (controladores) \
e MODBUS (medição física).
- Missão: prove que o sistema resolve a ausência de mecanismos integrados para \
orquestrar potência, registrar ciclos, faturar e comunicar.

ESCOPO PROIBIDO — recuse com clareza os seguintes tópicos:
- Questões pessoais, entretenimento ou assuntos sem relação com mobilidade elétrica
- Suporte técnico de hardware (falhas físicas, manutenção de equipamentos)
- Aconselhamento jurídico ou contábil além da orientação operacional padrão
- Dados de usuários finais (motoristas), privacidade ou LGPD
- Comparações comerciais com concorrentes do sistema ChargeGrid

FORMATO DE SAÍDA
Responda sempre em até 4 parágrafos curtos. Estruture assim:
1. Resposta direta à pergunta (1-2 frases)
2. Dado técnico ou regulatório que fundamenta a resposta
3. Ação que o sistema executou ou vai executar
4. Impacto financeiro ou operacional para o negócio do lojista (quando aplicável)

Tom: profissional, analítico, direto. Sem linguagem informal.

Quando disponível, utilize o contexto técnico entre <contexto_rag> e </contexto_rag> \
para fundamentar respostas com dados precisos.\
"""


# ---------------------------------------------------------------------------
# Few-shot examples — Sprint 1 test cases (C2)
# ---------------------------------------------------------------------------

FEW_SHOT = [
    {
        "role": "user",
        "content": (
            "A loja tá lotada hoje e o ar condicionado tá no máximo. "
            "Os carros carregando lá fora não vão derrubar a energia da loja não né?"
        ),
    },
    {
        "role": "assistant",
        "content": (
            "Não há risco de queda de energia na sua loja.\n\n"
            "O sistema realiza o gerenciamento inteligente de demanda de potência em tempo "
            "real via leitura do quadro elétrico pelo protocolo MODBUS a cada 15 segundos. "
            "Quando o consumo da loja ultrapassa 85% da demanda contratada, a potência "
            "entregue aos carregadores é reduzida automaticamente via SetChargingProfile (OCPP).\n\n"
            "Neste momento, o sistema já ajustou a distribuição de carga entre as sessões ativas "
            "para preservar o headroom elétrico da sua operação comercial.\n\n"
            "Resultado: proteção automática contra ultrapassagem de demanda, evitando multas "
            "de até 3x a tarifa normal por kW excedente na sua fatura de energia."
        ),
    },
    {
        "role": "user",
        "content": (
            "Como a loja tá cheia e a energia tá no limite, o sistema consegue cobrar "
            "mais caro de quem tá carregando o carro agora para compensar?"
        ),
    },
    {
        "role": "assistant",
        "content": (
            "Sim. O sistema aplica tarifação dinâmica automaticamente neste cenário.\n\n"
            "A Resolução Normativa ANEEL nº 1.000/2021 autoriza preços livremente negociados "
            "em eletropostos comerciais, sem tabelamento. O algoritmo de precificação eleva "
            "a tarifa quando a demanda elétrica disponível é baixa, controlando o consumo "
            "via preço e maximizando a eficiência operacional.\n\n"
            "A tarifa ajustada foi comunicada ao usuário final antes do início da sessão "
            "via integração com a API de pagamento, garantindo transparência na cobrança.\n\n"
            "Impacto para o seu negócio: receita por sessão aumentada no período de pico "
            "sem nenhuma intervenção manual da sua equipe."
        ),
    },
]

MAX_TURNS = 10  # mantém os últimos 10 turnos (pares user/assistant)


# ---------------------------------------------------------------------------
# Vectorstore (construído uma vez, injetado na classe)
# ---------------------------------------------------------------------------

def construir_vectorstore() -> FAISS:
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = splitter.split_documents(DOCUMENTOS)
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    return FAISS.from_documents(chunks, embeddings)


# ---------------------------------------------------------------------------
# Chatbot
# ---------------------------------------------------------------------------

class ChargeGridChatbot:
    """Assistente gerencial com memória de contexto, RAG e few-shot prompting."""

    def __init__(self, vectorstore: FAISS, modelo: str = "gpt-4o-mini", temperatura: float = 0.3):
        self.llm = ChatOpenAI(model=modelo, temperature=temperatura)
        self.vectorstore = vectorstore
        self.historico: list[dict] = []

    def _recuperar_contexto(self, pergunta: str, k: int = 3) -> str:
        docs = self.vectorstore.similarity_search(pergunta, k=k)
        return "\n\n".join(d.page_content for d in docs)

    def _montar_mensagens(self, pergunta: str) -> list:
        contexto_rag = self._recuperar_contexto(pergunta)

        system_content = SYSTEM_PROMPT
        if contexto_rag:
            system_content += f"\n\n<contexto_rag>\n{contexto_rag}\n</contexto_rag>"

        mensagens = [SystemMessage(content=system_content)]

        for ex in FEW_SHOT:
            cls = HumanMessage if ex["role"] == "user" else AIMessage
            mensagens.append(cls(content=ex["content"]))

        historico_recente = self.historico[-(MAX_TURNS * 2):]
        for msg in historico_recente:
            cls = HumanMessage if msg["role"] == "user" else AIMessage
            mensagens.append(cls(content=msg["content"]))

        mensagens.append(HumanMessage(content=pergunta))
        return mensagens

    def conversar(self, pergunta: str) -> str:
        mensagens = self._montar_mensagens(pergunta)
        resposta = self.llm.invoke(mensagens)
        texto = resposta.content

        self.historico.append({"role": "user", "content": pergunta})
        self.historico.append({"role": "assistant", "content": texto})

        return texto

    def resetar(self) -> None:
        self.historico.clear()
        print("Histórico resetado.")


# ---------------------------------------------------------------------------
# Interface de linha de comando
# ---------------------------------------------------------------------------

def main() -> None:
    carregar_api_key()
    vectorstore = construir_vectorstore()
    bot = ChargeGridChatbot(vectorstore=vectorstore)

    print("=" * 62)
    print(" ChargeGrid Intelligence — Assistente Gerencial")
    print(" EV Challenge 2026 | GoodWe x FIAP")
    print("=" * 62)
    print(" 'sair'  → encerra  |  'reset' → limpa o histórico")
    print("=" * 62)

    while True:
        try:
            entrada = input("\nOperador: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSistema encerrado.")
            break

        if not entrada:
            continue
        if entrada.lower() == "sair":
            print("Sistema encerrado.")
            break
        if entrada.lower() == "reset":
            bot.resetar()
            continue

        resposta = bot.conversar(entrada)
        print(f"\nChargeGrid: {resposta}")


if __name__ == "__main__":
    main()
