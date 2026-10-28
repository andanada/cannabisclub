'use strict';
// Utilitats comunes: construcció segura del DOM (mai innerHTML), API, formats.
const $ = (s, r = document) => r.querySelector(s);

let idSeq = 0;
function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  if (tag === 'input' || tag === 'select' || tag === 'textarea') e.id = 'i' + (++idSeq);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) e.setAttribute(k, v === true ? '' : v);
  }
  for (const k of kids.flat()) {
    if (k == null || k === false) continue;
    e.append(k.nodeType ? k : document.createTextNode(String(k)));
  }
  return e;
}

const S = { token: sessionStorage.getItem('t'), me: null, local: null, view: 'dispensar' };

function toast(text) {
  const t = $('#toast');
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toast.id);
  toast.id = setTimeout(() => { t.hidden = true; }, 3500);
}

async function api(path, opts = {}) {
  const headers = {};
  if (S.token) headers.Authorization = 'Bearer ' + S.token;
  if (opts.body) headers['Content-Type'] = 'application/json';
  let r;
  try {
    r = await fetch(path, { method: opts.method || 'GET', headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
  } catch (_) {
    // «Failed to fetch»: el navegador no arriba al servidor (parat, adreça diferent, sense xarxa).
    throw new Error('No es pot connectar amb el servidor. Comprova que el programa està en marxa i que tens connexió.');
  }
  if (r.status === 401 && S.token && !opts.noAuthRedirect) { logout(); throw new Error('La sessió ha caducat'); }
  if (opts.raw) return r;
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = data.detail;
    throw new Error(typeof d === 'string' ? d : (Array.isArray(d) && d[0] && d[0].msg) || 'Error de servidor');
  }
  return data;
}

const eur = (c) => (c / 100).toLocaleString(loc(), { style: 'currency', currency: 'EUR' });
const grams = (mg) => (mg / 1000).toLocaleString(loc(), { maximumFractionDigits: 3 }) + ' g';

function parseGrams(text) {
  const t = String(text).trim().replace(',', '.');
  if (!/^\d+(\.\d{1,3})?$/.test(t)) throw new Error('Quantitat no vàlida (màxim 3 decimals)');
  return t;
}
function parseEur(text) {
  const t = String(text).trim().replace(',', '.');
  if (!/^\d+(\.\d{1,2})?$/.test(t)) throw new Error('Import no vàlid (màxim 2 decimals)');
  return Math.round(parseFloat(t) * 100);
}

function field(label, input) {
  return h('div', null, h('label', { for: input.id }, label), input);
}
function msg(kind, text) { return h('div', { class: 'msg ' + kind, role: kind === 'err' ? 'alert' : 'status' }, text); }

// Executa una acció amb gestió d'errors i desactiva el botó mentre treballa.
async function guard(btn, out, fn) {
  btn.disabled = true;
  out.replaceChildren();
  try { await fn(); } catch (e) { out.replaceChildren(msg('err', e.message)); } finally { btn.disabled = false; }
}

const isManager = () => ['admin', 'encarregat'].includes(S.me.role);

// Icones de la navegació (SVG construït amb el DOM: la CSP no permet innerHTML ni estils en línia).
const ICONS = {
  dispensar: 'M12 3v18M5 8l7-5 7 5M4 21h16M7 12h10',
  socis: 'M16 19v-1a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v1M9.5 10a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7M21 19v-1a4 4 0 0 0-3-3.9M16 3.2a3.5 3.5 0 0 1 0 6.6',
  estoc: 'M21 8l-9-5-9 5 9 5 9-5zM3 8v8l9 5 9-5V8M12 13v8',
  caixa: 'M3 7h18v12H3zM3 11h18M16 15h2',
  fitxatge: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18M12 7v5l3 2',
  informe: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
  config: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z',
  compte: 'M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8',
};

function icon(name) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.8');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', ICONS[name] || ICONS.config);
  svg.append(path);
  return svg;
}

// Una pantalla amb diverses subseccions, d'una en una: [[id, etiqueta, async () => node], ...].
// Recorda l'última subsecció oberta; cada subsecció es carrega quan s'obre.
function sections(viewId, items) {
  const bar = h('div', { class: 'segments', role: 'tablist' });
  const body = h('div');
  const saved = sessionStorage.getItem('s:' + viewId);
  const first = items.some((i) => i[0] === saved) ? saved : items[0][0];
  const buttons = items.map(([id, label]) => {
    const b = h('button', { type: 'button', role: 'tab', 'data-sec': id }, label);
    b.addEventListener('click', () => open(id));
    return b;
  });
  bar.append(...buttons);
  let token = 0;
  async function open(id) {
    const mine = ++token;
    sessionStorage.setItem('s:' + viewId, id);
    buttons.forEach((b) => b.setAttribute('aria-selected', String(b.dataset.sec === id)));
    body.replaceChildren(h('p', { class: 'muted' }, 'Carregant…'));
    try {
      const node = await items.find((i) => i[0] === id)[2]();
      if (mine === token) body.replaceChildren(node);
    } catch (e) { if (mine === token) body.replaceChildren(msg('err', e.message)); }
  }
  open(first);
  return h('div', null, bar, body);
}

const pageHead = (title, lead) => h('div', { class: 'page-head' }, h('h2', null, title), lead ? h('p', { class: 'lead' }, lead) : null);
