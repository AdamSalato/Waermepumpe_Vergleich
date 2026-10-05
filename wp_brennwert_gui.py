"""
WP vs. Brennwert – interaktives Simulationsprogramm
====================================================

Python 3 + tkinter + numpy + matplotlib

Installation:
    pip install numpy matplotlib

Start:
    python wp_brennwert_gui.py

Funktionen:
- Interaktive Parameter-GUI
- 3 Diagramme:
  1. Heizkennlinie
  2. COP der Wärmepumpe
  3. Wärmekosten WP vs. Brennwertkessel
- Mehrere Heizkurven im ersten und zweiten Diagramm
- COP-Kennfeld über 3 Referenzpunkte je Vorlauftemperatur (mit linearer
  Extrapolation außerhalb des Stützstellenbereichs)
- Jahreskosten mit synthetischem Stundenprofil
- Investition, Lebensdauer, Wartung, Kalkulationszins (separat für WP/Kessel)
- Energiepreise inkl. Preissteigerung (auf Nutzungsdauer levelisiert)
- optionale PV-Eigenverbrauchsvereinfachung
- Gas-Grundpreis
- Schornsteinfeger
- CO2-Kosten
- Förderbetrag (WP und Kessel getrennt)
- Verteil-/Speicherverluste des Gebäudes
- Zurücksetzen aller Parameter auf geprüfte Standardwerte
- Export der Diagramme als PNG (inkl. korrekt zugeschnittener Einzelgrafiken)
- Export der aktuellen Parameter als TXT

Hinweis:
Das Programm ist ein transparentes Simulations-/Sensitivitätsmodell.
Es ersetzt keine Heizlastberechnung, Herstellerfreigabe oder Energieberatung.
Für eine belastbare Rechnung sollten reale Stunden-Wetterdaten und echte
Hersteller-Kennfelder verwendet werden.
"""
print("=== PROGRAMM WURDE GESTARTET ===", flush=True)
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


# ============================================================================
# DATENMODELLE
# ============================================================================

@dataclass
class Building:
    design_load_kw: float
    design_temp_c: float
    heating_limit_c: float
    dhw_kwh_year: float
    load_exponent: float
    distribution_loss_percent: float = 0.0


@dataclass
class HeatPump:
    investment_eur: float
    lifetime_years: float
    maintenance_eur_year: float
    electricity_price: float
    electricity_escalation: float
    discount_rate: float

    room_temperature_c: float
    min_supply_c: float
    max_supply_c: float
    slope: float
    level: float

    # COP-Kennfeld:
    # je Außentemperatur wird COP bei W35/W45/W55 eingegeben.
    cop_a_minus7_w35: float
    cop_a2_w35: float
    cop_a7_w35: float

    cop_a_minus7_w45: float
    cop_a2_w45: float
    cop_a7_w45: float

    cop_a_minus7_w55: float
    cop_a2_w55: float
    cop_a7_w55: float

    auxiliary_kwh_per_kwh_heat: float
    defrost_penalty_percent: float
    backup_start_c: float
    backup_share_percent: float

    pv_share: float
    pv_effective_price: float

    subsidy_eur: float = 0.0


@dataclass
class Boiler:
    investment_eur: float
    lifetime_years: float
    maintenance_eur_year: float
    gas_price: float
    gas_escalation: float
    electricity_price: float
    discount_rate: float

    efficiency: float
    high_temp_penalty: float
    auxiliary_kwh_per_kwh_heat: float

    gas_base_fee_year: float
    chimney_year: float
    co2_price_eur_per_ton: float
    gas_co2_kg_per_kwh: float

    subsidy_eur: float = 0.0


# ============================================================================
# HILFSFUNKTIONEN
# ============================================================================

def annuity_factor(rate, years):
    if years <= 0:
        return 0.0
    if abs(rate) < 1e-12:
        return 1.0 / years
    return rate * (1 + rate) ** years / ((1 + rate) ** years - 1)


def escalated_average_price(base_price, escalation_percent, discount_rate, years):
    """
    Berechnet einen über die Nutzungsdauer levelisierten (barwertäquivalenten)
    mittleren Energiepreis unter Berücksichtigung von Preissteigerung und
    Kalkulationszins.

    Idee: Der reale, jährlich steigende Preis wird auf den heutigen Barwert
    abgezinst; anschließend wird dieser Barwert wieder in einen konstanten
    Jahresbetrag ("Annuität") umgerechnet. Das Ergebnis ist ein einzelner,
    fairer Vergleichspreis für die gesamte Betrachtungsdauer.

    Bei escalation_percent == 0 entspricht das Ergebnis exakt base_price.
    """
    if base_price <= 0 or years <= 0:
        return max(base_price, 0.0)

    g = escalation_percent / 100.0
    d = discount_rate
    n = max(int(round(years)), 1)

    r = (1 + g) / (1 + d)

    if abs(r - 1.0) < 1e-9:
        present_value = base_price * n / (1 + d)
    else:
        present_value = base_price / (1 + d) * (1 - r ** n) / (1 - r)

    return present_value * annuity_factor(d, n)


def euro(x):
    return f"{x:.3f}".replace(".", ",") + " €"


def annualized_fixed_cost(investment, lifetime, maintenance, discount_rate,
                          annual_heat, subsidy=0.0):
    net_investment = max(investment - subsidy, 0.0)
    annual_investment = net_investment * annuity_factor(discount_rate, lifetime)
    return (annual_investment + maintenance) / max(annual_heat, 1.0)


