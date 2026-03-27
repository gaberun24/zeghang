"""
ZEG Hang — Zalaegerszeg Közösségi Platform
Flask application with all routes.
"""

import os
import uuid
from datetime import datetime, timedelta
from functools import wraps

import bcrypt
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, send_from_directory,
)
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user,
)
from flask_wtf.csrf import CSRFProtect
from flask_session import Session
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

from lib.config import (
    FLASK_SECRET_KEY, FLASK_DEBUG, UPLOAD_DIR, MAX_UPLOAD_MB,
)
from lib.database import get_db, init_db
from lib.ai import (
    categorize_issue, check_duplicates, quick_categorize,
    CATEGORIES, URGENCY_LABELS,
)
from districts import DISTRICTS, guess_district

# ── App setup ──
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.secret_key = FLASK_SECRET_KEY

app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = "flask_sessions"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
app.config["WTF_CSRF_TIME_LIMIT"] = None

Session(app)
csrf = CSRFProtect(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Jelentkezz be a folytatáshoz."
login_manager.login_message_category = "error"


# ── User model ──
class DistrictInfo:
    def __init__(self, row):
        self.id = row["id"]
        self.number = row["number"]
        self.name = row["name"]
        self.representative_name = row["representative_name"]
        self.representative_party = row.get("representative_party", "")


class User(UserMixin):
    def __init__(self, row, district_row=None):
        self.id = row["id"]
        self.email = row["email"]
        self.display_name = row.get("display_name") or "Körzeti lakos"
        self.district_id = row["district_id"]
        self.district = DistrictInfo(district_row) if district_row else None


@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT u.*, d.id AS d_id, d.number, d.name AS d_name, "
            "d.representative_name, d.representative_party "
            "FROM users u LEFT JOIN districts d ON u.district_id = d.id "
            "WHERE u.id = %s AND u.is_active = TRUE",
            (int(user_id),)
        ).fetchone()
        if not row:
            return None
        district_row = {
            "id": row["d_id"], "number": row["number"], "name": row["d_name"],
            "representative_name": row["representative_name"],
            "representative_party": row["representative_party"],
        }
        return User(row, district_row)
    finally:
        conn.close()


# ── Security ──
def log_security(event_type, details="", ip=None):
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO security_log (event_type, ip_address, details) VALUES (%s, %s, %s)",
            (event_type, ip or request.remote_addr, details),
        )
        conn.commit()
    finally:
        conn.close()


def check_rate_limit(ip, event_type="login_fail", max_attempts=5, window_seconds=300):
    conn = get_db()
    try:
        cutoff = datetime.now() - timedelta(seconds=window_seconds)
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM security_log "
            "WHERE event_type = %s AND ip_address = %s AND created_at >= %s",
            (event_type, ip, cutoff),
        ).fetchone()
        return row["cnt"] >= max_attempts
    finally:
        conn.close()


@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# ── Helpers ──
def get_district_stats(district_id):
    """Get stats for sidebar."""
    conn = get_db()
    try:
        active = conn.execute(
            "SELECT COUNT(*) AS cnt FROM issues WHERE district_id = %s AND status != 'done'",
            (district_id,)
        ).fetchone()["cnt"]

        solved = conn.execute(
            "SELECT COUNT(*) AS cnt FROM issues WHERE district_id = %s AND status = 'done' "
            "AND resolved_at >= NOW() - INTERVAL '30 days'",
            (district_id,)
        ).fetchone()["cnt"]

        total_users = conn.execute(
            "SELECT COUNT(*) AS cnt FROM users WHERE district_id = %s AND is_active = TRUE",
            (district_id,)
        ).fetchone()["cnt"]

        voters = conn.execute(
            "SELECT COUNT(DISTINCT v.user_id) AS cnt FROM votes v "
            "JOIN users u ON v.user_id = u.id WHERE u.district_id = %s",
            (district_id,)
        ).fetchone()["cnt"]

        participation = round(voters / total_users * 100) if total_users > 0 else 0

        return {
            "active": active,
            "solved_30d": solved,
            "participation": participation,
            "avg_response": "—",
        }
    finally:
        conn.close()


