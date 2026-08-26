"""Kommandozeile des Steuer-Assistenten."""

from __future__ import annotations

import argparse
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import euer, gaps, organize, report, rules, stammdaten, taxonomy
from .formatierung import eingabewert, euro, zahl_lesen
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
    HERKUENFTE,
    HERKUNFT_LABEL,
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
        profil.anzahl_kinder = _int_frage("Anzahl Kinder", profil.anzahl_kinder) or 0
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

        unplausibel = profil.unplausible_werte()
        if unplausibel:
            print("\nDiese Angaben sehen nicht plausibel aus:", file=sys.stderr)
            for meldung in unplausibel:
                print(f"  {meldung}", file=sys.stderr)
            print(
                "\nNichts gespeichert. Bitte 'steuer profil --bearbeiten' erneut aufrufen "
                "und die Werte korrigieren.",
                file=sys.stderr,
            )
            return 1

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
    antwort = _frage(text, eingabewert(vorgabe))
    if not antwort:
        return None
    wert = zahl_lesen(antwort)
    if wert is None:
        print(f"  '{antwort}' ist keine Zahl, der bisherige Wert bleibt stehen.", file=sys.stderr)
        return vorgabe
    return wert


def _int_frage(text: str, vorgabe: int | None) -> int | None:
    wert = _zahl_frage(text, float(vorgabe) if vorgabe is not None else None)
    return int(wert) if wert is not None else None


def befehl_stammdaten(args: argparse.Namespace) -> int:
    """Zeigt und pflegt die jahresuebergreifenden Fortschreibungswerte."""
    mappe = _mappe_oeffnen(args)
    daten = mappe.stammdaten

    if args.aus:
        quelle = Arbeitsmappe.laden(Path(args.aus))
        uebernommen, zu_pruefen = quelle.stammdaten.fuer_neues_jahr(mappe.jahr)
        if not uebernommen.gesetzte():
            print(f"In {quelle.wurzel} sind keine Stammdaten hinterlegt.")
            return 1
        mappe._stammdaten = uebernommen
        pfad = mappe.stammdaten_speichern()
        print(f"{len(uebernommen.gesetzte())} Werte aus {quelle.wurzel.name} uebernommen: {pfad}")
        if zu_pruefen:
            print(
                "\nDiese Werte laufen nicht unbegrenzt weiter und sind zu pruefen:\n  "
                + "\n  ".join(zu_pruefen)
            )
        return 0

    if args.bearbeiten:
        print(
            "Stammdaten erfassen. Enter uebernimmt den bisherigen Wert,\n"
            "ein Minuszeichen loescht ihn.\n"
        )
        for vorlage in stammdaten.VORLAGEN:
            eintrag = daten.eintrag(vorlage.id)
            if vorlage.hinweis:
                print(f"  {vorlage.hinweis}")
            antwort = _frage(
                vorlage.label + (f" in {vorlage.einheit}" if vorlage.einheit else ""),
                str(eintrag.wert) if eintrag and eintrag.ist_gesetzt else "",
            )
            if antwort == "-":
                daten.entfernen(vorlage.id)
                print("  entfernt\n")
                continue
            if not antwort:
                print()
                continue
            wert: Any = antwort
            if vorlage.einheit in ("EUR", "prozent_pro_jahr"):
                gelesen = zahl_lesen(antwort)
                if gelesen is None:
                    print(f"  '{antwort}' ist keine Zahl, uebersprungen.\n", file=sys.stderr)
                    continue
                wert = gelesen
            quelle = _frage("  Fundstelle", eintrag.quelle if eintrag else "")
            daten.setzen(vorlage.id, wert, quelle=quelle, gilt_ab_jahr=mappe.jahr)
            print()
        pfad = mappe.stammdaten_speichern()
        print(f"Stammdaten gespeichert: {pfad}")
        return 0

    gesetzt = daten.gesetzte()
    print(f"Stammdaten der Mappe {mappe.wurzel.name} ({mappe.jahr})")
    print(f"Datei: {mappe.stammdaten_pfad}\n")
    if not gesetzt:
        print("Noch keine Werte hinterlegt.\n")
        print("Diese Werte stehen in keinem einzelnen Beleg und gehen sonst verloren:")
        for vorlage in stammdaten.VORLAGEN:
            print(f"  {vorlage.id:38} {vorlage.label}")
        print("\nErfassen mit: steuer stammdaten --bearbeiten")
        return 0

    for eintrag in gesetzt:
        einheit = f" {eintrag.einheit}" if eintrag.einheit else ""
        print(f"  {eintrag.label or eintrag.id}: {eintrag.wert}{einheit}")
        if eintrag.quelle:
            print(f"      Quelle: {eintrag.quelle}")
        if eintrag.bestaetigt_am:
            print(f"      bestaetigt am {eintrag.bestaetigt_am}")

    fehlend = daten.fehlende_vorlagen()
    if fehlend:
        print(f"\nNoch nicht hinterlegt ({len(fehlend)}):")
        for vorlage in fehlend:
            print(f"  {vorlage.id:38} {vorlage.label}")
    return 0


def befehl_jahre(args: argparse.Namespace) -> int:
    """Zeigt, wie sich der Bestand auf die Veranlagungsjahre verteilt."""
    mappe = _mappe_oeffnen(args)
    if not mappe.dokumente:
        print("Noch keine Dokumente aufgenommen.")
        return 0

    ansicht = mappe.jahresansicht()
    print(f"Arbeitsmappe {mappe.wurzel}  ·  Sicht auf {mappe.jahr}\n")
    for jahr, anzahl in sorted(mappe.jahresverteilung().items()):
        markierung = "  <- dieses Jahr" if jahr == str(mappe.jahr) else ""
        print(f"  {anzahl:>5}  {jahr}{markierung}")

    print(
        f"\n  In die Auswertung fuer {mappe.jahr} gehen {len(ansicht.eigene)} Dokumente ein."
    )
    if ansicht.fremde:
        print(
            f"  {len(ansicht.fremde)} gehoeren in andere Jahre und bleiben aussen vor -\n"
            "  sie bleiben aber im Bestand und stehen ihrem Jahr zur Verfuegung."
        )
    if ansicht.ohne_jahr:
        print(
            f"  {len(ansicht.ohne_jahr)} haben kein erkennbares Jahr und gehen in keine Summe ein.\n"
            "  Das Jahr laesst sich beim Aufnehmen mit --jahr angeben oder je Dokument\n"
            "  in der Weboberflaeche setzen."
        )
    return 0


