"use strict";

const $ = (id) => document.getElementById(id);
const DEFAULT_GOAL = "Place A on the left, B in the center, and C on the right.";
const PLACES = {left:"left",center:"center",right:"right",src_a:"source A",src_b:"source B",src_c:"source C"};
const place = (id) => PLACES[id] || id;
const OUTCOME = {pass:"verified",fail:"failed",unknown:"uncertain"};
const MARK = {pass:"✓",fail:"✕",unknown:"?"};
const COMMAND_STATUS = {sent:"sent",completed:"completed",stopped:"stopped",rejected:"rejected",unknown:"unconfirmed",blocked:"blocked"};
const CASES = {
  success:["Complete kit","All three parts reach their targets."],
  grasp_failed:["Grip slips once","The first grip fails; a retry succeeds."],
  grasp_failed_persistent:["Grip keeps failing","The grip fails until the retry limit is reached."],
  wrong_piece:["Wrong part","A different part arrives at the target."],
  missing_piece:["Missing part","A required part is absent before the run."],
  misplaced:["Misplaced part","A part lands outside the position tolerance."],
  dropped:["Dropped part","A part is lost after pickup."],
  occluded_once:["View blocked once","A new observation resolves the blocked view."],
  occluded_persistent:["View stays blocked","The view remains blocked; the demo stops."],
  lost_ack:["Command not confirmed","The command result cannot be confirmed."]
};
const FRAME_ISSUES = {empty_frame:"empty image",undecodable_image:"unreadable image",too_dark:"insufficient light",too_bright:"excessive light",overexposed:"overexposed image",blurred:"blurred image",repeated_image:"repeated image",stale_token:"stale capture",image_hash_mismatch:"image integrity mismatch",wrong_run:"wrong run",wrong_step:"wrong step",wrong_attempt:"wrong attempt",wrong_phase:"wrong phase",wrong_command:"wrong command",region_out_of_frame:"region outside the image",camera_error:"camera unavailable"};
const FAILURE = {operator_stop:"Stopped by operator",motion_disabled:"Motion disabled",motion_unknown:"Motion result unknown",motion_rejected:"Command rejected",motion_stopped:"Motion stopped",unknown_state:"Observation inconclusive",missing_piece:"Required part missing",wrong_piece:"Wrong part detected",misplaced:"Placement outside tolerance",piece_lost:"Part location unknown",grasp_failed:"Grip retry limit reached",precondition_failed:"Precondition not met",ambiguous_state:"Scene needs review",kit_incomplete:"Kit not verified",internal_error:"Run stopped: internal error"};
let current = null, selected = null, pinned = false, statusData = null;
let starting = false, stopping = false, pollGeneration = 0, pollTimer = null;

function setView(name, focus = false) {
  const map = name === "map";
  $("state-map").hidden = !map; $("evidence-view").hidden = map;
  ["map", "evidence"].forEach((view) => {
    const tab = $(`${view}-tab`), active = view === name;
    tab.setAttribute("aria-selected", String(active)); tab.tabIndex = active ? 0 : -1;
  });
  if (focus) $(`${name}-tab`).focus();
  renderViewHint();
  document.dispatchEvent(new CustomEvent("premonition:view", {detail:name}));
}

function renderViewHint() {
  const map = $("map-tab").getAttribute("aria-selected") === "true";
  $("view-hint").textContent = map ? current ? "Select a part to view its results" : "3 parts · 6 actions" : current ? "Select a step to inspect its images" : "Demo results appear here";
}

