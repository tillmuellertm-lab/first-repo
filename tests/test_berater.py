"""Das Beratungsgespraech muss in die Mappe hineinsehen und in sie hineinschreiben."""

import json
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

    def beratung(
        self, system, werkzeuge, nachrichten, modell="", max_tokens=0, denktiefe=""
    ):
        self.aufrufe.append(
            {
                "system": system,
                "werkzeuge": werkzeuge,
                "nachrichten": nachrichten,
                "modell": modell,
                "max_tokens": max_tokens,
                "denktiefe": denktiefe,
            }
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


def test_verbesserungen_werden_gesammelt_statt_ueberschrieben(mappe, regelwerk):
    """Die Liste waechst - der zweite Eintrag darf den ersten nicht verdraengen."""
    for titel in ("Belege anderer Mappen sehen", "Entfernungspauschale rechnen"):
        berater.werkzeug_ausfuehren(
            "verbesserung_vorschlagen",
            {"titel": titel, "anlass": "kam gerade vor", "beschreibung": "waere hilfreich"},
            mappe,
            regelwerk,
        )
    text = berater.verbesserungen(mappe).read_text(encoding="utf-8")
    assert "Belege anderer Mappen sehen" in text
    assert "Entfernungspauschale rechnen" in text
    assert text.count("**Anlass:**") == 2


def test_verbesserung_ohne_anlass_wird_abgewiesen(mappe, regelwerk):
    with pytest.raises(berater.BeratungsFehler):
        berater.werkzeug_ausfuehren(
            "verbesserung_vorschlagen", {"titel": "Irgendwas"}, mappe, regelwerk
        )


def test_ohne_eintraege_gibt_es_keine_liste(mappe):
    assert berater.verbesserungen(mappe) is None


# --- Bilder im Gespraech -----------------------------------------------------


def _png() -> bytes:
    """Ein winziges gueltiges PNG."""
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )


def test_bild_wird_abgelegt_und_nur_einmal_gespeichert(mappe):
    erst = berater.bild_aufnehmen(mappe, _png(), "image/png")
    nochmal = berater.bild_aufnehmen(mappe, _png(), "image/png")
    assert erst["type"] == "bild_verweis"
    assert erst["datei"] == nochmal["datei"]
    assert len(list(berater.bilderordner(mappe).iterdir())) == 1


def test_fremdes_format_wird_abgelehnt(mappe):
    with pytest.raises(berater.BeratungsFehler, match="Bildformat"):
        berater.bild_aufnehmen(mappe, b"%PDF-1.4", "application/pdf")


def test_bildpfad_fuehrt_nicht_aus_dem_ordner_heraus(mappe):
    berater.bild_aufnehmen(mappe, _png(), "image/png")
    assert berater.bildpfad(mappe, "../dokumente.json") is None
    assert berater.bildpfad(mappe, "gibtsnicht.png") is None


def test_bild_steht_im_verlauf_nur_als_verweis(mappe, regelwerk):
    """Sonst waere die Verlaufsdatei nach drei Bildschirmfotos unlesbar."""
    verweis = berater.bild_aufnehmen(mappe, _png(), "image/png")
    dienst = Dienst(Antwort([{"type": "text", "text": "Ich sehe es."}]))
    gespraech = berater.Gespraech()
    berater.nachricht_senden(
        mappe, gespraech, "Was steht hier?", dienst, regelwerk, bilder=[verweis]
    )

    gespeichert = json.dumps(gespraech.als_dict())
    assert "bild_verweis" in gespeichert
    assert "base64" not in gespeichert

    # Erst auf dem Weg zur API wird das Bild eingesetzt.
    gesendet = dienst.aufrufe[0]["nachrichten"][0]["content"]
    assert gesendet[0]["type"] == "image"
    assert gesendet[0]["source"]["media_type"] == "image/png"
    assert gesendet[1]["text"] == "Was steht hier?"


def test_bild_erscheint_als_eigener_beitrag(mappe, regelwerk):
    verweis = berater.bild_aufnehmen(mappe, _png(), "image/png")
    gespraech = berater.Gespraech()
    berater.nachricht_senden(
        mappe,
        gespraech,
        "Sieh mal",
        Dienst(Antwort([{"type": "text", "text": "Ja."}])),
        regelwerk,
        bilder=[verweis],
    )
    rollen = [b.rolle for b in berater.beitraege(gespraech)]
    assert rollen == ["bild", "mandant", "berater"]


