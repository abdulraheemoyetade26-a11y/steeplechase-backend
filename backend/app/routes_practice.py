import io
import json
import random
from datetime import datetime, timedelta, timezone
from sqlalchemy import and_, or_, select, func
from .plans import plan_summary
from .trust import (
    PRACTICE_MIN_CONF,
    REVIEW_SECONDS_PER_LABEL,
    accepted_variants,
    build_vocabulary,
    is_eligible,
    is_supported,
    region_trust,
)

from .worker import job_summary
from fastapi import APIRouter, Depends, HTTPException, Response
from PIL import Image, ImageDraw
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .deps import get_current_user
from .grading import grade_answer, outcome_points
from .models import LabelFlag, LabelRegion, PageRender, PracticeSession, PracticeStation, ProcessingJob, Source, User
from .routes_pages import draw_number

router = APIRouter(prefix="/practice", tags=["practice"])

GRACE_SECONDS = 5

class SessionCreate(BaseModel):
    source_ids: list[int] | None = None
    station_count: int = Field(default=10, ge=1, le=60)
    seconds_per_station: int = Field(default=60, ge=10, le=600)
    labels_per_station: int = Field(default=1, ge=1, le=10)
    rest_every: int = Field(default=0, ge=0, le=20)
    rest_seconds: int = Field(default=30, ge=5, le=300)

class AnswerIn(BaseModel):
    answers: list[str] = Field(default_factory=list, max_length=10)

class FlagIn(BaseModel):
    region_id: int
    reason: str = Field(default="", max_length=300)

def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

def own_session(db: Session, session_id: int, user: User) -> PracticeSession:
    session = db.get(PracticeSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(404, "Practice session not found")
    return session

def get_station(db: Session, session: PracticeSession, number: int) -> PracticeStation:
    station = db.scalar(
        select(PracticeStation).where(PracticeStation.session_id == session.id, PracticeStation.number == number)
    )
    if station is None:
        raise HTTPException(404, "Station not found")
    return station

def deadline_of(session: PracticeSession, station: PracticeStation) -> datetime:
    return station.started_at + timedelta(seconds=session.seconds_per_station)

def station_state(session: PracticeSession, station: PracticeStation, now: datetime) -> str:
    if station.kind == "rest":
        return "rest"
    if station.submitted_at is not None:
        return "done"
    if station.started_at is None:
        return "pending"
    if now > deadline_of(session, station) + timedelta(seconds=GRACE_SECONDS):
        return "expired"
    return "active"

def region_ids_of(station: PracticeStation) -> list[int]:
    try:
        value = json.loads(station.region_ids_json or "[]")
        return value if isinstance(value, list) else []
    except ValueError:
        return []

def load_regions(db: Session, ids: list[int]) -> dict[int, LabelRegion]:
    if not ids:
        return {}
    rows = db.scalars(select(LabelRegion).where(LabelRegion.id.in_(ids))).all()
    return {r.id: r for r in rows}

def describe_session(session: PracticeSession, now: datetime) -> dict:
    return {
        "id": session.id,
        "status": session.status,
        "station_count": session.station_count,
        "seconds_per_station": session.seconds_per_station,
        "labels_per_station": session.labels_per_station,
        "rest_every": session.rest_every,
        "rest_seconds": session.rest_seconds,
        "earned": session.earned,
        "possible": session.possible,
        "stations": [
            {
                "number": s.number,
                "kind": s.kind,
                "state": station_state(session, s, now),
                "labels": len(region_ids_of(s)),
            }
            for s in session.stations
        ],
    }

def masked_image(path: str, regions: list[LabelRegion], numbered: bool) -> bytes:
    img = Image.open(path).convert("RGB")
    width, height = img.size
    draw = ImageDraw.Draw(img)
    for number, region in enumerate(regions, start=1):
        box = (int(region.x0 * width), int(region.y0 * height), int(region.x1 * width), int(region.y1 * height))
        draw.rectangle(box, fill=(70, 70, 70), outline=(255, 255, 255), width=2)
        if numbered:
            draw_number(draw, box, str(number))
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=88)
    return buffer.getvalue()

