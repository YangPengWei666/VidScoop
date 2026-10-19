"""
fetch.py —— 通用媒体抓取层（平台无关）
底层 yt-dlp，原生支持 YouTube/Bilibili 等上千站点。
产出结构化 dict：元数据 + (字幕文本 或 音频路径) + (可选高赞评论)。

设计要点：
- 字幕优先：若目标语言有字幕/自动字幕，直接抓字幕文本，跳过 whisper（省时省资源）。
- 无字幕才下载音频（供上层调 Groq whisper）。
- 失败做"通用错误分类"：提取器过期 / 需 cookie / 网络 / 限流 / 不支持该站 / 直播不可用，
  而不是针对某一个站打补丁。
"""
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from localbot import config

log = logging.getLogger("fetch")

YTDLP = "yt-dlp"


def _run(args, timeout=None):
    """统一执行 yt-dlp，返回 (returncode, stdout, stderr)。
    Windows 注意：yt-dlp 输出恒为 UTF-8，必须显式指定，否则按 GBK 解码会炸中文。"""
    cmd = [YTDLP] + args
    try:
        # CREATE_NO_WINDOW：worker 无控制台时，防止 yt-dlp 这个控制台程序自己弹黑框
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout or config.DOWNLOAD_TIMEOUT,
                           creationflags=0x08000000)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except FileNotFoundError:
        return 127, "", "yt-dlp 未安装"


def classify_error(stderr: str) -> str:
    """把 yt-dlp 的失败归到通用类别，便于上层给出人话提示。"""
    s = (stderr or "").lower()
    if "sign in" in s or "login" in s or "cookie" in s or "cookies" in s:
        return "need_cookie"          # 该内容需登录态（敏感，默认不开 cookie）
    if "unsupported url" in s or "no such extractor" in s:
        return "unsupported_site"     # 该 URL 不被支持
    if "429" in s or "rate" in s or "too many" in s:
        return "rate_limited"         # 被限流
    if "live event" in s or "premiere" in s or "is not available" in s or "unavailable" in s:
        return "unavailable_live"     # 直播/首播/已下架，本期不支持
    if "timed out" in s or "network" in s or "connection" in s or "name or service" in s:
        return "network"              # 网络层
    return "extractor_expired"        # 默认：多半是平台改接口，需 yt-dlp -U


def _pick_subtitle_lang(info: dict) -> str | None:
    """按偏好顺序挑一个可用字幕语言（优先手动字幕，其次自动字幕）。"""
    subs = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    for lang in config.PREFER_LANG_ORDER:
        if lang in subs:
            return lang
    for lang in config.PREFER_LANG_ORDER:
        if lang in auto:
            return lang
    # 退而求其次：挑任何含 zh 或 en 的语言
    for pool in (subs, auto):
        for lang in pool:
            if "zh" in lang or "en" in lang:
                return lang
    return None


def _parse_srt_text(path: str) -> str:
    """从 .srt 抽取纯文本（去序号与时间轴）。"""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            raw = f.read()
    except Exception:
        return ""
    lines = []
    for line in raw.splitlines():
        if re.match(r"^\d+$", line.strip()):
            continue
        if re.match(r"^\d{2}:\d{2}:\d{2}", line.strip()):
            continue
        if line.strip():
            lines.append(line.strip())
    return "\n".join(lines).strip()


def normalize_url(url: str) -> str:
    """链接归一化：把「页面型链接」改写成 yt-dlp 认识的视频直链。
    目前覆盖：
    1. B站/YouTube 剥掉跟踪参数（vd_source/spm_id_from 等）→ 去重哈希稳定
    """
    if "bilibili.com/video/" in url:
        return re.sub(r"\?.*$", "", url)
    if "youtube.com/watch" in url or "youtu.be/" in url:
        m2 = re.search(r"(?:[?&]v=|youtu\.be/)([\w-]+)", url)
        if m2:
            return f"https://www.youtube.com/watch?v={m2.group(1)}"
    return url