def test_ein_bild_ohne_text_reicht(mappe, regelwerk):
    verweis = berater.bild_aufnehmen(mappe, _png(), "image/png")
    dienst = Dienst(Antwort([{"type": "text", "text": "Das ist ein Kontoauszug."}]))
    berater.nachricht_senden(
        mappe, berater.Gespraech(), "", dienst, regelwerk, bilder=[verweis]
    )
    assert dienst.aufrufe[0]["nachrichten"][0]["content"][1]["text"]


def test_zu_viele_bilder_werden_abgelehnt(mappe, regelwerk):
    verweis = berater.bild_aufnehmen(mappe, _png(), "image/png")
    with pytest.raises(berater.BeratungsFehler, match="Hoechstens"):
        berater.nachricht_senden(
            mappe,
            berater.Gespraech(),
            "viele",
            Dienst(),
            regelwerk,
            bilder=[verweis] * (berater.MAX_BILDER_JE_NACHRICHT + 1),
        )


def test_geloeschtes_bild_bricht_das_gespraech_nicht_ab(mappe, regelwerk):
    """Ein stiller Ausfall waere schlimmer: das Modell antwortete ins Leere."""
    verweis = berater.bild_aufnehmen(mappe, _png(), "image/png")
    gespraech = berater.Gespraech()
    gespraech.anhaengen("user", [verweis, {"type": "text", "text": "Was ist das?"}])
    berater.bildpfad(mappe, verweis["datei"]).unlink()

    gesendet = gespraech.fuer_api(mappe)[0]["content"]
    assert gesendet[0]["type"] == "text"
    assert "nicht mehr vorhanden" in gesendet[0]["text"]


# --- Ein leerer Textblock darf das Gespraech nicht vergiften ------------------


def test_leerer_textblock_geht_nicht_an_die_api(mappe):
    """Die API weist ihn ab - und der ganze Verlauf geht bei jedem Zug erneut mit."""
    gespraech = berater.Gespraech()
    gespraech.anhaengen("user", [{"type": "text", "text": "Frage"}])
    gespraech.anhaengen("assistant", [{"type": "text", "text": ""}])
    gespraech.anhaengen("user", [{"type": "text", "text": "Und weiter?"}])

    verlauf = gespraech.fuer_api(mappe)
    assert all(
        block["text"].strip()
        for nachricht in verlauf
        for block in nachricht["content"]
        if block["type"] == "text"
    )


def test_weggefallene_nachricht_hinterlaesst_keine_doppelte_rolle(mappe):
    """Zwei Nachrichten derselben Rolle nacheinander weist die API ebenfalls ab."""
    gespraech = berater.Gespraech()
    gespraech.anhaengen("user", [{"type": "text", "text": "Erste Frage"}])
    gespraech.anhaengen("assistant", [{"type": "text", "text": "   "}])
    gespraech.anhaengen("user", [{"type": "text", "text": "Zweite Frage"}])

    verlauf = gespraech.fuer_api(mappe)
    assert [n["role"] for n in verlauf] == ["user"]
    assert len(verlauf[0]["content"]) == 2


def test_werkzeugaufruf_bleibt_neben_leerem_text_erhalten(mappe):
    gespraech = berater.Gespraech()
    gespraech.anhaengen("user", [{"type": "text", "text": "Such mal"}])
    gespraech.anhaengen(
        "assistant",
        [
            {"type": "text", "text": ""},
            {"type": "tool_use", "id": "a", "name": "dokumente_suchen", "input": {}},
        ],
    )
    gespraech.anhaengen("user", [{"type": "tool_result", "tool_use_id": "a", "content": "ok"}])

    verlauf = gespraech.fuer_api(mappe)
    assert [n["role"] for n in verlauf] == ["user", "assistant", "user"]
    assert [b["type"] for b in verlauf[1]["content"]] == ["tool_use"]


