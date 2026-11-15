"""Pruebas del contrato, el motor de limpieza y la persistencia (sin MLflow ni Docker)."""

from __future__ import annotations

import inspect
import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from api import esquemas
from api.esquemas import (
    Calidad,
    RespuestaObservaciones,
    SolicitudObservaciones,
    SolicitudPrediccion,
    cuerpo_error,
    validar_observaciones,
    validar_prediccion,
)
from novamercado import limpieza
from novamercado.db import (
    cargar_catalogos_en_bd,
    cargar_historico,
    correcciones,
    feriados,
    metadata,
    predicciones,
    solicitudes,
    tiendas,
)
from novamercado.limpieza import ErrorContrato, limpiar_observaciones, limpiar_prediccion
from sqlalchemy import func, inspect as sa_inspect, select

from tests.conftest import DIR_DATOS, DIR_EJEMPLOS, DIR_ERRORES, leer_json


# --------------------------------------------------------------------------- #
# Ayudas
# --------------------------------------------------------------------------- #
def es_observacion(payload: dict) -> bool:
    return "ventas" in payload


def validar(payload: dict, cat):
    fn = validar_observaciones if es_observacion(payload) else validar_prediccion
    return fn(payload, cat)


def rechazo(fn, payload, cat) -> list[dict]:
    with pytest.raises(ErrorContrato) as exc:
        fn(payload, cat)
    errores = exc.value.errores
    assert errores, "un rechazo debe traer al menos un detalle"
    for e in errores:
        assert set(e) == {"campo", "accion", "detalle"}
        assert e["accion"] == "rechazar" and e["detalle"]
    return errores


def acciones(calidad: Calidad) -> list[tuple[str, str]]:
    return [(o.campo, o.accion) for o in calidad.observaciones]


def assert_formato_calidad(calidad: dict) -> None:
    """Estructura exacta del bloque de calidad."""
    assert set(calidad) == {"estado", "observaciones"}
    assert calidad["estado"] in {"ok", "corregido", "advertencia"}
    assert isinstance(calidad["observaciones"], list)
    for o in calidad["observaciones"]:
        assert set(o) == {"campo", "accion", "detalle"}
        assert o["accion"] in {"reparar", "advertir"}
    if calidad["estado"] == "ok":
        assert calidad["observaciones"] == []
    else:
        assert calidad["observaciones"]
    tiene_adv = any(o["accion"] == "advertir" for o in calidad["observaciones"])
    assert (calidad["estado"] == "advertencia") == tiene_adv


def con_familia(payload: dict, i: int, **campos) -> dict:
    payload["familias"][i].update(campos)
    return payload


# --------------------------------------------------------------------------- #
# 1. Archivos de ejemplo (data/raw/ejemplos y data/raw/errores)
# --------------------------------------------------------------------------- #
ARCHIVOS_VALIDOS = sorted(DIR_EJEMPLOS.glob("*.json")) + sorted(DIR_DATOS.glob("*.json"))


