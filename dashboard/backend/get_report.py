# -*- coding: utf-8 -*-
import os
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
ZH_NUM = ['一', '二', '三', '四', '五', '六', '七']
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
    """
    在段落中插入一个可点击超链接（蓝色+下划线）
    """
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


def classify_item(tag: str | None, keywords: list[str] | None):
    """根据 tag/关键词判定分区/子类；默认落行业动态/其他。"""
    if tag and isinstance(tag, str) and tag.strip():
        if tag in TAG_MAP:
            return TAG_MAP[tag]
        if "工程建设" in tag:
            return ("industry", "核能")
    kw = "、".join(keywords or [])
    for key in TAG_MAP:
        if key and key in kw:
            return TAG_MAP[key]
    return ("industry", "其他")


def _norm_date(d):
    d = str(d or "")
    if len(d) == 8:
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return d


def _collect_keywords(insight_entries):
    seen, res = set(), []
    for it in insight_entries:
        kws = it.get("keywords") or []
        if isinstance(kws, str):
            kws = [x.strip() for x in re.split(r"[，、,\s]+", kws) if x.strip()]
        for k in kws:
            if k not in seen:
                seen.add(k)
                res.append(k)
    return res


def _group_by_section(insight_entries):
    """返回：{section_key: {'title':中文名, 'items':[...], 'subs':{子类:[...]}}}"""
    grouped = {
        key: {'title': title, 'items': [], 'subs': {s: [] for s in INDUSTRY_SUB}}
        for title, key in SECTIONS
    }
    for ent in insight_entries:
        tag = ent.get("tag")
        kws = ent.get("keywords")
        sec_key, sub = classify_item(tag, kws)
        if sec_key == "industry" and sub:
            grouped[sec_key]['subs'][sub].append(ent)
        elif sec_key == "industry":
            grouped[sec_key]['subs']["其他"].append(ent)
        else:
            grouped[sec_key]['items'].append(ent)
    return grouped


# ========== LLM 报告生成（首次） ==========
def get_report(
    insight_entries: list[dict],
    articles: list[dict],
    memory: str,         # 保留参数但在首次生成中忽略（不读记忆）
    topics: list[str],
    comment: str,        # 保留参数但在首次生成中忽略
    docx_file: str
) -> tuple[bool, str, str]:
    """
    仅基于本次传入的洞见/文章生成固定模板报告。
    返回: (ok, snapshot_text, report_title)
    """
    today = cn_today_str()
    report_title = topics[0].strip() if (topics and isinstance(topics, list) and (topics[0] or "").strip()) else f"中核日报（{today}）"

    grouped = _group_by_section(insight_entries)
    kws = _collect_keywords(insight_entries)

    # —— 将“洞见内容 + 关联文章摘要”拼成材料，供 LLM 参考（控制长度）
    def _mk_item_material(ent: dict) -> str:
        base = (ent.get("content") or "").strip()[:MAX_ITEM_CHARS]
        # 文章摘要拼入材料（最多取 MAX_ARTICLES_PER_ITEM 篇）
        parts = [base]
        arts = ent.get("articles") or []
        for a in arts[:MAX_ARTICLES_PER_ITEM]:
            title = (a.get("title") or "").strip()
            date_ = _norm_date(a.get("publish_time") or "")
            # 如果调用方给了 article 的 abstract/content，可在 entries 侧先注入；此处只兜底使用 title+date
            parts.append(f"【来源】{title}|{date_}".strip())
        return "\n".join([p for p in parts if p])

    def _mk_sec_material(sec_key: str) -> str:
        if sec_key != "industry":
            lines = []
            for idx, ent in enumerate(grouped[sec_key]['items'], start=1):
                lines.append(f"({idx}) {_mk_item_material(ent)}")
            return "\n".join(lines)
        parts = []
        for sub in INDUSTRY_SUB:
            items = grouped[sec_key]['subs'][sub]
            if not items:
                continue
            parts.append(f"[{sub}]")
            for idx, ent in enumerate(items, start=1):
                parts.append(f"({idx}) {_mk_item_material(ent)}")
        return "\n".join(parts)

    materials = []
    for _, sec_key in SECTIONS:
        sec = grouped.get(sec_key)
        if not sec:
            continue
        has_items = bool(sec['items'])
        has_subs = (sec_key == "industry" and any(sec['subs'][s] for s in INDUSTRY_SUB))
        if has_items or has_subs:
            materials.append(_mk_sec_material(sec_key))

    materials_text = "\n\n".join([m for m in materials if m])

    sys_prompt = (
        "你是一名专业报道撰写助手，请依据提供的“材料”严格生成一份《中核日报》正文：\n"
        "1) 结构：标题行、关键词行、分区（顺序固定：综合要闻、区域新闻、政策数据、科技前沿、行业动态、对标资讯、中核要闻）；\n"
        "2) 只生成有材料的分区；\n"
        "3) 每条用中文陈述事实，正式精炼，不臆造；\n"
        "4) 正文中不要插入链接；\n"
        "5) 标点严格使用中文，编号使用“1，”格式；\n"
        "6) 只输出正文，不要附加说明。"
    )
    user_prompt = (
        f"【标题】{report_title}\n"
        f"【关键词】{'、'.join(kws)}\n\n"
        f"【材料】\n{materials_text}\n\n"
        "【请直接输出上述结构的最终正文（含标题与“关键词：”行）。】"
    )

    snapshot_text = ""
    try:
        snapshot_text = openai_llm(
            messages=[{"role": "system", "content": sys_prompt},
                      {"role": "user", "content": user_prompt}],
            model=REPORT_MODEL,
            temperature=0.2,
            logger_=logger
        ) or ""
    except Exception as e:
        logger.error(f"LLM generate failed: {e}")
        snapshot_text = ""

    # 基本结构校验，失败则兜底程序化拼装
    secs = re.findall(r"^[一二三四五六七]、.*?：$", snapshot_text, flags=re.M)
    nums = re.findall(r"^\d+，", snapshot_text, flags=re.M)
    if not (secs and nums):
        lines = [report_title]
        if kws:
            lines.append(f"关键词：{'、'.join(kws)}")
        for i, (title_cn, sec_key) in enumerate(SECTIONS, start=1):
            sec = grouped.get(sec_key)
            if not sec:
                continue
            has_items = bool(sec['items'])
            has_subs = (sec_key == "industry" and any(sec['subs'][s] for s in INDUSTRY_SUB))
            if not (has_items or has_subs):
                continue
            lines.append(f"{ZH_NUM[i-1]}、{title_cn}：")
            if sec_key != "industry":
                for idx, ent in enumerate(sec['items'], start=1):
                    content = (ent.get("content") or "").strip()
                    lines.append(f"{idx}，{content}")
            else:
                for sub in INDUSTRY_SUB:
                    items = sec['subs'][sub]
                    if not items:
                        continue
                    lines.append(f"（{sub}）")
                    for idx, ent in enumerate(items, start=1):
                        content = (ent.get("content") or "").strip()
                        lines.append(f"{idx}，{content}")
        snapshot_text = "\n".join(lines)

    # 渲染 DOCX（行内链接 + 文末附录）
    ok = build_docx_from_snapshot(
        snapshot_text=snapshot_text,
        articles=articles,
        docx_file=docx_file,
        always_appendix=True,
        inline_links=True,
        grouped_for_links=_group_by_section(insight_entries)
    )
    return ok, snapshot_text, report_title


