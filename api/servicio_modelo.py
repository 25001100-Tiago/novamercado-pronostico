"""Modelo en memoria con caché local en disco y recarga en caliente desde MLflow.

* Al arrancar se carga la caché local (si existe): la API puede predecir aunque MLflow
  esté caído.
* ``sincronizar()`` (cada 20 s en segundo plano) consulta la versión de ``@champion``;
  si cambió, descarga el artefacto, lo valida, actualiza la caché de forma atómica
  (``os.replace``) y reemplaza el modelo en memoria sin reiniciar el proceso.
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

import joblib

log = logging.getLogger("novamercado.api.modelo")

ARCHIVO_CACHE = "modelo_cache.joblib"


class Registro(Protocol):
    def version_por_alias(self, alias: str = ...) -> str | None: ...
    def descargar(self, version: str, destino: str | Path) -> Path: ...


@dataclass(frozen=True)
class ModeloCargado:
    artefacto: Any
    version: str
    nombre: str
    alias: str
    origen: str  # "mlflow" | "cache"
    cargado_en: float


class ServicioModelo:
    def __init__(
        self,
        fabrica_registro: Callable[[], Registro] | None,
        dir_cache: str | Path,
        nombre: str = "novamercado-pronostico",
        alias: str = "champion",
    ):
        self._fabrica = fabrica_registro
        self._registro: Registro | None = None
        self.dir_cache = Path(dir_cache)
        self.nombre = nombre
        self.alias = alias
        self._lock = threading.Lock()
        self._actual: ModeloCargado | None = None
        self.ultimo_error: str | None = None
        self.ultima_consulta_ok: float | None = None

    @property
    def actual(self) -> ModeloCargado | None:
        return self._actual

    def _obtener_registro(self) -> Registro:
        if self._registro is None:
            if self._fabrica is None:
                raise RuntimeError("no hay registro de modelos configurado")
            self._registro = self._fabrica()
        return self._registro

    # ------------------------------------------------------------- caché
    @property
    def ruta_cache(self) -> Path:
        return self.dir_cache / ARCHIVO_CACHE

    def cargar_cache(self) -> bool:
        if not self.ruta_cache.exists():
            return False
        try:
            contenido = joblib.load(self.ruta_cache)
            self._fijar(contenido["artefacto"], str(contenido["version"]), "cache")
            log.info("modelo v%s cargado desde la caché local", contenido["version"])
            return True
        except Exception as e:  # caché corrupta: se ignora y se espera a MLflow
            log.warning("caché local inválida (%s); se ignora", e)
            return False

    def _guardar_cache(self, artefacto: Any, version: str) -> None:
        self.dir_cache.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.dir_cache, suffix=".tmp")
        os.close(fd)
        joblib.dump({"version": version, "nombre": self.nombre, "artefacto": artefacto}, tmp)
        os.replace(tmp, self.ruta_cache)

    def _fijar(self, artefacto: Any, version: str, origen: str) -> None:
        if not hasattr(artefacto, "predecir"):
            raise TypeError("el artefacto descargado no expone predecir()")
        with self._lock:
            self._actual = ModeloCargado(artefacto, version, self.nombre, self.alias, origen, time.time())

    # ------------------------------------------------------- sincronización
    def sincronizar(self) -> bool:
        """Devuelve True si se cargó una versión nueva."""
        try:
            registro = self._obtener_registro()
            version = registro.version_por_alias(self.alias)
            self.ultima_consulta_ok = time.time()
            if version is None:
                self.ultimo_error = f"aún no existe {self.nombre}@{self.alias} en MLflow"
                return False
            version = str(version)
            if self._actual is not None and self._actual.version == version:
                self.ultimo_error = None
                return False
            self.dir_cache.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=self.dir_cache) as tmp:
                artefacto = joblib.load(registro.descargar(version, tmp))
            anterior = self._actual.version if self._actual else None
            self._fijar(artefacto, version, "mlflow")
            self._guardar_cache(artefacto, version)
            self.ultimo_error = None
            log.info("hot-reload: %s@%s v%s -> v%s", self.nombre, self.alias, anterior, version)
            return True
        except Exception as e:
            self.ultimo_error = f"{type(e).__name__}: {e}"[:300]
            log.warning("no se pudo sincronizar el modelo: %s", self.ultimo_error)
            return False
