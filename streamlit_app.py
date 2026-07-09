"""
Company Technology Usage Dashboard - Streamlit UI

Presentation layer only. All scraping, detection and persistence logic
lives in company_tech_analysis/utils/scraper.py and database.py and is
untouched here - this file only renders it as a modern SaaS-style
dashboard (sidebar nav, hero, search card, result cards, charts, history
cards, settings/about pages).
"""

import html
import re
import sys
import threading
import time
from pathlib import Path

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

import write_secrets
write_secrets.main()

sys.path.append(str(Path(__file__).resolve().parent / "company_tech_analysis"))
from company_tech_analysis.utils.scraper import scrape_and_detect, TECH_SIGNATURES, HEADER_SIGNATURES
from database import (
    init_db, SessionLocal, add_scraped_record, get_scraped_records,
    get_scraped_record_by_id, search_scraped_records, delete_scraped_record,
)
import auth_pages

init_db()

st.set_page_config(page_title="Company Tech Usage Dashboard", page_icon="📊", layout="wide")
auth_pages.init_auth_state()

# ============================================================
# Static presentation metadata (UI-only - does not touch scraper logic)
# ============================================================

TECH_ICONS = {
    "React": "⚛️", "Vue.js": "💚", "Angular": "🅰️", "jQuery": "💠", "Next.js": "▲",
    "Bootstrap": "🅱️", "Tailwind CSS": "🌊", "WordPress": "📝", "Shopify": "🛍️",
    "Wix": "🎨", "Squarespace": "⬛", "Drupal": "💧", "Joomla": "🧩", "Webflow": "🌐",
    "Google Analytics": "📈", "Google Tag Manager": "🏷️", "Hotjar": "🔥", "Segment": "🧭",
    "Mixpanel": "📊", "Cloudflare": "☁️", "Amazon CloudFront": "🚀", "jsDelivr": "📦",
    "Stripe": "💳", "PayPal": "💰", "Font Awesome": "🔤", "Google Fonts": "🔠",
    "HubSpot": "🎯", "Intercom": "💬", "Zendesk": "🎧", "reCAPTCHA": "🛡️",
    "Nginx": "🟢", "Apache": "🪶", "Microsoft-Iis": "🪟", "Vercel": "▲",
}
DEFAULT_ICON = "⚙️"

CATEGORY_DESCRIPTIONS = {
    "JavaScript Framework": "Framework used to build interactive, component-driven user interfaces.",
    "JavaScript Library": "Library that adds reusable client-side functionality to the page.",
    "CSS Framework": "Styling framework used to build consistent, responsive layouts quickly.",
    "CMS": "Content management system used to author and publish site content.",
    "Ecommerce": "Platform powering the online storefront and checkout flow.",
    "Website Builder": "Hosted website builder used to design and publish the site.",
    "Analytics": "Tool used to track visitor behaviour and site performance.",
    "Tag Manager": "Tag management system used to deploy marketing/analytics scripts.",
    "CDN": "Content delivery network used to serve assets quickly worldwide.",
    "Payment": "Payment processor used to handle transactions on the site.",
    "Font Script": "Hosted font or icon service used for typography/iconography.",
    "Marketing Automation": "Marketing platform used for lead capture and nurture campaigns.",
    "Live Chat": "Live chat / support widget used for customer communication.",
    "Security": "Security service used to protect forms and content from abuse.",
    "Web Server": "Web server software handling HTTP requests for the site.",
    "Hosting": "Hosting / infrastructure platform serving the website.",
}

# name -> (vendor, category) built read-only from the scraper's own signature
# tables, so tech cards can show accurate category/vendor without changing
# scraper.py or the way technologies/vendors/categories are stored.
TECH_META = {name: (vendor, category) for name, (vendor, category, _patterns) in TECH_SIGNATURES.items()}
for _key, (_vendor, _category) in HEADER_SIGNATURES.items():
    TECH_META[_key.title()] = (_vendor, _category)

