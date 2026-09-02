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

import base64 as _b64
import datetime as _dt
import hashlib as _hashlib
import json
import logging
import time as _zeit
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import gaps, offen as offen_modul, stammdaten as stammdaten_modul, taxonomy
from .extract import inhalt_aufbereiten
from .formatierung import euro
from .models import EIGNUNG_LABEL, Dokument, ist_erstattung, zaehlt_als_aufwand
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
# Belege anderer Jahre stehen nur in Kurzform da, dafuer aber vollstaendig:
# Was nicht in der Liste steht, wird sonst fuer nicht vorhanden gehalten.
MAX_UEBRIGE_ZEILEN = 400
# Eine Antwort muss einen ausformulierten Brief tragen koennen. Bei 4096 Token
# brach das Modell mitten im Werkzeugaufruf ab: der Entwurf kam leer an und die
# angebrochene Antwort hinterliess einen leeren Textblock im Verlauf.
MAX_ANTWORT_TOKEN = 16000
# Vergleiche models.Analyse.betragsart. Nur "aufwand" und "erstattung" bewegen
# eine Summe; die uebrigen Arten bezeichnen Zahlen, die auf einem Beleg stehen,
# ohne Aufwand zu sein - eine Darlehenssumme, ein Kontostand.
BETRAGSARTEN = frozenset(
    {"aufwand", "erstattung", "einnahme", "vertragswert", "saldo"}
)


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
    denktiefe: str = ""
    begonnen_am: str = ""
    # Messwerte des zuletzt abgeschlossenen Zuges. Sie beantworten die Frage,
    # ob eine lange Wartezeit am Modell, an der Mappe oder an der Leitung lag -
    # raten muss man darueber nicht.
    letzter_zug: dict[str, Any] = field(default_factory=dict)

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

    def fuer_api(self, mappe: Arbeitsmappe | None = None) -> list[dict[str, Any]]:
        """Der Verlauf im Format der Messages-API, bei Bedarf vorne gekuerzt.

        Gekuerzt wird nur an einer Stelle, an der keine Antwort von ihrem
        Werkzeugaufruf getrennt wird: eine Nachricht mit ``tool_result`` ohne
        das zugehoerige ``tool_use`` davor weist die API zurueck.

        Bilder liegen als Datei in der Mappe und stehen im Verlauf nur als
        Verweis; erst hier werden sie eingesetzt. Sonst waere die
        Verlaufsdatei nach ein paar Bildschirmfotos unlesbar und um ein
        Vielfaches groesser als das Gespraech selbst.
        """
        gewaehlt = self.nachrichten[-MAX_NACHRICHTEN:]
        while gewaehlt and _enthaelt(gewaehlt[0], "tool_result"):
            gewaehlt = gewaehlt[1:]

        fertig: list[dict[str, Any]] = []
        for nachricht in gewaehlt:
            inhalt = _fuer_api_bloecke(nachricht["inhalt"], mappe)
            if not inhalt:
                # Eine Nachricht ohne Inhalt weist die API zurueck. Uebrig
                # bleibt sie nur, wenn sie ausschliesslich aus leerem Text
                # bestand - dann fehlt nichts, was noch gebraucht wuerde.
                continue
            if fertig and fertig[-1]["role"] == nachricht["rolle"]:
                # Faellt eine Nachricht weg, stossen zwei gleiche Rollen
                # aneinander. Die API verlangt Abwechslung, also zusammenlegen.
                fertig[-1]["content"] = fertig[-1]["content"] + inhalt
                continue
            fertig.append({"role": nachricht["rolle"], "content": inhalt})
        return fertig

    def als_dict(self) -> dict[str, Any]:
        return {
            "version": VERSION,
            "modell": self.modell,
            "denktiefe": self.denktiefe,
            "begonnen_am": self.begonnen_am,
            "letzter_zug": self.letzter_zug,
            "nachrichten": self.nachrichten,
        }

    @classmethod
    def aus_dict(cls, daten: dict[str, Any]) -> "Gespraech":
        daten = daten or {}
        return cls(
            nachrichten=list(daten.get("nachrichten") or []),
            modell=str(daten.get("modell") or ""),
            denktiefe=str(daten.get("denktiefe") or ""),
            begonnen_am=str(daten.get("begonnen_am") or ""),
            letzter_zug=dict(daten.get("letzter_zug") or {}),
        )


def _enthaelt(nachricht: dict[str, Any], blockart: str) -> bool:
    return any(
        isinstance(block, dict) and block.get("type") == blockart
        for block in nachricht.get("inhalt") or []
    )


def pfad(mappe: Arbeitsmappe) -> Path:
    return mappe.zustandsverzeichnis / GESPRAECHSDATEI


