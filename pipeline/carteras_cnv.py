"""Carteras semanales de los FCI desde la ficha pública de cada fondo en la CNV.

Fuente: https://www.cnv.gov.ar/SitioWeb/FondosComunesInversion/DetallesFCI/{id}
sección "Composición Semanal Cartera" (art. 34 Cap. XI). Se actualiza una vez
por semana, con unas semanas de atraso.

Uso:
  python pipeline/carteras_cnv.py                    # todos los fondos (abiertos y cerrados)
  python pipeline/carteras_cnv.py --ids 63445 63383  # solo esos fondos
  python pipeline/carteras_cnv.py --fecha 2026-09-30 # cartera vigente a esa fecha
  python pipeline/carteras_cnv.py --html ficha.html  # procesar un HTML guardado
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

import requests

BASE = "https://www.cnv.gov.ar/SitioWeb/FondosComunesInversion"
URL_LISTADO = f"{BASE}/GetFCIPorTipo"  # POST idTipo=0 abiertos, 1 cerrados
URL_FICHA = f"{BASE}/DetallesFCI/{{id}}"
HEADERS = {"User-Agent": "comparador-fci/0.1 (+https://github.com/marianarisariucema/comparador-fci)"}
PAUSA_SEG = 1.0
RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data" / "carteras"


def sin_acentos(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in texto if not unicodedata.combining(c)).lower().strip()


def nombre_clave(nombre: str) -> str:
    """Clave para cruzar nombres de CNV y CAFCI.
    'SF12-Supergestión Mix VI F.C.I.' y 'Supergestion Mix VI - Clase A' -> 'supergestion mix vi'."""
    n = sin_acentos(nombre)
    n = re.sub(r"^[a-z]{1,3}\d{1,4}\s*-\s*", "", n)          # prefijo tipo "SF12-"
    # Sufijos de la CNV: "Ex <nombre anterior>", "en Liquidación ...", nombre cortado
    n = re.sub(r"\s*\(?\bex\b\s.*$", "", n)
    n = re.sub(r"\s+en liquidacion\b.*$", "", n)
    n = re.sub(r"\s*\bfondo comun de inv\w*.*$", "", n)
    n = n.replace("ley 27.260", " ")
    n = re.split(r"\s+-\s+clase\b", n)[0]                     # " - Clase A"
    n = re.sub(r"\bf\.?\s*c\.?\s*i\.?(\s*abierto)?\.?", " ", n)  # "F.C.I."
    n = re.sub(r"[^a-z0-9]+", " ", n)
    n = re.sub(r"\bargentinas\b", "argentina", n)
    return re.sub(r"\s+", " ", n).strip()


def a_numero(texto: str):
    t = (texto or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


class _Tablas(HTMLParser):
    """Junta las tablas de la pestaña de cartera (div id='1b') con el estilo del primer td."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.en_tab = 0
        self.tablas: list[list[list[tuple[str, str]]]] = []
        self._fila = None
        self._celda = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "div":
            if self.en_tab:
                self.en_tab += 1
            elif a.get("id") == "1b":
                self.en_tab = 1
        if not self.en_tab:
            return
        if tag == "table":
            self.tablas.append([])
        elif tag == "tr" and self.tablas:
            self._fila = []
        elif tag in ("td", "th") and self._fila is not None:
            self._celda = [a.get("style", "") if tag == "td" else "th", ""]

    def handle_endtag(self, tag):
        if tag == "div" and self.en_tab:
            self.en_tab -= 1
        if not self.en_tab:
            return
        if tag in ("td", "th") and self._celda is not None:
            self._fila.append((self._celda[0], re.sub(r"\s+", " ", self._celda[1]).strip()))
            self._celda = None
        elif tag == "tr" and self._fila is not None:
            if self._fila:
                self.tablas[-1].append(self._fila)
            self._fila = None

    def handle_data(self, data):
        if self._celda is not None:
            self._celda[1] += data


