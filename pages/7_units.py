"""단위 변환: 온도·압력·에너지·동력·발열량·비열·유량·농도 (PRD 3.6)."""

import pandas as pd
import streamlit as st

from core.units import convert, convert_gas_flow, list_quantities, list_units
from state import active_fuel
from ui.components import input_group, page_header

page_header("단위 변환", "현장에서 쓰는 단위를 SI 단위와 서로 바꿉니다.")

DEFAULT_FROM = {"에너지": "Gcal", "동력·열유량": "Gcal/h", "체적 발열량": "kcal/Nm3", "질량 발열량": "kcal/kg",
                "질량 비열": "kcal/(kg·°C)", "체적 비열": "kcal/(Nm3·°C)", "압력": "kPa", "온도": "°C"}

left, right = st.columns([5, 7], gap="large")
with left:
    with input_group("변환할 값"):
        quantity = st.selectbox("물리량", list_quantities())
        units = list_units(quantity)
        default_from = DEFAULT_FROM.get(quantity, units[0])
        value = st.number_input("값", value=1.0, format="%.6g", key=f"uv_{quantity}")
        a, b = st.columns(2)
        u_from = a.selectbox("변환 전 단위", units, index=units.index(default_from), key=f"uf_{quantity}")
        to_default = 0 if units[0] != u_from else min(1, len(units) - 1)
        u_to = b.selectbox("변환 후 단위", units, index=to_default, key=f"ut_{quantity}")

    kwargs = {}
    if quantity == "가스 유량":
        with input_group("가스 상태 (이상기체)"):
            fuel = active_fuel()
            kwargs["density_normal"] = st.number_input(
                "Normal 밀도 [kg/Nm³]", min_value=0.0001, value=round(fuel.properties().density, 4), format="%.4f",
                help=f"kg/h 변환에 사용. 기본값은 현재 연료({fuel.name})의 밀도",
            )
            g2, g3 = st.columns(2)
            kwargs["t_actual_c"] = g2.number_input("실유량 온도 [°C]", min_value=-100.0, max_value=2000.0, value=25.0)
            kwargs["p_actual_kpa"] = g3.number_input("실유량 절대압력 [kPa]", min_value=1.0, value=101.325, format="%.3f")


def conv(v, f, t):
    return convert_gas_flow(v, f, t, **kwargs) if quantity == "가스 유량" else convert(v, f, t)


with right:
    try:
        result = conv(value, u_from, u_to)
    except ValueError as e:
        st.error(f"{e}. 값을 확인하세요.", icon=":material/error:")
    else:
        st.metric(f"{value:,.6g} {u_from}", f"{result:,.6g} {u_to}")
        rows = []
        for u in units:
            try:
                rows.append((u, f"{conv(value, u_from, u):,.6g}"))
            except ValueError as e:
                rows.append((u, f"계산 불가: {e}"))
        st.markdown("**모든 단위로 환산**")
        st.dataframe(pd.DataFrame(rows, columns=["단위", "값"]), hide_index=True, width="stretch")

with st.expander("변환 기준"):
    st.markdown(
        "- 1 kcal = 4.1868 kJ (국제표 칼로리), 1 Gcal = 4.1868 GJ, 1 Gcal/h = 1.163 MW\n"
        "- 1 TOE = 10⁷ kcal = 41.868 GJ\n"
        "- 1 Btu = 1.05506 kJ, Btu/scf 는 60 °F·1 atm 기준 scf 를 Nm³ 로 환산\n"
        "- Nm³: 0 °C, 101.325 kPa / Sm³: 15 °C 또는 20 °C, 101.325 kPa\n"
        "- 1 mmH₂O = 9.80665 Pa, 1 kgf/cm² = 98.0665 kPa"
    )
