# Producció: llista de comprovació

Aquest document és per posar el programa en servei i mantenir-lo. Les còpies de seguretat són a `COPIES.md`.

## 0. Com s'hi accedeix: només per Tailscale (decisió actual)

El club real **no s'exposa a Internet**: només s'hi arriba des de dispositius de la xarxa privada Tailscale (la «tailnet»). El servidor de proves públic (`nip.io` + certbot) és l'excepció i no s'ha de copiar a producció.

- **Servei**: uvicorn només a `127.0.0.1:8099` (mai `0.0.0.0`).
- **HTTPS**: `tailscale serve --bg https / http://127.0.0.1:8099` (certificat de Tailscale, sense nginx ni certbot, sense port 80/443 públics). Cal HTTPS per a la bàscula i l'NFC.
- **Entrada amb carnet**: limita-la a la tailnet amb `CLUB_CARNET_XARXES=100.64.0.0/10` (rang de Tailscale). Si no uses el carnet, `CLUB_LOGIN_CARNET=0`.
  Aquesta comprovació mira la IP del client: **prova-ho des d'un mòbil de la tailnet** abans de donar-ho per bo. Si darrere de `tailscale serve` l'aplicació veiés sempre 127.0.0.1, el carnet quedaria bloquejat; cal confirmar si Tailscale envia `X-Forwarded-For` (i llavors `CLUB_TRUST_PROXY=1`) o deixar el carnet només per a la IP que correspongui. No s'ha pogut verificar en aquest entorn.
- **Segon factor**: `CLUB_TOTP` **no** a `0`. Cada arrencada escriu al registre un avís `ATENCIÓ` si està desactivat, i la pantalla d'entrada mostra una franja vermella.
- **Claus**: a la primera arrencada la base de dades desa un «canari» de les claus; si després arrenques amb unes altres, el servei **no arrenca** (missatge clar al registre). Si has perdut el mòbil amb l'app d'autenticació: `python -m app.cli reiniciar-totp <usuari>`.
- **Bloqueig de login**: amb només la tailnet, qui pot bloquejar un usuari és algú de dins; `python -m app.cli desbloquejar <usuari>` ho resol.

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

- **Dues capes**: el carnet («alguna cosa que tens») i el PIN de **6 a 8 xifres** (abans 4-6; els PIN antics de 4-5 xifres segueixen entrant però el sistema obliga a canviar-lo) («alguna cosa que saps»). Es rebutgen PIN fàcils (xifres repetides, seqüències). El PIN es desa com Argon2 d'un HMAC amb `CLUB_INDEX_KEY`: sense aquesta clau no es pot atacar fora de línia.
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
- Auditoria: `club-audit.timer` (dilluns 06:00) executa `scripts/club-audit-verify.py` i falla (i avisa) si la cadena està trencada. Equivalent: `python -m app.cli verificar-auditoria [seq:hash]` (sortida 3 si falla; accepta un ancoratge). Vegeu «Auditoria: HMAC i ancoratge» més avall.
- Logs: `journalctl -u club-gestio`. Cada petició surt com `MÈTODE /camí estat durada` **sense** la query string. Un error inesperat surt amb un `id` de 12 caràcters; el mateix `id` el veu l'usuari a la pantalla. `CLUB_LOG_LEVEL=WARNING` redueix el soroll.

## 3. Actualitzar el programa

**Forma recomanada: `scripts/deploy.sh`** (des del teu ordinador, amb el commit que vols desplegar ja fet):

    scripts/deploy.sh --host usuari@servidor            # el servidor també es pot posar a CLUB_DEPLOY_HOST
    scripts/deploy.sh --host usuari@servidor --deps     # la primera vegada, i quan requirements.lock hagi canviat sense que ho detecti
    scripts/deploy.sh --host usuari@servidor --dry-run  # només diu què faria

Fa, en aquest ordre: puja el commit (sempre amb finals de línia LF), desa la base de dades i el codi actual a `~/club-backups`, canvia `backend/app`, `frontend`, `scripts` i `docs` (**el que ja no és al repositori desapareix del servidor**), instal·la `requirements.lock` amb hashes si ha canviat, executa `actualitzar-bd`, reinicia el servei i espera que `/salut` respongui amb **la versió nova** (`"versio"`). Si alguna cosa falla, **torna sola al codi anterior** i surt amb error; la base de dades només ha rebut canvis additius, així que tornar enrere el codi és segur. No toca `.env`, `.venv` ni les dades. Es guarden els 5 desplegaments més recents a `.releases/` (el codi anterior de cada un és a `<desplegament>.prev`). `--prova-rollback` força un error de salut per comprovar la tornada enrere.

