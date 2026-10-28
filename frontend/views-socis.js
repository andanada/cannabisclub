'use strict';
// Gestió de socis: foto, carnet (lector RFID/codi de barres), edició de dades i llistat.
// Es fa servir des de views-dispensar.js (fitxa del soci). Mai innerHTML: tot el text va com a node de text.

// Redueix la imatge (càmera o galeria) a un JPEG petit: el servidor només n'accepta fins a 250 KB.
async function photoToJpegBase64(file, max = 480, maxBytes = 240000) {
  if (!file.type.startsWith('image/')) throw new Error('El fitxer ha de ser una imatge');
  const bmp = await createImageBitmap(file);
  const k = Math.min(1, max / Math.max(bmp.width, bmp.height));
  const c = document.createElement('canvas');
  c.width = Math.max(1, Math.round(bmp.width * k));
  c.height = Math.max(1, Math.round(bmp.height * k));
  c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height);
  if (bmp.close) bmp.close();
  for (const q of [0.85, 0.7, 0.55, 0.4]) {
    const b64 = c.toDataURL('image/jpeg', q).split(',')[1];
    if (b64.length * 0.75 < maxBytes) return b64;
  }
  throw new Error('La foto és massa gran');
}

// Miniatura de la foto vigent (es descarrega només si el soci en té; cada consulta queda a l'auditoria).
function memberPhoto(m) {
  const img = h('img', { class: 'foto', alt: 'Foto de ' + m.nom, hidden: true });
  if (m.te_foto) {
    api(`/socis/${m.id}/foto`).then((f) => { img.src = `data:${f.mime};base64,${f.image_base64}`; img.hidden = false; }).catch(() => {});
  }
  return img;
}

function photoUploader(m, out, reload) {
  const file = h('input', { type: 'file', accept: 'image/*', capture: 'user', 'aria-label': 'Foto del soci' });
  const btn = h('button', { type: 'button' }, m.te_foto ? 'Canviar foto' : 'Afegir foto');
  btn.addEventListener('click', () => file.click());
  file.addEventListener('change', () => guard(btn, out, async () => {
    if (!file.files[0]) return;
    const image_base64 = await photoToJpegBase64(file.files[0]);
    await api(`/socis/${m.id}/foto`, { method: 'POST', body: { image_base64 } });
    toast('Foto desada');
    reload();
  }));
  file.hidden = true;
  return [btn, file];
}

// Carnet: el lector d'un carnet RFID o de barres «escriu» el codi i prem Intro, com un teclat.
function cardManager(m, out, reload) {
  const codi = h('input', { placeholder: 'Passa el carnet pel lector', autocomplete: 'off', autocapitalize: 'characters' });
  const assign = h('button', { class: 'primary', type: 'submit' }, m.te_carnet ? 'Canviar carnet' : 'Assignar carnet');
  const form = h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(assign, out, async () => {
      await api(`/socis/${m.id}/carnet`, { method: 'POST', body: { codi: codi.value.trim() } });
      codi.value = '';
      toast('Carnet assignat');
      reload();
    });
  } }, h('h3', null, 'Carnet'), field('Codi del carnet', codi), h('div', { class: 'actions' }, assign));
  if (m.te_carnet) {
    const del = h('button', { type: 'button', class: 'danger' }, 'Retirar carnet');
    del.addEventListener('click', () => guard(del, out, async () => {
      await api(`/socis/${m.id}/carnet`, { method: 'DELETE' });
      toast('Carnet retirat');
      reload();
    }));
    form.querySelector('.actions').append(del);
  }
  return form;
}

