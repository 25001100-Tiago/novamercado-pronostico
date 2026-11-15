"""Catálogos oficiales (tiendas, familias, costos, feriados) y estadísticas de referencia.

Las estadísticas del histórico (máximos por tienda/familia, rango de fechas) son la
referencia para detectar valores extremos y para el horizonte de predicción. Nunca se
usa el reloj del sistema: el servicio opera con fechas simuladas.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from novamercado.config import directorio_datos


@dataclass(frozen=True)
class Tienda:
    tienda_id: int
    nombre: str
    ciudad: str
    departamento: str
    tipo: str
    fecha_apertura: date


@dataclass(frozen=True, eq=False)
class Catalogos:
    tiendas: dict[int, Tienda]
    familias: dict[str, str]  # familia_id -> nombre visible
    costos: dict[str, dict[str, float]]
    feriados: tuple[dict, ...]
    max_ventas: dict[tuple[int, str], int]  # (tienda, familia) -> máximo histórico
    max_ventas_familia: dict[str, int]
    max_promo_familia: dict[str, int]
    familias_por_tienda: dict[int, frozenset[str]]
    fecha_min_historico: date | None
    fecha_max_historico: date | None

    def familias_esperadas(self, tienda_id: int | None) -> frozenset[str]:
        """Familias que la tienda vende según el histórico (todas si no hay histórico)."""
        if tienda_id is not None and tienda_id in self.familias_por_tienda:
            return self.familias_por_tienda[tienda_id]
        return frozenset(self.familias)


def _leer_csv(ruta: Path) -> list[dict[str, str]]:
    with open(ruta, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def construir_catalogos(directorio: Path) -> Catalogos:
    tiendas = {
        int(f["tienda_id"]): Tienda(
            tienda_id=int(f["tienda_id"]),
            nombre=f["nombre"],
            ciudad=f["ciudad"],
            departamento=f["departamento"],
            tipo=f["tipo"],
            fecha_apertura=date.fromisoformat(f["fecha_apertura"]),
        )
        for f in _leer_csv(directorio / "tiendas.csv")
    }
    familias = {f["familia_id"]: f["nombre"] for f in _leer_csv(directorio / "familias.csv")}

    costos: dict[str, dict[str, float]] = {}
    if (directorio / "costos.csv").exists():
        costos = {
            f["familia_id"]: {
                "costo_faltante": float(f["costo_faltante"]),
                "costo_sobrante": float(f["costo_sobrante"]),
            }
            for f in _leer_csv(directorio / "costos.csv")
        }

    feriados: tuple[dict, ...] = ()
    if (directorio / "feriados.csv").exists():
        feriados = tuple(
            {**f, "fecha": date.fromisoformat(f["fecha"])}
            for f in _leer_csv(directorio / "feriados.csv")
        )

    max_ventas: dict[tuple[int, str], int] = {}
    max_ventas_familia: dict[str, int] = {}
    max_promo_familia: dict[str, int] = {}
    familias_por_tienda: dict[int, set[str]] = {}
    fecha_min = fecha_max = None
    ruta_hist = directorio / "historico_ventas.csv"
    if ruta_hist.exists():
        with open(ruta_hist, encoding="utf-8", newline="") as f:
            for fila in csv.DictReader(f):
                t, fam = int(fila["tienda_id"]), fila["familia_id"]
                v, p = int(float(fila["ventas"])), int(float(fila["en_promocion"]))
                if v > max_ventas.get((t, fam), -1):
                    max_ventas[(t, fam)] = v
                if v > max_ventas_familia.get(fam, -1):
                    max_ventas_familia[fam] = v
                if p > max_promo_familia.get(fam, -1):
                    max_promo_familia[fam] = p
                familias_por_tienda.setdefault(t, set()).add(fam)
                d = fila["fecha"]  # ISO: la comparación lexicográfica equivale a la cronológica
                if fecha_min is None or d < fecha_min:
                    fecha_min = d
                if fecha_max is None or d > fecha_max:
                    fecha_max = d

    return Catalogos(
        tiendas=tiendas,
        familias=familias,
        costos=costos,
        feriados=feriados,
        max_ventas=max_ventas,
        max_ventas_familia=max_ventas_familia,
        max_promo_familia=max_promo_familia,
        familias_por_tienda={t: frozenset(s) for t, s in familias_por_tienda.items()},
        fecha_min_historico=date.fromisoformat(fecha_min) if fecha_min else None,
        fecha_max_historico=date.fromisoformat(fecha_max) if fecha_max else None,
    )


@lru_cache(maxsize=4)
def _cargar(ruta: str) -> Catalogos:
    return construir_catalogos(Path(ruta))


def cargar_catalogos(directorio: str | Path | None = None) -> Catalogos:
    """Carga (con caché) los catálogos desde el directorio de datos crudos."""
    return _cargar(str(Path(directorio or directorio_datos()).resolve()))
