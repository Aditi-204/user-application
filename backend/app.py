import base64
import binascii
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

load_dotenv()
MONGO_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
DB_NAME = os.getenv("MONGODB_DATABASE", "accessdesk")
JWT_SECRET = os.getenv("JWT_SECRET", "development-only-change-me")
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
    allow_origins=[os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


class RegisterInput(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginInput(BaseModel):
    email: EmailStr
    password: str


class ProfileInput(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    avatar_data: str | None = Field(default=None, max_length=1_400_000)


def now():
    return datetime.now(timezone.utc)


def public_user(user, include_avatar=False):
    result = {"id": str(user["_id"]), "name": user["name"], "email": user["email"],
              "role": user["role"], "status": user["status"],
              "created_at": user["created_at"].isoformat()}
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
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


@app.on_event("startup")
def initialize():
    users.create_index("email", unique=True)
    activities.create_index("created_at")
    email = os.getenv("ADMIN_EMAIL", "admin@example.com").strip().lower()
    password = os.getenv("ADMIN_PASSWORD")
    if password and not users.find_one({"email": email}):
        users.insert_one({"name": "Administrator", "email": email,
                          "password_hash": pwd.hash(password), "role": "admin",
                          "status": "approved", "created_at": now()})


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
    user = {"name": body.name.strip(), "email": email,
            "password_hash": pwd.hash(body.password), "role": "user",
            "status": "pending", "created_at": now()}
    try:
        result = users.insert_one(user)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user["_id"] = result.inserted_id
    record("account_created", user, user, "Registration submitted; awaiting admin approval")
    return {"message": "Registration received. Your account is waiting for admin approval."}


@app.post("/api/auth/login")
def login(body: LoginInput):
    user = users.find_one({"email": body.email.lower().strip()})
    if not user or not pwd.verify(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
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
    updates = {"name": name}
    unset = {}
    avatar_changed = "avatar_data" in body.__fields_set__
    if avatar_changed:
        if body.avatar_data is None:
            unset["avatar_data"] = ""
        else:
            validate_avatar(body.avatar_data)
            updates["avatar_data"] = body.avatar_data
    update_doc = {"$set": updates}
    if unset:
        update_doc["$unset"] = unset
    users.update_one({"_id": user["_id"]}, update_doc)
    user.update(updates)
    for key in unset:
        user.pop(key, None)
    record("profile_updated", user, user, "Profile details updated" if avatar_changed else "Profile name updated")
    return public_user(user, include_avatar=True)


@app.delete("/api/profile", status_code=204)
def delete_profile(user=Depends(current_user)):
    record("profile_deleted", user, user, "User deleted their profile")
    users.delete_one({"_id": user["_id"]})


@app.get("/api/admin/overview")
def overview(admin=Depends(admin_user)):
    return {"pending": users.count_documents({"role": "user", "status": "pending"}),
            "approved": users.count_documents({"role": "user", "status": "approved"}),
            "rejected": users.count_documents({"role": "user", "status": "rejected"}),
            "logins": activities.count_documents({"action": "login"})}


@app.get("/api/admin/users")
def list_users(admin=Depends(admin_user)):
    return [public_user(u) for u in users.find({"role": "user"}).sort("created_at", -1)]


@app.post("/api/admin/users/{user_id}/{decision}")
def decide_user(user_id: str, decision: Literal["approve", "reject"], admin=Depends(admin_user)):
    from bson import ObjectId
    if not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=404, detail="User not found")
    target = users.find_one({"_id": ObjectId(user_id), "role": "user"})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    new_status = "approved" if decision == "approve" else "rejected"
    users.update_one({"_id": target["_id"]}, {"$set": {"status": new_status}})
    record(f"registration_{new_status}", admin, target, f"Admin {new_status} registration")
    return {"message": f"Registration {new_status}", "status": new_status}


@app.get("/api/admin/activity")
def activity_log(limit: int = 100, admin=Depends(admin_user)):
    limit = max(1, min(limit, 500))
    return [{"id": str(a["_id"]), "action": a["action"], "actor_name": a["actor_name"],
             "actor_email": a["actor_email"], "target_email": a.get("target_email"),
             "detail": a.get("detail", ""), "created_at": a["created_at"].isoformat()}
            for a in activities.find().sort("created_at", -1).limit(limit)]


@app.get("/api/admin/ai-summary")
def ai_summary(admin=Depends(admin_user)):
    """A local, data-grounded starter summary; replace with an LLM provider if required."""
    pending = users.count_documents({"role": "user", "status": "pending"})
    approved = users.count_documents({"role": "user", "status": "approved"})
    recent = list(activities.find().sort("created_at", -1).limit(100))
    counts = {}
    for item in recent:
        counts[item["action"]] = counts.get(item["action"], 0) + 1
    common = max(counts, key=counts.get) if counts else None
    summary = f"There are {pending} registration request(s) awaiting review and {approved} approved user(s). "
    summary += f"The most common recorded action in the latest {len(recent)} events is {common.replace('_', ' ')} ({counts[common]})." if common else "No activity has been recorded yet."
    return {"summary": summary, "generated_at": now().isoformat(), "events_analyzed": len(recent)}
