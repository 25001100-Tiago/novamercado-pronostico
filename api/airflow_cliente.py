"""Cliente mínimo de la REST API v2 de Airflow 3 (token JWT + dagRuns)."""

from __future__ import annotations

import threading
import time

import httpx


class ErrorAirflow(RuntimeError):
    pass


class ClienteAirflow:
    def __init__(self, url: str, usuario: str, clave: str, dag_id: str, timeout: float = 10.0):
        self.url = url.rstrip("/")
        self.usuario = usuario
        self.clave = clave
        self.dag_id = dag_id
        self.timeout = timeout
        self._token: str | None = None
        self._token_expira = 0.0
        self._lock = threading.Lock()

    def _obtener_token(self, forzar: bool = False) -> str:
        with self._lock:
            if forzar or not self._token or time.time() > self._token_expira:
                r = httpx.post(
                    f"{self.url}/auth/token",
                    json={"username": self.usuario, "password": self.clave},
                    timeout=self.timeout,
                )
                if r.status_code not in (200, 201):
                    raise ErrorAirflow(f"autenticación con Airflow falló ({r.status_code}): {r.text[:200]}")
                self._token = r.json()["access_token"]
                self._token_expira = time.time() + 600
            return self._token

    def _peticion(self, metodo: str, ruta: str, **kw) -> httpx.Response:
        for intento in range(2):
            token = self._obtener_token(forzar=intento > 0)
            try:
                r = httpx.request(
                    metodo, f"{self.url}/api/v2{ruta}", headers={"Authorization": f"Bearer {token}"},
                    timeout=self.timeout, **kw,
                )
            except httpx.HTTPError as e:
                raise ErrorAirflow(f"Airflow no responde: {e}") from e
            if r.status_code != 401:
                return r
        return r

    def disparar(self, conf: dict, dag_run_id: str | None = None) -> str:
        try:
            self._peticion("PATCH", f"/dags/{self.dag_id}", json={"is_paused": False})
        except ErrorAirflow:
            raise
        cuerpo = {"logical_date": None, "conf": conf}
        if dag_run_id:
            cuerpo["dag_run_id"] = dag_run_id
        r = self._peticion("POST", f"/dags/{self.dag_id}/dagRuns", json=cuerpo)
        if r.status_code == 404:
            raise ErrorAirflow(f"el DAG {self.dag_id} no existe en Airflow (¿aún no se ha procesado?)")
        if r.status_code not in (200, 201):
            raise ErrorAirflow(f"Airflow rechazó la corrida ({r.status_code}): {r.text[:300]}")
        return r.json()["dag_run_id"]

    def estado(self, dag_run_id: str) -> str:
        r = self._peticion("GET", f"/dags/{self.dag_id}/dagRuns/{dag_run_id}")
        if r.status_code != 200:
            raise ErrorAirflow(f"no se pudo consultar la corrida ({r.status_code})")
        return r.json()["state"]
