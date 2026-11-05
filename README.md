# Comparador de FCI

Comparador de fondos comunes de inversión argentinos: rendimiento, patrimonio, gestoras y un índice propio de solidez (0 a 100).

Datos en vivo de [compararfondos.com.ar](https://compararfondos.com.ar/) (fuente CAFCI/CNV). Es una página estática (`index.html`) que se puede servir con GitHub Pages.

La información es informativa y no constituye recomendación de inversión.

## Datos automáticos (CAFCI)

`pipeline/actualizar.py` baja todas las noches la planilla diaria pública de CAFCI y el catálogo de fondos, calcula el flujo neto estimado de cada fondo y escribe JSON estáticos en `data/`:

- `data/ultimo.json`: todos los fondos del último día.
- `data/web/`: catálogo y una ficha por fondo que lee la página.
- `data/historico/<fecha>.json`: el histórico se arma día a día.
- `data/estructura_planilla.json`: columnas detectadas, para controlar si CAFCI cambia el formato.

Lo corre `.github/workflows/datos-diarios.yml` de martes a sábado a las 22:30 (hora argentina). También se puede lanzar a mano desde la pestaña Actions.

Flujo neto estimado = patrimonio de hoy − patrimonio de ayer × (cuotaparte de hoy / cuotaparte de ayer).

Pruebas: `pip install -r pipeline/requirements.txt pytest && pytest pipeline`.

## Carteras semanales (CNV)

`pipeline/carteras_cnv.py` lee la cartera de cada fondo de su ficha pública en la CNV (`cnv.gov.ar/SitioWeb/FondosComunesInversion/DetallesFCI/{id}`, sección "Composición Semanal Cartera"): totales por tipo de activo y cada activo con su % del patrimonio. El listado de fondos sale de `GetFCIPorTipo`. Escribe `data/carteras/ultima/<id>.json` y un histórico por fecha. Lo corre `.github/workflows/carteras-semanales.yml` los sábados, con 1 segundo de pausa entre fondos.

Planilla y carteras se cruzan por el campo `clave` (nombre del fondo normalizado, sin prefijo de la CNV, "F.C.I." ni "Clase").

## Comparador de bonos

`pipeline/tasas.js` lee las tablas de la calculadora de renta fija (precios de cierre BYMA) y `pipeline/bonos.py` arma `data/web/bonos.json`: un renglón por bono o letra con precio, tasa, duración, vencimiento y los fondos que lo tienen según las carteras de la CNV. La página lo muestra en `#bonos`: se tildan dos y se ven lado a lado (link para compartir: `#bonos/GD30,AL30`). Corre en la misma tanda nocturna de `datos-diarios.yml`.
