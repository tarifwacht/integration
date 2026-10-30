# Tarifwacht – Projektkontext für Claude

Home-Assistant-Custom-Integration (HACS), Domain `tarifwacht`. Zeigt laufend und rückwirkend, was der eigene Strombezug mit verschiedenen Tarifen gekostet hätte (Festpreis, dynamisch, Modul 3). Schwesterprojekt von Einspeisewacht (`../einspeisewacht`), Streckenwacht (`../streckenwacht`), Eilwacht (`../eilwacht`), Wärmewacht (`../waermewacht`) und Speicherwacht (`../speicherwacht`) – deren Muster übernehmen, wo es passt.

## Dokumentation

- **`docs/ENTWICKLUNG.md`** – Umfang, Abgrenzung, verifizierte Eigenheiten der Datenquellen, Schwächen des typischen Eigenbaus, Entscheidungen, offene Fragen. Vor größeren Arbeiten lesen.
- **`CHANGELOG.md`** – Projektstand und Versionsgeschichte. Hier stehen keine Statusberichte.
- **`docs/BRAND.md`** – Farben, Schrift, Bilddateien, Regenerierung. Brand-Bilder nicht verändern oder neu erzeugen, außer auf ausdrücklichen Wunsch.

## Verbindliche Entscheidungen

- **Liest vorhandene Entitäten** (Bezugszähler, Preissensoren), keine Cloud, keine `requirements`. Einzige Netzabfrage: SMARD.de-Börsenpreise, **nur auf ausdrückliche Aktion des Nutzers** – die Aktionen (Vergleich, Statistik nachtragen) oder der Haken `smard_fill` beim Hinzufügen/Ändern eines Börsenpreis-Tarifs (siehe unten). Erscheint als Integration (`integration_type: service`).
- Nur UI-Config-Flow, kein YAML.
- **Buchungskern aus der Einspeisewacht kopiert** (`timeslots.py`, `prices.py`, `meter.py`, Stand Commit `e4fd5fc`; `ledger.py` ist durch `history.py`/`engine.py` ersetzt; `smard.py` aus Commit `65857dc`): Viertelstunden-Delta des Zählers × Preis dieser Viertelstunde, ohne HA-Importe. Seitdem unabhängig weiterentwickelt, keine Abhängigkeit zur Laufzeit. Bei Fehlerkorrekturen am Kern prüfen, ob die Einspeisewacht denselben Fehler hat (und umgekehrt).
- Intern UTC, Raster 15 Minuten (Umstellungstage: 92 bzw. 100 Viertelstunden). Tage und Monate (Grundpreise) nach deutscher Ortszeit.
- Grundpreise optional, tageweise anteilig. Zeiträume über die Langzeitstatistik.
- **Verlauf statt Summen:** Verbrauch und jeder gesehene Preis werden je Viertelstunde gespeichert (`SlotSeries`, 96 Werte je UTC-Tag); alle Tarifsummen werden beim Start neu berechnet und dann fortgeschrieben. Deshalb gilt jeder neue oder geänderte Tarif ab der Einrichtung. Kennt der Preissensor eines später hinzugefügten Tarifs die Zeit davor nicht (`Engine.unpriced_until`), füllt `MeterRuntime._async_fill_past_prices` sie im Hintergrund: Börsenpreis-Tarife per `FallbackPrice` aus SMARD.de nur mit Haken `smard_fill` im Tarif (beim Hinzufügen eines Börsenpreis-Tarifs sichtbar vorbelegt und abwählbar; bestehende Tarife laden nichts, bis man ihn beim Ändern setzt – Entscheidung des Inhabers 30.10.; fehlt er: wie früher ausgelassen), Gesamtpreis-Sensoren ohne Rückfrage aus ihren Zuständen im Recorder (lokal, `prices_from_states`, ~10 Tage). Tarife sind Config-Untereinträge (`tariff`); jede Änderung lädt den Eintrag neu (`async_update_and_abort`, nicht `…reload…`).
- **SD-Karten schonen:** nie bei jeder Zählerablesung schreiben. Live-Datei nach jedem Viertelstunden-Tick, Jahresarchive einmal am Tag, SMARD-Jahresdateien nur nach neuen Wochen; Sensoren höchstens einmal pro Minute.
- **Rückblick** (Aktion `compare` mit Beginn vor der Einrichtung): Verbrauch aus Stundenwerten der Langzeitstatistik, Börsenpreise von SMARD.de nur für Tarife „Börsenpreis plus Aufschläge“, nur auf ausdrückliche Aktion des Nutzers und nur für die Zeit, bevor die Tarifwacht den Sensor las: vor der Einrichtung (Aktionen), bei später hinzugefügtem Tarif bzw. neuem Sensor bis zu dessen erstem Preis nur mit Haken `smard_fill` (`FallbackPrice`, `_smard_until`). Nie still beim Laden ohne diesen Haken. Gesamtpreis-Sensoren haben keine Vergangenheit außer ihrem Recorder-Verlauf – nie mit SMARD auffüllen.
- **Kein Code aus tariff_compare** (keine Lizenz); nur als Ideengeber im README nennen.
- Lizenz MIT. Repo: `github.com/tarifwacht/integration`. `codeowners`: `@n42net`.

