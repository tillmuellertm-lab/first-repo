"""Uebersicht fuer den Steuerberater: Markdown, HTML und CSV.

Die HTML-Fassung ist bewusst eigenstaendig und ohne externe Ressourcen gebaut,
damit sie sich per Browser ohne Weiteres als PDF drucken laesst.
"""

from __future__ import annotations

import csv
import datetime as _dt
import html
import io
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import taxonomy
from .formatierung import euro
from .gaps import Auswertung
from .models import (
    EIGNUNG_BEDINGT,
    EIGNUNG_GEEIGNET,
    EIGNUNG_LABEL,
    EIGNUNG_UNGEEIGNET,
    Befund,
    Dokument,
    Profil,
)
from .rules import Regelwerk

HAFTUNGSHINWEIS = (
    "Diese Uebersicht ist eine maschinelle Vorbereitung von Unterlagen und keine "
    "Steuerberatung im Sinne des Steuerberatungsgesetzes. Alle Einordnungen, Betraege "
    "und Hinweise sind Vorschlaege und muessen vor der Einreichung fachlich geprueft werden."
)


def _euro(betrag: float | None) -> str:
    """Wie formatierung.euro, aber leer statt Gedankenstrich: in Tabellenzellen
    liest sich eine leere Zelle besser als ein Platzhalter."""
    return "" if betrag is None else euro(betrag)


def _datum(wert: str | None) -> str:
    if not wert:
        return ""
    try:
        return _dt.date.fromisoformat(wert).strftime("%d.%m.%Y")
    except ValueError:
        return wert


def _nach_kategorie(dokumente: list[Dokument]) -> dict[str, list[Dokument]]:
    gruppen: dict[str, list[Dokument]] = defaultdict(list)
    for dokument in dokumente:
        gruppen[dokument.wirksame_kategorie].append(dokument)
    for liste in gruppen.values():
        liste.sort(key=lambda d: (d.analyse.datum if d.analyse and d.analyse.datum else "9999", d.dateiname))
    return gruppen


# ---------------------------------------------------------------- Markdown --

