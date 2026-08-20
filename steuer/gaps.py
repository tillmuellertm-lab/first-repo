"""Regelbasierte Auswertung: Kennzahlen, Luecken, Chancen und Warnungen.

Diese Stufe laeuft ohne Modellaufruf. Sie liefert das, was sich rein rechnerisch
und aus dem Regelwerk ableiten laesst, und dient der Gesamtauswertung durch das
Modell als Grundlage, damit dieses nicht dieselben Standardluecken noch einmal
findet.
"""

from __future__ import annotations

import datetime as _dt
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

from . import taxonomy
from .formatierung import euro
from .models import (
    EIGNUNG_BEDINGT,
    EIGNUNG_GEEIGNET,
    EIGNUNG_UNGEEIGNET,
    Befund,
    Dokument,
    Profil,
)
from .rules import Regelwerk

# Welche Dokumentkategorien einen Punkt der Checkliste abdecken.
CHECK_KATEGORIEN: dict[str, tuple[str, ...]] = {
    "stammdaten": ("stammdaten", "vorjahr"),
    "lohnsteuerbescheinigung": ("nichtselbstaendige_arbeit",),
    "lohnersatzleistungen": ("lohnersatzleistungen",),
    "fahrten_arbeit": ("werbungskosten_fahrten",),
    "homeoffice": ("werbungskosten_arbeitszimmer",),
    "arbeitsmittel": ("werbungskosten_arbeitsmittel",),
    "fortbildung": ("werbungskosten_fortbildung",),
    "bewerbungskosten": ("werbungskosten_sonstige",),
    "doppelte_haushaltsfuehrung": ("werbungskosten_sonstige",),
    "umzug": ("werbungskosten_sonstige", "haushaltsnahe_aufwendungen"),
    "gewerkschaft": ("werbungskosten_sonstige",),
    "vorsorge_kranken": ("vorsorgeaufwendungen",),
    "vorsorge_sonstige": ("vorsorgeaufwendungen",),
    "riester": ("altersvorsorge_av",),
    "kapitalertraege": ("kapitalertraege",),
    "kirchensteuer": ("sonderausgaben", "vorjahr"),
    "spenden": ("sonderausgaben",),
    "handwerker": ("haushaltsnahe_aufwendungen",),
    "haushaltsnahe_dienstleistungen": ("haushaltsnahe_aufwendungen",),
    "aussergewoehnliche_belastungen": ("aussergewoehnliche_belastungen",),
    "behinderung": ("aussergewoehnliche_belastungen",),
    "kinder": ("kinder",),
    "vermietung": ("vermietung",),
    "selbstaendig": ("selbstaendig",),
    "renten": ("renten",),
    "krypto_sonstiges": ("sonstige_einkuenfte",),
    "ausland": ("auslandseinkuenfte",),
    "unterhalt": ("unterhalt",),
}

# Zusaetzliche Stichworte fuer Checklistenpunkte, die sich eine Kategorie teilen.
CHECK_STICHWORTE: dict[str, tuple[str, ...]] = {
    "bewerbungskosten": ("bewerbung", "vorstellung", "absage"),
    "doppelte_haushaltsfuehrung": ("zweitwohnung", "doppelte haushalt", "familienheimfahrt"),
    "umzug": ("umzug", "spedition", "makler"),
    "gewerkschaft": ("gewerkschaft", "berufsverband", "kammer", "mitgliedsbeitrag"),
    "vorsorge_kranken": ("kranken", "pflegeversicherung", "beitragsbescheinigung"),
    "vorsorge_sonstige": ("haftpflicht", "berufsunfaehigkeit", "unfallversicherung", "risikoleben", "ruerup", "basisrente"),
    "kirchensteuer": ("kirchensteuer",),
    "spenden": ("spende", "zuwendung"),
    "handwerker": ("handwerk", "installat", "elektro", "maler", "sanitaer", "dach", "heizung", "schornstein", "reparatur"),
    "haushaltsnahe_dienstleistungen": ("nebenkosten", "betriebskosten", "reinigung", "garten", "winterdienst", "hausmeister", "pflegedienst", "haushaltshilfe"),
    "behinderung": ("behinder", "gdb", "merkzeichen", "feststellungsbescheid"),
    "aussergewoehnliche_belastungen": ("zuzahlung", "rezept", "zahn", "brille", "arzt", "klinik", "kur", "hoergeraet", "therapie"),
}

# Kategorien, deren Summen als Werbungskosten nach Paragraf 9 EStG zaehlen.
WERBUNGSKOSTEN_KATEGORIEN = (
    "werbungskosten_fahrten",
    "werbungskosten_arbeitsmittel",
    "werbungskosten_arbeitszimmer",
    "werbungskosten_fortbildung",
    "werbungskosten_sonstige",
)


@dataclass
class Auswertung:
    kennzahlen: dict[str, Any] = field(default_factory=dict)
    befunde: list[Befund] = field(default_factory=list)

    def nach_art(self, art: str) -> list[Befund]:
        return [b for b in self.befunde if b.art == art]

    @property
    def luecken(self) -> list[Befund]:
        return self.nach_art("luecke")

    @property
    def chancen(self) -> list[Befund]:
        return self.nach_art("chance")

    @property
    def warnungen(self) -> list[Befund]:
        return self.nach_art("warnung")


