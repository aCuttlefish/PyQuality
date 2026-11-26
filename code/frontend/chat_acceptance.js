"use strict";
/* 对话流内嵌 AI 代码验收模块：
   步骤 1 提需求/提示词 → AI 多轮追问搞清需求 → 步骤 2 生成并锁定测试用例（卡片化清晰排版） → 步骤 3 贴代码进 Docker 验收 → 步骤 4 同标准复测
*/
(function () {
  const ACC_LABELS = {
    FAIL: "未通过", PASS_WITHIN_SCOPE: "本轮检查通过", INCONCLUSIVE: "暂无法判定", UNKNOWN: "未判定",
    PASSED: "通过", ASSERTION_FAILED: "失败", TARGET_EXCEPTION: "目标异常", ENV_ERROR: "环境错误",
    HARNESS_ERROR: "检查器错误", TIMEOUT: "超时", NOT_RUN: "未执行", SKIPPED: "已跳过",
    COVERED: "已体现", COVERED_BY_CONTEXT: "上下文已包含", CONFLICT: "与需求冲突",
    MISSING_FROM_VISIBLE_PROMPT: "可见提示词未体现", AMBIGUOUS: "表述有歧义",
    NOT_USABLE: "当前实现不可用", USABLE_WITH_ADVICE: "范围内可用，建议改进",
    USABLE_WITHIN_SCOPE: "在本轮检查范围内可用", REVIEW_REQUIRED: "需要人工审查", UNDETERMINED: "证据不足，继续确认",
    CORRECTNESS_FIX: "功能修正", POTENTIAL_RISK: "潜在风险", READABILITY: "可读性", PERFORMANCE: "性能",
  };
  const CHECK_OPTIONS = [
    ["RETURN_EQUALS", "返回值等于"],
    ["RETURN_IS_NONE", "返回 None"],
    ["RAISES", "抛出异常"],
    ["RETURN_TYPE", "返回值类型"],
    ["ADVANCED", "其他检查（JSON）"],
  ];

  let cachedDemos = null;
  let seq = 0;

  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const toJson = (v) => JSON.stringify(v, null, 2);

  /* 紧凑单行可读 JSON：如 [2, 2] 或 [[0, 2], [1, 1], [2, 0]]，避免多行竖排把框撑烂 */
  function fmtCompact(v) {
    if (v === undefined) return "null";
    const compact = JSON.stringify(v);
    if (compact === undefined) return "null";
    const spaced = compact.replace(/,(?=\S)/g, ", ").replace(/":/g, '": ');
    if (spaced.length <= 140) return spaced;
    return JSON.stringify(v, null, 2);
  }

  function formatAssertionHuman(a) {
    if (!a) return "null";
    if (a.kind === "RETURN_EQUALS") return fmtCompact(a.expected);
    if (a.kind === "RETURN_IS_NONE") return "None";
    if (a.kind === "RETURN_TYPE") return `类型 = ${a.expected_type || ""}`;
    if (a.kind === "RAISES") return `抛出 ${a.exception_type || "异常"}`;
    if (a.kind === "ORDERED") return `${a.direction === "DESC" ? "降序" : "升序"}排列${a.strict ? "（严格）" : ""}`;
    if (a.kind === "INPUT_UNCHANGED") return "输入对象未被修改";
    if (a.kind === "SAME_MULTISET") return "与原输入元素一致";
    return fmtCompact(a);
  }

  function formatObservationHuman(obs) {
    if (!obs || typeof obs !== "object") return `<span class="acc-ev-code">${esc(fmtCompact(obs))}</span>`;
    const ms = typeof obs.duration_ms === "number" ? `<span class="acc-ev-ms">${obs.duration_ms.toFixed(1)} ms</span>` : "";
    if (obs.exception_type) {
      const msg = obs.exception_message ? `: ${obs.exception_message}` : "";
      return `<span class="acc-ev-code status-TARGET_EXCEPTION">抛出 ${esc(obs.exception_type + msg)}</span>${ms}`;
    }
    if ("return_value" in obs) {
      const extra = obs.check_detail ? `<div class="acc-muted" style="margin-top:3px;">详情：${esc(obs.check_detail)}</div>` : "";
      return `<span class="acc-ev-code">${esc(fmtCompact(obs.return_value))}</span>${ms}${extra}`;
    }
    if (obs.error) {
      return `<span class="acc-ev-code status-TARGET_EXCEPTION">${esc(obs.error)}</span>${ms}`;
    }
    return `<span class="acc-ev-code">${esc(fmtCompact(obs))}</span>${ms}`;
  }

  async function accApi(path, body) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 180000);
    try {
      const res = await fetch("/api/acceptance/" + path, {
        method: body === undefined ? "GET" : "POST",
        headers: { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data));
      }
      return data;
    } catch (e) {
      if (e.name === "AbortError") throw new Error("请求超时，请检查模型与 Docker 环境后重试。");
      throw e;
    } finally {
      clearTimeout(timer);
    }
  }

  function appendChatCard(innerHtml) {
    const chat = document.getElementById("chat");
    const div = document.createElement("div");
    div.className = "msg ai";
    div.innerHTML = `<div class="msg-avatar">⚡</div><div class="msg-body"><div class="msg-bubble acc-bubble">${innerHtml}</div></div>`;
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
    return div;
  }

  function scrollCardIntoView(el) {
    const chat = document.getElementById("chat");
    if (chat) chat.scrollTop = chat.scrollHeight;
    try { el.scrollIntoView({ behavior: "smooth", block: "nearest" }); } catch (_) {}
  }

  function expectationText(a) {
    if (!a) return "null";
    if (a.kind === "RETURN_EQUALS") return fmtCompact(a.expected);
    if (a.kind === "RETURN_IS_NONE") return "null";
    if (a.kind === "RETURN_TYPE") return a.expected_type || "";
    if (a.kind === "RAISES") return a.exception_type || "";
    return fmtCompact(a);
  }

  function buildManualDraft(requirement, entrypointCallable) {
    return {
      requirement,
      entrypoint: entrypointCallable ? { module: "solution", callable: entrypointCallable } : null,
      spec: {
        spec_id: "SPEC-DRAFT",
        requirements: [{
          id: "R1",
          statement: requirement,
          mandatory: true,
          origin: "EXPLICIT",
          kind: "FUNCTIONAL",
          source_quote: requirement,
          unresolved_questions: [],
          acceptance_intent: "用户确认的固定案例验收",
        }],
        input_domain: [],
        technical_constraints: [],
        unresolved_questions: [],
      },
      plan: {
        contracts: [{
          contract_id: "K_R1",
          requirement_ids: ["R1"],
          description: "固定输入输出案例",
          relation_to_requirement: "EQUIVALENT",
          relation_basis: "用户确认固定输入输出，结论仅覆盖声明的案例范围",
          oracle_origin: "MODEL_HYPOTHESIS",
        }],
        cases: [{
          case_id: "U1",
          contract_id: "K_R1",
          requirement_ids: ["R1"],
          args: [],
          kwargs: {},
          category: "USER_EXAMPLE",
          assertion: { kind: "RETURN_EQUALS", expected: null },
          expected_basis: "用户对照需求确认的期望值",
          input_domain_status: "IN_SCOPE",
        }],
      },
      issues: [],
      scope_note: "本轮仅验证已确认的固定测试案例；不保证未测试输入与输入域外行为。",
    };
  }

  async function runPrepareAndShowStep2(ctx, btnEl, noticeFn) {
    const req = (ctx.requirement || "").trim();
    if (!req) throw new Error("需求内容不能为空。");
    const origText = btnEl.textContent;
    btnEl.disabled = true;
    btnEl.textContent = "AI 正在按明确后的需求生成测试用例…";
    try {
      const body = { requirement: req };
      if (ctx.entrypoint) body.entrypoint = { module: "solution", callable: ctx.entrypoint };
      const draft = await accApi("prepare", body);
      ctx.draft = draft;
      if (draft.entrypoint?.callable && !ctx.entrypoint) {
        ctx.entrypoint = draft.entrypoint.callable;
      }
      renderStandardCard(ctx);
    } catch (e) {
      if (noticeFn) noticeFn(e.message, true);
    } finally {
      btnEl.disabled = false;
      btnEl.textContent = origText;
    }
  }

  /* ==================== 需求澄清多轮追问卡片 ==================== */
  function renderClarifyCard(ctx, res) {
    const cid = ++seq;
    const round = ctx.clarifyRound || 1;
    if (res.suggested_entrypoint && !ctx.entrypoint) {
      ctx.entrypoint = res.suggested_entrypoint;
    }
    if (res.refined_requirement) {
      ctx.requirement = res.refined_requirement;
    }

    if (res.ready) {
      const cardEl = appendChatCard(`
        <div class="acc-head">
          <div>
            <h4>需求澄清完成 · 可以生成测试用例了</h4>
            <p class="acc-sub">${esc(res.summary || "关键需求、边界和输入约定已搞清楚。")}</p>
          </div>
          <span class="acc-pill">第 ${round} 轮 · 已明确</span>
        </div>
        <div class="acc-ready-box">✓ 模型已确认需求无明显歧义。下面为你整理好了完整需求说明，核对无误即可直接生成测试用例。</div>
        <div class="acc-notice" id="clrNotice_${cid}" hidden></div>
        <label class="acc-label">整理后的清晰需求说明 <span>如需微调可直接修改</span></label>
        <textarea class="acc-ta" id="clrRefined_${cid}" rows="4">${esc(ctx.requirement)}</textarea>
        <label class="acc-label">待测函数名</label>
        <input type="text" class="acc-in" id="clrEntry_${cid}" placeholder="例如 possibilities" value="${esc(ctx.entrypoint || "")}">
        <div class="acc-actions">
          <button class="btn primary" id="clrGen_${cid}">按明确后的需求生成测试用例</button>
          <button class="btn ghost" id="clrMan_${cid}">改用手动编写测试</button>
        </div>
      `);

      const noticeEl = cardEl.querySelector(`#clrNotice_${cid}`);
      const refinedEl = cardEl.querySelector(`#clrRefined_${cid}`);
      const entryEl = cardEl.querySelector(`#clrEntry_${cid}`);
      const genBtn = cardEl.querySelector(`#clrGen_${cid}`);
      const manBtn = cardEl.querySelector(`#clrMan_${cid}`);

      function showNotice(msg, isErr = false) {
        noticeEl.textContent = msg;
        noticeEl.className = "acc-notice" + (isErr ? " error" : "");
        noticeEl.hidden = !msg;
      }

      genBtn.addEventListener("click", async () => {
        showNotice("");
        ctx.requirement = refinedEl.value.trim();
        ctx.entrypoint = entryEl.value.trim();
        await runPrepareAndShowStep2(ctx, genBtn, showNotice);
      });

      manBtn.addEventListener("click", () => {
        ctx.requirement = refinedEl.value.trim();
        ctx.entrypoint = entryEl.value.trim();
        ctx.draft = buildManualDraft(ctx.requirement, ctx.entrypoint);
        renderStandardCard(ctx);
      });

      scrollCardIntoView(cardEl);
      return;
    }

    const qs = res.questions || [];
    const qsHtml = qs.map((q, idx) => `
      <div class="acc-q-item" data-qidx="${idx}">
        <div class="acc-q-title">${esc(q.id || `Q${idx + 1}`)} · ${esc(q.question)}</div>
        ${(q.options && q.options.length) ? `
          <div class="acc-opts">
            ${q.options.map((opt) => `<button type="button" class="acc-opt-chip" data-val="${esc(opt)}">${esc(opt)}</button>`).join("")}
          </div>` : ""}
        <input type="text" class="acc-in clr-ans" data-qidx="${idx}" placeholder="点上方快捷选项，或直接输入你的回答…">
      </div>
    `).join("");

    const cardEl = appendChatCard(`
      <div class="acc-head">
        <div>
          <h4>需求追问 · 第 ${round} 轮（先搞清楚细节，再生成测试）</h4>
          <p class="acc-sub">${esc(res.summary || "为了生成准确的测试用例，有几个细节想先和你确认一下：")}</p>
        </div>
        <span class="acc-pill">待确认 ${qs.length} 项</span>
      </div>
      <div class="acc-notice" id="clrNotice_${cid}" hidden></div>
      ${qsHtml}
      <div class="acc-actions">
        <button class="btn primary" id="clrSubmit_${cid}">提交回答，继续确认</button>
        <button class="btn ghost" id="clrSkip_${cid}">已经够清楚了，直接生成测试用例</button>
      </div>
    `);

    const noticeEl = cardEl.querySelector(`#clrNotice_${cid}`);
    const submitBtn = cardEl.querySelector(`#clrSubmit_${cid}`);
    const skipBtn = cardEl.querySelector(`#clrSkip_${cid}`);

    function showNotice(msg, isErr = false) {
      noticeEl.textContent = msg;
      noticeEl.className = "acc-notice" + (isErr ? " error" : "");
      noticeEl.hidden = !msg;
    }

    for (const qBox of cardEl.querySelectorAll(".acc-q-item")) {
      const inputEl = qBox.querySelector(".clr-ans");
      for (const chip of qBox.querySelectorAll(".acc-opt-chip")) {
        chip.addEventListener("click", () => {
          for (const other of qBox.querySelectorAll(".acc-opt-chip")) other.classList.remove("active");
          chip.classList.add("active");
          inputEl.value = chip.dataset.val || "";
        });
      }
    }

    submitBtn.addEventListener("click", async () => {
      try {
        showNotice("");
        const answers = [];
        for (let i = 0; i < qs.length; i++) {
          const val = cardEl.querySelector(`.clr-ans[data-qidx="${i}"]`).value.trim();
          if (!val) throw new Error(`请先回答 ${qs[i].id || `Q${i + 1}`}，方便系统准确理解你的需求。`);
          answers.push({ question: qs[i].question, answer: val });
        }
        ctx.qaHistory.push(...answers);
        ctx.clarifyRound = round + 1;
        submitBtn.disabled = true;
        submitBtn.textContent = "AI 正在整理你的回答…";
        const nextRes = await accApi("clarify", {
          initial_input: ctx.initialInput,
          input_type: ctx.inputType,
          entrypoint: ctx.entrypoint || null,
          qa_history: ctx.qaHistory,
        });
        submitBtn.textContent = `已提交第 ${round} 轮回答`;
        renderClarifyCard(ctx, nextRes);
      } catch (e) {
        showNotice(e.message, true);
        submitBtn.disabled = false;
        submitBtn.textContent = "提交回答，继续确认";
      }
    });

    skipBtn.addEventListener("click", async () => {
      showNotice("");
      const extras = [];
      for (let i = 0; i < qs.length; i++) {
        const val = cardEl.querySelector(`.clr-ans[data-qidx="${i}"]`).value.trim();
        if (val) extras.push(`${qs[i].question}：${val}`);
      }
      if (extras.length) {
        ctx.requirement = (ctx.requirement || ctx.initialInput) + "\n补充说明：" + extras.join("；");
      }
      await runPrepareAndShowStep2(ctx, skipBtn, showNotice);
    });

    scrollCardIntoView(cardEl);
  }

  /* ==================== 步骤 2 · 核对并锁定测试用例标准（卡片化清晰排版） ==================== */
  function renderStandardCard(ctx) {
    const cid = ++seq;
    const draft = ctx.draft;
    const entryInit = ctx.entrypoint || draft.entrypoint?.callable || "";
    const draftIssues = [...new Set([
      ...(draft.issues || []),
      ...(draft.spec?.unresolved_questions || []),
    ].filter(Boolean))];
    const hasUnresolved = Boolean(
      (draft.spec?.unresolved_questions || []).length ||
      (draft.spec?.requirements || []).some((r) => r.mandatory !== false && (r.origin === "UNCLEAR" || (r.unresolved_questions || []).length))
    );

    const issuesBlock = draftIssues.length
      ? (hasUnresolved
          ? `<div class="acc-notice error"><strong>发现未澄清的模糊点：</strong><br>${draftIssues.map((x) => "• " + esc(x)).join("<br>")}<br>请在下方补充说明后重新生成测试用例，再锁定标准。</div>`
          : `<details class="acc-sec" style="margin-top:4px;border-top:none;padding-top:0;"><summary style="font-size:12px;color:var(--muted);">查看 AI 自检备注（${draftIssues.length} 条参考提示，不影响确认）</summary><div class="acc-notice">${draftIssues.map((x) => "• " + esc(x)).join("<br>")}</div></details>`)
      : "";

    const cardEl = appendChatCard(`
      <div class="acc-head">
        <div>
          <h4>步骤 2 · 核对并锁定测试用例标准</h4>
          <p class="acc-sub">系统已根据明确后的需求拆出检查项和测试用例。每条都可直接编辑或增删，打勾后锁死为本轮评判标准。</p>
        </div>
        <span class="acc-pill">${draft.plan.cases.length} 项测试</span>
      </div>
      ${issuesBlock}
      ${hasUnresolved ? `
        <div class="acc-clarify">
          <label class="acc-label">补充澄清需求 <span>补全上面指出的模糊点，点按钮重新生成测试用例</span></label>
          <textarea class="acc-ta" id="clarifyReq_${cid}" rows="3">${esc(ctx.requirement)}</textarea>
          <div class="acc-actions" style="margin-top:6px;">
            <button class="btn primary sm" id="regenBtn_${cid}">按补充后的需求重新生成测试用例</button>
          </div>
        </div>` : ""}
      <div class="acc-notice" id="stdNotice_${cid}" hidden></div>

      <label class="acc-label">拆解出的需求条目 <span>共 ${draft.spec.requirements.length} 项</span></label>
      <div class="acc-reqs">
        ${draft.spec.requirements.map((r, rIdx) => `
          <div class="acc-req">
            <div class="acc-req-text"><strong>${esc(r.id)} · ${r.mandatory === false ? "可选" : "必要"}</strong>　${esc(r.statement)}</div>
            <button type="button" class="btn ghost sm r-toggle" data-ridx="${rIdx}">${r.mandatory === false ? "设为必要" : "设为可选"}</button>
          </div>`).join("")}
      </div>

      <label class="acc-label">待测函数名 <span>锁定标准时必须指定函数入口名</span></label>
      <input type="text" class="acc-in" id="stdEntry_${cid}" placeholder="例如 possibilities" value="${esc(entryInit)}">

      <div class="acc-row" style="justify-content:space-between;margin-top:12px;">
        <label class="acc-label" style="margin:0;">测试用例清单 <span>多参数用 JSON 数组如 <code>[5, 0]</code>，单列表参数如 <code>[[1, 2]]</code></span></label>
        <button type="button" class="btn ghost sm" id="addCase_${cid}">+ 添加测试用例</button>
      </div>
      <div class="acc-case-list" id="casesList_${cid}"></div>

      <label class="acc-label">本轮验收范围说明</label>
      <textarea class="acc-ta" id="scope_${cid}" rows="2">${esc(draft.scope_note || "")}</textarea>
      <label class="acc-check">
        <input type="checkbox" id="chk_${cid}">
        <span>我已核对需求和每条测试用例的期望答案，同意把这批测试锁死为本轮代码的评判标准</span>
      </label>
      <div class="acc-actions">
        <button class="btn primary" id="confirmStd_${cid}" disabled>确认并锁定验收标准 → 下一步贴代码</button>
      </div>
    `);

    const listEl = cardEl.querySelector(`#casesList_${cid}`);
    const noticeEl = cardEl.querySelector(`#stdNotice_${cid}`);
    const entryEl = cardEl.querySelector(`#stdEntry_${cid}`);
    const chk = cardEl.querySelector(`#chk_${cid}`);
    const confirmBtn = cardEl.querySelector(`#confirmStd_${cid}`);
    const scopeEl = cardEl.querySelector(`#scope_${cid}`);

    function showNotice(msg, isErr = false) {
      noticeEl.textContent = msg;
      noticeEl.className = "acc-notice" + (isErr ? " error" : "");
      noticeEl.hidden = !msg;
    }

    cardEl.querySelector(`#regenBtn_${cid}`)?.addEventListener("click", async () => {
      const btn = cardEl.querySelector(`#regenBtn_${cid}`);
      const newReq = cardEl.querySelector(`#clarifyReq_${cid}`).value.trim();
      if (!newReq) return showNotice("请先填写补充后的功能需求。", true);
      ctx.requirement = newReq;
      ctx.entrypoint = entryEl.value.trim() || ctx.entrypoint;
      await runPrepareAndShowStep2(ctx, btn, showNotice);
    });

    for (const rBtn of cardEl.querySelectorAll(".r-toggle")) {
      rBtn.addEventListener("click", () => {
        const idx = Number(rBtn.dataset.ridx);
        const item = draft.spec.requirements[idx];
        item.mandatory = item.mandatory === false ? true : false;
        rBtn.textContent = item.mandatory === false ? "设为必要" : "设为可选";
        rBtn.parentElement.querySelector("strong").textContent = `${item.id} · ${item.mandatory === false ? "可选" : "必要"}`;
        chk.checked = false;
        confirmBtn.disabled = true;
      });
    }

    function readCasesFromDom() {
      const cards = [...listEl.querySelectorAll(".acc-case-card")];
      draft.plan.cases = cards.map((card, i) => {
        const old = draft.plan.cases[i];
        const kind = card.querySelector(".k-sel").value;
        const expStr = card.querySelector(".k-exp").value;
        let args;
        try {
          args = JSON.parse(card.querySelector(".k-args").value);
          if (!Array.isArray(args)) throw new Error("位置参数必须是 JSON 数组");
        } catch (e) {
          throw new Error(`${old.case_id} 参数格式错误：${e.message}`);
        }
        let assertion;
        try {
          if (kind === "RETURN_EQUALS") assertion = { kind, expected: JSON.parse(expStr) };
          else if (kind === "RETURN_IS_NONE") assertion = { kind };
          else if (kind === "RAISES") assertion = { kind, exception_type: expStr.trim(), message_contains: old.assertion?.message_contains || "" };
          else if (kind === "RETURN_TYPE") assertion = { kind, expected_type: expStr.trim() };
          else assertion = JSON.parse(expStr);
        } catch (e) {
          throw new Error(`${old.case_id} 期望值格式错误：${e.message}`);
        }
        const rids = card.querySelector(".k-rids").value.split(",").map((s) => s.trim()).filter(Boolean);
        const finalRids = rids.length ? rids : ["R1"];
        let cidVal = old.contract_id;
        const curContract = (draft.plan.contracts || []).find((ct) => ct.contract_id === cidVal);
        const fits = (ct) => ct && finalRids.every((id) => (ct.requirement_ids || []).includes(id));
        if (!fits(curContract)) {
          const match = (draft.plan.contracts || []).find(fits);
          if (match) {
            cidVal = match.contract_id;
          } else {
            const newCid = "K_USER_" + finalRids.join("_");
            if (!(draft.plan.contracts || []).some((ct) => ct.contract_id === newCid)) {
              draft.plan.contracts.push({
                contract_id: newCid,
                requirement_ids: finalRids,
                description: "用户补充的固定案例",
                relation_to_requirement: "EQUIVALENT",
                relation_basis: "用户确认固定输入输出，结论仅覆盖声明的案例范围",
                oracle_origin: "MODEL_HYPOTHESIS",
              });
            }
            cidVal = newCid;
          }
        }
        return { ...old, contract_id: cidVal, args, assertion, requirement_ids: finalRids };
      });
      draft.scope_note = scopeEl.value.trim();
    }

    function renderCaseCards() {
      if (!draft.plan.cases.length) {
        listEl.innerHTML = `<div class="acc-notice">当前暂无测试用例，请点击右上角「+ 添加测试用例」。</div>`;
        cardEl.querySelector(".acc-pill").textContent = "0 项测试";
        return;
      }
      listEl.innerHTML = draft.plan.cases.map((c, idx) => {
        const kind = CHECK_OPTIONS.some(([k]) => k === c.assertion?.kind) ? c.assertion.kind : "ADVANCED";
        const argsStr = fmtCompact(c.args || []);
        const expStr = expectationText(c.assertion);
        const expRows = expStr.includes("\n") ? Math.min(5, expStr.split("\n").length) : (expStr.length > 72 ? 2 : 1);
        const kwHint = c.kwargs && Object.keys(c.kwargs).length
          ? `<div class="acc-muted" style="margin-top:4px;">kwargs: <code>${esc(fmtCompact(c.kwargs))}</code></div>` : "";
        const basis = c.expected_basis ? `<span class="acc-case-basis" title="${esc(c.expected_basis)}">· ${esc(c.expected_basis)}</span>` : "";
        return `
          <div class="acc-case-card" data-idx="${idx}">
            <div class="acc-case-head">
              <div class="acc-case-meta">
                <span class="acc-case-num">#${idx + 1} · ${esc(c.case_id)}</span>
                <span class="acc-muted">关联需求</span>
                <input class="acc-in acc-case-rid k-rids" value="${esc((c.requirement_ids || ["R1"]).join(","))}">
                ${basis}
              </div>
              <button type="button" class="btn ghost sm k-del" title="删除此用例">删除</button>
            </div>
            <div class="acc-case-grid">
              <div>
                <span class="acc-field-lbl">输入参数（JSON 数组）</span>
                <input type="text" class="acc-in k-args" value="${esc(argsStr)}">
                ${kwHint}
              </div>
              <div>
                <span class="acc-field-lbl">检查方式与期望结果</span>
                <div class="acc-exp-row">
                  <select class="acc-sel k-sel">${CHECK_OPTIONS.map(([k, l]) => `<option value="${k}" ${k === kind ? "selected" : ""}>${l}</option>`).join("")}</select>
                  ${expRows === 1
                    ? `<input type="text" class="acc-in k-exp" value="${esc(expStr)}">`
                    : `<textarea class="acc-ta k-exp" rows="${expRows}">${esc(expStr)}</textarea>`}
                </div>
              </div>
            </div>
          </div>`;
      }).join("");
      cardEl.querySelector(".acc-pill").textContent = `${draft.plan.cases.length} 项测试`;

      for (const card of listEl.querySelectorAll(".acc-case-card")) {
        card.querySelector(".k-del").addEventListener("click", () => {
          try { readCasesFromDom(); } catch (_) {}
          draft.plan.cases.splice(Number(card.dataset.idx), 1);
          chk.checked = false; confirmBtn.disabled = true;
          renderCaseCards();
        });
        card.querySelector(".k-sel").addEventListener("change", (ev) => {
          const defaults = { RETURN_EQUALS: "null", RETURN_IS_NONE: "null", RAISES: "ValueError", RETURN_TYPE: "int", ADVANCED: '{"kind": "INPUT_UNCHANGED", "targets": [{"kind": "ARG", "index": 0}]}' };
          card.querySelector(".k-exp").value = defaults[ev.target.value];
        });
      }
    }

    renderCaseCards();
    cardEl.querySelector(`#addCase_${cid}`).addEventListener("click", () => {
      try { readCasesFromDom(); } catch (_) {}
      const ids = new Set(draft.plan.cases.map((c) => c.case_id));
      let n = draft.plan.cases.length + 1;
      while (ids.has("U" + n)) n++;
      const contract = draft.plan.contracts[0] || { contract_id: "K_R1", requirement_ids: ["R1"] };
      draft.plan.cases.push({
        case_id: "U" + n,
        contract_id: contract.contract_id,
        requirement_ids: contract.requirement_ids,
        args: [],
        kwargs: {},
        category: "USER_EXAMPLE",
        assertion: { kind: "RETURN_EQUALS", expected: null },
        expected_basis: "人工补充的测试用例",
        input_domain_status: "IN_SCOPE",
      });
      chk.checked = false; confirmBtn.disabled = true;
      renderCaseCards();
    });

    chk.addEventListener("change", () => { confirmBtn.disabled = !chk.checked; });

    confirmBtn.addEventListener("click", async () => {
      try {
        showNotice("");
        readCasesFromDom();
        if (!draft.plan.cases.length) throw new Error("请至少保留 1 条测试用例。");
        const entryName = entryEl.value.trim();
        if (!entryName) throw new Error("请填写待测函数名（例如 possibilities）。");
        confirmBtn.disabled = true;
        confirmBtn.textContent = "正在锁定验收标准…";
        const confirmed = await accApi("confirm", {
          requirement: ctx.requirement,
          entrypoint: { module: "solution", callable: entryName },
          spec: draft.spec,
          plan: draft.plan,
          scope_note: draft.scope_note,
          confirmed: true,
          case_scope_confirmed: true,
        });
        ctx.confirmed = confirmed;
        ctx.entrypoint = entryName;
        confirmBtn.textContent = `标准已锁定（${confirmed.confirmed_spec_id.slice(0, 14)}…）`;
        renderCodeSubmitCard(ctx);
      } catch (e) {
        showNotice(e.message, true);
        confirmBtn.disabled = !chk.checked;
        confirmBtn.textContent = "确认并锁定验收标准 → 下一步贴代码";
      }
    });
    scrollCardIntoView(cardEl);
  }

  /* ==================== 步骤 3 · 提交待测代码并执行验收 ==================== */
  function renderCodeSubmitCard(ctx) {
    const cid = ++seq;
    const caseCount = ctx.confirmed?.plan?.cases?.length ?? ctx.draft?.plan?.cases?.length ?? 0;
    const cardEl = appendChatCard(`
      <div class="acc-head">
        <div>
          <h4>步骤 3 · 提交待测代码并按标准验收</h4>
          <p class="acc-sub">测试标准已锁定（<code>${esc(ctx.confirmed.confirmed_spec_id)}</code> · 共 ${caseCount} 项测试 · 入口 <code>${esc(ctx.entrypoint)}</code>）。现在把 AI 写的代码贴进来检验。</p>
        </div>
        <span class="acc-pill">标准已锁定</span>
      </div>
      <div class="acc-notice" id="codeNotice_${cid}" hidden></div>
      <label class="acc-label">AI 生成的 Python 代码 <span>支持含 main() 的完整源码</span></label>
      <textarea class="acc-ta" id="subCode_${cid}" rows="10" spellcheck="false" placeholder="在这里粘贴待验收的 Python 函数代码…">${esc(ctx.code || "")}</textarea>
      <label class="acc-label">原始生成提示词 <span>可选，没有可留空；若第 1 步贴的是提示词已自动带入</span></label>
      <textarea class="acc-ta" id="subPrompt_${cid}" rows="2" placeholder="粘贴当时发给 AI 的提示词（可留空）">${esc(ctx.prompt || "")}</textarea>
      <div class="acc-actions">
        <button class="btn primary" id="evalRun_${cid}">在 Docker 容器中按标准验收</button>
      </div>
    `);

    const codeEl = cardEl.querySelector(`#subCode_${cid}`);
    const promptEl = cardEl.querySelector(`#subPrompt_${cid}`);
    const noticeEl = cardEl.querySelector(`#codeNotice_${cid}`);
    const runBtn = cardEl.querySelector(`#evalRun_${cid}`);

    runBtn.addEventListener("click", async () => {
      try {
        noticeEl.hidden = true;
        const code = codeEl.value;
        if (!code.trim()) throw new Error("请先粘贴待验收的 Python 代码。");
        ctx.code = code;
        ctx.prompt = promptEl.value.trim();
        runBtn.disabled = true;
        runBtn.textContent = "正在 Docker 容器中跑测试并检查质量…";
        const evalRes = await accApi("evaluate", {
          requirement: ctx.requirement,
          generation_prompt: ctx.prompt,
          code: ctx.code,
          entrypoint: { module: "solution", callable: ctx.entrypoint },
          acceptance_materials: {
            confirmed_spec_id: ctx.confirmed.confirmed_spec_id,
            confirmed_spec_hash: ctx.confirmed.confirmed_spec_hash,
          },
          options: { oracle_policy: "confirmed_only" },
        });
        runBtn.textContent = "验收完成（可在下方报告中复测）";
        runBtn.disabled = false;
        const prev = ctx.lastReport || null;
        ctx.lastReport = evalRes.report;
        renderReportCard(ctx, evalRes.report, prev);
      } catch (e) {
        noticeEl.textContent = e.message;
        noticeEl.className = "acc-notice error";
        noticeEl.hidden = false;
        runBtn.disabled = false;
        runBtn.textContent = "在 Docker 容器中按标准验收";
      }
    });

    scrollCardIntoView(cardEl);
  }

  /* ==================== 步骤 4 · 验收报告与同标准复测 ==================== */
  function renderReportCard(ctx, r, prev) {
    const cid = ++seq;
    const cov = r.coverage;
    const q = r.quality_report;
    const pr = r.prompt_report;
    const casesMap = new Map((r.test_plan?.cases || []).map((c) => [c.case_id, c]));
    const execution = (r.evidence || []).filter((e) => e.kind === "EXECUTED_CASE");
    const ratio = cov.cases_executed ? ((100 * cov.cases_passed) / cov.cases_executed).toFixed(1) + "%" : "未执行";
    const compareHtml =
      prev && prev.reproducibility?.plan_hash === r.reproducibility?.plan_hash
        ? `<div class="acc-comparison">同一批测试用例对比：上次 ${esc(ACC_LABELS[prev.code_verdict])}（${prev.coverage.cases_passed}/${prev.coverage.cases_planned}） → 本次 ${esc(ACC_LABELS[r.code_verdict])}（${cov.cases_passed}/${cov.cases_planned}）</div>`
        : "";

    const rowsHtml = execution.map((e) => {
      const c = casesMap.get(e.case_id);
      const statusLabel = ACC_LABELS[e.status] || e.status;
      const prefix = e.status === "PASSED" ? "✓ " : "✕ ";
      return `<tr>
        <td class="col-cid"><strong>${esc(e.case_id)}</strong><br><span class="acc-muted">${esc((e.requirement_ids || []).join(","))}</span></td>
        <td class="col-args"><span class="acc-ev-code">${esc(fmtCompact(c?.args ?? []))}</span></td>
        <td><span class="acc-ev-code">${esc(formatAssertionHuman(c?.assertion))}</span></td>
        <td>${formatObservationHuman(e.observation)}</td>
        <td class="col-verdict"><span class="acc-verdict-pill status-${esc(e.status)}">${prefix}${esc(statusLabel)}</span></td>
      </tr>`;
    }).join("");

    const promptHtml = pr.mappings.map((m) =>
      `<div class="acc-req"><div class="acc-req-text"><strong>${esc(m.requirement_id)} · ${esc(ACC_LABELS[m.status] || m.status)}</strong>　${esc(m.explanation)}</div></div>`
    ).join("");

    const suggHtml = (r.code_suggestions || []).map((s) => `
      <div class="acc-sugg">
        <strong>${esc(ACC_LABELS[s.category] || s.category)} · ${esc(s.location)}</strong>
        <p>${esc(s.explanation)}</p>
        ${s.trigger_condition ? `<p class="acc-muted">触发输入：<code>${esc(s.trigger_condition)}</code></p>` : ""}
        ${s.expected ? `<p class="acc-muted">期望：<code>${esc(s.expected)}</code> ｜ 实际：<code>${esc(s.actual)}</code></p>` : ""}
        <p><strong>建议：</strong>${esc(s.fix)}</p>
      </div>`).join("");

    const cardEl = appendChatCard(`
      <div class="acc-head">
        <div>
          <span class="acc-badge status-${esc(r.usability)}">${esc(ACC_LABELS[r.usability] || r.usability)}</span>
          <span class="acc-muted">${esc(ACC_LABELS[r.code_verdict] || r.code_verdict)} · ${esc(r.isolation_level)} · 标准 ${esc(r.acceptance_standard_id)}</span>
        </div>
        <button class="btn ghost sm" id="dl_${cid}">下载 JSON 报告</button>
      </div>
      <p class="acc-summary">${esc(r.summary)}</p>
      ${compareHtml}
      <div class="acc-metrics">
        <div class="acc-metric"><strong>${cov.cases_passed} / ${cov.cases_planned}</strong><span>通过 / 总测试用例</span></div>
        <div class="acc-metric"><strong>${ratio}</strong><span>已执行通过比例</span></div>
        <div class="acc-metric"><strong>${q.readability_score} · ${esc(q.readability_grade)}</strong><span>静态可读性评分</span></div>
      </div>
      ${r.blockers?.length ? `<div class="acc-notice error">${esc(r.blockers.join("\n"))}</div>` : ""}
      <details open class="acc-sec">
        <summary>测试输入、期望与实际执行证据（${execution.length} 项）</summary>
        <div class="acc-table-wrap">
          <table class="acc-table acc-ev-table">
            <thead><tr><th class="col-cid">用例</th><th class="col-args">输入参数</th><th>期望结果</th><th>实际运行结果</th><th class="col-verdict">判定</th></tr></thead>
            <tbody>${rowsHtml || '<tr><td colspan="5" class="acc-muted">无动态执行证据</td></tr>'}</tbody>
          </table>
        </div>
      </details>
      <details ${r.code_suggestions?.length ? "open" : ""} class="acc-sec">
        <summary>代码质量与修改建议（静态发现 ${q.findings.length} 项 · 建议 ${r.code_suggestions.length} 条）</summary>
        ${suggHtml || '<p class="acc-muted">本轮无额外代码修改建议。</p>'}
      </details>
      <details class="acc-sec">
        <summary>提示词诊断与改写（${pr.mode === "LLM" ? "模型语义分析" : "离线规则模式"}）</summary>
        ${promptHtml}
        ${pr.optimized_prompt ? `<pre class="acc-pre">${esc(pr.optimized_prompt)}</pre><button class="btn ghost sm" id="cp_${cid}">复制改写提示词</button>` : ""}
      </details>
      <div class="acc-actions">
        <button class="btn primary" id="retest_${cid}">修改代码 / AI 自动修复并同标准复测</button>
      </div>
    `);

    cardEl.querySelector(`#dl_${cid}`).addEventListener("click", () => {
      const url = URL.createObjectURL(new Blob([toJson(r)], { type: "application/json" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `${r.evaluation_id}.json`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });

    cardEl.querySelector(`#cp_${cid}`)?.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(pr.optimized_prompt);
        if (typeof toast === "function") toast("已复制改写提示词", "ok");
      } catch (_) {}
    });

    cardEl.querySelector(`#retest_${cid}`).addEventListener("click", () => {
      renderRetestCard(ctx);
    });

    scrollCardIntoView(cardEl);
  }

  function renderRetestCard(ctx) {
    const cid = ++seq;
    const caseCount = ctx.confirmed?.plan?.cases?.length ?? ctx.draft?.plan?.cases?.length ?? 0;
    const cardEl = appendChatCard(`
      <div class="acc-head">
        <div>
          <h4>同标准复测 · 保持测试用例不变</h4>
          <p class="acc-sub">沿用锁定标准 <code>${esc(ctx.confirmed.confirmed_spec_id)}</code>（${caseCount} 项固定测试），只修改代码再跑一遍对比。</p>
        </div>
        <span class="acc-pill">标准已锁定</span>
      </div>
      <div class="acc-notice" id="rtNotice_${cid}" hidden></div>
      <label class="acc-label">修改后的 Python 代码（入口：<code>${esc(ctx.entrypoint)}</code>）</label>
      <textarea class="acc-ta" id="rtCode_${cid}" rows="10" spellcheck="false">${esc(ctx.code)}</textarea>
      <label class="acc-label">原始/改写提示词（可选，留空即可）</label>
      <textarea class="acc-ta" id="rtPrompt_${cid}" rows="2">${esc(ctx.prompt || "")}</textarea>
      <div class="acc-actions">
        <button class="btn primary" id="rtAiFix_${cid}">✨ AI 根据失败反例自动修复并复测</button>
        <button class="btn ghost" id="rtRun_${cid}">手动修改后沿用原标准验收</button>
        ${ctx.activeDemo?.correct_code ? `<button class="btn ghost sm" id="rtFill_${cid}">换入示例修正版</button>` : ""}
      </div>
    `);

    const codeEl = cardEl.querySelector(`#rtCode_${cid}`);
    const promptEl = cardEl.querySelector(`#rtPrompt_${cid}`);
    const noticeEl = cardEl.querySelector(`#rtNotice_${cid}`);
    const aiFixBtn = cardEl.querySelector(`#rtAiFix_${cid}`);
    const runBtn = cardEl.querySelector(`#rtRun_${cid}`);

    cardEl.querySelector(`#rtFill_${cid}`)?.addEventListener("click", () => {
      codeEl.value = ctx.activeDemo.correct_code;
      if (ctx.activeDemo.correct_prompt) promptEl.value = ctx.activeDemo.correct_prompt;
    });

    async function runLockedRetest(triggerBtn, busyText, doneText) {
      ctx.code = codeEl.value;
      ctx.prompt = promptEl.value.trim();
      triggerBtn.disabled = true;
      triggerBtn.textContent = busyText;
      const evalRes = await accApi("evaluate", {
        requirement: ctx.requirement,
        generation_prompt: ctx.prompt,
        code: ctx.code,
        entrypoint: { module: "solution", callable: ctx.entrypoint },
        acceptance_materials: {
          confirmed_spec_id: ctx.confirmed.confirmed_spec_id,
          confirmed_spec_hash: ctx.confirmed.confirmed_spec_hash,
        },
        options: { oracle_policy: "confirmed_only" },
      });
      triggerBtn.textContent = doneText;
      triggerBtn.disabled = false;
      const prev = ctx.lastReport;
      ctx.lastReport = evalRes.report;
      renderReportCard(ctx, evalRes.report, prev);
    }

    aiFixBtn.addEventListener("click", async () => {
      try {
        noticeEl.hidden = true;
        aiFixBtn.disabled = true;
        runBtn.disabled = true;
        aiFixBtn.textContent = "AI 正在根据失败反例修复代码…";
        const r = ctx.lastReport;
        const casesMap = new Map((r?.test_plan?.cases || []).map((c) => [c.case_id, c]));
        const execEv = (r?.evidence || []).filter((e) => e.kind === "EXECUTED_CASE");
        const failedCases = [];
        const passedCases = [];
        for (const e of execEv) {
          const c = casesMap.get(e.case_id);
          const item = {
            case_id: e.case_id,
            args: c?.args ?? [],
            kwargs: c?.kwargs ?? {},
            assertion: c?.assertion,
            observation: e.observation,
            status: e.status,
          };
          if (e.status === "PASSED") passedCases.push(item);
          else failedCases.push(item);
        }
        const rep = await accApi("repair", {
          requirement: ctx.requirement,
          code: codeEl.value,
          entrypoint: { module: "solution", callable: ctx.entrypoint },
          failed_cases: failedCases,
          passed_cases: passedCases,
          suggestions: (r?.code_suggestions || []).map((s) => `${s.location}: ${s.fix}`),
        });
        codeEl.value = rep.fixed_code;
        noticeEl.textContent = `✓ AI 已生成修复候选（${rep.change_summary}），正在沿用原锁定标准送进 Docker 验证…`;
        noticeEl.className = "acc-notice";
        noticeEl.hidden = false;
        await runLockedRetest(aiFixBtn, "正在 Docker 中用原标准验证修复结果…", "✨ 再次让 AI 修复并复测");
        runBtn.disabled = false;
      } catch (e) {
        noticeEl.textContent = e.message;
        noticeEl.className = "acc-notice error";
        noticeEl.hidden = false;
        aiFixBtn.disabled = false;
        runBtn.disabled = false;
        aiFixBtn.textContent = "✨ AI 根据失败反例自动修复并复测";
      }
    });

    runBtn.addEventListener("click", async () => {
      try {
        noticeEl.hidden = true;
        await runLockedRetest(runBtn, "正在沿用原标准执行 Docker 复测…", "已完成复测（仍可继续修改复测）");
      } catch (e) {
        noticeEl.textContent = e.message;
        noticeEl.className = "acc-notice error";
        noticeEl.hidden = false;
        runBtn.disabled = false;
        runBtn.textContent = "手动修改后沿用原标准验收";
      }
    });

    scrollCardIntoView(cardEl);
  }

  /* ==================== 步骤 1 · 输入需求或生成提示词，默认先走 AI 多轮追问 ==================== */
  async function openAcceptanceInChat(opts = {}) {
    const cid = ++seq;
    const cardEl = appendChatCard(`
      <div class="acc-head">
        <div>
          <h4>步骤 1 · 先说出你的需求（或直接贴给 AI 的提示词）</h4>
          <p class="acc-sub" id="env_${cid}">正在检查 Docker 与模型运行环境…</p>
        </div>
        <div class="acc-row">
          <select class="acc-sel acc-demo-sel" id="demoSel_${cid}"><option value="">可选：加载内置示例…</option></select>
          <button class="btn ghost sm" id="demoBtn_${cid}">填入</button>
        </div>
      </div>
      <div class="acc-notice" id="inNotice_${cid}" hidden></div>
      <div class="acc-type-row">
        <label><input type="radio" name="inType_${cid}" value="requirement" checked> 我写的是功能需求</label>
        <label><input type="radio" name="inType_${cid}" value="prompt"> 我贴的是让 AI 写代码的提示词</label>
      </div>
      <label class="acc-label">需求描述 / 生成提示词 <span>粗略写就行，下一步 AI 会先向你追问细节，完全搞清后再出测试用例</span></label>
      <textarea class="acc-ta" id="req_${cid}" rows="4" placeholder="例如：写一个 possibilities(m, n) 函数，找出用 n 个非负整数凑出目标和 m 的所有有序列表。">${esc(opts.requirement || "")}</textarea>
      <label class="acc-label">待测函数名 <span>可选，没填时 AI 会在追问中帮你确认</span></label>
      <input type="text" class="acc-in" id="entry_${cid}" placeholder="例如 possibilities（可选）" value="${esc(opts.entrypoint || "")}">
      ${opts.code ? `<p class="acc-muted" style="margin-top:6px;">已暂存项目源码，锁定测试用例后会自动带入步骤 3。</p>` : ""}
      <div class="acc-actions">
        <button class="btn primary" id="clarify_${cid}">下一步：AI 追问澄清需求 →</button>
        <button class="btn ghost sm" id="prep_${cid}">跳过追问，直接生成测试</button>
        <button class="btn ghost sm" id="man_${cid}">手动编写测试</button>
      </div>
    `);

    const envEl = cardEl.querySelector(`#env_${cid}`);
    const noticeEl = cardEl.querySelector(`#inNotice_${cid}`);
    const reqEl = cardEl.querySelector(`#req_${cid}`);
    const entryEl = cardEl.querySelector(`#entry_${cid}`);
    const demoSel = cardEl.querySelector(`#demoSel_${cid}`);
    const clarifyBtn = cardEl.querySelector(`#clarify_${cid}`);
    const prepBtn = cardEl.querySelector(`#prep_${cid}`);
    const manBtn = cardEl.querySelector(`#man_${cid}`);

    const ctx = {
      initialInput: opts.requirement || "",
      inputType: "requirement",
      qaHistory: [],
      clarifyRound: 1,
      requirement: opts.requirement || "",
      prompt: opts.prompt || "",
      code: opts.code || "",
      entrypoint: opts.entrypoint || "",
      draft: null,
      confirmed: null,
      lastReport: null,
      activeDemo: null,
    };

    function showNotice(msg, isErr = false) {
      noticeEl.textContent = msg;
      noticeEl.className = "acc-notice" + (isErr ? " error" : "");
      noticeEl.hidden = !msg;
    }

    function readStep1Input() {
      const text = reqEl.value.trim();
      if (!text) throw new Error("请先填写你的功能需求或生成代码的提示词。");
      const inType = cardEl.querySelector(`input[name="inType_${cid}"]:checked`)?.value || "requirement";
      ctx.initialInput = text;
      ctx.inputType = inType;
      ctx.requirement = text;
      ctx.entrypoint = entryEl.value.trim();
      ctx.qaHistory = [];
      ctx.clarifyRound = 1;
      ctx.activeDemo = null;
      if (inType === "prompt" && !ctx.prompt) {
        ctx.prompt = text;
      }
    }

    accApi("environment").then((env) => {
      const m = env.model_configured ? "DeepSeek 模型已就绪" : "模型未配置（可手动编测试）";
      const e = env.execution_backend === "HOST_SUBPROCESS_DEV" ? "本地可信演示" :
        env.ready_for_execution ? "Docker 隔离执行已就绪" : "Docker 执行未就绪";
      envEl.textContent = `${e} · ${m}`;
    }).catch(() => { envEl.textContent = "运行环境检测失败"; });

    (cachedDemos ? Promise.resolve({ demos: cachedDemos }) : accApi("demos")).then((res) => {
      cachedDemos = res.demos || [];
      demoSel.innerHTML = `<option value="">可选：加载内置示例…</option>` + cachedDemos.map((d) => `<option value="${esc(d.id)}">${esc(d.title)}</option>`).join("");
    }).catch(() => {});

    cardEl.querySelector(`#demoBtn_${cid}`).addEventListener("click", () => {
      const d = (cachedDemos || []).find((x) => x.id === demoSel.value);
      if (!d) return showNotice("请先在下拉框选择一个示例，或直接在下方输入你的需求。", true);
      ctx.activeDemo = d;
      reqEl.value = d.requirement;
      entryEl.value = d.entrypoint?.callable || "";
      ctx.initialInput = d.requirement;
      ctx.requirement = d.requirement;
      ctx.prompt = d.generation_prompt || "";
      ctx.entrypoint = d.entrypoint?.callable || "";
      ctx.code = d.code;
      ctx.draft = buildManualDraft(d.requirement, ctx.entrypoint);
      ctx.draft.plan.cases = d.examples.map((ex, i) => ({
        case_id: "U" + (i + 1),
        contract_id: "K_R1",
        requirement_ids: ["R1"],
        args: ex.args,
        kwargs: ex.kwargs || {},
        assertion: ex.assertion || { kind: "RETURN_EQUALS", expected: ex.expected },
        expected_basis: ex.note || "",
        input_domain_status: "IN_SCOPE",
      }));
      showNotice("已载入示例需求与测试用例（示例代码会在锁定标准后自动带入步骤 3）。");
      renderStandardCard(ctx);
    });

    clarifyBtn.addEventListener("click", async () => {
      try {
        showNotice("");
        readStep1Input();
        clarifyBtn.disabled = true;
        clarifyBtn.textContent = "AI 正在分析需求并准备追问…";
        const res = await accApi("clarify", {
          initial_input: ctx.initialInput,
          input_type: ctx.inputType,
          entrypoint: ctx.entrypoint || null,
          qa_history: [],
        });
        renderClarifyCard(ctx, res);
      } catch (e) {
        showNotice(e.message, true);
      } finally {
        clarifyBtn.disabled = false;
        clarifyBtn.textContent = "下一步：AI 追问澄清需求 →";
      }
    });

    prepBtn.addEventListener("click", async () => {
      try {
        showNotice("");
        readStep1Input();
        await runPrepareAndShowStep2(ctx, prepBtn, showNotice);
      } catch (e) {
        showNotice(e.message, true);
      }
    });

    manBtn.addEventListener("click", () => {
      try {
        showNotice("");
        readStep1Input();
        ctx.draft = buildManualDraft(ctx.requirement, ctx.entrypoint);
        renderStandardCard(ctx);
      } catch (e) {
        showNotice(e.message, true);
      }
    });

    scrollCardIntoView(cardEl);
  }

  window.openAcceptanceInChat = openAcceptanceInChat;
})();
