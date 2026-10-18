"""Aktualisierung des hinterlegten Rechtsstands.

Das Werkzeug recherchiert die amtlichen Werte eines Veranlagungsjahres und legt
das Ergebnis als Entwurfsdatei neben der bestehenden Regeldatei ab. Uebernommen
wird der Entwurf erst nach ausdruecklicher Bestaetigung: ein Modell soll den
Rechtsstand vorschlagen, nicht unbemerkt veraendern.
"""

from __future__ import annotations

import datetime as _dt
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import rules
from .analyze import Analysedienst
from .rules import DATENVERZEICHNIS, Regelwerk


@dataclass
class Aenderung:
    schluessel: str
    label: str
    alt: float | None
    neu: float | None
    einheit: str = ""
    quelle: str = ""
    hinweis: str = ""

    @property
    def art(self) -> str:
        if self.alt is None:
            return "neu"
        if self.neu is None:
            return "entfallen"
        return "geaendert" if abs(self.alt - self.neu) > 1e-9 else "unveraendert"


@dataclass
class Updateergebnis:
    jahr: int
    entwurfspfad: Path
    berichtspfad: Path
    aenderungen: list[Aenderung] = field(default_factory=list)
    wesentliche_aenderungen: list[str] = field(default_factory=list)
    ungeklaert: list[str] = field(default_factory=list)
    quellen: list[str] = field(default_factory=list)
    fristen: dict[str, Any] = field(default_factory=dict)

    @property
    def relevante(self) -> list[Aenderung]:
        return [a for a in self.aenderungen if a.art != "unveraendert"]


def _basis_regelwerk(jahr: int) -> tuple[Regelwerk, int | None]:
    """Liefert den Ausgangspunkt fuer den Entwurf und das Jahr, von dem geerbt wird."""
    vorhandene = rules.verfuegbare_jahre()
    if jahr in vorhandene:
        return rules.laden(jahr, strikt=True), None
    fruehere = [j for j in vorhandene if j < jahr] or vorhandene
    if not fruehere:
        raise rules.RegelFehler("Es liegt keine einzige Regeldatei vor, auf der aufgebaut werden koennte.")
    quelle = max(fruehere)
    return rules.laden(quelle, strikt=True), quelle


