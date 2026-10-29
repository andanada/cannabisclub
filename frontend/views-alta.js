'use strict';
// Alta de soci en 5 passos: Dades → Signatura → Foto → Carnet → Quota i resum.
// El soci es crea en acabar el primer pas; la signatura és obligatòria per continuar, la resta es pot ometre i completar després.

const PASSOS_ALTA = ['Dades', 'Signatura', 'Foto', 'Carnet', 'Quota i resum'];

function stepper(actual, fets) {
  return h('ol', { class: 'stepper', 'aria-label': "Passos de l'alta" }, PASSOS_ALTA.map((t, i) =>
    h('li', { class: (i === actual ? 'actual ' : '') + (i < actual || fets.has(i) ? 'fet' : ''), 'aria-current': i === actual ? 'step' : null },
      h('span', { class: 'num-pas' }, i < actual || fets.has(i) ? '✓' : String(i + 1)), h('span', { class: 'nom-pas' }, t))));
}

// Camp amb comprovació immediata: `valida(valor)` torna {ok, text}.
function campAmbAjuda(etiqueta, input, valida) {
  const ajuda = h('div', { class: 'hint', 'aria-live': 'polite' });
  const pinta = () => {
    const r = valida(input.value);
    ajuda.textContent = r.text || '';
    ajuda.className = 'hint ' + (r.text ? (r.ok ? 'ok' : 'bad') : '');
    input.setAttribute('aria-invalid', String(!!input.value && !r.ok));
    return r;
  };
  input.addEventListener('input', pinta);
  input.addEventListener('blur', pinta);
  return { node: h('div', null, field(etiqueta, input), ajuda), pinta };
}

