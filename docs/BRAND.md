# Tarifwacht – Marke & Bilddateien

## Idee

Vier Viertelstunden-Balken gegen eine waagerechte Linie: Die Balken sind die Preise des dynamischen Tarifs, die Linie ist der Festpreis. Was über der Linie liegt, ist blass – dort wäre dynamisch teurer. Das Wachlicht mit Halo markiert den einen Balken, der darunter bleibt: Hier wäre dynamisch günstiger. Kachel, Schutzzone, Amber-Wachlicht, Off-White und Schrift sind dieselben wie bei Streckenwacht, Eilwacht und Einspeisewacht; das Wachlicht sitzt an derselben Stelle wie bei der Einspeisewacht. Die Kachelfarbe ist **RAL 4006 Verkehrspurpur**.

**Slogan:** „Jeder Tarif. Jede Viertelstunde.“

## Farben

| Rolle | Hex | Hinweis |
| --- | --- | --- |
| Kachel, Wortmarke | `#96497D` | RAL 4006 Verkehrspurpur, umgerechnet aus CIE L\*a\*b\* 42,38 / 39,48 / −14,94 (D65, Quelle: de.wikipedia.org, Artikel „RAL-Farbe“) |
| Wachlicht | `#F5A623` | Amber, wie bei den Geschwistern |
| Balken, Linie | `#FBF7EE` | warmes Off-White; über der Linie mit 45 % Deckkraft |
| Heller Hintergrund | `#FAF7F2` | README-Kopf, Social Preview |
| Dunkler Hintergrund | `#14181D` | README-Kopf (Dark Mode) |
| Tagline hell / dunkel | `#6B6357` / `#B9B2A6` | |

Halo: Amber mit 35 % Deckkraft. Kontrast Kachel zu Off-White 5,5 : 1.

**Zum Farbwert:** RAL legt keine Bildschirmfarben fest; Hex-Tabellen im Netz widersprechen sich (für RAL 4006 u. a. `#903373`, `#922B6E`, `#992572`). Tarifwacht rechnet deshalb nachvollziehbar aus den L\*a\*b\*-Werten um (D65 → XYZ → sRGB); dieselbe Umrechnung ergibt für RAL 5017 genau den Wert der Streckenwacht (`#005B8C`). Die Werte von Eilwacht und Einspeisewacht stammen aus einer anderen Tabelle.

## Schrift

**Space Grotesk** (Google Fonts, SIL Open Font License), Bold 700 für die Wortmarke, Medium 500 für Tagline und Zusatzzeilen. In allen SVGs ist der Text in Pfade umgewandelt.

## Dateien

| Ort | Inhalt |
| --- | --- |
| `custom_components/tarifwacht/brand/` | `icon(@2x)`, `dark_icon(@2x)`, `logo(@2x)`, `dark_logo(@2x)` – lädt Home Assistant ab 2026.3 aus der Integration |
| `assets/github/` | README-Kopf hell/dunkel (960×220, @2x), Social Preview 1280×640, Profilbild der Organisation 500/1024 |
| `assets/brand/svg/` | Vektor-Master: Icon, Mini-Icon, vollflächiges Icon, Motiv, Logo, README-Kopf, Social Preview |
| `assets/brand/png/` | Icon 16–2048 px, Motiv ohne Kachel, Logo hell/dunkel |
| `assets/brand/favicon/` | `favicon.ico` (16/32/48), `favicon.svg`, PNG, Apple-Touch- und Android-Icons |

Profilbild der Organisation und Social Preview lassen sich nicht per API setzen: von Hand hochladen (Organisation → Settings → Profile; Repo → Settings → General → Social preview).

## Regeln

- **≤ 32 px immer die Mini-Variante**: drei breitere Balken, dickere Linie, größeres Wachlicht, keine blassen Kappen, kein Halo.
- Motiv ohne Kachel: auf hellem Grund in Verkehrspurpur (`mark-on-light`), auf dunklem in Off-White (`mark-on-dark`).
- Farben nicht verändern, Motiv nicht verzerren, keine Schatten oder Verläufe.
- Um Logo und Icon mindestens ¼ der Kachelbreite frei lassen.

## Neu erzeugen

```bash
cd tools/brand
npm install
node build.mjs
```

Das Skript (von der Einspeisewacht übernommen) schreibt direkt an die Plätze oben; vorher werden diese Ordner geleert. Farben, Name, Slogan und Unterzeile stehen als Konstanten oben in `build.mjs`.

## Entstehung

Drei Motive verglichen (für Eingeladene: `https://claude.ai/artifact/Uhwye99FQeyEzSwCxYySL6`): Linie gegen Balken, Waage, Preisschild; Kachelfarben Verkehrspurpur, Blaulila (RAL 4005), Wasserblau (RAL 5021). Gewählt am 2026-10-26: Linie gegen Balken in Verkehrspurpur – erklärt als einziges Motiv das Prinzip und setzt die Reihe der Verkehrsfarben fort.
