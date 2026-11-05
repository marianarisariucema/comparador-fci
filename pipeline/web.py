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
        f.pop("_clave")
        catalogo.append({k: f[k] for k in ("id", "nombre", "gerente", "tipo", "subtipo", "riesgo", "moneda",
                                           "plazo_rescate", "patrimonio", "rend_1a", "rend_anio")})
        atado = (cart or {}).get("atado") or {}
        escribir(WEB / "fondos" / f"{f['id']}.json", {
            **f, "tipo_explicacion": expl, "frase": frase(f["subtipo"], atado),
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
