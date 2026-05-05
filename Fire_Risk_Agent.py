"""
Fire Risk AI Agent
==================
Monitors fire risk conditions using real-time weather data and Claude AI or ChatGPT.
Supports natural language queries, zone monitoring, and automated alerts.

Requirements:
    pip install anthropic openai requests python-dotenv

Usage:
    export ANTHROPIC_API_KEY=your_key_here
    export OPENAI_API_KEY=your_key_here      # optional, enables ChatGPT agent
    export ANTHROPIC_MODEL=your_model_here   # optional, default set in code
    export OPENAI_MODEL=your_model_here      # optional, default set in code
    export FIRMS_API_KEY=your_key_here        # optional, enables NASA FIRMS fire data
    python Fire_Risk_Agent.py
"""

import os
import json
import time
import math
import csv
import io
import sys
import requests
from datetime import datetime, timedelta
from typing import Any

from dotenv import load_dotenv

load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# ── Optional: real weather via Open-Meteo ─────────────────────────────────
REQUESTS_AVAILABLE = True


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
FIRMS_API_KEY = os.environ.get("FIRMS_API_KEY", "")
FIRMS_AREAS = {
    "USA": "-125,24,-66,50",
}

# Monitored zones (name, lat, lon)
ZONES = [
    {"name": "NE Ridge",      "lat": 40.08, "lon": -105.23},
    {"name": "West Valley",   "lat": 39.95, "lon": -105.55},
    {"name": "South Basin",   "lat": 39.55, "lon": -105.10},
    {"name": "Central Plain", "lat": 39.75, "lon": -104.85},
    {"name": "Lakeside",      "lat": 39.88, "lon": -105.08},
    {"name": "North Marsh",   "lat": 40.25, "lon": -104.95},
]

# Thresholds for risk scoring
RISK_THRESHOLDS = {
    "temp_high":       95,   # °F — above this, full temp score
    "humidity_low":    15,   # % — below this, full humidity score
    "wind_high":       30,   # mph — above this, full wind score
    "fuel_moisture":   5,    # % — below this, critical
}


# ─────────────────────────────────────────────────────────────────────────────
# Weather helpers
# ─────────────────────────────────────────────────────────────────────────────

def _simulate_weather(zone: dict) -> dict:
    """Return plausible demo weather for a zone (no API key needed)."""
    seed = abs(hash(zone["name"])) % 100
    return {
        "temp_f":        85  + (seed % 20),
        "humidity_pct":  10  + (seed % 25),
        "wind_mph":      20  + (seed % 25),
        "fuel_moisture": 4   + (seed % 8),
        "slope_pct":     10  + (seed % 30),
        "veg_density":   20  + (seed % 50),
        "source":        "simulated",
    }


def fetch_weather(zone: dict) -> dict:
    """Fetch current weather from Open-Meteo, else fall back to simulation."""
    if not REQUESTS_AVAILABLE:
        return _simulate_weather(zone)
    try:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={zone['lat']}&longitude={zone['lon']}"
            "&current=temperature_2m,relative_humidity_2m,wind_speed_10m"
            "&temperature_unit=fahrenheit&wind_speed_unit=mph"
        )
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        d = r.json()
        current = d["current"]
        simulated = _simulate_weather(zone)
        return {
            "temp_f":        current["temperature_2m"],
            "humidity_pct":  current["relative_humidity_2m"],
            "wind_mph":      current["wind_speed_10m"],
            "fuel_moisture": simulated["fuel_moisture"],  # not in Open-Meteo
            "slope_pct":     simulated["slope_pct"],
            "veg_density":   simulated["veg_density"],
            "source":        "open-meteo",
        }
    except Exception:
        return _simulate_weather(zone)


