'use strict';
// Configuració (només administradors): cada tasca a la seva subpantalla.
// Local i límits · Quotes · Normes · Categories · Gastos · Controls del club · Usuaris · Bàscules · Signatura · Carnets · Diagnòstic · Seguretat · Privacitat.
// El menú «Gestió» ja no existeix: el que servia viu aquí (la gerència hi veu la seva part; els treballadors, cap opció).

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
  // Excepcions per soci (abans a Controls del club): els límits del local i les seves excepcions queden en un sol lloc.
  return h('div', null, limits, h('div', { class: 'card' }, h('h3', null, 'Excepcions de límit per soci'), secLimits()),
    h('p', { class: 'muted' }, 'Crea un local nou. També serveix per crear un magatzem exterior al local.'), nou,
    warehouseCreateForm(() => show('config')));
}

// Normes del club: edat mínima, alerta d'inactivitat, decimals de la dispensació i pèrdua màxima tolerada en un inventari.
function normesSection() {
  const loc = localActual();
  const edat = h('input', { type: 'number', min: 18, max: 99, value: loc.edat_minima || 18 });
  const inact = h('input', { type: 'number', min: 1, max: 365, value: loc.inactivitat_dies || 30 });
  const dec = h('select', null, [0, 1, 2, 3].map((n) => h('option', { value: n, selected: n === (loc.decimals_dispensacio ?? 3) }, String(n))));
  const perdua = h('input', { inputmode: 'decimal', value: loc.perdua_maxima_mg ? (loc.perdua_maxima_mg / 1000).toString().replace('.', ',') : '', placeholder: 'sense límit' });
  const baix = h('input', { inputmode: 'decimal', value: String((loc.estoc_baix_mg ?? 5000) / 1000).replace('.', ','), 'aria-label': "Avís d'estoc baix" });
  const donMax = h('input', { inputmode: 'decimal', value: loc.donacions_dia_max_cent ? preuText(loc.donacions_dia_max_cent) : '', placeholder: 'sense límit', 'aria-label': 'Màxim de donacions per treballador i dia' });
  const diesCuota = h('input', { type: 'number', min: 0, max: 3650, value: loc.cuota_inactivitat_dies ?? 90, 'aria-label': 'Dies sense retirar genètiques' });
  const out = h('div');
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Desar');
  return h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      await api(`/locals/${S.local}/config`, { method: 'PUT', body: { edat_minima: Number(edat.value), inactivitat_dies: Number(inact.value), decimals_dispensacio: Number(dec.value),
        perdua_maxima_mg: perdua.value.trim() ? Math.round(parseGrams(perdua.value) * 1000) : 0,
        estoc_baix_mg: baix.value.trim() ? Math.round(parseGrams(baix.value) * 1000) : 0, cuota_inactivitat_dies: Number(diesCuota.value), donacions_dia_max_cent: donMax.value.trim() ? parseEur(donMax.value) : 0 } });
      S.me = await api('/me');
      out.replaceChildren(msg('ok', 'Normes desades'));
    });
  } }, h('h3', null, 'Normes del club · ' + loc.nom),
  h('div', { class: 'row' }, field('Edat mínima per ser soci', edat), field("Alerta d'inactivitat (dies sense visites)", inact)),
  h('div', { class: 'row' }, field('Decimals admesos en una dispensació', dec), field("Diferència màxima en un inventari (g): a partir d'aquí surt l'avís als resultats", perdua)),
  h('div', { class: 'row' }, field("Avís d'estoc baix: quan al dispensari queda menys de (g o unitats)", baix), field('Dies sense retirar genètiques abans de demanar la quota a l\'accés (0 = no es demana)', diesCuota)),
  h('div', { class: 'row' }, field('Màxim de donacions que pot afegir un treballador al dia (€; la gerència no en té)', donMax)),
  h('div', { class: 'actions' }, btn), out);
}

