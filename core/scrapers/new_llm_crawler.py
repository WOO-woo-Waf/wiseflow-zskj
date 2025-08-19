# -*- coding: utf-8 -*-
# 通用新闻爬虫（重构版：同栏目深爬 + 三要素抽取 + LLM 兜底一次）
# flag 语义（保持兼容）：
#  -7: 抓取/解码错误
#   0: 解析失败
#   1: 列表页，payload 为链接集合（集合 set[str]）
#  11: 详情页，payload 为 dict：至少包含 title / publish_time / content / url
import re
import sys
import os
import asyncio
from typing import Union, Tuple, Set, Dict, Optional
from collections import deque
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, urlsplit, urlunsplit, urljoin

import httpx
from bs4 import BeautifulSoup
from bs4.element import Comment
from gne import GeneralNewsExtractor
from dotenv import load_dotenv

from llms.openai_wrapper import openai_llm
from utils.general_utils import extract_and_convert_dates
import json_repair

# -------------------- 环境 & 全局 --------------------
ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)

model = os.environ.get("HTML_PARSE_MODEL", "DeepSeek-V3")
header = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Chrome/112.0.0.0 Safari/604.1 Edg/112.0.100.0"
    )
}
extractor = GeneralNewsExtractor()

# LLM 提示：要求输出 title/content/publish_time 原样字段
sys_info = '''Your task is to operate as an HTML content extractor, focusing on parsing a provided HTML segment. Your objective is to retrieve the following details directly from the raw text within the HTML, without summarizing or altering the content:

- The document's title
- The complete main content, as it appears in the HTML, comprising all textual elements considered part of the core article body
- The publication time in its original format found within the HTML

Ensure your response fits the following JSON structure, accurately reflecting the extracted data without modification:

{
  "title": "The Document's Exact Title",
  "content": "All the unaltered primary text content from the article",
  "publish_time": "Original Publication Time as per HTML"
}

It is essential that your output adheres strictly to this format, with each field filled based on the untouched information extracted directly from the HTML source.'''

# -------------------- 常量/正则 --------------------
try:
    from charset_normalizer import from_bytes as cn_from_bytes
except Exception:
    cn_from_bytes = None

REQUEST_TIMEOUT = 30
RETRY_TIMES = 2
MIN_LIST_LINKS = 20
MAX_LLM_TEXT_LEN = 29999

# hebei.gov.cn 等常见详情链接形态
DETAIL_PATTERNS = [
    re.compile(r"/t\d{8}_\d+\.html$"),
    re.compile(r"/\d{6,8}/t\d{8}_\d+\.html$"),
    re.compile(r"/content_\d+\.html$"),
    re.compile(r"/\d{4}(?:\d{2})?/\d{2}/[0-9a-f-]{8,}\.html$"),  # .../202505/30/uuid.html
]
# hebei.gov.cn 的栏目路径（columns/<uuid>/...）
COLUMN_ROOT_RE = re.compile(r"^/columns/(?P<cid>[0-9a-f-]{8,})/")

# 列表页结构/日期密度识别
LIST_CLASS_HINTS = (
    ".pagination", ".pager", ".pagebar", ".page", ".pages",
    ".list", ".news-list", ".list-unstyled", ".list-group"
)
DATE_REGEX = re.compile(r"(20\d{2})[.\-/年](\d{1,2})[.\-/月](\d{1,2})日?")

# 导航/侧栏/分页等应排除区域
EXCLUDE_ANCESTOR_SELECTORS = (
    "header", "nav", "footer",
    ".submenu", ".sub-menu", ".dropdown", ".dropdown-menu", ".menu", ".menus", ".navbar",
    ".top-nav", ".topbar", ".toolbar", ".bread", ".breadcrumb", ".breadcrumbs",
    ".sidebar", ".aside", ".left-nav", ".right-nav", ".sidenav", ".side-menu",
    ".pager", ".pagination", ".pagebar", ".pages", ".tab", ".tabs", ".tabbar",
    ".logo", ".site-nav", ".global-nav"
)

