# Producció: llista de comprovació

Aquest document és per posar el programa en servei i mantenir-lo. Les còpies de seguretat són a `COPIES.md`.

## 1. Abans del primer ús

- [ ] Python 3.12+ amb `.venv` i `pip install -r requirements.txt` (sense `-dev`).
- [ ] PostgreSQL 16+ amb els dos rols (`club` propietari i `club_app` per a l'aplicació): `python -m app.cli preparar-bd ../.env`.
- [ ] `.env` amb permisos `600`: `CLUB_FIELD_KEY`, `CLUB_INDEX_KEY`, `CLUB_DB_PASSWORD`, `CLUB_APP_DATABASE_URL`. **Fes-ne una còpia fora del servidor**: sense `CLUB_FIELD_KEY` les dades personals no es poden desxifrar mai més, i sense `CLUB_INDEX_KEY` es perden les cerques per document i els carnets.
- [ ] Servei: `scripts/systemd/club-gestio.service` (ja porta `--no-access-log`: els accessos de uvicorn registrarien documents i codis de carnet a la URL).
- [ ] HTTPS: la bàscula (Web Serial) i la gravació NFC només funcionen en un context segur. Amb Tailscale: `tailscale serve --bg https / http://127.0.0.1:8099`. Posa `CLUB_HSTS=1` al servei un cop confirmis que tot va per HTTPS.
- [ ] Còpies xifrades programades (`scripts/systemd/club-backup.timer`) i **una restauració provada**.
- [ ] No obris el port 8099 a cap interfície pública: només `127.0.0.1` darrere de Tailscale.

### Segon factor (TOTP)

Per defecte l'inici de sessió exigeix usuari, contrasenya i codi de l'app d'autenticació. Només en un **servidor de proves** es pot desactivar amb `CLUB_TOTP=0` al fitxer d'entorn del servei (la pantalla d'entrada amaga el camp). **No el deixis així amb dades reals**: sense el segon factor, la contrasenya és l'única protecció. Per tornar-lo a activar, treu la línia i reinicia el servei.

### Primer arrencada

Una base de dades sense cap local mostra a l'administrador un formulari per crear-ne el primer. Un usuari que no és administrador i no té cap local assignat veu un missatge que ho explica.

## 2. Monitoratge

- `GET /salut` (sense autenticació): `200 {"ok": true}` si la base de dades respon, `503` si no. Fes-lo servir des d'un `cron` o del teu sistema de monitoratge.
- Logs: `journalctl -u club-gestio`. Cada petició surt com `MÈTODE /camí estat durada` **sense** la query string. Un error inesperat surt amb un `id` de 12 caràcters; el mateix `id` el veu l'usuari a la pantalla, així que amb ell es troba la traça. `CLUB_LOG_LEVEL=WARNING` redueix el soroll.
- Cada setmana: **Configuració → Seguretat → Verificar la integritat de l'auditoria**.

## 3. Actualitzar el programa

1. Còpia de seguretat de la base de dades.
2. Actualitza el codi i `pip install -r requirements.txt`.
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
