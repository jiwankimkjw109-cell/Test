"""연소 설비 진단 계산기 — Streamlit 진입점.

st.navigation 으로 페이지 메뉴를 구성한다. 이 파일은 모든 페이지 실행 전에 매번 실행되므로
공통 설정(페이지 설정, 스타일, 세션 상태, 사이드바)을 여기서 한 번만 처리한다.
"""

import streamlit as st

from state import init_state, sidebar_status
from ui.theme import inject_css

st.set_page_config(page_icon="🔥", layout="wide")  # 탭 제목은 각 st.Page 의 title
inject_css()
init_state()

P = "pages/"
nav = st.navigation(
    {
        "시작": [
            st.Page(P + "0_home.py", title="홈", icon=":material/home:", default=True),
            st.Page(P + "1_fuel.py", title="연료 설정", icon=":material/local_fire_department:"),
        ],
        "계산·진단": [
            st.Page(P + "2_combustion.py", title="연소 계산", icon=":material/calculate:"),
            st.Page(P + "3_diagnosis.py", title="연소 진단", icon=":material/monitor_heart:"),
            st.Page(P + "4_savings.py", title="절감량 계산", icon=":material/savings:"),
            st.Page(P + "5_emission.py", title="표준산소 환산", icon=":material/air:"),
        ],
        "참고 도구": [
            st.Page(P + "6_properties.py", title="물성 DB", icon=":material/science:"),
            st.Page(P + "7_units.py", title="단위 변환", icon=":material/swap_horiz:"),
        ],
    }
)
sidebar_status()
nav.run()
