from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
import secrets
from database import (
    get_db, init_db, get_all_companies, filter_companies, get_stats, get_distinct_values, count_companies,
    get_scraped_records, get_scraped_record_by_id, count_scraped_records, add_scraped_record,
)
from sqlalchemy.orm import Session
from company_tech_analysis.utils.scraper import scrape_and_detect
from typing import Optional
import uvicorn
import auth

app = FastAPI(title="Company Tech Usage API", version="1.0.0")

# Initialize database on startup
@app.on_event("startup")
def startup_event():
    init_db()
    print("[OK] Database initialized")

# API Key management
VALID_API_KEYS = {
    "sk-demo-key-12345": "Demo Key",
    "sk-prod-key-67890": "Production Key"
}

# Generate a new API key
def generate_api_key():
    return f"sk-{secrets.token_hex(16)}"

# API Key verification
def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key not in VALID_API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key

# ============ User authentication (JWT) ============

bearer_scheme = HTTPBearer(auto_error=False)

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    """Dependency that validates the JWT bearer token and returns the User."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = auth.get_user_from_token(db, credentials.credentials)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="Account is deactivated")
    return user


class RegisterRequest(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    confirm_password: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    remember_me: bool = False

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str
    confirm_password: str

def _user_out(user) -> dict:
    return {
        "id": user.id,
        "full_name": user.full_name,
        "email": user.email,
        "created_at": user.created_at,
        "last_login": user.last_login,
        "is_active": user.is_active,
    }

@app.post("/api/auth/register")
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    """Create a new user account. Passwords are hashed with bcrypt."""
    try:
        user = auth.register_user(
            db, full_name=payload.full_name, email=payload.email,
            password=payload.password, confirm_password=payload.confirm_password,
        )
    except auth.AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": "Account created successfully", "user": _user_out(user)}

@app.post("/api/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate a user and return a JWT access token."""
    try:
        user = auth.authenticate_user(db, email=payload.email, password=payload.password)
    except auth.AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    token = auth.create_access_token(user, remember_me=payload.remember_me)
    return {"access_token": token, "token_type": "bearer", "user": _user_out(user)}

@app.get("/api/auth/me")
def read_current_user(current_user=Depends(get_current_user)):
    """Return the currently authenticated user (used to validate a stored token)."""
    return _user_out(current_user)

