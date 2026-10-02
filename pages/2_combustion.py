"""연소 계산: 공기량, 배가스량·조성, 단열화염온도, 민감도 그래프 (PRD 3.2)."""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.combustion import NO_COMBUSTIBLE_MSG, AirSpec, air_ratio_from_air_flow, combustion
from core.diagnosis import air_ratio_from_flue_o2
from core.flame import adiabatic_flame_temperature
from core.fuel import Fuel
from state import active_fuel
from ui.components import input_group, metric_row, page_header, stop_with_error
from ui.display import (
    KCAL_KJ, U_CP_VOL, U_HEAT_RATE, U_HV_VOL, fmt, formula_expander, gcal_h_from_kw, kcal_from_kj, kcal_from_mj, show_table,
)
from ui.inputs import number, oxidizer_inputs, radio
from ui.theme import HEAT, show_fig, style_fig

page_header("연소 계산", "공기비와 온도 조건으로 공기량, 배가스량·조성, 단열화염온도를 계산합니다.")
fuel = active_fuel()
props = fuel.properties()
if props.lhv_vol <= 0:
    stop_with_error(NO_COMBUSTIBLE_MSG)

left, right = st.columns([5, 7], gap="large")

# ---------------- 입력 ----------------
with left:
    st.caption(f"연료 **{fuel.name}**, LHV {kcal_from_mj(props.lhv_vol):,.0f} {U_HV_VOL}. 연료는 연료 설정에서 바꿉니다.")
    with input_group("연료량"):
        flow_mode = radio("입력 방식", "cc_flowmode", ["연료 유량", "열입력 (LHV)"], horizontal=True)
        if flow_mode == "연료 유량":
            fuel_flow = number("연료 유량 [Nm³/h]", "cc_flow", 1000.0, min_value=0.0, step=100.0,
                               help="버너에 공급되는 연료량 (0 °C, 101.325 kPa 환산)")
        else:
            q_in = number(f"열입력 [{U_HEAT_RATE}]", "cc_qin", 10.0, min_value=0.0, step=1.0,
                          help="저위발열량 기준 연소 열량")
            fuel_flow = q_in * 1e6 * KCAL_KJ / (props.lhv_vol * 1000.0)  # Gcal/h → kJ/h ÷ kJ/Nm³
            st.caption(f"연료 유량 {fuel_flow:,.1f} Nm³/h")

    with input_group("공기량"):
        ratio_mode = radio("지정 방식", "cc_ratiomode", ["공기비", "공기 유량", "배가스 O₂"], horizontal=True,
                           help="공기비를 직접 넣거나, 공기 유량 또는 배가스 O₂ 로부터 역산합니다.")
        ratio_slot = st.container()

    with input_group("온도"):
        t1, t2 = st.columns(2)
        t_fuel = number("연료 온도 [°C]", "cc_tfuel", 25.0, container=t1, min_value=-40.0, max_value=1000.0,
                        help="버너 입구 연료 온도")
        t_air = number("연소공기 온도 [°C]", "cc_tair", 25.0, container=t2, min_value=-40.0, max_value=1500.0,
                       help="예열 공기 온도. 리큐퍼레이터·리제너레이터 출구 온도를 입력")

    with st.expander("산화제·습도"):
        try:
            air = oxidizer_inputs("cc")
        except ValueError as e:
            stop_with_error(str(e))

    with ratio_slot:
        try:
            if ratio_mode == "공기비":
                air_ratio = number("공기비 m [-]", "cc_m", 1.15, min_value=0.5, max_value=5.0, step=0.01, format="%.3f",
                                   help="실제공기량 / 이론공기량. 1 미만은 공기 부족(연료 과잉)")
            elif ratio_mode == "공기 유량":
                air_flow = number("건조 공기 유량 [Nm³/h]", "cc_airflow", 11000.0, min_value=0.0, step=100.0,
                                  help="연소용 공기 유량 (건공기, 0 °C, 101.325 kPa 환산)")
                air_ratio = air_ratio_from_air_flow(fuel, fuel_flow, air_flow, air)
                st.caption(f"공기비 m = {air_ratio:.3f}")
            else:
                c1, c2 = st.columns([1, 2])
                o2_basis = radio("측정 기준", "cc_o2basis", ["dry", "wet"], container=c1,
                                 help="추출식(제습) 분석기는 dry, 직접 삽입식(지르코니아)은 wet")
                o2 = number(f"배가스 O₂ [vol%, {o2_basis}]", "cc_o2", 3.0, container=c2, min_value=0.0, max_value=20.0,
                            step=0.1, help="연소실 출구 배가스 산소 농도")
                air_ratio = air_ratio_from_flue_o2(fuel, o2, o2_basis, air)
                st.caption(f"공기비 m = {air_ratio:.3f}")
            flame = adiabatic_flame_temperature(fuel, air_ratio, air, t_fuel, t_air)
            r = combustion(fuel, air_ratio, air, t_eq_k=flame.t_ad_k)
        except ValueError as e:
            stop_with_error(str(e), "입력값을 확인하세요.")

