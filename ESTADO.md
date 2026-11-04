# Estado del proyecto (actualizado 4/11/2026)

Producto: módulo **marca blanca** de análisis didáctico de FCI para ALyCs y bancos (ej. Cohen). El inversor que solo ve nombres de fondos entiende qué es cada fondo, en qué invierte, a qué está atado, cuánto maneja, cuánta plata entra o sale y cómo le fue.

## Dónde está todo

| Qué | Dónde |
| --- | --- |
| Definición de producto (visión, usuarios, pantallas, datos, MVP, riesgos) | [Documento en Claude](https://claude.ai/artifact/8QEoUqsovNamA8FuJmRUXu) |
| Código y datos | Este repo: https://github.com/marianarisariucema/comparador-fci |
| Página publicada (prototipo viejo, todavía lee de compararfondos) | https://marianarisariucema.github.io/comparador-fci/ |
| Copia de trabajo en el proyecto | carpeta `comparador-fci/repo/` de los archivos del proyecto |
| Pruebas hechas en la PC de escritorio | `C:\Users\mrisari\Desktop\Maestria\FCI` (no hace falta para seguir) |

Nada depende de la compu de escritorio: todo corre en GitHub Actions.

## Fuentes de datos (todas oficiales y gratis, sin Fonditos)

| Dato | Fuente | Script | Frecuencia |
| --- | --- | --- | --- |
| Cuotaparte, patrimonio, flujo del día, honorarios, comisiones, mínimo, plazo, categoría, gerente | Planilla diaria CAFCI `api.pub.cafci.org.ar/pb_get` (~4.284 clases) | `pipeline/actualizar.py` | Mar a sáb 22:30 (hora AR) |
| Cartera: % por tipo de activo y cada activo | Ficha CNV `cnv.gov.ar/SitioWeb/FondosComunesInversion/DetallesFCI/{id}` (semanal, con atraso) | `pipeline/carteras_cnv.py` | Sábados 9:00 |
| Dólar, BADLAR, TAMAR, plazo fijo 30 días, inflación, REM, CER, UVA | API BCRA v4.0 | `pipeline/bcra.py` | Con la planilla diaria |
| Histórico de cuotaparte (para completar hacia atrás) | ArgentinaDatos `api.argentinadatos.com/v1/finanzas/fci/{categoria}/{AAAA/MM/DD}` | pendiente | Una vez |
| Precios de bonos, letras, acciones | BYMA Data gratis (con demora, sin histórico) | pendiente | — |

No funcionan: API vieja de CAFCI y `estadisticas.cafci.org.ar` (bloqueadas, 403).

## Datos que genera el repo (`data/`)

- `ultimo.json`: todos los fondos del último día. `fichas/<clase>.json`: uno por clase. `historico/<fecha>.json`: se arma día a día.
- `carteras/ultima/<id_cnv>.json` y `carteras/historico/<fecha>/`: carteras. `carteras/listado_cnv.json`: 1.668 abiertos + 45 cerrados.
- `bcra/<indicador>.json`: series de 2 años.
- Planilla y carteras se cruzan por el campo `clave` (nombre normalizado). Cruza solo el 84% de los fondos; el resto se mapea a mano.

## Pendiente para mañana

1. **Clave (EOD o BYMA):** no generar una nueva hasta tener abierto GitHub. Al generarla, pegarla enseguida en *Settings → Secrets and variables → Actions → New repository secret* con el nombre `EOD_API_KEY` (o `BYMA_API_KEY`) y guardarla también en un gestor de contraseñas. Los datos gratis de BYMA **no** necesitan clave. Falta confirmar para qué servicio es.
2. **Ficha didáctica:** armar la página nueva sobre los datos propios (`data/`), con: en una frase, tipo, patrimonio, en qué invierte, a qué está atado, flujos y rendimiento contra inflación, dólar y plazo fijo.
3. Completar el histórico con ArgentinaDatos.
4. Calcular rankings por gestora, AUM, facturación estimada y "qué fondos tienen tal activo".
5. Revisar los términos de uso de BYMA Data antes de mostrar precios.
6. Elegir la ALyC objetivo y mapear a mano sus 30 a 60 fondos entre CAFCI y CNV.
7. Contactos a evaluar: CAFCI (acceso formal) y, si se quisiera, Fonditos (licencia de redistribución). El socio prefiere no depender de Fonditos.

## Cómo retomar

Abrí el proyecto "fondos" en Claude desde la laptop y escribí en el hilo "Definir producto marca blanca de análisis de FCI" (o en el chat del proyecto): *"seguimos con el comparador, leé ESTADO.md"*. No hace falta instalar nada.
