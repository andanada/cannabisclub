from datetime import date, datetime, timezone
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, event
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
    tolerancia_bascula_mg: Mapped[int | None] = mapped_column(Integer, nullable=True)


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


class CashSession(Base):
    __tablename__ = "cash_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    local_id: Mapped[int] = mapped_column(ForeignKey("locals.id"))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    opened_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    opening_cent: Mapped[int] = mapped_column(Integer)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    expected_cent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    counted_cent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    diff_cent: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CashEntry(Base):
    """Apunts de caixa, només d'afegir. Positiu = entra, negatiu = surt."""
    __tablename__ = "cash_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    local_id: Mapped[int] = mapped_column(ForeignKey("locals.id"))
    session_id: Mapped[int] = mapped_column(ForeignKey("cash_sessions.id"))
    tipus: Mapped[str] = mapped_column(String(20))  # cobrament | despesa | correccio
    metode: Mapped[str] = mapped_column(String(10))  # efectiu | targeta
    import_cent: Mapped[int] = mapped_column(Integer)
    categoria: Mapped[str | None] = mapped_column(String(60), nullable=True)
    concepte: Mapped[str | None] = mapped_column(String(300), nullable=True)
    movement_id: Mapped[int | None] = mapped_column(ForeignKey("stock_movements.id"), nullable=True, unique=True)
    corregeix_id: Mapped[int | None] = mapped_column(ForeignKey("cash_entries.id"), nullable=True, unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))


@event.listens_for(CashEntry, "before_update")
def _no_update_cash(mapper, connection, target):
    raise ImmutableError("Els apunts de caixa no es poden modificar: crea una correcció")


@event.listens_for(CashEntry, "before_delete")
def _no_delete_cash(mapper, connection, target):
    raise ImmutableError("Els apunts de caixa no es poden esborrar: crea una correcció")


class TimeEvent(Base):
    """Fitxatge de personal, només d'afegir."""
    __tablename__ = "time_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    local_id: Mapped[int] = mapped_column(ForeignKey("locals.id"))
    tipus: Mapped[str] = mapped_column(String(15))  # entrada | sortida | pausa_inici | pausa_fi


class CheckIn(Base):
    __tablename__ = "checkins"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    local_id: Mapped[int] = mapped_column(ForeignKey("locals.id"))
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))


@event.listens_for(TimeEvent, "before_update")
@event.listens_for(TimeEvent, "before_delete")
@event.listens_for(CheckIn, "before_update")
@event.listens_for(CheckIn, "before_delete")
def _immutable_generic(mapper, connection, target):
    raise ImmutableError("Aquest registre no es pot modificar ni esborrar")


class Signature(Base):
    """Signatura manuscrita en pantalla de l'alta d'un soci. Només d'afegir; la imatge va xifrada."""
    __tablename__ = "signatures"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(20), default="alta")
    png_enc: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))  # hash(png + id del soci + data), per detectar alteracions


@event.listens_for(Signature, "before_update")
@event.listens_for(Signature, "before_delete")
def _immutable_signature(mapper, connection, target):
    raise ImmutableError("Les signatures no es poden modificar ni esborrar")


class Quota(Base):
    """Quota de soci. Només s'hi afegeixen files: va lligada a l'apunt de caixa que la cobra i, si es
    corregeix aquest apunt, la quota queda anul·lada (es calcula, no s'edita)."""
    __tablename__ = "quotes"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    local_id: Mapped[int] = mapped_column(ForeignKey("locals.id"))
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    cash_entry_id: Mapped[int] = mapped_column(ForeignKey("cash_entries.id"), unique=True)
    valid_des: Mapped[date] = mapped_column(Date)
    valid_fins: Mapped[date] = mapped_column(Date)
    mesos: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))


@event.listens_for(Quota, "before_update")
@event.listens_for(Quota, "before_delete")
def _immutable_quota(mapper, connection, target):
    raise ImmutableError("Les quotes no es poden modificar ni esborrar: corregeix l'apunt de caixa")


class MemberPhoto(Base):
    """Foto del soci. Només s'hi afegeixen files (la més recent és la vigent); la imatge va xifrada."""
    __tablename__ = "member_photos"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    mime: Mapped[str] = mapped_column(String(20))
    img_enc: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))


@event.listens_for(MemberPhoto, "before_update")
@event.listens_for(MemberPhoto, "before_delete")
def _immutable_photo(mapper, connection, target):
    raise ImmutableError("Les fotos no es poden modificar ni esborrar: puja'n una de nova")


