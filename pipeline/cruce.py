"""Cruce entre las carteras de la CNV y los fondos de la planilla CAFCI.

El nombre que usa la CNV y el de CAFCI no siempre coinciden ("Fima FCI Abierto Pymes" contra
"Fima Abierto Pymes", "MEGAQM Renta Dólares" contra "MEGAQM Renta Dolares"). Se prueba en orden,
siempre dentro de la misma gestora:
  1. el nombre del fondo tal cual (misma clave que usa CAFCI);
  2. la clave del nombre oficial de la CNV;
  3. el nombre sin palabras de relleno (FCI, abierto, ASG, "clase A", dólares/USD...);
  4. parecido de texto alto, solo si los números del nombre (I, II, VII, 20...) son iguales
     y el segundo candidato queda lejos.
Si dos carteras caen en el mismo fondo, queda la que coincide exacto y la otra se descarta.
"""
from __future__ import annotations

import collections
import difflib
import re

from carteras_cnv import nombre_clave

RELLENO = {"abierto", "ab", "fcic", "fci", "fcia", "asg", "esg", "ley", "27260", "fondo", "fondos", "comun",
           "inversion", "de", "dinero", "en", "el", "la", "para", "c", "a"}
NUMERO = re.compile(r"^(?:[ivxl]+|\d+)$")


def simple(nombre: str) -> str:
    s = nombre_clave(nombre)
    s = re.sub(r"\bu s\b|\busd\b|\bdolares\b|\bdolar\b", "dolar", s)
    s = re.sub(r"\bpyme\b", "pymes", s)
    s = re.sub(r"\bclase [a-z0-9]\b", "", s)
    s = re.sub(r"\bmoney markets?\b", "money market", s)
    s = re.sub(r"\bargentinas?\b", "argentina", s)
    return " ".join(t for t in s.split() if t not in RELLENO)


def numeros(s: str) -> list[str]:
    return [t for t in s.split() if NUMERO.match(t)]


class Cruce:
    def __init__(self, clases: list[dict]):
        self.claves = {c.get("clave") for c in clases if c.get("clave")}
        self.por_gerente = collections.defaultdict(set)
        for c in clases:
            if c.get("clave"):
                self.por_gerente[c.get("gerente")].add(c["clave"])
        self._simple = {k: simple(k) for k in self.claves}

    def emparejar(self, cart: dict) -> tuple[str | None, str]:
        """Devuelve (clave CAFCI, cómo se encontró)."""
        crudo = nombre_clave(cart.get("fondo") or "")
        cands = self.por_gerente.get(cart.get("gerente")) or set()
        if crudo and crudo in cands:
            return crudo, "exacto"
        if cart.get("clave") in self.claves:
            return cart["clave"], "exacto"
        if not cands:
            return None, "gestora sin fondos en CAFCI"
        nombres = [n for n in (simple(cart.get("fondo") or ""), simple(cart.get("clave") or "")) if n]
        for n in nombres:
            iguales = [k for k in cands if self._simple[k] == n]
            if len(iguales) == 1:
                return iguales[0], "nombre simplificado"
        puntajes = []
        for k in cands:
            sk = self._simple[k]
            if not any(numeros(n) == numeros(sk) for n in nombres):
                continue
            puntajes.append((max(difflib.SequenceMatcher(None, n, sk).ratio() for n in nombres), k))
        puntajes.sort(reverse=True)
        if puntajes and puntajes[0][0] >= 0.88 and (len(puntajes) == 1 or puntajes[0][0] - puntajes[1][0] >= 0.06):
            return puntajes[0][1], "parecido"
        return None, "sin cruce"

    def todas(self, carteras: dict[str, dict]) -> dict[str, tuple[str | None, str]]:
        """carteras: {id_cnv: cartera}. Resuelve choques (dos carteras al mismo fondo)."""
        res = {i: self.emparejar(c) for i, c in carteras.items()}
        por_clave = collections.defaultdict(list)
        for i, (k, _) in res.items():
            if k:
                por_clave[k].append(i)
        for k, ids in por_clave.items():
            if len(ids) < 2:
                continue
            exactos = [i for i in ids if nombre_clave(carteras[i].get("fondo") or "") == k]
            quedan = exactos[:1] or [i for i in ids if res[i][1] == "exacto"][:1]
            for i in ids:
                if i not in quedan:
                    res[i] = (None, f"choca con otra cartera en '{k}'")
        return res
