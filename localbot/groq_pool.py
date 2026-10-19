"""
groq_pool.py —— LLM / 转写 多供应商降级池
主备顺序（2026-10-11 定，国内直连优先，节点不稳时 Groq 常被拦 IP）：
  整理/摘要(chat)    ：智谱 glm-4-flash → 硅基 GLM-4-9B → Groq 双账号轮换(gpt-oss-120b)
  转写(transcribe)  ：硅基 SenseVoiceSmall → Groq 双账号轮换(whisper-large-v3-turbo)
想切回 Groq 主力：把 chain 里对应顺序调换即可。
Groq 双账号轮换策略不变：一条视频一个主力账号，视频间交替（状态存 work/groq_state.json）；
429 立刻换家；两个账号都满才退回"等 35 秒重试"。
"""
import json
import logging
import os
import time

import requests

from localbot import config

log = logging.getLogger("groq_pool")

_BACKOFF_SECONDS = 35      # Groq 全部账号都 429 时的等待
_MAX_ROUNDS = 4            # Groq 全员轮完算一轮，最多试 4 轮
_LABELS = ["A", "B"]

# 国内直连会话：绝不走环境代理（本地代理出口 IP 不稳定，国内站也不该绕代理）
_cn = requests.Session()
_cn.trust_env = False


# ==================== Groq 双账号轮换（备用线，逻辑不变） ====================

def _keys():
    """可用 key 列表：[(label, key), ...]"""
    out = []
    if config.GROQ_API_KEY:
        out.append((_LABELS[0], config.GROQ_API_KEY))
    if config.GROQ_API_KEY_2:
        out.append((_LABELS[1], config.GROQ_API_KEY_2))
    return out


def _state_path():
    return os.path.join(config.WORK_DIR, "groq_state.json")


def _load_start_index(n):
    """读上次记下的起始账号下标（状态文件丢了就从 0 开始，无碍）。"""
    try:
        with open(_state_path(), "r", encoding="utf-8") as f:
            idx = json.load(f).get("next", 0)
        return idx % n if n else 0
    except Exception:
        return 0


def _save_next_index(idx, n):
    try:
        os.makedirs(config.WORK_DIR, exist_ok=True)
        with open(_state_path(), "w", encoding="utf-8") as f:
            json.dump({"next": (idx + 1) % n}, f)
    except Exception:
        pass  # 状态文件写失败不影响主流程


