from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, Boolean
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime
import os

# Database setup
# DATABASE_URL = "sqlite:///E:/scraping web/company_tech.db"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///company_tech.db")

# Fix old PostgreSQL URLs if using one in the future
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql://",
        1
    )

# SQLite needs connect_args, PostgreSQL does not
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False}
    )
else:
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

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    auth_provider = Column(String, default="local")  # "local" or "google"

class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)
    token = Column(String, unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

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
    # Headquarters components (address kept above as the full-address string)
    hq_street = Column(String)
    hq_city = Column(String)
    hq_state = Column(String)
    hq_country = Column(String)
    hq_postal_code = Column(String)
    # Best single email/phone for quick display (emails/phones above hold the full lists)
    primary_email = Column(String)
    primary_phone = Column(String)
    contact_person = Column(String)
    logo_url = Column(String)
    linkedin_url = Column(String)
    facebook_url = Column(String)
    twitter_url = Column(String)
    instagram_url = Column(String)
    youtube_url = Column(String)
    github_url = Column(String)
    meta_title = Column(String)
    meta_description = Column(String)
    meta_keywords = Column(String)
    scraped_at = Column(DateTime, default=datetime.utcnow)

# Database initialization
def init_db():
    """Create all tables"""
    Base.metadata.create_all(bind=engine)
    _ensure_table_columns(ScrapedRecord)
    _ensure_table_columns(User)
    print("Database initialized successfully")

from sqlalchemy import inspect

def _ensure_table_columns(model) -> None:
    """
    Add any missing columns for the given model's table (e.g. when a new
    column is added to an existing model after the table was already
    created). Works with both SQLite and PostgreSQL.
    """
    table_name = model.__tablename__
    inspector = inspect(engine)

    # Table doesn't exist yet
    if table_name not in inspector.get_table_names():
        return

    existing_cols = {
        column["name"]
        for column in inspector.get_columns(table_name)
    }

    with engine.begin() as conn:
        for col in model.__table__.columns:
            if col.name not in existing_cols:
                col_type = col.type.compile(dialect=engine.dialect)
                conn.exec_driver_sql(
                    f'ALTER TABLE {table_name} ADD COLUMN "{col.name}" {col_type}'
                )

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
                        company_name: str = None, emails: list = None, phones: list = None, address: str = None,
                        hq_street: str = None, hq_city: str = None, hq_state: str = None,
                        hq_country: str = None, hq_postal_code: str = None,
                        primary_email: str = None, primary_phone: str = None, contact_person: str = None,
                        logo_url: str = None, linkedin_url: str = None, facebook_url: str = None,
                        twitter_url: str = None, instagram_url: str = None, youtube_url: str = None,
                        github_url: str = None, meta_title: str = None, meta_description: str = None,
                        meta_keywords: str = None) -> ScrapedRecord:
    """Store a scraper run's detected technologies/vendors/categories, plus
    the full company profile (contact details, headquarters, logo, social
    links, meta tags) found on the page, for a URL"""
    record = ScrapedRecord(
        url=url,
        technologies=",".join(technologies) if technologies else "",
        vendors=",".join(vendors) if vendors else "",
        categories=",".join(categories) if categories else "",
        chars_scraped=chars_scraped,
        company_name=company_name or "",
        emails=",".join(emails) if emails else "",
        phones=",".join(phones) if phones else "",
        address=address or "",
        hq_street=hq_street or "",
        hq_city=hq_city or "",
        hq_state=hq_state or "",
        hq_country=hq_country or "",
        hq_postal_code=hq_postal_code or "",
        primary_email=primary_email or "",
        primary_phone=primary_phone or "",
        contact_person=contact_person or "",
        logo_url=logo_url or "",
        linkedin_url=linkedin_url or "",
        facebook_url=facebook_url or "",
        twitter_url=twitter_url or "",
        instagram_url=instagram_url or "",
        youtube_url=youtube_url or "",
        github_url=github_url or "",
        meta_title=meta_title or "",
        meta_description=meta_description or "",
        meta_keywords=meta_keywords or "",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record

def get_scraped_records(db: Session, limit: int = 50, offset: int = 0):
    """Get most recent scraped records"""
    return db.query(ScrapedRecord).order_by(ScrapedRecord.scraped_at.desc()).offset(offset).limit(limit).all()

def get_scraped_record_by_id(db: Session, record_id: int):
    """Get a single scraped record by id"""
    return db.query(ScrapedRecord).filter(ScrapedRecord.id == record_id).first()

def count_scraped_records(db: Session):
    """Count total scraped records in database"""
    return db.query(ScrapedRecord).count()

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

def delete_scraped_record(db: Session, record_id: int) -> bool:
    """Delete a single scraped record by id. Returns True if a row was deleted."""
    record = db.query(ScrapedRecord).filter(ScrapedRecord.id == record_id).first()
    if record is None:
        return False
    db.delete(record)
    db.commit()
    return True


def delete_all_companies(db: Session):
    """Delete all companies (use carefully!)"""
    db.query(Company).delete()
    db.commit()
    return True


# ============ User / auth helpers ============

def get_user_by_email(db: Session, email: str):
    """Look up a user by email (case-insensitive)"""
    return db.query(User).filter(User.email.ilike(email.strip())).first()

def get_user_by_id(db: Session, user_id: int):
    return db.query(User).filter(User.id == user_id).first()

def create_user(db: Session, full_name: str, email: str, hashed_password: str, auth_provider: str = "local") -> User:
    user = User(
        full_name=full_name.strip(),
        email=email.strip().lower(),
        hashed_password=hashed_password,
        is_active=True,
        auth_provider=auth_provider,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

def update_last_login(db: Session, user: User) -> User:
    user.last_login = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user

def update_user_password(db: Session, user: User, hashed_password: str) -> User:
    user.hashed_password = hashed_password
    db.commit()
    db.refresh(user)
    return user


# ============ Password reset token helpers ============

def create_password_reset_token(db: Session, user_id: int, token: str, expires_at: datetime) -> PasswordResetToken:
    reset_token = PasswordResetToken(user_id=user_id, token=token, expires_at=expires_at, used=False)
    db.add(reset_token)
    db.commit()
    db.refresh(reset_token)
    return reset_token

def get_password_reset_token(db: Session, token: str):
    return db.query(PasswordResetToken).filter(PasswordResetToken.token == token).first()

def mark_reset_token_used(db: Session, reset_token: PasswordResetToken):
    reset_token.used = True
    db.commit()
