"""Kommandozeile des Steuer-Assistenten."""

from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import euer, gaps, organize, report, rules, taxonomy
from .formatierung import euro
from .analyze import (
    AUSWAHL_DOKUMENT,
    AUSWAHL_STRATEGIE,
    AnalyseFehler,
    Analysedienst,
    KeinSchluessel,
    modell_dokument_pruefen,
    modell_strategie_pruefen,
    schluessel_vorhanden,
)
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
        print(
            "\nBerufe und Betriebe im Haushalt, moeglichst konkret. Das entscheidet\n"
            "darueber, ob ein Beleg als betrieblich oder privat eingeordnet wird.\n"
            "Beispiel: 'Ehefrau betreibt ein Tuftingstudio (Teppiche, Kerzen, Workshops),\n"
            "Kleinunternehmerin; Ehemann angestellt im Vertrieb'.\n"
        )
        profil.taetigkeiten = _frage("Taetigkeiten", profil.taetigkeiten)
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
    if profil.taetigkeiten:
        print(f"  Taetigkeiten:   {profil.taetigkeiten}")
    else:
        print("  Taetigkeiten:   (nicht gesetzt - Belege koennen nicht betrieblich erkannt werden)")
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
    elif args.nachtragen:
        # Alles, was eine aeltere Fassung der Analyse gesehen hat. Ein
        # abgebrochener Lauf laesst sich damit fortsetzen, ohne die bereits
        # bezahlten Dokumente ein zweites Mal zu pruefen.
        zu_pruefen = [
            d
            for d in mappe.dokumente
            if d.analyse is None or d.status == STATUS_FEHLER or not d.analyse.ist_aktuell
        ]
    else:
        zu_pruefen = [d for d in mappe.dokumente if d.analyse is None or d.status == STATUS_FEHLER]

    if args.hoechstens and args.hoechstens > 0:
        zu_pruefen = zu_pruefen[: args.hoechstens]

    if args.ab_seite and not args.dokument:
        print(
            "--ab-seite prueft einen Ausschnitt eines langen Dokuments und ist deshalb "
            "nur zusammen mit --dokument <Kennung> sinnvoll.\n"
            "Die Kennungen zeigt: steuer liste",
            file=sys.stderr,
        )
        return 1

    if not zu_pruefen:
        veraltet = [d for d in mappe.dokumente if d.analyse and not d.analyse.ist_aktuell]
        print("Nichts zu analysieren. Mit --alle wird der gesamte Bestand neu geprueft.")
        if veraltet:
            print(
                f"{len(veraltet)} Dokumente stammen aus einer aelteren Fassung der Analyse. "
                "Nur diese nachholen mit: steuer analyse --nachtragen"
            )
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

    dienst = Analysedienst(
        modell_dokument=modell_dokument_pruefen(
            args.modell or mappe.einstellungen.get("modell_dokument")
        )
    )
    print(f"Analysiere {len(zu_pruefen)} Dokumente mit {dienst.modell_dokument} ...\n")

    def _einzeln(dokument: Dokument) -> tuple[Dokument, Exception | None]:
        try:
            analyse = dienst.dokument_analysieren(
                mappe.pfad_zu(dokument),
                dokument.medientyp,
                regelwerk,
                mappe.profil,
                dokument.notiz,
                ab_seite=args.ab_seite,
            )
            if args.ab_seite and dokument.analyse:
                # Der Ausschnitt ersetzt die Pruefung der vorderen Seiten nicht,
                # er ergaenzt sie. Was dort gefunden wurde, bleibt erhalten.
                _analysen_verbinden(dokument.analyse, analyse, args.ab_seite)
            dokument.analyse = analyse
            dokument.status = STATUS_ANALYSIERT
            dokument.fehler = ""
            return dokument, None
        except Exception as fehler:  # noqa: BLE001 - ein Dokument darf den Lauf nicht stoppen
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


