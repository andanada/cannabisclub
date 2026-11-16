"""Avisos de configuració insegura, que s'escriuen al registre cada vegada que arrenca el servei.

No bloquegen res (el servidor de proves funciona amb el segon factor desactivat a posta), però no poden passar desapercebuts:
si el `app.env` de proves arriba a producció, ha de quedar escrit a cada arrencada."""
import os

from . import carnet_login, security, service

XARXA_TAILSCALE = "100.64.0.0/10"


def configuracio() -> list[str]:
    a: list[str] = []
    if not service.totp_required():
        a.append("ATENCIÓ: CLUB_TOTP=0: el servidor NO demana el segon factor (codi de l'app d'autenticació); només contrasenya. "
                 "Només és per a proves, mai amb dades reals.")
    if not security.totp_replay_enabled():
        a.append("ATENCIÓ: CLUB_TOTP_REPLAY=0: un codi de l'app es pot reutilitzar dins la seva finestra. Només per a proves.")
    if carnet_login.enabled() and not os.environ.get("CLUB_CARNET_XARXES", "").strip():
        a.append(f"L'entrada amb carnet està activa sense restricció de xarxa (CLUB_CARNET_XARXES buit). Si el servei només es fa "
                 f"servir per Tailscale, defineix CLUB_CARNET_XARXES={XARXA_TAILSCALE}; si no s'usa el carnet, CLUB_LOGIN_CARNET=0.")
    return a
