"""Menú del club: carta de productes per a tauletes i TV, connectada a l'estoc.

Els productes no es munten a mà: el menú «dispensari» mostra els productes genètics amb estoc i el «bar» els no genètics. Noms, categories
i preus surten del producte (preu per gram o per unitat actual); si s'acaba l'estoc desapareix sol (o surt com a esgotat) i quan torna, torna.
Mai no hi surt cap dada de socis ni l'estoc exacte."""
import hashlib
import json
import re
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crypto, service, stock
from .models import Menu, MenuScreen, Product, User

TIPUS_MENU = ("dispensari", "bar")
TIPUS_PANTALLA = ("tauleta", "tv")
NOMS_DEFECTE = {"dispensari": "Dispensari", "bar": "Bar"}
MAX_IMG = 700_000   # caràcters d'una imatge en data URL
COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
IMG = re.compile(r"^data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+$")
OBLIG = "categories"

DISSENY_DEFECTE = {
    "tema": "fosc", "fons_tipus": "degradat", "color_fons": "#0f1a14", "color_fons2": "#1d3a2a", "color_text": "#f5f7f4",
    "color_accent": "#7bd88f", "logo": "club", "mida": 3, "columnes": 2, "orientacio": "h", "rotacio": 15,
    "mostrar_esgotats": False, "mostrar_preus": True, "trams": [1, 5, 10], "titol": "",
    "categories": None,   # llista ordenada [{"nom", "visible"}]; None = totes, en ordre per defecte
    "ocults": [],         # ids de productes amagats expressament
}


def categories_de(tipus: str) -> tuple[str, ...]:
    return stock.CATEGORIES[tipus == "dispensari"]


def neteja_disseny(d: dict | None, tipus: str, base: dict | None = None) -> dict:
    """Valida i normalitza un disseny: tot el que no és vàlid es descarta o es limita (mai no falla per un valor estrany)."""
    d = d if isinstance(d, dict) else {}
    o = {**DISSENY_DEFECTE, **(base or {})}
    for k in ("color_fons", "color_fons2", "color_text", "color_accent"):
        if isinstance(d.get(k), str) and COLOR.match(d[k]):
            o[k] = d[k].lower()
    for k, ok in (("tema", None), ("fons_tipus", ("color", "degradat", "imatge")), ("logo", ("club", "propi", "cap")), ("orientacio", ("h", "v"))):
        v = d.get(k)
        if isinstance(v, str) and (ok is None and re.fullmatch(r"[a-z0-9_-]{1,20}", v) or ok and v in ok):
            o[k] = v
    for k, lo, hi in (("mida", 1, 5), ("columnes", 1, 4), ("rotacio", 5, 120)):
        if isinstance(d.get(k), int) and not isinstance(d.get(k), bool):
            o[k] = max(lo, min(hi, d[k]))
    for k in ("mostrar_esgotats", "mostrar_preus"):
        if isinstance(d.get(k), bool):
            o[k] = d[k]
    if isinstance(d.get("titol"), str):
        o["titol"] = d["titol"].strip()[:60]
    if isinstance(d.get("trams"), list):
        t = [int(x) for x in d["trams"] if isinstance(x, int) and not isinstance(x, bool) and 1 <= x <= 1000][:4]
        o["trams"] = sorted(set(t)) or [1]
    if "categories" in d:
        o["categories"] = _categories(d["categories"], tipus)
    if isinstance(d.get("ocults"), list):
        o["ocults"] = sorted({int(x) for x in d["ocults"] if isinstance(x, int) and not isinstance(x, bool)})[:2000]
    return o


def _categories(v, tipus: str):
    if v is None:
        return None
    valides = set(categories_de(tipus)) | {"Altres"}
    out, vistes = [], set()
    for c in v if isinstance(v, list) else []:
        nom = c.get("nom") if isinstance(c, dict) else None
        if nom in valides and nom not in vistes:
            vistes.add(nom)
            out.append({"nom": nom, "visible": bool(c.get("visible", True))})
    return out


def disseny_publicat(m: Menu) -> dict:
    try:
        return neteja_disseny(json.loads(m.disseny or "{}"), m.tipus)
    except ValueError:
        return neteja_disseny({}, m.tipus)


def esborrany_de(m: Menu) -> dict | None:
    try:
        return json.loads(m.esborrany) if m.esborrany else None
    except ValueError:
        return None


def neteja_imatge(v) -> str | None:
    if v is None or v == "":
        return None
    if not isinstance(v, str) or len(v) > MAX_IMG or not IMG.match(v):
        raise ValueError("Imatge no vàlida (JPEG, PNG o WebP, màxim ~500 KB)")
    return v


# ---------- dades que veu la pantalla ----------