def _gilt(eintrag: dict[str, Any], profil: Profil) -> bool:
    """Prueft die Bedingungen eines Checklisten- oder Chanceneintrags."""
    for merkmal in eintrag.get("gilt_wenn", []) or []:
        if not profil.hat(str(merkmal)):
            return False
    for merkmal in eintrag.get("gilt_nicht_wenn", []) or []:
        if profil.hat(str(merkmal)):
            return False
    return True


def _suchtext(dokument: Dokument) -> str:
    analyse = dokument.analyse
    if not analyse:
        return dokument.dateiname.lower()
    teile = [
        dokument.dateiname,
        analyse.dokumenttyp,
        analyse.aussteller,
        analyse.zusammenfassung,
        " ".join(p.bezeichnung for p in analyse.positionen),
    ]
    return " ".join(teile).lower()


def _verwertbar(dokument: Dokument) -> bool:
    analyse = dokument.analyse
    return bool(analyse and analyse.eignung in (EIGNUNG_GEEIGNET, EIGNUNG_BEDINGT))


def _erfuellt(check_id: str, dokumente: list[Dokument]) -> list[Dokument]:
    """Liefert die Dokumente, die einen Checklistenpunkt abdecken."""
    kategorien = CHECK_KATEGORIEN.get(check_id, ())
    stichworte = CHECK_STICHWORTE.get(check_id, ())
    treffer = []
    for dokument in dokumente:
        if not _verwertbar(dokument):
            continue
        if dokument.wirksame_kategorie not in kategorien:
            continue
        if stichworte and not any(wort in _suchtext(dokument) for wort in stichworte):
            continue
        treffer.append(dokument)
    return treffer


def _summe(dokumente: Iterable[Dokument]) -> float:
    gesamt = 0.0
    for dokument in dokumente:
        analyse = dokument.analyse
        if not analyse or analyse.eignung == EIGNUNG_UNGEEIGNET:
            continue
        betrag = analyse.betrag_abzugsfaehig
        if betrag is None:
            betrag = analyse.betrag_gesamt
        if betrag:
            gesamt += float(betrag)
    return round(gesamt, 2)


def kennzahlen(dokumente: list[Dokument], regelwerk: Regelwerk, profil: Profil) -> dict[str, Any]:
    """Rechnerische Kennzahlen ueber den gesamten Bestand."""
    nach_kategorie: dict[str, list[Dokument]] = defaultdict(list)
    for dokument in dokumente:
        nach_kategorie[dokument.wirksame_kategorie].append(dokument)

    summen = {
        kategorie_id: _summe(liste)
        for kategorie_id, liste in nach_kategorie.items()
        if kategorie_id not in taxonomy.AUSGESCHLOSSEN
    }

    werbungskosten = round(sum(summen.get(k, 0.0) for k in WERBUNGSKOSTEN_KATEGORIEN), 2)
    haushaltsnah = _summe(nach_kategorie.get("haushaltsnahe_aufwendungen", []))

    faktor = 2 if profil.veranlagungsart == "zusammen" else 1
    an_pauschbetrag = float(regelwerk.wert("arbeitnehmer_pauschbetrag", 0) or 0)

    return {
        "anzahl_dokumente": len(dokumente),
        "anzahl_analysiert": sum(1 for d in dokumente if d.analyse),
        "anzahl_geeignet": sum(1 for d in dokumente if d.analyse and d.analyse.eignung == EIGNUNG_GEEIGNET),
        "anzahl_bedingt": sum(1 for d in dokumente if d.analyse and d.analyse.eignung == EIGNUNG_BEDINGT),
        "anzahl_ungeeignet": sum(1 for d in dokumente if d.analyse and d.analyse.eignung == EIGNUNG_UNGEEIGNET),
        "summen_je_kategorie": dict(sorted(summen.items(), key=lambda p: taxonomy.sortierschluessel(p[0]))),
        "werbungskosten_gesamt": werbungskosten,
        "arbeitnehmer_pauschbetrag": an_pauschbetrag,
        "werbungskosten_ueber_pauschbetrag": round(werbungskosten - an_pauschbetrag, 2),
        "haushaltsnahe_aufwendungen_gesamt": haushaltsnah,
        "haushaltsnahe_ermaessigung_geschaetzt": round(haushaltsnah * 0.2, 2),
        "sonderausgaben_gesamt": summen.get("sonderausgaben", 0.0),
        "aussergewoehnliche_belastungen_gesamt": summen.get("aussergewoehnliche_belastungen", 0.0),
        "veranlagungsfaktor": faktor,
    }


