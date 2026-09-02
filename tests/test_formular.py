"""Die Aufstellung sagt, in welchen Formularabschnitt ein Betrag gehoert."""

import datetime as dt

import pytest

from steuer import formular, rules
from steuer.models import Analyse, Dokument

REGELWERK = rules.laden(2024)


def dokument(kategorie: str, betrag: float, *, betragsart: str = "aufwand", kennung: str = "a") -> Dokument:
    doc = Dokument(id=kennung, dateiname=f"{kennung}.pdf")
    doc.analyse = Analyse(
        kategorie_id=kategorie,
        dokumenttyp="Rechnung",
        aussteller="Aussteller",
        datum="2024-05-01",
        steuerjahr=2024,
        betrag_gesamt=betrag,
        betragsart=betragsart,
        eignung="geeignet",
    )
    return doc


def posten_zu(posten, kategorie):
    return next(p for p in posten if p.kategorie_id == kategorie)


def test_jede_kategorie_bekommt_ihre_anlage():
    posten = formular.aufstellung([dokument("werbungskosten_fahrten", 1795.0)], REGELWERK)
    eintrag = posten_zu(posten, "werbungskosten_fahrten")
    assert eintrag.anlage == "Anlage N"
    assert eintrag.betrag == 1795.0
    assert eintrag.standardabschnitt.bezeichnung.startswith("Wege zwischen Wohnung")


def test_eine_kategorie_mit_mehreren_abschnitten_wird_nicht_geraten():
    """Welcher Beleg zur doppelten Haushaltsfuehrung gehoert, steht in keinem Beleg."""
    posten = formular.aufstellung([dokument("werbungskosten_sonstige", 2910.0)], REGELWERK)
    eintrag = posten_zu(posten, "werbungskosten_sonstige")
    assert eintrag.aufzuteilen
    bezeichnungen = [a.bezeichnung for a in eintrag.abschnitte]
    assert any("doppelte Haushaltsfuehrung" in b for b in bezeichnungen)
    assert any("Umzugskosten" in b for b in bezeichnungen)
    # Der Sammelposten ist als solcher markiert, damit er nicht zum Standardfall wird.
    assert eintrag.standardabschnitt.bezeichnung == "Weitere Werbungskosten"


def test_erstattungen_mindern_den_posten_und_bleiben_sichtbar():
    posten = formular.aufstellung(
        [
            dokument("aussergewoehnliche_belastungen", 456.68, kennung="aufwand"),
            dokument(
                "aussergewoehnliche_belastungen", 124.88, betragsart="erstattung", kennung="erst"
            ),
        ],
        REGELWERK,
    )
    eintrag = posten_zu(posten, "aussergewoehnliche_belastungen")
    assert eintrag.betrag == 331.80
    assert [d.id for d in eintrag.erstattungen] == ["erst"]
    assert [d.id for d in eintrag.belege] == ["aufwand"]


def test_kategorien_ohne_betrag_erscheinen_nicht():
    doc = dokument("nicht_steuerrelevant", 99.0)
    assert formular.aufstellung([doc], REGELWERK) == []


def test_markdown_warnt_vor_ungeprueften_zeilennummern():
    text = formular.als_markdown(
        formular.aufstellung([dokument("werbungskosten_fahrten", 100.0)], REGELWERK),
        REGELWERK,
        2024,
    )
    assert "nicht amtlich geprueft" in text
    assert "Anlage N" in text


def test_markdown_haelt_die_anmerkung_beim_beleg():
    doc = dokument("haushaltsnahe_aufwendungen", 890.0)
    doc.notiz = "Ueberweisung vom 02.04.2024, Kontoauszug liegt bei."
    text = formular.als_markdown(formular.aufstellung([doc], REGELWERK), REGELWERK, 2024)
    assert "Ueberweisung vom 02.04.2024" in text


def test_reihenfolge_folgt_der_steuererklaerung():
    posten = formular.aufstellung(
        [
            dokument("haushaltsnahe_aufwendungen", 100.0, kennung="h"),
            dokument("nichtselbstaendige_arbeit", 200.0, kennung="n"),
        ],
        REGELWERK,
    )
    assert [p.kategorie_id for p in posten] == [
        "nichtselbstaendige_arbeit",
        "haushaltsnahe_aufwendungen",
    ]
