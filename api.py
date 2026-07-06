from fastapi import FastAPI, Depends, HTTPException, Header
from sqlalchemy.orm import Session
import secrets
from database import get_db, init_db, get_all_companies, filter_companies, get_stats, get_distinct_values, count_companies
from typing import Optional
import uvicorn

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

# ============ Endpoints ============

@app.get("/")
def root():
    return {
        "message": "Company Tech Usage API",
        "docs": "/docs",
        "redoc": "/redoc",
        "version": "1.0.0",
        "auth": "Pass X-API-Key header",
        "database": "PostgreSQL"

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

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