def _frist_pruefen(regelwerk: Regelwerk, heute: _dt.date) -> list[Befund]:
    befunde: list[Befund] = []
    fristen = regelwerk.fristen or {}
    for schluessel, beschriftung in (
        ("abgabe_mit_berater", "Abgabefrist mit Steuerberater"),
        ("abgabe_ohne_berater", "Abgabefrist ohne Steuerberater"),
    ):
        roh = fristen.get(schluessel)
        if not roh:
            continue
        try:
            frist = _dt.date.fromisoformat(str(roh))
        except ValueError:
            continue
        tage = (frist - heute).days
        if tage < 0:
            befunde.append(
                Befund(
                    art="warnung",
                    id=f"frist_{schluessel}",
                    titel=f"{beschriftung} verstrichen",
                    beschreibung=(
                        f"Die Frist ist am {frist.strftime('%d.%m.%Y')} abgelaufen. "
                        "Der Steuerberater sollte moeglichst bald ueber den Stand informiert werden; "
                        "Verspaetungszuschlaege sind moeglich."
                    ),
                    prioritaet="hoch",
                )
            )
        elif tage <= 90:
            befunde.append(
                Befund(
                    art="warnung",
                    id=f"frist_{schluessel}",
                    titel=f"{beschriftung} in {tage} Tagen",
                    beschreibung=f"Die Frist laeuft am {frist.strftime('%d.%m.%Y')} ab.",
                    prioritaet="hoch" if tage <= 30 else "mittel",
                )
            )
    return befunde


def _dubletten_pruefen(dokumente: list[Dokument]) -> list[Befund]:
    gesehen: dict[tuple[str, str, float], list[str]] = defaultdict(list)
    for dokument in dokumente:
        analyse = dokument.analyse
        if not analyse or analyse.betrag_gesamt is None or not analyse.datum:
            continue
        schluessel = (
            analyse.aussteller.strip().lower(),
            analyse.datum,
            round(float(analyse.betrag_gesamt), 2),
        )
        if schluessel[0]:
            gesehen[schluessel].append(dokument.id)
    befunde = []
    for (aussteller, datum, betrag), ids in gesehen.items():
        if len(ids) > 1:
            befunde.append(
                Befund(
                    art="warnung",
                    id=f"dublette_{ids[0]}",
                    titel="Moegliche Dublette",
                    beschreibung=(
                        f"{len(ids)} Dokumente von {aussteller} vom {datum} ueber {betrag:.2f} EUR. "
                        "Vor der Uebergabe pruefen, ob es sich um denselben Beleg handelt."
                    ),
                    prioritaet="mittel",
                    betroffene_dokumente=ids,
                )
            )
    return befunde


