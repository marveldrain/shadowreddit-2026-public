#!/usr/bin/env python3
"""
ShadowReddit 2026 - Public Live Backend
FastAPI + SQLite | Zero bullshit | Production ready for Railway
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
import sqlite3
import hashlib
import secrets
from typing import Optional
import uvicorn

app = FastAPI(title="ShadowReddit 2026", version="2026.5")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "shadowreddit.db"

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        avatar TEXT,
        karma INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS subs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        display TEXT NOT NULL,
        description TEXT,
        members INTEGER DEFAULT 0,
        created_by TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sub TEXT NOT NULL,
        title TEXT NOT NULL,
        body TEXT,
        author TEXT NOT NULL,
        image TEXT,
        upvotes INTEGER DEFAULT 1,
        downvotes INTEGER DEFAULT 0,
        views INTEGER DEFAULT 0,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        author TEXT NOT NULL,
        body TEXT NOT NULL,
        upvotes INTEGER DEFAULT 0,
        downvotes INTEGER DEFAULT 0,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        expires_at TIMESTAMP NOT NULL
    )''')
    conn.commit()

    c.execute("SELECT COUNT(*) FROM subs")
    if c.fetchone()[0] == 0:
        default_subs = [
            ("underground", "r/underground", "The original shadow network. No rules. No limits.", 1240000),
            ("tech", "r/tech", "Bleeding edge hardware, exploits & zero-days", 987000),
            ("conspiracy", "r/conspiracy", "What they don't want you to know", 421000),
            ("blackhat", "r/blackhat", "Advanced persistent threats & red team ops", 178000),
            ("memes2026", "r/memes2026", "The freshest neural memes", 289000)
        ]
        for name, display, desc, members in default_subs:
            c.execute("INSERT INTO subs (name, display, description, members) VALUES (?, ?, ?, ?)", 
                     (name, display, desc, members))
        conn.commit()
    conn.close()

init_db()

class UserRegister(BaseModel):
    username: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class CreatePost(BaseModel):
    sub: str
    title: str
    body: Optional[str] = ""
    image: Optional[str] = None

class CreateComment(BaseModel):
    post_id: int
    body: str

class Vote(BaseModel):
    post_id: Optional[int] = None
    comment_id: Optional[int] = None
    is_upvote: bool

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.now() + timedelta(days=30)
    conn = get_db()
    conn.execute("INSERT INTO sessions (token, username, expires_at) VALUES (?, ?, ?)",
                 (token, username, expires))
    conn.commit()
    conn.close()
    return token

def get_current_user(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return None
    token = auth.split(" ")[1]
    conn = get_db()
    row = conn.execute("SELECT username FROM sessions WHERE token = ? AND expires_at > ?",
                       (token, datetime.now())).fetchone()
    conn.close()
    return row["username"] if row else None

@app.post("/api/register")
def register(user: UserRegister):
    conn = get_db()
    try:
        password_hash = hash_password(user.password)
        avatar = f"https://i.pravatar.cc/80?img={hash(user.username) % 70 + 1}"
        conn.execute("INSERT INTO users (username, password_hash, avatar) VALUES (?, ?, ?)",
                     (user.username, password_hash, avatar))
        conn.commit()
        token = create_session(user.username)
        return {"token": token, "username": user.username, "avatar": avatar}
    except sqlite3.IntegrityError:
        raise HTTPException(400, "Username already taken")
    finally:
        conn.close()

@app.post("/api/login")
def login(user: UserLogin):
    conn = get_db()
    row = conn.execute("SELECT password_hash, avatar FROM users WHERE username = ?",
                       (user.username,)).fetchone()
    if not row or row["password_hash"] != hash_password(user.password):
        raise HTTPException(401, "Invalid credentials")
    token = create_session(user.username)
    return {"token": token, "username": user.username, "avatar": row["avatar"]}
    conn.close()

@app.get("/api/me")
def me(request: Request):
    username = get_current_user(request)
    if not username:
        raise HTTPException(401, "Not logged in")
    conn = get_db()
    user = conn.execute("SELECT username, avatar, karma FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return dict(user)

@app.get("/api/subs")
def get_subs():
    conn = get_db()
    subs = conn.execute("SELECT * FROM subs ORDER BY members DESC").fetchall()
    conn.close()
    return [dict(s) for s in subs]

@app.post("/api/subs")
def create_sub(sub: dict, request: Request):
    username = get_current_user(request)
    if not username:
        raise HTTPException(401, "Login required")
    conn = get_db()
    try:
        conn.execute("INSERT INTO subs (name, display, description, created_by) VALUES (?, ?, ?, ?)",
                     (sub["name"], f"r/{sub['name']}", sub.get("description", ""), username))
        conn.commit()
        return {"success": True}
    except sqlite3.IntegrityError:
        raise HTTPException(400, "Sub already exists")
    finally:
        conn.close()

@app.get("/api/posts")
def get_posts(sub: Optional[str] = None, sort: str = "hot"):
    conn = get_db()
    query = "SELECT * FROM posts"
    params = []
    if sub and sub not in ["home", "popular"]:
        query += " WHERE sub = ?"
        params.append(sub)
    elif sub == "popular":
        query += " WHERE upvotes > 3000"
    if sort == "new":
        query += " ORDER BY timestamp DESC"
    elif sort == "top":
        query += " ORDER BY (upvotes - downvotes) DESC"
    else:
        query += " ORDER BY (upvotes - downvotes) * 0.85 + (julianday('now') - julianday(timestamp)) * -0.1 DESC"
    posts = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(p) for p in posts]

@app.post("/api/posts")
def create_post(post: CreatePost, request: Request):
    username = get_current_user(request)
    if not username:
        raise HTTPException(401, "Login required to post")
    conn = get_db()
    conn.execute("""INSERT INTO posts (sub, title, body, author, image, upvotes) 
                    VALUES (?, ?, ?, ?, ?, 1)""",
                 (post.sub, post.title, post.body or "", username, post.image))
    conn.commit()
    post_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return {"id": post_id, "success": True}

@app.post("/api/vote")
def vote(vote: Vote, request: Request):
    conn = get_db()
    if vote.post_id:
        if vote.is_upvote:
            conn.execute("UPDATE posts SET upvotes = upvotes + 1 WHERE id = ?", (vote.post_id,))
        else:
            conn.execute("UPDATE posts SET downvotes = downvotes + 1 WHERE id = ?", (vote.post_id,))
    elif vote.comment_id:
        if vote.is_upvote:
            conn.execute("UPDATE comments SET upvotes = upvotes + 1 WHERE id = ?", (vote.comment_id,))
        else:
            conn.execute("UPDATE comments SET downvotes = downvotes + 1 WHERE id = ?", (vote.comment_id,))
    conn.commit()
    conn.close()
    return {"success": True}

@app.get("/api/comments/{post_id}")
def get_comments(post_id: int):
    conn = get_db()
    comments = conn.execute("SELECT * FROM comments WHERE post_id = ? ORDER BY upvotes DESC", (post_id,)).fetchall()
    conn.close()
    return [dict(c) for c in comments]

@app.post("/api/comments")
def create_comment(comment: CreateComment, request: Request):
    username = get_current_user(request)
    if not username:
        raise HTTPException(401, "Login required to comment")
    conn = get_db()
    conn.execute("INSERT INTO comments (post_id, author, body, upvotes) VALUES (?, ?, ?, 1)",
                 (comment.post_id, username, comment.body))
    conn.commit()
    conn.close()
    return {"success": True}

@app.get("/api/stats")
def get_stats():
    conn = get_db()
    posts_count = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    users_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    comments_count = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    conn.close()
    return {"posts_today": posts_count, "active_operators": users_count, "comments": comments_count}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)