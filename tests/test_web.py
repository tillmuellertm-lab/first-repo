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


# --- Dubletten im Browser ----------------------------------------------------


@pytest.fixture
def mappe_mit_dubletten(mappe: Arbeitsmappe, tmp_path: Path) -> Arbeitsmappe:
    """Derselbe Beleg aus zwei Stapeln, dazu ein Einzelstueck ohne Partner."""
    for name in ("gehalt_scan_a.txt", "gehalt_scan_b.txt"):
        quelle = tmp_path / name
        quelle.write_text(name, encoding="utf-8")
        dokument, _ = mappe.datei_aufnehmen(quelle, herkunft_jahr=2024)
        dokument.analyse = Analyse(
            kategorie_id="werbungskosten_sonstige",
            dokumenttyp="Gehaltsabrechnung",
            aussteller="RasenBallsport",
            datum="2024-07-31",
            steuerjahr=2024,
            betrag_gesamt=7743.62,
        )

    einzeln = tmp_path / "einmalig.txt"
    einzeln.write_text("einmalig", encoding="utf-8")
    dokument, _ = mappe.datei_aufnehmen(einzeln, herkunft_jahr=2024)
    dokument.analyse = Analyse(
        kategorie_id="werbungskosten_sonstige",
        dokumenttyp="Tankbeleg",
        aussteller="Aral",
        datum="2024-09-01",
        steuerjahr=2024,
        betrag_gesamt=61.4,
    )
    mappe.speichern()
    return mappe


def test_dublettenseite_zeigt_nur_doppelte_belege(mappe_mit_dubletten):
    app = anwendung_bauen(mappe_mit_dubletten)
    app.config["TESTING"] = True
    with app.test_client() as klient:
        text = klient.get("/dubletten").get_data(as_text=True)

    assert "gehalt_scan_a.txt" in text
    assert "gehalt_scan_b.txt" in text
    assert "einmalig.txt" not in text


def test_dublette_wird_nur_fuer_angehakte_ids_entfernt(mappe_mit_dubletten):
    app = anwendung_bauen(mappe_mit_dubletten)
    app.config["TESTING"] = True
    zweiter = next(d for d in mappe_mit_dubletten.dokumente if d.dateiname == "gehalt_scan_b.txt")

    with app.test_client() as klient:
        antwort = klient.post("/dubletten", data={"entfernen": zweiter.id}, follow_redirects=True)
    assert antwort.status_code == 200

    wieder = Arbeitsmappe.laden(mappe_mit_dubletten.wurzel)
    namen = [d.dateiname for d in wieder.dokumente]
    assert "gehalt_scan_b.txt" not in namen
    assert "gehalt_scan_a.txt" in namen
    assert "einmalig.txt" in namen


def test_dublettenseite_haelt_auch_leere_mappe_aus(tmp_path):
    leer = Arbeitsmappe.anlegen(tmp_path / "leer", 2024, Profil(veranlagungsjahr=2024))
    app = anwendung_bauen(leer)
    app.config["TESTING"] = True
    with app.test_client() as klient:
        antwort = klient.get("/dubletten")
    assert antwort.status_code == 200
    assert "Keine Dubletten gefunden" in antwort.get_data(as_text=True)


# --- Beratung im Browser -----------------------------------------------------


def test_beratungsseite_rendert_leeres_gespraech(klient):
    antwort = klient.get("/beratung")
    assert antwort.status_code == 200
    assert "Noch kein Gespraech" in antwort.get_data(as_text=True)


def test_beratungsseite_zeigt_den_gespeicherten_verlauf(klient):
    from steuer import berater

    gespraech = berater.Gespraech()
    gespraech.anhaengen("user", [{"type": "text", "text": "Fehlt mir noch etwas?"}])
    gespraech.anhaengen("assistant", [{"type": "text", "text": "Die Zinsbescheinigung fehlt."}])
    berater.speichern(klient.mappe, gespraech)

    text = klient.get("/beratung").get_data(as_text=True)
    assert "Fehlt mir noch etwas?" in text
    assert "Die Zinsbescheinigung fehlt." in text

    stand = klient.get("/api/beratung").get_json()
    assert stand["laeuft"] is False
    assert [b["rolle"] for b in stand["beitraege"]] == ["mandant", "berater"]


