"""Configuración central leída de variables de entorno (con .env opcional)."""

from __future__ import annotations

import os
from pathlib import Path

try:  # python-dotenv es opcional: en contenedores las variables llegan por entorno.
    from dotenv import load_dotenv

    load_dotenv(override=False)
except ImportError:  # pragma: no cover
    pass

RAIZ_PROYECTO = Path(__file__).resolve().parents[2]

URL_BD_POR_DEFECTO = "postgresql+psycopg://novamercado:novamercado@localhost:5432/novamercado"


def directorio_datos() -> Path:
    """Directorio con los catálogos y el histórico crudo."""
    ruta = Path(os.getenv("NOVAMERCADO_DATA_DIR", RAIZ_PROYECTO / "data" / "raw"))
    return ruta if ruta.is_absolute() else (RAIZ_PROYECTO / ruta)


def url_base_datos() -> str:
    """URL SQLAlchemy de la base de datos (PostgreSQL en operación)."""
    return os.getenv("DATABASE_URL", URL_BD_POR_DEFECTO)
