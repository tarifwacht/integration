# Tarifwacht – Projektkontext für Claude

Home-Assistant-Custom-Integration (HACS), Domain `tarifwacht`. Zeigt laufend und rückwirkend, was der eigene Strombezug mit verschiedenen Tarifen gekostet hätte (Festpreis, dynamisch, Modul 3). Schwesterprojekt von Einspeisewacht (`../einspeisewacht`), Streckenwacht (`../streckenwacht`), Eilwacht (`../eilwacht`), Wärmewacht (`../waermewacht`) und Speicherwacht (`../speicherwacht`) – deren Muster übernehmen, wo es passt.

## Dokumentation

- **`docs/ENTWICKLUNG.md`** – Umfang, Abgrenzung, verifizierte Eigenheiten der Datenquellen, Schwächen des typischen Eigenbaus, Entscheidungen, offene Fragen. Vor größeren Arbeiten lesen.
- **`CHANGELOG.md`** – Projektstand und Versionsgeschichte. Hier stehen keine Statusberichte.
- **`docs/BRAND.md`** – Farben, Schrift, Bilddateien, Regenerierung. Brand-Bilder nicht verändern oder neu erzeugen, außer auf ausdrücklichen Wunsch.

## Verbindliche Entscheidungen

- **Liest vorhandene Entitäten** (Bezugszähler, Preissensoren), keine Cloud, keine `requirements`. Einzige Netzabfrage: SMARD.de-Börsenpreise, **nur auf ausdrückliche Aktion des Nutzers** – die Aktionen (Vergleich, Statistik nachtragen) oder der Haken `smard_fill` beim Hinzufügen/Ändern eines Börsenpreis-Tarifs (siehe unten). Erscheint als Integration (`integration_type: service`).
- Nur UI-Config-Flow, kein YAML.
- **Buchungskern aus der Einspeisewacht abgeleitet** (`timeslots.py` und `prices.py` Stand Einspeisewacht-Commit `9d42dcc`, `meter.py` `8569dea`, `smard.py` `aec036e`; maßgeblich ist die Kopfzeile „Derived from … (as of …)“ im Modul und die Tabelle in `../tools/check_shared.py`; ursprünglich kopiert aus `e4fd5fc` bzw. `65857dc`; `ledger.py` ist durch `history.py`/`engine.py` ersetzt): Viertelstunden-Delta des Zählers × Preis dieser Viertelstunde, ohne HA-Importe. Seitdem unabhängig weiterentwickelt, keine Abhängigkeit zur Laufzeit. Bei Fehlerkorrekturen am Kern prüfen, ob die Einspeisewacht denselben Fehler hat (und umgekehrt).
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

**Versionsnummer** (seit 2026-11-13, Andys Ja, gleich in allen sechs Wachten): die zweite Ziffer (0.x.0) bei neuen Sensoren, Blueprints oder Funktionen und bei allem mit „Bitte prüfen“; die dritte (0.x.y) nur bei Fehlerbehebungen und geänderten Texten. Nach Vorabversionen gilt zusätzlich Schritt 6.

**Version 1.0** (seit 2026-11-13, Andys Ja, gleich in allen sechs Wachten): 1.0.0 erst, wenn (1) ein paar Wochen kein Eintrag „Bitte prüfen“, keine umgezogenen Attribute und keine geänderte Bedeutung von Werten kamen, (2) der Kern fertig ist und die wichtigen Vorlagen bzw. Quellen von echten Nutzern bestätigt sind, (3) keine Fehlerberichte offen sind und die CI dauerhaft grün ist. Ab 1.0 bekommt alles, was bestehende Automationen, Dashboards oder Einstellungen bricht, eine neue erste Ziffer (2.0.0) und einen Eintrag „Bitte prüfen“. Stand 13.11.: erster Kandidat Streckenwacht (nach 0.10.0 und 2–3 Wochen ohne Fehler), Einspeisewacht zusammen mit dem EEG-2027-Update, Wärmewacht frühestens nach dem Winter.

