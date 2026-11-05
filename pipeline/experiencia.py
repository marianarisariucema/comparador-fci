"""Datos para explicarle cada fondo a alguien que no sabe de finanzas.

Genera, por cada fondo de data/web/fondos/<id>.json, el archivo data/web/experiencia/<id>.json con:

- movimiento: cuánto se movió hoy el fondo contra la mediana de su grupo y una frase
  ("fue el mercado" o "fue algo de este fondo").
- costo: honorarios de cada clase pasados a pesos por cada $1.000.000 al año, y si otra clase
  del mismo fondo cobra menos.
- senales: avisos con reglas fijas (salen inversores, fondo chico, mucho en un activo, cartera vieja,
  fondo nuevo, cambió de estrategia). Son hechos, no recomendaciones.
- rescate: días hábiles hasta cobrar (la fecha concreta la calcula la página con data/web/feriados.json).
- parecidos: fondos del mismo grupo con mucha cartera en común (% de la cartera que comparten).
- dudoso: clases con datos que no tienen sentido, para no mostrarlos.

Además:
- data/web/feriados.json: feriados nacionales del año (ArgentinaDatos). Si no se puede bajar, queda el último.
- data/precios/historico/<fecha>.json: precio de cada ticker del día, para explicar más adelante
  qué activo movió al fondo.
- data/web/experiencia/_resumen.json: totales de cada señal, para controlar que las reglas no se disparen de más.

Corre después de web.py. No usa nada de 1816 ni de Fonditos.
"""
from __future__ import annotations

import collections
import datetime as dt
import itertools
import json
import re
import shutil
import statistics
import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"
WEB = DATA / "web"
SALIDA = WEB / "experiencia"
FERIADOS_URL = "https://api.argentinadatos.com/v1/feriados/{anio}"
HEADERS = {"User-Agent": "comparador-fci/0.1 (+https://github.com/marianarisariucema/comparador-fci)"}

# Reglas de las señales (iguales para todos los fondos)
SALIDA_30D = -0.15        # rescates netos de más del 15% del patrimonio en 30 días
ENTRADA_30D = 0.30        # suscripciones netas de más del 30% en 30 días
FONDO_CHICO = 1e9         # patrimonio menor a $1.000 millones (solo fondos en pesos)
FONDO_CHICO_USD = 1e6     # patrimonio menor a USD 1 millón
UN_ACTIVO = 30.0          # un solo activo pesa más de 30%
CARTERA_VIEJA_DIAS = 30   # la CNV no publica cartera hace más de 30 días
FONDO_NUEVO_DIAS = 365    # menos de un año de historia
CAMBIO_CARTERA = 40.0     # la cartera cambió más de 40% desde la anterior
MOVIMIENTO_MIN = 0.5      # solo explicar movimientos del día de más de 0,5%
PARECIDO_MIN = 40.0       # fondos con al menos 40% de cartera en común
MILLON = 1_000_000
MINIMO_MINORISTA = 10_000_000  # clases con mínimo mayor a esto son para inversores grandes
# Grupos donde los fondos compran cosas parecidas: ahí sí se puede decir "fue algo propio de este fondo".
# En los grupos mixtos (renta mixta, renta fija mixta, retorno total) cada fondo hace algo distinto.
GRUPOS_PAREJOS = {
    "Money market", "Renta fija CER", "Renta fija tasa fija (Lecap)", "Renta fija TAMAR", "Dólar linked",
    "Renta fija dólares: bonos soberanos", "Renta fija dólares: empresas (ON)", "Renta fija pesos: empresas (ON)",
    "Acciones argentinas", "Acciones del exterior",
}


def leer(ruta: Path, defecto=None):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return defecto


