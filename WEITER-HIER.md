# Hier geht es weiter

Stand: 18. August 2026. Diese Datei ist der Merkzettel fuer den Wiedereinstieg.
Sie wird beim naechsten Arbeitsschritt aktualisiert.

---

## Der allererste Schritt

Der API-Schluessel steht noch aus. Er war zweimal in einem Screenshot sichtbar
und muss ersetzt werden. Reihenfolge einhalten, sonst steht zwischendurch kein
funktionierender Schluessel zur Verfuegung:

1. Auf <https://console.anthropic.com/settings/keys> mit **Create Key** einen
   neuen Schluessel anlegen und kopieren. Noch nichts loeschen.
2. Diese Zeile mit dem **neuen** Schluessel ausfuehren — nur
   `NEUER_SCHLUESSEL` ersetzen, sonst nichts, und keinen Screenshot davon:

   ```bash
   sed -i '/ANTHROPIC_API_KEY/d' ~/.bashrc && echo 'export ANTHROPIC_API_KEY=NEUER_SCHLUESSEL' >> ~/.bashrc && source ~/.bashrc
   ```

3. Erst jetzt in der Anthropic-Konsole den **alten** Schluessel loeschen
   (drei Punkte → Delete). Es ist der, der mit `tR_Mfo1vw` weitergeht.
4. Empfehlung: unter **Settings → Limits** ein monatliches Ausgabenlimit
   setzen, etwa 20 bis 50 Euro.

Pruefen, ohne den Schluessel sichtbar zu machen:

```bash
echo "Schluessel gesetzt: ${ANTHROPIC_API_KEY:+ja}"
```

---

## Danach: der offene Punkt

In der Gewerbemappe `~/gewerbe-2024` liegen Rechnungen aus **2025**. In den
Dateinamen steht durchgehend `2025-10-...`. Vermutlich sind dort Belege aus
zwei Jahren gemischt.

Das ist wahrscheinlich die Erklaerung dafuer, dass die erste EUeR-Aufstellung
**58.392,21 EUR Betriebseinnahmen** und einen **Gewinn von 44.239,77 EUR**
auswies, obwohl 2024 ein Verlustjahr war.

**Vor** der grossen Analyse pruefen, ob sich die 2025er-Belege aussortieren
lassen. Das spart einen erheblichen Teil der Kosten, weil Belege, die gar nicht
ins Jahr 2024 gehoeren, dann nicht bezahlt werden muessen:

```bash
cd ~/gewerbe-2024
steuer ausgliedern
```

Ohne weitere Angaben zeigt der Befehl nur die Verteilung nach Kategorie und
Steuerjahr an, ohne etwas zu veraendern.

---

## Dann: die Belege neu pruefen

Die Belege in `~/gewerbe-2024` wurden geprueft, bevor es die Felder
"Einnahme oder Ausgabe" gab. Deshalb beruht die bisherige Aufstellung allein
auf geratenen Stichworten und ist unbrauchbar. Erst ein Probelauf ueber
20 Dokumente, um die Kosten abzuschaetzen:

```bash
steuer analyse --nachtragen --hoechstens 20 --modell claude-sonnet-5
```

Danach in der Anthropic-Konsole nachsehen, was die 20 gekostet haben, und auf
die Gesamtzahl hochrechnen. Wenn das passt, der volle Lauf:

```bash
steuer analyse --nachtragen --modell claude-sonnet-5
```

`--nachtragen` nimmt sich nur die Dokumente vor, denen die Angabe fehlt. Ein
Abbruch mit `Strg` + `C` ist unproblematisch: Nach jedem Dokument wird
gespeichert, dieselbe Zeile setzt fort, nichts wird doppelt bezahlt.

Zum Schluss die Aufstellung neu erzeugen:

```bash
steuer euer --name "So Lems"
```

**Pruefen:** Kommt jetzt ein Verlust heraus? Wenn nicht, liegt es nicht mehr an
der fehlenden Angabe, und wir suchen gezielt weiter.

---

## Danach offen: die private Mappe

In `~/first-repo-claude-tax-return-document-tool-jesqdh/steuer-2024` liegen
268 Dokumente, davon **142 als "nicht steuerrelevant"** und **48 als
"Klaerung erforderlich"** — zusammen 190. Falls darunter falsch eingeordnete
Belege sind, steckt darin bares Geld. Noch nicht angesehen.

Ebenfalls offen: Schritt 2 der Weboberflaeche, die Gesamtauswertung
(`steuer ordnen --gesamtauswertung`).

---

## Bedienhinweise, die sich als wichtig erwiesen haben

- **Immer nur eine Zeile einfuegen.** Beim Einfuegen mehrerer Zeilen
  verschluckt die Konsole den Zeilenumbruch, und zwei Befehle kleben zusammen
  (`claude-sonnet-5cd ~/first-repo...`). Mehrere Schritte deshalb mit `&&`
  in einer einzigen Zeile verbinden.
- **In Platzhaltern nur den Platzhalter ersetzen.** Bei
  `steuer euer --name "So Lems"` bleibt `euer` stehen, es ist der Befehl.
- Das Repository liegt unter
  `~/first-repo-claude-tax-return-document-tool-jesqdh`, die private
  Arbeitsmappe darin unter `steuer-2024`.
- Updates holen, alles in einer Zeile:

  ```bash
  cd ~/first-repo-claude-tax-return-document-tool-jesqdh && git pull origin claude/tax-return-document-tool-jesqdh && pip install -e . && cd ~/gewerbe-2024
  ```

- Vor Arbeiten an den Mappen den Webserver mit `Strg` + `C` beenden. Er haelt
  den Bestand im Speicher und wuerde Aenderungen sonst ueberschreiben.
