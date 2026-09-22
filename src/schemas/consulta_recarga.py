"""
Schema de saída estruturada do domínio de recarga veicular, em Pydantic v2.

O núcleo das Sprints 1 e 2 devolvia texto livre: o formato de quatro parágrafos
definido no system prompt era uma convenção textual, não um contrato verificável.
Qualquer desvio só era detectável por leitura humana.

`ConsultaRecarga` transforma esse formato em contrato de dados. Cada parágrafo
vira um campo obrigatório, e as grandezas operacionais citadas pelo assistente
(potência, headroom, tarifa, estado do conector) passam a ser validadas contra os
limites físicos e comerciais do domínio antes de chegar ao operador.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

# Limites do domínio -------------------------------------------------------
# Potência: carregadores DC de alta potência homologados no ecossistema OCPP
# chegam a 350 kW; acima disso a leitura é ruído de medição ou alucinação.
POTENCIA_MAXIMA_KW = 350.0

# Tarifa: a faixa praticada em eletropostos comerciais brasileiros vai de
# R$ 1,00/kWh (AC lento fora de pico) a R$ 10,00/kWh (teto defensivo). A
# Resolução Normativa ANEEL nº 1.000/2021 não tabela preço, mas valores fora
# desta faixa indicam erro de unidade ou número inventado.
TARIFA_MINIMA_REAIS_KWH = 1.00
TARIFA_MAXIMA_REAIS_KWH = 10.00


class EstadoConector(str, Enum):
    """Estados de conector definidos pelo `StatusNotification` do OCPP 1.6/2.0.1."""

    DISPONIVEL = "Available"
    PREPARANDO = "Preparing"
    CARREGANDO = "Charging"
    SUSPENSO_EV = "SuspendedEV"
    SUSPENSO_EVSE = "SuspendedEVSE"
    FINALIZANDO = "Finishing"
    RESERVADO = "Reserved"
    INDISPONIVEL = "Unavailable"
    FALHA = "Faulted"


class CategoriaConsulta(str, Enum):
    """Taxonomia das consultas do operador comercial, herdada da matriz de
    testes das Sprints 1 e 2 e estendida com as categorias de recusa."""

    CONTROLE_DEMANDA = "controle_demanda"
    FATURAMENTO = "faturamento"
    REGULATORIO = "regulatorio"
    DADOS_OPERACIONAIS = "dados_operacionais"
    INTEROPERABILIDADE = "interoperabilidade"
    FORA_DE_ESCOPO = "fora_de_escopo"
    RECUSA_DOMINIO = "recusa_dominio"


CATEGORIAS_DE_RECUSA = {
    CategoriaConsulta.FORA_DE_ESCOPO,
    CategoriaConsulta.RECUSA_DOMINIO,
}


class ConsultaRecarga(BaseModel):
    """Resposta estruturada do ChargeGrid Intelligence a uma consulta do operador."""

    resposta_direta: str = Field(
        description="Resposta objetiva à pergunta, em uma ou duas frases."
    )
    fundamentacao_tecnica: str = Field(
        description=(
            "Dado técnico, operacional ou regulatório que sustenta a resposta "
            "(OCPP, MODBUS, algoritmo de gerenciamento de demanda, ANEEL)."
        )
    )
    acao_do_sistema: str = Field(
        description="Ação que o ChargeGrid executou ou executará em consequência."
    )
    impacto_no_negocio: str | None = Field(
        default=None,
        description=(
            "Impacto financeiro ou operacional para o estabelecimento. "
            "Deve ser nulo quando a consulta é recusada."
        ),
    )

    categoria: CategoriaConsulta = Field(
        description="Categoria da consulta segundo a taxonomia do projeto."
    )
    dentro_do_escopo: bool = Field(
        description="Falso quando a consulta foi recusada por escopo ou por domínio."
    )

    estado_conector: EstadoConector | None = Field(
        default=None, description="Estado OCPP do conector, quando citado."
    )
    potencia_entregue_kw: float | None = Field(
        default=None, description="Potência entregue à sessão, em kW."
    )
    headroom_kw: float | None = Field(
        default=None, description="Folga de potência disponível no ponto de entrega, em kW."
    )
    tarifa_aplicada_reais_kwh: float | None = Field(
        default=None, description="Tarifa aplicada à sessão, em R$/kWh."
    )
    base_regulatoria: str | None = Field(
        default=None, description="Norma citada como fundamento, quando houver."
    )
    fontes: list[str] = Field(
        default_factory=list,
        description="Identificadores das fontes técnicas usadas na resposta.",
    )

    # -- validadores de campo ------------------------------------------------

    @field_validator("resposta_direta", "fundamentacao_tecnica", "acao_do_sistema")
    @classmethod
    def _texto_substantivo(cls, valor: str) -> str:
        """Rejeita campos vazios ou preenchidos com marcadores de placeholder."""
        limpo = (valor or "").strip()
        if len(limpo) < 10:
            raise ValueError("campo textual obrigatório vazio ou curto demais")
        return limpo

    @field_validator("potencia_entregue_kw", "headroom_kw")
    @classmethod
    def _potencia_plausivel(cls, valor: float | None) -> float | None:
        if valor is None:
            return None
        if valor < 0:
            raise ValueError("potência não pode ser negativa")
        if valor > POTENCIA_MAXIMA_KW:
            raise ValueError(
                f"potência de {valor} kW excede o limite de {POTENCIA_MAXIMA_KW} kW "
                "dos carregadores homologados no ecossistema OCPP"
            )
        return round(valor, 2)

    @field_validator("tarifa_aplicada_reais_kwh")
    @classmethod
    def _tarifa_plausivel(cls, valor: float | None) -> float | None:
        if valor is None:
            return None
        if not TARIFA_MINIMA_REAIS_KWH <= valor <= TARIFA_MAXIMA_REAIS_KWH:
            raise ValueError(
                f"tarifa de R$ {valor}/kWh fora da faixa praticada em eletropostos "
                f"comerciais (R$ {TARIFA_MINIMA_REAIS_KWH} a R$ {TARIFA_MAXIMA_REAIS_KWH})"
            )
        return round(valor, 2)

    @field_validator("base_regulatoria")
    @classmethod
    def _norma_reconhecivel(cls, valor: str | None) -> str | None:
        """Impede que texto genérico ocupe o campo de fundamento normativo."""
        if valor is None:
            return None
        limpo = valor.strip()
        if not limpo:
            return None
        if not any(marca in limpo.upper() for marca in ("ANEEL", "RESOLUÇÃO", "RN ", "LEI ", "IEC", "ABNT")):
            raise ValueError(
                "base regulatória deve identificar a norma citada "
                "(ex.: 'Resolução Normativa ANEEL nº 1.000/2021')"
            )
        return limpo

    # -- validador de coerência entre campos ---------------------------------

    @model_validator(mode="after")
    def _coerencia_do_escopo(self) -> "ConsultaRecarga":
        """Garante que recusa e conteúdo operacional não coexistam.

        Uma resposta recusada não pode carregar métricas de operação nem
        projeção de impacto financeiro: seria uma recusa que, na prática,
        entregou o conteúdo recusado.
        """
        recusa = self.categoria in CATEGORIAS_DE_RECUSA

        if recusa and self.dentro_do_escopo:
            raise ValueError(
                "categoria de recusa exige dentro_do_escopo=False"
            )
        if not recusa and not self.dentro_do_escopo:
            raise ValueError(
                "dentro_do_escopo=False exige categoria 'fora_de_escopo' ou 'recusa_dominio'"
            )
        if recusa:
            campos_operacionais = (
                self.potencia_entregue_kw,
                self.headroom_kw,
                self.tarifa_aplicada_reais_kwh,
                self.impacto_no_negocio,
            )
            if any(campo is not None for campo in campos_operacionais):
                raise ValueError(
                    "resposta recusada não pode conter métricas operacionais "
                    "nem projeção de impacto no negócio"
                )
        return self

    # -- apresentação --------------------------------------------------------

    def como_texto(self) -> str:
        """Renderiza a resposta no formato de parágrafos usado na interface."""
        partes = [self.resposta_direta, self.fundamentacao_tecnica, self.acao_do_sistema]
        if self.impacto_no_negocio:
            partes.append(self.impacto_no_negocio)
        return "\n\n".join(partes)
