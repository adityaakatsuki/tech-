import pandas as pd
from pathlib import Path
from database import init_db, SessionLocal, Company
import sys
import io

# Fix encoding for Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def migrate_csv_to_db():
    """Migrate CSV data to SQLite database"""
    CSV_PATH = Path(r"E:\scraping web\company_tech_usage_sample_cleaned.csv")
    
    if not CSV_PATH.exists():
        print(f"Error: CSV file not found at {CSV_PATH}")
        return False
    
    print(f"Loading CSV from {CSV_PATH}...")
    df = pd.read_csv(CSV_PATH, encoding='utf-8')
    
    # Standardize column names to snake_case
    df.columns = df.columns.str.lower().str.replace(' ', '_')
    
    # Initialize database
    init_db()
    
    db = SessionLocal()
    
    try:
        # Check if data already exists
        existing_count = db.query(Company).count()
        if existing_count > 0:
            print(f"Database already contains {existing_count} records. Clearing...")
            db.query(Company).delete()
            db.commit()
        
        print(f"Migrating {len(df)} records...")
        
        for idx, row in df.iterrows():
            try:
                company = Company(
                    company_name=str(row.get('companyname', 'N/A'))[:255],
                    industry=str(row.get('industry', 'N/A'))[:255],
                    country=str(row.get('country', 'N/A'))[:255],
                    employee_count=int(row.get('employeecount', 0)) if pd.notna(row.get('employeecount')) else 0,
                    number_of_developers=int(row.get('numberofdevelopers', 0)) if pd.notna(row.get('numberofdevelopers')) else 0,
                    primary_database=str(row.get('primarydatabase', 'N/A'))[:255],
                    frontend_framework=str(row.get('frontendframework', 'N/A'))[:255],
                    cloud_provider=str(row.get('cloudprovider', 'N/A'))[:255],
                    uses_kubernetes=str(row.get('useskubernetes', 'No'))[:10],
                    tech_spend_percent=float(row.get('techspendpercentnormalized', 0)) if pd.notna(row.get('techspendpercentnormalized')) else 0.0
                )
                db.add(company)
            except Exception as e:
                print(f"Warning: Error on row {idx}: {e}")
                continue
        
        db.commit()
        final_count = db.query(Company).count()
        print(f"✓ Migration complete! {final_count} records in database")
        return True
        
    except Exception as e:
        db.rollback()
        print(f"Error during migration: {e}")
        return False
    finally:
        db.close()

if __name__ == "__main__":
    migrate_csv_to_db()
