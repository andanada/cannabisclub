'use strict';
// Horaris: calendari mensual (dilluns a diumenge) amb dos llocs per torn, mode «Omplir», finestra del dia, càlculs mensuals i
// sol·licituds dels treballadors. Els treballadors només hi miren i senyalen canvis; la gerència ho modifica tot. Mai innerHTML.

const LLOCS_H = [['dispensari', 'Dispensari'], ['recepcio', 'Recepció']];
const TORN_TXT = { mati: 'Matí', tarda: 'Tarda', unic: 'Torn únic' };
const HOR = { any: new Date().getFullYear(), mes: new Date().getMonth() + 1, omplir: false, triat: null };

const pad2 = (n) => String(n).padStart(2, '0');
const horesTxt = (min) => (min / 60).toLocaleString(loc(), { maximumFractionDigits: 2 }) + ' h';
const nomDiaSetmana = (i) => new Date(2024, 0, 1 + i).toLocaleDateString(loc(), { weekday: 'short' });
const colorDe = (dades, id) => 'hor-c' + (Math.max(0, dades.treballadors.findIndex((t) => t.id === id)) % 10);
const nomDe = (dades, id) => (dades.treballadors.find((t) => t.id === id) || {}).username || '?';

// Hora que es mostra al costat del nom només si és diferent de l'estàndard del torn.
function horaPropia(torn, post) {
  if (!post || (!post.inici && !post.fi)) return '';
  const ini = post.inici && post.inici !== torn.inici ? post.inici : '';
  const fi = post.fi && post.fi !== torn.fi ? '–' + post.fi : '';
  return (ini || (fi ? torn.inici : '')) + fi;
}

function xipPost(dades, torn, post) {
  if (!post) return h('span', { class: 'hor-buit' }, '+');
  const hora = horaPropia(torn, post);
  return h('span', { class: 'hor-xip ' + colorDe(dades, post.user_id) }, nomDe(dades, post.user_id).toUpperCase(), hora ? h('small', null, hora) : null);
}

async function omplirPost(dades, dia, torn, lloc, post, refresca) {
  if (!HOR.triat) { toast('Tria primer un treballador'); return; }
  if (post && post.user_id !== HOR.triat) { toast('Aquest lloc ja és ocupat: toca el treballador que hi ha per treure\'l'); return; }
  const user_id = post ? null : HOR.triat;
  // Una darrere l'altra: tocar molt de pressa no ha de crear conflictes de concurrència.
  HOR.cua = (HOR.cua || Promise.resolve()).then(async () => {
    try {
      await api(`/locals/${S.local}/horaris/slot`, { method: 'PUT', body: { data: dia.data, torn: torn.torn, lloc, user_id } });
      await refresca();
    } catch (e) { toast(e.message); }
  });
  return HOR.cua;
}

function cellaDia(dades, dia, mgr, refresca) {
  const d = new Date(dia.data + 'T12:00:00');
  const cel = h('div', { class: 'hor-dia' + (dia.data === new Date().toLocaleDateString('sv-SE') ? ' avui' : '') + (dia.dia_setmana === 6 ? ' festiu' : ''), 'data-dia': dia.data });
  cel.append(h('div', { class: 'hor-num' }, h('strong', null, d.getDate()), h('span', { class: 'hor-nomdia' }, nomDiaSetmana(dia.dia_setmana))));
  for (const torn of dia.torns) {
    const bloc = h('div', { class: 'hor-torn' }, h('div', { class: 'hor-hores' }, torn.inici + '–' + torn.fi));
    for (const [lloc, etiqueta] of LLOCS_H) {
      const post = torn.llocs[lloc];
      const b = h('button', { type: 'button', class: 'hor-post', 'aria-label': `${etiqueta} ${torn.inici}-${torn.fi} ${dia.data}`, title: etiqueta }, xipPost(dades, torn, post));
      if (HOR.omplir && mgr) b.addEventListener('click', (e) => { e.stopPropagation(); omplirPost(dades, dia, torn, lloc, post, refresca); });
      bloc.append(b);
    }
    cel.append(bloc);
  }
  if (!HOR.omplir) { cel.tabIndex = 0; cel.addEventListener('click', () => obreDia(dades, dia, mgr, refresca)); cel.addEventListener('keydown', (e) => { if (e.key === 'Enter') obreDia(dades, dia, mgr, refresca); }); }
  return cel;
}

