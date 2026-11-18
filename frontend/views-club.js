'use strict';
// Controls del club: espera, avalador, altes pendents, excepcions de límit, lots i traçabilitat, llibres signats.

const AVALS = { no: "No s'utilitza", opcional: 'Opcional', obligatori: 'Obligatori' };

async function secControls() {
  const c = await api(`/locals/${S.local}/club-config`);
  const admin = isAdmin();
  const espera = h('input', { type: 'number', min: 0, max: 365, value: c.espera_dies, disabled: !admin });
  const aval = h('select', { disabled: !admin }, Object.entries(AVALS).map(([k, v]) => h('option', { value: k, selected: k === c.aval }, v)));
  const pendent = h('input', { type: 'checkbox', checked: c.alta_pendent, disabled: !admin });
  const out = h('div'), pend = h('div');
  const btn = h('button', { class: 'primary', type: 'submit', disabled: !admin }, 'Desar controls');
  async function pintaPendents() {
    const l = await api(`/locals/${S.local}/socis?estat=pendent`);
    pend.replaceChildren(h('h3', null, 'Altes pendents d\'aprovació'), taula([['Soci'], ['']], l.map((m) => {
      // La fila (botó, motiu, botó) es maqueta amb la classe .fila-accions de style.css: la CSP no permet estils en línia.
      const motiu = h('input', { maxlength: 200, placeholder: 'Motiu del rebuig', 'aria-label': 'Motiu del rebuig' });
      const aprova = h('button', { type: 'button', class: 'small', onclick: () => guard(aprova, out, async () => { await api(`/socis/${m.id}/aprovar`, { method: 'POST' }); toast('Soci aprovat'); await pintaPendents(); }) }, 'Aprovar');
      const rebutja = h('button', { type: 'button', class: 'small', onclick: () => guard(rebutja, out, async () => {
        if (motiu.value.trim().length < 3) throw new Error('Escriu el motiu del rebuig (mínim 3 caràcters)');
        await api(`/socis/${m.id}/rebutjar`, { method: 'POST', body: { motiu: motiu.value.trim() } });
        toast('Alta rebutjada'); await pintaPendents();
      }) }, 'Rebutjar');
      return [`${m.nom} (núm. ${m.id})`, h('div', { class: 'actions fila-accions' }, aprova, motiu, rebutja)];
    }), 'Cap alta pendent.'));
  }
  pintaPendents().catch((e) => pend.replaceChildren(msg('err', e.message)));
  return h('div', null, h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      await api(`/locals/${S.local}/club-config`, { method: 'PUT', body: { espera_dies: Number(espera.value), aval: aval.value, alta_pendent: pendent.checked } });
      toast('Controls desats');
    });
  } }, h('h3', null, 'Controls del local'),
  h('div', { class: 'row' }, field('Dies d\'espera des de l\'alta abans de dispensar', espera), field('Avalador a l\'alta', aval)),
  h('label', { class: 'check' }, pendent, ' Les altes noves queden pendents fins que un gestor les aprovi (un altre gestor o un administrador).'),
  admin ? null : h('p', { class: 'muted' }, 'Només un administrador pot canviar-los.'), h('div', { class: 'actions' }, btn), out), h('div', { class: 'card' }, pend));
}

