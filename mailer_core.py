# -*- coding: utf-8 -*-
"""
mailer_core：GitHub 热榜日报核心模块（抓取 / 邮件 / 定时任务 / 配置）

被 CLI（send_trending.py）与 GUI（gui.py）共同复用。
打包为 exe 时，通过 set_base_dir() 将配置与日志目录指向 exe 所在目录。
"""

import datetime
import atexit
import ctypes
import hashlib
import html
import json
import logging
import os
import re
import smtplib
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
import urllib.parse
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate
from html import unescape
from pathlib import Path

APP_NAME = "StarTrace"
APP_VERSION = "v1.0.0"
APP_AUTHOR = "Guozhengkun"
TASK_NAME = "GitHubTrendingMailer"

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
LOG_PATH = BASE_DIR / "send_trending.log"
TRANSLATION_CACHE_PATH = BASE_DIR / "translation_cache.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_CONFIG = {
    "smtp": {"host": "smtp.qq.com", "port": 465, "user": "", "auth_code": ""},
    "from_name": APP_NAME,
    "to": [],
    "language": "all",
    "top_n": 25,
    "send_time": "09:00",
    "include_chinese": True,
    "translation_provider": "local",
    "translation_url": "",
    "translation_model": "",
}

LOG_HANDLER_EXTRA = []  # GUI 可注入回调：logging 记录时同步推送
_TRANSLATION_LOCK = threading.Lock()
_TRANSLATION_PROCESS = None
_TRANSLATION_PORT = None
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
TRANSLATION_MODEL_NAME = "Index-Translate-2B.Q4_K_M.gguf"
TRANSLATION_MODEL_URLS = (
    "https://modelscope.cn/models/IndexTeam/Index-Translate-2B-GGUF/resolve/master/"
    f"{TRANSLATION_MODEL_NAME}?download=true",
    "https://huggingface.co/IndexTeam/Index-Translate-2B-GGUF/resolve/main/"
    f"{TRANSLATION_MODEL_NAME}?download=true",
)
TRANSLATION_MODEL_SIZE = 1_310_000_000
LLAMA_CPP_VERSION = "b12027"
LLAMA_CPP_URL = (
    f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_CPP_VERSION}/"
    f"llama-{LLAMA_CPP_VERSION}-bin-win-cpu-x64.zip"
)


def _credential_target(username, kind="SMTP"):
    return f"{APP_NAME}/{kind}/{str(username or '').strip().lower()}"


def _credential_api():
    """Load the Windows Credential Manager API, or return None elsewhere."""
    if sys.platform != "win32":
        return None
    advapi = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    kernel = ctypes.WinDLL("Kernel32.dll", use_last_error=True)

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]

    class CREDENTIAL(ctypes.Structure):
        pass

    CREDENTIAL._fields_ = [
        ("Flags", ctypes.c_uint32), ("Type", ctypes.c_uint32),
        ("TargetName", ctypes.c_wchar_p), ("Comment", ctypes.c_wchar_p),
        ("LastWritten", FILETIME), ("CredentialBlobSize", ctypes.c_uint32),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", ctypes.c_uint32), ("AttributeCount", ctypes.c_uint32),
        ("Attributes", ctypes.c_void_p), ("TargetAlias", ctypes.c_wchar_p),
        ("UserName", ctypes.c_wchar_p),
    ]

    advapi.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), ctypes.c_uint32]
    advapi.CredWriteW.restype = ctypes.c_int
    advapi.CredReadW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                 ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    advapi.CredReadW.restype = ctypes.c_int
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    advapi.CredFree.argtypes = [ctypes.c_void_p]
    advapi.CredFree.restype = None
    return advapi, kernel, CREDENTIAL


