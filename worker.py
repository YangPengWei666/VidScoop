"""
worker.py —— 一次性入库进程（由扩展通过 Native Messaging 唤起，干完即退）
用法：pythonw worker.py <url>
流程：去重 → yt-dlp 抓取（字幕优先）→ 无字幕则语音转写 → AI 整理 → AI 摘要 → 写入笔记库
"""
import sys
import os
import json
import logging
import subprocess
import threading
import time
import uuid

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from localbot import config, dedup, fetch, polish, transcribe, summarize, note_builder  # noqa: E402

LOG_PATH = os.path.join(BASE, "worker.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8")],
)
log = logging.getLogger("worker")


# ---------- 进度回传：stdout 输出 JSON 行，native_host 转发给浏览器 ----------
def emit(obj):
    try:
        # 走字节流并显式 UTF-8：Windows 管道 stdout 默认 cp936(GBK)，
        # 而 native_host 固定按 utf-8 解码——中文经此边界曾全变 U+FFFD（P6）
        sys.stdout.buffer.write(json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n")
        sys.stdout.buffer.flush()
    except Exception:
        pass  # 无管道（手动运行）时静默


def prog(stage: str, msg: str):
    emit({"localbot_progress": {"stage": stage, "msg": msg}})


def done(ok: bool, **kw):
    kw["ok"] = ok
    if _engine.get("outdated"):
        kw["engine_outdated"] = True   # P4 埋字段；按钮可见提示在 P5 由插件读取
    emit({"localbot_done": kw})


# ---------- P4 · yt-dlp 引擎自检（后台 daemon 线程，不阻塞主链路、不拖住退出） ----------
_engine = {}  # 自检结果（当前只有 outdated）；由守护线程写、done() 读


def _ver_tuple(v: str):
    """'2026.08.19' / '2026.8.19' → (2026, 8, 19)。
    PyPI 按 PEP 440 规范化会吞掉前导零，与本机 yt-dlp 输出字符串不相等，必须按数字段比。
    解析不了返回 None（调用方静默跳过）。"""
    nums = []
    for part in (v or "").strip().split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        if not digits:
            return None
        nums.append(int(digits))
    return tuple(nums) if nums else None


def _ytdlp_check_worker():
    """守护线程体：读 24h 缓存 → 取本机版本 → 查 PyPI 最新版 → 比较并原子写缓存。
    除「命令缺失」外，任何失败一律静默，绝不影响主链路。"""
    try:
        import requests
        cache = os.path.join(config.WORK_DIR, "ytdlp_check.json")
        # 1) 缓存新鲜（默认 24h）直接采信，不发网络
        try:
            with open(cache, "r", encoding="utf-8") as f:
                c = json.load(f)
            if time.time() - float(c.get("ts", 0)) < config.YTDLP_CHECK_CACHE_HOURS * 3600:
                if c.get("outdated"):
                    _engine["outdated"] = True
                    log.warning("yt-dlp 有新版（缓存）：本机 %s → 最新 %s，建议 pip 升级",
                                c.get("local"), c.get("latest"))
                return
        except Exception:
            pass

        # 2) 本机版本；CREATE_NO_WINDOW 防控制台黑框。命令缺失必须 WARNING（B站/YouTube 会直接 127）
        try:
            p = subprocess.run(["yt-dlp", "--version"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=config.YTDLP_CHECK_TIMEOUT, creationflags=0x08000000)
        except FileNotFoundError:
            log.warning("yt-dlp 自检：PATH 中未找到 yt-dlp（B站/YouTube 抓取将不可用）")
            return
        if p.returncode != 0:
            log.warning("yt-dlp 自检：yt-dlp --version 失败（returncode=%s）", p.returncode)
            return
        local = p.stdout.strip()

        # 3) PyPI 最新稳定版（官方 JSON API：GET /pypi/yt-dlp/json → info.version）；网络失败静默
        r = requests.get("https://pypi.org/pypi/yt-dlp/json",
                         timeout=config.YTDLP_CHECK_TIMEOUT)
        r.raise_for_status()
        latest = (r.json().get("info") or {}).get("version") or ""
        lv, rv = _ver_tuple(local), _ver_tuple(latest)
        if not lv or not rv:
            return
        outdated = lv < rv

        # 4) 原子写缓存（tmp + replace），写失败也不影响判定
        try:
            os.makedirs(config.WORK_DIR, exist_ok=True)
            tmp = cache + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"ts": time.time(), "local": local,
                           "latest": latest, "outdated": outdated}, f)
            os.replace(tmp, cache)
        except Exception:
            pass

        if outdated:
            _engine["outdated"] = True
            log.warning("yt-dlp 有新版：本机 %s → 最新 %s，建议 pip install -U yt-dlp", local, latest)
        else:
            log.debug("yt-dlp 自检：已是最新（%s）", local)
    except Exception:
        pass  # 自检永不影响主链路


def _ytdlp_self_check():
    """仅负责拉起自检线程并立即返回。
    硬要求：daemon=True——worker 退出阶段（P1 崩溃点所在）绝不能被自检线程拖住。"""
    if not config.YTDLP_CHECK_ENABLED:
        return
    try:
        threading.Thread(target=_ytdlp_check_worker,
                         name="ytdlp-check", daemon=True).start()
    except Exception:
        pass


