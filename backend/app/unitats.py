"""Conversió única entre grams (Decimal) i mil·ligrams (enter). Una sola regla d'arrodoniment a tot el programa."""
from decimal import ROUND_HALF_UP, Decimal


def g_to_mg(g) -> int:
    """Grams -> mg arrodonint cap amunt a partir de la meitat. Sense signe: el control de rang és del cridador."""
    return int((Decimal(g) * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def mg_to_g(mg) -> str:
    """mg -> text en grams (Decimal exacte, sense pèrdua)."""
    return str(Decimal(int(mg)) / 1000)
