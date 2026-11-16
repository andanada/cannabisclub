# Còpies de seguretat i recuperació

## Model de seguretat

| Peça | Què és | On viu |
|---|---|---|
| Volcat `club-AAAAMMDD-HHMMSS.dump.gpg` | `pg_dump` xifrat a la **clau A** (destinatari) i signat per la **clau de la torre** | torre + **remot obligatori** |
| Paquet de claus `club-keys-*.keys.gpg` | `CLUB_FIELD_KEY` i `CLUB_INDEX_KEY`, xifrat a la **clau B** (diferent d'A) | torre + un lloc de custòdia diferent del remot dels volcats |
| Clau privada A | desxifra volcats | **fora de la torre** (persona 1) |
| Clau privada B | desxifra el paquet de claus | **fora de la torre**, en un lloc i amb una persona diferents (persona 2) |
| Clau de signatura de la torre | signa cada còpia (sense contrasenya, a la torre) | torre; l'**empremta** es guarda fora (`CLUB_BACKUP_SIGNER_FPR`) |

Per què separat: qui robi el volcat no té les claus de camp, i qui robi les claus no té les dades. Per llegir dades personals calen A **i** B.
El volcat ja porta els camps personals xifrats amb `CLUB_FIELD_KEY`: hi ha doble capa. El volcat mai toca el disc en clar (`pg_dump | gpg`)
i la restauració de prova tampoc (`gpg | pg_restore`).

**Una única font de claus al servidor**: `CLUB_FIELD_KEY`/`CLUB_INDEX_KEY` viuen només a `~/.config/club-gestio/app.env`
(mode 600). El `.env` del repositori no les ha de duplicar (només la contrasenya del propietari fins a `preparar-bd`; després, esborra-les d'allà).
`club-backup.sh` llegeix les claus d'`CLUB_KEYS_FILE` (per defecte `CLUB_ENV_FILE`); apunta-hi: `CLUB_KEYS_FILE=$HOME/.config/club-gestio/app.env`.

La signatura no protegeix d'algú que ja sigui a la torre (té la clau de signatura); protegeix que algú que manipuli el **remot**
o un suport extern no pugui substituir una còpia per una altra sense que ho detecti `restore-test`.

## Preparació (un cop)

1. Al TEU ordinador (no a la torre) genera **dues** claus de xifrat (A i B) amb contrasenya: `gpg --full-generate-key` (RSA 3072+). Exporta les públiques: `gpg --armor --export <id> > A-publica.asc`.
2. Guarda cada **clau privada** (`gpg --armor --export-secret-keys <id>`) amb còpia: A en un gestor de contrasenyes/paper de la persona 1; B en un lloc físicament i personalment diferent (persona 2, caixa forta). Apunta la contrasenya de cada clau en un lloc diferent de la clau.
3. A la torre: `gpg --import A-publica.asc B-publica.asc` i marca-les fiables (`gpg --edit-key <id> trust`).
4. A la torre, genera la clau de signatura (sense contrasenya, només per signar): `gpg --batch --passphrase '' --quick-generate-key torre-club@local ed25519 sign 5y`.
   Apunta la seva empremta (`gpg --fingerprint torre-club@local`) i guarda-la **fora de la torre** (és el que s'exigeix a la restauració).
   Exporta també la **clau pública** de signatura i guarda-la amb l'empremta: `gpg --armor --export torre-club@local > torre-signatura-publica.asc`.
   Sense ella, si la torre mor, `restore-test` no pot comprovar cap signatura (i una còpia que no passa no s'ha de restaurar).
5. `~/.config/club-gestio/backup.env`:

        CLUB_BACKUP_GPG_RECIPIENT=<id clau A>
        CLUB_BACKUP_KEYS_RECIPIENT=<id clau B>
        CLUB_BACKUP_SIGNER=torre-club@local
        CLUB_KEYS_FILE=/home/<usuari>/.config/club-gestio/app.env
        CLUB_BACKUP_REMOTE=usuari@hostremot:/ruta/volcats          # OBLIGATORI (vegeu sota)
        CLUB_BACKUP_KEYS_REMOTE=usuari@altrehost:/ruta/claus       # recomanat: un lloc diferent del dels volcats

6. Prova: `scripts/club-backup.sh run`. Activa-ho: `cp scripts/systemd/club-*.{service,timer} scripts/systemd/club-alert@.service ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable --now club-backup.timer club-monitor.timer club-audit.timer`.
7. El remot ha de ser **només d'afegir** per a la torre si pot ser (usuari amb `rsync` restringit, o còpies amb instantànies al destí): si la torre és compromesa, no hauria de poder esborrar les còpies externes. La retenció remota la fa la torre amb `ssh rm`; si vols un remot immutable, desactiva-la i fes la retenció des del remot.

## Variables

| Variable | Per defecte | Significat |
|---|---|---|
| `CLUB_BACKUP_REMOTE` | — | `usuari@host:/ruta` (rsync/ssh) o ruta local muntada. **Obligatòria** |
| `CLUB_BACKUP_ALLOW_LOCAL_ONLY` | `0` | `1` accepta no tenir remot (el script avisa; no recomanat) |
| `CLUB_BACKUP_GPG_RECIPIENT` / `CLUB_BACKUP_KEYS_RECIPIENT` | — | claus públiques A i B (han de ser diferents) |
| `CLUB_BACKUP_SIGNER` | — | clau secreta de signatura de la torre (obligatòria llevat de `CLUB_BACKUP_ALLOW_UNSIGNED=1`) |
| `CLUB_BACKUP_SIGNER_FPR` | — | empremta esperada; **obligatòria** a `restore-test` |
| `CLUB_BACKUP_KEEP_DAILY` / `_WEEKLY` / `_MONTHLY` | 14 / 8 / 12 | retenció per capes, local i remota |
| `CLUB_BACKUP_DIR` | `/data/backups/club` | carpeta local |
| `CLUB_DB_CONTAINER`, `CLUB_DB_NAME` | `club-gestio-db-1`, `club` | contenidor i base de dades |
| `CLUB_BACKUP_DB_USER` | `POSTGRES_USER` del contenidor | rol amb què es fa el `pg_dump`. Ha de ser el **propietari** de la base de dades, **no** el rol de l'aplicació: aquest no pot llegir `club_retencio_cfg` ni `club_buida_log` (REVOKE ALL a propòsit) i el volcat fallaria. Va pel socket local de dins del contenidor (`trust` a la imatge oficial), sense contrasenya |
| `CLUB_ENV_FILE`, `CLUB_KEYS_FILE`, `CLUB_PYTHON` | `.env` del repo, = `CLUB_ENV_FILE`, `.venv/bin/python` | rutes |
| `CLUB_RESTORE_IMAGE` | `postgres:17` | imatge de la restauració de prova |

Ancoratge de l'auditoria: després de cada còpia, `club-backup.sh run` desa `club-….dump.gpg.anchor` (`seq:hash`, `python -m app.audit_cli ancora`) al costat de la còpia i al remot, amb la mateixa retenció. No és secret però sí la prova que ningú no ha retallat la cadena: en restaurar, verifica-la amb `python -m app.cli verificar-auditoria "$(cat el-fitxer.anchor)"`. Cal l'entorn del servei (`CLUB_APP_DATABASE_URL` i les claus) a `CLUB_ENV_FILE`; si falla, la còpia continua i el script avisa.

Retenció per capes: es conserva la còpia més recent de cada un dels últims 14 dies, 8 setmanes ISO i 12 mesos amb còpia.
`scripts/club-backup.sh prune` l'aplica sense fer còpia.

## RPO i RTO

- **RPO** (dades que es poden perdre): fins a ~24 h amb el temporitzador diari (03:30). Per reduir-lo, afegeix un segon `OnCalendar` o executa `club-backup.sh run` abans de canvis grans. No hi ha arxivat WAL: el que passi entre còpies es perd.
- **RTO** objectiu: 2-4 h amb el material de custòdia a mà (vegeu el procediment).
- L'alerta salta si la darrera còpia correcta té més de 26 h (`club-monitor`).

## Restaurar i comprovar (al teu ordinador, amb la clau privada A)

    export CLUB_BACKUP_SIGNER_FPR=<empremta guardada fora de la torre>
    export CLUB_KEYS_FILE=<fitxer amb CLUB_INDEX_KEY (i CLUB_FIELD_KEY) del paquet de claus desxifrat amb la clau B>
    scripts/club-backup.sh restore-test club-AAAAMMDD-HHMMSS.dump.gpg

Exigeix el `.sha256` al costat, comprova que la signatura és de l'empremta esperada, restaura en un PostgreSQL temporal (Docker) i verifica la cadena d'auditoria.
La cadena d'auditoria porta HMAC: sense `CLUB_INDEX_KEY` (o `CLUB_AUDIT_KEY`) a `CLUB_KEYS_FILE`, `restore-test` s'atura amb un missatge i no pot verificar-la. Per això una recuperació necessita **A i B**.

Prova de cicle complet (còpia, xifratge, signatura, restauració, manipulació, clau equivocada, retenció) amb claus i PostgreSQL temporals, sense tocar res real: `scripts/test-backup.sh` (cal Docker, `gpg` i el `.venv` del projecte).
**Fes-ho cada mes** i després de canviar de claus: una còpia que mai s'ha restaurat no és una còpia.
Cal copiar a l'ordinador el volcat des del **remot** (no de la torre): és la còpia que sobreviu a la torre.

## Recuperar una torre morta (procediment complet)

Material de custòdia necessari (tot fora de la torre): clau privada A (+ contrasenya), clau privada B (+ contrasenya), empremta **i clau pública** de signatura (`torre-signatura-publica.asc`), accés al remot de volcats i al de claus, i còpia de `app.env` si no el tens al paquet de claus.

1. **Maquinari/SO nou.** Instal·la Linux, Docker, Python 3.12, nginx, Tailscale/xarxa. Clona el repositori a `/data/repos/club-gestio`; `python3 -m venv .venv && .venv/bin/pip install --require-hashes -r requirements.lock`.
2. **Recupera les claus de camp.** En un ordinador de confiança (no a la torre nova encara) importa la clau B i desxifra: `gpg --decrypt club-keys-XXXX.keys.gpg` → `CLUB_FIELD_KEY=`, `CLUB_INDEX_KEY=` i, si es feien servir, `CLUB_AUDIT_KEY=` i `CLUB_AUDIT_HMAC_DES_DE=`. Crea `~/.config/club-gestio/app.env` (mode 600) amb elles. **Sense `CLUB_FIELD_KEY` les dades personals són irrecuperables; sense `CLUB_INDEX_KEY` es perden cerques per document, PIN i carnets (cal reassignar-los).**
3. **Tria el volcat.** Baixa del remot el més recent (`club-*.dump.gpg` + `.sha256`). Importa la clau pública de signatura (`gpg --import torre-signatura-publica.asc`) i fes `restore-test` al teu ordinador: confirma hash, signatura i auditoria. Si falla, prova el volcat anterior; no restauris mai una còpia que no passi.
4. **PostgreSQL nou.** `docker compose up -d db` (amb `CLUB_DB_PASSWORD` nova al `.env`).
5. **Restaura.** `gpg --decrypt club-XXXX.dump.gpg | docker exec -i club-gestio-db-1 pg_restore -U club -d club --no-owner --no-privileges --exit-on-error` (BD buida). `--no-privileges` és imprescindible: el volcat porta els permisos del rol `club_app`, que encara no existeix (es crea al pas 6, que torna a donar els permisos); sense l'opció, `pg_restore` s'atura amb «role club_app does not exist».
6. **Rol i permisos.** `cd backend && CLUB_DATABASE_URL=<propietari> ../.venv/bin/python -m app.cli preparar-bd ../.env` (crea `club_app` amb contrasenya nova) i, per assegurar triggers/permisos, `actualitzar-bd`. Passa `CLUB_APP_DATABASE_URL` a `app.env` i esborra-la del `.env`.
7. **Servei.** Instal·la `club-gestio.service` (+ nginx de `scripts/nginx/`, certificat) i arrenca. Comprova `GET /salut`, entra, i **Configuració → Seguretat → Verificar auditoria**.
8. **Còpies de nou.** Genera una clau de signatura NOVA, importa A i B públiques, actualitza `backup.env`, **actualitza l'empremta de custòdia**, executa `club-backup.sh run` i `restore-test`. Reactiva els timers.
9. **Registra l'incident** (data, causa, còpia usada, dades perdudes = RPO real). Si la torre pot haver estat compromesa, segueix `docs/PRODUCCIO.md` § «Violació de seguretat».

## Custòdia de claus (fora del servidor)

- Mai a la torre: claus privades A i B, i la seva contrasenya.
- Dues persones diferents, un suport per persona, amb una còpia de reserva cada una (sobre tancat, caixa forta o gestor de contrasenyes amb 2FA). Document amb «qui té què» guardat al marge de les claus.
- Revisió anual: es pot desxifrar amb el material guardat? Prova real amb `restore-test` i el paquet de claus.
- Si una persona marxa o perd una clau: genera un parell nou, actualitza `backup.env`, fes una còpia nova i guarda la nova; les antigues continuen sent llegibles amb la clau antiga (conserva-la mentre quedin còpies xifrades per a ella).

## Rotació de claus FIELD / INDEX: límit conegut

**No hi ha rotació automàtica de `CLUB_FIELD_KEY` ni de `CLUB_INDEX_KEY`.** Canviar-les sense migrar fa il·legibles les dades existents
(i invalida els hash de document, PIN i carnets). Una rotació requeriria una ordre nova a `app.cli` que reencripti camp a camp en una transacció
(llegir amb la clau vella, escriure amb la nova) i recalculi els índexs; **no existeix**. Fins llavors: si es sospita que `CLUB_FIELD_KEY` s'ha filtrat,
es considera una violació de seguretat de dades (vegeu PRODUCCIO.md) i s'ha de dissenyar la migració abans de rotar. Cada paquet de claus antic es conserva mentre hi hagi volcats que en depenguin.

## Alertes

Vegeu `docs/PRODUCCIO.md` § Monitoratge. `club-backup.service` té `OnFailure=club-alert@%n.service`, que avisa per `CLUB_ALERT_CMD` si la còpia falla.

## Prova automàtica

`scripts/test-backup.sh` (cal Docker i GPG): remot obligatori, còpia, absència de dades i claus en clar, claus a part, restauració amb signatura,
empremta equivocada, falta de `.sha256`, còpia alterada, impossibilitat de desxifrar sense la privada i retenció local i remota.
