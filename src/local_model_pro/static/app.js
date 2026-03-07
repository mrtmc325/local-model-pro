const modelSelect = document.getElementById("modelSelect");
const modelFilterInput = document.getElementById("modelFilterInput");
const modelListMeta = document.getElementById("modelListMeta");
const customModelInput = document.getElementById("customModelInput");
const refreshModelsBtn = document.getElementById("refreshModelsBtn");
const applyModelBtn = document.getElementById("applyModelBtn");
const connectBtn = document.getElementById("connectBtn");
const resetBtn = document.getElementById("resetBtn");
const activeModelLabel = document.getElementById("activeModelLabel");
const statusBadge = document.getElementById("statusBadge");
const chatLog = document.getElementById("chatLog");
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

function setBusy(busy) {
  state.inflight = busy;
  sendBtn.disabled = busy || !state.connected;
  promptInput.disabled = !state.connected;
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
    sendWs({ type: "hello", model });
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
      updateActiveModelLabel(modelName);
      setBusy(false);
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

function resetConversation() {
  chatLog.innerHTML = "";
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
resetBtn.addEventListener("click", resetConversation);
chatForm.addEventListener("submit", sendPrompt);
modelFilterInput.addEventListener("input", () => renderModelOptions());
modelSelect.addEventListener("change", () => {
  customModelInput.value = "";
  renderModelOptions(modelSelect.value);
});

// Prevent accidental model changes when scrolling over the list without focused intent.
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

window.addEventListener("beforeunload", () => {
  closeWs();
});

setStatus(false, "offline");
setBusy(false);
loadModels();
