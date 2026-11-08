# Changelog

## Unveröffentlicht

- **Karte: Diagramme passen zur Spalte „Jahr“.** Die Säulen „Kosten je Monat“ und „Ersparnis je Monat“ zeigen genau die letzten zwölf Monate (den laufenden und die elf davor); bisher waren es dreizehn, im November also zwei Novembers nebeneinander. Monate des Vorjahres sind blasser, eine dünne Linie vor dem Januar mit den beiden Jahreszahlen trennt die Jahre – kräftig ist so genau das Kalenderjahr, das die Spalte „Jahr“ und die Kopfzeile zählen. Im Dezember liegen alle zwölf Monate im laufenden Jahr, dann gibt es keine Linie. Die Überschriften sagen jetzt „(letzte 12 Monate)“. Bild in der README neu.
- **Demo:** Die Uhr der Karte läuft ab dem gezeigten Zeitpunkt (Winter- oder Sommerabend), damit die letzten zwölf Monate und das Kalenderjahr dazu passen.

## 0.2.1 – 2026-11-08

- **Neu: eigene Karte „Tarifwacht“** fürs Dashboard, ohne Zusatzkarten aus HACS (*Dashboard bearbeiten → Karte hinzufügen →* „Tarifwacht“). Sie zeigt auf einen Blick, was dein Tarif kostet, ob ein anderer dieses Jahr günstiger gewesen wäre (und um wie viel) und was PV und Speicher sparen – jeweils heute, im Monat und im Kalenderjahr: oben dein Tarif, darunter jeder andere Tarif mit seinem Unterschied zu deinem (rot teurer, grün günstiger), mit PV und Speicher die Ersparnis zusammen und einzeln und was sie mit jedem anderen Tarif gespart hätten, dazu Säulen der letzten zwölf Monate. Die Karte passt sich an: Ohne PV-Anlage fehlt der Teil „PV und Speicher“, ohne Speicherzähler die Zeile „Speicher“. Im Editor wählst du nur den Eintrag; Tarife und Sensoren findet sie selbst, auch nach dem Umbenennen von Entitäten. Teile (Tarife, PV und Speicher, Diagramm) und Zeiträume sind wählbar, so kann die Karte auch zweimal ins Dashboard – etwa nur „PV und Speicher“ neben dem Speicher. Die Werte kommen aus der Langzeitstatistik wie bei einer Statistik-Karte, mit „Statistik nachtragen“ auch vor der Einrichtung; die Karte fragt alle fünf Minuten neu und nicht, solange die Seite im Hintergrund ist. Tarifwacht trägt sie selbst als Dashboard-Ressource ein und beim Entfernen des letzten Eintrags wieder aus. Deutsch und Englisch, helles und dunkles Theme, auch am Handy.
- **Neues Attribut `current`** an „Günstigster Tarif“: der Name deines aktuellen Tarifs, etwa für eine Kachel „Dein Tarif“ (`state_content: current`).
- **README:** Abschnitt „Karte“ mit Bild aus der Demo; das Beispiel „Dashboard: Tarifvergleich“ aus Standardkarten zeigt jetzt deinen Tarif, Kosten und Differenz auch fürs Jahr, dazu ein neues Beispiel für „PV und Speicher“ (Ersparnis je Monat und Jahr mit jedem Tarif, Säulen je Monat).
- **Bericht für Fehlermeldung:** nennt jetzt, wie die Karte ins Dashboard kommt (Dashboard-Ressource oder direkt geladen).
- **Demo:** zeigt oben die echte Karte, für die Wohnung ohne und für das Haus mit PV und Speicher.
- **Ersparnis durch PV und Speicher nachtragen:** Die Aktion **„Statistik nachtragen“** schreibt jetzt auch die Vergangenheit von „Ersparnis PV“ und „Ersparnis Speicher“ in die Langzeitstatistik – alle Stunden vor dem ersten Statistikwert dieser Sensoren, also auch die Zeit zwischen der Einrichtung des Eintrags und dem Hinzufügen von PV und Speicher. Bisher zählten Statistik-Karten mit Monat oder Jahr und Monatsdiagramme erst ab dem Hinzufügen; jetzt reichen sie so weit zurück wie die Statistik der Zähler. Ein Tarif, dem im Zeitraum Preise fehlen, wird wie bisher übersprungen.
- **Neues Attribut `since`** an „Ersparnis PV“ und „Ersparnis Speicher“: ab wann die Sensoren zählen (die Einrichtung des Eintrags), etwa für eine Markdown-Karte „seit …“.

## 0.2.0 – 2026-11-08

