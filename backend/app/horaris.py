"""Horaris: configuració de torns, calendari mensual, assignació de llocs i càlculs de torns i hores per treballador."""
import calendar
import json
import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import service
from .cash import _range
from .horaris_models import ScheduleConfig, ShiftChange, ShiftRequest, ShiftSlot, ShiftTurn
from .models import User

LLOCS = ("dispensari", "recepcio")
TORNS = ("mati", "tarda", "unic")
HORA = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

DEFECTE = {
    "torns": {"mati": ["10:00", "16:30"], "tarda": ["16:30", "23:00"], "unic": ["15:00", "23:00"]},
    "dies_unics": [6],  # dies de la setmana (0 = dilluns) amb un sol torn
    "excepcions": [
        {"dia": "12-24", "torns": {"mati": ["10:00", "16:30"], "tarda": ["16:30", "20:00"]}},
        {"dia": "12-31", "torns": {"mati": ["10:00", "16:30"], "tarda": ["16:30", "20:00"]}},
        {"dia": "12-25", "torns": {"unic": ["15:00", "21:00"]}},
        {"dia": "01-01", "torns": {"unic": ["15:00", "21:00"]}},
    ],
}


def _hora(v, nom="hora") -> str:
    if not isinstance(v, str) or not HORA.match(v):
        raise ValueError(f"{nom}: format HH:MM no vàlid")
    return v


def _parells(v, nom) -> list[str]:
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        raise ValueError(f"{nom}: cal una hora d'inici i una de fi")
    return [_hora(v[0], nom), _hora(v[1], nom)]


def valida_config(c: dict) -> dict:
    if not isinstance(c, dict):
        raise ValueError("Configuració no vàlida")
    torns = {k: _parells(v, "Torn " + k) for k, v in (c.get("torns") or {}).items() if k in TORNS}
    if set(torns) != set(TORNS):
        raise ValueError("Cal definir els torns matí, tarda i únic")
    dies = sorted({int(d) for d in (c.get("dies_unics") or [])})
    if any(d < 0 or d > 6 for d in dies):
        raise ValueError("Dia de la setmana no vàlid")
    exc = []
    for e in c.get("excepcions") or []:
        dia = str((e or {}).get("dia", ""))
        if not re.match(r"^(\d{4}-)?(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$", dia):
            raise ValueError("Dia de l'excepció no vàlid (MM-DD o AAAA-MM-DD)")
        t = {k: _parells(v, "Torn " + k) for k, v in (e.get("torns") or {}).items() if k in TORNS}
        if not t:
            raise ValueError("Una excepció necessita almenys un torn")
        exc.append({"dia": dia, "torns": t})
    return {"torns": torns, "dies_unics": dies, "excepcions": exc}


def get_config(db: Session, local_id: int) -> dict:
    fila = db.get(ScheduleConfig, local_id)
    if fila:
        try:
            return valida_config(json.loads(fila.valor))
        except ValueError:
            pass
    return json.loads(json.dumps(DEFECTE))


def set_config(db: Session, actor: User, local_id: int, c: dict) -> dict:
    c = valida_config(c)
    fila = db.get(ScheduleConfig, local_id)
    if fila:
        fila.valor = json.dumps(c)
    else:
        db.add(ScheduleConfig(local_id=local_id, valor=json.dumps(c)))
    _registre(db, actor, local_id, "config")
    service.audit_append(db, {"accio": "horaris_config", "local": local_id, "per": actor.id})
    db.commit()
    return c


def _registre(db, actor, local_id, accio, data=None, torn=None, lloc=None, user_id=None, abans=None, despres=None, request_id=None):
    db.add(ShiftChange(local_id=local_id, actor_id=actor.id, accio=accio, data=data, torn=torn, lloc=lloc, user_id=user_id,
                       abans=abans, despres=despres, request_id=request_id))


def torns_del_dia(cfg: dict, d: date, canvis: dict | None = None) -> dict[str, list[str]]:
    """Torns del dia amb el seu horari: excepció (data exacta, després MM-DD) > diumenge/dia únic > estàndard; i
    després l'horari modificat d'aquell torn (`canvis`: {torn: [ini, fi]})."""
    exact, mmdd = d.isoformat(), d.strftime("%m-%d")
    torns = None
    for clau in (exact, mmdd):
        for e in cfg["excepcions"]:
            if e["dia"] == clau and torns is None:
                torns = {k: list(v) for k, v in e["torns"].items()}
    if torns is None:
        noms = ("unic",) if d.weekday() in cfg["dies_unics"] else ("mati", "tarda")
        torns = {k: list(cfg["torns"][k]) for k in noms}
    for k, v in (canvis or {}).items():
        if k in torns:
            torns[k] = list(v)
    return dict(sorted(torns.items(), key=lambda kv: TORNS.index(kv[0])))


