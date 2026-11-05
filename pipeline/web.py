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
    "Money market": ("Mercado de dinero (money market)", "Funciona como una cuenta remunerada: casi no baja y la plata se retira en el día.", "bajo"),
    "Renta fija corto plazo (T+1)": ("Renta fija de corto plazo", "Invierte a muy corto plazo. Se mueve poco y rinde algo más que un money market.", "bajo"),
    "Renta fija CER": ("Renta fija atada a la inflación (CER)", "Compra bonos que ajustan por inflación. Sirve para cubrirse de la suba de precios.", "medio"),
    "Renta fija tasa fija (Lecap)": ("Renta fija a tasa fija", "Compra letras del Tesoro que pagan una tasa fija. Le va bien si la inflación baja.", "medio"),
    "Renta fija TAMAR": ("Renta fija a tasa variable (TAMAR)", "Compra deuda que paga una tasa que sigue a la de los plazos fijos grandes.", "medio"),
    "Dólar linked": ("Atado al dólar oficial (dólar linked)", "Compra bonos en pesos que ajustan por el dólar oficial. Sirve para cubrirse de una devaluación.", "medio"),
    "Renta fija pesos: empresas (ON)": ("Deuda de empresas en pesos", "Les presta a empresas a cambio de intereses.", "medio"),
    "Renta fija pesos: mixta": ("Renta fija en pesos", "Compra deuda en pesos de distinto tipo: te pagan intereses. Se mueve menos que las acciones.", "medio"),
    "Renta fija dólares: bonos soberanos": ("Bonos del Estado en dólares", "Compra bonos argentinos en dólares. Puede subir o bajar según el riesgo país.", "medio"),
    "Renta fija dólares: empresas (ON)": ("Deuda de empresas en dólares", "Les presta dólares a empresas a cambio de intereses.", "medio"),
    "Renta fija dólares: mixta": ("Renta fija en dólares", "Compra deuda en dólares de distinto tipo.", "medio"),
    "Acciones argentinas": ("Acciones argentinas", "Compra partes de empresas argentinas. Gana o pierde según la bolsa: es para varios años.", "alto"),
    "Acciones del exterior": ("Acciones del exterior", "Compra acciones de afuera (CEDEAR o ETF). Gana o pierde según la bolsa y el dólar.", "alto"),
    "Renta mixta": ("Renta mixta", "Combina bonos y acciones. Se mueve más que la renta fija y menos que las acciones.", "medio"),
}
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


