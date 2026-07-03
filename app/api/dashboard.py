"""Dashboard-Routen mit Jinja2 + HTMX."""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select, func

import sys
sys.path.insert(0, "/mnt/agents/output/ausschreibungs-wecker-europa")

from app.api.auth import verify_credentials
from app.core.database import get_session_dependency
from app.models.models import Tender, CompanyProfile, Match

logger = logging.getLogger("app.api.dashboard")

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

# Alle EU + EWR + CH Länder
ALL_COUNTRIES = [
    ("AT", "🇦🇹 Österreich"), ("BE", "🇧🇪 Belgien"), ("BG", "🇧🇬 Bulgarien"),
    ("CH", "🇨🇭 Schweiz"), ("CY", "🇨🇾 Zypern"), ("CZ", "🇨🇿 Tschechien"),
    ("DE", "🇩🇪 Deutschland"), ("DK", "🇩🇰 Dänemark"), ("EE", "🇪🇪 Estland"),
    ("EL", "🇬🇷 Griechenland"), ("ES", "🇪🇸 Spanien"), ("FI", "🇫🇮 Finnland"),
    ("FR", "🇫🇷 Frankreich"), ("HR", "🇭🇷 Kroatien"), ("HU", "🇭🇺 Ungarn"),
    ("IE", "🇮🇪 Irland"), ("IS", "🇮🇸 Island"), ("IT", "🇮🇹 Italien"),
    ("LI", "🇱🇮 Liechtenstein"), ("LT", "🇱🇹 Litauen"), ("LU", "🇱🇺 Luxemburg"),
    ("LV", "🇱🇻 Lettland"), ("MT", "🇲🇹 Malta"), ("NL", "🇳🇱 Niederlande"),
    ("NO", "🇳🇴 Norwegen"), ("PL", "🇵🇱 Polen"), ("PT", "🇵🇹 Portugal"),
    ("RO", "🇷🇴 Rumänien"), ("SE", "🇸🇪 Schweden"), ("SI", "🇸🇮 Slowenien"),
    ("SK", "🇸🇰 Slowakei"),
]

ALL_LANGUAGES = [
    ("de", "Deutsch"), ("fr", "Französisch"), ("it", "Italienisch"),
    ("en", "Englisch"), ("es", "Spanisch"), ("nl", "Niederländisch"),
    ("pl", "Polnisch"), ("sv", "Schwedisch"), ("pt", "Portugiesisch"),
    ("da", "Dänisch"), ("fi", "Finnisch"), ("el", "Griechisch"),
    ("cs", "Tschechisch"), ("hu", "Ungarisch"), ("ro", "Rumänisch"),
    ("hr", "Kroatisch"), ("sk", "Slowakisch"), ("sl", "Slowenisch"),
    ("et", "Estnisch"), ("lv", "Lettisch"), ("lt", "Litauisch"),
    ("bg", "Bulgarisch"), ("ga", "Irisch"), ("mt", "Maltesisch"),
]


def get_db_counts(session: Session):
    tender_count = session.exec(select(func.count(Tender.id))).one()
    match_count = session.exec(select(func.count(Match.id))).one()
    new_match = session.exec(select(func.count(Match.id)).where(Match.status == "new")).one()
    notified = session.exec(select(func.count(Match.id)).where(Match.status == "notified")).one()
    saved = session.exec(select(func.count(Match.id)).where(Match.status == "saved")).one()
    return {"tenders": tender_count, "matches": match_count, "new": new_match, "notified": notified, "saved": saved}


