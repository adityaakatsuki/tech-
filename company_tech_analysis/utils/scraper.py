"""
Company technology-detection and profile scraper.

Crawls a company's homepage plus a handful of relevant sub-pages
(/contact, /about, /legal, ...), inspects the combined HTML/headers for
known technology signatures, and extracts a full company profile: contact
details, headquarters/address, logo, social links, meta tags and
schema.org/JSON-LD structured data. Not exhaustive - a small, maintainable
signature list rather than a full Wappalyzer port.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import phonenumbers
import requests
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
REQUEST_TIMEOUT = 10

# --- Crawl configuration (requirement: "smarter crawling", capped + polite) ---
MAX_PAGES = 10          # homepage + up to 9 sub-pages, hard cap
MAX_WORKERS = 5         # sub-pages are fetched concurrently over one shared session
CRAWL_PATHS = [
    "/contact", "/contact-us", "/about", "/about-us", "/company",
    "/imprint", "/legal", "/privacy",
]
# Links on the homepage whose href/text mention these are crawled preferentially
# over the guessed CRAWL_PATHS, since real nav links are more reliable than guesses.
LINK_KEYWORDS = ["contact", "about", "company", "imprint", "legal", "privacy", "impressum", "team"]

# name -> (vendor, category, [substrings to look for in html/headers, case-insensitive])
TECH_SIGNATURES = {
    "React": ("Meta", "JavaScript Framework", ["react.production.min.js", "react-dom", "data-reactroot", "__react"]),
    "Vue.js": ("Vue.js", "JavaScript Framework", ["vue.js", "vue.min.js", "__vue__", "data-v-"]),
    "Angular": ("Google", "JavaScript Framework", ["ng-version", "angular.js", "angular.min.js"]),
    "jQuery": ("OpenJS Foundation", "JavaScript Library", ["jquery.js", "jquery.min.js", "jquery-"]),
    "Next.js": ("Vercel", "JavaScript Framework", ["/_next/static", "__next_data__"]),
    "Bootstrap": ("Bootstrap", "CSS Framework", ["bootstrap.min.css", "bootstrap.css", "bootstrap.min.js"]),
    "Tailwind CSS": ("Tailwind Labs", "CSS Framework", ["tailwind.css", "tailwindcss"]),
    "WordPress": ("Automattic", "CMS", ["wp-content", "wp-includes", "generator\" content=\"wordpress"]),
    "Shopify": ("Shopify", "Ecommerce", ["cdn.shopify.com", "shopify.com/s/", "myshopify.com"]),
    "Wix": ("Wix", "Website Builder", ["wix.com", "static.wixstatic.com"]),
    "Squarespace": ("Squarespace", "Website Builder", ["squarespace.com", "static1.squarespace.com"]),
    "Drupal": ("Drupal Association", "CMS", ["drupal.js", "sites/all/", "generator\" content=\"drupal"]),
    "Joomla": ("Open Source Matters", "CMS", ["generator\" content=\"joomla"]),
    "Webflow": ("Webflow", "Website Builder", ["webflow.js", "assets-global.website-files.com"]),
    "Google Analytics": ("Google", "Analytics", ["google-analytics.com/analytics.js", "googletagmanager.com/gtag/js", "ga('create'"]),
    "Google Tag Manager": ("Google", "Tag Manager", ["googletagmanager.com/gtm.js"]),
    "Hotjar": ("Hotjar", "Analytics", ["static.hotjar.com", "hotjar.com"]),
    "Segment": ("Twilio", "Analytics", ["cdn.segment.com"]),
    "Mixpanel": ("Mixpanel", "Analytics", ["cdn.mxpnl.com"]),
    "Cloudflare": ("Cloudflare", "CDN", ["cdnjs.cloudflare.com", "__cf_bm", "cloudflare"]),
    "Amazon CloudFront": ("Amazon", "CDN", ["cloudfront.net"]),
    "jsDelivr": ("jsDelivr", "CDN", ["cdn.jsdelivr.net"]),
    "Stripe": ("Stripe", "Payment", ["js.stripe.com", "stripe.com/v3"]),
    "PayPal": ("PayPal", "Payment", ["paypal.com/sdk", "paypalobjects.com"]),
    "Font Awesome": ("Fonticons", "Font Script", ["font-awesome", "fontawesome.com"]),
    "Google Fonts": ("Google", "Font Script", ["fonts.googleapis.com", "fonts.gstatic.com"]),
    "HubSpot": ("HubSpot", "Marketing Automation", ["js.hs-scripts.com", "hsforms.net"]),
    "Intercom": ("Intercom", "Live Chat", ["widget.intercom.io"]),
    "Zendesk": ("Zendesk", "Live Chat", ["zdassets.com", "zendesk.com"]),
    "reCAPTCHA": ("Google", "Security", ["google.com/recaptcha", "grecaptcha"]),
}

HEADER_SIGNATURES = {
    "nginx": ("F5, Inc.", "Web Server"),
    "apache": ("Apache Software Foundation", "Web Server"),
    "cloudflare": ("Cloudflare", "CDN"),
    "microsoft-iis": ("Microsoft", "Web Server"),
    "vercel": ("Vercel", "Hosting"),
}

# --- Contact-detail regexes ---
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
# Requires a space/dash/parenthesis separator between digit groups, so minified
# JS/CSS numbers like "00.000001" (dot-only) never match.
PHONE_RE = re.compile(r"(?:\+\d{1,3}[\s\-]?)?\(?\d{2,4}\)?[\s\-]\d{3,4}[\s\-]?\d{0,4}")
ADDRESS_RE = re.compile(
    # Deliberately excludes ambiguous plain-English words like "way"/"dr" (matches ordinary
    # prose, e.g. "...in a way that...") and forbids crossing a sentence boundary (". ") in
    # the gap before the suffix, to keep this heuristic from firing on unrelated body text.
    r"\d{1,5}\s+(?:(?!\.\s)[A-Za-z0-9,#.\-\s]){3,40}\b(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Highway|Hwy|Suite|Ste)\b[A-Za-z0-9,.\-\s]{0,40}",
    re.IGNORECASE,
)
POSTAL_CODE_RE = re.compile(r"\b\d{4,7}(?:-\d{4})?\b")
CONTACT_PERSON_RE = re.compile(
    r"(?:Contact(?:\s+Person)?|Attn|Attention)\s*[:\-]\s*([A-Z][a-zA-Z.'-]+(?:\s+[A-Z][a-zA-Z.'-]+){1,3})"
)

# --- Email data-quality blocklists (requirement: ignore placeholder addresses) ---
PLACEHOLDER_EMAIL_LOCAL_PARTS = {
    "test", "example", "sample", "demo", "user", "email",
    "admin", "postmaster", "webmaster",
}
PLACEHOLDER_EMAIL_PREFIXES = ("noreply", "no-reply", "donotreply", "do-not-reply")
PLACEHOLDER_EMAIL_DOMAINS = {
    "example.com", "example.org", "example.net", "test.com", "domain.com",
    "yourdomain.com", "email.com", "company.com", "site.com", "sentry.io",
}
# Extensions that make EMAIL_RE false-positive on asset URLs like "logo@2x.png"
NON_EMAIL_DOMAIN_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "css", "js",
    "woff", "woff2", "ttf", "eot", "pdf", "json", "xml",
}

# --- Social platforms (requirement: official links only, no share links) ---
SOCIAL_DOMAINS = {
    "linkedin": ["linkedin.com"],
    "facebook": ["facebook.com", "fb.com"],
    "twitter": ["twitter.com", "x.com"],
    "instagram": ["instagram.com"],
    "youtube": ["youtube.com", "youtu.be"],
    "github": ["github.com"],
}
SHARE_URL_MARKERS = [
    "sharer", "share.php", "share?", "/sharer/", "intent/tweet", "share-",
    "sharearticle", "whatsapp.com/send", "/plugins/", "/dialog/",
]
# Subdomains that carry a social domain's name but are never the company's own
# profile (support docs, help centers, blogs, etc.) - excluded from social matching.
BLOCKED_SOCIAL_SUBDOMAIN_PREFIXES = ("support.", "help.", "docs.", "status.", "developer.", "developers.", "blog.")

COUNTRY_NAME_TO_ISO2 = {
    "united states": "US", "usa": "US", "u.s.a.": "US", "united states of america": "US",
    "united kingdom": "GB", "uk": "GB", "great britain": "GB",
    "india": "IN", "canada": "CA", "australia": "AU", "germany": "DE", "france": "FR",
    "spain": "ES", "italy": "IT", "netherlands": "NL", "ireland": "IE", "singapore": "SG",
    "japan": "JP", "china": "CN", "brazil": "BR", "mexico": "MX", "south africa": "ZA",
    "united arab emirates": "AE", "uae": "AE", "new zealand": "NZ", "sweden": "SE",
    "switzerland": "CH", "poland": "PL", "russia": "RU", "south korea": "KR",
    "hong kong": "HK", "philippines": "PH", "indonesia": "ID", "malaysia": "MY",
    "pakistan": "PK", "bangladesh": "BD", "nigeria": "NG", "kenya": "KE", "egypt": "EG",
    "israel": "IL", "turkey": "TR", "portugal": "PT", "belgium": "BE", "austria": "AT",
    "denmark": "DK", "norway": "NO", "finland": "FI", "greece": "GR", "argentina": "AR",
    "chile": "CL", "colombia": "CO", "vietnam": "VN", "thailand": "TH",
}


def _normalize_url(url: str) -> str:
    url = url.strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = f"https://{url}"
    return url


# ============================================================
# Technology detection (unchanged behaviour, now runs over every
# crawled page's HTML instead of just the homepage)
# ============================================================

def _detect_technologies(html: str, headers: dict) -> tuple[list, list, list]:
    haystack = html.lower()
    technologies, vendors, categories = [], [], []

    for name, (vendor, category, patterns) in TECH_SIGNATURES.items():
        if any(pattern.lower() in haystack for pattern in patterns):
            technologies.append(name)
            vendors.append(vendor)
            categories.append(category)

    server_header = (headers.get("Server") or "").lower()
    powered_by = (headers.get("X-Powered-By") or "").lower()
    for key, (vendor, category) in HEADER_SIGNATURES.items():
        if key in server_header or key in powered_by:
            if key.title() not in technologies:
                technologies.append(key.title())
                vendors.append(vendor)
                categories.append(category)

    return technologies, sorted(set(vendors)), sorted(set(categories))


# ============================================================
# Crawling: robots.txt, fetching, page discovery
# ============================================================

def _get_robot_parser(session: requests.Session, base_url: str) -> RobotFileParser:
    """Fetch and parse robots.txt for the target site. Any failure (missing
    file, network error) is treated as "allow everything" - the same default
    RobotFileParser uses when it has no rules."""
    parsed = urlparse(base_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = RobotFileParser()
    rp.set_url(robots_url)
    try:
        resp = session.get(robots_url, timeout=REQUEST_TIMEOUT)
        rp.parse(resp.text.splitlines() if resp.status_code < 400 else [])
    except requests.RequestException:
        rp.parse([])
    return rp


def _is_allowed(rp: RobotFileParser, url: str) -> bool:
    try:
        return rp.can_fetch(USER_AGENT, url)
    except Exception:
        return True


def _fix_encoding(resp: requests.Response) -> None:
    """requests falls back to ISO-8859-1 when a text/* response has no
    charset in its Content-Type header, which mangles UTF-8 pages (e.g. an
    em dash in a <title>). Prefer the content-sniffed encoding in that case."""
    if resp.encoding is None or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding


def _fetch_homepage(session: requests.Session, base_url: str) -> dict:
    """Fetch the homepage. Failures propagate - an unreachable homepage is a
    real error the caller (Streamlit/API) should surface, unlike optional
    sub-pages which fail silently."""
    resp = session.get(base_url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    _fix_encoding(resp)
    return {"url": base_url, "html": resp.text, "headers": resp.headers}


def _fetch_page(session: requests.Session, url: str):
    """Fetch an optional sub-page. Returns None on any failure so a single
    missing /legal or /imprint page never breaks the whole scan."""
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code >= 400:
            return None
        _fix_encoding(resp)
        return {"url": url, "html": resp.text, "headers": resp.headers}
    except requests.RequestException:
        return None


def _discover_crawl_targets(base_url: str, homepage_soup: BeautifulSoup) -> list:
    """Build the list of sub-pages to crawl: real nav/footer links matching
    LINK_KEYWORDS (preferred, since they're known to exist) followed by the
    guessed CRAWL_PATHS as a fallback, deduplicated and capped."""
    parsed_base = urlparse(base_url)
    root = f"{parsed_base.scheme}://{parsed_base.netloc}"

    discovered = []
    for a in homepage_soup.find_all("a", href=True):
        href = a["href"]
        label = (a.get_text() or "").strip().lower()
        haystack = f"{href} {label}".lower()
        if any(keyword in haystack for keyword in LINK_KEYWORDS):
            full = urljoin(base_url, href)
            if full.startswith(("http://", "https://")) and urlparse(full).netloc == parsed_base.netloc:
                discovered.append(full)

    guessed = [root + path for path in CRAWL_PATHS]

    seen = {base_url.rstrip("/")}
    unique = []
    for link in discovered + guessed:
        clean = link.split("#")[0].rstrip("/")
        if clean not in seen:
            seen.add(clean)
            unique.append(link)

    return unique[: MAX_PAGES - 1]  # -1 reserves a slot for the homepage


def _crawl_site(session: requests.Session, base_url: str) -> list:
    """Fetch the homepage plus up to MAX_PAGES-1 relevant sub-pages,
    respecting robots.txt, fetching sub-pages concurrently over one
    reused session."""
    homepage = _fetch_homepage(session, base_url)
    pages = [homepage]

    homepage_soup = BeautifulSoup(homepage["html"], "html.parser")
    targets = _discover_crawl_targets(base_url, homepage_soup)

    robots = _get_robot_parser(session, base_url)
    allowed_targets = [t for t in targets if _is_allowed(robots, t)]

    if allowed_targets:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = [pool.submit(_fetch_page, session, target) for target in allowed_targets]
            for future in as_completed(futures):
                page = future.result()
                if page is not None:
                    pages.append(page)

    return pages[:MAX_PAGES]


# ============================================================
# JSON-LD / schema.org structured data
# ============================================================

def _extract_json_ld_organizations(soup: BeautifulSoup) -> list:
    """Parse <script type="application/ld+json"> blocks and return every
    Organization-like schema.org node found on the page."""
    orgs = []
    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.string or tag.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue

        nodes = data if isinstance(data, list) else [data]
        expanded = []
        for node in nodes:
            if isinstance(node, dict) and isinstance(node.get("@graph"), list):
                expanded.extend(node["@graph"])
            else:
                expanded.append(node)

        for node in expanded:
            if not isinstance(node, dict):
                continue
            node_type = node.get("@type", "")
            types = node_type if isinstance(node_type, list) else [node_type]
            if any(str(t).lower() in ("organization", "corporation", "localbusiness", "ngo") for t in types):
                orgs.append(node)
    return orgs


def _flatten_jsonld_org(org: dict) -> dict:
    """Pull the fields we care about (address, contactPoint, telephone,
    email, sameAs, logo, founder) out of a raw Organization JSON-LD node."""
    address = org.get("address")
    if isinstance(address, list):
        address = address[0] if address else None
    address = address if isinstance(address, dict) else {}

    country = address.get("addressCountry") or ""
    if isinstance(country, dict):
        country = country.get("name") or ""

    contact_point = org.get("contactPoint")
    if isinstance(contact_point, list):
        contact_point = contact_point[0] if contact_point else None
    contact_point = contact_point if isinstance(contact_point, dict) else {}

    same_as = org.get("sameAs") or []
    if isinstance(same_as, str):
        same_as = [same_as]

    logo = org.get("logo")
    if isinstance(logo, dict):
        logo = logo.get("url")

    founder = org.get("founder")
    if isinstance(founder, list):
        founder = founder[0] if founder else None
    if isinstance(founder, dict):
        founder = founder.get("name")

    return {
        "name": org.get("name") or "",
        "logo": logo or "",
        "telephone": org.get("telephone") or contact_point.get("telephone") or "",
        "email": org.get("email") or contact_point.get("email") or "",
        "street": address.get("streetAddress") or "",
        "city": address.get("addressLocality") or "",
        "state": address.get("addressRegion") or "",
        "postal_code": address.get("postalCode") or "",
        "country": country,
        "same_as": [s for s in same_as if isinstance(s, str)],
        "founder": founder or "",
    }


# ============================================================
# Meta tags, logo, social links
# ============================================================

def _extract_meta_tags(soup: BeautifulSoup) -> dict:
    def content(**attrs):
        tag = soup.find("meta", attrs=attrs)
        return tag.get("content", "").strip() if tag else ""

    return {
        "title": soup.title.get_text().strip() if soup.title else "",
        "description": content(name="description") or content(property="og:description"),
        "keywords": content(name="keywords"),
        "og_title": content(property="og:title"),
        "og_description": content(property="og:description"),
        "og_image": content(property="og:image"),
        "og_site_name": content(property="og:site_name"),
        "twitter_card": content(name="twitter:card"),
        "twitter_title": content(name="twitter:title"),
    }


def _extract_logo_url(soup: BeautifulSoup, page_url: str) -> str:
    """Best-effort logo lookup: OpenGraph image, then a header/logo-classed
    <img>, then the site favicon."""
    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        return urljoin(page_url, og_image["content"])

    logo_el = soup.select_one(
        "img[class*=logo], img[id*=logo], a[class*=logo] img, "
        "header img[class*=brand], .logo img, #logo img, header img"
    )
    if logo_el and logo_el.get("src"):
        return urljoin(page_url, logo_el["src"])

    for link in soup.find_all("link", rel=True):
        rel_values = [str(r).lower() for r in link.get("rel", [])]
        if any("icon" in r for r in rel_values) and link.get("href"):
            return urljoin(page_url, link["href"])

    return urljoin(page_url, "/favicon.ico")


def _netloc_matches_domain(netloc: str, domain: str) -> bool:
    """True only for the domain itself or a genuine subdomain of it - never
    a substring match, so "firefox.com" never matches domain "x.com"."""
    netloc = netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc == domain or netloc.endswith(f".{domain}")


def _path_depth(url: str) -> int:
    return len([p for p in urlparse(url).path.split("/") if p])


def _extract_social_links(soup: BeautifulSoup) -> dict:
    """Find official social profile links, skipping share/like/embed widgets
    and non-profile subdomains (support., help., docs., ...). When a page
    links the same platform multiple times, keep the shallowest path (e.g.
    github.com/mozilla over a deep link into a specific repo file) - it's
    the most likely candidate for the company's actual profile page."""
    candidates = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        low = href.lower()
        if any(marker in low for marker in SHARE_URL_MARKERS):
            continue
        netloc = urlparse(href).netloc.lower()
        if not netloc or netloc.startswith(BLOCKED_SOCIAL_SUBDOMAIN_PREFIXES):
            continue
        for platform, domains in SOCIAL_DOMAINS.items():
            if any(_netloc_matches_domain(netloc, domain) for domain in domains):
                if platform == "twitter" and ("/intent/" in low or "/share" in low):
                    continue
                candidates.setdefault(platform, []).append(href)

    return {platform: min(links, key=_path_depth) for platform, links in candidates.items()}


# ============================================================
# Headquarters / address detection
# ============================================================

def _extract_microdata_address(soup: BeautifulSoup):
    """schema.org microdata (itemprop=streetAddress/addressLocality/...)."""
    scope = soup.find(attrs={"itemtype": re.compile(r"PostalAddress", re.IGNORECASE)}) or soup

    def prop(name):
        tag = scope.find(attrs={"itemprop": name})
        return tag.get_text(strip=True) if tag else ""

    components = {
        "street": prop("streetAddress"), "city": prop("addressLocality"),
        "state": prop("addressRegion"), "postal_code": prop("postalCode"),
        "country": prop("addressCountry"),
    }
    return components if any(components.values()) else None


def _extract_maps_embed_address(soup: BeautifulSoup):
    """Google Maps iframe embeds often carry the address in the query string."""
    iframe = soup.find("iframe", src=re.compile(r"google\.[a-z.]+/maps", re.IGNORECASE))
    if not iframe or not iframe.get("src"):
        return None
    query = parse_qs(urlparse(iframe["src"]).query)
    for key in ("q", "daddr", "address"):
        if query.get(key):
            return query[key][0]
    return None


def _extract_address_from_text(text: str):
    match = ADDRESS_RE.search(text)
    return match.group(0).strip() if match else None


def _parse_address_components(full_address: str) -> dict:
    """Best-effort split of a free-text address into street/city/state/postal
    /country. Free-text addresses have no fixed grammar, so this is a
    heuristic (comma-position based), not an exact parser."""
    if not full_address:
        return {"street": "", "city": "", "state": "", "postal_code": "", "country": ""}
    parts = [p.strip() for p in full_address.split(",") if p.strip()]
    postal_match = POSTAL_CODE_RE.search(full_address)
    return {
        "street": parts[0] if len(parts) > 0 else "",
        "city": parts[1] if len(parts) > 1 else "",
        "state": parts[2] if len(parts) > 2 else "",
        "postal_code": postal_match.group(0) if postal_match else "",
        "country": parts[-1] if len(parts) > 3 else "",
    }


def _country_to_iso2(name: str):
    if not name:
        return None
    name = name.strip()
    if len(name) == 2 and name.isalpha():
        return name.upper()
    return COUNTRY_NAME_TO_ISO2.get(name.lower())


# ============================================================
# Email / phone / contact-person extraction and validation
# ============================================================

def _is_valid_company_email(email: str) -> bool:
    """Reject placeholder/example addresses and asset-URL false positives
    (e.g. "logo@2x.png" matching the email regex)."""
    email = email.strip().strip("\"'<>.,;:")
    if not EMAIL_RE.fullmatch(email):
        return False
    local, _, domain = email.rpartition("@")
    local_l, domain_l = local.lower(), domain.lower()
    extension = domain_l.rsplit(".", 1)[-1]

    if extension in NON_EMAIL_DOMAIN_EXTENSIONS:
        return False
    if local_l in PLACEHOLDER_EMAIL_LOCAL_PARTS:
        return False
    if local_l.startswith(PLACEHOLDER_EMAIL_PREFIXES):
        return False
    if domain_l in PLACEHOLDER_EMAIL_DOMAINS:
        return False
    return True


def _extract_emails_from_page(soup: BeautifulSoup, visible_text: str) -> set:
    mailto = {
        a["href"].split("mailto:", 1)[1].split("?")[0].strip()
        for a in soup.select('a[href^="mailto:"]') if a.get("href")
    }
    # Inline <script> blocks (JSON config, analytics snippets, etc.) are the
    # closest we get to "JS-rendered" content without running a real browser.
    script_text = " ".join(tag.get_text() for tag in soup.find_all("script"))
    candidates = mailto | set(EMAIL_RE.findall(visible_text)) | set(EMAIL_RE.findall(script_text))
    return {e for e in candidates if _is_valid_company_email(e)}


def _looks_like_placeholder_phone(digits: str) -> bool:
    return len(set(digits)) <= 1 or digits in {"1234567890", "0123456789", "1234567"}


def _normalize_phone(raw: str, region_hint):
    """Normalize + validate a phone number via `phonenumbers`, trying the
    detected headquarters country first, then a few common defaults, since
    many local-format numbers (e.g. "(022) 24567890") omit the country code."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 7 or len(digits) > 15 or _looks_like_placeholder_phone(digits):
        return None

    for region in [region_hint, None, "US", "GB", "IN"]:
        try:
            parsed = phonenumbers.parse(raw, region)
        except phonenumbers.NumberParseException:
            continue
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    return None


def _extract_phones_from_page(soup: BeautifulSoup, visible_text: str) -> set:
    tel = {
        a["href"].split("tel:", 1)[1].strip()
        for a in soup.select('a[href^="tel:"]') if a.get("href")
    }
    footer = soup.find("footer")
    footer_text = footer.get_text(separator=" ") if footer else ""
    candidates = tel | set(PHONE_RE.findall(visible_text)) | set(PHONE_RE.findall(footer_text))
    return {c.strip() for c in candidates if c and c.strip()}


def _extract_contact_person(visible_text: str, jsonld_orgs: list) -> str:
    for org in jsonld_orgs:
        founder = _flatten_jsonld_org(org)["founder"]
        if founder:
            return founder
    match = CONTACT_PERSON_RE.search(visible_text)
    return match.group(1).strip() if match else ""


# ============================================================
# Per-page extraction + cross-page aggregation
# ============================================================

def _extract_page_data(page: dict) -> dict:
    """Run every extractor over a single fetched page. Aggregation/priority
    across pages happens afterwards in `_merge_pages`."""
    url, html = page["url"], page["html"]
    soup = BeautifulSoup(html, "html.parser")

    visible_soup = BeautifulSoup(html, "html.parser")
    for tag in visible_soup(["script", "style"]):
        tag.decompose()
    visible_text = visible_soup.get_text(separator=" ")

    jsonld_orgs = _extract_json_ld_organizations(soup)

    return {
        "url": url,
        "jsonld": [_flatten_jsonld_org(o) for o in jsonld_orgs],
        "meta": _extract_meta_tags(soup),
        "logo": _extract_logo_url(soup, url),
        "social": _extract_social_links(soup),
        "microdata_address": _extract_microdata_address(soup),
        "maps_address": _extract_maps_embed_address(soup),
        "text_address": _extract_address_from_text(visible_text),
        "emails": _extract_emails_from_page(soup, visible_text),
        "phones": _extract_phones_from_page(soup, visible_text),
        "contact_person": _extract_contact_person(visible_text, jsonld_orgs),
    }


def _merge_pages(pages_extracted: list) -> dict:
    """Combine per-page extractions into one company profile. Pages are in
    crawl order (homepage first); for singular fields we take the first
    non-empty value found, with JSON-LD > microdata > page text > maps embed
    for addresses (requirement 10's homepage -> contact -> about fallback)."""
    all_emails, all_phones, social = set(), set(), {}
    company_name, logo_url, meta, contact_person = "", "", {}, ""
    address_candidates = []  # (priority, component-dict) - lower priority wins

    for page in pages_extracted:
        all_emails |= page["emails"]
        all_phones |= page["phones"]

        for platform, link in page["social"].items():
            social.setdefault(platform, link)

        if not logo_url and page["logo"]:
            logo_url = page["logo"]
        if not meta and any(page["meta"].values()):
            meta = page["meta"]
        if not contact_person and page["contact_person"]:
            contact_person = page["contact_person"]

        for org in page["jsonld"]:
            if not company_name and org["name"]:
                company_name = org["name"]
            if org["telephone"]:
                all_phones.add(org["telephone"])
            if org["email"] and _is_valid_company_email(org["email"]):
                all_emails.add(org["email"])
            if org["logo"] and not logo_url:
                logo_url = org["logo"]
            for same_as in org["same_as"]:
                netloc = urlparse(same_as).netloc.lower()
                for platform, domains in SOCIAL_DOMAINS.items():
                    if platform not in social and any(_netloc_matches_domain(netloc, d) for d in domains):
                        social[platform] = same_as
            if any([org["street"], org["city"], org["state"], org["postal_code"], org["country"]]):
                address_candidates.append((0, {k: org[k] for k in ("street", "city", "state", "postal_code", "country")}))

        if page["microdata_address"]:
            address_candidates.append((1, page["microdata_address"]))
        if page["text_address"]:
            address_candidates.append((2, _parse_address_components(page["text_address"])))
        elif page["maps_address"]:
            address_candidates.append((3, _parse_address_components(page["maps_address"])))

    address_candidates.sort(key=lambda c: c[0])
    headquarters = address_candidates[0][1] if address_candidates else {
        "street": "", "city": "", "state": "", "postal_code": "", "country": ""
    }
    full_address = ", ".join(p for p in (
        headquarters["street"], headquarters["city"], headquarters["state"],
        headquarters["postal_code"], headquarters["country"],
    ) if p)

    if not company_name:
        company_name = meta.get("og_site_name") or meta.get("title") or ""

    country_hint = _country_to_iso2(headquarters["country"])
    normalized_phones = []
    for raw in all_phones:
        normalized = _normalize_phone(raw, country_hint)
        if normalized and normalized not in normalized_phones:
            normalized_phones.append(normalized)

    valid_emails = sorted({e.lower() for e in all_emails if _is_valid_company_email(e)})

    return {
        "company_name": company_name,
        "logo_url": logo_url,
        "headquarters": {**headquarters, "full_address": full_address},
        "country": headquarters["country"],
        "city": headquarters["city"],
        "emails": valid_emails,
        "email": valid_emails[0] if valid_emails else "",
        "phones": normalized_phones,
        "phone": normalized_phones[0] if normalized_phones else "",
        "contact_person": contact_person,
        "social": social,
        "meta": meta,
    }


# ============================================================
# Public entry point
# ============================================================

def scrape_and_detect(url: str) -> dict:
    """Fetch `url` (plus a handful of relevant sub-pages), detect
    technologies/vendors/categories, and return a full company profile."""
    base_url = _normalize_url(url)

    session = requests.Session()  # reused across every request in this crawl
    session.headers["User-Agent"] = USER_AGENT
    try:
        pages = _crawl_site(session, base_url)
    finally:
        session.close()

    combined_html = "\n".join(p["html"] for p in pages)
    technologies, vendors, categories = _detect_technologies(combined_html, pages[0]["headers"])

    pages_extracted = [_extract_page_data(p) for p in pages]
    company_info = _merge_pages(pages_extracted)
    company_info["website"] = base_url
    company_info["pages_crawled"] = [p["url"] for p in pages]

    # Legacy shape kept intact so existing callers (streamlit_app.py) keep working.
    contact = {
        "company_name": company_info["company_name"],
        "emails": company_info["emails"],
        "phones": company_info["phones"],
        "address": company_info["headquarters"]["full_address"],
    }

    return {
        "technologies": technologies,
        "vendors": vendors,
        "categories": categories,
        "chars_scraped": len(combined_html),
        "contact": contact,
        "company_info": company_info,
    }
