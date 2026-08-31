"use strict";

const rowHeight = 64;
const sourceTracks = [];
const targetTracks = [];
const displayedLogs = [];
let csrfToken = "";
let generation = null;
let logCursor = 0;
let polling = false;

const $ = (selector) => document.querySelector(selector);
const form = $("#migration-form");
const planButton = $("#plan-button");
const applyButton = $("#apply-button");
const notice = $("#notice");
const logOutput = $("#log-output");

const phaseNames = {
  idle: "等待开始",
  loading: "读取网易云",
  matching: "匹配中",
  ready: "等待确认",
  applying: "写入 Spotify",
  completed: "迁移完成",
  error: "需要处理",
};

function showNotice(message) {
  notice.textContent = message;
  notice.hidden = !message;
}

function createText(className, text) {
  const element = document.createElement("div");
  element.className = className;
  element.textContent = text;
  return element;
}

function renderVirtual(viewport, items, targetSide) {
  const canvas = viewport.querySelector(".virtual-canvas");
  const empty = viewport.querySelector(".empty-state");
  empty.hidden = items.length > 0;
  canvas.style.height = `${Math.max(items.length * rowHeight, viewport.clientHeight)}px`;
  canvas.replaceChildren();
  if (!items.length) return;

  const start = Math.max(0, Math.floor(viewport.scrollTop / rowHeight) - 6);
  const visible = Math.ceil(viewport.clientHeight / rowHeight) + 12;
  const end = Math.min(items.length, start + visible);
  const fragment = document.createDocumentFragment();

  for (let index = start; index < end; index += 1) {
    const item = items[index];
    const row = document.createElement("div");
    row.className = "track-row";
    row.style.top = `${index * rowHeight}px`;
    row.append(createText("track-position", String(item.position)));

    const main = document.createElement("div");
    main.className = "track-main";
    const title = createText("track-title", item.title);
    if (targetSide && item.url) {
      const link = document.createElement("a");
      link.href = item.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = item.title;
      link.className = "track-link";
      title.replaceChildren(link);
    }
    main.append(title);
    main.append(createText("track-sub", [item.artists, item.album].filter(Boolean).join(" · ")));
    row.append(main);

    if (targetSide) {
      const status = document.createElement("span");
      status.className = `status-tag status-${item.status}`;
      status.textContent = item.status === "matched" ? `${Math.round(item.score * 100)}%` : item.status;
      status.title = item.reason || item.status;
      row.append(status);
    }
    fragment.append(row);
  }
  canvas.append(fragment);
}

const sourceViewport = $("#source-list");
const targetViewport = $("#target-list");
sourceViewport.addEventListener("scroll", () => renderVirtual(sourceViewport, sourceTracks, false));
targetViewport.addEventListener("scroll", () => renderVirtual(targetViewport, targetTracks, true));

function resetIncrementalState() {
  sourceTracks.length = 0;
  targetTracks.length = 0;
  displayedLogs.length = 0;
  logCursor = 0;
  sourceViewport.scrollTop = 0;
  targetViewport.scrollTop = 0;
  renderVirtual(sourceViewport, sourceTracks, false);
  renderVirtual(targetViewport, targetTracks, true);
  logOutput.textContent = "";
}

function updatePage(state) {
  csrfToken = state.csrf_token;
  if (generation !== state.generation) {
    generation = state.generation;
    resetIncrementalState();
  }
  sourceTracks.push(...state.source_tracks);
  targetTracks.push(...state.results);
  logCursor = state.log_count;
  displayedLogs.push(...state.logs);
  if (displayedLogs.length > 1000) displayedLogs.splice(0, displayedLogs.length - 1000);

  const phasePill = $("#phase-pill");
  phasePill.dataset.phase = state.phase;
  phasePill.textContent = phaseNames[state.phase] || state.phase;
  $("#progress-label").textContent = state.message;
  $("#source-name").textContent = state.source ? state.source.name : "等待载入歌单";
  $("#source-count").textContent = `${state.source_count} 首`;
  $("#target-count").textContent = `${state.result_count} 条结果`;
  $("#matched-count").textContent = state.summary.matched;
  $("#skipped-count").textContent = state.summary.skipped;

  const completed = state.progress.completed;
  const total = state.progress.total;
  const percent = total ? Math.min(100, Math.round((completed / total) * 100)) : 0;
  $("#progress-ring").style.setProperty("--progress", String(percent));
  $("#progress-percent").textContent = `${percent}%`;
  $("#progress-fraction").textContent = `${completed} / ${total}`;

  planButton.disabled = state.busy;
  applyButton.disabled = state.busy || !state.can_apply || state.phase === "completed";
  $("#manual-link").hidden = !state.manual_available;
  const spotifyLink = $("#spotify-link");
  spotifyLink.hidden = !state.playlist_url;
  spotifyLink.href = state.playlist_url || "#";
  if (state.playlist_url) $("#target-name").textContent = "迁移完成";

  renderVirtual(sourceViewport, sourceTracks, false);
  renderVirtual(targetViewport, targetTracks, true);
  if (state.logs.length) {
    logOutput.textContent = displayedLogs.join("\n");
    logOutput.scrollTop = logOutput.scrollHeight;
  }
  if (state.phase === "error") showNotice(state.message);
  else showNotice("");
}

async function pollState() {
  if (polling) return;
  polling = true;
  try {
    const query = new URLSearchParams({
      generation: generation === null ? "-1" : String(generation),
      source_after: String(sourceTracks.length),
      result_after: String(targetTracks.length),
      log_after: String(logCursor),
    });
    const response = await fetch(`/api/state?${query}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`状态请求失败：HTTP ${response.status}`);
    updatePage(await response.json());
  } catch (error) {
    showNotice(error.message || String(error));
  } finally {
    polling = false;
  }
}

async function postJson(path, payload = {}) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    body: JSON.stringify(payload),
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `请求失败：HTTP ${response.status}`);
  await pollState();
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  showNotice("");
  planButton.disabled = true;
  try {
    await postJson("/api/plan", {
      playlist: $("#playlist").value,
      spotify_client_id: $("#spotify-client-id").value,
      netease_api_base_url: $("#netease-api").value,
      expected_count: $("#expected-count").value,
      threshold: $("#threshold").value,
      ambiguity_gap: $("#ambiguity-gap").value,
      private: $("#private-playlist").checked,
    });
  } catch (error) {
    showNotice(error.message || String(error));
    planButton.disabled = false;
  }
});

applyButton.addEventListener("click", async () => {
  showNotice("");
  applyButton.disabled = true;
  try {
    await postJson("/api/apply");
  } catch (error) {
    showNotice(error.message || String(error));
    applyButton.disabled = false;
  }
});

pollState();
setInterval(pollState, 800);
