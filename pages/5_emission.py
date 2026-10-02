"""표준산소농도 환산: 측정 농도 → 표준산소 기준 농도, ppm↔mg/Nm³, Wet→Dry, 기준 대비 판정 (PRD 3.7)."""

import pandas as pd
import streamlit as st

from core.emission import correct, correct_batch, load_reference
from state import KEY_DIAG
from ui.components import input_group, metric_row, page_header, verdict_badge
from ui.display import fmt, formula_expander, show_table
from ui.inputs import number, radio, select

page_header("표준산소 환산", "측정한 배출 농도를 배출허용기준과 비교할 수 있도록 표준산소농도 기준으로 환산합니다.")
ref = load_reference()
pollutants = ref["pollutants"]
presets = {p["name"]: p for p in ref["presets"]}

left, right = st.columns([5, 7], gap="large")

# ---------------- 공통 조건 ----------------
with left:
    with input_group("환산 조건"):
        pol_key = select("대상 물질", "em_pol", list(pollutants) + ["사용자 정의"],
                         format_func=lambda k: pollutants[k]["name"] if k in pollutants else k,
                         help="NOx 는 NO₂ 기준 분자량으로 mg/Nm³ 를 계산합니다.")
        if pol_key == "사용자 정의":
            mw = number("분자량 [g/mol]", "em_mw", 30.0, min_value=0.0, step=1.0,
                        help="0 이면 ppm↔mg/Nm³ 변환 없이 입력 단위로만 환산합니다.") or None
        else:
            mw = pollutants[pol_key]["mw"]
            st.caption(f"분자량 {mw} g/mol" if mw else "분자량이 없는 물질이라 mg/Nm³ 로만 환산합니다.")
        preset_name = select("시설 유형 (표준산소농도)", "em_preset", list(presets),
                             help="대기환경보전법 시행규칙 배출허용기준의 시설별 표준산소농도")
        preset = presets[preset_name]
        if preset["o2_std_pct"] is None:
            o2_std = number("표준산소농도 [vol%]", "em_o2std", 4.0, min_value=0.0, max_value=20.0, step=0.5)
        else:
            o2_std = preset["o2_std_pct"]
            st.markdown(f"표준산소농도 **{o2_std:g} %**")
            if preset.get("verify"):
                st.caption("잠정값입니다. 대기환경보전법 시행규칙 [별표 8] 최신 원문으로 확인하세요.")
        c1, c2 = st.columns(2)
        basis = radio("측정 기준", "em_basis", ["dry", "wet"], container=c1, horizontal=True,
                      help="wet 이면 배가스 수분으로 농도·O₂ 를 dry 로 바꾼 뒤 환산합니다.")
        o2_air = number("공기 중 O₂ [vol%]", "em_o2air", 21.0, container=c2, min_value=20.9, max_value=21.0, step=0.05,
                        help="환산식의 21. 일부 기준은 20.9 를 씁니다.")

tab1, tab2 = right.tabs(["한 건 환산", "여러 건 일괄 환산"])


def _import_diag() -> None:
    """진단 결과를 측정값 위젯에 채움. 콜백은 위젯 생성 전에 실행되므로 위젯 키를 바꿀 수 있다 (B-01)."""
    d = st.session_state[KEY_DIAG]
    for k, v in (("em_basis", "dry"), ("em_o2", round(d["o2_dry"], 2)), ("em_flow", round(d["flue_dry_nm3h"], 1))):
        st.session_state[k] = st.session_state["_p_" + k] = v


# ---------------- 단건 ----------------
with left:
    units = ["ppm", "mg/Nm3"] if mw else ["mg/Nm3"]
    with input_group("측정값"):
        diag = st.session_state.get(KEY_DIAG)
        if diag:
            st.button(f"연소 진단 결과 가져오기 (O₂ dry {diag['o2_dry']:.2f} %, "
                      f"배가스 {diag['flue_dry_nm3h']:,.0f} Nm³/h dry)", icon=":material/input:", on_click=_import_diag)
        s1, s2 = st.columns(2)
        unit = select("농도 단위", "em_unit", units, container=s1, help="분석기 표시 단위")
        c_meas = number(f"측정 농도 [{unit}, {basis}]", "em_c", 100.0, container=s2, min_value=0.0, step=1.0,
                        help="배출구에서 측정한 농도 (표준산소 환산 전)")
        s3, s4 = st.columns(2)
        o2_meas = number(f"측정 O₂ [vol%, {basis}]", "em_o2", 8.0, container=s3, min_value=0.0, max_value=20.9, step=0.1,
                         help="20 % 이상이면 환산하지 않습니다.")
        h2o = (number("배가스 수분 [vol%]", "em_h2o", 15.0, container=s4, min_value=0.0, max_value=60.0, step=0.5)
               if basis == "wet" else 0.0)
        s5, s6 = st.columns(2)
        lim_unit = select("배출허용기준 단위", "em_limunit", units, container=s5, help="허가·법령 기준의 단위")
        limit = number(f"배출허용기준 [{lim_unit}]", "em_limit", 0.0, container=s6, min_value=0.0, step=1.0,
                       help="0 이면 판정하지 않습니다.")
        flow = number("배가스 유량 [Nm³/h, dry]", "em_flow", 0.0, min_value=0.0, step=100.0,
                      help="입력하면 배출량(kg/h)을 계산합니다. 0 이면 생략합니다.")

