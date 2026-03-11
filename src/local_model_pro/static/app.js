const modelSelect = document.getElementById("modelSelect");
const modelFilterInput = document.getElementById("modelFilterInput");
const modelListMeta = document.getElementById("modelListMeta");
const customModelInput = document.getElementById("customModelInput");
const refreshModelsBtn = document.getElementById("refreshModelsBtn");
const applyModelBtn = document.getElementById("applyModelBtn");
const pullModelInput = document.getElementById("pullModelInput");
const pullModelBtn = document.getElementById("pullModelBtn");
const refreshPullJobBtn = document.getElementById("refreshPullJobBtn");
const deleteModelBtn = document.getElementById("deleteModelBtn");
const modelAdminMeta = document.getElementById("modelAdminMeta");
const storeSelect = document.getElementById("storeSelect");
const storeQueryInput = document.getElementById("storeQueryInput");
const storeSearchBtn = document.getElementById("storeSearchBtn");
const storeOpenBtn = document.getElementById("storeOpenBtn");
const storeResultMeta = document.getElementById("storeResultMeta");
const storeResults = document.getElementById("storeResults");
const connectBtn = document.getElementById("connectBtn");
const resetBtn = document.getElementById("resetBtn");
const reasoningViewSelect = document.getElementById("reasoningViewSelect");
const activeModelLabel = document.getElementById("activeModelLabel");
const statusBadge = document.getElementById("statusBadge");
const chatLog = document.getElementById("chatLog");
const chatForm = document.getElementById("chatForm");
const promptInput = document.getElementById("promptInput");
const sendBtn = document.getElementById("sendBtn");
const reviewUploadInput = document.getElementById("reviewUploadInput");
const reviewUploadPickBtn = document.getElementById("reviewUploadPickBtn");
const reviewUploadBtn = document.getElementById("reviewUploadBtn");
const clearUploadsBtn = document.getElementById("clearUploadsBtn");
const uploadMeta = document.getElementById("uploadMeta");
const uploadList = document.getElementById("uploadList");
const mainDevflowToggle = document.getElementById("mainDevflowToggle");
const devflowSidePanel = document.getElementById("devflowSidePanel");
const menuToggleBtn = document.getElementById("menuToggleBtn");
const menuCloseBtn = document.getElementById("menuCloseBtn");
const drawerOverlay = document.getElementById("drawerOverlay");
const controlDrawer = document.getElementById("controlDrawer");
const toolHelpBtn = document.getElementById("toolHelpBtn");
const toolListBtn = document.getElementById("toolListBtn");
const toolTreeBtn = document.getElementById("toolTreeBtn");
const toolFindQueryInput = document.getElementById("toolFindQueryInput");
const toolFindPathInput = document.getElementById("toolFindPathInput");
const toolFindBtn = document.getElementById("toolFindBtn");
const toolReadPathInput = document.getElementById("toolReadPathInput");
const toolReadBtn = document.getElementById("toolReadBtn");
const toolSummaryPathInput = document.getElementById("toolSummaryPathInput");
const toolSummaryBtn = document.getElementById("toolSummaryBtn");
const toolRunCommandInput = document.getElementById("toolRunCommandInput");
const toolRunPreviewBtn = document.getElementById("toolRunPreviewBtn");
const toolRunExecBtn = document.getElementById("toolRunExecBtn");
const devflowPromptInput = document.getElementById("devflowPromptInput");
const devflowStartBtn = document.getElementById("devflowStartBtn");
const devflowStatusBtn = document.getElementById("devflowStatusBtn");
const devflowCancelBtn = document.getElementById("devflowCancelBtn");
const devflowApplySlotsBtn = document.getElementById("devflowApplySlotsBtn");
const devflowSaveSlotsBtn = document.getElementById("devflowSaveSlotsBtn");
const devflowMeta = document.getElementById("devflowMeta");
const devflowProgressBar = document.getElementById("devflowProgressBar");
const devflowTimeline = document.getElementById("devflowTimeline");
const devflowOutputs = document.getElementById("devflowOutputs");
const devflowDownloadLink = document.getElementById("devflowDownloadLink");
const devflowMainMeta = document.getElementById("devflowMainMeta");
const devflowMainProgressBar = document.getElementById("devflowMainProgressBar");
const devflowMainTimeline = document.getElementById("devflowMainTimeline");
const devflowMainOutputs = document.getElementById("devflowMainOutputs");
const devflowMainDownloadLink = document.getElementById("devflowMainDownloadLink");
const devflowRoleIntentReasoner = document.getElementById("devflowRoleIntentReasoner");
const devflowRoleIntentKnowledge = document.getElementById("devflowRoleIntentKnowledge");
const devflowRoleIntentFeasibility = document.getElementById("devflowRoleIntentFeasibility");
const devflowRoleCodeModel1 = document.getElementById("devflowRoleCodeModel1");
const devflowRoleCodeModel2 = document.getElementById("devflowRoleCodeModel2");
const devflowRoleCodeModel3 = document.getElementById("devflowRoleCodeModel3");
const devflowRoleDocInline = document.getElementById("devflowRoleDocInline");
const devflowRoleDocGit = document.getElementById("devflowRoleDocGit");
const devflowRoleDocRelease = document.getElementById("devflowRoleDocRelease");
const devflowRoleSelectors = {
  intent_reasoner: devflowRoleIntentReasoner,
  intent_knowledge: devflowRoleIntentKnowledge,
  intent_feasibility: devflowRoleIntentFeasibility,
  code_model_1: devflowRoleCodeModel1,
  code_model_2: devflowRoleCodeModel2,
  code_model_3: devflowRoleCodeModel3,
  doc_inline: devflowRoleDocInline,
  doc_git: devflowRoleDocGit,
  doc_release: devflowRoleDocRelease,
};
const profileActorInput = document.getElementById("profileActorInput");
const profileLoadBtn = document.getElementById("profileLoadBtn");
const profileApplyBtn = document.getElementById("profileApplyBtn");
const profileResetBtn = document.getElementById("profileResetBtn");
const profileCloseBtn = document.getElementById("profileCloseBtn");
const profileExportBtn = document.getElementById("profileExportBtn");
const profileImportBtn = document.getElementById("profileImportBtn");
const profileImportInput = document.getElementById("profileImportInput");
const profileMeta = document.getElementById("profileMeta");
const profileThemeSelect = document.getElementById("profileThemeSelect");
const profileDensitySelect = document.getElementById("profileDensitySelect");
const profileFontScaleInput = document.getElementById("profileFontScaleInput");
const profileReducedMotionInput = document.getElementById("profileReducedMotionInput");
const profileHighContrastInput = document.getElementById("profileHighContrastInput");
const profileLargeTargetsInput = document.getElementById("profileLargeTargetsInput");
const profileFocusRingInput = document.getElementById("profileFocusRingInput");
const profileTerminalFontFamilySelect = document.getElementById("profileTerminalFontFamilySelect");
const profileTerminalFontSizeInput = document.getElementById("profileTerminalFontSizeInput");
const profileTerminalCursorStyleSelect = document.getElementById("profileTerminalCursorStyleSelect");
const profileTerminalScrollbackInput = document.getElementById("profileTerminalScrollbackInput");
const profileTerminalCursorBlinkInput = document.getElementById("profileTerminalCursorBlinkInput");
const profileTerminalCopyOnSelectInput = document.getElementById("profileTerminalCopyOnSelectInput");
const profileTerminalPasteWarningInput = document.getElementById("profileTerminalPasteWarningInput");
const profileTerminalBellInput = document.getElementById("profileTerminalBellInput");
const profileExportFormatSelect = document.getElementById("profileExportFormatSelect");
const profileExportFilenameTemplateInput = document.getElementById("profileExportFilenameTemplateInput");
const profileExportIncludeTimestampsInput = document.getElementById("profileExportIncludeTimestampsInput");
const profileExportIncludeMetadataInput = document.getElementById("profileExportIncludeMetadataInput");
const profileReasoningSelect = document.getElementById("profileReasoningSelect");
const profileSendShortcutSelect = document.getElementById("profileSendShortcutSelect");
const profileDefaultNumCtxInput = document.getElementById("profileDefaultNumCtxInput");
const profileDefaultTemperatureInput = document.getElementById("profileDefaultTemperatureInput");
const profileStartupViewSelect = document.getElementById("profileStartupViewSelect");
const profileTabRestorePolicySelect = document.getElementById("profileTabRestorePolicySelect");
const profileAutoFocusTerminalInput = document.getElementById("profileAutoFocusTerminalInput");
const profileTerminalConfirmInput = document.getElementById("profileTerminalConfirmInput");
const profileIdleTimeoutInput = document.getElementById("profileIdleTimeoutInput");
const profileReauthTtlInput = document.getElementById("profileReauthTtlInput");
const profileAutoLockOnBlurInput = document.getElementById("profileAutoLockOnBlurInput");
const profileDestructiveReauthInput = document.getElementById("profileDestructiveReauthInput");
const profileAuditTimezoneInput = document.getElementById("profileAuditTimezoneInput");
const profileAuditDatetimeFormatSelect = document.getElementById("profileAuditDatetimeFormatSelect");
const profileAuditDefaultLimitInput = document.getElementById("profileAuditDefaultLimitInput");
const profileMaskSensitiveCommandsInput = document.getElementById("profileMaskSensitiveCommandsInput");
const profileToastLevelSelect = document.getElementById("profileToastLevelSelect");
const profileShowConnectEventsInput = document.getElementById("profileShowConnectEventsInput");
const profileShowDisconnectEventsInput = document.getElementById("profileShowDisconnectEventsInput");
const profileSystemMessagesInput = document.getElementById("profileSystemMessagesInput");
const profileVerboseErrorsInput = document.getElementById("profileVerboseErrorsInput");
const profileDisplayNameInput = document.getElementById("profileDisplayNameInput");
const profileEmailInput = document.getElementById("profileEmailInput");
const profileSystemPromptInput = document.getElementById("profileSystemPromptInput");
const adminTokenInput = document.getElementById("adminTokenInput");
const adminLoadBtn = document.getElementById("adminLoadBtn");
const adminRefreshEventsBtn = document.getElementById("adminRefreshEventsBtn");
const adminCloseBtn = document.getElementById("adminCloseBtn");
const adminSavePlatformBtn = document.getElementById("adminSavePlatformBtn");
const adminCreateUsernameInput = document.getElementById("adminCreateUsernameInput");
const adminCreateRoleSelect = document.getElementById("adminCreateRoleSelect");
const adminCreateUserBtn = document.getElementById("adminCreateUserBtn");
const adminUsersList = document.getElementById("adminUsersList");
const adminEventsList = document.getElementById("adminEventsList");
const adminMeta = document.getElementById("adminMeta");
const platformAllowPull = document.getElementById("platformAllowPull");
const platformAllowDelete = document.getElementById("platformAllowDelete");
const platformAllowStoreSearch = document.getElementById("platformAllowStoreSearch");
const platformAllowFilesystem = document.getElementById("platformAllowFilesystem");
const platformAllowTerminal = document.getElementById("platformAllowTerminal");
const platformAllowShellExecute = document.getElementById("platformAllowShellExecute");
const platformReadonlyMode = document.getElementById("platformReadonlyMode");
const toolActionElements = [
  toolHelpBtn,
  toolListBtn,
  toolTreeBtn,
  toolFindBtn,
  toolReadBtn,
  toolSummaryBtn,
  toolRunPreviewBtn,
  toolRunExecBtn,
].filter(Boolean);
const toolInputElements = [
  toolFindQueryInput,
  toolFindPathInput,
  toolReadPathInput,
  toolSummaryPathInput,
  toolRunCommandInput,
].filter(Boolean);

