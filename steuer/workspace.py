"""Arbeitsmappe: Verzeichnisstruktur und Zustand eines Steuerjahres.

Der gesamte Zustand liegt in zwei JSON-Dateien. Die Originalscans im Ordner
``eingang`` werden niemals veraendert oder geloescht; die aufbereitete Ablage
entsteht immer als Kopie. So bleibt jeder Lauf wiederholbar.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import stammdaten
from .models import Dokument, Profil

VERSION = 1
KONFIGDATEI = "steuer.json"
ZUSTANDSDATEI = "dokumente.json"

ORDNER_EINGANG = "eingang"
ORDNER_AUFBEREITET = "aufbereitet"
ORDNER_BERICHTE = "berichte"
ORDNER_ZUSTAND = ".zustand"

UNTERSTUETZTE_ENDUNGEN = frozenset(
    {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".txt", ".md", ".csv"}
)

MEDIENTYPEN = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".txt": "text/plain",
    ".md": "text/plain",
    ".csv": "text/plain",
}


class ArbeitsmappenFehler(RuntimeError):
    pass


@dataclass
class Jahresansicht:
    """Der Bestand einer Mappe aus Sicht eines Veranlagungsjahres."""

    jahr: int
    eigene: list[Dokument] = field(default_factory=list)
    fremde: list[Dokument] = field(default_factory=list)
    ohne_jahr: list[Dokument] = field(default_factory=list)

    @property
    def anzahl_gesamt(self) -> int:
        return len(self.eigene) + len(self.fremde) + len(self.ohne_jahr)

    def fremde_jahre(self) -> dict[int, int]:
        verteilung: dict[int, int] = {}
        for dokument in self.fremde:
            jahr = dokument.gehoert_ins_jahr
            if jahr:
                verteilung[jahr] = verteilung.get(jahr, 0) + 1
        return dict(sorted(verteilung.items()))


def sichere_bezeichnung(text: str, maxlaenge: int = 60) -> str:
    """Macht aus beliebigem Text einen dateisystemtauglichen Bestandteil."""
    # Erst die Umlaute ersetzen, dann zerlegen: nach NFKD steht das Trema als
    # eigenes Zeichen und "ü" waere nicht mehr als solches zu finden.
    text = unicodedata.normalize("NFC", text or "")
    ersetzungen = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}
    for quelle, ziel in ersetzungen.items():
        text = text.replace(quelle, ziel)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")
    text = re.sub(r"-{2,}", "-", text)
    return text[:maxlaenge].strip("-")


def sha256_datei(pfad: Path) -> str:
    hasher = hashlib.sha256()
    with pfad.open("rb") as datei:
        for block in iter(lambda: datei.read(1024 * 256), b""):
            hasher.update(block)
    return hasher.hexdigest()


@dataclass
class Arbeitsmappe:
    wurzel: Path
    jahr: int
    profil: Profil = field(default_factory=Profil)
    dokumente: list[Dokument] = field(default_factory=list)
    einstellungen: dict[str, Any] = field(default_factory=dict)
    # Traege geladen, damit eine Mappe ohne Stammdaten nichts kostet.
    _stammdaten: Any = field(default=None, repr=False, compare=False)

    # -- Pfade ---------------------------------------------------------------

    @property
    def eingang(self) -> Path:
        return self.wurzel / ORDNER_EINGANG

    @property
    def aufbereitet(self) -> Path:
        return self.wurzel / ORDNER_AUFBEREITET

    @property
    def berichte(self) -> Path:
        return self.wurzel / ORDNER_BERICHTE

    @property
    def zustandsverzeichnis(self) -> Path:
        return self.wurzel / ORDNER_ZUSTAND

    @property
    def stammdaten_pfad(self) -> Path:
        """Ort der jahresuebergreifenden Werte.

        Standard ist die Mappe selbst. Wer mehrere Jahre nebeneinander pflegt,
        kann in ``steuer.json`` unter ``einstellungen.stammdaten`` einen
        gemeinsamen Pfad hinterlegen - dann teilen sich alle Jahre eine Datei.
        """
        eigener = self.einstellungen.get("stammdaten")
        if eigener:
            return Path(eigener).expanduser()
        return self.wurzel / stammdaten.DATEINAME

    @property
    def stammdaten(self) -> stammdaten.Stammdaten:
        if self._stammdaten is None:
            self._stammdaten = stammdaten.laden(self.stammdaten_pfad)
        return self._stammdaten

    def stammdaten_speichern(self) -> Path:
        return stammdaten.speichern(self.stammdaten, self.stammdaten_pfad)

    def pfad_zu(self, dokument: Dokument) -> Path:
        return self.eingang / dokument.dateiname

    # -- Anlegen und Laden ---------------------------------------------------

    @classmethod
    def anlegen(cls, wurzel: Path, jahr: int, profil: Profil | None = None) -> "Arbeitsmappe":
        wurzel = Path(wurzel).expanduser().resolve()
        mappe = cls(wurzel=wurzel, jahr=jahr, profil=profil or Profil(veranlagungsjahr=jahr))
        mappe.profil.veranlagungsjahr = jahr
        for ordner in (mappe.eingang, mappe.aufbereitet, mappe.berichte, mappe.zustandsverzeichnis):
            ordner.mkdir(parents=True, exist_ok=True)
        mappe.speichern()
        return mappe

    @classmethod
    def laden(cls, wurzel: Path) -> "Arbeitsmappe":
        wurzel = Path(wurzel).expanduser().resolve()
        konfig_pfad = wurzel / KONFIGDATEI
        if not konfig_pfad.exists():
            raise ArbeitsmappenFehler(
                f"In {wurzel} liegt keine Arbeitsmappe. Mit 'steuer init --jahr <Jahr>' anlegen."
            )
        konfig = json.loads(konfig_pfad.read_text(encoding="utf-8"))
        mappe = cls(
            wurzel=wurzel,
            jahr=int(konfig.get("jahr", 0)),
            profil=Profil.aus_dict(konfig.get("profil", {})),
            einstellungen=konfig.get("einstellungen", {}),
        )
        zustand_pfad = mappe.zustandsverzeichnis / ZUSTANDSDATEI
        if zustand_pfad.exists():
            roh = json.loads(zustand_pfad.read_text(encoding="utf-8"))
            mappe.dokumente = [Dokument.aus_dict(d) for d in roh.get("dokumente", [])]
        for ordner in (mappe.eingang, mappe.aufbereitet, mappe.berichte, mappe.zustandsverzeichnis):
            ordner.mkdir(parents=True, exist_ok=True)
        return mappe

    @classmethod
    def finden(cls, start: Path | None = None) -> "Arbeitsmappe":
        """Sucht ab ``start`` aufwaerts nach einer Arbeitsmappe."""
        aktuell = Path(start or Path.cwd()).expanduser().resolve()
        for kandidat in [aktuell, *aktuell.parents]:
            if (kandidat / KONFIGDATEI).exists():
                return cls.laden(kandidat)
        raise ArbeitsmappenFehler(
            "Keine Arbeitsmappe gefunden. Mit 'steuer init --jahr <Jahr>' eine anlegen "
            "oder mit '--mappe <Pfad>' den Ort angeben."
        )

    def speichern(self) -> None:
        self.zustandsverzeichnis.mkdir(parents=True, exist_ok=True)
        konfig = {
            "version": VERSION,
            "jahr": self.jahr,
            "profil": self.profil.als_dict(),
            "einstellungen": self.einstellungen,
        }
        atomar_schreiben(self.wurzel / KONFIGDATEI, json.dumps(konfig, indent=2, ensure_ascii=False))
        zustand = {"version": VERSION, "dokumente": [d.als_dict() for d in self.dokumente]}
        atomar_schreiben(
            self.zustandsverzeichnis / ZUSTANDSDATEI,
            json.dumps(zustand, indent=2, ensure_ascii=False),
        )

    # -- Dokumente -----------------------------------------------------------

    def dokument(self, dokument_id: str) -> Dokument | None:
        for dokument in self.dokumente:
            if dokument.id == dokument_id:
                return dokument
        return None

    def datei_aufnehmen(
        self,
        quelle: Path,
        originalname: str | None = None,
        herkunft: str = "",
        herkunft_jahr: int | None = None,
    ) -> tuple[Dokument, bool]:
        """Kopiert eine Datei in den Eingang.

        Rueckgabe ist das Dokument und ob es neu ist. Dubletten werden anhand
        des SHA-256 erkannt und nicht erneut aufgenommen. ``herkunft`` und
        ``herkunft_jahr`` gelten fuer den ganzen Stapel und stammen vom Nutzer.
        """
        quelle = Path(quelle)
        if not quelle.is_file():
            raise ArbeitsmappenFehler(f"Datei nicht gefunden: {quelle}")
        name = originalname or quelle.name
        endung = Path(name).suffix.lower()
        if endung not in UNTERSTUETZTE_ENDUNGEN:
            raise ArbeitsmappenFehler(
                f"Dateityp {endung or '(ohne Endung)'} wird nicht unterstuetzt: {name}"
            )
        pruefsumme = sha256_datei(quelle)
        for vorhanden in self.dokumente:
            if vorhanden.sha256 == pruefsumme:
                # Dublette: die Datei nicht erneut aufnehmen, aber eine bisher
                # fehlende Herkunftsangabe nachtragen.
                if herkunft and not vorhanden.herkunft:
                    vorhanden.herkunft = herkunft
                if herkunft_jahr and not vorhanden.herkunft_jahr:
                    vorhanden.herkunft_jahr = herkunft_jahr
                return vorhanden, False

        self.eingang.mkdir(parents=True, exist_ok=True)
        zielname = _freier_name(self.eingang, name)
        ziel = self.eingang / zielname
        shutil.copy2(quelle, ziel)

        dokument = Dokument(
            id=pruefsumme[:12],
            dateiname=zielname,
            sha256=pruefsumme,
            groesse_bytes=ziel.stat().st_size,
            medientyp=MEDIENTYPEN.get(endung, "application/octet-stream"),
            herkunft=herkunft,
            herkunft_jahr=herkunft_jahr,
        )
        self.dokumente.append(dokument)
        return dokument, True

    def eingang_einlesen(self) -> list[Dokument]:
        """Nimmt Dateien auf, die direkt in den Eingangsordner gelegt wurden."""
        bekannt = {d.dateiname for d in self.dokumente}
        neue: list[Dokument] = []
        for pfad in sorted(self.eingang.iterdir()):
            if not pfad.is_file() or pfad.name.startswith("."):
                continue
            if pfad.name in bekannt:
                continue
            if pfad.suffix.lower() not in UNTERSTUETZTE_ENDUNGEN:
                continue
            pruefsumme = sha256_datei(pfad)
            if any(d.sha256 == pruefsumme for d in self.dokumente):
                continue
            dokument = Dokument(
                id=pruefsumme[:12],
                dateiname=pfad.name,
                sha256=pruefsumme,
                groesse_bytes=pfad.stat().st_size,
                medientyp=MEDIENTYPEN.get(pfad.suffix.lower(), "application/octet-stream"),
            )
            self.dokumente.append(dokument)
            neue.append(dokument)
        return neue

    def dokument_uebernehmen(self, dokument: Dokument, quelldatei: Path) -> bool:
        """Nimmt ein bereits analysiertes Dokument aus einer anderen Mappe auf.

        Die Analyse bleibt erhalten, es wird also nicht erneut geprueft.
        Rueckgabe ist False, wenn dasselbe Dokument hier schon liegt.
        """
        if any(d.sha256 == dokument.sha256 for d in self.dokumente):
            return False
        self.eingang.mkdir(parents=True, exist_ok=True)
        zielname = _freier_name(self.eingang, dokument.dateiname)
        shutil.copy2(quelldatei, self.eingang / zielname)

        uebernommen = Dokument.aus_dict(dokument.als_dict())
        uebernommen.dateiname = zielname
        # Die Ablage wird in der neuen Mappe frisch aufgebaut.
        uebernommen.zieldateiname = ""
        uebernommen.zielordner = ""
        self.dokumente.append(uebernommen)
        return True

    def dokument_entfernen(self, dokument_id: str, datei_loeschen: bool = False) -> bool:
        dokument = self.dokument(dokument_id)
        if dokument is None:
            return False
        self.dokumente = [d for d in self.dokumente if d.id != dokument_id]
        if datei_loeschen:
            pfad = self.pfad_zu(dokument)
            if pfad.exists():
                pfad.unlink()
        return True

    def jahresansicht(self, jahr: int | None = None) -> "Jahresansicht":
        """Teilt den Bestand nach Zugehoerigkeit zum Veranlagungsjahr auf.

        Ein Eingang, mehrere Jahre: Dokumente wandern nicht zwischen Mappen,
        sie gehoeren einfach zu einem anderen Jahr. Was keinem Jahr zugeordnet
        ist, bleibt sichtbar, geht aber in keine Summe ein - Raten waere hier
        besonders teuer, weil ein falsches Jahr den Abzug ganz kosten kann.
        """
        jahr = jahr or self.jahr
        eigene: list[Dokument] = []
        fremde: list[Dokument] = []
        ohne: list[Dokument] = []
        for dokument in self.dokumente:
            zugehoerig = dokument.gehoert_ins_jahr
            if zugehoerig is None:
                ohne.append(dokument)
            elif zugehoerig == jahr:
                eigene.append(dokument)
            else:
                fremde.append(dokument)
        return Jahresansicht(jahr=jahr, eigene=eigene, fremde=fremde, ohne_jahr=ohne)

    def jahresverteilung(self) -> dict[str, int]:
        """Wie viele Dokumente auf welches Jahr entfallen."""
        verteilung: dict[str, int] = {}
        for dokument in self.dokumente:
            kennung = str(dokument.gehoert_ins_jahr or "ohne Jahresangabe")
            verteilung[kennung] = verteilung.get(kennung, 0) + 1
        return verteilung

    def uebernehmen_aus(self, quelle: "Arbeitsmappe") -> tuple[int, int]:
        """Fuehrt eine andere Mappe in diese ein, ohne Analysen zu verlieren.

        Rueckgabe: uebernommen, uebersprungen. Die Gegenrichtung zu
        ``ausgliedern`` - wer den Bestand versehentlich zerteilt hat, kann ihn
        wieder zusammenfuehren.
        """
        uebernommen = uebersprungen = 0
        for dokument in quelle.dokumente:
            quelldatei = quelle.pfad_zu(dokument)
            if not quelldatei.exists():
                uebersprungen += 1
                continue
            if self.dokument_uebernehmen(dokument, quelldatei):
                uebernommen += 1
            else:
                uebersprungen += 1
        return uebernommen, uebersprungen

    def offene_dokumente(self) -> list[Dokument]:
        return [d for d in self.dokumente if d.analyse is None or d.status != "analysiert"]

    def kontext_pruefsumme(self) -> str:
        """Wissensstand aus Profil und Stammdaten zusammen."""
        return f"{self.profil.kontext_pruefsumme()}-{self.stammdaten.pruefsumme()}"

    def nachzutragen(self) -> list[Dokument]:
        """Dokumente, deren Analyse nicht mehr zum aktuellen Stand passt.

        Drei Gruende: noch nie geprueft, beim letzten Versuch fehlgeschlagen,
        oder mit einem aelteren Wissensstand geprueft - sei es eine aeltere
        Fassung der Analysefelder oder ein Profil, das den Betrieb im Haushalt
        noch nicht kannte. Derselbe Beleg wird dann heute anders eingeordnet.
        """
        kontext = self.kontext_pruefsumme()
        return [
            d
            for d in self.dokumente
            if d.analyse is None
            or d.status == "fehler"
            or not d.analyse.ist_aktuell
            or d.analyse.kontext != kontext
        ]


def _freier_name(ordner: Path, wunschname: str) -> str:
    ziel = ordner / wunschname
    if not ziel.exists():
        return wunschname
    stamm, endung = Path(wunschname).stem, Path(wunschname).suffix
    zaehler = 2
    while (ordner / f"{stamm}-{zaehler}{endung}").exists():
        zaehler += 1
    return f"{stamm}-{zaehler}{endung}"


def atomar_schreiben(pfad: Path, inhalt: str) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    temp = pfad.with_suffix(pfad.suffix + ".tmp")
    temp.write_text(inhalt, encoding="utf-8")
    temp.replace(pfad)


def dateien_sammeln(pfade: Iterable[Path]) -> list[Path]:
    """Loest Ordner rekursiv in unterstuetzte Einzeldateien auf."""
    gefunden: list[Path] = []
    for eintrag in pfade:
        eintrag = Path(eintrag).expanduser()
        if eintrag.is_dir():
            for kandidat in sorted(eintrag.rglob("*")):
                if kandidat.is_file() and kandidat.suffix.lower() in UNTERSTUETZTE_ENDUNGEN:
                    gefunden.append(kandidat)
        elif eintrag.is_file():
            gefunden.append(eintrag)
    return gefunden
