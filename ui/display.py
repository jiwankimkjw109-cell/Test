"""표시 단위 변환·서식.

단위 규칙: SI 를 기본으로 하되 열량 관련 단위는 kcal 계열로 표시한다.
  발열량 kcal/Nm³·kcal/kg, 열유량 Gcal/h, 연간 열량 Gcal/yr, 비열 kcal/(Nm³·°C),
  엔탈피 kcal/mol, 열량 단가 원/Gcal. core/ 는 SI(kJ, MJ, kW) 로 계산하고 여기서만 변환한다.
"""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st

KCAL_KJ = 4.1868  # 1 kcal = 4.1868 kJ (IT)

# 표시 단위 라벨
U_HV_VOL = "kcal/Nm³"
U_HV_MASS = "kcal/kg"
U_HEAT_PER_FUEL = "kcal/Nm³-fuel"
U_HEAT_RATE = "Gcal/h"
U_HEAT_YEAR = "Gcal/yr"
U_CP_VOL = "kcal/(Nm³·°C)"
U_CP_MOL = "kcal/(kmol·°C)"
U_H_MOL = "kcal/mol"


def kcal_from_kj(kj: float) -> float:
    """kJ → kcal (kJ/Nm³ → kcal/Nm³ 등 분모가 같은 경우)."""
    return kj / KCAL_KJ


def kcal_from_mj(mj: float) -> float:
    """MJ → kcal (MJ/Nm³ → kcal/Nm³, MJ/kg → kcal/kg)."""
    return mj * 1000.0 / KCAL_KJ


def gcal_h_from_kw(kw: float) -> float:
    """kW → Gcal/h."""
    return kw * 3600.0 / KCAL_KJ / 1e6


def gcal_from_gj(gj: float) -> float:
    """GJ → Gcal."""
    return gj / KCAL_KJ


def kcal_mol_from_kj_kmol(kj_per_kmol: float) -> float:
    """kJ/kmol → kcal/mol."""
    return kj_per_kmol / 1000.0 / KCAL_KJ


def fmt(value, decimals: int = 3) -> str:
    """천 단위 구분 + 고정 소수 자릿수. None/NaN 은 '-'."""
    if value is None:
        return "-"
    try:
        if math.isnan(value):
            return "-"
    except TypeError:
        return str(value)
    return f"{value:,.{decimals}f}"


def fmt_won(value: float) -> str:
    """원 → '1,234.5 백만원'."""
    return f"{value / 1e6:,.1f} 백만원"


def show_table(rows: list[tuple], key: str | None = None) -> pd.DataFrame:
    """rows = [(항목, 값, 단위, 소수자릿수), ...] 를 표로 표시하고 DataFrame 반환 (내보내기용)."""
    df = pd.DataFrame(
        [(r[0], fmt(r[1], r[3] if len(r) > 3 else 3), r[2]) for r in rows],
        columns=["항목", "값", "단위"],
    )
    st.dataframe(df, hide_index=True, width="stretch", key=key)
    return pd.DataFrame([(r[0], r[1], r[2]) for r in rows], columns=["항목", "값", "단위"])


def formula_expander(markdown: str, title: str = "계산 근거") -> None:
    with st.expander(title):
        st.markdown(markdown)