def time_ago(dt):
    """Human readable time difference."""
    now = datetime.now()
    diff = now - dt
    if diff.days > 30:
        return f"{diff.days // 30} hónapja"
    if diff.days > 7:
        return f"{diff.days // 7} hete"
    if diff.days > 0:
        return f"{diff.days} napja"
    hours = diff.seconds // 3600
    if hours > 0:
        return f"{hours} órája"
    return "most"


def enrich_issues(rows, user_id=None):
    """Add computed fields to issue rows."""
    if not rows:
        return []

    issue_ids = [r["id"] for r in rows]
    enriched = []

    conn = get_db()
    try:
        # Get user votes for these issues
        user_votes = {}
        if user_id and issue_ids:
            placeholders = ",".join(["%s"] * len(issue_ids))
            vote_rows = conn.execute(
                f"SELECT issue_id, direction FROM votes WHERE user_id = %s AND issue_id IN ({placeholders})",
                [user_id] + issue_ids,
            ).fetchall()
            user_votes = {r["issue_id"]: r["direction"] for r in vote_rows}

        for r in rows:
            issue = dict(r.items())
            issue["user_vote"] = user_votes.get(r["id"], 0)
            issue["time_ago"] = time_ago(r["created_at"])
            issue["district_number"] = r.get("district_number", r.get("number", 0))
            issue["district_participation"] = None  # TODO: compute
            enriched.append(type("Issue", (), issue))

        return enriched
    finally:
        conn.close()


# ── Routes: Public ──
@app.route("/")
def index():
    conn = get_db()
    try:
        total_issues = conn.execute("SELECT COUNT(*) AS cnt FROM issues").fetchone()["cnt"]
        solved_issues = conn.execute("SELECT COUNT(*) AS cnt FROM issues WHERE status = 'done'").fetchone()["cnt"]
        total_users = conn.execute("SELECT COUNT(*) AS cnt FROM users WHERE is_active = TRUE").fetchone()["cnt"]

        recent = conn.execute(
            "SELECT i.*, d.number AS district_number FROM issues i "
            "JOIN districts d ON i.district_id = d.id "
            "ORDER BY i.created_at DESC LIMIT 3"
        ).fetchall()

        # District activity
        district_issues = {}
        district_activity = {}
        da_rows = conn.execute(
            "SELECT d.number, COUNT(i.id) AS cnt FROM districts d "
            "LEFT JOIN issues i ON i.district_id = d.id AND i.status != 'done' "
            "GROUP BY d.number"
        ).fetchall()
        max_count = max((r["cnt"] for r in da_rows), default=1) or 1
        for r in da_rows:
            district_issues[r["number"]] = r["cnt"]
            district_activity[r["number"]] = round(r["cnt"] / max_count * 100)

        return render_template("landing.html",
            total_issues=total_issues,
            solved_issues=solved_issues,
            total_users=total_users,
            recent_issues=recent,
            districts=DISTRICTS,
            district_issues=district_issues,
            district_activity=district_activity,
            category_labels=CATEGORIES,
        )
    finally:
        conn.close()


@app.route("/hogyan-mukodik")
def how_it_works():
    return render_template("how_it_works.html")


