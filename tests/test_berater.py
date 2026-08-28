"""Das Beratungsgespraech muss in die Mappe hineinsehen und in sie hineinschreiben."""

from pathlib import Path

import pytest

from steuer import berater, rules
from steuer.models import Analyse, Profil
from steuer.workspace import Arbeitsmappe


class Antwort:
    """Eine Modellantwort, wie sie das SDK liefert - nur die Bloecke zaehlen."""

    def __init__(self, bloecke, stop_reason="end_turn"):
        self.content = bloecke
        self.stop_reason = stop_reason


class Dienst:
    """Gibt vorbereitete Antworten aus und merkt sich, was gefragt wurde."""

    def __init__(self, *antworten):
        self.antworten = list(antworten)
        self.aufrufe: list[dict] = []

    def beratung(self, system, werkzeuge, nachrichten, modell=""):
        self.aufrufe.append(
            {"system": system, "werkzeuge": werkzeuge, "nachrichten": nachrichten, "modell": modell}
        )
        return self.antworten.pop(0)


@pytest.fixture
def mappe(tmp_path: Path) -> Arbeitsmappe:
    profil = Profil(name="Testperson", veranlagungsjahr=2024, merkmale=["angestellt", "vermietung"])
    arbeitsmappe = Arbeitsmappe.anlegen(tmp_path / "mappe", 2024, profil)
    for name, analyse in (
        (
            "zinsen.txt",
            Analyse(
                kategorie_id="vermietung",
                dokumenttyp="Zinsbescheinigung",
                aussteller="DSL Bank",
                datum="2024-12-31",
                steuerjahr=2024,
                betrag_gesamt=8153.80,
                zusammenfassung="Zinsen fuer das Darlehen der vermieteten Wohnung.",
                fehlende_nachweise=["Klaerung, welches Objekt betroffen ist"],
            ),
        ),
        (
            "anhaenger.txt",
            Analyse(
                kategorie_id="werbungskosten_sonstige",
                dokumenttyp="Mietrechnung Anhaenger",
                aussteller="RentMyTrailer",
                datum="2024-08-14",
                steuerjahr=2024,
                betrag_gesamt=26.48,
            ),
        ),
    ):
        quelle = tmp_path / name
        quelle.write_text(name, encoding="utf-8")
        dokument, _ = arbeitsmappe.datei_aufnehmen(quelle, herkunft_jahr=2024)
        dokument.analyse = analyse
        dokument.status = "analysiert"
    arbeitsmappe.speichern()
    return arbeitsmappe


@pytest.fixture
def regelwerk():
    return rules.laden(2024)


def beleg(mappe: Arbeitsmappe, dateiname: str):
    return next(d for d in mappe.dokumente if d.dateiname == dateiname)


# --- Werkzeuge ---------------------------------------------------------------


def test_suche_findet_ueber_teilwort(mappe, regelwerk):
    text, _ = berater.werkzeug_ausfuehren(
        "dokumente_suchen", {"suchbegriff": "zins"}, mappe, regelwerk
    )
    assert "Zinsbescheinigung" in text
    assert "RentMyTrailer" not in text


def test_suche_verlangt_alle_woerter(mappe, regelwerk):
    treffer, _ = berater.werkzeug_ausfuehren(
        "dokumente_suchen", {"suchbegriff": "zins darlehen"}, mappe, regelwerk
    )
    assert "Zinsbescheinigung" in treffer

    leer, _ = berater.werkzeug_ausfuehren(
        "dokumente_suchen", {"suchbegriff": "zins anhaenger"}, mappe, regelwerk
    )
    assert leer == "Kein Beleg passt zu dieser Suche."


def test_suche_nur_mit_offenen_punkten(mappe, regelwerk):
    text, _ = berater.werkzeug_ausfuehren(
        "dokumente_suchen", {"nur_mit_offenen_punkten": True}, mappe, regelwerk
    )
    assert "Zinsbescheinigung" in text
    assert "RentMyTrailer" not in text


