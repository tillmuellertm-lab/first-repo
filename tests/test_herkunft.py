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
        version=ANALYSE_VERSION, kontext=mappe.profil.kontext_pruefsumme()
    )
    mappe.dokumente.append(dokument)
    assert mappe.nachzutragen() == []

    mappe.profil.taetigkeiten = "Tuftingstudio"
    assert len(mappe.nachzutragen()) == 1


def test_herkunftskennungen_sind_stabil():
    # Die Kennungen stehen in gespeicherten Mappen; sie duerfen sich nicht
    # unbemerkt aendern.
    assert HERKUNFT_IDS == {"privat", "gewerbe", "vermietung", "gemischt"}
