# Hier geht es weiter

Stand: 20. August 2026, abends. Die Ablage ist fertig, das Paket fuer
Dr. Hagn liegt bereit. Offen sind nur noch Rueckfragen und Besorgungen.

---

## Abgabefrist

Erledigt. Die Fristen für 2024 sind abgelaufen, Dr. Hagn ist informiert, ein
Verspätungszuschlag wird in Kauf genommen. **Kein Thema mehr.**

---

## Was noch fehlt und nur Menschen beschaffen können

1. **Aufschlüsselung nach § 35a — für Köln *und* Leipzig.** Das ist keine
   eigene Urkunde, sondern die Nebenkostenabrechnung mit gesondert
   ausgewiesenem **Lohnanteil**: Hausmeister, Treppenhausreinigung,
   Gartenpflege, Winterdienst, Schornsteinfeger, Heizungswartung. Nur der
   Arbeitslohn zählt, nicht das Material. 20 % davon mindern die Steuer direkt
   (höchstens 4.000 € haushaltsnahe Dienstleistungen, zusätzlich 1.200 €
   Handwerkerleistungen). Eine Pauschale gibt es dafür **nicht** — ohne
   Aufschlüsselung bleibt es bei 0,00 €. Ein Satz an den Vermieter genügt:
   *„Bitte weisen Sie mir für die Nebenkostenabrechnung 2024 die nach § 35a
   EStG begünstigten Lohnanteile gesondert aus."* Weigert er sich: als Mieter
   Belegeinsicht verlangen und die Lohnanteile selbst herausschreiben.
2. **Nebenkostenabrechnung Leipzig 2024** — beantragt, läuft. Den Satz aus
   Punkt 1 nachreichen, sonst kommt die Abrechnung ohne die Aufteilung.
   **Wichtig:** Bei Mietern zählt nach Verwaltungsauffassung meist das Jahr, in
   dem die Abrechnung *vorliegt*. Für die Erklärung 2024 wäre also die
   Abrechnung über **2023** die maßgebliche — die, die 2024 ins Haus kam. Falls
   die noch irgendwo liegt, ist sie wertvoller als die erwartete.
3. **Von der Ehefrau:** EÜR 2024 als PDF-Export aus der Rechnungs-App,
   Kontoauszüge des Geschäftskontos 2024, und die Klärung der Differenz
   zwischen −5.882,02 € (Screenshot) und −4.880,02 € (12.680,01 − 17.560,03).
4. **Verlustfeststellungsbescheid** zum Aktienverlust von 157 € aus 2023.

**Zwei Zahlen, die kein Dokument hergibt:** die Arbeitstage je Zeitraum
(Leipzig Januar–August 4 km, Köln September–Dezember 6 km) und die
Homeoffice-Tage 2024. 2023 waren es nur 47 von möglichen 210.

**Und für die Fahrten nach Halstenbek:** Datum, Anlass und Kilometer je Fahrt.
2023 wurden vier Fahrten à 414 km mit 994 € angesetzt; ohne Aufzeichnung fällt
das für 2024 weg.

---

## Genau hier weitermachen

Konsole oeffnen, eine Zeile:

```bash
cd ~/first-repo-claude-tax-return-document-tool-jesqdh && source .venv/bin/activate && cd steuer-2024 && git pull origin claude/tax-return-document-tool-jesqdh && steuer beantworten --erneut
```

Das legt die offenen **Rueckfragen** einzeln vor, der teuerste Beleg zuerst,
Kleinbetraege unter 50 EUR bleiben aussen vor. Antwort tippen, Enter. Leer =
ueberspringen, `-` = Anmerkung loeschen, `x` = abbrechen. Nach jeder Antwort
wird gespeichert; ein Abbruch kostet nichts.

**Die erste Frage ist schon beantwortet, sie muss nur eingetippt werden.** An
der ERGO-Rechnung ueber 269,19 EUR steht faelschlich ein Konsolenbefehl als
Anmerkung. Richtige Antwort:

> Privat angeschafft, Pendelstrecke. Durch Entfernungspauschale abgegolten,
> nicht zusaetzlich ansetzen.

Begruendung: Die Entfernungspauschale gilt saemtliche Fahrzeugkosten ab —
Anschaffung, Sprit, Versicherung, Steuer, Reparaturen (§ 9 Abs. 2 Satz 1 EStG).
Zusaetzlich bleiben nur Unfallkosten auf dem Arbeitsweg und Fahrkarten fuer Bus
und Bahn oberhalb der Pauschale.

**Zweite Frage, NUeRNBERGER Direktversicherung 1.509,24 EUR:** Gefragt ist, ob
neben dem Arbeitgeberbeitrag etwas aus dem Netto gezahlt wurde. Steht auf der
Gehaltsabrechnung ein Abzug „Direktversicherung" oder „Entgeltumwandlung"
*nach* der Steuerberechnung, dann ja. Steht er davor, war es Entgeltumwandlung
und damit bereits steuerfrei — dann lautet die Antwort „nur Arbeitgeberbeitrag,
keine private Zahlung".

Wenn Konsole nicht behagt: `steuer web` starten und die Anmerkung im Browser
bei jedem Dokument eintragen. Langsamer, aber der Scan steht daneben.

---

## Danach

```bash
steuer offen
```

Die Uebersicht buendelt die offenen Punkte nach Besorgung. Zuletzt sah sie so
aus (156 Einzelangaben, 12 Besorgungen):

| Belege | Summe | Besorgung |
| ---: | ---: | --- |
| 51 | 50.577,72 € | Zahlungsnachweis — Kontoauszug oder Ueberweisungsbeleg |
| 27 | 37.375,87 € | Rueckfragen — Auskunft, kein Dokument |
| 15 | −1.500,80 € | Sonstiges |
| 9 | 188.712,92 € | Lohnsteuerbescheinigung oder Gehaltsabrechnung |
| 9 | 163,71 € | Rechnung oder Aufschluesselung |
| 7 | 581,56 € | Aerztliche Verordnung oder Erstattungsnachweis |

Zu den **51 Zahlungsnachweisen:** Das waeren Ihre privaten Kontoauszuege 2024
plus PayPal. Fuer die meisten dieser Belege ist der Nachweis kein Muss, sondern
eine Absicherung fuer den Fall einer Rueckfrage. Zwingend ist er bei § 35a und
bei groesseren unbaren Zahlungen. Offene Frage an mich: welche der 51 ihn
wirklich brauchen — das kann ich durchgehen, wenn gewuenscht.

Ganz zum Schluss, wenn Antworten dazugekommen sind:

```bash
steuer ordnen --paket
```

Das kostet nichts und schreibt Ablage, Berichte und
`berichte/Steuerunterlagen_2024.zip` neu. Die Anmerkungen stehen dann im
Bericht unter der Frage, die sie beantworten.

---

## Erledigt an diesem Abend

- **Ablage folgt der Jahressicht.** Vorher lagen 271 Dokumente im Paket, waehrend
  die Kennzahlen nur 102 auswerteten. Jetzt sind es beidemal 102.
- **Zerlegte Fehlanzeigen repariert.** Das Modell schickte manchmal einen String
  statt einer Liste; der Code zerlegte ihn buchstabenweise. In der Uebersicht
  standen Zeilen wie „154 Belege: e". Die Saetze wurden beim Laden verlustfrei
  wiederhergestellt, ohne neu zu analysieren.
- **BUHA-Sammelscan getrennt und analysiert** (4 Teile, darunter der
  Kontoauszug-Export des Geschaeftskontos).
- **Warnung eingebaut:** Fahrzeugkosten neben der Entfernungspauschale sind ein
  doppelter Ansatz. Betraf die 269,19 EUR der ERGO-Rechnung.
- **Stammdaten** sind eingetragen.

---

## Zahlen, Stand heute

