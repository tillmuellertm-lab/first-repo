"""Entwuerfe muessen sich ausdrucken und unterschreiben lassen.

Auf der Seite standen sie als Rohtext: Ueberschriften als '#', Tabellen als
Reihen von Strichen. Zum Lesen ging das - zum Unterschreiben nicht, und genau
dafuer sind diese Dokumente da.
"""

from __future__ import annotations

from steuer.markdown import als_html


def test_ueberschriften_und_absaetze():
    html = als_html("# Titel\n\nEin Satz.\nNoch einer.")
    assert "<h1>Titel</h1>" in html
    assert "<p>Ein Satz.<br>Noch einer.</p>" in html


def test_tabelle_wird_zur_tabelle():
    text = (
        "| Position | Betrag |\n"
        "|---|---|\n"
        "| Unterkunft | 2.000,00 EUR |\n"
        "| Verpflegung | 910,00 EUR |\n"
    )
    html = als_html(text)
    assert "<th>Position</th>" in html
    assert "<td>2.000,00 EUR</td>" in html
    assert html.count("<tr>") == 3  # Kopf plus zwei Zeilen
    assert "|" not in html


def test_fettdruck_und_kursiv():
    html = als_html("Summe **3.000,00 EUR**, davon *geschaetzt* nichts.")
    assert "<strong>3.000,00 EUR</strong>" in html
    assert "<em>geschaetzt</em>" in html


def test_listen():
    assert "<ul><li>eins</li><li>zwei</li></ul>" in als_html("- eins\n- zwei")
    assert "<ol><li>eins</li></ol>" in als_html("1. eins")


def test_trenner_und_zitat():
    assert "<hr>" in als_html("---")
    assert "<blockquote>Bitte pruefen.</blockquote>" in als_html("> Bitte pruefen.")


def test_html_im_text_wird_maskiert():
    """Ein Entwurf kann eine Zeichenfolge enthalten, die wie ein Tag aussieht."""
    html = als_html("Der Wert <b>ist</b> gesetzt.")
    assert "&lt;b&gt;" in html
    assert "<b>" not in html


def test_paragraphenzeichen_und_umlaute_bleiben():
    html = als_html("Nach § 9 Abs. 4a EStG gekürzt.")
    assert "§ 9 Abs. 4a EStG" in html
    assert "gekürzt" in html


def test_leerer_text_ergibt_leeres_html():
    assert als_html("") == ""
    assert als_html("   \n\n  ") == ""


def test_unbekanntes_geht_nicht_verloren():
    html = als_html("~~durchgestrichen~~")
    assert "durchgestrichen" in html


def test_unterschriftszeile_bleibt_erhalten():
    html = als_html("Koeln, den ............\n\n............\nTill Mueller")
    assert "Till Mueller" in html
    assert "Koeln, den" in html
