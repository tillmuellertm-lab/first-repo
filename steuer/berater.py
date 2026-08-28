"""Beratungsgespraech: Dialog mit dem Modell ueber den Bestand der Mappe.

Bisher lief beides nebeneinander her. Der Mandant besprach seine Unterlagen an
einer Stelle, und das Werkzeug analysierte sie an einer anderen. Wer im Chat
eine Auskunft gab, musste sie hinterher von Hand in die Mappe eintragen; wer
das Werkzeug fragte, bekam eine Liste statt einer Antwort. Die Folge war, dass
dieselben Belege mehrfach durchgesprochen wurden und Antworten verloren gingen.

Dieses Modul verbindet die beiden Seiten: Das Modell sieht denselben Bestand,
den auch die Analyse gesehen hat, kann einzelne Belege nachschlagen, den
Originalscan ansehen und die Antworten des Mandanten dort hinterlegen, wo sie
in den Bericht fuer den Steuerberater eingehen. Jeder dieser Zugriffe steht als
eigene Zeile im Verlauf - man soll sehen koennen, worauf eine Auskunft beruht.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import gaps, offen as offen_modul, stammdaten as stammdaten_modul, taxonomy
from .extract import inhalt_aufbereiten
from .formatierung import euro
from .models import EIGNUNG_LABEL, Dokument
from .rules import Regelwerk
from .workspace import Arbeitsmappe, atomar_schreiben, sichere_bezeichnung

LOG = logging.getLogger(__name__)

GESPRAECHSDATEI = "gespraech.json"
# Wohin das Modell Entwuerfe legt: unterhalb der Berichte, damit sie beim
# Packen des Pakets nicht versehentlich mitgehen, aber leicht zu finden sind.
ENTWURFSORDNER = "entwuerfe"
# Was dem Werkzeug im Gebrauch fehlt, gesammelt an einer Stelle.
VERBESSERUNGSDATEI = "verbesserungen.md"
VERSION = 1

# Wie viele Nachrichten des Verlaufs an das Modell gehen. Ein Gespraech ueber
# eine Steuererklaerung wird lang; der vollstaendige Verlauf waere irgendwann
# teurer als er nuetzt. Aeltere Runden fallen weg, der Bestand steht ohnehin im
# Systemprompt und ist damit immer aktuell.
MAX_NACHRICHTEN = 60

# Hoechstzahl der Werkzeugrunden je Frage. Ohne Grenze koennte sich das Modell
# durch die ganze Mappe lesen und dabei erheblich Geld kosten.
MAX_RUNDEN = 8

MAX_TREFFER = 60
MAX_BESTANDSZEILEN = 250
MAX_ANTWORT_TOKEN = 4096


class BeratungsFehler(RuntimeError):
    pass


# --------------------------------------------------------------- Verlauf ----


@dataclass
class Gespraech:
    """Der gespeicherte Gespraechsverlauf einer Arbeitsmappe.

    Gespeichert wird das Rohformat der API samt Werkzeugaufrufen. Nur so laesst
    sich das Gespraech spaeter fortsetzen, ohne dass das Modell vergisst, was es
    bereits nachgeschlagen hat.
    """

    nachrichten: list[dict[str, Any]] = field(default_factory=list)
    modell: str = ""
    begonnen_am: str = ""

    def anhaengen(self, rolle: str, inhalt: list[dict[str, Any]]) -> None:
        if not self.begonnen_am:
            self.begonnen_am = _dt.datetime.now().isoformat(timespec="seconds")
        self.nachrichten.append(
            {
                "rolle": rolle,
                "inhalt": inhalt,
                "zeit": _dt.datetime.now().isoformat(timespec="seconds"),
            }
        )

    def fuer_api(self) -> list[dict[str, Any]]:
        """Der Verlauf im Format der Messages-API, bei Bedarf vorne gekuerzt.

        Gekuerzt wird nur an einer Stelle, an der keine Antwort von ihrem
        Werkzeugaufruf getrennt wird: eine Nachricht mit ``tool_result`` ohne
        das zugehoerige ``tool_use`` davor weist die API zurueck.
        """
        gewaehlt = self.nachrichten[-MAX_NACHRICHTEN:]
        while gewaehlt and _enthaelt(gewaehlt[0], "tool_result"):
            gewaehlt = gewaehlt[1:]
        return [{"role": n["rolle"], "content": n["inhalt"]} for n in gewaehlt]

    def als_dict(self) -> dict[str, Any]:
        return {
            "version": VERSION,
            "modell": self.modell,
            "begonnen_am": self.begonnen_am,
            "nachrichten": self.nachrichten,
        }

    @classmethod
    def aus_dict(cls, daten: dict[str, Any]) -> "Gespraech":
        daten = daten or {}
        return cls(
            nachrichten=list(daten.get("nachrichten") or []),
            modell=str(daten.get("modell") or ""),
            begonnen_am=str(daten.get("begonnen_am") or ""),
        )


def _enthaelt(nachricht: dict[str, Any], blockart: str) -> bool:
    return any(
        isinstance(block, dict) and block.get("type") == blockart
        for block in nachricht.get("inhalt") or []
    )


def pfad(mappe: Arbeitsmappe) -> Path:
    return mappe.zustandsverzeichnis / GESPRAECHSDATEI


def laden(mappe: Arbeitsmappe) -> Gespraech:
    datei = pfad(mappe)
    if not datei.exists():
        return Gespraech()
    try:
        return Gespraech.aus_dict(json.loads(datei.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError) as fehler:
        LOG.warning("Gespraech nicht lesbar (%s), es wird neu begonnen", fehler)
        return Gespraech()


def speichern(mappe: Arbeitsmappe, gespraech: Gespraech) -> None:
    atomar_schreiben(
        pfad(mappe), json.dumps(gespraech.als_dict(), indent=2, ensure_ascii=False)
    )


def loeschen(mappe: Arbeitsmappe) -> bool:
    datei = pfad(mappe)
    if datei.exists():
        datei.unlink()
        return True
    return False


# ------------------------------------------------------------- Anzeige -------


@dataclass
class Beitrag:
    """Eine Zeile des Verlaufs, wie sie in der Oberflaeche steht."""

    rolle: str  # mandant | berater | vorgang
    text: str
    zeit: str = ""

    def als_dict(self) -> dict[str, str]:
        return {"rolle": self.rolle, "text": self.text, "zeit": self.zeit}


def _vorgangstext(name: str, eingabe: dict[str, Any]) -> str:
    """Beschreibt einen Werkzeugaufruf in einem Satz.

    Der Mandant soll sehen, worauf eine Auskunft beruht - eine Antwort, die aus
    dem Nachschlagen von drei Belegen stammt, ist etwas anderes als eine aus dem
    Gedaechtnis.
    """
    if name == "dokumente_suchen":
        teile = [str(eingabe.get(f) or "") for f in ("suchbegriff", "kategorie", "steuerjahr")]
        beschreibung = ", ".join(t for t in teile if t) or "alle Belege"
        return f"durchsucht die Mappe: {beschreibung}"
    if name == "dokument_lesen":
        return f"schlaegt Beleg {eingabe.get('dokument_id', '?')} nach"
    if name == "beleg_ansehen":
        seite = eingabe.get("ab_seite")
        zusatz = f" ab Seite {seite}" if seite else ""
        return f"sieht sich den Originalscan von Beleg {eingabe.get('dokument_id', '?')} an{zusatz}"
    if name == "notiz_speichern":
        return f"traegt Ihre Antwort bei Beleg {eingabe.get('dokument_id', '?')} ein"
    if name == "kategorie_setzen":
        return (
            f"ordnet Beleg {eingabe.get('dokument_id', '?')} neu zu: "
            f"{eingabe.get('kategorie_id', '?')}"
        )
    if name == "kennzahlen_abrufen":
        return "ruft den aktuellen Stand der Mappe ab"
    if name == "offene_punkte":
        return "sieht die offenen Punkte durch"
    if name == "dubletten_finden":
        return "sucht nach doppelt vorliegenden Belegen"
    if name == "rechtsstand_lesen":
        return f"schlaegt den Rechtsstand {eingabe.get('jahr', '?')} nach"
    if name == "stammwert_speichern":
        return f"traegt den Stammwert '{eingabe.get('kennung', '?')}' ein"
    if name == "schreiben_entwerfen":
        return f"schreibt einen Entwurf: {eingabe.get('titel', 'ohne Titel')}"
    if name == "verbesserung_vorschlagen":
        return f"notiert eine Luecke im Werkzeug: {eingabe.get('titel', '')}"
    if name == "web_search":
        return f"sucht im Internet: {eingabe.get('query', '')}"
    return f"ruft {name} auf"


def beitraege(gespraech: Gespraech) -> list[Beitrag]:
    """Uebersetzt den Rohverlauf in das, was auf der Seite steht."""
    ergebnis: list[Beitrag] = []
    for nachricht in gespraech.nachrichten:
        rolle = nachricht.get("rolle")
        zeit = str(nachricht.get("zeit") or "")[11:16]
        for block in nachricht.get("inhalt") or []:
            if not isinstance(block, dict):
                continue
            art = block.get("type")
            if rolle == "user" and art == "text":
                ergebnis.append(Beitrag("mandant", str(block.get("text") or ""), zeit))
            elif rolle == "assistant" and art == "text":
                text = str(block.get("text") or "").strip()
                if text:
                    ergebnis.append(Beitrag("berater", text, zeit))
            elif rolle == "assistant" and art in ("tool_use", "server_tool_use"):
                ergebnis.append(
                    Beitrag(
                        "vorgang",
                        _vorgangstext(str(block.get("name") or ""), block.get("input") or {}),
                        zeit,
                    )
                )
    return ergebnis


# ------------------------------------------------------------ Lagebild -------


def _dokumentzeile(dokument: Dokument) -> str:
    analyse = dokument.analyse
    if analyse is None:
        return f"{dokument.id} | noch nicht analysiert | {dokument.dateiname}"
    bezeichnung = " - ".join(t for t in (analyse.dokumenttyp, analyse.aussteller) if t)
    betrag = euro(analyse.betrag_gesamt) if analyse.betrag_gesamt is not None else "kein Betrag"
    if analyse.betrag_abzugsfaehig is not None and analyse.betrag_abzugsfaehig != analyse.betrag_gesamt:
        betrag += f" (abzugsfaehig {euro(analyse.betrag_abzugsfaehig)})"
    teile = [
        dokument.id,
        analyse.datum or "ohne Datum",
        dokument.wirksame_kategorie,
        bezeichnung or "ohne Bezeichnung",
        betrag,
        EIGNUNG_LABEL.get(analyse.eignung, analyse.eignung),
    ]
    if analyse.betragsart and analyse.betragsart != "aufwand":
        teile.append(f"Betragsart {analyse.betragsart}")
    if analyse.fehlende_nachweise:
        anzahl = len(analyse.fehlende_nachweise)
        teile.append(f"{anzahl} offener Punkt" if anzahl == 1 else f"{anzahl} offene Punkte")
    teile.append(dokument.dateiname)
    zeile = " | ".join(teile)
    if dokument.notiz.strip():
        # Die Notiz ist die Antwort des Mandanten. Sie nur als "vorhanden" zu
        # melden hiesse, dieselbe Frage noch einmal zu stellen.
        zeile += "\n    Auskunft des Mandanten: " + _gekuerzt(dokument.notiz, 300)
    return zeile


def _gekuerzt(text: str, laenge: int) -> str:
    zusammen = " ".join((text or "").split())
    return zusammen if len(zusammen) <= laenge else zusammen[: laenge - 1] + "…"


def kennzahlen_text(mappe: Arbeitsmappe, regelwerk: Regelwerk) -> str:
    """Summen, Zahlen und Befunde der Mappe als Fliesstext fuer das Modell."""
    ansicht = mappe.jahresansicht()
    auswertung = gaps.auswerten(
        ansicht.eigene, regelwerk, mappe.profil, stammdaten=mappe.stammdaten
    )
    zahlen = auswertung.kennzahlen

    zeilen = [
        f"Dokumente im Veranlagungsjahr {mappe.jahr}: {len(ansicht.eigene)}",
        f"davon analysiert: {zahlen.get('anzahl_analysiert', 0)}, "
        f"einreichbar: {zahlen.get('anzahl_geeignet', 0)}, "
        f"bedingt geeignet: {zahlen.get('anzahl_bedingt', 0)}, "
        f"nicht geeignet: {zahlen.get('anzahl_ungeeignet', 0)}",
        f"Dokumente anderer Jahre in derselben Mappe: {len(ansicht.fremde)} "
        f"(Verteilung: {ansicht.fremde_jahre() or 'keine'})",
        f"Dokumente ohne Jahreszuordnung: {len(ansicht.ohne_jahr)}",
        # Ohne diese Zahl wuerde eine Auskunft sicherer klingen, als sie ist:
        # eine mit aelterem Wissensstand erstellte Analyse kann denselben Beleg
        # heute anders einordnen.
        f"Belege, deren Analyse nicht auf dem aktuellen Stand ist "
        f"(nie geprueft, fehlgeschlagen oder mit aelterem Wissensstand): "
        f"{len(mappe.nachzutragen())} von {len(mappe.dokumente)} in der ganzen Mappe",
        "",
        "Summen (nur Belege des Veranlagungsjahres, nur Betragsart 'aufwand'):",
    ]
    for kategorie_id, summe in (zahlen.get("summen_je_kategorie") or {}).items():
        if not summe:
            continue
        zeilen.append(f"- {taxonomy.kategorie(kategorie_id).label}: {euro(summe)}")
    zeilen += [
        f"Werbungskosten gesamt: {euro(zahlen.get('werbungskosten_gesamt'))} "
        f"(Arbeitnehmer-Pauschbetrag {euro(zahlen.get('arbeitnehmer_pauschbetrag'))}, "
        f"Differenz {euro(zahlen.get('werbungskosten_ueber_pauschbetrag'))})",
        f"Haushaltsnahe Aufwendungen: {euro(zahlen.get('haushaltsnahe_aufwendungen_gesamt'))}, "
        f"geschaetzte Ermaessigung {euro(zahlen.get('haushaltsnahe_ermaessigung_geschaetzt'))}",
    ]

    for art, ueberschrift in (
        ("warnung", "Warnungen der regelbasierten Pruefung"),
        ("luecke", "Erkannte Luecken"),
        ("chance", "Erkannte Chancen"),
    ):
        befunde = auswertung.nach_art(art)
        if not befunde:
            continue
        zeilen.append("")
        zeilen.append(f"{ueberschrift} ({len(befunde)}):")
        for befund in befunde[:20]:
            potenzial = f", Potenzial {euro(befund.potenzial_eur)}" if befund.potenzial_eur else ""
            zeilen.append(f"- [{befund.prioritaet}] {befund.titel}{potenzial}: {befund.beschreibung}")
        if len(befunde) > 20:
            zeilen.append(f"- ... {len(befunde) - 20} weitere, ueber 'kennzahlen_abrufen' nicht gekuerzt abrufbar")
    return "\n".join(zeilen)


def gesamtauswertung_text(mappe: Arbeitsmappe) -> str:
    """Die zuletzt erstellte Gesamtauswertung als Text.

    Sie ist der einzige Arbeitsschritt, der die Mappe als Ganzes betrachtet -
    also genau das, was im Gespraech oft gemeint ist, wenn nach "der Analyse"
    gefragt wird. Ohne sie muesste das Gespraech Schluesse noch einmal ziehen,
    fuer die bereits bezahlt wurde.
    """
    daten = mappe.gesamtauswertung()
    if not daten:
        return (
            "Es liegt noch keine Gesamtauswertung vor. Sie entsteht beim Ordnen "
            "mit der Option 'Gesamtauswertung'."
        )

    zeilen = []
    stand = daten.get("erstellt_am")
    modell = daten.get("modell")
    kopf = "Gesamtauswertung der Mappe"
    if stand:
        kopf += f" vom {stand}"
    if modell:
        kopf += f" ({modell})"
    zeilen.append(kopf + ":")
    if daten.get("gesamteinschaetzung"):
        zeilen.append(str(daten["gesamteinschaetzung"]))

    for schluessel, ueberschrift in (
        ("luecken", "Luecken laut Gesamtauswertung"),
        ("chancen", "Chancen laut Gesamtauswertung"),
    ):
        eintraege = [e for e in (daten.get(schluessel) or []) if isinstance(e, dict)]
        if not eintraege:
            continue
        zeilen.append("")
        zeilen.append(f"{ueberschrift} ({len(eintraege)}):")
        for eintrag in eintraege:
            titel = str(eintrag.get("titel") or "")
            beschreibung = str(eintrag.get("beschreibung") or "")
            zusatz = []
            if eintrag.get("prioritaet"):
                zusatz.append(str(eintrag["prioritaet"]))
            if eintrag.get("potenzial_eur"):
                zusatz.append(f"Potenzial {euro(eintrag['potenzial_eur'])}")
            if eintrag.get("rechtsgrundlage"):
                zusatz.append(str(eintrag["rechtsgrundlage"]))
            vorspann = f"[{', '.join(zusatz)}] " if zusatz else ""
            zeilen.append(f"- {vorspann}{titel}: {beschreibung}")
            if eintrag.get("naechster_schritt"):
                zeilen.append(f"  Naechster Schritt: {eintrag['naechster_schritt']}")

    for schluessel, ueberschrift in (
        ("fragen_an_den_mandanten", "Offene Fragen an den Mandanten"),
        ("hinweise_fuer_den_steuerberater", "Hinweise fuer den Steuerberater"),
    ):
        eintraege = [str(e) for e in (daten.get(schluessel) or []) if e]
        if not eintraege:
            continue
        zeilen.append("")
        zeilen.append(f"{ueberschrift}:")
        zeilen.extend(f"- {e}" for e in eintraege)
    return "\n".join(zeilen)


def lage_text(mappe: Arbeitsmappe, regelwerk: Regelwerk) -> str:
    """Das vollstaendige Lagebild fuer den Systemprompt."""
    ansicht = mappe.jahresansicht()
    zeilen = [kennzahlen_text(mappe, regelwerk), "", gesamtauswertung_text(mappe), ""]
    zeilen.append(
        f"Belege des Veranlagungsjahres {mappe.jahr}, je Zeile: Kennung | Datum | "
        "Kategorie | Bezeichnung | Betrag | Eignung | Besonderheiten | Dateiname"
    )
    sortiert = sorted(
        ansicht.eigene,
        key=lambda d: (d.analyse.datum if d.analyse and d.analyse.datum else "9999", d.dateiname),
    )
    for dokument in sortiert[:MAX_BESTANDSZEILEN]:
        zeilen.append(_dokumentzeile(dokument))
    if len(sortiert) > MAX_BESTANDSZEILEN:
        zeilen.append(
            f"... {len(sortiert) - MAX_BESTANDSZEILEN} weitere Belege dieses Jahres. "
            "Sie stehen nicht in dieser Liste, sind aber ueber 'dokumente_suchen' erreichbar."
        )
    if ansicht.fremde or ansicht.ohne_jahr:
        zeilen.append("")
        zeilen.append(
            f"Nicht aufgefuehrt: {len(ansicht.fremde)} Belege anderer Jahre und "
            f"{len(ansicht.ohne_jahr)} ohne Jahreszuordnung. Auch sie liegen in der Mappe "
            "und sind ueber 'dokumente_suchen' erreichbar."
        )
    return "\n".join(zeilen)


# ------------------------------------------------------------ Werkzeuge ------


def entwuerfe(mappe: Arbeitsmappe) -> list[str]:
    """Die im Gespraech entstandenen Entwuerfe, neueste zuerst."""
    ordner = mappe.berichte / ENTWURFSORDNER
    if not ordner.is_dir():
        return []
    return sorted((p.name for p in ordner.glob("*.md") if p.is_file()), reverse=True)


def verbesserungen(mappe: Arbeitsmappe) -> Path | None:
    """Die gesammelten Verbesserungswuensche, falls schon welche notiert wurden."""
    ziel = mappe.berichte / VERBESSERUNGSDATEI
    return ziel if ziel.is_file() else None


def entwurf_pfad(mappe: Arbeitsmappe, name: str) -> Path | None:
    """Loest einen Entwurfsnamen auf, ohne aus dem Ordner herauszufuehren.

    Der Name kommt aus der Adresszeile und damit von aussen; ein Pfad mit ".."
    wuerde sonst beliebige Dateien der Maschine ausliefern.
    """
    ordner = (mappe.berichte / ENTWURFSORDNER).resolve()
    ziel = (ordner / name).resolve()
    if ziel.parent != ordner or ziel.suffix != ".md" or not ziel.is_file():
        return None
    return ziel


def werkzeuge() -> list[dict[str, Any]]:
    """Die Werkzeuge, mit denen das Modell in die Mappe hineinsehen kann.

    Die Websuche fuehrt die API selbst aus; sie taucht deshalb in
    ``werkzeug_ausfuehren`` nicht auf. Sie ist die einzige, die etwas nach
    aussen gibt - was der Systemprompt entsprechend einschraenkt.
    """
    from .analyze import WEB_SUCHE_WERKZEUG  # lokal, um Zirkelbezuege zu vermeiden

    return [
        WEB_SUCHE_WERKZEUG,
        {
            "name": "dokumente_suchen",
            "description": (
                "Durchsucht alle Belege der Mappe, auch die anderer Jahre. Sucht in "
                "Dateiname, Dokumentart, Aussteller, Zusammenfassung, offenen Punkten "
                "und der Notiz des Mandanten. Ohne Angaben werden alle Belege gelistet."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "suchbegriff": {
                        "type": "string",
                        "description": (
                            "Ein oder mehrere Woerter. Mehrere Woerter muessen alle "
                            "vorkommen. Teilwoerter treffen ebenfalls ('zins' findet "
                            "'Zinsbescheinigung')."
                        ),
                    },
                    "kategorie": {"type": "string", "enum": taxonomy.ids()},
                    "steuerjahr": {"type": "integer"},
                    "nur_mit_offenen_punkten": {
                        "type": "boolean",
                        "description": "Nur Belege, bei denen noch Nachweise oder Auskuenfte fehlen.",
                    },
                    "nur_ohne_notiz": {
                        "type": "boolean",
                        "description": "Nur Belege, zu denen der Mandant noch nichts gesagt hat.",
                    },
                },
            },
        },
        {
            "name": "dokument_lesen",
            "description": (
                "Gibt die vollstaendige gespeicherte Analyse eines Belegs zurueck: "
                "Einzelpositionen, Hinweise, fehlende Nachweise, Notiz des Mandanten. "
                "Das ist die Auswertung, nicht der Scan selbst."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"dokument_id": {"type": "string"}},
                "required": ["dokument_id"],
            },
        },
        {
            "name": "beleg_ansehen",
            "description": (
                "Haengt den Originalscan eines Belegs an das Gespraech an, damit du ihn "
                "selbst lesen kannst. Nur verwenden, wenn die gespeicherte Analyse die "
                "Frage nicht beantwortet - das Ansehen kostet spuerbar mehr als "
                "'dokument_lesen'."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "dokument_id": {"type": "string"},
                    "ab_seite": {
                        "type": "integer",
                        "description": "Bei langen PDF: erste Seite des Ausschnitts, 1-basiert.",
                    },
                },
                "required": ["dokument_id"],
            },
        },
        {
            "name": "offene_punkte",
            "description": (
                "Listet die offenen Punkte des Veranlagungsjahres, gebuendelt nach der "
                "Besorgung oder Auskunft, die sie aufloest. Belege mit Notiz gelten als "
                "beantwortet und fehlen hier."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "thema": {
                        "type": "string",
                        "description": "Kennung eines Buendels, etwa 'zahlung' oder 'frage'. Leer = alle.",
                    }
                },
            },
        },
        {
            "name": "kennzahlen_abrufen",
            "description": (
                "Rechnet Summen, Zahlen und die regelbasierten Befunde neu aus. "
                "Nach jeder Aenderung an der Mappe sinnvoll."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "notiz_speichern",
            "description": (
                "Haelt eine Auskunft des Mandanten bei einem Beleg fest. Die Notiz "
                "erscheint im Bericht fuer den Steuerberater direkt unter der Frage, die "
                "sie beantwortet. Immer aufrufen, wenn der Mandant etwas sagt, das zu "
                "einem bestimmten Beleg gehoert - sonst ist die Auskunft nach dem "
                "Gespraech wieder verloren. Formuliere die Notiz so, dass der "
                "Steuerberater sie ohne das Gespraech versteht."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "dokument_id": {"type": "string"},
                    "notiz": {"type": "string"},
                    "ersetzen": {
                        "type": "boolean",
                        "description": (
                            "Standard ist Ergaenzen: die neue Notiz wird an die bestehende "
                            "angehaengt. Nur auf true setzen, wenn die bisherige Notiz "
                            "falsch war."
                        ),
                    },
                },
                "required": ["dokument_id", "notiz"],
            },
        },
        {
            "name": "dubletten_finden",
            "description": (
                "Findet Belege, die zweimal in der Mappe liegen: gleicher Aussteller, "
                "gleiches Datum, gleicher Betrag. Entfernen kann der Mandant sie selbst "
                "auf der Seite 'Dubletten' - nenne ihm, was du gefunden hast."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "rechtsstand_lesen",
            "description": (
                "Liest den hinterlegten Rechtsstand eines beliebigen Veranlagungsjahres: "
                "Pauschalen, Grenzen, Hoechstbetraege, Fristen und die Checkliste der "
                "erwarteten Unterlagen. Fuer Fragen zu Vorjahren und Folgejahren."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"jahr": {"type": "integer"}},
                "required": ["jahr"],
            },
        },
        {
            "name": "stammwert_speichern",
            "description": (
                "Haelt einen jahresuebergreifenden Wert fest, der in keinem einzelnen "
                "Beleg steht und aus den Vorjahren fortgeschrieben wird - Gebaeude-AfA, "
                "Bemessungsgrundlage, Verlustvortrag, Steuernummer, Finanzamt. Diese "
                "Werte gehen in jede kuenftige Analyse ein. Immer eine Fundstelle "
                "angeben, damit nachvollziehbar bleibt, woher der Wert stammt. Nur "
                "speichern, was der Mandant bestaetigt hat oder was du aus einem Beleg "
                "belegen kannst - nie eine Schaetzung."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "kennung": {
                        "type": "string",
                        "description": (
                            "Vorzugsweise eine bekannte Kennung: "
                            + ", ".join(v.id for v in stammdaten_modul.VORLAGEN)
                            + ". Eigene Kennungen sind erlaubt."
                        ),
                    },
                    "wert": {"type": "string"},
                    "quelle": {
                        "type": "string",
                        "description": "Fundstelle, etwa 'Anlage V 2023, Zeile 33' oder 'Angabe des Mandanten'.",
                    },
                    "gilt_ab_jahr": {"type": "integer"},
                    "hinweis": {"type": "string"},
                },
                "required": ["kennung", "wert", "quelle"],
            },
        },
        {
            "name": "schreiben_entwerfen",
            "description": (
                "Legt einen Text als Datei in der Mappe ab, damit der Mandant ihn "
                "verschicken, ausdrucken oder dem Steuerberater beilegen kann - eine "
                "E-Mail an den Steuerberater, ein Anschreiben an den Vermieter, eine "
                "Eigenaufstellung. Der Text wird nicht versendet, sondern nur "
                "gespeichert; der Mandant liest ihn und entscheidet selbst. Schreibe "
                "vollstaendig ausformuliert, nicht in Stichpunkten."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "titel": {"type": "string"},
                    "text": {
                        "type": "string",
                        "description": "Der vollstaendige Text. Markdown ist erlaubt.",
                    },
                },
                "required": ["titel", "text"],
            },
        },
        {
            "name": "verbesserung_vorschlagen",
            "description": (
                "Haelt fest, was diesem Werkzeug fehlt. Stoesst du an eine Grenze - ein "
                "Werkzeug, das du gebraucht haettest und nicht hast; eine Angabe, die du "
                "nicht sehen kannst; eine Aufgabe, die du nur umstaendlich loesen konntest "
                "-, dann schreib es auf, statt es zu uebergehen. Der Mandant entwickelt "
                "das Werkzeug weiter und braucht dafuer den konkreten Anlass, nicht die "
                "Idee allein. Nur echte Reibung aufschreiben, keine Wunschlisten."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "titel": {"type": "string", "description": "Kurz, in einer Zeile."},
                    "anlass": {
                        "type": "string",
                        "description": "Was gerade nicht ging und woran du es gemerkt hast.",
                    },
                    "beschreibung": {
                        "type": "string",
                        "description": "Was helfen wuerde, so konkret wie moeglich.",
                    },
                },
                "required": ["titel", "anlass", "beschreibung"],
            },
        },
        {
            "name": "kategorie_setzen",
            "description": (
                "Ordnet einen Beleg einer anderen Kategorie zu, wenn die Analyse ihn "
                "falsch eingeordnet hat. Die Zuordnung geht in alle Summen ein. Nur bei "
                "einem klaren Fehler verwenden und dem Mandanten sagen, was du geaendert "
                "hast."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "dokument_id": {"type": "string"},
                    "kategorie_id": {"type": "string", "enum": taxonomy.ids()},
                    "begruendung": {"type": "string"},
                },
                "required": ["dokument_id", "kategorie_id", "begruendung"],
            },
        },
    ]


def _passt(dokument: Dokument, eingabe: dict[str, Any]) -> bool:
    analyse = dokument.analyse
    kategorie = str(eingabe.get("kategorie") or "").strip()
    if kategorie and dokument.wirksame_kategorie != kategorie:
        return False
    jahr = eingabe.get("steuerjahr")
    if jahr and dokument.gehoert_ins_jahr != int(jahr):
        return False
    if eingabe.get("nur_mit_offenen_punkten") and not (analyse and analyse.fehlende_nachweise):
        return False
    if eingabe.get("nur_ohne_notiz") and dokument.notiz.strip():
        return False

    begriff = str(eingabe.get("suchbegriff") or "").strip().lower()
    if not begriff:
        return True
    heuhaufen = " ".join(
        [
            dokument.dateiname,
            dokument.zieldateiname,
            dokument.notiz,
            analyse.dokumenttyp if analyse else "",
            analyse.aussteller if analyse else "",
            analyse.zusammenfassung if analyse else "",
            " ".join(analyse.fehlende_nachweise) if analyse else "",
            " ".join(analyse.hinweise) if analyse else "",
        ]
    ).lower()
    # Alle Woerter muessen vorkommen; im Deutschen steckt das gesuchte Wort oft
    # in einer Zusammensetzung, deshalb wird auf Teilwoerter geprueft.
    return all(wort in heuhaufen for wort in begriff.split())


def _suchen(mappe: Arbeitsmappe, eingabe: dict[str, Any]) -> str:
    treffer = [d for d in mappe.dokumente if _passt(d, eingabe)]
    treffer.sort(
        key=lambda d: (d.analyse.datum if d.analyse and d.analyse.datum else "9999", d.dateiname)
    )
    if not treffer:
        return "Kein Beleg passt zu dieser Suche."
    zeilen = [f"{len(treffer)} Treffer:"]
    for dokument in treffer[:MAX_TREFFER]:
        zeilen.append(_dokumentzeile(dokument))
    if len(treffer) > MAX_TREFFER:
        zeilen.append(f"... {len(treffer) - MAX_TREFFER} weitere. Bitte enger suchen.")
    return "\n".join(zeilen)


def _dokument_holen(mappe: Arbeitsmappe, eingabe: dict[str, Any]) -> Dokument:
    kennung = str(eingabe.get("dokument_id") or "").strip()
    dokument = mappe.dokument(kennung)
    if dokument is None:
        raise BeratungsFehler(
            f"Es gibt keinen Beleg mit der Kennung '{kennung}'. "
            "Die Kennungen stehen in der Bestandsliste und in den Suchergebnissen."
        )
    return dokument


def _lesen(mappe: Arbeitsmappe, eingabe: dict[str, Any]) -> str:
    dokument = _dokument_holen(mappe, eingabe)
    daten: dict[str, Any] = {
        "dokument_id": dokument.id,
        "dateiname": dokument.dateiname,
        "seiten": dokument.seiten,
        "herkunft": dokument.herkunft,
        "herkunft_jahr": dokument.herkunft_jahr,
        "status": dokument.status,
        "wirksame_kategorie": dokument.wirksame_kategorie,
        "manuelle_kategorie": dokument.manuelle_kategorie,
        "notiz_des_mandanten": dokument.notiz,
    }
    if dokument.analyse:
        daten["analyse"] = dokument.analyse.als_dict()
    else:
        daten["analyse"] = None
        daten["hinweis"] = "Dieser Beleg ist noch nicht analysiert."
    return json.dumps(daten, ensure_ascii=False, indent=1)


def _ansehen(mappe: Arbeitsmappe, eingabe: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    dokument = _dokument_holen(mappe, eingabe)
    datei = mappe.pfad_zu(dokument)
    if not datei.is_file():
        raise BeratungsFehler(
            f"Die Datei zu Beleg {dokument.id} liegt nicht mehr im Eingang: {dokument.dateiname}"
        )
    ab_seite = eingabe.get("ab_seite")
    inhalt = inhalt_aufbereiten(datei, dokument.medientyp, int(ab_seite) if ab_seite else None)
    hinweis = " ".join(inhalt.hinweise) if inhalt.hinweise else ""
    text = f"Der Scan von '{dokument.dateiname}' haengt an dieser Nachricht."
    if hinweis:
        text += f" Hinweis zur Aufbereitung: {hinweis}"
    anhang = list(inhalt.bloecke) + [
        {"type": "text", "text": f"Das ist der Originalscan zu Beleg {dokument.id}."}
    ]
    return text, anhang


def _offene_punkte(mappe: Arbeitsmappe, eingabe: dict[str, Any]) -> str:
    gesucht = str(eingabe.get("thema") or "").strip().lower()
    buendel: dict[str, list[str]] = {}
    beschriftungen: dict[str, str] = {}
    for dokument in mappe.jahresansicht().eigene:
        analyse = dokument.analyse
        if not analyse or not analyse.fehlende_nachweise or dokument.notiz.strip():
            continue
        for punkt in analyse.fehlende_nachweise:
            kennung, beschriftung = offen_modul.thema(punkt)
            if gesucht and kennung != gesucht:
                continue
            beschriftungen[kennung] = beschriftung
            bezeichnung = (analyse.dokumenttyp or dokument.dateiname)
            if analyse.aussteller:
                bezeichnung += f" ({analyse.aussteller})"
            buendel.setdefault(kennung, []).append(f"{dokument.id} | {bezeichnung}: {punkt}")

    if not buendel:
        return "Zu diesem Thema ist nichts mehr offen."
    zeilen = []
    for kennung, eintraege in sorted(buendel.items(), key=lambda p: -len(p[1])):
        zeilen.append(f"\n{kennung} - {beschriftungen[kennung]} ({len(eintraege)}):")
        for eintrag in eintraege[:25]:
            zeilen.append(f"  {eintrag}")
        if len(eintraege) > 25:
            zeilen.append(f"  ... {len(eintraege) - 25} weitere, ueber thema='{kennung}' vollstaendig")
    return "\n".join(zeilen).strip()


def _notiz_speichern(mappe: Arbeitsmappe, eingabe: dict[str, Any]) -> str:
    dokument = _dokument_holen(mappe, eingabe)
    neu = str(eingabe.get("notiz") or "").strip()
    if not neu:
        raise BeratungsFehler("Eine leere Notiz wird nicht gespeichert.")
    alt = dokument.notiz.strip()
    if alt and not eingabe.get("ersetzen"):
        dokument.notiz = f"{alt}\n{neu}" if neu not in alt else alt
    else:
        dokument.notiz = neu
    mappe.speichern()
    hinweis = ""
    if alt and eingabe.get("ersetzen"):
        hinweis = f" Die bisherige Notiz lautete: {alt}"
    return f"Gespeichert bei {dokument.id}. Die Notiz lautet jetzt: {dokument.notiz}{hinweis}"


def _kategorie_setzen(mappe: Arbeitsmappe, eingabe: dict[str, Any]) -> str:
    dokument = _dokument_holen(mappe, eingabe)
    neu = str(eingabe.get("kategorie_id") or "").strip()
    if neu not in taxonomy.NACH_ID:
        raise BeratungsFehler(f"'{neu}' ist keine gueltige Kategorie.")
    vorher = dokument.wirksame_kategorie
    dokument.manuelle_kategorie = neu
    mappe.speichern()
    return (
        f"Beleg {dokument.id} war {vorher} und ist jetzt {neu}. "
        "Die Aenderung ist als manuelle Zuordnung vermerkt und geht in alle Summen ein."
    )


def _dubletten_finden(mappe: Arbeitsmappe) -> str:
    gruppen = gaps.dubletten_gruppen(mappe.dokumente)
    if not gruppen:
        return "Kein Beleg kommt mit gleichem Aussteller, Datum und Betrag zweimal vor."
    zeilen = [
        f"{len(gruppen)} Gruppen, teuerste zuerst. Entfernen kann der Mandant sie "
        "selbst auf der Seite 'Dubletten':"
    ]
    for gruppe in gruppen:
        zeilen.append("")
        for dokument in gruppe:
            zeilen.append(_dokumentzeile(dokument))
    return "\n".join(zeilen)


def _rechtsstand_lesen(eingabe: dict[str, Any]) -> str:
    from . import rules  # lokal, um Zirkelbezuege zu vermeiden

    try:
        jahr = int(eingabe.get("jahr") or 0)
    except (TypeError, ValueError):
        jahr = 0
    if not jahr:
        raise BeratungsFehler("Ohne Jahresangabe laesst sich kein Rechtsstand lesen.")

    werk = rules.laden(jahr)
    zeilen = [f"Rechtsstand fuer {werk.jahr}, Stand {werk.stand}, Status {werk.status}."]
    if werk.ist_ersatz:
        zeilen.append(
            f"ACHTUNG: Fuer {jahr} ist kein eigener Rechtsstand gepflegt. Die Werte "
            f"stammen aus {werk.quelle_jahr} und koennen veraltet sein. Sage das dem "
            "Mandanten, bevor du dich darauf stuetzt."
        )
    zeilen.append("")
    zeilen.append("Werte:")
    for schluessel, eintrag in (werk.werte or {}).items():
        if not isinstance(eintrag, dict):
            continue
        teile = [f"{eintrag.get('label', schluessel)}: {eintrag.get('wert')} {eintrag.get('einheit', '')}".strip()]
        for feld in ("max_betrag", "max_steuerermaessigung", "rechtsgrundlage"):
            if eintrag.get(feld):
                teile.append(f"{feld}: {eintrag[feld]}")
        zeilen.append("- " + "; ".join(teile))

    if werk.fristen:
        zeilen.append("")
        zeilen.append("Fristen: " + json.dumps(werk.fristen, ensure_ascii=False))
    if werk.checkliste:
        zeilen.append("")
        zeilen.append("Erwartete Unterlagen laut Checkliste dieses Jahres:")
        for eintrag in werk.checkliste:
            erwartet = "; ".join(str(e) for e in (eintrag.get("erwartete_dokumente") or []))
            zeilen.append(f"- {eintrag.get('titel', eintrag.get('id'))}: {erwartet}")
    zeilen.append("")
    zeilen.append(f"Gepflegte Jahre: {rules.verfuegbare_jahre()}")
    return "\n".join(zeilen)


def _stammwert_speichern(mappe: Arbeitsmappe, eingabe: dict[str, Any]) -> str:
    kennung = str(eingabe.get("kennung") or "").strip()
    wert = str(eingabe.get("wert") or "").strip()
    quelle = str(eingabe.get("quelle") or "").strip()
    if not kennung or not wert:
        raise BeratungsFehler("Kennung und Wert sind beide noetig.")
    if not quelle:
        raise BeratungsFehler(
            "Ohne Fundstelle wird kein Stammwert gespeichert. Ein Wert ohne Herkunft "
            "ist im naechsten Jahr nicht mehr nachpruefbar."
        )
    vorher = mappe.stammdaten.eintrag(kennung)
    jahr = eingabe.get("gilt_ab_jahr")
    eintrag = mappe.stammdaten.setzen(
        kennung,
        wert,
        quelle=quelle,
        gilt_ab_jahr=int(jahr) if jahr else mappe.jahr,
        hinweis=str(eingabe.get("hinweis") or ""),
    )
    mappe.stammdaten_speichern()
    meldung = f"Gespeichert: {eintrag.label or kennung} = {wert} (Quelle: {quelle})."
    if vorher and vorher.ist_gesetzt and str(vorher.wert) != wert:
        meldung += f" Der bisherige Wert war {vorher.wert}; sage dem Mandanten, dass du ihn ersetzt hast."
    return meldung


def _entwurf_schreiben(mappe: Arbeitsmappe, eingabe: dict[str, Any]) -> str:
    titel = str(eingabe.get("titel") or "").strip()
    text = str(eingabe.get("text") or "").strip()
    if not titel or not text:
        raise BeratungsFehler("Titel und Text sind beide noetig.")
    ordner = mappe.berichte / ENTWURFSORDNER
    ordner.mkdir(parents=True, exist_ok=True)
    name = f"{_dt.date.today().isoformat()}_{sichere_bezeichnung(titel)}.md"
    ziel = ordner / name
    atomar_schreiben(ziel, f"# {titel}\n\n{text}\n")
    return (
        f"Gespeichert als {ziel}. Der Mandant findet den Entwurf auf der Seite "
        "'Beratung' unter 'Entwuerfe' und kann ihn dort oeffnen und kopieren."
    )


def _verbesserung_vorschlagen(mappe: Arbeitsmappe, eingabe: dict[str, Any]) -> str:
    titel = str(eingabe.get("titel") or "").strip()
    anlass = str(eingabe.get("anlass") or "").strip()
    beschreibung = str(eingabe.get("beschreibung") or "").strip()
    if not (titel and anlass and beschreibung):
        raise BeratungsFehler("Titel, Anlass und Beschreibung sind alle drei noetig.")

    ziel = mappe.berichte / VERBESSERUNGSDATEI
    kopf = (
        "# Was diesem Werkzeug fehlt\n\n"
        "Waehrend der Arbeit aufgefallen, aus der Sicht dessen, der damit arbeiten "
        "muss. Jeder Eintrag nennt den Anlass, nicht nur die Idee.\n"
    )
    bestehend = ziel.read_text(encoding="utf-8") if ziel.is_file() else kopf
    eintrag = (
        f"\n## {_dt.date.today().isoformat()} — {titel}\n\n"
        f"**Anlass:** {anlass}\n\n{beschreibung}\n"
    )
    ziel.parent.mkdir(parents=True, exist_ok=True)
    atomar_schreiben(ziel, bestehend + eintrag)
    return (
        f"Notiert unter {ziel}. Der Mandant sieht die Liste auf der Seite 'Beratung' "
        "und kann sie in die Weiterentwicklung geben."
    )


def werkzeug_ausfuehren(
    name: str, eingabe: dict[str, Any], mappe: Arbeitsmappe, regelwerk: Regelwerk
) -> tuple[str, list[dict[str, Any]]]:
    """Fuehrt einen Werkzeugaufruf aus. Rueckgabe: Ergebnistext und Anhaenge."""
    if name == "verbesserung_vorschlagen":
        return _verbesserung_vorschlagen(mappe, eingabe), []
    if name == "dubletten_finden":
        return _dubletten_finden(mappe), []
    if name == "rechtsstand_lesen":
        return _rechtsstand_lesen(eingabe), []
    if name == "stammwert_speichern":
        return _stammwert_speichern(mappe, eingabe), []
    if name == "schreiben_entwerfen":
        return _entwurf_schreiben(mappe, eingabe), []
    if name == "dokumente_suchen":
        return _suchen(mappe, eingabe), []
    if name == "dokument_lesen":
        return _lesen(mappe, eingabe), []
    if name == "beleg_ansehen":
        return _ansehen(mappe, eingabe)
    if name == "offene_punkte":
        return _offene_punkte(mappe, eingabe), []
    if name == "kennzahlen_abrufen":
        return kennzahlen_text(mappe, regelwerk), []
    if name == "notiz_speichern":
        return _notiz_speichern(mappe, eingabe), []
    if name == "kategorie_setzen":
        return _kategorie_setzen(mappe, eingabe), []
    raise BeratungsFehler(f"Unbekanntes Werkzeug: {name}")


# ---------------------------------------------------------------- Lauf -------


def _als_dict(block: Any) -> dict[str, Any]:
    """Macht aus einem Antwortblock des SDK ein Dict, das sich speichern laesst."""
    if isinstance(block, dict):
        return dict(block)
    if hasattr(block, "model_dump"):
        return block.model_dump(exclude_none=True, mode="json")
    return {"type": getattr(block, "type", "text"), "text": getattr(block, "text", "")}


def nachricht_senden(
    mappe: Arbeitsmappe,
    gespraech: Gespraech,
    frage: str,
    dienst: Any,
    regelwerk: Regelwerk,
    modell: str = "",
    sichern: Callable[[Gespraech], None] | None = None,
) -> Gespraech:
    """Stellt eine Frage und laesst das Modell antworten, notfalls ueber Umwege.

    Zwischen Frage und Antwort koennen mehrere Werkzeugrunden liegen: erst
    suchen, dann einen Beleg lesen, dann die Antwort des Mandanten eintragen.
    Nach jeder Runde wird gesichert, damit die Oberflaeche waehrenddessen zeigen
    kann, woran gerade gearbeitet wird.
    """
    from .prompts import system_beratung  # lokal, um Zirkelbezuege zu vermeiden

    frage = frage.strip()
    if not frage:
        raise BeratungsFehler("Ohne Frage keine Antwort.")

    gespraech.modell = modell or gespraech.modell
    gespraech.anhaengen("user", [{"type": "text", "text": frage}])
    if sichern:
        sichern(gespraech)

    system = system_beratung(regelwerk, mappe.profil, mappe.stammdaten, lage_text(mappe, regelwerk))
    liste = werkzeuge()

    for runde in range(MAX_RUNDEN):
        letzte_runde = runde == MAX_RUNDEN - 1
        antwort = dienst.beratung(
            system=system,
            werkzeuge=[] if letzte_runde else liste,
            nachrichten=gespraech.fuer_api(),
            modell=modell,
        )
        bloecke = [_als_dict(block) for block in getattr(antwort, "content", []) or []]
        gespraech.anhaengen("assistant", bloecke)
        if sichern:
            sichern(gespraech)

        aufrufe = [b for b in bloecke if b.get("type") == "tool_use"]
        if not aufrufe:
            break

        ergebnisse: list[dict[str, Any]] = []
        anhaenge: list[dict[str, Any]] = []
        for aufruf in aufrufe:
            try:
                text, anhang = werkzeug_ausfuehren(
                    str(aufruf.get("name") or ""), aufruf.get("input") or {}, mappe, regelwerk
                )
                fehlgeschlagen = False
            except Exception as fehler:  # noqa: BLE001 - jede Ursache gehoert ins Gespraech
                LOG.warning("Werkzeug %s fehlgeschlagen: %s", aufruf.get("name"), fehler)
                text, anhang, fehlgeschlagen = str(fehler), [], True
            ergebnisse.append(
                {
                    "type": "tool_result",
                    "tool_use_id": aufruf.get("id"),
                    "content": text,
                    "is_error": fehlgeschlagen,
                }
            )
            anhaenge.extend(anhang)
        # Werkzeugergebnisse muessen am Anfang der Nachricht stehen; angehaengte
        # Scans kommen dahinter.
        gespraech.anhaengen("user", ergebnisse + anhaenge)
        if sichern:
            sichern(gespraech)

    if sichern:
        sichern(gespraech)
    return gespraech


__all__ = [
    "Beitrag",
    "BeratungsFehler",
    "Gespraech",
    "beitraege",
    "kennzahlen_text",
    "lage_text",
    "laden",
    "loeschen",
    "nachricht_senden",
    "speichern",
    "werkzeuge",
    "werkzeug_ausfuehren",
]
