# -*- coding: utf-8 -*-
import os
import random
import re
import time
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

from docx import Document
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

# 兼容不同版本的 python-docx：OxmlElement & qn
try:
    from docx.oxml.shared import OxmlElement, qn as qn_oxml
except ImportError:
    from docx.oxml import OxmlElement
    from docx.oxml.shared import qn as qn_oxml

# 第三方 / 业务依赖
from pb_api import PbTalker
from general_utils import get_logger_level

# OpenAI 客户端（兼容自定义 base_url 或仅 api_key）
from openai import OpenAI, RateLimitError


# ========== 环境 & 客户端 ==========
ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)

base_url = os.environ.get("LLM_API_BASE", "")
token = os.environ.get("LLM_API_KEY", "")

if not base_url and not token:
    raise ValueError("LLM_API_BASE or LLM_API_KEY must be set")
elif base_url and not token:
    client = OpenAI(base_url=base_url)
elif not base_url and token:
    client = OpenAI(api_key=token)
else:
    client = OpenAI(api_key=token, base_url=base_url)

PROJECT_DIR = os.environ.get("PROJECT_DIR", "")
os.makedirs(PROJECT_DIR, exist_ok=True)

logger_file = os.path.join(PROJECT_DIR, "backend_service.log")
logger.add(
    logger_file,
    level=get_logger_level(),
    backtrace=True,
    diagnose=True,
    rotation="50 MB",
)

pb = PbTalker(logger)

# LLM & 输入大小提示（可根据所用模型调整）
REPORT_MODEL = os.environ.get("REPORT_MODEL", "gpt-4o-mini-2024-07-18")
MAX_ITEM_CHARS = 10000          # 单条原始材料截断
MAX_ABSTRACT_CHARS = 4000       # 单篇文章摘要截断
MAX_ARTICLES_PER_ITEM = 30      # 每条编号下材料里最多塞几篇文章摘要


# ========== 固定模板常量 ==========
SECTIONS = [
    ("综合要闻", "general"),
    ("区域新闻", "regional"),
    ("政策数据", "policy"),
    ("科技前沿", "tech"),
    ("行业动态", "industry"),  # 含子类
    ("对标资讯", "benchmark"),
    ("中核要闻", "cnnc_headline"),
]
INDUSTRY_SUB = ["核能", "清洁能源", "环保", "金融", "核技术应用", "智能信息", "其他"]

TAG_MAP = {
    # 一级
    "综合要闻": ("general", None),
    "区域新闻": ("regional", None),
    "政策数据": ("policy", None),
    "科技前沿": ("tech", None),
    "对标资讯": ("benchmark", None),
    "中核要闻": ("cnnc_headline", None),
    # 行业动态子类
    "核能": ("industry", "核能"),
    "清洁能源": ("industry", "清洁能源"),
    "环保": ("industry", "环保"),
    "金融": ("industry", "金融"),
    "核技术应用": ("industry", "核技术应用"),
    "智能信息": ("industry", "智能信息"),
}


# ========== 工具函数 ==========
def cn_today_str(dt: datetime | None = None) -> str:
    dt = dt or datetime.now()
    return f"{dt.year}年{dt.month}月{dt.day}日"


def safe_filename(name: str) -> str:
    name = (name or "").strip()
    name = re.sub(r'[\/\\\:\*\?"<>\|]', "_", name)
    name = re.sub(r"\s+", " ", name)
    return name or f"中核日报（{cn_today_str()}）"