function secLimits() {
  const zona = h('div');
  return h('div', null, selectorSoci((s) => {
    const out = h('div'), llista = h('div');
    const periode = h('select', null, h('option', { value: 'dia' }, 'Diari'), h('option', { value: 'mes' }, 'Mensual'));
    const max = h('input', { inputmode: 'decimal', placeholder: 'grams' }), motiu = h('input', { maxlength: 200, required: true });
    async function pinta() {
      const l = await api(`/socis/${s.id}/limits`);
      llista.replaceChildren(taula([['Període'], ['Límit', true], ['Motiu'], ['']], l.map((x) => [x.periode === 'dia' ? 'Diari' : 'Mensual', grams(x.max_mg), x.motiu,
        h('button', { type: 'button', class: 'small', onclick: (e) => guard(e.target, out, async () => {
          const m = await demana('Motiu per treure l\'excepció');
          if (!m) return;
          await api(`/socis/${s.id}/limits`, { method: 'PUT', body: { periode: x.periode, max_g: null, motiu: m } }); await pinta();
        }) }, 'Treure')]), 'Aquest soci fa servir els límits del local.'));
    }
    const btn = h('button', { class: 'primary', type: 'submit' }, 'Desar excepció');
    zona.replaceChildren(h('form', { class: 'card', onsubmit: (e) => {
      e.preventDefault();
      guard(btn, out, async () => {
        await api(`/socis/${s.id}/limits`, { method: 'PUT', body: { periode: periode.value, max_g: parseGrams(max.value), motiu: motiu.value.trim() } });
        toast('Excepció desada'); await pinta();
      });
    } }, h('h3', null, `Excepcions de límit · ${s.nom}`), llista, h('div', { class: 'row' }, field('Període', periode), field('Límit (g)', max), field('Motiu (obligatori)', motiu)),
    h('div', { class: 'actions' }, btn), out));
    pinta().catch((e) => llista.replaceChildren(msg('err', e.message)));
  }), zona);
}

async function secLots() {
  const prods = await api(`/locals/${S.local}/productes`);
  if (!prods.length) return h('p', { class: 'muted' }, 'Primer cal crear productes.');
  const prod = h('select', null, prods.map((p) => h('option', { value: p.id }, p.nom)));
  const llista = h('div'), traca = h('div'), out = h('div');
  const f = { codi: h('input', { maxlength: 40 }), origen: h('input', { maxlength: 120 }), prov: h('input', { maxlength: 120 }), collita: h('input', { maxlength: 40 }),
    data: h('input', { type: 'date', value: new Date().toLocaleDateString('sv-SE') }), analisi: h('input', { maxlength: 300 }) };
  async function pinta() {
    const l = await api(`/productes/${prod.value}/lots`);
    llista.replaceChildren(taula([['Lot'], ['Proveïdor'], ['Entrada'], ['Existències', true], ['']], l.map((b) => [b.codi + (b.actiu ? '' : ' (tancat)'), b.proveidor || '', b.data_entrada, grams(b.existencies_mg),
      h('div', { class: 'actions' },
        h('button', { type: 'button', class: 'small', onclick: (e) => guard(e.target, out, async () => {
          const g = await demana('Grams que entren en aquest lot'); if (!g) return;
          await api(`/lots/${b.id}/entrada`, { method: 'POST', body: { grams: parseGrams(g) } }); toast('Entrada registrada'); await pinta();
        }) }, 'Entrada'),
        h('button', { type: 'button', class: 'small', onclick: (e) => guard(e.target, out, async () => {
          const t = await api(`/lots/${b.id}/tracabilitat`);
          traca.replaceChildren(h('div', { class: 'card' }, h('h3', null, `Traçabilitat del lot ${b.codi}`),
            h('p', null, `Entrat ${grams(t.entrat_mg)} · dispensat ${grams(t.dispensat_mg)} · existències ${grams(t.existencies_mg)} · socis afectats: ${t.socis_afectats.join(', ') || '—'}`),
            taula([['Moviment'], ['Data'], ['Tipus'], ['mg', true], ['Soci']], t.moviments.map((m) => [m.moviment, dataHora(m.ts), m.tipus + (m.corregit ? ' (corregit)' : ''), m.mg, m.soci_id ?? ''])),
            h('button', { type: 'button', class: 'small', onclick: () => baixaFitxer(`/lots/${b.id}/tracabilitat.csv`, `tracabilitat-${b.codi}.csv`).catch((er) => toast(er.message)) }, 'Descarregar CSV')));
        }) }, 'Traçabilitat'),
        b.actiu ? h('button', { type: 'button', class: 'small', onclick: (e) => guard(e.target, out, async () => { await api(`/lots/${b.id}/tancar`, { method: 'POST' }); await pinta(); }) }, 'Tancar') : null)]),
      'Aquest producte encara no té lots.'));
  }
  prod.addEventListener('change', () => { traca.replaceChildren(); pinta().catch((e) => llista.replaceChildren(msg('err', e.message))); });
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Crear lot');
  pinta().catch((e) => llista.replaceChildren(msg('err', e.message)));
  return h('div', null, h('div', { class: 'card' }, h('h3', null, 'Lots per producte'), field('Producte', prod), llista, out), traca,
    h('form', { class: 'card', onsubmit: (e) => {
      e.preventDefault();
      guard(btn, out, async () => {
        await api(`/productes/${prod.value}/lots`, { method: 'POST', body: { codi: f.codi.value.trim(), origen: f.origen.value.trim() || null, proveidor: f.prov.value.trim() || null,
          collita: f.collita.value.trim() || null, data_entrada: f.data.value || null, analisi: f.analisi.value.trim() || null } });
        f.codi.value = ''; toast('Lot creat'); await pinta();
      });
    } }, h('h3', null, 'Nou lot'), h('div', { class: 'row' }, field('Codi', f.codi), field('Origen', f.origen), field('Proveïdor', f.prov)),
    h('div', { class: 'row' }, field('Collita', f.collita), field('Data d\'entrada', f.data), field('Anàlisi (opcional)', f.analisi)), h('div', { class: 'actions' }, btn)),
    h('p', { class: 'muted' }, 'Les dispensacions normals surten del lot més antic amb existències (FIFO). Les entrades amb lot es fan des d\'aquí.'));
}

