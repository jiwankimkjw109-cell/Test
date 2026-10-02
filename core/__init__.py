"""연소 설비 진단 계산 엔진 (Streamlit 비의존).

기준 조건 (PRD 4.1)
- Normal 상태: 0 °C, 101.325 kPa, 이상기체 몰부피 22.414 Nm³/kmol
- 엔탈피 기준 온도: 25 °C (298.15 K)
"""

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

R_UNIVERSAL = 8.314462618  # kJ/(kmol·K)
V_NORMAL = 22.414  # Nm³/kmol
T_NORMAL = 273.15  # K
P_NORMAL = 101.325  # kPa
T_REF = 298.15  # K, 엔탈피 기준 온도
