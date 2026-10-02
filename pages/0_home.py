"""홈: 앱 소개, 진단 순서(페이지 바로가기), 기준 조건."""

import streamlit as st

from state import active_fuel
from ui.components import page_header
from ui.display import U_HV_VOL, kcal_from_mj

page_header(
    "연소 설비 진단 계산기",
    "가열로·소둔로·보일러의 연소 상태를 계산하고, 공기비를 낮췄을 때 아낄 수 있는 연료와 비용을 산출합니다. "
    "LNG와 부생가스(BFG·COG·LDG), 혼합가스를 다룹니다.",
)

fuel = active_fuel()
st.markdown(
    f"지금 선택된 연료는 **{fuel.name}** (LHV {kcal_from_mj(fuel.properties().lhv_vol):,.0f} {U_HV_VOL}) 입니다. "
    "연료가 다르면 먼저 연료 설정에서 바꾸세요."
)

st.subheader("진단 순서")
STEPS = [
    ("pages/1_fuel.py", "연료 설정", ":material/local_fire_department:",
     "연료를 고르고 분석 조성을 입력합니다. 여러 연료를 섞은 혼합가스도 만들 수 있습니다."),
    ("pages/2_combustion.py", "연소 계산", ":material/calculate:",
     "공기비와 예열 온도로 공기량, 배가스량·조성, 단열화염온도를 계산합니다."),
    ("pages/3_diagnosis.py", "연소 진단", ":material/monitor_heart:",
     "배가스 O₂·CO·온도 측정값으로 실제 공기비와 손실, 효율을 확인합니다."),
    ("pages/4_savings.py", "절감량 계산", ":material/savings:",
     "공기비를 개선했을 때 연간 절감 열량(Gcal), 금액, CO₂ 저감량을 산출합니다."),
]
cols = st.columns(len(STEPS))
for i, (col, (path, title, icon, desc)) in enumerate(zip(cols, STEPS), start=1):
    with col.container(border=True, height="stretch"):
        st.markdown(f'<span class="step-num">{i}단계</span>', unsafe_allow_html=True)
        st.page_link(path, label=title, icon=icon)
        st.caption(desc)

st.subheader("다른 도구")
t1, t2, t3 = st.columns(3)
t1.page_link("pages/5_emission.py", label="표준산소 환산", icon=":material/air:",
             help="NOx·CO·SO₂ 측정 농도를 배출허용기준 비교용 표준산소농도 기준으로 환산")
t2.page_link("pages/6_properties.py", label="물성 DB", icon=":material/science:",
             help="성분별 분자량, 발열량, 온도별 비열·엔탈피")
t3.page_link("pages/7_units.py", label="단위 변환", icon=":material/swap_horiz:",
             help="압력, 열량, 동력, 발열량, 유량 단위 변환")

st.subheader("계산 기준")
st.markdown(
    "| 항목 | 기준 |\n|---|---|\n"
    "| 표준상태 (Nm³) | 0 °C, 101.325 kPa, 몰부피 22.414 Nm³/kmol |\n"
    "| 엔탈피 기준 온도 | 25 °C (298.15 K) |\n"
    "| 물성 | NASA 7-계수 다항식 (McBride 외, NASA TM-4513) |\n"
    "| 단위 | SI. 열량 관련 단위는 kcal 계열 (kcal/Nm³, Gcal/h, Gcal/yr) |\n"
    "| 열량 환산 | 1 kcal = 4.1868 kJ |\n"
    "| 단열화염온도 | 완전연소 가정, 해리 무시 |"
)
