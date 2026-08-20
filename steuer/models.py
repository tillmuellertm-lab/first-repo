"""Datenmodell des Steuer-Assistenten.

Alle Objekte sind bewusst als schlanke Dataclasses mit JSON-Serialisierung
ausgelegt: der gesamte Zustand einer Arbeitsmappe liegt als lesbares JSON auf
der Platte, damit jederzeit nachvollziehbar bleibt, was das Werkzeug ueber ein
Dokument gespeichert hat.
"""

from __future__ import annotations

import datetime as _dt
import hashlib as _hashlib
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

# Woher ein Stapel stammt. Diese Angabe macht der Nutzer beim Aufnehmen; sie
# kostet nichts und trennt zuverlaessiger als jede Textanalyse. In einem realen
# Bestand lagen 540 Gewerbebelege und 747 Dokumente fremder Jahre zwischen den
# privaten Unterlagen - alle wurden analysiert und bezahlt, bevor auffiel, dass
# sie nicht hingehoerten.
HERKUENFTE: tuple[tuple[str, str], ...] = (
    ("privat", "Privat - eigene Steuererklaerung"),
    ("gewerbe", "Gewerbe oder Selbstaendigkeit"),
    ("vermietung", "Vermietete Immobilie"),
    ("gemischt", "Gemischt - muss noch getrennt werden"),
)

HERKUNFT_IDS = frozenset(h for h, _ in HERKUENFTE)
HERKUNFT_LABEL = dict(HERKUENFTE)

# Plausible Spannen der Zahlenfelder. Sie fangen Tippfehler und fehlerhaft
# gelesene Eingaben ab, bevor sie in die Berechnungen und in die Prompts geraten:
# eine Entfernung von 600.000 km faellt sonst niemandem auf.
FELDGRENZEN: dict[str, tuple[float, float, str]] = {
    "entfernung_km": (0, 500, "Einfache Entfernung zur Arbeit in km"),
    "arbeitstage": (0, 366, "Arbeitstage im Jahr"),
    "homeoffice_tage": (0, 366, "Homeoffice-Tage im Jahr"),
    "grad_der_behinderung": (0, 100, "Grad der Behinderung"),
    "pflegegrad": (0, 5, "Pflegegrad"),
    "bruttoarbeitslohn": (0, 5_000_000, "Bruttoarbeitslohn"),
    "gesamtbetrag_der_einkuenfte": (-5_000_000, 5_000_000, "Gesamtbetrag der Einkuenfte"),
    "anzahl_kinder": (0, 20, "Anzahl Kinder"),
}


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

    def kontext_pruefsumme(self) -> str:
        """Kennzeichnet den Wissensstand, mit dem ein Dokument geprueft wurde.

        Nur Angaben, die tatsaechlich in den Analyseauftrag einfliessen. Aendert
        sich eine davon, sind die vorhandenen Analysen ueberholt: Derselbe Beleg
        wird anders eingeordnet, wenn bekannt wird, dass im Haushalt ein Betrieb
        gefuehrt wird oder ein Umzug stattfand.
        """
        teile = [
            self.familienstand,
            self.veranlagungsart,
            str(self.anzahl_kinder),
            ",".join(sorted(self.merkmale)),
            str(self.entfernung_km or ""),
            str(self.arbeitstage or ""),
            str(self.homeoffice_tage or ""),
            str(self.grad_der_behinderung or ""),
            str(self.pflegegrad or ""),
            " ".join((self.taetigkeiten or "").split()),
            " ".join((self.notizen or "").split()),
        ]
        roh = "|".join(teile).encode("utf-8")
        return _hashlib.sha256(roh).hexdigest()[:12]

    def unplausible_werte(self) -> list[str]:
        """Meldet Zahlenfelder ausserhalb ihrer plausiblen Spanne."""
        meldungen: list[str] = []
        for feld, (unten, oben, beschriftung) in FELDGRENZEN.items():
            wert = getattr(self, feld, None)
            if wert is None or wert == "":
                continue
            try:
                zahl = float(wert)
            except (TypeError, ValueError):
                meldungen.append(f"{beschriftung}: '{wert}' ist keine Zahl.")
                continue
            if not unten <= zahl <= oben:
                meldungen.append(
                    f"{beschriftung}: {zahl:,.0f}".replace(",", ".")
                    + f" liegt ausserhalb des plausiblen Bereichs ({unten:,.0f} bis {oben:,.0f})."
                    .replace(",", ".")
                )
        return meldungen

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
    # Wissensstand des Profils zur Pruefzeit; siehe Profil.kontext_pruefsumme.
    kontext: str = ""
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
    # Angaben des Nutzers beim Aufnehmen des Stapels, siehe HERKUENFTE.
    herkunft: str = ""
    herkunft_jahr: int | None = None

    @property
    def gehoert_ins_jahr(self) -> int | None:
        """Steuerjahr, soweit bekannt. Die Angabe des Nutzers hat Vorrang.

        Sie stammt aus der Kenntnis des Stapels und ist damit verlaesslicher als
        ein Datum, das aus einem Kassenbon gelesen wurde.
        """
        if self.herkunft_jahr:
            return self.herkunft_jahr
        if self.analyse and self.analyse.steuerjahr:
            return self.analyse.steuerjahr
        return None

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
