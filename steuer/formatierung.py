"""Zahlenformate in deutscher Schreibweise.

Bewusst ohne ``locale``: die Umgebung, in der das Werkzeug laeuft, ist nicht
vorhersagbar, die Ausgabe soll es sein.
"""

from __future__ import annotations


def zahl(wert: float | int | None, nachkomma: int = 2) -> str:
    """Formatiert eine Zahl mit Tausenderpunkt und Dezimalkomma."""
    if wert is None:
        return "—"
    text = f"{float(wert):,.{nachkomma}f}"
    return text.replace(",", "#").replace(".", ",").replace("#", ".")


def euro(wert: float | int | None, nachkomma: int = 2) -> str:
    """Formatiert einen Betrag als '1.234,56 EUR'."""
    if wert is None:
        return "—"
    return f"{zahl(wert, nachkomma)} EUR"
