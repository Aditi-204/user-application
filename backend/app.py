import base64
import binascii
import hashlib
import logging
import os
import re
import secrets
import smtplib
import ssl
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Literal
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

load_dotenv()
MONGO_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
DB_NAME = os.getenv("MONGODB_DATABASE", "accessdesk")
JWT_SECRET = os.getenv("JWT_SECRET", "")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "Aditi.admin@gmail.com").strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
APP_ENV = os.getenv("APP_ENV", "development").lower()
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173").rstrip("/")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USERNAME)
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "false").lower() == "true"
SMTP_STARTTLS = os.getenv("SMTP_STARTTLS", "true").lower() == "true"
ALGORITHM = "HS256"
TOKEN_MINUTES = 60 * 12
pwd = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto", pbkdf2_sha256__rounds=600000)
bearer = HTTPBearer(auto_error=False)
client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
db = client[DB_NAME]
users = db.users
activities = db.activities
app = FastAPI(title="AccessDesk API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
logger = logging.getLogger("accessdesk")


class SlidingWindowLimiter:
    """Process-local limiter; use a shared store when running multiple workers."""
    def __init__(self):
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key, limit, window_seconds, at=None):
        at = time.monotonic() if at is None else at
        cutoff = at - window_seconds
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit:
                return False, max(1, int(window_seconds - (at - hits[0])))
            hits.append(at)
            return True, 0


rate_limiter = SlidingWindowLimiter()


@app.middleware("http")
async def limit_auth_requests(request: Request, call_next):
    policy = {
        "/api/auth/login": (8, 15 * 60),
        "/api/auth/register": (5, 60 * 60),
        "/api/auth/resend-verification": (3, 60 * 60),
        "/api/auth/verify-email": (10, 15 * 60),
    }.get(request.url.path)
    if policy:
        ip = request.client.host if request.client else "unknown"
        allowed, retry_after = rate_limiter.hit(f"{request.url.path}:{ip}", *policy)
        if not allowed:
            return JSONResponse({"detail": "Too many attempts. Please wait before trying again."}, status_code=429,
                                headers={"Retry-After": str(retry_after)})
    return await call_next(request)


class RegisterInput(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginInput(BaseModel):
    email: EmailStr
    password: str
    admin: bool = False


class EmailInput(BaseModel):
    email: EmailStr


class VerifyEmailInput(BaseModel):
    token: str = Field(min_length=32, max_length=256)


class ProfileInput(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    avatar_data: str | None = Field(default=None, max_length=1_400_000)


def now():
    return datetime.now(timezone.utc)


def validate_security_config():
    if len(JWT_SECRET) < 32:
        raise RuntimeError("Set JWT_SECRET to a random value at least 32 characters long in backend/.env")
    if len(ADMIN_PASSWORD) < 16:
        raise RuntimeError("Set ADMIN_PASSWORD to at least 16 characters in backend/.env")
    if APP_ENV == "production" and (not SMTP_HOST or not SMTP_FROM):
        raise RuntimeError("Configure SMTP_HOST and SMTP_FROM when APP_ENV=production")


def verification_token_pair():
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return token, digest


def send_verification_email(email, token):
    verify_url = f"{FRONTEND_ORIGIN}/?verify_email={quote(token)}"
    if not SMTP_HOST or not SMTP_FROM:
        if APP_ENV == "production":
            raise RuntimeError("Email delivery is not configured")
        logger.warning("Local development email verification link for %s: %s", email, verify_url)
        return False

    message = EmailMessage()
    message["Subject"] = "Verify your AccessDesk email"
    message["From"] = SMTP_FROM
    message["To"] = email
    message.set_content(f"Verify your email to submit your AccessDesk account request:\n\n{verify_url}\n\nThis link expires in 24 hours.")
    context = ssl.create_default_context()
    if SMTP_USE_SSL:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=15) as server:
            if SMTP_USERNAME:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(message)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            if SMTP_STARTTLS:
                server.starttls(context=context)
            if SMTP_USERNAME:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(message)
    return True


def public_user(user, include_avatar=False):
    result = {"id": str(user["_id"]), "name": user["name"], "email": user["email"],
              "role": user["role"], "status": user["status"],
              "created_at": user["created_at"].isoformat(),
              "email_verified": user.get("email_verified", True)}
    if include_avatar and user.get("avatar_data"):
        result["avatar_data"] = user["avatar_data"]
    return result


def validate_avatar(data_uri):
    match = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/]*={0,2})", data_uri)
    if not match:
        raise HTTPException(status_code=422, detail="Use a PNG, JPEG, or WebP profile photo")
    try:
        image = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail="The profile photo file is invalid")
    if not image or len(image) > 1_048_576:
        raise HTTPException(status_code=413, detail="Profile photos must be 1 MB or smaller")
    kind = match.group(1)
    valid_signature = (
        (kind == "png" and image.startswith(b"\x89PNG\r\n\x1a\n")) or
        (kind == "jpeg" and image.startswith(b"\xff\xd8\xff")) or
        (kind == "webp" and len(image) >= 12 and image.startswith(b"RIFF") and image[8:12] == b"WEBP")
    )
    if not valid_signature:
        raise HTTPException(status_code=422, detail="The selected file does not match its image type")


