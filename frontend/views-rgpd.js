'use strict';
// Privacitat (RGPD): consentiments, accés i portabilitat, supressió, registre d'accessos i retenció de dades.

const FINALITATS = { basic: 'Tractament bàsic', foto: 'Fotografia', contacte: 'Contacte' };
const dataHora = (iso) => new Date(iso).toLocaleString(loc(), { dateStyle: 'short', timeStyle: 'short' });
const isAdmin = () => S.me.role === 'admin';

// Cerca un soci per nom (o per número) i el passa a `onTria({id, nom})`.
function selectorSoci(onTria) {
  const q = h('input', { type: 'search', placeholder: 'Nom o número de soci', 'aria-label': 'Cercar soci' });
  const llista = h('div'), out = h('div');
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Cercar');
  const form = h('form', { class: 'card', onsubmit: (e) => {
    e.preventDefault();
    guard(btn, out, async () => {
      const t = q.value.trim();
      if (/^\d+$/.test(t)) { const m = await api(`/socis/${t}`); llista.replaceChildren(); onTria({ id: m.id, nom: m.nom }); return; }
      const socis = await api(`/locals/${S.local}/socis?q=${encodeURIComponent(t)}`);
      llista.replaceChildren(socis.length ? h('ul', { class: 'checks' }, socis.slice(0, 30).map((m) => h('li', null,
        h('button', { type: 'button', class: 'small', onclick: () => onTria({ id: m.id, nom: m.nom }) }, `${m.nom} (núm. ${m.id}, ${m.estat})`)))) : h('p', { class: 'muted' }, 'Cap soci coincideix.'));
    });
  } }, h('h3', null, 'Soci'), h('div', { class: 'row' }, field('Soci', q), h('div', { class: 'actions' }, btn)), llista, out);
  return form;
}

async function baixaFitxer(url, nom, tipus) {
  const r = await api(url, { raw: true });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "No s'ha pogut exportar");
  descarrega(tipus === 'json' ? new Blob([JSON.stringify(await r.json(), null, 2)], { type: 'application/json' }) : await r.blob(), nom);
}

function fitxaRgpd(soci) {
  const cos = h('div'), out = h('div');
  async function pinta() {
    const c = await api(`/socis/${soci.id}/consentiments`);
    const filaCons = (f) => {
      const vigent = c.vigents[f];
      const accio = f === 'basic' ? null : vigent
        ? h('button', { type: 'button', class: 'small', onclick: () => guard(out, out, async () => { await api(`/socis/${soci.id}/consentiments/retirada`, { method: 'POST', body: { finalitat: f } }); toast('Consentiment retirat'); await pinta(); }) }, 'Retirar')
        : h('button', { type: 'button', class: 'small', onclick: () => guard(out, out, async () => {
          const t = await api('/textos/informatiu?idioma=' + LANG);
          await api(`/socis/${soci.id}/consentiments`, { method: 'POST', body: { versio: t.versio, text_sha256: t.sha256, finalitats: [f], canal: 'presencial' } });
          toast('Consentiment registrat'); await pinta();
        }) }, 'Registrar');
      return [FINALITATS[f], vigent ? 'Sí' : 'No', accio];
    };
    cos.replaceChildren(
      taula([['Finalitat'], ['Vigent'], ['']], Object.keys(FINALITATS).map(filaCons)),
      h('h4', null, 'Historial de consentiments'),
      taula([['Data'], ['Finalitat'], ['Acció'], ['Versió'], ['Canal']], c.historial.map((x) => [dataHora(x.ts), FINALITATS[x.finalitat], x.accio === 'atorgat' ? 'Atorgat' : 'Retirat', x.versio, x.canal]), 'Cap consentiment registrat (soci anterior al registre).'));
  }
  const exporta = h('button', { type: 'button', onclick: () => guard(exporta, out, () => baixaFitxer(`/socis/${soci.id}/exportacio`, `dades-soci-${soci.id}.json`, 'json')) }, 'Exportar totes les dades (JSON)');
  const consum = h('button', { type: 'button', onclick: () => guard(consum, out, () => baixaFitxer(`/socis/${soci.id}/exportacio/consum.csv`, `consum-soci-${soci.id}.csv`)) }, 'Exportar consum (CSV)');
  const admin = !isAdmin() ? null : h('div', null, h('h4', null, 'Accessos i supressió'),
    h('div', { class: 'actions' },
      h('button', { type: 'button', onclick: (e) => guard(e.target, out, async () => {
        const r = await api(`/socis/${soci.id}/accessos`);
        out.replaceChildren(taula([['Data'], ['Acció'], ['Usuari']], r.accessos.map((a) => [dataHora(a.ts), a.accio, a.per_usuari || '—']), 'Ningú ha accedit a aquestes dades.'),
          h('button', { type: 'button', class: 'small', onclick: () => baixaFitxer(`/socis/${soci.id}/accessos.csv`, `accessos-soci-${soci.id}.csv`).catch((er) => toast(er.message)) }, 'Descarregar CSV'));
      }) }, 'Qui ha accedit a les dades'),
      h('button', { type: 'button', class: 'danger', onclick: (e) => guard(e.target, out, async () => {
        const prova = await api(`/socis/${soci.id}/supressio`, { method: 'POST', body: {} });
        if (prova.bloqueig === 'no_es_de_baixa') throw new Error('Només es poden suprimir les dades d\'un soci de baixa.');
        if (prova.bloqueig === 'retencio') throw new Error(`Bloquejat per la política de conservació (${prova.min_dies} dies des de la baixa).`);
        if (prova.bloqueig === 'ja_suprimit') throw new Error('Les dades d\'aquest soci ja estan suprimides.');
        if (!await confirma('Això esborra de manera irreversible el nom, el document, les dades de contacte, la foto i la signatura del soci. Continuar?')) return;
        const r = await api(`/socis/${soci.id}/supressio`, { method: 'POST', body: { confirmar: true, motiu: 'sol·licitud del soci' } });
        out.replaceChildren(msg('ok', `Dades suprimides (${r.binaris_buidats} imatges buidades).`));
      }) }, 'Suprimir dades (seudonimitzar)')));
  pinta().catch((e) => cos.replaceChildren(msg('err', e.message)));
  return h('div', { class: 'card' }, h('h3', null, `${soci.nom} · núm. ${soci.id}`), cos, h('h4', null, 'Dret d\'accés i portabilitat'), h('div', { class: 'actions' }, exporta, consum), admin, out);
}

