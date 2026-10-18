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


# --- Listenfelder aus der Modellantwort -------------------------------------


def test_string_wird_nicht_buchstabenweise_zerlegt():
    """Der Fehler, der 180 Fehlanzeigen in Buchstaben verwandelt hat.

    Das Modell soll ein Array liefern, schickt aber manchmal einen String.
    ``[str(x) for x in "abc"]`` ergibt ``["a", "b", "c"]`` - eine Liste von
    Strings, formal einwandfrei, inhaltlich Schrott.
    """
    from steuer.models import textliste

    assert textliste("Zahlungsnachweis fehlt") == ["Zahlungsnachweis fehlt"]
    assert textliste("Rechnung fehlt; Kontoauszug fehlt") == [
        "Rechnung fehlt",
        "Kontoauszug fehlt",
    ]
    assert textliste("Erste Zeile\nZweite Zeile") == ["Erste Zeile", "Zweite Zeile"]


def test_zerlegter_satz_wird_beim_laden_wieder_zusammengesetzt():
    """Gespeicherte Buchstabenlisten sind heilbar - die Reihenfolge blieb erhalten."""
    from steuer.models import Analyse, textliste

    zerlegt = list("Kontoauszug mit tatsaechlicher Abbuchung")
    assert textliste(zerlegt) == ["Kontoauszug mit tatsaechlicher Abbuchung"]

    analyse = Analyse.aus_dict({"fehlende_nachweise": zerlegt, "hinweise": list("Zwei Seiten")})
    assert analyse.fehlende_nachweise == ["Kontoauszug mit tatsaechlicher Abbuchung"]
    assert analyse.hinweise == ["Zwei Seiten"]


def test_echte_listen_bleiben_unangetastet():
    """Die Heilung darf keine gueltige Liste zusammenkleben."""
    from steuer.models import textliste

    echt = ["Rechnung fehlt", "Kontoauszug fehlt", "Attest fehlt", "Mietvertrag fehlt"]
    assert textliste(echt) == echt
    # Kurze Eintraege, aber nicht alle einzeichig: keine zerlegte Zeichenkette.
    assert textliste(["a", "bc", "d", "e"]) == ["a", "bc", "d", "e"]
    # Weniger als vier Zeichen bleiben, wie sie sind.
    assert textliste(["a", "b"]) == ["a", "b"]
    assert textliste([]) == []
    assert textliste(None) == []


def test_analyse_aus_der_api_zerlegt_keinen_string():
    """Die Stelle, an der der Fehler entstand."""
    from steuer.analyze import _analyse_aus_rohdaten

    analyse = _analyse_aus_rohdaten(
        {"kategorie_id": "unklar", "fehlende_nachweise": "Zahlungsnachweis fehlt"}
    )
    assert analyse.fehlende_nachweise == ["Zahlungsnachweis fehlt"]


def test_bruchstuecke_des_werkzeugaufrufs_werden_entfernt():
    """In einer echten Mappe stand ein Fragment des Modellaufrufs im Klartext."""
    from steuer.models import Analyse, textliste

    assert textliste('<parameter name="item">Einzelrechnungen/Quittungen zu allen Positionen') == [
        "Einzelrechnungen/Quittungen zu allen Positionen"
    ]
    assert textliste(["Klärung, ob Objekt vermietet ist</parameter>"]) == [
        "Klärung, ob Objekt vermietet ist"
    ]
    # Beim Laden alter Analysen ebenfalls.
    analyse = Analyse.aus_dict({"fehlende_nachweise": ['<parameter name="x">Kontoauszug fehlt']})
    assert analyse.fehlende_nachweise == ["Kontoauszug fehlt"]


def test_spitze_klammern_im_fliesstext_bleiben():
    """Ein Vergleichszeichen ist kein Bruchstueck."""
    from steuer.models import textliste

    assert textliste("Betrag < 800 EUR, daher geringwertiges Wirtschaftsgut") == [
        "Betrag < 800 EUR, daher geringwertiges Wirtschaftsgut"
    ]


def test_ein_reines_bruchstueck_verschwindet_ganz():
    from steuer.models import textliste

    assert textliste('<parameter name="leer">') == []
    assert textliste(["</parameter>", "Kontoauszug fehlt"]) == ["Kontoauszug fehlt"]


# --- Rettung beschaedigter PDFs ---------------------------------------------


def test_beschaedigtes_pdf_wird_neu_aufgebaut(tmp_path):
    """Ein von der API abgelehntes PDF ist meist nur strukturell fehlerhaft."""
    pytest.importorskip("pypdf")
    from pypdf import PdfWriter

    from steuer.extract import inhalt_neu_aufbauen, pdf_neu_aufbauen

    pfad = tmp_path / "beleg.pdf"
    schreiber = PdfWriter()
    schreiber.add_blank_page(width=595, height=842)
    with pfad.open("wb") as datei:
        schreiber.write(datei)

    daten = pdf_neu_aufbauen(pfad)
    assert daten and daten.startswith(b"%PDF")

    inhalt = inhalt_neu_aufbauen(pfad)
    assert inhalt is not None
    assert inhalt.bloecke[0]["type"] == "document"
    assert "neu aufgebaut" in " ".join(inhalt.hinweise)


def test_unrettbare_datei_gibt_nichts_zurueck(tmp_path):
    from steuer.extract import pdf_neu_aufbauen

    kaputt = tmp_path / "kaputt.pdf"
    kaputt.write_bytes(b"das ist kein PDF")
    assert pdf_neu_aufbauen(kaputt) is None


def test_notinhalt_braucht_lesbaren_text(tmp_path):
    """Ohne Textebene wird nichts erfunden - der Fehler bleibt ein Fehler."""
    from steuer.extract import notinhalt

    leer = tmp_path / "leer.pdf"
    leer.write_bytes(b"%PDF-1.4 nichts lesbares")
    assert notinhalt(leer, "Testgrund") is None
