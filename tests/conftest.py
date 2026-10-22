import copy
import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "altherma_two_units.json"


@pytest.fixture
def gateways() -> list[dict]:
    return copy.deepcopy(json.loads(FIXTURE.read_text()))