def _store_auth_code(username, auth_code, kind="SMTP"):
    api = _credential_api()
    if api is None:
        raise RuntimeError("密钥的安全存储仅支持 Windows 凭据管理器")
    advapi, _kernel, CREDENTIAL = api
    raw = str(auth_code).encode("utf-16-le")
    blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    cred = CREDENTIAL()
    cred.Type = 1  # CRED_TYPE_GENERIC
    cred.TargetName = _credential_target(username, kind)
    cred.CredentialBlobSize = len(raw)
    cred.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
    cred.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE (current Windows user)
    cred.UserName = str(username or "")
    if not advapi.CredWriteW(ctypes.byref(cred), 0):
        raise OSError(ctypes.get_last_error(), "Windows 凭据管理器保存失败")


def _load_auth_code(username, kind="SMTP"):
    api = _credential_api()
    if api is None:
        return ""
    advapi, _kernel, _CREDENTIAL = api
    ptr = ctypes.POINTER(_CREDENTIAL)()
    if not advapi.CredReadW(_credential_target(username, kind), 1, 0, ctypes.byref(ptr)):
        return ""
    try:
        item = ptr.contents
        if not item.CredentialBlobSize:
            return ""
        raw = ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize)
        return raw.decode("utf-16-le")
    finally:
        advapi.CredFree(ptr)


def set_base_dir(d):
    """将配置 / 日志目录切换到指定目录（exe 场景下为 exe 所在目录）。"""
    global BASE_DIR, CONFIG_PATH, LOG_PATH, TRANSLATION_CACHE_PATH
    BASE_DIR = Path(d)
    CONFIG_PATH = BASE_DIR / "config.json"
    LOG_PATH = BASE_DIR / "send_trending.log"
    TRANSLATION_CACHE_PATH = BASE_DIR / "translation_cache.json"
    _setup_logging()


def _setup_logging():
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        root.addHandler(logging.FileHandler(LOG_PATH, encoding="utf-8"))
    except OSError:
        pass
    root.setLevel(logging.INFO)


class _QueueHandler(logging.Handler):
    def __init__(self, q):
        super().__init__()
        self.q = q

    def emit(self, record):
        try:
            self.q.put(("log", self.format(record)))
        except Exception:
            pass


def attach_log_queue(q):
    """GUI 用：将日志同时推送到队列，由 UI 轮询显示。"""
    h = _QueueHandler(q)
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
    logging.getLogger().addHandler(h)


# ---------- 配置 ----------
def read_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k, v in data.items():
                    cfg[k] = v
                if isinstance(data.get("smtp"), dict):
                    cfg["smtp"] = {**cfg["smtp"], **data["smtp"]}
                legacy_auth = str(cfg["smtp"].get("auth_code", "") or "")
                username = cfg["smtp"].get("user", "")
                if legacy_auth and sys.platform == "win32":
                    # Migrate old plaintext settings before returning the config.
                    _store_auth_code(username, legacy_auth)
                    safe_data = dict(data)
                    safe_smtp = dict(data.get("smtp") or {})
                    safe_smtp.pop("auth_code", None)
                    safe_data["smtp"] = safe_smtp
                    temp_path = CONFIG_PATH.with_suffix(".tmp")
                    with open(temp_path, "w", encoding="utf-8") as f:
                        json.dump(safe_data, f, ensure_ascii=False, indent=2)
                    temp_path.replace(CONFIG_PATH)
                    logging.info("已将 SMTP 授权码迁移到 Windows 凭据管理器")
                    cfg["smtp"]["auth_code"] = legacy_auth
                elif not legacy_auth:
                    cfg["smtp"]["auth_code"] = _load_auth_code(username)
                cfg["translation_api_key"] = _load_auth_code("translation:StarTrace", "Translation")
                if not cfg["translation_api_key"]:
                    # Read keys saved by the earlier URL-specific credential scheme.
                    cfg["translation_api_key"] = _load_auth_code(
                        "translation:" + str(cfg.get("translation_url", "")), "Translation")
        except json.JSONDecodeError as e:
            logging.warning("配置文件解析失败，使用默认配置：%s", e)
        except OSError as e:
            logging.error("配置读取或授权码安全迁移失败：%s", e)
        except Exception as e:
            logging.error("SMTP 授权码迁移失败，原配置文件已保留：%s", e)
    return cfg


