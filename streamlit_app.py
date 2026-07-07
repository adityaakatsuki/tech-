import sys
import streamlit as st
import pandas as pd
import altair as alt
import requests
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent / "company_tech_analysis"))
from company_tech_analysis.utils.scraper import scrape_and_detect
from database import init_db, SessionLocal, add_scraped_record, get_scraped_records, search_scraped_records

init_db()

st.set_page_config(page_title="Company Tech Usage Dashboard", layout="wide")
st.title("Company Technology Usage Dashboard")
st.markdown("Search for a company to scrape and view its technology profile. Every scrape is saved to History.")


def load_scraped_df() -> pd.DataFrame:
    db = SessionLocal()
    try:
        records = get_scraped_records(db, limit=1000)
    finally:
        db.close()
    return pd.DataFrame([{
        "URL": r.url,
        "Company Name": r.company_name,
        "Technologies": r.technologies,
        "Vendors": r.vendors,
        "Categories": r.categories,
        "Head Office": r.address,
        "Chars Scraped": r.chars_scraped,
        "Scraped At": r.scraped_at
    } for r in records])


def explode_counts(series: pd.Series) -> dict:
    counts = {}
    for val in series.dropna():
        for item in str(val).split(","):
            item = item.strip()
            if item:
                counts[item] = counts.get(item, 0) + 1
    return counts


def render_company_detail(record) -> None:
    st.subheader(record.company_name or record.url)
    st.caption(f"Scraped at {record.scraped_at} · {record.url}")
    col1, col2 = st.columns(2)
    with col1:
        st.write(f"**Company Name:** {record.company_name or 'N/A'}")
        st.write(f"**Head Office:** {record.address or 'N/A'}")
        st.write(f"**Emails:** {record.emails or 'N/A'}")
        st.write(f"**Phones:** {record.phones or 'N/A'}")
    with col2:
        st.write(f"**Technologies:** {record.technologies or 'N/A'}")
        st.write(f"**Vendors:** {record.vendors or 'N/A'}")
        st.write(f"**Categories:** {record.categories or 'N/A'}")
        st.write(f"**Chars Scraped:** {record.chars_scraped}")


tab_search, tab_history = st.tabs(["🔍 Search Company", "📜 History"])

with tab_search:
    st.markdown("Look up a company you've already scraped, or enter a URL to scrape a new one.")
    search_query = st.text_input("Company name or URL", value="", key="search_query")
    search_col, scrape_col = st.columns(2)
    do_search = search_col.button("Search history")
    do_scrape = scrape_col.button("Scrape new URL")

    if do_search:
        query = search_query.strip()
        if not query:
            st.warning("Enter a company name or URL to search.")
        else:
            db_session = SessionLocal()
            try:
                matches = search_scraped_records(db_session, query)
            finally:
                db_session.close()
            if not matches:
                st.info("No matching company found in history. Use 'Scrape new URL' to scrape it.")
            else:
                for record in matches:
                    with st.container(border=True):
                        render_company_detail(record)

    if do_scrape:
        query = search_query.strip()
        if not query:
            st.warning("Enter a URL to scrape.")
        else:
            with st.spinner(f"Scraping {query}..."):
                try:
                    result = scrape_and_detect(query)
                except requests.RequestException as e:
                    st.error(f"Failed to fetch: {e}")
                else:
                    contact = result["contact"]
                    db_session = SessionLocal()
                    try:
                        record = add_scraped_record(
                            db_session,
                            url=query,
                            technologies=result["technologies"],
                            vendors=result["vendors"],
                            categories=result["categories"],
                            chars_scraped=result["chars_scraped"],
                            company_name=contact["company_name"],
                            emails=contact["emails"],
                            phones=contact["phones"],
                            address=contact["address"]
                        )
                    finally:
                        db_session.close()
                    st.success(f"Scraped {result['chars_scraped']} characters - saved to History")
                    with st.container(border=True):
                        render_company_detail(record)

with tab_history:
    df = load_scraped_df()

    if df.empty:
        st.info("No companies scraped yet. Use the Search tab to scrape your first company.")
    else:
        tech_counts = explode_counts(df['Technologies'])
        vendor_counts = explode_counts(df['Vendors'])
        category_counts = explode_counts(df['Categories'])

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Companies Scraped", df['URL'].nunique())
        with c2:
            st.metric("Unique Technologies", len(tech_counts))
        with c3:
            st.metric("Unique Vendors", len(vendor_counts))
        with c4:
            top_category = max(category_counts, key=category_counts.get) if category_counts else "N/A"
            st.metric("Top Category", top_category)

        st.markdown("---")

        col_left, col_right = st.columns(2)
        with col_left:
            st.subheader("Most Common Technologies")
            if tech_counts:
                tech_df = pd.DataFrame(sorted(tech_counts.items(), key=lambda x: -x[1])[:20], columns=["Technology", "Companies"])
                chart = alt.Chart(tech_df).mark_bar().encode(
                    x=alt.X('Technology:N', sort='-y'),
                    y='Companies:Q',
                    tooltip=['Technology', 'Companies']
                ).properties(height=350)
                st.altair_chart(chart, use_container_width=True)
            else:
                st.caption("No technologies detected yet.")

        with col_right:
            st.subheader("Category Distribution")
            if category_counts:
                cat_df = pd.DataFrame(sorted(category_counts.items(), key=lambda x: -x[1]), columns=["Category", "Companies"])
                chart2 = alt.Chart(cat_df).mark_bar().encode(
                    x=alt.X('Category:N', sort='-y'),
                    y='Companies:Q',
                    tooltip=['Category', 'Companies']
                ).properties(height=350)
                st.altair_chart(chart2, use_container_width=True)
            else:
                st.caption("No categories detected yet.")

        st.markdown("---")
        st.subheader("Most Common Vendors")
        if vendor_counts:
            vendor_df = pd.DataFrame(sorted(vendor_counts.items(), key=lambda x: -x[1])[:20], columns=["Vendor", "Companies"])
            chart3 = alt.Chart(vendor_df).mark_bar().encode(
                x=alt.X('Vendor:N', sort='-y'),
                y='Companies:Q',
                tooltip=['Vendor', 'Companies']
            ).properties(height=300)
            st.altair_chart(chart3, use_container_width=True)
        else:
            st.caption("No vendors detected yet.")

        st.markdown("---")
        st.subheader("All Scraped Companies")
        st.dataframe(df, use_container_width=True)

        csv_bytes = df.to_csv(index=False).encode('utf-8')
        st.download_button("Download scraped data as CSV", csv_bytes, file_name="scraped_company_tech_data.csv", mime='text/csv')
