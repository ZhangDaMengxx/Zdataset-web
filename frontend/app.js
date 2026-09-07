import { escapeHtml, formatBytes, formatDate, formatProgress, QUALITY_LABELS, STATUS_LABELS } from "./format.js";

const $ = (id) => document.getElementById(id);
const state = { roots: [], captures: [], runs: [], selected: null, selectedRun: null, view: "overview", polling: null };
const PIPELINE_STAGES = {
  integrity: ["完整性检查"], ego: ["完整性检查", "EGO 构建", "质量检查"],
  retarget: ["完整性检查", "机器人重定向", "质量检查"], quality: ["质量检查"],
  export: ["完整性检查", "数据导出"],
  full: ["完整性检查", "EGO 构建", "机器人重定向", "质量检查", "数据导出"],
};
const PIPELINE_KEYS = {
  integrity: ["integrity"], ego: ["integrity", "ego", "quality"],
  retarget: ["integrity", "retarget", "quality"], quality: ["quality"],
  export: ["integrity", "export"], full: ["integrity", "ego", "retarget", "quality", "export"],
};
const CATEGORY_LABELS = { acquisition: "采集侧指标", source: "采集侧指标", integrity: "完整性", canonical: "EGO 与精度指标", embodiment: "机器人重定向", precision: "精度指标" };

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  if (!response.ok) {
    let message = `请求失败 (${response.status})`;
    try { message = (await response.json()).detail || message; } catch { /* no JSON body */ }
    throw new Error(message);
  }
  return response.json();
}

function toast(message, error = false) {
  const node = $("toast"); node.textContent = message; node.className = `toast show${error ? " error" : ""}`;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { node.className = "toast"; }, 3000);
}

function status(value) {
  return `<span class="status ${escapeHtml(value)}">${escapeHtml(STATUS_LABELS[value] || value || "未知")}</span>`;
}
function emptyRow(columns, message) { return `<tr class="empty-row"><td colspan="${columns}">${escapeHtml(message)}</td></tr>`; }
function identity(item) { return `<div class="identity-cell" title="${escapeHtml(item.capture_id)}"><strong>${escapeHtml(item.display_name)}</strong><small>${escapeHtml(item.semantic_id)}</small></div>`; }
function qualityMetric(capture, key) { return (capture.quality || []).find((item) => item.key === key) || { state: "not_evaluated", value: "未评估" }; }
function qualityBadge(metric, includeValue = false) {
  const label = includeValue && metric.state !== "not_evaluated" ? metric.value : QUALITY_LABELS[metric.state] || "未评估";
  return `<span class="quality-state ${escapeHtml(metric.state)}">${escapeHtml(label)}</span>`;
}

function filteredCaptures() {
  const query = $("captureSearch").value.trim().toLowerCase(); const filter = $("statusFilter").value;
  return state.captures.filter((capture) => {
    const haystack = `${capture.capture_id} ${capture.semantic_id} ${capture.display_name} ${capture.task_description || ""} ${capture.device || ""}`.toLowerCase();
    return (!query || haystack.includes(query)) && (!filter || capture.status === filter);
  });
}

function renderSummary() {
  const totalBytes = state.captures.reduce((sum, item) => sum + (item.indexed_bytes || 0), 0);
  $("metricTotal").textContent = state.captures.length;
  $("metricProcessing").textContent = state.captures.filter((item) => item.status === "processing").length;
  $("metricFailed").textContent = state.captures.filter((item) => item.status === "failed").length;
  $("metricSize").textContent = totalBytes ? formatBytes(totalBytes) : "--";
  const recent = state.captures.slice(0, 6);
  $("recentRows").innerHTML = recent.length ? recent.map((item) => `<tr data-id="${escapeHtml(item.capture_id)}" data-root="${escapeHtml(item.root_id)}"><td>${identity(item)}</td><td>${escapeHtml(item.device || "--")}</td><td>${item.frame_count ?? "--"}</td><td>${item.ego_available ? "READY" : "--"}</td><td>${status(item.status)}</td></tr>`).join("") : emptyRow(5, "当前目录没有 Capture");
  document.querySelectorAll("#recentRows tr[data-id]").forEach((row) => row.addEventListener("click", () => selectCapture(row.dataset.id, row.dataset.root, "captures")));
  renderActiveRun();
}

