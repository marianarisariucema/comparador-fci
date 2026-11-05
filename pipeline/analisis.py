"""Cálculos sobre los datos propios: a qué está atado cada fondo, subtipo, vencimiento
promedio de la cartera, qué fondos tienen cada activo y ranking de gestoras.

Precios: los toma del robot BYMA End of Day que ya corre en el repo público
marianarisariucema/calculadora-renta-fija (datos.json y mercado.json). No necesita clave.

Uso:
  python pipeline/analisis.py                       # baja los precios de la calculadora
  python pipeline/analisis.py --precios-dir CARPETA # usa datos.json y mercado.json locales
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import sys
from pathlib import Path

import requests

from red import pedir

RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"
URL_CALCULADORA = "https://raw.githubusercontent.com/marianarisariucema/calculadora-renta-fija/main/{archivo}"

# Empresas como las nombra la CNV -> ticker de BYMA
ACCIONES = {
    "ypf": "YPFD", "pampa energia": "PAMP", "grupo financiero galicia": "GGAL", "bbva argentina": "BBAR",
    "banco macro": "BMA", "central puerto": "CEPU", "transportadora gas del sur": "TGSU2",
    "transportadora de gas del sur": "TGSU2", "loma negra": "LOMA", "ternium argentina": "TXAR",
    "transener": "TRAN", "cia de transporte de energia": "TRAN", "bolsas y mercados argentinos": "BYMA",
    "distribuidora de gas del centro": "DGCE", "transportadora de gas del norte": "TGNO4",
    "grupo supervielle": "SUPV", "metrogas": "METR", "aluar": "ALUA", "cresud": "CRES",
    "edenor": "EDN", "empresa distribuidora y comercializadora norte": "EDN", "telecom argentina": "TECO2",
    "holcim": "HARG", "mirgor": "MIRG", "cablevision holding": "CVH", "sociedad comercial del plata": "COME",
    "grupo financiero valores": "VALO", "banco de valores": "VALO", "distribuidora de gas cuyana": "DGCU2",
    "camuzzi gas pampeana": "CGPA2", "consultatio": "CTIO", "irsa": "IRSA", "agrometal": "AGRO",
    "morixe": "MORI", "ledesma": "LEDE", "molinos rio de la plata": "MOLI", "molinos agro": "MOLA",
    "grupo concesionario del oeste": "OEST", "laboratorios richmond": "RICH", "celulosa argentina": "CELU",
    "san miguel": "SAMI", "boldt": "BOLT", "longvie": "LONG", "ferrum": "FERR", "dycasa": "DYCA",
    "gas natural ban": "GBAN", "rigolleau": "RIGO", "autopistas del sol": "AUSO",
    "banco hipotecario": "BHIP", "central costanera": "CECO2", "havanna": "HAVA", "capex": "CAPX",
    "y.p.f.": "YPFD", "vista energy": "VIST", "petroleo brasileiro": "PBR", "mercadolibre": "MELI",
}


def sin_acentos(t: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", str(t))
    return "".join(c for c in t if not unicodedata.combining(c)).lower().strip()


def leer(ruta: Path, defecto=None):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return defecto


def escribir(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


# ------------------------------------------------------------------ precios
def cargar_precios(carpeta: str | None) -> dict:
    """Une precios (mercado.json, más amplio: incluye acciones y CEDEAR) e instrumentos
    con vencimiento (datos.json) de la calculadora de renta fija."""
    def traer(archivo):
        if carpeta:
            return json.loads((Path(carpeta) / archivo).read_text(encoding="utf-8"))
        r = pedir(URL_CALCULADORA.format(archivo=archivo))
        r.raise_for_status()
        return r.json()

    datos, mercado = traer("datos.json"), traer("mercado.json")
    precios = {}
    for plazo in ("T0", "T1"):  # T1 pisa a T0: es el plazo de referencia
        for t, x in (datos.get("precios", {}).get(plazo) or {}).items():
            precios[t] = {"px": x.get("px"), "plazo": plazo, "operaciones": x.get("operaciones")}
    for t, x in (mercado.get("precios") or {}).items():
        precios.setdefault(t, {"px": x.get("px"), "plazo": "T1", "operaciones": x.get("operaciones")})
    for t, x in (datos.get("instrumentos") or {}).items():
        p = precios.setdefault(t, {})
        p.update(vto=x.get("vto"), descripcion=x.get("descripcion"), grupo=x.get("grupo"), isin=x.get("isin"))
    return {"fecha": datos.get("fecha_precios") or mercado.get("fecha"),
            "fuente": "BYMA Market Data End of Day, vía calculadora-renta-fija",
            "mep": (datos.get("mep") or {}).get("valor") or mercado.get("mep"),
            "ccl": mercado.get("ccl"), "precios": precios}


def ticker_de(activo: str, precios: dict) -> str | None:
    """'Lecap S13N6' -> S13N6 ; 'Bono Boncer 2027 TZXM7' -> TZXM7 ; 'YPF S.A.' -> YPFD."""
    for tok in reversed(re.findall(r"[A-Z][A-Z0-9]{2,6}", activo)):
        if any(c.isdigit() for c in tok) and tok in precios:
            return tok
    n = sin_acentos(activo)
    for nombre, t in ACCIONES.items():
        if n.startswith(nombre):
            return t
    return None


# ------------------------------------------------------------------ clasificación
def atado(activo: str, tipo: str | None) -> str:
    n, t = sin_acentos(activo), sin_acentos(tipo or "")
    if re.search(r"lecer|boncer|\btx\d|\btzx|\bx\d{2}[a-z]\d\b|\bdicp\b|\bparp\b|\bcuap\b", n):
        return "Inflación (CER)"
    if re.search(r"lelink|dollar linked|dolar linked|\bd\d{2}[a-z]\d\b|\btv\d", n) or "linked" in t:
        return "Dólar linked"
    if re.search(r"\bdual\b|\btt[mjsd]\d", n):
        return "Bonos duales (tasa fija o TAMAR)"
    if re.search(r"tamar|\btmf|\btm[a-z]\d|\btmve", n):
        return "Tasa TAMAR"
    if re.search(r"lecap|boncap|\bs\d{2}[a-z]\d\b|\bt\d{2}[a-z]\d\b|letra tesoro", n):
        return "Tasa fija (Tesoro)"
    if re.search(r"\bcheque|\bpagare|\bvcp\b|valores de corto plazo|\becheq|\bfactura", n):
        return "Cheques, pagarés y deuda PyME"
    if re.search(r"\betf\b|ishares|\bspy\b|powershares|\bqqq\b", n):
        return "Acciones del exterior"
    if re.search(r"\bclase [a-z0-9]\b", n) and "on " not in n[:3]:
        return "Otros fondos y fideicomisos"
    if "pzo fi" in n or "plazo fi" in n or "plazo fijo" in n:
        return "Plazo fijo en bancos"
    if "caucion" in n or "pase colocador" in n:
        return "Cauciones (préstamos de 1 a 7 días)"
    if n.startswith("on ") or "obligacion" in n:
        return "Deuda de empresas en dólares (ON)" if "dolar" in t else "Deuda de empresas (ON)"
    if "cedear" in n or ("participaciones accionarias" in t and "argentina" not in t):
        return "Acciones del exterior"
    if "participaciones accionarias" in t:
        return "Acciones argentinas"
    if n.startswith(("fci ", "ff ", "fid")) or "fideicomiso" in n:
        return "Otros fondos y fideicomisos"
    if "titulos de deuda en dolar" in t:
        return "Bonos en dólares"
    if re.search(r"\b(al|gd|ae|ao|an)\d{2}\b|bonos? rep|bonar|global", n):
        return "Bonos en dólares"
    if "bono" in n or "letra" in n:
        return "Otros bonos del Tesoro"
    return "Otros"


def subtipo(categoria: str, grupos: dict) -> str:
    c = sin_acentos(categoria or "")
    tot = sum(v for v in grupos.values() if v and v > 0) or 1
    def peso(*gs):
        return sum(grupos.get(g, 0) or 0 for g in gs) / tot * 100
    if "mercado de dinero" in c:
        return "Money market"
    if "renta variable" in c:
        return "Acciones del exterior" if peso("Acciones del exterior") > 50 else "Acciones argentinas"
    if "renta fija" in c and ("dolar" in c or "usd" in c):
        if peso("Deuda de empresas en dólares (ON)", "Deuda de empresas (ON)") > 50:
            return "Renta fija dólares: empresas (ON)"
        if peso("Bonos en dólares") > 50:
            return "Renta fija dólares: bonos soberanos"
        if peso("Dólar linked") > 50:
            return "Dólar linked"
        return "Renta fija dólares: mixta"
    if "renta fija" in c:
        for g, nombre in (("Inflación (CER)", "Renta fija CER"), ("Tasa fija (Tesoro)", "Renta fija tasa fija (Lecap)"),
                          ("Dólar linked", "Dólar linked"), ("Tasa TAMAR", "Renta fija TAMAR"),
                          ("Plazo fijo en bancos", "Renta fija corto plazo (T+1)"),
                          ("Cauciones (préstamos de 1 a 7 días)", "Renta fija corto plazo (T+1)")):
            if peso(g) > 50:
                return nombre
        if peso("Deuda de empresas (ON)") > 50:
            return "Renta fija pesos: empresas (ON)"
        return "Renta fija pesos: mixta"
    if "mixta" in c:
        return "Renta mixta"
    return categoria or "Otros"


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--precios-dir", help="Carpeta con datos.json y mercado.json de la calculadora")
    args = ap.parse_args()

    planilla = leer(DATA / "ultimo.json", {})
    clases = planilla.get("fondos", [])
    try:
        precios = cargar_precios(args.precios_dir)
        escribir(DATA / "precios" / "ultimo.json", precios)
    except Exception as e:  # sin precios igual se calcula el resto
        print(f"Precios BYMA no disponibles: {e}")
        precios = {"fecha": None, "precios": {}}
    P = precios["precios"]
    hoy = dt.date.fromisoformat(precios["fecha"]) if precios.get("fecha") else dt.date.today()

    # Fondo (clave) = suma de sus clases
    fondos = collections.defaultdict(lambda: {"patrimonio": 0.0, "flujo": 0.0, "clases": 0, "honorarios": 0.0})
    for c in clases:
        f = fondos[c.get("clave")]
        f["patrimonio"] += c.get("patrimonio") or 0
        f["flujo"] += c.get("flujo_neto_estimado") or 0
        f["clases"] += 1
        # Facturación anual estimada de la gestora: patrimonio de la clase x honorario anual
        f["honorarios"] += (c.get("patrimonio") or 0) * (c.get("honorarios_gerente") or 0) / 100
        for k in ("categoria", "gerente", "moneda"):
            f.setdefault(k, c.get(k))
        f.setdefault("nombre", c.get("fondo_base") or c.get("fondo"))

    salida, activos = {}, collections.defaultdict(lambda: {"fondos": [], "monto_estimado": 0.0})
    con_ticker = sin_ticker = 0
    for ruta in sorted((DATA / "carteras" / "ultima").glob("*.json")):
        cart = leer(ruta)
        if not cart or not cart.get("activos"):
            continue
        f = fondos.get(cart.get("clave"))
        # Algunas gestoras cargan mal los porcentajes en la CNV (suman miles de %): se marca y no se usa
        suma = sum(a.get("pct_pn") or 0 for a in cart["activos"])
        if suma > 130:
            salida[cart["id_cnv"]] = {"fondo": cart.get("fondo"), "clave": cart.get("clave"),
                                      "fecha_cartera": cart.get("fecha_cartera"),
                                      "error": f"La cartera publicada en la CNV suma {suma:.0f}% del patrimonio"}
            continue
        grupos, venc_suma, venc_peso, top = collections.Counter(), 0.0, 0.0, []
        for a in cart["activos"]:
            pct = a.get("pct_pn") or 0
            g = atado(a["activo"], a.get("tipo"))
            grupos[g] += pct
            tk = ticker_de(a["activo"], P)
            info = P.get(tk, {}) if tk else {}
            if tk:
                con_ticker += 1
            else:
                sin_ticker += 1
            vto = info.get("vto")
            if vto and pct > 0:
                anios = (dt.date.fromisoformat(vto) - hoy).days / 365
                if anios >= 0:
                    venc_suma += anios * pct
                    venc_peso += pct
            top.append({"activo": a["activo"], "ticker": tk, "pct": pct, "atado": g,
                        "precio": info.get("px"), "vto": vto})
            k = tk or (g if g == "Cheques, pagarés y deuda PyME" else a["activo"])
            idx = activos[k]
            idx.setdefault("nombre", a["activo"])
            if idx["fondos"] and idx["fondos"][-1]["id_cnv"] == cart["id_cnv"]:
                idx["fondos"][-1]["pct"] = round(idx["fondos"][-1]["pct"] + pct, 4)  # mismo activo agrupado
            else:
                idx["fondos"].append({"id_cnv": cart["id_cnv"], "fondo": cart.get("fondo"), "pct": pct})
            if f:
                idx["monto_estimado"] += f["patrimonio"] * pct / 100
        disp = next((t["pct_pn"] for t in cart.get("por_tipo", []) if t["tipo"] == "Disponibilidades" and t["pct_pn"]), None)
        if disp:
            grupos["Efectivo"] += disp
        grupos = {g: round(v, 2) for g, v in grupos.most_common() if round(v, 2)}
        categoria = (f or {}).get("categoria") or cart.get("clasificacion")
        salida[cart["id_cnv"]] = {
            "fondo": cart.get("fondo"), "clave": cart.get("clave"), "gerente": cart.get("gerente"),
            "categoria": categoria, "subtipo": subtipo(categoria, grupos),
            "fecha_cartera": cart.get("fecha_cartera"), "atado": grupos,
            "vencimiento_promedio_anios": round(venc_suma / venc_peso, 2) if venc_peso else None,
            "vencimiento_cobertura_pct": round(venc_peso, 1),
            "patrimonio": round(f["patrimonio"], 2) if f else None,
            "activos": sorted(top, key=lambda x: -x["pct"])[:15], "n_activos": len(top),
        }

    # Solo activos que tienen ticker o que están en 2 o más fondos (los demás son únicos, ej. un cheque)
    activos = {k: v for k, v in activos.items() if k in P or len(v["fondos"]) >= 2}
    for k, v in activos.items():
        v["fondos"].sort(key=lambda x: -x["pct"])
        v["cantidad_fondos"] = len(v["fondos"])
        v["monto_estimado"] = round(v["monto_estimado"], 2)
        if k in P:
            v.update({x: P[k].get(x) for x in ("px", "vto", "descripcion")})

    # Gestoras
    gest = collections.defaultdict(lambda: {"patrimonio": 0.0, "flujo_dia": 0.0, "fondos": 0, "clases": 0,
                                            "facturacion_anual_estimada": 0.0, "por_categoria": collections.Counter()})
    total = 0.0
    for f in fondos.values():
        if (f.get("moneda") or "ARS") != "ARS":
            continue  # se suma en pesos; los fondos en dólares van aparte para no mezclar monedas
        g = gest[f.get("gerente") or "Sin dato"]
        g["patrimonio"] += f["patrimonio"]; g["flujo_dia"] += f["flujo"]; g["fondos"] += 1
        g["clases"] += f["clases"]; g["facturacion_anual_estimada"] += f["honorarios"]
        g["por_categoria"][f.get("categoria") or "Otros"] += f["patrimonio"]
        total += f["patrimonio"]
    ranking = []
    for nombre, g in gest.items():
        ranking.append({"gerente": nombre, "patrimonio": round(g["patrimonio"], 2),
                        "market_share_pct": round(g["patrimonio"] / total * 100, 3) if total else None,
                        "flujo_dia": round(g["flujo_dia"], 2), "fondos": g["fondos"], "clases": g["clases"],
                        "facturacion_anual_estimada": round(g["facturacion_anual_estimada"], 2),
                        "por_categoria": {k: round(v, 2) for k, v in g["por_categoria"].most_common()}})
    ranking.sort(key=lambda x: -x["patrimonio"])
    for i, r in enumerate(ranking, 1):
        r["puesto"] = i

    fecha = planilla.get("fecha_datos")
    escribir(DATA / "analisis" / "fondos.json", {"fecha_datos": fecha, "fecha_precios": precios.get("fecha"), "fondos": salida})
    escribir(DATA / "analisis" / "activos.json", {"fecha_datos": fecha, "activos": dict(sorted(activos.items(), key=lambda x: -x[1]["monto_estimado"]))})
    escribir(DATA / "analisis" / "gestoras.json", {"fecha_datos": fecha, "moneda": "ARS",
                                                   "nota": "Solo fondos en pesos. Facturación = patrimonio x honorario de gestión anual.",
                                                   "gestoras": ranking})
    print(f"Fondos analizados: {len(salida)} | activos distintos: {len(activos)} | "
          f"tenencias con ticker BYMA: {con_ticker}, sin ticker: {sin_ticker} | gestoras: {len(ranking)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
