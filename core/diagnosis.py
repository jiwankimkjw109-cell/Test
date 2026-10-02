"""연소 진단: 공기비 역산, 열수지(배가스 손실·유효열·효율), 판정 (PRD 3.3, 4.4, 4.5).

열수지 (연료 1 Nm³ 기준, 기준온도 t_ref)
  입열      = LHV + 연소공기 현열 + 연료 현열
  유효열 AH = 입열 − 배가스 현열 손실 − 불완전연소(CO) 손실
  효율      = AH / 발열량 (LHV 또는 HHV 기준)
  HHV 기준일 때는 (HHV − LHV) 를 배가스 잠열 손실로 별도 표시한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache

from scipy.optimize import brentq

from . import DATA_DIR, V_NORMAL
from .combustion import NO_COMBUSTIBLE_MSG, AirSpec, FlueGas, flue_products, theoretical_oxygen
from .fuel import Fuel
from .species import get_species

CO2_CHECK_TOL = 0.5  # vol%p, 측정·계산 CO₂ 허용 차이


def air_ratio_from_o2_simple(o2_dry_pct: float, o2_air_pct: float = 21.0) -> float:
    """간이식 m = 21 / (21 − O₂,dry) [-]. o2_dry_pct [vol%, dry]."""
    if not 0 <= o2_dry_pct < o2_air_pct - 0.1:
        raise ValueError(f"O₂ 측정값은 0 이상 {o2_air_pct - 0.1:g} vol% 미만이어야 함")
    return o2_air_pct / (o2_air_pct - o2_dry_pct)


def air_ratio_n2_formula(o2_dry_pct: float, co2_dry_pct: float, co_dry_pct: float = 0.0) -> float:
    """N₂ 기준식 m = N₂ / (N₂ − 3.76 (O₂ − 0.5 CO)), N₂ = 100 − CO₂ − O₂ − CO (dry vol%).

    연료 중 N₂ 를 무시하므로 BFG 처럼 N₂ 가 많은 연료에는 부적합.
    """
    n2 = 100.0 - co2_dry_pct - o2_dry_pct - co_dry_pct
    denom = n2 - 79.0 / 21.0 * (o2_dry_pct - 0.5 * co_dry_pct)
    if n2 <= 0 or denom <= 0:
        raise ValueError("배가스 조성이 올바르지 않아 N₂ 기준 공기비를 계산할 수 없음")
    return n2 / denom


def flue_with_co(fuel: Fuel, air_ratio: float, air: AirSpec, co_ppm_dry: float = 0.0) -> FlueGas:
    """공기비 m (≥ 1) 의 배가스에서 dry 기준 CO co_ppm_dry 만큼 CO₂ 가 CO 로 남은 조성.

    CO z [Nm³]: CO₂ −z, O₂ +z/2. z 는 결과 dry 농도가 co_ppm_dry 가 되도록 결정.
    """
    a_dry = air_ratio * theoretical_oxygen(fuel) / air.x_o2
    vols = flue_products(fuel, a_dry, air)
    y = co_ppm_dry * 1e-6
    if y <= 0:
        return FlueGas(vols)
    g_dry = sum(v for k, v in vols.items() if k != "H2O")
    z = min(y * g_dry / (1 - y / 2), vols.get("CO2", 0.0))
    vols = dict(vols)
    vols["CO2"] = vols.get("CO2", 0.0) - z
    vols["CO"] = z
    vols["O2"] = vols.get("O2", 0.0) + z / 2
    return FlueGas({k: v for k, v in vols.items() if v > 1e-12})


def flue_o2_pct(fuel: Fuel, air_ratio: float, air: AirSpec, basis: str = "dry", co_ppm_dry: float = 0.0) -> float:
    """공기비 m 에서의 배가스 O₂ [vol%] (basis "dry" | "wet")."""
    g = flue_with_co(fuel, air_ratio, air, co_ppm_dry)
    comp = g.composition_dry() if basis == "dry" else g.composition_wet()
    return comp.get("O2", 0.0)


def air_ratio_from_flue_o2(
    fuel: Fuel,
    o2_pct: float,
    basis: str = "dry",
    air: AirSpec | None = None,
    co_ppm_dry: float = 0.0,
) -> float:
    """배가스 O₂ [vol%] → 연료 조성 반영 공기비 (brentq, CO 보정).

    O₂ 가 m = 1 의 값 이하이면 1.0 을 반환 (O₂ 만으로는 공기 부족 정도를 알 수 없음).
    """
    air = air or AirSpec.standard()
    if basis not in ("dry", "wet"):
        raise ValueError("basis 는 'dry' 또는 'wet'")
    if theoretical_oxygen(fuel) <= 0:
        raise ValueError(NO_COMBUSTIBLE_MSG)
    # O₂ 상한: 공기를 무한히 넣었을 때의 배가스 O₂ (wet 은 공기 습분만큼 낮음)
    o2_max = air.x_o2 * 100.0 if basis == "dry" else air.x_o2 * 100.0 / (1.0 + air.h2o_per_dry_air)
    if not 0 <= o2_pct < o2_max - 0.1:
        raise ValueError(f"O₂ 측정값은 0 이상 {o2_max - 0.1:.2f} vol% 미만이어야 합니다 ({basis} 기준)")
    if basis == "dry" and flue_o2_pct(fuel, 1.5, air, "dry") > 99.9:
        raise ValueError("건배가스에 O₂ 외 성분이 없어(예: 수소 + 순산소) dry O₂ 로 공기비를 구할 수 없습니다. wet 기준을 사용하세요")

    def f(m: float) -> float:
        return flue_o2_pct(fuel, m, air, basis, co_ppm_dry) - o2_pct

    if f(1.0) >= 0:
        return 1.0
    if f(2000.0) <= 0:
        raise ValueError(f"측정 O₂ {o2_pct:g}% 는 이 연료·공기 조건에서 나올 수 없는 값입니다. 측정 기준(dry/wet)과 값을 확인하세요")
    return brentq(f, 1.0, 2000.0, xtol=1e-6)


@dataclass(frozen=True)
class HeatBalance:
    """연료 1 Nm³ 기준 열수지 [kJ/Nm³-fuel]."""

    lhv: float
    hhv: float
    air_sensible: float
    fuel_sensible: float
    flue_sensible: float
    incomplete: float
    flue: FlueGas = field(repr=False)

    @property
    def heat_input(self) -> float:
        """입열 = LHV + 공기·연료 현열."""
        return self.lhv + self.air_sensible + self.fuel_sensible

    @property
    def available(self) -> float:
        """유효열 = 입열 − 배가스 현열 − 불완전연소 손실."""
        return self.heat_input - self.flue_sensible - self.incomplete

    def hv(self, basis: str = "LHV") -> float:
        return self.hhv if basis == "HHV" else self.lhv

    def latent(self, basis: str = "LHV") -> float:
        """배가스 잠열 손실 (HHV 기준에서만 HHV − LHV)."""
        return self.hhv - self.lhv if basis == "HHV" else 0.0

    def efficiency(self, basis: str = "LHV") -> float:
        """효율 [-] = 유효열 / 발열량."""
        return self.available / self.hv(basis)


def heat_balance(
    fuel: Fuel,
    air_ratio: float,
    flue_temp_c: float,
    air: AirSpec | None = None,
    t_air_c: float = 25.0,
    t_fuel_c: float = 25.0,
    t_ref_c: float = 25.0,
    co_ppm_dry: float = 0.0,
) -> HeatBalance:
    """공기비·배가스 온도에서의 열수지 (공기비 ≥ 1)."""
    air = air or AirSpec.standard()
    if air_ratio < 1.0:
        raise ValueError("열수지 계산은 공기비 1.0 이상에서 지원")
    props = fuel.properties()
    if props.lhv_vol <= 0 or theoretical_oxygen(fuel) <= 0:
        raise ValueError(NO_COMBUSTIBLE_MSG)
    t_ref_k = t_ref_c + 273.15
    a_dry = air_ratio * theoretical_oxygen(fuel) / air.x_o2  # Nm³/Nm³-fuel
    air_sens = a_dry / V_NORMAL * sum(
        n * (get_species(k).h(t_air_c + 273.15) - get_species(k).h(t_ref_k)) for k, n in air.kmol_per_dry().items()
    )
    fuel_sens = sum(
        x * (get_species(k).h(t_fuel_c + 273.15) - get_species(k).h(t_ref_k)) for k, x in fuel.mole_fractions().items()
    ) / V_NORMAL
    flue = flue_with_co(fuel, air_ratio, air, co_ppm_dry)
    return HeatBalance(
        lhv=props.lhv_vol * 1000.0,
        hhv=props.hhv_vol * 1000.0,
        air_sensible=float(air_sens),
        fuel_sensible=float(fuel_sens),
        flue_sensible=flue.enthalpy_rise(flue_temp_c, t_ref_c),
        incomplete=flue.volumes.get("CO", 0.0) * get_species("CO").lhv_vol * 1000.0,
        flue=flue,
    )


@lru_cache(maxsize=1)
def load_criteria() -> dict:
    return json.loads((DATA_DIR / "diagnosis_criteria.json").read_text(encoding="utf-8"))


def judge(
    air_ratio: float,
    ratio_min: float,
    ratio_max: float,
    caution_margin: float = 0.10,
    co_ppm: float = 0.0,
    co_limit_ppm: float = 200.0,
) -> tuple[str, list[str]]:
    """권장 공기비 범위 대비 판정 → ("양호"|"주의"|"개선 필요", 사유 목록)."""
    reasons: list[str] = []
    verdict = "양호"
    if air_ratio > ratio_max + caution_margin:
        verdict = "개선 필요"
        reasons.append(f"공기비 {air_ratio:.2f} 가 권장 상한 {ratio_max:.2f} 를 크게 초과 (과잉공기 손실)")
    elif air_ratio > ratio_max:
        verdict = "주의"
        reasons.append(f"공기비 {air_ratio:.2f} 가 권장 상한 {ratio_max:.2f} 초과")
    elif air_ratio < ratio_min:
        verdict = "주의"
        reasons.append(f"공기비 {air_ratio:.2f} 가 권장 하한 {ratio_min:.2f} 미만 (불완전연소 위험)")
    if co_ppm > co_limit_ppm:
        if verdict == "양호":
            verdict = "주의"
        reasons.append(f"CO {co_ppm:.0f} ppm 이 기준 {co_limit_ppm:.0f} ppm 초과 (불완전연소)")
    if not reasons:
        reasons.append("권장 범위 이내")
    return verdict, reasons


@dataclass(frozen=True)
class DiagnosisResult:
    air_ratio_simple: float  # m = 21/(21 − O₂,dry) [-]
    air_ratio: float  # 연료 조성 반영 정밀 공기비 [-]
    air_ratio_n2: float | None  # N₂ 기준식 (CO₂ 측정 시) [-]
    o2_dry: float  # vol%
    o2_wet: float  # vol%
    co2_calc_dry: float  # vol%
    co2_meas_dry: float | None  # vol%
    balance: HeatBalance
    hv_basis: str  # "LHV" | "HHV"
    fuel_flow_nm3h: float
    verdict: str
    reasons: list[str]
    warnings: list[str]

    def kw(self, kj_per_nm3: float) -> float:
        """연료 1 Nm³ 당 kJ → kW (연료 유량 반영)."""
        return kj_per_nm3 * self.fuel_flow_nm3h / 3600.0

    @property
    def efficiency_pct(self) -> float:
        return self.balance.efficiency(self.hv_basis) * 100.0

    def pct(self, kj_per_nm3: float) -> float:
        """발열량 기준 백분율 [%]."""
        return kj_per_nm3 / self.balance.hv(self.hv_basis) * 100.0


def diagnose(
    fuel: Fuel,
    fuel_flow_nm3h: float,
    o2_pct: float,
    flue_temp_c: float,
    basis: str = "dry",
    co_ppm: float = 0.0,
    co2_meas_dry_pct: float | None = None,
    t_air_c: float = 25.0,
    t_fuel_c: float = 25.0,
    t_ref_c: float = 25.0,
    hv_basis: str = "LHV",
    air: AirSpec | None = None,
    ratio_min: float = 1.05,
    ratio_max: float = 1.20,
    caution_margin: float = 0.10,
    co_limit_ppm: float = 200.0,
) -> DiagnosisResult:
    """현장 측정값 (O₂, CO [ppm, dry], CO₂ [vol%, dry], 배가스 온도) 으로 공기비·손실·효율을 계산하고 판정."""
    air = air or AirSpec.standard()
    if fuel_flow_nm3h < 0:
        raise ValueError("연료 유량은 음수일 수 없음")
    warnings: list[str] = []
    m = air_ratio_from_flue_o2(fuel, o2_pct, basis, air, co_ppm)
    flue = flue_with_co(fuel, m, air, co_ppm)
    o2_dry = flue.composition_dry().get("O2", 0.0)
    m_simple = air_ratio_from_o2_simple(o2_dry, air.x_o2 * 100.0)
    if m == 1.0 and o2_pct <= flue_o2_pct(fuel, 1.0, air, basis, co_ppm):
        warnings.append("O₂ 가 이론공기 조건 이하입니다. 공기 부족 여부는 CO·H₂ 측정으로 확인하세요.")

    m_n2 = None
    co2_calc = flue.composition_dry().get("CO2", 0.0)
    if co2_meas_dry_pct is not None:
        diff = co2_meas_dry_pct - co2_calc
        if abs(diff) > CO2_CHECK_TOL:
            warnings.append(
                f"측정 CO₂ {co2_meas_dry_pct:.2f}% 와 계산 CO₂ {co2_calc:.2f}% 가 {diff:+.2f}%p 차이 — "
                "연료 조성 변동, 분석기 교정, 샘플링 위치(공기 침입)를 점검하세요."
            )
        try:
            m_n2 = air_ratio_n2_formula(o2_dry, co2_meas_dry_pct, co_ppm * 1e-4)
        except ValueError as e:
            warnings.append(str(e))

    bal = heat_balance(fuel, m, flue_temp_c, air, t_air_c, t_fuel_c, t_ref_c, co_ppm)
    if bal.available <= 0:
        raise ValueError(
            f"유효열이 0 이하입니다 (공기비 {m:.2f}, 배가스 {flue_temp_c:,.0f} °C 에서 배가스 손실이 입열보다 큼). "
            "O₂ 측정 위치(공기 침입)와 배가스 온도를 확인하세요"
        )
    if m > 3.0:
        warnings.append(f"공기비 {m:.2f} 는 연소 설비로서 비정상적으로 큽니다. 측정 위치에서 공기가 새어 들어오는지 확인하세요.")
    if flue_temp_c < flue.dew_point():
        warnings.append(f"배가스 온도가 노점 {flue.dew_point():.1f} °C 보다 낮습니다 (응축·부식 주의).")
    verdict, reasons = judge(m, ratio_min, ratio_max, caution_margin, co_ppm, co_limit_ppm)
    return DiagnosisResult(
        air_ratio_simple=m_simple,
        air_ratio=m,
        air_ratio_n2=m_n2,
        o2_dry=o2_dry,
        o2_wet=flue.composition_wet().get("O2", 0.0),
        co2_calc_dry=co2_calc,
        co2_meas_dry=co2_meas_dry_pct,
        balance=bal,
        hv_basis=hv_basis,
        fuel_flow_nm3h=fuel_flow_nm3h,
        verdict=verdict,
        reasons=reasons,
        warnings=warnings,
    )
