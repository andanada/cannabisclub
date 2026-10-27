from datetime import date, datetime, timezone
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


class Local(Base):
    __tablename__ = "locals"
    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(120), unique=True)
    limit_diari_mg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    limit_mensual_mg: Mapped[int | None] = mapped_column(Integer, nullable=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    totp_secret_enc: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20))  # admin | encarregat | dispensador
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class UserLocal(Base):
    __tablename__ = "user_locals"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    local_id: Mapped[int] = mapped_column(ForeignKey("locals.id"), primary_key=True)


class SessionToken(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Member(Base):
    __tablename__ = "members"
    __table_args__ = (UniqueConstraint("local_id", "document_idx"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    local_id: Mapped[int] = mapped_column(ForeignKey("locals.id"))
    nom_enc: Mapped[str] = mapped_column(Text)
    document_enc: Mapped[str] = mapped_column(Text)
    document_idx: Mapped[str] = mapped_column(String(64))  # HMAC per detectar duplicats sense desxifrar
    naixement_enc: Mapped[str] = mapped_column(Text)
    telefon_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    estat: Mapped[str] = mapped_column(String(20), default="actiu")  # actiu | suspes | baixa
    creat: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    creat_per: Mapped[int] = mapped_column(ForeignKey("users.id"))


class AuditLog(Base):
    __tablename__ = "audit_log"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    payload: Mapped[str] = mapped_column(Text)  # JSON canònic, sense dades personals en clar
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("local_id", "nom"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    local_id: Mapped[int] = mapped_column(ForeignKey("locals.id"))
    nom: Mapped[str] = mapped_column(String(120))
    categoria: Mapped[str] = mapped_column(String(60), default="")
    preu_cent_per_g: Mapped[int] = mapped_column(Integer, default=0)
    actiu: Mapped[bool] = mapped_column(Boolean, default=True)


class StockMovement(Base):
    """Només s'hi afegeixen files. Les correccions són un moviment nou que apunta a l'original."""
    __tablename__ = "stock_movements"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    local_id: Mapped[int] = mapped_column(ForeignKey("locals.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    tipus: Mapped[str] = mapped_column(String(20))  # entrada | dispensacio | merma | correccio
    delta_mg: Mapped[int] = mapped_column(Integer)  # positiu = entra, negatiu = surt
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    pes_bascula_mg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    import_cent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    corregeix_id: Mapped[int | None] = mapped_column(ForeignKey("stock_movements.id"), nullable=True, unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    nota: Mapped[str | None] = mapped_column(String(300), nullable=True)


class ImmutableError(RuntimeError):
    pass


@event.listens_for(StockMovement, "before_update")
def _no_update(mapper, connection, target):
    raise ImmutableError("Els moviments d'estoc no es poden modificar: crea una correcció")


@event.listens_for(StockMovement, "before_delete")
def _no_delete(mapper, connection, target):
    raise ImmutableError("Els moviments d'estoc no es poden esborrar: crea una correcció")
