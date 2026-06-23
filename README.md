# 视频素材自动化生产平台

服务直营运营团队的视频素材生产工具，串联三个核心模块：

| 模块 | 功能 | 实现状态 |
|------|------|----------|
| ① 爆款素材分析 | 上传 AData 导出的 CSV/Excel，按**消耗**降序展示 Top N 爆款素材 | ✅ 已实现 |
| ② 自动化生产脚本 | 逐条**下载视频 → 抽帧 → 大模型分析**，输出**还原分镜 + 口播文案 + 卖点要素拆解 + 可复用生产模板** | ✅ 已实现（视频分析版） |
| ③ 一键混剪 | 外链跳转剪映/妙思/即梦等工具 + 操作指引 | ✅ 已实现（短期方案） |

> 聚焦跑通完整工作流与可视化，后续迭代接入真实拉数与自建剪辑工具。

---

## 模块② 大模型视频分析

工作流：素材明细中的 **视频URL/MD5** → 下载视频 → ffmpeg 均匀抽帧 → 多模态大模型分析 → 结构化输出四项。

### 大模型调用方式（合规）

模块② 通过腾讯官方 **`claude-internal`（Claude Code Internal）CLI 非交互模式** 进行多模态图片分析，
这是平台文档明确支持的用法（`CODEBUDDY_API_KEY` + `claude-internal -p`），**不逆向、不直连平台模型 HTTP 接口**，符合合规要求。

调用链：抽帧图片 → 复制到临时目录 → `claude-internal -p --output-format json` 读图分析 → 解析 `result` 字段中的业务 JSON。

### 配置（启用真实分析）

1. 安装 `claude-internal`（若未安装）：
   ```bash
   npm install -g --registry=https://mirrors.tencent.com/npm @tencent/claude-code-internal
   ```
2. 复制 `.env.example` 为 `.env`，填写：
   - `CODEBUDDY_API_KEY`：从 CodeBuddy API Key 管理页获取
   - `VIDEO_URL_TEMPLATE`：若明细只有 MD5，配置如 `https://cdn.xxx.com/{md5}.mp4`
3. 安装 ffmpeg（`brew install ffmpeg`）
4. 重启服务

> **未配置 / CLI 不可用时**：自动降级为 mock 示例，保证流程可演示。前端有横幅提示。
> **健壮性**：单条素材下载/抽帧/分析任一失败都会降级，不中断整批任务。
> **性能**：每条视频分析约 30-60s（含模型读图推理）。

### 模块② API（异步任务）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/analyze-videos` | 提交分析任务（json: materials, industry, limit），返回 task_id |
| GET  | `/api/analyze-videos/{task_id}` | 轮询进度与结果 |
| GET  | `/api/llm-status` | 查询 LLM 配置状态 |

### 依赖
- **claude-internal**（Claude Code Internal CLI，多模态分析）
- **ffmpeg / ffprobe**（视频抽帧，需系统安装）
- httpx（下载视频）

---

## 为什么模块①是"上传文件"而不是自动拉数？

AData 站点（`adata.woa.com`）已对 **AI Agent 访问做安全拦截**（返回 403 + 拦截页），
API 调用和 Playwright 浏览器自动化均被拦截。因此当前采用**手动导出上传**方案：

1. 在浏览器打开 AData 报表
2. 点击「下载数据」导出 CSV/Excel
3. 上传到本平台分析

> 待申请白名单（`https://iwiki.woa.com/p/4019801921`）后，可在后续版本接入自动拉数。

---

## 技术栈

- 后端：Python 3.9+ / FastAPI / pandas / openpyxl
- 前端：原生 HTML + CSS + JavaScript（无构建依赖）

## 目录结构

```
material-studio/
├── backend/
│   ├── main.py          # FastAPI 主服务 + 路由 + 混剪工具配置
│   ├── analyzer.py      # 模块① 素材分析（解析+排序）
│   └── script_gen.py    # 模块② 脚本生成
├── frontend/
│   ├── index.html       # 三 Tab 界面
│   ├── style.css
│   └── app.js
├── requirements.txt
└── README.md
```

## 快速启动

```bash
cd material-studio

# 1. 安装依赖（建议虚拟环境）
pip3 install -r requirements.txt

# 2. 启动服务
cd backend
python3 main.py
# 或： uvicorn main:app --reload --port 8000

# 3. 浏览器打开
open http://127.0.0.1:8000
```

## 使用流程

1. **模块①**：上传 AData 导出文件 → 设置 Top N → 开始分析 → 查看按消耗排序的爆款素材
2. 点击「用这批素材生成脚本」→ 跳转模块②
3. **模块②**：选择行业 + 数量 → 生成脚本 → 复制口播/提示词
4. **模块③**：选择混剪工具 → 按指引带入素材完成成片

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/analyze` | 上传文件分析（form: file, top_n） |
| POST | `/api/generate-scripts` | 生成脚本（json: materials, industry, limit） |
| GET  | `/api/mixing-tools` | 获取混剪工具列表 |

## 后续迭代方向

- [ ] AData 白名单申请通过后接入自动拉数（复用 `adata-reader` skill）
- [ ] 模块② 接入大模型 API，生成更智能的卖点提炼与脚本
- [ ] 模块③ 自建后端剪辑工具，替代外链
- [ ] 增加用户体系与 token 计费（对应第二阶段规模化）
