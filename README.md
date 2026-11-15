# NovaMercado — Servicio de pronóstico en producción

Laboratorio 2: servicio de ML que pronostica ventas diarias por tienda y familia,
defiende su contrato frente a solicitudes mal formadas, persiste observaciones y
reentrena el modelo.

## Estado actual

- [x] Capa de datos: catálogos, motor de limpieza (`src/novamercado/limpieza.py`) y
      esquemas Pydantic (`api/esquemas.py`) para `POST /v1/prediccion` y `POST /v1/observaciones`.
- [x] Persistencia PostgreSQL / SQLite (`src/novamercado/db.py`) con observaciones idempotentes.
- [x] Pruebas (`tests/test_contrato_y_limpieza.py`).
- [ ] API FastAPI, modelo + MLflow, DAG de reentrenamiento en Airflow, Docker Compose.

## Uso rápido

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
cp .env.example .env   # ajustar DATABASE_URL
.venv/bin/python scripts/inicializar_bd.py
```

La política completa de reparar / advertir / rechazar está documentada en `CLAUDE.md`
y en el docstring de `src/novamercado/limpieza.py`.
