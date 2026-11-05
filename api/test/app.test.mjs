import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { crearApp } from '../src/app.js';
import { origenPermitido, verificarToken, emitirToken, resolverId, Limitador, DetectorBarrido } from '../src/lib.js';

const h = k => createHash('sha256').update(k).digest('hex');
const PK = 'pk_test_abc', SK = 'sk_test_xyz', PK2 = 'pk_otro_123';
const HOY = Date.parse('2026-11-05T12:00:00Z');
const clientes = [
  { id: 'alyc', nombre: 'ALyC', claves_publicas: [h(PK)], claves_secretas: [h(SK)], origenes: ['https://www.alyc.com.ar', 'https://*.alyc.com.ar'], fondos: null, tema: { marca: '#123456' } },
  { id: 'chico', nombre: 'Chico', claves_publicas: [h(PK2)], claves_secretas: [], origenes: ['https://chico.com'], fondos: ['fondo-a'], limite_por_minuto: 3, max_fichas_10_min: 2 },
  { id: 'vencido', nombre: 'V', vence: '2026-01-01', claves_publicas: [h('pk_v_1')], origenes: ['https://v.com'] },
];
const archivos = {
  '/datos/catalogo.json': { fecha: '2026-11-04', cantidad: 3, fondos: [{ id: 'fondo-a' }, { id: 'fondo-b' }, { id: 'fondo-c' }] },
  '/datos/referencias.json': { fecha: '2026-11-04', periodos: {} },
  '/datos/ids.json': { cafci: { '6419': 'fondo-b' }, cnv: {}, clase: {} },
  '/datos/fondos/fondo-a.json': { id: 'fondo-a', nombre: 'A' },
  '/datos/fondos/fondo-b.json': { id: 'fondo-b', nombre: 'B' },
  '/datos/fondos/fondo-c.json': { id: 'fondo-c', nombre: 'C' },
  '/widget/fondos-fci.js': 'export {}',
};
const env = {
  FIRMA_SECRETA: 'secreto-de-prueba',
  ASSETS: { fetch: async r => { const p = new URL(r.url).pathname; const x = archivos[p];
    return x === undefined ? new Response('no', { status: 404 }) : new Response(typeof x === 'string' ? x : JSON.stringify(x)); } },
};
const nueva = () => crearApp(clientes, { ahora: () => HOY });
const pedir = (app, ruta, { clave, origen, metodo = 'GET', cuerpo, ip = '1.1.1.1', auth } = {}) => {
  const headers = { 'CF-Connecting-IP': ip };
  if (clave) headers['X-Clave'] = clave;
  if (auth) headers.Authorization = 'Bearer ' + auth;
  if (origen) headers.Origin = origen;
  return app.fetch(new Request('https://api.test' + ruta, { method: metodo, headers, body: cuerpo ? JSON.stringify(cuerpo) : undefined }), env);
};

test('sin clave no hay datos', async () => {
  const r = await pedir(nueva(), '/v1/catalogo');
  assert.equal(r.status, 401);
});

test('clave pública desde dominio permitido: datos + CORS + huella', async () => {
  const r = await pedir(nueva(), '/v1/catalogo', { clave: PK, origen: 'https://www.alyc.com.ar' });
  assert.equal(r.status, 200);
  assert.equal(r.headers.get('Access-Control-Allow-Origin'), 'https://www.alyc.com.ar');
  assert.equal(r.headers.get('X-Licencia'), 'alyc');
  const d = await r.json();
  assert.equal(d.fondos.length, 3);
  assert.equal(d._licencia.cliente, 'alyc');
  assert.match(d._licencia.huella, /^[A-Za-z0-9_-]{16}$/);
});

test('subdominio con comodín permitido', async () => {
  const r = await pedir(nueva(), '/v1/fondos/fondo-a', { clave: PK, origen: 'https://app.alyc.com.ar' });
  assert.equal(r.status, 200);
});

test('clave pública desde otro dominio o sin dominio: rechazada', async () => {
  assert.equal((await pedir(nueva(), '/v1/catalogo', { clave: PK, origen: 'https://copion.com' })).status, 403);
  assert.equal((await pedir(nueva(), '/v1/catalogo', { clave: PK, origen: 'https://alyc.com.ar.copion.com' })).status, 403);
  assert.equal((await pedir(nueva(), '/v1/catalogo', { clave: PK })).status, 403);
});

