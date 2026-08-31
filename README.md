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
| Rückfragen klären | Gespräch mit dem Modell über den eigenen Bestand — es liest Belege nach und trägt Ihre Antworten ein |

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

## Beratung: das Gespräch über den eigenen Bestand

Der Menüpunkt **Beratung** öffnet ein Gespräch mit demselben Modell, das die Belege
ausgewertet hat — nur diesmal als Steuerexperte, der mit Ihnen spricht und nicht als
Zuarbeiter, der eine Liste abliefert.

Der Unterschied zu einem beliebigen Chat ist der Zugriff. Das Modell bekommt vor jeder
Antwort den aktuellen Stand in den Systemprompt:

* Profil, Stammdaten und den hinterlegten Rechtsstand des Jahres,
* alle Summen je Anlage und die Werbungskosten gegen den Pauschbetrag,
* jeden Beleg des Veranlagungsjahres in einer Zeile — mit Datum, Kategorie, Betrag,
  Eignung und der Notiz, die Sie bereits dazu gegeben haben,
* die regelbasierten Lücken, Chancen und Warnungen,
* die zuletzt erstellte **Gesamtauswertung**, sofern eine vorliegt,
* und die Zahl der Belege, deren Analyse nicht mehr auf dem aktuellen Stand ist.

Nicht enthalten sind die vollständigen Analysetexte, die Scans und die Belege anderer
Jahre — die holt sich das Modell bei Bedarf selbst. Dafür kann es

| Werkzeug | Wirkung |
| --- | --- |
| `dokumente_suchen` | durchsucht alle Belege, auch die anderer Jahre |
| `dokument_lesen` | die vollständige gespeicherte Analyse eines Belegs |
| `beleg_ansehen` | hängt den Originalscan ans Gespräch, wenn die Analyse nicht reicht |
| `offene_punkte` | die offenen Punkte, gebündelt nach der Besorgung dahinter |
| `kennzahlen_abrufen` | rechnet Summen und Befunde neu aus |
| `dubletten_finden` | benennt doppelt vorliegende Belege |
| `rechtsstand_lesen` | Werte, Fristen und Checkliste **jedes** Veranlagungsjahres |
| `web_search` | Recherche zu Rechtsfragen jenseits der hinterlegten Werte |
| `notiz_speichern` | **schreibt** Ihre Auskunft zum Beleg in die Mappe |
| `kategorie_setzen` | **korrigiert** eine falsche Zuordnung |
| `stammwert_speichern` | **hält** einen jahresübergreifenden Wert samt Fundstelle fest |
| `entwurf_lesen` | zeigt einen eigenen Entwurf wieder an, oder listet sie auf |
| `schreiben_entwerfen` | **legt** einen Text als Datei ab, etwa die Mail an den Steuerberater |
| `verbesserung_vorschlagen` | **notiert**, was dem Werkzeug im Gebrauch gefehlt hat |

Die letzten fünf ändern die Mappe. Das ist der eigentliche Zweck: Was Sie im Gespräch
über einen Beleg sagen, landet als Notiz an diesem Beleg und erscheint im Bericht für
den Steuerberater direkt unter der Frage, die es beantwortet — statt im Gesprächsverlauf
zu versanden. Jeder Zugriff steht als eigene Zeile im Verlauf, damit erkennbar bleibt,
worauf eine Antwort beruht.

Stößt das Modell an eine Grenze des Werkzeugs — ein Werkzeug, das es gebraucht hätte;
eine Angabe, die es nicht sehen kann —, schreibt es das mitsamt dem Anlass nach
`berichte/verbesserungen.md`. Die Liste entsteht also dort, wo die Reibung auftritt,
und nicht aus der Erinnerung.

Entwürfe landen in `berichte/entwuerfe/` und stehen auf der Seite **Beratung** unter
„Entwürfe“ zum Lesen und Kopieren bereit. Ein langer Text entsteht in Teilen: mit
`anhaengen` wächst ein Entwurf weiter, statt sich selbst zu ersetzen, und
`entwurf_lesen` zeigt, was schon darin steht. Versendet wird nichts, und ins ZIP für den
Steuerberater gehen sie nicht mit.

