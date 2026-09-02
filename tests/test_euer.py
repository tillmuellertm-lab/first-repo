from steuer import euer
from steuer.models import Analyse, Dokument


def beleg(
    dateiname: str,
    betrag: float | None = None,
    *,
    geschaeftsvorfall: str = "",
    euer_posten: str = "",
    typ: str = "",
    aussteller: str = "",
    eignung: str = "geeignet",
    kategorie: str = "selbstaendig",
    mit_analyse: bool = True,
) -> Dokument:
    doc = Dokument(id=dateiname[:12], dateiname=dateiname)
    if mit_analyse:
        doc.analyse = Analyse(
            kategorie_id=kategorie,
            dokumenttyp=typ,
            aussteller=aussteller,
            betrag_gesamt=betrag,
            eignung=eignung,
            geschaeftsvorfall=geschaeftsvorfall,
            euer_posten=euer_posten,
        )
    return doc


def test_posten_ids_sind_eindeutig():
    assert len(euer.ids()) == len(set(euer.ids()))
    assert euer.SAMMELPOSTEN in euer.NACH_ID


def test_analyse_haelt_die_neuen_felder_ueber_einen_speicherzyklus():
    original = Analyse(geschaeftsvorfall="ausgabe", euer_posten="buero")
    wieder = Analyse.aus_dict(original.als_dict())
    assert wieder.geschaeftsvorfall == "ausgabe"
    assert wieder.euer_posten == "buero"


def test_summen_und_verlust():
    dokumente = [
        beleg("honorar.pdf", 1000.0, geschaeftsvorfall="einnahme", euer_posten="betriebseinnahmen"),
        beleg("laptop.pdf", 1200.0, geschaeftsvorfall="ausgabe", euer_posten="abschreibung"),
        beleg("porto.pdf", 300.0, geschaeftsvorfall="ausgabe", euer_posten="buero"),
    ]
    aufstellung = euer.aufstellen(dokumente, 2024)
    assert aufstellung.summe_einnahmen == 1000.0
    assert aufstellung.summe_ausgaben == 1500.0
    assert aufstellung.ergebnis == -500.0
    assert aufstellung.ist_verlust
    assert aufstellung.anzahl_belege == 3


def test_posten_aus_der_analyse_hat_vorrang_vor_stichworten():
    # Der Dateiname deutet auf Buerobedarf, die Analyse sagt Fortbildung.
    dokument = beleg(
        "software-rechnung.pdf",
        90.0,
        geschaeftsvorfall="ausgabe",
        euer_posten="fortbildung",
    )
    aufstellung = euer.aufstellen([dokument], 2024)
    assert [z.posten.id for z in aufstellung.ausgaben] == ["fortbildung"]


def test_posten_aus_der_analyse_wird_verworfen_wenn_die_richtung_nicht_passt():
    dokument = beleg(
        "zahlung.pdf",
        90.0,
        geschaeftsvorfall="ausgabe",
        euer_posten="betriebseinnahmen",  # ein Einnahmeposten
    )
    aufstellung = euer.aufstellen([dokument], 2024)
    assert not aufstellung.einnahmen
    assert [z.posten.id for z in aufstellung.ausgaben] == [euer.SAMMELPOSTEN]


def test_stichwortfallback_ohne_analysefelder():
    dokumente = [
        beleg("beleg-1.pdf", 60.0, typ="Tankstelle Quittung"),
        beleg("beleg-2.pdf", 500.0, typ="Ausgangsrechnung", aussteller="Kundin"),
    ]
    aufstellung = euer.aufstellen(dokumente, 2024)
    assert [z.posten.id for z in aufstellung.ausgaben] == ["fahrzeug"]
    assert [z.posten.id for z in aufstellung.einnahmen] == ["betriebseinnahmen"]


def test_unklare_richtung_wird_nicht_geraten():
    aufstellung = euer.aufstellen([beleg("scan-0815.pdf", 42.0)], 2024)
    assert aufstellung.summe_einnahmen == 0.0
    assert aufstellung.summe_ausgaben == 0.0
    assert [d.dateiname for d in aufstellung.ungeklaert] == ["scan-0815.pdf"]


def test_beleg_ohne_betrag_wird_getrennt_ausgewiesen():
    dokument = beleg("rahmenvertrag.pdf", None, geschaeftsvorfall="ausgabe", euer_posten="beratung")
    aufstellung = euer.aufstellen([dokument], 2024)
    assert [d.dateiname for d in aufstellung.ohne_betrag] == ["rahmenvertrag.pdf"]
    assert aufstellung.anzahl_belege == 0


def test_ungeeignete_und_unanalysierte_belege_bleiben_draussen():
    dokumente = [
        beleg("werbung.pdf", 50.0, geschaeftsvorfall="ausgabe", eignung="ungeeignet"),
        beleg("neu.pdf", mit_analyse=False),
    ]
    aufstellung = euer.aufstellen(dokumente, 2024)
    assert aufstellung.anzahl_belege == 0
    assert not aufstellung.ungeklaert
    assert not aufstellung.ohne_betrag


