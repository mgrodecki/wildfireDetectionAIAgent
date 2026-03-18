# Colorado Fire Risk AI Agent

This application is a real-time wildfire monitoring across 6 geographic zones in Colorado using live weather data, AI-powered risk scoring, and a conversational interface for instant situational awareness and response recommendations.

---

## Overview

The Colorado Fire Risk AI Agent is an intelligent monitoring system that continuously tracks wildfire danger across six zones in Colorado. It combines real-time weather conditions with a multi-factor risk model and a Claude-powered conversational interface — giving fire managers, emergency responders, and public safety officials a single tool for situational awareness and decision support.

Rather than a static dashboard, this agent lets you ask plain-English questions and receive specific, data-driven answers. It reasons over live conditions, interprets trends, and generates tiered response plans when risk levels escalate.

---

## Features

- **6-zone risk monitoring** — NE Ridge, West Valley, South Basin, Central Plain, Lakeside, North Marsh
- **0–100 fire danger index** — weighted composite of fuel moisture, wind speed, temperature, humidity, terrain slope, and vegetation density
- **Four risk levels** — LOW, MODERATE, HIGH, EXTREME with zone-specific response plans
- **Conversational AI interface** — ask questions in plain English and get context-aware answers
- **Automated status checks** — sweep all zones and surface critical conditions unprompted
- **Active alerts** — Red Flag Warnings, Fire Weather Watches, and county burn bans
- **Multi-day forecast** — fire weather outlook with improving/worsening trend analysis
- **Real or simulated weather** — works out of the box with simulated data; plug in OpenWeatherMap for live conditions

---

## Requirements

- Python 3.9+
- An Anthropic API key ([get one here](https://console.anthropic.com))
- _(Optional)_ An OpenWeatherMap API key for live weather ([free tier](https://openweathermap.org/api))

---

## Installation

**1. Clone or download the project**

```bash
git clone https://github.com/your-org/fire-risk-agent.git
cd fire-risk-agent
```

**2. Install dependencies**

```bash
pip install anthropic requests python-dotenv
```

**3. Set your API keys**

Option A — export directly in your terminal:
```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OPENWEATHER_API_KEY=your_key_here   # optional
```

Option B — create a `.env` file in the project root:
```
ANTHROPIC_API_KEY=sk-ant-...
OPENWEATHER_API_KEY=your_key_here
```

Then load it at the top of the script with:
```python
from dotenv import load_dotenv
load_dotenv()
```

---

## Usage

**Run the agent:**

```bash
python fire_risk_agent.py
```

On startup the agent automatically runs a full status check across all zones, then enters interactive chat mode.

**Interactive commands:**

| Input | Action |
|---|---|
| Any question | Ask the agent about fire risk, zones, alerts, or forecasts |
| `status` | Run a full automated check across all 6 zones |
| `clear` | Reset conversation history |
| `quit` | Exit the agent |

**Example questions to try:**

```
What is the current risk in NE Ridge?
Which zone is most dangerous right now?
Should we pre-position crews in West Valley?
What's driving the risk spike in NE Ridge?
Give me a 3-day fire weather forecast.
Are there any active Red Flag Warnings?
What should responders do if NE Ridge hits EXTREME?
Compare risk across all zones.
```

---

## Risk Model

The danger index is a weighted composite of six factors:

| Factor | Weight | Notes |
|---|---|---|
| Fuel moisture | 30% | Below 5% is critical |
| Wind speed | 25% | Above 30 mph is high risk |
| Temperature | 20% | Above 95°F scores maximum |
| Humidity | 15% | Below 15% is critically low |
| Terrain slope | 5% | Steeper = faster fire spread |
| Vegetation density | 5% | Denser fuel load = higher risk |

**Risk levels:**

| Score | Level | Typical Response |
|---|---|---|
| 0–39 | LOW | Routine monitoring |
| 40–64 | MODERATE | Increased patrols, public advisory |
| 65–84 | HIGH | Pre-position crews, evacuation warnings |
| 85–100 | EXTREME | Mandatory evacuations, full ICS activation |

---

## Agent Tools

The AI uses five internal tools to gather data before responding:

| Tool | Description |
|---|---|
| `get_zone_risk` | Weather and risk score for a single zone |
| `get_all_zones_risk` | Ranked risk summary across all 6 zones |
| `get_active_alerts` | Current Red Flag Warnings and burn bans |
| `get_weather_forecast` | Multi-day fire weather outlook (1–5 days) |
| `get_response_recommendations` | Tactical action plan by zone and risk level |

---

## Extending the Agent

**Add a new zone** — append to the `ZONES` list in the script:
```python
{"name": "East Foothills", "lat": 39.73, "lon": -104.98}
```

**Connect to NWS alerts** — replace the `tool_get_active_alerts` function body with a call to:
```
https://api.weather.gov/alerts/active?area=CO
```

**Connect to InciWeb** — fetch active fire incidents from:
```
https://inciweb.wildfire.gov/state/colorado
```

**Schedule automated checks** — run `agent.run_status_check()` on a cron job or with `schedule`:
```python
import schedule
schedule.every(30).minutes.do(agent.run_status_check)
```

---

## Project Structure

```
fire-risk-agent/
├── fire_risk_agent.py   # Main agent — all logic in one file
├── README.md            # This file
└── .env                 # API keys (do not commit to git)
```

---

## Data Sources

| Source | Usage |
|---|---|
| [OpenWeatherMap](https://openweathermap.org) | Live temperature, humidity, wind (optional) |
| [National Weather Service](https://api.weather.gov) | Alerts and warnings (integration-ready) |
| [InciWeb](https://inciweb.wildfire.gov) | Active fire incidents (integration-ready) |
| [DFPC Colorado](https://dfpc.colorado.gov) | State wildfire information resource |

---

## License

MIT License. See `LICENSE` for details.