@pytest.mark.parametrize("ruta", ARCHIVOS_VALIDOS, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_ejemplos_validos_estado_ok(ruta: Path, cat):
    solicitud, calidad = validar(leer_json(ruta), cat)
    assert calidad.estado == "ok"
    assert calidad.observaciones == []
    assert calidad.model_dump() == {"estado": "ok", "observaciones": []}
    assert solicitud.tienda_id == 5 and solicitud.fecha == date(2025, 11, 17)


# Expectativa por archivo de errores: (resultado, verificación adicional)
def _e01(s, q):
    assert s.tienda_id == 5 and acciones(q) == [("tienda_id", "reparar")]


def _e02(s, q):
    ids = [f.familia_id for f in s.familias]
    assert ids[5] == "frutas_verduras" and ids[6] == "lacteos"
    assert acciones(q) == [("familias[5].familia_id", "reparar"), ("familias[6].familia_id", "reparar")]


def _e03(s, q):
    promo = {f.familia_id: f.en_promocion for f in s.familias}
    assert promo["bebidas"] == 8 and promo["snacks"] == 9
    assert all(type(f.en_promocion) is int for f in s.familias)


def _e04(s, q):
    assert s.fecha == date(2025, 11, 17) and acciones(q) == [("fecha", "reparar")]


def _e05(s, q):
    assert len(s.familias) == 10
    (obs,) = q.observaciones
    assert obs.accion == "advertir" and "bebe" in obs.detalle and "mascotas" in obs.detalle


def _e06(s, q):
    abarrotes = [f for f in s.familias if f.familia_id == "abarrotes"]
    assert len(abarrotes) == 1 and abarrotes[0].en_promocion == 3  # se conserva la última
    assert len(s.familias) == 12
    assert q.observaciones[0].accion == "advertir" and "abarrotes" in q.observaciones[0].detalle


def _e07(s, q):
    assert s.tienda_id == 5 and acciones(q) == [("tienda_id", "reparar")]


def _e09(s, q):
    assert q.estado == "ok"  # la repetición se resuelve en la BD (ver pruebas de idempotencia)


def _e10(s, q):
    v = {x.familia_id: x.ventas for x in s.ventas}
    assert v["bebe"] == 50 and v["bebidas"] == 1292


ESPERADO_ERRORES = {
    "E01_tienda_texto.json": ("corregido", _e01),
    "E02_familia_otra_forma.json": ("corregido", _e02),
    "E03_promocion_texto.json": ("corregido", _e03),
    "E04_fecha_formato.json": ("corregido", _e04),
    "E05_faltan_familias.json": ("advertencia", _e05),
    "E06_familia_repetida.json": ("advertencia", _e06),
    "E07_campo_renombrado.json": ("corregido", _e07),
    "E08_ventas_negativas.json": ("rechazo", "ventas[5].ventas"),
    "E09_envio_repetido.json": ("ok", _e09),
    "E10_numero_formato.json": ("corregido", _e10),
}


def test_todos_los_archivos_de_errores_tienen_expectativa():
    assert {p.name for p in DIR_ERRORES.glob("*.json")} == set(ESPERADO_ERRORES)


@pytest.mark.parametrize("nombre", sorted(ESPERADO_ERRORES))
def test_archivos_de_errores(nombre: str, cat):
    payload = leer_json(DIR_ERRORES / nombre)
    esperado, verificar = ESPERADO_ERRORES[nombre]
    fn = validar_observaciones if es_observacion(payload) else validar_prediccion
    if esperado == "rechazo":
        errores = rechazo(fn, payload, cat)
        assert [e["campo"] for e in errores] == [verificar]
        return
    solicitud, calidad = fn(payload, cat)
    assert calidad.estado == esperado
    assert_formato_calidad(calidad.model_dump())
    verificar(solicitud, calidad)


def test_e08_detalle_menciona_valor_negativo(cat):
    (error,) = rechazo(validar_observaciones, leer_json(DIR_ERRORES / "E08_ventas_negativas.json"), cat)
    assert "-4" in error["detalle"] and "negativo" in error["detalle"]


# --------------------------------------------------------------------------- #
# 2. tienda_id
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("valor", ["05", "5", " 5 ", "T5", "T05", "t05", "tienda_5", "Tienda 5", "TIENDA-05",
                                   "store_5", "tda#5", 5.0, "5.0", "+5"])
def test_tienda_reparable(valor, pred_valida, cat):
    pred_valida["tienda_id"] = valor
    s, q = validar_prediccion(pred_valida, cat)
    assert s.tienda_id == 5
    assert acciones(q) == [("tienda_id", "reparar")] and q.estado == "corregido"


@pytest.mark.parametrize("valor, fragmento", [
    (99, "no existe"), ("T99", "no existe"), (11, "no existe"), (-1, "positivo"), ("-5", "positivo"),
    (0, "positivo"), ("abc", "no se reconoce"), ("5a", "no se reconoce"), (5.5, "entero"),
    (True, "booleano"), (None, "nulo"), ([5], "tipo no admitido"), ("", "no se reconoce"),
])
def test_tienda_rechazada(valor, fragmento, pred_valida, cat):
    pred_valida["tienda_id"] = valor
    (e,) = rechazo(validar_prediccion, pred_valida, cat)
    assert e["campo"] == "tienda_id" and fragmento in e["detalle"]


def test_tienda_antes_de_su_apertura_se_rechaza(pred_valida, cat):
    pred_valida.update(tienda_id=10, fecha="2025-01-10")  # la tienda 10 abrió el 2025-03-15
    (e,) = rechazo(validar_prediccion, pred_valida, cat)
    assert e["campo"] == "fecha" and "2025-03-15" in e["detalle"]


@pytest.mark.parametrize("alias", ["tienda", "store_id", "id_tienda", "Tienda_ID", "tiendaId"])
def test_alias_de_tienda_se_renombra(alias, pred_valida, cat):
    pred_valida[alias] = pred_valida.pop("tienda_id")
    s, q = validar_prediccion(pred_valida, cat)
    assert s.tienda_id == 5 and acciones(q) == [("tienda_id", "reparar")]


def test_alias_contradictorio_se_rechaza(pred_valida, cat):
    pred_valida["tienda"] = 4
    (e,) = rechazo(validar_prediccion, pred_valida, cat)
    assert e["campo"] == "tienda_id" and "contradictorios" in e["detalle"]


def test_alias_duplicado_con_mismo_valor_se_repara(pred_valida, cat):
    pred_valida["tienda"] = 5
    s, q = validar_prediccion(pred_valida, cat)
    assert s.tienda_id == 5 and q.estado == "corregido"


# --------------------------------------------------------------------------- #
# 3. fecha
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("valor", [
    "17/11/2025", "17-11-2025", "17.11.2025", "2025/11/17", "2025.11.17", "2025-11-17T00:00:00",
    "2025-11-17T13:45:10Z", "2025-11-17 08:00", "2025-11-17T00:00:00-06:00", "2025-11-17T00:00:00.000+00:00",
    "20251117", " 2025-11-17 ", "11/17/2025", "2025-11-17t00:00:00",
])
def test_fecha_reparable(valor, pred_valida, cat):
    pred_valida["fecha"] = valor
    s, q = validar_prediccion(pred_valida, cat)
    assert s.fecha == date(2025, 11, 17)
    assert acciones(q) == [("fecha", "reparar")]


def test_fecha_ambigua_dd_mm_se_advierte(pred_valida, cat):
    pred_valida["fecha"] = "05/11/2025"
    s, q = validar_prediccion(pred_valida, cat)
    assert s.fecha == date(2025, 11, 5)
    assert acciones(q) == [("fecha", "advertir")] and q.estado == "advertencia"


def test_fecha_con_dia_y_mes_iguales_no_es_ambigua(pred_valida, cat):
    pred_valida["fecha"] = "11/11/2025"
    s, q = validar_prediccion(pred_valida, cat)
    assert s.fecha == date(2025, 11, 11) and q.estado == "corregido"


@pytest.mark.parametrize("valor, fragmento", [
    ("2025-02-30", "calendario"), ("2025-02-29", "calendario"), ("31/04/2025", "calendario"),
    ("2025-13-01", "calendario"), ("32/13/2025", "calendario"), ("00/01/2025", "calendario"),
    ("mañana", "no reconocido"), ("", "no reconocido"), ("17/11/25", "no reconocido"),
    ("2025-11-17T25:00:00", "hora inválida"), (None, "nula"), (20251117, "texto"),
    ("1999-12-31", "fuera del rango"), ("2101-01-01", "fuera del rango"),
])
def test_fecha_rechazada(valor, fragmento, pred_valida, cat):
    pred_valida["fecha"] = valor
    (e,) = rechazo(validar_prediccion, pred_valida, cat)
    assert e["campo"] == "fecha" and fragmento in e["detalle"]


def test_fecha_bisiesta_valida(pred_valida, cat):
    pred_valida["fecha"] = "29/02/2028"
    s, _ = validar_prediccion(pred_valida, cat)
    assert s.fecha == date(2028, 2, 29)


def test_horizonte_lejano_se_advierte_sin_usar_el_reloj(pred_valida, cat):
    pred_valida["fecha"] = "2030-06-01"  # >366 días después del último dato del histórico (2026-02-28)
    s, q = validar_prediccion(pred_valida, cat)
    assert acciones(q) == [("fecha", "advertir")] and "2026-02-28" in q.observaciones[0].detalle


def test_fecha_referencia_simulada_controla_el_horizonte(pred_valida, cat):
    pred_valida["fecha"] = "2030-06-01"
    _, q = validar_prediccion(pred_valida, cat, fecha_referencia=date(2030, 5, 1))
    assert q.estado == "ok"


def test_fechas_futuras_respecto_al_reloj_real_se_aceptan(pred_valida, cat):
    # El servicio usa fechas simuladas: una fecha posterior al día real no es un error.
    pred_valida["fecha"] = "2026-12-20"
    s, q = validar_prediccion(pred_valida, cat)
    assert s.fecha == date(2026, 12, 20) and q.estado == "ok"


@pytest.mark.parametrize("modulo", [limpieza, esquemas])
def test_no_se_consulta_el_reloj_del_sistema(modulo):
    codigo = inspect.getsource(modulo)
    for prohibido in ("today(", "now(", "time.time(", "utcnow("):
        assert prohibido not in codigo, f"{modulo.__name__} usa {prohibido}"


# --------------------------------------------------------------------------- #
# 4. familia_id
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("valor, esperado", [
    ("LÁCTEOS", "lacteos"), ("lacteos ", "lacteos"), ("Lácteos", "lacteos"),
    ("Frutas y Verduras", "frutas_verduras"), ("frutas-verduras", "frutas_verduras"),
    ("FRUTAS_VERDURAS", "frutas_verduras"), ("frutas & verduras", "frutas_verduras"),
    ("frutasverduras", "frutas_verduras"), ("Cuidado Personal", "cuidado_personal"),
    ("cuidado-personal", "cuidado_personal"), ("Panadería", "panaderia"), ("Bebé", "bebe"),
    ("Snacks y dulces", "snacks"), ("SNACKS", "snacks"),
    # errores tipográficos leves
    ("abarotes", "abarrotes"), ("lacteso", "lacteos"), ("bebidaz", "bebidas"), ("mascota", "mascotas"),
    ("limpiza", "limpieza"), ("panaderia_", "panaderia"), ("carne", "carnes"), ("Licroes", "licores"),
])
def test_familia_reparable(valor, esperado, pred_valida, cat):
    original = pred_valida["familias"][0]["familia_id"]
    pred_valida["familias"] = [f for f in pred_valida["familias"] if f["familia_id"] != esperado]
    pred_valida["familias"].append({"familia_id": valor, "en_promocion": 0})
    s, q = validar_prediccion(pred_valida, cat)
    assert s.familias[-1].familia_id == esperado
    assert ("familias[11].familia_id", "reparar") in acciones(q)
    assert original  # sanity


@pytest.mark.parametrize("valor, fragmento", [
    ("electrodomesticos", "no corresponde"), ("xyz", "no corresponde"), ("pan", "no corresponde"),
    ("bebida alcoholica", "no corresponde"), ("", "vacío"), ("   ", "vacío"), (None, "nulo"),
    (123, "texto"), (["lacteos"], "texto"),
])
def test_familia_rechazada(valor, fragmento, pred_valida, cat):
    con_familia(pred_valida, 3, familia_id=valor)
    (e,) = rechazo(validar_prediccion, pred_valida, cat)
    assert e["campo"] == "familias[3].familia_id" and fragmento in e["detalle"]


def test_familia_sin_campo_familia_id_se_rechaza(pred_valida, cat):
    del pred_valida["familias"][2]["familia_id"]
    (e,) = rechazo(validar_prediccion, pred_valida, cat)
    assert e["campo"] == "familias[2].familia_id"


def test_alias_de_campos_en_elementos(pred_valida, cat):
    pred_valida["familias"][0] = {"Familia": "abarrotes", "promocion": "2"}
    s, q = validar_prediccion(pred_valida, cat)
    assert s.familias[0].familia_id == "abarrotes" and s.familias[0].en_promocion == 2
    assert q.estado == "corregido"


# --------------------------------------------------------------------------- #
# 5. Cantidades (en_promocion / ventas)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("valor, esperado", [
    ("8", 8), (8.0, 8), ("8.0", 8), (" 3 ", 3), ("3,0", 3), ("+2", 2),
])
def test_promocion_reparable(valor, esperado, pred_valida, cat):
    con_familia(pred_valida, 0, en_promocion=valor)
    s, q = validar_prediccion(pred_valida, cat)
    assert s.familias[0].en_promocion == esperado and type(s.familias[0].en_promocion) is int
    assert acciones(q) == [("familias[0].en_promocion", "reparar")]