function renderMethodHelp() {
  const replay = document.querySelector('input[name="mode"]:checked').value === "replay";
  $("method-help").textContent = replay ? "Uses the original recording's check settings." : $("decision-method").value === "A3" ? "Compares measurements with a reference image." : "Checks each action using visual measurements.";
}

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}
function humanError(error) {
  const text = String(error?.message || error || "");
  if (/failed to fetch|networkerror|network request failed/i.test(text)) return "Server unavailable. Check the local connection.";
  if (/camera returned no frame|cannot open camera|no frame|La cámara|cámara falló/i.test(text)) return "Camera unavailable. Check the Jetson connection.";
  if (/ssh:|connection refused|connection timed out|no route to host|could not resolve|permission denied|host key verification/i.test(text)) return "Jetson unavailable. Check USB, power, and SSH access.";
  if (/Especifica una vez cada pieza|no interpreta peticiones/i.test(text)) return "Specify all three targets, e.g. A left, B center, C right.";
  if (/destino diferente|ocupado/i.test(text)) return "Assign a different target to each part.";
  if (/asignación del plan|objetivo debe|todas las piezas/i.test(text)) return "The plan does not match the requested kit.";
  if (/Ya hay una ejecución/i.test(text)) return "A run is already active.";
  if (/MODEL_API_KEY|Meta necesita/i.test(text)) return "Configure a Meta API key to use this option.";
  if (/límite|presupuesto/i.test(text)) return "API budget reached. Review the configured limit.";
  const meta = text.match(/Meta API HTTP (\d+)/);
  if (meta) return ({0:"Meta connection timed out.",401:"Meta API key rejected.",403:"Model access denied.",404:"Model unavailable for this account.",429:"Meta rate limit reached. Try later."})[meta[1]] || "Meta request failed. Try again later.";
  return "Request failed. Review the settings and try again.";
}
function reasonText(reason) {
  const [code, region, piece] = reason.split(":");
  if (code === "frame_rejected") return `Capture rejected: ${FRAME_ISSUES[region] || "new observation required"}.`;
  return ({region_occluded:()=>`${place(region)} is occluded.`,occupancy_ambiguous:()=>`Occupancy at ${place(region)} is unclear.`,identity_ambiguous:()=>`Part identity at ${place(region)} is uncertain.`,region_not_empty:()=>`${place(region)} is still occupied${piece ? ` by ${piece}` : ""}.`,piece_absent:()=>`No part detected at ${place(region)}.`,wrong_identity:()=>`Part ${piece} detected at ${place(region)}.`,out_of_tolerance:()=>`Position at ${place(region)} is outside tolerance.`,reference_mismatch:()=>`${place(region)} does not match the reference.`,reference_missing:()=>"Measurements used; no reference available."})[code]?.() || "Scene requires review.";
}
function notify(error) { $("notice").textContent = error ? humanError(error) : ""; }
async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Request failed");
  return body;
}
function list(id, items, empty) { $(id).replaceChildren(...(items.length ? items.map((text) => node("li", "", text)) : [node("li", "empty-list", empty)])); }
function stepName(step) {
  if (!step) return "No active step";
  return ({inspect_scene:step.scope === "initial" ? "Initial check" : "Final check",pick:`Pick ${step.piece_id}`,place:`Place ${step.piece_id} · ${place(step.destination_id)}`,verify_step:"Verify",stop:"Finish"})[step.action];
}
function image(id, runId, path, empty) {
  const box = $(id);
  const src = path ? `/api/runs/${encodeURIComponent(runId)}/files/${path.split("/").map(encodeURIComponent).join("/")}` : null;
  if (src && box.querySelector("img")?.getAttribute("src") === src) return;
  box.replaceChildren();
  if (src) {
    const img = node("img"); img.src = src;
    img.alt = ({"img-initial":"Scene before the action","img-reference":"Predicted visual reference","img-observed":"New observation after the action"})[id];
    box.append(img);
  } else box.append(node("div", "empty-frame", empty));
}
function latestStep(view) {
  const physical = view.steps.filter((s) => ["pick","place"].includes(s.action));
  const active = view.steps.find((s) => s.step_id === view.current_step);
  if (view.status === "running" && active) return active.target_step_id || active.step_id;
  if (view.status === "stopped") {
    const failed = [...view.steps].reverse().find((s) => s.action !== "verify_step" && ["fail","unknown"].includes(s.outcome));
    if (failed) return failed.step_id;
  }
  return [...physical].reverse().find((s) => Object.keys(s.images).length)?.step_id || view.steps.find((s) => s.outcome)?.step_id || view.steps[0]?.step_id;
}
function selectStep(id) { selected = id; pinned = true; render(current); }
function stepButton(step, view, inspection = false) {
  const button = node("button", inspection ? "inspection-button" : "step-action"); button.type = "button";
  button.setAttribute("aria-current", String(selected === step.step_id));
  if (step.outcome) button.dataset.outcome = step.outcome;
  const active = view.steps.find((s) => s.step_id === view.current_step);
  button.dataset.running = String(view.status === "running" && (active?.target_step_id || active?.step_id) === step.step_id);
  const mark = node("span", "mark", MARK[step.outcome] || "·"); mark.setAttribute("aria-label", OUTCOME[step.outcome] || "pending");
  button.append(mark, node("span", "", inspection ? stepName(step) : step.action === "pick" ? "Pick" : "Place"));
  button.title = `${stepName(step)}: ${OUTCOME[step.outcome] || "pending"}`;
  button.addEventListener("click", () => selectStep(step.step_id)); return button;
}
function renderPlan(view) {
  $("inspections").replaceChildren(...view.steps.filter((s) => s.action === "inspect_scene").map((s) => stepButton(s, view, true)));
  const actions = view.steps.filter((s) => ["pick","place"].includes(s.action));
  $("progress-label").textContent = `${actions.filter((s) => s.outcome === "pass").length} / ${actions.length || 6} verified`;
  if (!actions.length) {
    const placeholder = node("li", "sequence-placeholder");
    ["A","B","C"].forEach((part, index) => { if (index) placeholder.append(node("i")); placeholder.append(node("span", "", `${part} · pending`)); });
    $("plan").replaceChildren(placeholder); return;
  }
  $("plan").replaceChildren(...[...new Set(actions.map((s) => s.piece_id))].map((part) => {
    const row = node("li", "piece-row"); const head = node("div", "piece-row-heading");
    const token = node("span", "piece-token", part); token.dataset.piece = part;
    head.append(token, node("h3", "", `Part ${part}`));
    const buttons = node("div", "piece-actions"); buttons.append(...actions.filter((s) => s.piece_id === part).map((s) => stepButton(s, view)));
    row.append(head, buttons); return row;
  }));
}
function renderStep(view) {
  const step = view.steps.find((s) => s.step_id === selected); const images = step?.images || {};
  const inspection = step?.action === "inspect_scene";
  $("step-label").textContent = stepName(step);
  image("img-initial", view.run_id, images.initial, inspection ? "Inspection only" : "No frame");
  image("img-reference", view.run_id, images.reference, inspection ? "Not required" : "Not generated");
  image("img-observed", view.run_id, images.observed, "Awaiting observation");
  $("step-details").hidden = !step?.outcome; $("detail").hidden = !step?.outcome;
  if (!step?.outcome) return;
  const key = `${view.run_id}:${step.step_id}:${step.attempts}:${step.outcome}`;
  if ($("step-details").dataset.step !== key) {
    $("step-details").open = ["fail","unknown"].includes(step.outcome);
    $("step-details").dataset.step = key;
  }
  const detail = $("detail"); detail.dataset.outcome = step.outcome;
  detail.replaceChildren(node("strong", "", `${stepName(step)}: ${OUTCOME[step.outcome]}.`));
  if (step.attempts > 1) detail.append(node("span", "", ` Attempt ${step.attempts}.`));
  if (step.a2) detail.append(node("span", "", ` Measurements: ${OUTCOME[step.a2]}. With reference: ${OUTCOME[step.a3]}.`));
  if (step.reasons.length) { const reasons = node("ul"); reasons.append(...step.reasons.map((r) => node("li", "", reasonText(r)))); detail.append(reasons); }
}
function renderControls() {
  const running = current?.status === "running", busy = starting || running;
  const replay = document.querySelector('input[name="mode"]:checked').value === "replay";
  ["run", "start-from-results"].forEach((id) => {
    $(id).disabled = !statusData || busy;
    $(id).querySelector("span").textContent = starting ? "Starting…" : running ? current.mode === "replay" ? "Playing…" : "Running…" : replay ? "Play demo" : "Start demo";
  });
  $("stop").disabled = !running || current.mode === "replay" || stopping;
  $("cases").disabled = busy; $("request").disabled = busy;
  document.querySelectorAll('input[name="mode"]').forEach((input) => { input.disabled = busy; });
  $("decision-method").disabled = busy || replay; $("use-meta").disabled = busy || replay || !statusData?.meta.configured;
}
function render(view) {
  current = view; if (view.status !== "running") stopping = false;
  $("results-empty").hidden = true; $("results-content").hidden = false; renderViewHint();
  $("scene-description").textContent = view.status === "running" ? "Demo running. Follow the step results." : view.status === "completed" ? "Kit verified. Select a part to review its steps." : "Demo stopped. Review the step results.";
  $("session-state").dataset.status = view.status;
  $("session-state").replaceChildren(node("i"), document.createTextNode(({running:"Running",completed:"Complete",stopped:"Stopped"})[view.status] || "Idle"));
  $("verdict").dataset.tone = view.status; $("feedback-indicator").dataset.tone = view.status;
  $("verdict").textContent = view.status === "running" ? "Verifying each action" : view.status === "completed" ? "Kit verified" : FAILURE[view.failure_class] || "Run stopped";
  $("observation-source").textContent = view.mode === "replay" ? "RECORDED" : view.synthetic ? "SIMULATED" : "CAMERA";
  const provider = (source) => source === "fixture_simulado" ? "Local demo" : source?.startsWith("muse-") ? "Meta" : "Recorded";
  $("provenance").textContent = `${provider(view.planner_source)} planner · ${provider(view.reference_source)} reference · ${view.decision_method || "A2"}`;
  if (view.reference_failures.length) $("notice").textContent = `Reference unavailable. Using measurements. ${humanError(view.reference_failures[0])}`;
  if (!pinned || !view.steps.some((s) => s.step_id === selected)) selected = latestStep(view);
  renderPlan(view); renderStep(view);
  const state = view.state;
  list("requested", Object.entries(state.requested).map(([part, target]) => `${part} → ${place(target)}`), "No goal yet.");
  list("observed", Object.entries(state.observed).map(([zone, part]) => `${place(zone)}: ${part || "empty"}`), "No observations.");
  list("commanded", state.commanded.map((c) => `${c.action === "pick" ? "Pick" : "Place"} ${c.piece_id}: ${COMMAND_STATUS[c.status] || "unconfirmed"}`), "No commands.");
  list("uncertainty", [...new Set(state.uncertainty)].map((text) => {
    const match = text.match(/^s(\d+) intento (\d+): (.*)$/);
    if (match) return `Step ${match[1]}, attempt ${match[2]}: ${reasonText(match[3])}`;
    if (/el origen quedó vacío/i.test(text)) return `${text.split(":")[0]}: source empty; grip not directly measured.`;
    return "Scene requires review.";
  }), "None recorded.");
  renderControls();
  document.dispatchEvent(new CustomEvent("premonition:state", {detail:view}));
}
async function poll(runId) {
  clearTimeout(pollTimer); const generation = ++pollGeneration;
  const tick = async () => {
    try {
      const view = await api(`/api/runs/${encodeURIComponent(runId)}`);
      if (generation !== pollGeneration) return;
      render(view);
      if (view.status === "running") pollTimer = setTimeout(() => { tick().catch(() => {}); }, 350);
    } catch (error) { if (generation !== pollGeneration) return; notify(error); throw error; }
  };
  await tick();
}
function renderConnections(status) {
  const jetson = status.jetson;
  $("jetson").textContent = !jetson.checked ? "Not checked" : jetson.connected ? "Connected" : "Offline";
  $("jetson").title = jetson.connected ? `${jetson.hostname} · ${jetson.latency_ms} ms` : "Check the Jetson connection";
  $("meta").textContent = status.meta.configured ? "Key configured" : "Local demo";
  $("meta-tag").textContent = status.meta.configured ? "Access unverified" : "No API key";
  const replay = document.querySelector('input[name="mode"]:checked').value === "replay";
  $("use-meta").disabled = !status.meta.configured || replay;
  if ($("use-meta").disabled) $("use-meta").checked = false;
  $("meta-help").textContent = replay ? "Replay makes no API calls." : status.meta.configured ? "Uses the configured API budget." : "Configure an API key to enable.";
  $("decision-method").disabled = replay; $("request").readOnly = replay;
  renderMethodHelp();
  $("mode-title").textContent = replay ? "Recording" : "Simulation";
  $("case-label").textContent = replay ? "Recording" : "Test case";
  $("scene-description").textContent = replay ? "Choose a recording, then select Play demo." : "Choose a test case, then select Start demo.";
  $("tape").textContent = "Motion off";
  renderControls();
}
function renderCases(status) {
  $("cases").replaceChildren(...status.scenarios.map((scenario) => { const option = node("option", "", CASES[scenario.name]?.[0] || "Demo scenario"); option.value = scenario.name; return option; }));
  renderCaseDescription();
}
function renderCaseDescription() { $("case-description").textContent = CASES[$("cases").value]?.[1] || ""; }
function renderComparison(report) {
  const wrapper = node("div", "compare"), table = node("table"), head = node("thead"), header = node("tr");
  ["Metric","Measurements","With reference"].forEach((text) => { const th = node("th", "", text); th.scope = "col"; header.append(th); }); head.append(header); table.append(head);
  const body = node("tbody");
  [["Accepted failures / real failures","failures_accepted"],["Rejected correct / correct trials","correct_rejected"],["Uncertain / trials","abstentions"],["Failures / acceptances","failures_accepted_share_of_acceptances"]].forEach(([label,key]) => { const row = node("tr"), th = node("th", "", label); th.scope = "row"; row.append(th); ["A2","A3"].forEach((method) => { const ratio = report.methods[method][key]; row.append(node("td", "", `${ratio.num} / ${ratio.den}`)); }); body.append(row); });
  table.append(body); wrapper.append(table); const output = [wrapper];
  if (report.warning) output.push(node("p", "warning", "Synthetic data. Not evidence of real-world performance."));
  output.push(node("p", "evaluation-facts", `${report.kits.completed} / ${report.kits.attempted} kits completed · ${report.composition.trials_with_reference} reference trials`));
  $("compare-result").replaceChildren(...output);
}
function renderPhoto(capture) {
  if (!capture.file) return;
  $("photo-box").hidden = false; $("photo-box").open = true;
  const img = node("img"); img.src = `/api/captures/${encodeURIComponent(capture.file)}`; img.alt = "Real camera snapshot from Jetson Nano";
  const q = capture.quality;
  $("photo").replaceChildren(img, node("p", "", `${capture.width} × ${capture.height} · brightness ${q.brightness.toFixed(1)} · saturation ${(q.saturated * 100).toFixed(1)}% · sharpness ${q.sharpness.toFixed(1)} · uncalibrated`));
}