def markdown_bericht(
    dokumente: list[Dokument],
    auswertung: Auswertung,
    regelwerk: Regelwerk,
    profil: Profil,
    modellauswertung: dict[str, Any] | None = None,
) -> str:
    zahlen = auswertung.kennzahlen
    zeilen: list[str] = []
    a = zeilen.append

    a(f"# Steuerunterlagen {regelwerk.jahr}")
    a("")
    if profil.name:
        a(f"**Mandant:** {profil.name}  ")
    a(f"**Veranlagungszeitraum:** {regelwerk.jahr}  ")
    a(f"**Erstellt am:** {_dt.date.today().strftime('%d.%m.%Y')}  ")
    a(f"**Rechtsstand der hinterlegten Werte:** {regelwerk.stand}  ")
    if regelwerk.ist_ersatz:
        a(f"**Achtung:** ersatzweise Werte aus {regelwerk.quelle_jahr} verwendet.  ")
    a("")

    a("## Auf einen Blick")
    a("")
    a("| Kennzahl | Wert |")
    a("| --- | ---: |")
    a(f"| Dokumente insgesamt | {zahlen['anzahl_dokumente']} |")
    a(f"| davon einreichbar | {zahlen['anzahl_geeignet']} |")
    a(f"| davon mit offenen Punkten | {zahlen['anzahl_bedingt']} |")
    a(f"| davon nicht verwertbar | {zahlen['anzahl_ungeeignet']} |")
    a(f"| Werbungskosten erfasst | {_euro(zahlen['werbungskosten_gesamt'])} |")
    a(f"| Arbeitnehmer-Pauschbetrag | {_euro(zahlen['arbeitnehmer_pauschbetrag'])} |")
    a(f"| Haushaltsnahe Aufwendungen | {_euro(zahlen['haushaltsnahe_aufwendungen_gesamt'])} |")
    a(f"| davon Steuerermaessigung (20 %) | {_euro(zahlen['haushaltsnahe_ermaessigung_geschaetzt'])} |")
    a(f"| Sonderausgaben erfasst | {_euro(zahlen['sonderausgaben_gesamt'])} |")
    a(f"| Aussergewoehnliche Belastungen | {_euro(zahlen['aussergewoehnliche_belastungen_gesamt'])} |")
    a("")

    if modellauswertung and modellauswertung.get("gesamteinschaetzung"):
        a("## Einschaetzung")
        a("")
        a(str(modellauswertung["gesamteinschaetzung"]))
        a("")

    a("## Unterlagen nach Anlagen")
    a("")
    gruppen = _nach_kategorie(dokumente)
    for kategorie in taxonomy.KATEGORIEN:
        liste = gruppen.get(kategorie.id)
        if not liste:
            continue
        summe = sum(
            (d.analyse.betrag_abzugsfaehig or d.analyse.betrag_gesamt or 0.0)
            for d in liste
            if d.analyse and d.analyse.eignung != EIGNUNG_UNGEEIGNET
        )
        a(f"### {kategorie.ordner} — {kategorie.label}")
        a("")
        a(f"Anlage: {kategorie.anlage} · {len(liste)} Dokumente · Summe {_euro(round(summe, 2))}")
        a("")
        a("| Datei | Datum | Art | Aussteller | Betrag | Status |")
        a("| --- | --- | --- | --- | ---: | --- |")
        for dokument in liste:
            analyse = dokument.analyse
            name = dokument.zieldateiname or dokument.dateiname
            a(
                f"| {name} | {_datum(analyse.datum) if analyse else ''} "
                f"| {analyse.dokumenttyp if analyse else ''} "
                f"| {analyse.aussteller if analyse else ''} "
                f"| {_euro(analyse.betrag_abzugsfaehig or analyse.betrag_gesamt) if analyse else ''} "
                f"| {EIGNUNG_LABEL.get(analyse.eignung, 'offen') if analyse else 'nicht analysiert'} |"
            )
        a("")
        offene = [d for d in liste if d.analyse and d.analyse.fehlende_nachweise]
        if offene:
            a("**Offene Punkte:**")
            a("")
            for dokument in offene:
                name = dokument.zieldateiname or dokument.dateiname
                for fehlend in dokument.analyse.fehlende_nachweise:  # type: ignore[union-attr]
                    a(f"- {name}: {fehlend}")
                # Die Antwort des Mandanten steht direkt unter der Frage. Sonst
                # sucht der Steuerberater eine Auskunft, die laengst vorliegt.
                if dokument.notiz:
                    a(f"  - Anmerkung des Mandanten: {dokument.notiz}")
            a("")

        beantwortet = [d for d in liste if d.notiz and not (d.analyse and d.analyse.fehlende_nachweise)]
        if beantwortet:
            a("**Anmerkungen des Mandanten:**")
            a("")
            for dokument in beantwortet:
                a(f"- {dokument.zieldateiname or dokument.dateiname}: {dokument.notiz}")
            a("")

    def _befunde(titel: str, befunde: list[Befund]) -> None:
        if not befunde:
            return
        a(f"## {titel}")
        a("")
        for befund in befunde:
            kopf = f"### {befund.titel}"
            if befund.potenzial_eur:
                kopf += f" — bis zu {_euro(befund.potenzial_eur)}"
            a(kopf)
            a("")
            merkmale = [f"Prioritaet: {befund.prioritaet}"]
            if befund.anlage:
                merkmale.append(f"Anlage: {befund.anlage}")
            a("*" + " · ".join(merkmale) + "*")
            a("")
            a(befund.beschreibung)
            a("")

    _befunde("Was noch fehlt", auswertung.luecken)
    _befunde("Wo Geld liegen bleibt", auswertung.chancen)
    _befunde("Warnungen", auswertung.warnungen)

    if modellauswertung:
        for schluessel, titel in (
            ("luecken", "Weitere Luecken aus der Gesamtauswertung"),
            ("chancen", "Weitere Chancen aus der Gesamtauswertung"),
        ):
            eintraege = modellauswertung.get(schluessel) or []
            if not eintraege:
                continue
            a(f"## {titel}")
            a("")
            for eintrag in eintraege:
                a(f"### {eintrag.get('titel', '')}")
                a("")
                a(str(eintrag.get("beschreibung", "")))
                a("")
                if eintrag.get("rechtsgrundlage"):
                    a(f"Rechtsgrundlage: {eintrag['rechtsgrundlage']}")
                    a("")
                if eintrag.get("potenzial_eur"):
                    a(f"Groessenordnung: {_euro(float(eintrag['potenzial_eur']))}")
                    if eintrag.get("schaetzgrundlage"):
                        a(f"Grundlage der Schaetzung: {eintrag['schaetzgrundlage']}")
                    a("")
                if eintrag.get("naechster_schritt"):
                    a(f"**Naechster Schritt:** {eintrag['naechster_schritt']}")
                    a("")

        fragen = modellauswertung.get("fragen_an_den_mandanten") or []
        if fragen:
            a("## Fragen an den Mandanten")
            a("")
            for frage in fragen:
                a(f"- {frage}")
            a("")

        hinweise = modellauswertung.get("hinweise_fuer_den_steuerberater") or []
        if hinweise:
            a("## Hinweise fuer den Steuerberater")
            a("")
            for hinweis in hinweise:
                a(f"- {hinweis}")
            a("")

    a("---")
    a("")
    a(HAFTUNGSHINWEIS)
    a("")
    return "\n".join(zeilen)


