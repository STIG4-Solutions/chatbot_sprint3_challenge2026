# System prompt: controle de versões

Cada versão é um arquivo próprio neste diretório, comparável em diff e carregado
em tempo de execução por `src/chain/builder.py`. A versão de produção é a **v3**.

## Como o ganho foi medido

Todas as linhas da tabela vêm da execução do mesmo conjunto de avaliação
(`evals/eval_set.json`, 15 casos), no mesmo modelo (`gpt-oss:120b`), com os
mesmos parâmetros de geração, **três passadas por versão**, reportando a média.

A medição por versão de prompt é feita com a **camada de guardrails desligada**:

```bash
python -m evals.run_eval --apenas lcel --prompt vN --sem-guardrails --repeticoes 3
```

Com a camada ligada, mais da metade dos casos é interceptada de forma idêntica em
qualquer versão, e a tabela mediria a camada, não o prompt. A última linha mostra
a configuração de produção, ou seja, o prompt v3 **com** a camada, para dimensionar
a contribuição de cada parte.

O endpoint gerenciado não é determinístico nem com `temperature=0` e `seed` fixa,
por isso a coluna de desvio padrão entre passadas é reportada: só diferenças
maiores que ela são atribuíveis à mudança de versão.

## Tabela de versões

| Versão | O que mudou | Por quê | Nota (σ) | Acerto de escopo | Structured output | Tokens/turno |
|---|---|---|---|---|---|---|
| **v1** | Porte fiel do prompt entregue na Sprint 2: papel, função, diretrizes, escopo proibido e formato de quatro parágrafos, tudo em texto corrido | Estabelecer o ponto de partida. Sem baseline medido no mesmo modelo, nenhuma mudança posterior pode ser atribuída ao prompt | 69,5 (±1,2) | 80,0% | 0% | 856 |
| **v2** | Reestruturação integral em XML tagging: `<papel>`, `<objetivo>`, `<escopo_permitido>`, `<escopo_proibido>`, `<diretrizes>`, `<formato_saida>`, `<tom>`, `<uso_do_contexto>` | Delimitar as seções para que a instrução de escopo deixe de competir por atenção com o restante do texto | 67,9 (±2,8) | 77,8% | 0% | 1.006 |
| **v3** | Bloco `<seguranca>` com precedência declarada, regras de recusa de jailbreak e injeção, proibição de afirmar especificação ausente da base e encaminhamento obrigatório a profissional habilitado. Contrato de saída em JSON com `{format_instructions}` do schema Pydantic. Teto de 320 caracteres por campo | Tornar a saída verificável por máquina e explicitar as regras que a v2 deixara implícitas | 81,1 (±4,5) | 86,7% | **100%** | 2.484 |
| **v3 + guardrails** *(produção)* | Mesmo prompt v3, com a camada determinística de `src/guardrails/` ativa | Instrução em linguagem natural é persuasível; a recusa que não pode falhar precisa ser código | **96,1 (±2,4)** | **97,8%** | **100%** | 1.257 |

## Leitura dos resultados

**A reestruturação em XML, sozinha, não produziu ganho mensurável.** A v2 ficou
1,5 ponto abaixo da v1, diferença menor que o desvio entre passadas da própria v2
(±2,8). O acerto de escopo também não se moveu de forma significativa, de 80,0%
para 77,8%. Organizar a instrução em blocos nomeados tornou o prompt mais legível
para quem o mantém, mas não o tornou mais obedecido: as regras de recusa
continuavam sendo uma lista de tópicos entre outras, sem precedência declarada
sobre o que chegasse na conversa. A v2 foi mantida no repositório justamente por
isso, pois é a evidência de que o ganho da v3 não vem da formatação.

**O ganho da v3 é real e está concentrado no contrato de saída.** A nota sobe
11,6 pontos sobre a v1, acima do desvio de ambas, e a saída válida vai de 0% para
100%: a resposta deixou de ser texto a ser lido e passou a ser objeto validado
contra `ConsultaRecarga`. O acerto de escopo melhora de 80,0% para 86,7%, o que
mostra que declarar `<seguranca>` com precedência ajuda, mas não resolve. O custo
em tokens mais que dobra, de 1.006 para 2.484, porque o `{format_instructions}`
injeta o schema inteiro no prompt.

**O que fechou o escopo foi a camada determinística, e ela sai mais barata.** Com
os guardrails ativos o acerto vai a 97,8% e a nota a 96,1, com 15 pontos de ganho
sobre a v3 isolada. O detalhe contraintuitivo é o custo: os tokens por turno caem
de 2.484 para 1.257 e a latência de 2,71 s para 1,35 s, porque 8 dos 15 casos são
interceptados antes de qualquer chamada ao modelo. O guardrail é, ao mesmo tempo,
a garantia de segurança e a maior economia do sistema.

**Conclusão de engenharia.** O prompt versionado resolve o que é contrato de
formato; o que é regra inegociável pertence ao código. A v3 permanece necessária,
pois é ela que produz o JSON validável e orienta o tom das respostas legítimas,
mas sozinha não sustenta a exigência de recusa do §6.3.

## Observação sobre a v1

A v1 é transcrição literal do system prompt entregue na Sprint 2, preservada
caractere a caractere, inclusive na pontuação. Ela é comparável linha a linha com
a constante `SYSTEM_PROMPT` de `legacy/chatbot_sprint2.py`, e qualquer alteração
de redação invalidaria a sua função de baseline.

## Reprodução

```bash
# Ganho por versão de prompt, isolado da camada de guardrails
python -m evals.run_eval --apenas lcel --prompt v1 --sem-guardrails --repeticoes 3
python -m evals.run_eval --apenas lcel --prompt v2 --sem-guardrails --repeticoes 3
python -m evals.run_eval --apenas lcel --prompt v3 --sem-guardrails --repeticoes 3

# Configuração de produção (prompt v3 com guardrails) e baseline das Sprints 1 e 2
python -m evals.run_eval --repeticoes 3
```

Resultados brutos de cada execução em `evals/sprint3_results*.json` e
`evals/sprint2_baseline.json`, com as passadas individuais preservadas.