const state = {
  ws: null,
  connected: false,
  inflight: false,
  assistantEl: null,
  assistantRaw: "",
  currentModel: null,
  availableModels: [],
  modelStores: [],
  activePullJobId: null,
  pullPollTimer: null,
  profileVersion: null,
  profileLoadedActor: "anonymous",
  profilePreferences: null,
  adminPlatform: null,
  devflowJobId: null,
  devflowStatus: "idle",
  devflowTimelineItems: [],
  devflowOutputsByKey: {},
  devflowPendingStart: null,
  uploadedMaterials: [],
};

function setDrawerOpen(open) {
  const isOpen = Boolean(open);
  document.body.classList.toggle("drawer-open", isOpen);
  if (menuToggleBtn) {
    menuToggleBtn.setAttribute("aria-expanded", isOpen ? "true" : "false");
  }
  if (drawerOverlay) {
    drawerOverlay.setAttribute("aria-hidden", isOpen ? "false" : "true");
  }
  if (controlDrawer) {
    controlDrawer.setAttribute("aria-hidden", isOpen ? "false" : "true");
  }
}

function closeDrawer() {
  setDrawerOpen(false);
}

function toggleDrawer() {
  setDrawerOpen(!document.body.classList.contains("drawer-open"));
}

function wsUrl() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/chat`;
}

function currentActorId() {
  const value = String(profileActorInput?.value || "").trim();
  return value || "anonymous";
}

function adminHeaders(baseHeaders = {}) {
  const headers = { ...baseHeaders };
  const token = String(adminTokenInput?.value || "").trim();
  if (token) {
    headers["X-Admin-Token"] = token;
  }
  return headers;
}

async function apiJson(path, options = {}) {
  const response = await fetch(path, options);
  let payload = {};
  let rawText = "";
  try {
    rawText = await response.text();
  } catch (_err) {
    rawText = "";
  }

  if (rawText.trim()) {
    try {
      payload = JSON.parse(rawText);
    } catch (_err) {
      const preview = rawText.replace(/\s+/g, " ").trim().slice(0, 160);
      const suffix = preview ? `: ${preview}` : "";
      throw new Error(`Invalid JSON response from ${path}${suffix}`);
    }
  }

  if (!response.ok) {
    const detail = payload?.detail;
    if (typeof detail === "string" && detail) {
      throw new Error(detail);
    }
    throw new Error(`Request failed (${response.status})`);
  }
  return payload;
}

function setProfileMeta(text) {
  if (profileMeta) {
    profileMeta.textContent = text;
  }
}

function setAdminMeta(text) {
  if (adminMeta) {
    adminMeta.textContent = text;
  }
}

function setDevflowMeta(text) {
  if (devflowMeta) {
    devflowMeta.textContent = text;
  }
  if (devflowMainMeta) {
    devflowMainMeta.textContent = text;
  }
}

function uploadIds() {
  return state.uploadedMaterials.map((item) => String(item.upload_id || "").trim()).filter(Boolean);
}

function setUploadMeta(text) {
  if (uploadMeta) {
    uploadMeta.textContent = String(text || "");
  }
}

function renderUploadList() {
  if (!uploadList) {
    return;
  }
  uploadList.innerHTML = "";
  const uploads = Array.isArray(state.uploadedMaterials) ? state.uploadedMaterials : [];
  if (!uploads.length) {
    uploadList.hidden = true;
    setUploadMeta("No uploaded files attached.");
    return;
  }
  uploadList.hidden = false;
  uploads.forEach((item) => {
    const row = document.createElement("div");
    row.className = "upload-item";

    const meta = document.createElement("div");
    meta.className = "upload-item-meta";

    const title = document.createElement("div");
    title.className = "upload-item-title";
    title.textContent = `${String(item.filename || "upload")} (${String(item.kind || "file")})`;

    const summary = document.createElement("div");
    summary.className = "upload-item-summary";
    summary.textContent = String(item.summary || "");

    meta.appendChild(title);
    meta.appendChild(summary);

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "tool-action secondary";
    removeBtn.dataset.uploadId = String(item.upload_id || "");
    removeBtn.textContent = "Remove";

    row.appendChild(meta);
    row.appendChild(removeBtn);
    uploadList.appendChild(row);
  });
  setUploadMeta(`${uploads.length} uploaded file/ZIP item(s) attached to prompts.`);
}

function upsertUploadedMaterial(upload) {
  const uploadId = String(upload?.upload_id || "").trim();
  if (!uploadId) {
    return;
  }
  const next = {
    upload_id: uploadId,
    filename: String(upload?.filename || "upload"),
    kind: String(upload?.kind || "file"),
    summary: String(upload?.summary || ""),
  };
  const existingIndex = state.uploadedMaterials.findIndex(
    (item) => String(item.upload_id || "") === uploadId
  );
  if (existingIndex >= 0) {
    state.uploadedMaterials[existingIndex] = next;
  } else {
    state.uploadedMaterials.push(next);
  }
  renderUploadList();
}

async function loadUploadedMaterials() {
  try {
    const actorId = currentActorId();
    const payload = await apiJson(`/api/uploads?actor_id=${encodeURIComponent(actorId)}`);
    const uploads = Array.isArray(payload.uploads) ? payload.uploads : [];
    state.uploadedMaterials = uploads
      .map((item) => ({
        upload_id: String(item.upload_id || "").trim(),
        filename: String(item.filename || "upload"),
        kind: String(item.kind || "file"),
        summary: String(item.summary || ""),
      }))
      .filter((item) => item.upload_id);
    renderUploadList();
  } catch (error) {
    setUploadMeta(`Upload list error: ${error.message}`);
  }
}

async function removeUploadedMaterial(uploadId) {
  const id = String(uploadId || "").trim();
  if (!id) {
    return;
  }
  try {
    await apiJson(
      `/api/uploads/${encodeURIComponent(id)}?actor_id=${encodeURIComponent(currentActorId())}`,
      {
        method: "DELETE",
      }
    );
    state.uploadedMaterials = state.uploadedMaterials.filter(
      (item) => String(item.upload_id || "") !== id
    );
    renderUploadList();
  } catch (error) {
    setUploadMeta(`Remove upload error: ${error.message}`);
  }
}

async function clearUploadedMaterials() {
  try {
    await apiJson(`/api/uploads?actor_id=${encodeURIComponent(currentActorId())}`, {
      method: "DELETE",
    });
    state.uploadedMaterials = [];
    renderUploadList();
  } catch (error) {
    setUploadMeta(`Clear uploads error: ${error.message}`);
  }
}

async function uploadSelectedMaterials() {
  if (!reviewUploadInput) {
    return;
  }
  const files = Array.from(reviewUploadInput.files || []);
  if (!files.length) {
    setUploadMeta("Pick one or more files before uploading.");
    return;
  }
  if (reviewUploadBtn) {
    reviewUploadBtn.disabled = true;
  }
  try {
    for (const file of files) {
      const body = new FormData();
      body.append("actor_id", currentActorId());
      body.append("file", file);
      const response = await fetch("/api/uploads", {
        method: "POST",
        body,
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload?.detail || `Upload failed (${response.status})`);
      }
      const upload = payload?.upload;
      if (upload && typeof upload === "object") {
        upsertUploadedMaterial(upload);
      }
    }
    reviewUploadInput.value = "";
    setUploadMeta(`Uploaded ${files.length} file(s).`);
  } catch (error) {
    setUploadMeta(`Upload failed: ${error.message}`);
  } finally {
    if (reviewUploadBtn) {
      reviewUploadBtn.disabled = false;
    }
  }
}

function isMainDevflowModeEnabled() {
  return Boolean(mainDevflowToggle?.checked);
}

function syncMainDevflowPanelVisibility() {
  const shouldShow = isMainDevflowModeEnabled();
  if (devflowSidePanel) {
    devflowSidePanel.hidden = !shouldShow;
  }
  document.body.classList.toggle("devflow-main-open", shouldShow);
}

function loadMainDevflowTogglePreference() {
  if (!mainDevflowToggle) {
    return;
  }
  try {
    const raw = window.localStorage.getItem("local-model-pro.devflow.main-toggle");
    mainDevflowToggle.checked = raw === "true";
  } catch (_error) {
    mainDevflowToggle.checked = false;
  }
}

function saveMainDevflowTogglePreference() {
  if (!mainDevflowToggle) {
    return;
  }
  try {
    window.localStorage.setItem(
      "local-model-pro.devflow.main-toggle",
      mainDevflowToggle.checked ? "true" : "false"
    );
  } catch (_error) {
    return;
  }
}

function truncateText(text, maxChars = 1200) {
  const normalized = String(text || "");
  if (normalized.length <= maxChars) {
    return normalized;
  }
  return `${normalized.slice(0, maxChars)}\n...`;
}

function renderDevflowTimeline() {
  [devflowTimeline, devflowMainTimeline]
    .filter(Boolean)
    .forEach((target) => {
      target.innerHTML = "";
      if (!state.devflowTimelineItems.length) {
        const empty = document.createElement("div");
        empty.className = "field-help";
        empty.textContent = "No workflow events yet.";
        target.appendChild(empty);
        return;
      }
      state.devflowTimelineItems.slice(-40).forEach((item) => {
        const row = document.createElement("div");
        row.className = "admin-event-row";
        row.textContent = `${item.at} · ${item.label}`;
        target.appendChild(row);
      });
    });
  syncMainDevflowPanelVisibility();
}

function renderDevflowOutputs() {
  [devflowOutputs, devflowMainOutputs]
    .filter(Boolean)
    .forEach((target) => {
      target.innerHTML = "";
      const keys = Object.keys(state.devflowOutputsByKey);
      if (!keys.length) {
        const empty = document.createElement("div");
        empty.className = "field-help";
        empty.textContent = "No stage outputs yet.";
        target.appendChild(empty);
        return;
      }
      keys.forEach((key) => {
        const details = document.createElement("details");
        details.className = "devflow-output-item";
        const summary = document.createElement("summary");
        summary.textContent = key;
        const pre = document.createElement("pre");
        pre.textContent = truncateText(state.devflowOutputsByKey[key], 3000);
        details.appendChild(summary);
        details.appendChild(pre);
        target.appendChild(details);
      });
    });
  syncMainDevflowPanelVisibility();
}

function setDevflowDownload(downloadUrl) {
  [devflowDownloadLink, devflowMainDownloadLink]
    .filter(Boolean)
    .forEach((link) => {
      if (downloadUrl) {
        link.href = String(downloadUrl);
        link.classList.remove("disabled-link");
        link.setAttribute("aria-disabled", "false");
        link.textContent = "Download ZIP (Ready)";
        return;
      }
      link.href = "#";
      link.classList.add("disabled-link");
      link.setAttribute("aria-disabled", "true");
      link.textContent = "Download ZIP (Waiting)";
    });
}

function renderDevflowStatus({ status, percent, message }) {
  [devflowProgressBar, devflowMainProgressBar]
    .filter(Boolean)
    .forEach((bar) => {
      bar.value = Number(percent || 0);
    });
  state.devflowStatus = String(status || state.devflowStatus || "idle");
  setDevflowMeta(`${String(status || "idle")} · ${Math.round(Number(percent || 0))}% · ${String(message || "")}`);
  syncDevflowControls();
  syncMainDevflowPanelVisibility();
}

function syncDevflowControls() {
  const connected = Boolean(state.connected);
  const active = state.devflowStatus === "running" || state.devflowStatus === "queued";
  const pendingConnect = Boolean(state.devflowPendingStart) && !connected;
  if (devflowStartBtn) {
    devflowStartBtn.disabled = active || pendingConnect;
  }
  if (devflowStatusBtn) {
    devflowStatusBtn.disabled = !connected || !state.devflowJobId;
  }
  if (devflowCancelBtn) {
    devflowCancelBtn.disabled = !connected || !active || !state.devflowJobId;
  }
  if (devflowApplySlotsBtn) {
    devflowApplySlotsBtn.disabled = active;
  }
  if (devflowSaveSlotsBtn) {
    devflowSaveSlotsBtn.disabled = active;
  }
}

function roleSelectorOptions(selectedValue = "") {
  const options = [{ value: "", label: "Auto / fallback (use selected model pool)" }];
  state.availableModels.forEach((model) => {
    options.push({ value: model.name, label: modelLabel(model) });
  });
  if (selectedValue && !options.some((item) => item.value === selectedValue)) {
    options.push({ value: selectedValue, label: `${selectedValue} (manual)` });
  }
  return options;
}

function populateDevflowRoleSelectors(resolved = {}) {
  Object.entries(devflowRoleSelectors).forEach(([role, selectElement]) => {
    if (!selectElement) {
      return;
    }
    const currentValue = String(resolved[role] || selectElement.value || "");
    const options = roleSelectorOptions(currentValue);
    selectElement.innerHTML = "";
    options.forEach((item) => {
      const option = document.createElement("option");
      option.value = item.value;
      option.textContent = item.label;
      selectElement.appendChild(option);
    });
    selectElement.value = currentValue;
  });
}

function collectDevflowRoleModels() {
  const mapping = {};
  Object.entries(devflowRoleSelectors).forEach(([role, selectElement]) => {
    if (!selectElement) {
      return;
    }
    const value = String(selectElement.value || "").trim();
    if (value) {
      mapping[role] = value;
    }
  });
  return mapping;
}

function devflowRoleSlotsStorageKey(actorId = currentActorId()) {
  const normalized = String(actorId || "anonymous")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "_");
  return `local-model-pro.devflow.role-slots.${normalized || "anonymous"}`;
}

function saveDevflowRoleSlots({ showMessage = true } = {}) {
  const roleModels = collectDevflowRoleModels();
  try {
    window.localStorage.setItem(devflowRoleSlotsStorageKey(), JSON.stringify(roleModels));
    window.localStorage.setItem("local-model-pro.devflow.role-slots.default", JSON.stringify(roleModels));
    if (showMessage) {
      setDevflowMeta("Role slots saved.");
    }
  } catch (_error) {
    if (showMessage) {
      setDevflowMeta("Unable to save role slots in this browser.");
    }
  }
}

function loadDevflowRoleSlots() {
  let parsed = null;
  try {
    const actorRaw = window.localStorage.getItem(devflowRoleSlotsStorageKey());
    const fallbackRaw = window.localStorage.getItem("local-model-pro.devflow.role-slots.default");
    const raw = actorRaw || fallbackRaw;
    if (!raw) {
      return;
    }
    const decoded = JSON.parse(raw);
    if (!decoded || typeof decoded !== "object" || Array.isArray(decoded)) {
      return;
    }
    parsed = decoded;
  } catch (_error) {
    return;
  }
  populateDevflowRoleSelectors(parsed || {});
}

function preferredDevflowModel(roleModels = collectDevflowRoleModels()) {
  const priority = [
    "code_model_3",
    "code_model_2",
    "code_model_1",
    "intent_feasibility",
    "intent_reasoner",
    "intent_knowledge",
    "doc_inline",
    "doc_git",
    "doc_release",
  ];
  for (const role of priority) {
    const candidate = String(roleModels?.[role] || "").trim();
    if (candidate) {
      return candidate;
    }
  }
  return String(selectedModel() || state.currentModel || state.availableModels?.[0]?.name || "").trim();
}

function applyDevflowSlots() {
  const roleModels = collectDevflowRoleModels();
  const primaryModel = preferredDevflowModel(roleModels);
  if (!primaryModel) {
    setDevflowMeta("Select at least one role model to apply.");
    return;
  }
  if (!modelExists(primaryModel)) {
    upsertModel(primaryModel);
  }
  renderModelOptions(primaryModel);
  customModelInput.value = "";
  saveDevflowRoleSlots({ showMessage: false });
  if (state.connected) {
    try {
      sendWs({ type: "set_model", model: primaryModel });
      state.currentModel = primaryModel;
      updateActiveModelLabel(primaryModel);
      setDevflowMeta(`Applied slots. Active model set to ${primaryModel}.`);
      return;
    } catch (error) {
      setDevflowMeta(`Applied slots locally, but model switch failed: ${error.message}`);
      return;
    }
  }
  setDevflowMeta(`Applied slots. Next connection will use ${primaryModel}.`);
}

function pushDevflowTimeline(label) {
  const normalized = String(label || "").trim() || "event";
  state.devflowTimelineItems.push({
    at: new Date().toLocaleTimeString(),
    label: normalized,
  });
  addMessage("system", `[Devflow] ${normalized}`);
  renderDevflowTimeline();
}

function applyDevflowEvent(message) {
  const status = String(message.status || state.devflowStatus || "idle");
  const percent = Number(message.percent || 0);
  const infoMessage = String(message.message || "");
  const errorMessage = String(message.error || "");
  const composedMessage =
    message.type === "devflow_error" && errorMessage
      ? `${infoMessage}${infoMessage ? " · " : ""}${errorMessage}`
      : infoMessage;
  if (message.job_id) {
    state.devflowJobId = String(message.job_id);
  }
  renderDevflowStatus({ status, percent, message: composedMessage });
  const role = String(message.role || "");
  const stage = String(message.stage || "");
  const stageModel = String(message.model || "").trim();
  const attemptPath = String(message.attempt_path || "").trim();
  const attemptIndexRaw = Number(message.attempt_index || 0);
  const attemptIndex = Number.isFinite(attemptIndexRaw) ? attemptIndexRaw : 0;
  const attemptTag = attemptPath
    ? ` [${attemptPath}${attemptIndex > 0 ? `#${attemptIndex}` : ""}]`
    : "";
  if (message.type === "devflow_stage_result") {
    const outputKey = String(message.output_key || `${stage}.${role}` || "output");
    state.devflowOutputsByKey[outputKey] = String(message.output || "");
    renderDevflowOutputs();
    pushDevflowTimeline(
      `${stage}/${role} completed${stageModel ? ` (model=${stageModel})` : ""}${attemptTag}`
    );
  } else {
    const timelineText = composedMessage || infoMessage;
    pushDevflowTimeline(
      `${message.type}${role ? `/${role}` : ""}${attemptTag}${timelineText ? `: ${timelineText}` : ""}`
    );
  }
  const downloadUrl = String(message.download_url || "");
  if (downloadUrl) {
    setDevflowDownload(downloadUrl);
  }
  syncDevflowControls();
}

function resetDevflowView() {
  state.devflowJobId = null;
  state.devflowStatus = "idle";
  state.devflowTimelineItems = [];
  state.devflowOutputsByKey = {};
  state.devflowPendingStart = null;
  renderDevflowTimeline();
  renderDevflowOutputs();
  setDevflowDownload("");
  renderDevflowStatus({ status: "idle", percent: 0, message: "No programming workflow started." });
}

function startDevflowRun(options = {}) {
  const promptOverride =
    typeof options === "string" ? options : String(options?.promptOverride || "");
  const prompt = String(promptOverride || devflowPromptInput?.value || "").trim();
  if (!prompt) {
    setDevflowMeta("Enter a development request.");
    return;
  }
  if (devflowPromptInput) {
    devflowPromptInput.value = prompt;
  }
  const role_models = collectDevflowRoleModels();
  const primaryModel = preferredDevflowModel(role_models);
  if (!primaryModel) {
    setDevflowMeta("Select at least one role model before starting.");
    return;
  }
  saveDevflowRoleSlots({ showMessage: false });
  applyDevflowSlots();

  const fallback_models = state.availableModels.map((item) => item.name);
  const payload = {
    type: "devflow_start",
    prompt,
    actor_id: currentActorId(),
    selected_model: primaryModel,
    role_models,
    fallback_models,
    attachments: uploadIds(),
  };

  state.devflowTimelineItems = [];
  state.devflowOutputsByKey = {};
  renderDevflowTimeline();
  renderDevflowOutputs();
  setDevflowDownload("");
  if (devflowStartBtn) {
    devflowStartBtn.disabled = true;
  }
  try {
    if (!state.connected) {
      state.devflowPendingStart = payload;
      syncDevflowControls();
      setDevflowMeta(`Connecting websocket with ${primaryModel} for workflow start...`);
      connectWs({ disconnectIfConnected: false, preferredModel: primaryModel });
      return;
    }
    sendWs(payload);
    pushDevflowTimeline("Workflow start requested.");
    setDevflowMeta("Workflow start requested.");
  } catch (error) {
    setDevflowMeta(`Devflow start failed: ${error.message}`);
    state.devflowPendingStart = null;
    if (devflowStartBtn) {
      devflowStartBtn.disabled = false;
    }
    syncDevflowControls();
  }
}

function refreshDevflowStatus() {
  if (!state.connected) {
    return;
  }
  try {
    sendWs({
      type: "devflow_status",
      job_id: state.devflowJobId || undefined,
    });
  } catch (error) {
    setDevflowMeta(`Status refresh failed: ${error.message}`);
  }
}

function cancelDevflowRun() {
  if (!state.connected) {
    return;
  }
  try {
    sendWs({
      type: "devflow_cancel",
      job_id: state.devflowJobId || undefined,
    });
  } catch (error) {
    setDevflowMeta(`Cancel failed: ${error.message}`);
  }
}

function profilePayloadFromForm() {
  return {
    appearance: {
      theme_id: String(profileThemeSelect?.value || "aurora-dusk"),
      density: String(profileDensitySelect?.value || "comfortable"),
      font_scale: Number(profileFontScaleInput?.value || 1),
    },
    accessibility: {
      reduced_motion: Boolean(profileReducedMotionInput?.checked),
      high_contrast_mode: Boolean(profileHighContrastInput?.checked),
      large_click_targets: Boolean(profileLargeTargetsInput?.checked),
      enhanced_focus_ring: Boolean(profileFocusRingInput?.checked),
    },
    terminal: {
      font_family: String(profileTerminalFontFamilySelect?.value || "IBM Plex Mono"),
      font_size: Number(profileTerminalFontSizeInput?.value || 14),
      cursor_style: String(profileTerminalCursorStyleSelect?.value || "block"),
      cursor_blink: Boolean(profileTerminalCursorBlinkInput?.checked),
      copy_on_select: Boolean(profileTerminalCopyOnSelectInput?.checked),
      paste_warning: Boolean(profileTerminalPasteWarningInput?.checked),
      bell_enabled: Boolean(profileTerminalBellInput?.checked),
      scrollback_lines: Number(profileTerminalScrollbackInput?.value || 0),
    },
    sessions_models: {
      default_num_ctx: Number(profileDefaultNumCtxInput?.value || 4096),
      default_temperature: Number(profileDefaultTemperatureInput?.value || 0.2),
      startup_view: String(profileStartupViewSelect?.value || "models"),
      tab_restore_policy: String(profileTabRestorePolicySelect?.value || "none"),
      auto_focus_terminal: Boolean(profileAutoFocusTerminalInput?.checked),
    },
    security: {
      idle_timeout_minutes: Number(profileIdleTimeoutInput?.value || 30),
      auto_lock_on_blur: Boolean(profileAutoLockOnBlurInput?.checked),
      destructive_reauth_enabled: Boolean(profileDestructiveReauthInput?.checked),
      destructive_reauth_ttl_minutes: Number(profileReauthTtlInput?.value || 10),
    },
    audit: {
      timezone: String(profileAuditTimezoneInput?.value || "UTC"),
      datetime_format: String(profileAuditDatetimeFormatSelect?.value || "locale"),
      default_limit: Number(profileAuditDefaultLimitInput?.value || 100),
      mask_sensitive_commands: Boolean(profileMaskSensitiveCommandsInput?.checked),
    },
    chat: {
      reasoning_mode_default: String(profileReasoningSelect?.value || "summary"),
      system_prompt: String(profileSystemPromptInput?.value || ""),
      send_shortcut: String(profileSendShortcutSelect?.value || "enter"),
    },
    export: {
      default_format: String(profileExportFormatSelect?.value || "txt"),
      filename_template: String(profileExportFilenameTemplateInput?.value || "{model}_{timestamp}"),
      include_timestamps: Boolean(profileExportIncludeTimestampsInput?.checked),
      include_session_metadata: Boolean(profileExportIncludeMetadataInput?.checked),
    },
    account: {
      display_name: String(profileDisplayNameInput?.value || ""),
      email: String(profileEmailInput?.value || ""),
    },
    tools: {
      terminal_require_confirm: Boolean(profileTerminalConfirmInput?.checked),
      show_tool_tips: true,
    },
    notifications: {
      toast_level: String(profileToastLevelSelect?.value || "all"),
      show_connect_events: Boolean(profileShowConnectEventsInput?.checked),
      show_disconnect_events: Boolean(profileShowDisconnectEventsInput?.checked),
      verbose_error_details: Boolean(profileVerboseErrorsInput?.checked),
      show_system_messages: Boolean(profileSystemMessagesInput?.checked),
    },
  };
}

function applyProfilePreferences(preferences, { updateControls = true } = {}) {
  const payload = preferences || {};
  const appearance = payload.appearance || {};
  const accessibility = payload.accessibility || {};
  const terminal = payload.terminal || {};
  const sessionsModels = payload.sessions_models || {};
  const security = payload.security || {};
  const audit = payload.audit || {};
  const chat = payload.chat || {};
  const exportDefaults = payload.export || {};
  const account = payload.account || {};
  const tools = payload.tools || {};
  const notifications = payload.notifications || {};

  const theme = String(appearance.theme_id || "aurora-dusk");
  document.body.dataset.theme = theme;

  const fontScale = Number(appearance.font_scale || 1);
  if (Number.isFinite(fontScale)) {
    document.documentElement.style.setProperty("--ui-font-scale", String(fontScale));
  }

  document.body.classList.toggle("density-compact", String(appearance.density || "comfortable") === "compact");
  document.body.classList.toggle("accessibility-reduced-motion", Boolean(accessibility.reduced_motion));
  document.body.classList.toggle("accessibility-high-contrast", Boolean(accessibility.high_contrast_mode));
  document.body.classList.toggle("accessibility-large-targets", Boolean(accessibility.large_click_targets));
  document.body.classList.toggle("accessibility-focus-ring", Boolean(accessibility.enhanced_focus_ring));

  if (updateControls) {
    if (profileThemeSelect) {
      profileThemeSelect.value = theme;
    }
    if (profileDensitySelect) {
      profileDensitySelect.value = String(appearance.density || "comfortable");
    }
    if (profileFontScaleInput) {
      profileFontScaleInput.value = String(fontScale || 1);
    }
    if (profileReducedMotionInput) {
      profileReducedMotionInput.checked = Boolean(accessibility.reduced_motion);
    }
    if (profileHighContrastInput) {
      profileHighContrastInput.checked = Boolean(accessibility.high_contrast_mode);
    }
    if (profileLargeTargetsInput) {
      profileLargeTargetsInput.checked = Boolean(accessibility.large_click_targets);
    }
    if (profileFocusRingInput) {
      profileFocusRingInput.checked = Boolean(accessibility.enhanced_focus_ring);
    }

    if (profileTerminalFontFamilySelect) {
      profileTerminalFontFamilySelect.value = String(terminal.font_family || "IBM Plex Mono");
    }
    if (profileTerminalFontSizeInput) {
      profileTerminalFontSizeInput.value = String(Number(terminal.font_size || 14));
    }
    if (profileTerminalCursorStyleSelect) {
      profileTerminalCursorStyleSelect.value = String(terminal.cursor_style || "block");
    }
    if (profileTerminalScrollbackInput) {
      profileTerminalScrollbackInput.value = String(Number(terminal.scrollback_lines || 0));
    }
    if (profileTerminalCursorBlinkInput) {
      profileTerminalCursorBlinkInput.checked = Boolean(terminal.cursor_blink);
    }
    if (profileTerminalCopyOnSelectInput) {
      profileTerminalCopyOnSelectInput.checked = Boolean(terminal.copy_on_select);
    }
    if (profileTerminalPasteWarningInput) {
      profileTerminalPasteWarningInput.checked = Boolean(terminal.paste_warning);
    }
    if (profileTerminalBellInput) {
      profileTerminalBellInput.checked = Boolean(terminal.bell_enabled);
    }
    if (profileExportFormatSelect) {
      profileExportFormatSelect.value = String(exportDefaults.default_format || "txt");
    }
    if (profileExportFilenameTemplateInput) {
      profileExportFilenameTemplateInput.value = String(
        exportDefaults.filename_template || "{model}_{timestamp}"
      );
    }
    if (profileExportIncludeTimestampsInput) {
      profileExportIncludeTimestampsInput.checked = Boolean(exportDefaults.include_timestamps);
    }
    if (profileExportIncludeMetadataInput) {
      profileExportIncludeMetadataInput.checked = Boolean(exportDefaults.include_session_metadata);
    }

    if (profileReasoningSelect) {
      profileReasoningSelect.value = String(chat.reasoning_mode_default || "summary");
    }
    if (profileSendShortcutSelect) {
      profileSendShortcutSelect.value = String(chat.send_shortcut || "enter");
    }
    if (profileDefaultNumCtxInput) {
      profileDefaultNumCtxInput.value = String(Number(sessionsModels.default_num_ctx || 4096));
    }
    if (profileDefaultTemperatureInput) {
      profileDefaultTemperatureInput.value = String(Number(sessionsModels.default_temperature || 0.2));
    }
    if (profileStartupViewSelect) {
      profileStartupViewSelect.value = String(sessionsModels.startup_view || "models");
    }
    if (profileTabRestorePolicySelect) {
      profileTabRestorePolicySelect.value = String(sessionsModels.tab_restore_policy || "none");
    }
    if (profileAutoFocusTerminalInput) {
      profileAutoFocusTerminalInput.checked = Boolean(sessionsModels.auto_focus_terminal);
    }

    if (profileIdleTimeoutInput) {
      profileIdleTimeoutInput.value = String(Number(security.idle_timeout_minutes || 30));
    }
    if (profileReauthTtlInput) {
      profileReauthTtlInput.value = String(Number(security.destructive_reauth_ttl_minutes || 10));
    }
    if (profileAutoLockOnBlurInput) {
      profileAutoLockOnBlurInput.checked = Boolean(security.auto_lock_on_blur);
    }
    if (profileDestructiveReauthInput) {
      profileDestructiveReauthInput.checked = Boolean(security.destructive_reauth_enabled);
    }
    if (profileAuditTimezoneInput) {
      profileAuditTimezoneInput.value = String(audit.timezone || "UTC");
    }
    if (profileAuditDatetimeFormatSelect) {
      profileAuditDatetimeFormatSelect.value = String(audit.datetime_format || "locale");
    }
    if (profileAuditDefaultLimitInput) {
      profileAuditDefaultLimitInput.value = String(Number(audit.default_limit || 100));
    }
    if (profileMaskSensitiveCommandsInput) {
      profileMaskSensitiveCommandsInput.checked = Boolean(audit.mask_sensitive_commands);
    }
    if (profileToastLevelSelect) {
      profileToastLevelSelect.value = String(notifications.toast_level || "all");
    }
    if (profileShowConnectEventsInput) {
      profileShowConnectEventsInput.checked = Boolean(notifications.show_connect_events);
    }
    if (profileShowDisconnectEventsInput) {
      profileShowDisconnectEventsInput.checked = Boolean(notifications.show_disconnect_events);
    }
    if (profileTerminalConfirmInput) {
      profileTerminalConfirmInput.checked = Boolean(tools.terminal_require_confirm);
    }
    if (profileSystemMessagesInput) {
      profileSystemMessagesInput.checked = Boolean(notifications.show_system_messages);
    }
    if (profileVerboseErrorsInput) {
      profileVerboseErrorsInput.checked = Boolean(notifications.verbose_error_details);
    }
    if (profileDisplayNameInput) {
      profileDisplayNameInput.value = String(account.display_name || "");
    }
    if (profileEmailInput) {
      profileEmailInput.value = String(account.email || "");
    }
    if (profileSystemPromptInput) {
      profileSystemPromptInput.value = String(chat.system_prompt || "");
    }
  }

  if (reasoningViewSelect && !reasoningViewSelect.dataset.userChanged) {
    reasoningViewSelect.value = String(chat.reasoning_mode_default || "summary");
  }
}

function platformPatchFromForm() {
  return {
    allow_model_pull: Boolean(platformAllowPull?.checked),
    allow_model_delete: Boolean(platformAllowDelete?.checked),
    allow_model_store_search: Boolean(platformAllowStoreSearch?.checked),
    allow_filesystem_tools: Boolean(platformAllowFilesystem?.checked),
    allow_terminal_tools: Boolean(platformAllowTerminal?.checked),
    allow_shell_execute: Boolean(platformAllowShellExecute?.checked),
    readonly_mode: Boolean(platformReadonlyMode?.checked),
  };
}

function applyPlatformToControls(platform) {
  const payload = platform || {};
  if (platformAllowPull) {
    platformAllowPull.checked = Boolean(payload.allow_model_pull);
  }
  if (platformAllowDelete) {
    platformAllowDelete.checked = Boolean(payload.allow_model_delete);
  }
  if (platformAllowStoreSearch) {
    platformAllowStoreSearch.checked = Boolean(payload.allow_model_store_search);
  }
  if (platformAllowFilesystem) {
    platformAllowFilesystem.checked = Boolean(payload.allow_filesystem_tools);
  }
  if (platformAllowTerminal) {
    platformAllowTerminal.checked = Boolean(payload.allow_terminal_tools);
  }
  if (platformAllowShellExecute) {
    platformAllowShellExecute.checked = Boolean(payload.allow_shell_execute);
  }
  if (platformReadonlyMode) {
    platformReadonlyMode.checked = Boolean(payload.readonly_mode);
  }
}

function renderAdminUsers(users) {
  if (!adminUsersList) {
    return;
  }
  adminUsersList.innerHTML = "";
  if (!Array.isArray(users) || users.length === 0) {
    const empty = document.createElement("div");
    empty.className = "field-help";
    empty.textContent = "No users configured.";
    adminUsersList.appendChild(empty);
    return;
  }

  users.forEach((user) => {
    const row = document.createElement("div");
    row.className = "admin-user-row";
    row.dataset.userId = String(user.id || "");

    const meta = document.createElement("div");
    meta.className = "admin-user-meta";
    meta.textContent = `${String(user.username || "unknown")} (${String(user.role || "operator")})`;
    row.appendChild(meta);

    const controls = document.createElement("div");
    controls.className = "admin-user-controls";

    const roleSelect = document.createElement("select");
    roleSelect.innerHTML = '<option value="operator">operator</option><option value="sysadmin">sysadmin</option>';
    roleSelect.value = String(user.role || "operator");
    controls.appendChild(roleSelect);

    const statusSelect = document.createElement("select");
    statusSelect.innerHTML = '<option value="active">active</option><option value="disabled">disabled</option>';
    statusSelect.value = String(user.status || "active");
    controls.appendChild(statusSelect);

    const saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.className = "tool-action";
    saveBtn.textContent = "Save";
    saveBtn.addEventListener("click", () => {
      void updateAdminUser(String(user.id || ""), {
        role: roleSelect.value,
        status: statusSelect.value,
      });
    });
    controls.appendChild(saveBtn);

    const disableBtn = document.createElement("button");
    disableBtn.type = "button";
    disableBtn.className = "tool-action danger";
    disableBtn.textContent = "Disable";
    disableBtn.disabled = Boolean(user.is_bootstrap_root);
    disableBtn.addEventListener("click", () => {
      void disableAdminUser(String(user.id || ""));
    });
    controls.appendChild(disableBtn);

    row.appendChild(controls);
    adminUsersList.appendChild(row);
  });
}

function renderAdminEvents(events) {
  if (!adminEventsList) {
    return;
  }
  adminEventsList.innerHTML = "";
  if (!Array.isArray(events) || !events.length) {
    const empty = document.createElement("div");
    empty.className = "field-help";
    empty.textContent = "No events.";
    adminEventsList.appendChild(empty);
    return;
  }
  events.slice(0, 60).forEach((event) => {
    const row = document.createElement("div");
    row.className = "admin-event-row";
    const at = String(event.at || "");
    row.textContent = `${at} · ${String(event.event_type || "event")} · ${String(event.detail || "")}`;
    adminEventsList.appendChild(row);
  });
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
  if (
    role === "system" &&
    state.profilePreferences?.notifications &&
    state.profilePreferences.notifications.show_system_messages === false
  ) {
    return null;
  }
  const el = document.createElement("div");
  el.className = `msg msg-${role}`;
  el.textContent = text;
  chatLog.appendChild(el);
  chatLog.scrollTop = chatLog.scrollHeight;
  return el;
}

function extractReasoningTag(text, tagName) {
  const pattern = new RegExp(`<${tagName}>([\\s\\S]*?)<\\/${tagName}>`, "gi");
  const reasoningParts = [];
  let remaining = String(text || "").replace(pattern, (_match, content) => {
    const cleaned = String(content || "").trim();
    if (cleaned) {
      reasoningParts.push(cleaned);
    }
    return "";
  });

  const openTag = `<${tagName}>`;
  const closeTag = `</${tagName}>`;
  const lower = remaining.toLowerCase();
  const openIndex = lower.lastIndexOf(openTag);
  if (openIndex >= 0) {
    const closeIndex = lower.indexOf(closeTag, openIndex);
    if (closeIndex === -1) {
      const partial = remaining.slice(openIndex + openTag.length).trim();
      if (partial) {
        reasoningParts.push(partial);
      }
      remaining = remaining.slice(0, openIndex);
    }
  }

  return {
    remaining,
    reasoningParts,
  };
}

function splitReasoningAndAnswer(rawText) {
  let working = String(rawText || "");
  const reasoningParts = [];

  ["think", "reasoning"].forEach((tagName) => {
    const extracted = extractReasoningTag(working, tagName);
    working = extracted.remaining;
    if (extracted.reasoningParts.length) {
      reasoningParts.push(...extracted.reasoningParts);
    }
  });

  return {
    reasoning: reasoningParts.join("\n\n").trim(),
    answer: working.replace(/\n{3,}/g, "\n\n").trim(),
  };
}

function summarizeReasoning(text) {
  const normalized = String(text || "").trim();
  if (!normalized) {
    return "";
  }
  const maxChars = 460;
  const maxLines = 8;
  const lines = normalized.split("\n");
  const limitedLines = lines.slice(0, maxLines).join("\n");
  const truncated = limitedLines.length > maxChars ? `${limitedLines.slice(0, maxChars - 1)}…` : limitedLines;
  if (lines.length > maxLines || normalized.length > maxChars) {
    return `${truncated}\n…`;
  }
  return truncated;
}

function createAssistantShell() {
  const container = document.createElement("div");
  container.className = "msg msg-ai msg-ai-structured";
  container.dataset.raw = "";

  const reasoningBlock = document.createElement("details");
  reasoningBlock.className = "reasoning-block";
  reasoningBlock.setAttribute("data-role", "reasoning-block");
  reasoningBlock.hidden = true;

  const reasoningSummary = document.createElement("summary");
  reasoningSummary.className = "reasoning-summary";
  reasoningSummary.setAttribute("data-role", "reasoning-summary");
  reasoningSummary.textContent = "Reasoning";
  reasoningBlock.appendChild(reasoningSummary);

  const reasoningBody = document.createElement("div");
  reasoningBody.className = "reasoning-body";
  reasoningBody.setAttribute("data-role", "reasoning-body");
  reasoningBlock.appendChild(reasoningBody);

  const answerBody = document.createElement("div");
  answerBody.className = "answer-body";
  answerBody.setAttribute("data-role", "answer-body");

  container.appendChild(reasoningBlock);
  container.appendChild(answerBody);
  chatLog.appendChild(container);
  chatLog.scrollTop = chatLog.scrollHeight;
  return container;
}

function renderStructuredAssistant(container, rawText) {
  if (!container) {
    return;
  }
  container.dataset.raw = String(rawText || "");
  const reasoningBlock = container.querySelector('[data-role="reasoning-block"]');
  const reasoningSummary = container.querySelector('[data-role="reasoning-summary"]');
  const reasoningBody = container.querySelector('[data-role="reasoning-body"]');
  const answerBody = container.querySelector('[data-role="answer-body"]');
  if (!reasoningBlock || !reasoningSummary || !reasoningBody || !answerBody) {
    return;
  }

  const parsed = splitReasoningAndAnswer(rawText);
  const mode = String(reasoningViewSelect?.value || "summary");

  if (parsed.reasoning && mode !== "hidden") {
    reasoningBlock.hidden = false;
    const displayText = mode === "summary" ? summarizeReasoning(parsed.reasoning) : parsed.reasoning;
    reasoningBody.textContent = displayText;
    reasoningSummary.textContent =
      mode === "summary"
        ? `Reasoning summary (${parsed.reasoning.length} chars)`
        : `Reasoning (${parsed.reasoning.length} chars)`;
    reasoningBlock.open = mode === "full";
  } else if (mode !== "hidden") {
    reasoningBlock.hidden = false;
    reasoningSummary.textContent = "Reasoning";
    reasoningBody.textContent = state.inflight
      ? "Waiting for reasoning trace..."
      : "No reasoning trace emitted by this model. Try a thinking-capable model.";
    reasoningBlock.open = false;
  } else {
    reasoningBlock.hidden = true;
  }

  answerBody.textContent = parsed.answer || (state.inflight ? "(generating...)" : "");
  chatLog.scrollTop = chatLog.scrollHeight;
}

function rerenderReasoningMessages() {
  const messages = document.querySelectorAll(".msg-ai.msg-ai-structured");
  messages.forEach((container) => {
    const raw = String(container.dataset.raw || "");
    renderStructuredAssistant(container, raw);
  });
}

function setBusy(busy) {
  state.inflight = busy;
  const allowOfflineCompose = isMainDevflowModeEnabled();
  sendBtn.disabled = busy || (!state.connected && !allowOfflineCompose);
  promptInput.disabled = !state.connected && !allowOfflineCompose;
  toolActionElements.forEach((el) => {
    el.disabled = busy || !state.connected;
  });
  toolInputElements.forEach((el) => {
    el.disabled = busy || !state.connected;
  });
  syncDevflowControls();
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

function setModelAdminMeta(text) {
  if (modelAdminMeta) {
    modelAdminMeta.textContent = text;
  }
}

function selectedStore() {
  const id = String(storeSelect?.value || "").trim();
  return state.modelStores.find((store) => String(store.id) === id) || null;
}

function storeSearchUrl(store, query) {
  const template = String(store?.search_url_template || "").trim();
  if (!template) {
    return "";
  }
  return template.replace("{query}", encodeURIComponent(query));
}

function renderStoreOptions() {
  if (!storeSelect) {
    return;
  }
  storeSelect.innerHTML = "";
  if (!state.modelStores.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No stores available";
    option.disabled = true;
    option.selected = true;
    storeSelect.appendChild(option);
    return;
  }
  state.modelStores.forEach((store) => {
    const option = document.createElement("option");
    option.value = String(store.id || "");
    option.textContent = String(store.name || store.id || "store");
    storeSelect.appendChild(option);
  });
}

function renderStoreResults(items) {
  if (!storeResults) {
    return;
  }
  storeResults.innerHTML = "";
  if (!Array.isArray(items) || !items.length) {
    const empty = document.createElement("div");
    empty.className = "field-help";
    empty.textContent = "No results.";
    storeResults.appendChild(empty);
    return;
  }
  items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "store-result-item";

    const name = document.createElement("div");
    name.className = "store-result-name";
    name.textContent = String(item.name || item.id || "unnamed model");
    row.appendChild(name);

    const metaParts = [];
    if (item.downloads != null) {
      metaParts.push(`downloads=${item.downloads}`);
    }
    if (item.likes != null) {
      metaParts.push(`likes=${item.likes}`);
    }
    if (item.updated_at) {
      metaParts.push(`updated=${item.updated_at}`);
    }
    if (metaParts.length) {
      const meta = document.createElement("div");
      meta.className = "store-result-meta";
      meta.textContent = metaParts.join("  ");
      row.appendChild(meta);
    }

    if (item.url) {
      const link = document.createElement("a");
      link.className = "store-result-link";
      link.href = String(item.url);
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "Open";
      row.appendChild(link);
    }

    storeResults.appendChild(row);
  });
}

async function loadProfilePreferences() {
  const actorId = currentActorId();
  if (profileLoadBtn) {
    profileLoadBtn.disabled = true;
  }
  try {
    const payload = await apiJson(
      `/api/v1/profile/preferences?actor_id=${encodeURIComponent(actorId)}`
    );
    state.profileVersion = Number(payload.version || 1);
    state.profileLoadedActor = String(payload.actor_id || actorId);
    state.profilePreferences = payload.preferences || {};
    if (profileActorInput) {
      profileActorInput.value = state.profileLoadedActor;
    }
    applyProfilePreferences(state.profilePreferences);
    await loadUploadedMaterials();
    loadDevflowRoleSlots();
    setProfileMeta(
      `Loaded actor=${state.profileLoadedActor} version=${state.profileVersion}`
    );
  } catch (error) {
    setProfileMeta(`Profile load error: ${error.message}`);
  } finally {
    if (profileLoadBtn) {
      profileLoadBtn.disabled = false;
    }
  }
}

async function patchProfilePreferences(patch, metaPrefix = "Applied profile settings.") {
  const actorId = currentActorId();
  try {
    const payload = await apiJson("/api/v1/profile/preferences", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        actor_id: actorId,
        base_version: state.profileVersion,
        patch,
      }),
    });
    state.profileVersion = Number(payload.version || state.profileVersion || 1);
    state.profileLoadedActor = String(payload.actor_id || actorId);
    state.profilePreferences = payload.preferences || {};
    applyProfilePreferences(state.profilePreferences);
    setProfileMeta(
      `${metaPrefix} version=${state.profileVersion} keys=${(payload.updated_keys || []).length}`
    );
    return payload;
  } catch (error) {
    setProfileMeta(`Profile apply error: ${error.message}`);
    return null;
  }
}

async function applyProfilePreferencesFromForm() {
  if (profileApplyBtn) {
    profileApplyBtn.disabled = true;
  }
  try {
    await patchProfilePreferences(profilePayloadFromForm(), "Applied profile settings.");
  } finally {
    if (profileApplyBtn) {
      profileApplyBtn.disabled = false;
    }
  }
}

async function resetProfilePreferences() {
  const actorId = currentActorId();
  if (profileResetBtn) {
    profileResetBtn.disabled = true;
  }
  try {
    const payload = await apiJson("/api/v1/profile/preferences/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ actor_id: actorId, scope: "all" }),
    });
    state.profileVersion = Number(payload.version || 1);
    state.profileLoadedActor = String(payload.actor_id || actorId);
    state.profilePreferences = payload.preferences || {};
    applyProfilePreferences(state.profilePreferences);
    setProfileMeta(`Profile reset for ${state.profileLoadedActor}.`);
  } catch (error) {
    setProfileMeta(`Profile reset error: ${error.message}`);
  } finally {
    if (profileResetBtn) {
      profileResetBtn.disabled = false;
    }
  }
}

function exportProfileSettings() {
  const payload = {
    format: "local-model-pro.profile.v1",
    exported_at: new Date().toISOString(),
    actor_id: currentActorId(),
    version: state.profileVersion,
    preferences: profilePayloadFromForm(),
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: "application/json;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const suffix = currentActorId().replace(/[^a-z0-9._-]+/gi, "-").toLowerCase();
  const timestamp = new Date().toISOString().replace(/[:]/g, "-");
  link.href = url;
  link.download = `local-model-pro-settings-${suffix}-${timestamp}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
  setProfileMeta("Exported settings file.");
}

