"""Eine kleine Auszeichnungssprache in HTML uebersetzen.

Die Entwuerfe aus dem Gespraech sind Markdown. Auf der Seite standen sie
bisher als Rohtext: Ueberschriften als ``#``, Tabellen als Reihen von
Strichen. Zum Lesen ging das; zum Ausdrucken und Unterschreiben nicht - und
genau dafuer sind diese Dokumente da.

Bewusst kein fremdes Paket: Gebraucht wird der Ausschnitt, den die Entwuerfe
verwenden - Ueberschriften, Absaetze, Tabellen, Listen, Fettdruck, Trenner,
Zitate. Alles andere bleibt als Text stehen, statt zu verschwinden. Jeder
Textbestandteil wird maskiert, bevor er ins HTML geht: Ein Entwurf kann eine
Zeichenfolge enthalten, die wie ein Tag aussieht, und die soll man dann auch
sehen.
"""

from __future__ import annotations

import html
import re

# Fettdruck und Kursiv, nachdem der Text maskiert wurde. Die Reihenfolge
# zaehlt: Zwei Sternchen zuerst, sonst frisst die einfache Regel die Haelfte.
_FETT = re.compile(r"\*\*(.+?)\*\*")
_KURSIV = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")

_UEBERSCHRIFT = re.compile(r"^(#{1,6})\s+(.*)$")
_TRENNER = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
_AUFZAEHLUNG = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMMERIERT = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_TABELLENTRENNER = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")


def _inline(text: str) -> str:
    """Maskiert den Text und setzt danach die einfachen Auszeichnungen."""
    sicher = html.escape(text, quote=False)
    sicher = _CODE.sub(r"<code>\1</code>", sicher)
    sicher = _FETT.sub(r"<strong>\1</strong>", sicher)
    sicher = _KURSIV.sub(r"<em>\1</em>", sicher)
    return _LINK.sub(r'<a href="\2" rel="noopener">\1</a>', sicher)


def _zellen(zeile: str) -> list[str]:
    roh = zeile.strip()
    if roh.startswith("|"):
        roh = roh[1:]
    if roh.endswith("|"):
        roh = roh[:-1]
    return [teil.strip() for teil in roh.split("|")]


def _ist_tabellenzeile(zeile: str) -> bool:
    return "|" in zeile and zeile.strip().startswith("|")


def als_html(text: str) -> str:
    """Uebersetzt den Entwurfstext in HTML.

    Was die Uebersetzung nicht kennt, wird zum Absatz - nichts geht verloren.
    """
    zeilen = (text or "").replace("\r\n", "\n").split("\n")
    teile: list[str] = []
    absatz: list[str] = []
    liste: list[str] = []
    listenart = ""

    def absatz_schliessen() -> None:
        if absatz:
            teile.append("<p>" + "<br>".join(_inline(z) for z in absatz) + "</p>")
            absatz.clear()

    def liste_schliessen() -> None:
        nonlocal listenart
        if liste:
            punkte = "".join(f"<li>{_inline(p)}</li>" for p in liste)
            teile.append(f"<{listenart}>{punkte}</{listenart}>")
            liste.clear()
            listenart = ""

    def alles_schliessen() -> None:
        absatz_schliessen()
        liste_schliessen()

    stelle = 0
    while stelle < len(zeilen):
        zeile = zeilen[stelle]

        if not zeile.strip():
            alles_schliessen()
            stelle += 1
            continue

        if _TRENNER.match(zeile):
            alles_schliessen()
            teile.append("<hr>")
            stelle += 1
            continue

        treffer = _UEBERSCHRIFT.match(zeile)
        if treffer:
            alles_schliessen()
            stufe = min(len(treffer.group(1)), 6)
            teile.append(f"<h{stufe}>{_inline(treffer.group(2).strip())}</h{stufe}>")
            stelle += 1
            continue

        # Tabelle: Kopfzeile, Trennzeile, dann Datenzeilen bis zur naechsten
        # Zeile, die keine mehr ist.
        if (
            _ist_tabellenzeile(zeile)
            and stelle + 1 < len(zeilen)
            and _TABELLENTRENNER.match(zeilen[stelle + 1])
        ):
            alles_schliessen()
            kopf = _zellen(zeile)
            stelle += 2
            koerper: list[list[str]] = []
            while stelle < len(zeilen) and _ist_tabellenzeile(zeilen[stelle]):
                koerper.append(_zellen(zeilen[stelle]))
                stelle += 1
            kopfzeile = "".join(f"<th>{_inline(z)}</th>" for z in kopf)
            rumpf = "".join(
                "<tr>" + "".join(f"<td>{_inline(z)}</td>" for z in reihe) + "</tr>"
                for reihe in koerper
            )
            teile.append(
                '<div class="tabellenrahmen"><table><thead><tr>'
                f"{kopfzeile}</tr></thead><tbody>{rumpf}</tbody></table></div>"
            )
            continue

        if zeile.lstrip().startswith(">"):
            alles_schliessen()
            gesammelt = []
            while stelle < len(zeilen) and zeilen[stelle].lstrip().startswith(">"):
                gesammelt.append(zeilen[stelle].lstrip()[1:].strip())
                stelle += 1
            inhalt = "<br>".join(_inline(z) for z in gesammelt if z)
            teile.append(f"<blockquote>{inhalt}</blockquote>")
            continue

        treffer = _AUFZAEHLUNG.match(zeile)
        if treffer:
            absatz_schliessen()
            if listenart and listenart != "ul":
                liste_schliessen()
            listenart = "ul"
            liste.append(treffer.group(1))
            stelle += 1
            continue

        treffer = _NUMMERIERT.match(zeile)
        if treffer:
            absatz_schliessen()
            if listenart and listenart != "ol":
                liste_schliessen()
            listenart = "ol"
            liste.append(treffer.group(1))
            stelle += 1
            continue

        liste_schliessen()
        absatz.append(zeile.strip())
        stelle += 1

    alles_schliessen()
    return "\n".join(teile)


__all__ = ["als_html"]
