"""Kommandozeile des Steuer-Assistenten."""

from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import gaps, organize, report, rules, taxonomy
from .formatierung import euro
from .analyze import AnalyseFehler, Analysedienst, ExtraktionsFehler, KeinSchluessel, schluessel_vorhanden
from .models import (
    EIGNUNG_BEDINGT,
    EIGNUNG_GEEIGNET,
    EIGNUNG_UNGEEIGNET,
    MERKMALE,
    STATUS_ANALYSIERT,
    STATUS_FEHLER,
    Dokument,
    Profil,
)
from .workspace import Arbeitsmappe, ArbeitsmappenFehler, dateien_sammeln

LOG = logging.getLogger("steuer")

SYMBOL = {
    EIGNUNG_GEEIGNET: "+",
    EIGNUNG_BEDINGT: "!",
    EIGNUNG_UNGEEIGNET: "-",
    "unklar": "?",
}


def _mappe_oeffnen(args: argparse.Namespace) -> Arbeitsmappe:
    if getattr(args, "mappe", None):
        return Arbeitsmappe.laden(Path(args.mappe))
    return Arbeitsmappe.finden()


def _regelwerk(mappe: Arbeitsmappe) -> rules.Regelwerk:
    regelwerk = rules.laden(mappe.jahr)
    if regelwerk.ist_ersatz:
        print(
            f"Hinweis: Fuer {mappe.jahr} liegt kein gepflegter Rechtsstand vor. "
            f"Es werden ersatzweise die Werte aus {regelwerk.quelle_jahr} verwendet.\n"
            f"         Entwurf erzeugen mit: steuer recht-update --jahr {mappe.jahr}",
            file=sys.stderr,
        )
    return regelwerk


# ------------------------------------------------------------------ Befehle --

def befehl_init(args: argparse.Namespace) -> int:
    ziel = Path(args.pfad or Path.cwd() / f"steuer-{args.jahr}")
    if (ziel / "steuer.json").exists():
        print(f"In {ziel} liegt bereits eine Arbeitsmappe.")
        return 1
    profil = Profil(name=args.name or "", veranlagungsjahr=args.jahr)
    mappe = Arbeitsmappe.anlegen(ziel, args.jahr, profil)
    regelwerk = rules.laden(args.jahr)
    print(f"Arbeitsmappe fuer {args.jahr} angelegt: {mappe.wurzel}")
    print(f"  Scans ablegen in: {mappe.eingang}")
    print(f"  Rechtsstand:      {regelwerk.stand}" + (f" (ersatzweise aus {regelwerk.quelle_jahr})" if regelwerk.ist_ersatz else ""))
    print()
    print("Naechste Schritte:")
    print("  1. steuer profil --bearbeiten     Ausgangslage erfassen")
    print("  2. steuer hinzufuegen <Ordner>    Scans aufnehmen")
    print("  3. steuer analyse                 Dokumente pruefen lassen")
    print("  4. steuer ordnen                  Ablage und Uebersicht erzeugen")
    return 0


