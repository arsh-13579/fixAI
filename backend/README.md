# fixAI — AI Chatbot

A full-stack AI chatbot with a polished dark UI, JWT auth, conversation history, and Groq LLM.

---

## Stack
| Layer    | Tech                             |
|----------|----------------------------------|
| Frontend | HTML + CSS + Vanilla JS          |
| Backend  | Python FastAPI                   |
| Database | SQLite (file: `fixAI.db`)   |
| AI       | Groq — `llama-3.3-70b-versatile` |

---

## Project Structure
```
AI-chatbot/
├── backend/
│   ├── main.py
│   ├── .env              ← create this yourself (never shared)
│   ├── .env.example      ← template showing required keys
│   ├── requirements.txt
│   └── fixAI.db     ← auto-created on first run
└── frontend/
    └── index.html
```

---

## Quick Start

### 1. Clone the repository
```bash
git clone https://github.com/yourusername/fixai.git
cd fixai
```

### 2. Install Python dependencies
```bash
cd backend
pip install -r requirements.txt
```

### 3. Set up environment variables
```bash
copy .env.example .env
```
Open `.env` and fill in your values:
```
GROQ_API_KEY=your_groq_api_key_here
SECRET_KEY=your_long_random_secret_here
```

Get a free Groq API key at: https://console.groq.com

Generate a secret key with:
```bash
python -c "import secrets; print(secrets.token_hex(64))"
```

### 4. Run the backend
```bash
uvicorn main:app --reload --port 8000
```

### 5. Open the frontend
Visit: **http://localhost:8000**

That's it — no separate frontend server needed!

---

## Features
- **Auth** — Register / Login with bcrypt passwords & JWT tokens (7-day expiry)
- **Conversations** — Create, switch, and delete chat threads (stored per user)
- **History** — Full message history loaded per conversation, sent to Groq for context
- **Responsive** — Sidebar collapses on mobile with hamburger menu
- **Markdown** — Code blocks, bold, italic rendered in AI replies

---

## API Endpoints
| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/register` | Register new user |
| POST | `/auth/login` | Login → JWT token |
| GET  | `/auth/me` | Current user info |
| GET  | `/conversations` | List user's conversations |
| POST | `/conversations` | Create conversation |
| DELETE | `/conversations/{id}` | Delete conversation |
| GET  | `/conversations/{id}/messages` | Get messages |
| POST | `/conversations/{id}/chat` | Send message → Groq reply |
| GET  | `/health` | Health check |

---

## Model
Uses `llama-3.3-70b-versatile` via Groq (fast, free tier available).
To change model, edit `GROQ_MODEL` in `main.py`. Other options:
- `llama-3.1-8b-instant` (faster, smaller)
- `mixtral-8x7b-32768` (large context)

---

## Environment Variables
| Variable | Description |
|----------|-------------|
| `GROQ_API_KEY` | Your Groq API key from console.groq.com |
| `SECRET_KEY` | Random string used to sign JWT tokens |
