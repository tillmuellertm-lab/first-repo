# Hier geht es weiter

Stand: 1. September 2026. Die Neuanalyse aller Dokumente lief zuletzt.

## Als Erstes

```bash
cd ~/first-repo-claude-tax-return-document-tool-jesqdh && source .venv/bin/activate && git pull origin claude/tax-return-document-tool-jesqdh && cd steuer-2024 && steuer web
```

Dann <http://127.0.0.1:5173>. Im Browser einmal Strg+Umschalt+R.
Laeuft der Server schon im Fenster, blockiert er es: erst Strg+C.

## Wo wir stehen

Die Neuanalyse mit Analyseversion 4 wurde gestartet. **Als Erstes nachsehen,
ob sie durchgelaufen ist** - Seite Uebersicht, Hinweis "Dokumente wurden mit
einem aelteren Stand geprueft". Steht dort keine Zahl mehr, ist sie fertig.

Danach in dieser Reihenfolge:

| # | Schritt | Wo |
| --- | --- | --- |
| 1 | Ergebnis der Neuanalyse durchsehen, besonders die Waehrungswarnung | Seite **Luecken & Chancen** |
| 2 | Offene Faeden im Gespraech klaeren (siehe unten) | Seite **Beratung** |
| 3 | **Ordnen & Auswerten** mit Gesamtauswertung und ZIP | Seite **Uebersicht**, unten |
| 4 | Formularzuordnung durchsehen | Seite **Formular** |

## Die beiden Eigenaufstellungen

Beide sind fertig geschrieben und liegen als HTML vor; sie wurden im Chat
uebergeben und muessen als PDF in die Mappe.

| Aufstellung | Ergebnis | Stand |
| --- | ---: | --- |
| Verpflegungsmehraufwand, 11 Auswaertsspiele, alle Tagesreisen | 140,00 EUR | ersetzt die alte 280-EUR-Fassung, die aus der Mappe muss |
| Doppelte Haushaltsfuehrung 15.08.-30.09.2024 | 2.910,00 EUR | am 26.08. erstellt, war nie hochgeladen |

Geprueft: Die beiden ueberschneiden sich nicht. In den Zeitraum der doppelten
Haushaltsfuehrung faellt genau ein Auswaertsspiel - Duesseldorf am 21.09.2024 -
und dort stehen 0,00 EUR, weil die Abwesenheit unter acht Stunden lag.

## Offene Faeden im Gespraech

Diesen Text abschicken, er raeumt mehreres gleichzeitig ab:

> Die Neuanalyse ist durch. Drei Dinge:
>
> **1.** Sieh die Waehrungswarnungen durch und trag bei jedem Beleg in
> Fremdwaehrung den Euro-Betrag mit `betrag_setzen` nach.
>
> **2.** Pruef die 3.000 Euro: Die Umzugsrechnung Wuttke lautet ueber 3.000
> Euro, der Umzugskostenzuschuss des 1. FC Koeln ebenfalls. Sieh in den vier
> Koelner Gehaltsabrechnungen nach, ob der Zuschuss steuerpflichtig als
> Arbeitslohn lief oder steuerfrei als Auslagenersatz. Falls steuerfrei,
> erfasse ihn als Erstattung gegen die Umzugsrechnung.
>
> **3.** Bei den sonstigen Werbungskosten gibt es eine Formularzuordnung mit
> vier Abschnitten: doppelte Haushaltsfuehrung, Umzugskosten, Reisekosten,
> weitere Werbungskosten. Sie teilt Summen nicht selbst auf. Schreib deshalb
> bei jedem Beleg dieser Kategorie als Notiz dazu, in welchen Abschnitt er
> gehoert.

## Neu im Werkzeug, zuletzt

