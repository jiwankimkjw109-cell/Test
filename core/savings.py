"""공기비 개선 절감량 (PRD 3.4).

동일 유효열(공정 요구 열량) 유지 가정:
  연료량 ∝ 1 / AH  →  절감률 S = 1 − AH₁/AH₂  (AH: 연료 1 Nm³ 당 유효열)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import pandas as pd

from . import DATA_DIR, V_NORMAL
from .combustion import AirSpec
from .diagnosis import HeatBalance, heat_balance
from .fuel import Fuel

KCAL_KJ = 4.1868
GJ_PER_GCAL = 4.1868
GJ_PER_TOE = 41.868  # 1 TOE = 10⁷ kcal
M_CO2 = 44.009
PRICE_UNITS = ("원/Gcal", "원/Nm3", "원/GJ", "원/MJ")


@lru_cache(maxsize=1)
def _emission_factors() -> dict:
    return json.loads((DATA_DIR / "emission_factors.json").read_text(encoding="utf-8"))["factors"]


def default_co2_factor(fuel_name: str) -> float | None:
    """연료별 고정 배출계수 [tCO₂/TJ, LHV 기준]. 탄소수지 방식이면 None."""
    f = _emission_factors().get(fuel_name, {})
    return f.get("value_tCO2_per_TJ") if f.get("method") == "fixed" else None


def co2_kg_per_nm3(fuel: Fuel, factor_t_per_tj: float | None = None) -> float:
    """연료 1 Nm³ 연소 시 CO₂ 배출량 [kg/Nm³].

    factor_t_per_tj 가 주어지면 배출계수 × LHV, 없으면 탄소수지 (C 원자 × 44.009/22.414).
    """
    if factor_t_per_tj is not None:
        return factor_t_per_tj * fuel.properties().lhv_vol * 1e-3  # t/TJ × MJ/Nm³ → kg/Nm³
    return fuel.elements().get("C", 0.0) * M_CO2 / V_NORMAL


def fuel_saving_rate(ah_before: float, ah_after: float) -> float:
    """절감률 S = 1 − AH₁/AH₂ [-]. AH: 연료 단위량당 유효열 (또는 유효열 비율 η)."""
    if ah_after <= 0 or ah_before <= 0:
        raise ValueError("유효열이 0 이하입니다 (배가스 온도 또는 공기비를 확인)")
    return 1.0 - ah_before / ah_after


@dataclass(frozen=True)
class SavingsResult:
    before: HeatBalance
    after: HeatBalance
    saving_rate: float  # [-]
    fuel_flow_nm3h: float  # 현재 연료량 [Nm³/h]
    hours_effective: float  # 연간 유효 가동시간 [h/yr]
    fuel_saved_nm3h: float  # [Nm³/h]
    fuel_saved_nm3yr: float  # [Nm³/yr]
    heat_saved_lhv_kw: float  # [kW], LHV 기준
    heat_saved_lhv_gj_yr: float  # [GJ/yr]
    heat_saved_hhv_gj_yr: float  # [GJ/yr]
    toe_yr: float  # [TOE/yr], HHV(총발열량) 기준
    cost_saved_krw_yr: float  # [원/yr]
    co2_reduced_t_yr: float  # [tCO₂/yr]
    co2_value_krw_yr: float  # [원/yr]

    @property
    def saving_rate_pct(self) -> float:
        return self.saving_rate * 100.0

    def heat_saved_gcal_yr(self, basis: str = "LHV") -> float:
        gj = self.heat_saved_hhv_gj_yr if basis == "HHV" else self.heat_saved_lhv_gj_yr
        return gj / GJ_PER_GCAL

    @property
    def total_value_krw_yr(self) -> float:
        return self.cost_saved_krw_yr + self.co2_value_krw_yr


def fuel_cost(nm3: float, fuel: Fuel, price: float, price_unit: str, price_hv_basis: str = "HHV") -> float:
    """연료 nm3 [Nm³] 의 금액 [원]. 열량 단가는 price_hv_basis 발열량 기준."""
    p = fuel.properties()
    hv_mj = p.hhv_vol if price_hv_basis == "HHV" else p.lhv_vol
    mj = nm3 * hv_mj
    if price_unit == "원/Nm3":
        return nm3 * price
    if price_unit == "원/Gcal":
        return mj / (GJ_PER_GCAL * 1e3) * price
    if price_unit == "원/GJ":
        return mj / 1e3 * price
    if price_unit == "원/MJ":
        return mj * price
    raise ValueError(f"지원하지 않는 단가 단위: {price_unit!r}")


def compute_savings(
    fuel: Fuel,
    fuel_flow_nm3h: float,
    air_ratio_before: float,
    air_ratio_after: float,
    flue_temp_before_c: float,
    flue_temp_after_c: float | None = None,
    hours_per_year: float = 8000.0,
    utilization_pct: float = 100.0,
    fuel_price: float = 0.0,
    price_unit: str = "원/Gcal",
    price_hv_basis: str = "HHV",
    co2_factor_t_per_tj: float | None = None,
    co2_price_krw_per_t: float = 0.0,
    t_air_c: float = 25.0,
    t_fuel_c: float = 25.0,
    t_ref_c: float = 25.0,
    air: AirSpec | None = None,
) -> SavingsResult:
    """공기비 개선 전·후 비교 절감량 계산.

    fuel_flow_nm3h: 현재(개선 전) 연료 사용량 [Nm³/h]
    flue_temp_after_c: 개선 후 배가스 온도 [°C] (None 이면 개선 전과 동일)
    co2_factor_t_per_tj: 배출계수 [tCO₂/TJ] (None 이면 탄소수지)
    """
    if fuel_flow_nm3h < 0 or hours_per_year < 0 or not 0 <= utilization_pct <= 100:
        raise ValueError("연료 유량·가동시간은 0 이상, 가동률은 0~100 % 범위")
    if flue_temp_after_c is None:
        flue_temp_after_c = flue_temp_before_c
    hb1 = heat_balance(fuel, air_ratio_before, flue_temp_before_c, air, t_air_c, t_fuel_c, t_ref_c)
    hb2 = heat_balance(fuel, air_ratio_after, flue_temp_after_c, air, t_air_c, t_fuel_c, t_ref_c)
    s = fuel_saving_rate(hb1.available, hb2.available)
    hours = hours_per_year * utilization_pct / 100.0
    saved_h = fuel_flow_nm3h * s
    saved_yr = saved_h * hours
    p = fuel.properties()
    lhv_gj = saved_yr * p.lhv_vol / 1e3
    hhv_gj = saved_yr * p.hhv_vol / 1e3
    co2_t = saved_yr * co2_kg_per_nm3(fuel, co2_factor_t_per_tj) / 1e3
    return SavingsResult(
        before=hb1,
        after=hb2,
        saving_rate=s,
        fuel_flow_nm3h=fuel_flow_nm3h,
        hours_effective=hours,
        fuel_saved_nm3h=saved_h,
        fuel_saved_nm3yr=saved_yr,
        heat_saved_lhv_kw=saved_h * p.lhv_vol / 3.6,
        heat_saved_lhv_gj_yr=lhv_gj,
        heat_saved_hhv_gj_yr=hhv_gj,
        toe_yr=hhv_gj / GJ_PER_TOE,
        cost_saved_krw_yr=fuel_cost(saved_yr, fuel, fuel_price, price_unit, price_hv_basis),
        co2_reduced_t_yr=co2_t,
        co2_value_krw_yr=co2_t * co2_price_krw_per_t,
    )


def sensitivity_table(
    fuel: Fuel,
    air_ratio_before: float,
    flue_temp_c: float,
    air_ratios=None,
    air: AirSpec | None = None,
    t_air_c: float = 25.0,
    t_fuel_c: float = 25.0,
    t_ref_c: float = 25.0,
    hv_basis: str = "LHV",
    flue_temp_after_c: float | None = None,
) -> pd.DataFrame:
    """개선 후 공기비별 절감률 민감도.

    현재 상태는 (air_ratio_before, flue_temp_c), 개선 후 각 공기비는 flue_temp_after_c
    (None 이면 flue_temp_c 와 동일) 에서 계산한다.

    반환 열: 공기비, 배가스 O2 dry [%], 유효열 [kJ/Nm³], 효율 [%], 절감률 [%]
    """
    from .diagnosis import flue_o2_pct

    if air_ratios is None:
        air_ratios = np.round(np.arange(1.05, 1.501, 0.05), 2)
    air = air or AirSpec.standard()
    t_after = flue_temp_c if flue_temp_after_c is None else flue_temp_after_c
    hb1 = heat_balance(fuel, air_ratio_before, flue_temp_c, air, t_air_c, t_fuel_c, t_ref_c)
    rows = []
    for m in air_ratios:
        hb = heat_balance(fuel, float(m), t_after, air, t_air_c, t_fuel_c, t_ref_c)
        rows.append(
            {
                "공기비": float(m),
                "배가스 O2 dry [%]": flue_o2_pct(fuel, float(m), air, "dry"),
                "유효열 [kJ/Nm3]": hb.available,
                "효율 [%]": hb.efficiency(hv_basis) * 100.0,
                "절감률 [%]": (1.0 - hb1.available / hb.available) * 100.0 if hb.available > 0 else float("nan"),
            }
        )
    return pd.DataFrame(rows)