def minuts(ini: str, fi: str) -> int:
    a = int(ini[:2]) * 60 + int(ini[3:])
    b = int(fi[:2]) * 60 + int(fi[3:])
    return (b - a) % 1440


def _canvis_torn(db, local_id, des, fins) -> dict:
    out: dict = {}
    for t in db.scalars(select(ShiftTurn).where(ShiftTurn.local_id == local_id, ShiftTurn.data >= des, ShiftTurn.data <= fins)):
        out.setdefault(t.data, {})[t.torn] = [t.inici, t.fi]
    return out


def _check_torn(cfg, db, local_id, data: date, torn: str, lloc: str | None = None) -> list[str]:
    if lloc is not None and lloc not in LLOCS:
        raise ValueError("Lloc no vàlid")
    canvis = _canvis_torn(db, local_id, data, data).get(data)
    t = torns_del_dia(cfg, data, canvis)
    if torn not in t:
        raise ValueError("Aquest dia no té aquest torn")
    return t[torn]


def _usuari_local(db, local_id, user_id):
    from .routes.comu import personal_del_local
    if user_id not in {u.id for u in personal_del_local(db, local_id)}:
        raise ValueError("Aquest treballador no treballa en aquest local")


def _desc(s: ShiftSlot | None) -> str | None:
    return None if s is None else f"{s.user_id}" + (f" {s.inici or ''}-{s.fi or ''}" if s.inici or s.fi else "")


def assigna(db: Session, actor: User, local_id: int, data: date, torn: str, lloc: str, user_id: int | None,
            inici: str | None = None, fi: str | None = None, commit: bool = True) -> None:
    """Posa (o lleva, amb user_id None) un treballador en un lloc d'un torn. Opcionalment amb horari propi."""
    cfg = get_config(db, local_id)
    _check_torn(cfg, db, local_id, data, torn, lloc)
    if (inici is None) != (fi is None):
        raise ValueError("Cal indicar l'hora d'inici i la de fi, o cap de les dues")
    if inici is not None:
        _hora(inici, "Inici"), _hora(fi, "Fi")
    fila = db.scalar(select(ShiftSlot).where(ShiftSlot.local_id == local_id, ShiftSlot.data == data, ShiftSlot.torn == torn, ShiftSlot.lloc == lloc))
    abans = _desc(fila)
    if user_id is None:
        if fila:
            db.delete(fila)
            _registre(db, actor, local_id, "lleva", data, torn, lloc, fila.user_id, abans, None)
    else:
        _usuari_local(db, local_id, user_id)
        altre = db.scalar(select(ShiftSlot).where(ShiftSlot.local_id == local_id, ShiftSlot.data == data, ShiftSlot.torn == torn,
                                                  ShiftSlot.user_id == user_id, ShiftSlot.lloc != lloc))
        if altre:
            raise ValueError("Aquest treballador ja és en l'altre lloc d'aquest torn")
        if fila:
            fila.user_id, fila.inici, fila.fi = user_id, inici, fi
        else:
            fila = ShiftSlot(local_id=local_id, data=data, torn=torn, lloc=lloc, user_id=user_id, inici=inici, fi=fi)
            db.add(fila)
        db.flush()
        _registre(db, actor, local_id, "assigna" if abans is None else "horari_treballador" if abans.split(" ")[0] == str(user_id) else "assigna",
                  data, torn, lloc, user_id, abans, _desc(fila))
    service.audit_append(db, {"accio": "horaris_slot", "local": local_id, "data": data.isoformat(), "torn": torn, "lloc": lloc, "usuari": user_id, "per": actor.id})
    if commit:
        db.commit()