def record(action, actor, target=None, detail=""):
    activities.insert_one({"action": action, "actor_id": str(actor["_id"]),
                           "actor_name": actor["name"], "actor_email": actor["email"],
                           "target_id": str(target["_id"]) if target else None,
                           "target_name": target.get("name") if target else None,
                           "target_email": target["email"] if target else None,
                           "detail": detail, "created_at": now()})


def token_for(user):
    return jwt.encode({"sub": str(user["_id"]), "exp": now() + timedelta(minutes=TOKEN_MINUTES)}, JWT_SECRET, algorithm=ALGORITHM)


def current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    if not credentials:
        raise HTTPException(status_code=401, detail="Please sign in")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[ALGORITHM])
        from bson import ObjectId
        user = users.find_one({"_id": ObjectId(payload["sub"])})
    except (JWTError, ValueError, KeyError):
        user = None
    if not user or user["status"] != "approved":
        raise HTTPException(status_code=401, detail="Session is invalid or access is not approved")
    return user


def admin_user(user=Depends(current_user)):
    if user["role"] != "admin" or user["email"] != ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


@app.on_event("startup")
def initialize():
    validate_security_config()
    users.create_index("email", unique=True)
    activities.create_index("created_at")
    users.update_many({"email_verified": {"$exists": False}}, {"$set": {"email_verified": True}})
    email = ADMIN_EMAIL
    admin = users.find_one({"email": email})
    if not admin:
        users.insert_one({"name": "Administrator", "email": email,
                          "password_hash": pwd.hash(ADMIN_PASSWORD), "role": "admin",
                          "status": "approved", "email_verified": True, "created_at": now()})
    else:
        updates = {"role": "admin", "status": "approved", "email_verified": True}
        if not pwd.verify(ADMIN_PASSWORD, admin["password_hash"]):
            updates["password_hash"] = pwd.hash(ADMIN_PASSWORD)
        users.update_one({"_id": admin["_id"]}, {"$set": updates})


@app.get("/api/health")
def health():
    try:
        client.admin.command("ping")
        return {"status": "ok", "database": "connected"}
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")


@app.post("/api/auth/register", status_code=201)
def register(body: RegisterInput):
    email = body.email.lower().strip()
    if users.find_one({"email": email}):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    token, token_hash = verification_token_pair()
    created_at = now()
    user = {"name": body.name.strip(), "email": email,
            "password_hash": pwd.hash(body.password), "role": "user",
            "status": "pending", "email_verified": False,
            "verification_token_hash": token_hash,
            "verification_expires_at": created_at + timedelta(hours=24),
            "created_at": created_at}
    try:
        result = users.insert_one(user)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user["_id"] = result.inserted_id
    try:
        delivered = send_verification_email(email, token)
    except Exception:
        users.delete_one({"_id": user["_id"]})
        logger.exception("Could not send an email verification message")
        raise HTTPException(status_code=503, detail="We could not send the verification email. Please try again later.")
    record("account_created", user, user, "Registration submitted; awaiting admin approval")
    message = "Check your email for a verification link. Your request will be reviewed after verification."
    if not delivered:
        message += " In local development, the link is printed in the backend console."
    return {"message": message}


