"""Die Weboberflaeche muss alle Ansichten rendern, auch mit leerer Mappe."""

import io
from pathlib import Path

import pytest

from steuer import analyze
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


# ------------------------------------------------------------- Modellwahl --

def test_auswahlfelder_werden_angezeigt(klient):
    inhalt = klient.get("/").get_data(as_text=True)
    assert 'id="modell-dokument"' in inhalt
    assert 'id="modell-strategie"' in inhalt
    assert "Sonnet 5" in inhalt
    assert "Opus 5" in inhalt
    assert "Fable 5" in inhalt


def test_modellwahl_wird_gemerkt(klient, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    klient.post("/api/analyse", json={"modell": "claude-sonnet-5"})
    for _ in range(100):
        if not klient.get("/api/auftrag").get_json()["laeuft"]:
            break
        import time

        time.sleep(0.05)
    geladen = Arbeitsmappe.laden(klient.mappe.wurzel)
    assert geladen.einstellungen["modell_dokument"] == "claude-sonnet-5"
    # und das Auswahlfeld zeigt die Wahl wieder an
    inhalt = klient.get("/").get_data(as_text=True)
    assert '<option value="claude-sonnet-5" title=' in inhalt
    assert 'value="claude-sonnet-5"' in inhalt.split('id="modell-dokument"')[1]


def test_unbekanntes_modell_wird_nicht_durchgereicht(klient, monkeypatch):
    """Die Kennung kommt aus dem Browser und darf nicht ungeprueft an die API gehen."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    klient.post("/api/analyse", json={"modell": "boesartig-erfunden"})
    for _ in range(100):
        if not klient.get("/api/auftrag").get_json()["laeuft"]:
            break
        import time

        time.sleep(0.05)
    geladen = Arbeitsmappe.laden(klient.mappe.wurzel)
    assert geladen.einstellungen["modell_dokument"] == analyze.MODELL_DOKUMENT


def test_modellwahl_der_gesamtauswertung_wird_gemerkt(klient):
    antwort = klient.post("/api/ordnen", json={"modell": "claude-fable-5"})
    assert antwort.status_code == 200
    for _ in range(100):
        if not klient.get("/api/auftrag").get_json()["laeuft"]:
            break
        import time

        time.sleep(0.05)
    geladen = Arbeitsmappe.laden(klient.mappe.wurzel)
    assert geladen.einstellungen["modell_strategie"] == "claude-fable-5"


# --- Rueckfragen im Browser --------------------------------------------------


@pytest.fixture
def mappe_mit_fragen(mappe: Arbeitsmappe, tmp_path: Path) -> Arbeitsmappe:
    for name, betrag, frage in (
        ("darlehen.txt", 35000.0, "Klärung, ob und in welcher Höhe Zinsen anzusetzen sind"),
        ("abo.txt", 29.99, "Zuordnung, ob das Abo der Wohnungssuche diente"),
    ):
        quelle = tmp_path / name
        quelle.write_text(name, encoding="utf-8")
        dokument, _ = mappe.datei_aufnehmen(quelle, herkunft_jahr=2024)
        dokument.analyse = Analyse(
            kategorie_id="werbungskosten_sonstige",
            dokumenttyp=name,
            betrag_gesamt=betrag,
            steuerjahr=2024,
            fehlende_nachweise=[frage],
        )
    mappe.speichern()
    return mappe


def test_rueckfragen_seite_zeigt_teuersten_beleg_zuerst(mappe_mit_fragen):
    app = anwendung_bauen(mappe_mit_fragen)
    app.config["TESTING"] = True
    with app.test_client() as klient:
        text = klient.get("/rueckfragen").get_data(as_text=True)

    assert "Klärung, ob und in welcher Höhe Zinsen" in text
    # Die Handwerkerrechnung vermisst ein Dokument, keine Auskunft.
    assert "Kontoauszug zur Ueberweisung" not in text
    assert text.index("darlehen.txt") < text.index("abo.txt")


def test_antworten_lassen_sich_gesammelt_speichern(mappe_mit_fragen):
    app = anwendung_bauen(mappe_mit_fragen)
    app.config["TESTING"] = True
    darlehen = next(d for d in mappe_mit_fragen.dokumente if d.dateiname == "darlehen.txt")

    with app.test_client() as klient:
        antwort = klient.post(
            "/rueckfragen",
            data={f"notiz-{darlehen.id}": "Umschuldung, Zinsen anteilig"},
            follow_redirects=True,
        )
    assert antwort.status_code == 200

    wieder = Arbeitsmappe.laden(mappe_mit_fragen.wurzel)
    gespeichert = next(d for d in wieder.dokumente if d.dateiname == "darlehen.txt")
    assert gespeichert.notiz == "Umschuldung, Zinsen anteilig"


def test_leeres_feld_loescht_die_antwort(mappe_mit_fragen):
    app = anwendung_bauen(mappe_mit_fragen)
    app.config["TESTING"] = True
    darlehen = next(d for d in mappe_mit_fragen.dokumente if d.dateiname == "darlehen.txt")
    darlehen.notiz = "falsche Antwort"
    mappe_mit_fragen.speichern()

    with app.test_client() as klient:
        klient.post("/rueckfragen", data={f"notiz-{darlehen.id}": "  "}, follow_redirects=True)

    wieder = Arbeitsmappe.laden(mappe_mit_fragen.wurzel)
    assert not next(d for d in wieder.dokumente if d.dateiname == "darlehen.txt").notiz


def test_rueckfragen_seite_haelt_auch_leere_mappe_aus(tmp_path):
    leer = Arbeitsmappe.anlegen(tmp_path / "leer", 2024, Profil(veranlagungsjahr=2024))
    app = anwendung_bauen(leer)
    app.config["TESTING"] = True
    with app.test_client() as klient:
        antwort = klient.get("/rueckfragen")
    assert antwort.status_code == 200
    assert "Keine offenen Rueckfragen" in antwort.get_data(as_text=True)
