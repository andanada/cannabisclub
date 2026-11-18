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
      await api(`/socis/${m.id}/carnet`, { method: 'POST', body: { codi: normalizeScan(codi.value, await readerProfile()) } });
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

// Camps de perfil (gènere, adreça i tipus de membre), compartits per l'alta i l'edició.
// `valors()` torna un objecte amb tots els camps; `canvis(m)` només els que difereixen de la fitxa `m`.
function campsPerfil(m = {}) {
  const t = (v, a = {}) => h('input', { value: v || '', autocomplete: 'off', maxlength: 120, ...a });
  const f = {
    genere: h('select', null, [['', '—'], ['home', 'Home'], ['dona', 'Dona'], ['altre', 'Altre']].map(([v, x]) => h('option', { value: v, selected: v === (m.genere || '') }, x))),
    adreca: t(m.adreca), ciutat: t(m.ciutat), codi_postal: t(m.codi_postal, { maxlength: 12, inputmode: 'numeric' }),
    provincia: t(m.provincia), pais: t(m.pais),
    tipus: t(m.tipus || 'Ordinari', { maxlength: 40, list: 'tipus-membre' }),
  };
  const llista = h('datalist', { id: 'tipus-membre' }, ['Ordinari', 'Terapèutic', 'Convidat'].map((x) => h('option', { value: x })));
  const valors = () => Object.fromEntries(Object.entries(f).map(([k, i]) => [k, i.value.trim()]));
  const canvis = (orig) => Object.fromEntries(Object.entries(valors()).filter(([k, v]) => v !== (orig[k] || (k === 'tipus' ? 'Ordinari' : ''))));
  const node = h('div', null, llista,
    h('div', { class: 'row' }, field('Tipus de membre', f.tipus), field('Gènere', f.genere)),
    h('div', { class: 'row' }, field('Adreça', f.adreca), field('Ciutat', f.ciutat)),
    h('div', { class: 'row' }, field('Codi postal', f.codi_postal), field('Província', f.provincia), field('País', f.pais)));
  return { node, valors, canvis };
}

// Edició de dades. Només s'envia el que ha canviat; telèfon o correu buits els esborren.
function editForm(m, out, reload) {
  const f = { nom: h('input', { value: m.nom }), doc: h('input', { value: m.document, autocapitalize: 'characters' }),
    naix: h('input', { type: 'date', value: m.naixement }), tel: h('input', { inputmode: 'tel', value: m.telefon || '' }),
    mail: h('input', { type: 'email', value: m.email || '' }) };
  const perfil = campsPerfil(m);
  const dto = h('input', { type: 'number', min: 0, max: 100, step: 1, value: m.descompte_pct || 0, 'aria-label': 'Descompte permanent del soci (%)' });
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
      Object.assign(body, perfil.canvis(m));
      if (Number(dto.value) !== (m.descompte_pct || 0)) body.descompte_pct = Number(dto.value);
      if (!Object.keys(body).length) throw new Error('No hi ha cap canvi');
      await api(`/socis/${m.id}`, { method: 'PATCH', body });
      toast('Dades actualitzades');
      reload();
    });
  } }, h('h3', null, 'Editar dades'),
  h('div', { class: 'row' }, field('Nom i cognoms', f.nom), field('Document', f.doc), field('Data de naixement', f.naix)),
  h('div', { class: 'row' }, field('Telèfon', f.tel), field('Correu', f.mail)),
  perfil.node, field('Descompte permanent (%)', dto),
  h('div', { class: 'actions' }, btn));
}