function renderCaptures() {
  const captures = filteredCaptures(); $("captureCount").textContent = `${captures.length} 条`;
  $("captureRows").innerHTML = captures.length ? captures.map((item) => {
    const specs = [item.fps ? `${item.fps} Hz` : null, item.source_format].filter(Boolean).join(" · ") || "--";
    const derived = `${item.ego_available ? "EGO" : "无 EGO"}${item.robot_datasets.length ? ` · ${item.robot_datasets.length} Robot` : ""}`;
    const selected = state.selected?.capture_id === item.capture_id && state.selected?.root_id === item.root_id;
    return `<tr data-id="${escapeHtml(item.capture_id)}" data-root="${escapeHtml(item.root_id)}" class="${selected ? "selected" : ""}"><td>${identity(item)}</td><td>${escapeHtml(formatDate(item.created_at))}</td><td>${escapeHtml(item.device || "--")}</td><td>${escapeHtml(specs)}</td><td>${escapeHtml(derived)}</td><td>${status(item.status)}</td></tr>`;
  }).join("") : emptyRow(6, "没有符合条件的 Capture");
  document.querySelectorAll("#captureRows tr[data-id]").forEach((row) => row.addEventListener("click", () => selectCapture(row.dataset.id, row.dataset.root)));
}

async function selectCapture(captureId, rootId, navigate = null) {
  if (navigate) switchView(navigate);
  try {
    state.selected = await api(`/api/v1/captures/${encodeURIComponent(captureId)}?root_id=${encodeURIComponent(rootId)}`);
    $("openRunButton").disabled = false; renderCaptures(); renderInspector();
    if (state.view === "quality") renderQualityDetail();
  } catch (error) { toast(error.message, true); }
}

function renderInspector() {
  const item = state.selected; if (!item) return;
  const stages = Object.entries(item.stages || {}).map(([name, stage]) => `<div><dt>${escapeHtml(name.toUpperCase())}</dt><dd>${escapeHtml(stage.status || "--")}</dd></div>`).join("");
  const capabilities = (item.capabilities || []).map((capability) => `<div><dt>${escapeHtml(capability.key.toUpperCase())}</dt><dd class="${capability.enabled ? "ok" : "bad"}" title="${escapeHtml(capability.reason)}">${capability.enabled ? "可用" : "不可用"}</dd></div>`).join("");
  const warnings = item.manifest_warnings?.length ? `<ul class="warning-list">${item.manifest_warnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join("")}</ul>` : "";
  $("captureInspector").innerHTML = `<div class="inspect-head">${status(item.status)}<h2>${escapeHtml(item.display_name)}</h2><span>${escapeHtml(item.semantic_id)} · ${escapeHtml(item.capture_id)}</span>${item.failure_reason ? `<div class="failure-box">${escapeHtml(item.failure_reason)}</div>` : ""}${warnings}<div class="inspect-actions"><button class="button" id="editMetadataButton">编辑标识</button><button class="button" id="inspectQualityButton">质量详情</button></div></div>
    <section class="inspect-section"><div class="section-title"><h3>基本信息</h3><span>${escapeHtml(item.native_status)}</span></div><dl class="detail-list"><div><dt>任务</dt><dd>${escapeHtml(item.task_description || "未填写")}</dd></div><div><dt>操作者</dt><dd>${escapeHtml(item.operator || "未填写")}</dd></div><div><dt>采集时间</dt><dd>${escapeHtml(formatDate(item.created_at))}</dd></div><div><dt>设备</dt><dd>${escapeHtml(item.device || "--")}</dd></div><div><dt>帧数 / 帧率</dt><dd>${item.frame_count ?? "--"} / ${item.fps ?? "--"} Hz</dd></div><div><dt>源格式</dt><dd>${escapeHtml(item.source_format || "--")}</dd></div><div><dt>索引容量</dt><dd>${escapeHtml(formatBytes(item.indexed_bytes))}</dd></div></dl></section>
    <section class="inspect-section"><div class="section-title"><h3>处理能力</h3><span>PRE-FLIGHT</span></div><dl class="detail-list">${capabilities}</dl></section>
    <section class="inspect-section"><div class="section-title"><h3>Capture 阶段</h3><span>MANIFEST</span></div><dl class="detail-list">${stages || "<div><dt>状态</dt><dd>无阶段信息</dd></div>"}</dl></section>`;
  $("editMetadataButton").addEventListener("click", openMetadataDialog);
  $("inspectQualityButton").addEventListener("click", () => { switchView("quality"); renderQualityDetail(); });
}

