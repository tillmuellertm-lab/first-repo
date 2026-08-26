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
    befehl_offen(argparse.Namespace(mappe=str(mappe.wurzel), jahr=None, thema=None, voll=False))
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
    befehl_offen(argparse.Namespace(mappe=str(mappe.wurzel), jahr=None, thema="zahlung", voll=True))
    ausgabe = capsys.readouterr().out

    assert "Kontoauszuege Geschaeftskonto 2024" in ausgabe
    assert "Lohnsteuerbescheinigung" not in ausgabe


def test_unbekanntes_thema_meldet_die_vorhandenen(tmp_path, capsys):
    mappe = _mappe_mit_offenen_punkten(tmp_path)
    code = befehl_offen(argparse.Namespace(mappe=str(mappe.wurzel), jahr=None, thema="quatsch", voll=False))
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

    befehl_offen(argparse.Namespace(mappe=str(mappe.wurzel), jahr=None, thema=None, voll=False))
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
    befehl_offen(argparse.Namespace(mappe=str(mappe.wurzel), jahr=None, thema=None, voll=False))

    zeilen = [z for z in capsys.readouterr().out.splitlines() if " EUR  " in z]
    zahlen = [int(z.strip().split()[0]) for z in zeilen]
    assert zahlen == sorted(zahlen, reverse=True), zeilen


# --- Rueckfragen beantworten -------------------------------------------------


def _mappe_mit_fragen(tmp_path: Path) -> Arbeitsmappe:
    mappe = Arbeitsmappe.anlegen(tmp_path / "mappe", 2024)
    for nummer, frage in enumerate(
        [
            "Klärung, ob die App beruflich oder privat genutzt wird",
            "Zuordnung zu einer konkreten Fahrt (Datum, Start/Ziel, Zweck)",
        ]
    ):
        pfad = tmp_path / f"frage{nummer}.txt"
        pfad.write_text(str(nummer), encoding="utf-8")
        dokument, _ = mappe.datei_aufnehmen(pfad, herkunft_jahr=2024)
        dokument.analyse = Analyse(
            kategorie_id="werbungskosten_sonstige",
            dokumenttyp="Rechnung",
            aussteller="Beispiel GmbH",
            betrag_gesamt=47.87,
            fehlende_nachweise=[frage],
        )
    # Ein Beleg, dem ein Dokument fehlt - keine Frage, darf nicht drankommen.
    pfad = tmp_path / "beleg.txt"
    pfad.write_text("b", encoding="utf-8")
    dokument, _ = mappe.datei_aufnehmen(pfad, herkunft_jahr=2024)
    dokument.analyse = Analyse(
        kategorie_id="werbungskosten_sonstige", fehlende_nachweise=["Kontoauszug fehlt"]
    )
    mappe.speichern()
    return mappe


def test_antworten_werden_am_beleg_festgehalten(tmp_path, capsys, monkeypatch):
    from steuer.cli import befehl_beantworten

    mappe = _mappe_mit_fragen(tmp_path)
    antworten = iter(["beruflich, fuer die Wohnungssuche in Koeln", ""])
    monkeypatch.setattr("builtins.input", lambda *_: next(antworten))

    befehl_beantworten(argparse.Namespace(mappe=str(mappe.wurzel), jahr=None, thema="frage", erneut=False, ab_betrag=0.0))
    ausgabe = capsys.readouterr().out

    assert "2 offene Punkte" in ausgabe, "die Kontoauszug-Zeile gehoert nicht dazu"
    assert "1 Antworten festgehalten" in ausgabe

    wieder = Arbeitsmappe.laden(mappe.wurzel)
    notizen = [d.notiz for d in wieder.dokumente if d.notiz]
    assert notizen == ["beruflich, fuer die Wohnungssuche in Koeln"]


