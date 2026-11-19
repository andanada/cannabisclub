# Més que un Club

(Nom tècnic del projecte: `club-gestio`.)

Programa propi de gestió d'un club (socis, estoc, caixa, personal, multi-local). Els requisits són a `REQUISITS.md`.
Backend FastAPI + SQLAlchemy (PostgreSQL en producció, SQLite per a proves) i una PWA sense dependències a `frontend/`.

Secrets: `CLUB_DB_PASSWORD` va a `.env`; `CLUB_FIELD_KEY`, `CLUB_INDEX_KEY` i `CLUB_APP_DATABASE_URL` van **només** a `~/.config/club-gestio/app.env` (plantilla amb totes les variables: `app.env.example`). Res d'això s'ha de versionar. No s'exposa a Internet; només per Tailscale.

## Instal·lació

Cal Python 3.12 (o superior) i Node 20+ (només per a les proves de la bàscula).

**Windows (PowerShell):**

    py -3.12 -m venv .venv
    .venv\Scripts\python -m pip install -r requirements-dev.txt

**Linux / macOS:**

    python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements-dev.txt

Al llarg del document es fa servir `.venv/bin/python`; a Windows és `.venv\Scripts\python`.

## Arrencada (desenvolupament)

Claus: `CLUB_FIELD_KEY` és una clau Fernet (`python -c "from app.crypto import generate_key; print(generate_key())"` dins de `backend`) i `CLUB_INDEX_KEY`, un text llarg qualsevol. Han de ser sempre les mateixes: si canvien, les dades desades ja no es poden desxifrar.

    export CLUB_FIELD_KEY=... CLUB_INDEX_KEY=... CLUB_DATABASE_URL=sqlite:///dev.db
    cd backend && ../.venv/bin/python -m app.cli crear-admin <usuari>
    ../.venv/bin/uvicorn --factory app.main:create_app --host 127.0.0.1 --port 8099

(a Windows PowerShell: `$env:CLUB_FIELD_KEY="..."` i `.venv\Scripts\python -m uvicorn ...`). `crear-admin` demana la contrasenya (mínim 12 caràcters) i mostra el secret TOTP per a l'app d'autenticació.

## Com s'organitza la interfície

El menú té vuit entrades: **Socis · Accés · Caixa · Dispensar · Estoc · Horaris · Estadístiques i informes · Configuració**.

