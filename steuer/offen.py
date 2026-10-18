"""Buendelung der offenen Punkte nach der Besorgung, die sie aufloest.

Eigenes Modul, weil sowohl die Kommandozeile als auch die Weboberflaeche die
Einteilung brauchen. Die Oberflaeche darf die Kommandozeile nicht importieren.
"""

from __future__ import annotations

import re

# Wonach sich die offenen Punkte buendeln lassen. Das Modell formuliert jede
# Fehlanzeige neu ("Kontoauszug mit tatsaechlicher Abbuchung der vier Raten"),
# weshalb wortgleiches Gruppieren nichts zusammenbringt: 180 Einzelangaben
# ergaben 180 Gruppen. Entscheidend ist nicht der Wortlaut, sondern die
# Besorgung dahinter - und die wiederholt sich sehr wohl.
# Reihenfolge = Vorrang; die erste zutreffende Zeile gewinnt.
# Die Muster binden nur am Wortanfang: Im Deutschen wachsen die Woerter
# hinten weiter ("Kontoauszuege", "Versicherungsbestaetigung"), eine
# schliessende Wortgrenze wuerde genau diese Faelle verfehlen.
OFFEN_THEMEN: tuple[tuple[str, str, str], ...] = (
    ("frage", r"\b(kl[aä]rung|klarstellung|zuordnung|angabe, ob|klären, ob|umrechnen)",
     "Rueckfrage - keine Besorgung, sondern eine Auskunft von Ihnen"),
    ("zahlung", r"\b(kontoausz|zahlungsnachweis|[uü]berweisungsbeleg|lastschrift|paypal|"
                r"abbuchung|einzahlungsquittung|zahlungsbest[aä]tigung)",
     "Zahlungsnachweis - Kontoauszug oder Ueberweisungsbeleg"),
    ("lohn", r"\b(lohnsteuerbescheinigung|gehaltsabrechnung|lohnabrechnung|"
             r"lohn-/gehaltsabrechnung)",
     "Lohnsteuerbescheinigung oder Gehaltsabrechnung"),
    ("nebenkosten", r"\b(nebenkostenabrechnung|betriebskostenabrechnung|grundsteuerbescheid)",
     "Nebenkosten- oder Betriebskostenabrechnung"),
    ("mietvertrag", r"\b(mietvertrag|renovierungsklausel|renovierungspflicht|"
                    r"renovierungsverpflichtung|kaution|[uü]bergabeprotokoll)",
     "Mietvertrag, Kautions- oder Uebergabeunterlagen"),
    ("arzt", r"\b([aä]rztliche|attest|verordnung|rezept|medizinische[rn]? notwendigkeit|"
             r"krankenkasse|erstattung)",
     "Aerztliche Verordnung oder Nachweis der Erstattung"),
    ("beruflich", r"\b(berufliche[rn]? (veranlassung|nutzung)|betriebliche[rn]? nutzung|"
                  r"nutzungsanteil|nutzungsnachweis|fahrtenbuch|arbeitgeberbest[aä]tigung)",
     "Nachweis der beruflichen Veranlassung oder Nutzung"),
    ("umzug", r"\b(umzugskosten|doppelte[rn]? miete|doppelmiete|bukg)",
     "Umzugsunterlagen"),
    ("betrieb", r"\b(e[uü]er|gesch[aä]ftskonto|eingangsrechnung|ausgangsrechnung|"
                r"abschreibungstabelle|geringwertige)",
     "Unterlagen aus dem Gewerbe Ihrer Frau"),
    ("versicherung", r"\b(versicherung|direktversicherung|beitrags|jahrespr[aä]mie|"
                     r"entgeltumwandlung|bav)",
     "Bescheinigung der Versicherung"),
    ("rechnung", r"\b(rechnung|aufschl[uü]sselung|aufteilung|detailaufl|leistungsnachweis|"
                 r"beitragsrechnung)",
     "Rechnung oder Aufschluesselung der Posten"),
)


def thema(text: str) -> tuple[str, str]:
    """Ordnet eine Fehlanzeige der Besorgung zu, die sie aufloest."""
    vereinfacht = re.sub(r"\s+", " ", text.strip().lower())
    for kennung, muster, beschriftung in OFFEN_THEMEN:
        if re.search(muster, vereinfacht):
            return kennung, beschriftung
    return "sonstiges", "Sonstiges - Einzelfaelle ohne gemeinsame Ursache"
