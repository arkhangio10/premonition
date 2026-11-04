from pathlib import Path

import pytest

from premonition.cell import load_cell
from premonition.planner import build_kit_plan

ROOT = Path(__file__).resolve().parent.parent
DEMO = {"A": "left", "B": "center", "C": "right"}


@pytest.fixture
def sim_cell():
    return load_cell(ROOT / "config" / "sim_cell.json")


@pytest.fixture
def real_cell():
    return load_cell(ROOT / "config" / "cell.json")


@pytest.fixture
def demo_plan(sim_cell):
    return build_kit_plan(DEMO, sim_cell)