- **Neu: Ersparnis durch PV und Speicher.** Unter *Tarifwacht → Hinzufügen → PV und Speicher* trägst du Einspeisezähler, PV-Zähler und (optional) die Zähler „Speicher geladen/entladen“ ein, dazu die Einspeisevergütung und ob es bei negativen Börsenpreisen nichts gibt (§ 51 EEG). Jeder Tarif bekommt dann die Sensoren **„Ersparnis PV“** und **„Ersparnis Speicher“**: was PV und Speicher seit der Einrichtung gespart haben, verglichen mit dem Bezug des ganzen Verbrauchs aus dem Netz, mit dem Preis jeder Viertelstunde. So zeigt sich auch, was PV und Speicher mit einem dynamischen Tarif wert wären: Mittags ist der Strom dort billig, abends teuer. Gerechnet wird stündlich aus der Langzeitstatistik der Zähler; Hybrid-Wechselrichter (Speicher am selben Wechselrichter wie die PV) und Speicher mit eigenem Wechselrichter werden unterschieden, die Einrichtung schlägt die passende Antwort aus den Daten vor. Ist Einspeisewacht eingerichtet, sind Einspeisezähler, Vergütung und Börsenpreis vorausgefüllt (einmalig übernommen, keine Abhängigkeit). Die Aktion **„Tarife vergleichen“** liefert die Ersparnis unter `pv_battery` mit, je Monat und auch für die Zeit vor der Einrichtung. Anlass: Home-Assistant-Wunsch #1065.
- **Demo:** Das Haus hat jetzt eine erfundene PV-Anlage (9 kWp) mit Speicher (10 kWh) am Hybrid-Wechselrichter. Die Demo zeigt die Ersparnis durch PV und Speicher je Tarif, die drei Fälle (ohne PV und Speicher, nur PV, tatsächlich), die Energiemengen mit der unvergüteten Einspeisung bei negativen Preisen und die Ersparnis je Monat im Jahresrückblick. Der Strombezug des Hauses ist dadurch kleiner als bisher. Der erfundene Börsenpreis fällt mittags etwas seltener unter null (rund 580 statt 840 Stunden im Jahr, ähnlich wie 2025).

## 0.1.4 – 2026-11-07

- **Neu: Schaltfläche „Bericht für Fehlermeldung“** am Gerät des Zählers (unter *Diagnose*). Sie zeigt einen kurzen Bericht als Benachrichtigung zum Kopieren in ein Issue: Versionen, Zähler und Preissensoren nach Rolle (Integration, Einheit, Zustandsklasse, Zustand; beim Zähler nur, ob er eine Zahl liefert), die Tarife nach Art und Nummer mit Preisen, Modul 3 und Preisänderungen, den Stand der Buchung, Sensoren ohne Wert und offene Reparaturhinweise – ohne Entity-IDs, die Namen von Eintrag und Tarifen, Bereiche, Zählerstände sowie Energie- und Kostensummen. Viele wollen die Diagnose-Datei nicht öffentlich teilen, weil Home Assistant ihr unter anderem die Liste aller installierten Integrationen voranstellt. Die README erklärt jetzt unter „Fehler melden“, was in der Diagnose-Datei steht und welche Teile man vor dem Teilen löschen darf; die Issue-Vorlage fragt nach dem Bericht.

## 0.1.3 – 2026-11-05

- **Eigene Sensoren als Quelle abgewiesen:** Einrichtung, *Neu konfigurieren* und die Tarif-Formulare nehmen keine Sensoren von Tarifwacht selbst mehr als Bezugszähler oder Preissensor an. Der eigene Sensor „Strombezug“ ging bisher als Zähler durch – der Eintrag hätte dann seine eigenen Ergebnisse gelesen und still nichts gebucht. Jetzt meldet das Formular den Fehler und bittet um den echten Bezugszähler bzw. den Preissensor der Preis-Integration. Anlass war eine Rückmeldung aus der Schwester Wärmewacht, wo jemand den eigenen Standby-Sensor als Quelle gewählt hatte.
- **Neuer Reparaturhinweis „Sensor von Tarifwacht als Quelle gewählt“:** Für bestehende Einträge, die einen eigenen Sensor schon als Zähler oder Preissensor haben. Tarifwacht liest diesen Sensor nicht mehr: Mit eigenem Zähler bucht der Eintrag keinen Verbrauch mehr (mit dem „Strombezug“ desselben Eintrags buchte er ohnehin nichts, mit dem eines anderen Eintrags dessen Verbrauch um bis zu eine Minute versetzt), ein Tarif mit eigenem Preissensor bekommt keine Preise, und „Tarife vergleichen“ liest keinen Verbrauch aus seiner Statistik. Was schon gebucht ist, bleibt. Der Hinweis nennt den Sensor und den Ausweg (Zähler unter *Tarifwacht → ⋮ → Neu konfigurieren*, Preissensor im Tarif) und verschwindet nach der Korrektur; der neue Zähler beginnt mit seinem ersten Wert als Ausgangsstand.
- **Demo zum Ausprobieren ohne Installation:** [tarifwacht.github.io/integration](https://tarifwacht.github.io/integration/) zeigt den Tarifvergleich im Dashboard, die Geräte, die Monatsübersicht des Blueprints und einen Jahresrückblick – für eine Wohnung und ein Haus mit E-Auto und Wärmepumpe, an einem Winter- und einem Sommerabend. Preise, Verbräuche und Tarife sind erfunden und so gekennzeichnet; gebucht werden sie vom Code der Integration.
- **Kategorien im Manifest** für die neue Integrationsübersicht von Home Assistant 2026.11: Tarifwacht steht dort unter *Energie* bei „Energiepreise“ und „Zähler und Überwachung“.
- Intern: `tools/make_demo.py` erzeugt die Daten der Demo, der Workflow „Demo“ veröffentlicht sie über GitHub Pages.

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
