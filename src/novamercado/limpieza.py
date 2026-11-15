"""Motor general de defensa del contrato de NovaMercado.

Recibe el JSON crudo de ``POST /v1/prediccion`` o ``POST /v1/observaciones`` y
devuelve una solicitud canónica junto con su bloque de calidad, o lanza
:class:`ErrorContrato` (que la API traduce a HTTP 422).

Política (cada decisión queda registrada en ``calidad.observaciones``):

* **reparar** — la corrección es inequívoca: identificadores o números enviados como
  texto (``"T05"`` → 5, ``"1,292"`` → 1292, ``8.0`` → 8), fechas en otro formato
  no ambiguo, familias escritas de otra forma o con un error tipográfico leve con
  una única coincidencia, campos renombrados con un sinónimo conocido, duplicados
  idénticos.
* **advertir** — se responde, pero se supuso algo: ``en_promocion`` nulo o ausente
  (se asume 0), familia repetida con valores distintos (se conserva la última),
  familias faltantes, fecha DD/MM ambigua, valores extremos pero plausibles,
  campos desconocidos ignorados, horizonte de predicción lejano.
* **rechazar** — no hay forma segura de continuar: tienda inexistente o no
  positiva, familia irreconocible, fecha inexistente en el calendario o anterior a
  la apertura de la tienda, cantidades negativas, no enteras o inverosímiles,
  listas vacías, campos obligatorios ausentes o contradictorios.

Regla crítica: el servicio opera con fechas simuladas, así que este módulo **nunca**
consulta el reloj del sistema. Las referencias temporales salen de los catálogos
(apertura de tiendas, último día del histórico) o de ``fecha_referencia``.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any, Iterable

from novamercado.catalogos import Catalogos, cargar_catalogos

# --------------------------------------------------------------------------- #
# Constantes de política
# --------------------------------------------------------------------------- #
ACCION_REPARAR = "reparar"
ACCION_ADVERTIR = "advertir"
ACCION_RECHAZAR = "rechazar"

ESTADO_OK = "ok"
ESTADO_CORREGIDO = "corregido"
ESTADO_ADVERTENCIA = "advertencia"

TIPO_PREDICCION = "prediccion"
TIPO_OBSERVACIONES = "observaciones"

MAX_ELEMENTOS = 100  # una solicitud no debería traer más que unas pocas decenas
HORIZONTE_MAX_DIAS = 366  # más allá, el pronóstico se emite con advertencia
ANIO_MIN, ANIO_MAX = 2000, 2100

# Umbrales relativos al máximo histórico de referencia.
FACTOR_EXTREMO_VENTAS = 1.5  # > 1.5× máximo (tienda, familia) -> advertir
FACTOR_ABSURDO_VENTAS = 20  # > 20× máximo (tienda, familia) -> rechazar
FACTOR_EXTREMO_PROMO = 1.0  # > máximo histórico de la familia -> advertir
FACTOR_ABSURDO_PROMO = 10  # > 10× máximo histórico de la familia -> rechazar

_FALTA = object()  # centinela: el campo no vino en la solicitud


# --------------------------------------------------------------------------- #
# Tipos de resultado
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ObservacionCalidad:
    campo: str
    accion: str
    detalle: str

    def a_dict(self) -> dict[str, str]:
        return {"campo": self.campo, "accion": self.accion, "detalle": self.detalle}


class ErrorContrato(ValueError):
    """La solicitud no puede atenderse; ``errores`` es el ``detail`` del HTTP 422."""

    def __init__(self, errores: Iterable[dict[str, str]]):
        self.errores = list(errores)
        super().__init__("; ".join(f"{e['campo']}: {e['detalle']}" for e in self.errores))


def calcular_estado(observaciones: Iterable[Any]) -> str:
    """'advertencia' si hay alguna advertencia, 'corregido' si solo hubo reparaciones, si no 'ok'."""
    acciones = {o["accion"] if isinstance(o, dict) else o.accion for o in observaciones}
    if ACCION_ADVERTIR in acciones:
        return ESTADO_ADVERTENCIA
    if ACCION_REPARAR in acciones:
        return ESTADO_CORREGIDO
    return ESTADO_OK


@dataclass
class ResultadoLimpieza:
    tipo: str
    datos: dict[str, Any]
    observaciones: list[ObservacionCalidad]

    @property
    def estado(self) -> str:
        return calcular_estado(self.observaciones)

    @property
    def calidad(self) -> dict[str, Any]:
        return {
            "estado": self.estado,
            "observaciones": [o.a_dict() for o in self.observaciones],
        }


class _Bitacora:
    def __init__(self) -> None:
        self.observaciones: list[ObservacionCalidad] = []
        self.errores: list[dict[str, str]] = []

    def reparar(self, campo: str, detalle: str) -> None:
        self.observaciones.append(ObservacionCalidad(campo, ACCION_REPARAR, detalle))

    def advertir(self, campo: str, detalle: str) -> None:
        self.observaciones.append(ObservacionCalidad(campo, ACCION_ADVERTIR, detalle))

    def rechazar(self, campo: str, detalle: str) -> None:
        self.errores.append({"campo": campo, "accion": ACCION_RECHAZAR, "detalle": detalle})


# --------------------------------------------------------------------------- #
# Utilidades de texto
# --------------------------------------------------------------------------- #
def sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def normalizar_texto(texto: str) -> str:
    """'  Frutas y Verduras ' -> 'frutas_y_verduras'; 'LÁCTEOS' -> 'lacteos'."""
    t = sin_tildes(texto).lower().strip()
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_")


def _clave(nombre: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", sin_tildes(str(nombre)).lower())


def _mostrar(valor: Any) -> str:
    try:
        return json.dumps(valor, ensure_ascii=False)
    except (TypeError, ValueError):
        return repr(valor)


def _ruta(prefijo: str, campo: str) -> str:
    return f"{prefijo}.{campo}" if prefijo else campo


# --------------------------------------------------------------------------- #
# Nombres de campo (E07)
# --------------------------------------------------------------------------- #
_ALIAS_TIENDA = {
    "tiendaid", "tienda", "idtienda", "store", "storeid", "codtienda", "codigotienda",
    "numtienda", "notienda", "numerotienda", "sucursal", "sucursalid", "idsucursal",
}
_ALIAS_FECHA = {"fecha", "date", "dia", "fechaprediccion", "fechaventa", "fechaventas", "fechaobservacion"}
_ALIAS_FAMILIA = {"familiaid", "familia", "idfamilia", "family", "familyid", "categoria", "categoriaid"}
_ALIAS_PROMO = {"enpromocion", "promocion", "promociones", "promo", "enpromo", "onpromotion", "productosenpromocion"}
_ALIAS_VENTAS = {"ventas", "venta", "sales", "unidades", "unidadesvendidas", "cantidad", "cantidadvendida"}

_ESQUEMA_RAIZ = {
    TIPO_PREDICCION: {
        "tienda_id": _ALIAS_TIENDA,
        "fecha": _ALIAS_FECHA,
        "familias": {"familias", "familia", "items", "detalle", "productos", "lineas"},
    },
    TIPO_OBSERVACIONES: {
        "tienda_id": _ALIAS_TIENDA,
        "fecha": _ALIAS_FECHA,
        "ventas": {"ventas", "observaciones", "items", "detalle", "registros", "lineas"},
    },
}
_ESQUEMA_ELEMENTO = {
    TIPO_PREDICCION: {"familia_id": _ALIAS_FAMILIA, "en_promocion": _ALIAS_PROMO},
    TIPO_OBSERVACIONES: {"familia_id": _ALIAS_FAMILIA, "ventas": _ALIAS_VENTAS, "en_promocion": _ALIAS_PROMO},
}


def _mapear_claves(obj: dict, esquema: dict[str, set[str]], prefijo: str, bit: _Bitacora) -> dict[str, Any]:
    """Lleva cada clave a su nombre canónico; ignora (con advertencia) las desconocidas."""
    indice = {alias: canon for canon, aliases in esquema.items() for alias in aliases | {_clave(canon)}}
    resultado: dict[str, Any] = {}
    origen: dict[str, str] = {}
    for clave, valor in obj.items():
        canon = indice.get(_clave(clave))
        if canon is None:
            bit.advertir(_ruta(prefijo, str(clave)), f"el campo '{clave}' no forma parte del contrato; se ignoró")
            continue
        ruta = _ruta(prefijo, canon)
        if canon in resultado:
            previo = origen[canon]
            if type(resultado[canon]) is type(valor) and resultado[canon] == valor:
                bit.reparar(ruta, f"el campo llegó duplicado como '{previo}' y '{clave}' con el mismo valor; se conservó uno")
            else:
                bit.rechazar(
                    ruta,
                    f"valores contradictorios en '{previo}' ({_mostrar(resultado[canon])}) "
                    f"y '{clave}' ({_mostrar(valor)})",
                )
            continue
        if clave != canon:
            bit.reparar(ruta, f"el campo '{clave}' se renombró a '{canon}' según el contrato")
        resultado[canon] = valor
        origen[canon] = clave
    return resultado


# --------------------------------------------------------------------------- #
# tienda_id (E01)
# --------------------------------------------------------------------------- #
_RE_ENTERO_TEXTO = re.compile(r"^[+-]?\d+(?:\.0+)?$")
_RE_TIENDA_PREFIJO = re.compile(r"^(?:tienda|store|sucursal|suc|tda|t)[\s_\-#:.]*(\d+)$")


def _limpiar_tienda(valor: Any, cat: Catalogos, bit: _Bitacora, campo: str = "tienda_id") -> int | None:
    if valor is None:
        bit.rechazar(campo, "es obligatorio y llegó nulo")
        return None
    if isinstance(valor, bool):
        bit.rechazar(campo, f"se recibió un booleano ({_mostrar(valor)}); se esperaba un entero")
        return None
    if isinstance(valor, int):
        n = valor
    elif isinstance(valor, float):
        if not (math.isfinite(valor) and valor.is_integer()):
            bit.rechazar(campo, f"{_mostrar(valor)} no es un identificador entero de tienda")
            return None
        n = int(valor)
        bit.reparar(campo, f"{_mostrar(valor)} → {n} (decimal sin parte fraccionaria)")
    elif isinstance(valor, str):
        s = sin_tildes(valor).strip().lower()
        if _RE_ENTERO_TEXTO.match(s):
            n = int(Decimal(s))
        elif m := _RE_TIENDA_PREFIJO.match(s):
            n = int(m.group(1))
        else:
            bit.rechazar(campo, f"no se reconoce un identificador de tienda en {_mostrar(valor)}; se esperaba un entero como 5")
            return None
        bit.reparar(campo, f"{_mostrar(valor)} → {n} (identificador enviado como texto)")
    else:
        bit.rechazar(campo, f"tipo no admitido ({type(valor).__name__}); se esperaba un entero")
        return None

    if n <= 0:
        bit.rechazar(campo, f"debe ser un entero positivo; se recibió {n}")
        return None
    if n not in cat.tiendas:
        validas = ", ".join(str(t) for t in sorted(cat.tiendas))
        bit.rechazar(campo, f"la tienda {n} no existe en el catálogo de tiendas (válidas: {validas})")
        return None
    return n


# --------------------------------------------------------------------------- #
# fecha (E04)
# --------------------------------------------------------------------------- #
_RE_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_RE_MARCA_TIEMPO = re.compile(
    r"^(\d{4})-(\d{1,2})-(\d{1,2})[T ](\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?\s*(?:Z|[+-]\d{2}(?::?\d{2})?)?$",
    re.IGNORECASE,
)
_RE_AMD = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")
_RE_DMA = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$")
_RE_COMPACTA = re.compile(r"^(\d{4})(\d{2})(\d{2})$")


def _limpiar_fecha(valor: Any, bit: _Bitacora, campo: str = "fecha") -> date | None:
    if valor is None:
        bit.rechazar(campo, "es obligatoria y llegó nula")
        return None
    if not isinstance(valor, str):
        bit.rechazar(campo, f"debe ser texto con formato AAAA-MM-DD; se recibió {_mostrar(valor)}")
        return None

    s = valor.strip()
    nota: str | None = None
    advertencia: str | None = None
    if m := _RE_ISO.match(s):
        anio, mes, dia = m.groups()
        nota = None if s == valor else "se eliminaron espacios"
    elif m := _RE_MARCA_TIEMPO.match(s):
        anio, mes, dia, hh, mm, ss = m.groups()
        if int(hh) > 23 or int(mm) > 59 or (ss is not None and int(ss) > 59):
            bit.rechazar(campo, f"{_mostrar(valor)} contiene una hora inválida")
            return None
        nota = "marca de tiempo ISO; se conservó solo la fecha"
    elif m := _RE_AMD.match(s):
        anio, mes, dia = m.groups()
        nota = "formato AAAA/MM/DD"
    elif m := _RE_COMPACTA.match(s):
        anio, mes, dia = m.groups()
        nota = "formato AAAAMMDD"
    elif m := _RE_DMA.match(s):
        x, y, anio = int(m.group(1)), int(m.group(2)), m.group(3)
        if x > 12 and y <= 12:
            dia, mes, nota = x, y, "formato DD/MM/AAAA"
        elif y > 12 and x <= 12:
            mes, dia, nota = x, y, "formato MM/DD/AAAA: el segundo número solo puede ser el día"
        elif x <= 12 and y <= 12:
            dia, mes = x, y
            if x == y:
                nota = "formato DD/MM/AAAA"
            else:
                advertencia = "el orden día/mes es ambiguo; se interpretó como DD/MM/AAAA (convención local)"
        else:
            bit.rechazar(campo, f"{_mostrar(valor)} no es una fecha válida del calendario")
            return None
    else:
        bit.rechazar(campo, f"formato de fecha no reconocido en {_mostrar(valor)}; use AAAA-MM-DD")
        return None

    try:
        fecha = date(int(anio), int(mes), int(dia))
    except ValueError:
        bit.rechazar(campo, f"{_mostrar(valor)} no es una fecha válida del calendario")
        return None
    if not ANIO_MIN <= fecha.year <= ANIO_MAX:
        bit.rechazar(campo, f"el año {fecha.year} está fuera del rango admitido ({ANIO_MIN}–{ANIO_MAX})")
        return None

    if advertencia:
        bit.advertir(campo, f"{_mostrar(valor)} → {fecha.isoformat()}: {advertencia}")
    elif nota:
        bit.reparar(campo, f"{_mostrar(valor)} → {fecha.isoformat()} ({nota})")
    return fecha


# --------------------------------------------------------------------------- #
# familia_id (E02)
# --------------------------------------------------------------------------- #
def _distancia(a: str, b: str) -> int:
    """Distancia de Damerau-Levenshtein (alineamiento óptimo de cadenas)."""
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            costo = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + costo)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[len(a)][len(b)]


def _variantes(normalizado: str) -> set[str]:
    sin_y = re.sub(r"(^|_)y(_|$)", "_", normalizado).strip("_")
    return {normalizado, sin_y, normalizado.replace("_", ""), sin_y.replace("_", "")}


class ResolutorFamilias:
    """Mapea cualquier escritura razonable de una familia a su ``familia_id`` oficial."""

    def __init__(self, familias: dict[str, str]):
        self.oficiales = frozenset(familias)
        self._indice: dict[str, str] = {}
        for fid, nombre in familias.items():
            for texto in (fid, nombre):
                for v in _variantes(normalizar_texto(texto)):
                    self._indice.setdefault(v, fid)

    def resolver(self, texto: str) -> tuple[str | None, str]:
        """Devuelve (familia_id, tipo) con tipo en exacto|normalizado|tipografico|desconocido."""
        if texto in self.oficiales:
            return texto, "exacto"
        normalizado = normalizar_texto(texto)
        variantes = _variantes(normalizado)
        for v in variantes:
            if v in self._indice:
                return self._indice[v], "normalizado"
        compacto = min(variantes, key=len)
        if not compacto:
            return None, "desconocido"
        mejores: dict[str, int] = {}
        for clave, fid in self._indice.items():
            if "_" not in clave:
                mejores[fid] = min(mejores.get(fid, 99), _distancia(compacto, clave))
        orden = sorted(mejores.items(), key=lambda kv: kv[1])
        fid, dist = orden[0]
        segunda = orden[1][1] if len(orden) > 1 else 99
        tolerancia = 1 if len(compacto) <= 4 else 2
        if dist <= tolerancia and segunda > dist:
            return fid, "tipografico"
        return None, "desconocido"


@lru_cache(maxsize=8)
def _resolutor(familias: tuple[tuple[str, str], ...]) -> ResolutorFamilias:
    return ResolutorFamilias(dict(familias))


def _limpiar_familia(valor: Any, campo: str, resolutor: ResolutorFamilias, bit: _Bitacora) -> str | None:
    if valor is _FALTA:
        bit.rechazar(campo, "falta el campo obligatorio 'familia_id'")
        return None
    if valor is None:
        bit.rechazar(campo, "es obligatorio y llegó nulo")
        return None
    if not isinstance(valor, str):
        bit.rechazar(campo, f"debe ser texto; se recibió {_mostrar(valor)}")
        return None
    if not valor.strip():
        bit.rechazar(campo, "llegó vacío")
        return None
    fid, tipo = resolutor.resolver(valor)
    if fid is None:
        validas = ", ".join(sorted(resolutor.oficiales))
        bit.rechazar(campo, f"{_mostrar(valor)} no corresponde a ninguna familia del catálogo (válidas: {validas})")
        return None
    if tipo == "normalizado":
        bit.reparar(campo, f"{_mostrar(valor)} → '{fid}' (normalización de mayúsculas, tildes, espacios o separadores)")
    elif tipo == "tipografico":
        bit.reparar(campo, f"{_mostrar(valor)} → '{fid}' (corrección de error tipográfico leve)")
    return fid


# --------------------------------------------------------------------------- #
# Cantidades enteras: en_promocion (E03), ventas (E08, E10)
# --------------------------------------------------------------------------- #
class _NumeroInvalido(ValueError):
    pass


_RE_INT = re.compile(r"^[+-]?\d+$")
_RE_PUNTO = re.compile(r"^([+-]?)(\d+)\.(\d+)$")
_RE_COMA = re.compile(r"^([+-]?)(\d+),(\d+)$")
_RE_MILES_COMA = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
_RE_MILES_PUNTO = re.compile(r"^[+-]?\d{1,3}(?:\.\d{3})+(?:,\d+)?$")


def _decimal_a_entero(texto: str, original: Any) -> int:
    try:
        d = Decimal(texto)
    except InvalidOperation as e:  # pragma: no cover - las regex ya filtran
        raise _NumeroInvalido(f"{_mostrar(original)} no es un número reconocible") from e
    if d != d.to_integral_value():
        raise _NumeroInvalido(f"{_mostrar(original)} no es un número entero")
    return int(d)


def _parece_miles(entero: str, fraccion: str) -> bool:
    # "1,292" / "1.292": tres dígitos tras un único separador y parte entera de 1-3 dígitos
    # sin cero inicial. La lectura decimal (1.292) no es entera, así que la única lectura
    # entera es la de miles.
    return len(fraccion) == 3 and 1 <= len(entero) <= 3 and not entero.startswith("0")


def _texto_a_entero(original: str) -> tuple[int, str]:
    s = original.strip().replace(" ", "").replace(" ", "")
    if not s:
        raise _NumeroInvalido("llegó como texto vacío")
    if _RE_INT.match(s):
        return int(s), "número enviado como texto"
    if m := _RE_PUNTO.match(s):
        signo, ent, frac = m.groups()
        if _parece_miles(ent, frac):
            if frac == "000":
                raise _NumeroInvalido(
                    f"{_mostrar(original)} es ambiguo: puede ser {signo}{ent} (decimal) o {signo}{ent}000 (miles)"
                )
            return int(signo + ent + frac), "punto como separador de miles"
        return _decimal_a_entero(f"{signo}{ent}.{frac}", original), "decimal sin parte fraccionaria enviado como texto"
    if m := _RE_COMA.match(s):
        signo, ent, frac = m.groups()
        if _parece_miles(ent, frac):
            return int(signo + ent + frac), "coma como separador de miles"
        return _decimal_a_entero(f"{signo}{ent}.{frac}", original), "coma decimal sin parte fraccionaria"
    if _RE_MILES_COMA.match(s):
        return _decimal_a_entero(s.replace(",", ""), original), "comas como separador de miles"
    if _RE_MILES_PUNTO.match(s):
        return _decimal_a_entero(s.replace(".", "").replace(",", "."), original), "puntos como separador de miles"
    raise _NumeroInvalido(f"{_mostrar(original)} no es un número reconocible")


def _a_entero(valor: Any) -> tuple[int, str | None]:
    if isinstance(valor, bool):
        raise _NumeroInvalido(f"se recibió un booleano ({_mostrar(valor)}); se esperaba un entero")
    if isinstance(valor, int):
        return valor, None
    if isinstance(valor, float):
        if not math.isfinite(valor):
            raise _NumeroInvalido(f"{valor!r} no es un número finito")
        if not valor.is_integer():
            raise _NumeroInvalido(f"{_mostrar(valor)} no es un número entero")
        return int(valor), "decimal sin parte fraccionaria"
    if isinstance(valor, str):
        return _texto_a_entero(valor)
    raise _NumeroInvalido(f"tipo no admitido ({type(valor).__name__}); se esperaba un entero")


def _limpiar_cantidad(valor: Any, campo: str, bit: _Bitacora, *, nulo_como_cero: bool) -> int | None:
    if valor is _FALTA or valor is None:
        if nulo_como_cero:
            motivo = "no se envió" if valor is _FALTA else "llegó nulo"
            bit.advertir(campo, f"{motivo}; se asumió 0")
            return 0
        bit.rechazar(campo, "es obligatorio" if valor is _FALTA else "es obligatorio y llegó nulo")
        return None
    try:
        n, motivo = _a_entero(valor)
    except _NumeroInvalido as e:
        bit.rechazar(campo, str(e))
        return None
    if n < 0:
        extra = "; las devoluciones no se registran como ventas" if campo.endswith(".ventas") else ""
        bit.rechazar(campo, f"no puede ser negativo (se recibió {n}){extra}")
        return None
    if motivo:
        bit.reparar(campo, f"{_mostrar(valor)} → {n} ({motivo})")
    return n


def _revisar_extremo(
    n: int, campo: str, magnitud: str, tienda: int | None, familia: str, cat: Catalogos, bit: _Bitacora
) -> None:
    if magnitud == "ventas":
        referencia = cat.max_ventas.get((tienda, familia)) if tienda is not None else None
        ambito = f"la familia '{familia}' en la tienda {tienda}"
        if referencia is None:
            referencia = cat.max_ventas_familia.get(familia)
            ambito = f"la familia '{familia}'"
        f_extremo, f_absurdo = FACTOR_EXTREMO_VENTAS, FACTOR_ABSURDO_VENTAS
    else:
        referencia = cat.max_promo_familia.get(familia)
        ambito = f"la familia '{familia}'"
        f_extremo, f_absurdo = FACTOR_EXTREMO_PROMO, FACTOR_ABSURDO_PROMO
    if referencia is None:
        return
    referencia = max(referencia, 1)
    if n > referencia * f_absurdo:
        bit.rechazar(
            campo,
            f"{n} es inverosímil: supera {f_absurdo}× el máximo histórico ({referencia}) de {ambito}",
        )
    elif n > referencia * f_extremo:
        bit.advertir(
            campo,
            f"{n} es un valor extremo: supera el máximo histórico ({referencia}) de {ambito}; se aceptó",
        )


# --------------------------------------------------------------------------- #
# Elementos de la lista y consolidación (E05, E06)
# --------------------------------------------------------------------------- #
def _limpiar_elemento(
    elemento: Any,
    prefijo: str,
    tipo: str,
    tienda: int | None,
    cat: Catalogos,
    resolutor: ResolutorFamilias,
    bit: _Bitacora,
) -> dict[str, Any] | None:
    if not isinstance(elemento, dict):
        bit.rechazar(prefijo, f"cada elemento debe ser un objeto con 'familia_id'; se recibió {_mostrar(elemento)}")
        return None
    errores_previos = len(bit.errores)
    campos = _mapear_claves(elemento, _ESQUEMA_ELEMENTO[tipo], prefijo, bit)
    familia = _limpiar_familia(campos.get("familia_id", _FALTA), f"{prefijo}.familia_id", resolutor, bit)

    if tipo == TIPO_PREDICCION:
        campo = f"{prefijo}.en_promocion"
        promo = _limpiar_cantidad(campos.get("en_promocion", _FALTA), campo, bit, nulo_como_cero=True)
        if promo is not None and familia:
            _revisar_extremo(promo, campo, "en_promocion", tienda, familia, cat, bit)
        resultado: dict[str, Any] = {"familia_id": familia, "en_promocion": promo}
    else:
        campo = f"{prefijo}.ventas"
        ventas = _limpiar_cantidad(campos.get("ventas", _FALTA), campo, bit, nulo_como_cero=False)
        if ventas is not None and familia:
            _revisar_extremo(ventas, campo, "ventas", tienda, familia, cat, bit)
        resultado = {"familia_id": familia, "ventas": ventas}
        promo_crudo = campos.get("en_promocion", _FALTA)
        if promo_crudo is not _FALTA and promo_crudo is not None:  # opcional en observaciones
            campo = f"{prefijo}.en_promocion"
            promo = _limpiar_cantidad(promo_crudo, campo, bit, nulo_como_cero=False)
            if promo is not None and familia:
                _revisar_extremo(promo, campo, "en_promocion", tienda, familia, cat, bit)
            resultado["en_promocion"] = promo

    return None if len(bit.errores) > errores_previos else resultado


def _consolidar(elementos: list[tuple[int, dict]], clave_lista: str, bit: _Bitacora) -> list[dict]:
    """Una entrada por familia: se conserva la última aparición (en la posición de la primera)."""
    grupos: dict[str, list[tuple[int, dict]]] = {}
    for i, e in elementos:
        grupos.setdefault(e["familia_id"], []).append((i, e))
    salida = []
    for fid, apariciones in grupos.items():
        ultimo_i, ultimo = apariciones[-1]
        if len(apariciones) > 1:
            posiciones = ", ".join(str(i) for i, _ in apariciones)
            valores = [{k: v for k, v in e.items() if k != "familia_id"} for _, e in apariciones]
            if all(v == valores[0] for v in valores):
                bit.reparar(
                    clave_lista,
                    f"la familia '{fid}' aparece {len(apariciones)} veces (posiciones {posiciones}) "
                    "con valores idénticos; se conservó una sola",
                )
            else:
                desc = "; ".join(
                    f"posición {i}: " + ", ".join(f"{k}={v}" for k, v in val.items())
                    for (i, _), val in zip(apariciones, valores)
                )
                bit.advertir(
                    clave_lista,
                    f"la familia '{fid}' aparece {len(apariciones)} veces con valores distintos ({desc}); "
                    f"se conservó la última (posición {ultimo_i})",
                )
        salida.append(ultimo)
    return salida


# --------------------------------------------------------------------------- #
# Punto de entrada
# --------------------------------------------------------------------------- #
def _limpiar(crudo: Any, tipo: str, cat: Catalogos, fecha_referencia: date | None) -> ResultadoLimpieza:
    bit = _Bitacora()
    clave_lista = "familias" if tipo == TIPO_PREDICCION else "ventas"

    if not isinstance(crudo, dict):
        raise ErrorContrato(
            [{"campo": "cuerpo", "accion": ACCION_RECHAZAR,
              "detalle": f"el cuerpo debe ser un objeto JSON; se recibió {type(crudo).__name__}"}]
        )

    raiz = _mapear_claves(crudo, _ESQUEMA_RAIZ[tipo], "", bit)
    for campo in ("tienda_id", "fecha", clave_lista):
        if campo not in raiz:
            bit.rechazar(campo, f"falta el campo obligatorio '{campo}'")

    tienda = _limpiar_tienda(raiz["tienda_id"], cat, bit) if "tienda_id" in raiz else None
    fecha = _limpiar_fecha(raiz["fecha"], bit) if "fecha" in raiz else None

    if tienda is not None and fecha is not None:
        apertura = cat.tiendas[tienda].fecha_apertura
        if fecha < apertura:
            bit.rechazar(
                "fecha",
                f"la tienda {tienda} abrió el {apertura.isoformat()}; no puede haber operación el {fecha.isoformat()}",
            )
    if tipo == TIPO_PREDICCION and fecha is not None:
        referencia = fecha_referencia or cat.fecha_max_historico
        if referencia is not None and (fecha - referencia).days > HORIZONTE_MAX_DIAS:
            bit.advertir(
                "fecha",
                f"{fecha.isoformat()} está a {(fecha - referencia).days} días del último dato conocido "
                f"({referencia.isoformat()}); el pronóstico es menos confiable",
            )

    elementos: list[tuple[int, dict]] = []
    if clave_lista in raiz:
        lista = raiz[clave_lista]
        if not isinstance(lista, list):
            bit.rechazar(clave_lista, f"debe ser una lista de objetos; se recibió {_mostrar(lista)}")
        elif not lista:
            bit.rechazar(clave_lista, "la lista está vacía; se requiere al menos una familia")
        elif len(lista) > MAX_ELEMENTOS:
            bit.rechazar(clave_lista, f"la lista tiene {len(lista)} elementos; el máximo admitido es {MAX_ELEMENTOS}")
        else:
            resolutor = _resolutor(tuple(sorted(cat.familias.items())))
            for i, elemento in enumerate(lista):
                r = _limpiar_elemento(elemento, f"{clave_lista}[{i}]", tipo, tienda, cat, resolutor, bit)
                if r is not None:
                    elementos.append((i, r))

    if bit.errores:
        raise ErrorContrato(bit.errores)

    consolidados = _consolidar(elementos, clave_lista, bit)

    faltan = sorted(cat.familias_esperadas(tienda) - {e["familia_id"] for e in consolidados})
    if faltan:
        consecuencia = (
            "no se emitirá pronóstico para ellas" if tipo == TIPO_PREDICCION
            else "no se registrarán ventas para ellas"
        )
        bit.advertir(
            clave_lista,
            f"faltan {len(faltan)} familias que la tienda vende ({', '.join(faltan)}); {consecuencia}",
        )
    if tipo == TIPO_OBSERVACIONES and all(e["ventas"] == 0 for e in consolidados):
        bit.advertir(clave_lista, "todas las ventas reportadas son 0; verifique si la tienda estuvo cerrada")

    datos = {"tienda_id": tienda, "fecha": fecha.isoformat(), clave_lista: consolidados}
    return ResultadoLimpieza(tipo=tipo, datos=datos, observaciones=bit.observaciones)


def limpiar_prediccion(
    crudo: Any, catalogos: Catalogos | None = None, *, fecha_referencia: date | None = None
) -> ResultadoLimpieza:
    """Valida y repara una solicitud de ``POST /v1/prediccion``.

    ``fecha_referencia`` es el "hoy" simulado (último dato conocido); por defecto se usa
    el último día del histórico. Lanza :class:`ErrorContrato` si debe rechazarse.
    """
    return _limpiar(crudo, TIPO_PREDICCION, catalogos or cargar_catalogos(), fecha_referencia)


def limpiar_observaciones(crudo: Any, catalogos: Catalogos | None = None) -> ResultadoLimpieza:
    """Valida y repara una solicitud de ``POST /v1/observaciones``."""
    return _limpiar(crudo, TIPO_OBSERVACIONES, catalogos or cargar_catalogos(), None)
