# -*- coding: utf-8 -*-
# when you use this general crawler, remember followings
# When you receive flag -7, it means that the problem occurs in the HTML fetch process.
# When you receive flag 0, it means that the problem occurred during the content parsing process.
# when you receive flag 1, the result would be a tuple, means that the input url is possible a article_list page
# and the set contains the url of the articles.
# when you receive flag 11, you will get the dict contains the title, content, url, date, and the source of the article.
import re
import sys
from typing import Union, Tuple, Set, Dict
from gne import GeneralNewsExtractor
import httpx
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urlparse
from llms.openai_wrapper import openai_llm
# from llms.siliconflow_wrapper import sfa_llm
from bs4.element import Comment
from utils.general_utils import extract_and_convert_dates
import asyncio
import json_repair
import os
from typing import Union
from requests.compat import urljoin
from scrapers import scraper_map
from pathlib import Path
from dotenv import load_dotenv
from .new_llm_crawler import smart_crawler

# 找到上层目录（例如上一级或两级，按实际调整）
ROOT = Path(__file__).resolve().parents[2]  
load_dotenv(ROOT / ".env", override=True)


ONCLICK_URL_RE = re.compile(
    r"""(?:window\.open|location\.href\s*=|open)\s*\(\s*['"](?P<u>[^'"]+)['"]""",
    re.I
)

model = os.environ.get('HTML_PARSE_MODEL', 'DeepSeek-V3')
header = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/604.1 Edg/112.0.100.0'}
extractor = GeneralNewsExtractor()


def tag_visible(element: Comment) -> bool:
    if element.parent.name in ["style", "script", "head", "title", "meta", "[document]"]:
        return False
    if isinstance(element, Comment):
        return False
    return True


def text_from_soup(soup: BeautifulSoup) -> str:
    res = []
    texts = soup.find_all(string=True)
    visible_texts = filter(tag_visible, texts)
    for v in visible_texts:
        res.append(v)
    text = "\n".join(res)
    return text.strip()


sys_info = '''Your task is to operate as an HTML content extractor, focusing on parsing a provided HTML segment. Your objective is to retrieve the following details directly from the raw text within the HTML, without summarizing or altering the content:

- The document's title
- The complete main content, as it appears in the HTML, comprising all textual elements considered part of the core article body
- The publication time in its original format found within the HTML

Ensure your response fits the following JSON structure, accurately reflecting the extracted data without modification:

```json
{
  "title": "The Document's Exact Title",
  "content": "All the unaltered primary text content from the article",
  "publish_time": "Original Publication Time as per HTML"
}
```

It is essential that your output adheres strictly to this format, with each field filled based on the untouched information extracted directly from the HTML source.'''



from typing import Union, Tuple, Set, Dict
from urllib.parse import urlparse, urlsplit, urlunsplit, urljoin
from datetime import datetime
import asyncio
import httpx
from bs4 import BeautifulSoup
from bs4.element import Comment
import re
from typing import Optional

from urllib.parse import urlsplit

DETAIL_PATTERNS = [
    re.compile(r"/t\d{8}_\d+\.html$"),
    re.compile(r"/\d{6,8}/t\d{8}_\d+\.html$"),
    re.compile(r"/content_\d+\.html$"),
    re.compile(r"/\d{4}(?:\d{2})?/\d{2}/[0-9a-f-]{8,}\.html$"),  # like .../202505/30/uuid.html
]

try:
    # 可选：如果环境里装了会更准
    from charset_normalizer import from_bytes as cn_from_bytes
except Exception:
    cn_from_bytes = None


NAV_PATH_PREFIXES = ("/search", "/s/", "/rss", "/sitemap", "/tag", "/category")  # 可按需增删
MIN_LIST_LINKS = 20                  # 多少同域链接视为“更可能是列表页”
MAX_LLM_TEXT_LEN = 29999             # 与你原逻辑保持一致
REQUEST_TIMEOUT = 30                 # 秒
RETRY_TIMES = 2                      # 网络重试次数


def _same_site(a: str, b: str) -> bool:
    """严格同域判断（忽略前缀 www.）。如需允许子域，改成 endswith 判断。"""
    a = a.lower().lstrip(".")
    b = b.lower().lstrip(".")
    if a.startswith("www."):
        a = a[4:]
    if b.startswith("www."):
        b = b[4:]
    return a == b


