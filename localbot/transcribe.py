"""
transcribe.py —— 音频转文字（无字幕时的兜底）
Groq whisper-large-v3-turbo（免费、本机实测可达），走 groq_pool 双账号轮换。
"""
import logging
import os
from localbot import config
from localbot import groq_pool

log = logging.getLogger("transcribe")


def transcribe(audio_path: str) -> str:
    """返回逐字稿文本；失败抛异常。"""
    if not (config.SILICONFLOW_API_KEY or config.GROQ_API_KEY or config.GROQ_API_KEY_2):
        raise RuntimeError("未配置任何转写渠道 key（SILICONFLOW_API_KEY / GROQ_API_KEY）")
    if not os.path.exists(audio_path):
        raise RuntimeError("音频文件不存在")
    text = groq_pool.transcribe(audio_path, config.GROQ_WHISPER_MODEL)
    if not text:
        raise RuntimeError("whisper 返回空")
    return text
