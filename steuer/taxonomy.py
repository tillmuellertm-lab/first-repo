"""Kategorien steuerrelevanter Dokumente und ihre Zuordnung zu den Anlagen.

Die Reihenfolge der Eintraege bestimmt die Reihenfolge der Ordner in der
aufbereiteten Ablage und die Reihenfolge der Kapitel in der Uebersicht fuer den
Steuerberater. Sie folgt dem Aufbau der Einkommensteuererklaerung: erst
Stammdaten, dann Einkuenfte, dann Abzuege.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Kategorie:
    id: str
    label: str
    anlage: str
    ordner: str
    beschreibung: str
    stichworte: tuple[str, ...] = field(default=())


KATEGORIEN: tuple[Kategorie, ...] = (
    Kategorie(
        id="stammdaten",
        label="Stammdaten und Vollmachten",
        anlage="Mantelbogen",
        ordner="00_Stammdaten",
        beschreibung="Persoenliche Daten, Steuer-ID, Bankverbindung, Vollmacht, Meldebescheinigung.",
        stichworte=("steuer-identifikationsnummer", "steuer-id", "vollmacht", "meldebescheinigung", "iban"),
    ),
    Kategorie(
        id="vorjahr",
        label="Vorjahresunterlagen",
        anlage="Mantelbogen",
        ordner="01_Vorjahr",
        beschreibung="Steuerbescheide und Erklaerungen frueherer Jahre, Vorauszahlungsbescheide.",
        stichworte=("steuerbescheid", "einkommensteuerbescheid", "vorauszahlung", "festsetzung"),
    ),
    Kategorie(
        id="nichtselbstaendige_arbeit",
        label="Nichtselbstaendige Arbeit",
        anlage="Anlage N",
        ordner="10_Anlage_N_Einkuenfte",
        beschreibung="Lohnsteuerbescheinigungen, Arbeitsvertraege, Abfindungen, Sachbezuege.",
        stichworte=("lohnsteuerbescheinigung", "gehaltsabrechnung", "arbeitsvertrag", "abfindung", "bruttoarbeitslohn"),
    ),
    Kategorie(
        id="werbungskosten_fahrten",
        label="Fahrten und Reisekosten",
        anlage="Anlage N",
        ordner="11_Anlage_N_Fahrten_Reisekosten",
        beschreibung="Entfernungspauschale, Dienstreisen, Fahrtenbuch, Jobticket, Verpflegungsmehraufwand.",
        stichworte=("fahrtkosten", "jobticket", "deutschlandticket", "reisekostenabrechnung", "fahrtenbuch", "km"),
    ),
    Kategorie(
        id="werbungskosten_arbeitsmittel",
        label="Arbeitsmittel und Fachliteratur",
        anlage="Anlage N",
        ordner="12_Anlage_N_Arbeitsmittel",
        beschreibung="Notebook, Monitor, Buerostuhl, Software, Fachbuecher, Berufskleidung.",
        stichworte=("notebook", "laptop", "monitor", "buerostuhl", "fachbuch", "software", "arbeitsmittel"),
    ),
    Kategorie(
        id="werbungskosten_arbeitszimmer",
        label="Arbeitszimmer und Homeoffice",
        anlage="Anlage N",
        ordner="13_Anlage_N_Arbeitszimmer_Homeoffice",
        beschreibung="Homeoffice-Tage, Mietvertrag und Nebenkosten fuer das haeusliche Arbeitszimmer.",
        stichworte=("homeoffice", "arbeitszimmer", "heimarbeit", "mietvertrag"),
    ),
    Kategorie(
        id="werbungskosten_fortbildung",
        label="Fort- und Weiterbildung",
        anlage="Anlage N",
        ordner="14_Anlage_N_Fortbildung",
        beschreibung="Seminare, Kurse, Zertifizierungen, Pruefungsgebuehren, Fachtagungen.",
        stichworte=("seminar", "weiterbildung", "fortbildung", "zertifizierung", "kursgebuehr", "schulung"),
    ),
    Kategorie(
        id="werbungskosten_sonstige",
        label="Sonstige Werbungskosten",
        anlage="Anlage N",
        ordner="15_Anlage_N_Sonstige_Werbungskosten",
        beschreibung="Berufsverbaende, Bewerbungskosten, Umzug, doppelte Haushaltsfuehrung, Kontofuehrung.",
        stichworte=("gewerkschaft", "berufsverband", "bewerbung", "umzug", "doppelte haushaltsfuehrung"),
    ),
    Kategorie(
        id="lohnersatzleistungen",
        label="Lohnersatzleistungen",
        anlage="Anlage N / Mantelbogen",
        ordner="16_Lohnersatzleistungen",
        beschreibung="Arbeitslosengeld, Kurzarbeitergeld, Krankengeld, Elterngeld, Mutterschaftsgeld.",
        stichworte=("arbeitslosengeld", "kurzarbeitergeld", "krankengeld", "elterngeld", "mutterschaftsgeld", "progressionsvorbehalt"),
    ),
    Kategorie(
        id="kapitalertraege",
        label="Kapitalertraege",
        anlage="Anlage KAP",
        ordner="20_Anlage_KAP",
        beschreibung="Jahressteuerbescheinigungen, Verlustbescheinigungen, Quellensteuer, Depotertraege.",
        stichworte=("jahressteuerbescheinigung", "kapitalertragsteuer", "abgeltungsteuer", "verlustbescheinigung", "depot", "dividende"),
    ),
    Kategorie(
        id="vermietung",
        label="Vermietung und Verpachtung",
        anlage="Anlage V",
        ordner="21_Anlage_V",
        beschreibung="Mieteinnahmen, Darlehenszinsen, Grundsteuer, Reparaturen, Hausgeldabrechnung.",
        stichworte=("mieteinnahmen", "mietvertrag", "hausgeld", "grundsteuer", "darlehenszinsen", "eigentuemergemeinschaft"),
    ),
    Kategorie(
        id="selbstaendig",
        label="Selbstaendige und gewerbliche Einkuenfte",
        anlage="Anlage S / G / EUeR",
        ordner="22_Anlage_S_G_EUeR",
        beschreibung="Einnahmen-Ueberschuss-Rechnung, Ausgangsrechnungen, Betriebsausgaben, Umsatzsteuer.",
        stichworte=("rechnung", "eueR", "einnahmenueberschussrechnung", "umsatzsteuervoranmeldung", "betriebsausgabe", "honorar"),
    ),
    Kategorie(
        id="renten",
        label="Renten und Versorgungsbezuege",
        anlage="Anlage R",
        ordner="23_Anlage_R",
        beschreibung="Rentenbezugsmitteilung, Rentenanpassung, Betriebsrenten, Zusatzversorgung.",
        stichworte=("rentenbezugsmitteilung", "rentenanpassung", "deutsche rentenversicherung", "betriebsrente"),
    ),
    Kategorie(
        id="sonstige_einkuenfte",
        label="Sonstige Einkuenfte und private Veraeusserungen",
        anlage="Anlage SO",
        ordner="24_Anlage_SO",
        beschreibung="Private Veraeusserungsgeschaefte, Kryptowerte, Unterhaltseinnahmen, gelegentliche Leistungen.",
        stichworte=("krypto", "bitcoin", "veraeusserungsgewinn", "transaktionsreport", "steuerreport"),
    ),
    Kategorie(
        id="auslandseinkuenfte",
        label="Auslandseinkuenfte",
        anlage="Anlage AUS / N-AUS",
        ordner="25_Anlage_AUS",
        beschreibung="Auslaendische Steuerbescheide, Quellensteuernachweise, Bescheinigungen nach DBA.",
        stichworte=("quellensteuer", "doppelbesteuerung", "foreign tax", "withholding"),
    ),
    Kategorie(
        id="vorsorgeaufwendungen",
        label="Vorsorgeaufwendungen",
        anlage="Anlage Vorsorgeaufwand",
        ordner="30_Anlage_Vorsorgeaufwand",
        beschreibung="Kranken- und Pflegeversicherung, Haftpflicht, Berufsunfaehigkeit, Ruerup, Unfallversicherung.",
        stichworte=("krankenversicherung", "pflegeversicherung", "haftpflicht", "berufsunfaehigkeit", "ruerup", "basisrente", "beitragsbescheinigung"),
    ),
    Kategorie(
        id="altersvorsorge_av",
        label="Riester und Altersvorsorgezulage",
        anlage="Anlage AV",
        ordner="31_Anlage_AV",
        beschreibung="Bescheinigung nach § 10a EStG, Zulagenbescheide, Riester-Vertraege.",
        stichworte=("riester", "altersvorsorgezulage", "zulagennummer", "10a estg"),
    ),
    Kategorie(
        id="sonderausgaben",
        label="Sonderausgaben",
        anlage="Sonderausgaben",
        ordner="32_Sonderausgaben",
        beschreibung="Spenden, Kirchensteuer, Berufsausbildungskosten, Schulgeld, Unterhalt.",
        stichworte=("zuwendungsbestaetigung", "spendenquittung", "kirchensteuer", "schulgeld", "studiengebuehr"),
    ),
    Kategorie(
        id="aussergewoehnliche_belastungen",
        label="Aussergewoehnliche Belastungen",
        anlage="Aussergewoehnliche Belastungen",
        ordner="33_Aussergewoehnliche_Belastungen",
        beschreibung="Krankheitskosten, Zuzahlungen, Zahnersatz, Brille, Kur, Pflege, Behinderung, Bestattung.",
        stichworte=("zuzahlung", "rezept", "zahnarzt", "brille", "hoergeraet", "pflegegrad", "schwerbehindertenausweis", "attest"),
    ),
    Kategorie(
        id="haushaltsnahe_aufwendungen",
        label="Haushaltsnahe Aufwendungen und Handwerker",
        anlage="Anlage haushaltsnahe Aufwendungen",
        ordner="34_Haushaltsnahe_Aufwendungen",
        beschreibung="Handwerkerrechnungen, Reinigung, Gartenpflege, Winterdienst, Nebenkostenabrechnung, Schornsteinfeger.",
        stichworte=("handwerker", "lohnanteil", "nebenkostenabrechnung", "betriebskostenabrechnung", "schornsteinfeger", "gartenpflege", "winterdienst", "hausmeister"),
    ),
    Kategorie(
        id="kinder",
        label="Kinder",
        anlage="Anlage Kind",
        ordner="35_Anlage_Kind",
        beschreibung="Kindergeld, Betreuungskosten, Schulgeld, Ausbildungsnachweise, Kinderfreibetraege.",
        stichworte=("kindergeld", "kita", "kindergarten", "betreuungsvertrag", "immatrikulation", "ausbildungsvertrag"),
    ),
    Kategorie(
        id="unterhalt",
        label="Unterhaltsleistungen",
        anlage="Anlage U / Unterhalt",
        ordner="36_Unterhalt",
        beschreibung="Realsplitting, Unterhalt an beduerftige Personen, Zahlungsnachweise.",
        stichworte=("unterhalt", "realsplitting", "anlage u", "trennungsunterhalt"),
    ),
    Kategorie(
        id="zahlungsnachweise",
        label="Zahlungsnachweise",
        anlage="belegbegleitend",
        ordner="90_Zahlungsnachweise",
        beschreibung="Kontoauszuege und Ueberweisungsbelege, die eine Rechnung erst abzugsfaehig machen.",
        stichworte=("kontoauszug", "ueberweisung", "lastschrift", "zahlungsbeleg"),
    ),
    Kategorie(
        id="unklar",
        label="Klaerung erforderlich",
        anlage="offen",
        ordner="98_Klaerung_erforderlich",
        beschreibung="Dokumente, deren steuerliche Einordnung ohne Ruecksprache nicht moeglich ist.",
    ),
    Kategorie(
        id="nicht_steuerrelevant",
        label="Nicht steuerrelevant",
        anlage="keine",
        ordner="99_Nicht_steuerrelevant",
        beschreibung="Dokumente ohne steuerliche Bedeutung. Werden nicht an den Steuerberater uebergeben.",
    ),
)

NACH_ID: dict[str, Kategorie] = {k.id: k for k in KATEGORIEN}

# Kategorien, die nicht in die Uebergabe an den Steuerberater gehoeren.
AUSGESCHLOSSEN: frozenset[str] = frozenset({"nicht_steuerrelevant"})


def kategorie(kategorie_id: str) -> Kategorie:
    """Liefert die Kategorie zur id, faellt bei Unbekanntem auf 'unklar' zurueck."""
    return NACH_ID.get(kategorie_id, NACH_ID["unklar"])


def sortierschluessel(kategorie_id: str) -> int:
    """Position der Kategorie in der Uebergabereihenfolge."""
    for index, eintrag in enumerate(KATEGORIEN):
        if eintrag.id == kategorie_id:
            return index
    return len(KATEGORIEN)


def ids() -> list[str]:
    return [k.id for k in KATEGORIEN]
