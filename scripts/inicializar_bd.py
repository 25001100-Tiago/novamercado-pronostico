"""Crea el esquema y carga catálogos + histórico en la base de datos.

Uso:  python scripts/inicializar_bd.py [--url postgresql+psycopg://...]
Es idempotente: se puede ejecutar varias veces sin duplicar datos.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from novamercado.catalogos import cargar_catalogos  # noqa: E402
from novamercado.config import directorio_datos  # noqa: E402
from novamercado.db import (  # noqa: E402
    Repositorio,
    cargar_catalogos_en_bd,
    cargar_historico,
    crear_motor,
    inicializar_esquema,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=None, help="URL SQLAlchemy (por defecto DATABASE_URL)")
    args = parser.parse_args()

    motor = crear_motor(args.url)
    inicializar_esquema(motor)
    cargar_catalogos_en_bd(motor, cargar_catalogos())
    nuevas = cargar_historico(motor, directorio_datos() / "historico_ventas.csv")
    total = Repositorio(motor).contar_ventas()
    print(f"Esquema listo. Histórico: {nuevas} filas nuevas, {total} filas en total.")


if __name__ == "__main__":
    main()
