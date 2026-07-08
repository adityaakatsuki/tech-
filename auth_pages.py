"""
Streamlit authentication UI: login, register, forgot/reset password, and
session_state helpers (including a lightweight "remember me" using the
page's URL query params so a JWT can survive a browser refresh).

This module only renders auth screens and manages st.session_state - it
does not touch the scraper, technology detection, or existing dashboard
pages in streamlit_app.py.
"""

from contextlib import contextmanager

import streamlit as st

import auth
from database import SessionLocal

APP_NAME = "Company Technology Dashboard"


# ============================================================
# Session state helpers
# ============================================================

def init_auth_state() -> None:
    st.session_state.setdefault("auth_user", None)
    st.session_state.setdefault("auth_token", None)
    st.session_state.setdefault("auth_page", "login")
    _restore_session_from_query_params()
    _sync_google_session()


def _restore_session_from_query_params() -> None:
    """Support 'remember me': if a valid token is present in the URL query
    params, restore the session without asking for credentials again."""
    if st.session_state.get("auth_user"):
        return
    token = st.query_params.get("token")
    if not token:
        return
    db = SessionLocal()
    try:
        user = auth.get_user_from_token(db, token)
    finally:
        db.close()
    if user is not None and user.is_active:
        st.session_state["auth_user"] = user
        st.session_state["auth_token"] = token
    else:
        _clear_query_token()


def _sync_google_session() -> None:
    """If Streamlit's built-in st.login("google") succeeded, mirror it into
    our own User table / session_state so the rest of the app (sidebar,
    logout, JWT) behaves the same regardless of how the user signed in."""
    if st.session_state.get("auth_user"):
        return
    try:
        google_user = st.user
        if not google_user.is_logged_in:
            return
        email = google_user.email
        full_name = getattr(google_user, "name", None) or email
    except Exception:
        return

    db = SessionLocal()
    try:
        user = auth.get_or_create_google_user(db, email=email, full_name=full_name)
        auth.update_last_login_for(db, user)
    finally:
        db.close()

    token = auth.create_access_token(user, remember_me=True)
    st.session_state["auth_user"] = user
    st.session_state["auth_token"] = token


def is_authenticated() -> bool:
    return st.session_state.get("auth_user") is not None


def current_user():
    return st.session_state.get("auth_user")


def _set_query_token(token: str) -> None:
    st.query_params["token"] = token

def _clear_query_token() -> None:
    if "token" in st.query_params:
        del st.query_params["token"]


def login_session(user, token: str, remember_me: bool) -> None:
    st.session_state["auth_user"] = user
    st.session_state["auth_token"] = token
    if remember_me:
        _set_query_token(token)
    else:
        _clear_query_token()


def logout_session() -> None:
    st.session_state["auth_user"] = None
    st.session_state["auth_token"] = None
    st.session_state["auth_page"] = "login"
    _clear_query_token()
    try:
        if st.user.is_logged_in:
            st.logout()
    except Exception:
        pass


def go_to(page: str) -> None:
    st.session_state["auth_page"] = page
    st.rerun()


# ============================================================
# Shared chrome
# ============================================================

@contextmanager
def auth_card(subtitle: str):
    """Centered, rounded card that encloses the whole auth form (header +
    the actual input widgets) - not just markdown text."""
    st.markdown("<div class='auth-top-spacer'></div>", unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 1.3, 1])
    with mid:
        with st.container(key="auth_card"):
            st.markdown(
                f"<div class='auth-logo'>📊</div>"
                f"<div class='auth-title'>{APP_NAME}</div>"
                f"<div class='auth-subtitle'>{subtitle}</div>",
                unsafe_allow_html=True,
            )
            yield


def render_google_button(key: str) -> None:
    """'Continue with Google' - uses Streamlit's built-in st.login()
    (OIDC via Authlib), configured in .streamlit/secrets.toml."""
    if st.button("Continue with Google", width="stretch", key=key, icon=":material/account_circle:"):
        try:
            st.login("google")
        except Exception as e:
            st.error(
                "Google sign-in isn't configured yet. Add your OAuth client "
                f"credentials to .streamlit/secrets.toml. ({e})"
            )
    st.markdown(
        "<div class='auth-or-divider'><span>or continue with email</span></div>",
        unsafe_allow_html=True,
    )


