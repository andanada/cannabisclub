'use strict';
// Pantalla d'administració: locals, usuaris, límits i verificació de l'auditoria.

VIEWS.admin = async () => {
  const box = h('div', null, h('h2', null, 'Administració'));

  // Verificació de la cadena d'auditoria
  const outA = h('div');
  const bA = h('button', null, 'Verificar integritat de l\'auditoria');
  bA.addEventListener('click', () => guard(bA, outA, async () => {
    const r = await api('/auditoria/verificar');
    outA.replaceChildren(r.integra ? msg('ok', 'Cadena d\'auditoria íntegra') : msg('err', 'ALTERACIÓ detectada a l\'entrada ' + r.primera_alterada));
  }));
  box.append(h('div', { class: 'card' }, h('h3', null, 'Auditoria'), bA, outA));

  // Límits i tolerància del local actual
  const loc = S.me.locals.find((l) => l.id === S.local);
  const toG = (mg) => (mg == null ? '' : String(mg / 1000).replace('.', ','));
  const d = h('input', { inputmode: 'decimal', value: toG(loc.limit_diari_mg), placeholder: 'sense límit' });
  const m = h('input', { inputmode: 'decimal', value: toG(loc.limit_mensual_mg), placeholder: 'sense límit' });
  const t = h('input', { inputmode: 'decimal', value: toG(loc.tolerancia_bascula_mg), placeholder: 'sense control' });
  const outL = h('div');
  const bL = h('button', { class: 'primary', type: 'submit' }, 'Desar');
  const opt = (i) => (i.value.trim() ? parseGrams(i.value) : null);
  box.append(h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(bL, outL, async () => {
      await api(`/locals/${S.local}/limits`, { method: 'PUT', body: { limit_diari_g: opt(d), limit_mensual_g: opt(m), tolerancia_bascula_g: opt(t) } });
      S.me = await api('/me');
      outL.replaceChildren(msg('ok', 'Límits desats'));
    });
  } }, h('h3', null, 'Límits per soci · ' + loc.nom),
  h('div', { class: 'row' }, field('Límit diari (g)', d), field('Límit mensual (g)', m), field('Tolerància bàscula (g)', t)),
  h('div', { class: 'actions' }, bL), outL));

  // Quotes del local: import i durada per defecte, i si es bloqueja dispensar amb la quota caducada
  const qImp = h('input', { inputmode: 'decimal', value: loc.quota_cent ? (loc.quota_cent / 100).toFixed(2).replace('.', ',') : '', placeholder: 'sense import per defecte' });
  const qMesos = h('input', { type: 'number', min: 1, max: 24, value: loc.quota_mesos || 1 });
  const qObl = h('input', { type: 'checkbox', checked: !!loc.quota_obligatoria });
  const outQ = h('div');
  const bQ = h('button', { class: 'primary', type: 'submit' }, 'Desar');
  box.append(h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(bQ, outQ, async () => {
      await api(`/locals/${S.local}/config`, { method: 'PUT', body: { quota_cent: qImp.value.trim() ? parseEur(qImp.value) : 0, quota_mesos: Number(qMesos.value), quota_obligatoria: qObl.checked } });
      S.me = await api('/me');
      outQ.replaceChildren(msg('ok', 'Quotes desades'));
    });
  } }, h('h3', null, 'Quotes · ' + loc.nom),
  h('div', { class: 'row' }, field('Import per defecte (€)', qImp), field('Mesos per defecte', qMesos)),
  h('label', null, qObl, ' Exigir la quota al dia per poder dispensar'),
  h('div', { class: 'actions' }, bQ), outQ));

  // Nou local
  const nom = h('input');
  const outN = h('div');
  const bN = h('button', { type: 'submit' }, 'Crear local');
  box.append(h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(bN, outN, async () => {
      await api('/locals', { method: 'POST', body: { nom: nom.value.trim() } });
      S.me = await api('/me');
      nom.value = '';
      renderShell(); show('admin');
    });
  } }, h('h3', null, 'Nou local'), field('Nom', nom), h('div', { class: 'actions' }, bN), outN));

  // Nou usuari
  const un = h('input', { autocomplete: 'off' });
  const pw = h('input', { type: 'password', autocomplete: 'new-password' });
  const rol = h('select', null, ['dispensador', 'encarregat', 'admin'].map((r) => h('option', { value: r }, r)));
  const checks = S.me.locals.map((l) => h('label', null, h('input', { type: 'checkbox', value: l.id }), ' ', l.nom));
  const outU = h('div');
  const bU = h('button', { type: 'submit' }, 'Crear usuari');
  box.append(h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(bU, outU, async () => {
      const ids = checks.map((c) => c.querySelector('input')).filter((i) => i.checked).map((i) => Number(i.value));
      const r = await api('/usuaris', { method: 'POST', body: { username: un.value.trim(), password: pw.value, role: rol.value, local_ids: ids } });
      pw.value = '';
      outU.replaceChildren(msg('ok', 'Usuari creat. Dona-li aquest secret per a l\'app d\'autenticació; no es tornarà a mostrar:'),
        h('div', { class: 'secret' }, r.totp_secret));
    });
  } }, h('h3', null, 'Nou usuari'),
  h('div', { class: 'row' }, field('Nom d\'usuari', un), field('Contrasenya (mínim 12 caràcters)', pw), field('Rol', rol)),
  h('h3', null, 'Locals amb accés'), h('div', null, checks), h('div', { class: 'actions' }, bU), outU));
  box.append(await usersCard());
  box.append(scaleDiagnostics());
  return box;
};

