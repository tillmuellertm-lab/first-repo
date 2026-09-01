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


def _mappe_mit_bestand(tmp_path):
    mappe = Arbeitsmappe.anlegen(tmp_path / "mappe", 2024)
    ohne = Dokument(id="a", dateiname="bon.pdf")
    ohne.analyse = Analyse(kategorie_id="unklar", eignung="geeignet")
    mit_jahr = Dokument(id="b", dateiname="rechnung.pdf")
    mit_jahr.analyse = Analyse(kategorie_id="unklar", eignung="geeignet", steuerjahr=2025)
    mappe.dokumente += [ohne, mit_jahr]
    return mappe, ohne, mit_jahr


def test_jahr_setzen_fasst_nur_dokumente_ohne_jahr_an(tmp_path):
    """Vorsichtiger Standard: was ein Jahr hat, bleibt unberuehrt."""
    mappe, ohne, mit_jahr = _mappe_mit_bestand(tmp_path)
    betroffen = [
        d for d in mappe.dokumente if d.gehoert_ins_jahr is None
    ]
    assert [d.dateiname for d in betroffen] == ["bon.pdf"]

    for dokument in betroffen:
        dokument.herkunft_jahr = 2024
    assert ohne.gehoert_ins_jahr == 2024
    assert mit_jahr.gehoert_ins_jahr == 2025, "das erkannte Jahr bleibt stehen"
    assert len(mappe.jahresansicht().eigene) == 1


def test_gesetztes_jahr_ueberlebt_das_speichern(tmp_path):
    mappe, ohne, _ = _mappe_mit_bestand(tmp_path)
    ohne.herkunft_jahr = 2024
    mappe.speichern()
    wieder = Arbeitsmappe.laden(mappe.wurzel)
    assert wieder.dokument("a").gehoert_ins_jahr == 2024


def test_datum_aus_dateiname_liest_vollstaendige_daten():
    from steuer.cli import datum_aus_dateiname as lesen

    # So benennen Scan-Programme ueblicherweise.
    assert lesen("2024-03-12_Rechnung.pdf") == "2024-03-12"
    assert lesen("2023-07-31_RTL interactive.pdf") == "2023-07-31"
    # Deutsche Schreibweise irgendwo im Namen.
    assert lesen("Rechnung vom 12.03.2024 Elektro.pdf") == "2024-03-12"
    assert lesen("Beleg 5.9.2024.pdf") == "2024-09-05"


def test_datum_aus_dateiname_verwirft_mehrdeutiges():
    from steuer.cli import datum_aus_dateiname as lesen

    # Eine blosse Jahreszahl kann eine Rechnungsnummer sein.
    assert lesen("Rechnung 2024 Nr 4711.pdf") is None
    assert lesen("Kassenbon.pdf") is None
    # Unmoegliche Daten sind keine Daten.
    assert lesen("2024-13-45_unsinn.pdf") is None
    assert lesen("32.01.2024_beleg.pdf") is None


def test_datum_aus_dateiname_nimmt_das_erste_datum():
    from steuer.cli import datum_aus_dateiname as lesen

    # Der vorangestellte Zeitstempel gilt, nicht ein spaeter erwaehntes Datum.
    assert lesen("2024-02-01_Kassenzettel vom 31.01.2024.pdf") == "2024-02-01"


def test_belegdatum_dient_als_zweite_quelle(tmp_path):
    """Wo der Dateiname schweigt, zaehlt das aus dem Scan gelesene Belegdatum."""
    mappe = Arbeitsmappe.anlegen(tmp_path / "mappe", 2024)
    aus_name = Dokument(id="a", dateiname="2024-06-24_Umzug.pdf")
    aus_name.analyse = Analyse(datum="2019-01-01")  # der Dateiname hat Vorrang
    aus_beleg = Dokument(id="b", dateiname="Kassenbon.pdf")
    aus_beleg.analyse = Analyse(datum="2024-02-01")
    unlesbar = Dokument(id="c", dateiname="scan.pdf")
    unlesbar.analyse = Analyse(datum="unleserlich")
    mappe.dokumente += [aus_name, aus_beleg, unlesbar]

    from steuer.cli import datum_aus_dateiname

    assert datum_aus_dateiname(aus_name.dateiname) == "2024-06-24"
    assert datum_aus_dateiname(aus_beleg.dateiname) is None
    # Ein unleserliches Feld darf nicht als Datum durchgehen.
    import re

    assert not re.fullmatch(r"(?:19|20)\d{2}-\d{2}-\d{2}", unlesbar.analyse.datum)


def test_ablage_nimmt_nur_belege_des_jahres(tmp_path):
    """Der Steuerberater darf keine Belege fremder Jahre im Paket finden.

    Die Kennzahlen des Berichts stuetzen sich auf die Jahressicht. Naehme die
    Ablage den ganzen Bestand, enthielte das Paket mehr, als der Bericht
    ausweist - und niemand koennte sagen, welche Zahl zu welchem Beleg gehoert.
    """
    from steuer import organize

    mappe = Arbeitsmappe.anlegen(tmp_path / "mappe", 2024)
    for name, jahr in (("heuer.txt", 2024), ("vorjahr.txt", 2023), ("naechstes.txt", 2025)):
        quelle = _datei(tmp_path, name, inhalt=name)
        dokument, _ = mappe.datei_aufnehmen(quelle, herkunft_jahr=jahr)
        dokument.analyse = Analyse(kategorie_id="werbungskosten_sonstige", eignung="geeignet")

    ablage = organize.ablage_erzeugen(mappe)
    abgelegt = {pfad.name for pfad in ablage.wurzel.rglob("*") if pfad.is_file()}
    assert ablage.anzahl == 1
    assert any("heuer" in name for name in abgelegt)
    assert not any("vorjahr" in name or "naechstes" in name for name in abgelegt)


# ----------------------------------------------- bewusst uebersprungene -----
#
# "Alles neu analysieren" laesst Belege aus, die der Nutzer selbst einem anderen
# Jahr zugeordnet hat. Richtig - aber die Uebersicht zaehlte sie trotzdem unter
# "wird nachgeholt". Wer daraufhin den teuren Knopf drueckte, zahlte fuer einen
# Lauf, nach dem dieselbe Zahl unveraendert dastand.

def test_fremdes_jahr_wird_getrennt_gezaehlt(tmp_path):
    from steuer.models import Dokument
    from steuer.workspace import Arbeitsmappe

    mappe = Arbeitsmappe.anlegen(tmp_path / "m", 2024)
    mappe.dokumente = [
        Dokument(id="a", dateiname="a.pdf", sha256="1"),
        Dokument(id="b", dateiname="b.pdf", sha256="2", herkunft_jahr=2025),
        Dokument(id="c", dateiname="c.pdf", sha256="3", herkunft_jahr=2024),
    ]

    offen = mappe.nachzutragen()
    assert {d.id for d in offen} == {"a", "b", "c"}

    uebersprungen = mappe.uebersprungen_fremdes_jahr(offen)
    assert [d.id for d in uebersprungen] == ["b"]


def test_ohne_liste_zaehlt_die_ganze_mappe(tmp_path):
    from steuer.models import Dokument
    from steuer.workspace import Arbeitsmappe

    mappe = Arbeitsmappe.anlegen(tmp_path / "m2", 2024)
    mappe.dokumente = [
        Dokument(id="a", dateiname="a.pdf", sha256="1", herkunft_jahr=2023),
        Dokument(id="b", dateiname="b.pdf", sha256="2"),
    ]
    assert [d.id for d in mappe.uebersprungen_fremdes_jahr()] == ["a"]
