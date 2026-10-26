<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/tarifwacht/integration/main/assets/github/readme-header-dark@2x.png">
  <img alt="Tarifwacht – Jeder Tarif. Jede Viertelstunde." src="https://raw.githubusercontent.com/tarifwacht/integration/main/assets/github/readme-header-light@2x.png" width="640">
</picture>

[![Release](https://img.shields.io/github/v/release/tarifwacht/integration?color=96497D)](https://github.com/tarifwacht/integration/releases)
[![CI](https://github.com/tarifwacht/integration/actions/workflows/ci.yml/badge.svg)](https://github.com/tarifwacht/integration/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-F5A623.svg)](LICENSE)

**Was hätte dein Strom mit einem anderen Tarif gekostet?**
Tarifwacht ist eine Home-Assistant-Integration, die deinen tatsächlichen Strombezug Viertelstunde für Viertelstunde gegen beliebig viele Tarife rechnet – Festpreis und dynamisch – und zeigt, welcher günstiger gewesen wäre.

> **Beta.** Tarifwacht ist neu und wird gerade erprobt. Rückmeldungen gern als [Issue](https://github.com/tarifwacht/integration/issues).

## Was Tarifwacht kann

- **Kosten je Tarif** (€): Verbrauchskosten und Kosten gesamt (mit Grundpreis) – für Energie-Dashboard und Langzeitstatistik.
- **Differenz zum aktuellen Tarif** (€) für jeden anderen Tarif. Positiv heißt: Dieser Tarif wäre teurer gewesen; negativ: günstiger.
- **Durchschnittspreis** je Tarif (ct/kWh, mit Grundpreis) und **Günstigster Tarif** bisher.
- **Strombezug** (kWh): die erfasste Menge, zum Abgleich mit deinem Zähler.
- **Beliebig viele Tarife:** Festpreis, dynamisch mit einem Gesamtpreis-Sensor oder dynamisch aus Börsenpreis plus Netzentgelt, Steuern/Abgaben/Umlagen, Anbieteraufschlag und Mehrwertsteuer.
- Bucht an Viertelstundengrenzen exakt: Ein Zählerdelta wird zeitanteilig auf die Viertelstunden verteilt, jede mit dem Preis **genau dieser Viertelstunde** aus der Prognose.
- **Rechnet jeden Tarif ab der Einrichtung:** Verbrauch und Preise werden je Viertelstunde gespeichert. Ein später hinzugefügter oder geänderter Tarif (z. B. ein korrigierter Aufschlag) gilt deshalb für den ganzen Zeitraum.
- Fällt der Zähler aus oder startet Home Assistant neu, wird der Verbrauch der Lücke nachgebucht statt verloren. Fehlt ein Preis, rechnet Tarifwacht nie mit 0 €.
- **Grundpreise** optional, pro Monat oder pro Jahr, tageweise anteilig.
- Erkennt Zähler-Resets und unplausible Sprünge und bucht sie nicht.
- Rein lokal: liest nur vorhandene Entitäten, keine Cloud.

Zeiträume (Tag, Woche, Monat, Jahr) zeigen die Statistik-Karte oder das Energie-Dashboard – eigene Tages- oder Monatszähler braucht es nicht.

## Hinweise zum Vergleich

- Der Vergleich unterstellt das **gleiche Verbrauchsverhalten**. Mit einem dynamischen Tarif verschieben viele ihren Verbrauch in günstige Stunden – das kann der Vergleich nicht abbilden.
- Erfasse **alle Preisbestandteile auf beiden Seiten** gleich, sonst ist der Vergleich verzerrt. Der Gesamtpreis eines dynamischen Tarifs ist Börsenpreis plus Netzentgelt, Konzessionsabgabe, Umlagen, Stromsteuer und Anbieteraufschlag, dazu Mehrwertsteuer. Die Werte stehen in den Preisblättern von Anbieter und Netzbetreiber.
- Die Werte sind eine Orientierung. Maßgeblich ist die Abrechnung deines Stromanbieters.

## Voraussetzungen

- Home Assistant 2026.3 oder neuer.
- Ein **Bezugszähler**: fortlaufender Energiesensor (Wh, kWh oder MWh) für den Strom aus dem Netz, am besten der Zähler am Netzanschlusspunkt.
- Für dynamische Tarife ein **Preissensor** in €/kWh, am besten mit Prognose je Viertelstunde – z. B. aus der Integration [EPEX Spot](https://github.com/mampfes/ha_epex_spot): der Gesamtpreis (`…_total_price`) oder der Börsenpreis (`…_market_price`), zu dem Tarifwacht die Aufschläge selbst addiert.

## Installation

1. HACS → ⋮ → *Benutzerdefinierte Repositories* → `https://github.com/tarifwacht/integration`, Typ *Integration*.
2. Tarifwacht suchen und herunterladen. Home Assistant neu starten.
3. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Tarifwacht*.

## Einrichtung

1. **Bezugszähler:** Name und Zähler.
2. **Tarife:** Arbeitspreis eines Festpreistarifs (ct/kWh, brutto) und ein Sensor mit dem Gesamtpreis eines dynamischen Tarifs, für beide optional der Grundpreis pro Monat. Daraus entstehen die ersten beiden Tarife; der Festpreis ist „Mein aktueller Tarif“.

**Weitere Tarife:** *Tarifwacht → Tarif hinzufügen* und die Art wählen:

| Art | Eingaben |
|---|---|
| Festpreis | Arbeitspreis (ct/kWh, brutto) |
| Dynamisch: Gesamtpreis-Sensor | Sensor, der schon alle Bestandteile enthält |
| Dynamisch: Börsenpreis plus Aufschläge | Börsenpreis-Sensor; Netzentgelt, Steuern/Abgaben/Umlagen, Anbieteraufschlag (je ct/kWh netto); Mehrwertsteuer (%) |

Jeder Tarif hat einen optionalen Grundpreis (pro Monat oder pro Jahr) und den Haken **Mein aktueller Tarif** – die anderen Tarife zeigen ihre Differenz zu diesem. Ändern: beim Tarif ⋮ → *Neu konfigurieren*; Tarifwacht rechnet dann den ganzen Zeitraum neu.

Mehrere Zähler: je einen Eintrag anlegen. Name oder Zähler ändern: *Tarifwacht → ⋮ → Neu konfigurieren*.

**Update von 0.1.0b1:** Die beiden Tarife werden zu eigenen Tarif-Einträgen, der Verbrauch seit der Einrichtung wird einmalig aus dem Verlauf (Recorder) nachgelesen. Die Sensoren behalten ihre Entitäts-IDs; „Mehrkosten dynamisch“ heißt jetzt „Differenz zum aktuellen Tarif“.

## Danke

Die Idee, den eigenen Verbrauch in Home Assistant direkt gegen beide Tarife zu rechnen, stammt aus [tariff_compare](https://github.com/fischit87/tariff_compare) von fischit87.

## Lizenz

MIT