AVATAR_PALETTE = ["#3B82F6", "#2563EB", "#10B981", "#F59E0B", "#8B5CF6", "#EC4899", "#14B8A6"]

URL_RE = re.compile(r"^(https?://)?([\w-]+\.)+[a-zA-Z]{2,}(:\d{1,5})?(/[^\s]*)?$")


# ============================================================
# CSS
# ============================================================

def load_css() -> None:
    css_path = Path(__file__).resolve().parent / "assets" / "style.css"
    st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


# ============================================================
# Small render helpers
# ============================================================

def badge(text: str, color: str = "gray") -> str:
    return f"<span class='badge badge-{color}'>{html.escape(str(text))}</span>"


def avatar(seed: str) -> str:
    seed = seed or "?"
    color = AVATAR_PALETTE[sum(ord(c) for c in seed) % len(AVATAR_PALETTE)]
    letter = seed.strip()[:1].upper() or "?"
    return (f"<div class='hc-logo' style='background:{color}22;color:{color};"
            f"font-weight:700;'>{html.escape(letter)}</div>")


def split_list(raw: str) -> list:
    return [item.strip() for item in str(raw or "").split(",") if item.strip()]


def format_dt(value) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, str):
        return value
    try:
        return value.strftime("%b %d, %Y · %H:%M")
    except AttributeError:
        return str(value)


# ============================================================
# Data access (thin wrappers over database.py - no logic changes)
# ============================================================

def load_scraped_df() -> pd.DataFrame:
    user = auth_pages.current_user()
    db = SessionLocal()
    try:
        records = get_scraped_records(db, user_id=user.id, limit=1000)
    finally:
        db.close()
    return pd.DataFrame([{
        "id": r.id,
        "URL": r.url,
        "Company Name": r.company_name,
        "Technologies": r.technologies,
        "Vendors": r.vendors,
        "Categories": r.categories,
        "Head Office": r.address,
        "Chars Scraped": r.chars_scraped,
        "Scraped At": r.scraped_at,
    } for r in records])


def explode_counts(series: pd.Series) -> dict:
    counts = {}
    for val in series.dropna():
        for item in str(val).split(","):
            item = item.strip()
            if item:
                counts[item] = counts.get(item, 0) + 1
    return counts


def compute_dashboard_stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "companies": 0, "technologies": 0, "last_scan": None,
            "success_rate": 0, "avg_tech": 0.0, "top_tech": "N/A",
        }
    tech_counts = explode_counts(df["Technologies"])
    per_company_tech = df["Technologies"].apply(lambda v: len(split_list(v)))
    success = (per_company_tech > 0).sum()
    return {
        "companies": df["URL"].nunique(),
        "technologies": len(tech_counts),
        "last_scan": df["Scraped At"].max(),
        "success_rate": round(success / len(df) * 100, 1) if len(df) else 0,
        "avg_tech": round(per_company_tech.mean(), 1) if len(df) else 0.0,
        "top_tech": max(tech_counts, key=tech_counts.get) if tech_counts else "N/A",
    }


# ============================================================
# Sidebar navigation
# ============================================================

NAV_PAGES = ["🏠 Dashboard", "🔍 Search Company", "📜 History", "⚙️ Settings", "ℹ️ About"]

def render_sidebar() -> str:
    with st.sidebar:
        st.markdown(
            "<div class='sidebar-brand'>"
            "<div class='logo-badge'>📊</div>"
            "<div class='brand-text'><div class='name'>TechScope</div>"
            "<div class='tag'>Company tech intelligence</div></div>"
            "</div>",
            unsafe_allow_html=True,
        )
        if "page" not in st.session_state:
            st.session_state.page = NAV_PAGES[0]
        choice = st.radio(
            "Navigation", NAV_PAGES,
            index=NAV_PAGES.index(st.session_state.page),
            label_visibility="collapsed", key="nav_radio",
        )
        st.session_state.page = choice
        st.markdown(
            "<div class='sidebar-footer-note'>Every scan is saved automatically "
            "to History. Data is stored locally in SQLite.</div>",
            unsafe_allow_html=True,
        )

        user = auth_pages.current_user()
        if user is not None:
            provider_badge = badge("Google", "blue") if getattr(user, "auth_provider", "local") == "google" else ""
            st.markdown("<div class='sidebar-divider'></div>", unsafe_allow_html=True)
            st.markdown(
                f"<div class='sidebar-user'>{avatar(user.full_name)}"
                f"<div><div class='hc-name'>{html.escape(user.full_name)} {provider_badge}</div>"
                f"<div class='hc-url'>{html.escape(user.email)}</div></div></div>",
                unsafe_allow_html=True,
            )
            if st.button("🚪 Logout", width="stretch"):
                auth_pages.logout_session()
                st.rerun()
    return choice


