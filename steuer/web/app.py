"""Lokale Weboberflaeche.

Bewusst nur an 127.0.0.1 gebunden: die Arbeitsmappe enthaelt hochsensible Daten
und hat im Netz nichts verloren. Laufende Analysen werden in einem
Hintergrundthread ausgefuehrt, damit die Oberflaeche waehrenddessen bedienbar
bleibt.
"""

from __future__ import annotations

import base64 as _b64
import binascii
import datetime as _dt
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .. import (
    berater,
    formular as formular_modul,
    gaps,
    offen as offen_modul,
    organize,
    report,
    rules,
    stammdaten as stammdaten_modul,
    taxonomy,
)
from ..formatierung import eingabewert, euro, zahl_lesen
from ..analyze import (
    AUSWAHL_BERATUNG,
    AUSWAHL_DENKTIEFE,
    AUSWAHL_DOKUMENT,
    AUSWAHL_STRATEGIE,
    Analysedienst,
    denktiefe_pruefen,
    modell_beratung_pruefen,
    modell_dokument_pruefen,
    modell_strategie_pruefen,
    schluessel_vorhanden,
)
from ..models import (
    EIGNUNG_BEDINGT,
    EIGNUNG_GEEIGNET,
    EIGNUNG_LABEL,
    EIGNUNG_UNGEEIGNET,
    HERKUENFTE,
    HERKUNFT_IDS,
    HERKUNFT_LABEL,
    MERKMALE,
    STATUS_ANALYSIERT,
    STATUS_FEHLER,
    Profil,
)
from ..workspace import Arbeitsmappe, ArbeitsmappenFehler

LOG = logging.getLogger(__name__)


@dataclass
class Auftrag:
    """Zustand eines laufenden Hintergrundlaufs."""

    art: str = ""
    laeuft: bool = False
    gesamt: int = 0
    erledigt: int = 0
    aktuell: str = ""
    meldungen: list[str] = field(default_factory=list)
    fehler: str = ""
    fertig_um: str = ""

    def als_dict(self) -> dict[str, Any]:
        return {
            "art": self.art,
            "laeuft": self.laeuft,
            "gesamt": self.gesamt,
            "erledigt": self.erledigt,
            "aktuell": self.aktuell,
            "meldungen": self.meldungen[-40:],
            "fehler": self.fehler,
            "fertig_um": self.fertig_um,
        }


@dataclass
class Beratungslauf:
    """Zustand des laufenden Gespraechszugs.

    Der Verlauf selbst liegt in der Mappe; hier steht nur, ob gerade eine
    Antwort erarbeitet wird. Ein Zug kann eine Minute dauern, wenn das Modell
    mehrere Belege nachschlaegt - solange muss die Seite zeigen koennen, dass
    etwas passiert.
    """

    laeuft: bool = False
    fehler: str = ""
    begonnen_um: str = ""