def save_config(cfg):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    safe_cfg = json.loads(json.dumps(cfg))
    smtp = safe_cfg.get("smtp") or {}
    auth_code = str(smtp.pop("auth_code", "") or "")
    if auth_code:
        _store_auth_code(smtp.get("user", ""), auth_code)
    api_key = str(safe_cfg.pop("translation_api_key", "") or "")
    if api_key:
        _store_auth_code("translation:StarTrace", api_key, "Translation")
    temp_path = CONFIG_PATH.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(safe_cfg, f, ensure_ascii=False, indent=2)
    temp_path.replace(CONFIG_PATH)
    logging.info("配置已保存：%s", CONFIG_PATH)


def validate_config(cfg):
    """校验配置，非法时抛出 ValueError（含中文提示）。"""
    smtp = cfg.get("smtp") or {}
    if not str(smtp.get("user", "")).strip():
        raise ValueError("请填写发件邮箱（smtp.user）")
    if not str(smtp.get("auth_code", "")).strip():
        raise ValueError("请填写 SMTP 授权码（smtp.auth_code）")
    if not smtp.get("host"):
        raise ValueError("SMTP 服务器地址（smtp.host）不能为空")
    to = cfg.get("to") or []
    if isinstance(to, str):
        to = [to]
    if not to or not any(str(x).strip() for x in to):
        raise ValueError("请至少填写一个收件邮箱（to）")
    try:
        int(smtp.get("port", 465))
    except (TypeError, ValueError):
        raise ValueError("SMTP 端口必须为数字")
    try:
        top_n = int(cfg.get("top_n", 25))
    except (TypeError, ValueError):
        raise ValueError("推送数量（top_n）必须为数字")
    if not 5 <= top_n <= 50:
        raise ValueError("推送数量应设置为 5 到 50 条")
    if not re.match(r"^\d{1,2}:\d{2}$", str(cfg.get("send_time", ""))):
        raise ValueError("推送时间格式应为 HH:MM，如 09:00")


# ---------- 网络 ----------
def http_get(url, api=False, timeout=30):
    headers = {"User-Agent": USER_AGENT}
    if api:
        headers["Accept"] = "application/vnd.github+json"
    last = None
    for attempt in range(3):  # 自动重试，规避临时限流
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            time.sleep(3 * (attempt + 1))
    raise last