def _analysen_verbinden(alt, neu, ab_seite: int) -> None:
    """Traegt die Erkenntnisse der vorderen Seiten in die Analyse des Ausschnitts nach.

    Ein langes Dokument wird abschnittsweise geprueft. Ohne dieses Zusammenfuehren
    wuerde der zweite Lauf den ersten stillschweigend loeschen.
    """
    neu.zusammenfassung = " ".join(
        teil for teil in (alt.zusammenfassung, neu.zusammenfassung) if teil
    ).strip()
    for feld in ("hinweise", "fehlende_nachweise", "optimierungshinweise"):
        vorher = list(getattr(alt, feld))
        nachher = getattr(neu, feld)
        for eintrag in vorher:
            if eintrag not in nachher:
                nachher.insert(0, eintrag)
    neu.positionen = list(alt.positionen) + list(neu.positionen)
    # Betraege der vorderen Seiten nicht verlieren, wenn der Ausschnitt keine nennt.
    for feld in ("betrag_gesamt", "betrag_abzugsfaehig", "datum", "steuerjahr", "aussteller"):
        if not getattr(neu, feld) and getattr(alt, feld):
            setattr(neu, feld, getattr(alt, feld))
    neu.hinweise.insert(
        0, f"Zusammengefuehrt aus zwei Laeufen: vordere Seiten und Ausschnitt ab Seite {ab_seite}."
    )


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
            modell = modell_strategie_pruefen(
                args.modell_strategie or mappe.einstellungen.get("modell_strategie")
            )
            print(f"Erstelle Gesamtauswertung mit {modell} ...")
            try:
                dienst = Analysedienst(modell_strategie=modell)
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


def befehl_euer(args: argparse.Namespace) -> int:
    """Erzeugt aus einer Gewerbemappe die Aufstellung fuer die EUeR."""
    mappe = _mappe_oeffnen(args)
    dokumente = mappe.dokumente
    if args.kategorie:
        dokumente = [d for d in dokumente if d.wirksame_kategorie == args.kategorie]
        if not dokumente:
            print(f"Keine Dokumente in der Kategorie {args.kategorie}.")
            return 1

    analysiert = [d for d in dokumente if d.analyse]
    if not analysiert:
        print("Keine analysierten Dokumente. Zuerst 'steuer analyse' ausfuehren.")
        return 1

    betriebsbelege = [d for d in analysiert if d.wirksame_kategorie == "selbstaendig"]
    if not betriebsbelege and not args.trotzdem:
        print(
            f"In dieser Mappe ({mappe.wurzel}) liegt kein einziges Dokument der Kategorie\n"
            "'selbstaendig'. Das spricht dafuer, dass es die private Steuermappe ist und\n"
            "nicht die Mappe des Betriebs.\n\n"
            "Eine Aufstellung aus privaten Unterlagen waere irrefuehrend: Ein Bruttoarbeitslohn\n"
            "sieht fuer das Werkzeug aus wie eine Betriebseinnahme.\n\n"
            "  Alle Arbeitsmappen finden:  find ~ -name steuer.json -not -path \"*/.*\"\n"
            "  In die richtige wechseln:   cd <Pfad>\n"
            "  Trotzdem hier auswerten:    steuer euer --trotzdem",
            file=sys.stderr,
        )
        return 1

    aufstellung = euer.aufstellen(analysiert, mappe.jahr)
    name = args.name or mappe.profil.name

    mappe.berichte.mkdir(parents=True, exist_ok=True)
    csv_pfad = mappe.berichte / f"euer-aufstellung-{mappe.jahr}.csv"
    md_pfad = mappe.berichte / f"euer-aufstellung-{mappe.jahr}.md"
    # BOM, damit Excel die Umlaute und das Semikolon richtig liest.
    csv_pfad.write_text(euer.csv_export(aufstellung), encoding="utf-8-sig")
    md_pfad.write_text(euer.markdown_bericht(aufstellung, name), encoding="utf-8")

    if aufstellung.nur_geraten:
        print(
            "ACHTUNG: Bei keinem Beleg war in der Analyse vermerkt, ob es sich um eine\n"
            "Einnahme oder eine Ausgabe handelt. Die Richtung wurde durchweg anhand von\n"
            "Stichworten geraten. Die folgenden Summen sind nicht belastbar.\n\n"
            "  Abhilfe: steuer analyse --alle   (danach steuer euer erneut)\n",
            file=sys.stderr,
        )

    print(f"Erfasste Belege: {aufstellung.anzahl_belege}")
    print(f"Betriebseinnahmen: {euro(aufstellung.summe_einnahmen)}")
    print(f"Betriebsausgaben:  {euro(aufstellung.summe_ausgaben)}")
    bezeichnung = "Verlust" if aufstellung.ist_verlust else "Gewinn"
    print(f"Vorlaeufiges Ergebnis: {bezeichnung} {euro(abs(aufstellung.ergebnis))}")
    if aufstellung.ungeklaert:
        print(
            f"\n{euer.belege(len(aufstellung.ungeklaert))} ohne klare Richtung "
            "(nicht in den Summen enthalten)."
        )
    if aufstellung.ohne_betrag:
        print(f"{euer.belege(len(aufstellung.ohne_betrag))} ohne erkennbaren Betrag.")
    if aufstellung.privat:
        print(
            f"{euer.belege(len(aufstellung.privat))} als private Unterlagen uebergangen "
            "(Arbeitslohn, Vorsorge, Kinder und aehnliches)."
        )
    print(f"\n  {md_pfad}\n  {csv_pfad}")
    return 0


