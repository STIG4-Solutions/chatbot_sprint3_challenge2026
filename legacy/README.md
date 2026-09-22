# `legacy/`: núcleo conversacional das Sprints 1 e 2

Esta pasta preserva, **sem qualquer alteração**, o núcleo conversacional entregue
nas Sprints 1 e 2 do EV Challenge 2026.

| Arquivo | Descrição |
|---|---|
| `chatbot_sprint2.py` | Implementação manual: montagem de mensagens em lista Python, histórico controlado por fatiamento de lista, saída em texto livre. |
| `ChargeGrid_Intelligence_Sprint2.ipynb` | Notebook de demonstração interativa da Sprint 2. |
| `arquitetura_sprint2.png` | Diagrama de arquitetura publicado na Sprint 2. |

## Por que o código legado permanece no repositório

O item §8.3 do escopo da Sprint 3 exige uma **tabela de comparativo antes/depois**
entre a versão manual e a versão refatorada em LCEL. Manter o legado versionado e
executável torna esse comparativo **reproduzível por terceiros**: o mesmo conjunto de
avaliação (`evals/eval_set.json`) é executado sobre as duas arquiteturas, e os números
publicados no relatório podem ser reconstruídos a partir deste repositório.

O arquivo `chatbot_sprint2.py` é tratado como **registro histórico imutável**. A
execução do baseline não o modifica: o adaptador `evals/legacy_adapter.py` importa dele
o system prompt, os exemplos few-shot e a base de conhecimento, e reproduz a montagem
manual de mensagens tal como estava, substituindo apenas o cliente de inferência, para
que legado e refactory sejam medidos sob o mesmo modelo e a arquitetura permaneça como
única variável do experimento.

## Histórico Git

O histórico de commits das Sprints 1 e 2 foi preservado integralmente neste repositório.
A separação por sprint é organizacional: cada entrega tem o seu repositório público,
e a continuidade do projeto é verificável em `git log`.