**Rol del dia.** En iniciar sessió, un treballador tria **Recepció** o **Dispensari** (la gerència —admin i encarregat— té accés complet i no tria). Recepció: Accés (pàgina d'inici), Caixa, Socis. Dispensari: Dispensar (inici), Estoc, Socis. Les donacions (crèdit als socis) i la caixa són de recepció; el dispensari no els toca. Tot el personal pot consultar els socis i afegir-ne incidències.

- **Accés**: una sola pantalla. Carnet RFID o cerca per DNI/NIE/passaport, codi, nom o cognoms; llista dels socis dins per ordre d'entrada amb foto, hora i avís d'incidències. Un soci **expulsat** no pot entrar; si fa més de 3 mesos que no retira genètiques, el programa proposa cobrar la quota.
- **Socis**: «Cercar i llista» units. Alta sense gènere ni adreça i amb **Tipus de membre** (Ordinari, Terapèutic 20 %, Família 30 % de descompte). A la fitxa, Donacions primer, l'estat (amb Expulsar) i el tipus es canvien directament.
- **Donacions**: cada soci té un saldo; es carrega a recepció i s'afegeix a la caixa. Dispensar es paga sempre del saldo.
- **Caixa**: una sola caixa, a recepció: Estat · Despesa · Apunts · Tancament · Resum de sessions.
- **Dispensar**: cerca única + llista de socis dins; la finestra del soci mostra incidències, consum del mes i historial, categories, productes i **carret** (regal per línia, descompte de membre, total i saldo) i un sol botó «Dispensar».
- **Estoc**: Productes (genètica/no genètica, categories segons el tipus, preu d'entrada i de dispensació, unitat, tara del pot, «es pot regalar», «no s'apliquen descomptes»; llistes per tipus amb filtre d'estat; esborrar només la gerència) · Existències i moviments (magatzem i dispensari, avís d'estoc baix, entrada/moviment/sortida amb historial) · Inventaris (dispensari amb tara, magatzem, no genètics; complet o d'un sol producte; es guarda amb «Guardar» sense tocar l'estoc; Resultats amb avisos de diferència gran per a la gerència, que pot ajustar l'estoc) · Historial (gerència, amb dates).
- **Càmeres**: imatge en directe de càmeres IP (RTSP) via `ffmpeg`, per a la gerència o amb el permís «Veure les càmeres en directe»; s'afegeixen a Configuració › Càmeres (adreça xifrada, només xarxa privada o Tailscale). Vegeu `docs/CAMERES.md`.
- **Configuració** agrupa: Local i límits · Quotes · Normes del club (inclou l'avís d'estoc baix i els dies d'inactivitat) · Usuaris · Bàscules · Tauletes · Carnets · Diagnòstic · Seguretat · Estoc avançat (magatzems, categories, descomptes, línies de preu, contenidors, regles) · Despeses i comptabilitat · Controls del club · Privacitat.

A l'escriptori hi ha una barra lateral; al mòbil i a la tauleta, pestanyes a baix. Mode fosc automàtic.

## Dispositius (Configuració)

Cada local té **perfils** de dispositius guardats al servidor, i la tauleta fa servir el perfil per defecte:

- **Bàscules**: velocitat, bits de dades, paritat, bits de parada, control de flux, ordres de lectura, tara, zero i unitat; amb panell de prova (connecta, llegeix pes, envia ordres i mostra la comunicació en cru) que fa servir el formulari encara que no l'hagis desat.
- **Tauletes de signatura**: mida del llenç, color i gruix del traç, sensibilitat a la pressió del llapis i traços mínims. Serveix per a pantalla tàctil, llapis o qualsevol tauleta que actuï com a ratolí o llapis. *Les tauletes que exigeixen el SDK propi del fabricant (p. ex. Wacom STU) no es poden fer servir directament des del navegador.*
- **Carnets i lectors**: perfil del lector (USB com a teclat o NFC, terminador, prefix, longitud mínima) i **creador de carnets**: genera un codi únic amb dígit de control, el mostra una sola vegada, imprimeix una targeta amb foto, nom i **codi de barres Code 128** i, a Chrome per a Android amb HTTPS, el grava en una etiqueta NFC.

Producció i manteniment: `docs/PRODUCCIO.md`.

## Què fa

- **Socis**: alta amb signatura manuscrita en pantalla, validació de document (DNI/NIE amb lletra de control, o passaport), majoria d'edat i duplicats; edició de dades; estat (actiu / suspès / baixa); llistat amb filtre; foto (xifrada, amb historial); carnet RFID o de barres (només es desa l'empremta HMAC del codi); cerca per document o passant el carnet pel lector; registre d'entrades.
- **Quotes**: cobrament de la quota d'un soci (entra a la caixa oberta), estat «al dia», historial i anul·lació corregint l'apunt de caixa. Per local es pot fixar un import i durada per defecte i **exigir la quota al dia per poder dispensar** (Admin → Quotes).
- **Productes i estoc**: catàleg amb preu per gram (es pot editar; el canvi només afecta les dispensacions noves), desactivar/reactivar productes (cal estoc zero), entrades, merma, ajust d'inventari, dispensacions amb límit diari i mensual per soci i tolerància de bàscula.
- **Caixa**: obertura i tancament amb quadrament i diferència, cobraments, despeses, historial d'apunts i correccions.
- **Personal**: fitxatge d'entrada, sortida i pauses; hores treballades.
- **Informes** (amb exportació a CSV, que queda a l'auditoria): caixa, vendes per producte i categoria, dispensacions (amb miniatura, indicador de producte genètic, cercador i filtre per empleat), evolució del club (altes, baixes, quotes noves i renovacions per mes), demografia (franges d'edat, sense dades personals), estoc valorat, assistència de socis i hores del personal. A la fitxa del soci, historial de consum.
- **Descomptes**: percentatge o import per gram, per a tot, una categoria o un producte, amb dates de vigència; l'import original i el descomptat queden registrats a la dispensació.
- **Línies de preu**: llistes de preus per gram alternatives (p. ex. «VIP») que s'assignen a cada soci; un producte sense preu a la línia es cobra al preu base.
- **Regles**: límit de grams per soci i període (dia, setmana o mes) per a tot el catàleg, una categoria o un producte; es comproven en dispensar i les correccions alliberen gramatge.
- **Inventari**: recompte guiat producte a producte; en tancar, l'estoc s'ajusta a la quantitat comptada en una sola transacció.
- **Magatzems**: el principal és on es dispensa; els altres guarden estoc que es mou amb traspassos atòmics.
- **Contenidors**: tipus amb tara i contenidors amb codi, producte i pes brut/net.
- **Perfil del soci**: tipus de membre, gènere, adreça (xifrats), codi curt visible (p. ex. `PP12`), descompte permanent (%), documents (foto del document, contracte signat; xifrats i esborrables), incidències (text xifrat), avalats i contracte descarregable en HTML imprimible.
- **Cobrament**: efectiu, targeta, Bizum i **monedero** (saldo prepagat: es recarrega a la caixa, límit negatiu per local o per empleat; gastar-ne no es compta com a ingrés nou), dispensació com a **regal** (productes regalables) i **devolució** atòmica (estoc, lot i caixa) amb permís propi.
- **Accés**: entrada i sortida de socis (manual, «Sortir-ne tots» i quiosc RFID que alterna entrada/sortida) i informe de visites.
- **Caixes registradores**: diverses caixes (Dispensari, Entrada…), una sessió oberta per caixa i per empleat, magatzem propi per caixa i resum de sessions (empleat, caixa, import anterior, totals per mètode, diferència).
- **Despeses i comptabilitat**: categories, tipus, tipus de compte (suma/resta) i comptes; la despesa pot sortir de la caixa (tot o res) i s'anul·la sense esborrar-la.
- **Estadístiques**: socis (edat i gènere amb protecció d'anonimat, nous per mes, top 10), dispensari i bar, finances (variacions, benefici mensual).
- **Normes del club i privilegis**: edat mínima, decimals de la dispensació, alerta d'inactivitat, pèrdua màxima d'inventari; privilegis d'empleat (devolucions, editar descomptes, límit del monedero); monedes.
- **Productes en unitats i categories**: unitat de venda (grams o unitats), dispensació a granel o només enters, icona i color per categoria.
- **Idiomes**: català, castellà i anglès (selector a la barra lateral).
- **Administració**: locals, usuaris (rol, locals amb accés, activar/desactivar, contrasenya nova, reinici del segon factor TOTP), límits per soci, canvi de la pròpia contrasenya (pestanya «Compte»), verificació de la cadena d'auditoria.
- **Seguretat**: dades personals xifrades camp a camp, contrasenyes Argon2id + TOTP, bloqueig temporal després de 5 intents fallits en 15 minuts (també en canviar la contrasenya), límits de mida a les dades de login, auditoria serialitzada a PostgreSQL perquè la cadena de hash no es bifurqui, auditoria encadenada per hash i només d'afegir, registre d'accessos a dades de socis, taules d'apunts només d'afegir (triggers a PostgreSQL) i rol de base de dades sense privilegis per a l'aplicació. Capçaleres: CSP estricta (`script-src 'self'`), `no-store` a l'API, `X-Frame-Options: DENY`. El token de sessió viu a `sessionStorage` i el service worker només desa l'estructura de l'app, mai respostes de l'API.

## Base de dades en producció

Dos rols de PostgreSQL:
- `club` (propietari): només per crear l'esquema, els triggers i el rol de l'aplicació. No s'usa en funcionament.
- `club_app`: el que fa servir l'aplicació (`CLUB_APP_DATABASE_URL`). No és superusuari ni propietari: a les taules d'apunts només té SELECT i INSERT, i no pot desactivar triggers, canviar ni esborrar taules.

Preparació (un cop): `cd backend && CLUB_DATABASE_URL=<url del propietari> ../.venv/bin/python -m app.cli preparar-bd ../.env`
Arrencada: `CLUB_DATABASE_URL=$CLUB_APP_DATABASE_URL uvicorn --factory app.main:create_app ...`

## Actualitzar el programa

Cada versió pot afegir taules noves. **Després d'actualitzar el codi i abans de reiniciar el servei**, amb l'usuari propietari:

    cd backend && CLUB_DATABASE_URL=<url del propietari> ../.venv/bin/python -m app.cli actualitzar-bd

Crea les taules, les columnes noves (amb valor per defecte), els índexs i els triggers que falten i dona al rol `club_app` els permisos justos. No toca dades ni contrasenyes i es pot repetir. Si te n'oblides, l'aplicació no arrenca i ho diu clarament («Falten taules a la base de dades…») en comptes de donar errors a mig servei.

Si algú bloqueja un usuari a posta amb intents fallits (és temporal, 15 minuts), es pot treure al moment amb l'usuari propietari:

    cd backend && CLUB_DATABASE_URL=<url> ../.venv/bin/python -m app.cli desbloquejar <usuari>

**Fotos i dret de supressió**: les fotos són d'«només afegir» (com les signatures), amb un màxim de 20 per soci. Per esborrar-ne una (p. ex. a petició del soci) cal fer-ho a mà amb el rol propietari de PostgreSQL, desactivant temporalment el trigger `member_photos_no_change`, i deixar-ho anotat.

Les còpies de seguretat estan descrites a `docs/COPIES.md`.

## Proves

Suite completa amb PostgreSQL real, **una sola ordre** (usa `pgserver` incrustat si hi és, o Docker; no cal tocar `requirements.txt`):

    .venv/bin/python -m pip install pgserver       # un cop (alternativa: tenir Docker)
    .venv/bin/python scripts/test-pg.py            # accepta arguments de pytest: ... scripts/test-pg.py -k carnet

Alternatives manuals:

    docker compose --profile test up -d db-test    # PostgreSQL temporal a 127.0.0.1:5434
    export CLUB_TEST_PG_URL=postgresql+psycopg://club:club-test@127.0.0.1:5434/club
    cd backend && ../.venv/bin/python -m pytest -q -rs

Sense `CLUB_TEST_PG_URL` es fa servir SQLite i les proves específiques de PostgreSQL (triggers d'«només d'afegir», permisos del rol sense privilegis, actualització de la base de dades) es salten. El rol de la URL ha de poder crear esquemes i rols (superusuari de proves).
Front: `cd frontend && node --test test/`. El nombre de proves no es fixa aquí: **vegeu l'última execució de la CI** (`.github/workflows/ci.yml`, que corre amb PostgreSQL i no admet proves saltades sense avís: `-rs`).

## Instal·lació reproduïble i CI

`pip install --require-hashes -r requirements.lock` instal·la exactament les versions i hashes provats (Linux, macOS i Windows). Es regenera amb `scripts/update-lock.sh`.
La CI executa les proves, `pip-audit`, `node --test` i `shellcheck`.

## Bàscula OHAUS

`frontend/bascula.js` parla amb la bàscula per port sèrie (Web Serial): ordres `IP` (pes ara), `T` (tara), `Z` (zero); llegeix fins que el pes és estable (sense «?»).

**No s'ha provat amb cap bàscula real ni es pot garantir que funcioni amb tots els models d'OHAUS.** A Admin → «Bàscula (perfil i diagnòstic)» es pot veure què envia el dispositiu i ajustar velocitat i ordres (per defecte prova `IP`, `P` i `SP`); el perfil es desa al navegador. Només cobreix dispositius per port sèrie o USB virtual (no Ethernet/Bluetooth). Requisits: Chrome o Edge, i un context segur (HTTPS o `localhost`). Per una tauleta a la xarxa privada cal servir l'app per HTTPS (per exemple amb `tailscale serve`), perquè amb `http://` el navegador amaga l'API de ports sèrie. La unitat de la bàscula ha de ser grams (o mg, kg, oz, lb, ct).
El servidor ja valida la tolerància entre el pes de la bàscula i la quantitat dispensada (Admin → límits).

## Carnets (RFID / codi de barres)

Els lectors USB funcionen com un teclat: «escriuen» el codi i prem Intro. Per assignar un carnet: obre la fitxa del soci → Carnet → passa el carnet pel lector. Per identificar un soci: a Socis o Dispensar, posa el cursor al camp «o carnet» i passa el carnet. El codi ha de tenir 4 a 64 caràcters (lletres, xifres i `: _ . / -`). No es desa el codi, només una empremta HMAC; si es perd la `CLUB_INDEX_KEY`, cal tornar a assignar els carnets.

## Estat respecte als requisits

Tots els apartats de `REQUISITS.md` estan implementats. El que no es pot garantir encara:
- **Maquinari real**: la bàscula OHAUS no s'ha provat amb cap dispositiu; el lector de carnets s'ha provat com a teclat simulat; el pad de signatura és el llenç tàctil de la pantalla.
- **Bloqueig de login**: protegeix contra endevinar contrasenyes, però algú que conegui un nom d'usuari pot bloquejar-lo 15 minuts amb intents fallits; en una xarxa privada (Tailscale) es considera un risc acceptable.
- **Producció**: hi ha un servidor de PROVES desplegat amb `scripts/deploy.sh` (accés públic, segon factor desactivat). Cap club real l'usa encara; el club real anirà només per Tailscale (`docs/PRODUCCIO.md` § 0). Actualitza amb «Actualitzar el programa».
