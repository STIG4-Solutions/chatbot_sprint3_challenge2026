"""
Moderação de entrada: subversão de instruções e domínios de profissional habilitado.

Duas famílias de ameaça são tratadas antes de qualquer chamada ao modelo:

1. Subversão das instruções: jailbreak (pedir que o assistente abandone as
   regras, assuma outra persona ou opere em "modo" irrestrito) e injeção de
   prompt (instruções plantadas no texto do usuário se passando por comando do
   sistema, ou tentativa de fechar as marcas XML do system prompt).

2. Domínios que exigem profissional habilitado. orientação jurídica, financeira
   e de segurança elétrica. Aqui não se trata de assunto proibido: o assunto é
   legítimo na operação de um eletroposto, mas a responsabilidade técnica ou
   profissional não é do assistente. A recusa, portanto, sempre encaminha.

Interceptar na entrada, e não confiar apenas na instrução do prompt, é o que
torna a recusa determinística: não depende de o modelo resistir à insistência.
"""

from __future__ import annotations

import re
import unicodedata

from src.guardrails import CategoriaBloqueio, Veredito, montar_recusa


# ---------------------------------------------------------------------------
# Normalização
# ---------------------------------------------------------------------------

def normalizar(texto: str) -> str:
    """Reduz o texto a minúsculas sem acentuação e com espaçamento colapsado.

    Impede que variação de acento, caixa ou espaçamento contorne os padrões:
    "ignóre   as  INSTRUÇÕES" e "ignore as instrucoes" colidem na mesma forma.
    """
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento.lower()).strip()


def _compilar(padroes: list[str]) -> list[re.Pattern]:
    return [re.compile(p) for p in padroes]


# ---------------------------------------------------------------------------
# Padrões de subversão de instruções
# ---------------------------------------------------------------------------

PADROES_JAILBREAK = _compilar([
    r"\b(ignore|ignora|esqueca|desconsidere|apague|descarte)\b.{0,40}\b(instrucoes|regras|diretrizes|orientacoes|prompt|system|contexto anterior)\b",
    r"\b(voce agora e|a partir de agora voce e|de agora em diante voce e|assuma que voce e)\b",
    r"\b(aja|atue|comporte-se|finja|simule|pretenda)\b.{0,30}\b(como se|que voce|sem (as )?(regras|restricoes|limites|filtros))\b",
    r"\bmodo\b.{0,15}\b(desenvolvedor|developer|irrestrito|livre|sem filtro|sem restricao|deus|god)\b",
    r"\b(dan|do anything now|jailbreak)\b",
    r"\b(sem|nenhuma?)\b.{0,15}\b(restricoes|censura|filtros|limitacoes)\b",
    r"\b(revele|mostre|imprima|repita|exiba|me diga)\b.{0,40}\b(system prompt|prompt de sistema|suas instrucoes|as instrucoes acima|seu prompt)\b",
    r"\bresponda\b.{0,30}\bsem (seguir|aplicar|obedecer)\b",
])

PADROES_INJECAO = _compilar([
    r"</?(seguranca|escopo_proibido|escopo_permitido|papel|diretrizes|formato_saida|system)>",
    r"<\|.{0,20}\|>",
    r"^\s*(system|sistema|assistant|assistente)\s*:",
    r"\b(nova|atualizacao da|correcao da)\s+(instrucao|diretriz|regra|politica)\b\s*:",
    r"\bas instrucoes (acima|anteriores)\b.{0,40}\b(estao )?(desatualizadas|canceladas|invalidas|revogadas)\b",
    r"\b(este|esse) (documento|texto|trecho|arquivo)\b.{0,40}\b(substitui|sobrepoe|tem precedencia)\b",
])


