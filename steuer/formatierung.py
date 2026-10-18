"""Zahlenformate in deutscher Schreibweise.

Bewusst ohne ``locale``: die Umgebung, in der das Werkzeug laeuft, ist nicht
vorhersagbar, die Ausgabe soll es sein.
"""

from __future__ import annotations


def zahl_lesen(text: str | float | int | None) -> float | None:
    """Liest eine Zahl in deutscher oder englischer Schreibweise.

    Der Punkt ist mehrdeutig: In "132.052" trennt er Tausender, in "6.5" die
    Nachkommastellen. Wer ihn pauschal entfernt, macht aus einer gespeicherten
    6.0 beim naechsten Speichern eine 60 - der Wert waechst mit jedem Durchlauf
    um den Faktor zehn. Deshalb hier eine Entscheidung nach Stellenzahl.
    """
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)

    roh = str(text).strip().replace(" ", "").replace(" ", "")
    for zeichen in ("€", "EUR", "eur", "km", "%"):
        roh = roh.replace(zeichen, "")
    roh = roh.strip()
    if not roh:
        return None

    vorzeichen = -1.0 if roh.startswith("-") else 1.0
    roh = roh.lstrip("+-")

    if "," in roh and "." in roh:
        # Das zuletzt stehende Zeichen trennt die Nachkommastellen.
        if roh.rfind(",") > roh.rfind("."):
            roh = roh.replace(".", "").replace(",", ".")
        else:
            roh = roh.replace(",", "")
    elif "," in roh:
        roh = roh.replace(",", ".")
    elif roh.count(".") > 1:
        roh = roh.replace(".", "")  # 1.234.567
    elif "." in roh:
        vor, _, nach = roh.partition(".")
        # Genau drei Ziffern dahinter und Ziffern davor: Tausenderpunkt.
        # Alles andere - auch das ".0" aus einem Formularfeld - ist dezimal.
        if len(nach) == 3 and vor.isdigit() and nach.isdigit():
            roh = vor + nach

    try:
        return vorzeichen * float(roh)
    except ValueError:
        return None


def eingabewert(wert: float | int | None) -> str:
    """Stellt eine Zahl so dar, dass sie unveraendert zurueckgelesen wird."""
    if wert is None:
        return ""
    if isinstance(wert, int) or float(wert).is_integer():
        return str(int(wert))
    return f"{float(wert):.2f}".replace(".", ",")


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
