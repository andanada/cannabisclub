"""Ajustos opcionals per local (taula clau/valor). Tot té un valor per defecte: un local sense ajustos
es comporta com abans."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import service
from .models import LocalSetting, User

DEFECTES = {"quota_obligatoria": False, "quota_cent": None, "quota_mesos": 1,
            "espera_dies": 0, "aval": "no", "alta_pendent": False,
            "moneder_actiu": False, "moneder_limit_cent": 0, "consum_exigit": False, "targeta_activa": False,
            "estoc_baix_mg": 5000, "cuota_inactivitat_dies": 90, "donacions_dia_max_cent": 0,
            "edat_minima": 18, "inactivitat_dies": 30, "decimals_dispensacio": 3, "perdua_maxima_mg": 0}
# edat_minima: edat per ser soci (mai per sota de 18); inactivitat_dies: dies sense visites per considerar inactiu un soci;
# decimals_dispensacio: decimals admesos en els grams d'una dispensació (0-3); perdua_maxima_mg: falta màxima tolerada en tancar
# un inventari abans d'avisar (0 = no s'avisa)  # monedero: activat i límit de saldo negatiu (cèntims)  # els tres últims: controls de club (controls.py)
BOOLEANS = {"quota_obligatoria", "alta_pendent", "moneder_actiu", "consum_exigit", "targeta_activa"}  # targeta_activa: el local accepta targeta i Bizum (TPV); si no, només efectiu i monedero  # consum_exigit: cal consentiment explícit de consum per dispensar
AVALS = {"no", "opcional", "obligatori"}
MAX_QUOTA_CENT = 1_000_000


def _parse(clau: str, valor: str):
    if clau in BOOLEANS:
        return valor == "1"
    if clau == "aval":
        return valor if valor in AVALS else "no"
    return int(valor)


def get(db: Session, local_id: int) -> dict:
    out = dict(DEFECTES)
    for r in db.scalars(select(LocalSetting).where(LocalSetting.local_id == local_id)):
        if r.clau in DEFECTES:
            out[r.clau] = _parse(r.clau, r.valor)
    return out


def _validate(clau: str, valor) -> None:
    if clau == "quota_cent" and valor is not None and not 0 < valor <= MAX_QUOTA_CENT:
        raise ValueError("L'import de la quota ha d'estar entre 0,01 € i 10.000 €")
    if clau == "quota_mesos" and not 1 <= valor <= 24:
        raise ValueError("Els mesos de la quota han d'estar entre 1 i 24")
    if clau == "espera_dies" and not 0 <= valor <= 365:
        raise ValueError("El període d'espera ha d'estar entre 0 i 365 dies")
    if clau == "edat_minima" and not 18 <= valor <= 99:
        raise ValueError("L'edat mínima ha d'estar entre 18 i 99 anys")
    if clau == "inactivitat_dies" and not 1 <= valor <= 365:
        raise ValueError("L'alerta d'inactivitat ha d'estar entre 1 i 365 dies")
    if clau == "decimals_dispensacio" and not 0 <= valor <= 3:
        raise ValueError("Els decimals de la dispensació han d'estar entre 0 i 3")
    if clau == "perdua_maxima_mg" and not 0 <= valor <= 10_000_000:
        raise ValueError("La pèrdua màxima ha d'estar entre 0 i 10.000 g")
    if clau == "moneder_limit_cent" and not 0 <= valor <= MAX_QUOTA_CENT:
        raise ValueError("El límit negatiu del monedero ha d'estar entre 0 i 10.000 €")
    if clau == "estoc_baix_mg" and not 0 <= valor <= 10_000_000:
        raise ValueError("L'avís d'estoc baix ha d'estar entre 0 i 10.000")
    if clau == "cuota_inactivitat_dies" and not 0 <= valor <= 3650:
        raise ValueError("Els dies d'inactivitat per cobrar la quota han d'estar entre 0 (desactivat) i 3650")
    if clau == "donacions_dia_max_cent" and not 0 <= valor <= 100_000_000:
        raise ValueError("El màxim de donacions per empleat i dia ha d'estar entre 0 (sense límit) i 1.000.000 €")
    if clau == "aval" and valor not in AVALS:
        raise ValueError("Avalador: no, opcional o obligatori")


def set_(db: Session, actor: User, local_id: int, canvis: dict) -> dict:
    """Desa els ajustos indicats (els que valen None es deixen com estan, excepte quota_cent que s'esborra amb 0)."""
    aplicats = {}
    for clau, valor in canvis.items():
        if clau not in DEFECTES or valor is None:
            continue
        if clau == "quota_cent" and valor == 0:
            fila = db.get(LocalSetting, (local_id, clau))
            if fila:
                db.delete(fila)
            aplicats[clau] = None
            continue
        _validate(clau, valor)
        text = ("1" if valor else "0") if clau in BOOLEANS else (valor if clau == "aval" else str(int(valor)))
        fila = db.get(LocalSetting, (local_id, clau))
        if fila:
            fila.valor = text
        else:
            db.add(LocalSetting(local_id=local_id, clau=clau, valor=text))
        aplicats[clau] = valor
    if not aplicats:
        raise ValueError("No hi ha cap ajust per desar")
    service.audit_append(db, {"accio": "canvi_ajustos", "local": local_id, "ajustos": aplicats, "per": actor.id})
    db.commit()
    return get(db, local_id)
