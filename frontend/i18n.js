'use strict';
// Idiomes: català (el de l'origen del text), castellà i anglès.
// Els textos del programa estan escrits en català; aquí es tradueixen en pintar-los al DOM, així que cap pantalla
// no depèn d'aquest fitxer. Els diccionaris són a i18n-*.js: I18N.es / I18N.en = { «text en català»: «traducció» }
// i I18N.pat.es / I18N.pat.en = [[expressió regular, plantilla amb $1…], …] per als textos amb dades (noms, imports…).
// Canviar d'idioma recarrega la pàgina (la sessió es conserva a sessionStorage).

const I18N = window.I18N = window.I18N || { es: {}, en: {}, pat: { es: [], en: [] } };
const LANGS = { ca: 'Català', es: 'Castellano', en: 'English' };
const LOCALES = { ca: 'ca-ES', es: 'es-ES', en: 'en-GB' };

function detectLang() {
  let saved = null;
  try { saved = localStorage.getItem('lang'); } catch (_) { /* sense emmagatzematge */ }
  if (saved in LANGS) return saved;
  const n = (navigator.language || 'ca').slice(0, 2).toLowerCase();
  return n in LANGS ? n : 'ca';
}
let LANG = detectLang();
document.documentElement.lang = LANG;
const loc = () => LOCALES[LANG];

function setLang(code) {
  try { localStorage.setItem('lang', code); } catch (_) { /* es perd en tancar */ }
  location.reload();
}

// Tradueix un text (mantenint els espais de les vores). Sense traducció, es deixa com està.
function tr(text) {
  if (LANG === 'ca' || typeof text !== 'string') return text;
  const m = /^(\s*)([\s\S]*?)(\s*)$/.exec(text);
  const core = m[2];
  if (!core) return text;
  const dict = I18N[LANG];
  if (Object.prototype.hasOwnProperty.call(dict, core)) return m[1] + dict[core] + m[3];
  for (const [re, tpl] of I18N.pat[LANG]) {
    const r = re.exec(core);
    if (r) return m[1] + core.replace(re, tpl) + m[3];
  }
  return text;
}

const ATTRS = ['placeholder', 'title', 'aria-label', 'alt'];
const SKIP = new Set(['SCRIPT', 'STYLE', 'CANVAS', 'TEXTAREA', 'PRE']);

function translateTree(root) {
  if (LANG === 'ca') return;
  if (root.nodeType === 3) { const v = tr(root.nodeValue); if (v !== root.nodeValue) root.nodeValue = v; return; }
  if (root.nodeType !== 1 || SKIP.has(root.tagName) || root.closest('[data-no-i18n]')) return;
  ATTRS.forEach((a) => { if (root.hasAttribute(a)) { const v = tr(root.getAttribute(a)); if (v !== root.getAttribute(a)) root.setAttribute(a, v); } });
  root.childNodes.forEach(translateTree);
}

if (LANG !== 'ca') {
  new MutationObserver((muts) => {
    for (const m of muts) {
      if (m.type === 'childList') m.addedNodes.forEach(translateTree);
      else if (m.type === 'characterData') translateTree(m.target);
      else if (m.type === 'attributes') translateTree(m.target);
    }
  }).observe(document.documentElement, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  document.addEventListener('DOMContentLoaded', () => { document.title = tr(document.title); translateTree(document.body); });
  // Els diàlegs del navegador no passen pel DOM.
  for (const f of ['confirm', 'prompt', 'alert']) { const o = window[f].bind(window); window[f] = (msg, ...rest) => o(tr(msg), ...rest); }
}

// Selector d'idioma (el fa servir el panell lateral, el de dalt al mòbil i la pantalla d'entrada).
function langSelect() {
  const sel = document.createElement('select');
  sel.setAttribute('aria-label', 'Language');
  sel.setAttribute('data-no-i18n', '');
  for (const [code, name] of Object.entries(LANGS)) {
    const o = document.createElement('option');
    o.value = code; o.textContent = name; o.selected = code === LANG;
    sel.append(o);
  }
  sel.addEventListener('change', () => setLang(sel.value));
  return sel;
}
