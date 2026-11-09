"""S1/S2: la funció SECURITY DEFINER club_buida_binaris no es pot enganyar des del rol de l'aplicació
(taules temporals que fan ombra) i calcula ella mateixa la retenció amb una configuració que l'aplicació no pot escriure."""
import secrets

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app import schema, service
from app.db import make_session_factory
from app.models import Member
from tests.test_api import ctx, env, token  # noqa: F401
from tests.test_rgpd_nucli import _admin, _dades_personals, _soci, pg_only

ROLE = "club_app_buida"


@pytest.fixture
def app_pg(ctx):
    client, owner_factory, sec = ctx
    with owner_factory() as s:
        owner_engine = s.get_bind()
        nom = s.execute(text("SELECT current_schema()")).scalar()
        propietari = s.execute(text("SELECT current_user")).scalar()
    pw = secrets.token_urlsafe(16)
    schema.create_app_role(owner_engine, ROLE, pw)
    schema.grant_app_role(owner_engine, ROLE)
    eng = create_engine(owner_engine.url.set(username=ROLE, password=pw), connect_args={"options": f"-csearch_path={nom}"})
    yield eng, client, sec, owner_factory, owner_engine, propietari
    eng.dispose()


@pg_only
def test_s1_el_rol_de_l_aplicacio_no_pot_crear_taules_temporals(app_pg):
    eng = app_pg[0]
    with eng.connect() as c:
        with pytest.raises(DBAPIError):
            c.execute(text("CREATE TEMP TABLE x (a int)"))


@pg_only
def test_s1_taules_temporals_no_fan_ombra_a_la_funcio_definer(app_pg):
    eng, client, sec, owner_factory, owner_engine, propietari = app_pg
    enc = token(client, sec, "enc")
    mid = _soci(client, enc)
    _dades_personals(client, enc, mid)
    # defensa en profunditat: encara que algú hagués donat TEMP al rol, el search_path fix (pg_temp al final) ho neutralitza
    with owner_factory() as s:
        s.execute(text(f'GRANT TEMPORARY ON DATABASE "{s.execute(text("SELECT current_database()")).scalar()}" TO {ROLE}'))
        s.commit()
    with eng.connect() as c:
        for sql in ("CREATE TEMP TABLE proof (u text)",
                    "CREATE TEMP TABLE members (id int, estat text, baixa_en timestamptz, suprimit_en timestamptz)",
                    f"INSERT INTO pg_temp.members VALUES ({mid}, 'baixa', now() - interval '10 years', NULL)",
                    "CREATE TEMP TABLE member_photos (id int, member_id int, img_enc text, sha256 text, ts timestamptz)",
                    f"INSERT INTO pg_temp.member_photos VALUES (1, {mid}, 'x', 'x', now())",
                    "CREATE TEMP TABLE club_retencio_cfg (clau text, valor int)",
                    "INSERT INTO pg_temp.club_retencio_cfg VALUES ('min_dies_baixa', 0)",
                    "CREATE FUNCTION pg_temp.pwn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
                    "INSERT INTO pg_temp.proof VALUES (current_user); RETURN NEW; END $$",
                    "CREATE TRIGGER t BEFORE UPDATE ON pg_temp.member_photos FOR EACH ROW EXECUTE FUNCTION pg_temp.pwn()"):
            c.execute(text(sql))
        c.commit()
        for crida in ("SELECT club_buida_binaris(:m, 'tot')", "SELECT club_buida_binaris(:m, 'tot', now())"):  # nova i antiga signatura
            try:
                c.execute(text(crida), {"m": mid})
                c.commit()  # si l'atac funciona, la prova (fila a la taula temporal) ha de sobreviure
            except DBAPIError:
                c.rollback()
        executats = [r[0] for r in c.execute(text("SELECT u FROM pg_temp.proof"))]
    assert propietari not in executats, "codi de l'atacant executat com a propietari"


@pg_only
def test_s2_la_funcio_aplica_la_retencio_i_no_accepta_tall_arbitrari(app_pg):
    eng, client, sec, owner_factory, owner_engine, propietari = app_pg
    enc = token(client, sec, "enc")
    mid = _soci(client, enc)
    _dades_personals(client, enc, mid)
    with owner_factory() as s:
        service.set_member_status(s, _admin(s), s.get(Member, mid), "baixa")
    schema.set_retention(owner_engine, min_dies=365, fotos_dies=365)
    with eng.connect() as c:
        with pytest.raises(DBAPIError):  # de baixa fa un moment: la retenció (de la BD) ho impedeix
            c.execute(text("SELECT club_buida_binaris(:m, 'tot')"), {"m": mid})
        c.rollback()
        with pytest.raises(DBAPIError):  # ja no existeix la versió amb tall arbitrari
            c.execute(text("SELECT club_buida_binaris(:m, 'fotos_velles', 'infinity'::timestamptz)"), {"m": 0})
        c.rollback()
        # fotos_velles: el tall el calcula la funció (365 d), les fotos d'ara no es toquen
        assert c.execute(text("SELECT club_buida_binaris(0, 'fotos_velles')")).scalar() == 0
        c.rollback()
        # l'aplicació no pot canviar la configuració ni tocar el rastre
        for sql in ("UPDATE club_retencio_cfg SET valor = 0", "INSERT INTO club_retencio_cfg VALUES ('x', 1)",
                    "SELECT * FROM club_buida_log", "DELETE FROM club_buida_log", "INSERT INTO club_buida_log (mode) VALUES ('x')"):
            with pytest.raises(DBAPIError):
                c.execute(text(sql))
            c.rollback()
    schema.set_retention(owner_engine, min_dies=0, fotos_dies=365)
    with eng.connect() as c:
        assert c.execute(text("SELECT club_buida_binaris(:m, 'tot')"), {"m": mid}).scalar() == 2
        c.commit()
    with owner_factory() as s:
        fila = s.execute(text("SELECT member_id, mode, n FROM club_buida_log")).all()
    assert [tuple(r) for r in fila] == [(mid, "tot", 2)]
