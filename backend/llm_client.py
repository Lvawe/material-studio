"""
大模型客户端 - 通过 claude-internal CLI（Claude Code Internal）进行分析。

合规说明：
使用腾讯官方 `claude-internal` 命令行工具的非交互模式（-p），文档明确支持
（CODEBUDDY_API_KEY + claude-internal -p）。不逆向、不直连平台模型 HTTP 接口。

两种分析模式（ANALYSIS_MODE）：
  - text  ：基于「素材名称 + 行业 + AData 投放数据」用内部文本模型生成策略性脚本。
            非交互模式内部模型为文本模型（GLM/DeepSeek 等），无视觉能力，故走文本推断。
  - vision：抽帧 → 多模态读图分析（需要真正支持图片的视觉模型，待视觉 API 到位后启用）。

未配置 key / CLI 不可用 / 调用失败时降级为 mock，保证 pipeline 可跑通。
"""
import os
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
CLI_MODEL = os.getenv("LLM_MODEL", "").strip()                    # 主模型
CLI_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "").strip()  # 回退模型
USE_MOCK = os.getenv("USE_MOCK", "false").lower() == "true"
# 分析模式：text（文本推断，当前默认） / vision（读图，需视觉API）
ANALYSIS_MODE = os.getenv("ANALYSIS_MODE", "text").strip().lower()

_cli_path_cache = None


def _find_cli():
    global _cli_path_cache
    if _cli_path_cache is not None:
        return _cli_path_cache
    _cli_path_cache = shutil.which(CLAUDE_CLI) or ""
    return _cli_path_cache


def is_configured() -> bool:
    """是否具备真实调用条件：有 key + CLI 可用 + 未强制 mock"""
    return bool(CODEBUDDY_API_KEY) and bool(_find_cli()) and not USE_MOCK


def _model_chain():
    chain = []
    if CLI_MODEL:
        chain.append(CLI_MODEL)
    if CLI_FALLBACK_MODEL and CLI_FALLBACK_MODEL not in chain:
        chain.append(CLI_FALLBACK_MODEL)
    return chain or [""]


# ============================================================
#  对外主入口
# ============================================================
def analyze_material(material_name: str = "", industry: str = "",
                     extra_context: dict = None, frames: list = None) -> dict:
    """
    统一分析入口。根据 ANALYSIS_MODE 选择文本/视觉模式。
    text 模式：忽略 frames，基于元数据+投放数据推断。
    vision 模式：使用 frames 读图分析。
    """
    if not is_configured():
        return _mock_analysis(material_name, industry,
                              reason="未配置CODEBUDDY_API_KEY或CLI不可用")

    ctx = extra_context or {}
    last_err = None
    for model in _model_chain():
        try:
            if ANALYSIS_MODE == "vision":
                if not frames:
                    raise RuntimeError("vision 模式需要视频帧")
                result = _call_cli_vision(frames, material_name, industry, ctx, model=model)
            else:
                result = _call_cli_text(material_name, industry, ctx, model=model)
            result["_model"] = model or "default"
            result["_mode"] = ANALYSIS_MODE
            return result
        except Exception as e:
            last_err = e
            logger.warning(f"模型[{model or 'default'}]分析失败：{e}，尝试下一个...")
    logger.warning(f"全部模型均失败，降级 mock：{last_err}")
    return _mock_analysis(material_name, industry, reason=f"调用失败:{last_err}")


# 兼容旧接口名
def analyze_video_frames(frames: list, material_name: str = "", industry: str = "",
                         extra_context: dict = None) -> dict:
    return analyze_material(material_name, industry, extra_context, frames=frames)


# ============================================================
#  文本模式（方案 C）
# ============================================================
def _build_text_prompt(material_name: str, industry: str, ctx: dict) -> str:
    metric_lines = "\n".join(f"- {k}: {v}" for k, v in ctx.items() if v not in ("", None))
    return f"""你是资深电商短视频广告策划。基于以下爆款素材的元数据与投放表现，为运营团队产出一条可复用的视频生产脚本。

素材名称：{material_name or '未知'}
所属行业：{industry or '未知'}
{('投放数据：' + chr(10) + metric_lines) if metric_lines else ''}

请结合该行业的爆款规律与上述投放数据（消耗高说明该素材有效，可重点参考其打法），
设计一条 30-60s 的竖版带货视频脚本。**只输出一个 JSON**（不要解释、不要 markdown 代码块），结构如下：
{{
  "分镜": [
    {{"序号":1, "时长":"0-3s", "画面":"建议画面内容", "运镜":"运镜方式(特写/推拉/环绕/平移等)", "作用":"该镜头作用(钩子/卖点/CTA等)"}}
  ],
  "口播文案": "完整口播/字幕文案，用\\n分隔每句",
  "卖点要素": [
    {{"卖点":"卖点名", "呈现方式":"建议如何在画面中呈现", "爆款要素":"为什么能吸引用户"}}
  ],
  "生产模板": {{
    "适用行业":"...",
    "结构公式":"如：钩子(3s)+卖点A+卖点B+场景+CTA",
    "拍摄要点":["要点1","要点2"],
    "可复用文案模板":"把口播抽象成可替换变量的模板"
  }}
}}
要求：分镜 4-7 个，时长合理；贴合行业特性；直接输出 JSON。"""


