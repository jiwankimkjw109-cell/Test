"""표준산소농도 환산 (PRD 3.7, 4.6).

C_std = C_meas × (21 − O₂,std) / (21 − O₂,meas)   (Dry 기준)
ppm ↔ mg/Nm³: C[mg/Nm³] = C[ppm] × M / 22.414  (0 °C, 101.325 kPa)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

import pandas as pd

from . import DATA_DIR, V_NORMAL

O2_AIR_PCT = 21.0
O2_MEAS_MAX = 20.0  # vol%, 이 이상이면 분모가 작아 환산 오차가 과대 → 계산 거부


@lru_cache(maxsize=1)
def load_reference() -> dict:
    """data/standard_o2.json (시설별 표준산소농도 프리셋, 오염물질 분자량)."""
    return json.loads((DATA_DIR / "standard_o2.json").read_text(encoding="utf-8"))


def correction_factor(o2_meas_pct: float, o2_std_pct: float, o2_air_pct: float = O2_AIR_PCT) -> float:
    """환산 계수 (21 − O₂,std) / (21 − O₂,meas) [-]."""
    if not 0 <= o2_meas_pct < o2_air_pct:
        raise ValueError(f"측정 O₂ 는 0 이상 {o2_air_pct:g} vol% 미만이어야 함")
    if o2_meas_pct >= min(O2_MEAS_MAX, o2_air_pct - 0.1):
        raise ValueError(
            f"측정 O₂ {o2_meas_pct:g}% 가 {O2_MEAS_MAX:g}% 이상이어서 분모(21 − O₂)가 너무 작습니다. 환산할 수 없습니다."
        )
    if not 0 <= o2_std_pct < o2_air_pct:
        raise ValueError(f"표준산소농도는 0 이상 {o2_air_pct:g} vol% 미만이어야 함")
    return (o2_air_pct - o2_std_pct) / (o2_air_pct - o2_meas_pct)


def correct_to_reference_o2(c_meas: float, o2_meas_pct: float, o2_std_pct: float, o2_air_pct: float = O2_AIR_PCT) -> float:
    """측정 농도를 표준산소농도 기준으로 환산. 농도 단위는 입력과 동일, O₂ 는 vol% (dry)."""
    if c_meas < 0:
        raise ValueError("측정 농도는 음수일 수 없음")
    return c_meas * correction_factor(o2_meas_pct, o2_std_pct, o2_air_pct)


def ppm_to_mg_per_nm3(ppm: float, mw: float) -> float:
    """ppm → mg/Nm³ = ppm × M / 22.414."""
    if not mw or mw <= 0:
        raise ValueError("ppm ↔ mg/Nm³ 변환에는 분자량이 필요함")
    return ppm * mw / V_NORMAL


def mg_per_nm3_to_ppm(mg: float, mw: float) -> float:
    """mg/Nm³ → ppm = mg × 22.414 / M."""
    if not mw or mw <= 0:
        raise ValueError("ppm ↔ mg/Nm³ 변환에는 분자량이 필요함")
    return mg * V_NORMAL / mw


def wet_to_dry(value_wet: float, h2o_pct: float) -> float:
    """Wet 기준 농도 (또는 O₂ vol%) → Dry 기준 = value / (1 − x_H₂O)."""
    if not 0 <= h2o_pct < 100:
        raise ValueError("수분은 0 이상 100 vol% 미만")
    return value_wet / (1.0 - h2o_pct / 100.0)


def emission_rate_kg_h(c_mg_per_nm3: float, flow_nm3h_dry: float) -> float:
    """배출량 [kg/h] = 농도 [mg/Nm³, 실측 dry] × 유량 [Nm³/h, dry] × 1e-6."""
    if flow_nm3h_dry < 0:
        raise ValueError("유량은 음수일 수 없음")
    return c_mg_per_nm3 * flow_nm3h_dry * 1e-6


@dataclass(frozen=True)
class CorrectionResult:
    ppm_meas_dry: float | None  # 실측 (dry) ppm
    mg_meas_dry: float | None  # 실측 (dry) mg/Nm³
    o2_meas_dry: float  # vol%
    o2_std: float  # vol%
    factor: float  # 환산 계수
    ppm_std: float | None  # 표준산소 환산 ppm
    mg_std: float | None  # 표준산소 환산 mg/Nm³
    limit: float | None  # 배출허용기준 (limit_unit 단위)
    limit_unit: str
    ratio_to_limit_pct: float | None  # %
    verdict: str | None  # "적합" | "초과"
    emission_kg_h: float | None


def correct(
    value: float,
    unit: str,
    o2_meas_pct: float,
    o2_std_pct: float,
    mw: float | None = None,
    basis: str = "dry",
    h2o_pct: float = 0.0,
    limit: float | None = None,
    limit_unit: str = "ppm",
    flow_nm3h_dry: float | None = None,
    o2_air_pct: float = O2_AIR_PCT,
) -> CorrectionResult:
    """측정값 1건의 표준산소농도 환산 (Wet 이면 농도·O₂ 를 먼저 Dry 로 변환).

    unit: "ppm" | "mg/Nm3" (먼지 등 분자량 없는 물질은 mg/Nm3 만 가능)
    """
    if unit not in ("ppm", "mg/Nm3"):
        raise ValueError("농도 단위는 'ppm' 또는 'mg/Nm3'")
    if basis == "wet":
        value = wet_to_dry(value, h2o_pct)
        o2_meas_pct = wet_to_dry(o2_meas_pct, h2o_pct)
    factor = correction_factor(o2_meas_pct, o2_std_pct, o2_air_pct)
    if value < 0:
        raise ValueError("측정 농도는 음수일 수 없음")

    if unit == "ppm":
        ppm = value
        mg = ppm_to_mg_per_nm3(ppm, mw) if mw else None
    else:
        mg = value
        ppm = mg_per_nm3_to_ppm(mg, mw) if mw else None
    ppm_std = ppm * factor if ppm is not None else None
    mg_std = mg * factor if mg is not None else None

    ratio = verdict = None
    if limit is not None and limit > 0:
        c_std = ppm_std if limit_unit == "ppm" else mg_std
        if c_std is None:
            raise ValueError("배출허용기준 단위 변환에 분자량이 필요함")
        ratio = c_std / limit * 100.0
        verdict = "적합" if c_std <= limit else "초과"
    emission = emission_rate_kg_h(mg, flow_nm3h_dry) if (mg is not None and flow_nm3h_dry) else None
    return CorrectionResult(ppm, mg, o2_meas_pct, o2_std_pct, factor, ppm_std, mg_std, limit, limit_unit, ratio, verdict, emission)


def correct_batch(
    df: pd.DataFrame,
    o2_std_pct: float,
    unit: str,
    mw: float | None,
    basis: str = "dry",
    o2_air_pct: float = O2_AIR_PCT,
) -> pd.DataFrame:
    """여러 측정점 일괄 환산. df 열: "측정 농도", "측정 O2 [%]", (Wet 이면) "수분 [%]".

    반환: 입력 열 + "환산 계수", "환산 농도 [unit]", "오류".
    """
    out = df.copy()
    factors, values, errors = [], [], []
    for _, row in df.iterrows():
        try:
            r = correct(
                float(row["측정 농도"]), unit, float(row["측정 O2 [%]"]), o2_std_pct, mw, basis,
                float(row.get("수분 [%]", 0.0) or 0.0), o2_air_pct=o2_air_pct,
            )
            factors.append(r.factor)
            values.append(r.ppm_std if unit == "ppm" else r.mg_std)
            errors.append("")
        except (ValueError, TypeError) as e:
            factors.append(float("nan"))
            values.append(float("nan"))
            errors.append(str(e))
    out["환산 계수"] = factors
    out[f"환산 농도 [{unit}]"] = values
    out["오류"] = errors
    return out
