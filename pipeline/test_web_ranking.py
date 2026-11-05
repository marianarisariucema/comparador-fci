import web


def test_nombre_gestora():
    assert web.nombre_gestora("Santander Asset Management G.F.C.I.S.A.") == "Santander Asset Management"
    assert web.nombre_gestora("BBVA Asset Management Argentina S.A.U.S.G.F.C.I.") == "BBVA Asset Management Argentina"
    assert web.nombre_gestora("Cohen S.A.") == "Cohen"
    assert web.nombre_gestora("Mercado Pago Asset Managemet S.A.") == "Mercado Pago Asset Management"


def test_por_dia_money_market():
    f = {"subtipo": "Money market", "moneda": "ARS", "_r": {"7d": 0.4}}
    d = web.por_dia(f)
    assert d["monto"] == 100000 and 55 < d["gana"] < 58 and d["tna"] == 20.86
    assert web.por_dia({"subtipo": "Renta mixta", "moneda": "ARS", "_r": {"7d": 0.4}}) is None


def test_premio_por_riesgo_puesto_en_su_grupo():
    fs = [{"subtipo": "Renta mixta", "moneda": "ARS", "_r": {"1a": 30 + i}, "volatilidad_1a": 5} for i in range(6)]
    fs.append({"subtipo": "Money market", "moneda": "ARS", "_r": {"1a": 30}, "volatilidad_1a": 1})
    web.premio_por_riesgo(fs, {"periodos": {"1a": {"plazo_fijo": 25}}})
    assert fs[5]["premio_riesgo"]["puesto"] == 1 and fs[5]["premio_riesgo"]["de"] == 6
    assert fs[0]["premio_riesgo"]["valor"] == 1.0
    assert "premio_riesgo" not in fs[6]
