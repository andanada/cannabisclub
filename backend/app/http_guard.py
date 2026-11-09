"""Proteccions de la capa HTTP: mida màxima del cos de les peticions i fitxers estàtics permesos."""
import json
import os

from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

# El cos més gran legítim és la foto/signatura en base64 (≈ 400 KB). 1 MiB deixa marge i talla qualsevol abús.
MAX_BODY_BYTES = 1_048_576


def max_body_bytes() -> int:
    try:
        return int(os.environ.get("CLUB_MAX_BODY_BYTES", MAX_BODY_BYTES))
    except ValueError:
        return MAX_BODY_BYTES


class BodyLimitMiddleware:
    """Middleware ASGI pur: rebutja amb 413 un cos més gran que el límit, tant si ho declara Content-Length com si
    s'envia a trossos (chunked) i menteix o no declara la mida. No llegeix res a memòria més enllà del límit."""

    def __init__(self, app, limit: int | None = None):
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = self.limit or max_body_bytes()
        declarat = dict(scope["headers"]).get(b"content-length")
        if declarat is not None and declarat.isdigit() and int(declarat) > limit:
            return await self._rebutja(send)
        vist = 0
        passat = False
        enviat = False

        async def receive_limitat():
            nonlocal vist, passat
            if passat:
                return {"type": "http.disconnect"}
            msg = await receive()
            if msg["type"] == "http.request":
                vist += len(msg.get("body", b""))
                if vist > limit:
                    # L'aplicació veurà una desconnexió (FastAPI convertiria qualsevol excepció en un 400): la resposta
                    # que enviï s'ignora i el 413 el donem nosaltres.
                    passat = True
                    return {"type": "http.disconnect"}
            return msg

        async def send_vigilat(msg):
            nonlocal enviat
            if passat:
                return
            if msg["type"] == "http.response.start":
                enviat = True
            await send(msg)

        try:
            await self.app(scope, receive_limitat, send_vigilat)
        finally:
            if passat and not enviat:
                await self._rebutja(send)

    @staticmethod
    async def _rebutja(send):
        cos = json.dumps({"detail": "La petició és massa gran"}).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(cos)).encode()),
                                (b"connection", b"close")]})
        await send({"type": "http.response.body", "body": cos})


class FrontendFiles(StaticFiles):
    """Serveix el frontend però mai la carpeta de proves ni fitxers ocults."""
    BLOQUEJATS = {"test", "tests", "node_modules"}

    async def get_response(self, path, scope):
        parts = [p for p in path.replace("\\", "/").split("/") if p]
        if any(p in self.BLOQUEJATS or p.startswith(".") for p in parts) or (parts and parts[-1].endswith(".test.js")):
            raise StarletteHTTPException(status_code=404)
        return await super().get_response(path, scope)
