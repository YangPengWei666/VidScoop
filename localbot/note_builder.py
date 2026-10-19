"""
note_builder.py —— 组装单篇 .md（frontmatter + 元数据 + 字幕/逐字稿 + AI 摘要 + 评论）
文件名：00-Clip/{type}-{标题}.md ；type 由 URL 域名自动识别。
机器人只新增、绝不改现有文件（冲突红线）。
"""
import logging
import os
from datetime import datetime
from localbot import config

log = logging.getLogger("note_builder")


def _fmt_duration(sec: int) -> str:
    if not sec:
        return ""
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _unique_filename(abs_dir: str, stem: str, ext: str = ".md") -> str:
    """同名不覆盖：已存在则追加 -2/-3…（Obsidian 社区通行惯例）。"""
    name = stem + ext
    n = 2
    while os.path.exists(os.path.join(abs_dir, name)):
        name = f"{stem}-{n}{ext}"
        n += 1
    if n > 2:
        log.warning("同名笔记已存在，本篇改名为: %s", name)
    return name


def build(meta: dict, transcript: str, summary: str, comments=None,
          transcript_source: str = None) -> tuple[str, str]:
    """
    返回 (filepath, content)。
    filepath 为相对 KB_REPO_DIR 的路径。
    """
    ctype = config.detect_type(meta.get("webpage_url") or meta.get("url") or "")
    title = meta.get("title") or "未命名"
    safe = config.sanitize_filename(title)
    stem = f"{ctype}-{safe}"
    abs_dir = config.NOTES_DIR
    os.makedirs(abs_dir, exist_ok=True)
    fname = _unique_filename(abs_dir, stem)
    rel = os.path.join("00-Clip", fname)

    today = datetime.now().strftime("%Y-%m-%d")

    # frontmatter：通用字段，不带任何特定笔记库的私有口径
    fm = []
    fm.append("---")
    fm.append(f'title: "{title.replace(chr(34), "' ")}"')
    fm.append("tags: [视频转写]")
    fm.append(f"created: {today}")
    fm.append(f"updated: {today}")
    fm.append(f"type: {ctype}")
    fm.append(f"author: {meta.get('author','未知')}")
    fm.append(f"source_url: {meta.get('webpage_url') or meta.get('url','')}")
    fm.append(f"platform: {ctype}")
    dur = _fmt_duration(meta.get("duration") or 0)
    if dur:
        fm.append(f"duration: {dur}")
    fm.append("ingest_method: localbot")
    if meta.get("video_fingerprint"):
        fm.append(f"video_fingerprint: {meta['video_fingerprint']}")
    fm.append("---")
    frontmatter = "\n".join(fm)

    body = []
    body.append("## 元数据")
    body.append(f"- 作者：{meta.get('author','未知')}")
    body.append(f"- 原链接：{meta.get('webpage_url') or meta.get('url','')}")
    if dur:
        body.append(f"- 时长：{dur}")
    if meta.get("description"):
        body.append(f"- 简介：{meta.get('description')[:2000]}")
    if meta.get("thumbnail"):
        body.append(f"- 封面：{meta.get('thumbnail')}")

    if transcript_source == "subtitle":
        body.append("\n## 字幕（原始文本）")
    elif transcript_source == "whisper_polished":
        body.append("\n## 逐字稿（语音转写 · AI 整理）")
    else:
        body.append("\n## 逐字稿（语音转写）")
    body.append(transcript.strip()[: config.MAX_TRANSCRIPT_CHARS * 3])

    body.append("\n## AI 摘要")
    body.append(summary.strip())

    if comments:
        body.append("\n## 高赞评论")
        for c in comments[: config.COMMENTS_TOP_N]:
            body.append(f"- {c['text']}（赞 {c['likes']}）")

    content = frontmatter + "\n\n" + "\n".join(body) + "\n"
    return rel, content