function triggerProfileImportPicker() {
  profileImportInput?.click();
}

async function handleProfileImportFile(event) {
  const input = event.currentTarget;
  const file = input?.files?.[0];
  if (!file) {
    return;
  }
  try {
    const rawText = await file.text();
    const parsed = JSON.parse(rawText);
    const maybePreferences =
      parsed && typeof parsed === "object" && parsed.preferences && typeof parsed.preferences === "object"
        ? parsed.preferences
        : parsed;
    if (!maybePreferences || typeof maybePreferences !== "object" || Array.isArray(maybePreferences)) {
      throw new Error("Invalid settings file format.");
    }
    const allowedCategories = [
      "appearance",
      "accessibility",
      "terminal",
      "sessions_models",
      "security",
      "audit",
      "notifications",
      "export",
      "account",
      "chat",
      "tools",
    ];
    const patch = {};
    allowedCategories.forEach((category) => {
      const value = maybePreferences[category];
      if (value && typeof value === "object" && !Array.isArray(value)) {
        patch[category] = value;
      }
    });
    if (!Object.keys(patch).length) {
      throw new Error("No supported settings categories found.");
    }
    await patchProfilePreferences(patch, "Imported and applied settings.");
  } catch (error) {
    setProfileMeta(`Import failed: ${error.message}`);
  } finally {
    if (input) {
      input.value = "";
    }
  }
}

