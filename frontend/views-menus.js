'use strict';
// Menú del club: vista prèvia gran en directe + dos panells («Categories» i «Disseny») + publicar. Les pantalles són a views-menus-pantalles.js.
// La carta surt de l'estoc (no es munta a mà); aquí només es tria què es mostra i com es veu. Desat automàtic a l'esborrany; «Publicar» el fa visible.

const MENUS_TEMES = () => (window.Pantalla ? window.Pantalla.TEMES : {});

function mcSwitch(text, on, canvi) {
  const c = h('input', { type: 'checkbox', checked: !!on });
  c.addEventListener('change', () => canvi(c.checked));
  return h('label', { class: 'mc-switch' }, c, h('span', { class: 'mc-switch-pista' }), h('span', null, text));
}

function mcSegments(opcions, actual, canvi) {
  const caixa = h('div', { class: 'mc-segs', role: 'group' });
  const pinta = (v) => [...caixa.children].forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.v === String(v))));
  opcions.forEach(([v, t]) => {
    const b = h('button', { 'data-v': String(v) }, t);
    b.addEventListener('click', () => { pinta(v); canvi(v); });
    caixa.append(b);
  });
  pinta(actual);
  return caixa;
}

// Redimensiona una imatge triada (canvas) perquè càpiga al límit del servidor; torna una data URL JPEG.
function mcImatge(fitxer, ampleMax) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(fitxer), img = new Image();
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('No es pot llegir la imatge')); };
    img.onload = () => {
      URL.revokeObjectURL(url);
      const k = Math.min(1, ampleMax / img.width), cv = document.createElement('canvas');
      cv.width = Math.round(img.width * k); cv.height = Math.round(img.height * k);
      const g = cv.getContext('2d');
      g.drawImage(img, 0, 0, cv.width, cv.height);
      for (let q = 0.85; q > 0.2; q -= 0.15) {
        const d = cv.toDataURL(ampleMax <= 600 ? 'image/png' : 'image/jpeg', q);
        if (d.length < 650000) return resolve(d);
      }
      reject(new Error('La imatge és massa gran'));
    };
    img.src = url;
  });
}