def test_beratung_ohne_schluessel_wird_abgelehnt(klient, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    antwort = klient.post("/api/beratung", json={"nachricht": "Hallo"})
    assert antwort.status_code == 400
    assert "ANTHROPIC_API_KEY" in antwort.get_json()["fehler"]


def test_leere_nachricht_wird_abgelehnt(klient, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    antwort = klient.post("/api/beratung", json={"nachricht": "   "})
    assert antwort.status_code == 400


def test_gespraech_laesst_sich_verwerfen(klient):
    from steuer import berater

    gespraech = berater.Gespraech()
    gespraech.anhaengen("user", [{"type": "text", "text": "Alte Frage"}])
    berater.speichern(klient.mappe, gespraech)

    klient.post("/beratung/loeschen", follow_redirects=True)
    assert berater.laden(klient.mappe).nachrichten == []


def test_entwurf_wird_angezeigt_und_verlinkt(klient):
    from steuer import berater, rules

    berater.werkzeug_ausfuehren(
        "schreiben_entwerfen",
        {"titel": "Mail an den Steuerberater", "text": "Sehr geehrter Herr Dr. Hagn,"},
        klient.mappe,
        rules.laden(2024),
    )
    seite = klient.get("/beratung").get_data(as_text=True)
    assert "Mail-an-den-Steuerberater" in seite

    name = berater.entwuerfe(klient.mappe)[0]
    entwurf = klient.get(f"/entwurf/{name}")
    assert entwurf.status_code == 200
    assert "Sehr geehrter Herr Dr. Hagn," in entwurf.get_data(as_text=True)


def test_unbekannter_entwurf_ergibt_404(klient):
    assert klient.get("/entwurf/gibtsnicht.md").status_code == 404


def test_verbesserungsliste_wird_verlinkt_und_angezeigt(klient):
    from steuer import berater, rules

    assert klient.get("/verbesserungen").status_code == 404
    berater.werkzeug_ausfuehren(
        "verbesserung_vorschlagen",
        {
            "titel": "Belege anderer Mappen sehen",
            "anlass": "Nach der EUeR der Ehefrau gefragt, sie liegt in einer anderen Mappe.",
            "beschreibung": "Ein Werkzeug, das mappenuebergreifend sucht.",
        },
        klient.mappe,
        rules.laden(2024),
    )
    assert "Was diesem Werkzeug fehlt" in klient.get("/beratung").get_data(as_text=True)
    seite = klient.get("/verbesserungen")
    assert seite.status_code == 200
    assert "Belege anderer Mappen sehen" in seite.get_data(as_text=True)


# --- Bildschirmfotos im Gespraech --------------------------------------------


def _png_base64() -> str:
    return (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )


def test_bild_wird_angenommen_und_ausgeliefert(klient, monkeypatch):
    from steuer import berater

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    # Der Modellaufruf selbst wird nicht gebraucht: geprueft wird, dass das
    # Bild ankommt, bevor der Hintergrundlauf ueberhaupt beginnt.
    monkeypatch.setattr(berater, "nachricht_senden", lambda *a, **k: None)

    antwort = klient.post(
        "/api/beratung",
        json={
            "nachricht": "Was steht auf diesem Bildschirmfoto?",
            "bilder": [{"medientyp": "image/png", "daten": _png_base64()}],
        },
    )
    assert antwort.status_code == 200

    name = next(p.name for p in berater.bilderordner(klient.mappe).iterdir())
    bild = klient.get(f"/gespraechsbild/{name}")
    assert bild.status_code == 200
    assert klient.get("/gespraechsbild/gibtsnicht.png").status_code == 404


def test_unbrauchbares_bild_wird_sofort_abgelehnt(klient, monkeypatch):
    """Der Fehler soll kommen, bevor eine Minute Arbeit vergeht."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    antwort = klient.post(
        "/api/beratung",
        json={"nachricht": "hier", "bilder": [{"medientyp": "application/pdf", "daten": "AAAA"}]},
    )
    assert antwort.status_code == 400
    assert "Bild abgelehnt" in antwort.get_json()["fehler"]


def test_nachricht_nur_aus_einem_bild_ist_erlaubt(klient, monkeypatch):
    from steuer import berater

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(berater, "nachricht_senden", lambda *a, **k: None)
    antwort = klient.post(
        "/api/beratung",
        json={"nachricht": "", "bilder": [{"medientyp": "image/png", "daten": _png_base64()}]},
    )
    assert antwort.status_code == 200


def test_formularseite_ordnet_die_kategorien_zu(klient):
    seite = klient.get("/formular")
    assert seite.status_code == 200
    text = seite.get_data(as_text=True)
    assert "Anlage Haushaltsnahe Aufwendungen" in text
    assert "Handwerkerleistungen" in text
    # Solange die Zeilennummern nicht geprueft sind, muss das dabeistehen.
    assert "nicht amtlich geprueft" in text


def test_formularseite_haelt_auch_leere_mappe_aus(tmp_path):
    leer = Arbeitsmappe.anlegen(tmp_path / "leer", 2024, Profil(veranlagungsjahr=2024))
    app = anwendung_bauen(leer)
    app.config["TESTING"] = True
    with app.test_client() as klient:
        antwort = klient.get("/formular")
    assert antwort.status_code == 200
    assert "Noch nichts zuzuordnen" in antwort.get_data(as_text=True)
