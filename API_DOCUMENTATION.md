# Company Tech Usage API - SQLite Integration

## Overview
This API provides full REST access to company technology usage data stored in SQLite database with API key authentication.

## Quick Start

### 1. Run the API
```bash
cd "E:\scraping web"
python api.py
```
Server starts on: `http://localhost:8000`

### 2. API Documentation
- **Interactive Docs**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Authentication

All endpoints require an `X-API-Key` header.

**Demo API Keys:**
```
sk-demo-key-12345
sk-prod-key-67890
```

**Example Request:**
```bash
curl -X GET "http://localhost:8000/api/health" \
  -H "X-API-Key: sk-demo-key-12345"
```

## Database Schema

### Companies Table
```
id                 INTEGER  PRIMARY KEY
company_name       VARCHAR  (indexed)
industry           VARCHAR  (indexed)
country            VARCHAR  (indexed)
employee_count     INTEGER
number_of_developers INTEGER
primary_database   VARCHAR
frontend_framework VARCHAR
cloud_provider     VARCHAR  (indexed)
uses_kubernetes    VARCHAR
tech_spend_percent FLOAT
created_at         DATETIME
updated_at         DATETIME
```

**File:** `E:\scraping web\company_tech.db` (SQLite)

## API Endpoints

### Health Check
```
GET /api/health
```
Check if API and database are operational.

**Response:**
```json
{
  "status": "healthy",
  "database": "connected",
  "total_records": 200
}
```

---

### Get All Companies
```
GET /api/data?limit=100&offset=0
```

**Query Parameters:**
- `limit` (int): Records per page (default: 100)
- `offset` (int): Starting record (default: 0)

**Response:**
```json
{
  "total_records": 200,
  "limit": 100,
  "offset": 0,
  "returned": 100,
  "data": [
    {
      "id": 1,
      "company_name": "TechCorp",
      "industry": "SaaS",
      "country": "USA",
      "employee_count": 500,
      "number_of_developers": 150,
      "primary_database": "PostgreSQL",
      "frontend_framework": "React",
      "cloud_provider": "AWS",
      "uses_kubernetes": "Yes",
      "tech_spend_percent": 25.5
    }
  ]
}
```

---

### Filter Companies
```
GET /api/filtered?industries=SaaS,Finance&countries=USA,UK&uses_kubernetes=Yes&min_employees=100&max_employees=5000
```

**Query Parameters:**
- `industries` (string): Comma-separated values
- `countries` (string): Comma-separated values
- `cloud_providers` (string): Comma-separated values
- `uses_kubernetes` (string): "Yes" or "No"
- `min_employees` (int): Minimum employee count
- `max_employees` (int): Maximum employee count

**Example:**
```bash
curl -X GET "http://localhost:8000/api/filtered?industries=SaaS,Finance&countries=USA" \
  -H "X-API-Key: sk-demo-key-12345"
```

---

### Get Statistics
```
GET /api/stats?industries=SaaS&countries=USA
```

Same filter parameters as `/api/filtered`

**Response:**
```json
{
  "total_companies": 45,
  "avg_employees": 1250,
  "avg_developers": 175.3,
  "avg_tech_spend_percent": 29.5,
  "kubernetes_usage_count": 30,
  "kubernetes_usage_percent": 66.7
}
```

---

### Get Distinct Values
```
GET /api/industries
GET /api/countries
GET /api/cloud-providers
GET /api/databases
GET /api/frameworks
```

**Response:**
```json
{
  "industries": ["SaaS", "Finance", "Healthcare", ...]
}
```

---

### Get Specific Company
```
GET /api/company/{company_id}
```

**Example:**
```bash
curl -X GET "http://localhost:8000/api/company/1" \
  -H "X-API-Key: sk-demo-key-12345"
```

**Response:**
```json
{
  "id": 1,
  "company_name": "TechCorp",
  "industry": "SaaS",
  "country": "USA",
  "employee_count": 500,
  "number_of_developers": 150,
  "primary_database": "PostgreSQL",
  "frontend_framework": "React",
  "cloud_provider": "AWS",
  "uses_kubernetes": "Yes",
  "tech_spend_percent": 25.5,
  "created_at": "2024-01-15T10:00:00",
  "updated_at": "2024-01-15T10:00:00"
}
```

---

### Generate New API Key
```
POST /api/keys/generate
```

**Response:**
```json
{
  "api_key": "sk-a1b2c3d4e5f6g7h8i9j0",
  "message": "Store this key securely. You'll need it for all API requests."
}
```

## Usage Examples

### Example 1: Get Tech Spend Stats for SaaS Companies
```bash
curl -X GET "http://localhost:8000/api/stats?industries=SaaS" \
  -H "X-API-Key: sk-demo-key-12345"
```

### Example 2: Find AWS Users with Kubernetes
```bash
curl -X GET "http://localhost:8000/api/filtered?cloud_providers=AWS&uses_kubernetes=Yes" \
  -H "X-API-Key: sk-demo-key-12345"
```

### Example 3: Get Companies by Country and Size
```bash
curl -X GET "http://localhost:8000/api/filtered?countries=USA,UK&min_employees=1000&max_employees=5000" \
  -H "X-API-Key: sk-demo-key-12345"
```

## Files

| File | Purpose |
|------|---------|
| `api.py` | FastAPI application with all endpoints |
| `database.py` | SQLAlchemy models and database operations |
| `migrate.py` | CSV to SQLite migration script |
| `company_tech.db` | SQLite database file |
| `requirements.txt` | Python dependencies |

## Integration with Streamlit

The Streamlit dashboard (`streamlit_app.py`) can be modified to use this API instead of loading CSV directly:

```python
import requests

API_KEY = "sk-demo-key-12345"
API_URL = "http://localhost:8000"

@st.cache_data
def load_data_from_api():
    headers = {"X-API-Key": API_KEY}
    response = requests.get(f"{API_URL}/api/data?limit=1000", headers=headers)
    if response.status_code == 200:
        return pd.DataFrame(response.json()["data"])
    return None
```

## Performance Notes

- **Database**: SQLite is suitable for ~1000+ records
- **Pagination**: Use limit/offset for large datasets
- **Filtering**: Indexed columns (Industry, Country, Cloud Provider) are optimized
- **Response Time**: Typical queries complete in <100ms

## Future Enhancements

- [ ] Add POST endpoint to add new companies
- [ ] Add PUT/DELETE for updating/removing companies
- [ ] Add advanced filtering (date ranges, complex queries)
- [ ] Add CSV export endpoint
- [ ] Rate limiting and API key management UI
- [ ] Database backup automation