def openai_llm(messages: list, model: str, logger_=None, **kwargs) -> str:
    if logger_:
        logger_.debug(f"messages:\n {messages}")
        logger_.debug(f"model: {model}")
        logger_.debug(f"kwargs:\n {kwargs}")

    try:
        resp = client.chat.completions.create(messages=messages, model=model, **kwargs)
    except RateLimitError as e:
        logger.warning(f"{e}\nRetrying in 60 second...")
        time.sleep(60)
        resp = client.chat.completions.create(messages=messages, model=model, **kwargs)
        if not getattr(resp, "choices", None):
            logger.warning(f"openai_llm warning: {resp}")
            return ""
    except Exception as e:
        if logger_:
            logger_.error(f"openai_llm error: {e}")
        return ""

    if logger_:
        logger_.debug(f"result:\n {resp.choices[0]}")
        if getattr(resp, "usage", None):
            logger_.debug(f"usage:\n {resp.usage}")

    return resp.choices[0].message.content


def add_hyperlink(paragraph, url, text):
    """在段落中插入一个可点击超链接（蓝色+下划线）"""
    part = paragraph.part
    try:
        r_id = part.relate_to(url, RT.HYPERLINK, is_external=True)
    except Exception:
        r_id = part.relate_to(
            url,
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
            is_external=True,
        )

    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn_oxml("r:id"), r_id)

    new_run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")

    u = OxmlElement("w:u")
    u.set(qn_oxml("w:val"), "single")
    color = OxmlElement("w:color")
    color.set(qn_oxml("w:val"), "0000FF")

    rPr.append(u)
    rPr.append(color)
    new_run.append(rPr)

    t = OxmlElement("w:t")
    t.text = text
    new_run.append(t)

    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)
    return hyperlink


def _norm_date(d):
    d = str(d or "")
    digits = re.sub(r"[^\d]", "", d)
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return ""


def _collect_keywords(insights: list[dict]) -> list[str]:
    seen, res = set(), []
    for it in insights or []:
        kws = it.get("keywords") or []
        if isinstance(kws, str):
            kws = [x.strip() for x in re.split(r"[，、,\s]+", kws) if x.strip()]
        for k in kws:
            if k not in seen:
                seen.add(k)
                res.append(k)
    return res


def _load_role_config():
    """从 PB 获取角色设定（roleplays 集合）"""
    try:
        role_cfg = pb.read(collection_name="roleplays", filter="activated=True")
        if role_cfg:
            character = role_cfg[0].get("character", "") or ""
            report_type = role_cfg[0].get("report_type", "") or ""
            return character, report_type, role_cfg[0].get("id", "")
    except Exception as e:
        logger.warning(f"load roleplays failed: {e}")
    return "", "", ""


# ========== 分类相关 ==========
def classify_item(tag: str | None, keywords: list[str] | None, category: str | None = None):
    """优先 category（可中文分区名/英文 key/行业子类），回退 tag/keywords，兜底 industry/其他"""
    if category and category.strip() in TAG_MAP:
        return TAG_MAP[category.strip()]
    if category:
        for title_cn, key in SECTIONS:
            if category.strip() == key:
                return (key, None)
    if category and category.strip() in INDUSTRY_SUB:
        return ("industry", category.strip())

    if tag and tag.strip() in TAG_MAP:
        return TAG_MAP[tag.strip()]
    if tag and "工程建设" in tag:
        return ("industry", "核能")

    kw = "、".join(keywords or [])
    for k in TAG_MAP:
        if k and k in kw:
            return TAG_MAP[k]
    return ("industry", "其他")


# ========== 逐洞见建模（三件套） ==========
def _extract_article_summaries(ent: dict) -> list[dict]:
    """从 ent['articles'] 抽取标题/日期/摘要/URL；长度兜底"""
    arts = []
    for a in (ent.get("articles") or [])[:MAX_ARTICLES_PER_ITEM]:
        arts.append({
            "title": (a.get("title") or "").strip(),
            "date": _norm_date(a.get("publish_time")),
            "abstract": (a.get("abstract") or a.get("content") or "").strip()[:MAX_ABSTRACT_CHARS],
            "url": (a.get("url") or "").strip(),
        })
    return arts


def _recent_time(arts: list[dict]) -> str:
    ts = [x.get("date") for x in arts if x.get("date")]
    return max(ts) if ts else ""