ONCLICK_URL_RE = re.compile(
    r"(?:window\.open|location\.href\s*=|open)\s*\(\s*['\"](?P<u>[^'\"]+)['\"]",
    re.I
)

# -------------------- 基础工具 --------------------
def _normalize_encoding(enc: Optional[str]) -> Optional[str]:
    if not enc:
        return None
    e = enc.strip().lower()
    if e in {"utf8", "utf-8", "utf_8"}:
        return "utf-8"
    if e in {"gbk", "gb2312", "gb-2312", "gb_2312-80", "gb-18030", "gb18030"}:
        return "gb18030"
    if e in {"cp936"}:
        return "cp936"
    if e in {"big5", "big-5"}:
        return "big5"
    return e

# ---- 全局连接池（HTTP/2 + 限流），替换 _fetch 使用 ----
_HTTP_CLIENT = None

def get_http_client() -> httpx.AsyncClient:
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None:
        _HTTP_CLIENT = httpx.AsyncClient(
            http2=True,
            headers=header,
            follow_redirects=True,
            timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=REQUEST_TIMEOUT),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
    return _HTTP_CLIENT

async def _fetch(url: str, logger) -> Tuple[httpx.Response, str]:
    """
    使用全局连接池；退避 2s -> 5s；不再 60s 卡死事件循环。
    """
    client = get_http_client()
    delays = (2, 5)
    last_exc = None
    for i, delay in enumerate(delays + (None,)):  # 最后一次不 sleep
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            final_url = str(resp.url)
            if resp.history:
                logger.debug(f"redirected: {url} -> {final_url} ({[r.status_code for r in resp.history]})")
            return resp, final_url
        except Exception as e:
            last_exc = e
            if delay is not None:
                logger.info(f"fetch retry in {delay}s: {url} ({e})")
                await asyncio.sleep(delay)
    raise last_exc

# ---- 更快的解码器：先试快路径，再少量样本让 charset_normalizer 猜测 ----
def _decode_response_text(response, logger) -> str:
    raw = response.content or b""
    if not raw:
        return ""

    # 快路径 0：已知编码
    if response.encoding:
        try:
            return raw.decode(_normalize_encoding(response.encoding) or "utf-8", errors="strict")
        except Exception:
            pass

    # 快路径 1：先尝试 utf-8 / gb18030（覆盖绝大多数中文政务站）
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except Exception:
            continue

    # 快路径 2：HTTP 头与 <meta charset>
    enc = None
    ct = response.headers.get("Content-Type", "")
    m = re.search(r"charset=([^\s;]+)", ct, flags=re.I)
    if m:
        enc = _normalize_encoding(m.group(1))
        try:
            return raw.decode(enc)
        except Exception:
            pass

    head = raw[:8192]
    m = re.search(br"<meta[^>]+charset=['\"]?\s*([a-zA-Z0-9_\-]+)", head, flags=re.I) or \
        re.search(br"http-equiv=['\"]?content-type['\"][^>]*content=['\"][^;]+;\s*charset=([a-zA-Z0-9_\-]+)", head, flags=re.I)
    if m:
        try:
            enc = _normalize_encoding(m.group(1).decode("ascii", "ignore"))
            return raw.decode(enc)
        except Exception:
            pass

    # 慢路径：仅对前 64KB 进行 charset_normalizer 猜测（避免整页大文件卡慢）
    if cn_from_bytes:
        try:
            r = cn_from_bytes(raw[:65536]).best()
            if r and r.encoding:
                enc = _normalize_encoding(r.encoding)
                return raw.decode(enc)
        except Exception:
            pass

    # 最后兜底
    logger.warning("decode fallback to response.text (may be wrong).")
    return response.text or ""


def tag_visible(element: Comment) -> bool:
    if element.parent and element.parent.name in ["style", "script", "head", "title", "meta", "[document]"]:
        return False
    if isinstance(element, Comment):
        return False
    return True

def text_from_soup(soup: BeautifulSoup) -> str:
    texts = soup.find_all(string=True)
    vt = filter(tag_visible, texts)
    res = [v.strip() for v in vt if str(v).strip()]
    return "\n".join(res).strip()