def befehl_profil(args: argparse.Namespace) -> int:
    mappe = _mappe_oeffnen(args)
    profil = mappe.profil

    if args.bearbeiten:
        print("Profil erfassen. Enter uebernimmt den bisherigen Wert.\n")
        profil.name = _frage("Name", profil.name)
        profil.familienstand = _frage(
            "Familienstand (ledig/verheiratet/geschieden/verwitwet)", profil.familienstand
        )
        profil.veranlagungsart = _frage("Veranlagung (einzel/zusammen)", profil.veranlagungsart)
        profil.anzahl_kinder = int(_frage("Anzahl Kinder", str(profil.anzahl_kinder)) or 0)
        print("\nZutreffendes mit j bestaetigen:\n")
        merkmale = []
        for merkmal, beschriftung in MERKMALE:
            vorgabe = "j" if profil.hat(merkmal) else "n"
            if _frage(f"  {beschriftung}? (j/n)", vorgabe).strip().lower().startswith("j"):
                merkmale.append(merkmal)
        profil.merkmale = merkmale
        print()
        if "pendler" in merkmale:
            profil.entfernung_km = _zahl_frage("Einfache Entfernung zur Arbeit in km", profil.entfernung_km)
            profil.arbeitstage = _int_frage("Arbeitstage im Jahr", profil.arbeitstage)
        if "homeoffice" in merkmale:
            profil.homeoffice_tage = _int_frage("Homeoffice-Tage im Jahr", profil.homeoffice_tage)
        if "behinderung" in merkmale:
            profil.grad_der_behinderung = _int_frage("Grad der Behinderung", profil.grad_der_behinderung)
        if "pflege" in merkmale:
            profil.pflegegrad = _int_frage("Pflegegrad der gepflegten Person", profil.pflegegrad)
        profil.bruttoarbeitslohn = _zahl_frage(
            "Bruttoarbeitslohn (optional, verbessert die Schaetzungen)", profil.bruttoarbeitslohn
        )
        profil.gesamtbetrag_der_einkuenfte = _zahl_frage(
            "Gesamtbetrag der Einkuenfte (optional, fuer die zumutbare Belastung)",
            profil.gesamtbetrag_der_einkuenfte,
        )
        profil.notizen = _frage("Notizen", profil.notizen)
        mappe.speichern()
        print("\nProfil gespeichert.")
        return 0

    print(f"Profil der Arbeitsmappe {mappe.wurzel.name} ({mappe.jahr})")
    print(f"  Name:           {profil.name or '(nicht gesetzt)'}")
    print(f"  Familienstand:  {profil.familienstand}, Veranlagung {profil.veranlagungsart}")
    print(f"  Kinder:         {profil.anzahl_kinder}")
    print(f"  Merkmale:       {', '.join(profil.merkmale) or '(keine)'}")
    for feld, beschriftung in (
        ("entfernung_km", "Entfernung km"),
        ("arbeitstage", "Arbeitstage"),
        ("homeoffice_tage", "Homeoffice-Tage"),
        ("grad_der_behinderung", "Grad der Behinderung"),
        ("pflegegrad", "Pflegegrad"),
        ("bruttoarbeitslohn", "Bruttoarbeitslohn"),
        ("gesamtbetrag_der_einkuenfte", "Gesamtbetrag der Einkuenfte"),
    ):
        wert = getattr(profil, feld)
        if wert:
            print(f"  {beschriftung + ':':15} {wert}")
    if profil.notizen:
        print(f"  Notizen:        {profil.notizen}")
    return 0


def _frage(text: str, vorgabe: str | None = "") -> str:
    anzeige = f" [{vorgabe}]" if vorgabe else ""
    try:
        eingabe = input(f"{text}{anzeige}: ").strip()
    except EOFError:
        return vorgabe or ""
    return eingabe or (vorgabe or "")


def _zahl_frage(text: str, vorgabe: float | None) -> float | None:
    antwort = _frage(text, str(vorgabe) if vorgabe is not None else "")
    if not antwort:
        return None
    try:
        return float(antwort.replace(",", "."))
    except ValueError:
        return vorgabe


def _int_frage(text: str, vorgabe: int | None) -> int | None:
    wert = _zahl_frage(text, float(vorgabe) if vorgabe is not None else None)
    return int(wert) if wert is not None else None


def befehl_hinzufuegen(args: argparse.Namespace) -> int:
    mappe = _mappe_oeffnen(args)
    dateien = dateien_sammeln([Path(p) for p in args.pfade])
    if not dateien:
        print("Keine unterstuetzten Dateien gefunden.")
        return 1
    neu = uebersprungen = 0
    for datei in dateien:
        try:
            dokument, ist_neu = mappe.datei_aufnehmen(datei)
        except ArbeitsmappenFehler as fehler:
            print(f"  uebersprungen: {fehler}")
            uebersprungen += 1
            continue
        if ist_neu:
            neu += 1
            print(f"  aufgenommen: {dokument.dateiname}")
        else:
            uebersprungen += 1
            print(f"  Dublette:    {datei.name} (identisch mit {dokument.dateiname})")
    mappe.speichern()
    print(f"\n{neu} neu, {uebersprungen} uebersprungen. Insgesamt {len(mappe.dokumente)} Dokumente.")
    return 0


