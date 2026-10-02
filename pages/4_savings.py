"""절감량 계산: 공기비 개선 전·후 비교 → 절감률, 열량, 금액, CO₂ (PRD 3.4)."""

import io

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.combustion import AIR_RATIO_MAX, NO_COMBUSTIBLE_MSG
from core.diagnosis import air_ratio_from_flue_o2, flue_o2_pct
from core.savings import PRICE_UNITS, co2_kg_per_nm3, compute_savings, default_co2_factor, sensitivity_table
from state import KEY_DIAG, active_fuel, hv_basis
from ui.components import input_group, metric_row, page_header, stop_with_error
from ui.display import U_HEAT_PER_FUEL, U_HEAT_RATE, U_HEAT_YEAR, formula_expander, gcal_h_from_kw, kcal_from_kj, show_table
from ui.inputs import checkbox, number, oxidizer_inputs, radio, select
from ui.theme import show_fig, style_fig

page_header("절감량 계산", "공기비를 낮췄을 때 같은 열을 얻는 데 필요한 연료가 얼마나 줄어드는지 열량과 금액으로 계산합니다.")
fuel = active_fuel()
basis_hv = hv_basis()
if fuel.properties().lhv_vol <= 0:
    stop_with_error(NO_COMBUSTIBLE_MSG)

left, right = st.columns([5, 7], gap="large")