# ------------------------------------------------------------- Bilder --------

# Was ein Bildschirmfoto sein kann. PDF gehoert nicht dazu: ein Beleg wird
# hochgeladen und analysiert, nicht ins Gespraech geworfen.
BILDTYPEN = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
MAX_BILDER_JE_NACHRICHT = 5


def bilderordner(mappe: Arbeitsmappe) -> Path:
    return mappe.zustandsverzeichnis / "gespraechsbilder"


def bild_aufnehmen(mappe: Arbeitsmappe, rohdaten: bytes, medientyp: str) -> dict[str, Any]:
    """Legt ein Bild in der Mappe ab und gibt den Verweis fuer den Verlauf.

    Der Dateiname ist die Pruefsumme: dasselbe Bildschirmfoto zweimal
    eingefuegt liegt einmal auf der Platte.
    """
    from .extract import ExtraktionsFehler, bild_verkleinern  # lokal, Zirkelbezug

    if medientyp not in BILDTYPEN:
        raise BeratungsFehler(
            f"'{medientyp}' ist kein unterstuetztes Bildformat. Moeglich sind "
            "PNG, JPEG, GIF und WebP."
        )
    if not rohdaten:
        raise BeratungsFehler("Das Bild ist leer.")
    try:
        daten, medientyp, _ = bild_verkleinern(rohdaten, medientyp)
    except ExtraktionsFehler as fehler:
        raise BeratungsFehler(str(fehler)) from fehler

    ordner = bilderordner(mappe)
    ordner.mkdir(parents=True, exist_ok=True)
    name = _hashlib.sha256(daten).hexdigest()[:16] + BILDTYPEN[medientyp]
    ziel = ordner / name
    if not ziel.exists():
        ziel.write_bytes(daten)
    return {"type": "bild_verweis", "datei": name, "medientyp": medientyp}


def bildpfad(mappe: Arbeitsmappe, name: str) -> Path | None:
    """Loest einen Bildnamen auf, ohne aus dem Ordner herauszufuehren."""
    ordner = bilderordner(mappe).resolve()
    if not ordner.is_dir():
        return None
    ziel = (ordner / name).resolve()
    if ziel.parent != ordner or not ziel.is_file():
        return None
    return ziel


