from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime
import os

# Database setup
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    # Railway (and some other providers) emit the legacy "postgres://" scheme;
    # SQLAlchemy 1.4+ requires "postgresql://"
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# Models
class Company(Base):
    __tablename__ = "companies"
    
    id = Column(Integer, primary_key=True, index=True)
    company_name = Column(String, index=True)
    industry = Column(String, index=True)
    country = Column(String, index=True)
    employee_count = Column(Integer)
    number_of_developers = Column(Integer)
    primary_database = Column(String)
    frontend_framework = Column(String)
    cloud_provider = Column(String, index=True)
    uses_kubernetes = Column(String)
    tech_spend_percent = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ScrapedRecord(Base):
    __tablename__ = "scraped_records"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, index=True)
    technologies = Column(String)
    vendors = Column(String)
    categories = Column(String)
    chars_scraped = Column(Integer)
    company_name = Column(String)
    emails = Column(String)
    phones = Column(String)
    address = Column(String)
    scraped_at = Column(DateTime, default=datetime.utcnow)

# Database initialization
def init_db():
    """Create all tables"""
    Base.metadata.create_all(bind=engine)
    print("Database initialized successfully")



def get_db():
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def add_company(db: Session, **kwargs) -> Company:
    """Add a single company record"""
    company = Company(**kwargs)
    db.add(company)
    db.commit()
    db.refresh(company)
    return company

def get_all_companies(db: Session, limit: int = 100, offset: int = 0):
    """Get all companies with pagination"""
    return db.query(Company).offset(offset).limit(limit).all()

def get_company_by_id(db: Session, company_id: int):
    """Get company by ID"""
    return db.query(Company).filter(Company.id == company_id).first()

def filter_companies(db: Session, **filters):
    """Filter companies with multiple conditions"""
    query = db.query(Company)
    
    if "industries" in filters and filters["industries"]:
        query = query.filter(Company.industry.in_(filters["industries"]))
    
    if "countries" in filters and filters["countries"]:
        query = query.filter(Company.country.in_(filters["countries"]))
    
    if "cloud_providers" in filters and filters["cloud_providers"]:
        query = query.filter(Company.cloud_provider.in_(filters["cloud_providers"]))
    
    if "uses_kubernetes" in filters and filters["uses_kubernetes"]:
        query = query.filter(Company.uses_kubernetes == filters["uses_kubernetes"])
    
    if "min_employees" in filters and filters["min_employees"] is not None:
        query = query.filter(Company.employee_count >= filters["min_employees"])
    
    if "max_employees" in filters and filters["max_employees"] is not None:
        query = query.filter(Company.employee_count <= filters["max_employees"])
    
    return query.all()

def get_stats(db: Session, **filters):
    """Get aggregated statistics"""
    query = db.query(Company)
    
    if "industries" in filters and filters["industries"]:
        
        query = query.filter(Company.industry.in_(filters["industries"]))
    
    if "countries" in filters and filters["countries"]:
        query = query.filter(Company.country.in_(filters["countries"]))
    
    if "cloud_providers" in filters and filters["cloud_providers"]:
        query = query.filter(Company.cloud_provider.in_(filters["cloud_providers"]))
    
    if "uses_kubernetes" in filters and filters["uses_kubernetes"]:
        query = query.filter(Company.uses_kubernetes == filters["uses_kubernetes"])
    
    if "min_employees" in filters and filters["min_employees"] is not None:
        query = query.filter(Company.employee_count >= filters["min_employees"])
    
    if "max_employees" in filters and filters["max_employees"] is not None:
        query = query.filter(Company.employee_count <= filters["max_employees"])
    
    companies = query.all()
    total = len(companies)
    
    if total == 0:
        return {
            "total_companies": 0,
            "avg_employees": 0,
            "avg_developers": 0,
            "avg_tech_spend_percent": 0,
            "kubernetes_usage_count": 0,
            "kubernetes_usage_percent": 0
        }
    
    avg_emp = sum(c.employee_count for c in companies if c.employee_count) / len([c for c in companies if c.employee_count])
    avg_dev = sum(c.number_of_developers for c in companies if c.number_of_developers) / len([c for c in companies if c.number_of_developers])
    avg_spend = sum(c.tech_spend_percent for c in companies if c.tech_spend_percent) / len([c for c in companies if c.tech_spend_percent])
    k8s_count = len([c for c in companies if c.uses_kubernetes == "Yes"])
    
    return {
        "total_companies": total,
        "avg_employees": int(avg_emp),
        "avg_developers": round(avg_dev, 1),
        "avg_tech_spend_percent": round(avg_spend, 2),
        "kubernetes_usage_count": k8s_count,
        "kubernetes_usage_percent": round((k8s_count / total * 100), 1) if total > 0 else 0
    }

def get_distinct_values(db: Session, column_name: str):
    """Get distinct values for a column"""
    if column_name == "industry":
        return sorted([v[0] for v in db.query(Company.industry).distinct().all() if v[0]])
    elif column_name == "country":
        return sorted([v[0] for v in db.query(Company.country).distinct().all() if v[0]])
    elif column_name == "cloud_provider":
        return sorted([v[0] for v in db.query(Company.cloud_provider).distinct().all() if v[0]])
    elif column_name == "database":
        return sorted([v[0] for v in db.query(Company.primary_database).distinct().all() if v[0]])
    elif column_name == "framework":
        return sorted([v[0] for v in db.query(Company.frontend_framework).distinct().all() if v[0]])
    return []

def count_companies(db: Session):
    """Count total companies in database"""
    return db.query(Company).count()

def add_scraped_record(db: Session, url: str, technologies: list, vendors: list, categories: list, chars_scraped: int,
                        company_name: str = None, emails: list = None, phones: list = None, address: str = None) -> ScrapedRecord:
    """Store a scraper run's detected technologies/vendors/categories, plus
    any client/company contact details found on the page, for a URL"""
    record = ScrapedRecord(
        url=url,
        technologies=",".join(technologies) if technologies else "",
        vendors=",".join(vendors) if vendors else "",
        categories=",".join(categories) if categories else "",
        chars_scraped=chars_scraped,
        company_name=company_name or "",
        emails=",".join(emails) if emails else "",
        phones=",".join(phones) if phones else "",
        address=address or ""
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record

def get_scraped_records(db: Session, limit: int = 50):
    """Get most recent scraped records"""
    return db.query(ScrapedRecord).order_by(ScrapedRecord.scraped_at.desc()).limit(limit).all()

def search_scraped_records(db: Session, query: str, limit: int = 20):
    """Find previously scraped records whose company name or URL contains query (case-insensitive)"""
    like_query = f"%{query}%"
    return (
        db.query(ScrapedRecord)
        .filter((ScrapedRecord.company_name.ilike(like_query)) | (ScrapedRecord.url.ilike(like_query)))
        .order_by(ScrapedRecord.scraped_at.desc())
        .limit(limit)
        .all()
    )

def delete_all_companies(db: Session):
    """Delete all companies (use carefully!)"""
    db.query(Company).delete()
    db.commit()
    return True