| | |
| --- | ---: |
| Dokumente 2024 | 102 |
| davon einreichbar | 7 |
| mit offenen Punkten | 64 |
| nicht verwertbar | 27 |
| Werbungskosten | 12.871,04 € |
| Arbeitnehmer-Pauschbetrag | 1.230 € |
| Haushaltsnahe Kosten | 0,00 € |
| Ergebnis Gewerbe der Ehefrau | Verlust 5.882,02 € |

Die Werbungskosten koennen nach der Kfz-Klaerung um 269,19 € sinken. Das waere
kein Verlust, sondern die Vermeidung eines Fehlers.

---

## Stand der Arbeitsmappen

| Mappe | Inhalt |
| --- | --- |
| `~/first-repo-claude-.../steuer-2024` | 274 Dokumente, davon 102 fuer 2024 |
| `~/gewerbe-2024` | 19 Belege des Tuftingstudios, davon nur wenige aus 2024 |
| `~/gewerbe-2025` | 541 Belege des Folgejahres |
| `~/steuer-sonstige` | 224 Dokumente anderer Jahre, überwiegend 2025 |

Seit dem Umbau müssen die nicht mehr getrennt bleiben:
`steuer zusammenfuehren <Mappe>` nimmt eine andere Mappe auf, samt Analysen.
Die Jahressicht sorgt dafür, dass trotzdem nur die Belege des jeweiligen Jahres
in die Auswertung eingehen.

---

## Was das Werkzeug seit dem Umbau kann

- **Herkunft beim Aufnehmen:** `--herkunft` und `--jahr`, in der Oberfläche zwei
  Felder unter dem Ablagebereich. Belege fremder Jahre werden nicht analysiert
  und kosten nichts. Hätte 540 von 1.100 Dokumenten kostenlos aussortiert.
- **Stammdaten:** bestätigte Werte mit Fundstelle, Fortschreibung ins Folgejahr
  über `steuer stammdaten --aus <Mappe>`.
- **Veraltete Analysen:** Ändert sich Profil oder Stammdaten, zeigt das Werkzeug,
  wie viele Analysen überholt sind. `steuer analyse --nachtragen` holt genau
  diese nach — gestartet wird nichts von allein.
- **Jahressicht:** ein Bestand, jedes Jahr greift sich heraus, was ihm gehört.
  `steuer jahre` zeigt die Verteilung.

---

## Bedienhinweise, die sich als nötig erwiesen haben

- **Immer nur eine Zeile in die Konsole einfügen.** Beim Einfügen mehrerer
  Zeilen verschluckt sie den Zeilenumbruch und klebt zwei Befehle zusammen.
  Mehrere Schritte deshalb mit `&&` zu einer Zeile verbinden.
- **Jeder neue Tab braucht die Umgebung:**
  `cd ~/first-repo-claude-tax-return-document-tool-jesqdh && source .venv/bin/activate`.
  Steht links `(.venv)`, ist alles richtig. Fehlt es, kennt die Konsole
  `steuer` nicht.
- **Ein laufender Server blockiert sein Fenster.** Für Befehle einen eigenen Tab
  öffnen (`+`), oder den Server mit `Strg` + `C` beenden. Nach einem Update muss
  er ohnehin neu gestartet werden, sonst zeigt die Oberfläche die alte Fassung.
- **In Platzhaltern nur den Platzhalter ersetzen.** Bei
  `steuer euer --name "So Lems"` bleibt `euer` stehen, es ist der Befehl.
- **Lange Texte im Browser eingeben**, nicht in der Konsole.
- **Wenn die Konsole eine Frage stellt (`>`), wartet sie auf eine Antwort,
  nicht auf einen Befehl.** Eingefuegte Befehlszeilen werden dort seit dem
  20.08. abgewiesen, aber der Beleg kommt dann erst beim naechsten Lauf wieder.
- **Der API-Schlüssel gehört in keinen Screenshot und in keinen Chat.** Er läuft
  30 Tage; danach meldet das Werkzeug `authentication_error`.
