"""
模块②核心编排：对每条爆款素材执行 视频下载 → 抽帧 → 大模型分析 → 结构化输出。
输出四项：还原分镜、口播文案、卖点要素、生产模板。

对单条素材的处理是健壮的：任一环节失败都会降级（模板/mock），不中断整批任务。
"""
import logging

import video_utils
import llm_client
from script_gen import generate_storyboard  # 旧的规则模板，作为无视频时降级

logger = logging.getLogger(__name__)

# 素材记录里可能存放视频地址/MD5 的列名候选
VIDEO_FIELD_CANDIDATES = [
    "视频URL", "视频url", "视频链接", "视频地址", "video_url", "url",
    "md5", "素材MD5", "素材md5", "视频md5", "resource_signature", "素材签名",
]

NAME_FIELD_CANDIDATES = ["素材名称", "素材名", "标题", "creative_name"]


def _pick(material: dict, candidates: list, default=""):
    for c in candidates:
        for k in material.keys():
            if str(k).strip().lower() == c.strip().lower():
                v = material[k]
                if v not in (None, ""):
                    return v
    return default


def analyze_one(material: dict, industry: str = "") -> dict:
    """
    分析单条素材。返回统一结构：
    {
      素材, 识别行业, 参考消耗, 视频地址, 分析来源(llm/mock/template),
      分镜, 口播文案, 卖点要素, 生产模板, [error]
    }
    """
    name = _pick(material, NAME_FIELD_CANDIDATES, default="未命名素材")
    cost = _pick(material, ["消耗", "竞价消耗", "effect_cost_yuan", "花费"], default="")
    raw_video = _pick(material, VIDEO_FIELD_CANDIDATES, default="")

    # 投放数据上下文（供模型参考）
    ctx = {
        "消耗": cost,
        "点击率": _pick(material, ["点击率", "ctr", "CTR"], ""),
        "3秒完播率": _pick(material, ["3秒完播率", "3s完播率", "video_play_3s_rate"], ""),
        "下单ROI": _pick(material, ["下单ROI", "roi", "204_roi"], ""),
    }

    base = {
        "素材": name,
        "识别行业": industry or "自动识别",
        "参考消耗": cost,
        "视频地址": "",
    }

    if raw_video:
        base["视频地址"] = video_utils.resolve_video_url(raw_video)

    video_path = None
    frames_dir = None
    try:
        frames = None
        # 仅 vision 模式才需要下载视频并抽帧；text 模式直接用元数据推断
        if llm_client.ANALYSIS_MODE == "vision":
            if not raw_video:
                tpl = generate_storyboard(material, industry)
                return _from_template(base, tpl, reason="vision模式但素材无视频地址")
            video_path = video_utils.download_video(base["视频地址"])
            frames = video_utils.extract_frames(video_path)
            frames_dir = frames[0].rsplit("/", 1)[0] if frames else None

        analysis = llm_client.analyze_material(
            material_name=name, industry=industry, extra_context=ctx, frames=frames)

        base.update({
            "分析来源": analysis.get("_source", "llm"),
            "使用模型": analysis.get("_model", ""),
            "分析模式": analysis.get("_mode", llm_client.ANALYSIS_MODE),
            "分镜": analysis.get("分镜", []),
            "口播文案": analysis.get("口播文案", ""),
            "卖点要素": analysis.get("卖点要素", []),
            "生产模板": analysis.get("生产模板", {}),
        })
        if analysis.get("_mock_reason"):
            base["提示"] = analysis["_mock_reason"]
        return base

    except Exception as e:
        logger.warning(f"素材[{name}] 分析失败，降级模板：{e}")
        tpl = generate_storyboard(material, industry)
        return _from_template(base, tpl, reason=f"分析失败：{e}")
    finally:
        video_utils.cleanup(video_path, frames_dir)


def _from_template(base: dict, tpl: dict, reason: str) -> dict:
    """把旧规则模板结果适配成统一结构"""
    base.update({
        "分析来源": "template",
        "提示": reason,
        "分镜": [
            {"序号": s["序号"], "时长": s["时长"], "画面": s["画面描述"],
             "运镜": s["镜头"], "作用": s["类型"]}
            for s in tpl.get("分镜脚本", [])
        ],
        "口播文案": tpl.get("口播文案", ""),
        "卖点要素": [],
        "生产模板": {
            "适用行业": tpl.get("识别行业", ""),
            "结构公式": "钩子(3s)+卖点A+卖点B+场景+CTA",
            "拍摄要点": ["前3秒视觉冲击", "竖版9:16构图干净", "卖点特写呈现"],
            "可复用文案模板": "（基于规则模板，配置LLM后可获得真实视频分析）",
        },
    })
    return base
