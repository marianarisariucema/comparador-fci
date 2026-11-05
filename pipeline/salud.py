"""Chequeo diario de salud del comparador: revisa los datos, repara lo que puede
y avisa solo cuando hace falta una persona.

Lo corre .github/workflows/vigilancia.yml (GitHub Actions, sin Claude ni claves):
  - apenas termina cada corrida de datos o carteras (para reintentar enseguida),
  - a las 2:30 de la madrugada (por si la corrida de la noche nunca arrancó),
  - a las 7:00 (veredicto final: si sigue roto, abre un aviso).

Qué revisa:
  planilla CAFCI al día, cantidad de clases, calidad (cuotapartes, patrimonios,
  saltos raros), columnas de la planilla, series del BCRA, carteras CNV, precios
  BYMA, rendimientos, datos de la página, lo publicado en GitHub Pages, el estado
  de los workflows y el tamaño del repo.

Qué repara solo:
  si los datos del día faltan o quedaron a medias, vuelve a lanzar el workflow
  correspondiente (como mucho 2 veces por día para no entrar en un bucle).

Cómo avisa:
  abre un issue "El comparador necesita una mano" (GitHub manda un mail a la
  dueña del repo). Cuando todo vuelve a estar bien, lo comenta y lo cierra solo.

Uso:
  python pipeline/salud.py                     # solo revisa (local, sin GitHub)
  python pipeline/salud.py --reparar --avisar  # lo que hace el workflow
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"
AR = dt.timezone(dt.timedelta(hours=-3))
PAGINA = "https://marianarisariucema.github.io/comparador-fci/"
ETIQUETA = "alerta-datos"
TITULO_AVISO = "⚠️ El comparador necesita una mano"
MAX_RELANZAMIENTOS_POR_DIA = 2

# Workflow que vuelve a generar cada cosa.
WF_DIARIO = "datos-diarios.yml"
WF_CARTERAS = "carteras-semanales.yml"


@dataclass
class Chequeo:
    id: str
    nombre: str
    estado: str = "ok"  # ok | aviso | error
    detalle: str = ""
    reparar_con: str | None = None  # workflow que lo arregla, si se arregla solo
    # Si después de agotar los reintentos sigue en "aviso", ¿pasa a "error"?
    # No para atrasos que dependen de la fuente (feriados, CNV o BCRA que publican tarde).
    escalar: bool = True
    en_reparacion: bool = False
    datos: dict = field(default_factory=dict)


def leer(ruta: Path):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None


def fecha(texto) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(texto)[:10])
    except (TypeError, ValueError):
        return None


FERIADOS: set[dt.date] = set()


def cargar_feriados(anios: list[int]) -> None:
    """Feriados nacionales de ArgentinaDatos, para no confundir un feriado con un atraso."""
    from red import pedir
    for a in anios:
        try:
            r = pedir(f"https://api.argentinadatos.com/v1/feriados/{a}", intentos=2, timeout=30)
            if r.status_code == 200:
                FERIADOS.update(f for f in (fecha(x.get("fecha")) for x in r.json()) if f)
        except Exception as e:  # sin feriados igual funciona, solo puede avisar de más
            print(f"Aviso: no pude bajar feriados {a}: {e}", file=sys.stderr)


def es_habil(d: dt.date) -> bool:
    return d.weekday() < 5 and d not in FERIADOS


def dias_habiles_entre(desde: dt.date, hasta: dt.date) -> int:
    """Días hábiles después de `desde` y hasta `hasta` inclusive (0 si desde >= hasta)."""
    n, d = 0, desde
    while d < hasta:
        d += dt.timedelta(days=1)
        if es_habil(d):
            n += 1
    return n


def ultimo_dia_esperado(ahora_ar: dt.datetime) -> dt.date:
    """Última fecha de la planilla que ya debería estar publicada.

    CAFCI publica la planilla del día alrededor de las 21 hs y nuestra corrida es a
    las 22:30. Antes de las 23:30 se espera la del día hábil anterior.
    """
    d = ahora_ar.date()
    if ahora_ar.time() < dt.time(23, 30):
        d -= dt.timedelta(days=1)
    while not es_habil(d):
        d -= dt.timedelta(days=1)
    return d


# ------------------------------------------------------------------ chequeos de datos
def chequear_planilla(ahora_ar: dt.datetime) -> list[Chequeo]:
    out = []
    u = leer(DATA / "ultimo.json")
    if not u:
        return [Chequeo("planilla", "Planilla diaria CAFCI", "error", "No existe data/ultimo.json", WF_DIARIO)]
    fondos = u.get("fondos") or []
    fd = fecha(u.get("fecha_datos"))
    esperado = ultimo_dia_esperado(ahora_ar)
    atraso = dias_habiles_entre(fd, esperado) if fd else 99
    c = Chequeo("planilla", "Planilla diaria CAFCI al día", datos={"fecha_datos": str(fd), "esperada": str(esperado), "atraso_habiles": atraso})
    if atraso == 0:
        c.detalle = f"Datos al {fd}."
    elif atraso == 1:
        c.estado, c.reparar_con, c.escalar = "aviso", WF_DIARIO, False
        c.detalle = f"Datos al {fd}, falta el {esperado} (CAFCI puede publicar tarde)."
    else:
        c.estado, c.reparar_con = "error", WF_DIARIO
        c.detalle = f"Datos al {fd}: {atraso} días hábiles de atraso."
    out.append(c)

    # Cantidad de clases contra el día anterior guardado
    n = len(fondos)
    hist = sorted((DATA / "historico").glob("*.json"))
    previos = [h for h in hist if h.stem < str(fd)]
    n_prev = len(leer(previos[-1]) or []) if previos else None
    c = Chequeo("cantidad", "Cantidad de clases", datos={"hoy": n, "anterior": n_prev})
    if n < 2500:
        c.estado, c.detalle, c.reparar_con = "error", f"Solo {n} clases (lo normal es ~4.300).", WF_DIARIO
    elif n_prev and n < 0.9 * n_prev:
        c.estado, c.detalle = "aviso", f"{n} clases contra {n_prev} del día anterior."
    else:
        c.detalle = f"{n} clases" + (f" (día anterior: {n_prev})." if n_prev else ".")
    out.append(c)

    # Calidad de los números
    sin_vcp = sum(1 for f in fondos if not f.get("vcp"))
    pat_neg = sum(1 for f in fondos if (f.get("patrimonio") or 0) < 0)
    saltos = [f for f in fondos if f.get("variacion_pct") is not None and abs(f["variacion_pct"]) > 25]
    c = Chequeo("calidad", "Calidad de los números", datos={"sin_cuotaparte": sin_vcp, "patrimonio_negativo": pat_neg,
                                                            "saltos_mayores_25pct": [f["fondo"] for f in saltos[:20]]})
    problemas = []
    if n and sin_vcp > 0.05 * n:
        problemas.append(f"{sin_vcp} clases sin cuotaparte")
    if pat_neg:
        problemas.append(f"{pat_neg} con patrimonio negativo")
    if n and len(saltos) > 0.01 * n:
        problemas.append(f"{len(saltos)} con saltos de cuotaparte mayores a 25% en un día")
    if problemas:
        c.estado, c.detalle = "aviso", "; ".join(problemas) + "."
    else:
        c.detalle = f"Sin problemas ({len(saltos)} saltos grandes aislados, normal en fondos chicos)."
    out.append(c)

    # Formato de la planilla
    est = leer(DATA / "estructura_planilla.json") or {}
    faltan = est.get("columnas_faltantes") or []
    c = Chequeo("formato", "Formato de la planilla CAFCI", datos={"columnas_faltantes": faltan})
    if faltan:
        c.estado = "error"
        c.detalle = (f"CAFCI cambió la planilla: no encuentro {', '.join(faltan)}. "
                     "Hay que ajustar POR_NOMBRE/POR_POSICION en pipeline/actualizar.py.")
    else:
        c.detalle = "Todas las columnas reconocidas."
    out.append(c)

    # Datos derivados: deben ser del mismo día que la planilla
    for id_, nombre, ruta, campo, minimo in [
        ("rendimientos", "Rendimientos por período", DATA / "analisis" / "rendimientos.json", "fecha", 1500),
        ("analisis", "Análisis de carteras", DATA / "analisis" / "fondos.json", "fecha_datos", 0),
        ("web", "Datos de la página (catálogo y fichas)", DATA / "web" / "catalogo.json", "fecha", 500),
    ]:
        d = leer(ruta)
        c = Chequeo(id_, nombre)
        if not d:
            c.estado, c.detalle, c.reparar_con = "aviso", f"No existe {ruta.relative_to(RAIZ)}.", WF_DIARIO
        else:
            fx = fecha(d.get(campo))
            cant = d.get("cantidad") if isinstance(d.get("cantidad"), int) else len(d.get("fondos") or [])
            c.datos = {"fecha": str(fx), "cantidad": cant}
            if fd and fx and fx < fd:
                c.estado, c.reparar_con = "aviso", WF_DIARIO
                c.detalle = f"Quedó del {fx} y la planilla es del {fd} (el paso falló o no corrió)."
            elif minimo and cant < minimo:
                c.estado, c.detalle = "aviso", f"Solo {cant} fondos (se esperan más de {minimo})."
            else:
                c.detalle = f"Al {fx}, {cant} fondos."
            # Rendimientos: cada período tiene que tener una base razonable de fondos
            flacos = {k: v for k, v in (d.get("clases_con_dato") or {}).items()
                      if k in ("7d", "30d", "90d", "1a") and isinstance(v, int) and v < 0.25 * max(cant, 1)}
            if flacos and c.estado == "ok":
                c.estado = "aviso"
                c.detalle += " Períodos con pocos fondos: " + ", ".join(f"{k} ({v})" for k, v in flacos.items()) + \
                    " (falta histórico de esa fecha base)."
        out.append(c)
    return out


def chequear_bcra(hoy: dt.date) -> Chequeo:
    # (nombre, días máximos sin dato nuevo)
    limites = {"dolar_mayorista": 6, "dolar_minorista": 6, "badlar": 8, "tamar": 8, "tasa_plazo_fijo_30d": 8,
               "cer": 8, "uva": 8, "inflacion_mensual": 75, "inflacion_interanual": 75, "inflacion_esperada_12m": 75}
    viejas = []
    ultimos = {}
    for clave, maximo in limites.items():
        d = leer(DATA / "bcra" / f"{clave}.json") or {}
        serie = d.get("serie") or []
        f = fecha(serie[-1]["fecha"]) if serie else None
        ultimos[clave] = str(f)
        if not f or (hoy - f).days > maximo:
            viejas.append(f"{clave} ({f or 'sin datos'})")
    c = Chequeo("bcra", "Indicadores BCRA", datos=ultimos)
    if len(viejas) >= 4:
        c.estado, c.detalle, c.reparar_con = "error", "Series desactualizadas: " + ", ".join(viejas), WF_DIARIO
    elif viejas:
        c.estado, c.detalle, c.reparar_con = "aviso", "Series desactualizadas: " + ", ".join(viejas), WF_DIARIO
        c.escalar = False
    else:
        c.detalle = "Todas las series al día."
    return c


def chequear_carteras(hoy: dt.date) -> Chequeo:
    archivos = list((DATA / "carteras" / "ultima").glob("*.json"))
    fechas = []
    for a in archivos:
        d = leer(a) or {}
        f = fecha(d.get("fecha_cartera"))
        if f:
            fechas.append(f)
    fechas.sort()
    mediana = fechas[len(fechas) // 2] if fechas else None
    c = Chequeo("carteras", "Carteras CNV", datos={"archivos": len(archivos), "fecha_mediana": str(mediana)})
    # La CNV publica con 2-3 semanas de atraso y corremos los sábados.
    if len(archivos) < 800:
        c.estado, c.detalle, c.reparar_con = "error", f"Solo {len(archivos)} carteras guardadas.", WF_CARTERAS
    elif not mediana or (hoy - mediana).days > 45:
        c.estado, c.reparar_con = "error", WF_CARTERAS
        c.detalle = f"La cartera típica es del {mediana}: más de 45 días."
    elif (hoy - mediana).days > 30:
        c.estado, c.reparar_con, c.escalar = "aviso", WF_CARTERAS, False
        c.detalle = f"La cartera típica es del {mediana}: más de 30 días."
    else:
        c.detalle = f"{len(archivos)} carteras, la típica al {mediana}."
    return c


def chequear_precios(hoy: dt.date) -> Chequeo:
    d = leer(DATA / "precios" / "ultimo.json") or {}
    f = fecha(d.get("fecha"))
    c = Chequeo("precios", "Precios BYMA (de la calculadora de renta fija)", datos={"fecha": str(f)})
    atraso = dias_habiles_entre(f, hoy) if f else 99
    if atraso > 5:
        c.estado = "error"
        c.detalle = (f"Precios del {f}. Revisar el robot del repo calculadora-renta-fija "
                     "(credenciales BYMA vencidas o workflow apagado).")
    elif atraso > 2:
        c.estado, c.detalle = "aviso", f"Precios del {f} ({atraso} días hábiles)."
    else:
        c.detalle = f"Precios al {f}."
    return c


def chequear_pagina(local_fecha: str | None) -> Chequeo:
    """Compara lo publicado en GitHub Pages con lo que hay en el repo."""
    import requests
    from red import pedir
    c = Chequeo("pagina", "Página publicada")
    try:
        r = pedir(PAGINA + "data/ultimo.json", intentos=3, espera=10, timeout=60, stream=True)
        if r.status_code != 200:
            c.estado, c.detalle = "error", f"{PAGINA} responde HTTP {r.status_code}."
            return c
        # Solo hace falta el encabezado del JSON (fecha_datos está al principio).
        cabeza = next(r.iter_content(4096), b"").decode("utf-8", "ignore")
        r.close()
        import re
        m = re.search(r'"fecha_datos"\s*:\s*"([0-9-]+)"', cabeza)
        publicada = m.group(1) if m else None
        c.datos = {"publicada": publicada, "repo": local_fecha}
        if publicada != local_fecha:
            c.estado = "aviso"
            c.detalle = f"La página muestra datos del {publicada} y el repo tiene del {local_fecha} (GitHub Pages atrasado)."
        else:
            c.detalle = f"Responde y muestra datos del {publicada}."
        r = pedir(PAGINA, intentos=3, espera=10, timeout=60)
        if r.status_code != 200:
            c.estado, c.detalle = "error", f"La portada responde HTTP {r.status_code}."
    except requests.RequestException as e:
        c.estado, c.detalle = "aviso", f"No pude abrir la página: {type(e).__name__}."
    return c


# ------------------------------------------------------------------ GitHub
class GitHub:
    def __init__(self, repo: str, token: str):
        import requests
        self.repo = repo
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                               "X-GitHub-Api-Version": "2022-11-28"})

    def api(self, metodo: str, ruta: str, **kw):
        from red import pedir
        r = pedir(f"https://api.github.com/repos/{self.repo}{ruta}", sesion=self.s, metodo=metodo, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"GitHub {metodo} {ruta}: HTTP {r.status_code} {r.text[:200]}")
        return r.json() if r.text.strip() else {}

    def corridas(self, workflow: str, n: int = 10) -> list[dict]:
        return self.api("GET", f"/actions/workflows/{workflow}/runs", params={"per_page": n}).get("workflow_runs", [])

    def relanzar(self, workflow: str, rama: str = "main") -> None:
        self.api("POST", f"/actions/workflows/{workflow}/dispatches", json={"ref": rama})


def chequear_workflows(gh: GitHub) -> list[Chequeo]:
    out = []
    for wf, nombre in [(WF_DIARIO, "Workflow de datos diarios"), (WF_CARTERAS, "Workflow de carteras")]:
        c = Chequeo(f"wf_{wf.split('.')[0]}", nombre)
        try:
            runs = gh.corridas(wf)
        except Exception as e:
            c.estado, c.detalle = "aviso", f"No pude consultar GitHub: {e}"
            out.append(c)
            continue
        terminadas = [r for r in runs if r.get("status") == "completed"]
        if not terminadas:
            c.detalle = "Sin corridas terminadas todavía."
        else:
            r = terminadas[0]
            c.datos = {"conclusion": r.get("conclusion"), "url": r.get("html_url"), "fecha": r.get("created_at")}
            if r.get("conclusion") in ("failure", "timed_out", "startup_failure"):
                c.estado, c.reparar_con = "aviso", wf
                c.detalle = f"La última corrida terminó en '{r['conclusion']}': {r.get('html_url')}"
                # Dos fallas seguidas ya no es un problema pasajero
                if len(terminadas) > 1 and terminadas[1].get("conclusion") in ("failure", "timed_out", "startup_failure"):
                    c.estado = "error"
                    c.detalle = f"Las últimas dos corridas fallaron: {r.get('html_url')}"
            else:
                c.detalle = f"Última corrida: {r.get('conclusion')} ({r.get('created_at')})."
        out.append(c)
    return out


def chequear_tamano(gh: GitHub) -> Chequeo:
    c = Chequeo("tamano", "Tamaño del repositorio")
    try:
        kb = gh.s.get(f"https://api.github.com/repos/{gh.repo}", timeout=30).json().get("size", 0)
    except Exception as e:
        c.estado, c.detalle = "aviso", f"No pude consultarlo: {e}"
        return c
    gb = kb / 1024 / 1024
    c.datos = {"gb": round(gb, 2)}
    # GitHub recomienda repos de menos de 1 GB; arriba de 5 GB puede pedir que se reduzca.
    if gb > 3:
        c.estado, c.detalle = "error", f"{gb:.1f} GB: hay que sacar el histórico de data/ del repo (ver VIGILANCIA.md)."
    elif gb > 1:
        c.estado, c.detalle = "aviso", f"{gb:.1f} GB: crece con cada noche; conviene mover los datos a otra rama o a Releases."
    else:
        c.detalle = f"{gb:.2f} GB."
    return c


# ------------------------------------------------------------------ reparar y avisar
def relanzamientos_hoy(gh: GitHub, wf: str, hoy_utc: dt.date) -> tuple[int, bool]:
    """(cuántas veces lo relanzó el bot hoy, si hay una corrida en curso)."""
    runs = gh.corridas(wf, 20)
    en_curso = any(r.get("status") in ("queued", "in_progress", "waiting", "pending", "requested") for r in runs)
    n = sum(1 for r in runs if r.get("event") == "workflow_dispatch"
            and (r.get("triggering_actor") or {}).get("login") == "github-actions[bot]"
            and str(r.get("created_at", ""))[:10] == hoy_utc.isoformat())
    return n, en_curso


def reparar(gh: GitHub, chequeos: list[Chequeo], hoy_utc: dt.date) -> list[str]:
    acciones = []
    a_relanzar = {c.reparar_con for c in chequeos if c.reparar_con and c.estado != "ok"}
    for wf in sorted(a_relanzar):
        n, en_curso = relanzamientos_hoy(gh, wf, hoy_utc)
        if en_curso:
            acciones.append(f"{wf}: ya hay una corrida en curso, espero a que termine.")
            for c in chequeos:
                if c.reparar_con == wf and c.estado != "ok":
                    c.en_reparacion = True
        elif wf == WF_CARTERAS and n >= 1:
            acciones.append(f"{wf}: ya lo relancé hoy (tarda ~2 h), no insisto.")
        elif n >= MAX_RELANZAMIENTOS_POR_DIA:
            acciones.append(f"{wf}: ya lo relancé {n} veces hoy; si sigue mal, necesita una persona.")
            for c in chequeos:
                if c.reparar_con == wf and c.estado == "aviso" and c.escalar:
                    c.estado = "error"  # agotó los reintentos automáticos
                    c.detalle += " (sigue igual después de los reintentos automáticos)"
        else:
            gh.relanzar(wf)
            for c in chequeos:
                if c.reparar_con == wf and c.estado != "ok":
                    c.en_reparacion = True  # no se avisa todavía: se vuelve a chequear al terminar
            acciones.append(f"{wf}: relanzado ({n + 1}/{MAX_RELANZAMIENTOS_POR_DIA} de hoy).")
    return acciones


def cuerpo_aviso(chequeos: list[Chequeo], acciones: list[str], url_corrida: str | None) -> str:
    errores = [c for c in chequeos if c.estado == "error" and not c.en_reparacion]
    avisos = [c for c in chequeos if c.estado == "aviso"]
    lineas = ["@marianarisariucema el chequeo automático encontró algo que no pudo arreglar solo.", ""]
    lineas += ["### Necesita una persona", ""] + [f"- **{c.nombre}**: {c.detalle}" for c in errores]
    if avisos:
        lineas += ["", "### Para mirar (no urgente)", ""] + [f"- {c.nombre}: {c.detalle}" for c in avisos]
    if acciones:
        lineas += ["", "### Lo que ya intentó el robot", ""] + [f"- {a}" for a in acciones]
    lineas += ["", "Mientras tanto la página sigue mostrando el último dato bueno.",
               "Qué hacer en cada caso: ver `VIGILANCIA.md`."]
    if url_corrida:
        lineas += ["", f"Detalle de este chequeo: {url_corrida}"]
    lineas += ["", "_Este issue lo abre y lo cierra solo `pipeline/salud.py`._"]
    return "\n".join(lineas)


def avisar(gh: GitHub, chequeos: list[Chequeo], acciones: list[str], url_corrida: str | None) -> str:
    abiertos = gh.api("GET", "/issues", params={"labels": ETIQUETA, "state": "open", "per_page": 5})
    abiertos = [i for i in abiertos if "pull_request" not in i]
    errores = [c for c in chequeos if c.estado == "error" and not c.en_reparacion]
    if not errores:
        if any(c.en_reparacion for c in chequeos):
            return "Hay una reparación en curso; vuelvo a chequear cuando termine."
        for i in abiertos:
            gh.api("POST", f"/issues/{i['number']}/comments",
                   json={"body": "✅ Se resolvió: el último chequeo dio todo bien. Lo cierro solo."})
            gh.api("PATCH", f"/issues/{i['number']}", json={"state": "closed", "state_reason": "completed"})
        return f"Cerré {len(abiertos)} aviso(s) viejo(s)." if abiertos else "Sin avisos."
    cuerpo = cuerpo_aviso(chequeos, acciones, url_corrida)
    firma = "<!-- errores: " + ",".join(sorted(c.id for c in errores)) + " -->"
    cuerpo += "\n" + firma
    if abiertos:
        i = abiertos[0]
        cambio = firma not in (i.get("body") or "")
        gh.api("PATCH", f"/issues/{i['number']}", json={"body": cuerpo})
        if cambio:  # solo notifica de nuevo si cambió qué está roto
            gh.api("POST", f"/issues/{i['number']}/comments",
                   json={"body": "Cambió lo que está roto: " + ", ".join(c.nombre for c in errores) + "."})
        return f"Actualicé el aviso #{i['number']}."
    try:
        gh.api("POST", "/labels", json={"name": ETIQUETA, "color": "d93f0b",
                                        "description": "Abierto por el chequeo automático de datos"})
    except RuntimeError:
        pass  # ya existe
    i = gh.api("POST", "/issues", json={"title": TITULO_AVISO, "body": cuerpo, "labels": [ETIQUETA]})
    return f"Abrí el aviso #{i.get('number')}."


# ------------------------------------------------------------------ informe
ICONO = {"ok": "✅", "aviso": "🟡", "error": "🔴"}


def informe(chequeos: list[Chequeo], acciones: list[str], resultado_aviso: str | None) -> str:
    peor = "error" if any(c.estado == "error" for c in chequeos) else "aviso" if any(c.estado == "aviso" for c in chequeos) else "ok"
    titulo = {"ok": "Todo en orden", "aviso": "Funciona, con detalles para mirar", "error": "Necesita una persona"}[peor]
    lineas = [f"## {ICONO[peor]} Salud del comparador: {titulo}", "", "| | Qué | Detalle |", "|---|---|---|"]
    lineas += [f"| {ICONO[c.estado]} | {c.nombre} | {c.detalle}{' (reparando)' if c.en_reparacion else ''} |" for c in chequeos]
    if acciones:
        lineas += ["", "**Reparaciones automáticas:**", ""] + [f"- {a}" for a in acciones]
    if resultado_aviso:
        lineas += ["", f"**Aviso:** {resultado_aviso}"]
    return "\n".join(lineas)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reparar", action="store_true", help="Relanzar workflows si faltan datos")
    ap.add_argument("--avisar", action="store_true", help="Abrir/cerrar el issue de aviso")
    ap.add_argument("--sin-red", action="store_true", help="No consultar la página publicada ni GitHub")
    ap.add_argument("--salida", help="Guardar el resultado en este JSON")
    args = ap.parse_args()

    ahora = dt.datetime.now(dt.timezone.utc)
    ahora_ar = ahora.astimezone(AR)
    hoy = ahora_ar.date()
    if not args.sin_red:
        cargar_feriados(sorted({hoy.year - 1, hoy.year}))

    chequeos = chequear_planilla(ahora_ar)
    chequeos += [chequear_bcra(hoy), chequear_carteras(hoy), chequear_precios(hoy)]
    if not args.sin_red:
        chequeos.append(chequear_pagina((leer(DATA / "ultimo.json") or {}).get("fecha_datos")))

    gh = None
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if token and repo and not args.sin_red:
        gh = GitHub(repo, token)
        chequeos += chequear_workflows(gh)
        chequeos.append(chequear_tamano(gh))

    acciones, resultado_aviso = [], None
    if gh and args.reparar:
        try:
            acciones = reparar(gh, chequeos, ahora.date())
        except Exception as e:
            acciones.append(f"No pude relanzar: {e}")
    if gh and args.avisar:
        url = None
        if os.environ.get("GITHUB_RUN_ID"):
            url = f"https://github.com/{repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
        resultado_aviso = avisar(gh, chequeos, acciones, url)

    texto = informe(chequeos, acciones, resultado_aviso)
    print(texto)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(texto + "\n")
    if args.salida:
        Path(args.salida).write_text(json.dumps({
            "fecha": ahora.isoformat(timespec="seconds"), "chequeos": [asdict(c) for c in chequeos],
            "acciones": acciones, "aviso": resultado_aviso}, ensure_ascii=False, indent=1), encoding="utf-8")
    # El workflow no se marca como fallido por datos viejos (eso lo avisa el issue);
    # sí falla si el propio chequeo se rompió, para que se note.
    return 0


if __name__ == "__main__":
    sys.exit(main())
