"""COLUMNES_NOVES és un diccionari: una clau repetida en sobreescriu una altra en silenci i la columna no s'afegeix a les bases de dades existents."""
import ast
from pathlib import Path


def test_columnes_noves_no_te_claus_repetides():
    arbre = ast.parse((Path(__file__).resolve().parents[1] / "app" / "schema.py").read_text(encoding="utf-8"))
    for node in ast.walk(arbre):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "COLUMNES_NOVES" for t in node.targets):
            claus = [k.value for k in node.value.keys]
            repetides = {c for c in claus if claus.count(c) > 1}
            assert not repetides, f"claus repetides a COLUMNES_NOVES: {repetides}"
            return
    raise AssertionError("COLUMNES_NOVES no trobat")


def test_totes_les_columnes_dels_models_noves_estan_a_columnes_noves_o_a_la_taula_base():
    """Cada columna afegida recentment als models ha de ser a COLUMNES_NOVES (si no, una BD existent peta en consultar-la)."""
    from app import schema
    from app.models import InventoryCount, InventorySession, MemberIncident, Product, SessionToken
    esperades = {SessionToken: {"rol_dia"}, InventorySession: {"tipus", "control", "product_id", "ajustat"}, InventoryCount: {"brut_mg", "nota", "expected_mg"},
                 Product: {"preu_entrada_cent", "tara_mg", "sense_descomptes"}, MemberIncident: {"tipus", "alerta"}}
    for model, cols in esperades.items():
        declarades = {c for c, _ in schema.COLUMNES_NOVES.get(model.__tablename__, [])}
        assert cols <= declarades, (model.__tablename__, cols - declarades)
