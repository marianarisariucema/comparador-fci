// Prueba del componente en un navegador de verdad, con los datos estáticos de data/web.
// Uso: node api/test/navegador.e2e.mjs   (necesita el paquete playwright con Chromium)
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const RAIZ = join(fileURLToPath(new URL('.', import.meta.url)), '..', '..');
const { chromium } = createRequire(import.meta.url)('playwright');
const TIPOS = { '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json' };

const srv = createServer(async (req, res) => {
  const ruta = normalize(decodeURIComponent(new URL(req.url, 'http://x').pathname)).replace(/^(\.\.[/\\])+/, '');
  try { res.writeHead(200, { 'Content-Type': TIPOS[extname(ruta)] || 'application/octet-stream' }); res.end(await readFile(join(RAIZ, ruta))); }
  catch { res.writeHead(404); res.end(); }
}).listen(0);
const base = `http://localhost:${srv.address().port}`;
const fallas = [];
const chequear = (ok, msj) => { console.log((ok ? 'ok   ' : 'FALLA ') + msj); if (!ok) fallas.push(msj); };

const b = await chromium.launch();
try {
  for (const [nombre, vp] of [['escritorio', { width: 1200, height: 900 }], ['celular', { width: 375, height: 740 }]]) {
    const p = await b.newPage({ viewport: vp });
    const errores = [];
    p.on('pageerror', e => errores.push(e.message));
    p.on('console', m => m.type() === 'error' && errores.push(m.text()));
    await p.goto(base + '/embed/demo.html');
    await p.waitForSelector('fondos-fci >> .item', { timeout: 20000 });
    chequear(await p.locator('fondos-fci >> .item').count() > 0, `${nombre}: el buscador lista fondos`);
    await p.waitForSelector('fondos-fci-etiqueta >> .que', { timeout: 20000 });
    chequear(await p.locator('fondos-fci-etiqueta >> .que').count() >= 5, `${nombre}: las etiquetas aparecen en la tabla del broker`);
    await p.locator('fondos-fci-etiqueta').first().locator('.que').click();
    await p.waitForSelector('fondos-fci-etiqueta >> dialog .ficha', { timeout: 20000 });
    chequear(await p.locator('fondos-fci-etiqueta >> dialog [data-comp] .comp-row').count() >= 1, `${nombre}: la ficha compara contra inflación`);
    await p.keyboard.press('Escape');
    await p.locator('fondos-fci >> .pill[data-obj="dolar"]').click();
    await p.locator('fondos-fci >> .item').first().click();
    await p.waitForSelector('fondos-fci >> .ficha');
    const det = await p.evaluate(() => new Promise(r => {
      document.addEventListener('fci-invertir', e => r(e.detail), { once: true });
      document.querySelector('fondos-fci').shadowRoot.querySelector('[data-accion="invertir"]').click();
    }));
    chequear(!!det && !!det.id, `${nombre}: el botón Invertir avisa a la ALyC (${det && det.id})`);
    const ancho = await p.evaluate(() => document.documentElement.scrollWidth);
    chequear(ancho <= vp.width, `${nombre}: no hay desplazamiento horizontal (${ancho}px)`);
    chequear(errores.length === 0, `${nombre}: sin errores en la consola ${errores.length ? JSON.stringify(errores) : ''}`);
    await p.close();
  }
} finally {
  await b.close();
  srv.close();
}
if (fallas.length) { console.error(`\n${fallas.length} fallas`); process.exit(1); }
console.log('\nComponente OK en navegador.');