# Die Begrenzungen (?<!\d) und (?!\d) sind wesentlich: Ohne sie liest das
# Muster aus dem unmoeglichen "32.01.2024" klaglos den 2. Januar heraus - eine
# falsche Zahl, die niemandem auffaellt.
DATUM_MUSTER = (
    # ISO-Datum, wie es Scan-Programme voranstellen: 2024-03-12_Rechnung.pdf
    re.compile(
        r"(?<!\d)(?P<jahr>(?:19|20)\d{2})-(?P<monat>0[1-9]|1[0-2])-(?P<tag>0[1-9]|[12]\d|3[01])(?!\d)"
    ),
    # Deutsche Schreibweise irgendwo im Namen: Rechnung vom 12.03.2024
    re.compile(
        r"(?<!\d)(?P<tag>0?[1-9]|[12]\d|3[01])\.(?P<monat>0?[1-9]|1[0-2])\.(?P<jahr>(?:19|20)\d{2})(?!\d)"
    ),
)


def datum_aus_dateiname(name: str) -> str | None:
    """Liest ein vollstaendiges Datum aus dem Dateinamen, sonst None.

    Bewusst nur vollstaendige Datumsangaben: Eine blosse Jahreszahl im Namen
    kann alles Moegliche sein - eine Rechnungsnummer, ein Modelljahr, ein
    Aktenzeichen. Ein Tag-Monat-Jahr-Muster ist dagegen eindeutig.
    """
    for muster in DATUM_MUSTER:
        treffer = muster.search(name)
        if treffer:
            return "{jahr}-{monat:0>2}-{tag:0>2}".format(**treffer.groupdict())
    return None


def befehl_jahr_aus_dateiname(args: argparse.Namespace) -> int:
    """Leitet das Steuerjahr aus einem ablesbaren Datum ab.

    Zwei Quellen: das Datum im Dateinamen, das viele Scan-Programme voranstellen,
    und ersatzweise das Belegdatum aus der Analyse. Beides ist abgelesen, nicht
    geschaetzt - wo nichts steht, bleibt das Jahr offen.
    """
    mappe = _mappe_oeffnen(args)
    gefunden: list[tuple] = []
    ohne_datum: list = []
    for dokument in mappe.dokumente:
        if dokument.gehoert_ins_jahr is not None and not args.auch_erkannte:
            continue
        # Zwei Quellen, beide abgelesen statt geraten. Der Dateiname hat
        # Vorrang: Ihn hat ein Mensch vergeben, das Belegdatum hat ein Modell
        # aus dem Scan gelesen.
        datum = datum_aus_dateiname(dokument.dateiname)
        quelle = "Dateiname"
        if not datum and dokument.analyse and dokument.analyse.datum:
            gelesen = str(dokument.analyse.datum).strip()[:10]
            if re.fullmatch(r"(?:19|20)\d{2}-\d{2}-\d{2}", gelesen):
                datum, quelle = gelesen, "Belegdatum"
        if datum:
            gefunden.append((dokument, datum, quelle))
        else:
            ohne_datum.append(dokument)

    if not gefunden:
        print("In keinem der betroffenen Dateinamen steht ein vollstaendiges Datum.")
        return 0

    verteilung: dict[str, int] = {}
    quellen: dict[str, int] = {}
    for _, datum, quelle in gefunden:
        jahr = datum[:4]
        verteilung[jahr] = verteilung.get(jahr, 0) + 1
        quellen[quelle] = quellen.get(quelle, 0) + 1

    herkunft = ", ".join(f"{anzahl} aus dem {quelle}" for quelle, anzahl in quellen.items())
    print(f"Fuer {len(gefunden)} Dokumente ist ein Datum ablesbar ({herkunft}).\nDaraus ergibt sich:\n")
    for jahr, anzahl in sorted(verteilung.items()):
        markierung = "  <- Jahr dieser Mappe" if jahr == str(mappe.jahr) else ""
        print(f"  {anzahl:>5}  {jahr}{markierung}")

    print("\n  Beispiele:")
    for dokument, datum, quelle in gefunden[:8]:
        print(f"    {datum}  {quelle:<11}  {dokument.dateiname[:48]}")
    if len(gefunden) > 8:
        print(f"    ... und {len(gefunden) - 8} weitere")

    if ohne_datum:
        print(
            f"\n  Bei {len(ohne_datum)} Dokumenten ist kein Datum ablesbar; sie bleiben ohne Jahr."
        )

    if args.probelauf:
        print("\nProbelauf, es wurde nichts veraendert.")
        print("Zum Ausfuehren denselben Befehl ohne --probelauf aufrufen.")
        return 0

    for dokument, datum, _ in gefunden:
        dokument.herkunft_jahr = int(datum[:4])
    mappe.speichern()
    ansicht = mappe.jahresansicht()
    print(f"\nGesetzt. In die Auswertung fuer {mappe.jahr} gehen jetzt {len(ansicht.eigene)} Dokumente ein.")
    if ansicht.ohne_jahr:
        print(f"{len(ansicht.ohne_jahr)} haben weiterhin kein Jahr.")
    return 0