VIEWS.menus = async () => {
  if (!te('menus')) return msg('err', 'No tens permís per gestionar el menú del club');
  const llista = await api(`/locals/${S.local}/menus`);
  const guardat = Number(sessionStorage.getItem('menu:sel'));
  let menuId = (llista.menus.find((m) => m.id === guardat) || llista.menus.find((m) => m.tipus === 'dispensari') || llista.menus[0]).id;
  const arrel = h('div', { class: 'mc' });
  let E = null, panell = '', temps = null, parar = null;
  const estat = h('span', { class: 'mc-estat' }, '');
  const prev = h('div', { class: 'pt-prev' });
  const lat = h('aside', { class: 'mc-lat card' });
  const out = h('div');

  async function carrega() {
    E = await api(`/menus/${menuId}/editor`);
    pinta();
  }
  function pintaPrev() {
    if (parar) parar();
    if (E.vista && E.vista.menu) {
      prev.classList.toggle('v', E.disseny.orientacio === 'v');
      prev.replaceChildren();
      const arr = h('div', { class: 'pt-arrel' });
      prev.append(arr);
      const v = window.Pantalla.pintaTv(arr, E.vista);
      const ro = window.Pantalla.ajusta(arr, prev, E.disseny.orientacio === 'v');
      parar = () => { v.aturar(); ro(); };
    }
  }
  // Canvi al disseny: es veu a l'instant (colors, mida…) i es desa sol al cap d'un moment.
  function canvia(parcial, { servidor = false, imatges = {} } = {}) {
    E.disseny = { ...E.disseny, ...parcial };
    E.vista = { ...E.vista, disseny: { ...E.vista.disseny, ...Object.fromEntries(Object.entries(parcial).filter(([k]) => k in E.vista.disseny)) } };
    if (imatges.logo !== undefined) { E.logo = imatges.logo; E.vista.imatges = { ...E.vista.imatges, logo: imatges.logo || undefined }; }
    if (imatges.fons !== undefined) { E.fons = imatges.fons; E.vista.imatges = { ...E.vista.imatges, fons: imatges.fons || undefined }; }
    E.sense_publicar = true;
    estat.textContent = 'Desant…';
    if (!servidor) pintaPrev();
    clearTimeout(temps);
    temps = setTimeout(async () => {
      try {
        const cos = { disseny: parcial };
        if (imatges.logo !== undefined) { cos.logo = imatges.logo; cos.canvia_logo = true; }
        if (imatges.fons !== undefined) { cos.fons = imatges.fons; cos.canvia_fons = true; }
        await api(`/menus/${menuId}/esborrany`, { method: 'PUT', body: cos });
        if (servidor) { const n = await api(`/menus/${menuId}/editor`); E = { ...n, disseny: n.disseny }; pintaPrev(); }
        estat.textContent = 'Desat';
        pintaCap();
      } catch (e) { estat.textContent = ''; out.replaceChildren(msg('err', e.message)); }
    }, 500);
    pintaCap();
  }
  window.mcCanvia = canvia;   // (les funcions dels panells el fan servir)
  window.mcRepinta = () => pintaPanell();

  const cap = h('div', { class: 'mc-cap' });
  function pintaCap() {
    const pub = h('button', { class: 'primary', disabled: !E.sense_publicar }, 'Publicar');
    pub.addEventListener('click', () => guard(pub, out, async () => {
      await new Promise((r) => setTimeout(r, 650));   // deixa acabar el desat automàtic
      await api(`/menus/${menuId}/publica`, { method: 'POST' });
      toast('Menú publicat: les pantalles l\'actualitzen soles');
      await carrega();
    }));
    const descarta = E.sense_publicar ? h('button', { class: 'small', onclick: async () => {
      if (!await confirma('Es perdran els canvis que no has publicat.', { perill: true, boto: 'Descartar' })) return;
      await api(`/menus/${menuId}/descarta`, { method: 'POST' });
      await carrega();
    } }, 'Descartar canvis') : null;
    const tabs = h('div', { class: 'mc-menus', role: 'tablist' }, llista.menus.map((m) => {
      const b = h('button', { role: 'tab', 'aria-selected': String(m.id === menuId), onclick: () => { menuId = m.id; sessionStorage.setItem('menu:sel', menuId); panell = ''; carrega(); } }, m.nom);
      return b;
    }), h('button', { class: 'mc-mes', 'aria-label': 'Opcions dels menús', title: 'Opcions dels menús', onclick: () => opcionsMenus() }, '⋯'));
    cap.replaceChildren(tabs, h('div', { class: 'mc-accions' }, estat, E.sense_publicar ? h('span', { class: 'mc-pendent' }, 'Canvis sense publicar') : h('span', { class: 'mc-ok' }, 'Publicat'), descarta, pub));
  }

  function pintaPanell() {
    if (!panell) { lat.hidden = true; arrel.classList.remove('amb-panell'); return; }
    lat.hidden = false; arrel.classList.add('amb-panell');
    lat.replaceChildren(panell === 'cat' ? panellCategories(E) : panellDisseny(E));
  }
  function pinta() {
    pintaCap();
    const bC = h('button', { class: panell === 'cat' ? 'on' : '', onclick: () => { panell = panell === 'cat' ? '' : 'cat'; pinta(); } }, 'Categories');
    const bD = h('button', { class: panell === 'dis' ? 'on' : '', onclick: () => { panell = panell === 'dis' ? '' : 'dis'; pinta(); } }, 'Disseny');
    barra.replaceChildren(bC, bD);
    pintaPrev();
    pintaPanell();
  }
  const barra = h('div', { class: 'mc-barra' });
  arrel.append(pageHead('Menú del club', 'La carta surt sola de l\'estoc: si una genètica s\'acaba desapareix, i quan torna, torna.'), cap, out, barra,
    h('div', { class: 'mc-cos' }, prev, lat), h('div', { id: 'mc-pantalles' }));
  lat.hidden = true;
  await carrega();
  arrel.querySelector('#mc-pantalles').replaceWith(await vistaPantalles(() => llista, () => carrega()));
  // L'estoc canvia: la vista prèvia es refresca cada 30 s mentre l'editor és a la pantalla.
  const refresc = setInterval(async () => {
    if (!arrel.isConnected) { clearInterval(refresc); if (parar) parar(); return; }
    if (document.hidden || panell === 'cat') return;
    try { const n = await api(`/menus/${menuId}/editor`); E.vista = n.vista; pintaPrev(); } catch (_) { /* es manté l'última */ }
  }, 30000);

  function opcionsMenus() {
    obreModal('Menús', (tanca) => {
      const o = h('div'), cosM = h('div', { class: 'mc-opcions' });
      const m = llista.menus.find((x) => x.id === menuId);
      const nom = h('input', { value: m.nom, maxlength: 60, 'aria-label': 'Nom del menú' });
      const refresca = async () => { tanca(); show('menus'); };
      cosM.append(
        field('Nom del menú', nom),
        mcSwitch('Actiu (si l\'apagues, les pantalles no el mostren)', m.actiu, async (v) => { await api(`/menus/${m.id}`, { method: 'PUT', body: { actiu: v } }).catch((e) => o.replaceChildren(msg('err', e.message))); }),
        h('div', { class: 'actions' },
          h('button', { class: 'primary', onclick: () => guard(o, o, async () => { await api(`/menus/${m.id}`, { method: 'PUT', body: { nom: nom.value.trim() } }); await refresca(); }) }, 'Canviar nom'),
          m.per_defecte ? null : h('button', { onclick: () => guard(o, o, async () => { await api(`/menus/${m.id}`, { method: 'PUT', body: { per_defecte: true } }); await refresca(); }) }, 'Marcar per defecte'),
          h('button', { onclick: () => guard(o, o, async () => { const r = await api(`/menus/${m.id}/duplica`, { method: 'POST' }); sessionStorage.setItem('menu:sel', r.id); await refresca(); }) }, 'Duplicar'),
          h('button', { class: 'danger', onclick: async () => { if (await confirma(`Esborrar el menú «${m.nom}»?`, { perill: true, boto: 'Esborrar' })) guard(o, o, async () => { await api(`/menus/${m.id}`, { method: 'DELETE' }); sessionStorage.removeItem('menu:sel'); await refresca(); }); } }, 'Esborrar')),
        h('hr'), h('h4', null, 'Nou menú (opcional)'));
      const nn = h('input', { placeholder: 'Nom (p. ex. Festes)', maxlength: 60, 'aria-label': 'Nom del nou menú' });
      const tp = h('select', { 'aria-label': 'Tipus' }, h('option', { value: 'dispensari' }, 'Dispensari'), h('option', { value: 'bar' }, 'Bar'));
      cosM.append(h('div', { class: 'row' }, field('Nom', nn), field('Tipus', tp)), h('div', { class: 'actions' },
        h('button', { onclick: () => guard(o, o, async () => { const r = await api(`/locals/${S.local}/menus`, { method: 'POST', body: { nom: nn.value.trim(), tipus: tp.value } }); sessionStorage.setItem('menu:sel', r.id); await refresca(); }) }, 'Crear')));
      return h('div', null, cosM, o);
    });
  }
  return arrel;
};

