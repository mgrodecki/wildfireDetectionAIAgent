import types

from conftest import StubBlock, StubResponse


def test_calculate_risk_low_and_extreme(load_module):
    agent = load_module()

    low_weather = {
        "temp_f": 60,
        "humidity_pct": 60,
        "wind_mph": 0,
        "fuel_moisture": 20,
        "slope_pct": 0,
        "veg_density": 0,
    }
    low = agent.calculate_risk(low_weather)
    assert low["index"] == 0
    assert low["label"] == "LOW"

    extreme_weather = {
        "temp_f": 110,
        "humidity_pct": 5,
        "wind_mph": 50,
        "fuel_moisture": 2,
        "slope_pct": 60,
        "veg_density": 80,
    }
    extreme = agent.calculate_risk(extreme_weather)
    assert extreme["label"] == "EXTREME"
    assert 85 <= extreme["index"] <= 100


def test_index_to_label_thresholds(load_module):
    agent = load_module()

    assert agent._index_to_label(0) == "LOW"
    assert agent._index_to_label(39) == "LOW"
    assert agent._index_to_label(40) == "MODERATE"
    assert agent._index_to_label(64) == "MODERATE"
    assert agent._index_to_label(65) == "HIGH"
    assert agent._index_to_label(84) == "HIGH"
    assert agent._index_to_label(85) == "EXTREME"


def test_tool_get_zone_risk_unknown_zone(load_module):
    agent = load_module()
    result = agent.tool_get_zone_risk("Nowhere")
    assert "error" in result
    assert "Available" in result["error"]


def test_tool_get_all_zones_risk_sorted(load_module):
    agent = load_module()
    summary = agent.tool_get_all_zones_risk()
    indices = [z["risk"]["index"] for z in summary["zones"]]
    assert indices == sorted(indices, reverse=True)


def test_tool_get_weather_forecast_days_clamped(load_module):
    agent = load_module()

    one_day = agent.tool_get_weather_forecast(0)
    assert len(one_day["forecast"]) == 1

    five_day = agent.tool_get_weather_forecast(10)
    assert len(five_day["forecast"]) == 5


def test_tool_get_response_recommendations_default(load_module):
    agent = load_module()
    result = agent.tool_get_response_recommendations("NE Ridge", "UNKNOWN")
    assert result["risk_level"] == "UNKNOWN"
    assert result["action_level"] == "Prepare"


def test_check_zone_alerts_flags(load_module):
    agent = load_module()

    weather = {
        "humidity_pct": 10,
        "wind_mph": 35,
        "fuel_moisture": 4,
    }
    risk = {"index": 90}
    alerts = agent._check_zone_alerts(weather, risk)

    assert any("Critically low humidity" in a for a in alerts)
    assert any("High wind speed" in a for a in alerts)
    assert any("Critical fuel moisture" in a for a in alerts)
    assert any("EXTREME risk" in a for a in alerts)


def test_fetch_weather_open_meteo_mock(load_module, dummy_zone, dummy_open_meteo_response, monkeypatch):
    agent = load_module()

    captured = {}

    def dummy_get(url, timeout):
        captured["url"] = url
        captured["timeout"] = timeout
        return dummy_open_meteo_response

    monkeypatch.setattr(agent, "REQUESTS_AVAILABLE", True)
    monkeypatch.setattr(agent, "requests", types.SimpleNamespace(get=dummy_get), raising=False)
    monkeypatch.setattr(
        agent,
        "_simulate_weather",
        lambda zone: {"fuel_moisture": 7, "slope_pct": 11, "veg_density": 42},
    )

    weather = agent.fetch_weather(dummy_zone)

    assert weather["temp_f"] == 88
    assert weather["humidity_pct"] == 22
    assert weather["wind_mph"] == 12
    assert weather["fuel_moisture"] == 7
    assert weather["slope_pct"] == 11
    assert weather["veg_density"] == 42
    assert weather["source"] == "open-meteo"
    assert "latitude=1.0" in captured["url"]
    assert "longitude=2.0" in captured["url"]
    assert "temperature_unit=fahrenheit" in captured["url"]
    assert "wind_speed_unit=mph" in captured["url"]



