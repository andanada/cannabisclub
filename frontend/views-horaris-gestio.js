'use strict';
// Horaris (gerència): registre de canvis, avançaments de sou i configuració dels torns estàndard. Mai innerHTML.

const ACCIO_TXT = { assigna: 'Assignació', lleva: 'Lloc buidat', horari_torn: 'Horari del torn', horari_treballador: 'Horari del treballador',
  canvi: 'Canvi de torn aprovat', diferencia: "Diferència d'horari aprovada", config: 'Torns estàndard modificats' };

async function secRegistre() {
  const avui = new Date().toLocaleDateString('sv-SE');
  const fa30 = new Date(Date.now() - 30 * 86400000).toLocaleDateString('sv-SE');
  const des = h('input', { type: 'date', value: fa30 }), fins = h('input', { type: 'date', value: avui });
  const res = h('div'), out = h('div');
  const btn = h('button', { type: 'button', class: 'primary' }, 'Consultar');
  const carrega = () => guard(btn, out, async () => {
    const l = await api(`/locals/${S.local}/horaris/registre?des=${des.value}&fins=${fins.value}`);
    res.replaceChildren(taula([['Quan'], ['Qui'], ['Acció'], ['Dia'], ['Torn'], ['Treballador'], ['Abans'], ['Després']],
      l.map((c) => [new Date(c.ts).toLocaleString(loc()), c.actor, ACCIO_TXT[c.accio] || c.accio, c.data || '', c.torn ? TORN_TXT[c.torn] : '', c.usuari || '', c.abans || '', c.despres || '']),
      'Cap canvi en aquest període.'));
  });
  btn.addEventListener('click', carrega);
  carrega();
  return h('div', null, h('div', { class: 'card' }, h('div', { class: 'row' }, field('Des de', des), field('Fins a', fins)), h('div', { class: 'actions' }, btn), out), res);
}

async function secAvancos() {
  const avui = new Date().toLocaleDateString('sv-SE');
  const iniMes = avui.slice(0, 8) + '01';
  const mes = await api(`/locals/${S.local}/horaris/mes`);
  const out = h('div'), res = h('div');
  const data = h('input', { type: 'date', value: avui, max: avui, required: true });
  const user = h('select', { required: true }, mes.treballadors.map((t) => h('option', { value: t.id }, t.username)));
  const imp = h('input', { inputmode: 'decimal', placeholder: '0,00', required: true });
  const com = h('input', { maxlength: 300 });
  const caixa = h('input', { type: 'checkbox' });
  const metode = h('select', null, metodesIngres());
  const btn = h('button', { type: 'submit', class: 'primary' }, 'Apuntar avançament');
  const des = h('input', { type: 'date', value: iniMes }), fins = h('input', { type: 'date', value: avui });
  async function llista() {
    const r = await api(`/locals/${S.local}/horaris/avancos?des=${des.value}&fins=${fins.value}`);
    const files = r.avancos.map((a) => {
      const b = h('button', { type: 'button', class: 'small' }, 'Anul·lar');
      b.addEventListener('click', async () => {
        const nota = await demana("Motiu de l'anul·lació");
        if (!nota || nota.trim().length < 3) return;
        guard(b, out, async () => { await api(`/horaris/avancos/${a.id}/anulacio`, { method: 'POST', body: { nota: nota.trim() } }); toast('Avançament anul·lat'); await llista(); });
      });
      return [a.data, a.usuari, a.anulacio ? '−' + eur(a.import_cent) : eur(a.import_cent), a.de_caixa ? 'Sí' : 'No', a.comentari,
        a.anulacio ? h('span', { class: 'pill warn' }, 'anul·lació') : a.anulat ? h('span', { class: 'pill' }, 'anul·lat') : b];
    });
    res.replaceChildren(
      taula([['Treballador'], ['Total avançat', true]], r.totals.map((t) => [t.usuari, eur(t.import_cent)]), 'Cap avançament en aquest període.'),
      taula([['Data'], ['Treballador'], ['Import', true], ['De caixa'], ['Comentari'], ['']], files, 'Cap avançament en aquest període.'));
  }
  const form = h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      await api(`/locals/${S.local}/horaris/avancos`, { method: 'POST', body: { data: data.value, user_id: Number(user.value), import_cent: parseEur(imp.value),
        comentari: com.value.trim() || null, de_caixa: caixa.checked, metode: metode.value } });
      toast('Avançament apuntat: també consta a Despeses');
      imp.value = ''; com.value = '';
      await llista();
    });
  } }, h('h3', null, 'Nou avançament'), h('p', { class: 'muted' }, 'Cada avançament compta com a despesa (categoria «Sous/avançaments»).'),
  h('div', { class: 'row' }, field('Data', data), field('Treballador', user), field('Import (€)', imp), field('Comentari', com)),
  h('div', { class: 'row' }, h('label', { class: 'check' }, caixa, ' Surt de la caixa'), field('Mètode (si surt de caixa)', metode)),
  h('div', { class: 'actions' }, btn), out);
  des.addEventListener('change', llista); fins.addEventListener('change', llista);
  await llista();
  return h('div', null, form, h('div', { class: 'row' }, field('Des de', des), field('Fins a', fins)), res);
}

