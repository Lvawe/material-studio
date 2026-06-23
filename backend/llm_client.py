"""
大模型客户端 - OpenAI 兼容协议
支持多模态（文本 + 图片帧）输入，用于视频内容分析。
未配置 key 或调用失败时降级为 mock，保证 pipeline 可跑通。
"""
import os
import json
import base64
import logging

import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
USE_MOCK = os.getenv("USE_MOCK", "false").lower() == "true"


def is_configured() -> bool:
    """是否具备真实调用条件"""
    return bool(LLM_BASE_URL and LLM_API_KEY) and not USE_MOCK


def _encode_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def analyze_video_frames(frames: list, material_name: str = "", industry: str = "",
                         extra_context: dict = None) -> dict:
    """
    把视频抽帧 + 元信息发给多模态大模型，返回结构化分析。
    frames: 帧图片路径列表
    返回: {分镜, 口播文案, 卖点要素, 生产模板, _source}
    """
    if not is_configured() or not frames:
        return _mock_analysis(material_name, industry, reason="未配置LLM" if not is_configured() else "无帧")

    try:
        return _call_llm(frames, material_name, industry, extra_context or {})
    except Exception as e:
        logger.warning(f"LLM 调用失败，降级 mock：{e}")
        return _mock_analysis(material_name, industry, reason=f"调用失败:{e}")


def _build_prompt(material_name: str, industry: str, ctx: dict) -> str:
    metric_lines = "\n".join(f"- {k}: {v}" for k, v in ctx.items() if v not in ("", None))
    return f"""你是资深短视频广告分析师。下面是一条电商爆款广告视频按时间顺序均匀抽取的若干帧画面。
素材名称：{material_name or '未知'}
所属行业：{industry or '未知'}
{('投放数据：' + chr(10) + metric_lines) if metric_lines else ''}

请基于这些帧，还原并分析这条视频，严格输出 JSON（不要任何额外文字），结构如下：
{{
  "分镜": [
    {{"序号":1, "时长":"0-3s", "画面":"画面内容描述", "运镜":"运镜方式(特写/推拉/环绕/平移等)", "作用":"该镜头作用(钩子/卖点/CTA等)"}}
  ],
  "口播文案": "逐句还原或推测的口播/字幕文案，用换行分隔",
  "卖点要素": [
    {{"卖点":"卖点名", "呈现方式":"如何在画面中呈现的", "爆款要素":"为什么吸引人"}}
  ],
  "生产模板": {{
    "适用行业":"...",
    "结构公式":"如：钩子(3s)+卖点A+卖点B+场景+CTA",
    "拍摄要点":["要点1","要点2"],
    "可复用文案模板":"把口播抽象成可替换的模板"
  }}
}}
注意：分镜按帧的时间顺序合理推断；时长总和控制在30-60s；只输出 JSON。"""


def _call_llm(frames, material_name, industry, ctx) -> dict:
    content = [{"type": "text", "text": _build_prompt(material_name, industry, ctx)}]
    for fp in frames:
        b64 = _encode_image(fp)
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })

    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.4,
        "max_tokens": 2500,
    }
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=120) as client:
        r = client.post(f"{LLM_BASE_URL}/chat/completions", json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()

    text = data["choices"][0]["message"]["content"]
    parsed = _extract_json(text)
    parsed["_source"] = "llm"
    return parsed


def _extract_json(text: str) -> dict:
    """从模型输出中提取 JSON（兼容 ```json 包裹）"""
    t = text.strip()
    if "```" in t:
        # 取第一个代码块内容
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
    if start != -1 and end != -1:
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