def _process_insight_item(ent: dict, character: str, report_type: str) -> dict:
    """
    输入：{'content': 洞见摘要, 'articles': [...], 'url': 源链接, 可选 'title','category','tag','keywords'}
    输出：{'title','summary','sources'[1~3 urls],'time'}
    """
    content = (ent.get("content") or "").strip()[:MAX_ITEM_CHARS]
    articles = _extract_article_summaries(ent)
    recent_time = _recent_time(articles)

    # 源链接优先：洞见本身的 url
    src_urls = []
    if isinstance(ent.get("url"), str) and ent["url"].strip():
        src_urls.append(ent["url"].strip())
    # 再补充文章里的 URL
    for a in articles:
        if a.get("url") and a["url"] not in src_urls:
            src_urls.append(a["url"])
    src_urls = src_urls[:3]

    # 提示词（参考你给的写法，改为 OpenAI）
    character = character or "专业情报分析官"
    report_type = report_type or "综合情报"
    sys = (
        f"你是一名{character}。根据“洞见摘要”和“原始文章摘录”，输出结构化结果：\n"
        "1) concise_title：20字内提要式标题；\n"
        "2) detailed_summary：120~200字，准确客观、书面化；\n"
        "3) sources：最多3个 URL（原样返回）。\n"
        "必须严格输出 JSON。"
    )
    usr = {
        "report_type": report_type,
        "insight_summary": content,
        "primary_url": ent.get("url", ""),
        "articles": articles
    }

    title = ""; summary = ""; sources = []
    try:
        out = openai_llm(
            messages=[{"role": "system", "content": sys},
                      {"role": "user", "content": str(usr)}],
            model=REPORT_MODEL,
            temperature=0.2,
            logger_=logger
        ) or ""
        m = re.search(r"\{.*\}", out, flags=re.S)
        if m:
            import json
            data = json.loads(m.group(0))
            title = (data.get("concise_title") or "").strip()
            summary = (data.get("detailed_summary") or "").strip()
            s = data.get("sources") or []
            if isinstance(s, str):
                s = [s]
            sources = [x.strip() for x in s if isinstance(x, str) and x.strip()]
    except Exception as e:
        logger.warning(f"_process_insight_item llm fail: {e}")

    # 兜底
    if not title:
        title = (ent.get("title") or (articles[0]["title"] if articles and articles[0]["title"] else content[:24])).strip()
    if not summary:
        base = content
        if articles and articles[0].get("abstract"):
            base = f"{base}\n{articles[0]['abstract']}"
        summary = base[:180]
    if not sources:
        sources = src_urls

    return {"title": title, "summary": summary, "sources": sources[:3], "time": recent_time}


# ========== 分类聚合 & 类别内逻辑排序 ==========
def _group_by_section(insights: list[dict], character: str, report_type: str) -> dict:
    """
    返回：{section_key: {'title':中文名, 'items':[processed...], 'subs':{子类:[processed...]}}}
    processed: {'title','summary','sources','time','_raw'}
    """
    grouped = {
        key: {'title': title, 'items': [], 'subs': {s: [] for s in INDUSTRY_SUB}}
        for title, key in SECTIONS
    }

    for ent in insights or []:
        sec_key, sub = classify_item(ent.get("tag"), ent.get("keywords"), ent.get("category"))
        proc = _process_insight_item(ent, character, report_type)
        proc["_raw"] = ent
        if sec_key == "industry":
            grouped[sec_key]['subs'][sub or "其他"].append(proc)
        else:
            grouped[sec_key]['items'].append(proc)
    return grouped


