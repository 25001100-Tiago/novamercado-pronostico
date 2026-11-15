from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from novamercado.catalogos import cargar_catalogos
from novamercado.db import Repositorio, cargar_catalogos_en_bd, crear_motor, inicializar_esquema, metadata

DIR_DATOS = Path(__file__).resolve().parents[1] / "data" / "raw"
DIR_EJEMPLOS = DIR_DATOS / "ejemplos"
DIR_ERRORES = DIR_DATOS / "errores"
HAY_DATOS = (DIR_DATOS / "tiendas.csv").exists() and (DIR_DATOS / "historico_ventas.csv").exists()


def pytest_collection_modifyitems(config, items):
    """Los datos publicados no se versionan: sin data/raw las pruebas se omiten con aviso."""
    if HAY_DATOS:
        return
    marca = pytest.mark.skip(reason="faltan los datos publicados en data/raw/ (ver README)")
    for item in items:
        item.add_marker(marca)


def leer_json(ruta: Path) -> dict:
    return json.loads(ruta.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def cat():
    return cargar_catalogos(DIR_DATOS)


@pytest.fixture(scope="session")
def historico() -> pd.DataFrame:
    return pd.read_csv(DIR_DATOS / "historico_ventas.csv")


@pytest.fixture
def pred_valida() -> dict:
    return copy.deepcopy(leer_json(DIR_EJEMPLOS / "prediccion_valida.json"))


@pytest.fixture
def obs_valida() -> dict:
    return copy.deepcopy(leer_json(DIR_EJEMPLOS / "observacion_valida.json"))


def _urls_bd() -> list:
    urls = [pytest.param("sqlite://", id="sqlite-memoria")]
    if os.getenv("TEST_DATABASE_URL"):  # p. ej. el PostgreSQL de docker compose
        urls.append(pytest.param(os.environ["TEST_DATABASE_URL"], id="postgresql"))
    return urls


@pytest.fixture(params=_urls_bd())
def motor(request, cat):
    m = crear_motor(request.param)
    metadata.drop_all(m)
    inicializar_esquema(m)
    cargar_catalogos_en_bd(m, cat)
    yield m
    metadata.drop_all(m)
    m.dispose()


@pytest.fixture
def repo(motor) -> Repositorio:
    return Repositorio(motor)