def human_stars(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "?"
    if n >= 1000:
        v = f"{n / 1000.0:.1f}".rstrip("0").rstrip(".")
        return f"{v}k"
    return str(n)


# ---------- 抓取 Trending（主方案：抓页面；备用：Search API） ----------
def fetch_trending(language, top_n):
    if language != "all":
        path = f"https://github.com/trending/{language}?since=daily"
    else:
        path = "https://github.com/trending?since=daily"
    fallback_reason = ""
    try:
        html = http_get(path)
        repos = parse_trending_html(html)
        if len(repos) < 5:
            raise ValueError("解析结果过少")
        if len(repos) < int(top_n):
            logging.info("GitHub Trending 页面仅返回 %d 条，改用 Search API 补足到 %d 条。", len(repos), top_n)
            fallback_reason = f"Trending 页面仅返回 {len(repos)} 条"
        else:
            for repo in repos:
                repo["source"] = "trending_daily"
            return repos[:top_n]
    except Exception as e:
        logging.warning("Trending 页面抓取失败（%s），改用 GitHub Search API 备用方案", e)
        fallback_reason = str(e)

    try:
        return fetch_via_search_api(top_n, language)
    except Exception as fallback_error:
        logging.error("GitHub Search API 备用抓取失败：%s", fallback_error)
        raise RuntimeError(
            "无法连接 GitHub Trending 或 Search API。请检查当前网络、代理/VPN 或防火墙后重试。"
            f"（Trending：{fallback_reason}；Search API：{fallback_error}）"
        ) from fallback_error


def _clean(text):
    text = re.sub(r"<[^>]+>", "", text or "")
    # Descriptions can be escaped more than once in scraped markup.
    for _ in range(3):
        decoded = unescape(text)
        if decoded == text:
            break
        text = decoded
    return re.sub(r"\s+", " ", text).strip()


def parse_trending_html(html):
    repos = []
    for row in re.split(r'<article\s+class="Box-row"', html)[1:]:
        m = re.search(r'<h2[^>]*>[\s\S]*?href="/([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+)"', row)
        if not m:
            continue
        name = m.group(1)
        m_desc = re.search(r'<p class="col-9[^>]*>([\s\S]*?)</p>', row)
        desc = _clean(m_desc.group(1)) if m_desc else ""
        m_lang = re.search(r'itemprop="programmingLanguage">([^<]+)</span>', row)
        lang = m_lang.group(1).strip() if m_lang else "—"
        m_star = re.search(r'href="/[^"]+/stargazers"[\s\S]*?</svg>\s*([\d.,]+k?)\s*</a>', row)
        stars = m_star.group(1).strip() if m_star else "?"
        m_today = re.search(r"([\d.,]+k?)\s+stars today", row)
        today = m_today.group(1) if m_today else ""
        repos.append(
            {
                "name": name,
                "url": f"https://github.com/{name}",
                "desc": desc,
                "lang": lang,
                "stars": stars,
                "today": today,
            }
        )
    return repos


def fetch_via_search_api(top_n, language="all"):
    since = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    query = f"created:>{since}"
    if language and language != "all":
        query += f" language:{language}"
    params = urllib.parse.urlencode({"q": query, "sort": "stars", "order": "desc",
                                    "per_page": min(top_n, 50)})
    url = f"https://api.github.com/search/repositories?{params}"
    data = json.loads(http_get(url, api=True))
    items = data.get("items", [])
    if not items:
        raise RuntimeError("无法获取 GitHub 数据，请检查网络后重试。")
    repos = []
    for it in items:
        repos.append(
            {
                "name": it["full_name"],
                "url": it["html_url"],
                "desc": (it.get("description") or "").strip(),
                "lang": it.get("language") or "—",
                "stars": human_stars(it.get("stargazers_count", 0)),
                "today": "",
                "source": "search_7d",
            }
        )
    return repos[:top_n]


def source_label(repos):
    source = next((r.get("source") for r in repos if r.get("source")), "trending_daily")
    if source == "search_7d":
        return "GitHub Search API（近 7 天新建，按 Stars 排序）"
    return "GitHub Trending（daily）"


# ---------- 邮件 ----------
def _read_translation_cache():
    try:
        with open(TRANSLATION_CACHE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _local_model_dir():
    local_root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return local_root / APP_NAME / "models"


def translation_model_ready():
    return (_local_model_dir() / TRANSLATION_MODEL_NAME).is_file()


def _download_file(url, destination, label, expected_size=None):
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".download")
    urls = (url,) if isinstance(url, str) else tuple(url)
    last_error = None
    for index, source_url in enumerate(urls):
        try:
            if index:
                logging.warning("国内模型源暂不可用，正在切换备用源。")
            request = urllib.request.Request(source_url, headers={"User-Agent": USER_AGENT})
            received = 0
            last_report_bytes = 0
            last_report_step = -1
            with urllib.request.urlopen(request, timeout=90) as response, open(partial, "wb") as output:
                total = int(response.headers.get("Content-Length") or expected_size or 0)
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    output.write(block)
                    received += len(block)
                    if total:
                        percent = min(100, int(received * 100 / total))
                        step = percent // 10
                        if step > last_report_step:
                            logging.info("正在下载%s：%d%%（%.0f MB / %.0f MB）", label,
                                         percent, received / 1024 / 1024, total / 1024 / 1024)
                            last_report_step = step
                    elif received - last_report_bytes >= 50 * 1024 * 1024:
                        logging.info("正在下载%s：%.0f MB", label, received / 1024 / 1024)
                        last_report_bytes = received
            if expected_size and received < expected_size * 0.95:
                raise RuntimeError(f"{label}下载不完整，请检查网络后重试")
            partial.replace(destination)
            return
        except Exception as exc:
            last_error = exc
            partial.unlink(missing_ok=True)
            if index + 1 < len(urls):
                continue
    raise RuntimeError(f"{label}下载失败：{last_error}") from last_error


def _ensure_llama_server(model_dir):
    runtime_dir = model_dir / "llama.cpp" / LLAMA_CPP_VERSION
    matches = list(runtime_dir.rglob("llama-server.exe")) if runtime_dir.exists() else []
    if matches:
        return matches[0]
    archive = model_dir / f"llama-{LLAMA_CPP_VERSION}-win-cpu.zip"
    if not archive.exists():
        logging.info("首次使用高质量翻译，需要下载本地推理组件。")
        _download_file(LLAMA_CPP_URL, archive, "本地推理组件")
    runtime_dir.mkdir(parents=True, exist_ok=True)
    root = runtime_dir.resolve()
    with zipfile.ZipFile(archive) as package:
        for item in package.infolist():
            target = (runtime_dir / item.filename).resolve()
            if target != root and root not in target.parents:
                raise RuntimeError("推理组件压缩包包含无效路径")
        package.extractall(runtime_dir)
    matches = list(runtime_dir.rglob("llama-server.exe"))
    if not matches:
        raise RuntimeError("推理组件中没有找到 llama-server.exe")
    return matches[0]


def _ensure_translation_server():
    """Download and run Index-Translate locally on the loopback interface."""
    global _TRANSLATION_PROCESS, _TRANSLATION_PORT
    with _TRANSLATION_LOCK:
        if _TRANSLATION_PROCESS and _TRANSLATION_PROCESS.poll() is None:
            return _TRANSLATION_PORT
        model_dir = _local_model_dir()
        model_path = model_dir / TRANSLATION_MODEL_NAME
        if not model_path.exists():
            logging.info("首次使用中文翻译，从 ModelScope 国内源下载 Index-Translate 2B（约 1.31 GB）。")
            _download_file(TRANSLATION_MODEL_URLS, model_path, "Index-Translate 翻译模型",
                           TRANSLATION_MODEL_SIZE)
        server = _ensure_llama_server(model_dir)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        command = [str(server), "--model", str(model_path), "--host", "127.0.0.1",
                   "--port", str(port), "--alias", "Index-Translate-2B",
                   "--ctx-size", "4096", "--threads",
                   str(max(2, min(os.cpu_count() or 4, 8))), "--parallel", "1",
                   "--jinja", "--reasoning", "off",
                   "--no-webui"]
        _TRANSLATION_PROCESS = subprocess.Popen(
            command, cwd=str(server.parent), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
        _TRANSLATION_PORT = port
        for _ in range(360):
            if _TRANSLATION_PROCESS.poll() is not None:
                raise RuntimeError("本地翻译模型启动失败，请在设置页查看运行记录")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                    if response.status == 200:
                        logging.info("Index-Translate 本地翻译模型已就绪。")
                        return port
            except Exception:
                time.sleep(1)
        _TRANSLATION_PROCESS.terminate()
        _TRANSLATION_PROCESS = None
        raise RuntimeError("本地翻译模型启动超时；请检查可用内存后重试")


def prepare_translation_model():
    """Download the local translation model if needed and start its local server."""
    _ensure_translation_server()
    return True


def _stop_translation_server():
    if _TRANSLATION_PROCESS and _TRANSLATION_PROCESS.poll() is None:
        _TRANSLATION_PROCESS.terminate()


atexit.register(_stop_translation_server)


def _translate_one(text):
    if not text:
        return ""
    try:
        port = _ensure_translation_server()
        prompt = (
            "请将以下 GitHub 项目简介翻译为简体中文，直接输出翻译结果，不要进行任何解释。"
            "请使用自然、准确的中文表达，并保留项目名、产品名、框架名、编程语言和代码标识。\n\n" + text
        )
        payload = json.dumps({
            "model": "Index-Translate-2B", "messages": [{"role": "user", "content": prompt}],
            "temperature": 0, "max_tokens": 512, "stream": False,
        }).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.loads(response.read().decode("utf-8"))
        return str(result["choices"][0]["message"]["content"]).strip()
    except Exception as exc:
        logging.warning("本地翻译失败：%s", exc)
        return ""


def _translate_remote(text, cfg):
    url = str(cfg.get("translation_url", "")).strip().rstrip("/")
    model = str(cfg.get("translation_model", "")).strip()
    key = str(cfg.get("translation_api_key", "")).strip()
    if not url or not model or not key:
        raise ValueError("请在设置中填写翻译 API 地址、模型名称和 API Key")
    endpoint = url if url.endswith("/chat/completions") else url + "/chat/completions"
    prompt = ("请将以下 GitHub 项目简介翻译为简体中文，直接输出翻译结果，不要解释。"
              "中文表达自然准确，保留项目名、产品名、框架名、编程语言和代码标识。\n\n" + text)
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                       "temperature": 0, "max_tokens": 512}).encode("utf-8")
    request = urllib.request.Request(endpoint, data=body, headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + key,
        "User-Agent": USER_AGENT,
    }, method="POST")
    with urllib.request.urlopen(request, timeout=90) as response:
        result = json.loads(response.read().decode("utf-8"))
    return str(result["choices"][0]["message"]["content"]).strip()


