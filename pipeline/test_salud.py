"""Pruebas del chequeo de salud y de las protecciones del último dato bueno."""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import actualizar
import salud

AR = salud.AR


@pytest.fixture(autouse=True)
def sin_feriados():
    salud.FERIADOS.clear()
    yield
    salud.FERIADOS.clear()


def test_dia_esperado_respeta_horario_y_fin_de_semana():
    # Jueves 5/11/2026 a la 1:00 (hora AR): se espera la planilla del miércoles 4
    assert salud.ultimo_dia_esperado(dt.datetime(2026, 11, 5, 1, 0, tzinfo=AR)) == dt.date(2026, 11, 4)
    # Jueves a las 23:45: ya debería estar la del jueves
    assert salud.ultimo_dia_esperado(dt.datetime(2026, 11, 5, 23, 45, tzinfo=AR)) == dt.date(2026, 11, 5)
    # Lunes 9/11 a la mañana: la del viernes 6
    assert salud.ultimo_dia_esperado(dt.datetime(2026, 11, 9, 7, 0, tzinfo=AR)) == dt.date(2026, 11, 6)


def test_feriado_no_cuenta_como_atraso():
    salud.FERIADOS.add(dt.date(2026, 11, 23))
    # Datos del viernes 20, el lunes 23 es feriado, martes 24 a la mañana: sin atraso
    esperado = salud.ultimo_dia_esperado(dt.datetime(2026, 11, 24, 7, 0, tzinfo=AR))
    assert esperado == dt.date(2026, 11, 20)
    assert salud.dias_habiles_entre(dt.date(2026, 11, 20), esperado) == 0


def preparar(tmp_path, monkeypatch, fecha="2026-11-04", n=4000, previo=4000, faltantes=()):
    data = tmp_path / "data"
    (data / "historico").mkdir(parents=True, exist_ok=True)
    fondos = [{"fondo": f"F{i}", "vcp": 1.0, "patrimonio": 10.0, "variacion_pct": 0.1} for i in range(n)]
    (data / "ultimo.json").write_text(json.dumps({"fecha_datos": fecha, "fondos": fondos}))
    (data / "historico" / "2026-11-03.json").write_text(json.dumps([{}] * previo))
    (data / "estructura_planilla.json").write_text(json.dumps({"columnas_faltantes": list(faltantes)}))
    monkeypatch.setattr(salud, "DATA", data)
    monkeypatch.setattr(salud, "RAIZ", tmp_path)
    return data


def por_id(chequeos):
    return {c.id: c for c in chequeos}


def test_planilla_al_dia(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch)
    c = por_id(salud.chequear_planilla(dt.datetime(2026, 11, 5, 7, 0, tzinfo=AR)))
    assert c["planilla"].estado == "ok"
    assert c["cantidad"].estado == "ok"
    assert c["formato"].estado == "ok"


def test_planilla_atrasada_se_repara_y_dos_dias_es_error(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch, fecha="2026-11-03")
    c = por_id(salud.chequear_planilla(dt.datetime(2026, 11, 5, 7, 0, tzinfo=AR)))
    assert c["planilla"].estado == "aviso" and c["planilla"].reparar_con == salud.WF_DIARIO
    assert c["planilla"].escalar is False  # un día de atraso puede ser CAFCI publicando tarde
    preparar(tmp_path, monkeypatch, fecha="2026-11-02")
    c = por_id(salud.chequear_planilla(dt.datetime(2026, 11, 5, 7, 0, tzinfo=AR)))
    assert c["planilla"].estado == "error"


def test_formato_cambiado_necesita_persona(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch, faltantes=["patrimonio"])
    c = por_id(salud.chequear_planilla(dt.datetime(2026, 11, 5, 7, 0, tzinfo=AR)))
    assert c["formato"].estado == "error" and c["formato"].reparar_con is None


def test_caida_de_cantidad(tmp_path, monkeypatch):
    preparar(tmp_path, monkeypatch, n=3000, previo=4000)
    c = por_id(salud.chequear_planilla(dt.datetime(2026, 11, 5, 7, 0, tzinfo=AR)))
    assert c["cantidad"].estado == "aviso"


