# Tarifwacht – Projektkontext für Claude

Home-Assistant-Custom-Integration (HACS), Domain `tarifwacht`. Zeigt laufend und rückwirkend, was der eigene Strombezug mit verschiedenen Tarifen gekostet hätte (Festpreis, dynamisch, Modul 3). Schwesterprojekt von Einspeisewacht (`../einspeisewacht`), Streckenwacht (`../streckenwacht`) und Eilwacht (`../eilwacht`) – deren Muster übernehmen, wo es passt.

## Dokumentation

- **`docs/ENTWICKLUNG.md`** – Umfang, Abgrenzung, verifizierte Eigenheiten der Datenquellen, Schwächen des typischen Eigenbaus, Entscheidungen, offene Fragen. Vor größeren Arbeiten lesen.
- **`CHANGELOG.md`** – Projektstand und Versionsgeschichte. Hier stehen keine Statusberichte.
- **`docs/BRAND.md`** – Farben, Schrift, Bilddateien, Regenerierung. Brand-Bilder nicht verändern oder neu erzeugen, außer auf ausdrücklichen Wunsch.

## Verbindliche Entscheidungen

- **Liest vorhandene Entitäten** (Bezugszähler, Preissensoren), keine Cloud, keine `requirements`. Einzige Netzabfrage: SMARD.de-Börsenpreise für den Rückblick (siehe unten). Erscheint als Integration (`integration_type: service`).
- Nur UI-Config-Flow, kein YAML.
- **Buchungskern aus der Einspeisewacht kopiert** (`timeslots.py`, `prices.py`, `meter.py`, Stand Commit `e4fd5fc`; `ledger.py` ist durch `history.py`/`engine.py` ersetzt; `smard.py` aus Commit `65857dc`): Viertelstunden-Delta des Zählers × Preis dieser Viertelstunde, ohne HA-Importe. Seitdem unabhängig weiterentwickelt, keine Abhängigkeit zur Laufzeit. Bei Fehlerkorrekturen am Kern prüfen, ob die Einspeisewacht denselben Fehler hat (und umgekehrt).
- Intern UTC, Raster 15 Minuten (Umstellungstage: 92 bzw. 100 Viertelstunden). Tage und Monate (Grundpreise) nach deutscher Ortszeit.
- Grundpreise optional, tageweise anteilig. Zeiträume über die Langzeitstatistik.
- **Verlauf statt Summen:** Verbrauch und jeder gesehene Preis werden je Viertelstunde gespeichert (`SlotSeries`, 96 Werte je UTC-Tag); alle Tarifsummen werden beim Start neu berechnet und dann fortgeschrieben. Deshalb gilt jeder neue oder geänderte Tarif ab der Einrichtung. Tarife sind Config-Untereinträge (`tariff`); jede Änderung lädt den Eintrag neu (`async_update_and_abort`, nicht `…reload…`).
- **SD-Karten schonen:** nie bei jeder Zählerablesung schreiben. Live-Datei nach jedem Viertelstunden-Tick, Jahresarchive einmal am Tag, SMARD-Jahresdateien nur nach neuen Wochen; Sensoren höchstens einmal pro Minute.
- **Rückblick** (Aktion `compare` mit Beginn vor der Einrichtung): Verbrauch aus Stundenwerten der Langzeitstatistik, Börsenpreise von SMARD.de nur für Tarife „Börsenpreis plus Aufschläge“ und nur vor der Einrichtung (`FallbackPrice`). Gesamtpreis-Sensoren haben keine Vergangenheit – nie mit SMARD auffüllen.
- **Kein Code aus tariff_compare** (keine Lizenz); nur als Ideengeber im README nennen.
- Lizenz MIT. Repo: `github.com/tarifwacht/integration`. `codeowners`: `@n42net`.

## Arbeitsregeln