function quadricula(dades, mgr, refresca) {
  const cap = h('div', { class: 'hor-cap' }, [0, 1, 2, 3, 4, 5, 6].map((i) => h('div', null, nomDiaSetmana(i))));
  const primer = dades.dies[0].dia_setmana;
  const cels = [...Array(primer).fill(null).map(() => h('div', { class: 'hor-dia buit', 'aria-hidden': 'true' })), ...dades.dies.map((d) => cellaDia(dades, d, mgr, refresca))];
  return h('div', { class: 'hor-cal' + (HOR.omplir ? ' omplir' : '') }, cap, h('div', { class: 'hor-grid' }, cels));
}

function llegenda(dades, repinta) {
  return h('div', { class: 'hor-llegenda', role: 'group', 'aria-label': 'Treballadors' }, dades.treballadors.map((t) => {
    const actiu = HOR.omplir && HOR.triat === t.id;
    const b = h('button', { type: 'button', class: 'hor-xip ' + colorDe(dades, t.id) + (actiu ? ' triat' : ''), 'aria-pressed': actiu ? 'true' : 'false' }, t.username.toUpperCase());
    if (HOR.omplir) b.addEventListener('click', () => { HOR.triat = HOR.triat === t.id ? null : t.id; repinta(); });
    else b.disabled = true;
    return b;
  }));
}

function totals(dades) {
  return h('div', { class: 'card' }, h('h3', null, 'Torns i hores del mes'),
    taula([['Treballador'], ['Torns', true], ['Hores', true], ['Diferències aprovades', true]],
      dades.totals.map((t) => [h('span', { class: 'hor-xip ' + colorDe(dades, t.user_id) }, t.usuari.toUpperCase()), t.torns, horesTxt(t.minuts),
        t.minuts_diferencies ? (t.minuts_diferencies > 0 ? '+' : '−') + horesTxt(Math.abs(t.minuts_diferencies)) : '—']),
      'Encara no hi ha cap torn planificat aquest mes.'));
}

async function secCalendari() {
  const mgr = isManager();
  const cos = h('div');
  async function pinta() {
    const dades = await api(`/locals/${S.local}/horaris/mes?any=${HOR.any}&mes=${HOR.mes}`);
    const repinta = () => cos.replaceChildren(...contingut(dades));
    const refresca = async () => { const nous = await api(`/locals/${S.local}/horaris/mes?any=${HOR.any}&mes=${HOR.mes}`); Object.assign(dades, nous); repinta(); };
    function contingut() {
      const titol = new Date(HOR.any, HOR.mes - 1, 1).toLocaleDateString(loc(), { month: 'long', year: 'numeric' });
      const canvia = (delta) => { const d = new Date(HOR.any, HOR.mes - 1 + delta, 1); HOR.any = d.getFullYear(); HOR.mes = d.getMonth() + 1; pinta(); };
      const barra = h('div', { class: 'hor-barra' },
        h('button', { type: 'button', class: 'small', 'aria-label': 'Mes anterior', onclick: () => canvia(-1) }, '‹'),
        h('h3', { class: 'hor-titol' }, titol),
        h('button', { type: 'button', class: 'small', 'aria-label': 'Mes següent', onclick: () => canvia(1) }, '›'),
        h('button', { type: 'button', class: 'small', onclick: () => { HOR.any = new Date().getFullYear(); HOR.mes = new Date().getMonth() + 1; pinta(); } }, 'Avui'),
        mgr ? h('button', { type: 'button', class: HOR.omplir ? 'primary' : '', onclick: () => { HOR.omplir = !HOR.omplir; HOR.triat = null; repinta(); } }, HOR.omplir ? 'Acabar' : 'Omplir') : null);
      const avis = HOR.omplir ? h('p', { class: 'muted' }, 'Mode omplir: tria un treballador i toca els llocs buits. Torna a tocar un lloc seu per treure\'l.') : null;
      const aprovar = dades.pendents ? h('p', null, h('span', { class: 'pill warn' }, dades.pendents + (mgr ? ' sol·licituds pendents d\'aprovar' : ' sol·licituds teves pendents'))) : null;
      return [barra, aprovar, avis, llegenda(dades, repinta), quadricula(dades, mgr, refresca), totals(dades)].filter(Boolean);
    }
    repinta();
  }
  await pinta();
  return cos;
}

// ---------- finestra del dia ----------

function obreDia(dades, dia, mgr, refresca) {
  const d = new Date(dia.data + 'T12:00:00');
  const titol = d.toLocaleDateString(loc(), { weekday: 'long', day: 'numeric', month: 'long' });
  obreModal(titol, (tanca) => {
    const out = h('div');
    const meu = (S.me || {}).id;
    const blocs = dia.torns.map((torn) => mgr ? formTorn(dades, dia, torn, tanca, refresca, out) : vistaTorn(dades, dia, torn, tanca, out, meu));
    return h('div', { class: 'hor-modal' }, blocs, out);
  });
}

