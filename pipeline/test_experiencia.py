import collections
import datetime as dt

import experiencia as ex


def test_dias_habiles_saltea_fin_de_semana_y_feriados():
    jueves = dt.date(2026, 11, 5)
    assert ex.dias_habiles_despues(jueves, 1, set()) == dt.date(2026, 11, 6)
    assert ex.dias_habiles_despues(jueves, 2, set()) == dt.date(2026, 11, 9)
    assert ex.dias_habiles_despues(jueves, 1, {"2026-11-06"}) == dt.date(2026, 11, 9)


def test_cartera_en_comun():
    a = collections.Counter({"AL30": 50, "plazo fijo": 50})
    b = collections.Counter({"AL30": 20, "GD30": 80})
    assert ex.en_comun(a, b) == 20


def test_vector_usa_ticker_o_nombre():
    c = {"activos": [{"activo": "Bono X", "ticker": "al30", "pct": 10}, {"activo": "Pzo  Fi $ Bco", "pct": 5},
                     {"activo": "Bono X", "pct_pn": 3}]}
    assert ex.vector(c) == {"AL30": 10, "pzo fi bco": 5, "bono x": 3}
    assert ex.vector(c, por_nombre=True) == {"bono x": 13, "pzo fi bco": 5}


def test_dato_dudoso():
    assert ex.dudosa({"rend_12m_pct": 396754}) is not None
    assert ex.dudosa({"rend_12m_pct": 25, "variacion_pct": -0.4}) is None


def test_formato_argentino():
    assert ex.pct(-1.25) in ("1,2%", "1,3%")
    assert ex.pct(0.55) == "0,55%"
    assert ex.pct(3.0) == "3%"
    assert ex.pesos(32000) == "$32.000"
