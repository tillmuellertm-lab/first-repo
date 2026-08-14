"""Aufbereitung der Scans fuer die Analyse.

Die Anthropic-API nimmt PDFs und Bilder direkt entgegen, eine eigene OCR-Stufe
ist deshalb nicht noetig. Dieses Modul kuemmert sich um die Randbedingungen:
Seitenzahl, Dateigroesse, Bildkantenlaenge und das Zerlegen von Sammelscans.
"""

from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOG = logging.getLogger(__name__)

# Grenzen der Anthropic-API mit etwas Sicherheitsabstand.
MAX_PDF_SEITEN = 30
MAX_BILDKANTE = 1568
MAX_BILD_BYTES = 4_500_000
MAX_TEXT_ZEICHEN = 60_000

BILDTYPEN = {"image/png", "image/jpeg", "image/gif", "image/webp"}


class ExtraktionsFehler(RuntimeError):
    pass


@dataclass
class Inhalt:
    """Fuer die API aufbereiteter Dokumentinhalt."""

    bloecke: list[dict[str, Any]]
    seiten: int | None = None
    gekuerzt: bool = False
    textvorschau: str = ""
    hinweise: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.hinweise is None:
            self.hinweise = []


def _pypdf():
    try:
        import pypdf  # noqa: PLC0415
    except ImportError as fehler:  # pragma: no cover - Abhaengigkeit fehlt
        raise ExtraktionsFehler(
            "Fuer PDF-Verarbeitung wird 'pypdf' benoetigt: pip install pypdf"
        ) from fehler
    return pypdf


def _pillow():
    try:
        from PIL import Image  # noqa: PLC0415
    except ImportError:
        return None
    return Image


def seitenzahl(pfad: Path) -> int | None:
    if pfad.suffix.lower() != ".pdf":
        return None
    try:
        pypdf = _pypdf()
        with pfad.open("rb") as datei:
            return len(pypdf.PdfReader(datei).pages)
    except ExtraktionsFehler:
        raise
    except Exception as fehler:  # beschaedigte PDFs sollen nicht den Lauf stoppen
        LOG.warning("Seitenzahl von %s nicht ermittelbar: %s", pfad.name, fehler)
        return None


def pdf_text(pfad: Path, max_seiten: int = MAX_PDF_SEITEN) -> str:
    """Liest die Textebene eines PDFs, sofern vorhanden."""
    try:
        pypdf = _pypdf()
        with pfad.open("rb") as datei:
            leser = pypdf.PdfReader(datei)
            teile = []
            for seite in leser.pages[:max_seiten]:
                teile.append(seite.extract_text() or "")
        return "\n".join(teile).strip()
    except Exception as fehler:
        LOG.debug("Keine Textebene in %s: %s", pfad.name, fehler)
        return ""


def _pdf_kuerzen(pfad: Path, max_seiten: int) -> bytes:
    pypdf = _pypdf()
    with pfad.open("rb") as datei:
        leser = pypdf.PdfReader(datei)
        schreiber = pypdf.PdfWriter()
        for seite in leser.pages[:max_seiten]:
            schreiber.add_page(seite)
        puffer = io.BytesIO()
        schreiber.write(puffer)
    return puffer.getvalue()