# ========== LLM 结构锁定改写（修改） ==========
def revise_snapshot_text(snapshot_text: str, comment: str, logger_=None) -> str:
    """
    仅在“修改”场景使用：严格保留结构与编号，只改条目文字。
    """
    if not snapshot_text or not (comment or "").strip():
        return ""

    sys = (
        "你是报告改写助手。请在【严格保留结构与编号】的前提下，根据修改意见对报告正文文字进行润色调整："
        "1) 不得增删任何分区标题、子类标头（如（核能））、编号行（如'1，'）。"
        "2) 标题行与“关键词：”行必须原样保留。"
        "3) 允许改写'综述'段落（若存在）及各编号条目内容；"
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

    def _struct(txt: str):
        return (len(re.findall(r"^[一二三四五六七]、.*?：$", txt, flags=re.M)),
                len(re.findall(r"^\d+，", txt, flags=re.M)))
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

    current_section = None
    current_sub = None
    item_counters = {}
    title2key = {title_cn: sec_key for title_cn, sec_key in SECTIONS}

    i = 1
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        m_sec = re.match(r"^([一二三四五六七])、(.+?)：$", stripped)
        if m_sec:
            h = doc.add_heading(level=2)
            run = h.add_run(stripped)
            run.font.name = u'宋体'
            run._element.rPr.rFonts.set(qn('w:eastAsia'), u'宋体')
            current_sub = None
            sec_title_cn = m_sec.group(2)
            current_section = title2key.get(sec_title_cn)
            item_counters[(current_section, None)] = 0
            i += 1
            continue

        m_sub = re.match(r"^（(.+?)）$", stripped)
        if m_sub:
            p = doc.add_paragraph()
            r = p.add_run(stripped)
            r.bold = True
            current_sub = m_sub.group(1)
            item_counters[(current_section, current_sub)] = 0
            i += 1
            continue

        if re.match(r"^\d+，", stripped):
            p = doc.add_paragraph()
            p.add_run(stripped)

            if inline_links and grouped_for_links:
                key = (current_section, current_sub)
                idx = item_counters.get(key, 0) + 1
                item_counters[key] = idx
                try:
                    if current_section == "industry":
                        items = grouped_for_links["industry"]["subs"].get(current_sub or "其他", [])
                        ent = items[idx - 1] if idx - 1 < len(items) else None
                    else:
                        items = grouped_for_links.get(current_section, {}).get("items", [])
                        ent = items[idx - 1] if idx - 1 < len(items) else None

                    if ent:
                        links = ent.get("articles") or []
                        for link in links[:3]:
                            url = link.get("url") or ""
                            if not url:
                                continue
                            lp = doc.add_paragraph()
                            add_hyperlink(lp, url, url)
                except Exception:
                    pass

            i += 1
            continue

        doc.add_paragraph(line)
        i += 1

    # 文末附录
    if always_appendix or any("附：原始信息网页" in s for s in lines):
        doc.add_heading("附：原始信息网页", level=2)
        for k, a in enumerate(articles, start=1):
            title_a = a.get("title", "")
            url_a = a.get("url", "")
            d = _norm_date(a.get("publish_time", ""))
            doc.add_paragraph(f"{k}、{title_a}|{d}")
            p2 = doc.add_paragraph()
            if url_a:
                add_hyperlink(p2, url_a, url_a)

    doc.save(docx_file)
    return True