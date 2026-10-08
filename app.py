import csv
import io
import os
import sqlite3
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from functools import wraps
from typing import Optional

from flask import Flask, g, jsonify, make_response, request, session
from werkzeug.security import check_password_hash, generate_password_hash
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

DB_PATH = os.environ.get("DB_PATH", "aceest_fitness.db")

PROGRAM_TEMPLATES = {
    "Fat Loss": ["Full Body HIIT", "Circuit Training", "Cardio + Weights"],
    "Muscle Gain": ["Push/Pull/Legs", "Upper/Lower Split", "Full Body Strength"],
    "Beginner": ["Full Body 3x/week", "Light Strength + Mobility"],
}



def calculate_bmi(weight_kg: float, height_m: float) -> float:
    if weight_kg <= 0 or height_m <= 0:
        raise ValueError("weight_kg and height_m must be > 0")
    return round(weight_kg / (height_m ** 2), 2)


def bmi_category(bmi: float) -> str:
    if bmi < 18.5:
        return "Underweight"
    if bmi < 25:
        return "Normal"
    if bmi < 30:
        return "Overweight"
    return "Obese"


def calculate_daily_calories(weight_kg: float, height_cm: float, age: int, gender: str, activity: str) -> int:
    if weight_kg <= 0 or height_cm <= 0 or age <= 0:
        raise ValueError("weight, height and age must be positive")
    gender = gender.lower()
    if gender not in {"male", "female"}:
        raise ValueError("gender must be male or female")
    factors = {"sedentary": 1.2, "light": 1.375, "moderate": 1.55, "active": 1.725}
    if activity not in factors:
        raise ValueError("activity must be sedentary, light, moderate or active")
    bmr = (10 * weight_kg) + (6.25 * height_cm) - (5 * age) + (5 if gender == "male" else -161)
    return int(round(bmr * factors[activity]))


def now_text() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def svg_progress_chart(rows):
    width, height = 700, 360
    margin = 50
    values = [float(r["weight_kg"]) for r in rows if r["weight_kg"] is not None]
    labels = [str(r["recorded_at"])[:10] for r in rows if r["weight_kg"] is not None]
    root = ET.Element("svg", width=str(width), height=str(height), xmlns="http://www.w3.org/2000/svg")
    ET.SubElement(root, "rect", x="0", y="0", width=str(width), height=str(height), fill="white")
    ET.SubElement(root, "text", x="30", y="25").text = "ACEest Progress Chart - Weight (kg)"
    if not values:
        ET.SubElement(root, "text", x="50", y="180").text = "No progress data"
        return ET.tostring(root, encoding="unicode")
    ymin, ymax = min(values), max(values)
    if ymin == ymax:
        ymin -= 1
        ymax += 1
    plot_w = width - 2 * margin
    plot_h = height - 2 * margin
    points = []
    for i, value in enumerate(values):
        x = margin if len(values) == 1 else margin + (plot_w * i / (len(values) - 1))
        y = margin + plot_h * (ymax - value) / (ymax - ymin)
        points.append((x, y))
    ET.SubElement(root, "line", x1=str(margin), y1=str(height-margin), x2=str(width-margin), y2=str(height-margin), stroke="black")
    ET.SubElement(root, "line", x1=str(margin), y1=str(margin), x2=str(margin), y2=str(height-margin), stroke="black")
    ET.SubElement(root, "polyline", points=" ".join(f"{x:.1f},{y:.1f}" for x, y in points), fill="none", stroke="blue", **{"stroke-width": "2"})
    for (x, y), label, value in zip(points, labels, values):
        ET.SubElement(root, "circle", cx=f"{x:.1f}", cy=f"{y:.1f}", r="4", fill="blue")
        ET.SubElement(root, "text", x=f"{x:.1f}", y=f"{y-8:.1f}", **{"text-anchor": "middle"}).text = str(value)
        ET.SubElement(root, "text", x=f"{x:.1f}", y=str(height-20), **{"text-anchor": "middle"}).text = label
    return ET.tostring(root, encoding="unicode")