with left:
    st.caption(f"연료 **{fuel.name}**, 열량 기준 **{basis_hv}** (사이드바에서 변경)")
    diag = st.session_state.get(KEY_DIAG)
    if diag and diag.get("fuel") == fuel.name and diag["air_ratio"] > AIR_RATIO_MAX:
        st.caption(f"연소 진단의 공기비 {diag['air_ratio']:.2f} 가 계산 범위(최대 {AIR_RATIO_MAX:g})를 넘어 가져올 수 없습니다.")
    elif diag and diag.get("fuel") == fuel.name:
        if st.button(f"연소 진단 결과 가져오기 (공기비 {diag['air_ratio']:.3f}, 배가스 {diag['flue_temp_c']:.0f} °C)",
                     icon=":material/input:"):
            vals = {"sv_m1mode": "공기비", "sv_m1": round(diag["air_ratio"], 3), "sv_tg1": float(diag["flue_temp_c"]),
                    "sv_tair": float(diag["t_air_c"]), "sv_flow": float(diag["fuel_flow_nm3h"])}
            for k, v in vals.items():
                st.session_state[k] = st.session_state["_p_" + k] = v
            st.rerun()

    with st.expander("산화제·습도"):
        try:
            air = oxidizer_inputs("sv")
        except ValueError as e:
            stop_with_error(str(e))

    def ratio_input(prefix: str, default_m: float, default_o2: float) -> float:
        mode = radio("지정 방식", f"{prefix}mode", ["공기비", "배가스 O₂ (dry)"], horizontal=True)
        if mode == "공기비":
            m = number("공기비 m [-]", prefix, default_m, min_value=1.0, max_value=AIR_RATIO_MAX, step=0.01, format="%.3f",
                       help="실제공기량 / 이론공기량 (1.0~5.0)")
            st.caption(f"배가스 O₂ (dry) {flue_o2_pct(fuel, m, air):.2f} %")
        else:
            o2 = number("배가스 O₂ [vol%, dry]", f"{prefix}o2", default_o2, min_value=0.0, max_value=15.0, step=0.1,
                        help="연료 조성을 반영해 공기비로 환산합니다.")
            m = air_ratio_from_flue_o2(fuel, o2, "dry", air)
            st.caption(f"공기비 m = {m:.3f}")
        return m

    try:
        cb, ca = st.columns(2)
        with cb, input_group("현재"):
            m1 = ratio_input("sv_m1", 1.30, 5.2)
            tg1 = number("배가스 온도 [°C]", "sv_tg1", 450.0, min_value=25.0, max_value=1600.0, step=10.0,
                         help="배출 지점 배가스 온도")
        with ca, input_group("개선 후"):
            m2 = ratio_input("sv_m2", 1.10, 2.0)
            same_t = checkbox("배가스 온도 현재와 같음", "sv_samet", True,
                              help="공기비만 바뀌고 배가스 온도는 그대로라고 가정")
            tg2 = tg1 if same_t else number("배가스 온도 [°C]", "sv_tg2", tg1, min_value=25.0, max_value=1600.0, step=10.0,
                                            help="공기비 개선 후 예상 배가스 온도")
    except ValueError as e:
        stop_with_error(str(e), "입력값을 확인하세요.")

    with input_group("운전 조건"):
        c1, c2 = st.columns(2)
        flow = number("현재 연료 사용량 [Nm³/h]", "sv_flow", 1000.0, container=c1, min_value=0.0, step=100.0,
                      help="개선 전 평균 연료 사용량 (0 °C, 101.325 kPa 환산)")
        t_air = number("연소공기 온도 [°C]", "sv_tair", 25.0, container=c2, min_value=-40.0, max_value=1500.0,
                       help="예열 공기 온도 (개선 전·후 동일 가정)")
        c3, c4, c5 = st.columns(3)
        hours = number("가동시간 [h/yr]", "sv_hours", 8000.0, container=c3, min_value=0.0, max_value=8784.0, step=100.0,
                       help="연간 운전 시간 (최대 8,784 h)")
        util = number("가동률 [%]", "sv_util", 100.0, container=c4, min_value=0.0, max_value=100.0, step=5.0,
                      help="운전 시간 중 위 연료 사용량으로 가동하는 비율")
        t_ref = number("기준 온도 [°C]", "sv_tref", 25.0, container=c5, min_value=-40.0, max_value=60.0,
                       help="현열 계산 기준 (외기) 온도")

    with input_group("단가·CO₂"):
        p1, p2 = st.columns(2)
        price_unit = select("연료 단가 단위", "sv_punit", list(PRICE_UNITS), container=p1,
                            help="계약 단가의 단위. 단위를 바꾸면 그 단위의 단가를 따로 입력합니다.")
        # 단위마다 별도 키: 단위만 바꿨을 때 이전 숫자가 다른 단위로 해석되지 않도록 (B-03)
        price = number(f"연료 단가 [{price_unit}]", f"sv_price_{price_unit}", 100000.0 if price_unit == "원/Gcal" else 0.0,
                       container=p2, min_value=0.0, step=1000.0 if price_unit in ("원/Gcal", "원/GJ") else 1.0,
                       format="%.0f" if price_unit in ("원/Gcal", "원/GJ") else "%.3f",
                       help="원/Gcal 기본값 100,000 은 예시값입니다. 실제 계약 단가를 입력하세요.")
        price_basis = radio("단가 열량 기준", "sv_pbasis", ["HHV", "LHV"], horizontal=True,
                            help="국내 도시가스·LNG 요금은 보통 총발열량(HHV) 기준", disabled=price_unit == "원/Nm3")
        fixed = default_co2_factor(fuel.name)
        # 연료마다 별도 키: 연료를 바꿨을 때 이전 연료의 배출계수가 남지 않도록 (B-05)
        co2_method = radio("CO₂ 배출계수", f"sv_co2m_{fuel.name}", ["고정 배출계수", "탄소수지 (조성 기반)"], horizontal=True,
                           default="고정 배출계수" if fixed else "탄소수지 (조성 기반)",
                           help="LNG 는 IPCC 고정 배출계수, 부생가스는 조성의 탄소로 계산하는 탄소수지가 기본")
        p3, p4 = st.columns(2)
        if co2_method == "고정 배출계수":
            factor = number("배출계수 [tCO₂/TJ, LHV]", f"sv_co2f_{fuel.name}", fixed or 56.1, container=p3, min_value=0.0, step=0.1,
                            help="LNG 기본값 56.1 (IPCC 2006)")
        else:
            factor = None
            p3.caption(f"탄소수지 {co2_kg_per_nm3(fuel):.4f} kgCO₂/Nm³")
        co2_price = number("배출권 가격 [원/tCO₂]", "sv_co2p", 0.0, container=p4, min_value=0.0, step=1000.0,
                           help="입력하면 CO₂ 저감량을 금액으로 환산합니다. 0 이면 생략")