async def _fetch(url: str, logger) -> Tuple[httpx.Response, str]:
    """
    拉取页面，自动跟随重定向；返回 (response, final_url)
    final_url 用于后续一切 URL 解析/拼接，避免 301/302 抖动。
    """
    async with httpx.AsyncClient() as client:
        last_exc = None
        for attempt in range(RETRY_TIMES):
            try:
                resp = await client.get(
                    url,
                    headers=header,
                    timeout=REQUEST_TIMEOUT,
                    follow_redirects=True,  # 修复 301/302
                )
                resp.raise_for_status()
                final_url = str(resp.url)
                # 有重定向时给点调试信息
                if resp.history:
                    logger.debug(
                        f"redirected: {url} -> {final_url} ({[r.status_code for r in resp.history]})"
                    )
                return resp, final_url
            except Exception as e:
                last_exc = e
                if attempt < RETRY_TIMES - 1:
                    logger.info(f"can not reach\n{e}\nwaiting 1min")
                    await asyncio.sleep(60)
                else:
                    logger.error(e)
        raise last_exc


def _normalize_encoding(enc: Optional[str]) -> Optional[str]:
    if not enc:
        return None
    e = enc.strip().lower()
    # 常见同义词归一
    if e in {"utf8", "utf-8", "utf_8"}:
        return "utf-8"
    if e in {"gbk", "gb2312", "gb-2312", "gb_2312-80", "gb-18030", "gb18030"}:
        return "gb18030"  # 用最全的 gb18030
    if e in {"cp936"}:
        return "cp936"
    if e in {"big5", "big-5"}:
        return "big5"
    return e


def _decode_response_text(response, logger) -> str:
    """
    更稳的 HTML 解码：
      1) 头部 charset
      2) <meta charset=...> / http-equiv
      3) charset_normalizer 兜底（若可用）
      4) 尝试 utf-8 / gb18030 / cp936 / big5
    """
    raw = response.content or b""
    if not raw:
        return ""

    # 1) HTTP 头部
    ct = response.headers.get("Content-Type", "")
    m = re.search(r"charset=([^\s;]+)", ct, flags=re.I)
    enc = _normalize_encoding(m.group(1)) if m else None

    # 2) HTML <meta ... charset=...>
    if not enc:
        head = raw[:8192]  # 看前 8KB 就足够
        m = re.search(br"<meta[^>]+charset=['\"]?\s*([a-zA-Z0-9_\-]+)", head, flags=re.I)
        if not m:
            m = re.search(br"http-equiv=['\"]?content-type['\"][^>]*content=['\"][^;]+;\s*charset=([a-zA-Z0-9_\-]+)",
                          head, flags=re.I)
        if m:
            try:
                enc = _normalize_encoding(m.group(1).decode("ascii", "ignore"))
            except Exception:
                enc = None

    # 3) charset_normalizer（可选）
    if not enc and cn_from_bytes:
        try:
            r = cn_from_bytes(raw).best()
            if r and r.encoding:
                enc = _normalize_encoding(r.encoding)
                logger.debug(f"charset_normalizer guessed: {enc} (confidence={getattr(r,'encoding',None)})")
        except Exception:
            pass

    # 4) 依次尝试
    tried = set()
    for cand in [enc, "utf-8", "gb18030", "cp936", "big5"]:
        if not cand or cand in tried:
            continue
        try:
            text = raw.decode(cand)
            if cand != enc:
                logger.debug(f"decoded with fallback encoding: {cand}")
            return text
        except Exception:
            tried.add(cand)
            continue

    # 实在不行，退回 httpx 自己的判断（可能错）
    logger.warning("decode failed with all candidates; falling back to response.text (may be wrong).")
    return response.text or ""


# === 新增/调整：新闻识别配置 ===
NEWS_PATH_KEYWORDS = (
    "/news", "/press", "/media", "/information", "/xinwen", "/zhxw", "/xwzx",
    "/updates", "/notice", "/announc", "/bulletin", "/article", "/reports",
    "/detail",   # ★ 新增：很多站的详情路径
)

V_SEGMENT_RE = re.compile(r"/v/\d+(/|$)")

