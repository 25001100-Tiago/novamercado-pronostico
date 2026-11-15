# CLAUDE.md — NovaMercado: servicio de pronóstico en producción (Laboratorio 2)

Servicio que pronostica ventas diarias por tienda (10) y familia (12) para NovaMercado,
recibe observaciones reales, las persiste y reentrena el modelo (MLflow + Airflow).

## Entorno y comandos

El código vive en WSL (`~/product-dev/novamercado`). Ejecutar todo dentro de WSL:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q                       # SQLite en memoria, sin Docker ni MLflow
TEST_DATABASE_URL=postgresql+psycopg://u:p@localhost:5432/db .venv/bin/python -m pytest -q  # + PostgreSQL
.venv/bin/python scripts/inicializar_bd.py          # esquema + catálogos + histórico (idempotente)
```

`pyproject.toml` configura `pythonpath = ["src", "."]` para pytest (paquetes `novamercado` y `api`).

## Estructura

- `src/novamercado/` — lógica de dominio
  - `config.py` — variables de entorno (`DATABASE_URL`, `NOVAMERCADO_DATA_DIR`).
  - `catalogos.py` — tiendas, familias, costos, feriados + estadísticas del histórico (máximos, rango de fechas).
  - `limpieza.py` — **motor de defensa del contrato** (reparar / advertir / rechazar).
  - `db.py` — persistencia SQLAlchemy Core (PostgreSQL; SQLite en memoria para pruebas).
- `api/esquemas.py` — modelos Pydantic estrictos + fachada `validar_prediccion` / `validar_observaciones` / `cuerpo_error`.
- `dags/` (Airflow), `docker/` (imágenes/compose), `scripts/`, `tests/`, `docs/evidencia/`.
- `data/raw/` — datos crudos versionados. Ejemplos válidos en `data/raw/ejemplos/`, casos E01–E10 en `data/raw/errores/`.

## Contrato (no romper)

- `POST /v1/prediccion`: `{tienda_id, fecha, familias: [{familia_id, en_promocion}]}`.
- `POST /v1/observaciones`: `{tienda_id, fecha, ventas: [{familia_id, ventas, en_promocion?}]}` → `{registros_guardados, calidad}`.
- Bloque de calidad **exacto**: `{"estado": "ok"|"corregido"|"advertencia", "observaciones": [{"campo", "accion", "detalle"}]}`.
  - `accion` ∈ `reparar` | `advertir`. `estado == "ok"` ⇔ `observaciones == []`.
  - `advertencia` si hay alguna advertencia; si solo hubo reparaciones, `corregido`.
- Rechazo: HTTP 422 con `{"detail": [{"campo", "accion": "rechazar", "detalle"}]}` (se reportan todos los errores a la vez).
- Los endpoints deben recibir el JSON **crudo** (`dict`/`Body`) y pasarlo por `validar_*`; no declarar el modelo
  estricto como parámetro de FastAPI (su 422 automático impediría reparar).

## Política de limpieza (resumen; detalle en el docstring de `limpieza.py`)

| Caso | Acción |
|---|---|
| E01 tienda `"T05"`, `"05"`, `"tienda_5"`, `5.0` | reparar |
| E02 familia `"LÁCTEOS"`, `"Frutas y Verduras"`, typo leve con coincidencia única | reparar |
| E03/E10 números como texto, `8.0`, `"1,292"` (miles), `"50,0"` (coma decimal) | reparar |
| E04 fecha DD/MM/AAAA, AAAA/MM/DD, DD-MM-AAAA, ISO con hora, AAAAMMDD | reparar (DD/MM ambiguo → advertir) |
| E07 campo renombrado con sinónimo conocido (`tienda`) | reparar (alias contradictorio → rechazar) |
| E05 faltan familias | advertir (se pronostica/guarda solo lo enviado) |
| E06 familia repetida | idénticas → reparar; distintas → advertir, se conserva la última |
| `en_promocion` nulo/ausente | advertir, se asume 0 |
| Valor extremo (> máx. histórico) | advertir; inverosímil (≥ 10–20× máx.) → rechazar |
| Campo desconocido | advertir y se ignora |
| E08 negativos, no enteros, `"994.000"` ambiguo, tienda inexistente/≤0, familia irreconocible, fecha inválida o anterior a la apertura, lista vacía, campo obligatorio ausente | rechazar 422 |
| E09 envío repetido | se acepta; la BD lo hace idempotente (`registros_guardados: 0`) |

## Reglas críticas

- **Nunca** usar `datetime.today()`, `date.today()`, `datetime.now()` ni `time.time()` para validar o decidir:
  operamos con fechas simuladas. El "hoy" es `fecha_referencia` o el último día con datos
  (`Repositorio.fecha_max_ventas()` / `Catalogos.fecha_max_historico`). Hay una prueba que lo vigila.
- `guardar_observaciones` es un único `INSERT ... ON CONFLICT DO UPDATE ... WHERE ventas <> excluded.ventas RETURNING`:
  cuenta solo filas nuevas o con ventas cambiadas. No reemplazar por SELECT+INSERT (no es atómico).
  Un cambio solo en `en_promocion` no cuenta como registro guardado.
- Toda predicción persistida lleva `version_modelo`. Toda corrección/rechazo se guarda en `correcciones`.
- No usar `rowcount` para contar inserciones (psycopg devuelve -1 en lotes); usar `RETURNING`.
- Las pruebas no deben depender de MLflow ni Docker activos.
- Código, mensajes y nombres en español.
