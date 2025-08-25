# main.py
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

app = FastAPI()

DIST_DIR = Path(__file__).parent / "dist"
INDEX_FILE = DIST_DIR / "index.html"

# === 这里挂你的 /api 路由（一定要写在 mount/回退 之前）===
# from .api import router as api_router
# app.include_router(api_router, prefix="/api")

# 性能优先：单独挂载 /assets（Vite 打包静态资源目录）
app.mount("/assets", StaticFiles(directory=str(DIST_DIR / "assets")), name="assets")

def safe_path(rel: str) -> Path:
    """
    将 URL 路径映射到 dist 下的安全文件路径，防止目录穿越。
    """
    full = (DIST_DIR / rel.lstrip("/")).resolve()
    root = DIST_DIR.resolve()
    if not str(full).startswith(str(root)):
        # 阻止越权访问
        raise HTTPException(status_code=404)
    return full

@app.get("/", include_in_schema=False)
async def root():
    # 首页返回 index.html
    if not INDEX_FILE.is_file():
        raise HTTPException(status_code=500, detail="index.html not found.")
    return FileResponse(INDEX_FILE)

# 顶层常见静态文件（可选，但能明确类型，避免部分代理错误识别）
@app.get("/vite.svg", include_in_schema=False)
async def vite_svg():
    file = safe_path("vite.svg")
    if file.is_file():
        return FileResponse(file, media_type="image/svg+xml")
    raise HTTPException(status_code=404)

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    file = safe_path("favicon.ico")
    if file.is_file():
        return FileResponse(file)
    raise HTTPException(status_code=404)

# SPA 回退：除 /api/* 外，其他路径先尝试文件命中，不存在则回退 index.html
@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str):
    # 不拦截 API
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404)

    # 命中文件则返回
    file = safe_path(full_path)
    if file.is_file():
        # 例如 /manifest.webmanifest、/robots.txt、/some.png 等
        return FileResponse(file)

    # 未命中文件：统一回退到 SPA 入口
    if INDEX_FILE.is_file():
        return FileResponse(INDEX_FILE)

    raise HTTPException(status_code=500, detail="index.html not found.")
