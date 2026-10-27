# club-gestio

Programa propi de gestió d'un club (socis, estoc, caixa, personal, multi-local). Vegeu `REQUISITS.md`.

Estat: fase 1 (nucli de seguretat). Hi ha xifrat de camps, auditoria encadenada i contrasenyes/TOTP, amb proves.

    cd backend && ../.venv/bin/python -m pytest -q

Secrets: `CLUB_FIELD_KEY` i `CLUB_DB_PASSWORD` van a `.env` (fora de git). No s'exposa a Internet; només per Tailscale.