def _canonicalize(u: str) -> str:
    """规范 URL：去掉 fragment，清洗部分跟踪参数，归一 host 大小写与多余斜杠。"""
    p = urlsplit(u)
    # 清洗常见跟踪参数
    q = re.sub(r"(?:^|&)(utm_[^&]+|from|spm)=[^&]*", "", p.query).strip("&")
    path = re.sub(r"/{2,}", "/", p.path)
    return urlunsplit((p.scheme, p.netloc.lower(), path, q, ""))

def _same_etld1(a: str, b: str) -> bool:
    def norm(h: str) -> str:
        h = h.lower()
        return h[4:] if h.startswith("www.") else h
    return norm(a) == norm(b)

def _is_in_excluded_zone(el) -> bool:
    try:
        for sel in EXCLUDE_ANCESTOR_SELECTORS:
            if el.find_parent(sel):
                return True
    except Exception:
        pass
    return False

# -------------------- 页面/栏目判定 --------------------
def _is_detail_like_url(url: str) -> bool:
    path = urlsplit(url).path
    return any(p.search(path) for p in DETAIL_PATTERNS)

def _is_same_column(base_url: str, candidate_url: str) -> bool:
    """
    仅允许在“同一栏目根”下深入：
    例：/columns/de3fe4ea-.../index.html -> /columns/de3fe4ea-.../202505/30/*.html ✅
       /columns/OTHER-.../... ❌
    若 base 非 columns 结构，则退化为“同目录前缀”限定。
    """
    bp, cp = urlsplit(base_url), urlsplit(candidate_url)
    if not _same_etld1(bp.netloc, cp.netloc):
        return False
    bm, cm = COLUMN_ROOT_RE.search(bp.path or ""), COLUMN_ROOT_RE.search(cp.path or "")
    if bm and cm:
        return bm.group("cid") == cm.group("cid")
    # 非 columns 结构：使用目录前缀限定
    base_dir = re.sub(r"index\.html?$", "", bp.path or "").rstrip("/")
    return (cp.path or "/").startswith(base_dir + "/")

def is_list_like_page(soup: BeautifulSoup) -> bool:
    if any(soup.select(sel) for sel in LIST_CLASS_HINTS):
        return True
    text = soup.get_text(" ", strip=True)[:100000]
    return len(DATE_REGEX.findall(text)) >= 5

def classify_page(final_url: str, soup: BeautifulSoup) -> str:
    if _is_detail_like_url(final_url):
        return "detail"
    return "list" if is_list_like_page(soup) else "unknown"

# -------- 强化：从 DOM 中抓 JS 导航类链接 --------
def _extract_js_nav_urls_from_dom(final_url: str, soup: BeautifulSoup) -> set[str]:
    """
    从 onclick / data-* / role="link|button" 等 DOM 属性里抽取导航 URL。
    注意：这里只“发现”URL，不做同栏目/新闻感过滤；统一交给上层过滤。
    """
    urls = set()
    # 1) onclick/data-href/data-url/data-link/role="link|button"
    candidates = soup.select(
        '[onclick], [data-href], [data-url], [data-link], [data-target], [role="link"], [role="button"]'
    )
    for el in candidates:
        # 排除导航/菜单/页脚/侧栏等
        if _is_in_excluded_zone(el):
            continue

        # onclick 解析
        cand = None
        if el.has_attr("onclick"):
            m = ONCLICK_URL_RE.search(el.get("onclick") or "")
            if m:
                cand = m.group("u")

        # data-* 解析
        if not cand:
            for attr in ("data-href", "data-url", "data-link", "data-target"):
                if el.has_attr(attr) and el.get(attr):
                    cand = el.get(attr)
                    break

        # 如果这个“看起来像链接”的元素里面本来就有 <a>，也兜一下
        if not cand:
            a = el.find("a", href=True)
            if a and a.get("href"):
                cand = a["href"]

        if not cand:
            continue

        abs_url = _canonicalize(urljoin(final_url, cand.strip()))
        # 丢掉空/锚点
        if abs_url and not abs_url.endswith("#"):
            urls.add(abs_url)

    return urls

