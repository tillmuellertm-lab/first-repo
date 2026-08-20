"""Anbindung an die Claude-API fuer Dokumentanalyse, Gesamtauswertung und Rechtsupdate."""

from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import euer, prompts
from .extract import ExtraktionsFehler, inhalt_aufbereiten
from .models import ANALYSE_VERSION, Analyse, Position, Profil, Segment
from .rules import Regelwerk

LOG = logging.getLogger(__name__)

# Modellwahl je Arbeitsschritt. Ueber die Umgebungsvariablen STEUER_MODELL_DOKUMENT,
# STEUER_MODELL_STRATEGIE und STEUER_MODELL_RECHT laesst sich der Standard je Stufe
# umstellen; in der Oberflaeche waehlt der Nutzer vor jedem Lauf einzeln aus.
MODELL_DOKUMENT = os.environ.get("STEUER_MODELL_DOKUMENT", "claude-opus-5")
MODELL_STRATEGIE = os.environ.get("STEUER_MODELL_STRATEGIE", "claude-fable-5")
MODELL_RECHT = os.environ.get("STEUER_MODELL_RECHT", "claude-opus-5")

# Zur Auswahl angebotene Modelle je Arbeitsschritt: (Kennung, Bezeichnung, Erlaeuterung).
# Die Reihenfolge ist die Reihenfolge im Auswahlfeld.
AUSWAHL_DOKUMENT: tuple[tuple[str, str, str], ...] = (
    (
        "claude-sonnet-5",
        "Sonnet 5",
        "Schnell und guenstig. Fuer klar lesbare Standardbelege meist ausreichend.",
    ),
    (
        "claude-opus-5",
        "Opus 5",
        "Gruendlichste Einordnung, spuerbar teurer. Lohnt bei schlechten Scans "
        "und ungewoehnlichen Belegen.",
    ),
)

AUSWAHL_STRATEGIE: tuple[tuple[str, str, str], ...] = (
    (
        "claude-opus-5",
        "Opus 5",
        "Auf anspruchsvolles, mehrstufiges Schlussfolgern ausgelegt.",
    ),
    (
        "claude-fable-5",
        "Fable 5",
        "Alternative aus derselben Modellfamilie. Im Zweifel beide ausprobieren "
        "und die Ergebnisse vergleichen.",
    ),
)


def _pruefen(modell: str | None, auswahl: tuple[tuple[str, str, str], ...], standard: str) -> str:
    """Laesst nur Modelle aus der Auswahlliste zu.

    Die Kennung kommt aus der Weboberflaeche und damit von aussen; ein
    unbekannter Wert wird stillschweigend auf den Standard zurueckgesetzt,
    statt ihn an die API durchzureichen.
    """
    erlaubt = {kennung for kennung, _, _ in auswahl}
    return modell if modell in erlaubt else standard


def modell_dokument_pruefen(modell: str | None) -> str:
    return _pruefen(modell, AUSWAHL_DOKUMENT, MODELL_DOKUMENT)


def modell_strategie_pruefen(modell: str | None) -> str:
    return _pruefen(modell, AUSWAHL_STRATEGIE, MODELL_STRATEGIE)

MAX_VERSUCHE = 4
WEB_SUCHE_WERKZEUG = {"type": "web_search_20250305", "name": "web_search", "max_uses": 12}


class AnalyseFehler(RuntimeError):
    pass


class KeinSchluessel(AnalyseFehler):
    pass


def schluessel_vorhanden() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


