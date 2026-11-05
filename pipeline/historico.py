"""Histórico de cuotaparte y rendimientos por período.

- `--completar`: baja de ArgentinaDatos (gratis, sin clave) la cuotaparte y el patrimonio de
  todos los fondos hacia atrás: todos los días hábiles del último año y medio y el último día de
  cada mes de los 5 años anteriores. Guarda un archivo por fecha en data/historico_ad/.
  Solo baja las fechas que faltan, así que se puede cortar y volver a correr.
- Sin argumentos: calcula data/analisis/rendimientos.json (7 y 30 días, 3 meses, año en curso,
  1, 2 y 5 años) con data/historico/ (planilla CAFCI propia) y data/historico_ad/.

Uso:
  python pipeline/historico.py --completar [--dias 550] [--anios 5]
  python pipeline/historico.py
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"
AD = DATA / "historico_ad"
URL = "https://api.argentinadatos.com/v1/finanzas/fci/{cat}/{fecha}"
CATEGORIAS = ["mercadoDinero", "rentaFija", "rentaVariable", "rentaMixta", "otros"]
HEADERS = {"User-Agent": "comparador-fci/0.1 (+https://github.com/marianarisariucema/comparador-fci)"}
PERIODOS = {"7d": 7, "30d": 30, "90d": 90, "1a": 365, "2a": 730, "5a": 1825}


def slug(texto: str) -> str:  # igual que pipeline/actualizar.py
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower().strip()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def escribir(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def num(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ completar
def fechas_a_bajar(dias: int, anios: int) -> list[dt.date]:
    hoy = dt.date.today()
    fechas = {hoy - dt.timedelta(days=i) for i in range(1, dias + 1)}
    fechas = {f for f in fechas if f.weekday() < 5}
    # Fin de cada mes más atrás (los rendimientos de 2 y 5 años solo necesitan un punto por mes)
    m = (hoy - dt.timedelta(days=dias)).replace(day=1)
    while m > hoy - dt.timedelta(days=365 * anios + 31):
        fin = m - dt.timedelta(days=1)
        fechas.add(fin)
        m = fin.replace(day=1)
    return sorted(fechas, reverse=True)


def bajar_fecha(s: requests.Session, fecha: dt.date) -> dict:
    """{id: [vcp, patrimonio]} de todas las categorías para esa fecha ({} si no hubo datos)."""
    out = {}
    for cat in CATEGORIAS:
        r = s.get(URL.format(cat=cat, fecha=fecha.strftime("%Y/%m/%d")), timeout=60)
        if r.status_code == 404:
            continue
        r.raise_for_status()
        filas = r.json() if r.text.strip() else []
        for x in filas if isinstance(filas, list) else []:
            nombre, vcp = x.get("fondo"), num(x.get("vcp"))
            if nombre and vcp:
                out[slug(nombre)] = [vcp, num(x.get("patrimonio"))]
        time.sleep(0.2)
    return out


def completar(dias: int, anios: int) -> int:
    s = requests.Session()
    s.headers.update(HEADERS)
    pendientes = [f for f in fechas_a_bajar(dias, anios) if not (AD / f"{f.isoformat()}.json").exists()]
    print(f"Fechas a bajar de ArgentinaDatos: {len(pendientes)}")
    ok = vacias = errores = 0
    vacias_seguidas = 0
    for f in pendientes:
        try:
            datos = bajar_fecha(s, f)
        except Exception as e:
            errores += 1
            print(f"  {f}: {str(e)[:150]}")
            if errores > 30:
                print("Demasiados errores, corto acá (lo bajado queda guardado).")
                break
            continue
        if datos:
            escribir(AD / f"{f.isoformat()}.json", datos)
            ok += 1
            vacias_seguidas = 0
        else:
            vacias += 1  # feriado, o fecha anterior al inicio de ArgentinaDatos
            vacias_seguidas += 1
            if f.day >= 25 and (f.month != (f + dt.timedelta(days=1)).month or vacias_seguidas >= 3):
                # fin de mes sin datos: probar unos días antes
                for k in range(1, 5):
                    g = f - dt.timedelta(days=k)
                    if g.weekday() < 5 and not (AD / f"{g.isoformat()}.json").exists():
                        d2 = bajar_fecha(s, g)
                        if d2:
                            escribir(AD / f"{g.isoformat()}.json", d2)
                            ok += 1
                            break
    print(f"ArgentinaDatos: {ok} fechas guardadas, {vacias} sin datos, {errores} con error.")
    return 0 if ok or not pendientes else 1


# ------------------------------------------------------------------ rendimientos
def fechas_disponibles() -> dict[dt.date, Path]:
    out = {}
    for carpeta in (AD, DATA / "historico"):  # la planilla propia pisa a ArgentinaDatos
        for p in carpeta.glob("*.json"):
            try:
                out[dt.date.fromisoformat(p.stem)] = p
            except ValueError:
                pass
    return out


def cargar(p: Path) -> dict:
    d = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(d, dict):
        return {k: (v[0], v[1] if len(v) > 1 else None) for k, v in d.items() if v and v[0]}
    return {x["id"]: (x["vcp"], x.get("patrimonio")) for x in d if x.get("id") and x.get("vcp")}


def rendimientos() -> int:
    fechas = fechas_disponibles()
    if not fechas:
        print("No hay histórico todavía.")
        return 0
    orden = sorted(fechas)
    f0 = orden[-1]
    hoy = cargar(fechas[f0])

    tolerancias = {"7d": 3, "30d": 6, "90d": 20, "1a": 15, "2a": 31, "5a": 45, "anio": 10}
    objetivos = {k: f0 - dt.timedelta(days=d) for k, d in PERIODOS.items()}
    objetivos["anio"] = dt.date(f0.year - 1, 12, 31)
    cache: dict[dt.date, dict] = {}

    def vcps(f):
        if f not in cache:
            cache[f] = cargar(fechas[f])
        return cache[f]

    # Para cada período, las fechas candidatas de la más cercana a la más lejana (ArgentinaDatos
    # trae días incompletos, así que cada fondo usa la fecha más cercana en la que figura)
    candidatas = {k: [f for f in reversed(orden) if objetivos[k] - dt.timedelta(days=tolerancias[k]) <= f <= objetivos[k]]
                  for k in objetivos}
    out = {}
    for fid, (v0, p0) in hoy.items():
        r = {}
        for k, fs in candidatas.items():
            for f in fs:
                vb, pb = vcps(f).get(fid, (None, None))
                if vb:
                    r[k] = round((v0 / vb - 1) * 100, 3)
                    # Plata que entró (+) o salió (-) en el período: lo que creció el patrimonio
                    # por encima de lo que explica el rendimiento
                    if k in ("7d", "30d") and p0 and pb:
                        r[f"flujo_{k}"] = round(p0 - pb * (v0 / vb), 2)
                    break
        for k, anios in (("2a", 2), ("5a", 5)):
            if k in r and r[k] > -100:
                r[f"{k}_anual"] = round(((1 + r[k] / 100) ** (1 / anios) - 1) * 100, 3)
        if r:
            out[fid] = r
    bases = {k: (fs[0] if fs else None) for k, fs in candidatas.items()}
    cobertura = {k: sum(1 for r in out.values() if k in r) for k in objetivos}
    escribir(DATA / "analisis" / "rendimientos.json", {
        "fecha": f0.isoformat(), "fuente": "Planilla CAFCI (propia) y ArgentinaDatos",
        "fechas_base": {k: (f.isoformat() if f else None) for k, f in bases.items()},
        "clases_con_dato": cobertura,
        "nota": "Variación % de la cuotaparte. *_anual = rendimiento anual equivalente.",
        "fondos": out})
    print(f"Rendimientos al {f0}: {len(out)} clases. Con dato por período: " +
          ", ".join(f"{k}={n}" for k, n in cobertura.items()))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--completar", action="store_true", help="Bajar histórico de ArgentinaDatos")
    ap.add_argument("--dias", type=int, default=550, help="Días hacia atrás con dato diario")
    ap.add_argument("--diagnostico", help="Mostrar qué devuelve ArgentinaDatos para esa fecha (AAAA-MM-DD)")
    ap.add_argument("--anios", type=int, default=5, help="Años hacia atrás con dato de fin de mes")
    args = ap.parse_args()
    if args.diagnostico:
        s = requests.Session(); s.headers.update(HEADERS)
        f = dt.date.fromisoformat(args.diagnostico)
        for cat in CATEGORIAS + ["ultimo"]:
            u = URL.format(cat=cat, fecha=f.strftime("%Y/%m/%d")) if cat != "ultimo" else URL.format(cat="rentaFija", fecha="ultimo")
            r = s.get(u, timeout=60)
            j = r.json() if r.ok and r.text.strip() else None
            fechas = sorted({x.get("fecha") for x in j}) if isinstance(j, list) else None
            print(cat, r.status_code, len(j) if isinstance(j, list) else j if not r.ok else type(j).__name__,
                  "fechas:", (fechas[:3], fechas[-3:]) if fechas else None, "ej:", (j[0] if isinstance(j, list) and j else None))
        return 0
    rc = completar(args.dias, args.anios) if args.completar else 0
    rendimientos()
    return rc


if __name__ == "__main__":
    sys.exit(main())
