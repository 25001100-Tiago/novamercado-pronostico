"""Inicialización idempotente del stack (servicio ``bootstrap`` de docker compose).

1. Espera a PostgreSQL del producto, crea el esquema y carga los CSV de ``data/raw``
   **solo si** aún no están cargados.
2. Espera a MLflow y, **solo si** no existe ``novamercado-pronostico@champion``,
   entrena y registra el primer modelo y le asigna el alias ``champion``.

Con volúmenes existentes detecta que datos y modelo ya están y termina sin rehacer nada.
"""

from __future__ import annotations

import logging
import sys
import time
import uuid
from typing import Callable

log = logging.getLogger("novamercado.bootstrap")


def esperar(nombre: str, verificar: Callable[[], object], limite: float = 300, pausa: float = 3) -> None:
    inicio = time.time()
    while True:
        try:
            verificar()
            log.info("%s disponible", nombre)
            return
        except Exception as e:
            if time.time() - inicio > limite:
                raise RuntimeError(f"{nombre} no respondió en {limite:.0f} s: {e}") from e
            log.info("esperando a %s (%s)", nombre, type(e).__name__)
            time.sleep(pausa)


def asegurar_datos(motor) -> dict[str, int]:
    from novamercado.catalogos import cargar_catalogos
    from novamercado.config import directorio_datos
    from novamercado.db import cargar_catalogos_en_bd, cargar_historico, estado_carga, inicializar_esquema

    inicializar_esquema(motor)
    conteos = estado_carga(motor)
    directorio = directorio_datos()
    if conteos["tiendas"] and conteos["familias"]:
        log.info("catálogos ya cargados (%s tiendas, %s familias): se conservan", conteos["tiendas"], conteos["familias"])
    else:
        if not (directorio / "tiendas.csv").exists():
            raise FileNotFoundError(f"faltan los CSV publicados en {directorio} (ver README: data/raw/)")
        cargar_catalogos_en_bd(motor, cargar_catalogos(directorio))
        log.info("catálogos cargados desde %s", directorio)
    if conteos["historico"]:
        log.info("histórico ya cargado (%s filas) y %s observaciones: se conservan",
                 conteos["historico"], conteos["observaciones"])
    else:
        n = cargar_historico(motor, directorio / "historico_ventas.csv")
        log.info("histórico cargado: %s filas", n)
    return estado_carga(motor)


def asegurar_modelo(motor) -> str:
    from novamercado.db import Repositorio, leer_catalogos
    from novamercado.entrenamiento import entrenar_candidato, registrar_candidato
    from novamercado.registro import ALIAS_CHAMPION, RegistroMlflow

    registro = RegistroMlflow()
    esperar("MLflow", registro.cliente.search_experiments)
    vigente = registro.version_por_alias(ALIAS_CHAMPION)
    if vigente is not None:
        log.info("ya existe %s@%s (v%s): no se reentrena", registro.nombre, ALIAS_CHAMPION, vigente)
        return vigente

    repo = Repositorio(motor)
    ejecucion = repo.crear_ejecucion(motivo="bootstrap: primer modelo", id=f"bootstrap-{uuid.uuid4().hex[:8]}")
    try:
        res = entrenar_candidato(repo.leer_ventas_df(), leer_catalogos(motor))
        version, _ = registrar_candidato(res, registro, ejecucion, "modelo inicial (bootstrap)")
        registro.asignar_alias(version, ALIAS_CHAMPION)
        motivo = (f"modelo inicial: no existía @champion; v{version} registrada con costo de validación "
                  f"{res.metricas['costo_total_validacion']:.2f} (baseline "
                  f"{res.metricas_baseline['costo_total_validacion']:.2f})")
        repo.actualizar_ejecucion(ejecucion, estado="exitoso", promovido=True, version=version, motivo=motivo,
                                  metricas={"candidato": res.metricas, "baseline": res.metricas_baseline,
                                            "ventanas": res.ventanas.a_dict()})
        log.info(motivo)
        return version
    except Exception as e:
        repo.actualizar_ejecucion(ejecucion, estado="fallido", promovido=False, version="", motivo=str(e)[:500])
        raise


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from novamercado.db import Repositorio, crear_motor

    motor = crear_motor()
    esperar("PostgreSQL del producto", Repositorio(motor).ping)
    conteos = asegurar_datos(motor)
    log.info("datos listos: %s", conteos)
    version = asegurar_modelo(motor)
    log.info("bootstrap completo: @champion = v%s", version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
