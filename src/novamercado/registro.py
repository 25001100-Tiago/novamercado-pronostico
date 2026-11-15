"""Acceso al Model Registry de MLflow (experimento, versiones y alias).

El artefacto se registra como modelo ``pyfunc`` (MLmodel estándar) cuyo archivo
``artefacto.joblib`` contiene el :class:`~novamercado.modelo.ArtefactoModelo`.
La API y la compuerta descargan ese archivo y lo cargan con joblib.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import joblib

from novamercado.modelo import ArtefactoModelo

NOMBRE_MODELO = os.getenv("MLFLOW_MODELO_NOMBRE", "novamercado-pronostico")
EXPERIMENTO = os.getenv("MLFLOW_EXPERIMENTO", "novamercado-ventas")
ALIAS_CHAMPION = "champion"
ALIAS_CHALLENGER = "challenger"
ARCHIVO_ARTEFACTO = "artefacto.joblib"

REQUISITOS_PIP = [
    "scikit-learn>=1.5",
    "pandas>=2.2",
    "numpy>=1.26",
    "joblib>=1.4",
]


def _mlflow():
    import mlflow  # import diferido: las pruebas no requieren MLflow activo

    return mlflow


try:  # la clase pyfunc solo existe si mlflow está instalado
    from mlflow.pyfunc import PythonModel as _PythonModel
except Exception:  # pragma: no cover
    _PythonModel = object  # type: ignore[misc,assignment]


class ModeloPyfunc(_PythonModel):  # type: ignore[misc]
    """Envoltorio pyfunc: recibe un DataFrame de features y devuelve venta y cantidad."""

    def load_context(self, context):  # pragma: no cover - lo ejercita MLflow
        self.artefacto = joblib.load(context.artifacts["artefacto"])

    def predict(self, context, model_input, params=None):  # pragma: no cover
        import pandas as pd

        venta, cantidad = self.artefacto.predecir(model_input)
        return pd.DataFrame({"venta_esperada": venta, "cantidad_sugerida": cantidad})


def buscar_artefacto(directorio: str | Path) -> Path:
    for ruta in Path(directorio).rglob(ARCHIVO_ARTEFACTO):
        return ruta
    raise FileNotFoundError(f"no se encontró {ARCHIVO_ARTEFACTO} en {directorio}")


class RegistroMlflow:
    def __init__(self, tracking_uri: str | None = None, nombre: str = NOMBRE_MODELO):
        self.mlflow = _mlflow()
        self.tracking_uri = tracking_uri or os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
        self.mlflow.set_tracking_uri(self.tracking_uri)
        self.nombre = nombre
        self.cliente = self.mlflow.MlflowClient(tracking_uri=self.tracking_uri)

    # ----------------------------------------------------------- consultas
    def version_por_alias(self, alias: str = ALIAS_CHAMPION) -> str | None:
        from mlflow.exceptions import MlflowException

        try:
            return str(self.cliente.get_model_version_by_alias(self.nombre, alias).version)
        except MlflowException as e:
            codigo = getattr(e, "error_code", "")
            if "RESOURCE_DOES_NOT_EXIST" in str(codigo) or "INVALID_PARAMETER_VALUE" in str(codigo):
                return None
            raise

    def descargar(self, version: str, destino: str | Path) -> Path:
        ruta = self.mlflow.artifacts.download_artifacts(
            artifact_uri=f"models:/{self.nombre}/{version}", dst_path=str(destino)
        )
        return buscar_artefacto(ruta)

    def cargar_artefacto(self, version: str) -> ArtefactoModelo:
        with tempfile.TemporaryDirectory() as tmp:
            return joblib.load(self.descargar(version, tmp))

    def versiones(self) -> list[str]:
        return sorted(
            (str(v.version) for v in self.cliente.search_model_versions(f"name='{self.nombre}'")), key=int
        )

    # ----------------------------------------------------------- escritura
    def registrar(
        self,
        artefacto: ArtefactoModelo,
        *,
        nombre_corrida: str,
        parametros: dict[str, Any],
        metricas: dict[str, float],
        etiquetas: dict[str, str],
        extras: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        """Crea una corrida en el experimento, registra el modelo y devuelve (version, run_id)."""
        mlflow = self.mlflow
        mlflow.set_experiment(EXPERIMENTO)
        with mlflow.start_run(run_name=nombre_corrida) as corrida:
            mlflow.log_params({k: str(v)[:500] for k, v in parametros.items()})
            mlflow.log_metrics({k: float(v) for k, v in metricas.items()})
            mlflow.set_tags(etiquetas)
            for nombre, contenido in (extras or {}).items():
                mlflow.log_dict(json.loads(json.dumps(contenido, default=str)), f"{nombre}.json")
            with tempfile.TemporaryDirectory() as tmp:
                ruta = Path(tmp) / ARCHIVO_ARTEFACTO
                joblib.dump(artefacto, ruta)
                info = mlflow.pyfunc.log_model(
                    name="modelo",
                    python_model=ModeloPyfunc(),
                    artifacts={"artefacto": str(ruta)},
                    pip_requirements=REQUISITOS_PIP,
                    registered_model_name=self.nombre,
                )
            version = str(info.registered_model_version)
            run_id = corrida.info.run_id
        self.cliente.set_model_version_tag(self.nombre, version, "tipo", artefacto.tipo)
        self.cliente.set_model_version_tag(self.nombre, version, "fecha_corte", str(artefacto.fecha_corte))
        return version, run_id

    def asignar_alias(self, version: str, alias: str = ALIAS_CHAMPION) -> None:
        self.cliente.set_registered_model_alias(self.nombre, alias, str(version))

    def registrar_metricas(self, run_id: str, metricas: dict[str, float], etiquetas: dict[str, str] | None = None):
        for k, v in metricas.items():
            self.cliente.log_metric(run_id, k, float(v))
        for k, v in (etiquetas or {}).items():
            self.cliente.set_tag(run_id, k, str(v))