def _logical_sort_items_via_llm(section_title: str, items: list[dict]) -> list[dict]:
    """用 LLM 给出类别内排序；失败回退时间倒序"""
    if not items:
        return items

    payload = [{"idx": i + 1, "title": it.get("title", ""), "summary": it.get("summary", ""), "time": it.get("time", "")}
               for i, it in enumerate(items)]

    sys = (
        "你是资深编辑。请对同一类别的新闻条目做逻辑排序："
        "优先级=政策/监管>项目工程>企业行动>数据/研究；同主题聚在一起，时间相近相邻。"
        "只输出 JSON：{\"order\":[原始idx,...]}。"
    )
    order = []
    try:
        out = openai_llm(
            messages=[{"role": "system", "content": sys},
                      {"role": "user", "content": str({"section": section_title, "items": payload})}],
            model=REPORT_MODEL,
            temperature=0.1,
            logger_=logger
        ) or ""
        m = re.search(r"\{.*\}", out, flags=re.S)
        if m:
            import json
            data = json.loads(m.group(0))
            order = [int(x) for x in (data.get("order") or []) if isinstance(x, int)]
    except Exception as e:
        logger.warning(f"logical sort llm error: {e}")

    if order and set(order) == set(range(1, len(items) + 1)):
        return [items[i - 1] for i in order]

    # 兜底：时间倒序
    def _k(it): return it.get("time") or "", it.get("title") or ""
    return sorted(items, key=_k, reverse=True)


# ========== 存储/更新记忆 ==========
def _save_report_memory(title: str, snapshot_text: str, docx_path: str) -> str:
    """把本次报告存为记忆项；返回记录 id（若可用）"""
    body = {
        "title": title,
        "snapshot": snapshot_text,
        "docx_path": docx_path,
        "created": datetime.now().isoformat(timespec="seconds")
    }
    try:
        res_id = pb.add(collection_name="report_memories", body=body)
        return str(res_id or "")
    except Exception as e:
        logger.warning(f"save memory failed: {e}")
        return ""


def _update_report_memory(jawbone_id: str, title: str, snapshot_text: str, docx_path: str) -> None:
    body = {
        "title": title,
        "snapshot": snapshot_text,
        "docx_path": docx_path,
        "updated": datetime.now().isoformat(timespec="seconds")
    }
    try:
        pb.update(collection_name="report_memories", id=jawbone_id, body=body)
    except Exception as e:
        logger.warning(f"update memory failed: {e}")

def _get_report_memory_by_id(memory_id: str) -> dict | None:
    try:
        recs = pb.read("report_memories",
                       fields=["id", "title", "snapshot", "docx_path", "created", "updated"],
                       filter=f'id="{memory_id}"')
        return recs[0] if recs else None
    except Exception as e:
        logger.warning(f"read report memory failed: {e}")
        return None
    