# ── Routes: Auth ──
@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        display_name = request.form.get("display_name", "").strip() or None
        address_street = request.form.get("address_street", "").strip()
        address_zip = request.form.get("address_zip", "").strip() or "8900"
        district_num = request.form.get("district_id", "")

        # Validation
        if not email or "@" not in email:
            flash("Érvényes email címet adj meg.", "error")
            return render_template("register.html", districts=DISTRICTS)

        if len(password) < 8:
            flash("A jelszónak legalább 8 karakter hosszúnak kell lennie.", "error")
            return render_template("register.html", districts=DISTRICTS)

        if password != password2:
            flash("A két jelszó nem egyezik.", "error")
            return render_template("register.html", districts=DISTRICTS)

        if not address_street:
            flash("A zalaegerszegi lakcím megadása kötelező.", "error")
            return render_template("register.html", districts=DISTRICTS)

        if not district_num:
            # Try auto-detect
            guessed = guess_district(address_street)
            if guessed:
                district_num = str(guessed)
            else:
                flash("Válaszd ki a körzetedet.", "error")
                return render_template("register.html", districts=DISTRICTS)

        conn = get_db()
        try:
            # Check duplicate email
            existing = conn.execute(
                "SELECT id FROM users WHERE email = %s", (email,)
            ).fetchone()
            if existing:
                flash("Ez az email cím már regisztrálva van.", "error")
                return render_template("register.html", districts=DISTRICTS)

            # Get district id
            district = conn.execute(
                "SELECT id FROM districts WHERE number = %s", (int(district_num),)
            ).fetchone()
            if not district:
                flash("Érvénytelen körzet.", "error")
                return render_template("register.html", districts=DISTRICTS)

            # Hash password
            pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

            conn.execute(
                "INSERT INTO users (email, password_hash, display_name, address_street, address_zip, district_id) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (email, pw_hash, display_name, address_street, address_zip, district["id"]),
            )
            conn.commit()

            log_security("register_ok", f"email={email}", request.remote_addr)
            flash("Sikeres regisztráció! Most már bejelentkezhetsz.", "success")
            return redirect(url_for("login"))
        except Exception:
            conn.rollback()
            flash("Hiba történt a regisztráció során.", "error")
            return render_template("register.html", districts=DISTRICTS)
        finally:
            conn.close()

    return render_template("register.html", districts=DISTRICTS)


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        ip = request.remote_addr
        if check_rate_limit(ip):
            flash("Túl sok sikertelen próbálkozás. Próbáld újra 5 perc múlva.", "error")
            return render_template("login.html")

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = get_db()
        try:
            row = conn.execute(
                "SELECT u.*, d.id AS d_id, d.number, d.name AS d_name, "
                "d.representative_name, d.representative_party "
                "FROM users u LEFT JOIN districts d ON u.district_id = d.id "
                "WHERE u.email = %s AND u.is_active = TRUE",
                (email,)
            ).fetchone()

            if row and bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
                district_row = {
                    "id": row["d_id"], "number": row["number"], "name": row["d_name"],
                    "representative_name": row["representative_name"],
                    "representative_party": row["representative_party"],
                }
                user = User(row, district_row)
                login_user(user, remember=True)
                log_security("login_ok", f"email={email}", ip)
                return redirect(url_for("dashboard"))
            else:
                log_security("login_fail", f"email={email}", ip)
                flash("Hibás email vagy jelszó.", "error")
        finally:
            conn.close()

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


# ── Routes: Dashboard ──
@app.route("/dashboard")
@login_required
def dashboard():
    tab = request.args.get("tab", "district")
    sort = request.args.get("sort", "votes")
    category_filter = request.args.get("category")

    # Sort SQL
    sort_sql = "i.vote_score DESC"
    if sort == "newest":
        sort_sql = "i.created_at DESC"
    elif sort == "urgency":
        sort_sql = "CASE i.ai_urgency WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, i.vote_score DESC"

    conn = get_db()
    try:
        # Build query
        where_clauses = []
        params = []

        if tab == "mine":
            where_clauses.append("i.user_id = %s")
            params.append(current_user.id)
        elif tab == "city":
            pass  # No filter
        else:
            where_clauses.append("i.district_id = %s")
            params.append(current_user.district_id)

        if category_filter and category_filter in CATEGORIES:
            where_clauses.append("i.category = %s")
            params.append(category_filter)

        where_sql = " AND ".join(where_clauses) if where_clauses else "TRUE"

        issues = conn.execute(
            f"SELECT i.*, d.number AS district_number FROM issues i "
            f"JOIN districts d ON i.district_id = d.id "
            f"WHERE {where_sql} ORDER BY {sort_sql} LIMIT 50",
            params,
        ).fetchall()

        enriched = enrich_issues(issues, current_user.id)

        # Trending (top 4 city-wide)
        trending = conn.execute(
            "SELECT i.title, i.vote_score, d.number AS district_number FROM issues i "
            "JOIN districts d ON i.district_id = d.id "
            "WHERE i.status != 'done' ORDER BY i.vote_score DESC LIMIT 4"
        ).fetchall()

        # District activity for bottom panel
        da_rows = conn.execute(
            "SELECT d.number, COUNT(CASE WHEN i.status != 'done' THEN 1 END) AS active "
            "FROM districts d LEFT JOIN issues i ON i.district_id = d.id "
            "GROUP BY d.number ORDER BY d.number"
        ).fetchall()
        max_active = max((r["active"] for r in da_rows), default=1) or 1
        district_activity_list = [
            type("DA", (), {"number": r["number"], "active": r["active"],
                            "percent": round(r["active"] / max_active * 100)})
            for r in da_rows
        ]

        stats = get_district_stats(current_user.district_id)

        return render_template("dashboard.html",
            issues=enriched,
            tab=tab,
            sort=sort,
            category_filter=category_filter,
            category_labels=CATEGORIES,
            urgency_labels=URGENCY_LABELS,
            trending=trending,
            district_activity_list=district_activity_list,
            stats=stats,
            active_page="dashboard" if tab != "mine" else "my_issues",
        )
    finally:
        conn.close()