@dataclass
class Analysedienst:
    """Duenne Huelle um den Anthropic-Client mit Wiederholungslogik."""

    api_key: str | None = None
    modell_dokument: str = MODELL_DOKUMENT
    modell_strategie: str = MODELL_STRATEGIE
    modell_recht: str = MODELL_RECHT
    _client: Any = None

    def __post_init__(self) -> None:
        self.api_key = self.api_key or os.environ.get("ANTHROPIC_API_KEY")

    @property
    def client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.api_key:
            raise KeinSchluessel(
                "Es ist kein ANTHROPIC_API_KEY gesetzt. Den Schluessel unter "
                "https://console.anthropic.com/settings/keys erzeugen und als Umgebungsvariable "
                "hinterlegen: export ANTHROPIC_API_KEY=sk-ant-..."
            )
        try:
            from anthropic import Anthropic  # noqa: PLC0415
        except ImportError as fehler:  # pragma: no cover
            raise AnalyseFehler(
                "Das Paket 'anthropic' fehlt. Installation: pip install anthropic"
            ) from fehler
        self._client = Anthropic(api_key=self.api_key)
        return self._client

    # -- interne Hilfen ------------------------------------------------------

    def _mit_wiederholung(self, aufruf: Callable[[], Any]) -> Any:
        letzter_fehler: Exception | None = None
        for versuch in range(1, MAX_VERSUCHE + 1):
            try:
                return aufruf()
            except Exception as fehler:  # noqa: BLE001 - SDK-Fehlertypen bewusst breit
                name = type(fehler).__name__
                voruebergehend = name in {
                    "RateLimitError",
                    "APIConnectionError",
                    "APITimeoutError",
                    "InternalServerError",
                    "OverloadedError",
                }
                if not voruebergehend or versuch == MAX_VERSUCHE:
                    raise
                letzter_fehler = fehler
                wartezeit = min(30.0, 2 ** versuch) + random.uniform(0, 1)
                LOG.warning(
                    "API-Aufruf fehlgeschlagen (%s), Versuch %s von %s, warte %.1fs",
                    name, versuch, MAX_VERSUCHE, wartezeit,
                )
                time.sleep(wartezeit)
        raise AnalyseFehler(str(letzter_fehler))

    @staticmethod
    def _werkzeugergebnis(antwort: Any, werkzeugname: str) -> dict[str, Any]:
        for block in getattr(antwort, "content", []) or []:
            if getattr(block, "type", "") == "tool_use" and getattr(block, "name", "") == werkzeugname:
                return dict(getattr(block, "input", {}) or {})
        text = " ".join(
            getattr(b, "text", "") for b in getattr(antwort, "content", []) or []
            if getattr(b, "type", "") == "text"
        ).strip()
        raise AnalyseFehler(
            f"Das Modell hat das Werkzeug '{werkzeugname}' nicht aufgerufen."
            + (f" Antwort: {text[:400]}" if text else "")
        )

    # -- Dokumentanalyse -----------------------------------------------------

    def dokument_analysieren(
        self,
        pfad: Path,
        medientyp: str,
        regelwerk: Regelwerk,
        profil: Profil,
        zusatzhinweis: str = "",
        ab_seite: int | None = None,
        herkunft: str = "",
        stammdaten=None,
    ) -> Analyse:
        inhalt = inhalt_aufbereiten(pfad, medientyp, ab_seite)

        aufforderung = [
            f"Dateiname des Scans: {pfad.name}",
            f"Veranlagungszeitraum der Arbeitsmappe: {regelwerk.jahr}",
        ]
        if inhalt.seiten:
            aufforderung.append(f"Seitenzahl: {inhalt.seiten}")
        for hinweis in inhalt.hinweise:
            aufforderung.append(f"Verarbeitungshinweis: {hinweis}")
        if herkunft:
            # Die Angabe stammt vom Mandanten und ist verlaesslicher als jede
            # Ableitung aus dem Dokument selbst.
            aufforderung.append(
                f"Herkunft des Stapels laut Mandant: {herkunft}. Diese Angabe hat "
                "Vorrang vor deinem Eindruck aus dem Dokument; weiche nur davon ab, "
                "wenn das Dokument ihr eindeutig widerspricht, und sage dann warum."
            )
        if zusatzhinweis:
            aufforderung.append(f"Zusatzinformation des Mandanten: {zusatzhinweis}")
        aufforderung.append(
            "Analysiere dieses Dokument und rufe genau einmal das Werkzeug "
            "'dokument_analyse' auf."
        )

        bloecke = list(inhalt.bloecke) + [{"type": "text", "text": "\n".join(aufforderung)}]

        try:
            antwort = self._mit_wiederholung(
                lambda: self.client.messages.create(
                    model=self.modell_dokument,
                    max_tokens=4096,
                    system=prompts.system_analyse(regelwerk, profil, stammdaten),
                    tools=[prompts.WERKZEUG_ANALYSE],
                    tool_choice={"type": "tool", "name": "dokument_analyse"},
                    messages=[{"role": "user", "content": bloecke}],
                )
            )
        except Exception as fehler:
            # Die haeufigsten API-Fehler in verstaendliche Meldungen uebersetzen,
            # statt den englischen Traceback bis zum Nutzer durchzureichen.
            meldung = str(fehler)
            if "prompt is too long" in meldung:
                raise AnalyseFehler(
                    f"{pfad.name} ist zu umfangreich fuer eine einzelne Analyse. "
                    "Bitte die Datei in kleinere Teile aufteilen, am besten je Beleg "
                    "eine Datei, und erneut hochladen."
                ) from fehler
            if "credit balance is too low" in meldung:
                raise AnalyseFehler(
                    "Das Guthaben des API-Kontos ist aufgebraucht. Unter "
                    "console.anthropic.com/settings/billing aufladen und erneut versuchen."
                ) from fehler
            raise

        rohdaten = self._werkzeugergebnis(antwort, "dokument_analyse")
        analyse = _analyse_aus_rohdaten(rohdaten)
        analyse.modell = self.modell_dokument
        if inhalt.gekuerzt:
            analyse.hinweise.append(
                "Das Dokument wurde fuer die Analyse gekuerzt; die hinteren Seiten wurden nicht geprueft."
            )
        for hinweis in inhalt.hinweise:
            if hinweis not in analyse.hinweise:
                analyse.hinweise.append(hinweis)
        return analyse

    # -- Gesamtauswertung ----------------------------------------------------

    def gesamtauswertung(
        self,
        regelwerk: Regelwerk,
        profil: Profil,
        bestand: list[dict[str, Any]],
        regelbefunde: list[dict[str, Any]],
    ) -> dict[str, Any]:
        bestand, weggelassen = _bestand_begrenzen(bestand)
        vorwort = ""
        if weggelassen:
            vorwort = (
                f"Hinweis: Die Mappe enthaelt {len(bestand) + weggelassen} Dokumente. "
                f"Aufgefuehrt sind die {len(bestand)} steuerlich bedeutsamsten; "
                f"{weggelassen} als nicht steuerrelevant oder nicht verwertbar eingestufte "
                "Belege sind weggelassen. Beziehe dich in der Einschaetzung auf diesen Umstand.\n\n"
            )
        text = (
            vorwort
            + "Dokumentenbestand der Arbeitsmappe:\n"
            + prompts.bestandsuebersicht(bestand)
            + "\n\nBereits regelbasiert erkannte Luecken und Chancen:\n"
            + prompts.bestandsuebersicht(regelbefunde)
            + "\n\nWerte die Mappe aus und rufe genau einmal das Werkzeug 'gesamtauswertung' auf."
        )
        antwort = self._mit_wiederholung(
            lambda: self.client.messages.create(
                model=self.modell_strategie,
                max_tokens=8192,
                system=prompts.system_strategie(regelwerk, profil),
                tools=[prompts.WERKZEUG_STRATEGIE],
                tool_choice={"type": "tool", "name": "gesamtauswertung"},
                messages=[{"role": "user", "content": text}],
            )
        )
        return self._werkzeugergebnis(antwort, "gesamtauswertung")

    # -- Rechtsupdate --------------------------------------------------------

    def rechtsstand_recherchieren(self, jahr: int, bisherige_werte: dict[str, Any]) -> dict[str, Any]:
        text = (
            f"Ermittle den Rechtsstand fuer den Veranlagungszeitraum {jahr}.\n\n"
            "Bisher hinterlegte Werte (Schluessel, Bezeichnung, Wert, Einheit):\n"
            + prompts.bestandsuebersicht(
                [
                    {
                        "schluessel": schluessel,
                        "label": eintrag.get("label"),
                        "wert": eintrag.get("wert"),
                        "einheit": eintrag.get("einheit"),
                    }
                    for schluessel, eintrag in bisherige_werte.items()
                    if isinstance(eintrag, dict)
                ]
            )
            + "\n\nRecherchiere die amtlichen Werte und rufe danach genau einmal das Werkzeug "
            "'rechtsstand' auf."
        )
        antwort = self._mit_wiederholung(
            lambda: self.client.messages.create(
                model=self.modell_recht,
                max_tokens=8192,
                system=prompts.system_rechtsupdate(jahr),
                tools=[WEB_SUCHE_WERKZEUG, prompts.WERKZEUG_RECHTSUPDATE],
                messages=[{"role": "user", "content": text}],
            )
        )
        return self._werkzeugergebnis(antwort, "rechtsstand")