def test_fetch_firms_data_parses_csv(load_module, dummy_firms_response, monkeypatch):
    agent = load_module()

    captured = {}

    def dummy_get(url, timeout):
        captured["url"] = url
        captured["timeout"] = timeout
        return dummy_firms_response

    monkeypatch.setattr(agent, "REQUESTS_AVAILABLE", True)
    monkeypatch.setattr(agent, "FIRMS_API_KEY", "test-key")
    monkeypatch.setattr(agent, "requests", types.SimpleNamespace(get=dummy_get), raising=False)

    result = agent.fetch_firms_data(days=1)

    assert result["source"] == "firms"
    assert result["product"] == "VIIRS_SNPP_NRT"
    assert result["country"] == "USA"
    assert result["days"] == 1
    assert len(result["events"]) == 2
    assert result["events"][0]["latitude"] == "40.1"
    assert "/api/area/csv/" in captured["url"]
    assert "/VIIRS_SNPP_NRT/-125,24,-66,50/1" in captured["url"]


def test_tool_get_recent_fires_limits(load_module, dummy_firms_response, monkeypatch):
    agent = load_module()

    def dummy_get(url, timeout):
        return dummy_firms_response

    monkeypatch.setattr(agent, "REQUESTS_AVAILABLE", True)
    monkeypatch.setattr(agent, "FIRMS_API_KEY", "test-key")
    monkeypatch.setattr(agent, "requests", types.SimpleNamespace(get=dummy_get), raising=False)

    result = agent.tool_get_recent_fires(days=1, limit=1)

    assert result["count"] == 2
    assert len(result["events"]) == 1
    assert result["events"][0]["latitude"] == "40.1"



def test_fetch_firms_data_missing_api_key(load_module, monkeypatch):
    agent = load_module()

    monkeypatch.setattr(agent, "REQUESTS_AVAILABLE", True)
    monkeypatch.setattr(agent, "FIRMS_API_KEY", "")

    result = agent.fetch_firms_data(days=1)

    assert result["error"] == "FIRMS_API_KEY not set"

def test_dispatch_tool_routes(load_module, monkeypatch):
    agent = load_module()

    monkeypatch.setattr(agent, "tool_get_zone_risk", lambda zone: ("zone", zone))
    monkeypatch.setattr(agent, "tool_get_all_zones_risk", lambda: ("all", True))
    monkeypatch.setattr(agent, "tool_get_active_alerts", lambda: ("alerts", 1))
    monkeypatch.setattr(agent, "tool_get_weather_forecast", lambda days: ("forecast", days))
    monkeypatch.setattr(
        agent,
        "tool_get_response_recommendations",
        lambda zone, level: ("recs", zone, level),
    )

    assert agent.dispatch_tool("get_zone_risk", {"zone_name": "NE Ridge"}) == (
        "zone",
        "NE Ridge",
    )
    assert agent.dispatch_tool("get_all_zones_risk", {}) == ("all", True)
    assert agent.dispatch_tool("get_active_alerts", {}) == ("alerts", 1)
    assert agent.dispatch_tool("get_weather_forecast", {"days": 4}) == ("forecast", 4)
    assert agent.dispatch_tool(
        "get_response_recommendations",
        {"zone_name": "NE Ridge", "risk_level": "HIGH"},
    ) == ("recs", "NE Ridge", "HIGH")
    assert "error" in agent.dispatch_tool("unknown_tool", {})


def test_agentic_loop_with_stubbed_anthropic(load_module, monkeypatch, anthropic_stub):
    responses = [
        StubResponse(
            [
                StubBlock(
                    "tool_use",
                    name="get_zone_risk",
                    input={"zone_name": "NE Ridge"},
                    id="tool-1",
                )
            ],
            stop_reason="tool_use",
        ),
        StubResponse([StubBlock("text", text="All good.")], stop_reason="end_turn"),
    ]

    anthropic_stub(responses)
    agent = load_module()

    calls = []

    def fake_dispatch(name, inputs):
        calls.append((name, inputs))
        return {"ok": True}

    monkeypatch.setattr(agent, "dispatch_tool", fake_dispatch)

    fire_agent = agent.FireRiskAgent()
    result = fire_agent._agentic_loop("Status?")

    assert result == "All good."
    assert calls == [("get_zone_risk", {"zone_name": "NE Ridge"})]



