"""Pruebas de los endpoints de la API con dependencias simuladas (sin MLflow, Airflow ni Docker)."""

from __future__ import annotations

import copy
import time
from datetime import date
from pathlib import Path

import joblib
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert

from api.main import Contexto, crear_app
from api.salud import MonitorSalud
from api.servicio_modelo import ServicioModelo
from novamercado.db import (
    Repositorio,
    cargar_catalogos_en_bd,
    crear_motor,
    inicializar_esquema,
    predicciones,
    solicitudes,
    ventas,
)
from novamercado.entrenamiento import entrenar_candidato

from tests.conftest import DIR_ERRORES, DIR_EJEMPLOS, leer_json

TIENDAS_PRUEBA = (5, 10)


# --------------------------------------------------------------------------- #
# Dobles de prueba
# --------------------------------------------------------------------------- #
class RegistroFalso:
    """Imita RegistroMlflow: versiones -> artefactos y alias -> versión."""

    def __init__(self):
        self.versiones: dict[str, object] = {}
        self.alias: dict[str, str] = {}
        self.caido = False
        self.descargas = 0

    def version_por_alias(self, alias="champion"):
        if self.caido:
            raise ConnectionError("MLflow no responde")
        return self.alias.get(alias)

    def descargar(self, version, destino):
        if self.caido:
            raise ConnectionError("MLflow no responde")
        self.descargas += 1
        ruta = Path(destino) / "modelo" / "artifacts" / "artefacto.joblib"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.versiones[version], ruta)
        return ruta


class AirflowFalso:
    def __init__(self):
        self.disparos: list[dict] = []
        self.estado_corrida = "running"
        self.caido = False

    def disparar(self, conf, dag_run_id=None):
        if self.caido:
            raise ConnectionError("Airflow no responde")
        self.disparos.append(conf)
        return dag_run_id or "manual__1"

    def estado(self, dag_run_id):
        return self.estado_corrida


class Dependencias:
    def __init__(self):
        self.caidas: set[str] = set()

    def verificador(self, nombre):
        def _verificar():
            if nombre in self.caidas:
                raise ConnectionError(f"{nombre} caído")
        return _verificar


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def ventas_prueba(historico) -> pd.DataFrame:
    df = historico[historico["tienda_id"].isin(TIENDAS_PRUEBA) & (historico["fecha"] >= "2025-07-01")]
    return df.reset_index(drop=True)


@pytest.fixture(scope="session")
def artefactos(ventas_prueba, cat):
    """Dos versiones de modelo: v1 (HGB) y v2 (baseline) para probar el hot-reload."""
    res = entrenar_candidato(ventas_prueba, cat, params={"max_iter": 60})
    return {"1": res.artefacto, "2": res.baseline}


@pytest.fixture
def entorno(tmp_path, cat, ventas_prueba, artefactos):
    motor = crear_motor("sqlite://")
    inicializar_esquema(motor)
    cargar_catalogos_en_bd(motor, cat)
    filas = ventas_prueba.assign(fecha=pd.to_datetime(ventas_prueba["fecha"]).dt.date, origen="historico")
    with motor.begin() as con:
        con.execute(insert(ventas), filas.to_dict("records"))
    repo = Repositorio(motor)

    registro = RegistroFalso()
    registro.versiones.update(artefactos)
    registro.alias["champion"] = "1"
    servicio = ServicioModelo(lambda: registro, tmp_path / "cache")
    servicio.sincronizar()
    deps = Dependencias()
    monitor = MonitorSalud({n: deps.verificador(n) for n in ("base_datos", "mlflow", "airflow")})
    airflow = AirflowFalso()
    ctx = Contexto(repo=repo, servicio=servicio, monitor=monitor, airflow=airflow, cargar_catalogos=lambda: cat)
    app = crear_app(lambda: ctx, iniciar_tareas=False)
    with TestClient(app) as cliente:
        yield {"cliente": cliente, "repo": repo, "registro": registro, "servicio": servicio, "deps": deps,
               "airflow": airflow, "ctx": ctx, "monitor": monitor, "tmp": tmp_path}
    motor.dispose()


def _prediccion_valida():
    return leer_json(DIR_EJEMPLOS / "prediccion_valida.json")


