"""Buendelung der offenen Punkte.

Die Formulierungen stammen woertlich aus einem echten Bestand: Das Modell
schreibt jede Fehlanzeige neu, weshalb wortgleiches Gruppieren nichts
zusammenbringt - 180 Einzelangaben ergaben 180 Gruppen.
"""

import argparse
from pathlib import Path

import pytest

from steuer.cli import OFFEN_THEMEN, _offen_thema, befehl_offen
from steuer.models import Analyse
from steuer.workspace import Arbeitsmappe

# Woertliche Fehlanzeigen aus dem Bestand, je mit der Besorgung, die sie aufloest.
ECHTE_FAELLE = [
    ("Kontoauszug mit tatsaechlicher Abbuchung der vier Raten (optional)", "zahlung"),
    ("Zahlungsnachweis (Kontoauszug/Ueberweisungsbeleg)", "zahlung"),
    ("Nachweis der tatsächlichen PayPal-Abbuchung/Kontoauszug", "zahlung"),
    ("Kontoauszüge oder Einzahlungsquittungen zum Nachweis der tatsächlichen", "zahlung"),
    ("Lohnsteuerbescheinigung 1. FC Köln GmbH & Co. KGaA (64.954,50 EUR) fehlt", "lohn"),
    ("Nebenkostenabrechnung Leipzig fehlt noch laut Notiz", "nebenkosten"),
    ("Grundsteuerbescheid der Gemeinde Halstenbek für 2024", "nebenkosten"),
    ("Mietvertrag Leipzig mit Renovierungsklausel", "mietvertrag"),
    ("Übergabeprotokoll und Abrechnung der Kaution", "mietvertrag"),
    ("Ärztliche Verordnung/Attest für die Heilpraktikerbehandlung", "arzt"),
    ("Nachweis über (Nicht-)Erstattung durch die Krankenkasse", "arzt"),
    ("Fahrtenbuch oder Nutzungsnachweis, falls anteilige Werbungskosten", "beruflich"),
    ("Nachweis/Begründung der beruflichen Veranlassung (z.B. Arbeitgeberbestätigung)", "beruflich"),
    ("Belege zu Umzugskosten und doppelter Miete für den Werbungskostenabzug", "umzug"),
    ("Kontoauszuege Geschaeftskonto 2024", "zahlung"),
    ("EUER 2024 als PDF-Export (fuer VZ 2024 angefordert)", "betrieb"),
    # Beitragsuebersicht des Versicherers: die Besorgung ist die Versicherung,
    # nicht die Bank - "Jahreskontoauszug" ist hier nur das Wort dafuer.
    ("Jahreskontoauszug/Beitragsübersicht 2024 des Versicherers", "versicherung"),
    ("Versicherungsbestätigung mit konkretem Versicherungsbeginn", "versicherung"),
    ("Anlage mit Detailauflistung der erbrachten Leistungen", "rechnung"),
    ("Klärung der Differenz von 1.002 € zwischen App-Export und Auswertung", "frage"),
    ("Zuordnung zu einer konkreten Fahrt (Datum, Start/Ziel, Zweck)", "frage"),
    ("USD-Betrag in EUR umrechnen (Wechselkurs am Zahlungstag)", "frage"),
]


@pytest.mark.parametrize("text,erwartet", ECHTE_FAELLE)
def test_echte_fehlanzeigen_finden_ihre_besorgung(text, erwartet):
    kennung, _ = _offen_thema(text)
    assert kennung == erwartet, f"{text!r} landete unter {kennung!r}"


def test_hoechstens_ein_fuenftel_bleibt_unsortiert():
    """Landet zu viel unter 'sonstiges', taugt die Buendelung nicht."""
    kennungen = [_offen_thema(text)[0] for text, _ in ECHTE_FAELLE]
    sonstige = kennungen.count("sonstiges")
    assert sonstige <= len(ECHTE_FAELLE) // 5


def _mappe_mit_offenen_punkten(tmp_path: Path) -> Arbeitsmappe:
    mappe = Arbeitsmappe.anlegen(tmp_path / "mappe", 2024)
    for nummer, (text, _) in enumerate(ECHTE_FAELLE):
        pfad = tmp_path / f"beleg{nummer}.txt"
        pfad.write_text(str(nummer), encoding="utf-8")
        dokument, _ = mappe.datei_aufnehmen(pfad, herkunft_jahr=2024)
        dokument.analyse = Analyse(
            kategorie_id="werbungskosten_sonstige",
            eignung="bedingt_geeignet",
            betrag_gesamt=100.0,
            fehlende_nachweise=[text],
        )
    mappe.speichern()
    return mappe


