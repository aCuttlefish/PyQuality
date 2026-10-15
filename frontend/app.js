const API = "/api";
const $ = (id) => document.getElementById(id);
const HISTORY_KEY = "pyquality_chat_history";
const MAX_HISTORY = 100;

let currentPid = "";
let pickedFiles = [];
let cmdHistory = [];
let cmdHistoryIdx = -1;

const ALL_COMMANDS = ["/help", "/projects", "/use", "/files", "/sample", "/analyze", "/summary", "/smells", "/score", "/security", "/deps", "/deadcode", "/funcs", "/tests", "/fix", "/advice", "/config", "/history", "/export", "/compare", "/snippet", "/dashboard", "/rename", "/delete", "/cicd", "/tree", "/ignore", "/search", "/doc", "/type", "/dup", "/perf", "/refactor"];
const CMD_PARAMS = {
  "/analyze": ["all"],
  "/config": ["set", "reset"],
  "/export": ["markdown", "json", "sarif", "html"],
  "/fix": ["all", "apply"],
  "/tests": ["all"],
  "/advice": ["all"],
  "/delete": ["confirm"],
  "/cicd": ["github", "gitlab"],
  "/ignore": ["add", "del"],
};

(function initTheme() {
  const saved = localStorage.getItem("theme") || "dark";
  document.documentElement.setAttribute("data-theme", saved);
  $("themeBtn").textContent = saved === "dark" ? "🌙" : "☀️";
})();

$("sendBtn").addEventListener("click", sendMessage);
$("msgInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  else if (e.key === "ArrowUp" && cmdHistory.length) { e.preventDefault(); cmdHistoryIdx = Math.min(cmdHistoryIdx + 1, cmdHistory.length - 1); $("msgInput").value = cmdHistory[cmdHistory.length - 1 - cmdHistoryIdx]; }
  else if (e.key === "ArrowDown" && cmdHistoryIdx >= 0) { e.preventDefault(); cmdHistoryIdx--; $("msgInput").value = cmdHistoryIdx >= 0 ? cmdHistory[cmdHistory.length - 1 - cmdHistoryIdx] : ""; }
  else if (e.key === "Tab" && $("msgInput").value.startsWith("/")) { e.preventDefault(); const v = $("msgInput").value; const sp = v.indexOf(" "); if (sp === -1) { const matches = ALL_COMMANDS.filter(c => c.startsWith(v)); if (matches.length === 1) $("msgInput").value = matches[0] + " "; else if (matches.length > 1) addMsg("ai", "可选项: " + matches.join("  ")); } else { const cmd = v.substring(0, sp); const arg = v.substring(sp + 1); const params = CMD_PARAMS[cmd] || []; const matches = params.filter(p => p.startsWith(arg)); if (matches.length === 1) $("msgInput").value = cmd + " " + matches[0] + " "; else if (matches.length > 1) addMsg("ai", "参数: " + matches.join("  ")); } }
});
document.addEventListener("keydown", (e) => {
  if (e.ctrlKey && e.key === "l") { e.preventDefault(); clearHistory(); addMsg("ai", "对话已清空。输入 `/help` 查看命令。"); }
  else if (e.ctrlKey && e.key === "k") { e.preventDefault(); $("msgInput").focus(); }
});
$("projectSelect").addEventListener("change", () => { currentPid = $("projectSelect").value; });
$("uploadBtn").addEventListener("click", () => { $("uploadModal").hidden = false; });
$("closeModalBtn").addEventListener("click", closeModal);
$("modalOverlay").addEventListener("click", closeModal);
$("doUploadBtn").addEventListener("click", uploadProject);
$("themeBtn").addEventListener("click", toggleTheme);

const dz = $("dropzone");
dz.addEventListener("click", () => $("fileInput").click());
$("fileInput").addEventListener("change", (e) => pickFiles(e.target.files));
dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("drag"); });
dz.addEventListener("dragleave", () => dz.classList.remove("drag"));
dz.addEventListener("drop", (e) => { e.preventDefault(); dz.classList.remove("drag"); pickFiles(e.dataTransfer.files); });

document.querySelectorAll(".chip[data-cmd]").forEach((chip) => {
  chip.addEventListener("click", () => { $("msgInput").value = chip.dataset.cmd; sendMessage(); });
});

init();

