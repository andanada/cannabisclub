'use strict';
// Estoc › Existències i moviments: llista per categories amb Magatzem i Dispensari, avisos d'estoc baix i finestra de moviments.

const ESTAT_EX = { esgotat: ['bad', 'Esgotat'], baix: ['warn', 'Estoc baix'] };

async function existenciesSection() {
  const arrel = h('div');
  const estat = { genetic: true, q: '' };
  const pinta = async () => {
    const r = await api(`/locals/${S.local}/existencies`);
    const avisos = r.productes.filter((p) => p.estat !== 'ok').length;
    const cos = h('div');
    const mostra = () => {
      const t = estat.q.trim().toLowerCase();
      const files = r.productes.filter((p) => p.es_genetic === estat.genetic && (!t || p.nom.toLowerCase().includes(t)));
      const cats = [...new Set(files.map((p) => p.categoria || 'Sense categoria'))].sort();
      cos.replaceChildren(...(cats.length ? cats.map((c) => h('div', { class: 'card' }, h('h3', null, c),
        taula([['Producte'], ['Magatzem', true], ['Dispensari', true], ['']], files.filter((p) => (p.categoria || 'Sense categoria') === c).map((p) => {
          const marca = ESTAT_EX[p.estat];
          const b = h('button', { type: 'button', class: 'small primary' }, 'Moviments');
          b.addEventListener('click', () => movimentsModal(p, r.magatzem_id, pinta));
          return [p.nom, p.magatzem_g + ' ' + unitTxt(p), h('span', null, p.dispensari_g + ' ' + unitTxt(p), ' ', marca ? h('span', { class: 'pill ' + marca[0] }, marca[1]) : null), b];
        }), 'Cap producte.')))
        : [h('div', { class: 'card empty' }, 'Cap producte.')]));
    };
    const cerca = h('input', { type: 'search', placeholder: 'Cercar producte…', 'aria-label': 'Cercar producte', autocomplete: 'off' });
    cerca.addEventListener('input', () => { estat.q = cerca.value; mostra(); });
    const barra = h('div', { class: 'pestanyes', role: 'tablist' });
    [[true, 'Genètiques'], [false, 'No genètiques']].forEach(([v, t]) => {
      const b = h('button', { type: 'button', role: 'tab', 'aria-pressed': String(v === estat.genetic) }, t);
      b.addEventListener('click', () => { estat.genetic = v; [...barra.children].forEach((x) => x.setAttribute('aria-pressed', String(x === b))); mostra(); });
      barra.append(b);
    });
    mostra();
    arrel.replaceChildren(...[
      avisos ? msg('err', isManager() ? `${avisos} productes per acabar o esgotats (l'avís es configura a Configuració › Normes del club).` : `${avisos} productes per acabar o esgotats.`) : null,
      h('div', { class: 'row dis-filtre' }, barra, cerca), cos].filter(Boolean));
  };
  await pinta();
  return arrel;
}

