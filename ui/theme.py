"""전역 스타일과 그래프 공통 템플릿.

색 역할
- 주색(가스 화염 청색): 위젯·링크 — .streamlit/config.toml 의 primaryColor
- 고온 주황: 화염온도 등 온도 결과에만 사용 (HEAT)
- 그래프 계열색: config.toml chartCategoricalColors (dataviz 기준 팔레트, 고정 순서)
"""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

HEAT = "#e8590c"  # 고온 표시
FLAME_GRADIENT = "linear-gradient(90deg, #1858c4 0%, #2f8fd8 35%, #f2a516 75%, #e8590c 100%)"

_CSS = f"""
<style>
/* 한국어는 어절 단위로 줄바꿈 */
[data-testid="stMarkdownContainer"], [data-testid="stCaptionContainer"], .page-head p, [data-testid="stWidgetLabel"] {{
  word-break: keep-all; overflow-wrap: break-word;
}}
/* 태블릿 폭(사이드바 포함 1180px 이하)에서는 열을 세로로 쌓아 입력 → 결과 순서로 보이게 */
@media (max-width: 1180px) {{
  [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap; }}
  [data-testid="stColumn"] {{ flex: 1 1 100% !important; min-width: 100% !important; }}
}}
/* 숫자는 고정폭 숫자로 정렬 */
[data-testid="stMetricValue"], [data-testid="stNumberInputField"], [data-testid="stMarkdownContainer"] td {{
  font-variant-numeric: tabular-nums;
}}
/* 페이지 머리말: 제목 + 화염 색 눈금선 (청색 화염 → 고온 주황) */
.page-head h1 {{ margin-bottom: 0.15rem; }}
.page-head p {{ margin: 0 0 0.6rem 0; opacity: 0.78; max-width: 62ch; }}
.flame-rule {{ height: 3px; border-radius: 2px; background: {FLAME_GRADIENT}; margin: 0 0 1.4rem 0; }}
/* 결과 수치 라벨은 조금 작게 */
[data-testid="stMetricLabel"] p {{ font-size: 0.85rem; }}
/* 사이드바 요약 */
.sb-fuel {{ font-size: 0.9rem; line-height: 1.5; }}
.sb-fuel b {{ font-size: 1rem; }}
/* 절감량 대표 수치: 연간 절감액 */
.hero-saving .label {{ font-size: 0.9rem; opacity: 0.75; }}
.hero-saving .value {{ font-size: 2.6rem; font-weight: 700; line-height: 1.15; font-variant-numeric: tabular-nums; }}
.hero-saving .sub {{ font-size: 0.9rem; opacity: 0.75; }}
/* 홈 단계 카드 */
.step-num {{ font-weight: 600; font-size: 0.8rem; opacity: 0.6; }}
@media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; animation: none !important; }} }}
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def style_fig(
    fig: go.Figure,
    title: str | None = None,
    x: str | None = None,
    y: str | None = None,
    height: int = 340,
    hovermode: str = "x unified",
    legend: bool = True,
) -> go.Figure:
    """그래프 공통 레이아웃: 제목, 축 단위, 범례 위치, 얇은 선·8px 마커, 옅은 격자."""
    fig.update_layout(
        title=dict(text=title, font=dict(size=15), x=0, xanchor="left") if title else None,
        height=height,
        margin=dict(l=8, r=8, t=56 if title else 24, b=8),
        hovermode=hovermode,
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, title=None),
        font=dict(family="IBM Plex Sans KR, sans-serif"),
    )
    fig.update_xaxes(title_text=x, showgrid=False, ticks="outside", zeroline=False)
    fig.update_yaxes(title_text=y, zeroline=False)
    fig.update_traces(selector=dict(type="scatter", mode="lines"), line=dict(width=2))
    fig.update_traces(selector=dict(type="scatter", mode="lines+markers"), line=dict(width=2), marker=dict(size=8))
    return fig


def show_fig(fig: go.Figure) -> None:
    st.plotly_chart(
        fig,
        width="stretch",
        config={"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"]},
    )
