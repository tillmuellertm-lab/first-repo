"""Die Weboberflaeche muss alle Ansichten rendern, auch mit leerer Mappe."""

import io
from pathlib import Path

import pytest

from steuer.models import Analyse, Profil
from steuer.web.app import anwendung_bauen
from steuer.workspace import Arbeitsmappe

flask = pytest.importorskip("flask")


@pytest.fixture
def mappe(tmp_path: Path) -> Arbeitsmappe:
    profil = Profil(
        name="Testperson",
        veranlagungsjahr=2024,
        merkmale=["angestellt", "eigener_haushalt", "pendler"],
        entfernung_km=22,
        arbeitstage=210,
    )
    arbeitsmappe = Arbeitsmappe.anlegen(tmp_path / "mappe", 2024, profil)
    quelle = tmp_path / "handwerker.txt"
    quelle.write_text("Rechnung Elektro Mueller, Lohnanteil 890 EUR", encoding="utf-8")
    dokument, _ = arbeitsmappe.datei_aufnehmen(quelle)
    dokument.analyse = Analyse(
        kategorie_id="haushaltsnahe_aufwendungen",
        dokumenttyp="Handwerkerrechnung",
        aussteller="Elektro Mueller",
        datum="2024-04-02",
        steuerjahr=2024,
        betrag_gesamt=1450.0,
        betrag_abzugsfaehig=890.0,
        eignung="bedingt_geeignet",
        eignung_begruendung="Zahlungsnachweis fehlt.",
        vertrauen=0.82,
        zusammenfassung="Erneuerung der Elektroinstallation.",
        fehlende_nachweise=["Kontoauszug zur Ueberweisung"],
        zahlungsart="unbekannt",
    )
    dokument.status = "analysiert"
    arbeitsmappe.speichern()
    return arbeitsmappe


@pytest.fixture
def klient(mappe: Arbeitsmappe):
    app = anwendung_bauen(mappe)
    app.config["TESTING"] = True
    with app.test_client() as klient:
        klient.mappe = mappe
        yield klient


def test_uebersicht_zeigt_dokumente(klient):
    antwort = klient.get("/")
    assert antwort.status_code == 200
    inhalt = antwort.get_data(as_text=True)
    assert "Handwerkerrechnung" in inhalt
    assert "34_Haushaltsnahe_Aufwendungen" in inhalt
    assert "890,00 EUR" in inhalt


def test_befundseite_zeigt_luecken_und_werte(klient):
    inhalt = klient.get("/befunde").get_data(as_text=True)
    assert "Was noch fehlt" in inhalt
    assert "Grundfreibetrag" in inhalt


def test_dokumentansicht(klient):
    kennung = klient.mappe.dokumente[0].id
    inhalt = klient.get(f"/dokument/{kennung}").get_data(as_text=True)
    assert "Elektro Mueller" in inhalt
    assert "Kontoauszug zur Ueberweisung" in inhalt


def test_unbekanntes_dokument_ergibt_404(klient):
    assert klient.get("/dokument/gibtesnicht").status_code == 404


def test_profil_speichern(klient):
    antwort = klient.post(
        "/profil",
        data={
            "name": "Neue Person",
            "familienstand": "verheiratet",
            "veranlagungsart": "zusammen",
            "anzahl_kinder": "2",
            "merkmale": ["angestellt", "kinder"],
            "entfernung_km": "18,5",
            "arbeitstage": "200",
            "gesamtbetrag_der_einkuenfte": "62.000",
            "notizen": "Umzug im Mai",
        },
    )
    assert antwort.status_code == 302
    geladen = Arbeitsmappe.laden(klient.mappe.wurzel)
    assert geladen.profil.name == "Neue Person"
    assert geladen.profil.anzahl_kinder == 2
    assert geladen.profil.entfernung_km == 18.5
    assert geladen.profil.gesamtbetrag_der_einkuenfte == 62000.0
    assert set(geladen.profil.merkmale) == {"angestellt", "kinder"}


def test_bericht_wird_gerendert(klient):
    inhalt = klient.get("/bericht").get_data(as_text=True)
    assert "<!doctype html>" in inhalt
    assert "Steuerunterlagen 2024" in inhalt


def test_datei_wird_ausgeliefert(klient):
    kennung = klient.mappe.dokumente[0].id
    antwort = klient.get(f"/datei/{kennung}")
    assert antwort.status_code == 200
    assert b"Elektro Mueller" in antwort.data


def test_hochladen_nimmt_datei_auf(klient):
    antwort = klient.post(
        "/api/hochladen",
        data={"dateien": (io.BytesIO("Spendenquittung".encode()), "spende.txt")},
        content_type="multipart/form-data",
    )
    daten = antwort.get_json()
    assert daten["aufgenommen"] == ["spende.txt"]
    assert daten["gesamt"] == 2


def test_hochladen_lehnt_unbekannten_typ_ab(klient):
    antwort = klient.post(
        "/api/hochladen",
        data={"dateien": (io.BytesIO(b"MZ"), "schadcode.exe")},
        content_type="multipart/form-data",
    )
    daten = antwort.get_json()
    assert daten["abgelehnt"] and daten["abgelehnt"][0]["datei"] == "schadcode.exe"
    assert not daten["aufgenommen"]


def test_kategorie_manuell_ueberschreiben(klient):
    kennung = klient.mappe.dokumente[0].id
    klient.post(f"/dokument/{kennung}", data={"kategorie": "sonderausgaben", "notiz": "geprueft"})
    geladen = Arbeitsmappe.laden(klient.mappe.wurzel)
    assert geladen.dokumente[0].wirksame_kategorie == "sonderausgaben"
    assert geladen.dokumente[0].notiz == "geprueft"


def test_analyse_ohne_schluessel_wird_abgelehnt(klient, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    antwort = klient.post("/api/analyse", json={})
    assert antwort.status_code == 400
    assert "ANTHROPIC_API_KEY" in antwort.get_json()["fehler"]


def test_ordnen_erzeugt_ablage_und_berichte(klient):
    antwort = klient.post("/api/ordnen", json={"paket": True})
    assert antwort.status_code == 200
    # Der Lauf ist ein Hintergrundthread; auf sein Ende warten.
    for _ in range(100):
        if not klient.get("/api/auftrag").get_json()["laeuft"]:
            break
        import time

        time.sleep(0.05)
    zustand = klient.get("/api/auftrag").get_json()
    assert not zustand["laeuft"]
    assert not zustand["fehler"]
    mappe = klient.mappe
    assert (mappe.berichte / "Uebersicht_2024.html").exists()
    assert (mappe.berichte / "Steuerunterlagen_2024.zip").exists()
    assert (mappe.aufbereitet / "2024" / "34_Haushaltsnahe_Aufwendungen").is_dir()


def test_leere_mappe_rendert(tmp_path: Path):
    leer = Arbeitsmappe.anlegen(tmp_path / "leer", 2024, Profil(veranlagungsjahr=2024))
    app = anwendung_bauen(leer)
    app.config["TESTING"] = True
    with app.test_client() as klient:
        assert klient.get("/").status_code == 200
        assert "Noch keine Unterlagen" in klient.get("/").get_data(as_text=True)
        assert klient.get("/befunde").status_code == 200
        assert klient.get("/profil").status_code == 200
        assert klient.get("/bericht").status_code == 200
