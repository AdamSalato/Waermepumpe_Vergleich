# WP vs. Brennwert – Simulationsprogramm

Ein interaktives Python/tkinter-Tool zum Vergleich von **Wärmepumpe** und
**Brennwertkessel** hinsichtlich Vorlauftemperatur, Effizienz (COP) und
Wärmekosten – mit frei einstellbaren Parametern für Gebäude, Anlagentechnik,
Energiepreise und Förderung.

## Was macht das Tool?

Das Programm zeigt drei Diagramme, die live auf jede Parameteränderung
reagieren:

1. **Heizkennlinie** – wie sich die Vorlauftemperatur der Wärmepumpe mit der
   Außentemperatur ändert (klassische Steilheit/Niveau-Formel, wie sie auch
   in echten Heizungsreglern verwendet wird).
2. **COP der Wärmepumpe** – die Arbeitszahl in Abhängigkeit von Außen- und
   Vorlauftemperatur, abgeleitet aus einem 3×3-Herstellerkennfeld.
3. **Wärmekosten** – Energiekosten und Vollkosten (inkl. Investition,
   Wartung, Förderung) von WP und Kessel im direkten Vergleich, über die
   gesamte Außentemperaturspanne.

Zusätzlich lassen sich Diagramme als PNG und alle Parameter als TXT
exportieren.

## Installation & Start

```bash
pip install numpy matplotlib
python wp_brennwert_gui.py
```

Benötigt wird Python 3 mit `tkinter` (bei den meisten Standard-Python-
Installationen bereits enthalten; unter Linux ggf. `sudo apt install
python3-tk` nachinstallieren).

## Bedienung

- Links lassen sich alle Parameter in sechs Kategorien eingeben (Gebäude,
  WP-Wirtschaft, WP-Heizkurve, WP-COP-Kennfeld, PV, Brennwertkessel).
- **↻ Diagramme aktualisieren** berechnet alle drei Grafiken neu.
- **PNG exportieren** speichert sowohl die Gesamtansicht als auch jedes
  Diagramm einzeln in einem gewählten Ordner.
- **Parameter exportieren** schreibt alle aktuellen Eingabewerte in eine
  TXT-Datei (z. B. zur Dokumentation einer Beratung).
- **⟲ Attribute auf Standard setzen** setzt alle Felder auf die unten
  beschriebenen Standardwerte zurück.

## Die wichtigsten Begriffe

- **A / W** (im COP-Kennfeld): `A` = Außentemperatur, `W` = Vorlauf
  (**W**asser)-Temperatur. `A-7/W35` heißt also: -7 °C außen, 35 °C Vorlauf.
- **Steilheit (Neigung)**: wie stark die Vorlauftemperatur mit sinkender
  Außentemperatur ansteigt. Typisch 0,2–0,6 für Wärmepumpen, 0,8–1,8 für
  klassische Heizkörpersysteme.
- **Niveau**: additiver Versatz der gesamten Heizkurve nach oben/unten (K).
- **Bivalenzpunkt / Kreuzungspunkt** (Diagramm 3): die Außentemperatur, ab
  der der Kessel pro kWh günstiger wird als die Wärmepumpe (weil deren COP
  bei Kälte sinkt). Mit den Standardwerten liegt dieser Punkt bei ca. -9 °C.

## Standardwerte – Stand & Quellen (Herbst 2026)

Die vom Reset-Button wiederhergestellten Werte wurden anhand aktueller
Marktdaten geprüft:

| Parameter | Standardwert | Einordnung |
|---|---|---|
| Strompreis | 0,28 €/kWh | typischer WP-Stromtarif (BDEW-Gesamtschnitt liegt bei ~37 ct, dedizierte WP-Tarife meist 21–28 ct) |
| Gaspreis | 0,12 €/kWh | BDEW-Schnitt Herbst 2026: 11,6–12,6 ct/kWh |
| CO2-Preis | 60 €/t | gesetzlicher Korridor 2026: 55–65 €/t (Mittelwert) |
| CO2-Faktor Gas | 0,202 kg/kWh | physikalische Konstante (Erdgas) |
| WP-Investition | 27.000 € | Marktspanne 2026 für ein EFH inkl. Einbau: ca. 25.000–35.000 € |
| Kessel-Investition | 9.000 € | übliche Spanne: 6.000–12.000 € |
| Lebensdauer (beide) | 20 Jahre | Standardannahme |
| WP-COP-Kennfeld | 2,8/4,0/4,8 (W35), 2,3/3,3/4,0 (W45), 1,8/2,5/3,1 (W55) | realistische Werte einer modernen Luft-Wasser-WP (A-7/A2/A7) |

**Wichtig:** Das sind sinnvolle Durchschnittswerte für eine erste
Orientierung – kein Ersatz für ein konkretes Angebot oder Datenblatt. Vor
allem Strompreis (eigener Tarif!), WP-Investition und COP-Kennfeld sollten
nach Möglichkeit durch reale, projektspezifische Zahlen ersetzt werden.

## Methodik (Kurzfassung)

- **Heizkennlinie**: `Vorlauf = Raumsolltemperatur + Steilheit×ΔT +
  Steilheit×0,02×ΔT² + Niveau`, mit `ΔT = Raumsolltemperatur −
  Außentemperatur`. Physikalisch begründete, leicht progressive Kurvenform,
  keine künstliche Krümmung.
- **COP**: bilineare Interpolation im 3×3-Kennfeld (Außentemperatur ×
  Vorlauftemperatur), mit linearer Extrapolation außerhalb des
  Stützstellenbereichs (-7…7 °C) statt einer unrealistischen Randwert-
  Klemmung.
- **Energiepreise**: Strom- und Gaspreis werden über die Nutzungsdauer
  "levelisiert" – d. h. Preissteigerung und Kalkulationszins werden zu
  einem fairen, barwertäquivalenten Durchschnittspreis zusammengefasst,
  statt nur den heutigen Momentanpreis zu verwenden.
- **Jahreswärmebedarf**: aus einem synthetischen 8760h-Außentemperatur-
  profil plus Warmwasserbedarf und Verteil-/Speicherverlusten berechnet.
- **Fixkosten**: Investition (abzüglich Förderung) wird über die
  Lebensdauer annuisiert und zusammen mit der Wartung auf den
  Jahreswärmebedarf umgelegt.

## Grenzen des Modells

Das Programm ist ein **transparentes Sensitivitätsmodell**, kein
zertifiziertes Planungswerkzeug. Es ersetzt **keine** Heizlastberechnung
nach DIN EN 12831, keine Herstellerfreigabe und keine Energieberatung.
Insbesondere:

- Das synthetische Temperaturprofil ersetzt keine realen Standort-
  Wetterdaten (TRY/Messdaten).
- Das COP-Kennfeld ist eine vereinfachte 3×3-Interpolation, kein
  zertifiziertes Herstellerkennfeld nach EN 14511.
- Strom- und Gaspreise unterliegen kurzfristig starken Schwankungen –
  die Standardwerte sind eine Momentaufnahme (Herbst 2026).

Für eine belastbare Entscheidung sollten reale Angebote, Hersteller-
Datenblätter und eine individuelle Heizlastberechnung herangezogen werden.