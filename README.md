# Steuer-Assistent

Bereitet eingescannte Unterlagen für die deutsche Einkommensteuererklärung so auf,
dass ein Steuerberater sie ohne Rückfragen übernehmen kann.

Das Werkzeug prüft jedes Dokument einzeln, benennt es sprechend, sortiert es in die
richtige Anlage, erstellt eine Übersicht für den Berater und sagt Ihnen, **was noch
fehlt** und **wo Geld liegen bleibt**.

> **Keine Steuerberatung.** Das Werkzeug sortiert und beschreibt Unterlagen, es berät nicht.
> Alle Einordnungen, Beträge und Hinweise sind maschinell erzeugte Vorschläge und müssen
> von Ihrem Steuerberater fachlich geprüft werden.

---

## Was das Werkzeug tut

| Aufgabe | Umsetzung |
| --- | --- |
| Dokument verstehen | Claude liest den Scan direkt (PDF oder Bild), erkennt Art, Aussteller, Datum, Beträge |
| Eignung prüfen | vier Stufen: geeignet, bedingt geeignet, nicht geeignet, unklar — mit Begründung |
| Formfehler finden | Barzahlung bei § 35a, fehlender Lohnanteil, falsches Steuerjahr, fehlender Zahlungsnachweis |
| Sinnvoll benennen | `03_2024-03-15_Handwerkerrechnung_Elektro-Mueller_1189-42EUR_PRUEFEN.pdf` |
| Struktur erzeugen | Ordner in der Reihenfolge der Steuererklärung, von `00_Stammdaten` bis `99_Nicht_steuerrelevant` |
| Übersicht erstellen | HTML zum Ausdrucken oder als PDF, Markdown und CSV für den Berater |
| Lücken erkennen | Checkliste je Veranlagungsjahr, abgeglichen mit Ihrem Profil |
| Chancen erkennen | ausgerechnete Pauschalen, ungenutzte Höchstbeträge, Gestaltungsansätze |
| Aktuell bleiben | versionierte Regeldateien je Jahr plus Recherche-Befehl mit Web-Suche |
| Sammelscans trennen | erkennt mehrere Dokumente in einer PDF und zerlegt sie seitengenau |

---

## Installation

Voraussetzung ist Python 3.10 oder neuer.

```bash
git clone <dieses-repository>
cd first-repo

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
```

Für die Dokumentanalyse wird ein API-Schlüssel von Anthropic benötigt. Erzeugen unter
<https://console.anthropic.com/settings/keys>, dann hinterlegen:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Damit der Schlüssel dauerhaft gesetzt ist, gehört die Zeile in `~/.bashrc` oder `~/.zshrc`.

Ohne Schlüssel lassen sich alle Funktionen außer der inhaltlichen Analyse nutzen:
Ordnen, Berichte, Lücken- und Chancenanalyse laufen rein lokal.

---

## Schnellstart

```bash
# 1. Arbeitsmappe für ein Veranlagungsjahr anlegen
steuer init --jahr 2025 --name "Vorname Nachname"
cd steuer-2025

# 2. Ausgangslage erfassen — das ist der wichtigste Schritt für die Lückenanalyse
steuer profil --bearbeiten

# 3. Scans aufnehmen (einzelne Dateien oder ganze Ordner)
steuer hinzufuegen ~/Scans/Steuer2025/

# 4. Dokumente prüfen lassen
steuer analyse

# 5. Sehen, was fehlt und wo etwas zu holen ist
steuer pruefen

# 6. Ablage und Übersicht für den Steuerberater erzeugen
steuer ordnen --paket --gesamtauswertung
```

Danach liegt in `berichte/` ein ZIP, das Sie dem Steuerberater schicken können.

### Lieber im Browser

```bash
steuer web
```

Öffnet die Oberfläche auf <http://127.0.0.1:5173>: Scans per Drag-and-drop ablegen,
Analyse anstoßen, Ergebnisse mit Vorschau des Originals durchsehen, Kategorien von Hand
korrigieren, Bericht erzeugen. Der Server lauscht ausschließlich lokal.

---

## Die Arbeitsmappe