// Finestra de moviments d'un producte: entrada, moviment entre llocs o sortida, amb els totals sempre visibles i l'historial petit.
function movimentsModal(p, magatzemId, alTancar) {
  const un = unitTxt(p);
  obreModal(p.nom, (tanca) => {
    const arrel = h('div');
    const estat = { tipus: 'entrada' };
    const pinta = async () => {
      const [r, hist] = await Promise.all([api(`/locals/${S.local}/existencies`), api(`/productes/${p.id}/moviments`)]);
      const act = r.productes.find((x) => x.id === p.id) || p;
      const out = h('div');
      const lloc = (id) => id === 'mag' ? 'Magatzem' : 'Dispensari';
      const opcions = (sel) => ['mag', 'dis'].map((v) => h('option', { value: v, selected: v === sel }, lloc(v)));
      const destiEntrada = h('select', { 'aria-label': 'On entra' }, opcions('mag'));
      const de = h('select', { 'aria-label': 'De' }, opcions('mag'));
      const a = h('select', { 'aria-label': 'A' }, opcions('dis'));
      const origenSortida = h('select', { 'aria-label': 'D\'on surt' }, opcions('dis'));
      const q = h('input', { inputmode: 'decimal', placeholder: '0', 'aria-label': 'Quantitat', class: 'dis-q' });
      // Preu pagat per AQUESTA entrada (total, €): el preu d'entrada fix del producte només és el suggeriment (preu × quantitat).
      const cost = h('input', { inputmode: 'decimal', placeholder: '0,00', 'aria-label': 'Preu pagat per aquesta entrada' });
      const tocatCost = { v: false };
      cost.addEventListener('input', () => { tocatCost.v = true; });
      q.addEventListener('input', () => {
        if (tocatCost.v || act.preu_entrada_cent == null) return;
        try { const g = parseGrams(q.value); cost.value = g > 0 ? preuText(Math.round(act.preu_entrada_cent * g)) : ''; } catch (_) { cost.value = ''; }
      });
      const nota = h('textarea', { rows: 2, maxlength: 300, placeholder: 'Comentaris (opcional)', 'aria-label': 'Comentaris' });
      const ident = (v) => (v === 'mag' ? magatzemId : null);
      const btn = h('button', { class: 'primary', type: 'submit' }, 'Confirmar moviment');
      const camps = { entrada: [field('On entra', destiEntrada)], moure: [h('div', { class: 'row' }, field('De', de), field('A', a))], sortida: [field("D'on surt", origenSortida)] }[estat.tipus];
      const form = h('form', { onsubmit: (e) => {
        e.preventDefault();
        guard(btn, out, async () => {
          const g = parseGrams(q.value);
          const comentari = nota.value.trim();
          if (estat.tipus === 'entrada' && !cost.value.trim()
            && !(await confirma("Sense preu no es crea la despesa ni el cost real. Vols desar l'entrada igualment?", { boto: 'Desar sense preu' }))) return;
          if (estat.tipus === 'entrada') await api('/moviments/entrada', { method: 'POST', body: { product_id: p.id, grams: g, nota: comentari || null, magatzem_id: ident(destiEntrada.value), cost_cent: cost.value.trim() ? parseEur(cost.value) : null } });
          else if (estat.tipus === 'moure') {
            if (de.value === a.value) throw new Error("L'origen i el destí han de ser diferents");
            await api('/moviments/traspas', { method: 'POST', body: { product_id: p.id, de: ident(de.value), a: ident(a.value), grams: g } });
          } else {
            if (comentari.length < 3) throw new Error('Una sortida necessita un comentari (mínim 3 caràcters)');
            await api('/moviments/merma', { method: 'POST', body: { product_id: p.id, grams: g, nota: comentari, magatzem_id: ident(origenSortida.value) } });
          }
          toast('Moviment registrat');
          await pinta();
        });
      } }, ...camps, field(`Quantitat (${un})`, q),
      estat.tipus === 'entrada' ? field("Preu pagat per aquesta entrada (€, total; crea la despesa de proveïdors)", cost) : null,
      estat.tipus === 'entrada' ? h('p', { class: 'muted' }, 'Sense preu no es crea la despesa ni el cost real.') : null,
      estat.tipus === 'entrada' && act.preu_entrada_cent != null ? h('p', { class: 'muted' }, "Suggeriment: el preu d'entrada del producte multiplicat per la quantitat. Pots canviar-lo.") : null, nota, h('div', { class: 'actions' }, btn), out);
      const barra = h('div', { class: 'pestanyes', role: 'group', 'aria-label': 'Tipus de moviment' });
      [['entrada', 'Entrada'], ['moure', 'Moure'], ['sortida', 'Sortida']].forEach(([v, t]) => {
        const b = h('button', { type: 'button', 'aria-pressed': String(v === estat.tipus) }, t);
        b.addEventListener('click', () => { estat.tipus = v; pinta(); });
        barra.append(b);
      });
      arrel.replaceChildren(
        h('div', { class: 'row' }, kpi('Magatzem', act.magatzem_g + ' ' + un), kpi('Dispensari', act.dispensari_g + ' ' + un)),
        barra, form,
        h('h4', null, 'Darrers moviments'),
        taula([['Data'], ['Tipus'], ['Lloc'], ['Quantitat', true], ['Preu pagat', true], ['Qui'], ['Nota']], hist.map((m) => [horaCa(m.ts), m.tipus, m.lloc, m.grams, m.cost_cent ? eur(m.cost_cent) : '', m.usuari || '', m.nota || '']), 'Cap moviment.'));
    };
    pinta().catch((e) => arrel.replaceChildren(msg('err', e.message)));
    return arrel;
  });
  // en tancar la finestra, la llista darrere es refresca (els totals han canviat)
  const obs = new MutationObserver(() => { if (!document.querySelector('dialog.gran')) { obs.disconnect(); alTancar(); } });
  obs.observe(document.body, { childList: true });
}
