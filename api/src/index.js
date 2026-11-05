// Punto de entrada del Worker. clientes.json tiene solo hashes de claves, nunca las claves.
import clientes from '../clientes.json';
import { crearApp } from './app.js';

export default crearApp(clientes);
