"""
模块①：爆款素材分析
解析 AData 导出的 Excel/CSV，按消耗降序排序，输出 Top N 素材明细。
"""
import io
import re
import pandas as pd


# 可能的"消耗"列名候选（AData 导出列名不固定，做模糊匹配）
COST_COLUMN_CANDIDATES = [
    "消耗", "竞价消耗", "消耗(元)", "竞价消耗(元)", "花费", "cost",
    "effect_cost_yuan", "总消耗", "广告消耗",
]

# 常见指标列名 → 标准化展示名
METRIC_ALIASES = {
    "md5": ["md5", "素材md5", "素材MD5", "resource_signature", "素材签名", "视频md5"],
    "material_id": ["素材id", "素材ID", "resource_id", "素材编号", "creative_id"],
    "material_name": ["素材名称", "素材名", "标题", "creative_name", "素材标题"],
    "cost": COST_COLUMN_CANDIDATES,
    "ctr": ["ctr", "点击率", "CTR", "点击率(%)"],
    "play_3s_rate": ["3秒完播率", "3s完播率", "video_play_3s_rate", "3秒播放率", "3秒播完率"],
    "conversion_cost": ["转化成本", "综合转化成本", "conversion_cost_mix", "下单成本"],
    "roi": ["roi", "ROI", "下单roi", "下单ROI", "204_roi"],
    "ad_count": ["广告数", "有消耗广告数", "has_cost_ad_count"],
}


def _read_dataframe(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """根据文件名后缀读取为 DataFrame"""
    name = (filename or "").lower()
    if name.endswith(".csv"):
        # AData 导出 CSV 常用 utf-8-sig
        for enc in ("utf-8-sig", "utf-8", "gbk"):
            try:
                return pd.read_csv(io.BytesIO(file_bytes), encoding=enc)
            except (UnicodeDecodeError, Exception):
                continue
        raise ValueError("CSV 文件编码无法识别")
    elif name.endswith(".xlsx") or name.endswith(".xls"):
        return pd.read_excel(io.BytesIO(file_bytes))
    else:
        raise ValueError("仅支持 .csv / .xlsx / .xls 文件")


def _normalize_cost(series: pd.Series) -> pd.Series:
    """把消耗列转成数值（去掉千分位逗号、货币符号等）"""
    def to_num(v):
        if pd.isna(v):
            return 0.0
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v)
        s = re.sub(r"[^\d.\-]", "", s)  # 仅保留数字、小数点、负号
        try:
            return float(s) if s not in ("", "-", ".") else 0.0
        except ValueError:
            return 0.0
    return series.apply(to_num)


def _match_column(columns, candidates):
    """在 columns 中模糊匹配候选名（忽略大小写和空格）"""
    norm_cols = {str(c).strip().lower(): c for c in columns}
    # 精确匹配优先
    for cand in candidates:
        key = cand.strip().lower()
        if key in norm_cols:
            return norm_cols[key]
    # 包含匹配
    for cand in candidates:
        key = cand.strip().lower()
        for nc, orig in norm_cols.items():
            if key in nc or nc in key:
                return orig
    return None


def analyze(file_bytes: bytes, filename: str, top_n: int = 50) -> dict:
    """
    主分析函数。
    返回:
      {
        "total": 总行数,
        "cost_column": 识别到的消耗列原始名,
        "columns": 原始列名列表,
        "metric_mapping": 识别到的标准指标 → 原始列名,
        "top": [ {row...}, ... ]  # 按消耗降序的 Top N
        "summary": { 消耗合计, 平均ctr 等概览 }
      }
    """
    df = _read_dataframe(file_bytes, filename)
    df = df.dropna(how="all")  # 去掉全空行
    if df.empty:
        raise ValueError("文件中没有有效数据")

    columns = [str(c) for c in df.columns]

    # 识别各标准指标对应的真实列名
    metric_mapping = {}
    for std_key, aliases in METRIC_ALIASES.items():
        col = _match_column(df.columns, aliases)
        if col is not None:
            metric_mapping[std_key] = str(col)

    cost_col = metric_mapping.get("cost")
    if cost_col is None:
        raise ValueError(
            f"未能识别出『消耗』列。当前列：{columns}。"
            "请确认导出文件包含消耗相关列（如『消耗』『竞价消耗』『effect_cost_yuan』）。"
        )

    # 标准化消耗并排序
    df["_cost_num"] = _normalize_cost(df[cost_col])
    df_sorted = df.sort_values("_cost_num", ascending=False).reset_index(drop=True)

    top_df = df_sorted.head(top_n).copy()
    top_df.insert(0, "排名", range(1, len(top_df) + 1))

    # 概览统计
    summary = {
        "素材总数": int(len(df)),
        "消耗合计": round(float(df["_cost_num"].sum()), 2),
        "Top消耗合计": round(float(top_df["_cost_num"].sum()), 2),
        "最高单素材消耗": round(float(df["_cost_num"].max()), 2),
    }
    if "ctr" in metric_mapping:
        try:
            summary["平均CTR"] = round(float(pd.to_numeric(
                df[metric_mapping["ctr"]].astype(str).str.replace("%", ""),
                errors="coerce").mean()), 4)
        except Exception:
            pass

    # 输出列：把内部辅助列去掉
    out_df = top_df.drop(columns=["_cost_num"])
    # NaN → 空字符串，便于 JSON 序列化
    out_df = out_df.where(pd.notna(out_df), "")
    records = out_df.to_dict(orient="records")

    return {
        "total": int(len(df)),
        "top_n": int(len(top_df)),
        "cost_column": str(cost_col),
        "columns": columns,
        "metric_mapping": metric_mapping,
        "summary": summary,
        "top": records,
    }
