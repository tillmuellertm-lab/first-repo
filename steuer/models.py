"""Datenmodell des Steuer-Assistenten.

Alle Objekte sind bewusst als schlanke Dataclasses mit JSON-Serialisierung
ausgelegt: der gesamte Zustand einer Arbeitsmappe liegt als lesbares JSON auf
der Platte, damit jederzeit nachvollziehbar bleibt, was das Werkzeug ueber ein
Dokument gespeichert hat.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import asdict, dataclass, field
from typing import Any

# Bewertung, ob ein Dokument fuer die Einreichung taugt.
EIGNUNG_GEEIGNET = "geeignet"
EIGNUNG_BEDINGT = "bedingt_geeignet"
EIGNUNG_UNGEEIGNET = "ungeeignet"
EIGNUNG_UNKLAR = "unklar"

EIGNUNG_LABEL = {
    EIGNUNG_GEEIGNET: "geeignet",
    EIGNUNG_BEDINGT: "bedingt geeignet",
    EIGNUNG_UNGEEIGNET: "nicht geeignet",
    EIGNUNG_UNKLAR: "unklar",
}

EIGNUNG_REIHENFOLGE = [EIGNUNG_GEEIGNET, EIGNUNG_BEDINGT, EIGNUNG_UNKLAR, EIGNUNG_UNGEEIGNET]

# Wird erhoeht, wenn die Analyse neue Felder erhebt. So laesst sich erkennen,
# welche Dokumente von einer aelteren Fassung geprueft wurden und nachgeholt
# werden muessen, ohne den gesamten Bestand erneut zu bezahlen.
ANALYSE_VERSION = 1

STATUS_NEU = "neu"
STATUS_ANALYSIERT = "analysiert"
STATUS_FEHLER = "fehler"

# Merkmale, die die Lueckenanalyse steuert. Reihenfolge = Reihenfolge im Formular.
MERKMALE: tuple[tuple[str, str], ...] = (
    ("angestellt", "Angestellt beschaeftigt"),
    ("jobwechsel", "Arbeitgeberwechsel oder Bewerbungen im Jahr"),
    ("homeoffice", "Arbeit von zu Hause"),
    ("pendler", "Regelmaessige Fahrten zur Arbeit"),
    ("doppelter_haushalt", "Zweitwohnung aus beruflichen Gruenden"),
    ("umzug", "Umzug im Steuerjahr"),
    ("lohnersatzleistungen", "Arbeitslosen-, Kranken-, Kurzarbeiter- oder Elterngeld"),
    ("selbstaendig", "Selbstaendige oder gewerbliche Einkuenfte"),
    ("vermietung", "Einkuenfte aus Vermietung"),
    ("rente", "Renten oder Versorgungsbezuege"),
    ("kapitalanlagen", "Depot, Zinsen oder Dividenden"),
    ("krypto", "Kryptowerte oder private Veraeusserungsgeschaefte"),
    ("auslandseinkuenfte", "Einkuenfte oder Konten im Ausland"),
    ("eigener_haushalt", "Eigener Haushalt"),
    ("mieter", "Zur Miete wohnend"),
    ("eigentuemer", "Selbstgenutztes Wohneigentum"),
    ("kinder", "Kinder"),
    ("studium", "Studium oder Zweitausbildung"),
    ("unterhalt", "Unterhaltszahlungen geleistet"),
    ("behinderung", "Anerkannte Behinderung"),
    ("pflege", "Angehoerige gepflegt"),
    ("kirchensteuerpflichtig", "Kirchensteuerpflichtig"),
    ("riester", "Riester-Vertrag"),
    ("ehrenamt", "Ehrenamtliche Taetigkeit"),
)

MERKMAL_IDS = frozenset(m for m, _ in MERKMALE)


def _heute() -> str:
    return _dt.date.today().isoformat()


@dataclass
class Profil:
    """Steuerliche Ausgangslage. Steuert Lueckenanalyse und Optimierungsvorschlaege."""

    name: str = ""
    veranlagungsjahr: int = 0
    familienstand: str = "ledig"  # ledig, verheiratet, geschieden, verwitwet
    veranlagungsart: str = "einzel"  # einzel, zusammen
    anzahl_kinder: int = 0
    merkmale: list[str] = field(default_factory=list)
    entfernung_km: float | None = None
    arbeitstage: int | None = None
    homeoffice_tage: int | None = None
    grad_der_behinderung: int | None = None
    pflegegrad: int | None = None
    bruttoarbeitslohn: float | None = None
    gesamtbetrag_der_einkuenfte: float | None = None
    # Was der Betrieb herstellt oder anbietet, und welche Berufe im Haushalt
    # ausgeuebt werden. Ohne diese Angabe kann kein Modell erkennen, dass ein
    # Karton Wollgarn Betriebsmaterial ist und keine private Bastelei.
    taetigkeiten: str = ""
    notizen: str = ""

    def hat(self, merkmal: str) -> bool:
        return merkmal in self.merkmale

    def als_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def aus_dict(cls, daten: dict[str, Any]) -> "Profil":
        bekannt = {f for f in cls.__dataclass_fields__}
        gefiltert = {k: v for k, v in (daten or {}).items() if k in bekannt}
        profil = cls(**gefiltert)
        profil.merkmale = [m for m in profil.merkmale if m in MERKMAL_IDS]
        return profil


@dataclass
class Position:
    """Einzelner Betrag innerhalb eines Dokuments, etwa der Lohnanteil einer Rechnung."""

    bezeichnung: str = ""
    betrag: float | None = None
    abzugsfaehig: bool | None = None
    hinweis: str = ""


@dataclass
class Segment:
    """Ein Teildokument innerhalb eines Sammelscans."""

    von_seite: int = 1
    bis_seite: int = 1
    beschreibung: str = ""
    kategorie_id: str = "unklar"


@dataclass
class Analyse:
    """Ergebnis der inhaltlichen Pruefung eines Dokuments."""

    kategorie_id: str = "unklar"
    dokumenttyp: str = ""
    aussteller: str = ""
    datum: str | None = None  # ISO-Datum des Belegs
    steuerjahr: int | None = None
    betrag_gesamt: float | None = None
    betrag_abzugsfaehig: float | None = None
    waehrung: str = "EUR"
    eignung: str = EIGNUNG_UNKLAR
    eignung_begruendung: str = ""
    vertrauen: float = 0.0
    zusammenfassung: str = ""
    hinweise: list[str] = field(default_factory=list)
    fehlende_nachweise: list[str] = field(default_factory=list)
    optimierungshinweise: list[str] = field(default_factory=list)
    positionen: list[Position] = field(default_factory=list)
    enthaelt_mehrere_dokumente: bool = False
    segmente: list[Segment] = field(default_factory=list)
    zahlungsart: str = ""  # unbar, bar, unbekannt
    # Nur bei betrieblichen Belegen gefuellt; steuert die EUeR-Aufstellung.
    geschaeftsvorfall: str = ""  # einnahme, ausgabe, kein_betrieblicher_vorgang
    euer_posten: str = ""  # Posten-Id aus steuer.euer
    modell: str = ""
    # 0 = vor Einfuehrung der Versionierung geprueft.
    version: int = 0
    analysiert_am: str = field(default_factory=_heute)

    @property
    def ist_aktuell(self) -> bool:
        return self.version >= ANALYSE_VERSION

    def als_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def aus_dict(cls, daten: dict[str, Any]) -> "Analyse":
        daten = dict(daten or {})
        positionen = [Position(**p) for p in daten.pop("positionen", []) or []]
        segmente = [Segment(**s) for s in daten.pop("segmente", []) or []]
        bekannt = {f for f in cls.__dataclass_fields__}
        gefiltert = {k: v for k, v in daten.items() if k in bekannt}
        analyse = cls(**gefiltert)
        analyse.positionen = positionen
        analyse.segmente = segmente
        return analyse


@dataclass
class Dokument:
    """Ein eingescanntes Dokument samt Analyseergebnis."""

    id: str
    dateiname: str  # Originalname im Eingangsordner
    sha256: str = ""
    groesse_bytes: int = 0
    seiten: int | None = None
    medientyp: str = ""
    hinzugefuegt_am: str = field(default_factory=_heute)
    status: str = STATUS_NEU
    fehler: str = ""
    analyse: Analyse | None = None
    zieldateiname: str = ""
    zielordner: str = ""
    manuelle_kategorie: str = ""  # setzt die Kategorie der Analyse ausser Kraft
    notiz: str = ""

    @property
    def wirksame_kategorie(self) -> str:
        if self.manuelle_kategorie:
            return self.manuelle_kategorie
        if self.analyse:
            return self.analyse.kategorie_id
        return "unklar"

    def als_dict(self) -> dict[str, Any]:
        daten = asdict(self)
        daten["analyse"] = self.analyse.als_dict() if self.analyse else None
        return daten

    @classmethod
    def aus_dict(cls, daten: dict[str, Any]) -> "Dokument":
        daten = dict(daten)
        analyse = daten.pop("analyse", None)
        bekannt = {f for f in cls.__dataclass_fields__}
        gefiltert = {k: v for k, v in daten.items() if k in bekannt}
        dokument = cls(**gefiltert)
        dokument.analyse = Analyse.aus_dict(analyse) if analyse else None
        return dokument


@dataclass
class Befund:
    """Eine Luecke oder eine Chance aus der Auswertung."""

    art: str  # luecke | chance | warnung
    id: str
    titel: str
    beschreibung: str
    anlage: str = ""
    prioritaet: str = "mittel"  # hoch, mittel, niedrig
    potenzial_eur: float | None = None
    betroffene_dokumente: list[str] = field(default_factory=list)

    def als_dict(self) -> dict[str, Any]:
        return asdict(self)
