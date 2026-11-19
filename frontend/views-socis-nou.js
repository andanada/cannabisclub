'use strict';
// Socis: «Cercar» i «Llista» units en una sola pestanya (cerca per nom, cognoms, DNI/NIE/passaport o carnet RFID + llista filtrable)
// i la fitxa del soci a sota. L'alta de socis és de la gerència.

VIEWS.socis = async () => {
  const items = [['cercar', 'Cercar i llista', async () => {
    const panel = memberPanel();
    const cerca = capsaCerca(async (m) => { panel.show(m, h('div')); panel.found.scrollIntoView({ behavior: 'smooth', block: 'start' }); });
    return h('div', null, cerca, panel.found, h('h3', null, 'Tots els socis'),
      memberList((m, out) => { panel.show(m, out); panel.found.scrollIntoView({ behavior: 'smooth', block: 'start' }); }));
  }]];
  if (isManager()) items.push(['alta', 'Alta de soci', async () => altaWizard()]);
  return h('div', null, pageHead('Socis', 'Cerca un soci per nom, cognoms, DNI/NIE/passaport o carnet, o mira la llista.'), sections('socis', items));
};