Requisits al servidor: `ssh` sense contrasenya, `sudo -n systemctl restart club-gestio`, Docker (per a la còpia de la BD) i el servei amb `/salut`. Per desplegar un commit concret: `--ref <commit>`.

**Pas a pas, a mà** (el que fa el script, per si cal fer-ho sense ell):

1. Còpia de seguretat de la base de dades.
2. Actualitza el codi i `pip install --require-hashes -r requirements.lock`.
3. Amb l'usuari propietari: `python -m app.cli actualitzar-bd` (crea taules, **columnes** noves amb valor per defecte i **índexs**, dona permisos i fa la migració única dels productes genètics, vegeu § 3.1; es pot repetir).
4. Reinicia el servei. Si t'has oblidat del pas 3, el servei no arrenca i diu què falta (taules o columnes).
5. Les pestanyes obertes agafen la versió nova la propera vegada que es recarreguen: els fitxers del front es serveixen amb `Cache-Control: no-cache` (el navegador revalida sempre) i el service worker s'activa de seguida.

### 3.1 Migració dels productes genètics (`es_genetic`) — cal revisar-la

Els límits diari/mensual per soci **només compten productes marcats com a genètics**. En una base de dades anterior a aquest camp, tots els productes queden amb `es_genetic = FALSE` i, sense fer res, **els límits deixarien d'aplicar-se**. Per això `actualitzar-bd`, **una sola vegada per local** (marca `es_genetic_migrat` a `local_settings`; en repetir l'ordre no torna a tocar res):