def _call_cli_text(material_name, industry, ctx, model="") -> dict:
    prompt = _build_text_prompt(material_name, industry, ctx)
    answer = _run_cli(prompt, cwd=None, model=model)
    parsed = _extract_json(answer)
    if not isinstance(parsed, dict) or "分镜" not in parsed:
        raise RuntimeError("模型输出不含预期结构")
    parsed["_source"] = "llm"
    return parsed


# ============================================================
#  视觉模式（方案 B，待视觉 API 到位启用）
# ============================================================
def _build_vision_prompt(frame_names: list, material_name: str, industry: str, ctx: dict) -> str:
    metric_lines = "\n".join(f"- {k}: {v}" for k, v in ctx.items() if v not in ("", None))
    frame_list = "、".join(frame_names)
    return f"""请用 Read 工具逐个打开当前目录下的图片：{frame_list}
这些是同一条电商广告视频按时间顺序抽取的关键帧（第一张开头、最后一张结尾）。

素材名称：{material_name or '未知'}
所属行业：{industry or '未知'}
{('投放数据：' + chr(10) + metric_lines) if metric_lines else ''}

看完全部帧后还原并分析视频，**只输出一个 JSON**：
{{
  "分镜": [{{"序号":1, "时长":"0-3s", "画面":"画面描述", "运镜":"运镜方式", "作用":"镜头作用"}}],
  "口播文案": "逐句还原文案，用\\n分隔",
  "卖点要素": [{{"卖点":"...", "呈现方式":"...", "爆款要素":"..."}}],
  "生产模板": {{"适用行业":"...","结构公式":"...","拍摄要点":["..."],"可复用文案模板":"..."}}
}}
直接输出 JSON，不要其它文字。"""


def _call_cli_vision(frames, material_name, industry, ctx, model="") -> dict:
    work_dir = tempfile.mkdtemp(prefix="cc_analyze_")
    try:
        frame_names = []
        for i, fp in enumerate(frames, 1):
            name = f"frame_{i:02d}.jpg"
            shutil.copy(fp, os.path.join(work_dir, name))
            frame_names.append(name)
        prompt = _build_vision_prompt(frame_names, material_name, industry, ctx)
        answer = _run_cli(prompt, cwd=work_dir, model=model)
        parsed = _extract_json(answer)
        if not isinstance(parsed, dict) or "分镜" not in parsed:
            raise RuntimeError("模型输出不含预期结构（可能未读图）")
        parsed["_source"] = "llm"
        return parsed
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ============================================================
#  CLI 调用底座
# ============================================================
def _run_cli(prompt: str, cwd=None, model="") -> str:
    """调用 claude-internal -p，返回 result 文本。空/错误时抛异常。"""
    env = os.environ.copy()
    env["CODEBUDDY_API_KEY"] = CODEBUDDY_API_KEY
    env.pop("ANTHROPIC_API_KEY", None)

    cli = _find_cli()
    cmd = [cli, "-p", "--output-format", "json", "--dangerously-skip-permissions"]
    if model:
        cmd += ["--model", model]
    cmd.append(prompt)

    result = subprocess.run(
        cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=CLI_TIMEOUT,
    )
    if result.returncode != 0:
        raise RuntimeError(f"CLI 退出码 {result.returncode}: {result.stderr[-200:]}")
    raw = result.stdout.strip()
    if not raw:
        raise RuntimeError("CLI stdout 为空")
    envelope = json.loads(raw)
    if envelope.get("is_error"):
        raise RuntimeError(f"CLI 返回错误: {envelope.get('result', '')[:200]}")
    answer = (envelope.get("result") or "").strip()
    if not answer:
        raise RuntimeError("CLI 返回空 result")
    return answer


def _extract_json(text: str) -> dict:
    """从模型输出中提取 JSON（兼容 ```json 包裹或前后有说明文字）"""
    t = text.strip()
    if "```" in t:
        for p in t.split("```"):
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


# 供前端状态展示
def mode_label() -> str:
    return "文本推断(内部模型)" if ANALYSIS_MODE != "vision" else "视觉读图"


LLM_MODEL = (CLI_MODEL or "claude-internal默认") + \
    (f" + 回退:{CLI_FALLBACK_MODEL}" if CLI_FALLBACK_MODEL else "")
LLM_BASE_URL = "claude-internal-cli"
