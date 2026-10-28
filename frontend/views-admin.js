'use strict';
// Usuaris existents (llista editable) i el compte propi.

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
