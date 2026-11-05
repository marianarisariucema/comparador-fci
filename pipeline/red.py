"""Pedidos HTTP con reintentos.

Las fuentes públicas (CAFCI, BCRA, ArgentinaDatos, CNV, GitHub) a veces
responden 5xx, 429 o cortan la conexión unos minutos. Antes de dar la
corrida por fallida se reintenta con esperas crecientes.
"""
from __future__ import annotations

import sys
import time

import requests

REINTENTABLES = {408, 425, 429, 500, 502, 503, 504, 520, 522, 524}


def pedir(url: str, *, sesion: requests.Session | None = None, metodo: str = "GET",
          intentos: int = 4, espera: float = 5.0, timeout: float = 60, **kwargs) -> requests.Response:
    """Hace el pedido y reintenta ante errores de red o respuestas transitorias.

    Devuelve la respuesta tal cual (también un 404 o un 403: esos no se arreglan
    reintentando). Si se agotan los intentos, relanza el último error o devuelve
    la última respuesta transitoria.
    """
    cliente = sesion or requests
    ultimo_error: Exception | None = None
    for n in range(1, intentos + 1):
        try:
            r = cliente.request(metodo, url, timeout=timeout, **kwargs)
            if r.status_code not in REINTENTABLES or n == intentos:
                return r
            motivo = f"HTTP {r.status_code}"
        except (requests.ConnectionError, requests.Timeout) as e:
            ultimo_error = e
            motivo = type(e).__name__
            if n == intentos:
                raise
        pausa = espera * (3 ** (n - 1))
        print(f"  {url}: {motivo}, reintento {n}/{intentos - 1} en {pausa:.0f} s", file=sys.stderr)
        time.sleep(pausa)
    raise ultimo_error or RuntimeError(f"Sin respuesta de {url}")  # no debería llegar acá