def _fuer_api_bloecke(
    inhalt: list[dict[str, Any]], mappe: Arbeitsmappe | None
) -> list[dict[str, Any]]:
    """Bringt gespeicherte Bloecke in die Form, die die API annimmt.

    Zwei Dinge passieren hier. Bildverweise werden durch die Bilddaten ersetzt.
    Und leere Textbloecke fallen heraus: Die API weist eine Nachricht mit einem
    leeren Textblock ab ("text content blocks must be non-empty"), und weil der
    ganze Verlauf bei jedem Zug erneut mitgeht, macht ein einziger solcher Block
    das Gespraech dauerhaft unbrauchbar. Sie entstehen, wenn eine Antwort an der
    Token-Grenze abgeschnitten wird. Hier greift die Reparatur auch rueckwirkend,
    fuer Verlaeufe, die schon einen solchen Block enthalten.
    """
    ergebnis: list[dict[str, Any]] = []
    for block in inhalt:
        if not isinstance(block, dict):
            continue
        art = block.get("type")
        if art == "text" and not str(block.get("text") or "").strip():
            continue
        if art == "hinweis":
            # Nur fuer die Anzeige gedacht, nicht fuer das Modell.
            continue
        if art != "bild_verweis":
            ergebnis.append(block)
            continue
        datei = bildpfad(mappe, str(block.get("datei") or "")) if mappe else None
        if datei is None:
            # Das Bild ist weg. Ein Hinweis ist ehrlicher als ein stiller
            # Ausfall: sonst antwortet das Modell zu einem Bild, das es nie sah.
            ergebnis.append(
                {"type": "text", "text": "[Ein frueher gezeigtes Bild ist nicht mehr vorhanden.]"}
            )
            continue
        ergebnis.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": str(block.get("medientyp") or "image/png"),
                    "data": _b64.b64encode(datei.read_bytes()).decode("ascii"),
                },
            }
        )
    return ergebnis


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

    rolle: str  # mandant | berater | vorgang | bild
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
        if eingabe.get("ohne_jahreszuordnung"):
            teile.append("ohne Jahreszuordnung")
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
    if name == "betrag_setzen":
        return f"setzt bei Beleg {eingabe.get('dokument_id', '?')} den Betrag {eingabe.get('betrag', '?')}"
    if name == "nicht_ansetzen":
        richtung = "zaehlt wieder mit" if eingabe.get("rueckgaengig") else "bleibt aus den Summen"
        return f"Beleg {eingabe.get('dokument_id', '?')} {richtung}"
    if name == "jahr_setzen":
        anzahl = len(eingabe.get("dokument_ids") or [])
        return f"traegt bei {anzahl} Belegen das Jahr {eingabe.get('jahr', '?')} ein"
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
        verb = "ergaenzt" if eingabe.get("anhaengen") else "schreibt"
        return f"{verb} einen Entwurf: {eingabe.get('titel', 'ohne Titel')}"
    if name == "entwurf_lesen":
        ziel = eingabe.get("name") or "die Liste der Entwuerfe"
        return f"sieht nach: {ziel}"
    if name == "unterlagen_lesen":
        ziel = eingabe.get("name") or "die Liste der Unterlagen"
        return f"liest die Unterlagen des Werkzeugs: {ziel}"
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
            if rolle == "user" and art == "bild_verweis":
                ergebnis.append(Beitrag("bild", str(block.get("datei") or ""), zeit))
            elif rolle == "user" and art == "text":
                ergebnis.append(Beitrag("mandant", str(block.get("text") or ""), zeit))
            elif rolle == "assistant" and art == "text":
                text = str(block.get("text") or "").strip()
                if text:
                    ergebnis.append(Beitrag("berater", text, zeit))
            elif art == "hinweis":
                ergebnis.append(Beitrag("vorgang", str(block.get("text") or ""), zeit))
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
    if dokument.manueller_betrag is not None:
        teile.append(f"Betrag manuell auf {euro(dokument.manueller_betrag)} gesetzt")
    if dokument.fremdwaehrung:
        teile.append(f"Fremdwaehrung {dokument.fremdwaehrung}, zaehlt nicht mit")
    if dokument.nicht_ansetzen:
        teile.append(f"bewusst nicht angesetzt: {dokument.nicht_ansetzen_grund}")
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
    stand = str(daten.get("erstellt_am") or "")
    modell = daten.get("modell")
    kopf = "Gesamtauswertung der Mappe"
    if stand:
        kopf += f" vom {stand}"
    if modell:
        kopf += f" ({modell})"
    zeilen.append(kopf + ":")

    # Eine Gesamtauswertung altert schlecht. Was sie als fehlend meldet, kann
    # laengst in der Mappe liegen; sie weiss nur nichts davon. Das ungeprueft
    # weiterzugeben hiesse, dem Mandanten einen Beleg als fehlend zu nennen,
    # den er selbst hochgeladen hat.
    neuestes = max((d.hinzugefuegt_am for d in mappe.dokumente if d.hinzugefuegt_am), default="")
    if stand and neuestes > stand:
        zeilen.append(
            f"ACHTUNG: Seit dieser Auswertung sind Belege dazugekommen, zuletzt am "
            f"{neuestes}. Was sie als fehlend meldet, kann inzwischen vorliegen. "
            "Pruefe jede solche Aussage mit 'dokumente_suchen' nach, bevor du sie "
            "weitergibst."
        )
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

    # Die uebrigen Belege in Kurzform. Sie gehen in keine Summe ein, liegen aber
    # sehr wohl in der Mappe - und wurden zweimal als fehlend gemeldet, weil sie
    # hier nicht standen: erst eine Lohnsteuerbescheinigung, dann eine ganze
    # Reihe Kontoauszuege. Ein Beleg, den der Mandant hochgeladen hat, darf
    # nicht daran scheitern, dass eine Liste ihn nicht kennt.
    uebrige = sorted(
        ansicht.ohne_jahr + ansicht.fremde,
        key=lambda d: (str(d.gehoert_ins_jahr or "0000"), d.dateiname),
    )
    if uebrige:
        zeilen.append("")
        zeilen.append(
            f"Weitere {len(uebrige)} Belege in derselben Mappe, die nicht zum "
            f"Veranlagungsjahr {mappe.jahr} gehoeren und in keine Summe eingehen. "
            "Sie sind trotzdem da; je Zeile: Kennung | Jahr | Bezeichnung | Dateiname"
        )
        for dokument in uebrige[:MAX_UEBRIGE_ZEILEN]:
            analyse = dokument.analyse
            bezeichnung = ""
            if analyse:
                bezeichnung = " - ".join(t for t in (analyse.dokumenttyp, analyse.aussteller) if t)
            zeilen.append(
                " | ".join(
                    [
                        dokument.id,
                        str(dokument.gehoert_ins_jahr or "ohne Jahr"),
                        bezeichnung or "ohne Bezeichnung",
                        dokument.dateiname,
                    ]
                )
            )
        if len(uebrige) > MAX_UEBRIGE_ZEILEN:
            zeilen.append(
                f"... {len(uebrige) - MAX_UEBRIGE_ZEILEN} weitere, ueber 'dokumente_suchen' erreichbar."
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


# Hoechstens so viele Zeichen aus einer Projektunterlage. README und
# Arbeitsstand sind zusammen rund 45.000 Zeichen; einzeln passen sie bequem.
MAX_UNTERLAGE_ZEICHEN = 80_000


def projektwurzel(mappe: Arbeitsmappe) -> Path | None:
    """Sucht das Verzeichnis des Werkzeugs oberhalb der Arbeitsmappe.

    Die Mappe liegt ueblicherweise im Projektverzeichnis. Gefunden wird es an
    der ``pyproject.toml``; liegt die Mappe woanders, gibt es eben keine
    Unterlagen zu lesen.
    """
    for kandidat in [mappe.wurzel, *mappe.wurzel.parents]:
        if (kandidat / "pyproject.toml").is_file():
            return kandidat
    return None


def projektunterlagen(mappe: Arbeitsmappe) -> list[str]:
    """Die Textdokumente des Werkzeugs selbst, alphabetisch."""
    wurzel = projektwurzel(mappe)
    if wurzel is None:
        return []
    return sorted(p.name for p in wurzel.glob("*.md") if p.is_file())


def projektunterlage_pfad(mappe: Arbeitsmappe, name: str) -> Path | None:
    """Loest einen Unterlagennamen auf, ohne aus dem Projektverzeichnis zu fuehren."""
    wurzel = projektwurzel(mappe)
    if wurzel is None:
        return None
    wurzel = wurzel.resolve()
    ziel = (wurzel / name).resolve()
    if ziel.parent != wurzel or ziel.suffix != ".md" or not ziel.is_file():
        return None
    return ziel


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
                    "ohne_jahreszuordnung": {
                        "type": "boolean",
                        "description": (
                            "Nur Belege, denen kein Jahr zugeordnet ist. Sie gehen in "
                            "keine Summe ein und kommen nicht in die Ablage - deshalb "
                            "sind sie die wichtigste Gruppe zum Durchsehen."
                        ),
                    },
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
                    "anhaengen": {
                        "type": "boolean",
                        "description": (
                            "An einen Entwurf gleichen Titels vom selben Tag anhaengen, "
                            "statt ihn zu ersetzen. So entsteht ein langer Text in "
                            "Teilen, ohne ihn jedes Mal ganz neu zu schreiben."
                        ),
                    },
                },
                "required": ["titel", "text"],
            },
        },
        {
            "name": "unterlagen_lesen",
            "description": (
                "Liest die Textunterlagen des Werkzeugs selbst - Handbuch, Arbeitsstand "
                "und was sonst im Projektverzeichnis liegt. Ohne Namen aufgerufen kommt "
                "die Liste. Immer zuerst hier nachsehen, bevor du ueber das Werkzeug "
                "urteilst: Ein Papier, das dir jemand in den Text kopiert, kann veraltet "
                "sein, und eine Kritik am falschen Stand hilft niemandem."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Dateiname aus der Liste."}},
            },
        },
        {
            "name": "entwurf_lesen",
            "description": (
                "Zeigt einen bereits abgelegten Entwurf wieder an. Ohne Namen "
                "aufgerufen kommt die Liste der vorhandenen. Nuetzlich, bevor du "
                "einen Text fortsetzt oder ersetzt - du siehst sonst nicht, was "
                "schon darin steht."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Dateiname aus der Liste."}},
            },
        },
        {
            "name": "betrag_setzen",
            "description": (
                "Setzt den abzugsfaehigen Betrag eines Belegs. Noetig, wenn sich die "
                "steuerliche Zuordnung erst im Gespraech klaert: Die Analyse kannte den "
                "Verwendungszweck damals nicht und liess das Feld leer, weshalb der "
                "Beleg trotz geklaerter Veranlassung mit 0 EUR in den Summen steht. "
                "Auch der Weg, einen Fremdwaehrungsbetrag in Euro nachzutragen - "
                "massgeblich ist die tatsaechliche Belastung, meist aus der "
                "Kreditkartenabrechnung. Nur setzen, was belegt oder vom Mandanten "
                "bestaetigt ist, und ihm sagen, welcher Betrag jetzt zaehlt."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "dokument_id": {"type": "string"},
                    "betrag": {
                        "type": "number",
                        "description": "Abzugsfaehiger Betrag in Euro.",
                    },
                    "betragsart": {
                        "type": "string",
                        "enum": ["aufwand", "erstattung", "einnahme", "vertragswert", "saldo"],
                        "description": (
                            "Was der Betrag bedeutet. Nur 'aufwand' geht in eine "
                            "Werbungskosten- oder Sonderausgabensumme ein, 'erstattung' "
                            "mindert sie. Traegt der Beleg eine andere Art - etwa "
                            "'saldo' bei einer Bescheinigung -, bleibt auch ein gesetzter "
                            "Betrag ohne Wirkung auf die Summe. Hier angeben, wenn die "
                            "bisherige Art nicht stimmt."
                        ),
                    },
                    "begruendung": {"type": "string"},
                },
                "required": ["dokument_id", "betrag", "begruendung"],
            },
        },
        {
            "name": "nicht_ansetzen",
            "description": (
                "Nimmt einen Beleg aus den Summen, ohne ihn zu loeschen oder als nicht "
                "steuerrelevant auszugeben. Fuer die ueberholte Fassung einer Rechnung, "
                "einen bereits anderweitig erfassten Posten, einen Beleg, den der "
                "Steuerberater nicht ansetzen soll. Der Beleg bleibt in seiner "
                "Kategorie und erscheint im Bericht in einem eigenen Abschnitt mit dem "
                "Grund. Mit rueckgaengig=true wieder aufheben."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "dokument_id": {"type": "string"},
                    "grund": {"type": "string"},
                    "rueckgaengig": {"type": "boolean"},
                },
                "required": ["dokument_id", "grund"],
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
            "name": "jahr_setzen",
            "description": (
                "Traegt das Veranlagungsjahr bei einem oder mehreren Belegen ein. "
                "Ein Beleg ohne Jahr geht in keine Summe ein und kommt nicht in die "
                "Ablage fuer den Steuerberater - er faellt also still unter den Tisch. "
                "Die Angabe hat Vorrang vor dem Datum, das die Analyse gelesen hat, und "
                "ist deshalb genau dann richtig, wenn der Mandant es weiss: eine "
                "Dezemberabrechnung, die im Januar kommt, ein Kontoauszug ohne Datum. "
                "Nur setzen, was der Mandant bestaetigt hat."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "dokument_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Kennungen der Belege, hoechstens 50 auf einmal.",
                    },
                    "jahr": {"type": "integer"},
                    "begruendung": {"type": "string"},
                },
                "required": ["dokument_ids", "jahr", "begruendung"],
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
    if eingabe.get("ohne_jahreszuordnung") and dokument.gehoert_ins_jahr is not None:
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


