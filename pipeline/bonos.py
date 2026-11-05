"""Arma data/web/bonos.json para el comparador de bonos de la página.

Un renglón por bono o letra con tasa calculada (pipeline/tasas.js, precios de cierre BYMA vía la
calculadora de renta fija): familia, moneda, precio, TIR, duración, vencimiento y qué fondos lo
tienen (carteras CNV, data/analisis/activos.json).

Corre después de tasas.js, analisis.py y web.py. Sin tasas no escribe nada (la página esconde
el comparador).
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from web import DATA, WEB, escribir, leer, slug  # noqa: E402

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
MAX_FONDOS = 8

# Prefijo del ticker -> nombre que se usa en el mercado
NOMBRES = {
    "Tasa fija": [("S", "Lecap"), ("T", "Boncap")],
    "Inflación (CER)": [("TZX", "Boncer"), ("X", "Lecer")],
    "Dólar linked": [("TZV", "Bono dólar linked"), ("D", "Letra dólar linked")],
    "Bonos en dólares": [("GD", "Global"), ("AL", "Bonar"), ("AE", "Bonar")],
}


def nombre(ticker: str, d: dict) -> str:
    tipo = next((n for p, n in NOMBRES.get(d.get("familia"), []) if ticker.startswith(p)), d.get("familia") or "Bono")
    vto = d.get("vto")
    if not vto:
        return tipo
    y, m = int(vto[:4]), int(vto[5:7])
    if d.get("familia") == "Bonos en dólares":
        return f"{tipo} {y}"
    return f"{tipo} {MESES[m - 1]} {y}"


def mapa_fondos() -> dict[str, dict]:
    """id_cnv -> {id, nombre} del fondo en la página (mismo id que data/web/fondos/<id>.json)."""
    base = {}
    for c in (leer(DATA / "ultimo.json", {}) or {}).get("fondos", []):
        k = c.get("clave") or c.get("id")
        if c.get("fondo_base"):
            base.setdefault(k, c["fondo_base"])
    catalogo = {f["id"]: f for f in (leer(WEB / "catalogo.json", {}) or {}).get("fondos", [])}
    out = {}
    for idc, f in ((leer(DATA / "analisis" / "fondos.json", {}) or {}).get("fondos", {})).items():
        clave = f.get("clave")
        if not clave:
            continue
        fid = slug(base.get(clave) or clave)
        if fid in catalogo:
            out[idc] = {"id": fid, "nombre": catalogo[fid]["nombre"]}
    return out


def armar(tasas: dict, activos: dict, fondos: dict, hoy: dt.date) -> list[dict]:
    por = tasas.get("por_ticker", {})
    bonos = []
    for tk, d in por.items():
        # tasas.js repite los soberanos como AL30 y AL30D (mismo dato): queda uno solo
        if tk.endswith("D") and por.get(tk[:-1]) == d:
            continue
        if d.get("tasa") is None or not d.get("vto"):
            continue
        dias = (dt.date.fromisoformat(d["vto"]) - hoy).days
        if dias <= 0:
            continue
        en = [a for a in (activos.get(tk), activos.get(tk + "D")) if a]
        tenencias, vistos = [], set()
        for a in en:
            for x in a.get("fondos", []):
                f = fondos.get(x.get("id_cnv"))
                if f and f["id"] not in vistos:
                    vistos.add(f["id"])
                    tenencias.append({**f, "pct": x.get("pct")})
        tenencias.sort(key=lambda x: -(x["pct"] or 0))
        usd = d.get("familia") == "Bonos en dólares"
        bonos.append({
            "ticker": tk, "nombre": nombre(tk, d), "familia": d["familia"],
            "moneda": "USD" if usd else "ARS",
            "precio": d.get("precio"), "tasa": d["tasa"], "tasa_tipo": d.get("tasa_tipo"),
            "md": d.get("md"), "vto": d["vto"], "dias": dias, "ley": d.get("ley"),
            "fondos_cantidad": len(tenencias), "fondos": tenencias[:MAX_FONDOS],
        })
    orden = list(NOMBRES)
    bonos.sort(key=lambda b: (orden.index(b["familia"]) if b["familia"] in orden else 9, b["dias"]))
    return bonos


def main() -> int:
    tasas = leer(DATA / "tasas" / "ultimo.json")
    if not tasas or not tasas.get("por_ticker"):
        print("Sin tasas de bonos (data/tasas/ultimo.json): no se arma el comparador.")
        return 0
    activos = (leer(DATA / "analisis" / "activos.json", {}) or {}).get("activos", {})
    precios = leer(DATA / "precios" / "ultimo.json", {}) or {}
    hoy = dt.date.fromisoformat(precios["fecha"]) if precios.get("fecha") else dt.date.today()
    bonos = armar(tasas, activos, mapa_fondos(), hoy)
    escribir(WEB / "bonos.json", {"fecha": precios.get("fecha") or hoy.isoformat(), "fuente": tasas.get("fuente"),
                                  "precios": tasas.get("precios"), "cantidad": len(bonos), "bonos": bonos})
    con = sum(1 for b in bonos if b["fondos_cantidad"])
    print(f"Bonos: {len(bonos)} para comparar, {con} con fondos que los tienen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