## Arbeitsregeln

1. **Formate nie raten.** Die Dateien in `tests/fixtures/` sind die Wahrheit über Formate der Preissensoren (Herkunft in `tests/fixtures/_index.json`). Neue Preisquellen nur mit Fixture: am besten aufgezeichnet; sonst abgeleitet aus echten API-Daten des Projekts nach dessen Quellcode (fester Commit, Zeilen zitiert, `tools/make_price_fixtures.py`), dann im README als „experimentell“ markiert (Entscheidung 2026-10-26).
2. **Preisbestandteile nie aus dem Gedächtnis.** Netzentgelte, Umlagen, Steuern nur mit Quelle (Preisblatt, Gesetz, Veröffentlichung) in `docs/ENTWICKLUNG.md`.
3. **Keine personenbezogenen Daten ins Repo:** keine Zählerstände, Verläufe oder Tarifdaten des Nutzers – auch nicht als Beispielwerte in Tests. Preis-Fixtures (Marktdaten, SMARD.de, CC BY 4.0) sind erlaubt; Rohdaten nur in `raw/`.
4. Entwickelt wird gegen eine produktive Home-Assistant-Instanz. Logik erst als reines Python ohne HA-Importe testen. Ein Fehler (Preis fehlt, Zähler unavailable) darf nie die Integration oder HA blockieren und nie still falsch buchen.
5. Code, Kommentare, Entity-IDs auf Englisch; UI-Texte über `strings.json` + `translations/de.json` und `en.json`. Doku auf Deutsch.
6. Tests gegen Fixtures. HA-Tests (`tests/ha/`, `pytest-homeassistant-custom-component`) nur in GitHub Actions.
7. **Branches:** Entwickelt wird auf `dev`; `main` erhält nur freigegebene Stände (Ablauf unter „Release“), weil die HACS-Installationen daran hängen. Ein Ruleset erzwingt grüne CI (`test`, `hassfest`, `compat`) für `main`. Kein Force-Push, Tags `v*` sind unveränderlich.
8. **Werkzeuge:** `uv run pytest`, `uv run ruff check .`, `uv run ruff format .`. `homeassistant` (dev) und `pytest-homeassistant-custom-component` (ha-tests) immer gemeinsam anheben. Rechnerspezifisches und die Testumgebung stehen in `CLAUDE.local.md`, der Arbeitsstand in `NOTES.md` (beide nicht im Repo).

## Release

Gleicher Ablauf in allen Schwesterprojekten (Eilwacht, Einspeisewacht, Speicherwacht, Streckenwacht, Tarifwacht, Wärmewacht). Neue Erkenntnisse zum Ablauf hier eintragen und für die Schwestern melden.