def test_abbruch_behaelt_das_bereits_gegebene(tmp_path, capsys, monkeypatch):
    from steuer.cli import befehl_beantworten

    mappe = _mappe_mit_fragen(tmp_path)
    antworten = iter(["privat genutzt", "x"])
    monkeypatch.setattr("builtins.input", lambda *_: next(antworten))

    befehl_beantworten(argparse.Namespace(mappe=str(mappe.wurzel), jahr=None, thema="frage", erneut=False, ab_betrag=0.0))
    assert "Abgebrochen" in capsys.readouterr().out

    wieder = Arbeitsmappe.laden(mappe.wurzel)
    assert [d.notiz for d in wieder.dokumente if d.notiz] == ["privat genutzt"]


def test_beantwortete_belege_kommen_nicht_wieder(tmp_path, capsys, monkeypatch):
    from steuer.cli import befehl_beantworten

    mappe = _mappe_mit_fragen(tmp_path)
    monkeypatch.setattr("builtins.input", lambda *_: "erste Antwort")
    befehl_beantworten(argparse.Namespace(mappe=str(mappe.wurzel), jahr=None, thema="frage", erneut=False, ab_betrag=0.0))
    capsys.readouterr()

    monkeypatch.setattr("builtins.input", lambda *_: "")
    befehl_beantworten(argparse.Namespace(mappe=str(mappe.wurzel), jahr=None, thema="frage", erneut=False, ab_betrag=0.0))
    assert "Nichts offen" in capsys.readouterr().out


def test_anmerkung_steht_im_bericht(tmp_path):
    """Eine Antwort, die der Steuerberater nicht sieht, war vergeudete Zeit."""
    from steuer import gaps, report
    from steuer.rules import laden as regeln_laden

    mappe = _mappe_mit_fragen(tmp_path)
    mappe.dokumente[0].notiz = "beruflich, fuer die Wohnungssuche in Koeln"

    werk = regeln_laden(2024)
    auswertung = gaps.auswerten(mappe.dokumente, werk, mappe.profil)
    text = report.markdown_bericht(mappe.dokumente, auswertung, werk, mappe.profil)
    assert "beruflich, fuer die Wohnungssuche in Koeln" in text
    assert "Anmerkung des Mandanten" in text


def test_eingefuegter_konsolenbefehl_wird_nicht_als_antwort_gespeichert(tmp_path, capsys, monkeypatch):
    """Beim Einfuegen mehrerer Zeilen landet die zweite in der Eingabeaufforderung."""
    from steuer.cli import befehl_beantworten

    mappe = _mappe_mit_fragen(tmp_path)
    eingaben = iter(["git pull origin claude/tax-return-document-tool-jesqdh && steuer beantworten", "x"])
    monkeypatch.setattr("builtins.input", lambda *_: next(eingaben))

    befehl_beantworten(
        argparse.Namespace(mappe=str(mappe.wurzel), jahr=None, thema="frage", erneut=False, ab_betrag=0.0)
    )
    assert "nicht\n        gespeichert" in capsys.readouterr().out

    wieder = Arbeitsmappe.laden(mappe.wurzel)
    assert not [d.notiz for d in wieder.dokumente if d.notiz], "der Befehl darf nirgends stehen"


def test_falsche_anmerkung_laesst_sich_loeschen(tmp_path, capsys, monkeypatch):
    from steuer.cli import befehl_beantworten

    mappe = _mappe_mit_fragen(tmp_path)
    mappe.dokumente[0].notiz = "git pull origin ..."
    mappe.speichern()

    monkeypatch.setattr("builtins.input", lambda *_: "-")
    befehl_beantworten(
        argparse.Namespace(mappe=str(mappe.wurzel), jahr=None, thema="frage", erneut=True, ab_betrag=0.0)
    )
    capsys.readouterr()

    wieder = Arbeitsmappe.laden(mappe.wurzel)
    assert not [d.notiz for d in wieder.dokumente if d.notiz]