def _kategorienverteilung(mappe: Arbeitsmappe) -> None:
    """Zeigt, wie sich die Dokumente tatsaechlich auf die Kategorien verteilen."""
    verteilung: dict[str, int] = {}
    jahre: dict[str, int] = {}
    for dokument in mappe.dokumente:
        kennung = dokument.wirksame_kategorie if dokument.analyse else "(nicht analysiert)"
        verteilung[kennung] = verteilung.get(kennung, 0) + 1
        if dokument.analyse:
            jahr = str(dokument.analyse.steuerjahr or "ohne Jahresangabe")
            jahre[jahr] = jahre.get(jahr, 0) + 1

    print(f"So verteilen sich die {len(mappe.dokumente)} Dokumente dieser Mappe:\n")
    for kennung, anzahl in sorted(verteilung.items(), key=lambda p: -p[1]):
        label = taxonomy.NACH_ID[kennung].label if kennung in taxonomy.NACH_ID else ""
        print(f"  {anzahl:>5}  {kennung:34} {label}")

    if jahre:
        print(f"\nNach Steuerjahr (Mappe ist fuer {mappe.jahr}):\n")
        for jahr, anzahl in sorted(jahre.items()):
            print(f"  {anzahl:>5}  {jahr}")

    print(
        "\nDie linke Spalte ist die Kennung fuer --kategorie. "
        "Ein Ordnername wie '22_Anlage_S_G_EUeR' ist nicht die Kennung."
    )


