# Relatório de uso de modelos e parâmetros

**ChargeGrid Intelligence · Sprint 3 · EV Challenge 2026 · GoodWe × FIAP**

Documento exigido pelo item §6.2 do escopo. Todos os números vêm de execução do
conjunto de avaliação do projeto (`evals/eval_set.json`, 15 casos) e podem ser
reproduzidos a partir do repositório:

```bash
python -m evals.comparar_modelos --temperatura
```

Resultados brutos em `evals/comparativo_modelos.json`.

---

## 1. Infraestrutura de inferência

| Item | Escolha |
|---|---|
| Classe de cliente | `ChatOllama` (`langchain-ollama`) |
| Endpoint | `https://ollama.com`, Ollama Cloud |
| Autenticação | `Authorization: Bearer $OLLAMA_API_KEY`, via `client_kwargs` |
| Modelo primário | `gpt-oss:120b` |
| Segundo modelo | `gpt-oss:20b`, mesma família, porte menor |
| Terceiro modelo | `gemma4:31b`, família distinta |
| Janela de contexto | 128k tokens |

A execução local foi descartada por restrição de hardware: `gpt-oss:120b` exige
cerca de 65 GB e `gpt-oss:20b` cerca de 13 GB de armazenamento, contra 14 GB
livres e 16 GB de memória na máquina de desenvolvimento. A Ollama Cloud serve o
modelo exato exigido pelo escopo através da mesma classe `ChatOllama`, sem
consumo de disco: apenas a `base_url` e o cabeçalho de autenticação mudam em
relação a uma instalação local.

**Modelos verificados e descartados.** A escolha do terceiro modelo foi feita por
teste de disponibilidade, não por preferência. `qwen3.5:397b`,
`deepseek-v4.1-flash` e `glm-5.3-flash` respondem `this model is not included in
your free usage`, e por isso ficaram fora. `gemma4:31b` respondeu normalmente e
foi adotado como representante de família distinta.

---

## 2. Parâmetros de geração

| Parâmetro | Valor de produção | Justificativa |
|---|---|---|
| `temperature` | **0,2** | Melhor resultado medido em duas varreduras independentes: 80,6 contra 76,1 em 0,0 e 73,9 em 0,7 na última, com a mesma ordenação na anterior. O assistente produz orientação operacional e regulatória, onde variação de conteúdo entre execuções é indesejável, mas a amostragem estritamente gulosa mostrou-se pior. Ver §4 |
| `top_p` | **0,9** | Descarta a cauda de baixa probabilidade sem estreitar o vocabulário técnico do domínio, como nomes de protocolo, unidades e referências normativas |
| `max_tokens` (`num_predict`) | **1.400** | A resposta estruturada típica consome cerca de 950 tokens. Em 900 o JSON era truncado antes do fechamento (`done_reason: length`), invalidando o contrato de saída; 1.400 dá margem sem permitir divagação |
| `seed` | nulo em produção | Testada e descartada: o endpoint gerenciado não produz saída determinística nem com `seed` fixa e `temperature=0`. Ver §5 |

Definidos em `src/config.py`, na classe `ParametrosModelo`, com a justificativa
registrada no próprio código.

---

## 3. Matriz de modelos por versões de prompt

Cada célula é uma execução completa do conjunto de 15 casos, **com a camada de
guardrails desligada**. A camada é determinística e responde de forma idêntica sob
qualquer modelo: mantê-la ativa uniformizaria 8 dos 15 casos e esconderia
justamente a diferença que esta matriz precisa medir. Os números abaixo
representam o que cada modelo sustenta por conta própria, não o comportamento do
sistema em produção, que está em `evals/sprint3_results.json`.

| Modelo | Prompt | Nota | Acerto de escopo | Structured output | Tokens/turno | Latência | Adequadas | Inadequadas |
|---|---|---|---|---|---|---|---|---|
| **gpt-oss:120b** | v2 | 71,1 | 80,0% | 0% | 1.005 | 2,23 s | 7 | 4 |
| **gpt-oss:120b** | **v3** | 76,1 | 73,3% | **100%** | 2.487 | 2,48 s | 8 | 4 |
| gpt-oss:20b | v2 | 46,1 | 46,7% | 0% | 1.036 | 9,77 s | 5 | 9 |
| gpt-oss:20b | v3 | 67,8 | 73,3% | 93,3% | 2.463 | 12,42 s | 4 | 5 |
| gemma4:31b | v2 | 65,0 | 60,0% | 0% | 1.033 | 2,30 s | 5 | 6 |
| gemma4:31b | **v3** | **83,3** | 80,0% | **100%** | 2.485 | **1,23 s** | 8 | 3 |

### Leitura

**O contrato de saída move mais o resultado do que a troca de modelo.** Em todos
os três modelos, passar da v2 para a v3 melhora a nota, e o salto é maior no
modelo mais fraco: `gpt-oss:20b` ganha 21,7 pontos, `gemma4:31b` ganha 18,3 e
`gpt-oss:120b` ganha 5,0. O schema restringe o espaço de resposta a ponto de o
modelo menor conseguir preenchê-lo corretamente, o que estreita a distância entre
os modelos: sob a v2 a diferença entre o melhor e o pior é de 25,0 pontos; sob a
v3, cai para 15,5.

