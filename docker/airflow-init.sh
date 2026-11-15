#!/usr/bin/env bash
# Inicialización de Airflow: migra la BD de metadatos y escribe el archivo de
# contraseñas del SimpleAuthManager a partir de variables de entorno (nada queda en la imagen).
set -euo pipefail

mkdir -p /opt/airflow/auth
printf '{"%s": "%s"}\n' "${AIRFLOW_USUARIO:-admin}" "${AIRFLOW_CLAVE:-admin}" > /opt/airflow/auth/passwords.json
chmod 600 /opt/airflow/auth/passwords.json

airflow db migrate
echo "Airflow inicializado"