# ---------------------------------------------------------------------------
# Padrões de domínio com profissional habilitado
# ---------------------------------------------------------------------------
# A operação de eletropostos usa vocabulário que colide com os três domínios:
# "demanda contratada" é termo tarifário, não contratual; "custo" e "receita" são
# grandezas de faturamento, não recomendação de investimento; "carregador" e
# "potência" são operacionais, não intervenção elétrica. Os padrões abaixo são
# deliberadamente específicos, e as expressões operacionais ficam protegidas em
# `EXPRESSOES_OPERACIONAIS`.

EXPRESSOES_OPERACIONAIS = _compilar([
    r"\b(demanda|potencia|carga|tarifa)\s+contratad[ao]\b",
    r"\bcontrato de (demanda|fornecimento|energia)\b",
])

PADROES_JURIDICO = _compilar([
    r"\b(advogad[oa]|jurisprudencia|peticao|liminar|processo judicial|acao judicial|tribunal|juiz)\b",
    r"\b(posso ser processad|me processar|entrar na justica|abrir um processo)\w*\b",
    r"\b(clausula|rescisao|aditivo)\b.{0,30}\bcontrat\w*\b",
    r"\bcontrat\w*\b.{0,30}\b(clausula|rescisao|nulidade|litigio)\b",
    r"\b(indenizacao|dano moral|responsabilidade civil)\b",
    r"\b(redija|escreva|elabore)\b.{0,30}\b(contrato|notificacao extrajudicial|parecer juridico)\b",
])

PADROES_FINANCEIRO = _compilar([
    r"\b(vale a pena|devo|compensa)\b.{0,30}\b(investir|financiar|comprar acoes|aplicar)\b",
    r"\b(investimento|financiamento|emprestimo|capital de giro|leasing)\b.{0,30}\b(recomend|indic|suger|melhor|qual)\w*\b",
    r"\b(recomend|indic|suger|qual|melhor)\w*\b.{0,30}\b(investimento|financiamento|emprestimo|leasing|fundo|acoes)\b",
    r"\b(regime tributario|simples nacional|lucro presumido|lucro real|elisao fiscal|planejamento tributario)\b",
    r"\b(como (declarar|deduzir)|qual (imposto|aliquota|tributo))\b",
    r"\b(abrir|constituir)\b.{0,20}\b(empresa|cnpj|holding)\b",
])

PADROES_SEGURANCA_ELETRICA = _compilar([
    r"\b(posso|como|devo)\b.{0,40}\b(trocar|instalar|ligar|religar|mexer|abrir|desligar|substituir)\b.{0,40}\b(disjuntor|quadro|barramento|cabeamento|fiacao|aterramento|padrao de entrada|transformador|contator)\b",
    r"\b(mexer|intervir|trabalhar)\b.{0,30}\b(energizad|sob tensao|no quadro eletrico)\w*\b",
    r"\b(fazer|executar) a instalacao\b.{0,30}\b(eu mesmo|por conta propria|sozinho)\b",
    r"\b(bitola|secao) (do|de) cabo\b.{0,30}\b(uso|utilizo|devo|qual)\b",
    r"\b(aumentar|forcar|burlar)\b.{0,30}\b(limite|protecao|disjuntor)\b",
])


# ---------------------------------------------------------------------------
# Respostas padronizadas
# ---------------------------------------------------------------------------

