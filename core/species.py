"""성분 물성: 분자량, 생성엔탈피, 발열량, NASA 7-계수 다항식 기반 cp(T)·h(T).

데이터 출처는 data/species.json 의 "source" 필드 참조.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

from . import DATA_DIR, R_UNIVERSAL, T_REF


@dataclass(frozen=True)
class Nasa7:
    """NASA 7-계수 다항식 (두 온도 구간)."""

    t_min: float
    t_mid: float
    t_max: float
    low: tuple[float, ...]
    high: tuple[float, ...]

    def _coeffs(self, t: np.ndarray) -> np.ndarray:
        low, high = np.asarray(self.low), np.asarray(self.high)
        return np.where((t < self.t_mid)[..., None], low, high)

    def cp_r(self, t):
        """cp/R [-], t [K]."""
        t = np.asarray(t, dtype=float)
        a = self._coeffs(t)
        return a[..., 0] + a[..., 1] * t + a[..., 2] * t**2 + a[..., 3] * t**3 + a[..., 4] * t**4

    def h_rt(self, t):
        """h/(R·T) [-], t [K]. 생성엔탈피를 포함한 절대 엔탈피."""
        t = np.asarray(t, dtype=float)
        a = self._coeffs(t)
        return (
            a[..., 0]
            + a[..., 1] * t / 2
            + a[..., 2] * t**2 / 3
            + a[..., 3] * t**3 / 4
            + a[..., 4] * t**4 / 5
            + a[..., 5] / t
        )

    def s_r(self, t):
        """s°/R [-] (표준압력 1 bar), t [K]."""
        t = np.asarray(t, dtype=float)
        a = self._coeffs(t)
        return (
            a[..., 0] * np.log(t)
            + a[..., 1] * t
            + a[..., 2] * t**2 / 2
            + a[..., 3] * t**3 / 3
            + a[..., 4] * t**4 / 4
            + a[..., 6]
        )


@dataclass(frozen=True)
class Species:
    """단일 화학종의 물성."""

    key: str
    formula: str
    name_ko: str
    mw: float  # kg/kmol
    elements: dict[str, float] = field(hash=False)
    hf298: float  # kJ/kmol
    lhv_vol: float  # MJ/Nm³
    hhv_vol: float  # MJ/Nm³
    lhv_mass: float  # MJ/kg
    hhv_mass: float  # MJ/kg
    nasa: Nasa7 = field(hash=False)
    note: str = ""

    def cp(self, t_k):
        """정압 몰비열 cp [kJ/(kmol·K)], t_k [K]."""
        return R_UNIVERSAL * self.nasa.cp_r(t_k)

    def h(self, t_k):
        """절대 몰엔탈피 h [kJ/kmol] (생성엔탈피 포함), t_k [K]."""
        t_k = np.asarray(t_k, dtype=float)
        return R_UNIVERSAL * t_k * self.nasa.h_rt(t_k)

    def s(self, t_k):
        """표준 몰엔트로피 s° [kJ/(kmol·K)], t_k [K]."""
        return R_UNIVERSAL * self.nasa.s_r(t_k)

    def g(self, t_k):
        """표준 몰 Gibbs 에너지 g° = h − T·s° [kJ/kmol], t_k [K]."""
        t_k = np.asarray(t_k, dtype=float)
        return self.h(t_k) - t_k * self.s(t_k)

    def h_sensible(self, t_k):
        """현열 엔탈피 h(T) − h(298.15 K) [kJ/kmol]."""
        return self.h(t_k) - self.h(T_REF)

    @property
    def is_combustible(self) -> bool:
        return self.lhv_vol > 0.0

    @property
    def o2_demand(self) -> float:
        """완전연소에 필요한 O₂ [kmol/kmol] = C + H/4 + S − O/2 (음수 가능: O₂ 자체 = −1)."""
        e = self.elements
        return e.get("C", 0) + e.get("H", 0) / 4 + e.get("S", 0) - e.get("O", 0) / 2


@lru_cache(maxsize=1)
def load_species() -> dict[str, Species]:
    """data/species.json 을 읽어 {key: Species} 반환 (캐시)."""
    raw = json.loads((DATA_DIR / "species.json").read_text(encoding="utf-8"))
    out: dict[str, Species] = {}
    for key, d in raw["species"].items():
        n = d["nasa7"]
        out[key] = Species(
            key=key,
            formula=d["formula"],
            name_ko=d["name_ko"],
            mw=d["mw"],
            elements=dict(d["elements"]),
            hf298=d["hf298_kJ_per_mol"] * 1000.0,
            lhv_vol=d["lhv_MJ_per_Nm3"],
            hhv_vol=d["hhv_MJ_per_Nm3"],
            lhv_mass=d["lhv_MJ_per_kg"],
            hhv_mass=d["hhv_MJ_per_kg"],
            nasa=Nasa7(n["t_min"], n["t_mid"], n["t_max"], tuple(n["low"]), tuple(n["high"])),
            note=d.get("note", ""),
        )
    return out


def get_species(key: str) -> Species:
    """성분 키로 Species 조회. 없으면 KeyError (지원 성분 목록 포함)."""
    db = load_species()
    if key not in db:
        raise KeyError(f"지원하지 않는 성분: {key!r}. 지원 성분: {', '.join(db)}")
    return db[key]


def species_keys() -> list[str]:
    return list(load_species())


# 연료 성분으로 입력 가능한 종 (PRD 3.1 F-07). SO2는 생성물 전용.
FUEL_SPECIES: tuple[str, ...] = (
    "CH4", "C2H6", "C3H8", "n-C4H10", "i-C4H10", "n-C5H12", "C2H4", "C3H6",
    "H2", "CO", "CO2", "N2", "O2", "H2O", "H2S", "Ar",
)


def mixture_h(composition: dict[str, float], t_k: float) -> float:
    """혼합물 엔탈피 Σ nᵢ·hᵢ(T) [kJ], composition = {key: kmol}."""
    return float(sum(n * get_species(k).h(t_k) for k, n in composition.items() if n))


def mixture_cp(composition: dict[str, float], t_k: float) -> float:
    """혼합물 열용량 Σ nᵢ·cpᵢ(T) [kJ/K], composition = {key: kmol}."""
    return float(sum(n * get_species(k).cp(t_k) for k, n in composition.items() if n))
