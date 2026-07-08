Run the Streamlit dashboard (Windows):

1. (Optional) Create and activate a Python virtual environment.
2. Install dependencies:
   pip install -r "E:\\scraping web\\requirements.txt"
3. Run the app:
   streamlit run "E:\\scraping web\\streamlit_app.py"

The app expects the cleaned CSV at:
E:\\scraping web\\company_tech_usage_sample_cleaned.csv

Use the sidebar filters to explore the dataset. The app provides KPI cards, charts, and a download button for the filtered subset.