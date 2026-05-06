const state = {
  dashboard: null,
};

const riskClass = (label = "") => `risk-${label.toLowerCase()}`;

const fmtTime = (iso) => {
  if (!iso) return "--";
  return new Date(iso).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
};

const escapeHtml = (value) =>
  String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

const qs = (selector) => document.querySelector(selector);

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `Request failed: ${response.status}`);
  }
  return data;
}

function setStatus(text, ok = true) {
  const status = qs("#connectionStatus");
  status.textContent = text;
  status.style.background = ok ? "#26342b" : "#8a2f23";
}

async function loadDashboard() {
  setStatus("Refreshing");
  const data = await fetchJson("/api/dashboard");
  state.dashboard = data;
  renderDashboard(data);
  setStatus("Live");
}

function renderDashboard(data) {
  const zones = data.zones;
  const alerts = data.alerts.alerts || [];
  const burnBans = data.alerts.burn_bans || [];

  qs("#overallIndex").textContent = zones.overall_index;
  qs("#overallLabel").textContent = zones.overall_label;
  qs("#overallLabel").className = `risk-label ${riskClass(zones.overall_label)}`;
  qs("#highCount").textContent = (zones.high_count || 0) + (zones.extreme_count || 0);
  qs("#alertCount").textContent = alerts.length;
  qs("#burnBanCount").textContent = `${burnBans.length} burn ban${burnBans.length === 1 ? "" : "s"}`;
  qs("#modelName").textContent =
    data.model.provider === "openai" ? data.model.openai : data.model.anthropic;
  qs("#providerName").textContent = data.model.provider;
  qs("#lastUpdated").textContent = `Updated ${fmtTime(zones.timestamp)}`;

  renderZones(zones.zones);
  renderAlerts(data.alerts);
  renderForecast(data.forecast.forecast || []);
  renderFires(data.recent_fires);
  drawMap(data.zone_locations, zones.zones);
}