# -------- 强化：从 <script> 文本块中提取同栏目 URL --------
SCRIPT_URL_RE = re.compile(
    r"""(?P<q>["'])                                     # 引号
        (?P<u>(?:https?:)?//[^"']+?|/[^"']+?)           # URL（绝对或相对）
        (?P=q)                                          # 同引号闭合
    """,
    re.X | re.I,
)

def _extract_urls_from_script_blocks(final_url: str, soup: BeautifulSoup) -> set[str]:
    """
    从脚本块里提取字符串常量形式的 URL。
    - 兼容 JSON 初始化（__INITIAL_STATE__/__NEXT_DATA__）
    - 兼容字符串数组/list 中直接写死的链接
    这里只负责“捞”，不上过滤与同栏目判定。
    """
    urls = set()
    for js in soup.find_all("script"):
        # 只取可见文本（忽略巨大内联框架/空脚本）
        content = js.string or js.get_text("", strip=True) or ""
        if not content or len(content) < 5:
            continue

        # 1) 优先解析 JSON（常见数据块）
        if ("__INITIAL_STATE__" in content or "__NEXT_DATA__" in content
            or content.lstrip().startswith("{") or content.lstrip().startswith("[")):
            try:
                import json
                # 尝试提纯 JSON：找到第一个 { 或 [
                start = min([i for i in (content.find("{"), content.find("[")) if i != -1], default=-1)
                if start >= 0:
                    maybe = content[start:]
                    # 宽容解析：尽量把外层 JSON 读出来（失败则回退到正则抽）
                    data = json_repair.repair_json(maybe, return_objects=True)
                    # 深度搜集 value 中的 URL 字符串
                    def walk(x):
                        if isinstance(x, dict):
                            for v in x.values(): walk(v)
                        elif isinstance(x, list):
                            for v in x: walk(v)
                        elif isinstance(x, str):
                            s = x.strip()
                            if s.startswith(("http://", "https://", "/")) and len(s) > 6:
                                urls.add(_canonicalize(urljoin(final_url, s)))
                    walk(data)
            except Exception:
                pass

        # 2) 通用字符串常量里的 URL
        for m in SCRIPT_URL_RE.finditer(content):
            s = m.group("u").strip()
            if s.startswith(("http://", "https://", "/")) and len(s) > 6:
                urls.add(_canonicalize(urljoin(final_url, s)))

    return urls

# -------- 统一入口：抽“同栏目”的子链接（DOM + JS + 分页） --------
def extract_section_links(final_url: str, soup: BeautifulSoup, base_section_url: str) -> set[str]:
    """
    从列表页抽取“同栏目”的子链接：
      - DOM 中的 <a href>（已过滤导航区）
      - JS 导航：onclick/data-*、role="link|button"
      - <script> 数据块中出现的同栏目 URL
      - 分页链接（rel=next、分页器）
    再统一做：canonicalize → 同站 → 同栏目 → 去重。
    """
    base_canon = _canonicalize(base_section_url)
    domain = urlsplit(final_url).netloc

    candidates = set()

    # A) 普通 <a> 链接
    for a in soup.find_all("a", href=True):
        if _is_in_excluded_zone(a):
            continue
        href = (a.get("href") or "").strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        absu = _canonicalize(urljoin(final_url, href))
        candidates.add(absu)

    # B) JS 导航（DOM 属性）
    candidates |= _extract_js_nav_urls_from_dom(final_url, soup)

    # C) JS 数据块（脚本文本）
    candidates |= _extract_urls_from_script_blocks(final_url, soup)

    # D) 分页（rel=next / 常见分页器）
    next_link = soup.find("link", rel=lambda v: v and "next" in v.lower())
    if next_link and next_link.get("href"):
        candidates.add(_canonicalize(urljoin(final_url, next_link["href"])))
    for sel in (".pagination a", ".pager a", ".pages a", ".pagebar a"):
        for a in soup.select(sel):
            if a and a.get("href"):
                candidates.add(_canonicalize(urljoin(final_url, a["href"].strip())))

    # ---- 统一过滤：同站 + 同栏目 ----
    filtered = set()
    for u in candidates:
        if not u or u.endswith("#"):
            continue
        p = urlsplit(u)
        if not _same_etld1(p.netloc, domain):
            continue
        if not _is_same_column(base_canon, u):
            continue
        filtered.add(u)

    return filtered


