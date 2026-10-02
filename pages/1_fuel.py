"""연료 설정: 연료 선택·조성 편집·정규화, 혼합 연료, 수분, JSON 입출력, 연료 물성 (PRD 3.1)."""

import pandas as pd
import streamlit as st

from core.fuel import (
    Fuel, fuels_from_json, fuels_to_json, h2o_pct_from_dew_point, load_default_fuels, mix_fuels, with_moisture,
)
from core.species import FUEL_SPECIES, get_species
from state import KEY_ACTIVE, active_fuel, fuel_library, save_fuel
from ui.components import input_group, page_header
from ui.display import U_HV_MASS, U_HV_VOL, formula_expander, kcal_from_mj, show_table

page_header("연료 설정", "연료를 고르고 조성을 입력합니다. 여기서 선택한 연료가 모든 계산 페이지에 쓰입니다.")
lib = fuel_library()
defaults = load_default_fuels()


def properties_table(comp: dict) -> None:
    p = Fuel("tmp", comp).properties()
    show_table(
        [
            ("저위발열량 LHV", kcal_from_mj(p.lhv_vol), U_HV_VOL, 0),
            ("고위발열량 HHV", kcal_from_mj(p.hhv_vol), U_HV_VOL, 0),
            ("저위발열량 LHV", kcal_from_mj(p.lhv_mass), U_HV_MASS, 0),
            ("고위발열량 HHV", kcal_from_mj(p.hhv_mass), U_HV_MASS, 0),
            ("Wobbe Index (HHV)", kcal_from_mj(p.wobbe_hhv), U_HV_VOL, 0),
            ("Wobbe Index (LHV)", kcal_from_mj(p.wobbe_lhv), U_HV_VOL, 0),
            ("분자량", p.mw, "kg/kmol", 3),
            ("밀도 (0 °C, 101.325 kPa)", p.density, "kg/Nm³", 4),
            ("비중 (공기 = 1)", p.specific_gravity, "-", 4),
        ]
    )


tab_edit, tab_mix, tab_io = st.tabs(["조성 편집", "혼합 연료", "불러오기·내보내기"])

# ---------------- 조성 편집 ----------------
with tab_edit:
    left, right = st.columns([5, 6], gap="large")
    with left:
        names = list(lib)
        # 공유 상태 키는 위젯 키로 쓰지 않음 (페이지 이동 시 위젯 키가 삭제되므로)
        selected = st.selectbox("연료", names, index=names.index(active_fuel().name),
                                help="기본 연료(LNG·COG·BFG·LDG)와 저장한 사용자 연료")
        if selected != st.session_state[KEY_ACTIVE]:
            st.session_state[KEY_ACTIVE] = selected
            st.rerun()  # 사이드바(페이지보다 먼저 그려짐)에 새 연료를 바로 반영 (B-08)
        fuel = lib[selected]
        if fuel.description:
            st.caption(fuel.description)
        df = pd.DataFrame(
            {
                "성분": list(FUEL_SPECIES),
                "이름": [get_species(k).name_ko for k in FUEL_SPECIES],
                "vol%": [fuel.composition.get(k, 0.0) for k in FUEL_SPECIES],
            }
        )
        edited = st.data_editor(
            df,
            key=f"editor_{fuel.name}_{hash(tuple(sorted(fuel.composition.items())))}",
            hide_index=True,
            disabled=["성분", "이름"],
            width="stretch",
            height=35 * (len(df) + 1) + 3,
            column_config={
                "vol%": st.column_config.NumberColumn(
                    "vol% (건가스)", min_value=0.0, max_value=100.0, step=0.001, format="%.3f",
                    help="분석 조성을 입력하세요. 0 인 성분은 비워 두어도 됩니다.",
                )
            },
        )
    comp = {k: float(v) for k, v in zip(edited["성분"], edited["vol%"]) if pd.notna(v) and v > 0}
    total = sum(comp.values())

    with right:
        with input_group("조성 합계와 저장"):
            if total <= 0:
                st.error("조성이 비어 있습니다. 왼쪽 표에 성분 농도를 입력하세요.", icon=":material/error:")
            elif abs(total - 100.0) > 0.01:
                st.warning(f"조성 합계가 {total:.3f} vol% 입니다. '정규화 후 저장'을 누르면 100 vol% 로 맞춥니다.",
                           icon=":material/warning:")
            else:
                st.success(f"조성 합계 {total:.3f} vol%", icon=":material/check_circle:")
            new_name = st.text_input("저장 이름", value=fuel.name,
                                     help="같은 이름이면 덮어쓰고, 새 이름이면 사용자 연료로 추가합니다.")
            can_save = total > 0 and bool(new_name.strip())
            b1, b2, b3 = st.columns(3)
            if b1.button("저장", disabled=not can_save, width="stretch"):
                save_fuel(Fuel(new_name.strip(), comp, fuel.description))
                st.rerun()
            if b2.button("정규화 후 저장", type="primary", disabled=not can_save, width="stretch"):
                save_fuel(Fuel(new_name.strip(), comp, fuel.description).normalized())
                st.rerun()
            if fuel.name in defaults:
                if b3.button("기본값 복원", width="stretch"):
                    save_fuel(defaults[fuel.name])
                    st.rerun()
            elif b3.button("연료 삭제", width="stretch", disabled=len(lib) <= 1):
                del lib[fuel.name]
                st.session_state[KEY_ACTIVE] = next(iter(lib))
                st.rerun()

        if total > 0:
            st.markdown("**연료 물성** (편집 중인 조성)")
            properties_table(comp)
            if abs(total - 100.0) > 0.01:
                st.caption("합계가 100이 아니면 정규화한 조성으로 물성을 계산합니다.")

        with st.expander("연료 수분 (습가스로 변환)"):
            st.caption("위 조성은 건가스 기준입니다. 수분을 지정하면 H₂O 를 포함한 습가스 조성을 새 연료로 저장합니다.")
            mmode = st.radio("수분 입력 방식", ["수분 vol%", "노점 °C"], horizontal=True)
            if mmode == "수분 vol%":
                h2o = st.number_input("수분 [vol%, 습가스 기준]", min_value=0.0, max_value=50.0, value=0.0, step=0.5,
                                      help="습가스 전체 중 수증기 체적 비율")
            else:
                dp = st.number_input("연료 노점 [°C]", min_value=-40.0, max_value=80.0, value=30.0,
                                     help="포화 상태로 보고 노점에서 수분을 계산합니다.")
                h2o = h2o_pct_from_dew_point(dp)
                st.caption(f"포화 수분 {h2o:.3f} vol%")
            has_dry = any(k != "H2O" for k in comp)
            if not has_dry and total > 0:
                st.caption("H₂O 외의 성분이 없어 습가스로 변환할 수 없습니다.")
            if st.button("습가스로 저장", disabled=not has_dry or h2o <= 0):
                dry = Fuel(new_name.strip() or fuel.name, {k: v for k, v in comp.items() if k != "H2O"}, fuel.description)
                wet = with_moisture(dry, h2o)
                save_fuel(Fuel(f"{dry.name} (습)", wet.composition, f"{fuel.description} / 수분 {h2o:.2f} vol%"))
                st.rerun()

    formula_expander(
        "- 발열량: 성분 발열량의 몰분율 가중합 (이상기체, 25 °C 생성엔탈피 기준)\n"
        "- 밀도 = M / 22.414, 비중 = M / 28.965 (건공기)\n"
        "- Wobbe Index = 발열량 / √비중\n"
        "- 1 kcal = 4.1868 kJ"
    )