function secLlibres() {
  const avui = new Date().toLocaleDateString('sv-SE');
  const des = h('input', { type: 'date', value: avui }), fins = h('input', { type: 'date', value: avui });
  const res = h('div'), out = h('div');
  const baixa = (nom, etiqueta) => {
    const b = h('button', { type: 'button', class: 'primary' }, etiqueta);
    b.addEventListener('click', () => guard(b, out, async () => {
      const r = await api(`/locals/${S.local}/llibres/${nom}.csv?des=${des.value}&fins=${fins.value}`, { raw: true });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "No s'ha pogut exportar");
      descarrega(await r.blob(), `llibre-${nom}-${des.value}_${fins.value}.csv`);
      res.replaceChildren(msg('ok', 'SHA-256 del fitxer (queda a l\'auditoria): ' + r.headers.get('X-Content-SHA256')));
    }));
    return b;
  };
  const hash = h('input', { placeholder: 'SHA-256 (64 caràcters)' }), vout = h('div');
  const vbtn = h('button', { type: 'submit' }, 'Comprovar');
  return h('div', null, h('div', { class: 'card' }, h('h3', null, 'Llibres exportables i signats'),
    h('div', { class: 'row' }, field('Des de', des), field('Fins a', fins)),
    h('div', { class: 'actions' }, baixa('socis', 'Llibre de socis (altes i baixes)'), baixa('estoc', "Llibre d'entrades i sortides")), res, out),
  h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(vbtn, vout, async () => {
      const r = await api('/llibres/verificar', { method: 'POST', body: { sha256: hash.value.trim().toLowerCase() } });
      vout.replaceChildren(r.coincidencies.length ? msg('ok', `Coincideix amb ${r.coincidencies.length} exportació(ns) registrada(es), l'última el ${dataHora(r.coincidencies[r.coincidencies.length - 1].ts)}.`)
        : msg('err', 'Cap exportació registrada té aquest hash: el fitxer no és original o ha estat alterat.'));
    });
  } }, h('h3', null, 'Comprovar un fitxer'), field('Hash SHA-256', hash), h('div', { class: 'actions' }, vbtn), vout));
}

VIEWS.club = async () => sections('club', [
  ['controls', 'Controls', secControls], ['limits', 'Límits per soci', async () => secLimits()],
  ['lots', 'Lots i traçabilitat', secLots], ['llibres', 'Llibres', async () => secLlibres()],
]);
