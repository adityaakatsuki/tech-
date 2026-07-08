"""Writes .streamlit/secrets.toml from environment variables at container
startup. .streamlit/secrets.toml is git-ignored (it holds real OAuth
credentials), so on a host like Railway - which only has env vars, not that
file - this script recreates it right before Streamlit starts.

Required env vars: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
STREAMLIT_COOKIE_SECRET, OAUTH_REDIRECT_URI (e.g.
https://your-app.up.railway.app/oauth2callback).
"""

import os
import sys
from pathlib import Path

REQUIRED_VARS = [
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "STREAMLIT_COOKIE_SECRET",
    "OAUTH_REDIRECT_URI",
]


def main() -> None:
    missing = [name for name in REQUIRED_VARS if not os.environ.get(name)]
    if missing:
        print(f"[write_secrets] Skipping - missing env vars: {', '.join(missing)}. "
              f"Google sign-in will show as not configured until these are set.")
        return

    secrets_dir = Path(__file__).resolve().parent / ".streamlit"
    secrets_dir.mkdir(exist_ok=True)
    secrets_path = secrets_dir / "secrets.toml"

    secrets_path.write_text(
        "[auth]\n"
        f'redirect_uri = "{os.environ["OAUTH_REDIRECT_URI"]}"\n'
        f'cookie_secret = "{os.environ["STREAMLIT_COOKIE_SECRET"]}"\n'
        "\n"
        "[auth.google]\n"
        f'client_id = "{os.environ["GOOGLE_CLIENT_ID"]}"\n'
        f'client_secret = "{os.environ["GOOGLE_CLIENT_SECRET"]}"\n'
        'server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"\n'
    )
    print(f"[write_secrets] Wrote {secrets_path}")


if __name__ == "__main__":
    main()
    sys.exit(0)