# -------------------- 详情三要素抽取（结构化→GNE→规则→LLM 一次） --------------------
def extract_structured_meta(soup: BeautifulSoup) -> dict:
    out = {}
    # JSON-LD
    for tag in soup.find_all("script", type=lambda v: v and "ld+json" in v.lower()):
        try:
            import json
            data = json.loads(tag.string or "{}")
            def take(d):
                if not isinstance(d, dict): return
                t = (d.get("@type") or "").lower()
                if t in {"newsarticle", "article", "blogposting"}:
                    out.setdefault("title", d.get("headline"))
                    out.setdefault("publish_time", d.get("datePublished") or d.get("dateCreated"))
            if isinstance(data, list):
                for it in data: take(it)
            elif isinstance(data, dict):
                take(data)
        except Exception:
            pass
    # OG/meta
    ogt = soup.find("meta", {"property": "og:title"})
    if ogt and ogt.get("content"):
        out.setdefault("title", ogt["content"].strip())
    for name in ("article:published_time", "publish_time", "pubdate", "date", "dc.date"):
        m = soup.find("meta", {"property": name}) or soup.find("meta", {"name": name})
        if m and m.get("content"):
            out.setdefault("publish_time", m["content"].strip())
    return out

def extract_by_rules(soup: BeautifulSoup) -> dict:
    res = {}
    # 标题
    h1 = soup.find("h1")
    if h1:
        t = h1.get_text(" ", strip=True)
        if t: res["title"] = t
    if "title" not in res:
        h2 = soup.find("h2")
        if h2:
            t = h2.get_text(" ", strip=True)
            if t: res["title"] = t
    # 时间（常见格式）
    txt = soup.get_text("\n", strip=True)
    m = re.search(r"((20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})[日]?(?:\s+\d{2}:\d{2}(?::\d{2})?)?)", txt)
    if m:
        res["publish_time"] = m.group(1)
    # 正文：挑文本密度高的容器
    candidates = []
    for sel in ("article", ".article", ".content", ".article-content", ".newstext", ".news-content", "#content"):
        for node in soup.select(sel):
            text = node.get_text("\n", strip=True)
            if text and len(text) > 200:
                link_cnt = len(node.find_all("a"))
                score = len(text) - link_cnt * 20
                candidates.append((score, text))
    if candidates:
        candidates.sort(reverse=True)
        res["content"] = candidates[0][1]
    else:
        # 退化：全页可见文本
        texts = soup.find_all(string=True)
        vt = [t for t in texts if tag_visible(t)]
        res["content"] = "\n".join([v.strip() for v in vt if str(v).strip()])
    return res

