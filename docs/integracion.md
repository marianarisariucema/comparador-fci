# Integración en el sitio de una ALyC

El producto se integra de tres maneras. Las tres usan los mismos datos y la misma API, y se pueden combinar.

| Opción | Para quién | Esfuerzo de la ALyC |
| --- | --- | --- |
| **A. Etiqueta en su listado** `<fondos-fci-etiqueta>` | Ya tiene su tabla de fondos y no quiere cambiarla | Una línea por fondo |
| **B. Componente** `<fondos-fci>` / `<fondos-fci-ficha>` | Quiere una sección "Conocé los fondos" o la ficha dentro de su página | Un script y una etiqueta |
| **C. iframe** | No puede sumar scripts a su sitio (CMS cerrado, app híbrida) | Un `<iframe>` |
| **D. Solo datos (API JSON)** | Tiene equipo de front y quiere dibujar todo con su diseño | Programar las pantallas |

Demo con un broker ficticio, las tres marcas y modo oscuro: `embed/demo.html` (en GitHub Pages: `/embed/demo.html`; publicada desde la API: `/demo`).

## A. Etiqueta al lado de cada fondo

```html
<script type="module" src="https://API/widget/fondos-fci.js"></script>
<script>window.FondosFCIConfig = { api: 'https://API/v1', clave: 'pk_suclave' };</script>

<td>Fima Premium <fondos-fci-etiqueta fondo="cafci:1234"></fondos-fci-etiqueta></td>
```

Muestra el tipo de fondo y el riesgo, y un botón "¿Qué es este fondo?" que abre la ficha explicada en una ventana. Para fondo se puede usar:

- el código CAFCI de la clase que la ALyC ya tiene: `cafci:1234`
- el código CNV del fondo: `cnv:567`
- nuestro identificador: `fima-premium`

Atributos: `compacta` (solo riesgo y botón), `texto="¿Qué es?"` (texto del botón), `invertir="Suscribir"` (muestra un botón en la ficha que dispara `fci-invertir`).

## B. Buscador o ficha dentro de la página

```html
<fondos-fci invertir="Suscribir"></fondos-fci>            <!-- buscador "¿Qué querés hacer con tu plata?" + fichas -->
<fondos-fci-ficha fondo="cafci:1234"></fondos-fci-ficha>  <!-- una ficha sola -->
```

### Que se vea como el resto del sitio

El componente hereda la tipografía de la página y se ajusta con variables CSS. Ninguna es obligatoria:

```css
fondos-fci, fondos-fci-ficha, fondos-fci-etiqueta {
  --fci-marca: #1a3d7c;          /* color principal: botones, barras del fondo, selección */
  --fci-marca-texto: #fff;       /* texto sobre el color principal */
  --fci-superficie: #fff;        /* fondo de las tarjetas */
  --fci-texto: #16202a;
  --fci-suave: #5d6b78;          /* textos secundarios */
  --fci-linea: #e2e6ea;          /* bordes */
  --fci-radio: 8px;              /* redondeo */
  --fci-fuente: inherit;         /* o la tipografía de la marca */
  --fci-fuente-numeros: inherit;
  --fci-positivo: #1d7a45; --fci-negativo: #b4372b; --fci-alerta: #a36a00;
  --fci-tamano: 15px;
}
```

Modo oscuro: atributo `tema="oscuro"` o `tema="auto"` (sigue al sistema), o directamente las variables de arriba con sus colores oscuros.

Para cambios más finos están las partes (`::part()`): `ficha`, `lista`, `item`, `chip`, `boton`, `invertir`, `etiqueta`, `dialogo`, `termino`, `volver`.

```css
fondos-fci::part(boton) { text-transform: uppercase; letter-spacing: .04em; }
```

El componente usa Shadow DOM: los estilos del sitio no lo rompen y los suyos no tocan el sitio.

Los colores por defecto de cada cliente también se pueden guardar del lado nuestro (campo `tema` en `api/clientes.json`): así la ALyC no tiene que escribir CSS, y si escribe, el suyo gana.

### Eventos para conectarlo con su circuito

| Evento | Cuándo | `event.detail` |
| --- | --- | --- |
| `fci-invertir` | Tocaron el botón de invertir de la ficha | `{ id, nombre, clases }` |
| `fci-fondo` | Se abrió la ficha de un fondo (sirve para analítica) | `{ id, nombre }` |
| `fci-error` | No se pudieron cargar los datos | `{ mensaje, status, donde }` |

```js
document.addEventListener('fci-invertir', e => abrirSuscripcion(e.detail.id));
```

## C. iframe

