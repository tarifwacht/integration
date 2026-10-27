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
3. Rückwirkende Berechnung: Verbrauch aus der Recorder-Statistik, historische Preise von SMARD.de – umgesetzt als Rückblick der Aktion „Tarife vergleichen“ (2026-10-26). Offen: Vergangenheit in die Langzeitstatistik der Sensoren schreiben (wie „Statistik nachtragen“ der Einspeisewacht).
4. Optional: dynamisch mit Modul-3-Netzentgelt (Zeitfenster manuell eingetragen).
5. Veröffentlichung: README, Release, Vorstellung im simon42-Thread „Kostenvergleich von dynamischem und normalem Stromtarif“.

## 2. Buchungskern (aus der Einspeisewacht)

`timeslots.py`, `prices.py` und `meter.py` stammen aus der Einspeisewacht (Commit `e4fd5fc`). Prinzip: Jedes Zählerdelta wird zeitlinear auf die berührten Viertelstunden verteilt, jedes Teilstück mit dem Preis seiner Viertelstunde bewertet; fehlt ein Preis, wartet das Teilstück bis 24 h nach dem Ende seiner Viertelstunde. Intern UTC, Umstellungstage haben 92 bzw. 100 Viertelstunden.

**Verlauf statt laufender Summen (ab Stufe 2, Entscheidung 2026-10-26):** Die Engine speichert den Verbrauch je Viertelstunde (`history.py`, eine Liste mit 96 Werten je UTC-Tag, ca. 350 KB pro Jahr) und jeden Preis jedes Preissensors für den ganzen Abrechnungszeitraum. Die Summen jedes Tarifs werden daraus abgeleitet: beim Start vollständig neu berechnet, danach laufend fortgeschrieben – nach denselben Regeln (Test `test_recompute_equals_incremental`). Folgen:

- Ein geänderter Tarif (Preis korrigiert, Grundpreis nachgetragen) und ein neu hinzugefügter Tarif gelten **für den ganzen Zeitraum** seit Beginn – Tarife sind gedachte Alternativen, keine Vertragshistorie. Preisänderungen eines Tarifs im Zeitverlauf (z. B. ab 1. Januar) brauchen später eigene Gültigkeitszeiträume.
- `ledger.py` (laufende Summen) ist damit entfallen.
- **Update von 0.1.0b1** (Speicherversion 1, nur Summen): Preise und Zähler werden übernommen, Beginn = `created_at` des Eintrags; der Verbrauch von der Einrichtung bis zur letzten von 0.1.0b1 gebuchten Ablesung wird einmalig aus dem Recorder gelesen (`state_changes_during_period`, Muster wie die Integration `statistics`, `after_dependencies: recorder`). Schlägt das fehl, versucht es der nächste Start erneut; die Live-Buchung läuft unabhängig. Das ist zugleich der erste Baustein der rückwirkenden Berechnung (Stufe 3).

Seitdem unabhängig weiterentwickelt; die Tarifwacht braucht die Einspeisewacht nicht. Bei Fehlerkorrekturen am Kern prüfen, ob die Schwester denselben Fehler hat. Eine gemeinsame Bibliothek erst, wenn sich der Kern in beiden Projekten als stabil erwiesen hat (eine Abhängigkeit mehr für die Nutzer).

## 2a. Modul 3 – zeitvariables Netzentgelt (§ 14a EnWG)

Recherchiert 2026-10-26 an Primärquellen; keine Rechts- oder Abrechnungsberatung.

