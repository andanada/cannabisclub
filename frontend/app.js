'use strict';
// Arrencada, login, estructura i navegació. Les pantalles són a views-*.js (objecte VIEWS).
const VIEWS = {};

function logout() {
  if (S.token) fetch('/auth/logout', { method: 'POST', headers: { Authorization: 'Bearer ' + S.token } }).catch(() => {});
  S.token = null; S.me = null;
  sessionStorage.removeItem('t');
  renderLogin();
}

function renderLogin() {
  const out = h('div');
  const user = h('input', { autocomplete: 'username', required: true });
  const pass = h('input', { type: 'password', autocomplete: 'current-password', required: true });
  const code = h('input', { inputmode: 'numeric', autocomplete: 'one-time-code', maxlength: 6, required: true });
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Entrar');
  const form = h('form', { class: 'card login', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      const r = await api('/auth/login', { method: 'POST', noAuthRedirect: true,
        body: { username: user.value.trim(), password: pass.value, totp: code.value.trim() } });
      S.token = r.token;
      sessionStorage.setItem('t', r.token);
      pass.value = ''; code.value = '';
      await boot();
    });
  } },
  h('h1', null, 'Gestió del club'),
  field('Usuari', user), field('Contrasenya', pass), field('Codi de l\'app d\'autenticació', code),
  h('div', { class: 'actions' }, btn), out);
  $('#app').replaceChildren(form);
  user.focus();
}

const TABS = [
  ['dispensar', 'Dispensar', () => true],
  ['socis', 'Socis', () => true],
  ['estoc', 'Estoc', () => true],
  ['caixa', 'Caixa', () => true],
  ['fitxatge', 'Fitxatge', () => true],
  ['informe', 'Informe', isManager],
  ['admin', 'Admin', () => S.me.role === 'admin'],
  ['compte', 'Compte', () => true],
];

function renderShell() {
  const sel = h('select', { 'aria-label': 'Local', onchange: () => { S.local = Number(sel.value); sessionStorage.setItem('l', S.local); show(S.view); } },
    S.me.locals.map((l) => h('option', { value: l.id, selected: l.id === S.local }, l.nom)));
  const nav = h('nav', { class: 'tabs', 'aria-label': 'Seccions' },
    TABS.filter((t) => t[2]()).map(([id, label]) =>
      h('button', { 'data-view': id, onclick: () => show(id) }, label)));
  $('#app').replaceChildren(
    h('header', { class: 'top' },
      h('div', null, h('h1', null, 'Gestió del club'), h('div', { class: 'who' }, S.me.username + ' · ' + S.me.role)),
      h('div', { class: 'row' }, sel, h('button', { onclick: logout }, 'Sortir'))),
    h('main', { id: 'main' }), nav);
}

async function show(view) {
  S.view = view;
  document.querySelectorAll('nav.tabs button').forEach((b) => {
    if (b.dataset.view === view) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
  });
  const main = $('#main');
  main.replaceChildren(h('p', { class: 'muted' }, 'Carregant…'));
  try { main.replaceChildren(await VIEWS[view]()); } catch (e) { main.replaceChildren(msg('err', e.message)); }
}

async function boot() {
  try {
    S.me = await api('/me');
  } catch (e) { return; }
  if (!S.me.locals.length) { $('#app').replaceChildren(msg('err', 'Aquest usuari no té cap local assignat.'), h('button', { onclick: logout }, 'Sortir')); return; }
  const saved = Number(sessionStorage.getItem('l'));
  S.local = S.me.locals.some((l) => l.id === saved) ? saved : S.me.locals[0].id;
  renderShell();
  show(S.view);
}

if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
if (S.token) boot().then(() => { if (!S.me) renderLogin(); }); else renderLogin();