async function loadAdminPlatform() {
  const payload = await apiJson("/api/v1/admin/platform", {
    headers: adminHeaders(),
  });
  state.adminPlatform = payload.platform || {};
  applyPlatformToControls(state.adminPlatform);
}

async function saveAdminPlatform() {
  if (adminSavePlatformBtn) {
    adminSavePlatformBtn.disabled = true;
  }
  try {
    const actorId = currentActorId();
    const payload = await apiJson("/api/v1/admin/platform", {
      method: "PATCH",
      headers: adminHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        actor_id: actorId,
        patch: platformPatchFromForm(),
      }),
    });
    state.adminPlatform = payload.platform || {};
    applyPlatformToControls(state.adminPlatform);
    setAdminMeta("Platform policy saved.");
  } catch (error) {
    setAdminMeta(`Platform save error: ${error.message}`);
  } finally {
    if (adminSavePlatformBtn) {
      adminSavePlatformBtn.disabled = false;
    }
  }
}

async function loadAdminUsers() {
  const payload = await apiJson("/api/v1/admin/users", {
    headers: adminHeaders(),
  });
  renderAdminUsers(payload.users || []);
}

async function createAdminUser() {
  const username = String(adminCreateUsernameInput?.value || "").trim();
  if (!username) {
    setAdminMeta("Enter a username for new user.");
    return;
  }
  if (adminCreateUserBtn) {
    adminCreateUserBtn.disabled = true;
  }
  try {
    await apiJson("/api/v1/admin/users", {
      method: "POST",
      headers: adminHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        actor_id: currentActorId(),
        username,
        role: String(adminCreateRoleSelect?.value || "operator"),
      }),
    });
    if (adminCreateUsernameInput) {
      adminCreateUsernameInput.value = "";
    }
    await loadAdminUsers();
    await loadAdminEvents();
    setAdminMeta(`Created user ${username}.`);
  } catch (error) {
    setAdminMeta(`Create user error: ${error.message}`);
  } finally {
    if (adminCreateUserBtn) {
      adminCreateUserBtn.disabled = false;
    }
  }
}