// Usuaris existents: rol, locals, activar/desactivar, contrasenya nova i reinici del segon factor (TOTP).
async function usersCard() {
  const users = await api('/usuaris');
  const wrap = h('div', null, h('h2', null, 'Usuaris'));
  users.forEach((u) => wrap.append(userCard(u)));
  return wrap;
}

function userCard(u) {
  const out = h('div');
  const reload = () => show('admin');
  const rol = h('select', null, ['dispensador', 'encarregat', 'admin'].map((r) => h('option', { value: r, selected: r === u.role }, r)));
  const checks = S.me.locals.map((l) => h('label', null, h('input', { type: 'checkbox', value: l.id, checked: u.local_ids.includes(l.id) }), ' ', l.nom));
  const save = h('button', { class: 'primary', type: 'button' }, 'Desar rol i locals');
  save.addEventListener('click', () => guard(save, out, async () => {
    const local_ids = checks.map((c) => c.querySelector('input')).filter((i) => i.checked).map((i) => Number(i.value));
    await api(`/usuaris/${u.id}`, { method: 'PATCH', body: { role: rol.value, local_ids } });
    toast('Usuari actualitzat');
    reload();
  }));
  const toggle = h('button', { type: 'button', class: u.active ? 'danger' : '' }, u.active ? 'Desactivar' : 'Reactivar');
  toggle.addEventListener('click', () => guard(toggle, out, async () => {
    if (u.active && !confirm(`Desactivar ${u.username}? Se li tancaran les sessions obertes.`)) return;
    await api(`/usuaris/${u.id}`, { method: 'PATCH', body: { active: !u.active } });
    toast(u.active ? 'Usuari desactivat' : 'Usuari reactivat');
    reload();
  }));
  const pw = h('input', { type: 'password', autocomplete: 'new-password', placeholder: 'Contrasenya nova (mínim 12)' });
  const setPw = h('button', { type: 'button' }, 'Posar contrasenya');
  setPw.addEventListener('click', () => guard(setPw, out, async () => {
    await api(`/usuaris/${u.id}/contrasenya`, { method: 'POST', body: { password: pw.value } });
    pw.value = '';
    out.replaceChildren(msg('ok', 'Contrasenya canviada. Se li han tancat les sessions.'));
  }));
  const totp = h('button', { type: 'button' }, 'Reiniciar TOTP');
  totp.addEventListener('click', () => guard(totp, out, async () => {
    if (!confirm(`Reiniciar el segon factor de ${u.username}? El codi actual deixarà de servir.`)) return;
    const r = await api(`/usuaris/${u.id}/totp`, { method: 'POST' });
    out.replaceChildren(msg('ok', 'Nou secret per a l\'app d\'autenticació; no es tornarà a mostrar:'), h('div', { class: 'secret' }, r.totp_secret));
  }));
  return h('div', { class: 'card' },
    h('div', null, h('strong', null, u.username), ' ', h('span', { class: 'pill ' + (u.active ? 'ok' : 'warn') }, u.active ? 'actiu' : 'desactivat')),
    h('div', { class: 'row' }, field('Rol', rol), field('Contrasenya nova', pw)),
    h('h3', null, 'Locals amb accés'), h('div', null, checks),
    h('div', { class: 'actions' }, save, setPw, totp, toggle), out);
}

