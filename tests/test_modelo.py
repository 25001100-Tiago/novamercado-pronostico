"""Pruebas de features (sin fuga temporal), costo de negocio, factores y compuerta."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from novamercado.entrenamiento import Ventanas, decidir_promocion, entrenar_candidato
from novamercado.modelo import (
    COLUMNAS_FEATURES,
    ArtefactoModelo,
    construir_features,
    costo_negocio,
    optimizar_factores,
    razon_critica,
)


@pytest.fixture(scope="module")
def ventas_t5(historico):
    return historico[(historico["tienda_id"] == 5) & (historico["fecha"] >= "2025-09-01")].reset_index(drop=True)


def test_features_no_usan_el_mismo_dia_ni_el_futuro(ventas_t5, cat):
    base = construir_features(ventas_t5, ventas_t5, cat)
    alterado = ventas_t5.copy()
    corte = "2025-12-01"
    alterado.loc[alterado["fecha"] >= corte, "ventas"] = 10**6
    nuevo = construir_features(alterado, ventas_t5, cat)
    m = base["fecha"] <= pd.Timestamp(corte)  # el propio día de corte tampoco puede verse afectado
    cols = [c for c in COLUMNAS_FEATURES if c != "en_promocion"]
    pd.testing.assert_frame_equal(base.loc[m, cols], nuevo.loc[m, cols])
    assert not base.loc[~m, "lag_1"].equals(nuevo.loc[~m, "lag_1"])


def test_lags_y_medias_correctos(ventas_t5, cat):
    f = construir_features(ventas_t5, ventas_t5, cat)
    fila = f[(f["fecha"] == "2025-11-17") & (f["familia_id"] == "abarrotes")].iloc[0]
    serie = ventas_t5[ventas_t5["familia_id"] == "abarrotes"].set_index("fecha")["ventas"]
    assert fila["lag_1"] == serie["2025-11-16"] and fila["lag_7"] == serie["2025-11-10"]
    assert fila["media_7"] == pytest.approx(serie["2025-11-10":"2025-11-16"].mean())
    assert fila["dias_desde_ultimo"] == 1


def test_serving_con_hueco_usa_ultimo_valor(ventas_t5, cat):
    hist = ventas_t5[ventas_t5["fecha"] <= "2025-11-01"]
    obj = pd.DataFrame([{"fecha": "2025-11-17", "tienda_id": 5, "familia_id": "bebe", "en_promocion": 2}])
    f = construir_features(hist, obj, cat).iloc[0]
    assert np.isnan(f["lag_1"]) and f["dias_desde_ultimo"] == 16
    assert f["ultimo_valor"] == hist[(hist["familia_id"] == "bebe")]["ventas"].iloc[-1]
    assert f["en_promocion"] == 2


def test_feriados_nacionales_y_por_ciudad(cat):
    obj = pd.DataFrame([
        {"fecha": "2025-09-15", "tienda_id": 2, "familia_id": "bebe", "en_promocion": 0},  # nacional
        {"fecha": "2025-07-25", "tienda_id": 6, "familia_id": "bebe", "en_promocion": 0},  # Antigua Guatemala
        {"fecha": "2025-07-25", "tienda_id": 1, "familia_id": "bebe", "en_promocion": 0},  # no aplica
        {"fecha": "2025-08-15", "tienda_id": 1, "familia_id": "bebe", "en_promocion": 0},  # ciudad Guatemala
        {"fecha": "2025-08-15", "tienda_id": 2, "familia_id": "bebe", "en_promocion": 0},  # Mixco: no aplica
        {"fecha": "2025-09-14", "tienda_id": 3, "familia_id": "bebe", "en_promocion": 0},  # víspera nacional
    ])
    f = construir_features(pd.DataFrame(columns=["fecha", "tienda_id", "familia_id", "ventas"]), obj, cat)
    assert f["es_feriado"].tolist() == [1, 1, 0, 1, 0, 0]
    assert f["vispera_feriado"].tolist()[-1] == 1


def test_costo_negocio_asimetrico(cat):
    fam = pd.Series(["panaderia", "panaderia", "licores"])
    # panadería: faltante 1.0, sobrante 2.5 ; licores: faltante 2.0
    assert costo_negocio([10, 10, 10], [12, 8, 9], fam, cat.costos) == pytest.approx(2 * 2.5 + 2 * 1.0 + 1 * 2.0)


def test_factores_minimizan_costo_y_siguen_razon_critica(cat):
    rng = np.random.default_rng(0)
    pred = np.full(2000, 100.0)
    real = rng.poisson(100, 2000)
    fams = pd.Series(["licores"] * 1000 + ["panaderia"] * 1000)
    f = optimizar_factores(pred, real, fams, cat.costos)
    rc = razon_critica(cat.costos)
    assert rc["licores"] > 0.9 and rc["panaderia"] < 0.3
    assert f["licores"] > 1.0 > f["panaderia"]  # faltar licores es caro; sobrar pan es caro
    cantidad = np.rint(pred * fams.map(f).to_numpy())
    assert costo_negocio(real, cantidad, fams, cat.costos) < costo_negocio(real, pred, fams, cat.costos)


def test_artefacto_devuelve_cantidades_enteras_no_negativas(ventas_t5, cat):
    feats = construir_features(ventas_t5, ventas_t5, cat).tail(50)
    art = ArtefactoModelo(tipo="baseline", estimador=None, factores={"abarrotes": 1.5})
    venta, cantidad = art.predecir(feats)
    assert cantidad.dtype.kind == "i" and (cantidad >= 0).all() and (venta >= 0).all()


def test_entrenamiento_metricas_y_ventanas(historico, cat):
    df = historico[historico["tienda_id"].isin([1, 10]) & (historico["fecha"] >= "2025-08-01")]
    res = entrenar_candidato(df, cat, params={"max_iter": 50})
    assert res.ventanas == Ventanas.desde_fecha_max(pd.Timestamp("2026-02-28").date())
    assert res.artefacto.fecha_corte == "2026-01-31"
    for k in ("mae_validacion", "rmse_validacion", "costo_total_validacion"):
        assert res.metricas[k] > 0 and res.metricas_baseline[k] > 0
    assert set(res.artefacto.factores) == set(cat.familias)
    assert res.linaje["filas_validacion"] == 2 * 12 * 28


def test_entrenamiento_rechaza_datos_insuficientes(historico, cat):
    df = historico[historico["fecha"] >= "2026-01-15"]
    with pytest.raises(ValueError, match="insuficientes"):
        entrenar_candidato(df, cat)


@pytest.mark.parametrize("cand, vig, esperado", [
    (90.0, 100.0, True), (100.0, 100.0, False), (110.0, 100.0, False), (50.0, None, True),
])
def test_compuerta_de_reemplazo(cand, vig, esperado):
    promover, motivo = decidir_promocion(cand, vig)
    assert promover is esperado and motivo