def befehl_jahr_setzen(args: argparse.Namespace) -> int:
    """Traegt ein Steuerjahr fuer mehrere Dokumente auf einmal ein.

    Gedacht fuer den haeufigen Fall, dass ein Stapel erkennbar zu einem Jahr
    gehoert, die einzelnen Belege es aber nicht ausweisen - ein Kassenbon nennt
    selten ein Jahr. Die Angabe kommt vom Nutzer und ist damit keine Schaetzung
    des Werkzeugs; standardmaessig werden nur Dokumente angefasst, bei denen
    ueberhaupt kein Jahr erkennbar ist.
    """
    mappe = _mappe_oeffnen(args)
    betroffen = []
    for dokument in mappe.dokumente:
        if args.kategorie and dokument.wirksame_kategorie not in args.kategorie:
            continue
        if args.herkunft and dokument.herkunft != args.herkunft:
            continue
        if dokument.gehoert_ins_jahr is not None and not args.auch_erkannte:
            continue
        if dokument.herkunft_jahr == args.auf:
            continue
        betroffen.append(dokument)

    if not betroffen:
        print("Kein Dokument passt auf diese Auswahl.")
        return 0

    mit_erkanntem_jahr = [d for d in betroffen if d.analyse and d.analyse.steuerjahr]
    print(f"{len(betroffen)} von {len(mappe.dokumente)} Dokumenten bekommen das Jahr {args.auf}.")
    if mit_erkanntem_jahr:
        print(
            f"  Darunter {len(mit_erkanntem_jahr)}, bei denen die Analyse bereits ein Jahr "
            "gelesen hat.\n  Ihre Angabe setzt es ausser Kraft."
        )
    print("\n  Beispiele:")
    for dokument in betroffen[:8]:
        erkannt = dokument.analyse.steuerjahr if dokument.analyse else None
        zusatz = f"  (Analyse las {erkannt})" if erkannt else ""
        print(f"    {dokument.dateiname[:60]}{zusatz}")
    if len(betroffen) > 8:
        print(f"    ... und {len(betroffen) - 8} weitere")

    if args.probelauf:
        print("\nProbelauf, es wurde nichts veraendert.")
        print("Zum Ausfuehren denselben Befehl ohne --probelauf aufrufen.")
        return 0

    for dokument in betroffen:
        dokument.herkunft_jahr = args.auf
    mappe.speichern()
    ansicht = mappe.jahresansicht()
    print(f"\nGesetzt. In die Auswertung fuer {mappe.jahr} gehen jetzt {len(ansicht.eigene)} Dokumente ein.")
    print("Rueckgaengig: dieselben Dokumente in der Weboberflaeche einzeln leeren,")
    print("oder das Jahr erneut setzen.")
    return 0


def befehl_zusammenfuehren(args: argparse.Namespace) -> int:
    """Nimmt eine andere Arbeitsmappe in diese auf - die Gegenrichtung zu ausgliedern."""
    mappe = _mappe_oeffnen(args)
    quelle = Arbeitsmappe.laden(Path(args.quelle))
    if quelle.wurzel == mappe.wurzel:
        print("Quelle und Ziel sind dieselbe Mappe.", file=sys.stderr)
        return 1

    print(f"Quelle: {quelle.wurzel} ({len(quelle.dokumente)} Dokumente)")
    print(f"Ziel:   {mappe.wurzel} ({len(mappe.dokumente)} Dokumente)\n")
    if args.probelauf:
        vorhanden = {d.sha256 for d in mappe.dokumente}
        neu = [d for d in quelle.dokumente if d.sha256 not in vorhanden]
        print(f"{len(neu)} Dokumente wuerden uebernommen, {len(quelle.dokumente) - len(neu)} sind schon da.")
        print("Probelauf, es wurde nichts veraendert.")
        return 0

    uebernommen, uebersprungen = mappe.uebernehmen_aus(quelle)
    mappe.speichern()
    print(f"{uebernommen} Dokumente uebernommen, {uebersprungen} uebersprungen.")
    print("Die Analysen wurden mituebernommen, eine erneute Pruefung ist nicht noetig.")
    print(f"Die Quellmappe bleibt unveraendert: {quelle.wurzel}")
    return 0


