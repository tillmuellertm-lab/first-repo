"""Zahleneingaben: deutsche Schreibweise lesen, ohne bei Wiederholung zu wachsen."""

import pytest

from steuer.formatierung import eingabewert, euro, zahl, zahl_lesen
from steuer.models import Profil


@pytest.mark.parametrize(
    "eingabe,erwartet",
    [
        ("6", 6.0),
        ("6,5", 6.5),
        ("132.052", 132052.0),          # deutscher Tausenderpunkt
        ("132052", 132052.0),
        ("1.234.567", 1234567.0),
        ("1.234,56", 1234.56),          # deutsch mit beidem
        ("1,234.56", 1234.56),          # englisch mit beidem
        ("6.0", 6.0),                   # Rueckgabe eines Formularfelds
        ("132052.0", 132052.0),
        ("135.544,00", 135544.0),
        ("1 234", 1234.0),
        ("142.389 €", 142389.0),
        ("-500,25", -500.25),
        ("", None),
        ("   ", None),
        ("keine Zahl", None),
        (None, None),
        (6.5, 6.5),
    ],
)
def test_zahl_lesen(eingabe, erwartet):
    assert zahl_lesen(eingabe) == erwartet


@pytest.mark.parametrize("start", [6.0, 6.5, 132052.0, 135544.0, 0.0, 250])
def test_speicherzyklus_veraendert_den_wert_nicht(start):
    """Der eigentliche Fehler: aus 6 wurde ueber mehrere Speichervorgaenge 600000.

    Formularfeld fuellen, zurueckschicken, wieder fuellen - zehn Runden lang
    muss derselbe Wert herauskommen.
    """
    wert = start
    for _ in range(10):
        wert = zahl_lesen(eingabewert(wert))
    assert wert == start


def test_eingabewert_schreibt_keine_nachkommanull():
    assert eingabewert(6.0) == "6"
    assert eingabewert(132052.0) == "132052"
    assert eingabewert(6.5) == "6,50"
    assert eingabewert(None) == ""


def test_unplausible_werte_werden_erkannt():
    profil = Profil(
        veranlagungsjahr=2024,
        entfernung_km=600000.0,
        bruttoarbeitslohn=14238900000.0,
        gesamtbetrag_der_einkuenfte=13527700000.0,
    )
    meldungen = profil.unplausible_werte()
    assert len(meldungen) == 3
    assert any("Entfernung" in m for m in meldungen)
    assert any("Bruttoarbeitslohn" in m for m in meldungen)


def test_plausible_werte_werden_durchgelassen():
    profil = Profil(
        veranlagungsjahr=2024,
        entfernung_km=6.0,
        arbeitstage=250,
        homeoffice_tage=50,
        anzahl_kinder=2,
        bruttoarbeitslohn=132052.0,
        gesamtbetrag_der_einkuenfte=135544.0,
    )
    assert profil.unplausible_werte() == []


def test_leere_felder_gelten_nicht_als_unplausibel():
    assert Profil(veranlagungsjahr=2024).unplausible_werte() == []


def test_deutsche_ausgabe_bleibt_unveraendert():
    assert zahl(1234.5) == "1.234,50"
    assert euro(1234.5) == "1.234,50 EUR"
    assert euro(None) == "—"


def test_kontextpruefsumme_reagiert_auf_inhaltliche_aenderungen():
    """Der Wissensstand muss sich aendern, wenn sich das Wissen aendert."""
    basis = Profil(veranlagungsjahr=2024, merkmale=["angestellt"])
    unveraendert = Profil(veranlagungsjahr=2024, merkmale=["angestellt"])
    assert basis.kontext_pruefsumme() == unveraendert.kontext_pruefsumme()

    mit_betrieb = Profil(
        veranlagungsjahr=2024, merkmale=["angestellt"], taetigkeiten="Tuftingstudio"
    )
    assert mit_betrieb.kontext_pruefsumme() != basis.kontext_pruefsumme()

    mit_umzug = Profil(veranlagungsjahr=2024, merkmale=["angestellt", "umzug"])
    assert mit_umzug.kontext_pruefsumme() != basis.kontext_pruefsumme()

    mit_notiz = Profil(veranlagungsjahr=2024, merkmale=["angestellt"], notizen="Umzug 2024")
    assert mit_notiz.kontext_pruefsumme() != basis.kontext_pruefsumme()


def test_kontextpruefsumme_ignoriert_belangloses():
    """Name und Leerraum aendern den Analyseauftrag nicht."""
    a = Profil(veranlagungsjahr=2024, name="Till", taetigkeiten="Tuftingstudio  Koeln")
    b = Profil(veranlagungsjahr=2024, name="T. Mueller", taetigkeiten="Tuftingstudio Koeln")
    assert a.kontext_pruefsumme() == b.kontext_pruefsumme()
