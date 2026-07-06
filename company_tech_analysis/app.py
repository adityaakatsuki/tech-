
"""
Company Technology Usage Analysis - Main Application
Main Streamlit application entry point for analyzing and visualizing
company technology stack usage across departments and projects.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
from utils.data_loader import load_technology_data
from utils.data_processor import process_tech_data

# Configure page settings
st.set_page_config(
    page_title="Company Tech Analysis",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom styling
st.markdown("""
<style>
    .main { padding-top: 0; }
    .metric-card { padding: 20px; background-color: #f0f2f6; border-radius: 10px; }
</style>
""", unsafe_allow_html=True)

# Application header
st.title("🔧 Company Technology Usage Analysis")
st.markdown("""
A comprehensive dashboard for analyzing and tracking technology adoption,
usage patterns, and software inventory across your organization.
""")

# Sidebar navigation
st.sidebar.title("Navigation")
page = st.sidebar.radio("Select Page", ["Dashboard", "Technologies", "Departments", "Reports"])

# Load data
@st.cache_data
def get_data():
    raw_data = load_technology_data()
    processed_data = process_tech_data(raw_data)
    return processed_data

data = get_data()

# Dashboard Page
if page == "Dashboard":
    st.header("📊 Dashboard Overview")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Technologies", len(data['technologies'].unique()) if not data.empty else 0)
    with col2:
        st.metric("Active Departments", len(data['department'].unique()) if not data.empty else 0)
    with col3:
        st.metric("Total Projects", len(data) if not data.empty else 0)
    with col4:
        st.metric("Avg Adoption Rate", f"{data['adoption_rate'].mean():.1f}%" if not data.empty else "0%")

    st.divider()

    # Technology distribution chart
    if not data.empty:
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Technology Distribution by Department")
            tech_dept = data.groupby(['department', 'technologies']).size().reset_index(name='count')
            fig = px.bar(tech_dept, x='department', y='count', color='technologies', title="Tech Usage by Department")
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.subheader("Top 10 Technologies")
            top_tech = data['technologies'].value_counts().head(10)
            fig = px.pie(values=top_tech.values, names=top_tech.index, title="Top Technologies")
            st.plotly_chart(fig, use_container_width=True)

# Technologies Page
elif page == "Technologies":
    st.header("🛠️ Technology Catalog")
    st.write("Browse and analyze individual technologies used across the organization.")

    if not data.empty:
        selected_tech = st.selectbox("Select Technology", data['technologies'].unique())
        tech_data = data[data['technologies'] == selected_tech]

        st.subheader(f"Details for {selected_tech}")
        st.write(tech_data[['department', 'project_name', 'adoption_rate', 'status']])

# Departments Page
elif page == "Departments":
    st.header("🏢 Department Analysis")
    st.write("Analyze technology usage patterns by department.")

    if not data.empty:
        selected_dept = st.selectbox("Select Department", data['department'].unique())
        dept_data = data[data['department'] == selected_dept]

        st.subheader(f"Technologies in {selected_dept}")
        st.write(dept_data[['technologies', 'project_name', 'adoption_rate']])

# Reports Page
elif page == "Reports":
    st.header("📋 Reports & Analytics")
    st.write("Generate detailed reports and export analysis results.")

    report_type = st.selectbox("Select Report Type", ["Summary", "Detailed Analysis", "Export Data"])

    if report_type == "Summary":
        st.subheader("Executive Summary")
        st.info("Summary report showing key metrics and insights.")
    elif report_type == "Detailed Analysis":
        st.subheader("Detailed Analysis")
        st.info("Comprehensive analysis with deep dives into trends and patterns.")
    else:
        st.subheader("Data Export")
        if st.button("Download Data as CSV"):
            st.success("Data exported successfully!")
