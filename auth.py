"""
Authentication core module.

Extends the existing app with user registration, login, JWT issuance/
validation and a forgot-password flow. Uses the same SQLAlchemy session
pattern as database.py and does not modify any existing scraping/
technology-detection logic.
"""

import os
import re
import secrets
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Optional

import bcrypt
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from database import (
    User,
    get_user_by_email,
    create_user as db_create_user,
    update_last_login as db_update_last_login,
    update_user_password as db_update_user_password,
    create_password_reset_token,
    get_password_reset_token,
    mark_reset_token_used,
)

# ============ Config ============

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-only-insecure-secret-change-me")
if JWT_SECRET_KEY == "dev-only-insecure-secret-change-me":
    print("[WARN] JWT_SECRET_KEY is not set - using an insecure development default. "
          "Set the JWT_SECRET_KEY environment variable in production.")

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60          # normal session
REMEMBER_ME_EXPIRE_DAYS = 7               # "Remember me" session
RESET_TOKEN_EXPIRE_MINUTES = 30

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ============ Validation helpers ============

def is_valid_email(email: str) -> bool:
    return bool(email) and bool(EMAIL_RE.match(email.strip()))

def is_valid_password(password: str) -> bool:
    return bool(password) and len(password) >= 8


# ============ Password hashing ============

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


# ============ JWT ============

def create_access_token(user: User, remember_me: bool = False) -> str:
    expire_delta = (
        timedelta(days=REMEMBER_ME_EXPIRE_DAYS) if remember_me
        else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    expire_at = datetime.utcnow() + expire_delta
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "full_name": user.full_name,
        "exp": expire_at,
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

def decode_access_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None


# ============ Registration / login ============

class AuthError(Exception):
    """Raised for user-facing validation/auth failures."""


def register_user(db: Session, full_name: str, email: str, password: str, confirm_password: str) -> User:
    full_name = (full_name or "").strip()
    email = (email or "").strip().lower()

    if not full_name:
        raise AuthError("Full name is required.")
    if not is_valid_email(email):
        raise AuthError("Enter a valid email address.")
    if not is_valid_password(password):
        raise AuthError("Password must be at least 8 characters long.")
    if password != confirm_password:
        raise AuthError("Passwords do not match.")
    if get_user_by_email(db, email) is not None:
        raise AuthError("An account with this email already exists.")

    return db_create_user(db, full_name=full_name, email=email, hashed_password=hash_password(password))


def authenticate_user(db: Session, email: str, password: str) -> User:
    email = (email or "").strip().lower()
    user = get_user_by_email(db, email)
    if user is None or not verify_password(password, user.hashed_password):
        raise AuthError("Incorrect email or password.")
    if not user.is_active:
        raise AuthError("This account has been deactivated.")
    db_update_last_login(db, user)
    return user


def get_or_create_google_user(db: Session, email: str, full_name: str) -> User:
    """Look up a user by their Google account email, auto-creating one on
    first sign-in. Google-created accounts get an unusable random password
    hash - they can only sign in via Google unless they later use
    'forgot password' to set a real one."""
    email = (email or "").strip().lower()
    user = get_user_by_email(db, email)
    if user is not None:
        return user
    unusable_password_hash = hash_password(secrets.token_urlsafe(32))
    return db_create_user(
        db, full_name=full_name or email, email=email,
        hashed_password=unusable_password_hash, auth_provider="google",
    )


def update_last_login_for(db: Session, user: User) -> User:
    return db_update_last_login(db, user)


def get_user_from_token(db: Session, token: str) -> Optional[User]:
    payload = decode_access_token(token)
    if not payload:
        return None
    user_id = payload.get("sub")
    if user_id is None:
        return None
    from database import get_user_by_id
    return get_user_by_id(db, int(user_id))


# ============ Forgot / reset password ============

def request_password_reset(db: Session, email: str) -> Optional[str]:
    """Create a reset token for the given email and 'send' it.

    Returns the plaintext token only when SMTP isn't configured, so the
    caller (Streamlit) can display it directly for local/dev testing.
    Returns None both when a real email was sent and when the account
    doesn't exist, so the UI can show the same generic message either way.
    """
    email = (email or "").strip().lower()
    user = get_user_by_email(db, email)
    if user is None:
        # Do not reveal whether the account exists.
        return None

    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)
    create_password_reset_token(db, user_id=user.id, token=token, expires_at=expires_at)

    sent_via_smtp = _send_reset_email(user.email, token)
    return None if sent_via_smtp else token


def reset_password(db: Session, token: str, new_password: str, confirm_password: str) -> User:
    if not is_valid_password(new_password):
        raise AuthError("Password must be at least 8 characters long.")
    if new_password != confirm_password:
        raise AuthError("Passwords do not match.")

    reset_token = get_password_reset_token(db, token)
    if reset_token is None or reset_token.used:
        raise AuthError("This reset link is invalid or has already been used.")
    if reset_token.expires_at < datetime.utcnow():
        raise AuthError("This reset link has expired. Please request a new one.")

    from database import get_user_by_id
    user = get_user_by_id(db, reset_token.user_id)
    if user is None:
        raise AuthError("This reset link is invalid.")

    db_update_user_password(db, user, hash_password(new_password))
    mark_reset_token_used(db, reset_token)
    return user


def _send_reset_email(to_email: str, token: str) -> bool:
    """Send the reset token via SMTP if configured, else mock by printing
    to the console. Returns True if an SMTP send was attempted."""
    smtp_host = os.getenv("SMTP_HOST")
    reset_link = f"Reset code: {token}"

    if not smtp_host:
        print(f"[MOCK EMAIL] Password reset requested for {to_email}. {reset_link} "
              f"(valid for {RESET_TOKEN_EXPIRE_MINUTES} minutes)")
        return False

    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_from = os.getenv("SMTP_FROM", smtp_user or "no-reply@example.com")

    message = EmailMessage()
    message["Subject"] = "Password Reset - Company Technology Dashboard"
    message["From"] = smtp_from
    message["To"] = to_email
    message.set_content(
        f"You requested a password reset.\n\n{reset_link}\n\n"
        f"This code expires in {RESET_TOKEN_EXPIRE_MINUTES} minutes. "
        f"If you did not request this, ignore this email."
    )

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            server.send_message(message)
        return True
    except Exception as e:
        print(f"[WARN] Failed to send reset email via SMTP, falling back to console: {e}")
        print(f"[MOCK EMAIL] {reset_link}")
        return False