def fetch_firms_data(days: int = 1, country: str = "USA", product: str = "VIIRS_SNPP_NRT") -> dict:
    """Fetch recent NASA FIRMS detections (CSV) for a country and timeframe."""
    days = max(1, min(10, int(days)))
    if not REQUESTS_AVAILABLE:
        return {"error": "requests library not available"}
    if not FIRMS_API_KEY:
        return {"error": "FIRMS_API_KEY not set"}

    area = FIRMS_AREAS.get(country.upper(), country)
    url = (
        "https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
        f"{FIRMS_API_KEY}/{product}/{area}/{days}"
    )
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        text = r.text.strip()
        if not text:
            events = []
        else:
            reader = csv.DictReader(io.StringIO(text))
            events = list(reader)
        return {
            "source": "firms",
            "product": product,
            "country": country,
            "area": area,
            "days": days,
            "events": events,
        }
    except Exception as exc:
        return {"error": f"FIRMS request failed: {type(exc).__name__}"}


# ─────────────────────────────────────────────────────────────────────────────
# Risk calculation
# ─────────────────────────────────────────────────────────────────────────────

def calculate_risk(weather: dict) -> dict:
    """
    Compute a 0-100 fire risk index from weather + terrain factors.
    Returns score, label, and factor breakdown.
    """
    t  = weather["temp_f"]
    h  = weather["humidity_pct"]
    w  = weather["wind_mph"]
    fm = weather["fuel_moisture"]
    sl = weather["slope_pct"]
    vd = weather["veg_density"]

    # Individual 0-1 sub-scores
    temp_score     = min(1.0, max(0.0, (t  - 60) / (RISK_THRESHOLDS["temp_high"] - 60)))
    humidity_score = min(1.0, max(0.0, (50 - h)  / (50 - RISK_THRESHOLDS["humidity_low"])))
    wind_score     = min(1.0, max(0.0, w  / RISK_THRESHOLDS["wind_high"]))
    fuel_score     = min(1.0, max(0.0, (20 - fm) / (20 - RISK_THRESHOLDS["fuel_moisture"])))
    slope_score    = min(1.0, sl / 60.0)
    veg_score      = min(1.0, vd / 80.0)

    # Weighted composite (weights sum to 1)
    weights = {
        "fuel_moisture": 0.30,
        "wind_speed":    0.25,
        "temperature":   0.20,
        "humidity":      0.15,
        "terrain_slope": 0.05,
        "vegetation":    0.05,
    }
    scores = {
        "fuel_moisture": fuel_score,
        "wind_speed":    wind_score,
        "temperature":   temp_score,
        "humidity":      humidity_score,
        "terrain_slope": slope_score,
        "vegetation":    veg_score,
    }
    composite = sum(scores[k] * weights[k] for k in weights) * 100
    index = round(min(100, max(0, composite)))

    if index >= 85:
        label = "EXTREME"
    elif index >= 65:
        label = "HIGH"
    elif index >= 40:
        label = "MODERATE"
    else:
        label = "LOW"

    return {
        "index":   index,
        "label":   label,
        "factors": {k: round(scores[k] * 100) for k in scores},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Agent tools (called by Claude via tool_use)
# ─────────────────────────────────────────────────────────────────────────────

TOOLS: list[dict] = [
    {
        "name":        "get_zone_risk",
        "description": (
            "Fetch current weather and calculate the fire risk index for a specific "
            "monitoring zone. Returns temperature, humidity, wind speed, fuel moisture, "
            "and a composite risk score (0-100)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "zone_name": {
                    "type":        "string",
                    "description": "Name of the zone to check (e.g. 'NE Ridge').",
                }
            },
            "required": ["zone_name"],
        },
    },
    {
        "name":        "get_all_zones_risk",
        "description": "Fetch fire risk for all monitored zones and return a ranked summary.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name":        "get_active_alerts",
        "description": "Return current fire weather alerts and red-flag warnings for Colorado.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name":        "get_recent_fires",
        "description": (
            "Fetch recent NASA FIRMS VIIRS fire detections for the USA and return a "
            "count plus a small sample of events."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type":        "integer",
                    "description": "Number of days to look back (1-10).",
                    "default":     1,
                },
                "limit": {
                    "type":        "integer",
                    "description": "Max number of events to return.",
                    "default":     50,
                },
            },
        },
    },
    {
        "name":        "get_weather_forecast",
        "description": (
            "Return a multi-day fire weather outlook including expected changes in "
            "temperature, humidity, and wind for the monitored region."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type":        "integer",
                    "description": "Number of forecast days (1-5).",
                    "default":     3,
                }
            },
        },
    },
    {
        "name":        "get_response_recommendations",
        "description": (
            "Generate specific fire response recommendations for a zone based on "
            "current risk level and contributing factors."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "zone_name": {
                    "type":        "string",
                    "description": "Zone to generate recommendations for.",
                },
                "risk_level": {
                    "type":        "string",
                    "enum":        ["LOW", "MODERATE", "HIGH", "EXTREME"],
                    "description": "Current risk level for the zone.",
                },
            },
            "required": ["zone_name", "risk_level"],
        },
    },
]