def befehl_analyse(args: argparse.Namespace) -> int:
    mappe = _mappe_oeffnen(args)
    neue = mappe.eingang_einlesen()
    if neue:
        print(f"{len(neue)} Dateien aus dem Eingangsordner uebernommen.")
    regelwerk = _regelwerk(mappe)

    if args.dokument:
        zu_pruefen = [d for d in mappe.dokumente if d.id.startswith(args.dokument)]
    elif args.alle:
        zu_pruefen = list(mappe.dokumente)
    else:
        zu_pruefen = [d for d in mappe.dokumente if d.analyse is None or d.status == STATUS_FEHLER]

    if not zu_pruefen:
        print("Nichts zu analysieren. Mit --alle wird der gesamte Bestand neu geprueft.")
        mappe.speichern()
        return 0

    if not schluessel_vorhanden():
        print(
            "Es ist kein ANTHROPIC_API_KEY gesetzt.\n"
            "Schluessel erzeugen unter https://console.anthropic.com/settings/keys und setzen mit:\n"
            "  export ANTHROPIC_API_KEY=sk-ant-...",
            file=sys.stderr,
        )
        return 2

    dienst = Analysedienst(modell_dokument=args.modell or Analysedienst.modell_dokument)
    print(f"Analysiere {len(zu_pruefen)} Dokumente mit {dienst.modell_dokument} ...\n")

    def _einzeln(dokument: Dokument) -> tuple[Dokument, Exception | None]:
        try:
            analyse = dienst.dokument_analysieren(
                mappe.pfad_zu(dokument), dokument.medientyp, regelwerk, mappe.profil, dokument.notiz
            )
            dokument.analyse = analyse
            dokument.status = STATUS_ANALYSIERT
            dokument.fehler = ""
            return dokument, None
        except (AnalyseFehler, ExtraktionsFehler, OSError) as fehler:
            dokument.status = STATUS_FEHLER
            dokument.fehler = str(fehler)
            return dokument, fehler

    fehlerhaft = 0
    with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
        for dokument, fehler in pool.map(_einzeln, zu_pruefen):
            if fehler:
                fehlerhaft += 1
                print(f"  [x] {dokument.dateiname}: {fehler}")
                continue
            analyse = dokument.analyse
            assert analyse is not None
            zeichen = SYMBOL.get(analyse.eignung, "?")
            kategorie = taxonomy.kategorie(analyse.kategorie_id)
            print(f"  [{zeichen}] {dokument.dateiname}")
            print(f"      {analyse.dokumenttyp or 'unbestimmt'} -> {kategorie.label} ({kategorie.anlage})")
            if analyse.zusammenfassung:
                print(f"      {analyse.zusammenfassung}")
            if analyse.fehlende_nachweise:
                print(f"      fehlt noch: {'; '.join(analyse.fehlende_nachweise)}")
            if analyse.enthaelt_mehrere_dokumente:
                print(f"      Sammelscan mit {len(analyse.segmente)} Teildokumenten, "
                      f"trennen mit: steuer trennen {dokument.id}")
            mappe.speichern()

    mappe.speichern()
    print(f"\nFertig. {len(zu_pruefen) - fehlerhaft} analysiert, {fehlerhaft} fehlgeschlagen.")
    return 1 if fehlerhaft and fehlerhaft == len(zu_pruefen) else 0


