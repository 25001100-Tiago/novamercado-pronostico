# Imagen de la API y del bootstrap. No contiene datos ni credenciales:
# los CSV se montan en /datos (solo lectura) y la configuración llega por variables de entorno.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    GIT_PYTHON_REFRESH=quiet

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml ./
COPY src ./src
COPY api ./api
COPY scripts ./scripts
RUN pip install --no-cache-dir --no-deps . \
    && useradd --create-home --uid 1000 app \
    && mkdir -p /app/cache \
    && chown app /app/cache

USER app
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