# ---------------- 결과 ----------------
with right:
    metric_row(
        [
            ("단열화염온도", f"{flame.t_ad_c:,.0f} °C", f"{flame.t_ad_k:,.0f} K, 완전연소(해리 무시)"),
            ("이론공기량 A₀ (Wet)", f"{r.air_theoretical_wet:.3f} Nm³/Nm³"),
            ("실제배가스량 G (Wet)", f"{r.flue.wet:.3f} Nm³/Nm³"),
            ("배가스 O₂ (Dry)", f"{r.flue.composition_dry().get('O2', 0.0):.2f} %"),
        ]
    )
    if flame.t_ad_k > 2500:
        st.warning("단열화염온도가 2,500 K 를 넘습니다. 이 온도에서는 해리(CO, H₂, OH 등) 영향이 커서 "
                   "실제 화염온도는 이 값보다 낮습니다.", icon=":material/warning:")
    if air_ratio < 1.0:
        st.info(f"공기비가 1 미만이라 수성가스 평형(평형온도 {flame.t_ad_k:,.0f} K)으로 CO·H₂ 를 계산했습니다.",
                icon=":material/info:")

    tab_q, tab_c = st.tabs(["공기량·배가스량", "배가스 조성"])
    with tab_q:
        t_flue_cp = number("평균비열 계산 배가스 온도 [°C]", "cc_tcp", 1000.0, min_value=25.0, max_value=2500.0,
                           step=50.0, help="배가스 평균비열을 25 °C 부터 이 온도까지 평균합니다.")
        rows = [
            ("공기비 m", r.air_ratio, "-", 3),
            ("당량비 φ", r.equivalence_ratio, "-", 3),
            ("이론산소량 O₀", r.o2_theoretical, "Nm³/Nm³-fuel", 3),
            ("이론산소량 O₀", r.o2_theoretical_mass, "Nm³/kg-fuel", 3),
            ("이론공기량 A₀ (Dry)", r.air_theoretical_dry, "Nm³/Nm³-fuel", 3),
            ("이론공기량 A₀ (Wet)", r.air_theoretical_wet, "Nm³/Nm³-fuel", 3),
            ("실제공기량 A (Dry)", r.air_actual_dry, "Nm³/Nm³-fuel", 3),
            ("실제공기량 A (Wet)", r.air_actual_wet, "Nm³/Nm³-fuel", 3),
            ("실제공기량 A (Wet)", r.air_actual_wet * fuel_flow, "Nm³/h", 0),
            ("이론배가스량 G₀ (Wet)", r.flue_theoretical.wet, "Nm³/Nm³-fuel", 3),
            ("이론배가스량 G₀ (Dry)", r.flue_theoretical.dry, "Nm³/Nm³-fuel", 3),
            ("실제배가스량 G (Wet)", r.flue.wet, "Nm³/Nm³-fuel", 3),
            ("실제배가스량 G (Dry)", r.flue.dry, "Nm³/Nm³-fuel", 3),
            ("실제배가스량 G (Wet)", r.flue.wet * fuel_flow, "Nm³/h", 0),
            ("실제배가스량 G (Wet)", r.flue.mass * fuel_flow, "kg/h", 0),
            ("CO₂max (Dry)", r.co2_max_dry, "vol%", 2),
            ("배가스 노점", r.flue.dew_point(), "°C", 0),
            ("공기/연료 질량비", r.air_fuel_mass_ratio, "kg/kg", 3),
            ("배가스 밀도 (Wet)", r.flue.density, "kg/Nm³", 4),
            (f"배가스 평균비열 (25→{t_flue_cp:,.0f} °C)", kcal_from_kj(r.flue.mean_cp(t_flue_cp)), U_CP_VOL, 4),
            ("열입력 (LHV)", gcal_h_from_kw(fuel_flow * props.lhv_vol / 3.6), U_HEAT_RATE, 3),
            ("단열화염온도", flame.t_ad_c, "°C", 0),
            ("단열화염온도", flame.t_ad_k, "K", 0),
        ]
        table = show_table(rows)
        st.download_button(
            "결과 CSV 내려받기", table.to_csv(index=False).encode("utf-8-sig"), f"연소계산_{fuel.name}.csv", "text/csv",
            icon=":material/download:",
        )
    with tab_c:
        wet, dry = r.flue.composition_wet(), r.flue.composition_dry()
        order = [k for k in ("CO2", "CO", "H2O", "H2", "O2", "N2", "Ar", "SO2") if k in wet]
        st.dataframe(
            pd.DataFrame({"성분": order, "Wet [vol%]": [fmt(wet[k], 2) for k in order],
                          "Dry [vol%]": [fmt(dry.get(k), 2) for k in order]}),
            hide_index=True, width="stretch",
        )
        fig = go.Figure()
        fig.add_bar(x=order, y=[wet[k] for k in order], name="Wet", hovertemplate="%{x}: %{y:.2f} vol%<extra>Wet</extra>")
        fig.add_bar(x=order, y=[dry.get(k, 0) for k in order], name="Dry",
                    hovertemplate="%{x}: %{y:.2f} vol%<extra>Dry</extra>")
        fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08)
        show_fig(style_fig(fig, y="vol%", height=300, hovermode="closest"))