def translate_descriptions(repos):
    """Add cached Chinese translations while keeping original English descriptions."""
    cache = _read_translation_cache()
    pending = {}
    for repo in repos:
        source = str(repo.get("desc") or "").strip()
        repo["desc_en"] = source
        repo["desc_zh"] = "暂无项目简介" if not source else ""
        if not source:
            continue
        key = hashlib.sha256(("translation-v5-index-translate-2b\0" + source).encode("utf-8")).hexdigest()
        if key in cache:
            repo["desc_zh"] = cache[key]
        else:
            pending.setdefault(key, source)

    if pending:
        translations = {}
        with ThreadPoolExecutor(max_workers=1) as pool:
            futures = {pool.submit(_translate_one, value): key for key, value in pending.items()}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    translations[key] = future.result()
                except Exception:
                    translations[key] = ""
        cache.update({key: value for key, value in translations.items() if value})
        try:
            TRANSLATION_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            temp_path = TRANSLATION_CACHE_PATH.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
            temp_path.replace(TRANSLATION_CACHE_PATH)
        except OSError as exc:
            logging.info("无法保存简介翻译缓存：%s", exc)
        for repo in repos:
            source = str(repo.get("desc") or "").strip()
            if source:
                key = hashlib.sha256(("translation-v5-index-translate-2b\0" + source).encode("utf-8")).hexdigest()
                repo["desc_zh"] = translations.get(key, cache.get(key, ""))

    # Apply the wording correction to both fresh results and cached entries.
    idiom_fixes = [
        (r"运行在您的机器上的求职", "可在本机运行的求职工具"),
        (r"AI\s*工作申请框架", "AI 求职辅助工具"),
        (r"评估张贴", "评估招聘信息"),
        (r"裁剪\s*CV", "定制简历"),
        (r"写封面信", "撰写求职信"),
        (r"叉开它并拥有它", "Fork 这个项目，并按自己的需求进行修改"),
    ]
    for repo in repos:
        translated = str(repo.get("desc_zh") or "")
        for pattern, replacement in idiom_fixes:
            translated = re.sub(pattern, replacement, translated, flags=re.I)
        repo["desc_zh"] = translated


