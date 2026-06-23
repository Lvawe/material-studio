"""
大模型客户端 - 通过 claude-internal CLI（Claude Code Internal）进行多模态分析。

合规说明：
本模块使用腾讯官方提供的 `claude-internal` 命令行工具的非交互模式（-p）进行调用，
这是文档明确支持的用法（CODEBUDDY_API_KEY + claude-internal -p）。
不逆向、不直连平台模型 HTTP 接口，符合平台合规要求。

工作方式：
  抽帧图片 → 复制到临时工作目录 → 调用 `claude-internal -p` 读图分析 → 解析返回 JSON
未配置 key / CLI 不可用 / 调用失败时降级为 mock，保证 pipeline 可跑通。
"""
import os
import re
import json
import shutil
import logging
import subprocess
import tempfile

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

CODEBUDDY_API_KEY = os.getenv("CODEBUDDY_API_KEY", "") or os.getenv("LLM_API_KEY", "")
CLAUDE_CLI = os.getenv("CLAUDE_CLI_PATH", "claude-internal")
CLI_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "180"))
USE_MOCK = os.getenv("USE_MOCK", "false").lower() == "true"

_cli_path_cache = None


def _find_cli():
    """查找 claude-internal 可执行文件路径"""
    global _cli_path_cache
    if _cli_path_cache is not None:
        return _cli_path_cache
    path = shutil.which(CLAUDE_CLI)
    _cli_path_cache = path or ""
    return _cli_path_cache


def is_configured() -> bool:
    """是否具备真实调用条件：有 key + CLI 可用 + 未强制 mock"""
    return bool(CODEBUDDY_API_KEY) and bool(_find_cli()) and not USE_MOCK


def analyze_video_frames(frames: list, material_name: str = "", industry: str = "",
                         extra_context: dict = None) -> dict:
    """
    把视频抽帧 + 元信息交给 claude-internal 分析，返回结构化结果。
    frames: 帧图片路径列表
    """
    if not is_configured() or not frames:
        reason = "未配置CODEBUDDY_API_KEY或CLI不可用" if not is_configured() else "无帧"
        return _mock_analysis(material_name, industry, reason=reason)

    try:
        return _call_cli(frames, material_name, industry, extra_context or {})
    except Exception as e:
        logger.warning(f"claude-internal 调用失败，降级 mock：{e}")
        return _mock_analysis(material_name, industry, reason=f"调用失败:{e}")


def _build_prompt(frame_names: list, material_name: str, industry: str, ctx: dict) -> str:
    metric_lines = "\n".join(f"- {k}: {v}" for k, v in ctx.items() if v not in ("", None))
    frame_list = "、".join(frame_names)
    return f"""请读取当前目录下这些按视频时间顺序抽取的帧图片：{frame_list}

这是一条电商爆款广告视频的关键帧。
素材名称：{material_name or '未知'}
所属行业：{industry or '未知'}
{('投放数据：' + chr(10) + metric_lines) if metric_lines else ''}

请基于这些帧，还原并分析这条视频，**只输出一个 JSON**（不要任何解释文字、不要 markdown 代码块标记），结构如下：
{{
  "分镜": [
    {{"序号":1, "时长":"0-3s", "画面":"画面内容描述", "运镜":"运镜方式(特写/推拉/环绕/平移等)", "作用":"该镜头作用(钩子/卖点/CTA等)"}}
  ],
  "口播文案": "逐句还原或推测的口播/字幕文案，用\\n分隔",
  "卖点要素": [
    {{"卖点":"卖点名", "呈现方式":"如何在画面中呈现", "爆款要素":"为什么吸引人"}}
  ],
  "生产模板": {{
    "适用行业":"...",
    "结构公式":"如：钩子(3s)+卖点A+卖点B+场景+CTA",
    "拍摄要点":["要点1","要点2"],
    "可复用文案模板":"把口播抽象成可替换的模板"
  }}
}}
要求：分镜按帧时间顺序合理推断；总时长30-60s；直接输出 JSON，不要包含任何其它文字。"""