def _dokumentwarnungen(dokumente: list[Dokument], jahr: int, regelwerk: Regelwerk) -> list[Befund]:
    befunde: list[Befund] = []

    # Lange PDF werden aus Kostengruenden nur bis zu einer Seitengrenze geprueft.
    # Gerade bei einer Steuererklaerung stehen die wertvollen Anlagen aber hinten,
    # deshalb darf das nicht stillschweigend geschehen.
    unvollstaendig = [
        d
        for d in dokumente
        if d.analyse
        and any("Seiten wurden analysiert" in h or "Seiten analysiert" in h for h in d.analyse.hinweise)
    ]
    if unvollstaendig:
        beispiele = ", ".join(f"{d.dateiname} ({d.seiten or '?'} Seiten)" for d in unvollstaendig[:5])
        befunde.append(
            Befund(
                art="warnung",
                id="nur_teilweise_geprueft",
                titel=f"{len(unvollstaendig)} Dokumente wurden nur teilweise gelesen",
                beschreibung=(
                    f"Betroffen: {beispiele}. Von diesen Dateien wurden nur die vorderen "
                    "Seiten geprueft. Bei einer Steuererklaerung oder einem Sammelscan "
                    "stehen die wichtigsten Anlagen jedoch hinten - eine Anlage V mit der "
                    "Gebaeude-AfA etwa. Den hinteren Teil nachtraeglich pruefen mit: "
                    "steuer analyse --dokument <Kennung> --ab-seite <Seite>"
                ),
                prioritaet="hoch",
                betroffene_dokumente=[d.id for d in unvollstaendig],
            )
        )

    falsches_jahr = [
        d for d in dokumente
        if d.analyse and d.analyse.steuerjahr and d.analyse.steuerjahr != jahr
    ]
    if falsches_jahr:
        beispiele = ", ".join(
            f"{d.dateiname} ({d.analyse.steuerjahr})" for d in falsches_jahr[:5] if d.analyse
        )
        befunde.append(
            Befund(
                art="warnung",
                id="falsches_steuerjahr",
                titel=f"{len(falsches_jahr)} Dokumente gehoeren in ein anderes Jahr",
                beschreibung=(
                    f"Betroffen: {beispiele}. "
                    "Bei Paragraf 35a und Sonderausgaben zaehlt das Zahlungsdatum, nicht das Rechnungsdatum. "
                    "Diese Belege gehoeren voraussichtlich in eine andere Arbeitsmappe."
                ),
                prioritaet="hoch",
                betroffene_dokumente=[d.id for d in falsches_jahr],
            )
        )

    barzahlung = [
        d for d in dokumente
        if d.analyse
        and d.wirksame_kategorie in ("haushaltsnahe_aufwendungen", "kinder")
        and d.analyse.zahlungsart == "bar"
    ]
    if barzahlung:
        befunde.append(
            Befund(
                art="warnung",
                id="barzahlung_35a",
                titel=f"{len(barzahlung)} bar gezahlte Belege sind nicht abzugsfaehig",
                beschreibung=(
                    "Bei haushaltsnahen Leistungen nach Paragraf 35a EStG und bei Kinderbetreuungskosten "
                    "ist die unbare Zahlung zwingend. Barzahlung schliesst den Abzug vollstaendig aus. "
                    "Falls doch ueberwiesen wurde, den Kontoauszug nachreichen."
                ),
                prioritaet="hoch",
                betroffene_dokumente=[d.id for d in barzahlung],
            )
        )

    unbelegt = [
        d for d in dokumente
        if d.analyse and d.analyse.eignung == EIGNUNG_BEDINGT and d.analyse.fehlende_nachweise
    ]
    if unbelegt:
        befunde.append(
            Befund(
                art="luecke",
                id="fehlende_nachweise",
                titel=f"{len(unbelegt)} Belege sind noch unvollstaendig",
                beschreibung=(
                    "Zu diesen Dokumenten fehlt noch etwas, damit sie verwertbar sind. "
                    "Die Einzelheiten stehen in der Dokumentliste unter 'Fehlt noch'."
                ),
                prioritaet="hoch",
                betroffene_dokumente=[d.id for d in unbelegt],
            )
        )

    ungeeignet = [d for d in dokumente if d.analyse and d.analyse.eignung == EIGNUNG_UNGEEIGNET]
    if ungeeignet:
        befunde.append(
            Befund(
                art="warnung",
                id="ungeeignete_dokumente",
                titel=f"{len(ungeeignet)} Dokumente sind steuerlich nicht verwertbar",
                beschreibung=(
                    "Sie liegen im Ordner 99 und gehen nicht an den Steuerberater. "
                    "Vor dem Aussortieren kurz gegenlesen, ob die Einschaetzung stimmt."
                ),
                prioritaet="niedrig",
                betroffene_dokumente=[d.id for d in ungeeignet],
            )
        )

    unsicher = [d for d in dokumente if d.analyse and d.analyse.vertrauen < 0.5]
    if unsicher:
        befunde.append(
            Befund(
                art="warnung",
                id="geringe_sicherheit",
                titel=f"{len(unsicher)} Dokumente konnten nur unsicher eingeordnet werden",
                beschreibung=(
                    "Meist liegt es an der Scanqualitaet. Ein besserer Scan oder eine kurze Notiz "
                    "zum Dokument verbessert die Einordnung deutlich."
                ),
                prioritaet="mittel",
                betroffene_dokumente=[d.id for d in unsicher],
            )
        )

    if regelwerk.ist_ersatz:
        befunde.append(
            Befund(
                art="warnung",
                id="rechtsstand_ersatz",
                titel=f"Kein gepflegter Rechtsstand fuer {regelwerk.jahr}",
                beschreibung=(
                    f"Es wurden ersatzweise die Werte aus {regelwerk.quelle_jahr} verwendet. "
                    f"Mit 'steuer recht-update --jahr {regelwerk.jahr}' laesst sich ein Entwurf "
                    "auf Basis aktueller Quellen erzeugen."
                ),
                prioritaet="hoch",
            )
        )
    return befunde


def _fahrzeugkosten_pruefen(dokumente: list[Dokument], profil: Profil) -> list[Befund]:
    """Warnt, wenn Fahrzeugkosten neben der Entfernungspauschale stehen.

    Die Entfernungspauschale gilt alle Aufwendungen fuer den Weg zur Arbeit ab -
    Anschaffung, Sprit, Versicherung, Steuer, Reparaturen (§ 9 Abs. 2 Satz 1
    EStG). Wer sie zusaetzlich ansetzt, rechnet zweimal dasselbe. Das Werkzeug
    zaehlt solche Belege aber stumpf zu den Werbungskosten, weil in der Kategorie
    'werbungskosten_fahrten' auch berechtigte Posten liegen (Bahnticket ueber der
    Pauschale, Unfallkosten). Deshalb keine stille Korrektur, sondern ein Hinweis.
    """
    if not profil.hat("pendler"):
        return []
    betroffen = [
        d
        for d in dokumente
        if d.wirksame_kategorie == "werbungskosten_fahrten"
        and d.analyse
        and (d.analyse.betrag_abzugsfaehig or d.analyse.betrag_gesamt)
    ]
    if not betroffen:
        return []
    summe = round(_summe(betroffen), 2)
    if not summe:
        return []
    return [
        Befund(
            art="warnung",
            id="fahrzeugkosten_neben_entfernungspauschale",
            titel="Fahrzeugkosten koennen nicht neben die Entfernungspauschale treten",
            beschreibung=(
                f"{len(betroffen)} Belege unter 'Fahrten' ergeben {summe:.2f} EUR. "
                "Die Entfernungspauschale gilt saemtliche Aufwendungen fuer den Weg "
                "zur ersten Taetigkeitsstaette ab: Anschaffung, Kraftstoff, "
                "Versicherung, Kfz-Steuer, Reparaturen und Wertverlust "
                "(§ 9 Abs. 2 Satz 1 EStG). Ein privat angeschafftes Fahrzeug, mit "
                "dem gependelt wird, aendert daran nichts. Zusaetzlich absetzbar "
                "bleiben nur Unfallkosten auf dem Arbeitsweg sowie Fahrkarten fuer "
                "oeffentliche Verkehrsmittel, soweit sie ueber der Pauschale liegen. "
                "Diese Belege gehen derzeit in die Werbungskosten ein - bitte "
                "einzeln pruefen, welche davon wirklich hinzukommen."
            ),
            anlage="Anlage N",
            prioritaet="hoch",
            betroffene_dokumente=[d.id for d in betroffen],
        )
    ]


