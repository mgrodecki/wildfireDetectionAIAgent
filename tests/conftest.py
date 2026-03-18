import importlib.util
from pathlib import Path
import sys
import types

import pytest


class StubBlock:
    def __init__(self, block_type, **kwargs):
        self.type = block_type
        for key, value in kwargs.items():
            setattr(self, key, value)


class StubResponse:
    def __init__(self, content, stop_reason):
        self.content = content
        self.stop_reason = stop_reason


class StubMessages:
    def __init__(self, responses):
        self._responses = iter(responses)

    def create(self, **kwargs):
        return next(self._responses)


class StubAnthropic:
    def __init__(self, responses):
        self.messages = StubMessages(responses)


def make_anthropic_stub(responses):
    return types.SimpleNamespace(Anthropic=lambda *a, **k: StubAnthropic(responses))


class DummyOpenWeatherResponse:
    def __init__(self, temp=88, humidity=22, wind_speed=12):
        self._payload = {"main": {"temp": temp, "humidity": humidity}, "wind": {"speed": wind_speed}}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class DummyFirmsResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


@pytest.fixture
def anthropic_stub(monkeypatch):
    def _install(responses):
        monkeypatch.setitem(sys.modules, "anthropic", make_anthropic_stub(responses))

    return _install


@pytest.fixture
def load_module():
    def _load():
        # Provide a lightweight stub so importing the agent doesn't require the real SDK.
        if "anthropic" not in sys.modules:
            sys.modules["anthropic"] = types.SimpleNamespace(Anthropic=lambda *a, **k: None)

        module_path = Path(__file__).resolve().parents[1] / "Fire_Risk_Agent.py"
        spec = importlib.util.spec_from_file_location("fire_risk_agent", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return _load


@pytest.fixture
def dummy_zone():
    return {"name": "Test Zone", "lat": 1.0, "lon": 2.0}


@pytest.fixture
def dummy_owm_response():
    return DummyOpenWeatherResponse()


@pytest.fixture
def dummy_firms_csv():
    return (
        "latitude,longitude,bright_ti4,acq_date,acq_time\n"
        "40.1,-105.2,330.1,2026-03-16,1930\n"
        "39.9,-105.0,315.5,2026-03-16,1945\n"
    )


@pytest.fixture
def dummy_firms_response(dummy_firms_csv):
    return DummyFirmsResponse(dummy_firms_csv)


