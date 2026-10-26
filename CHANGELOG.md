# Changelog

## Unveröffentlicht

- **Aktion „Tarife vergleichen“** (`tarifwacht.compare`): Kosten aller Tarife in einem frei wählbaren Zeitraum, der günstigste zuerst – mit Verbrauchs- und Grundpreisanteil, Durchschnittspreis und Differenz zum aktuellen Tarif.
- **Preisänderungen ab einem Datum:** Tarif → *Neu konfigurieren* → *Preisänderung hinzufügen* (z. B. neuer Arbeitspreis oder neue Netzentgelte ab 1. Januar). Davor gelten die bisherigen Preise; der Grundpreis wird am Wechseltag aufgeteilt.
- **Hinweise unter Reparaturen:** Preissensor oder Zähler mit falscher Einheit, überfällige Preise, fehlgeschlagenes Nachlesen aus dem Recorder. Sie verschwinden, sobald die Ursache behoben ist.

## 0.1.0b3 – 2026-10-26

- Icon und Logo (Verkehrspurpur, Viertelstunden gegen den Festpreis); Home Assistant zeigt sie ab 2026.3.
- **Schont SD-Karten:** Abgeschlossene Tage wandern einmal am Tag in ein Jahresarchiv; die laufende Datei bleibt wenige KB groß und wird nur noch jede Viertelstunde geschrieben statt bei jeder Zähleränderung. Sensoren aktualisieren sich höchstens einmal pro Minute (weniger Recorder-Einträge); die Rangfolge von „Günstigster Tarif“ wird nicht aufgezeichnet.

## 0.1.0b2 – 2026-10-26

- Verbrauch und Preise werden je Viertelstunde für den ganzen Zeitraum gespeichert; die Kosten jedes Tarifs werden daraus berechnet. Geänderte Preise (z. B. ein korrigierter Aufschlag oder ein nachgetragener Grundpreis) gelten damit rückwirkend ab der Einrichtung.
- Update von 0.1.0b1: Der Verbrauch seit der Einrichtung wird einmalig aus dem Recorder nachgelesen – es geht nichts verloren.
- **Beliebig viele Tarife:** *Tarifwacht → Tarif hinzufügen* – Festpreis, dynamisch mit Gesamtpreis-Sensor oder dynamisch aus Börsenpreis plus Netzentgelt, Steuern/Abgaben/Umlagen, Anbieteraufschlag und MwSt. Jeder Tarif lässt sich einzeln ändern; neue und geänderte Tarife gelten ab der Einrichtung.
- **Mein aktueller Tarif:** Die anderen Tarife zeigen ihre Differenz dazu (ersetzt „Mehrkosten dynamisch“, Verlauf bleibt erhalten).
- **Neue Sensoren:** Durchschnittspreis je Tarif (ct/kWh), Günstigster Tarif.
- **Grundpreis** wahlweise pro Monat oder pro Jahr.
- Jeder Tarif ist ein eigenes Gerät; die Sensoren aus 0.1.0b1 behalten ihre Entitäts-IDs.

## 0.1.0b1 – 2026-10-26

Erste Vorab-Version (MVP) zum Testen.

- **Einrichtung** in der Oberfläche: Bezugszähler (Wh, kWh oder MWh, fortlaufend), Festpreis (ct/kWh) und Sensor mit dem Gesamtpreis des dynamischen Tarifs (€/kWh), je Tarif ein optionaler Grundpreis (€/Monat). Nachträglich änderbar (*Neu konfigurieren*).
- **Sensoren:** Strombezug (kWh), je Tarif Verbrauchskosten und Kosten gesamt, Mehrkosten dynamisch (positiv = dynamisch teurer).
- Jedes Zählerdelta wird zeitanteilig auf die Viertelstunden verteilt; der dynamische Tarif bewertet jedes Stück mit dem Preis seiner Viertelstunde aus der Prognose. Lücken (Zähler nicht verfügbar, Neustart) werden nachgebucht statt verloren.
- Grundpreis tageweise anteilig (Monatspreis ÷ Tage des Monats), auch für Zeiten, in denen Home Assistant aus war.
- Fehlt ein Preis, wird nie mit 0 € gerechnet: die Menge wartet bis zu 24 h auf den Preis. Preissensoren mit anderer Einheit als €/kWh werden abgelehnt. Zähler-Resets und unplausible Sprünge werden nicht gebucht; Stand übersteht Neustarts; Diagnose ohne personenbezogene Daten.
- Projektstart: Repository-Gerüst, CI (Tests, hassfest, HACS, Kompatibilität mit HA 2026.3), Release-ZIP-Workflow; Buchungskern aus der Einspeisewacht übernommen.