def _rechnerische_chancen(
    zahlen: dict[str, Any], regelwerk: Regelwerk, profil: Profil
) -> list[Befund]:
    befunde: list[Befund] = []

    werbungskosten = zahlen["werbungskosten_gesamt"]
    pauschbetrag = zahlen["arbeitnehmer_pauschbetrag"]
    if profil.hat("angestellt") and pauschbetrag:
        if werbungskosten < pauschbetrag:
            fehlbetrag = round(pauschbetrag - werbungskosten, 2)
            befunde.append(
                Befund(
                    art="chance",
                    id="werbungskosten_unter_pauschbetrag",
                    titel="Werbungskosten liegen noch unter dem Pauschbetrag",
                    beschreibung=(
                        f"Erfasst sind {werbungskosten:.2f} EUR, der Arbeitnehmer-Pauschbetrag betraegt "
                        f"{pauschbetrag:.0f} EUR. Erst {fehlbetrag:.2f} EUR mehr wirken sich ueberhaupt aus. "
                        "Am schnellsten gelingt das ueber die Entfernungspauschale, Homeoffice-Tage, "
                        "Arbeitsmittel und Fortbildungen."
                    ),
                    anlage="Anlage N",
                    prioritaet="hoch",
                    potenzial_eur=None,
                )
            )
        else:
            befunde.append(
                Befund(
                    art="chance",
                    id="werbungskosten_ueber_pauschbetrag",
                    titel="Werbungskosten uebersteigen den Pauschbetrag",
                    beschreibung=(
                        f"Erfasst sind {werbungskosten:.2f} EUR, das sind "
                        f"{werbungskosten - pauschbetrag:.2f} EUR ueber dem Pauschbetrag. "
                        "Jeder weitere Beleg wirkt sich ab jetzt voll aus."
                    ),
                    anlage="Anlage N",
                    prioritaet="mittel",
                )
            )

    # Entfernungspauschale aus dem Profil rechnen, wenn die Angaben da sind.
    if profil.hat("pendler") and profil.entfernung_km and profil.arbeitstage:
        km = float(profil.entfernung_km)
        tage = int(profil.arbeitstage)
        satz_kurz = float(regelwerk.wert("entfernungspauschale_bis_20km", 0.30) or 0.30)
        satz_lang = float(regelwerk.wert("entfernungspauschale_ab_21km", 0.38) or 0.38)
        betrag = tage * (min(km, 20) * satz_kurz + max(0.0, km - 20) * satz_lang)
        befunde.append(
            Befund(
                art="chance",
                id="entfernungspauschale_berechnet",
                titel=f"Entfernungspauschale ergibt rund {euro(betrag, 0)}",
                beschreibung=(
                    f"{tage} Arbeitstage bei {km:g} km einfacher Entfernung: "
                    f"{min(km, 20):g} km zu {satz_kurz:.2f} EUR"
                    + (f" und {max(0.0, km - 20):g} km zu {satz_lang:.2f} EUR" if km > 20 else "")
                    + f" ergeben {euro(betrag)} Werbungskosten. "
                    "Der Steuerberater braucht dafuer nur die Anzahl der Arbeitstage und die "
                    "einfache Entfernung, keine Belege."
                ),
                anlage="Anlage N",
                prioritaet="hoch",
                potenzial_eur=round(betrag, 2),
            )
        )

    if profil.hat("homeoffice") and profil.homeoffice_tage:
        eintrag = regelwerk.eintrag("homeoffice_pauschale_pro_tag")
        satz = float(eintrag.get("wert", 6) or 6)
        max_tage = int(eintrag.get("max_tage", 210) or 210)
        tage = min(int(profil.homeoffice_tage), max_tage)
        betrag = tage * satz
        befunde.append(
            Befund(
                art="chance",
                id="homeoffice_berechnet",
                titel=f"Homeoffice-Pauschale ergibt {euro(betrag, 0)}",
                beschreibung=(
                    f"{tage} Tage zu {satz:.0f} EUR ergeben {euro(betrag)}. "
                    f"Maximal anerkannt werden {max_tage} Tage. "
                    "Fuer denselben Tag kann nicht zusaetzlich die Entfernungspauschale angesetzt werden."
                ),
                anlage="Anlage N",
                prioritaet="mittel",
                potenzial_eur=round(betrag, 2),
            )
        )

    # Paragraf 35a: Ausschoepfung der Hoechstbetraege.
    eintrag = regelwerk.eintrag("handwerkerleistungen_hoechstbetrag_aufwand")
    hoechstbetrag = float(eintrag.get("wert", 6000) or 6000)
    max_ermaessigung = float(eintrag.get("max_steuerermaessigung", 1200) or 1200)
    haushaltsnah = zahlen["haushaltsnahe_aufwendungen_gesamt"]
    if profil.hat("eigener_haushalt"):
        if haushaltsnah <= 0:
            befunde.append(
                Befund(
                    art="chance",
                    id="35a_ungenutzt",
                    titel="Paragraf 35a ist bisher vollstaendig ungenutzt",
                    beschreibung=(
                        f"Bis zu {max_ermaessigung:.0f} EUR Steuerermaessigung fuer Handwerkerleistungen "
                        "und bis zu 4.000 EUR fuer haushaltsnahe Dienstleistungen bleiben liegen. "
                        "Diese Ermaessigung mindert die Steuer direkt, nicht nur das zu versteuernde Einkommen. "
                        "Typische Belege: Schornsteinfeger, Heizungswartung, Reinigung, Gartenpflege, "
                        "Winterdienst und die Nebenkostenabrechnung."
                    ),
                    anlage="Anlage haushaltsnahe Aufwendungen",
                    prioritaet="hoch",
                    potenzial_eur=max_ermaessigung,
                )
            )
        elif haushaltsnah < hoechstbetrag:
            rest = hoechstbetrag - haushaltsnah
            befunde.append(
                Befund(
                    art="chance",
                    id="35a_luft_nach_oben",
                    titel=f"Paragraf 35a: noch {euro(rest, 0)} Aufwand anrechenbar",
                    beschreibung=(
                        f"Erfasst sind {euro(haushaltsnah)} Lohnanteil, das sind rund "
                        f"{euro(haushaltsnah * 0.2)} Steuerermaessigung. "
                        f"Bis zum Hoechstbetrag von {euro(hoechstbetrag, 0)} sind noch "
                        f"{euro(rest)} moeglich, also weitere {euro(rest * 0.2)} Ermaessigung."
                    ),
                    anlage="Anlage haushaltsnahe Aufwendungen",
                    prioritaet="mittel",
                    potenzial_eur=round(rest * 0.2, 2),
                )
            )
        else:
            befunde.append(
                Befund(
                    art="warnung",
                    id="35a_ausgeschoepft",
                    titel="Hoechstbetrag fuer Handwerkerleistungen ist erreicht",
                    beschreibung=(
                        f"Mit {euro(haushaltsnah)} ist der Hoechstbetrag von {euro(hoechstbetrag, 0)} "
                        "ausgeschoepft. Weitere Rechnungen wirken sich in diesem Jahr nicht mehr aus. "
                        "Sofern moeglich, die Zahlung offener Rechnungen ins naechste Jahr verschieben; "
                        "massgeblich ist das Zahlungsdatum."
                    ),
                    prioritaet="mittel",
                )
            )

    # Zumutbare Belastung bei aussergewoehnlichen Belastungen.
    agb = zahlen["aussergewoehnliche_belastungen_gesamt"]
    if agb > 0 and profil.gesamtbetrag_der_einkuenfte:
        grenze = zumutbare_belastung(
            float(profil.gesamtbetrag_der_einkuenfte), regelwerk, profil
        )
        if grenze is not None:
            wirksam = round(agb - grenze, 2)
            if wirksam > 0:
                befunde.append(
                    Befund(
                        art="chance",
                        id="agb_wirksam",
                        titel=f"Aussergewoehnliche Belastungen wirken mit {euro(wirksam)}",
                        beschreibung=(
                            f"Erfasst sind {euro(agb)}, die zumutbare Belastung betraegt "
                            f"{euro(grenze)}. Der Rest mindert das zu versteuernde Einkommen."
                        ),
                        anlage="Aussergewoehnliche Belastungen",
                        prioritaet="mittel",
                        potenzial_eur=wirksam,
                    )
                )
            else:
                befunde.append(
                    Befund(
                        art="chance",
                        id="agb_unter_grenze",
                        titel="Aussergewoehnliche Belastungen bleiben unter der zumutbaren Belastung",
                        beschreibung=(
                            f"Erfasst sind {euro(agb)}, wirksam wird erst, was ueber "
                            f"{euro(grenze)} liegt. Es fehlen noch {euro(grenze - agb)}. "
                            "Deshalb lohnt es sich, alle Zuzahlungen zusammenzutragen und planbare "
                            "Behandlungen in einem Jahr zu buendeln. Die Krankenkasse stellt auf "
                            "Anfrage eine Zuzahlungsbescheinigung aus."
                        ),
                        anlage="Aussergewoehnliche Belastungen",
                        prioritaet="mittel",
                    )
                )

    if profil.hat("behinderung") and profil.grad_der_behinderung:
        betrag = behinderten_pauschbetrag(int(profil.grad_der_behinderung), regelwerk)
        if betrag:
            befunde.append(
                Befund(
                    art="chance",
                    id="behinderten_pauschbetrag",
                    titel=f"Behinderten-Pauschbetrag {euro(betrag, 0)}",
                    beschreibung=(
                        f"Bei einem Grad der Behinderung von {profil.grad_der_behinderung} betraegt der "
                        f"Pauschbetrag {euro(betrag, 0)}. Er wird ohne Einzelnachweis gewaehrt; "
                        "der Feststellungsbescheid oder Ausweis muss beiliegen."
                    ),
                    anlage="Aussergewoehnliche Belastungen",
                    prioritaet="hoch",
                    potenzial_eur=float(betrag),
                )
            )

    if profil.hat("pflege") and profil.pflegegrad:
        schluessel = {2: "pflege_pauschbetrag_grad_2", 3: "pflege_pauschbetrag_grad_3"}.get(
            int(profil.pflegegrad), "pflege_pauschbetrag_grad_4_5"
        )
        betrag = regelwerk.wert(schluessel)
        if betrag and int(profil.pflegegrad) >= 2:
            befunde.append(
                Befund(
                    art="chance",
                    id="pflege_pauschbetrag",
                    titel=f"Pflege-Pauschbetrag {euro(float(betrag), 0)}",
                    beschreibung=(
                        f"Bei Pflegegrad {profil.pflegegrad} steht ein Pauschbetrag von "
                        f"{euro(float(betrag), 0)} zu, wenn die Pflege unentgeltlich erfolgt."
                    ),
                    anlage="Aussergewoehnliche Belastungen",
                    prioritaet="hoch",
                    potenzial_eur=float(betrag),
                )
            )
    return befunde