function quotesSection() {
  const loc = localActual();
  const imp = h('input', { inputmode: 'decimal', value: loc.quota_cent ? preuText(loc.quota_cent) : '', placeholder: 'sense import per defecte' });
  const mesos = h('input', { type: 'number', min: 1, max: 24, value: loc.quota_mesos || 1 });
  const obl = h('input', { type: 'checkbox', checked: !!loc.quota_obligatoria });
  const mon = h('input', { type: 'checkbox', checked: !!loc.moneder_actiu });
  const cons = h('input', { type: 'checkbox', checked: !!loc.consum_exigit });
  const targ = h('input', { type: 'checkbox', checked: !!loc.targeta_activa });
  const monLim = h('input', { inputmode: 'decimal', value: preuText(loc.moneder_limit_cent || 0), placeholder: '0,00' });
  const out = h('div');
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Desar');
  return h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      await api(`/locals/${S.local}/config`, { method: 'PUT', body: { quota_cent: imp.value.trim() ? parseEur(imp.value) : 0, quota_mesos: Number(mesos.value), quota_obligatoria: obl.checked, moneder_actiu: mon.checked, consum_exigit: cons.checked, targeta_activa: targ.checked, moneder_limit_cent: monLim.value.trim() ? parseEur(monLim.value) : 0 } });
      S.me = await api('/me');
      out.replaceChildren(msg('ok', 'Quotes desades'));
    });
  } }, h('h3', null, 'Quotes · ' + loc.nom),
  h('p', { class: 'muted' }, 'Import i durada que es proposen en cobrar una quota, i si cal tenir-la al dia per poder dispensar.'),
  h('div', { class: 'row' }, field('Import per defecte (€)', imp), field('Mesos per defecte', mesos)),
  h('label', null, obl, ' Exigir la quota al dia per poder dispensar'),
  h('h3', null, 'Donacions i monedero'),
  h('p', { class: 'muted' }, 'Donacions: els diners que donen els socis (es cobren a recepció i entren a la caixa; gastar-los en dispensacions no és un ingrés nou). Monedero: la part del perfil de cada soci que mostra el que ha donat i el saldo que li queda.'),
  h('label', null, cons, ' Exigir el consentiment explícit del registre de consum per dispensar'), h('label', null, mon, ' Activar el monedero (saldo a la fitxa del soci)'), h('div', { class: 'row' }, field('Saldo negatiu permès (€)', monLim)),
  h('label', null, targ, ' El local accepta targeta i Bizum (si no, només efectiu i crèdits del compte)'),
  h('div', { class: 'actions' }, btn), out);
}

// Contrasenya aleatòria de 16 caràcters sense lletres ambigües (0/O, 1/l/I), amb majúscules, minúscules, xifres i símbol.
function contrasenyaAleatoria() {
  const grups = ['ABCDEFGHJKLMNPQRSTUVWXYZ', 'abcdefghijkmnopqrstuvwxyz', '23456789', '#$%&*+=?'];
  const tots = grups.join('');
  const bytes = new Uint32Array(16);
  crypto.getRandomValues(bytes);
  const out = Array.from(bytes, (b, i) => (i < grups.length ? grups[i][b % grups[i].length] : tots[b % tots.length]));
  for (let i = out.length - 1; i > 0; i--) { const j = bytes[i] % (i + 1); [out[i], out[j]] = [out[j], out[i]]; }
  return out.join('');
}

const ROL_DESCRIPCIONS = {
  admin: "Perfil d'accés complet: recepció, dispensari, configuració, usuaris i informes. Veu tots els locals.",
  encarregat: "Gerència, perfil d'accés complet a recepció i dispensari dels seus locals, amb gastos, controls i informes. No gestiona usuaris.",
  dispensador: 'Treballador: en iniciar sessió tria el rol del dia (Recepció o Dispensari) i només veu les pantalles d\'aquest rol.',
};