def entwurf_erzeugen(jahr: int, dienst: Analysedienst | None = None) -> Updateergebnis:
    """Recherchiert den Rechtsstand und schreibt einen Entwurf zur Durchsicht."""
    dienst = dienst or Analysedienst()
    regelwerk, erbt_von = _basis_regelwerk(jahr)

    ergebnis_roh = dienst.rechtsstand_recherchieren(jahr, regelwerk.werte)

    aenderungen: list[Aenderung] = []
    neue_werte: dict[str, Any] = {}
    for eintrag in ergebnis_roh.get("werte") or []:
        if not isinstance(eintrag, dict):
            continue
        schluessel = str(eintrag.get("schluessel") or "").strip()
        if not schluessel:
            continue
        bisher = regelwerk.eintrag(schluessel)
        alt = bisher.get("wert")
        try:
            neu = float(eintrag.get("wert"))
        except (TypeError, ValueError):
            continue
        aenderung = Aenderung(
            schluessel=schluessel,
            label=str(eintrag.get("label") or bisher.get("label") or schluessel),
            alt=float(alt) if isinstance(alt, (int, float)) else None,
            neu=neu,
            einheit=str(eintrag.get("einheit") or bisher.get("einheit") or ""),
            quelle=str(eintrag.get("quelle") or ""),
            hinweis=str(eintrag.get("hinweis") or ""),
        )
        aenderungen.append(aenderung)
        if aenderung.art in ("neu", "geaendert"):
            datensatz = dict(bisher)
            datensatz.update(
                {
                    "label": aenderung.label,
                    "wert": neu,
                    "einheit": aenderung.einheit,
                }
            )
            if eintrag.get("rechtsgrundlage"):
                datensatz["rechtsgrundlage"] = str(eintrag["rechtsgrundlage"])
            hinweisteile = [t for t in (aenderung.hinweis, f"Quelle: {aenderung.quelle}" if aenderung.quelle else "") if t]
            if hinweisteile:
                datensatz["hinweis"] = " ".join(hinweisteile)
            neue_werte[schluessel] = datensatz

    fristen = {k: v for k, v in (ergebnis_roh.get("fristen") or {}).items() if v}

    entwurf: dict[str, Any] = {
        "jahr": jahr,
        "stand": _dt.date.today().isoformat(),
        "status": "entwurf",
        "hinweis": (
            "Maschinell recherchierter Entwurf. Vor der Uebernahme jeden Wert gegen die "
            "angegebene Quelle pruefen. Uebernahme mit "
            f"'steuer recht-uebernehmen --jahr {jahr}'."
        ),
    }
    if erbt_von:
        entwurf["erbt_von"] = erbt_von
    elif regelwerk.daten.get("erbt_von"):
        entwurf["erbt_von"] = regelwerk.daten["erbt_von"]
    quellen = [str(q) for q in ergebnis_roh.get("quellen") or []]
    if quellen:
        entwurf["quellen"] = quellen
    if neue_werte:
        entwurf["werte"] = neue_werte
    if fristen:
        entwurf["fristen"] = fristen

    DATENVERZEICHNIS.mkdir(parents=True, exist_ok=True)
    entwurfspfad = DATENVERZEICHNIS / f"{jahr}.vorschlag.yaml"
    entwurfspfad.write_text(
        yaml.safe_dump(entwurf, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )

    ergebnis = Updateergebnis(
        jahr=jahr,
        entwurfspfad=entwurfspfad,
        berichtspfad=DATENVERZEICHNIS / f"{jahr}.vorschlag.md",
        aenderungen=aenderungen,
        wesentliche_aenderungen=[str(x) for x in ergebnis_roh.get("wesentliche_aenderungen") or []],
        ungeklaert=[str(x) for x in ergebnis_roh.get("ungeklaert") or []],
        quellen=quellen,
        fristen=fristen,
    )
    ergebnis.berichtspfad.write_text(_bericht(ergebnis), encoding="utf-8")
    return ergebnis


def _bericht(ergebnis: Updateergebnis) -> str:
    zeilen = [
        f"# Rechtsstand {ergebnis.jahr} — Entwurf",
        "",
        f"Recherchiert am {_dt.date.today().strftime('%d.%m.%Y')}.",
        "",
        "## Abweichungen zum hinterlegten Stand",
        "",
    ]
    relevante = ergebnis.relevante
    if relevante:
        zeilen += ["| Wert | bisher | neu | Einheit | Quelle |", "| --- | ---: | ---: | --- | --- |"]
        for aenderung in relevante:
            alt = "—" if aenderung.alt is None else f"{aenderung.alt:g}"
            neu = "—" if aenderung.neu is None else f"{aenderung.neu:g}"
            zeilen.append(
                f"| {aenderung.label} | {alt} | {neu} | {aenderung.einheit} | {aenderung.quelle} |"
            )
    else:
        zeilen.append("Keine Abweichungen gefunden.")
    zeilen.append("")

    if ergebnis.fristen:
        zeilen += ["## Fristen", ""]
        for schluessel, wert in ergebnis.fristen.items():
            zeilen.append(f"- {schluessel}: {wert}")
        zeilen.append("")

    if ergebnis.wesentliche_aenderungen:
        zeilen += ["## Wesentliche Gesetzesaenderungen", ""]
        zeilen += [f"- {x}" for x in ergebnis.wesentliche_aenderungen]
        zeilen.append("")

    if ergebnis.ungeklaert:
        zeilen += ["## Nicht belastbar ermittelt", ""]
        zeilen += [f"- {x}" for x in ergebnis.ungeklaert]
        zeilen.append("")

    if ergebnis.quellen:
        zeilen += ["## Quellen", ""]
        zeilen += [f"- {x}" for x in ergebnis.quellen]
        zeilen.append("")

    zeilen += [
        "---",
        "",
        "Dieser Entwurf wurde maschinell erstellt. Er ist erst dann verlaesslich, wenn jeder",
        "Wert gegen die amtliche Quelle geprueft wurde.",
        "",
    ]
    return "\n".join(zeilen)


def entwurf_uebernehmen(jahr: int) -> Path:
    """Uebernimmt den Entwurf als gepflegte Regeldatei und sichert die bisherige."""
    entwurf = DATENVERZEICHNIS / f"{jahr}.vorschlag.yaml"
    if not entwurf.exists():
        raise rules.RegelFehler(
            f"Kein Entwurf fuer {jahr} vorhanden. Zuerst 'steuer recht-update --jahr {jahr}' ausfuehren."
        )
    daten = yaml.safe_load(entwurf.read_text(encoding="utf-8")) or {}
    daten["status"] = "gepflegt"
    daten["hinweis"] = (
        f"Aus dem Rechercheentwurf vom {daten.get('stand', 'unbekannt')} uebernommen und geprueft."
    )

    ziel = DATENVERZEICHNIS / f"{jahr}.yaml"
    if ziel.exists():
        sicherung = DATENVERZEICHNIS / f"{jahr}.yaml.bak"
        shutil.copy2(ziel, sicherung)
    ziel.write_text(
        yaml.safe_dump(daten, allow_unicode=True, sort_keys=False, width=100), encoding="utf-8"
    )
    entwurf.unlink()
    return ziel
