"""Perfils de dispositius per local: bàscules, tauletes de signatura i lectors de carnets.
La configuració es valida de manera estricta: un perfil no pot portar res fora de la llista (ordres, colors, mides…)."""
import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import service
from .models import DeviceProfile, User

KINDS = {"bascula", "signatura", "lector"}
_ORDRE = re.compile(r"[A-Za-z0-9?_ ]{1,10}")
_COLOR = re.compile(r"#[0-9a-fA-F]{6}")
_PREFIX = re.compile(r"[A-Z0-9]{2,6}")


def _en(valor, permesos, nom):
    if valor not in permesos:
        raise ValueError(f"«{nom}» no és vàlid (permesos: {', '.join(map(str, permesos))})")
    return valor


def _rang(valor, lo, hi, nom):
    if isinstance(valor, bool) or not isinstance(valor, int) or not lo <= valor <= hi:
        raise ValueError(f"«{nom}» ha de ser un enter entre {lo} i {hi}")
    return valor


def _bool(valor, nom):
    if not isinstance(valor, bool):
        raise ValueError(f"«{nom}» ha de ser sí o no")
    return valor


def _ordre(valor, nom):
    if not isinstance(valor, str) or not _ORDRE.fullmatch(valor):
        raise ValueError(f"«{nom}»: ordre no vàlida (1 a 10 lletres, xifres, ? _ o espai)")
    return valor


def _bascula(c: dict) -> dict:
    ordres = c.get("read", ["IP", "P", "SP"])
    if not isinstance(ordres, list) or not 1 <= len(ordres) <= 8:
        raise ValueError("«read» ha de ser una llista d'1 a 8 ordres")
    return {
        "baud_rate": _en(c.get("baud_rate", 9600), [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200], "baud_rate"),
        "data_bits": _en(c.get("data_bits", 8), [7, 8], "data_bits"),
        "parity": _en(c.get("parity", "none"), ["none", "even", "odd"], "parity"),
        "stop_bits": _en(c.get("stop_bits", 1), [1, 2], "stop_bits"),
        "flow": _en(c.get("flow", "none"), ["none", "hardware"], "flow"),
        "read": [_ordre(o, "read") for o in ordres],
        "tare": _ordre(c.get("tare", "T"), "tare"),
        "zero": _ordre(c.get("zero", "Z"), "zero"),
        "unit": _en(c.get("unit", "g"), ["g", "mg", "kg", "oz", "lb", "ct"], "unit"),
    }


def _signatura(c: dict) -> dict:
    for k in ("color", "fons"):
        if k in c and not (isinstance(c[k], str) and _COLOR.fullmatch(c[k])):
            raise ValueError(f"«{k}» ha de ser un color #rrggbb")
    return {
        "mode": _en(c.get("mode", "llenc"), ["llenc"], "mode"),
        "amplada": _rang(c.get("amplada", 600), 300, 1200, "amplada"),
        "alcada": _rang(c.get("alcada", 220), 120, 600, "alcada"),
        "gruix": _rang(c.get("gruix", 3), 1, 8, "gruix"),
        "color": c.get("color", "#000000"),
        "fons": c.get("fons", "#ffffff"),
        "pressio": _bool(c.get("pressio", True), "pressio"),
        "tracos_min": _rang(c.get("tracos_min", 2), 1, 20, "tracos_min"),
    }


def _lector(c: dict) -> dict:
    prefix = c.get("prefix", "")
    if not isinstance(prefix, str) or len(prefix) > 8 or re.search(r"[^\x21-\x7e]", prefix):
        raise ValueError("«prefix» ha de tenir com a màxim 8 caràcters visibles")
    gen = c.get("prefix_generat", "CLB")
    if not isinstance(gen, str) or not _PREFIX.fullmatch(gen):
        raise ValueError("«prefix_generat» ha de tenir 2 a 6 lletres majúscules o xifres")
    return {
        "mode": _en(c.get("mode", "teclat"), ["teclat", "nfc"], "mode"),
        "terminador": _en(c.get("terminador", "enter"), ["enter", "tab", "cap"], "terminador"),
        "prefix": prefix,
        "longitud_min": _rang(c.get("longitud_min", 4), 4, 64, "longitud_min"),
        "majuscules": _bool(c.get("majuscules", True), "majuscules"),
        "prefix_generat": gen,
    }


_VALIDADORS = {"bascula": _bascula, "signatura": _signatura, "lector": _lector}
_CLAUS = {"bascula": {"baud_rate", "data_bits", "parity", "stop_bits", "flow", "read", "tare", "zero", "unit"},
          "signatura": {"mode", "amplada", "alcada", "gruix", "color", "fons", "pressio", "tracos_min"},
          "lector": {"mode", "terminador", "prefix", "longitud_min", "majuscules", "prefix_generat"}}