# ============================================================
# Login page
# ============================================================

def render_login_page() -> None:
    with auth_card("Sign in to continue"):
        render_google_button(key="google_login_btn")
        with st.form("login_form", clear_on_submit=False):
            email = st.text_input("Email Address", placeholder="you@company.com")
            password = st.text_input("Password", type="password", placeholder="••••••••")
            remember_me = st.checkbox("Remember me for 7 days")
            submitted = st.form_submit_button("Login", type="primary", width="stretch")

        if submitted:
            db = SessionLocal()
            try:
                user = auth.authenticate_user(db, email=email, password=password)
            except auth.AuthError as e:
                st.error(str(e))
                db.close()
            else:
                token = auth.create_access_token(user, remember_me=remember_me)
                login_session(user, token, remember_me)
                db.close()
                st.rerun()

        st.markdown("<div class='auth-divider'></div>", unsafe_allow_html=True)
        st.caption("Don't have an account?")
        if st.button("Register", width="stretch"):
            go_to("register")
        if st.button("Forgot password?", width="stretch"):
            go_to("forgot")


# ============================================================
# Register page
# ============================================================

def render_register_page() -> None:
    with auth_card("Create your account"):
        render_google_button(key="google_register_btn")
        with st.form("register_form", clear_on_submit=False):
            full_name = st.text_input("Full Name", placeholder="Jane Doe")
            email = st.text_input("Email Address", placeholder="you@company.com")
            password = st.text_input("Password", type="password", placeholder="At least 8 characters")
            confirm_password = st.text_input("Confirm Password", type="password", placeholder="Re-enter password")
            submitted = st.form_submit_button("Create Account", type="primary", width="stretch")

        if submitted:
            db = SessionLocal()
            try:
                auth.register_user(
                    db, full_name=full_name, email=email,
                    password=password, confirm_password=confirm_password,
                )
            except auth.AuthError as e:
                st.error(str(e))
            else:
                st.success("Account created successfully. You can now log in.")
            finally:
                db.close()

        st.markdown("<div class='auth-divider'></div>", unsafe_allow_html=True)
        st.caption("Already have an account?")
        if st.button("Back to Login", width="stretch"):
            go_to("login")


# ============================================================
# Forgot / reset password page
# ============================================================

def render_forgot_password_page() -> None:
    with auth_card("Reset your password"):
        st.markdown("##### Step 1 - Request a reset code")
        with st.form("forgot_form", clear_on_submit=False):
            email = st.text_input("Email Address", placeholder="you@company.com")
            submitted = st.form_submit_button("Send Reset Code", type="primary", width="stretch")

        if submitted:
            db = SessionLocal()
            try:
                token = auth.request_password_reset(db, email=email)
            finally:
                db.close()
            st.success("If an account with that email exists, a reset code has been sent.")
            if token:
                st.info(
                    "SMTP is not configured, so here is your reset code for testing:\n\n"
                    f"`{token}`"
                )

        st.markdown("##### Step 2 - Enter your reset code and new password")
        with st.form("reset_form", clear_on_submit=False):
            token_input = st.text_input("Reset Code")
            new_password = st.text_input("New Password", type="password", placeholder="At least 8 characters")
            confirm_password = st.text_input("Confirm New Password", type="password")
            reset_submitted = st.form_submit_button("Reset Password", width="stretch")

        if reset_submitted:
            db = SessionLocal()
            try:
                auth.reset_password(
                    db, token=token_input, new_password=new_password,
                    confirm_password=confirm_password,
                )
            except auth.AuthError as e:
                st.error(str(e))
            else:
                st.success("Password reset successfully. You can now log in.")
            finally:
                db.close()

        st.markdown("<div class='auth-divider'></div>", unsafe_allow_html=True)
        if st.button("Back to Login", width="stretch"):
            go_to("login")


# ============================================================
# Router
# ============================================================

def render_auth_flow() -> None:
    """Renders whichever auth screen is active. Call only when the user
    is not authenticated."""
    page = st.session_state.get("auth_page", "login")
    if page == "register":
        render_register_page()
    elif page == "forgot":
        render_forgot_password_page()
    else:
        render_login_page()