# ── Routes: Issues ──
@app.route("/issue/new", methods=["POST"])
@login_required
def new_issue():
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    category = request.form.get("category", "other")
    location = request.form.get("location", "").strip() or None

    if not title or not description:
        return jsonify({"ok": False, "error": "Cím és leírás megadása kötelező."}), 400

    if category not in CATEGORIES:
        category = "other"

    conn = get_db()
    try:
        # AI processing
        ai_result = categorize_issue(title, description)
        ai_urgency = ai_result.get("urgency", "low")
        ai_cat = ai_result.get("category", category)

        # Check duplicates
        existing = conn.execute(
            "SELECT id, title, description FROM issues WHERE district_id = %s AND status != 'done' "
            "ORDER BY created_at DESC LIMIT 50",
            (current_user.district_id,)
        ).fetchall()
        existing_list = [{"id": r["id"], "title": r["title"], "description": r["description"]} for r in existing]
        dup_id = check_duplicates(title, description, existing_list)

        # Insert issue
        cur = conn.execute(
            "INSERT INTO issues (title, description, category, location, district_id, user_id, "
            "ai_urgency, ai_category_suggestion, ai_duplicate_of) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (title, description, category, location, current_user.district_id,
             current_user.id, ai_urgency, ai_cat, dup_id),
        )
        issue_row = cur.fetchone()
        issue_id = issue_row["id"]

        # Handle photo uploads
        photos = request.files.getlist("photos")
        for photo in photos:
            if photo and photo.filename:
                ext = os.path.splitext(photo.filename)[1].lower()
                if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                    filename = f"{uuid.uuid4().hex}{ext}"
                    os.makedirs(UPLOAD_DIR, exist_ok=True)
                    photo.save(os.path.join(UPLOAD_DIR, filename))
                    conn.execute(
                        "INSERT INTO issue_media (issue_id, filename, original_name, mime_type) "
                        "VALUES (%s, %s, %s, %s)",
                        (issue_id, filename, secure_filename(photo.filename), photo.content_type),
                    )

        conn.commit()
        return jsonify({"ok": True, "issue_id": issue_id})
    except Exception as e:
        conn.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()


