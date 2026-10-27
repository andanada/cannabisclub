'use strict';
// Bàscules OHAUS per port sèrie (RS232 o USB virtual) amb l'API Web Serial del navegador.
// Protocol (manuals d'interfície OHAUS): ordres ASCII acabades en CRLF — IP = imprimeix ara (estable o no),
// SP = imprimeix en estabilitzar-se, T = tara, Z = zero. Resposta: pes, unitat, «?» si és inestable, G/N, CRLF.
// Atenció: el format exacte (amplada de camps) depèn del model; l'analitzador és tolerant però NO s'ha provat amb una bàscula real.

const MG_PER_UNIT = { mg: 1, g: 1000, kg: 1e6, oz: 28349.523125, lb: 453592.37, ct: 200 };

// Analitza una línia de la bàscula. Torna null si no té pes; llança error si la unitat no és suportada.
function parsePesLine(line) {
  const m = /^\s*([+-]?\d+(?:[.,]\d+)?)\s*([A-Za-z]{1,5})?\s*(\?)?(?:\s+([GNgn]))?\s*$/.exec(line);
  if (!m) return null;
  const unit = (m[2] || 'g').toLowerCase();
  if (!(unit in MG_PER_UNIT)) throw new Error('Unitat de la bàscula no suportada: ' + m[2] + ' (configura-la en grams)');
  const value = parseFloat(m[1].replace(',', '.'));
  return { mg: Math.round(value * MG_PER_UNIT[unit]), unit, stable: !m[3], mode: m[4] ? m[4].toUpperCase() : null, raw: line.trim() };
}

class Bascula {
  constructor(opts) {
    const o = opts || {};
    this.serial = o.serial || (typeof navigator !== 'undefined' ? navigator.serial : undefined);
    this.baudRate = o.baudRate || 9600;
    this.port = null; this.writer = null; this.reader = null;
    this.last = null; this.lastError = null; this.waiters = [];
    this.connected = false;
  }

  static supported() { return typeof navigator !== 'undefined' && !!navigator.serial; }

  async connect() {
    if (!this.serial) throw new Error('Aquest navegador o connexió no admet ports sèrie (cal Chrome/Edge i HTTPS o localhost)');
    this.port = await this.serial.requestPort();
    await this.port.open({ baudRate: this.baudRate, dataBits: 8, stopBits: 1, parity: 'none', flowControl: 'none' });
    this.writer = this.port.writable.getWriter();
    this.connected = true;
    this._readLoop();
  }

  async _readLoop() {
    const dec = new TextDecoder();
    let buf = '';
    this.reader = this.port.readable.getReader();
    try {
      for (;;) {
        const { value, done } = await this.reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split(/\r\n|\r|\n/);
        buf = lines.pop();
        for (const line of lines) this._onLine(line);
      }
    } catch (e) { this.lastError = e; } finally {
      this.connected = false;
      this._wake();
    }
  }

  _onLine(line) {
    if (!line.trim()) return;
    try {
      const p = parsePesLine(line);
      if (p) { this.last = Object.assign(p, { at: Date.now() }); this.lastError = null; }
    } catch (e) { this.lastError = e; }
    this._wake();
  }

  _wake() { const w = this.waiters; this.waiters = []; w.forEach((f) => f()); }
  _waitForData(ms) { return new Promise((res) => { const t = setTimeout(res, ms); this.waiters.push(() => { clearTimeout(t); res(); }); }); }

  async send(cmd) {
    if (!this.connected) throw new Error('La bàscula no està connectada');
    await this.writer.write(new TextEncoder().encode(cmd + '\r\n'));
  }

  // Demana el pes fins que és estable. Torna {mg, unit, stable, raw}.
  async readStable(opts) {
    const o = opts || {};
    const deadline = Date.now() + (o.timeoutMs || 6000);
    const poll = o.pollMs || 250;
    while (Date.now() < deadline) {
      const since = Date.now();
      await this.send('IP');
      while (Date.now() - since < poll && !(this.last && this.last.at >= since)) await this._waitForData(poll);
      if (this.lastError && !(this.last && this.last.at >= since)) throw this.lastError;
      if (this.last && this.last.at >= since && this.last.stable) return this.last;
      if (!this.connected) throw new Error('S\'ha perdut la connexió amb la bàscula');
    }
    throw new Error('La bàscula no s\'estabilitza: espera que el pes quedi quiet');
  }

  tare() { return this.send('T'); }
  zero() { return this.send('Z'); }

  async disconnect() {
    this.connected = false;
    try { await this.reader?.cancel(); } catch (_) { /* ja tancat */ }
    try { this.writer?.releaseLock(); } catch (_) { /* ja alliberat */ }
    try { await this.port?.close(); } catch (_) { /* ja tancat */ }
  }
}

if (typeof module !== 'undefined') module.exports = { parsePesLine, Bascula, MG_PER_UNIT };
