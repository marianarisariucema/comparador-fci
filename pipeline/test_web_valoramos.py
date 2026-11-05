import datetime as dt

import web


def _serie(valores, desde=(2025, 1)):
    y, m = desde
    out = []
    for v in valores:
        out.append((dt.date(y, m, 28), v))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def test_meses_movimiento_peor_y_mejor_mes():
    s = _serie([100, 102, 99, 103, 104, 105, 106, 110])
    m = web.meses_movimiento(s)
    assert m["total"] == 7 and m["positivos"] == 6
    assert m["peor_mes"] == "2025-03" and round(m["peor_pct"], 1) == -2.9
    assert m["mejor_mes"] == "2025-04"


def test_meses_movimiento_no_mezcla_huecos_ni_mes_en_curso():
    s = _serie([100, 101, 102, 103, 104, 105, 106])
    s.insert(3, (dt.date(2025, 3, 5), 50.0))  # dato de principio de mes: no es cierre
    s.append((dt.date(2026, 1, 28), 10.0))     # hueco de meses: no se compara
    m = web.meses_movimiento(s)
    assert m["total"] == 6 and m["peor_pct"] > 0
    assert web.meses_movimiento(_serie([100, 101, 102])) is None


def test_lo_que_valoramos_compara_con_fondos_parecidos():
    def fondo(i, costo, r1):
        ref = {"id": f"f{i}-a", "honorarios_gerente": costo, "honorarios_depositaria": 0,
               "comision_ingreso": 0, "comision_rescate": 0}
        return {"subtipo": "Renta fija CER", "moneda": "ARS", "disponible": True, "gerente": "G",
                "_ref": ref, "_cs": [ref], "_r": {"1a": r1}, "_serie": []}
    fs = [fondo(i, 1 + i * 0.5, 30 + i) for i in range(6)]
    web.lo_que_valoramos(fs, {"G": {"nombre": "G", "puesto": 2, "cantidad_fondos": 6, "patrimonio": 1}}, {"f0-a": "2024-01-31"})
    v = fs[0]["valoramos"]
    assert v["costo"]["cobran_mas"] == 5 and v["costo"]["de"] == 6
    assert v["rend_1a"] == {"puesto": 6, "de": 6} and fs[5]["valoramos"]["rend_1a"]["puesto"] == 1
    assert v["gestora"]["puesto"] == 2 and v["desde"] == "2024-01-31"
    assert v["rend_2a"] is None