def _cat_ordre(cfg: dict, tipus: str) -> list[dict]:
    """Categories amb el seu ordre: les configurades primer; les que falten (noves) al final, visibles."""
    conf = cfg.get("categories")
    per_defecte = [*categories_de(tipus), "Altres"]
    if conf is None:
        return [{"nom": n, "visible": True} for n in per_defecte]
    vistes = {c["nom"] for c in conf}
    return [*conf, *[{"nom": n, "visible": True} for n in per_defecte if n not in vistes]]


def _fmt_g(g: int) -> str:
    return f"{g} g"


def vista(db: Session, m: Menu, cfg: dict, imatges: dict | None = None) -> dict:
    """Carta calculada ara mateix. `cfg` és el disseny (publicat o esborrany). Només productes del local, actius, del tipus del menú."""
    genetic = m.tipus == "dispensari"
    prods = list(db.scalars(select(Product).where(Product.local_id == m.local_id, Product.actiu.is_(True), Product.es_genetic.is_(genetic))
                            .order_by(Product.nom)))
    estoc = stock.stock_by_product(db, [p.id for p in prods])
    ocults = set(cfg["ocults"])
    per_cat: dict[str, list[dict]] = {}
    for p in prods:
        if p.id in ocults:
            continue
        disponible = estoc.get(p.id, 0) > 0
        if not disponible and not cfg["mostrar_esgotats"]:
            continue
        cat = p.categoria if p.categoria in categories_de(m.tipus) else "Altres"
        per_cat.setdefault(cat, []).append({"id": p.id, "nom": p.nom, "unitat": p.unitat, "disponible": disponible,
                                            "preu_cent": p.preu_cent_per_g if cfg["mostrar_preus"] else None})
    categories = [{"nom": c["nom"], "productes": per_cat[c["nom"]]} for c in _cat_ordre(cfg, m.tipus) if c["visible"] and per_cat.get(c["nom"])]
    return {"menu": {"id": m.id, "nom": m.nom, "tipus": m.tipus}, "versio": m.versio,
            "disseny": {k: cfg[k] for k in DISSENY_DEFECTE if k not in ("categories", "ocults")},
            "imatges": imatges or {}, "categories": categories}


def imatges_publiques(m: Menu, token: str) -> dict:
    out = {}
    if m.logo_img:
        out["logo"] = f"/pantalla/{token}/logo?v={m.versio}"
    if m.fons_img:
        out["fons"] = f"/pantalla/{token}/fons?v={m.versio}"
    return out


def llista_productes(db: Session, m: Menu, cfg: dict) -> list[dict]:
    """Per a la finestra «Categories»: productes del menú (amb estat) per poder amagar-ne un concret."""
    genetic = m.tipus == "dispensari"
    prods = list(db.scalars(select(Product).where(Product.local_id == m.local_id, Product.actiu.is_(True), Product.es_genetic.is_(genetic)).order_by(Product.nom)))
    estoc = stock.stock_by_product(db, [p.id for p in prods])
    ocults = set(cfg["ocults"])
    return [{"id": p.id, "nom": p.nom, "categoria": p.categoria if p.categoria in categories_de(m.tipus) else "Altres",
             "disponible": estoc.get(p.id, 0) > 0, "ocult": p.id in ocults} for p in prods]


# ---------- menús ----------

def assegura_defecte(db: Session, actor: User, local_id: int) -> None:
    """Un menú Dispensari i un Bar per defecte, ja creats."""
    if db.scalar(select(Menu.id).where(Menu.local_id == local_id).limit(1)):
        return
    for t in TIPUS_MENU:
        db.add(Menu(local_id=local_id, tipus=t, nom=NOMS_DEFECTE[t], per_defecte=True, disseny=json.dumps(neteja_disseny({}, t))))
    db.flush()
    service.audit_append(db, {"accio": "menus_per_defecte", "local": local_id, "per": actor.id})
    db.commit()


def _nom(db: Session, local_id: int, nom, excepte: int | None = None) -> str:
    nom = (nom or "").strip()
    if not 1 <= len(nom) <= 60:
        raise ValueError("El nom ha de tenir entre 1 i 60 caràcters")
    q = select(Menu.id).where(Menu.local_id == local_id, Menu.nom == nom)
    if excepte:
        q = q.where(Menu.id != excepte)
    if db.scalar(q):
        raise ValueError("Ja hi ha un menú amb aquest nom")
    return nom