def zumutbare_belastung(
    gesamtbetrag: float, regelwerk: Regelwerk, profil: Profil
) -> float | None:
    """Stufenweise Berechnung nach Paragraf 33 Abs. 3 EStG (BFH VI R 75/14)."""
    daten = regelwerk.daten.get("zumutbare_belastung")
    if not isinstance(daten, dict):
        return None
    stufen = daten.get("stufen_gesamtbetrag_der_einkuenfte") or []
    saetze = daten.get("saetze") or {}

    if profil.anzahl_kinder >= 3:
        gruppe = "drei_oder_mehr_kinder"
    elif profil.anzahl_kinder >= 1:
        gruppe = "ein_oder_zwei_kinder"
    elif profil.veranlagungsart == "zusammen":
        gruppe = "verheiratet_ohne_kind"
    else:
        gruppe = "ledig_ohne_kind"

    prozente = saetze.get(gruppe)
    if not prozente or len(stufen) + 1 != len(prozente):
        return None

    grenzen = [0.0, *[float(s) for s in stufen], float("inf")]
    gesamt = 0.0
    for index, prozent in enumerate(prozente):
        untergrenze, obergrenze = grenzen[index], grenzen[index + 1]
        anteil = max(0.0, min(gesamtbetrag, obergrenze) - untergrenze)
        gesamt += anteil * float(prozent) / 100.0
    return round(gesamt, 2)