1. Marca com a genètics els productes la **categoria** dels quals sigui de flor, hash/haixix, extracte/resina, clon/esqueix o llavor/semilla/seed (també «cannabis», «marihuana»).
2. No toca res si el local ja té algun producte genètic (algú ja l'havia classificat): només desa la marca.
3. **Mostra per pantalla** els productes marcats i la llista dels que han quedat com a **no genètics, pendents de revisar** (amb una pista si el *nom* sembla genètic però la categoria no). Desa aquesta sortida: no es torna a mostrar.
4. Deixa un registre d'auditoria `migracio_es_genetic` amb els ids marcats.

**Què has de fer després:** a **Estoc → Productes**, repassa la llista de pendents i marca «És genètic» on calgui. Mentre el local tingui límits actius i **cap** producte genètic, la pantalla de productes mostra un avís vermell. Un producte que la migració hagi marcat per error es desmarca a la mateixa pantalla (no es tornarà a marcar).

### 3.2 Variables d'entorn noves

Totes van al fitxer d'entorn del servei (`app.env`), llevat que s'indiqui.

| Variable | Per defecte | Significat |
|---|---|---|
| `CLUB_AUDIT_KEY` | derivada de `CLUB_INDEX_KEY` | Clau de l'HMAC de la cadena d'auditoria (entrades noves marcades `h1`). Si no hi és s'usa una derivada de `CLUB_INDEX_KEY`. **Canviar-la (o canviar `CLUB_INDEX_KEY` sense `CLUB_AUDIT_KEY`) invalida la verificació de les entrades `h1` existents.** Custòdia fora del servidor, com les altres claus. |
| `CLUB_AUDIT_HMAC_DES_DE` | — | Número de `seq` a partir del qual TOTES les entrades han de ser `h1`. Fixa'l al `seq` de l'últim ancoratge un cop activat l'HMAC: així ningú pot refer la cadena amb SHA-256 sense la clau. |
| `CLUB_LOGIN_IP_LIMIT` | `60` | Intents de `/auth/login` i `/auth/login-carnet` per adreça IP i minut (429 si se supera). Darrere nginx cal `CLUB_TRUST_PROXY=1` perquè sigui la IP real. |
| `CLUB_ARGON_CONCURRENCY` | `4` | Quantes verificacions Argon2 (contrasenya/PIN) poden córrer alhora; les altres esperen i, si el servidor va saturat, reben 503 amb `Retry-After`. Ajusta-ho als nuclis i a la memòria. |
| `CLUB_MAX_BODY_BYTES` | `1048576` | Mida màxima del cos d'una petició (413 si es supera). El cos legítim més gran és la foto/signatura en base64 (~400 KB); no el pugis sense motiu i alinea'l amb `client_max_body_size` de nginx. |
| `CLUB_TOTP_REPLAY` | `1` | Un codi TOTP només serveix una vegada per usuari. `0` ho desactiva (**només per a proves**). El registre és en memòria: es perd en reiniciar. |

### 3.3 Canvis que cal conèixer en actualitzar

- **Cerques per POST**: la cerca de soci per document i per carnet ja no passen per la URL sinó per `POST /locals/{id}/socis/cerca` i `POST /locals/{id}/socis/carnet` (cos JSON). Els `GET` antics han desaparegut: si hi ha scripts o marcadors propis, cal adaptar-los. Així el document i el codi no queden als logs de nginx ni a l'historial.
- **Dispensar i cobrar**: `POST /dispensacions` accepta `metode` (`efectiu`/`targeta`) i aleshores dispensa i cobra en una sola transacció. La pantalla ofereix «Dispensar i cobrar en efectiu / amb targeta» i, a part, «Dispensar i cobrar després» (flux anterior).
- **Tancar la caixa** avisa de les dispensacions sense cobrar (també abans de tancar, a Caixa → Tancament); la resposta porta `sense_cobrar` i `sense_cobrar_cent`.
- **Errors**: un registre immutable (moviments, apunts, signatures…) o una col·lisió de restricció no esperada responen **409** amb un missatge net, mai 500.

### 3.4 Auditoria: HMAC i ancoratge

La cadena d'auditoria només detecta retalls del final o reescriptures completes si es compara amb un **ancoratge** guardat fora del servidor (últim `seq:hash`).

- `python -m app.audit_cli ancora` imprimeix `seq:hash`. `scripts/club-backup.sh run` l'executa després de cada còpia i el desa a `club-AAAAMMDD-HHMMSS.dump.gpg.anchor` (al costat de la còpia i al remot, amb la mateixa retenció). Si no el pot obtenir, avisa però la còpia es conserva.
- Verificar contra un ancoratge: `python -m app.cli verificar-auditoria <seq:hash>` (o `python -m app.audit_cli verifica <seq:hash>`); sense argument només comprova la cadena i avisa `sense_ancoratge`. Per fer-ho contra el de la còpia remota més recent: `... verificar-auditoria "$(cat club-....dump.gpg.anchor)"`.
- Els ancoratges interns (`audit_anchors`, `POST /auditoria/ancoratges`) porten una columna `sig` = HMAC(clau d'auditoria, `club-anchor|seq|hash`); `verificar-auditoria` **ignora** els que no tenen una `sig` vàlida (qui pugui escriure a la BD sense la clau no els pot forjar). **Compatibilitat:** els ancoratges interns existents d'abans d'aquest canvi no tenen `sig` i deixen de comptar: després d'actualitzar, executa `POST /auditoria/ancoratges` (o `actualitzar-bd` i un ancoratge nou) i compara la verificació amb l'ancoratge extern; l'avís `sense_ancoratge` indica que no n'hi ha cap de signat. Canviar la clau d'auditoria també invalida els ancoratges interns signats.
- Recomanat: un cop activat l'HMAC, fixa `CLUB_AUDIT_HMAC_DES_DE` al `seq` de l'ancoratge i guarda la clau (`CLUB_AUDIT_KEY` o `CLUB_INDEX_KEY`) fora del servidor.

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

- **Bloqueig provocable per tercers (límit conegut):** qualsevol persona amb accés a la pantalla d'entrada i que conegui un nom d'usuari el pot bloquejar 15 minuts amb 5 intents fallits (denegació de servei dirigida; el comportament no s'ha canviat deliberadament, perquè l'alternativa —no bloquejar— afebleix la protecció contra l'endevinació de PIN). Mitigació recomanada: a nginx, `limit_req` (i si cal `limit_conn`) per IP a `/auth/` (ja inclòs a `scripts/nginx/club.conf`; ajusta `rate`/`burst`), amb `CLUB_TRUST_PROXY=1` perquè el límit i els registres vegin la IP real, i no exposar el servei a Internet obert. En una xarxa privada és un risc acceptat.
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
