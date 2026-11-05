"""Arma los datos livianos que lee la página (index.html):

- data/web/catalogo.json: un renglón por fondo (no por clase) para el listado y el buscador.
- data/web/fondos/<id>.json: la ficha didáctica de cada fondo.
- data/web/referencias.json: inflación, plazo fijo y dólar para comparar rendimientos.

Corre después de actualizar.py, analisis.py e historico.py.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import re
import shutil
import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"
WEB = DATA / "web"


def leer(ruta: Path, defecto=None):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return defecto


def escribir(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def sano(v, limite):
    """Descarta rendimientos imposibles (cambio de unidad de la cuotaparte, fondo liquidándose)."""
    return v if v is not None and -90 <= v <= limite else None


def slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower().strip()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


# ------------------------------------------------------------------ referencias (BCRA)
def serie(nombre: str) -> list[tuple[dt.date, float]]:
    d = leer(DATA / "bcra" / f"{nombre}.json", {}) or {}
    out = []
    for x in d.get("serie", []):
        try:
            out.append((dt.date.fromisoformat(x["fecha"][:10]), float(x["valor"])))
        except (KeyError, TypeError, ValueError):
            pass
    return sorted(out)


def valor_en(s, fecha: dt.date):
    previos = [v for f, v in s if f <= fecha]
    return previos[-1] if previos else None


def referencias(hoy: dt.date) -> dict:
    infl_m, infl_a = serie("inflacion_mensual"), serie("inflacion_interanual")
    dolar, pf = serie("dolar_mayorista"), serie("tasa_plazo_fijo_30d")
    ref = {"fecha": hoy.isoformat(), "periodos": {}}

    def cambio(s, desde):
        a, b = valor_en(s, desde), (s[-1][1] if s else None)
        return round((b / a - 1) * 100, 2) if a and b else None

    def plazo_fijo(desde):
        # Renovar un plazo fijo a 30 días con la tasa de cada momento
        tasas = [v for f, v in pf if desde <= f <= hoy]
        if not tasas:
            return None
        dias = (hoy - desde).days
        tna = sum(tasas) / len(tasas)
        return round(((1 + tna / 100 * 30 / 365) ** (dias / 30) - 1) * 100, 2)

    def inflacion(desde):
        meses = [v for f, v in infl_m if f > desde]
        if not meses:
            return None, None
        acum = 1.0
        for v in meses:
            acum *= 1 + v / 100
        hasta = [f for f, v in infl_m if f > desde][-1]
        return round((acum - 1) * 100, 2), hasta.isoformat()

    for clave, desde in (("30d", hoy - dt.timedelta(days=30)), ("anio", dt.date(hoy.year - 1, 12, 31)),
                         ("1a", hoy - dt.timedelta(days=365)), ("2a", hoy - dt.timedelta(days=730))):
        inf, hasta = inflacion(desde)
        if clave == "1a" and infl_a:
            inf, hasta = infl_a[-1][1], infl_a[-1][0].isoformat()
        ref["periodos"][clave] = {"inflacion": inf, "inflacion_hasta": hasta,
                                  "plazo_fijo": plazo_fijo(desde), "dolar": cambio(dolar, desde)}
    def mensual_bcra(s):
        return mensual([(f, v) for f, v in s if f >= hoy - dt.timedelta(days=740)])
    ref["serie_cer"] = mensual_bcra(serie("cer"))
    ref["serie_dolar"] = mensual_bcra(dolar)
    ref["dolar_hoy"] = dolar[-1][1] if dolar else None
    ref["plazo_fijo_tna_hoy"] = pf[-1][1] if pf else None
    return ref


# ------------------------------------------------------------------ textos didácticos
TIPOS = {
    "Money market": ("Mercado de dinero (money market)", "Funciona como una cuenta remunerada: tu plata rinde todos los días y la rescatás en el día.", "bajo"),
    "Renta fija corto plazo (T+1)": ("Renta fija de corto plazo", "Invierte a muy corto plazo. Se mueve poco y rinde algo más que un money market.", "bajo"),
    "Renta fija CER": ("Renta fija atada a la inflación (CER)", "Compra bonos que ajustan por inflación. Sirve para cubrirse de la suba de precios.", "medio"),
    "Renta fija tasa fija (Lecap)": ("Renta fija a tasa fija", "Compra letras del Tesoro que pagan una tasa fija. Le va bien si la inflación baja.", "medio"),
    "Renta fija TAMAR": ("Renta fija a tasa variable (TAMAR)", "Compra deuda que paga una tasa que sigue a la de los plazos fijos grandes.", "medio"),
    "Dólar linked": ("Atado al dólar oficial (dólar linked)", "Compra bonos en pesos que ajustan por el dólar oficial. Sirve para cubrirse de una devaluación.", "medio"),
    "Renta fija pesos: empresas (ON)": ("Deuda de empresas en pesos", "Les presta a empresas a cambio de intereses.", "medio"),
    "Renta fija pesos: mixta": ("Renta fija en pesos", "Compra deuda en pesos de distinto tipo: te pagan intereses. Se mueve menos que las acciones.", "medio"),
    "Renta fija dólares: bonos soberanos": ("Bonos del Estado en dólares", "Invierte en bonos argentinos en dólares. Su precio acompaña al riesgo país.", "medio"),
    "Renta fija dólares: empresas (ON)": ("Deuda de empresas en dólares", "Les presta dólares a empresas a cambio de intereses.", "medio"),
    "Renta fija dólares: mixta": ("Renta fija en dólares", "Compra deuda en dólares de distinto tipo.", "medio"),
    "Acciones argentinas": ("Acciones argentinas", "Invierte en acciones de empresas argentinas, pensado para hacer crecer tu capital en varios años.", "alto"),
    "Acciones del exterior": ("Acciones del exterior", "Invierte en empresas de todo el mundo, a través de CEDEAR o ETF.", "alto"),
    "Renta mixta": ("Renta mixta", "Combina bonos y acciones para diversificar en un solo fondo.", "medio"),
    # Fondos sin cartera en la CNV: se clasifican por su categoría CAFCI (ver CATEGORIA_CAFCI)
    "PyMEs": ("Deuda de PyMEs", "Les presta a pequeñas y medianas empresas, sobre todo con cheques y pagarés. Por ley, la mayor parte tiene que ir a PyMEs.", "medio"),
    "Retorno total": ("Retorno total (el administrador elige)", "El administrador puede comprar de todo (bonos, acciones y más) buscando el mejor rendimiento.", "alto"),
    "Infraestructura": ("Infraestructura", "Financia obras y proyectos, como energía, rutas o viviendas. Es para varios años.", "medio"),
    "ASG": ("Sustentable (ASG)", "Invierte en empresas y proyectos que cumplen reglas ambientales, sociales y de buen gobierno.", "medio"),
    "Régimen especial": ("Fondo de régimen especial", "Fondo armado bajo una norma especial de la CNV, con reglas propias sobre en qué puede invertir.", "medio"),
    "Fondo cerrado": ("Fondo cerrado", "No podés entrar ni sacar la plata cuando quieras: se opera en la bolsa o se cobra cuando el fondo termina.", "alto"),
    "En liquidación": ("Fondo en liquidación", "El fondo está cerrando y devolviendo la plata a quienes ya estaban. Ya no se puede invertir.", "medio"),
    "En trámite": ("Fondo en trámite", "Todavía no empezó a funcionar.", "medio"),
}
# Categorías CAFCI tal como vienen en la planilla -> el tipo de arriba que les corresponde.
# Sin esto, un tercio de los fondos se mostraba con el nombre técnico ("Renta Fija Dolar Estadounidense Billete").
CATEGORIA_CAFCI = [
    (r"^en proceso de liquidaci", "En liquidación"),
    (r"^solicitud en tr", "En trámite"),
    (r"^fondos cerrados", "Fondo cerrado"),
    (r"^mercado de dinero", "Money market"),
    (r"^renta fija peso", "Renta fija pesos: mixta"),
    (r"^renta fija d[oó]lar", "Renta fija dólares: mixta"),
    (r"^renta mixta", "Renta mixta"),
    (r"^renta variable peso", "Acciones argentinas"),
    (r"^renta variable d[oó]lar", "Acciones del exterior"),
    (r"^pymes", "PyMEs"),
    (r"^retorno total", "Retorno total"),
    (r"^infraestructura", "Infraestructura"),
    (r"^asg", "ASG"),
    (r"^rg ?\d+", "Régimen especial"),
]
NO_DISPONIBLE = {"Fondo cerrado", "En liquidación", "En trámite"}


def tipo_de(sub: str | None) -> str | None:
    """Lleva una categoría CAFCI cruda a uno de los tipos explicados en TIPOS."""
    if not sub or sub in TIPOS:
        return sub
    for patron, destino in CATEGORIA_CAFCI:
        if re.search(patron, sub, re.I):
            return destino
    return sub
QUE_ES = {
    "Plazo fijo en bancos": "plazos fijos en bancos", "Cauciones (préstamos de 1 a 7 días)": "préstamos de muy corto plazo",
    "Inflación (CER)": "bonos que ajustan por inflación", "Tasa fija (Tesoro)": "letras del Tesoro a tasa fija",
    "Tasa TAMAR": "deuda que paga tasa TAMAR", "Dólar linked": "bonos atados al dólar oficial",
    "Bonos duales (tasa fija o TAMAR)": "bonos duales del Tesoro", "Deuda de empresas (ON)": "deuda de empresas",
    "Deuda de empresas en dólares (ON)": "deuda de empresas en dólares", "Bonos en dólares": "bonos en dólares",
    "Acciones argentinas": "acciones argentinas", "Acciones del exterior": "acciones del exterior",
    "Cheques, pagarés y deuda PyME": "cheques y pagarés de PyMEs", "Otros fondos y fideicomisos": "otros fondos",
    "Otros bonos del Tesoro": "otros bonos del Tesoro", "Efectivo": "efectivo",
}



MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def en_palabras(activo: str, atado: str | None, vto: str | None, tipo_activo: str | None = None) -> str:
    """'Lecer X30N6' -> 'Letra del Tesoro que ajusta por inflación, vence en noviembre de 2026'."""
    a = activo.strip()
    n = a.lower()
    vence = ""
    if vto:
        try:
            f = dt.date.fromisoformat(vto)
            vence = f", vence en {MESES[f.month - 1]} de {f.year}"
        except ValueError:
            pass
    usd = "u$s" in n or "usd" in n or "dolar" in n or "dólar" in n
    m = re.match(r"(?:pzo|plazo) ?fi\w*\s*(?:\$|u\$s|usd)?\s*(?:bco\.?|banco)?\s*(.*)", a, re.I)
    if m:
        banco = m.group(1).strip()
        for x, y in ((r"\bRi$", "Río"), (r"\bNacion\b", "Nación"), (r"\bNvo\b", "Nuevo"), (r"\bBco\b", "Banco"),
                     (r"\bIndus$", "Industrial"), (r"\bCdad\b", "Ciudad"), (r"\bBs\.? ?As\.?", "Buenos Aires")):
            banco = re.sub(x, y, banco)
        return f"Plazo fijo en {'dólares' if usd else 'pesos'} en el Banco {banco}".replace("Banco Banco", "Banco")
    if "caucion" in n or "caución" in n or "pase colocador" in n:
        return f"Préstamo de 1 a 7 días en la bolsa, en {'dólares' if usd else 'pesos'} (caución)"
    if n.startswith("fci ") or re.search(r" - clase [a-z0-9]", n):
        return "Otro fondo: " + re.sub(r"^FCI\s+", "", a, flags=re.I)
    if n.startswith("on "):
        return "Deuda de la empresa " + re.sub(r"\s+(C|Clase|Serie)\s*\w+.*$", "", a[3:], flags=re.I).strip()
    textos = {
        "Inflación (CER)": "Bono o letra del Tesoro que ajusta por inflación",
        "Tasa fija (Tesoro)": "Letra del Tesoro que paga una tasa fija",
        "Tasa TAMAR": "Bono que paga la tasa TAMAR de los bancos",
        "Dólar linked": "Letra del Tesoro atada al dólar oficial",
        "Bonos duales (tasa fija o TAMAR)": "Bono dual del Tesoro (paga tasa fija o TAMAR, la que sea mayor)",
        "Bonos en dólares": "Bono del Estado argentino en dólares",
        "Cheques, pagarés y deuda PyME": "Cheques y pagarés de empresas",
    }
    if atado in textos:
        return textos[atado] + vence
    if atado == "Acciones argentinas":
        return "Acciones de " + re.sub(r"\s+S\.?A\.?.*$", "", a)
    if atado == "Acciones del exterior":
        return "Acciones del exterior: " + a
    return a + vence


def frase(tipo: str, atado: dict) -> str:
    partes = [(g, v) for g, v in atado.items() if g in QUE_ES and g not in ("Efectivo",) and v >= 10][:2]
    if not partes:
        return ""
    txt = " y ".join(QUE_ES[g] for g, _ in partes)
    principal = partes[0][1]
    cuanto = "casi todo en" if principal >= 80 else "más que nada en" if principal >= 50 else "sobre todo en"
    return f"Invierte {cuanto} {txt}."



# ------------------------------------------------------------------ series de cuotaparte
def series_historicas(ids: set[str], desde: dt.date) -> dict[str, list[tuple[dt.date, float]]]:
    """Cuotaparte de esas clases en todas las fechas guardadas desde `desde`."""
    archivos = {}
    for carpeta in (DATA / "historico_ad", DATA / "historico"):  # la planilla propia pisa
        for p in carpeta.glob("*.json"):
            try:
                f = dt.date.fromisoformat(p.stem)
            except ValueError:
                continue
            if f >= desde:
                archivos[f] = p
    out = collections.defaultdict(list)
    for f in sorted(archivos):
        d = leer(archivos[f], {})
        if isinstance(d, dict):
            for i in ids & d.keys():
                v = d[i]
                if v and v[0]:
                    out[i].append((f, float(v[0])))
        else:
            for x in d:
                if x.get("id") in ids and x.get("vcp"):
                    out[x["id"]].append((f, float(x["vcp"])))
    return out


def mensual(s: list[tuple[dt.date, float]]) -> list[list]:
    """Último dato de cada mes + el último disponible."""
    por_mes = {}
    for f, v in s:
        por_mes[(f.year, f.month)] = (f, v)
    pts = [por_mes[k] for k in sorted(por_mes)]
    return [[f.isoformat(), round(v, 4)] for f, v in pts]


def riesgo_medido(s: list[tuple[dt.date, float]], hoy: dt.date):
    """Peor caída (desde un máximo) y volatilidad anual del último año, en %."""
    pts = [(f, v) for f, v in s if f >= hoy - dt.timedelta(days=365)]
    if len(pts) < 20:
        return None, None
    pico, peor = pts[0][1], 0.0
    for _, v in pts:
        pico = max(pico, v)
        peor = min(peor, v / pico - 1)
    import math
    rets = []
    for (f1, v1), (f2, v2) in zip(pts, pts[1:]):
        dias = max((f2 - f1).days, 1)
        if v1 > 0 and v2 > 0 and dias <= 10:
            rets.append(math.log(v2 / v1) / math.sqrt(dias))
    if len(rets) < 15:
        return round(peor * 100, 2), None
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    return round(peor * 100, 2), round(math.sqrt(var * 365) * 100, 2)


PARA_QUE = {
    "Money market": ("Para la plata que vas a usar pronto: sueldo, gastos del mes o un fondo de emergencia.", ["pronto"]),
    "Renta fija corto plazo (T+1)": ("Para plata que podés dejar algunas semanas o meses.", ["pronto", "anio"]),
    "Renta fija CER": ("Para ahorros de 6 meses o más que querés que no pierdan contra la inflación.", ["inflacion", "anio"]),
    "Renta fija tasa fija (Lecap)": ("Para ahorros de algunos meses si creés que la inflación va a bajar.", ["anio"]),
    "Renta fija TAMAR": ("Para ahorros de algunos meses, con una tasa que sigue a la de los bancos.", ["anio"]),
    "Dólar linked": ("Para cubrirte si pensás que el dólar oficial va a subir, sin comprar dólares.", ["dolar"]),
    "Renta fija pesos: empresas (ON)": ("Para ahorros de 1 año o más en pesos.", ["anio"]),
    "Renta fija pesos: mixta": ("Para ahorros en pesos de varios meses.", ["anio"]),
    "Renta fija dólares: bonos soberanos": ("Para hacer rendir tus dólares en uno o varios años.", ["dolar", "largo"]),
    "Renta fija dólares: empresas (ON)": ("Para hacer rendir dólares con deuda de empresas, a más de un año.", ["dolar", "largo"]),
    "Renta fija dólares: mixta": ("Para hacer rendir dólares.", ["dolar"]),
    "Acciones argentinas": ("Para hacer crecer tu capital en varios años.", ["largo"]),
    "Acciones del exterior": ("Para hacer crecer tu capital en varios años, con empresas de todo el mundo.", ["largo", "dolar"]),
    "Renta mixta": ("Para plata a mediano o largo plazo, con algo de bonos y algo de acciones.", ["largo"]),
    "PyMEs": ("Para ahorros en pesos de varios meses, prestándoles a empresas chicas y medianas.", ["anio"]),
    "Retorno total": ("Para plata a varios años, si aceptás que el administrador decida en qué invertir.", ["largo"]),
    "Infraestructura": ("Para plata que no vas a tocar en varios años.", ["largo"]),
    "ASG": ("Para ahorros de varios meses o más, con criterios sustentables.", ["anio"]),
    "Fondo cerrado": ("Para horizontes largos: no se rescata en cualquier momento.", []),
    "En liquidación": ("Ya no recibe inversiones: está devolviendo la plata.", []),
    "En trámite": ("Todavía no recibe inversiones.", []),
    "Régimen especial": ("Tiene reglas propias: antes de invertir, preguntá en tu banco o broker para qué sirve.", []),
}
NIVEL = {"bajo": 1, "medio": 3, "alto": 5}


def nivel_riesgo(sub: str, riesgo: str, vol):
    """1 a 5. Si hay volatilidad medida, manda el dato; si no, el tipo de fondo."""
    if vol is not None:
        return 1 if vol < 1.5 else 2 if vol < 5 else 3 if vol < 12 else 4 if vol < 25 else 5
    if sub == "Renta fija corto plazo (T+1)":
        return 2
    if sub == "Renta mixta":
        return 4
    return NIVEL.get(riesgo, 3)


# ------------------------------------------------------------------ main
def main() -> int:
    planilla = leer(DATA / "ultimo.json", {}) or {}
    clases = planilla.get("fondos", [])
    if not clases:
        print("Falta data/ultimo.json")
        return 1
    rend = (leer(DATA / "analisis" / "rendimientos.json", {}) or {}).get("fondos", {})
    carteras = {}
    for idc, c in ((leer(DATA / "analisis" / "fondos.json", {}) or {}).get("fondos", {})).items():
        if c.get("clave") and not c.get("error"):
            if c["clave"] not in carteras or c.get("n_activos", 0) > carteras[c["clave"]].get("n_activos", 0):
                carteras[c["clave"]] = dict(c, id_cnv=idc)
    fecha = planilla.get("fecha_datos") or dt.date.today().isoformat()
    hoy = dt.date.fromisoformat(fecha)

    grupos = collections.defaultdict(list)
    for c in clases:
        grupos[c.get("clave") or c["id"]].append(c)

    # Un fondo puede tener clases en pesos y en dólares: todo se suma en la moneda principal
    dolar_s = serie("dolar_mayorista")
    DOLAR = dolar_s[-1][1] if dolar_s else 1.0
    es_usd = lambda c: c.get("moneda") in ("USD", "USB")
    a_pesos = lambda c, v: (v or 0) * (DOLAR if es_usd(c) else 1)

    fondos = []
    for clave, cs in grupos.items():
        usd_main = sum(a_pesos(c, c.get("patrimonio")) for c in cs if es_usd(c)) > sum(a_pesos(c, c.get("patrimonio")) for c in cs if not es_usd(c))
        div = DOLAR if usd_main else 1.0
        conv = lambda c, v: a_pesos(c, v) / div
        pat = sum(conv(c, c.get("patrimonio")) for c in cs)
        principales = [c for c in cs if es_usd(c) == usd_main] or cs
        # La clase A es la que suelen comprar las personas, salvo que esté vacía (sin plata, cuotaparte quieta):
        # tomarla igual mostraba "+0,0% en 12 meses" en unos 190 fondos.
        ref = next((c for c in principales if re.search(r"clase a\b", c["fondo"], re.I) and (c.get("patrimonio") or 0) > 0), None) \
            or max(principales, key=lambda c: c.get("patrimonio") or 0)
        cart = carteras.get(clave)
        sub = tipo_de((cart or {}).get("subtipo") or ref.get("categoria"))
        tipo_nombre, tipo_expl, riesgo = TIPOS.get(sub, (sub or "Sin clasificar", "", None))
        if riesgo is None:
            cat = (ref.get("categoria") or "").lower()
            riesgo = "bajo" if "dinero" in cat else "alto" if "variable" in cat else "medio"
        r = rend.get(ref["id"], {})
        flujo_30 = sum(conv(c, (rend.get(c["id"], {}) or {}).get("flujo_30d")) for c in cs) if any("flujo_30d" in rend.get(c["id"], {}) for c in cs) else None
        fid = slug(ref.get("fondo_base") or clave)
        fondos.append({
            "id": fid, "nombre": ref.get("fondo_base") or ref["fondo"], "gerente": ref.get("gerente"),
            "categoria": ref.get("categoria"), "subtipo": sub, "tipo": tipo_nombre, "riesgo": riesgo,
            "moneda": "USD" if ref.get("moneda") in ("USD", "USB") else ref.get("moneda"), "plazo_rescate": ref.get("plazo_liquidacion"),
            "patrimonio": round(pat, 2), "rend_1a": r.get("1a", None if "1a" in r.get("dudoso", []) else sano(ref.get("rend_12m_pct"), 250)),
            "rend_anio": r.get("anio", None if "anio" in r.get("dudoso", []) else sano(ref.get("rend_anio_pct"), 200)), "rend_30d": r.get("30d"),
            "_clave": clave, "_div": div, "_cs": cs, "_ref": ref, "_cart": cart, "_r": r, "_flujo30": flujo_30,
            "_tipo_expl": tipo_expl,
        })

    series = series_historicas({f["_ref"]["id"] for f in fondos}, hoy - dt.timedelta(days=740))
    for f in fondos:
        s = series.get(f["_ref"]["id"], [])
        f["_serie"] = s
        peor, vol = riesgo_medido(s, hoy)
        f["peor_caida_1a"], f["volatilidad_1a"] = peor, vol
        f["riesgo_nivel"] = nivel_riesgo(f["subtipo"], f["riesgo"], vol)
        pq = PARA_QUE.get(f["subtipo"])
        f["disponible"] = f["subtipo"] not in NO_DISPONIBLE
        f["objetivos"] = (pq[1] if pq else []) + (["dolar"] if f["disponible"] and f["moneda"] == "USD" and (not pq or "dolar" not in pq[1]) else [])
        f["_para_que"] = pq[0] if pq else None

    # Puesto por tamaño dentro de su categoría CAFCI
    por_cat = collections.defaultdict(list)
    for f in fondos:
        por_cat[(f["categoria"], f["moneda"])].append(f)
    for lista in por_cat.values():
        lista.sort(key=lambda f: -f["patrimonio"])
        for i, f in enumerate(lista, 1):
            f["puesto"], f["en_categoria"] = i, len(lista)

    if (WEB / "fondos").exists():
        shutil.rmtree(WEB / "fondos")
    catalogo = []
    for f in sorted(fondos, key=lambda f: -f["patrimonio"]):
        ref, cart, r, cs = f.pop("_ref"), f.pop("_cart"), f.pop("_r"), f.pop("_cs")
        flujo30, expl = f.pop("_flujo30"), f.pop("_tipo_expl")
        f["flujo_30d_total"] = flujo30
        div_f = f.pop("_div")
        serie_f, para_que = f.pop("_serie"), f.pop("_para_que")
        f.pop("_clave")
        catalogo.append({k: f[k] for k in ("id", "nombre", "gerente", "tipo", "subtipo", "riesgo", "moneda",
                                           "plazo_rescate", "patrimonio", "rend_1a", "rend_anio",
                                           "riesgo_nivel", "objetivos", "disponible")})
        atado = (cart or {}).get("atado") or {}
        escribir(WEB / "fondos" / f"{f['id']}.json", {
            **f, "tipo_explicacion": expl, "para_que": para_que, "evolucion": mensual(serie_f), "frase": frase(f["subtipo"], atado),
            "horizonte": ref.get("horizonte"), "depositaria": ref.get("depositaria"),
            "flujo_dia": (round(sum(a_pesos(c, c.get("flujo_neto_estimado")) / div_f for c in cs), 2)
                          if any(c.get("flujo_neto_estimado") is not None for c in cs) else None),
            "flujo_30d": round(flujo30, 2) if flujo30 is not None else None,
            "rendimientos": {k: r.get(k) for k in ("7d", "30d", "anio", "1a", "2a", "2a_anual")},
            "rend_cafci": {"mes": ref.get("rend_mes_pct"), "anio": ref.get("rend_anio_pct"), "12m": ref.get("rend_12m_pct")},
            "cartera": None if not cart else {
                "fecha": cart.get("fecha_cartera"), "atado": atado, "n_activos": cart.get("n_activos"),
                "vencimiento_promedio_anios": cart.get("vencimiento_promedio_anios"),
                "vencimiento_cobertura_pct": cart.get("vencimiento_cobertura_pct"),
                "tasas": cart.get("tasas"),
                "principales": [{**{k: a.get(k) for k in ("activo", "ticker", "pct", "atado", "vto")},
                                 "en_palabras": en_palabras(a["activo"], a.get("atado"), a.get("vto"))}
                                for a in cart.get("activos", [])[:10]],
            },
            "clases": [{"nombre": c["fondo"], "moneda": "USD" if es_usd(c) else "ARS", "patrimonio": c.get("patrimonio"), "vcp": c.get("vcp"),
                        "honorarios_gerente": c.get("honorarios_gerente"), "honorarios_depositaria": c.get("honorarios_depositaria"),
                        "comision_ingreso": c.get("comision_ingreso"), "comision_rescate": c.get("comision_rescate"),
                        "minimo": c.get("minimo_inversion"), "rend_1a": (rend.get(c["id"]) or {}).get("1a", None if "1a" in (rend.get(c["id"]) or {}).get("dudoso", []) else sano(c.get("rend_12m_pct"), 250))}
                       for c in sorted(cs, key=lambda c: c["fondo"])],
        })

    escribir(WEB / "catalogo.json", {"fecha": fecha, "cantidad": len(catalogo), "fondos": catalogo})
    refs = referencias(hoy)
    escribir(WEB / "referencias.json", refs)
    tas = leer(DATA / "tasas" / "ultimo.json")
    if tas:
        escribir(WEB / "tasas.json", {"precios": tas.get("precios"), "fuente": tas.get("fuente"), "curvas": tas.get("curvas")})

    # Portada: a dónde fue la plata de la gente el último mes, por grupo simple
    def grupo(sub, mon):
        if mon == "USD" or "dólar" in (sub or "").lower():
            return "En dólares o atados al dólar"
        if sub in ("Money market", "Renta fija corto plazo (T+1)"):
            return "Money market y corto plazo"
        if (sub or "").startswith("Renta fija"):
            return "Renta fija en pesos"
        if "Acciones" in (sub or ""):
            return "Acciones"
        return "Mixtos y otros"
    dolar = refs.get("dolar_hoy") or 0
    res = collections.defaultdict(lambda: {"patrimonio": 0.0, "flujo_30d": 0.0, "fondos": 0})
    for f in fondos:
        g = res[grupo(f["subtipo"], f["moneda"])]
        k = dolar if f["moneda"] == "USD" else 1  # todo en pesos para poder sumar
        g["patrimonio"] += (f["patrimonio"] or 0) * k
        g["flujo_30d"] += (f.get("flujo_30d_total") or 0) * k
        g["fondos"] += 1
    escribir(WEB / "resumen.json", {"fecha": fecha, "moneda": "ARS", "dolar_usado": dolar,
                                    "grupos": sorted(({"grupo": k, **{x: round(y, 2) if isinstance(y, float) else y for x, y in v.items()}}
                                                      for k, v in res.items()), key=lambda g: -g["patrimonio"])})
    print(f"Web: {len(catalogo)} fondos, {sum(1 for f in fondos if f.get('subtipo'))} con subtipo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
