"""Aufstellung der Einnahmen und Ausgaben als Zuarbeit zur Einnahmen-Ueberschuss-Rechnung.

Das Werkzeug fuellt keine Anlage EUeR aus. Es fasst die erfassten Belege zu einer
geordneten Aufstellung zusammen, aus der der Steuerberater die EUeR erstellt.
Die Zuordnung zu den Posten ist ein Vorschlag und muss geprueft werden.

Die Postenbezeichnungen folgen dem Aufbau der Anlage EUeR nach Paragraf 4 Abs. 3
EStG, sind aber bewusst zusammengefasst: eine feinere Aufteilung als der
Dokumentenbestand hergibt, taeuscht Genauigkeit nur vor.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
from dataclasses import dataclass, field
from typing import Iterable

from .formatierung import euro
from .models import EIGNUNG_UNGEEIGNET, Dokument

EINNAHME = "einnahme"
AUSGABE = "ausgabe"


@dataclass(frozen=True)
class Posten:
    id: str
    label: str
    art: str
    stichworte: tuple[str, ...] = ()
    hinweis: str = ""


# Reihenfolge = Reihenfolge in der Aufstellung.
POSTEN: tuple[Posten, ...] = (
    Posten(
        id="betriebseinnahmen",
        label="Betriebseinnahmen",
        art=EINNAHME,
        stichworte=("ausgangsrechnung", "honorar", "erloes", "umsatz", "gutschrift", "auszahlung", "payout"),
    ),
    Posten(
        id="sonstige_einnahmen",
        label="Sonstige Betriebseinnahmen",
        art=EINNAHME,
        stichworte=("zuschuss", "foerderung", "erstattung", "entschaedigung"),
        hinweis="Auch die Privatnutzung betrieblicher Gegenstaende gehoert hierher.",
    ),
    Posten(
        id="wareneinkauf",
        label="Wareneinkauf, Roh-, Hilfs- und Betriebsstoffe",
        art=AUSGABE,
        stichworte=("wareneinkauf", "material", "rohstoff", "einkauf", "grosshandel"),
    ),
    Posten(
        id="fremdleistungen",
        label="Fremdleistungen",
        art=AUSGABE,
        stichworte=("fremdleistung", "subunternehmer", "auftrag an", "dienstleistung", "agentur"),
    ),
    Posten(
        id="personal",
        label="Personalkosten",
        art=AUSGABE,
        stichworte=("lohn", "gehalt", "minijob", "sozialversicherung arbeitgeber", "lohnabrechnung"),
    ),
    Posten(
        id="abschreibung",
        label="Abschreibungen und geringwertige Wirtschaftsgueter",
        art=AUSGABE,
        stichworte=("anlagevermoegen", "afa", "abschreibung", "notebook", "laptop", "computer", "monitor", "moebel"),
        hinweis="Ab 800 EUR netto ueber die Nutzungsdauer verteilt, darunter sofort abziehbar.",
    ),
    Posten(
        id="raumkosten",
        label="Raumkosten und Miete",
        art=AUSGABE,
        stichworte=("miete", "pacht", "nebenkosten", "strom", "heizung", "gas", "reinigung"),
    ),
    Posten(
        id="fahrzeug",
        label="Fahrzeugkosten",
        art=AUSGABE,
        stichworte=("tankstelle", "kraftstoff", "benzin", "diesel", "werkstatt", "kfz", "leasing", "parkgebuehr"),
    ),
    Posten(
        id="reisekosten",
        label="Reise- und Uebernachtungskosten",
        art=AUSGABE,
        stichworte=("bahn", "flug", "hotel", "uebernachtung", "reisekosten", "taxi", "mietwagen"),
    ),
    Posten(
        id="werbung",
        label="Werbe- und Repraesentationskosten",
        art=AUSGABE,
        stichworte=("werbung", "anzeige", "marketing", "facebook", "google ads", "visitenkarte", "messe"),
    ),
    Posten(
        id="bewirtung",
        label="Bewirtungskosten",
        art=AUSGABE,
        stichworte=("bewirtung", "restaurant", "gaststaette", "catering"),
        hinweis="Nur zu 70 Prozent abziehbar, und nur mit ordnungsgemaessem Bewirtungsbeleg.",
    ),
    Posten(
        id="buero",
        label="Buerobedarf, Porto, Telefon und Internet",
        art=AUSGABE,
        stichworte=("buerobedarf", "porto", "telefon", "internet", "mobilfunk", "software", "hosting", "domain"),
    ),
    Posten(
        id="fortbildung",
        label="Fortbildungskosten",
        art=AUSGABE,
        stichworte=("fortbildung", "seminar", "schulung", "kurs", "fachbuch", "coaching"),
    ),
    Posten(
        id="versicherung_beitrag",
        label="Beitraege, Gebuehren, Versicherungen",
        art=AUSGABE,
        stichworte=("versicherung", "beitrag", "kammer", "ihk", "gebuehr", "mitgliedschaft"),
        hinweis="Nur betriebliche Versicherungen; private gehoeren in die Vorsorgeaufwendungen.",
    ),
    Posten(
        id="beratung",
        label="Rechts- und Steuerberatung, Buchfuehrung",
        art=AUSGABE,
        stichworte=("steuerberater", "rechtsanwalt", "notar", "buchhaltung", "buchfuehrung"),
    ),
    Posten(
        id="zinsen",
        label="Schuldzinsen",
        art=AUSGABE,
        stichworte=("zinsen", "darlehen", "kredit", "finanzierung"),
    ),
    Posten(
        id="uebrige",
        label="Uebrige Betriebsausgaben",
        art=AUSGABE,
        stichworte=(),
        hinweis="Sammelposten fuer alles, was sich keinem anderen Posten zuordnen liess.",
    ),
)

NACH_ID = {p.id: p for p in POSTEN}
SAMMELPOSTEN = "uebrige"

# Kategorien, die niemals Betriebseinnahmen oder Betriebsausgaben sein koennen.
# Ohne diese Sperre wuerde eine Lohnsteuerbescheinigung als Betriebseinnahme
# gezaehlt, und die Aufstellung saehe richtig aus, waehrend sie es nicht ist.
PRIVATE_KATEGORIEN = frozenset({
    "stammdaten",
    "vorjahr",
    "nichtselbstaendige_arbeit",
    "werbungskosten_fahrten",
    "werbungskosten_arbeitsmittel",
    "werbungskosten_arbeitszimmer",
    "werbungskosten_fortbildung",
    "werbungskosten_sonstige",
    "lohnersatzleistungen",
    "kapitalertraege",
    "vermietung",
    "renten",
    "sonstige_einkuenfte",
    "vorsorgeaufwendungen",
    "altersvorsorge_av",
    "sonderausgaben",
    "aussergewoehnliche_belastungen",
    "haushaltsnahe_aufwendungen",
    "kinder",
    "unterhalt",
})


def ids() -> list[str]:
    return [p.id for p in POSTEN]


def postenuebersicht() -> str:
    """Kurze Liste der Posten fuer den Systemprompt."""
    zeilen = []
    for posten in POSTEN:
        art = "Einnahme" if posten.art == EINNAHME else "Ausgabe"
        zeilen.append(f"- {posten.id} ({art}): {posten.label}")
    return "\n".join(zeilen)


@dataclass
class Zeile:
    """Ein Posten der Aufstellung mit den zugehoerigen Belegen."""

    posten: Posten
    betrag: float = 0.0
    dokumente: list[Dokument] = field(default_factory=list)

    @property
    def anzahl(self) -> int:
        return len(self.dokumente)


@dataclass
class Aufstellung:
    jahr: int
    einnahmen: list[Zeile] = field(default_factory=list)
    ausgaben: list[Zeile] = field(default_factory=list)
    ungeklaert: list[Dokument] = field(default_factory=list)
    ohne_betrag: list[Dokument] = field(default_factory=list)
    privat: list[Dokument] = field(default_factory=list)
    # Belege, deren Richtung aus der Analyse stammt bzw. nur geraten wurde.
    aus_analyse: int = 0
    geschaetzt: int = 0

    @property
    def summe_einnahmen(self) -> float:
        return round(sum(z.betrag for z in self.einnahmen), 2)

    @property
    def summe_ausgaben(self) -> float:
        return round(sum(z.betrag for z in self.ausgaben), 2)

    @property
    def ergebnis(self) -> float:
        """Vorlaeufiger Gewinn oder Verlust."""
        return round(self.summe_einnahmen - self.summe_ausgaben, 2)

    @property
    def ist_verlust(self) -> bool:
        return self.ergebnis < 0

    @property
    def anzahl_belege(self) -> int:
        return sum(z.anzahl for z in self.einnahmen + self.ausgaben)

    @property
    def nur_geraten(self) -> bool:
        """Kein einziger Beleg trug die Richtung aus der Analyse bei.

        Typisch fuer Mappen, die vor Einfuehrung der Felder analysiert wurden.
        Die Summen beruhen dann allein auf Stichworten und sind unbrauchbar.
        """
        return self.geschaetzt > 0 and self.aus_analyse == 0


def _suchtext(dokument: Dokument) -> str:
    analyse = dokument.analyse
    if not analyse:
        return dokument.dateiname.lower()
    teile = [
        dokument.dateiname,
        analyse.dokumenttyp,
        analyse.aussteller,
        analyse.zusammenfassung,
        " ".join(p.bezeichnung for p in analyse.positionen),
    ]
    return " ".join(teile).lower()


def _richtung(dokument: Dokument) -> tuple[str | None, str]:
    """Einnahme oder Ausgabe samt Herkunft der Angabe.

    Vorrang hat die Angabe aus der Analyse; nur wenn sie fehlt, wird anhand
    von Stichworten geschaetzt. Was unklar bleibt, wird auch als unklar
    ausgewiesen, statt es zu raten. Die Herkunft wird mitgefuehrt, weil eine
    geratene Richtung sehr viel weniger wert ist als eine gelesene.
    """
    analyse = dokument.analyse
    if analyse and analyse.geschaeftsvorfall in (EINNAHME, AUSGABE):
        return analyse.geschaeftsvorfall, "analyse"

    text = _suchtext(dokument)
    einnahme_worte = ("ausgangsrechnung", "honorar", "erloes", "gutschrift", "auszahlung", "payout", "zahlungseingang")
    ausgabe_worte = ("eingangsrechnung", "quittung", "kassenbon", "beleg ueber", "rechnung von", "lastschrift", "abbuchung")
    if any(wort in text for wort in einnahme_worte):
        return EINNAHME, "stichwort"
    if any(wort in text for wort in ausgabe_worte):
        return AUSGABE, "stichwort"
    return None, ""


def _posten_bestimmen(dokument: Dokument, richtung: str) -> Posten:
    analyse = dokument.analyse
    if analyse and analyse.euer_posten in NACH_ID:
        posten = NACH_ID[analyse.euer_posten]
        if posten.art == richtung:
            return posten

    text = _suchtext(dokument)
    for posten in POSTEN:
        if posten.art != richtung or not posten.stichworte:
            continue
        if any(wort in text for wort in posten.stichworte):
            return posten
    return NACH_ID[SAMMELPOSTEN] if richtung == AUSGABE else NACH_ID["sonstige_einnahmen"]


def _betrag(dokument: Dokument) -> float | None:
    analyse = dokument.analyse
    if not analyse:
        return None
    for wert in (analyse.betrag_gesamt, analyse.betrag_abzugsfaehig):
        if wert is not None:
            return float(wert)
    return None


def aufstellen(dokumente: Iterable[Dokument], jahr: int) -> Aufstellung:
    """Fasst die Belege zu einer Aufstellung nach EUeR-Posten zusammen."""
    aufstellung = Aufstellung(jahr=jahr)
    zeilen: dict[str, Zeile] = {p.id: Zeile(posten=p) for p in POSTEN}

    for dokument in dokumente:
        analyse = dokument.analyse
        if not analyse or analyse.eignung == EIGNUNG_UNGEEIGNET:
            continue
        if dokument.wirksame_kategorie in PRIVATE_KATEGORIEN:
            aufstellung.privat.append(dokument)
            continue
        betrag = _betrag(dokument)
        if betrag is None:
            aufstellung.ohne_betrag.append(dokument)
            continue
        richtung, herkunft = _richtung(dokument)
        if richtung is None:
            aufstellung.ungeklaert.append(dokument)
            continue
        if herkunft == "analyse":
            aufstellung.aus_analyse += 1
        else:
            aufstellung.geschaetzt += 1
        posten = _posten_bestimmen(dokument, richtung)
        zeile = zeilen[posten.id]
        zeile.betrag = round(zeile.betrag + abs(betrag), 2)
        zeile.dokumente.append(dokument)

    aufstellung.einnahmen = [z for z in zeilen.values() if z.posten.art == EINNAHME and z.anzahl]
    aufstellung.ausgaben = [z for z in zeilen.values() if z.posten.art == AUSGABE and z.anzahl]
    return aufstellung


# ------------------------------------------------------------------ Ausgabe --

CSV_SPALTEN = ["art", "posten", "anzahl_belege", "betrag_eur", "hinweis"]


def csv_export(aufstellung: Aufstellung) -> str:
    puffer = io.StringIO()
    schreiber = csv.DictWriter(puffer, fieldnames=CSV_SPALTEN, delimiter=";")
    schreiber.writeheader()
    for zeile in aufstellung.einnahmen:
        schreiber.writerow({
            "art": "Einnahme", "posten": zeile.posten.label, "anzahl_belege": zeile.anzahl,
            "betrag_eur": f"{zeile.betrag:.2f}".replace(".", ","), "hinweis": zeile.posten.hinweis,
        })
    for zeile in aufstellung.ausgaben:
        schreiber.writerow({
            "art": "Ausgabe", "posten": zeile.posten.label, "anzahl_belege": zeile.anzahl,
            "betrag_eur": f"{zeile.betrag:.2f}".replace(".", ","), "hinweis": zeile.posten.hinweis,
        })
    schreiber.writerow({
        "art": "Summe", "posten": "Betriebseinnahmen", "anzahl_belege": "",
        "betrag_eur": f"{aufstellung.summe_einnahmen:.2f}".replace(".", ","), "hinweis": "",
    })
    schreiber.writerow({
        "art": "Summe", "posten": "Betriebsausgaben", "anzahl_belege": "",
        "betrag_eur": f"{aufstellung.summe_ausgaben:.2f}".replace(".", ","), "hinweis": "",
    })
    schreiber.writerow({
        "art": "Ergebnis", "posten": "Verlust" if aufstellung.ist_verlust else "Gewinn",
        "anzahl_belege": "", "betrag_eur": f"{aufstellung.ergebnis:.2f}".replace(".", ","),
        "hinweis": "vorlaeufig, vor Pruefung durch den Steuerberater",
    })
    return puffer.getvalue()


def belege(anzahl: int) -> str:
    """'1 Beleg' oder '5 Belege' - die Berichte lesen Menschen."""
    return f"{anzahl} Beleg" if anzahl == 1 else f"{anzahl} Belege"


def markdown_bericht(aufstellung: Aufstellung, name: str = "") -> str:
    zeilen: list[str] = []
    a = zeilen.append

    a(f"# Aufstellung der Einnahmen und Ausgaben {aufstellung.jahr}")
    a("")
    if name:
        a(f"**Betrieb:** {name}  ")
    a(f"**Erstellt am:** {_dt.date.today().strftime('%d.%m.%Y')}  ")
    a(f"**Erfasste Belege:** {aufstellung.anzahl_belege}  ")
    a("")
    a("> Diese Aufstellung ersetzt keine Einnahmen-Ueberschuss-Rechnung. Sie fasst die")
    a("> vorhandenen Belege zusammen, damit der Steuerberater die Anlage EUeR daraus")
    a("> erstellen kann. Die Zuordnung zu den Posten ist ein Vorschlag.")
    a("")

    if aufstellung.nur_geraten:
        a("## Die Summen sind hier nicht belastbar")
        a("")
        a("Bei **keinem einzigen** Beleg stand in der Analyse, ob es sich um eine Einnahme")
        a("oder eine Ausgabe handelt. Die Richtung wurde deshalb durchweg anhand von")
        a("Stichworten geraten, und das geht regelmaessig schief: Auf einem Kontoauszug")
        a("steht \"Gutschrift\" auch dort, wo Geld abgeht.")
        a("")
        a("Die Dokumente stammen aus einer Pruefung, die diese Angabe noch nicht erhoben")
        a("hat. Abhilfe: die Belege mit `steuer analyse --alle` erneut pruefen lassen,")
        a("danach diese Aufstellung neu erzeugen.")
        a("")
        a("**Bis dahin sind die folgenden Zahlen nur eine grobe Sortierhilfe.**")
        a("")
    elif aufstellung.geschaetzt:
        anteil = aufstellung.geschaetzt / max(aufstellung.anzahl_belege, 1)
        a(f"> Bei {belege(aufstellung.geschaetzt)} ({anteil:.0%}) wurde die Richtung nicht")
        a("> aus dem Dokument gelesen, sondern anhand von Stichworten geschaetzt.")
        a("")

    a("## Betriebseinnahmen")
    a("")
    if aufstellung.einnahmen:
        a("| Posten | Belege | Betrag |")
        a("| --- | ---: | ---: |")
        for zeile in aufstellung.einnahmen:
            a(f"| {zeile.posten.label} | {zeile.anzahl} | {euro(zeile.betrag)} |")
        a(f"| **Summe** | **{sum(z.anzahl for z in aufstellung.einnahmen)}** | **{euro(aufstellung.summe_einnahmen)}** |")
    else:
        a("Keine Einnahmen erfasst.")
    a("")

    a("## Betriebsausgaben")
    a("")
    if aufstellung.ausgaben:
        a("| Posten | Belege | Betrag |")
        a("| --- | ---: | ---: |")
        for zeile in aufstellung.ausgaben:
            a(f"| {zeile.posten.label} | {zeile.anzahl} | {euro(zeile.betrag)} |")
        a(f"| **Summe** | **{sum(z.anzahl for z in aufstellung.ausgaben)}** | **{euro(aufstellung.summe_ausgaben)}** |")
    else:
        a("Keine Ausgaben erfasst.")
    a("")

    a("## Vorlaeufiges Ergebnis")
    a("")
    bezeichnung = "Verlust" if aufstellung.ist_verlust else "Gewinn"
    a(f"**{bezeichnung}: {euro(abs(aufstellung.ergebnis))}**")
    a("")
    if aufstellung.ist_verlust:
        a("Ein Verlust ist steuerlich kein Nachteil: Er laesst sich mit anderen Einkuenften")
        a("verrechnen, bei Zusammenveranlagung auch mit denen des Ehepartners. Bei laengeren")
        a("Verlustserien prueft das Finanzamt allerdings, ob eine Gewinnerzielungsabsicht")
        a("besteht (Stichwort Liebhaberei). Der Steuerberater sollte das einordnen.")
        a("")

    hinweise = [z.posten for z in aufstellung.ausgaben if z.posten.hinweis]
    if hinweise:
        a("## Zu beachten")
        a("")
        for posten in hinweise:
            a(f"- **{posten.label}:** {posten.hinweis}")
        a("")

    if aufstellung.privat:
        a("## Nicht beruecksichtigt: private Unterlagen")
        a("")
        a(f"**{belege(len(aufstellung.privat))}** gehoeren zu Kategorien, die keine")
        a("Betriebseinnahmen oder -ausgaben sein koennen (Arbeitslohn, Renten, Vorsorge,")
        a("Kinder und aehnliches). Sie wurden uebergangen. Sind es viele, ist das ein")
        a("Zeichen dafuer, dass hier private Steuerunterlagen und Betriebsbelege in")
        a("derselben Mappe liegen.")
        a("")

    if aufstellung.ungeklaert or aufstellung.ohne_betrag:
        a("## Offene Punkte")
        a("")
        if aufstellung.ungeklaert:
            a(f"**{belege(len(aufstellung.ungeklaert))} ohne klare Richtung.** Hier liess sich")
            a("nicht sicher bestimmen, ob es sich um Einnahmen oder Ausgaben handelt. Sie sind")
            a("in den Summen oben **nicht** enthalten:")
            a("")
            for dokument in aufstellung.ungeklaert[:30]:
                betrag = euro(_betrag(dokument))
                a(f"- {dokument.dateiname} ({betrag})")
            if len(aufstellung.ungeklaert) > 30:
                a(f"- … und {len(aufstellung.ungeklaert) - 30} weitere")
            a("")
        if aufstellung.ohne_betrag:
            a(f"**{belege(len(aufstellung.ohne_betrag))} ohne erkennbaren Betrag.** Auch sie fehlen")
            a("in den Summen:")
            a("")
            for dokument in aufstellung.ohne_betrag[:20]:
                a(f"- {dokument.dateiname}")
            if len(aufstellung.ohne_betrag) > 20:
                a(f"- … und {len(aufstellung.ohne_betrag) - 20} weitere")
            a("")

    a("---")
    a("")
    a("Die Betraege stammen aus der maschinellen Auswertung der Belege und sind vor der")
    a("Verwendung abzugleichen. Ob Betraege brutto oder netto anzusetzen sind, haengt")
    a("davon ab, ob die Kleinunternehmerregelung nach Paragraf 19 UStG angewendet wird;")
    a("das ist hier nicht beruecksichtigt.")
    a("")
    return "\n".join(zeilen)
