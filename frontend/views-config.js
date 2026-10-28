'use strict';
// Configuració (només administradors): cada tasca a la seva subpantalla.
// Locals i límits · Quotes · Usuaris · Bàscules · Tauletes de signatura · Carnets (RFID) · Seguretat.

const gToText = (mg) => (mg == null ? '' : String(mg / 1000).replace('.', ','));
const localActual = () => S.me.locals.find((l) => l.id === S.local);

function localSection() {
  const loc = localActual();
  const d = h('input', { inputmode: 'decimal', value: gToText(loc.limit_diari_mg), placeholder: 'sense límit' });
  const m = h('input', { inputmode: 'decimal', value: gToText(loc.limit_mensual_mg), placeholder: 'sense límit' });
  const t = h('input', { inputmode: 'decimal', value: gToText(loc.tolerancia_bascula_mg), placeholder: 'sense control' });
  const outL = h('div');
  const bL = h('button', { class: 'primary', type: 'submit' }, 'Desar límits');
  const opt = (i) => (i.value.trim() ? parseGrams(i.value) : null);
  const limits = h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(bL, outL, async () => {
      await api(`/locals/${S.local}/limits`, { method: 'PUT', body: { limit_diari_g: opt(d), limit_mensual_g: opt(m), tolerancia_bascula_g: opt(t) } });
      S.me = await api('/me');
      outL.replaceChildren(msg('ok', 'Límits desats'));
    });
  } }, h('h3', null, 'Límits per soci · ' + loc.nom),
  h('p', { class: 'muted' }, 'Màxim de grams que es pot dispensar a un soci, i diferència màxima permesa entre el pes de la bàscula i la quantitat dispensada.'),
  h('div', { class: 'row' }, field('Límit diari (g)', d), field('Límit mensual (g)', m), field('Tolerància de la bàscula (g)', t)),
  h('div', { class: 'actions' }, bL), outL);

  const nom = h('input');
  const outN = h('div');
  const bN = h('button', { type: 'submit' }, 'Crear local');
  const nou = h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(bN, outN, async () => {
      await api('/locals', { method: 'POST', body: { nom: nom.value.trim() } });
      S.me = await api('/me');
      nom.value = '';
      renderShell();
      show('config');
    });
  } }, h('h3', null, 'Nou local'), field('Nom', nom), h('div', { class: 'actions' }, bN), outN);
  return h('div', null, limits, nou);
}

function quotesSection() {
  const loc = localActual();
  const imp = h('input', { inputmode: 'decimal', value: loc.quota_cent ? preuText(loc.quota_cent) : '', placeholder: 'sense import per defecte' });
  const mesos = h('input', { type: 'number', min: 1, max: 24, value: loc.quota_mesos || 1 });
  const obl = h('input', { type: 'checkbox', checked: !!loc.quota_obligatoria });
  const out = h('div');
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Desar');
  return h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      await api(`/locals/${S.local}/config`, { method: 'PUT', body: { quota_cent: imp.value.trim() ? parseEur(imp.value) : 0, quota_mesos: Number(mesos.value), quota_obligatoria: obl.checked } });
      S.me = await api('/me');
      out.replaceChildren(msg('ok', 'Quotes desades'));
    });
  } }, h('h3', null, 'Quotes · ' + loc.nom),
  h('p', { class: 'muted' }, 'Import i durada que es proposen en cobrar una quota, i si cal tenir-la al dia per poder dispensar.'),
  h('div', { class: 'row' }, field('Import per defecte (€)', imp), field('Mesos per defecte', mesos)),
  h('label', null, obl, ' Exigir la quota al dia per poder dispensar'), h('div', { class: 'actions' }, btn), out);
}

async function usersSection() {
  const un = h('input', { autocomplete: 'off' });
  const pw = h('input', { type: 'password', autocomplete: 'new-password' });
  const rol = h('select', null, ['dispensador', 'encarregat', 'admin'].map((r) => h('option', { value: r }, r)));
  const checks = S.me.locals.map((l) => h('label', null, h('input', { type: 'checkbox', value: l.id }), ' ', l.nom));
  const outU = h('div');
  const bU = h('button', { class: 'primary', type: 'submit' }, 'Crear usuari');
  const nou = h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(bU, outU, async () => {
      const ids = checks.map((c) => c.querySelector('input')).filter((i) => i.checked).map((i) => Number(i.value));
      const r = await api('/usuaris', { method: 'POST', body: { username: un.value.trim(), password: pw.value, role: rol.value, local_ids: ids } });
      pw.value = '';
      outU.replaceChildren(msg('ok', "Usuari creat. Dona-li aquest secret per a l'app d'autenticació; no es tornarà a mostrar:"), h('div', { class: 'secret' }, r.totp_secret));
    });
  } }, h('h3', null, 'Nou usuari'),
  h('div', { class: 'row' }, field("Nom d'usuari", un), field('Contrasenya (mínim 12 caràcters)', pw), field('Rol', rol)),
  h('h3', null, 'Locals amb accés'), h('div', null, checks), h('div', { class: 'actions' }, bU), outU);
  return h('div', null, nou, await usersCard());
}

function securitySection() {
  const outA = h('div');
  const bA = h('button', { class: 'primary' }, "Verificar la integritat de l'auditoria");
  bA.addEventListener('click', () => guard(bA, outA, async () => {
    const r = await api('/auditoria/verificar');
    outA.replaceChildren(r.integra ? msg('ok', "Cadena d'auditoria íntegra") : msg('err', "ALTERACIÓ detectada a l'entrada " + r.primera_alterada));
  }));
  return h('div', null, h('div', { class: 'card' }, h('h3', null, 'Auditoria'),
    h('p', { class: 'muted' }, "Cada acció queda en un registre encadenat per hash. Si algú el modifica, aquesta comprovació ho detecta."), h('div', { class: 'actions' }, bA), outA),
  h('div', { class: 'card' }, h('h3', null, 'Bloqueig per intents fallits'),
    h('p', { class: 'muted' }, "Després de 5 intents fallits en 15 minuts un usuari queda bloquejat uns minuts. Per desbloquejar-lo abans, executa al servidor: python -m app.cli desbloquejar <usuari>.")));
}

VIEWS.config = async () => {
  const items = [
    ['local', 'Local i límits', async () => localSection()],
    ['quotes', 'Quotes', async () => quotesSection()],
    ['usuaris', 'Usuaris', usersSection],
    ['bascules', 'Bàscules', async () => deviceSection('bascula')],
    ['signatura', 'Tauletes de signatura', async () => deviceSection('signatura')],
    ['carnets', 'Carnets i lectors', async () => cardsSection()],
    ['seguretat', 'Seguretat', async () => securitySection()],
  ];
  return h('div', null, pageHead('Configuració', 'Ajustos del local, usuaris i dispositius. Cada subpantalla fa una sola cosa.'), sections('config', items));
};
