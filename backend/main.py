"""
fixAI Backend — FastAPI + SQLite + Groq
============================================
Install:
    pip install fastapi uvicorn "python-jose[cryptography]" bcrypt groq python-multipart

Run:
    uvicorn main:app --reload --port 8000
"""
from dotenv import load_dotenv 
import os
import sqlite3
import bcrypt
from datetime import datetime, timedelta
from typing import Optional, List
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, validator
from pydantic import BaseModel
from jose import JWTError, jwt
from groq import Groq
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# This tells Python to look in the exact same folder as this main.py file
backend_folder = os.path.dirname(__file__)
dotenv_path = os.path.join(backend_folder, '.env')

# Explicitly load it from that exact path
load_dotenv(dotenv_path=dotenv_path)

# ─────────────────────────────────────────────────────────
# CONFIG  ← edit these two lines
# ─────────────────────────────────────────────────────────
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")    
SECRET_KEY   = os.environ.get("SECRET_KEY") 


GROQ_MODEL   = "llama-3.3-70b-versatile"
SYSTEM_PROMPT = (
    "You are fixAI, a helpful, concise, and knowledgeable AI assistant. "
    "Be direct and clear. Format code with markdown code fences."
)
ALGORITHM    = "HS256"
TOKEN_EXPIRE = 60 * 24 * 7   # 7 days in minutes
DB_PATH      = "fixAI.db"

# ─────────────────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────────────────
app = FastAPI(title="fixAI API", version="1.0.0")

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="../frontend"), name="static")

@app.get("/")
def serve_frontend():
    return FileResponse("../frontend/index.html")


oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/login")

# Groq client — only initialised when key is set
def get_groq():
    if not GROQ_API_KEY:
        raise HTTPException(502, "Groq API key not configured in main.py")
    return Groq(api_key=GROQ_API_KEY)

