"""물성 DB: 성분별 물성표, cp(T)·h(T) 표와 그래프 (PRD 3.5)."""

import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import DATA_DIR
from core.species import load_species
from ui.components import page_header
from ui.display import KCAL_KJ, U_CP_MOL, U_H_MOL, U_HV_MASS, U_HV_VOL, kcal_from_mj, kcal_mol_from_kj_kmol
from ui.theme import show_fig, style_fig

page_header("물성 DB", "계산에 쓰는 성분별 물성값입니다. 비열과 엔탈피는 온도에 따라 바뀌는 값으로 계산합니다.")
db = load_species()

st.subheader("성분 물성표")
st.dataframe(
    pd.DataFrame(
        [
            {
                "성분": k,
                "이름": s.name_ko,
                "분자량 [kg/kmol]": f"{s.mw:.3f}",
                "밀도 [kg/Nm³]": f"{s.mw / 22.414:.4f}",
                f"생성엔탈피 [{U_H_MOL}]": f"{kcal_mol_from_kj_kmol(s.hf298):,.2f}",
                f"LHV [{U_HV_VOL}]": f"{kcal_from_mj(s.lhv_vol):,.0f}",
                f"HHV [{U_HV_VOL}]": f"{kcal_from_mj(s.hhv_vol):,.0f}",
                f"LHV [{U_HV_MASS}]": f"{kcal_from_mj(s.lhv_mass):,.0f}",
                f"HHV [{U_HV_MASS}]": f"{kcal_from_mj(s.hhv_mass):,.0f}",
                "이론산소량 [Nm³/Nm³]": f"{max(s.o2_demand, 0.0):.3f}",
                f"cp 25 °C [{U_CP_MOL}]": f"{float(s.cp(298.15)) / KCAL_KJ:.3f}",
            }
            for k, s in db.items()
        ]
    ),
    hide_index=True,
    width="stretch",
)

st.subheader("온도별 비열·엔탈피")
c1, c2, c3 = st.columns([3, 1, 1])
sel = c1.multiselect("성분 (최대 8개)", list(db), default=["N2", "O2", "CO2", "H2O"], max_selections=8,
                     help="그래프 색은 선택 순서대로 고정 배정됩니다.")
t_lo = c2.number_input("최저 온도 [°C]", min_value=-70.0, max_value=5000.0, value=0.0, step=100.0)
t_hi = c3.number_input("최고 온도 [°C]", min_value=-70.0, max_value=5700.0, value=2000.0, step=100.0)
if t_hi <= t_lo:
    st.error("최고 온도를 최저 온도보다 크게 입력하세요.", icon=":material/error:")
elif not sel:
    st.info("성분을 하나 이상 선택하면 그래프와 표가 나타납니다.", icon=":material/info:")
else:
    t_c = np.linspace(t_lo, t_hi, 81)
    t_k = t_c + 273.15
    fig_cp, fig_h = go.Figure(), go.Figure()
    for k in sel:
        s = db[k]
        fig_cp.add_scatter(x=t_c, y=s.cp(t_k) / KCAL_KJ, mode="lines", name=k,
                           hovertemplate=f"{k} %{{y:.3f}}<extra></extra>")
        fig_h.add_scatter(x=t_c, y=s.h_sensible(t_k) / KCAL_KJ / 1000.0, mode="lines", name=k,
                          hovertemplate=f"{k} %{{y:,.2f}}<extra></extra>")
    g1, g2 = st.columns(2)
    with g1:
        show_fig(style_fig(fig_cp, "정압 몰비열 cp(T)", "온도 [°C]", U_CP_MOL))
    with g2:
        show_fig(style_fig(fig_h, "현열 엔탈피 h(T) − h(25 °C)", "온도 [°C]", U_H_MOL))

    step_t = np.arange(np.ceil(t_lo / 100) * 100, t_hi + 1e-9, 100.0)
    if len(step_t):
        table = {"온도 [°C]": [f"{t:,.0f}" for t in step_t]}
        raw_table = {"온도 [°C]": step_t}
        for k in sel:
            s = db[k]
            cp = s.cp(step_t + 273.15) / KCAL_KJ
            dh = s.h_sensible(step_t + 273.15) / KCAL_KJ / 1000.0
            table[f"{k} cp"] = [f"{v:.3f}" for v in cp]
            table[f"{k} Δh"] = [f"{v:,.2f}" for v in dh]
            raw_table[f"{k} cp [{U_CP_MOL}]"] = cp
            raw_table[f"{k} Δh [{U_H_MOL}]"] = dh
        st.caption(f"cp [{U_CP_MOL}], Δh = h(T) − h(25 °C) [{U_H_MOL}]")
        st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")
        st.download_button("표 CSV 내려받기", pd.DataFrame(raw_table).to_csv(index=False).encode("utf-8-sig"),
                           "물성표.csv", "text/csv", icon=":material/download:")
    out_of_range = [k for k in sel if t_k.min() < db[k].nasa.t_min or t_k.max() > db[k].nasa.t_max]
    if out_of_range:
        n = db[out_of_range[0]].nasa
        st.warning(f"다항식 유효범위({n.t_min:.0f}~{n.t_max:.0f} K)를 벗어나 외삽한 값이 있습니다: "
                   + ", ".join(out_of_range), icon=":material/warning:")

with st.expander("데이터 출처"):
    raw = json.loads((DATA_DIR / "species.json").read_text(encoding="utf-8"))
    st.write(raw["source"])
    st.caption("cp/R = a₁ + a₂T + a₃T² + a₄T³ + a₅T⁴, h/RT = a₁ + a₂T/2 + a₃T²/3 + a₄T³/4 + a₅T⁴/5 + a₆/T (T [K])")