# -------------------------------------------------------------------- HTML --

_STIL = """
:root {
  --grund: #ffffff; --text: #1a1c1f; --gedaempft: #5c6470; --rahmen: #dfe3e8;
  --flaeche: #f6f7f9; --akzent: #1f4d7a; --gut: #1a7f4b; --achtung: #a86a00; --schlecht: #b3261e;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 2.5rem 1.5rem 4rem; background: var(--grund); color: var(--text);
  font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}
main { max-width: 60rem; margin: 0 auto; }
h1 { font-size: 1.9rem; margin: 0 0 .25rem; letter-spacing: -0.01em; }
h2 { font-size: 1.3rem; margin: 2.5rem 0 .75rem; padding-bottom: .35rem; border-bottom: 2px solid var(--rahmen); }
h3 { font-size: 1.05rem; margin: 1.5rem 0 .35rem; }
p { margin: .4rem 0; }
.kopf { color: var(--gedaempft); margin-bottom: 1.5rem; }
.kacheln { display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); gap: .75rem; margin: 1rem 0 0; }
.kachel { background: var(--flaeche); border: 1px solid var(--rahmen); border-radius: .5rem; padding: .8rem .9rem; }
.kachel .wert { font-size: 1.5rem; font-weight: 600; letter-spacing: -0.02em; }
.kachel .titel { font-size: .8rem; color: var(--gedaempft); text-transform: uppercase; letter-spacing: .04em; }
table { width: 100%; border-collapse: collapse; margin: .75rem 0; font-size: .92rem; }
th, td { text-align: left; padding: .45rem .6rem; border-bottom: 1px solid var(--rahmen); vertical-align: top; }
th { background: var(--flaeche); font-weight: 600; }
td.betrag, th.betrag { text-align: right; white-space: nowrap; }
.marke { display: inline-block; padding: .1rem .5rem; border-radius: 1rem; font-size: .78rem; font-weight: 600; white-space: nowrap; }
.marke.geeignet { background: #e4f4ea; color: var(--gut); }
.marke.bedingt_geeignet { background: #fdf1dc; color: var(--achtung); }
.marke.ungeeignet { background: #fbe6e4; color: var(--schlecht); }
.marke.unklar { background: var(--flaeche); color: var(--gedaempft); }
.abschnitt { border: 1px solid var(--rahmen); border-left: 4px solid var(--akzent); border-radius: .4rem; padding: .8rem 1rem; margin: .75rem 0; background: var(--flaeche); }
.abschnitt.hoch { border-left-color: var(--schlecht); }
.abschnitt.mittel { border-left-color: var(--achtung); }
.abschnitt.niedrig { border-left-color: var(--gedaempft); }
.abschnitt h3 { margin-top: 0; }
.meta { font-size: .82rem; color: var(--gedaempft); margin-bottom: .35rem; }
.gruppe { margin-top: 2rem; }
.gruppe .zeile { color: var(--gedaempft); font-size: .9rem; }
ul { margin: .4rem 0 .4rem 1.2rem; padding: 0; }
.fuss { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--rahmen); color: var(--gedaempft); font-size: .85rem; }
@media print {
  body { padding: 0; font-size: 11pt; }
  h2 { break-after: avoid; }
  .abschnitt, tr { break-inside: avoid; }
}
@media (prefers-color-scheme: dark) {
  :root { --grund: #14161a; --text: #e8eaed; --gedaempft: #9aa4b2; --rahmen: #2c313a;
          --flaeche: #1c1f25; --akzent: #6fa8dc; --gut: #6cc48f; --achtung: #e0a94a; --schlecht: #e8796f; }
  .marke.geeignet { background: #17301f; } .marke.bedingt_geeignet { background: #332612; }
  .marke.ungeeignet { background: #331c19; }
}
"""


