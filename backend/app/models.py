import json
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def now():
    return datetime.now(timezone.utc)

def naive_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    tier: Mapped[str] = mapped_column(String(20), default="free")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    plan: Mapped[str] = mapped_column(String(20), default="free") # free, basic, pro
    plan_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    pages_processed_this_month: Mapped[int] = mapped_column(Integer, default=0)
    usage_month: Mapped[str] = mapped_column(String(10), default="")
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    tutorial_seen: Mapped[bool] = mapped_column(Boolean, default=False)


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    marking_profile: Mapped[str] = mapped_column(String(30), default="balanced")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(300))
    file_type: Mapped[str] = mapped_column(String(10))
    stored_path: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="processing")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="source", cascade="all, delete-orphan", order_by="Chunk.order_index"
    )
    images: Mapped[list["ImageItem"]] = relationship(
        cascade="all, delete-orphan", order_by="ImageItem.order_index"
    )
    pages: Mapped[list["PageRender"]] = relationship(
        cascade="all, delete-orphan", order_by="PageRender.page_number"
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    order_index: Mapped[int] = mapped_column(Integer)
    location_type: Mapped[str] = mapped_column(String(10))
    location_number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)

    source: Mapped["Source"] = relationship(back_populates="chunks")


class ImageItem(Base):
    __tablename__ = "image_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    order_index: Mapped[int] = mapped_column(Integer)
    location_type: Mapped[str] = mapped_column(String(10))
    location_number: Mapped[int] = mapped_column(Integer)
    file_path: Mapped[str] = mapped_column(String(500))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(40))
    context_text: Mapped[str] = mapped_column(Text, default="")
    suggested_label: Mapped[str] = mapped_column(String(300), default="")
    label: Mapped[str] = mapped_column(String(300), default="")
    accepted_json: Mapped[str] = mapped_column(Text, default="[]")
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    @property
    def accepted_answers(self) -> list[str]:
        try:
            value = json.loads(self.accepted_json or "[]")
            return value if isinstance(value, list) else []
        except ValueError:
            return []


class PageRender(Base):
    __tablename__ = "page_renders"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    file_path: Mapped[str] = mapped_column(String(500))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    ocr_done: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    regions: Mapped[list["LabelRegion"]] = relationship(
        cascade="all, delete-orphan", order_by="LabelRegion.y0"
    )


class LabelRegion(Base):
    __tablename__ = "label_regions"

    id: Mapped[int] = mapped_column(primary_key=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("page_renders.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    x0: Mapped[float] = mapped_column(Float)
    y0: Mapped[float] = mapped_column(Float)
    x1: Mapped[float] = mapped_column(Float)
    y1: Mapped[float] = mapped_column(Float)
    text: Mapped[str] = mapped_column(String(300), default="")
    accepted_json: Mapped[str] = mapped_column(Text, default="[]")
    origin: Mapped[str] = mapped_column(String(10), default="text")
    confidence: Mapped[float] = mapped_column(Float, default=100.0)
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    corrected_from: Mapped[str | None] = mapped_column(String(300), nullable=True)

    @property
    def accepted_answers(self) -> list[str]:
        try:
            value = json.loads(self.accepted_json or "[]")
            return value if isinstance(value, list) else []
        except ValueError:
            return []


class PracticeSession(Base):
    __tablename__ = "practice_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(12), default="active")
    station_count: Mapped[int] = mapped_column(Integer)
    seconds_per_station: Mapped[int] = mapped_column(Integer)
    labels_per_station: Mapped[int] = mapped_column(Integer)
    rest_every: Mapped[int] = mapped_column(Integer, default=0)
    rest_seconds: Mapped[int] = mapped_column(Integer, default=30)
    earned: Mapped[float] = mapped_column(Float, default=0.0)
    possible: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=naive_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    stations: Mapped[list["PracticeStation"]] = relationship(
        cascade="all, delete-orphan", order_by="PracticeStation.number"
    )


class PracticeStation(Base):
    __tablename__ = "practice_stations"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("practice_sessions.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(10), default="station")
    page_id: Mapped[int | None] = mapped_column(ForeignKey("page_renders.id"), nullable=True)
    region_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    late: Mapped[bool] = mapped_column(Boolean, default=False)
    answers_json: Mapped[str] = mapped_column(Text, default="[]")
    results_json: Mapped[str] = mapped_column(Text, default="[]")


class LabelFlag(Base):
    __tablename__ = "label_flags"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("label_regions.id"), index=True)
    reason: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=naive_now)
    status: Mapped[str] = mapped_column(String(10), default="pending")
    session_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    student_answer: Mapped[str] = mapped_column(Text, default="")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_by: Mapped[int | None] = mapped_column(Integer, nullable=True)

class LabelAudit(Base):
    __tablename__ = "label_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("label_regions.id"), unique=True, index=True)
    ocr_text: Mapped[str] = mapped_column(String(300), default="")
    final_text: Mapped[str] = mapped_column(String(300), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    decision: Mapped[str] = mapped_column(String(10), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=naive_now)
    action: Mapped[str] = mapped_column(String(20), default="decided")
    undone: Mapped[bool] = mapped_column(Boolean, default=False)

class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    scope: Mapped[str] = mapped_column(String(12), default="image_pages")
    pages_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(12), default="queued")
    pages_total: Mapped[int] = mapped_column(Integer, default=0)
    pages_done: Mapped[int] = mapped_column(Integer, default=0)
    pages_failed: Mapped[int] = mapped_column(Integer, default=0)
    labels_found: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(String(300), default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=naive_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class ActivationCode(Base):
    __tablename__ = "activation_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    plan: Mapped[str] = mapped_column(String(10))
    days: Mapped[int] = mapped_column(Integer, default=30)
    batch: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=naive_now)
    used_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    page: Mapped[str] = mapped_column(String(300), default="")
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(20), default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=naive_now)