def test_abgeschnittene_antwort_wird_im_verlauf_benannt(mappe, regelwerk):
    """Sonst sieht sie aus wie eine vollstaendige, die mitten im Satz endet."""
    dienst = Dienst(
        Antwort([{"type": "text", "text": "Sehr geehrter Herr Dr."}], stop_reason="max_tokens")
    )
    gespraech = berater.Gespraech()
    berater.nachricht_senden(mappe, gespraech, "Schreib mir eine Mail.", dienst, regelwerk)

    texte = [b.text for b in berater.beitraege(gespraech)]
    assert any("abgeschnitten" in t for t in texte)
    # Der Hinweis ist fuer den Menschen, nicht fuer das Modell.
    assert all(
        block["type"] != "hinweis"
        for nachricht in gespraech.fuer_api(mappe)
        for block in nachricht["content"]
    )


# --- Lange Entwuerfe in Teilen -----------------------------------------------


def test_entwurf_kann_fortgesetzt_statt_ersetzt_werden(mappe, regelwerk):
    """Ein zwoelfteiliger Text entsteht in Teilen, nicht in einem Zug."""
    berater.werkzeug_ausfuehren(
        "schreiben_entwerfen",
        {"titel": "Durchsicht", "text": "Punkt 1 bis 4."},
        mappe,
        regelwerk,
    )
    berater.werkzeug_ausfuehren(
        "schreiben_entwerfen",
        {"titel": "Durchsicht", "text": "Punkt 5 bis 12.", "anhaengen": True},
        mappe,
        regelwerk,
    )
    inhalt = berater.entwurf_pfad(mappe, berater.entwuerfe(mappe)[0]).read_text(encoding="utf-8")
    assert "Punkt 1 bis 4." in inhalt
    assert "Punkt 5 bis 12." in inhalt
    assert len(berater.entwuerfe(mappe)) == 1


def test_ersetzter_entwurf_wird_benannt(mappe, regelwerk):
    """Stilles Ueberschreiben kostete gestern eine halbe Analyse."""
    berater.werkzeug_ausfuehren(
        "schreiben_entwerfen", {"titel": "Durchsicht", "text": "alt"}, mappe, regelwerk
    )
    meldung, _ = berater.werkzeug_ausfuehren(
        "schreiben_entwerfen", {"titel": "Durchsicht", "text": "neu"}, mappe, regelwerk
    )
    assert "ersetzt" in meldung


def test_entwurf_laesst_sich_wieder_lesen(mappe, regelwerk):
    leer, _ = berater.werkzeug_ausfuehren("entwurf_lesen", {}, mappe, regelwerk)
    assert "noch kein Entwurf" in leer

    berater.werkzeug_ausfuehren(
        "schreiben_entwerfen", {"titel": "Durchsicht", "text": "Punkt 1."}, mappe, regelwerk
    )
    liste, _ = berater.werkzeug_ausfuehren("entwurf_lesen", {}, mappe, regelwerk)
    assert "Durchsicht" in liste

    name = berater.entwuerfe(mappe)[0]
    inhalt, _ = berater.werkzeug_ausfuehren("entwurf_lesen", {"name": name}, mappe, regelwerk)
    assert "Punkt 1." in inhalt


def test_unbekannter_entwurf_ergibt_einen_hinweis(mappe, regelwerk):
    with pytest.raises(berater.BeratungsFehler, match="keinen Entwurf"):
        berater.werkzeug_ausfuehren("entwurf_lesen", {"name": "../steuer.json"}, mappe, regelwerk)


# --- Das Werkzeug liest seine eigenen Unterlagen -----------------------------


@pytest.fixture
def mappe_im_projekt(tmp_path: Path) -> Arbeitsmappe:
    """Eine Mappe, wie sie tatsaechlich liegt: im Verzeichnis des Werkzeugs."""
    projekt = tmp_path / "werkzeug"
    projekt.mkdir()
    (projekt / "pyproject.toml").write_text("[project]\nname = 'steuer'\n", encoding="utf-8")
    (projekt / "README.md").write_text("# Handbuch\n\nErstattungen mindern den Aufwand.\n", encoding="utf-8")
    (projekt / "WEITER-HIER.md").write_text("# Stand\n", encoding="utf-8")
    (projekt / "geheim.txt").write_text("kein Markdown", encoding="utf-8")
    return Arbeitsmappe.anlegen(projekt / "steuer-2024", 2024, Profil(veranlagungsjahr=2024))


