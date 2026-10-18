"""Benennung der aufbereiteten Dateien.

Ziel ist ein Name, der im Dateimanager sortierbar ist und dem Steuerberater
schon in der Dateiliste sagt, worum es geht:

    03_2024-03-15_Handwerkerrechnung_Elektro-Meier_1189-42EUR_PRUEFEN.pdf
    ^  ^          ^                  ^             ^          ^
    |  |          |                  |             |          Kennzeichnung, wenn etwas fehlt
    |  |          |                  |             Betrag
    |  |          |                  Aussteller
    |  |          Dokumentart
    |  Belegdatum
    Laufende Nummer innerhalb des Ordners
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import EIGNUNG_BEDINGT, EIGNUNG_UNGEEIGNET, EIGNUNG_UNKLAR, Dokument
from .workspace import sichere_bezeichnung

MARKIERUNG_PRUEFEN = "PRUEFEN"
MARKIERUNG_UNGEEIGNET = "NICHT-EINREICHEN"
MARKIERUNG_UNKLAR = "UNKLAR"


def betrag_als_text(betrag: float | None, waehrung: str = "EUR") -> str:
    if betrag is None:
        return ""
    gerundet = round(float(betrag), 2)
    ganz = int(abs(gerundet))
    nachkomma = int(round((abs(gerundet) - ganz) * 100))
    vorzeichen = "minus" if gerundet < 0 else ""
    return f"{vorzeichen}{ganz}-{nachkomma:02d}{sichere_bezeichnung(waehrung or 'EUR', 6)}"


def datum_als_text(dokument: Dokument, fallback_jahr: int) -> str:
    analyse = dokument.analyse
    if analyse and analyse.datum and re.fullmatch(r"\d{4}-\d{2}-\d{2}", analyse.datum):
        return analyse.datum
    if analyse and analyse.steuerjahr:
        return f"{analyse.steuerjahr}-00-00"
    return f"{fallback_jahr}-00-00"


def dateiname(dokument: Dokument, laufende_nummer: int, fallback_jahr: int) -> str:
    """Baut den Zieldateinamen fuer ein Dokument."""
    analyse = dokument.analyse
    endung = Path(dokument.dateiname).suffix.lower() or ".pdf"

    teile = [f"{laufende_nummer:02d}", datum_als_text(dokument, fallback_jahr)]

    typ = sichere_bezeichnung(analyse.dokumenttyp if analyse else "", 40)
    if not typ:
        typ = sichere_bezeichnung(Path(dokument.dateiname).stem, 40) or "Dokument"
    teile.append(typ)

    aussteller = sichere_bezeichnung(analyse.aussteller if analyse else "", 32)
    if aussteller:
        teile.append(aussteller)

    betrag = betrag_als_text(
        (analyse.betrag_abzugsfaehig or analyse.betrag_gesamt) if analyse else None,
        analyse.waehrung if analyse else "EUR",
    )
    if betrag:
        teile.append(betrag)

    if analyse:
        if analyse.eignung == EIGNUNG_BEDINGT:
            teile.append(MARKIERUNG_PRUEFEN)
        elif analyse.eignung == EIGNUNG_UNGEEIGNET:
            teile.append(MARKIERUNG_UNGEEIGNET)
        elif analyse.eignung == EIGNUNG_UNKLAR:
            teile.append(MARKIERUNG_UNKLAR)

    name = "_".join(t for t in teile if t)
    return f"{name[:150]}{endung}"


def eindeutig_machen(name: str, vergeben: set[str]) -> str:
    if name not in vergeben:
        vergeben.add(name)
        return name
    stamm, endung = Path(name).stem, Path(name).suffix
    zaehler = 2
    while f"{stamm}-{zaehler}{endung}" in vergeben:
        zaehler += 1
    eindeutig = f"{stamm}-{zaehler}{endung}"
    vergeben.add(eindeutig)
    return eindeutig
