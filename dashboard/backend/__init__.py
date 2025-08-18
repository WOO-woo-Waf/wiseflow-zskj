import os
import time
import json
import uuid
from get_report import get_report, logger, pb, revise_snapshot_text, build_docx_from_snapshot, PROJECT_DIR
from get_search import search_insight
from datetime import datetime



# ========== 记忆存储（每个 anchor 仅一份最新快照） ==========
class MemoryStore:
    """只保存每个 anchor(insight_id) 的一份最新快照与历史；支持清全部。"""
    def __init__(self):
        # { anchor_id: {"snapshot": str, "filename": str, "history": [ {"snapshot":..., "filename":...} ] } }
        self._mem = {}

    def get(self, anchor_id: str) -> dict | None:
        return self._mem.get(anchor_id)

    def set(self, anchor_id: str, snapshot: str, filename: str):
        prev = self._mem.get(anchor_id)
        if prev and prev.get("snapshot") and prev.get("filename"):
            hist = prev.get("history", [])
            hist.insert(0, {"snapshot": prev["snapshot"], "filename": prev["filename"]})
            self._mem[anchor_id] = {"snapshot": snapshot, "filename": filename, "history": hist[:20]}
        else:
            self._mem[anchor_id] = {"snapshot": snapshot, "filename": filename, "history": []}

    def clear_one(self, anchor_id: str) -> int:
        return 1 if self._mem.pop(anchor_id, None) is not None else 0

    def clear_all(self) -> int:
        n = len(self._mem)
        self._mem.clear()
        return n


# ========== 后端服务 ==========
class BackendService:
    def __init__(self):
        self.project_dir = PROJECT_DIR
        self.cache_url = os.path.join(self.project_dir, "backend_service")
        os.makedirs(self.cache_url, exist_ok=True)
        self.memory = MemoryStore()
        logger.info("backend service init success.")

    # ---- 通用返回包装（若你已有同名实现可保留原实现） ----
    def build_out(self, code: int, data):
        return {"code": code, "data": data}

    # ---- 拉取洞见与文章并组装为 entries/footer ----
    def _fetch_entries_and_footer(self, insight_ids: list[str]):
        insights = []
        for iid in insight_ids:
            rec = pb.read(
                "insights",
                fields=["id", "content", "tag", "keywords", "articles", "docx"],
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
                fields=["id", "title", "abstract", "content", "url", "publish_time"],
                filter=f'id="{aid}"',
            )
            if rec and rec[0]:
                articles_map[aid] = rec[0]

        # 组装 entries & footer
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
                    # 如果你希望 LLM 材料中包含文章摘要，可在此把 abstract/content 注入到 entries
                    # "abstract": (a.get("abstract") or a.get("content") or "")[:MAX_ABSTRACT_CHARS],
                })
                used_article_ids.append(aid)

            entries.append({
                "id": ins["id"],
                "content": (ins.get("content") or "").strip(),
                "tag": ins.get("tag") or "",
                "keywords": kws,
                "articles": links,
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

    # ---- 首次生成（严格不读记忆） ----
    def generate_report(self, anchor_id: str, topics: list[str], insight_ids: list[str]) -> dict:
        try:
            target_ids = list(dict.fromkeys([_id for _id in (insight_ids or [anchor_id]) if _id]))
            if not target_ids:
                return self.build_out(-2, "no valid insight id")

            entries, footer = self._fetch_entries_and_footer(target_ids)
            if not entries:
                return self.build_out(-2, "no valid insight found")

            tmp_docx = os.path.join(self.cache_url, f"{anchor_id}_{uuid.uuid4()}.docx")
            ok, snapshot, report_title = get_report(
                insight_entries=entries,
                articles=footer or [],
                memory="",          # 首次生成忽略记忆
                topics=topics,
                comment="",         # 首次生成忽略 comment
                docx_file=tmp_docx,
            )
            if not ok:
                return self.build_out(-11, "report generate failed.")

            final_filename = f"{report_title}.docx"
            with open(tmp_docx, "rb") as f:
                message = pb.upload("insights", anchor_id, "docx", final_filename, f)
            if not message:
                return self.build_out(-2, "report generated but PB update failed")

            # 写入记忆（仅一份最新）
            self.memory.set(anchor_id, snapshot, final_filename)
            logger.debug(f"report success and updated PB: {anchor_id}")
            # 返回可下载文件名（前端从 PB 的 docx 字段即可下载）
            return self.build_out(11, {"insight_id": anchor_id, "filename": final_filename})
        except Exception as e:
            logger.error(f"generate_report error: {e}")
            return self.build_out(-2, "internal error")

    # ---- 追加修改（基于上一版快照） ----
    def revise_report(self, anchor_id: str, comment: str, insight_ids_for_footer: list[str] | None = None) -> dict:
        """
        如需保证附录仍完整，可传 insight_ids_for_footer 以便重拉文章生成 footer；
        不传则附录生成空列表（仅改正文）。
        """
        try:
            prev = self.memory.get(anchor_id)
            if not prev or not prev.get("snapshot"):
                return self.build_out(-2, "no previous snapshot to revise")

            revised = revise_snapshot_text(prev["snapshot"], comment, logger_=logger)
            if not revised:
                return self.build_out(-11, "revise failed")

            # 重新拉一遍文章，保证行内链接/附录仍可生成（推荐做法）
            footer = []
            if insight_ids_for_footer:
                _, footer = self._fetch_entries_and_footer(list(dict.fromkeys(insight_ids_for_footer)))

            tmp_docx = os.path.join(self.cache_url, f"{anchor_id}_{uuid.uuid4()}.docx")
            ok = build_docx_from_snapshot(
                snapshot_text=revised,
                articles=footer or [],
                docx_file=tmp_docx,
                always_appendix=True,
                inline_links=False,           # 修改时通常只改文字；如需也保留行内链接，可设 True 并传 grouped_for_links
                grouped_for_links=None
            )
            if not ok:
                return self.build_out(-11, "revise render failed")

            report_title = revised.splitlines()[0].strip() if revised else f"中核日报（{cn_today_str()}）"
            final_filename = f"{report_title}.docx"
            with open(tmp_docx, "rb") as f:
                message = pb.upload("insights", anchor_id, "docx", final_filename, f)
            if not message:
                return self.build_out(-2, "revise generated but PB update failed")

            self.memory.set(anchor_id, revised, final_filename)
            logger.debug(f"revise success and updated PB: {anchor_id}")
            return self.build_out(11, {"insight_id": anchor_id, "filename": final_filename})
        except Exception as e:
            logger.error(f"revise_report error: {e}")
            return self.build_out(-2, "internal error")

    # ---- 清除记忆（可清单个或全部） ----
    def clear_report_memory(self, insight_id: str | None = None, clear_all: bool = False) -> dict:
        try:
            if clear_all:
                n = self.memory.clear_all()
                return self.build_out(11, f"cleared {n} memory keys")
            if not insight_id:
                return self.build_out(-2, "insight_id required or set clear_all=True")
            removed = self.memory.clear_one(insight_id)
            return self.build_out(11, f"cleared {removed} memory key")
        except Exception as e:
            logger.error(f"clear_report_memory error: {e}")
            return self.build_out(-2, "internal error")

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

