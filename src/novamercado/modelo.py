"""Ingeniería de features, modelos (baseline y HGB) y costo de negocio.

Regla de oro (cero fuga temporal): las features de un objetivo con fecha ``D`` se
calculan **solo** con observaciones de fecha ``< D``. Se construye una rejilla diaria
completa por (tienda, familia) y todas las features históricas salen de la serie
desplazada al menos un día (``shift(k)`` con ``k >= 1``). La misma función se usa al
entrenar y al servir, lo que garantiza paridad entrenamiento/producción.

Lo único del propio día ``D`` que entra al modelo es lo que se conoce al pedir el
pronóstico: ``en_promocion`` (viene en la solicitud), el calendario y los feriados.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from novamercado.catalogos import Catalogos

CLAVES = ["tienda_id", "familia_id"]

FEATURES_NUMERICAS = [
    "en_promocion",
    "lag_1", "lag_7", "lag_14", "lag_28",
    "media_7", "media_28", "std_28", "media_dow_4",
    "promo_media_28", "promo_delta",
    "ultimo_valor", "dias_desde_ultimo", "tendencia_7_28",
    "dia_semana", "dia_mes", "mes", "semana_anio", "es_quincena", "es_fin_de_semana",
    "es_feriado", "es_comercial", "es_pago", "es_medio_dia", "vispera_feriado",
    "dias_desde_apertura",
]
FEATURES_CATEGORICAS = ["tienda_id", "familia_cod", "tipo_tienda_cod"]
COLUMNAS_FEATURES = FEATURES_NUMERICAS + FEATURES_CATEGORICAS

_TIPOS_FERIADO = {
    "feriado": "es_feriado",
    "comercial": "es_comercial",
    "pago": "es_pago",
    "medio_dia": "es_medio_dia",
}


# --------------------------------------------------------------------------- #
# Features
# --------------------------------------------------------------------------- #
def _flags_feriados(fechas: pd.Series, ciudades: pd.Series, cat: Catalogos) -> pd.DataFrame:
    """Feriado aplica si ``ambito == 'nacional'`` o ``ambito == ciudad de la tienda``."""
    nacionales: dict[str, set] = {t: set() for t in _TIPOS_FERIADO}
    locales: dict[str, set] = {t: set() for t in _TIPOS_FERIADO}
    for f in cat.feriados:
        tipo = f["tipo"]
        if tipo not in _TIPOS_FERIADO:
            continue
        d = pd.Timestamp(f["fecha"])
        if f["ambito"] == "nacional":
            nacionales[tipo].add(d)
        else:
            locales[tipo].add((d, f["ambito"]))
    pares = list(zip(fechas, ciudades))
    salida = {
        col: np.fromiter(
            ((d in nacionales[t]) or ((d, c) in locales[t]) for d, c in pares), dtype=np.int8, count=len(pares)
        )
        for t, col in _TIPOS_FERIADO.items()
    }
    un_dia = pd.Timedelta(days=1)
    salida["vispera_feriado"] = np.fromiter(
        ((d + un_dia in nacionales["feriado"]) or ((d + un_dia, c) in locales["feriado"]) for d, c in pares),
        dtype=np.int8, count=len(pares),
    )
    return pd.DataFrame(salida, index=fechas.index)


def construir_features(historia: pd.DataFrame, objetivos: pd.DataFrame, cat: Catalogos) -> pd.DataFrame:
    """Devuelve ``objetivos`` + columnas de features.

    historia: fecha, tienda_id, familia_id, ventas[, en_promocion]
    objetivos: fecha, tienda_id, familia_id, en_promocion[, ventas, ...]
    Para cada objetivo con fecha D solo se usa historia con fecha < D.
    """
    obj = objetivos.copy()
    obj["fecha"] = pd.to_datetime(obj["fecha"])
    obj["tienda_id"] = obj["tienda_id"].astype(int)
    obj["en_promocion"] = pd.to_numeric(obj["en_promocion"], errors="coerce").fillna(0).astype(float)

    h = historia.copy()
    if "en_promocion" not in h.columns:
        h["en_promocion"] = np.nan
    h = h[["fecha", "tienda_id", "familia_id", "ventas", "en_promocion"]]
    h["fecha"] = pd.to_datetime(h["fecha"])
    h["tienda_id"] = h["tienda_id"].astype(int)
    h = h.rename(columns={"ventas": "_v", "en_promocion": "_p"}).astype({"_v": float, "_p": float})

    claves = pd.concat([h[CLAVES], obj[CLAVES]]).drop_duplicates()
    inicio = min(h["fecha"].min(), obj["fecha"].min()) if len(h) else obj["fecha"].min()
    fechas = pd.DataFrame({"fecha": pd.date_range(inicio, obj["fecha"].max(), freq="D")})
    g = claves.merge(fechas, how="cross").merge(h, on=["fecha", *CLAVES], how="left")
    g = g.sort_values([*CLAVES, "fecha"], kind="mergesort").reset_index(drop=True)

    grupo = [g["tienda_id"], g["familia_id"]]
    v = g.groupby(CLAVES, sort=False)["_v"]
    previo = v.shift(1)  # todo lo que sigue usa solo días < D
    g["lag_1"] = previo
    for k in (7, 14, 21, 28):
        g[f"lag_{k}"] = v.shift(k)
    g_prev = previo.groupby(grupo, sort=False)
    g["media_7"] = g_prev.transform(lambda s: s.rolling(7, min_periods=1).mean())
    g["media_28"] = g_prev.transform(lambda s: s.rolling(28, min_periods=1).mean())
    g["std_28"] = g_prev.transform(lambda s: s.rolling(28, min_periods=2).std())
    g["media_dow_4"] = g[["lag_7", "lag_14", "lag_21", "lag_28"]].mean(axis=1, skipna=True)
    promo_prev = g.groupby(CLAVES, sort=False)["_p"].shift(1)
    g["promo_media_28"] = promo_prev.groupby(grupo, sort=False).transform(
        lambda s: s.rolling(28, min_periods=1).mean()
    )
    g["ultimo_valor"] = g_prev.ffill()
    fecha_obs = g["fecha"].where(g["_v"].notna())
    ultima_fecha = fecha_obs.groupby(grupo, sort=False).shift(1).groupby(grupo, sort=False).ffill()
    g["dias_desde_ultimo"] = (g["fecha"] - ultima_fecha).dt.days
    g["tendencia_7_28"] = g["media_7"] / g["media_28"].replace(0, np.nan)

    cols_hist = ["lag_1", "lag_7", "lag_14", "lag_28", "media_7", "media_28", "std_28", "media_dow_4",
                 "promo_media_28", "ultimo_valor", "dias_desde_ultimo", "tendencia_7_28"]
    out = obj.merge(g[["fecha", *CLAVES, *cols_hist]], on=["fecha", *CLAVES], how="left")

    out["promo_delta"] = out["en_promocion"] - out["promo_media_28"]
    f = out["fecha"]
    out["dia_semana"] = f.dt.day_of_week
    out["dia_mes"] = f.dt.day
    out["mes"] = f.dt.month
    out["semana_anio"] = f.dt.isocalendar().week.astype(int).to_numpy()
    out["es_quincena"] = ((f.dt.day == 15) | f.dt.is_month_end).astype(int)
    out["es_fin_de_semana"] = (f.dt.day_of_week >= 5).astype(int)

    ciudad = {t: x.ciudad for t, x in cat.tiendas.items()}
    tipos = sorted({x.tipo for x in cat.tiendas.values()})
    tipo = {t: tipos.index(x.tipo) for t, x in cat.tiendas.items()}
    apertura = {t: pd.Timestamp(x.fecha_apertura) for t, x in cat.tiendas.items()}
    familias = sorted(cat.familias)
    out = pd.concat([out, _flags_feriados(f, out["tienda_id"].map(ciudad), cat)], axis=1)
    out["dias_desde_apertura"] = (f - out["tienda_id"].map(apertura)).dt.days
    out["tipo_tienda_cod"] = out["tienda_id"].map(tipo).fillna(-1).astype(int)
    out["familia_cod"] = out["familia_id"].map({x: i for i, x in enumerate(familias)}).fillna(-1).astype(int)
    return out


# --------------------------------------------------------------------------- #
# Costo de negocio y cantidad sugerida
# --------------------------------------------------------------------------- #
def costos_por_fila(familias: pd.Series, costos: dict[str, dict[str, float]]) -> tuple[np.ndarray, np.ndarray]:
    cf = familias.map({k: v["costo_faltante"] for k, v in costos.items()}).fillna(1.0).to_numpy(float)
    cs = familias.map({k: v["costo_sobrante"] for k, v in costos.items()}).fillna(1.0).to_numpy(float)
    return cf, cs


def costo_negocio(real, sugerido, familias: pd.Series, costos) -> float:
    """sum C_faltante * max(real - sugerido, 0) + C_sobrante * max(sugerido - real, 0)."""
    real = np.asarray(real, float)
    sugerido = np.asarray(sugerido, float)
    cf, cs = costos_por_fila(pd.Series(familias).reset_index(drop=True), costos)
    return float(np.sum(cf * np.maximum(real - sugerido, 0) + cs * np.maximum(sugerido - real, 0)))


def razon_critica(costos: dict[str, dict[str, float]]) -> dict[str, float]:
    """Cuantil óptimo del vendedor de periódicos: C_f / (C_f + C_s)."""
    return {k: v["costo_faltante"] / (v["costo_faltante"] + v["costo_sobrante"]) for k, v in costos.items()}


REJILLA_FACTORES = np.round(np.arange(0.50, 2.505, 0.01), 2)


def a_cantidad(venta_esperada: np.ndarray, factor: np.ndarray | float) -> np.ndarray:
    return np.maximum(np.rint(np.asarray(venta_esperada, float) * factor), 0).astype(np.int64)


def optimizar_factores(pred, real, familias: pd.Series, costos) -> dict[str, float]:
    """Factor multiplicativo por familia que minimiza el costo asimétrico real (búsqueda exacta).

    Equivale a estimar empíricamente el cuantil C_f/(C_f+C_s) de la demanda condicionada
    al pronóstico, pero optimiza directamente la cantidad entera que se enviará.
    """
    pred = np.asarray(pred, float)
    real = np.asarray(real, float)
    familias = pd.Series(familias).reset_index(drop=True)
    factores: dict[str, float] = {}
    for fam in sorted(set(familias)):
        m = (familias == fam).to_numpy()
        c = costos.get(fam, {"costo_faltante": 1.0, "costo_sobrante": 1.0})
        q = np.maximum(np.rint(np.outer(pred[m], REJILLA_FACTORES)), 0)
        r = real[m][:, None]
        costo = (c["costo_faltante"] * np.maximum(r - q, 0) + c["costo_sobrante"] * np.maximum(q - r, 0)).sum(0)
        mejores = np.flatnonzero(costo == costo.min())
        factores[fam] = float(REJILLA_FACTORES[mejores[np.argmin(np.abs(REJILLA_FACTORES[mejores] - 1))]])
    return factores


# --------------------------------------------------------------------------- #
# Artefacto desplegable
# --------------------------------------------------------------------------- #
def prediccion_baseline(X: pd.DataFrame) -> np.ndarray:
    """Media de los últimos 4 mismos días de la semana (tienda, familia); respaldo: media 28 días."""
    base = X["media_dow_4"].fillna(X["media_28"]).fillna(X["ultimo_valor"]).fillna(0.0)
    return np.maximum(base.to_numpy(float), 0)


@dataclass
class ArtefactoModelo:
    """Lo que se registra en MLflow y se carga en la API (serializado con joblib)."""

    tipo: str  # "hgb" | "baseline"
    estimador: Any
    factores: dict[str, float]
    columnas: list[str] = field(default_factory=lambda: list(COLUMNAS_FEATURES))
    fecha_corte: str | None = None  # último día de datos usado para ajustar
    metadatos: dict[str, Any] = field(default_factory=dict)

    def venta_esperada(self, X: pd.DataFrame) -> np.ndarray:
        if self.tipo == "baseline":
            return prediccion_baseline(X)
        return np.maximum(self.estimador.predict(X[self.columnas]), 0)

    def predecir(self, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """Devuelve (venta_esperada float, cantidad_sugerida int >= 0)."""
        v = self.venta_esperada(X)
        factor = X["familia_id"].map(self.factores).fillna(1.0).to_numpy(float)
        return v, a_cantidad(v, factor)