def _clip_description(text, limit=180):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:，。；：") + "…"


def build_mail_payload(repos, date_str, lang_label, include_chinese=False, translator=None,
                       translation_label=""):
    for repo in repos:
        repo["desc_en"] = str(repo.get("desc_en") or repo.get("desc") or "")
    if include_chinese:
        if translator:
            for repo in repos:
                source = str(repo.get("desc") or "").strip()
                repo["desc_en"] = source
                repo["desc_zh"] = translator(source) if source else "暂无项目简介"
        else:
            translate_descriptions(repos)
    rows_txt, rows_html = [], []
    for i, r in enumerate(repos, 1):
        en = str(r.get("desc_en") or "")
        zh = str(r.get("desc_zh") or "")
        stars = html.escape(str(r.get("stars", "?")))
        today = html.escape(str(r.get("today", "")))
        lang = html.escape(str(r.get("lang", "未标注")))
        name = html.escape(str(r.get("name", "")))
        url = html.escape(str(r.get("url", "")), quote=True)
        desc_txt = (f"English: {en}\n" if en else "") + (f"中文：{zh or '暂时无法翻译'}" if include_chinese else "")
        rows_txt.append(
            f"{i:02d}  {r.get('name', '')}\n"
            f"Stars {r.get('stars', '?')}  ·  今日新增 {('+' + str(r.get('today'))) if r.get('today') else '暂无数据'}  ·  {r.get('lang') or '未标注'}\n"
            f"{desc_txt}\n{r.get('url', '')}"
        )
        zh_html = (f"<div style='margin-top:7px;color:#24292f;'>中文：{html.escape(zh)}</div>" if zh else "<div style='margin-top:7px;color:#6e7781;'>中文：暂时无法翻译</div>") if include_chinese else ""
        en_html = f"<div style='color:#6e7781;'>English: {html.escape(en)}</div>" if en else ""
        today_label = f"今日新增 <b style='color:#176b45;'>+{today}</b>" if today else "今日新增 —"
        rows_html.append(
            f"<tr><td style='padding:0 0 10px;'>"
            f"<table role='presentation' style='width:100%;border:1px solid #e3e6e8;border-collapse:collapse;background:#fff;'>"
            f"<tr><td style='padding:12px 14px 5px;'>"
            f"<span style='display:inline-block;width:30px;color:#7a8288;font:600 13px Consolas,monospace;'>{i:02d}</span>"
            f"<a href='{url}' style='color:#1f2328;font-weight:650;font-size:16px;text-decoration:none;word-break:break-word;'>{name}</a>"
            f"</td></tr><tr><td style='padding:3px 14px 8px;color:#59636e;font-size:12px;line-height:1.6;'>"
            f"<span>Stars <b style='color:#30363d;'>{stars}</b></span><span style='padding-left:14px;'>{today_label}</span>"
            f"<span style='padding-left:14px;'>{lang}</span></td></tr>"
            f"<tr><td style='padding:2px 14px 12px;color:#30363d;font-size:13px;line-height:1.6;'>"
            f"{en_html}{zh_html}"
            f"<div style='margin-top:8px;'><a href='{url}' style='color:#0969da;text-decoration:none;'>查看项目</a></div>"
            f"</td></tr></table></td></tr>"
        )

    subject = f"GitHub 项目日报（StarTrace）· {date_str} · Top {len(repos)}"
    data_source = source_label(repos)
    translation_note = f"简介翻译：{translation_label}" if include_chinese and translation_label else ""
    text_body = (
        f"GitHub 项目日报 · {date_str} · {lang_label} · Top {len(repos)}\n\n"
        + "\n".join(rows_txt)
        + (f"\n\n{translation_note}" if translation_note else "")
        + f"\n数据来源：{data_source}\n{APP_NAME}"
    )
    html_body = f"""<!DOCTYPE html><html><head><meta charset='utf-8'></head>
<body style='font-family:Segoe UI,Microsoft YaHei,Arial,sans-serif;background:#f5f6f7;padding:18px;'>
<div style='max-width:680px;margin:auto;background:#fff;border:1px solid #e1e4e8;'>
<div style='color:#202428;padding:18px 20px 14px;border-bottom:1px solid #e6e8eb;'>
<h2 style='margin:0;font-size:19px;font-weight:650;'>GitHub 项目日报</h2>
<div style='color:#687078;font-size:13px;margin-top:6px;'>{date_str}　·　{lang_label}　·　Top {len(repos)}</div>
</div>
<table role='presentation' style='width:100%;border-collapse:collapse;font-size:14px;'><tr><td style='padding:16px;'><table role='presentation' style='width:100%;border-collapse:collapse;'>{''.join(rows_html)}</table></td></tr></table>
<div style='padding:12px 20px;color:#70777e;font-size:12px;line-height:1.6;border-top:1px solid #e6e8eb;'>
{(html.escape(translation_note) + '　' if translation_note else '')}数据来源：{html.escape(data_source)}<br>
{APP_NAME}
</div>
</div></body></html>"""
    return subject, text_body, html_body


