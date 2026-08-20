"""Herkunftsangabe beim Aufnehmen: Wissen des Nutzers schlaegt Textanalyse."""

from pathlib import Path

from steuer import euer
from steuer.models import Analyse, Dokument, HERKUNFT_IDS, Profil
from steuer.workspace import Arbeitsmappe


def _datei(ordner: Path, name: str, inhalt: str = "Beleg") -> Path:
    pfad = ordner / name
    pfad.write_text(inhalt, encoding="utf-8")
    return pfad


def test_herkunft_wird_beim_aufnehmen_gespeichert(tmp_path):
    mappe = Arbeitsmappe.anlegen(tmp_path / "mappe", 2024)
    quelle = _datei(tmp_path, "wollgarn.txt")
    dokument, neu = mappe.datei_aufnehmen(quelle, herkunft="gewerbe", herkunft_jahr=2025)
    assert neu
    assert dokument.herkunft == "gewerbe"
    assert dokument.herkunft_jahr == 2025


def test_herkunft_ueberlebt_das_speichern(tmp_path):
    mappe = Arbeitsmappe.anlegen(tmp_path / "mappe", 2024)
    mappe.datei_aufnehmen(_datei(tmp_path, "beleg.txt"), herkunft="vermietung", herkunft_jahr=2024)
    mappe.speichern()
    wieder = Arbeitsmappe.laden(mappe.wurzel)
    assert wieder.dokumente[0].herkunft == "vermietung"
    assert wieder.dokumente[0].herkunft_jahr == 2024


def test_dublette_traegt_fehlende_herkunft_nach(tmp_path):
    mappe = Arbeitsmappe.anlegen(tmp_path / "mappe", 2024)
    quelle = _datei(tmp_path, "beleg.txt")
    mappe.datei_aufnehmen(quelle)
    zweitname = _datei(tmp_path, "beleg-kopie.txt")  # gleicher Inhalt, anderer Name
    dokument, neu = mappe.datei_aufnehmen(zweitname, herkunft="gewerbe")
    assert not neu, "gleicher Inhalt = Dublette"
    assert dokument.herkunft == "gewerbe", "die Angabe darf nicht verlorengehen"
    assert len(mappe.dokumente) == 1


def test_vorhandene_herkunft_wird_nicht_ueberschrieben(tmp_path):
    mappe = Arbeitsmappe.anlegen(tmp_path / "mappe", 2024)
    quelle = _datei(tmp_path, "beleg.txt")
    mappe.datei_aufnehmen(quelle, herkunft="privat")
    dokument, _ = mappe.datei_aufnehmen(_datei(tmp_path, "kopie.txt"), herkunft="gewerbe")
    assert dokument.herkunft == "privat"


def test_jahr_des_nutzers_hat_vorrang_vor_der_analyse():
    dokument = Dokument(id="a", dateiname="bon.pdf", herkunft_jahr=2025)
    dokument.analyse = Analyse(steuerjahr=2024)
    assert dokument.gehoert_ins_jahr == 2025

    ohne_angabe = Dokument(id="b", dateiname="bon.pdf")
    ohne_angabe.analyse = Analyse(steuerjahr=2024)
    assert ohne_angabe.gehoert_ins_jahr == 2024

    ganz_ohne = Dokument(id="c", dateiname="bon.pdf")
    assert ganz_ohne.gehoert_ins_jahr is None


def test_euer_nimmt_gewerbebelege_unabhaengig_von_der_kategorie():
    """Ein Kassenbon landet unter 'nicht_steuerrelevant' - die Angabe rettet ihn."""
    bon = Dokument(id="a", dateiname="wollgarn.pdf", herkunft="gewerbe")
    bon.analyse = Analyse(
        kategorie_id="nicht_steuerrelevant",
        eignung="geeignet",
        betrag_gesamt=148.92,
        geschaeftsvorfall="ausgabe",
        euer_posten="wareneinkauf",
    )
    aufstellung = euer.aufstellen([bon], 2024)
    assert aufstellung.summe_ausgaben == 148.92
    assert not aufstellung.privat


def test_euer_haelt_privatbelege_draussen_trotz_passender_kategorie():
    beleg = Dokument(id="a", dateiname="material.pdf", herkunft="privat")
    beleg.analyse = Analyse(
        kategorie_id="selbstaendig",
        eignung="geeignet",
        betrag_gesamt=99.0,
        geschaeftsvorfall="ausgabe",
        euer_posten="wareneinkauf",
    )
    aufstellung = euer.aufstellen([beleg], 2024)
    assert aufstellung.summe_ausgaben == 0.0
    assert [d.dateiname for d in aufstellung.privat] == ["material.pdf"]


