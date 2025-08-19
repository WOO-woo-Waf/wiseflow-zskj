import os
from pathlib import Path
import time
import json
import uuid

from dotenv import load_dotenv
from get_report import cn_today_str, get_report, logger, pb, revise_snapshot_text, build_docx_from_snapshot, PROJECT_DIR
from get_search import search_insight
from datetime import datetime

# ========== PB 持久化记忆 + 后端服务（替换你给的整段） ==========
# ========== 环境 & 客户端 ==========
ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)
# 可选：用于兜底构造 PocketBase 文件URL（如 pb_api 未提供现成方法）
PB_BASE_URL = os.environ.get("PB_BASE_URL", "").rstrip("/")


# ========== 后端服务 ==========
class BackendService:
    def __init__(self):
        self.project_dir = PROJECT_DIR
        self.cache_url = os.path.join(self.project_dir, "backend_service")
        os.makedirs(self.cache_url, exist_ok=True)
        logger.info("backend service init success.")

    @staticmethod
    def build_out(code: int, data):
        return {"code": code, "data": data}

    # ---------- 工具：读取单条记忆，拿到 docx_path ----------
    def _read_memory_docx_path(self, memory_id: str) -> str:
        try:
            recs = pb.read(
                "report_memories",
                fields=["id", "docx_path"],
                filter=f'id="{memory_id}"'
            )
            if recs and recs[0]:
                return recs[0].get("docx_path") or ""
        except Exception as e:
            logger.warning(f"_read_memory_docx_path error: {e}")
        return ""

    # ---------- 首次生成（不读记忆；仅返回下载链接等） ----------
    def generate_report(self, anchor_id: str, topics: list[str], insight_ids: list[str] | None) -> dict:
        """
        - 仅使用本次传入的洞见/文章生成
        - 由 get_report() 内部完成：逐洞见处理/汇总、渲染 DOCX、保存记忆（title/snapshot/docx_path）
        - 本方法只负责把下载链接等返回给前端
        """
        try:
            target_ids = list(dict.fromkeys([_id for _id in (insight_ids or [anchor_id]) if _id]))
            if not target_ids:
                return self.build_out(-2, "no valid insight id")

            # 拉 entries + footer
            entries, footer = self._fetch_entries_and_footer(target_ids)
            if not entries:
                return self.build_out(-2, "no valid insight found")

            # 本地临时 docx 路径（传入 get_report 用来渲染）
            tmp_docx = os.path.join(self.cache_url, f"{anchor_id}_{uuid.uuid4()}.docx")

            # 调用你新版 get_report（它会入库记忆，并返回 memory_id）
            # 新版约定返回 4 元组：ok, snapshot_text, report_title, memory_id
            ok, snapshot_text, report_title, memory_id = get_report(
                insight_entries=entries,
                articles=footer or [],
                memory="",              # 首次生成不读记忆
                topics=topics,
                comment="",             # 无改写意见
                docx_file=tmp_docx,
            )
            if not ok:
                return self.build_out(-11, "report generate failed")

            # 根据 memory_id 拿 docx_path（下载链接）
            docx_path = self._read_memory_docx_path(memory_id) if memory_id else ""
            if not docx_path:
                logger.warning("report generated but docx_path is empty in memory")

            return self.build_out(11, {
                "title": report_title,
                "memory_id": memory_id,
                "docx_path": docx_path,     # 前端直接用这个链接下载
            })
        except Exception as e:
            logger.error(f"generate_report error: {e}")
            return self.build_out(-2, "internal error")

    # ---------- 追加修改（基于前端选中的 memory + comment） ----------
    def revise_report(self,
                      anchor_id: str,
                      comment: str,
                      insight_ids_for_footer: list[str] | None = None,
                      memory_id: str | None = None) -> dict:
        """
        - 前端必须传 memory_id：服务层从 PB 读出 memory.snapshot，然后把 memory + comment 交给 get_report 改写
        - get_report() 内部完成渲染 DOCX & 保存“新记忆”
        - 本方法返回新记忆的下载链接（docx_path）
        """
        try:
            if not (comment or "").strip():
                return self.build_out(-2, "comment required")
            if not (memory_id or "").strip():
                return self.build_out(-2, "memory_id required")

            # 读出被选中的历史快照
            mem = pb.read(
                "report_memories",
                fields=["id", "snapshot", "title"],
                filter=f'id="{memory_id}"'
            )
            if not mem or not mem[0] or not (mem[0].get("snapshot") or "").strip():
                return self.build_out(-2, "invalid memory_id or empty snapshot")
            base_snapshot = mem[0]["snapshot"]

            # 可选：重拉 footer（保证文末附录/行内链接）
            footer = []
            if insight_ids_for_footer:
                _, footer = self._fetch_entries_and_footer(list(dict.fromkeys(insight_ids_for_footer)))

            tmp_docx = os.path.join(self.cache_url, f"{anchor_id}_{uuid.uuid4()}.docx")

            # 调用 get_report 的“改写模式”
            ok, new_text, report_title, new_memory_id = get_report(
                insight_entries=[],         # 改写不需要 entries
                articles=footer or [],
                memory=base_snapshot,       # 关键：传入原快照
                topics=[report_title] if (report_title := mem[0].get("title")) else [""],
                comment=comment,            # 改写意见
                docx_file=tmp_docx,
            )
            if not ok:
                return self.build_out(-11, "revise failed")

            docx_path = self._read_memory_docx_path(new_memory_id) if new_memory_id else ""
            if not docx_path:
                logger.warning("revise succeeded but docx_path is empty in memory")

            return self.build_out(11, {
                "title": report_title or (new_text.splitlines()[0].strip() if new_text else f"中核日报（{cn_today_str()}）"),
                "memory_id": new_memory_id,
                "docx_path": docx_path,
            })
        except Exception as e:
            logger.error(f"revise_report error: {e}")
            return self.build_out(-2, "internal error")

    # ---- 拉取洞见与文章并组装为 entries/footer ----
    def _fetch_entries_and_footer(self, insight_ids: list[str]):
        insights = []
        for iid in insight_ids:
            rec = pb.read(
                "insights",
                fields=["id", "content", "tag", "articles", "url", "docx", "category"],
                filter=f'id="{iid}"',
            )
            if rec and rec[0]:
                insights.append(rec[0])
            else:
                logger.warning(f"insight {iid} not found, skip")

        if not insights:
            return None, None

        # 收集文章
        article_ids = []
        for ins in insights:
            article_ids.extend(ins.get("articles") or [])
        article_ids = list(dict.fromkeys(article_ids))

        articles_map = {}
        for aid in article_ids:
            rec = pb.read(
                "articles",
                fields=["id", "title", "abstract", "content", "url", "publish_time", "category"],
                filter=f'id="{aid}"',
            )
            if rec and rec[0]:
                articles_map[aid] = rec[0]

        # 组装 entries（供 get_report 使用） & footer（文末附录）
        used_article_ids = []
        entries = []
        for ins in insights:
            kws = ins.get("keywords") or []
            if isinstance(kws, str):
                kws = [x.strip() for x in re.split(r"[，、,\s]+", kws) if x.strip()]

            links = []
            for aid in (ins.get("articles") or []):
                a = articles_map.get(aid)
                if not a:
                    continue
                links.append({
                    "title": a.get("title", ""),
                    "url": a.get("url", ""),
                    "publish_time": a.get("publish_time", ""),
                    # 如需把摘要送入 LLM，可取消注释
                    # "abstract": (a.get("abstract") or a.get("content") or "")[:MAX_ABSTRACT_CHARS],
                })
                used_article_ids.append(aid)

            entries.append({
                "id": ins["id"],
                "content": (ins.get("content") or "").strip(),
                "tag": ins.get("tag") or "",
                "keywords": kws,
                "url": ins.get("url", "") or "",   # 关键：洞见的源链接
                "articles": links,
                # 也可把 category 放进来（若存在）
                "category": ins.get("category") or "",
            })

        footer_articles = []
        seen = set()
        for aid in used_article_ids:
            if aid in seen:
                continue
            seen.add(aid)
            a = articles_map.get(aid)
            if not a:
                continue
            footer_articles.append({
                "title": a.get("title", ""),
                "abstract": a.get("abstract", ""),
                "content": a.get("content", ""),
                "url": a.get("url", ""),
                "publish_time": a.get("publish_time", ""),
            })

        return entries, footer_articles

    # ---- 旧接口兼容：/report ----
    def report(
        self,
        insight_id: str,
        topics: list[str],
        comment: str,
        insight_ids: list[str] | None = None,
        force_regenerate: bool = False,
    ) -> dict:
        """
        兼容老前端：
        - force_regenerate 或 comment 为空 → 当作“首次生成”（严格不读记忆）；
        - comment 非空 → 当作“修改”（基于最新快照）。
        """
        logger.debug(
            f'got report request insight_id={insight_id}, insight_ids={insight_ids}, '
            f'comment_len={len(comment or "")}, force={force_regenerate}'
        )
        if force_regenerate or not (comment or "").strip():
            return self.generate_report(
                anchor_id=insight_id,
                topics=topics,
                insight_ids=insight_ids or [insight_id]
            )
        else:
            return self.revise_report(
                anchor_id=insight_id,
                comment=comment,
                insight_ids_for_footer=insight_ids or [insight_id]
            )


    def build_out(self, flag: int, answer: str = "") -> dict:
        return {"flag": flag, "result": [{"type": "text", "answer": answer}]}

    def more_search(self, insight_id: str) -> dict:
        logger.debug(f'got search request for insight： {insight_id}')
        insight = pb.read('insights', filter=f'id="{insight_id}"')
        if not insight:
            logger.error(f'insight {insight_id} not found')
            return self.build_out(-2, 'insight not found')

        article_ids = insight[0]['articles']
        if article_ids:
            article_list = [pb.read('articles', fields=['url'], filter=f'id="{_id}"') for _id in article_ids]
            url_list = [_article[0]['url'] for _article in article_list if _article]
        else:
            url_list = []

        flag, search_result = search_insight(insight[0]['content'], logger, url_list)
        if flag <= 0:
            logger.debug('no search result, nothing happen')
            return self.build_out(flag, 'search engine error or no result')

        for item in search_result:
            new_article_id = pb.add(collection_name='articles', body=item)
            if new_article_id:
                article_ids.append(new_article_id)
            else:
                logger.warning(f'add article {item} failed, writing to cache_file')
                with open(os.path.join(self.cache_url, 'cache_articles.json'), 'a', encoding='utf-8') as f:
                    json.dump(item, f, ensure_ascii=False, indent=4)

        message = pb.update(collection_name='insights', id=insight_id, body={'articles': article_ids})
        if message:
            logger.debug(f'insight search success finish and update to: {message}')
            return self.build_out(11, insight_id)
        else:
            logger.error(f'{insight_id} search success, however failed to update to pb.')
            return self.build_out(-2, 'search success, however failed to update to pb.')

    def _clean_sites(self, sites: list[str]) -> list[str]:
        # 去空白、去重复
        seen = set()
        cleaned = []
        for s in sites or []:
            s = (s or "").strip()
            if not s or s in seen:
                continue
            seen.add(s)
            cleaned.append(s)
        return cleaned

    def upsert_task_site(self, task_id: str, after_yyyymmdd: str, sites: list[str]) -> bool:
        """
        仅负责把任务写/更新到 PB 的 sites 集合，让你的“task 机制”自行消费。
        不触发任何抓取或后台流程。
        需要 sites 集合具备字段：task_id(text), after(text), sites(json/array), working(bool), progress(number)
        """
        try:
            sites = self._clean_sites(sites)
            if not sites:
                return False

            # 查是否已有同 task_id 记录
            exist = pb.read('sites', filter=f'task_id="{task_id}"')
            body = {
                "task_id": task_id,
                "after": after_yyyymmdd,   # 形如 YYYYMMDD
                "sites": sites,
                "working": True,           # 交给 task 机制消费，消费完自行置 False
                "progress": 0
            }

            if exist:
                site_id = exist[0]['id']
                ok = pb.update('sites', site_id, body)
                return bool(ok)
            else:
                site_id = pb.add('sites', body)
                return bool(site_id)
        except Exception as e:
            logger.exception(f"upsert_task_site failed: {e}")
            return False