# --------------------------------------------------------------------------- #
# POST /v1/prediccion
# --------------------------------------------------------------------------- #
def test_prediccion_valida_formato_completo(entorno):
    r = entorno["cliente"].post("/v1/prediccion", json=_prediccion_valida())
    assert r.status_code == 200, r.text
    d = r.json()
    assert set(d) == {"tienda_id", "fecha", "version_modelo", "predicciones", "calidad"}
    assert d["tienda_id"] == 5 and d["fecha"] == "2025-11-17"
    assert isinstance(d["version_modelo"], str) and d["version_modelo"] == "1"
    assert d["calidad"] == {"estado": "ok", "observaciones": []}
    assert len(d["predicciones"]) == 12
    for p in d["predicciones"]:
        assert set(p) == {"familia_id", "venta_esperada", "cantidad_sugerida"}  # exacto según el Anexo
        assert isinstance(p["familia_id"], str)
        assert isinstance(p["cantidad_sugerida"], int) and p["cantidad_sugerida"] >= 0
        assert isinstance(p["venta_esperada"], float) and p["venta_esperada"] >= 0


def test_prediccion_registra_solicitud_y_predicciones_con_version(entorno):
    entorno["cliente"].post("/v1/prediccion", json=_prediccion_valida())
    repo = entorno["repo"]
    (sol,) = repo.listar(solicitudes)
    assert sol["http_status"] == 200 and sol["estado_calidad"] == "ok"
    preds = repo.listar(predicciones, solicitud_id=sol["id"])
    assert len(preds) == 12 and {p["version_modelo"] for p in preds} == {"1"}


@pytest.mark.parametrize("archivo, estado", [
    ("E01_tienda_texto.json", "corregido"), ("E02_familia_otra_forma.json", "corregido"),
    ("E03_promocion_texto.json", "corregido"), ("E04_fecha_formato.json", "corregido"),
    ("E05_faltan_familias.json", "advertencia"), ("E06_familia_repetida.json", "advertencia"),
    ("E07_campo_renombrado.json", "corregido"),
])
def test_prediccion_con_errores_reparables(entorno, archivo, estado):
    r = entorno["cliente"].post("/v1/prediccion", json=leer_json(DIR_ERRORES / archivo))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["calidad"]["estado"] == estado and d["calidad"]["observaciones"]
    assert all(o["accion"] in ("reparar", "advertir") for o in d["calidad"]["observaciones"])


@pytest.mark.parametrize("cambio", [{"tienda_id": 99}, {"fecha": "2025-02-30"}, {"familias": []}])
def test_prediccion_invalida_422_con_detail(entorno, cambio):
    r = entorno["cliente"].post("/v1/prediccion", json={**_prediccion_valida(), **cambio})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, list) and detail[0]["accion"] == "rechazar" and detail[0]["detalle"]
    (sol,) = entorno["repo"].listar(solicitudes)
    assert sol["http_status"] == 422


def test_prediccion_cuerpo_no_json_422(entorno):
    r = entorno["cliente"].post("/v1/prediccion", content=b"{no es json", headers={"content-type": "application/json"})
    assert r.status_code == 422 and r.json()["detail"][0]["campo"] == "cuerpo"


def test_prediccion_no_usa_observaciones_del_mismo_dia_ni_futuras(entorno):
    """Cero fuga: agregar datos con fecha >= D no cambia el pronóstico de D."""
    cliente, repo = entorno["cliente"], entorno["repo"]
    antes = cliente.post("/v1/prediccion", json=_prediccion_valida()).json()["predicciones"]
    for d in ("2025-11-17", "2025-11-20"):
        repo.guardar_observaciones(5, d, [{"familia_id": p["familia_id"], "ventas": 99999} for p in antes])
    despues = cliente.post("/v1/prediccion", json=_prediccion_valida()).json()["predicciones"]
    assert antes == despues


def test_prediccion_si_usa_el_dia_anterior(entorno):
    cliente, repo = entorno["cliente"], entorno["repo"]
    antes = cliente.post("/v1/prediccion", json=_prediccion_valida()).json()["predicciones"]
    repo.guardar_observaciones(5, "2025-11-16", [{"familia_id": p["familia_id"], "ventas": 5000} for p in antes])
    despues = cliente.post("/v1/prediccion", json=_prediccion_valida()).json()["predicciones"]
    assert antes != despues


def test_prediccion_sin_modelo_503(entorno):
    entorno["servicio"]._actual = None
    r = entorno["cliente"].post("/v1/prediccion", json=_prediccion_valida())
    assert r.status_code == 503