@app.post("/api/auth/verify-email")
def verify_email(body: VerifyEmailInput):
    token_hash = hashlib.sha256(body.token.encode("utf-8")).hexdigest()
    user = users.find_one({"verification_token_hash": token_hash,
                           "verification_expires_at": {"$gt": now()}, "email_verified": False})
    if not user:
        raise HTTPException(status_code=400, detail="This verification link is invalid or has expired.")
    users.update_one({"_id": user["_id"]}, {"$set": {"email_verified": True},
                                           "$unset": {"verification_token_hash": "", "verification_expires_at": ""}})
    return {"message": "Email verified. Your registration request is now waiting for admin approval."}


@app.post("/api/auth/resend-verification")
def resend_verification(body: EmailInput):
    email = body.email.lower().strip()
    user = users.find_one({"email": email, "email_verified": False, "role": "user"})
    if user:
        token, token_hash = verification_token_pair()
        users.update_one({"_id": user["_id"]}, {"$set": {"verification_token_hash": token_hash,
                                                          "verification_expires_at": now() + timedelta(hours=24)}})
        try:
            delivered = send_verification_email(email, token)
        except Exception:
            logger.exception("Could not resend an email verification message")
            raise HTTPException(status_code=503, detail="We could not send the verification email. Please try again later.")
    else:
        delivered = bool(SMTP_HOST and SMTP_FROM)
    message = "If that address has an unverified account, a new verification link has been sent."
    if not delivered and APP_ENV != "production":
        message += " In local development, check the backend console."
    return {"message": message}


