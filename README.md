# 视频素材自动化生产平台

服务直营运营团队的视频素材生产工具，串联三个核心模块：

| 模块 | 功能 | 实现状态 |
|------|------|----------|
| ① 爆款素材分析 | 上传 AData 导出的 CSV/Excel，按**消耗**降序展示 Top N 爆款素材 | ✅ 已实现 |
| ② 自动化生产脚本 | 基于爆款素材，自动总结为**分镜脚本 + 口播文案 + AI 生成提示词** | ✅ 已实现 |
| ③ 一键混剪 | 外链跳转剪映/妙思/即梦等工具 + 操作指引 | ✅ 已实现（短期方案） |

> 第一版聚焦跑通完整工作流与可视化，后续迭代接入真实拉数与自建剪辑工具。

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