| Neu | Wofuer |
| --- | --- |
| **Denktiefe** im Gespraech | Schnell / Zuegig / Gruendlich. Das Gespraech lief vorher auf der langsamsten Stufe. |
| **Messzeile** unter dem Eingabefeld | Sekunden, Runden, Token aus dem Zwischenspeicher - zeigt, woran eine lange Wartezeit lag |
| Modellwahl richtig beschriftet | Fable 5 ist das leistungsfaehigste Modell und kostet das Doppelte von Opus 5 |
| `betrag_setzen`, `nicht_ansetzen` | Betrag im Gespraech setzen; Beleg aussortieren, ohne ihn zu loeschen |
| Fremdwaehrung | Nicht-Euro-Betraege zaehlen nicht mehr stillschweigend als Euro mit |
| Dubletten nach Rechnungsnummer | findet zwei Fassungen derselben Rechnung mit verschiedenen Betraegen |

## Noch nicht gebaut

Aus der Zwoelf-Punkte-Durchsicht offen: Aufteilung eines Belegs auf mehrere
Anlagen, eigene Pruefung der Formerfordernisse, Paragraf 13b Reverse Charge,
Neuanalyse als Folge einer geaenderten Notiz. Dazu: die Antwort im Gespraech
erscheint erst vollstaendig statt Satz fuer Satz - eine Umstellung darauf
wuerde die Wartezeit gefuehlt deutlich verkuerzen.

## Die 3.000 Euro sind der teuerste offene Punkt

Umzugsrechnung Wuttke 3.000 Euro, Umzugskostenzuschuss 1. FC Koeln 3.000 Euro.
Wenn der Verein steuerfreien Auslagenersatz nach § 3 Nr. 16 EStG gezahlt hat,
faellt der Werbungskostenabzug in dieser Hoehe weg. Die Umzugskostenpauschale
nach § 10 BUKG (2.893 Euro) bliebe daneben bestehen - sie deckt andere Posten
ab. Es geht um rund 1.260 Euro Steuer.

## Danach

| Schritt | Wo |
| --- | --- |
| 1. Restliche Rueckfragen beantworten | Seite **Beratung** |
| 2. **Alles neu analysieren** (5-15 Euro, 30-60 Min) | Seite **Uebersicht** |
| 3. **Ordnen** mit Gesamtauswertung und ZIP | Seite **Uebersicht**, unten |
| 4. Formularzuordnung durchsehen | Seite **Formular** |

Die Neuanalyse ist noetig, weil die neue Betragsart `erstattung` und die
korrigierte Regel zum Zahlungsdatum nur eine frische Analyse setzen kann.

## Was heute dazugekommen ist

| Neu | Wofuer |
| --- | --- |
| Betragsart `erstattung` | Kassenerstattung, Arbeitgeberzuschuss und Fahrtkostenersatz mindern den Aufwand |
| § 11 EStG im Prompt | Zahlungsdatum gilt bei allen Ausgaben, dazu die Zehn-Tage-Regel |
| `jahr_setzen` | Jahr im Gespraech nachtragen, statt jede Belegseite einzeln zu oeffnen |
| `ohne_jahreszuordnung` | Belege ohne Jahr gezielt finden - sie fielen aus allem heraus |
| Vollstaendiges Lagebild | alle Belege der Mappe, nicht nur die des Jahres |
| `unterlagen_lesen` | das Modell liest das Handbuch, bevor es ueber das Werkzeug urteilt |
| **Seite Formular** | wo welcher Betrag in der Steuererklaerung hingehoert |
| Bildschirmfotos | Strg+V direkt ins Eingabefeld |
| Abgabefrist | wird nur noch einmal gemeldet statt doppelt |
| BUKG | Pauschale und Transportkosten stehen nebeneinander, nicht zur Wahl |

## Zur Uebermittlung ans Finanzamt

Direkt aus diesem Werkzeug: nein. Jede Uebermittlung laeuft ueber ERiC, eine
Bibliothek der Finanzverwaltung, die eine Herstellerregistrierung voraussetzt.
Das ist eine harte Grenze. Und solange Dr. Hagn beauftragt ist, gilt die
Fristverlaengerung bis 30.04.2026 nur ueber ihn.

