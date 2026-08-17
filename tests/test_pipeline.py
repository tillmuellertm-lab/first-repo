"""Ablauf vom Aufnehmen der Datei bis zum fertigen Bericht, ohne API-Aufruf."""

from pathlib import Path

import pytest

from steuer import extract, gaps, naming, organize, report, rules
from steuer.models import Analyse, Profil
from steuer.workspace import Arbeitsmappe, ArbeitsmappenFehler, sichere_bezeichnung

REGELWERK = rules.laden(2024, strikt=True)


@pytest.fixture
def mappe(tmp_path: Path) -> Arbeitsmappe:
    profil = Profil(
        name="Testperson",
        veranlagungsjahr=2024,
        merkmale=["angestellt", "eigener_haushalt", "mieter", "pendler"],
        entfernung_km=25,
        arbeitstage=220,
        gesamtbetrag_der_einkuenfte=55000,
    )
    return Arbeitsmappe.anlegen(tmp_path / "mappe", 2024, profil)


def _datei(tmp_path: Path, name: str, inhalt: str = "Testinhalt") -> Path:
    pfad = tmp_path / name
    pfad.write_text(inhalt, encoding="utf-8")
    return pfad


# ------------------------------------------------------------- Arbeitsmappe --

def test_anlegen_erzeugt_struktur(mappe: Arbeitsmappe):
    assert (mappe.wurzel / "steuer.json").exists()
    assert mappe.eingang.is_dir()
    assert mappe.berichte.is_dir()


def test_laden_stellt_profil_wieder_her(mappe: Arbeitsmappe):
    geladen = Arbeitsmappe.laden(mappe.wurzel)
    assert geladen.jahr == 2024
    assert geladen.profil.name == "Testperson"
    assert "pendler" in geladen.profil.merkmale
    assert geladen.profil.entfernung_km == 25


def test_datei_aufnehmen_und_dublette_erkennen(mappe: Arbeitsmappe, tmp_path: Path):
    quelle = _datei(tmp_path, "beleg.txt", "Rechnung ueber 100 Euro")
    dokument, neu = mappe.datei_aufnehmen(quelle)
    assert neu and dokument.sha256
    kopie = _datei(tmp_path, "beleg-kopie.txt", "Rechnung ueber 100 Euro")
    _, nochmal_neu = mappe.datei_aufnehmen(kopie)
    assert not nochmal_neu
    assert len(mappe.dokumente) == 1


def test_unbekannter_dateityp_wird_abgelehnt(mappe: Arbeitsmappe, tmp_path: Path):
    quelle = _datei(tmp_path, "beleg.exe")
    with pytest.raises(ArbeitsmappenFehler):
        mappe.datei_aufnehmen(quelle)


def test_eingang_einlesen_nimmt_direkt_abgelegte_dateien_auf(mappe: Arbeitsmappe):
    (mappe.eingang / "direkt.txt").write_text("Beleg", encoding="utf-8")
    neue = mappe.eingang_einlesen()
    assert [d.dateiname for d in neue] == ["direkt.txt"]


def test_namenskollision_im_eingang_wird_aufgeloest(mappe: Arbeitsmappe, tmp_path: Path):
    ordner_a = tmp_path / "a"
    ordner_b = tmp_path / "b"
    ordner_a.mkdir()
    ordner_b.mkdir()
    (ordner_a / "beleg.txt").write_text("erster Beleg", encoding="utf-8")
    (ordner_b / "beleg.txt").write_text("zweiter Beleg", encoding="utf-8")
    erste, _ = mappe.datei_aufnehmen(ordner_a / "beleg.txt")
    zweite, neu = mappe.datei_aufnehmen(ordner_b / "beleg.txt")
    assert neu
    assert erste.dateiname != zweite.dateiname
    assert (mappe.eingang / zweite.dateiname).exists()


# ------------------------------------------------------------------ Namen --

def test_sichere_bezeichnung_wandelt_umlaute():
    assert sichere_bezeichnung("Müller & Söhne GmbH") == "Mueller-Soehne-GmbH"
    assert sichere_bezeichnung("  ") == ""


