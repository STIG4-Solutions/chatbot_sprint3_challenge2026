"""
Consolidação de múltiplas execuções do conjunto de avaliação.

Uma passada isolada não sustenta a tabela de comparativo antes/depois: o
endpoint gerenciado não é determinístico, e a diferença entre duas arquiteturas
só é atribuível ao desenho se for maior do que a variação entre execuções da
mesma arquitetura. Este módulo consolida N passadas em média, mínimo e máximo
por métrica, e mantém o resultado de cada passada no arquivo final.
"""

from __future__ import annotations

from statistics import pstdev

METRICAS_CONSOLIDADAS = (
    "nota_media",
    "taxa_acerto_de_escopo",
    "acuracia_structured_output",
    "tokens_por_turno",
    "tokens_por_turno_com_inferencia",
    "latencia_media_segundos",
    "latencia_media_com_inferencia",
    "adequadas",
    "parcialmente_adequadas",
    "inadequadas",
    "casos_interceptados",
)


def consolidar(passadas: list[dict]) -> dict:
    """Agrega os resumos das passadas em estatísticas por métrica."""
    consolidado = {}
    for metrica in METRICAS_CONSOLIDADAS:
        valores = [passada["resumo"][metrica] for passada in passadas if metrica in passada["resumo"]]
        if not valores:
            continue
        consolidado[metrica] = {
            "media": round(sum(valores) / len(valores), 2),
            "minimo": round(min(valores), 2),
            "maximo": round(max(valores), 2),
            "desvio_padrao": round(pstdev(valores), 2) if len(valores) > 1 else 0.0,
        }
    return consolidado


def notas_por_caso(passadas: list[dict]) -> list[dict]:
    """Nota média de cada caso ao longo das passadas, para leitura caso a caso."""
    indice: dict[int, list[dict]] = {}
    for passada in passadas:
        for caso in passada["casos"]:
            indice.setdefault(caso["id"], []).append(caso)

    consolidado = []
    for identificador, ocorrencias in sorted(indice.items()):
        notas = [ocorrencia["nota"] for ocorrencia in ocorrencias]
        consolidado.append({
            "id": identificador,
            "classe": ocorrencias[0]["classe"],
            "categoria": ocorrencias[0]["categoria"],
            "pergunta": ocorrencias[0]["pergunta"],
            "nota_media": round(sum(notas) / len(notas), 1),
            "nota_minima": min(notas),
            "nota_maxima": max(notas),
            "acertos_de_escopo": f"{sum(o['acerto_de_escopo'] for o in ocorrencias)}/{len(ocorrencias)}",
            "saida_valida": f"{sum(o['saida_valida'] for o in ocorrencias)}/{len(ocorrencias)}",
            "avaliacao_modal": max(
                {o["avaliacao"] for o in ocorrencias},
                key=lambda rotulo: sum(1 for o in ocorrencias if o["avaliacao"] == rotulo),
            ),
            "resposta_ultima_passada": ocorrencias[-1]["resposta"],
        })
    return consolidado