---

## Wie weit es noch ist

```bash
cd ~/first-repo-claude-tax-return-document-tool-jesqdh && source .venv/bin/activate && cd steuer-2024 && git pull origin claude/tax-return-document-tool-jesqdh && steuer status
```

Die Anlagen-Summen sind repariert und sollten jetzt deutlich kleiner sein als
zuvor. **Das ist richtig so** — siehe unten.

| Schritt | Wo | Dauer |
| --- | --- | --- |
| 1. Vier **Dubletten** löschen | Seite **Dubletten** | 5 Min |
| 2. Drei **Zinsbescheinigungen** suchen | zuerst auf der Seite **Beratung** fragen | 15 Min |
| 3. Restliche **Rückfragen** beantworten | Seite **Beratung** oder **Rückfragen** | 15 Min |
| 4. Einmal **neu analysieren** (5–15 €) | Seite **Übersicht** | 30–60 Min |
| 5. **`steuer ordnen --paket`** | Konsole | 2 Min |

---

## Der Bestand: was fehlt

`steuer bestand` gibt die ganze Mappe als kopierbare Liste aus — damit lässt
sich ein Gespräch führen, ohne dass jemand raten muss, was schon da ist.
Stand: 115 Dokumente für 2024, 24 mit eigener Anmerkung.

**Sicher fehlend:**

1. **Zinsbescheinigungen 2024** — In der Anlage V steht nur der Darlehensvertrag
   IB.SH von 2017. Für 2024 keine einzige Bescheinigung: **DSL Bank, IB.SH und
   DKB**. 2023 waren das zusammen **8.153,80 €** — der größte
   Werbungskostenblock der Anlage V.
2. **Mietvertrag und Mieteinnahmen 2024** — rund 28.800 €. Die Einnahmenseite
   der Anlage V fehlt vollständig.
3. **Gebäudeversicherung 2024** (2023: DEVK 273,67 €)
4. **Nebenkostenabrechnung 2023 für die Mieter**
5. **eToro-Steuerreport 2024**
6. **Die eigene Aufstellung zur doppelten Haushaltsführung** (2.910 €) taucht
   in der Mappe nicht auf — nur die zum Verpflegungsmehraufwand.