try:
    s = compute_savings(
        fuel, flow, m1, m2, tg1, tg2, hours, util, price, price_unit, price_basis, factor, co2_price,
        t_air, 25.0, t_ref, air,
    )
except ValueError as e:
    with right:
        stop_with_error(str(e), "입력값을 확인하세요.")

# ---------------- 결과 ----------------
with right:
    st.markdown(
        f'<div class="hero-saving"><div class="label">연간 절감액</div>'
        f'<div class="value">{s.cost_saved_krw_yr / 1e6:,.1f} 백만원</div>'
        f'<div class="sub">연료 {s.fuel_saved_nm3yr:,.0f} Nm³/yr 절감, 연간 {s.hours_effective:,.0f} h 가동 기준</div></div>',
        unsafe_allow_html=True,
    )
    metric_row(
        [
            ("연료 절감률 [%]", f"{s.saving_rate_pct:.2f}"),
            (f"절감 열량 ({basis_hv}) [{U_HEAT_YEAR}]", f"{s.heat_saved_gcal_yr(basis_hv):,.0f}"),
            ("CO₂ 저감 [tCO₂/yr]", f"{s.co2_reduced_t_yr:,.1f}"),
        ],
        per_row=3,
    )
    if price <= 0:
        st.info("연료 단가를 입력하면 연간 절감액이 계산됩니다.", icon=":material/info:")
    if s.saving_rate < 0:
        st.warning("개선 후 조건의 유효열이 더 작아 연료 사용량이 오히려 늘어납니다. 개선 후 공기비를 확인하세요.",
                   icon=":material/warning:")

    st.markdown(f"**현재와 개선 후 비교** (연료 1 Nm³ 기준, 효율은 {basis_hv} 기준)")
    cmp_rows = []
    for name, hb, m, tg in (("현재", s.before, m1, tg1), ("개선 후", s.after, m2, tg2)):
        cmp_rows.append(
            {
                "구분": name,
                "공기비": f"{m:.3f}",
                "O₂ dry [%]": f"{flue_o2_pct(fuel, m, air):.2f}",
                "배가스 [°C]": f"{tg:,.0f}",
                "손실 [kcal/Nm³]": f"{kcal_from_kj(hb.flue_sensible):,.0f}",
                "유효열 [kcal/Nm³]": f"{kcal_from_kj(hb.available):,.0f}",
                "효율 [%]": f"{hb.efficiency(basis_hv) * 100:.2f}",
            }
        )
    cmp_df = pd.DataFrame(cmp_rows)
    st.dataframe(cmp_df, hide_index=True, width="stretch")

    tab_d, tab_s = st.tabs(["절감량 상세", "공기비별 민감도"])
    with tab_d:
        result = show_table(
            [
                ("연료 절감률", s.saving_rate_pct, "%", 2),
                ("절감 연료량", s.fuel_saved_nm3h, "Nm³/h", 1),
                ("절감 연료량", s.fuel_saved_nm3yr, "Nm³/yr", 0),
                ("절감 열량 (LHV)", gcal_h_from_kw(s.heat_saved_lhv_kw), U_HEAT_RATE, 3),
                ("절감 열량 (LHV)", s.heat_saved_gcal_yr("LHV"), U_HEAT_YEAR, 0),
                ("절감 열량 (HHV)", s.heat_saved_gcal_yr("HHV"), U_HEAT_YEAR, 0),
                ("절감 열량 (TOE, 총발열량 기준)", s.toe_yr, "TOE/yr", 1),
                ("절감 금액", s.cost_saved_krw_yr, "원/yr", 0),
                ("CO₂ 저감량", s.co2_reduced_t_yr, "tCO₂/yr", 1),
                ("CO₂ 배출권 환산", s.co2_value_krw_yr, "원/yr", 0),
                ("합계 (연료 + 배출권)", s.total_value_krw_yr, "원/yr", 0),
                ("연간 유효 가동시간", s.hours_effective, "h/yr", 0),
            ]
        )
    with tab_s:
        sens = sensitivity_table(fuel, m1, tg1, air=air, t_air_c=t_air, t_ref_c=t_ref, hv_basis=basis_hv,
                                 flue_temp_after_c=tg2)
        sens[f"유효열 [{U_HEAT_PER_FUEL}]"] = sens.pop("유효열 [kJ/Nm3]").map(kcal_from_kj)
        sens["절감 연료량 [Nm³/yr]"] = sens["절감률 [%]"] / 100 * flow * s.hours_effective
        fig = go.Figure(go.Scatter(x=sens["공기비"], y=sens["절감률 [%]"], mode="lines+markers", name="절감률",
                                   hovertemplate="m %{x:.2f}: %{y:.2f} %<extra></extra>"))
        fig.add_scatter(x=[m2], y=[s.saving_rate_pct], mode="markers", name="개선 목표",
                        marker=dict(size=13, symbol="star"), hovertemplate="개선 목표 %{y:.2f} %<extra></extra>")
        fig.add_scatter(x=[m1], y=[0], mode="markers", name="현재", marker=dict(size=11, symbol="x"),
                        hovertemplate="현재<extra></extra>")
        fig.add_hline(y=0, line_width=1, line_dash="dot")
        show_fig(style_fig(fig, None, "개선 후 공기비 m [-]", "연료 절감률 [%]", height=320, hovermode="closest"))
        st.dataframe(
            sens.assign(**{c: sens[c].map(lambda v: f"{v:,.2f}") for c in sens.columns if c != "공기비"}),
            hide_index=True, width="stretch",
        )
        st.caption(f"현재 {m1:.2f}·{tg1:,.0f} °C 대비, 개선 후 배가스 온도 {tg2:,.0f} °C 에서 공기비만 바꿔 계산했습니다.")

    inputs_df = pd.DataFrame(
        [
            ("연료", fuel.name, ""), ("현재 공기비", m1, "-"), ("개선 후 공기비", m2, "-"),
            ("현재 배가스 온도", tg1, "°C"), ("개선 후 배가스 온도", tg2, "°C"), ("연소공기 온도", t_air, "°C"),
            ("기준 온도", t_ref, "°C"), ("연료 사용량", flow, "Nm³/h"), ("가동시간", hours, "h/yr"),
            ("가동률", util, "%"), ("연료 단가", price, price_unit), ("단가 열량 기준", price_basis, ""),
            ("CO₂ 배출계수", factor if factor is not None else "탄소수지", "tCO₂/TJ"), ("배출권 가격", co2_price, "원/tCO₂"),
        ],
        columns=["항목", "값", "단위"],
    )
    csv = pd.concat([inputs_df.assign(구분="입력"), result.assign(구분="결과")])[["구분", "항목", "값", "단위"]]
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        inputs_df.to_excel(xw, sheet_name="입력", index=False)
        result.to_excel(xw, sheet_name="결과", index=False)
        cmp_df.to_excel(xw, sheet_name="비교", index=False)
        sens.to_excel(xw, sheet_name="민감도", index=False)
    e1, e2 = st.columns(2)
    e1.download_button("결과 CSV 내려받기", csv.to_csv(index=False).encode("utf-8-sig"), "절감량_계산.csv", "text/csv",
                       icon=":material/download:", width="stretch")
    e2.download_button("결과 Excel 내려받기", buf.getvalue(), "절감량_계산.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       icon=":material/download:", width="stretch")

formula_expander(
    "- 가정: 공정이 요구하는 유효열은 개선 전·후 동일\n"
    "- 유효열 AH = LHV + 공기·연료 현열 − 배가스 현열 손실 (연료 1 Nm³ 기준)\n"
    "- 연료 절감률 S = 1 − AH₁ / AH₂\n"
    "- 절감 연료량 = 현재 연료량 × S, 연간 = × 가동시간 × 가동률\n"
    "- 절감 금액: 원/Nm³ 이면 체적 × 단가, 열량 단가면 선택한 발열량 기준 열량 × 단가 (1 Gcal = 4.1868 GJ)\n"
    "- TOE: 총발열량(HHV) 기준, 1 TOE = 10⁷ kcal\n"
    "- CO₂: 고정 배출계수 × LHV 열량, 또는 탄소수지 (연료 중 C × 44.009 / 22.414 kg/Nm³)"
)