MAX_JAHR_AUF_EINMAL = 50


def _jahr_setzen(mappe: Arbeitsmappe, eingabe: dict[str, Any]) -> str:
    kennungen = [str(k).strip() for k in (eingabe.get("dokument_ids") or []) if str(k).strip()]
    if not kennungen:
        raise BeratungsFehler("Ohne Kennungen laesst sich kein Jahr setzen.")
    if len(kennungen) > MAX_JAHR_AUF_EINMAL:
        raise BeratungsFehler(
            f"Hoechstens {MAX_JAHR_AUF_EINMAL} Belege auf einmal. Nenne sie einzeln, "
            "damit der Mandant sieht, was sich aendert."
        )
    try:
        jahr = int(eingabe.get("jahr") or 0)
    except (TypeError, ValueError):
        jahr = 0
    if not 1990 <= jahr <= 2100:
        raise BeratungsFehler(f"'{eingabe.get('jahr')}' ist kein plausibles Veranlagungsjahr.")

    # Erst alle Kennungen pruefen, dann aendern. Sonst waere bei einer falschen
    # Kennung die Haelfte umgestellt und die andere nicht - und niemand wuesste,
    # welche Haelfte.
    dokumente = []
    for kennung in kennungen:
        dokument = mappe.dokument(kennung)
        if dokument is None:
            raise BeratungsFehler(
                f"Es gibt keinen Beleg mit der Kennung '{kennung}'. Es wurde nichts "
                "geaendert; pruefe die Kennungen und ruf erneut auf."
            )
        dokumente.append(dokument)

    geaendert: list[str] = []
    unveraendert: list[str] = []
    for dokument in dokumente:
        kennung = dokument.id
        vorher = dokument.gehoert_ins_jahr
        if vorher == jahr:
            unveraendert.append(f"{kennung} ({dokument.dateiname})")
            continue
        dokument.herkunft_jahr = jahr
        geaendert.append(f"{kennung} ({dokument.dateiname}): {vorher or 'ohne Jahr'} -> {jahr}")
    mappe.speichern()

    zeilen = []
    if geaendert:
        zeilen.append(f"{len(geaendert)} Belege auf {jahr} gesetzt:")
        zeilen.extend(f"- {z}" for z in geaendert)
        zeilen.append(
            "Sie gehen ab jetzt in die Summen des Jahres ein und kommen beim Ordnen "
            "in die Ablage. Sag dem Mandanten, was du geaendert hast."
        )
    if unveraendert:
        zeilen.append(f"Unveraendert, weil schon auf {jahr}: " + ", ".join(unveraendert))
    return "\n".join(zeilen)