# ============================================================
# Shared components: company overview + tech cards + charts
# ============================================================

def _na(value) -> str:
    """Requirement: never show a missing field as blank - say so explicitly."""
    return str(value).strip() if value and str(value).strip() else "Not Available"


def render_social_buttons(record) -> None:
    platforms = [
        ("LinkedIn", "🔗", getattr(record, "linkedin_url", "")),
        ("Facebook", "📘", getattr(record, "facebook_url", "")),
        ("Twitter/X", "🐦", getattr(record, "twitter_url", "")),
        ("Instagram", "📸", getattr(record, "instagram_url", "")),
        ("YouTube", "▶️", getattr(record, "youtube_url", "")),
        ("GitHub", "🐙", getattr(record, "github_url", "")),
    ]
    links = [(label, icon, url) for label, icon, url in platforms if url]
    if not links:
        st.caption("No social media links found.")
        return
    cols = st.columns(len(links))
    for col, (label, icon, url) in zip(cols, links):
        with col:
            st.link_button(f"{icon} {label}", url, width="stretch")


def render_company_overview(record) -> None:
    status_badge = badge("✓ Success", "green") if split_list(record.technologies) else badge("No tech detected", "amber")

    logo_col, info_col = st.columns([1, 5])
    with logo_col:
        logo_url = getattr(record, "logo_url", "")
        if logo_url:
            try:
                st.image(logo_url, width=80)
            except Exception:
                st.markdown(avatar(record.company_name or record.url), unsafe_allow_html=True)
        else:
            st.markdown(avatar(record.company_name or record.url), unsafe_allow_html=True)
    with info_col:
        st.markdown(f"### {html.escape(_na(record.company_name))}")
        st.caption(record.url)

    headquarters = ", ".join(part for part in [
        getattr(record, "hq_street", ""), getattr(record, "hq_city", ""),
        getattr(record, "hq_state", ""), getattr(record, "hq_postal_code", ""),
        getattr(record, "hq_country", ""),
    ] if part) or record.address or "Not Available"

    items = [
        ("Website", record.url),
        ("Headquarters", headquarters),
        ("Phone", _na(getattr(record, "primary_phone", ""))),
        ("Email", _na(getattr(record, "primary_email", ""))),
        ("Status", None),
        ("Scan Time", format_dt(record.scraped_at)),
    ]
    hideable_labels = {"Website", "Headquarters", "Phone", "Email"}
    cells = []
    for label, value in items:
        if label == "Status":
            cells.append(f"<div class='overview-item'><div class='k'>{label}</div><div class='v'>{status_badge}</div></div>")
        elif label in hideable_labels and (not value or value == "Not Available"):
            continue
        else:
            cells.append(f"<div class='overview-item'><div class='k'>{label}</div><div class='v'>{html.escape(str(value))}</div></div>")
    st.markdown(
        f"<div class='app-card'><div class='section-title'>🏢 Company Overview</div>"
        f"<div class='overview-grid'>{''.join(cells)}</div></div>",
        unsafe_allow_html=True,
    )

    st.markdown("<div class='section-title'>🔗 Social Media</div>", unsafe_allow_html=True)
    render_social_buttons(record)


