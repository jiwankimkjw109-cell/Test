"""페이지 간 공유 상태 (st.session_state) 초기화·조회.

세션 키 규칙 (README 참조)
- "fuel_library": dict[str, Fuel]  기본 연료 + 사용자 정의/수정 연료
- "active_fuel_name": str          현재 선택된 연료 이름
- "hv_basis": str                  효율·열량 기준 "LHV" | "HHV" (사이드바)
- "diag_result": dict              연소 진단 결과 (표준산소 환산·절감량 페이지 연동)
- "_p_<위젯키>":                   페이지 이동 후에도 유지되는 위젯 값 (ui/inputs.py)
"""

from __future__ import annotations

import html

import streamlit as st

from core.fuel import Fuel, load_default_fuels
from ui.display import U_HV_VOL, kcal_from_mj
from ui.inputs import radio

KEY_LIBRARY = "fuel_library"
KEY_ACTIVE = "active_fuel_name"
KEY_HV = "hv_basis"
KEY_DIAG = "diag_result"


def init_state() -> None:
    if KEY_LIBRARY not in st.session_state:
        st.session_state[KEY_LIBRARY] = load_default_fuels()
    if KEY_ACTIVE not in st.session_state:
        st.session_state[KEY_ACTIVE] = "LNG"
    if KEY_HV not in st.session_state:
        st.session_state[KEY_HV] = "LHV"


def fuel_library() -> dict[str, Fuel]:
    init_state()
    return st.session_state[KEY_LIBRARY]


def active_fuel() -> Fuel:
    lib = fuel_library()
    name = st.session_state[KEY_ACTIVE]
    if name not in lib:
        name = next(iter(lib))
        st.session_state[KEY_ACTIVE] = name
    return lib[name]


def save_fuel(fuel: Fuel, make_active: bool = True) -> None:
    fuel_library()[fuel.name] = fuel
    if make_active:
        st.session_state[KEY_ACTIVE] = fuel.name


def hv_basis() -> str:
    init_state()
    return st.session_state[KEY_HV]


def sidebar_status() -> None:
    """사이드바: 현재 연료 요약, 발열량 기준 선택, 기준 상태."""
    f = active_fuel()
    p = f.properties()
    sb = st.sidebar
    sb.divider()
    sb.markdown(
        f'<div class="sb-fuel">현재 연료<br><b>{html.escape(f.name)}</b><br>'
        f"LHV {kcal_from_mj(p.lhv_vol):,.0f} {U_HV_VOL}<br>"
        f"HHV {kcal_from_mj(p.hhv_vol):,.0f} {U_HV_VOL}</div>",
        unsafe_allow_html=True,
    )
    st.session_state[KEY_HV] = radio(
        "효율·열량 기준", "sb_hv", ["LHV", "HHV"], container=sb, horizontal=True,
        help="LHV: 저위발열량(진발열량) 기준 / HHV: 고위발열량(총발열량) 기준",
    )
    sb.caption("기준 상태 0 °C, 101.325 kPa (Nm³)\n\n엔탈피 기준 25 °C\n\n단위 SI, 열량은 kcal 계열")