@app.route("/issue/<int:issue_id>")
@login_required
def issue_detail(issue_id):
    conn = get_db()
    try:
        issue = conn.execute(
            "SELECT i.*, d.number AS district_number, "
            "COALESCE(u.display_name, 'Körzeti lakos') AS author_name "
            "FROM issues i "
            "JOIN districts d ON i.district_id = d.id "
            "JOIN users u ON i.user_id = u.id "
            "WHERE i.id = %s",
            (issue_id,)
        ).fetchone()

        if not issue:
            flash("Bejelentés nem található.", "error")
            return redirect(url_for("dashboard"))

        # User vote
        vote_row = conn.execute(
            "SELECT direction FROM votes WHERE issue_id = %s AND user_id = %s",
            (issue_id, current_user.id),
        ).fetchone()
        user_vote = vote_row["direction"] if vote_row else 0

        # Comments
        comments_raw = conn.execute(
            "SELECT c.*, COALESCE(u.display_name, 'Körzeti lakos') AS author_name "
            "FROM comments c JOIN users u ON c.user_id = u.id "
            "WHERE c.issue_id = %s ORDER BY c.created_at ASC",
            (issue_id,)
        ).fetchall()
        comments = []
        for c in comments_raw:
            comment = type("Comment", (), dict(c.items()))
            comment.time_ago = time_ago(c["created_at"])
            comments.append(comment)

        # Photos
        photos = conn.execute(
            "SELECT * FROM issue_media WHERE issue_id = %s", (issue_id,)
        ).fetchall()

        stats = get_district_stats(current_user.district_id)

        return render_template("issue_detail.html",
            issue=issue,
            user_vote=user_vote,
            comments=comments,
            photos=photos,
            category_labels=CATEGORIES,
            urgency_labels=URGENCY_LABELS,
            stats=stats,
            active_page="dashboard",
        )
    finally:
        conn.close()


@app.route("/issue/<int:issue_id>/vote", methods=["POST"])
@login_required
def vote_issue(issue_id):
    data = request.get_json()
    direction = data.get("direction", 0)
    if direction not in (1, -1):
        return jsonify({"ok": False}), 400

    conn = get_db()
    try:
        # Check existing vote
        existing = conn.execute(
            "SELECT id, direction FROM votes WHERE issue_id = %s AND user_id = %s",
            (issue_id, current_user.id),
        ).fetchone()

        if existing:
            if existing["direction"] == direction:
                # Toggle off
                conn.execute("DELETE FROM votes WHERE id = %s", (existing["id"],))
                user_vote = 0
            else:
                # Change direction
                conn.execute("UPDATE votes SET direction = %s WHERE id = %s", (direction, existing["id"]))
                user_vote = direction
        else:
            # New vote
            conn.execute(
                "INSERT INTO votes (issue_id, user_id, direction) VALUES (%s, %s, %s)",
                (issue_id, current_user.id, direction),
            )
            user_vote = direction

        # Update cached score
        score_row = conn.execute(
            "SELECT COALESCE(SUM(direction), 0) AS score FROM votes WHERE issue_id = %s",
            (issue_id,)
        ).fetchone()
        new_score = score_row["score"]
        conn.execute(
            "UPDATE issues SET vote_score = %s, updated_at = NOW() WHERE id = %s",
            (new_score, issue_id),
        )
        conn.commit()

        return jsonify({"ok": True, "vote_score": new_score, "user_vote": user_vote})
    except Exception:
        conn.rollback()
        return jsonify({"ok": False}), 500
    finally:
        conn.close()


@app.route("/issue/<int:issue_id>/comment", methods=["POST"])
@login_required
def add_comment(issue_id):
    data = request.get_json()
    content = data.get("content", "").strip()
    if not content:
        return jsonify({"ok": False, "error": "Üres hozzászólás."}), 400

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO comments (issue_id, user_id, content) VALUES (%s, %s, %s)",
            (issue_id, current_user.id, content),
        )
        conn.execute(
            "UPDATE issues SET comment_count = comment_count + 1, updated_at = NOW() WHERE id = %s",
            (issue_id,),
        )
        conn.commit()
        return jsonify({"ok": True})
    except Exception:
        conn.rollback()
        return jsonify({"ok": False}), 500
    finally:
        conn.close()


# ── Routes: API ──
@app.route("/api/ai-categorize", methods=["POST"])
@login_required
def api_ai_categorize():
    data = request.get_json()
    title = data.get("title", "")
    category = quick_categorize(title)
    return jsonify({"category": category})


@app.route("/api/check-district")
def api_check_district():
    street = request.args.get("street", "")
    district_num = guess_district(street)
    if district_num:
        d = next((d for d in DISTRICTS if d["number"] == district_num), None)
        return jsonify({"district": district_num, "name": d["name"] if d else ""})
    return jsonify({"district": None})


# ── Routes: File serving ──
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


# ── Init & Run ──
with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=FLASK_DEBUG)
