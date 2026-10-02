"""입력 위젯 헬퍼: 페이지 이동 후에도 값이 유지되는 위젯, 산화제·습도 입력."""

from __future__ import annotations

import streamlit as st

from core.combustion import AirSpec, humidity_from_rh

_P = "_p_"  # 영구 저장 접두사


def _save(key: str) -> None:
    st.session_state[_P + key] = st.session_state[key]


def persistent(widget, label: str, key: str, default, **kwargs):
    """페이지를 떠나도 값이 유지되는 위젯.

    Streamlit 은 렌더링되지 않은 페이지의 위젯 키를 삭제하므로, 별도 키(_p_<key>)에 값을 보관했다가 복원한다.
    """
    if key not in st.session_state:
        st.session_state[key] = st.session_state.get(_P + key, default)
    st.session_state[_P + key] = st.session_state[key]
    return widget(label, key=key, on_change=_save, args=(key,), **kwargs)


_INT_FORMAT_UNITS = ("°C", "Nm³/h", "h/yr", "원/")


def number(label: str, key: str, default: float, container=st, **kwargs) -> float:
    if "format" not in kwargs and any(u in label for u in _INT_FORMAT_UNITS):
        kwargs["format"] = "%.0f"  # 온도·유량·가동시간·금액은 정수로 표시
    lo, hi = kwargs.get("min_value"), kwargs.get("max_value")
    for k in (key, _P + key):  # 저장값이 현재 범위를 벗어나면 범위 안으로 (범위 초과 시 Streamlit 예외 방지)
        if k in st.session_state and st.session_state[k] is not None:
            v = st.session_state[k]
            if lo is not None and v < lo:
                st.session_state[k] = lo
            elif hi is not None and v > hi:
                st.session_state[k] = hi
    return persistent(container.number_input, label, key, default, **kwargs)


def _ensure_option(key: str, options, default) -> None:
    """저장된 값이 현재 선택지에 없으면 기본값으로 되돌림 (선택지가 바뀌는 위젯용)."""
    for k in (key, _P + key):
        if k in st.session_state and st.session_state[k] not in options:
            st.session_state[k] = default


def select(label: str, key: str, options, default=None, container=st, **kwargs):
    options = list(options)
    default = options[0] if default is None else default
    _ensure_option(key, options, default)
    return persistent(container.selectbox, label, key, default, options=options, **kwargs)


def radio(label: str, key: str, options, default=None, container=st, **kwargs):
    options = list(options)
    default = options[0] if default is None else default
    _ensure_option(key, options, default)
    return persistent(container.radio, label, key, default, options=options, **kwargs)


def checkbox(label: str, key: str, default: bool = False, container=st, **kwargs) -> bool:
    return persistent(container.checkbox, label, key, default, **kwargs)


OXIDIZERS = ("공기", "산소부화공기", "순산소")


def oxidizer_inputs(prefix: str) -> AirSpec:
    """산화제 종류·조성·습도 입력 → AirSpec. prefix 로 페이지별 키를 구분."""
    c1, c2 = st.columns(2)
    kind = radio("산화제", f"{prefix}_ox", list(OXIDIZERS), container=c1, horizontal=True,
                 help="공기 / 산소부화공기(O₂ 농도 지정) / 순산소")
    if kind == "공기":
        comp = radio(
            "공기 조성", f"{prefix}_aircomp", ["표준 (O₂ 20.95%)", "단순화 (O₂ 21%)"], container=c2, horizontal=True,
            help="표준: O₂ 20.95, N₂ 78.09, Ar 0.93, CO₂ 0.03 vol% / 단순화: O₂ 21, N₂ 79 vol%",
        )
        o2_pct = None
    elif kind == "산소부화공기":
        o2_pct = number("산화제 O₂ 농도 [vol%]", f"{prefix}_o2enr", 30.0, container=c2,
                        min_value=21.0, max_value=99.9, step=1.0)
        comp = None
    else:
        o2_pct, comp = 100.0, None

    c3, c4, c5 = st.columns(3)
    hmode = radio("습도 입력", f"{prefix}_hmode", ["상대습도", "절대습도"], container=c3, horizontal=True)
    if hmode == "상대습도":
        t_amb = number("대기 온도 [°C]", f"{prefix}_tamb", 25.0, container=c4, min_value=-40.0, max_value=60.0)
        rh = number("상대습도 [%]", f"{prefix}_rh", 60.0, container=c5, min_value=0.0, max_value=100.0, step=5.0)
        humidity = humidity_from_rh(rh, t_amb)
    else:
        humidity = number("절대습도 [kg/kg-건공기]", f"{prefix}_xabs", 0.012, container=c4,
                          min_value=0.0, max_value=0.2, step=0.001, format="%.4f")
    if o2_pct is not None:
        return AirSpec.enriched(o2_pct, humidity)
    return AirSpec.standard(humidity) if comp.startswith("표준") else AirSpec.simplified(humidity)
