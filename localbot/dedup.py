"""
去重：扫描笔记目录下所有 .md 的 frontmatter（source_url）建哈希集合，入库前判重。
归档目录（存在时）一并扫描，防止提炼归档后历史笔记失联导致去重失效。
"""
import hashlib
import os
import re
from localbot import config

_cache = None       # type: set | None   # url 哈希集合


def _normalize(url: str) -> str:
    """去掉常见跟踪参数与末尾斜杠，降低误判。
    2026-10-19 修 C：原先只清 spm/from/timestamp/t，漏掉 vd_source、
    share_source 等实际会带的参数，导致同一视频不同入口哈希不同。
    注意：只删这些具名参数，不动 v=（YouTube 视频号）与 p=（B站分P），否则会误判。"""
    u = (url or "").strip()
    u = re.sub(
        r"[?&](spm_id_from|from_spmid|from_source|utm_campaign|utm_medium|utm_source|"
        r"share_medium|share_source|share_plat|share_tag|share_from|session_id|"
        r"is_story_h5|unique_k|modeFrom|vd_source|timestamp|spm|from|"
        r"buvid|up_id|tab|si|feature|scene|wfr|msource|bbid|t)=[^&#]*",
        "", u,
    )
    u = re.sub(r"[?&]+$", "", u)      # 删空参数后可能留下孤立的 ? 或 &
    u = re.sub(r"[?&]{2,}", "&", u)   # 连续分隔符收敛
    return u.rstrip("/")


def _hash(url: str) -> str:
    return hashlib.sha256(_normalize(url).encode("utf-8")).hexdigest()[:16]


def _scan_dirs() -> list:
    """判重扫描目录：入库目录 + 可选归档目录（ARCHIVE_DIR）。
    用途：若你把旧笔记 move 到别处归档，只扫入库目录会让历史笔记失联、
    去重整体失效（表现为重复点已入库视频又白下一遍、多出一份重复笔记）。
    归档笔记的 source_url 字段原样保留，故零迁移、零回写；未配置则跳过。
    """
    dirs = [config.NOTES_DIR]
    if config.ARCHIVE_DIR and os.path.isdir(config.ARCHIVE_DIR):
        dirs.append(config.ARCHIVE_DIR)
    return dirs


def _scan_existing() -> set:
    existing = set()
    for d in _scan_dirs():
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if not fn.endswith(".md"):
                continue
            try:
                with open(os.path.join(d, fn), "r", encoding="utf-8") as f:
                    text = f.read(4000)
            except Exception:
                continue
            m = re.search(r"^source_url:\s*(.+)$", text, re.MULTILINE)
            if m:
                existing.add(_hash(m.group(1).strip().strip('"')))
    return existing


def is_duplicate(url: str) -> bool:
    """URL 归一化哈希判重。"""
    global _cache
    if _cache is None:
        _cache = _scan_existing()
    return _hash(url) in _cache


def mark_ingested(url: str) -> None:
    """入库成功后登记，避免同进程内重复提交。"""
    global _cache
    if _cache is None:
        _cache = _scan_existing()
    _cache.add(_hash(url))
