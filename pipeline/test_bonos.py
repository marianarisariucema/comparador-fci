"""Pruebas del armado de data/web/bonos.json."""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import bonos

HOY = dt.date(2026, 11, 4)
SOB = {"familia": "Bonos en dólares", "tasa": 10.9, "tasa_tipo": "anual en dólares", "md": 1.6,
       "vto": "2030-07-09", "precio": 54.4, "ley": "NY"}
TASAS = {"por_ticker": {
    "S13N6": {"familia": "Tasa fija", "tasa": 30.1, "md": 0.02, "vto": "2026-11-13", "precio": 109.1},
    "TZX28": {"familia": "Inflación (CER)", "tasa": 6.0, "md": 1.5, "vto": "2028-06-30", "precio": 120},
    "S30S6": {"familia": "Tasa fija", "tasa": 1.0, "md": 0, "vto": "2026-09-30", "precio": 100},  # vencida
    "GD30": SOB, "GD30D": SOB,
}}
ACTIVOS = {
    "S13N6": {"fondos": [{"id_cnv": "1", "pct": 5.0}, {"id_cnv": "2", "pct": 20.0}, {"id_cnv": "9", "pct": 50.0}]},
    "GD30D": {"fondos": [{"id_cnv": "1", "pct": 3.0}]},
}
FONDOS = {"1": {"id": "fondo-uno", "nombre": "Fondo Uno"}, "2": {"id": "fondo-dos", "nombre": "Fondo Dos"}}


def test_arma_un_renglon_por_bono_vigente():
    b = {x["ticker"]: x for x in bonos.armar(TASAS, ACTIVOS, FONDOS, HOY)}
    assert set(b) == {"S13N6", "TZX28", "GD30"}  # sin el alias GD30D ni la letra vencida
    assert b["GD30"]["moneda"] == "USD" and b["S13N6"]["moneda"] == "ARS"
    assert b["S13N6"]["dias"] == 9


def test_fondos_que_lo_tienen_ordenados_y_solo_los_de_la_pagina():
    b = {x["ticker"]: x for x in bonos.armar(TASAS, ACTIVOS, FONDOS, HOY)}
    assert [f["id"] for f in b["S13N6"]["fondos"]] == ["fondo-dos", "fondo-uno"]  # el 9 no está en la página
    assert b["GD30"]["fondos_cantidad"] == 1  # la CNV lo lista como GD30D
    assert b["TZX28"]["fondos"] == []


def test_nombres_simples():
    assert bonos.nombre("S13N6", TASAS["por_ticker"]["S13N6"]) == "Lecap nov 2026"
    assert bonos.nombre("TZX28", TASAS["por_ticker"]["TZX28"]) == "Boncer jun 2028"
    assert bonos.nombre("GD30", SOB) == "Global 2030"
    assert bonos.nombre("AE38", dict(SOB, vto="2038-01-09")) == "Bonar 2038"
