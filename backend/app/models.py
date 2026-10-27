from datetime import date, datetime, timezone
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


class Local(Base):
    __tablename__ = "locals"
    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(120), unique=True)


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
