# Wärmepumpe vs. Brennwertkessel

Ein einfaches Python-Programm zur vergleichenden Simulation von **Wärmepumpe und Brennwertkessel**.

Die Anwendung stellt Heizkennlinie, COP und Wärmekosten grafisch dar und ermöglicht die Anpassung verschiedener technischer und wirtschaftlicher Parameter.

## Funktionen

- Interaktive Parameter-GUI
- Vergleich von Wärmepumpe und Brennwertkessel
- Heizkennlinien mit verschiedenen Steilheiten
- COP-Berechnung anhand eines vereinfachten Kennfelds
- Simulation eines synthetischen Jahresverlaufs
- Berechnung von Energie- und Vollkosten
- Berücksichtigung von:
  - Investitionskosten
  - Wartung
  - Energiepreissteigerungen
  - Kalkulationszins
  - Förderung
  - PV-Eigenverbrauch
  - Gas-Grundpreis
  - Schornsteinfeger
  - CO₂-Kosten
  - Verteil- und Speicherverlusten
- Export der Diagramme als PNG
- Export der verwendeten Parameter als TXT

## Installation

Benötigt wird **Python 3**.

Abhängigkeiten installieren:

```bash
pip install numpy matplotlib