RECUSAS = {
    CategoriaBloqueio.JAILBREAK: (
        "Não atendo a pedidos para suspender, reescrever ou revelar as instruções "
        "que regem este assistente.",
        "As diretrizes operacionais do ChargeGrid Intelligence têm precedência sobre "
        "instruções recebidas durante a conversa e não são negociáveis em tempo de execução.",
        "Nenhuma consulta foi encaminhada ao modelo. Posso seguir com gestão de demanda, "
        "faturamento, dados OCPP/MODBUS, base regulatória ou interoperabilidade.",
    ),
    CategoriaBloqueio.INJECAO_DE_PROMPT: (
        "Não aceito instruções embutidas no texto enviado: elas foram tratadas como "
        "conteúdo a ser analisado e descartadas.",
        "Comandos de sistema só são aceitos pela configuração do próprio serviço. Texto "
        "colado na conversa é sempre material a ser analisado.",
        "A instrução embutida foi descartada. Reformule a pergunta e eu sigo com a análise "
        "operacional dentro do escopo.",
    ),
    CategoriaBloqueio.ACONSELHAMENTO_JURIDICO: (
        "Não emito parecer jurídico nem interpretação de contrato.",
        "Posso expor o dispositivo regulatório aplicável e seu efeito operacional. A "
        "Resolução Normativa ANEEL nº 1.000/2021, por exemplo, classifica a recarga "
        "comercial como serviço de valor adicionado com preços livremente negociados. "
        "mas a leitura jurídica do caso concreto é atribuição de advogado.",
        "Encaminhe a questão ao advogado ou ao departamento jurídico do estabelecimento. "
        "Aqui, posso detalhar o enquadramento regulatório e o registro das sessões que "
        "servirá de evidência.",
    ),
    CategoriaBloqueio.ACONSELHAMENTO_FINANCEIRO: (
        "Não faço recomendação de investimento, financiamento ou estrutura tributária.",
        "Posso apurar os números da operação, como receita por sessão, custo de energia "
        "e efeito da tarifação dinâmica sobre a margem, mas decisão de alocação de capital "
        "e tratamento fiscal dependem de análise contábil do estabelecimento.",
        "Encaminhe a decisão ao contador ou consultor financeiro habilitado. Posso gerar "
        "o relatório de receita e consumo que sustenta essa análise.",
    ),
    CategoriaBloqueio.SEGURANCA_ELETRICA: (
        "Não oriento intervenção física em instalação, quadro, cabeamento ou equipamento "
        "energizado.",
        "Intervenção em instalação elétrica exige projeto e execução sob responsabilidade "
        "técnica registrada, conforme a regulamentação aplicável a serviços em eletricidade.",
        "Acione eletricista ou engenheiro eletricista habilitado. Posso descrever o "
        "comportamento do sistema, a leitura atual do ponto de entrega e os limites que o "
        "gerenciamento de demanda está aplicando.",
    ),
}


# ---------------------------------------------------------------------------
# Avaliação
# ---------------------------------------------------------------------------

_GRUPOS = [
    (CategoriaBloqueio.INJECAO_DE_PROMPT, PADROES_INJECAO),
    (CategoriaBloqueio.JAILBREAK, PADROES_JAILBREAK),
    (CategoriaBloqueio.SEGURANCA_ELETRICA, PADROES_SEGURANCA_ELETRICA),
    (CategoriaBloqueio.ACONSELHAMENTO_JURIDICO, PADROES_JURIDICO),
    (CategoriaBloqueio.ACONSELHAMENTO_FINANCEIRO, PADROES_FINANCEIRO),
]


def _protegido_por_vocabulario_operacional(texto: str, inicio: int, fim: int) -> bool:
    """Evita falso positivo quando o trecho casado é termo técnico do domínio."""
    for padrao in EXPRESSOES_OPERACIONAIS:
        for ocorrencia in padrao.finditer(texto):
            if ocorrencia.start() <= inicio and ocorrencia.end() >= fim:
                return True
    return False


def avaliar_entrada(pergunta: str) -> Veredito:
    """Inspeciona a pergunta do operador antes de qualquer chamada ao modelo."""
    texto = normalizar(pergunta)
    if not texto:
        return Veredito.liberado()

    for categoria, padroes in _GRUPOS:
        for padrao in padroes:
            ocorrencia = padrao.search(texto)
            if not ocorrencia:
                continue
            if _protegido_por_vocabulario_operacional(texto, ocorrencia.start(), ocorrencia.end()):
                continue
            direta, fundamento, acao = RECUSAS[categoria]
            return Veredito(
                bloqueado=True,
                categoria=categoria,
                motivo=direta,
                gatilho=ocorrencia.group(0),
                resposta=montar_recusa(categoria, direta, fundamento, acao),
            )

    return Veredito.liberado()
