# Tarifwacht

**Was hätte dein Strom mit einem anderen Tarif gekostet?**
Tarifwacht ist eine Home-Assistant-Integration, die deinen tatsächlichen Strombezug Viertelstunde für Viertelstunde gegen zwei Tarife rechnet – Festpreis und dynamisch – und zeigt, welcher günstiger gewesen wäre.

> **Beta.** Tarifwacht ist neu und wird gerade erprobt. Rückmeldungen gern als [Issue](https://github.com/tarifwacht/integration/issues).

## Was Tarifwacht kann

- **Kosten je Tarif** (€): Verbrauchskosten und Kosten gesamt (mit Grundpreis) für Festpreis und dynamischen Tarif – für Energie-Dashboard und Langzeitstatistik.
- **Mehrkosten dynamisch** (€): dynamisch minus Festpreis. Positiv heißt: Der dynamische Tarif wäre teurer gewesen; negativ: günstiger.
- **Strombezug** (kWh): die erfasste Menge, zum Abgleich mit deinem Zähler.
- Bucht an Viertelstundengrenzen exakt: Ein Zählerdelta wird zeitanteilig auf die Viertelstunden verteilt, jede mit dem Preis **genau dieser Viertelstunde** aus der Prognose.
- Fällt der Zähler aus oder startet Home Assistant neu, wird der Verbrauch der Lücke nachgebucht statt verloren. Fehlt ein Preis, rechnet Tarifwacht nie mit 0 €.
- **Grundpreise** optional, tageweise anteilig (Monatspreis ÷ Tage des Monats).
- Erkennt Zähler-Resets und unplausible Sprünge und bucht sie nicht. Der Stand übersteht Neustarts.
- Rein lokal: liest nur vorhandene Entitäten, keine Cloud.

Zeiträume (Tag, Woche, Monat, Jahr) zeigen die Statistik-Karte oder das Energie-Dashboard – eigene Tages- oder Monatszähler braucht es nicht.

## Hinweise zum Vergleich

- Der Vergleich unterstellt das **gleiche Verbrauchsverhalten**. Mit einem dynamischen Tarif verschieben viele ihren Verbrauch in günstige Stunden – das kann der Vergleich nicht abbilden.
- Erfasse **alle Preisbestandteile auf beiden Seiten** gleich, sonst ist der Vergleich verzerrt. Der Gesamtpreis eines dynamischen Tarifs ist Börsenpreis plus Netzentgelt, Konzessionsabgabe, Umlagen, Stromsteuer und Anbieteraufschlag, dazu Mehrwertsteuer. Die Werte stehen in den Preisblättern von Anbieter und Netzbetreiber.
- Die Werte sind eine Orientierung. Maßgeblich ist die Abrechnung deines Stromanbieters.

## Voraussetzungen

- Home Assistant 2026.3 oder neuer.
- Ein **Bezugszähler**: fortlaufender Energiesensor (Wh, kWh oder MWh) für den Strom aus dem Netz, am besten der Zähler am Netzanschlusspunkt.
- Ein **Preissensor mit dem Gesamtpreis** des dynamischen Tarifs in €/kWh, am besten mit Prognose je Viertelstunde – z. B. der Gesamtpreis (`…_total_price`) der Integration [EPEX Spot](https://github.com/mampfes/ha_epex_spot). Dort lassen sich Aufschlag und Steuersatz einstellen.

## Installation

1. HACS → ⋮ → *Benutzerdefinierte Repositories* → `https://github.com/tarifwacht/integration`, Typ *Integration*.
2. Tarifwacht suchen und herunterladen. Home Assistant neu starten.
3. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Tarifwacht*.

## Einrichtung

1. **Bezugszähler:** Name und Zähler.
2. **Tarife:** Arbeitspreis des Festpreistarifs (ct/kWh, brutto), Sensor mit dem Gesamtpreis des dynamischen Tarifs, für beide optional der Grundpreis pro Monat.

Mehrere Zähler: je einen Eintrag anlegen. Ändern: *Tarifwacht → ⋮ → Neu konfigurieren* – neue Preise gelten ab dann, Bisheriges bleibt gebucht.

## Danke

Die Idee, den eigenen Verbrauch in Home Assistant direkt gegen beide Tarife zu rechnen, stammt aus [tariff_compare](https://github.com/fischit87/tariff_compare) von fischit87.

## Lizenz

MIT
