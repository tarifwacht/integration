# Tarifwacht – Projektkontext für Claude

Home-Assistant-Custom-Integration (HACS), Domain `tarifwacht`. Zeigt laufend und rückwirkend, was der eigene Strombezug mit verschiedenen Tarifen gekostet hätte (Festpreis, dynamisch, später Modul 3). Schwesterprojekt von Einspeisewacht (`../einspeisewacht`), Streckenwacht (`../streckenwacht`) und Eilwacht (`../eilwacht`) – deren Muster übernehmen, wo es passt.

## Dokumentation

- **`docs/ENTWICKLUNG.md`** – Umfang, Abgrenzung, verifizierte Eigenheiten der Datenquellen, Schwächen des typischen Eigenbaus, Entscheidungen, offene Fragen. Vor größeren Arbeiten lesen.
- **`CHANGELOG.md`** – Projektstand und Versionsgeschichte. Hier stehen keine Statusberichte.
- **`docs/BRAND.md`** – Farben, Schrift, Bilddateien, Regenerierung. Brand-Bilder nicht verändern oder neu erzeugen, außer auf ausdrücklichen Wunsch.

## Verbindliche Entscheidungen

- **Liest vorhandene Entitäten** (Bezugszähler, Preissensoren), keine Cloud, keine `requirements`. Erscheint als Integration (`integration_type: service`).
- Nur UI-Config-Flow, kein YAML.
- **Buchungskern aus der Einspeisewacht kopiert** (`timeslots.py`, `prices.py`, `meter.py`, `ledger.py`, Stand Commit `e4fd5fc`): Viertelstunden-Delta des Zählers × Preis dieser Viertelstunde, ohne HA-Importe. Seitdem unabhängig weiterentwickelt, keine Abhängigkeit zur Laufzeit. Bei Fehlerkorrekturen am Kern prüfen, ob die Einspeisewacht denselben Fehler hat (und umgekehrt).
- Intern UTC, Raster 15 Minuten (Umstellungstage: 92 bzw. 100 Viertelstunden). Tage und Monate (Grundpreise) nach deutscher Ortszeit.
- Grundpreise optional, tageweise anteilig. Zeiträume über die Langzeitstatistik.
- **Kein Code aus tariff_compare** (keine Lizenz); nur als Ideengeber im README nennen.
- Lizenz MIT. Repo: `github.com/tarifwacht/integration`. `codeowners`: `@n42net`.

## Arbeitsregeln

1. **Formate nie raten.** Die Dateien in `tests/fixtures/` sind die Wahrheit über Formate der Preissensoren (Herkunft in `tests/fixtures/_index.json`). Neue Preisquellen erst mit echtem Fixture.
2. **Preisbestandteile nie aus dem Gedächtnis.** Netzentgelte, Umlagen, Steuern nur mit Quelle (Preisblatt, Gesetz, Veröffentlichung) in `docs/ENTWICKLUNG.md`.
3. **Keine personenbezogenen Daten ins Repo:** keine Zählerstände, Verläufe oder Tarifdaten des Nutzers – auch nicht als Beispielwerte in Tests. Preis-Fixtures (Marktdaten, SMARD.de, CC BY 4.0) sind erlaubt; Rohdaten nur in `raw/`.
4. Entwickelt wird gegen eine produktive Home-Assistant-Instanz. Logik erst als reines Python ohne HA-Importe testen. Ein Fehler (Preis fehlt, Zähler unavailable) darf nie die Integration oder HA blockieren und nie still falsch buchen.
5. Code, Kommentare, Entity-IDs auf Englisch; UI-Texte über `strings.json` + `translations/de.json` und `en.json`. Doku auf Deutsch.
6. Tests gegen Fixtures. HA-Tests (`tests/ha/`, `pytest-homeassistant-custom-component`) nur in GitHub Actions.
7. **Branches:** Entwickelt wird auf `dev`; `main` erhält nur freigegebene Stände (Versions-Bump in `manifest.json`, `const.py` und `pyproject.toml` mit `uv lock` + GitHub-Release, auch Betas als **reguläres** Release – sonst scheitert HACS). Kein Force-Push, Tags `v*` sind unveränderlich.
8. **Werkzeuge:** `uv run pytest`, `uv run ruff check .`, `uv run ruff format .`. `homeassistant` (dev) und `pytest-homeassistant-custom-component` (ha-tests) immer gemeinsam anheben. Rechnerspezifisches und die Testumgebung stehen in `CLAUDE.local.md`.
