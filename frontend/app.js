// ============ 全局状态 ============
const state = {
  file: null,
  analyzeResult: null,   // 模块①结果
};

const API = {
  analyze: "/api/analyze",
  analyzeVideos: "/api/analyze-videos",
  llmStatus: "/api/llm-status",
  tools: "/api/mixing-tools",
};

// ============ 工具函数 ============
function toast(msg, type = "") {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = "toast show " + type;
  setTimeout(() => (t.className = "toast " + type), 2600);
}

function $(id) { return document.getElementById(id); }

// ============ Tab 切换 ============
function switchTab(tabId) {
  document.querySelectorAll(".tab-btn").forEach(b =>
    b.classList.toggle("active", b.dataset.tab === tabId));
  document.querySelectorAll(".tab-pane").forEach(p =>
    p.classList.toggle("active", p.id === tabId));
  document.querySelectorAll(".step-tag").forEach(s =>
    s.classList.toggle("active", s.dataset.jump === tabId));
}
document.querySelectorAll(".tab-btn").forEach(b =>
  b.addEventListener("click", () => switchTab(b.dataset.tab)));
document.querySelectorAll(".step-tag").forEach(s =>
  s.addEventListener("click", () => switchTab(s.dataset.jump)));

// ============ 模块① 上传与分析 ============
const uploadZone = $("uploadZone");
const fileInput = $("fileInput");

