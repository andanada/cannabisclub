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
  const r = await fetch(path, { method: opts.method || 'GET', headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
  if (r.status === 401 && S.token && !opts.noAuthRedirect) { logout(); throw new Error('La sessió ha caducat'); }
  if (opts.raw) return r;
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = data.detail;
    throw new Error(typeof d === 'string' ? d : (Array.isArray(d) && d[0] && d[0].msg) || 'Error de servidor');
  }
  return data;
}

const eur = (c) => (c / 100).toLocaleString('ca-ES', { style: 'currency', currency: 'EUR' });
const grams = (mg) => (mg / 1000).toLocaleString('ca-ES', { maximumFractionDigits: 3 }) + ' g';

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