def llista(db: Session, local_id: int) -> list[dict]:
    pantalles = {}
    for s in db.scalars(select(MenuScreen).where(MenuScreen.local_id == local_id, MenuScreen.revocada.is_(None))):
        pantalles[s.menu_id] = pantalles.get(s.menu_id, 0) + 1
    return [{"id": m.id, "tipus": m.tipus, "nom": m.nom, "per_defecte": m.per_defecte, "actiu": m.actiu, "pantalles": pantalles.get(m.id, 0),
             "sense_publicar": m.esborrany is not None}
            for m in sorted(db.scalars(select(Menu).where(Menu.local_id == local_id)), key=lambda m: (m.tipus != "dispensari", m.id))]


def crea(db: Session, actor: User, local_id: int, tipus: str, nom: str) -> Menu:
    if tipus not in TIPUS_MENU:
        raise ValueError("Tipus de menú no vàlid")
    m = Menu(local_id=local_id, tipus=tipus, nom=_nom(db, local_id, nom), disseny=json.dumps(neteja_disseny({}, tipus)))
    m.per_defecte = db.scalar(select(Menu.id).where(Menu.local_id == local_id, Menu.tipus == tipus, Menu.per_defecte.is_(True))) is None
    db.add(m)
    db.flush()
    service.audit_append(db, {"accio": "alta_menu", "menu": m.id, "local": local_id, "tipus": tipus, "per": actor.id})
    db.commit()
    return m


def duplica(db: Session, actor: User, m: Menu) -> Menu:
    base, n = m.nom[:50], 2
    while db.scalar(select(Menu.id).where(Menu.local_id == m.local_id, Menu.nom == f"{base} ({n})")):
        n += 1
    c = Menu(local_id=m.local_id, tipus=m.tipus, nom=f"{base} ({n})", disseny=m.disseny, logo_img=m.logo_img, fons_img=m.fons_img, esborrany=m.esborrany)
    db.add(c)
    db.flush()
    service.audit_append(db, {"accio": "duplica_menu", "menu": c.id, "origen": m.id, "per": actor.id})
    db.commit()
    return c


def edita(db: Session, actor: User, m: Menu, nom: str | None, actiu: bool | None, per_defecte: bool | None) -> None:
    canvis = []
    if nom is not None and nom.strip() != m.nom:
        m.nom = _nom(db, m.local_id, nom, m.id)
        canvis.append("nom")
    if actiu is not None and actiu != m.actiu:
        m.actiu = actiu
        canvis.append("actiu")
    if per_defecte and not m.per_defecte:
        for altre in db.scalars(select(Menu).where(Menu.local_id == m.local_id, Menu.tipus == m.tipus, Menu.per_defecte.is_(True))):
            altre.per_defecte = False
        m.per_defecte = True
        canvis.append("per_defecte")
    if not canvis:
        raise ValueError("No hi ha cap canvi")
    service.audit_append(db, {"accio": "edita_menu", "menu": m.id, "camps": canvis, "per": actor.id})
    db.commit()


def esborra(db: Session, actor: User, m: Menu) -> None:
    if db.scalar(select(MenuScreen.id).where(MenuScreen.menu_id == m.id, MenuScreen.revocada.is_(None))):
        raise ValueError("Hi ha pantalles que mostren aquest menú: assigna'ls un altre menú abans d'esborrar-lo")
    for s in db.scalars(select(MenuScreen).where(MenuScreen.menu_id == m.id)):
        s.menu_id = None
    service.audit_append(db, {"accio": "esborra_menu", "menu": m.id, "per": actor.id})
    db.delete(m)
    db.commit()


def desa_esborrany(db: Session, m: Menu, disseny: dict | None, logo, fons, canvia_logo: bool, canvia_fons: bool) -> None:
    """Desat automàtic: no es publica res fins a «Publicar». No s'audita (es crida a cada canvi)."""
    actual = esborrany_de(m) or {"disseny": json.loads(m.disseny or "{}"), "logo_img": m.logo_img, "fons_img": m.fons_img}
    nou = neteja_disseny(disseny, m.tipus, base=neteja_disseny(actual.get("disseny"), m.tipus)) if disseny is not None else neteja_disseny(actual.get("disseny"), m.tipus)
    if canvia_logo:
        actual["logo_img"] = neteja_imatge(logo)
    if canvia_fons:
        actual["fons_img"] = neteja_imatge(fons)
    m.esborrany = json.dumps({"disseny": nou, "logo_img": actual.get("logo_img"), "fons_img": actual.get("fons_img")})
    db.commit()


def configuracio_editable(m: Menu) -> tuple[dict, dict]:
    """(disseny, imatges) que es veuen a l'editor: l'esborrany si n'hi ha, i si no el publicat."""
    e = esborrany_de(m)
    if not e:
        return disseny_publicat(m), {"logo": m.logo_img, "fons": m.fons_img}
    return neteja_disseny(e.get("disseny"), m.tipus), {"logo": e.get("logo_img"), "fons": e.get("fons_img")}


