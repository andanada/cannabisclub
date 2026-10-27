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
  return box;
};