def _post_chat(key, model, messages, max_tokens, temperature, timeout):
    r = requests.post(
        config.GROQ_BASE_URL + "/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _post_audio(key, audio_path, model, timeout):
    with open(audio_path, "rb") as f:
        r = requests.post(
            config.GROQ_BASE_URL + "/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            files={"file": (os.path.basename(audio_path), f)},
            data={"model": model, "response_format": "text"},
            timeout=timeout,
        )
    r.raise_for_status()
    return r.text.strip()


def _run(caller: str, func, *args, **kwargs):
    """Groq 带轮换的执行：先按上次记住的账号开始，429 就换下家，全员撞墙才等待重试。"""
    keys = _keys()
    if not keys:
        raise RuntimeError("未配置任何 GROQ_API_KEY")
    n = len(keys)
    start = _load_start_index(n)
    last_err = None
    for round_no in range(1, _MAX_ROUNDS + 1):
        for offset in range(n):
            idx = (start + offset) % n
            label, key = keys[idx]
            try:
                result = func(key, *args, **kwargs)
                _save_next_index(idx, n)
                log.info("%s：账号%s 完成（第 %d 轮）", caller, label, round_no)
                return result
            except requests.exceptions.HTTPError as e:
                code = getattr(e.response, "status_code", 0)
                last_err = e
                if code == 429:
                    log.warning("%s：账号%s 撞限流（429），切换下一账号", caller, label)
                    continue
                raise  # 非 429 的错误（401/500 等）换了账号也没用，直接抛
            except Exception as e:
                last_err = e
                raise
        # 所有账号都 429：等一会再来一轮
        if round_no < _MAX_ROUNDS:
            log.warning("%s：两个账号都限流，等 %d 秒进入第 %d 轮",
                        caller, _BACKOFF_SECONDS, round_no + 1)
            time.sleep(_BACKOFF_SECONDS)
    raise last_err


# ==================== 国内供应商（主力线） ====================

def _zhipu_chat(messages, max_tokens, temperature, timeout):
    """智谱开放平台 glm-4-flash（免费，128K 上下文）。"""
    r = _cn.post(
        config.ZHIPU_BASE_URL + "/chat/completions",
        headers={"Authorization": f"Bearer {config.ZHIPU_API_KEY}"},
        json={
            "model": config.ZHIPU_LLM_MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _siliconflow_chat(messages, max_tokens, temperature, timeout):
    """硅基流动 GLM-4-9B（免费）。"""
    r = _cn.post(
        config.SILICONFLOW_BASE_URL + "/chat/completions",
        headers={"Authorization": f"Bearer {config.SILICONFLOW_API_KEY}"},
        json={
            "model": config.SILICONFLOW_LLM_MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _siliconflow_audio(audio_path, timeout):
    """硅基流动 SenseVoiceSmall（免费，中文口播准；无标点由后续 polish 补）。"""
    with open(audio_path, "rb") as f:
        r = _cn.post(
            config.SILICONFLOW_BASE_URL + "/audio/transcriptions",
            headers={"Authorization": f"Bearer {config.SILICONFLOW_API_KEY}"},
            files={"file": (os.path.basename(audio_path), f)},
            data={"model": config.SILICONFLOW_ASR_MODEL},
            timeout=timeout,
        )
    r.raise_for_status()
    return (r.json().get("text") or "").strip()


# ==================== 降级链执行器 ====================

def _try_chain(caller: str, steps):
    """steps: [(渠道名, callable), ...] 依次尝试；空结果视为失败继续换下家；全挂才抛。"""
    errs = []
    for name, fn in steps:
        try:
            result = fn()
            if result:
                log.info("%s：%s 完成", caller, name)
                return result
            errs.append(f"{name}: 空结果")
            log.warning("%s：%s 返回空 → 切下一渠道", caller, name)
        except Exception as e:
            errs.append(f"{name}: {type(e).__name__} {e}")
            log.warning("%s：%s 失败 → 切下一渠道 (%s)", caller, name, e)
    raise RuntimeError(f"{caller}：所有渠道失败 —— " + " | ".join(errs))


def _has_groq():
    return bool(config.GROQ_API_KEY or config.GROQ_API_KEY_2)


def chat(model, messages, max_tokens, temperature, timeout=None):
    """整理/摘要：Groq → 智谱 → 硅基 轮换。

    2026-10-19 调整顺序：Groq 提到第一位。
    依据实测（同一份 2800 字真实稿件）：
      Groq-A 6.4s / Groq-B 7.8s，智谱 glm-4-flash 约 70s（慢 10 倍以上）。
    第三方基准（toolfreebie 2026-08）也显示 GLM Flash 生成仅 20 tok/s，
    是免费档里最慢的一档；Groq 约 527 tok/s。
    智谱保留为第二腿兜底：Groq 撞限流或故障时自动切回，总可用性不降。
    model 参数仅用于 Groq 腿。"""
    timeout = timeout or config.LLM_TIMEOUT
    steps = []
    if _has_groq():
        steps.append(("Groq双账号轮换",
                      lambda: _run("LLM(Groq)", _post_chat, model, messages,
                                   max_tokens, temperature, timeout)))
    if config.ZHIPU_API_KEY:
        steps.append(("智谱glm-4-flash",
                      lambda: _zhipu_chat(messages, max_tokens, temperature, timeout)))
    if config.SILICONFLOW_API_KEY:
        steps.append(("硅基GLM-4-9B",
                      lambda: _siliconflow_chat(messages, max_tokens, temperature, timeout)))
    if not steps:
        raise RuntimeError("未配置任何 LLM 渠道 key")
    return _try_chain("LLM", steps)


def transcribe(audio_path, model, timeout=None):
    """转写：硅基 SenseVoice → Groq 轮换。model 参数仅用于 Groq 备用腿。"""
    timeout = timeout or config.DOWNLOAD_TIMEOUT
    steps = []
    if config.SILICONFLOW_API_KEY:
        steps.append(("硅基SenseVoice",
                      lambda: _siliconflow_audio(audio_path, timeout)))
    if _has_groq():
        steps.append(("Groq双账号轮换",
                      lambda: _run("转写(Groq)", _post_audio, audio_path, model, timeout)))
    if not steps:
        raise RuntimeError("未配置任何转写渠道 key")
    return _try_chain("转写", steps)
