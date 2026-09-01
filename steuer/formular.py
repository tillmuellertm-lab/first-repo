"""Aufstellung nach Formularabschnitten: was wohin gehoert.

Die Kennzahlen sagen "Werbungskosten 12.920,58 EUR". Wer das in ELSTER oder in
eine Steuersoftware eintragen soll, weiss damit noch nicht, in welches Feld -
und sucht sich durch die Anlagen. Dieses Modul schlaegt die Bruecke: Es ordnet
jede Kategorie ihrem Formularabschnitt zu und legt die Belege darunter.

Zwei Dinge tut es bewusst nicht. Es erfindet keine Zeilennummer; wo im Regelwerk
keine hinterlegt ist, steht die Abschnittsbezeichnung, die sich in ELSTER
suchen laesst. Und es verteilt keine Betraege auf mehrere Abschnitte einer
Kategorie - welcher Teil der sonstigen Werbungskosten auf die doppelte
Haushaltsfuehrung entfaellt, steht in keinem Beleg. Beides bleibt sichtbar
offen, statt plausibel geraten zu werden.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import taxonomy
from .formatierung import euro
from .models import Dokument, EIGNUNG_UNGEEIGNET, ist_erstattung, zaehlt_als_aufwand
from .rules import Regelwerk


@dataclass
class Abschnitt:
    """Ein Abschnitt eines Formulars, wie er im Vordruck heisst."""

    bezeichnung: str
    zeile: str = ""
    hinweis: str = ""
    standard: bool = False

    @property
    def fundstelle(self) -> str:
        return f"Zeile {self.zeile} - {self.bezeichnung}" if self.zeile else self.bezeichnung


@dataclass
class Posten:
    """Eine Kategorie mit ihrem Platz im Formular."""

    kategorie_id: str
    label: str
    anlage: str
    betrag: float
    abschnitte: list[Abschnitt] = field(default_factory=list)
    belege: list[Dokument] = field(default_factory=list)
    erstattungen: list[Dokument] = field(default_factory=list)
    nicht_angesetzt: list[Dokument] = field(default_factory=list)
    aufwand: float = 0.0
    erstattet: float = 0.0

    @property
    def standardabschnitt(self) -> Abschnitt | None:
        """Der Abschnitt, in den die Summe gehoert - falls es nur einen gibt."""
        vorgemerkt = [a for a in self.abschnitte if a.standard]
        if len(vorgemerkt) == 1:
            return vorgemerkt[0]
        if len(self.abschnitte) == 1:
            return self.abschnitte[0]
        return None

    @property
    def aufzuteilen(self) -> bool:
        """Ob die Summe auf mehrere Abschnitte verteilt werden muss."""
        return len(self.abschnitte) > 1


def _abschnitte(eintrag: dict[str, Any]) -> list[Abschnitt]:
    ergebnis = []
    for roh in eintrag.get("abschnitte") or []:
        if not isinstance(roh, dict):
            continue
        ergebnis.append(
            Abschnitt(
                bezeichnung=str(roh.get("bezeichnung", "")).strip(),
                zeile=str(roh.get("zeile") or "").strip(),
                hinweis=" ".join(str(roh.get("hinweis") or "").split()),
                standard=bool(roh.get("standard")),
            )
        )
    return [a for a in ergebnis if a.bezeichnung]


def zuordnung(regelwerk: Regelwerk) -> dict[str, dict[str, Any]]:
    """Die im Regelwerk hinterlegte Zuordnung, nach Kategorie."""
    eintraege = regelwerk.daten.get("formularzeilen") or []
    return {
        str(e.get("id")): e
        for e in eintraege
        if isinstance(e, dict) and e.get("id")
    }


def aufstellung(dokumente: list[Dokument], regelwerk: Regelwerk) -> list[Posten]:
    """Baut die Aufstellung in der Reihenfolge der Steuererklaerung."""
    nach_kategorie: dict[str, list[Dokument]] = {}
    for dokument in dokumente:
        nach_kategorie.setdefault(dokument.wirksame_kategorie, []).append(dokument)

    zuordnungen = zuordnung(regelwerk)
    posten: list[Posten] = []
    for kategorie_id, liste in nach_kategorie.items():
        if kategorie_id in taxonomy.AUSGESCHLOSSEN:
            continue
        eintrag = zuordnungen.get(kategorie_id, {})
        kategorie = taxonomy.kategorie(kategorie_id)

        aufwand = 0.0
        erstattet = 0.0
        belege: list[Dokument] = []
        erstattungen: list[Dokument] = []
        nicht_angesetzt: list[Dokument] = []
        for dokument in liste:
            analyse = dokument.analyse
            if not analyse or analyse.eignung == EIGNUNG_UNGEEIGNET:
                continue
            if dokument.nicht_ansetzen:
                nicht_angesetzt.append(dokument)
                continue
            wert = dokument.wirksamer_betrag
            if ist_erstattung(analyse):
                erstattungen.append(dokument)
                erstattet += abs(float(wert or 0.0))
            elif zaehlt_als_aufwand(analyse):
                belege.append(dokument)
                aufwand += float(wert or 0.0)

        betrag = aufwand - erstattet
        if not belege and not erstattungen and not nicht_angesetzt:
            continue
        posten.append(
            Posten(
                kategorie_id=kategorie_id,
                label=kategorie.label,
                anlage=str(eintrag.get("anlage") or kategorie.anlage),
                betrag=round(betrag, 2),
                aufwand=round(aufwand, 2),
                erstattet=round(erstattet, 2),
                nicht_angesetzt=nicht_angesetzt,
                abschnitte=_abschnitte(eintrag),
                belege=sorted(belege, key=lambda d: (d.analyse.datum or "9999", d.dateiname)),
                erstattungen=erstattungen,
            )
        )

    posten.sort(key=lambda p: taxonomy.sortierschluessel(p.kategorie_id))
    return posten


def _belegzeile(dokument: Dokument) -> str:
    analyse = dokument.analyse
    bezeichnung = " - ".join(t for t in (analyse.dokumenttyp, analyse.aussteller) if t)
    wert = dokument.wirksamer_betrag
    teile = [
        analyse.datum or "ohne Datum",
        bezeichnung or dokument.dateiname,
        euro(wert) if wert is not None else "kein Euro-Betrag",
    ]
    if dokument.fremdwaehrung:
        roh = analyse.betrag_abzugsfaehig or analyse.betrag_gesamt
        teile.append(f"Beleg lautet auf {roh} {dokument.fremdwaehrung}")
    if dokument.manueller_betrag is not None:
        teile.append("Betrag manuell gesetzt")
    return " | ".join(teile)


def als_markdown(
    posten: list[Posten], regelwerk: Regelwerk, jahr: int, geprueft: bool | None = None
) -> str:
    """Die Aufstellung als Text zum Abtippen oder Weitergeben."""
    if geprueft is None:
        geprueft = bool(regelwerk.daten.get("formularzeilen_geprueft"))

    zeilen = [
        f"# Aufstellung nach Formularabschnitten {jahr}",
        "",
        "Diese Aufstellung sagt, in welchen Abschnitt der Steuererklaerung jeder "
        "Betrag gehoert. Sie ersetzt das Suchen im Formular, nicht die Pruefung "
        "durch den Steuerberater.",
        "",
    ]
    if not geprueft:
        zeilen += [
            "> **Zeilennummern nicht amtlich geprueft.** Hinterlegt sind die "
            "Abschnittsbezeichnungen der Vordrucke; sie lassen sich in ELSTER "
            "suchen. Wo eine Zeilennummer fehlt, ist sie bewusst weggelassen - "
            "eine falsche Nummer waere schlimmer als keine.",
            "",
        ]

    for eintrag in posten:
        zeilen.append(f"## {eintrag.label}")
        zeilen.append("")
        if eintrag.erstattet:
            zeilen.append(
                f"**{eintrag.anlage}** &middot; Aufwand {euro(eintrag.aufwand)} "
                f"&minus; Erstattungen {euro(eintrag.erstattet)} "
                f"= **{euro(eintrag.betrag)}**"
            )
        else:
            zeilen.append(f"**{eintrag.anlage}** &middot; Summe **{euro(eintrag.betrag)}**")
        zeilen.append("")

        if not eintrag.abschnitte:
            zeilen.append(
                "Fuer diese Kategorie ist noch kein Formularabschnitt hinterlegt. "
                "Der Steuerberater ordnet sie zu."
            )
        elif eintrag.aufzuteilen:
            zeilen.append(
                "Diese Summe verteilt sich auf mehrere Abschnitte. Welcher Beleg "
                "wohin gehoert, steht in keinem Beleg - deshalb hier ungeteilt:"
            )
            zeilen.append("")
            for abschnitt in eintrag.abschnitte:
                marke = " (Sammelposten)" if abschnitt.standard else ""
                zeilen.append(f"- **{abschnitt.fundstelle}**{marke}")
                if abschnitt.hinweis:
                    zeilen.append(f"  {abschnitt.hinweis}")
        else:
            abschnitt = eintrag.standardabschnitt or eintrag.abschnitte[0]
            zeilen.append(f"Eintragen unter: **{abschnitt.fundstelle}**")
            if abschnitt.hinweis:
                zeilen.append("")
                zeilen.append(abschnitt.hinweis)

        if eintrag.erstattungen:
            zeilen.append("")
            zeilen.append("Bereits gegengerechnete Erstattungen:")
            for dokument in eintrag.erstattungen:
                zeilen.append(f"- {_belegzeile(dokument)}")

        if eintrag.nicht_angesetzt:
            zeilen.append("")
            zeilen.append("Bewusst nicht angesetzt:")
            for dokument in eintrag.nicht_angesetzt:
                grund = dokument.nicht_ansetzen_grund or "ohne Begruendung"
                zeilen.append(f"- {_belegzeile(dokument)} — {grund}")

        zeilen.append("")
        zeilen.append(f"<details><summary>{len(eintrag.belege)} Belege</summary>")
        zeilen.append("")
        for dokument in eintrag.belege:
            zeilen.append(f"- {_belegzeile(dokument)}")
            if dokument.notiz:
                zeilen.append(f"  - Anmerkung: {' '.join(dokument.notiz.split())}")
        zeilen.append("")
        zeilen.append("</details>")
        zeilen.append("")

    if not posten:
        zeilen.append("Es liegen noch keine verwertbaren Belege mit Betrag vor.")
    return "\n".join(zeilen).rstrip() + "\n"


__all__ = ["Abschnitt", "Posten", "als_markdown", "aufstellung", "zuordnung"]