def validate(kind: str, config: dict) -> dict:
    """Retorna la configuració normalitzada (amb els valors per defecte) o llança ValueError."""
    if kind not in KINDS:
        raise ValueError("Tipus de dispositiu no vàlid (bascula, signatura o lector)")
    if not isinstance(config, dict):
        raise ValueError("La configuració ha de ser un objecte")
    sobren = set(config) - _CLAUS[kind]
    if sobren:
        raise ValueError(f"Camps desconeguts: {', '.join(sorted(sobren))}")
    return _VALIDADORS[kind](config)


def _nom(nom: str) -> str:
    nom = (nom or "").strip()
    if not 1 <= len(nom) <= 60:
        raise ValueError("El nom ha de tenir entre 1 i 60 caràcters")
    return nom


def _view(p: DeviceProfile) -> dict:
    return {"id": p.id, "local_id": p.local_id, "kind": p.kind, "nom": p.nom, "per_defecte": p.per_defecte, "config": json.loads(p.config)}


def list_profiles(db: Session, local_id: int, kind: str | None = None) -> list[dict]:
    q = select(DeviceProfile).where(DeviceProfile.local_id == local_id).order_by(DeviceProfile.kind, DeviceProfile.id)
    if kind:
        q = q.where(DeviceProfile.kind == kind)
    return [_view(p) for p in db.scalars(q)]


def _exclusiu(db: Session, p: DeviceProfile) -> None:
    for altre in db.scalars(select(DeviceProfile).where(DeviceProfile.local_id == p.local_id, DeviceProfile.kind == p.kind, DeviceProfile.id != p.id)):
        altre.per_defecte = False


def _nom_lliure(db: Session, local_id: int, kind: str, nom: str, excepte: int | None = None) -> None:
    q = select(DeviceProfile.id).where(DeviceProfile.local_id == local_id, DeviceProfile.kind == kind, DeviceProfile.nom == nom)
    if excepte:
        q = q.where(DeviceProfile.id != excepte)
    if db.scalar(q):
        raise ValueError("Ja existeix un dispositiu d'aquest tipus amb aquest nom en aquest local")


def create(db: Session, actor: User, local_id: int, kind: str, nom: str, config: dict, per_defecte: bool = False) -> DeviceProfile:
    cfg, nom = validate(kind, config), _nom(nom)
    _nom_lliure(db, local_id, kind, nom)
    primer = db.scalar(select(DeviceProfile.id).where(DeviceProfile.local_id == local_id, DeviceProfile.kind == kind)) is None
    p = DeviceProfile(local_id=local_id, kind=kind, nom=nom, config=json.dumps(cfg, sort_keys=True), per_defecte=per_defecte or primer)
    db.add(p)
    db.flush()
    if p.per_defecte:
        _exclusiu(db, p)
    service.audit_append(db, {"accio": "alta_dispositiu", "dispositiu": p.id, "kind": kind, "local": local_id, "per": actor.id})
    db.commit()
    return p


def update(db: Session, actor: User, p: DeviceProfile, nom: str | None, config: dict | None, per_defecte: bool | None) -> None:
    if nom is None and config is None and per_defecte is None:
        raise ValueError("No hi ha cap canvi")
    if nom is not None:
        p.nom = _nom(nom)
        _nom_lliure(db, p.local_id, p.kind, p.nom, p.id)
    if config is not None:
        p.config = json.dumps(validate(p.kind, config), sort_keys=True)
    if per_defecte is not None:
        p.per_defecte = per_defecte
        if per_defecte:
            _exclusiu(db, p)
    service.audit_append(db, {"accio": "edita_dispositiu", "dispositiu": p.id, "kind": p.kind, "per": actor.id})
    db.commit()


def delete(db: Session, actor: User, p: DeviceProfile) -> None:
    pid, kind, local_id = p.id, p.kind, p.local_id
    db.delete(p)
    db.flush()
    if not db.scalar(select(DeviceProfile.id).where(DeviceProfile.local_id == local_id, DeviceProfile.kind == kind, DeviceProfile.per_defecte.is_(True))):
        nou = db.scalar(select(DeviceProfile).where(DeviceProfile.local_id == local_id, DeviceProfile.kind == kind).order_by(DeviceProfile.id))
        if nou:
            nou.per_defecte = True  # sempre n'hi ha un de per defecte mentre en quedi algun
    service.audit_append(db, {"accio": "esborra_dispositiu", "dispositiu": pid, "kind": kind, "per": actor.id})
    db.commit()