async function updateAdminUser(userId, patch) {
  try {
    await apiJson(`/api/v1/admin/users/${encodeURIComponent(userId)}`, {
      method: "PATCH",
      headers: adminHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        actor_id: currentActorId(),
        ...patch,
      }),
    });
    await loadAdminUsers();
    await loadAdminEvents();
    setAdminMeta(`Updated user ${userId}.`);
  } catch (error) {
    setAdminMeta(`Update user error: ${error.message}`);
  }
}

async function disableAdminUser(userId) {
  try {
    await apiJson(
      `/api/v1/admin/users/${encodeURIComponent(userId)}?actor_id=${encodeURIComponent(
        currentActorId()
      )}`,
      {
        method: "DELETE",
        headers: adminHeaders(),
      }
    );
    await loadAdminUsers();
    await loadAdminEvents();
    setAdminMeta(`Disabled user ${userId}.`);
  } catch (error) {
    setAdminMeta(`Disable user error: ${error.message}`);
  }
}

async function loadAdminEvents() {
  const payload = await apiJson("/api/v1/admin/events?limit=60", {
    headers: adminHeaders(),
  });
  renderAdminEvents(payload.events || []);
}

async function loadAdminData() {
  if (adminLoadBtn) {
    adminLoadBtn.disabled = true;
  }
  try {
    await Promise.all([loadAdminPlatform(), loadAdminUsers(), loadAdminEvents()]);
    setAdminMeta("Admin data loaded.");
  } catch (error) {
    setAdminMeta(`Admin load error: ${error.message}`);
  } finally {
    if (adminLoadBtn) {
      adminLoadBtn.disabled = false;
    }
  }
}

