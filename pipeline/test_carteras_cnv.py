"""Pruebas con HTML que imita la ficha de la CNV (estructura relevada el 2026-11-04)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import carteras_cnv as c

HTML = """<html><body><div class="tab-content"><div class="tab-pane" id="1a"><table><tr><td>Otra cosa</td><td>x</td></tr></table></div>
<div class="tab-pane m-b-15" id="1b"><h2>Composición Semanal Cartera FONDO (artículo 34 del Capítulo XI)</h2>
<table><tbody>
<tr><td>Fondo</td><td>Supergestion Mix VI</td></tr>
<tr><td>Cartera al (*)</td><td>16/10/26</td></tr>
<tr><td>Gerente</td><td>Gestora S.A.</td></tr>
<tr><td>Depositaria</td><td>Banco S.A.</td></tr>
<tr><td>Clasificación</td><td>Renta Fija</td></tr>
<tr><td>Moneda</td><td>Peso Argentina</td></tr>
</tbody></table>
<H4>COMPOSICIÓN DE CARTERAS ANTERIORES</H4><input type="date" id="fecha">
<table><thead><tr><th>Detalle (1)</th><th>% del P.N.</th><th>% del P.N.(2)</th></tr></thead><tbody>
<tr><td style="font-weight: bold;">Disponibilidades</td><td></td><td>0,12</td></tr>
<tr><td style="font-weight: bold;">Titulos de Deuda en Peso Argentina</td><td></td><td>79,94</td></tr>
<tr><td style="padding-left: 30px;"><span>Lecer X30N6</span></td><td>10,81</td><td></td></tr>
<tr><td style="padding-left: 30px;"><span>Bono del Tesoro Nacional TML27</span></td><td>9,28</td><td></td></tr>
<tr><td style="font-weight: bold;">Operaciones a Plazo</td><td></td><td>19,94</td></tr>
<tr><td style="padding-left: 30px;"><span>Plazo Fijo Banco Nación</span></td><td>19,94</td><td></td></tr>
<tr><td style="font-weight: bold;"></td><td></td><td>100,00</td></tr>
<tr><td style="font-weight: bold;">(Peso Argentina)</td><td>1.163.737.181.833,70</td><td></td></tr>
</tbody></table><p>Notas de metodología</p></div></div></body></html>"""

def test_parsea_ficha():
    r = c.parsear_ficha(HTML)
    assert r["fondo"] == "Supergestion Mix VI" and r["fecha_cartera"] == "2026-10-16"
    assert r["gerente"] == "Gestora S.A." and r["clasificacion"] == "Renta Fija"
    assert [t["tipo"] for t in r["por_tipo"]] == [
        "Disponibilidades", "Titulos de Deuda en Peso Argentina", "Operaciones a Plazo"]
    assert r["por_tipo"][1]["pct_pn"] == 79.94
    assert r["activos"][0] == {"activo": "Lecer X30N6", "tipo": "Titulos de Deuda en Peso Argentina", "pct_pn": 10.81}
    assert r["activos"][2]["tipo"] == "Operaciones a Plazo"
    assert r["patrimonio_por_moneda"] == {"Peso Argentina": 1163737181833.70}

def test_nombre_clave_cruza_cnv_y_cafci():
    assert c.nombre_clave("SF12-Supergestión Mix VI F.C.I.") == "supergestion mix vi"
    assert c.nombre_clave("Supergestion Mix VI - Clase A") == "supergestion mix vi"
    assert c.nombre_clave("Alpha Acciones Ex 1784 ACCIONES") == c.nombre_clave("Alpha Acciones - Clase B")
    assert c.nombre_clave("MAF Acciones Argentina FCI") == c.nombre_clave("MAF Acciones Argentinas")
    assert c.nombre_clave("BULL MARKET ACCIONES ARGENTINAS FONDO COMUN DE INV") == c.nombre_clave("Bull Market Acciones Argentinas")
    assert c.nombre_clave("ALLARIA ACCIONES FCI   Ex AL RENTA VARIABLE FC)") == "allaria acciones"

def test_sin_cartera():
    try:
        c.parsear_ficha("<html><div id='1a'></div></html>")
    except ValueError:
        return
    raise AssertionError("debió fallar")


def test_nombre_clave_clase_sin_guion():
    assert c.nombre_clave("Pellegrini Liquidez Pesos Clase C") == "pellegrini liquidez pesos"
    assert c.nombre_clave("Fondo Clase Ley 27.743") != "fondo"