async function init() {
  loadProjects();
  checkAiStatus();
  if (!loadHistory()) {
    addMsg("ai", "👋 欢迎使用 **PyQuality**！\n\n我是一个 Python 代码质量助手，可以帮你：\n- 🔍 分析代码坏味、安全、依赖、可读性\n- 🤖 生成 pytest 测试用例\n- 🔧 AI 修复代码\n- 💡 提出改进建议\n\n输入 `/help` 查看所有命令，或选择/上传项目后输入 `/analyze` 开始。");
  }
}

function saveHistory() {
  const msgs = [];
  document.querySelectorAll("#chat .msg").forEach((el) => {
    const role = el.classList.contains("ai") ? "ai" : "user";
    const bubble = el.querySelector(".msg-bubble");
    if (bubble) msgs.push({ role, html: bubble.innerHTML });
  });
  try { localStorage.setItem(HISTORY_KEY, JSON.stringify(msgs.slice(-MAX_HISTORY))); } catch {}
}

function loadHistory() {
  try {
    const data = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    if (!data.length) return false;
    const chat = $("chat");
    for (const m of data) {
      const div = document.createElement("div");
      div.className = `msg ${m.role}`;
      const avatar = m.role === "ai" ? "⚡" : "🧑";
      div.innerHTML = `<div class="msg-avatar">${avatar}</div><div class="msg-body"><div class="msg-bubble">${m.html}</div></div>`;
      chat.appendChild(div);
    }
    chat.scrollTop = chat.scrollHeight;
    return true;
  } catch { return false; }
}

function clearHistory() {
  localStorage.removeItem(HISTORY_KEY);
  $("chat").innerHTML = "";
}

function closeModal() { $("uploadModal").hidden = true; }

function pickFiles(fileList) {
  pickedFiles = Array.from(fileList);
  const names = pickedFiles.map((f) => f.name + " (" + fmtSize(f.size) + ")");
  $("dzFiles").textContent = names.length ? "已选择:\n" + names.join("\n") : "";
}

async function uploadProject() {
  if (!pickedFiles.length) return toast("请先选择文件", "err");
  const fd = new FormData();
  const zip = pickedFiles.find((f) => f.name.toLowerCase().endsWith(".zip"));
  if (zip) fd.append("archive", zip);
  pickedFiles.filter((f) => f !== zip).forEach((f) => fd.append("files", f));
  if ($("projName").value.trim()) fd.append("name", $("projName").value.trim());
  await withLoading($("doUploadBtn"), "上传中...", async () => {
    const r = await api("/projects/upload", { method: "POST", body: fd }, 120000);
    toast(`项目「${r.project.name}」上传成功`, "ok");
    closeModal();
    pickedFiles = []; $("fileInput").value = ""; $("dzFiles").textContent = ""; $("projName").value = "";
    await loadProjects();
    currentPid = r.project.id;
    $("projectSelect").value = currentPid;
    addMsg("ai", `✅ 项目「**${r.project.name}**」已加载（${r.files.length} 个文件）。\n\n输入 \`/analyze\` 开始分析。`);
  });
}

async function loadProjects() {
  try {
    const r = await api("/projects");
    const sel = $("projectSelect");
    sel.innerHTML = `<option value="">选择项目...</option>` + r.projects.map((p) => {
      const badge = p.grade ? ` (${p.score}·${p.grade})` : "";
      return `<option value="${p.id}">${esc(p.name)}${badge}</option>`;
    }).join("");
    if (currentPid) sel.value = currentPid;
  } catch (e) { toast(e.message, "err"); }
}

async function checkAiStatus() {
  try {
    const r = await api("/ai/status");
    const el = $("aiStatus");
    if (r.available) { el.className = "ai-status on"; el.innerHTML = '<span class="dot"></span>AI 已连接'; }
    else { el.className = "ai-status off"; el.innerHTML = '<span class="dot"></span>AI 未配置'; }
  } catch { $("aiStatus").innerHTML = '<span class="dot"></span>服务离线'; }
}

