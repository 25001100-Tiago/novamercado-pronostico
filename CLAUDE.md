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

## Stack (docker compose)

```bash
docker compose up -d --build                     # db-producto, db-airflow, mlflow, airflow-*, bootstrap, api
.venv/bin/python scripts/auditoria_evaluador.py   # auditoría en vivo -> docs/evidencia/reporte_auditoria.md
```
Desde PowerShell, ejecutar comandos de WSL con `wsl -e bash script.sh` (las comillas internas se pierden).

## Contrato (no romper)

- `POST /v1/prediccion`: `{tienda_id, fecha, familias: [{familia_id, en_promocion}]}` →
  `{tienda_id, fecha, version_modelo (str), predicciones: [{familia_id, venta_esperada (float), cantidad_sugerida (int>=0)}], calidad}`.
  Cada predicción lleva **solo** esos tres campos (Anexo); no agregar `en_promocion` ni otros.
- `POST /admin/reentrenar` (sin cuerpo) → 202 `{id}` | 503; `GET /admin/reentrenar/{id}` → `{estado}` en curso;
  al terminar `{estado, promovido (bool), version (str), motivo}`; sin `id` en el cuerpo; 404 si no existe.
- `GET /modelo` → `{nombre, alias, version}` (str). `GET /health` → `ok` | `degradado`+`motivo` (200) | 503 sin modelo.
- `POST /v1/observaciones`: `{tienda_id, fecha, ventas: [{familia_id, ventas, en_promocion?}]}` → `{registros_guardados, calidad}`.
- Bloque de calidad **exacto**: `{"estado": "ok"|"corregido"|"advertencia", "observaciones": [{"campo", "accion", "detalle"}]}`.
  - `accion` ∈ `reparar` | `advertir`. `estado == "ok"` ⇔ `observaciones == []`.
  - `advertencia` si hay alguna advertencia; si solo hubo reparaciones, `corregido`.
- Rechazo: HTTP 422 con `{"detail": [{"campo", "accion": "rechazar", "detalle"}]}` (se reportan todos los errores a la vez).
- Los endpoints deben recibir el JSON **crudo** (`dict`/`Body`) y pasarlo por `validar_*`; no declarar el modelo
  estricto como parámetro de FastAPI (su 422 automático impediría reparar).

La política reparar / advertir / rechazar (casos E01–E10) está en el docstring de `src/novamercado/limpieza.py`.

## Reglas críticas

- `data/raw/` contiene los datos publicados y **no se versiona** (ver `data/raw/LEEME.md`); las pruebas se omiten si faltan.

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
