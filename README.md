# NovaMercado — Servicio de pronóstico en producción (Laboratorio 2)

Servicio de ML que pronostica la venta diaria por **tienda (10) × familia (12)**, sugiere la
cantidad a enviar minimizando el costo asimétrico de faltantes/sobrantes, defiende su
contrato ante solicitudes mal formadas, persiste observaciones reales y se reentrena con
Airflow, promoviendo un nuevo modelo solo si reduce el costo de negocio.

## Arquitectura

```
                         ┌──────────────────────────── docker compose ────────────────────────────┐
  cliente ──HTTP:8000──► │  api (FastAPI)                                                          │
                         │   ├─ defensa del contrato (limpieza.py + esquemas Pydantic)              │
                         │   ├─ modelo @champion en memoria + caché en disco (volumen api-cache)    │
                         │   ├─ hot-reload: consulta @champion cada 20 s ───────────────┐           │
                         │   ├─ /health: chequea BD, MLflow y Airflow cada 15 s          │           │
                         │   └─ POST /admin/reentrenar ──REST v2──► airflow-apiserver:8080           │
                         │                                              │                │           │
                         │  db-producto (PostgreSQL 16)  ◄──────────────┼── DAG reentrenamiento_    │
                         │   catálogos, ventas (histórico +             │   novamercado            │
                         │   observaciones), solicitudes,               │   (scheduler + dag-      │
                         │   predicciones, correcciones,                │   processor, Local-      │
                         │   ejecuciones_reentrenamiento                │   Executor)              │
                         │                                              ▼                │           │
                         │  mlflow:5000 (v3.17.2, backend SQLite, artefactos en volumen) ◄┘           │
                         │   experimento novamercado-ventas · modelo novamercado-pronostico          │
                         │   alias @champion / @challenger                                          │
                         │                                                                          │
                         │  db-airflow (PostgreSQL 16, metadatos de Airflow)                        │
                         │  bootstrap (una vez): carga CSV → BD y entrena el 1er modelo si no existe │
                         └──────────────────────────────────────────────────────────────────────────┘
```

| Servicio | Imagen | Puerto | Volumen persistente |
|---|---|---|---|
| `db-producto` | `postgres:16.10` | interno | `db-producto-datos` |
| `db-airflow` | `postgres:16.10` | interno | `db-airflow-datos` |
| `mlflow` | `ghcr.io/mlflow/mlflow:v3.17.2` | 5000 | `mlflow-datos` (SQLite + artefactos) |
| `airflow-init`, `airflow-apiserver`, `airflow-scheduler`, `airflow-dag-processor` | `novamercado-airflow:3.3.2` (de `apache/airflow:3.3.2-python3.12`) | 8080 | `airflow-logs`, `airflow-auth` |
| `bootstrap` | `novamercado-api:1.0` (de `python:3.12-slim`) | — | — |
| `api` | `novamercado-api:1.0` | 8000 | `api-cache` |

Ninguna imagen contiene datos ni credenciales: los CSV se montan en solo lectura y la
configuración llega por variables de entorno (`.env`).

## Dónde colocar los archivos publicados

Los datos **no se versionan**. Copia los archivos publicados exactamente en `data/raw/`:

```
data/raw/tiendas.csv
data/raw/familias.csv
data/raw/historico_ventas.csv
data/raw/feriados.csv
data/raw/costos.csv
data/raw/catalogo_errores.md
data/raw/ejemplos/prediccion_valida.json
data/raw/ejemplos/observacion_valida.json
data/raw/errores/E01_tienda_texto.json … E10_numero_formato.json
```

## Levantar todo desde cero

```bash
git clone https://github.com/25001100-Tiago/novamercado-pronostico.git
cd novamercado-pronostico
# 1) copiar los archivos publicados a data/raw/ (ver arriba)
# 2) credenciales (opcional en desarrollo: hay valores por defecto)
cp .env.example .env
# 3) construir y levantar
docker compose up -d --build
# 4) esperar a que esté sano (≈ 1–2 min la primera vez: carga de datos + primer entrenamiento)
curl http://localhost:8000/health        # {"estado":"ok"}
```

- API y documentación interactiva: http://localhost:8000/docs
- MLflow: http://localhost:5000 · Airflow: http://localhost:8080 (usuario/clave de `.env`, por defecto `admin`/`admin`)
- Detener conservando datos y modelos: `docker compose down` · Borrar todo: `docker compose down -v`

Al volver a levantar con los volúmenes existentes, `bootstrap` detecta que los datos y
`novamercado-pronostico@champion` ya existen y no repite la carga ni el entrenamiento.

## Endpoints

| Método y ruta | Respuesta |
|---|---|
| `POST /v1/prediccion` | 200 `{tienda_id, fecha, version_modelo, predicciones: [{familia_id, en_promocion, venta_esperada, cantidad_sugerida}], calidad}` · 422 `{detail}` |
| `POST /v1/observaciones` | 200 `{registros_guardados, calidad}` (idempotente) · 422 `{detail}` |
| `POST /admin/reentrenar` | 202 `{id}` · 503 si Airflow no puede iniciarlo |
| `GET /admin/reentrenar/{id}` | `{id, estado: en_curso\|exitoso\|fallido}` + al terminar `promovido`, `version`, `motivo` · 404 |
| `GET /modelo` | `{nombre, alias: "champion", version}` |
| `GET /health` | 200 `{"estado":"ok"}` · 200 `{"estado":"degradado","motivo":…}` · 503 sin modelo |

`calidad = {"estado": "ok"|"corregido"|"advertencia", "observaciones": [{campo, accion, detalle}]}`.

```bash
curl -s -X POST localhost:8000/v1/prediccion -H 'content-type: application/json' \
     -d @data/raw/ejemplos/prediccion_valida.json
```

## Pruebas y auditoría

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q                         # 278 pruebas, sin Docker ni MLflow
.venv/bin/python scripts/auditoria_evaluador.py       # contra el stack en vivo
```

La auditoría verifica salud, contrato, operación diaria e idempotencia, reentrenamiento y
hot-reload, caída de MLflow y persistencia de volúmenes; el último reporte está en
[`docs/evidencia/reporte_auditoria.md`](docs/evidencia/reporte_auditoria.md).

## Estructura

```
api/                 FastAPI: main.py, esquemas.py, servicio_modelo.py, salud.py, airflow_cliente.py
src/novamercado/     limpieza.py, catalogos.py, db.py, modelo.py, entrenamiento.py, registro.py, bootstrap.py
dags/                reentrenamiento_novamercado.py (Airflow 3)
docker/              api.Dockerfile, airflow.Dockerfile, airflow-init.sh
scripts/             auditoria_evaluador.py, inicializar_bd.py
tests/               test_contrato_y_limpieza.py, test_modelo.py, test_api_endpoints.py
docs/evidencia/      reporte_auditoria.md
DECISIONES.md        justificación de las decisiones de diseño
```
