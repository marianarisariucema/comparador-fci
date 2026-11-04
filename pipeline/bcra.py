"""Indicadores del BCRA para comparar los fondos contra inflación, dólar y plazo fijo.

Fuente: API pública de Estadísticas del BCRA (sin clave):
  https://api.bcra.gob.ar/estadisticas/v3.0/monetarias            -> lista de variables
  https://api.bcra.gob.ar/estadisticas/v3.0/monetarias/{id}?desde=&hasta=  -> serie

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

BASE = "https://api.bcra.gob.ar/estadisticas/v3.0/monetarias"
HEADERS = {"User-Agent": "comparador-fci/0.1 (+https://github.com/marianarisariucema/comparador-fci)",
           "Accept-Language": "es-AR"}
DATA = Path(__file__).resolve().parent.parent / "data" / "bcra"
DIAS = 730

# clave -> palabras que deben aparecer en la descripción (sin acentos, minúsculas)
BUSCADAS = {
    "cer": ["cer"],
    "dolar_mayorista": ["tipo de cambio", "mayorista"],
    "dolar_minorista": ["tipo de cambio", "minorista"],
    "tasa_plazo_fijo": ["plazo fijo"],
    "badlar": ["badlar"],
    "inflacion_mensual": ["inflacion mensual"],
    "inflacion_interanual": ["inflacion interanual"],
    "uva": ["uva"],
}


def norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t))
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def get(sesion, url, **params):
    r = sesion.get(url, params=params or None, timeout=60)
    r.raise_for_status()
    return r.json()


def elegir(variables: list[dict]) -> dict[str, dict]:
    elegidas = {}
    for clave, palabras in BUSCADAS.items():
        candidatas = [v for v in variables if all(p in norm(v.get("descripcion", "")) for p in palabras)]
        if candidatas:
            # la descripción más corta suele ser la serie principal
            elegidas[clave] = min(candidatas, key=lambda v: len(v.get("descripcion", "")))
    return elegidas


def puntos(respuesta) -> list[dict]:
    res = respuesta.get("results", respuesta)
    if isinstance(res, list) and res and isinstance(res[0], dict) and "detalle" in res[0]:
        res = res[0]["detalle"]
    return [{"fecha": p.get("fecha"), "valor": p.get("valor")} for p in res if isinstance(p, dict)]


def main() -> int:
    s = requests.Session()
    s.headers.update(HEADERS)
    variables = get(s, BASE).get("results", [])
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "variables.json").write_text(json.dumps(variables, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"BCRA: {len(variables)} variables disponibles")

    hasta = dt.date.today()
    desde = hasta - dt.timedelta(days=DIAS)
    elegidas = elegir(variables)
    for clave, v in elegidas.items():
        try:
            serie = puntos(get(s, f"{BASE}/{v['idVariable']}", desde=desde.isoformat(), hasta=hasta.isoformat()))
            serie.sort(key=lambda p: p["fecha"] or "")
            (DATA / f"{clave}.json").write_text(json.dumps({
                "clave": clave, "id_bcra": v["idVariable"], "descripcion": v.get("descripcion"),
                "fuente": "BCRA - API de Estadísticas v3.0", "serie": serie,
            }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            print(f"  {clave}: id {v['idVariable']} '{v.get('descripcion')}' -> {len(serie)} puntos")
        except Exception as e:
            print(f"  {clave}: error {e}", file=sys.stderr)
        time.sleep(0.5)
    faltan = sorted(set(BUSCADAS) - set(elegidas))
    if faltan:
        print(f"No encontré variables para: {faltan}")
    return 0 if elegidas else 1


if __name__ == "__main__":
    sys.exit(main())