async function loadModels() {
  refreshModelsBtn.disabled = true;
  try {
    const payload = await apiJson("/api/models");

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
    populateDevflowRoleSelectors();
    loadDevflowRoleSlots();
    customModelInput.value = "";
    if (pullModelInput && !pullModelInput.value.trim()) {
      pullModelInput.value = defaultModel;
    }
  } catch (error) {
    addMessage("system", `Model list error: ${error.message}`);
  } finally {
    refreshModelsBtn.disabled = false;
  }
}

async function loadModelStores() {
  if (!storeSelect) {
    return;
  }
  try {
    const payload = await apiJson("/api/model-stores");
    state.modelStores = Array.isArray(payload.stores) ? payload.stores : [];
    renderStoreOptions();
  } catch (error) {
    setModelAdminMeta(`Store load error: ${error.message}`);
  }
}

function stopPullPolling() {
  if (state.pullPollTimer) {
    window.clearInterval(state.pullPollTimer);
    state.pullPollTimer = null;
  }
}

function startPullPolling(jobId) {
  stopPullPolling();
  state.pullPollTimer = window.setInterval(() => {
    void refreshPullJobStatus(jobId);
  }, 1500);
}

async function refreshPullJobStatus(jobId = state.activePullJobId) {
  if (!jobId) {
    setModelAdminMeta("No pull job in progress.");
    return;
  }
  try {
    const response = await fetch(`/api/models/pull/${encodeURIComponent(jobId)}`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Unable to fetch pull status");
    }

    const status = String(payload.status || "unknown");
    const detail = String(payload.detail || "");
    const progress =
      typeof payload.completed === "number" && typeof payload.total === "number" && payload.total > 0
        ? ` (${bytesToHuman(payload.completed)}/${bytesToHuman(payload.total)})`
        : "";

    if (status === "failed") {
      setModelAdminMeta(`Pull failed for ${payload.model}: ${payload.error || detail}`);
      stopPullPolling();
      state.activePullJobId = null;
      return;
    }

    if (status === "done") {
      setModelAdminMeta(`Pull complete for ${payload.model}.`);
      stopPullPolling();
      state.activePullJobId = null;
      await loadModels();
      return;
    }

    setModelAdminMeta(`Pull ${status}: ${detail}${progress}`);
  } catch (error) {
    setModelAdminMeta(`Pull status error: ${error.message}`);
  }
}

