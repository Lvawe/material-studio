// ============ 全局状态 ============
const state = {
  file: null,
  analyzeResult: null,   // 模块①结果
};

const API = {
  analyze: "/api/analyze",
  generate: "/api/generate-scripts",
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

// ============ 模块② 生成脚本 ============
$("genScriptBtn").addEventListener("click", async () => {
  if (!state.analyzeResult || !state.analyzeResult.top.length) {
    toast("请先在模块①完成素材分析", "error");
    switchTab("tab-analyze");
    return;
  }
  const btn = $("genScriptBtn");
  btn.disabled = true; btn.textContent = "生成中...";
  try {
    const res = await fetch(API.generate, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        materials: state.analyzeResult.top,
        industry: $("industrySelect").value,
        limit: parseInt($("scriptLimit").value) || 5,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "生成失败");
    renderScripts(data);
    toast("已生成 " + data.count + " 套脚本", "success");
  } catch (err) {
    toast(err.message, "error");
  } finally {
    btn.disabled = false; btn.textContent = "生成脚本";
  }
});

function renderScripts(data) {
  const wrap = $("scriptResult");
  wrap.innerHTML = "";
  if (!data.scripts.length) {
    wrap.innerHTML = '<div class="empty-tip">无脚本</div>';
    return;
  }
  data.scripts.forEach((s, idx) => {
    const shotsRows = s.分镜脚本.map(sh =>
      `<tr><td>${sh.序号}</td><td>${sh.时长}</td><td>${sh.类型}</td>
       <td>${sh.画面描述}</td><td>${sh["口播/字幕"]}</td></tr>`).join("");
    const prompts = s.AI生成提示词.map(p =>
      `<div class="prompt-item"><b>分镜${p.分镜}</b>：${p.提示词}
       <button class="btn copy-btn" data-copy="${encodeURIComponent(p.提示词)}">复制</button></div>`).join("");

    wrap.innerHTML += `
      <div class="script-card">
        <div class="script-head">
          <span class="title">#${idx + 1} ${s.素材}</span>
          <span class="badges">
            <span>行业：${s.识别行业}</span>
            <span>消耗：${s.参考消耗 || "-"}</span>
            <span>时长：${s.总时长建议}</span>
          </span>
        </div>
        <div class="script-body">
          <div class="script-section">
            <h4>📋 分镜脚本</h4>
            <div class="table-wrap"><table class="shot-table">
              <thead><tr><th>序号</th><th>时长</th><th>类型</th><th>画面描述</th><th>口播/字幕</th></tr></thead>
              <tbody>${shotsRows}</tbody>
            </table></div>
          </div>
          <div class="script-section">
            <h4>🎙️ 口播文案
              <button class="btn copy-btn" data-copy="${encodeURIComponent(s.口播文案)}">复制全文</button>
            </h4>
            <div class="voiceover">${s.口播文案}</div>
          </div>
          <div class="script-section">
            <h4>🤖 AI 生成提示词（图生视频用）</h4>
            ${prompts}
          </div>
        </div>
      </div>`;
  });

  // 绑定复制按钮
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