def escribir(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def slug(texto: str) -> str:  # igual que pipeline/web.py
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower().strip()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def pct(v: float) -> str:
    """1.234 -> '1,2%', 0.55 -> '0,55%' (formato argentino)."""
    t = f"{abs(v):.2f}" if abs(v) < 1 else f"{abs(v):.1f}"
    return t.rstrip("0").rstrip(".").replace(".", ",") + "%"


def pesos(v: float) -> str:
    return "$" + f"{round(v):,}".replace(",", ".")


# ------------------------------------------------------------------ feriados
def feriados(anio: int) -> list[str]:
    destino = WEB / "feriados.json"
    previo = leer(destino, {}) or {}
    try:
        import requests
        fechas = []
        for a in (anio, anio + 1):
            r = requests.get(FERIADOS_URL.format(anio=a), headers=HEADERS, timeout=30)
            r.raise_for_status()
            fechas += [x["fecha"] for x in r.json() if x.get("fecha")]
        fechas = sorted(set(fechas))
        escribir(destino, {"fuente": "ArgentinaDatos", "actualizado": dt.date.today().isoformat(), "feriados": fechas})
        return fechas
    except Exception as e:  # sin red: seguimos con lo último que se bajó
        print(f"Feriados: no se pudieron bajar ({e}); uso los guardados.")
        return previo.get("feriados", [])


def dias_habiles_despues(desde: dt.date, n: int, feriados_: set[str]) -> dt.date:
    d = desde
    while n > 0:
        d += dt.timedelta(days=1)
        if d.weekday() < 5 and d.isoformat() not in feriados_:
            n -= 1
    return d


# ------------------------------------------------------------------ piezas
def clave_activo(a: dict) -> str:
    if a.get("ticker"):
        return a["ticker"].upper()
    return re.sub(r"\s+", " ", slug(a.get("activo", "")).replace("-", " ")).strip()


def vector(cartera: dict, por_nombre: bool = False) -> collections.Counter:
    """% de la cartera por activo. por_nombre=True ignora el ticker (las carteras históricas no lo tienen)."""
    v = collections.Counter()
    for a in cartera.get("activos", []):
        p = a.get("pct", a.get("pct_pn"))
        if p is not None and p > 0:
            v[clave_activo({"activo": a.get("activo")} if por_nombre else a)] += p
    return v


def en_comun(a: collections.Counter, b: collections.Counter) -> float:
    return sum(min(a[k], b[k]) for k in a.keys() & b.keys())


def honorario(c: dict) -> float | None:
    g, d = c.get("honorarios_gerente"), c.get("honorarios_depositaria")
    if g is None and d is None:
        return None
    return round((g or 0) + (d or 0), 4)


def dudosa(c: dict) -> str | None:
    r, v = c.get("rend_12m_pct"), c.get("variacion_pct")
    if r is not None and (r > 300 or r < -90):
        return f"rendimiento de 12 meses de {r}%"
    if v is not None and abs(v) > 20:
        return f"variación de un día de {v}%"
    return None


def primera_fecha_por_clase() -> dict[str, str]:
    """Primera fecha en la que aparece cada clase (ArgentinaDatos + planilla propia)."""
    primera = {}
    for carpeta in (DATA / "historico_ad", DATA / "historico"):
        for f in sorted(carpeta.glob("*.json")):
            datos = leer(f, {}) or {}
            if isinstance(datos, list):  # planilla propia: lista de clases
                ids = [x.get("id") for x in datos]
            elif "fondos" in datos:
                ids = [x.get("id") for x in datos["fondos"]]
            else:  # ArgentinaDatos: {id: [vcp, patrimonio]}
                ids = datos.keys()
            for i in ids:
                if i and i not in primera:
                    primera[i] = f.stem
    return primera


def cartera_anterior(id_cnv: str, fecha_actual: str) -> dict | None:
    base = DATA / "carteras" / "historico"
    if not base.exists():
        return None
    for carpeta in sorted((p for p in base.iterdir() if p.is_dir() and p.name < fecha_actual), reverse=True)[:6]:
        c = leer(carpeta / f"{id_cnv}.json")
        if c and c.get("activos"):
            return c
    return None


def guardar_precios_del_dia() -> None:
    p = leer(DATA / "precios" / "ultimo.json", {}) or {}
    if p.get("fecha") and p.get("precios"):
        escribir(DATA / "precios" / "historico" / f"{p['fecha']}.json",
                 {t: x.get("px") for t, x in p["precios"].items() if x.get("px") is not None})


# ------------------------------------------------------------------ main
def main() -> int:
    planilla = leer(DATA / "ultimo.json", {}) or {}
    clases = planilla.get("fondos", [])
    fondos_web = {f.stem: leer(f) for f in (WEB / "fondos").glob("*.json")}
    if not clases or not fondos_web:
        print("Faltan data/ultimo.json o data/web/fondos (correr antes actualizar.py y web.py)")
        return 1
    fecha = planilla.get("fecha_datos") or max((c.get("fecha") or "") for c in clases) or dt.date.today().isoformat()
    hoy = dt.date.fromisoformat(fecha[:10])
    fer = set(feriados(hoy.year))
    guardar_precios_del_dia()
    rend = (leer(DATA / "analisis" / "rendimientos.json", {}) or {}).get("fondos", {})

    # Clases de cada fondo de la página (mismo agrupamiento que web.py: por "clave")
    por_clave = collections.defaultdict(list)
    for c in clases:
        por_clave[c.get("clave") or c["id"]].append(c)
    clases_de, clave_de = {}, {}
    for clave, cs in por_clave.items():
        ref = next((c for c in cs if re.search(r"clase a\b", c["fondo"], re.I)), None) or max(cs, key=lambda c: c.get("patrimonio") or 0)
        fid = slug(ref.get("fondo_base") or clave)
        if fid in fondos_web:
            clases_de[fid], clave_de[fid] = cs, clave

    # Carteras por clave (la de más activos si hay varias)
    carteras = {}
    for idc, c in ((leer(DATA / "analisis" / "fondos.json", {}) or {}).get("fondos", {})).items():
        if c.get("clave") and not c.get("error") and c.get("activos"):
            if c["clave"] not in carteras or c.get("n_activos", 0) > carteras[c["clave"]].get("n_activos", 0):
                carteras[c["clave"]] = dict(c, id_cnv=idc)

    # Movimiento del día: variación de la clase más grande de cada fondo, contra la mediana de su grupo
    var_fondo = {}
    for fid, cs in clases_de.items():
        grande = max(cs, key=lambda c: c.get("patrimonio") or 0)
        v = grande.get("variacion_pct")
        if v is not None and not dudosa(grande) and grande.get("fecha") == fecha[:10]:
            var_fondo[fid] = v
    grupo_de = {fid: (f.get("subtipo") or f.get("categoria"), f.get("moneda")) for fid, f in fondos_web.items()}
    por_grupo = collections.defaultdict(list)
    for fid, v in var_fondo.items():
        por_grupo[grupo_de[fid]].append(v)
    mediana = {g: statistics.median(vs) for g, vs in por_grupo.items() if len(vs) >= 5}

    # Fondos parecidos (mismo grupo, cartera en común)
    vectores = {fid: vector(carteras[clave_de[fid]]) for fid in clases_de if clave_de[fid] in carteras}
    parecidos = collections.defaultdict(list)
    grupos_cartera = collections.defaultdict(list)
    for fid in vectores:
        grupos_cartera[grupo_de[fid]].append(fid)
    for ids in grupos_cartera.values():
        for a, b in itertools.combinations(ids, 2):
            o = en_comun(vectores[a], vectores[b])
            if o >= PARECIDO_MIN:
                parecidos[a].append((o, b))
                parecidos[b].append((o, a))

    primera = primera_fecha_por_clase()
    if SALIDA.exists():
        shutil.rmtree(SALIDA)
    resumen = collections.Counter()

    for fid, f in fondos_web.items():
        cs = clases_de.get(fid, [])
        cart = carteras.get(clave_de.get(fid))
        moneda = f.get("moneda") or "ARS"
        out = {"id": fid, "fecha": fecha[:10]}

        # 1. Movimiento del día
        v, g = var_fondo.get(fid), grupo_de.get(fid)
        if v is not None and abs(v) >= MOVIMIENTO_MIN and g in mediana:
            m = mediana[g]
            verbo = "subió" if v > 0 else "bajó"
            parecido = (v > 0) == (m > 0) and abs(v - m) <= max(0.5, abs(v) / 2)
            if not parecido and g[0] not in GRUPOS_PAREJOS:
                texto = None  # grupo mixto: no alcanza para decir que fue algo propio
            elif parecido:
                texto = (f"Hoy {verbo} {pct(v)}. Los fondos de su mismo tipo {'subieron' if m > 0 else 'bajaron'} "
                         f"en promedio {pct(m)}: fue un movimiento del mercado, no algo propio de este fondo.")
            else:
                texto = (f"Hoy {verbo} {pct(v)} y los fondos de su mismo tipo se movieron {pct(m)} "
                         f"{'para arriba' if m > 0 else 'para abajo'}. Fue algo propio de este fondo: puede ser un activo "
                         f"que tiene y que se movió fuerte, o muchos rescates en el día.")
        if v is not None and abs(v) >= MOVIMIENTO_MIN and g in mediana and texto:
            out["movimiento"] = {"variacion": v, "grupo": round(m, 3), "fondos_en_grupo": len(por_grupo[g]),
                                 "explicacion": "mercado" if parecido else "propio", "texto": texto}
            resumen["movimiento_" + ("mercado" if parecido else "propio")] += 1

        # 2. Costo en pesos
        costos = []
        for c in cs:
            h = honorario(c)
            if h is None or not c.get("patrimonio"):  # clases vacías no cuentan
                continue
            costos.append({"clase": c["fondo"], "honorarios_pct": h, "costo_por_millon": round(h / 100 * MILLON),
                           "minimo": c.get("minimo_inversion"), "comision_ingreso": c.get("comision_ingreso"),
                           "comision_rescate": c.get("comision_rescate"), "rend_1a": (rend.get(c["id"]) or {}).get("1a", c.get("rend_12m_pct")),
                           "patrimonio": c.get("patrimonio")})
        if costos:
            costos.sort(key=lambda x: x["honorarios_pct"])
            for x in costos:
                x["para_minoristas"] = x["minimo"] is None or x["minimo"] <= MINIMO_MINORISTA
            minoristas = [x for x in costos if x["para_minoristas"]] or costos
            barata, cara = minoristas[0], minoristas[-1]
            out["costo"] = {"moneda": moneda, "por_clase": costos}
            if cara["honorarios_pct"] - barata["honorarios_pct"] >= 0.5:
                out["costo"]["diferencia_max_pct"] = round(cara["honorarios_pct"] - barata["honorarios_pct"], 4)
                out["costo"]["texto"] = (f"Las clases de este fondo invierten en lo mismo pero cobran distinto: "
                                         f"de {pct(barata['honorarios_pct'])} a {pct(cara['honorarios_pct'])} por año. "
                                         f"Por cada {pesos(MILLON) if moneda == 'ARS' else 'USD 1.000.000'} son "
                                         f"{pesos(barata['costo_por_millon']) if moneda == 'ARS' else 'USD ' + str(barata['costo_por_millon'])} contra "
                                         f"{pesos(cara['costo_por_millon']) if moneda == 'ARS' else 'USD ' + str(cara['costo_por_millon'])}. "
                                         f"Consultá qué clase podés comprar.")
                resumen["clase_mas_barata"] += 1

        # 3. Señales
        senales = []
        pat = f.get("patrimonio") or 0
        flujo30 = f.get("flujo_30d")
        if flujo30 is not None and pat > 0:
            prop = flujo30 / (pat - flujo30) if pat - flujo30 > 0 else None
            if prop is not None and prop <= SALIDA_30D:
                senales.append({"tipo": "salen_inversores", "nivel": "atencion", "valor": round(prop * 100, 1),
                                "texto": f"En el último mes los inversores sacaron cerca del {pct(prop * 100)} de la plata del fondo."})
            elif prop is not None and prop >= ENTRADA_30D:
                senales.append({"tipo": "entran_inversores", "nivel": "info", "valor": round(prop * 100, 1),
                                "texto": f"En el último mes entró mucha plata nueva: cerca de {pct(prop * 100)} más."})
        chico = FONDO_CHICO if moneda == "ARS" else FONDO_CHICO_USD
        if 0 < pat < chico:
            senales.append({"tipo": "fondo_chico", "nivel": "atencion",
                            "texto": "Es un fondo chico: si varios inversores sacan la plata a la vez, puede moverse más."})
        if cart:
            top = max(cart["activos"], key=lambda a: a.get("pct") or 0)
            if (top.get("pct") or 0) > UN_ACTIVO and top.get("atado") not in ("Efectivo",):
                senales.append({"tipo": "un_activo", "nivel": "atencion", "valor": top["pct"], "activo": top.get("ticker") or top.get("activo"),
                                "texto": f"El {pct(top['pct'])} está en un solo activo ({top.get('ticker') or top.get('activo')})."})
            fc = cart.get("fecha_cartera")
            if fc:
                dias = (hoy - dt.date.fromisoformat(fc[:10])).days
                if dias > CARTERA_VIEJA_DIAS:
                    senales.append({"tipo": "cartera_vieja", "nivel": "info", "valor": dias,
                                    "texto": f"Lo que tiene adentro es lo último que publicó la CNV, del {dt.date.fromisoformat(fc[:10]):%d/%m/%Y}."})
            ant = cartera_anterior(cart["id_cnv"], fc or fecha)
            if ant:
                cambio = 100 - en_comun(vector(cart, True), vector(ant, True))
                if cambio > CAMBIO_CARTERA:
                    senales.append({"tipo": "cambio_cartera", "nivel": "info", "valor": round(cambio, 1),
                                    "texto": f"Desde la cartera anterior cambió cerca del {pct(cambio)} de lo que tiene."})
        else:
            senales.append({"tipo": "sin_cartera", "nivel": "info",
                            "texto": "La CNV no tiene publicada la cartera de este fondo: no podemos mostrar qué tiene adentro."})
        desde = min((primera[c["id"]] for c in cs if c["id"] in primera), default=None)
        con_un_anio = any((rend.get(c["id"]) or {}).get("1a") is not None or c.get("rend_12m_pct") is not None for c in cs)
        if desde and not con_un_anio and (hoy - dt.date.fromisoformat(desde)).days < FONDO_NUEVO_DIAS:
            senales.append({"tipo": "fondo_nuevo", "nivel": "info",
                            "texto": "Todavía no hay un año de datos de este fondo: no se puede ver cómo le va en momentos malos."})
        out["senales"] = senales
        for s in senales:
            resumen[s["tipo"]] += 1

        # 4. Rescate
        try:
            n = int(f.get("plazo_rescate"))
        except (TypeError, ValueError):
            n = None
        if n is not None and 0 <= n <= 10:
            ej = dias_habiles_despues(hoy, n, fer) if n else hoy
            out["rescate"] = {"dias_habiles": n,
                              "texto": ("La plata vuelve el mismo día en que pedís el rescate." if n == 0 else
                                        f"La plata vuelve {n} día{'s' if n > 1 else ''} hábil{'es' if n > 1 else ''} después de pedir el rescate."),
                              "ejemplo": {"pedido": hoy.isoformat(), "cobro": ej.isoformat()}}

        # 5. Parecidos
        if parecidos.get(fid):
            out["parecidos"] = [{"id": b, "nombre": fondos_web[b].get("nombre"), "gerente": fondos_web[b].get("gerente"),
                                 "en_comun_pct": round(o, 1)} for o, b in sorted(parecidos[fid], reverse=True)[:3]]
            resumen["con_parecidos"] += 1

        # 6. Datos dudosos
        malas = [{"clase": c["fondo"], "motivo": dudosa(c)} for c in cs if dudosa(c)]
        if malas:
            out["dudoso"] = malas
            resumen["dudoso"] += 1

        escribir(SALIDA / f"{fid}.json", out)

    escribir(SALIDA / "_resumen.json", {"fecha": fecha[:10], "fondos": len(fondos_web), "totales": dict(resumen),
                                        "reglas": {"salida_30d": SALIDA_30D, "entrada_30d": ENTRADA_30D, "fondo_chico_ars": FONDO_CHICO,
                                                   "fondo_chico_usd": FONDO_CHICO_USD, "un_activo_pct": UN_ACTIVO,
                                                   "cartera_vieja_dias": CARTERA_VIEJA_DIAS, "fondo_nuevo_dias": FONDO_NUEVO_DIAS,
                                                   "cambio_cartera_pct": CAMBIO_CARTERA, "movimiento_min_pct": MOVIMIENTO_MIN,
                                                   "parecido_min_pct": PARECIDO_MIN}})
    print(f"Experiencia: {len(fondos_web)} fondos. " + ", ".join(f"{k}={v}" for k, v in sorted(resumen.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