# ─────────────────────────────────────────────────────────
# DATABASE  (one persistent connection per request)
# ─────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.commit()
        conn.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            username   TEXT    UNIQUE NOT NULL COLLATE NOCASE,
            email      TEXT    UNIQUE NOT NULL COLLATE NOCASE,
            password   TEXT    NOT NULL,
            created_at TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS conversations (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title      TEXT    NOT NULL DEFAULT 'New Conversation',
            created_at TEXT    DEFAULT (datetime('now')),
            updated_at TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role            TEXT    NOT NULL,
            content         TEXT    NOT NULL,
            created_at      TEXT    DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()
    print("Database initialised")

init_db()

# ─────────────────────────────────────────────────────────
# PASSWORD HELPERS  (plain bcrypt — no passlib)
# ─────────────────────────────────────────────────────────
def hash_password(plain: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(plain.encode("utf-8"), salt)
    return hashed.decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception as e:
        print(f"Password verify error: {e}")
        return False

# ─────────────────────────────────────────────────────────
# JWT HELPERS
# ─────────────────────────────────────────────────────────
def create_token(username: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=TOKEN_EXPIRE)
    return jwt.encode({"sub": username, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2), db: sqlite3.Connection = Depends(get_db)):
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if not username:
            raise exc
    except JWTError:
        raise exc
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not row:
        raise exc
    return dict(row)

# ─────────────────────────────────────────────────────────
# SCHEMAS
# ─────────────────────────────────────────────────────────
class UserRegister(BaseModel):
    username: str
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class ConversationCreate(BaseModel):
    title: Optional[str] = "New Conversation"

class ChatRequest(BaseModel):
    message: str

    @validator('message')
    def message_length(cls, v):
        if len(v) > 4000:
            raise ValueError('Message too long')
        return v

# ─────────────────────────────────────────────────────────
# AUTH ROUTES
# ─────────────────────────────────────────────────────────
@app.post("/auth/register", status_code=201)
def register(body: UserRegister, db: sqlite3.Connection = Depends(get_db)):
    body.username = body.username.strip()
    body.email    = body.email.strip().lower()

    if len(body.username) < 3:
        raise HTTPException(400, "Username must be at least 3 characters")
    if len(body.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    if db.execute("SELECT 1 FROM users WHERE username = ?", (body.username,)).fetchone():
        raise HTTPException(400, "Username already taken")
    if db.execute("SELECT 1 FROM users WHERE email = ?", (body.email,)).fetchone():
        raise HTTPException(400, "Email already registered")

    hashed = hash_password(body.password)
    db.execute(
        "INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
        (body.username, body.email, hashed)
    )
    db.commit()
    print(f"Registered user: {body.username}")
    return {"message": "Account created successfully"}


@app.post("/auth/login", response_model=Token)
@limiter.limit("5/minute")
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: sqlite3.Connection = Depends(get_db)):
    username = form.username.strip()
    row = db.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()

    if not row:
        print(f"Login failed — user not found: {username}")
        raise HTTPException(400, "Invalid username or password")

    if not verify_password(form.password, row["password"]):
        print(f"Login failed — wrong password for: {username}")
        raise HTTPException(400, "Invalid username or password")

    token = create_token(row["username"])
    print(f"Logged in: {username}")
    return {"access_token": token, "token_type": "bearer"}


@app.get("/auth/me")
def me(user=Depends(get_current_user)):
    return {"id": user["id"], "username": user["username"], "email": user["email"]}

# ─────────────────────────────────────────────────────────
# CONVERSATION ROUTES
# ─────────────────────────────────────────────────────────
@app.get("/conversations")
def list_conversations(user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute(
        "SELECT id, title, created_at, updated_at FROM conversations "
        "WHERE user_id = ? ORDER BY updated_at DESC LIMIT 100",
        (user["id"],)
    ).fetchall()
    return [dict(r) for r in rows]


@app.post("/conversations", status_code=201)
def create_conversation(body: ConversationCreate, user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    cur = db.execute(
        "INSERT INTO conversations (user_id, title) VALUES (?, ?)",
        (user["id"], body.title or "New Conversation")
    )
    db.commit()
    row = db.execute("SELECT * FROM conversations WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


@app.delete("/conversations/{conv_id}", status_code=204)
def delete_conversation(conv_id: int, user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT 1 FROM conversations WHERE id = ? AND user_id = ?", (conv_id, user["id"])).fetchone()
    if not row:
        raise HTTPException(404, "Not found")
    db.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
    db.commit()


@app.get("/conversations/{conv_id}/messages")
def get_messages(conv_id: int, user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT 1 FROM conversations WHERE id = ? AND user_id = ?", (conv_id, user["id"])).fetchone()
    if not row:
        raise HTTPException(404, "Not found")
    msgs = db.execute(
        "SELECT id, role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY id ASC",
        (conv_id,)
    ).fetchall()
    return [dict(m) for m in msgs]

# ─────────────────────────────────────────────────────────
# CHAT ROUTE
# ─────────────────────────────────────────────────────────
@app.post("/conversations/{conv_id}/chat")
def chat(conv_id: int, body: ChatRequest, user=Depends(get_current_user), db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT * FROM conversations WHERE id = ? AND user_id = ?", (conv_id, user["id"])).fetchone()
    if not row:
        raise HTTPException(404, "Conversation not found")

    history = db.execute(
        "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id ASC LIMIT 40",
        (conv_id,)
    ).fetchall()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += [{"role": r["role"], "content": r["content"]} for r in history]
    messages.append({"role": "user", "content": body.message})

    try:
        groq = get_groq()
        completion = groq.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            max_tokens=2048,
            temperature=0.7,
        )
        reply = completion.choices[0].message.content
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Groq error: {str(e)}")

    db.execute(
        "INSERT INTO messages (conversation_id, role, content) VALUES (?, 'user', ?)",
        (conv_id, body.message)
    )
    db.execute(
        "INSERT INTO messages (conversation_id, role, content) VALUES (?, 'assistant', ?)",
        (conv_id, reply)
    )
    db.execute("UPDATE conversations SET updated_at = datetime('now') WHERE id = ?", (conv_id,))
    db.commit()

    return {"response": reply, "conversation_id": conv_id}


# ─────────────────────────────────────────────────────────
# HEALTH
# ─────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "model": GROQ_MODEL}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