def test_notiz_wird_gespeichert_und_bleibt_auf_der_platte(mappe, regelwerk):
    kennung = beleg(mappe, "zinsen.txt").id
    berater.werkzeug_ausfuehren(
        "notiz_speichern",
        {"dokument_id": kennung, "notiz": "Betrifft Halstenbek."},
        mappe,
        regelwerk,
    )
    wieder = Arbeitsmappe.laden(mappe.wurzel)
    assert wieder.dokument(kennung).notiz == "Betrifft Halstenbek."


def test_notiz_wird_ergaenzt_statt_ueberschrieben(mappe, regelwerk):
    """Eine zweite Auskunft darf die erste nicht loeschen."""
    kennung = beleg(mappe, "zinsen.txt").id
    for satz in ("Betrifft Halstenbek.", "Darlehen laeuft bei der DSL Bank."):
        berater.werkzeug_ausfuehren(
            "notiz_speichern", {"dokument_id": kennung, "notiz": satz}, mappe, regelwerk
        )
    notiz = mappe.dokument(kennung).notiz
    assert "Halstenbek" in notiz and "DSL Bank" in notiz


def test_notiz_ersetzen_nur_auf_ansage(mappe, regelwerk):
    kennung = beleg(mappe, "zinsen.txt").id
    berater.werkzeug_ausfuehren(
        "notiz_speichern", {"dokument_id": kennung, "notiz": "falsch"}, mappe, regelwerk
    )
    berater.werkzeug_ausfuehren(
        "notiz_speichern",
        {"dokument_id": kennung, "notiz": "richtig", "ersetzen": True},
        mappe,
        regelwerk,
    )
    assert mappe.dokument(kennung).notiz == "richtig"


def test_unbekannter_beleg_ergibt_verstaendlichen_fehler(mappe, regelwerk):
    with pytest.raises(berater.BeratungsFehler, match="keinen Beleg"):
        berater.werkzeug_ausfuehren("dokument_lesen", {"dokument_id": "gibtsnicht"}, mappe, regelwerk)


def test_kategorie_setzen_weist_erfundene_kategorie_ab(mappe, regelwerk):
    kennung = beleg(mappe, "anhaenger.txt").id
    with pytest.raises(berater.BeratungsFehler):
        berater.werkzeug_ausfuehren(
            "kategorie_setzen",
            {"dokument_id": kennung, "kategorie_id": "werbungskosten", "begruendung": "x"},
            mappe,
            regelwerk,
        )
    assert not mappe.dokument(kennung).manuelle_kategorie


def test_kategorie_setzen_wirkt_auf_die_zuordnung(mappe, regelwerk):
    kennung = beleg(mappe, "anhaenger.txt").id
    berater.werkzeug_ausfuehren(
        "kategorie_setzen",
        {
            "dokument_id": kennung,
            "kategorie_id": "haushaltsnahe_aufwendungen",
            "begruendung": "Umzugsleistung",
        },
        mappe,
        regelwerk,
    )
    assert mappe.dokument(kennung).wirksame_kategorie == "haushaltsnahe_aufwendungen"


def test_offene_punkte_uebergehen_beantwortete_belege(mappe, regelwerk):
    text, _ = berater.werkzeug_ausfuehren("offene_punkte", {}, mappe, regelwerk)
    assert "Zinsbescheinigung" in text

    beleg(mappe, "zinsen.txt").notiz = "Ist geklaert."
    danach, _ = berater.werkzeug_ausfuehren("offene_punkte", {}, mappe, regelwerk)
    assert danach == "Zu diesem Thema ist nichts mehr offen."


def test_beleg_ansehen_haengt_den_scan_an(mappe, regelwerk):
    kennung = beleg(mappe, "zinsen.txt").id
    text, anhang = berater.werkzeug_ausfuehren(
        "beleg_ansehen", {"dokument_id": kennung}, mappe, regelwerk
    )
    assert "haengt an dieser Nachricht" in text
    assert anhang and anhang[-1]["type"] == "text"


# --- Lagebild ----------------------------------------------------------------


def test_lagebild_nennt_summen_und_jeden_beleg(mappe, regelwerk):
    lage = berater.lage_text(mappe, regelwerk)
    assert "Zinsbescheinigung" in lage
    assert "RentMyTrailer" in lage
    assert "Werbungskosten gesamt" in lage
    assert beleg(mappe, "zinsen.txt").id in lage