1. Version in `manifest.json`, `const.py` und `pyproject.toml` anheben, `uv lock`; `tests/test_manifest.py` prüft die Gleichheit. „Unveröffentlicht“ in `CHANGELOG.md` zur Version machen. Danach `uv run tools/make_demo.py` laufen lassen und geänderte Dateien unter `docs/demo/` in den Versions-Commit nehmen: Die Demo zeigt die Version und rechnet mit dem Code der Integration, Pages baut nur `main` (Eilwacht 0.3.2 zeigte so noch 0.3.1).
2. `dev` pushen und auf den CI-Lauf **genau dieses Commits** warten (`gh run list --commit <sha>` mit vollem SHA aus `git rev-parse HEAD`, ein Kurz-SHA findet nichts): Push-CI startet manchmal Minuten verspätet, ein älterer grüner Lauf täuscht.
3. `main` vorspulen mit `git push origin dev:main` – **ohne Branch-Wechsel** im Arbeitsverzeichnis (auf dem Netzlaufwerk hat `git switch` schon Dateien verloren, ein Release entstand so auf altem Stand). Danach prüfen, dass `origin/main` auf dem Versions-Commit steht.
4. `gh release create vX --target main --latest --notes-file …` (Text nach „Release-Notes“ unten). Ziel `main`, kein Kurz-SHA (gibt 422). Immer ein **reguläres** Release, auch für Betas, nie `--prerelease`: Sonst nimmt HACS den letzten Commit und sucht dort vergeblich die ZIP. Blockiert der Auto-Modus das Veröffentlichen: Befehl nennen, der Inhaber führt ihn aus – nie umgehen.
5. Workflow „Release-ZIP“ prüfen: `tarifwacht.zip` muss am Release hängen. Der Workflow bricht ab, wenn Tag und `manifest.json` nicht passen; fehlt die ZIP, ihn per Hand mit dem Tag starten. Ohne ZIP scheitern HACS-Installationen.
6. Prüfen, dass HACS die neue Version sieht: `gh api repos/<org>/integration/releases --jq '.[0].tag_name'` muss das neue Tag sein – HACS nimmt den **ersten** Eintrag dieser Liste, nicht „Latest“. GitHub sortiert diese Liste offenbar nach der Basisversion; innerhalb derselben Basis (`0.1.0b1` … `0.1.0b10`, `0.1.0`) ist die Reihenfolge willkürlich (Tarifwacht 2026-10-27: b9, b8, b7, b6, **b10**, **0.1.0**, b5 …; Einspeisewacht: 0.1.1 oben, darunter b11, b10, 0.1.0, b9 …). HACS bot deshalb weder b10 noch 0.1.0 an. **Regel:** Nach Vorabversionen die nächste Version mit **höherer Basis** veröffentlichen (`0.1.1` statt `0.1.0` nach `0.1.0b…`), und Vorabnummern zweistellig gar nicht erst erreichen.
7. Bricht eine Sitzung mitten im Release ab: erst den Stand prüfen (`git log origin/dev origin/main`, CI des Commits, `gh release list`), dann weitermachen.

### Release-Notes (seit 2026-11-11, Anlass Wärmewacht-Issue #5)

HACS zeigt den Release-Text in der Update-Entität von HA. Deshalb **Englisch zuerst, Deutsch darunter** (gleich in allen sechs Wachten):

- Erste Zeile `*(German version below · Deutsche Fassung weiter unten)*`, dann `## English` mit der englischen Fassung, dann `## Deutsch` mit dem Abschnitt aus dem `CHANGELOG.md` wörtlich. **Kein eigenes `---`:** HACS hängt die Texte aller Releases zwischen installierter und neuester Version aneinander (höchstens fünf, Einstellung `release_limit`), je mit `# vX` davor und `---` danach (`update.py`, `async_release_notes`, geprüft 11.11.). Deshalb zählen auch die Texte der letzten fünf Releases, nicht nur der neueste.
- Gruppen, nur wenn belegt, in dieser Reihenfolge: **Action needed / Bitte prüfen** (Breaking Changes, alles, was man nach dem Update selbst tun muss), **New / Neu**, **Fixed / Behoben**, **Changed / Geändert**. Das `CHANGELOG.md` hat dieselben Gruppen als `###`.
- Jeder Eintrag: fette Überschrift, dann ein bis drei Sätze (was ändert sich, wen betrifft es, was ist zu tun). Hintergrund (Rechenweg, Quellen, Messwerte) gehört in README oder `docs/ENTWICKLUNG.md`, im Eintrag höchstens ein Link.
- Statt „Anlass: …“ am Ende des Eintrags „(thanks to … / danke an …)“. GitHub-Nutzer mit `@login` (GitHub benachrichtigt sie und zeigt sie als Beitragende am Release), Forum-Nutzer mit ihrem öffentlichen Namen und dem Forum, z. B. „(thanks to suedschwede, simon42 forum)“. Eigene Prüfung: nichts dazuschreiben.
- Im englischen Teil die Begriffe aus `translations/en.json` verwenden, keine eigene Übersetzung von Feldnamen.

„Unveränderliche Releases“ bleibt in GitHub aus, weil der Workflow die ZIP erst nach dem Veröffentlichen anhängt; die Tags `v*` schützt das Ruleset.

## Fallstricke

- Home Assistant läuft auf diesem Windows-Rechner nicht (`fcntl` fehlt, kein WSL/Docker). Oberfläche und Screenshots über den gesteuerten Browser im HA des Nutzers; anmelden tut er sich selbst. HA-MCP ist nur lesend.
- HA-Tests: Zeitzone ist US/Pacific → `hass.config.async_set_time_zone("Europe/Berlin")`. Recorder-Tests in eigener Datei mit autouse-Fixture, die `recorder_mock` vor `hass` anfordert. `device_registry.async_get_device` ist veraltet (wirft) → `dr.async_entries_for_config_entry`. Die Tests laufen auch gegen HA 2026.3 (`compat`-Job): neue HA-APIs absichern.
- Der EPEX-Spot-Sensor kennt per Prognose den ganzen laufenden Tag – auch die Stunden vor der Einrichtung. In Tests für den Rückblick deshalb den Vortag nehmen.
- Ein Preissensor ohne Prognose liefert nur seinen aktuellen Wert: Der Viertelstunden-Tick muss ihn für jede neue Viertelstunde übernehmen (in der Einspeisewacht ebenso behoben, Commit `027f447`, 0.1.0b9).
- Shell-Heredocs mit Anführungszeichen scheitern: Bearbeitungsskripte als Datei in den Scratchpad schreiben. Python-Dateien mit `newline="\n"` schreiben (sonst CRLF).
- In HA 2026.10 heißen die Entwicklerwerkzeuge *Einstellungen → Werkzeuge*; in der Doku beide Wege nennen.
