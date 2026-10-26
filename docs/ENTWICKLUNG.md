# Tarifwacht – Entwicklerdokumentation

Stand: 2026-10-26 (Projektstart). Vor größeren Arbeiten lesen.

## 1. Ziel und Umfang

Tarifwacht zeigt laufend und rückwirkend, was der eigene Strombezug mit verschiedenen Tarifen gekostet hätte (Festpreis, dynamisch, später dynamisch mit zeitvariablem Netzentgelt nach Modul 3), damit Nutzer fundiert entscheiden können, ob sich ein Wechsel lohnt. Sie ersetzt Eigenbau-Lösungen aus Template-Sensoren und Utility Metern.

Abgrenzung (geprüft 2026-10-24, nachgeprüft 2026-10-26):

| Projekt | Stand | Warum keine Lösung |
|---|---|---|
| [tariff_compare](https://github.com/fischit87/tariff_compare) (fischit87) | v0.1.5 (26.06.2026), 730 Zeilen, keine Tests, **keine Lizenz** | Bewertet jedes Zählerdelta mit dem Preis im Moment der Zustandsänderung statt mit dem Preis seiner Viertelstunde; nach einem Neustart wird die ganze Ausfallzeit zum dann aktuellen Preis gebucht. Eigene Tag/Monat/Jahr-Zähler statt Langzeitstatistik, daher nicht rückwirkend; Grundpreis am Monatsersten voll. Dateien im Repo-Wurzelverzeichnis, keine `hacs.json`. Speichert nach jeder Zustandsänderung (nicht nur beim Entladen, wie zuerst angenommen). |
| [ha-netzentgelt-rechner](https://github.com/principat/ha-netzentgelt-rechner) (principat) | v1.2.0 (13.10.2026), Tests, HACS | Andere Frage: Wirtschaftlichkeitsrechnung PV + Speicher auf Knopfdruck, braucht ≥ 200 Tage Statistik, kein laufender Alltagsvergleich |
| [energie-tarifvergleich](https://github.com/McCryptoX/energie-tarifvergleich) (McCryptoX) | „feature-complete“ | Keine HACS-Installation, keine Feature-Wünsche, eigene SQLite-DB |

Entscheidung 2026-10-26: eigene Integration, kein Umbau von tariff_compare (wäre eine Neufassung). Im README auf tariff_compare als Ideengeber verweisen; **keinen Code übernehmen** (keine Lizenz).

Fahrplan:

1. **MVP:** ein Bezugszähler, zwei Tarife (Festpreis, dynamisch mit Gesamtpreis-Sensor), Kostensensoren, Differenz. Parallel zum Eigenbau laufen lassen und vergleichen.
2. Beliebig viele Tarife (Untereinträge), Grundpreise, Durchschnittspreise, Service mit Antwortdaten für frei wählbare Zeiträume.
3. Rückwirkende Berechnung: Verbrauch aus der Recorder-Statistik, historische Preise aus eigener Quelle (SMARD.de?).
4. Optional: dynamisch mit Modul-3-Netzentgelt (Zeitfenster manuell eingetragen).
5. Veröffentlichung: README, Release, Vorstellung im simon42-Thread „Kostenvergleich von dynamischem und normalem Stromtarif“.

## 2. Buchungskern (aus der Einspeisewacht)

`timeslots.py`, `prices.py`, `meter.py` und `ledger.py` stammen aus der Einspeisewacht (Commit `e4fd5fc`); `ledger.py` ohne deren Einspeise-Bewertung. Prinzip: Jedes Zählerdelta wird zeitlinear auf die berührten Viertelstunden verteilt, jedes Teilstück sofort mit dem Preis seiner Viertelstunde bewertet (`Valuation`); fehlt ein Preis, wartet das Teilstück bis zu 24 h. Intern UTC, Umstellungstage haben 92 bzw. 100 Viertelstunden.

Seitdem unabhängig weiterentwickelt; die Tarifwacht braucht die Einspeisewacht nicht. Bei Fehlerkorrekturen am Kern prüfen, ob die Schwester denselben Fehler hat. Eine gemeinsame Bibliothek erst, wenn sich der Kern in beiden Projekten als stabil erwiesen hat (eine Abhängigkeit mehr für die Nutzer).

## 3. Datenquellen – verifizierte Eigenheiten (geprüft 2026-10-26)

### Preis: EPEX Spot (mampfes), Quelle SMARD.de

- `sensor.epex_spot_data_market_price` (Börsenpreis, netto) und `sensor.epex_spot_data_total_price` (Gesamtpreis) haben **dasselbe Format**: Zustand €/kWh der laufenden Viertelstunde, `state_class: measurement`; Attribut `data` als Liste `{start_time, end_time, price_per_kwh}` mit ISO-Zeitstempeln (Offset Europe/Berlin), Zeitumstellung als Eintrag `02:45+02:00 → 02:00+01:00`. `parse_interval_prices` liest beide.
- Gesamtpreis = (Börsenpreis + Aufschlag absolut) × (1 + Steuer), auf 6 Nachkommastellen gerundet (nachgeprüft an mehreren Viertelstunden, auch bei Börsenpreis 0).
- Die Tarifwacht übernimmt Preise unverändert und akzeptiert deshalb nur die Einheit €/kWh (`PRICE_UNITS`); ein Sensor mit anderer Einheit wird abgelehnt (Einrichtung) bzw. ignoriert (Laufzeit, in der Diagnose sichtbar).
- Aufschlag und Steuersatz stehen in der Konfiguration der EPEX-Spot-Integration. Ob der Aufschlag alle Preisbestandteile abdeckt, liegt beim Nutzer (siehe Abschnitt 5).
- Weitere Eigenheiten (Zustandswechsel 0,1–0,4 s nach der Grenze; Recorder speichert `data` nicht; Langzeitstatistik nur Stundenmittel): siehe Einspeisewacht `docs/ENTWICKLUNG.md`, Abschnitt 3.

### Bezugszähler

- Fronius Smart Meter TS 65A-3 (Plattform `fronius`): Wh, `total_increasing`, ganze Wh, neuer Zustand nur bei Wertänderung.
- Homematic IP HmIP-ESI (Plattform `homematicip_cloud`, liest den Zähler des Netzbetreibers optisch aus): kWh, `total_increasing`, vier Nachkommastellen. Läuft über die Homematic-Cloud: Ausfälle und verzögerte Werte möglich – das Verteilen auf Viertelstunden muss das abfangen.
- Ein Bezugszähler erreicht höchstens die Leistung des Hausanschlusses (Plausibilitätsgrenze in `MeterTracker`, z. B. 3 × 35 A ≈ 24 kW).

## 4. Typischer Eigenbau und seine Schwächen

Häufige Lösung: je Tarif ein Trigger-Template-Sensor, der bei jeder Zähleränderung `Kosten += (neu − alt) × Preis` rechnet, dazu Utility Meter für Monatswerte. Schwächen, die Tarifwacht vermeiden muss:

- **Preis im Moment der Änderung:** Ein Delta, das kurz nach einer Viertelstundengrenze ankommt, gehört größtenteils zur vorigen Viertelstunde, wird aber mit dem neuen Preis bewertet.
- **Ausfälle gehen verloren:** War der Zähler `unavailable` (oder HA neu gestartet), ist der alte Wert keine Zahl; das Delta über die Lücke wird nie gebucht. Der Eigenbau zählt dann zu wenig.
- **Preis fehlt = gratis:** `float(0)` als Rückfall bewertet Verbrauch bei nicht verfügbarem Preissensor mit 0 €.
- **Keine Grundpreise.**

Für den Vergleich im MVP heißt das: Tarifwacht sollte etwas **mehr** Verbrauch und damit Kosten zeigen als der Eigenbau, wenn es Lücken gab. Abweichungen nicht „wegkorrigieren“, sondern erklären.

## 5. Entscheidungen

- Liest vorhandene Entitäten (Bezugszähler, Preissensoren), keine Cloud, keine `requirements`. Erscheint als Integration (`integration_type: service`), wie die Einspeisewacht.
- Nur UI-Config-Flow, kein YAML. Tarife als Untereinträge (ab Stufe 2).
- **Grundpreise optional** je Tarif (€/Monat, leer = 0). Jeder Tag erhält €/Monat ÷ Tage des Monats, gleichmäßig verteilt auf seine 92/96/100 Viertelstunden; ein Monat ergibt so genau den Monatspreis (Entscheidung 2026-10-26; anbieterabhängige Abrechnung, z. B. Jahrespreis ÷ 365, kann später als Option folgen). Gebucht ab der ersten Viertelstunde nach der Einrichtung; Zeiten, in denen HA aus war, werden nachgebucht (der Grundpreis fällt trotzdem an).
- **Kostensensoren** mit `device_class: monetary` haben `state_class: total` – Home Assistant erlaubt für Geldbeträge nichts anderes (die Übergabe nannte `total_increasing`).
- **Fehlt ein dynamischer Preis**, wartet die Menge bis zu 24 h; danach wird sie gezählt (`energy_without_price`, Diagnose), aber **nie mit 0 € bewertet**.
- **Plausibilitätsgrenze** des Zählers: 100 kW (`MAX_GRID_POWER_KW`, mehr als jeder Hausanschluss); kein Einrichtungsfeld.
- MVP-Sensoren: Strombezug (kWh), je Tarif Verbrauchskosten und Kosten gesamt, Mehrkosten dynamisch (dynamisch − Festpreis, positiv = dynamisch teurer). Alles laufende Summen seit der Einrichtung.
- Zeiträume (Tag/Monat/Jahr) über die Langzeitstatistik, nicht über eigene Sensoren.
- Stand verzögert speichern (höchstens alle 60 s) und beim Entladen/Beenden, nicht bei jeder Zähleränderung.
- README-Hinweise: Der Vergleich unterstellt gleiches Verbrauchsverhalten (mit dynamischem Tarif verschieben Nutzer oft Verbrauch); alle Preisbestandteile auf beiden Seiten gleich erfassen.

## 6. Arbeitsweise

- GitHub: Organisation `tarifwacht` (angelegt 2026-10-26), Repo `integration`. Wie bei der Einspeisewacht: Standard-Branch `main`, Ruleset „main schützen“ (nur grüne CI `test`, `hassfest`, `compat`; kein Löschen, kein Force-Push) und „Release-Tags schützen“ (`v*` unveränderlich). Brand-Bilder fehlen noch: der CI-Job `hacs` ignoriert `brands`.
- Releases, auch Betas, als **reguläre** GitHub-Releases (nicht „Pre-release“) – sonst sucht HACS die ZIP unter dem Commit und scheitert (Erfahrung Einspeisewacht 0.1.0b2).

## 7. Offene Fragen

- **Preisbestandteile:** Wie erklärt man Nutzern am besten, welche Bestandteile im Aufschlag eines dynamischen Tarifs stecken müssen (Netzentgelt, Konzessionsabgabe, Umlagen, Stromsteuer, Anbieteraufschlag)? Stufe 2: Börsenpreis + einzeln eingetragene Bestandteile.
- **Grundpreis:** Wie rechnen Anbieter tagesgenau ab (Monatspreis ÷ Tage des Monats oder Jahrespreis ÷ 365)?
- **Historische Preise** für die rückwirkende Berechnung: SMARD.de (Nutzungsbedingungen, CC BY 4.0, inoffizielle Schnittstelle – Erfahrung der Einspeisewacht nutzen).
- Brand-Bilder; `categories` im Manifest.
