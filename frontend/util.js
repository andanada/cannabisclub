'use strict';
// Utilitats comunes: construcció segura del DOM (mai innerHTML), API, formats.
const $ = (s, r = document) => r.querySelector(s);

let idSeq = 0;
function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  if (tag === 'input' || tag === 'select' || tag === 'textarea') e.id = 'i' + (++idSeq);
  // Un <button> sense «type» dins d'un <form> l'envia: aquí només envia qui ho demana amb type: 'submit'.
  if (tag === 'button' && !(attrs && attrs.type)) e.setAttribute('type', 'button');
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

// Igual, però amb diversos botons que fan la mateixa operació (p. ex. tres maneres de dispensar): es bloquegen tots,
// perquè prémer-ne un altre mentre el primer treballa no la faci dues vegades.
async function guardTots(btns, out, fn) {
  btns.forEach((b) => { b.disabled = true; });
  out.replaceChildren();
  try { await fn(); } catch (e) { out.replaceChildren(msg('err', e.message)); } finally { btns.forEach((b) => { b.disabled = false; }); }
}

// Referència d'una operació amb diners o producte. Es crea quan es prepara l'operació (no a cada clic): si la petició es
// repeteix (Intro, segon clic, reintent perquè la resposta s'ha perdut), el servidor no la torna a fer i retorna el mateix resultat.
function novaRef() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
  let r = '';
  while (r.length < 32) r += Math.floor(Math.random() * 16).toString(16);
  return r;
}

const isManager = () => ['admin', 'encarregat'].includes(S.me.role);
// Permís concret: la gerència els té tots; un treballador, només els que l'administrador li ha donat (S.me.permisos).
const te = (clau) => isManager() || (S.me.permisos || []).includes(clau);

// Icones de la navegació (SVG construït amb el DOM: la CSP no permet innerHTML ni estils en línia).
const ICONS = {
  dispensar: 'M12 3v18M5 8l7-5 7 5M4 21h16M7 12h10',
  socis: 'M16 19v-1a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v1M9.5 10a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7M21 19v-1a4 4 0 0 0-3-3.9M16 3.2a3.5 3.5 0 0 1 0 6.6',
  estoc: 'M21 8l-9-5-9 5 9 5 9-5zM3 8v8l9 5 9-5V8M12 13v8',
  caixa: 'M3 7h18v12H3zM3 11h18M16 15h2',
  acces: 'M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4M10 17l5-5-5-5M15 12H3',
  gastos: 'M12 2v20M17 6.5C17 4.6 14.8 3.5 12 3.5S7 4.6 7 6.5 9 9.4 12 10s5 1.3 5 3.5-2.2 3-5 3-5-1.1-5-3',
  estadistiques: 'M21 12A9 9 0 1 1 12 3v9zM15 3.5A9 9 0 0 1 20.5 9H15z',
  descomptes: 'M19 5L5 19M7.5 9a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3M16.5 18a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3',
  fitxatge: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18M12 7v5l3 2',
  informe: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
  estinf: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
  cameres: 'M23 7l-7 5 7 5V7zM1 5h15v14H1z',
  menus: 'M3 5h18v11H3zM8 20h8M12 16v4M7 9h6M7 12h10',
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
    if (typeof marcaMenu === 'function') marcaMenu();
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

// Diàlegs propis (en lloc de confirm()/prompt() del navegador, que bloquegen i no es poden estilar ni traduir).
// Tots dos retornen una promesa: confirma → true/false; demana → text (o null si es cancel·la). Esc o fora = cancel·lar.
function dialegModal(titol, cos, primariText, perill) {
  return new Promise((resolve) => {
    const dlg = h('dialog', { class: 'dialeg', 'aria-label': titol });
    const ok = h('button', { type: 'submit', class: perill ? 'danger' : 'primary' }, primariText);
    const no = h('button', { type: 'button' }, 'Cancel·lar');
    const form = h('form', { method: 'dialog' }, h('p', { class: 'dialeg-text' }, titol), ...cos, h('div', { class: 'actions' }, no, ok));
    dlg.append(form);
    let valor = false;
    form.addEventListener('submit', (e) => { e.preventDefault(); valor = true; dlg.close(); });
    no.addEventListener('click', () => dlg.close());
    dlg.addEventListener('close', () => { dlg.remove(); resolve(valor); });
    document.body.append(dlg);
    dlg.showModal();
    (cos[0] || no).focus();
  });
}

async function confirma(text, { perill = false, boto = 'Continuar' } = {}) {
  if (typeof document.createElement !== 'function' || !window.HTMLDialogElement) return window.confirm(text);
  return dialegModal(text, [], boto, perill);
}

async function demana(text, { placeholder = '' } = {}) {
  if (typeof document.createElement !== 'function' || !window.HTMLDialogElement) return window.prompt(text);
  const camp = h('input', { type: 'text', 'aria-label': text, placeholder, autocomplete: 'off', maxlength: 200 });
  const ok = await dialegModal(text, [camp], 'Acceptar', false);
  return ok ? camp.value : null;
}

// Observacions de soci: tipus i banner d'alertes (compartits per Accés, Dispensar i la fitxa).
const TIPUS_OBS = { nota: 'Observació', comportament: 'Mal comportament', objecte: 'Objecte oblidat al club', avis: 'Avís' };

// Banner amb les alertes obertes del soci (null si no n'hi ha). Es mostra al personal en fer l'entrada i en dispensar.
function alertesSoci(alertes) {
  if (!alertes || !alertes.length) return null;
  return h('div', { class: 'alerta-soci', role: 'alert' }, h('strong', null, alertes.length === 1 ? 'Alerta del soci' : 'Alertes del soci'),
    h('ul', null, alertes.map((a) => h('li', null, h('span', { class: 'pill warn' }, TIPUS_OBS[a.tipus] || a.tipus), ' ', a.descripcio))));
}