class GitHubFalso:
    def __init__(self, runs):
        self.runs, self.relanzados = runs, []

    def corridas(self, wf, n=10):
        return self.runs

    def relanzar(self, wf, rama="main"):
        self.relanzados.append(wf)


def test_reparar_relanza_y_limita():
    hoy = dt.date(2026, 11, 5)
    c = salud.Chequeo("web", "Web", "aviso", reparar_con=salud.WF_DIARIO)
    gh = GitHubFalso([])
    salud.reparar(gh, [c], hoy)
    assert gh.relanzados == [salud.WF_DIARIO] and c.en_reparacion

    bot = {"login": "github-actions[bot]"}
    runs = [{"status": "completed", "event": "workflow_dispatch", "triggering_actor": bot,
             "created_at": "2026-11-05T05:00:00Z"}] * 2
    c = salud.Chequeo("web", "Web", "aviso", reparar_con=salud.WF_DIARIO)
    gh = GitHubFalso(runs)
    salud.reparar(gh, [c], hoy)
    assert gh.relanzados == [] and c.estado == "error"  # agotó los reintentos

    c = salud.Chequeo("planilla", "Planilla", "aviso", reparar_con=salud.WF_DIARIO, escalar=False)
    salud.reparar(GitHubFalso(runs), [c], hoy)
    assert c.estado == "aviso"  # atraso de la fuente: no molesta a nadie


def test_no_relanza_si_hay_corrida_en_curso():
    c = salud.Chequeo("web", "Web", "aviso", reparar_con=salud.WF_DIARIO)
    gh = GitHubFalso([{"status": "in_progress"}])
    salud.reparar(gh, [c], dt.date(2026, 11, 5))
    assert gh.relanzados == [] and c.en_reparacion


# ---- protección del último dato bueno en actualizar.py
def fondos(n, con_vcp=None):
    con_vcp = n if con_vcp is None else con_vcp
    return [{"vcp": 1.0 if i < con_vcp else None} for i in range(n)]


def test_rechaza_planilla_rota():
    previo = {"fecha_datos": "2026-11-04", "cantidad_fondos": 4290}
    assert actualizar.rechazar(fondos(4290), "2026-11-05", previo) is None
    assert "más viejos" in actualizar.rechazar(fondos(4290), "2026-11-03", previo)
    assert "cayó" in actualizar.rechazar(fondos(1000), "2026-11-05", previo)
    assert "columnas" in actualizar.rechazar(fondos(4290, con_vcp=100), "2026-11-05", previo)
    assert actualizar.rechazar(fondos(10), "2026-11-05", None) is None  # primera corrida


class Resp:
    def __init__(self, status, datos):
        self.status_code, self._d = status, datos
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._d


def test_api_salud(monkeypatch):
    import red
    monkeypatch.setattr(red, "pedir", lambda *a, **k: Resp(200, {"ok": True, "fecha_datos": "2026-11-04"}))
    assert salud.chequear_api("https://api").estado == "ok"
    monkeypatch.setattr(red, "pedir", lambda *a, **k: Resp(503, {"ok": False, "dias_de_atraso": 7}))
    assert salud.chequear_api("https://api").estado == "error"


def test_opcionales(tmp_path, monkeypatch):
    data = preparar(tmp_path, monkeypatch)
    assert salud.chequear_opcionales() == []  # todavía no existen: no se chequean
    (data / "tasas").mkdir()
    (data / "tasas" / "ultimo.json").write_text(json.dumps({"por_ticker": {f"T{i}": {} for i in range(5)}}))
    (data / "analisis").mkdir()
    (data / "analisis" / "cruce.json").write_text(json.dumps({"resumen": {"exacto": 900, "sin cruce": 150},
                                                              "sin_cruce": [{}] * 150}))
    c = por_id(salud.chequear_opcionales())
    assert c["tasas"].estado == "aviso" and c["cruce"].estado == "aviso" and not c["cruce"].escalar
