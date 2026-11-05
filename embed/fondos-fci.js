/* Fondos explicados · componentes web para integrar en el sitio de una ALyC.
 *
 *   <script type="module" src="https://API/widget/fondos-fci.js"></script>
 *   <fondos-fci></fondos-fci>                         buscador + ficha
 *   <fondos-fci-ficha fondo="cafci:6419"></fondos-fci-ficha>   ficha de un fondo
 *   <fondos-fci-etiqueta fondo="fima-premium"></fondos-fci-etiqueta>   etiqueta para el listado propio de la ALyC
 *
 * Configuración (una vez por página, o por atributos en cada etiqueta):
 *   FondosFCI.configurar({ api: 'https://API/v1', clave: 'pk_...' })                     clave pública atada al dominio
 *   FondosFCI.configurar({ api: 'https://API/v1', obtenerToken: () => fetch('/mi-backend/token').then(r => r.json()) })
 *   FondosFCI.configurar({ datos: 'data/web/' })                                          archivos estáticos (demo)
 *
 * Estilo: hereda la tipografía de la página y se ajusta con variables CSS (--fci-marca, --fci-fuente, --fci-radio...)
 * y ::part(). Eventos: fci-fondo (abrió una ficha), fci-invertir (tocó "Invertir"), fci-error.
 * Sin dependencias. Shadow DOM: los estilos de la ALyC no lo rompen y los nuestros no tocan su página.
 */

const VERSION = '1.0.0';

// ------------------------------------------------------------------ configuración y datos
const CONFIG = { api: '', clave: '', datos: '', obtenerToken: null, tema: null };
const cache = new Map();
const vivos = new Set();   // componentes en pantalla: si cambia la configuración se vuelven a dibujar
let token = null, tokenVence = 0, tokenPendiente = null;
// También se puede configurar antes de cargar el script: window.FondosFCIConfig = { api, clave, ... }
if (typeof window !== 'undefined' && window.FondosFCIConfig) Object.assign(CONFIG, window.FondosFCIConfig);

function configurar(opciones = {}) {
  Object.assign(CONFIG, opciones);
  cache.clear();
  token = null;
  vivos.forEach(el => el._dibujado && el.redibujar());
  return CONFIG;
}

function fuente(el) {
  return {
    api: (el && el.getAttribute('api')) || CONFIG.api,
    clave: (el && el.getAttribute('clave')) || CONFIG.clave,
    datos: (el && el.getAttribute('datos')) || CONFIG.datos,
  };
}

async function obtenerToken(forzar) {
  if (!CONFIG.obtenerToken) return null;
  if (!forzar && token && Date.now() < tokenVence - 60000) return token;
  if (!tokenPendiente) {
    tokenPendiente = Promise.resolve(CONFIG.obtenerToken()).then(t => {
      token = typeof t === 'string' ? t : t && t.token;
      tokenVence = t && t.expira ? Date.parse(t.expira) : Date.now() + 10 * 60000;
      return token;
    }).finally(() => { tokenPendiente = null; });
  }
  return tokenPendiente;
}

async function pedir(src, ruta) {
  const clave = `${src.api}|${src.datos}|${src.clave}|${ruta}`;
  if (cache.has(clave)) return cache.get(clave);
  const p = (async () => {
    if (src.api) {
      const base = src.api.replace(/\/+$/, '');
      const intentar = async forzar => {
        const t = await obtenerToken(forzar);
        const headers = {};
        if (t) headers.Authorization = 'Bearer ' + t; else if (src.clave) headers['X-Clave'] = src.clave;
        return fetch(`${base}/${ruta}`, { headers, credentials: 'omit' });
      };
      let r = await intentar(false);
      if (r.status === 401 && CONFIG.obtenerToken) r = await intentar(true);
      if (!r.ok) throw Object.assign(new Error(`HTTP ${r.status}`), { status: r.status });
      return r.json();
    }
    const base = (src.datos || 'data/web/').replace(/\/?$/, '/');
    const archivo = ruta === 'config' ? null : ruta.replace(/^fondos\/(.+)$/, (m, id) => `fondos/${id}`) + '.json';
    if (!archivo) return {};
    const r = await fetch(base + archivo);
    if (!r.ok) throw Object.assign(new Error(`HTTP ${r.status}`), { status: r.status });
    return r.json();
  })();
  cache.set(clave, p);
  p.catch(() => cache.delete(clave));
  return p;
}

async function idDeFondo(src, pedido) {
  const p = String(pedido || '').trim().toLowerCase();
  if (!/^(cafci|cnv|clase):/.test(p) || src.api) return p;
  try { const ids = await pedir(src, 'ids'); const [t, c] = p.split(':'); return (ids[t] || {})[c] || p; } catch { return p; }
}

const datos = {
  catalogo: el => pedir(fuente(el), 'catalogo'),
  referencias: el => pedir(fuente(el), 'referencias'),
  config: el => pedir(fuente(el), 'config').catch(() => ({})),
  fondo: async (el, id) => { const src = fuente(el); return pedir(src, 'fondos/' + encodeURIComponent(await idDeFondo(src, id))); },
};

