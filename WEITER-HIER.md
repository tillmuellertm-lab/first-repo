# Hier geht es weiter

Stand: 20. August 2026, nach dem Umbau in vier Punkten.

---

## Das Dringendste, unabhängig vom Werkzeug

**Die Abgabefristen für 2024 sind abgelaufen** (31.07.2025 ohne Berater,
30.04.2026 mit Berater). Der Bescheid 2023 vom 07.01.2026 kündigt für den
Wiederholungsfall einen Verspätungszuschlag an, und es besteht Pflicht zur
Abgabe (Vermietung, Lohnersatzleistungen). **Dr. Hagn anrufen.**

Das ist der einzige Punkt mit Zeitdruck. Alles andere kann warten.

---

## Was noch fehlt und nur Menschen beschaffen können

1. **Bescheinigung nach § 35a vom Kölner Vermieter** — die haushaltsnahen
   Anteile aus der Nebenkostenabrechnung (Hausmeister, Treppenhausreinigung,
   Gartenpflege, Schornsteinfeger). Dazu ist er auf Verlangen verpflichtet.
   Ohne sie stehen die haushaltsnahen Kosten weiter bei 0,00 EUR.
2. **Nebenkostenabrechnung Leipzig 2024** vom dortigen Vermieter.
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

## Nächster Schritt am Werkzeug

Server beenden (`Strg` + `C`), dann diese eine Zeile:

```bash
cd ~/first-repo-claude-tax-return-document-tool-jesqdh && source .venv/bin/activate && git pull origin claude/tax-return-document-tool-jesqdh && pip install -e . && cd steuer-2024 && steuer jahre && steuer status
```

`steuer jahre` zeigt, wie sich die 269 Dokumente auf die Veranlagungsjahre
verteilen. Die Kennzahlen stützen sich seit dem Umbau **nur noch auf Belege des
Jahres 2024** — die Werbungskosten können deshalb unter 12.871,04 € gefallen
sein. Das wäre kein Fehler, sondern die Korrektur einer stillen Ungenauigkeit.

Danach im Browser unter **Stammdaten** eintragen:

| Feld | Wert | Fundstelle |
| --- | --- | --- |
| Gebäude-AfA, Jahresbetrag | 7177 | ESt-Erklärung 2023, Anlage V, Zeile 33 |
| Gebäude-AfA, Satz | 2 | § 7 Abs. 4 Satz 1 Nr. 2a EStG |
| Vermietetes Objekt | Bickbargen 153a, 25469 Halstenbek | |
| Objekt angeschafft am | 02.08.2017 | Anlage V 2023, Zeile 7 |
| Objekt fertiggestellt am | 15.01.2018 | Anlage V 2023, Zeile 7 |
| Einheitswert-Aktenzeichen | 912937151516102 | Anlage V 2023, Zeile 6 |
| AfA bewegliche Wirtschaftsgüter | 920 | Anlage V 2023, Zeile 42 |
| Verlustvortrag aus Kapitalvermögen | 157 | Steuerbescheid 2023, Seite 3 |
| Steuernummer | 219/5230/3521 | |
| Zuständiges Finanzamt | Köln-Süd | |

**Danach nicht neu analysieren.** Das Werkzeug wird melden, dass alle 269
Dokumente mit einem älteren Stand geprüft wurden — technisch richtig, praktisch
belanglos: Die Stammdaten betreffen die Anlage V, nicht die Einordnung von
Kassenbons. Der Zähler ist ein Hinweis, keine Aufforderung. Ein Neulauf kostet
5 bis 15 Euro für ein nahezu identisches Ergebnis.

Gelohnt hat er sich einmal, als das Werkzeug nichts vom Tuftingstudio und vom
Umzug wusste: plus 3.070 € Werbungskosten.

---

## Stand der Arbeitsmappen

| Mappe | Inhalt |
| --- | --- |
| `~/first-repo-claude-.../steuer-2024` | 269 private Dokumente, Veranlagung 2024 |
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
- **Der API-Schlüssel gehört in keinen Screenshot und in keinen Chat.** Er läuft
  30 Tage; danach meldet das Werkzeug `authentication_error`.
