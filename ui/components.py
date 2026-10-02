"""재사용 화면 컴포넌트: 페이지 머리말, 입력 묶음, 판정 배지, 수치 카드, 오류 표시."""

from __future__ import annotations

import html
from contextlib import contextmanager

import streamlit as st

from state import init_state

VERDICT_STYLE = {
    # 판정: (배지 색, 아이콘) — 색만으로 뜻을 전달하지 않도록 아이콘·문구를 함께 표시
    "양호": ("green", ":material/check_circle:"),
    "적합": ("green", ":material/check_circle:"),
    "주의": ("orange", ":material/warning:"),
    "개선 필요": ("red", ":material/error:"),
    "초과": ("red", ":material/error:"),
}


def page_header(title: str, description: str = "") -> None:
    """페이지 머리말 (제목, 한 줄 설명, 화염 색 눈금선). 세션 상태도 초기화한다."""
    init_state()
    desc = f"<p>{html.escape(description)}</p>" if description else ""
    st.markdown(
        f'<div class="page-head"><h1>{html.escape(title)}</h1>{desc}<div class="flame-rule"></div></div>',
        unsafe_allow_html=True,
    )


@contextmanager
def input_group(title: str):
    """테두리 있는 입력 묶음."""
    with st.container(border=True):
        st.markdown(f"**{title}**")
        yield


def verdict_badge(verdict: str) -> None:
    color, icon = VERDICT_STYLE.get(verdict, ("gray", ":material/info:"))
    st.badge(verdict, icon=icon, color=color)


def metric_row(items: list[tuple], container=st, per_row: int = 2) -> None:
    """items = [(라벨, 값 문자열, 도움말|None), ...] 를 수치 카드로 표시 (한 줄에 per_row 개).

    결과 열(화면 폭의 약 60%)에서는 2개씩 배치해야 값이 잘리지 않는다.
    """
    for start in range(0, len(items), per_row):
        chunk = items[start:start + per_row]
        cols = container.columns(per_row)
        for col, item in zip(cols, chunk):
            col.metric(item[0], item[1], help=item[2] if len(item) > 2 else None)


def stop_with_error(message: str, hint: str | None = None) -> None:
    """입력 오류: 무엇이 잘못됐고 어떻게 고치는지 표시하고 이후 계산을 멈춘다.

    hint 는 message 에 이미 안내 문장('~하세요')이 없을 때만 덧붙인다.
    """
    if hint and not message.rstrip(". ").endswith("요"):
        message = f"{message.rstrip('. ')}. {hint}"
    st.error(message, icon=":material/error:")
    st.stop()