function altaWizard() {
  const root = h('div');
  const st = { pas: 0, id: null, m: null, fets: new Set() };
  const refresca = async () => { st.m = await api(`/socis/${st.id}`); };
  const nav = (pas) => { st.pas = pas; pinta(); };

  function pasDades() {
    const out = h('div');
    const f = {
      nom: h('input', { autocomplete: 'off', required: true }), cognoms: h('input', { autocomplete: 'off', required: true }),
      doc: h('input', { autocapitalize: 'characters', autocomplete: 'off', required: true, placeholder: 'DNI, NIE o passaport' }),
      naix: h('input', { type: 'date', required: true, max: new Date().toLocaleDateString('sv-SE') }),
      tel: h('input', { inputmode: 'tel', placeholder: '+34 600 000 000' }), mail: h('input', { type: 'email', placeholder: 'nom@correu.cat' }),
      rgpd: h('input', { type: 'checkbox', required: true }),
    };
    const doc = campAmbAjuda('Document', f.doc, validaDocument);
    const naix = campAmbAjuda('Data de naixement', f.naix, validaNaixement);
    const tel = campAmbAjuda('Telèfon (opcional)', f.tel, validaTelefon);
    const mail = campAmbAjuda('Correu (opcional)', f.mail, validaCorreu);
    const btn = h('button', { class: 'primary', type: 'submit' }, 'Continuar a la signatura');
    return h('form', { class: 'card', onsubmit: (e) => {
      e.preventDefault();
      guard(btn, out, async () => {
        const nom = (f.nom.value.trim() + ' ' + f.cognoms.value.trim()).trim();
        if (!f.nom.value.trim() || !f.cognoms.value.trim()) throw new Error('Escriu el nom i els cognoms');
        if (!doc.pinta().ok) throw new Error('Revisa el document');
        if (!naix.pinta().ok) throw new Error('Revisa la data de naixement');
        if (!tel.pinta().ok || !mail.pinta().ok) throw new Error('Revisa el telèfon i el correu');
        if (!f.rgpd.checked) throw new Error("Cal confirmar que el soci ha estat informat del tractament de dades");
        const r = await api('/socis', { method: 'POST', body: { local_id: S.local, nom, document: f.doc.value.trim(), naixement: f.naix.value,
          telefon: f.tel.value.trim() || null, email: f.mail.value.trim() || null } });
        st.id = r.id;
        st.fets.add(0);
        await refresca();
        nav(1);
      });
    } },
    h('h3', null, 'Dades personals'),
    h('div', { class: 'row' }, field('Nom', f.nom), field('Cognoms', f.cognoms)),
    h('div', { class: 'row' }, doc.node, naix.node),
    h('h3', null, 'Contacte'), h('div', { class: 'row' }, tel.node, mail.node),
    h('label', { class: 'check' }, f.rgpd, ' El soci ha estat informat del tractament de les seves dades i hi dona el consentiment.'),
    h('div', { class: 'actions' }, btn), out);
  }

  function pasSignatura() {
    const out = h('div');
    return h('div', null, h('div', { class: 'card' }, h('h3', null, 'Signatura'),
      h('p', { class: 'muted' }, `${st.m.nom} ha de signar dins del quadre per acabar l'alta.`)), signaturePad(st.id, out, async () => {
      st.fets.add(1);
      nav(2);
    }), out);
  }

  function pasFoto() {
    const out = h('div');
    const recarrega = async () => { await refresca(); if (st.m.te_foto) st.fets.add(2); pinta(); };
    const seguent = h('button', { class: 'primary', type: 'button' }, st.m.te_foto ? 'Continuar' : 'Ometre per ara');
    seguent.addEventListener('click', () => nav(3));
    return h('div', { class: 'card' }, h('h3', null, 'Foto del soci'),
      h('p', { class: 'muted' }, 'Fes la foto amb la càmera o puja una imatge. Es redueix automàticament i es desa xifrada.'),
      h('div', { class: 'member' }, memberPhoto(st.m), h('div', { class: 'actions' }, ...photoUploader(st.m, out, recarrega))),
      h('div', { class: 'actions' }, seguent), out);
  }

  function pasCarnet() {
    const out = h('div');
    const recarrega = async () => { await refresca(); if (st.m.te_carnet) st.fets.add(3); pinta(); };
    const seguent = h('button', { class: 'primary', type: 'button' }, st.m.te_carnet ? 'Continuar' : 'Ometre per ara');
    seguent.addEventListener('click', () => nav(4));
    return h('div', null, cardManager(st.m, out, recarrega),
      h('p', { class: 'muted' }, 'Pots llegir un carnet que ja tinguis o crear-ne un de nou a Configuració → Carnets i lectors.'),
      h('div', { class: 'actions' }, seguent), out);
  }

  function pasResum() {
    const out = h('div');
    const loc = S.me.locals.find((l) => l.id === st.m.local_id) || S.me.locals.find((l) => l.id === S.local) || {};
    const alDia = !!(st.m.quota && st.m.quota.al_dia);
    const fila = (ok, text, pendent) => h('li', { class: ok ? 'ok' : 'pendent' }, h('span', { class: 'marca' }, ok ? '✓' : '·'), ' ', ok ? text : pendent);
    const resum = h('div', { class: 'card' }, h('h3', null, 'Resum'), h('div', { class: 'big' }, st.m.nom), h('p', { class: 'muted' }, `${st.m.document} · ${st.m.naixement}`),
      h('ul', { class: 'resum' }, fila(true, 'Dades personals', ''), fila(st.fets.has(1), 'Signatura desada', 'Signatura pendent'),
        fila(!!st.m.te_foto, 'Foto desada', 'Sense foto'), fila(!!st.m.te_carnet, 'Carnet assignat', 'Sense carnet'),
        fila(alDia, 'Quota al dia fins al ' + (alDia ? dataCa(st.m.quota.valid_fins) : ''), 'Quota pendent')));
    const finalitza = h('button', { class: 'primary', type: 'button' }, 'Finalitzar alta');
    finalitza.addEventListener('click', () => { st.pas = 5; pinta(); });
    const pagament = !alDia ? quotaForm(st.m, out, async () => { await refresca(); pinta(); }) : null;
    return h('div', null, resum, pagament, loc.quota_obligatoria && !alDia ? msg('err', 'Aquest local exigeix la quota al dia per poder dispensar.') : null,
      h('div', { class: 'actions' }, finalitza), out);
  }

  function pasFet() {
    const nou = h('button', { class: 'primary', type: 'button' }, 'Nou soci');
    nou.addEventListener('click', () => { st.pas = 0; st.id = null; st.m = null; st.fets = new Set(); pinta(); });
    const dispensar = h('button', { type: 'button' }, 'Anar a Dispensar');
    dispensar.addEventListener('click', () => show('dispensar'));
    return h('div', { class: 'card fet-alta' }, h('div', { class: 'gran-marca', 'aria-hidden': 'true' }, '✓'), h('h3', null, 'Alta completada'),
      h('p', null, h('strong', null, st.m.nom), ` ja és soci (núm. ${st.m.id}).`), h('div', { class: 'actions' }, nou, dispensar));
  }

  function pinta() {
    const pasos = [pasDades, pasSignatura, pasFoto, pasCarnet, pasResum, pasFet];
    const cos = pasos[st.pas]();
    const enrere = st.pas >= 2 && st.pas <= 4 ? h('button', { type: 'button', class: 'small' }, '← Enrere') : null;
    if (enrere) enrere.addEventListener('click', () => nav(st.pas - 1));
    root.replaceChildren(...(st.pas < 5 ? [stepper(st.pas, st.fets)] : []), cos, ...(enrere ? [h('div', { class: 'actions' }, enrere)] : []));
  }
  pinta();
  return root;
}
