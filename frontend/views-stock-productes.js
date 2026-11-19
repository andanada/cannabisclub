'use strict';
// Estoc › Productes: creació (tipus, categories per tipus, tara, unitat, opcions) i llista en dues pestanyes (genètiques / no genètiques).

const CATS_GENETIC = ['Weed', 'Hash', 'Ice', 'Rosin', 'Preroll'];
const CATS_NO_GENETIC = ['Parafernalia', 'Beguda', 'Menjar', 'Merch'];
const pesText = (g) => String(g).replace('.', ',');

// Finestra modal genèrica: `cos(tanca)` torna el contingut. Esc o la creu la tanquen.
function obreModal(titol, cos) {
  const dlg = h('dialog', { class: 'dialeg gran', 'aria-label': titol });
  const tanca = () => { if (dlg.open) dlg.close(); };
  const x = h('button', { type: 'button', class: 'small modal-x', 'aria-label': 'Tancar' }, '✕');
  x.addEventListener('click', tanca);
  dlg.append(h('div', { class: 'modal-cap' }, h('h3', null, titol), x), cos(tanca));
  dlg.addEventListener('close', () => dlg.remove());
  document.body.append(dlg);
  dlg.showModal();
  return tanca;
}

// Formulari de producte: nou (p = null) o edició. `fet()` s'executa en desar.
function productForm(p, fet) {
  const out = h('div');
  let genetic = p ? !!p.es_genetic : true;
  const nom = h('input', { value: p ? p.nom : '', maxlength: 120, autocomplete: 'off', 'aria-label': 'Nom' });
  const cat = h('select', { 'aria-label': 'Categoria' });
  const entrada = h('input', { inputmode: 'decimal', value: p && p.preu_entrada_cent != null ? preuText(p.preu_entrada_cent) : '', placeholder: '0,00', 'aria-label': "Preu d'entrada" });
  const preu = h('input', { inputmode: 'decimal', value: p ? preuText(p.preu_cent_per_g) : '', placeholder: '0,00', 'aria-label': 'Preu de dispensació' });
  const tara = h('input', { inputmode: 'decimal', value: p && Number(p.tara_g) ? pesText(p.tara_g) : '', placeholder: '0,0', 'aria-label': 'Tara' });
  const unitat = h('select', { 'aria-label': 'Unitat de venda' });
  const reg = h('input', { type: 'checkbox', checked: !!(p && p.regalable) });
  const sd = h('input', { type: 'checkbox', checked: !!(p && p.sense_descomptes) });
  const tipusBox = h('div', { class: 'pestanyes', role: 'group', 'aria-label': 'Tipus de producte' });
  const taraField = field('Tara / pes del pot (g)', tara);
  const taraAjuda = h('p', { class: 'muted' }, 'Pes del pot buit del dispensari. A l\'inventari de fi de dia, el programa el resta del pes de la bàscula.');
  const lbPreu = h('label', null, '');
  const repinta = () => {
    const cats = genetic ? CATS_GENETIC : CATS_NO_GENETIC;
    const actual = cat.value || (p ? p.categoria : '');
    cat.replaceChildren(...(actual && !cats.includes(actual) ? [h('option', { value: actual, selected: true }, actual)] : []), ...cats.map((c) => h('option', { value: c, selected: c === actual }, c)));
    const u = genetic ? (unitat.value || (p ? p.unitat : 'g')) : 'u';
    unitat.replaceChildren(...(genetic ? [['g', 'Grams'], ['u', 'Unitat']] : [['u', 'Unitat (els no genètics sempre per unitat)']]).map(([v, t]) => h('option', { value: v, selected: v === u }, t)));
    unitat.disabled = !genetic || !!p;   // una unitat ja en ús no es canvia (hi ha moviments)
    const grams = genetic && unitat.value === 'g';
    taraField.hidden = taraAjuda.hidden = !grams;
    [...tipusBox.children].forEach((b) => b.setAttribute('aria-pressed', String((b.dataset.g === '1') === genetic)));
  };
  [['1', 'Genètica'], ['0', 'No genètica']].forEach(([v, t]) => {
    const b = h('button', { type: 'button', 'data-g': v }, t);
    b.addEventListener('click', () => { if (p) return; genetic = v === '1'; cat.value = ''; unitat.value = ''; repinta(); });
    tipusBox.append(b);
  });
  unitat.addEventListener('change', repinta);
  repinta();
  const btn = h('button', { class: 'primary', type: 'submit' }, p ? 'Desar canvis' : 'Crear producte');
  return h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      if (!nom.value.trim()) throw new Error('Escriu el nom del producte');
      const base = { preu_cent_per_g: parseEur(preu.value), preu_entrada_cent: entrada.value.trim() ? parseEur(entrada.value) : null, regalable: reg.checked,
        sense_descomptes: sd.checked, tara_g: !taraField.hidden && tara.value.trim() ? parseGrams(tara.value) : (p ? 0 : null) };
      if (!p) {
        await api('/productes', { method: 'POST', body: { local_id: S.local, nom: nom.value.trim(), categoria: cat.value, es_genetic: genetic, unitat: unitat.value, estricte: true, ...base } });
        toast('Producte creat');
      } else {
        const body = { estricte: true };
        if (nom.value.trim() !== p.nom) body.nom = nom.value.trim();
        if (cat.value !== p.categoria) body.categoria = cat.value;
        if (base.preu_cent_per_g !== p.preu_cent_per_g) body.preu_cent_per_g = base.preu_cent_per_g;
        if (base.preu_entrada_cent != null && base.preu_entrada_cent !== p.preu_entrada_cent) body.preu_entrada_cent = base.preu_entrada_cent;
        if (base.regalable !== !!p.regalable) body.regalable = base.regalable;
        if (base.sense_descomptes !== !!p.sense_descomptes) body.sense_descomptes = base.sense_descomptes;
        if (base.tara_g !== null && base.tara_g !== Number(p.tara_g)) body.tara_g = base.tara_g;
        if (Object.keys(body).length === 1) throw new Error('No hi ha cap canvi');
        await api(`/productes/${p.id}`, { method: 'PATCH', body });
        toast('Producte actualitzat');
      }
      await fet();
    });
  } }, p ? null : h('h3', null, 'Nou producte'),
  field('Tipus', tipusBox), h('div', { class: 'row' }, field('Nom', nom), field('Categoria', cat)),
  h('div', { class: 'row' }, field("Preu d'entrada (€)", entrada), field('Preu de dispensació (€ per gram o unitat)', preu), field('Unitat de venda', unitat)),
  taraField, taraAjuda,
  h('div', { class: 'row' }, h('label', { class: 'check' }, reg, ' Es pot regalar'),
    h('label', { class: 'check' }, sd, ' No s\'apliquen descomptes: el preu no canvia mai per a ningú')),
  h('div', { class: 'actions' }, btn), out);
}