def test_unterlagen_werden_gefunden_und_gelesen(mappe_im_projekt, regelwerk):
    liste, _ = berater.werkzeug_ausfuehren("unterlagen_lesen", {}, mappe_im_projekt, regelwerk)
    assert "README.md" in liste and "WEITER-HIER.md" in liste
    assert "geheim.txt" not in liste

    text, _ = berater.werkzeug_ausfuehren(
        "unterlagen_lesen", {"name": "README.md"}, mappe_im_projekt, regelwerk
    )
    assert "Erstattungen mindern den Aufwand." in text


def test_unterlagen_fuehren_nicht_aus_dem_projekt_heraus(mappe_im_projekt):
    assert berater.projektunterlage_pfad(mappe_im_projekt, "../README.md") is None
    assert berater.projektunterlage_pfad(mappe_im_projekt, "steuer-2024/steuer.json") is None
    assert berater.projektunterlage_pfad(mappe_im_projekt, "gibtsnicht.md") is None


def test_mappe_ausserhalb_des_projekts_sagt_das(mappe, regelwerk):
    text, _ = berater.werkzeug_ausfuehren("unterlagen_lesen", {}, mappe, regelwerk)
    assert "keine Projektunterlagen erreichbar" in text


def test_veraltete_gesamtauswertung_wird_als_solche_gekennzeichnet(mappe, regelwerk):
    """Was sie als fehlend meldet, kann laengst hochgeladen sein."""
    mappe.gesamtauswertung_speichern(
        {"gesamteinschaetzung": "x", "luecken": [], "chancen": [], "erstellt_am": "2020-01-01"}
    )
    lage = berater.lage_text(mappe, regelwerk)
    assert "Seit dieser Auswertung sind Belege dazugekommen" in lage


def test_frische_gesamtauswertung_ohne_warnung(mappe, regelwerk):
    mappe.gesamtauswertung_speichern(
        {"gesamteinschaetzung": "x", "luecken": [], "chancen": [], "erstellt_am": "2099-01-01"}
    )
    assert "Belege dazugekommen" not in berater.lage_text(mappe, regelwerk)


def test_lagebild_fuehrt_auch_belege_ohne_und_mit_fremdem_jahr(mappe, tmp_path, regelwerk):
    """Zweimal wurde ein vorhandener Beleg als fehlend gemeldet, weil er hier fehlte."""
    from steuer.models import Analyse as A

    for name, jahr in (("report_ohne_jahr.txt", None), ("report_2025.txt", 2025)):
        quelle = tmp_path / name
        quelle.write_text(name, encoding="utf-8")
        dokument, _ = mappe.datei_aufnehmen(quelle)
        dokument.analyse = A(dokumenttyp="Finanzreport", aussteller="comdirect", steuerjahr=jahr)

    lage = berater.lage_text(mappe, regelwerk)
    assert "report_ohne_jahr.txt" in lage
    assert "report_2025.txt" in lage
    # Und der Zusammenhang muss erkennbar bleiben: sie gehen in keine Summe ein.
    assert "in keine Summe eingehen" in lage


# --- Das Veranlagungsjahr nachtragen -----------------------------------------


def test_jahr_setzen_holt_belege_ins_jahr(mappe, tmp_path, regelwerk):
    """Ohne Jahr geht ein Beleg in keine Summe ein und fehlt in der Ablage."""
    from steuer.models import Analyse as A

    quelle = tmp_path / "finanzreport.txt"
    quelle.write_text("report", encoding="utf-8")
    dokument, _ = mappe.datei_aufnehmen(quelle)
    dokument.analyse = A(dokumenttyp="Finanzreport", aussteller="comdirect")
    assert dokument.gehoert_ins_jahr is None

    meldung, _ = berater.werkzeug_ausfuehren(
        "jahr_setzen",
        {"dokument_ids": [dokument.id], "jahr": 2024, "begruendung": "Kontoauszug 2024"},
        mappe,
        regelwerk,
    )
    assert "ohne Jahr -> 2024" in meldung
    assert Arbeitsmappe.laden(mappe.wurzel).dokument(dokument.id).gehoert_ins_jahr == 2024


def test_jahr_setzen_meldet_was_schon_stimmte(mappe, regelwerk):
    kennung = beleg(mappe, "zinsen.txt").id
    meldung, _ = berater.werkzeug_ausfuehren(
        "jahr_setzen",
        {"dokument_ids": [kennung], "jahr": 2024, "begruendung": "passt schon"},
        mappe,
        regelwerk,
    )
    assert "Unveraendert" in meldung