async function sendMessage() {
  const msg = $("msgInput").value.trim();
  if (!msg) return;
  $("msgInput").value = "";
  cmdHistory.push(msg);
  if (cmdHistory.length > 50) cmdHistory.shift();
  cmdHistoryIdx = -1;
  addMsg("user", msg);
  const thinking = addMsg("ai", '<span class="loading"></span> 处理中...', true);
  await withLoading($("sendBtn"), "发送中", async () => {
    try {
      const r = await api("/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: msg, project_id: currentPid }) });
      thinking.remove();
      addMsg("ai", r.reply);
      if (r.project_id && r.project_id !== currentPid) { currentPid = r.project_id; $("projectSelect").value = currentPid; }
    } catch (e) { thinking.remove(); addMsg("ai", `⚠ ${e.message}`); }
  });
}

function addMsg(role, content, isHtml = false) {
  const chat = $("chat");
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  const avatar = role === "ai" ? "⚡" : "🧑";
  const body = isHtml ? content : (role === "ai" ? renderMarkdown(content) : esc(content));
  div.innerHTML = `<div class="msg-avatar">${avatar}</div><div class="msg-body"><div class="msg-bubble">${body}</div></div>`;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  if (!isHtml) saveHistory();
  return div;
}

function toggleTheme() {
  const cur = document.documentElement.getAttribute("data-theme") || "dark";
  const next = cur === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("theme", next);
  $("themeBtn").textContent = next === "dark" ? "🌙" : "☀️";
}

function highlightPython(code) {
  try {
    let h = esc(code);
    h = h.replace(/(#.*?$)/gm, '<span class="hl-com">$1</span>');
    h = h.replace(/(&quot;[^&]*?&quot;)/g, '<span class="hl-str">$1</span>');
    h = h.replace(/(&#39;[^&]*?&#39;)/g, '<span class="hl-str">$1</span>');
    h = h.replace(/\bdef\b(\s+)([A-Za-z_]\w*)/g, 'def$1<span class="hl-fn">$2</span>');
    h = h.replace(/\bclass\b(\s+)([A-Za-z_]\w*)/g, 'class$1<span class="hl-fn">$2</span>');
    h = h.replace(/\b(\d+\.?\d*)\b/g, '<span class="hl-num">$1</span>');
    h = h.replace(/\b(def|class|return|if|elif|else|for|while|try|except|finally|with|as|import|from|in|not|and|or|is|None|True|False|lambda|yield|async|await|raise|pass|break|continue|global|assert|del)\b/g, '<span class="hl-kw">$1</span>');
    return h;
  } catch { return esc(code); }
}

function renderMarkdown(md) {
  const codeBlocks = [];
  let text = md.replace(/```(\w*)\n([\s\S]*?)```/g, (m, lang, code) => {
    codeBlocks.push({ lang, code });
    return `\x00CB${codeBlocks.length - 1}\x00`;
  });
  let html = esc(text);
  html = html.replace(/^### (.+)$/gm, "<h3>$1</h3>");
  html = html.replace(/^## (.+)$/gm, "<h2>$1</h2>");
  html = html.replace(/^# (.+)$/gm, "<h1>$1</h1>");
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/^- (.+)$/gm, "<li>$1</li>");
  html = html.replace(/(<li>[\s\S]*?<\/li>)(?!\s*<li>)/g, "<ul>$1</ul>");
  html = html.replace(/^&gt; (.+)$/gm, "<blockquote>$1</blockquote>");
  html = html.replace(/\n{2,}/g, "<br>");
  html = html.replace(/\x00CB(\d+)\x00/g, (m, idx) => {
    const { lang, code } = codeBlocks[parseInt(idx)];
    return `<pre class="code-block">${lang === "python" ? highlightPython(code) : esc(code)}</pre>`;
  });
  return html;
}

async function withLoading(btn, text, fn) {
  const orig = btn.textContent;
  btn.disabled = true; btn.innerHTML = '<span class="loading"></span>' + text;
  try { await fn(); } finally { btn.disabled = false; btn.textContent = orig; }
}

async function api(path, opts = {}, timeoutMs = 30000) {
  const controller = new AbortController();
  const tid = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(API + path, { ...opts, signal: controller.signal });
    let data;
    try { data = await resp.json(); } catch { throw new Error("服务响应异常 (" + resp.status + ")"); }
    if (!resp.ok) throw new Error(data.detail || data.error || data.message || "请求失败 " + resp.status);
    return data;
  } catch (e) {
    if (e.name === "AbortError") throw new Error("请求超时（" + timeoutMs / 1000 + " 秒），AI 服务可能不可达");
    throw e;
  } finally { clearTimeout(tid); }
}

function esc(s) { return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;"); }
function fmtSize(n) { return n > 1048576 ? (n / 1048576).toFixed(1) + "MB" : (n / 1024).toFixed(1) + "KB"; }
function toast(msg, type = "") { const el = document.createElement("div"); el.className = "toast " + type; el.textContent = msg; document.body.appendChild(el); setTimeout(() => el.remove(), 3500); }