# --------------------------------------------------------------------------- #
# POST /v1/observaciones
# --------------------------------------------------------------------------- #
def test_observaciones_idempotentes(entorno):
    obs = leer_json(DIR_EJEMPLOS / "observacion_valida.json")
    obs["fecha"] = "2026-03-01"  # posterior al histórico
    c = entorno["cliente"]
    r1 = c.post("/v1/observaciones", json=obs)
    r2 = c.post("/v1/observaciones", json=obs)
    assert r1.status_code == 200 and r1.json() == {"registros_guardados": 12,
                                                    "calidad": {"estado": "ok", "observaciones": []}}
    assert r2.status_code == 200 and r2.json()["registros_guardados"] == 0


def test_observaciones_sobre_historico_existente_no_cuentan(entorno):
    obs = leer_json(DIR_ERRORES / "E09_envio_repetido.json")
    r = entorno["cliente"].post("/v1/observaciones", json=obs)
    assert r.status_code == 200
    # 2025-11-17 de la tienda 5 ya está en el histórico: solo cuentan las filas que difieren
    previo = {v["familia_id"]: v["ventas"] for v in entorno["repo"].obtener_ventas(5, "2025-11-17")}
    assert all(previo[v["familia_id"]] == v["ventas"] for v in obs["ventas"])
    assert entorno["cliente"].post("/v1/observaciones", json=obs).json()["registros_guardados"] == 0


def test_observaciones_reparadas_y_rechazadas(entorno):
    c = entorno["cliente"]
    e10 = leer_json(DIR_ERRORES / "E10_numero_formato.json")
    e10["fecha"] = "2026-03-02"
    r = c.post("/v1/observaciones", json=e10)
    assert r.status_code == 200 and r.json()["calidad"]["estado"] == "corregido"
    assert r.json()["registros_guardados"] == 12
    r = c.post("/v1/observaciones", json=leer_json(DIR_ERRORES / "E08_ventas_negativas.json"))
    assert r.status_code == 422 and r.json()["detail"][0]["campo"] == "ventas[5].ventas"


def test_observaciones_actualizan_valor_cambiado(entorno):
    obs = leer_json(DIR_EJEMPLOS / "observacion_valida.json")
    obs["fecha"] = "2026-03-03"
    c = entorno["cliente"]
    c.post("/v1/observaciones", json=obs)
    obs["ventas"][0]["ventas"] += 1
    assert c.post("/v1/observaciones", json=obs).json()["registros_guardados"] == 1


# --------------------------------------------------------------------------- #
# /admin/reentrenar
# --------------------------------------------------------------------------- #
def test_reentrenar_202_y_estado_en_curso(entorno):
    c = entorno["cliente"]
    r = c.post("/admin/reentrenar")
    assert r.status_code == 202
    id_ = r.json()["id"]
    assert isinstance(id_, str) and set(r.json()) == {"id"}
    assert entorno["airflow"].disparos == [{"ejecucion_id": id_}]
    e = c.get(f"/admin/reentrenar/{id_}")
    assert e.status_code == 200 and e.json() == {"estado": "en_curso"}


def test_reentrenar_exitoso_incluye_promovido_version_motivo(entorno):
    c, repo = entorno["cliente"], entorno["repo"]
    id_ = c.post("/admin/reentrenar").json()["id"]
    repo.actualizar_ejecucion(id_, estado="exitoso", promovido=True, version="2",
                              motivo="el candidato redujo el costo")
    d = c.get(f"/admin/reentrenar/{id_}").json()
    assert d == {"estado": "exitoso", "promovido": True, "version": "2",
                 "motivo": "el candidato redujo el costo"}
    assert isinstance(d["version"], str) and isinstance(d["promovido"], bool)


def test_reentrenar_fallido_en_airflow_se_refleja(entorno):
    c = entorno["cliente"]
    id_ = c.post("/admin/reentrenar").json()["id"]
    entorno["airflow"].estado_corrida = "failed"
    d = c.get(f"/admin/reentrenar/{id_}").json()
    assert d["estado"] == "fallido" and d["promovido"] is False
    assert d["version"] == "1" and "failed" in d["motivo"]


def test_reentrenar_id_inexistente_404(entorno):
    r = entorno["cliente"].get("/admin/reentrenar/no-existe")
    assert r.status_code == 404 and "detail" in r.json()


