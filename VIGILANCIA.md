# Vigilancia: cómo se cuida solo el comparador

Todo corre en GitHub Actions, de noche, como scripts comunes (sin Claude, sin claves, sin la PC).

## Qué pasa cada noche

| Hora (AR) | Qué corre | Si falla |
| --- | --- | --- |
| 22:30 mar a sáb | **Datos diarios CAFCI** (planilla, BCRA, análisis, rendimientos, página) | Cada descarga reintenta 3 veces con esperas de 5, 15 y 45 s. Si igual falla, el paso no pisa nada: queda publicado el último dato bueno. |
| Apenas termina | **Vigilancia** revisa los datos | Si faltan o quedaron a medias, relanza el workflow (máximo 2 veces por día). |
| 2:30 todos los días | **Vigilancia** | Por si la corrida de las 22:30 nunca arrancó (GitHub a veces saltea horarios). |
| 2:00 sábados | **Carteras CNV** | Vigilancia la relanza una vez si quedó vieja o con pocas carteras. |
| 7:00 todos los días | **Vigilancia**, veredicto de la mañana | Si algo sigue roto y no se arregla solo, abre un issue **"⚠️ El comparador necesita una mano"**. GitHub te manda un mail. Cuando se arregla, el issue se cierra solo. |

Si no te llega ningún mail, está todo bien. El detalle de cada chequeo está en *Actions → Vigilancia → la corrida → Summary*.

## Protecciones del último dato bueno

- **Planilla CAFCI** (`pipeline/actualizar.py`): no se publica si trae una fecha más vieja que la publicada, si trae 30% menos clases que la anterior o si menos del 80% de las clases tiene cuotaparte (señal de columnas corridas).
- **BCRA** (`pipeline/bcra.py`): si una serie viene con menos de la mitad de los puntos que ya había, se conserva la anterior.
- **Guardado**: si dos corridas guardan a la vez, el push reintenta 4 veces. `datos-diarios` nunca corre dos veces en paralelo.
- **Pruebas** (`.github/workflows/pruebas.yml`): cada cambio al código corre las pruebas antes de llegar a `main`, para que un error no rompa la corrida de la noche.
- **Versiones**: `requirements.txt` tiene techo de versión mayor, así una versión nueva de pandas no rompe nada de un día para el otro.

## Qué revisa (`pipeline/salud.py`)

| Chequeo | Aviso (no molesta) | Error (abre issue) |
| --- | --- | --- |
| Planilla al día (descuenta fines de semana y feriados nacionales de ArgentinaDatos) | 1 día hábil de atraso | 2 o más |
| Cantidad de clases | 10% menos que el día anterior | menos de 2.500 |
| Calidad | >5% sin cuotaparte, patrimonios negativos, >1% con saltos de más de 25% en un día | — |
| Formato de la planilla | — | CAFCI cambió columnas |
| Rendimientos, análisis, datos de la página | quedaron de un día anterior a la planilla; períodos con muy pocos fondos | siguen así después de 2 reintentos |
| BCRA | alguna serie atrasada | 4 o más series atrasadas |
| Carteras CNV | cartera típica de más de 30 días | más de 45 días o menos de 800 carteras |
| Precios BYMA (calculadora) | 3 a 5 días hábiles | más de 5 |
| Página publicada | muestra otra fecha que el repo | no responde |
| Workflows | la última corrida falló | las dos últimas fallaron |
| Tamaño del repo | más de 1 GB | más de 3 GB |

## Qué hacer si llega el mail

| Dice | Qué hacer |
| --- | --- |
| Formato de la planilla CAFCI | CAFCI cambió columnas. Pedirle a Claude: "la vigilancia dice que cambió la planilla, ajustá `actualizar.py`". |
| Planilla con 2+ días de atraso | Entrar a cafci.org.ar. Si allá tampoco está, es de ellos: esperar. Si está, abrir la corrida fallida en Actions y pasarle el error a Claude. |
| Precios BYMA viejos | Es el repo `calculadora-renta-fija`: revisar que su workflow corra y que las credenciales BYMA no hayan vencido. |
| Carteras CNV | Probar abrir una ficha en cnv.gov.ar. Si la CNV cambió la página, pedirle a Claude que ajuste `carteras_cnv.py`. |
| Workflows fallaron dos veces | Abrir el link del issue, copiar el error y pasárselo a Claude. |
| Tamaño del repo | Ver la propuesta 1 de abajo. |

Para correrlo a mano: *Actions → Vigilancia → Run workflow*. Local: `python pipeline/salud.py --sin-red`.

## Propuestas para hacerlo más autónomo y eficiente

Ordenadas por impacto. Ninguna está hecha todavía.

1. **Sacar los datos de `main`.** Antes de sacar `data/fichas/` (5/11) cada noche sumaba 2 a 3 MB comprimidos al repo; ahora bastante menos, pero igual crece todos los días. Opciones: publicar `data/` con `actions/deploy-pages` en vez de commitearla, o guardarla en una rama `datos` que se reescribe. La vigilancia avisa al pasar 1 GB.
2. **Plan B si CAFCI falla:** completar el día con ArgentinaDatos (cuotaparte y patrimonio) marcándolo como dato parcial, para que la página nunca muestre un hueco.
3. **Aviso en la página:** si `ultimo.json` tiene más de 2 días hábiles, mostrar "Datos al dd/mm, actualizándose" en vez de números viejos sin explicación.
4. **Avisos por Telegram o WhatsApp** además del mail: hace falta crear un bot y guardar su token como secreto.
5. **Dependabot para las Actions:** propone actualizaciones de seguridad una vez por mes; con las pruebas en verde se podrían aprobar solas.
6. **Copia de respaldo:** subir una vez por semana un `.zip` de `data/` como *Release*, por si alguien borra o rompe el repo.