def test_jahr_setzen_weist_unsinnige_jahre_ab(mappe, regelwerk):
    kennung = beleg(mappe, "zinsen.txt").id
    with pytest.raises(berater.BeratungsFehler, match="plausibles"):
        berater.werkzeug_ausfuehren(
            "jahr_setzen",
            {"dokument_ids": [kennung], "jahr": 24, "begruendung": "Tippfehler"},
            mappe,
            regelwerk,
        )


def test_jahr_setzen_bricht_bei_unbekannter_kennung_ab(mappe, regelwerk):
    """Lieber gar nichts aendern als die Haelfte und dann abbrechen - sichtbar bleibt es so."""
    dokument = beleg(mappe, "anhaenger.txt")
    with pytest.raises(berater.BeratungsFehler, match="keinen Beleg"):
        berater.werkzeug_ausfuehren(
            "jahr_setzen",
            {"dokument_ids": [dokument.id, "gibtsnicht"], "jahr": 2023, "begruendung": "x"},
            mappe,
            regelwerk,
        )
    assert dokument.gehoert_ins_jahr == 2024


def test_suche_findet_belege_ohne_jahreszuordnung(mappe, tmp_path, regelwerk):
    """Sie gehen in keine Summe ein - und waren bisher nicht gezielt auffindbar."""
    from steuer.models import Analyse as A

    quelle = tmp_path / "ohne_jahr.txt"
    quelle.write_text("x", encoding="utf-8")
    dokument, _ = mappe.datei_aufnehmen(quelle)
    dokument.analyse = A(dokumenttyp="Google Rechnung", aussteller="Google")

    text, _ = berater.werkzeug_ausfuehren(
        "dokumente_suchen", {"ohne_jahreszuordnung": True}, mappe, regelwerk
    )
    assert "ohne_jahr.txt" in text
    assert "zinsen.txt" not in text


# --- Betrag setzen und Belege bewusst nicht ansetzen -------------------------


def test_betrag_setzen_wirkt_sofort_in_den_summen(mappe, regelwerk):
    """Eine geklaerte Kategorie allein aendert keine Summe, wenn kein Betrag drinsteht."""
    kennung = beleg(mappe, "anhaenger.txt").id
    meldung, _ = berater.werkzeug_ausfuehren(
        "betrag_setzen",
        {"dokument_id": kennung, "betrag": 239.88, "begruendung": "beruflich, laut Mandant"},
        mappe,
        regelwerk,
    )
    assert "239,88" in meldung
    assert Arbeitsmappe.laden(mappe.wurzel).dokument(kennung).wirksamer_betrag == 239.88


def test_betrag_setzen_nennt_die_fremdwaehrung(mappe, regelwerk):
    kennung = beleg(mappe, "anhaenger.txt").id
    mappe.dokument(kennung).analyse.waehrung = "USD"
    meldung, _ = berater.werkzeug_ausfuehren(
        "betrag_setzen",
        {"dokument_id": kennung, "betrag": 132.40, "begruendung": "Kreditkartenabrechnung"},
        mappe,
        regelwerk,
    )
    assert "USD" in meldung


def test_betrag_setzen_ohne_begruendung_wird_abgewiesen(mappe, regelwerk):
    with pytest.raises(berater.BeratungsFehler, match="Begruendung"):
        berater.werkzeug_ausfuehren(
            "betrag_setzen",
            {"dokument_id": beleg(mappe, "anhaenger.txt").id, "betrag": 10.0, "begruendung": " "},
            mappe,
            regelwerk,
        )


def test_nicht_ansetzen_laesst_den_beleg_in_seiner_kategorie(mappe, regelwerk):
    """Nach 'nicht_steuerrelevant' umzugliedern waere eine Falschaussage."""
    dokument = beleg(mappe, "anhaenger.txt")
    berater.werkzeug_ausfuehren(
        "nicht_ansetzen",
        {"dokument_id": dokument.id, "grund": "Ueberholte Fassung der Rechnung."},
        mappe,
        regelwerk,
    )
    wieder = Arbeitsmappe.laden(mappe.wurzel).dokument(dokument.id)
    assert wieder.nicht_ansetzen is True
    assert wieder.wirksame_kategorie == "werbungskosten_sonstige"
    assert wieder.wirksamer_betrag is None