def _betrag_setzen(mappe: Arbeitsmappe, eingabe: dict[str, Any]) -> str:
    dokument = _dokument_holen(mappe, eingabe)
    try:
        betrag = round(float(eingabe.get("betrag")), 2)
    except (TypeError, ValueError):
        raise BeratungsFehler(f"'{eingabe.get('betrag')}' ist kein Betrag.") from None
    if not str(eingabe.get("begruendung") or "").strip():
        raise BeratungsFehler("Ohne Begruendung wird kein Betrag gesetzt.")

    art = str(eingabe.get("betragsart") or "").strip().lower()
    if art and art not in BETRAGSARTEN:
        raise BeratungsFehler(
            f"'{art}' ist keine Betragsart. Erlaubt: {', '.join(sorted(BETRAGSARTEN))}."
        )

    vorher = dokument.wirksamer_betrag
    fremd = dokument.fremdwaehrung
    dokument.manueller_betrag = betrag
    if art and dokument.analyse:
        dokument.analyse.betragsart = art
    mappe.speichern()

    meldung = f"Beleg {dokument.id}: abzugsfaehiger Betrag jetzt {euro(betrag)}."
    if fremd:
        roh = dokument.analyse.betrag_abzugsfaehig or dokument.analyse.betrag_gesamt
        meldung += f" Er lautete auf {roh} {fremd} und ging bisher in keine Summe ein."
    elif vorher is None:
        meldung += " Bisher stand kein Betrag darin; der Beleg zaehlte mit 0 EUR."
    elif vorher != betrag:
        meldung += f" Die Analyse hatte {euro(vorher)} ermittelt."

    # Der Betrag allein bewegt keine Summe. Ob er zaehlt, entscheidet die
    # Betragsart - und wenn sie es nicht tut, muss das hier stehen und nicht
    # erst auffallen, wenn die Summe unerklaerlich zu niedrig bleibt.
    if zaehlt_als_aufwand(dokument.analyse):
        meldung += " Er geht als Aufwand in die Summen ein."
    elif ist_erstattung(dokument.analyse):
        meldung += " Er mindert als Erstattung die Summe seiner Kategorie."
    else:
        gegenwaertig = (
            dokument.analyse.betragsart if dokument.analyse else ""
        ) or "nicht gesetzt"
        meldung += (
            f" ACHTUNG: Er geht in KEINE Summe ein, weil die Betragsart "
            f"'{gegenwaertig}' lautet. Soll er zaehlen, rufe betrag_setzen noch "
            "einmal mit betragsart='aufwand' auf - und sag dem Mandanten, dass "
            "der Betrag bis dahin nirgends mitgerechnet wird."
        )
    return meldung + " Sag dem Mandanten, was sich dadurch in den Summen aendert."