def _call_cli(frames, material_name, industry, ctx) -> dict:
    """在临时目录里放帧图，调用 claude-internal -p 分析"""
    work_dir = tempfile.mkdtemp(prefix="cc_analyze_")
    try:
        # 复制帧到工作目录，用简单文件名
        frame_names = []
        for i, fp in enumerate(frames, 1):
            name = f"frame_{i:02d}.jpg"
            shutil.copy(fp, os.path.join(work_dir, name))
            frame_names.append(name)

        prompt = _build_prompt(frame_names, material_name, industry, ctx)

        env = os.environ.copy()
        env["CODEBUDDY_API_KEY"] = CODEBUDDY_API_KEY
        # 避免读取到 ANTHROPIC_API_KEY 导致校验冲突（文档 FAQ 提及）
        env.pop("ANTHROPIC_API_KEY", None)

        cli = _find_cli()
        result = subprocess.run(
            [cli, "-p", "--output-format", "json",
             "--dangerously-skip-permissions", prompt],
            cwd=work_dir, env=env, capture_output=True, text=True, timeout=CLI_TIMEOUT,
        )
        if result.returncode != 0:
            raise RuntimeError(f"CLI 退出码 {result.returncode}: {result.stderr[-200:]}")

        # --output-format json 返回外层信封，真正回答在 result 字段
        envelope = json.loads(result.stdout.strip())
        if envelope.get("is_error"):
            raise RuntimeError(f"CLI 返回错误: {envelope.get('result', '')[:200]}")
        answer = envelope.get("result", "")
        if not answer:
            raise RuntimeError("CLI 返回空 result")

        parsed = _extract_json(answer)
        parsed["_source"] = "llm"
        return parsed
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _extract_json(text: str) -> dict:
    """从模型输出中提取 JSON（兼容 ```json 包裹或前后有说明文字）"""
    t = text.strip()
    if "```" in t:
        parts = t.split("```")
        for p in parts:
            p = p.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            if p.startswith("{"):
                t = p
                break
    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        t = t[start:end + 1]
    return json.loads(t)


def _mock_analysis(material_name: str, industry: str, reason: str = "") -> dict:
    """降级示例结果，保证流程可跑通"""
    ind = industry or "通用"
    return {
        "分镜": [
            {"序号": 1, "时长": "0-3s", "画面": f"{material_name or '产品'}主体特写快速入场",
             "运镜": "快速推近", "作用": "开场钩子"},
            {"序号": 2, "时长": "3-12s", "画面": "核心卖点细节展示", "运镜": "特写环绕", "作用": "卖点1"},
            {"序号": 3, "时长": "12-22s", "画面": "使用场景演示", "运镜": "中景平移", "作用": "卖点2/场景"},
            {"序号": 4, "时长": "22-30s", "画面": "价格优惠卡+引导下单", "运镜": "全景定格", "作用": "CTA"},
        ],
        "口播文案": f"还在为挑{ind}发愁？\n这一个细节就够打动你\n真实场景实测效果\n点击下方，限时优惠！",
        "卖点要素": [
            {"卖点": "核心功能", "呈现方式": "特写+实测画面", "爆款要素": "前3秒强冲击留住用户"},
            {"卖点": "使用场景", "呈现方式": "生活化场景演示", "爆款要素": "代入感强易转化"},
        ],
        "生产模板": {
            "适用行业": ind,
            "结构公式": "钩子(3s)+卖点A特写+卖点B场景+CTA",
            "拍摄要点": ["前3秒必须有视觉冲击", "竖版9:16构图干净", "卖点用特写+实测呈现"],
            "可复用文案模板": "还在为{痛点}发愁？{产品}帮你{核心利益}，点击下方限时优惠！",
        },
        "_source": "mock",
        "_mock_reason": reason,
    }


# 兼容旧引用：暴露一个 LLM_MODEL 名称供前端状态展示
LLM_MODEL = os.getenv("LLM_MODEL", "claude-internal")
LLM_BASE_URL = "claude-internal-cli"  # 标记为 CLI 模式