# ========== LLM 报告生成（首次 / 或按记忆改写） ==========
def get_report(
    insight_entries: list[dict],
    articles: list[dict],
    memory: str,         # 若提供，则走“改写”流程
    topics: list[str],
    comment: str,
    docx_file: str
) -> tuple[bool, str, str]:
    """
    两种模式：
    1) 首次生成：基于多洞见→逐条建模→分类→排序→组装→DOCX→入库
    2) 改写：有 memory + comment 时，只按意见改写 memory→DOCX→更新入库
    返回: (ok, snapshot_text, report_title)
    """
    character, report_type, _role_id = _load_role_config()
    today = cn_today_str()
    report_title = topics[0].strip() if (topics and isinstance(topics, list) and (topics[0] or "").strip()) else f"中核日报（{today}）"

    # ========== 改写模式 ==========
    if (memory or "").strip() and (comment or "").strip():
        logger.debug("rewrite mode with memory + comment")
        new_text = revise_snapshot_text(memory, comment, logger_=logger)
        if not new_text:
            return False, "", report_title
        # DOCX
        ok = build_docx_from_snapshot(
            snapshot_text=new_text,
            articles=articles,
            docx_file=docx_file,
            always_appendix=True,
            inline_links=True,
            grouped_for_links=None
        )
        # 保存/更新记忆
        id = _save_report_memory(report_title, new_text, docx_file)
        return ok, new_text, report_title, id

    # ========== 首次生成 ==========
    # 1) 分类 + 逐洞见建模
    grouped = _group_by_section(insight_entries, character, report_type)

    # 2) 类别内逻辑排序
    for title_cn, key in SECTIONS:
        if key == "industry":
            for sub in INDUSTRY_SUB:
                grouped[key]['subs'][sub] = _logical_sort_items_via_llm(f"{title_cn}-({sub})", grouped[key]['subs'][sub])
        else:
            grouped[key]['items'] = _logical_sort_items_via_llm(title_cn, grouped[key]['items'])

    # 3) 关键词
    kws = _collect_keywords(insight_entries)

    # 4) 组装最终正文（分区标题不加序号；每条=编号行→概括→链接行）
    lines = [report_title]
    if kws:
        lines.append(f"关键词：{'、'.join(kws)}")

    def _emit_item_block(idx: int, it: dict) -> list[str]:
        urls = [u for u in (it.get("sources") or []) if u][:3]
        blk = [f"{idx}，{(it.get('title') or '').strip()}"]
        if it.get("summary"):
            blk.append(it["summary"].strip())
        blk.extend(urls)
        return blk

    has_any = False
    for title_cn, key in SECTIONS:
        if key != "industry":
            items = grouped[key]['items']
            if not items:
                continue
            has_any = True
            lines.append(f"{title_cn}：")
            for i, it in enumerate(items, start=1):
                lines.extend(_emit_item_block(i, it))
        else:
            subs_have = any(grouped[key]['subs'][s] for s in INDUSTRY_SUB)
            if not subs_have:
                continue
            has_any = True
            lines.append(f"{title_cn}：")
            for sub in INDUSTRY_SUB:
                items = grouped[key]['subs'][sub]
                if not items:
                    continue
                lines.append(f"（{sub}）")
                for i, it in enumerate(items, start=1):
                    lines.extend(_emit_item_block(i, it))

    snapshot_text = "\n".join(lines)
    if not has_any:
        logger.warning("no content after grouping")
        return False, "", report_title

    # 5) DOCX 渲染
    ok = build_docx_from_snapshot(
        snapshot_text=snapshot_text,
        articles=articles if articles is not None else [],
        docx_file=docx_file,
        always_appendix=True,
        inline_links=True,
        grouped_for_links=None  # 我们直接把 URL 打印在正文里了
    )

    # 6) 入库记忆
    id = _save_report_memory(report_title, snapshot_text, docx_file)

    return ok, snapshot_text, report_title, id


# ========== LLM 结构锁定改写（只改文字，不改结构） ==========
def revise_snapshot_text(snapshot_text: str, comment: str, logger_=None) -> str:
    """
    根据修改意见对报告正文进行润色调整：
    - 不增删分区标题/子类标头（如（核能））/编号行（如“1，”）；
    - 标题行与“关键词：”行保留；
    - 允许改写各条目文字与概括，不得臆造。
    """
    if not snapshot_text or not (comment or "").strip():
        return ""

    sys = (
        "你是报告改写助手。请在【严格保留结构与编号】的前提下，根据修改意见对报告正文文字进行润色调整："
        "1) 不得增删任何分区标题、子类标头（如（核能））、编号行（如“1，”）。"
        "2) 标题行与“关键词：”行必须原样保留。"
        "3) 允许改写条目内容与概括；"
        "4) 保持事实准确，不得臆造；"
        "5) 输出必须仍为纯文本，结构与输入一致。"
    )
    usr = f"【报告文本（原始）】\n{snapshot_text}\n\n【修改意见】\n{comment}\n\n【请输出改写后的完整文本】"

    try:
        out = openai_llm(
            messages=[{"role": "system", "content": sys}, {"role": "user", "content": usr}],
            model=REPORT_MODEL,
            temperature=0.2,
            logger_=logger_
        ) or ""
    except Exception as e:
        if logger_:
            logger_.error(f"revise failed: {e}")
        return ""

    # 粗校验：分区标题行与编号行数量是否一致
    def _struct(txt: str):
        secs = re.findall(r"^(.+?)：$", txt, flags=re.M)  # 无序号分区标题
        nums = re.findall(r"^\d+，", txt, flags=re.M)
        return (len(secs), len(nums))
    if _struct(out) != _struct(snapshot_text):
        if logger_:
            logger_.warning("revise rejected due to structure mismatch")
        return ""

    return out.strip()