@app.post("/api/auth/login")
def login(body: LoginInput):
    user = users.find_one({"email": body.email.lower().strip()})
    if not user or not pwd.verify(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    if body.admin and (user["email"] != ADMIN_EMAIL or user["role"] != "admin"):
        raise HTTPException(status_code=403, detail="Administrator credentials are not valid")
    if not body.admin and user["role"] == "admin":
        raise HTTPException(status_code=403, detail="Use the administrator sign-in option for this account.")
    if not user.get("email_verified", True):
        raise HTTPException(status_code=403, detail="Please verify your email before signing in.")
    if user["status"] == "pending":
        raise HTTPException(status_code=403, detail="Your registration is waiting for admin approval.")
    if user["status"] == "rejected":
        raise HTTPException(status_code=403, detail="Your registration was not approved. Contact an administrator.")
    record("login", user, user, "Successful login")
    return {"token": token_for(user), "user": public_user(user, include_avatar=True)}


@app.get("/api/auth/me")
def me(user=Depends(current_user)):
    return public_user(user, include_avatar=True)


@app.patch("/api/profile")
def update_profile(body: ProfileInput, user=Depends(current_user)):
    name = body.name.strip()
    email = body.email.lower().strip()
    updates = {"name": name, "email": email}
    unset = {}
    changed = []
    email_change_token = None
    if name != user["name"]:
        changed.append("name")
    if email != user["email"]:
        if users.find_one({"email": email, "_id": {"$ne": user["_id"]}}):
            raise HTTPException(status_code=409, detail="An account with this email already exists")
        changed.append("email")
        email_change_token, verification_hash = verification_token_pair()
        updates.update({"email_verified": False, "verification_token_hash": verification_hash,
                        "verification_expires_at": now() + timedelta(hours=24)})
    avatar_changed = "avatar_data" in body.__fields_set__
    if avatar_changed:
        if body.avatar_data is None:
            avatar_changed = user.get("avatar_data") is not None
            unset["avatar_data"] = ""
        else:
            validate_avatar(body.avatar_data)
            avatar_changed = body.avatar_data != user.get("avatar_data")
            updates["avatar_data"] = body.avatar_data
    if avatar_changed:
        changed.append("profile photo")
    if not changed:
        return public_user(user, include_avatar=True)
    if email_change_token:
        try:
            send_verification_email(email, email_change_token)
        except Exception:
            logger.exception("Could not send an email verification message for an email change")
            raise HTTPException(status_code=503, detail="We could not send a verification email to the new address. No profile changes were saved.")
    update_doc = {"$set": updates}
    if unset:
        update_doc["$unset"] = unset
    try:
        users.update_one({"_id": user["_id"]}, update_doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user.update(updates)
    for key in unset:
        user.pop(key, None)
    record("profile_updated", user, user, f"Updated: {', '.join(changed)}")
    return public_user(user, include_avatar=True)


@app.delete("/api/profile", status_code=204)
def delete_profile(user=Depends(current_user)):
    record("profile_deleted", user, user, "User deleted their profile")
    users.delete_one({"_id": user["_id"]})


@app.get("/api/admin/overview")
def overview(admin=Depends(admin_user)):
    return {"pending": users.count_documents({"role": "user", "email_verified": True, "status": "pending"}),
            "approved": users.count_documents({"role": "user", "email_verified": True, "status": "approved"}),
            "rejected": users.count_documents({"role": "user", "email_verified": True, "status": "rejected"}),
            "logins": activities.count_documents({"action": "login", "actor_email": {"$ne": ADMIN_EMAIL}})}


@app.get("/api/admin/users")
def list_users(admin=Depends(admin_user)):
    return [public_user(u) for u in users.find({"role": "user", "email_verified": True}).sort("created_at", -1)]


@app.post("/api/admin/users/{user_id}/{decision}")
def decide_user(user_id: str, decision: Literal["approve", "reject"], admin=Depends(admin_user)):
    from bson import ObjectId
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=404, detail="User not found")
    target = users.find_one({"_id": ObjectId(user_id), "role": "user", "email_verified": True})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    new_status = "approved" if decision == "approve" else "rejected"
    users.update_one({"_id": target["_id"]}, {"$set": {"status": new_status}})
    record(f"registration_{new_status}", admin, target, f"Admin {new_status} registration")
    return {"message": f"Registration {new_status}", "status": new_status}


@app.get("/api/admin/activity")
def activity_log(limit: int = 100, admin=Depends(admin_user)):
    limit = max(1, min(limit, 500))
    query = {"$nor": [{"actor_email": ADMIN_EMAIL, "target_email": ADMIN_EMAIL}]}
    return [{"id": str(a["_id"]), "action": a["action"], "actor_id": a.get("actor_id"),
             "target_id": a.get("target_id"), "actor_name": a["actor_name"],
             "actor_email": a["actor_email"], "target_email": a.get("target_email"),
             "target_name": a.get("target_name"),
             "detail": a.get("detail", ""), "created_at": a["created_at"].isoformat()}
            for a in activities.find(query).sort("created_at", -1).limit(limit)]


@app.get("/api/admin/ai-summary")
def ai_summary(admin=Depends(admin_user)):
    """A local, data-grounded starter summary; replace with an LLM provider if required."""
    pending = users.count_documents({"role": "user", "email_verified": True, "status": "pending"})
    approved = users.count_documents({"role": "user", "email_verified": True, "status": "approved"})
    recent = list(activities.find({"$nor": [{"actor_email": ADMIN_EMAIL, "target_email": ADMIN_EMAIL}]}).sort("created_at", -1).limit(100))
    counts = {}
    for item in recent:
        counts[item["action"]] = counts.get(item["action"], 0) + 1
    common = max(counts, key=counts.get) if counts else None
    summary = f"There are {pending} registration request(s) awaiting review and {approved} approved user(s). "
    summary += f"The most common recorded action in the latest {len(recent)} events is {common.replace('_', ' ')} ({counts[common]})." if common else "No activity has been recorded yet."
    return {"summary": summary, "generated_at": now().isoformat(), "events_analyzed": len(recent)}
