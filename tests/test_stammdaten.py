"""Jahresuebergreifendes Gedaechtnis: bestaetigte Fortschreibungswerte."""

from pathlib import Path

import pytest

from steuer import gaps, prompts, rules, stammdaten
from steuer.models import Profil
from steuer.workspace import Arbeitsmappe


@pytest.fixture()
def gefuellt() -> stammdaten.Stammdaten:
    daten = stammdaten.Stammdaten()
    daten.setzen(
        "gebaeude_afa_jahresbetrag",
        7177.0,
        quelle="ESt-Erklaerung 2023, Anlage V, Zeile 33",
        gilt_ab_jahr=2024,
    )
    daten.setzen("gebaeude_afa_satz", 2.0)
    daten.setzen("objekt_bezeichnung", "Bickbargen 153a, Halstenbek")
    return daten


def test_setzen_und_lesen(gefuellt):
    assert gefuellt.wert("gebaeude_afa_jahresbetrag") == 7177.0
    assert "gebaeude_afa_jahresbetrag" in gefuellt
    assert "verlustvortrag_kapital" not in gefuellt
    assert gefuellt.wert("verlustvortrag_kapital", 0) == 0


def test_label_und_einheit_kommen_aus_der_vorlage(gefuellt):
    eintrag = gefuellt.eintrag("gebaeude_afa_jahresbetrag")
    assert eintrag.label == "Gebaeude-AfA, Jahresbetrag"
    assert eintrag.einheit == "EUR"
    assert eintrag.bestaetigt_am  # wird automatisch gesetzt


def test_speichern_und_laden(tmp_path, gefuellt):
    pfad = tmp_path / stammdaten.DATEINAME
    stammdaten.speichern(gefuellt, pfad)
    wieder = stammdaten.laden(pfad)
    assert wieder.wert("gebaeude_afa_jahresbetrag") == 7177.0
    assert wieder.eintrag("gebaeude_afa_jahresbetrag").quelle.startswith("ESt-Erklaerung 2023")
    assert wieder.wert("objekt_bezeichnung") == "Bickbargen 153a, Halstenbek"


def test_fehlende_datei_ist_kein_fehler(tmp_path):
    daten = stammdaten.laden(tmp_path / "gibtsnicht.yaml")
    assert daten.gesetzte() == []


def test_entfernen(gefuellt):
    assert gefuellt.entfernen("gebaeude_afa_satz")
    assert "gebaeude_afa_satz" not in gefuellt
    assert not gefuellt.entfernen("gebaeude_afa_satz")


def test_fortschreiben_ins_naechste_jahr(gefuellt):
    gefuellt.setzen("verlustvortrag_kapital", 157.0)
    gefuellt.setzen("afa_bewegliche_wirtschaftsgueter", 920.0)

    neu, zu_pruefen = gefuellt.fuer_neues_jahr(2025)

    assert neu.wert("gebaeude_afa_jahresbetrag") == 7177.0
    assert neu.eintrag("gebaeude_afa_jahresbetrag").gilt_ab_jahr == 2025
    # Werte mit endlicher Laufzeit werden uebernommen, aber zur Pruefung gestellt.
    assert "AfA beweglicher Wirtschaftsgueter" in zu_pruefen
    assert any("Verlustvortrag" in t for t in zu_pruefen)
    assert "Gebaeude-AfA, Jahresbetrag" not in zu_pruefen
    # Die Quelle bleibt erhalten, damit nachvollziehbar bleibt, woher der Wert stammt.
    assert neu.eintrag("gebaeude_afa_jahresbetrag").quelle


def test_fortschreiben_veraendert_das_original_nicht(gefuellt):
    neu, _ = gefuellt.fuer_neues_jahr(2025)
    neu.setzen("gebaeude_afa_jahresbetrag", 1.0)
    assert gefuellt.wert("gebaeude_afa_jahresbetrag") == 7177.0


def test_pruefsumme_reagiert_auf_werte(gefuellt):
    vorher = gefuellt.pruefsumme()
    gefuellt.setzen("verlustvortrag_kapital", 157.0)
    assert gefuellt.pruefsumme() != vorher


def test_bekannte_afa_ist_keine_chance_mehr(gefuellt):
    profil = Profil(veranlagungsjahr=2024, merkmale=["vermietung"])
    werk = rules.laden(2024)

    ohne = gaps.auswerten([], werk, profil)
    assert any(b.id == "regel_gebaeude_afa_sichern" for b in ohne.chancen)

    mit = gaps.auswerten([], werk, profil, stammdaten=gefuellt)
    assert not any(b.id == "regel_gebaeude_afa_sichern" for b in mit.chancen)


def test_uebernommene_werte_werden_sichtbar_gemacht(gefuellt):
    ergebnis = gaps.auswerten([], rules.laden(2024), Profil(veranlagungsjahr=2024), stammdaten=gefuellt)
    hinweise = ergebnis.nach_art("hinweis")
    assert hinweise, "der Nutzer muss sehen, woher eine Zahl stammt"
    assert "7177" in hinweise[0].beschreibung.replace(".", "")
    assert "Anlage V" in hinweise[0].beschreibung


def test_stammdaten_stehen_im_systemprompt(gefuellt):
    text = prompts.system_analyse(rules.laden(2024), Profil(veranlagungsjahr=2024), gefuellt)
    assert "Bereits bestaetigte Werte" in text
    assert "7177" in text
    ohne = prompts.system_analyse(rules.laden(2024), Profil(veranlagungsjahr=2024))
    assert "Bereits bestaetigte Werte" not in ohne


def test_mappe_findet_und_speichert_stammdaten(tmp_path):
    mappe = Arbeitsmappe.anlegen(tmp_path / "m", 2024)
    assert mappe.stammdaten.gesetzte() == []
    mappe.stammdaten.setzen("steuernummer", "219/5230/3521")
    pfad = mappe.stammdaten_speichern()
    assert pfad == mappe.wurzel / stammdaten.DATEINAME

    wieder = Arbeitsmappe.laden(mappe.wurzel)
    assert wieder.stammdaten.wert("steuernummer") == "219/5230/3521"


def test_gemeinsame_datei_ueber_einstellung(tmp_path):
    gemeinsam = tmp_path / "gemeinsam" / "stammdaten.yaml"
    for jahr in (2024, 2025):
        mappe = Arbeitsmappe.anlegen(tmp_path / f"m{jahr}", jahr)
        mappe.einstellungen["stammdaten"] = str(gemeinsam)
        mappe.speichern()
        if jahr == 2024:
            mappe.stammdaten.setzen("finanzamt", "Koeln-Sued")
            mappe.stammdaten_speichern()
        else:
            assert mappe.stammdaten.wert("finanzamt") == "Koeln-Sued"


def test_kontext_umfasst_die_stammdaten(tmp_path):
    mappe = Arbeitsmappe.anlegen(tmp_path / "m", 2024)
    vorher = mappe.kontext_pruefsumme()
    mappe.stammdaten.setzen("gebaeude_afa_jahresbetrag", 7177.0)
    assert mappe.kontext_pruefsumme() != vorher