def send_email(cfg, subject, html_body, text_body=""):
    smtp = cfg["smtp"]
    user = smtp["user"]
    to = cfg["to"] if isinstance(cfg["to"], list) else [cfg["to"]]
    to = [str(x).strip() for x in to if str(x).strip()]
    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header(cfg.get("from_name", APP_NAME), "utf-8")), user))
    msg["To"] = ", ".join(to)
    msg["Date"] = formatdate(localtime=True)

    port = int(smtp.get("port", 465))
    if port == 465:
        server = smtplib.SMTP_SSL(smtp["host"], port, timeout=60, context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(smtp["host"], port, timeout=60)
        server.ehlo()
        server.starttls(context=ssl.create_default_context())
        server.ehlo()
    try:
        server.login(user, smtp["auth_code"])
        server.sendmail(user, to, msg.as_string())
    finally:
        server.quit()


def send_today_mail(cfg):
    """抓取今日榜单并发送邮件，返回 (日期, 项目数, 收件人)。"""
    lang = str(cfg.get("language", "all")).strip().lower()
    lang_label = lang if lang != "all" else "全部语言"
    top_n = int(cfg.get("top_n", 25))
    repos = fetch_trending(lang, top_n)
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    translator = None
    translation_label = ""
    if cfg.get("include_chinese"):
        if cfg.get("translation_provider") == "remote":
            model = str(cfg.get("translation_model", "")).strip() or "未填写模型名"
            translation_label = f"云大模型：{model}"
            translator = lambda text: _translate_remote(text, cfg)
        else:
            translation_label = "本地模型：Index-Translate-2B"
    subject, text_body, html_body = build_mail_payload(
        repos, date_str, lang_label, bool(cfg.get("include_chinese", False)), translator,
        translation_label)
    send_email(cfg, subject, html_body, text_body)
    to = cfg["to"] if isinstance(cfg["to"], list) else [cfg["to"]]
    logging.info("已发送邮件 subject=%s to=%s", subject, to)
    return date_str, len(repos), ", ".join(str(x) for x in to)


# ---------- Windows 定时任务 ----------
def _q(p):
    s = str(p)
    return f'"{s}"' if " " in s else s


def _task_command():
    if getattr(sys, "frozen", False):
        return f"{_q(Path(sys.executable))} --send"
    pyw = Path(sys.executable).with_name("pythonw.exe")
    exe = pyw if pyw.exists() else sys.executable
    return f"{_q(exe)} {_q(BASE_DIR / 'send_trending.py')} --send"


def register_task(time_str):
    if not re.match(r"^\d{1,2}:\d{2}$", str(time_str)):
        raise ValueError(f"时间格式应为 HH:MM，收到：{time_str}")
    tr = _task_command()
    cmd = ["schtasks", "/Create", "/TN", TASK_NAME, "/TR", tr, "/SC", "DAILY", "/ST", time_str, "/F"]
    subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8",
                   errors="replace", creationflags=CREATE_NO_WINDOW)
    logging.info("已注册定时任务 %s，每天 %s", TASK_NAME, time_str)


def unregister_task():
    r = subprocess.run(
        ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )
    if r.returncode != 0 and "没有运行" not in r.stdout + r.stderr:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip() or "删除定时任务失败")
    logging.info("已删除定时任务 %s", TASK_NAME)


def task_info():
    """查询定时任务状态，返回 (是否已注册, 下次运行时间或 None)。"""
    try:
        r = subprocess.run(
            ["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception:
        return False, None
    if r.returncode != 0:
        return False, None
    m = re.search(r"\d{4}/\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2}", r.stdout)
    return True, (m.group(0) if m else None)


def open_base_dir():
    os_startfile(BASE_DIR)


def os_startfile(path):
    import os
    if sys.platform == "win32":
        os.startfile(str(path))  # noqa
    else:
        subprocess.Popen(["open", str(path)])


_setup_logging()
