const modelSelect = document.getElementById("modelSelect");
const modelFilterInput = document.getElementById("modelFilterInput");
const modelListMeta = document.getElementById("modelListMeta");
const customModelInput = document.getElementById("customModelInput");
const refreshModelsBtn = document.getElementById("refreshModelsBtn");
const applyModelBtn = document.getElementById("applyModelBtn");
const knowledgeAssistToggle = document.getElementById("knowledgeAssistToggle");
const knowledgeModeMeta = document.getElementById("knowledgeModeMeta");
const groundedModeToggle = document.getElementById("groundedModeToggle");
const groundedProfileSelect = document.getElementById("groundedProfileSelect");
const groundedModeMeta = document.getElementById("groundedModeMeta");
const webAssistToggle = document.getElementById("webAssistToggle");
const webQueryInput = document.getElementById("webQueryInput");
const webSearchBtn = document.getElementById("webSearchBtn");
const webModeMeta = document.getElementById("webModeMeta");
const connectBtn = document.getElementById("connectBtn");
const resetBtn = document.getElementById("resetBtn");
const activeModelLabel = document.getElementById("activeModelLabel");
const statusBadge = document.getElementById("statusBadge");
const chatLog = document.getElementById("chatLog");
const evidenceLog = document.getElementById("evidenceLog");
const chatForm = document.getElementById("chatForm");
const promptInput = document.getElementById("promptInput");
const sendBtn = document.getElementById("sendBtn");

const state = {
  ws: null,
  connected: false,
  inflight: false,
  assistantEl: null,
  currentModel: null,
  availableModels: [],
  webAssistEnabled: false,
  knowledgeAssistEnabled: true,
  groundedModeEnabled: true,
  groundedProfile: "balanced",
};

