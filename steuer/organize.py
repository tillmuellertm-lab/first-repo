"""Aufbereitete Ablage: Umbenennen, Einsortieren, Paket fuer den Steuerberater.

Die Originale im Eingang bleiben unangetastet. Die Ablage wird bei jedem Lauf
neu aufgebaut, damit sie immer den aktuellen Analysestand widerspiegelt.
"""

from __future__ import annotations

import shutil
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from . import naming, taxonomy
from .models import Dokument
from .workspace import Arbeitsmappe


@dataclass
class Ablageergebnis:
    wurzel: Path
    dateien: dict[str, Path] = field(default_factory=dict)  # dokument_id -> Zielpfad
    uebersprungen: list[tuple[str, str]] = field(default_factory=list)  # (dateiname, Grund)

    @property
    def anzahl(self) -> int:
        return len(self.dateien)


def _sortierschluessel(dokument: Dokument) -> tuple:
    analyse = dokument.analyse
    datum = (analyse.datum if analyse and analyse.datum else "9999-99-99")
    return (datum, dokument.dateiname)


def ablage_erzeugen(
    mappe: Arbeitsmappe,
    zielordner: Path | None = None,
    ungeeignete_mitnehmen: bool = True,
) -> Ablageergebnis:
    """Baut die nach Anlagen sortierte Kopie des Dokumentenbestands auf.

    Nur die Dokumente des Veranlagungsjahres. Der Steuerberater bekommt sonst
    Belege fremder Jahre mitgeliefert, waehrend die Kennzahlen des Berichts sie
    zu Recht aussen vor lassen - eine Ablage, die etwas anderes enthaelt als der
    Bericht behauptet, ist schlimmer als gar keine.
    """
    ziel = Path(zielordner) if zielordner else mappe.aufbereitet / str(mappe.jahr)
    if ziel.exists():
        shutil.rmtree(ziel)
    ziel.mkdir(parents=True, exist_ok=True)

    nach_kategorie: dict[str, list[Dokument]] = defaultdict(list)
    for dokument in mappe.jahresansicht().eigene:
        nach_kategorie[dokument.wirksame_kategorie].append(dokument)

    ergebnis = Ablageergebnis(wurzel=ziel)

    for kategorie in taxonomy.KATEGORIEN:
        dokumente = nach_kategorie.get(kategorie.id, [])
        if not dokumente:
            continue
        if kategorie.id in taxonomy.AUSGESCHLOSSEN and not ungeeignete_mitnehmen:
            for dokument in dokumente:
                ergebnis.uebersprungen.append((dokument.dateiname, "nicht steuerrelevant"))
            continue

        ordner = ziel / kategorie.ordner
        ordner.mkdir(parents=True, exist_ok=True)
        vergeben: set[str] = set()

        for nummer, dokument in enumerate(sorted(dokumente, key=_sortierschluessel), start=1):
            quelle = mappe.pfad_zu(dokument)
            if not quelle.exists():
                ergebnis.uebersprungen.append((dokument.dateiname, "Originaldatei fehlt"))
                continue
            name = naming.eindeutig_machen(
                naming.dateiname(dokument, nummer, mappe.jahr), vergeben
            )
            zielpfad = ordner / name
            shutil.copy2(quelle, zielpfad)
            dokument.zieldateiname = name
            dokument.zielordner = kategorie.ordner
            ergebnis.dateien[dokument.id] = zielpfad

        _ordnerinhalt_schreiben(ordner, kategorie, sorted(dokumente, key=_sortierschluessel))

    return ergebnis


def _ordnerinhalt_schreiben(
    ordner: Path, kategorie: taxonomy.Kategorie, dokumente: list[Dokument]
) -> None:
    """Legt in jedem Ordner eine kurze Inhaltsangabe ab."""
    zeilen = [
        f"# {kategorie.label}",
        "",
        f"Anlage: {kategorie.anlage}",
        "",
        kategorie.beschreibung,
        "",
        "## Inhalt",
        "",
    ]
    for dokument in dokumente:
        if not dokument.zieldateiname:
            continue
        analyse = dokument.analyse
        beschreibung = analyse.zusammenfassung if analyse else "noch nicht analysiert"
        zeilen.append(f"- **{dokument.zieldateiname}**  \n  {beschreibung}")
        if analyse and analyse.fehlende_nachweise:
            zeilen.append("  Fehlt noch: " + "; ".join(analyse.fehlende_nachweise))
    zeilen.append("")
    (ordner / "_INHALT.md").write_text("\n".join(zeilen), encoding="utf-8")


def paket_erzeugen(mappe: Arbeitsmappe, ablage: Ablageergebnis, zusatzdateien: list[Path] | None = None) -> Path:
    """Packt die aufbereitete Ablage samt Berichten in ein ZIP fuer den Steuerberater."""
    mappe.berichte.mkdir(parents=True, exist_ok=True)
    ziel = mappe.berichte / f"Steuerunterlagen_{mappe.jahr}.zip"
    with zipfile.ZipFile(ziel, "w", compression=zipfile.ZIP_DEFLATED) as archiv:
        for pfad in sorted(ablage.wurzel.rglob("*")):
            if pfad.is_file():
                archiv.write(pfad, pfad.relative_to(ablage.wurzel.parent))
        for pfad in zusatzdateien or []:
            if Path(pfad).is_file():
                archiv.write(pfad, Path(pfad).name)
    return ziel