def test_uebersicht_buendelt_deutlich(tmp_path, capsys):
    mappe = _mappe_mit_offenen_punkten(tmp_path)
    befehl_offen(argparse.Namespace(mappe=str(mappe.wurzel), jahr=None, thema=None))
    ausgabe = capsys.readouterr().out

    assert f"{len(ECHTE_FAELLE)} Einzelangaben" in ausgabe
    themen = {_offen_thema(text)[0] for text, _ in ECHTE_FAELLE}
    assert f"gebuendelt zu {len(themen)} Besorgungen" in ausgabe

    # Der Sinn der Uebung: verschieden formulierte Wuensche landen in einer
    # Zeile. Die Stichprobe nennt den Zahlungsnachweis mehrfach und jedes Mal
    # anders - die Uebersicht muss daraus eine einzige Zeile machen.
    zahlungen = sum(1 for text, _ in ECHTE_FAELLE if _offen_thema(text)[0] == "zahlung")
    assert zahlungen >= 4, "Stichprobe taugt nicht zum Nachweis der Buendelung"
    zeilen = [z for z in ausgabe.splitlines() if " zahlung " in z]
    assert len(zeilen) == 1
    assert zeilen[0].strip().startswith(str(zahlungen)), zeilen[0]

    # Und die Zahl der Zeilen ist durch die Themenliste gedeckelt, nicht durch
    # die Zahl der Fehlanzeigen: Ein Bestand mit 180 Angaben ergibt dieselben.
    assert len(themen) <= len(OFFEN_THEMEN) + 1


def test_ein_thema_zeigt_seine_einzelnen_punkte(tmp_path, capsys):
    mappe = _mappe_mit_offenen_punkten(tmp_path)
    befehl_offen(argparse.Namespace(mappe=str(mappe.wurzel), jahr=None, thema="zahlung"))
    ausgabe = capsys.readouterr().out

    assert "Kontoauszuege Geschaeftskonto 2024" in ausgabe
    assert "Lohnsteuerbescheinigung" not in ausgabe


def test_unbekanntes_thema_meldet_die_vorhandenen(tmp_path, capsys):
    mappe = _mappe_mit_offenen_punkten(tmp_path)
    code = befehl_offen(argparse.Namespace(mappe=str(mappe.wurzel), jahr=None, thema="quatsch"))
    assert code == 1
    assert "zahlung" in capsys.readouterr().err


def test_ein_dokument_zaehlt_je_thema_nur_einmal(tmp_path, capsys):
    """Drei Kontoauszug-Wuensche an einem Beleg sind ein Beleg, nicht drei."""
    mappe = Arbeitsmappe.anlegen(tmp_path / "mappe", 2024)
    pfad = tmp_path / "beleg.txt"
    pfad.write_text("x", encoding="utf-8")
    dokument, _ = mappe.datei_aufnehmen(pfad, herkunft_jahr=2024)
    dokument.analyse = Analyse(
        kategorie_id="werbungskosten_sonstige",
        betrag_gesamt=100.0,
        fehlende_nachweise=[
            "Kontoauszug als Zahlungsnachweis",
            "Zahlungsnachweis (Ueberweisungsbeleg)",
            "Nachweis der tatsaechlichen Abbuchung per Lastschrift",
        ],
    )
    mappe.speichern()

    befehl_offen(argparse.Namespace(mappe=str(mappe.wurzel), jahr=None, thema=None))
    ausgabe = capsys.readouterr().out
    assert "3 Einzelangaben" in ausgabe
    zeile = next(z for z in ausgabe.splitlines() if "zahlung" in z and "EUR" in z)
    assert zeile.strip().startswith("1"), f"Beleg mehrfach gezaehlt: {zeile!r}"
    assert "100,00" in zeile


def test_reihenfolge_passt_zur_angezeigten_zahl(tmp_path, capsys):
    """Sortiert wird nach Belegen, gezaehlt auch - sonst steht die Liste falsch.

    Ein Thema mit vielen Fehlanzeigen an wenigen Belegen rutschte sonst nach
    oben, obwohl in seiner Spalte eine kleinere Zahl steht als darunter.
    """
    mappe = Arbeitsmappe.anlegen(tmp_path / "mappe", 2024)

    def beleg(name: str, nachweise: list[str]) -> None:
        pfad = tmp_path / name
        pfad.write_text(name, encoding="utf-8")
        dokument, _ = mappe.datei_aufnehmen(pfad, herkunft_jahr=2024)
        dokument.analyse = Analyse(
            kategorie_id="werbungskosten_sonstige",
            betrag_gesamt=10.0,
            fehlende_nachweise=nachweise,
        )

    # Ein Beleg mit fuenf Wuenschen zum selben Thema ...
    beleg("euer.txt", [f"EUER-Auszug Teil {n}" for n in range(5)])
    # ... gegen drei Belege mit je einem.
    for n in range(3):
        beleg(f"arzt{n}.txt", ["Aerztliche Verordnung"])

    mappe.speichern()
    befehl_offen(argparse.Namespace(mappe=str(mappe.wurzel), jahr=None, thema=None))

    zeilen = [z for z in capsys.readouterr().out.splitlines() if " EUR  " in z]
    zahlen = [int(z.strip().split()[0]) for z in zeilen]
    assert zahlen == sorted(zahlen, reverse=True), zeilen