def test_nicht_ansetzen_laesst_sich_zuruecknehmen(mappe, regelwerk):
    dokument = beleg(mappe, "anhaenger.txt")
    for eingabe in (
        {"dokument_id": dokument.id, "grund": "erst mal raus"},
        {"dokument_id": dokument.id, "grund": "doch ansetzen", "rueckgaengig": True},
    ):
        berater.werkzeug_ausfuehren("nicht_ansetzen", eingabe, mappe, regelwerk)
    assert mappe.dokument(dokument.id).nicht_ansetzen is False
    assert mappe.dokument(dokument.id).wirksamer_betrag == 26.48


def test_nicht_ansetzen_verlangt_einen_grund(mappe, regelwerk):
    with pytest.raises(berater.BeratungsFehler, match="Ohne Grund"):
        berater.werkzeug_ausfuehren(
            "nicht_ansetzen",
            {"dokument_id": beleg(mappe, "anhaenger.txt").id, "grund": ""},
            mappe,
            regelwerk,
        )


def test_lagebild_zeigt_manuelle_eingriffe(mappe, regelwerk):
    dokument = beleg(mappe, "anhaenger.txt")
    dokument.manueller_betrag = 99.0
    lage = berater.lage_text(mappe, regelwerk)
    assert "Betrag manuell" in lage

    dokument.nicht_ansetzen = True
    dokument.nicht_ansetzen_grund = "doppelt erfasst"
    assert "bewusst nicht angesetzt: doppelt erfasst" in berater.lage_text(mappe, regelwerk)


# ----------------------------------------------------- Betrag und Betragsart --
#
# Ein gesetzter Betrag allein bewegt keine Summe: Ob er zaehlt, entscheidet die
# Betragsart. Bei den Zinsbescheinigungen zur Vermietung fiel das auf - rund
# 7.900 EUR standen am Beleg und in keiner Summe. Seither sagt das Werkzeug es
# selbst, statt es den Nutzer an einer zu niedrigen Summe erraten zu lassen.

def _mappe_mit_beleg(tmp_path, betragsart):
    from steuer.models import Analyse, Dokument
    from steuer.workspace import Arbeitsmappe

    mappe = Arbeitsmappe.anlegen(tmp_path / "m", 2024)
    dokument = Dokument(
        id="abc123",
        dateiname="zinsen.pdf",
        sha256="1",
        analyse=Analyse(
            dokumenttyp="Zinsbescheinigung",
            zusammenfassung="Zinsbescheinigung 2024",
            betragsart=betragsart,
        ),
    )
    mappe.dokumente = [dokument]
    return mappe, dokument


def test_betrag_ohne_passende_betragsart_wird_als_wirkungslos_gemeldet(tmp_path):
    from steuer import berater

    mappe, _ = _mappe_mit_beleg(tmp_path, "saldo")
    meldung = berater.werkzeug_ausfuehren(
        "betrag_setzen",
        {"dokument_id": "abc123", "betrag": 6483.31, "begruendung": "laut Bescheinigung"},
        mappe,
        None,
    )[0]
    assert "KEINE Summe" in meldung
    assert "saldo" in meldung


def test_betragsart_laesst_sich_mitsetzen(tmp_path):
    from steuer import berater
    from steuer.models import zaehlt_als_aufwand

    mappe, dokument = _mappe_mit_beleg(tmp_path, "saldo")
    meldung = berater.werkzeug_ausfuehren(
        "betrag_setzen",
        {
            "dokument_id": "abc123",
            "betrag": 6483.31,
            "betragsart": "aufwand",
            "begruendung": "Schuldzinsen Vermietung",
        },
        mappe,
        None,
    )[0]
    assert zaehlt_als_aufwand(dokument.analyse)
    assert dokument.wirksamer_betrag == 6483.31
    assert "Aufwand" in meldung


def test_unbekannte_betragsart_wird_abgewiesen(tmp_path):
    import pytest as _pytest

    from steuer import berater

    mappe, _ = _mappe_mit_beleg(tmp_path, "saldo")
    with _pytest.raises(berater.BeratungsFehler):
        berater.werkzeug_ausfuehren(
            "betrag_setzen",
            {
                "dokument_id": "abc123",
                "betrag": 1.0,
                "betragsart": "werbungskosten",
                "begruendung": "x",
            },
            mappe,
            None,
        )