def _e(text: Any) -> str:
    return html.escape(str(text or ""))


def html_bericht(
    dokumente: list[Dokument],
    auswertung: Auswertung,
    regelwerk: Regelwerk,
    profil: Profil,
    modellauswertung: dict[str, Any] | None = None,
) -> str:
    zahlen = auswertung.kennzahlen
    t: list[str] = []
    a = t.append

    a("<!doctype html><html lang='de'><head><meta charset='utf-8'>")
    a("<meta name='viewport' content='width=device-width, initial-scale=1'>")
    a(f"<title>Steuerunterlagen {regelwerk.jahr}</title>")
    a(f"<style>{_STIL}</style></head><body><main>")

    a(f"<h1>Steuerunterlagen {regelwerk.jahr}</h1>")
    kopfzeilen = []
    if profil.name:
        kopfzeilen.append(_e(profil.name))
    kopfzeilen.append(f"erstellt am {_dt.date.today().strftime('%d.%m.%Y')}")
    kopfzeilen.append(f"Rechtsstand {_e(regelwerk.stand)}")
    if regelwerk.ist_ersatz:
        kopfzeilen.append(f"<strong>ersatzweise Werte aus {regelwerk.quelle_jahr}</strong>")
    a(f"<p class='kopf'>{' · '.join(kopfzeilen)}</p>")

    kacheln = [
        ("Dokumente", str(zahlen["anzahl_dokumente"])),
        ("Einreichbar", str(zahlen["anzahl_geeignet"])),
        ("Offene Punkte", str(zahlen["anzahl_bedingt"])),
        ("Werbungskosten", _euro(zahlen["werbungskosten_gesamt"])),
        ("Haushaltsnah, 20 %", _euro(zahlen["haushaltsnahe_ermaessigung_geschaetzt"])),
        ("Chancen erkannt", str(len(auswertung.chancen))),
    ]
    a("<div class='kacheln'>")
    for titel, wert in kacheln:
        a(f"<div class='kachel'><div class='titel'>{_e(titel)}</div><div class='wert'>{_e(wert)}</div></div>")
    a("</div>")

    if modellauswertung and modellauswertung.get("gesamteinschaetzung"):
        a("<h2>Einschaetzung</h2>")
        a(f"<p>{_e(modellauswertung['gesamteinschaetzung'])}</p>")

    hinweise = (modellauswertung or {}).get("hinweise_fuer_den_steuerberater") or []
    if hinweise:
        a("<h2>Zuerst lesen</h2><ul>")
        for hinweis in hinweise:
            a(f"<li>{_e(hinweis)}</li>")
        a("</ul>")

    a("<h2>Unterlagen nach Anlagen</h2>")
    gruppen = _nach_kategorie(dokumente)
    for kategorie in taxonomy.KATEGORIEN:
        liste = gruppen.get(kategorie.id)
        if not liste:
            continue
        summe = sum(
            (d.analyse.betrag_abzugsfaehig or d.analyse.betrag_gesamt or 0.0)
            for d in liste
            if d.analyse and d.analyse.eignung != EIGNUNG_UNGEEIGNET
        )
        a("<div class='gruppe'>")
        a(f"<h3>{_e(kategorie.ordner)} — {_e(kategorie.label)}</h3>")
        a(
            f"<p class='zeile'>Anlage {_e(kategorie.anlage)} · {len(liste)} Dokumente · "
            f"Summe {_e(_euro(round(summe, 2)))}</p>"
        )
        a("<table><thead><tr><th>Datei</th><th>Datum</th><th>Art</th><th>Aussteller</th>"
          "<th class='betrag'>Betrag</th><th>Status</th></tr></thead><tbody>")
        for dokument in liste:
            analyse = dokument.analyse
            eignung = analyse.eignung if analyse else "unklar"
            a("<tr>")
            a(f"<td>{_e(dokument.zieldateiname or dokument.dateiname)}")
            if analyse and analyse.zusammenfassung:
                a(f"<br><span class='zeile'>{_e(analyse.zusammenfassung)}</span>")
            if analyse and analyse.fehlende_nachweise:
                a(
                    "<br><span class='zeile'><strong>Fehlt noch:</strong> "
                    + _e("; ".join(analyse.fehlende_nachweise))
                    + "</span>"
                )
            if dokument.notiz:
                a(
                    "<br><span class='zeile'><strong>Anmerkung des Mandanten:</strong> "
                    + _e(dokument.notiz)
                    + "</span>"
                )
            a("</td>")
            a(f"<td>{_e(_datum(analyse.datum) if analyse else '')}</td>")
            a(f"<td>{_e(analyse.dokumenttyp if analyse else '')}</td>")
            a(f"<td>{_e(analyse.aussteller if analyse else '')}</td>")
            betrag = (analyse.betrag_abzugsfaehig or analyse.betrag_gesamt) if analyse else None
            a(f"<td class='betrag'>{_e(_euro(betrag))}</td>")
            a(f"<td><span class='marke {_e(eignung)}'>{_e(EIGNUNG_LABEL.get(eignung, 'offen'))}</span></td>")
            a("</tr>")
        a("</tbody></table></div>")

    def _abschnitt(titel: str, befunde: list[Befund]) -> None:
        if not befunde:
            return
        a(f"<h2>{_e(titel)}</h2>")
        for befund in befunde:
            a(f"<div class='abschnitt {_e(befund.prioritaet)}'>")
            kopf = _e(befund.titel)
            if befund.potenzial_eur:
                kopf += f" — bis zu {_e(_euro(befund.potenzial_eur))}"
            a(f"<h3>{kopf}</h3>")
            meta = [f"Prioritaet {_e(befund.prioritaet)}"]
            if befund.anlage:
                meta.append(_e(befund.anlage))
            a(f"<p class='meta'>{' · '.join(meta)}</p>")
            a(f"<p>{_e(befund.beschreibung)}</p>")
            a("</div>")

    _abschnitt("Was noch fehlt", auswertung.luecken)
    _abschnitt("Wo Geld liegen bleibt", auswertung.chancen)
    _abschnitt("Warnungen", auswertung.warnungen)

    if modellauswertung:
        for schluessel, titel in (
            ("luecken", "Weitere Luecken aus der Gesamtauswertung"),
            ("chancen", "Weitere Chancen aus der Gesamtauswertung"),
        ):
            eintraege = modellauswertung.get(schluessel) or []
            if not eintraege:
                continue
            a(f"<h2>{_e(titel)}</h2>")
            for eintrag in eintraege:
                stufe = _e(eintrag.get("prioritaet", "mittel"))
                a(f"<div class='abschnitt {stufe}'>")
                kopf = _e(eintrag.get("titel", ""))
                if eintrag.get("potenzial_eur"):
                    kopf += f" — {_e(_euro(float(eintrag['potenzial_eur'])))}"
                a(f"<h3>{kopf}</h3>")
                if eintrag.get("rechtsgrundlage"):
                    a(f"<p class='meta'>{_e(eintrag['rechtsgrundlage'])}</p>")
                a(f"<p>{_e(eintrag.get('beschreibung', ''))}</p>")
                if eintrag.get("schaetzgrundlage"):
                    a(f"<p class='meta'>Grundlage der Schaetzung: {_e(eintrag['schaetzgrundlage'])}</p>")
                if eintrag.get("naechster_schritt"):
                    a(f"<p><strong>Naechster Schritt:</strong> {_e(eintrag['naechster_schritt'])}</p>")
                a("</div>")

        fragen = modellauswertung.get("fragen_an_den_mandanten") or []
        if fragen:
            a("<h2>Fragen an den Mandanten</h2><ul>")
            for frage in fragen:
                a(f"<li>{_e(frage)}</li>")
            a("</ul>")

    a(f"<p class='fuss'>{_e(HAFTUNGSHINWEIS)}</p>")
    a("</main></body></html>")
    return "\n".join(t)