def befehl_trennen(args: argparse.Namespace) -> int:
    mappe = _mappe_oeffnen(args)
    treffer = [d for d in mappe.dokumente if d.id.startswith(args.dokument)]
    if len(treffer) != 1:
        print(f"{'Kein' if not treffer else 'Mehr als ein'} Dokument passt zu '{args.dokument}'.")
        return 1
    dokument = treffer[0]
    if not dokument.analyse or not dokument.analyse.segmente:
        print("Fuer dieses Dokument wurden keine Teildokumente erkannt.")
        return 1
    if dokument.medientyp != "application/pdf":
        print("Nur PDFs koennen getrennt werden.")
        return 1

    from .extract import pdf_zerlegen

    segmente = [(s.von_seite, s.bis_seite) for s in dokument.analyse.segmente]
    basis = Path(dokument.dateiname).stem
    erzeugt = pdf_zerlegen(mappe.pfad_zu(dokument), segmente, mappe.eingang, basis)
    print(f"{len(erzeugt)} Teildokumente erzeugt:")
    for pfad, segment in zip(erzeugt, dokument.analyse.segmente):
        print(f"  {pfad.name}  ({segment.beschreibung})")
    mappe.eingang_einlesen()
    mappe.dokument_entfernen(dokument.id, datei_loeschen=False)
    quelle = mappe.pfad_zu(dokument)
    if quelle.exists():
        archiv = mappe.eingang / "_sammelscans"
        archiv.mkdir(exist_ok=True)
        quelle.rename(archiv / quelle.name)
        print(f"\nOriginal verschoben nach {archiv / quelle.name}")
    mappe.speichern()
    print("Die neuen Teildokumente mit 'steuer analyse' pruefen lassen.")
    return 0


def befehl_status(args: argparse.Namespace) -> int:
    mappe = _mappe_oeffnen(args)
    mappe.eingang_einlesen()
    mappe.speichern()
    regelwerk = _regelwerk(mappe)
    auswertung = gaps.auswerten(mappe.dokumente, regelwerk, mappe.profil)
    zahlen = auswertung.kennzahlen

    print(f"Arbeitsmappe {mappe.wurzel}  ·  Veranlagungszeitraum {mappe.jahr}")
    print(f"Rechtsstand {regelwerk.stand}\n")
    print(f"  Dokumente insgesamt      {zahlen['anzahl_dokumente']}")
    print(f"  analysiert               {zahlen['anzahl_analysiert']}")
    print(f"  einreichbar              {zahlen['anzahl_geeignet']}")
    print(f"  mit offenen Punkten      {zahlen['anzahl_bedingt']}")
    print(f"  nicht verwertbar         {zahlen['anzahl_ungeeignet']}")
    print()
    print(f"  Werbungskosten           {euro(zahlen['werbungskosten_gesamt'])} "
          f"(Pauschbetrag {euro(zahlen['arbeitnehmer_pauschbetrag'], 0)})")
    print(f"  Haushaltsnahe Kosten     {euro(zahlen['haushaltsnahe_aufwendungen_gesamt'])} "
          f"-> ca. {euro(zahlen['haushaltsnahe_ermaessigung_geschaetzt'])} Ermaessigung")
    print()
    print(f"  Luecken   {len(auswertung.luecken)}")
    print(f"  Chancen   {len(auswertung.chancen)}")
    print(f"  Warnungen {len(auswertung.warnungen)}")
    return 0


def befehl_pruefen(args: argparse.Namespace) -> int:
    mappe = _mappe_oeffnen(args)
    regelwerk = _regelwerk(mappe)
    auswertung = gaps.auswerten(mappe.dokumente, regelwerk, mappe.profil)

    def _ausgeben(titel: str, befunde: list) -> None:
        if not befunde:
            return
        print(f"\n{titel}")
        print("=" * len(titel))
        for befund in befunde:
            kopf = befund.titel
            if befund.potenzial_eur:
                kopf += f"  (bis zu {euro(befund.potenzial_eur, 0)})"
            print(f"\n[{befund.prioritaet}] {kopf}")
            if befund.anlage:
                print(f"  Anlage: {befund.anlage}")
            for zeile in _umbrechen(befund.beschreibung, 92):
                print(f"  {zeile}")

    _ausgeben("Was noch fehlt", auswertung.luecken)
    _ausgeben("Wo Geld liegen bleibt", auswertung.chancen)
    _ausgeben("Warnungen", auswertung.warnungen)
    print()
    return 0