# ========== DOCX 渲染 ==========
def build_docx_from_snapshot(snapshot_text: str,
                             articles: list[dict],
                             docx_file: str,
                             always_appendix: bool = True,
                             inline_links: bool = True,
                             grouped_for_links: dict | None = None) -> bool:
    """
    兼容两种分区标题：
      1) “综合要闻：”  2) “一、综合要闻：”
    对正文中“单行 URL”渲染为可点击链接；末尾附录列出所有 articles。
    """
    if not snapshot_text:
        return False

    doc = Document()
    doc.styles['Normal'].font.name = u'宋体'
    doc.styles['Normal']._element.rPr.rFonts.set(qn('w:eastAsia'), u'宋体')
    doc.styles['Normal'].font.size = Pt(12)
    doc.styles['Normal'].font.color.rgb = RGBColor(0, 0, 0)

    lines = snapshot_text.splitlines()
    # 标题
    title = lines[0].strip() if lines else f"中核日报（{datetime.now().strftime('%Y-%m-%d')}）"
    H1 = doc.add_heading(level=1)
    H1.alignment = WD_PARAGRAPH_ALIGNMENT.LEFT
    run = H1.add_run(title)
    run.font.name = u'宋体'
    run._element.rPr.rFonts.set(qn('w:eastAsia'), u'宋体')

    url_line_pat = re.compile(r"^(https?://[^\s]+)$")

    i = 1
    while i < len(lines):
        stripped = (lines[i] or "").strip()
        if not stripped:
            i += 1
            continue

        # 分区标题
        m_sec_num = re.match(r"^[一二三四五六七]、(.+?)：$", stripped)
        m_sec_plain = re.match(r"^(.+?)：$", stripped)
        if m_sec_num or m_sec_plain:
            sec_title_cn = (m_sec_num.group(1) if m_sec_num else m_sec_plain.group(1)).strip()
            h = doc.add_heading(level=2)
            rr = h.add_run(f"{sec_title_cn}：")
            rr.font.name = u'宋体'
            rr._element.rPr.rFonts.set(qn('w:eastAsia'), u'宋体')
            i += 1
            continue

        # 子类
        if re.match(r"^（(.+?)）$", stripped):
            p = doc.add_paragraph()
            r = p.add_run(stripped)
            r.bold = True
            i += 1
            continue

        # 编号标题行
        if re.match(r"^\d+，", stripped):
            p = doc.add_paragraph()
            p.add_run(stripped)
            i += 1
            continue

        # 单行 URL → 超链接
        if url_line_pat.match(stripped):
            p2 = doc.add_paragraph()
            add_hyperlink(p2, stripped, stripped)
            i += 1
            continue

        # 普通段落
        doc.add_paragraph(stripped)
        i += 1

    # 文末附录
    if always_appendix:
        doc.add_heading("附：原始信息网页", level=2)
        for k, a in enumerate(articles or [], start=1):
            title_a = a.get("title", "")
            url_a = a.get("url", "")
            d = _norm_date(a.get("publish_time", ""))
            doc.add_paragraph(f"{k}、{title_a}|{d}")
            p2 = doc.add_paragraph()
            if url_a:
                add_hyperlink(p2, url_a, url_a)

    doc.save(docx_file)
    return True
