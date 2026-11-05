// Funciones puras de la API (sin dependencias de Cloudflare), para poder probarlas con node --test.

const enc = new TextEncoder();

export function b64url(bytes) {
  let s = '';
  for (const b of new Uint8Array(bytes)) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export function desdeB64url(txt) {
  const s = atob(txt.replace(/-/g, '+').replace(/_/g, '/') + '==='.slice((txt.length + 3) % 4));
  return Uint8Array.from(s, c => c.charCodeAt(0));
}

export async function sha256hex(texto) {
  const h = await crypto.subtle.digest('SHA-256', enc.encode(texto));
  return [...new Uint8Array(h)].map(b => b.toString(16).padStart(2, '0')).join('');
}

async function claveHmac(secreto) {
  return crypto.subtle.importKey('raw', enc.encode(secreto), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign', 'verify']);
}

export async function hmac(secreto, texto) {
  return b64url(await crypto.subtle.sign('HMAC', await claveHmac(secreto), enc.encode(texto)));
}

// Comparación en tiempo constante para no filtrar información por tiempos de respuesta.
export function igualSeguro(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}

// ------------------------------------------------------------------ clientes
// Cada cliente (ALyC) tiene:
//   id, nombre, activo, vence (AAAA-MM-DD), claves_publicas / claves_secretas (hash SHA-256),
//   origenes (dominios desde donde se puede usar en el navegador), fondos (null = todos),
//   limite_por_minuto, tema (colores por defecto del componente).
export async function buscarCliente(clientes, clave) {
  if (!clave || typeof clave !== 'string' || clave.length > 200) return null;
  const tipo = clave.startsWith('pk_') ? 'publica' : clave.startsWith('sk_') ? 'secreta' : null;
  if (!tipo) return null;
  const h = await sha256hex(clave);
  for (const c of clientes) {
    const lista = tipo === 'publica' ? c.claves_publicas : c.claves_secretas;
    if ((lista || []).some(x => igualSeguro(x, h))) return { cliente: c, tipo };
  }
  return null;
}

export function clienteVigente(c, hoy = new Date()) {
  if (!c || c.activo === false) return false;
  if (c.vence && hoy.toISOString().slice(0, 10) > c.vence) return false;
  return true;
}

// "https://*.ejemplo.com.ar" permite cualquier subdominio; "http://localhost:*" cualquier puerto.
export function origenPermitido(origen, permitidos) {
  if (!origen) return false;
  let u;
  try { u = new URL(origen); } catch { return false; }
  if (u.origin !== origen) return false;
  return (permitidos || []).some(p => {
    if (p === origen) return true;
    const m = /^(https?):\/\/(\*\.)?([^:/*]+)(:\*|:\d+)?$/.exec(p);
    if (!m) return false;
    const [, proto, comodin, host, puerto] = m;
    if (u.protocol !== proto + ':') return false;
    if (puerto === ':*') { /* cualquier puerto */ } else if ((puerto || '') !== (u.port ? ':' + u.port : '')) return false;
    if (comodin) return u.hostname.endsWith('.' + host);
    return u.hostname === host;
  });
}

// ------------------------------------------------------------------ tokens de sesión
// El servidor de la ALyC cambia su clave secreta por un token corto (15 min) que va al navegador.
// Así la clave secreta nunca sale de su servidor y un token robado vence solo.
export async function emitirToken(secreto, { cliente, origen = null, minutos = 15 }, ahora = Date.now()) {
  const cuerpo = b64url(enc.encode(JSON.stringify({ c: cliente, o: origen, exp: Math.floor(ahora / 1000) + minutos * 60 })));
  return { token: `tk_${cuerpo}.${await hmac(secreto, cuerpo)}`, expira: new Date(ahora + minutos * 60000).toISOString() };
}

export async function verificarToken(secreto, token, ahora = Date.now()) {
  if (!secreto || typeof token !== 'string' || !token.startsWith('tk_') || token.length > 600) return null;
  const [cuerpo, firma] = token.slice(3).split('.');
  if (!cuerpo || !firma || !igualSeguro(await hmac(secreto, cuerpo), firma)) return null;
  let datos;
  try { datos = JSON.parse(new TextDecoder().decode(desdeB64url(cuerpo))); } catch { return null; }
  if (!datos || typeof datos.exp !== 'number' || datos.exp * 1000 < ahora) return null;
  return datos;
}

// ------------------------------------------------------------------ huella por cliente
// Cada respuesta lleva una marca que identifica a qué cliente se le entregó.
// Si los datos aparecen copiados en otro lado, la huella dice de qué contrato salieron.
export async function huella(secreto, clienteId, fecha) {
  return (await hmac(secreto || 'sin-secreto', `${clienteId}|${fecha}`)).slice(0, 16);
}

// ------------------------------------------------------------------ límite de uso
// Contador en memoria por instancia. Cloudflare reparte el tráfico en varias instancias, así que
// esto es un freno de primera línea; el límite global lo da la regla de Rate Limiting (ver wrangler.toml).
export class Limitador {
  constructor() { this.ventanas = new Map(); }
  permitir(clave, limite, ahora = Date.now(), ventanaMs = 60000) {
    const v = this.ventanas.get(clave);
    if (!v || ahora - v.desde >= ventanaMs) {
      this.ventanas.set(clave, { desde: ahora, n: 1 });
      if (this.ventanas.size > 5000) this.limpiar(ahora, ventanaMs);
      return true;
    }
    v.n += 1;
    return v.n <= limite;
  }
  limpiar(ahora, ventanaMs) {
    for (const [k, v] of this.ventanas) if (ahora - v.desde >= ventanaMs) this.ventanas.delete(k);
  }
}

// Detecta descargas masivas: alguien que pide muchas fichas distintas en poco tiempo es un robot copiando.
export class DetectorBarrido {
  constructor() { this.vistos = new Map(); }
  registrar(clave, fondo, maximo, ahora = Date.now(), ventanaMs = 10 * 60000) {
    let v = this.vistos.get(clave);
    if (!v || ahora - v.desde >= ventanaMs) {
      v = { desde: ahora, ids: new Set() };
      this.vistos.set(clave, v);
      if (this.vistos.size > 5000) for (const [k, x] of this.vistos) if (ahora - x.desde >= ventanaMs) this.vistos.delete(k);
    }
    v.ids.add(fondo);
    return v.ids.size <= maximo;
  }
}

// ------------------------------------------------------------------ ids de fondos
const ID_VALIDO = /^[a-z0-9][a-z0-9-]{0,120}$/;
export function idValido(id) { return typeof id === 'string' && ID_VALIDO.test(id); }

// Acepta el id propio ("fima-premium") o códigos que la ALyC ya usa: "cafci:6419", "cnv:1901", "clase:fima-premium-clase-a".
export function resolverId(pedido, indice) {
  if (!pedido) return null;
  const p = String(pedido).trim().toLowerCase();
  const m = /^(cafci|cnv|clase):(.+)$/.exec(p);
  if (!m) return idValido(p) ? p : null;
  const tabla = (indice || {})[m[1]] || {};
  return Object.prototype.hasOwnProperty.call(tabla, m[2]) ? tabla[m[2]] : null;
}

export function fondoHabilitado(cliente, id) {
  return !Array.isArray(cliente.fondos) || cliente.fondos.includes(id);
}
