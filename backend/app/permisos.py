"""Permisos per usuari: la gerència (admin i encarregat) ho pot tot; a un treballador l'administrador li pot donar, un a un, privilegis
addicionals (veure informes, historial d'estoc, esborrar productes…). Es desen com a llista JSON a `users.permisos`.
El rol del dia (recepció o dispensari) continua decidint la feina del dia; els permisos s'hi afegeixen."""
import json

from sqlalchemy.orm import Session

from . import service
from .models import User

# (clau, etiqueta, grup)
CATALEG = [
    ("informes", "Veure informes i estadístiques", "Informes"),
    ("historial", "Veure l'historial de moviments d'estoc", "Estoc"),
    ("resultats_inventari", "Veure els resultats dels inventaris i ajustar l'estoc", "Estoc"),
    ("esborrar_productes", "Esborrar productes", "Estoc"),
    ("moviments_estoc", "Fer entrades, sortides (mermes) i traspassos d'estoc", "Estoc"),
    ("editar_preus", "Canviar preus i marcar productes com a regal o sense descomptes", "Estoc"),
    ("corregir_caixa", "Corregir apunts de caixa", "Caixa"),
    ("corregir_estoc", "Corregir moviments d'estoc", "Estoc"),
    ("gestio_socis", "Donar d'alta i editar socis (dades, estat, foto, carnet, documents)", "Socis"),
]
CLAUS = {c for c, _, _ in CATALEG}


def llegeix(u: User) -> list[str]:
    try:
        v = json.loads(getattr(u, "permisos", None) or "[]")
    except ValueError:
        return []
    return [c for c in v if c in CLAUS]


def te(u: User, clau: str) -> bool:
    """Gerència: sempre. Treballador: només si l'administrador li ho ha donat."""
    if u.role in ("admin", "encarregat"):
        return True
    return clau in llegeix(u)


def efectius(u: User) -> list[str]:
    """Permisos que té ara (la gerència els té tots): és el que rep la interfície per decidir què mostrar."""
    return sorted(CLAUS) if u.role in ("admin", "encarregat") else llegeix(u)


def assigna(db: Session, actor: User, u: User, claus: list[str]) -> list[str]:
    desconeguts = set(claus) - CLAUS
    if desconeguts:
        raise ValueError("Permís desconegut: " + ", ".join(sorted(desconeguts)))
    if u.role in ("admin", "encarregat"):
        raise ValueError("La gerència ja ho pot tot: els permisos són per als treballadors")
    nous = sorted(set(claus))
    anteriors = llegeix(u)
    u.permisos = json.dumps(nous)
    service.audit_append(db, {"accio": "permisos_usuari", "usuari": u.id, "de": anteriors, "a": nous, "per": actor.id})
    db.commit()
    return nous