def heating_load_fraction(temp, b: Building):
    temp = np.asarray(temp, dtype=float)
    frac = (b.heating_limit_c - temp) / (b.heating_limit_c - b.design_temp_c)
    return np.clip(frac, 0, 1) ** b.load_exponent


def heating_curve(temp, b: Building, wp: HeatPump, slope=None, level=None):
    """
    Klassische, in Heizungsreglern (Vaillant, Buderus, Viessmann u.a.)
    verwendete Heizkennlinien-Formel nach Neigung ("Steilheit") und
    Niveau:

        ΔT     = Raumsolltemperatur − Außentemperatur   (nur wenn > 0)
        Vorlauf = Raumsolltemperatur
                  + Steilheit × ΔT
                  + Steilheit × 0,02 × ΔT²
                  + Niveau

    Das erzeugt die typische, leicht progressiv gekrümmte Form (flach in
    der Nähe der Raumtemperatur, zunehmend steiler bei Kälte) – ganz ohne
    künstlich erzwungene Kurve, exakt wie in gängigen
    Heizkurven-Diagrammen dargestellt. Bei sehr kleiner Steilheit nähert
    sich die Kurve einer Geraden an.

    Der quadratische Koeffizient ist so kalibriert, dass eine Steilheit
    von 0,4 (übliche WP-Grenzkurve) bei -5 °C Außentemperatur rund 35 °C
    Vorlauf ergibt – der in den meisten gängigen Heizkurven-Diagrammen
    gezeigte Referenzwert.

    Typische Steilheit-Werte: ~0,2–0,6 für Wärmepumpen (niedrige
    Vorlauftemperaturen, meist Fußbodenheizung), ~0,8–1,8 für klassische
    Heizkörpersysteme.
    """
    temp = np.asarray(temp, dtype=float)

    if slope is None:
        slope = wp.slope
    if level is None:
        level = wp.level

    delta = np.maximum(wp.room_temperature_c - temp, 0.0)

    supply = (
        wp.room_temperature_c
        + slope * delta
        + slope * 0.02 * delta ** 2
        + level
    )

    return np.clip(
        supply,
        wp.min_supply_c + level,
        wp.max_supply_c
    )


def interpolate_1d(x, points_x, points_y):
    return np.interp(x, points_x, points_y)


def extrapolate_1d(x, points_x, points_y):
    """
    Wie np.interp, aber unterhalb/oberhalb der Stützstellen wird die
    Steigung des jeweils äußersten Segments linear fortgeführt statt den
    Randwert einfach zu klemmen. Realistischer für ein COP-Kennfeld, dessen
    Stützstellen typischerweise nur -7…7 °C abdecken, während die
    Simulation auch deutlich kältere Außentemperaturen durchrechnet.
    """
    x = np.asarray(x, dtype=float)
    points_x = np.asarray(points_x, dtype=float)
    points_y = np.asarray(points_y, dtype=float)

    y = np.interp(x, points_x, points_y).astype(float)

    below = x < points_x[0]
    if np.any(below):
        slope = (points_y[1] - points_y[0]) / (points_x[1] - points_x[0])
        y[below] = points_y[0] + slope * (x[below] - points_x[0])

    above = x > points_x[-1]
    if np.any(above):
        slope = (points_y[-1] - points_y[-2]) / (points_x[-1] - points_x[-2])
        y[above] = points_y[-1] + slope * (x[above] - points_x[-1])

    return y


def cop_from_field(temp_outdoor, supply, wp: HeatPump):
    """
    Interpoliert ein 3x3-artiges Hersteller-Kennfeld:
      Außen: -7, +2, +7 °C
      Vorlauf: 35, 45, 55 °C

    Zuerst linear über Vorlauf, danach über Außentemperatur.
    Für Außentemperaturen außerhalb -7/+7 wird die Steigung des jeweils
    nächstliegenden Randbereichs linear fortgeführt (statt geklemmt).
    """

    temp_outdoor = np.asarray(temp_outdoor, dtype=float)
    supply = np.asarray(supply, dtype=float)

    outdoor_points = np.array([-7.0, 2.0, 7.0])

    cop35 = np.array([
        wp.cop_a_minus7_w35,
        wp.cop_a2_w35,
        wp.cop_a7_w35
    ])
    cop45 = np.array([
        wp.cop_a_minus7_w45,
        wp.cop_a2_w45,
        wp.cop_a7_w45
    ])
    cop55 = np.array([
        wp.cop_a_minus7_w55,
        wp.cop_a2_w55,
        wp.cop_a7_w55
    ])

    # Erst Temperaturabhängigkeit für W35/W45/W55 (mit Extrapolation an
    # den Rändern, damit sehr kalte Tage nicht künstlich am -7°C-COP kleben)
    c35 = extrapolate_1d(temp_outdoor, outdoor_points, cop35)
    c45 = extrapolate_1d(temp_outdoor, outdoor_points, cop45)
    c55 = extrapolate_1d(temp_outdoor, outdoor_points, cop55)

    # Danach Vorlauftemperatur
    cop = np.empty_like(temp_outdoor)

    low = supply <= 35
    mid = (supply > 35) & (supply <= 45)
    high = supply > 45

    cop[low] = c35[low]
    cop[mid] = c35[mid] + (c45[mid] - c35[mid]) * (
        (supply[mid] - 35) / 10
    )

    cop[high] = c45[high] + (c55[high] - c45[high]) * (
        np.clip(supply[high], 45, 55) - 45
    ) / 10

    # oberhalb 55 °C wird der COP extrapoliert nicht weiter künstlich erhöht
    over = supply > 55
    if np.any(over):
        cop[over] = c55[over] - 0.035 * (supply[over] - 55)

    # Unter 35 °C: kleine Verbesserung gegenüber W35 begrenzen
    under = supply < 35
    if np.any(under):
        cop[under] = c35[under] + 0.025 * (35 - supply[under])

    return np.maximum(cop, 1.05)