async function startPullModel() {
  const modelName = String(pullModelInput?.value || "").trim();
  if (!modelName) {
    setModelAdminMeta("Enter a model tag to pull.");
    return;
  }
  pullModelBtn.disabled = true;
  try {
    const response = await fetch("/api/models/pull", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: modelName }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Pull request failed");
    }
    state.activePullJobId = String(payload.job_id || "");
    setModelAdminMeta(`Pull queued for ${payload.model}.`);
    startPullPolling(state.activePullJobId);
    if (!modelExists(modelName)) {
      upsertModel(modelName);
      renderModelOptions(modelName);
    }
  } catch (error) {
    setModelAdminMeta(`Pull request error: ${error.message}`);
  } finally {
    pullModelBtn.disabled = false;
  }
}

async function deleteSelectedModel() {
  const modelName = selectedModel();
  if (!modelName) {
    setModelAdminMeta("Select a model to delete.");
    return;
  }
  const confirmed = window.confirm(`Delete model '${modelName}' from Ollama?`);
  if (!confirmed) {
    return;
  }
  deleteModelBtn.disabled = true;
  try {
    const response = await fetch("/api/models/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: modelName }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Delete failed");
    }
    setModelAdminMeta(`Deleted model ${modelName}.`);
    state.availableModels = state.availableModels.filter((item) => item.name !== modelName);
    renderModelOptions();
    customModelInput.value = "";
    if (state.currentModel === modelName) {
      state.currentModel = null;
      updateActiveModelLabel("");
    }
  } catch (error) {
    setModelAdminMeta(`Delete error: ${error.message}`);
  } finally {
    deleteModelBtn.disabled = false;
  }
}

async function searchStoreApi() {
  const store = selectedStore();
  if (!store) {
    setModelAdminMeta("No store selected.");
    return;
  }
  const query = String(storeQueryInput?.value || "").trim();
  if (!query) {
    if (storeResultMeta) {
      storeResultMeta.textContent = "Enter a search term.";
    }
    return;
  }
  if (!store.supports_api_search) {
    if (storeResultMeta) {
      storeResultMeta.textContent = `${store.name} does not expose API search. Use Open Site.`;
    }
    renderStoreResults([]);
    return;
  }
  storeSearchBtn.disabled = true;
  try {
    const url = `/api/model-stores/search?store_id=${encodeURIComponent(
      String(store.id || "")
    )}&q=${encodeURIComponent(query)}`;
    const response = await fetch(url);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Store search failed");
    }
    if (storeResultMeta) {
      storeResultMeta.textContent = `Found ${Number(payload.count || 0)} results.`;
    }
    renderStoreResults(payload.results);
  } catch (error) {
    if (storeResultMeta) {
      storeResultMeta.textContent = `Store search error: ${error.message}`;
    }
    renderStoreResults([]);
  } finally {
    storeSearchBtn.disabled = false;
  }
}