function renderRuns() {
  $("runRows").innerHTML = state.runs.length ? state.runs.map((run) => {
    const cancellable = ["queued", "running"].includes(run.status);
    return `<tr data-run-row="${escapeHtml(run.run_id)}"><td class="capture-name">${escapeHtml(run.run_id)}</td><td class="capture-name" title="${escapeHtml(run.capture_id)}">${escapeHtml(run.capture_id)}</td><td>${escapeHtml(run.pipeline)}</td><td>${escapeHtml(run.current_stage || "--")}</td><td><span class="mini-progress"><i style="width:${formatProgress(run.progress)}"></i></span> ${formatProgress(run.progress)}</td><td>${escapeHtml(formatDate(run.started_at || run.created_at))}</td><td>${status(run.status)}</td><td><button class="cancel-button" data-run="${escapeHtml(run.run_id)}" ${cancellable ? "" : "disabled"}>取消</button></td></tr>`;
  }).join("") : emptyRow(8, "尚无处理作业");
  document.querySelectorAll("[data-run-row]").forEach((row) => row.addEventListener("click", () => { state.selectedRun = state.runs.find((item) => item.run_id === row.dataset.runRow); renderRunDetail(); }));
  document.querySelectorAll(".cancel-button[data-run]:not(:disabled)").forEach((button) => button.addEventListener("click", (event) => { event.stopPropagation(); cancelRun(button.dataset.run); }));
  renderActiveRun(); renderRunDetail();
}

function renderActiveRun() {
  const run = state.runs.find((item) => ["queued", "running"].includes(item.status)) || state.runs[0];
  if (!run) { $("activeRun").innerHTML = '<div class="run-empty"><strong>当前没有运行</strong><span>从 Capture 目录启动处理</span></div>'; return; }
  const stages = run.stages.map((stage) => `<div class="stage-row ${escapeHtml(stage.status)}"><i></i><span>${escapeHtml(stage.label)}</span><b>${stage.progress}%</b></div>`).join("");
  $("activeRun").innerHTML = `<div class="active-run"><span class="run-id">${escapeHtml(run.run_id)} · LOCAL</span><h3>${escapeHtml(run.capture_id)}</h3><span>${escapeHtml(run.current_stage || STATUS_LABELS[run.status] || run.status)}</span><div class="progress-track"><div class="progress-bar" style="width:${formatProgress(run.progress)}"></div></div><div class="progress-meta"><span>${formatProgress(run.progress)}</span><span>${escapeHtml(STATUS_LABELS[run.status] || run.status)}</span></div><div class="stage-list">${stages}</div></div>`;
}

function renderRunDetail() {
  const run = state.selectedRun; if (!run) return;
  const artifacts = run.artifacts?.length ? run.artifacts.map((item) => escapeHtml(item)).join("<br>") : "尚无产物";
  $("runDetails").innerHTML = `<div class="run-detail-head">${status(run.status)}<strong>${escapeHtml(run.run_id)} · ${escapeHtml(run.robot_target || "--")}</strong><span>${artifacts}</span></div><pre class="run-log">${escapeHtml((run.logs || []).join("\n"))}</pre>`;
}

function renderQuality() {
  $("qualityRows").innerHTML = state.captures.length ? state.captures.map((item) => `<tr data-quality-id="${escapeHtml(item.capture_id)}" data-root="${escapeHtml(item.root_id)}"><td>${identity(item)}</td><td>${qualityBadge(qualityMetric(item, "source_rgb_resolution"), true)}</td><td>${qualityBadge(qualityMetric(item, "source_depth_resolution"), true)}</td><td>${qualityBadge(qualityMetric(item, "source_rgb_depth_sync"), true)}</td><td>${qualityBadge(qualityMetric(item, "integrity"))}</td><td>${qualityBadge(qualityMetric(item, "detect"), true)}</td></tr>`).join("") : emptyRow(6, "当前目录没有 Capture");
  document.querySelectorAll("[data-quality-id]").forEach((row) => row.addEventListener("click", () => selectCapture(row.dataset.qualityId, row.dataset.root)));
  if (state.selected) renderQualityDetail();
}