// ------------------------------------------------------------------ formato
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const nf = (v, d = 1) => v == null || Number.isNaN(v) ? 's/d' : Number(v).toLocaleString('es-AR', { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (v, d = 1) => v == null ? 's/d' : (v > 0 ? '+' : v < 0 ? '−' : '') + nf(Math.abs(v), d) + '%';
const plata = (v, mon) => {
  if (v == null) return 's/d';
  const a = Math.abs(v), s = mon === 'USD' ? 'US$ ' : '$ ';
  if (a >= 1e12) return s + nf(v / 1e12, 2) + ' billones';
  if (a >= 1e9) return s + nf(v / 1e9, 1) + ' mil millones';
  if (a >= 1e6) return s + nf(v / 1e6, 1) + ' millones';
  return s + nf(v, 0);
};
const fecha = f => { if (!f) return ''; const [y, m, d] = String(f).slice(0, 10).split('-'); return `${d}/${m}/${y}`; };
const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
const mesAnio = f => { if (!f) return ''; const [y, m] = String(f).split('-'); return `${MESES[+m - 1]} de ${y}`; };
const plazo = p => p == null || p === '' ? 's/d' : +p === 0 ? 'en el día' : +p === 1 ? 'al día hábil siguiente' : `en ${p} días hábiles`;
const HORIZ = { Cor: 'unos días o semanas', Med: 'varios meses', Lar: 'varios años', Flex: 'cualquier plazo' };
const norm = s => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
// "Balanz S.G.F.C.I.S.A.U." -> "Balanz": las siglas legales no le dicen nada a quien empieza
const gestora = s => { const p = String(s || '').trim().split(/\s+/); while (p.length > 1 && /^(?:[SAUGFCI]\.){2,}[SAUGFCI]?\.?$/.test(p[p.length - 1])) p.pop(); return p.join(' '); };
// Fondos cerrados o en liquidación: no se puede entrar, así que solo aparecen si se los busca por nombre
const disponible = f => f.disponible !== false && !/liquidaci|cerrad|tr[aá]mite/i.test(f.tipo || '');

const RIESGO = {
  1: ['Muy bajo', 'Casi no cambia de valor día a día.'],
  2: ['Bajo', 'Puede tener días en negativo, pero se mueve poco.'],
  3: ['Medio', 'Puede bajar algunos meses. Conviene no necesitar la plata enseguida.'],
  4: ['Alto', 'Puede bajar bastante en poco tiempo. Es para dejar la plata un buen rato.'],
  5: ['Muy alto', 'Puede tener caídas fuertes. Es para plazos largos y plata que no vas a necesitar.'],
};
const nivelRiesgo = f => f.riesgo_nivel || ({ bajo: 2, medio: 3, alto: 4 })[f.riesgo] || null;

// Palabras que alguien sin experiencia no tiene por qué saber. Se explican con un toque.
const GLOSARIO = {
  patrimonio: 'Toda la plata que tiene el fondo, sumando la de todos los que invirtieron.',
  rescate: 'Pedir que te devuelvan tu plata. Es como “sacar” la inversión.',
  cer: 'Índice que sigue a la inflación. Un bono CER ajusta su valor según suben los precios.',
  'dolar linked': 'Bonos en pesos que ajustan según el dólar oficial. Protegen si hay devaluación.',
  tamar: 'Tasa que pagan los bancos por plazos fijos grandes. Sube y baja con las tasas.',
  caucion: 'Préstamo de muy corto plazo (1 a 7 días) con garantía, dentro de la bolsa.',
  'money market': 'Fondo que invierte en lo más seguro y corto: cuentas y plazos fijos. La plata está disponible en el día.',
  cuotaparte: 'Cada “porción” del fondo. Cuando invertís, comprás cuotapartes; su precio sube o baja con lo que gana el fondo.',
  custodia: 'Banco que guarda la plata y los activos del fondo, separado de la administradora. Si la administradora quiebra, tu plata no se pierde.',
  'costo anual': 'Lo que te cobran por año por administrar el fondo. Ya está descontado del rendimiento que ves.',
  inflacion: 'Cuánto suben los precios. Si tu inversión rinde menos que la inflación, perdiste poder de compra.',
  'plazo fijo': 'Depósito en un banco a 30 días con tasa fija. Sirve como punto de comparación.',
  clase: 'Un mismo fondo puede tener varias “clases” con distinto costo o monto mínimo. Invierten en lo mismo. La que te toca la define la plataforma donde invertís: a las personas casi siempre les ofrecen la clase A.',
  emergencia: 'Plata guardada para imprevistos: de 3 a 6 meses de gastos, en algo que no baje y que puedas sacar en el día.',
  suscribir: 'Es el nombre técnico de poner plata en un fondo. Sacarla se llama rescatar.',
};
const termino = (clave, texto) => `<button type="button" class="term" data-term="${esc(clave)}" data-label="${esc(texto || clave)}" part="termino">${esc(texto || clave)}</button>`;

// ------------------------------------------------------------------ estilos
const CSS = `
:host{
  --_marca:var(--fci-marca,var(--fci-tema-marca,#0f6b5c));
  --_fondo:var(--fci-fondo,transparent);
  --_sup:var(--fci-superficie,#fff);
  --_texto:var(--fci-texto,#15201c);
  --_suave:var(--fci-suave,#5b6964);
  --_linea:var(--fci-linea,#dde3e0);
  --_marca-suave:var(--fci-marca-suave,color-mix(in srgb,var(--_marca) 10%,var(--_sup)));
  --_bien:var(--fci-positivo,#1d7a45);
  --_mal:var(--fci-negativo,#b4372b);
  --_alerta:var(--fci-alerta,#a36a00);
  --_radio:var(--fci-radio,var(--fci-tema-radio,12px));
  --_fuente:var(--fci-fuente,var(--fci-tema-fuente,inherit));
  --_num:var(--fci-fuente-numeros,inherit);
  --_s1:#3f8fd1;--_s2:#d39a2b;--_s3:#8a5cc2;--_s4:#c4553d;--_s5:#2f9e8f;--_s6:#b07aa1;--_s7:#7a8a84;
  display:block;color:var(--_texto);font-family:var(--_fuente);font-size:var(--fci-tamano,15px);line-height:1.5;
  background:var(--_fondo);container-type:inline-size;
}
:host([hidden]){display:none}
:host([tema="oscuro"]){--fci-superficie:#17201d;--fci-texto:#e7eeeb;--fci-suave:#9aaba5;--fci-linea:#2a3632;--fci-positivo:#5cc98a;--fci-negativo:#ef7d70;--fci-alerta:#e3b04f;color-scheme:dark}
@media (prefers-color-scheme:dark){:host([tema="auto"]){--fci-superficie:#17201d;--fci-texto:#e7eeeb;--fci-suave:#9aaba5;--fci-linea:#2a3632;--fci-positivo:#5cc98a;--fci-negativo:#ef7d70;--fci-alerta:#e3b04f;color-scheme:dark}}
*{box-sizing:border-box}
h2,h3,p{margin:0}
h2{font-size:1.35em;line-height:1.2;text-wrap:balance}
h3{font-size:.76em;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--_suave)}
button{font:inherit;color:inherit}
.num{font-family:var(--_num);font-variant-numeric:tabular-nums}
.peq{color:var(--_suave);font-size:.87em}
.caja{background:var(--_sup);border:1px solid var(--_linea);border-radius:var(--_radio)}
.chips{display:flex;gap:6px;flex-wrap:wrap}
.chip{font-size:.74em;padding:2px 9px;border-radius:999px;border:1px solid var(--_linea);color:var(--_suave);white-space:nowrap;background:var(--_sup)}
.chip.r1,.chip.r2{color:var(--_bien);border-color:currentColor}.chip.r3{color:var(--_alerta);border-color:currentColor}.chip.r4,.chip.r5{color:var(--_mal);border-color:currentColor}
.term{background:none;border:0;padding:0;border-bottom:1px dashed currentColor;cursor:help;font:inherit}
.term:focus-visible,.boton:focus-visible,.item:focus-visible,.pill:focus-visible{outline:2px solid var(--_marca);outline-offset:2px}
.boton{display:inline-flex;align-items:center;justify-content:center;gap:6px;border:0;border-radius:calc(var(--_radio) * .75);padding:10px 18px;font-weight:600;cursor:pointer;background:var(--_marca);color:var(--fci-marca-texto,#fff)}
.boton.sec{background:transparent;color:var(--_marca);border:1px solid currentColor}
.link{background:none;border:0;padding:0;color:var(--_marca);cursor:pointer;font-weight:600}
.pop{position:fixed;z-index:2147483000;max-width:min(320px,calc(100vw - 32px));background:var(--_texto);color:var(--_sup);padding:10px 12px;border-radius:10px;font-size:.86em;line-height:1.4;box-shadow:0 8px 24px rgba(0,0,0,.2)}
.pop b{display:block;margin-bottom:2px}
/* buscador */
.buscador{display:grid;gap:14px}
.buscador input{font:inherit;width:100%;padding:11px 14px;border-radius:calc(var(--_radio) * .8);border:1px solid var(--_linea);background:var(--_sup);color:var(--_texto)}
.buscador input:focus{outline:2px solid var(--_marca);outline-offset:1px}
.pills{display:flex;gap:6px;flex-wrap:wrap}
.pill{font-size:.84em;border:1px solid var(--_linea);background:var(--_sup);border-radius:999px;padding:5px 12px;cursor:pointer}
.pill[aria-pressed="true"]{border-color:var(--_marca);color:var(--_marca);background:var(--_marca-suave);font-weight:600}
.pregunta{display:grid;gap:8px}
.empezar{padding:12px 14px}.empezar summary{font-weight:700;cursor:pointer}.empezar ol{margin:10px 0 0;padding-left:20px;display:grid;gap:8px;font-size:.93em}
.chip.pos{color:var(--_bien)}.chip.neg{color:var(--_mal)}
.pregunta p{font-weight:600}
.lista{overflow:hidden}
.item{display:grid;grid-template-columns:1fr auto;gap:4px 14px;padding:12px 16px;border:0;border-bottom:1px solid var(--_linea);background:none;width:100%;text-align:left;cursor:pointer}
.item:last-child{border-bottom:0}
.item:hover{background:var(--_marca-suave)}
.item .n{font-weight:600}
.item .g{color:var(--_suave);font-size:.82em}
.item .r{text-align:right;grid-row:span 2;align-self:center}
.item .chips{grid-column:1}
.barra-sup{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
.vacio{padding:24px 16px;color:var(--_suave)}
/* ficha */
.ficha{padding:22px 20px;display:grid;gap:26px}
.cab{display:grid;gap:8px}
.frase{font-size:1.12em;line-height:1.45;max-width:62ch}
.grid{display:grid;grid-template-columns:1fr;gap:22px}
@container (min-width:560px){.grid{grid-template-columns:1fr 1fr}.ficha{padding:26px 28px}}
.bloque{display:grid;gap:10px;align-content:start;min-width:0}
.dato{font-size:1.45em;font-weight:600;line-height:1.2}
.medidor{display:grid;grid-template-columns:repeat(5,1fr);gap:4px}
.medidor i{height:10px;border-radius:5px;background:var(--_linea)}
.medidor i.on{background:var(--_c)}
.medidor-txt{display:flex;justify-content:space-between;font-size:.74em;color:var(--_suave)}
.barra{display:flex;height:14px;border-radius:7px;overflow:hidden;background:var(--_linea)}
.barra span{display:block;height:100%}
.leyenda{display:grid;gap:6px;font-size:.88em}
.leyenda div{display:grid;grid-template-columns:12px 1fr auto;gap:8px;align-items:center}
.leyenda i{width:12px;height:12px;border-radius:3px;display:block}
table{width:100%;border-collapse:collapse;font-size:.88em}
td,th{padding:7px 0;border-bottom:1px solid var(--_linea);vertical-align:top;text-align:left}
td:last-child,th:last-child{text-align:right;padding-left:12px}
th{font-size:.74em;text-transform:uppercase;letter-spacing:.05em;color:var(--_suave);font-weight:600}
.scroll{overflow-x:auto}
.comp{display:grid;gap:8px}
.comp-row{display:grid;grid-template-columns:minmax(92px,150px) 1fr 74px;gap:10px;align-items:center;font-size:.88em}
.track{height:12px;background:var(--_linea);border-radius:6px;position:relative;overflow:hidden}
.fill{position:absolute;top:0;bottom:0;left:0;border-radius:6px;background:var(--_s7)}
.comp-row.yo .fill{background:var(--_marca)}
.comp-row.yo{font-weight:600}
.fill.neg{background:var(--_mal)}
.veredicto{padding:10px 12px;border-radius:calc(var(--_radio) * .7);background:var(--_marca-suave);font-size:.92em}
.pos{color:var(--_bien)}.neg{color:var(--_mal)}
.spark{width:100%;height:auto;display:block;overflow:visible}
.spark path.l{fill:none;stroke:var(--_marca);stroke-width:2;vector-effect:non-scaling-stroke}
.spark path.a{fill:var(--_marca-suave)}
.spark text{font-size:11px;fill:var(--_suave);font-family:var(--_num)}
.acciones{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.aviso{font-size:.76em;color:var(--_suave);border-top:1px solid var(--_linea);padding-top:12px}
/* etiqueta */
.etq{display:inline-flex;gap:6px;align-items:center;flex-wrap:wrap;vertical-align:middle}
.etq .que{font-size:.78em;padding:2px 10px;border-radius:999px;border:1px solid var(--_marca);color:var(--_marca);background:transparent;cursor:pointer;font-weight:600;white-space:nowrap}
.etq .que:hover{background:var(--_marca-suave)}
.etq .frase-c{font-size:.82em;color:var(--_suave);flex-basis:100%}
dialog{border:0;padding:0;border-radius:var(--_radio);width:min(760px,calc(100vw - 24px));max-height:calc(100dvh - 24px);background:var(--_sup);color:var(--_texto);box-shadow:0 20px 60px rgba(0,0,0,.3)}
dialog::backdrop{background:rgba(10,20,16,.45)}
.cerrar{position:sticky;top:0;display:flex;justify-content:flex-end;padding:10px 10px 0;background:linear-gradient(var(--_sup) 70%,transparent);z-index:1}
.cerrar button{border:0;background:var(--_marca-suave);border-radius:999px;width:34px;height:34px;cursor:pointer;font-size:1.1em}
.esqueleto{display:grid;gap:12px;padding:22px}
.esqueleto i{height:14px;border-radius:7px;background:linear-gradient(90deg,var(--_linea),var(--_marca-suave),var(--_linea));background-size:200% 100%}
@media (prefers-reduced-motion:no-preference){.esqueleto i{animation:brillo 1.2s infinite linear}.barra span,.fill{transition:width .4s ease}}
@keyframes brillo{to{background-position:-200% 0}}
`;
let hoja = null;
function estilos(root) {
  if ('adoptedStyleSheets' in Document.prototype && typeof CSSStyleSheet === 'function' && 'replaceSync' in CSSStyleSheet.prototype) {
    if (!hoja) { hoja = new CSSStyleSheet(); hoja.replaceSync(CSS); }
    root.adoptedStyleSheets = [hoja];
  } else {
    const s = document.createElement('style'); s.textContent = CSS; root.appendChild(s);
  }
}

// ------------------------------------------------------------------ filtros pensados como preguntas
const OBJETIVOS = [
  ['todos', 'Ver todos', () => true],
  ['disponible', 'Tener la plata disponible', f => /money market|corto plazo|mercado de dinero/i.test(f.tipo + ' ' + f.subtipo)],
  ['inflacion', 'Ganarle a la inflación', f => /CER|inflaci/i.test(f.tipo + ' ' + f.subtipo)],
  ['dolar', 'Cubrirme del dólar', f => f.moneda === 'USD' || /d[oó]lar/i.test(f.tipo + ' ' + f.subtipo)],
  ['tasa', 'Una tasa en pesos', f => f.moneda !== 'USD' && /tasa fija|TAMAR|renta fija (en )?pesos|empresas en pesos/i.test(f.tipo + ' ' + f.subtipo)],
  ['crecer', 'Hacer crecer a largo plazo', f => /acciones|renta variable/i.test(f.tipo + ' ' + f.subtipo)],
  ['mixto', 'Un poco de todo', f => /mixta/i.test(f.tipo + ' ' + f.subtipo)],
];

// ------------------------------------------------------------------ base común
class Base extends HTMLElement {
  constructor() {
    super();
    this.root = this.attachShadow({ mode: 'open' });
    estilos(this.root);
    this.vista = document.createElement('div');
    this.root.appendChild(this.vista);
    this.root.addEventListener('click', e => this.clickTermino(e));
  }
  connectedCallback() {
    vivos.add(this);
    if (this._iniciado) return;
    this._iniciado = true;
    // Se espera un instante para que la página termine de llamar a configurar().
    setTimeout(() => this.redibujar());
  }
  disconnectedCallback() { vivos.delete(this); }
  attributeChangedCallback(n, a, b) { if (this._dibujado && a !== b) this.render(); }
  redibujar() {
    this._dibujado = true;
    const s = this.root.querySelector('style[data-tema]'); if (s) s.remove();
    this.aplicarTema();
    this.render();
  }
  async aplicarTema() {
    const t = CONFIG.tema || (await datos.config(this)).tema || {};
    const css = [];
    if (t.marca) css.push(`--fci-tema-marca:${t.marca}`);
    if (t.fuente) css.push(`--fci-tema-fuente:${t.fuente}`);
    if (t.radio) css.push(`--fci-tema-radio:${t.radio}`);
    // Valores del servidor con la prioridad más baja: el CSS de la ALyC siempre gana.
    if (css.length && !this.root.querySelector('style[data-tema]')) {
      const s = document.createElement('style'); s.dataset.tema = ''; s.textContent = `:host{${css.join(';').replace(/[{}<>]/g, '')}}`;
      this.root.prepend(s);
    }
  }
  emitir(nombre, detalle) {
    return this.dispatchEvent(new CustomEvent(nombre, { detail: detalle, bubbles: true, composed: true, cancelable: true }));
  }
  fallo(e, donde) {
    this.emitir('fci-error', { mensaje: String(e && e.message || e), status: e && e.status, donde });
    const msj = e && (e.status === 403 || e.status === 401) ? 'Este sitio no está habilitado para mostrar esta información.' : e && e.status === 404 ? 'No encontramos ese fondo.' : 'No pudimos cargar la información. Probá de nuevo en un rato.';
    return `<p class="vacio" role="status">${msj}</p>`;
  }
  clickTermino(e) {
    const b = e.target.closest && e.target.closest('.term');
    this.root.querySelectorAll('.pop').forEach(p => p.remove());
    if (!b) return;
    e.stopPropagation();
    const k = b.dataset.term;
    const pop = document.createElement('div');
    pop.className = 'pop'; pop.setAttribute('role', 'tooltip');
    const etiqueta = b.dataset.label || k;
    pop.innerHTML = `<b>${esc(etiqueta.charAt(0).toUpperCase() + etiqueta.slice(1))}</b>${esc(GLOSARIO[k] || '')}`;
    this.root.appendChild(pop);
    const r = b.getBoundingClientRect();
    const w = pop.offsetWidth;
    pop.style.left = Math.max(16, Math.min(r.left, innerWidth - w - 16)) + 'px';
    pop.style.top = (r.bottom + 8 + pop.offsetHeight > innerHeight ? r.top - pop.offsetHeight - 8 : r.bottom + 8) + 'px';
    const cerrar = ev => { if (!pop.contains(ev.composedPath()[0])) { pop.remove(); document.removeEventListener('click', cerrar, true); } };
    setTimeout(() => document.addEventListener('click', cerrar, true));
  }
  esqueleto() { return `<div class="esqueleto caja" aria-busy="true" aria-label="Cargando"><i style="width:55%"></i><i></i><i style="width:80%"></i><i style="width:65%"></i></div>`; }

  // ---------------------------------------------------------------- ficha (la usan los tres componentes)
  async htmlFicha(id, { volver = false } = {}) {
    const [f, ref] = await Promise.all([datos.fondo(this, id), datos.referencias(this).catch(() => ({ periodos: {} }))]);
    this.fondoActual = f;
    this.ref = ref;
    const c = f.cartera, nivel = nivelRiesgo(f);
    const costo = f.clases && f.clases.length ? Math.min(...f.clases.map(x => (x.honorarios_gerente || 0) + (x.honorarios_depositaria || 0))) : null;
    const minimo = f.clases && f.clases.length ? Math.min(...f.clases.map(x => x.minimo ?? Infinity)) : null;
    const atado = c ? Object.entries(c.atado || {}).filter(a => a[1] > 0) : [];
    const tot = atado.reduce((s, a) => s + a[1], 0) || 100;
    const col = ['var(--_marca)', 'var(--_s1)', 'var(--_s2)', 'var(--_s3)', 'var(--_s4)', 'var(--_s5)', 'var(--_s6)', 'var(--_s7)'];
    const fl = f.flujo_30d ?? f.flujo_dia, flTxt = f.flujo_30d != null ? 'el último mes' : 'el último día hábil';
    const invertir = this.getAttribute('invertir');
    const glos = t => t.replace(/\b(CER|TAMAR|money market|dólar linked|cauciones?)\b/gi, m => termino(norm(m).replace(/es$/, '').replace('cauciones', 'caucion'), m));
    const rg = RIESGO[nivel];
    const caida = f.peor_caida_1a;

    return `
    ${volver ? `<button type="button" class="link" data-accion="volver" part="volver">← Todos los fondos</button>` : ''}
    <article class="ficha caja" part="ficha" aria-labelledby="t-${esc(f.id)}">
      <header class="cab">
        <h2 id="t-${esc(f.id)}">${esc(f.nombre)}</h2>
        <p class="peq">Lo administra ${esc(gestora(f.gerente) || 's/d')}</p>
        <div class="chips">
          <span class="chip" part="chip">${esc(f.tipo)}</span>
          <span class="chip" part="chip">${f.moneda === 'USD' ? 'En dólares' : 'En pesos'}</span>
          <span class="chip" part="chip">Retirás ${plazo(f.plazo_rescate)}</span>
          ${nivel ? `<span class="chip r${nivel}" part="chip">Riesgo ${rg[0].toLowerCase()}</span>` : ''}
        </div>
      </header>
      ${disponible(f) ? '' : `<p class="frase">⚠ ${esc(f.tipo_explicacion || 'Este fondo no recibe inversiones nuevas.')}</p>`}
      ${f.frase ? `<p class="frase">${glos(esc(f.frase))}</p>` : ''}
      <div class="grid">
        <section class="bloque"><h3>Para qué sirve</h3>
          <p>${glos(esc(f.para_que || f.tipo_explicacion || ''))}</p>
          ${f.horizonte && HORIZ[f.horizonte] ? `<p class="peq">Pensado para dejar la plata ${HORIZ[f.horizonte]}.</p>` : ''}</section>
        ${nivel ? `<section class="bloque"><h3>Cuánto se puede mover</h3>
          <div class="medidor" role="img" aria-label="Riesgo ${rg[0]}, ${nivel} de 5" style="--_c:${nivel <= 2 ? 'var(--_bien)' : nivel === 3 ? 'var(--_alerta)' : 'var(--_mal)'}">${[1, 2, 3, 4, 5].map(i => `<i class="${i <= nivel ? 'on' : ''}"></i>`).join('')}</div>
          <div class="medidor-txt"><span>Tranquilo</span><span>Movido</span></div>
          <p>${esc(rg[1])}${caida != null && caida < -0.5 ? ` En el último año, en su peor momento llegó a estar <b class="num neg">${pct(caida)}</b> abajo.` : ''}</p></section>` : ''}
      </div>
      <section class="bloque">
        <div class="barra-sup"><h3>Cómo le fue</h3>
          <div class="pills" role="group" aria-label="Período">${[['30d', '1 mes'], ['anio', 'En el año'], ['1a', '12 meses'], ['2a', '2 años']].map(p => `<button type="button" class="pill" data-periodo="${p[0]}" aria-pressed="${p[0] === '1a'}">${p[1]}</button>`).join('')}</div></div>
        <div class="comp" data-comp></div>
        <p class="veredicto" data-veredicto></p>
        ${this.sparkline(f.evolucion)}
      </section>
      ${c ? `<section class="bloque"><h3>A qué está atada tu plata</h3>
        <div class="barra" role="img" aria-label="Composición de la cartera">${atado.map((a, i) => `<span style="width:${a[1] / tot * 100}%;background:${col[i % 8]}"></span>`).join('')}</div>
        <div class="leyenda">${atado.map((a, i) => `<div><i style="background:${col[i % 8]}"></i><span>${glos(esc(a[0]))}</span><span class="num">${nf(a[1], 1)}%</span></div>`).join('')}</div>
        <p class="peq">Según la cartera publicada por la CNV al ${fecha(c.fecha)}, con ${c.n_activos} inversiones distintas.${c.vencimiento_promedio_anios != null && c.vencimiento_cobertura_pct >= 30 ? ` Lo que tiene fecha de vencimiento vence en promedio en ${c.vencimiento_promedio_anios < 1 ? nf(c.vencimiento_promedio_anios * 12, 0) + ' meses' : nf(c.vencimiento_promedio_anios, 1) + ' años'}.` : ''}</p></section>`
        : `<section class="bloque"><h3>En qué invierte</h3><p class="peq">La CNV todavía no publicó la cartera de este fondo.</p></section>`}
      <div class="grid">
        ${c && c.principales && c.principales.length ? `<section class="bloque"><h3>Lo que más tiene</h3><table><tbody>${c.principales.slice(0, 6).map(t => `<tr><td>${esc(t.en_palabras || t.activo)}${t.en_palabras ? `<br><span class="peq">${esc(t.activo)}</span>` : ''}</td><td class="num">${nf(t.pct, 1)}%</td></tr>`).join('')}</tbody></table></section>` : ''}
        <section class="bloque"><h3>Qué tan grande es</h3>
          <p class="dato num">${plata(f.patrimonio, f.moneda)}</p>
          <p class="peq">Es su ${termino('patrimonio')}. ${f.puesto ? `Está ${f.puesto === 1 ? 'primero' : `en el puesto ${f.puesto}`} entre ${f.en_categoria} fondos parecidos.` : ''}</p>
          ${fl != null ? `<p><span class="num ${fl >= 0 ? 'pos' : 'neg'}">${fl >= 0 ? '+' : '−'} ${plata(Math.abs(fl), f.moneda)}</span> <span class="peq">${fl >= 0 ? 'entraron' : 'salieron'} ${flTxt} (lo que la gente puso menos lo que retiró).</span></p>` : ''}
        </section>
      </div>
      <section class="bloque"><h3>Antes de invertir</h3><table><tbody>
        <tr><td>Te devuelven la plata (${termino('rescate')})</td><td>${plazo(f.plazo_rescate)}</td></tr>
        <tr><td>${termino('costo anual', 'Costo anual')}</td><td class="num">${costo == null ? 's/d' : (f.clases.length > 1 ? 'desde ' : '') + nf(costo, 2) + '%'}</td></tr>
        ${minimo != null && Number.isFinite(minimo) ? `<tr><td>Monto mínimo</td><td class="num">${minimo > 0 ? plata(minimo, f.moneda) : 'sin mínimo'}</td></tr>` : ''}
        <tr><td>Quién guarda la plata (${termino('custodia')})</td><td>${esc(f.depositaria || 's/d')}</td></tr>
      </tbody></table>
      ${f.clases && f.clases.length > 1 ? `<details><summary class="peq" style="cursor:pointer">Ver las ${f.clases.length} ${termino('clase', 'clases')} del fondo</summary><p class="peq">Invierten en lo mismo. Las que rinden más suelen ser para empresas o montos grandes, porque cobran menos.${f.clases.some(x => /27\.?743/.test(x.nombre)) ? ' Las que dicen “Ley 27.743” son para plata que entró con el blanqueo de 2024.' : ''}</p><div class="scroll"><table><thead><tr><th>Clase</th><th>Costo anual</th><th>Mínimo</th><th>12 meses</th></tr></thead><tbody>${f.clases.map(x => `<tr><td>${esc(x.nombre.split(' - ').slice(1).join(' - ') || x.nombre)}</td><td class="num">${nf((x.honorarios_gerente || 0) + (x.honorarios_depositaria || 0), 2)}%</td><td class="num">${x.minimo != null ? plata(x.minimo, f.moneda) : 's/d'}</td><td class="num">${pct(x.rend_1a)}</td></tr>`).join('')}</tbody></table></div></details>` : ''}
      </section>
      ${invertir !== null ? `<div class="acciones"><button type="button" class="boton" data-accion="invertir" part="boton invertir">${esc(invertir || 'Invertir en este fondo')}</button></div>` : ''}
      <p class="aviso">Fuentes oficiales: CAFCI, CNV, BCRA y ArgentinaDatos. Rendimientos de la clase principal, ya descontados los costos. Lo que rindió antes no asegura lo que va a rendir. Información con fines educativos: no es una recomendación de inversión.</p>
    </article>`;
  }
  sparkline(ev) {
    if (!Array.isArray(ev) || ev.length < 3) return '';
    const v = ev.map(x => +x[1]).filter(Number.isFinite);
    if (v.length < 3) return '';
    const base = v[0], ser = v.map(x => x / base * 100), mn = Math.min(...ser), mx = Math.max(...ser), W = 300, H = 70;
    const pts = ser.map((y, i) => [i / (ser.length - 1) * W, H - (y - mn) / ((mx - mn) || 1) * (H - 8) - 4]);
    const d = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join('');
    const fin = ser[ser.length - 1] - 100;
    return `<figure style="margin:0" class="bloque"><svg class="spark" viewBox="0 -14 ${W} ${H + 28}" role="img" aria-label="Cómo cambió el valor desde ${mesAnio(ev[0][0])}: ${pct(fin)}">
      <path class="a" d="${d}L${W} ${H}L0 ${H}Z"/><path class="l" d="${d}"/>
      <text x="0" y="${H + 12}">${esc(mesAnio(ev[0][0]))}</text><text x="${W}" y="${H + 12}" text-anchor="end">${esc(mesAnio(ev[ev.length - 1][0]))}</text></svg>
      <figcaption class="peq">Si hubieras puesto $ 100 en ${esc(mesAnio(ev[0][0]))}, hoy tendrías <b class="num">$ ${nf(100 + fin, 0)}</b>.</figcaption></figure>`;
  }
  activarFicha(cont) {
    const f = this.fondoActual, ref = this.ref || { periodos: {} };
    const pintar = periodo => {
      const P = ref.periodos?.[periodo] || {}, v = f.rendimientos?.[periodo];
      const usd = f.moneda === 'USD';
      const filas = [['Este fondo', v, true], ...(usd ? [] : [['Inflación', P.inflacion], ['Plazo fijo', P.plazo_fijo], ['Dólar oficial', P.dolar]])].filter(r => r[2] || r[1] != null);
      const max = Math.max(...filas.map(r => Math.abs(r[1] || 0)), 1);
      cont.querySelector('[data-comp]').innerHTML = filas.map(([n, x, yo]) => `<div class="comp-row ${yo ? 'yo' : ''}"><span>${n === 'Inflación' ? termino('inflacion', n) : n === 'Plazo fijo' ? termino('plazo fijo', n) : n}</span><span class="track"><span class="fill ${x < 0 ? 'neg' : ''}" style="width:${Math.abs(x || 0) / max * 100}%"></span></span><span class="num" style="text-align:right">${pct(x)}</span></div>`).join('');
      const d = v != null && P.inflacion != null && !usd ? v - P.inflacion : null;
      cont.querySelector('[data-veredicto]').innerHTML = v == null ? 'No hay datos del fondo para este período.'
        : usd ? `Rindió <b class="num">${pct(v)}</b> en dólares. Como está en dólares, no se compara con la inflación en pesos.`
        : d == null ? `Rindió <b class="num">${pct(v)}</b>. Todavía no hay dato de inflación para comparar este período.`
        : `${d >= 0 ? '✓ Le ganó' : '✗ Le perdió'} a la inflación por <b class="num">${nf(Math.abs(d), 1)} puntos</b>: ${d >= 0 ? 'con lo que ganaste podías comprar más cosas que antes.' : 'con lo que tenías podías comprar menos cosas que antes.' + ((nivelRiesgo(f) || 9) <= 1 ? ' Es lo habitual en fondos así: sirven para tener la plata a mano, no para ganarle a la inflación.' : '')}${P.inflacion_hasta ? ` <span class="peq">Inflación hasta ${mesAnio(P.inflacion_hasta)}.</span>` : ''}`;
    };
    cont.querySelectorAll('[data-periodo]').forEach(b => b.onclick = () => {
      cont.querySelectorAll('[data-periodo]').forEach(x => x.setAttribute('aria-pressed', x === b)); pintar(b.dataset.periodo);
    });
    pintar('1a');
    const inv = cont.querySelector('[data-accion="invertir"]');
    if (inv) inv.onclick = () => this.emitir('fci-invertir', { id: f.id, nombre: f.nombre, clases: (f.clases || []).map(c => c.nombre) });
    this.emitir('fci-fondo', { id: f.id, nombre: f.nombre });
  }
}

// ------------------------------------------------------------------ <fondos-fci>: buscador + ficha
class FondosFCI extends Base {
  static get observedAttributes() { return ['fondo']; }
  constructor() { super(); this.estado = { objetivo: 'todos', texto: '', orden: 'patrimonio', mostrar: 25 }; }
  async render() {
    const id = this.getAttribute('fondo');
    if (id) return this.mostrarFicha(id, false);
    this.vista.innerHTML = this.esqueleto();
    try { this.cat = await datos.catalogo(this); } catch (e) { this.vista.innerHTML = this.fallo(e, 'catalogo'); return; }
    this.refLista = await datos.referencias(this).catch(() => null);
    this.listado();
  }
  async mostrarFicha(id, volver) {
    this.vista.innerHTML = this.esqueleto();
    try { this.vista.innerHTML = await this.htmlFicha(id, { volver }); } catch (e) { this.vista.innerHTML = (volver ? '<button type="button" class="link" data-accion="volver">← Todos los fondos</button>' : '') + this.fallo(e, 'fondo'); }
    const v = this.vista.querySelector('[data-accion="volver"]');
    if (v) v.onclick = () => { this.listado(); this.scrollIntoView({ block: 'start', behavior: 'smooth' }); };
    if (this.fondoActual) this.activarFicha(this.vista);
  }
  listado() {
    const s = this.estado, cat = this.cat;
    this.vista.innerHTML = `
    <div class="buscador">
      <details class="caja empezar" part="empezar"><summary>¿Nunca invertiste? Empezá acá</summary><ol>
        <li><b>Primero, tu colchón.</b> Separá unos 3 a 6 meses de gastos para imprevistos (${termino('emergencia', 'fondo de emergencia')}) en un ${termino('money market')}: casi no baja y la sacás en el día.</li>
        <li><b>Después, pensá cuándo vas a necesitar el resto.</b> Si es en unos meses, elegí riesgo bajo. Cuanto más tiempo puedas dejarla, más subas y bajas podés aguantar.</li>
        <li><b>Fijate si le ganó a la inflación.</b> Un “+20%” no es ganancia si los precios subieron más que eso.</li>
        <li><b>Invertir es tocar el botón del fondo</b> (a veces dice “${termino('suscribir')}”). Para sacar la plata pedís el ${termino('rescate')}.</li></ol></details>
      <div class="pregunta"><p>¿Qué querés hacer con tu plata?</p>
        <div class="pills" role="group" aria-label="Objetivo">${OBJETIVOS.map(o => `<button type="button" class="pill" data-obj="${o[0]}" aria-pressed="${s.objetivo === o[0]}">${o[1]}</button>`).join('')}</div></div>
      <input type="search" placeholder="O buscá un fondo por nombre o administradora" aria-label="Buscar fondo" value="${esc(s.texto)}">
      <div class="barra-sup"><span class="peq" data-cuantos></span>
        <label class="peq">Ordenar por <select data-orden style="font:inherit"><option value="patrimonio">Más grandes</option><option value="rend">Más rindieron (12 meses)</option></select></label></div>
      <div class="lista caja" part="lista" data-lista></div>
      <button type="button" class="boton sec" data-mas hidden>Ver más fondos</button>
      <p class="aviso">Datos al ${fecha(cat.fecha)}. Fuentes oficiales: CAFCI, CNV, BCRA. Información educativa, no es una recomendación de inversión.</p>
    </div>`;
    const q = this.vista.querySelector('input'), sel = this.vista.querySelector('[data-orden]');
    sel.value = s.orden;
    q.oninput = () => { s.texto = q.value; s.mostrar = 25; this.filas(); };
    sel.onchange = () => { s.orden = sel.value; this.filas(); };
    this.vista.querySelectorAll('[data-obj]').forEach(b => b.onclick = () => {
      s.objetivo = b.dataset.obj; s.mostrar = 25;
      this.vista.querySelectorAll('[data-obj]').forEach(x => x.setAttribute('aria-pressed', x === b)); this.filas();
    });
    this.vista.querySelector('[data-mas]').onclick = () => { s.mostrar += 25; this.filas(); };
    this.vista.querySelector('[data-lista]').onclick = e => { const it = e.target.closest('.item'); if (it) this.mostrarFicha(it.dataset.id, true); };
    this.filas();
  }
  filas() {
    const s = this.estado, fn = OBJETIVOS.find(o => o[0] === s.objetivo)[2], t = norm(s.texto);
    let l = this.cat.fondos.filter(f => fn(f) && (t ? norm(f.nombre + ' ' + f.gerente).includes(t) : disponible(f)));
    const inf = this.refLista?.periodos?.['1a']?.inflacion;
    if (s.orden === 'rend') l = [...l].sort((a, b) => (b.rend_1a ?? -1e9) - (a.rend_1a ?? -1e9));
    this.vista.querySelector('[data-cuantos]').textContent = l.length.toLocaleString('es-AR') + (l.length === 1 ? ' fondo' : ' fondos');
    this.vista.querySelector('[data-lista]').innerHTML = l.length ? l.slice(0, s.mostrar).map(f => {
      const n = nivelRiesgo(f);
      return `<button type="button" class="item" part="item" data-id="${esc(f.id)}">
        <span><span class="n">${esc(f.nombre)}</span><br><span class="g">${esc(gestora(f.gerente))}</span></span>
        <span class="r"><span class="num ${f.rend_1a < 0 ? 'neg' : ''}" style="font-weight:600">${pct(f.rend_1a)}</span><br><span class="g">últimos 12 meses</span></span>
        <span class="chips"><span class="chip">${esc(f.tipo)}</span><span class="chip">${f.moneda === 'USD' ? 'Dólares' : 'Pesos'}</span><span class="chip">Retirás ${plazo(f.plazo_rescate)}</span>${n ? `<span class="chip r${n}">Riesgo ${RIESGO[n][0].toLowerCase()}</span>` : ''}${inf != null && f.moneda !== 'USD' && f.rend_1a != null ? `<span class="chip ${f.rend_1a >= inf ? 'pos' : 'neg'}">${f.rend_1a >= inf ? '✓ Le ganó a la inflación' : '✗ Menos que la inflación'}</span>` : ''}</span></button>`;
    }).join('') : '<p class="vacio">No encontramos fondos con ese nombre.</p>';
    this.vista.querySelector('[data-mas]').hidden = l.length <= s.mostrar;
  }
}

// ------------------------------------------------------------------ <fondos-fci-ficha fondo="...">
class FondosFCIFicha extends FondosFCI {
  async render() {
    const id = this.getAttribute('fondo');
    if (!id) { this.vista.innerHTML = '<p class="vacio">Falta el atributo fondo.</p>'; return; }
    return this.mostrarFicha(id, false);
  }
}

// ------------------------------------------------------------------ <fondos-fci-etiqueta fondo="...">
// Va al lado del nombre del fondo en el listado que la ALyC ya tiene. Un toque abre la ficha completa.
class FondosFCIEtiqueta extends Base {
  static get observedAttributes() { return ['fondo']; }
  async render() {
    const pedido = this.getAttribute('fondo');
    this.vista.innerHTML = '';
    if (!pedido) return;
    let f;
    try {
      const src = fuente(this), id = await idDeFondo(src, pedido);
      const cat = await datos.catalogo(this);
      f = cat.fondos.find(x => x.id === id);
      if (!f && /^(cafci|cnv|clase):/.test(id)) f = await datos.fondo(this, pedido); // la API resuelve el código
    } catch (e) { this.emitir('fci-error', { mensaje: String(e.message || e), status: e.status, donde: 'etiqueta' }); return; }
    if (!f) return;
    const n = nivelRiesgo(f), compacta = this.hasAttribute('compacta');
    this.vista.innerHTML = `<span class="etq" part="etiqueta">
      ${compacta ? '' : `<span class="chip" part="chip">${esc(f.tipo)}</span>`}
      ${n ? `<span class="chip r${n}" part="chip" title="${esc(RIESGO[n][1])}">Riesgo ${RIESGO[n][0].toLowerCase()}</span>` : ''}
      <button type="button" class="que" part="boton" aria-haspopup="dialog">${esc(this.getAttribute('texto') || '¿Qué es este fondo?')}</button>
    </span>`;
    this.vista.querySelector('.que').onclick = () => this.abrir(f.id);
  }
  async abrir(id) {
    let d = this.root.querySelector('dialog');
    if (!d) {
      d = document.createElement('dialog');
      d.setAttribute('part', 'dialogo');
      d.addEventListener('click', e => { if (e.target === d) d.close(); });
      this.root.appendChild(d);
    }
    d.innerHTML = `<div class="cerrar"><button type="button" aria-label="Cerrar">✕</button></div><div data-c>${this.esqueleto()}</div>`;
    d.querySelector('.cerrar button').onclick = () => d.close();
    if (typeof d.showModal === 'function') d.showModal(); else d.setAttribute('open', '');
    const c = d.querySelector('[data-c]');
    try { c.innerHTML = await this.htmlFicha(id); this.activarFicha(c); c.querySelector('.ficha').style.border = '0'; }
    catch (e) { c.innerHTML = this.fallo(e, 'fondo'); }
  }
}

const definir = (n, c) => { if (!customElements.get(n)) customElements.define(n, c); };
definir('fondos-fci', FondosFCI);
definir('fondos-fci-ficha', FondosFCIFicha);
definir('fondos-fci-etiqueta', FondosFCIEtiqueta);

const API = { configurar, version: VERSION, glosario: GLOSARIO };
if (typeof window !== 'undefined') window.FondosFCI = Object.assign(window.FondosFCI || {}, API);
export { configurar, VERSION as version };