def _nicht_ansetzen(mappe: Arbeitsmappe, eingabe: dict[str, Any]) -> str:
    dokument = _dokument_holen(mappe, eingabe)
    grund = str(eingabe.get("grund") or "").strip()
    if not grund:
        raise BeratungsFehler(
            "Ohne Grund nicht. Ein Beleg, der ohne Begruendung aus den Summen "
            "verschwindet, ist spaeter nicht mehr nachvollziehbar."
        )
    if eingabe.get("rueckgaengig"):
        dokument.nicht_ansetzen = False
        dokument.nicht_ansetzen_grund = ""
        mappe.speichern()
        return f"Beleg {dokument.id} zaehlt wieder in den Summen mit."

    dokument.nicht_ansetzen = True
    dokument.nicht_ansetzen_grund = grund
    mappe.speichern()
    return (
        f"Beleg {dokument.id} bleibt in der Kategorie {dokument.wirksame_kategorie}, "
        f"geht aber mit 0,00 EUR in die Summen ein. Grund: {grund}. Er erscheint im "
        "Bericht unter 'Bewusst nicht angesetzte Belege'."
    )


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
        raise BeratungsFehler(
            "Titel und Text sind beide noetig. War dein Text sehr lang, wurde er "
            "womoeglich an der Token-Grenze abgeschnitten - schreib ihn kuerzer "
            "oder leg ihn in zwei Teilen ab."
        )
    ordner = mappe.berichte / ENTWURFSORDNER
    ordner.mkdir(parents=True, exist_ok=True)
    name = f"{_dt.date.today().isoformat()}_{sichere_bezeichnung(titel)}.md"
    ziel = ordner / name

    bestand = ziel.read_text(encoding="utf-8") if ziel.is_file() else ""
    if bestand and eingabe.get("anhaengen"):
        # Ein langer Text entsteht in Teilen. Ohne diesen Weg muesste das
        # Modell den ganzen Entwurf jedes Mal neu schreiben - und genau daran
        # ist es an der Token-Grenze schon einmal gescheitert.
        atomar_schreiben(ziel, f"{bestand.rstrip()}\n\n{text}\n")
        meldung = f"An {ziel} angehaengt."
    else:
        atomar_schreiben(ziel, f"# {titel}\n\n{text}\n")
        meldung = f"Gespeichert als {ziel}."
        if bestand:
            # Nicht stillschweigend ueberschreiben: der Mandant koennte den
            # alten Stand noch gebraucht haben.
            meldung += (
                " ACHTUNG: Ein Entwurf mit diesem Titel von heute wurde dabei "
                "ersetzt. Sag das dem Mandanten. Wolltest du fortsetzen statt "
                "ersetzen, ruf erneut mit anhaengen=true auf."
            )
    return (
        f"{meldung} Der Mandant findet den Entwurf auf der Seite 'Beratung' unter "
        "'Entwuerfe' und kann ihn dort oeffnen und kopieren."
    )


