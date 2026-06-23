"""
模块②：自动化生产脚本
把分析得到的爆款素材，总结成可用于 AI 视频生产的「分镜脚本 / 口播脚本 / AI 提示词」。

设计依据 SOP：
- step1 原生图 → step2 AI 图生视频片段（5s/10s）→ step3 混剪
- 每个素材按「卖点 → 镜头呈现方式 ABC」拆解分镜
- 输出三类脚本：分镜脚本、口播文案、AI 生成提示词
"""
import re


# 行业 → 默认卖点维度（来自 SOP，可扩展）
INDUSTRY_SELLING_POINTS = {
    "男装": ["版型剪裁", "面料质感", "细节工艺", "上身效果", "场景搭配"],
    "女装": ["版型显瘦", "面料舒适", "设计细节", "上身气质", "穿搭场景"],
    "厨具": ["不粘性能", "防刮耐用", "材质安全", "易清洁", "使用场景"],
    "美妆": ["上妆效果", "成分功效", "质地肤感", "持妆时长", "使用方法"],
    "珠宝": ["材质光泽", "工艺细节", "佩戴效果", "搭配场景", "品质保障"],
    "食品": ["口感风味", "原料品质", "食用场景", "包装设计", "健康卖点"],
    "日百": ["核心功能", "材质做工", "使用场景", "便捷性", "性价比"],
}

DEFAULT_SELLING_POINTS = ["核心卖点", "外观细节", "使用效果", "适用场景", "品质保障"]

# 镜头呈现方式 ABC（来自 SOP「镜头呈现方式ABC」）
SHOT_PRESENTATIONS = {
    "A": "特写镜头 — 聚焦细节，缓慢推进，突出质感",
    "B": "全景/中景 — 展示整体，环绕或平移运镜",
    "C": "场景化镜头 — 真实使用场景，自然光线，生活化氛围",
}


def _guess_industry(material_name: str, default_industry: str = "") -> str:
    """从素材名/标题里猜测行业"""
    text = str(material_name)
    for ind in INDUSTRY_SELLING_POINTS:
        if ind in text:
            return ind
    return default_industry


def _selling_points_for(industry: str):
    return INDUSTRY_SELLING_POINTS.get(industry, DEFAULT_SELLING_POINTS)


def generate_storyboard(material: dict, industry: str = "") -> dict:
    """
    为单个爆款素材生成分镜脚本。
    material: 分析结果里的一条素材记录（dict）
    返回: 包含分镜、口播、AI提示词的结构
    """
    name = material.get("素材名称") or material.get("素材名") or material.get("标题") \
        or material.get("md5") or material.get("素材md5") or "未命名素材"
    ind = _guess_industry(name, industry)
    points = _selling_points_for(ind)

    # 取消耗作为参考
    cost = material.get("消耗") or material.get("竞价消耗") or material.get("effect_cost_yuan") or ""

    # 构建分镜：开头钩子 + 各卖点分镜 + 结尾CTA
    shots = []
    shots.append({
        "序号": 1,
        "时长": "0-3s",
        "类型": "开场钩子",
        "镜头": SHOT_PRESENTATIONS["A"],
        "画面描述": f"产品主体特写快速入场，制造视觉冲击，3秒内抓住注意力",
        "口播/字幕": f"还在为挑{ind or '好物'}发愁？这一个就够了",
    })

    seq = 2
    for i, point in enumerate(points[:4]):  # 取前4个卖点
        shot_key = ["A", "B", "C"][i % 3]
        shots.append({
            "序号": seq,
            "时长": f"{3 + (seq-2)*5}-{3 + (seq-1)*5}s",
            "类型": f"卖点{i+1}：{point}",
            "镜头": SHOT_PRESENTATIONS[shot_key],
            "画面描述": f"围绕『{point}』展开：{_point_visual(point)}",
            "口播/字幕": f"{point}，{_point_copy(point)}",
        })
        seq += 1

    shots.append({
        "序号": seq,
        "时长": "结尾5s",
        "类型": "行动号召CTA",
        "镜头": SHOT_PRESENTATIONS["B"],
        "画面描述": "产品全景 + 价格/优惠信息卡 + 引导下单动效",
        "口播/字幕": "点击下方链接，限时优惠，手慢无！",
    })

    # 口播全文
    voiceover = "\n".join(f"[{s['时长']}] {s['口播/字幕']}" for s in shots)

    # AI 生成提示词（供即梦/可灵/海螺等图生视频使用）
    ai_prompts = []
    for s in shots:
        ai_prompts.append({
            "分镜": s["序号"],
            "提示词": f"{s['画面描述']}，{s['镜头']}，竖版9:16，构图干净，"
                     f"画面无文字贴纸，电商商品视频风格，光线明亮真实",
        })

    return {
        "素材": name,
        "识别行业": ind or "通用",
        "参考消耗": cost,
        "总时长建议": "30-60s",
        "分镜脚本": shots,
        "口播文案": voiceover,
        "AI生成提示词": ai_prompts,
    }


def _point_visual(point: str) -> str:
    mapping = {
        "版型剪裁": "模特转身展示立体剪裁，腰身线条流畅",
        "面料质感": "手指轻抚面料，特写纹理与垂坠感",
        "细节工艺": "拉链、纽扣、车线特写，体现做工",
        "不粘性能": "煎蛋轻松滑动，无残留",
        "防刮耐用": "金属铲刮擦表面，完好无损",
        "上妆效果": "上妆前后对比，肤色提亮均匀",
    }
    return mapping.get(point, f"多角度展示产品的{point}优势")


def _point_copy(point: str) -> str:
    mapping = {
        "版型剪裁": "上身显瘦不挑人",
        "面料质感": "亲肤透气一整天",
        "细节工艺": "每个细节都讲究",
        "不粘性能": "煎炒不糊好清洗",
        "防刮耐用": "用十年都不花",
    }
    return mapping.get(point, "看得见的好品质")


def batch_generate(materials: list, industry: str = "", limit: int = 10) -> dict:
    """
    批量为 Top 素材生成脚本（默认前 10 条，避免一次过多）。
    """
    results = []
    for m in materials[:limit]:
        results.append(generate_storyboard(m, industry))
    return {
        "count": len(results),
        "industry": industry or "自动识别",
        "scripts": results,
    }
