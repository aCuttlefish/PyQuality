"use strict";
const $ = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
const json = value => JSON.stringify(value, null, 2);
const labels = {
  FAIL:"未通过", PASS_WITHIN_SCOPE:"本轮检查通过", INCONCLUSIVE:"暂无法判定", UNKNOWN:"未判定",
  PASSED:"通过", ASSERTION_FAILED:"失败", TARGET_EXCEPTION:"目标异常", ENV_ERROR:"环境错误",
  HARNESS_ERROR:"检查器错误", TIMEOUT:"超时", NOT_RUN:"未执行", SKIPPED:"已跳过",
  COVERED:"已体现", COVERED_BY_CONTEXT:"上下文已包含", CONFLICT:"与需求冲突",
  MISSING_FROM_VISIBLE_PROMPT:"可见提示词未体现", AMBIGUOUS:"表述有歧义",
  NOT_USABLE:"当前实现不可用", USABLE_WITH_ADVICE:"范围内可用，建议改进",
  USABLE_WITHIN_SCOPE:"在本轮检查范围内可用", REVIEW_REQUIRED:"需要人工审查", UNDETERMINED:"证据不足，继续确认",
  CORRECTNESS_FIX:"功能修正", POTENTIAL_RISK:"潜在风险", READABILITY:"可读性", PERFORMANCE:"性能",
};
let draft = null, confirmed = null, lastReport = null, demos = [], activeDemo = null, busy = false, advancedDirty = false;
const STORAGE = "pyquality.acceptance.v5";
function notice(text, error = false) {
  $("message").textContent = text;
  $("message").classList.toggle("error", error);
  $("message").hidden = !text;
}
function inputPayload() {
  const body = {requirement:$("reqText").value.trim(), generation_prompt:$("promptText").value.trim(), code:$("codeText").value};
  if ($("entryText").value.trim()) body.entrypoint = {module:"solution", callable:$("entryText").value.trim()};
  return body;
}
function save() {
  try { localStorage.setItem(STORAGE, JSON.stringify({input:inputPayload(), draft, confirmed, demo:activeDemo?.id})); }
  catch (_) {}
}
function updateButtons() {
  $("evalBtn").disabled = busy || !confirmed;
  $("confirmBtn").disabled = busy || !$("confirmCheck").checked || !draft;
  $("correctDemo").hidden = !activeDemo;
}
function invalidateStandard(message = "标准已编辑，请重新核对并确认。") {
  confirmed = null; $("confirmCheck").checked = false;
  $("standardStatus").textContent = message; updateButtons(); save();
}
function runTask(task) {
  if (busy) return;
  busy = true;
  const controls = [...document.querySelectorAll("button,input,textarea,select")];
  const disabled = controls.map(el => el.disabled);
  controls.forEach(el => el.disabled = true);
  Promise.resolve().then(task).catch(e => notice(e.message, true)).finally(() => {
    controls.forEach((el, i) => el.disabled = disabled[i]);
    busy = false; updateButtons();
  });
}
async function api(path, body) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 180000);
  try {
    const response = await fetch("/api/acceptance/" + path, {
      method:body === undefined ? "GET" : "POST", headers:{"Content-Type":"application/json"},
      body:body === undefined ? undefined : JSON.stringify(body), signal:controller.signal,
    });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : JSON.stringify(result.detail || result));
    return result;
  } catch (e) {
    if (e.name === "AbortError") throw new Error("请求超时，请检查模型与执行环境后重试。");
    throw e;
  } finally { clearTimeout(timeout); }
}
async function refreshEnvironment() {
  $("envStatus").textContent = "正在检查运行环境…";
  try {
    const env = await api("environment");
    const model = env.model_configured ? "模型已配置（调用时验证连接）" : "模型未配置";
    const execution = env.execution_backend === "HOST_SUBPROCESS_DEV" ? "本地可信演示" :
      env.ready_for_execution ? "Docker 隔离执行已就绪" :
      env.execution_available ? "Docker 镜像待准备" : "动态执行未就绪";
    $("envStatus").textContent = model + " · " + execution;
    $("envActions").innerHTML = env.actions.map(a => `<li>${esc(a)}</li>`).join("");
  } catch(e) { $("envStatus").textContent = "环境检查失败：" + e.message; }
}
function manualDraft() {
  const payload = inputPayload();
  if (!payload.requirement) throw new Error("请先填写功能需求。");
  return {
    requirement:payload.requirement, entrypoint:payload.entrypoint || null,
    spec:{spec_id:"SPEC-DRAFT", requirements:[{
      id:"R1", statement:payload.requirement, mandatory:true, origin:"EXPLICIT",
      kind:"FUNCTIONAL", source_quote:payload.requirement, unresolved_questions:[],
      acceptance_intent:"用户确认的固定案例验收",
    }], input_domain:[], technical_constraints:[], unresolved_questions:[]},
    plan:{contracts:[{contract_id:"K_R1", requirement_ids:["R1"], description:"固定输入输出案例",
      relation_to_requirement:"EQUIVALENT", relation_basis:"用户确认固定输入输出，结论仅覆盖声明的案例范围",
      oracle_origin:"MODEL_HYPOTHESIS"}], cases:[]},
    issues:[], scope_note:"本轮仅验证已确认的固定测试案例；不保证未测试输入与输入域外行为。",
  };
}
function expectationValue(a) {
  if (a.kind === "RETURN_EQUALS") return json(a.expected);
  if (a.kind === "RETURN_IS_NONE") return "null";
  if (a.kind === "RETURN_TYPE") return a.expected_type;
  if (a.kind === "RAISES") return a.exception_type;
  return json(a);
}
const checkOptions = [["RETURN_EQUALS","返回值等于"], ["RETURN_IS_NONE","返回 None"], ["RAISES","抛出异常"], ["RETURN_TYPE","返回值类型"], ["ADVANCED","其他检查（JSON）"]];
function renderDraft() {
  $("standardArea").hidden = !draft;
  if (!draft) return;
  if (!confirmed) $("standardStatus").textContent = `标准草案 · ${draft.plan.cases.length} 个案例 · 核对后确认`;
  $("reviewIssues").hidden = !draft.issues?.length;
  $("reviewIssues").textContent = (draft.issues || []).join("\n");
  $("requirementsList").innerHTML = draft.spec.requirements.map(r =>
    `<div class="requirement"><strong>${esc(r.id)} · ${r.mandatory === false ? "可选" : "必要"}</strong> ${esc(r.statement)}
     <small>依据：${esc(r.source_quote || r.derivation_basis || "待澄清")}</small></div>`).join("");
  $("casesBody").innerHTML = draft.plan.cases.map((c, index) => {
    const kind = checkOptions.some(([k]) => k === c.assertion.kind) ? c.assertion.kind : "ADVANCED";
    return `<tr data-index="${index}"><td><span class="case-id">${esc(c.case_id)}</span>
      <input class="rids" aria-label="${esc(c.case_id)} 需求编号" value="${esc(c.requirement_ids.join(","))}"></td>
      <td><textarea class="args" rows="3" aria-label="${esc(c.case_id)} 输入">${esc(json(c.args))}</textarea></td>
      <td><select class="kind" aria-label="${esc(c.case_id)} 检查类型">${checkOptions.map(([k,l]) => `<option value="${k}" ${kind === k ? "selected" : ""}>${l}</option>`).join("")}</select>
      <textarea class="expected" rows="2" aria-label="${esc(c.case_id)} 期望结果">${esc(expectationValue(c.assertion))}</textarea></td>
      <td><button class="btn ghost sm remove" aria-label="删除 ${esc(c.case_id)}">删除</button></td></tr>`;
  }).join("");
  for (const tr of $("casesBody").querySelectorAll("tr")) {
    tr.querySelector(".remove").addEventListener("click", () => {
      try { readCases(); draft.plan.cases.splice(Number(tr.dataset.index), 1); invalidateStandard(); renderDraft(); }
      catch(e) { notice(e.message, true); }
    });
    tr.querySelector(".kind").addEventListener("change", () => {
      const defaults = {RETURN_EQUALS:"null",RETURN_IS_NONE:"null",RAISES:"ValueError",RETURN_TYPE:"int",ADVANCED:'{"kind":"INPUT_UNCHANGED","targets":[{"kind":"ARG","index":0}]}'};
      tr.querySelector(".expected").value = defaults[tr.querySelector(".kind").value];
      invalidateStandard();
    });
    tr.addEventListener("input", () => {
      invalidateStandard();
      try { readCases(); if (!advancedDirty) syncEditors(); save(); } catch (_) {}
    });
  }
  $("scopeText").value = draft.scope_note;
  syncEditors(); $("confirmCheck").checked = false; updateButtons();
}
function syncEditors() {
  $("specEditor").value = json(draft.spec); $("planEditor").value = json(draft.plan); advancedDirty = false;
}
function readCases() {
  draft.plan.cases = [...$("casesBody").querySelectorAll("tr")].map((tr, i) => {
    const old = draft.plan.cases[i], value = tr.querySelector(".expected").value, kind = tr.querySelector(".kind").value;
    try {
      const args = JSON.parse(tr.querySelector(".args").value);
      if (!Array.isArray(args)) throw new Error("位置参数需要 JSON 数组，例如 [1, 2] 或 [[1, 2]]");
      let assertion;
      if (kind === "RETURN_EQUALS") assertion = {kind, expected:JSON.parse(value)};
      else if (kind === "RETURN_IS_NONE") assertion = {kind};
      else if (kind === "RAISES") assertion = {kind, exception_type:value.trim(), message_contains:old.assertion.message_contains || ""};
      else if (kind === "RETURN_TYPE") assertion = {kind, expected_type:value.trim()};
      else assertion = JSON.parse(value);
      return {...old, args, assertion, requirement_ids:tr.querySelector(".rids").value.split(",").map(s=>s.trim()).filter(Boolean)};
    } catch(e) { throw new Error(`${old.case_id}：${e.message}`); }
  });
  draft.scope_note = $("scopeText").value.trim();
}
function appendCase() {
  if (!draft) return;
  readCases();
  const ids = new Set(draft.plan.cases.map(c=>c.case_id));
  let n = draft.plan.cases.length + 1;
  while (ids.has("U" + n)) n++;
  const contract = draft.plan.contracts[0];
  if (!contract) throw new Error("请在完整计划中先填写至少一个契约。");
  draft.plan.cases.push({case_id:"U"+n, contract_id:contract.contract_id,
    requirement_ids:contract.requirement_ids, args:[], kwargs:{}, category:"USER_EXAMPLE",
    assertion:{kind:"RETURN_EQUALS",expected:null}, expected_basis:"用户对照需求确认的期望值", input_domain_status:"IN_SCOPE"});
  invalidateStandard(); renderDraft();
}
$("prepareBtn").addEventListener("click", () => runTask(async () => {
  notice("正在提取需求并审查测试计划，请稍候…");
  draft = await api("prepare", inputPayload()); confirmed = null;
  if (draft.entrypoint) $("entryText").value = draft.entrypoint.callable;
  renderDraft(); save(); notice("标准已生成。请核对需求、输入与期望，再确认标准。");
}));
$("manualBtn").addEventListener("click", () => {
  try { draft = manualDraft(); confirmed = null; renderDraft(); appendCase(); notice("请填写测试输入和期望结果，并指定待测函数名。"); }
  catch(e) { notice(e.message, true); }
});
$("addCase").addEventListener("click", () => { try { appendCase(); } catch(e) { notice(e.message, true); } });
$("applyAdvanced").addEventListener("click", () => {
  try {
    const spec = JSON.parse($("specEditor").value), plan = JSON.parse($("planEditor").value);
    if (!Array.isArray(spec.requirements) || !Array.isArray(plan.contracts) || !Array.isArray(plan.cases)) throw new Error("需要 requirements、contracts、cases 数组。");
    draft.spec = spec; draft.plan = plan; draft.issues = [];
    invalidateStandard(); renderDraft(); notice("修改已应用，请重新核对并确认。");
  } catch(e) { notice(e.message, true); }
});
$("confirmCheck").addEventListener("change", updateButtons);
$("scopeText").addEventListener("input", () => invalidateStandard());
for (const id of ["specEditor","planEditor"]) $(id).addEventListener("input", () => {
  advancedDirty = true; invalidateStandard("完整标准有未应用的编辑，请先点击「应用编辑」。");
});
$("confirmBtn").addEventListener("click", () => runTask(async () => {
  if (advancedDirty) throw new Error("请先应用完整标准编辑。");
  readCases();
  const name = $("entryText").value.trim() || draft.entrypoint?.callable;
  if (!name) throw new Error("请填写待测函数名。");
  notice("正在保存本轮确认标准…");
  confirmed = await api("confirm", {requirement:$("reqText").value.trim(), entrypoint:{module:"solution",callable:name},
    spec:draft.spec, plan:draft.plan, scope_note:draft.scope_note, confirmed:true, case_scope_confirmed:true});
  draft.spec = confirmed.spec; draft.plan = confirmed.plan;
  renderDraft(); $("confirmCheck").checked = true;
  $("entryText").value = name;
  $("standardStatus").textContent = `标准已确认 · ${draft.plan.cases.length} 个案例 · 修改代码后可直接复评`;
  syncEditors(); save(); notice("标准已确认。点击「开始验收」运行代码。");
}));
for (const id of ["reqText","entryText"]) $(id).addEventListener("input", () => {
  invalidateStandard("需求或函数入口已改变，请重新生成或修订标准并确认。");
  if (draft && id === "reqText") { draft = null; renderDraft(); save(); }
});
for (const id of ["codeText","promptText"]) $(id).addEventListener("input", () => {
  $("runHint").textContent = confirmed ? "输入已修改，可复用当前标准重新验收。下方报告仍为上次输入的结果。" : "请先确认验收标准。"; save();
});
$("evalBtn").addEventListener("click", () => runTask(async () => {
  notice("正在执行固定案例、分析代码质量并生成建议…");
  const previous = lastReport;
  const data = await api("evaluate", {...inputPayload(), acceptance_materials:{
    confirmed_spec_id:confirmed.confirmed_spec_id, confirmed_spec_hash:confirmed.confirmed_spec_hash,
  }, options:{oracle_policy:"confirmed_only"}});
  lastReport = data.report; renderReport(lastReport, previous);
  notice("验收已完成。修改代码或提示词后，可以复用同一标准再次验收。");
  $("reportArea").scrollIntoView({behavior:"smooth",block:"start"});
}));
function renderReport(r, previous) {
  const cov = r.coverage, q = r.quality_report, pr = r.prompt_report;
  const cases = new Map((r.test_plan?.cases || []).map(c=>[c.case_id,c]));
  const execution = r.evidence.filter(e=>e.kind === "EXECUTED_CASE");
  const ratio = cov.cases_executed ? (100 * cov.cases_passed / cov.cases_executed).toFixed(1) + "%" : "未执行";
  const compare = previous && previous.reproducibility.plan_hash === r.reproducibility.plan_hash ?
    `<p class="comparison">相同验收标准：上次 ${esc(labels[previous.code_verdict])}（${previous.coverage.cases_passed}/${previous.coverage.cases_planned}） → 本次 ${esc(labels[r.code_verdict])}（${cov.cases_passed}/${cov.cases_planned}）</p>` : "";
  let html = `<section class="card"><div class="report-title"><h3>验收结果</h3><button id="downloadReport" class="btn ghost sm">下载完整报告</button></div>
    <span class="badge status-${esc(r.usability)}">${esc(labels[r.usability])}</span><span class="muted">${esc(labels[r.code_verdict])} · ${esc(r.isolation_level)}</span>
    <p>${esc(r.summary)}</p>${compare}
    <div class="metrics"><div class="metric"><strong>${cov.cases_passed} / ${cov.cases_planned}</strong><span>通过 / 计划案例</span></div>
    <div class="metric"><strong>${ratio}</strong><span>已执行案例通过比例</span></div><div class="metric"><strong>${q.readability_score}</strong><span>静态可读性评分 · ${esc(q.readability_grade)}</span></div></div>
    <p class="hint">判定标准：认可范围内的一条有效反例即失败；必要需求的认可检查全部执行且通过，才判本轮通过；证据不完整时保留无法判定。测试比例只用于展示。</p>`;
  html += r.requirement_results.map(rr=>`<div class="requirement"><strong class="status-${esc(rr.status)}">${esc(rr.requirement_id)} · ${esc(labels[rr.status])}</strong> ${esc(rr.statement)}
    <small>${esc(rr.explanation || rr.uncovered_scope)} ${esc(rr.code_location)}</small></div>`).join("");
  if (r.blockers.length) html += `<div class="notice">${esc(r.blockers.join("\n"))}</div>`;
  html += `<ul class="muted">${r.next_actions.map(a=>`<li>${esc(a)}</li>`).join("")}</ul></section>`;
  html += `<section class="card"><h3>测试输入、期望与实际结果</h3><div class="table-scroll"><table><thead><tr><th>案例 / 需求</th><th>输入</th><th>预期检查</th><th>实际观察</th><th>结果</th></tr></thead><tbody>`;
  for (const e of execution) {
    const c = cases.get(e.case_id);
    html += `<tr><td>${esc(e.case_id)}<br>${esc(e.requirement_ids.join(", "))}</td><td>${esc(json({args:c?.args,kwargs:c?.kwargs}))}</td>
      <td>${esc(json(c?.assertion))}</td><td>${esc(json(e.observation))}</td><td class="status-${esc(e.status)}">${esc(labels[e.status] || e.status)}</td></tr>`;
  }
  html += `</tbody></table></div>${execution.length ? "" : '<p class="muted">没有动态执行证据，请检查运行环境及验收标准。</p>'}</section>`;
  html += `<section class="card"><h3>提示词诊断与改写</h3><p class="hint">${pr.mode === "LLM" ? "模型语义分析；改写效果尚未经过重新生成验证。" : "离线规则模式：仅匹配原文，不进行语义冲突判断或提示词改写。"}</p>`;
  html += pr.mappings.map(m=>`<div class="requirement"><strong>${esc(m.requirement_id)} · ${esc(labels[m.status] || m.status)}</strong> ${esc(m.explanation)}</div>`).join("");
  if (pr.optimized_prompt) html += `<pre>${esc(pr.optimized_prompt)}</pre><button id="copyPrompt" class="btn ghost sm">复制提示词</button>`;
  if (pr.unresolved_questions.length) html += `<p class="hint">${esc(pr.unresolved_questions.join("；"))}</p>`;
  html += `</section><section class="card"><h3>代码质量与修改建议</h3><p class="hint">${esc(q.criteria)} 共 ${q.findings.length} 项静态发现。建议中的修改尚未自动执行，请复用当前标准回归验收。</p>`;
  html += r.code_suggestions.map(s=>`<article class="suggestion"><strong>${esc(labels[s.category] || s.category)} · ${esc(s.location)}</strong><p>${esc(s.explanation)}</p>
    ${s.trigger_condition ? `<p class="muted">触发输入：${esc(s.trigger_condition)}</p>` : ""}
    ${s.expected ? `<p class="muted">期望：${esc(s.expected)}<br>实际：${esc(s.actual)}</p>` : ""}
    <p>建议：${esc(s.fix)}</p><p class="muted">${esc(s.regression_check)}</p><details><summary>查看依据</summary><p>${esc(s.evidence_ids.join(", "))}</p></details></article>`).join("");
  html += `</section><details class="card"><summary>判定范围与限制</summary><ul class="muted">${r.limitations.map(l=>`<li>${esc(l)}</li>`).join("")}</ul><p class="hint">标准 ${esc(r.acceptance_standard_id)} · 报告 ${esc(r.evaluation_id)}</p></details>`;
  $("reportArea").innerHTML = html;
  $("downloadReport").addEventListener("click", () => {
    const url = URL.createObjectURL(new Blob([json(lastReport)], {type:"application/json"}));
    const a = document.createElement("a"); a.href = url; a.download = lastReport.evaluation_id + ".json"; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  $("copyPrompt")?.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(pr.optimized_prompt); notice("提示词已复制。"); }
    catch(_) { notice("无法访问剪贴板，请直接选择并复制提示词文本。", true); }
  });
}
$("refreshEnv").addEventListener("click", refreshEnvironment);
$("loadDemo").addEventListener("click", () => {
  const demo = demos.find(d=>d.id === $("demoSelect").value);
  if (!demo) return notice("请选择一个示例。", true);
  activeDemo = demo;
  $("reqText").value = demo.requirement; $("promptText").value = demo.generation_prompt;
  $("codeText").value = demo.code; $("entryText").value = demo.entrypoint.callable;
  draft = manualDraft();
  draft.plan.cases = demo.examples.map((e,i)=>({case_id:"U"+(i+1),contract_id:"K_R1",requirement_ids:["R1"],
    args:e.args,kwargs:e.kwargs || {},assertion:e.assertion || {kind:"RETURN_EQUALS",expected:e.expected},expected_basis:e.note,input_domain_status:"IN_SCOPE"}));
  confirmed = null; lastReport = null; $("reportArea").innerHTML = "";
  renderDraft(); save(); notice("已填入错误实现及人工核对的案例。确认标准后验收，再换入正确实现对照。");
});
$("correctDemo").addEventListener("click", () => {
  if (!activeDemo || $("reqText").value.trim() !== activeDemo.requirement) return;
  $("codeText").value = activeDemo.correct_code; $("codeText").dispatchEvent(new Event("input"));
  if (activeDemo.correct_prompt) {
    $("promptText").value = activeDemo.correct_prompt;
    $("promptText").dispatchEvent(new Event("input"));
  }
  notice("已换入正确实现。点击「开始验收」复用相同标准对照结果。");
});
async function init() {
  try {
    const result = await api("demos"); demos = result.demos;
    $("demoSelect").innerHTML += demos.map(d=>`<option value="${esc(d.id)}">${esc(d.title)}</option>`).join("");
    if (demos.length) $("demoSelect").value = demos[0].id;
  } catch(e) { notice("演示列表加载失败：" + e.message, true); }
  try {
    const state = JSON.parse(localStorage.getItem(STORAGE) || "null");
    if (state) {
      $("reqText").value = state.input.requirement; $("promptText").value = state.input.generation_prompt;
      $("codeText").value = state.input.code; $("entryText").value = state.input.entrypoint?.callable || "";
      draft = state.draft; confirmed = state.confirmed; activeDemo = demos.find(d=>d.id === state.demo) || null;
      if (activeDemo) $("demoSelect").value = activeDemo.id;
      renderDraft();
      if (confirmed) $("standardStatus").textContent = "已恢复确认标准，可继续修改代码并复评。";
    }
  } catch(_) {}
  updateButtons(); refreshEnvironment();
}
init();