**Vier Dubletten löschen** (Dokument öffnen → „Aus der Mappe entfernen"):
Sammelscan Gehaltsabrechnungen RB Leipzig 77.434,62 € (2×, sonst zählt der
Bruttolohn doppelt) · Arbeitsvertrag 1. FC Köln (2×) · Abfallgebührenbescheid
251,76 € (2×) · Anhängermiete 26,48 € vom 14.08. (2×, falls es nicht wirklich
zwei Anhänger waren).

**Zwei Fehleinordnungen mit Geldwert:**

- **Steuerberaterrechnung 410,55 €** steht unter Sonderausgaben. Dort gehört
  sie seit 2006 nicht mehr hin. Der auf die Ermittlung der Einkünfte
  entfallende Teil ist **Werbungskosten** — Dr. Hagn kann das aufteilen.
- **RTL+-Abo** steht unter „nicht steuerrelevant". Für einen Bereichsleiter
  Medien ist es ein Kandidat für Werbungskosten, sobald die
  Arbeitgeberbestätigung vorliegt.

---

## Warum die Summen jetzt kleiner sind

Die Kennzahlen zählten bisher **jede Zahl**, die ein Beleg trug:

| Anlage | vorher | Fehlerquelle |
| --- | ---: | --- |
| Anlage N | 251.532,98 € | Bruttolohn doppelt, dazu 30.200 € aus einer Meldebescheinigung |
| Anlage KAP | 20.322,50 € | Kontoauszugssalden statt Kapitalerträge (tatsächlich 480 €) |
| Anlage V | 106.636,86 € | 100.000 € Darlehenssumme von 2017 |
| Sonstige WK | 12.576,77 € | 3.590 € Monatsmiete aus einem Mietvertrag |

Die Analyse liefert jetzt mit, **was** ein Betrag bedeutet — Aufwand,
Einnahme, Vertragswert oder Saldo. Nur Aufwand geht in eine Summe ein. Für
ältere Analysen wird die Art aus der Dokumentart abgeleitet, ohne dass etwas
neu laufen muss.

---

## Eigenaufstellungen, die erstellt und hochgeladen sind

| Dokument | Ergebnis |
| --- | ---: |
| Doppelte Haushaltsführung 15.08.–30.09.2024 | **2.910,00 €** |
| Verpflegungsmehraufwand Dienstreisen (15 Auswärtsspiele) | **280,00 €** |

Beide mit Herleitung, Rechtsgrundlagen und den Punkten, die Dr. Hagn entscheiden
muss. Bei der doppelten Haushaltsführung ist das der August (1.336 € als vorab
entstandene Werbungskosten, gestützt auf die Freistellung ab Mitte Juli).

---

## Geprüft und abgeschlossen

**Die Abschreibung der Immobilie Halstenbek ist korrekt.** Aus Kaufvertrag
(449.000 €, 264 m² Teilfläche), Bodenrichtwert (370 €/m², Stichtag 31.12.2016)
und Umrechnungskoeffizient (1,2886 nach der Tabelle des Gutachterausschusses
Pinneberg) ergibt sich eine Bemessungsgrundlage von 360.050 € gegenüber den
angesetzten 358.850 € — 0,3 % Abweichung. Die Sonderwünsche von 2017/2018 über
10.874 € sind bereits eingerechnet. **Kein Handlungsbedarf, kein Anruf bei B+R
nötig.**

**Die Einbauküche läuft richtig:** 9.200 € über zehn Jahre = 920 €/Jahr bis 2027.
Genau der Betrag, der als „AfA bewegliche Wirtschaftsgüter" in der Anlage V steht.

**Beide Lohnsteuerbescheinigungen sind ausgewertet:**

| | |
| --- | ---: |
| RasenBallsport Leipzig, 01.01.–31.08. | 77.434,62 € |
| 1. FC Köln, 01.09.–31.12. | 64.954,50 € |
| **Bruttoarbeitslohn 2024** | **142.389,12 €** |

Zeile 20 (Verpflegungszuschüsse) und Zeile 21 (Leistungen bei doppelter
Haushaltsführung) sind bei beiden leer — beide Eigenaufstellungen sind daher
ungekürzt ansetzbar. RB Leipzig Zeile 18: 72,00 € pauschal versteuerte
Fahrtkostenzuschüsse, die die Entfernungspauschale um diesen Betrag mindern.

**Kinderbetreuung 2024: 4.538,00 €** (Leipzig, beide Kinder), davon zwei Drittel
= **3.025,33 € Sonderausgaben**. Köln kostete nichts — der Elternbeitrag ist ab
August 2024 mit 0,00 € festgesetzt, die Zahlungen an Köln Kitas gGmbH sind reines
Essensgeld und nicht abzugsfähig.

**§ 35a Köln:** aus der Nebenkostenabrechnung 15.08.–31.12.2024 nur zwei Positionen
begünstigt — Treppenhausreinigung 98,46 € und der Lohnanteil der Gasthermenwartung
rund 109 €. Zusammen etwa **41 € Steuerermäßigung**. Der Vermieter muss nichts mehr
liefern; alle Belege liegen der Abrechnung bei.

---

## Was nachgeliefert wird, ohne den Termin zu blockieren

| Was | Bei wem | Wert |
| --- | --- | --- |
| Restliche Rechnungen ChatGPT Plus und MaxAI | Anbieterkonten, Stripe-Mails | **~250 € Steuer** |
| Nebenkostenabrechnung Leipzig mit § 35a-Lohnanteilen | Institutional InvestmentPartners GmbH | ~50–100 € |
| Jahresbescheinigungen bAV | NÜRNBERGER und Zurich | dokumentarisch |
| Ordnungsgemäße Rechnung Sixt | Sixt-Kundenkonto | Formsache |

**Zahlen, die kein Dokument hergibt** und die nur Sie liefern können:

1. **Arbeitstage 2024** je Zeitraum — Leipzig Januar–August (4 km), Köln
   September–Dezember (6 km, der Arbeitgeber rechnet mit 5)
2. **Homeoffice-Tage 2024** — 2023 waren es 47 von möglichen 210
3. **Fahrten nach Halstenbek** — eine ist durch Tankbelege belegt
   (31.01./01.02.2024), die übrigen aus dem Kalender rekonstruieren.
   Pro Fahrt rund 222 € bei 0,30 €/km für 740 km hin und zurück
5. **Testspiel FC St. Gallen am 06.01.2024** — fand das im Trainingslager
   statt? Bei mehrtägiger Auswärtstätigkeit je voller Tag 28 €, bei einer
   Woche also rund 170 € zusätzlich
6. **Sichtschutzwand Halstenbek** (1.785 € brutto, 2017) — eigenständige
   Außenanlage, nicht Teil des Gebäudes. Bei Verblendmauerwerk rund
   20 Jahre Nutzungsdauer, also etwa 89 €/Jahr bis 2037. Prüfen, ob sie in
   der Anlage V erfasst ist
4. **Von der Ehefrau:** Sind im EÜR-Export Zahlungen der Agentur für Arbeit als
   Betriebseinnahme gebucht? Der Gründungszuschuss darf dort nicht stehen.
   Und: Waren zum 31.12.2024 rund 1.002 € an Rechnungen offen?

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
5. **Kinderbetreuungskosten 2024** — Kita-/Elternbeiträge samt Zahlungsnachweis.
   Zwei Drittel davon, höchstens 4.000 € je Kind, sind Sonderausgaben.
6. **Zum DKB-Darlehen:** Restschuld des Altkredits am 30.08.2024, die
   ursprüngliche Aufteilung des Kredits von 2021 und die 2024 gezahlten Zinsen
   (DKB-Kontoauszug). Ohne Beträge ist der Zinsabzug nicht darstellbar.

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
cd ~/first-repo-claude-tax-return-document-tool-jesqdh && source .venv/bin/activate && git pull origin claude/tax-return-document-tool-jesqdh && cd steuer-2024 && steuer web
```

Dann im Browser <http://127.0.0.1:5173> oeffnen und oben auf **Beratung**
klicken. Dort einfach losschreiben — ganze Saetze, wie in einem Gespraech.
Strg+Enter sendet, der Knopf „Senden" auch.

Waehrend gearbeitet wird, erscheinen graue Zeilen wie „durchsucht die Mappe:
zins" oder „traegt Ihre Antwort bei Beleg 3f2a ein". Daran sehen Sie, worauf
die Antwort beruht. Eine Antwort dauert je nach Nachschlagen 10 bis 60 Sekunden.

Wer die Rueckfragen lieber der Reihe nach abarbeitet, hat weiterhin die Seite
**Rueckfragen** mit einem Feld je Beleg. Beides schreibt in dieselbe Notiz.

---

### Frage 1 von 16 — DKB-Privatdarlehen 35.000 EUR — fertig, nur eintippen

```
Umschuldung eines DKB-Darlehens von 2021 (2,95 %), das u.a. Ausbau der vermieteten Immobilie Halstenbek, Motorrad, HSV-Anleihe und Umzug Leipzig finanziert hatte. Neues Darlehen 6,4 %, 30.08.2024-30.07.2031, loeste dieses ab und finanzierte zusaetzlich Anwaltskosten Arbeitsvertrag 1. FC Koeln, Umzugsunternehmen, Kautionsdifferenz, Renovierung alte Wohnung, Umbau neue Wohnung, 2,5 Monate doppelte Miete, Kitagebuehr, Moebel, Haartransplantation. Zinsen nur anteilig abziehbar, Aufteilung nach Betraegen folgt.
```

**Warum:** Ein Umschuldungsdarlehen tritt in die Fussstapfen des abgeloesten
Kredits — der Verwendungszweck lebt weiter. Abziehbar sind die Zinsen nur,
soweit das Geld der Erzielung von Einkuenften diente:

| Verwendung | Zinsen abziehbar? |
| --- | --- |
| **Ausbau Halstenbek** | ✅ Anlage V, unbegrenzt, bis 2031 |
| **Anwaltskosten Arbeitsvertrag 1. FC Köln** | ✅ Anlage N |
| **Umzugsunternehmen** | ✅ Anlage N |
| **Renovierung alte Wohnung** (Mietvertragspflicht) | ✅ Anlage N |
| **2,5 Monate doppelte Miete** | ✅ Anlage N |
| Umzug Leipzig 2021 + Küche | ⚠️ Umzug ja, Küche nein |
| Kautionsdifferenz | ⚠️ strittig — Kaution ist Vermögen, kein Aufwand |
| HSV-Anleihe | ❌ § 20 Abs. 9 EStG: kein WK-Abzug bei Kapitaleinkünften |
| Motorrad, Möbel, Umbau neue Wohnung, Haartransplantation | ❌ privat |

Der wertvollste Posten ist **Halstenbek** — Anlage V, unbegrenzt, Jahr fuer Jahr
bis 2031.

**Dafuer noch zu beschaffen — ohne Betraege kann Dr. Hagn nichts ansetzen:**

1. Restschuld des alten Kredits am 30.08.2024 (welcher Teil war Abloesung?)
2. Urspruengliche Aufteilung des Kredits von 2021 — was kostete der Ausbau
   Halstenbek, was Motorrad, Anleihe, Umzug? Steht im Darlehensantrag 2021.
3. Aufteilung der neuen Posten. Vieles ist schon belegt: Wuttke 2.115,35 EUR,
   Renovierung 1.260,50 EUR, doppelte Miete.
4. Gezahlte Zinsen 2024 aus dem DKB-Kontoauszug. Bei 6,4 % ab 30.08. grob
   700 bis 800 EUR.

---

### Frage 2 — NUeRNBERGER Direktversicherung 1.509,24 EUR

Gefragt ist, ob neben dem Arbeitgeberbeitrag etwas aus dem Netto gezahlt wurde.
Steht auf der Gehaltsabrechnung ein Abzug „Direktversicherung" oder
„Entgeltumwandlung" *nach* der Steuerberechnung, dann ja. Steht er davor, war es
Entgeltumwandlung und bereits steuerfrei — dann: „nur Arbeitgeberbeitrag, keine
private Zahlung".

---

### Bereits geklaert, falls die ERGO-Rechnung noch einmal kommt

```
Privat angeschafft, Pendelstrecke. Durch Entfernungspauschale abgegolten, nicht zusaetzlich ansetzen.
```

---

## Neu aufgetaucht: Kitagebuehren

Beim Darlehen als Verwendungszweck genannt — und selbst absetzbar, unabhaengig
vom Kredit: **zwei Drittel der Kinderbetreuungskosten, hoechstens 4.000 EUR je
Kind** (§ 10 Abs. 1 Nr. 5 EStG, Stand 2024; ab 2025 sind es 80 % und 4.800 EUR).

In den offenen Punkten steht bereits „Tatsaechliche Zahlungsnachweise/
Kontoauszuege fuer 2024 gezahlte Kita-/Elternbeitraege". Das gehoert zu den
Dingen, die sich wirklich lohnen — anders als die 29,99-EUR-Abos.

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