def befehl_hinzufuegen(args: argparse.Namespace) -> int:
    mappe = _mappe_oeffnen(args)
    dateien = dateien_sammeln([Path(p) for p in args.pfade])
    if not dateien:
        print("Keine unterstuetzten Dateien gefunden.")
        return 1
    if args.herkunft:
        print(
            f"Stapel wird aufgenommen als: {HERKUNFT_LABEL[args.herkunft]}"
            + (f", Steuerjahr {args.jahr}" if args.jahr else "")
        )
    else:
        print(
            "Hinweis: Ohne --herkunft muss spaeter die Analyse entscheiden, wohin\n"
            "         die Belege gehoeren. Das kostet Geld und ist ungenauer als\n"
            "         Ihre eigene Angabe. Moegliche Werte: "
            + ", ".join(h for h, _ in HERKUENFTE)
        )

    neu = uebersprungen = 0
    for datei in dateien:
        try:
            dokument, ist_neu = mappe.datei_aufnehmen(
                datei, herkunft=args.herkunft or "", herkunft_jahr=args.jahr
            )
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
    if args.jahr and args.jahr != mappe.jahr:
        print(
            f"Der Stapel gehoert ins Jahr {args.jahr}, die Mappe ist fuer {mappe.jahr}.\n"
            "Diese Dokumente werden bei der Analyse uebersprungen und kosten nichts."
        )
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
        # Alles, was eine aeltere Fassung der Analyse gesehen hat oder einen
        # aelteren Wissensstand ueber den Haushalt. Ein abgebrochener Lauf und
        # eine Profilaenderung lassen sich damit nachholen, ohne die bereits
        # bezahlten und weiterhin gueltigen Dokumente erneut zu pruefen.
        zu_pruefen = mappe.nachzutragen()
    else:
        zu_pruefen = [d for d in mappe.dokumente if d.analyse is None or d.status == STATUS_FEHLER]

    # Belege, die der Nutzer selbst einem anderen Jahr zugeordnet hat, werden
    # nicht geprueft. Sie bleiben in der Mappe und stehen spaeteren Jahren zur
    # Verfuegung - nur bezahlt wird fuer sie jetzt nichts.
    fremdes_jahr = [
        d for d in zu_pruefen if d.herkunft_jahr and d.herkunft_jahr != mappe.jahr
    ]
    if fremdes_jahr and not args.dokument:
        zu_pruefen = [d for d in zu_pruefen if d not in fremdes_jahr]
        print(
            f"{len(fremdes_jahr)} Dokumente gehoeren laut Ihrer Angabe in ein anderes "
            f"Jahr und werden uebersprungen.\n"
        )

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
        veraltet = mappe.nachzutragen()
        print("Nichts zu analysieren. Mit --alle wird der gesamte Bestand neu geprueft.")
        if veraltet:
            print(
                f"{len(veraltet)} Dokumente wurden mit einem aelteren Stand geprueft. "
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
                herkunft=HERKUNFT_LABEL.get(dokument.herkunft, ""),
                stammdaten=mappe.stammdaten,
            )
            if args.ab_seite and dokument.analyse:
                # Der Ausschnitt ersetzt die Pruefung der vorderen Seiten nicht,
                # er ergaenzt sie. Was dort gefunden wurde, bleibt erhalten.
                _analysen_verbinden(dokument.analyse, analyse, args.ab_seite)
            analyse.kontext = mappe.kontext_pruefsumme()
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
    auswertung = gaps.auswerten(mappe.jahresansicht().eigene, regelwerk, mappe.profil, stammdaten=mappe.stammdaten)
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

    ansicht = mappe.jahresansicht()
    if ansicht.fremde or ansicht.ohne_jahr:
        print()
        if ansicht.fremde:
            teile = ", ".join(f"{anzahl}x {jahr}" for jahr, anzahl in ansicht.fremde_jahre().items())
            print(f"  {len(ansicht.fremde)} Dokumente gehoeren in andere Jahre ({teile}).")
        if ansicht.ohne_jahr:
            print(f"  {len(ansicht.ohne_jahr)} Dokumente ohne erkennbares Jahr.")
        print("  Sie bleiben im Bestand. Verteilung ansehen mit: steuer jahre")

    nachzutragen = mappe.nachzutragen()
    if nachzutragen:
        print(
            f"\n  {len(nachzutragen)} Dokumente wurden mit einem aelteren Stand geprueft.\n"
            "  Seitdem hat sich das Profil oder die Analyse geaendert; dieselben Belege\n"
            "  wuerden heute womoeglich anders eingeordnet.\n"
            "  Nachholen mit: steuer analyse --nachtragen"
        )
    return 0


