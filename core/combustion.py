"""양론 연소 계산: 이론산소량, 이론/실제 공기량, 배가스량·조성 (PRD 3.2, 4.1~4.2).

모든 체적은 Normal 상태(0 °C, 101.325 kPa) 기준, 연료 1 Nm³ 당 값.
- 공기비 ≥ 1: 완전연소 (CO₂, H₂O, SO₂, O₂, N₂, Ar)
- 공기비 < 1: 수성가스 평형 CO + H₂O ⇌ CO₂ + H₂ 로 CO·H₂ 생성 (평형온도 필요)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import P_NORMAL, R_UNIVERSAL, T_REF, V_NORMAL
from .fuel import Fuel
from .species import get_species, mixture_cp, mixture_h

M_H2O = 18.015  # kg/kmol
NO_COMBUSTIBLE_MSG = "가연 성분이 없는 연료입니다. 연료 설정에서 조성을 확인하세요"
AIR_RATIO_MIN, AIR_RATIO_MAX = 0.5, 5.0


@dataclass(frozen=True)
class AirSpec:
    """연소용 산화제 조성과 습도.

    dry: 건조 산화제 몰분율 {O2, N2, Ar, CO2} (합 1)
    humidity: 절대습도 [kg-H2O/kg-건조 산화제]
    """

    dry: dict[str, float] = field(default_factory=lambda: {"O2": 0.2095, "N2": 0.7809, "Ar": 0.0093, "CO2": 0.0003})
    humidity: float = 0.0

    @classmethod
    def standard(cls, humidity: float = 0.0) -> "AirSpec":
        """표준 건공기 O₂ 20.95 / N₂ 78.09 / Ar 0.93 / CO₂ 0.03 vol%."""
        return cls(humidity=humidity)

    @classmethod
    def simplified(cls, humidity: float = 0.0) -> "AirSpec":
        """단순화 공기 O₂ 21 / N₂ 79 vol%."""
        return cls({"O2": 0.21, "N2": 0.79}, humidity)

    @classmethod
    def enriched(cls, o2_pct: float, humidity: float = 0.0) -> "AirSpec":
        """산소부화공기 (O₂ o2_pct vol%, 나머지 N₂). o2_pct = 100 이면 순산소."""
        if not 21.0 <= o2_pct <= 100.0:
            raise ValueError("산소부화 O₂ 농도는 21~100 vol% 범위")
        dry = {"O2": o2_pct / 100.0}
        if o2_pct < 100.0:
            dry["N2"] = 1.0 - o2_pct / 100.0
        return cls(dry, humidity)

    def __post_init__(self) -> None:
        if abs(sum(self.dry.values()) - 1.0) > 1e-6:
            raise ValueError("산화제 조성 몰분율 합이 1이 아님")
        if self.dry.get("O2", 0) <= 0:
            raise ValueError("산화제 중 O₂ 가 0 임")
        if self.humidity < 0:
            raise ValueError("절대습도는 음수일 수 없음")

    @property
    def x_o2(self) -> float:
        return self.dry["O2"]

    @property
    def mw_dry(self) -> float:
        """건조 산화제 분자량 [kg/kmol]."""
        return sum(x * get_species(k).mw for k, x in self.dry.items())

    @property
    def h2o_per_dry_air(self) -> float:
        """건조 산화제 1 Nm³ 당 수증기 [Nm³/Nm³]."""
        return self.humidity * self.mw_dry / M_H2O

    def kmol_per_dry(self) -> dict[str, float]:
        """건조 산화제 1 kmol 당 성분 kmol (수증기 포함)."""
        out = dict(self.dry)
        w = self.h2o_per_dry_air
        if w > 0:
            out["H2O"] = w
        return out


def saturation_pressure(t_c: float) -> float:
    """물의 포화증기압 [kPa] (Buck 1981, 수면 기준, −40~100 °C 권장)."""
    return 0.61121 * math.exp((18.678 - t_c / 234.5) * (t_c / (257.14 + t_c)))


def dew_point(p_h2o_kpa: float) -> float:
    """수증기 분압 [kPa] → 노점 [°C] (saturation_pressure 의 역함수, Newton 반복)."""
    if p_h2o_kpa <= 0:
        return float("nan")
    t = 50.0
    for _ in range(50):
        f = saturation_pressure(t) - p_h2o_kpa
        dfdt = (saturation_pressure(t + 1e-3) - saturation_pressure(t - 1e-3)) / 2e-3
        step = f / dfdt
        t -= step
        if abs(step) < 1e-6:
            break
    return t


def humidity_from_rh(rh_pct: float, t_c: float, p_kpa: float = P_NORMAL) -> float:
    """상대습도 [%] + 건구온도 [°C] → 절대습도 [kg/kg-건공기]."""
    if not 0 <= rh_pct <= 100:
        raise ValueError("상대습도는 0~100 % 범위")
    pv = rh_pct / 100.0 * saturation_pressure(t_c)
    if pv >= p_kpa:
        raise ValueError("수증기 분압이 전압 이상임")
    return 0.62198 * pv / (p_kpa - pv)


@dataclass(frozen=True)
class FlueGas:
    """배가스 (연료 1 Nm³ 당 성분별 Nm³)."""

    volumes: dict[str, float]  # Nm³/Nm³-fuel

    @property
    def wet(self) -> float:
        return sum(self.volumes.values())

    @property
    def dry(self) -> float:
        return self.wet - self.volumes.get("H2O", 0.0)

    def composition_wet(self) -> dict[str, float]:
        """Wet 기준 vol%."""
        g = self.wet
        return {k: v / g * 100.0 for k, v in self.volumes.items()}

    def composition_dry(self) -> dict[str, float]:
        """Dry 기준 vol% (H₂O 제외). 건배가스가 없으면 (예: H₂ + 순산소, m = 1) 빈 dict."""
        g = self.dry
        if g <= 1e-12:
            return {}
        return {k: v / g * 100.0 for k, v in self.volumes.items() if k != "H2O"}

    @property
    def mass(self) -> float:
        """배가스 질량 [kg/Nm³-fuel]."""
        return sum(v / V_NORMAL * get_species(k).mw for k, v in self.volumes.items())

    @property
    def density(self) -> float:
        """배가스 밀도 (Wet) [kg/Nm³]."""
        return self.mass / self.wet

    def kmol(self) -> dict[str, float]:
        """연료 1 Nm³ 당 kmol."""
        return {k: v / V_NORMAL for k, v in self.volumes.items()}

    def enthalpy_rise(self, t_c: float, t_ref_c: float = 25.0) -> float:
        """배가스 현열 h(t) − h(t_ref) [kJ/Nm³-fuel]."""
        n = self.kmol()
        return mixture_h(n, t_c + 273.15) - mixture_h(n, t_ref_c + 273.15)

    def mean_cp(self, t_c: float) -> float:
        """25 °C ~ t_c 평균 정압비열 [kJ/(Nm³·K)] (Wet 배가스 기준)."""
        t_k = t_c + 273.15
        if abs(t_k - T_REF) < 1e-6:
            return mixture_cp(self.kmol(), T_REF) / self.wet
        return self.enthalpy_rise(t_c) / (t_k - T_REF) / self.wet

    def dew_point(self, p_kpa: float = P_NORMAL) -> float:
        """배가스 수증기 노점 [°C]."""
        y = self.volumes.get("H2O", 0.0) / self.wet
        return dew_point(y * p_kpa)


@dataclass(frozen=True)
class CombustionResult:
    """연소 계산 결과 (연료 1 Nm³ 기준). 단위는 필드 주석 참조."""

    fuel_name: str
    air_ratio: float  # m (λ)
    o2_theoretical: float  # O₀ [Nm³/Nm³-fuel]
    o2_theoretical_mass: float  # O₀ [Nm³/kg-fuel]
    air_theoretical_dry: float  # A₀,dry [Nm³/Nm³-fuel]
    air_theoretical_wet: float  # A₀,wet [Nm³/Nm³-fuel]
    air_actual_dry: float  # A_dry [Nm³/Nm³-fuel]
    air_actual_wet: float  # A_wet [Nm³/Nm³-fuel]
    flue_theoretical: FlueGas  # m = 1
    flue: FlueGas  # 실제 공기비
    co2_max_dry: float  # vol%
    fuel_density: float  # kg/Nm³
    air_mass: float  # kg-습공기/Nm³-fuel
    air_fuel_mass_ratio: float  # kg-습공기/kg-fuel
    t_equilibrium_k: float | None = None  # 공기비 < 1 일 때 수성가스 평형온도 [K]

    @property
    def equivalence_ratio(self) -> float:
        """당량비 φ = 1/m."""
        return 1.0 / self.air_ratio

    @property
    def fuel_air_mass_ratio(self) -> float:
        return 1.0 / self.air_fuel_mass_ratio


def theoretical_oxygen(fuel: Fuel) -> float:
    """이론산소량 O₀ [Nm³/Nm³-fuel] = Σ xᵢ (C + H/4 + S − O/2)ᵢ."""
    return sum(x * get_species(k).o2_demand for k, x in fuel.mole_fractions().items())


def water_gas_k(t_k: float) -> float:
    """수성가스 반응 CO + H₂O ⇌ CO₂ + H₂ 평형상수 Kp [-]."""
    sp = {k: get_species(k) for k in ("CO", "H2O", "CO2", "H2")}
    dg = sp["CO2"].g(t_k) + sp["H2"].g(t_k) - sp["CO"].g(t_k) - sp["H2O"].g(t_k)
    return float(np.exp(-dg / (R_UNIVERSAL * t_k)))


def _water_gas_split(c: float, hh: float, o_avail: float, k: float) -> tuple[float, float, float, float]:
    """원소수지 + 수성가스 평형으로 (CO₂, CO, H₂O, H₂) [kmol] 계산.

    c: C 원자, hh: H₂ 분자 상당 (H/2), o_avail: SO₂ 를 제외한 가용 O 원자.
    """
    deficit = 2 * c + hh - o_avail  # = CO + H₂ (완전연소 대비 부족한 O 원자)
    if o_avail < c - 1e-12:
        raise ValueError("공기비가 너무 낮아 그을음(C) 생성 영역입니다")
    if c <= 1e-12:
        co = 0.0
    elif hh <= 1e-12:
        co = deficit
    else:
        lo, hi = max(0.0, deficit - hh), min(c, deficit)
        qa = 1.0 - k
        qb = -(c + deficit + k * (hh - deficit))
        qc = c * deficit
        if abs(qa) < 1e-12:
            roots = [-qc / qb]
        else:
            disc = math.sqrt(max(qb * qb - 4 * qa * qc, 0.0))
            roots = [(-qb - disc) / (2 * qa), (-qb + disc) / (2 * qa)]
        valid = [r for r in roots if lo - 1e-9 <= r <= hi + 1e-9]
        if not valid:
            raise ValueError("수성가스 평형 해를 찾을 수 없습니다")
        co = min(max(valid[0], lo), hi)
    h2 = deficit - co
    return c - co, co, hh - h2, h2


def flue_products(fuel: Fuel, air_dry: float, air: AirSpec, t_eq_k: float | None = None) -> dict[str, float]:
    """연료 1 Nm³ + 건조 산화제 air_dry [Nm³] 의 연소 생성물 [Nm³/Nm³-fuel].

    산소가 부족하면 t_eq_k [K] 에서의 수성가스 평형으로 CO·H₂ 를 계산한다.
    """
    el = fuel.elements()
    w = air.h2o_per_dry_air
    c = el.get("C", 0.0) + air_dry * air.dry.get("CO2", 0.0)
    h = el.get("H", 0.0) + 2 * air_dry * w
    o = el.get("O", 0.0) + air_dry * (2 * air.x_o2 + 2 * air.dry.get("CO2", 0.0) + w)
    s = el.get("S", 0.0)
    o_avail = o - 2 * s
    vols = {
        "SO2": s,
        "N2": el.get("N", 0.0) / 2 + air_dry * air.dry.get("N2", 0.0),
        "Ar": el.get("Ar", 0.0) + air_dry * air.dry.get("Ar", 0.0),
    }
    need = 2 * c + h / 2
    if o_avail >= need - 1e-12:
        vols.update({"CO2": c, "H2O": h / 2, "O2": max(o_avail - need, 0.0) / 2})
    else:
        if t_eq_k is None:
            raise ValueError("공기 부족 조건의 배가스 조성 계산에는 평형온도가 필요함")
        co2, co, h2o, h2 = _water_gas_split(c, h / 2, o_avail, water_gas_k(t_eq_k))
        vols.update({"CO2": co2, "CO": co, "H2O": h2o, "H2": h2})
    return {k: v for k, v in vols.items() if v > 1e-12}


def combustion(
    fuel: Fuel,
    air_ratio: float,
    air: AirSpec | None = None,
    t_eq_k: float | None = None,
) -> CombustionResult:
    """연료 + 공기비 → 공기량, 배가스량·조성.

    air_ratio: 공기비 m (= 실제공기량/이론공기량), 0.5 ≤ m ≤ 5.0
    t_eq_k: 공기비 < 1 일 때 수성가스 평형온도 [K]. 생략하면 단열화염온도(반응물 25 °C)를 사용.
    """
    air = air or AirSpec.standard()
    if not AIR_RATIO_MIN <= air_ratio <= AIR_RATIO_MAX:
        raise ValueError(f"공기비는 {AIR_RATIO_MIN}~{AIR_RATIO_MAX} 범위여야 함")
    o2_0 = theoretical_oxygen(fuel)
    if o2_0 <= 0:
        raise ValueError(NO_COMBUSTIBLE_MSG)
    if air_ratio < 1.0 and t_eq_k is None:
        from .flame import adiabatic_flame_temperature

        t_eq_k = adiabatic_flame_temperature(fuel, air_ratio, air).t_ad_k
    props = fuel.properties()
    w = air.h2o_per_dry_air

    a0_dry = o2_0 / air.x_o2
    a_dry = air_ratio * a0_dry
    flue0 = FlueGas(flue_products(fuel, a0_dry, air))
    flue = FlueGas(flue_products(fuel, a_dry, air, t_eq_k))

    air_mass = a_dry / V_NORMAL * (air.mw_dry + w * M_H2O)
    fuel_mass = props.density  # kg/Nm³-fuel
    return CombustionResult(
        fuel_name=fuel.name,
        air_ratio=air_ratio,
        o2_theoretical=o2_0,
        o2_theoretical_mass=o2_0 / fuel_mass,
        air_theoretical_dry=a0_dry,
        air_theoretical_wet=a0_dry * (1 + w),
        air_actual_dry=a_dry,
        air_actual_wet=a_dry * (1 + w),
        flue_theoretical=flue0,
        flue=flue,
        co2_max_dry=flue0.volumes.get("CO2", 0.0) / flue0.dry * 100.0 if flue0.dry > 1e-12 else float("nan"),
        fuel_density=fuel_mass,
        air_mass=air_mass,
        air_fuel_mass_ratio=air_mass / fuel_mass,
        t_equilibrium_k=t_eq_k if air_ratio < 1.0 else None,
    )


def air_ratio_from_air_flow(fuel: Fuel, fuel_flow: float, air_flow_dry: float, air: AirSpec | None = None) -> float:
    """연료 유량 [Nm³/h] 과 건조 산화제 유량 [Nm³/h] → 공기비 m."""
    air = air or AirSpec.standard()
    if fuel_flow <= 0:
        raise ValueError("연료 유량은 0보다 커야 함")
    o2_0 = theoretical_oxygen(fuel)
    if o2_0 <= 0:
        raise ValueError(NO_COMBUSTIBLE_MSG)
    return air_flow_dry / (fuel_flow * o2_0 / air.x_o2)
