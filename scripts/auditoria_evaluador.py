"""Auditoría de punta a punta contra el stack en vivo (simula al evaluador).

Uso (desde la raíz del repo, con el stack levantado):
    python scripts/auditoria_evaluador.py [--url http://localhost:8000] [--secciones 1,2,3,4,5,6]

Verifica: 1) salud y modelo, 2) contrato y defensa ante errores, 3) operación diaria e
idempotencia, 4) reentrenamiento y hot-reload, 5) caída de MLflow, 6) persistencia de
volúmenes. Escribe docs/evidencia/reporte_auditoria.md con los JSON reales.
Requiere: httpx, docker compose en el PATH y los datos publicados en data/raw/.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import os
import random
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parents[1]
DATOS = RAIZ / "data" / "raw"
REPORTE = RAIZ / "docs" / "evidencia" / "reporte_auditoria.md"
MLFLOW = os.getenv("AUDITORIA_MLFLOW_URL", "http://localhost:5000")
MODELO = "novamercado-pronostico"


# --------------------------------------------------------------------------- #
# Registro de resultados
# --------------------------------------------------------------------------- #
@dataclass
class Seccion:
    numero: int
    titulo: str
    chequeos: list[tuple[str, bool, str]] = field(default_factory=list)
    evidencias: list[str] = field(default_factory=list)
    notas: list[str] = field(default_factory=list)

    def chequear(self, descripcion: str, ok: bool, detalle: str = "") -> bool:
        self.chequeos.append((descripcion, bool(ok), detalle))
        print(f"  [{'OK' if ok else 'FALLA'}] {descripcion}" + (f" — {detalle}" if detalle and not ok else ""))
        return bool(ok)

    @property
    def ok(self) -> bool:
        return all(c[1] for c in self.chequeos)


def _json(x, limite: int = 6000) -> str:
    texto = json.dumps(x, ensure_ascii=False, indent=2, default=str)
    return texto if len(texto) <= limite else texto[:limite] + "\n... (truncado)"


class Auditoria:
    def __init__(self, url: str):
        self.url = url.rstrip("/")
        self.http = httpx.Client(base_url=self.url, timeout=30)
        self.secciones: list[Seccion] = []
        self.actual: Seccion | None = None
        self.inicio = datetime.now()

    def seccion(self, numero: int, titulo: str) -> Seccion:
        print(f"\n== {numero}. {titulo}")
        self.actual = Seccion(numero, titulo)
        self.secciones.append(self.actual)
        return self.actual

    def llamar(self, metodo: str, ruta: str, cuerpo=None, *, evidencia: str | None = None, **kw):
        t0 = time.perf_counter()
        try:
            r = self.http.request(metodo, ruta, json=cuerpo, **kw)
            codigo = r.status_code
            try:
                datos = r.json()
            except ValueError:
                datos = r.text
        except httpx.HTTPError as e:
            codigo, datos = 0, {"error_conexion": str(e)}
        ms = (time.perf_counter() - t0) * 1000
        if evidencia and self.actual:
            bloque = f"**{evidencia}** — `{metodo} {ruta}` → HTTP {codigo} ({ms:.0f} ms)\n"
            if cuerpo is not None:
                bloque += f"\nSolicitud:\n```json\n{_json(cuerpo, 2500)}\n```\n"
            bloque += f"\nRespuesta:\n```json\n{_json(datos)}\n```\n"
            self.actual.evidencias.append(bloque)
        return codigo, datos


def compose(*args: str, timeout: int = 300) -> str:
    r = subprocess.run(["docker", "compose", *args], cwd=RAIZ, capture_output=True, text=True, timeout=timeout)
    return (r.stdout + r.stderr).strip()


def psql(sql: str) -> str:
    usuario = os.getenv("POSTGRES_USER", "novamercado")
    bd = os.getenv("POSTGRES_DB", "novamercado")
    r = subprocess.run(
        ["docker", "compose", "exec", "-T", "db-producto", "psql", "-U", usuario, "-d", bd, "-t", "-A", "-c", sql],
        cwd=RAIZ, capture_output=True, text=True, timeout=60,
    )
    return r.stdout.strip()


def leer(ruta: Path) -> dict:
    return json.loads(ruta.read_text(encoding="utf-8"))


def esperar(condicion, limite: float, pausa: float = 3.0):
    """Repite ``condicion()`` hasta que devuelva algo verdadero; devuelve (valor, segundos)."""
    t0 = time.time()
    valor = None
    while time.time() - t0 < limite:
        valor = condicion()
        if valor:
            return valor, time.time() - t0
        time.sleep(pausa)
    return valor, time.time() - t0


def validar_prediccion(s: Seccion, datos, etiqueta: str) -> bool:
    ok = isinstance(datos, dict) and isinstance(datos.get("version_modelo"), str) and bool(datos.get("predicciones"))
    ok = ok and all(
        isinstance(p.get("cantidad_sugerida"), int) and not isinstance(p.get("cantidad_sugerida"), bool)
        and p["cantidad_sugerida"] >= 0 for p in datos["predicciones"]
    )
    calidad = datos.get("calidad", {}) if isinstance(datos, dict) else {}
    ok = ok and calidad.get("estado") in ("ok", "corregido", "advertencia")
    ok = ok and ((calidad.get("estado") == "ok") == (calidad.get("observaciones") == []))
    return s.chequear(f"{etiqueta}: version_modelo str, cantidad_sugerida int >= 0, calidad válida", ok,
                      _json(datos, 300))


# --------------------------------------------------------------------------- #
# 1. Salud inicial
# --------------------------------------------------------------------------- #
def prueba_salud(a: Auditoria) -> None:
    s = a.seccion(1, "Salud inicial y modelo")
    def sano():
        c, d = a.llamar("GET", "/health")
        return c == 200 and isinstance(d, dict) and d.get("estado") == "ok"

    _, seg = esperar(sano, 180, 3)
    codigo, datos = a.llamar("GET", "/health", evidencia="Salud")
    s.notas.append(f"/health respondió 'ok' tras {seg:.0f} s de espera")
    s.chequear("GET /health → 200 con estado == 'ok'", codigo == 200 and datos.get("estado") == "ok", _json(datos))
    c, m = a.llamar("GET", "/modelo", evidencia="Modelo vigente")
    s.chequear("GET /modelo → 200", c == 200, _json(m))
    s.chequear("nombre, alias y version son str",
               isinstance(m, dict) and all(isinstance(m.get(k), str) and m.get(k) for k in ("nombre", "alias", "version")),
               _json(m))
    s.chequear("alias == 'champion'", isinstance(m, dict) and m.get("alias") == "champion")


# --------------------------------------------------------------------------- #
# 2. Contrato
# --------------------------------------------------------------------------- #
ESPERADO_ERRORES = {
    "E01_tienda_texto.json": ("prediccion", 200, "corregido"),
    "E02_familia_otra_forma.json": ("prediccion", 200, "corregido"),
    "E03_promocion_texto.json": ("prediccion", 200, "corregido"),
    "E04_fecha_formato.json": ("prediccion", 200, "corregido"),
    "E05_faltan_familias.json": ("prediccion", 200, "advertencia"),
    "E06_familia_repetida.json": ("prediccion", 200, "advertencia"),
    "E07_campo_renombrado.json": ("prediccion", 200, "corregido"),
    "E08_ventas_negativas.json": ("observaciones", 422, None),
    "E09_envio_repetido.json": ("observaciones", 200, "ok"),
    "E10_numero_formato.json": ("observaciones", 200, "corregido"),
}


def _nuevos_casos(base: dict) -> list[tuple[str, dict, int, str | None]]:
    def caso(mutar):
        p = copy.deepcopy(base)
        mutar(p)
        return p

    def familia(i, **kw):
        return lambda p: p["familias"][i].update(kw)

    return [
        ("tienda como texto con prefijo 'tienda_05'", caso(lambda p: p.update(tienda_id="tienda_05")), 200, "corregido"),
        ("tienda como texto ' 5 '", caso(lambda p: p.update(tienda_id=" 5 ")), 200, "corregido"),
        ("familia con mayúsculas y guion 'Cuidado-Personal'", caso(familia(4, familia_id="Cuidado-Personal")), 200, "corregido"),
        ("familia con tilde 'PANADERÍA'", caso(familia(10, familia_id="PANADERÍA")), 200, "corregido"),
        ("familia con error tipográfico 'Lacteso'", caso(familia(6, familia_id="Lacteso")), 200, "corregido"),
        ("fecha AAAA/MM/DD", caso(lambda p: p.update(fecha="2025/11/17")), 200, "corregido"),
        ("fecha invertida MM/DD/AAAA '11/17/2025'", caso(lambda p: p.update(fecha="11/17/2025")), 200, "corregido"),
        ("fecha ambigua DD/MM '05/11/2025'", caso(lambda p: p.update(fecha="05/11/2025")), 200, "advertencia"),
        ("en_promocion nulo", caso(familia(0, en_promocion=None)), 200, "advertencia"),
        ("en_promocion ausente", caso(lambda p: p["familias"][1].pop("en_promocion")), 200, "advertencia"),
        ("en_promocion '3,0' con coma decimal", caso(familia(2, en_promocion="3,0")), 200, "corregido"),
        ("campo 'Fecha' con mayúscula", caso(lambda p: p.update(Fecha=p.pop("fecha"))), 200, "corregido"),
        ("campo desconocido 'canal'", caso(lambda p: p.update(canal="pos")), 200, "advertencia"),
        ("FATAL tienda inexistente 99", caso(lambda p: p.update(tienda_id=99)), 422, None),
        ("FATAL tienda negativa -3", caso(lambda p: p.update(tienda_id=-3)), 422, None),
        ("FATAL familia irreconocible 'juguetes'", caso(familia(3, familia_id="juguetes")), 422, None),
        ("FATAL fecha inexistente 2025-02-30", caso(lambda p: p.update(fecha="2025-02-30")), 422, None),
        ("FATAL fecha anterior a la apertura (tienda 10)", caso(lambda p: p.update(tienda_id=10, fecha="2025-01-05")), 422, None),
        ("FATAL en_promocion negativo", caso(familia(0, en_promocion=-1)), 422, None),
        ("FATAL en_promocion decimal 2.5", caso(familia(0, en_promocion=2.5)), 422, None),
        ("FATAL lista de familias vacía", caso(lambda p: p.update(familias=[])), 422, None),
        ("FATAL falta tienda_id", caso(lambda p: p.pop("tienda_id")), 422, None),
    ]


def prueba_contrato(a: Auditoria) -> None:
    s = a.seccion(2, "Contrato y defensa ante errores")
    for ruta in sorted((DATOS / "ejemplos").glob("*.json")):
        cuerpo = leer(ruta)
        endpoint = "/v1/observaciones" if "ventas" in cuerpo else "/v1/prediccion"
        c, d = a.llamar("POST", endpoint, cuerpo, evidencia=f"ejemplos/{ruta.name}")
        s.chequear(f"ejemplos/{ruta.name} → 200 y calidad 'ok'",
                   c == 200 and d.get("calidad") == {"estado": "ok", "observaciones": []}, _json(d, 300))
        if endpoint == "/v1/prediccion" and c == 200:
            validar_prediccion(s, d, f"ejemplos/{ruta.name}")

    for nombre, (tipo, codigo_esp, estado_esp) in ESPERADO_ERRORES.items():
        cuerpo = leer(DATOS / "errores" / nombre)
        c, d = a.llamar("POST", f"/v1/{tipo}", cuerpo, evidencia=f"errores/{nombre}")
        if codigo_esp == 422:
            s.chequear(f"errores/{nombre} → 422 con detail", c == 422 and isinstance(d, dict) and d.get("detail"),
                       _json(d, 300))
        else:
            ok = c == 200 and d.get("calidad", {}).get("estado") == estado_esp
            s.chequear(f"errores/{nombre} → 200 con calidad '{estado_esp}'", ok, _json(d, 300))
            if tipo == "prediccion" and c == 200:
                validar_prediccion(s, d, f"errores/{nombre}")

    base = leer(DATOS / "ejemplos" / "prediccion_valida.json")
    for descripcion, cuerpo, codigo_esp, estado_esp in _nuevos_casos(base):
        c, d = a.llamar("POST", "/v1/prediccion", cuerpo, evidencia=f"Caso nuevo: {descripcion}")
        if codigo_esp == 422:
            ok = c == 422 and isinstance(d, dict) and isinstance(d.get("detail"), list) and d["detail"]
            s.chequear(f"{descripcion} → 422 con detail", ok, _json(d, 300))
        else:
            s.chequear(f"{descripcion} → 200 con calidad '{estado_esp}'",
                       c == 200 and d.get("calidad", {}).get("estado") == estado_esp, _json(d, 300))
            if c == 200:
                validar_prediccion(s, d, descripcion)

    c, d = a.llamar("POST", "/v1/prediccion", content=b"esto no es json", headers={"content-type": "application/json"},
                    evidencia="FATAL cuerpo que no es JSON")
    s.chequear("cuerpo que no es JSON → 422 con detail", c == 422 and d.get("detail"))
    obs = leer(DATOS / "ejemplos" / "observacion_valida.json")
    obs["ventas"][0]["ventas"] = "abc"
    c, d = a.llamar("POST", "/v1/observaciones", obs, evidencia="FATAL ventas no numéricas")
    s.chequear("observación con ventas 'abc' → 422 con detail", c == 422 and d.get("detail"))


# --------------------------------------------------------------------------- #
# 3. Operación diaria
# --------------------------------------------------------------------------- #
def _historico() -> dict[tuple[str, int], list[dict]]:
    por_dia: dict[tuple[str, int], list[dict]] = {}
    with open(DATOS / "historico_ventas.csv", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            por_dia.setdefault((fila["fecha"], int(fila["tienda_id"])), []).append(fila)
    return por_dia


def _costos() -> dict[str, tuple[float, float]]:
    with open(DATOS / "costos.csv", encoding="utf-8") as f:
        return {r["familia_id"]: (float(r["costo_faltante"]), float(r["costo_sobrante"])) for r in csv.DictReader(f)}


DIAS_SIMULADOS = 7
INICIO_SIMULACION = date(2026, 3, 2)  # el histórico termina el 2026-02-28


def _dia_fuente(hist: dict, dia: date, tienda: int) -> list[dict]:
    """Mismo día de la semana un año antes; si no existe (p. ej. tienda 10, abierta en
    2025-03-15), el mismo día de la semana más reciente del histórico."""
    for atras in [364] + [7 * k for k in range(1, 60)]:
        clave = ((dia - timedelta(days=atras)).isoformat(), tienda)
        if clave in hist:
            return hist[clave]
    raise KeyError(f"sin histórico para la tienda {tienda}")


def prueba_operacion(a: Auditoria) -> None:
    s = a.seccion(3, "Operación diaria e idempotencia de observaciones")
    hist, costos = _historico(), _costos()
    rng = random.Random(time.time_ns())
    tiendas = sorted({t for _, t in hist})
    pronosticos: dict[tuple[str, int], dict[str, int]] = {}
    filas_tabla, costo_total, n_pred, fallos_idem, primeras = [], 0.0, 0, 0, []
    for k in range(DIAS_SIMULADOS):
        dia = INICIO_SIMULACION + timedelta(days=k)
        ayer = dia - timedelta(days=1)
        guardados_dia = 0
        for t in tiendas:
            # Observaciones reales simuladas de ayer: mismo día de la semana un año antes, con ruido.
            origen = _dia_fuente(hist, ayer, t)
            obs = {"tienda_id": t, "fecha": ayer.isoformat(), "ventas": [
                {"familia_id": r["familia_id"],
                 "ventas": max(0, round(int(r["ventas"]) * rng.uniform(0.9, 1.1)))} for r in origen]}
            ev = f"Observaciones {ayer} tienda {t} (1er envío)" if k == 0 and t == tiendas[0] else None
            c1, d1 = a.llamar("POST", "/v1/observaciones", obs, evidencia=ev)
            ev2 = f"Observaciones {ayer} tienda {t} (2º envío idéntico)" if ev else None
            c2, d2 = a.llamar("POST", "/v1/observaciones", obs, evidencia=ev2)
            primeras.append(d1.get("registros_guardados") if c1 == 200 else None)
            if not (c1 == 200 and d1.get("registros_guardados", 0) > 0 and c2 == 200 and d2.get("registros_guardados") == 0):
                fallos_idem += 1
                s.notas.append(f"idempotencia {ayer} t{t}: 1º={c1} {d1} 2º={c2} {d2}")
            guardados_dia += d1.get("registros_guardados", 0) if c1 == 200 else 0
            # Costo real de lo que se sugirió ayer para esta tienda
            if (ayer.isoformat(), t) in pronosticos:
                for v in obs["ventas"]:
                    q = pronosticos[(ayer.isoformat(), t)].get(v["familia_id"])
                    if q is not None:
                        cf, cs = costos[v["familia_id"]]
                        costo_total += cf * max(v["ventas"] - q, 0) + cs * max(q - v["ventas"], 0)
            # Pronóstico de hoy (en_promocion del mismo día un año antes)
            plan = _dia_fuente(hist, dia, t)
            pedido = {"tienda_id": t, "fecha": dia.isoformat(),
                      "familias": [{"familia_id": r["familia_id"], "en_promocion": int(r["en_promocion"])} for r in plan]}
            ev = f"Pronóstico {dia} tienda {t}" if k == 0 and t == tiendas[0] else None
            c, d = a.llamar("POST", "/v1/prediccion", pedido, evidencia=ev)
            if c == 200 and isinstance(d.get("version_modelo"), str) and all(
                    isinstance(p["cantidad_sugerida"], int) and p["cantidad_sugerida"] >= 0 for p in d["predicciones"]):
                n_pred += 1
                pronosticos[(dia.isoformat(), t)] = {p["familia_id"]: p["cantidad_sugerida"] for p in d["predicciones"]}
            else:
                s.notas.append(f"pronóstico {dia} t{t}: {c} {_json(d, 200)}")
        filas_tabla.append(f"| {dia} | {ayer} | {guardados_dia} | {len(tiendas)} |")
    total = DIAS_SIMULADOS * len(tiendas)
    s.chequear(f"{total} pares de envíos: 1º registros_guardados > 0 y 2º idéntico → 200 con 0", fallos_idem == 0,
               f"{fallos_idem} fallos")
    s.chequear(f"{total} pronósticos diarios → 200 con version_modelo str y cantidades int >= 0", n_pred == total,
               f"{n_pred}/{total}")
    s.evidencias.insert(0, "| Día pronosticado | Observaciones enviadas de | registros_guardados (1er envío) | tiendas |\n"
                           "|---|---|---|---|\n" + "\n".join(filas_tabla) + "\n\n"
                        f"Costo de negocio real de las cantidades sugeridas en la simulación "
                        f"({len(pronosticos) - len(tiendas)} tienda-días evaluados): **{costo_total:,.2f}**\n")


# --------------------------------------------------------------------------- #
# 4. Reentrenamiento y hot-reload
# --------------------------------------------------------------------------- #
def _inicio_contenedor_api() -> str:
    cid = compose("ps", "-q", "api").splitlines()[0]
    r = subprocess.run(["docker", "inspect", "-f", "{{.State.StartedAt}}|{{.RestartCount}}", cid],
                       capture_output=True, text=True)
    return r.stdout.strip()


def _mlflow_alias(alias: str) -> str | None:
    r = httpx.get(f"{MLFLOW}/api/2.0/mlflow/registered-models/alias", params={"name": MODELO, "alias": alias}, timeout=10)
    return r.json()["model_version"]["version"] if r.status_code == 200 else None


def _mlflow_fijar_alias(alias: str, version: str) -> None:
    httpx.post(f"{MLFLOW}/api/2.0/mlflow/registered-models/alias",
               json={"name": MODELO, "alias": alias, "version": version}, timeout=10).raise_for_status()


def _esperar_version(a: Auditoria, version: str, limite: float = 120):
    def ok():
        c, m = a.llamar("GET", "/modelo")
        return c == 200 and m.get("version") == version
    return esperar(ok, limite, 2)


def prueba_reentrenamiento(a: Auditoria) -> None:
    s = a.seccion(4, "Ciclo de reentrenamiento y hot-reload")
    inicio_api = _inicio_contenedor_api()
    _, antes = a.llamar("GET", "/modelo", evidencia="Modelo antes del reentrenamiento")
    c, d = a.llamar("POST", "/admin/reentrenar", evidencia="Disparo del reentrenamiento")
    s.chequear("POST /admin/reentrenar → 202 con id (texto)", c == 202 and isinstance(d.get("id"), str) and d["id"],
               _json(d))
    if c != 202:
        return
    id_ = d["id"]
    vistos = []

    def terminado():
        c, e = a.llamar("GET", f"/admin/reentrenar/{id_}")
        if c == 200 and (not vistos or vistos[-1] != e.get("estado")):
            vistos.append(e.get("estado"))
        return e if c == 200 and e.get("estado") != "en_curso" else None

    final, seg = esperar(terminado, 900, 5)
    a.llamar("GET", f"/admin/reentrenar/{id_}", evidencia=f"Estado final de la ejecución ({seg:.0f} s)")
    s.chequear("el estado pasa de 'en_curso' a 'exitoso'", vistos[:1] == ["en_curso"] and final and final.get("estado") == "exitoso",
               f"secuencia {vistos} final {final}")
    s.chequear("incluye promovido (bool), version (str) y motivo (str)",
               bool(final) and isinstance(final.get("promovido"), bool) and isinstance(final.get("version"), str)
               and isinstance(final.get("motivo"), str) and final["motivo"], _json(final))
    c404, d404 = a.llamar("GET", "/admin/reentrenar/id-que-no-existe", evidencia="Id inexistente")
    s.chequear("GET /admin/reentrenar/{id inexistente} → 404", c404 == 404, _json(d404))
    if not final or final.get("estado") != "exitoso":
        return

    if final["promovido"]:
        nueva = final["version"]
        listo, seg = _esperar_version(a, nueva)
        s.chequear(f"GET /modelo usa la versión promovida v{nueva} en < 2 min", bool(listo), f"{seg:.0f} s")
        c, p = a.llamar("POST", "/v1/prediccion", leer(DATOS / "ejemplos" / "prediccion_valida.json"),
                        evidencia="Predicción con el modelo promovido")
        s.chequear("POST /v1/prediccion responde con version_modelo de la nueva versión", c == 200 and p.get("version_modelo") == nueva)
        s.notas.append(f"El reentrenamiento promovió v{nueva}; la API la cargó en {seg:.0f} s sin reinicio.")
    else:
        # El candidato no ganó la compuerta: se verifica el mecanismo de hot-reload con una
        # promoción controlada en MLflow (moviendo @champion al challenger y luego restaurándolo).
        vigente, candidata = antes.get("version"), _mlflow_alias("challenger")
        s.notas.append(f"La compuerta no promovió (motivo: {final['motivo']}). Se verificó el hot-reload moviendo "
                       f"@champion al challenger v{candidata} directamente en MLflow y restaurando v{vigente}.")
        if candidata and candidata != vigente:
            _mlflow_fijar_alias("champion", candidata)
            listo, seg = _esperar_version(a, candidata)
            s.chequear(f"hot-reload: GET /modelo pasa a v{candidata} en < 2 min", bool(listo), f"{seg:.0f} s")
            c, p = a.llamar("POST", "/v1/prediccion", leer(DATOS / "ejemplos" / "prediccion_valida.json"),
                            evidencia=f"Predicción tras la promoción controlada a v{candidata}")
            s.chequear("POST /v1/prediccion usa la nueva versión", c == 200 and p.get("version_modelo") == candidata)
            _mlflow_fijar_alias("champion", vigente)
            listo, seg = _esperar_version(a, vigente)
            s.chequear(f"hot-reload de vuelta a v{vigente} en < 2 min", bool(listo), f"{seg:.0f} s")
    s.chequear("el contenedor api no se reinició", _inicio_contenedor_api() == inicio_api, inicio_api)
    _, despues = a.llamar("GET", "/modelo", evidencia="Modelo al terminar la sección")


# --------------------------------------------------------------------------- #
# 5. Caída de MLflow
# --------------------------------------------------------------------------- #
def prueba_caida_mlflow(a: Auditoria) -> None:
    s = a.seccion(5, "Caída de MLflow")
    pedido = leer(DATOS / "ejemplos" / "prediccion_valida.json")
    compose("stop", "mlflow")
    t0 = time.time()

    def degradado():
        c, d = a.llamar("GET", "/health")
        return (c, d) if c == 200 and d.get("estado") == "degradado" else None

    res, seg = esperar(degradado, 30, 2)
    a.llamar("GET", "/health", evidencia=f"Salud con MLflow detenido ({time.time() - t0:.0f} s)")
    s.chequear("GET /health → 200 con estado 'degradado' y motivo en <= 30 s",
               bool(res) and bool(res[1].get("motivo")), f"{seg:.0f} s, {res}")
    c, p = a.llamar("POST", "/v1/prediccion", pedido, evidencia="Predicción con MLflow detenido")
    s.chequear("POST /v1/prediccion sigue respondiendo 200 con el modelo en memoria", c == 200)
    if c == 200:
        validar_prediccion(s, p, "predicción con MLflow detenido")
    compose("start", "mlflow")
    t1 = time.time()

    def recuperado():
        c, d = a.llamar("GET", "/health")
        return d if c == 200 and d.get("estado") == "ok" else None

    res, seg = esperar(recuperado, 120, 3)
    a.llamar("GET", "/health", evidencia=f"Salud tras reiniciar MLflow ({time.time() - t1:.0f} s)")
    s.chequear("GET /health vuelve a 'ok' en < 2 min", bool(res), f"{seg:.0f} s")


# --------------------------------------------------------------------------- #
# 6. Persistencia
# --------------------------------------------------------------------------- #
def _conteos() -> dict[str, str]:
    return {
        "observaciones": psql("select count(*) from ventas where origen='observacion'"),
        "historico": psql("select count(*) from ventas where origen='historico'"),
        "predicciones": psql("select count(*) from predicciones"),
        "solicitudes": psql("select count(*) from solicitudes"),
        "ejecuciones": psql("select count(*) from ejecuciones_reentrenamiento"),
    }


def _versiones_mlflow() -> list[str]:
    r = httpx.get(f"{MLFLOW}/api/2.0/mlflow/model-versions/search", params={"filter": f"name='{MODELO}'"}, timeout=10)
    return sorted((v["version"] for v in r.json().get("model_versions", [])), key=int)


def prueba_persistencia(a: Auditoria) -> None:
    s = a.seccion(6, "Persistencia de volúmenes (docker compose down / up -d)")
    _, modelo_antes = a.llamar("GET", "/modelo", evidencia="Modelo antes de down")
    conteos_antes, versiones_antes = _conteos(), _versiones_mlflow()
    s.evidencias.append(f"Antes de `down`:\n```json\n{_json({'conteos': conteos_antes, 'versiones_mlflow': versiones_antes})}\n```\n")
    salida_down = compose("down", timeout=300)
    t0 = time.time()
    salida_up = compose("up", "-d", timeout=600)
    s.notas.append(f"`docker compose down` y `up -d` ejecutados; up tardó {time.time() - t0:.0f} s.")

    def sano():
        c, d = a.llamar("GET", "/health")
        return d if c == 200 and d.get("estado") == "ok" else None

    res, seg = esperar(sano, 240, 5)
    s.chequear("tras up -d, GET /health vuelve a 200 'ok'", bool(res), f"{seg:.0f} s")
    conteos_despues, versiones_despues = _conteos(), _versiones_mlflow()
    _, modelo_despues = a.llamar("GET", "/modelo", evidencia="Modelo después de up")
    s.evidencias.append(f"Después de `up -d`:\n```json\n{_json({'conteos': conteos_despues, 'versiones_mlflow': versiones_despues})}\n```\n")
    for clave in ("observaciones", "historico", "predicciones", "solicitudes", "ejecuciones"):
        s.chequear(f"se conservan las filas de {clave} ({conteos_antes[clave]})",
                   conteos_antes[clave] == conteos_despues[clave] and conteos_antes[clave] != "",
                   f"{conteos_antes[clave]} → {conteos_despues[clave]}")
    s.chequear("se conservan las versiones del modelo en MLflow sin entrenar de nuevo",
               versiones_antes == versiones_despues and versiones_antes, f"{versiones_antes} → {versiones_despues}")
    s.chequear("GET /modelo mantiene la misma versión @champion", modelo_antes == modelo_despues,
               f"{modelo_antes} → {modelo_despues}")
    logs = compose("logs", "bootstrap")
    s.chequear("el bootstrap detectó datos y modelo existentes (no recargó ni reentrenó)",
               "no se reentrena" in logs and "ya cargado" in logs, logs[-500:])
    lineas = [l for l in logs.splitlines() if "novamercado.bootstrap" in l][-6:]
    s.evidencias.append("Log del bootstrap tras `up -d`:\n```\n" + "\n".join(lineas) + "\n```\n")
    obs = leer(DATOS / "ejemplos" / "observacion_valida.json")
    c, d = a.llamar("POST", "/v1/observaciones", obs, evidencia="Reenvío de una observación ya guardada tras el reinicio")
    s.chequear("reenviar una observación ya guardada tras el reinicio → registros_guardados 0",
               c == 200 and d.get("registros_guardados") == 0)


# --------------------------------------------------------------------------- #
# Reporte
# --------------------------------------------------------------------------- #
def escribir_reporte(a: Auditoria) -> None:
    total = sum(len(s.chequeos) for s in a.secciones)
    ok = sum(c[1] for s in a.secciones for c in s.chequeos)
    lineas = [
        "# Reporte de auditoría — NovaMercado",
        "",
        f"- Ejecutada: {a.inicio:%Y-%m-%d %H:%M:%S} (duración {(datetime.now() - a.inicio).seconds // 60} min)",
        f"- API: `{a.url}` · MLflow: `{MLFLOW}`",
        f"- Resultado: **{ok}/{total} chequeos aprobados** — "
        + ("**TODAS LAS PRUEBAS PASAN**" if ok == total else "**HAY FALLAS**"),
        "",
        "| # | Prueba | Resultado | Chequeos |",
        "|---|---|---|---|",
    ]
    for s in a.secciones:
        n_ok = sum(c[1] for c in s.chequeos)
        lineas.append(f"| {s.numero} | {s.titulo} | {'✅ pasa' if s.ok else '❌ falla'} | {n_ok}/{len(s.chequeos)} |")
    for s in a.secciones:
        lineas += ["", f"## {s.numero}. {s.titulo}", ""]
        lineas += [f"- {'✅' if c[1] else '❌'} {c[0]}" + (f" — `{c[2][:200]}`" if not c[1] and c[2] else "")
                   for c in s.chequeos]
        if s.notas:
            lineas += ["", "Notas:", *[f"- {n}" for n in s.notas[:30]]]
        if s.evidencias:
            lineas += ["", "<details><summary>Evidencia (JSON reales)</summary>", ""]
            lineas += [e + "\n" for e in s.evidencias]
            lineas += ["</details>"]
    REPORTE.parent.mkdir(parents=True, exist_ok=True)
    REPORTE.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print(f"\nReporte: {REPORTE} — {ok}/{total} chequeos aprobados")


PRUEBAS = {1: prueba_salud, 2: prueba_contrato, 3: prueba_operacion, 4: prueba_reentrenamiento,
           5: prueba_caida_mlflow, 6: prueba_persistencia}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--secciones", default="1,2,3,4,5,6")
    args = p.parse_args()
    a = Auditoria(args.url)
    for n in (int(x) for x in args.secciones.split(",")):
        try:
            PRUEBAS[n](a)
        except Exception as e:  # una sección rota no debe impedir el reporte
            s = a.actual if a.actual and a.actual.numero == n else a.seccion(n, f"Prueba {n}")
            s.chequear(f"la prueba {n} terminó sin excepciones", False, f"{type(e).__name__}: {e}")
    escribir_reporte(a)
    return 0 if all(s.ok for s in a.secciones) else 1


if __name__ == "__main__":
    sys.exit(main())