def synthetic_year(seed=42):
    """
    Einfaches synthetisches 8760h-Profil.
    Ersetzt für eine reale Standortrechnung idealerweise durch Mess-/TRY-Daten.
    """
    rng = np.random.default_rng(seed)
    h = np.arange(8760)

    annual = 9.5 + 10.0 * np.sin(2 * np.pi * (h - 1100) / 8760)
    daily = 2.0 * np.sin(2 * np.pi * h / 24 - 0.8)
    noise = rng.normal(0, 2.3, 8760)

    return np.clip(annual + daily + noise, -20, 30)


def annual_heat_demand(temps, b: Building):
    load = heating_load_fraction(temps, b)
    space = np.sum(b.design_load_kw * load)
    total = space + b.dhw_kwh_year
    return total * (1 + b.distribution_loss_percent / 100)


def defrost_factor(temp, wp: HeatPump):
    """
    Vereinfachte Abtaukorrektur.
    Maximum rund um 0…4 °C.
    """
    t = np.asarray(temp, dtype=float)

    f = np.zeros_like(t)

    zone1 = (t >= 0) & (t <= 4)
    f[zone1] = 1 - t[zone1] / 4

    zone2 = (t < 0) & (t >= -7)
    f[zone2] = 1 - np.abs(t[zone2]) / 7

    return np.clip(f, 0, 1) * wp.defrost_penalty_percent / 100


def wp_cost_per_kwh(
    temp,
    b: Building,
    wp: HeatPump,
    include_fixed=False,
    fixed_cost=0.0,
    electricity_price_override=None,
):
    temp = np.asarray(temp, dtype=float)

    supply = heating_curve(temp, b, wp)
    cop = cop_from_field(temp, supply, wp)

    cop = cop / (1 + defrost_factor(temp, wp))

    # Heizstab
    backup = np.where(
        temp <= wp.backup_start_c,
        wp.backup_share_percent / 100,
        0
    )

    # Strombedarf pro kWh Wärme
    electricity = (1 - backup) / cop + backup

    # Hilfsenergie
    electricity += wp.auxiliary_kwh_per_kwh_heat

    grid_price = (
        wp.electricity_price
        if electricity_price_override is None
        else electricity_price_override
    )

    # PV-Eigenverbrauch als vereinfachter Anteil
    effective_price = (
        wp.pv_share / 100 * wp.pv_effective_price
        + (1 - wp.pv_share / 100) * grid_price
    )

    variable = electricity * effective_price

    if include_fixed:
        variable = variable + fixed_cost

    return variable


def boiler_efficiency(temp, b: Building, boiler: Boiler):
    temp = np.asarray(temp, dtype=float)

    # Näherung für steigende Vorlauftemperatur bei kaltem Wetter
    supply = 35 + 1.0 * np.clip(
        b.heating_limit_c - temp, 0, 45
    )

    penalty = np.maximum(supply - 55, 0) * boiler.high_temp_penalty

    return np.clip(boiler.efficiency - penalty, 0.70, 1.02)


def boiler_cost_per_kwh(
    temp,
    b: Building,
    boiler: Boiler,
    include_fixed=False,
    fixed_cost=0.0,
    gas_price_override=None,
    electricity_price_override=None,
):
    eta = boiler_efficiency(temp, b, boiler)

    gas = 1 / eta

    gas_price = boiler.gas_price if gas_price_override is None else gas_price_override
    elec_price = (
        boiler.electricity_price
        if electricity_price_override is None
        else electricity_price_override
    )

    # CO2-Kosten
    co2 = (
        gas
        * boiler.gas_co2_kg_per_kwh
        * boiler.co2_price_eur_per_ton
        / 1000
    )

    variable = (
        gas * gas_price
        + boiler.auxiliary_kwh_per_kwh_heat * elec_price
        + co2
    )

    if include_fixed:
        variable += fixed_cost

    return variable