def befehl_ausgliedern(args: argparse.Namespace) -> int:
    """Verschiebt Dokumente nach Kategorie oder Steuerjahr in eine andere Mappe."""
    mappe = _mappe_oeffnen(args)
    if not args.kategorie and not args.fremdes_jahr:
        print(
            "Bitte angeben, was ausgegliedert werden soll:\n"
            "  --kategorie <Kennung>   z. B. selbstaendig\n"
            "  --fremdes-jahr          alles, was nicht ins Jahr der Mappe gehoert\n"
        )
        _kategorienverteilung(mappe)
        return 1

    unbekannt = [k for k in (args.kategorie or []) if k not in taxonomy.NACH_ID]
    if unbekannt:
        print(f"Unbekannte Kategorie: {', '.join(unbekannt)}", file=sys.stderr)
        return 1

    betroffen = []
    for dokument in mappe.dokumente:
        grund = ""
        if args.kategorie and dokument.wirksame_kategorie in args.kategorie:
            grund = taxonomy.kategorie(dokument.wirksame_kategorie).label
        elif (
            args.fremdes_jahr
            and dokument.analyse
            and dokument.analyse.steuerjahr
            and dokument.analyse.steuerjahr != mappe.jahr
        ):
            grund = f"Steuerjahr {dokument.analyse.steuerjahr}"
        if grund:
            betroffen.append((dokument, grund))

    if not betroffen:
        print("Kein Dokument passt auf diese Auswahl.\n")
        _kategorienverteilung(mappe)
        return 0

    print(f"{len(betroffen)} von {len(mappe.dokumente)} Dokumenten betroffen:\n")
    nach_grund: dict[str, int] = {}
    for _, grund in betroffen:
        nach_grund[grund] = nach_grund.get(grund, 0) + 1
    for grund, anzahl in sorted(nach_grund.items(), key=lambda p: -p[1]):
        print(f"  {anzahl:>5}  {grund}")

    if args.probelauf:
        print("\nProbelauf, es wurde nichts verschoben.")
        print("Zum Ausfuehren denselben Befehl ohne --probelauf und mit --nach <Pfad> aufrufen.")
        return 0

    if not args.nach:
        print("\nBitte mit --nach <Pfad> angeben, wohin die Dokumente sollen.", file=sys.stderr)
        return 1

    ziel_pfad = Path(args.nach).expanduser()
    if (ziel_pfad / "steuer.json").exists():
        ziel = Arbeitsmappe.laden(ziel_pfad)
        print(f"\nZielmappe: {ziel.wurzel} (vorhanden, Jahr {ziel.jahr})")
    else:
        profil = Profil(
            name=args.name or mappe.profil.name,
            veranlagungsjahr=args.jahr or mappe.jahr,
        )
        ziel = Arbeitsmappe.anlegen(ziel_pfad, args.jahr or mappe.jahr, profil)
        print(f"\nZielmappe: {ziel.wurzel} (neu angelegt)")

    verschoben = uebersprungen = 0
    for dokument, _ in betroffen:
        quelle = mappe.pfad_zu(dokument)
        if not quelle.exists():
            uebersprungen += 1
            continue
        if ziel.dokument_uebernehmen(dokument, quelle):
            mappe.dokument_entfernen(dokument.id, datei_loeschen=True)
            verschoben += 1
        else:
            uebersprungen += 1

    ziel.speichern()
    mappe.speichern()

    print(f"\n{verschoben} Dokumente verschoben, {uebersprungen} uebersprungen.")
    print(f"In dieser Mappe verbleiben {len(mappe.dokumente)} Dokumente.")
    print("\nDie Analysen wurden uebernommen, es ist keine erneute Pruefung noetig.")
    print(f"Zielmappe ansehen:  cd {ziel.wurzel} && steuer status")
    return 0


def befehl_dateien(args: argparse.Namespace) -> int:
    """Zeigt Groesse und Seitenzahl jeder Datei, um Ausreisser zu finden."""
    from .extract import MAX_PDF_SEITEN, seitenzahl

    mappe = _mappe_oeffnen(args)
    mappe.eingang_einlesen()
    mappe.speichern()
    if not mappe.dokumente:
        print("Noch keine Dokumente aufgenommen.")
        return 0

    print(f"{'Groesse':>10}  {'Seiten':>8}  Datei")
    print("-" * 78)

    auffaellig: list[tuple[str, str]] = []
    zeilen = []
    for dokument in mappe.dokumente:
        pfad = mappe.pfad_zu(dokument)
        if not pfad.exists():
            auffaellig.append((dokument.dateiname, "Originaldatei fehlt"))
            continue
        groesse = pfad.stat().st_size
        seiten = seitenzahl(pfad) if dokument.medientyp == "application/pdf" else None
        if dokument.medientyp == "application/pdf" and seiten is None:
            anzeige = "unlesbar"
            auffaellig.append(
                (dokument.dateiname, "Seitenzahl nicht lesbar - haeufigste Ursache fuer Abbrueche")
            )
        elif seiten is None:
            anzeige = "-"
        else:
            anzeige = str(seiten)
            if seiten > MAX_PDF_SEITEN:
                auffaellig.append(
                    (dokument.dateiname, f"{seiten} Seiten, nur die ersten {MAX_PDF_SEITEN} werden geprueft")
                )
        if groesse > 20_000_000:
            auffaellig.append((dokument.dateiname, f"{groesse / 1_000_000:.0f} MB, zu gross fuer die Analyse"))
        zeilen.append((groesse, f"{groesse / 1_000_000:9.1f} MB  {anzeige:>8}  {dokument.dateiname}"))

    for _, zeile in sorted(zeilen, reverse=True):
        print(zeile)

    print()
    if auffaellig:
        print("Auffaellig:")
        for name, grund in auffaellig:
            print(f"  {name}")
            print(f"      {grund}")
        print("\nSolche Dateien am besten je Beleg einzeln neu einscannen oder aufteilen.")
    else:
        print("Keine Auffaelligkeiten. Alle Dateien sind fuer die Analyse geeignet.")
    return 0