NON_NEWS_DENY_PREFIXES = (
    "/language", "/lang",
)
# URL 中的日期模式：/2025/08/18/ 或 /202508/ 或 t20250818_12345.html 等
DATE_IN_URL = re.compile(
    r"(?:(?:/20\d{2}[/._-]?(?:0?[1-9]|1[0-2])[/._-]?(?:0?[1-9]|[12]\d|3[01]))|t20\d{6,8}_\d+|/20\d{2}/(?:0?[1-9]|1[0-2])(?:/|$))",
    re.I,
)

def _path_depth(path: str) -> int:
    return len([seg for seg in path.split("/") if seg])

def _is_news_like_url(path: str, query: str, anchor_text: str = "") -> bool:
    """
    仅用“路径级”启发式判断是否像新闻链接：
      - 排除明显的非新闻前缀
      - 命中新闻关键词 or 带日期  → 强信号
      - 适度限制：优先 .html，且路径深度 >= 2
    """
    low_path = path.lower()

    # 明确排除
    for deny in NON_NEWS_DENY_PREFIXES:
        if low_path.startswith(deny):
            return False

    kw_hit   = any(kw in low_path for kw in NEWS_PATH_KEYWORDS)
    date_hit = bool(DATE_IN_URL.search(low_path))
    v_hit    = bool(V_SEGMENT_RE.search(low_path))  # ★ 新增：/v/123456/ 结构

    anchor_hit = False
    if anchor_text:
        t = anchor_text.strip().lower()
        if any(k in t for k in ("news", "press", "media", "公告", "新闻", "资讯", "动态", "报道", "通告", "通知")):
            anchor_hit = True

    depth_ok  = _path_depth(low_path) >= 2
    suffix_ok = low_path.endswith(".html") or date_hit or v_hit  # ★ 非 .html 但带日期或 /v/ 也放行

    return suffix_ok and depth_ok and (kw_hit or date_hit or v_hit or anchor_hit)

def _collect_same_site_links(final_url: str, soup: BeautifulSoup, logger) -> Set[str]:
    """
    从页面收集“同域 + 像新闻”的链接集合（更严格）。
    """
    final_parts = urlsplit(final_url)
    domain = final_parts.netloc
    urls: Set[str] = set()

    for a in soup.find_all("a", href=True):
        href = (a["href"] or "").strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue

        abs_url = urljoin(final_url, href)
        parts = urlsplit(abs_url)

        # 仅同域
        if not _same_site(parts.netloc, domain):
            continue

        path = parts.path or "/"
        if not _is_news_like_url(path, parts.query, getattr(a, "get_text", lambda: "")()):
            continue

        parts = parts._replace(fragment="")
        abs_url = urlunsplit(parts)
        if abs_url != final_url:
            urls.add(abs_url)

    return urls

ONCLICK_URL_RE = re.compile(r"(?:window\.open|location\.href\s*=|open)\s*\(\s*['\"](?P<u>[^'\"]+)['\"]", re.I)

def _extract_js_nav_urls(final_url: str, soup: BeautifulSoup, domain: str, list_slug: str | None) -> set[str]:
    urls = set()
    # 覆盖 onclick/data-href/data-url/role=link
    candidates = soup.select('[onclick], [data-href], [data-url], [role="link"]')

    for el in candidates:
        # ★ 排除位于导航/菜单/侧栏/页脚中的元素
        if _is_in_excluded_zone(el):
            continue

        cand = None
        if el.has_attr('onclick'):
            m = ONCLICK_URL_RE.search(el.get('onclick') or '')
            if m:
                cand = m.group('u')
        if not cand:
            for attr in ('data-href', 'data-url'):
                if el.has_attr(attr) and el.get(attr):
                    cand = el.get(attr)
                    break
        if not cand:
            continue

        abs_url = urljoin(final_url, cand.strip())
        parts = urlsplit(abs_url)

        # 仅同域
        netloc = parts.netloc.lower().lstrip(".")
        dom = urlsplit(final_url).netloc.lower().lstrip(".")
        if netloc.startswith("www."): netloc = netloc[4:]
        if dom.startswith("www."): dom = dom[4:]
        if netloc != dom:
            continue

        path = (parts.path or "/").lower()

        # ★ 栏目限定
        if list_slug and (f"/detail_{list_slug}/" not in path):
            continue

        anchor_text = el.get_text(" ", strip=True) if hasattr(el, "get_text") else ""
        if not _is_news_like_url(path, parts.query, anchor_text):
            continue

        parts = parts._replace(fragment="")
        urls.add(urlunsplit(parts))

    return urls