@pytest.mark.parametrize("modo", ["nulo", "ausente"])
def test_promocion_nula_o_ausente_asume_cero_y_advierte(modo, pred_valida, cat):
    if modo == "nulo":
        con_familia(pred_valida, 4, en_promocion=None)
    else:
        del pred_valida["familias"][4]["en_promocion"]
    s, q = validar_prediccion(pred_valida, cat)
    assert s.familias[4].en_promocion == 0
    assert acciones(q) == [("familias[4].en_promocion", "advertir")] and q.estado == "advertencia"
    assert "0" in q.observaciones[0].detalle


@pytest.mark.parametrize("valor, fragmento", [
    (-1, "negativo"), ("-3", "negativo"), (2.5, "entero"), ("2,5", "entero"), ("abc", "reconocible"),
    (True, "booleano"), (float("nan"), "finito"), ("", "vacío"), ({"v": 1}, "tipo no admitido"),
    (500, "inverosímil"),
])
def test_promocion_rechazada(valor, fragmento, pred_valida, cat):
    con_familia(pred_valida, 0, en_promocion=valor)
    (e,) = rechazo(validar_prediccion, pred_valida, cat)
    assert e["campo"] == "familias[0].en_promocion" and fragmento in e["detalle"]


def test_promocion_extrema_pero_plausible_se_advierte(pred_valida, cat):
    con_familia(pred_valida, 0, en_promocion=cat.max_promo_familia["abarrotes"] + 5)
    s, q = validar_prediccion(pred_valida, cat)
    assert acciones(q) == [("familias[0].en_promocion", "advertir")] and "extremo" in q.observaciones[0].detalle