def fetch(url: str) -> dict:
    """通用抓取。返回 dict，失败时含 'error' 与 'error_type'。"""
    url = normalize_url(url)
    result = {"ok": False, "url": url}
    work = tempfile.mkdtemp(dir=config.WORK_DIR)
    out_tmpl = os.path.join(work, "media.%(ext)s")

    def _fail(msg, etype):
        """失败出口：先清临时目录再返回（2026-10-19 修 A）。
        旧版失败时只 return 不清理，每次失败在 work/ 留一个目录；
        若失败发生在媒体已下载之后，整个视频文件会永久占盘。
        成功路径的 work_dir 由 worker 在写完笔记后清理，故此处只清失败分支。"""
        shutil.rmtree(work, ignore_errors=True)
        result.update(error=msg, error_type=etype)
        return result

    extra = []
    t_json, t_subs, t_av = 120, 180, config.DOWNLOAD_TIMEOUT
    try:
        # 1) 取元数据 + 评论（不下载媒体）
        meta_args = [
            "--dump-json", "--no-download", "--no-warnings",
            "--write-comments",
            *extra,
            url,
        ]
        rc, out, err = _run(meta_args, timeout=t_json)
        # 2026-10-19 修：YouTube 反爬会随机抛 "Sign in to confirm you're not a bot"，
        # 实测同一链接重试即成功（10-13 16:59 失败 → 5 秒后再点成功）。
        # 仅在失败分支重试一次，成功路径零改动；只对 YouTube 生效，不波及其它平台。
        if rc != 0 and "youtube" in url and classify_error(err) in ("need_cookie", "rate_limited"):
            log.warning("YouTube 首次抓取被拦（%s），3 秒后自动重试一次", classify_error(err))
            time.sleep(3)
            rc, out, err = _run(meta_args, timeout=t_json)
            if rc == 0:
                log.info("YouTube 重试成功")
        if rc != 0:
            return _fail(err.strip()[:500], classify_error(err))

        try:
            info = json.loads(out)
        except json.JSONDecodeError:
            return _fail("元数据解析失败", "extractor_expired")

        result.update(
            title=info.get("title") or info.get("fulltitle") or "未命名",
            author=info.get("uploader") or info.get("channel") or info.get("uploader_id") or "未知",
            duration=info.get("duration") or 0,
            description=info.get("description") or "",
            tags=info.get("tags") or [],
            thumbnail=info.get("thumbnail") or "",
            webpage_url=info.get("webpage_url") or url,
            upload_date=info.get("upload_date") or "",
        )

        # 2) 评论（可选，取高赞前 N）
        if config.GRAB_COMMENTS:
            comments = info.get("comments") or []
            try:
                comments = sorted(
                    comments,
                    key=lambda c: (c.get("like_count") or c.get("likes") or 0),
                    reverse=True,
                )[: config.COMMENTS_TOP_N]
                result["comments"] = [
                    {"text": c.get("text") or c.get("message") or "",
                     "likes": c.get("like_count") or c.get("likes") or 0}
                    for c in comments if (c.get("text") or c.get("message"))
                ]
            except Exception:
                result["comments"] = []
            # B站专属：yt-dlp 不返回 B站评论点赞数，改走官方 API 拿真实点赞
            if "bilibili.com" in url:
                try:
                    api_comments = _bilibili_comments(url, config.COMMENTS_TOP_N)
                    if api_comments:
                        result["comments"] = api_comments
                        log.info("B站评论（官方 API，%d 条）", len(api_comments))
                except Exception as e:
                    log.warning("B站评论 API 失败，退回 yt-dlp 评论: %s", e)

        # 3) 字幕优先：有则抓字幕文本，跳过 whisper
        lang = _pick_subtitle_lang(info)
        subtitle_text = None
        if lang:
            rc2, _, err2 = _run([
                "--skip-download", "--write-subs", "--write-auto-subs",
                "--sub-langs", lang, "--convert-subs", "srt",
                "-o", out_tmpl, "--no-warnings",
                *extra,
                url,
            ], timeout=t_subs)
            if rc2 == 0:
                for fn in os.listdir(work):
                    if fn.endswith(".srt"):
                        subtitle_text = _parse_srt_text(os.path.join(work, fn))
                        break
        if subtitle_text and len(subtitle_text) > 30:
            result.update(ok=True, transcript=subtitle_text, transcript_source="subtitle", work_dir=work)
            return result

        # 4) 无字幕 → 下载音频（供上层 whisper）
        rc3, _, err3 = _run([
            "-x", "--audio-format", "mp3", "--no-warnings",
            "-o", out_tmpl,
            *extra,
            url,
        ], timeout=t_av)
        if rc3 != 0:
            return _fail(err3.strip()[:500], classify_error(err3))

        audio_path = None
        for fn in os.listdir(work):
            if fn.endswith(".mp3") or fn.endswith(".m4a") or fn.endswith(".opus"):
                audio_path = os.path.join(work, fn)
                break
        if not audio_path:
            return _fail("音频提取失败", "extractor_expired")

        # 体积上限保护
        if os.path.getsize(audio_path) > config.MAX_AUDIO_MB * 1024 * 1024:
            return _fail(f"音频超 {config.MAX_AUDIO_MB}MB 上限", "too_large")

        result.update(ok=True, audio_path=audio_path, transcript_source=None, work_dir=work)
        return result
    finally:
        pass  # 音频等产物留在 work 由上层清理