def _umbrechen(text: str, breite: int) -> list[str]:
    import textwrap

    return textwrap.wrap(" ".join((text or "").split()), width=breite) or [""]


def befehl_ordnen(args: argparse.Namespace) -> int:
    mappe = _mappe_oeffnen(args)
    regelwerk = _regelwerk(mappe)
    offen = [d for d in mappe.dokumente if d.analyse is None]
    if offen and not args.trotzdem:
        print(
            f"{len(offen)} Dokumente sind noch nicht analysiert. "
            "Zuerst 'steuer analyse' ausfuehren oder mit --trotzdem fortfahren."
        )
        return 1

    auswertung = gaps.auswerten(mappe.dokumente, regelwerk, mappe.profil)
    modellauswertung = None
    if args.gesamtauswertung:
        if not schluessel_vorhanden():
            print("Ohne ANTHROPIC_API_KEY ist keine Gesamtauswertung moeglich.", file=sys.stderr)
        else:
            print("Erstelle Gesamtauswertung ...")
            try:
                dienst = Analysedienst()
                modellauswertung = dienst.gesamtauswertung(
                    regelwerk,
                    mappe.profil,
                    [_bestandseintrag(d) for d in mappe.dokumente],
                    [b.als_dict() for b in auswertung.befunde],
                )
            except (AnalyseFehler, KeinSchluessel) as fehler:
                print(f"Gesamtauswertung fehlgeschlagen: {fehler}", file=sys.stderr)

    ablage = organize.ablage_erzeugen(mappe, ungeeignete_mitnehmen=not args.ohne_ungeeignete)
    mappe.speichern()
    berichte = report.berichte_schreiben(
        mappe.berichte, mappe.dokumente, auswertung, regelwerk, mappe.profil, modellauswertung
    )

    print(f"\n{ablage.anzahl} Dateien einsortiert unter {ablage.wurzel}")
    for datei, grund in ablage.uebersprungen:
        print(f"  uebersprungen: {datei} ({grund})")
    print("\nBerichte:")
    for pfad in berichte:
        print(f"  {pfad}")

    if args.paket:
        paket = organize.paket_erzeugen(mappe, ablage, berichte)
        print(f"\nPaket fuer den Steuerberater: {paket}")
    return 0


def _bestandseintrag(dokument: Dokument) -> dict:
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


def befehl_liste(args: argparse.Namespace) -> int:
    mappe = _mappe_oeffnen(args)
    if not mappe.dokumente:
        print("Noch keine Dokumente aufgenommen.")
        return 0
    for kategorie in taxonomy.KATEGORIEN:
        liste = [d for d in mappe.dokumente if d.wirksame_kategorie == kategorie.id]
        if not liste:
            continue
        print(f"\n{kategorie.ordner} — {kategorie.label}  ({kategorie.anlage})")
        for dokument in liste:
            analyse = dokument.analyse
            zeichen = SYMBOL.get(analyse.eignung, "?") if analyse else " "
            betrag = ""
            if analyse and (analyse.betrag_abzugsfaehig or analyse.betrag_gesamt):
                betrag = f"{euro(analyse.betrag_abzugsfaehig or analyse.betrag_gesamt):>16}"
            print(f"  [{zeichen}] {dokument.id}  {dokument.dateiname[:52]:<52} {betrag}")
            if analyse and analyse.fehlende_nachweise:
                print(f"          fehlt noch: {'; '.join(analyse.fehlende_nachweise)}")
    print()
    return 0