// ---------- panell «Categories» ----------
function panellCategories(E) {
  const d = E.disseny;
  const possibles = E.categories_possibles;
  let ordre = (d.categories || possibles.map((nom) => ({ nom, visible: true })));
  const vistes = new Set(ordre.map((c) => c.nom));
  ordre = [...ordre, ...possibles.filter((n) => !vistes.has(n)).map((nom) => ({ nom, visible: true }))];
  const caixa = h('div', { class: 'mc-cats' });
  const desa = (nou, extra = {}) => { ordre = nou; window.mcCanvia({ categories: ordre, ...extra }, { servidor: true }); };
  const ocults = new Set(d.ocults || []);
  ordre.forEach((c, i) => {
    const prods = E.productes.filter((p) => p.categoria === c.nom);
    const fila = h('div', { class: 'mc-cat' + (c.visible ? '' : ' apagada') },
      mcSwitch(c.nom, c.visible, (v) => desa(ordre.map((x) => (x.nom === c.nom ? { ...x, visible: v } : x)))),
      h('span', { class: 'muted' }, prods.length + (prods.length === 1 ? ' producte' : ' productes')),
      h('span', { class: 'mc-ordre' },
        h('button', { class: 'small', 'aria-label': 'Pujar', disabled: i === 0, onclick: () => { const n = [...ordre]; [n[i - 1], n[i]] = [n[i], n[i - 1]]; desa(n); } }, '▲'),
        h('button', { class: 'small', 'aria-label': 'Baixar', disabled: i === ordre.length - 1, onclick: () => { const n = [...ordre]; [n[i + 1], n[i]] = [n[i], n[i + 1]]; desa(n); } }, '▼')));
    const cos = h('div', { class: 'mc-cat-bloc' }, fila);
    if (prods.length) {
      cos.append(h('details', { class: 'mc-prods' }, h('summary', null, 'Productes'), prods.map((p) =>
        mcSwitch(p.nom + (p.disponible ? '' : ' (esgotat)'), !ocults.has(p.id), (v) => {
          v ? ocults.delete(p.id) : ocults.add(p.id);
          window.mcCanvia({ ocults: [...ocults] }, { servidor: true });
        }))));
    }
    caixa.append(cos);
  });
  return h('div', null, h('h3', null, 'Categories'), h('p', { class: 'muted' }, 'Tria què es mostra i en quin ordre. Els productes surten sols de l\'estoc.'),
    mcSwitch('Mostrar també els productes esgotats', d.mostrar_esgotats, (v) => window.mcCanvia({ mostrar_esgotats: v }, { servidor: true })), caixa);
}