def _entwurf_lesen(mappe: Arbeitsmappe, eingabe: dict[str, Any]) -> str:
    """Zeigt einen eigenen Entwurf wieder an - oder listet auf, welche es gibt."""
    name = str(eingabe.get("name") or "").strip()
    if not name:
        vorhanden = entwuerfe(mappe)
        if not vorhanden:
            return "Es liegt noch kein Entwurf vor."
        return "Vorhandene Entwuerfe, neueste zuerst:\n" + "\n".join(f"- {n}" for n in vorhanden)
    datei = entwurf_pfad(mappe, name)
    if datei is None:
        raise BeratungsFehler(
            f"Es gibt keinen Entwurf '{name}'. Ohne Namen aufgerufen bekommst du die Liste."
        )
    return datei.read_text(encoding="utf-8")


def _unterlagen_lesen(mappe: Arbeitsmappe, eingabe: dict[str, Any]) -> str:
    """Gibt eine Unterlage des Werkzeugs aus - oder listet auf, welche es gibt."""
    name = str(eingabe.get("name") or "").strip()
    vorhanden = projektunterlagen(mappe)
    if not vorhanden:
        return (
            "Zu dieser Mappe sind keine Projektunterlagen erreichbar. Sie liegt "
            "offenbar ausserhalb des Werkzeugverzeichnisses."
        )
    if not name:
        return "Unterlagen des Werkzeugs:\n" + "\n".join(f"- {n}" for n in vorhanden)

    datei = projektunterlage_pfad(mappe, name)
    if datei is None:
        raise BeratungsFehler(
            f"Es gibt keine Unterlage '{name}'. Vorhanden sind: {', '.join(vorhanden)}."
        )
    text = datei.read_text(encoding="utf-8")
    if len(text) > MAX_UNTERLAGE_ZEICHEN:
        text = text[:MAX_UNTERLAGE_ZEICHEN] + "\n\n[... gekuerzt, die Unterlage ist laenger]"
    return text


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
    if name == "entwurf_lesen":
        return _entwurf_lesen(mappe, eingabe), []
    if name == "unterlagen_lesen":
        return _unterlagen_lesen(mappe, eingabe), []
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
    if name == "jahr_setzen":
        return _jahr_setzen(mappe, eingabe), []
    if name == "betrag_setzen":
        return _betrag_setzen(mappe, eingabe), []
    if name == "nicht_ansetzen":
        return _nicht_ansetzen(mappe, eingabe), []
    if name == "kategorie_setzen":
        return _kategorie_setzen(mappe, eingabe), []
    raise BeratungsFehler(f"Unbekanntes Werkzeug: {name}")


# ---------------------------------------------------------------- Lauf -------


@dataclass
class _Messung:
    """Zaehlt mit, woran die Wartezeit eines Zuges liegt.

    Eine langsame Antwort hat drei moegliche Ursachen, und sie fuehren zu ganz
    verschiedenen Abhilfen: Das Modell denkt lange nach (Denktiefe senken), es
    schlaegt viele Belege nach (Runden), oder der Bestand geht ungespeichert
    jedes Mal neu mit (Zwischenspeicher greift nicht). Ohne Messung raet man.
    """

    system_zeichen: int = 0
    runden: int = 0
    sekunden: float = 0.0
    eingabe_token: int = 0
    ausgabe_token: int = 0
    zwischenspeicher_token: int = 0

    def runde_buchen(self, dauer: float, antwort: Any) -> None:
        self.runden += 1
        self.sekunden += dauer
        verbrauch = getattr(antwort, "usage", None)
        if verbrauch is None:
            return
        self.eingabe_token += int(getattr(verbrauch, "input_tokens", 0) or 0)
        self.ausgabe_token += int(getattr(verbrauch, "output_tokens", 0) or 0)
        self.zwischenspeicher_token += int(
            getattr(verbrauch, "cache_read_input_tokens", 0) or 0
        )

    def ergebnis(self) -> dict[str, Any]:
        return {
            "zeitpunkt": _dt.datetime.now().isoformat(timespec="seconds"),
            "sekunden": round(self.sekunden, 1),
            "runden": self.runden,
            "system_zeichen": self.system_zeichen,
            "eingabe_token": self.eingabe_token,
            "ausgabe_token": self.ausgabe_token,
            "zwischenspeicher_token": self.zwischenspeicher_token,
        }


