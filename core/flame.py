"""단열화염온도 (PRD 3.2 C-10, 4.3).

에너지 보존: Σ nᵢ·hᵢ(T_reactants) = Σ nⱼ·hⱼ(T_ad), scipy.optimize.brentq 로 풀이.
- "complete": 해리 무시. 공기비 < 1 이면 T_ad 에서의 수성가스 평형 조성을 사용 (조성-온도 동시 수렴).
- "equilibrium": 화학평형(해리 반영) — P2, 미구현.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq

from . import V_NORMAL
from .combustion import AIR_RATIO_MAX, AIR_RATIO_MIN, NO_COMBUSTIBLE_MSG, AirSpec, FlueGas, flue_products, theoretical_oxygen
from .fuel import Fuel
from .species import get_species, mixture_h

T_SEARCH = (250.0, 5900.0)  # K, NASA 다항식 유효범위 내


@dataclass(frozen=True)
class FlameResult:
    t_ad_k: float  # 단열화염온도 [K]
    mode: str  # "complete" | "equilibrium"
    products: FlueGas  # T_ad 에서의 생성물 [Nm³/Nm³-fuel]
    reactant_enthalpy: float  # 반응물 엔탈피 [kJ/Nm³-fuel] (생성엔탈피 포함)

    @property
    def t_ad_c(self) -> float:
        return self.t_ad_k - 273.15


def reactant_enthalpy(fuel: Fuel, air_dry: float, air: AirSpec, t_fuel_k: float, t_air_k: float) -> float:
    """반응물 엔탈피 [kJ/kmol-fuel] = 연료(t_fuel) + 산화제·수분(t_air)."""
    h_fuel = sum(x * get_species(k).h(t_fuel_k) for k, x in fuel.mole_fractions().items())
    h_air = air_dry * sum(n * get_species(k).h(t_air_k) for k, n in air.kmol_per_dry().items())
    return float(h_fuel + h_air)


def adiabatic_flame_temperature(
    fuel: Fuel,
    air_ratio: float,
    air: AirSpec | None = None,
    t_fuel_c: float = 25.0,
    t_air_c: float = 25.0,
    mode: str = "complete",
) -> FlameResult:
    """단열화염온도 계산.

    fuel: 연료, air_ratio: 공기비 m [-] (0.5~5.0)
    t_fuel_c, t_air_c: 연료·연소공기 온도 [°C] (예열 반영)
    mode: "complete"(해리 무시) | "equilibrium"(P2)
    """
    if mode != "complete":
        raise NotImplementedError("화학평형 모드는 향후 지원 예정 (PRD P2)")
    air = air or AirSpec.standard()
    if not AIR_RATIO_MIN <= air_ratio <= AIR_RATIO_MAX:
        raise ValueError(f"공기비는 {AIR_RATIO_MIN}~{AIR_RATIO_MAX} 범위여야 함")
    o2_0 = theoretical_oxygen(fuel)
    if o2_0 <= 0:
        raise ValueError(NO_COMBUSTIBLE_MSG)
    air_dry = air_ratio * o2_0 / air.x_o2
    h_r = reactant_enthalpy(fuel, air_dry, air, t_fuel_c + 273.15, t_air_c + 273.15)

    def residual(t_k: float) -> float:
        vols = flue_products(fuel, air_dry, air, t_k)
        return mixture_h(vols, t_k) - h_r  # vols [kmol/kmol-fuel] 와 수치 동일

    lo, hi = T_SEARCH
    if residual(lo) > 0:
        raise ValueError("반응물 엔탈피가 너무 낮아 화염온도를 계산할 수 없음 (발열량 부족)")
    if residual(hi) < 0:
        raise ValueError("화염온도가 물성 유효범위(6000 K)를 초과함")
    t_ad = brentq(residual, lo, hi, xtol=1e-3)
    return FlameResult(
        t_ad_k=t_ad,
        mode=mode,
        products=FlueGas(flue_products(fuel, air_dry, air, t_ad)),
        reactant_enthalpy=h_r / V_NORMAL,
    )


def flame_curve(
    fuel: Fuel,
    air_ratios,
    air: AirSpec | None = None,
    t_fuel_c: float = 25.0,
    t_air_c: float = 25.0,
) -> list[FlameResult | None]:
    """여러 공기비에 대한 단열화염온도 (계산 불가 점은 None)."""
    out: list[FlameResult | None] = []
    for m in np.atleast_1d(air_ratios):
        try:
            out.append(adiabatic_flame_temperature(fuel, float(m), air, t_fuel_c, t_air_c))
        except ValueError:
            out.append(None)
    return out
