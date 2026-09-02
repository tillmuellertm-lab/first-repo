"""Laden und Zusammenfuehren der Steuerrechts-Regeldateien.

Jedes Veranlagungsjahr liegt als eigene YAML-Datei in ``rules/data``. Ueber den
Schluessel ``erbt_von`` erbt eine Jahresdatei von einer anderen Datei, sodass
nur noch die tatsaechlich geaenderten Werte gepflegt werden muessen. Listen mit
``id`` werden eintragsweise zusammengefuehrt, alles andere ueberschreibt.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DATENVERZEICHNIS = Path(__file__).parent / "data"
BASISNAME = "basis"
LISTEN_MIT_ID = ("checkliste", "chancen")


class RegelFehler(RuntimeError):
    pass


@dataclass
class Regelwerk:
    """Zusammengefuehrter Rechtsstand fuer ein Veranlagungsjahr."""

    jahr: int
    daten: dict[str, Any]
    quelle_jahr: int | None = None  # gesetzt, wenn ersatzweise ein anderes Jahr geladen wurde

    @property
    def stand(self) -> str:
        return str(self.daten.get("stand", "unbekannt"))

    @property
    def status(self) -> str:
        return str(self.daten.get("status", "unbekannt"))

    @property
    def ist_ersatz(self) -> bool:
        return self.quelle_jahr is not None and self.quelle_jahr != self.jahr

    @property
    def werte(self) -> dict[str, Any]:
        return self.daten.get("werte", {})

    @property
    def checkliste(self) -> list[dict[str, Any]]:
        return self.daten.get("checkliste", [])

    @property
    def chancen(self) -> list[dict[str, Any]]:
        return self.daten.get("chancen", [])

    @property
    def fristen(self) -> dict[str, Any]:
        return self.daten.get("fristen", {})

    def wert(self, schluessel: str, standard: Any = None) -> Any:
        """Liefert den reinen Zahlenwert eines Eintrags aus ``werte``."""
        eintrag = self.werte.get(schluessel)
        if not isinstance(eintrag, dict):
            return standard
        return eintrag.get("wert", standard)

    def eintrag(self, schluessel: str) -> dict[str, Any]:
        eintrag = self.werte.get(schluessel)
        return eintrag if isinstance(eintrag, dict) else {}


def verfuegbare_jahre() -> list[int]:
    """Alle Jahre, fuer die eine gepflegte Regeldatei vorliegt."""
    jahre = []
    for pfad in DATENVERZEICHNIS.glob("*.yaml"):
        if pfad.stem == BASISNAME or "." in pfad.stem:
            continue
        try:
            jahre.append(int(pfad.stem))
        except ValueError:
            continue
    return sorted(jahre)


def _datei_laden(name: str) -> dict[str, Any]:
    pfad = DATENVERZEICHNIS / f"{name}.yaml"
    if not pfad.exists():
        raise RegelFehler(f"Regeldatei fehlt: {pfad}")
    with pfad.open(encoding="utf-8") as datei:
        daten = yaml.safe_load(datei) or {}
    if not isinstance(daten, dict):
        raise RegelFehler(f"Regeldatei {pfad} enthaelt kein Objekt auf oberster Ebene.")
    return daten


def _listen_zusammenfuehren(basis: list[Any], ergaenzung: list[Any]) -> list[Any]:
    """Fuehrt Listen mit ``id``-Schluessel eintragsweise zusammen."""
    if not all(isinstance(e, dict) and "id" in e for e in basis + ergaenzung):
        return copy.deepcopy(ergaenzung)
    ergebnis = [copy.deepcopy(e) for e in basis]
    position = {e["id"]: i for i, e in enumerate(ergebnis)}
    for eintrag in ergaenzung:
        if eintrag["id"] in position:
            ergebnis[position[eintrag["id"]]] = _zusammenfuehren(
                ergebnis[position[eintrag["id"]]], eintrag
            )
        else:
            ergebnis.append(copy.deepcopy(eintrag))
    return ergebnis


def _zusammenfuehren(basis: dict[str, Any], ergaenzung: dict[str, Any]) -> dict[str, Any]:
    ergebnis = copy.deepcopy(basis)
    for schluessel, wert in ergaenzung.items():
        vorhanden = ergebnis.get(schluessel)
        if isinstance(vorhanden, dict) and isinstance(wert, dict):
            ergebnis[schluessel] = _zusammenfuehren(vorhanden, wert)
        elif (
            schluessel in LISTEN_MIT_ID
            and isinstance(vorhanden, list)
            and isinstance(wert, list)
        ):
            ergebnis[schluessel] = _listen_zusammenfuehren(vorhanden, wert)
        else:
            ergebnis[schluessel] = copy.deepcopy(wert)
    return ergebnis


def _aufloesen(name: str, kette: tuple[str, ...] = ()) -> dict[str, Any]:
    if name in kette:
        raise RegelFehler(f"Zirkulaere Vererbung in den Regeldateien: {' -> '.join(kette + (name,))}")
    daten = _datei_laden(name)
    eltern = daten.get("erbt_von")
    if not eltern:
        return daten
    basis = _aufloesen(str(eltern), kette + (name,))
    zusammengefuehrt = _zusammenfuehren(basis, daten)
    zusammengefuehrt.pop("erbt_von", None)
    return zusammengefuehrt


def laden(jahr: int, strikt: bool = False) -> Regelwerk:
    """Laedt das Regelwerk fuer ein Jahr.

    Fehlt die Datei und ``strikt`` ist nicht gesetzt, wird ersatzweise das
    juengste vorhandene Jahr geladen und ueber ``ist_ersatz`` gekennzeichnet.
    """
    jahre = verfuegbare_jahre()
    if jahr in jahre:
        return Regelwerk(jahr=jahr, daten=_aufloesen(str(jahr)), quelle_jahr=jahr)
    if strikt or not jahre:
        raise RegelFehler(
            f"Fuer {jahr} liegt keine Regeldatei vor. Vorhanden: {', '.join(map(str, jahre)) or 'keine'}. "
            f"Mit 'steuer recht-update --jahr {jahr}' laesst sich ein Entwurf erzeugen."
        )
    ersatz = max(jahre)
    return Regelwerk(jahr=jahr, daten=_aufloesen(str(ersatz)), quelle_jahr=ersatz)


def rohdatei_lesen(jahr: int) -> str:
    pfad = DATENVERZEICHNIS / f"{jahr}.yaml"
    if not pfad.exists():
        raise RegelFehler(f"Regeldatei fehlt: {pfad}")
    return pfad.read_text(encoding="utf-8")