def zug_bericht(zug: dict[str, Any]) -> str:
    """Die Messwerte eines Zuges in einem Satz, fuer die Oberflaeche."""
    if not zug:
        return ""
    def tausender(zahl: int) -> str:
        return f"{zahl:,d}".replace(",", ".")

    teile = [f"{float(zug.get('sekunden') or 0):.0f} Sekunden"]
    runden = int(zug.get("runden") or 0)
    if runden > 1:
        teile.append(f"{runden} Runden - das Modell hat zwischendurch nachgeschlagen")
    gelesen = int(zug.get("zwischenspeicher_token") or 0)
    frisch = int(zug.get("eingabe_token") or 0)
    if gelesen:
        teile.append(f"{tausender(gelesen)} Token aus dem Zwischenspeicher")
    elif frisch > 20000:
        teile.append(
            f"{tausender(frisch)} Token neu gelesen - der Zwischenspeicher hat "
            "nicht gegriffen, weil sich die Mappe seit der letzten Frage "
            "geaendert hat"
        )
    return " · ".join(teile)


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
    bilder: list[dict[str, Any]] | None = None,
    denktiefe: str = "",
) -> Gespraech:
    """Stellt eine Frage und laesst das Modell antworten, notfalls ueber Umwege.

    Zwischen Frage und Antwort koennen mehrere Werkzeugrunden liegen: erst
    suchen, dann einen Beleg lesen, dann die Antwort des Mandanten eintragen.
    Nach jeder Runde wird gesichert, damit die Oberflaeche waehrenddessen zeigen
    kann, woran gerade gearbeitet wird.
    """
    from .prompts import system_beratung  # lokal, um Zirkelbezuege zu vermeiden

    frage = frage.strip()
    bilder = list(bilder or [])
    if not frage and not bilder:
        raise BeratungsFehler("Ohne Frage keine Antwort.")
    if len(bilder) > MAX_BILDER_JE_NACHRICHT:
        raise BeratungsFehler(
            f"Hoechstens {MAX_BILDER_JE_NACHRICHT} Bilder je Nachricht."
        )

    gespraech.modell = modell or gespraech.modell
    gespraech.denktiefe = denktiefe or gespraech.denktiefe
    # Das Bild zuerst, die Frage danach: so weiss das Modell beim Lesen des
    # Bildes schon nicht, worauf es achten soll - aber die Frage bezieht sich
    # eindeutig auf das, was darueber steht.
    inhalt = bilder + [{"type": "text", "text": frage or "Bitte sieh dir das an."}]
    gespraech.anhaengen("user", inhalt)
    if sichern:
        sichern(gespraech)

    system = system_beratung(regelwerk, mappe.profil, mappe.stammdaten, lage_text(mappe, regelwerk))
    liste = werkzeuge()
    messung = _Messung(system_zeichen=len(system))

    for runde in range(MAX_RUNDEN):
        letzte_runde = runde == MAX_RUNDEN - 1
        begonnen = _zeit.monotonic()
        antwort = dienst.beratung(
            system=system,
            werkzeuge=[] if letzte_runde else liste,
            nachrichten=gespraech.fuer_api(mappe),
            modell=modell,
            max_tokens=MAX_ANTWORT_TOKEN,
            denktiefe=denktiefe,
        )
        messung.runde_buchen(_zeit.monotonic() - begonnen, antwort)
        bloecke = [_als_dict(block) for block in getattr(antwort, "content", []) or []]
        if getattr(antwort, "stop_reason", "") == "max_tokens":
            # Nicht verschweigen: eine abgeschnittene Antwort sieht sonst aus
            # wie eine vollstaendige, die mitten im Satz endet.
            LOG.warning("Antwort an der Token-Grenze abgeschnitten")
            bloecke.append(
                {
                    "type": "hinweis",
                    "text": "Die Antwort war zu lang und wurde abgeschnitten. "
                    "Bitten Sie um eine kuerzere Fassung oder um einen Teil davon.",
                }
            )
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

    gespraech.letzter_zug = messung.ergebnis()
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
    "zug_bericht",
]