# --- Gespraechsfuehrung ------------------------------------------------------


def test_ein_zug_mit_werkzeug_endet_mit_einer_antwort(mappe, regelwerk):
    kennung = beleg(mappe, "zinsen.txt").id
    dienst = Dienst(
        Antwort(
            [
                {
                    "type": "tool_use",
                    "id": "werkzeug_1",
                    "name": "notiz_speichern",
                    "input": {"dokument_id": kennung, "notiz": "Objekt Halstenbek."},
                }
            ],
            stop_reason="tool_use",
        ),
        Antwort([{"type": "text", "text": "Ich habe das bei der Zinsbescheinigung vermerkt."}]),
    )

    gespraech = berater.Gespraech()
    berater.nachricht_senden(
        mappe, gespraech, "Die Zinsen betreffen Halstenbek.", dienst, regelwerk
    )

    assert mappe.dokument(kennung).notiz == "Objekt Halstenbek."
    rollen = [b.rolle for b in berater.beitraege(gespraech)]
    assert rollen == ["mandant", "vorgang", "berater"]
    # Der zweite Aufruf muss das Werkzeugergebnis enthalten haben.
    letzte = dienst.aufrufe[-1]["nachrichten"][-1]
    assert letzte["content"][0]["type"] == "tool_result"


def test_werkzeugfehler_bricht_das_gespraech_nicht_ab(mappe, regelwerk):
    dienst = Dienst(
        Antwort(
            [
                {
                    "type": "tool_use",
                    "id": "werkzeug_1",
                    "name": "dokument_lesen",
                    "input": {"dokument_id": "gibtsnicht"},
                }
            ],
            stop_reason="tool_use",
        ),
        Antwort([{"type": "text", "text": "Diesen Beleg finde ich nicht."}]),
    )

    gespraech = berater.Gespraech()
    berater.nachricht_senden(mappe, gespraech, "Was steht in Beleg gibtsnicht?", dienst, regelwerk)

    ergebnis = dienst.aufrufe[-1]["nachrichten"][-1]["content"][0]
    assert ergebnis["is_error"] is True
    assert berater.beitraege(gespraech)[-1].rolle == "berater"


def test_letzte_runde_laeuft_ohne_werkzeuge(mappe, regelwerk, monkeypatch):
    """Sonst koennte sich das Modell endlos durch die Mappe lesen."""
    monkeypatch.setattr(berater, "MAX_RUNDEN", 2)
    aufruf = {
        "type": "tool_use",
        "id": "werkzeug_1",
        "name": "dokumente_suchen",
        "input": {"suchbegriff": "zins"},
    }
    dienst = Dienst(
        Antwort([dict(aufruf)], stop_reason="tool_use"),
        Antwort([{"type": "text", "text": "Zusammengefasst: ..."}]),
    )

    gespraech = berater.Gespraech()
    berater.nachricht_senden(mappe, gespraech, "Suche bitte.", dienst, regelwerk)

    assert dienst.aufrufe[0]["werkzeuge"]
    assert dienst.aufrufe[-1]["werkzeuge"] == []


def test_leere_frage_wird_abgewiesen(mappe, regelwerk):
    with pytest.raises(berater.BeratungsFehler):
        berater.nachricht_senden(mappe, berater.Gespraech(), "   ", Dienst(), regelwerk)


def test_gespraech_ueberlebt_das_speichern(mappe, regelwerk):
    dienst = Dienst(Antwort([{"type": "text", "text": "Guten Tag."}]))
    gespraech = berater.Gespraech()
    berater.nachricht_senden(
        mappe, gespraech, "Hallo", dienst, regelwerk, sichern=lambda g: berater.speichern(mappe, g)
    )

    wieder = berater.laden(mappe)
    assert [b.text for b in berater.beitraege(wieder)] == ["Hallo", "Guten Tag."]

    assert berater.loeschen(mappe) is True
    assert berater.laden(mappe).nachrichten == []