class MemberCard(Base):
    """Carnet (RFID, codi de barres…) d'un soci. Només es desa l'empremta HMAC del codi, mai el codi."""
    __tablename__ = "member_cards"
    __table_args__ = (UniqueConstraint("local_id", "code_idx"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    local_id: Mapped[int] = mapped_column(ForeignKey("locals.id"))
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    code_idx: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    creat: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    creat_per: Mapped[int] = mapped_column(ForeignKey("users.id"))


class LoginAttempt(Base):
    """Intents d'entrada fallits recents, per bloquejar temporalment un nom d'usuari (també si no existeix)."""
    __tablename__ = "login_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(60), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LocalSetting(Base):
    """Ajustos opcionals d'un local (clau/valor). Taula a part perquè afegir-ne no canviï la taula `locals`."""
    __tablename__ = "local_settings"
    local_id: Mapped[int] = mapped_column(ForeignKey("locals.id"), primary_key=True)
    clau: Mapped[str] = mapped_column(String(40), primary_key=True)
    valor: Mapped[str] = mapped_column(String(200))


# Índexs per a les consultes habituals (estoc, caixa, informes, assistència). Les taules que ja existeixen els
# reben amb `python -m app.cli actualitzar-bd`.
Index("ix_stock_mov_product", StockMovement.product_id)
Index("ix_stock_mov_local_ts", StockMovement.local_id, StockMovement.ts)
Index("ix_stock_mov_member_ts", StockMovement.member_id, StockMovement.ts)
Index("ix_cash_entries_local_ts", CashEntry.local_id, CashEntry.ts)
Index("ix_cash_entries_session", CashEntry.session_id)
Index("ix_checkins_local_ts", CheckIn.local_id, CheckIn.ts)
Index("ix_time_events_user", TimeEvent.user_id, TimeEvent.id)
Index("ix_members_local", Member.local_id)
Index("ix_sessions_user", SessionToken.user_id)
Index("ix_sessions_exp", SessionToken.expires_at)
Index("ix_quotes_member", Quota.member_id)
Index("ix_cards_member", MemberCard.member_id)
Index("ix_photos_member", MemberPhoto.member_id)
Index("ix_products_local", Product.local_id)


class DeviceProfile(Base):
    """Perfil d'un dispositiu (bàscula, tauleta de signatura, lector de carnets) d'un local. La configuració va en JSON
    validat pel servidor; la connexió física (port sèrie, etc.) la tria cada navegador."""
    __tablename__ = "device_profiles"
    __table_args__ = (UniqueConstraint("local_id", "kind", "nom"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    local_id: Mapped[int] = mapped_column(ForeignKey("locals.id"))
    kind: Mapped[str] = mapped_column(String(12))  # bascula | signatura | lector
    nom: Mapped[str] = mapped_column(String(60))
    config: Mapped[str] = mapped_column(Text)
    per_defecte: Mapped[bool] = mapped_column(Boolean, default=False)
    creat: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


Index("ix_device_profiles_local", DeviceProfile.local_id, DeviceProfile.kind)


class ProductImage(Base):
    """Miniatura d'un producte (una per producte, es pot substituir). No són dades personals: no va xifrada."""
    __tablename__ = "product_images"
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), primary_key=True)
    mime: Mapped[str] = mapped_column(String(20))
    data: Mapped[str] = mapped_column(Text)  # base64
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Discount(Base):
    """Descompte configurable d'un local: percentatge o import fix per gram, per a tot, una categoria o un producte."""
    __tablename__ = "discounts"
    __table_args__ = (UniqueConstraint("local_id", "nom"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    local_id: Mapped[int] = mapped_column(ForeignKey("locals.id"))
    nom: Mapped[str] = mapped_column(String(60))
    tipus: Mapped[str] = mapped_column(String(10))  # percent | import_g
    valor: Mapped[int] = mapped_column(Integer)  # percent: 1-100; import_g: cèntims per gram
    ambit: Mapped[str] = mapped_column(String(10))  # tot | categoria | producte
    categoria: Mapped[str | None] = mapped_column(String(60), nullable=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    inici: Mapped[date | None] = mapped_column(Date, nullable=True)
    fi: Mapped[date | None] = mapped_column(Date, nullable=True)
    actiu: Mapped[bool] = mapped_column(Boolean, default=True)


class MovementDiscount(Base):
    """Descompte aplicat a una dispensació. Només d'afegir: guarda l'import original i el descomptat."""
    __tablename__ = "movement_discounts"
    movement_id: Mapped[int] = mapped_column(ForeignKey("stock_movements.id"), primary_key=True)
    discount_id: Mapped[int] = mapped_column(ForeignKey("discounts.id"))
    nom: Mapped[str] = mapped_column(String(60))
    original_cent: Mapped[int] = mapped_column(Integer)
    descompte_cent: Mapped[int] = mapped_column(Integer)


@event.listens_for(MovementDiscount, "before_update")
@event.listens_for(MovementDiscount, "before_delete")
def _immutable_movement_discount(mapper, connection, target):
    raise ImmutableError("Els descomptes aplicats no es poden modificar ni esborrar: corregeix la dispensació")


Index("ix_discounts_local", Discount.local_id)
