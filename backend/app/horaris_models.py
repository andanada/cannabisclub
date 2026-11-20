"""Models del mòdul d'horaris: calendari planificat, sol·licituds de canvi, registre de canvis (només d'afegir),
avançaments (només d'afegir) i configuració dels torns estàndard per local."""
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import ImmutableError, now


class ScheduleConfig(Base):
    """Configuració JSON dels torns estàndard d'un local (editable per la gerència)."""
    __tablename__ = "schedule_configs"
    local_id: Mapped[int] = mapped_column(ForeignKey("locals.id"), primary_key=True)
    valor: Mapped[str] = mapped_column(Text)


class ShiftSlot(Base):
    """Un lloc (dispensari | recepcio) d'un torn d'un dia. `inici`/`fi` (HH:MM) són l'horari propi del treballador, si difereix."""
    __tablename__ = "shift_slots"
    __table_args__ = (UniqueConstraint("local_id", "data", "torn", "lloc"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    local_id: Mapped[int] = mapped_column(ForeignKey("locals.id"))
    data: Mapped[date] = mapped_column(Date)
    torn: Mapped[str] = mapped_column(String(10))    # mati | tarda | unic
    lloc: Mapped[str] = mapped_column(String(12))    # dispensari | recepcio
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    inici: Mapped[str | None] = mapped_column(String(5), nullable=True)
    fi: Mapped[str | None] = mapped_column(String(5), nullable=True)


Index("ix_shift_slots_local_data", ShiftSlot.local_id, ShiftSlot.data)
Index("ix_shift_slots_user", ShiftSlot.user_id)


class ShiftTurn(Base):
    """Horari modificat d'un torn concret d'un dia (si no hi és, s'usa l'estàndard)."""
    __tablename__ = "shift_turns"
    __table_args__ = (UniqueConstraint("local_id", "data", "torn"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    local_id: Mapped[int] = mapped_column(ForeignKey("locals.id"))
    data: Mapped[date] = mapped_column(Date)
    torn: Mapped[str] = mapped_column(String(10))
    inici: Mapped[str] = mapped_column(String(5))
    fi: Mapped[str] = mapped_column(String(5))


class ShiftRequest(Base):
    """Canvi de torn o diferència d'horari senyalats per un treballador; no compten fins que l'encarregada els aprova."""
    __tablename__ = "shift_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    local_id: Mapped[int] = mapped_column(ForeignKey("locals.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))                    # qui ho senyala (i a qui afecta)
    tipus: Mapped[str] = mapped_column(String(10))                                  # canvi | diferencia
    data: Mapped[date] = mapped_column(Date)
    torn: Mapped[str] = mapped_column(String(10))
    lloc: Mapped[str] = mapped_column(String(12))
    substitut_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)   # canvi: qui el rellevarà
    minuts: Mapped[int] = mapped_column(Integer, default=0)                         # diferència: + es queda més, - surt abans
    comentari: Mapped[str | None] = mapped_column(String(300), nullable=True)
    estat: Mapped[str] = mapped_column(String(16), default="pendent")               # pendent | aprovada | rebutjada | cancel·lada
    resolt_per: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolt_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    nota: Mapped[str | None] = mapped_column(String(300), nullable=True)


Index("ix_shift_requests_local_estat", ShiftRequest.local_id, ShiftRequest.estat)


class ShiftChange(Base):
    """Registre de tots els canvis efectuats al calendari (només d'afegir)."""
    __tablename__ = "shift_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    local_id: Mapped[int] = mapped_column(ForeignKey("locals.id"))
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    accio: Mapped[str] = mapped_column(String(20))   # assigna | lleva | horari_torn | horari_treballador | canvi | diferencia | config
    data: Mapped[date | None] = mapped_column(Date, nullable=True)
    torn: Mapped[str | None] = mapped_column(String(10), nullable=True)
    lloc: Mapped[str | None] = mapped_column(String(12), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)       # treballador afectat
    abans: Mapped[str | None] = mapped_column(String(200), nullable=True)
    despres: Mapped[str | None] = mapped_column(String(200), nullable=True)
    request_id: Mapped[int | None] = mapped_column(ForeignKey("shift_requests.id"), nullable=True)


Index("ix_shift_changes_local_ts", ShiftChange.local_id, ShiftChange.ts)


class Advance(Base):
    """Avançament de sou (només d'afegir). Cada un genera una despesa (Expense); una anul·lació és una fila amb `corregeix_id`."""
    __tablename__ = "advances"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    local_id: Mapped[int] = mapped_column(ForeignKey("locals.id"))
    data: Mapped[date] = mapped_column(Date)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))        # treballador que el rep
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))       # qui l'apunta
    import_cent: Mapped[int] = mapped_column(Integer)
    comentari: Mapped[str | None] = mapped_column(String(300), nullable=True)
    de_caixa: Mapped[bool] = mapped_column(Boolean, default=False)
    expense_id: Mapped[int | None] = mapped_column(ForeignKey("expenses.id"), nullable=True)
    corregeix_id: Mapped[int | None] = mapped_column(ForeignKey("advances.id"), nullable=True, unique=True)


Index("ix_advances_local_data", Advance.local_id, Advance.data)


@event.listens_for(ShiftChange, "before_update")
@event.listens_for(ShiftChange, "before_delete")
@event.listens_for(Advance, "before_update")
@event.listens_for(Advance, "before_delete")
def _immutable_horaris(mapper, connection, target):
    raise ImmutableError("Aquest registre no es pot modificar ni esborrar")
