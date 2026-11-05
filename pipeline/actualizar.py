"""Actualización diaria de datos de FCI desde fuentes públicas de CAFCI.

Pasos:
  1. Baja la planilla diaria pública de CAFCI (todos los fondos, un archivo).
  2. Baja el catálogo de fondos del sitio de estadísticas de CAFCI.
  3. Normaliza la planilla, calcula el flujo neto estimado de cada fondo
     y escribe archivos JSON estáticos en data/ listos para servir.

Uso:
  python pipeline/actualizar.py                 # baja de CAFCI y procesa
  python pipeline/actualizar.py --planilla X.xls # procesa un archivo local
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd
import requests

from carteras_cnv import nombre_clave  # misma clave para cruzar con las carteras de la CNV
from red import pedir

URL_PLANILLA = "https://api.pub.cafci.org.ar/pb_get"
# El sitio de estadísticas bloquea pedidos automáticos (CloudFront 403, probado 2026-11-04);
# se intenta igual y si falla se sigue sin catálogo.
URL_CATALOGO = "https://estadisticas.cafci.org.ar/consulta-de-fondos.json"
HEADERS = {
    "User-Agent": "comparador-fci/0.1 (+https://github.com/marianarisariucema/comparador-fci)",
    "Accept-Language": "es-AR,es;q=0.9",
}
RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"

# Columnas de la planilla diaria de CAFCI. El encabezado tiene dos niveles
# (fila 8 = grupo, fila 9 = subcolumna) y las subcolumnas de los grupos con
# fechas cambian todos los días, así que dentro de un grupo se toma por posición.
POR_POSICION = {
    "vcp": ("valor", 0),
    "vcp_anterior": ("valor", 1),
    "variacion_pct": ("valor", 2),
    "cuotapartes": ("cantidad de cuotapartes", 0),
    "cuotapartes_anterior": ("cantidad de cuotapartes", 1),
    "patrimonio": ("patrimonio", 0),
    "patrimonio_anterior": ("patrimonio", 1),
    # Variación de cuotaparte contra fin del mes anterior, fin del año anterior y hace 12 meses
    "rend_mes_pct": ("variacion cuotaparte", 0),
    "rend_anio_pct": ("variacion cuotaparte", 1),
    "rend_12m_pct": ("variacion cuotaparte", 2),
}
# Resto de columnas: (texto del grupo, texto de la subcolumna o "").
POR_NOMBRE = {
    "moneda": ("clasificacion", "moneda"),
    "region": ("clasificacion", "region"),
    "horizonte": ("clasificacion", "horizonte"),
    "fecha": ("fecha", ""),
    "market_share": ("market share", ""),
    "depositaria": ("sociedad depositaria", ""),
    "gerente": ("sociedad gerente", ""),
    "codigo_cnv": ("codigo cnv", ""),
    "codigo_cafci": ("codigo cafci", ""),
    "calificacion": ("calificacion", ""),
    "comision_ingreso": ("comision ingreso", ""),
    "comision_rescate": ("comision rescate", ""),
    "honorarios_gerente": ("honorarios adm. sg", ""),
    "honorarios_depositaria": ("honorarios adm. sd", ""),
    "gastos_gestion": ("gastos ord gestion", ""),
    "honorarios_exito": ("honorarios exito", ""),
    "moneda_fondo": ("moneda fondo", ""),
    "plazo_liquidacion": ("plazo liq", ""),
    "minimo_inversion": ("minimo de inversion", ""),
    "tipo_dinero": ("tipo de dinero", ""),
}
NUMERICAS = {"rend_mes_pct", "rend_anio_pct", "rend_12m_pct", "vcp", "vcp_anterior", "variacion_pct", "cuotapartes", "cuotapartes_anterior",
             "patrimonio", "patrimonio_anterior", "market_share", "comision_ingreso",
             "comision_rescate", "honorarios_gerente", "honorarios_depositaria",
             "gastos_gestion", "honorarios_exito", "minimo_inversion"}
COLUMNAS = ["fondo", *POR_POSICION, *POR_NOMBRE]


def sin_acentos(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in texto if not unicodedata.combining(c)).lower().strip()


def slug(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", sin_acentos(texto)).strip("-")


def bajar(url: str) -> bytes:
    r = pedir(url, headers=HEADERS)
    if r.status_code != 200:
        raise RuntimeError(f"{url} respondió HTTP {r.status_code}: {r.text[:200]}")
    return r.content


def leer_excel(contenido: bytes) -> pd.DataFrame:
    if contenido[:4] == b"\xd0\xcf\x11\xe0":
        motor = "xlrd"  # .xls viejo
    elif contenido[:2] == b"PK":
        motor = "openpyxl"  # .xlsx
    else:
        raise RuntimeError("La planilla no es un Excel reconocible (¿página de error?).")
    return pd.read_excel(io.BytesIO(contenido), header=None, engine=motor, dtype=object)


def encontrar_encabezado(crudo: pd.DataFrame) -> int:
    for i, fila in crudo.head(40).iterrows():
        celdas = [sin_acentos(c) for c in fila if pd.notna(c)]
        if any(c == "fondo" for c in celdas) and len(celdas) >= 4:
            return i
    raise RuntimeError("No encontré la fila de encabezados (con 'Fondo') en la planilla.")


def nombres_de_columnas(crudo: pd.DataFrame, fila: int) -> list[tuple[str, str]]:
    """Devuelve (grupo, subcolumna) por columna. Las celdas combinadas del grupo
    vienen vacías, así que se arrastra el último grupo hacia la derecha."""
    arriba, abajo = crudo.iloc[fila], crudo.iloc[fila + 1]
    nombres, grupo = [], ""
    for a, b in zip(arriba, abajo):
        if pd.notna(a) and str(a).strip():
            grupo = sin_acentos(a)
        nombres.append((grupo, sin_acentos(b) if pd.notna(b) else ""))
    return nombres


def mapear(nombres: list[tuple[str, str]]) -> dict[str, int]:
    mapa: dict[str, int] = {}
    for i, (g, _) in enumerate(nombres):
        if g == "fondo":
            mapa["fondo"] = i
            break
    for clave, (grupo, pos) in POR_POSICION.items():
        idx = [i for i, (g, _) in enumerate(nombres) if g.startswith(grupo)]
        if len(idx) > pos:
            mapa[clave] = idx[pos]
    for clave, (grupo, sub) in POR_NOMBRE.items():
        for i, (g, s) in enumerate(nombres):
            if g.startswith(grupo) and (not sub or s.startswith(sub)):
                mapa[clave] = i
                break
    return mapa


def a_numero(valor):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    if str(valor).strip() in {"", "-", "–", "—"}:
        return None
    texto = str(valor).strip().replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def a_fecha(valor):
    """Devuelve la fecha en formato ISO (AAAA-MM-DD); CAFCI usa dd/mm/aaaa."""
    if valor is None:
        return None
    if isinstance(valor, (dt.date, dt.datetime, pd.Timestamp)):
        return pd.Timestamp(valor).date().isoformat()
    try:
        return pd.to_datetime(str(valor).strip(), dayfirst=True).date().isoformat()
    except (ValueError, TypeError):
        return None


def normalizar(crudo: pd.DataFrame) -> tuple[list[dict], dict]:
    fila_enc = encontrar_encabezado(crudo)
    nombres = nombres_de_columnas(crudo, fila_enc)
    mapa = mapear(nombres)
    if "fondo" not in mapa:
        raise RuntimeError(f"No encontré la columna de fondo. Columnas: {nombres}")

    fondos, categoria = [], None
    for _, fila in crudo.iloc[fila_enc + 2 :].iterrows():
        valores = list(fila)
        llenas = [v for v in valores if pd.notna(v) and str(v).strip()]
        if not llenas:
            continue
        # Fila de sección: solo tiene texto en una celda (ej. "Renta Fija - Pesos")
        if len(llenas) == 1 and isinstance(llenas[0], str):
            categoria = llenas[0].strip()
            continue
        nombre = valores[mapa["fondo"]]
        if pd.isna(nombre) or not str(nombre).strip():
            continue

        def campo(clave):
            i = mapa.get(clave)
            return None if i is None or pd.isna(valores[i]) else valores[i]

        nombre = str(nombre).strip()
        registro = {
            "id": slug(nombre),
            "fondo": nombre,
            # Cada fila es una clase; el fondo es el nombre sin " - Clase X"
            "fondo_base": re.split(r"\s+-\s+clase\b", nombre, flags=re.I)[0].strip(),
            "categoria": categoria,
        }
        registro["clave"] = nombre_clave(registro["fondo_base"])
        for clave in COLUMNAS:
            if clave == "fondo":
                continue
            v = campo(clave)
            if clave in NUMERICAS:
                v = a_numero(v)
            elif clave == "fecha":
                v = a_fecha(v)
            elif v is not None:
                v = str(v).strip()
            registro[clave] = v
        registro["flujo_neto_estimado"] = flujo_neto(registro)
        fondos.append(registro)

    info = {"fila_encabezado": int(fila_enc), "columnas": [" / ".join(x for x in n if x) for n in nombres],
            "columnas_reconocidas": {k: " / ".join(x for x in nombres[i] if x) for k, i in mapa.items()},
            "columnas_faltantes": [k for k in COLUMNAS if k not in mapa]}
    return fondos, info


def flujo_neto(r: dict):
    """Suscripciones menos rescates del día, estimado.

    flujo ≈ patrimonio_hoy − patrimonio_ayer × (vcp_hoy / vcp_ayer)
    Lo que creció el patrimonio por encima de lo que explica el rendimiento.
    """
    p, p0, v, v0 = (r.get(k) for k in ("patrimonio", "patrimonio_anterior", "vcp", "vcp_anterior"))
    if None in (p, p0, v, v0) or not v0:
        return None
    return round(p - p0 * (v / v0), 2)


def leer_previo() -> dict | None:
    try:
        d = json.loads((DATA / "ultimo.json").read_text(encoding="utf-8"))
        return {"fecha_datos": d.get("fecha_datos"), "cantidad_fondos": d.get("cantidad_fondos") or len(d.get("fondos", []))}
    except (FileNotFoundError, ValueError):
        return None


def rechazar(fondos: list[dict], fecha: str, previo: dict | None) -> str | None:
    """Motivo para no publicar una planilla que parece rota (o None si está bien).

    Protege el último dato bueno: una planilla a medio cargar, de una fecha vieja
    o con las columnas corridas no pisa lo que ya está publicado.
    """
    if previo and previo.get("fecha_datos") and fecha < previo["fecha_datos"]:
        return f"trae datos del {fecha}, más viejos que los publicados ({previo['fecha_datos']})"
    if previo and previo.get("cantidad_fondos") and len(fondos) < 0.7 * previo["cantidad_fondos"]:
        return f"trae {len(fondos)} clases y la anterior {previo['cantidad_fondos']} (cayó más de 30%)"
    con_vcp = sum(1 for f in fondos if f.get("vcp"))
    if con_vcp < 0.8 * len(fondos):
        return f"solo {con_vcp} de {len(fondos)} clases tienen cuotaparte (¿columnas corridas?)"
    return None


def escribir_json(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--planilla", help="Procesar un archivo local en vez de bajarlo")
    ap.add_argument("--sin-catalogo", action="store_true")
    args = ap.parse_args()

    hoy = dt.date.today().isoformat()
    contenido = Path(args.planilla).read_bytes() if args.planilla else bajar(URL_PLANILLA)
    fondos, info = normalizar(leer_excel(contenido))
    if not fondos:
        raise RuntimeError("La planilla no tuvo fondos; no sobrescribo los datos.")

    fecha = next((f["fecha"] for f in fondos if f.get("fecha")), None) or hoy
    previo = leer_previo()
    if previo and previo.get("fecha_datos") and fecha < previo["fecha_datos"]:
        # CAFCI devolvió una planilla vieja (pasa a veces de madrugada): no es un error, se deja lo publicado.
        print(f"La planilla es del {fecha} y ya está publicada la del {previo['fecha_datos']}: no cambio nada.")
        return 0
    motivo = rechazar(fondos, fecha, previo)
    if motivo:
        # Se conserva el último dato bueno publicado; el chequeo de salud avisa si se repite.
        raise RuntimeError(f"Planilla rechazada, no sobrescribo los datos: {motivo}")
    resumen = {
        "actualizado": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "fecha_datos": fecha,
        "fuente": "Planilla diaria CAFCI (api.pub.cafci.org.ar/pb_get)",
        "cantidad_fondos": len(fondos),
        "aviso": "Información con fines informativos. No constituye recomendación de inversión.",
    }
    escribir_json(DATA / "ultimo.json", {**resumen, "fondos": fondos})
    # Histórico compacto: {id: [cuotaparte, patrimonio, cuotapartes]} (unos 200 KB por día)
    escribir_json(DATA / "historico" / f"{fecha}.json",
                  {f["id"]: [f.get("vcp"), f.get("patrimonio"), f.get("cuotapartes")] for f in fondos if f.get("vcp")})
    escribir_json(DATA / "estructura_planilla.json", info)

    if not args.sin_catalogo:
        try:
            escribir_json(DATA / "catalogo.json", json.loads(bajar(URL_CATALOGO)))
        except Exception as e:  # el catálogo es complementario: no frena la corrida
            print(f"Aviso: no se pudo bajar el catálogo: {e}", file=sys.stderr)

    print(f"OK: {len(fondos)} fondos al {fecha}. Columnas reconocidas: {list(info['columnas_reconocidas'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
