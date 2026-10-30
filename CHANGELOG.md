# Changelog

## 0.1.2 – 2026-10-30

- **Umbenannte Entitäten:** Wer den Bezugszähler oder einen Preissensor umbenennt (Entity-ID geändert, auch über „Entity-IDs neu erstellen“ am Gerät), muss nichts mehr tun. Tarifwacht zieht die neue ID selbst nach und lädt den Eintrag kurz danach neu. Bisher buchte Tarifwacht nach dem Umbenennen des Zählers still nichts mehr; nach dem Umbenennen eines Preissensors kam „Preise fehlen“, und wählte man den neuen Sensor unter *Neu konfigurieren*, gingen die gespeicherten Preise verloren – „Differenz zum aktuellen Tarif“ und „Günstigster Tarif“ verglichen dann nur noch die letzten Tage. Jetzt gehen die gespeicherten Preise und der letzte Zählerstand mit, auch wenn der Eintrag beim Umbenennen gerade nicht geladen war (dann beim nächsten Start). War gerade „Neu konfigurieren“ offen, bleibt beim Speichern die neue ID.
- **Einrichtung:** Das Feld „Arbeitspreis“ ist anfangs leer statt „0“ (0 wurde ohnehin abgewiesen).
- **Neuer Reparaturhinweis „Entität fehlt“:** Gibt es den Zähler oder einen Preissensor zehn Minuten nach dem Start nicht mehr (gelöscht, durch ein neues Gerät ersetzt), meldet Tarifwacht das unter *Einstellungen → Reparaturen*, statt still nichts zu buchen.
- **Modul 3 bleibt beim Bearbeiten erhalten:** „Tarif bearbeiten“ hat ein eingetragenes zeitvariables Netzentgelt (Modul 3) beim Speichern verworfen. Jetzt bleibt es, wie die Preisänderungen.
- **Später hinzugefügter dynamischer Tarif rechnet wieder ab der Einrichtung:** Kam ein dynamischer Tarif nach der Einrichtung dazu oder bekam er einen anderen Preissensor, fehlten ihm die Preise der Zeit davor – der neue Sensor kannte sie nicht. „Differenz zum aktuellen Tarif“ und „Günstigster Tarif“ verglichen deshalb erst ab dem Hinzufügen (der Rest stand in `energy_left_out_kwh`), die Grundpreise liefen dagegen ab der Einrichtung. Jetzt füllt Tarifwacht diese Zeit beim Laden im Hintergrund auf: bei einem Sensor mit Gesamtpreis aus seinem Verlauf im Recorder (rein lokal, meist die letzten 10 Tage), nie mit SMARD.de. Bei „Börsenpreis plus Aufschläge“ fragt das Formular beim Hinzufügen bzw. Ändern des Tarifs: „Zeit seit der Einrichtung mit Börsenpreisen von SMARD.de nachtragen“ (beim Hinzufügen vorausgewählt). Nur mit diesem Haken lädt Tarifwacht die Börsenpreise einmal von SMARD.de, danach aus dem Speicher; bestehende Tarife laden nichts, bis du den Haken setzt. Was sich nicht füllen lässt, bleibt wie bisher außen vor und steht in `energy_left_out_kwh`. Ein Preis aus dem Verlauf gilt nie über einen Neustart von Home Assistant hinweg – in der Zeit, in der Home Assistant aus war, kann er sich geändert haben. Schon geladene Börsenpreise von SMARD.de gelten nach einem Neustart sofort, die Sensoren springen also nicht kurz auf andere Werte. Die Aktionen „Tarife vergleichen“ und „Statistik nachtragen“ rechnen genauso.
- **Bezugszähler getauscht:** Wählt man in der Neukonfiguration einen anderen Zähler, buchte Tarifwacht dessen ersten Wert gegen den letzten Stand des alten Zählers (ein Phantom-Verbrauch, wenn der Unterschied plausibel klein war). Jetzt merkt sich der gespeicherte Stand seinen Zähler; der neue Zähler beginnt mit seinem ersten Wert als Ausgangsstand. Gespeicherte Stände von vorher verhalten sich wie bisher.

## 0.1.1 – 2026-10-27

Inhaltlich gleich 0.1.0 – nur eine neue Nummer, damit HACS die Version anbietet. GitHub sortiert alle Releases „0.1.0…“ willkürlich (0.1.0 landete hinter b10 und b6), HACS hielt deshalb weiter 0.1.0b9 für die neueste Version. Wer 0.1.0b9 hat, bekommt mit 0.1.1 die Neuerungen von 0.1.0b10 (geführte Einrichtung des dynamischen Tarifs).

## 0.1.0 – 2026-10-27

Erste stabile Version, inhaltlich gleich 0.1.0b10. HACS hat 0.1.0b10 nicht als Update angeboten: GitHub liefert die Releases so sortiert, dass b10 hinter b6 landet, und HACS hielt b9 für die neueste Version. Wer noch 0.1.0b9 hat, bekommt mit 0.1.0 die Neuerungen von b10 (geführte Einrichtung des dynamischen Tarifs).

## 0.1.0b10 – 2026-10-27

- **Einrichtung:** Der dynamische Tarif wird jetzt in einem eigenen Schritt angelegt – erst die Art wählen, „Börsenpreis plus Aufschläge“ steht als empfohlen vorn, dann dieselben Felder wie beim Hinzufügen eines Tarifs (MwSt. mit 19 % vorausgefüllt). Bisher legte die Einrichtung immer einen Gesamtpreis-Sensor an, mit dem es keinen Rückblick und kein Nachtragen der Statistik gibt. Bestehende Einträge bleiben unverändert.

## 0.1.0b9 – 2026-10-27

- **Neuer Tarif mit neuem Preissensor:** Die Zeit seit der Einrichtung, die länger als 24 Stunden zurückliegt, wurde bis zum nächsten Neustart „ohne Preis“ gezählt – die Neuberechnung beim Laden lief, bevor der neue Sensor seine Preise geliefert hatte. Kommen Preise für schon so gezählte Viertelstunden, rechnet Tarifwacht jetzt neu. Das hilft auch, wenn ein Preissensor beim Start von Home Assistant noch nicht bereit ist.
- **Dynamischen Tarif richtig anlegen:** README und Dialoge empfehlen jetzt „Börsenpreis plus Aufschläge“ – nur damit gibt es Rückblick und Statistik nachtragen. Für EPEX Spot zeigt eine kleine Tabelle, welche Werte wohin gehören (absoluter Aufschlag in Cent, Steuer als MwSt.); dann rechnet der Tarif genau wie der Gesamtpreis von EPEX Spot.
- README: fertiger Dashboard-Abschnitt „Tarifvergleich“ (günstigster Tarif, Durchschnittspreise, Kosten und Differenz heute und im Monat, Balken je Tag) statt der einzelnen Monatskarte; Hinweis, dass nachgetragene Statistik bei späteren Preiskorrekturen nicht mitrechnet.

## 0.1.0b8 – 2026-10-27

- **Blueprint „Monatsübersicht“:** schickt am Ersten jedes Monats Strombezug, Kosten jedes Tarifs, Differenz zum aktuellen Tarif und den günstigsten Tarif des Vormonats – als Benachrichtigung in Home Assistant oder mit einer eigenen Aktion. Import per Knopf im README.
- Intern: Der Quellen-Check erwartet in Wochen mit Zeitumstellung 668 bzw. 676 Viertelstunden statt immer 672 (meldete „676 von 672“).
- Intern: Dependabot schlägt Aktualisierungen jetzt für `dev` vor statt für `main`.

## 0.1.0b7 – 2026-10-27

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