$("form").addEventListener("submit", async (event) => {
  event.preventDefault(); if (starting || current?.status === "running") return;
  const form = new FormData($("form")); notify(""); starting = true; pinned = false; renderControls();
  try {
    const {run_id} = await api("/api/runs", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({scenario:form.get("scenario"),mode:form.get("mode"),request_text:$("request").value,use_meta:$("use-meta").checked,decision_method:$("decision-method").value})});
    $("config-box").open = false; setView("evidence"); history.replaceState(null, "", `?run=${encodeURIComponent(run_id)}`); await poll(run_id);
  } catch (error) { notify(error); }
  finally { starting = false; renderControls(); }
});
$("stop").addEventListener("click", async () => { if (!current) return; stopping = true; renderControls(); try { await api(`/api/runs/${encodeURIComponent(current.run_id)}/stop`, {method:"POST"}); } catch (error) { stopping = false; notify(error); renderControls(); } });
document.querySelectorAll('input[name="mode"]').forEach((input) => input.addEventListener("change", () => { if (statusData) renderConnections(statusData); }));
$("cases").addEventListener("change", renderCaseDescription);
$("decision-method").addEventListener("change", renderMethodHelp);
["map", "evidence"].forEach((name) => {
  $(`${name}-tab`).addEventListener("click", () => setView(name));
  $(`${name}-tab`).addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault(); setView(event.key === "Home" ? "map" : event.key === "End" ? "evidence" : name === "map" ? "evidence" : "map", true);
  });
});
document.addEventListener("premonition:inspect", (event) => {
  const actions = current?.steps.filter((step) => step.piece_id === event.detail && ["pick", "place"].includes(step.action)) || [];
  if (!actions.length) { setView("evidence", true); return; }
  const active = current.steps.find((step) => step.step_id === current.current_step);
  const step = actions.find((step) => step.step_id === (active?.target_step_id || active?.step_id)) || [...actions].reverse().find((step) => step.outcome) || actions[0];
  selectStep(step.step_id); setView("evidence"); $("evidence-tab").focus();
});
$("evaluation-link").addEventListener("click", () => { $("compare-box").open = true; });
document.addEventListener("pointerdown", (event) => { if (!$("config-box").contains(event.target)) $("config-box").open = false; });
document.addEventListener("keydown", (event) => { if (event.key === "Escape" && $("config-box").open) { $("config-box").open = false; $("config-box").querySelector("summary").focus(); } });
$("check").addEventListener("click", async () => { $("check").disabled = true; notify(""); try { statusData.jetson = await api("/api/jetson/check", {method:"POST"}); renderConnections(statusData); if (!statusData.jetson.connected) notify(statusData.jetson.detail); } catch (error) { notify(error); } finally { $("check").disabled = false; } });
$("capture").addEventListener("click", async () => { $("capture").disabled = true; notify(""); try { renderPhoto(await api("/api/camera/capture", {method:"POST"})); $("photo-box").scrollIntoView({block:"nearest"}); } catch (error) { notify(error); } finally { $("capture").disabled = false; } });
$("compare").addEventListener("click", async () => { $("compare").disabled = true; $("compare").textContent = "Comparing…"; notify(""); try { renderComparison(await api("/api/evaluation", {method:"POST"})); } catch (error) { notify(error); } finally { $("compare").disabled = false; $("compare").textContent = "Run comparison"; } });
async function init() {
  renderPlan({steps:[]}); image("img-initial", "", null, "No frame"); image("img-reference", "", null, "Not generated"); image("img-observed", "", null, "Awaiting observation");
  try {
    statusData = await api("/api/status"); $("request").value = DEFAULT_GOAL;
    renderCases(statusData); renderConnections(statusData); renderPhoto(statusData.capture); renderControls();
    const runId = new URLSearchParams(location.search).get("run");
    if (runId) { setView("evidence"); await poll(runId).catch(() => { $("notice").textContent = "Run unavailable in this session. Start a new run."; }); }
  } catch (error) { notify(error); }
}
init();