def test_teuerster_beleg_kommt_zuerst(tmp_path, capsys, monkeypatch):
    """Eine Frage zu 29,99 EUR ist dieselbe Minute Arbeit wie eine zu 35.000 EUR."""
    from steuer.cli import befehl_beantworten

    mappe = Arbeitsmappe.anlegen(tmp_path / "mappe", 2024)
    for name, betrag in (("klein.txt", 29.99), ("gross.txt", 35000.0), ("mittel.txt", 500.0)):
        pfad = tmp_path / name
        pfad.write_text(name, encoding="utf-8")
        dokument, _ = mappe.datei_aufnehmen(pfad, herkunft_jahr=2024)
        dokument.analyse = Analyse(
            kategorie_id="werbungskosten_sonstige",
            dokumenttyp=name,
            betrag_gesamt=betrag,
            fehlende_nachweise=["Klärung, ob beruflich veranlasst"],
        )
    mappe.speichern()

    monkeypatch.setattr("builtins.input", lambda *_: "")
    befehl_beantworten(
        argparse.Namespace(mappe=str(mappe.wurzel), jahr=None, thema="frage", erneut=False, ab_betrag=0.0)
    )
    zeilen = [z for z in capsys.readouterr().out.splitlines() if z.startswith("[")]
    assert "gross" in zeilen[0] and "klein" in zeilen[-1], zeilen


def test_kleinbetraege_bleiben_standardmaessig_aussen_vor(tmp_path, capsys, monkeypatch):
    from steuer.cli import befehl_beantworten

    mappe = Arbeitsmappe.anlegen(tmp_path / "mappe", 2024)
    for name, betrag in (("klein.txt", 29.99), ("gross.txt", 500.0)):
        pfad = tmp_path / name
        pfad.write_text(name, encoding="utf-8")
        dokument, _ = mappe.datei_aufnehmen(pfad, herkunft_jahr=2024)
        dokument.analyse = Analyse(
            kategorie_id="werbungskosten_sonstige",
            dokumenttyp=name,
            betrag_gesamt=betrag,
            fehlende_nachweise=["Klärung, ob beruflich veranlasst"],
        )
    mappe.speichern()

    monkeypatch.setattr("builtins.input", lambda *_: "")
    befehl_beantworten(
        argparse.Namespace(mappe=str(mappe.wurzel), jahr=None, thema="frage", erneut=False, ab_betrag=50.0)
    )
    ausgabe = capsys.readouterr().out
    assert "1 offene Punkte" in ausgabe
    assert "1 weitere Fragen betreffen Betraege unter" in ausgabe


# --- Nachsehen, was gespeichert ist ------------------------------------------


def test_anmerkungen_zeigen_was_gespeichert_wurde(tmp_path, capsys):
    """Wer in kurzen Abschnitten arbeitet, muss nachsehen koennen."""
    from steuer.cli import befehl_anmerkungen

    mappe = _mappe_mit_fragen(tmp_path)
    mappe.dokumente[0].notiz = "beruflich, fuer die Wohnungssuche in Koeln"
    mappe.speichern()

    befehl_anmerkungen(argparse.Namespace(mappe=str(mappe.wurzel), jahr=None))
    ausgabe = capsys.readouterr().out

    assert "1 Anmerkungen" in ausgabe
    assert "beruflich, fuer die Wohnungssuche in Koeln" in ausgabe
    assert "1 Rueckfragen sind noch offen" in ausgabe


def test_leere_mappe_nennt_die_offenen_rueckfragen(tmp_path, capsys):
    from steuer.cli import befehl_anmerkungen

    mappe = _mappe_mit_fragen(tmp_path)
    befehl_anmerkungen(argparse.Namespace(mappe=str(mappe.wurzel), jahr=None))
    ausgabe = capsys.readouterr().out
    assert "Keine Anmerkungen gespeichert" in ausgabe
    assert "2 Rueckfragen warten" in ausgabe


def test_versehentlich_gespeicherter_befehl_wird_markiert(tmp_path, capsys):
    """Die alte Fehleingabe muss auffindbar bleiben, nicht nur verhindert."""
    from steuer.cli import befehl_anmerkungen

    mappe = _mappe_mit_fragen(tmp_path)
    mappe.dokumente[0].notiz = "git pull origin claude/tax-return-document-tool-jesqdh"
    mappe.speichern()

    befehl_anmerkungen(argparse.Namespace(mappe=str(mappe.wurzel), jahr=None))
    assert "ACHTUNG: sieht nach einer eingefuegten Konsolenzeile aus" in capsys.readouterr().out