def test_dateiname_enthaelt_alle_bestandteile(mappe: Arbeitsmappe, tmp_path: Path):
    dokument, _ = mappe.datei_aufnehmen(_datei(tmp_path, "scan.pdf"))
    dokument.analyse = Analyse(
        kategorie_id="haushaltsnahe_aufwendungen",
        dokumenttyp="Handwerkerrechnung",
        aussteller="Elektro Müller",
        datum="2024-03-15",
        betrag_abzugsfaehig=1189.42,
        eignung="bedingt_geeignet",
    )
    name = naming.dateiname(dokument, 3, 2024)
    assert name.startswith("03_2024-03-15_Handwerkerrechnung_Elektro-Mueller_1189-42EUR")
    assert name.endswith("_PRUEFEN.pdf")


def test_dateiname_ohne_analyse_faellt_auf_originalnamen_zurueck(mappe: Arbeitsmappe, tmp_path: Path):
    dokument, _ = mappe.datei_aufnehmen(_datei(tmp_path, "unbekannt.pdf"))
    name = naming.dateiname(dokument, 1, 2024)
    assert name == "01_2024-00-00_unbekannt.pdf"


def test_eindeutig_machen_haengt_zaehler_an():
    vergeben: set[str] = set()
    assert naming.eindeutig_machen("a.pdf", vergeben) == "a.pdf"
    assert naming.eindeutig_machen("a.pdf", vergeben) == "a-2.pdf"
    assert naming.eindeutig_machen("a.pdf", vergeben) == "a-3.pdf"


# ------------------------------------------------------------- Gesamtlauf --

def _befuellen(mappe: Arbeitsmappe, tmp_path: Path) -> None:
    belege = [
        ("lohn.pdf", "nichtselbstaendige_arbeit", "Lohnsteuerbescheinigung", "Arbeitgeber AG", 52000.0, "geeignet"),
        ("handwerker.pdf", "haushaltsnahe_aufwendungen", "Handwerkerrechnung", "Elektro Müller", 890.0, "geeignet"),
        ("nebenkosten.pdf", "haushaltsnahe_aufwendungen", "Nebenkostenabrechnung", "Hausverwaltung", 310.0, "bedingt_geeignet"),
        ("werbung.pdf", "nicht_steuerrelevant", "Werbeschreiben", "Versand", None, "ungeeignet"),
        ("spende.pdf", "sonderausgaben", "Zuwendungsbestaetigung", "Tierheim", 120.0, "geeignet"),
    ]
    for name, kategorie, typ, aussteller, betrag, eignung in belege:
        quelle = tmp_path / name
        quelle.write_text(f"Inhalt von {name}", encoding="utf-8")
        # Textdateien mit PDF-Endung wuerden abgelehnt, daher ueber .txt aufnehmen.
        quelle_txt = quelle.with_suffix(".txt")
        quelle_txt.write_text(f"Inhalt von {name}", encoding="utf-8")
        dokument, _ = mappe.datei_aufnehmen(quelle_txt)
        dokument.analyse = Analyse(
            kategorie_id=kategorie,
            dokumenttyp=typ,
            aussteller=aussteller,
            datum="2024-06-01",
            steuerjahr=2024,
            betrag_gesamt=betrag,
            betrag_abzugsfaehig=betrag,
            eignung=eignung,
            vertrauen=0.9,
            zusammenfassung=f"{typ} von {aussteller}",
            fehlende_nachweise=["Zahlungsnachweis"] if eignung == "bedingt_geeignet" else [],
        )
        dokument.status = "analysiert"
    mappe.speichern()


def test_ablage_sortiert_nach_anlagen(mappe: Arbeitsmappe, tmp_path: Path):
    _befuellen(mappe, tmp_path)
    ablage = organize.ablage_erzeugen(mappe)
    assert ablage.anzahl == 5
    ordner = {p.name for p in ablage.wurzel.iterdir() if p.is_dir()}
    assert "10_Anlage_N_Einkuenfte" in ordner
    assert "34_Haushaltsnahe_Aufwendungen" in ordner
    assert "99_Nicht_steuerrelevant" in ordner
    inhalt = (ablage.wurzel / "34_Haushaltsnahe_Aufwendungen" / "_INHALT.md").read_text(encoding="utf-8")
    assert "Handwerkerrechnung" in inhalt
    assert "Fehlt noch: Zahlungsnachweis" in inhalt


def test_ablage_kann_ungeeignete_weglassen(mappe: Arbeitsmappe, tmp_path: Path):
    _befuellen(mappe, tmp_path)
    ablage = organize.ablage_erzeugen(mappe, ungeeignete_mitnehmen=False)
    assert not (ablage.wurzel / "99_Nicht_steuerrelevant").exists()
    assert ablage.uebersprungen


