'use strict';
// Generador de codis QR sense llibreries (mode byte, correcció d'errors M, versions 1-10: fins a ~210 caràcters).
// Ús: QR.matriu('adreça') -> array de files de booleans; QR.svg(text, px) -> element <svg> (construït amb el DOM).
(function (global) {
  const ECC_PER_BLOC = [0, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26];
  const BLOCS = [0, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5];

  function bitsCru(v) {
    let r = (16 * v + 128) * v + 64;
    if (v >= 2) { const n = Math.floor(v / 7) + 2; r -= (25 * n - 10) * n - 55; if (v >= 7) r -= 36; }
    return r;
  }
  function posicionsAlineacio(v) {
    if (v === 1) return [];
    const n = Math.floor(v / 7) + 2, mida = v * 4 + 17;
    const pas = Math.ceil((v * 4 + 4) / (n * 2 - 2)) * 2;
    const r = [6];
    for (let p = mida - 7; r.length < n; p -= pas) r.splice(1, 0, p);
    return r;
  }
  function mulGF(x, y) {
    let z = 0;
    for (let i = 7; i >= 0; i--) { z = (z << 1) ^ ((z >>> 7) * 0x11d); z ^= ((y >>> i) & 1) * x; }
    return z;
  }
  function divisor(grau) {
    const r = new Array(grau).fill(0);
    r[grau - 1] = 1;
    let arrel = 1;
    for (let i = 0; i < grau; i++) {
      for (let j = 0; j < grau; j++) { r[j] = mulGF(r[j], arrel); if (j + 1 < grau) r[j] ^= r[j + 1]; }
      arrel = mulGF(arrel, 2);
    }
    return r;
  }
  function residu(dades, div) {
    const r = new Array(div.length).fill(0);
    for (const b of dades) {
      const f = b ^ r.shift();
      r.push(0);
      div.forEach((c, i) => { r[i] ^= mulGF(c, f); });
    }
    return r;
  }

  function codifica(bytes) {
    let v = 1;
    for (;; v++) {
      if (v > 10) throw new Error('Text massa llarg per al QR');
      const cap = Math.floor(bitsCru(v) / 8) - ECC_PER_BLOC[v] * BLOCS[v];
      if (4 + (v < 10 ? 8 : 16) + 8 * bytes.length <= cap * 8) break;
    }
    const capDades = Math.floor(bitsCru(v) / 8) - ECC_PER_BLOC[v] * BLOCS[v];
    const bits = [];
    const push = (val, n) => { for (let i = n - 1; i >= 0; i--) bits.push((val >>> i) & 1); };
    push(4, 4); push(bytes.length, v < 10 ? 8 : 16);
    bytes.forEach((b) => push(b, 8));
    push(0, Math.min(4, capDades * 8 - bits.length));
    while (bits.length % 8) bits.push(0);
    for (let pad = 0xec; bits.length < capDades * 8; pad ^= 0xec ^ 0x11) push(pad, 8);
    const dades = [];
    for (let i = 0; i < bits.length; i += 8) dades.push(parseInt(bits.slice(i, i + 8).join(''), 2));
    // blocs + correcció d'errors
    const nb = BLOCS[v], le = ECC_PER_BLOC[v], cru = Math.floor(bitsCru(v) / 8);
    const curts = nb - (cru % nb), llargCurt = Math.floor(cru / nb);
    const div = divisor(le), blocs = [];
    for (let i = 0, k = 0; i < nb; i++) {
      const dat = dades.slice(k, k + llargCurt - le + (i < curts ? 0 : 1));
      k += dat.length;
      const ecc = residu(dat, div);
      if (i < curts) dat.push(0);
      blocs.push(dat.concat(ecc));
    }
    const tot = [];
    for (let i = 0; i < blocs[0].length; i++) blocs.forEach((b, j) => { if (i !== llargCurt - le || j >= curts) tot.push(b[i]); });
    return { v, tot };
  }

  function matriu(text) {
    const bytes = Array.from(new TextEncoder().encode(String(text)));
    const { v, tot } = codifica(bytes);
    const n = v * 4 + 17;
    const m = Array.from({ length: n }, () => new Array(n).fill(false));
    const fn = Array.from({ length: n }, () => new Array(n).fill(false));
    const set = (x, y, d) => { m[y][x] = d; fn[y][x] = true; };
    for (let i = 0; i < n; i++) { set(6, i, i % 2 === 0); set(i, 6, i % 2 === 0); }
    for (const [cx, cy] of [[3, 3], [n - 4, 3], [3, n - 4]]) {
      for (let dy = -4; dy <= 4; dy++) for (let dx = -4; dx <= 4; dx++) {
        const d = Math.max(Math.abs(dx), Math.abs(dy)), x = cx + dx, y = cy + dy;
        if (x >= 0 && x < n && y >= 0 && y < n) set(x, y, d !== 2 && d !== 4);
      }
    }
    const al = posicionsAlineacio(v);
    al.forEach((cx, i) => al.forEach((cy, j) => {
      if ((i === 0 && j === 0) || (i === 0 && j === al.length - 1) || (i === al.length - 1 && j === 0)) return;
      for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) set(cx + dx, cy + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
    }));
    const format = (mask) => {
      const dd = (0 << 3) | mask;   // M = 00
      let r = dd;
      for (let i = 0; i < 10; i++) r = (r << 1) ^ ((r >>> 9) * 0x537);
      const b = ((dd << 10) | r) ^ 0x5412, bit = (i) => ((b >>> i) & 1) !== 0;
      for (let i = 0; i <= 5; i++) set(8, i, bit(i));
      set(8, 7, bit(6)); set(8, 8, bit(7)); set(7, 8, bit(8));
      for (let i = 9; i < 15; i++) set(14 - i, 8, bit(i));
      for (let i = 0; i < 8; i++) set(n - 1 - i, 8, bit(i));
      for (let i = 8; i < 15; i++) set(8, n - 15 + i, bit(i));
      set(8, n - 8, true);
    };
    format(0);
    if (v >= 7) {
      let r = v;
      for (let i = 0; i < 12; i++) r = (r << 1) ^ ((r >>> 11) * 0x1f25);
      const b = (v << 12) | r;
      for (let i = 0; i < 18; i++) { const bit = ((b >>> i) & 1) !== 0, a = n - 11 + (i % 3), c = Math.floor(i / 3); set(a, c, bit); set(c, a, bit); }
    }
    let i = 0;
    for (let dreta = n - 1; dreta >= 1; dreta -= 2) {
      if (dreta === 6) dreta = 5;
      for (let vert = 0; vert < n; vert++) for (let j = 0; j < 2; j++) {
        const x = dreta - j, amunt = ((dreta + 1) & 2) === 0, y = amunt ? n - 1 - vert : vert;
        if (!fn[y][x] && i < tot.length * 8) { m[y][x] = ((tot[i >>> 3] >>> (7 - (i & 7))) & 1) !== 0; i++; }
      }
    }
    const MASQUES = [(x, y) => (x + y) % 2 === 0, (x, y) => y % 2 === 0, (x) => x % 3 === 0, (x, y) => (x + y) % 3 === 0,
      (x, y) => (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0, (x, y) => ((x * y) % 2) + ((x * y) % 3) === 0,
      (x, y) => (((x * y) % 2) + ((x * y) % 3)) % 2 === 0, (x, y) => (((x + y) % 2) + ((x * y) % 3)) % 2 === 0];
    const aplica = (k) => { for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) if (!fn[y][x] && MASQUES[k](x, y)) m[y][x] = !m[y][x]; };
    const penal = () => {
      let p = 0, negres = 0;
      for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
        if (m[y][x]) negres++;
        if (x < n - 1 && y < n - 1 && m[y][x] === m[y][x + 1] && m[y][x] === m[y + 1][x] && m[y][x] === m[y + 1][x + 1]) p += 3;
      }
      for (const t of [false, true]) for (let a = 0; a < n; a++) {
        let run = 1;
        for (let b = 1; b < n; b++) {
          const cur = t ? m[b][a] : m[a][b], prev = t ? m[b - 1][a] : m[a][b - 1];
          if (cur === prev) { run++; if (run === 5) p += 3; else if (run > 5) p++; } else run = 1;
        }
      }
      return p + Math.floor(Math.abs(negres * 20 - n * n * 10) / (n * n)) * 10;
    };
    let millor = 0, minim = Infinity;
    for (let k = 0; k < 8; k++) { aplica(k); format(k); const p = penal(); if (p < minim) { minim = p; millor = k; } aplica(k); }
    aplica(millor); format(millor);
    return m;
  }

  // <svg> amb el QR (marge de 4 mòduls). Només rectangles: res d'estils en línia.
  function svg(text, px) {
    const m = matriu(text), n = m.length, NS = 'http://www.w3.org/2000/svg';
    const s = document.createElementNS(NS, 'svg');
    s.setAttribute('viewBox', `0 0 ${n + 8} ${n + 8}`);
    s.setAttribute('width', px || 192); s.setAttribute('height', px || 192);
    s.setAttribute('role', 'img'); s.setAttribute('aria-label', 'Codi QR de l’enllaç');
    const fons = document.createElementNS(NS, 'rect');
    fons.setAttribute('width', n + 8); fons.setAttribute('height', n + 8); fons.setAttribute('fill', '#ffffff');
    s.append(fons);
    const path = document.createElementNS(NS, 'path');
    let d = '';
    m.forEach((fila, y) => fila.forEach((on, x) => { if (on) d += `M${x + 4} ${y + 4}h1v1h-1z`; }));
    path.setAttribute('d', d); path.setAttribute('fill', '#000000');
    s.append(path);
    return s;
  }

  global.QR = { matriu, svg };
  if (typeof module !== 'undefined' && module.exports) module.exports = global.QR;
})(typeof window !== 'undefined' ? window : globalThis);