# ============================================================================
# GUI
# ============================================================================

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Wärmepumpe vs. Brennwertkessel – Simulation")
        self.root.geometry("1550x950")
        self.root.minsize(1250, 800)

        self.vars = {}
        self.create_variables()
        self.build_gui()

        self.update_plots()

    def create_variables(self):
        # Diese Werte dienen als fachlich geprüfte Standardwerte (Stand
        # 2026) für einen durchschnittlichen deutschen Einfamilienhaus-
        # Vergleich WP vs. Brennwertkessel und werden auch vom
        # "Auf Standard zurücksetzen"-Button wiederhergestellt.
        self.defaults = {
            # Gebäude
            "design_load": 10.0,
            "design_temp": -10.0,
            "heating_limit": 15.0,
            "dhw": 2500.0,
            "load_exponent": 1.15,
            "distribution_loss": 5.0,

            # WP Wirtschaft
            "wp_invest": 27000.0,
            "wp_subsidy": 0.0,
            "wp_life": 20.0,
            "wp_maintenance": 300.0,
            "electricity": 0.28,
            "electricity_growth": 2.0,
            "discount": 4.0,

            # WP Heizkurve
            "wp_room_temp": 20.0,
            "wp_supply_min": 25.0,
            "wp_supply_max": 55.0,
            "wp_slope": 0.40,
            "wp_level": 0.0,

            # COP W35
            "cop_m7_w35": 2.8,
            "cop_2_w35": 4.0,
            "cop_7_w35": 4.8,

            # COP W45
            "cop_m7_w45": 2.3,
            "cop_2_w45": 3.3,
            "cop_7_w45": 4.0,

            # COP W55
            "cop_m7_w55": 1.8,
            "cop_2_w55": 2.5,
            "cop_7_w55": 3.1,

            "wp_aux": 0.015,
            "defrost": 8.0,
            "backup_start": -10.0,
            "backup_share": 0.0,
            "pv_share": 0.0,
            "pv_price": 0.10,

            # Kessel
            "boiler_invest": 9000.0,
            "boiler_subsidy": 0.0,
            "boiler_life": 20.0,
            "boiler_maintenance": 250.0,
            "gas": 0.12,
            "gas_growth": 2.0,
            "boiler_eff": 98.0,
            "boiler_temp_penalty": 0.0005,
            "boiler_aux": 0.02,
            "gas_base": 180.0,
            "chimney": 100.0,
            "co2": 60.0,
            "gas_co2": 0.202,
            "boiler_discount": 4.0,
        }

        for k, v in self.defaults.items():
            self.vars[k] = tk.DoubleVar(value=v)

    def reset_to_defaults(self):
        for k, v in self.defaults.items():
            self.vars[k].set(v)
        self.update_plots()
        self.status.config(text="Alle Parameter auf Standardwerte zurückgesetzt.")

    def add_entry(self, parent, row, label, key, unit=""):
        ttk.Label(parent, text=label).grid(
            row=row, column=0, sticky="w", padx=4, pady=2
        )
        e = ttk.Entry(parent, textvariable=self.vars[key], width=10)
        e.grid(row=row, column=1, sticky="e", padx=4, pady=2)
        ttk.Label(parent, text=unit).grid(
            row=row, column=2, sticky="w", padx=3
        )
        return e

    def section(self, parent, title, row):
        frame = ttk.LabelFrame(parent, text=title)
        frame.grid(
            row=row, column=0, sticky="ew", padx=5, pady=5
        )
        return frame

    def build_gui(self):
        main = ttk.Frame(self.root)
        main.pack(fill="both", expand=True)

        # --------------------------------------------------------------------
        # LINKER PARAMETERBEREICH
        # --------------------------------------------------------------------
        left_outer = ttk.Frame(main, width=390)
        left_outer.pack(side="left", fill="y")

        canvas = tk.Canvas(left_outer, width=390)
        scrollbar = ttk.Scrollbar(
            left_outer, orient="vertical", command=canvas.yview
        )

        params = ttk.Frame(canvas)
        params.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=params, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="y", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Gebäude
        f = self.section(params, "Gebäude", 0)
        self.add_entry(f, 0, "Auslegungs-Heizlast", "design_load", "kW")
        self.add_entry(f, 1, "Auslegungstemperatur", "design_temp", "°C")
        self.add_entry(f, 2, "Heizgrenze", "heating_limit", "°C")
        self.add_entry(f, 3, "Warmwasser", "dhw", "kWh/a")
        self.add_entry(f, 4, "Last-Exponent", "load_exponent", "")
        self.add_entry(f, 5, "Verteil-/Speicherverluste", "distribution_loss", "%")

        # WP Wirtschaft
        f = self.section(params, "Wärmepumpe – Wirtschaft", 1)
        self.add_entry(f, 0, "Investition", "wp_invest", "€")
        self.add_entry(f, 1, "Förderung", "wp_subsidy", "€")
        self.add_entry(f, 2, "Lebensdauer", "wp_life", "a")
        self.add_entry(f, 3, "Wartung", "wp_maintenance", "€/a")
        self.add_entry(f, 4, "Strompreis", "electricity", "€/kWh")
        self.add_entry(f, 5, "Strompreissteigerung", "electricity_growth", "%/a")
        self.add_entry(f, 6, "Kalkulationszins", "discount", "%")

        # WP Heizkurve
        f = self.section(params, "Wärmepumpe – Heizkurve", 2)
        self.add_entry(f, 0, "Raumsolltemperatur", "wp_room_temp", "°C")
        self.add_entry(f, 1, "Minimaler Vorlauf", "wp_supply_min", "°C")
        self.add_entry(f, 2, "Maximaler Vorlauf", "wp_supply_max", "°C")
        self.add_entry(f, 3, "Steilheit (Neigung)", "wp_slope", "")
        ttk.Label(
            f, text="Typisch 0,2–0,6 für WP · 0,4 gilt oft als WP-Grenzkurve",
            font=("TkDefaultFont", 8, "italic")
        ).grid(row=4, column=0, columnspan=3, sticky="w", padx=4, pady=(0, 3))
        self.add_entry(f, 5, "Niveau", "wp_level", "K")

        # COP
        f = self.section(params, "Wärmepumpe – COP-Kennfeld", 3)
        ttk.Label(
            f, text="W35 / W45 / W55 bei A-7 / A2 / A7 °C",
            font=("TkDefaultFont", 8, "italic")
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=4, pady=3)

        row = 1
        for key, label in [
            ("cop_m7_w35", "A-7 / W35"),
            ("cop_2_w35", "A2 / W35"),
            ("cop_7_w35", "A7 / W35"),
            ("cop_m7_w45", "A-7 / W45"),
            ("cop_2_w45", "A2 / W45"),
            ("cop_7_w45", "A7 / W45"),
            ("cop_m7_w55", "A-7 / W55"),
            ("cop_2_w55", "A2 / W55"),
            ("cop_7_w55", "A7 / W55"),
        ]:
            self.add_entry(f, row, label, key, "COP")
            row += 1

        self.add_entry(f, row, "Hilfsenergie", "wp_aux", "kWh/kWh")
        row += 1
        self.add_entry(f, row, "Abtauverlust", "defrost", "%")
        row += 1
        self.add_entry(f, row, "Heizstab ab", "backup_start", "°C")
        row += 1
        self.add_entry(f, row, "Heizstab-Anteil", "backup_share", "%")

        # PV
        f = self.section(params, "PV / eigener Strom", 4)
        self.add_entry(f, 0, "PV-Anteil", "pv_share", "%")
        self.add_entry(f, 1, "Preis PV-Strom", "pv_price", "€/kWh")

        # Kessel
        f = self.section(params, "Brennwertkessel", 5)
        self.add_entry(f, 0, "Investition", "boiler_invest", "€")
        self.add_entry(f, 1, "Förderung", "boiler_subsidy", "€")
        self.add_entry(f, 2, "Lebensdauer", "boiler_life", "a")
        self.add_entry(f, 3, "Wartung", "boiler_maintenance", "€/a")
        self.add_entry(f, 4, "Gaspreis", "gas", "€/kWh")
        self.add_entry(f, 5, "Gaspreissteigerung", "gas_growth", "%/a")
        self.add_entry(f, 6, "Kalkulationszins", "boiler_discount", "%")
        self.add_entry(f, 7, "Wirkungsgrad", "boiler_eff", "%")
        self.add_entry(f, 8, "Temp.-Penalty", "boiler_temp_penalty", "1/K")
        self.add_entry(f, 9, "Hilfsstrom", "boiler_aux", "kWh/kWh")
        self.add_entry(f, 10, "Gas-Grundpreis", "gas_base", "€/a")
        self.add_entry(f, 11, "Schornsteinfeger", "chimney", "€/a")
        self.add_entry(f, 12, "CO2-Preis", "co2", "€/t")
        self.add_entry(f, 13, "CO2-Faktor Gas", "gas_co2", "kg/kWh")

        # Buttons
        bf = ttk.Frame(params)
        bf.grid(row=6, column=0, padx=5, pady=10, sticky="ew")

        ttk.Button(
            bf, text="↻ Diagramme aktualisieren",
            command=self.update_plots
        ).pack(fill="x", pady=3)

        ttk.Button(
            bf, text="PNG exportieren",
            command=self.export_png
        ).pack(fill="x", pady=3)

        ttk.Button(
            bf, text="Parameter exportieren",
            command=self.export_parameters
        ).pack(fill="x", pady=3)

        ttk.Separator(bf, orient="horizontal").pack(fill="x", pady=4)

        ttk.Button(
            bf, text="⟲ Attribute auf Standard setzen",
            command=self.reset_to_defaults
        ).pack(fill="x", pady=3)

        # --------------------------------------------------------------------
        # RECHTER BEREICH
        # --------------------------------------------------------------------
        right = ttk.Frame(main)
        right.pack(side="right", fill="both", expand=True)

        self.figure = Figure(figsize=(10, 9), dpi=100)
        self.ax1 = self.figure.add_subplot(311)
        self.ax2 = self.figure.add_subplot(312)
        self.ax3 = self.figure.add_subplot(313)

        self.figure.subplots_adjust(
            left=0.08, right=0.98,
            top=0.96, bottom=0.07,
            hspace=0.42
        )

        self.chart = FigureCanvasTkAgg(self.figure, master=right)
        self.chart.get_tk_widget().pack(fill="both", expand=True)

        self.status = ttk.Label(
            right,
            text="Bereit",
            anchor="w",
            relief="sunken"
        )
        self.status.pack(fill="x")

    # ------------------------------------------------------------------------
    # PARAMETER AUSLESEN
    # ------------------------------------------------------------------------

    def get_models(self):
        v = self.vars

        b = Building(
            design_load_kw=v["design_load"].get(),
            design_temp_c=v["design_temp"].get(),
            heating_limit_c=v["heating_limit"].get(),
            dhw_kwh_year=v["dhw"].get(),
            load_exponent=v["load_exponent"].get(),
            distribution_loss_percent=v["distribution_loss"].get(),
        )

        wp = HeatPump(
            investment_eur=v["wp_invest"].get(),
            lifetime_years=v["wp_life"].get(),
            maintenance_eur_year=v["wp_maintenance"].get(),
            electricity_price=v["electricity"].get(),
            electricity_escalation=v["electricity_growth"].get(),
            discount_rate=v["discount"].get() / 100,

            room_temperature_c=v["wp_room_temp"].get(),
            min_supply_c=v["wp_supply_min"].get(),
            max_supply_c=v["wp_supply_max"].get(),
            slope=v["wp_slope"].get(),
            level=v["wp_level"].get(),

            cop_a_minus7_w35=v["cop_m7_w35"].get(),
            cop_a2_w35=v["cop_2_w35"].get(),
            cop_a7_w35=v["cop_7_w35"].get(),

            cop_a_minus7_w45=v["cop_m7_w45"].get(),
            cop_a2_w45=v["cop_2_w45"].get(),
            cop_a7_w45=v["cop_7_w45"].get(),

            cop_a_minus7_w55=v["cop_m7_w55"].get(),
            cop_a2_w55=v["cop_2_w55"].get(),
            cop_a7_w55=v["cop_7_w55"].get(),

            auxiliary_kwh_per_kwh_heat=v["wp_aux"].get(),
            defrost_penalty_percent=v["defrost"].get(),
            backup_start_c=v["backup_start"].get(),
            backup_share_percent=v["backup_share"].get(),

            pv_share=v["pv_share"].get(),
            pv_effective_price=v["pv_price"].get(),

            subsidy_eur=v["wp_subsidy"].get(),
        )

        boiler = Boiler(
            investment_eur=v["boiler_invest"].get(),
            lifetime_years=v["boiler_life"].get(),
            maintenance_eur_year=v["boiler_maintenance"].get(),
            gas_price=v["gas"].get(),
            gas_escalation=v["gas_growth"].get(),
            electricity_price=v["electricity"].get(),
            discount_rate=v["boiler_discount"].get() / 100,

            efficiency=v["boiler_eff"].get() / 100,
            high_temp_penalty=v["boiler_temp_penalty"].get(),
            auxiliary_kwh_per_kwh_heat=v["boiler_aux"].get(),

            gas_base_fee_year=v["gas_base"].get(),
            chimney_year=v["chimney"].get(),
            co2_price_eur_per_ton=v["co2"].get(),
            gas_co2_kg_per_kwh=v["gas_co2"].get(),

            subsidy_eur=v["boiler_subsidy"].get(),
        )

        return b, wp, boiler

    # ------------------------------------------------------------------------
    # DIAGRAMME
    # ------------------------------------------------------------------------

    def update_plots(self):
        try:
            b, wp, boiler = self.get_models()

            if b.design_temp_c >= b.heating_limit_c:
                raise ValueError("Auslegungstemperatur muss unter der Heizgrenze liegen.")
            if wp.min_supply_c >= wp.max_supply_c:
                raise ValueError("Min. Vorlauf muss kleiner als Max. Vorlauf sein.")
            if wp.room_temperature_c <= b.design_temp_c:
                raise ValueError("Raumsolltemperatur muss über der Auslegungstemperatur liegen.")
            if wp.lifetime_years <= 0 or boiler.lifetime_years <= 0:
                raise ValueError("Lebensdauer muss größer als 0 sein.")
            if wp.investment_eur < wp.subsidy_eur:
                raise ValueError("WP-Förderung darf die WP-Investition nicht übersteigen.")
            if boiler.investment_eur < boiler.subsidy_eur:
                raise ValueError("Kessel-Förderung darf die Kessel-Investition nicht übersteigen.")

            x = np.linspace(-20, 20, 401)

            temps_year = synthetic_year()
            annual_heat = annual_heat_demand(temps_year, b)

            # Auf die Nutzungsdauer levelisierte Energiepreise (berücksichtigen
            # Preissteigerung + Kalkulationszins) statt statischer Momentanpreise
            wp_elec_price_eff = escalated_average_price(
                wp.electricity_price, wp.electricity_escalation,
                wp.discount_rate, wp.lifetime_years
            )
            boiler_gas_price_eff = escalated_average_price(
                boiler.gas_price, boiler.gas_escalation,
                boiler.discount_rate, boiler.lifetime_years
            )
            boiler_elec_price_eff = escalated_average_price(
                boiler.electricity_price, wp.electricity_escalation,
                boiler.discount_rate, boiler.lifetime_years
            )

            # Fixkosten (jetzt inkl. Förderung)
            wp_fixed = annualized_fixed_cost(
                wp.investment_eur,
                wp.lifetime_years,
                wp.maintenance_eur_year,
                wp.discount_rate,
                annual_heat,
                wp.subsidy_eur
            )

            boiler_fixed = annualized_fixed_cost(
                boiler.investment_eur,
                boiler.lifetime_years,
                boiler.maintenance_eur_year
                + boiler.gas_base_fee_year
                + boiler.chimney_year,
                boiler.discount_rate,
                annual_heat,
                boiler.subsidy_eur
            )

            # ================================================================
            # GRAPH 1
            # ================================================================
            self.ax1.clear()

            # Klassische Steilheit-Werte (Neigung), wie sie auch in
            # Heizungsregler-Diagrammen üblich sind. 0,4 gilt vielfach als
            # sinnvolle Obergrenze für Wärmepumpen (niedrige, effiziente
            # Vorlauftemperaturen), höhere Werte entsprechen klassischen,
            # für Heizkörper ausgelegten Systemen.
            variants = [
                ("Sehr flach (0,2)", 0.20, 0),
                ("WP-Grenzkurve (0,4)", 0.40, 0),
                ("Mittel (0,6)", 0.60, 0),
                ("Steil (1,0)", 1.00, 0),
                ("Sehr steil (1,5)", 1.50, 0),
            ]

            for name, slope, level in variants:
                y = heating_curve(
                    x, b, wp,
                    slope=slope,
                    level=level
                )
                self.ax1.plot(
                    x, y,
                    linewidth=2.2,
                    label=name
                )

            # Aktuell eingestellte Heizkurve (aus den GUI-Feldern
            # "Steilheit"/"Niveau") zusätzlich hervorgehoben, da die
            # Vergleichsvarianten oben davon unabhängig sind
            y_current = heating_curve(x, b, wp)
            self.ax1.plot(
                x, y_current,
                linewidth=3.0,
                linestyle=":",
                color="black",
                label="Aktuell eingestellt"
            )

            self.ax1.axvline(
                b.design_temp_c,
                linestyle="--",
                linewidth=1,
                alpha=0.55
            )

            self.ax1.set_title(
                "1. Heizkennlinie der Wärmepumpe",
                fontweight="bold"
            )
            self.ax1.set_xlabel("Außentemperatur [°C]")
            self.ax1.set_ylabel("Vorlauftemperatur [°C]")
            self.ax1.set_xlim(-20, 20)
            self.ax1.grid(alpha=0.22)
            self.ax1.legend(fontsize=8, ncol=3)

            # ================================================================
            # GRAPH 2
            # ================================================================
            self.ax2.clear()

            for name, slope, level in variants:
                supply = heating_curve(
                    x, b, wp,
                    slope=slope,
                    level=level
                )
                cop = cop_from_field(x, supply, wp)
                cop = cop / (1 + defrost_factor(x, wp))

                self.ax2.plot(
                    x, cop,
                    linewidth=2.1,
                    label=name
                )

            cop_current = cop_from_field(x, y_current, wp)
            cop_current = cop_current / (1 + defrost_factor(x, wp))
            self.ax2.plot(
                x, cop_current,
                linewidth=3.0,
                linestyle=":",
                color="black",
                label="Aktuell eingestellt"
            )

            self.ax2.set_title(
                "2. COP der Wärmepumpe",
                fontweight="bold"
            )
            self.ax2.set_xlabel("Außentemperatur [°C]")
            self.ax2.set_ylabel("COP [kWh Wärme / kWh Strom]")
            self.ax2.set_xlim(-20, 20)
            self.ax2.set_ylim(bottom=1)
            self.ax2.grid(alpha=0.22)
            self.ax2.legend(fontsize=8, ncol=3)

            # ================================================================
            # GRAPH 3
            # ================================================================
            self.ax3.clear()

            wp_variable = wp_cost_per_kwh(
                x, b, wp,
                electricity_price_override=wp_elec_price_eff,
            )
            wp_total = wp_variable + wp_fixed

            boiler_variable = boiler_cost_per_kwh(
                x, b, boiler,
                gas_price_override=boiler_gas_price_eff,
                electricity_price_override=boiler_elec_price_eff,
            )
            boiler_total = boiler_variable + boiler_fixed

            self.ax3.plot(
                x, wp_variable,
                linestyle="--",
                linewidth=1.8,
                label="WP – Energie"
            )
            self.ax3.plot(
                x, wp_total,
                linewidth=2.8,
                label="WP – Vollkosten"
            )
            self.ax3.plot(
                x, boiler_variable,
                linestyle="--",
                linewidth=1.8,
                label="Kessel – Energie"
            )
            self.ax3.plot(
                x, boiler_total,
                linewidth=2.8,
                label="Kessel – Vollkosten"
            )
            
            self.ax3.set_title(
                "3. Wärmekosten (Energiepreise über Nutzungsdauer levelisiert)",
                fontweight="bold",
                pad=12
            )
            self.ax3.set_xlabel("Außentemperatur [°C]")
            self.ax3.set_ylabel("Kosten [€/kWh Wärme]")
            self.ax3.set_xlim(-20, 20)
            self.ax3.set_ylim(bottom=0)
            self.ax3.grid(alpha=0.22)
            self.ax3.legend(fontsize=8, ncol=2)

            info = (
                f"Jahres-Wärmebedarf ≈ {annual_heat:,.0f} kWh/a   |   "
                f"WP Invest+Wartung ≈ {wp_fixed:.3f} €/kWh   |   "
                f"Kessel Invest+Wartung+Fixkosten ≈ {boiler_fixed:.3f} €/kWh"
            )

            # Info innerhalb des Diagramms platzieren, damit sie weder
            # die Überschrift noch den oberen Rand überdeckt.
            self.ax3.text(
                0.02, 0.97,
                info.replace(",", "."),
                transform=self.ax3.transAxes,
                ha="left",
                va="top",
                fontsize=8,
                bbox=dict(
                    boxstyle="round,pad=0.3",
                    facecolor="white",
                    alpha=0.8,
                    edgecolor="0.75"
                )
            )

            self.figure.canvas.draw_idle()

            self.status.config(
                text=(
                    f"Jahres-Wärmebedarf: {annual_heat:,.0f} kWh/a | "
                    f"WP Fixkostenanteil: {wp_fixed:.3f} €/kWh | "
                    f"Kessel Fixkostenanteil: {boiler_fixed:.3f} €/kWh | "
                    f"Strompreis (levelisiert): {wp_elec_price_eff:.3f} €/kWh | "
                    f"Gaspreis (levelisiert): {boiler_gas_price_eff:.3f} €/kWh"
                ).replace(",", ".")
            )

        except Exception as exc:
            messagebox.showerror(
                "Fehler bei der Berechnung",
                str(exc)
            )

    # ------------------------------------------------------------------------
    # EXPORT
    # ------------------------------------------------------------------------

    def export_png(self):
        try:
            folder = filedialog.askdirectory(
                title="Ordner für Diagramme auswählen"
            )
            if not folder:
                return

            folder = Path(folder)

            # Aktuelle Figure enthält alle drei Diagramme
            self.figure.savefig(
                folder / "wp_brennwert_alle_3_diagramme.png",
                dpi=220,
                bbox_inches="tight"
            )

            # Einzelne Diagramme separat exportieren: bbox_inches muss die
            # Bounding-Box der jeweiligen Achse sein, sonst wird (wie zuvor)
            # trotzdem immer die gesamte Figure gespeichert.
            for ax, filename in [
                (self.ax1, "01_heizkennlinien.png"),
                (self.ax2, "02_cop.png"),
                (self.ax3, "03_waermekosten.png"),
            ]:
                extent = ax.get_window_extent().transformed(
                    self.figure.dpi_scale_trans.inverted()
                )
                extent = extent.expanded(1.25, 1.25)
                self.figure.savefig(
                    folder / filename,
                    dpi=220,
                    bbox_inches=extent
                )

            messagebox.showinfo(
                "Export",
                f"Diagramme wurden gespeichert in:\n{folder}"
            )

        except Exception as exc:
            messagebox.showerror("Exportfehler", str(exc))

    def export_parameters(self):
        try:
            filename = filedialog.asksaveasfilename(
                title="Parameter speichern",
                defaultextension=".txt",
                filetypes=[("Textdatei", "*.txt")]
            )

            if not filename:
                return

            b, wp, boiler = self.get_models()

            lines = [
                "WÄRMEPUMPE vs. BRENNWERTKESSEL",
                "================================",
                "",
                "GEBÄUDE",
                f"Heizlast: {b.design_load_kw} kW",
                f"Auslegungstemperatur: {b.design_temp_c} °C",
                f"Heizgrenze: {b.heating_limit_c} °C",
                f"Warmwasser: {b.dhw_kwh_year} kWh/a",
                f"Last-Exponent: {b.load_exponent}",
                f"Verteil-/Speicherverluste: {b.distribution_loss_percent} %",
                "",
                "WÄRMEPUMPE",
                f"Investition: {wp.investment_eur} €",
                f"Förderung: {wp.subsidy_eur} €",
                f"Lebensdauer: {wp.lifetime_years} a",
                f"Wartung: {wp.maintenance_eur_year} €/a",
                f"Strompreis: {wp.electricity_price} €/kWh",
                f"Strompreissteigerung: {wp.electricity_escalation} %/a",
                f"Kalkulationszins: {wp.discount_rate * 100} %",
                f"Raumsolltemperatur: {wp.room_temperature_c} °C",
                f"Vorlauf min: {wp.min_supply_c} °C",
                f"Vorlauf max: {wp.max_supply_c} °C",
                f"Steilheit (Neigung): {wp.slope}",
                f"Niveau: {wp.level} K",
                "",
                "COP-KENNFELD",
                f"A-7/W35: {wp.cop_a_minus7_w35}",
                f"A2/W35: {wp.cop_a2_w35}",
                f"A7/W35: {wp.cop_a7_w35}",
                f"A-7/W45: {wp.cop_a_minus7_w45}",
                f"A2/W45: {wp.cop_a2_w45}",
                f"A7/W45: {wp.cop_a7_w45}",
                f"A-7/W55: {wp.cop_a_minus7_w55}",
                f"A2/W55: {wp.cop_a2_w55}",
                f"A7/W55: {wp.cop_a7_w55}",
                "",
                "BRENNWERTKESSEL",
                f"Investition: {boiler.investment_eur} €",
                f"Förderung: {boiler.subsidy_eur} €",
                f"Lebensdauer: {boiler.lifetime_years} a",
                f"Wartung: {boiler.maintenance_eur_year} €/a",
                f"Gaspreis: {boiler.gas_price} €/kWh",
                f"Gaspreissteigerung: {boiler.gas_escalation} %/a",
                f"Kalkulationszins: {boiler.discount_rate * 100} %",
                f"Wirkungsgrad: {boiler.efficiency * 100:.2f} %",
                f"Gas-Grundpreis: {boiler.gas_base_fee_year} €/a",
                f"Schornsteinfeger: {boiler.chimney_year} €/a",
                f"CO2-Preis: {boiler.co2_price_eur_per_ton} €/t",
                "",
                "HINWEIS",
                "Modellrechnung; keine Hersteller-/Energieberatung.",
            ]

            Path(filename).write_text(
                "\n".join(lines),
                encoding="utf-8"
            )

            messagebox.showinfo(
                "Export",
                f"Parameter gespeichert:\n{filename}"
            )

        except Exception as exc:
            messagebox.showerror("Exportfehler", str(exc))


def main():
    root = tk.Tk()

    # Modernes ttk-Theme, sofern vorhanden
    try:
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass

    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()