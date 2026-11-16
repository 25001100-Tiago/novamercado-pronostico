"""API FastAPI del servicio de pronóstico de NovaMercado (puerto 8000).

Endpoints: POST /v1/prediccion, POST /v1/observaciones, POST /admin/reentrenar,
GET /admin/reentrenar/{id}, GET /modelo, GET /health.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable

# Fallar rápido si MLflow no responde (antes de importar mlflow en cualquier parte).
os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "10")
os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "1")
os.environ.setdefault("MLFLOW_HTTP_REQUEST_BACKOFF_FACTOR", "1")

import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from api.airflow_cliente import ClienteAirflow, ErrorAirflow
from api.esquemas import (
    Calidad,
    EstadoReentrenamiento,
    PrediccionFamilia,
    RespuestaModelo,
    RespuestaObservaciones,
    RespuestaPrediccion,
    cuerpo_error,
    validar_observaciones,
    validar_prediccion,
)
from api.salud import INTERVALO_SEGUNDOS, MonitorSalud, validar_airflow, verificar_http
from api.servicio_modelo import ServicioModelo
from novamercado.catalogos import Catalogos, cargar_catalogos
from novamercado.config import directorio_datos
from novamercado.db import Repositorio, crear_motor, inicializar_esquema, leer_catalogos
from novamercado.limpieza import ErrorContrato
from novamercado.modelo import construir_features

log = logging.getLogger("novamercado.api")

INTERVALO_MODELO_SEGUNDOS = float(os.getenv("INTERVALO_MODELO_SEGUNDOS", "20"))
DIAS_HISTORIA = 60


class NoDisponible(Exception):
    def __init__(self, detalle: str):
        self.detalle = detalle


@dataclass
class Contexto:
    repo: Repositorio
    servicio: ServicioModelo
    monitor: MonitorSalud
    airflow: ClienteAirflow | None
    cargar_catalogos: Callable[[], Catalogos]
    catalogos: Catalogos | None = None
    tareas: list = field(default_factory=list)

    def obtener_catalogos(self) -> Catalogos:
        if self.catalogos is None:
            try:
                self.catalogos = self.cargar_catalogos()
            except Exception as e:
                raise NoDisponible(f"catálogos no disponibles: {e}") from e
        return self.catalogos


def contexto_por_defecto() -> Contexto:
    from novamercado.registro import NOMBRE_MODELO, RegistroMlflow

    motor = crear_motor()
    repo = Repositorio(motor)
    mlflow_uri = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000").rstrip("/")
    airflow_url = os.getenv("AIRFLOW_URL", "http://airflow-apiserver:8080").rstrip("/")
    servicio = ServicioModelo(
        lambda: RegistroMlflow(mlflow_uri), os.getenv("MODELO_CACHE_DIR", "/app/cache"), nombre=NOMBRE_MODELO
    )
    monitor = MonitorSalud({
        "base_datos": repo.ping,
        "mlflow": verificar_http(f"{mlflow_uri}/health"),
        "airflow": verificar_http(f"{airflow_url}/api/v2/monitor/health", validar=validar_airflow),
    })
    airflow = ClienteAirflow(
        airflow_url,
        os.getenv("AIRFLOW_USUARIO", "admin"),
        os.getenv("AIRFLOW_CLAVE", "admin"),
        os.getenv("AIRFLOW_DAG_ID", "reentrenamiento_novamercado"),
    )

    def catalogos() -> Catalogos:
        if (directorio_datos() / "tiendas.csv").exists():
            return cargar_catalogos()
        return leer_catalogos(motor)

    return Contexto(repo=repo, servicio=servicio, monitor=monitor, airflow=airflow, cargar_catalogos=catalogos)


async def _bucle(nombre: str, intervalo: float, funcion: Callable[[], Any]) -> None:
    while True:
        try:
            await asyncio.to_thread(funcion)
        except Exception:  # pragma: no cover - el bucle nunca debe morir
            log.exception("falló la tarea periódica %s", nombre)
        await asyncio.sleep(intervalo)


def crear_app(fabrica: Callable[[], Contexto] = contexto_por_defecto, iniciar_tareas: bool = True) -> FastAPI:
    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI):
        ctx = fabrica()
        app.state.ctx = ctx
        try:
            inicializar_esquema(ctx.repo.motor)
        except Exception as e:  # la BD puede tardar; se reintenta en cada solicitud
            log.warning("no se pudo inicializar el esquema todavía: %s", e)
        ctx.servicio.cargar_cache()
        if iniciar_tareas:
            ctx.tareas = [
                asyncio.create_task(_bucle("salud", INTERVALO_SEGUNDOS, ctx.monitor.verificar_todo)),
                asyncio.create_task(_bucle("modelo", INTERVALO_MODELO_SEGUNDOS, ctx.servicio.sincronizar)),
            ]
        yield
        for t in ctx.tareas:
            t.cancel()

    app = FastAPI(
        title="NovaMercado — Servicio de pronóstico",
        version="1.0.0",
        lifespan=ciclo_de_vida,
    )

    @app.exception_handler(NoDisponible)
    async def _no_disponible(_: Request, exc: NoDisponible):
        return JSONResponse(status_code=503, content={"detail": exc.detalle})

    @app.exception_handler(SQLAlchemyError)
    async def _bd_caida(_: Request, exc: SQLAlchemyError):
        log.warning("error de base de datos: %s", exc)
        return JSONResponse(status_code=503, content={"detail": "la base de datos del producto no está disponible"})

    def ctx_de(request: Request) -> Contexto:
        return request.app.state.ctx

    async def leer_json(request: Request) -> Any:
        try:
            return await request.json()
        except Exception:
            raise ErrorContrato([{"campo": "cuerpo", "accion": "rechazar", "detalle": "el cuerpo no es JSON válido"}])

    def registrar_rechazo(ctx: Contexto, endpoint: str, crudo: Any, exc: ErrorContrato) -> JSONResponse:
        try:
            ctx.repo.registrar_solicitud(endpoint, crudo if isinstance(crudo, (dict, list)) else None, 422,
                                         errores=exc.errores)
        except Exception as e:  # auditar no debe impedir responder
            log.warning("no se pudo registrar la solicitud rechazada: %s", e)
        return JSONResponse(status_code=422, content=cuerpo_error(exc))

    # ------------------------------------------------------------- predicción
    @app.post("/v1/prediccion", response_model=RespuestaPrediccion)
    async def prediccion(request: Request):
        ctx = ctx_de(request)
        try:
            crudo = await leer_json(request)
        except ErrorContrato as exc:
            return registrar_rechazo(ctx, "/v1/prediccion", None, exc)
        return await asyncio.to_thread(_predecir, ctx, crudo)

    def _predecir(ctx: Contexto, crudo: Any):
        cat = ctx.obtener_catalogos()
        try:
            referencia = ctx.repo.fecha_max_ventas()
        except SQLAlchemyError:
            referencia = None
        try:
            solicitud, calidad = validar_prediccion(crudo, cat, fecha_referencia=referencia)
        except ErrorContrato as exc:
            return registrar_rechazo(ctx, "/v1/prediccion", crudo, exc)
        modelo = ctx.servicio.actual
        if modelo is None:
            raise NoDisponible("todavía no hay un modelo cargado")

        historia = ctx.repo.historia_para_prediccion(solicitud.tienda_id, solicitud.fecha, DIAS_HISTORIA)
        objetivos = pd.DataFrame(
            [{"fecha": solicitud.fecha, "tienda_id": solicitud.tienda_id, "familia_id": f.familia_id,
              "en_promocion": f.en_promocion} for f in solicitud.familias]
        )
        feats = construir_features(historia, objetivos, cat)
        venta, cantidad = modelo.artefacto.predecir(feats)
        predicciones = [
            PrediccionFamilia(familia_id=f.familia_id, venta_esperada=round(float(v), 2),
                              cantidad_sugerida=int(c))
            for f, v, c in zip(solicitud.familias, venta, cantidad)
        ]
        respuesta = RespuestaPrediccion(
            tienda_id=solicitud.tienda_id, fecha=solicitud.fecha, version_modelo=str(modelo.version),
            predicciones=predicciones, calidad=calidad,
        )
        sid = ctx.repo.registrar_solicitud("/v1/prediccion", crudo, 200, payload_limpio=solicitud, calidad=calidad)
        ctx.repo.registrar_predicciones(
            sid, solicitud.tienda_id, solicitud.fecha,
            [{"familia_id": f.familia_id, "en_promocion": f.en_promocion, "prediccion": p.venta_esperada}
             for f, p in zip(solicitud.familias, predicciones)],
            str(modelo.version),
        )
        return respuesta

    # ---------------------------------------------------------- observaciones
    @app.post("/v1/observaciones", response_model=RespuestaObservaciones)
    async def observaciones(request: Request):
        ctx = ctx_de(request)
        try:
            crudo = await leer_json(request)
        except ErrorContrato as exc:
            return registrar_rechazo(ctx, "/v1/observaciones", None, exc)
        return await asyncio.to_thread(_observar, ctx, crudo)

    def _observar(ctx: Contexto, crudo: Any):
        cat = ctx.obtener_catalogos()
        try:
            solicitud, calidad = validar_observaciones(crudo, cat)
        except ErrorContrato as exc:
            return registrar_rechazo(ctx, "/v1/observaciones", crudo, exc)
        datos = solicitud.model_dump()
        guardados = ctx.repo.guardar_observaciones(datos["tienda_id"], datos["fecha"], datos["ventas"])
        ctx.repo.registrar_solicitud("/v1/observaciones", crudo, 200, payload_limpio=solicitud, calidad=calidad)
        return RespuestaObservaciones(registros_guardados=guardados, calidad=calidad)

    # --------------------------------------------------------- reentrenamiento
    @app.post("/admin/reentrenar", status_code=202)
    def reentrenar(request: Request):
        ctx = ctx_de(request)
        id_ejecucion = uuid.uuid4().hex
        ctx.repo.crear_ejecucion(motivo="reentrenamiento solicitado vía POST /admin/reentrenar", id=id_ejecucion)
        try:
            if ctx.airflow is None:
                raise ErrorAirflow("Airflow no está configurado")
            run_id = ctx.airflow.disparar({"ejecucion_id": id_ejecucion}, dag_run_id=f"api__{id_ejecucion}")
        except Exception as e:
            motivo = f"no se pudo iniciar el reentrenamiento en Airflow: {e}"
            version = ctx.servicio.actual.version if ctx.servicio.actual else ""
            ctx.repo.actualizar_ejecucion(id_ejecucion, estado="fallido", promovido=False, version=version,
                                          motivo=motivo)
            return JSONResponse(status_code=503, content={"detail": motivo, "id": id_ejecucion})
        ctx.repo.actualizar_ejecucion(id_ejecucion, airflow_run_id=run_id)
        return {"id": id_ejecucion}

    @app.get("/admin/reentrenar/{id_ejecucion}")
    def estado_reentrenamiento(id_ejecucion: str, request: Request):
        ctx = ctx_de(request)
        fila = ctx.repo.obtener_ejecucion(id_ejecucion)
        if fila is None:
            return JSONResponse(status_code=404, content={"detail": f"no existe la ejecución {id_ejecucion}"})
        if fila["estado"] == "en_curso" and fila.get("airflow_run_id") and ctx.airflow is not None:
            try:
                estado_af = ctx.airflow.estado(fila["airflow_run_id"])
            except Exception:
                estado_af = None  # Airflow caído: se informa el último estado conocido
            if estado_af == "failed":
                version = ctx.servicio.actual.version if ctx.servicio.actual else ""
                ctx.repo.actualizar_ejecucion(
                    id_ejecucion, estado="fallido", promovido=False, version=version,
                    motivo=f"la corrida {fila['airflow_run_id']} de Airflow terminó en estado failed",
                )
                fila = ctx.repo.obtener_ejecucion(id_ejecucion)
        version = fila.get("version") or (ctx.servicio.actual.version if ctx.servicio.actual else "")
        estado = EstadoReentrenamiento(
            id=fila["id"], estado=fila["estado"], promovido=fila["promovido"], version=str(version),
            motivo=fila.get("motivo"),
        )
        return estado.a_respuesta()

    # ------------------------------------------------------------------ modelo
    @app.get("/modelo", response_model=RespuestaModelo)
    def modelo(request: Request):
        actual = ctx_de(request).servicio.actual
        if actual is None:
            raise NoDisponible("todavía no hay un modelo cargado")
        return RespuestaModelo(nombre=actual.nombre, alias=actual.alias, version=str(actual.version))

    # ------------------------------------------------------------------ salud
    @app.get("/health")
    def salud(request: Request):
        ctx = ctx_de(request)
        caidas = ctx.monitor.caidas()
        if ctx.servicio.actual is None:
            motivo = ctx.servicio.ultimo_error or "todavía no hay un modelo cargado"
            return JSONResponse(status_code=503, content={"estado": "no_disponible", "motivo": motivo})
        if caidas:
            motivo = "; ".join(f"{n} no disponible ({d})" for n, d in sorted(caidas.items()))
            return {"estado": "degradado", "motivo": motivo}
        return {"estado": "ok"}

    return app


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = crear_app()