def frase(tipo: str, atado: dict) -> str:
    partes = [(g, v) for g, v in atado.items() if g in QUE_ES and g not in ("Efectivo",) and v >= 10][:2]
    if not partes:
        return ""
    txt = " y ".join(QUE_ES[g] for g, _ in partes)
    principal = partes[0][1]
    cuanto = "casi todo en" if principal >= 80 else "más que nada en" if principal >= 50 else "sobre todo en"
    return f"Junta la plata de muchos ahorristas y la invierte {cuanto} {txt}."



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
    "Renta fija dólares: bonos soberanos": ("Para hacer rendir dólares durante uno o varios años, aceptando subas y bajas.", ["dolar", "largo"]),
    "Renta fija dólares: empresas (ON)": ("Para hacer rendir dólares con deuda de empresas, a más de un año.", ["dolar", "largo"]),
    "Renta fija dólares: mixta": ("Para hacer rendir dólares.", ["dolar"]),
    "Acciones argentinas": ("Para plata que no vas a tocar en varios años y aguanta caídas fuertes.", ["largo"]),
    "Acciones del exterior": ("Para plata a varios años, invertida en empresas de afuera.", ["largo", "dolar"]),
    "Renta mixta": ("Para plata a mediano o largo plazo, con algo de bonos y algo de acciones.", ["largo"]),
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

    fondos = []
    for clave, cs in grupos.items():
        pat = sum(c.get("patrimonio") or 0 for c in cs)
        ref = next((c for c in cs if re.search(r"clase a\b", c["fondo"], re.I)), None) or max(cs, key=lambda c: c.get("patrimonio") or 0)
        cart = carteras.get(clave)
        sub = (cart or {}).get("subtipo") or ref.get("categoria")
        tipo_nombre, tipo_expl, riesgo = TIPOS.get(sub, (sub or "Sin clasificar", "", None))
        if riesgo is None:
            cat = (ref.get("categoria") or "").lower()
            riesgo = "bajo" if "dinero" in cat else "alto" if "variable" in cat else "medio"
        r = rend.get(ref["id"], {})
        flujo_30 = sum((rend.get(c["id"], {}) or {}).get("flujo_30d") or 0 for c in cs) if any("flujo_30d" in rend.get(c["id"], {}) for c in cs) else None
        fid = slug(ref.get("fondo_base") or clave)
        fondos.append({
            "id": fid, "nombre": ref.get("fondo_base") or ref["fondo"], "gerente": ref.get("gerente"),
            "categoria": ref.get("categoria"), "subtipo": sub, "tipo": tipo_nombre, "riesgo": riesgo,
            "moneda": ref.get("moneda"), "plazo_rescate": ref.get("plazo_liquidacion"),
            "patrimonio": round(pat, 2), "rend_1a": r.get("1a", ref.get("rend_12m_pct")),
            "rend_anio": r.get("anio", ref.get("rend_anio_pct")), "rend_30d": r.get("30d"),
            "_clave": clave, "_cs": cs, "_ref": ref, "_cart": cart, "_r": r, "_flujo30": flujo_30,
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
        f["objetivos"] = (pq[1] if pq else []) + (["dolar"] if f["moneda"] == "USD" and (not pq or "dolar" not in pq[1]) else [])
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
        serie_f, para_que = f.pop("_serie"), f.pop("_para_que")
        f.pop("_clave")
        catalogo.append({k: f[k] for k in ("id", "nombre", "gerente", "tipo", "subtipo", "riesgo", "moneda",
                                           "plazo_rescate", "patrimonio", "rend_1a", "rend_anio",
                                           "riesgo_nivel", "objetivos")})
        atado = (cart or {}).get("atado") or {}
        escribir(WEB / "fondos" / f"{f['id']}.json", {
            **f, "tipo_explicacion": expl, "para_que": para_que, "evolucion": mensual(serie_f), "frase": frase(f["subtipo"], atado),
            "horizonte": ref.get("horizonte"), "depositaria": ref.get("depositaria"),
            "flujo_dia": (round(sum(c.get("flujo_neto_estimado") or 0 for c in cs), 2)
                          if any(c.get("flujo_neto_estimado") is not None for c in cs) else None),
            "flujo_30d": round(flujo30, 2) if flujo30 is not None else None,
            "rendimientos": {k: r.get(k) for k in ("7d", "30d", "anio", "1a", "2a", "2a_anual")},
            "rend_cafci": {"mes": ref.get("rend_mes_pct"), "anio": ref.get("rend_anio_pct"), "12m": ref.get("rend_12m_pct")},
            "cartera": None if not cart else {
                "fecha": cart.get("fecha_cartera"), "atado": atado, "n_activos": cart.get("n_activos"),
                "vencimiento_promedio_anios": cart.get("vencimiento_promedio_anios"),
                "vencimiento_cobertura_pct": cart.get("vencimiento_cobertura_pct"),
                "principales": [{k: a.get(k) for k in ("activo", "ticker", "pct", "atado")} for a in cart.get("activos", [])[:10]],
            },
            "clases": [{"nombre": c["fondo"], "patrimonio": c.get("patrimonio"), "vcp": c.get("vcp"),
                        "honorarios_gerente": c.get("honorarios_gerente"), "honorarios_depositaria": c.get("honorarios_depositaria"),
                        "comision_ingreso": c.get("comision_ingreso"), "comision_rescate": c.get("comision_rescate"),
                        "minimo": c.get("minimo_inversion"), "rend_1a": (rend.get(c["id"]) or {}).get("1a", c.get("rend_12m_pct"))}
                       for c in sorted(cs, key=lambda c: c["fondo"])],
        })

    escribir(WEB / "catalogo.json", {"fecha": fecha, "cantidad": len(catalogo), "fondos": catalogo})
    escribir(WEB / "referencias.json", referencias(hoy))
    print(f"Web: {len(catalogo)} fondos, {sum(1 for f in fondos if f.get('subtipo'))} con subtipo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
