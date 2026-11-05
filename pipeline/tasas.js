// Tasas de bonos y letras calculadas por la calculadora de renta fija de Mariana
// (repo público marianarisariucema/calculadora-renta-fija), con precios de cierre de BYMA.
// Abre la calculadora en un navegador sin pantalla y lee sus tablas: LECAP, CER, dólar linked
// y soberanos en dólares. No usa ninguna API paga ni de terceros.
//
// Uso: node pipeline/tasas.js <carpeta de la calculadora> <archivo de salida>
// Requiere: playwright (require('playwright')) y python3 para servir la carpeta.
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const [carpeta, salida] = process.argv.slice(2);
if (!carpeta || !salida) { console.error('Uso: node pipeline/tasas.js <calculadora> <salida.json>'); process.exit(2); }
const PUERTO = 8900 + Math.floor(Math.random() * 90);

function num(s) {
  if (s == null) return null;
  s = String(s).replace(/%|\$|US\$|\s/g, '');
  if (!s || !/\d/.test(s)) return null;
  if (s.includes(',')) s = s.replace(/\./g, '').replace(',', '.');
  const v = parseFloat(s);
  return isNaN(v) ? null : v;
}
const fechaISO = s => { const m = String(s || '').match(/(\d{2})\/(\d{2})\/(\d{4})/); return m ? `${m[3]}-${m[2]}-${m[1]}` : null; };

(async () => {
  const srv = spawn('python3', ['-m', 'http.server', String(PUERTO), '--bind', '127.0.0.1'], { cwd: path.resolve(carpeta), stdio: 'ignore' });
  await new Promise(r => setTimeout(r, 1000));
  const b = await chromium.launch();
  try {
    const p = await b.newPage();
    await p.goto(`http://127.0.0.1:${PUERTO}/`, { waitUntil: 'networkidle', timeout: 60000 });
    await p.waitForTimeout(2500);
    const t = await p.evaluate(() => {
      const tabla = id => { const el = document.getElementById(id); if (!el) return [];
        const filas = [...el.rows].map(r => [...r.cells].map(c => { const i = c.querySelector('input'); return (i ? i.value : c.textContent).trim(); }));
        const cab = filas.shift() || []; return filas.map(f => Object.fromEntries(cab.map((h, i) => [h, f[i]]))); };
      const est = document.body.innerText.match(/Precios\s*(.+)/);
      return { lecap: tabla('tLecap'), cer: tabla('tLecer'), dl: tabla('tDl'), sob: tabla('tSob'), precios: est ? est[1] : null };
    });
    const tk = s => String(s || '').trim().split(/\s+/)[0].toUpperCase();
    const vivo = r => (num(r['Días']) ?? 1) > 0;
    const out = { generado: new Date().toISOString(), fuente: 'Calculadora de renta fija (precios de cierre BYMA)', precios: t.precios, por_ticker: {} };
    const pon = (ticker, d) => { if (ticker && d.tasa != null) out.por_ticker[ticker] = d; };
    for (const r of t.lecap.filter(vivo)) pon(tk(r.Ticker), { familia: 'Tasa fija', tasa: num(r.TEA), tasa_tipo: 'anual en pesos', md: num(r.MD), vto: fechaISO(r['Vto.']), precio: num(r.Precio) });
    for (const r of t.cer.filter(vivo)) pon(tk(r.Ticker), { familia: 'Inflación (CER)', tasa: num(r['TIR real']), tasa_tipo: 'anual por encima de la inflación', md: num(r.MD), vto: fechaISO(r['Vto.']), precio: num(r.Precio) });
    for (const r of t.dl.filter(vivo)) pon(tk(r.Ticker), { familia: 'Dólar linked', tasa: num(r['TIR (USD +)']), tasa_tipo: 'anual por encima del dólar oficial', md: num(r.MD), vto: fechaISO(r['Vto.']), precio: num(r['Precio $']) });
    for (const r of t.sob) {
      const d = { familia: 'Bonos en dólares', tasa: num(r.TIR), tasa_tipo: 'anual en dólares', md: num(r.MD), vto: fechaISO(r['Vto.']), precio: num(r['Precio USD']), ley: r.Ley };
      const k = tk(r.Ticker); pon(k, d); pon(k + 'D', d); // la CNV puede listar AL30 o AL30D
    }
    // Curvas: tasa contra días al vencimiento, por familia
    const curvas = {};
    for (const [k, d] of Object.entries(out.por_ticker)) {
      if (k.endsWith('D') && out.por_ticker[k.slice(0, -1)] === d) continue;
      const dias = d.vto ? Math.round((Date.parse(d.vto) - Date.now()) / 864e5) : null;
      (curvas[d.familia] = curvas[d.familia] || []).push({ ticker: k, dias, tasa: d.tasa, md: d.md });
    }
    for (const c of Object.values(curvas)) c.sort((a, b) => (a.dias ?? 0) - (b.dias ?? 0));
    out.curvas = curvas;
    fs.mkdirSync(path.dirname(salida), { recursive: true });
    fs.writeFileSync(salida, JSON.stringify(out));
    console.log(`Tasas: ${Object.keys(out.por_ticker).length} instrumentos (${Object.entries(curvas).map(([k, v]) => k + ' ' + v.length).join(', ')})`);
  } finally { await b.close(); srv.kill(); }
})().catch(e => { console.error(e); process.exit(1); });