def test_reentrenar_airflow_caido_503(entorno):
    entorno["airflow"].caido = True
    r = entorno["cliente"].post("/admin/reentrenar")
    assert r.status_code == 503
    fila = entorno["repo"].obtener_ejecucion(r.json()["id"])
    assert fila["estado"] == "fallido"


# --------------------------------------------------------------------------- #
# GET /modelo y hot-reload
# --------------------------------------------------------------------------- #
def test_modelo_devuelve_textos(entorno):
    r = entorno["cliente"].get("/modelo")
    assert r.status_code == 200
    assert r.json() == {"nombre": "novamercado-pronostico", "alias": "champion", "version": "1"}


def test_hot_reload_cambia_version_sin_reiniciar(entorno):
    c, registro, servicio = entorno["cliente"], entorno["registro"], entorno["servicio"]
    assert servicio.sincronizar() is False  # misma versión: no descarga de nuevo
    registro.alias["champion"] = "2"
    assert servicio.sincronizar() is True
    assert c.get("/modelo").json()["version"] == "2"
    assert c.post("/v1/prediccion", json=_prediccion_valida()).json()["version_modelo"] == "2"


def test_cache_local_permite_arrancar_con_mlflow_caido(entorno):
    registro = entorno["registro"]
    registro.caido = True
    nuevo = ServicioModelo(lambda: registro, entorno["tmp"] / "cache")
    assert nuevo.actual is None and nuevo.cargar_cache() is True
    assert nuevo.actual.version == "1" and nuevo.actual.origen == "cache"
    assert nuevo.sincronizar() is False and "MLflow" in nuevo.ultimo_error
    assert nuevo.actual.version == "1"


def test_cache_corrupta_se_ignora(tmp_path):
    (tmp_path / "modelo_cache.joblib").write_bytes(b"basura")
    assert ServicioModelo(None, tmp_path).cargar_cache() is False


# --------------------------------------------------------------------------- #
# GET /health y modo degradado
# --------------------------------------------------------------------------- #
def test_health_ok(entorno):
    r = entorno["cliente"].get("/health")
    assert r.status_code == 200 and r.json() == {"estado": "ok"}


def test_health_sin_modelo_503(entorno):
    entorno["servicio"]._actual = None
    r = entorno["cliente"].get("/health")
    assert r.status_code == 503 and r.json()["estado"] != "ok"


@pytest.mark.parametrize("dependencia", ["mlflow", "airflow"])
def test_modo_degradado_sigue_prediciendo(entorno, dependencia):
    c, deps, monitor = entorno["cliente"], entorno["deps"], entorno["monitor"]
    deps.caidas.add(dependencia)
    entorno["registro"].caido = dependencia == "mlflow"
    monitor.verificar_todo()  # lo que hace la tarea periódica cada 15 s
    r = c.get("/health")
    assert r.status_code == 200 and r.json()["estado"] == "degradado"
    assert dependencia in r.json()["motivo"]
    entorno["servicio"].sincronizar()  # el hot-reload falla, pero el modelo en memoria sigue
    p = c.post("/v1/prediccion", json=_prediccion_valida())
    assert p.status_code == 200 and p.json()["version_modelo"] == "1"
    # la dependencia regresa -> vuelve a "ok" en el siguiente chequeo
    deps.caidas.clear()
    entorno["registro"].caido = False
    monitor.verificar_todo()
    assert c.get("/health").json() == {"estado": "ok"}


def test_health_verifica_en_vivo_si_el_chequeo_es_viejo(entorno):
    deps, monitor = entorno["deps"], entorno["monitor"]
    monitor.verificar_todo()
    deps.caidas.add("mlflow")
    for nombre, r in list(monitor.resultados.items()):
        monitor.resultados[nombre] = type(r)(r.ok, r.detalle, time.time() - 60)
    assert entorno["cliente"].get("/health").json()["estado"] == "degradado"


def test_base_de_datos_caida_responde_503_en_operaciones(entorno):
    entorno["repo"].motor.dispose()
    from sqlalchemy import create_engine

    entorno["repo"].motor = create_engine("postgresql+psycopg://x:y@127.0.0.1:1/z",
                                          connect_args={"connect_timeout": 1})
    r = entorno["cliente"].post("/v1/observaciones", json=leer_json(DIR_EJEMPLOS / "observacion_valida.json"))
    assert r.status_code == 503 and "base de datos" in r.json()["detail"]