def behinderten_pauschbetrag(grad: int, regelwerk: Regelwerk) -> float | None:
    daten = regelwerk.daten.get("behinderten_pauschbetrag")
    if not isinstance(daten, dict):
        return None
    passend = None
    for eintrag in daten.get("staffel", []):
        if grad >= int(eintrag.get("gdb", 0)):
            passend = float(eintrag.get("betrag", 0))
    return passend


# Hoechstens so viele Chancen aus Einzeldokumenten uebernehmen. Bei sehr grossen
# Mappen entstehen sonst tausende fast gleichlautende Eintraege, die weder der
# Nutzer lesen noch die Gesamtauswertung verarbeiten kann.
MAX_DOKUMENTHINWEISE = 25


def _hinweise_zusammenfassen(dokumente: list[Dokument]) -> list[Befund]:
    """Fasst die Optimierungshinweise der Einzeldokumente zusammen.

    Gleichlautende Hinweise aus vielen Dokumenten werden zu einem Befund
    gebuendelt, der alle betroffenen Dokumente nennt.
    """
    gebuendelt: dict[str, list[str]] = defaultdict(list)
    for dokument in dokumente:
        if not dokument.analyse:
            continue
        for hinweis in dokument.analyse.optimierungshinweise:
            text = " ".join(str(hinweis).split())
            if text:
                gebuendelt[text].append(dokument.id)

    # Haeufigste Hinweise zuerst: was viele Belege betrifft, wiegt schwerer.
    sortiert = sorted(gebuendelt.items(), key=lambda paar: (-len(paar[1]), paar[0]))

    befunde: list[Befund] = []
    for nummer, (text, ids) in enumerate(sortiert[:MAX_DOKUMENTHINWEISE]):
        titel = "Aus einem Beleg" if len(ids) == 1 else f"Aus {len(ids)} Belegen"
        befunde.append(
            Befund(
                art="chance",
                id=f"dokumenthinweis_{nummer}",
                titel=titel,
                beschreibung=text,
                prioritaet="mittel",
                betroffene_dokumente=ids,
            )
        )

    uebrig = len(sortiert) - len(befunde)
    if uebrig > 0:
        befunde.append(
            Befund(
                art="chance",
                id="dokumenthinweise_weitere",
                titel=f"{uebrig} weitere Einzelhinweise",
                beschreibung=(
                    f"Aus den Belegen stammen {uebrig} weitere Hinweise, die hier nicht "
                    "einzeln aufgefuehrt sind. Sie stehen jeweils in der Detailansicht "
                    "des betreffenden Dokuments unter 'Ansatzpunkte'."
                ),
                prioritaet="niedrig",
            )
        )
    return befunde