```
steuer-2025/
├── steuer.json                 Jahr und Profil
├── eingang/                    Ihre Originalscans — werden nie verändert
├── aufbereitet/2025/           die sortierte Kopie für den Steuerberater
│   ├── 00_Stammdaten/
│   ├── 10_Anlage_N_Einkuenfte/
│   ├── 30_Anlage_Vorsorgeaufwand/
│   ├── 34_Haushaltsnahe_Aufwendungen/
│   └── 99_Nicht_steuerrelevant/
├── berichte/
│   ├── Uebersicht_2025.html    zum Ausdrucken oder als PDF speichern
│   ├── Uebersicht_2025.md
│   ├── Dokumentliste_2025.csv
│   └── Steuerunterlagen_2025.zip
└── .zustand/dokumente.json     alle Analyseergebnisse, lesbares JSON
```

Jeder Ordner der Ablage enthält eine `_INHALT.md` mit einer Kurzbeschreibung jedes Belegs.
Die Originale bleiben unangetastet, die Ablage wird bei jedem Lauf frisch aufgebaut.

---

## Befehle

| Befehl | Zweck |
| --- | --- |
| `steuer init --jahr 2025` | Arbeitsmappe anlegen |
| `steuer profil [--bearbeiten]` | Ausgangslage anzeigen oder erfassen |
| `steuer hinzufuegen <Pfade>` | Dateien oder Ordner aufnehmen, Dubletten werden erkannt |
| `steuer analyse [--alle]` | Dokumente prüfen; ohne `--alle` nur die neuen |
| `steuer liste` | alle Dokumente nach Anlagen sortiert |
| `steuer status` | Kennzahlen auf einen Blick |
| `steuer pruefen` | Lücken, Chancen und Warnungen |
| `steuer trennen <Kennung>` | erkannten Sammelscan seitengenau zerlegen |
| `steuer ordnen [--paket] [--gesamtauswertung]` | Ablage, Berichte, ZIP |
| `steuer recht-zeigen [--jahr]` | hinterlegten Rechtsstand anzeigen |
| `steuer recht-update --jahr 2026` | Rechtsstand recherchieren, Entwurf erzeugen |
| `steuer recht-uebernehmen --jahr 2026` | geprüften Entwurf übernehmen |
| `steuer web` | lokale Weboberfläche starten |

---

## Wie das Steuerrecht aktuell bleibt

Alle Beträge, Grenzen und Fristen liegen als versionierte YAML-Dateien im Repository,
eine Datei je Veranlagungsjahr:

```
steuer/rules/data/
├── basis.yaml    Checkliste und Optimierungsansätze, die nicht jährlich wechseln
├── 2023.yaml     erbt von 2024, pflegt nur die Abweichungen
├── 2024.yaml     Referenzjahr mit dem vollständigen Wertesatz
└── 2025.yaml     erbt von 2024, pflegt nur die Abweichungen
```

Jeder Wert trägt Bezeichnung, Betrag, Einheit und Rechtsgrundlage. Über `erbt_von`
werden nur noch die tatsächlichen Änderungen eines Jahres gepflegt.

Für ein neues Jahr:

```bash
steuer recht-update --jahr 2026
```

Claude recherchiert dabei mit Web-Suche die amtlichen Werte, bevorzugt aus BMF-Schreiben,
„Gesetze im Internet“ und dem Bundesgesetzblatt, und legt zwei Dateien ab:

* `steuer/rules/data/2026.vorschlag.yaml` — der Entwurf
* `steuer/rules/data/2026.vorschlag.md` — ein Bericht mit jeder Abweichung samt Quelle

**Der Entwurf wird nicht automatisch übernommen.** Erst nach Ihrer Durchsicht:

```bash
steuer recht-uebernehmen --jahr 2026
```

Der bisherige Stand wird dabei als `.bak` gesichert. Ein Modell soll den Rechtsstand
vorschlagen dürfen, aber nicht unbemerkt verändern.

Fehlt für ein Jahr eine Datei, lädt das Werkzeug ersatzweise das jüngste vorhandene Jahr
und weist in jeder Ausgabe und in jedem Bericht sichtbar darauf hin.

---

## Das Profil

Ohne Profil kann der Assistent Dokumente einordnen, aber nicht sagen, was fehlt: Ob eine
Anlage V fehlt, hängt davon ab, ob Sie vermieten. Erfasst werden Familienstand,
Veranlagungsart, Kinder sowie rund zwei Dutzend Merkmale (angestellt, pendelt, Homeoffice,
eigener Haushalt, Kapitalanlagen, Behinderung, Unterhalt …).

Freiwillige Zahlenangaben schalten Berechnungen frei:

* **Entfernung und Arbeitstage** → die Entfernungspauschale wird ausgerechnet,
  gestaffelt mit 0,30 € bis zum 20. und 0,38 € ab dem 21. Kilometer
* **Homeoffice-Tage** → Tagespauschale, gedeckelt auf 210 Tage
* **Grad der Behinderung / Pflegegrad** → der zustehende Pauschbetrag
* **Gesamtbetrag der Einkünfte** → die zumutbare Belastung nach § 33 Abs. 3 EStG,
  stufenweise gerechnet nach BFH VI R 75/14

---

## Datenschutz

Steuerunterlagen gehören zu den sensibelsten Daten, die ein Haushalt besitzt.

* Alles bleibt auf Ihrem Rechner. Es gibt keinen Server, keine Cloud, keine Datenbank.
* Die Weboberfläche lauscht ausschließlich auf `127.0.0.1`.
* Nach außen geht ausschließlich der Inhalt der Dokumente, die Sie analysieren lassen,
  an die Anthropic-API. Anthropic verwendet API-Daten standardmäßig nicht für Training;
  maßgeblich sind die Nutzungsbedingungen unter <https://www.anthropic.com/legal/commercial-terms>.
* Wollen Sie einzelne Dokumente gar nicht übertragen, nehmen Sie sie nicht in die Mappe
  auf und ergänzen sie später von Hand in der Ablage.
* `.gitignore` schließt Arbeitsmappen aus. Committen Sie niemals eine Mappe.

---

## Kosten

Pro Dokument fällt ein Modellaufruf an. Die Größenordnung liegt bei wenigen Cent je
Beleg; ein Jahrgang mit 80 Dokumenten kostet typischerweise unter zwei Euro. Die
abschließende Gesamtauswertung ist ein weiterer, etwas teurerer Aufruf.

Voreingestellt sind `claude-sonnet-5` für die Einzeldokumente und `claude-opus-5` für
Gesamtauswertung und Rechtsrecherche. Abweichend wählbar mit `steuer analyse --modell …`.

---

## Grenzen

Ehrlich gesagt gehört Folgendes dazu:

* Das Werkzeug **rechnet keine Steuer aus**. Es bereitet vor. Die Erklärung erstellt Ihr
  Steuerberater.
* Beträge werden aus Scans gelesen. Bei schlechter Scanqualität sinkt die
  Erkennungsgüte; jedes Dokument trägt deshalb eine Selbsteinschätzung der Sicherheit,
  und alles unter 50 % wird gesondert gemeldet.
* Die hinterlegten Werte sind sorgfältig zusammengetragen, aber nicht amtlich. Vor der
  Abgabe gehören sie mit dem Berater abgeglichen.
* Die Chancenanalyse kennt nur, was Sie ihr geben. Ein leeres Profil führt zu
  allgemeinen Hinweisen statt zu konkreten.

---

## Entwicklung

```bash
pip install -e ".[dev]"
pytest
```

Die Testabdeckung umfasst die Regelvererbung, die Berechnungen (zumutbare Belastung,
Pauschbeträge, § 35a), die Lücken- und Chancenerkennung, Benennung und Ablage, die
Berichtserzeugung samt HTML-Maskierung sowie alle Ansichten der Weboberfläche. Die
Tests laufen ohne API-Schlüssel und ohne Netzzugriff.

### Aufbau

| Modul | Aufgabe |
| --- | --- |
| `steuer/rules/` | Regelwerk je Jahr, Vererbung, Laden |
| `steuer/taxonomy.py` | Kategorien und ihre Zuordnung zu den Anlagen |
| `steuer/models.py` | Datenmodell, JSON-serialisierbar |
| `steuer/workspace.py` | Arbeitsmappe, Dateiaufnahme, Dublettenerkennung |
| `steuer/extract.py` | Aufbereitung der Scans für die API, PDF-Zerlegung |
| `steuer/prompts.py` | Rollenbeschreibung und Werkzeugschemata |
| `steuer/analyze.py` | Anbindung an die Claude-API mit Wiederholungslogik |
| `steuer/gaps.py` | regelbasierte Auswertung ohne Modellaufruf |
| `steuer/naming.py`, `organize.py` | Benennung und Ablage |
| `steuer/report.py` | HTML, Markdown, CSV |
| `steuer/lawupdate.py` | Rechtsstandsrecherche und Entwurfsverwaltung |
| `steuer/web/` | lokale Weboberfläche |

---

## Lizenz

MIT, siehe `LICENSE`.
