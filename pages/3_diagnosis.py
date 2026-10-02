"""연소 진단: 배가스 측정값 → 실제 공기비, 배가스 손실, 유효열·효율, 판정 (PRD 3.3)."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.combustion import NO_COMBUSTIBLE_MSG
from core.diagnosis import diagnose, load_criteria
from state import KEY_DIAG, active_fuel, hv_basis
from ui.components import input_group, metric_row, page_header, stop_with_error, verdict_badge
from ui.display import U_HEAT_PER_FUEL, U_HEAT_RATE, formula_expander, gcal_h_from_kw, kcal_from_kj, show_table
from ui.inputs import checkbox, number, oxidizer_inputs, radio, select
from ui.theme import show_fig, style_fig

page_header("연소 진단", "배가스 측정값으로 실제 공기비, 배가스 손실, 효율을 계산하고 설비 기준과 비교합니다.")
fuel = active_fuel()
basis_hv = hv_basis()
if fuel.properties().lhv_vol <= 0:
    stop_with_error(NO_COMBUSTIBLE_MSG)
crit = load_criteria()
presets = {p["name"]: p for p in crit["presets"]}

left, right = st.columns([5, 7], gap="large")

# ---------------- 입력 ----------------
with left:
    st.caption(f"연료 **{fuel.name}**, 효율 기준 **{basis_hv}** (사이드바에서 변경)")
    with input_group("배가스 측정값"):
        c1, c2 = st.columns([1, 2])
        o2_basis = radio("O₂ 기준", "dg_o2basis", ["dry", "wet"], container=c1,
                         help="추출식(제습) 분석기는 dry, 직접 삽입식(지르코니아)은 wet")
        o2 = number(f"O₂ [vol%, {o2_basis}]", "dg_o2", 5.2, container=c2, min_value=0.0, max_value=20.0, step=0.1,
                    help="연소실 출구 또는 열회수 설비 전 배가스 산소 농도")
        c3, c4 = st.columns(2)
        co = number("CO [ppm, dry]", "dg_co", 50.0, container=c3, min_value=0.0, max_value=100000.0, step=10.0, format="%.0f",
                    help="불완전연소 손실과 공기비 보정에 사용")
        t_flue = number("배가스 온도 [°C]", "dg_tflue", 450.0, container=c4, min_value=0.0, max_value=1600.0, step=10.0,
                        help="열회수 설비(리큐퍼레이터 등) 이후 배출 지점 온도")
        use_co2 = checkbox("CO₂ 측정값도 입력 (정합성 점검)", "dg_useco2", False)
        co2 = (number("CO₂ [vol%, dry]", "dg_co2", 9.0, min_value=0.0, max_value=30.0, step=0.1,
                      help="계산 CO₂ 와 0.5 %p 이상 차이 나면 경고합니다.") if use_co2 else None)

    with input_group("운전 조건"):
        c5, c6 = st.columns(2)
        fuel_flow = number("연료 유량 [Nm³/h]", "dg_flow", 1000.0, container=c5, min_value=0.0, step=100.0,
                           help="손실·유효열을 시간당 열량으로 환산할 때 사용")
        t_air = number("연소공기 온도 [°C]", "dg_tair", 25.0, container=c6, min_value=-40.0, max_value=1500.0,
                       help="예열 공기 온도")
        c7, c8 = st.columns(2)
        t_fuel = number("연료 온도 [°C]", "dg_tfuel", 25.0, container=c7, min_value=-40.0, max_value=1000.0,
                        help="버너 입구 연료 온도 (예열 시 입력)")
        t_ref = number("기준(외기) 온도 [°C]", "dg_tref", 25.0, container=c8, min_value=-40.0, max_value=60.0,
                       help="현열 손실·입열 계산의 기준 온도")

    with st.expander("산화제·습도"):
        try:
            air = oxidizer_inputs("dg")
        except ValueError as e:
            stop_with_error(str(e))

    with st.expander("판정 기준 (설비별 권장 공기비)"):
        preset_name = select("설비 유형", "dg_preset", list(presets))
        p = presets[preset_name]
        k1, k2 = st.columns(2)
        ratio_min = k1.number_input("권장 공기비 하한", min_value=1.0, max_value=3.0, value=p["air_ratio_min"], step=0.01,
                                    key=f"dg_rmin_{p['id']}")
        ratio_max = k2.number_input("권장 공기비 상한", min_value=1.0, max_value=3.0, value=p["air_ratio_max"], step=0.01,
                                    key=f"dg_rmax_{p['id']}")
        k3, k4 = st.columns(2)
        margin = k3.number_input("주의 여유폭", min_value=0.0, max_value=1.0, value=crit["caution_margin"], step=0.01,
                                 help="상한 + 여유폭을 넘으면 '개선 필요'")
        co_limit = k4.number_input("CO 기준 [ppm]", min_value=0.0, value=float(crit["co_limit_ppm"]), step=50.0)
        st.caption("권장 범위는 참고값입니다. 사업장 기준에 맞게 수정하세요.")
        if ratio_min > ratio_max:
            stop_with_error("권장 공기비 하한이 상한보다 큽니다. 하한을 상한 이하로 입력하세요.")

try:
    d = diagnose(
        fuel, fuel_flow, o2, t_flue, o2_basis, co, co2, t_air, t_fuel, t_ref, basis_hv, air,
        ratio_min, ratio_max, margin, co_limit,
    )
except ValueError as e:
    with right:
        stop_with_error(str(e), "측정값을 확인하세요.")

b = d.balance
flue = b.flue
lat = b.latent(basis_hv)
st.session_state[KEY_DIAG] = {
    "fuel": fuel.name,
    "air_ratio": d.air_ratio,
    "o2_dry": d.o2_dry,
    "flue_temp_c": t_flue,
    "t_air_c": t_air,
    "h2o_wet_pct": flue.composition_wet().get("H2O", 0.0),
    "flue_dry_nm3h": flue.dry * fuel_flow,
    "fuel_flow_nm3h": fuel_flow,
}

# ---------------- 결과 ----------------
with right:
    verdict_badge(d.verdict)
    for reason in d.reasons:
        st.markdown(f"{reason}.")
    metric_row(
        [
            ("공기비 (조성 반영)", f"{d.air_ratio:.3f}", "연료 조성으로 배가스를 계산해 측정 O₂ 와 맞춘 값 (CO 보정)"),
            (f"효율 ({basis_hv})", f"{d.efficiency_pct:.2f} %", "유효열 / 발열량"),
            ("배가스 현열 손실", f"{d.pct(b.flue_sensible):.2f} %"),
            ("유효열", f"{gcal_h_from_kw(d.kw(b.available)):.3f} {U_HEAT_RATE}"),
        ]
    )
    for w in d.warnings:
        st.warning(w, icon=":material/warning:")

    tab_h, tab_g = st.tabs(["열수지", "공기비·배가스"])
    with tab_h:
        heat_rows = [
            (f"발열량 ({basis_hv})", b.hv(basis_hv), 100.0),
            ("연소공기 현열", b.air_sensible, d.pct(b.air_sensible)),
            ("연료 현열", b.fuel_sensible, d.pct(b.fuel_sensible)),
            ("배가스 현열 손실", b.flue_sensible, d.pct(b.flue_sensible)),
        ]
        if lat:
            heat_rows.append(("배가스 잠열 손실 (HHV−LHV)", lat, d.pct(lat)))
        heat_rows += [("불완전연소(CO) 손실", b.incomplete, d.pct(b.incomplete)), ("유효열", b.available, d.efficiency_pct)]
        heat_df = pd.DataFrame(
            {
                "항목": [n for n, _, _ in heat_rows],
                f"[{U_HEAT_PER_FUEL}]": [f"{kcal_from_kj(kj):,.0f}" for _, kj, _ in heat_rows],
                f"[{U_HEAT_RATE}]": [f"{gcal_h_from_kw(d.kw(kj)):,.3f}" for _, kj, _ in heat_rows],
                f"[% of {basis_hv}]": [f"{pct:.2f}" for _, _, pct in heat_rows],
            }
        )
        st.dataframe(heat_df, hide_index=True, width="stretch")

        bars = [("유효열", d.efficiency_pct), ("배가스 현열 손실", d.pct(b.flue_sensible))]
        if lat:
            bars.append(("잠열 손실", d.pct(lat)))
        bars.append(("불완전연소 손실", d.pct(b.incomplete)))
        fig = go.Figure(go.Bar(
            y=[n for n, _ in bars][::-1], x=[v for _, v in bars][::-1], orientation="h",
            text=[f"{v:.2f} %" for _, v in bars][::-1], textposition="outside", cliponaxis=False,
            hovertemplate="%{y}: %{x:.2f} %<extra></extra>",
        ))
        fig.update_xaxes(range=[0, max(v for _, v in bars) * 1.18], showticklabels=False)
        show_fig(style_fig(fig, f"열 분배 (% of {basis_hv})", None, None, height=240, hovermode="closest", legend=False))
        if b.air_sensible + b.fuel_sensible > 0.5:
            st.caption("공기·연료 예열 현열이 입열에 포함되므로 유효열이 발열량의 100%를 넘을 수 있습니다.")

    with tab_g:
        rows = [
            ("공기비 (간이식 21/(21−O₂))", d.air_ratio_simple, "-", 3),
            ("공기비 (연료 조성 반영, CO 보정)", d.air_ratio, "-", 3),
        ]
        if d.air_ratio_n2 is not None:
            rows.append(("공기비 (N₂ 기준식)", d.air_ratio_n2, "-", 3))
        rows += [
            ("배가스 O₂ (Dry)", d.o2_dry, "vol%", 2),
            ("배가스 O₂ (Wet)", d.o2_wet, "vol%", 2),
            ("배가스 CO₂ 계산값 (Dry)", d.co2_calc_dry, "vol%", 2),
        ]
        if d.co2_meas_dry is not None:
            rows.append(("배가스 CO₂ 측정값 (Dry)", d.co2_meas_dry, "vol%", 2))
        rows += [
            ("배가스량 (Wet)", flue.wet * fuel_flow, "Nm³/h", 0),
            ("배가스량 (Dry)", flue.dry * fuel_flow, "Nm³/h", 0),
            ("배가스 노점", flue.dew_point(), "°C", 0),
        ]
        show_table(rows)

formula_expander(
    "- 간이 공기비 m = 21 / (21 − O₂,dry) (공기 O₂ 20.95% 사용 시 20.95)\n"
    "- 정밀 공기비: 연료 조성으로 배가스를 계산해 측정 O₂ 와 일치하는 m 을 수치해(brentq)로 탐색. "
    "CO 측정 시 CO₂ 일부가 CO 로 남고 O₂ 가 CO/2 만큼 증가한 것으로 보정\n"
    "- N₂ 기준식 m = N₂ / (N₂ − 3.76 (O₂ − 0.5 CO)) — 연료 중 N₂ 무시 (BFG 등에는 부적합)\n"
    "- 배가스 현열 손실 = Σ nᵢ [hᵢ(T_flue) − hᵢ(T_ref)]\n"
    "- 유효열 = LHV + 공기·연료 현열 − 배가스 현열 손실 − CO 손실 (CO × 3,016 kcal/Nm³)\n"
    "- 효율 = 유효열 / 발열량. HHV 기준이면 (HHV − LHV) 를 잠열 손실로 표시\n"
    "- 측정 CO₂ 와 계산 CO₂ 차이가 0.5 %p 를 넘으면 경고"
)
