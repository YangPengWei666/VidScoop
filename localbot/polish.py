"""
polish.py —— whisper 逐字稿整理（Groq LLM）
作用：加标点、分段落、修正明显同音错词（如 Tree→Trae、promote→prompt）。
设计：长稿分片送审（默认 2800 字/片），单片失败保留该片原文，绝不因整理挂掉而失败入库。
"""
import logging

from localbot import config
from localbot import groq_pool

log = logging.getLogger("polish")

GLOSSARY = (
    "常见语音转写错别字（仅当原音明显指该词时替换，拿不准保留原文）："
    "Tree/Tray/Trei→Trae，Workbody/WordBody→WorkBuddy，promote→prompt，"
    "Obsidium/Absidian→Obsidian，克劳德福→Cloudflare。"
)


def _chunks(text: str, size: int):
    text = text.strip()
    for i in range(0, len(text), size):
        yield text[i:i + size]


def polish(transcript: str) -> str:
    """整理逐字稿；任何失败都只影响对应片段（保留原文），不抛异常。"""
    if not transcript or len(transcript) < 80:
        return transcript
    parts = list(_chunks(transcript, config.POLISH_CHUNK_CHARS))
    out = []
    for i, ch in enumerate(parts, 1):
        prompt = (
            "下面是语音转写得到的视频文字稿片段，请整理：\n"
            "1) 加标点；2) 分出自然段落；3) 修正明显的同音错别字。\n"
            "要求：不要改写句子、不要增删内容、不要加任何评论，"
            "保持原意与口语风格，直接输出整理后的正文。\n"
            + GLOSSARY + "\n\n片段：\n" + ch
        )
        try:
            fixed = groq_pool.chat(
                config.GROQ_LLM_MODEL,
                [{"role": "user", "content": prompt}],
                max_tokens=config.POLISH_MAX_TOKENS,
                temperature=0.1,
            )
            # 防止模型跑飞：长度缩水过半视为异常，保留原文
            if len(fixed) >= len(ch) * 0.4:
                out.append(fixed)
                log.info("整理片段 %d/%d 完成（%d 字）", i, len(parts), len(fixed))
            else:
                log.warning("整理片段 %d 结果异常（过短），保留原文", i)
                out.append(ch)
        except Exception as e:
            log.warning("整理片段 %d 失败，保留原文: %s", i, e)
            out.append(ch)
    return "\n\n".join(out)
