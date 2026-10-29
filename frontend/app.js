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
  const codeField = field("Codi de l'app d'autenticació", code);
  // Si el servidor no exigeix el segon factor (servidor de proves), el camp no es mostra.
  fetch('/auth/opcions').then((r) => r.json()).then((o) => { if (!o.totp) { codeField.hidden = true; code.required = false; } }).catch(() => {});
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
  h('div', { class: 'actions' }, langSelect()), h('h1', null, 'Gestió del club'),
  field('Usuari', user), field('Contrasenya', pass), codeField,
  h('div', { class: 'actions' }, btn), out);
  $('#app').replaceChildren(form);
  user.focus();
}

const TABS = [
  ['dispensar', 'Dispensar', () => true],
  ['socis', 'Socis', () => true],
  ['estoc', 'Estoc', isManager, [
    ['existencies', 'Existències'], ['magatzems', 'Magatzems'], ['linies', 'Línies de preu'], ['contenidors', 'Contenidors'],
    ['tipus-contenidor', 'Tipus de contenidors'], ['moviment', 'Moviments'], ['inventari', 'Inventaris'], ['descomptes', 'Descomptes'],
    ['regles', 'Regles'], ['productes', 'Productes'], ['historial', 'Historial']]],
  ['caixa', 'Caixa', () => true],
  ['fitxatge', 'Fitxatge', () => true],
  ['informe', 'Informes', isManager, [['vendes', 'Vendes'], ['dispensacions', 'Dispensacions'], ['evolucio', 'Evolució del club'], ['demografia', 'Demografia'], ['caixa', 'Caixa'], ['estoc', 'Estoc valorat'], ['assistencia', 'Assistència'], ['hores', 'Hores']]],
  ['config', 'Configuració', isManager],
  ['compte', 'Compte', () => true],
];

// Marca l'entrada activa del menú (i la subentrada, si n'hi ha) i desplega el grup de la vista actual.
function marcaMenu() {
  document.querySelectorAll('nav.tabs button[data-view]').forEach((b) => {
    const actual = b.dataset.view === S.view;
    const sub = b.dataset.sub;
    const triada = sessionStorage.getItem('s:' + S.view);
    const marcat = sub ? actual && triada === sub : actual && !b.classList.contains('has-sub');
    if (marcat || (actual && b.classList.contains('has-sub') && !triada)) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
  });
  document.querySelectorAll('nav.tabs .sub-group').forEach((g) => { g.hidden = g.dataset.view !== S.view; });
}

function localSelect() {
  const sel = h('select', { 'aria-label': 'Local', onchange: () => { S.local = Number(sel.value); sessionStorage.setItem('l', S.local); show(S.view); } },
    S.me.locals.map((l) => h('option', { value: l.id, selected: l.id === S.local }, l.nom)));
  return sel;
}

function renderShell() {
  const nav = h('nav', { class: 'tabs', 'aria-label': 'Seccions' },
    TABS.filter((t) => t[2]()).flatMap(([id, label, , subs]) => {
      const main = h('button', { 'data-view': id, class: subs ? 'has-sub' : '', onclick: () => show(id) }, icon(id), h('span', null, label));
      if (!subs) return [main];
      const grup = h('div', { class: 'sub-group', 'data-view': id, hidden: true }, subs.map(([sid, slabel]) =>
        h('button', { 'data-view': id, 'data-sub': sid, class: 'sub', onclick: () => { sessionStorage.setItem('s:' + id, sid); show(id); } }, h('span', null, slabel))));
      return [main, grup];
    }));
  const side = h('aside', { class: 'side' }, h('div', { class: 'side-in' },
    h('div', { class: 'brand' }, h('div', { class: 'logo', 'aria-hidden': 'true' }, 'C'), h('div', null, 'Gestió del club', h('small', null, 'Panell de treball'))),
    nav,
    h('div', { class: 'who' }, h('div', null, h('strong', null, S.me.username), ' · ', S.me.role), localSelect(), langSelect(),
      h('button', { class: 'small', onclick: logout }, 'Sortir'))));
  const topbar = h('div', { class: 'topbar' }, h('strong', null, 'Gestió del club'),
    h('div', { class: 'row' }, localSelect(), langSelect(), h('button', { class: 'small', onclick: logout }, 'Sortir')));
  $('#app').replaceChildren(h('div', { class: 'shell' }, side, h('div', null, topbar, h('main', { id: 'main', class: 'main' }))));
}

async function show(view) {
  S.view = view;
  marcaMenu();
  const main = $('#main');
  main.replaceChildren(h('p', { class: 'muted' }, 'Carregant…'));
  try { main.replaceChildren(await VIEWS[view]()); } catch (e) { main.replaceChildren(msg('err', e.message)); }
}

// Primer arrencada: encara no hi ha cap local. L'administrador en crea el primer i entra.
function renderFirstLocal() {
  const nom = h('input', { required: true, maxlength: 60, placeholder: 'Nom del club o del local' });
  const out = h('div');
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Crear local i entrar');
  const form = h('form', { class: 'card login', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      await api('/locals', { method: 'POST', body: { nom: nom.value.trim() } });
      await boot();
    });
  } }, h('h1', null, 'Benvingut'), h('p', { class: 'muted' }, "Encara no hi ha cap local. Crea'n el primer per començar; després hi podràs afegir productes, socis i usuaris."),
  field('Nom del local', nom), h('div', { class: 'actions' }, btn, h('button', { type: 'button', onclick: logout }, 'Sortir')), out);
  $('#app').replaceChildren(form);
  nom.focus();
}

async function boot() {
  try {
    S.me = await api('/me');
  } catch (e) { return; }
  if (!S.me.locals.length && S.me.role === 'admin') { renderFirstLocal(); return; }
  if (!S.me.locals.length) { $('#app').replaceChildren(msg('err', 'Aquest usuari no té cap local assignat.'), h('button', { onclick: logout }, 'Sortir')); return; }
  const saved = Number(sessionStorage.getItem('l'));
  S.local = S.me.locals.some((l) => l.id === saved) ? saved : S.me.locals[0].id;
  renderShell();
  show(S.view);
}

if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
if (S.token) boot().then(() => { if (!S.me) renderLogin(); }); else renderLogin();
