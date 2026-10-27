<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/tarifwacht/integration/main/assets/github/readme-header-dark@2x.png">
  <img alt="Tarifwacht – Jeder Tarif. Jede Viertelstunde." src="https://raw.githubusercontent.com/tarifwacht/integration/main/assets/github/readme-header-light@2x.png" width="640">
</picture>

[![Release](https://img.shields.io/github/v/release/tarifwacht/integration?color=96497D)](https://github.com/tarifwacht/integration/releases)
[![CI](https://github.com/tarifwacht/integration/actions/workflows/ci.yml/badge.svg)](https://github.com/tarifwacht/integration/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-F5A623.svg)](LICENSE)

🇩🇪 **Deutsch** · 🇬🇧 [English](https://github.com/tarifwacht/integration/blob/main/README.en.md)

> ℹ️ **Beta.** Tarifwacht ist neu und wird gerade erprobt. Rückmeldungen sind sehr willkommen – siehe [Fehler melden](#fehler-melden).

**Was hätte dein Strom mit einem anderen Tarif gekostet?** Tarifwacht rechnet deinen tatsächlichen Strombezug in Home Assistant Viertelstunde für Viertelstunde gegen beliebig viele Tarife – Festpreis, dynamisch, mit oder ohne Modul 3 – und zeigt, welcher günstiger gewesen wäre. Jeder dynamische Tarif bekommt dabei den Preis **genau dieser Viertelstunde**, nicht den Preis des Augenblicks, in dem der Zähler zufällig meldet.

> **Keine Abrechnungs- oder Tarifberatung.** Die Werte sind eine Orientierung. Maßgeblich ist die Abrechnung deines Stromanbieters.

Die Oberfläche gibt es auf Deutsch und Englisch; sie folgt der Sprache deines Home Assistant.

<img alt="Gerät eines Tarifs mit Kosten, Durchschnittspreis und Differenz zum aktuellen Tarif" src="https://raw.githubusercontent.com/tarifwacht/integration/main/assets/screenshots/geraet.png" width="640">

## Was Tarifwacht kann

- **Kosten je Tarif** (€): Verbrauchskosten und Kosten gesamt (mit Grundpreis) – mit Langzeitstatistik für Statistik-Karten und Energie-Dashboard.
- **Differenz zum aktuellen Tarif** (€) für jeden anderen Tarif. Positiv heißt: Dieser Tarif wäre teurer gewesen; negativ: günstiger.
- **Durchschnittspreis** je Tarif (ct/kWh, mit Grundpreis) und **Günstigster Tarif** bisher.
- **Beliebig viele Tarife:** Festpreis, dynamisch mit einem Gesamtpreis-Sensor oder dynamisch aus Börsenpreis plus Netzentgelt, Steuern/Abgaben, Anbieteraufschlag und Mehrwertsteuer.
- **Modul 3** (§ 14a EnWG): zeitvariables Netzentgelt mit Niedrig- und Hochlastfenstern je Quartal.
- **Preisänderungen ab einem Datum**, z. B. neue Netzentgelte zum 1. Januar – davor gelten die alten Preise weiter.
- **Grundpreise** optional, pro Monat oder pro Jahr, tageweise anteilig.
- **Vergleich für einen beliebigen Zeitraum** per Aktion, je Monat aufgeschlüsselt – auch **vor der Einrichtung**, so weit die Langzeitstatistik deines Zählers zurückreicht: Was hätte dich das letzte Jahr mit jedem Tarif gekostet? Auf Wunsch auch [in die Langzeitstatistik nachgetragen](#statistik-nachtragen).
- **Rechnet jeden Tarif ab der Einrichtung:** Verbrauch und Preise werden je Viertelstunde gespeichert. Ein später hinzugefügter oder korrigierter Tarif gilt deshalb für den ganzen Zeitraum.
- **Verliert nichts:** Fällt der Zähler aus oder startet Home Assistant neu, wird der Verbrauch der Lücke nachgebucht. Fehlt ein Preis, rechnet Tarifwacht nie mit 0 €. Zähler-Resets und unplausible Sprünge werden erkannt und nicht gebucht.
- **Schont SD-Karten:** schreibt nur einmal pro Viertelstunde (abgeschlossene Tage einmal am Tag ins Jahresarchiv) und aktualisiert die Sensoren höchstens einmal pro Minute.
- Rein lokal: liest nur vorhandene Entitäten, keine Cloud. Nur für den Rückblick lädt Tarifwacht öffentliche Börsenpreise von SMARD.de.

## Hinweise zum Vergleich

- Der Vergleich unterstellt das **gleiche Verbrauchsverhalten**. Mit einem dynamischen Tarif verschieben viele ihren Verbrauch in günstige Stunden – das kann der Vergleich nicht abbilden. Er zeigt also eher, was ein dynamischer Tarif *mindestens* bringt.
- Erfasse **alle Preisbestandteile auf beiden Seiten** gleich, sonst ist der Vergleich verzerrt. Der Gesamtpreis eines dynamischen Tarifs ist Börsenpreis plus Netzentgelt, Konzessionsabgabe, Umlagen, Stromsteuer und Anbieteraufschlag, dazu Mehrwertsteuer. Die Werte stehen in den Preisblättern von Anbieter und Netzbetreiber.
- Home Assistant misst meist mit einem eigenen Zähler (Lesekopf, Energiemessgerät), der Anbieter mit dem Zähler des Netzbetreibers. Kleine Abweichungen sind normal.

## Voraussetzungen

- Home Assistant 2026.3 oder neuer.
- Ein **Bezugszähler**: fortlaufender Energiesensor (Wh, kWh oder MWh) für den Strom aus dem Netz, am besten der Zähler am Netzanschlusspunkt.
- Für dynamische Tarife ein **Preissensor** in €/kWh, am besten mit Prognose je Viertelstunde oder Stunde:

| Quelle (Integration) | Gesamtpreis | Börsenpreis | Status |
|---|---|---|---|
| [EPEX Spot](https://github.com/mampfes/ha_epex_spot) | `…_total_price` | `…_market_price` | erprobt |
| [Nord Pool](https://github.com/custom-components/nordpool) (HACS) | Sensor mit MwSt. und Zusatzkosten | Sensor ohne MwSt. und Zusatzkosten | experimentell |
| [ENTSO-E](https://github.com/JaccoR/hass-entso-e) (HACS) | Durchschnittspreis-Sensor mit Aufschlägen | Durchschnittspreis-Sensor ohne Aufschläge | experimentell |

„Experimentell“ heißt: Das Format ist aus dem Quellcode der Integration und echten Marktdaten nachgebildet, aber noch nicht an einer laufenden Installation geprüft. Wenn du eine davon nutzt, freue ich mich über eine Rückmeldung mit der Diagnose-Datei. Die Nord-Pool-Integration von Home Assistant selbst liefert keine Prognose als Attribut und wird nicht unterstützt.

Ein Sensor ohne Prognose geht auch: Dann gilt sein aktueller Wert, bis er sich ändert. Läuft Home Assistant eine Zeit lang nicht, fehlen für diese Zeit aber die Preise – mit Prognose holt Tarifwacht sie nach.

## Installation

1. HACS → ⋮ → *Benutzerdefinierte Repositories* → `https://github.com/tarifwacht/integration`, Typ *Integration*.
2. Tarifwacht suchen und herunterladen. Home Assistant neu starten.
3. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Tarifwacht*.

## Einrichtung

1. **Bezugszähler:** Name (z. B. „Haus“) und Zähler.
2. **Festpreistarif:** Arbeitspreis (ct/kWh, brutto), optional der Grundpreis pro Monat. Er wird „Mein aktueller Tarif“.
3. **Dynamischer Tarif:** erst die Art wählen – **Börsenpreis plus Aufschläge** (empfohlen, siehe [Dynamischen Tarif anlegen](#dynamischen-tarif-anlegen)) oder Sensor mit Gesamtpreis (rechnet nur ab der Einrichtung) –, dann die Preise.

Daraus entstehen die ersten beiden Tarife. Hast du Tarifwacht vor 0.1.0b10 mit einem Gesamtpreis-Sensor eingerichtet: den dynamischen Tarif zusätzlich als „Börsenpreis plus Aufschläge“ anlegen, danach kannst du den alten löschen.

### Weitere Tarife

*Tarifwacht → Tarif hinzufügen* und die Art wählen:

<img alt="Auswahl der Tarifart" src="https://raw.githubusercontent.com/tarifwacht/integration/main/assets/screenshots/tarif-art.png" width="480">

| Art | Eingaben |
|---|---|
| Festpreis | Arbeitspreis (ct/kWh, brutto) |
| Dynamisch: Sensor mit Gesamtpreis | Sensor, der schon alle Bestandteile enthält – rechnet nur ab der Einrichtung |
| Dynamisch: Börsenpreis plus Aufschläge | Börsenpreis-Sensor; Netzentgelt, Steuern/Abgaben, Anbieteraufschlag (je ct/kWh netto); Mehrwertsteuer (%) |

Jeder Tarif hat einen optionalen Grundpreis (pro Monat oder pro Jahr) und den Schalter **Mein aktueller Tarif** – die anderen Tarife zeigen ihre Differenz zu diesem.

### Dynamischen Tarif anlegen

Nimm **Börsenpreis plus Aufschläge**. Nur damit kann Tarifwacht auch die Zeit vor der Einrichtung rechnen ([Rückblick](#rückblick-vor-der-einrichtung), [Statistik nachtragen](#statistik-nachtragen)) – die Börsenpreise von damals kommen von SMARD.de. Ein Sensor mit Gesamtpreis kennt nur die Zeit seit der Einrichtung.

Hast du in **EPEX Spot** einen Aufschlag und eine Steuer eingestellt, übernimm einfach diese Werte – dann rechnet der Tarif genau wie der Gesamtpreis von EPEX Spot:

| In EPEX Spot | In Tarifwacht |
|---|---|
| Sensor mit dem Marktpreis (Market Price) | Sensor mit Börsenpreis |
| Aufschlag absolut, z. B. 0,15 €/kWh | Anbieteraufschlag **15** ct/kWh (Tarifwacht rechnet in Cent: € × 100) |
| Steuer, z. B. 19 % | Mehrwertsteuer 19 % |

Netzentgelt sowie Steuern und Abgaben bleiben leer – sie stecken schon im Aufschlag. Geprüft für einen absoluten Aufschlag; einen prozentualen haben wir noch nicht nachgerechnet. Hast du die Preisblätter, kannst du den Aufschlag später aufteilen (*Tarif bearbeiten*).

### Tarif ändern

Beim Tarif auf das Zahnrad (*Konfigurieren*):

- **Tarif bearbeiten:** Name, aktueller Tarif und Preise **ab Beginn** – für Tippfehler und Korrekturen. Tarifwacht rechnet den ganzen Zeitraum neu.
- **Preisänderung ab einem Datum hinzufügen:** neue Preise ab Mitternacht dieses Tages (deutsche Ortszeit), z. B. eine Preiserhöhung des Anbieters oder neue Netzentgelte. Davor bleiben die bisherigen Preise. Das Formular ist mit den heute gültigen Preisen vorausgefüllt.
- **Preisänderung entfernen:** danach gelten wieder die Preise davor.
- **Modul 3** (nur bei „Börsenpreis plus Aufschläge“), siehe unten.

Mehrere Zähler: je einen Eintrag anlegen. Name oder Zähler ändern: *Tarifwacht → ⋮ → Neu konfigurieren*.

### Modul 3 (§ 14a EnWG)

Mit einer steuerbaren Verbrauchseinrichtung (Wärmepumpe, Wallbox) kannst du beim Netzbetreiber Modul 3 wählen: ein Netzentgelt, das von der Uhrzeit abhängt. Ob sich das lohnt, zeigt ein zweiter Tarif mit denselben Preisen und eingeschaltetem Modul 3.

<img alt="Modul 3 mit Niedrig- und Hochlastfenstern" src="https://raw.githubusercontent.com/tarifwacht/integration/main/assets/screenshots/modul3.png" width="480">

- **Stufen:** Niedriglast (NT) und Hochlast (HT) in ct/kWh netto; außerhalb der Fenster gilt das normale Netzentgelt des Tarifs (Standardstufe).
- **Quartale:** in welchen Quartalen die Fenster gelten; in den anderen gilt den ganzen Tag die Standardstufe.
- **Zeitfenster:** Ortszeit im Viertelstundenraster, mehrere mit Komma getrennt, auch über Mitternacht – z. B. `23:00-06:00` oder `01:45-06:15, 22:30-24:00`.
- Alle Werte stehen im Preisblatt deines Netzbetreibers. Ändern sie sich (meist zum Jahreswechsel), das neue Preisblatt als Preisänderung ab dem Stichtag eintragen.
- Modul 3 gilt für den **gesamten** Netzbezug der Marktlokation, nicht nur für Wärmepumpe oder Wallbox. Das passt, solange das Gerät nicht über einen eigenen Zähler läuft.

Grundlage: Festlegung der Bundesnetzagentur BK8-22/010-A; Einzelheiten und Quellen in [docs/ENTWICKLUNG.md](docs/ENTWICKLUNG.md).

## Entitäten

Am Gerät des Zählers (z. B. „Haus“):

| Entität | Einheit | Bedeutung |
|---|---|---|
| Strombezug | kWh | erfasste Menge seit der Einrichtung – zum Abgleich mit deinem Zähler |
| Günstigster Tarif | Text | Tarif mit den niedrigsten Kosten gesamt; Attribut `ranking` mit allen Tarifen (fehlende Preise siehe unten) |

An jedem Tarif (z. B. „Haus Festpreis“):

| Entität | Einheit | Bedeutung |
|---|---|---|
| Verbrauchskosten | € | Strombezug × Preis der jeweiligen Viertelstunde |
| Kosten gesamt | € | Verbrauchskosten plus Grundpreis |
| Durchschnittspreis | ct/kWh | Kosten gesamt ÷ Strombezug |
| Differenz zum aktuellen Tarif | € | Kosten gesamt minus Kosten des aktuellen Tarifs (fehlt beim aktuellen Tarif selbst; fehlende Preise siehe unten) |

Bei dynamischen Tarifen wartet der Verbrauch einer Viertelstunde bis zu 24 Stunden auf seinen Preis; meist ist er schon seit dem Vortag bekannt.

## Dashboard: Tarifvergleich

Tages-, Monats- und Jahreswerte liefert die Langzeitstatistik – eigene Zähler braucht es nicht. Ein fertiger Abschnitt für eine Sektionen-Ansicht: günstigster Tarif, Durchschnittspreise, Kosten heute und im Monat, die Differenz und ein Balkendiagramm je Tag. Am Desktop stehen vier Karten nebeneinander, am Handy zwei. *Dashboard bearbeiten → Abschnitt hinzufügen → ⋮ → Im Code-Editor bearbeiten*; die Entitäts-IDs hängen von deinen Namen ab (hier Zähler „Haus“, Tarife „Festpreis“ und „Dynamisch“):

```yaml
type: grid
column_span: 2
cards:
  - type: heading
    heading: Tarifvergleich
    icon: mdi:scale-balance
  - type: tile
    entity: sensor.haus_gunstigster_tarif
    name: Günstigster Tarif
    grid_options: {columns: 12}
  - type: tile
    entity: sensor.haus_festpreis_durchschnittspreis
    name: Ø Festpreis
    grid_options: {columns: 6}
  - type: tile
    entity: sensor.haus_dynamisch_durchschnittspreis
    name: Ø Dynamisch
    grid_options: {columns: 6}
  - type: statistic
    entity: sensor.haus_festpreis_kosten_gesamt
    name: Festpreis heute
    stat_type: change
    period: {calendar: {period: day}}
    grid_options: {columns: 6}
  - type: statistic
    entity: sensor.haus_dynamisch_kosten_gesamt
    name: Dynamisch heute
    stat_type: change
    period: {calendar: {period: day}}
    grid_options: {columns: 6}
  - type: statistic
    entity: sensor.haus_festpreis_kosten_gesamt
    name: Festpreis Monat
    stat_type: change
    period: {calendar: {period: month}}
    grid_options: {columns: 6}
  - type: statistic
    entity: sensor.haus_dynamisch_kosten_gesamt
    name: Dynamisch Monat
    stat_type: change
    period: {calendar: {period: month}}
    grid_options: {columns: 6}
  - type: statistic
    entity: sensor.haus_dynamisch_differenz_zum_aktuellen_tarif
    name: Differenz heute
    stat_type: change
    period: {calendar: {period: day}}
    grid_options: {columns: 12}
  - type: statistic
    entity: sensor.haus_dynamisch_differenz_zum_aktuellen_tarif
    name: Differenz Monat
    stat_type: change
    period: {calendar: {period: month}}
    grid_options: {columns: 12}
  - type: heading
    heading_style: subtitle
    heading: "Differenz positiv: dynamisch wäre teurer gewesen"
  - type: statistics-graph
    title: Kosten je Tag
    chart_type: bar
    period: day
    days_to_show: 30
    stat_types: [change]
    entities:
      - entity: sensor.haus_festpreis_kosten_gesamt
        name: Festpreis
      - entity: sensor.haus_dynamisch_kosten_gesamt
        name: Dynamisch
    grid_options: {columns: full}
```

Für einen Jahresüberblick im Diagramm `period: month` und `days_to_show: 365`. Mit [Statistik nachtragen](#statistik-nachtragen) zeigen die Karten auch die Zeit vor der Einrichtung.

## Vergleich für einen Zeitraum

*Einstellungen → Werkzeuge → Aktionen* (früher *Entwicklerwerkzeuge → Aktionen*) → **Tarife vergleichen**, Zähler und Zeitraum wählen, „Antwort anzeigen“:

```yaml
action: tarifwacht.compare
data:
  config_entry: <Eintrag auswählen>
  start: "2026-11-01 00:00:00"
  end: "2026-12-01 00:00:00"
```

<img alt="Antwort der Aktion „Tarife vergleichen“" src="https://raw.githubusercontent.com/tarifwacht/integration/main/assets/screenshots/vergleich.png" width="640">

Die Antwort enthält Strombezug und Anzahl der Viertelstunden im Zeitraum, den günstigsten Tarif und je Tarif – günstigster zuerst – die Kosten gesamt, Verbrauchs- und Grundpreiskosten, den Durchschnittspreis und die Differenz zum aktuellen Tarif; unter `months` dasselbe kürzer je Kalendermonat. Ohne Beginn bzw. Ende: seit der Einrichtung bzw. bis jetzt. Zeiten ohne Zeitzone gelten als Ortszeit deines Home Assistant.

### Rückblick vor der Einrichtung

Liegt der Beginn vor der Einrichtung, rechnet Tarifwacht diese Zeit nach:

- **Verbrauch:** aus der Langzeitstatistik deines Bezugszählers. Sie hat Stundenwerte; jede Stunde wird gleichmäßig auf ihre vier Viertelstunden verteilt. Für einen Festpreis ist das exakt, bei dynamischen Preisen eine gute Näherung (seit 1. Oktober 2025 wechselt der Börsenpreis jede Viertelstunde).
- **Börsenpreise:** von [SMARD.de](https://www.smard.de) (Bundesnetzagentur), Day-Ahead DE-LU – dieselben Preise wie der Marktpreis von EPEX Spot. Tarifwacht lädt sie beim ersten Vergleich einer Zeit (je Woche eine Anfrage, ein Jahr dauert etwa eine halbe Minute) und speichert sie; danach geht es ohne Abruf.
- **Welche Tarife:** Festpreis und „Börsenpreis plus Aufschläge“ (auch mit Modul 3 und Preisänderungen). Ein **Sensor mit Gesamtpreis** kennt nur die Zeit seit der Einrichtung – solche Tarife stehen dann mit `energy_without_price_kwh` am Ende, zählen nicht als günstigster und haben keine Differenz zum aktuellen Tarif (`null`), weil sie sonst günstiger aussähen, als sie sind. Tipp: den dynamischen Tarif als „Börsenpreis plus Aufschläge“ anlegen, siehe [Dynamischen Tarif anlegen](#dynamischen-tarif-anlegen).
- Unter `estimate` steht, bis wann geschätzt wurde, wie viel Energie das war und wie viele Stunden in der Statistik fehlen (z. B. weil es den Zähler noch nicht gab); dazu die Quellenangabe von SMARD.de, falls Börsenpreise von dort nötig waren.
- Preise und Grundpreise gelten so, wie der Tarif heute eingetragen ist (mit seinen Preisänderungen). Für einen Vergleich über einen Jahreswechsel die alten Preise als Preisänderung eintragen, z. B. die Netzentgelte des Vorjahres.

Die Antwort lässt sich auch in Skripten und Automationen verwenden (`response_variable`) – fertig als Blueprint:

| Blueprint | Was er tut | |
| --- | --- | --- |
| **Monatsübersicht** | schickt am Ersten jedes Monats Strombezug, Kosten jedes Tarifs, Differenz zum aktuellen Tarif und den günstigsten Tarif des Vormonats – als Benachrichtigung in Home Assistant oder mit einer eigenen Aktion (z. B. ans Handy) | [![Blueprint importieren](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Ftarifwacht%2Fintegration%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Ftarifwacht%2Fmonatsuebersicht.yaml) |

## Statistik nachtragen

Die Sensoren haben Langzeitstatistik erst ab der Einrichtung. Damit Statistik-Karten und Diagramme (z. B. der [Tarifvergleich](#dashboard-tarifvergleich)) auch die Zeit davor zeigen, gibt es die Aktion **Tarifwacht: Statistik nachtragen** (*Einstellungen → Werkzeuge → Aktionen*, früher *Entwicklerwerkzeuge → Aktionen*):

```yaml
action: tarifwacht.import_statistics
data:
  config_entry: <Zähler auswählen>
  start: "2026-01-01"
```

- Sie rechnet wie der [Rückblick](#rückblick-vor-der-einrichtung) und schreibt die Stunden **vor** dem ersten vorhandenen Statistikwert in die Langzeitstatistik von Strombezug, Verbrauchskosten, Kosten gesamt und Differenz; die späteren Summen werden passend verschoben. Ein später hinzugefügter Tarif bekommt so auch die Zeit seit der Einrichtung.
- Der Beginn muss vor der Einrichtung liegen; früher als die Langzeitstatistik deines Zählers geht es nicht (die Antwort nennt den tatsächlichen Beginn).
- Ein Tarif, dem im Zeitraum Preise fehlen – etwa ein **Sensor mit Gesamtpreis** –, wird ganz übersprungen und unter `skipped` genannt: lieber keine Vergangenheit als eine mit Lücken.
- Nachgetragene Stunden bleiben, wie sie geschrieben wurden: Korrigierst du später Preise eines Tarifs, rechnen Sensoren und Aktion neu, die nachgetragene Statistik nicht. Dafür die Statistik der Sensoren dieses Tarifs löschen (*Werkzeuge → Statistik*) und erneut nachtragen.
- **Das greift in die Statistik-Datenbank ein – vorher ein Backup anlegen.** Ein zweiter Aufruf findet nichts mehr nachzutragen.

## Datenschutz

Tarifwacht rechnet lokal und liest nur die Entitäten, die du auswählst. Einzige Ausnahme: Vergleichst du eine Zeit vor der Einrichtung, lädt Tarifwacht öffentliche Börsenpreise von SMARD.de. Dabei wird nichts über dich übertragen – nur der Abruf der Preisdateien mit der Kennung `Tarifwacht/<Version>`. Die Diagnose-Datei enthält deine Tarifeinstellungen (Preise, Sensoren), aber weder Namen noch Zählerstände, Energie- oder Kostensummen.

## Was Tarifwacht nicht kann

- **Keine Abrechnung:** Abweichungen zur Rechnung sind normal (anderer Zähler, Rundung, Abschläge).
- **Kein verändertes Verhalten:** Der Vergleich rechnet deinen tatsächlichen Verbrauch – was du mit einem dynamischen Tarif verschieben würdest, sieht er nicht.
- **Sensoren beginnen bei der Einrichtung:** Die Zeit davor gibt es über die Aktion „Tarife vergleichen“ und – für Statistik-Karten – über [Statistik nachtragen](#statistik-nachtragen).
- **Keine Netzeinspeisung:** Tarifwacht rechnet nur den Bezug. Für die Einspeisung gibt es das Schwesterprojekt [Einspeisewacht](https://github.com/einspeisewacht/integration).
- **Module 1 und 2** nach § 14a EnWG bildet Tarifwacht nicht eigens ab.

## Fehlerbehebung

Tarifwacht meldet Probleme unter *Einstellungen → Reparaturen*:

- **Preissensor mit nicht unterstützter Einheit:** Der Sensor liefert z. B. ct/kWh oder €/MWh. Tarifwacht braucht €/kWh und ignoriert seine Preise bis dahin.
- **Zähler mit nicht unterstützter Einheit:** Tarifwacht bucht nichts, bis der Zähler Wh, kWh oder MWh liefert.
- **Preise fehlen:** Für eine vergangene Viertelstunde fehlt der Preis, vermutlich ist die Preis-Integration ausgefallen. Nach 24 Stunden wird der Verbrauch ohne Preis gezählt – nie als kostenlos. Damit der betroffene Tarif nicht günstiger aussieht, lassen „Differenz zum aktuellen Tarif“ und „Günstigster Tarif“ solche Viertelstunden für alle Tarife aus; wie viel Strom das war, steht im Attribut `energy_left_out_kwh`.

Weiteres:

- **Werte bleiben bei 0:** Liefert der Bezugszähler Werte? „Strombezug“ sollte mit deinem Zähler mitwachsen.
- **Dynamische Kosten hinken hinterher:** Eine Viertelstunde wird erst gebucht, wenn ihr Preis bekannt ist. Mit Prognose ist das sofort der Fall; sonst siehe „Preise fehlen“.
- **Diagnose:** *Tarifwacht → Eintrag → ⋮ → Diagnosedaten herunterladen*. **Debug-Protokoll:** *Tarifwacht → ⋮ → Debug-Protokoll aktivieren*.

**Update von 0.1.0b1:** Die beiden Tarife werden zu eigenen Tarif-Einträgen, der Verbrauch seit der Einrichtung wird einmalig aus dem Verlauf (Recorder) nachgelesen. Die Sensoren behalten ihre Entitäts-IDs; „Mehrkosten dynamisch“ heißt jetzt „Differenz zum aktuellen Tarif“.

## Entfernen

1. *Einstellungen → Geräte & Dienste → Tarifwacht* → bei jedem Eintrag ⋮ → *Löschen*. Die gespeicherten Viertelstunden dieses Eintrags werden mit gelöscht.
2. Optional: HACS → Tarifwacht → ⋮ → *Entfernen*, dann Home Assistant neu starten.

Die Langzeitstatistik der gelöschten Sensoren bleibt in Home Assistant erhalten, bis du sie unter *Einstellungen → Werkzeuge → Statistik* (früher *Entwicklerwerkzeuge*) entfernst.

## Fehler melden

Bitte als [Issue](https://github.com/tarifwacht/integration/issues) – am besten mit Diagnose-Datei und den Versionen von Home Assistant und Tarifwacht. Sicherheitslücken bitte vertraulich, siehe [SECURITY.md](SECURITY.md).

## Danke

Die Idee, den eigenen Verbrauch in Home Assistant direkt gegen beide Tarife zu rechnen, stammt aus [tariff_compare](https://github.com/fischit87/tariff_compare) von fischit87.

## Lizenz

MIT. Historische Börsenpreise (nur für Vergleiche vor der Einrichtung): Bundesnetzagentur | [SMARD.de](https://www.smard.de), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Die Bilder in diesem README zeigen einen Demo-Eintrag mit erfundenem Verbrauch und erfundenen Preisen.
