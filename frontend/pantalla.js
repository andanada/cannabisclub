'use strict';
// Menú del club: pintat de la carta (TV i tauleta). El fa servir la pantalla pública (/pantalla/<token>, sense sessió) i la vista prèvia
// de l'editor del programa, així el que es veu a l'editor és exactament el que es veurà a la TV.
// Només llegeix dades de la carta (noms, categories, preus); cap dada de socis. Sense estils en línia: els valors dinàmics
// (colors, mides) van com a variables CSS posades amb style.setProperty (CSSOM, permès per la CSP).
(function (global) {
  const TEMES = {
    fosc: { nom: 'Fosc', fons_tipus: 'degradat', color_fons: '#0f1a14', color_fons2: '#1d3a2a', color_text: '#f5f7f4', color_accent: '#7bd88f' },
    negre: { nom: 'Negre', fons_tipus: 'color', color_fons: '#050505', color_fons2: '#111111', color_text: '#ffffff', color_accent: '#7bd88f' },
    clar: { nom: 'Clar', fons_tipus: 'color', color_fons: '#f6f3ec', color_fons2: '#ffffff', color_text: '#1b2420', color_accent: '#1b6b50' },
    crema: { nom: 'Crema', fons_tipus: 'degradat', color_fons: '#fbf6ea', color_fons2: '#e9efe1', color_text: '#22301f', color_accent: '#2f6b3a' },
    nit: { nom: 'Nit', fons_tipus: 'degradat', color_fons: '#101528', color_fons2: '#26204a', color_text: '#f2f3fb', color_accent: '#9aa7ff' },
  };
  const FONT = { 1: 1.5, 2: 1.8, 3: 2.1, 4: 2.5, 5: 3 };   // mida de lletra en unitats (1 unitat = 1% de l'ample de la pantalla)
  const ALT_CAP = 9, PAD = 3, ALT_CAT = 2.6, ALT_FILA = 1.9, SEP_CAT = 0.8;

  function preu(cent) {
    if (cent == null) return '';
    const e = Math.round(cent) / 100;
    return (Number.isInteger(e) ? String(e) : e.toFixed(2).replace('.', ',')) + ' €';
  }
  function preuTram(p, g) { return preu(Math.round(p.preu_cent * g)); }
  function ambGrams(cat) { return cat.productes.some((p) => p.unitat === 'g'); }

  // Reparteix la carta en pàgines de N columnes. Funció pura: [[columna: [{t:'cat'|'fila', ...}]]]
  function paginar(dades) {
    const d = dades.disseny, f = FONT[d.mida] || FONT[3], v = d.orientacio === 'v';
    const alt = (v ? 100 * 16 / 9 : 100 * 9 / 16) - ALT_CAP - 2 * PAD;
    const cap = alt / f, n = Math.max(1, d.columnes);
    const reparteix = (limit) => {
      const cols = [];
      let col = [], usat = 0;
      const nova = () => { if (col.length) cols.push(col); col = []; usat = 0; };
      for (const c of dades.categories) {
        const grams = ambGrams(c);
        let primera = true, ambCap = false;
        for (const p of c.productes) {
          const cal = (ambCap ? 0 : ALT_CAT + (col.length ? SEP_CAT : 0)) + ALT_FILA;
          if (col.length && usat + cal > limit) { nova(); ambCap = false; }
          if (!ambCap) {
            usat += ALT_CAT + (col.length ? SEP_CAT : 0);
            col.push({ t: 'cat', nom: c.nom, grams, cont: !primera });
            ambCap = true;
          }
          col.push({ t: 'fila', p });
          usat += ALT_FILA;
          primera = false;
        }
      }
      nova();
      return cols;
    };
    let cols = reparteix(cap);
    if (cols.length <= n) {   // cap en una sola pàgina: es reparteix a parts iguals entre les columnes en lloc d'omplir-ne només les primeres
      for (let l = ALT_CAT + ALT_FILA; l < cap; l += 0.5) { const c = reparteix(l); if (c.length <= n) { cols = c; break; } }
    }
    const pagines = [];
    for (let i = 0; i < cols.length; i += n) pagines.push(cols.slice(i, i + n));
    return pagines;
  }

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function vars(e, o) { for (const k of Object.keys(o)) e.style.setProperty(k, String(o[k])); }

  function aplicaDisseny(arrel, dades) {
    const d = dades.disseny, im = dades.imatges || {};
    const fons = d.fons_tipus === 'color' ? d.color_fons : `linear-gradient(135deg, ${d.color_fons}, ${d.color_fons2})`;
    vars(arrel, { '--pt-fons': d.fons_tipus === 'imatge' && im.fons ? d.color_fons : fons, '--pt-text': d.color_text, '--pt-accent': d.color_accent,
      '--pt-f': FONT[d.mida] || FONT[3], '--pt-cols': d.columnes, '--pt-cap': ALT_CAP, '--pt-pad': PAD, '--pt-cat': ALT_CAT, '--pt-fila': ALT_FILA, '--pt-sep': SEP_CAT });
    arrel.classList.toggle('pt-v', d.orientacio === 'v');
    arrel.classList.toggle('pt-clar', luminancia(d.color_fons) > 0.55);
  }
  function luminancia(hex) {
    const n = parseInt(String(hex).slice(1), 16) || 0;
    return (0.2126 * ((n >> 16) & 255) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255)) / 255;
  }

  function capcalera(dades, mode) {
    const d = dades.disseny, im = dades.imatges || {};
    const cap = el('header', 'pt-cap');
    if (d.logo !== 'cap') {
      const logo = el('img', 'pt-logo');
      logo.alt = '';
      logo.src = d.logo === 'propi' && im.logo ? im.logo : '/logo.png';
      cap.append(logo);
    }
    const t = el('div', 'pt-titol', d.titol || (dades.menu && dades.menu.nom) || '');
    cap.append(t);
    return cap;
  }

  function fila(p, d, grams) {
    const r = el('div', 'pt-fila' + (p.disponible ? '' : ' pt-esgotat'));
    r.append(el('span', 'pt-nom', p.nom));
    const preus = el('span', 'pt-preus');
    if (!p.disponible) preus.append(el('span', 'pt-tag', 'Esgotat'));
    else if (p.preu_cent != null) {
      if (p.unitat === 'g') d.trams.forEach((g) => preus.append(el('span', 'pt-preu', preuTram(p, g))));
      else {
        if (grams) for (let i = 1; i < d.trams.length; i++) preus.append(el('span', 'pt-preu pt-buit', ''));
        preus.append(el('span', 'pt-preu', preu(p.preu_cent)));
      }
    }
    r.append(preus);
    return r;
  }
  function titolCat(c, d) {
    const h = el('div', 'pt-cat');
    h.append(el('span', 'pt-cat-nom', c.nom + (c.cont ? ' …' : '')));
    if (c.grams && d.mostrar_preus) {
      const tr = el('span', 'pt-preus pt-trams');
      d.trams.forEach((g) => tr.append(el('span', 'pt-preu', g + ' g')));
      h.append(tr);
    }
    return h;
  }

  function pintaPagina(pagina, dades) {
    const d = dades.disseny;
    const cont = el('div', 'pt-cols');
    for (const col of pagina) {
      const c = el('div', 'pt-col');
      for (const x of col) c.append(x.t === 'cat' ? titolCat(x, d) : fila(x.p, d, col.some((y) => y.t === 'cat' && y.grams)));
      cont.append(c);
    }
    return cont;
  }

  // TV: pàgines que roten soles. Torna un objecte amb aturar() i actualitza(dades).
  function pintaTv(arrel, dades) {
    arrel.replaceChildren();
    arrel.classList.add('pt-tv');
    aplicaDisseny(arrel, dades);
    if ((dades.imatges || {}).fons && dades.disseny.fons_tipus === 'imatge') {
      const fons = el('img', 'pt-fons-img'); fons.alt = ''; fons.src = dades.imatges.fons; arrel.append(fons, el('div', 'pt-vel'));
    }
    arrel.append(capcalera(dades, 'tv'));
    const cos = el('main', 'pt-cos'), punts = el('div', 'pt-punts');
    arrel.append(cos, punts);
    const pagines = paginar(dades);
    let i = 0, temps = null;
    const mostra = () => {
      cos.classList.remove('pt-entra');
      cos.replaceChildren(pagines.length ? pintaPagina(pagines[i], dades) : el('div', 'pt-buida', 'Ara mateix no hi ha productes disponibles'));
      void cos.offsetWidth;
      cos.classList.add('pt-entra');
      punts.replaceChildren(...(pagines.length > 1 ? pagines.map((_, k) => el('span', 'pt-punt' + (k === i ? ' on' : ''))) : []));
    };
    mostra();
    if (pagines.length > 1) temps = setInterval(() => { i = (i + 1) % pagines.length; mostra(); }, dades.disseny.rotacio * 1000);
    return { aturar() { if (temps) clearInterval(temps); } };
  }

  // Tauleta: categories a dalt (pestanyes) i cerca; es desplaça.
  function pintaTauleta(arrel, dades) {
    arrel.replaceChildren();
    arrel.classList.add('pt-tauleta');
    aplicaDisseny(arrel, dades);
    arrel.classList.remove('pt-v');
    if ((dades.imatges || {}).fons && dades.disseny.fons_tipus === 'imatge') {
      const fons = el('img', 'pt-fons-img'); fons.alt = ''; fons.src = dades.imatges.fons; arrel.append(fons, el('div', 'pt-vel'));
    }
    const d = dades.disseny;
    const cap = capcalera(dades, 'tauleta');
    const cerca = el('input', 'pt-cerca');
    cerca.type = 'search'; cerca.placeholder = 'Cerca…'; cerca.setAttribute('aria-label', 'Cerca'); cerca.autocomplete = 'off';
    cap.append(cerca);
    const tabs = el('nav', 'pt-tabs'), llista = el('main', 'pt-llista');
    arrel.append(cap, tabs, llista);
    let triada = '';
    const pinta = () => {
      const q = cerca.value.trim().toLowerCase();
      tabs.replaceChildren(...[['', 'Tot'], ...dades.categories.map((c) => [c.nom, c.nom])].map(([k, t]) => {
        const b = el('button', 'pt-tab' + (triada === k ? ' on' : ''), t);
        b.type = 'button';
        b.addEventListener('click', () => { triada = k; pinta(); });
        return b;
      }));
      const blocs = [];
      for (const c of dades.categories) {
        if (triada && c.nom !== triada) continue;
        const ps = c.productes.filter((p) => !q || p.nom.toLowerCase().includes(q));
        if (!ps.length) continue;
        const b = el('section', 'pt-bloc');
        b.append(titolCat({ ...c, grams: ambGrams(c) }, d), ...ps.map((p) => fila(p, d, ambGrams(c))));
        blocs.push(b);
      }
      llista.replaceChildren(...(blocs.length ? blocs : [el('div', 'pt-buida', 'Res no coincideix')]));
    };
    pinta();
    return { aturar() {} };
  }

  // Ajusta la mida del llenç 16:9 (o 9:16) al contenidor i fixa la unitat (--pt-u = 1% de l'ample).
  function ajusta(arrel, contenidor, vertical) {
    const calcula = () => {
      const w = contenidor.clientWidth, hh = contenidor.clientHeight || w * 9 / 16;
      const r = vertical ? 9 / 16 : 16 / 9;
      const ample = Math.min(w, hh * r);
      arrel.style.width = ample + 'px';
      arrel.style.height = ample / r + 'px';
      arrel.style.setProperty('--pt-u', ample / 100 + 'px');
    };
    calcula();
    if (typeof ResizeObserver !== 'undefined') { const ro = new ResizeObserver(calcula); ro.observe(contenidor); return () => ro.disconnect(); }
    window.addEventListener('resize', calcula);
    return () => window.removeEventListener('resize', calcula);
  }

  // ---------- pantalla pública ----------
  function arrenca() {
    const arrel = document.getElementById('pt-arrel');
    const token = location.pathname.split('/')[2];
    let vista = null, ultim = '', parar = null, ro = null;
    const avis = el('div', 'pt-avis'); avis.hidden = true;
    document.body.append(avis);
    const mostraMissatge = (t) => { if (vista) { vista.aturar(); vista = null; } arrel.className = 'pt-arrel'; arrel.replaceChildren(el('div', 'pt-buida pt-gran', t)); ultim = ''; };
    async function refresca() {
      try {
        const r = await fetch(`/pantalla/${encodeURIComponent(token)}/dades`, { cache: 'no-cache' });
        if (r.status === 404) { mostraMissatge('Aquesta pantalla no està activa'); return 60000; }
        if (!r.ok) throw new Error('http');
        const text = await r.text();
        avis.hidden = true;
        if (text !== ultim) {
          ultim = text;
          const dades = JSON.parse(text);
          if (vista) vista.aturar();
          if (ro) ro();
          arrel.className = 'pt-arrel';
          if (!dades.menu) { mostraMissatge('Aquesta pantalla encara no té cap menú assignat'); ultim = text; return 30000; }
          const tauleta = dades.pantalla.tipus === 'tauleta';
          document.title = dades.menu.nom;
          if (tauleta) { arrel.style.removeProperty('width'); arrel.style.removeProperty('height'); vista = pintaTauleta(arrel, dades); }
          else { vista = pintaTv(arrel, dades); ro = ajusta(arrel, document.body, dades.disseny.orientacio === 'v'); }
        }
      } catch (_) { avis.textContent = 'Sense connexió: es mostra l’última carta'; avis.hidden = false; }
      return 30000;
    }
    const cicle = async () => { const espera = await refresca(); setTimeout(cicle, espera); };
    cicle();
    document.addEventListener('dblclick', () => { if (document.fullscreenElement) document.exitFullscreen(); else if (document.documentElement.requestFullscreen) document.documentElement.requestFullscreen(); });
    if (navigator.wakeLock) navigator.wakeLock.request('screen').catch(() => {});
    parar = null; void parar;
  }

  const Pantalla = { TEMES, FONT, preu, preuTram, paginar, pintaTv, pintaTauleta, ajusta };
  global.Pantalla = Pantalla;
  if (typeof module !== 'undefined' && module.exports) module.exports = Pantalla;
  if (typeof document !== 'undefined' && document.body && document.body.dataset && document.body.dataset.pantalla === '1') arrenca();
})(typeof window !== 'undefined' ? window : globalThis);
