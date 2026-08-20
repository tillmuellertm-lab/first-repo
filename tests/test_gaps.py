import datetime as dt

from steuer import gaps, rules
from steuer.models import Analyse, Dokument, Profil


def dokument(
    kategorie: str,
    betrag: float | None = None,
    *,
    eignung: str = "geeignet",
    typ: str = "Rechnung",
    aussteller: str = "",
    datum: str | None = None,
    steuerjahr: int | None = 2024,
    zahlungsart: str = "unbar",
    vertrauen: float = 0.9,
    kennung: str = "",
) -> Dokument:
    doc = Dokument(id=kennung or f"{kategorie[:6]}{int(betrag or 0)}", dateiname=f"{kategorie}.pdf")
    doc.analyse = Analyse(
        kategorie_id=kategorie,
        dokumenttyp=typ,
        aussteller=aussteller,
        datum=datum,
        steuerjahr=steuerjahr,
        betrag_gesamt=betrag,
        betrag_abzugsfaehig=betrag,
        eignung=eignung,
        vertrauen=vertrauen,
        zahlungsart=zahlungsart,
        zusammenfassung="Testbeleg",
    )
    return doc


def profil(*merkmale: str, **felder) -> Profil:
    return Profil(veranlagungsjahr=2024, merkmale=list(merkmale), **felder)


REGELWERK = rules.laden(2024, strikt=True)


# ------------------------------------------------------------- Kennzahlen --

def test_werbungskosten_summe_ueber_alle_teilkategorien():
    dokumente = [
        dokument("werbungskosten_fahrten", 1200),
        dokument("werbungskosten_arbeitsmittel", 800),
        dokument("werbungskosten_fortbildung", 300),
        dokument("sonderausgaben", 500),
    ]
    zahlen = gaps.kennzahlen(dokumente, REGELWERK, profil("angestellt"))
    assert zahlen["werbungskosten_gesamt"] == 2300
    assert zahlen["sonderausgaben_gesamt"] == 500
    assert zahlen["werbungskosten_ueber_pauschbetrag"] == 1070


def test_ungeeignete_dokumente_zaehlen_nicht_in_die_summe():
    dokumente = [
        dokument("haushaltsnahe_aufwendungen", 1000),
        dokument("haushaltsnahe_aufwendungen", 5000, eignung="ungeeignet"),
    ]
    zahlen = gaps.kennzahlen(dokumente, REGELWERK, profil())
    assert zahlen["haushaltsnahe_aufwendungen_gesamt"] == 1000
    assert zahlen["haushaltsnahe_ermaessigung_geschaetzt"] == 200


# --------------------------------------------------- zumutbare Belastung --

def test_zumutbare_belastung_stufenweise_ledig():
    # 5 % auf 15.340, dann 6 % auf den Rest bis 51.130, dann 7 %
    ergebnis = gaps.zumutbare_belastung(60000, REGELWERK, profil())
    erwartet = 15340 * 0.05 + (51130 - 15340) * 0.06 + (60000 - 51130) * 0.07
    assert ergebnis == round(erwartet, 2)


def test_zumutbare_belastung_mit_kindern_ist_niedriger():
    ohne = gaps.zumutbare_belastung(60000, REGELWERK, profil())
    mit = gaps.zumutbare_belastung(60000, REGELWERK, profil(anzahl_kinder=2))
    assert mit < ohne


def test_zumutbare_belastung_erste_stufe():
    ergebnis = gaps.zumutbare_belastung(10000, REGELWERK, profil())
    assert ergebnis == 500.0


# ------------------------------------------------- Behinderten-Pauschbetrag --

def test_behinderten_pauschbetrag_staffelung():
    assert gaps.behinderten_pauschbetrag(50, REGELWERK) == 1140
    assert gaps.behinderten_pauschbetrag(55, REGELWERK) == 1140
    assert gaps.behinderten_pauschbetrag(100, REGELWERK) == 2840
    assert gaps.behinderten_pauschbetrag(10, REGELWERK) is None


# ------------------------------------------------------------------ Luecken --

def test_luecke_wird_gemeldet_wenn_kategorie_fehlt():
    ergebnis = gaps.auswerten([], REGELWERK, profil("angestellt"), heute=dt.date(2025, 1, 15))
    titel = {b.id for b in ergebnis.luecken}
    assert "check_lohnsteuerbescheinigung" in titel


def test_luecke_entfaellt_wenn_passendes_dokument_vorliegt():
    dokumente = [dokument("nichtselbstaendige_arbeit", 45000, typ="Lohnsteuerbescheinigung")]
    ergebnis = gaps.auswerten(dokumente, REGELWERK, profil("angestellt"), heute=dt.date(2025, 1, 15))
    assert "check_lohnsteuerbescheinigung" not in {b.id for b in ergebnis.luecken}


