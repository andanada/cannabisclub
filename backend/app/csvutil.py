"""Utilitats de CSV."""
import csv
import io

# Un full de càlcul interpreta com a fórmula qualsevol cel·la que comenci per aquests caràcters.
_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def cell(value):
    """Neutralitza text que un full de càlcul executaria com a fórmula (p. ex. un producte anomenat «=HYPERLINK(…)»).
    Els números passen tal qual: només es toquen els textos."""
    if isinstance(value, str) and value.startswith(_FORMULA):
        return "'" + value
    return value


def to_csv(header: list[str], rows) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(header)
    for r in rows:
        w.writerow([cell(v) for v in r])
    return out.getvalue()