@pytest.mark.parametrize("valor, esperado", [
    ("994", 994), ("994.0", 994), (994.0, 994), ("1,234", 1234), ("1.234", 1234), ("812,0", 812),
    ("1,234.0", 1234), ("1.234,0", 1234), ("1 234", 1234), ("1,000", 1000), ("0", 0),
])
def test_ventas_reparables(valor, esperado, obs_valida, cat):
    obs_valida["ventas"][2]["ventas"] = valor  # bebidas (máx. histórico alto)
    s, q = validar_observaciones(obs_valida, cat)
    assert s.ventas[2].ventas == esperado and type(s.ventas[2].ventas) is int
    assert ("ventas[2].ventas", "reparar") in acciones(q)


@pytest.mark.parametrize("valor, fragmento", [
    (-4, "negativo"), ("-4", "negativo"), ("812,5", "entero"), (12.3, "entero"), ("doce", "reconocible"),
    ("994.000", "ambiguo"), (None, "nulo"), (False, "booleano"), ("1e3", "reconocible"),
    (10_000_000, "inverosímil"),
])
def test_ventas_rechazadas(valor, fragmento, obs_valida, cat):
    obs_valida["ventas"][2]["ventas"] = valor
    (e,) = rechazo(validar_observaciones, obs_valida, cat)
    assert e["campo"] == "ventas[2].ventas" and fragmento in e["detalle"]