def befehl_recht_zeigen(args: argparse.Namespace) -> int:
    jahr = args.jahr or _mappe_oeffnen(args).jahr
    regelwerk = rules.laden(jahr)
    print(f"Rechtsstand {regelwerk.jahr}  ·  gepflegt am {regelwerk.stand}  ·  Status {regelwerk.status}")
    if regelwerk.ist_ersatz:
        print(f"ACHTUNG: ersatzweise geladen aus {regelwerk.quelle_jahr}")
    print()
    for schluessel, eintrag in regelwerk.werte.items():
        if not isinstance(eintrag, dict):
            continue
        print(f"  {eintrag.get('label', schluessel)}")
        print(f"      {eintrag.get('wert')} {eintrag.get('einheit', '')}"
              + (f"   {eintrag['rechtsgrundlage']}" if eintrag.get("rechtsgrundlage") else ""))
    if regelwerk.fristen:
        print("\n  Fristen")
        for schluessel, wert in regelwerk.fristen.items():
            print(f"      {schluessel}: {wert}")
    return 0


def befehl_recht_update(args: argparse.Namespace) -> int:
    from . import lawupdate

    if not schluessel_vorhanden():
        print("Fuer die Recherche wird ein ANTHROPIC_API_KEY benoetigt.", file=sys.stderr)
        return 2
    jahr = args.jahr
    print(f"Recherchiere den Rechtsstand fuer {jahr}. Das dauert ein bis zwei Minuten ...\n")
    try:
        ergebnis = lawupdate.entwurf_erzeugen(jahr)
    except (AnalyseFehler, rules.RegelFehler) as fehler:
        print(f"Recherche fehlgeschlagen: {fehler}", file=sys.stderr)
        return 1

    relevante = ergebnis.relevante
    if relevante:
        print(f"{len(relevante)} Abweichungen zum hinterlegten Stand:\n")
        for aenderung in relevante:
            alt = "—" if aenderung.alt is None else f"{aenderung.alt:g}"
            print(f"  {aenderung.label}")
            print(f"      {alt} -> {aenderung.neu:g} {aenderung.einheit}")
            if aenderung.quelle:
                print(f"      Quelle: {aenderung.quelle}")
    else:
        print("Keine Abweichungen gefunden.")

    if ergebnis.ungeklaert:
        print("\nNicht belastbar ermittelt:")
        for punkt in ergebnis.ungeklaert:
            print(f"  - {punkt}")

    print(f"\nEntwurf:  {ergebnis.entwurfspfad}")
    print(f"Bericht:  {ergebnis.berichtspfad}")
    print(
        f"\nNach Durchsicht uebernehmen mit:  steuer recht-uebernehmen --jahr {jahr}\n"
        "Der bisherige Stand wird dabei als .bak gesichert."
    )
    return 0


def befehl_recht_uebernehmen(args: argparse.Namespace) -> int:
    from . import lawupdate

    try:
        ziel = lawupdate.entwurf_uebernehmen(args.jahr)
    except rules.RegelFehler as fehler:
        print(str(fehler), file=sys.stderr)
        return 1
    print(f"Rechtsstand fuer {args.jahr} uebernommen: {ziel}")
    return 0


def befehl_web(args: argparse.Namespace) -> int:
    from .web.app import starten

    try:
        mappe = _mappe_oeffnen(args)
    except ArbeitsmappenFehler as fehler:
        print(str(fehler), file=sys.stderr)
        return 1
    starten(mappe, host=args.host, port=args.port, debug=args.debug)
    return 0


# ------------------------------------------------------------------- Parser --