def create_app(db_path: Optional[str] = None) -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path or DB_PATH
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-this-key")

    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DB_PATH"])
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_db(exception=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def init_db():
        db = sqlite3.connect(app.config["DB_PATH"])
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                age INTEGER,
                gender TEXT,
                height_cm REAL,
                weight_kg REAL,
                goal TEXT,
                membership_status TEXT DEFAULT 'Active',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS programs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_name TEXT NOT NULL,
                program_type TEXT NOT NULL,
                details TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS exercises (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                muscle_group TEXT,
                equipment TEXT
            );
            CREATE TABLE IF NOT EXISTS workouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_name TEXT NOT NULL,
                exercise_name TEXT NOT NULL,
                date TEXT NOT NULL,
                duration_min INTEGER DEFAULT 30,
                calories_burned INTEGER DEFAULT 0,
                notes TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_name TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                weight_kg REAL,
                body_fat_pct REAL,
                chest_cm REAL,
                waist_cm REAL,
                hip_cm REAL,
                notes TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_name TEXT NOT NULL,
                goal_type TEXT NOT NULL,
                target_value REAL,
                target_date TEXT,
                status TEXT DEFAULT 'Active'
            );
            CREATE TABLE IF NOT EXISTS progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_name TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                weight_kg REAL,
                note TEXT DEFAULT ''
            );
            """
        )
        defaults = [
            ("admin", generate_password_hash("admin123"), "admin"),
            ("trainer", generate_password_hash("trainer123"), "trainer"),
        ]
        for username, password_hash, role in defaults:
            db.execute("INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?, ?, ?)", (username, password_hash, role))
        db.commit()
        db.close()

    def error(message, status):
        return jsonify(error=message), status

    def require_role(*roles):
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                if session.get("role") not in roles:
                    return error("login with an allowed role is required", 403)
                return func(*args, **kwargs)
            return wrapper
        return decorator


    def client_exists(db, name):
        return db.execute("SELECT name FROM clients WHERE name = ?", (name,)).fetchone() is not None

    @app.get("/")
    def home():
        return jsonify(service="ACEest Fitness & Gym API", status="running", version="1.0")

    @app.get("/health")
    def health():
        return jsonify(status="ok"), 200

    @app.post("/login")
    def login():
        data = request.get_json(silent=True) or {}
        username, password = data.get("username"), data.get("password")
        if not username or not password:
            return error("username and password are required", 400)
        db = get_db()
        row = db.execute("SELECT username, password_hash, role FROM users WHERE username = ?", (username,)).fetchone()
        if row is None or not check_password_hash(row["password_hash"], password):
            return error("invalid credentials", 401)
        session.clear()
        session["username"] = row["username"]
        session["role"] = row["role"]
        return jsonify(username=row["username"], role=row["role"], message="login successful"), 200

    @app.post("/logout")
    def logout():
        session.clear()
        return jsonify(message="logout successful"), 200

    @app.post("/clients")
    def add_client():
        data = request.get_json(silent=True) or {}
        name = data.get("name")
        if not name:
            return error("name is required", 400)
        db = get_db()
        try:
            db.execute(
                "INSERT INTO clients (name, age, gender, height_cm, weight_kg, goal, membership_status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'Active', ?)",
                (name, data.get("age"), data.get("gender"), data.get("height_cm"), data.get("weight_kg"), data.get("goal"), now_text()),
            )
            db.commit()
        except sqlite3.IntegrityError:
            return error(f"client '{name}' already exists", 409)
        return jsonify(message=f"client '{name}' created"), 201

    @app.get("/clients")
    def list_clients():
        rows = get_db().execute("SELECT * FROM clients ORDER BY name").fetchall()
        return jsonify([dict(r) for r in rows]), 200

    @app.get("/clients/<name>")
    def get_client(name):
        row = get_db().execute("SELECT * FROM clients WHERE name = ?", (name,)).fetchone()
        if row is None:
            return error("client not found", 404)
        return jsonify(dict(row)), 200

    @app.delete("/clients/<name>")
    @require_role("admin", "trainer")
    def delete_client(name):
        db = get_db()
        row = db.execute("SELECT id FROM clients WHERE name = ?", (name,)).fetchone()
        if row is None:
            return error("client not found", 404)
        db.execute("DELETE FROM clients WHERE name = ?", (name,))
        db.commit()
        return jsonify(message="client deleted"), 200

    init_db()
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