def render_tech_cards(technologies: list) -> None:
    if not technologies:
        st.info("No technologies were detected on this page.")
        return
    st.markdown("<div class='section-title'>🛠️ Technologies Detected</div>", unsafe_allow_html=True)
    cols = st.columns(3)
    for i, name in enumerate(technologies):
        vendor, category = TECH_META.get(name, ("Unknown vendor", "Other"))
        icon = TECH_ICONS.get(name, DEFAULT_ICON)
        desc = CATEGORY_DESCRIPTIONS.get(category, "Detected on this website.")
        with cols[i % 3]:
            st.markdown(
                f"<div class='tech-card'>"
                f"<div class='tech-head'><div class='tech-icon'>{icon}</div>"
                f"<div><div class='tech-name'>{html.escape(name)}</div>"
                f"{badge(category, 'blue')}</div></div>"
                f"{badge(vendor, 'violet')}"
                f"<div class='tech-desc'>{html.escape(desc)}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )


def render_scan_charts(technologies: list, categories: list) -> None:
    if not technologies:
        return
    st.markdown("<div class='section-title'>📈 Scan Breakdown</div>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        if categories:
            cat_counts = pd.Series(categories).value_counts().reset_index()
            cat_counts.columns = ["Category", "Count"]
            fig = px.pie(cat_counts, names="Category", values="Count", hole=0.55,
                         color_discrete_sequence=px.colors.sequential.Blues_r)
            fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=320,
                               paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                               font_color="#E2E8F0", legend=dict(orientation="h", y=-0.15))
            st.plotly_chart(fig, width="stretch")
    with c2:
        tech_df = pd.DataFrame({"Technology": technologies, "Detected": 1})
        fig2 = px.bar(tech_df, x="Detected", y="Technology", orientation="h",
                      color_discrete_sequence=["#3B82F6"])
        fig2.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=320,
                            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                            font_color="#E2E8F0", xaxis=dict(visible=False), yaxis_title=None)
        st.plotly_chart(fig2, width="stretch")


def render_full_result(record) -> None:
    render_company_overview(record)
    st.write("")
    render_tech_cards(split_list(record.technologies))
    render_scan_charts(split_list(record.technologies), split_list(record.categories))


# ============================================================
# Dashboard page
# ============================================================

def render_hero() -> None:
    st.markdown(
        "<div class='hero-wrap'>"
        "<div class='hero-emoji'>🧭</div>"
        "<div class='hero-title'>Company Technology Usage Dashboard</div>"
        "<div class='hero-subtitle'>Analyze websites and discover the technologies "
        "powering modern companies.</div>"
        "</div>",
        unsafe_allow_html=True,
    )


def render_dashboard() -> None:
    render_hero()
    df = load_scraped_df()
    stats = compute_dashboard_stats(df)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📦 Companies Scraped", stats["companies"])
    c2.metric("🛠️ Technologies Found", stats["technologies"])
    c3.metric("🕒 Last Scan", format_dt(stats["last_scan"]) if stats["last_scan"] is not None else "N/A")
    c4.metric("✅ Success Rate", f"{stats['success_rate']}%")

    st.markdown("<div class='section-title'>📌 Key Metrics</div>", unsafe_allow_html=True)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Companies", stats["companies"])
    m2.metric("Total Technologies", stats["technologies"])
    m3.metric("Avg. Tech / Company", stats["avg_tech"])
    m4.metric("Most Common Technology", stats["top_tech"])

    if df.empty:
        st.info("No companies scraped yet. Head to **Search Company** to run your first scan.")
        return

    st.markdown("<div class='section-title'>📅 Scan Timeline</div>", unsafe_allow_html=True)
    timeline = df.copy()
    timeline["Scraped At"] = pd.to_datetime(timeline["Scraped At"])
    timeline_counts = timeline.set_index("Scraped At").resample("D").size().reset_index(name="Scans")
    fig = px.area(timeline_counts, x="Scraped At", y="Scans", color_discrete_sequence=["#3B82F6"])
    fig.update_traces(line_color="#3B82F6", fillcolor="rgba(59,130,246,0.18)")
    fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=280,
                       paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#E2E8F0")
    st.plotly_chart(fig, width="stretch")

    st.markdown("<div class='section-title'>🕓 Recent Scans</div>", unsafe_allow_html=True)
    recent = df.sort_values("Scraped At", ascending=False).head(3)
    cols = st.columns(len(recent)) if len(recent) else []
    for col, (_, row) in zip(cols, recent.iterrows()):
        with col:
            st.markdown(
                f"<div class='history-card'><div class='hc-top'>{avatar(row['Company Name'] or row['URL'])}"
                f"<div><div class='hc-name'>{html.escape(row['Company Name'] or 'Unknown')}</div>"
                f"<div class='hc-url'>{html.escape(row['URL'])}</div></div></div>"
                f"<div class='hc-meta'>{format_dt(row['Scraped At'])} · "
                f"{len(split_list(row['Technologies']))} technologies</div></div>",
                unsafe_allow_html=True,
            )