async function usersSection() {
  const un = h('input', { autocomplete: 'off', placeholder: 'p. ex. maria', 'aria-label': "Nom d'usuari" });
  const pw = h('input', { type: 'password', autocomplete: 'new-password', placeholder: 'Mínim 12 caràcters' });
  const rol = h('select', null, Object.keys(ROL_NOMS).reverse().map((r) => h('option', { value: r }, ROL_NOMS[r])));
  rol.value = 'dispensador';
  const descRol = h('p', { class: 'muted' }, ROL_DESCRIPCIONS[rol.value]);
  const checks = S.me.locals.map((l) => h('label', { class: 'check' }, h('input', { type: 'checkbox', value: l.id }), ' ', l.nom));
  const localsBox = h('div');
  localsBox.append(h('h3', null, 'Locals amb accés'), h('p', { class: 'muted' }, 'Marca els locals on podrà treballar.'), h('div', null, checks));
  const mostraLocals = () => { localsBox.hidden = rol.value === 'admin'; descRol.textContent = ROL_DESCRIPCIONS[rol.value]; };
  rol.addEventListener('change', mostraLocals);
  mostraLocals();
  const gen = h('button', { type: 'button', class: 'small' }, 'Generar contrasenya');
  gen.addEventListener('click', () => { pw.value = contrasenyaAleatoria(); pw.type = 'text'; });
  const veure = h('button', { type: 'button', class: 'small' }, 'Mostrar');
  veure.addEventListener('click', () => { pw.type = pw.type === 'password' ? 'text' : 'password'; veure.textContent = pw.type === 'password' ? 'Mostrar' : 'Amagar'; });
  const outU = h('div');
  const llista = h('div');
  const pintaLlista = async () => llista.replaceChildren(await usersCard());
  const opcions = await fetch('/auth/opcions').then((r) => r.json()).catch(() => ({ totp: true }));
  const bU = h('button', { class: 'primary', type: 'submit' }, 'Crear usuari');
  const nou = h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(bU, outU, async () => {
      const usuari = un.value.trim(), clau = pw.value;
      if (usuari.length < 3) throw new Error("El nom d'usuari ha de tenir almenys 3 caràcters");
      if (clau.length < 12) throw new Error('La contrasenya ha de tenir almenys 12 caràcters');
      const ids = rol.value === 'admin' ? [] : checks.map((c) => c.querySelector('input')).filter((i) => i.checked).map((i) => Number(i.value));
      if (rol.value !== 'admin' && !ids.length) throw new Error('Marca almenys un local');
      const r = await api('/usuaris', { method: 'POST', body: { username: usuari, password: clau, role: rol.value, local_ids: ids } });
      un.value = ''; pw.value = ''; pw.type = 'password';
      checks.forEach((c) => { c.querySelector('input').checked = false; });
      const credencials = `Usuari: ${usuari}\nContrasenya: ${clau}` + (opcions.totp ? `\nSecret TOTP: ${r.totp_secret}` : '');
      const copia = h('button', { type: 'button', class: 'small' }, 'Copiar credencials');
      copia.addEventListener('click', async () => { try { await navigator.clipboard.writeText(credencials); toast('Credencials copiades'); } catch (_) { toast('No s\'ha pogut copiar: selecciona el text'); } });
      outU.replaceChildren(msg('ok', `Usuari «${usuari}» creat. Copia les credencials ara: no es tornaran a mostrar.`),
        h('pre', { class: 'secret' }, credencials), h('div', { class: 'actions' }, copia));
      await pintaLlista();
    });
  } }, h('h3', null, 'Nou usuari'),
  h('div', { class: 'row' }, field("Nom d'usuari", un), field('Rol', rol)),
  descRol,
  h('div', { class: 'row' }, field('Contrasenya (mínim 12 caràcters)', pw), h('div', { class: 'actions' }, gen, veure)),
  localsBox, h('div', { class: 'actions' }, bU), outU);
  await pintaLlista();
  return h('div', null, nou, llista);
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

// Seccions de Configuració. Admin: totes. Encarregat (gerència): només les seves. Els treballadors no hi entren (el menú no els la mostra).
const CONFIG_ENCARREGAT = ['categories', 'gastos', 'controls', 'carnets', 'diagnostic', 'rgpd'];
const controlsSection = async () => sections('controls', [
  ['controls', 'Controls', secControls], ['lots', 'Lots i traçabilitat', secLots], ['llibres', 'Llibres', async () => secLlibres()],
]);
function configItems() {
  const items = [
    ['local', 'Local i límits', async () => localSection()],
    ['quotes', 'Quotes', async () => quotesSection()],
    ['normes', 'Normes del club', async () => normesSection()],
    ['categories', 'Categories de productes', secCategories],
    ['gastos', 'Gastos', gastosSection],
    ['controls', 'Controls del club', controlsSection],
    ['usuaris', 'Usuaris', usersSection],
    ['bascules', 'Bàscules', async () => deviceSection('bascula')],
    ['signatura', 'Tauletes de signatura', async () => deviceSection('signatura')],
    ['carnets', 'Carnets i lectors', async () => cardsSection()],
    ['diagnostic', 'Diagnòstic', diagnosticSection],
    ['seguretat', 'Seguretat', async () => securitySection()],
    ['rgpd', 'Privacitat i protecció de dades', rgpdSection],
  ];
  if (S.me.role === 'admin') return items;
  return isManager() ? items.filter(([id]) => CONFIG_ENCARREGAT.includes(id)) : [];
}

VIEWS.config = async () => {
  const visibles = configItems();
  if (!visibles.length) return h('div', { class: 'card empty' }, 'No tens accés a la configuració.');
  return h('div', null, pageHead('Configuració', 'Ajustos del local, gastos, usuaris i dispositius. Cada subpantalla fa una sola cosa.'), sections('config', visibles));
};