def anwendung_bauen(mappe: Arbeitsmappe) -> Any:
    try:
        from flask import (  # noqa: PLC0415
            Flask,
            abort,
            jsonify,
            redirect,
            render_template,
            request,
            send_file,
            url_for,
        )
    except ImportError as fehler:  # pragma: no cover
        raise ArbeitsmappenFehler(
            "Fuer die Weboberflaeche wird Flask benoetigt: pip install flask"
        ) from fehler

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 256 * 1024 * 1024
    # Formularfelder muessen so gefuellt werden, dass ein erneutes Speichern
    # denselben Wert ergibt. Die Python-Darstellung "6.0" tut das nicht.
    app.jinja_env.filters["eingabewert"] = eingabewert
    sperre = threading.Lock()
    auftrag = Auftrag()
    beratungslauf = Beratungslauf()

    def regelwerk() -> rules.Regelwerk:
        return rules.laden(mappe.jahr)

    def auswertung() -> gaps.Auswertung:
        return gaps.auswerten(mappe.jahresansicht().eigene, regelwerk(), mappe.profil, stammdaten=mappe.stammdaten)

    def grunddaten() -> dict[str, Any]:
        werk = regelwerk()
        return {
            "mappe": mappe,
            "jahr": mappe.jahr,
            "profil": mappe.profil,
            "regelwerk": werk,
            "taxonomy": taxonomy,
            "eignung_label": EIGNUNG_LABEL,
            "schluessel_vorhanden": schluessel_vorhanden(),
            "auftrag_laeuft": auftrag.laeuft,
            "auswahl_dokument": AUSWAHL_DOKUMENT,
            "auswahl_strategie": AUSWAHL_STRATEGIE,
            "herkuenfte": HERKUENFTE,
            # zuletzt getroffene Wahl, damit das Auswahlfeld sie wieder anzeigt
            "modell_dokument": modell_dokument_pruefen(mappe.einstellungen.get("modell_dokument")),
            "modell_strategie": modell_strategie_pruefen(mappe.einstellungen.get("modell_strategie")),
            # Dokumente, deren Analyse einen aelteren Wissensstand hat.
            "nachzutragen": len(mappe.nachzutragen()),
            "jahresansicht": mappe.jahresansicht(),
        }

    # ----------------------------------------------------------- Ansichten --

    @app.get("/")
    def uebersicht():
        werk = regelwerk()
        ergebnis = gaps.auswerten(mappe.jahresansicht().eigene, werk, mappe.profil, stammdaten=mappe.stammdaten)
        gruppen = []
        for kategorie in taxonomy.KATEGORIEN:
            liste = [d for d in mappe.dokumente if d.wirksame_kategorie == kategorie.id]
            if liste:
                liste.sort(key=lambda d: (d.analyse.datum if d.analyse and d.analyse.datum else "9999", d.dateiname))
                gruppen.append((kategorie, liste))
        return render_template(
            "index.html",
            **grunddaten(),
            auswertung=ergebnis,
            kennzahlen=ergebnis.kennzahlen,
            gruppen=gruppen,
            nicht_analysiert=[d for d in mappe.dokumente if d.analyse is None],
        )

    @app.get("/befunde")
    def befunde():
        ergebnis = auswertung()
        return render_template("befunde.html", **grunddaten(), auswertung=ergebnis)

    @app.route("/profil", methods=["GET", "POST"])
    def profil():
        if request.method == "POST":
            formular = request.form
            neu = Profil(
                name=formular.get("name", "").strip(),
                veranlagungsjahr=mappe.jahr,
                familienstand=formular.get("familienstand", "ledig"),
                veranlagungsart=formular.get("veranlagungsart", "einzel"),
                anzahl_kinder=_ganzzahl(formular.get("anzahl_kinder")) or 0,
                merkmale=formular.getlist("merkmale"),
                entfernung_km=_kommazahl(formular.get("entfernung_km")),
                arbeitstage=_ganzzahl(formular.get("arbeitstage")),
                homeoffice_tage=_ganzzahl(formular.get("homeoffice_tage")),
                grad_der_behinderung=_ganzzahl(formular.get("grad_der_behinderung")),
                pflegegrad=_ganzzahl(formular.get("pflegegrad")),
                bruttoarbeitslohn=_kommazahl(formular.get("bruttoarbeitslohn")),
                gesamtbetrag_der_einkuenfte=_kommazahl(formular.get("gesamtbetrag_der_einkuenfte")),
                taetigkeiten=formular.get("taetigkeiten", "").strip(),
                notizen=formular.get("notizen", "").strip(),
            )
            fehler = neu.unplausible_werte()
            if fehler:
                # Nicht speichern: ein unplausibler Wert wuerde die bisherige
                # Angabe ueberschreiben und faende sich spaeter in jeder
                # Berechnung wieder. Das Formular zeigt die Eingabe zurueck,
                # damit sie sich korrigieren laesst.
                grund = grunddaten()
                grund["profil"] = neu
                return (
                    render_template(
                        "profil.html",
                        **grund,
                        merkmale=MERKMALE,
                        gespeichert=None,
                        fehler=fehler,
                    ),
                    400,
                )
            mappe.profil = neu
            mappe.speichern()
            return redirect(url_for("profil", gespeichert=1))
        return render_template(
            "profil.html",
            **grunddaten(),
            merkmale=MERKMALE,
            gespeichert=request.args.get("gespeichert"),
            fehler=None,
        )

    @app.route("/stammdaten", methods=["GET", "POST"])
    def stammdaten():
        daten = mappe.stammdaten
        if request.method == "POST":
            fehler: list[str] = []
            for vorlage in stammdaten_modul.VORLAGEN:
                roh = (request.form.get(f"wert_{vorlage.id}") or "").strip()
                quelle = (request.form.get(f"quelle_{vorlage.id}") or "").strip()
                if not roh:
                    daten.entfernen(vorlage.id)
                    continue
                wert: Any = roh
                if vorlage.einheit in ("EUR", "prozent_pro_jahr"):
                    gelesen = zahl_lesen(roh)
                    if gelesen is None:
                        fehler.append(f"{vorlage.label}: '{roh}' ist keine Zahl.")
                        continue
                    wert = gelesen
                daten.setzen(vorlage.id, wert, quelle=quelle, gilt_ab_jahr=mappe.jahr)
            if fehler:
                return (
                    render_template(
                        "stammdaten.html",
                        **grunddaten(),
                        vorlagen=stammdaten_modul.VORLAGEN,
                        stammdaten=daten,
                        gespeichert=None,
                        fehler=fehler,
                    ),
                    400,
                )
            mappe.stammdaten_speichern()
            return redirect(url_for("stammdaten", gespeichert=1))
        return render_template(
            "stammdaten.html",
            **grunddaten(),
            vorlagen=stammdaten_modul.VORLAGEN,
            stammdaten=daten,
            gespeichert=request.args.get("gespeichert"),
            fehler=None,
        )

    @app.get("/beratung")
    def beratung():
        """Das Gespraech mit dem Steuerexperten ueber den eigenen Bestand.

        Bisher lief die Beratung ausserhalb des Werkzeugs und wusste deshalb
        nichts von den Belegen, und das Werkzeug analysierte die Belege, ohne
        zurueckfragen zu koennen. Hier faellt beides zusammen.
        """
        gespraech = berater.laden(mappe)
        return render_template(
            "beratung.html",
            **grunddaten(),
            beitraege=berater.beitraege(gespraech),
            entwuerfe=berater.entwuerfe(mappe),
            verbesserungen=berater.verbesserungen(mappe) is not None,
            auswahl_beratung=AUSWAHL_BERATUNG,
            modell_beratung=modell_beratung_pruefen(mappe.einstellungen.get("modell_beratung")),
            auswahl_denktiefe=AUSWAHL_DENKTIEFE,
            denktiefe=denktiefe_pruefen(mappe.einstellungen.get("denktiefe_beratung")),
            zug_bericht=berater.zug_bericht(gespraech.letzter_zug),
            laeuft=beratungslauf.laeuft,
            fehler=beratungslauf.fehler,
        )

    @app.get("/entwurf/<name>")
    def entwurf(name: str):
        """Zeigt einen im Gespraech entstandenen Entwurf zum Lesen und Kopieren."""
        datei = berater.entwurf_pfad(mappe, name)
        if datei is None:
            abort(404)
        return render_template(
            "entwurf.html", **grunddaten(), name=datei.name, text=datei.read_text(encoding="utf-8")
        )

    @app.get("/gespraechsbild/<name>")
    def gespraechsbild(name: str):
        """Liefert ein im Gespraech gezeigtes Bild fuer die Anzeige im Verlauf."""
        datei = berater.bildpfad(mappe, name)
        if datei is None:
            abort(404)
        return send_file(datei)

    @app.get("/verbesserungen")
    def verbesserungen():
        """Was dem Werkzeug im Gebrauch gefehlt hat, gesammelt vom Modell selbst."""
        datei = berater.verbesserungen(mappe)
        if datei is None:
            abort(404)
        return render_template(
            "entwurf.html", **grunddaten(), name=datei.name, text=datei.read_text(encoding="utf-8")
        )

    @app.post("/beratung/loeschen")
    def beratung_loeschen():
        berater.loeschen(mappe)
        return redirect(url_for("beratung"))

    @app.get("/api/beratung")
    def beratung_stand():
        gespraech = berater.laden(mappe)
        return jsonify(
            {
                "laeuft": beratungslauf.laeuft,
                "fehler": beratungslauf.fehler,
                "beitraege": [b.als_dict() for b in berater.beitraege(gespraech)],
            }
        )

    @app.post("/api/beratung")
    def beratung_senden():
        if beratungslauf.laeuft:
            return jsonify({"fehler": "Es wird gerade schon eine Antwort erarbeitet."}), 409
        if not schluessel_vorhanden():
            return jsonify({"fehler": "Ohne ANTHROPIC_API_KEY ist kein Gespraech moeglich."}), 400
        daten = request.get_json(silent=True) or {}
        text = str(daten.get("nachricht") or "").strip()
        rohbilder = daten.get("bilder") or []
        if not text and not rohbilder:
            return jsonify({"fehler": "Die Nachricht ist leer."}), 400
        if len(rohbilder) > berater.MAX_BILDER_JE_NACHRICHT:
            return jsonify(
                {"fehler": f"Hoechstens {berater.MAX_BILDER_JE_NACHRICHT} Bilder je Nachricht."}
            ), 400

        # Die Bilder werden hier aufgenommen, nicht im Hintergrundlauf: ein
        # unbrauchbares Bild soll sofort eine Fehlermeldung ergeben und nicht
        # eine Minute spaeter ein abgebrochenes Gespraech.
        bilder = []
        for eintrag in rohbilder:
            if not isinstance(eintrag, dict):
                continue
            try:
                rohdaten = _b64.b64decode(str(eintrag.get("daten") or ""), validate=True)
                bilder.append(
                    berater.bild_aufnehmen(mappe, rohdaten, str(eintrag.get("medientyp") or ""))
                )
            except (berater.BeratungsFehler, ValueError, binascii.Error) as fehler:
                return jsonify({"fehler": f"Bild abgelehnt: {fehler}"}), 400

        modell = modell_beratung_pruefen(daten.get("modell") or mappe.einstellungen.get("modell_beratung"))
        mappe.einstellungen["modell_beratung"] = modell
        tiefe = denktiefe_pruefen(daten.get("denktiefe") or mappe.einstellungen.get("denktiefe_beratung"))
        mappe.einstellungen["denktiefe_beratung"] = tiefe
        mappe.speichern()

        beratungslauf.laeuft = True
        beratungslauf.fehler = ""
        beratungslauf.begonnen_um = _dt.datetime.now().strftime("%H:%M:%S")

        def lauf() -> None:
            try:
                # Waehrend eines Zuges darf kein anderer Lauf die Mappe
                # veraendern: das Modell traegt Notizen ein und ordnet um.
                with sperre:
                    gespraech = berater.laden(mappe)
                    berater.nachricht_senden(
                        mappe,
                        gespraech,
                        text,
                        dienst=Analysedienst(modell_beratung=modell),
                        regelwerk=regelwerk(),
                        modell=modell,
                        sichern=lambda g: berater.speichern(mappe, g),
                        bilder=bilder,
                        denktiefe=tiefe,
                    )
            except Exception as fehler:  # noqa: BLE001 - jeder Fehler gehoert auf die Seite
                beratungslauf.fehler = str(fehler)
                LOG.warning("Beratung fehlgeschlagen: %s", fehler)
            finally:
                beratungslauf.laeuft = False

        threading.Thread(target=lauf, daemon=True).start()
        return jsonify({"laeuft": True})

    @app.route("/dubletten", methods=["GET", "POST"])
    def dubletten():
        """Doppelt vorliegende Belege anzeigen und in einem Zug entfernen.

        Von Hand sind Dubletten muehsam zu finden: Sie stehen in derselben
        Gruppe untereinander, sehen aber je nach Scan unterschiedlich aus. Ein
        doppelt gezaehlter Bruttolohn faellt dafuer sofort auf - in der falschen
        Richtung.
        """
        if request.method == "POST":
            entfernt = 0
            for kennung in request.form.getlist("entfernen"):
                if mappe.dokument_entfernen(kennung, datei_loeschen=True):
                    entfernt += 1
            if entfernt:
                mappe.speichern()
            return redirect(url_for("dubletten", entfernt=entfernt))

        gruppen = gaps.dubletten_gruppen(mappe.dokumente)
        return render_template(
            "dubletten.html",
            **grunddaten(),
            gruppen=gruppen,
            entfernt=request.args.get("entfernt", type=int),
        )

    @app.route("/rueckfragen", methods=["GET", "POST"])
    def rueckfragen():
        """Alle offenen Rueckfragen auf einer Seite, jede mit eigenem Feld.

        In der Konsole werden die Fragen nacheinander gestellt; zurueck kommt man
        nur ueber einen Neustart. Wer in kurzen Abschnitten arbeitet, braucht
        stattdessen eine Seite, auf der alles nebeneinander steht und in
        beliebiger Reihenfolge beantwortet werden kann.
        """
        if request.method == "POST":
            geaendert = 0
            for schluessel, wert in request.form.items():
                if not schluessel.startswith("notiz-"):
                    continue
                eintrag = mappe.dokument(schluessel[len("notiz-"):])
                if eintrag is None:
                    continue
                neuer_text = wert.strip()
                if neuer_text != eintrag.notiz:
                    eintrag.notiz = neuer_text
                    geaendert += 1
            if geaendert:
                mappe.speichern()
            return redirect(url_for("rueckfragen", gespeichert=geaendert))

        offen, erledigt = [], []
        for dokument in mappe.jahresansicht().eigene:
            if not dokument.analyse:
                continue
            fragen = [
                text.strip()
                for text in dokument.analyse.fehlende_nachweise
                if text.strip() and offen_modul.thema(text)[0] == "frage"
            ]
            if not fragen:
                continue
            analyse = dokument.analyse
            betrag = analyse.betrag_abzugsfaehig or analyse.betrag_gesamt or 0.0
            eintrag = {"dokument": dokument, "fragen": fragen, "betrag": betrag}
            (erledigt if dokument.notiz else offen).append(eintrag)

        # Teuerster Beleg zuerst: Dieselbe Minute Arbeit bringt bei 35.000 EUR
        # tausendmal mehr als bei einem Abo ueber 29,99 EUR.
        for liste in (offen, erledigt):
            liste.sort(key=lambda e: -abs(float(e["betrag"] or 0)))

        return render_template(
            "rueckfragen.html",
            **grunddaten(),
            offen=offen,
            erledigt=erledigt,
            gespeichert=request.args.get("gespeichert", type=int),
        )

    @app.route("/dokument/<dokument_id>", methods=["GET", "POST"])
    def dokument(dokument_id: str):
        eintrag = mappe.dokument(dokument_id)
        if eintrag is None:
            abort(404)
        if request.method == "POST":
            eintrag.manuelle_kategorie = request.form.get("kategorie", "").strip()
            eintrag.notiz = request.form.get("notiz", "").strip()
            # Das Jahr von Hand setzen: Ihre Angabe hat Vorrang vor dem, was
            # die Analyse aus dem Dokument gelesen hat.
            gesetztes_jahr = _ganzzahl(request.form.get("herkunft_jahr"))
            eintrag.herkunft_jahr = (
                gesetztes_jahr if gesetztes_jahr and 1990 <= gesetztes_jahr <= 2100 else None
            )
            gewaehlte_herkunft = (request.form.get("herkunft") or "").strip()
            eintrag.herkunft = gewaehlte_herkunft if gewaehlte_herkunft in HERKUNFT_IDS else ""
            mappe.speichern()
            return redirect(url_for("dokument", dokument_id=dokument_id, gespeichert=1))
        return render_template(
            "dokument.html",
            **grunddaten(),
            dokument=eintrag,
            kategorien=taxonomy.KATEGORIEN,
            gespeichert=request.args.get("gespeichert"),
        )

    @app.get("/datei/<dokument_id>")
    def datei(dokument_id: str):
        eintrag = mappe.dokument(dokument_id)
        if eintrag is None:
            abort(404)
        pfad = mappe.pfad_zu(eintrag)
        if not pfad.exists():
            abort(404)
        return send_file(pfad, mimetype=eintrag.medientyp or None)

    @app.get("/formular")
    def formularzuordnung():
        """Wo jeder Betrag in der Steuererklaerung hingehoert."""
        werk = regelwerk()
        return render_template(
            "formular.html",
            **grunddaten(),
            posten=formular_modul.aufstellung(mappe.jahresansicht().eigene, werk),
            geprueft=bool(werk.daten.get("formularzeilen_geprueft")),
        )

    @app.get("/bericht")
    def bericht():
        werk = regelwerk()
        ergebnis = gaps.auswerten(mappe.jahresansicht().eigene, werk, mappe.profil, stammdaten=mappe.stammdaten)
        return report.html_bericht(
            mappe.jahresansicht().eigene, ergebnis, werk, mappe.profil, mappe.gesamtauswertung()
        )

    # ---------------------------------------------------------------- API --

    @app.post("/api/hochladen")
    def hochladen():
        dateien = request.files.getlist("dateien")
        if not dateien:
            return jsonify({"fehler": "Keine Dateien empfangen."}), 400
        # Angaben zum ganzen Stapel: Sie kommen vom Nutzer und sind
        # verlaesslicher als jede Ableitung aus dem Dokument.
        herkunft = request.form.get("herkunft", "").strip()
        if herkunft not in HERKUNFT_IDS:
            herkunft = ""
        herkunft_jahr = _ganzzahl(request.form.get("herkunft_jahr"))
        if herkunft_jahr is not None and not 1990 <= herkunft_jahr <= 2100:
            herkunft_jahr = None

        aufgenommen, dubletten, abgelehnt = [], [], []
        with TemporaryDirectory() as temp:
            for datei in dateien:
                if not datei.filename:
                    continue
                zwischenpfad = Path(temp) / Path(datei.filename).name
                datei.save(zwischenpfad)
                try:
                    eintrag, ist_neu = mappe.datei_aufnehmen(
                        zwischenpfad,
                        Path(datei.filename).name,
                        herkunft=herkunft,
                        herkunft_jahr=herkunft_jahr,
                    )
                except ArbeitsmappenFehler as fehler:
                    abgelehnt.append({"datei": datei.filename, "grund": str(fehler)})
                    continue
                (aufgenommen if ist_neu else dubletten).append(eintrag.dateiname)
        mappe.speichern()
        return jsonify(
            {
                "aufgenommen": aufgenommen,
                "dubletten": dubletten,
                "abgelehnt": abgelehnt,
                "gesamt": len(mappe.dokumente),
            }
        )

    @app.post("/api/analyse")
    def analyse_starten():
        if not schluessel_vorhanden():
            return jsonify({"fehler": "Es ist kein ANTHROPIC_API_KEY gesetzt."}), 400
        alle = bool(request.json and request.json.get("alle"))
        nur = (request.json or {}).get("dokument")
        modell = modell_dokument_pruefen((request.json or {}).get("modell"))
        # Sofort festhalten: die Wahl soll auch dann erhalten bleiben, wenn der
        # Lauf gar nicht erst startet, etwa weil es nichts zu analysieren gibt.
        mappe.einstellungen["modell_dokument"] = modell
        mappe.speichern()
        with sperre:
            if auftrag.laeuft:
                return jsonify({"fehler": "Es laeuft bereits ein Vorgang."}), 409
            if nur:
                zu_pruefen = [d for d in mappe.dokumente if d.id == nur]
            elif alle:
                zu_pruefen = list(mappe.dokumente)
            else:
                zu_pruefen = [d for d in mappe.dokumente if d.analyse is None or d.status == STATUS_FEHLER]
            if not nur:
                # Was der Nutzer selbst einem anderen Jahr zugeordnet hat,
                # wird nicht geprueft und kostet nichts.
                zu_pruefen = [
                    d for d in zu_pruefen
                    if not (d.herkunft_jahr and d.herkunft_jahr != mappe.jahr)
                ]
            if not zu_pruefen:
                return jsonify({"fehler": "Es gibt nichts zu analysieren."}), 400
            auftrag.art = "analyse"
            auftrag.laeuft = True
            auftrag.gesamt = len(zu_pruefen)
            auftrag.erledigt = 0
            auftrag.aktuell = ""
            auftrag.meldungen = []
            auftrag.fehler = ""
            auftrag.fertig_um = ""

        def lauf() -> None:
            dienst = Analysedienst(modell_dokument=modell)
            werk = regelwerk()
            auftrag.meldungen.append(f"Dokumentanalyse mit {modell}")
            try:
                for eintrag in zu_pruefen:
                    auftrag.aktuell = eintrag.dateiname
                    try:
                        eintrag.analyse = dienst.dokument_analysieren(
                            mappe.pfad_zu(eintrag),
                            eintrag.medientyp,
                            werk,
                            mappe.profil,
                            eintrag.notiz,
                            herkunft=HERKUNFT_LABEL.get(eintrag.herkunft, ""),
                            stammdaten=mappe.stammdaten,
                        )
                        eintrag.analyse.kontext = mappe.kontext_pruefsumme()
                        eintrag.status = STATUS_ANALYSIERT
                        eintrag.fehler = ""
                        zusatz = EIGNUNG_LABEL.get(eintrag.analyse.eignung, "")
                        auftrag.meldungen.append(f"{eintrag.dateiname}: {eintrag.analyse.dokumenttyp} ({zusatz})")
                    except Exception as fehler:  # noqa: BLE001 - ein Dokument darf den Lauf nicht stoppen
                        eintrag.status = STATUS_FEHLER
                        eintrag.fehler = str(fehler)
                        auftrag.meldungen.append(f"{eintrag.dateiname}: FEHLER {fehler}")
                        # Kein Traceback: Ein einzelner fehlgeschlagener Beleg ist
                        # ein vorgesehener Fall, keine Stoerung des Laufs. Wer die
                        # Konsole sieht, soll nicht glauben, es sei etwas kaputt.
                        LOG.warning("Analyse von %s fehlgeschlagen: %s", eintrag.dateiname, fehler)
                    auftrag.erledigt += 1
                    mappe.speichern()
            except Exception as fehler:  # noqa: BLE001 - Thread darf nicht still sterben
                auftrag.fehler = str(fehler)
                LOG.exception("Analyselauf abgebrochen")
            finally:
                auftrag.laeuft = False
                auftrag.aktuell = ""
                auftrag.fertig_um = _dt.datetime.now().strftime("%H:%M:%S")

        threading.Thread(target=lauf, daemon=True).start()
        return jsonify(auftrag.als_dict())

    @app.get("/api/auftrag")
    def auftrag_abfragen():
        return jsonify(auftrag.als_dict())

    @app.post("/api/ordnen")
    def ordnen():
        daten = request.json or {}
        modell = modell_strategie_pruefen(daten.get("modell"))
        mappe.einstellungen["modell_strategie"] = modell
        mappe.speichern()
        with sperre:
            if auftrag.laeuft:
                return jsonify({"fehler": "Es laeuft bereits ein Vorgang."}), 409
            auftrag.art = "ordnen"
            auftrag.laeuft = True
            auftrag.gesamt = 1
            auftrag.erledigt = 0
            auftrag.meldungen = []
            auftrag.fehler = ""
            auftrag.aktuell = "Ablage wird aufgebaut"

        def lauf() -> None:
            try:
                werk = regelwerk()
                ergebnis = gaps.auswerten(mappe.jahresansicht().eigene, werk, mappe.profil, stammdaten=mappe.stammdaten)
                modellauswertung = None
                if daten.get("gesamtauswertung") and schluessel_vorhanden():
                    auftrag.aktuell = f"Gesamtauswertung laeuft ({modell})"
                    auftrag.meldungen.append(f"Gesamtauswertung mit {modell}")
                    dienst = Analysedienst(modell_strategie=modell)
                    modellauswertung = dienst.gesamtauswertung(
                        werk,
                        mappe.profil,
                        [_bestandseintrag(d) for d in mappe.jahresansicht().eigene],
                        [b.als_dict() for b in ergebnis.befunde],
                    )
                    mappe.gesamtauswertung_speichern(modellauswertung, modell)
                auftrag.aktuell = "Dateien werden einsortiert"
                ablage = organize.ablage_erzeugen(
                    mappe, ungeeignete_mitnehmen=not daten.get("ohne_ungeeignete")
                )
                mappe.speichern()
                berichte = report.berichte_schreiben(
                    mappe.berichte,
                    mappe.jahresansicht().eigene,
                    ergebnis,
                    werk,
                    mappe.profil,
                    modellauswertung,
                )
                auftrag.meldungen.append(f"{ablage.anzahl} Dateien einsortiert unter {ablage.wurzel}")
                for pfad in berichte:
                    auftrag.meldungen.append(f"Bericht: {pfad}")
                if daten.get("paket"):
                    paket = organize.paket_erzeugen(mappe, ablage, berichte)
                    auftrag.meldungen.append(f"Paket: {paket}")
                auftrag.erledigt = 1
            except Exception as fehler:  # noqa: BLE001
                auftrag.fehler = str(fehler)
                LOG.exception("Ordnen fehlgeschlagen")
            finally:
                auftrag.laeuft = False
                auftrag.aktuell = ""
                auftrag.fertig_um = _dt.datetime.now().strftime("%H:%M:%S")

        threading.Thread(target=lauf, daemon=True).start()
        return jsonify(auftrag.als_dict())

    @app.post("/api/dokument/<dokument_id>/loeschen")
    def dokument_loeschen(dokument_id: str):
        erfolg = mappe.dokument_entfernen(dokument_id, datei_loeschen=True)
        mappe.speichern()
        return jsonify({"erfolg": erfolg})

    @app.post("/api/eingang-einlesen")
    def eingang_einlesen():
        neue = mappe.eingang_einlesen()
        mappe.speichern()
        return jsonify({"neu": [d.dateiname for d in neue]})

    # ------------------------------------------------------------ Hilfen --

    @app.template_filter("euro")
    def _euro(betrag: float | None) -> str:
        return euro(betrag) if betrag not in (None, "") else "—"

    @app.template_filter("datum")
    def _datum(wert: str | None) -> str:
        if not wert:
            return ""
        try:
            return _dt.date.fromisoformat(str(wert)).strftime("%d.%m.%Y")
        except ValueError:
            return str(wert)

    return app