def test_negative_betraege_zaehlen_dem_betrag_nach():
    # Manche Belege weisen Ausgaben mit Minuszeichen aus.
    dokument = beleg("lastschrift.pdf", -80.0, geschaeftsvorfall="ausgabe", euer_posten="buero")
    aufstellung = euer.aufstellen([dokument], 2024)
    assert aufstellung.summe_ausgaben == 80.0


def test_csv_export_ist_deutsch_formatiert():
    dokumente = [
        beleg("honorar.pdf", 1234.5, geschaeftsvorfall="einnahme", euer_posten="betriebseinnahmen"),
        beleg("porto.pdf", 34.5, geschaeftsvorfall="ausgabe", euer_posten="buero"),
    ]
    text = euer.csv_export(euer.aufstellen(dokumente, 2024))
    zeilen = text.splitlines()
    assert zeilen[0].startswith("art;posten;")
    assert "1234,50" in text
    assert "Gewinn" in text
    assert "1200,00" in text


def test_markdown_bericht_nennt_verlust_und_offene_punkte():
    dokumente = [
        beleg("honorar.pdf", 100.0, geschaeftsvorfall="einnahme", euer_posten="betriebseinnahmen"),
        beleg("miete.pdf", 900.0, geschaeftsvorfall="ausgabe", euer_posten="raumkosten"),
        beleg("scan-0815.pdf", 42.0),
    ]
    text = euer.markdown_bericht(euer.aufstellen(dokumente, 2024), name="Praxis Mustermann")
    assert "Praxis Mustermann" in text
    assert "Verlust: 800,00 EUR" in text
    assert "ersetzt keine Einnahmen-Ueberschuss-Rechnung" in text
    assert "1 Beleg ohne klare Richtung" in text
    assert "scan-0815.pdf" in text
    # Der ungeklaerte Beleg darf die Summe nicht beeinflussen.
    assert "842" not in text


def test_arbeitslohn_wird_niemals_als_betriebseinnahme_gezaehlt():
    # Der Kern der Sperre: eine Lohnsteuerbescheinigung sieht nach einer
    # Auszahlung aus und wuerde sonst als Betriebseinnahme in die Summe gehen.
    lohn = beleg(
        "lohnsteuerbescheinigung.pdf",
        37391.40,
        typ="Lohnsteuerbescheinigung",
        aussteller="Arbeitgeber",
        kategorie="nichtselbstaendige_arbeit",
    )
    honorar = beleg(
        "honorar.pdf", 500.0, geschaeftsvorfall="einnahme", euer_posten="betriebseinnahmen"
    )
    aufstellung = euer.aufstellen([lohn, honorar], 2024)
    assert aufstellung.summe_einnahmen == 500.0
    assert [d.dateiname for d in aufstellung.privat] == ["lohnsteuerbescheinigung.pdf"]
    assert lohn not in aufstellung.ungeklaert


def test_alle_privaten_kategorien_werden_uebergangen():
    dokumente = [
        beleg(f"{kategorie}.pdf", 100.0, geschaeftsvorfall="einnahme", kategorie=kategorie)
        for kategorie in sorted(euer.PRIVATE_KATEGORIEN)
    ]
    aufstellung = euer.aufstellen(dokumente, 2024)
    assert aufstellung.summe_einnahmen == 0.0
    assert len(aufstellung.privat) == len(euer.PRIVATE_KATEGORIEN)


def test_neutrale_kategorien_bleiben_auswertbar():
    # Kassenbons landen oft unter 'unklar' oder 'nicht_steuerrelevant'; sie
    # duerfen nicht mit den privaten Unterlagen herausfallen.
    for kategorie in ("unklar", "nicht_steuerrelevant", "zahlungsnachweise", "selbstaendig"):
        dokument = beleg(
            "bon.pdf", 20.0, geschaeftsvorfall="ausgabe", euer_posten="buero", kategorie=kategorie
        )
        assert euer.aufstellen([dokument], 2024).summe_ausgaben == 20.0, kategorie


def test_bericht_weist_uebergangene_private_unterlagen_aus():
    dokumente = [
        beleg("honorar.pdf", 100.0, geschaeftsvorfall="einnahme", euer_posten="betriebseinnahmen"),
        beleg("rente.pdf", 9000.0, kategorie="renten"),
    ]
    text = euer.markdown_bericht(euer.aufstellen(dokumente, 2024))
    assert "1 Beleg" in text
    assert "private Unterlagen" in text
    assert "9.000" not in text


def test_herkunft_der_richtung_wird_gezaehlt():
    dokumente = [
        beleg("a.pdf", 100.0, geschaeftsvorfall="einnahme", euer_posten="betriebseinnahmen"),
        beleg("b.pdf", 60.0, typ="Tankstelle Quittung"),  # nur Stichwort
    ]
    aufstellung = euer.aufstellen(dokumente, 2024)
    assert aufstellung.aus_analyse == 1
    assert aufstellung.geschaetzt == 1
    assert not aufstellung.nur_geraten


