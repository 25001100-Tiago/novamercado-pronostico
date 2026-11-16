"""Esquemas Pydantic del contrato HTTP.

Defensa en dos capas:

1. :mod:`novamercado.limpieza` recibe el JSON crudo, repara lo inequívoco, advierte
   lo supuesto y rechaza lo imposible (por eso los endpoints reciben ``dict`` crudo:
   si FastAPI validara primero, rechazaría con 422 casos que sí se pueden reparar).
2. Los modelos canónicos de este módulo son **estrictos** (``StrictInt``, sin campos
   extra, fecha ISO, familias únicas y del catálogo). Validan la salida de la
   limpieza como garantía final antes de llegar al modelo o a la base de datos.

``Calidad`` hace cumplir el formato de calidad: ``estado`` coherente con las
acciones y ``observaciones == []`` si y solo si ``estado == 'ok'``.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from novamercado.catalogos import Catalogos, cargar_catalogos
from novamercado.limpieza import (
    ErrorContrato,
    ResultadoLimpieza,
    calcular_estado,
    limpiar_observaciones,
    limpiar_prediccion,
)

EstadoCalidad = Literal["ok", "corregido", "advertencia"]
AccionCalidad = Literal["reparar", "advertir"]

_RE_FECHA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")

FamiliaId = Annotated[StrictStr, Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=40)]
Cantidad = Annotated[StrictInt, Field(ge=0)]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- #
# Calidad
# --------------------------------------------------------------------------- #
class ObservacionCalidad(_Base):
    campo: StrictStr = Field(min_length=1)
    accion: AccionCalidad
    detalle: StrictStr = Field(min_length=1)


class Calidad(_Base):
    estado: EstadoCalidad
    observaciones: list[ObservacionCalidad] = Field(default_factory=list)

    @model_validator(mode="after")
    def _estado_coherente(self) -> "Calidad":
        esperado = calcular_estado(self.observaciones)
        if self.estado != esperado:
            raise ValueError(
                f"estado '{self.estado}' incoherente con las observaciones (corresponde '{esperado}')"
            )
        return self

    @classmethod
    def desde_resultado(cls, resultado: ResultadoLimpieza) -> "Calidad":
        return cls.model_validate(resultado.calidad)


# --------------------------------------------------------------------------- #
# Solicitudes canónicas (estrictas)
# --------------------------------------------------------------------------- #
class _SolicitudBase(_Base):
    tienda_id: StrictInt = Field(gt=0)
    fecha: date

    @field_validator("fecha", mode="before")
    @classmethod
    def _fecha_iso(cls, v: Any) -> Any:
        if isinstance(v, str) and not _RE_FECHA_ISO.match(v):
            raise ValueError("la fecha canónica debe tener formato AAAA-MM-DD")
        if isinstance(v, date) or isinstance(v, str):
            return v
        raise ValueError("la fecha canónica debe ser texto AAAA-MM-DD")

    def _validar_contra_catalogo(self, info: ValidationInfo, familias: list[str]) -> None:
        cat: Catalogos | None = (info.context or {}).get("catalogos")
        if len(set(familias)) != len(familias):
            raise ValueError("cada familia debe aparecer una sola vez")
        if cat is None:
            return
        if self.tienda_id not in cat.tiendas:
            raise ValueError(f"la tienda {self.tienda_id} no existe en el catálogo")
        desconocidas = sorted(set(familias) - set(cat.familias))
        if desconocidas:
            raise ValueError(f"familias fuera del catálogo: {', '.join(desconocidas)}")


class FamiliaPrediccion(_Base):
    familia_id: FamiliaId
    en_promocion: Cantidad


class SolicitudPrediccion(_SolicitudBase):
    familias: list[FamiliaPrediccion] = Field(min_length=1)

    @model_validator(mode="after")
    def _catalogo(self, info: ValidationInfo) -> "SolicitudPrediccion":
        self._validar_contra_catalogo(info, [f.familia_id for f in self.familias])
        return self


class VentaObservada(_Base):
    familia_id: FamiliaId
    ventas: Cantidad
    en_promocion: Cantidad | None = None


class SolicitudObservaciones(_SolicitudBase):
    ventas: list[VentaObservada] = Field(min_length=1)

    @model_validator(mode="after")
    def _catalogo(self, info: ValidationInfo) -> "SolicitudObservaciones":
        self._validar_contra_catalogo(info, [v.familia_id for v in self.ventas])
        return self


# --------------------------------------------------------------------------- #
# Respuestas
# --------------------------------------------------------------------------- #
class PrediccionFamilia(_Base):
    """Exactamente los campos del Anexo: ``familia_id``, ``venta_esperada``, ``cantidad_sugerida``."""

    familia_id: StrictStr
    venta_esperada: float = Field(ge=0)
    cantidad_sugerida: StrictInt = Field(ge=0)


class RespuestaPrediccion(_Base):
    tienda_id: int
    fecha: date
    version_modelo: StrictStr = Field(min_length=1)
    predicciones: list[PrediccionFamilia]
    calidad: Calidad


class RespuestaObservaciones(_Base):
    registros_guardados: StrictInt = Field(ge=0)
    calidad: Calidad


class RespuestaModelo(_Base):
    nombre: StrictStr
    alias: StrictStr
    version: StrictStr


class RespuestaReentrenar(_Base):
    id: StrictStr


class EstadoReentrenamiento(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: StrictStr
    estado: Literal["en_curso", "exitoso", "fallido"]
    promovido: bool | None = None
    version: StrictStr | None = None
    motivo: StrictStr | None = None

    def a_respuesta(self) -> dict[str, Any]:
        """Formato del Anexo: en curso solo ``estado``; al terminar, ``estado``, ``promovido``,
        ``version`` y ``motivo`` (el ``id`` ya va en la URL y no se repite)."""
        if self.estado == "en_curso":
            return {"estado": self.estado}
        return {
            "estado": self.estado,
            "promovido": bool(self.promovido),
            "version": self.version or "",
            "motivo": self.motivo or "",
        }


class ErrorDetalle(_Base):
    campo: str
    accion: Literal["rechazar"] = "rechazar"
    detalle: str


class RespuestaError(_Base):
    detail: list[ErrorDetalle]


# --------------------------------------------------------------------------- #
# Fachada usada por los endpoints
# --------------------------------------------------------------------------- #
def _ruta_pydantic(loc: tuple[Any, ...]) -> str:
    ruta = ""
    for parte in loc:
        ruta += f"[{parte}]" if isinstance(parte, int) else (f".{parte}" if ruta else str(parte))
    return ruta or "cuerpo"


def _errores_pydantic(exc: ValidationError) -> list[dict[str, str]]:
    return [
        {"campo": _ruta_pydantic(tuple(e["loc"])), "accion": "rechazar", "detalle": e["msg"]}
        for e in exc.errors()
    ]


def validar_prediccion(
    crudo: Any, catalogos: Catalogos | None = None, *, fecha_referencia: date | None = None
) -> tuple[SolicitudPrediccion, Calidad]:
    """JSON crudo -> (solicitud canónica, calidad). Lanza ErrorContrato si debe rechazarse."""
    cat = catalogos or cargar_catalogos()
    resultado = limpiar_prediccion(crudo, cat, fecha_referencia=fecha_referencia)
    try:
        solicitud = SolicitudPrediccion.model_validate(resultado.datos, context={"catalogos": cat})
    except ValidationError as e:
        raise ErrorContrato(_errores_pydantic(e)) from e
    return solicitud, Calidad.desde_resultado(resultado)


def validar_observaciones(
    crudo: Any, catalogos: Catalogos | None = None
) -> tuple[SolicitudObservaciones, Calidad]:
    """JSON crudo -> (observaciones canónicas, calidad). Lanza ErrorContrato si debe rechazarse."""
    cat = catalogos or cargar_catalogos()
    resultado = limpiar_observaciones(crudo, cat)
    try:
        solicitud = SolicitudObservaciones.model_validate(resultado.datos, context={"catalogos": cat})
    except ValidationError as e:
        raise ErrorContrato(_errores_pydantic(e)) from e
    return solicitud, Calidad.desde_resultado(resultado)


def cuerpo_error(exc: ErrorContrato) -> dict[str, Any]:
    """Cuerpo JSON del HTTP 422: ``{"detail": [{campo, accion: 'rechazar', detalle}, ...]}``."""
    return RespuestaError(detail=[ErrorDetalle(**e) for e in exc.errores]).model_dump()
