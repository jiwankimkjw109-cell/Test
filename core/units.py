"""공학 단위 변환 (PRD 3.6).

선형 단위는 SI 기준 단위에 대한 배율 테이블로 정의한다.
- 열량 kcal 은 국제표 칼로리(IT): 1 kcal = 4.1868 kJ
- 1 TOE = 10⁷ kcal = 41.868 GJ (에너지법 시행규칙 기준)
- 가스 유량(Nm³, Sm³, 실 m³, kg)은 상태 조건이 필요하므로 convert_gas_flow() 사용
"""

from __future__ import annotations

from . import P_NORMAL, T_NORMAL

KCAL = 4186.8  # J
BTU = 1055.05585262  # J (IT)
LB = 0.45359237  # kg
FT3 = 0.028316846592  # m³
T_SCF = 288.705556  # K (60 °F)

# quantity -> {unit: 배율 (SI 기준 단위로의 환산)}
UNITS: dict[str, dict[str, float]] = {
    "압력": {  # Pa
        "Pa": 1.0, "kPa": 1e3, "MPa": 1e6, "bar": 1e5, "atm": 101325.0,
        "mmH2O": 9.80665, "mmHg": 133.322387415, "kgf/cm2": 98066.5, "psi": 6894.757293168,
    },
    "에너지": {  # J
        "J": 1.0, "kJ": 1e3, "MJ": 1e6, "GJ": 1e9, "TJ": 1e12,
        "kcal": KCAL, "Mcal": KCAL * 1e3, "Gcal": KCAL * 1e6,
        "kWh": 3.6e6, "MWh": 3.6e9, "TOE": KCAL * 1e7, "Btu": BTU, "MMBtu": BTU * 1e6,
    },
    "동력·열유량": {  # W
        "W": 1.0, "kW": 1e3, "MW": 1e6,
        "kcal/h": KCAL / 3600, "Mcal/h": KCAL * 1e3 / 3600, "Gcal/h": KCAL * 1e6 / 3600,
        "Btu/h": BTU / 3600, "MMBtu/h": BTU * 1e6 / 3600,
    },
    "체적 발열량": {  # J/Nm³
        "MJ/Nm3": 1e6, "kJ/Nm3": 1e3, "kcal/Nm3": KCAL,
        # 1 scf (60 °F, 1 atm) = FT3 × 273.15/288.706 Nm³
        "Btu/scf": BTU / (FT3 * T_NORMAL / T_SCF),
    },
    "질량 발열량": {  # J/kg
        "MJ/kg": 1e6, "kJ/kg": 1e3, "kcal/kg": KCAL, "Btu/lb": BTU / LB,
    },
    "질량 비열": {  # J/(kg·K)
        "kJ/(kg·K)": 1e3, "J/(kg·K)": 1.0, "kcal/(kg·°C)": KCAL, "Btu/(lb·°F)": BTU / LB * 1.8,
    },
    "체적 비열": {  # J/(Nm³·K)
        "kJ/(Nm3·K)": 1e3, "kcal/(Nm3·°C)": KCAL,
    },
    "질량 유량": {  # kg/s
        "kg/s": 1.0, "kg/h": 1 / 3600, "t/h": 1000 / 3600, "lb/h": LB / 3600,
    },
    "농도": {  # 몰분율
        "vol%": 1e-2, "ppm": 1e-6, "ppb": 1e-9,
    },
}

TEMPERATURE_UNITS = ("°C", "K", "°F")
GAS_FLOW_UNITS = ("Nm3/h", "Nm3/s", "Sm3/h (15°C)", "Sm3/h (20°C)", "m3/h (실유량)", "kg/h")


def list_quantities() -> list[str]:
    return ["온도", *UNITS.keys(), "가스 유량"]


def list_units(quantity: str) -> list[str]:
    if quantity == "온도":
        return list(TEMPERATURE_UNITS)
    if quantity == "가스 유량":
        return list(GAS_FLOW_UNITS)
    return list(UNITS[quantity])


def convert_temperature(value: float, from_unit: str, to_unit: str) -> float:
    to_k = {"°C": lambda v: v + 273.15, "K": lambda v: v, "°F": lambda v: (v - 32) / 1.8 + 273.15}
    from_k = {"°C": lambda k: k - 273.15, "K": lambda k: k, "°F": lambda k: (k - 273.15) * 1.8 + 32}
    if from_unit not in to_k or to_unit not in from_k:
        raise ValueError(f"온도 단위 오류: {from_unit} → {to_unit}")
    k = to_k[from_unit](value)
    if k < 0:
        raise ValueError("절대온도가 0 K 미만임")
    return from_k[to_unit](k)


def _find_quantity(unit: str) -> str:
    for q, table in UNITS.items():
        if unit in table:
            return q
    raise ValueError(f"알 수 없는 단위: {unit!r}")


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """선형 단위 및 온도 변환. 가스 유량은 convert_gas_flow() 사용."""
    if from_unit in TEMPERATURE_UNITS or to_unit in TEMPERATURE_UNITS:
        return convert_temperature(value, from_unit, to_unit)
    q_from, q_to = _find_quantity(from_unit), _find_quantity(to_unit)
    if q_from != q_to:
        raise ValueError(f"서로 다른 물리량 간 변환 불가: {from_unit} ({q_from}) → {to_unit} ({q_to})")
    table = UNITS[q_from]
    return value * table[from_unit] / table[to_unit]


def convert_gas_flow(
    value: float,
    from_unit: str,
    to_unit: str,
    density_normal: float | None = None,
    t_actual_c: float | None = None,
    p_actual_kpa: float | None = None,
) -> float:
    """가스 유량 변환 (이상기체).

    density_normal: Normal 상태 밀도 [kg/Nm³] (kg/h 변환 시 필요)
    t_actual_c, p_actual_kpa: 실유량 m³/h 의 온도 [°C]·절대압력 [kPa]
    """

    def to_nm3h(v: float, u: str) -> float:
        if u == "Nm3/h":
            return v
        if u == "Nm3/s":
            return v * 3600
        if u == "Sm3/h (15°C)":
            return v * T_NORMAL / 288.15
        if u == "Sm3/h (20°C)":
            return v * T_NORMAL / 293.15
        if u == "m3/h (실유량)":
            if t_actual_c is None or p_actual_kpa is None:
                raise ValueError("실유량 변환에는 온도와 절대압력이 필요함")
            return v * (p_actual_kpa / P_NORMAL) * (T_NORMAL / (t_actual_c + 273.15))
        if u == "kg/h":
            if not density_normal:
                raise ValueError("kg/h 변환에는 Normal 밀도 [kg/Nm³] 가 필요함")
            return v / density_normal
        raise ValueError(f"알 수 없는 유량 단위: {u!r}")

    nm3h = to_nm3h(value, from_unit)
    # 역변환: 1 단위 값을 Nm³/h 로 바꾼 배율로 나눔 (모든 변환이 선형)
    return nm3h / to_nm3h(1.0, to_unit)
