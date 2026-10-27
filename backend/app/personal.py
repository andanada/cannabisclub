from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import service
from .cash import _range
from .models import TimeEvent, User

# estat actual -> {esdeveniment permès: nou estat}
TRANSICIONS = {
    "fora": {"entrada": "treballant"},
    "treballant": {"pausa_inici": "pausa", "sortida": "fora"},
    "pausa": {"pausa_fi": "treballant"},
}


def _estat(db: Session, user_id: int) -> str:
    last = db.scalar(select(TimeEvent).where(TimeEvent.user_id == user_id).order_by(TimeEvent.id.desc()).limit(1))
    if not last:
        return "fora"
    return {"entrada": "treballant", "pausa_fi": "treballant", "pausa_inici": "pausa", "sortida": "fora"}[last.tipus]


def clock(db: Session, user: User, local_id: int, tipus: str, now: datetime | None = None) -> TimeEvent:
    estat = _estat(db, user.id)
    nou = TRANSICIONS[estat].get(tipus)
    if not nou:
        raise ValueError(f"No pots fer «{tipus}» estant «{estat}»")
    ev = TimeEvent(user_id=user.id, local_id=local_id, tipus=tipus, ts=now or datetime.now(timezone.utc))
    db.add(ev)
    db.flush()
    service.audit_append(db, {"accio": "fitxatge", "esdeveniment": ev.id, "tipus": tipus, "per": user.id})
    db.commit()
    return ev


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def hours(db: Session, local_id: int, des: date, fins: date) -> dict:
    a, b = _range(des, fins)
    events = db.scalars(select(TimeEvent).where(TimeEvent.local_id == local_id, TimeEvent.ts >= a, TimeEvent.ts < b)
                        .order_by(TimeEvent.user_id, TimeEvent.id)).all()
    per_user = defaultdict(lambda: {"segons_treballats": 0, "torns": 0, "torn_obert": False})
    start = pause_start = None
    pause_total = 0
    current = None
    for e in events:
        if e.user_id != current:
            current, start, pause_start, pause_total = e.user_id, None, None, 0
        t = _aware(e.ts)
        r = per_user[e.user_id]
        if e.tipus == "entrada":
            start, pause_total, pause_start = t, 0, None
            r["torn_obert"] = True
        elif e.tipus == "pausa_inici":
            pause_start = t
        elif e.tipus == "pausa_fi" and pause_start:
            pause_total += int((t - pause_start).total_seconds())
            pause_start = None
        elif e.tipus == "sortida" and start:
            r["segons_treballats"] += int((t - start).total_seconds()) - pause_total
            r["torns"] += 1
            r["torn_obert"] = False
            start = None
    return {str(k): v for k, v in per_user.items()}