// Llista de productes d'un tipus, dividida per categories, amb filtre d'estat.
function llistaProductes(tots, genetic, recarrega) {
  const estat = { v: 'actius' };
  const box = h('div');
  const avis = h('div');   // errors i avisos (no la llista: guard() buida el contenidor que rep)
  const barra = h('div', { class: 'pestanyes', role: 'group', 'aria-label': 'Filtre' });
  const pinta = () => {
    const files = tots.filter((p) => !!p.es_genetic === genetic && (estat.v === 'tots' || (estat.v === 'actius') === p.actiu));
    const cats = [...new Set(files.map((p) => p.categoria || 'Sense categoria'))].sort();
    box.replaceChildren(...(cats.length ? cats.map((c) => h('div', { class: 'card' }, h('h3', null, c),
      taula([['Producte'], ["Entrada", true], ['Dispensació', true], ['Estat'], ['']], files.filter((p) => (p.categoria || 'Sense categoria') === c).map((p) => {
        const tog = h('button', { type: 'button', class: 'small ' + (p.actiu ? '' : 'primary') }, p.actiu ? 'Desactivar' : 'Activar');
        tog.addEventListener('click', () => guard(tog, avis, async () => { await api(`/productes/${p.id}`, { method: 'PATCH', body: { actiu: !p.actiu } }); toast(p.actiu ? 'Producte desactivat' : 'Producte activat'); await recarrega(); }));
        const ed = h('button', { type: 'button', class: 'small' }, 'Modificar');
        ed.addEventListener('click', () => obreModal(p.nom, (tanca) => productForm(p, async () => { tanca(); await recarrega(); })));
        const acc = [ed, tog];
        if (isManager()) {
          const del = h('button', { type: 'button', class: 'small danger' }, 'Esborrar');
          del.addEventListener('click', () => guard(del, avis, async () => {
            if (!await confirma(`Esborrar «${p.nom}»? No es pot desfer.`, { perill: true, boto: 'Esborrar' })) return;
            await api(`/productes/${p.id}`, { method: 'DELETE' }); toast('Producte esborrat'); await recarrega();
          }));
          acc.push(del);
        }
        return [h('span', null, p.nom, p.regalable ? ' 🎁' : '', p.sense_descomptes ? ' 🔒' : ''), p.preu_entrada_cent != null ? eur(p.preu_entrada_cent) : '—', eur(p.preu_cent_per_g) + '/' + unitTxt(p),
          h('span', { class: 'pill ' + (p.actiu ? 'ok' : 'warn') }, p.actiu ? 'actiu' : 'desactivat'), h('div', { class: 'actions' }, ...acc)];
      }), 'Cap producte.')))
      : [h('div', { class: 'card empty' }, 'Cap producte amb aquest filtre.')]));
  };
  [['actius', 'Actius'], ['desactivats', 'Desactivats'], ['tots', 'Tots']].forEach(([v, t]) => {
    const b = h('button', { type: 'button', 'aria-pressed': String(v === estat.v) }, t);
    b.addEventListener('click', () => { estat.v = v; [...barra.children].forEach((x) => x.setAttribute('aria-pressed', String(x === b))); pinta(); });
    barra.append(b);
  });
  pinta();
  return h('div', null, barra, avis, box);
}

async function productesSection() {
  const arrel = h('div');
  const pinta = async () => {
    const tots = await api(`/locals/${S.local}/productes`);
    const pestanya = { v: sessionStorage.getItem('ps') || 'g' };
    const cos = h('div');
    const mostra = () => cos.replaceChildren(llistaProductes(tots, pestanya.v === 'g', pinta));
    const barra = h('div', { class: 'pestanyes', role: 'tablist' });
    [['g', 'Genètiques'], ['n', 'No genètiques']].forEach(([v, t]) => {
      const b = h('button', { type: 'button', role: 'tab', 'aria-pressed': String(v === pestanya.v) }, t);
      b.addEventListener('click', () => { pestanya.v = v; sessionStorage.setItem('ps', v); [...barra.children].forEach((x) => x.setAttribute('aria-pressed', String(x === b))); mostra(); });
      barra.append(b);
    });
    mostra();
    arrel.replaceChildren(productForm(null, pinta), h('h3', null, 'Productes'), barra, cos);
  };
  await pinta();
  return arrel;
}
