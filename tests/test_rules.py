import pytest

from steuer import rules


def test_verfuegbare_jahre_enthalten_gepflegte_jahre():
    jahre = rules.verfuegbare_jahre()
    assert {2023, 2024, 2025} <= set(jahre)
    assert all(isinstance(j, int) for j in jahre)


def test_basis_wird_nicht_als_jahr_gefuehrt():
    assert "basis" not in [str(j) for j in rules.verfuegbare_jahre()]


def test_jahresdatei_erbt_checkliste_aus_basis():
    regelwerk = rules.laden(2024)
    ids = {eintrag["id"] for eintrag in regelwerk.checkliste}
    assert "handwerker" in ids
    assert "lohnsteuerbescheinigung" in ids


def test_2023_erbt_von_2024_und_ueberschreibt_einzelne_werte():
    regelwerk = rules.laden(2023)
    # eigener Wert
    assert regelwerk.wert("grundfreibetrag") == 10908
    # geerbter Wert
    assert regelwerk.wert("arbeitnehmer_pauschbetrag") == 1230
    # geerbte Checkliste
    assert any(e["id"] == "spenden" for e in regelwerk.checkliste)


def test_2025_hat_eigene_kinderbetreuungsregel():
    regelwerk = rules.laden(2025)
    eintrag = regelwerk.eintrag("kinderbetreuungskosten")
    assert eintrag["max_abzug"] == 4800
    assert eintrag["abziehbarer_anteil"] == 0.8


def test_chancen_werden_eintragsweise_zusammengefuehrt():
    regelwerk = rules.laden(2023)
    chancen = {eintrag["id"]: eintrag for eintrag in regelwerk.chancen}
    # aus basis geerbt
    assert "nebenkostenabrechnung" in chancen
    # in 2023 ueberschrieben
    assert "2027" in chancen["rueckwirkende_abgabe"]["beschreibung"]


def test_unbekanntes_jahr_faellt_auf_juengstes_jahr_zurueck():
    regelwerk = rules.laden(2099)
    assert regelwerk.ist_ersatz
    assert regelwerk.quelle_jahr == max(rules.verfuegbare_jahre())
    assert regelwerk.jahr == 2099


def test_strikter_modus_meldet_fehlendes_jahr():
    with pytest.raises(rules.RegelFehler):
        rules.laden(2099, strikt=True)


def test_alle_jahre_haben_fristen_und_stand():
    for jahr in rules.verfuegbare_jahre():
        regelwerk = rules.laden(jahr, strikt=True)
        assert regelwerk.stand != "unbekannt"
        assert regelwerk.fristen.get("abgabe_mit_berater")
        assert regelwerk.wert("grundfreibetrag")
