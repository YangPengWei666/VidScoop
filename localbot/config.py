"""
localbot 配置中心 —— 本机版
与服务器版的区别：
- 直写本机 Obsidian 库（无 git、无 HMAC、无 TG、无 OmniRoute）
- 监听 127.0.0.1，只有本机浏览器能访问
所有可调项均可通过项目根目录 .env 覆盖。
"""
import os

def _load_env():
    """极简 .env 解析（避免引入 python-dotenv 依赖）。不覆盖已存在的环境变量。"""
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

_load_env()

# ---------- 路径 ----------
VAULT_DIR = os.getenv("VAULT_DIR", "")                             # 笔记库根目录（必填，见 .env.example）
KB_REPO_DIR = VAULT_DIR                                            # 兼容 note_builder 的路径拼法
NOTES_DIR = os.path.join(VAULT_DIR, "00-Clip")                     # 入库目录
# 可选：归档目录（如把旧笔记挪去别处，指过来让去重仍能扫到；留空不扫）
ARCHIVE_DIR = os.getenv("ARCHIVE_DIR", "")
WORK_DIR = os.getenv("WORK_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "work"))

# ---------- LLM（Groq 直连，本机实测可达） ----------
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_API_KEY_2 = os.getenv("GROQ_API_KEY_2", "")                # 账号B（独立额度），与主 key 轮换
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_LLM_MODEL = os.getenv("GROQ_LLM_MODEL", "openai/gpt-oss-120b")
GROQ_WHISPER_MODEL = "whisper-large-v3-turbo"                    # 无字幕时音频转写

# ---------- 国内备用/主力渠道（免费，直连不走代理） ----------
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY", "")       # 硅基流动（实名账号，尾号 laee）
SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
SILICONFLOW_LLM_MODEL = os.getenv("SILICONFLOW_LLM_MODEL", "THUDM/GLM-4-9B-0414")  # 免费聊天
SILICONFLOW_ASR_MODEL = "FunAudioLLM/SenseVoiceSmall"            # 免费语音转写（无标点，polish 补）
ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "")                   # 智谱开放平台
ZHIPU_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
ZHIPU_LLM_MODEL = os.getenv("ZHIPU_LLM_MODEL", "glm-4-flash")    # 免费聊天，128K 上下文
OMNIROUTE_URL = ""                                               # 本地版不使用网关
OMNIROUTE_API_KEY = ""
OMNIROUTE_MODEL = ""

# ---------- 服务 ----------
HOST = os.getenv("HOST", "127.0.0.1")                            # 只监听本机
PORT = int(os.getenv("PORT", "20130"))
RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "10"))
MAX_CONCURRENT_TASKS = int(os.getenv("MAX_CONCURRENT_TASKS", "1"))  # 本机资源有限，串行稳妥

# ---------- 资源限制 ----------
DOWNLOAD_TIMEOUT = int(os.getenv("DOWNLOAD_TIMEOUT", "600"))
MAX_AUDIO_MB = int(os.getenv("MAX_AUDIO_MB", "200"))
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "1200"))
MAX_TRANSCRIPT_CHARS = int(os.getenv("MAX_TRANSCRIPT_CHARS", "60000"))

# ---------- 功能开关 ----------
GRAB_COMMENTS = os.getenv("GRAB_COMMENTS", "true").lower() == "true"
COMMENTS_TOP_N = int(os.getenv("COMMENTS_TOP_N", "5"))
PREFER_LANG_ORDER = ["zh-CN", "zh-Hans", "zh", "en", "en-US"]

# ---------- 逐字稿整理（whisper → AI 加标点/分段/纠错） ----------
POLISH_ENABLED = os.getenv("POLISH_ENABLED", "true").lower() == "true"
POLISH_CHUNK_CHARS = int(os.getenv("POLISH_CHUNK_CHARS", "2800"))
POLISH_MAX_TOKENS = int(os.getenv("POLISH_MAX_TOKENS", "4000"))

# ---------- yt-dlp 引擎自检（P4：仅日志+埋字段，查询失败静默，不阻塞主链路） ----------
YTDLP_CHECK_ENABLED = os.getenv("YTDLP_CHECK_ENABLED", "true").lower() == "true"
YTDLP_CHECK_TIMEOUT = int(os.getenv("YTDLP_CHECK_TIMEOUT", "6"))     # 秒；本地命令与 PyPI 查询共用
YTDLP_CHECK_CACHE_HOURS = int(os.getenv("YTDLP_CHECK_CACHE_HOURS", "24"))  # 结果缓存，一天最多查一次

# ---------- 平台域名 → type ----------
DOMAIN_TYPE_MAP = [
    (("youtube.com", "youtu.be"), "youtube"),
    (("bilibili.com", "b23.tv"), "bilibili"),
    (("x.com", "twitter.com"), "x"),
    (("kuaishou.com",), "kuaishou"),
]


def detect_type(url: str) -> str:
    u = (url or "").lower()
    for domains, t in DOMAIN_TYPE_MAP:
        for d in domains:
            if d in u:
                return t
    return "link"


def sanitize_filename(name: str, max_len: int = 60) -> str:
    bad = '<>:"/\\|?*\n\t\r'
    for ch in bad:
        name = name.replace(ch, " ")
    name = " ".join(name.split())
    if not name:
        name = "untitled"
    return name[:max_len].strip()
