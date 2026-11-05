// API de datos para clientes (ALyCs). Corre como Cloudflare Worker delante de los archivos de data/web.
// Ningún archivo de datos se sirve sin pasar por acá: clave válida, dominio permitido, límite de uso y huella.
import {
  buscarCliente, clienteVigente, origenPermitido, emitirToken, verificarToken, huella,
  Limitador, DetectorBarrido, resolverId, fondoHabilitado, idValido,
} from './lib.js';

const VERSION = '1';
const MAX_FICHAS_10_MIN = 150;      // más fichas distintas que esto en 10 minutos = robot copiando
const LIMITE_DEFECTO = 120;         // pedidos por minuto por cliente y dirección IP

const SEGURIDAD = {
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'X-Frame-Options': 'DENY',
  'Cross-Origin-Resource-Policy': 'cross-origin',
  'X-Robots-Tag': 'noindex, nofollow',   // que los buscadores no indexen los datos
};

function respuesta(cuerpo, status = 200, extra = {}) {
  const h = new Headers({ ...SEGURIDAD, ...extra });
  if (typeof cuerpo !== 'string' && !(cuerpo instanceof ArrayBuffer) && cuerpo !== null) {
    cuerpo = JSON.stringify(cuerpo);
    h.set('Content-Type', 'application/json; charset=utf-8');
  }
  return new Response(cuerpo, { status, headers: h });
}

function error(status, codigo, mensaje, extra) {
  return respuesta({ error: codigo, mensaje }, status, { 'Cache-Control': 'no-store', ...extra });
}

function origenDeReferer(ref) {
  if (!ref) return null;
  try { return new URL(ref).origin; } catch { return null; }
}

function cors(origen) {
  return origen ? {
    'Access-Control-Allow-Origin': origen,
    'Access-Control-Allow-Headers': 'X-Clave, Authorization, Content-Type',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Expose-Headers': 'X-Licencia, X-Datos-Fecha',
    'Access-Control-Max-Age': '86400',
    Vary: 'Origin',
  } : { Vary: 'Origin' };
}

