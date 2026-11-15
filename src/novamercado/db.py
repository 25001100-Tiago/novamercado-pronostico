"""Persistencia en PostgreSQL (SQLite en memoria para pruebas sin Docker).

Tablas:

* ``tiendas``, ``familias``, ``costos``, ``feriados`` — catálogos.
* ``ventas`` — histórico y observaciones en una sola tabla (clave fecha+tienda+familia,
  columna ``origen``); es la fuente del reentrenamiento.
* ``solicitudes`` — cada solicitud recibida (cruda y limpia), con su estado HTTP.
* ``predicciones`` — cada pronóstico emitido, con ``version_modelo``.
* ``correcciones`` — cada reparación, advertencia o rechazo aplicado a una solicitud.
* ``ejecuciones_reentrenamiento`` — id, estado, promovido, version, motivo, métricas.

``guardar_observaciones`` es idempotente y atómico: un único
``INSERT ... ON CONFLICT DO UPDATE ... WHERE ventas <> excluded.ventas RETURNING``
solo devuelve filas nuevas o cuyo valor de ventas cambió, de modo que
``registros_guardados`` es exactamente ese conteo (reenviar lo mismo devuelve 0).
"""

from __future__ import annotations

import csv
import json
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Engine,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    false,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.pool import StaticPool

from novamercado.catalogos import Catalogos, Tienda
from novamercado.config import url_base_datos

metadata = MetaData()
JSONVariante = JSON().with_variant(JSONB(), "postgresql")

ESTADOS_EJECUCION = ("en_curso", "exitoso", "fallido")  # contrato de GET /admin/reentrenar/{id}

# ------------------------------------------------------------------ catálogos
tiendas = Table(
    "tiendas", metadata,
    Column("tienda_id", Integer, primary_key=True, autoincrement=False),
    Column("nombre", String(120), nullable=False),
    Column("ciudad", String(80), nullable=False),
    Column("departamento", String(80), nullable=False),
    Column("tipo", String(40), nullable=False),
    Column("fecha_apertura", Date, nullable=False),
)

familias = Table(
    "familias", metadata,
    Column("familia_id", String(40), primary_key=True),
    Column("nombre", String(80), nullable=False),
)

costos = Table(
    "costos", metadata,
    Column("familia_id", String(40), ForeignKey("familias.familia_id"), primary_key=True),
    Column("costo_faltante", Float, nullable=False),
    Column("costo_sobrante", Float, nullable=False),
)

feriados = Table(
    "feriados", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("fecha", Date, nullable=False, index=True),
    Column("nombre", String(120), nullable=False),
    Column("tipo", String(40), nullable=False),
    Column("ambito", String(80), nullable=False),
    UniqueConstraint("fecha", "nombre", "ambito", name="uq_feriados_fecha_nombre_ambito"),
)

