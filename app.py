
import os
import json
import base64
import io
import sqlite3
import secrets
from datetime import datetime, timezone
from functools import wraps

import numpy as np
import face_recognition

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("FACEGUARD_SECRET", secrets.token_hex(32))

DB = "faceguard.db"


# ---------------- DATABASE ----------------

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                face_encoding TEXT,
                created_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                event TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)


def log_event(user_id, event):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO events (user_id, event, created_at) VALUES (?, ?, ?)",
            (
                user_id,
                event,
                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            )
        )


# ---------------- AUTHENTICATION ----------------

def login_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if not session.get("uid"):
            return redirect(url_for("login"))

        if not session.get("face_verified"):
            session.pop("uid", None)
            return redirect(url_for("login"))

        return function(*args, **kwargs)
    return wrapper


# ---------------- HOME ----------------

@app.route("/")
def index():
    if session.get("uid"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


# ---------------- REGISTRATION ----------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        face_image = request.form.get("face_image", "")

        if not name or not email or len(password) < 8 or not face_image:
            flash(
                "Fill in all fields, capture your face, "
                "and use a password of at least 8 characters.",
                "error"
            )
            return render_template("register.html")

        try:
            raw = base64.b64decode(face_image.split(",", 1)[1])

            image = face_recognition.load_image_file(
                io.BytesIO(raw)
            )

            encodings = face_recognition.face_encodings(image)

            if len(encodings) != 1:
                flash(
                    "Please capture a clear image with exactly one face.",
                    "error"
                )
                return render_template("register.html")

            face_encoding = json.dumps(encodings[0].tolist())

            with get_db() as conn:
                cursor = conn.execute("""
                    INSERT INTO users
                    (name, email, password_hash, face_encoding, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    name,
                    email,
                    generate_password_hash(password),
                    face_encoding,
                    datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                ))
                user_id = cursor.lastrowid

            log_event(user_id, "Account created")
            flash("Account created successfully! Please sign in.", "success")
            return redirect(url_for("login"))

        except sqlite3.IntegrityError:
            flash("This email is already registered.", "error")

        except Exception:
            app.logger.exception("Registration error")
            flash("Unable to process your face image. Try again.", "error")

    return render_template("register.html")


# ---------------- PASSWORD LOGIN ----------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        with get_db() as conn:
            user = conn.execute(
                "SELECT * FROM users WHERE email = ?",
                (email,)
            ).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["pending_uid"] = user["id"]

            return render_template(
                "face_check.html",
                email=email
            )

        flash("Incorrect email or password.", "error")

    return render_template("login.html")


# ---------------- FACE VERIFICATION ----------------

@app.route("/verify-face", methods=["POST"])
def verify_face():
    user_id = session.get("pending_uid")

    if not user_id:
        return jsonify(
            ok=False,
            message="Please sign in again."
        ), 401

    try:
        data = request.get_json(silent=True) or {}
        image_data = data.get("image", "")

        if not image_data.startswith("data:image/"):
            return jsonify(
                ok=False,
                message="Invalid image."
            ), 400

        raw = base64.b64decode(
            image_data.split(",", 1)[1],
            validate=True
        )

        image = face_recognition.load_image_file(
            io.BytesIO(raw)
        )

        captured_encodings = face_recognition.face_encodings(image)

        with get_db() as conn:
            user = conn.execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,)
            ).fetchone()

        if not user or not user["face_encoding"]:
            log_event(user_id, "Face verification failed")
            return jsonify(
                ok=False,
                message="No enrolled face found."
            )

        if len(captured_encodings) != 1:
            log_event(user_id, "Face verification failed")
            return jsonify(
                ok=False,
                message="Please show exactly one clear face."
            )

        enrolled_encoding = np.array(
            json.loads(user["face_encoding"])
        )

        distance = float(
            face_recognition.face_distance(
                [enrolled_encoding],
                captured_encodings[0]
            )[0]
        )

        # Demonstration threshold only.
        # Must be validated before real-world use.
        threshold = 0.48

        if distance < threshold:
            session.clear()
            session["uid"] = user_id
            session["face_verified"] = True


            log_event(user_id, "Face verification successful")

            return jsonify(
                ok=True,
                message="Identity verified!",
                redirect=url_for("dashboard")
            )

        log_event(user_id, "Face verification failed")

        return jsonify(
            ok=False,
            message="Face did not match. Please try again."
        )

    except Exception:
        app.logger.exception("Face verification error")
        return jsonify(
            ok=False,
            message="Unable to verify the image. Try again."
        ), 400


# ---------------- DASHBOARD ----------------

@app.route("/dashboard")
@login_required
def dashboard():
    user_id = session["uid"]

    with get_db() as conn:
        user = conn.execute(
            "SELECT name, email, created_at FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()

        events = conn.execute("""
            SELECT event, created_at
            FROM events
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 8
        """, (user_id,)).fetchall()

        total = conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE user_id = ?",
            (user_id,)
        ).fetchone()["n"]

    return render_template(
        "dashboard.html",
        user=user,
        events=events,
        total=total
    )


# ---------------- LOGOUT ----------------

@app.route("/logout", methods=["POST"])
def logout():
    user_id = session.get("uid")

    if user_id:
        log_event(user_id, "Signed out")

    session.clear()
    return redirect(url_for("login"))


# ---------------- RUN APP ----------------

if __name__ == "__main__":
    init_db()

    # Local development only.
    # Never use Flask debug mode on a public deployment.
    app.run(debug=True)