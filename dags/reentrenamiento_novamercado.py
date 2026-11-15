"""DAG de reentrenamiento de NovaMercado (Airflow 3).

Flujo: preparar_datos -> entrenar_candidato -> compuerta_y_promocion
       (registrar_fallo se ejecuta solo si alguna tarea falla)

* Lee el histórico y todas las observaciones acumuladas en el PostgreSQL del producto.
* Entrena el candidato (HistGradientBoostingRegressor) y lo registra en MLflow
  (experimento ``novamercado-ventas``, modelo ``novamercado-pronostico``, alias ``challenger``).
* Compuerta: evalúa @champion y challenger en la misma ventana de validación reciente y
  mueve ``@champion`` solo si el challenger reduce el costo de negocio.
* Actualiza ``ejecuciones_reentrenamiento`` (lo que devuelve GET /admin/reentrenar/{id}).

Las tareas corren el código del producto en un entorno virtual propio dentro de la imagen
(``NOVAMERCADO_PYTHON``) para no mezclar dependencias con las de Airflow.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

PYTHON = os.environ.get("NOVAMERCADO_PYTHON", "/opt/airflow/novamercado-venv/bin/python")
CLI = f"{PYTHON} -m novamercado.entrenamiento"
ID_EJECUCION = "{{ ti.xcom_pull(task_ids='preparar_datos') or '' }}"

with DAG(
    dag_id="reentrenamiento_novamercado",
    description="Reentrena el pronóstico de NovaMercado y promueve @champion si reduce el costo",
    schedule=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=False,
    default_args={"retries": 0, "execution_timeout": timedelta(minutes=20)},
    tags=["novamercado", "mlops"],
    doc_md=__doc__,
) as dag:
    preparar = BashOperator(
        task_id="preparar_datos",
        bash_command=f"{CLI} preparar",
        env={"EJECUCION_ID": "{{ (dag_run.conf or {}).get('ejecucion_id', '') }}", "AIRFLOW_RUN_ID": "{{ run_id }}"},
        append_env=True,
        do_xcom_push=True,  # la última línea impresa es el id de la ejecución
    )
    entrenar = BashOperator(
        task_id="entrenar_candidato",
        bash_command=f"{CLI} entrenar",
        env={"EJECUCION_ID": ID_EJECUCION},
        append_env=True,
        do_xcom_push=False,
    )
    promover = BashOperator(
        task_id="compuerta_y_promocion",
        bash_command=f"{CLI} promover",
        env={"EJECUCION_ID": ID_EJECUCION},
        append_env=True,
        do_xcom_push=False,
    )
    fallo = BashOperator(
        task_id="registrar_fallo",
        bash_command=f'{CLI} fallar --motivo "falló una tarea del DAG (corrida {{{{ run_id }}}})"',
        env={"EJECUCION_ID": "{{ ti.xcom_pull(task_ids='preparar_datos') or (dag_run.conf or {}).get('ejecucion_id', '') }}"},
        append_env=True,
        trigger_rule="one_failed",
        do_xcom_push=False,
    )

    preparar >> entrenar >> promover
    [preparar, entrenar, promover] >> fallo
