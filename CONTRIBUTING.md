# Mitmachen

Danke, dass du Tarifwacht verbessern willst! Fehler und Ideen bitte als [Issue](https://github.com/tarifwacht/integration/issues/new/choose). Sicherheitslücken bitte vertraulich melden, siehe [SECURITY.md](SECURITY.md).

## Pull Requests

- Kleine Änderungen (Fehlerbehebungen, Übersetzungen, Doku) gern direkt als Pull Request. Neue Funktionen, Tarifarten, Preisquellen oder Umbauten bitte erst in einem Issue besprechen, damit niemand umsonst arbeitet.
- **Basis ist `dev`**, nicht `main`. `main` enthält nur veröffentlichte Stände, an denen die HACS-Installationen hängen.
- Vor dem Pull Request: `uv run pytest`, `uv run ruff check .` und `uv run ruff format .`. Die Home-Assistant-Tests (`tests/ha/`) laufen nur in GitHub Actions, unter Windows nicht. Bei Pull Requests aus Forks startet die CI erst, wenn ich sie freigebe.
- Code, Kommentare und Entity-IDs auf Englisch. UI-Texte stehen in `strings.json` und `translations/de.json` + `en.json`, immer in beiden Sprachen.
- `CHANGELOG.md` und Versionsnummer bitte nicht ändern. Den Eintrag und das Release übernehme ich.

## KI-Assistenten

Beiträge mit Hilfe von KI-Assistenten (z. B. Claude Code) sind willkommen, wenn du die Änderung selbst verstanden und getestet hast. Bitte im Pull Request kurz erwähnen; ein `Co-Authored-By`-Trailer im Commit genügt.

[`CLAUDE.md`](CLAUDE.md) und [`docs/ENTWICKLUNG.md`](docs/ENTWICKLUNG.md) enthalten die Projektregeln, die dein Assistent lesen sollte. Release, Veröffentlichen und alles an `main` mache nur ich.

## Besonderheiten von Tarifwacht

- **Preisbestandteile nur mit Quelle:** Netzentgelte, Umlagen und Steuern mit Preisblatt, Gesetz oder Veröffentlichung, eingetragen in [`docs/ENTWICKLUNG.md`](docs/ENTWICKLUNG.md), nicht aus dem Gedächtnis.
- **Neue Preisquellen nur mit Fixture** in `tests/fixtures/` (Herkunft in `_index.json`), am besten aufgezeichnet. Nur aus dem Quellcode abgeleitete Formate gelten als „experimentell“. Formate nie raten.
- **Keine personenbezogenen Daten ins Repo:** keine eigenen Zählerstände, Verläufe oder Tarifdaten, auch nicht als Testwerte. Marktdaten (z. B. SMARD.de) sind erlaubt.
- Änderungen an der Buchung nur mit Tests. Fehlt ein Preis oder ist ein Zähler `unavailable`, darf nie still falsch gebucht werden.

## English

Contributions are welcome. Small fixes, translations and docs can go straight to a pull request; for new features, tariff types, price sources or larger changes please open an issue first. Target the **`dev`** branch, run `uv run pytest` and `uv run ruff check .` before opening the PR, and keep code and comments in English (UI texts in both German and English). Price components need a source, new price sources a fixture, and no personal meter or tariff data goes into the repo. AI-assisted contributions are fine if you have reviewed and tested them yourself; please mention it in the PR. Issues and pull requests in English are welcome.
