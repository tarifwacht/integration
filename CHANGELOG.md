# Changelog

## Unveröffentlicht

- **Statistik nachtragen** (neue Aktion `tarifwacht.import_statistics`): schreibt die Stunden vor der ersten Langzeitstatistik der Sensoren – Strombezug, Verbrauchskosten, Kosten gesamt und Differenz – so dass Statistik-Karten und Diagramme auch die Zeit vor der Einrichtung zeigen. Gerechnet wird wie beim Rückblick; die späteren Summen werden passend verschoben. Ein Tarif, dem im Zeitraum Preise fehlen (z. B. ein Gesamtpreis-Sensor), wird ganz übersprungen. Vorher ein Backup anlegen.

## 0.1.0b6 – 2026-10-27

- **Tarife vergleichen:** Ein Tarif, dem für einen Teil des Zeitraums Preise fehlen (z. B. ein Gesamtpreis-Sensor im Rückblick vor der Einrichtung), hat keine Differenz zum aktuellen Tarif mehr (`null`). Bisher stand dort die Differenz der unvollständigen Kosten – der Tarif sah um Hunderte Euro günstiger aus. Ebenso, wenn dem aktuellen Tarif selbst Preise fehlen.
- **Differenz zum aktuellen Tarif und Günstigster Tarif (Sensoren):** Fehlt einem Tarif dauerhaft der Preis einer Viertelstunde (Preis-Integration länger als 24 Stunden ausgefallen), lassen beide diese Viertelstunde jetzt für alle Tarife aus. Bisher fehlte sie nur beim betroffenen Tarif, der dadurch dauerhaft günstiger aussah. Die ausgelassene Energie steht im Attribut `energy_left_out_kwh`. Ohne Preisausfall ändert sich nichts.
- **Tarife vergleichen:** Die Quellenangabe von SMARD.de (`estimate.exchange_prices`) steht nur noch in der Antwort, wenn Börsenpreise von dort gebraucht wurden.
- **Preisänderung hinzufügen:** Das Formular schlägt die heute gültigen Werte jetzt nach deutscher Zeit vor, wie die Preisänderungen selbst gelten. Bisher zählte das Datum in der Zeitzone von Home Assistant – das wich nur bei einer anderen Zeitzone und nur rund um Mitternacht ab.
- README: Die Bilder der Geräteseite eines Tarifs und der Antwort von „Tarife vergleichen“ sind wieder da (Demo-Eintrag mit erfundenen Werten).
- Intern: wöchentlicher Quellen-Check (`tools/source_check.py`, Workflow „Quellen-Check“, montags): lädt Index und die beiden neuesten Wochen von SMARD.de mit dem echten Parser und prüft Format, Aktualität, Viertelstundenraster und Preisspanne – die Schnittstelle ist nicht offiziell dokumentiert. Bei Problemen öffnet er ein Issue mit Label `quellen-check` und schließt es wieder, sobald alles geht.
- Intern: Entwicklungs- und Testumgebung auf Home Assistant 2026.10.4 angehoben (Testbibliothek 0.13.375), wie bei Streckenwacht.

## 0.1.0b5 – 2026-10-26

- **Rückblick vor der Einrichtung:** Die Aktion „Tarife vergleichen“ rechnet auch Zeiträume vor der Einrichtung – mit den Stundenwerten deines Zählers aus der Langzeitstatistik und historischen Börsenpreisen von SMARD.de (Bundesnetzagentur, nur bei Tarifen „Börsenpreis plus Aufschläge“; einmal geladen, dann gespeichert). Tarife mit Gesamtpreis-Sensor lassen sich für diese Zeit nicht berechnen und werden entsprechend markiert.
- Die Antwort der Aktion schlüsselt jetzt nach Monaten auf (`months`) und zeigt unter `estimate`, was geschätzt ist. Als günstigster gilt nur ein Tarif, der jede kWh bepreisen konnte.
- **Preissensoren ohne Prognose:** Ihr aktueller Wert gilt jetzt für jede Viertelstunde, bis er sich ändert. Bisher bekam nur die Viertelstunde einen Preis, in der sich der Wert änderte – bei einem stündlich wechselnden Preis blieben drei von vier Viertelstunden ohne Preis.
- README überarbeitet und auf Englisch (`README.en.md`): Preisänderungen, Modul 3, Preisquellen, Aktion „Tarife vergleichen“, Dashboard-Beispiel, Reparaturen, Datenschutz, Entfernen; Bilder mit einem Demo-Eintrag.

## 0.1.0b4 – 2026-10-26

- **Aktion „Tarife vergleichen“** (`tarifwacht.compare`): Kosten aller Tarife in einem frei wählbaren Zeitraum, der günstigste zuerst – mit Verbrauchs- und Grundpreisanteil, Durchschnittspreis und Differenz zum aktuellen Tarif.
- **Preisänderungen ab einem Datum:** Tarif → *Neu konfigurieren* → *Preisänderung hinzufügen* (z. B. neuer Arbeitspreis oder neue Netzentgelte ab 1. Januar). Davor gelten die bisherigen Preise; der Grundpreis wird am Wechseltag aufgeteilt.
- **Icons** für alle Sensoren und die Aktion.
- **Modul 3 (§ 14a EnWG):** zeitvariables Netzentgelt für Tarife „Börsenpreis plus Aufschläge“ – Niedriglast- und Hochlastfenster, Quartale und Preise aus dem Preisblatt des Netzbetreibers; neue Preisblätter als Preisänderung ab einem Datum.
- **Weitere Preisquellen (experimentell):** Nord Pool (HACS-Integration `custom-components/nordpool`, Attribute `raw_today`/`raw_tomorrow`) und ENTSO-E (HACS-Integration `JaccoR/hass-entso-e`, Durchschnittspreis-Sensor mit `prices`). Die Diagnose zeigt jetzt den Aufbau der Preis-Attribute (ohne Werte), damit weitere Quellen ergänzt werden können.
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