// Incidències del soci: llista (oberta/tancada), alta i tancament. El text és lliure i es desa xifrat.
function memberIncidents(m) {
  const box = h('div', { class: 'card' });
  const out = h('div');
  const text = h('textarea', { rows: 3, maxlength: 1000, 'aria-label': "Descripció de la incidència", placeholder: 'Descriu la incidència' });
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Registrar incidència');
  const pinta = async () => {
    const l = await api(`/socis/${m.id}/incidencies`);
    box.replaceChildren(h('h3', null, 'Incidències'),
      h('form', { onsubmit: (e) => {
        e.preventDefault();
        guard(btn, out, async () => { await api(`/socis/${m.id}/incidencies`, { method: 'POST', body: { descripcio: text.value.trim() } }); text.value = ''; toast('Incidència registrada'); await pinta(); });
      } }, field('Nova incidència', text), h('div', { class: 'actions' }, btn)), out,
      taula([['Descripció'], ['Estat'], ['Creada'], ['Creada per'], ['']], l.map((i) => {
        const b = h('button', { type: 'button', class: 'small' }, 'Tancar');
        b.addEventListener('click', () => guard(b, out, async () => { await api(`/incidencies/${i.id}/tanca`, { method: 'POST' }); await pinta(); }));
        return [i.descripcio, h('span', { class: 'pill ' + (i.estat === 'oberta' ? 'warn' : 'ok') }, i.estat), new Date(i.creat).toLocaleString(loc()), i.creat_per, i.estat === 'oberta' ? b : ''];
      }), 'Cap incidència.'));
  };
  pinta().catch((e) => box.replaceChildren(msg('err', e.message)));
  return box;
}

// Fitxer (imatge o PDF) a base64 sense prefix. Les imatges es redueixen; un PDF es puja tal qual (màxim 400 KB al servidor).
async function fitxerBase64(file) {
  if (file.type.startsWith('image/')) return photoToJpegBase64(file, 1400, 380000);
  if (file.type !== 'application/pdf') throw new Error('El fitxer ha de ser una imatge o un PDF');
  if (file.size > 400000) throw new Error('El PDF és massa gran (màxim 400 KB)');
  const bytes = new Uint8Array(await file.arrayBuffer());
  let bin = '';
  for (let i = 0; i < bytes.length; i += 8192) bin += String.fromCharCode(...bytes.subarray(i, i + 8192));
  return btoa(bin);
}

function base64ABlob(b64, mime) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}

// Documents del soci (foto del document d'identitat davant i darrere, contracte signat, altres) i descàrrega del contracte.
function memberDocuments(m) {
  const box = h('div', { class: 'card' });
  const out = h('div');
  const pinta = async () => {
    const r = await api(`/socis/${m.id}/documents`);
    const tipus = h('select', { 'aria-label': 'Tipus de document' }, Object.entries(r.tipus).map(([k, v]) => h('option', { value: k }, v)));
    const file = h('input', { type: 'file', accept: 'image/*,application/pdf', capture: 'environment', 'aria-label': 'Fitxer' });
    const btn = h('button', { class: 'primary', type: 'submit' }, 'Pujar document');
    const contracte = h('button', { type: 'button' }, 'Descarregar contracte');
    contracte.addEventListener('click', () => guard(contracte, out, async () => {
      const resp = await api(`/socis/${m.id}/contracte?idioma=${LANG}`, { raw: true });
      if (!resp.ok) throw new Error("No s'ha pogut generar el contracte");
      descarrega(await resp.blob(), `contracte-${m.id}.html`);
    }));
    box.replaceChildren(h('h3', null, 'Documents'),
      h('form', { onsubmit: (e) => {
        e.preventDefault();
        guard(btn, out, async () => {
          if (!file.files[0]) throw new Error('Tria un fitxer');
          await api(`/socis/${m.id}/documents`, { method: 'POST', body: { tipus: tipus.value, nom: file.files[0].name.slice(0, 120), data_base64: await fitxerBase64(file.files[0]) } });
          toast('Document pujat');
          await pinta();
        });
      } }, h('div', { class: 'row' }, field('Tipus', tipus), field('Fitxer', file)), h('div', { class: 'actions' }, btn, contracte)), out,
      taula([['Tipus'], ['Nom'], ['Pujat'], ['']], r.documents.map((d) => {
        const veure = h('button', { type: 'button', class: 'small' }, 'Descarregar');
        veure.addEventListener('click', () => guard(veure, out, async () => {
          const x = await api(`/documents/${d.id}`);
          descarrega(base64ABlob(x.data_base64, x.mime), x.nom);
        }));
        const del = h('button', { type: 'button', class: 'small danger' }, 'Esborrar');
        del.addEventListener('click', () => guard(del, out, async () => { await api(`/documents/${d.id}`, { method: 'DELETE' }); toast('Document esborrat'); await pinta(); }));
        return [r.tipus[d.tipus] || d.tipus, d.nom, new Date(d.ts).toLocaleDateString(loc()), h('span', { class: 'actions fila-accions' }, veure, del)];
      }), 'Cap document.'));
  };
  pinta().catch((e) => box.replaceChildren(msg('err', e.message)));
  return box;
}