def parser_bauen() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="steuer",
        description=(
            "Bereitet eingescannte Unterlagen fuer die deutsche Einkommensteuererklaerung auf: "
            "pruefen, benennen, ordnen, Luecken und Chancen finden."
        ),
        epilog="Dieses Werkzeug ersetzt keine Steuerberatung.",
    )
    parser.add_argument("--mappe", help="Pfad zur Arbeitsmappe (sonst wird aufwaerts gesucht).")
    parser.add_argument("-v", "--ausfuehrlich", action="store_true", help="Ausfuehrliche Protokollierung.")
    unter = parser.add_subparsers(dest="befehl", required=True)

    p = unter.add_parser("init", help="Neue Arbeitsmappe fuer ein Veranlagungsjahr anlegen.")
    p.add_argument("--jahr", type=int, required=True)
    p.add_argument("--pfad", help="Zielverzeichnis, Standard: ./steuer-<Jahr>")
    p.add_argument("--name", help="Name des Steuerpflichtigen.")
    p.set_defaults(funktion=befehl_init)

    p = unter.add_parser("profil", help="Steuerliche Ausgangslage anzeigen oder erfassen.")
    p.add_argument("--bearbeiten", action="store_true", help="Profil im Dialog erfassen.")
    p.set_defaults(funktion=befehl_profil)

    p = unter.add_parser("hinzufuegen", help="Scans aufnehmen (Dateien oder Ordner).")
    p.add_argument("pfade", nargs="+")
    p.set_defaults(funktion=befehl_hinzufuegen)

    p = unter.add_parser("analyse", help="Dokumente inhaltlich pruefen lassen.")
    p.add_argument("--alle", action="store_true", help="Auch bereits analysierte Dokumente erneut pruefen.")
    p.add_argument("--dokument", help="Nur ein Dokument, Angabe der Kennung.")
    p.add_argument("--modell", help="Abweichendes Modell fuer die Dokumentanalyse.")
    p.add_argument("--parallel", type=int, default=3, help="Gleichzeitige Analysen, Standard 3.")
    p.set_defaults(funktion=befehl_analyse)

    p = unter.add_parser("trennen", help="Erkannten Sammelscan in Einzeldokumente zerlegen.")
    p.add_argument("dokument", help="Kennung des Dokuments.")
    p.set_defaults(funktion=befehl_trennen)

    p = unter.add_parser("status", help="Kurzer Ueberblick ueber die Arbeitsmappe.")
    p.set_defaults(funktion=befehl_status)

    p = unter.add_parser("liste", help="Alle Dokumente nach Anlagen sortiert auflisten.")
    p.set_defaults(funktion=befehl_liste)

    p = unter.add_parser("pruefen", help="Luecken, Chancen und Warnungen anzeigen.")
    p.set_defaults(funktion=befehl_pruefen)

    p = unter.add_parser("ordnen", help="Ablage aufbauen und Uebersicht fuer den Steuerberater erzeugen.")
    p.add_argument("--paket", action="store_true", help="Zusaetzlich ein ZIP fuer den Steuerberater packen.")
    p.add_argument("--gesamtauswertung", action="store_true", help="Abschliessende Auswertung durch das Modell.")
    p.add_argument("--ohne-ungeeignete", action="store_true", help="Nicht steuerrelevante Dokumente weglassen.")
    p.add_argument("--trotzdem", action="store_true", help="Auch bei nicht analysierten Dokumenten fortfahren.")
    p.set_defaults(funktion=befehl_ordnen)

    p = unter.add_parser("recht-zeigen", help="Hinterlegten Rechtsstand anzeigen.")
    p.add_argument("--jahr", type=int)
    p.set_defaults(funktion=befehl_recht_zeigen)

    p = unter.add_parser("recht-update", help="Rechtsstand recherchieren und Entwurf erzeugen.")
    p.add_argument("--jahr", type=int, required=True)
    p.set_defaults(funktion=befehl_recht_update)

    p = unter.add_parser("recht-uebernehmen", help="Geprueften Entwurf als Rechtsstand uebernehmen.")
    p.add_argument("--jahr", type=int, required=True)
    p.set_defaults(funktion=befehl_recht_uebernehmen)

    p = unter.add_parser("web", help="Lokale Weboberflaeche starten.")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5173)
    p.add_argument("--debug", action="store_true")
    p.set_defaults(funktion=befehl_web)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = parser_bauen()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.ausfuehrlich else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        return int(args.funktion(args))
    except (ArbeitsmappenFehler, rules.RegelFehler, KeinSchluessel) as fehler:
        print(str(fehler), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nAbgebrochen.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