# ---------------- 민감도 그래프 ----------------
@st.cache_data(show_spinner=False)
def _curves(comp: tuple, air_dry: tuple, humidity: float, t_fuel_c: float, t_air_c: float):
    f = Fuel("c", dict(comp))
    a = AirSpec(dict(air_dry), humidity)
    rows = []
    for m in np.round(np.arange(0.8, 2.001, 0.025), 3):
        try:
            fl = adiabatic_flame_temperature(f, float(m), a, t_fuel_c, t_air_c)
            d = combustion(f, float(m), a, t_eq_k=fl.t_ad_k).flue.composition_dry()
            rows.append((m, fl.t_ad_c, d.get("O2", 0.0), d.get("CO2", 0.0), d.get("CO", 0.0)))
        except ValueError:
            continue
    curve_m = pd.DataFrame(rows, columns=["m", "T_ad", "O2", "CO2", "CO"])
    rows = []
    for tp in np.arange(25, 1201, 25):
        try:
            rows.append((tp, adiabatic_flame_temperature(f, 1.1, a, t_fuel_c, float(tp)).t_ad_c))
        except ValueError:
            continue
    return curve_m, pd.DataFrame(rows, columns=["T_air", "T_ad"])


st.subheader("공기비·예열온도에 따른 변화")
curve_m, curve_t = _curves(
    tuple(sorted(fuel.composition.items())), tuple(sorted(air.dry.items())), air.humidity, t_fuel, t_air
)
g1, g2, g3 = st.columns(3)
with g1:
    fig = go.Figure(go.Scatter(x=curve_m["m"], y=curve_m["T_ad"], mode="lines", line=dict(color=HEAT),
                               name="단열화염온도", hovertemplate="%{y:,.0f} °C"))
    fig.add_scatter(x=[air_ratio], y=[flame.t_ad_c], mode="markers", marker=dict(size=10, color=HEAT),
                    name="현재", hovertemplate="현재 %{y:,.0f} °C")
    show_fig(style_fig(fig, "단열화염온도", "공기비 m [-]", "단열화염온도 °C", legend=False))
with g2:
    fig = go.Figure()
    for col, label in (("O2", "O₂"), ("CO2", "CO₂"), ("CO", "CO")):
        fig.add_scatter(x=curve_m["m"], y=curve_m[col], mode="lines", name=label,
                        hovertemplate=f"{label} %{{y:.2f}} %<extra></extra>")
    fig.add_vline(x=air_ratio, line_dash="dot", line_width=1)
    show_fig(style_fig(fig, "배가스 조성 (Dry)", "공기비 m [-]", "vol%"))
with g3:
    fig = go.Figure(go.Scatter(x=curve_t["T_air"], y=curve_t["T_ad"], mode="lines", line=dict(color=HEAT),
                               name="단열화염온도", hovertemplate="%{y:,.0f} °C"))
    fig.add_vline(x=t_air, line_dash="dot", line_width=1)
    show_fig(style_fig(fig, "연소공기 예열 효과 (m = 1.10)", "연소공기 온도 [°C]", "단열화염온도 °C", legend=False))

formula_expander(
    "- 이론산소량 O₀ = Σ xᵢ (C + H/4 + S − O/2)ᵢ [Nm³/Nm³-fuel]\n"
    "- 이론공기량 A₀,dry = O₀ / x_O₂,air, A₀,wet = A₀,dry × (1 + 습분)\n"
    "- 배가스: CO₂ = ΣC, H₂O = ΣH/2 + 공기 습분, O₂ = (m − 1)·O₀, N₂·Ar = 연료 + 공기\n"
    "- 공기비 < 1: 수성가스 평형 CO + H₂O ⇌ CO₂ + H₂ (평형온도 = 단열화염온도)\n"
    "- 단열화염온도: Σ n·h(반응물 온도) = Σ n·h(T_ad), NASA 7-계수 다항식, 해리 무시\n"
    "- 공기 유량 → 공기비: m = 공기 유량 / (연료 유량 × A₀,dry)\n"
    "- 배가스 O₂ → 공기비: 연료 조성 기반 배가스 계산을 반복(brentq)하여 O₂ 일치점 탐색\n"
    "- 기준: 0 °C, 101.325 kPa, 22.414 Nm³/kmol, 1 kcal = 4.1868 kJ"
)
