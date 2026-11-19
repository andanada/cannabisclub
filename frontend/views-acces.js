'use strict';
// Accés: una sola pantalla. Es passa el carnet RFID o es busca el soci (DNI/NIE/passaport, codi, nom o cognoms) i es registra l'entrada;
// a sota, els socis que són dins per ordre d'entrada amb foto, hora, avís d'incidències i botó de sortida.
// Un soci expulsat no pot entrar; si fa més de 3 mesos que no retira genètiques, el programa proposa cobrar la quota.

function bannerInactivitat(m, ina, alFinal) {
  const loc = S.me.locals.find((l) => l.id === S.local) || {};
  const out = h('div');
  const mesos = Math.floor(ina.dies / 30);
  const imp = h('input', { inputmode: 'decimal', value: loc.quota_cent ? preuText(loc.quota_cent) : '', placeholder: '0,00', 'aria-label': 'Import de la quota' });
  const met = h('select', { 'aria-label': 'Mètode' }, ['efectiu', 'targeta', 'bizum'].map((x) => h('option', { value: x }, x)));
  const cobra = h('button', { class: 'primary', type: 'button' }, 'Cobrar quota');
  const no = h('button', { type: 'button' }, 'No cobrar');
  const ref = novaRef();
  cobra.addEventListener('click', () => guard(cobra, out, async () => {
    const r = await api(`/socis/${m.id}/quotes`, { method: 'POST', body: { client_ref: ref, import_cent: parseEur(imp.value), metode: met.value, mesos: loc.quota_mesos || 1 } });
    toast('Quota cobrada: vàlida fins al ' + dataCa(r.valid_fins));
    alFinal();
  }));
  no.addEventListener('click', alFinal);
  return h('div', { class: 'acces-avis inactiu', role: 'alert' }, h('strong', null, `${m.nom}: fa ${mesos >= 1 ? mesos + ' mesos' : ina.dies + ' dies'} que no retira genètiques.`),
    h('span', null, 'Cobrar la quota?'), h('div', { class: 'actions' }, imp, met, cobra, no), out);
}

async function registraEntrada(m, resultat, refresca) {
  resultat.replaceChildren();
  try {
    const r = await api(`/socis/${m.id}/entrada`, { method: 'POST' });
    toast(m.nom + ': entrada registrada');
    resultat.replaceChildren(...[h('div', { class: 'acces-avis ok', role: 'status' }, h('strong', null, m.nom), ' ha entrat.'),
      alertesSoci(r.alertes), r.quota && !r.quota.al_dia ? msg('err', 'La quota no està al dia.') : null,
      r.inactivitat ? bannerInactivitat(m, r.inactivitat, () => { resultat.replaceChildren(); refresca(); }) : null].filter(Boolean));
  } catch (e) {
    // Soci expulsat, de baixa, etc.: avís gran i en vermell; no entra.
    resultat.replaceChildren(h('div', { class: 'acces-avis expulsat', role: 'alert' }, h('strong', null, m.nom), h('span', null, e.message)));
  }
  refresca();
}

async function registraSortida(m, resultat, refresca) {
  try { await api(`/socis/${m.id}/sortida`, { method: 'POST' }); toast(m.nom + ': sortida registrada'); resultat.replaceChildren(); }
  catch (e) { resultat.replaceChildren(msg('err', e.message)); }
  refresca();
}

VIEWS.acces = async () => {
  const arrel = h('div');
  const resultat = h('div');
  const llista = h('div');
  const refresca = async () => {
    const sortidaBtn = (s) => { const b = h('button', { type: 'button', class: 'small' }, 'Sortida'); b.addEventListener('click', () => guard(b, resultat, () => registraSortida(s, resultat, refresca))); return b; };
    const dins = await llistaDins(() => {}, sortidaBtn);
    const tots = isManager() ? h('div', { class: 'actions' }, (() => {
      const b = h('button', { type: 'button', class: 'danger' }, 'Sortir-ne tots');
      b.addEventListener('click', () => guard(b, resultat, async () => {
        if (!await confirma('Es registrarà la sortida de tots els socis que són dins. Continuar?', { perill: true, boto: 'Sortir-ne tots' })) return;
        const r = await api(`/locals/${S.local}/acces/sortir-tots`, { method: 'POST' });
        toast(r.sortits + ' socis han sortit');
        await refresca();
      }));
      return b;
    })()) : null;
    llista.replaceChildren(...[dins, tots].filter(Boolean));
  };
  // El carnet o la cerca porta al soci: si ja és dins se'n registra la sortida, si no l'entrada.
  const cerca = capsaCerca(async (m) => {
    const ids = (await api(`/locals/${S.local}/acces`)).dins.map((x) => x.id);
    if (ids.includes(m.id)) await registraSortida(m, resultat, refresca);
    else await registraEntrada(m, resultat, refresca);
  });
  arrel.append(pageHead('Accés', "Passa el carnet o busca el soci per registrar-ne l'entrada o la sortida."), cerca, resultat, llista);
  await refresca();
  return arrel;
};