function wsUrl() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/chat`;
}

function bytesToHuman(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(size >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function queryPlanToText(msg) {
  const lines = ["Recursive query plan:"];
  const exactRequired = Boolean(msg.exact_required);
  lines.push(`exact_required: ${exactRequired}`);
  lines.push(`reason: ${String(msg.reason || "").trim()}`);
  lines.push(`meaning: ${String(msg.meaning || "").trim()}`);
  lines.push(`purpose: ${String(msg.purpose || "").trim()}`);
  lines.push(`db_query: ${String(msg.db_query || "").trim()}`);
  lines.push(`web_query: ${String(msg.web_query || "").trim()}`);
  return lines.join("\n");
}

function memoryResultsToText(msg) {
  const query = String(msg.query || "").trim();
  const lines = [];
  if (query) {
    lines.push(`Memory results for: ${query}`);
  }
  const results = Array.isArray(msg.results) ? msg.results : [];
  if (results.length === 0) {
    lines.push("No memory results returned.");
  } else {
    results.forEach((item, idx) => {
      if (!item || typeof item !== "object") {
        return;
      }
      const insight = String(item.insight || "").trim() || "(empty insight)";
      const score = Number(item.score || 0).toFixed(3);
      const source = String(item.source_session || "").trim() || "unknown";
      const scope = String(item.actor_scope || "").trim();
      lines.push(`${idx + 1}. ${insight}`);
      lines.push(`score=${score} session=${source}${scope ? ` scope=${scope}` : ""}`);
    });
  }
  return lines.join("\n");
}

function webResultsToText(msg) {
  const query = String(msg.query || "").trim();
  const retrievedAt = String(msg.retrieved_at || "").trim();
  const lines = [];
  if (query) {
    lines.push(`Web results for: ${query}`);
  }
  if (retrievedAt) {
    lines.push(`Retrieved: ${retrievedAt}`);
  }
  const results = Array.isArray(msg.results) ? msg.results : [];
  if (results.length === 0) {
    lines.push("No results returned.");
  } else {
    results.forEach((item, idx) => {
      if (!item || typeof item !== "object") {
        return;
      }
      const title = String(item.title || "").trim() || "(untitled)";
      const url = String(item.url || "").trim();
      const snippet = String(item.snippet || "").trim();
      const sourceTag = String(item.source_tag || "").trim();
      const confidence = Number(item.confidence || 0).toFixed(2);
      lines.push(`${idx + 1}. ${title}`);
      if (url) {
        lines.push(url);
      }
      if (sourceTag) {
        lines.push(`source=${sourceTag} confidence=${confidence}`);
      }
      if (snippet) {
        lines.push(snippet);
      }
    });
  }
  return lines.join("\n");
}

function evidenceUsedToText(msg) {
  const results = Array.isArray(msg.results) ? msg.results : [];
  if (results.length === 0) {
    return "Evidence used: none";
  }
  const lines = ["Evidence used:"];
  results.forEach((item) => {
    if (!item || typeof item !== "object") {
      return;
    }
    const label = String(item.label || "").trim() || "E?";
    const sourceType = String(item.source_type || "").trim() || "unknown";
    const confidence = Number(item.confidence || 0).toFixed(2);
    const scope = String(item.actor_scope || "").trim();
    lines.push(`${label} ${sourceType} conf=${confidence}${scope ? ` scope=${scope}` : ""}`);
  });
  return lines.join("\n");
}

function groundingStatusToText(msg) {
  const profile = String(msg.profile || state.groundedProfile);
  const status = String(msg.status || "unknown");
  const confidence = Number(msg.overall_confidence || 0).toFixed(2);
  const exactRequired = Boolean(msg.exact_required);
  const note = String(msg.note || "").trim();
  const lines = [
    `Grounding status: ${status} (profile=${profile}, exact_required=${exactRequired}, confidence=${confidence})`,
  ];
  if (note) {
    lines.push(`note: ${note}`);
  }
  return lines.join("\n");
}

function clarifyToText(msg) {
  const question = String(msg.question || "").trim();
  return question ? `Clarify needed: ${question}` : "Clarify needed: specify the exact fact to verify.";
}

function memorySavedToText(msg) {
  const artifactId = String(msg.artifact_id || "").trim() || "(none)";
  const filePath = String(msg.file_path || "").trim() || "(none)";
  const indexedCount = Number(msg.indexed_count || 0);
  const note = String(msg.note || "").trim();
  const lines = [`Memory saved: artifact=${artifactId} indexed=${indexedCount} file=${filePath}`];
  if (note) {
    lines.push(`note: ${note}`);
  }
  return lines.join("\n");
}

function urlReviewSavedToText(msg) {
  const items = Array.isArray(msg.items) ? msg.items : [];
  if (items.length === 0) {
    return "URL review save: no items";
  }
  const lines = ["URL review save results:"];
  items.forEach((item, idx) => {
    if (!item || typeof item !== "object") {
      return;
    }
    const url = String(item.url || "").trim() || "(unknown url)";
    const status = String(item.status || "").trim() || "unknown";
    const indexed = Number(item.indexed_count || 0);
    const error = String(item.error || "").trim();
    lines.push(`${idx + 1}. ${url} status=${status} indexed=${indexed}`);
    if (error) {
      lines.push(`error: ${error}`);
    }
  });
  return lines.join("\n");
}

function updateWebModeMeta() {
  if (state.groundedModeEnabled && state.groundedProfile === "strict") {
    webModeMeta.textContent =
      "Web assist is available for direct web search. Strict grounded chat does not inject web evidence automatically.";
    return;
  }
  webModeMeta.textContent = state.webAssistEnabled
    ? "Web assist is on. Each chat prompt can include fresh web context."
    : "Web assist is off.";
}

function updateKnowledgeModeMeta() {
  if (state.groundedModeEnabled) {
    knowledgeModeMeta.textContent =
      "Knowledge assist is forced on by Grounded mode for recursion + memory-first retrieval.";
    return;
  }
  knowledgeModeMeta.textContent = state.knowledgeAssistEnabled
    ? "Knowledge assist is on. Prompts are recursively broken down before memory/web lookup."
    : "Knowledge assist is off.";
}

function updateGroundedModeMeta() {
  if (!state.groundedModeEnabled) {
    groundedModeMeta.textContent = "Grounded mode is off. Responses may use normal best-effort generation.";
    return;
  }
  if (state.groundedProfile === "strict") {
    groundedModeMeta.textContent =
      "Grounded mode is on (strict). Knowledge Assist is forced on. Chat responses rely on memory evidence first without automatic web injection.";
    return;
  }
  groundedModeMeta.textContent =
    "Grounded mode is on (balanced). Knowledge Assist is forced on. Web evidence can be included when Web Assist is enabled.";
}

function syncKnowledgeToggleState() {
  knowledgeAssistToggle.checked = state.knowledgeAssistEnabled;
  knowledgeAssistToggle.disabled = state.groundedModeEnabled;
}

function normalizeModelEntry(entry) {
  return {
    name: String(entry.name || "").trim(),
    size: typeof entry.size === "number" ? entry.size : null,
  };
}

function modelLabel(model) {
  return model.size ? `${model.name} (${bytesToHuman(model.size)})` : model.name;
}

function updateModelListMeta({ totalCount, shownCount, selectedName }) {
  if (totalCount === 0) {
    modelListMeta.textContent = "No downloaded models found.";
    return;
  }

  const selectedPart = selectedName ? ` selected: ${selectedName}` : "";
  modelListMeta.textContent = `${shownCount}/${totalCount} shown.${selectedPart}`;
}

function modelExists(modelName) {
  return state.availableModels.some((model) => model.name === modelName);
}

function upsertModel(modelName, size = null) {
  const normalizedName = String(modelName || "").trim();
  if (!normalizedName) {
    return;
  }

  const existing = state.availableModels.find((model) => model.name === normalizedName);
  if (existing) {
    if (typeof size === "number") {
      existing.size = size;
    }
  } else {
    state.availableModels.push({ name: normalizedName, size });
    state.availableModels.sort((a, b) => a.name.localeCompare(b.name));
  }
}

function renderModelOptions(preferredModel = null) {
  const filterText = modelFilterInput.value.trim().toLowerCase();
  const selectedBeforeRender = preferredModel || modelSelect.value || state.currentModel || "";

  const filteredModels = state.availableModels.filter((model) =>
    model.name.toLowerCase().includes(filterText)
  );

  modelSelect.innerHTML = "";
  if (filteredModels.length === 0) {
    const emptyOption = document.createElement("option");
    emptyOption.value = "";
    emptyOption.textContent = "No models match current filter";
    emptyOption.disabled = true;
    emptyOption.selected = true;
    modelSelect.appendChild(emptyOption);
    updateModelListMeta({
      totalCount: state.availableModels.length,
      shownCount: 0,
      selectedName: "",
    });
    return;
  }

  filteredModels.forEach((model) => {
    const option = document.createElement("option");
    option.value = model.name;
    option.textContent = modelLabel(model);
    option.title = modelLabel(model);
    modelSelect.appendChild(option);
  });

  const targetSelection = filteredModels.some((model) => model.name === selectedBeforeRender)
    ? selectedBeforeRender
    : filteredModels[0].name;
  modelSelect.value = targetSelection;
  updateModelListMeta({
    totalCount: state.availableModels.length,
    shownCount: filteredModels.length,
    selectedName: targetSelection,
  });
}

function setStatus(online, labelText) {
  statusBadge.textContent = labelText;
  statusBadge.classList.toggle("status-pill-online", online);
  statusBadge.classList.toggle("status-pill-offline", !online);
  connectBtn.textContent = online ? "Disconnect" : "Connect";
}

function addMessage(role, text) {
  const el = document.createElement("div");
  el.className = `msg msg-${role}`;
  el.textContent = text;
  chatLog.appendChild(el);
  chatLog.scrollTop = chatLog.scrollHeight;
  return el;
}

function renderEvidence(results) {
  evidenceLog.innerHTML = "";
  if (!Array.isArray(results) || results.length === 0) {
    const empty = document.createElement("div");
    empty.className = "evidence-empty";
    empty.textContent = "No evidence yet.";
    evidenceLog.appendChild(empty);
    return;
  }

  results.forEach((item) => {
    if (!item || typeof item !== "object") {
      return;
    }
    const card = document.createElement("div");
    card.className = "evidence-item";

    const label = String(item.label || "").trim() || "E?";
    const sourceType = String(item.source_type || "").trim() || "unknown";
    const confidence = Number(item.confidence || 0).toFixed(2);
    const actorScope = String(item.actor_scope || "").trim();
    const evidenceId = String(item.evidence_id || "").trim();

    const meta = document.createElement("div");
    meta.className = "evidence-meta";
    meta.textContent = `${label} ${sourceType} conf=${confidence}${actorScope ? ` scope=${actorScope}` : ""}`;
    card.appendChild(meta);

    if (evidenceId) {
      const evidenceMeta = document.createElement("div");
      evidenceMeta.className = "evidence-meta";
      evidenceMeta.textContent = `id=${evidenceId}`;
      card.appendChild(evidenceMeta);
    }

    const content = String(item.content || "").trim();
    if (content) {
      const contentEl = document.createElement("div");
      contentEl.className = "evidence-content";
      contentEl.textContent = content;
      card.appendChild(contentEl);
    }

    const url = String(item.url || "").trim();
    if (url) {
      const link = document.createElement("a");
      link.className = "evidence-link";
      link.href = url;
      link.target = "_blank";
      link.rel = "noreferrer noopener";
      link.textContent = url;
      card.appendChild(link);
    }

    evidenceLog.appendChild(card);
  });
}

function setBusy(busy) {
  state.inflight = busy;
  sendBtn.disabled = busy || !state.connected;
  promptInput.disabled = !state.connected;
  webSearchBtn.disabled = busy || !state.connected;
}

function selectedModel() {
  const custom = customModelInput.value.trim();
  if (custom) {
    return custom;
  }
  return modelSelect.value.trim();
}

function updateActiveModelLabel(modelName) {
  activeModelLabel.textContent = modelName ? `model: ${modelName}` : "model: n/a";
}

async function loadModels() {
  refreshModelsBtn.disabled = true;
  try {
    const response = await fetch("/api/models");
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Failed to read model list");
    }

    const models = Array.isArray(payload.models) ? payload.models : [];
    state.availableModels = models
      .map(normalizeModelEntry)
      .filter((entry) => entry.name)
      .sort((a, b) => a.name.localeCompare(b.name));

    if (state.availableModels.length === 0) {
      renderModelOptions();
      addMessage("system", "No local models found in Ollama.");
      return;
    }

    const defaultModel = String(payload.default_model || state.availableModels[0].name);
    renderModelOptions(defaultModel);
    customModelInput.value = "";
  } catch (error) {
    addMessage("system", `Model list error: ${error.message}`);
  } finally {
    refreshModelsBtn.disabled = false;
  }
}

function closeWs() {
  if (state.ws) {
    state.ws.close();
    state.ws = null;
  }
  state.connected = false;
  setStatus(false, "offline");
  setBusy(false);
}

function sendWs(payload) {
  if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
    throw new Error("WebSocket is not connected");
  }
  state.ws.send(JSON.stringify(payload));
}

function connectWs() {
  if (state.connected) {
    closeWs();
    addMessage("system", "Disconnected.");
    return;
  }

  const model = selectedModel();
  if (!model) {
    addMessage("system", "Select or type a model before connecting.");
    return;
  }

  const ws = new WebSocket(wsUrl());
  state.ws = ws;
  setStatus(false, "connecting...");
  setBusy(true);

  ws.onopen = () => {
    setStatus(true, "connected");
    state.connected = true;
    sendWs({
      type: "hello",
      model,
      web_assist_enabled: state.webAssistEnabled,
      knowledge_assist_enabled: state.knowledgeAssistEnabled,
      grounded_mode_enabled: state.groundedModeEnabled,
      grounded_profile: state.groundedProfile,
    });
    addMessage("system", `Connected. Requested model: ${model}`);
  };

  ws.onclose = () => {
    state.connected = false;
    setStatus(false, "offline");
    setBusy(false);
  };

  ws.onerror = () => {
    addMessage("system", "WebSocket error.");
  };

  ws.onmessage = (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch (_err) {
      return;
    }

    const msgType = message.type;
    if (msgType === "info") {
      addMessage("system", String(message.message || "info"));
      return;
    }

    if (msgType === "ready") {
      const modelName = String(message.model || "");
      state.currentModel = modelName;
      if (modelName) {
        if (!modelExists(modelName)) {
          upsertModel(modelName);
        }
        renderModelOptions(modelName);
      }
      if (typeof message.web_assist_enabled === "boolean") {
        state.webAssistEnabled = message.web_assist_enabled;
        webAssistToggle.checked = state.webAssistEnabled;
        updateWebModeMeta();
      }
      if (typeof message.knowledge_assist_enabled === "boolean") {
        state.knowledgeAssistEnabled = message.knowledge_assist_enabled;
      }
      if (typeof message.grounded_mode_enabled === "boolean") {
        state.groundedModeEnabled = message.grounded_mode_enabled;
        groundedModeToggle.checked = state.groundedModeEnabled;
      }
      if (typeof message.grounded_profile === "string" && message.grounded_profile) {
        state.groundedProfile = message.grounded_profile;
        groundedProfileSelect.value = state.groundedProfile;
      }
      syncKnowledgeToggleState();
      updateKnowledgeModeMeta();
      updateGroundedModeMeta();
      updateActiveModelLabel(modelName);
      setBusy(false);
      return;
    }

    if (msgType === "web_mode") {
      state.webAssistEnabled = Boolean(message.enabled);
      webAssistToggle.checked = state.webAssistEnabled;
      updateWebModeMeta();
      return;
    }

    if (msgType === "knowledge_mode") {
      state.knowledgeAssistEnabled = Boolean(message.enabled);
      syncKnowledgeToggleState();
      updateKnowledgeModeMeta();
      return;
    }

    if (msgType === "grounded_mode") {
      state.groundedModeEnabled = Boolean(message.enabled);
      groundedModeToggle.checked = state.groundedModeEnabled;
      if (state.groundedModeEnabled) {
        state.knowledgeAssistEnabled = true;
      }
      syncKnowledgeToggleState();
      updateKnowledgeModeMeta();
      updateGroundedModeMeta();
      updateWebModeMeta();
      return;
    }

    if (msgType === "grounded_profile") {
      const profile = String(message.profile || "").trim();
      if (profile === "strict" || profile === "balanced") {
        state.groundedProfile = profile;
        groundedProfileSelect.value = profile;
      }
      updateGroundedModeMeta();
      updateWebModeMeta();
      return;
    }

    if (msgType === "query_plan") {
      addMessage("system", queryPlanToText(message));
      return;
    }

    if (msgType === "memory_results") {
      addMessage("system", memoryResultsToText(message));
      return;
    }

    if (msgType === "web_results") {
      addMessage("system", webResultsToText(message));
      return;
    }

    if (msgType === "evidence_used") {
      addMessage("system", evidenceUsedToText(message));
      renderEvidence(message.results);
      return;
    }

    if (msgType === "grounding_status") {
      addMessage("system", groundingStatusToText(message));
      return;
    }

    if (msgType === "clarify_needed") {
      addMessage("system", clarifyToText(message));
      return;
    }

    if (msgType === "memory_saved") {
      addMessage("system", memorySavedToText(message));
      return;
    }

    if (msgType === "url_review_saved") {
      addMessage("system", urlReviewSavedToText(message));
      return;
    }

    if (msgType === "start") {
      state.assistantEl = addMessage("ai", "");
      setBusy(true);
      return;
    }

    if (msgType === "token") {
      if (!state.assistantEl) {
        state.assistantEl = addMessage("ai", "");
      }
      state.assistantEl.textContent += String(message.text || "");
      chatLog.scrollTop = chatLog.scrollHeight;
      return;
    }

    if (msgType === "done") {
      state.assistantEl = null;
      setBusy(false);
      if (message.model) {
        state.currentModel = String(message.model);
        updateActiveModelLabel(state.currentModel);
      }
      if (typeof message.web_assist_enabled === "boolean") {
        state.webAssistEnabled = message.web_assist_enabled;
        webAssistToggle.checked = state.webAssistEnabled;
        updateWebModeMeta();
      }
      if (typeof message.knowledge_assist_enabled === "boolean") {
        state.knowledgeAssistEnabled = message.knowledge_assist_enabled;
      }
      if (typeof message.grounded_mode_enabled === "boolean") {
        state.groundedModeEnabled = message.grounded_mode_enabled;
        groundedModeToggle.checked = state.groundedModeEnabled;
      }
      if (typeof message.grounded_profile === "string" && message.grounded_profile) {
        state.groundedProfile = message.grounded_profile;
        groundedProfileSelect.value = state.groundedProfile;
      }
      syncKnowledgeToggleState();
      updateKnowledgeModeMeta();
      updateGroundedModeMeta();
      updateWebModeMeta();
      return;
    }

    if (msgType === "error") {
      addMessage("system", `Error: ${String(message.message || "unknown error")}`);
      state.assistantEl = null;
      setBusy(false);
    }
  };
}

function applyModel() {
  if (!state.connected) {
    addMessage("system", "Connect first, then switch model.");
    return;
  }
  const model = selectedModel();
  if (!model) {
    addMessage("system", "Pick a model to switch.");
    return;
  }
  try {
    sendWs({ type: "set_model", model });
    if (!modelExists(model)) {
      upsertModel(model);
      renderModelOptions(model);
    }
    state.currentModel = model;
    updateActiveModelLabel(model);
    customModelInput.value = "";
  } catch (error) {
    addMessage("system", `Model switch failed: ${error.message}`);
  }
}

function sendWebSearch() {
  if (!state.connected) {
    addMessage("system", "Connect first.");
    return;
  }
  const query = webQueryInput.value.trim();
  if (!query) {
    addMessage("system", "Enter a web search query.");
    return;
  }
  try {
    sendWs({ type: "web_search", query });
  } catch (error) {
    addMessage("system", `Web search failed: ${error.message}`);
  }
}

function toggleWebAssist() {
  state.webAssistEnabled = webAssistToggle.checked;
  updateWebModeMeta();
  if (!state.connected) {
    return;
  }
  try {
    sendWs({ type: "set_web_mode", enabled: state.webAssistEnabled });
  } catch (error) {
    addMessage("system", `Web assist update failed: ${error.message}`);
  }
}

function toggleKnowledgeAssist() {
  state.knowledgeAssistEnabled = knowledgeAssistToggle.checked;
  updateKnowledgeModeMeta();
  if (!state.connected) {
    return;
  }
  try {
    sendWs({ type: "set_knowledge_mode", enabled: state.knowledgeAssistEnabled });
  } catch (error) {
    addMessage("system", `Knowledge assist update failed: ${error.message}`);
  }
}

function toggleGroundedMode() {
  state.groundedModeEnabled = groundedModeToggle.checked;
  if (state.groundedModeEnabled) {
    state.knowledgeAssistEnabled = true;
  }
  syncKnowledgeToggleState();
  updateKnowledgeModeMeta();
  updateGroundedModeMeta();
  updateWebModeMeta();
  if (!state.connected) {
    return;
  }
  try {
    sendWs({ type: "set_grounded_mode", enabled: state.groundedModeEnabled });
  } catch (error) {
    addMessage("system", `Grounded mode update failed: ${error.message}`);
  }
}

function setGroundedProfile() {
  const profile = groundedProfileSelect.value === "strict" ? "strict" : "balanced";
  state.groundedProfile = profile;
  updateGroundedModeMeta();
  updateWebModeMeta();
  if (!state.connected) {
    return;
  }
  try {
    sendWs({ type: "set_grounded_profile", profile });
  } catch (error) {
    addMessage("system", `Grounded profile update failed: ${error.message}`);
  }
}

function resetConversation() {
  chatLog.innerHTML = "";
  renderEvidence([]);
  state.assistantEl = null;
  if (!state.connected) {
    addMessage("system", "Local chat view cleared.");
    return;
  }
  try {
    sendWs({ type: "reset" });
    addMessage("system", "Conversation reset.");
  } catch (error) {
    addMessage("system", `Reset failed: ${error.message}`);
  }
}

function sendPrompt(event) {
  event.preventDefault();
  if (!state.connected) {
    addMessage("system", "Connect first.");
    return;
  }
  const prompt = promptInput.value.trim();
  if (!prompt) {
    return;
  }

  addMessage("user", prompt);
  promptInput.value = "";
  try {
    sendWs({ type: "chat", prompt });
  } catch (error) {
    addMessage("system", `Send failed: ${error.message}`);
    setBusy(false);
  }
}

connectBtn.addEventListener("click", connectWs);
refreshModelsBtn.addEventListener("click", loadModels);
applyModelBtn.addEventListener("click", applyModel);
webSearchBtn.addEventListener("click", sendWebSearch);
webAssistToggle.addEventListener("change", toggleWebAssist);
knowledgeAssistToggle.addEventListener("change", toggleKnowledgeAssist);
groundedModeToggle.addEventListener("change", toggleGroundedMode);
groundedProfileSelect.addEventListener("change", setGroundedProfile);
resetBtn.addEventListener("click", resetConversation);
chatForm.addEventListener("submit", sendPrompt);
modelFilterInput.addEventListener("input", () => renderModelOptions());
modelSelect.addEventListener("change", () => {
  customModelInput.value = "";
  renderModelOptions(modelSelect.value);
});

modelSelect.addEventListener(
  "wheel",
  (event) => {
    if (document.activeElement !== modelSelect) {
      event.preventDefault();
    }
  },
  { passive: false }
);

promptInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

webQueryInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    sendWebSearch();
  }
});

window.addEventListener("beforeunload", () => {
  closeWs();
});

setStatus(false, "offline");
setBusy(false);
updateWebModeMeta();
updateKnowledgeModeMeta();
updateGroundedModeMeta();
syncKnowledgeToggleState();
renderEvidence([]);
loadModels();