def _build_openai_tools(tools: list[dict]) -> list[dict]:
    openai_tools = []
    for tool in tools:
        openai_tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
                },
            }
        )
    return openai_tools


OPENAI_TOOLS = _build_openai_tools(TOOLS)


# ─────────────────────────────────────────────────────────────────────────────
# Tool implementations
# ─────────────────────────────────────────────────────────────────────────────

def tool_get_zone_risk(zone_name: str) -> dict:
    zone = next((z for z in ZONES if z["name"].lower() == zone_name.lower()), None)
    if not zone:
        available = [z["name"] for z in ZONES]
        return {"error": f"Zone '{zone_name}' not found. Available: {available}"}

    weather = fetch_weather(zone)
    risk    = calculate_risk(weather)
    return {
        "zone":         zone["name"],
        "timestamp":    datetime.now().isoformat(),
        "weather":      weather,
        "risk":         risk,
        "alerts":       _check_zone_alerts(weather, risk),
    }


def tool_get_all_zones_risk() -> dict:
    results = []
    for zone in ZONES:
        weather = fetch_weather(zone)
        risk    = calculate_risk(weather)
        results.append({
            "zone":    zone["name"],
            "risk":    risk,
            "weather": {
                "temp_f":        weather["temp_f"],
                "humidity_pct":  weather["humidity_pct"],
                "wind_mph":      weather["wind_mph"],
                "fuel_moisture": weather["fuel_moisture"],
            },
        })
    results.sort(key=lambda x: x["risk"]["index"], reverse=True)
    overall = round(sum(r["risk"]["index"] for r in results) / len(results))
    return {
        "timestamp":      datetime.now().isoformat(),
        "overall_index":  overall,
        "overall_label":  _index_to_label(overall),
        "zones":          results,
        "extreme_count":  sum(1 for r in results if r["risk"]["label"] == "EXTREME"),
        "high_count":     sum(1 for r in results if r["risk"]["label"] == "HIGH"),
    }


