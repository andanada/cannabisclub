'use strict';
// Usuaris existents (llista editable) i el compte propi.

const ROL_NOMS = { admin: 'Administrador', encarregat: 'Encarregat', dispensador: 'Treballador (dispensador)' };

// Usuaris existents: rol, locals, activar/desactivar, contrasenya nova i reinici del segon factor (TOTP).
async function usersCard() {
  const users = await api('/usuaris');
  const wrap = h('div', null, h('h2', null, 'Usuaris'));
  users.forEach((u) => wrap.append(userCard(u)));
  return wrap;
}

// Carnet imprimible d'un treballador: nom, codi de barres i el codi en text.
function printableStaffCard(u, codi) {
  return h('div', { class: 'print-area' }, h('div', { class: 'carnet-print' }, h('div'),
    h('div', null, h('div', { class: 'nom' }, u.username), h('div', null, 'Treballador'), h('div', null, 'Més que un Club')),
    barcodeSvg(codi), h('div', { class: 'codi-text' }, codi)));
}

function userCard(u) {
  const out = h('div');
  const reload = () => show('config');
  const rol = h('select', null, Object.keys(ROL_NOMS).map((r) => h('option', { value: r, selected: r === u.role }, ROL_NOMS[r])));
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
  // Carnet RFID d'entrada (carnet + PIN). Només carnets generats pel programa: codi llarg i imprevisible. No per a administradors.
  const pinNou = h('input', { type: 'password', inputmode: 'numeric', maxlength: 8, autocomplete: 'new-password', placeholder: '4 a 8 xifres', 'aria-label': 'PIN de ' + u.username });
  const generat = h('div');
  const genera = h('button', { type: 'button', class: 'primary' }, u.te_carnet ? 'Generar carnet nou' : 'Generar carnet');
  genera.addEventListener('click', () => guard(genera, out, async () => {
    if (u.te_carnet && !confirm(`Generar un carnet nou per a ${u.username}? L'actual deixarà de servir.`)) return;
    const r = await api(`/usuaris/${u.id}/carnet/generar`, { method: 'POST', body: { pin: pinNou.value } });
    pinNou.value = '';
    generat.replaceChildren(msg('ok', "Carnet generat. Imprimeix-lo o grava'l ara: el codi no es tornarà a mostrar. Dona el PIN al treballador en persona."),
      printableStaffCard(u, r.codi), cardOutputs(r.codi, null));
    toast('Carnet generat');
  }));
  const treuCarnet = u.te_carnet ? h('button', { type: 'button', class: 'danger' }, 'Retirar carnet') : null;
  if (treuCarnet) treuCarnet.addEventListener('click', () => guard(treuCarnet, out, async () => {
    await api(`/usuaris/${u.id}/carnet`, { method: 'DELETE' });
    toast('Carnet retirat');
    reload();
  }));
  const blocCarnet = u.role === 'admin'
    ? h('p', { class: 'muted' }, "Els administradors entren sempre amb contrasenya: no poden tenir carnet d'entrada.")
    : h('div', null,
      h('p', { class: 'muted' }, u.te_carnet ? "Aquest usuari ja té carnet. Per canviar-lo o posar-li un PIN nou, genera'n un de nou." : 'Entrarà amb el carnet més un PIN que només sap ell. Un carnet perdut no obre cap sessió sense el PIN.'),
      h('div', { class: 'row' }, field('PIN (4 a 8 xifres, no seqüències)', pinNou), h('div', { class: 'actions' }, genera, treuCarnet)), generat);
  return h('div', { class: 'card' },
    h('div', null, h('strong', null, u.username), ' ', h('span', { class: 'pill' }, ROL_NOMS[u.role] || u.role), ' ', h('span', { class: 'pill ' + (u.active ? 'ok' : 'warn') }, u.active ? 'actiu' : 'desactivat')),
    h('div', { class: 'row' }, field('Rol', rol), field('Contrasenya nova', pw)),
    h('h3', null, 'Locals amb accés'), h('div', null, checks),
    h('h3', null, "Carnet d'entrada"), blocCarnet,
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
    h('div', { class: 'actions' }, btn), out),
    S.me.te_carnet ? pinForm() : null);
};

// El treballador canvia el seu propi PIN de carnet (cal el PIN actual).
function pinForm() {
  const act = h('input', { type: 'password', inputmode: 'numeric', maxlength: 8, autocomplete: 'off' });
  const nou = h('input', { type: 'password', inputmode: 'numeric', maxlength: 8, autocomplete: 'new-password' });
  const out = h('div');
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Canviar el PIN');
  return h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      await api('/auth/carnet-pin', { method: 'POST', body: { actual: act.value, nova: nou.value } });
      act.value = nou.value = '';
      out.replaceChildren(msg('ok', 'PIN canviat.'));
    });
  } }, h('h3', null, 'PIN del carnet'), h('div', { class: 'row' }, field('PIN actual', act), field('PIN nou (4 a 8 xifres)', nou)), h('div', { class: 'actions' }, btn), out);
}
