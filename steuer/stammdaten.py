"""Jahresuebergreifendes Gedaechtnis: bestaetigte Fortschreibungswerte.

Manche Zahlen einer Steuererklaerung stehen in keinem einzelnen Beleg. Die
Gebaeude-AfA etwa wird aus den Vorjahren fortgeschrieben; sie steht nicht im
Steuerbescheid, sondern nur in der eingereichten Anlage V. Wer sie nicht
festhaelt, sucht sie jedes Jahr neu - oder laesst den groessten Posten der
Anlage V stillschweigend ausfallen.

Anders als das Regelwerk in ``steuer/rules`` sind diese Werte nicht gesetzlich
vorgegeben, sondern personen- und objektbezogen: dieses Haus, diese Familie.
Deshalb liegen sie in der Arbeitsmappe und nicht im Programmverzeichnis.

Nichts wird automatisch uebernommen. Jeder Wert traegt seine Fundstelle und das
Datum, an dem der Nutzer ihn bestaetigt hat.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DATEINAME = "stammdaten.yaml"


@dataclass(frozen=True)
class Vorlage:
    """Ein ueblicher Fortschreibungswert samt Erlaeuterung."""

    id: str
    label: str
    einheit: str = ""
    hinweis: str = ""
    fortschreiben: bool = True


# Was erfahrungsgemaess ueber Jahre hinweg gebraucht wird. Die Liste ist ein
# Angebot, keine Schranke: eigene Kennungen sind erlaubt.
VORLAGEN: tuple[Vorlage, ...] = (
    Vorlage(
        id="gebaeude_afa_jahresbetrag",
        label="Gebaeude-AfA, Jahresbetrag",
        einheit="EUR",
        hinweis=(
            "Steht in der Anlage V des Vorjahres, Zeile 33 - nicht im Steuerbescheid. "
            "Meist der groesste Posten der Anlage V."
        ),
    ),
    Vorlage(
        id="gebaeude_afa_satz",
        label="Gebaeude-AfA, Satz",
        einheit="prozent_pro_jahr",
        hinweis="Regelfall 2 % nach § 7 Abs. 4 Satz 1 Nr. 2a EStG.",
    ),
    Vorlage(
        id="gebaeude_afa_bemessungsgrundlage",
        label="Bemessungsgrundlage Gebaeude ohne Grund und Boden",
        einheit="EUR",
        hinweis="Aus dem Kaufvertrag, aufgeteilt auf Gebaeude und Grund und Boden.",
    ),
    Vorlage(
        id="objekt_bezeichnung",
        label="Vermietetes Objekt",
        hinweis="Anschrift, damit klar ist, worauf sich die AfA bezieht.",
    ),
    Vorlage(id="objekt_angeschafft_am", label="Objekt angeschafft am"),
    Vorlage(id="objekt_fertiggestellt_am", label="Objekt fertiggestellt am"),
    Vorlage(id="einheitswert_aktenzeichen", label="Einheitswert-Aktenzeichen"),
    Vorlage(
        id="afa_bewegliche_wirtschaftsgueter",
        label="AfA beweglicher Wirtschaftsgueter",
        einheit="EUR",
        hinweis="Laeuft aus, wenn die Nutzungsdauer endet - jedes Jahr pruefen.",
        fortschreiben=False,
    ),
    Vorlage(
        id="verlustvortrag_kapital",
        label="Verlustvortrag aus Kapitalvermoegen",
        einheit="EUR",
        hinweis="Aus dem Verlustfeststellungsbescheid. Verfaellt, wenn er nicht uebernommen wird.",
        fortschreiben=False,
    ),
    Vorlage(
        id="verlustvortrag_gewerbe",
        label="Verlustvortrag aus Gewerbebetrieb",
        einheit="EUR",
        fortschreiben=False,
    ),
    Vorlage(id="steuernummer", label="Steuernummer"),
    Vorlage(id="finanzamt", label="Zustaendiges Finanzamt"),
)

NACH_ID = {v.id: v for v in VORLAGEN}


def _heute() -> str:
    return _dt.date.today().isoformat()


@dataclass
class Stammwert:
    """Ein bestaetigter Wert samt Herkunft."""

    id: str
    wert: Any = None
    label: str = ""
    einheit: str = ""
    quelle: str = ""  # Fundstelle, z. B. "ESt-Erklaerung 2023, Anlage V, Zeile 33"
    rechtsgrundlage: str = ""
    hinweis: str = ""
    gilt_ab_jahr: int | None = None
    bestaetigt_am: str = field(default_factory=_heute)

    @property
    def ist_gesetzt(self) -> bool:
        return self.wert not in (None, "")

    def als_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in (None, "")}


@dataclass
class Stammdaten:
    """Die Sammlung aller bestaetigten Werte einer Mappe."""

    werte: dict[str, Stammwert] = field(default_factory=dict)
    pfad: Path | None = None

    # -- Zugriff -------------------------------------------------------------

    def __contains__(self, kennung: str) -> bool:
        eintrag = self.werte.get(kennung)
        return bool(eintrag and eintrag.ist_gesetzt)

    def wert(self, kennung: str, ersatz: Any = None) -> Any:
        eintrag = self.werte.get(kennung)
        return eintrag.wert if eintrag and eintrag.ist_gesetzt else ersatz

    def eintrag(self, kennung: str) -> Stammwert | None:
        return self.werte.get(kennung)

    def setzen(
        self,
        kennung: str,
        wert: Any,
        quelle: str = "",
        gilt_ab_jahr: int | None = None,
        hinweis: str = "",
    ) -> Stammwert:
        vorlage = NACH_ID.get(kennung)
        eintrag = Stammwert(
            id=kennung,
            wert=wert,
            label=vorlage.label if vorlage else kennung,
            einheit=vorlage.einheit if vorlage else "",
            hinweis=hinweis or (vorlage.hinweis if vorlage else ""),
            quelle=quelle,
            gilt_ab_jahr=gilt_ab_jahr,
        )
        self.werte[kennung] = eintrag
        return eintrag

    def entfernen(self, kennung: str) -> bool:
        return self.werte.pop(kennung, None) is not None

    def gesetzte(self) -> list[Stammwert]:
        """Alle gesetzten Werte, in der Reihenfolge der Vorlagen."""
        reihenfolge = {v.id: i for i, v in enumerate(VORLAGEN)}
        vorhanden = [e for e in self.werte.values() if e.ist_gesetzt]
        return sorted(vorhanden, key=lambda e: (reihenfolge.get(e.id, 999), e.id))

    def fehlende_vorlagen(self) -> list[Vorlage]:
        return [v for v in VORLAGEN if v.id not in self]

    # -- Fuer Prompt und Pruefsumme ------------------------------------------

    def als_text(self) -> str:
        """Kurzfassung fuer den Analyseauftrag."""
        zeilen = []
        for eintrag in self.gesetzte():
            teil = f"- {eintrag.label or eintrag.id}: {eintrag.wert}"
            if eintrag.einheit and eintrag.einheit != "text":
                teil += f" {eintrag.einheit}"
            if eintrag.quelle:
                teil += f" (Quelle: {eintrag.quelle})"
            zeilen.append(teil)
        return "\n".join(zeilen)

    def pruefsumme(self) -> str:
        roh = "|".join(f"{e.id}={e.wert}" for e in self.gesetzte()).encode("utf-8")
        return hashlib.sha256(roh).hexdigest()[:12]

    # -- Fortschreiben --------------------------------------------------------

    def fuer_neues_jahr(self, jahr: int) -> tuple["Stammdaten", list[str]]:
        """Uebertraegt die Werte in ein neues Jahr und meldet, was zu pruefen ist.

        Fortgeschrieben wird nur, was seiner Natur nach gleich bleibt. Werte mit
        endlicher Laufzeit - Abschreibungen beweglicher Gueter, Verlustvortraege -
        werden mituebernommen, aber ausdruecklich zur Pruefung gestellt, statt
        stillschweigend weiterzulaufen.
        """
        neu = Stammdaten(pfad=self.pfad)
        zu_pruefen: list[str] = []
        for eintrag in self.gesetzte():
            uebernommen = Stammwert(**asdict(eintrag))
            uebernommen.gilt_ab_jahr = jahr
            neu.werte[eintrag.id] = uebernommen
            vorlage = NACH_ID.get(eintrag.id)
            if vorlage and not vorlage.fortschreiben:
                zu_pruefen.append(eintrag.label or eintrag.id)
        return neu, zu_pruefen


# ------------------------------------------------------------------ Ablage --

def laden(pfad: Path) -> Stammdaten:
    """Liest die Stammdaten. Eine fehlende Datei ist kein Fehler."""
    pfad = Path(pfad)
    daten = Stammdaten(pfad=pfad)
    if not pfad.exists():
        return daten
    import yaml  # noqa: PLC0415 - nur beim tatsaechlichen Laden noetig

    roh = yaml.safe_load(pfad.read_text(encoding="utf-8")) or {}
    for kennung, eintrag in (roh.get("werte") or {}).items():
        if not isinstance(eintrag, dict):
            eintrag = {"wert": eintrag}
        bekannt = {f for f in Stammwert.__dataclass_fields__}
        gefiltert = {k: v for k, v in eintrag.items() if k in bekannt}
        gefiltert["id"] = kennung
        daten.werte[kennung] = Stammwert(**gefiltert)
    return daten


def speichern(daten: Stammdaten, pfad: Path | None = None) -> Path:
    import yaml  # noqa: PLC0415

    ziel = Path(pfad or daten.pfad or DATEINAME)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    inhalt = {
        "hinweis": (
            "Bestaetigte Fortschreibungswerte. Von Hand aenderbar; jeder Wert "
            "sollte seine Fundstelle nennen."
        ),
        "werte": {e.id: e.als_dict() for e in daten.gesetzte()},
    }
    text = yaml.safe_dump(inhalt, allow_unicode=True, sort_keys=False)
    temp = ziel.with_suffix(ziel.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(ziel)
    daten.pfad = ziel
    return ziel


__all__ = [
    "DATEINAME",
    "NACH_ID",
    "Stammdaten",
    "Stammwert",
    "VORLAGEN",
    "Vorlage",
    "laden",
    "speichern",
]