@router.post("/sessions")
def create_session(data: SessionCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = (
        select(LabelRegion, PageRender)
        .join(PageRender, PageRender.id == LabelRegion.page_id)
        .where(
            PageRender.user_id == user.id,
            or_(
                LabelRegion.status == "verified",
                and_(LabelRegion.status == "auto", LabelRegion.confidence >= PRACTICE_MIN_CONF),
            ),
        )
    )
    if data.source_ids:
        query = query.where(PageRender.source_id.in_(data.source_ids))
    rows = db.execute(query).all()

    flagged = set(db.scalars(select(LabelFlag.region_id).where(LabelFlag.user_id == user.id)).all())
    by_page: dict[int, list[LabelRegion]] = {}
    for region, page in rows:
        if region.id in flagged:
            continue
        by_page.setdefault(page.id, []).append(region)

    if not by_page:
        raise HTTPException(400, "No usable labels yet. Render pages and read labels for a source first.")

    page_ids = list(by_page)
    random.shuffle(page_ids)
    used: set[int] = set()
    plan: list[tuple[int, list[int]]] = []
    for index in range(data.station_count):
        if index > 0 and index % len(page_ids) == 0:
            random.shuffle(page_ids)
        page_id = page_ids[index % len(page_ids)]
        regions = by_page[page_id]
        fresh = [r for r in regions if r.id not in used]
        pool = fresh or regions
        chosen = random.sample(pool, min(data.labels_per_station, len(pool)))
        chosen.sort(key=lambda r: (r.y0, r.x0))
        used.update(r.id for r in chosen)
        plan.append((page_id, [r.id for r in chosen]))

    session = PracticeSession(
        user_id=user.id,
        station_count=len(plan),
        seconds_per_station=data.seconds_per_station,
        labels_per_station=data.labels_per_station,
        rest_every=data.rest_every,
        rest_seconds=data.rest_seconds,
    )
    db.add(session)
    db.flush()

    number = 0
    for index, (page_id, region_ids) in enumerate(plan, start=1):
        number += 1
        db.add(
            PracticeStation(
                session_id=session.id,
                number=number,
                kind="station",
                page_id=page_id,
                region_ids_json=json.dumps(region_ids),
            )
        )
        if data.rest_every and index % data.rest_every == 0 and index < len(plan):
            number += 1
            db.add(PracticeStation(session_id=session.id, number=number, kind="rest"))
    db.commit()
    db.refresh(session)
    return describe_session(session, utcnow())

@router.get("/readiness")
def readiness(
    source_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """What a student can practice right now, what is held back, and how processing is going."""
    query = (
        select(LabelRegion, PageRender)
        .join(PageRender, PageRender.id == LabelRegion.page_id)
        .where(PageRender.user_id == user.id, LabelRegion.status != "rejected")
    )
    if source_id is not None:
        query = query.where(PageRender.source_id == source_id)

    flagged = flagged_region_ids(db, user.id)
    stats: dict[int, dict] = {}
    for region, page in db.execute(query).all():
        if region.id in flagged:
            continue
        entry = stats.setdefault(page.source_id, {"pages": set(), "ready_pages": set(), "ready": 0, "held": 0})
        entry["pages"].add(page.id)
        if is_eligible(region):
            entry["ready"] += 1
            entry["ready_pages"].add(page.id)
        else:
            entry["held"] += 1

    latest_job: dict[int, ProcessingJob] = {}
    jobs = db.scalars(
        select(ProcessingJob).where(ProcessingJob.user_id == user.id).order_by(ProcessingJob.id.desc()).limit(200)
    ).all()
    for job in jobs:
        if source_id is not None and job.source_id != source_id:
            continue
        latest_job.setdefault(job.source_id, job)

    names = {s.id: s.filename for s in db.scalars(select(Source).where(Source.user_id == user.id)).all()}
    result = []
    for sid in sorted(set(stats) | set(latest_job)):
        entry = stats.get(sid, {"pages": set(), "ready_pages": set(), "ready": 0, "held": 0})
        job = latest_job.get(sid)
        result.append(
            {
                "source_id": sid,
                "filename": names.get(sid, "deleted source"),
                "pages_processed": len(entry["pages"]),
                "ready_labels": entry["ready"],
                "ready_pages": len(entry["ready_pages"]),
                "held_back_labels": entry["held"],
                "review_seconds_estimate": entry["held"] * REVIEW_SECONDS_PER_LABEL,
                "processing": job_summary(job) if job else None,
            }
        )
    return {
        "seconds_per_label": REVIEW_SECONDS_PER_LABEL, 
        "sources": result,
        "plan": plan_summary(user, db) # <--- Add this line
    }
    return {"seconds_per_label": REVIEW_SECONDS_PER_LABEL, "sources": result}

@router.get("/sessions")
def list_sessions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.scalars(
        select(PracticeSession)
        .where(PracticeSession.user_id == user.id)
        .order_by(PracticeSession.id.desc())
        .limit(50)
    ).all()
    return [
        {
            "id": s.id,
            "status": s.status,
            "station_count": s.station_count,
            "earned": s.earned,
            "possible": s.possible,
            "created_at": s.created_at.isoformat(),
        }
        for s in rows
    ]

@router.get("/sessions/{session_id}")
def session_detail(session_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return describe_session(own_session(db, session_id, user), utcnow())

@router.get("/sessions/{session_id}/stations/{number}")
def station_detail(
    session_id: int, number: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    session = own_session(db, session_id, user)
    station = get_station(db, session, number)
    now = utcnow()
    state = station_state(session, station, now)
    detail = {
        "number": station.number,
        "kind": station.kind,
        "state": state,
        "labels": len(region_ids_of(station)),
        "seconds_total": session.rest_seconds if station.kind == "rest" else session.seconds_per_station,
    }
    if state == "active":
        detail["seconds_left"] = max(0, round((deadline_of(session, station) - now).total_seconds()))
    return detail

@router.post("/sessions/{session_id}/stations/{number}/start")
def start_station(
    session_id: int, number: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    session = own_session(db, session_id, user)
    if session.status != "active":
        raise HTTPException(409, "This session is already finished")
    station = get_station(db, session, number)
    if station.kind == "rest":
        return {"kind": "rest", "seconds_total": session.rest_seconds}

    now = utcnow()
    state = station_state(session, station, now)
    if state in ("done", "expired"):
        raise HTTPException(409, "This station is already finished")
    blockers = [
        s for s in session.stations
        if s.number < number and s.kind == "station" and station_state(session, s, now) in ("pending", "active")
    ]
    if blockers:
        raise HTTPException(409, "Finish the earlier stations first")

    if station.started_at is None:
        station.started_at = now
        db.commit()
    left = max(0, round((deadline_of(session, station) - now).total_seconds()))
    return {
        "kind": "station",
        "labels": len(region_ids_of(station)),
        "seconds_total": session.seconds_per_station,
        "seconds_left": left,
    }

@router.get("/sessions/{session_id}/stations/{number}/image")
def station_image(
    session_id: int, number: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    session = own_session(db, session_id, user)
    station = get_station(db, session, number)
    if station.kind != "station":
        raise HTTPException(400, "This is a rest station")
    state = station_state(session, station, utcnow())
    if state == "pending":
        raise HTTPException(409, "Start the station first")
    if state != "active":
        raise HTTPException(403, "This station is closed")

    page = db.get(PageRender, station.page_id) if station.page_id else None
    if page is None:
        raise HTTPException(404, "The source page for this station no longer exists")
    ids = region_ids_of(station)
    by_id = load_regions(db, ids)
    regions = [by_id[i] for i in ids if i in by_id]
    payload = masked_image(page.file_path, regions, numbered=len(regions) > 1)
    return Response(content=payload, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

@router.post("/sessions/{session_id}/stations/{number}/answer")
def submit_answer(
    session_id: int,
    number: int,
    data: AnswerIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = own_session(db, session_id, user)
    if session.status != "active":
        raise HTTPException(409, "This session is already finished")
    station = get_station(db, session, number)
    if station.kind != "station":
        raise HTTPException(400, "This is a rest station")

    now = utcnow()
    state = station_state(session, station, now)
    if state == "done":
        raise HTTPException(409, "This station was already submitted")

    count = len(region_ids_of(station))
    answers = [(a or "").strip()[:200] for a in data.answers][:count]
    answers += [""] * (count - len(answers))

    accepted = True
    skipped = state == "pending"
    if skipped:
        accepted = False
        answers = [""] * count
    elif state == "expired":
        station.late = True
        accepted = False
        answers = [""] * count

    station.answers_json = json.dumps(answers)
    station.submitted_at = now
    db.commit()
    return {"accepted": accepted, "late": station.late, "skipped": skipped}

def flagged_region_ids(db: Session, user_id: int) -> set[int]:
    return set(db.scalars(select(LabelFlag.region_id).where(LabelFlag.user_id == user_id)).all())

def load_items(station: PracticeStation) -> list[dict]:
    try:
        value = json.loads(station.results_json or "[]")
        return value if isinstance(value, list) else []
    except ValueError:
        return []

def session_totals(session: PracticeSession, flagged: set[int]) -> tuple[float, int]:
    earned, possible = 0.0, 0
    for station in session.stations:
        if station.kind != "station":
            continue
        for item in load_items(station):
            if item.get("counted", True) and item["region_id"] not in flagged:
                earned += item["points"]
                possible += 1
    return earned, possible


def grade_session(db: Session, session: PracticeSession) -> None:
    vocab_cache: dict[int, set[str]] = {}
    for station in session.stations:
        if station.kind != "station":
            continue
        ids = region_ids_of(station)
        by_id = load_regions(db, ids)
        page = db.get(PageRender, station.page_id) if station.page_id else None
        
        vocabulary = set()
        if page is not None:
            if page.source_id not in vocab_cache:
                vocab_cache[page.source_id] = build_vocabulary(db, page.source_id)
            vocabulary = vocab_cache[page.source_id]
            
        try:
            answers = json.loads(station.answers_json or "[]")
        except ValueError:
            answers = []

        items = []
        for index, region_id in enumerate(ids):
            region = by_id.get(region_id)
            if region is None:
                continue
            student = answers[index] if index < len(answers) else ""
            
            # TRUST LOGIC
            supported = is_supported(region.text, vocabulary)
            trust = region_trust(region, supported)
            accepted = [region.text] + region.accepted_answers + accepted_variants(region.text, vocabulary)
            
            outcome = grade_answer(student, accepted)
            counted = True
            
            # If the label is medium trust and the student got it wrong, don't punish them!
            if outcome == "wrong" and trust == "medium":
                outcome = "unscored" 
                counted = False
                
            items.append(
                {
                    "number": index + 1,
                    "region_id": region_id,
                    "correct": region.text,
                    "also_accepted": region.accepted_answers,
                    "student": student,
                    "outcome": outcome,
                    "points": outcome_points(outcome),
                    "trust": trust,
                    "counted": counted,
                }
            )
        station.results_json = json.dumps(items)

    session.status = "finished"
    session.finished_at = utcnow()
    session.earned, session.possible = session_totals(session, flagged_region_ids(db, session.user_id))


@router.post("/sessions/{session_id}/finish")
def finish_session(session_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    session = own_session(db, session_id, user)
    if session.status != "finished":
        grade_session(db, session)
        db.commit()
    return {"id": session.id, "status": session.status, "earned": session.earned, "possible": session.possible}

@router.get("/sessions/{session_id}/results")
def session_results(session_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    session = own_session(db, session_id, user)
    if session.status != "finished":
        raise HTTPException(409, "Finish the session first")

    flagged = flagged_region_ids(db, user.id)
    stations = []
    total_earned, total_possible = 0.0, 0
    score_if_accepted, possible_if_accepted = 0.0, 0

    for station in session.stations:
        if station.kind != "station":
            continue
        page = db.get(PageRender, station.page_id) if station.page_id else None
        source = db.get(Source, page.source_id) if page else None
        shown = []
        
        for item in load_items(station):
            item = dict(item)
            if item["region_id"] in flagged:
                item["outcome"] = "flagged"
                item["counted"] = False
                possible_if_accepted += 1
                if item["points"] > 0: score_if_accepted += 1
            else:
                if item.get("counted", True):
                    total_earned += item["points"]
                    total_possible += 1
                possible_if_accepted += 1
                if item["points"] > 0: score_if_accepted += 1
            shown.append(item)

        # Calculate the station's specific score
        station_earned = sum(i["points"] for i in shown if i.get("counted", True))
        station_possible = sum(1 for i in shown if i.get("counted", True))

        stations.append({
            "number": station.number,
            "source": source.filename if source else None,
            "page_number": page.page_number if page else None,
            "items": shown,
            "earned": station_earned,
            "possible": station_possible,
            "reveal_url": f"/practice/sessions/{session.id}/stations/{station.number}/reveal",
        })

    percent = round(100 * total_earned / total_possible, 1) if total_possible else 0.0
    return {
        "id": session.id,
        "earned": total_earned,
        "possible": total_possible,
        "percent": percent,
        "score_if_reports_accepted": score_if_accepted,
        "possible_if_reports_accepted": possible_if_accepted,
        "stations": stations,
    }


@router.get("/sessions/{session_id}/stations/{number}/reveal")
def reveal_station(
    session_id: int, number: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    session = own_session(db, session_id, user)
    if session.status != "finished":
        raise HTTPException(409, "Answers are shown after the session is finished")
    station = get_station(db, session, number)
    page = db.get(PageRender, station.page_id) if station.page_id else None
    if station.kind != "station" or page is None:
        raise HTTPException(404, "Nothing to show for this station")

    try:
        items = json.loads(station.results_json or "[]")
    except ValueError:
        items = []
    by_id = load_regions(db, [i["region_id"] for i in items])

    img = Image.open(page.file_path).convert("RGB")
    width, height = img.size
    draw = ImageDraw.Draw(img)
    for item in items:
        region = by_id.get(item["region_id"])
        if region is None:
            continue
        color = (22, 163, 74) if item["outcome"] in ("exact", "close") else (220, 38, 38)
        box = (int(region.x0 * width), int(region.y0 * height), int(region.x1 * width), int(region.y1 * height))
        draw.rectangle(box, outline=color, width=4)
        tag = max(20, min(48, box[3] - box[1]))
        top = max(0, box[1] - tag)
        tag_box = (box[0], top, box[0] + tag, top + tag)
        draw.rectangle(tag_box, fill=color)
        draw_number(draw, tag_box, str(item["number"]))

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=88)
    return Response(content=buffer.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})

@router.post("/flags")
def flag_label(data: FlagIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    region = db.get(LabelRegion, data.region_id)
    if region is None or region.user_id != user.id:
        raise HTTPException(404, "Label not found")
        
    latest_session = db.scalar(select(PracticeSession).where(PracticeSession.user_id == user.id).order_by(PracticeSession.id.desc()))
    if latest_session:
        flag_count = db.scalar(select(func.count()).select_from(LabelFlag).where(LabelFlag.user_id == user.id, LabelFlag.session_id == latest_session.id))
        if flag_count >= 5:
            raise HTTPException(400, "You have reached the maximum of 5 reports for this session.")
            
    db.add(LabelFlag(
        user_id=user.id, 
        region_id=region.id, 
        reason=data.reason.strip(),
        session_id=latest_session.id if latest_session else None,
    ))
    db.commit()
    return {"flagged": region.id}