const dosParells = (v) => (v ? v : ['', '']);

async function secConfigTorns() {
  const cfg = await api(`/locals/${S.local}/horaris/config`);
  const out = h('div');
  const temps = (v, etiqueta) => h('input', { type: 'time', value: v || '', 'aria-label': etiqueta });
  const fila = (clau) => { const [a, b] = dosParells(cfg.torns[clau]); return { clau, ini: temps(a, 'Inici'), fi: temps(b, 'Fi') }; };
  const base = ['mati', 'tarda', 'unic'].map(fila);
  const dies = [0, 1, 2, 3, 4, 5, 6].map((i) => ({ i, c: h('input', { type: 'checkbox', checked: cfg.dies_unics.includes(i) }) }));
  const llistaExc = h('div', { class: 'hor-excepcions' });
  const excs = [];
  function afegeixExc(e) {
    const dia = h('input', { value: e ? e.dia : '', placeholder: 'MM-DD', maxlength: 10, 'aria-label': 'Dia' });
    const parells = ['mati', 'tarda', 'unic'].map((k) => { const [a, b] = dosParells(e && e.torns[k]); return { k, ini: temps(a, 'Inici'), fi: temps(b, 'Fi') }; });
    const item = { dia, parells };
    const treu = h('button', { type: 'button', class: 'small danger' }, 'Treure');
    const caixa = h('div', { class: 'hor-exc card' }, field('Dia (MM-DD o AAAA-MM-DD)', dia),
      parells.map((p) => h('div', { class: 'row' }, h('strong', null, TORN_TXT[p.k]), field('Inici', p.ini), field('Fi', p.fi))), treu);
    treu.addEventListener('click', () => { excs.splice(excs.indexOf(item), 1); caixa.remove(); });
    excs.push(item);
    llistaExc.append(caixa);
  }
  cfg.excepcions.forEach(afegeixExc);
  const btn = h('button', { type: 'button', class: 'primary' }, 'Desar els torns');
  btn.addEventListener('click', () => guard(btn, out, async () => {
    const torns = {};
    for (const b of base) torns[b.clau] = [b.ini.value, b.fi.value];
    const excepcions = excs.map((e) => ({ dia: e.dia.value.trim(), torns: Object.fromEntries(e.parells.filter((p) => p.ini.value && p.fi.value).map((p) => [p.k, [p.ini.value, p.fi.value]])) }));
    await api(`/locals/${S.local}/horaris/config`, { method: 'PUT', body: { torns, dies_unics: dies.filter((d) => d.c.checked).map((d) => d.i), excepcions } });
    toast('Torns estàndard desats');
  }));
  const afegeix = h('button', { type: 'button', onclick: () => afegeixExc(null) }, 'Afegir un dia especial');
  return h('div', null, h('div', { class: 'card' }, h('h3', null, 'Horari estàndard dels torns'),
    base.map((b) => h('div', { class: 'row' }, h('strong', null, TORN_TXT[b.clau]), field('Inici', b.ini), field('Fi', b.fi))),
    h('h3', null, 'Dies amb un sol torn (torn únic)'),
    h('div', { class: 'hor-dies-unics' }, dies.map((d) => h('label', { class: 'check' }, d.c, ' ' + nomDiaSetmana(d.i))))),
  h('div', { class: 'card' }, h('h3', null, 'Dies especials (festius)'), h('p', { class: 'muted' }, 'Deixa buits els torns que aquell dia no existeixen.'),
    llistaExc, h('div', { class: 'actions' }, afegeix)),
  h('div', { class: 'actions' }, btn), out);
}
