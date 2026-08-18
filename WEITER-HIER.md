# Hier geht es weiter

Stand: 18. August 2026, nach Auswertung der Erklärung 2023 und des Steuerbescheids 2023.

---

## Dringend, unabhängig vom Werkzeug

**Die Abgabefristen für 2024 sind abgelaufen** (31.07.2025 ohne Berater,
30.04.2026 mit Berater). Der Bescheid 2023 vom 07.01.2026 enthält den Satz, dass
die Erklärung verspätet einging und künftig mit einem Verspätungszuschlag zu
rechnen ist. Es besteht Pflicht zur Abgabe (Vermietung, Lohnersatzleistungen).
**Dr. Hagn anrufen und den Stand klären.**

Ebenfalls anzufordern, von niemandem sonst zu beschaffen:

- **Nebenkostenabrechnung Leipzig 2024** vom dortigen Vermieter.
- **Aufschlüsselung der haushaltsnahen Anteile** zur Kölner Nebenkostenabrechnung
  (Hausmeister, Treppenhausreinigung, Gartenpflege, Schornsteinfeger) — sonst
  bringt sie für § 35a nichts.
- **Von der Ehefrau:** EÜR 2024 als PDF-Export aus der Rechnungs-App,
  Kontoauszüge des Geschäftskontos 2024, Klärung der Differenz zwischen
  −5.882,02 € (Screenshot) und −4.880,02 € (12.680,01 minus 17.560,03).
- **Verlustfeststellungsbescheid** zum Aktienverlust von 157 € aus 2023.

---

## Stand der Arbeitsmappen

| Mappe | Inhalt |
| --- | --- |
| `~/first-repo-claude-.../steuer-2024` | 268 private Dokumente, Veranlagung 2024 |
| `~/gewerbe-2024` | 19 Dokumente des Tuftingstudios, davon nur wenige aus 2024 |
| `~/gewerbe-2025` | 541 Belege des Folgejahres, für die Erklärung 2025 |
| `~/steuer-sonstige` | 224 Dokumente aus anderen Jahren, überwiegend 2025 |

Das Profil der Mappe `steuer-2024` ist vollständig gefüllt: Tätigkeiten
(Tuftingstudio), Umzug, Vermietung, Nebenkosten, Vorjahreszahlen.

---

## Der nächste Schritt

Server starten — **eine Zeile, nichts anhängen**:

```bash
cd ~/first-repo-claude-tax-return-document-tool-jesqdh && git pull origin claude/tax-return-document-tool-jesqdh && pip install -e . && cd steuer-2024 && steuer web
```

Dann auf <http://localhost:5173>:

1. **Profil prüfen:** Häkchen bei „Eigener Haushalt" (schaltet § 35a überhaupt
   erst frei), Bruttoarbeitslohn 132.052, Gesamtbetrag der Einkünfte 135.544.
2. **Schritt 1 → „Alle erneut prüfen"** mit Sonnet 5. Dauert bei 268 Dokumenten
   etwa eine Stunde.
3. **Schritt 2 → Ordnen und auswerten** mit Gesamtauswertung.

---

## Was danach noch offen ist

- Die **AfA ist geklärt**: 7.177 EUR linear 2 %, Quelle ist die Anlage V 2023 in
  der ESt-Erklärung ab Seite 37. Dr. Hagn wird dafür nicht mehr gebraucht.
- **Homeoffice-Tage 2024** ermitteln. 2023 waren es nur 47 von möglichen 210.
- Die **19 Dokumente in `~/gewerbe-2024`** sind fast alle aus 2025 und müssten
  noch nach `~/gewerbe-2025` umziehen; ihr erkanntes Steuerjahr steht auf 2024,
  deshalb greift `--fremdes-jahr` bei ihnen nicht.

---

## Bedienhinweise, die sich als nötig erwiesen haben

- **Immer nur eine Zeile in die Konsole einfügen.** Beim Einfügen mehrerer
  Zeilen verschluckt sie den Zeilenumbruch und klebt zwei Befehle zusammen.
  Mehrere Schritte deshalb mit `&&` zu einer Zeile verbinden.
- **In Platzhaltern nur den Platzhalter ersetzen.** Bei
  `steuer euer --name "So Lems"` bleibt `euer` stehen, es ist der Befehl.
- **Lange Texte im Browser eingeben**, nicht in der Konsole.
- **Den API-Schlüssel niemals in einen Screenshot oder in den Chat.** Er läuft
  30 Tage; danach meldet das Werkzeug `authentication_error`.
- Vor Arbeiten an den Mappen den Webserver mit `Strg` + `C` beenden. Er hält den
  Bestand im Speicher und würde Änderungen sonst überschreiben.