**Bildschirmfotos** lassen sich mit `Strg`+`V` direkt in das Eingabefeld einfügen, per
Drag-and-drop hineinziehen oder über „Bild anhängen“ auswählen — höchstens fünf je
Nachricht, PNG, JPEG, GIF und WebP. Große Bilder werden vor dem Senden auf 1568 Pixel
an der langen Kante verkleinert; ungekürzt kosten sie ein Vielfaches, ohne mehr zu
zeigen. Die Bilder liegen als Datei in `.zustand/gespraechsbilder/`, im Verlauf steht
nur ein Verweis darauf — sonst wäre die Verlaufsdatei nach drei Bildschirmfotos
unlesbar und um ein Vielfaches größer als das Gespräch selbst.

Ein vollständiger Steuerbeleg gehört trotzdem auf die Übersichtsseite hochgeladen, nicht
ins Gespräch: nur dort wird er analysiert, benannt und einsortiert.

Der Verlauf liegt in `.zustand/gespraech.json` und wird beim nächsten Start
fortgesetzt. „Gespräch verwerfen“ löscht ihn; eingetragene Notizen bleiben.

**Die Websuche ist die einzige Stelle, an der etwas den Rechner verlässt.** Sie dient
Rechtsfragen jenseits der hinterlegten Werte — Rechtsprechung, Änderungen kommender
Jahre. Der Systemprompt verbietet ausdrücklich, Namen, Anschriften, Steuernummern,
Arbeitgeber oder Beträge aus den Belegen in eine Suchanfrage zu schreiben. Was gesucht
wurde, steht als graue Zeile im Verlauf.

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
| `steuer stammdaten [--bearbeiten] [--aus MAPPE]` | jahresübergreifende Werte wie die Gebäude-AfA pflegen und fortschreiben |
| `steuer hinzufuegen <Pfade> [--herkunft] [--jahr]` | Dateien oder Ordner aufnehmen; Herkunft und Steuerjahr des Stapels gleich mitgeben |
| `steuer analyse [--alle] [--nachtragen] [--hoechstens N]` | Dokumente prüfen; `--nachtragen` holt nur nach, was mit älterem Stand geprüft wurde |
| `steuer liste` | alle Dokumente nach Anlagen sortiert |
| `steuer dateien` | Größe und Seitenzahl aller Dateien, findet Ausreißer |
| `steuer ausgliedern` | Dokumente nach Herkunft, Kategorie oder Steuerjahr in eine andere Mappe verschieben |
| `steuer jahre` | Verteilung des Bestands auf die Veranlagungsjahre |
| `steuer jahr-aus-dateiname` | das Steuerjahr aus Dateiname oder Belegdatum ableiten |
| `steuer jahr-setzen --auf 2024` | ein Steuerjahr für viele Dokumente auf einmal eintragen |
| `steuer zusammenfuehren <Mappe>` | eine andere Arbeitsmappe aufnehmen, samt Analysen |
| `steuer status` | Kennzahlen auf einen Blick |
| `steuer pruefen` | Lücken, Chancen und Warnungen |
| `steuer trennen <Kennung>` | erkannten Sammelscan seitengenau zerlegen |
| `steuer ordnen [--paket] [--gesamtauswertung]` | Ablage, Berichte, ZIP |
| `steuer euer [--kategorie selbstaendig]` | Aufstellung der Betriebseinnahmen und -ausgaben für die Anlage EÜR |
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

## Was über Jahre hinweg gilt

Manche Zahlen stehen in keinem einzelnen Beleg. Die Gebäude-AfA einer vermieteten
Immobilie etwa wird aus den Vorjahren fortgeschrieben und steht **nicht im
Steuerbescheid** — nur in der eingereichten Anlage V. Wer sie nicht festhält, sucht
sie jedes Jahr neu oder lässt den größten Posten der Anlage V stillschweigend
ausfallen.

```bash
steuer stammdaten --bearbeiten      # Werte einzeln erfassen, mit Fundstelle
steuer stammdaten                   # zeigen, was hinterlegt ist
```

Jeder Wert trägt seine Fundstelle und das Datum der Bestätigung. Nichts wird
automatisch übernommen.

Beim Wechsel ins nächste Jahr:

```bash
cd ~/steuer-2025
steuer stammdaten --aus ~/steuer-2024
```