// Compte propi: canvi de contrasenya (disponible per a tots els rols).
VIEWS.compte = async () => {
  const act = h('input', { type: 'password', autocomplete: 'current-password' });
  const nova = h('input', { type: 'password', autocomplete: 'new-password' });
  const rep = h('input', { type: 'password', autocomplete: 'new-password' });
  const out = h('div');
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Canviar contrasenya');
  return h('div', null, h('h2', null, 'El meu compte'), h('p', { class: 'muted' }, S.me.username + ' · ' + S.me.role),
    h('form', { class: 'card', onsubmit: (e) => {
      e.preventDefault();
      guard(btn, out, async () => {
        if (nova.value !== rep.value) throw new Error('Les contrasenyes noves no coincideixen');
        await api('/auth/canvi-contrasenya', { method: 'POST', body: { actual: act.value, nova: nova.value } });
        act.value = nova.value = rep.value = '';
        out.replaceChildren(msg('ok', 'Contrasenya canviada. Les altres sessions s\'han tancat.'));
      });
    } }, h('h3', null, 'Canviar la contrasenya'),
    field('Contrasenya actual', act), field('Contrasenya nova (mínim 12 caràcters)', nova), field('Repeteix la contrasenya nova', rep),
    h('div', { class: 'actions' }, btn), out));
};

// Diagnòstic i perfil de la bàscula: serveix per adaptar-se a qualsevol model OHAUS veient què envia realment.
function scaleDiagnostics() {
  if (!Bascula.supported()) {
    return h('div', { class: 'card' }, h('h3', null, 'Bàscula'), h('p', { class: 'muted' }, 'Aquest navegador o connexió no admet ports sèrie (cal Chrome o Edge i HTTPS o localhost).'));
  }
  const p = loadProfile();
  const baud = h('select', null, [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200].map((b) => h('option', { value: b, selected: b === p.baudRate }, b + ' bauds')));
  const read = h('input', { value: p.read.join(',') });
  const tare = h('input', { value: p.tare });
  const zero = h('input', { value: p.zero });
  const log = h('pre', { class: 'secret', 'aria-live': 'off' }, 'Encara no s\'ha rebut res.');
  const out = h('div');
  const paint = () => {
    const lines = (BASCULA ? BASCULA.rawLog : []).slice(-25).map((e) => (e.dir === 'tx' ? '→ ' : '← ') + JSON.stringify(e.text));
    log.textContent = lines.length ? lines.join('\n') : 'Encara no s\'ha rebut res.';
  };
  const profile = () => ({ baudRate: Number(baud.value), read: read.value.split(',').map((x) => x.trim()).filter(Boolean), tare: tare.value.trim() || 'T', zero: zero.value.trim() || 'Z' });
  const save = h('button', { type: 'button' }, 'Desar perfil');
  save.addEventListener('click', () => { saveProfile(profile()); toast('Perfil desat'); });
  const connect = h('button', { class: 'primary', type: 'button' }, 'Connectar');
  connect.addEventListener('click', () => guard(connect, out, async () => {
    if (BASCULA && BASCULA.connected) await BASCULA.disconnect();
    BASCULA = new Bascula(Object.assign(profile(), { onRaw: paint }));
    await BASCULA.connect();
    out.replaceChildren(msg('ok', 'Connectada. Prem «Llegir pes» o escriu una ordre.'));
  }));
  const cmd = h('input', { placeholder: 'Ordre (p. ex. IP, P, T, Z)' });
  const send = h('button', { type: 'button' }, 'Enviar ordre');
  send.addEventListener('click', () => guard(send, out, async () => {
    if (!BASCULA || !BASCULA.connected) throw new Error('Connecta primer la bàscula');
    await BASCULA.send(cmd.value.trim());
    setTimeout(paint, 400);
  }));
  const weigh = h('button', { type: 'button' }, 'Llegir pes');
  weigh.addEventListener('click', () => guard(weigh, out, async () => {
    if (!BASCULA || !BASCULA.connected) throw new Error('Connecta primer la bàscula');
    const r = await BASCULA.readStable();
    paint();
    out.replaceChildren(msg('ok', 'Pes estable: ' + r.raw + ' (ordre que funciona: ' + BASCULA.workingCommand + ')'));
  }));
  return h('div', { class: 'card' }, h('h3', null, 'Bàscula (perfil i diagnòstic)'),
    h('p', { class: 'muted' }, 'Si el teu model d\'OHAUS no respon bé, connecta-la aquí, mira què envia i ajusta les ordres. El perfil es desa en aquest dispositiu.'),
    h('div', { class: 'row' }, field('Velocitat', baud), field('Ordres de lectura (per ordre de prova)', read), field('Tara', tare), field('Zero', zero)),
    h('div', { class: 'actions' }, connect, save), h('div', { class: 'row' }, field('Ordre manual', cmd)),
    h('div', { class: 'actions' }, send, weigh), out, h('h3', null, 'Comunicació en cru'), log);
}