// Edició de dades. Només s'envia el que ha canviat; telèfon o correu buits els esborren.
function editForm(m, out, reload) {
  const f = { nom: h('input', { value: m.nom }), doc: h('input', { value: m.document, autocapitalize: 'characters' }),
    naix: h('input', { type: 'date', value: m.naixement }), tel: h('input', { inputmode: 'tel', value: m.telefon || '' }),
    mail: h('input', { type: 'email', value: m.email || '' }) };
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Desar els canvis');
  return h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      const body = {};
      if (f.nom.value.trim() !== m.nom) body.nom = f.nom.value.trim();
      if (f.doc.value.trim() !== m.document) body.document = f.doc.value.trim();
      if (f.naix.value !== m.naixement) body.naixement = f.naix.value;
      if (f.tel.value.trim() !== (m.telefon || '')) body.telefon = f.tel.value.trim() || null;
      if (f.mail.value.trim() !== (m.email || '')) body.email = f.mail.value.trim() || null;
      if (!Object.keys(body).length) throw new Error('No hi ha cap canvi');
      await api(`/socis/${m.id}`, { method: 'PATCH', body });
      toast('Dades actualitzades');
      reload();
    });
  } }, h('h3', null, 'Editar dades'),
  h('div', { class: 'row' }, field('Nom i cognoms', f.nom), field('Document', f.doc), field('Data de naixement', f.naix)),
  h('div', { class: 'row' }, field('Telèfon', f.tel), field('Correu', f.mail)),
  h('div', { class: 'actions' }, btn));
}

// Eines de la fitxa per als responsables: foto, carnet i edició (plegables per no ocupar la pantalla).
function memberTools(m, out, onChange) {
  const reload = async () => onChange(await api(`/socis/${m.id}`));
  const panel = h('div');
  const toggle = (label, build) => {
    const b = h('button', { type: 'button', 'aria-expanded': 'false' }, label);
    b.addEventListener('click', () => {
      const open = b.getAttribute('aria-expanded') === 'true';
      document.querySelectorAll('.tool-toggle').forEach((x) => x.setAttribute('aria-expanded', 'false'));
      panel.replaceChildren(...(open ? [] : [build()]));
      if (!open) b.setAttribute('aria-expanded', 'true');
    });
    b.classList.add('tool-toggle');
    return b;
  };
  return { bar: [...photoUploader(m, out, reload), toggle('Carnet', () => cardManager(m, out, reload)), toggle('Editar dades', () => editForm(m, out, reload))], panel };
}

// Llistat de socis del local amb filtre per nom i estat (només responsables).
function memberList(onOpen) {
  const q = h('input', { type: 'search', placeholder: 'Cerca per nom', autocomplete: 'off' });
  const estat = h('select', null, [['', 'Tots els estats'], ['actiu', 'Actius'], ['suspes', 'Suspesos'], ['baixa', 'De baixa']].map(([v, t]) => h('option', { value: v }, t)));
  const body = h('div', null, h('p', { class: 'muted' }, 'Prem «Carregar» per veure els socis.'));
  const out = h('div');
  const load = h('button', { class: 'primary', type: 'submit' }, 'Carregar');
  const form = h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(load, out, async () => {
      const params = new URLSearchParams();
      if (q.value.trim()) params.set('q', q.value.trim());
      if (estat.value) params.set('estat', estat.value);
      const rows = await api(`/locals/${S.local}/socis?${params}`);
      body.replaceChildren(rows.length ? h('table', null, h('tbody', null, rows.map((r) => {
        const open = h('button', { type: 'button' }, 'Obrir');
        open.addEventListener('click', () => guard(open, out, async () => onOpen(await api(`/socis/${r.id}`), out)));
        return h('tr', null, h('td', null, r.nom), h('td', null, h('span', { class: 'pill ' + (r.estat === 'actiu' ? 'ok' : 'bad') }, r.estat)),
          h('td', null, quotaPill(r.quota)), h('td', null, open));
      }))) : h('p', { class: 'muted' }, 'Cap soci amb aquest filtre.'),
      h('p', { class: 'muted' }, rows.length + ' socis'));
    });
  } }, h('h3', null, 'Filtrar la llista'), h('div', { class: 'row' }, field('Nom', q), field('Estat', estat)), h('div', { class: 'actions' }, load), out, body);
  return form;
}
