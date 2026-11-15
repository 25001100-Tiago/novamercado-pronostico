"""Monitor de dependencias: verificación periódica (15 s) con timeouts cortos."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

import httpx

TIMEOUT_SEGUNDOS = 3.0
INTERVALO_SEGUNDOS = 15.0
ANTIGUEDAD_MAXIMA = 20.0  # si el último chequeo es más viejo, /health verifica en vivo


@dataclass(frozen=True)
class Resultado:
    ok: bool
    detalle: str
    verificado_en: float


class MonitorSalud:
    def __init__(self, verificaciones: dict[str, Callable[[], None]], timeout: float = TIMEOUT_SEGUNDOS):
        self.verificaciones = verificaciones
        self.timeout = timeout
        self.resultados: dict[str, Resultado] = {}
        self._pool = ThreadPoolExecutor(max_workers=max(1, len(verificaciones)), thread_name_prefix="salud")

    def verificar_todo(self) -> dict[str, Resultado]:
        futuros = {n: self._pool.submit(f) for n, f in self.verificaciones.items()}
        ahora = time.time()
        for nombre, fut in futuros.items():
            try:
                fut.result(timeout=self.timeout + 1)
                self.resultados[nombre] = Resultado(True, "ok", ahora)
            except Exception as e:
                detalle = f"{type(e).__name__}: {e}".strip()[:200] or type(e).__name__
                self.resultados[nombre] = Resultado(False, detalle, ahora)
        return self.resultados

    def vigente(self) -> bool:
        if set(self.resultados) != set(self.verificaciones):
            return False
        return min(r.verificado_en for r in self.resultados.values()) > time.time() - ANTIGUEDAD_MAXIMA

    def caidas(self) -> dict[str, str]:
        if not self.vigente():
            self.verificar_todo()
        return {n: r.detalle for n, r in self.resultados.items() if not r.ok}


def verificar_http(url: str, timeout: float = TIMEOUT_SEGUNDOS, validar: Callable[[httpx.Response], None] | None = None):
    def _verificar() -> None:
        r = httpx.get(url, timeout=timeout)
        r.raise_for_status()
        if validar:
            validar(r)

    return _verificar


def validar_airflow(r: httpx.Response) -> None:
    datos = r.json()
    for componente in ("metadatabase", "scheduler"):
        estado = (datos.get(componente) or {}).get("status")
        if estado != "healthy":
            raise RuntimeError(f"{componente} de Airflow en estado {estado}")