def test_nachzutragen_beruecksichtigt_den_kontext(tmp_path):
    from steuer.models import ANALYSE_VERSION

    mappe = Arbeitsmappe.anlegen(tmp_path / "mappe", 2024, Profil(veranlagungsjahr=2024))
    dokument = Dokument(id="a", dateiname="beleg.pdf")
    dokument.status = "analysiert"
    dokument.analyse = Analyse(
        version=ANALYSE_VERSION, kontext=mappe.kontext_pruefsumme()
    )
    mappe.dokumente.append(dokument)
    assert mappe.nachzutragen() == []

    mappe.profil.taetigkeiten = "Tuftingstudio"
    assert len(mappe.nachzutragen()) == 1


def test_herkunftskennungen_sind_stabil():
    # Die Kennungen stehen in gespeicherten Mappen; sie duerfen sich nicht
    # unbemerkt aendern.
    assert HERKUNFT_IDS == {"privat", "gewerbe", "vermietung", "gemischt"}


def test_jahresansicht_teilt_den_bestand(tmp_path):
    mappe = Arbeitsmappe.anlegen(tmp_path / "mappe", 2024)
    for name, jahr in (("a.pdf", 2024), ("b.pdf", 2025), ("c.pdf", None)):
        dokument = Dokument(id=name[0], dateiname=name, herkunft_jahr=jahr)
        mappe.dokumente.append(dokument)

    ansicht = mappe.jahresansicht()
    assert [d.dateiname for d in ansicht.eigene] == ["a.pdf"]
    assert [d.dateiname for d in ansicht.fremde] == ["b.pdf"]
    assert [d.dateiname for d in ansicht.ohne_jahr] == ["c.pdf"]
    assert ansicht.anzahl_gesamt == 3
    assert ansicht.fremde_jahre() == {2025: 1}


def test_jahresansicht_folgt_der_analyse_wenn_nichts_gesetzt_ist(tmp_path):
    mappe = Arbeitsmappe.anlegen(tmp_path / "mappe", 2024)
    dokument = Dokument(id="a", dateiname="a.pdf")
    dokument.analyse = Analyse(steuerjahr=2025)
    mappe.dokumente.append(dokument)
    assert len(mappe.jahresansicht().fremde) == 1

    # Die Angabe des Nutzers holt es zurueck.
    dokument.herkunft_jahr = 2024
    assert len(mappe.jahresansicht().eigene) == 1


def test_jahresverteilung(tmp_path):
    mappe = Arbeitsmappe.anlegen(tmp_path / "mappe", 2024)
    for name, jahr in (("a", 2024), ("b", 2024), ("c", 2025), ("d", None)):
        mappe.dokumente.append(Dokument(id=name, dateiname=f"{name}.pdf", herkunft_jahr=jahr))
    assert mappe.jahresverteilung() == {"2024": 2, "2025": 1, "ohne Jahresangabe": 1}


def test_zusammenfuehren_uebernimmt_analysen(tmp_path):
    quelle = Arbeitsmappe.anlegen(tmp_path / "quelle", 2025)
    quelle.datei_aufnehmen(_datei(tmp_path, "gewerbe.txt"), herkunft="gewerbe", herkunft_jahr=2025)
    quelle.dokumente[0].analyse = Analyse(dokumenttyp="Ausgangsrechnung", betrag_gesamt=320.0)
    quelle.speichern()

    ziel = Arbeitsmappe.anlegen(tmp_path / "ziel", 2024)
    uebernommen, uebersprungen = ziel.uebernehmen_aus(quelle)

    assert (uebernommen, uebersprungen) == (1, 0)
    assert ziel.dokumente[0].analyse.dokumenttyp == "Ausgangsrechnung"
    assert ziel.dokumente[0].herkunft == "gewerbe"
    assert ziel.dokumente[0].herkunft_jahr == 2025
    # Die Quelle bleibt unangetastet.
    assert len(quelle.dokumente) == 1


def test_zusammenfuehren_erkennt_dubletten(tmp_path):
    quelle = Arbeitsmappe.anlegen(tmp_path / "quelle", 2025)
    quelle.datei_aufnehmen(_datei(tmp_path, "beleg.txt"))
    ziel = Arbeitsmappe.anlegen(tmp_path / "ziel", 2024)
    ziel.uebernehmen_aus(quelle)
    uebernommen, uebersprungen = ziel.uebernehmen_aus(quelle)
    assert (uebernommen, uebersprungen) == (0, 1)
    assert len(ziel.dokumente) == 1