# 顶部常量区新增
EXCLUDE_ANCESTOR_SELECTORS = (
    "header", "nav", "footer",
    ".submenu", ".sub-menu", ".dropdown", ".dropdown-menu", ".menu", ".menus", ".navbar",
    ".top-nav", ".topbar", ".toolbar", ".bread", ".breadcrumb", ".breadcrumbs",
    ".sidebar", ".aside", ".left-nav", ".right-nav", ".sidenav", ".side-menu",
    ".pager", ".pagination", ".pagebar", ".pages", ".tab", ".tabs", ".tabbar",
    ".logo", ".site-nav", ".global-nav"
)

def _is_in_excluded_zone(el) -> bool:
    """候选节点是否位于导航/顶部菜单/侧栏/页脚等容器内。"""
    try:
        for sel in EXCLUDE_ANCESTOR_SELECTORS:
            if el.find_parent(sel):
                return True
    except Exception:
        pass
    return False


# === 新增：更强的“文章链接”识别 & 栏目页提示 ===
import re
from urllib.parse import urlsplit, urlunsplit, urljoin

ARTICLE_LINK_PATTERNS = [
    re.compile(r"/t\d{8}_\d+\.html$"),   # .../t20250327_325028.html
    re.compile(r"/content_\d+\.html$"),  # .../content_123456.html
]
DATE_REGEX = re.compile(r"(20\d{2})[.\-/年](\d{1,2})[.\-/月](\d{1,2})日?")

LIST_CLASS_HINTS = (
    ".pagination", ".pager", ".pagebar", ".page", ".pages",
    ".list", ".news-list", ".list-unstyled", ".list-group"
)

LIST_SLUG_RE = re.compile(r"/list_(?P<slug>[a-z0-9_]+)/", re.I)

def _extract_list_slug(url_or_path: str) -> str | None:
    m = LIST_SLUG_RE.search(url_or_path)
    return m.group("slug").lower() if m else None


def _extract_article_links(final_url: str, soup: BeautifulSoup, domain: str, list_slug: str | None) -> set[str]:
    urls = set()
    for a in soup.find_all("a", href=True):
        # ★ 排除位于导航/菜单/侧栏/页脚中的 a
        if _is_in_excluded_zone(a):
            continue

        href = (a["href"] or "").strip()
        if not href or href.startswith(("javascript:", "#", "mailto:", "tel:")):
            continue

        abs_url = urljoin(final_url, href)
        parts = urlsplit(abs_url)

        # 仅同域
        netloc = parts.netloc.lower().lstrip(".")
        dom = domain.lower().lstrip(".")
        if netloc.startswith("www."): netloc = netloc[4:]
        if dom.startswith("www."): dom = dom[4:]
        if netloc != dom:
            continue

        path = (parts.path or "/").lower()

        # ★ 栏目限定：list_gzwx 只要 detail_gzwx
        if list_slug and (f"/detail_{list_slug}/" not in path):
            continue

        # 新闻启发式（含日期/关键词/或 /v/123/）
        anchor_text = a.get_text(" ", strip=True)
        if not _is_news_like_url(path, parts.query, anchor_text):
            continue

        parts = parts._replace(fragment="")
        urls.add(urlunsplit(parts))
    return urls

# ===== 中文标题增强 =====
CN_RE = re.compile(r"[\u4e00-\u9fff]")
TITLE_SEPARATORS = r"\|\-—_｜·•"
TITLE_SPLIT_RE = re.compile(rf"\s*[{TITLE_SEPARATORS}]\s*")

TITLE_SELECTORS = (
    "h1", "h2",
    ".news-title", ".article-title", ".detail-title",
    "[class*='title']",
    "[id*='title']",
    "[class*='biaoti']",
    "[id*='biaoti']",
)

def _cn_ratio(s: str) -> float:
    if not s: return 0.0
    cnt = len(CN_RE.findall(s))
    return cnt / max(1, len(s))