export function crearApp(clientes, opciones = {}) {
  const limitador = new Limitador();
  const barrido = new DetectorBarrido();
  const ahora = opciones.ahora || (() => Date.now());

  async function leerAsset(env, req, ruta) {
    const r = await env.ASSETS.fetch(new Request(new URL(ruta, req.url)));
    if (!r.ok) return null;
    return r;
  }
  async function leerJson(env, req, ruta) {
    const r = await leerAsset(env, req, ruta);
    return r ? r.json() : null;
  }

  // Quién pide: clave pública (navegador, atada a dominios), token (navegador, emitido por el servidor
  // de la ALyC) o clave secreta (servidor a servidor, nunca desde un navegador).
  async function autenticar(req, env, url) {
    // Los navegadores no mandan Origin en un GET al mismo dominio: en ese caso se usa el de Referer.
    const origen = req.headers.get('Origin') || origenDeReferer(req.headers.get('Referer'));
    const auth = req.headers.get('Authorization') || '';
    const credencial = req.headers.get('X-Clave') || (auth.startsWith('Bearer ') ? auth.slice(7).trim() : '') || url.searchParams.get('clave') || '';
    if (!credencial) return { error: error(401, 'falta_clave', 'Falta la clave de acceso (encabezado X-Clave).') };

    if (credencial.startsWith('tk_')) {
      const t = await verificarToken(env.FIRMA_SECRETA, credencial, ahora());
      if (!t) return { error: error(401, 'token_invalido', 'Token vencido o inválido. Pedí uno nuevo.') };
      const c = clientes.find(x => x.id === t.c);
      if (!clienteVigente(c, new Date(ahora()))) return { error: error(403, 'cliente_inactivo', 'El acceso de este cliente está suspendido.') };
      // Un token atado a un dominio solo sirve desde ese dominio (el de la ALyC, o el del iframe que servimos nosotros).
      if (t.o) { if (t.o !== origen) return { error: error(403, 'origen_no_permitido', 'Este token es para otro dominio.') }; }
      else if (origen && !origenPermitido(origen, c.origenes)) return { error: error(403, 'origen_no_permitido', 'Dominio no habilitado para este cliente.') };
      return { cliente: c, tipo: 'token', origen };
    }
    if (url.searchParams.get('clave') && credencial.startsWith('sk_'))
      return { error: error(400, 'clave_secreta_en_url', 'La clave secreta nunca va en la URL.') };

    const r = await buscarCliente(clientes, credencial);
    if (!r) return { error: error(401, 'clave_invalida', 'Clave de acceso inválida.') };
    if (!clienteVigente(r.cliente, new Date(ahora()))) return { error: error(403, 'cliente_inactivo', 'El acceso de este cliente está suspendido.') };
    if (r.tipo === 'publica') {
      if (!origenPermitido(origen, r.cliente.origenes))
        return { error: error(403, 'origen_no_permitido', 'Dominio no habilitado para esta clave.') };
    } else if (req.headers.get('Origin')) {
      // Una clave secreta usada desde un navegador quiere decir que se filtró: se rechaza.
      return { error: error(403, 'clave_secreta_en_navegador', 'La clave secreta solo se usa desde un servidor. Usá un token o la clave pública.') };
    }
    return { cliente: r.cliente, tipo: r.tipo, origen };
  }

  async function marcar(env, cliente, datos, fecha) {
    return { ...datos, _licencia: { cliente: cliente.id, huella: await huella(env.FIRMA_SECRETA, cliente.id, fecha), uso: 'Licencia exclusiva del cliente indicado. Prohibida su redistribución.' } };
  }

  function registrar(req, url, status, extra = {}) {
    // Queda en Workers Logs: sirve para auditar quién pidió qué.
    console.log(JSON.stringify({ t: new Date(ahora()).toISOString(), m: req.method, p: url.pathname, s: status, ip: req.headers.get('CF-Connecting-IP') || '', o: req.headers.get('Origin') || '', ...extra }));
  }

  async function manejar(req, env, url) {
    const p = url.pathname.replace(/\/+$/, '') || '/';

    if (p === '/' || p === '/v1') return respuesta({ servicio: 'Fondos explicados API', version: VERSION, documentacion: 'Pedile la documentación al proveedor.' }, 200, { 'Cache-Control': 'no-store' });
    if (p === '/v1/salud') {
      const cat = await leerJson(env, req, '/datos/catalogo.json');
      const fecha = cat?.fecha || null;
      const dias = fecha ? Math.floor((ahora() - Date.parse(fecha + 'T00:00:00Z')) / 86400000) : null;
      const ok = !!cat && dias != null && dias <= 5;
      return respuesta({ ok, fecha_datos: fecha, dias_de_atraso: dias, fondos: cat?.cantidad ?? 0 }, ok ? 200 : 503, { 'Cache-Control': 'no-store' });
    }
    // El código del componente es público (corre en el navegador del cliente); los datos no.
    if (p === '/widget/fondos-fci.js') {
      const r = await leerAsset(env, req, '/widget/fondos-fci.js');
      if (!r) return error(404, 'no_encontrado', 'No encontrado.');
      return new Response(r.body, { headers: { ...SEGURIDAD, 'Content-Type': 'text/javascript; charset=utf-8', 'Cache-Control': 'public, max-age=3600', 'Access-Control-Allow-Origin': '*' } });
    }
    if (p === '/demo' || p === '/demo/index.html') {
      const r = await leerAsset(env, req, '/demo/index.html');
      if (!r) return error(404, 'no_encontrado', 'No encontrado.');
      return new Response(r.body, { headers: { ...SEGURIDAD, 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'public, max-age=600' } });
    }
    // Versión iframe para ALyCs que no pueden sumar scripts: solo la pueden enmarcar los dominios del cliente
    // (frame-ancestors, lo hace cumplir el navegador) y lleva un token de 60 minutos atado a este dominio.
    const em = /^\/embed\/([a-z0-9-]{2,40})$/.exec(p);
    if (em && req.method === 'GET') {
      const c = clientes.find(x => x.id === em[1]);
      if (!clienteVigente(c, new Date(ahora())) || !(c.origenes || []).length) return error(404, 'no_encontrado', 'No encontrado.');
      if (!env.FIRMA_SECRETA) return error(500, 'sin_configurar', 'Falta FIRMA_SECRETA en el servidor.');
      const ip = req.headers.get('CF-Connecting-IP') || 'sin-ip';
      if (!limitador.permitir(`embed:${ip}`, 30, ahora())) return error(429, 'demasiados_pedidos', 'Demasiados pedidos. Esperá un minuto.', { 'Retry-After': '60' });
      const r = await leerAsset(env, req, '/demo/iframe.html');
      if (!r) return error(404, 'no_encontrado', 'No encontrado.');
      const { token } = await emitirToken(env.FIRMA_SECRETA, { cliente: c.id, origen: url.origin, minutos: 60 }, ahora());
      const html = (await r.text())
        .replace('<meta name="fci-api" content="">', '<meta name="fci-api" content="/v1">')
        .replace('<meta name="fci-token" content="">', `<meta name="fci-token" content="${token}">`);
      const ancestros = c.origenes.filter(o => /^https?:\/\/[a-z0-9.*:-]+$/i.test(o)).join(' ');
      const h = { ...SEGURIDAD, 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store',
        'Content-Security-Policy': `frame-ancestors ${ancestros || "'none'"}; default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'` };
      delete h['X-Frame-Options'];
      return new Response(html, { headers: h });
    }
    if (!p.startsWith('/v1/')) return error(404, 'no_encontrado', 'No encontrado.');

    const origen = req.headers.get('Origin');
    if (req.method === 'OPTIONS') {
      // Preflight: solo se responde con CORS a dominios de algún cliente vigente.
      const ok = origen && clientes.some(c => clienteVigente(c, new Date(ahora())) && origenPermitido(origen, c.origenes));
      return new Response(null, { status: ok ? 204 : 403, headers: { ...SEGURIDAD, ...cors(ok ? origen : null) } });
    }

    const a = await autenticar(req, env, url);
    if (a.error) return a.error;
    const { cliente } = a;
    const hc = cors(a.origen);

    const ip = req.headers.get('CF-Connecting-IP') || 'sin-ip';
    const limite = cliente.limite_por_minuto || LIMITE_DEFECTO;
    if (env.LIMITE && typeof env.LIMITE.limit === 'function') {
      const { success } = await env.LIMITE.limit({ key: `${cliente.id}:${ip}` });
      if (!success) return error(429, 'demasiados_pedidos', 'Demasiados pedidos. Esperá un minuto.', { ...hc, 'Retry-After': '60' });
    }
    if (!limitador.permitir(`${cliente.id}:${ip}`, limite, ahora()))
      return error(429, 'demasiados_pedidos', 'Demasiados pedidos. Esperá un minuto.', { ...hc, 'Retry-After': '60' });

    const privado = { ...hc, 'Cache-Control': 'private, max-age=300', 'X-Licencia': cliente.id };

    if (p === '/v1/token' && req.method === 'POST') {
      if (a.tipo !== 'secreta') return error(403, 'requiere_clave_secreta', 'El token se pide desde el servidor con la clave secreta.', hc);
      if (!env.FIRMA_SECRETA) return error(500, 'sin_configurar', 'Falta FIRMA_SECRETA en el servidor.');
      let cuerpo = {};
      try { cuerpo = await req.json(); } catch { /* sin cuerpo */ }
      const o = cuerpo && typeof cuerpo.origen === 'string' ? cuerpo.origen : null;
      if (o && !origenPermitido(o, cliente.origenes)) return error(400, 'origen_no_permitido', 'Ese dominio no está habilitado para tu cuenta.');
      const minutos = Math.min(Math.max(parseInt(cuerpo?.minutos, 10) || 15, 1), 60);
      return respuesta(await emitirToken(env.FIRMA_SECRETA, { cliente: cliente.id, origen: o, minutos }, ahora()), 200, { 'Cache-Control': 'no-store' });
    }
    if (req.method !== 'GET') return error(405, 'metodo_no_permitido', 'Método no permitido.', hc);

    if (p === '/v1/config') {
      return respuesta({ cliente: cliente.nombre, tema: cliente.tema || {}, fondos_habilitados: Array.isArray(cliente.fondos) ? cliente.fondos.length : 'todos' }, 200, privado);
    }
    if (p === '/v1/catalogo') {
      const cat = await leerJson(env, req, '/datos/catalogo.json');
      if (!cat) return error(503, 'sin_datos', 'Datos no disponibles.', hc);
      const fondos = cat.fondos.filter(f => fondoHabilitado(cliente, f.id));
      return respuesta(await marcar(env, cliente, { ...cat, cantidad: fondos.length, fondos }, cat.fecha), 200, { ...privado, 'X-Datos-Fecha': cat.fecha || '' });
    }
    if (p === '/v1/referencias') {
      const ref = await leerJson(env, req, '/datos/referencias.json');
      if (!ref) return error(503, 'sin_datos', 'Datos no disponibles.', hc);
      return respuesta(await marcar(env, cliente, ref, ref.fecha), 200, privado);
    }
    const m = /^\/v1\/fondos\/([^/]+)$/.exec(p);
    if (m) {
      let pedido;
      try { pedido = decodeURIComponent(m[1]); } catch { return error(400, 'id_invalido', 'Identificador inválido.', hc); }
      const indice = /^(cafci|cnv|clase):/i.test(pedido) ? await leerJson(env, req, '/datos/ids.json') : null;
      const id = resolverId(pedido, indice);
      if (!id || !idValido(id)) return error(404, 'fondo_no_encontrado', 'No encontramos ese fondo.', hc);
      if (!fondoHabilitado(cliente, id)) return error(404, 'fondo_no_encontrado', 'No encontramos ese fondo.', hc);
      if (!barrido.registrar(`${cliente.id}:${ip}`, id, cliente.max_fichas_10_min || MAX_FICHAS_10_MIN, ahora())) {
        registrar(req, url, 429, { c: cliente.id, alerta: 'barrido' });
        return error(429, 'uso_anormal', 'Detectamos un uso anormal. Si es un error, contactanos.', { ...hc, 'Retry-After': '600' });
      }
      const f = await leerJson(env, req, `/datos/fondos/${id}.json`);
      if (!f) return error(404, 'fondo_no_encontrado', 'No encontramos ese fondo.', hc);
      return respuesta(await marcar(env, cliente, f, new Date(ahora()).toISOString().slice(0, 10)), 200, privado);
    }
    return error(404, 'no_encontrado', 'No encontrado.', hc);
  }

  return {
    async fetch(req, env) {
      const url = new URL(req.url);
      let r;
      try {
        r = await manejar(req, env, url);
      } catch (e) {
        console.log(JSON.stringify({ t: new Date(ahora()).toISOString(), p: url.pathname, error: String(e && e.stack || e) }));
        r = error(500, 'error_interno', 'Error interno.');
      }
      if (url.pathname.startsWith('/v1/') && url.pathname !== '/v1/salud') registrar(req, url, r.status, { c: r.headers.get('X-Licencia') || '' });
      return r;
    },
  };
}
