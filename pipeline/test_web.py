from web import NO_DISPONIBLE, PARA_QUE, TIPOS, tipo_de


def test_categorias_cafci_llevan_a_un_tipo_explicado():
    for cruda, esperado in (
        ("Renta Fija Dolar Estadounidense Billete", "Renta fija dólares: mixta"),
        ("Mercado de Dinero Peso Argentina", "Money market"),
        ("PyMes Peso Argentina", "PyMEs"),
        ("Retorno Total Dolar Estadounidense", "Retorno total"),
        ("En Proceso de Liquidacion por Pago Total", "En liquidación"),
        ("Fondos Cerrados Peso Argentina", "Fondo cerrado"),
        ("RG900 Peso Argentina", "Régimen especial"),
    ):
        assert tipo_de(cruda) == esperado
        assert esperado in TIPOS and esperado in PARA_QUE


def test_tipos_conocidos_y_vacios_no_cambian():
    assert tipo_de("Renta fija CER") == "Renta fija CER"
    assert tipo_de(None) is None
    assert tipo_de("Algo nuevo") == "Algo nuevo"


def test_no_disponibles_no_tienen_objetivos():
    for t in NO_DISPONIBLE:
        assert PARA_QUE[t][1] == []
