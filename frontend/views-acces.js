'use strict';
// Accés al local: pantalla manual (socis dins / fora, clic per entrar o sortir, «Sortir-ne tots») i mode quiosc RFID
// (passar el carnet registra entrada o sortida, a pantalla gran). Mai innerHTML: tot el text va com a node de text.

const horaCurta = (iso) => new Date(iso).toLocaleTimeString(loc(), { hour: '2-digit', minute: '2-digit' });

// Columna de socis amb comptador i buscador. `accio(soci, boto)` s'executa en prémer un soci.
function columnaAcces(titol, socis, accio, detall) {
  const cerca = h('input', { type: 'search', placeholder: 'Buscar…', 'aria-label': 'Buscar soci', autocomplete: 'off' });
  const llista = h('ul', { class: 'llista-acces' });
  const compte = h('span', { class: 'pill' });
  const pinta = () => {
    const t = cerca.value.trim().toLowerCase();
    const f = socis.filter((s) => !t || s.nom.toLowerCase().includes(t));
    compte.textContent = String(socis.length);
    llista.replaceChildren(...(f.length ? f.map((s) => {
      const b = h('button', { type: 'button', class: 'fila-acces' }, h('strong', null, s.nom), detall ? h('span', { class: 'muted' }, detall(s)) : null);
      b.addEventListener('click', () => accio(s, b));
      return h('li', null, b);
    }) : [h('li', { class: 'muted' }, 'Ningú')]));
  };
  cerca.addEventListener('input', pinta);
  pinta();
  return h('div', { class: 'card' }, h('h3', null, titol, ' ', compte), cerca, llista);
}

async function accesManual() {
  const out = h('div');
  const box = h('div');
  const carrega = async () => {
    const e = await api(`/locals/${S.local}/acces`);
    const entra = (s, b) => guard(b, out, async () => { await api(`/socis/${s.id}/entrada`, { method: 'POST' }); toast(s.nom + ': entrada registrada'); await carrega(); });
    const surt = (s, b) => guard(b, out, async () => { await api(`/socis/${s.id}/sortida`, { method: 'POST' }); toast(s.nom + ': sortida registrada'); await carrega(); });
    const tots = h('button', { type: 'button', class: 'danger' }, 'Sortir-ne tots');
    tots.addEventListener('click', () => guard(tots, out, async () => {
      const r = await api(`/locals/${S.local}/acces/sortir-tots`, { method: 'POST' });
      toast(r.sortits + ' socis han sortit');
      await carrega();
    }));
    box.replaceChildren(h('div', { class: 'row acces-cols' },
      columnaAcces('Socis sense check-in', e.fora, entra),
      h('div', null, columnaAcces('Socis amb check-in', e.dins, surt, (s) => 'entrada ' + horaCurta(s.entrada)),
        isManager() && e.dins.length ? h('div', { class: 'actions' }, tots) : null)));
  };
  await carrega();
  return h('div', null, box, out);
}

// Mode quiosc: pantalla gran amb un camp que sempre té el focus (el lector escriu el codi i prem Intro).
function accesQuiosc() {
  const codi = h('input', { class: 'card-input', autocomplete: 'off', autocapitalize: 'characters', spellcheck: 'false', 'aria-label': 'Carnet', placeholder: 'Passa el carnet pel lector' });
  const resultat = h('div', { class: 'quiosc-resultat', role: 'status', 'aria-live': 'polite' }, h('p', { class: 'muted' }, 'Posa el carnet al lector'));
  const form = h('form', { class: 'quiosc' }, h('h2', null, 'Accés per carnet'), codi, resultat);
  let timer = null;
  const refoca = () => { if (document.body.contains(codi)) codi.focus(); };
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const valor = codi.value.trim();
    codi.value = '';
    if (!valor) return;
    clearTimeout(timer);
    try {
      const r = await api(`/locals/${S.local}/acces/carnet`, { method: 'POST', body: { codi: normalizeScan(valor, await readerProfile()) } });
      const entra = r.accio === 'entrada';
      resultat.replaceChildren(h('div', { class: 'quiosc-ok ' + (entra ? 'entra' : 'surt') }, h('div', { class: 'gran-marca', 'aria-hidden': 'true' }, entra ? '→' : '←'),
        h('div', { class: 'big' }, r.nom), h('p', null, entra ? 'Benvingut/da. Entrada registrada.' : 'Fins aviat. Sortida registrada.'),
        entra && r.quota && !r.quota.al_dia ? h('p', { class: 'pill warn' }, 'La quota no està al dia') : null));
    } catch (er) {
      resultat.replaceChildren(h('div', { class: 'quiosc-ok error' }, h('div', { class: 'gran-marca', 'aria-hidden': 'true' }, '!'), msg('err', er.message)));
    }
    timer = setTimeout(() => { resultat.replaceChildren(h('p', { class: 'muted' }, 'Posa el carnet al lector')); refoca(); }, 6000);
    refoca();
  });
  const pantalla = h('button', { type: 'button' }, 'Pantalla completa');
  pantalla.addEventListener('click', () => { if (document.documentElement.requestFullscreen) document.documentElement.requestFullscreen().catch(() => {}); refoca(); });
  form.addEventListener('click', refoca);
  setTimeout(refoca, 0);
  return h('div', null, form, h('div', { class: 'actions' }, pantalla));
}

VIEWS.acces = async () => h('div', null, pageHead('Accés', 'Entrades i sortides dels socis al local.'), await sections('acces', [
  ['manual', 'Accés manual', accesManual], ['quiosc', 'Quiosc RFID', async () => accesQuiosc()],
]));