def publica(db: Session, actor: User, m: Menu) -> None:
    e = esborrany_de(m)
    if not e:
        raise ValueError("No hi ha canvis per publicar")
    m.disseny = json.dumps(neteja_disseny(e.get("disseny"), m.tipus))
    m.logo_img, m.fons_img = neteja_imatge(e.get("logo_img")), neteja_imatge(e.get("fons_img"))
    m.esborrany = None
    m.versio = (m.versio or 1) + 1
    service.audit_append(db, {"accio": "publica_menu", "menu": m.id, "per": actor.id})
    db.commit()


def descarta(db: Session, m: Menu) -> None:
    m.esborrany = None
    db.commit()


# ---------- pantalles ----------

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _nom_pantalla(db: Session, local_id: int, nom, excepte: int | None = None) -> str:
    nom = (nom or "").strip()
    if not 1 <= len(nom) <= 60:
        raise ValueError("El nom ha de tenir entre 1 i 60 caràcters")
    q = select(MenuScreen.id).where(MenuScreen.local_id == local_id, MenuScreen.nom == nom)
    if excepte:
        q = q.where(MenuScreen.id != excepte)
    if db.scalar(q):
        raise ValueError("Ja hi ha una pantalla amb aquest nom")
    return nom


def _menu_del_local(db: Session, local_id: int, menu_id: int | None) -> int | None:
    if menu_id is None:
        return None
    m = db.get(Menu, menu_id)
    if not m or m.local_id != local_id:
        raise ValueError("Menú inexistent en aquest local")
    return m.id


def crea_pantalla(db: Session, actor: User, local_id: int, nom: str, tipus: str, menu_id: int | None) -> MenuScreen:
    if tipus not in TIPUS_PANTALLA:
        raise ValueError("Tipus de pantalla no vàlid")
    token = secrets.token_urlsafe(24)
    s = MenuScreen(local_id=local_id, nom=_nom_pantalla(db, local_id, nom), tipus=tipus, menu_id=_menu_del_local(db, local_id, menu_id),
                   token_hash=_hash(token), token_enc=crypto.encrypt(token))
    db.add(s)
    db.flush()
    service.audit_append(db, {"accio": "alta_pantalla_menu", "pantalla": s.id, "local": local_id, "tipus": tipus, "per": actor.id})
    db.commit()
    return s


def edita_pantalla(db: Session, actor: User, s: MenuScreen, nom: str | None, tipus: str | None, menu_id: int | None, canvia_menu: bool) -> None:
    if s.revocada:
        raise ValueError("Aquesta pantalla està revocada")
    canvis = {}
    if nom is not None and nom.strip() != s.nom:
        s.nom = _nom_pantalla(db, s.local_id, nom, s.id)
        canvis["nom"] = True
    if tipus is not None and tipus != s.tipus:
        if tipus not in TIPUS_PANTALLA:
            raise ValueError("Tipus de pantalla no vàlid")
        s.tipus = tipus
        canvis["tipus"] = True
    if canvia_menu and menu_id != s.menu_id:
        canvis["menu"] = [s.menu_id, menu_id]
        s.menu_id = _menu_del_local(db, s.local_id, menu_id)
    if not canvis:
        raise ValueError("No hi ha cap canvi")
    service.audit_append(db, {"accio": "edita_pantalla_menu", "pantalla": s.id, "camps": canvis, "per": actor.id})
    db.commit()


def revoca_pantalla(db: Session, actor: User, s: MenuScreen) -> None:
    if s.revocada:
        raise ValueError("Ja està revocada")
    s.revocada = datetime.now(timezone.utc)
    service.audit_append(db, {"accio": "revoca_pantalla_menu", "pantalla": s.id, "per": actor.id})
    db.commit()


def llista_pantalles(db: Session, local_id: int) -> list[dict]:
    noms = {m.id: m.nom for m in db.scalars(select(Menu).where(Menu.local_id == local_id))}
    out = []
    for s in db.scalars(select(MenuScreen).where(MenuScreen.local_id == local_id).order_by(MenuScreen.id)):
        out.append({"id": s.id, "nom": s.nom, "tipus": s.tipus, "menu_id": s.menu_id, "menu": noms.get(s.menu_id), "revocada": s.revocada is not None,
                    "url": None if s.revocada else "/pantalla/" + crypto.decrypt(s.token_enc),
                    "darrera_connexio": s.darrera_connexio.replace(tzinfo=s.darrera_connexio.tzinfo or timezone.utc).isoformat() if s.darrera_connexio else None})
    return out


def pantalla_per_token(db: Session, token: str) -> MenuScreen | None:
    if not token or len(token) > 80:
        return None
    s = db.scalar(select(MenuScreen).where(MenuScreen.token_hash == _hash(token)))
    return s if s and not s.revocada else None