function renderZones(zones) {
  qs("#zoneList").innerHTML = zones
    .map((zone) => {
      const label = zone.risk.label;
      const index = zone.risk.index;
      return `
        <article class="zone-row">
          <div class="zone-row-top">
            <span class="zone-name">${escapeHtml(zone.zone)}</span>
            <span class="risk-label ${riskClass(label)}">${label} ${index}</span>
          </div>
          <div class="bar"><span class="${riskClass(label)}" style="width:${index}%"></span></div>
          <div class="zone-metrics">
            <span>${Math.round(zone.weather.temp_f)}°F</span>
            <span>${Math.round(zone.weather.humidity_pct)}% RH</span>
            <span>${Math.round(zone.weather.wind_mph)} mph</span>
            <span>${Math.round(zone.weather.fuel_moisture)}% fuel</span>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderAlerts(alertData) {
  const alerts = alertData.alerts || [];
  const burnBans = alertData.burn_bans || [];
  const alertHtml = alerts
    .map(
      (alert) => `
      <article class="stack-item">
        <div class="stack-item-top">
          <span class="stack-title">${escapeHtml(alert.type)}</span>
          <span class="risk-label ${riskClass(alert.severity)}">${escapeHtml(alert.severity)}</span>
        </div>
        <p>${escapeHtml(alert.message)}</p>
        <p>${escapeHtml((alert.counties || []).join(", "))}</p>
        <p>Expires ${escapeHtml(alert.expires)}</p>
      </article>
    `,
    )
    .join("");
  const banHtml = burnBans
    .map((ban) => `<article class="stack-item"><span class="stack-title">Burn Ban</span><p>${escapeHtml(ban)}</p></article>`)
    .join("");
  qs("#alertsList").innerHTML = alertHtml + banHtml || `<p class="empty">No active alerts.</p>`;
}

function renderForecast(forecast) {
  qs("#forecastList").innerHTML = forecast
    .map(
      (day) => `
      <article class="stack-item">
        <div class="stack-item-top">
          <span class="stack-title">${escapeHtml(day.day)}</span>
          <span class="risk-label ${riskClass(day.risk_label)}">${day.risk_label} ${day.risk_index}</span>
        </div>
        <p>${day.high_f}°F high, ${day.humidity_pct}% humidity, ${day.wind_mph} mph wind</p>
        <p>${escapeHtml(day.summary)}</p>
      </article>
    `,
    )
    .join("");
}

function renderFires(fires) {
  if (fires.error) {
    qs("#firesList").innerHTML = `<p class="empty">${escapeHtml(fires.error)}</p>`;
    return;
  }
  const events = fires.events || [];
  if (!events.length) {
    qs("#firesList").innerHTML = `<p class="empty">No recent detections returned.</p>`;
    return;
  }
  qs("#firesList").innerHTML = events
    .slice(0, 4)
    .map(
      (event) => `
      <article class="stack-item">
        <span class="stack-title">${escapeHtml(event.latitude)}, ${escapeHtml(event.longitude)}</span>
        <p>Confidence ${escapeHtml(event.confidence || "n/a")} · Brightness ${escapeHtml(event.bright_ti4 || event.brightness || "n/a")}</p>
      </article>
    `,
    )
    .join("");
}

function terrainHeight(nx, ny) {
  const westSlope = 1 - nx;
  const ridge =
    0.34 * Math.exp(-Math.pow(nx - 0.24, 2) / 0.016) +
    0.18 * Math.exp(-Math.pow(nx - 0.48, 2) / 0.028);
  const basin = -0.16 * Math.exp(-(Math.pow(nx - 0.78, 2) + Math.pow(ny - 0.58, 2)) / 0.06);
  const folds =
    0.055 * Math.sin(nx * 28 + ny * 9) +
    0.04 * Math.sin(nx * 13 - ny * 22) +
    0.025 * Math.cos((nx + ny) * 34);
  return westSlope * 0.48 + ridge + basin + folds;
}

function terrainColor(heightValue, shade) {
  const stops = [
    { at: 0.12, color: [195, 206, 166] },
    { at: 0.32, color: [219, 207, 156] },
    { at: 0.5, color: [187, 154, 105] },
    { at: 0.68, color: [139, 120, 95] },
    { at: 0.86, color: [220, 218, 203] },
  ];
  const h = Math.max(0, Math.min(0.95, heightValue));
  let lower = stops[0];
  let upper = stops[stops.length - 1];
  for (let i = 1; i < stops.length; i += 1) {
    if (h <= stops[i].at) {
      lower = stops[i - 1];
      upper = stops[i];
      break;
    }
  }
  const span = Math.max(0.001, upper.at - lower.at);
  const t = (h - lower.at) / span;
  const lit = 0.78 + shade * 0.38;
  const rgb = lower.color.map((channel, index) =>
    Math.round((channel + (upper.color[index] - channel) * t) * lit),
  );
  return `rgb(${rgb.map((value) => Math.max(0, Math.min(255, value))).join(",")})`;
}

function drawTopoBase(ctx, width, height) {
  const cell = 10;
  for (let y = 0; y < height; y += cell) {
    for (let x = 0; x < width; x += cell) {
      const nx = x / width;
      const ny = y / height;
      const center = terrainHeight(nx, ny);
      const east = terrainHeight((x + cell) / width, ny);
      const south = terrainHeight(nx, (y + cell) / height);
      const shade = (center - east) * 2.2 + (center - south) * 1.4;
      ctx.fillStyle = terrainColor(center, shade);
      ctx.fillRect(x, y, cell + 1, cell + 1);
    }
  }

  ctx.save();
  ctx.globalAlpha = 0.22;
  ctx.fillStyle = "#ffffff";
  for (let i = -height; i < width; i += 62) {
    ctx.beginPath();
    ctx.moveTo(i, height);
    ctx.lineTo(i + height * 0.9, 0);
    ctx.lineTo(i + height * 0.9 + 20, 0);
    ctx.lineTo(i + 20, height);
    ctx.closePath();
    ctx.fill();
  }
  ctx.restore();
}

function drawContourLines(ctx, width, height) {
  const levels = [0.22, 0.3, 0.38, 0.46, 0.54, 0.62, 0.7, 0.78];
  levels.forEach((level, levelIndex) => {
    ctx.strokeStyle = levelIndex % 2 === 0 ? "rgba(91, 75, 47, 0.48)" : "rgba(91, 75, 47, 0.3)";
    ctx.lineWidth = levelIndex % 2 === 0 ? 1.3 : 0.85;
    for (let y = 26; y < height - 20; y += 16) {
      ctx.beginPath();
      let drawing = false;
      for (let x = 16; x < width - 16; x += 10) {
        const nx = x / width;
        const ny = y / height;
        const h = terrainHeight(nx, ny);
        const wave = Math.sin((nx * 11 + ny * 5 + level) * Math.PI) * 7;
        const contourY = y + (h - level) * 42 + wave;
        if (Math.abs(h - level) < 0.035) {
          if (!drawing) {
            ctx.moveTo(x, contourY);
            drawing = true;
          } else {
            ctx.lineTo(x, contourY);
          }
        } else if (drawing) {
          ctx.stroke();
          ctx.beginPath();
          drawing = false;
        }
      }
      if (drawing) ctx.stroke();
    }

    if (levelIndex % 2 === 0) {
      const labelX = 48 + levelIndex * 86;
      const labelY = 92 + ((levelIndex * 37) % 230);
      ctx.fillStyle = "rgba(255,255,255,0.68)";
      ctx.fillRect(labelX - 8, labelY - 13, 58, 18);
      ctx.fillStyle = "rgba(76, 61, 39, 0.9)";
      ctx.font = "11px Segoe UI, Arial";
      ctx.fillText(`${6200 + levelIndex * 450} ft`, labelX, labelY);
    }
  });
}

function drawTopoFeatures(ctx, width, height) {
  ctx.save();
  ctx.lineCap = "round";

  ctx.strokeStyle = "rgba(63, 103, 126, 0.52)";
  ctx.lineWidth = 2.2;
  [
    [[0.18, 0.08], [0.28, 0.26], [0.23, 0.46], [0.36, 0.75], [0.42, 0.96]],
    [[0.55, 0.0], [0.49, 0.2], [0.58, 0.42], [0.53, 0.64], [0.65, 1.0]],
    [[0.76, 0.12], [0.7, 0.36], [0.78, 0.55], [0.72, 0.82], [0.82, 0.98]],
  ].forEach((points) => {
    ctx.beginPath();
    points.forEach(([px, py], index) => {
      const x = px * width;
      const y = py * height;
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  });

  ctx.strokeStyle = "rgba(92, 76, 48, 0.55)";
  ctx.lineWidth = 2.8;
  [
    [[0.14, 0.98], [0.18, 0.73], [0.15, 0.5], [0.2, 0.24], [0.18, 0.02]],
    [[0.39, 1], [0.35, 0.72], [0.41, 0.49], [0.36, 0.24], [0.43, 0]],
  ].forEach((points) => {
    ctx.beginPath();
    points.forEach(([px, py], index) => {
      const x = px * width;
      const y = py * height;
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  });

  ctx.fillStyle = "rgba(39, 44, 33, 0.72)";
  ctx.font = "700 13px Segoe UI, Arial";
  ctx.fillText("Continental Divide foothills", width * 0.08, height * 0.88);
  ctx.fillText("South Platte basin", width * 0.67, height * 0.2);
  ctx.fillText("Front Range canyons", width * 0.33, height * 0.58);
  ctx.restore();
}

function drawTopoLegend(ctx, width, height) {
  const x = width - 164;
  const y = height - 84;
  ctx.fillStyle = "rgba(255,255,255,0.82)";
  ctx.fillRect(x, y, 130, 54);
  ctx.fillStyle = "#18221c";
  ctx.font = "700 12px Segoe UI, Arial";
  ctx.fillText("Elevation", x + 12, y + 19);
  const colors = ["#c3cea6", "#dbcf9c", "#bb9a69", "#8b785f", "#dcdacb"];
  colors.forEach((color, index) => {
    ctx.fillStyle = color;
    ctx.fillRect(x + 12 + index * 20, y + 28, 20, 10);
  });
  ctx.fillStyle = "#647067";
  ctx.font = "10px Segoe UI, Arial";
  ctx.fillText("low", x + 12, y + 49);
  ctx.fillText("high", x + 88, y + 49);
}

function drawMap(locations, zoneRisk) {
  const canvas = qs("#zoneMap");
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);

  drawTopoBase(ctx, width, height);
  drawTopoFeatures(ctx, width, height);
  drawContourLines(ctx, width, height);
  drawTopoLegend(ctx, width, height);

  const riskByName = Object.fromEntries(zoneRisk.map((item) => [item.zone, item]));
  const lats = locations.map((z) => z.lat);
  const lons = locations.map((z) => z.lon);
  const minLat = Math.min(...lats) - 0.12;
  const maxLat = Math.max(...lats) + 0.12;
  const minLon = Math.min(...lons) - 0.18;
  const maxLon = Math.max(...lons) + 0.18;

  ctx.fillStyle = "rgba(255,255,255,0.82)";
  ctx.fillRect(18, 18, 294, 62);
  ctx.fillStyle = "#18221c";
  ctx.font = "700 19px Segoe UI, Arial";
  ctx.fillText("Colorado Front Range", 34, 45);
  ctx.fillStyle = "#647067";
  ctx.font = "12px Segoe UI, Arial";
  ctx.fillText("Topographic risk overlay", 34, 64);

  locations.forEach((zone) => {
    const risk = riskByName[zone.name];
    const x = 70 + ((zone.lon - minLon) / (maxLon - minLon)) * (width - 140);
    const y = 70 + ((maxLat - zone.lat) / (maxLat - minLat)) * (height - 140);
    const label = risk?.risk?.label || "LOW";
    const index = risk?.risk?.index || 0;
    const color = getComputedStyle(document.documentElement).getPropertyValue(`--${label.toLowerCase()}`).trim();

    ctx.beginPath();
    ctx.fillStyle = "rgba(255,255,255,0.82)";
    ctx.arc(x, y, 26, 0, Math.PI * 2);
    ctx.fill();

    ctx.beginPath();
    ctx.fillStyle = color;
    ctx.arc(x, y, 18, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = "#ffffff";
    ctx.font = "700 13px Segoe UI, Arial";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(String(index), x, y);

    ctx.fillStyle = "#18221c";
    ctx.font = "700 14px Segoe UI, Arial";
    ctx.textBaseline = "top";
    ctx.fillText(zone.name, x, y + 32);
  });

  ctx.textAlign = "start";
  ctx.textBaseline = "alphabetic";
}

function addMessage(role, body, kind = role) {
  const messages = qs("#messages");
  const node = document.createElement("div");
  node.className = `message ${kind}`;
  node.innerHTML = `
    <div class="message-role">${escapeHtml(role)}</div>
    <div class="message-body">${escapeHtml(body)}</div>
  `;
  messages.appendChild(node);
  messages.scrollTop = messages.scrollHeight;
  return node;
}

async function sendQuestion(question) {
  addMessage("You", question, "user");
  const pending = addMessage("Agent", "Working...", "agent");
  qs("#sendBtn").disabled = true;
  try {
    const data = await fetchJson("/api/query", {
      method: "POST",
      body: JSON.stringify({ question }),
    });
    pending.querySelector(".message-body").textContent = data.answer;
    await loadDashboard();
  } catch (error) {
    pending.className = "message error";
    pending.querySelector(".message-body").textContent = error.message;
  } finally {
    qs("#sendBtn").disabled = false;
  }
}

qs("#refreshBtn").addEventListener("click", () => {
  loadDashboard().catch((error) => setStatus(error.message, false));
});

qs("#clearChatBtn").addEventListener("click", async () => {
  await fetchJson("/api/clear");
  qs("#messages").innerHTML = "";
  addMessage("Agent", "Conversation cleared.", "agent");
});

qs("#chatForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = qs("#questionInput");
  const question = input.value.trim();
  if (!question) return;
  input.value = "";
  sendQuestion(question);
});

loadDashboard().catch((error) => setStatus(error.message, false));