1. **Formate nie raten.** Die Dateien in `tests/fixtures/` sind die Wahrheit über Formate der Preissensoren (Herkunft in `tests/fixtures/_index.json`). Neue Preisquellen nur mit Fixture: am besten aufgezeichnet; sonst abgeleitet aus echten API-Daten des Projekts nach dessen Quellcode (fester Commit, Zeilen zitiert, `tools/make_price_fixtures.py`), dann im README als „experimentell“ markiert (Entscheidung 2026-10-26).
2. **Preisbestandteile nie aus dem Gedächtnis.** Netzentgelte, Umlagen, Steuern nur mit Quelle (Preisblatt, Gesetz, Veröffentlichung) in `docs/ENTWICKLUNG.md`.
3. **Keine personenbezogenen Daten ins Repo:** keine Zählerstände, Verläufe oder Tarifdaten des Nutzers – auch nicht als Beispielwerte in Tests. Preis-Fixtures (Marktdaten, SMARD.de, CC BY 4.0) sind erlaubt; Rohdaten nur in `raw/`.
4. Entwickelt wird gegen eine produktive Home-Assistant-Instanz. Logik erst als reines Python ohne HA-Importe testen. Ein Fehler (Preis fehlt, Zähler unavailable) darf nie die Integration oder HA blockieren und nie still falsch buchen.
5. Code, Kommentare, Entity-IDs auf Englisch; UI-Texte über `strings.json` + `translations/de.json` und `en.json`. Doku auf Deutsch.
6. Tests gegen Fixtures. HA-Tests (`tests/ha/`, `pytest-homeassistant-custom-component`) nur in GitHub Actions.
7. **Branches:** Entwickelt wird auf `dev`; `main` erhält nur freigegebene Stände (Versions-Bump in `manifest.json`, `const.py` und `pyproject.toml` mit `uv lock` + GitHub-Release, auch Betas als **reguläres** Release – sonst scheitert HACS). Kein Force-Push, Tags `v*` sind unveränderlich.
8. **Werkzeuge:** `uv run pytest`, `uv run ruff check .`, `uv run ruff format .`. `homeassistant` (dev) und `pytest-homeassistant-custom-component` (ha-tests) immer gemeinsam anheben. Rechnerspezifisches und die Testumgebung stehen in `CLAUDE.local.md`, der Arbeitsstand in `NOTES.md` (beide nicht im Repo).
9. **Release-Ablauf:** Bump auf `dev`, CI grün abwarten, dann `git push origin dev:main` (Fast-Forward). Das GitHub-Release (`gh release create v… --target main --latest --notes-file …`) legt der Nutzer an – der Auto-Modus blockiert Veröffentlichen, Merges ohne Review und `--amend`; nie umgehen, Befehl nennen. Danach die ZIP aus `release-asset.yml` prüfen.

## Fallstricke

- Home Assistant läuft auf diesem Windows-Rechner nicht (`fcntl` fehlt, kein WSL/Docker). Oberfläche und Screenshots über den gesteuerten Browser im HA des Nutzers; anmelden tut er sich selbst. HA-MCP ist nur lesend.
- HA-Tests: Zeitzone ist US/Pacific → `hass.config.async_set_time_zone("Europe/Berlin")`. Recorder-Tests in eigener Datei mit autouse-Fixture, die `recorder_mock` vor `hass` anfordert. `device_registry.async_get_device` ist veraltet (wirft) → `dr.async_entries_for_config_entry`. Die Tests laufen auch gegen HA 2026.3 (`compat`-Job): neue HA-APIs absichern.
- Der EPEX-Spot-Sensor kennt per Prognose den ganzen laufenden Tag – auch die Stunden vor der Einrichtung. In Tests für den Rückblick deshalb den Vortag nehmen.
- Ein Preissensor ohne Prognose liefert nur seinen aktuellen Wert: Der Viertelstunden-Tick muss ihn für jede neue Viertelstunde übernehmen (in der Einspeisewacht steckt dieselbe Stelle noch, gemeldet 2026-10-26).
- Shell-Heredocs mit Anführungszeichen scheitern: Bearbeitungsskripte als Datei in den Scratchpad schreiben. Python-Dateien mit `newline="\n"` schreiben (sonst CRLF).
- In HA 2026.10 heißen die Entwicklerwerkzeuge *Einstellungen → Werkzeuge*; in der Doku beide Wege nennen.
