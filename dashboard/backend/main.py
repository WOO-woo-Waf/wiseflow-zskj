from typing import List, Optional, Dict

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from __init__ import BackendService


# =======================
# Pydantic Models
# =======================

class SitesRequest(BaseModel):
    after: str = Field(..., pattern=r"^\d{8}$", description="YYYYMMDD")
    sites: List[str]
    task_id: str


class DataResponse(BaseModel):
    task_id: str
    working: bool
    progress: Optional[float] = None
    stats: Optional[Dict[str, int]] = None
    last_update: Optional[str] = None


class InvalidInputException(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=442, detail=detail)


class TranslateRequest(BaseModel):
    article_ids: List[str]


# ------- 旧接口的请求体（兼容） -------
class ReportRequest(BaseModel):
    insight_id: str
    toc: List[str] = [""]                 # 旧字段名：标题列表（沿用）
    comment: str = ""                     # 旧逻辑：comment 为空 → 生成；非空 → 修改
    insight_ids: Optional[List[str]] = None
    force_regenerate: bool = False


# ------- 新接口的请求体 -------
class GenerateReportRequest(BaseModel):
    """首次生成：只用这次的洞见/文章，不读取记忆"""
    insight_id: str
    toc: List[str] = [""]                 # 标题（取 toc[0]；为空则用默认“中核日报（YYYY年M月D日）”）
    insight_ids: Optional[List[str]] = None


# ------- 新的请求体（确保 memory_id 为必填）-------
class ReviseReportRequest(BaseModel):
    """基于选中的记忆 + 修改意见进行结构锁定改写"""
    insight_id: str                      # 用于把新 DOCX 上传到哪个 insight 的 docx 字段
    comment: str                         # 修改意见（必填）
    memory_id: str                       # ★ 必填：作为底稿的 report_memories 记录 ID
    insight_ids_for_footer: Optional[List[str]] = None  # 可选：用于重拉附录/行内链接



# =======================
# FastAPI App
# =======================

app = FastAPI(
    title="wiseflow Backend Server",
    description="From WiseFlow Team.",
    version="0.4",
    openapi_url="/openapi.json"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

bs = BackendService()


@app.get("/")
def read_root():
    return {"msg": "Hello, This is WiseFlow Backend."}


# =======================
# 你现有保留的接口
# =======================

@app.post("/sites")
def create_sites(req: SitesRequest):
    """
    仅把任务写入 PB.sites，交给你现有的 task 机制去执行；后端不额外跑 pipeline。
    前端 createTask() 正是调用这个接口。
    """
    ok = bs.upsert_task_site(req.task_id, req.after, req.sites)
    if not ok:
        raise HTTPException(status_code=400, detail="failed to upsert task to PB.sites")
    return {"task_id": req.task_id, "accepted": True}


@app.post("/search_for_insight")
def add_article_from_insight(request: ReportRequest):
    # 沿用你现有逻辑
    return bs.more_search(request.insight_id)


# =======================
# 新的报告相关接口
# =======================


@app.post("/report/generate")
def generate_report(request: GenerateReportRequest):
    """
    首次生成（严格不读记忆）：
    - 仅使用这次传入的洞见/文章拼接材料
    - 调用 LLM 生成正文
    - 渲染 DOCX 并上传 PB（文件名优先取 toc[0]）
    - 在 report_memories 写入一条新记录
    返回：
    {
      code: 11,
      data: {
        insight_id, title, docx_filename, docx_url, memory_id
      }
    }
    """
    return bs.generate_report(
        anchor_id=request.insight_id,
        topics=request.toc,
        insight_ids=request.insight_ids or [request.insight_id]
    )


@app.post("/report/revise")
def revise_report(request: ReviseReportRequest):
    """
    应用修改（基于选中的记忆）：
    - 必须传 memory_id：以该条 report_memories.snapshot 为底稿改写
    - get_report() 内部完成：按意见改写→渲染新 DOCX→写入新的 report_memories
    返回：
    {
      code: 11,
      data: { title, memory_id, docx_path }
    }
    """
    if not request.comment.strip():
        raise InvalidInputException("comment is required for /report/revise")
    if not request.memory_id.strip():
        raise InvalidInputException("memory_id is required for /report/revise")

    return bs.revise_report(
        anchor_id=request.insight_id,
        comment=request.comment,
        insight_ids_for_footer=request.insight_ids_for_footer,
        memory_id=request.memory_id,
    )

# =======================
# 旧接口兼容（可逐步下线）
# =======================

@app.post("/report")
def report_compat(request: ReportRequest):
    """
    兼容旧路由：
    - force_regenerate 或 comment 为空 → 当作“首次生成”（严格不读记忆）
    - comment 非空 → 当作“修改”（基于最新快照）
    """
    if request.force_regenerate or not request.comment.strip():
        return bs.generate_report(
            anchor_id=request.insight_id,
            topics=request.toc,
            insight_ids=request.insight_ids or [request.insight_id]
        )
    else:
        return bs.revise_report(
            anchor_id=request.insight_id,
            comment=request.comment,
            insight_ids_for_footer=request.insight_ids,
            memory_id=None,  # 旧接口无 memory_id，后端走“最新”逻辑
        )