def befehl_pruefen(args: argparse.Namespace) -> int:
    mappe = _mappe_oeffnen(args)
    regelwerk = _regelwerk(mappe)
    auswertung = gaps.auswerten(mappe.jahresansicht().eigene, regelwerk, mappe.profil, stammdaten=mappe.stammdaten)

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

    auswertung = gaps.auswerten(mappe.jahresansicht().eigene, regelwerk, mappe.profil, stammdaten=mappe.stammdaten)
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
                    [_bestandseintrag(d) for d in mappe.jahresansicht().eigene],
                    [b.als_dict() for b in auswertung.befunde],
                )
            except (AnalyseFehler, KeinSchluessel) as fehler:
                print(f"Gesamtauswertung fehlgeschlagen: {fehler}", file=sys.stderr)

    ablage = organize.ablage_erzeugen(mappe, ungeeignete_mitnehmen=not args.ohne_ungeeignete)
    mappe.speichern()
    berichte = report.berichte_schreiben(
        mappe.berichte,
        mappe.jahresansicht().eigene,
        auswertung,
        regelwerk,
        mappe.profil,
        modellauswertung,
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
    herkuenfte: dict[str, int] = {}
    for dokument in mappe.dokumente:
        kennung = dokument.wirksame_kategorie if dokument.analyse else "(nicht analysiert)"
        verteilung[kennung] = verteilung.get(kennung, 0) + 1
        jahr = str(dokument.gehoert_ins_jahr or "ohne Jahresangabe")
        jahre[jahr] = jahre.get(jahr, 0) + 1
        quelle = dokument.herkunft or "(nicht angegeben)"
        herkuenfte[quelle] = herkuenfte.get(quelle, 0) + 1

    print(f"So verteilen sich die {len(mappe.dokumente)} Dokumente dieser Mappe:\n")
    for kennung, anzahl in sorted(verteilung.items(), key=lambda p: -p[1]):
        label = taxonomy.NACH_ID[kennung].label if kennung in taxonomy.NACH_ID else ""
        print(f"  {anzahl:>5}  {kennung:34} {label}")

    if len(herkuenfte) > 1 or "(nicht angegeben)" not in herkuenfte:
        print("\nNach Herkunft (Ihre Angabe beim Aufnehmen):\n")
        for quelle, anzahl in sorted(herkuenfte.items(), key=lambda p: -p[1]):
            print(f"  {anzahl:>5}  {HERKUNFT_LABEL.get(quelle, quelle)}")

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
    if not args.kategorie and not args.fremdes_jahr and not args.herkunft:
        print(
            "Bitte angeben, was ausgegliedert werden soll:\n"
            "  --herkunft <Kennung>    z. B. gewerbe, nach Ihrer Angabe beim Aufnehmen\n"
            "  --kategorie <Kennung>   z. B. selbstaendig, nach der Einordnung der Analyse\n"
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
        if args.herkunft and dokument.herkunft == args.herkunft:
            grund = HERKUNFT_LABEL[args.herkunft]
        elif args.kategorie and dokument.wirksame_kategorie in args.kategorie:
            grund = taxonomy.kategorie(dokument.wirksame_kategorie).label
        elif (
            args.fremdes_jahr
            and dokument.gehoert_ins_jahr
            and dokument.gehoert_ins_jahr != mappe.jahr
        ):
            grund = f"Steuerjahr {dokument.gehoert_ins_jahr}"
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


# Wonach sich die offenen Punkte buendeln lassen. Das Modell formuliert jede
# Fehlanzeige neu ("Kontoauszug mit tatsaechlicher Abbuchung der vier Raten"),
# weshalb wortgleiches Gruppieren nichts zusammenbringt: 180 Einzelangaben
# ergaben 180 Gruppen. Entscheidend ist nicht der Wortlaut, sondern die
# Besorgung dahinter - und die wiederholt sich sehr wohl.
# Reihenfolge = Vorrang; die erste zutreffende Zeile gewinnt.
# Die Muster binden nur am Wortanfang: Im Deutschen wachsen die Woerter
# hinten weiter ("Kontoauszuege", "Versicherungsbestaetigung"), eine
# schliessende Wortgrenze wuerde genau diese Faelle verfehlen.
OFFEN_THEMEN: tuple[tuple[str, str, str], ...] = (
    ("frage", r"\b(kl[aä]rung|klarstellung|zuordnung|angabe, ob|klären, ob|umrechnen)",
     "Rueckfrage - keine Besorgung, sondern eine Auskunft von Ihnen"),
    ("zahlung", r"\b(kontoausz|zahlungsnachweis|[uü]berweisungsbeleg|lastschrift|paypal|"
                r"abbuchung|einzahlungsquittung|zahlungsbest[aä]tigung)",
     "Zahlungsnachweis - Kontoauszug oder Ueberweisungsbeleg"),
    ("lohn", r"\b(lohnsteuerbescheinigung|gehaltsabrechnung|lohnabrechnung|"
             r"lohn-/gehaltsabrechnung)",
     "Lohnsteuerbescheinigung oder Gehaltsabrechnung"),
    ("nebenkosten", r"\b(nebenkostenabrechnung|betriebskostenabrechnung|grundsteuerbescheid)",
     "Nebenkosten- oder Betriebskostenabrechnung"),
    ("mietvertrag", r"\b(mietvertrag|renovierungsklausel|renovierungspflicht|"
                    r"renovierungsverpflichtung|kaution|[uü]bergabeprotokoll)",
     "Mietvertrag, Kautions- oder Uebergabeunterlagen"),
    ("arzt", r"\b([aä]rztliche|attest|verordnung|rezept|medizinische[rn]? notwendigkeit|"
             r"krankenkasse|erstattung)",
     "Aerztliche Verordnung oder Nachweis der Erstattung"),
    ("beruflich", r"\b(berufliche[rn]? (veranlassung|nutzung)|betriebliche[rn]? nutzung|"
                  r"nutzungsanteil|nutzungsnachweis|fahrtenbuch|arbeitgeberbest[aä]tigung)",
     "Nachweis der beruflichen Veranlassung oder Nutzung"),
    ("umzug", r"\b(umzugskosten|doppelte[rn]? miete|doppelmiete|bukg)",
     "Umzugsunterlagen"),
    ("betrieb", r"\b(e[uü]er|gesch[aä]ftskonto|eingangsrechnung|ausgangsrechnung|"
                r"abschreibungstabelle|geringwertige)",
     "Unterlagen aus dem Gewerbe Ihrer Frau"),
    ("versicherung", r"\b(versicherung|direktversicherung|beitrags|jahrespr[aä]mie|"
                     r"entgeltumwandlung|bav)",
     "Bescheinigung der Versicherung"),
    ("rechnung", r"\b(rechnung|aufschl[uü]sselung|aufteilung|detailaufl|leistungsnachweis|"
                 r"beitragsrechnung)",
     "Rechnung oder Aufschluesselung der Posten"),
)


def _belegname(dokument: Dokument) -> str:
    """Der Name, unter dem der Nutzer den Beleg wiedererkennt."""
    analyse = dokument.analyse
    if analyse and analyse.dokumenttyp:
        aussteller = (analyse.aussteller or "").strip()
        return f"{analyse.dokumenttyp}, {aussteller}" if aussteller else analyse.dokumenttyp
    return dokument.zieldateiname or dokument.dateiname


def _kurz(text: str, breite: int) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    return text if len(text) <= breite else text[: breite - 1].rstrip() + "…"


def _offen_thema(text: str) -> tuple[str, str]:
    """Ordnet eine Fehlanzeige der Besorgung zu, die sie aufloest."""
    vereinfacht = re.sub(r"\s+", " ", text.strip().lower())
    for kennung, muster, beschriftung in OFFEN_THEMEN:
        if re.search(muster, vereinfacht):
            return kennung, beschriftung
    return "sonstiges", "Sonstiges - Einzelfaelle ohne gemeinsame Ursache"


def befehl_offen(args: argparse.Namespace) -> int:
    """Buendelt die offenen Punkte nach der Besorgung, die sie aufloest.

    Eine Liste mit 180 Fehlanzeigen ist keine Arbeitsanweisung, sondern eine
    Zumutung. Interessant ist nicht, welcher Beleg etwas vermisst, sondern
    welche Besorgung sich wiederholt: Ein einziger Kontoauszug kann vierzig
    Belege auf einmal klaeren.
    """
    mappe = _mappe_oeffnen(args)
    ansicht = mappe.jahresansicht()
    dokumente = [d for d in ansicht.eigene if d.analyse]
    if not dokumente:
        print(f"Keine analysierten Dokumente fuer {mappe.jahr}.")
        return 1

    gruppen: dict[str, list[tuple[str, Dokument]]] = {}
    beschriftungen: dict[str, str] = {}
    for dokument in dokumente:
        for fehlend in dokument.analyse.fehlende_nachweise:
            text = fehlend.strip()
            if not text:
                continue
            kennung, beschriftung = _offen_thema(text)
            beschriftungen[kennung] = beschriftung
            gruppen.setdefault(kennung, []).append((text, dokument))

    if not gruppen:
        print(f"Kein Dokument aus {mappe.jahr} vermisst einen Nachweis.")
        return 0

    if args.thema:
        if args.thema not in gruppen:
            vorhanden = ", ".join(sorted(gruppen))
            print(f"Kein Thema '{args.thema}'. Vorhanden: {vorhanden}", file=sys.stderr)
            return 1
        eintraege = gruppen[args.thema]
        print(f"{beschriftungen[args.thema]}  ({len(eintraege)} Punkte)\n")
        breite = 999 if args.voll else 62
        for nummer, (text, dokument) in enumerate(
            sorted(eintraege, key=lambda p: p[1].dateiname), start=1
        ):
            print(f"{nummer:>4}. {_kurz(_belegname(dokument), 34)}  {_kurz(text, breite)}")
        if not args.voll:
            print("\nGanze Saetze: dieselbe Zeile mit --voll")
        if args.thema == "frage":
            print("Der Reihe nach beantworten: steuer beantworten")
        return 0

    einzelangaben = sum(len(e) for e in gruppen.values())
    betroffen = {d.id for eintraege in gruppen.values() for _, d in eintraege}
    print(
        f"{len(dokumente)} Dokumente aus {mappe.jahr}, davon {len(betroffen)} mit offenen "
        f"Punkten.\n{einzelangaben} Einzelangaben, gebuendelt zu {len(gruppen)} Besorgungen.\n"
    )
    print(f"{'Belege':>6}  {'Summe':>16}  {'Kennung':<12} Was zu besorgen ist")
    print("-" * 100)

    # Ein Dokument kann mehrere Fehlanzeigen desselben Themas tragen. Gezaehlt,
    # summiert und sortiert wird nach Dokumenten - sonst steht in der Spalte
    # "Belege" eine andere Zahl, als die Reihenfolge behauptet.
    zeilen = []
    for kennung, eintraege in gruppen.items():
        je_dokument = {d.id: d for _, d in eintraege}
        summe = sum(
            d.analyse.betrag_abzugsfaehig or d.analyse.betrag_gesamt or 0.0
            for d in je_dokument.values()
        )
        zeilen.append((len(je_dokument), summe, kennung))

    for anzahl, summe, kennung in sorted(zeilen, key=lambda z: (-z[0], z[2])):
        print(
            f"{anzahl:>6}  {euro(summe) if summe else '':>16}  "
            f"{kennung:<12} {beschriftungen[kennung]}"
        )

    print("-" * 100)
    print(
        "\nJede Zeile ist eine Besorgung, nicht hunderte. Die Summe ist der Betrag\n"
        "der betroffenen Belege - nicht das, was sie an Steuer bringen.\n"
        "Einzelne Punkte eines Themas: steuer offen --thema <Kennung>"
    )
    return 0


# Woerter, mit denen eine Antwort nie beginnt, eine Konsolenzeile aber sehr wohl.
BEFEHLSWOERTER = frozenset(
    "git steuer cd source pip python ls cat sudo export unzip xdg-open mkdir rm chmod".split()
)


def _sieht_aus_wie_befehl(text: str) -> bool:
    """Erkennt eine versehentlich eingefuegte Konsolenzeile.

    Beim Einfuegen mehrerer Zeilen verschluckt die Konsole den Zeilenumbruch,
    und die zweite Zeile landet in der naechsten Eingabeaufforderung. So wurde
    aus der Antwort zur Kfz-Versicherung schon einmal
    "git pull origin ... && steuer beantworten".
    """
    erstes = text.strip().split(maxsplit=1)[0].lower() if text.strip() else ""
    return erstes in BEFEHLSWOERTER


def befehl_beantworten(args: argparse.Namespace) -> int:
    """Stellt die offenen Rueckfragen einzeln und haelt die Antworten fest.

    Eine Rueckfrage braucht kein Dokument, sondern eine Auskunft: War die Fahrt
    beruflich? Gehoert das Abo zur Wohnungssuche? Als Textwand in der Konsole
    ist das unbeantwortbar. Einzeln gestellt, mit dem Beleg davor, ist es eine
    Minute Arbeit je Frage.

    Die Antwort landet in der Notiz des Belegs. Von dort geht sie in den Bericht
    fuer den Steuerberater und in eine spaetere Neuanalyse ein.
    """
    mappe = _mappe_oeffnen(args)
    dokumente = [d for d in mappe.jahresansicht().eigene if d.analyse]

    aufgaben: list[tuple[Dokument, list[str], float]] = []
    uebergangen = 0
    uebergangene_summe = 0.0
    nur = (args.nur or "").strip().lower()
    for dokument in dokumente:
        # Angezeigt wird der aufbereitete Name, gesucht werden muss aber auch im
        # Originalnamen - und im Dokumenttyp, denn der steht in der Kopfzeile.
        if nur and not any(
            nur in feld.lower()
            for feld in (
                dokument.id,
                dokument.dateiname,
                dokument.zieldateiname,
                dokument.analyse.dokumenttyp,
                dokument.analyse.aussteller,
            )
            if feld
        ):
            continue
        fragen = [
            text.strip()
            for text in dokument.analyse.fehlende_nachweise
            if text.strip() and _offen_thema(text)[0] == args.thema
        ]
        # Wer gezielt einen Beleg aufruft, will ihn sehen - auch wenn schon eine
        # Antwort daran haengt und auch wenn der Betrag klein ist.
        if not fragen or (dokument.notiz and not (args.erneut or nur)):
            continue
        betrag = abs(
            float(dokument.analyse.betrag_abzugsfaehig or dokument.analyse.betrag_gesamt or 0.0)
        )
        if betrag < args.ab_betrag and not nur:
            uebergangen += 1
            uebergangene_summe += betrag
            continue
        aufgaben.append((dokument, fragen, betrag))

    # Der teuerste Beleg zuerst: Eine Frage zu einem Abo ueber 29,99 EUR ist
    # dieselbe Minute Arbeit wert wie eine zu 35.000 EUR Darlehenszinsen, bringt
    # aber ein Tausendstel. So kann jederzeit aufgehoert werden, ohne dass etwas
    # Wichtiges unbeantwortet zurueckbleibt.
    aufgaben.sort(key=lambda a: (-a[2], a[0].dateiname))

    if not aufgaben:
        if nur:
            print(f"Kein Beleg zu '{args.nur}' mit einer offenen Frage unter '{args.thema}'.")
            print("Gespeicherte Antworten ansehen: steuer anmerkungen")
            return 1
        print(f"Nichts offen unter '{args.thema}'.")
        if uebergangen:
            print(
                f"{uebergangen} Fragen betreffen Betraege unter {euro(args.ab_betrag)} "
                f"(zusammen {euro(uebergangene_summe)}). Auch die stellen: --ab-betrag 0"
            )
        vorhanden = sum(1 for d in dokumente if d.notiz)
        if vorhanden and not args.erneut:
            print(f"{vorhanden} Belege haben bereits eine Anmerkung. Erneut vorlegen: --erneut")
        return 0

    print(
        f"{len(aufgaben)} offene Punkte unter '{args.thema}', der teuerste Beleg zuerst.\n"
        "Antwort eingeben und Enter. Leer lassen = ueberspringen. "
        "'-' loescht eine Anmerkung. 'x' = abbrechen.\n"
    )
    if uebergangen:
        print(
            f"({uebergangen} weitere Fragen betreffen Betraege unter {euro(args.ab_betrag)}, "
            f"zusammen {euro(uebergangene_summe)}. Mit --ab-betrag 0 kommen sie dazu.)\n"
        )

    beantwortet = 0
    for nummer, (dokument, fragen, betrag) in enumerate(aufgaben, start=1):
        analyse = dokument.analyse
        kopf = f"[{nummer}/{len(aufgaben)}] {_belegname(dokument)}"
        if betrag:
            kopf += f"  ({euro(betrag)})"
        print(kopf)
        print(f"        Datei: {dokument.zieldateiname or dokument.dateiname}")
        if analyse.zusammenfassung:
            print(f"        {_kurz(analyse.zusammenfassung, 90)}")
        for frage in fragen:
            print(f"        ? {frage}")
        if dokument.notiz:
            print(f"        bisher: {dokument.notiz}")
        try:
            antwort = input("        > ").strip()
        except EOFError:
            print("\nAbgebrochen.")
            break
        print()
        if antwort.lower() == "x":
            print("Abgebrochen.")
            break
        if not antwort:
            continue
        if _sieht_aus_wie_befehl(antwort):
            print(
                "        Das sieht nach einem Konsolenbefehl aus und wurde nicht\n"
                "        gespeichert. Beim Einfuegen mehrerer Zeilen landet die zweite\n"
                "        hier. Der Beleg kommt beim naechsten Lauf wieder.\n"
            )
            continue
        dokument.notiz = "" if antwort == "-" else antwort
        beantwortet += 1
        # Nach jeder Antwort sichern: ein Abbruch mittendrin darf nichts kosten.
        mappe.speichern()

    print(f"{beantwortet} Antworten festgehalten.")
    if beantwortet:
        print(
            "Sie stehen im Bericht unter dem jeweiligen Beleg.\n"
            "In die Uebersicht uebernehmen: steuer ordnen --paket"
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


def befehl_anmerkungen(args: argparse.Namespace) -> int:
    """Zeigt, was tatsaechlich als Anmerkung gespeichert ist.

    Wer ueber Wochen in kurzen Abschnitten arbeitet, muss nachsehen koennen, was
    davon angekommen ist. Ohne diese Anzeige bleibt nur der Glaube daran, und
    eine verlorene Antwort faellt erst dem Steuerberater auf.
    """
    mappe = _mappe_oeffnen(args)
    ansicht = mappe.jahresansicht()
    mit_notiz = [d for d in ansicht.eigene if d.notiz]

    offen = 0
    for dokument in ansicht.eigene:
        if not dokument.analyse or dokument.notiz:
            continue
        if any(_offen_thema(f)[0] == "frage" for f in dokument.analyse.fehlende_nachweise):
            offen += 1

    if not mit_notiz:
        print(f"Keine Anmerkungen gespeichert (Veranlagung {mappe.jahr}).")
        if offen:
            print(f"{offen} Rueckfragen warten. Beantworten mit: steuer beantworten")
        return 0

    print(f"{len(mit_notiz)} Anmerkungen, Veranlagung {mappe.jahr}:\n")
    for dokument in sorted(mit_notiz, key=lambda d: d.dateiname):
        analyse = dokument.analyse
        betrag = (analyse.betrag_abzugsfaehig or analyse.betrag_gesamt) if analyse else None
        kopf = _belegname(dokument)
        if betrag:
            kopf += f"  ({euro(betrag)})"
        print(f"  {kopf}")
        print(f"      {dokument.notiz}")
        if _sieht_aus_wie_befehl(dokument.notiz):
            print("      ACHTUNG: sieht nach einer eingefuegten Konsolenzeile aus.")
        print()

    print(f"{offen} Rueckfragen sind noch offen.")
    if offen:
        print("Weiter mit: steuer beantworten")
    print("Aendern oder loeschen: steuer beantworten --erneut ('-' loescht)")
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

    p = unter.add_parser(
        "stammdaten",
        help="Jahresuebergreifende Werte wie die Gebaeude-AfA anzeigen oder pflegen.",
    )
    p.add_argument("--bearbeiten", action="store_true", help="Werte einzeln erfassen.")
    p.add_argument(
        "--aus",
        metavar="MAPPE",
        help="Werte aus einer anderen Arbeitsmappe uebernehmen und fortschreiben.",
    )
    p.set_defaults(funktion=befehl_stammdaten)

    p = unter.add_parser("hinzufuegen", help="Scans aufnehmen (Dateien oder Ordner).")
    p.add_argument(
        "--herkunft",
        choices=[h for h, _ in HERKUENFTE],
        help="Wem der Stapel gehoert. Ihre Angabe hat Vorrang vor der Analyse.",
    )
    p.add_argument(
        "--jahr",
        type=int,
        help="Steuerjahr des Stapels. Fremde Jahre werden nicht analysiert und kosten nichts.",
    )
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
    p.add_argument(
        "--herkunft",
        choices=[h for h, _ in HERKUENFTE],
        help="Alle Dokumente dieser Herkunft verschieben, nach Ihrer Angabe beim Aufnehmen.",
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

    p = unter.add_parser(
        "jahre", help="Verteilung des Bestands auf die Veranlagungsjahre anzeigen."
    )
    p.set_defaults(funktion=befehl_jahre)

    p = unter.add_parser(
        "jahr-aus-dateiname",
        help="Das Steuerjahr aus Dateiname oder Belegdatum ableiten.",
    )
    p.add_argument(
        "--auch-erkannte", action="store_true",
        help="Auch Dokumente ueberschreiben, bei denen bereits ein Jahr bekannt ist.",
    )
    p.add_argument("--probelauf", action="store_true", help="Nur anzeigen, was passieren wuerde.")
    p.set_defaults(funktion=befehl_jahr_aus_dateiname)

    p = unter.add_parser(
        "jahr-setzen",
        help="Ein Steuerjahr fuer viele Dokumente auf einmal eintragen.",
    )
    p.add_argument("--auf", type=int, required=True, metavar="JAHR", help="Das zu setzende Jahr.")
    p.add_argument(
        "--kategorie", action="append", choices=taxonomy.ids(), metavar="KENNUNG",
        help="Nur diese Kategorie. Mehrfach angebbar.",
    )
    p.add_argument(
        "--herkunft", choices=[h for h, _ in HERKUENFTE],
        help="Nur Dokumente dieser Herkunft.",
    )
    p.add_argument(
        "--auch-erkannte", action="store_true",
        help="Auch Dokumente ueberschreiben, bei denen die Analyse bereits ein Jahr gelesen hat.",
    )
    p.add_argument("--probelauf", action="store_true", help="Nur anzeigen, was passieren wuerde.")
    p.set_defaults(funktion=befehl_jahr_setzen)

    p = unter.add_parser(
        "zusammenfuehren",
        help="Eine andere Arbeitsmappe in diese aufnehmen, samt Analysen.",
    )
    p.add_argument("quelle", help="Pfad der Mappe, die uebernommen werden soll.")
    p.add_argument(
        "--probelauf", action="store_true", help="Nur anzeigen, was uebernommen wuerde."
    )
    p.set_defaults(funktion=befehl_zusammenfuehren)

    p = unter.add_parser("liste", help="Alle Dokumente nach Anlagen sortiert auflisten.")
    p.add_argument("--kategorie", choices=taxonomy.ids(), help="Nur diese Kategorie zeigen.")
    p.set_defaults(funktion=befehl_liste)

    p = unter.add_parser(
        "typen",
        help="Dokumentarten einer Kategorie zaehlen und summieren - Uebersicht bei vielen Belegen.",
    )
    p.add_argument("--kategorie", choices=taxonomy.ids(), help="Auf eine Kategorie beschraenken.")
    p.set_defaults(funktion=befehl_typen)

    p = unter.add_parser(
        "offen",
        help="Offene Punkte nach Ursache buendeln - zeigt, welche Besorgung am meisten bringt.",
    )
    p.add_argument(
        "--thema",
        help="Einzelne Punkte eines Themas auflisten (Kennung aus der Uebersicht).",
    )
    p.add_argument("--voll", action="store_true", help="Ganze Saetze statt gekuerzter Zeilen.")
    p.set_defaults(funktion=befehl_offen)

    p = unter.add_parser(
        "beantworten",
        help="Offene Rueckfragen einzeln stellen und die Antworten festhalten.",
    )
    p.add_argument(
        "--thema",
        default="frage",
        help="Welches Thema abgearbeitet wird (Standard: frage).",
    )
    p.add_argument(
        "--erneut",
        action="store_true",
        help="Auch Belege vorlegen, zu denen schon eine Anmerkung vorliegt.",
    )
    p.add_argument(
        "--ab-betrag",
        type=float,
        default=50.0,
        help="Nur Belege ab diesem Betrag vorlegen (Standard: 50 EUR, 0 = alle).",
    )
    p.add_argument(
        "--nur",
        help="Nur einen Beleg vorlegen - Anfang der Kennung oder Teil des Dateinamens. "
        "Ignoriert Betragsgrenze und vorhandene Anmerkung.",
    )
    p.set_defaults(funktion=befehl_beantworten)

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

    p = unter.add_parser(
        "anmerkungen",
        help="Zeigen, welche eigenen Antworten gespeichert sind.",
    )
    p.set_defaults(funktion=befehl_anmerkungen)

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