def parsear_ficha(html: str) -> dict:
    p = _Tablas()
    p.feed(html)
    if len(p.tablas) < 2:
        raise ValueError("No encontré la sección de cartera (div id='1b') en la ficha.")
    datos = {}
    for fila in p.tablas[0]:
        if len(fila) >= 2:
            datos[sin_acentos(fila[0][1]).rstrip(":")] = fila[1][1]
    cartera = next((t for t in p.tablas[1:] if any(c[0] == "th" for f in t for c in f)), p.tablas[1])

    tipos, activos, patrimonio, tipo_actual = [], [], {}, None
    for fila in cartera:
        if fila[0][0] == "th" or len(fila) < 3:
            continue
        estilo, detalle = fila[0][0].replace(" ", "").lower(), fila[0][1]
        pct2, pct3 = a_numero(fila[1][1]), a_numero(fila[2][1])
        if "padding-left" in estilo:
            activos.append({"activo": detalle, "tipo": tipo_actual, "pct_pn": pct2})
        elif "bold" in estilo:
            if not detalle:
                continue  # fila del total 100%
            if detalle.startswith("(") and detalle.endswith(")"):
                patrimonio[detalle.strip("()")] = pct2
                continue
            tipo_actual = detalle
            tipos.append({"tipo": detalle, "pct_pn": pct3})

    fecha = datos.get("cartera al (*)") or datos.get("cartera al")
    if fecha and re.fullmatch(r"\d{2}/\d{2}/\d{2}", fecha):
        d, m, a = fecha.split("/")
        fecha = f"20{a}-{m}-{d}"
    return {
        "fondo": datos.get("fondo"),
        "fecha_cartera": fecha,
        "gerente": datos.get("gerente"),
        "depositaria": datos.get("depositaria"),
        "clasificacion": datos.get("clasificacion"),
        "moneda": datos.get("moneda"),
        "region": datos.get("region"),
        "horizonte": datos.get("horizonte"),
        "patrimonio_por_moneda": patrimonio,
        "por_tipo": tipos,
        "activos": activos,
        "fuente": "CNV - Composición Semanal Cartera (art. 34 Cap. XI)",
    }


def listar_fondos(sesion: requests.Session) -> list[dict]:
    """Fondos abiertos (idTipo=0) y cerrados (idTipo=1) de la CNV."""
    fondos, vistos = [], set()
    for id_tipo in (0, 1):
        r = sesion.post(URL_LISTADO, data={"idTipo": id_tipo}, timeout=60)
        r.raise_for_status()
        items = r.json()
        print(f"Listado CNV idTipo={id_tipo}: {len(items)} elementos")
        for x in items:
            v = str(x.get("Value") or "").strip()
            if v and v not in vistos:
                vistos.add(v)
                fondos.append({"id": v, "nombre_cnv": x.get("Text", ""),
                               "clave": nombre_clave(x.get("Text", "")), "abierto": id_tipo == 0})
    return fondos


def bajar_ficha(sesion: requests.Session, fondo_id: str, fecha: str | None = None) -> str:
    params = {"fecha": fecha, "compo": "true"} if fecha else None
    r = sesion.get(URL_FICHA.format(id=fondo_id), params=params, timeout=60)
    r.raise_for_status()
    return r.text


def escribir_json(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="*", help="IDs de DetallesFCI a bajar (por defecto, todos los abiertos)")
    ap.add_argument("--fecha", help="Cartera vigente a esta fecha (AAAA-MM-DD)")
    ap.add_argument("--html", help="Procesar un HTML guardado y mostrar el resultado")
    args = ap.parse_args()

    if args.html:
        print(json.dumps(parsear_ficha(Path(args.html).read_text(encoding="utf-8")), ensure_ascii=False, indent=1))
        return 0

    s = requests.Session()
    s.headers.update(HEADERS)
    listado = listar_fondos(s)
    escribir_json(DATA / "listado_cnv.json", listado)
    if args.ids:
        por_id = {f["id"]: f for f in listado}
        elegidos = [por_id.get(i, {"id": i, "nombre_cnv": "", "clave": ""}) for i in args.ids]
    else:
        elegidos = listado

    ok, errores = 0, []
    for i, f in enumerate(elegidos):
        try:
            cartera = parsear_ficha(bajar_ficha(s, f["id"], args.fecha))
            cartera.update(id_cnv=f["id"], nombre_cnv=f["nombre_cnv"], clave=f["clave"])
            escribir_json(DATA / "ultima" / f"{f['id']}.json", cartera)
            if cartera["fecha_cartera"]:
                escribir_json(DATA / "historico" / cartera["fecha_cartera"] / f"{f['id']}.json", cartera)
            ok += 1
        except Exception as e:  # un fondo sin cartera no frena el resto
            errores.append({"id": f["id"], "nombre": f["nombre_cnv"], "error": str(e)[:200]})
        if i < len(elegidos) - 1:
            time.sleep(PAUSA_SEG)

    escribir_json(DATA / "errores.json", errores)
    print(f"OK: {ok} carteras, {len(errores)} sin cartera o con error, de {len(elegidos)} fondos.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
