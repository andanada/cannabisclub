'use strict';
// Lògica pura del diagnòstic de dispositius (sense DOM): analitza el que s'ha rebut i dóna un veredicte
// amb una llista de comprovacions {id, ok, text}. La pantalla (views-diagnostic.js) només les pinta.

const check = (id, ok, text) => ({ id, ok: !!ok, text });
const verdict = (checks) => ({ ok: checks.length > 0 && checks.every((c) => c.ok), checks });

// ---------- Bàscula ----------
// `lines`: línies de text rebudes; `cfg`: perfil (unit, read…); `parse`: parsePesLine de bascula.js.
function analyzeScale(lines, cfg, parse) {
  const checks = [check('rebut', lines.length > 0, lines.length ? `La bàscula ha respost (${lines.length} línies).` : "No s'ha rebut cap resposta: revisa el cable, la velocitat i l'ordre de lectura.")];
  let reading = null;
  let error = null;
  for (const l of lines) {
    try { const r = parse(l); if (r) { reading = r; break; } } catch (e) { error = e.message; }
  }
  checks.push(check('pes', !!reading, reading ? `Pes reconegut: ${reading.raw}.` : (error || "Hi ha respostes, però no semblen un pes: prova una altra ordre de lectura.")));
  if (reading) {
    const unitOk = !cfg || !cfg.unit || reading.unit === cfg.unit;
    checks.push(check('unitat', unitOk, unitOk ? `Unitat correcta (${reading.unit}).` : `La bàscula treballa en ${reading.unit} i el perfil diu ${cfg.unit}: canvia la unitat de la bàscula o del perfil.`));
    checks.push(check('estable', reading.stable, reading.stable ? 'Lectura estable.' : "La lectura és inestable («?»): deixa el pes quieto i torna a provar."));
  }
  return Object.assign(verdict(checks), { reading });
}

// ---------- Lector de carnets que fa de teclat ----------
// `keys`: [{ key, t }] (t en ms). Un lector «escriu» tot el codi en pocs mil·lisegons i acaba amb Intro/Tab;
// una persona teclejant triga molt més entre tecles.
const MAX_GAP_READER_MS = 60;

function analyzeKeystrokes(keys, cfg) {
  const term = { enter: 'Enter', tab: 'Tab' }[(cfg && cfg.terminador) || 'enter'];
  const chars = keys.filter((k) => k.key.length === 1);
  const last = keys[keys.length - 1];
  const gaps = chars.slice(1).map((k, i) => k.t - chars[i].t);
  const maxGap = gaps.length ? Math.round(Math.max(...gaps)) : 0;
  const code = chars.map((k) => k.key).join('');
  const fast = chars.length >= 4 && maxGap <= MAX_GAP_READER_MS;
  const checks = [
    check('rebut', chars.length > 0, chars.length ? `S'han rebut ${chars.length} caràcters.` : "No s'ha rebut res: fes clic al camp i passa el carnet pel lector."),
    check('velocitat', fast, fast ? `Ritme de lector (màxim ${maxGap} ms entre caràcters).` : `Ritme massa lent (${maxGap} ms): sembla escrit a mà, no un lector.`),
  ];
  if (term) {
    const ok = !!last && last.key === term;
    checks.push(check('terminador', ok, ok ? `El lector acaba amb ${term}, com diu el perfil.` : `El perfil espera ${term} al final i no ha arribat: canvia el terminador del perfil o la configuració del lector.`));
  }
  const prefix = (cfg && cfg.prefix) || '';
  if (prefix) checks.push(check('prefix', code.startsWith(prefix), code.startsWith(prefix) ? `Prefix «${prefix}» detectat.` : `No ha arribat el prefix «${prefix}» del perfil.`));
  const min = (cfg && cfg.longitud_min) || 4;
  const clean = prefix && code.startsWith(prefix) ? code.slice(prefix.length) : code;
  checks.push(check('longitud', clean.length >= min, clean.length >= min ? `Longitud correcta (${clean.length}).` : `Codi massa curt (${clean.length}; el perfil demana ${min}).`));
  return Object.assign(verdict(checks), { code: clean, maxGap });
}

// ---------- Tauleta de signatura ----------
// `events`: [{ type: 'down'|'move'|'up', pointerType, pressure }].
function analyzePointer(events, cfg) {
  const downs = events.filter((e) => e.type === 'down');
  const moves = events.filter((e) => e.type === 'move');
  const types = [...new Set(events.map((e) => e.pointerType))];
  const pressures = moves.map((e) => e.pressure).filter((p) => p > 0 && p < 1);
  const min = (cfg && cfg.tracos_min) || 1;
  const checks = [
    check('traços', downs.length >= min, downs.length >= min ? `${downs.length} traços rebuts.` : `Només ${downs.length} traços; el perfil en demana ${min}.`),
    check('moviment', moves.length >= 10, moves.length >= 10 ? 'El punter segueix el traç amb continuïtat.' : 'Gairebé no hi ha moviment: el dispositiu no envia el traç complet.'),
  ];
  const pen = types.includes('pen');
  if (cfg && cfg.pressio) {
    checks.push(check('pressio', !pen || pressures.length > 0, pen ? (pressures.length ? 'El llapis envia pressió.' : 'El llapis no envia pressió: desmarca «sensible a la pressió» al perfil.') : 'Sense llapis: es fa servir un gruix fix.'));
  }
  return Object.assign(verdict(checks), { pointerTypes: types, pressure: pressures.length > 0 });
}

// ---------- Capacitats del navegador ----------
function browserSupport(env) {
  return {
    serial: !!(env && env.serial),
    nfc: !!(env && env.nfc),
    secure: !!(env && env.secure),
    pointer: !!(env && env.pointer),
  };
}

if (typeof module !== 'undefined') module.exports = { analyzeScale, analyzeKeystrokes, analyzePointer, browserSupport, MAX_GAP_READER_MS };
