'use strict';
// Càmeres IP en directe. El servidor converteix el flux RTSP en fotogrames JPEG (~2 per segon) i aquí es demanen amb la capçalera
// d'autenticació (mai a la URL). El bucle s'atura sol quan la imatge ja no és a la pantalla o la pestanya no es veu.

// Mostra una càmera en un <img>: demana el fotograma, el posa i repeteix. `estat` rep els avisos d'error.
function directe(id, img, estat) {
  let anterior = null;
  const bucle = async () => {
    for (let i = 0; i < 30 && !img.isConnected; i++) await new Promise((r) => setTimeout(r, 100));   // la pantalla encara està afegint la imatge a la pàgina
    while (img.isConnected) {
      if (document.hidden) { await new Promise((r) => setTimeout(r, 1000)); continue; }
      try {
        const r = await fetch(`/cameres/${id}/frame`, { headers: { Authorization: 'Bearer ' + S.token }, cache: 'no-store' });
        if (r.status === 401) return;
        if (!r.ok) {
          const e = await r.json().catch(() => ({}));
          estat.textContent = e.detail || 'Sense imatge';
          estat.hidden = false;
          await new Promise((res) => setTimeout(res, 3000));
          continue;
        }
        const url = URL.createObjectURL(await r.blob());
        img.src = url;
        if (anterior) URL.revokeObjectURL(anterior);
        anterior = url;
        estat.hidden = true;
      } catch (_) {
        estat.textContent = 'Sense connexió';
        estat.hidden = false;
        await new Promise((res) => setTimeout(res, 3000));
        continue;
      }
      await new Promise((res) => setTimeout(res, 600));
    }
    if (anterior) URL.revokeObjectURL(anterior);
  };
  bucle();
}

function tileCamera(c, gran) {
  const img = h('img', { class: 'camera-img', alt: 'Càmera ' + c.nom });
  const estat = h('div', { class: 'camera-estat' }, 'Connectant…');
  const tile = h('div', { class: 'camera-tile' + (gran ? ' gran' : '') }, h('div', { class: 'camera-nom' }, c.nom), img, estat);
  directe(c.id, img, estat);
  return tile;
}

VIEWS.cameres = async () => {
  const r = await api(`/locals/${S.local}/cameres`);
  const actives = r.cameres.filter((c) => c.actiu);
  const graella = h('div', { class: 'cameres-grid' }, actives.map((c) => {
    const t = tileCamera(c, false);
    t.addEventListener('click', () => obreModal(c.nom, () => tileCamera(c, true)));   // clic: pantalla gran
    return t;
  }));
  return h('div', null, pageHead('Càmeres', 'Imatge en directe de les càmeres del club. Toca una càmera per veure-la més gran.'),
    !r.ffmpeg ? msg('err', "El servidor no té ffmpeg instal·lat (sudo apt install ffmpeg): sense ell no es pot veure la imatge.") : null,
    actives.length ? graella : h('div', { class: 'card empty' }, isManager() ? 'Encara no hi ha cap càmera: afegeix-ne a Configuració › Càmeres.' : 'Encara no hi ha cap càmera configurada.'),
    h('p', { class: 'muted' }, "Mirar les càmeres queda registrat a l'auditoria."));
};

// Administració (només administrador): afegir, provar, desactivar i esborrar càmeres.
VIEWS['cameres-admin'] = async () => {
  const llista = await api(`/locals/${S.local}/cameres`);
  const out = h('div');
  const nom = h('input', { maxlength: 60, placeholder: 'Entrada, Pati…', 'aria-label': 'Nom de la càmera', autocomplete: 'off' });
  const url = h('input', { placeholder: 'rtsp://usuari:contrasenya@192.168.1.20:554/stream1', 'aria-label': 'Adreça RTSP', autocomplete: 'off', spellcheck: 'false' });
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Afegir càmera');
  const nou = h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      await api(`/locals/${S.local}/cameres`, { method: 'POST', body: { nom: nom.value.trim(), url: url.value.trim() } });
      toast('Càmera afegida');
      show('cameres-admin');
    });
  } }, h('h3', null, 'Nova càmera'), h('div', { class: 'row' }, field('Nom', nom), field('Adreça RTSP (amb usuari i contrasenya de la càmera)', url)),
  h('p', { class: 'muted' }, "L'adreça es desa xifrada i no es torna a mostrar. Només s'accepten càmeres de la xarxa del club (192.168.x.x, 10.x.x.x, 172.16-31.x.x) o de Tailscale."),
  h('div', { class: 'actions' }, btn), out);
  const files = llista.cameres.map((c) => {
    const prova = h('button', { type: 'button', class: 'small' }, 'Provar');
    prova.addEventListener('click', () => guard(prova, out, async () => {
      const r = await api(`/cameres/${c.id}/prova`, { method: 'POST' });
      out.replaceChildren(r.ok ? msg('ok', `${c.nom}: arriba imatge (${Math.round(r.bytes / 1024)} KB).`) : msg('err', `${c.nom}: ${r.motiu}`));
    }));
    const act = h('button', { type: 'button', class: 'small' }, c.actiu ? 'Desactivar' : 'Activar');
    act.addEventListener('click', () => guard(act, out, async () => { await api(`/cameres/${c.id}`, { method: 'PUT', body: { actiu: !c.actiu } }); show('cameres-admin'); }));
    const nova = h('button', { type: 'button', class: 'small' }, 'Canviar adreça');
    nova.addEventListener('click', () => guard(nova, out, async () => {
      const u = await demana(`Nova adreça RTSP de «${c.nom}»`);
      if (!u) return;
      await api(`/cameres/${c.id}`, { method: 'PUT', body: { url: u.trim() } });
      toast('Adreça actualitzada');
    }));
    const del = h('button', { type: 'button', class: 'small danger' }, 'Esborrar');
    del.addEventListener('click', () => guard(del, out, async () => {
      if (!await confirma(`Esborrar la càmera «${c.nom}»?`, { perill: true, boto: 'Esborrar' })) return;
      await api(`/cameres/${c.id}`, { method: 'DELETE' });
      show('cameres-admin');
    }));
    return [c.nom, c.servidor, h('span', { class: 'pill ' + (c.actiu ? 'ok' : 'warn') }, c.actiu ? 'activa' : 'desactivada'), h('div', { class: 'actions' }, prova, nova, act, del)];
  });
  return h('div', null, pageHead('Càmeres', 'Càmeres IP (RTSP) del local. Necessiten ffmpeg al servidor i que aquest les vegi per la xarxa del club o Tailscale.'),
    !llista.ffmpeg ? msg('err', "El servidor no té ffmpeg instal·lat: instal·la'l amb «sudo apt install ffmpeg».") : null, nou,
    h('div', { class: 'card table-wrap' }, taula([['Nom'], ['Servidor'], ['Estat'], ['']], files, 'Encara no hi ha cap càmera.')));
};
