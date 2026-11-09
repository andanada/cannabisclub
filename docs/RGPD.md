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

## C. Què implementa el programa (revisió RGPD i controls de club)

Resum tècnic; no substitueix la validació jurídica de la secció D.

1. **Consentiments** (`consents`, només d'afegir). Finalitats `basic`, `foto`, `contacte`; cada registre porta versió del text,
   SHA-256 del text acceptat, canal, usuari i la signatura vinculada. La retirada és un registre nou (`accio = retirat`);
   el tractament bàsic només es «retira» donant de baixa el soci. Textos versionats a `backend/app/textos/<versio>/{ca,es,en}.txt`
   (mai es modifica una versió publicada: es crea la v2). L'alta (`POST /socis/{id}/alta-rgpd`) desa els consentiments, la signatura
   (enllaçada amb el hash del text, `signatures.text_sha256`, o amb `sig_ultima` si ja s'havia desat), `doc_verificat` i l'avalador.
   Un soci amb registre no pot tenir foto sense consentiment `foto` vigent; els socis anteriors al registre es comporten com abans.
2. **Accés i portabilitat** (`GET /socis/{id}/exportacio`, `.../exportacio/consum.csv`; admin i encarregat, auditat): ficha descifrada,
   consentiments, quotes, entrades, dispensacions, carnets, metadades de fotos/signatures (amb enllaç, sense el binari) i l'auditoria que l'afecta.
3. **Supressió per seudonimització** (`POST /socis/{id}/supressio`, només admin, amb `confirmar`). Es conserva la fila de `members` i el seu id;
   s'anul·len nom, document, naixement, telèfon, correu, empremtes HMAC (document i carnets), aval, fotos i signatures. Les fotos i signatures són
   a taules només d'afegir: el mecanisme és la funció `club_buida_binaris` (SECURITY DEFINER, propietat del propietari de la BD) i un trigger que
   només admet l'UPDATE originat per aquesta funció que buida la imatge i el seu hash; el rol `club_app` només pot cridar-la i només per a socis
   de baixa. Descartat el *crypto-shredding* per soci (obligaria a re-xifrar tot i custodiar una taula de claus) i donar propietat a l'aplicació
   (trencaria el mínim privilegi). Bloquejada fins que passin `CLUB_RETENCIO_MIN_DIES` dies (365 per defecte) des de la baixa. Queda a l'auditoria. **Endurit (PostgreSQL):** la funció té `search_path = pg_catalog, <esquema>, pg_temp` i taules qualificades, i `TEMPORARY` està revocat a PUBLIC
   (cap taula temporal pot fer-hi ombra). La funció calcula ella mateixa la retenció (`baixa_en <= now() - min_dies`) llegint `club_retencio_cfg`, que
   només escriu el propietari (`actualitzar-bd` la sincronitza amb `CLUB_RETENCIO_MIN_DIES`/`CLUB_RETENCIO_FOTOS_DIES`; també `schema.set_retention`); no accepta cap
   tall arbitrari i deixa rastre a `club_buida_log` (només d'afegir, sense privilegis per a `club_app`). Els socis de baixa antics sense `baixa_en` només es poden
   buidar amb retenció 0 fins que s'ompli la data.
4. **Retenció** (`backend/app/retencio.py`, `scripts/club-retencio.py`, `GET /locals/{id}/retencio`): simula per defecte; amb `--aplicar` suprimeix els socis
   vençuts, buida fotos antigues (no la darrera de cada soci; `CLUB_RETENCIO_FOTOS_DIES`, 365) i esborra intents de login (`CLUB_RETENCIO_INTENTS_DIES`, 30) i sessions caducades.
5. **Registre d'accessos**: s'audita la fitxa, quotes, consum, foto, signatura, exportacions i consultes d'auditoria. `GET /auditoria/consulta`
   (admin; per soci, usuari, acció, dates; paginat) i `GET /socis/{id}/accessos(.csv)` («qui ha accedit»).
6. **Controls de club** (per local, valors per defecte = comportament anterior): `espera_dies`, `aval` (no/opcional/obligatori), `alta_pendent`
   (aprovació per un altre gestor o un admin), excepcions de límit diari/mensual per soci amb motiu i auditoria. Es validen a `controls.py`, cridat des de `stock.dispense`.
7. **Lots** (`batches`, `movement_batches`): entrada amb lot, dispensació FIFO o amb lot manual (`POST /dispensacions/amb-lot`), correcció que retorna al lot, informe de traçabilitat.
8. **Llibres signats** (`/locals/{id}/llibres/{socis,estoc}.csv`): hash SHA-256 a la capçalera `X-Content-SHA256` i a l'auditoria; `POST /llibres/verificar`.
   Els informes demogràfics no publiquen cap cel·la amb menys de 5 socis (amb supressió complementària). Els camps lliures passen per `csvutil.cell`.
9. **Seguretat**: `users.last_totp_step` (anti-reutilització TOTP persistent i atòmica; `CLUB_TOTP_REPLAY=0` ho desactiva), `audit_log.alg` (informatiu i
   coherent amb `_alg`; les entrades antigues queden a NULL i no es toquen), taula `audit_anchors` (`POST /auditoria/ancoratges`) que `audit_verify` comprova.

Migració: tot són taules/columnes noves amb valor per defecte; `python -m app.cli actualitzar-bd` és idempotent (provat sobre SQLite i PostgreSQL).

## D. Pendent d'advocat / DPO

- Validar i completar el **text informatiu** (identitat del responsable, base jurídica real de cada finalitat, destinataris, terminis) i la **versió v1**; decidir si cal DPO.
- Fixar els **terminis de conservació** reals (`CLUB_RETENCIO_MIN_DIES` és un valor prudent, no una obligació jurídica) segons obligacions fiscals, associatives i de les administracions competents.
- Avaluar si la **fotografia** és un tractament de categoria especial (biometria) i si l'EIPD (secció B) és obligatòria; el programa no fa reconeixement facial.
- El camp lliure `nota`/`concepte` dels moviments pot contenir dades personals si algú les escriu: la supressió no els toca (política d'ús o revisió manual).
- **Còpies de seguretat**: les còpies anteriors a una supressió conserven les dades; cal una política de rotació/restauració coherent amb l'art. 17.
- Registre d'activitats (A), contracte d'encarregat amb el proveïdor d'allotjament, procediment de **violacions de seguretat** (72 h) i resposta a l'exercici de drets (terminis d'un mes).
- Revisar el **llindar k = 5** i la supressió complementària dels informes, i la legalitat del model d'aval i de període d'espera d'acord amb els estatuts i la normativa autonòmica.
- Conservar **fora de l'equip** l'ancoratge de l'auditoria (`/auditoria/ancoratge`): l'ancoratge a la BD no protegeix contra qui sigui propietari de la base de dades.