def test_ventas_ausentes_se_rechazan(obs_valida, cat):
    del obs_valida["ventas"][0]["ventas"]
    (e,) = rechazo(validar_observaciones, obs_valida, cat)
    assert e["campo"] == "ventas[0].ventas"


def test_ventas_extremas_pero_plausibles_se_advierten(obs_valida, cat):
    maximo = cat.max_ventas[(5, "abarrotes")]
    obs_valida["ventas"][0]["ventas"] = maximo * 2
    s, q = validar_observaciones(obs_valida, cat)
    assert s.ventas[0].ventas == maximo * 2
    assert acciones(q) == [("ventas[0].ventas", "advertir")]


def test_todas_las_ventas_en_cero_se_advierte(obs_valida, cat):
    for v in obs_valida["ventas"]:
        v["ventas"] = 0
    _, q = validar_observaciones(obs_valida, cat)
    assert acciones(q) == [("ventas", "advertir")]


def test_observacion_acepta_en_promocion_opcional(obs_valida, cat):
    obs_valida["ventas"][0]["en_promocion"] = "2"
    s, q = validar_observaciones(obs_valida, cat)
    assert s.ventas[0].en_promocion == 2 and s.ventas[1].en_promocion is None
    assert acciones(q) == [("ventas[0].en_promocion", "reparar")]


# --------------------------------------------------------------------------- #
# 6. Listas, duplicados, faltantes y estructura
# --------------------------------------------------------------------------- #
def test_duplicado_identico_se_consolida_como_reparacion(pred_valida, cat):
    pred_valida["familias"].append({"familia_id": "bebidas", "en_promocion": 8})
    s, q = validar_prediccion(pred_valida, cat)
    assert len(s.familias) == 12 and acciones(q) == [("familias", "reparar")]


def test_duplicado_por_normalizacion_con_valores_distintos(pred_valida, cat):
    pred_valida["familias"].append({"familia_id": "LÁCTEOS", "en_promocion": 4})
    s, q = validar_prediccion(pred_valida, cat)
    lacteos = [f for f in s.familias if f.familia_id == "lacteos"]
    assert lacteos[0].en_promocion == 4 and len(s.familias) == 12
    assert ("familias", "advertir") in acciones(q)


def test_observacion_duplicada_conserva_la_ultima(obs_valida, cat):
    obs_valida["ventas"].append({"familia_id": "abarrotes", "ventas": 1000})
    s, q = validar_observaciones(obs_valida, cat)
    assert {v.familia_id: v.ventas for v in s.ventas}["abarrotes"] == 1000
    assert q.estado == "advertencia"


def test_observacion_con_familias_faltantes_se_advierte(obs_valida, cat):
    obs_valida["ventas"] = obs_valida["ventas"][:3]
    s, q = validar_observaciones(obs_valida, cat)
    assert len(s.ventas) == 3 and acciones(q) == [("ventas", "advertir")]


@pytest.mark.parametrize("fn, clave", [(validar_prediccion, "familias"), (validar_observaciones, "ventas")])
@pytest.mark.parametrize("valor, fragmento", [([], "vacía"), (None, "lista"), ("abarrotes", "lista"),
                                              ({"familia_id": "abarrotes"}, "lista")])
def test_lista_invalida_se_rechaza(fn, clave, valor, fragmento, pred_valida, obs_valida, cat):
    payload = pred_valida if clave == "familias" else obs_valida
    payload[clave] = valor
    (e,) = rechazo(fn, payload, cat)
    assert e["campo"] == clave and fragmento in e["detalle"]


def test_lista_demasiado_larga_se_rechaza(pred_valida, cat):
    pred_valida["familias"] = pred_valida["familias"] * 10
    (e,) = rechazo(validar_prediccion, pred_valida, cat)
    assert "máximo" in e["detalle"]


def test_elemento_que_no_es_objeto_se_rechaza(pred_valida, cat):
    pred_valida["familias"][1] = "bebe"
    (e,) = rechazo(validar_prediccion, pred_valida, cat)
    assert e["campo"] == "familias[1]"


@pytest.mark.parametrize("campo", ["tienda_id", "fecha", "familias"])
def test_campo_obligatorio_ausente_se_rechaza(campo, pred_valida, cat):
    del pred_valida[campo]
    errores = rechazo(validar_prediccion, pred_valida, cat)
    assert any(e["campo"] == campo and "falta" in e["detalle"] for e in errores)