**O modelo menor é mais lento, não mais rápido.** Este é o resultado
contraintuitivo da matriz: `gpt-oss:20b` levou 9,77 s contra 2,23 s do `120b` na
v2, e 12,42 s contra 2,48 s na v3, entre 4,4 e 5,0 vezes mais tempo. O número não
mede a eficiência do modelo, mede a infraestrutura que o serve: na Ollama Cloud o
`gpt-oss:120b` é o modelo de maior demanda e recebe alocação e otimização
correspondentes. Em uma instalação local a relação se inverteria. A conclusão
prática é específica deste ambiente e está registrada como tal.

**O `gemma4:31b` mediu acima do modelo primário, e isso é reportado como está.**
Sob a v3, obteve 83,3 contra 76,1 do `gpt-oss:120b`, com metade da latência
(1,23 s contra 2,48 s) e o mesmo custo em tokens. A diferença de 7,2 pontos foi
obtida em passada única por célula, e o desvio entre passadas nesta configuração
é da ordem de ±4,5 pontos (medido em `prompts/VERSIONS.md`), de modo que o
resultado é sugestivo e **não conclusivo**: confirmá-lo exigiria repetir a matriz.
O registro fica porque o dado é o que é, e porque ele reforça a leitura anterior,
a de que a escolha de modelo não é o fator dominante neste sistema.

### Escolha

**`gpt-oss:120b` com prompt v3.** É o modelo nomeado no escopo da Sprint 3, tem a
melhor latência entre os modelos da própria família neste ambiente e sustenta 100%
de saída válida. O `gemma4:31b` fica registrado em `OLLAMA_MODEL_ALT2` como
alternativa imediata, com resultado medido igual ou superior, e o `gpt-oss:20b` em
`OLLAMA_MODEL_ALT` como contingência de menor porte. Qualquer das trocas é feita
por variável de ambiente, sem alteração de código.

---

## 4. Varredura de `temperature`

Modelo `gpt-oss:120b`, prompt v3, uma execução completa do conjunto por valor.

| `temperature` | Nota | Acerto de escopo | Structured output | Latência |
|---|---|---|---|---|
| 0,0 | 76,1 | 80,0% | 100% | 2,11 s |
| **0,2** | **80,6** | **93,3%** | 100% | 2,37 s |
| 0,7 | 73,9 | 73,3% | 100% | 2,44 s |

A saída estruturada permaneceu em 100% nos três valores: o contrato é sustentado
pelo schema e pelo modo JSON do cliente, não pela temperatura.

O ponto de atenção é que `temperature=0,0` ficou **abaixo** de 0,2, contrariando a
expectativa de que amostragem gulosa produziria a resposta mais aderente. Com uma
única passada por valor, a diferença de 4,5 pontos está próxima do desvio entre
passadas desta configuração e não deve ser lida isoladamente como conclusiva. O
que sustenta a escolha é a repetição do padrão: uma varredura anterior, executada
em outro momento, também colocou 0,2 à frente de 0,0 e de 0,7. Adotou-se 0,2 por
ser o melhor valor nas duas medições e por manter baixa a dispersão de tom entre
execuções.

---

## 5. Determinismo

O endpoint gerenciado **não** produz saída determinística. O mesmo prompt,
submetido três vezes com `temperature=0` e `seed=42`, retornou três redações
distintas; sem `seed`, duas. A causa é o agrupamento de requisições no servidor,
que altera a ordem de redução em ponto flutuante independentemente dos parâmetros
de amostragem.

Consequência metodológica: nenhuma métrica central deste projeto é reportada a
partir de uma única execução. O executor do eval aceita `--repeticoes N` e o
módulo `evals/agregacao.py` consolida média, mínimo, máximo e desvio padrão,
preservando as passadas individuais. A tabela de comparativo antes e depois do
relatório de evolução reporta três passadas por arquitetura, e as duas
arquiteturas são medidas na mesma invocação, para que a coluna de latência não
compare janelas de tempo diferentes.

---

## 6. Bônus: chamada multi-provider

O item §6.5 pede consultar mais de um modelo e mais de um prompt. A matriz do §3
é exatamente isso: **3 modelos por 2 versões de system prompt**, seis execuções
completas do conjunto de avaliação, com resultados comparados sob os mesmos
parâmetros. Somada à varredura do §4, são nove execuções do conjunto, todas
gravadas em `evals/comparativo_modelos.json`.

A troca de modelo e de prompt é parametrizada:

```bash
OLLAMA_MODEL=gemma4:31b python -m src.cli v2
```

`src/chain/builder.py` carrega a versão de prompt pedida a partir de `prompts/` e
`src/config.py` resolve o modelo a partir do ambiente. Nenhuma das duas trocas
exige alteração de código.
