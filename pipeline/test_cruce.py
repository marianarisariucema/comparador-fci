from cruce import Cruce

G = "Gestora S.A."
CLASES = [{"clave": c, "gerente": G} for c in (
    "fima abierto pymes", "megaqm renta dolares", "fondo global vi", "fondo global vii",
    "megaqm cobertura", "megaqm cobertura a pymes")]


def test_nombre_simplificado():
    k, m = Cruce(CLASES).emparejar({"fondo": "Fima FCI Abierto Pymes", "clave": "fima", "gerente": G})
    assert k == "fima abierto pymes"


def test_dolares_y_acentos():
    k, _ = Cruce(CLASES).emparejar({"fondo": "MEGAQM Renta Dólares", "clave": "x", "gerente": G})
    assert k == "megaqm renta dolares"


def test_no_confunde_numeros():
    k, _ = Cruce(CLASES).emparejar({"fondo": "Fondo Global VIII", "clave": "x", "gerente": G})
    assert k is None


def test_otra_gestora_no_cruza():
    k, _ = Cruce(CLASES).emparejar({"fondo": "Fima Abierto Pymes", "clave": "x", "gerente": "Otra"})
    assert k is None


def test_choque_queda_el_exacto():
    carteras = {"1": {"fondo": "MEGAQM Cobertura", "clave": "megaqm cobertura", "gerente": G},
                "2": {"fondo": "MEGAQM Cobertura FCIA Pymes", "clave": "megaqm cobertura", "gerente": G}}
    r = Cruce(CLASES).todas(carteras)
    assert r["1"][0] == "megaqm cobertura"
    assert r["2"][0] in (None, "megaqm cobertura a pymes")