def extract_article_three_fields(final_url: str, text: str, soup: BeautifulSoup, *, call_llm_once: bool, logger) -> dict:
    """
    固定顺序：结构化→GNE→规则；若 title/publish_time/content 任一缺失则仅调用一次 LLM 兜底。
    返回至少：title, publish_time, content, url；并附加 site/crawl_time（不污染 content）。
    """
    result = {"url": final_url}
    domain = urlsplit(final_url).netloc
    result["site"] = domain.split(":")[0].replace("www.", "")
    result["crawl_time"] = datetime.utcnow().isoformat()

    # 1) 结构化
    meta = extract_structured_meta(soup)
    result.update({k: v for k, v in meta.items() if v})

    # 2) GNE
    if not all(result.get(k) for k in ("title", "publish_time", "content")):
        try:
            g = extractor.extract(text)
            g.pop("meta", None)
            if g.get("title"): result.setdefault("title", g["title"])
            if g.get("publish_time"): result.setdefault("publish_time", g["publish_time"])
            if g.get("content") and len(g["content"]) > 100:
                result.setdefault("content", g["content"])
        except Exception as e:
            logger.debug(f"GNE err: {e}")

    # 3) 规则兜底（不调模型）
    if not all(result.get(k) for k in ("title", "publish_time", "content")):
        rule_res = extract_by_rules(soup)
        for k in ("title", "publish_time", "content"):
            if rule_res.get(k):
                result.setdefault(k, rule_res[k])

    # 4) 模型兜底（仅一次）
    need_llm = not all(result.get(k) for k in ("title", "publish_time", "content"))
    if need_llm and call_llm_once:
        html_lines = [line.strip() for line in soup.get_text("\n").split("\n") if line.strip()]
        html_text = "\n".join(html_lines)
        if 0 < len(html_text) <= MAX_LLM_TEXT_LEN:
            messages = [
                {"role": "system", "content": sys_info},
                {"role": "user", "content": html_text},
            ]
            llm_output = openai_llm(messages, model=model, logger=logger, temperature=0.01)
            parsed = json_repair.repair_json(llm_output, return_objects=True)
            if isinstance(parsed, dict):
                for k in ("title", "publish_time", "content"):
                    if parsed.get(k):
                        result[k] = parsed[k]
                # 可选：让模型产出摘要
                if parsed.get("abstract"):
                    result["abstract"] = parsed["abstract"]

    # 额外提供标准化时间（不覆盖原始 publish_time）
    if result.get("publish_time"):
        try:
            norm = extract_and_convert_dates(result["publish_time"])
            if norm:
                result["publish_time_norm"] = norm
        except Exception:
            pass

    return result

# -------------------- 深爬入口：同栏目 BFS（最多 3 层） --------------------
async def crawl_section(base_list_url: str, logger, max_depth: int = 3, max_pages: int = 500):
    """
    从“栏目列表页”出发，按同栏目路径向下 BFS 深入至 max_depth。
    返回：列表 [article_dict, ...]，每个至少包含 title/publish_time/content/url。
    """
    seen = set()
    articles = []
    q = deque()
    q.append((_canonicalize(base_list_url), 0))
    base_canon = _canonicalize(base_list_url)

    while q and len(seen) < max_pages:
        url, depth = q.popleft()
        if url in seen:
            continue
        seen.add(url)

        # 抓取
        try:
            resp, final_url = await _fetch(url, logger)
        except Exception as e:
            logger.info(f"fetch failed: {url} {e}")
            continue

        text = _decode_response_text(resp, logger)
        if not text:
            continue
        soup = BeautifulSoup(text, "html.parser")

        ptype = classify_page(final_url, soup)
        if ptype == "detail" or _is_detail_like_url(final_url):
            data = extract_article_three_fields(final_url, text, soup, call_llm_once=True, logger=logger)
            if all(data.get(k) for k in ("title", "publish_time", "content")):
                articles.append(data)
            continue

        # 列表/未知页：在同栏目内继续扩展
        if depth < max_depth:
            links = extract_section_links(final_url, soup, base_canon)
            for link in links:
                if link not in seen and _is_same_column(base_canon, link):
                    q.append((link, depth + 1))

    return articles

# -------------------- 单页入口：保留并升级 --------------------
async def general_crawler(url: str, logger) -> Tuple[int, Union[Set[str], Dict]]:
    """
    单页识别：
      - 列表页：返回同栏目候选链接集合（flag=1）
      - 详情页：返回三要素（不足则 LLM 兜底一次）（flag=11）
    """
    # 0) 站点特化优先
    parsed_url = urlparse(url)
    init_domain = parsed_url.netloc


    # 1) 抓页面
    try:
        response, final_url = await _fetch(url, logger)
    except Exception:
        return -7, {}

    # 2) 解码 + 解析
    text = _decode_response_text(response, logger)
    if not text:
        return -7, {}
    soup = BeautifulSoup(text, "html.parser")

    # 3) 判定
    ptype = classify_page(final_url, soup)

    # 3.a 列表页：返回同栏目的候选集合
    if ptype in ("list", "unknown"):
        links = extract_section_links(final_url, soup, final_url)
        # 若集合太小、但页面还是像列表，额外做一次宽松同域收集（以兼容老逻辑）
        if not links and is_list_like_page(soup):
            # 降级：保留同域新闻感链接（不强制同栏目）
            links = set()
            domain = urlsplit(final_url).netloc
            for a in soup.find_all("a", href=True):
                if _is_in_excluded_zone(a):
                    continue
                href = (a.get("href") or "").strip()
                if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
                    continue
                abs_url = urljoin(final_url, href)
                parts = urlsplit(abs_url)
                if not _same_etld1(parts.netloc, domain):
                    continue
                links.add(_canonicalize(urlunsplit(parts._replace(fragment=""))))
        if links:
            return 1, links

    # 3.b 详情页：抽三要素（不足则 LLM 兜底一次）
    data = extract_article_three_fields(final_url, text, soup, call_llm_once=True, logger=logger)
    if all(data.get(k) for k in ("title", "publish_time", "content")):
        return 11, data

    # 4) 失败
    return 0, {}


