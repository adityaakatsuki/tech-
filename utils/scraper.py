"""
Lightweight technology-detection scraper.

Fetches a URL and inspects the HTML, response headers and inline/linked
scripts for known signatures (script src patterns, meta generator tags,
server headers, cookie names) to guess which technologies, vendors and
categories a site uses. Also pulls basic contact details (company name,
emails, phones, address) off the page. Not exhaustive - a small,
maintainable signature list rather than a full Wappalyzer port.
"""

import re
import requests
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
REQUEST_TIMEOUT = 10

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

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
# Requires a space/dash/parenthesis separator between digit groups, so minified
# JS/CSS numbers like "00.000001" (dot-only) never match.
PHONE_RE = re.compile(r"(?:\+\d{1,3}[\s\-]?)?\(?\d{2,4}\)?[\s\-]\d{3,4}[\s\-]?\d{0,4}")
ADDRESS_RE = re.compile(
    r"\d{1,5}\s+[A-Za-z0-9.\s]{3,60}\b(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Way|Suite|Ste)\b[A-Za-z0-9.,\s]{0,60}",
    re.IGNORECASE,
)


def _normalize_url(url: str) -> str:
    url = url.strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = f"https://{url}"
    return url


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


def _extract_contact(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    og_site_name = soup.find("meta", property="og:site_name")
    company_name = (
        og_site_name["content"].strip() if og_site_name and og_site_name.get("content")
        else soup.title.get_text().strip() if soup.title else ""
    )

    mailto_emails = {
        a["href"].split("mailto:", 1)[1].split("?")[0].strip()
        for a in soup.select('a[href^="mailto:"]') if a.get("href")
    }
    tel_phones = {
        a["href"].split("tel:", 1)[1].strip()
        for a in soup.select('a[href^="tel:"]') if a.get("href")
    }

    for tag in soup(["script", "style"]):
        tag.decompose()
    visible_text = soup.get_text(separator=" ")

    emails = sorted(mailto_emails | set(EMAIL_RE.findall(visible_text)))
    phones = sorted(tel_phones | set(PHONE_RE.findall(visible_text)))
    address_match = ADDRESS_RE.search(visible_text)
    address = address_match.group(0).strip() if address_match else ""

    return {
        "company_name": company_name,
        "emails": emails,
        "phones": phones,
        "address": address,
    }


def scrape_and_detect(url: str) -> dict:
    """Fetch `url` and return detected technologies/vendors/categories plus
    any contact details found on the page."""
    target = _normalize_url(url)
    response = requests.get(target, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    html = response.text

    technologies, vendors, categories = _detect_technologies(html, response.headers)
    contact = _extract_contact(html)

    return {
        "technologies": technologies,
        "vendors": vendors,
        "categories": categories,
        "chars_scraped": len(html),
        "contact": contact,
    }
