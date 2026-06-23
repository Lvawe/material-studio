"""
视频素材自动化生产平台 - 后端主服务
FastAPI 提供三个模块的 API + 静态前端托管。
"""
import os
import uuid
import threading

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from analyzer import analyze
import llm_client
import video_analyzer

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

app = FastAPI(title="视频素材自动化生产平台", version="0.1.0")


# ---------- 模块③：混剪工具配置（外链跳转 + 操作指引）----------
# 来源 SOP「采购工具」sheet
MIXING_TOOLS = [
    {
        "name": "剪映",
        "url": "https://www.capcut.cn/",
        "tag": "免费·直播切片·一键混剪",
        "desc": "无门槛免费工具，支持直播切片、模板混剪、一键成片",
        "steps": [
            "打开剪映，导入模块②生成脚本对应的 AI 视频片段",
            "选择『图文成片』或『模板』，套用竖版 9:16 模板",
            "按分镜脚本顺序排列片段，添加口播文案为字幕",
            "导出 30-60s 竖版成片",
        ],
    },
    {
        "name": "妙思",
        "url": "https://www.capcut.cn/",
        "tag": "免费·智能混剪",
        "desc": "优选无门槛免费混剪工具，适合规模化生产",
        "steps": [
            "上传素材片段与口播文案",
            "选择智能混剪模式，自动匹配卡点",
            "微调后导出",
        ],
    },
    {
        "name": "Seko",
        "url": "https://seko.sensetime.com/explore",
        "tag": "AI片段生成·原片一键生成",
        "desc": "商汤 Seko，支持 AI 片段生成与一键成片",
        "steps": ["输入模块②生成的 AI 提示词", "生成片段", "下载用于混剪"],
    },
    {
        "name": "即梦",
        "url": "https://jimeng.jianying.com/ai-tool/home",
        "tag": "AI图生视频",
        "desc": "图生视频片段生成（5s/10s）",
        "steps": ["上传原生图", "粘贴模块②的 AI 提示词", "生成 5s/10s 片段"],
    },
    {
        "name": "可灵",
        "url": "https://app.klingai.com/cn/",
        "tag": "AI图生视频",
        "desc": "快手可灵，高质量图生视频",
        "steps": ["上传原生图 + 提示词", "生成片段", "下载"],
    },
    {
        "name": "海螺",
        "url": "https://hailuoai.com/",
        "tag": "AI图生视频",
        "desc": "MiniMax 海螺 AI 视频生成",
        "steps": ["上传图片 + 提示词", "生成", "下载"],
    },
    {
        "name": "LibLibAI",
        "url": "https://www.liblib.art/",
        "tag": "生图·AI片段生成",
        "desc": "用于原生图生成与 AI 片段制作",
        "steps": ["生成/上传原生图", "图生视频", "下载"],
    },
    {
        "name": "Vidu",
        "url": "https://www.vidu.cn/",
        "tag": "AI图生视频",
        "desc": "生数科技 Vidu 视频生成",
        "steps": ["上传图片 + 提示词", "生成片段", "下载"],
    },
]


class ScriptRequest(BaseModel):
    materials: list
    industry: str = ""
    limit: int = 10


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/analyze")
async def api_analyze(file: UploadFile = File(...), top_n: int = Form(50)):
    """模块①：上传 AData 导出文件，按消耗排序返回 Top N"""
    try:
        content = await file.read()
        result = analyze(content, file.filename, top_n=top_n)
        return JSONResponse(result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析失败：{e}")


# ---------- 模块②：视频分析异步任务 ----------
# 任务存储（内存版，单进程足够；后续可换 Redis）
TASKS = {}
TASKS_LOCK = threading.Lock()


def _run_analyze_task(task_id: str, materials: list, industry: str):
    """后台线程：逐条分析素材，实时更新进度"""
    total = len(materials)
    for i, m in enumerate(materials):
        try:
            res = video_analyzer.analyze_one(m, industry=industry)
        except Exception as e:
            res = {"素材": m.get("素材名称", f"#{i+1}"), "分析来源": "error",
                   "提示": str(e), "分镜": [], "口播文案": "", "卖点要素": [], "生产模板": {}}
        with TASKS_LOCK:
            t = TASKS.get(task_id)
            if t is None or t.get("cancelled"):
                return
            t["done"] = i + 1
            t["results"].append(res)
    with TASKS_LOCK:
        if task_id in TASKS:
            TASKS[task_id]["status"] = "completed"


@app.post("/api/analyze-videos")
def api_analyze_videos(req: ScriptRequest, background: BackgroundTasks):
    """模块②：启动视频分析任务，返回 task_id 供轮询进度"""
    if not req.materials:
        raise HTTPException(status_code=400, detail="素材列表为空，请先在模块①完成分析")
    materials = req.materials[: req.limit]
    task_id = uuid.uuid4().hex[:12]
    with TASKS_LOCK:
        TASKS[task_id] = {
            "status": "running", "total": len(materials),
            "done": 0, "results": [], "industry": req.industry,
        }
    background.add_task(_run_analyze_task, task_id, materials, req.industry)
    return {"task_id": task_id, "total": len(materials),
            "llm_configured": llm_client.is_configured()}


@app.get("/api/analyze-videos/{task_id}")
def api_task_status(task_id: str):
    """轮询任务进度与结果"""
    with TASKS_LOCK:
        t = TASKS.get(task_id)
        if not t:
            raise HTTPException(status_code=404, detail="任务不存在或已过期")
        return {
            "status": t["status"], "total": t["total"], "done": t["done"],
            "industry": t["industry"], "results": t["results"],
        }


@app.get("/api/llm-status")
def api_llm_status():
    """返回 LLM 配置状态，供前端提示"""
    return {
        "configured": llm_client.is_configured(),
        "model": llm_client.LLM_MODEL if llm_client.is_configured() else None,
        "mode": llm_client.ANALYSIS_MODE,
        "mode_label": llm_client.mode_label(),
    }


@app.get("/api/mixing-tools")
def api_mixing_tools():
    """模块③：返回混剪工具列表与操作指引"""
    return {"tools": MIXING_TOOLS}


# ---------- 静态前端托管 ----------
if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
