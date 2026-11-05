# Seguridad: que no se copien el producto

## Qué hay para robar y cuánto vale

| Qué | Dónde está hoy | Riesgo | Valor |
| --- | --- | --- | --- |
| **Código del robot** (lectura de CNV y CAFCI, cruce de fondos, clasificación "a qué está atado", textos didácticos, rendimientos) | Repo **público** | Alto: cualquiera lo copia con un clic | Es el corazón del producto |
| **Datos procesados** (`data/`) | Repo público y GitHub Pages | Alto: se bajan enteros sin pedir permiso | Alto: meses de trabajo de cruce y limpieza |
| **Diseño y textos de la ficha** | Navegador del usuario | Inevitable: todo lo que se ve en pantalla se puede copiar | Medio: se protege con contrato y marca |
| **Claves de clientes** | Sitios de las ALyC | Medio | Si se filtra una, alguien usa el servicio a costa del cliente |
| **Cuentas** (GitHub, Cloudflare) | — | Bajo si hay doble factor | Total: quien entra se lleva todo |

Los datos de base son públicos (CAFCI, CNV, BCRA), así que nadie puede impedir que otro arme lo mismo desde cero. Lo que se protege es el trabajo hecho encima, y la ventaja real es llegar antes y tener los clientes.

## Hecho en esta rama

1. **API con llave** (`api/`, Cloudflare Workers, plan gratis). Los datos dejan de servirse como archivos sueltos: cada pedido pasa por un control.
   - Clave por cliente. Las claves no están en el repo: solo su huella SHA-256.
   - **Clave pública atada a dominios.** Copiada en otro sitio no funciona.
   - **Clave secreta solo para servidores.** Si aparece en un navegador, se rechaza (quiere decir que se filtró).
   - **Tokens de 15 minutos** firmados, para que ni la clave pública tenga que estar en la página.
   - **Cada cliente ve solo sus fondos** (opcional) y tiene **fecha de vencimiento**: si no renueva, se corta solo.
   - **Límite por minuto** por cliente e IP, y **corte de descargas masivas**: quien pide más de 150 fichas distintas en 10 minutos queda bloqueado 10 minutos.
   - **Huella en cada respuesta** (`_licencia` y encabezado `X-Licencia`): si los datos aparecen copiados en otro lado, la huella dice de qué cliente salieron.
   - Los archivos de datos no se pueden pedir directo: `/datos/...` devuelve 404.
   - Registro de cada pedido (cliente, ruta, IP) en los logs de Cloudflare.
   - 22 pruebas automáticas que corren antes de cada publicación (`api/test/`).
2. **iframe solo para los dominios del cliente** (`frame-ancestors`): el navegador lo bloquea en cualquier otro sitio.
3. **Componente sin dependencias externas** y con Shadow DOM: no carga código de terceros (nadie puede meter código malicioso por ahí) y no interfiere con el sitio de la ALyC.
4. **Componente minificado** en la versión publicada, con aviso de licencia.
5. **Publicación con permisos mínimos**: el workflow solo puede leer el repo; las credenciales de Cloudflare son secretos de GitHub.
6. **Licencia propietaria** en el repo (`LICENSE`): deja por escrito que no se puede usar sin permiso.

## Lo que falta y solo puede hacer Mariana

En orden de importancia:

1. **Hacer el repo privado.** *Settings → General → Danger Zone → Change visibility → Private.* Hoy el código y los datos están a la vista de cualquiera (por ahora sin forks ni visitas registradas, así que es buen momento).
   - GitHub Pages deja de funcionar en un repo privado del plan gratis. La demo pasa a vivir en la API (`/demo`). Si se quiere seguir con Pages, GitHub Pro cuesta US$ 4 por mes.
   - Los robots nocturnos siguen andando. En repo privado hay 2.000 minutos gratis por mes; hoy se usan unos 750 (carteras ~2 h por semana + planilla diaria).
   - Lo mismo conviene revisar en `calculadora-renta-fija`: también es pública.
2. **Doble factor** en GitHub y en Cloudflare (*Settings → Password and authentication*). Es la medida más barata y la que más protege.
3. **Activar la API** (ver `docs/integracion.md`, "Poner la API en marcha"): crear la cuenta de Cloudflare y cargar 3 secretos. Hasta entonces el workflow corre las pruebas y avisa, sin fallar.
4. **Protección legal**, porque la técnica sola no alcanza:
   - Registrar el software en la Dirección Nacional del Derecho de Autor (DNDA): trámite online, barato, da fecha cierta de autoría.
   - Registrar la marca en el INPI (clase 36, servicios financieros, y 42, software).
   - Contrato de licencia con cada ALyC: uso solo en sus dominios, prohibido revender o redistribuir los datos, derecho a cortar el servicio, confidencialidad. La huella por cliente sirve como prueba si hay incumplimiento.
   - Acuerdo de confidencialidad con quien vea el código o los datos antes de firmar (incluido el período de prueba con una ALyC).
   - Dejar por escrito entre socios quién es dueño del código y de la marca.
5. **Términos de las fuentes**: revisar las condiciones de uso de BYMA Data antes de mostrar precios a terceros, y citar las fuentes oficiales (el componente ya lo hace).

## Límites (para no venderle humo a nadie)

- Todo lo que se muestra en pantalla se puede copiar a mano o con un robot lento que use una clave válida. El límite por minuto, el corte de descargas masivas y la huella lo hacen caro y rastreable, no imposible.
- El encabezado de origen lo manda el navegador. Fuera de un navegador se puede falsificar; por eso la clave pública solo da acceso a lo que ese cliente ya muestra en su sitio, con límite de uso.
- El límite por minuto y el detector de descargas cuentan por instancia del servidor. Para un límite global exacto está la regla de Rate Limiting de Cloudflare, comentada en `api/wrangler.toml` (activar si la cuenta la tiene).
- Los datos de base son públicos. La protección está en el trabajo encima de ellos, en la marca y en los contratos.