def test_checklistenpunkt_gilt_nur_bei_passendem_merkmal():
    ohne = gaps.auswerten([], REGELWERK, profil("angestellt"), heute=dt.date(2025, 1, 15))
    assert "check_vermietung" not in {b.id for b in ohne.luecken}
    mit = gaps.auswerten([], REGELWERK, profil("angestellt", "vermietung"), heute=dt.date(2025, 1, 15))
    assert "check_vermietung" in {b.id for b in mit.luecken}


def test_stichworte_trennen_punkte_derselben_kategorie():
    # Eine Handwerkerrechnung deckt nicht den Punkt "haushaltsnahe Dienstleistungen" ab.
    dokumente = [dokument("haushaltsnahe_aufwendungen", 500, typ="Handwerkerrechnung Elektro")]
    ergebnis = gaps.auswerten(
        dokumente, REGELWERK, profil("eigener_haushalt"), heute=dt.date(2025, 1, 15)
    )
    ids = {b.id for b in ergebnis.luecken}
    assert "check_handwerker" not in ids
    assert "check_haushaltsnahe_dienstleistungen" in ids


# ------------------------------------------------------------------ Chancen --

def test_entfernungspauschale_wird_gerechnet():
    ergebnis = gaps.auswerten(
        [], REGELWERK, profil("pendler", entfernung_km=30, arbeitstage=220),
        heute=dt.date(2025, 1, 15),
    )
    treffer = [b for b in ergebnis.chancen if b.id == "entfernungspauschale_berechnet"]
    assert treffer
    erwartet = 220 * (20 * 0.30 + 10 * 0.38)
    assert treffer[0].potenzial_eur == round(erwartet, 2)


def test_homeoffice_pauschale_wird_gedeckelt():
    ergebnis = gaps.auswerten(
        [], REGELWERK, profil("homeoffice", homeoffice_tage=300), heute=dt.date(2025, 1, 15)
    )
    treffer = [b for b in ergebnis.chancen if b.id == "homeoffice_berechnet"]
    assert treffer[0].potenzial_eur == 1260.0


def test_35a_ungenutzt_wird_als_chance_gemeldet():
    ergebnis = gaps.auswerten(
        [], REGELWERK, profil("eigener_haushalt"), heute=dt.date(2025, 1, 15)
    )
    assert "35a_ungenutzt" in {b.id for b in ergebnis.chancen}


def test_35a_ausgeschoepft_wird_zur_warnung():
    dokumente = [dokument("haushaltsnahe_aufwendungen", 7000, typ="Handwerkerrechnung")]
    ergebnis = gaps.auswerten(
        dokumente, REGELWERK, profil("eigener_haushalt"), heute=dt.date(2025, 1, 15)
    )
    assert "35a_ausgeschoepft" in {b.id for b in ergebnis.warnungen}


# --------------------------------------------------------------- Warnungen --

def test_falsches_steuerjahr_wird_gemeldet():
    dokumente = [dokument("sonderausgaben", 100, steuerjahr=2023)]
    ergebnis = gaps.auswerten(dokumente, REGELWERK, profil(), heute=dt.date(2025, 1, 15))
    assert "falsches_steuerjahr" in {b.id for b in ergebnis.warnungen}


def test_barzahlung_bei_35a_wird_gemeldet():
    dokumente = [dokument("haushaltsnahe_aufwendungen", 900, zahlungsart="bar")]
    ergebnis = gaps.auswerten(dokumente, REGELWERK, profil(), heute=dt.date(2025, 1, 15))
    assert "barzahlung_35a" in {b.id for b in ergebnis.warnungen}


def test_dublette_wird_erkannt():
    dokumente = [
        dokument("sonderausgaben", 250, aussteller="Verein", datum="2024-05-01", kennung="a1"),
        dokument("sonderausgaben", 250, aussteller="Verein", datum="2024-05-01", kennung="a2"),
    ]
    ergebnis = gaps.auswerten(dokumente, REGELWERK, profil(), heute=dt.date(2025, 1, 15))
    assert any(b.id.startswith("dublette_") for b in ergebnis.warnungen)


def test_frist_wird_als_verstrichen_gemeldet():
    ergebnis = gaps.auswerten([], REGELWERK, profil(), heute=dt.date(2026, 8, 1))
    treffer = [b for b in ergebnis.warnungen if b.id == "frist_abgabe_mit_berater"]
    assert treffer and "verstrichen" in treffer[0].titel


def test_ersatzrechtsstand_wird_gemeldet():
    ersatz = rules.laden(2099)
    ergebnis = gaps.auswerten([], ersatz, profil(), heute=dt.date(2026, 8, 1))
    assert "rechtsstand_ersatz" in {b.id for b in ergebnis.warnungen}


def test_manuelle_kategorie_setzt_analyse_ausser_kraft():
    doc = dokument("unklar", 500)
    doc.manuelle_kategorie = "haushaltsnahe_aufwendungen"
    zahlen = gaps.kennzahlen([doc], REGELWERK, profil())
    assert zahlen["haushaltsnahe_aufwendungen_gesamt"] == 500


# ------------------------------------------- Grosse Mappen bleiben lesbar --