def test_ablage_wird_bei_erneutem_lauf_neu_aufgebaut(mappe: Arbeitsmappe, tmp_path: Path):
    _befuellen(mappe, tmp_path)
    erste = organize.ablage_erzeugen(mappe)
    fremd = erste.wurzel / "10_Anlage_N_Einkuenfte" / "altlast.pdf"
    fremd.write_text("alt", encoding="utf-8")
    zweite = organize.ablage_erzeugen(mappe)
    assert not fremd.exists()
    assert zweite.anzahl == 5


def test_berichte_werden_geschrieben(mappe: Arbeitsmappe, tmp_path: Path):
    _befuellen(mappe, tmp_path)
    organize.ablage_erzeugen(mappe)
    auswertung = gaps.auswerten(mappe.dokumente, REGELWERK, mappe.profil)
    pfade = report.berichte_schreiben(
        mappe.berichte, mappe.dokumente, auswertung, REGELWERK, mappe.profil
    )
    assert len(pfade) == 3
    html = (mappe.berichte / "Uebersicht_2024.html").read_text(encoding="utf-8")
    assert "Steuerunterlagen 2024" in html
    assert "Handwerkerrechnung" in html
    assert "Steuerberatung" in html  # Haftungshinweis
    markdown = (mappe.berichte / "Uebersicht_2024.md").read_text(encoding="utf-8")
    assert "## Unterlagen nach Anlagen" in markdown
    csv_inhalt = (mappe.berichte / "Dokumentliste_2024.csv").read_text(encoding="utf-8-sig")
    assert "ordner;zieldatei" in csv_inhalt
    assert csv_inhalt.count("\n") == 6  # Kopfzeile plus fuenf Dokumente


def test_html_bericht_maskiert_sonderzeichen(mappe: Arbeitsmappe, tmp_path: Path):
    _befuellen(mappe, tmp_path)
    mappe.dokumente[0].analyse.aussteller = "<script>alert(1)</script>"
    auswertung = gaps.auswerten(mappe.dokumente, REGELWERK, mappe.profil)
    html = report.html_bericht(mappe.dokumente, auswertung, REGELWERK, mappe.profil)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_paket_enthaelt_ablage_und_berichte(mappe: Arbeitsmappe, tmp_path: Path):
    import zipfile

    _befuellen(mappe, tmp_path)
    ablage = organize.ablage_erzeugen(mappe)
    auswertung = gaps.auswerten(mappe.dokumente, REGELWERK, mappe.profil)
    berichte = report.berichte_schreiben(
        mappe.berichte, mappe.dokumente, auswertung, REGELWERK, mappe.profil
    )
    paket = organize.paket_erzeugen(mappe, ablage, berichte)
    with zipfile.ZipFile(paket) as archiv:
        namen = archiv.namelist()
    assert any("34_Haushaltsnahe_Aufwendungen" in n for n in namen)
    assert any(n.endswith("Uebersicht_2024.html") for n in namen)


def test_auswertung_findet_chancen_und_luecken(mappe: Arbeitsmappe, tmp_path: Path):
    _befuellen(mappe, tmp_path)
    auswertung = gaps.auswerten(mappe.dokumente, REGELWERK, mappe.profil)
    assert auswertung.kennzahlen["haushaltsnahe_aufwendungen_gesamt"] == 1200.0
    ids = {b.id for b in auswertung.chancen}
    assert "entfernungspauschale_berechnet" in ids
    assert "regel_nebenkostenabrechnung" in ids  # Merkmal "mieter"
    assert any(b.id == "fehlende_nachweise" for b in auswertung.luecken)


# --------------------------------------------------- Schutz vor Riesendateien --

def _pdf_erzeugen(pfad: Path, seiten: int) -> Path:
    """Legt ein minimales PDF mit der gewuenschten Seitenzahl an."""
    import pypdf

    schreiber = pypdf.PdfWriter()
    for _ in range(seiten):
        schreiber.add_blank_page(width=200, height=200)
    with pfad.open("wb") as datei:
        schreiber.write(datei)
    return pfad