def _stammdaten_hinweis(stammdaten) -> list[Befund]:
    """Macht sichtbar, welche Werte aus den Vorjahren uebernommen wurden."""
    if not stammdaten:
        return []
    gesetzt = stammdaten.gesetzte()
    if not gesetzt:
        return []
    zeilen = []
    for eintrag in gesetzt:
        teil = f"{eintrag.label or eintrag.id}: {eintrag.wert}"
        if eintrag.einheit and eintrag.einheit != "text":
            teil += f" {eintrag.einheit}"
        if eintrag.quelle:
            teil += f" (Quelle: {eintrag.quelle})"
        zeilen.append(teil)
    return [
        Befund(
            art="hinweis",
            id="stammdaten_uebernommen",
            titel=f"{len(gesetzt)} Werte aus den Stammdaten uebernommen",
            beschreibung=(
                "Diese Werte stammen nicht aus einem Beleg dieses Jahres, sondern aus "
                "bestaetigten Angaben der Vorjahre: " + "; ".join(zeilen) + "."
            ),
            prioritaet="niedrig",
        )
    ]


def _erledigt(eintrag: dict, stammdaten) -> bool:
    """Prueft, ob ein bestaetigter Stammdatenwert den Eintrag gegenstandslos macht.

    Steht die Gebaeude-AfA als bestaetigter Wert in der Mappe, ist sie keine
    Luecke mehr - auch wenn kein einzelnes Dokument sie belegt.
    """
    kennung = eintrag.get("erledigt_wenn_stammdatum")
    return bool(kennung and stammdaten and kennung in stammdaten)


def auswerten(
    dokumente: list[Dokument],
    regelwerk: Regelwerk,
    profil: Profil,
    heute: _dt.date | None = None,
    stammdaten=None,
) -> Auswertung:
    """Fuehrt die vollstaendige regelbasierte Auswertung durch."""
    heute = heute or _dt.date.today()
    zahlen = kennzahlen(dokumente, regelwerk, profil)
    befunde: list[Befund] = []

    # Checkliste: was fehlt?
    for eintrag in regelwerk.checkliste:
        check_id = str(eintrag.get("id", ""))
        if not _gilt(eintrag, profil) or _erledigt(eintrag, stammdaten):
            continue
        treffer = _erfuellt(check_id, dokumente)
        if treffer:
            continue
        erwartet = eintrag.get("erwartete_dokumente") or []
        beschreibung = ""
        if erwartet:
            beschreibung = "Erwartet werden: " + "; ".join(str(e) for e in erwartet) + "."
        if eintrag.get("hinweis"):
            beschreibung = (beschreibung + " " + str(eintrag["hinweis"])).strip()
        befunde.append(
            Befund(
                art="luecke",
                id=f"check_{check_id}",
                titel=str(eintrag.get("titel", check_id)),
                beschreibung=beschreibung or "Zu diesem Bereich liegt noch nichts vor.",
                anlage=str(eintrag.get("anlage", "")),
                prioritaet=str(eintrag.get("prioritaet", "mittel")),
            )
        )

    # Chancen aus dem Regelwerk.
    for eintrag in regelwerk.chancen:
        if not _gilt(eintrag, profil) or _erledigt(eintrag, stammdaten):
            continue
        potenzial = eintrag.get("potenzial_eur")
        befunde.append(
            Befund(
                art="chance",
                id=f"regel_{eintrag.get('id')}",
                titel=str(eintrag.get("titel", "")),
                beschreibung=str(eintrag.get("beschreibung", "")).strip(),
                prioritaet="mittel",
                potenzial_eur=float(potenzial) if potenzial else None,
            )
        )

    befunde.extend(_rechnerische_chancen(zahlen, regelwerk, profil))
    befunde.extend(_dokumentwarnungen(dokumente, regelwerk.jahr, regelwerk))
    befunde.extend(_fahrzeugkosten_pruefen(dokumente, profil))
    befunde.extend(_dubletten_pruefen(dokumente))
    befunde.extend(_frist_pruefen(regelwerk, heute))
    befunde.extend(_stammdaten_hinweis(stammdaten))

    befunde.extend(_hinweise_zusammenfassen(dokumente))

    reihenfolge = {"hoch": 0, "mittel": 1, "niedrig": 2}
    befunde.sort(key=lambda b: (reihenfolge.get(b.prioritaet, 3), b.titel))
    return Auswertung(kennzahlen=zahlen, befunde=befunde)
