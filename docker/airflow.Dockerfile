# Airflow 3 + entorno virtual aislado con el código de entrenamiento de NovaMercado.
# Las tareas del DAG ejecutan /opt/airflow/novamercado-venv/bin/python para no mezclar
# dependencias (SQLAlchemy 2.x, scikit-learn, MLflow) con las del propio Airflow.
FROM apache/airflow:3.3.2-python3.12

USER airflow
RUN python -m venv /opt/airflow/novamercado-venv

COPY --chown=airflow:root requirements.txt /opt/airflow/novamercado-app/requirements.txt
RUN /opt/airflow/novamercado-venv/bin/pip install --no-cache-dir -r /opt/airflow/novamercado-app/requirements.txt

COPY --chown=airflow:root pyproject.toml /opt/airflow/novamercado-app/pyproject.toml
COPY --chown=airflow:root src /opt/airflow/novamercado-app/src
RUN /opt/airflow/novamercado-venv/bin/pip install --no-cache-dir --no-deps /opt/airflow/novamercado-app \
    && mkdir -p /opt/airflow/auth

COPY --chown=airflow:root docker/airflow-init.sh /opt/airflow/novamercado-init.sh

ENV NOVAMERCADO_PYTHON=/opt/airflow/novamercado-venv/bin/python \
    GIT_PYTHON_REFRESH=quiet
