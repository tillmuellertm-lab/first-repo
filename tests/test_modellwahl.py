"""Die angebotene Modellwahl muss auch ankommen.

`_pruefen` setzt einen unbekannten Wert stillschweigend auf den Standard
zurueck - richtig gegenueber Eingaben aus dem Browser, gefaehrlich gegenueber
einem Tippfehler in unserer eigenen Auswahlliste: Wer im Feld "Fable 5" waehlt,
bekaeme dann ohne jede Meldung das Standardmodell. Diese Tests schliessen genau
diese Luecke.
"""

from __future__ import annotations

import pytest

from steuer.analyze import (
    AUSWAHL_BERATUNG,
    AUSWAHL_DENKTIEFE,
    AUSWAHL_DOKUMENT,
    AUSWAHL_STRATEGIE,
    modell_beratung_pruefen,
    modell_dokument_pruefen,
    modell_strategie_pruefen,
    denktiefe_pruefen,
)

# Kennungen, die es bei Anthropic wirklich gibt. Eine Kennung, die hier nicht
# steht, wuerde die API mit einem Fehler ablehnen.
BEKANNTE_KENNUNGEN = {
    "claude-fable-5",
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-haiku-4-5",
}

AUSWAHLEN = (
    (AUSWAHL_DOKUMENT, modell_dokument_pruefen),
    (AUSWAHL_STRATEGIE, modell_strategie_pruefen),
    (AUSWAHL_BERATUNG, modell_beratung_pruefen),
)


@pytest.mark.parametrize("auswahl, pruefen", AUSWAHLEN)
def test_jede_angebotene_wahl_kommt_an(auswahl, pruefen):
    for kennung, bezeichnung, _ in auswahl:
        assert pruefen(kennung) == kennung, (
            f"'{bezeichnung}' waere im Feld waehlbar, wuerde aber auf das "
            f"Standardmodell zurueckfallen."
        )


@pytest.mark.parametrize("auswahl, _pruefen", AUSWAHLEN)
def test_nur_existierende_modelle_werden_angeboten(auswahl, _pruefen):
    for kennung, _, _ in auswahl:
        assert kennung in BEKANNTE_KENNUNGEN


@pytest.mark.parametrize("auswahl, pruefen", AUSWAHLEN)
def test_unbekannte_kennung_faellt_auf_den_standard_zurueck(auswahl, pruefen):
    standard = pruefen("claude-gibt-es-nicht")
    assert standard in {kennung for kennung, _, _ in auswahl}


@pytest.mark.parametrize("auswahl, _pruefen", AUSWAHLEN)
def test_jede_wahl_traegt_bezeichnung_und_erlaeuterung(auswahl, _pruefen):
    for kennung, bezeichnung, erlaeuterung in auswahl:
        assert bezeichnung.strip(), f"{kennung} ohne Bezeichnung"
        assert erlaeuterung.strip(), f"{kennung} ohne Erlaeuterung"


def test_fable_steht_dort_zur_wahl_wo_abgewogen_wird():
    """Fable 5 ist das staerkste Modell - es gehoert dorthin, wo geurteilt wird."""
    assert "claude-fable-5" in {k for k, _, _ in AUSWAHL_STRATEGIE}
    assert "claude-fable-5" in {k for k, _, _ in AUSWAHL_BERATUNG}


# --------------------------------------------------------------- Denktiefe ---
#
# Die Denktiefe ist die groesste Stellschraube fuer die Wartezeit. Sie geht als
# output_config.effort an die API; ein Wert, den die API nicht kennt, wuerde die
# Anfrage mit einem Fehler beantworten statt sie langsamer zu machen.

ERLAUBTE_STUFEN = {"low", "medium", "high", "xhigh", "max"}


def test_jede_angebotene_denktiefe_kommt_an():
    for stufe, bezeichnung, _ in AUSWAHL_DENKTIEFE:
        assert denktiefe_pruefen(stufe) == stufe, f"'{bezeichnung}' faellt zurueck"


def test_nur_von_der_api_gekannte_stufen():
    for stufe, _, _ in AUSWAHL_DENKTIEFE:
        assert stufe in ERLAUBTE_STUFEN


def test_unbekannte_stufe_faellt_auf_den_standard_zurueck():
    assert denktiefe_pruefen("sehr-gruendlich") in ERLAUBTE_STUFEN
    assert denktiefe_pruefen(None) in ERLAUBTE_STUFEN


def test_denktiefe_erreicht_die_api():
    """Ohne diese Zusicherung waere die Wahl im Feld reine Zierde."""
    gesehen = {}

    class Client:
        class messages:  # noqa: N801 - spiegelt die SDK-Form
            @staticmethod
            def create(**argumente):
                gesehen.update(argumente)
                return object()

    from steuer.analyze import Analysedienst

    dienst = Analysedienst(api_key="x", _client=Client())
    dienst.beratung(system="s", werkzeuge=[], nachrichten=[], denktiefe="low")
    assert gesehen["output_config"] == {"effort": "low"}
