'use strict';
// Menú del club › Pantalles (TV i tauletes): llista curta, «Nova pantalla», enllaç copiable, QR i revocar.
// L'enllaç és secret: qui el tingui (dins la xarxa del club) veu la carta, però res més. Revocar-lo el talla a l'instant.

function copiaText(text) {
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
  return new Promise((resolve, reject) => {
    const t = h('textarea', { 'aria-label': 'Enllaç' });
    t.value = text;
    document.body.append(t);
    t.select();
    try { document.execCommand('copy') ? resolve() : reject(new Error('No s\'ha pogut copiar')); } catch (e) { reject(e); } finally { t.remove(); }
  });
}

function enllacComplet(url) { return location.origin + url; }

function modalQr(p) {
  const link = enllacComplet(p.url);
  obreModal('QR · ' + p.nom, () => {
    let qr;
    try { qr = QR.svg(link, 280); } catch (e) { qr = msg('err', e.message); }
    return h('div', { class: 'mc-qr' }, qr, h('p', { class: 'muted' }, 'Escaneja-ho amb la tauleta (ha d\'estar a la xarxa del club).'), h('code', { class: 'mc-link' }, link));
  });
}

async function vistaPantalles(getLlista, canvi) {
  const caixa = h('section', { class: 'mc-pantalles card' });
  const out = h('div');
  async function pinta() {
    const [{ pantalles }] = await Promise.all([api(`/locals/${S.local}/pantalles`)]);
    const menus = getLlista().menus;
    const files = pantalles.filter((p) => !p.revocada).map((p) => {
      const sel = h('select', { 'aria-label': 'Menú de ' + p.nom }, h('option', { value: '' }, '— cap menú —'), menus.map((m) => h('option', { value: m.id, selected: m.id === p.menu_id }, m.nom)));
      sel.addEventListener('change', () => guard(sel, out, async () => { await api(`/pantalles/${p.id}`, { method: 'PUT', body: { menu_id: sel.value ? Number(sel.value) : null } }); toast('Menú assignat'); }));
      const copia = h('button', { class: 'small', onclick: () => copiaText(enllacComplet(p.url)).then(() => toast('Enllaç copiat')).catch((e) => out.replaceChildren(msg('err', e.message))) }, 'Copiar enllaç');
      const revoca = h('button', { class: 'small danger', onclick: async () => {
        if (!await confirma(`Revocar «${p.nom}»? L'enllaç deixarà de funcionar a l'instant.`, { perill: true, boto: 'Revocar' })) return;
        await guard(revoca, out, async () => { await api(`/pantalles/${p.id}/revoca`, { method: 'POST' }); toast('Pantalla revocada'); await pinta(); });
      } }, 'Revocar');
      const estat = p.darrera_connexio ? 'Connectada ' + new Date(p.darrera_connexio).toLocaleString(loc()) : 'Encara no s\'ha connectat';
      return h('div', { class: 'mc-pan' }, h('div', { class: 'mc-pan-nom' }, h('strong', null, p.nom), h('span', { class: 'muted' }, (p.tipus === 'tv' ? 'TV' : 'Tauleta') + ' · ' + estat)),
        sel, h('div', { class: 'mc-pan-accions' }, copia, h('button', { class: 'small', onclick: () => modalQr(p) }, 'QR'), h('a', { class: 'button small', href: p.url, target: '_blank', rel: 'noopener' }, 'Obrir'), revoca));
    });
    caixa.replaceChildren(h('div', { class: 'mc-pan-cap' }, h('h3', null, 'Pantalles'), h('button', { class: 'primary', onclick: nova }, 'Nova pantalla')),
      files.length ? files : h('p', { class: 'muted' }, 'Encara no hi ha cap pantalla. Crea una, copia l\'enllaç i obre\'l a la TV o la tauleta.'), out);
  }
  function nova() {
    obreModal('Nova pantalla', (tanca) => {
      const o = h('div');
      const nom = h('input', { maxlength: 60, placeholder: 'TV del bar, Tauleta entrada…', 'aria-label': 'Nom de la pantalla', autocomplete: 'off' });
      const tipus = h('select', { 'aria-label': 'Tipus' }, h('option', { value: 'tv' }, 'TV (rota soles)'), h('option', { value: 'tauleta' }, 'Tauleta (es navega i es cerca)'));
      const menu = h('select', { 'aria-label': 'Menú' }, getLlista().menus.map((m) => h('option', { value: m.id }, m.nom)));
      const ok = h('button', { class: 'primary' }, 'Crear');
      ok.addEventListener('click', () => guard(ok, o, async () => {
        await api(`/locals/${S.local}/pantalles`, { method: 'POST', body: { nom: nom.value.trim(), tipus: tipus.value, menu_id: Number(menu.value) } });
        tanca(); toast('Pantalla creada'); await pinta();
      }));
      return h('div', null, field('Nom', nom), field('Tipus', tipus), field('Menú', menu), h('div', { class: 'actions' }, ok), o);
    });
  }
  await pinta();
  return caixa;
}