test('clave secreta: sirve desde servidor, se rechaza desde navegador y en la URL', async () => {
  assert.equal((await pedir(nueva(), '/v1/catalogo', { auth: SK })).status, 200);
  assert.equal((await pedir(nueva(), '/v1/catalogo', { auth: SK, origen: 'https://www.alyc.com.ar' })).status, 403);
  assert.equal((await pedir(nueva(), '/v1/catalogo?clave=' + SK)).status, 400);
});

test('token: se emite con clave secreta, vale para su dominio y vence', async () => {
  const app = nueva();
  assert.equal((await pedir(app, '/v1/token', { metodo: 'POST', clave: PK, origen: 'https://www.alyc.com.ar' })).status, 403);
  const r = await pedir(app, '/v1/token', { metodo: 'POST', auth: SK, cuerpo: { origen: 'https://www.alyc.com.ar', minutos: 15 } });
  assert.equal(r.status, 200);
  const { token } = await r.json();
  assert.equal((await pedir(app, '/v1/catalogo', { auth: token, origen: 'https://www.alyc.com.ar' })).status, 200);
  assert.equal((await pedir(app, '/v1/catalogo', { auth: token, origen: 'https://app.alyc.com.ar' })).status, 403);
  const vencido = crearApp(clientes, { ahora: () => HOY + 16 * 60000 });
  assert.equal((await pedir(vencido, '/v1/catalogo', { auth: token, origen: 'https://www.alyc.com.ar' })).status, 401);
  const trucho = token.slice(0, -2) + (token.endsWith('AA') ? 'BB' : 'AA');
  assert.equal((await pedir(app, '/v1/catalogo', { auth: trucho, origen: 'https://www.alyc.com.ar' })).status, 401);
});

test('token para un dominio que el cliente no tiene: rechazado', async () => {
  const r = await pedir(nueva(), '/v1/token', { metodo: 'POST', auth: SK, cuerpo: { origen: 'https://copion.com' } });
  assert.equal(r.status, 400);
});

test('cliente vencido o inactivo: cortado', async () => {
  assert.equal((await pedir(nueva(), '/v1/catalogo', { clave: 'pk_v_1', origen: 'https://v.com' })).status, 403);
});

test('cliente con lista de fondos solo ve los suyos', async () => {
  const app = nueva();
  const d = await (await pedir(app, '/v1/catalogo', { clave: PK2, origen: 'https://chico.com' })).json();
  assert.deepEqual(d.fondos.map(f => f.id), ['fondo-a']);
  assert.equal((await pedir(app, '/v1/fondos/fondo-b', { clave: PK2, origen: 'https://chico.com', ip: '2.2.2.2' })).status, 404);
});

test('límite por minuto', async () => {
  const app = nueva();
  const estados = [];
  for (let i = 0; i < 5; i++) estados.push((await pedir(app, '/v1/referencias', { clave: PK2, origen: 'https://chico.com', ip: '9.9.9.9' })).status);
  assert.deepEqual(estados, [200, 200, 200, 429, 429]);
});

test('barrido de fichas: corta al robot que pide muchas distintas', async () => {
  const cl = [{ ...clientes[0], max_fichas_10_min: 2 }];
  const app = crearApp(cl, { ahora: () => HOY });
  const o = { clave: PK, origen: 'https://www.alyc.com.ar', ip: '7.7.7.7' };
  assert.equal((await pedir(app, '/v1/fondos/fondo-a', o)).status, 200);
  assert.equal((await pedir(app, '/v1/fondos/fondo-b', o)).status, 200);
  assert.equal((await pedir(app, '/v1/fondos/fondo-a', o)).status, 200); // repetir no suma
  assert.equal((await pedir(app, '/v1/fondos/fondo-c', o)).status, 429);
});

test('códigos de la ALyC: cafci:<código> resuelve al fondo', async () => {
  const r = await pedir(nueva(), '/v1/fondos/cafci:6419', { clave: PK, origen: 'https://www.alyc.com.ar' });
  assert.equal(r.status, 200);
  assert.equal((await r.json()).id, 'fondo-b');
});

test('ids raros no llegan a los archivos', async () => {
  for (const id of ['..%2F..%2Fcatalogo', '%2e%2e', 'A B', 'x'.repeat(200), 'cafci:nada']) {
    const r = await pedir(nueva(), '/v1/fondos/' + id, { clave: PK, origen: 'https://www.alyc.com.ar' });
    const txt = await r.text();
    assert.ok(r.status === 404 || !/"nombre"|"fondos"/.test(txt), id); // "%2e%2e" el URL lo normaliza a /v1 (sin datos)
  }
});

