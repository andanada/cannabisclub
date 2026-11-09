# RGPD: plantilles (BORRADOR — a validar per un advocat o el DPO)

> Punt de partida tècnic, **no assessorament legal**. Cal completar-lo i validar-lo abans d'usar-lo.
> Les dades de consum de cànnabis poden considerar-se de categoria especial (salut) o de risc elevat.

## A. Registre d'activitats de tractament (art. 30)

Un bloc per activitat (socis, dispensació, caixa, personal/fitxatge, còpies de seguretat).

| Camp | Contingut (exemple: socis) |
|---|---|
| Responsable | <nom de l'entitat, NIF, adreça, contacte> |
| DPO / contacte de privacitat | <si escau> |
| Finalitat | <gestió de socis, control d'edat i límits, comptabilitat> |
| Base jurídica (art. 6 / art. 9) | <contracte / obligació legal / consentiment explícit: a determinar> |
| Categories d'interessats | socis, personal |
| Categories de dades | identificació, document, data de naixement, contacte, foto, signatura, consum (grams per producte) |
| Dades de categoria especial? | <a valorar: consum com a indicatiu de salut> |
| Destinataris | <cap / assessoria / autoritat> |
| Transferències internacionals | <cap / ubicació del remot de còpies> |
| Termini de conservació | <a determinar> (les taules «només afegir» limiten la supressió: vegeu README) |
| Mesures de seguretat (art. 32) | xifrat de camps (Fernet) i de còpies (GPG), Argon2id + TOTP, rol de BD sense privilegis, auditoria encadenada, xarxa privada, còpies signades amb claus separades |
| Encarregats del tractament | <hosting, remot de còpies> amb contracte de l'art. 28 |

## B. Checklist d'avaluació d'impacte (EIPD, art. 35)

- [ ] Descripció sistemàtica del tractament i de les finalitats.
- [ ] Necessitat i proporcionalitat: minimització (quines dades de soci són imprescindibles?).
- [ ] Dades de categoria especial o a gran escala? Hi ha biometria/NFC?
- [ ] Riscos per als drets: accés il·legítim, modificació, pèrdua, exposició del consum, discriminació.
- [ ] Mesures per a cada risc (xifrat, control per rol/local, auditoria, còpies, formació del personal).
- [ ] Drets dels interessats: accés, rectificació, supressió (**límit tècnic**: fotos i apunts «només afegir», procediment manual), portabilitat, oposició; qui respon i en 1 mes.
- [ ] Retenció i esborrat definits (socis de baixa, fotos, còpies antigues: retenció 14/8/12).
- [ ] Contractes de l'art. 28 amb els encarregats.
- [ ] Procediment de violació provat (`docs/PRODUCCIO.md` § 6).
- [ ] Consulta prèvia a l'autoritat si el risc residual és alt (art. 36).
- [ ] Informació als socis (art. 13) i registre del consentiment si és la base jurídica.
- [ ] Revisió periòdica de l'EIPD (anual o davant canvis importants).