uploadZone.addEventListener("click", () => fileInput.click());
uploadZone.addEventListener("dragover", e => {
  e.preventDefault();
  uploadZone.classList.add("dragover");
});
uploadZone.addEventListener("dragleave", () => uploadZone.classList.remove("dragover"));
uploadZone.addEventListener("drop", e => {
  e.preventDefault();
  uploadZone.classList.remove("dragover");
  if (e.dataTransfer.files.length) setFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener("change", e => {
  if (e.target.files.length) setFile(e.target.files[0]);
});

function setFile(f) {
  state.file = f;
  $("fileName").textContent = "已选择：" + f.name;
  $("analyzeBtn").disabled = false;
}

$("analyzeBtn").addEventListener("click", async () => {
  if (!state.file) return;
  const btn = $("analyzeBtn");
  btn.disabled = true;
  btn.textContent = "分析中...";
  try {
    const fd = new FormData();
    fd.append("file", state.file);
    fd.append("top_n", $("topN").value || 50);
    const res = await fetch(API.analyze, { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "分析失败");
    state.analyzeResult = data;
    renderAnalyze(data);
    toast("分析完成，共 " + data.total + " 条素材", "success");
  } catch (err) {
    toast(err.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "开始分析";
  }
});

function renderAnalyze(data) {
  $("analyzeResult").classList.remove("hidden");

  // 概览
  const sg = $("summary");
  sg.innerHTML = "";
  for (const [k, v] of Object.entries(data.summary)) {
    sg.innerHTML += `<div class="summary-item">
      <div class="label">${k}</div>
      <div class="value">${typeof v === "number" ? v.toLocaleString() : v}</div>
    </div>`;
  }

  $("resultMeta").textContent =
    `识别消耗列：「${data.cost_column}」 · 按消耗降序 · 展示 Top ${data.top_n}`;

  // 表格
  const rows = data.top;
  const table = $("resultTable");
  if (!rows.length) { table.innerHTML = "<tr><td>无数据</td></tr>"; return; }
  const cols = Object.keys(rows[0]);
  let html = "<thead><tr>" + cols.map(c => `<th>${c}</th>`).join("") + "</tr></thead><tbody>";
  rows.forEach(r => {
    html += "<tr>" + cols.map(c => {
      const isCost = c === data.cost_column;
      return `<td class="${isCost ? "cost-cell" : ""}">${r[c]}</td>`;
    }).join("") + "</tr>";
  });
  html += "</tbody>";
  table.innerHTML = html;
}

// 跳转到模块②
$("toScriptBtn").addEventListener("click", () => {
  if (!state.analyzeResult) { toast("请先完成分析", "error"); return; }
  switchTab("tab-script");
  $("scriptSourceInfo").textContent =
    `数据源：${state.analyzeResult.top_n} 条爆款素材（来自模块①）`;
});

// ============ 模块② 视频分析（大模型）============
// 加载 LLM 状态横幅
async function loadLLMStatus() {
  try {
    const res = await fetch(API.llmStatus);
    const d = await res.json();
    const banner = $("llmBanner");
    if (d.configured) {
      banner.className = "banner ok";
      const modeNote = d.mode === "vision"
        ? "将下载视频抽帧并读图分析"
        : "基于素材元数据 + 投放数据生成策略脚本（视觉API到位后可切换为读图分析）";
      banner.innerHTML = `✅ 大模型已就绪 · 模式：<b>${d.mode_label}</b>（${d.model}）。${modeNote}`;
    } else {
      banner.className = "banner warn";
      banner.innerHTML = `⚠️ 未检测到 claude-internal 或未配置 CODEBUDDY_API_KEY，当前为<b>示例(mock)模式</b>。` +
        `请安装 claude-internal 并在 <code>.env</code> 配置 CODEBUDDY_API_KEY 后重启服务。`;
    }
  } catch (e) { /* 忽略 */ }
}
loadLLMStatus();

let pollTimer = null;

$("genScriptBtn").addEventListener("click", async () => {
  if (!state.analyzeResult || !state.analyzeResult.top.length) {
    toast("请先在模块①完成素材分析", "error");
    switchTab("tab-analyze");
    return;
  }
  const btn = $("genScriptBtn");
  btn.disabled = true; btn.textContent = "提交中...";
  $("scriptResult").innerHTML = "";
  try {
    const res = await fetch(API.analyzeVideos, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        materials: state.analyzeResult.top,
        industry: $("industrySelect").value,
        limit: parseInt($("scriptLimit").value) || 3,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "提交失败");
    startPolling(data.task_id, data.total);
  } catch (err) {
    toast(err.message, "error");
    btn.disabled = false; btn.textContent = "开始分析视频";
  }
});

function startPolling(taskId, total) {
  $("progressWrap").classList.remove("hidden");
  updateProgress(0, total);
  const btn = $("genScriptBtn");
  btn.textContent = "分析中...";

  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const res = await fetch(`${API.analyzeVideos}/${taskId}`);
      const d = await res.json();
      updateProgress(d.done, d.total);
      renderVideoResults(d.results);
      if (d.status === "completed") {
        clearInterval(pollTimer);
        btn.disabled = false; btn.textContent = "开始分析视频";
        toast(`分析完成，共 ${d.results.length} 条`, "success");
      }
    } catch (e) {
      clearInterval(pollTimer);
      btn.disabled = false; btn.textContent = "开始分析视频";
      toast("轮询失败：" + e.message, "error");
    }
  }, 1500);
}

function updateProgress(done, total) {
  const pct = total ? Math.round((done / total) * 100) : 0;
  $("progressFill").style.width = pct + "%";
  $("progressText").textContent = `${done} / ${total}（${pct}%）`;
}

const SOURCE_LABEL = { llm: "大模型分析", mock: "示例模式", template: "规则模板", error: "失败" };

function renderVideoResults(results) {
  const wrap = $("scriptResult");
  wrap.innerHTML = "";
  if (!results.length) return;

  results.forEach((s, idx) => {
    const src = s.分析来源 || "template";
    // 分镜表
    const shotsRows = (s.分镜 || []).map(sh =>
      `<tr><td>${sh.序号 || ""}</td><td>${sh.时长 || ""}</td>
       <td>${sh.画面 || ""}</td><td>${sh.运镜 || ""}</td><td>${sh.作用 || ""}</td></tr>`).join("");
    // 卖点
    const points = (s.卖点要素 || []).map(p =>
      `<div class="point-item"><b>${p.卖点 || ""}</b> ｜ 呈现：${p.呈现方式 || ""} ｜ 爆款要素：${p.爆款要素 || ""}</div>`).join("")
      || '<div class="meta">（本条未提取到卖点要素）</div>';
    // 模板
    const tpl = s.生产模板 || {};
    const tplPoints = (tpl.拍摄要点 || []).map(x => `<li>${x}</li>`).join("");
    const tplHtml = `
      <div class="template-box">
        <div class="row"><b>适用行业：</b>${tpl.适用行业 || "-"}</div>
        <div class="row"><b>结构公式：</b>${tpl.结构公式 || "-"}</div>
        <div class="row"><b>拍摄要点：</b><ul>${tplPoints}</ul></div>
        <div class="row"><b>可复用文案模板：</b>${tpl.可复用文案模板 || "-"}
          <button class="btn copy-btn" data-copy="${encodeURIComponent(tpl.可复用文案模板 || "")}">复制</button></div>
      </div>`;

    const tip = s.提示 ? `<div class="meta" style="margin-top:6px">ℹ️ ${s.提示}</div>` : "";

    wrap.innerHTML += `
      <div class="script-card">
        <div class="script-head">
          <span class="title">#${idx + 1} ${s.素材}
            <span class="source-badge ${src}">${SOURCE_LABEL[src] || src}</span>
          </span>
          <span class="badges">
            <span>行业：${s.识别行业 || "-"}</span>
            <span>消耗：${s.参考消耗 || "-"}</span>
          </span>
        </div>
        <div class="script-body">
          <div class="script-section">
            <h4>📋 还原分镜</h4>
            <div class="table-wrap"><table class="shot-table">
              <thead><tr><th>序号</th><th>时长</th><th>画面</th><th>运镜</th><th>作用</th></tr></thead>
              <tbody>${shotsRows || '<tr><td colspan="5">无</td></tr>'}</tbody>
            </table></div>
          </div>
          <div class="script-section">
            <h4>🎙️ 口播/字幕文案
              <button class="btn copy-btn" data-copy="${encodeURIComponent(s.口播文案 || "")}">复制全文</button>
            </h4>
            <div class="voiceover">${s.口播文案 || "（无）"}</div>
          </div>
          <div class="script-section">
            <h4>💡 爆款卖点要素拆解</h4>
            ${points}
          </div>
          <div class="script-section">
            <h4>📐 可复用生产模板</h4>
            ${tplHtml}
          </div>
          ${tip}
        </div>
      </div>`;
  });

  wrap.querySelectorAll("[data-copy]").forEach(btn => {
    btn.addEventListener("click", () => {
      navigator.clipboard.writeText(decodeURIComponent(btn.dataset.copy));
      toast("已复制到剪贴板", "success");
    });
  });
}

// ============ 模块③ 混剪工具 ============
async function loadTools() {
  try {
    const res = await fetch(API.tools);
    const data = await res.json();
    const grid = $("toolsGrid");
    grid.innerHTML = "";
    data.tools.forEach(t => {
      const steps = t.steps.map(s => `<li>${s}</li>`).join("");
      grid.innerHTML += `
        <div class="tool-card">
          <h3>${t.name}</h3>
          <span class="tool-tag">${t.tag}</span>
          <p class="tool-desc">${t.desc}</p>
          <ol class="tool-steps">${steps}</ol>
          <a class="btn primary" href="${t.url}" target="_blank" rel="noopener">打开 ${t.name} ↗</a>
        </div>`;
    });
  } catch (e) {
    $("toolsGrid").innerHTML = '<div class="empty-tip">工具列表加载失败</div>';
  }
}
loadTools();
