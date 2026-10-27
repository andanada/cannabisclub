# club-gestio

Programa propi de gestió d'un club (socis, estoc, caixa, personal, multi-local). Vegeu `REQUISITS.md`.

Estat: fase 1 (nucli de seguretat). Hi ha xifrat de camps, auditoria encadenada i contrasenyes/TOTP, amb proves.

    cd backend && ../.venv/bin/python -m pytest -q

Secrets: `CLUB_FIELD_KEY` i `CLUB_DB_PASSWORD` van a `.env` (fora de git). No s'exposa a Internet; només per Tailscale.

## Interfície

PWA sense dependències a `frontend/`, servida pel mateix backend (`/`). Pantalles: Dispensar, Socis, Estoc, Caixa, Fitxatge, Informe i Admin (segons el rol).
El token de sessió viu a `sessionStorage`; el service worker només desa l'estructura de l'app, mai respostes de l'API.
Capçaleres: CSP estricta (`script-src 'self'`), `no-store` a l'API, `X-Frame-Options: DENY`.

Arrencada (dev):

    export CLUB_FIELD_KEY=... CLUB_INDEX_KEY=... CLUB_DATABASE_URL=sqlite:///dev.db
    cd backend && ../.venv/bin/python -m app.cli crear-admin <usuari>
    ../.venv/bin/uvicorn --factory app.main:create_app --host 127.0.0.1 --port 8099

## Base de dades en producció

Dos rols de PostgreSQL:
- `club` (propietari): només per crear l'esquema, els triggers i el rol de l'aplicació. No s'usa en funcionament.
- `club_app`: el que fa servir l'aplicació (`CLUB_APP_DATABASE_URL`). No és superusuari ni propietari: a les taules d'apunts només té SELECT i INSERT,
  i no pot desactivar triggers, canviar ni esborrar taules.

Preparació (un cop): `cd backend && CLUB_DATABASE_URL=<url del propietari> ../.venv/bin/python -m app.cli preparar-bd ../.env`
Arrencada: `CLUB_DATABASE_URL=$CLUB_APP_DATABASE_URL uvicorn --factory app.main:create_app ...`

Proves contra PostgreSQL: `CLUB_TEST_PG_URL=postgresql+psycopg://club:...@127.0.0.1:5433/club pytest`

## Bàscula OHAUS

`frontend/bascula.js` parla amb la bàscula per port sèrie (Web Serial): ordres `IP` (pes ara), `T` (tara), `Z` (zero); llegeix fins que el pes és estable (sense «?»).
Proves de l'analitzador i del protocol amb una bàscula simulada: `cd frontend && node --test test/bascula.test.js`.

**No s'ha provat amb cap bàscula real.** Requisits: Chrome o Edge, i un context segur (HTTPS o `localhost`). Per una tauleta a la xarxa privada cal servir l'app per HTTPS
(per exemple amb `tailscale serve`), perquè amb `http://` el navegador amaga l'API de ports sèrie. La unitat de la bàscula ha de ser grams (o mg, kg, oz, lb, ct).
El servidor ja valida la tolerància entre el pes de la bàscula i la quantitat dispensada (Admin → límits).