def test_langes_pdf_wird_auf_seitengrenze_gekuerzt(tmp_path: Path):
    pfad = _pdf_erzeugen(tmp_path / "sammelscan.pdf", extract.MAX_PDF_SEITEN + 25)
    inhalt = extract.inhalt_aufbereiten(pfad, "application/pdf")
    assert inhalt.gekuerzt
    assert any("Seiten" in h for h in inhalt.hinweise)


def test_zu_grosse_datei_wird_mit_klarem_hinweis_abgelehnt(tmp_path: Path, monkeypatch):
    """Statt an der Kontextgrenze der API zu scheitern, soll das Tool selbst bremsen."""
    pfad = _pdf_erzeugen(tmp_path / "riesig.pdf", 5)
    monkeypatch.setattr(extract, "MAX_PDF_BYTES", 100)
    with pytest.raises(extract.ExtraktionsFehler) as fehler:
        extract.inhalt_aufbereiten(pfad, "application/pdf")
    assert "zu gross" in str(fehler.value)
    assert "aufteilen" in str(fehler.value)


def test_pdf_ohne_lesbare_seitenzahl_wird_vorsorglich_gekuerzt(tmp_path: Path, monkeypatch):
    pfad = _pdf_erzeugen(tmp_path / "eigenartig.pdf", 3)
    monkeypatch.setattr(extract, "seitenzahl", lambda _p: None)
    inhalt = extract.inhalt_aufbereiten(pfad, "application/pdf")
    assert inhalt.gekuerzt
    assert any("nicht ermittelbar" in h for h in inhalt.hinweise)


# ------------------------------------------------------------ Ausgliedern --

def test_dokument_mit_analyse_in_andere_mappe_uebernehmen(mappe: Arbeitsmappe, tmp_path: Path):
    """Beim Verschieben muss die Analyse erhalten bleiben."""
    quelle = _datei(tmp_path, "gewerbe.txt", "Eingangsrechnung")
    dokument, _ = mappe.datei_aufnehmen(quelle)
    dokument.analyse = Analyse(
        kategorie_id="selbstaendig",
        dokumenttyp="Eingangsrechnung",
        betrag_gesamt=119.0,
        eignung="bedingt_geeignet",
        zusammenfassung="Wareneinkauf",
    )
    dokument.status = "analysiert"
    dokument.zieldateiname = "alt.pdf"

    ziel = Arbeitsmappe.anlegen(tmp_path / "gewerbe", 2024, Profil(veranlagungsjahr=2024))
    assert ziel.dokument_uebernehmen(dokument, mappe.pfad_zu(dokument))

    uebernommen = ziel.dokumente[0]
    assert uebernommen.analyse is not None
    assert uebernommen.analyse.dokumenttyp == "Eingangsrechnung"
    assert uebernommen.analyse.betrag_gesamt == 119.0
    assert uebernommen.status == "analysiert"
    assert (ziel.eingang / uebernommen.dateiname).exists()
    # die Ablage der neuen Mappe wird frisch aufgebaut
    assert uebernommen.zieldateiname == ""


def test_uebernehmen_erkennt_dublette(mappe: Arbeitsmappe, tmp_path: Path):
    quelle = _datei(tmp_path, "beleg.txt", "derselbe Inhalt")
    dokument, _ = mappe.datei_aufnehmen(quelle)
    ziel = Arbeitsmappe.anlegen(tmp_path / "ziel", 2024, Profil(veranlagungsjahr=2024))
    assert ziel.dokument_uebernehmen(dokument, mappe.pfad_zu(dokument))
    assert not ziel.dokument_uebernehmen(dokument, mappe.pfad_zu(dokument))
    assert len(ziel.dokumente) == 1


def test_uebernehmen_loest_namenskollision_auf(mappe: Arbeitsmappe, tmp_path: Path):
    ziel = Arbeitsmappe.anlegen(tmp_path / "ziel", 2024, Profil(veranlagungsjahr=2024))
    (ziel.eingang / "beleg.txt").write_text("schon da", encoding="utf-8")

    quelle = _datei(tmp_path, "beleg.txt", "anderer Inhalt")
    dokument, _ = mappe.datei_aufnehmen(quelle)
    assert ziel.dokument_uebernehmen(dokument, mappe.pfad_zu(dokument))
    assert ziel.dokumente[0].dateiname != "beleg.txt"
    assert (ziel.eingang / "beleg.txt").read_text(encoding="utf-8") == "schon da"
