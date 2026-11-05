// Genera claves para un cliente nuevo (o para rotar las de uno existente).
//   node api/scripts/nueva-clave.mjs <id-cliente> [publica|secreta|ambas]
// Imprime las claves UNA vez (guardalas en un gestor de contraseñas y mandáselas al cliente por un canal seguro)
// y los hashes, que son lo único que va en api/clientes.json.
import { randomBytes, createHash } from 'node:crypto';

const [id, tipo = 'ambas'] = process.argv.slice(2);
if (!id || !/^[a-z0-9-]{2,40}$/.test(id)) {
  console.error('Uso: node api/scripts/nueva-clave.mjs <id-cliente> [publica|secreta|ambas]  (id en minúsculas, ej. broker-demo)');
  process.exit(1);
}
const gen = pref => `${pref}_${id.replace(/-/g, '')}_${randomBytes(24).toString('base64url')}`;
const hash = k => createHash('sha256').update(k).digest('hex');
const out = {};
if (tipo !== 'secreta') { const k = gen('pk'); out.publica = { clave: k, hash: hash(k) }; }
if (tipo !== 'publica') { const k = gen('sk'); out.secreta = { clave: k, hash: hash(k) }; }
console.log(JSON.stringify(out, null, 2));
console.log('\nEn api/clientes.json agregá los hash en "claves_publicas" / "claves_secretas". La clave en sí NO va al repo.');