# --------------------------------------------------------------------- CSV --

CSV_SPALTEN = [
    "ordner",
    "zieldatei",
    "originaldatei",
    "kategorie",
    "anlage",
    "datum",
    "steuerjahr",
    "dokumenttyp",
    "aussteller",
    "betrag_gesamt",
    "betrag_abzugsfaehig",
    "waehrung",
    "zahlungsart",
    "eignung",
    "begruendung",
    "fehlende_nachweise",
    "vertrauen",
    "zusammenfassung",
]


def csv_export(dokumente: list[Dokument]) -> str:
    puffer = io.StringIO()
    schreiber = csv.DictWriter(puffer, fieldnames=CSV_SPALTEN, delimiter=";")
    schreiber.writeheader()
    gruppen = _nach_kategorie(dokumente)
    for kategorie in taxonomy.KATEGORIEN:
        for dokument in gruppen.get(kategorie.id, []):
            analyse = dokument.analyse
            schreiber.writerow(
                {
                    "ordner": kategorie.ordner,
                    "zieldatei": dokument.zieldateiname,
                    "originaldatei": dokument.dateiname,
                    "kategorie": kategorie.label,
                    "anlage": kategorie.anlage,
                    "datum": analyse.datum if analyse else "",
                    "steuerjahr": analyse.steuerjahr if analyse else "",
                    "dokumenttyp": analyse.dokumenttyp if analyse else "",
                    "aussteller": analyse.aussteller if analyse else "",
                    "betrag_gesamt": analyse.betrag_gesamt if analyse else "",
                    "betrag_abzugsfaehig": analyse.betrag_abzugsfaehig if analyse else "",
                    "waehrung": analyse.waehrung if analyse else "",
                    "zahlungsart": analyse.zahlungsart if analyse else "",
                    "eignung": EIGNUNG_LABEL.get(analyse.eignung, "") if analyse else "",
                    "begruendung": analyse.eignung_begruendung if analyse else "",
                    "fehlende_nachweise": "; ".join(analyse.fehlende_nachweise) if analyse else "",
                    "vertrauen": f"{analyse.vertrauen:.2f}" if analyse else "",
                    "zusammenfassung": analyse.zusammenfassung if analyse else "",
                }
            )
    return puffer.getvalue()