def befehl_typen(args: argparse.Namespace) -> int:
    """Verdichtet eine Kategorie auf ihre Dokumentarten.

    Bei mehreren hundert Belegen ist die Einzelliste unlesbar. Die Frage, ob in
    einem Topf etwas Verwertbares steckt, beantwortet die Verteilung der
    Dokumentarten schneller als jeder Dateiname.
    """
    mappe = _mappe_oeffnen(args)
    dokumente = [d for d in mappe.dokumente if d.analyse]
    if args.kategorie:
        dokumente = [d for d in dokumente if d.wirksame_kategorie == args.kategorie]
    if not dokumente:
        print("Keine analysierten Dokumente in dieser Auswahl.")
        return 1

    gruppen: dict[str, list[Dokument]] = {}
    for dokument in dokumente:
        typ = (dokument.analyse.dokumenttyp or "ohne Bezeichnung").strip()
        gruppen.setdefault(typ, []).append(dokument)

    titel = f" in {args.kategorie}" if args.kategorie else ""
    print(f"{len(dokumente)} Dokumente{titel}, nach Dokumentart:\n")
    print(f"{'Anzahl':>6}  {'Summe':>16}  {'Aussteller (Beispiele)':<34} Art")
    print("-" * 100)

    for typ, liste in sorted(gruppen.items(), key=lambda p: (-len(p[1]), p[0])):
        summe = sum(
            d.analyse.betrag_gesamt or d.analyse.betrag_abzugsfaehig or 0.0 for d in liste
        )
        aussteller = []
        for dokument in liste:
            name = (dokument.analyse.aussteller or "").strip()
            if name and name not in aussteller:
                aussteller.append(name)
            if len(aussteller) == 3:
                break
        beispiele = ", ".join(aussteller)[:33] or "-"
        print(f"{len(liste):>6}  {euro(summe) if summe else '':>16}  {beispiele:<34} {typ[:40]}")

    gesamt = sum(
        d.analyse.betrag_gesamt or d.analyse.betrag_abzugsfaehig or 0.0 for d in dokumente
    )
    print("-" * 100)
    print(f"{len(dokumente):>6}  {euro(gesamt):>16}  Summe ueber alle Arten")
    print(
        "\nEinzelne Dokumente einer Art ansehen: steuer liste --kategorie <Kennung>"
    )
    return 0