// ---------- panell «Disseny» ----------
function panellDisseny(E) {
  const d = E.disseny, c = window.mcCanvia;
  const color = (text, clau) => { const i = h('input', { type: 'color', value: d[clau], 'aria-label': text }); i.addEventListener('input', () => c({ [clau]: i.value })); return h('label', { class: 'mc-color' }, i, h('span', null, text)); };
  const temes = h('div', { class: 'mc-temes' }, Object.entries(MENUS_TEMES()).map(([k, t]) => {
    const b = h('button', { class: 'mc-tema', 'aria-label': t.nom, title: t.nom, 'data-tema': k }, h('span', { class: 'mc-tema-mostra mt-' + k }), h('span', null, t.nom));
    b.addEventListener('click', () => { const { nom, ...cols } = t; c({ ...cols, tema: k }); window.mcRepinta(); document.querySelectorAll('.mc-tema').forEach((x) => x.setAttribute('aria-pressed', String(x === b))); });
    b.setAttribute('aria-pressed', String(d.tema === k));
    return b;
  }));
  const err = h('div');
  const triaImg = (clau, ample, text) => {
    const f = h('input', { type: 'file', accept: 'image/png,image/jpeg,image/webp', 'aria-label': text });
    f.addEventListener('change', async () => {
      if (!f.files[0]) return;
      try { c(clau === 'logo' ? { logo: 'propi' } : { fons_tipus: 'imatge' }, { imatges: { [clau]: await mcImatge(f.files[0], ample) } }); err.replaceChildren(); } catch (e) { err.replaceChildren(msg('err', e.message)); }
    });
    return f;
  };
  const tr = h('input', { value: (d.trams || []).join(', '), 'aria-label': 'Trams de pes', placeholder: '1, 5, 10' });
  tr.addEventListener('change', () => { const t = tr.value.split(/[ ,;]+/).map(Number).filter((n) => Number.isInteger(n) && n > 0 && n <= 1000); if (t.length) c({ trams: [...new Set(t)].sort((a, b) => a - b).slice(0, 4) }); });
  const ti = h('input', { value: d.titol || '', maxlength: 60, placeholder: E.menu.nom, 'aria-label': 'Títol' });
  ti.addEventListener('input', () => c({ titol: ti.value }));
  const rot = h('input', { type: 'number', min: 5, max: 120, value: d.rotacio, 'aria-label': 'Segons per pàgina' });
  rot.addEventListener('change', () => c({ rotacio: Math.max(5, Math.min(120, Number(rot.value) || 15)) }));
  const mida = h('input', { type: 'range', min: 1, max: 5, value: d.mida, 'aria-label': 'Mida de lletra' });
  mida.addEventListener('change', () => c({ mida: Number(mida.value) }, { servidor: true }));
  return h('div', null, h('h3', null, 'Disseny'),
    h('h4', null, 'Plantilla'), temes,
    h('h4', null, 'Fons'), mcSegments([['color', 'Color'], ['degradat', 'Degradat'], ['imatge', 'Imatge']], d.fons_tipus, (v) => c({ fons_tipus: v })),
    h('div', { class: 'mc-colors' }, color('Fons', 'color_fons'), color('Fons 2', 'color_fons2')),
    h('div', { class: 'mc-imatge' }, triaImg('fons', 1920, 'Imatge de fons'), E.fons ? h('button', { class: 'small', onclick: () => c({ fons_tipus: 'degradat' }, { imatges: { fons: null } }) }, 'Treure imatge') : null),
    h('h4', null, 'Logo'), mcSegments([['club', 'Del club'], ['propi', 'Propi'], ['cap', 'Cap']], d.logo, (v) => c({ logo: v })),
    h('div', { class: 'mc-imatge' }, triaImg('logo', 600, 'Logo propi')),
    h('h4', null, 'Colors'), h('div', { class: 'mc-colors' }, color('Text', 'color_text'), color('Accent', 'color_accent')),
    h('h4', null, 'Lletra i columnes'), field('Mida de lletra', mida),
    mcSegments([[1, '1 columna'], [2, '2'], [3, '3'], [4, '4']], d.columnes, (v) => c({ columnes: Number(v) }, { servidor: true })),
    mcSegments([['h', 'Horitzontal'], ['v', 'Vertical']], d.orientacio, (v) => c({ orientacio: v }, { servidor: true })),
    h('h4', null, 'Més'), field('Títol (opcional)', ti), field('Trams de pes (grams)', tr), field('Segons per pàgina (TV)', rot),
    mcSwitch('Mostrar preus', d.mostrar_preus, (v) => c({ mostrar_preus: v }, { servidor: true })), err);
}