@pytest.mark.parametrize("cuerpo", [[], "texto", 5, None])
def test_cuerpo_que_no_es_objeto_se_rechaza(cuerpo, cat):
    (e,) = rechazo(validar_prediccion, cuerpo, cat)
    assert e["campo"] == "cuerpo"


def test_campo_desconocido_se_ignora_con_advertencia(pred_valida, cat):
    pred_valida["canal"] = "pos"
    pred_valida["familias"][0]["comentario"] = "x"
    s, q = validar_prediccion(pred_valida, cat)
    assert acciones(q) == [("canal", "advertir"), ("familias[0].comentario", "advertir")]
    assert "canal" not in s.model_dump()


def test_se_reportan_todos_los_errores_a_la_vez(pred_valida, cat):
    pred_valida.update(tienda_id=99, fecha="2025-02-30")
    con_familia(pred_valida, 0, familia_id="juguetes")
    con_familia(pred_valida, 1, en_promocion=-2)
    campos = {e["campo"] for e in rechazo(validar_prediccion, pred_valida, cat)}
    assert campos == {"tienda_id", "fecha", "familias[0].familia_id", "familias[1].en_promocion"}


def test_varias_reparaciones_y_una_advertencia(pred_valida, cat):
    pred_valida.update(tienda="T05", fecha="17/11/2025")
    del pred_valida["tienda_id"]
    con_familia(pred_valida, 6, familia_id="LÁCTEOS", en_promocion="1")
    con_familia(pred_valida, 7, en_promocion=None)
    s, q = validar_prediccion(pred_valida, cat)
    assert q.estado == "advertencia"
    assert s.model_dump(mode="json")["tienda_id"] == 5
    assert_formato_calidad(q.model_dump())


def test_limpieza_no_modifica_el_payload_original(cat):
    payload = leer_json(DIR_ERRORES / "E02_familia_otra_forma.json")
    copia = json.loads(json.dumps(payload))
    limpiar_prediccion(payload, cat)
    assert payload == copia


def test_resultado_es_json_canonico(cat):
    r = limpiar_observaciones(leer_json(DIR_ERRORES / "E10_numero_formato.json"), cat)
    assert r.datos["fecha"] == "2025-11-17" and json.loads(json.dumps(r.datos)) == r.datos
    assert_formato_calidad(r.calidad)


# --------------------------------------------------------------------------- #
# 7. Esquemas Pydantic (capa estricta y formato de calidad)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("calidad", [
    {"estado": "ok", "observaciones": [{"campo": "fecha", "accion": "reparar", "detalle": "x"}]},
    {"estado": "corregido", "observaciones": []},
    {"estado": "advertencia", "observaciones": []},
    {"estado": "corregido", "observaciones": [{"campo": "f", "accion": "advertir", "detalle": "x"}]},
    {"estado": "advertencia", "observaciones": [{"campo": "f", "accion": "reparar", "detalle": "x"}]},
    {"estado": "corregido", "observaciones": [{"campo": "f", "accion": "rechazar", "detalle": "x"}]},
    {"estado": "error", "observaciones": []},
    {"estado": "ok", "observaciones": [], "extra": 1},
    {"estado": "corregido", "observaciones": [{"campo": "f", "accion": "reparar"}]},
])
def test_calidad_incoherente_es_invalida(calidad):
    with pytest.raises(ValidationError):
        Calidad.model_validate(calidad)


def test_calidad_ok_serializa_observaciones_vacias():
    assert Calidad(estado="ok").model_dump() == {"estado": "ok", "observaciones": []}


@pytest.mark.parametrize("cambio", [
    {"tienda_id": "5"}, {"tienda_id": 0}, {"fecha": "17/11/2025"}, {"familias": []},
    {"familias": [{"familia_id": "abarrotes", "en_promocion": "1"}]},
    {"familias": [{"familia_id": "Abarrotes", "en_promocion": 1}]},
    {"familias": [{"familia_id": "abarrotes", "en_promocion": -1}]},
    {"familias": [{"familia_id": "abarrotes", "en_promocion": 1}, {"familia_id": "abarrotes", "en_promocion": 1}]},
    {"extra": True},
])
def test_modelo_canonico_es_estricto(cambio, pred_valida):
    with pytest.raises(ValidationError):
        SolicitudPrediccion.model_validate({**pred_valida, **cambio})


def test_modelo_canonico_valida_catalogo_por_contexto(pred_valida, cat):
    pred_valida["familias"][0]["familia_id"] = "juguetes"
    SolicitudPrediccion.model_validate(pred_valida)  # sin catálogo: el formato es válido
    with pytest.raises(ValidationError):
        SolicitudPrediccion.model_validate(pred_valida, context={"catalogos": cat})


def test_modelo_observaciones_estricto(obs_valida):
    SolicitudObservaciones.model_validate(obs_valida)
    obs_valida["ventas"][0]["ventas"] = "994"
    with pytest.raises(ValidationError):
        SolicitudObservaciones.model_validate(obs_valida)