def single_result(r) -> None:
    main_val, main_unit = (r.ppm_std, "ppm") if unit == "ppm" else (r.mg_std, "mg/Nm³")
    if r.verdict:
        verdict_badge(r.verdict)
        st.markdown(f"환산 농도가 배출허용기준의 {r.ratio_to_limit_pct:.1f} % 입니다.")
    metric_row([(f"환산 농도 (O₂ {o2_std:g} % 기준)", f"{main_val:,.2f} {main_unit}"),
                ("환산 계수", f"{r.factor:.4f}"),
                ("측정 O₂ (dry)", f"{r.o2_meas_dry:.2f} %")], per_row=3)
    if r.o2_meas_dry < o2_std:
        st.info("측정 O₂ 가 표준산소농도보다 낮아 환산 농도가 실측보다 낮게 나옵니다.", icon=":material/info:")
    rows = [
        ("환산 계수 (21−O₂std)/(21−O₂meas)", r.factor, "-", 4),
        ("실측 농도 (dry)", r.ppm_meas_dry, "ppm", 2),
        ("실측 농도 (dry)", r.mg_meas_dry, "mg/Nm³", 2),
        ("환산 농도", r.ppm_std, "ppm", 2),
        ("환산 농도", r.mg_std, "mg/Nm³", 2),
    ]
    if r.emission_kg_h is not None:
        rows += [("배출량", r.emission_kg_h, "kg/h", 3), ("배출량 (8,760 h 가동)", r.emission_kg_h * 8.76, "t/yr", 2)]
    show_table([row for row in rows if row[1] is not None])


with tab1:
    try:
        result = correct(c_meas, unit, o2_meas, o2_std, mw, basis, h2o, limit or None, lim_unit, flow or None, o2_air)
    except ValueError as e:
        st.error(f"{e} 측정 O₂ 를 확인하세요.", icon=":material/error:")
    else:
        single_result(result)

# ---------------- 일괄 ----------------
with tab2:
    st.caption("측정값을 표에 입력하거나 엑셀에서 복사해 붙여넣으세요. 왼쪽의 환산 조건이 모든 행에 적용됩니다.")
    bunit = st.selectbox("농도 단위", units, key="em_bunit")
    cols = {"시각": ["09:00", "10:00", "11:00"], "측정 농도": [100.0, 95.0, 110.0], "측정 O2 [%]": [8.0, 7.5, 8.4]}
    if basis == "wet":
        cols["수분 [%]"] = [15.0, 15.0, 15.0]
    batch_in = st.data_editor(pd.DataFrame(cols), num_rows="dynamic", hide_index=True, key=f"em_batch_{basis}",
                              width="stretch")
    rows_in = batch_in.dropna(subset=["측정 농도", "측정 O2 [%]"])
    if len(rows_in):
        out = correct_batch(rows_in, o2_std, bunit, mw, basis, o2_air)
        show = out.copy()
        for c in ("환산 계수", f"환산 농도 [{bunit}]"):
            show[c] = show[c].map(lambda v: fmt(v, 4 if c == "환산 계수" else 2))
        st.dataframe(show, hide_index=True, width="stretch")
        st.download_button("일괄 환산 결과 CSV 내려받기", out.to_csv(index=False).encode("utf-8-sig"), "표준산소_환산.csv",
                           "text/csv", icon=":material/download:")
    else:
        st.info("표에 측정 농도와 측정 O₂ 를 입력하면 환산 결과가 나타납니다.", icon=":material/info:")

formula_expander(
    "- 환산 농도 C_std = C_meas × (21 − O₂,std) / (21 − O₂,meas)  (Dry 기준)\n"
    "- ppm → mg/Nm³ = ppm × M / 22.414 (0 °C, 101.325 kPa). NOx 는 NO₂ (M = 46.006) 기준\n"
    "- Wet → Dry: C_dry = C_wet / (1 − x_H₂O), O₂ 도 같은 방식으로 변환 후 환산\n"
    "- 배출량 [kg/h] = 실측 농도 [mg/Nm³, dry] × 배가스 유량 [Nm³/h, dry] × 10⁻⁶\n"
    "- 측정 O₂ 20 % 이상은 분모가 작아 오차가 과대하므로 환산하지 않음"
)