def _write_note(meta: dict, transcript: str, summary: str, source: str,
                retries: int = 5) -> str:
    """写笔记，撞名则换名重试（2026-10-19 修 B）。
    旧版 note_builder._unique_filename() 是「先检查后创建」，两个 worker 进程
    同时点两条视频时会撞窗口期：8 线程实测 3 条直接 FileExistsError 丢笔记。
    config.MAX_CONCURRENT_TASKS 是死配置、没有任何代码读它，故在此兜住。

    重试策略：前几次仍走 build()（正常情况一次就过，文件名最干净）；
    连续撞名说明并发压力大，改用「标题 + 随机短码」直接构造名字，
    避开所有线程算出同一个名字的活锁。全程 "x" 模式，绝不覆盖已有笔记。"""
    last = None
    for attempt in range(retries):
        rel, content = note_builder.build(
            meta, transcript, summary, meta.get("comments"), source)
        abs_path = os.path.join(config.KB_REPO_DIR, rel)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        # 第 3 次起改随机后缀，绕开并发活锁
        if attempt >= 2:
            stem, ext = os.path.splitext(abs_path)
            tag = uuid.uuid4().hex[:6]
            abs_path = f"{stem}-{tag}{ext}"
        try:
            with open(abs_path, "x", encoding="utf-8") as f:
                f.write(content)
            return abs_path
        except FileExistsError as e:
            last = e
            log.warning("写入撞名（第 %d/%d 次），换名重试: %s",
                        attempt + 1, retries, os.path.basename(abs_path))
            continue
    raise RuntimeError(f"连续 {retries} 次撞名，放弃写入: {last}")


def main(url: str):
    os.makedirs(config.WORK_DIR, exist_ok=True)
    os.makedirs(config.NOTES_DIR, exist_ok=True)
    _ytdlp_self_check()  # P4：daemon 后台自检，立即返回，不阻塞
    prog("started", "开始处理")
    url = fetch.normalize_url(url)  # 页面型链接 → 视频直链（去重也更准）
    log.info("收到入库请求: %s", url)

    if dedup.is_duplicate(url):
        log.info("去重命中，跳过: %s", url)
        done(True, skipped=True, title="", msg="这条视频已经入库过了")
        return

    # 1) 抓取：yt-dlp 字幕优先，无字幕则下载音频
    prog("download", "下载视频")
    meta = fetch.fetch(url)
    if not meta.get("ok"):
        etype, detail = meta.get("error_type", "?"), (meta.get("error", "") or "")[:160]
        log.error("抓取失败 [%s]: %s", etype, detail)  # 英文原文只进日志，不上屏
        # 按错误类别给人话提示（哪坏了+怎么办），不甩 yt-dlp 英文原文
        human = {
            "need_cookie":     "需要登录态或 IP 被平台判定可疑。YouTube 的话：换个代理节点，再点一次。",
            "rate_limited":    "被平台限流了，等几分钟再点。",
            "unsupported_site": "这不是支持的链接（仅 B站/YouTube 视频页），换个视频页再点。",
            "unavailable_live": "这是直播、首播或已下架的视频，存不了。",
            "network":         "网络不通，检查代理是否开着，或换个节点。",
            "extractor_expired": "平台可能改了接口，跑一下 yt-dlp -U 更新，或等插件更新。",
        }.get(etype, "抓取失败（原因见日志），再点一次试试。")
        done(False, stage="download", error=human)
        return

    # 2) 文字稿：字幕 or whisper
    transcript = meta.get("transcript")
    source = meta.get("transcript_source")
    if not transcript:
        prog("transcribe", "语音转写中")
        log.info("无字幕，下载音频走语音转写（硅基 SenseVoice → Groq whisper 兜底）…")
        transcript = transcribe.transcribe(meta["audio_path"])
        source = "whisper"
    # whisper 原稿无标点：AI 整理（加标点/分段/纠错）；字幕本身带标点，跳过
    if source == "whisper" and config.POLISH_ENABLED:
        prog("polish", "逐字稿整理中")
        log.info("AI 整理逐字稿（加标点/分段/纠错）…")
        try:
            polished = polish.polish(transcript)
            if polished and len(polished) >= len(transcript) * 0.4:
                transcript = polished
                source = "whisper_polished"
            else:
                log.warning("整理结果异常，保留原稿")
        except Exception as e:
            log.warning("逐字稿整理失败，保留原稿: %s", e)
    log.info("文字稿就绪（来源=%s，%d 字）", source, len(transcript))

    # 3) 摘要
    prog("summarize", "摘要生成中")
    summary = summarize.summarize(meta, transcript, meta.get("comments"))

    # 4) 写入 Obsidian 库
    prog("write", "写入笔记")
    abs_path = _write_note(meta, transcript, summary, source)
    dedup.mark_ingested(url)
    log.info("笔记已写入: %s", abs_path)

    # 5) 清理临时目录
    import shutil
    work = meta.get("work_dir")
    if work and os.path.isdir(work):
        shutil.rmtree(work, ignore_errors=True)

    done(True, title=(meta.get("title") or "未命名")[:80], note_path=abs_path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: worker.py <url>")
        sys.exit(1)
    try:
        main(sys.argv[1])
    except Exception as e:
        log.exception("入库失败")
        done(False, error=f"处理出错：{str(e)[:160]}")
        sys.exit(1)
