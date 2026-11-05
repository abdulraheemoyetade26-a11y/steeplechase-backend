from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RegisterIn(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=72)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CourseIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    marking_profile: str = "balanced"


class CourseOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str
    marking_profile: str


class SourceOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    course_id: int | None
    filename: str
    file_type: str
    status: str
    error: str | None
    unit_count: int
    created_at: datetime


class ChunkOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    order_index: int
    location_type: str
    location_number: int
    text: str


class ImageOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    source_id: int
    order_index: int
    location_type: str
    location_number: int
    width: int
    height: int
    context_text: str
    suggested_label: str
    label: str
    accepted_answers: list[str]
    note: str
    status: str


class ImageUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=300)
    accepted_answers: list[str] | None = None
    note: str | None = Field(default=None, max_length=1000)
    status: Literal["proposed", "verified", "rejected"] | None = None


class RenderIn(BaseModel):
    pages: list[int] | None = None
    ocr: bool = False

class PageOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    source_id: int
    page_number: int
    width: int
    height: int


class RegionOut(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    page_id: int
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    accepted_answers: list[str]
    origin: str
    status: str
    confidence: float


class RegionCreate(BaseModel):
    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)
    text: str = Field(min_length=1, max_length=300)
    accepted_answers: list[str] = []


class RegionUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=300)
    accepted_answers: list[str] | None = None
    status: Literal["proposed", "verified", "rejected"] | None = None


class CropIn(BaseModel):
    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)
    label: str = Field(min_length=1, max_length=300)
    accepted_answers: list[str] = []
    note: str = Field(default="", max_length=1000)