function vistaTorn(dades, dia, torn, tanca, out, meu) {
  const files = LLOCS_H.map(([lloc, etiqueta]) => {
    const p = torn.llocs[lloc];
    return h('div', { class: 'hor-fila' }, h('span', { class: 'muted' }, etiqueta), p ? xipPost(dades, torn, p) : h('span', { class: 'muted' }, 'Sense assignar'),
      p && p.user_id === meu ? h('button', { type: 'button', class: 'small', onclick: () => formSollicitud(dades, dia, torn, tanca) }, 'Senyalar un canvi') : null);
  });
  return h('section', { class: 'hor-modal-torn' }, h('h3', null, TORN_TXT[torn.torn] + ' · ' + torn.inici + '–' + torn.fi), files);
}

function formSollicitud(dades, dia, torn, tanca) {
  obreModal('Senyalar un canvi', (tanca2) => {
    const out = h('div');
    const tipus = h('select', { 'aria-label': 'Tipus de canvi' }, h('option', { value: 'diferencia' }, "Diferència d'horari"), h('option', { value: 'canvi' }, 'Canvi de torn'));
    const sentit = h('select', { 'aria-label': 'Sentit' }, h('option', { value: '-1' }, 'Surto abans'), h('option', { value: '1' }, 'Em quedo més estona'));
    const min = h('input', { type: 'number', min: 5, max: 720, step: 5, value: 60, 'aria-label': 'Minuts' });
    const subs = h('select', { 'aria-label': 'Substitut' }, h('option', { value: '' }, 'Ningú (queda lliure)'),
      ...dades.treballadors.filter((t) => t.id !== S.me.id).map((t) => h('option', { value: t.id }, t.username)));
    const com = h('input', { maxlength: 300, 'aria-label': 'Comentari' });
    const caixaDif = h('div', { class: 'row' }, field('Sentit', sentit), field('Minuts', min));
    const caixaCanvi = h('div', { class: 'row', hidden: true }, field('Substitut', subs));
    tipus.addEventListener('change', () => { caixaDif.hidden = tipus.value !== 'diferencia'; caixaCanvi.hidden = tipus.value !== 'canvi'; });
    const btn = h('button', { type: 'submit', class: 'primary' }, 'Enviar a l\'encarregada');
    return h('form', { onsubmit: (e) => {
      e.preventDefault();
      guard(btn, out, async () => {
        const cos = { tipus: tipus.value, data: dia.data, torn: torn.torn, comentari: com.value.trim() || null };
        if (tipus.value === 'diferencia') cos.minuts = Number(sentit.value) * Number(min.value);
        else cos.substitut_id = subs.value ? Number(subs.value) : null;
        await api(`/locals/${S.local}/horaris/sollicituds`, { method: 'POST', body: cos });
        toast('Sol·licitud enviada: l\'encarregada l\'ha d\'aprovar');
        tanca2(); tanca(); show('fitxatge');
      });
    } }, h('p', { class: 'muted' }, 'No es farà efectiu fins que l\'encarregada l\'aprovi.'), field('Què vols senyalar?', tipus), caixaDif, caixaCanvi, field('Comentari', com), h('div', { class: 'actions' }, btn), out);
  });
}

function formTorn(dades, dia, torn, tanca, refresca, out) {
  const ini = h('input', { type: 'time', value: torn.inici, 'aria-label': 'Inici del torn' }), fi = h('input', { type: 'time', value: torn.fi, 'aria-label': 'Fi del torn' });
  const llocs = LLOCS_H.map(([lloc, etiqueta]) => {
    const p = torn.llocs[lloc];
    const sel = h('select', { 'aria-label': etiqueta }, h('option', { value: '' }, '—'), ...dades.treballadors.map((t) => h('option', { value: t.id, selected: !!p && p.user_id === t.id }, t.username)));
    const pi = h('input', { type: 'time', value: p && p.inici ? p.inici : '', 'aria-label': 'Inici propi' }), pf = h('input', { type: 'time', value: p && p.fi ? p.fi : '', 'aria-label': 'Fi propi' });
    return { lloc, etiqueta, sel, pi, pf, p };
  });
  const btn = h('button', { type: 'button', class: 'primary' }, 'Desar el torn');
  btn.addEventListener('click', () => guard(btn, out, async () => {
    const base = `/locals/${S.local}/horaris`;
    if (ini.value !== torn.inici || fi.value !== torn.fi) await api(base + '/torn', { method: 'PUT', body: { data: dia.data, torn: torn.torn, inici: ini.value, fi: fi.value } });
    for (const l of llocs) {
      const nou = l.sel.value ? Number(l.sel.value) : null;
      const propi = nou && l.pi.value && l.pf.value ? [l.pi.value, l.pf.value] : null;
      const abans = l.p ? [l.p.user_id, l.p.inici, l.p.fi] : [null, null, null];
      if (nou !== abans[0] || (propi ? propi[0] : null) !== abans[1] || (propi ? propi[1] : null) !== abans[2])
        await api(base + '/slot', { method: 'PUT', body: { data: dia.data, torn: torn.torn, lloc: l.lloc, user_id: nou, inici: propi ? propi[0] : null, fi: propi ? propi[1] : null } });
    }
    toast('Torn desat');
    tanca();
    await refresca();
  }));
  return h('section', { class: 'hor-modal-torn' }, h('h3', null, TORN_TXT[torn.torn]),
    h('div', { class: 'row' }, field('Inici del torn', ini), field('Fi del torn', fi)),
    llocs.map((l) => h('div', { class: 'hor-edita' }, h('strong', null, l.etiqueta), h('div', { class: 'row' }, field('Treballador', l.sel), field('Hora pròpia: inici', l.pi), field('Hora pròpia: fi', l.pf)))),
    h('div', { class: 'actions' }, btn));
}