def test_ohne_jede_analyseangabe_gilt_die_aufstellung_als_geraten():
    dokumente = [
        beleg("kontoauszug.pdf", 5000.0, typ="Gutschrift"),
        beleg("bon.pdf", 20.0, typ="Quittung"),
    ]
    aufstellung = euer.aufstellen(dokumente, 2024)
    assert aufstellung.nur_geraten
    text = euer.markdown_bericht(aufstellung)
    assert "nicht belastbar" in text
    assert "steuer analyse --alle" in text


def test_leere_aufstellung_gilt_nicht_als_geraten():
    aufstellung = euer.aufstellen([], 2024)
    assert not aufstellung.nur_geraten
    assert "nicht belastbar" not in euer.markdown_bericht(aufstellung)


def test_teilweise_geratene_aufstellung_nennt_den_anteil():
    dokumente = [
        beleg(f"a{i}.pdf", 100.0, geschaeftsvorfall="einnahme", euer_posten="betriebseinnahmen")
        for i in range(3)
    ] + [beleg("bon.pdf", 60.0, typ="Tankstelle Quittung")]
    text = euer.markdown_bericht(euer.aufstellen(dokumente, 2024))
    assert "1 Beleg (25%)" in text
    assert "nicht belastbar" not in text


def test_lange_listen_werden_gekuerzt():
    dokumente = [beleg(f"scan-{i}.pdf", 10.0) for i in range(40)]
    text = euer.markdown_bericht(euer.aufstellen(dokumente, 2024))
    assert "und 10 weitere" in text


def test_analyseversion_erkennt_alte_pruefungen():
    from steuer.models import ANALYSE_VERSION

    alt = Analyse.aus_dict({"dokumenttyp": "Bon"})
    assert alt.version == 0 and not alt.ist_aktuell
    assert Analyse(version=ANALYSE_VERSION).ist_aktuell
    # Ueber einen Speicherzyklus muss die Version erhalten bleiben.
    assert Analyse.aus_dict(Analyse(version=ANALYSE_VERSION).als_dict()).ist_aktuell


def test_taetigkeiten_stehen_im_systemprompt():
    from steuer import prompts, rules
    from steuer.models import Profil

    profil = Profil(veranlagungsjahr=2024, merkmale=["selbstaendig"], taetigkeiten="Tuftingstudio")
    text = prompts.system_analyse(rules.laden(2024), profil)
    assert "Tuftingstudio" in text
    assert "betrieblich veranlasst" in text
    # Ohne Angabe darf der Block nicht erscheinen.
    ohne = prompts.system_analyse(rules.laden(2024), Profil(veranlagungsjahr=2024, name="X"))
    assert "Berufe und Betriebe im Haushalt" not in ohne


def test_ausschnitt_eines_langen_pdf(tmp_path):
    """Ein 42-seitiges PDF muss sich ab einer beliebigen Seite pruefen lassen."""
    from pypdf import PdfWriter

    from steuer.extract import inhalt_aufbereiten

    pfad = tmp_path / "erklaerung.pdf"
    schreiber = PdfWriter()
    for _ in range(42):
        schreiber.add_blank_page(width=200, height=200)
    with pfad.open("wb") as datei:
        schreiber.write(datei)

    vorne = inhalt_aufbereiten(pfad, "application/pdf")
    assert vorne.gekuerzt
    assert any("ersten 30" in h for h in vorne.hinweise)

    hinten = inhalt_aufbereiten(pfad, "application/pdf", ab_seite=31)
    assert any("31 bis 42" in h for h in hinten.hinweise)
    # Der Ausschnitt muss kleiner sein als das ganze Dokument.
    assert hinten.bloecke[0]["source"]["data"] != vorne.bloecke[0]["source"]["data"]


def test_gekuerzte_dokumente_werden_als_warnung_gemeldet():
    from steuer import gaps, rules
    from steuer.models import Profil

    dokument = beleg("erklaerung-2023.pdf", 0.0, kategorie="vorjahr")
    dokument.seiten = 42
    dokument.analyse.hinweise = ["Nur die ersten 30 von 42 Seiten wurden analysiert."]
    ergebnis = gaps.auswerten([dokument], rules.laden(2024), Profil(veranlagungsjahr=2024))
    warnung = [b for b in ergebnis.warnungen if b.id == "nur_teilweise_geprueft"]
    assert warnung, "Die Kuerzung muss auffallen"
    assert "--ab-seite" in warnung[0].beschreibung


def test_analysen_verbinden_verliert_nichts():
    from steuer.cli import _analysen_verbinden

    alt = Analyse(
        zusammenfassung="Vordere Seiten: Mantelbogen.",
        hinweise=["Nur die ersten 30 von 42 Seiten wurden analysiert."],
        betrag_gesamt=100.0,
        aussteller="Finanzamt Koeln-Sued",
    )
    neu = Analyse(zusammenfassung="Anlage V mit Gebaeude-AfA 7.177 EUR.")
    _analysen_verbinden(alt, neu, 31)
    assert "Mantelbogen" in neu.zusammenfassung and "Anlage V" in neu.zusammenfassung
    assert "Nur die ersten 30 von 42 Seiten wurden analysiert." in neu.hinweise
    assert neu.betrag_gesamt == 100.0
    assert neu.aussteller == "Finanzamt Koeln-Sued"
