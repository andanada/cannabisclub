# Producció: llista de comprovació

Aquest document és per posar el programa en servei i mantenir-lo. Les còpies de seguretat són a `COPIES.md`.

## 1. Abans del primer ús

- [ ] Python 3.12+ amb `.venv`. Instal·lació reproduïble: `pip install --require-hashes -r requirements.lock` (versions i hashes fixats; es regenera amb `scripts/update-lock.sh`). `requirements.txt` és la llista de partida.
- [ ] PostgreSQL 16+ amb els dos rols (`club` propietari i `club_app` per a l'aplicació): `python -m app.cli preparar-bd ../.env`.
- [ ] `.env` amb permisos `600` (`CLUB_DB_PASSWORD`) i `~/.config/club-gestio/app.env` (`CLUB_FIELD_KEY`, `CLUB_INDEX_KEY`, `CLUB_APP_DATABASE_URL`): les claus només han de viure en **un** lloc del servidor. **Custòdia fora del servidor** (`docs/COPIES.md`): sense `CLUB_FIELD_KEY` les dades personals no es poden desxifrar mai més, i sense `CLUB_INDEX_KEY` es perden les cerques per document i els carnets.
- [ ] Servei: `scripts/systemd/club-gestio.service` (mode usuari) o `club-gestio.system.service` (mode sistema, enduriment complet i `After=docker.service`). Porta `--no-access-log`: els accessos de uvicorn registrarien documents i codis de carnet a la URL.
  - Mode usuari: `sudo loginctl enable-linger <usuari>` perquè arrenqui en reiniciar sense sessió oberta. Una unitat d'usuari no pot dependre de `docker.service` (és del sistema): reintenta amb `Restart=on-failure` fins que la BD respongui.
  - Enduriment que funciona en mode usuari: `UMask=0077`, `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`, `RestrictAddressFamilies`, `LockPersonality`, `MemoryMax` (aquest darrer requereix delegar el controlador de memòria: vegeu el comentari al fitxer).
  - Només en mode sistema: `User=`, `PrivateDevices`, `ProtectKernel*`, `ProtectProc`, `CapabilityBoundingSet=`, `SystemCallFilter`, `Requires=docker.service`. Comprova'n el resultat amb `systemd-analyze [--user] security club-gestio`.
- [ ] nginx davant: `scripts/nginx/club.conf` (HTTPS, `limit_req` a `/auth/`, `client_max_body_size`, `X-Forwarded-For`, capçaleres). Amb nginx cal `CLUB_TRUST_PROXY=1`.
- [ ] HTTPS: la bàscula (Web Serial) i la gravació NFC només funcionen en un context segur. Amb Tailscale: `tailscale serve --bg https / http://127.0.0.1:8099`. Posa `CLUB_HSTS=1` al servei un cop confirmis que tot va per HTTPS.
- [ ] Còpies xifrades programades (`scripts/systemd/club-backup.timer`), **remot configurat** (sense `CLUB_BACKUP_REMOTE` la còpia falla a propòsit), claus en custòdia i **una restauració provada**: `docs/COPIES.md`.
- [ ] Alertes actives (§ 2) i provades amb `scripts/club-monitor.sh test`.
- [ ] No obris el port 8099 a cap interfície pública: només `127.0.0.1` darrere de Tailscale.

### Segon factor (TOTP)

Per defecte l'inici de sessió exigeix usuari, contrasenya i codi de l'app d'autenticació. Només en un **servidor de proves** es pot desactivar amb `CLUB_TOTP=0` al fitxer d'entorn del servei (la pantalla d'entrada amaga el camp). **No el deixis així amb dades reals**: sense el segon factor, la contrasenya és l'única protecció. Per tornar-lo a activar, treu la línia i reinicia el servei.

### Entrada amb carnet RFID + PIN

Els treballadors (no els administradors) poden entrar passant un carnet pel lector i escrivint un PIN, per canviar de lloc de feina sense escriure l'usuari. Es configura a **Configuració → Usuaris → Carnet d'entrada** (només administradors).

- **Dues capes**: el carnet («alguna cosa que tens») i el PIN de 4 a 8 xifres («alguna cosa que saps»). Es rebutgen PIN fàcils (xifres repetides, seqüències). El PIN es desa com Argon2 d'un HMAC amb `CLUB_INDEX_KEY`: sense aquesta clau no es pot atacar fora de línia.
- **Només carnets generats pel programa** (codi llarg i imprevisible amb dígit de control). No s'accepta l'UID d'un xip qualsevol: és curt i es pot copiar o endevinar. El codi es mostra una sola vegada en generar-lo; s'imprimeix amb codi de barres o es grava en una etiqueta NFC.
- **Bloqueig**: 5 PIN erronis en 15 minuts bloquegen el carnet d'aquell usuari (la contrasenya segueix funcionant); hi ha un límit global per a carnets desconeguts. El bloqueig i cada entrada queden a l'auditoria.
- **Carnet perdut**: retira'l a Usuaris → Retirar carnet; deixa de servir a l'acte.
- **Només des de la xarxa del club (recomanat)**: `CLUB_CARNET_XARXES=192.168.1.0/24` (llista de CIDR separats per comes). Darrere nginx cal també `CLUB_TRUST_PROXY=1`; només es fa cas de l'última entrada de `X-Forwarded-For`, la que afegeix el proxy.
- **Apagar-ho**: `CLUB_LOGIN_CARNET=0`.
- Un carnet RFID segueix sent copiable: per això el PIN és obligatori i els administradors no hi entren mai.

### Primer arrencada

Una base de dades sense cap local mostra a l'administrador un formulari per crear-ne el primer. Un usuari que no és administrador i no té cap local assignat veu un missatge que ho explica.

## 2. Monitoratge i alertes

- `GET /salut` (sense autenticació): `200 {"ok": true}` si la base de dades respon, `503` si no.
- `scripts/club-monitor.sh check` (timer `club-monitor.timer`, cada 15 min) comprova `/salut`, l'espai en disc (85 %), l'edat de l'última còpia correcta (> 26 h) i la caducitat del certificat (`CLUB_CERT_HOST=host:443` o `CLUB_CERT_FILE`; 14 dies). Avisa en canviar d'estat i repeteix cada 6 h (`CLUB_ALERT_REPEAT_MIN`).
- Notificació: `CLUB_ALERT_CMD` a `~/.config/club-gestio/monitor.env` (mode 600). Rep el missatge per stdin i a `$CLUB_ALERT_MESSAGE`. Exemples (mail, Telegram) a la capçalera del script. Prova: `scripts/club-monitor.sh test`.
- `OnFailure=club-alert@%n.service` a `club-backup.service` i `club-audit.service`: una còpia o verificació fallida avisa sola.
- Auditoria: `club-audit.timer` (dilluns 06:00) executa `scripts/club-audit-verify.py` i falla (i avisa) si la cadena està trencada. `python -m app.cli` **no té** subordre per a això. Per a qui editi `cli.py`: afegir `verificar-auditoria` que cridi `service.audit_verify` i retorni 3 si falla; llavors `club-audit.service` pot usar-lo en lloc de l'script.
- Logs: `journalctl -u club-gestio`. Cada petició surt com `MÈTODE /camí estat durada` **sense** la query string. Un error inesperat surt amb un `id` de 12 caràcters; el mateix `id` el veu l'usuari a la pantalla. `CLUB_LOG_LEVEL=WARNING` redueix el soroll.

## 3. Actualitzar el programa

1. Còpia de seguretat de la base de dades.
2. Actualitza el codi i `pip install --require-hashes -r requirements.lock`.
3. Amb l'usuari propietari: `python -m app.cli actualitzar-bd` (crea taules, **columnes** noves amb valor per defecte i **índexs**, i dona permisos; es pot repetir).
4. Reinicia el servei. Si t'has oblidat del pas 3, el servei no arrenca i diu què falta (taules o columnes).
5. Les pestanyes obertes agafen la versió nova la propera vegada que es recarreguen: els fitxers del front es serveixen amb `Cache-Control: no-cache` (el navegador revalida sempre) i el service worker s'activa de seguida.

## 4. Incidències habituals

| Símptoma | Què fer |
|---|---|
| Un usuari no pot entrar i les credencials són bones | Pot estar bloquejat (5 intents fallits en 15 min): `python -m app.cli desbloquejar <usuari>` |
| Un usuari ha perdut el telèfon | Configuració → Usuaris → **Reiniciar TOTP** (mostra el secret nou una sola vegada) |
| Error 500 amb un codi | Busca el codi als logs: `journalctl -u club-gestio \| grep <codi>` |
| `Falten taules a la base de dades` en arrencar | Executa `actualitzar-bd` amb l'usuari propietari |
| La bàscula no apareix | Cal Chrome o Edge i HTTPS (o `localhost`); prova la comunicació a Configuració → Bàscules |
| Un carnet no es llegeix | Comprova el prefix i el terminador a Configuració → Carnets i lectors → Lector |
| Cal esborrar una foto d'un soci | Només amb el rol propietari de PostgreSQL, desactivant el trigger `member_photos_no_change`; deixa-ho anotat |

## 5. Límits coneguts

- Una persona que conegui un nom d'usuari el pot bloquejar 15 minuts amb intents fallits; en una xarxa privada és un risc acceptat.
- Els codis de carnet només es mostren en generar-los (al servidor només hi ha una empremta): si es perd la targeta, es genera un carnet nou.
- La bàscula OHAUS i la gravació NFC no s'han provat amb maquinari real; hi ha eines de prova a Configuració per ajustar-ho al teu model.
- Hi ha una versió del programa per a un sol servidor. Si es fan servir dos servidors alhora, caldria compartir els bloquejos d'inici de sessió (ara van a la base de dades, així que ja és compatible) i revisar la caché de perfils del navegador.
- **Rotació de `CLUB_FIELD_KEY` / `CLUB_INDEX_KEY`: no implementada** (vegeu `docs/COPIES.md`).
- La còpia és diària: RPO fins a ~24 h (sense arxivat WAL).
- La signatura de les còpies no protegeix d'un atacant que ja controli la torre (té la clau de signatura); sí d'una manipulació del remot.

## 6. Violació de seguretat de dades personals (RGPD arts. 33-34)

> BORRADOR a validar per l'advocat o el DPO. No és assessorament legal. Termini: **72 h** per notificar a l'autoritat (APDCAT/AEPD) des que se'n té coneixement.

1. **Detectar i anotar**: hora de coneixement, qui, com. Obre un registre d'incident.
2. **Contenir**: aïlla la torre de la xarxa (`tailscale down`, tanca nginx); **no l'apaguis ni esborris** (evidència). Reinicia el servei, canvia contrasenyes/TOTP dels usuaris afectats i retira els carnets implicats.
3. **Preservar evidències**: `journalctl -u club-gestio > incident.log`, còpia del volcat més recent, `scripts/club-audit-verify.py` i el registre d'accessos a dades de socis.
4. **Avaluar el risc** per a les persones: categories (identificació, contacte, document, foto, signatura, consum = possible dada de salut), nombre d'afectats, si estaven xifrades i si s'han filtrat les claus. Un volcat filtrat **sense** `CLUB_FIELD_KEY` té risc baix; una torre sencera amb claus, màxim.
5. **Notificar a l'autoritat en ≤ 72 h** si hi ha risc (art. 33): naturalesa, categories i nombre aproximat, contacte del DPO/responsable, conseqüències probables, mesures. Es pot fer per fases. Si no notifiques, documenta per què.
6. **Comunicar als afectats** sense dilació si el risc és **alt** (art. 34): llenguatge clar, què ha passat, què poden fer, contacte. No cal si les dades eren il·legibles (xifrades amb una clau no compromesa).
7. **Remeiar**: rota secrets (contrasenya de BD, `club_app`, TOTP, claus GPG; la rotació de FIELD/INDEX és un límit conegut), corregeix la causa, restaura d'una còpia vàlida si cal (`docs/COPIES.md`).
8. **Tancar**: lliçons apreses i, si cal, revisa l'EIPD. Conserva el registre de l'incident encara que no hi hagi notificació (art. 33.5).

Plantilles de registre d'activitats (art. 30) i checklist d'EIPD: `docs/RGPD.md`.