def berichte_schreiben(
    ordner: Path,
    dokumente: list[Dokument],
    auswertung: Auswertung,
    regelwerk: Regelwerk,
    profil: Profil,
    modellauswertung: dict[str, Any] | None = None,
) -> list[Path]:
    """Schreibt alle Berichtsformate und liefert die erzeugten Pfade."""
    ordner = Path(ordner)
    ordner.mkdir(parents=True, exist_ok=True)
    erzeugt = []

    pfad = ordner / f"Uebersicht_{regelwerk.jahr}.html"
    pfad.write_text(html_bericht(dokumente, auswertung, regelwerk, profil, modellauswertung), encoding="utf-8")
    erzeugt.append(pfad)

    pfad = ordner / f"Uebersicht_{regelwerk.jahr}.md"
    pfad.write_text(markdown_bericht(dokumente, auswertung, regelwerk, profil, modellauswertung), encoding="utf-8")
    erzeugt.append(pfad)

    pfad = ordner / f"Dokumentliste_{regelwerk.jahr}.csv"
    pfad.write_text(csv_export(dokumente), encoding="utf-8-sig")
    erzeugt.append(pfad)

    # Eigene Datei statt eines Abschnitts im Bericht: Wer die Erklaerung
    # ausfuellt, hat sie dann neben dem Formular offen und muss nicht durch
    # eine Uebersicht blaettern.
    from . import formular  # lokal, um Zirkelbezuege zu vermeiden

    pfad = ordner / f"Formularzuordnung_{regelwerk.jahr}.md"
    pfad.write_text(
        formular.als_markdown(
            formular.aufstellung(dokumente, regelwerk), regelwerk, regelwerk.jahr
        ),
        encoding="utf-8",
    )
    erzeugt.append(pfad)

    return erzeugt


__all__ = [
    "EIGNUNG_BEDINGT",
    "EIGNUNG_GEEIGNET",
    "berichte_schreiben",
    "csv_export",
    "html_bericht",
    "markdown_bericht",
]