@router.get("/", response_class=HTMLResponse)
async def dashboard_home(
    request: Request,
    status: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    session: Session = Depends(get_session_dependency),
    user: str = Depends(verify_credentials),
):
    query = select(Match, Tender, CompanyProfile).join(Tender, Match.tender_id == Tender.id).join(CompanyProfile, Match.profile_id == CompanyProfile.id)
    if status:
        query = query.where(Match.status == status)
    if country:
        query = query.where(Tender.country == country.upper())
    query = query.order_by(Match.score.desc())
    results = session.exec(query).all()

    matches_data = [{"match": m, "tender": t, "profile": p} for m, t, p in results]
    counts = get_db_counts(session)

    # Länder-Filter-Counts
    country_counts = session.exec(select(Tender.country, func.count(Tender.id)).group_by(Tender.country)).all()

    return templates.TemplateResponse("matches.html", {
        "request": request, "matches": matches_data, "counts": counts,
        "filter_status": status, "filter_country": country,
        "all_countries": ALL_COUNTRIES, "country_counts": dict(country_counts),
        "user": user,
    })


@router.post("/matches/{match_id}/status")
async def update_match_status(match_id: int, status: str = Form(...), session: Session = Depends(get_session_dependency), user: str = Depends(verify_credentials)):
    match = session.get(Match, match_id)
    if match:
        match.status = status
        session.add(match)
    return HTMLResponse(f'<span class="badge badge-{status}">{status}</span>')


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request, session: Session = Depends(get_session_dependency), user: str = Depends(verify_credentials)):
    profile = session.exec(select(CompanyProfile)).first()
    if not profile:
        profile = CompanyProfile(name="Meine Firma", description="Beschreibung der Kernleistungen...")
        session.add(profile)
        session.commit()
        session.refresh(profile)
    counts = get_db_counts(session)
    selected_countries = profile.get_countries()
    selected_languages = profile.get_languages_ok()
    return templates.TemplateResponse("profile.html", {
        "request": request, "profile": profile, "counts": counts,
        "all_countries": ALL_COUNTRIES, "all_languages": ALL_LANGUAGES,
        "selected_countries": selected_countries, "selected_languages": selected_languages,
        "user": user,
    })


@router.post("/profile")
async def update_profile(
    request: Request, name: str = Form(...), description: str = Form(...),
    keywords: str = Form(""), cpv_whitelist: str = Form(""),
    regions: str = Form(""), min_deadline_days: int = Form(7),
    countries: list[str] = Form([]), languages_ok: list[str] = Form([]),
    session: Session = Depends(get_session_dependency), user: str = Depends(verify_credentials),
):
    import json
    profile = session.exec(select(CompanyProfile)).first()
    if not profile:
        profile = CompanyProfile()
        session.add(profile)
    profile.name = name
    profile.description = description
    profile.keywords = keywords
    profile.cpv_whitelist = cpv_whitelist
    profile.regions = regions
    profile.min_deadline_days = min_deadline_days
    profile.countries = json.dumps(countries) if countries else "[]"
    profile.languages_ok = json.dumps(languages_ok) if languages_ok else '["de","en"]'
    session.add(profile)
    session.commit()
    return RedirectResponse(url="/profile", status_code=303)


@router.get("/tenders", response_class=HTMLResponse)
async def tenders_page(
    request: Request, q: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    session: Session = Depends(get_session_dependency), user: str = Depends(verify_credentials),
):
    query = select(Tender).order_by(Tender.created_at.desc())
    if q:
        query = query.where((Tender.title.contains(q)) | (Tender.description.contains(q)) | (Tender.buyer.contains(q)))
    if country:
        query = query.where(Tender.country == country.upper())
    tenders = session.exec(query.limit(100)).all()
    counts = get_db_counts(session)
    return templates.TemplateResponse("tenders.html", {
        "request": request, "tenders": tenders, "counts": counts,
        "search_query": q, "filter_country": country, "all_countries": ALL_COUNTRIES, "user": user,
    })


@router.get("/health", response_class=HTMLResponse)
async def health_page(request: Request, session: Session = Depends(get_session_dependency), user: str = Depends(verify_credentials)):
    counts = get_db_counts(session)
    source_stats = session.exec(select(Tender.source, func.count(Tender.id)).group_by(Tender.source)).all()
    country_stats = session.exec(select(Tender.country, func.count(Tender.id)).group_by(Tender.country)).all()
    return templates.TemplateResponse("health.html", {
        "request": request, "counts": counts, "source_stats": source_stats,
        "country_stats": country_stats, "user": user,
    })