Fortgeschrieben wird, was gleich bleibt. Werte mit endlicher Laufzeit — Abschreibungen
beweglicher Güter, Verlustvorträge — wandern mit, werden aber ausdrücklich zur Prüfung
gestellt, statt stillschweigend weiterzulaufen.

Was hier bestätigt ist, gilt als bekannt: Die Lückenanalyse meldet es nicht mehr als
fehlend, und der Analyseauftrag nennt es dem Modell als gesichert.

In der Weboberfläche gibt es dafür den Menüpunkt **Stammdaten**.

---

## Woher ein Stapel stammt

Die wirksamste Sortierung kostet nichts: Sie kommt von Ihnen. Wer beim Aufnehmen
sagt, wem ein Stapel gehört und in welches Jahr er fällt, erspart dem Werkzeug
das Raten — und sich selbst die Analysekosten für Belege, die gar nicht zu
diesem Jahr gehören.

```bash
steuer hinzufuegen ~/Scans/Gewerbe2025/ --herkunft gewerbe --jahr 2025
steuer hinzufuegen ~/Scans/Privat2024/  --herkunft privat  --jahr 2024
```

Die Angabe wirkt an drei Stellen: Sie steht im Analyseauftrag und hat dort
Vorrang vor dem Eindruck des Modells; Dokumente eines fremden Jahres werden
übersprungen und kosten nichts; und `steuer ausgliedern --herkunft gewerbe`
trennt sie später in einem Zug heraus.

In der Weboberfläche stehen dieselben beiden Felder direkt unter dem
Ablagebereich und gelten für den nächsten Stapel.

---

## Ein Bestand, mehrere Jahre

Ein Dokument muss die Mappe nicht wechseln, wenn es in ein anderes Jahr gehört — es
gehört einfach zu einem anderen Jahr. Die Auswertung schaut immer nur auf das
Veranlagungsjahr der Mappe:

```bash
steuer jahre        # wie sich der Bestand verteilt
```

Was in ein anderes Jahr fällt, bleibt im Bestand, geht aber in keine Kennzahl und in
keinen Bericht dieses Jahres ein. Was **kein** erkennbares Jahr hat, bleibt ebenfalls
sichtbar und ebenfalls außerhalb der Summen — ein geratenes Jahr kann den Abzug ganz
kosten, deshalb wird hier nicht geraten.

Das Jahr eines einzelnen Belegs korrigieren Sie in der Weboberfläche auf seiner Seite;
Ihre Angabe hat Vorrang vor dem, was die Analyse gelesen hat.

Und falls ein Bestand versehentlich zerteilt wurde, führt der Gegenbefehl ihn wieder
zusammen, ohne dass Analysen verlorengehen:

```bash
steuer zusammenfuehren ~/steuer-sonstige --probelauf
steuer zusammenfuehren ~/steuer-sonstige
```

---

## Mehrere Mappen sauber trennen

Geschäftsbelege und private Steuerunterlagen gehören nicht in dieselbe Mappe: Die
Buchhaltung eines Gewerbes mündet in eine Einnahmen-Überschuss-Rechnung, nicht in
Einzelbelege für die Steuererklärung. Vermischt verfälschen sie alle Kennzahlen.

`steuer ausgliedern` verschiebt bereits analysierte Dokumente samt ihrer Analyse in
eine andere Arbeitsmappe — eine erneute Prüfung ist nicht nötig:

```bash
# erst ansehen, was passieren würde
steuer ausgliedern --kategorie selbstaendig --probelauf

# dann ausführen
steuer ausgliedern --kategorie selbstaendig --nach ~/gewerbe-2024

# alles, was in ein anderes Steuerjahr gehört
steuer ausgliedern --fremdes-jahr --nach ~/steuer-sonstige
```

Die Zielmappe wird bei Bedarf angelegt. `--kategorie` ist mehrfach angebbar, die
verfügbaren Kennungen listet der Befehl ohne Argumente auf.

---

## Aufstellung für die Einnahmen-Überschuss-Rechnung

Liegen die Geschäftsbelege in einer eigenen Mappe, fasst `steuer euer` sie zu einer
Aufstellung nach den Posten der Anlage EÜR zusammen — als Markdown zum Lesen und als
CSV, das sich in Excel oder LibreOffice öffnen lässt:

```bash
cd ~/gewerbe-2024
steuer euer --name "Atelier Musterfrau"
```

