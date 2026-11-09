from sqlalchemy import select, text

from app import cli, migracio_genetic
from app.models import LocalSetting, Product
from tests.test_api import ctx, env  # noqa: F401
from tests.test_migracio import bd_antiga, entorn  # noqa: F401


def test_categories():
    for c in ("Flor", "flores CBD", "Hash", "Haixix", "Hachís", "Extractes", "Clons", "Llavors", "Semillas", "Seeds"):
        assert migracio_genetic.es_genetic_per_categoria(c), c
    for c in ("Accessoris", "Begudes", "", "Papers", "Grinders"):
        assert not migracio_genetic.es_genetic_per_categoria(c), c


def _prods(factory, noms_cat):
    s = factory()
    from app.models import Local
    for n, c in noms_cat:
        s.add(Product(local_id=1, nom=n, categoria=c, preu_cent_per_g=100))
    s.commit()
    s.close()


def test_migracio_marca_una_sola_vegada_i_llista_pendents(ctx):
    _, factory, _ = ctx
    _prods(factory, [("OG", "Flor"), ("Pol", "Hash"), ("Grinder", "Accessoris"), ("Flor mix", "Varis"), ("Sense", "")])
    with factory() as db:
        r = migracio_genetic.migra(db)
        assert sorted(f["nom"] for f in r["marcats"]) == ["OG", "Pol"]
        assert sorted(f["nom"] for f in r["pendents"]) == ["Flor mix", "Grinder", "Sense"]
        assert next(f for f in r["pendents"] if f["nom"] == "Flor mix")["pista"] is True
        assert db.get(LocalSetting, (1, migracio_genetic.MARCA)) is not None
    # una persona desmarca un producte: la migració no el torna a marcar
    with factory() as db:
        db.scalar(select(Product).where(Product.nom == "OG")).es_genetic = False
        db.commit()
        r2 = migracio_genetic.migra(db)
        assert r2["marcats"] == [] and r2["locals_ja_fets"] >= 1
        assert db.scalar(select(Product.es_genetic).where(Product.nom == "OG")) is False


def test_si_el_local_ja_esta_classificat_no_es_toca(ctx):
    _, factory, _ = ctx
    _prods(factory, [("OG", "Flor"), ("Pol", "Hash")])
    with factory() as db:
        db.scalar(select(Product).where(Product.nom == "OG")).es_genetic = True
        db.commit()
        r = migracio_genetic.migra(db)
        assert r["marcats"] == [] and [f["nom"] for f in r["pendents"]] == ["Pol"]


def test_actualitzar_bd_executa_la_migracio_i_la_mostra(entorn, capsys):
    engine = bd_antiga(entorn)
    with engine.begin() as c:
        c.execute(text("INSERT INTO locals (id, nom) VALUES (1, 'L')"))
        c.execute(text("INSERT INTO products (local_id, nom, categoria, preu_cent_per_g, actiu, es_genetic) VALUES (1,'OG','Flor',800,1,0),(1,'Bong','Accessoris',500,1,0)"))
    assert cli.main(["actualitzar-bd"]) == 0
    sortida = capsys.readouterr().out
    assert "marcats com a genètics: 1" in sortida and "Bong" in sortida
    with engine.connect() as c:
        assert dict(c.execute(text("SELECT nom, es_genetic FROM products")).all()) == {"OG": 1, "Bong": 0} or \
            dict(c.execute(text("SELECT nom, es_genetic FROM products")).all()) == {"OG": True, "Bong": False}
    assert cli.main(["actualitzar-bd"]) == 0
    assert "marcats" not in capsys.readouterr().out  # segona vegada: res a fer


def test_verificar_auditoria(entorn, capsys):
    bd_antiga(entorn)
    assert cli.main(["actualitzar-bd"]) == 0
    assert cli.main(["verificar-auditoria"]) == 0
    assert "INTEGRA" in capsys.readouterr().out
