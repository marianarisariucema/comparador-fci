// Arma api/dist con lo que sube el Worker: datos de data/web, el componente y la demo.
// Uso: node api/preparar.mjs   (lo corre el workflow antes de desplegar)
import { cpSync, mkdirSync, rmSync, readFileSync, writeFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const API = dirname(fileURLToPath(import.meta.url));
const RAIZ = join(API, '..');
const DIST = join(API, 'dist');
const WEB = join(RAIZ, 'data', 'web');

if (!existsSync(join(WEB, 'catalogo.json'))) { console.error('Falta data/web/catalogo.json: correr antes pipeline/web.py'); process.exit(1); }
rmSync(DIST, { recursive: true, force: true });
mkdirSync(join(DIST, 'widget'), { recursive: true });
mkdirSync(join(DIST, 'demo'), { recursive: true });
cpSync(WEB, join(DIST, 'datos'), { recursive: true });

const wrangler = readFileSync(join(API, 'wrangler.toml'), 'utf8');
const clave = (/DEMO_CLAVE_PUBLICA\s*=\s*"([^"]+)"/.exec(wrangler) || [])[1] || '';
const widget = process.env.WIDGET_MIN && existsSync(process.env.WIDGET_MIN) ? process.env.WIDGET_MIN : join(RAIZ, 'embed', 'fondos-fci.js');
writeFileSync(join(DIST, 'widget', 'fondos-fci.js'),
  `/*! Fondos explicados · componente <fondos-fci> · (c) ${new Date().getFullYear()} · Uso solo bajo licencia. Prohibida su copia o redistribución. */\n` + readFileSync(widget, 'utf8'));
const widgetAbs = html => html.replace(/(['"])\.\/fondos-fci\.js\1/g, "'/widget/fondos-fci.js'");
// Demo: en el Worker usa la API con la clave de demo; en GitHub Pages usa los archivos estáticos.
writeFileSync(join(DIST, 'demo', 'index.html'), widgetAbs(readFileSync(join(RAIZ, 'embed', 'demo.html'), 'utf8'))
  .replace('<meta name="fci-api" content="">', '<meta name="fci-api" content="/v1">')
  .replace('<meta name="fci-clave" content="">', `<meta name="fci-clave" content="${clave}">`));
// iframe: la API le pone el token al servirla en /embed/<cliente>.
writeFileSync(join(DIST, 'demo', 'iframe.html'), widgetAbs(readFileSync(join(RAIZ, 'embed', 'iframe.html'), 'utf8')));
console.log('dist listo:', DIST);