def _normalize_space(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def _guess_site_names(soup: BeautifulSoup, domain: str) -> set[str]:
    names = set()
    # og:site_name
    m = soup.find("meta", {"property": "og:site_name"})
    if m and m.get("content"): names.add(_normalize_space(m["content"]))
    # <title> 拆分，短片段多为站名
    if soup.title and soup.title.string:
        for part in TITLE_SPLIT_RE.split(soup.title.string):
            part = _normalize_space(part)
            if 0 < len(part) <= 20:
                names.add(part)
    # 域名主干
    dom = domain.lower()
    dom = dom[4:] if dom.startswith("www.") else dom
    names.add(dom.split(":")[0])
    # 常见公司关键词作为弱匹配
    for kw in ("有限公司", "集团", "公司", "股份", "门户网站"):
        for n in list(names):
            if kw in n:
                names.add(n)
    return {n for n in names if n}

def _clean_title_segment(seg: str, site_names: set[str]) -> str:
    s = _normalize_space(seg)
    if not s: return s
    # 去掉首尾站名 + 分隔符
    for n in site_names:
        if not n: continue
        s = re.sub(rf"^({re.escape(n)})\s*[{TITLE_SEPARATORS}]*\s*", "", s)
        s = re.sub(rf"\s*[{TITLE_SEPARATORS}]*\s*({re.escape(n)})\s*$", "", s)
    return _normalize_space(s)

def _clean_title(raw: str, site_names: set[str]) -> str:
    raw = _normalize_space(raw)
    if not raw: return raw
    parts = [p for p in TITLE_SPLIT_RE.split(raw) if _normalize_space(p)]
    if not parts: parts = [raw]
    # 选“更像正文标题”的片段：中文占比、长度接近 10~40、有无新闻关键词等
    def score(p: str) -> float:
        p2 = _clean_title_segment(p, site_names)
        L = len(p2)
        len_score = 1.0 if 10 <= L <= 40 else (0.6 if 6 <= L <= 60 else 0.2)
        kw_bonus = 0.2 if any(k in p2 for k in ("发布", "会议", "通知", "公告", "报道", "网讯", "召开", "举行")) else 0.0
        return _cn_ratio(p2) * 2.0 + len_score + kw_bonus
    best = max(parts, key=score)
    return _clean_title_segment(best, site_names)

def _collect_title_candidates(soup: BeautifulSoup) -> list[tuple[str, float]]:
    """
    返回 [(文本, 基础权重)]，只收中文候选，排除导航/侧栏/页脚等
    """
    cands: list[tuple[str, float]] = []

    # 结构性标题
    for sel in TITLE_SELECTORS:
        for el in soup.select(sel):
            try:
                if _is_in_excluded_zone(el):
                    continue
            except Exception:
                pass
            txt = _normalize_space(el.get_text(" ", strip=True))
            if not txt or _cn_ratio(txt) <= 0.2:
                continue
            # 基础权重：h1 > h2 > 其他
            w = 2.5 if el.name == "h1" else (2.0 if el.name == "h2" else 1.5)
            # class/id 中含 title/biaoti/news 提升
            attr = " ".join([el.get("class") and " ".join(el.get("class")) or "", el.get("id") or ""]).lower()
            if any(k in attr for k in ("title", "biaoti", "news", "detail")):
                w += 0.5
            cands.append((txt, w))

    # meta 标题（次优）
    for sel in (
        'meta[property="og:title"]',
        'meta[name="title"]',
        'meta[name="twitter:title"]',
    ):
        m = soup.select_one(sel)
        if m and m.get("content"):
            txt = _normalize_space(m["content"])
            if txt and _cn_ratio(txt) > 0.2:
                cands.append((txt, 1.2))

    return cands

def refine_chinese_title(orig_title: str, soup: BeautifulSoup, domain: str) -> str:
    """
    根据 DOM 强化“中文正文标题”，若无法判定则返回清洗后的 orig_title。
    """
    site_names = _guess_site_names(soup, domain)

    # 先清洗一下原始标题作为备选
    fallback = _clean_title(orig_title or "", site_names)

    cands = _collect_title_candidates(soup)
    if not cands:
        return fallback

    # 评分：中文占比、长度、基础权重
    def score(txt: str, base_w: float) -> float:
        txt2 = _clean_title(txt, site_names)
        L = len(txt2)
        len_score = 1.0 if 10 <= L <= 40 else (0.6 if 6 <= L <= 60 else 0.2)
        return base_w + _cn_ratio(txt2) * 2.0 + len_score

    best_txt, best_w = max(cands, key=lambda x: score(x[0], x[1]))
    best_txt = _clean_title(best_txt, site_names)

    # 最终兜底：必须包含中文
    if _cn_ratio(best_txt) <= 0.2:
        return fallback
    return best_txt


def _is_list_like_page(soup) -> bool:
    """通过页面特征判断是否像‘列表页’：有分页/列表类名，或出现多次日期模式"""
    # 1) CSS/结构提示
    for sel in LIST_CLASS_HINTS:
        if soup.select_one(sel):
            return True
    # 2) 页面上日期出现次数较多
    text = soup.get_text(" ", strip=True)[:100000]  # 限一次匹配的量
    return len(DATE_REGEX.findall(text)) >= 5


async def general_crawler(url: str, logger) -> Tuple[int, Union[Set[str], Dict]]:
    """
    Return (flag, payload):
      - flag < 0 : 错误（-7 为网络/解码问题）
      - flag = 0 : 解析失败
      - flag = 1 : 可能是“列表页”，payload 为同域文章候选 URL 集合
      - flag = 11: 文章解析成功，payload 为 {title, content, publish_time, ...}

    工作流：
      0) 若域名有专用爬虫 -> 走专用
      1) 抓页面（自动跟随重定向）
      2) 判断是否“列表页”：同域链接 >= MIN_LIST_LINKS
      3) GNE 抽取正文
      4) 失败则 LLM 兜底抽取
      5) 后处理（时间、前缀、摘要、图片/作者绝对化、最终 URL）
    """
    # 0) 站点特化优先
    parsed_url = urlparse(url)
    init_domain = parsed_url.netloc
    if init_domain in scraper_map:
        return await scraper_map[init_domain](url, logger)
    
    # return await smart_crawler(url, logger)

    # 1) 抓页面（自动跟随重定向）；若失败 -> -7
    try:
        response, final_url = await _fetch(url, logger)
    except Exception:
        return -7, {}

    # 统一用“最终 URL/域名”，确保后续 join/过滤正确
    final_parts = urlsplit(final_url)
    domain = final_parts.netloc
    base_url = f"{final_parts.scheme}://{domain}"

    # 2) 解码 + 解析 DOM
    text = _decode_response_text(response, logger)
    if not text:
        return -7, {}

    soup = BeautifulSoup(text, "html.parser")

    # ★ 识别当前列表页的栏目 slug（如 list_gzwx → gzwx）
    list_slug = _extract_list_slug(final_parts.path)


    # ——先识别“文章详情链接集合”——
    article_links = _extract_article_links(final_url, soup, domain, list_slug)

    # ★ 并入通过 onclick/data-* 抓到的链接
    js_links = _extract_js_nav_urls(final_url, soup, domain, list_slug)
    if js_links:
        article_links |= js_links
    # 仅当“新闻候选”达到阈值才视为列表页（比如 8，按需调小/调大）
    NEWS_LIST_MIN = 8
    if len(article_links) >= NEWS_LIST_MIN or _is_list_like_page(soup):
        if len(article_links) >= NEWS_LIST_MIN:
            logger.info(f"{final_url} detected as news list page, found {len(article_links)} news-like links")
            for i, u in enumerate(list(article_links)[:5]):
                logger.debug(f"list candidate[{i}]: {u}")
            return 1, article_links
        # 如果仅靠页面结构判定是列表页，再用“新闻过滤”收一次
        fallback_urls = _collect_same_site_links(final_url, soup, logger)
        if len(fallback_urls) >= NEWS_LIST_MIN:
            logger.info(f"{final_url} looks like a list (structure), collected {len(fallback_urls)} news-like links")
            for i, u in enumerate(list(fallback_urls)[:5]):
                logger.debug(f"list candidate[{i}]: {u}")
            return 1, fallback_urls


    # 先看 URL 是否像详情页（只要像，就先尝试正文抽取）
    path = urlsplit(final_url).path  # 注意：用最终 URL
    is_detail_like = any(p.search(path) for p in DETAIL_PATTERNS)
    if is_detail_like:
        # 先试 GNE（快速路径）
        try:
            result = extractor.extract(text)
            if "meta" in result:
                del result["meta"]
            bad_title = result.get("title", "").startswith(("服务器错误", "您访问的页面", "403", "出错了"))
            bad_content = result.get("content", "").startswith("This website uses cookies")
            too_short = len(result.get("title", "")) < 4 or len(result.get("content", "")) < 200  # 适当收紧正文长度
            if not (bad_title or bad_content or too_short):
                # ——后处理，与你原有逻辑一致——
                date_str = extract_and_convert_dates(result.get("publish_time", ""))
                result["publish_time"] = date_str if date_str else datetime.strftime(datetime.today(), "%Y%m%d")
                from_site = domain.replace("www.", "").split(".")[0]
                result["content"] = f"[from {from_site}] {result['content']}"
                try:
                    meta_description = soup.find("meta", {"name": "description"})
                    result["abstract"] = f"[from {from_site}] {meta_description['content'].strip()}" if meta_description and meta_description.get("content") else ""
                except Exception:
                    result["abstract"] = ""
                result["url"] = final_url
                # GNE 提取成功后，返回前增加：
                result["title"] = refine_chinese_title(result.get("title", ""), soup, domain)
                return 11, result
            else:
                logger.debug("detail-like url but GNE judged not good; will fall back to list/LLM flow.")
        except Exception as e:
            logger.debug(f"GNE error on detail-like url: {e}; will fall back.")

    # 3) 判断“更像列表页” → 返回 flag=1
    urls = _collect_same_site_links(final_url, soup, logger)
    if len(urls) >= MIN_LIST_LINKS:
        logger.info(f"{final_url} is more like an article list page, find {len(urls)} urls with the same netloc")
        return 1, urls

    # 4) GNE 抽取正文
    try:
        result = extractor.extract(text)
        if "meta" in result:
            del result["meta"]
        result["title"] = refine_chinese_title(result.get("title", ""), soup, domain)

        # 常见异常页/隐私页/报错页过滤
        bad_title = (
            result.get("title", "").startswith(("服务器错误", "您访问的页面", "403", "出错了"))
        )
        bad_content = result.get("content", "").startswith("This website uses cookies")
        too_short = len(result.get("title", "")) < 4 or len(result.get("content", "")) < 24
        if bad_title or bad_content or too_short:
            logger.info(f"gne extract not good: {result}")
            result = None
    except Exception as e:
        logger.info(f"gne extract error: {e}")
        result = None

    # 5) LLM 兜底
    if not result:
        html_text = text_from_soup(soup)
        # 清理空白行
        html_lines = [line.strip() for line in html_text.split("\n") if line.strip()]
        html_text = "\n".join(html_lines)

        if not html_text or html_text.startswith(("服务器错误", "您访问的页面", "403", "出错了")):
            logger.warning(f"can not get {final_url} from the Internet")
            return -7, {}

        if len(html_text) > MAX_LLM_TEXT_LEN:
            logger.info(f"{final_url} content too long for llm parsing")
            return 0, {}

        messages = [
            {"role": "system", "content": sys_info},
            {"role": "user", "content": html_text},
        ]
        llm_output = openai_llm(messages, model=model, logger=logger, temperature=0.01)
        result = json_repair.repair_json(llm_output, return_objects=True)
        logger.debug(f"decoded_object: {result}")

        if not isinstance(result, dict):
            logger.debug("failed to parse from llm output")
            return 0, {}
        if "title" not in result or "content" not in result:
            logger.debug("llm parsed result not good")
            return 0, {}
        
        # 补充图片（绝对 URL）
        image_links = []
        for img in soup.find_all("img"):
            src = img.get("src")
            if not src:
                continue
            image_links.append(urljoin(final_url, src))
        result["images"] = image_links

        # 补充作者
        author_element = soup.find("meta", {"name": "author"})
        result["author"] = author_element["content"] if author_element else ""

    # 6) 后处理：时间规范化、来源前缀、摘要、最终 URL
    date_str = extract_and_convert_dates(result.get("publish_time", ""))
    result["publish_time"] = date_str if date_str else datetime.strftime(datetime.today(), "%Y%m%d")

    from_site = domain.replace("www.", "").split(".")[0]
    result["content"] = f"[from {from_site}] {result['content']}"

    try:
        meta_description = soup.find("meta", {"name": "description"})
        if meta_description and meta_description.get("content"):
            result["abstract"] = f"[from {from_site}] {meta_description['content'].strip()}"
        else:
            result["abstract"] = ""
    except Exception:
        result["abstract"] = ""

    # 用“最终 URL”作为结果 URL（避免 301 前的地址不一致）
    result["url"] = final_url

    return 11, result