def horari_torn(db: Session, actor: User, local_id: int, data: date, torn: str, inici: str | None, fi: str | None) -> None:
    """Modifica l'horari d'un torn d'un dia (None, None el torna a l'estàndard)."""
    cfg = get_config(db, local_id)
    _check_torn(cfg, db, local_id, data, torn)
    fila = db.scalar(select(ShiftTurn).where(ShiftTurn.local_id == local_id, ShiftTurn.data == data, ShiftTurn.torn == torn))
    abans = f"{fila.inici}-{fila.fi}" if fila else None
    if inici is None and fi is None:
        if fila:
            db.delete(fila)
    else:
        _hora(inici, "Inici"), _hora(fi, "Fi")
        if fila:
            fila.inici, fila.fi = inici, fi
        else:
            db.add(ShiftTurn(local_id=local_id, data=data, torn=torn, inici=inici, fi=fi))
    _registre(db, actor, local_id, "horari_torn", data, torn, None, None, abans, None if inici is None else f"{inici}-{fi}")
    service.audit_append(db, {"accio": "horaris_torn", "local": local_id, "data": data.isoformat(), "torn": torn, "per": actor.id})
    db.commit()


def _mes_rang(any_: int, mes: int):
    if not 1 <= mes <= 12:
        raise ValueError("Mes no vàlid")
    return date(any_, mes, 1), date(any_, mes, calendar.monthrange(any_, mes)[1])


def mes(db: Session, local_id: int, any_: int, mes_: int) -> dict:
    """Calendari del mes (dies complets, de dilluns a diumenge a la vista) i totals per treballador."""
    des, fins = _mes_rang(any_, mes_)
    cfg = get_config(db, local_id)
    canvis = _canvis_torn(db, local_id, des, fins)
    slots = db.scalars(select(ShiftSlot).where(ShiftSlot.local_id == local_id, ShiftSlot.data >= des, ShiftSlot.data <= fins)).all()
    per_dia: dict = {}
    for s in slots:
        per_dia.setdefault((s.data, s.torn), {})[s.lloc] = s
    noms = {i: n for i, n in db.execute(select(User.id, User.username))}
    dies, totals = [], {}
    for n in range(1, fins.day + 1):
        d = date(any_, mes_, n)
        torns = []
        for torn, (ini, fi) in torns_del_dia(cfg, d, canvis.get(d)).items():
            posts = {}
            for lloc in LLOCS:
                s = per_dia.get((d, torn), {}).get(lloc)
                posts[lloc] = None if s is None else {"user_id": s.user_id, "inici": s.inici, "fi": s.fi}
                if s is not None:
                    t = totals.setdefault(s.user_id, {"user_id": s.user_id, "torns": 0, "minuts_planificats": 0, "minuts_diferencies": 0})
                    t["torns"] += 1
                    t["minuts_planificats"] += minuts(s.inici or ini, s.fi or fi)
            torns.append({"torn": torn, "inici": ini, "fi": fi, "llocs": posts})
        dies.append({"data": d.isoformat(), "dia_setmana": d.weekday(), "torns": torns})
    for r in db.scalars(select(ShiftRequest).where(ShiftRequest.local_id == local_id, ShiftRequest.estat == "aprovada",
                                                    ShiftRequest.tipus == "diferencia", ShiftRequest.data >= des, ShiftRequest.data <= fins)):
        t = totals.setdefault(r.user_id, {"user_id": r.user_id, "torns": 0, "minuts_planificats": 0, "minuts_diferencies": 0})
        t["minuts_diferencies"] += r.minuts
    for t in totals.values():
        t["minuts"] = t["minuts_planificats"] + t["minuts_diferencies"]
        t["hores"] = round(t["minuts"] / 60, 2)
        t["usuari"] = noms.get(t["user_id"])
    return {"any": any_, "mes": mes_, "dies": dies, "totals": sorted(totals.values(), key=lambda t: t["usuari"] or "")}


def registre(db: Session, local_id: int, des: date, fins: date, limit: int = 500) -> list[dict]:
    noms = {i: n for i, n in db.execute(select(User.id, User.username))}
    a, b = _range(des, fins)
    q = (select(ShiftChange).where(ShiftChange.local_id == local_id, ShiftChange.ts >= a, ShiftChange.ts < b)
         .order_by(ShiftChange.id.desc()).limit(limit))
    return [{"id": c.id, "ts": c.ts.isoformat(), "actor": noms.get(c.actor_id), "accio": c.accio, "data": c.data.isoformat() if c.data else None,
             "torn": c.torn, "lloc": c.lloc, "usuari": noms.get(c.user_id), "abans": c.abans, "despres": c.despres, "request_id": c.request_id}
            for c in db.scalars(q)]