function renderQualityDetail() {
  const item = state.selected; if (!item) return;
  const groups = new Map();
  for (const metric of item.quality || []) {
    const category = CATEGORY_LABELS[metric.category] || CATEGORY_LABELS.precision;
    if (!groups.has(category)) groups.set(category, []);
    groups.get(category).push(metric);
  }
  const content = [...groups.entries()].map(([name, metrics]) => `<section class="quality-group"><h3>${escapeHtml(name)}</h3>${metrics.map((metric) => `<div class="metric-detail"><div class="metric-detail-top"><strong>${escapeHtml(metric.label)}</strong>${qualityBadge(metric)}</div><div class="metric-values"><span>实测值<b>${escapeHtml(metric.value)}</b></span><span>门槛<b>${escapeHtml(metric.threshold || "--")}</b></span></div><div class="evidence-list">${(metric.evidence || []).map((evidence) => `<span class="evidence ${evidence.exists ? "exists" : ""}"><i></i><span>${escapeHtml(evidence.path)} · ${escapeHtml(evidence.role)}</span></span>`).join("")}</div>${metric.note ? `<p class="metric-note">${escapeHtml(metric.note)}</p>` : ""}</div>`).join("")}</section>`).join("");
  $("qualityInspector").innerHTML = `<div class="quality-detail-head">${status(item.status)}<h2>${escapeHtml(item.display_name)}</h2><small>${escapeHtml(item.semantic_id)} · ${escapeHtml(item.capture_id)}</small></div>${content || '<div class="empty-state"><strong>没有质量指标</strong></div>'}`;
}

function renderExports() {
  $("exportRows").innerHTML = state.captures.length ? state.captures.map((item) => `<tr data-id="${escapeHtml(item.capture_id)}" data-root="${escapeHtml(item.root_id)}"><td>${identity(item)}</td><td>${item.ego_available ? '<span class="quality-state pass">可用</span>' : '<span class="quality-state not_evaluated">无</span>'}</td><td>${escapeHtml(item.robot_datasets.join(", ") || "无")}</td><td>${escapeHtml(formatBytes(item.indexed_bytes))}</td><td>${status(item.status)}</td></tr>`).join("") : emptyRow(5, "当前目录没有可导出数据");
  document.querySelectorAll("#exportRows tr[data-id]").forEach((row) => row.addEventListener("click", () => selectCapture(row.dataset.id, row.dataset.root, "captures")));
}

function switchView(name) {
  state.view = name;
  if (window.location.hash !== `#${name}`) window.history.replaceState(null, "", `#${name}`);
  document.querySelectorAll(".view").forEach((node) => node.classList.toggle("active", node.id === `view-${name}`));
  document.querySelectorAll(".nav-item").forEach((node) => node.classList.toggle("active", node.dataset.view === name));
  if (name === "quality") renderQuality(); if (name === "exports") renderExports();
}

async function loadRoots() {
  state.roots = await api("/api/v1/roots");
  $("rootSelect").innerHTML = '<option value="all">全部目录</option>' + state.roots.map((root) => `<option value="${escapeHtml(root.id)}">${escapeHtml(root.path)}</option>`).join("");
}

async function refreshCatalog(showToast = false) {
  const rootId = $("rootSelect").value; const suffix = rootId && rootId !== "all" ? `?root_id=${encodeURIComponent(rootId)}` : "";
  state.captures = await api(`/api/v1/captures${suffix}`);
  if (state.selected) {
    const current = state.captures.find((item) => item.capture_id === state.selected.capture_id && item.root_id === state.selected.root_id);
    if (!current) { state.selected = null; $("openRunButton").disabled = true; }
    else { await selectCapture(current.capture_id, current.root_id); }
  }
  $("lastScan").textContent = `更新于 ${new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`;
  renderSummary(); renderCaptures(); renderQuality(); renderExports();
  if (showToast) toast(`已发现 ${state.captures.length} 个 Capture`);
}

async function loadRuns() {
  const hadActive = state.runs.some((run) => ["queued", "running"].includes(run.status));
  state.runs = await api("/api/v1/runs");
  if (state.selectedRun) state.selectedRun = state.runs.find((run) => run.run_id === state.selectedRun.run_id) || null;
  renderRuns();
  const active = state.runs.some((run) => ["queued", "running"].includes(run.status));
  clearTimeout(state.polling);
  if (active) state.polling = setTimeout(() => loadRuns().catch((error) => toast(error.message, true)), 700);
  else if (hadActive) await refreshCatalog();
}

async function scan() {
  $("scanButton").disabled = true;
  try { await api("/api/v1/catalog/scan", { method: "POST" }); await refreshCatalog(true); }
  catch (error) { toast(error.message, true); } finally { $("scanButton").disabled = false; }
}

function openRunDialog() {
  if (!state.selected) return;
  $("runCaptureId").textContent = `${state.selected.display_name} · ${state.selected.semantic_id}`;
  $("robotTarget").value = state.selected.device?.includes("Orbbec") ? "nero_inspire_rgbd" : "nero_inspire_rgb";
  $("retargetRevision").value = ""; renderPipelinePreview(); $("runDialog").showModal();
}