# ---------------- 혼합 연료 ----------------
with tab_mix:
    left, right = st.columns([5, 6], gap="large")
    with left:
        st.caption("여러 연료를 유량 또는 열량비로 섞습니다. 예: BFG + COG (M-gas)")
        basis = st.radio("혼합 기준", ["유량 [Nm³/h]", "열량비 [%]"], horizontal=True,
                         help="열량비는 LHV 기준 열량 기여 비율입니다.")
        mix_edit = st.data_editor(
            pd.DataFrame({"연료": list(lib), "비율": [0.0] * len(lib)}),
            key="mix_editor", hide_index=True, disabled=["연료"], width="stretch",
            column_config={"비율": st.column_config.NumberColumn(min_value=0.0, step=1.0, format="%.2f")},
        )
        mix_name = st.text_input("혼합 연료 이름", value="혼합가스")
    parts = [(lib[n], float(a)) for n, a in zip(mix_edit["연료"], mix_edit["비율"]) if pd.notna(a) and a > 0]
    with right:
        if not parts:
            st.info("왼쪽 표의 비율 열에 섞을 연료의 값을 입력하면 혼합 조성이 여기에 나타납니다.", icon=":material/info:")
        else:
            try:
                mixed = mix_fuels([f for f, _ in parts], [a for _, a in parts],
                                  "flow" if basis.startswith("유량") else "heat", mix_name.strip() or "혼합가스")
                st.markdown(f"**{mixed.name}** 조성 (vol%)")
                st.dataframe(
                    pd.DataFrame({"성분": list(mixed.composition),
                                  "vol%": [f"{v:.3f}" for v in mixed.composition.values()]}),
                    hide_index=True, width="stretch",
                )
                properties_table(mixed.composition)
                if st.button("혼합 연료 저장 후 선택", type="primary", disabled=not mix_name.strip()):
                    save_fuel(mixed)
                    st.rerun()
            except ValueError as e:
                st.error(str(e), icon=":material/error:")

# ---------------- 불러오기·내보내기 ----------------
with tab_io:
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("**내보내기**")
        st.caption("현재 연료 목록(기본 + 사용자 연료)을 JSON 파일로 저장합니다.")
        st.download_button(
            "연료 목록 내려받기 (JSON)", data=fuels_to_json(list(lib.values())).encode("utf-8"),
            file_name="fuels.json", mime="application/json", icon=":material/download:",
        )
    with right:
        st.markdown("**불러오기**")
        flash = st.session_state.pop("_flash_fuel_io", None)
        if flash:
            st.success(flash, icon=":material/check_circle:")
        up = st.file_uploader("연료 JSON 파일", type=["json"], help="이 앱에서 내려받은 형식의 파일")
        if up is not None:
            try:
                loaded = fuels_from_json(up.getvalue().decode("utf-8"))
                st.write("불러올 연료: " + ", ".join(f.name for f in loaded))
                if st.button("목록에 추가", type="primary"):
                    for f in loaded:
                        save_fuel(f, make_active=False)
                    st.session_state["_flash_fuel_io"] = f"{len(loaded)}개 연료를 추가했습니다. 조성 편집 탭의 연료 목록에서 고르세요."
                    st.rerun()  # 조성 편집 탭의 연료 목록(먼저 그려짐)에 바로 반영 (B-09)
            except (ValueError, KeyError, TypeError, UnicodeDecodeError) as e:
                st.error(f"연료 JSON 형식이 아닙니다 ({e}). 이 앱에서 내려받은 파일을 사용하세요.", icon=":material/error:")
