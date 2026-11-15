"""Entrenamiento, evaluación, compuerta de reemplazo y pasos de orquestación.

Esquema temporal (todas las ventanas se derivan de la última fecha con datos ``F``):

    ... entrenamiento_calibración ... | calibración (28 d) | validación (28 d) = [F-27, F]
    modelo desplegado: ajustado con datos < inicio de validación

* El modelo de calibración (datos < calibración) predice la ventana de calibración y con
  esas predicciones fuera de muestra se optimiza el factor de ``cantidad_sugerida`` por familia.
* El modelo desplegado (datos < validación) se evalúa en la ventana de validación:
  MAE, RMSE y ``costo_total_validacion`` (costo asimétrico de costos.csv).
* Se despliega **exactamente** el artefacto evaluado (no se reajusta después), así el
  @champion vigente nunca vio la ventana de validación de un reentrenamiento posterior y
  la comparación champion vs challenger es fuera de muestra para ambos.

Compuerta: en un reentrenamiento se evalúan el @champion y el challenger en la misma
ventana de validación reciente; se promueve el challenger solo si su costo es menor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from novamercado.catalogos import Catalogos
from novamercado.modelo import (
    COLUMNAS_FEATURES,
    FEATURES_CATEGORICAS,
    ArtefactoModelo,
    construir_features,
    costo_negocio,
    optimizar_factores,
    prediccion_baseline,
    razon_critica,
)

log = logging.getLogger("novamercado.entrenamiento")

DIAS_VALIDACION = 28
DIAS_CALIBRACION = 28
DIAS_MINIMOS_ENTRENAMIENTO = 28

PARAMS_HGB: dict[str, Any] = {
    "loss": "poisson",
    "learning_rate": 0.06,
    "max_iter": 300,
    "max_leaf_nodes": 31,
    "min_samples_leaf": 40,
    "l2_regularization": 1.0,
    "early_stopping": False,
    "random_state": 42,
}


# --------------------------------------------------------------------------- #
# Entrenamiento y evaluación (puro: sin MLflow ni BD)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Ventanas:
    inicio_calibracion: date
    inicio_validacion: date
    fin_validacion: date

    @classmethod
    def desde_fecha_max(cls, fecha_max: date) -> "Ventanas":
        iv = fecha_max - timedelta(days=DIAS_VALIDACION - 1)
        return cls(iv - timedelta(days=DIAS_CALIBRACION), iv, fecha_max)

    def a_dict(self) -> dict[str, str]:
        return {k: v.isoformat() for k, v in self.__dict__.items()}

    @classmethod
    def desde_dict(cls, d: dict[str, str]) -> "Ventanas":
        return cls(**{k: date.fromisoformat(v) for k, v in d.items()})


@dataclass
class ResultadoEntrenamiento:
    artefacto: ArtefactoModelo
    baseline: ArtefactoModelo
    metricas: dict[str, float]
    metricas_baseline: dict[str, float]
    ventanas: Ventanas
    linaje: dict[str, Any]
    segundos: float


def ajustar_hgb(X: pd.DataFrame, y: pd.Series, params: dict[str, Any] | None = None):
    from sklearn.ensemble import HistGradientBoostingRegressor

    categoricas = [c in FEATURES_CATEGORICAS for c in COLUMNAS_FEATURES]
    modelo = HistGradientBoostingRegressor(categorical_features=categoricas, **(params or PARAMS_HGB))
    return modelo.fit(X[COLUMNAS_FEATURES], y)


def evaluar(artefacto: ArtefactoModelo, feats: pd.DataFrame, costos) -> dict[str, float]:
    venta, cantidad = artefacto.predecir(feats)
    real = feats["ventas"].to_numpy(float)
    metricas = {
        "mae_validacion": float(np.mean(np.abs(real - venta))),
        "rmse_validacion": float(np.sqrt(np.mean((real - venta) ** 2))),
        "costo_total_validacion": costo_negocio(real, cantidad, feats["familia_id"], costos),
        "n_validacion": float(len(feats)),
    }
    for fam in sorted(feats["familia_id"].unique()):
        m = (feats["familia_id"] == fam).to_numpy()
        metricas[f"costo_validacion_{fam}"] = costo_negocio(real[m], cantidad[m], feats["familia_id"][m], costos)
    return metricas


def huella_datos(ventas_df: pd.DataFrame) -> str:
    resumen = f"{len(ventas_df)}|{ventas_df['ventas'].sum()}|{ventas_df['fecha'].min()}|{ventas_df['fecha'].max()}"
    return hashlib.sha256(resumen.encode()).hexdigest()[:16]


def features_entrenamiento(ventas_df: pd.DataFrame, cat: Catalogos) -> pd.DataFrame:
    df = ventas_df.copy()
    df["en_promocion"] = df["en_promocion"].fillna(0)
    return construir_features(df, df, cat)


def entrenar_candidato(
    ventas_df: pd.DataFrame, cat: Catalogos, params: dict[str, Any] | None = None
) -> ResultadoEntrenamiento:
    t0 = time.perf_counter()
    feats = features_entrenamiento(ventas_df, cat)
    fecha_max = feats["fecha"].max().date()
    v = Ventanas.desde_fecha_max(fecha_max)
    fmin = feats["fecha"].min().date()
    if (v.inicio_calibracion - fmin).days < DIAS_MINIMOS_ENTRENAMIENTO:
        raise ValueError(
            f"datos insuficientes: se requieren al menos "
            f"{DIAS_MINIMOS_ENTRENAMIENTO + DIAS_CALIBRACION + DIAS_VALIDACION} días (hay {(fecha_max - fmin).days + 1})"
        )
    ic, iv = pd.Timestamp(v.inicio_calibracion), pd.Timestamp(v.inicio_validacion)
    ent_cal = feats[feats["fecha"] < ic]
    cal = feats[(feats["fecha"] >= ic) & (feats["fecha"] < iv)]
    ent = feats[feats["fecha"] < iv]
    val = feats[feats["fecha"] >= iv]

    params = {**PARAMS_HGB, **(params or {})}
    m_cal = ajustar_hgb(ent_cal, ent_cal["ventas"], params)
    factores = optimizar_factores(
        np.maximum(m_cal.predict(cal[COLUMNAS_FEATURES]), 0), cal["ventas"], cal["familia_id"], cat.costos
    )
    modelo = ajustar_hgb(ent, ent["ventas"], params)
    corte = (v.inicio_validacion - timedelta(days=1)).isoformat()
    linaje = {
        "fecha_min_datos": fmin.isoformat(),
        "fecha_max_datos": fecha_max.isoformat(),
        "filas_datos": int(len(ventas_df)),
        "huella_datos": huella_datos(ventas_df),
        **{f"ventana_{k}": x for k, x in v.a_dict().items()},
        "filas_entrenamiento": int(len(ent)),
        "filas_calibracion": int(len(cal)),
        "filas_validacion": int(len(val)),
    }
    artefacto = ArtefactoModelo(
        tipo="hgb", estimador=modelo, factores=factores, fecha_corte=corte,
        metadatos={"params": params, "razon_critica": razon_critica(cat.costos), **linaje},
    )
    factores_base = optimizar_factores(prediccion_baseline(cal), cal["ventas"], cal["familia_id"], cat.costos)
    baseline = ArtefactoModelo(tipo="baseline", estimador=None, factores=factores_base, fecha_corte=corte,
                               metadatos=dict(linaje))
    return ResultadoEntrenamiento(
        artefacto=artefacto,
        baseline=baseline,
        metricas=evaluar(artefacto, val, cat.costos),
        metricas_baseline=evaluar(baseline, val, cat.costos),
        ventanas=v,
        linaje=linaje,
        segundos=time.perf_counter() - t0,
    )


def decidir_promocion(costo_candidato: float, costo_vigente: float | None) -> tuple[bool, str]:
    """Compuerta explícita: promover solo si el challenger reduce el costo de negocio."""
    if costo_vigente is None:
        return True, "no existe un modelo @champion vigente"
    if costo_candidato < costo_vigente:
        mejora = 100 * (costo_vigente - costo_candidato) / costo_vigente if costo_vigente else 0.0
        return True, (f"el candidato redujo el costo de validación de {costo_vigente:.2f} a "
                      f"{costo_candidato:.2f} (-{mejora:.2f}%)")
    return False, (f"el candidato no redujo el costo de validación ({costo_candidato:.2f} frente a "
                   f"{costo_vigente:.2f} del vigente)")


# --------------------------------------------------------------------------- #
# Orquestación (BD del producto + MLflow)
# --------------------------------------------------------------------------- #
def _repo_y_catalogos():
    from novamercado.db import Repositorio, crear_motor, inicializar_esquema, leer_catalogos

    motor = crear_motor()
    inicializar_esquema(motor)
    return Repositorio(motor), leer_catalogos(motor)


def _metricas_planas(res: ResultadoEntrenamiento) -> dict[str, float]:
    m = dict(res.metricas)
    m.update({f"baseline_{k}": x for k, x in res.metricas_baseline.items()})
    m["segundos_entrenamiento"] = res.segundos
    return m


def registrar_candidato(res: ResultadoEntrenamiento, registro, ejecucion_id: str, motivo: str) -> tuple[str, str]:
    etiquetas = {
        "ejecucion_id": ejecucion_id,
        "motivo": motivo,
        "modelo_tipo": "HistGradientBoostingRegressor",
        "baseline": "media de los ultimos 4 mismos dias de la semana",
        **{f"linaje.{k}": str(x) for k, x in res.linaje.items()},
    }
    parametros = {**{f"hgb_{k}": x for k, x in PARAMS_HGB.items()},
                  "dias_validacion": DIAS_VALIDACION, "dias_calibracion": DIAS_CALIBRACION,
                  "features": ",".join(COLUMNAS_FEATURES), **res.linaje}
    return registro.registrar(
        res.artefacto,
        nombre_corrida=f"entrenamiento-{ejecucion_id}",
        parametros=parametros,
        metricas=_metricas_planas(res),
        etiquetas=etiquetas,
        extras={"factores_cantidad_sugerida": res.artefacto.factores,
                "razon_critica": res.artefacto.metadatos.get("razon_critica", {}),
                "metricas_baseline": res.metricas_baseline},
    )


def paso_preparar(ejecucion_id: str | None, airflow_run_id: str | None = None) -> str:
    repo, cat = _repo_y_catalogos()
    if ejecucion_id and repo.obtener_ejecucion(ejecucion_id):
        repo.actualizar_ejecucion(ejecucion_id, estado="en_curso", airflow_run_id=airflow_run_id)
    else:
        ejecucion_id = repo.crear_ejecucion(
            motivo="disparado desde Airflow", id=ejecucion_id or None, airflow_run_id=airflow_run_id
        )
    from novamercado.db import estado_carga

    conteos = estado_carga(repo.motor)
    if conteos["historico"] + conteos["observaciones"] == 0 or not cat.tiendas:
        raise RuntimeError("la base del producto no tiene datos para entrenar")
    log.info("ejecución %s: %s filas disponibles (%s)", ejecucion_id, sum(conteos.values()), conteos)
    return ejecucion_id


def paso_entrenar(ejecucion_id: str) -> dict[str, Any]:
    from novamercado.registro import ALIAS_CHALLENGER, RegistroMlflow

    repo, cat = _repo_y_catalogos()
    ventas_df = repo.leer_ventas_df()
    res = entrenar_candidato(ventas_df, cat)
    registro = RegistroMlflow()
    version, run_id = registrar_candidato(res, registro, ejecucion_id, "reentrenamiento")
    registro.asignar_alias(version, ALIAS_CHALLENGER)
    estado = {
        "version_candidata": version,
        "run_id": run_id,
        "ventanas": res.ventanas.a_dict(),
        "candidato": res.metricas,
        "baseline": res.metricas_baseline,
        "segundos_entrenamiento": res.segundos,
    }
    repo.actualizar_ejecucion(ejecucion_id, metricas=estado)
    log.info("candidato v%s registrado; costo validación %.2f", version, res.metricas["costo_total_validacion"])
    return estado


def paso_promover(ejecucion_id: str) -> dict[str, Any]:
    from novamercado.registro import ALIAS_CHAMPION, RegistroMlflow

    repo, cat = _repo_y_catalogos()
    ejecucion = repo.obtener_ejecucion(ejecucion_id)
    estado = dict((ejecucion or {}).get("metricas") or {})
    if "version_candidata" not in estado:
        raise RuntimeError(f"la ejecución {ejecucion_id} no tiene un candidato registrado")
    registro = RegistroMlflow()
    v = Ventanas.desde_dict(estado["ventanas"])

    feats = features_entrenamiento(repo.leer_ventas_df(), cat)
    val = feats[(feats["fecha"] >= pd.Timestamp(v.inicio_validacion)) & (feats["fecha"] <= pd.Timestamp(v.fin_validacion))]
    candidato = registro.cargar_artefacto(estado["version_candidata"])
    m_cand = evaluar(candidato, val, cat.costos)

    version_vigente = registro.version_por_alias(ALIAS_CHAMPION)
    m_vig = None
    if version_vigente is not None:
        m_vig = evaluar(registro.cargar_artefacto(version_vigente), val, cat.costos)
    promover, razon = decidir_promocion(
        m_cand["costo_total_validacion"], m_vig["costo_total_validacion"] if m_vig else None
    )
    ventana = f"ventana {v.inicio_validacion}..{v.fin_validacion}"
    if promover:
        registro.asignar_alias(estado["version_candidata"], ALIAS_CHAMPION)
        motivo = f"{razon} en la {ventana}; v{estado['version_candidata']} promovida a @champion"
        if version_vigente:
            motivo += f" (antes v{version_vigente})"
    else:
        motivo = f"{razon} en la {ventana}; se conserva v{version_vigente} como @champion"
    version_final = registro.version_por_alias(ALIAS_CHAMPION)

    registro.registrar_metricas(
        estado["run_id"],
        {"costo_candidato_compuerta": m_cand["costo_total_validacion"],
         **({"costo_champion_compuerta": m_vig["costo_total_validacion"]} if m_vig else {})},
        {"compuerta.promovido": promover, "compuerta.champion_previo": version_vigente or "ninguno"},
    )
    estado["compuerta"] = {
        "costo_candidato": m_cand["costo_total_validacion"],
        "costo_champion": m_vig["costo_total_validacion"] if m_vig else None,
        "version_champion_previa": version_vigente,
        "promovido": promover,
    }
    repo.actualizar_ejecucion(
        ejecucion_id, estado="exitoso", promovido=promover, version=str(version_final), motivo=motivo, metricas=estado
    )
    log.info(motivo)
    return estado


def paso_fallar(ejecucion_id: str | None, motivo: str) -> None:
    if not ejecucion_id:
        return
    repo, _ = _repo_y_catalogos()
    version = None
    try:
        from novamercado.registro import RegistroMlflow

        version = RegistroMlflow().version_por_alias()
    except Exception as e:  # MLflow caído: el estado igual debe cerrarse
        log.warning("no se pudo consultar @champion: %s", e)
    if repo.obtener_ejecucion(ejecucion_id) is None:
        repo.crear_ejecucion(motivo=motivo, id=ejecucion_id)
    repo.actualizar_ejecucion(
        ejecucion_id, estado="fallido", promovido=False, version=str(version) if version else "", motivo=motivo
    )


# --------------------------------------------------------------------------- #
# CLI (usada por el DAG de Airflow y por el bootstrap)
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="python -m novamercado.entrenamiento")
    p.add_argument("paso", choices=["preparar", "entrenar", "promover", "fallar"])
    p.add_argument("--ejecucion-id", default=os.getenv("EJECUCION_ID") or None)
    p.add_argument("--airflow-run-id", default=os.getenv("AIRFLOW_RUN_ID") or None)
    p.add_argument("--motivo", default="falló una tarea del DAG de reentrenamiento")
    a = p.parse_args(argv)
    if a.paso == "preparar":
        print(paso_preparar(a.ejecucion_id, a.airflow_run_id))  # última línea -> XCom
        return 0
    if not a.ejecucion_id and a.paso != "fallar":
        p.error("--ejecucion-id es obligatorio")
    if a.paso == "entrenar":
        print(json.dumps(paso_entrenar(a.ejecucion_id), default=str)[:2000])
    elif a.paso == "promover":
        print(json.dumps(paso_promover(a.ejecucion_id), default=str)[:2000])
    else:
        paso_fallar(a.ejecucion_id, a.motivo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