def befehl_liste(args: argparse.Namespace) -> int:
    mappe = _mappe_oeffnen(args)
    if not mappe.dokumente:
        print("Noch keine Dokumente aufgenommen.")
        return 0
    kategorien = taxonomy.KATEGORIEN
    if getattr(args, "kategorie", None):
        kategorien = [k for k in kategorien if k.id == args.kategorie]
    for kategorie in kategorien:
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
    p.add_argument(
        "--nachtragen",
        action="store_true",
        help="Nur Dokumente aus einer aelteren Fassung der Analyse nachholen. "
        "Setzt einen abgebrochenen Lauf fort, ohne Fertiges erneut zu bezahlen.",
    )
    p.add_argument(
        "--hoechstens",
        type=int,
        metavar="N",
        help="Hoechstens N Dokumente pruefen. Fuer einen Probelauf, um die Kosten abzuschaetzen.",
    )
    p.add_argument(
        "--modell",
        choices=[k for k, _, _ in AUSWAHL_DOKUMENT],
        help="Modell fuer die Dokumentanalyse.",
    )
    p.add_argument("--parallel", type=int, default=3, help="Gleichzeitige Analysen, Standard 3.")
    p.add_argument(
        "--ab-seite",
        type=int,
        metavar="N",
        help="Bei langen PDF den Abschnitt ab Seite N pruefen. Nur mit --dokument; "
        "das Ergebnis wird mit der bisherigen Analyse zusammengefuehrt.",
    )
    p.set_defaults(funktion=befehl_analyse)

    p = unter.add_parser("trennen", help="Erkannten Sammelscan in Einzeldokumente zerlegen.")
    p.add_argument("dokument", help="Kennung des Dokuments.")
    p.set_defaults(funktion=befehl_trennen)

    p = unter.add_parser("status", help="Kurzer Ueberblick ueber die Arbeitsmappe.")
    p.set_defaults(funktion=befehl_status)

    p = unter.add_parser(
        "dateien",
        help="Groesse und Seitenzahl aller Dateien anzeigen, um Ausreisser zu finden.",
    )
    p.set_defaults(funktion=befehl_dateien)

    p = unter.add_parser(
        "ausgliedern",
        help="Dokumente nach Kategorie oder Steuerjahr in eine andere Arbeitsmappe verschieben.",
    )
    p.add_argument(
        "--kategorie",
        action="append",
        metavar="KENNUNG",
        help="Kategorie, die verschoben wird. Mehrfach angebbar.",
    )
    p.add_argument(
        "--fremdes-jahr",
        action="store_true",
        help="Alle Dokumente verschieben, die in ein anderes Steuerjahr gehoeren.",
    )
    p.add_argument("--nach", metavar="PFAD", help="Zielmappe; wird bei Bedarf angelegt.")
    p.add_argument("--jahr", type=int, help="Veranlagungsjahr der neuen Zielmappe.")
    p.add_argument("--name", help="Name fuer die neue Zielmappe.")
    p.add_argument(
        "--probelauf",
        action="store_true",
        help="Nur anzeigen, was verschoben wuerde, ohne etwas zu aendern.",
    )
    p.set_defaults(funktion=befehl_ausgliedern)

    p = unter.add_parser("liste", help="Alle Dokumente nach Anlagen sortiert auflisten.")
    p.add_argument("--kategorie", choices=taxonomy.ids(), help="Nur diese Kategorie zeigen.")
    p.set_defaults(funktion=befehl_liste)

    p = unter.add_parser(
        "typen",
        help="Dokumentarten einer Kategorie zaehlen und summieren - Uebersicht bei vielen Belegen.",
    )
    p.add_argument("--kategorie", choices=taxonomy.ids(), help="Auf eine Kategorie beschraenken.")
    p.set_defaults(funktion=befehl_typen)

    p = unter.add_parser("pruefen", help="Luecken, Chancen und Warnungen anzeigen.")
    p.set_defaults(funktion=befehl_pruefen)

    p = unter.add_parser("ordnen", help="Ablage aufbauen und Uebersicht fuer den Steuerberater erzeugen.")
    p.add_argument("--paket", action="store_true", help="Zusaetzlich ein ZIP fuer den Steuerberater packen.")
    p.add_argument("--gesamtauswertung", action="store_true", help="Abschliessende Auswertung durch das Modell.")
    p.add_argument(
        "--modell-strategie",
        choices=[k for k, _, _ in AUSWAHL_STRATEGIE],
        help="Modell fuer die Gesamtauswertung.",
    )
    p.add_argument("--ohne-ungeeignete", action="store_true", help="Nicht steuerrelevante Dokumente weglassen.")
    p.add_argument("--trotzdem", action="store_true", help="Auch bei nicht analysierten Dokumenten fortfahren.")
    p.set_defaults(funktion=befehl_ordnen)

    p = unter.add_parser(
        "euer",
        help="Aufstellung der Betriebseinnahmen und -ausgaben fuer die Anlage EUeR erzeugen.",
    )
    p.add_argument(
        "--kategorie",
        choices=taxonomy.ids(),
        help="Nur Dokumente dieser Kategorie auswerten, fuer den Betrieb also 'selbstaendig'.",
    )
    p.add_argument("--name", help="Bezeichnung des Betriebs fuer den Bericht.")
    p.add_argument(
        "--trotzdem",
        action="store_true",
        help="Auch auswerten, wenn die Mappe nicht nach einer Betriebsmappe aussieht.",
    )
    p.set_defaults(funktion=befehl_euer)

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