```html
<iframe src="https://API/embed/<id-cliente>?fondo=cafci:1234&marca=%231a3d7c&invertir=Suscribir"
        style="width:100%;border:0" title="Ficha del fondo"></iframe>
<script>
addEventListener('message', e => {
  if (e.origin !== 'https://API' || e.data?.fuente !== 'fondos-fci') return;
  if (e.data.tipo === 'fci-alto') document.querySelector('iframe').style.height = e.data.alto + 'px';
  if (e.data.tipo === 'fci-invertir') abrirSuscripcion(e.data.id);
});
</script>
```

Parámetros: `fondo` (sin él, buscador completo), `marca` (color), `fuente`, `radio` (ej. `8px`), `tema` (`claro`, `oscuro`, `auto`), `invertir` (texto del botón).

Solo los dominios del cliente pueden mostrar el iframe: el navegador lo bloquea en cualquier otro sitio.

## D. Solo datos

Todas las respuestas son JSON en español. Cada una trae `_licencia` (a quién se le entregó).

| Pedido | Devuelve |
| --- | --- |
| `GET /v1/catalogo` | Un renglón por fondo habilitado: id, nombre, gerente, tipo, riesgo, moneda, plazo de rescate, patrimonio, rendimientos |
| `GET /v1/fondos/{id}` | Ficha completa. `{id}` puede ser `cafci:<código>`, `cnv:<código>` o nuestro id |
| `GET /v1/referencias` | Inflación, plazo fijo y dólar por período, para comparar |
| `GET /v1/config` | Nombre del cliente y su tema |
| `POST /v1/token` | Token de 15 minutos (ver abajo) |
| `GET /v1/salud` | Estado del servicio y fecha de los datos (público, sin datos) |

## Claves

Cada ALyC recibe:

- **Clave pública** `pk_...`: va en su página. Solo funciona desde sus dominios (los que figuren en su contrato). Si alguien la copia y la usa en otro sitio, no anda.
- **Clave secreta** `sk_...` (opcional): solo para su servidor. Sirve para pedir datos de servidor a servidor o para emitir tokens. Si se usa desde un navegador, la API la rechaza.

Opción más segura para la página: que su servidor pida un token corto y se lo dé al navegador.

```js
// En su servidor (Node, ejemplo)
const r = await fetch('https://API/v1/token', {
  method: 'POST',
  headers: { Authorization: 'Bearer ' + process.env.FCI_CLAVE_SECRETA, 'Content-Type': 'application/json' },
  body: JSON.stringify({ origen: 'https://www.su-dominio.com.ar', minutos: 15 }),
});
// → { token: "tk_...", expira: "..." }

// En su página
FondosFCI.configurar({ api: 'https://API/v1', obtenerToken: () => fetch('/fci-token').then(r => r.json()) });
```

El componente pide un token nuevo solo cuando vence.

## Alta de un cliente nuevo

1. Generar las claves: `node api/scripts/nueva-clave.mjs <id-cliente>` (imprime las claves una sola vez y sus hash).
2. Agregar el cliente en `api/clientes.json` con los **hash** (nunca las claves), sus dominios, fecha de vencimiento del contrato, y si corresponde la lista de fondos que vende (`"fondos": [...]`; `null` = todos).
3. Hacer commit. La API se vuelve a publicar sola.
4. Mandarle las claves por un canal seguro (no por mail abierto). Guardarlas en un gestor de contraseñas.

Para cortar a un cliente: `"activo": false`, o dejar que pase la fecha de `vence`. Para rotar una clave: agregar el hash nuevo, avisar, y a los días sacar el viejo.

## Poner la API en marcha (una sola vez)

1. Crear una cuenta gratis en [Cloudflare](https://dash.cloudflare.com/sign-up) y entrar una vez a **Workers & Pages** para elegir el subdominio `*.workers.dev`.
2. En Cloudflare: **Mi perfil → API Tokens → Create Token → plantilla "Edit Cloudflare Workers"**. Copiar el token.
3. En GitHub, en este repo: **Settings → Secrets and variables → Actions**:
   - `CLOUDFLARE_API_TOKEN`: el token del paso 2.
   - `CLOUDFLARE_ACCOUNT_ID`: aparece a la derecha en la portada de Workers.
   - `FIRMA_SECRETA`: un texto largo al azar (por ejemplo, 40 letras y números). No se vuelve a cambiar.
   - En la pestaña **Variables**: `API_URL` = `https://fondos-api.<subdominio>.workers.dev`.
4. **Actions → Publicar API para clientes → Run workflow.** Desde ahí se publica sola cada noche, apenas terminan de bajar los datos.
5. Cambiar `https://*.workers.dev` en el cliente `demo` de `api/clientes.json` por la dirección exacta del paso 3.

Plan gratis: 100.000 pedidos por día. Una ALyC mediana con 5.000 visitas diarias a fondos usa unos 15.000.

Opcional: dominio propio (ej. `api.fondosexplicados.com.ar`) en **Workers → Settings → Domains & Routes**.