def test_gleiche_hinweise_werden_gebuendelt():
    """Derselbe Hinweis aus vielen Belegen ergibt einen Befund, nicht hunderte."""
    dokumente = []
    for nummer in range(40):
        doc = dokument("werbungskosten_arbeitsmittel", 50, kennung=f"d{nummer:03d}")
        doc.analyse.optimierungshinweise = ["Zahlungsnachweis beilegen."]
        dokumente.append(doc)
    ergebnis = gaps.auswerten(dokumente, REGELWERK, profil(), heute=dt.date(2025, 1, 15))
    treffer = [b for b in ergebnis.chancen if "Zahlungsnachweis" in b.beschreibung]
    assert len(treffer) == 1
    assert treffer[0].titel == "Aus 40 Belegen"
    assert len(treffer[0].betroffene_dokumente) == 40


def test_sehr_viele_verschiedene_hinweise_werden_gedeckelt():
    dokumente = []
    for nummer in range(80):
        doc = dokument("werbungskosten_arbeitsmittel", 50, kennung=f"d{nummer:03d}")
        doc.analyse.optimierungshinweise = [f"Einzelfall {nummer}"]
        dokumente.append(doc)
    ergebnis = gaps.auswerten(dokumente, REGELWERK, profil(), heute=dt.date(2025, 1, 15))
    einzel = [b for b in ergebnis.chancen if b.id.startswith("dokumenthinweis")]
    assert len(einzel) <= gaps.MAX_DOKUMENTHINWEISE + 1
    assert any(b.id == "dokumenthinweise_weitere" for b in einzel)


def test_bestand_fuer_gesamtauswertung_behaelt_die_wichtigen():
    """Bei sehr grossen Mappen darf die Kontextgrenze nicht gesprengt werden."""
    from steuer.analyze import MAX_BESTAND_GESAMTAUSWERTUNG, _bestand_begrenzen

    bestand = (
        [{"kategorie": "nicht_steuerrelevant", "eignung": "ungeeignet"} for _ in range(900)]
        + [{"kategorie": "sonderausgaben", "eignung": "geeignet", "betrag_gesamt": 500} for _ in range(50)]
    )
    gekuerzt, weggelassen = _bestand_begrenzen(bestand)
    assert len(gekuerzt) == MAX_BESTAND_GESAMTAUSWERTUNG
    assert weggelassen == len(bestand) - MAX_BESTAND_GESAMTAUSWERTUNG
    # die verwertbaren Belege muessen vollstaendig enthalten sein
    assert sum(1 for e in gekuerzt if e["eignung"] == "geeignet") == 50


def test_kleiner_bestand_bleibt_unveraendert():
    from steuer.analyze import _bestand_begrenzen

    bestand = [{"kategorie": "sonderausgaben", "eignung": "geeignet"} for _ in range(10)]
    gekuerzt, weggelassen = _bestand_begrenzen(bestand)
    assert gekuerzt == bestand and weggelassen == 0


# --- Fahrzeugkosten neben der Entfernungspauschale ---------------------------


def _fahrtbeleg(betrag: float, kategorie: str = "werbungskosten_fahrten") -> Dokument:
    dokument = Dokument(id=f"kfz{betrag}", dateiname="kfz.pdf")
    dokument.analyse = Analyse(
        kategorie_id=kategorie,
        dokumenttyp="Kfz-Rechnung",
        eignung="bedingt_geeignet",
        betrag_gesamt=betrag,
    )
    return dokument


def test_fahrzeugkosten_werden_als_doppelter_ansatz_gemeldet():
    """Die Entfernungspauschale gilt alle Fahrzeugkosten ab (§ 9 Abs. 2 EStG)."""
    profil = Profil(merkmale=["angestellt", "pendler"], entfernung_km=6)
    auswertung = gaps.auswerten([_fahrtbeleg(269.19)], REGELWERK, profil)

    treffer = [b for b in auswertung.warnungen if b.id == "fahrzeugkosten_neben_entfernungspauschale"]
    assert treffer, "der doppelte Ansatz muss auffallen"
    assert treffer[0].prioritaet == "hoch"
    assert "269" in treffer[0].beschreibung


def test_ohne_pendlerpauschale_keine_warnung():
    """Wer nicht pendelt, kann auch nichts doppelt ansetzen."""
    profil = Profil(merkmale=["angestellt"])
    auswertung = gaps.auswerten([_fahrtbeleg(269.19)], REGELWERK, profil)
    assert not [b for b in auswertung.warnungen if b.id == "fahrzeugkosten_neben_entfernungspauschale"]


def test_belege_ohne_betrag_loesen_keine_warnung_aus():
    profil = Profil(merkmale=["angestellt", "pendler"])
    ohne_betrag = _fahrtbeleg(0.0)
    ohne_betrag.analyse.betrag_gesamt = None
    auswertung = gaps.auswerten([ohne_betrag], REGELWERK, profil)
    assert not [b for b in auswertung.warnungen if b.id == "fahrzeugkosten_neben_entfernungspauschale"]