from collections import deque

async def smart_crawler(
    url: str,
    logger,
    *,
    max_depth: int = 3,
    max_pages: int = 1000,
) -> Tuple[int, Union[Set[str], Dict]]:
    """
    融合入口：
      - 若是详情页：抽三要素（缺任一 → 模型兜底一次）→ (11, article_dict)
      - 若是列表/未知页：同栏目 BFS 深爬，深入至 max_depth 层，仅收集“详情页 URL”集合 → (1, set[str])

    返回 (flag, payload) 兼容老接口：
      - flag < 0 : 错误（-7 为网络/解码问题）
      - flag = 0 : 解析失败
      - flag = 1 : 列表页（payload 为同栏目内 BFS 收集到的文章详情 URL 集合）
      - flag = 11: 详情页解析成功（payload 为 {title, content, publish_time, ...}）
    """
    # 站点专用分发（与 general_crawler 保持一致）
    parsed_url = urlparse(url)
    init_domain = parsed_url.netloc

    # 抓入口页
    try:
        resp, final_url = await _fetch(url, logger)
    except Exception:
        return -7, {}

    text = _decode_response_text(resp, logger)
    if not text:
        return -7, {}
    soup = BeautifulSoup(text, "html.parser")

    # 页面类型判定
    ptype = classify_page(final_url, soup)

    # --- 情况 A：详情页 → 直接抽三要素（不足则 LLM 兜底一次） ---
    if ptype == "detail" or _is_detail_like_url(final_url):
        data = extract_article_three_fields(final_url, text, soup, call_llm_once=True, logger=logger)
        if all(data.get(k) for k in ("title", "publish_time", "content")):
            return 11, data
        return 0, {}

    # --- 情况 B：列表/未知页 → 同栏目 BFS，收集“文章详情 URL 集合” ---
    base_canon = _canonicalize(final_url)
    seen: Set[str] = set()
    article_urls: Set[str] = set()
    q = deque()
    q.append((base_canon, 0))

    while q and len(seen) < max_pages:
        cur_url, depth = q.popleft()
        cur_url = _canonicalize(cur_url)
        if cur_url in seen:
            continue
        seen.add(cur_url)

        try:
            r, fu = await _fetch(cur_url, logger)
        except Exception as e:
            logger.debug(f"BFS fetch fail: {cur_url} - {e}")
            continue

        t = _decode_response_text(r, logger)
        if not t:
            continue
        sp = BeautifulSoup(t, "html.parser")

        # 判定类型
        cur_type = classify_page(fu, sp)

        # 命中“详情页” → 收集 URL（不解析正文，满足 flag=1 的接口要求）
        if cur_type == "detail" or _is_detail_like_url(fu):
            article_urls.add(_canonicalize(fu))
            continue

        # 列表/未知 → 仅在同栏目内继续扩展
        if depth < max_depth:
            children = extract_section_links(fu, sp, base_canon)
            for link in children:
                if link not in seen and _is_same_column(base_canon, link):
                    q.append((link, depth + 1))

    # 无论是否抓到文章 URL，都是“列表页”语义，返回 flag=1
    return 1, article_urls