function secSoci() {
  const zona = h('div');
  return h('div', null, selectorSoci((s) => zona.replaceChildren(fitxaRgpd(s))), zona);
}

function secAuditoria() {
  const f = { soci: h('input', { inputmode: 'numeric' }), usuari: h('input', { inputmode: 'numeric' }), accio: h('input', { maxlength: 40 }),
    des: h('input', { type: 'date' }), fins: h('input', { type: 'date' }) };
  const res = h('div'), out = h('div');
  let offset = 0;
  const LIM = 50;
  async function carrega() {
    const p = new URLSearchParams({ limit: String(LIM), offset: String(offset) });
    for (const [k, el] of Object.entries(f)) if (el.value.trim()) p.set(k, el.value.trim());
    const r = await api('/auditoria/consulta?' + p);
    const ant = h('button', { type: 'button', class: 'small', disabled: offset === 0, onclick: () => { offset = Math.max(0, offset - LIM); carrega().catch((e) => res.replaceChildren(msg('err', e.message))); } }, '← Anteriors');
    const seg = h('button', { type: 'button', class: 'small', disabled: !r.hi_ha_mes, onclick: () => { offset += LIM; carrega().catch((e) => res.replaceChildren(msg('err', e.message))); } }, 'Següents →');
    res.replaceChildren(taula([['Núm.'], ['Data'], ['Acció'], ['Soci'], ['Usuari']], r.entrades.map((e) => [e.seq, dataHora(e.ts), e.accio, e.soci ?? '', e.per_usuari || e.per || ''])),
      h('div', { class: 'actions' }, ant, seg));
  }
  const btn = h('button', { class: 'primary', type: 'submit' }, 'Consultar');
  return h('div', null, h('form', { class: 'card', onsubmit: (e) => { e.preventDefault(); offset = 0; guard(btn, out, carrega); } },
    h('h3', null, "Registre d'accessos i accions"),
    h('div', { class: 'row' }, field('Soci (núm.)', f.soci), field('Usuari (núm.)', f.usuari), field('Acció', f.accio)),
    h('div', { class: 'row' }, field('Des de', f.des), field('Fins a', f.fins)), h('div', { class: 'actions' }, btn), out), res);
}

function secRetencio() {
  const res = h('div'), out = h('div');
  async function veure() {
    const r = await api(`/locals/${S.local}/retencio`);
    const aplica = h('button', { type: 'button', class: 'danger', disabled: !r.suprimibles && !r.fotos_velles && !r.intents_login && !r.sessions_caducades,
      onclick: () => guard(aplica, out, async () => {
        if (!await confirma(`S'aplicarà la purga: ${r.suprimibles} socis seudonimitzats, ${r.fotos_velles} fotos antigues, ${r.intents_login} intents de login. Continuar?`)) return;
        const x = await api(`/locals/${S.local}/retencio/aplicar`, { method: 'POST', body: { confirmar: true } });
        out.replaceChildren(msg('ok', `Fet: ${x.suprimits.length} socis seudonimitzats.`));
        await veure();
      }) }, 'Aplicar la purga');
    res.replaceChildren(h('div', { class: 'card' }, h('h3', null, 'Simulació (no s\'ha canviat res)'),
      h('p', { class: 'muted' }, `Conservació mínima des de la baixa: ${r.config.min_dies_baixa} dies · fotos antigues: ${r.config.fotos_velles_dies} dies · intents de login: ${r.config.intents_login_dies} dies.`),
      taula([['Soci'], ['Baixa'], ['Dies', true], ['Estat']], r.candidats.map((c) => [c.soci, c.baixa ? dataHora(c.baixa) : '—', c.dies_des_de_la_baixa ?? '', c.suprimible ? 'Es pot suprimir' : 'Bloquejat per la conservació mínima']), 'Cap soci de baixa pendent de suprimir.'),
      h('p', null, `Fotos antigues a buidar: ${r.fotos_velles} · intents de login: ${r.intents_login} · sessions caducades: ${r.sessions_caducades}`), h('div', { class: 'actions' }, aplica)));
  }
  veure().catch((e) => res.replaceChildren(msg('err', e.message)));
  return h('div', null, res, out);
}

VIEWS.rgpd = async () => sections('rgpd', [
  ['soci', "Dades d'un soci", async () => secSoci()],
  ...(isAdmin() ? [['auditoria', "Registre d'accessos", async () => secAuditoria()], ['retencio', 'Retenció de dades', async () => secRetencio()]] : []),
]);
