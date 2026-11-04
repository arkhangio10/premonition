"use strict";
const $ = id => document.getElementById(id);
const JOINTS = {base:"Base",shoulder:"Shoulder",elbow:"Elbow",wrist_pitch:"Wrist pitch",wrist_roll:"Wrist roll",gripper:"Gripper"};
let state = null, busy = false;
let live=false, liveToken=null, liveTimer=null, liveStarted=0, livePolling=false;
let regionMode=null, dragStart=null, draft={file:null,sha256:null,source:null,destination:null};
function rememberDraft() { try { sessionStorage.setItem("premonition-workspace-draft",JSON.stringify(draft)); } catch {} }
function validDraftRegion(r,capture) { return r && [r.x,r.y,r.w,r.h].every(Number.isInteger) && r.x>=0 && r.y>=0 && r.w>=10 && r.h>=10 && r.x+r.w<=capture.width && r.y+r.h<=capture.height; }
function element(tag,text) { const e=document.createElement(tag); e.textContent=text; return e; }
async function api(path, options) {
  const response=await fetch(path,options), body=await response.json();
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Request failed. Check the settings.");
  return body;
}
function controls() {
  $("inspect-arm").disabled=busy; $("refresh-photo").disabled=busy;
  $("live-preview").disabled=busy && !live;
  $("live-preview").textContent=live ? "Pause video" : "Go live";
  $("analyze-scene").disabled=busy || !state?.meta_configured;
  const hasPhoto=!!state?.capture?.file && !live;
  $("mark-source").disabled=$("mark-destination").disabled=busy || !hasPhoto;
  const report=state?.scene_analysis;
  $("select-gripper").disabled=busy || !hasPhoto || !state?.meta_configured || report?.capture.file!==state.capture.file;
  $("use-sponge").disabled=busy || !hasPhoto || report?.capture.file!==state.capture.file || !report.objects.some(o=>o.role==="workpiece");
  $("save-workspace").disabled=busy || live || !draft.source || !draft.destination || !$("workspace-observed").checked;
  $("save-pose").disabled=busy || !state || state.pose_blockers.length>0 || !$("pose-observed").checked || !$("pose-name").value.trim();
}
function photo(capture) {
  if (!capture?.file) return;
  if (state) state.capture=capture;
  if (draft.file!==capture.file || draft.sha256!==capture.sha256) {
    draft={file:capture.file,sha256:capture.sha256,source:null,destination:null};regionMode=null;dragStart=null;
    $("workspace-observed").checked=false;
    const proposal=state?.workspace_proposal;
    if (proposal?.capture.file===capture.file && proposal.capture.sha256===capture.sha256) {
      draft.source=proposal.source;draft.destination=proposal.destination;
    }
    try {
      const remembered=JSON.parse(sessionStorage.getItem("premonition-workspace-draft"));
      if (remembered?.file===capture.file && remembered.sha256===capture.sha256) {
        if (validDraftRegion(remembered.source,capture)) draft.source=remembered.source;
        if (validDraftRegion(remembered.destination,capture)) draft.destination=remembered.destination;
      }
    } catch {}
    const workspace=state?.workspace_regions;
    if (workspace?.capture.file===capture.file && workspace.capture.sha256===capture.sha256) {
      draft.source=workspace.source;draft.destination=workspace.destination;
    }
    rememberDraft();
  }
  $("camera-image").src=`/api/captures/${encodeURIComponent(capture.file)}`;
  if (live) { $("camera-image").hidden=true; scene(state?.scene_analysis,null);drawRegions();return; }
  $("camera-image").hidden=false; $("camera-placeholder").hidden=true;
  const q=capture.quality;
  $("camera-facts").textContent=`${capture.width} × ${capture.height} · ${capture.restored ? "Saved snapshot" : "Snapshot"} · ${(q.saturated*100).toFixed(1)}% saturated pixels`;
  $("camera-guidance").textContent=q.saturated>.2 ? "Exposure is high. Reduce glare and light the work area evenly before calibrating vision." : "Check the framing and focus. Vision thresholds still need calibration.";
  scene(state?.scene_analysis, capture);
  drawRegions();
}
function drawRegions() {
  const overlay=$("regions-overlay"), capture=state?.capture;
  overlay.replaceChildren();overlay.setAttribute("hidden","");
  $("camera-canvas").classList.toggle("marking",!!regionMode);
  $("mark-source").setAttribute("aria-pressed",String(regionMode==="source"));
  $("mark-destination").setAttribute("aria-pressed",String(regionMode==="destination"));
  if (!capture?.file || live) return;
  overlay.setAttribute("viewBox",`0 0 ${capture.width} ${capture.height}`);
  for (const [kind,label,color] of [["source","Pick up","#147e88"],["destination","Place","#e75127"],["gripper","Gripper selection","#666666"]]) {
    const r=draft[kind];if (!r) continue;
    overlay.append(svgElement("rect",{x:r.x,y:r.y,width:r.w,height:r.h,fill:color,"fill-opacity":.08,stroke:color,"stroke-width":3,"stroke-dasharray":"10 5","vector-effect":"non-scaling-stroke"}));
    const ratio=capture.width/Math.max(1,$("camera-image").clientWidth);
    const text=svgElement("text",{x:r.x+8,y:Math.max(14*ratio,r.y-10),fill:color,"font-size":14*ratio,"font-family":"monospace",stroke:"#f3f2ee","stroke-width":3*ratio,"paint-order":"stroke"});
    text.textContent=label;overlay.append(text);overlay.removeAttribute("hidden");
  }
  const saved=state.workspace_regions;
  $("workspace-summary").textContent=saved?.capture.file===capture.file ? "Areas saved · pick and place poses still needed." : draft.source && draft.destination ? "Both areas marked. Check them on the table before saving." : saved ? "Saved areas belong to an earlier photo. Mark this view before changing them." : "Mark the pick-up and destination areas.";
}
function chooseRegion(kind) {
  regionMode=regionMode===kind ? null : kind;
  $("workspace-hint").textContent=regionMode ? `Drag a rectangle on the photo for ${kind==="source" ? "pick-up" : kind==="gripper" ? "the gripper" : "the destination"}.` : "Mark two areas on this photo. Arm positions are taught separately.";
  if(kind==="gripper") {$("calibration-notice").textContent="Drag a rectangle around the gripper in this photo. SAM will outline the selected object.";$("camera-image").scrollIntoView({block:"center"});}
  drawRegions();
}
function imagePoint(event) {
  const rect=$("camera-image").getBoundingClientRect(), capture=state.capture;
  return {x:Math.max(0,Math.min(capture.width,Math.round((event.clientX-rect.left)*capture.width/rect.width))),y:Math.max(0,Math.min(capture.height,Math.round((event.clientY-rect.top)*capture.height/rect.height)))};
}
$("camera-canvas").addEventListener("pointerdown",event=>{
  if (!regionMode || busy || !state?.capture.file) return;
  event.preventDefault();dragStart=imagePoint(event);event.currentTarget.setPointerCapture(event.pointerId);
});
$("camera-canvas").addEventListener("pointermove",event=>{
  if (!dragStart || !regionMode) return;
  const end=imagePoint(event);draft[regionMode]={x:Math.min(dragStart.x,end.x),y:Math.min(dragStart.y,end.y),w:Math.abs(end.x-dragStart.x),h:Math.abs(end.y-dragStart.y)};
  if(regionMode!=="gripper")$("workspace-observed").checked=false;drawRegions();controls();
});
$("camera-canvas").addEventListener("pointerup",()=>{
  if (!dragStart || !regionMode) return;
  const kind=regionMode;
  const region=draft[regionMode];if (!region || region.w<10 || region.h<10) {draft[regionMode]=null;$("workspace-hint").textContent="Draw a larger area on the photo.";}
  dragStart=null;regionMode=null;rememberDraft();drawRegions();controls();
  if(kind==="gripper" && region && region.w>=10 && region.h>=10)action(async()=>{
    $("calibration-notice").textContent="SAM is segmenting the selected gripper…";
    const result=await api("/api/calibration/select-gripper",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({capture_file:state.capture.file,capture_sha256:state.capture.sha256,region})});
    draft.gripper=null;render(result.status);$("calibration-notice").textContent="Selected-region check complete. This is assisted segmentation.";
  });
});
$("camera-canvas").addEventListener("pointercancel",()=>{if(regionMode)draft[regionMode]=null;dragStart=null;regionMode=null;drawRegions();controls();});
function svgElement(tag, attrs) {
  const node=document.createElementNS("http://www.w3.org/2000/svg",tag);
  for (const [key,value] of Object.entries(attrs)) node.setAttribute(key,String(value));
  return node;
}
function scene(report, capture) {
  $("scene-result").hidden=!report; $("scene-empty").hidden=!!report;
  const overlay=$("scene-overlay"); overlay.replaceChildren(); overlay.setAttribute("hidden","");
  $("detection-toggle").hidden=true;
  if (!report) return;
  const current=!live && report.capture.file===capture?.file && report.capture.sha256===capture?.sha256;
  const a=report.understanding;
  $("scene-summary").textContent=a.summary;
  const date=new Intl.DateTimeFormat("en",{timeZone:"America/Lima",dateStyle:"medium",timeStyle:"short"}).format(new Date(report.created_at));
  $("scene-stamp").textContent=`${current ? "This photo" : "Earlier photo"} · ${date} Lima · Gripper detail: ${a.gripper_detail}`;
  const assisted=report.segmentation.some(s=>s.role==="gripper" && s.prompt_type==="box");
  const guided=report.segmentation.some(s=>s.role==="gripper" && s.prompt_type==="model_box" && s.count>0);
  $("scene-next").textContent=(assisted ? "Gripper segmentation uses a selected image region. " : guided ? "Muse located the gripper; SAM outlined it. " : "")+a.next_observation;
  $("scene-objects").replaceChildren(...report.segmentation.map(s=>element("span",`${s.role==="gripper" ? "Gripper" : "Sponge"} · ${s.status==="failed" ? "Unavailable" : s.count===0 ? "Not detected" : `${s.count} ${s.prompt_type==="box" ? "selected" : s.prompt_type==="model_box" ? "model-guided" : "detected"}`}`)));
  const errors=report.segmentation.flatMap(s=>s.status==="failed" ? [s.detail] : s.guidance_error ? [s.guidance_error] : []);
  const assistedNote=(assisted || guided) ? [`Gripper: ${assisted ? "selected-region" : "Muse-guided"} segmentation; the original text-only SAM search found ${report.automatic_gripper_result?.count ?? "unknown"} matches.`] : [];
  $("scene-evidence").replaceChildren(...[...a.observations,...a.limitations,...errors,...assistedNote,"Image coordinates only. Physical positions and routes still need teaching."].map(text=>element("li",text)));
  const cost=(report.api_usage || []).reduce((sum,u)=>sum+(u.usd || 0),0);
  $("scene-cost").textContent=`${report.source} + ${report.segmentation_source} · Estimated API cost: $${cost.toFixed(4)}`;
  $("scene-photo").href=`/api/captures/${encodeURIComponent(report.capture.file)}`;
  if (!current || !report.objects.length) return;
  $("detection-toggle").hidden=false;
  overlay.setAttribute("viewBox",`0 0 ${report.capture.width} ${report.capture.height}`);
  for (const object of report.objects) {
    const color=object.role==="gripper" ? "#147e88" : "#e75127";
    for (const points of object.outlines) overlay.append(svgElement("polygon",{points:points.map(p=>p.join(",")).join(" "),fill:color,"fill-opacity":.18,stroke:color,"stroke-width":2,"vector-effect":"non-scaling-stroke"}));
    const [x1,y1,x2,y2]=object.box_xyxy;
    overlay.append(svgElement("rect",{x:x1,y:y1,width:x2-x1,height:y2-y1,fill:"none",stroke:color,"stroke-width":1.5,"stroke-dasharray":"6 4","vector-effect":"non-scaling-stroke"}));
  }
  overlay.toggleAttribute("hidden",!$("show-detections").checked);
}
function render(data) {
  state=data; const reading=data.controller;
  $("connection-state").textContent=!data.jetson.checked ? "Not checked" : data.jetson.connected ? "Connected" : "Offline";
  $("controller-summary").textContent=!reading ? "Check the arm to read its outputs." : reading.mode1&16 ? "Controller asleep · outputs off" : data.pose_blockers.length ? "Controller needs setup" : "Outputs active · ready to record";
  $("joint-readings").replaceChildren(...Object.entries(JOINTS).map(([key,label])=>{const row=element("tr",""), value=reading?.commanded_us?.[key]; row.append(element("th",label),element("td",!reading ? "Not read" : value===null ? "Off" : reading.prescale!==121 || value===undefined ? "PWM setup needed" : `${value} µs`)); row.firstChild.scope="row"; return row;}));
  $("pose-ready").textContent=data.pose_blockers.length ? "Setup needed" : "Ready to record";
  $("first-move-guidance").textContent=!data.stop_procedure_confirmed ? "Identify how to cut servo power before the first movement." : !reading ? "Check the arm, mark the work areas and record the observation pose." : data.pose_blockers.length ? "The controller needs setup before teaching more positions." : "Mark the pick-up and destination areas. The approach, grasp, lift and place positions still need to be taught.";
  $("pose-guidance").textContent=!reading ? "Check the arm first. A pose records the commanded pulses you have checked on the real arm." : data.pose_blockers.length ? "The outputs are not ready. Establish the initial joint positions before recording a pose." : "Observe the arm, name the pose and confirm its position before recording.";
  $("saved-poses").replaceChildren(...(data.poses.length ? data.poses.map(p=>element("li",p.name)) : [element("li","No poses recorded yet.")]));
  $("reference-poses").replaceChildren(...(data.reference_poses?.poses || []).map(p=>{const row=element("tr",""); row.append(element("th",p.name),...Object.keys(JOINTS).map(j=>element("td",`${p.complete_vector_us[j]} µs`))); row.firstChild.scope="row"; return row;}));
  $("meta-state").textContent=data.meta_verified ? "API access verified" : data.meta_configured ? "Key configured · access unverified" : "API key needed";
  $("meta-setup-command").textContent=data.meta_setup_command;
  $("meta-guidance").textContent=data.meta_verified ? "All three model endpoints passed the API test. Scene calibration is still required." : data.meta_configured ? "The key is configured. Model access must be tested before the Meta pipeline can be used." : "A Meta API key is needed for model calls. Joint calibration works locally.";
  const vision=data.vision_analysis;
  $("vision-result").hidden=!vision;
  if (vision) {
    const a=vision.analysis;
    $("vision-summary").textContent=`Muse Spark · View: ${a.wrist_view_change.replaceAll("_"," ")} · Gripper: ${a.gripper_change.replaceAll("_"," ")}`;
    $("vision-next").textContent=a.next_observation;
    $("vision-limits").replaceChildren(...a.limitations.map(text=>element("li",text)));
    $("vision-frames").replaceChildren(...vision.frames.map(frame=>{
      const link=element("a",frame.label);link.href=`/api/captures/${encodeURIComponent(frame.file)}`;
      link.target="_blank";link.rel="noreferrer";return link;
    }));
  }
  photo(data.capture); controls();
  if (!data.capture?.file) scene(data.scene_analysis,null);
}
async function action(work) {
  if (busy) return; busy=true; controls(); $("calibration-notice").textContent="";
  try { await work(); } catch(error) { $("calibration-notice").textContent=error.message; }
  finally { busy=false; controls(); }
}
async function pausePreview(stopRemote=true) {
  const token=liveToken;live=false;liveToken=null;clearInterval(liveTimer);liveTimer=null;
  $("live-image").removeAttribute("src");$("live-image").hidden=true;
  if (state?.capture?.file) photo(state.capture);else $("camera-placeholder").hidden=false;
  controls();
  if (token && stopRemote) await api("/api/camera/live/stop",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token})});
}
async function pollPreview() {
  if (!live || livePolling) return;
  livePolling=true;const token=liveToken;
  try {
    const status=await api("/api/camera/live/status");
    if (!live || token!==liveToken) return;
    if (status.token===token && status.active) {
      $("camera-facts").textContent=`LIVE · ${status.width} × ${status.height} · ${status.fps} fps`;
      $("camera-guidance").textContent="Watch the movement here. Analyze scene checks a new Full HD photo.";
    } else if ((status.token===token && status.error) || Date.now()-liveStarted>15000) {
      const detail=status.token===token && status.error ? status.error : "Live preview is unavailable. Check the Jetson connection.";
      await pausePreview(false);$("calibration-notice").textContent=detail;
    }
  } catch(error) { if(live && token===liveToken) {await pausePreview(false);$("calibration-notice").textContent=error.message;} }
  finally {livePolling=false;}
}
function startPreview() {
  live=true;liveToken=crypto.randomUUID().replaceAll("-","");liveStarted=Date.now();regionMode=null;dragStart=null;
  $("camera-image").hidden=true;$("camera-placeholder").hidden=true;$("live-image").hidden=false;
  $("live-image").src=`/api/camera/live.mjpg?token=${liveToken}`;
  $("camera-facts").textContent="Connecting live video…";
  scene(state?.scene_analysis,null);drawRegions();controls();
  liveTimer=setInterval(pollPreview,1000);
}
$("live-preview").addEventListener("click",()=>action(async()=>{if(live)await pausePreview();else startPreview();}));
$("live-image").addEventListener("error",()=>{if(live)pausePreview(false).then(()=>{$("calibration-notice").textContent="Live preview stopped. Check the camera and try Go live again.";});});
window.addEventListener("pagehide",()=>{if(liveToken)navigator.sendBeacon("/api/camera/live/stop",new Blob([JSON.stringify({token:liveToken})],{type:"application/json"}));});
$("inspect-arm").addEventListener("click",()=>action(async()=>{try { render(await api("/api/calibration/inspect",{method:"POST"})); } catch(error) { state=null; try { render(await api("/api/calibration")); } catch {} throw error; }}));
$("refresh-photo").addEventListener("click",()=>action(async()=>{if(live)await pausePreview();photo(await api("/api/camera/capture",{method:"POST"}));}));
$("analyze-scene").addEventListener("click",()=>action(async()=>{
  $("analyze-scene").textContent="Analyzing…";
  $("calibration-notice").textContent="Taking a new photo and checking it with Muse Spark + SAM…";
  try { if(live)await pausePreview();const result=await api("/api/calibration/analyze-scene",{method:"POST"});render(result.status);$("calibration-notice").textContent="Scene checked. Detections refer to this photo."; }
  catch(error) { try { render(await api("/api/calibration")); } catch {} throw error; }
  finally { $("analyze-scene").textContent="Analyze scene"; }
}));
$("show-detections").addEventListener("change",()=>scene(state?.scene_analysis,state?.capture));
$("mark-source").addEventListener("click",()=>chooseRegion("source"));
$("mark-destination").addEventListener("click",()=>chooseRegion("destination"));
$("select-gripper").addEventListener("click",()=>chooseRegion("gripper"));
$("use-sponge").addEventListener("click",()=>{
  const object=state.scene_analysis.objects.filter(o=>o.role==="workpiece").sort((a,b)=>b.area_pixels-a.area_pixels)[0];
  const [x,y,x2,y2]=object.box_xyxy;draft.source={x,y,w:x2-x,h:y2-y};$("workspace-observed").checked=false;rememberDraft();drawRegions();controls();
});
$("workspace-observed").addEventListener("change",controls);
window.addEventListener("resize",()=>drawRegions());
$("save-workspace").addEventListener("click",()=>action(async()=>{
  const result=await api("/api/calibration/workspace",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({capture_file:draft.file,capture_sha256:draft.sha256,source:draft.source,destination:draft.destination,operator_observed:$("workspace-observed").checked})});
  render(result.status);$("calibration-notice").textContent="Areas saved. Teach the matching arm positions next.";
}));
$("pose-name").addEventListener("input",controls); $("pose-observed").addEventListener("change",controls);
$("pose-form").addEventListener("submit",event=>{event.preventDefault(); if (!state || $("save-pose").disabled) return; action(async()=>{const result=await api("/api/calibration/poses",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:$("pose-name").value,expected:state.controller.commanded_us,operator_observed:$("pose-observed").checked})}); $("pose-name").value=""; $("pose-observed").checked=false; render(result.status); $("calibration-notice").textContent=`Pose recorded: ${result.pose.name}.`;});});
action(async()=>render(await api("/api/calibration")));