# ------------------------------------------------------- histórico/observaciones
ventas = Table(
    "ventas", metadata,
    Column("fecha", Date, primary_key=True),
    Column("tienda_id", Integer, ForeignKey("tiendas.tienda_id"), primary_key=True),
    Column("familia_id", String(40), ForeignKey("familias.familia_id"), primary_key=True),
    Column("ventas", Integer, nullable=False),
    Column("en_promocion", Integer, nullable=True),
    Column("origen", String(20), nullable=False),
    Column("actualizado_en", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("ventas >= 0", name="ck_ventas_no_negativas"),
    CheckConstraint("en_promocion IS NULL OR en_promocion >= 0", name="ck_promo_no_negativa"),
    CheckConstraint("origen IN ('historico', 'observacion')", name="ck_ventas_origen"),
)

# ---------------------------------------------------------------- auditoría
solicitudes = Table(
    "solicitudes", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("endpoint", String(60), nullable=False),
    Column("recibido_en", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("payload_crudo", JSONVariante, nullable=True),
    Column("payload_limpio", JSONVariante, nullable=True),
    Column("estado_calidad", String(20), nullable=True),
    Column("http_status", Integer, nullable=False),
    Column("tienda_id", Integer, nullable=True),
    Column("fecha", Date, nullable=True),
)

predicciones = Table(
    "predicciones", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("solicitud_id", Integer, ForeignKey("solicitudes.id"), nullable=True, index=True),
    Column("tienda_id", Integer, nullable=False),
    Column("fecha", Date, nullable=False),
    Column("familia_id", String(40), nullable=False),
    Column("en_promocion", Integer, nullable=True),
    Column("prediccion", Float, nullable=False),
    Column("version_modelo", String(80), nullable=False),
    Column("creado_en", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

correcciones = Table(
    "correcciones", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("solicitud_id", Integer, ForeignKey("solicitudes.id"), nullable=False, index=True),
    Column("campo", String(200), nullable=False),
    Column("accion", String(20), nullable=False),
    Column("detalle", Text, nullable=False),
    Column("creado_en", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("accion IN ('reparar', 'advertir', 'rechazar')", name="ck_correcciones_accion"),
)

ejecuciones_reentrenamiento = Table(
    "ejecuciones_reentrenamiento", metadata,
    Column("id", String(64), primary_key=True),
    Column("estado", String(20), nullable=False, server_default="en_curso"),
    Column("promovido", Boolean, nullable=False, server_default=false()),
    Column("version", String(80), nullable=True),
    Column("motivo", Text, nullable=True),
    Column("metricas", JSONVariante, nullable=True),
    Column("airflow_run_id", String(250), nullable=True),
    Column("iniciado_en", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("finalizado_en", DateTime(timezone=True), nullable=True),
    CheckConstraint("estado IN ('en_curso', 'exitoso', 'fallido')", name="ck_ejecucion_estado"),
)


# --------------------------------------------------------------------------- #
# Motor y esquema
# --------------------------------------------------------------------------- #
def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def crear_motor(url: str | None = None, **kwargs: Any) -> Engine:
    """Crea el motor. ``sqlite://`` usa una única conexión compartida (memoria)."""
    url = url or url_base_datos()
    if url.startswith("sqlite"):
        opciones: dict[str, Any] = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:", "sqlite+pysqlite:///:memory:"):
            opciones["poolclass"] = StaticPool
        motor = create_engine(url, json_serializer=_json, **opciones, **kwargs)

        @event.listens_for(motor, "connect")
        def _activar_fk(conexion, _registro):  # pragma: no cover - trivial
            cursor = conexion.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return motor
    if url.startswith("postgresql") and "connect_args" not in kwargs:
        kwargs["connect_args"] = {"connect_timeout": 3}  # chequeos de salud rápidos si la BD cae
    return create_engine(url, json_serializer=_json, pool_pre_ping=True, **kwargs)


def inicializar_esquema(motor: Engine) -> None:
    metadata.create_all(motor)


def _insert(dialecto: str, tabla: Table):
    if dialecto == "postgresql":
        return pg_insert(tabla)
    if dialecto == "sqlite":
        return sqlite_insert(tabla)
    raise NotImplementedError(f"dialecto no soportado para upsert: {dialecto}")


def _a_fecha(valor: date | str) -> date:
    return valor if isinstance(valor, date) else date.fromisoformat(valor)


def _a_dict(obj: Any) -> Any:
    return obj.model_dump(mode="json") if hasattr(obj, "model_dump") else obj


def cargar_catalogos_en_bd(motor: Engine, cat: Catalogos) -> None:
    """Sincroniza los catálogos (upsert; se puede ejecutar varias veces)."""
    with motor.begin() as con:
        d = con.dialect.name

        def upsert(tabla: Table, filas: list[dict], claves: list[str], actualizar: bool = True) -> None:
            if not filas:
                return
            ins = _insert(d, tabla).values(filas)
            if actualizar:
                cambios = {c.name: ins.excluded[c.name] for c in tabla.columns if c.name not in claves}
                con.execute(ins.on_conflict_do_update(index_elements=claves, set_=cambios))
            else:
                con.execute(ins.on_conflict_do_nothing(index_elements=claves))

        upsert(tiendas, [
            {"tienda_id": t.tienda_id, "nombre": t.nombre, "ciudad": t.ciudad,
             "departamento": t.departamento, "tipo": t.tipo, "fecha_apertura": t.fecha_apertura}
            for t in cat.tiendas.values()
        ], ["tienda_id"])
        upsert(familias, [{"familia_id": k, "nombre": v} for k, v in cat.familias.items()], ["familia_id"])
        upsert(costos, [{"familia_id": k, **v} for k, v in cat.costos.items()], ["familia_id"])
        upsert(feriados, [
            {"fecha": f["fecha"], "nombre": f["nombre"], "tipo": f["tipo"], "ambito": f["ambito"]}
            for f in cat.feriados
        ], ["fecha", "nombre", "ambito"], actualizar=False)


def cargar_historico(motor: Engine, ruta_csv: str | Path, tamano_lote: int = 2000) -> int:
    """Carga el histórico sin pisar datos existentes. Devuelve filas insertadas."""
    insertadas = 0
    with motor.begin() as con, open(ruta_csv, encoding="utf-8", newline="") as f:
        lote: list[dict] = []

        def volcar() -> int:
            if not lote:
                return 0
            # RETURNING en vez de rowcount: con psycopg rowcount puede ser -1.
            stmt = (
                _insert(con.dialect.name, ventas)
                .values(lote)
                .on_conflict_do_nothing(index_elements=["fecha", "tienda_id", "familia_id"])
                .returning(ventas.c.tienda_id)
            )
            n = len(con.execute(stmt).all())
            lote.clear()
            return n

        for fila in csv.DictReader(f):
            lote.append({
                "fecha": date.fromisoformat(fila["fecha"]),
                "tienda_id": int(fila["tienda_id"]),
                "familia_id": fila["familia_id"],
                "ventas": int(float(fila["ventas"])),
                "en_promocion": int(float(fila["en_promocion"])),
                "origen": "historico",
            })
            if len(lote) >= tamano_lote:
                insertadas += volcar()
        insertadas += volcar()
    return insertadas


# --------------------------------------------------------------------------- #
# Repositorio
# --------------------------------------------------------------------------- #
class Repositorio:
    def __init__(self, motor: Engine):
        self.motor = motor

    # ------------------------------------------------------- observaciones
    def guardar_observaciones(
        self, tienda_id: int, fecha: date | str, filas: Iterable[Mapping[str, Any]], origen: str = "observacion"
    ) -> int:
        """Upsert idempotente. Devuelve cuántas filas son nuevas o cambiaron su valor de ventas."""
        fecha = _a_fecha(fecha)
        por_familia: dict[str, dict[str, Any]] = {}
        for f in filas:  # última aparición gana (evita doble conflicto en un mismo INSERT)
            por_familia[f["familia_id"]] = {
                "fecha": fecha,
                "tienda_id": int(tienda_id),
                "familia_id": f["familia_id"],
                "ventas": int(f["ventas"]),
                "en_promocion": f.get("en_promocion"),
                "origen": origen,
            }
        if not por_familia:
            return 0
        with self.motor.begin() as con:
            ins = _insert(con.dialect.name, ventas).values(list(por_familia.values()))
            exc = ins.excluded
            stmt = ins.on_conflict_do_update(
                index_elements=["fecha", "tienda_id", "familia_id"],
                set_={
                    "ventas": exc.ventas,
                    "en_promocion": func.coalesce(exc.en_promocion, ventas.c.en_promocion),
                    "origen": exc.origen,
                    "actualizado_en": func.now(),
                },
                where=ventas.c.ventas != exc.ventas,
            ).returning(ventas.c.familia_id)
            return len(con.execute(stmt).all())

    def obtener_ventas(self, tienda_id: int | None = None, fecha: date | str | None = None) -> list[dict]:
        q = select(ventas).order_by(ventas.c.fecha, ventas.c.tienda_id, ventas.c.familia_id)
        if tienda_id is not None:
            q = q.where(ventas.c.tienda_id == tienda_id)
        if fecha is not None:
            q = q.where(ventas.c.fecha == _a_fecha(fecha))
        with self.motor.connect() as con:
            return [dict(r._mapping) for r in con.execute(q)]

    def contar_ventas(self) -> int:
        with self.motor.connect() as con:
            return con.execute(select(func.count()).select_from(ventas)).scalar_one()

    def fecha_max_ventas(self) -> date | None:
        """Último día con datos: es el "hoy" simulado del servicio."""
        with self.motor.connect() as con:
            return con.execute(select(func.max(ventas.c.fecha))).scalar_one()

    # ------------------------------------------------------------ auditoría
    def registrar_solicitud(
        self,
        endpoint: str,
        payload_crudo: Any,
        http_status: int,
        *,
        payload_limpio: Any = None,
        calidad: Any = None,
        errores: Iterable[Mapping[str, str]] | None = None,
    ) -> int:
        """Guarda la solicitud y, en la misma transacción, sus correcciones/rechazos."""
        limpio = _a_dict(payload_limpio)
        calidad = _a_dict(calidad)
        observaciones = list((calidad or {}).get("observaciones", [])) + list(errores or [])
        with self.motor.begin() as con:
            solicitud_id = con.execute(
                insert(solicitudes).values(
                    endpoint=endpoint,
                    payload_crudo=payload_crudo,
                    payload_limpio=limpio,
                    estado_calidad=(calidad or {}).get("estado"),
                    http_status=http_status,
                    tienda_id=(limpio or {}).get("tienda_id"),
                    fecha=_a_fecha(limpio["fecha"]) if limpio and limpio.get("fecha") else None,
                ).returning(solicitudes.c.id)
            ).scalar_one()
            if observaciones:
                con.execute(insert(correcciones), [
                    {"solicitud_id": solicitud_id, "campo": o["campo"], "accion": o["accion"], "detalle": o["detalle"]}
                    for o in observaciones
                ])
        return solicitud_id

    def registrar_predicciones(
        self,
        solicitud_id: int | None,
        tienda_id: int,
        fecha: date | str,
        filas: Iterable[Mapping[str, Any]],
        version_modelo: str,
    ) -> int:
        if not version_modelo:
            raise ValueError("version_modelo es obligatoria para registrar predicciones")
        registros = [
            {
                "solicitud_id": solicitud_id,
                "tienda_id": tienda_id,
                "fecha": _a_fecha(fecha),
                "familia_id": f["familia_id"],
                "en_promocion": f.get("en_promocion"),
                "prediccion": float(f["prediccion"]),
                "version_modelo": version_modelo,
            }
            for f in filas
        ]
        if not registros:
            return 0
        with self.motor.begin() as con:
            con.execute(insert(predicciones), registros)
        return len(registros)

    def listar(self, tabla: Table, **filtros: Any) -> list[dict]:
        q = select(tabla)
        for col, val in filtros.items():
            q = q.where(tabla.c[col] == val)
        with self.motor.connect() as con:
            return [dict(r._mapping) for r in con.execute(q)]

    # -------------------------------------------------------- lecturas para el modelo
    def leer_ventas_df(self, hasta: date | str | None = None):
        """Todo el histórico + observaciones (para entrenar)."""
        import pandas as pd

        q = select(ventas.c.fecha, ventas.c.tienda_id, ventas.c.familia_id, ventas.c.ventas, ventas.c.en_promocion)
        if hasta is not None:
            q = q.where(ventas.c.fecha <= _a_fecha(hasta))
        with self.motor.connect() as con:
            filas = con.execute(q.order_by(ventas.c.fecha)).all()
        return pd.DataFrame(filas, columns=["fecha", "tienda_id", "familia_id", "ventas", "en_promocion"])

    def historia_para_prediccion(self, tienda_id: int, fecha: date | str, dias: int = 60):
        """Observaciones de la tienda con fecha < ``fecha`` (últimos ``dias`` días con datos)."""
        import pandas as pd

        fecha = _a_fecha(fecha)
        with self.motor.connect() as con:
            ultima = con.execute(
                select(func.max(ventas.c.fecha)).where(ventas.c.tienda_id == tienda_id, ventas.c.fecha < fecha)
            ).scalar_one()
            if ultima is None:
                filas = []
            else:
                desde = ultima - timedelta(days=dias - 1)
                filas = con.execute(
                    select(ventas.c.fecha, ventas.c.tienda_id, ventas.c.familia_id, ventas.c.ventas,
                           ventas.c.en_promocion)
                    .where(ventas.c.tienda_id == tienda_id, ventas.c.fecha >= desde, ventas.c.fecha < fecha)
                ).all()
        return pd.DataFrame(filas, columns=["fecha", "tienda_id", "familia_id", "ventas", "en_promocion"])

    def ping(self) -> None:
        with self.motor.connect() as con:
            con.execute(select(1))

    # -------------------------------------------------------- reentrenamiento
    def crear_ejecucion(
        self, motivo: str | None = None, id: str | None = None, airflow_run_id: str | None = None
    ) -> str:
        id = id or uuid.uuid4().hex
        with self.motor.begin() as con:
            con.execute(insert(ejecuciones_reentrenamiento).values(
                id=id, estado="en_curso", promovido=False, motivo=motivo, airflow_run_id=airflow_run_id
            ))
        return id

    def actualizar_ejecucion(
        self,
        id: str,
        *,
        estado: str | None = None,
        promovido: bool | None = None,
        version: str | None = None,
        motivo: str | None = None,
        metricas: Mapping[str, Any] | None = None,
        airflow_run_id: str | None = None,
    ) -> None:
        if estado is not None and estado not in ESTADOS_EJECUCION:
            raise ValueError(f"estado inválido: {estado}; válidos: {', '.join(ESTADOS_EJECUCION)}")
        cambios: dict[str, Any] = {
            k: v for k, v in {
                "estado": estado, "promovido": promovido, "version": version, "motivo": motivo,
                "metricas": dict(metricas) if metricas is not None else None, "airflow_run_id": airflow_run_id,
            }.items() if v is not None
        }
        if estado in ("exitoso", "fallido"):
            cambios["finalizado_en"] = func.now()
        if not cambios:
            return
        with self.motor.begin() as con:
            r = con.execute(
                update(ejecuciones_reentrenamiento)
                .where(ejecuciones_reentrenamiento.c.id == id)
                .values(**cambios)
            )
            if r.rowcount == 0:
                raise KeyError(f"no existe la ejecución {id}")

    def obtener_ejecucion(self, id: str) -> dict | None:
        with self.motor.connect() as con:
            fila = con.execute(
                select(ejecuciones_reentrenamiento).where(ejecuciones_reentrenamiento.c.id == id)
            ).first()
        return dict(fila._mapping) if fila else None

    def listar_ejecuciones(self, limite: int = 20) -> list[dict]:
        with self.motor.connect() as con:
            filas = con.execute(
                select(ejecuciones_reentrenamiento)
                .order_by(ejecuciones_reentrenamiento.c.iniciado_en.desc())
                .limit(limite)
            )
            return [dict(r._mapping) for r in filas]


# --------------------------------------------------------------------------- #
# Catálogos desde la BD (Airflow lee todo del PostgreSQL del producto)
# --------------------------------------------------------------------------- #
def leer_catalogos(motor: Engine) -> Catalogos:
    with motor.connect() as con:
        ts = {
            r.tienda_id: Tienda(r.tienda_id, r.nombre, r.ciudad, r.departamento, r.tipo, r.fecha_apertura)
            for r in con.execute(select(tiendas))
        }
        fams = {r.familia_id: r.nombre for r in con.execute(select(familias))}
        cts = {
            r.familia_id: {"costo_faltante": r.costo_faltante, "costo_sobrante": r.costo_sobrante}
            for r in con.execute(select(costos))
        }
        fers = tuple(
            {"fecha": r.fecha, "nombre": r.nombre, "tipo": r.tipo, "ambito": r.ambito}
            for r in con.execute(select(feriados).order_by(feriados.c.fecha))
        )
        max_tf = {
            (r[0], r[1]): r[2]
            for r in con.execute(
                select(ventas.c.tienda_id, ventas.c.familia_id, func.max(ventas.c.ventas))
                .group_by(ventas.c.tienda_id, ventas.c.familia_id)
            )
        }
        agg_f = con.execute(
            select(ventas.c.familia_id, func.max(ventas.c.ventas), func.max(ventas.c.en_promocion))
            .group_by(ventas.c.familia_id)
        ).all()
        fmin, fmax = con.execute(select(func.min(ventas.c.fecha), func.max(ventas.c.fecha))).one()
    por_tienda: dict[int, set[str]] = {}
    for t, f in max_tf:
        por_tienda.setdefault(t, set()).add(f)
    return Catalogos(
        tiendas=ts,
        familias=fams,
        costos=cts,
        feriados=fers,
        max_ventas=max_tf,
        max_ventas_familia={r[0]: r[1] for r in agg_f},
        max_promo_familia={r[0]: r[2] for r in agg_f if r[2] is not None},
        familias_por_tienda={t: frozenset(s) for t, s in por_tienda.items()},
        fecha_min_historico=fmin,
        fecha_max_historico=fmax,
    )


def estado_carga(motor: Engine) -> dict[str, int]:
    """Conteos para decidir si el bootstrap debe cargar datos."""
    with motor.connect() as con:
        return {
            "tiendas": con.execute(select(func.count()).select_from(tiendas)).scalar_one(),
            "familias": con.execute(select(func.count()).select_from(familias)).scalar_one(),
            "historico": con.execute(
                select(func.count()).select_from(ventas).where(ventas.c.origen == "historico")
            ).scalar_one(),
            "observaciones": con.execute(
                select(func.count()).select_from(ventas).where(ventas.c.origen == "observacion")
            ).scalar_one(),
        }
