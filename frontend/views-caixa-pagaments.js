'use strict';
// Pagaments i caixa: mètodes de pagament de la quota i de les donacions, foto gran en fer el check-in,
// tancament de torn amb fons de caixa, billets i monedes, i fulla imprimible dels totals del TPV.

const METODES_TXT = { efectiu: 'Efectiu', targeta: 'Targeta', bizum: 'Bizum', monedero: 'Crèdits del compte' };

// Mètodes amb què es pot cobrar al local: efectiu sempre; targeta i Bizum només si el local els ha activat (Configuració);
// els crèdits del compte del soci només quan s'indica (la quota).
function metodesIngres(opcions) {
  const loc = S.me.locals.find((l) => l.id === S.local) || {};
  const llista = ['efectiu', ...(loc.targeta_activa ? ['targeta', 'bizum'] : []), ...(opcions && opcions.monedero ? ['monedero'] : [])];
  return llista.map((x) => h('option', { value: x }, METODES_TXT[x]));
}

// Foto del soci en gran (finestra modal) en fer-ne el check-in: així es reconeix bé qui entra.
function fotoGranModal(m) {
  return obreModal(m.nom, () => h('div', { class: 'foto-gran' }, fotoSoci(m.id, m.nom, 320),
    h('div', { class: 'foto-gran-nom' }, m.nom)));
}

// ---------- tancament de torn ----------

const eurOpt = (text) => (String(text).trim() === '' ? 0 : parseEur(text));
const textEur = (c) => (c / 100).toFixed(2).replace('.', ',');

// Fulla imprimible amb els totals del TPV (targeta i Bizum) del torn. L'efectiu no hi surt: va a part, al tancament.
function fullaTpv(t, empleat) {
  const fila = (nom, n, cent) => h('tr', null, h('td', null, nom), h('td', { class: 'num' }, String(n)), h('td', { class: 'num' }, eur(cent)));
  return h('div', { class: 'card' }, h('div', { class: 'print-area tpv-fulla' },
    h('h3', null, 'Totals del TPV del torn'),
    h('p', { class: 'muted' }, new Date().toLocaleString(loc()) + (empleat ? ' · ' + empleat : '')),
    h('table', null, h('thead', null, h('tr', null, h('th', null, 'Mètode'), h('th', { class: 'num' }, 'Cobraments'), h('th', { class: 'num' }, 'Import'))),
      h('tbody', null, fila('Targeta', t.targeta_n, t.targeta_cent), fila('Bizum', t.bizum_n, t.bizum_cent),
        h('tr', { class: 'total' }, h('td', null, 'Total TPV'), h('td'), h('td', { class: 'num' }, eur(t.total_cent))))),
    h('p', { class: 'muted' }, "Compara aquests imports amb el tancament del datàfon. L'efectiu no hi és inclòs.")),
  (() => { const b = h('button', { class: 'primary', type: 'button' }, 'Imprimir la fulla del TPV'); b.addEventListener('click', () => window.print()); return h('div', { class: 'actions' }, b); })());
}

async function closeForm() {
  const st = await api(`/locals/${S.local}/caixa`);
  if (!st.oberta) return h('div', { class: 'card empty' }, 'No hi ha cap caixa oberta per tancar.');
  const loc1 = S.me.locals.find((l) => l.id === S.local) || {};
  const comptat = h('input', { inputmode: 'decimal', placeholder: '0,00', 'aria-label': 'Efectiu comptat' });
  const fons = h('input', { inputmode: 'decimal', placeholder: '0,00', 'aria-label': 'Fons de caixa que es deixa', value: st.fons_darrer_cent != null ? textEur(st.fons_darrer_cent) : '' });
  const billets = h('input', { inputmode: 'decimal', placeholder: '0,00', 'aria-label': 'Billets que surten' });
  const monedes = h('input', { inputmode: 'decimal', placeholder: '0,00', 'aria-label': 'Monedes que surten' });
  const surt = h('div', { class: 'big' }, eur(0));
  const quadra = h('div', { class: 'muted', role: 'status' });
  const btn = h('button', { class: 'danger', type: 'submit' }, 'Tancar caixa');
  const out = h('div');
  const box = h('div');
  const calcula = () => {
    try {
      const total = eurOpt(comptat.value) - eurOpt(fons.value);
      surt.textContent = eur(total);
      const resta = total - eurOpt(billets.value) - eurOpt(monedes.value);
      quadra.className = resta === 0 && total >= 0 ? 'pill ok' : 'pill warn';
      quadra.textContent = total < 0 ? 'El fons és més gran que l’efectiu comptat' : resta === 0 ? 'Billets i monedes quadren' : (resta > 0 ? 'Falten ' : 'Sobren ') + eur(Math.abs(resta));
    } catch (e) { quadra.className = 'pill warn'; quadra.textContent = 'Import no vàlid'; }
  };
  for (const i of [comptat, fons, billets, monedes]) i.addEventListener('input', calcula);
  calcula();
  const avisAbans = senseCobrar(st.sense_cobrar, st.sense_cobrar_cent, false);
  if (avisAbans) box.append(avisAbans);
  box.append(h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      const body = { local_id: S.local, counted_cent: parseEur(comptat.value), fons_cent: eurOpt(fons.value), billets_cent: eurOpt(billets.value), monedes_cent: eurOpt(monedes.value) };
      const r = await api('/caixa/tancar', { method: 'POST', body });
      const d = r.diferencia_cent;
      const xifra = (t, v) => h('div', { class: 'stat' }, h('div', { class: 'muted' }, t), h('div', { class: 'big' }, v));
      box.replaceChildren(...[h('div', { class: 'card' }, h('h3', null, 'Caixa tancada'), h('div', { class: 'stats' },
        xifra('Esperat', eur(r.esperat_cent)), xifra('Comptat', eur(r.comptat_cent)),
        h('div', { class: 'stat' }, h('div', { class: 'muted' }, 'Diferència'), h('span', { class: 'pill ' + (d === 0 ? 'ok' : 'bad') }, (d > 0 ? '+' : '') + eur(d)))),
      h('div', { class: 'stats' }, xifra('Fons que es deixa', eur(r.fons_deixat_cent)), xifra('Surten en billets', eur(r.sortida_billets_cent)), xifra('Surten en monedes', eur(r.sortida_monedes_cent)))),
      loc1.targeta_activa || r.tpv.total_cent ? fullaTpv(r.tpv, S.me.username) : null, senseCobrar(r.sense_cobrar, r.sense_cobrar_cent, true)].filter(Boolean));
    });
  } }, h('h3', null, 'Tancament de caixa'),
  h('p', { class: 'muted' }, "Compta l'efectiu del calaix (només efectiu: targeta i Bizum van a part). Escriu el fons que es deixa a la caixa: el programa calcula el total que en surt i cal repartir-lo en billets i monedes."),
  field('Efectiu comptat al calaix (€)', comptat), field('Fons de caixa que es deixa (€)', fons),
  h('div', { class: 'stat' }, h('div', { class: 'muted' }, 'Total que surt de la caixa'), surt),
  h('div', { class: 'row' }, field('Dels quals, billets (€)', billets), field('Dels quals, monedes (€)', monedes)), quadra,
  h('div', { class: 'actions' }, btn), out));
  return box;
}