// ---------- sol·licituds ----------

const ESTAT_TXT = { pendent: 'Pendent', aprovada: 'Aprovada', rebutjada: 'Rebutjada', 'cancel·lada': 'Cancel·lada' };
const ESTAT_PILL = { pendent: 'warn', aprovada: 'ok', rebutjada: 'bad', 'cancel·lada': '' };

function descSollicitud(r) {
  if (r.tipus === 'diferencia') return (r.minuts < 0 ? 'Surt ' : 'Es queda ') + Math.abs(r.minuts) + (r.minuts < 0 ? ' min abans' : ' min més');
  return 'Canvi de torn' + (r.substitut ? ' · el cobreix ' + r.substitut : ' · queda lliure');
}

async function secSollicituds() {
  const mgr = isManager();
  const llista = await api(`/locals/${S.local}/horaris/sollicituds`);
  const out = h('div');
  const accio = (r, etiqueta, ruta, cos, perill) => {
    const b = h('button', { type: 'button', class: 'small' + (perill ? ' danger' : ''), onclick: () => guard(b, out, async () => {
      let nota = null;
      if (ruta === 'rebutja') { nota = await demana('Motiu (opcional)'); if (nota === null) return; }
      await api(`/horaris/sollicituds/${r.id}/${ruta}`, { method: 'POST', body: ruta === 'cancela' ? undefined : { nota: nota || null } });
      toast(etiqueta);
      show('fitxatge');
    }) }, ruta === 'aprova' ? 'Aprovar' : ruta === 'rebutja' ? 'Rebutjar' : 'Cancel·lar');
    return b;
  };
  const files = llista.map((r) => [new Date(r.ts).toLocaleDateString(loc()), r.usuari, new Date(r.data + 'T12:00:00').toLocaleDateString(loc(), { day: 'numeric', month: 'short' }) + ' · ' + TORN_TXT[r.torn],
    descSollicitud(r) + (r.comentari ? ' · ' + r.comentari : ''), h('span', { class: 'pill ' + ESTAT_PILL[r.estat] }, ESTAT_TXT[r.estat]),
    r.estat !== 'pendent' ? [r.resolt_per || '', r.nota ? ' · ' + r.nota : ''] : h('div', { class: 'actions fila-accions' },
      mgr ? [accio(r, 'Sol·licitud aprovada', 'aprova'), accio(r, 'Sol·licitud rebutjada', 'rebutja', null, true)] : (r.usuari === S.me.username ? accio(r, 'Sol·licitud cancel·lada', 'cancela') : null))]);
  return h('div', null, h('p', { class: 'lead' }, mgr ? 'Els canvis que senyalen els treballadors no compten fins que els aprovis.' : 'Les teves sol·licituds. Per senyalar-ne una, toca el teu torn al calendari.'),
    taula([['Enviada'], ['Treballador'], ['Dia i torn'], ['Canvi'], ['Estat'], ['Resolució']], files, 'Cap sol·licitud.'), out);
}

// Vista principal: pestanyes. Les de gestió són només per a la gerència (vegeu views-horaris-gestio.js).
VIEWS.fitxatge = async () => {
  const items = [['calendari', 'Calendari', secCalendari], ['sollicituds', 'Sol·licituds', secSollicituds], ['fitxar', 'Fitxar', secFitxar]];
  if (isManager()) items.push(['registre', 'Registre de canvis', secRegistre], ['avancos', 'Avançaments', secAvancos], ['torns', 'Torns estàndard', secConfigTorns]);
  return h('div', null, pageHead('Horaris', 'Calendari de torns, canvis, fitxatge i avançaments.'), sections('fitxatge', items));
};