@app.post("/api/auth/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Request a password reset. Always returns a generic success message so
    existing emails cannot be enumerated. If SMTP is not configured, the
    reset token is printed to the server console (mock email)."""
    auth.request_password_reset(db, email=payload.email)
    return {"message": "If an account with that email exists, a password reset link has been sent."}

@app.post("/api/auth/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Reset a password using a valid, unused, unexpired reset token."""
    try:
        auth.reset_password(
            db, token=payload.token, new_password=payload.new_password,
            confirm_password=payload.confirm_password,
        )
    except auth.AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": "Password reset successfully. You can now log in."}

# ============ Endpoints ============

@app.get("/")
def root():
    return {
        "message": "Company Tech Usage API",
        "docs": "/docs",
        "redoc": "/redoc",
        "version": "1.0.0",
        "auth": "Pass X-API-Key header",
        "database": "SQLite"
    }

@app.post("/api/keys/generate")
def generate_key():
    """Generate a new API key (demo endpoint)"""
    new_key = generate_api_key()
    VALID_API_KEYS[new_key] = "Auto-generated key"
    return {
        "api_key": new_key,
        "message": "Store this key securely. You'll need it for all API requests."
    }

@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    """Check API health and database status"""
    try:
        total = count_companies(db)
        return {
            "status": "healthy",
            "database": "connected",
            "total_records": total
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "database": "error",
            "error": str(e)
        }

@app.get("/api/data")
def get_data(
    api_key: str = Depends(verify_api_key),
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """Get all company data with pagination"""
    companies = get_all_companies(db, limit=limit, offset=offset)
    return {
        "total_records": count_companies(db),
        "limit": limit,
        "offset": offset,
        "returned": len(companies),
        "data": [
            {
                "id": c.id,
                "company_name": c.company_name,
                "industry": c.industry,
                "country": c.country,
                "employee_count": c.employee_count,
                "number_of_developers": c.number_of_developers,
                "primary_database": c.primary_database,
                "frontend_framework": c.frontend_framework,
                "cloud_provider": c.cloud_provider,
                "uses_kubernetes": c.uses_kubernetes,
                "tech_spend_percent": c.tech_spend_percent
            }
            for c in companies
        ]
    }

@app.get("/api/filtered")
def get_filtered_data(
    api_key: str = Depends(verify_api_key),
    industries: Optional[str] = None,
    countries: Optional[str] = None,
    cloud_providers: Optional[str] = None,
    uses_kubernetes: Optional[str] = None,
    min_employees: Optional[int] = None,
    max_employees: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """Get filtered company data
    
    Query Parameters:
    - industries: Comma-separated list (e.g., "Technology,Finance")
    - countries: Comma-separated list (e.g., "USA,UK")
    - cloud_providers: Comma-separated list (e.g., "AWS,Azure")
    - uses_kubernetes: 'Yes' or 'No'
    - min_employees: Minimum employee count
    - max_employees: Maximum employee count
    """
    filters = {
        "industries": [x.strip() for x in industries.split(",")] if industries else None,
        "countries": [x.strip() for x in countries.split(",")] if countries else None,
        "cloud_providers": [x.strip() for x in cloud_providers.split(",")] if cloud_providers else None,
        "uses_kubernetes": uses_kubernetes,
        "min_employees": min_employees,
        "max_employees": max_employees
    }
    
    companies = filter_companies(db, **filters)
    
    return {
        "total_records": len(companies),
        "filters_applied": {
            "industries": industries,
            "countries": countries,
            "cloud_providers": cloud_providers,
            "uses_kubernetes": uses_kubernetes,
            "min_employees": min_employees,
            "max_employees": max_employees
        },
        "data": [
            {
                "id": c.id,
                "company_name": c.company_name,
                "industry": c.industry,
                "country": c.country,
                "employee_count": c.employee_count,
                "number_of_developers": c.number_of_developers,
                "primary_database": c.primary_database,
                "frontend_framework": c.frontend_framework,
                "cloud_provider": c.cloud_provider,
                "uses_kubernetes": c.uses_kubernetes,
                "tech_spend_percent": c.tech_spend_percent
            }
            for c in companies
        ]
    }

@app.get("/api/stats")
def get_api_stats(
    api_key: str = Depends(verify_api_key),
    industries: Optional[str] = None,
    countries: Optional[str] = None,
    cloud_providers: Optional[str] = None,
    uses_kubernetes: Optional[str] = None,
    min_employees: Optional[int] = None,
    max_employees: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """Get aggregated statistics with optional filters"""
    filters = {
        "industries": [x.strip() for x in industries.split(",")] if industries else None,
        "countries": [x.strip() for x in countries.split(",")] if countries else None,
        "cloud_providers": [x.strip() for x in cloud_providers.split(",")] if cloud_providers else None,
        "uses_kubernetes": uses_kubernetes,
        "min_employees": min_employees,
        "max_employees": max_employees
    }
    
    return get_stats(db, **filters)

@app.get("/api/industries")
def get_industries(api_key: str = Depends(verify_api_key), db: Session = Depends(get_db)):
    """Get list of all industries"""
    return {"industries": get_distinct_values(db, "industry")}

@app.get("/api/countries")
def get_countries(api_key: str = Depends(verify_api_key), db: Session = Depends(get_db)):
    """Get list of all countries"""
    return {"countries": get_distinct_values(db, "country")}

@app.get("/api/cloud-providers")
def get_cloud_providers(api_key: str = Depends(verify_api_key), db: Session = Depends(get_db)):
    """Get list of all cloud providers"""
    return {"cloud_providers": get_distinct_values(db, "cloud_provider")}

@app.get("/api/databases")
def get_databases(api_key: str = Depends(verify_api_key), db: Session = Depends(get_db)):
    """Get list of all primary databases"""
    return {"databases": get_distinct_values(db, "database")}

@app.get("/api/frameworks")
def get_frameworks(api_key: str = Depends(verify_api_key), db: Session = Depends(get_db)):
    """Get list of all frontend frameworks"""
    return {"frameworks": get_distinct_values(db, "framework")}

@app.get("/api/company/{company_id}")
def get_company(company_id: int, api_key: str = Depends(verify_api_key), db: Session = Depends(get_db)):
    """Get specific company by ID"""
    from database import get_company_by_id
    company = get_company_by_id(db, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return {
        "id": company.id,
        "company_name": company.company_name,
        "industry": company.industry,
        "country": company.country,
        "employee_count": company.employee_count,
        "number_of_developers": company.number_of_developers,
        "primary_database": company.primary_database,
        "frontend_framework": company.frontend_framework,
        "cloud_provider": company.cloud_provider,
        "uses_kubernetes": company.uses_kubernetes,
        "tech_spend_percent": company.tech_spend_percent,
        "created_at": company.created_at,
        "updated_at": company.updated_at
    }

# ============ Scraped company profiles ============

class ScrapeRequest(BaseModel):
    url: str

def _split_csv(raw: Optional[str]) -> list:
    return [item.strip() for item in (raw or "").split(",") if item.strip()]

def _na(value):
    """Requirement: never expose a missing field as None/empty - say so explicitly."""
    return value if value else "Not Available"

def _serialize_scraped_record(r) -> dict:
    return {
        "id": r.id,
        "url": r.url,
        "company_name": _na(r.company_name),
        "technologies": _split_csv(r.technologies),
        "vendors": _split_csv(r.vendors),
        "categories": _split_csv(r.categories),
        "chars_scraped": r.chars_scraped,
        "emails": _split_csv(r.emails),
        "phones": _split_csv(r.phones),
        "primary_email": _na(r.primary_email),
        "primary_phone": _na(r.primary_phone),
        "contact_person": _na(r.contact_person),
        "logo_url": _na(r.logo_url),
        "headquarters": {
            "street": _na(r.hq_street),
            "city": _na(r.hq_city),
            "state": _na(r.hq_state),
            "postal_code": _na(r.hq_postal_code),
            "country": _na(r.hq_country),
            "full_address": _na(r.address),
        },
        "social_media": {
            "linkedin": _na(r.linkedin_url),
            "facebook": _na(r.facebook_url),
            "twitter": _na(r.twitter_url),
            "instagram": _na(r.instagram_url),
            "youtube": _na(r.youtube_url),
            "github": _na(r.github_url),
        },
        "meta": {
            "title": _na(r.meta_title),
            "description": _na(r.meta_description),
            "keywords": _na(r.meta_keywords),
        },
        "scraped_at": r.scraped_at,
    }

def _store_scrape_result(db: Session, url: str, result: dict):
    info = result["company_info"]
    return add_scraped_record(
        db, url=url,
        technologies=result["technologies"], vendors=result["vendors"],
        categories=result["categories"], chars_scraped=result["chars_scraped"],
        company_name=info["company_name"], emails=info["emails"], phones=info["phones"],
        address=info["headquarters"]["full_address"],
        hq_street=info["headquarters"]["street"], hq_city=info["headquarters"]["city"],
        hq_state=info["headquarters"]["state"], hq_country=info["headquarters"]["country"],
        hq_postal_code=info["headquarters"]["postal_code"],
        primary_email=info["email"], primary_phone=info["phone"], contact_person=info["contact_person"],
        logo_url=info["logo_url"],
        linkedin_url=info["social"].get("linkedin", ""), facebook_url=info["social"].get("facebook", ""),
        twitter_url=info["social"].get("twitter", ""), instagram_url=info["social"].get("instagram", ""),
        youtube_url=info["social"].get("youtube", ""), github_url=info["social"].get("github", ""),
        meta_title=info["meta"].get("title", ""), meta_description=info["meta"].get("description", ""),
        meta_keywords=info["meta"].get("keywords", ""),
    )

@app.get("/api/scraped-records")
def get_scraped_records_endpoint(
    api_key: str = Depends(verify_api_key),
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """Get previously scraped company profiles (technologies + full contact/company info)"""
    records = get_scraped_records(db, limit=limit, offset=offset)
    return {
        "total_records": count_scraped_records(db),
        "limit": limit,
        "offset": offset,
        "returned": len(records),
        "data": [_serialize_scraped_record(r) for r in records],
    }

@app.get("/api/scraped-records/{record_id}")
def get_scraped_record_endpoint(record_id: int, api_key: str = Depends(verify_api_key), db: Session = Depends(get_db)):
    """Get a single scraped company profile by id"""
    record = get_scraped_record_by_id(db, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Scraped record not found")
    return _serialize_scraped_record(record)

@app.post("/api/scrape")
def scrape_company(payload: ScrapeRequest, api_key: str = Depends(verify_api_key), db: Session = Depends(get_db)):
    """Scrape a company website (homepage + contact/about/legal pages),
    detect technologies, store the full company profile and return it"""
    try:
        result = scrape_and_detect(payload.url)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to scrape site: {e}")

    record = _store_scrape_result(db, payload.url, result)
    return _serialize_scraped_record(record)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
