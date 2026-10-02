"""연료 조성, 혼합, 연료 물성 (발열량·밀도·비중·Wobbe)."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

from . import DATA_DIR, V_NORMAL
from .species import FUEL_SPECIES, get_species

M_AIR = 28.9647  # kg/kmol, 건공기 (비중 계산 기준)
COMPOSITION_TOL = 0.01  # vol%, 합계 100% 판정 허용오차


@dataclass
class Fuel:
    """기체 연료. composition 은 vol% (= mol%, 이상기체), 건가스 기준."""

    name: str
    composition: dict[str, float]
    description: str = ""

    def __post_init__(self) -> None:
        comp = {}
        for k, v in self.composition.items():
            v = float(v)
            if k not in FUEL_SPECIES:
                raise ValueError(f"연료 성분으로 지원하지 않는 성분: {k!r}")
            if v < 0 or math.isnan(v):
                raise ValueError(f"성분 {k} 의 농도가 올바르지 않음: {v}")
            if v > 0:
                comp[k] = v
        self.composition = comp

    @property
    def total(self) -> float:
        """조성 합계 [vol%]."""
        return sum(self.composition.values())

    def is_normalized(self, tol: float = COMPOSITION_TOL) -> bool:
        return abs(self.total - 100.0) <= tol

    def normalized(self) -> "Fuel":
        """합계 100 vol% 로 정규화한 새 Fuel."""
        t = self.total
        if t <= 0:
            raise ValueError("조성 합계가 0 이므로 정규화할 수 없음")
        return Fuel(self.name, {k: v * 100.0 / t for k, v in self.composition.items()}, self.description)

    def mole_fractions(self) -> dict[str, float]:
        """몰분율 (합 1). 합계가 100이 아니어도 정규화하여 반환."""
        t = self.total
        if t <= 0:
            raise ValueError("조성 합계가 0 임")
        return {k: v / t for k, v in self.composition.items()}

    def elements(self) -> dict[str, float]:
        """연료 1 kmol 당 원소 kmol {C, H, O, N, S, Ar}."""
        out: dict[str, float] = {}
        for k, x in self.mole_fractions().items():
            for e, n in get_species(k).elements.items():
                out[e] = out.get(e, 0.0) + x * n
        return out

    def properties(self) -> "FuelProperties":
        return fuel_properties(self)

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description, "composition": dict(self.composition)}

    @classmethod
    def from_dict(cls, d: dict) -> "Fuel":
        return cls(d["name"], dict(d["composition"]), d.get("description", ""))


@dataclass(frozen=True)
class FuelProperties:
    """연료 물성 (기준: 0 °C, 101.325 kPa, 이상기체)."""

    mw: float  # kg/kmol
    density: float  # kg/Nm³
    specific_gravity: float  # - (공기 = 1)
    lhv_vol: float  # MJ/Nm³
    hhv_vol: float  # MJ/Nm³
    lhv_mass: float  # MJ/kg
    hhv_mass: float  # MJ/kg
    wobbe_hhv: float  # MJ/Nm³
    wobbe_lhv: float  # MJ/Nm³
    elements: dict[str, float] = field(hash=False)  # kmol/kmol-fuel


def fuel_properties(fuel: Fuel) -> FuelProperties:
    """조성으로부터 분자량, 밀도, 비중, HHV/LHV, Wobbe Index 계산."""
    x = fuel.mole_fractions()
    mw = sum(xi * get_species(k).mw for k, xi in x.items())
    lhv = sum(xi * get_species(k).lhv_vol for k, xi in x.items())
    hhv = sum(xi * get_species(k).hhv_vol for k, xi in x.items())
    sg = mw / M_AIR
    rho = mw / V_NORMAL
    return FuelProperties(
        mw=mw,
        density=rho,
        specific_gravity=sg,
        lhv_vol=lhv,
        hhv_vol=hhv,
        lhv_mass=lhv / rho,
        hhv_mass=hhv / rho,
        wobbe_hhv=hhv / math.sqrt(sg),
        wobbe_lhv=lhv / math.sqrt(sg),
        elements=fuel.elements(),
    )


def mix_fuels(fuels: list[Fuel], amounts: list[float], basis: str = "flow", name: str = "혼합가스") -> Fuel:
    """여러 연료를 혼합한 Fuel 반환.

    basis="flow": amounts 는 각 연료 유량 [Nm³/h] (또는 체적 비율).
    basis="heat": amounts 는 각 연료의 열량 비율 [%] (LHV 기준).
    """
    if len(fuels) != len(amounts) or not fuels:
        raise ValueError("연료와 비율의 개수가 맞지 않거나 비어 있음")
    if any(a < 0 for a in amounts):
        raise ValueError("혼합 비율은 음수일 수 없음")
    if basis == "flow":
        vols = list(amounts)
    elif basis == "heat":
        vols = []
        for f, a in zip(fuels, amounts):
            lhv = f.properties().lhv_vol
            if a > 0 and lhv <= 0:
                raise ValueError(f"{f.name} 의 발열량이 0 이어서 열량비로 혼합할 수 없음")
            vols.append(a / lhv if a > 0 else 0.0)
    else:
        raise ValueError(f"basis 는 'flow' 또는 'heat': {basis!r}")
    total = sum(vols)
    if total <= 0:
        raise ValueError("혼합 비율 합계가 0 임")
    comp: dict[str, float] = {}
    for f, v in zip(fuels, vols):
        for k, xi in f.mole_fractions().items():
            comp[k] = comp.get(k, 0.0) + xi * v / total * 100.0
    desc = " + ".join(f"{f.name} {a:g}" for f, a in zip(fuels, amounts) if a > 0)
    return Fuel(name, comp, f"{desc} ({'유량' if basis == 'flow' else '열량'} 기준)")


def with_moisture(fuel: Fuel, h2o_pct: float) -> Fuel:
    """건가스 기준 연료에 수분 h2o_pct [vol%, 습가스 기준] 을 더한 습가스 조성 (PRD 3.1 F-08)."""
    if not 0 <= h2o_pct < 100:
        raise ValueError("연료 수분은 0 이상 100 vol% 미만")
    if h2o_pct == 0:
        return fuel
    dry = {k: v for k, v in fuel.normalized().composition.items() if k != "H2O"}
    if not dry:
        raise ValueError("H₂O 외의 성분이 없어 습가스로 변환할 수 없음")
    scale = (100.0 - h2o_pct) / sum(dry.values())
    comp = {k: v * scale for k, v in dry.items()}
    comp["H2O"] = h2o_pct
    return Fuel(fuel.name, comp, fuel.description)


def h2o_pct_from_dew_point(dew_point_c: float, p_kpa: float = 101.325) -> float:
    """연료 노점 [°C] → 포화 수분 [vol%] (Buck 식)."""
    from .combustion import saturation_pressure

    pv = saturation_pressure(dew_point_c)
    if pv >= p_kpa:
        raise ValueError("노점이 너무 높음")
    return pv / p_kpa * 100.0


def load_default_fuels() -> dict[str, Fuel]:
    """data/fuels_default.json 의 기본 연료."""
    raw = json.loads((DATA_DIR / "fuels_default.json").read_text(encoding="utf-8"))
    return {
        name: Fuel(name, d["composition"], d.get("description", ""))
        for name, d in raw["fuels"].items()
    }


def fuels_to_json(fuels: list[Fuel]) -> str:
    return json.dumps({"fuels": [f.to_dict() for f in fuels]}, ensure_ascii=False, indent=2)


def fuels_from_json(text: str) -> list[Fuel]:
    """fuels_to_json 형식 (또는 단일 연료 dict) 을 읽어 Fuel 목록 반환."""
    data = json.loads(text)
    items = data["fuels"] if isinstance(data, dict) and "fuels" in data else [data]
    return [Fuel.from_dict(d) for d in items]