def test_gekuerzter_verlauf_beginnt_nie_mit_einem_werkzeugergebnis(monkeypatch):
    """Ein Ergebnis ohne den Aufruf davor weist die API zurueck."""
    monkeypatch.setattr(berater, "MAX_NACHRICHTEN", 2)
    gespraech = berater.Gespraech()
    gespraech.anhaengen("user", [{"type": "text", "text": "Frage"}])
    gespraech.anhaengen("assistant", [{"type": "tool_use", "id": "a", "name": "x", "input": {}}])
    gespraech.anhaengen("user", [{"type": "tool_result", "tool_use_id": "a", "content": "ok"}])
    gespraech.anhaengen("assistant", [{"type": "text", "text": "Antwort"}])

    verlauf = gespraech.fuer_api()
    assert verlauf[0]["content"][0]["type"] != "tool_result"


# --- Stand der Analyse -------------------------------------------------------


def test_lagebild_traegt_die_gesamtauswertung_mit(mappe, regelwerk):
    """Der einzige Schritt, der die Mappe als Ganzes bewertet, darf nicht fehlen."""
    mappe.gesamtauswertung_speichern(
        {
            "gesamteinschaetzung": "Die Anlage V ist unvollstaendig.",
            "luecken": [
                {
                    "titel": "Zinsbescheinigungen 2024",
                    "beschreibung": "Fuer kein Darlehen liegt eine Bescheinigung vor.",
                    "prioritaet": "hoch",
                    "naechster_schritt": "Bei DSL Bank, IB.SH und DKB anfordern.",
                }
            ],
            "chancen": [{"titel": "Arbeitszimmer", "beschreibung": "pruefen", "potenzial_eur": 1260}],
            "fragen_an_den_mandanten": ["Wurde die Wohnung ganzjaehrig vermietet?"],
        },
        modell="claude-fable-5",
    )
    lage = berater.lage_text(mappe, regelwerk)
    assert "Die Anlage V ist unvollstaendig." in lage
    assert "Bei DSL Bank, IB.SH und DKB anfordern." in lage
    assert "Wurde die Wohnung ganzjaehrig vermietet?" in lage
    assert "claude-fable-5" in lage


def test_lagebild_sagt_wenn_keine_gesamtauswertung_vorliegt(mappe, regelwerk):
    assert "noch keine Gesamtauswertung" in berater.lage_text(mappe, regelwerk)


def test_lagebild_enthaelt_bereits_gegebene_antworten(mappe, regelwerk):
    """Sonst wird dieselbe Frage ein zweites Mal gestellt."""
    beleg(mappe, "zinsen.txt").notiz = "Betrifft die vermietete Wohnung in Halstenbek."
    lage = berater.lage_text(mappe, regelwerk)
    assert "Auskunft des Mandanten: Betrifft die vermietete Wohnung in Halstenbek." in lage


def test_lagebild_benennt_veraltete_analysen(mappe, regelwerk):
    lage = berater.lage_text(mappe, regelwerk)
    assert "nicht auf dem aktuellen Stand" in lage


# --- Die uebrigen Werkzeuge --------------------------------------------------


def test_dubletten_werden_gefunden(mappe, regelwerk, tmp_path):
    """Derselbe Beleg aus zwei Stapeln - der Chat soll ihn benennen koennen."""
    from steuer.models import Analyse as A

    quelle = tmp_path / "zinsen_zweiter_scan.txt"
    quelle.write_text("zweiter scan", encoding="utf-8")
    zwilling, _ = mappe.datei_aufnehmen(quelle, herkunft_jahr=2024)
    zwilling.analyse = A(
        kategorie_id="vermietung",
        dokumenttyp="Zinsbescheinigung",
        aussteller="DSL Bank",
        datum="2024-12-31",
        steuerjahr=2024,
        betrag_gesamt=8153.80,
    )
    text, _ = berater.werkzeug_ausfuehren("dubletten_finden", {}, mappe, regelwerk)
    assert "zinsen_zweiter_scan.txt" in text
    assert "zinsen.txt" in text


def test_ohne_dubletten_sagt_das_werkzeug_das(mappe, regelwerk):
    text, _ = berater.werkzeug_ausfuehren("dubletten_finden", {}, mappe, regelwerk)
    assert "zweimal" in text


