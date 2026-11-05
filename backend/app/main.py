from .routes_admin import router as admin_router
from contextlib import asynccontextmanager
from .routes_jobs import router as jobs_router
from .worker import start_worker, stop_worker
from .routes_review import router as review_router
from .routes_practice import router as practice_router
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from . import models  # noqa: F401
from .database import Base, engine
from .routes_auth import router as auth_router
from .routes_courses import router as courses_router
from .routes_images import router as images_router
from .routes_pages import region_router as regions_router
from .routes_pages import router as pages_router
from .routes_sources import router as sources_router
from .routes_plan import router as plan_router

Base.metadata.create_all(bind=engine)
@asynccontextmanager
async def lifespan(_app):
    start_worker()
    yield
    stop_worker()

app = FastAPI(title="Steeplechase API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(courses_router)
app.include_router(sources_router)
app.include_router(images_router)
app.include_router(pages_router)
app.include_router(regions_router)
app.include_router(practice_router)
app.include_router(review_router)
app.include_router(jobs_router)
app.include_router(plan_router)
app.include_router(admin_router)

REVIEW_PAGE = Path(__file__).parent / "static" / "review.html"
EDITOR_PAGE = Path(__file__).parent / "static" / "editor.html"


@app.get("/review", response_class=HTMLResponse, include_in_schema=False)
def review_page():
    return REVIEW_PAGE.read_text(encoding="utf-8")


@app.get("/editor", response_class=HTMLResponse, include_in_schema=False)
def editor_page():
    return EDITOR_PAGE.read_text(encoding="utf-8")


@app.get("/health")
def health():
    return {"status": "ok"}

PRACTICE_PAGE = Path(__file__).parent / "static" / "practice.html"

@app.get("/practice-test", response_class=HTMLResponse, include_in_schema=False)
def practice_page():
    return PRACTICE_PAGE.read_text(encoding="utf-8")

ADMIN_PAGE = Path(__file__).parent / "static" / "admin.html"

@app.get("/admin-test", response_class=HTMLResponse, include_in_schema=False)
def admin_page():
    return ADMIN_PAGE.read_text(encoding="utf-8")