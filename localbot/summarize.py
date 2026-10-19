"""
summarize.py —— 用 LLM 产出结构化摘要/章节/标签
策略：OmniRoute 网关为可选增强（仅在配置了 OMNIROUTE_API_KEY 时启用，自带 fallback + 仪表盘）；
      默认主用 Groq 直连（qwen3.8 中文 + 已在新加坡服务器实测可用），稳定且零额外配置。
两者都是 OpenAI 兼容接口，便于切换。
"""
import logging
from localbot import config
from localbot import groq_pool

log = logging.getLogger("summarize")

SYSTEM_PROMPT = (
    "你是一个中文知识库助手。用户会给你一段视频/音频的标题、作者、描述、"
    "逐字稿（或字幕）以及高赞评论。请输出结构化的中文笔记，严格使用以下 Markdown 结构：\n"
    "## 一句话总结\n（30字内）\n"
    "## 核心要点\n（3-6 条，每条一行，用 - 开头）\n"
    "## 关键观点/金句\n（提炼 1-3 句值得记住的话）\n"
    "## 章节脉络\n（若内容较长，按时间或逻辑给出 3-8 个小标题与一句话说明）\n"
    "## 标签建议\n（5-10 个逗号分隔的中文标签，便于检索）\n"
    "不要输出额外解释，只输出上述结构。"
)


def _build_user(meta: dict, transcript: str, comments) -> str:
    parts = []
    parts.append(f"标题：{meta.get('title','')}")
    parts.append(f"作者：{meta.get('author','')}")
    if meta.get("description"):
        parts.append(f"简介：{meta.get('description')[:1500]}")
    if transcript:
        t = transcript[: config.MAX_TRANSCRIPT_CHARS]
        parts.append(f"逐字稿/字幕：\n{t}")
    if comments:
        ctext = "\n".join(f"- {c['text']}（赞 {c['likes']}）" for c in comments[: config.COMMENTS_TOP_N])
        parts.append(f"高赞评论：\n{ctext}")
    return "\n\n".join(parts)


def _call_endpoint(base_url: str, api_key: str, model: str, user_msg: str) -> str:
    import time
    import requests
    # 免费档限流（429）常见：逐字稿整理刚用完额度，摘要立刻跟上就撞墙 → 等待重试
    last_err = None
    for attempt in range(4):
        try:
            r = requests.post(
                base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {api_key or 'not-needed'}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    "max_tokens": config.LLM_MAX_TOKENS,
                    "temperature": 0.3,
                },
                timeout=config.LLM_TIMEOUT,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        except requests.exceptions.HTTPError as e:
            code = getattr(e.response, "status_code", 0)
            last_err = e
            if code == 429 and attempt < 3:
                wait = 35 * (attempt + 1)
                log.warning("摘要被限流（429），等 %d 秒后第 %d 次重试", wait, attempt + 1)
                time.sleep(wait)
                continue
            raise
        except Exception as e:
            last_err = e
            break
    raise last_err


def _call_groq(user_msg: str) -> str:
    """Groq 直连（双账号轮换 + 429 自动换家，见 groq_pool）。"""
    return groq_pool.chat(
        config.GROQ_LLM_MODEL,
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=config.LLM_MAX_TOKENS,
        temperature=0.3,
    )


def summarize(meta: dict, transcript: str, comments=None) -> str:
    """返回 LLM 生成的 Markdown 摘要；配置了 OmniRoute key 时优先网关，否则 Groq 双账号轮换。"""
    user_msg = _build_user(meta, transcript, comments)
    # 仅在配置了 OmniRoute 网关 key 时优先走网关（本地版未配置，等于关闭）
    if config.OMNIROUTE_URL and config.OMNIROUTE_API_KEY:
        try:
            log.info("尝试 OmniRoute 网关摘要")
            return _call_endpoint(config.OMNIROUTE_URL, config.OMNIROUTE_API_KEY,
                                  config.OMNIROUTE_MODEL, user_msg)
        except Exception as e:
            log.warning("OmniRoute 摘要失败，转 Groq 直连: %s", e)
    return _call_groq(user_msg)
