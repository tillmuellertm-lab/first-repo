"use strict";

// Kleine Oberflaechenlogik: Datei-Upload per Drag and Drop, Anstossen der
// Hintergrundlaeufe und Anzeige ihres Fortschritts.

const fortschritt = document.getElementById("fortschritt");
const fuellung = document.getElementById("fuellung");
const fortschrittText = document.getElementById("fortschritt-text");
const protokoll = document.getElementById("protokoll");

let abfrage = null;

function zeigeFortschritt(sichtbar) {
  if (fortschritt) fortschritt.hidden = !sichtbar;
}

function aktualisiere(zustand) {
  if (!fortschritt) return;
  const anteil = zustand.gesamt ? Math.round((zustand.erledigt / zustand.gesamt) * 100) : 0;
  fuellung.style.width = `${anteil}%`;
  if (zustand.fehler) {
    fortschrittText.textContent = `Abgebrochen: ${zustand.fehler}`;
  } else if (zustand.laeuft) {
    const wobei = zustand.aktuell ? ` · ${zustand.aktuell}` : "";
    fortschrittText.textContent = `${zustand.erledigt} von ${zustand.gesamt}${wobei}`;
  } else {
    fortschrittText.textContent = `Fertig um ${zustand.fertig_um || "jetzt"}. Seite wird neu geladen ...`;
  }
  protokoll.textContent = (zustand.meldungen || []).join("\n");
  protokoll.scrollTop = protokoll.scrollHeight;
}

function beobachte() {
  if (abfrage) clearInterval(abfrage);
  abfrage = setInterval(async () => {
    try {
      const antwort = await fetch("/api/auftrag");
      const zustand = await antwort.json();
      aktualisiere(zustand);
      if (!zustand.laeuft) {
        clearInterval(abfrage);
        abfrage = null;
        setTimeout(() => window.location.reload(), 1200);
      }
    } catch (fehler) {
      fortschrittText.textContent = `Verbindung zum Assistenten verloren: ${fehler}`;
      clearInterval(abfrage);
      abfrage = null;
    }
  }, 1000);
}

async function starte(pfad, nutzlast) {
  zeigeFortschritt(true);
  protokoll.textContent = "";
  fortschrittText.textContent = "Wird gestartet ...";
  const antwort = await fetch(pfad, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(nutzlast || {}),
  });
  const daten = await antwort.json();
  if (!antwort.ok) {
    fortschrittText.textContent = daten.fehler || "Der Vorgang konnte nicht gestartet werden.";
    return;
  }
  aktualisiere(daten);
  beobachte();
}

// --- Hochladen ------------------------------------------------------------

async function lade(dateien) {
  if (!dateien || !dateien.length) return;
  const formular = new FormData();
  for (const datei of dateien) formular.append("dateien", datei);

  zeigeFortschritt(true);
  fortschrittText.textContent = `${dateien.length} Dateien werden uebertragen ...`;
  protokoll.textContent = "";
  fuellung.style.width = "35%";

  try {
    const antwort = await fetch("/api/hochladen", { method: "POST", body: formular });
    const daten = await antwort.json();
    fuellung.style.width = "100%";
    const zeilen = [];
    (daten.aufgenommen || []).forEach((n) => zeilen.push(`aufgenommen: ${n}`));
    (daten.dubletten || []).forEach((n) => zeilen.push(`Dublette, uebersprungen: ${n}`));
    (daten.abgelehnt || []).forEach((e) => zeilen.push(`abgelehnt: ${e.datei} (${e.grund})`));
    protokoll.textContent = zeilen.join("\n");
    fortschrittText.textContent = `${(daten.aufgenommen || []).length} neu aufgenommen. Seite wird neu geladen ...`;
    setTimeout(() => window.location.reload(), 1400);
  } catch (fehler) {
    fortschrittText.textContent = `Upload fehlgeschlagen: ${fehler}`;
  }
}

const ablage = document.getElementById("ablage");
if (ablage) {
  ["dragenter", "dragover"].forEach((ereignis) =>
    ablage.addEventListener(ereignis, (e) => {
      e.preventDefault();
      ablage.classList.add("aktiv");
    })
  );
  ["dragleave", "drop"].forEach((ereignis) =>
    ablage.addEventListener(ereignis, (e) => {
      e.preventDefault();
      ablage.classList.remove("aktiv");
    })
  );
  ablage.addEventListener("drop", (e) => lade(e.dataTransfer.files));
}

const dateiwahl = document.getElementById("dateiwahl");
if (dateiwahl) dateiwahl.addEventListener("change", () => lade(dateiwahl.files));

// --- Aktionen -------------------------------------------------------------

document.addEventListener("click", async (ereignis) => {
  const knopf = ereignis.target.closest("[data-aktion]");
  if (!knopf) return;
  const aktion = knopf.dataset.aktion;

  if (aktion === "analyse") {
    await starte("/api/analyse", {});
  } else if (aktion === "analyse-alle") {
    if (!confirm("Alle Dokumente noch einmal analysieren? Das verursacht erneut API-Kosten.")) return;
    await starte("/api/analyse", { alle: true });
  } else if (aktion === "neu-analysieren") {
    await starte("/api/analyse", { dokument: knopf.dataset.dokument });
  } else if (aktion === "ordnen") {
    await starte("/api/ordnen", {
      gesamtauswertung: document.getElementById("mit-gesamtauswertung")?.checked || false,
      paket: document.getElementById("mit-paket")?.checked || false,
    });
  } else if (aktion === "eingang-einlesen") {
    const antwort = await fetch("/api/eingang-einlesen", { method: "POST" });
    const daten = await antwort.json();
    alert(
      daten.neu.length
        ? `${daten.neu.length} neue Dateien aufgenommen.`
        : "Keine neuen Dateien im Eingangsordner."
    );
    window.location.reload();
  } else if (aktion === "loeschen") {
    if (!confirm("Dieses Dokument aus der Mappe entfernen? Die Originaldatei wird geloescht.")) return;
    await fetch(`/api/dokument/${knopf.dataset.dokument}/loeschen`, { method: "POST" });
    window.location.href = "/";
  }
});
