"""
视频处理工具：根据 MD5/URL 下载视频，并用 ffmpeg 均匀抽帧。
"""
import os
import re
import shutil
import logging
import subprocess
import tempfile

import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# 视频 URL 模板：当明细里只有 MD5 时，用此模板拼出可下载地址。
# {md5} 会被替换为素材 MD5。可在 .env 中通过 VIDEO_URL_TEMPLATE 覆盖。
VIDEO_URL_TEMPLATE = os.getenv("VIDEO_URL_TEMPLATE", "")
FRAME_COUNT = int(os.getenv("FRAME_COUNT", "8"))

WORK_DIR = os.path.join(tempfile.gettempdir(), "material_studio_video")
os.makedirs(WORK_DIR, exist_ok=True)


def resolve_video_url(md5_or_url: str) -> str:
    """
    把 MD5 或 URL 解析为可下载的视频地址。
    - 已是 http(s) URL：直接返回
    - 是 MD5：用 VIDEO_URL_TEMPLATE 拼接（未配置则原样返回，留待上层判断）
    """
    s = str(md5_or_url).strip()
    if s.startswith("http://") or s.startswith("https://"):
        return s
    if VIDEO_URL_TEMPLATE and "{md5}" in VIDEO_URL_TEMPLATE:
        return VIDEO_URL_TEMPLATE.replace("{md5}", s)
    return s  # 无模板，原样返回


def download_video(url: str, dest_dir: str = WORK_DIR) -> str:
    """下载视频到本地，返回本地路径。失败抛异常。"""
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError(f"无效的视频地址（需要可下载的 URL，当前为：{url[:60]}）。"
                         f"若明细里只有 MD5，请在 .env 配置 VIDEO_URL_TEMPLATE。")

    safe = re.sub(r"[^\w.-]", "_", url.split("/")[-1].split("?")[0]) or "video"
    if not os.path.splitext(safe)[1]:
        safe += ".mp4"
    local_path = os.path.join(dest_dir, safe)

    with httpx.Client(timeout=120, follow_redirects=True) as client:
        with client.stream("GET", url) as r:
            r.raise_for_status()
            with open(local_path, "wb") as f:
                for chunk in r.iter_bytes(chunk_size=65536):
                    f.write(chunk)
    if os.path.getsize(local_path) < 1024:
        raise ValueError("下载的视频文件过小，可能地址无效或无权限")
    return local_path


def extract_frames(video_path: str, count: int = None, out_dir: str = None) -> list:
    """
    用 ffmpeg 均匀抽取 count 帧，返回帧图片路径列表。
    """
    count = count or FRAME_COUNT
    out_dir = out_dir or os.path.join(WORK_DIR, "frames_" +
                                      os.path.splitext(os.path.basename(video_path))[0])
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    duration = _get_duration(video_path)
    frames = []

    if duration and duration > 0:
        # 均匀时间点抽帧
        interval = duration / (count + 1)
        for i in range(1, count + 1):
            ts = interval * i
            out_path = os.path.join(out_dir, f"frame_{i:02d}.jpg")
            cmd = ["ffmpeg", "-y", "-ss", f"{ts:.2f}", "-i", video_path,
                   "-frames:v", "1", "-q:v", "3", "-vf", "scale=512:-1", out_path]
            _run(cmd)
            if os.path.isfile(out_path):
                frames.append(out_path)
    else:
        # 拿不到时长，用 fps 滤镜兜底
        out_pattern = os.path.join(out_dir, "frame_%02d.jpg")
        cmd = ["ffmpeg", "-y", "-i", video_path,
               "-vf", f"fps=1,scale=512:-1", "-frames:v", str(count), out_pattern]
        _run(cmd)
        frames = sorted(
            os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.endswith(".jpg"))

    if not frames:
        raise ValueError("抽帧失败，未生成任何帧图片")
    return frames


def _get_duration(video_path: str):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, timeout=30)
        return float(out.stdout.strip())
    except Exception:
        return None


def _run(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if res.returncode != 0:
        logger.warning(f"ffmpeg 命令异常: {res.stderr[-300:]}")
    return res


def cleanup(*paths):
    """清理临时文件/目录"""
    for p in paths:
        try:
            if p and os.path.isfile(p):
                os.remove(p)
            elif p and os.path.isdir(p):
                shutil.rmtree(p)
        except Exception:
            pass