def test_cuerpo_error_422(cat):
    with pytest.raises(ErrorContrato) as exc:
        validar_observaciones(leer_json(DIR_ERRORES / "E08_ventas_negativas.json"), cat)
    cuerpo = cuerpo_error(exc.value)
    assert list(cuerpo) == ["detail"]
    assert cuerpo["detail"][0]["campo"] == "ventas[5].ventas"
    assert cuerpo["detail"][0]["accion"] == "rechazar"


def test_respuesta_observaciones_formato():
    r = RespuestaObservaciones(registros_guardados=0, calidad=Calidad(estado="ok"))
    assert r.model_dump() == {"registros_guardados": 0, "calidad": {"estado": "ok", "observaciones": []}}


# --------------------------------------------------------------------------- #
# 8. Persistencia (SQLite en memoria; PostgreSQL si TEST_DATABASE_URL está definida)
# --------------------------------------------------------------------------- #
def test_esquema_crea_todas_las_tablas(motor):
    esperadas = {"tiendas", "familias", "costos", "feriados", "ventas", "solicitudes", "predicciones",
                 "correcciones", "ejecuciones_reentrenamiento"}
    assert esperadas <= set(sa_inspect(motor).get_table_names())


def test_carga_de_catalogos_es_idempotente(motor, cat):
    cargar_catalogos_en_bd(motor, cat)
    with motor.connect() as con:
        assert con.execute(select(func.count()).select_from(tiendas)).scalar_one() == 10
        assert con.execute(select(func.count()).select_from(feriados)).scalar_one() == len(cat.feriados)


def _guardar(repo, cat, payload) -> int:
    s, _ = validar_observaciones(payload, cat)
    d = s.model_dump()
    return repo.guardar_observaciones(d["tienda_id"], d["fecha"], d["ventas"])


def test_e09_envio_repetido_es_idempotente(repo, cat):
    payload = leer_json(DIR_ERRORES / "E09_envio_repetido.json")
    assert _guardar(repo, cat, payload) == 12
    assert _guardar(repo, cat, payload) == 0
    assert _guardar(repo, cat, payload) == 0
    assert repo.contar_ventas() == 12


def test_registros_guardados_cuenta_solo_nuevos_o_cambiados(repo, cat, obs_valida):
    assert _guardar(repo, cat, obs_valida) == 12
    obs_valida["ventas"][0]["ventas"] = 1000  # cambia
    obs_valida["ventas"][1]["ventas"] = 50  # igual
    assert _guardar(repo, cat, obs_valida) == 1
    assert {v["familia_id"]: v["ventas"] for v in repo.obtener_ventas(5, "2025-11-17")}["abarrotes"] == 1000
    assert _guardar(repo, cat, obs_valida) == 0


def test_observacion_reparada_equivale_a_la_valida(repo, cat, obs_valida):
    # E10 normalizado coincide con la observación válida salvo los valores reparados
    assert _guardar(repo, cat, obs_valida) == 12
    e10 = leer_json(DIR_ERRORES / "E10_numero_formato.json")
    assert _guardar(repo, cat, e10) == 0  # "50,0" == 50 y "1,292" == 1292


def test_observacion_parcial_y_luego_completa(repo, cat, obs_valida):
    parcial = {**obs_valida, "ventas": obs_valida["ventas"][:5]}
    assert _guardar(repo, cat, parcial) == 5
    assert _guardar(repo, cat, obs_valida) == 7


def test_otro_dia_u_otra_tienda_son_filas_nuevas(repo, cat, obs_valida):
    assert _guardar(repo, cat, obs_valida) == 12
    assert _guardar(repo, cat, {**obs_valida, "fecha": "2025-11-18"}) == 12
    assert _guardar(repo, cat, {**obs_valida, "tienda_id": 4}) == 12


def test_cambio_solo_en_promocion_no_cuenta(repo):
    filas = [{"familia_id": "abarrotes", "ventas": 10, "en_promocion": 1}]
    assert repo.guardar_observaciones(5, "2025-11-17", filas) == 1
    assert repo.guardar_observaciones(5, "2025-11-17", [{**filas[0], "en_promocion": 3}]) == 0


def test_duplicado_en_la_misma_llamada_no_rompe_el_upsert(repo):
    filas = [{"familia_id": "abarrotes", "ventas": 10}, {"familia_id": "abarrotes", "ventas": 12}]
    assert repo.guardar_observaciones(5, date(2025, 11, 17), filas) == 1
    assert repo.obtener_ventas(5, "2025-11-17")[0]["ventas"] == 12