def test_rechtsstand_eines_anderen_jahres(mappe, regelwerk):
    text, _ = berater.werkzeug_ausfuehren("rechtsstand_lesen", {"jahr": 2023}, mappe, regelwerk)
    assert "Rechtsstand fuer 2023" in text
    assert "Werte:" in text


def test_rechtsstand_ohne_jahr_wird_abgewiesen(mappe, regelwerk):
    with pytest.raises(berater.BeratungsFehler):
        berater.werkzeug_ausfuehren("rechtsstand_lesen", {}, mappe, regelwerk)


def test_stammwert_braucht_eine_fundstelle(mappe, regelwerk):
    """Ein Wert ohne Herkunft ist im naechsten Jahr nicht mehr nachpruefbar."""
    with pytest.raises(berater.BeratungsFehler, match="Fundstelle"):
        berater.werkzeug_ausfuehren(
            "stammwert_speichern",
            {"kennung": "gebaeude_afa_jahresbetrag", "wert": "8971"},
            mappe,
            regelwerk,
        )


def test_stammwert_wird_gespeichert_und_ueberlebt(mappe, regelwerk):
    berater.werkzeug_ausfuehren(
        "stammwert_speichern",
        {
            "kennung": "gebaeude_afa_jahresbetrag",
            "wert": "8971",
            "quelle": "Anlage V 2023, Zeile 33",
        },
        mappe,
        regelwerk,
    )
    wieder = Arbeitsmappe.laden(mappe.wurzel)
    eintrag = wieder.stammdaten.eintrag("gebaeude_afa_jahresbetrag")
    assert eintrag.wert == "8971"
    assert eintrag.quelle == "Anlage V 2023, Zeile 33"


def test_geaenderter_stammwert_nennt_den_alten(mappe, regelwerk):
    for wert in ("8971", "9200"):
        text, _ = berater.werkzeug_ausfuehren(
            "stammwert_speichern",
            {"kennung": "gebaeude_afa_jahresbetrag", "wert": wert, "quelle": "Anlage V"},
            mappe,
            regelwerk,
        )
    assert "8971" in text


def test_entwurf_wird_abgelegt_und_ist_auffindbar(mappe, regelwerk):
    text, _ = berater.werkzeug_ausfuehren(
        "schreiben_entwerfen",
        {"titel": "Mail an Dr. Hagn", "text": "Sehr geehrter Herr Dr. Hagn, ..."},
        mappe,
        regelwerk,
    )
    assert "Gespeichert als" in text
    liste = berater.entwuerfe(mappe)
    assert len(liste) == 1 and "Mail-an-Dr-Hagn" in liste[0]
    pfad = berater.entwurf_pfad(mappe, liste[0])
    assert "Sehr geehrter Herr Dr. Hagn" in pfad.read_text(encoding="utf-8")


def test_entwurfspfad_fuehrt_nicht_aus_dem_ordner_heraus(mappe):
    """Der Name kommt aus der Adresszeile und ist damit nicht vertrauenswuerdig."""
    assert berater.entwurf_pfad(mappe, "../../steuer.json") is None
    assert berater.entwurf_pfad(mappe, "gibtsnicht.md") is None


def test_websuche_gehoert_zu_den_werkzeugen():
    namen = {w.get("name") for w in berater.werkzeuge()}
    assert "web_search" in namen
    assert {"dubletten_finden", "rechtsstand_lesen", "stammwert_speichern",
            "schreiben_entwerfen"} <= namen


def test_serverwerkzeug_erscheint_als_vorgang_im_verlauf():
    """Die Websuche fuehrt die API selbst aus - sichtbar sein muss sie trotzdem."""
    gespraech = berater.Gespraech()
    gespraech.anhaengen(
        "assistant",
        [
            {"type": "server_tool_use", "id": "s1", "name": "web_search",
             "input": {"query": "Verpflegungspauschale 2026"}},
            {"type": "web_search_tool_result", "tool_use_id": "s1", "content": []},
            {"type": "text", "text": "Ab 2026 sind es 32 Euro."},
        ],
    )
    liste = berater.beitraege(gespraech)
    assert [b.rolle for b in liste] == ["vorgang", "berater"]
    assert "Verpflegungspauschale 2026" in liste[0].text