test('los archivos de datos no se pueden pedir directo', async () => {
  for (const ruta of ['/datos/catalogo.json', '/datos/fondos/fondo-a.json', '/catalogo.json']) {
    assert.equal((await pedir(nueva(), ruta)).status, 404, ruta);
  }
});

test('preflight CORS solo para dominios de clientes vigentes', async () => {
  assert.equal((await pedir(nueva(), '/v1/catalogo', { metodo: 'OPTIONS', origen: 'https://www.alyc.com.ar' })).status, 204);
  assert.equal((await pedir(nueva(), '/v1/catalogo', { metodo: 'OPTIONS', origen: 'https://copion.com' })).status, 403);
  assert.equal((await pedir(nueva(), '/v1/catalogo', { metodo: 'OPTIONS', origen: 'https://v.com' })).status, 403);
});

test('salud: pública, sin datos, avisa si están viejos', async () => {
  const r = await pedir(nueva(), '/v1/salud');
  assert.equal(r.status, 200);
  const d = await r.json();
  assert.equal(d.dias_de_atraso, 1);
  const tarde = crearApp(clientes, { ahora: () => HOY + 10 * 86400000 });
  assert.equal((await pedir(tarde, '/v1/salud')).status, 503);
});

test('el componente se sirve público', async () => {
  const r = await pedir(nueva(), '/widget/fondos-fci.js');
  assert.equal(r.status, 200);
  assert.match(r.headers.get('Content-Type'), /javascript/);
});

test('origenPermitido: casos borde', () => {
  assert.ok(origenPermitido('http://localhost:5173', ['http://localhost:*']));
  assert.ok(!origenPermitido('https://localhost:5173', ['http://localhost:*']));
  assert.ok(!origenPermitido('https://alyc.com.ar', ['https://*.alyc.com.ar']));
  assert.ok(!origenPermitido('https://evilalyc.com.ar', ['https://*.alyc.com.ar']));
  assert.ok(!origenPermitido('null', ['https://a.com']));
  assert.ok(!origenPermitido('https://a.com/path', ['https://a.com']));
});

test('tokens: firma y vencimiento', async () => {
  const { token } = await emitirToken('s', { cliente: 'x' }, HOY);
  assert.equal((await verificarToken('s', token, HOY)).c, 'x');
  assert.equal(await verificarToken('otro', token, HOY), null);
  assert.equal(await verificarToken('s', token, HOY + 3600000), null);
});

test('resolverId y limitadores', () => {
  assert.equal(resolverId('Fima-Premium', null), 'fima-premium');
  assert.equal(resolverId('cafci:__proto__', { cafci: {} }), null);
  const l = new Limitador();
  assert.ok(l.permitir('a', 1, 0)); assert.ok(!l.permitir('a', 1, 1)); assert.ok(l.permitir('a', 1, 60001));
  const d = new DetectorBarrido();
  assert.ok(d.registrar('a', 'x', 1, 0)); assert.ok(!d.registrar('a', 'y', 1, 1));
});

test('iframe /embed/<cliente>: token atado al dominio de la API y solo enmarcable por el cliente', async () => {
  archivos['/demo/iframe.html'] = '<meta name="fci-api" content=""><meta name="fci-token" content="">';
  const app = nueva();
  const r = await pedir(app, '/embed/alyc');
  assert.equal(r.status, 200);
  assert.match(r.headers.get('Content-Security-Policy'), /frame-ancestors https:\/\/www\.alyc\.com\.ar https:\/\/\*\.alyc\.com\.ar;/);
  assert.equal(r.headers.get('X-Frame-Options'), null);
  const token = /fci-token" content="([^"]+)"/.exec(await r.text())[1];
  assert.equal((await pedir(app, '/v1/catalogo', { auth: token, origen: 'https://api.test' })).status, 200);
  assert.equal((await pedir(app, '/v1/catalogo', { auth: token, origen: 'https://copion.com' })).status, 403);
  assert.equal((await pedir(app, '/embed/vencido')).status, 404);
  assert.equal((await pedir(app, '/embed/no-existe')).status, 404);
});

test('mismo dominio sin Origin: se usa el Referer', async () => {
  const app = nueva();
  const r = await app.fetch(new Request('https://api.test/v1/catalogo', { headers: { 'X-Clave': PK, Referer: 'https://www.alyc.com.ar/fondos' } }), env);
  assert.equal(r.status, 200);
  const r2 = await app.fetch(new Request('https://api.test/v1/catalogo', { headers: { 'X-Clave': PK, Referer: 'https://copion.com/' } }), env);
  assert.equal(r2.status, 403);
});