1. Version in `manifest.json`, `const.py` und `pyproject.toml` anheben, `uv lock`; `tests/test_manifest.py` prüft die Gleichheit. „Unveröffentlicht“ in `CHANGELOG.md` zur Version machen.
2. `dev` pushen und auf den CI-Lauf **genau dieses Commits** warten (`gh run list --commit <sha>`): Push-CI startet manchmal Minuten verspätet, ein älterer grüner Lauf täuscht.
3. `main` vorspulen mit `git push origin dev:main` – **ohne Branch-Wechsel** im Arbeitsverzeichnis (auf dem Netzlaufwerk hat `git switch` schon Dateien verloren, ein Release entstand so auf altem Stand). Danach prüfen, dass `origin/main` auf dem Versions-Commit steht.
4. `gh release create vX --target main --latest --notes-file …` (Text aus dem Changelog). Ziel `main`, kein Kurz-SHA (gibt 422). Immer ein **reguläres** Release, auch für Betas, nie `--prerelease`: Sonst nimmt HACS den letzten Commit und sucht dort vergeblich die ZIP. Blockiert der Auto-Modus das Veröffentlichen: Befehl nennen, der Inhaber führt ihn aus – nie umgehen.
5. Workflow „Release-ZIP“ prüfen: `tarifwacht.zip` muss am Release hängen. Der Workflow bricht ab, wenn Tag und `manifest.json` nicht passen; fehlt die ZIP, ihn per Hand mit dem Tag starten. Ohne ZIP scheitern HACS-Installationen.
6. Prüfen, dass HACS die neue Version sieht: `gh api repos/<org>/integration/releases --jq '.[0].tag_name'` muss das neue Tag sein – HACS nimmt den **ersten** Eintrag dieser Liste, nicht „Latest“. GitHub sortiert diese Liste offenbar nach der Basisversion; innerhalb derselben Basis (`0.1.0b1` … `0.1.0b10`, `0.1.0`) ist die Reihenfolge willkürlich (Tarifwacht 2026-10-27: b9, b8, b7, b6, **b10**, **0.1.0**, b5 …; Einspeisewacht: 0.1.1 oben, darunter b11, b10, 0.1.0, b9 …). HACS bot deshalb weder b10 noch 0.1.0 an. **Regel:** Nach Vorabversionen die nächste Version mit **höherer Basis** veröffentlichen (`0.1.1` statt `0.1.0` nach `0.1.0b…`), und Vorabnummern zweistellig gar nicht erst erreichen.
7. Bricht eine Sitzung mitten im Release ab: erst den Stand prüfen (`git log origin/dev origin/main`, CI des Commits, `gh release list`), dann weitermachen.

„Unveränderliche Releases“ bleibt in GitHub aus, weil der Workflow die ZIP erst nach dem Veröffentlichen anhängt; die Tags `v*` schützt das Ruleset.

## Fallstricke

- Home Assistant läuft auf diesem Windows-Rechner nicht (`fcntl` fehlt, kein WSL/Docker). Oberfläche und Screenshots über den gesteuerten Browser im HA des Nutzers; anmelden tut er sich selbst. HA-MCP ist nur lesend.
- HA-Tests: Zeitzone ist US/Pacific → `hass.config.async_set_time_zone("Europe/Berlin")`. Recorder-Tests in eigener Datei mit autouse-Fixture, die `recorder_mock` vor `hass` anfordert. `device_registry.async_get_device` ist veraltet (wirft) → `dr.async_entries_for_config_entry`. Die Tests laufen auch gegen HA 2026.3 (`compat`-Job): neue HA-APIs absichern.
- Der EPEX-Spot-Sensor kennt per Prognose den ganzen laufenden Tag – auch die Stunden vor der Einrichtung. In Tests für den Rückblick deshalb den Vortag nehmen.
- Ein Preissensor ohne Prognose liefert nur seinen aktuellen Wert: Der Viertelstunden-Tick muss ihn für jede neue Viertelstunde übernehmen (in der Einspeisewacht ebenso behoben, Commit `027f447`, 0.1.0b9).
- Shell-Heredocs mit Anführungszeichen scheitern: Bearbeitungsskripte als Datei in den Scratchpad schreiben. Python-Dateien mit `newline="\n"` schreiben (sonst CRLF).
- In HA 2026.10 heißen die Entwicklerwerkzeuge *Einstellungen → Werkzeuge*; in der Doku beide Wege nennen.