function renderPipelinePreview() {
  const pipeline = $("pipelineSelect").value;
  $("pipelinePreview").innerHTML = PIPELINE_STAGES[pipeline].map((label) => `<span>${escapeHtml(label)}</span>`).join("");
  if (!state.selected) return;
  const capabilities = new Map((state.selected.capabilities || []).map((item) => [item.key, item]));
  const buildsEgo = PIPELINE_KEYS[pipeline].includes("ego") && capabilities.get("ego")?.enabled;
  const blocked = PIPELINE_KEYS[pipeline].filter((key) => !(buildsEgo && ["retarget", "quality", "export"].includes(key))).map((key) => capabilities.get(key)).find((item) => item && !item.enabled);
  const note = $("capabilityNote"); note.classList.toggle("blocked", Boolean(blocked));
  note.textContent = blocked ? `${blocked.key.toUpperCase()}：${blocked.reason}` : "前置条件满足。作业将调用本机固定工具链。";
  $("startRunButton").disabled = Boolean(blocked);
}

async function submitRun(event) {
  event.preventDefault(); if (event.submitter?.value === "cancel") { $("runDialog").close(); return; } if (!state.selected) return;
  $("startRunButton").disabled = true;
  try {
    await api("/api/v1/runs", { method: "POST", body: JSON.stringify({ capture_id: state.selected.capture_id, root_id: state.selected.root_id, pipeline: $("pipelineSelect").value, robot_target: $("robotTarget").value, target_revision: $("targetRevision").value, retarget_revision: $("retargetRevision").value || null }) });
    $("runDialog").close(); switchView("runs"); await loadRuns(); toast("本地处理作业已进入队列");
  } catch (error) { toast(error.message, true); } finally { $("startRunButton").disabled = false; }
}

function openMetadataDialog() {
  const item = state.selected; if (!item) return;
  $("semanticId").value = item.semantic_id; $("displayName").value = item.display_name;
  $("taskDescription").value = item.task_description || ""; $("operatorName").value = item.operator || "";
  $("metadataDialog").showModal();
}

async function submitMetadata(event) {
  event.preventDefault(); if (event.submitter?.value === "cancel") { $("metadataDialog").close(); return; } if (!state.selected) return;
  $("saveMetadataButton").disabled = true;
  try {
    state.selected = await api(`/api/v1/captures/${encodeURIComponent(state.selected.capture_id)}/metadata?root_id=${encodeURIComponent(state.selected.root_id)}`, { method: "PATCH", body: JSON.stringify({ semantic_id: $("semanticId").value.trim(), display_name: $("displayName").value.trim(), task_description: $("taskDescription").value.trim() || null, operator: $("operatorName").value.trim() || null }) });
    $("metadataDialog").close(); await refreshCatalog(); toast("数据标识已保存");
  } catch (error) { toast(error.message, true); } finally { $("saveMetadataButton").disabled = false; }
}

async function cancelRun(runId) {
  try { await api(`/api/v1/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" }); await loadRuns(); toast("已请求取消作业"); }
  catch (error) { toast(error.message, true); }
}

function bindEvents() {
  document.querySelectorAll(".nav-item").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
  document.querySelectorAll("[data-go]").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.go)));
  $("captureSearch").addEventListener("input", renderCaptures); $("statusFilter").addEventListener("change", renderCaptures);
  $("rootSelect").addEventListener("change", () => refreshCatalog().catch((error) => toast(error.message, true)));
  $("scanButton").addEventListener("click", scan); $("openRunButton").addEventListener("click", openRunDialog);
  $("pipelineSelect").addEventListener("change", renderPipelinePreview); $("runForm").addEventListener("submit", submitRun);
  $("metadataForm").addEventListener("submit", submitMetadata);
}

async function init() {
  bindEvents();
  try {
    const health = await api("/api/v1/health"); $("serviceDot").classList.add("online");
    $("serviceLabel").textContent = health.lerobot_runtime ? "服务正常" : "处理环境缺失";
    await loadRoots(); await Promise.all([refreshCatalog(), loadRuns()]);
    const requested = window.location.hash.slice(1);
    if (["overview", "captures", "runs", "quality", "exports"].includes(requested)) switchView(requested);
    if (["captures", "quality"].includes(state.view) && !state.selected && state.captures[0]) {
      await selectCapture(state.captures[0].capture_id, state.captures[0].root_id);
    }
  } catch (error) {
    $("serviceDot").classList.add("error"); $("serviceLabel").textContent = "服务异常"; toast(error.message, true);
    $("recentRows").innerHTML = emptyRow(5, "无法连接本地服务"); $("captureRows").innerHTML = emptyRow(6, "无法连接本地服务");
  }
}

init();