# Hoechstens so viele Dokumente in die Gesamtauswertung geben. Bei sehr grossen
# Mappen sprengt die vollstaendige Liste sonst die Kontextgrenze des Modells.
MAX_BESTAND_GESAMTAUSWERTUNG = 300

# Reihenfolge, in der Dokumente bei Platzmangel behalten werden.
_EIGNUNG_GEWICHT = {"geeignet": 0, "bedingt_geeignet": 1, "unklar": 2, "ungeeignet": 3}


def _bestand_begrenzen(bestand: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Kuerzt sehr grosse Bestaende auf die steuerlich bedeutsamsten Dokumente.

    Behalten werden zuerst die verwertbaren Belege, danach die unklaren; als
    nicht steuerrelevant eingestufte fallen zuerst heraus. Rueckgabe ist die
    gekuerzte Liste und die Zahl der weggelassenen Eintraege.
    """
    if len(bestand) <= MAX_BESTAND_GESAMTAUSWERTUNG:
        return bestand, 0

    def gewicht(eintrag: dict[str, Any]) -> tuple[int, int, float]:
        eignung = str(eintrag.get("eignung", "unklar"))
        nicht_relevant = 1 if eintrag.get("kategorie") == "nicht_steuerrelevant" else 0
        betrag = eintrag.get("betrag_abzugsfaehig") or eintrag.get("betrag_gesamt") or 0
        try:
            betrag = float(betrag)
        except (TypeError, ValueError):
            betrag = 0.0
        # grosse Betraege zuerst, damit die wesentlichen Belege sicher dabei sind
        return (nicht_relevant, _EIGNUNG_GEWICHT.get(eignung, 2), -betrag)

    sortiert = sorted(bestand, key=gewicht)
    behalten = sortiert[:MAX_BESTAND_GESAMTAUSWERTUNG]
    return behalten, len(bestand) - len(behalten)


def _zahl(wert: Any) -> float | None:
    if wert is None or wert == "":
        return None
    try:
        return float(wert)
    except (TypeError, ValueError):
        return None


def _geschaeftsvorfall(wert: Any) -> str:
    text = str(wert or "").strip().lower()
    return text if text in (euer.EINNAHME, euer.AUSGABE, "kein_betrieblicher_vorgang") else ""


def _analyse_aus_rohdaten(rohdaten: dict[str, Any]) -> Analyse:
    """Uebersetzt die Werkzeugausgabe in das interne Modell, tolerant gegen Luecken."""
    from . import taxonomy  # lokal, um Zirkelbezuege zu vermeiden

    kategorie_id = str(rohdaten.get("kategorie_id") or "unklar")
    if kategorie_id not in taxonomy.NACH_ID:
        kategorie_id = "unklar"

    positionen = []
    for eintrag in rohdaten.get("positionen") or []:
        if not isinstance(eintrag, dict):
            continue
        positionen.append(
            Position(
                bezeichnung=str(eintrag.get("bezeichnung", "")),
                betrag=_zahl(eintrag.get("betrag")),
                abzugsfaehig=eintrag.get("abzugsfaehig"),
                hinweis=str(eintrag.get("hinweis", "")),
            )
        )

    segmente = []
    for eintrag in rohdaten.get("segmente") or []:
        if not isinstance(eintrag, dict):
            continue
        segmente.append(
            Segment(
                von_seite=int(eintrag.get("von_seite") or 1),
                bis_seite=int(eintrag.get("bis_seite") or eintrag.get("von_seite") or 1),
                beschreibung=str(eintrag.get("beschreibung", "")),
                kategorie_id=str(eintrag.get("kategorie_id") or "unklar"),
            )
        )

    steuerjahr = rohdaten.get("steuerjahr")
    try:
        steuerjahr = int(steuerjahr) if steuerjahr else None
    except (TypeError, ValueError):
        steuerjahr = None

    vertrauen = _zahl(rohdaten.get("vertrauen")) or 0.0
    vertrauen = min(1.0, max(0.0, vertrauen))

    return Analyse(
        kategorie_id=kategorie_id,
        dokumenttyp=str(rohdaten.get("dokumenttyp", "")).strip(),
        aussteller=str(rohdaten.get("aussteller", "")).strip(),
        datum=(str(rohdaten.get("datum")).strip() or None) if rohdaten.get("datum") else None,
        steuerjahr=steuerjahr,
        betrag_gesamt=_zahl(rohdaten.get("betrag_gesamt")),
        betrag_abzugsfaehig=_zahl(rohdaten.get("betrag_abzugsfaehig")),
        waehrung=str(rohdaten.get("waehrung") or "EUR"),
        eignung=str(rohdaten.get("eignung") or "unklar"),
        eignung_begruendung=str(rohdaten.get("eignung_begruendung", "")).strip(),
        vertrauen=vertrauen,
        zusammenfassung=str(rohdaten.get("zusammenfassung", "")).strip(),
        hinweise=[str(h) for h in rohdaten.get("hinweise") or []],
        fehlende_nachweise=[str(h) for h in rohdaten.get("fehlende_nachweise") or []],
        optimierungshinweise=[str(h) for h in rohdaten.get("optimierungshinweise") or []],
        positionen=positionen,
        enthaelt_mehrere_dokumente=bool(rohdaten.get("enthaelt_mehrere_dokumente")),
        segmente=segmente,
        zahlungsart=str(rohdaten.get("zahlungsart") or "unbekannt"),
        version=ANALYSE_VERSION,
        geschaeftsvorfall=_geschaeftsvorfall(rohdaten.get("geschaeftsvorfall")),
        euer_posten=str(rohdaten.get("euer_posten") or "").strip()
        if str(rohdaten.get("euer_posten") or "").strip() in euer.NACH_ID
        else "",
    )


__all__ = [
    "AUSWAHL_DOKUMENT",
    "AUSWAHL_STRATEGIE",
    "AnalyseFehler",
    "Analysedienst",
    "ExtraktionsFehler",
    "KeinSchluessel",
    "modell_dokument_pruefen",
    "modell_strategie_pruefen",
    "schluessel_vorhanden",
]
