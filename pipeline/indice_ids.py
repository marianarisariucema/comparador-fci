"""Índice de códigos → fondo, para que la ALyC use los códigos que ya tiene en su sistema.

Escribe data/web/ids.json:
  {"cafci": {"<codigo_cafci>": "<id fondo>"}, "cnv": {"<codigo_cnv>": "<id fondo>"},
   "clase": {"<id clase>": "<id fondo>"}}

Con eso el componente y la API aceptan fondo="cafci:6419" o "cnv:1901" además del id propio.
Lee solo lo que ya generaron actualizar.py y web.py (no baja nada). Corre después de web.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"
WEB = DATA / "web"


def main() -> int:
    try:
        clases = json.loads((DATA / "ultimo.json").read_text(encoding="utf-8")).get("fondos", [])
    except FileNotFoundError:
        print("Falta data/ultimo.json")
        return 1
    por_nombre = {}
    for ruta in sorted((WEB / "fondos").glob("*.json")):
        f = json.loads(ruta.read_text(encoding="utf-8"))
        for c in f.get("clases", []):
            por_nombre.setdefault(c.get("nombre"), f["id"])
    indice = {"cafci": {}, "cnv": {}, "clase": {}}
    sin = 0
    for c in clases:
        fid = por_nombre.get(c.get("fondo"))
        if not fid:
            sin += 1
            continue
        indice["clase"][str(c["id"]).lower()] = fid
        if c.get("codigo_cafci"):
            indice["cafci"][str(c["codigo_cafci"]).strip().lower()] = fid
        if c.get("codigo_cnv"):
            # Un código CNV es del fondo; todas sus clases apuntan al mismo id.
            indice["cnv"].setdefault(str(c["codigo_cnv"]).strip().lower(), fid)
    (WEB / "ids.json").write_text(json.dumps(indice, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"ids.json: {len(indice['clase'])} clases, {len(indice['cafci'])} códigos CAFCI, {len(indice['cnv'])} CNV; {sin} clases sin ficha.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
