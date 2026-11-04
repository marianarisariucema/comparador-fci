"""Pruebas con una planilla que imita el formato real de CAFCI (relevado 2026-11-04):
bloque de título, encabezado en dos niveles con subcolumnas fechadas, filas de sección
y una fila por clase."""
import io, sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).parent))
import actualizar as a

N = None
ENC1 = ["Fondo", "Clasificación", N, N, "Fecha", "Valor (mil cuotapartes)", N, N, N,
        "Variacion cuotaparte %", N, N, "Cantidad de cuotapartes", N, "Patrimonio", N,
        "Market Share", "Sociedad Depositaria", "Codigo CNV", "Calificación", "Código CAFCI",
        "Código de Soc.Gte.", "Código de Soc.Dep.", "Sociedad Gerente", "Código de Moneda",
        "Honorarios Adm. SG", "Honorarios Adm. SD", "Moneda Fondo", "Plazo Liq.", "Mínimo de Inversión"]
ENC2 = [N, "Moneda", "Región", "Horizonte", N, "Actual", "02/11/26", "Variac. %", "Reexp.Pesos",
        "30/10/26", "30/12/25", "31/10/25", "Actual", "02/11/26", "Actual", "02/11/26"] + [N] * 14

def fila(nombre, vcp, vcp0, var, cp, pat, pat0, cnv, cafci):
    return [nombre, "ARS", "Arg", "Flex", "03/11/26", vcp, vcp0, var, vcp, -0.511, "–", "–",
            cp, cp, pat, pat0, 0.045, "Banco Comafi S.A.", cnv, "–", cafci, 3118, 115,
            "BAVSA Fondos S.A.", 1, 3.5, 0.1, "ARS", 1, 1000.0]

def planilla_prueba() -> bytes:
    filas = [["CAMARA ARGENTINA DE FONDOS COMUNES DE INVERSION"] + [N] * 29,
             ["Reporte: Planilla Diaria (Valores sujetos a revisión)"] + [N] * 29]
    filas += [[N] * 30] * 5 + [ENC1, ENC2, [N] * 30]
    filas += [["Renta Variable Peso Argentina"] + [N] * 29,
              fila("BAVSA Renta Balanceado IX - Clase A", 1030.248, 1018.501, 1.153,
                   698034918.33, 719149294.23, 710948031.6, "CNV 1901", "CAFCI 6419"),
              fila("BAVSA Renta Balanceado IX - Clase B", 100.0, 100.0, 0.0,
                   50.0, 500.0, 600.0, "CNV 1901", "CAFCI 6420"),
              ["Mercado de Dinero Peso Argentina"] + [N] * 29,
              fila("Fondo MM", 10.0, 9.99, 0.1, 5.0, 1000.0, "–", "CNV 2000", "CAFCI 7000"),
              ["(*) Nota al pie"] + [N] * 29]
    buf = io.BytesIO()
    pd.DataFrame(filas).to_excel(buf, header=False, index=False)
    return buf.getvalue()

def test_formato_real():
    fondos, info = a.normalizar(a.leer_excel(planilla_prueba()))
    assert [f["fondo"] for f in fondos] == [
        "BAVSA Renta Balanceado IX - Clase A", "BAVSA Renta Balanceado IX - Clase B", "Fondo MM"]
    # la planilla de prueba no trae comisiones ni tipo de dinero; el resto debe reconocerse
    assert set(info["columnas_faltantes"]) == {"comision_ingreso", "comision_rescate", "gastos_gestion", "honorarios_exito", "tipo_dinero"}
    a1, b1, mm = fondos
    assert a1["fondo_base"] == "BAVSA Renta Balanceado IX" == b1["fondo_base"]
    assert a1["clave"] == "bavsa renta balanceado ix"
    assert a1["categoria"] == "Renta Variable Peso Argentina"
    assert mm["categoria"] == "Mercado de Dinero Peso Argentina"
    assert a1["fecha"] == "2026-11-03"
    assert (a1["vcp"], a1["vcp_anterior"], a1["variacion_pct"]) == (1030.248, 1018.501, 1.153)
    assert a1["cuotapartes"] == 698034918.33
    assert a1["rend_mes_pct"] == -0.511 and a1["rend_anio_pct"] is None
    assert (a1["patrimonio"], a1["patrimonio_anterior"]) == (719149294.23, 710948031.6)
    assert a1["moneda"] == "ARS" and a1["horizonte"] == "Flex"
    assert a1["gerente"] == "BAVSA Fondos S.A." and a1["depositaria"] == "Banco Comafi S.A."
    assert a1["codigo_cnv"] == "CNV 1901" and a1["codigo_cafci"] == "CAFCI 6419"
    assert a1["honorarios_gerente"] == 3.5 and a1["minimo_inversion"] == 1000.0
    assert a1["calificacion"] is None or a1["calificacion"] == "–"
    # 719.149.294,23 - 710.948.031,6 * 1030.248/1018.501
    esperado = 719149294.23 - 710948031.6 * 1030.248 / 1018.501
    assert abs(a1["flujo_neto_estimado"] - esperado) < 0.01
    assert b1["flujo_neto_estimado"] == -100.0
    assert mm["flujo_neto_estimado"] is None  # patrimonio anterior "–"

def test_rechaza_pagina_de_error():
    try:
        a.leer_excel(b"<html>Request blocked</html>")
    except RuntimeError:
        return
    raise AssertionError("debió fallar")
