# Més que un Club

(Nom tècnic del projecte: `club-gestio`.)

Programa propi de gestió d'un club (socis, estoc, caixa, personal, multi-local). Els requisits són a `REQUISITS.md`.
Backend FastAPI + SQLAlchemy (PostgreSQL en producció, SQLite per a proves) i una PWA sense dependències a `frontend/`.

Secrets: `CLUB_FIELD_KEY`, `CLUB_INDEX_KEY` i `CLUB_DB_PASSWORD` van a `.env` (fora de git). No s'exposa a Internet; només per Tailscale.

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

Una pantalla = una àrea de treball, i dins de cada àrea cada **subpantalla fa una sola tasca**:

- **Dispensar**: identificar el soci → producte i quantitat → cobrar.
- **Socis**: Cercar · Llista · Alta de soci.
- **Estoc**: Existències · Moviments · Productes · Descomptes · Línies de preu · Regles · Inventari · Magatzems · Contenidors · Tipus de contenidor · Historial. A la barra lateral es desplega amb una entrada per cada subpantalla.
- **Caixa**: Estat · Despesa · Apunts · Tancament.
- **Fitxatge** · **Informes** (Vendes · Dispensacions · Evolució del club · Demografia · Caixa · Estoc valorat · Assistència · Hores) · **Compte**.
- **Configuració** (administrador; l'encarregat hi veu Carnets i lectors i Diagnòstic): Local i límits · Quotes · Usuaris · **Bàscules** · **Tauletes de signatura** · **Carnets i lectors** · Diagnòstic · Seguretat.

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

    cd backend && ../.venv/bin/python -m pytest -q            # SQLite: algunes proves es salten
    cd frontend && node --test test/bascula.test.js           # protocol de la bàscula amb una bàscula simulada

Les proves de PostgreSQL (triggers d'«només d'afegir», permisos del rol sense privilegis, actualització de la base de dades) necessiten un PostgreSQL i la variable `CLUB_TEST_PG_URL`:

    CLUB_TEST_PG_URL=postgresql+psycopg://club:...@127.0.0.1:5433/club pytest

Sense Docker, a la màquina de desenvolupament es pot fer servir un PostgreSQL incrustat (paquet `pgserver`, no cal afegir-lo a `requirements.txt`):

    .venv/bin/python -m pip install pgserver
    .venv/bin/python -c "import pgserver; s = pgserver.get_server('/tmp/pgdata', cleanup_mode=None); print(s.get_uri())"
    # la URI que mostra (postgresql://postgres:@127.0.0.1:PORT/postgres) serveix canviant el prefix per postgresql+psycopg://

Amb PostgreSQL les proves es passen totes (228 de 228, cap saltada).

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
- **Producció**: no s'ha desplegat cap versió nova a un servidor real des d'aquest repositori; segueix el procediment «Actualitzar el programa».