def _bild_aufbereiten(pfad: Path, medientyp: str) -> tuple[bytes, str, list[str]]:
    """Skaliert zu grosse Bilder herunter, damit sie die API-Grenzen einhalten."""
    rohdaten = pfad.read_bytes()
    hinweise: list[str] = []
    Image = _pillow()
    if Image is None:
        if len(rohdaten) > MAX_BILD_BYTES:
            raise ExtraktionsFehler(
                f"{pfad.name} ist zu gross fuer die Analyse und 'Pillow' fehlt zum Verkleinern: "
                "pip install Pillow"
            )
        return rohdaten, medientyp, hinweise

    with Image.open(io.BytesIO(rohdaten)) as bild:
        bild.load()
        breite, hoehe = bild.size
        aendern = max(breite, hoehe) > MAX_BILDKANTE or len(rohdaten) > MAX_BILD_BYTES
        if not aendern:
            return rohdaten, medientyp, hinweise
        faktor = min(1.0, MAX_BILDKANTE / max(breite, hoehe))
        neue_groesse = (max(1, int(breite * faktor)), max(1, int(hoehe * faktor)))
        verkleinert = bild.convert("RGB").resize(neue_groesse, Image.LANCZOS)
        puffer = io.BytesIO()
        verkleinert.save(puffer, format="JPEG", quality=85, optimize=True)
        daten = puffer.getvalue()
        while len(daten) > MAX_BILD_BYTES and verkleinert.size[0] > 400:
            verkleinert = verkleinert.resize(
                (int(verkleinert.size[0] * 0.8), int(verkleinert.size[1] * 0.8)), Image.LANCZOS
            )
            puffer = io.BytesIO()
            verkleinert.save(puffer, format="JPEG", quality=80, optimize=True)
            daten = puffer.getvalue()
        hinweise.append(f"Bild fuer die Analyse auf {verkleinert.size[0]}x{verkleinert.size[1]} Pixel verkleinert.")
        return daten, "image/jpeg", hinweise


def inhalt_aufbereiten(pfad: Path, medientyp: str) -> Inhalt:
    """Baut die Inhaltsbloecke fuer einen API-Aufruf."""
    pfad = Path(pfad)
    if not pfad.is_file():
        raise ExtraktionsFehler(f"Datei nicht gefunden: {pfad}")

    if medientyp == "application/pdf":
        seiten = seitenzahl(pfad)
        gekuerzt = bool(seiten and seiten > MAX_PDF_SEITEN)
        rohdaten = _pdf_kuerzen(pfad, MAX_PDF_SEITEN) if gekuerzt else pfad.read_bytes()
        hinweise = []
        if gekuerzt:
            hinweise.append(
                f"Nur die ersten {MAX_PDF_SEITEN} von {seiten} Seiten wurden analysiert."
            )
        block = {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.standard_b64encode(rohdaten).decode("ascii"),
            },
        }
        return Inhalt(
            bloecke=[block],
            seiten=seiten,
            gekuerzt=gekuerzt,
            textvorschau=pdf_text(pfad)[:2000],
            hinweise=hinweise,
        )

    if medientyp in BILDTYPEN:
        daten, typ, hinweise = _bild_aufbereiten(pfad, medientyp)
        block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": typ,
                "data": base64.standard_b64encode(daten).decode("ascii"),
            },
        }
        return Inhalt(bloecke=[block], seiten=1, hinweise=hinweise)

    if medientyp.startswith("text/"):
        text = pfad.read_text(encoding="utf-8", errors="replace")
        gekuerzt = len(text) > MAX_TEXT_ZEICHEN
        block = {"type": "text", "text": text[:MAX_TEXT_ZEICHEN]}
        return Inhalt(
            bloecke=[block],
            seiten=1,
            gekuerzt=gekuerzt,
            textvorschau=text[:2000],
            hinweise=["Textdatei wurde gekuerzt."] if gekuerzt else [],
        )

    raise ExtraktionsFehler(f"Nicht unterstuetzter Medientyp: {medientyp}")


def pdf_zerlegen(pfad: Path, segmente: list[tuple[int, int]], zielordner: Path, basisname: str) -> list[Path]:
    """Zerlegt einen Sammelscan in einzelne PDFs.

    ``segmente`` enthaelt 1-basierte, inklusive Seitenbereiche.
    """
    pypdf = _pypdf()
    zielordner.mkdir(parents=True, exist_ok=True)
    erzeugt: list[Path] = []
    with pfad.open("rb") as datei:
        leser = pypdf.PdfReader(datei)
        gesamt = len(leser.pages)
        for nummer, (von, bis) in enumerate(segmente, start=1):
            von = max(1, min(von, gesamt))
            bis = max(von, min(bis, gesamt))
            schreiber = pypdf.PdfWriter()
            for index in range(von - 1, bis):
                schreiber.add_page(leser.pages[index])
            ziel = zielordner / f"{basisname}_teil{nummer:02d}_S{von:02d}-{bis:02d}.pdf"
            with ziel.open("wb") as ausgabe:
                schreiber.write(ausgabe)
            erzeugt.append(ziel)
    return erzeugt
