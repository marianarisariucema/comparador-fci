"""Indicadores del BCRA para comparar los fondos contra inflación, dólar y plazo fijo.

Fuente: API pública de Estadísticas del BCRA (sin clave):
  https://api.bcra.gob.ar/estadisticas/v4.0/monetarias            -> lista de variables
  https://api.bcra.gob.ar/estadisticas/v4.0/monetarias/{id}?desde=&hasta=  -> serie

Las variables se eligen por su descripción (los IDs pueden cambiar).
Escribe data/bcra/variables.json y data/bcra/<clave>.json.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests

from red import pedir

# v3.0 respondió 410 Gone el 2026-11-04; se prueba v4.0 primero.
BASES = ["https://api.bcra.gob.ar/estadisticas/v4.0/monetarias",
         "https://api.bcra.gob.ar/estadisticas/v3.0/monetarias"]
HEADERS = {"User-Agent": "comparador-fci/0.1 (+https://github.com/marianarisariucema/comparador-fci)",
           "Accept-Language": "es-AR"}
DATA = Path(__file__).resolve().parent.parent / "data" / "bcra"
DIAS = 730

# Variables elegidas por ID (verificadas contra la descripción el 2026-11-04).
# Elegir por palabras fallaba: "cer" coincide con "terceros".
VARIABLES = {
    "dolar_minorista": 4,       # Tipo de cambio minorista (promedio vendedor)
    "dolar_mayorista": 5,       # Tipo de cambio mayorista de referencia (A3500)
    "badlar": 7,                # Tasa BADLAR de bancos privados
    "tasa_plazo_fijo_30d": 12,  # Tasa de depósitos a 30 días
    "inflacion_mensual": 27,
    "inflacion_interanual": 28,
    "inflacion_esperada_12m": 29,  # REM
    "cer": 30,                  # Coeficiente de estabilización de referencia
    "uva": 31,
    "tamar": 44,                # Tasa TAMAR de bancos privados
}


def norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t))
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def get(sesion, url, **params):
    r = pedir(url, sesion=sesion, params=params or None)
    r.raise_for_status()
    return r.json()


def elegir(variables: list[dict]) -> dict[str, dict]:
    por_id = {v["idVariable"]: v for v in variables}
    return {clave: por_id.get(i, {"idVariable": i, "descripcion": None}) for clave, i in VARIABLES.items()}


def puntos(respuesta) -> list[dict]:
    res = respuesta.get("results", respuesta)
    if isinstance(res, list) and res and isinstance(res[0], dict) and "detalle" in res[0]:
        res = res[0]["detalle"]
    return [{"fecha": p.get("fecha"), "valor": p.get("valor")} for p in res if isinstance(p, dict)]


def main() -> int:
    s = requests.Session()
    s.headers.update(HEADERS)
    variables, BASE = [], None
    for base in BASES:
        try:
            variables = get(s, base).get("results", [])
            BASE = base
            break
        except Exception as e:
            print(f"{base}: {e}", file=sys.stderr)
    if not BASE:
        return 1
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "variables.json").write_text(json.dumps(variables, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"BCRA ({BASE}): {len(variables)} variables disponibles")

    hasta = dt.date.today()
    desde = hasta - dt.timedelta(days=DIAS)
    elegidas = elegir(variables)
    for clave, v in elegidas.items():
        try:
            serie = puntos(get(s, f"{BASE}/{v['idVariable']}", desde=desde.isoformat(), hasta=hasta.isoformat()))
            serie.sort(key=lambda p: p["fecha"] or "")
            previa = DATA / f"{clave}.json"
            n_previa = len(json.loads(previa.read_text(encoding="utf-8")).get("serie", [])) if previa.exists() else 0
            if len(serie) < 0.5 * n_previa:
                # Respuesta incompleta: se conserva la serie que ya estaba.
                print(f"  {clave}: vinieron {len(serie)} puntos y había {n_previa}; conservo la anterior", file=sys.stderr)
                continue
            (DATA / f"{clave}.json").write_text(json.dumps({
                "clave": clave, "id_bcra": v["idVariable"], "descripcion": v.get("descripcion"),
                "fuente": f"BCRA - API de Estadísticas ({BASE})", "serie": serie,
            }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            print(f"  {clave}: id {v['idVariable']} '{v.get('descripcion')}' -> {len(serie)} puntos")
        except Exception as e:
            print(f"  {clave}: error {e}", file=sys.stderr)
        time.sleep(0.5)
    return 0 if elegidas else 1


if __name__ == "__main__":
    sys.exit(main())
