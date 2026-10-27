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