// Socis que aquest soci ha avalat.
function memberAvalats(m) {
  const box = h('div', { class: 'card' }, h('h3', null, 'Avalats'));
  api(`/socis/${m.id}/avalats`).then((l) => box.append(taula([['Soci'], ['Tipus'], ['Estat'], ['Alta']], l.map((x) => [x.nom, x.tipus, x.estat, new Date(x.creat).toLocaleDateString(loc())]), "No ha avalat cap soci."))).catch((e) => box.append(msg('err', e.message)));
  return box;
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
  // Un dispensador amb el privilegi de devolucions només hi veu l'historial de consum (des d'on es fa la devolució).
  if (!isManager()) return { bar: [toggle('Historial de consum', () => memberConsumption(m))], panel };
  return { bar: [...photoUploader(m, out, reload), toggle('Carnet', () => cardManager(m, out, reload)), toggle('Editar dades', () => editForm(m, out, reload)),
    ...(isManager() ? [toggle('Historial de consum', () => memberConsumption(m)), toggle('Incidències', () => memberIncidents(m)), toggle('Avalats', () => memberAvalats(m)), toggle('Documents', () => memberDocuments(m)), toggle('Línia de preu', () => { const box = h('div'); memberPriceLine(m, out, reload).then((f) => box.replaceChildren(f)).catch((e) => box.replaceChildren(msg('err', e.message))); return box; })] : [])], panel };
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
      // Es pinten de 100 en 100: amb milers de socis, una taula única fa el mòbil lent.
      const PAGINA = 100;
      const tbody = h('tbody');
      const mes = h('button', { type: 'button' }, 'Mostrar-ne més');
      let pintats = 0;
      const pintaMes = () => {
        tbody.append(...rows.slice(pintats, pintats + PAGINA).map((r) => {
          const open = h('button', { type: 'button' }, 'Obrir');
          open.addEventListener('click', () => guard(open, out, async () => onOpen(await api(`/socis/${r.id}`), out)));
          return h('tr', null, h('td', null, h('span', { class: 'muted' }, `[${r.codi}] `), r.nom), h('td', null, r.tipus), h('td', null, h('span', { class: 'pill ' + (r.estat === 'actiu' ? 'ok' : 'bad') }, r.estat)),
            h('td', null, quotaPill(r.quota)), h('td', null, open));
        }));
        pintats = Math.min(rows.length, pintats + PAGINA);
        mes.hidden = pintats >= rows.length;
      };
      pintaMes();
      mes.addEventListener('click', pintaMes);
      body.replaceChildren(...(rows.length ? [h('div', { class: 'table-wrap' }, h('table', null, tbody)), h('div', { class: 'actions' }, mes)] : [h('p', { class: 'muted' }, 'Cap soci amb aquest filtre.')]),
        h('p', { class: 'muted' }, rows.length + ' socis'));
    });
  } }, h('h3', null, 'Filtrar la llista'), h('div', { class: 'row' }, field('Nom', q), field('Estat', estat)), h('div', { class: 'actions' }, load), out, body);
  return form;
}
