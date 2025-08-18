# -*- coding: utf-8 -*-
# when you use this general crawler, remember followings
# When you receive flag -7, it means that the problem occurs in the HTML fetch process.
# When you receive flag 0, it means that the problem occurred during the content parsing process.
# when you receive flag 1, the result would be a tuple, means that the input url is possible a article_list page
# and the set contains the url of the articles.
# when you receive flag 11, you will get the dict contains the title, content, url, date, and the source of the article.

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


model = os.environ.get('HTML_PARSE_MODEL', 'gpt-4o-mini-2024-07-18')
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

# 顶部常量区域（与 MIN_LIST_LINKS 同级）
DETAIL_PATTERNS = [
    re.compile(r"/t\d{8}_\d+\.html$"),          # .../t20250327_325028.html
    re.compile(r"/\d{6,8}/t\d{8}_\d+\.html$"),  # .../202503/t20250327_325028.html
    re.compile(r"/content_\d+\.html$"),         # .../content_123456.html（常见）
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
                    follow_redirects=True,  # ✅ 修复 301/302
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
        return "gb18030"  # ✅ 用最全的 gb18030
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


def _collect_same_site_links(final_url: str, soup: BeautifulSoup, logger) -> Set[str]:
    """
    从页面里收集“同域链接”，保留查询串 ?query、丢弃 #fragment、过滤无效 href 和明显导航类路径。
    返回 set(unique_urls)
    """
    final_parts = urlsplit(final_url)
    domain = final_parts.netloc
    current_dir = final_parts.path.rsplit("/", 1)[0] + "/"  # 当前目录
    urls: Set[str] = set()

    for a in soup.find_all("a", href=True):
        href = (a["href"] or "").strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue

        # 用最终 URL 作为基准来拼相对链接
        abs_url = urljoin(final_url, href)

        parts = urlsplit(abs_url)
        # 仅收集同域链接（如需允许子域，改 _same_site 为 endswith）
        if not _same_site(parts.netloc, domain):
            continue
        # 收紧计数：仅限“同目录 + .html”
        if not parts.path.startswith(current_dir):
            continue
        if not parts.path.endswith(".html"):
            continue

        # 过滤明显的“导航/搜索/站点地图”入口，减少 404/噪声
        pth = parts.path.lower()
        if pth.startswith(NAV_PATH_PREFIXES):
            logger.debug(f"skip nav-like url: {abs_url}")
            continue

        # 丢弃 fragment，保留 query；urlunsplit 会自动补上 '?'
        parts = parts._replace(fragment="")
        abs_url = urlunsplit(parts)

        if abs_url != final_url:
            urls.add(abs_url)

    return urls


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

def _extract_article_links(final_url: str, soup, domain: str) -> set[str]:
    """从页面里抽‘像文章详情’的链接：同域 + 匹配文章路径模式 or .html 结尾"""
    urls = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("javascript:", "#", "mailto:", "tel:")):
            continue
        abs_url = urljoin(final_url, href)
        parts = urlsplit(abs_url)
        # 同域
        netloc = parts.netloc.lower().lstrip(".")
        if netloc.startswith("www."): netloc = netloc[4:]
        dom = domain.lower().lstrip(".")
        if dom.startswith("www."): dom = dom[4:]
        if netloc != dom:
            continue
        path = parts.path
        # 像文章详情的路径
        if any(p.search(path) for p in ARTICLE_LINK_PATTERNS) or path.endswith(".html"):
            parts = parts._replace(fragment="")
            urls.add(urlunsplit(parts))
    return urls

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

    # ——先识别“文章详情链接集合”——
    article_links = _extract_article_links(final_url, soup, domain)
    if len(article_links) >= 3 or _is_list_like_page(soup):
        # 只要像列表页，就不要跑 GNE/LLM，直接把子链接交回 pipeline
        logger.info(f"{final_url} detected as list page, found {len(article_links)} article-like links")
        # 给点调试：展示前几个
        for i, u in enumerate(list(article_links)[:5]):
            logger.debug(f"list candidate[{i}]: {u}")
        return 1, article_links


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