- **Grundlage:** BNetzA BK8-22/010-A vom 23.11.2023 (Tenor Ziff. 3, Anlage S. 62; [Festlegung](https://www.bundesnetzagentur.de/DE/Beschlusskammern/1_GZ/BK8-GZ/2022/2022_4-Steller/BK8-22-0010/BK8-22-0010-A_Festlegung_DL_BF.html)). Bis 26.10.2026 keine Änderungsfestlegung; BNetzA erwägt Weiterentwicklung im Rahmen von AgNes, frühestens 2027.
- **Drei Stufen:** Standard (normaler Arbeitspreis des Netzentgelts), Hochlast HT (≤ 2 × Standard, mindestens 2 h täglich), Niedriglast NT (10–40 % des Standards) – Anlage Nr. 1/2. Erlösneutral gegenüber H0-Profil (Nr. 3).
- **Quartale:** in mindestens zwei Quartalen, sonst ganztägig Standard; jede Stufe kommt an jedem Tag dieser Quartale vor (Tenor 3 c). Die Quartale wechseln teils jährlich (Netze BW: 2025 Q2–Q4, 2026 Q1–Q4). Abrechnung seit 01.04.2025.
- **Umfang:** gilt für den **gesamten Netzbezug der Marktlokation** ([BNetzA-FAQ](https://www.bundesnetzagentur.de/DE/Vportal/Energie/SteuerbareVBE/Netzentgelt_table.html); Rz. 90–91) – passt zum Ein-Zähler-Ansatz, solange das Gerät nicht separat gezählt wird. Nur zusammen mit Modul 1, nicht mit Modul 2.
- **Zeitfenster:** Ortszeit Europe/Berlin ohne Rücksicht auf die Zeitumstellung (UTILTS AHB 1.1, § 8.4); am Umstellungstag bekommt die doppelte Stunde beide Male ihre Stufe. Preisblätter: Viertelstunden-Raster (Pforzheim 01:45–06:15), Fenster über Mitternacht (EAM 23:00–06:00), mehrere Fenster je Stufe; keine Unterscheidung nach Wochentag oder Feiertag gefunden. BDEW-Anwendungshilfe V1.2: Fenster ganzjährig gleich.
- **Was sich ändert:** nur der Arbeitspreis des Netzentgelts; Energie, Abgaben, Umlagen, Steuern, Grundpreis bleiben.
- **Umsetzung:** Option der Tarifart „Börsenpreis plus Aufschläge“ (das Netzentgelt-Feld ist die Standardstufe). Gespeichert unter `modul3` = `{active, nt, ht, quarters, nt_windows, ht_windows}` (ct/kWh netto, Fenster als Text „HH:MM-HH:MM, …“); auch per Preisänderung ab einem Datum (neues Preisblatt). Geprüft: Format, Viertelstunden-Raster, keine Überschneidung, je Stufe mindestens ein Fenster, mindestens ein Quartal. Nicht erzwungen (Preisblatt hat Vorrang): Preisgrenzen NT/HT, Mindestdauer HT, mindestens zwei Quartale.
- **Beispiele 2026 (netto ct/kWh), in den Tests:** Netze BW (Q1–Q4, NT 10–14 3,03, HT 17–22 11,06, sonst 7,57), Netzgesellschaft Düsseldorf (Q1+Q4, NT 04:30–05:00 3,16, HT 18–20 8,19, sonst 7,91).

## 3. Datenquellen – verifizierte Eigenheiten (geprüft 2026-10-26)

### Preis: EPEX Spot (mampfes), Quelle SMARD.de

- `sensor.epex_spot_data_market_price` (Börsenpreis, netto) und `sensor.epex_spot_data_total_price` (Gesamtpreis) haben **dasselbe Format**: Zustand €/kWh der laufenden Viertelstunde, `state_class: measurement`; Attribut `data` als Liste `{start_time, end_time, price_per_kwh}` mit ISO-Zeitstempeln (Offset Europe/Berlin), Zeitumstellung als Eintrag `02:45+02:00 → 02:00+01:00`. `parse_interval_prices` liest beide.
- Gesamtpreis = (Börsenpreis + Aufschlag absolut) × (1 + Steuer), auf 6 Nachkommastellen gerundet (nachgeprüft an mehreren Viertelstunden, auch bei Börsenpreis 0).
- Die Tarifwacht übernimmt Preise unverändert und akzeptiert deshalb nur die Einheit €/kWh (`PRICE_UNITS`); ein Sensor mit anderer Einheit wird abgelehnt (Einrichtung) bzw. ignoriert (Laufzeit, in der Diagnose sichtbar).
- Aufschlag und Steuersatz stehen in der Konfiguration der EPEX-Spot-Integration. Ob der Aufschlag alle Preisbestandteile abdeckt, liegt beim Nutzer (siehe Abschnitt 5).
- Weitere Eigenheiten (Zustandswechsel 0,1–0,4 s nach der Grenze; Recorder speichert `data` nicht; Langzeitstatistik nur Stundenmittel): siehe Einspeisewacht `docs/ENTWICKLUNG.md`, Abschnitt 3.

### Weitere Preisquellen (experimentell, Entscheidung 2026-10-26)

Recherchiert am Quellcode (feste Commit-Stände) am 2026-10-26. Ein Format wird nur an den **genauen Schlüsseln** erkannt (`parse_price_attributes`), nicht am Attributnamen – `data` nutzen EPEX Spot, Ostrom und der Tibber-Export mit verschiedenem Aufbau.

| Integration | Attribut | Eintrag | Hinweise |
|---|---|---|---|
| EPEX Spot (mampfes) | `data` | `{start_time, end_time, price_per_kwh}` | aufgezeichnetes Fixture; deckt über seine Quellen auch aWATTar, Tibber (Gesamtpreis), SMARD ab |
| Nord Pool, HACS `custom-components/nordpool` 0.0.18 | `raw_today`, `raw_tomorrow` | `{start, end, value}` (in HA `datetime`-Objekte) | Einheit `EUR/kWh` (oder `c/kWh` → abgelehnt); Wert = Börse/1000 × (1+MwSt.) + Zusatzkosten-Template, gerundet (Standard 3 Stellen); Listen nicht im Recorder; Repo ohne Lizenz – kein Code übernommen |
| ENTSO-E, HACS `JaccoR/hass-entso-e` v0.7.5 | `prices`, `prices_today`, `prices_tomorrow` (nur am Durchschnittspreis-Sensor) | `{time, price}` **ohne Ende**, `time` mit Leerzeichen | Länge aus dem häufigsten Abstand (15/60 min, UTC); Lücken werden nicht gefüllt; Standard ohne MwSt./Aufschlag = reiner Börsenpreis |

Nicht unterstützt (zu unsicher oder nicht vorhanden): HA-Core Nord Pool und Tibber (Preise nur über Aktionen), HACS `tibber_prices` (frei konfigurierbarer Export), Ostrom (`data` mit `{date, price}`, ct/kWh, Platzhalter-Einträge), Rabot (Ende und Auflösung im Code selbst als Annahme markiert), 1KOMMA5 (zwei Integrationen, gleicher Name `forecast`, anderer Aufbau), Octopus (nur bei `isTimeOfUse`, Format ungeprüft). Fixtures für Nord Pool und ENTSO-E sind **abgeleitet** aus echten API-Daten der Projekte (`tools/make_price_fixtures.py`, Herkunft in `tests/fixtures/_index.json`); sobald ein Nutzer eine Diagnose schickt (`attribute_shape`), gegen echte Attribute prüfen.

### SMARD.de (Rückblick, geprüft 2026-10-26)

- Format, Endpunkte und Eigenheiten wie in der Einspeisewacht (`docs/ENTWICKLUNG.md` dort, Abschnitt 3, Stand Commit 65857dc): Index `…/4169/DE-LU/index_quarterhour.json`, Wochendateien ab Montag 00:00 Ortszeit, €/MWh, `null` für fehlende Werte, vor dem 01.10.2025 jeder Stundenpreis viermal. Die `chart_data`-Endpunkte sind **nicht als API dokumentiert**.
- Fixtures aus der Einspeisewacht übernommen (`tests/fixtures/smard_*.json`, Herkunft in `_index.json`). Test: Am 25.10.2026 stimmen alle 100 Viertelstunden mit dem EPEX-Spot-Marktpreis überein – SMARD ergänzt deshalb nur Tarife „Börsenpreis plus Aufschläge“, nie einen Gesamtpreis-Sensor.
- **Quellen-Check:** `uv run tools/source_check.py` prüft Index und die beiden neuesten Wochen (Format, Aktualität, Viertelstundenraster, Preisspanne) mit dem echten Code; läuft montags per `.github/workflows/source-check.yml`, öffnet bei Problemen ein Issue (Label `quellen-check`), kommentiert ein offenes und schließt es, sobald alles wieder geht. Zeitgesteuerte Workflows laufen nur von `main` und schlafen nach 60 Tagen ohne Repo-Aktivität ein.
- Lizenz CC BY 4.0, Quellenangabe „Bundesnetzagentur | SMARD.de“ (README, Antwort der Aktion unter `estimate.exchange_prices`).

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
- Nur UI-Config-Flow, kein YAML.
- **Tarife als Untereinträge** (Stufe 2, Entscheidung 2026-10-26; Muster wie die Kern-Integration `bayesian`): Die Einrichtung fragt Zähler, Festpreis und Gesamtpreis-Sensor und legt daraus zwei Untereinträge an; „Tarif hinzufügen“ bietet Festpreis, dynamisch mit Gesamtpreis-Sensor und dynamisch aus Börsenpreis + Bestandteilen (Netzentgelt, Steuern/Abgaben/Umlagen, Anbieteraufschlag, je ct/kWh netto, plus MwSt. in %). Jede Änderung lädt den Eintrag neu (Update-Listener; deshalb `async_update_and_abort`, nicht `…reload…`, das ab HA 2026.12 mit Listener scheitert) und berechnet den ganzen Zeitraum neu.
- **Referenztarif** per Haken „Mein aktueller Tarif“ im Tarif; setzt man ihn, verschwindet er beim bisherigen. Jeder andere Tarif hat „Differenz zum aktuellen Tarif“ (positiv = teurer).
- **Ein Gerät je Tarif** („Haus Festpreis“): Verbrauchskosten, Kosten gesamt, Durchschnittspreis (ct/kWh, inkl. Grundpreis), ggf. Differenz. Am Zähler-Gerät: Strombezug, Günstigster Tarif (mit Rangfolge als Attribut). Unique IDs `{entry_id}_{key}_{sensor}`; die beiden Tarife aus 0.1.0b1 behalten die Schlüssel `fixed`/`dynamic`, neue Tarife nutzen ihre Subentry-ID. Beim Update von 0.1.0b1 (Eintragsversion 1 → 2) entstehen die Untereinträge, „Mehrkosten dynamisch“ wird zur Differenz des dynamischen Tarifs (Unique ID umbenannt, Entity-ID und Verlauf bleiben).
- **Grundpreis pro Monat oder pro Jahr** (Auswahl je Tarif): pro Jahr tagesgenau Jahrespreis ÷ 365 bzw. 366.
- **Grundpreise optional** je Tarif (€/Monat, leer = 0). Jeder Tag erhält €/Monat ÷ Tage des Monats, gleichmäßig verteilt auf seine 92/96/100 Viertelstunden; ein Monat ergibt so genau den Monatspreis (Entscheidung 2026-10-26; anbieterabhängige Abrechnung, z. B. Jahrespreis ÷ 365, kann später als Option folgen). Gebucht ab der ersten Viertelstunde nach der Einrichtung; Zeiten, in denen HA aus war, werden nachgebucht (der Grundpreis fällt trotzdem an).
- **Kostensensoren** mit `device_class: monetary` haben `state_class: total` – Home Assistant erlaubt für Geldbeträge nichts anderes (die Übergabe nannte `total_increasing`).
- **Fehlt ein dynamischer Preis**, wartet die Menge bis zu 24 h; danach wird sie gezählt (`energy_without_price`, Diagnose), aber **nie mit 0 € bewertet**.
- **Plausibilitätsgrenze** des Zählers: 100 kW (`MAX_GRID_POWER_KW`, mehr als jeder Hausanschluss); kein Einrichtungsfeld.
- MVP-Sensoren: Strombezug (kWh), je Tarif Verbrauchskosten und Kosten gesamt, Mehrkosten dynamisch (dynamisch − Festpreis, positiv = dynamisch teurer). Summen über den Abrechnungszeitraum seit der Einrichtung.
- **Dynamischer Preis aus Bestandteilen** (`ComposedPrice`): (Börsenpreis + Aufschläge netto) × (1 + MwSt.) – dieselbe Formel wie der Gesamtpreis von EPEX Spot. Nötig für die rückwirkende Berechnung, weil es für die Vergangenheit keinen Gesamtpreis-Sensor gibt.
- **Rückwirkend** (Reihenfolge, Entscheidung 2026-10-26): erst MVP prüfen, dann Stufe 2, dann eine Aktion mit Antwortdaten für frei wählbare Zeiträume (Verbrauch aus der Statistik, Preise von SMARD.de), danach ggf. eigene Langzeitstatistik für die Vergangenheit. **Kein** Startdatum, das die Sensoren mit einem Vergangenheitsbetrag beginnen lässt (erschiene in Monatsgrafiken als Sprung).
- **Rückblick** (Entscheidung 2026-10-26): Liegt der Beginn der Aktion „Tarife vergleichen“ vor der Einrichtung, kommt der Verbrauch davor aus der Langzeitstatistik des Zählers (`statistics_during_period`, Stundenwerte `change`, gleichmäßig auf vier Viertelstunden verteilt – Muster der Einspeisewacht), die Börsenpreise davor von SMARD.de (`FallbackPrice`: zuerst die Preise des Sensors, nur vor der Einrichtung SMARD). Viertelstunden vor der Einrichtung ohne Preis zählen sofort als „ohne Preis“ (warten nicht 24 h). Der Abruf läuft **automatisch** bei einem solchen Vergleich (kein Opt-in; im README unter Datenschutz genannt), nur wenn ein Tarif „Börsenpreis plus Aufschläge“ existiert; **ohne Zeitgrenze** nach hinten. Preise je UTC-Jahr in einem gemeinsamen Speicher `tarifwacht.smard.<jahr>` für alle Einträge, geschrieben nur nach neuen Wochen; 0,5 s Pause je Woche, Kennung `Tarifwacht/<Version>`. Die Antwort hat `estimate` (bis wann, Energie, fehlende Stunden, Quellenangabe) und `months`. „Günstigster“ ist nur ein Tarif, der jede kWh bepreisen konnte.
- Zeiträume (Tag/Monat/Jahr) über die Langzeitstatistik, nicht über eigene Sensoren.
- **Wenig Schreiblast (SD-Karten, Entscheidung 2026-10-26):**
  - Speicher in zwei Teilen (Speicherversion 3): eine kleine **Live-Datei** `tarifwacht.<entry_id>` (Zähler, gestern und heute, wenige KB) und je Kalenderjahr ein **Archiv** `tarifwacht.<entry_id>.<jahr>` mit den abgeschlossenen UTC-Tagen. Die Live-Datei wird nach jedem Viertelstunden-Tick und beim Beenden geschrieben, nicht bei jeder Zähleränderung; ein Archiv einmal am Tag, wenn ein Tag abgeschlossen ist (`archived_until`). Ein Absturz kostet höchstens eine Viertelstunde, die der nächste Zählerwert (Lücke wird verteilt) und die Preisprognose wieder auffüllen.
  - Zuvor (0.1.0b2) wurde die ganze, wachsende Datei bei jeder Zähleränderung (verzögert um 60 s, bei sekündlichen Zählern also womöglich nie) geschrieben – nach einem Jahr rund 700 KB je Schreibvorgang.
  - Sensoren werden höchstens **einmal pro Minute** und an jeder Viertelstundengrenze aktualisiert (`NOTIFY_INTERVAL`), nicht bei jedem Zählerwert: weniger Recorder-Zeilen (bei 14 Sensoren und einem Zähler im Sekundentakt sonst über 200 000 am Tag).
  - Das Attribut `ranking` von „Günstigster Tarif“ wird nicht aufgezeichnet (`_unrecorded_attributes`).
  - Grenze: Späte Änderungen an Tagen eines **früheren** Jahres (z. B. ein im Januar nachgelieferter Dezemberpreis) landen erst beim nächsten Archiv-Durchlauf jenes Jahres – praktisch nie nötig.
- README-Hinweise: Der Vergleich unterstellt gleiches Verbrauchsverhalten (mit dynamischem Tarif verschieben Nutzer oft Verbrauch); alle Preisbestandteile auf beiden Seiten gleich erfassen.

## 6. Arbeitsweise

- GitHub: Organisation `tarifwacht` (angelegt 2026-10-26), Repo `integration`. Wie bei der Einspeisewacht: Standard-Branch `main`, Ruleset „main schützen“ (nur grüne CI `test`, `hassfest`, `compat`; kein Löschen, kein Force-Push) und „Release-Tags schützen“ (`v*` unveränderlich). Brand-Bilder seit 2026-10-26 (`docs/BRAND.md`), der CI-Job `hacs` prüft sie mit.
- **GitHub-Sicherheit (gesetzt 2026-10-26, wie Einspeisewacht plus CodeQL):** Organisation mit Zwei-Faktor-Pflicht (ohne „nur sichere Methoden“ – SMS bleibt möglich), Beschreibung und Link gesetzt. Repo: Secret Scanning mit Push-Schutz, Dependabot-Alarme und -Sicherheitsupdates, private Meldung von Sicherheitslücken (für `SECURITY.md`), Branches nach Merge löschen, Actions nur GitHub-eigene plus `astral-sh/setup-uv@*`, `home-assistant/actions/*`, `hacs/action@*` (neue Actions dort freigeben!), Standard-Workflow-Rechte nur lesen, Code Scanning (CodeQL, Standardkonfiguration). **Nicht** gesetzt: unveränderliche Releases – sonst kann `release-asset.yml` die ZIP nach dem Veröffentlichen nicht anhängen; die Tags `v*` schützt der Regelsatz.
- Releases, auch Betas, als **reguläre** GitHub-Releases (nicht „Pre-release“) – sonst sucht HACS die ZIP unter dem Commit und scheitert (Erfahrung Einspeisewacht 0.1.0b2).

## 7. Offene Fragen

- **Preisbestandteile:** Wie erklärt man Nutzern am besten, welche Bestandteile im Aufschlag eines dynamischen Tarifs stecken müssen (Netzentgelt, Konzessionsabgabe, Umlagen, Stromsteuer, Anbieteraufschlag)? Stufe 2: Börsenpreis + einzeln eingetragene Bestandteile.
- **SMARD-Schnittstelle** ist inoffiziell: Ändern sich Pfade oder Format, scheitert nur der Rückblick (Fehlermeldung der Aktion), nicht die laufende Buchung.
- `categories` im Manifest (Hinweis von hassfest).