def tool_get_active_alerts() -> dict:
    # In production, integrate with NWS API: https://api.weather.gov/alerts/active?area=CO
    now = datetime.now()
    return {
        "timestamp": now.isoformat(),
        "alerts": [
            {
                "type":     "Red Flag Warning",
                "severity": "EXTREME",
                "message":  "Critical fire weather conditions. Low humidity (<15%), high winds (25-40 mph).",
                "counties": ["Larimer", "Boulder", "Jefferson", "Adams", "Arapahoe"],
                "expires":  (now + timedelta(hours=6)).strftime("%Y-%m-%d %H:%M"),
            },
            {
                "type":     "Fire Weather Watch",
                "severity": "HIGH",
                "message":  "Dry and gusty conditions expected. Monitor conditions closely.",
                "counties": ["El Paso", "Douglas", "Elbert", "Lincoln"],
                "expires":  (now + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M"),
            },
        ],
        "burn_bans": ["Larimer County — all outdoor burning prohibited"],
        "nws_url":   "https://api.weather.gov/alerts/active?area=CO",
    }


def tool_get_recent_fires(days: int = 1, limit: int = 50) -> dict:
    days = max(1, min(10, int(days)))
    limit = max(1, min(500, int(limit)))
    data = fetch_firms_data(days=days)
    if "error" in data:
        return data
    events = data.get("events", [])
    return {
        "timestamp": datetime.now().isoformat(),
        "source": data.get("source", "firms"),
        "product": data.get("product"),
        "country": data.get("country"),
        "days": data.get("days"),
        "count": len(events),
        "events": events[:limit],
    }

def tool_get_weather_forecast(days: int = 3) -> dict:
    days = max(1, min(5, days))
    forecast = []
    base_risk = 75
    for i in range(days):
        date  = (datetime.now() + timedelta(days=i)).strftime("%Y-%m-%d")
        delta = -8 * i  # gradual improvement after peak
        risk  = max(20, min(100, base_risk + delta))
        forecast.append({
            "date":         date,
            "day":          ["Today", "Tomorrow"][i] if i < 2 else f"Day {i+1}",
            "high_f":       96 - i * 5,
            "low_f":        58 - i * 3,
            "humidity_pct": 18 + i * 8,
            "wind_mph":     34 - i * 6,
            "precip_pct":   5  + i * 10,
            "risk_index":   risk,
            "risk_label":   _index_to_label(risk),
            "summary":      _forecast_summary(risk, i),
        })
    return {"forecast": forecast, "trend": "improving" if days > 1 else "steady"}


def tool_get_response_recommendations(zone_name: str, risk_level: str) -> dict:
    recs = {
        "LOW": {
            "action_level": "Monitor",
            "steps": [
                "Continue routine monitoring every 4 hours.",
                "Ensure water supplies and hand tools are accessible.",
                "Review evacuation routes with personnel.",
            ],
        },
        "MODERATE": {
            "action_level": "Prepare",
            "steps": [
                "Increase monitoring frequency to every 2 hours.",
                "Pre-position one engine crew at the zone perimeter.",
                "Issue public advisory: avoid open burning.",
                "Brief evacuation routes to nearby residents.",
            ],
        },
        "HIGH": {
            "action_level": "Ready",
            "steps": [
                "Deploy two engine crews and one airtanker on standby.",
                "Issue evacuation warnings for high-risk structures.",
                "Coordinate with county OEM for resource pre-positioning.",
                "Activate ICS Level 2 organization.",
                "All burning bans strictly enforced.",
            ],
        },
        "EXTREME": {
            "action_level": "Go — Immediate Action Required",
            "steps": [
                "Order mandatory evacuations for all structures within 1 mile.",
                "Request VLAT (Very Large Air Tanker) support immediately.",
                "Activate full ICS, establish Unified Command.",
                "Close public access — all roads into zone restricted.",
                "Coordinate with Red Cross for evacuation center activation.",
                "Notify NWS and request spot weather forecast.",
            ],
        },
    }
    plan = recs.get(risk_level, recs["MODERATE"])
    return {
        "zone":         zone_name,
        "risk_level":   risk_level,
        "action_level": plan["action_level"],
        "steps":        plan["steps"],
        "timestamp":    datetime.now().isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _index_to_label(index: int) -> str:
    if index >= 85: return "EXTREME"
    if index >= 65: return "HIGH"
    if index >= 40: return "MODERATE"
    return "LOW"


def _check_zone_alerts(weather: dict, risk: dict) -> list[str]:
    alerts = []
    if weather["humidity_pct"] < 15:
        alerts.append("Critically low humidity — extreme spotting potential.")
    if weather["wind_mph"] > 30:
        alerts.append("High wind speed — rapid fire spread risk.")
    if weather["fuel_moisture"] < 5:
        alerts.append("Critical fuel moisture — any ignition is dangerous.")
    if risk["index"] >= 85:
        alerts.append("EXTREME risk — consider pre-evacuation notifications.")
    return alerts


def _forecast_summary(risk: int, day_offset: int) -> str:
    if risk >= 85: return "Extreme fire danger. Avoid all ignition sources."
    if risk >= 65: return "High fire danger. Red Flag Warning likely."
    if risk >= 40: return "Moderate fire danger. Monitor conditions."
    return "Low fire danger. Normal precautions."


def dispatch_tool(name: str, inputs: dict) -> Any:
    """Route a tool call to the correct implementation."""
    if name == "get_zone_risk":
        return tool_get_zone_risk(inputs["zone_name"])
    if name == "get_all_zones_risk":
        return tool_get_all_zones_risk()
    if name == "get_active_alerts":
        return tool_get_active_alerts()
    if name == "get_recent_fires":
        return tool_get_recent_fires(inputs.get("days", 1), inputs.get("limit", 50))
    if name == "get_weather_forecast":
        return tool_get_weather_forecast(inputs.get("days", 3))
    if name == "get_response_recommendations":
        return tool_get_response_recommendations(
            inputs["zone_name"], inputs["risk_level"]
        )
    return {"error": f"Unknown tool: {name}"}


# ─────────────────────────────────────────────────────────────────────────────
# Agent core — agentic loop
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a professional fire risk monitoring AI agent for Colorado.
You have access to real-time weather data, zone risk indices, and fire weather alerts.

Your responsibilities:
- Monitor fire risk conditions across 6 zones (NE Ridge, West Valley, South Basin,
  Central Plain, Lakeside, North Marsh)
- Answer questions about current fire risk in clear, actionable language
- Proactively flag dangerous conditions and recommend appropriate responses
- Provide forecasts and trend analysis

Always use your tools to get current data before answering — never guess at conditions.
Include NASA FIRMS detections when asked about active fires.
Be direct, concise, and prioritize safety-critical information first.
When risk is HIGH or EXTREME, lead with the most urgent action items."""


class FireRiskAgent:
    def __init__(self):
        self.client = anthropic.Anthropic()
        self.conversation_history: list[dict] = []
        print("\nFire Risk AI Agent initialized")
        print(f"   Model  : {ANTHROPIC_MODEL}")
        print(f"   Zones  : {len(ZONES)}")
        print(f"   Weather: {'Open-Meteo' if REQUESTS_AVAILABLE else 'Simulated'}\n")

    def _agentic_loop(self, user_message: str) -> str:
        """Run the full tool-use loop until the model returns a final text response."""
        self.conversation_history.append({"role": "user", "content": user_message})

        while True:
            response = self.client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=self.conversation_history,
            )

            # Collect text and tool-use blocks
            text_blocks = []
            tool_calls  = []
            for block in response.content:
                if block.type == "text":
                    text_blocks.append(block.text)
                elif block.type == "tool_use":
                    tool_calls.append(block)

            # If the model is done (no more tool calls), return the final answer
            if response.stop_reason == "end_turn" or not tool_calls:
                final_text = "\n".join(text_blocks).strip()
                self.conversation_history.append(
                    {"role": "assistant", "content": response.content}
                )
                return final_text

            # Execute tool calls and feed results back
            self.conversation_history.append(
                {"role": "assistant", "content": response.content}
            )
            tool_results = []
            for tc in tool_calls:
                print(f"   [tool] {tc.name}({json.dumps(tc.input)})")
                result = dispatch_tool(tc.name, tc.input)
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": tc.id,
                    "content":     json.dumps(result),
                })
            self.conversation_history.append(
                {"role": "user", "content": tool_results}
            )

    def query(self, question: str) -> str:
        return self._agentic_loop(question)

    def run_status_check(self):
        """Autonomous: pull all zone data and surface any critical alerts."""
        print("\n-- Automated status check ------------------------------")
        response = self.query(
            "Run a full status check across all zones. Summarize overall risk, "
            "highlight any zones at HIGH or EXTREME risk, list active alerts, "
            "and recommend immediate actions if needed."
        )
        print(f"\n{response}\n")

    def chat(self):
        """Interactive REPL — type questions, 'status' for a full check, 'quit' to exit."""
        print("=" * 60)
        print("  Colorado Fire Risk AI Agent - Interactive Mode")
        print("=" * 60)
        print("Commands: 'status' = full check | 'clear' = reset | 'quit' = exit\n")

        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nAgent shutting down. Stay safe.")
                break

            if not user_input:
                continue
            if user_input.lower() == "quit":
                print("Agent shutting down. Stay safe.")
                break
            if user_input.lower() == "clear":
                self.conversation_history.clear()
                print("Conversation cleared.\n")
                continue
            if user_input.lower() == "status":
                self.run_status_check()
                continue

            print("\nAgent: ", end="", flush=True)
            answer = self.query(user_input)
            print(answer)
            print()


# Alternate agent core — OpenAI ChatGPT
class ChatGPTFireRiskAgent:
    def __init__(self):
        if not OPENAI_AVAILABLE:
            raise RuntimeError("openai package not installed. Run: pip install openai")
        self.client = OpenAI()
        self.conversation_history: list[dict] = []
        print("\nChatGPT Fire Risk Agent initialized")
        print(f"   Model  : {OPENAI_MODEL}")
        print(f"   Zones  : {len(ZONES)}")
        print(f"   Weather: {'Open-Meteo' if REQUESTS_AVAILABLE else 'Simulated'}\n")

    def _agentic_loop(self, user_message: str) -> str:
        """Run the full tool-use loop until the model returns a final text response."""
        self.conversation_history.append({"role": "user", "content": user_message})

        while True:
            messages = [{"role": "system", "content": SYSTEM_PROMPT}] + self.conversation_history
            response = self.client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=messages,
                tools=OPENAI_TOOLS,
                tool_choice="auto",
            )

            message = response.choices[0].message
            tool_calls = message.tool_calls or []

            if not tool_calls:
                final_text = (message.content or "").strip()
                self.conversation_history.append(
                    {"role": "assistant", "content": final_text}
                )
                return final_text

            assistant_message = {
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [],
            }
            for tc in tool_calls:
                assistant_message["tool_calls"].append(
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                )
            self.conversation_history.append(assistant_message)

            tool_results = []
            for tc in tool_calls:
                print(f"   [tool] {tc.function.name}({tc.function.arguments})")
                try:
                    inputs = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    inputs = {}
                result = dispatch_tool(tc.function.name, inputs)
                tool_results.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result),
                    }
                )
            self.conversation_history.extend(tool_results)

    def query(self, question: str) -> str:
        return self._agentic_loop(question)

    def run_status_check(self):
        """Autonomous: pull all zone data and surface any critical alerts."""
        print("\n-- Automated status check ---------------------------------")
        response = self.query(
            "Run a full status check across all zones. Summarize overall risk, "
            "highlight any zones at HIGH or EXTREME risk, list active alerts, "
            "and recommend immediate actions if needed."
        )
        print(f"\n{response}\n")

    def chat(self):
        """Interactive REPL — type questions, 'status' for a full check, 'quit' to exit."""
        print("=" * 60)
        print("  Colorado Fire Risk AI Agent - Interactive Mode")
        print("=" * 60)
        print("Commands: 'status' = full check | 'clear' = reset | 'quit' = exit\n")

        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nAgent shutting down. Stay safe.")
                break

            if not user_input:
                continue
            if user_input.lower() == "quit":
                print("Agent shutting down. Stay safe.")
                break
            if user_input.lower() == "clear":
                self.conversation_history.clear()
                print("Conversation cleared.\n")
                continue
            if user_input.lower() == "status":
                self.run_status_check()
                continue

            print("\nAgent: ", end="", flush=True)
            answer = self.query(user_input)
            print(answer)
            print()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    agent = FireRiskAgent()
    # To use ChatGPT instead:
    # agent = ChatGPTFireRiskAgent()

    # Demo: run one autonomous status check, then enter interactive mode
    agent.run_status_check()
    agent.chat()