function openStoreSearch() {
  const store = selectedStore();
  if (!store) {
    return;
  }
  const query = String(storeQueryInput?.value || "").trim();
  const target = storeSearchUrl(store, query || "llm");
  if (!target) {
    if (storeResultMeta) {
      storeResultMeta.textContent = "No search URL configured for this store.";
    }
    return;
  }
  window.open(target, "_blank", "noopener,noreferrer");
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

function connectWs(options = {}) {
  const disconnectIfConnected = options?.disconnectIfConnected !== false;
  const preferredModel = String(options?.preferredModel || "").trim();
  closeDrawer();
  if (state.connected) {
    if (disconnectIfConnected) {
      closeWs();
      addMessage("system", "Disconnected.");
    }
    return;
  }

  if (state.ws && state.ws.readyState === WebSocket.CONNECTING) {
    return;
  }

  const model = preferredModel || selectedModel() || preferredDevflowModel();
  if (!model) {
    addMessage("system", "Select or type a model before connecting.");
    state.devflowPendingStart = null;
    syncDevflowControls();
    return;
  }

  const ws = new WebSocket(wsUrl());
  state.ws = ws;
  setStatus(false, "connecting...");
  setBusy(true);

  ws.onopen = () => {
    setStatus(true, "connected");
    state.connected = true;
    syncDevflowControls();
    const actorId = currentActorId();
    const systemPrompt = String(
      state.profilePreferences?.chat?.system_prompt || profileSystemPromptInput?.value || ""
    ).trim();
    sendWs({
      type: "hello",
      model,
      actor_id: actorId,
      system_prompt: systemPrompt || undefined,
    });
    addMessage("system", `Connected. Requested model: ${model} (actor=${actorId})`);
  };

  ws.onclose = () => {
    state.connected = false;
    setStatus(false, "offline");
    setBusy(false);
    if (state.devflowPendingStart) {
      setDevflowMeta("Workflow start failed because websocket disconnected.");
      state.devflowPendingStart = null;
    }
    syncDevflowControls();
  };

  ws.onerror = () => {
    addMessage("system", "WebSocket error.");
    if (state.devflowPendingStart) {
      setDevflowMeta("Workflow start failed due to websocket error.");
      state.devflowPendingStart = null;
      syncDevflowControls();
    }
  };

  ws.onmessage = (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch (_err) {
      return;
    }

    const msgType = message.type;
    if (
      msgType === "devflow_started" ||
      msgType === "devflow_progress" ||
      msgType === "devflow_stage_result" ||
      msgType === "devflow_done" ||
      msgType === "devflow_error"
    ) {
      applyDevflowEvent(message);
      if (msgType === "devflow_done" || msgType === "devflow_error") {
        syncDevflowControls();
      }
      return;
    }

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
      if (state.devflowPendingStart && state.connected) {
        const pendingPayload = state.devflowPendingStart;
        state.devflowPendingStart = null;
        try {
          sendWs(pendingPayload);
          pushDevflowTimeline("Workflow start requested.");
          setDevflowMeta("Workflow start requested.");
        } catch (error) {
          setDevflowMeta(`Workflow start failed after connect: ${error.message}`);
        }
        syncDevflowControls();
      }
      return;
    }

    if (msgType === "status") {
      addMessage(
        "system",
        `status: model=${String(message.model || "")} messages=${Number(message.message_count || 0)}`
      );
      return;
    }

    if (msgType === "start") {
      state.assistantRaw = "";
      state.assistantEl = createAssistantShell();
      renderStructuredAssistant(state.assistantEl, state.assistantRaw);
      setBusy(true);
      return;
    }

    if (msgType === "token") {
      if (!state.assistantEl) {
        state.assistantRaw = "";
        state.assistantEl = createAssistantShell();
      }
      state.assistantRaw += String(message.text || "");
      renderStructuredAssistant(state.assistantEl, state.assistantRaw);
      return;
    }

    if (msgType === "done") {
      if (state.assistantEl) {
        renderStructuredAssistant(state.assistantEl, state.assistantRaw);
      }
      state.assistantEl = null;
      state.assistantRaw = "";
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
      state.assistantRaw = "";
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
  state.assistantRaw = "";
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
  sendChatPrompt(promptInput.value);
  promptInput.value = "";
}

function sendChatPrompt(rawPrompt) {
  const prompt = String(rawPrompt || "").trim();
  if (!prompt) {
    return;
  }

  if (document.body.classList.contains("drawer-open")) {
    closeDrawer();
  }
  addMessage("user", prompt);

  if (isMainDevflowModeEnabled()) {
    startDevflowRun({ promptOverride: prompt });
    return;
  }

  if (!state.connected) {
    addMessage("system", "Connect first.");
    return;
  }

  try {
    const reasoning_mode = String(reasoningViewSelect?.value || "summary");
    sendWs({
      type: "chat",
      prompt,
      reasoning_mode,
      attachments: uploadIds(),
    });
  } catch (error) {
    addMessage("system", `Send failed: ${error.message}`);
    setBusy(false);
  }
}

function quoteToolArg(raw) {
  const value = String(raw || "").trim();
  if (!value) {
    return "";
  }
  if (!/[\s"'\\]/.test(value)) {
    return value;
  }
  return `"${value.replace(/["\\]/g, "\\$&")}"`;
}

function runToolCommand(command) {
  sendChatPrompt(command);
}

function runFindTool() {
  const query = String(toolFindQueryInput.value || "").trim();
  if (!query) {
    addMessage("system", "Enter a file search query.");
    return;
  }
  const path = String(toolFindPathInput.value || ".").trim() || ".";
  runToolCommand(`/find ${quoteToolArg(query)} ${quoteToolArg(path)}`);
}

function runReadTool() {
  const path = String(toolReadPathInput.value || "").trim();
  if (!path) {
    addMessage("system", "Enter a file path to read.");
    return;
  }
  runToolCommand(`/read ${quoteToolArg(path)}`);
}

function runSummaryTool() {
  const path = String(toolSummaryPathInput.value || ".").trim() || ".";
  runToolCommand(`/summary ${quoteToolArg(path)}`);
}

function runCommandPreview() {
  const command = String(toolRunCommandInput.value || "").trim();
  if (!command) {
    addMessage("system", "Enter a terminal command to preview.");
    return;
  }
  runToolCommand(`/run ${command}`);
}

function runCommandExecute() {
  const command = String(toolRunCommandInput.value || "").trim();
  if (!command) {
    addMessage("system", "Enter a terminal command to execute.");
    return;
  }
  runToolCommand(`/run! ${command}`);
}

connectBtn.addEventListener("click", connectWs);
refreshModelsBtn.addEventListener("click", loadModels);
applyModelBtn.addEventListener("click", applyModel);
resetBtn.addEventListener("click", resetConversation);
chatForm.addEventListener("submit", sendPrompt);
if (reviewUploadPickBtn) {
  reviewUploadPickBtn.addEventListener("click", () => {
    reviewUploadInput?.click();
  });
}
if (reviewUploadBtn) {
  reviewUploadBtn.addEventListener("click", () => {
    void uploadSelectedMaterials();
  });
}
if (clearUploadsBtn) {
  clearUploadsBtn.addEventListener("click", () => {
    void clearUploadedMaterials();
  });
}
if (reviewUploadInput) {
  reviewUploadInput.addEventListener("change", () => {
    const count = Number(reviewUploadInput.files?.length || 0);
    setUploadMeta(count > 0 ? `${count} file(s) selected; click Upload.` : "No uploaded files attached.");
  });
}
if (uploadList) {
  uploadList.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement)) {
      return;
    }
    const uploadId = String(target.dataset.uploadId || "").trim();
    if (!uploadId) {
      return;
    }
    void removeUploadedMaterial(uploadId);
  });
}
if (menuToggleBtn) {
  menuToggleBtn.addEventListener("click", toggleDrawer);
}
if (menuCloseBtn) {
  menuCloseBtn.addEventListener("click", closeDrawer);
}
if (drawerOverlay) {
  drawerOverlay.addEventListener("click", closeDrawer);
}
if (toolHelpBtn) {
  toolHelpBtn.addEventListener("click", () => runToolCommand("/tools"));
}
if (toolListBtn) {
  toolListBtn.addEventListener("click", () => runToolCommand("/ls ."));
}
if (toolTreeBtn) {
  toolTreeBtn.addEventListener("click", () => runToolCommand("/tree ."));
}
if (toolFindBtn) {
  toolFindBtn.addEventListener("click", runFindTool);
}
if (toolReadBtn) {
  toolReadBtn.addEventListener("click", runReadTool);
}
if (toolSummaryBtn) {
  toolSummaryBtn.addEventListener("click", runSummaryTool);
}
if (toolRunPreviewBtn) {
  toolRunPreviewBtn.addEventListener("click", runCommandPreview);
}
if (toolRunExecBtn) {
  toolRunExecBtn.addEventListener("click", runCommandExecute);
}
if (devflowStartBtn) {
  devflowStartBtn.addEventListener("click", startDevflowRun);
}
if (devflowStatusBtn) {
  devflowStatusBtn.addEventListener("click", refreshDevflowStatus);
}
if (devflowCancelBtn) {
  devflowCancelBtn.addEventListener("click", cancelDevflowRun);
}
if (devflowApplySlotsBtn) {
  devflowApplySlotsBtn.addEventListener("click", applyDevflowSlots);
}
if (devflowSaveSlotsBtn) {
  devflowSaveSlotsBtn.addEventListener("click", () => saveDevflowRoleSlots({ showMessage: true }));
}
if (pullModelBtn) {
  pullModelBtn.addEventListener("click", () => {
    void startPullModel();
  });
}
if (refreshPullJobBtn) {
  refreshPullJobBtn.addEventListener("click", () => {
    void refreshPullJobStatus();
  });
}
if (deleteModelBtn) {
  deleteModelBtn.addEventListener("click", () => {
    void deleteSelectedModel();
  });
}
if (storeSearchBtn) {
  storeSearchBtn.addEventListener("click", () => {
    void searchStoreApi();
  });
}
if (storeOpenBtn) {
  storeOpenBtn.addEventListener("click", openStoreSearch);
}
if (profileLoadBtn) {
  profileLoadBtn.addEventListener("click", () => {
    void loadProfilePreferences();
  });
}
if (profileApplyBtn) {
  profileApplyBtn.addEventListener("click", () => {
    void applyProfilePreferencesFromForm();
  });
}
if (profileResetBtn) {
  profileResetBtn.addEventListener("click", () => {
    void resetProfilePreferences();
  });
}
if (profileCloseBtn) {
  profileCloseBtn.addEventListener("click", () => {
    closeDrawer();
  });
}
if (profileExportBtn) {
  profileExportBtn.addEventListener("click", exportProfileSettings);
}
if (profileImportBtn) {
  profileImportBtn.addEventListener("click", triggerProfileImportPicker);
}
if (profileImportInput) {
  profileImportInput.addEventListener("change", (event) => {
    void handleProfileImportFile(event);
  });
}

const profilePreviewElements = [
  profileThemeSelect,
  profileDensitySelect,
  profileFontScaleInput,
  profileReducedMotionInput,
  profileHighContrastInput,
  profileLargeTargetsInput,
  profileFocusRingInput,
];
profilePreviewElements
  .filter(Boolean)
  .forEach((element) => {
    const eventName = element === profileFontScaleInput ? "input" : "change";
    element.addEventListener(eventName, () => {
      applyProfilePreferences(profilePayloadFromForm(), { updateControls: false });
    });
  });
if (profileReasoningSelect) {
  profileReasoningSelect.addEventListener("change", () => {
    if (reasoningViewSelect && !reasoningViewSelect.dataset.userChanged) {
      reasoningViewSelect.value = profileReasoningSelect.value;
    }
  });
}
if (adminLoadBtn) {
  adminLoadBtn.addEventListener("click", () => {
    void loadAdminData();
  });
}
if (adminRefreshEventsBtn) {
  adminRefreshEventsBtn.addEventListener("click", () => {
    void loadAdminEvents();
  });
}
if (adminSavePlatformBtn) {
  adminSavePlatformBtn.addEventListener("click", () => {
    void saveAdminPlatform();
  });
}
if (adminCreateUserBtn) {
  adminCreateUserBtn.addEventListener("click", () => {
    void createAdminUser();
  });
}
if (adminCloseBtn) {
  adminCloseBtn.addEventListener("click", () => {
    closeDrawer();
  });
}
if (reasoningViewSelect) {
  reasoningViewSelect.addEventListener("change", () => {
    reasoningViewSelect.dataset.userChanged = "true";
    rerenderReasoningMessages();
  });
}
if (mainDevflowToggle) {
  mainDevflowToggle.addEventListener("change", () => {
    saveMainDevflowTogglePreference();
    syncMainDevflowPanelVisibility();
    setBusy(state.inflight);
    if (mainDevflowToggle.checked) {
      setDevflowMeta("Programming Development Mode enabled for main chat send.");
    }
  });
}
modelFilterInput.addEventListener("input", () => renderModelOptions());
modelSelect.addEventListener("change", () => {
  customModelInput.value = "";
  if (pullModelInput && !pullModelInput.value.trim()) {
    pullModelInput.value = modelSelect.value;
  }
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
  if (event.key !== "Enter") {
    return;
  }
  const sendShortcut = String(
    state.profilePreferences?.chat?.send_shortcut || profileSendShortcutSelect?.value || "enter"
  );
  if (sendShortcut === "ctrl_enter") {
    if (event.ctrlKey || event.metaKey) {
      event.preventDefault();
      chatForm.requestSubmit();
    }
    return;
  }
  if (!event.shiftKey) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

if (toolFindQueryInput) {
  toolFindQueryInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      runFindTool();
    }
  });
}
if (toolReadPathInput) {
  toolReadPathInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      runReadTool();
    }
  });
}
if (toolSummaryPathInput) {
  toolSummaryPathInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      runSummaryTool();
    }
  });
}
if (toolRunCommandInput) {
  toolRunCommandInput.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") {
      return;
    }
    event.preventDefault();
    if (event.shiftKey) {
      runCommandExecute();
      return;
    }
    runCommandPreview();
  });
}
if (pullModelInput) {
  pullModelInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void startPullModel();
    }
  });
}
if (storeQueryInput) {
  storeQueryInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void searchStoreApi();
    }
  });
}
if (devflowPromptInput) {
  devflowPromptInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      startDevflowRun();
    }
  });
}
if (profileActorInput) {
  profileActorInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void loadProfilePreferences();
    }
  });
}
if (adminCreateUsernameInput) {
  adminCreateUsernameInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void createAdminUser();
    }
  });
}

window.addEventListener("beforeunload", () => {
  stopPullPolling();
  closeWs();
});
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && document.body.classList.contains("drawer-open")) {
    closeDrawer();
  }
});

setStatus(false, "offline");
loadMainDevflowTogglePreference();
setBusy(false);
updateActiveModelLabel(state.currentModel);
populateDevflowRoleSelectors();
resetDevflowView();
if (profileActorInput) {
  profileActorInput.value = state.profileLoadedActor;
}
renderUploadList();
loadModels();
loadModelStores();
loadProfilePreferences();
setDrawerOpen(false);