def _bestandseintrag(dokument) -> dict[str, Any]:
    analyse = dokument.analyse
    if not analyse:
        return {"datei": dokument.dateiname, "status": "nicht analysiert"}
    return {
        "datei": dokument.dateiname,
        "kategorie": dokument.wirksame_kategorie,
        "typ": analyse.dokumenttyp,
        "aussteller": analyse.aussteller,
        "datum": analyse.datum,
        "steuerjahr": analyse.steuerjahr,
        "betrag_gesamt": analyse.betrag_gesamt,
        "betrag_abzugsfaehig": analyse.betrag_abzugsfaehig,
        "zahlungsart": analyse.zahlungsart,
        "eignung": analyse.eignung,
        "fehlende_nachweise": analyse.fehlende_nachweise,
        "zusammenfassung": analyse.zusammenfassung,
    }


def _ganzzahl(wert: Any) -> int | None:
    zahl = zahl_lesen(wert)
    return int(round(zahl)) if zahl is not None else None


def _kommazahl(wert: Any) -> float | None:
    return zahl_lesen(wert)


def starten(mappe: Arbeitsmappe, host: str = "127.0.0.1", port: int = 5173, debug: bool = False) -> None:
    app = anwendung_bauen(mappe)
    print(f"Steuer-Assistent laeuft auf http://{host}:{port}")
    print(f"Arbeitsmappe: {mappe.wurzel}  ·  Veranlagungszeitraum {mappe.jahr}")
    if not schluessel_vorhanden():
        print("Hinweis: ohne ANTHROPIC_API_KEY ist die Dokumentanalyse deaktiviert.")
    app.run(host=host, port=port, debug=debug, use_reloader=False)


__all__ = [
    "EIGNUNG_BEDINGT",
    "EIGNUNG_GEEIGNET",
    "EIGNUNG_UNGEEIGNET",
    "anwendung_bauen",
    "starten",
]