def test_historico_completo_y_observacion_igual_al_historico(repo, motor):
    insertadas = cargar_historico(motor, DIR_DATOS / "historico_ventas.csv")
    assert insertadas == 83052 and repo.contar_ventas() == 83052
    assert cargar_historico(motor, DIR_DATOS / "historico_ventas.csv") == 0  # idempotente
    assert repo.fecha_max_ventas() == date(2026, 2, 28)
    fila = repo.obtener_ventas(1, "2024-03-01")[0]
    assert repo.guardar_observaciones(1, "2024-03-01", [fila]) == 0
    assert repo.guardar_observaciones(1, "2024-03-01", [{**fila, "ventas": fila["ventas"] + 1}]) == 1
    actualizada = repo.obtener_ventas(1, "2024-03-01")[0]
    assert actualizada["origen"] == "observacion" and actualizada["en_promocion"] == fila["en_promocion"]


def test_restricciones_de_bd_impiden_ventas_negativas_y_tiendas_inexistentes(repo):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        repo.guardar_observaciones(5, "2025-11-17", [{"familia_id": "abarrotes", "ventas": -1}])
    with pytest.raises(IntegrityError):
        repo.guardar_observaciones(99, "2025-11-17", [{"familia_id": "abarrotes", "ventas": 1}])


def test_registrar_solicitud_corregida_guarda_correcciones(repo, cat):
    crudo = leer_json(DIR_ERRORES / "E02_familia_otra_forma.json")
    s, q = validar_prediccion(crudo, cat)
    sid = repo.registrar_solicitud("/v1/prediccion", crudo, 200, payload_limpio=s, calidad=q)
    (fila,) = repo.listar(solicitudes, id=sid)
    assert fila["estado_calidad"] == "corregido" and fila["tienda_id"] == 5
    assert fila["fecha"] == date(2025, 11, 17) and fila["payload_crudo"] == crudo
    assert fila["payload_limpio"]["familias"][6]["familia_id"] == "lacteos"
    corr = repo.listar(correcciones, solicitud_id=sid)
    assert [(c["campo"], c["accion"]) for c in corr] == acciones(q)


def test_registrar_solicitud_rechazada(repo, cat):
    crudo = leer_json(DIR_ERRORES / "E08_ventas_negativas.json")
    with pytest.raises(ErrorContrato) as exc:
        validar_observaciones(crudo, cat)
    sid = repo.registrar_solicitud("/v1/observaciones", crudo, 422, errores=exc.value.errores)
    (fila,) = repo.listar(solicitudes, id=sid)
    assert fila["http_status"] == 422 and fila["payload_limpio"] is None
    (c,) = repo.listar(correcciones, solicitud_id=sid)
    assert c["accion"] == "rechazar" and c["campo"] == "ventas[5].ventas"


def test_registrar_predicciones_con_version_modelo(repo, cat, pred_valida):
    s, q = validar_prediccion(pred_valida, cat)
    sid = repo.registrar_solicitud("/v1/prediccion", pred_valida, 200, payload_limpio=s, calidad=q)
    filas = [{"familia_id": f.familia_id, "en_promocion": f.en_promocion, "prediccion": 100.5} for f in s.familias]
    assert repo.registrar_predicciones(sid, 5, s.fecha, filas, "novamercado-pronostico/3") == 12
    guardadas = repo.listar(predicciones, solicitud_id=sid)
    assert len(guardadas) == 12 and {g["version_modelo"] for g in guardadas} == {"novamercado-pronostico/3"}
    with pytest.raises(ValueError):
        repo.registrar_predicciones(sid, 5, s.fecha, filas, "")


def test_ciclo_de_vida_de_ejecucion_de_reentrenamiento(repo):
    eid = repo.crear_ejecucion(motivo="llegaron 7 días nuevos de observaciones")
    e = repo.obtener_ejecucion(eid)
    assert e["estado"] == "pendiente" and e["promovido"] is False and e["version"] is None
    assert e["motivo"].startswith("llegaron")
    repo.actualizar_ejecucion(eid, estado="en_curso")
    repo.actualizar_ejecucion(eid, estado="completada", promovido=True, version="4",
                              metricas={"costo_candidato": 10.2, "costo_produccion": 11.0})
    e = repo.obtener_ejecucion(eid)
    assert (e["estado"], e["promovido"], e["version"]) == ("completada", True, "4")
    assert e["metricas"]["costo_candidato"] == 10.2 and e["finalizado_en"] is not None
    assert [x["id"] for x in repo.listar_ejecuciones()] == [eid]


def test_ejecucion_estado_invalido_o_inexistente(repo):
    eid = repo.crear_ejecucion("prueba")
    with pytest.raises(ValueError):
        repo.actualizar_ejecucion(eid, estado="terminada")
    with pytest.raises(KeyError):
        repo.actualizar_ejecucion("no-existe", estado="fallida")
    assert repo.obtener_ejecucion("no-existe") is None


def test_metadata_no_depende_de_mlflow():
    import sys

    assert "mlflow" not in sys.modules
    assert metadata.tables  # el esquema se define sin servicios externos