# ============================================================
# Search Company page
# ============================================================

def run_scan_with_progress(url: str):
    """Runs scrape_and_detect on a worker thread while animating step labels
    on the main thread (only the main thread touches Streamlit APIs)."""
    result_holder = {}

    def worker():
        try:
            result_holder["result"] = scrape_and_detect(url)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user below
            result_holder["error"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    steps = ["Connecting", "Downloading page", "Detecting technologies"]
    placeholder = st.empty()
    i = 0
    while thread.is_alive():
        lines = []
        for idx, step in enumerate(steps):
            if idx < i % len(steps):
                lines.append(f"<div class='step-row done'><div class='step-icon'>✓</div>{step}</div>")
            elif idx == i % len(steps):
                lines.append(f"<div class='step-row active'><div class='step-icon'>●</div>{step}…</div>")
            else:
                lines.append(f"<div class='step-row pending'><div class='step-icon'>{idx+1}</div>{step}</div>")
        placeholder.markdown(f"<div class='app-card'>{''.join(lines)}</div>", unsafe_allow_html=True)
        time.sleep(0.5)
        i += 1
    thread.join()

    if "error" in result_holder:
        placeholder.empty()
        raise result_holder["error"]

    lines = [f"<div class='step-row done'><div class='step-icon'>✓</div>{step}</div>" for step in steps]
    lines.append("<div class='step-row active'><div class='step-icon'>●</div>Saving to database…</div>")
    placeholder.markdown(f"<div class='app-card'>{''.join(lines)}</div>", unsafe_allow_html=True)

    return result_holder["result"], placeholder, steps


def render_search() -> None:
    render_hero()
    st.markdown("<div class='search-card'><h3>🔍 Analyze a Company</h3>", unsafe_allow_html=True)
    mode = st.radio("Mode", ["🆕 Analyze new company", "🔎 Find in history"],
                     horizontal=True, label_visibility="collapsed", key="search_mode")
    query = st.text_input("Company website", placeholder="Enter company website (https://example.com)",
                           label_visibility="collapsed", key="search_query")
    action_label = "🚀 Analyze Company" if mode.startswith("🆕") else "🔎 Search History"
    go = st.button(action_label, type="primary", width="stretch")
    st.markdown("</div>", unsafe_allow_html=True)

    if not go:
        _maybe_render_last_result()
        return

    query = (query or "").strip()
    if not query:
        st.warning("Enter a company website or name first.")
        _maybe_render_last_result()
        return

    if mode.startswith("🆕"):
        if not URL_RE.match(query):
            st.error("That doesn't look like a valid website. Try something like `example.com` or `https://example.com`.")
            _maybe_render_last_result()
            return
        try:
            result, placeholder, steps = run_scan_with_progress(query)
        except requests.RequestException as e:
            st.error(f"Failed to fetch: {e}")
            _maybe_render_last_result()
            return

        info = result["company_info"]
        user = auth_pages.current_user()
        db_session = SessionLocal()
        try:
            record = add_scraped_record(
                db_session, url=query, user_id=user.id,
                technologies=result["technologies"], vendors=result["vendors"],
                categories=result["categories"], chars_scraped=result["chars_scraped"],
                company_name=info["company_name"], emails=info["emails"],
                phones=info["phones"], address=info["headquarters"]["full_address"],
                hq_street=info["headquarters"]["street"], hq_city=info["headquarters"]["city"],
                hq_state=info["headquarters"]["state"], hq_country=info["headquarters"]["country"],
                hq_postal_code=info["headquarters"]["postal_code"],
                primary_email=info["email"], primary_phone=info["phone"],
                contact_person=info["contact_person"], logo_url=info["logo_url"],
                linkedin_url=info["social"].get("linkedin", ""), facebook_url=info["social"].get("facebook", ""),
                twitter_url=info["social"].get("twitter", ""), instagram_url=info["social"].get("instagram", ""),
                youtube_url=info["social"].get("youtube", ""), github_url=info["social"].get("github", ""),
                meta_title=info["meta"].get("title", ""), meta_description=info["meta"].get("description", ""),
                meta_keywords=info["meta"].get("keywords", ""),
            )
        finally:
            db_session.close()

        done_lines = [f"<div class='step-row done'><div class='step-icon'>✓</div>{step}</div>" for step in steps]
        done_lines.append("<div class='step-row done'><div class='step-icon'>✓</div>Saving database</div>")
        placeholder.markdown(f"<div class='app-card'>{''.join(done_lines)}</div>", unsafe_allow_html=True)
        st.success(f"Scraped {result['chars_scraped']:,} characters · saved to History")
        st.session_state["last_scan_record"] = record
    else:
        user = auth_pages.current_user()
        db_session = SessionLocal()
        try:
            matches = search_scraped_records(db_session, query, user_id=user.id)
        finally:
            db_session.close()
        if not matches:
            st.info("No matching company found in history. Switch to **Analyze new company** to scan it.")
            st.session_state.pop("last_scan_record", None)
        else:
            st.session_state["last_scan_matches"] = matches
            st.session_state.pop("last_scan_record", None)

    _maybe_render_last_result()


def _maybe_render_last_result() -> None:
    record = st.session_state.get("last_scan_record")
    if record is not None:
        st.write("")
        render_full_result(record)
        return
    matches = st.session_state.get("last_scan_matches")
    if matches:
        st.write("")
        st.markdown(f"<div class='section-title'>Found {len(matches)} match(es)</div>", unsafe_allow_html=True)
        for m in matches:
            with st.container(border=True):
                render_full_result(m)


# ============================================================
# History page
# ============================================================

def render_history_card(row: pd.Series) -> None:
    company = row["Company Name"] or "Unknown company"
    tech_count = len(split_list(row["Technologies"]))
    record_id = int(row["id"])

    st.markdown(
        f"<div class='history-card'>"
        f"<div class='hc-top'>{avatar(company)}"
        f"<div><div class='hc-name'>{html.escape(company)}</div>"
        f"<div class='hc-url'>{html.escape(row['URL'])}</div></div></div>"
        f"<div class='hc-meta'>📅 {format_dt(row['Scraped At'])} &nbsp;·&nbsp; "
        f"🛠️ {tech_count} technologies</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
    user = auth_pages.current_user()
    b1, b2 = st.columns(2)
    view_key = f"view_{record_id}"
    if b1.button("👁️ View Details", key=f"btn_{view_key}", width="stretch"):
        st.session_state[view_key] = not st.session_state.get(view_key, False)
    if b2.button("🗑️ Delete", key=f"del_{record_id}", width="stretch"):
        db_session = SessionLocal()
        try:
            delete_scraped_record(db_session, record_id, user_id=user.id)
        finally:
            db_session.close()
        st.session_state.pop(view_key, None)
        st.rerun()

    if st.session_state.get(view_key):
        db_session = SessionLocal()
        try:
            record = get_scraped_record_by_id(db_session, record_id, user_id=user.id)
        finally:
            db_session.close()
        if record:
            render_full_result(record)


def render_history() -> None:
    st.markdown("<div class='hero-wrap'><div class='hero-emoji'>📜</div>"
                "<div class='hero-title' style='font-size:1.9rem;'>History</div>"
                "<div class='hero-subtitle'>Every company you've scanned, saved automatically.</div></div>",
                unsafe_allow_html=True)

    df = load_scraped_df()
    if df.empty:
        st.info("No companies scraped yet. Use **Search Company** to scrape your first one.")
        return

    tech_counts = explode_counts(df["Technologies"])
    vendor_counts = explode_counts(df["Vendors"])
    category_counts = explode_counts(df["Categories"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📦 Companies Scraped", df["URL"].nunique())
    c2.metric("🛠️ Unique Technologies", len(tech_counts))
    c3.metric("🏭 Unique Vendors", len(vendor_counts))
    c4.metric("🗂️ Top Category", max(category_counts, key=category_counts.get) if category_counts else "N/A")

    st.markdown("<div class='section-title'>🔎 Filter & Sort</div>", unsafe_allow_html=True)
    f1, f2, f3 = st.columns([2, 1, 1])
    search_text = f1.text_input("Search history", placeholder="Search by company name or URL",
                                 label_visibility="collapsed")
    sort_by = f2.selectbox("Sort", ["Newest first", "Oldest first", "Most technologies"], label_visibility="collapsed")
    category_filter = f3.multiselect("Filter by category", sorted(category_counts.keys()),
                                      label_visibility="collapsed", placeholder="Filter by category")

    filtered = df.copy()
    if search_text.strip():
        q = search_text.strip().lower()
        filtered = filtered[
            filtered["Company Name"].fillna("").str.lower().str.contains(q)
            | filtered["URL"].fillna("").str.lower().str.contains(q)
        ]
    if category_filter:
        filtered = filtered[filtered["Categories"].fillna("").apply(
            lambda v: any(cat in split_list(v) for cat in category_filter)
        )]

    filtered = filtered.assign(_tech_count=filtered["Technologies"].apply(lambda v: len(split_list(v))))
    if sort_by == "Newest first":
        filtered = filtered.sort_values("Scraped At", ascending=False)
    elif sort_by == "Oldest first":
        filtered = filtered.sort_values("Scraped At", ascending=True)
    else:
        filtered = filtered.sort_values("_tech_count", ascending=False)

    st.markdown(f"<div class='section-title'>🗂️ {len(filtered)} Company Records</div>", unsafe_allow_html=True)
    cards = list(filtered.iterrows())
    for row_start in range(0, len(cards), 2):
        cols = st.columns(2)
        for col, (_, row) in zip(cols, cards[row_start:row_start + 2]):
            with col:
                render_history_card(row)

    st.markdown("<div class='section-title'>📈 Category Distribution</div>", unsafe_allow_html=True)
    col_left, col_right = st.columns(2)
    with col_left:
        if category_counts:
            cat_df = pd.DataFrame(sorted(category_counts.items(), key=lambda x: -x[1]), columns=["Category", "Companies"])
            fig = px.pie(cat_df, names="Category", values="Companies", hole=0.55,
                         color_discrete_sequence=px.colors.sequential.Blues_r)
            fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=340,
                               paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                               font_color="#E2E8F0", legend=dict(orientation="h", y=-0.15))
            st.plotly_chart(fig, width="stretch")
        else:
            st.caption("No categories detected yet.")
    with col_right:
        if tech_counts:
            tech_df = pd.DataFrame(sorted(tech_counts.items(), key=lambda x: -x[1])[:15], columns=["Technology", "Companies"])
            fig2 = px.bar(tech_df, x="Companies", y="Technology", orientation="h",
                          color_discrete_sequence=["#3B82F6"])
            fig2.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=340,
                                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                                font_color="#E2E8F0", yaxis=dict(autorange="reversed"), yaxis_title=None)
            st.plotly_chart(fig2, width="stretch")
        else:
            st.caption("No technologies detected yet.")

    st.markdown("<div class='section-title'>📅 Scan Timeline</div>", unsafe_allow_html=True)
    timeline = df.copy()
    timeline["Scraped At"] = pd.to_datetime(timeline["Scraped At"])
    timeline_counts = timeline.set_index("Scraped At").resample("D").size().reset_index(name="Scans")
    fig3 = px.area(timeline_counts, x="Scraped At", y="Scans", color_discrete_sequence=["#10B981"])
    fig3.update_traces(line_color="#10B981", fillcolor="rgba(16,185,129,0.18)")
    fig3.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=260,
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#E2E8F0")
    st.plotly_chart(fig3, width="stretch")

    with st.expander("📋 View raw table & export"):
        st.dataframe(df.drop(columns=["id"]), width="stretch")
        csv_bytes = df.drop(columns=["id"]).to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download scraped data as CSV", csv_bytes,
                            file_name="scraped_company_tech_data.csv", mime="text/csv")


# ============================================================
# Settings & About pages
# ============================================================

def render_settings() -> None:
    st.markdown("<div class='hero-wrap'><div class='hero-emoji'>⚙️</div>"
                "<div class='hero-title' style='font-size:1.9rem;'>Settings</div>"
                "<div class='hero-subtitle'>App preferences and local data controls.</div></div>",
                unsafe_allow_html=True)

    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("#### Appearance")
    st.caption("This dashboard uses a fixed modern dark theme for readability and consistency.")
    st.color_picker("Primary color", "#3B82F6", disabled=True, label_visibility="visible")
    st.markdown("</div>", unsafe_allow_html=True)

    st.write("")
    st.markdown("<div class='app-card'>", unsafe_allow_html=True)
    st.markdown("#### Data")
    st.caption("Scraped data is stored locally in `company_tech.db` (SQLite).")
    if st.button("♻️ Clear cached results in this session"):
        st.session_state.pop("last_scan_record", None)
        st.session_state.pop("last_scan_matches", None)
        st.cache_data.clear()
        st.success("Session cache cleared.")
    st.markdown("</div>", unsafe_allow_html=True)


def render_about() -> None:
    st.markdown("<div class='hero-wrap'><div class='hero-emoji'>ℹ️</div>"
                "<div class='hero-title' style='font-size:1.9rem;'>About</div>"
                "<div class='hero-subtitle'>What this dashboard does and how it works.</div></div>",
                unsafe_allow_html=True)

    st.markdown(
        "<div class='app-card'>"
        "<p>The <strong>Company Technology Usage Dashboard</strong> scrapes a company's public "
        "website, inspects its HTML, headers and scripts for known technology signatures, and "
        "stores the results so you can build a history of technology adoption across the web.</p>"
        "<p>Every scan captures detected technologies, vendors, categories and any public contact "
        "details (company name, emails, phones, address) found on the page.</p>"
        "</div>",
        unsafe_allow_html=True,
    )


# ============================================================
# Footer
# ============================================================

def render_footer() -> None:
    st.markdown(
        "<div class='app-footer'>Built with ❤️ using"
        "<div class='stack-pills'>"
        + badge("Python", "blue") + badge("FastAPI", "green")
        + badge("BeautifulSoup", "amber") + badge("Streamlit", "red")
        + badge("SQLite", "violet")
        + "</div></div>",
        unsafe_allow_html=True,
    )


# ============================================================
# App entry point
# ============================================================

def main() -> None:
    load_css()

    if not auth_pages.is_authenticated():
        print(f"[debug] main: not authenticated - session auth_user="
              f"{st.session_state.get('auth_user')!r}, query_params={dict(st.query_params)}")
        auth_pages.render_auth_flow()
        return

    page = render_sidebar()

    if page == "🏠 Dashboard":
        render_dashboard()
    elif page == "🔍 Search Company":
        render_search()
    elif page == "📜 History":
        render_history()
    elif page == "⚙️ Settings":
        render_settings()
    elif page == "ℹ️ About":
        render_about()

    render_footer()


main()