Beides landet in `berichte/`. Zwei Dinge sind dabei wichtig:

- **Das ist keine EÜR.** Die Aufstellung ist Zuarbeit; die Anlage EÜR erstellt der
  Steuerberater daraus. Die Zuordnung zu den Posten ist ein Vorschlag.
- **Was unklar ist, wird nicht geraten.** Belege, bei denen sich Einnahme und Ausgabe
  nicht sicher unterscheiden lassen, und Belege ohne erkennbaren Betrag stehen separat
  unter „Offene Punkte“ und gehen **nicht** in die Summen ein. Eine zu schöne Summe
  wäre schlimmer als eine unvollständige.

Bei einem Verlustjahr ist die Aufstellung besonders nützlich: Der Verlust lässt sich
mit anderen Einkünften verrechnen, bei Zusammenveranlagung auch mit denen des
Ehepartners.

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

Pro Dokument fällt ein Modellaufruf an, dazu je ein Aufruf für die abschließende
Gesamtauswertung und für eine Rechtsrecherche.

**In der Weboberfläche wählen Sie das Modell vor jedem Lauf selbst** — je ein
Auswahlfeld über den beiden Knöpfen, mit kurzer Erläuterung zur getroffenen Wahl.
Die Auswahl wird in der Arbeitsmappe gemerkt und beim nächsten Start wieder angezeigt.

| Arbeitsschritt | Zur Wahl | Voreinstellung | Umgebungsvariable |
| --- | --- | --- | --- |
| Analyse jedes einzelnen Dokuments | Sonnet 5, Opus 5 | `claude-opus-5` | `STEUER_MODELL_DOKUMENT` |
| Abschließende Gesamtauswertung | Opus 5, Fable 5 | `claude-fable-5` | `STEUER_MODELL_STRATEGIE` |
| Rechtsstandsrecherche | — | `claude-opus-5` | `STEUER_MODELL_RECHT` |
| Beratungsgespräch | Opus 5, Fable 5 | `claude-opus-5` | `STEUER_MODELL_BERATUNG` |

An der Kommandozeile geht dasselbe über Optionen:

```bash
steuer analyse --modell claude-sonnet-5
steuer ordnen --gesamtauswertung --modell-strategie claude-opus-5
```

Die Voreinstellung je Stufe lässt sich zusätzlich über die Umgebungsvariable setzen:

```bash
STEUER_MODELL_DOKUMENT=claude-sonnet-5 steuer analyse
```

**Zu den Kosten:** Die Dokumentanalyse ist der mit Abstand größte Posten, weil sie
einmal je Beleg anfällt. Opus liefert dort die sorgfältigste Einordnung, ist aber
deutlich teurer als Sonnet. Wer viele Belege hat und Kosten sparen will, stellt
`STEUER_MODELL_DOKUMENT` auf `claude-sonnet-5` und behält Opus nur für die Fälle,
die das Werkzeug als unsicher markiert (`steuer analyse --dokument <Kennung>
--modell claude-opus-5`).

**Zum Beratungsgespräch:** Jede Frage kostet einen Modellaufruf, plus einen weiteren
je Werkzeugrunde (höchstens acht). Der Bestand der Mappe geht dabei jedes Mal mit,
wird aber zwischengespeichert und ist deshalb nur beim ersten Aufruf voll zu bezahlen.
Teuer wird das Ansehen eines Originalscans (`beleg_ansehen`) — es entspricht einer
weiteren Dokumentanalyse. Das Modell ist angehalten, erst die gespeicherte Analyse zu
lesen und den Scan nur zu holen, wenn diese die Frage nicht beantwortet.

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
| `steuer/berater.py` | Beratungsgespräch: Verlauf, Werkzeuge, Zugriff auf die Mappe |
| `steuer/naming.py`, `organize.py` | Benennung und Ablage |
| `steuer/report.py` | HTML, Markdown, CSV |
| `steuer/euer.py` | Aufstellung der Betriebseinnahmen und -ausgaben |
| `steuer/stammdaten.py` | jahresübergreifende, bestätigte Werte |
| `steuer/lawupdate.py` | Rechtsstandsrecherche und Entwurfsverwaltung |
| `steuer/web/` | lokale Weboberfläche |

---

## Lizenz

MIT, siehe `LICENSE`.
