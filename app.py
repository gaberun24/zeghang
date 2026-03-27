"""
Zalaegerszeg Hangja — Közösségi Platform
Flask application with all routes.
"""

import hashlib
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
from lib.moderation import censor_text
from lib.notifications import notify_vote, notify_comment, notify_status_change
from lib.config import VAPID_PUBLIC_KEY
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

# ── Jinja2 filters ──
app.jinja_env.filters["censor"] = censor_text


# ── User model ──
class DistrictInfo:
    def __init__(self, row):
        self.id = row["id"]
        self.number = row["number"]
        self.name = row["name"]
        self.representative_name = row["representative_name"]
        self.representative_party = row.get("representative_party", "")


REPUTATION_LEVELS = [
    (0, "Újonc", "🌱"),
    (10, "Figyelő", "👀"),
    (30, "Aktív polgár", "🏘️"),
    (75, "Közösségi hang", "📢"),
    (150, "Körzeti hős", "🦸"),
    (300, "Városi legenda", "🏆"),
]


def get_reputation_level(points):
    """Return (name, icon) for a given reputation score."""
    level_name, level_icon = REPUTATION_LEVELS[0][1], REPUTATION_LEVELS[0][2]
    for threshold, name, icon in REPUTATION_LEVELS:
        if points >= threshold:
            level_name, level_icon = name, icon
    return level_name, level_icon


class User(UserMixin):
    def __init__(self, row, district_row=None):
        self.id = row["id"]
        self.email = row["email"]
        self.display_name = row.get("display_name") or "Körzeti lakos"
        self.district_id = row["district_id"]
        self.is_admin = row.get("is_admin", False)
        self.reputation = row.get("reputation", 0) or 0
        self.address_changed_at = row.get("address_changed_at")
        self.notify_votes = row.get("notify_votes", True) if row.get("notify_votes") is not None else True
        self.notify_comments = row.get("notify_comments", True) if row.get("notify_comments") is not None else True
        self.notify_status = row.get("notify_status", True) if row.get("notify_status") is not None else True
        self.push_subscription = row.get("push_subscription")
        self.district = DistrictInfo(district_row) if district_row else None

    @property
    def rep_level(self):
        return get_reputation_level(self.reputation)

    @property
    def rep_level_name(self):
        return self.rep_level[0]

    @property
    def rep_level_icon(self):
        return self.rep_level[1]

    @property
    def next_level_info(self):
        """Return (next_name, points_needed) or None if max level."""
        for threshold, name, icon in REPUTATION_LEVELS:
            if self.reputation < threshold:
                return name, threshold - self.reputation
        return None


def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            flash("Nincs jogosultságod ehhez az oldalhoz.", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT u.*, d.id AS d_id, d.number, d.name AS d_name, "
            "d.representative_name, d.representative_party, "
            "COALESCE(("
            "  SELECT SUM(CASE WHEN v.direction = 1 THEN 2 WHEN v.direction = -1 THEN -1 ELSE 0 END) "
            "  FROM votes v JOIN issues i ON v.issue_id = i.id WHERE i.user_id = u.id"
            "), 0) + COALESCE(("
            "  SELECT COUNT(*) FROM comments c WHERE c.user_id = u.id AND c.is_hidden = FALSE"
            "), 0) + COALESCE(("
            "  SELECT COUNT(*) * 5 FROM issues i WHERE i.user_id = u.id AND i.status = 'done'"
            "), 0) AS reputation "
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


@app.route("/hasznalati-utmutato")
def user_guide():
    return render_template("guide.html")


@app.route("/adatvedelem")
def privacy():
    return render_template("privacy.html")


@app.route("/aszf")
def terms():
    return render_template("terms.html")


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
        if not request.form.get("accept_terms"):
            flash("Az ÁSZF és az Adatvédelmi tájékoztató elfogadása kötelező.", "error")
            return render_template("register.html", districts=DISTRICTS)

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

            # Hash address (irreversible — only district_id is needed after this)
            address_hash = hashlib.sha256(
                (address_street.lower() + ":" + address_zip).encode()
            ).hexdigest()

            conn.execute(
                "INSERT INTO users (email, password_hash, display_name, address_street, address_zip, district_id) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (email, pw_hash, display_name, address_hash, "", district["id"]),
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


# ── Routes: Settings ──
@app.route("/settings", methods=["GET", "POST"])
@login_required
def user_settings():
    conn = get_db()
    try:
        if request.method == "POST":
            action = request.form.get("action")

            if action == "notifications":
                notify_votes = request.form.get("notify_votes") == "on"
                notify_comments = request.form.get("notify_comments") == "on"
                notify_status = request.form.get("notify_status") == "on"
                conn.execute(
                    "UPDATE users SET notify_votes = %s, notify_comments = %s, notify_status = %s "
                    "WHERE id = %s",
                    (notify_votes, notify_comments, notify_status, current_user.id),
                )
                conn.commit()
                flash("Értesítési beállítások mentve.", "success")

            elif action == "display_name":
                new_name = request.form.get("display_name", "").strip()
                if new_name and len(new_name) <= 100:
                    conn.execute(
                        "UPDATE users SET display_name = %s WHERE id = %s",
                        (new_name, current_user.id),
                    )
                    conn.commit()
                    flash("Megjelenítési név frissítve.", "success")

            elif action == "change_address":
                new_street = request.form.get("address_street", "").strip()
                new_district = request.form.get("district_id", "")
                if not new_street or not new_district:
                    flash("Kérlek add meg az új címet és körzetet.", "error")
                    return redirect(url_for("user_settings"))

                # Check if address was changed in the last year
                user_row = conn.execute(
                    "SELECT address_changed_at FROM users WHERE id = %s",
                    (current_user.id,),
                ).fetchone()
                last_change = user_row["address_changed_at"] if user_row else None
                if last_change and (datetime.now() - last_change).days < 365:
                    days_left = 365 - (datetime.now() - last_change).days
                    flash(f"Címet évente csak egyszer módosíthatod. Következő lehetőség: {days_left} nap múlva.", "error")
                    return redirect(url_for("user_settings"))

                # Find district
                district = conn.execute(
                    "SELECT id FROM districts WHERE number = %s", (int(new_district),)
                ).fetchone()
                if not district:
                    flash("Érvénytelen körzet.", "error")
                    return redirect(url_for("user_settings"))

                address_hash = hashlib.sha256(new_street.lower().encode()).hexdigest()
                conn.execute(
                    "UPDATE users SET address_street = %s, district_id = %s, address_changed_at = NOW() "
                    "WHERE id = %s",
                    (address_hash, district["id"], current_user.id),
                )
                conn.commit()
                log_security("address_change", f"user={current_user.id}", request.remote_addr)
                flash("Lakcím és körzet sikeresen módosítva.", "success")

            elif action == "change_password":
                old_pw = request.form.get("old_password", "")
                new_pw = request.form.get("new_password", "")
                new_pw2 = request.form.get("new_password2", "")
                if not old_pw or not new_pw:
                    flash("Kérlek töltsd ki a jelszó mezőket.", "error")
                    return redirect(url_for("user_settings"))
                if new_pw != new_pw2:
                    flash("Az új jelszavak nem egyeznek.", "error")
                    return redirect(url_for("user_settings"))
                if len(new_pw) < 8:
                    flash("Az új jelszó legalább 8 karakter legyen.", "error")
                    return redirect(url_for("user_settings"))

                user_row = conn.execute(
                    "SELECT password_hash FROM users WHERE id = %s", (current_user.id,)
                ).fetchone()
                if not bcrypt.checkpw(old_pw.encode(), user_row["password_hash"].encode()):
                    flash("A jelenlegi jelszó nem helyes.", "error")
                    return redirect(url_for("user_settings"))

                new_hash = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt()).decode()
                conn.execute(
                    "UPDATE users SET password_hash = %s WHERE id = %s",
                    (new_hash, current_user.id),
                )
                conn.commit()
                flash("Jelszó sikeresen megváltoztatva.", "success")

            return redirect(url_for("user_settings"))

        # GET — load user data
        user_row = conn.execute(
            "SELECT display_name, address_changed_at, notify_votes, notify_comments, notify_status "
            "FROM users WHERE id = %s",
            (current_user.id,),
        ).fetchone()

        can_change_address = True
        days_until_change = 0
        if user_row["address_changed_at"]:
            days_since = (datetime.now() - user_row["address_changed_at"]).days
            if days_since < 365:
                can_change_address = False
                days_until_change = 365 - days_since

        stats = get_district_stats(current_user.district_id)

        return render_template("settings.html",
            user_row=user_row,
            can_change_address=can_change_address,
            days_until_change=days_until_change,
            districts=DISTRICTS,
            stats=stats,
            active_page="settings",
            vapid_public_key=VAPID_PUBLIC_KEY,
        )
    finally:
        conn.close()


@app.route("/api/push-subscribe", methods=["POST"])
@login_required
def push_subscribe():
    data = request.get_json()
    subscription = data.get("subscription")
    if not subscription:
        return jsonify({"ok": False}), 400
    conn = get_db()
    try:
        import json
        conn.execute(
            "UPDATE users SET push_subscription = %s WHERE id = %s",
            (json.dumps(subscription), current_user.id),
        )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@app.route("/api/push-unsubscribe", methods=["POST"])
@login_required
def push_unsubscribe():
    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET push_subscription = NULL WHERE id = %s",
            (current_user.id,),
        )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


# ── Routes: Dashboard ──
@app.route("/dashboard")
@login_required
def dashboard():
    tab = request.args.get("tab", "district")
    sort = request.args.get("sort", "votes")
    category_filter = request.args.get("category")

    # Sort SQL — weighted vote score: vote_score * (median_pop / district_pop)
    # This equalizes districts so larger ones don't dominate
    weighted_score = (
        "i.vote_score * (SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY population) "
        "FROM districts WHERE population > 0) / GREATEST(d.population, 1)"
    )
    sort_sql = f"{weighted_score} DESC"
    if sort == "newest":
        sort_sql = "i.created_at DESC"
    elif sort == "urgency":
        sort_sql = f"CASE i.ai_urgency WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, {weighted_score} DESC"

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

        where_clauses.append("i.is_hidden = FALSE")
        where_sql = " AND ".join(where_clauses) if where_clauses else "TRUE"

        issues = conn.execute(
            f"SELECT i.*, d.number AS district_number FROM issues i "
            f"JOIN districts d ON i.district_id = d.id "
            f"WHERE {where_sql} ORDER BY {sort_sql} LIMIT 50",
            params,
        ).fetchall()

        enriched = enrich_issues(issues, current_user.id)

        # Trending (top 4 city-wide, weighted by population)
        trending = conn.execute(
            "SELECT i.title, i.vote_score, d.number AS district_number FROM issues i "
            "JOIN districts d ON i.district_id = d.id "
            "WHERE i.status != 'done' ORDER BY i.vote_score * "
            "(SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY population) "
            "FROM districts WHERE population > 0) / GREATEST(d.population, 1) DESC LIMIT 4"
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
    lat = request.form.get("lat", type=float)
    lng = request.form.get("lng", type=float)

    if not title or not description:
        return jsonify({"ok": False, "error": "Cím és leírás megadása kötelező."}), 400

    if category not in CATEGORIES:
        category = "other"

    conn = get_db()
    try:
        # AI processing
        ai_result = categorize_issue(title, description)

        # Content moderation — reject invalid submissions
        if ai_result.get("rejected"):
            reason = ai_result.get("rejection_reason", "A bejelentés nem közterületi probléma.")
            return jsonify({"ok": False, "error": reason}), 400

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

        # Warn user about duplicate before saving (unless they confirmed)
        confirm_dup = request.form.get("confirm_duplicate") == "true"
        if dup_id and not confirm_dup:
            dup_issue = next((i for i in existing_list if i["id"] == dup_id), None)
            dup_title = dup_issue["title"] if dup_issue else f"#{dup_id}"
            dup_desc = dup_issue["description"][:200] if dup_issue else ""
            # Fetch vote score and status for the duplicate
            dup_extra = conn.execute(
                "SELECT vote_score, status, created_at FROM issues WHERE id = %s",
                (dup_id,)
            ).fetchone()
            return jsonify({
                "ok": False,
                "duplicate": True,
                "duplicate_id": dup_id,
                "duplicate_title": dup_title,
                "duplicate_desc": dup_desc,
                "duplicate_votes": dup_extra["vote_score"] if dup_extra else 0,
                "duplicate_status": dup_extra["status"] if dup_extra else "new",
                "duplicate_date": dup_extra["created_at"].strftime("%Y.%m.%d") if dup_extra else "",
                "error": "Hasonlo bejelentes mar letezik: " + dup_title + ". Biztosan ujat szeretnel kuldeni?",
            }), 409

        # Insert issue
        cur = conn.execute(
            "INSERT INTO issues (title, description, category, location, district_id, user_id, "
            "ai_urgency, ai_category_suggestion, ai_duplicate_of, lat, lng) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (title, description, category, location, current_user.district_id,
             current_user.id, ai_urgency, ai_cat, dup_id, lat, lng),
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
            "COALESCE(u.display_name, 'Körzeti lakos') AS author_name, "
            "COALESCE(("
            "  SELECT SUM(CASE WHEN v2.direction = 1 THEN 2 WHEN v2.direction = -1 THEN -1 ELSE 0 END) "
            "  FROM votes v2 JOIN issues i2 ON v2.issue_id = i2.id WHERE i2.user_id = u.id"
            "), 0) + COALESCE(("
            "  SELECT COUNT(*) FROM comments c2 WHERE c2.user_id = u.id AND c2.is_hidden = FALSE"
            "), 0) + COALESCE(("
            "  SELECT COUNT(*) * 5 FROM issues i3 WHERE i3.user_id = u.id AND i3.status = 'done'"
            "), 0) AS author_reputation "
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

        # Comments (hide moderated ones for non-admins)
        comments_raw = conn.execute(
            "SELECT c.*, COALESCE(u.display_name, 'Körzeti lakos') AS author_name, "
            "COALESCE(("
            "  SELECT SUM(CASE WHEN v2.direction = 1 THEN 2 WHEN v2.direction = -1 THEN -1 ELSE 0 END) "
            "  FROM votes v2 JOIN issues i2 ON v2.issue_id = i2.id WHERE i2.user_id = u.id"
            "), 0) + COALESCE(("
            "  SELECT COUNT(*) FROM comments c2 WHERE c2.user_id = u.id AND c2.is_hidden = FALSE"
            "), 0) + COALESCE(("
            "  SELECT COUNT(*) * 5 FROM issues i3 WHERE i3.user_id = u.id AND i3.status = 'done'"
            "), 0) AS author_reputation "
            "FROM comments c JOIN users u ON c.user_id = u.id "
            "WHERE c.issue_id = %s AND c.is_hidden = FALSE ORDER BY c.created_at ASC",
            (issue_id,)
        ).fetchall()
        comments = []
        for c in comments_raw:
            props = dict(c.items())
            rep = props.get("author_reputation", 0) or 0
            rep_name, rep_icon = get_reputation_level(rep)
            props["rep_level_name"] = rep_name
            props["rep_level_icon"] = rep_icon
            comment = type("Comment", (), props)
            comment.time_ago = time_ago(c["created_at"])
            comments.append(comment)

        # Photos
        photos = conn.execute(
            "SELECT * FROM issue_media WHERE issue_id = %s", (issue_id,)
        ).fetchall()

        stats = get_district_stats(current_user.district_id)

        author_rep = issue["author_reputation"] or 0
        author_rep_name, author_rep_icon = get_reputation_level(author_rep)

        # Resolution voting data
        resolution_active = False
        resolution_expired = False
        resolution_yes = 0
        resolution_no = 0
        user_resolution_vote = None
        resolution_deadline = None
        resolution_starter = None

        if issue["resolution_started_at"]:
            deadline = issue["resolution_started_at"] + timedelta(days=7)
            resolution_deadline = deadline
            now = datetime.now()
            if now <= deadline:
                resolution_active = True
            else:
                resolution_expired = True

            # Vote counts
            res_counts = conn.execute(
                "SELECT vote, COUNT(*) AS cnt FROM resolution_votes "
                "WHERE issue_id = %s GROUP BY vote",
                (issue_id,)
            ).fetchall()
            for rc in res_counts:
                if rc["vote"]:
                    resolution_yes = rc["cnt"]
                else:
                    resolution_no = rc["cnt"]

            # Current user's vote
            user_rv = conn.execute(
                "SELECT vote FROM resolution_votes WHERE issue_id = %s AND user_id = %s",
                (issue_id, current_user.id),
            ).fetchone()
            if user_rv is not None:
                user_resolution_vote = user_rv["vote"]

            # Who started it
            starter = conn.execute(
                "SELECT COALESCE(display_name, 'Körzeti lakos') AS name FROM users WHERE id = %s",
                (issue["resolution_started_by"],)
            ).fetchone()
            if starter:
                resolution_starter = starter["name"]

            # Auto-resolve if expired and majority says yes
            if resolution_expired and issue["status"] != "done":
                if resolution_yes > resolution_no and resolution_yes >= 3:
                    conn.execute(
                        "UPDATE issues SET status = 'done', resolved_at = NOW(), updated_at = NOW() WHERE id = %s",
                        (issue_id,)
                    )
                    conn.commit()
                    issue = dict(issue.items())
                    issue["status"] = "done"

        return render_template("issue_detail.html",
            issue=issue,
            user_vote=user_vote,
            comments=comments,
            photos=photos,
            category_labels=CATEGORIES,
            urgency_labels=URGENCY_LABELS,
            stats=stats,
            active_page="dashboard",
            author_rep_name=author_rep_name,
            author_rep_icon=author_rep_icon,
            resolution_active=resolution_active,
            resolution_expired=resolution_expired,
            resolution_yes=resolution_yes,
            resolution_no=resolution_no,
            user_resolution_vote=user_resolution_vote,
            resolution_deadline=resolution_deadline,
            resolution_starter=resolution_starter,
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

        # Send push notification (async-safe, non-blocking)
        if user_vote != 0:
            try:
                notify_vote(issue_id, current_user.display_name, direction)
            except Exception:
                pass

        return jsonify({"ok": True, "vote_score": new_score, "user_vote": user_vote})
    except Exception:
        conn.rollback()
        return jsonify({"ok": False}), 500
    finally:
        conn.close()


@app.route("/issue/<int:issue_id>/resolve", methods=["POST"])
@login_required
def start_resolution(issue_id):
    """Start a community resolution vote (7-day voting period)."""
    conn = get_db()
    try:
        issue = conn.execute("SELECT * FROM issues WHERE id = %s", (issue_id,)).fetchone()
        if not issue:
            return jsonify({"ok": False, "error": "Nem található."}), 404
        if issue["status"] == "done":
            return jsonify({"ok": False, "error": "Már megoldottnak jelölve."}), 400
        if issue["resolution_started_at"]:
            return jsonify({"ok": False, "error": "Már folyamatban van a szavazás."}), 400

        conn.execute(
            "UPDATE issues SET resolution_started_at = NOW(), resolution_started_by = %s, updated_at = NOW() WHERE id = %s",
            (current_user.id, issue_id),
        )
        # Auto-vote yes for the initiator
        conn.execute(
            "INSERT INTO resolution_votes (issue_id, user_id, vote) VALUES (%s, %s, TRUE)",
            (issue_id, current_user.id),
        )
        conn.commit()
        return jsonify({"ok": True})
    except Exception:
        conn.rollback()
        return jsonify({"ok": False}), 500
    finally:
        conn.close()


@app.route("/issue/<int:issue_id>/resolve-vote", methods=["POST"])
@login_required
def resolution_vote(issue_id):
    """Vote on whether an issue is resolved."""
    data = request.get_json()
    vote = data.get("vote")  # True = yes resolved, False = no not resolved
    if vote is None:
        return jsonify({"ok": False}), 400

    conn = get_db()
    try:
        issue = conn.execute("SELECT * FROM issues WHERE id = %s", (issue_id,)).fetchone()
        if not issue or not issue["resolution_started_at"]:
            return jsonify({"ok": False, "error": "Nincs aktív szavazás."}), 400

        deadline = issue["resolution_started_at"] + timedelta(days=7)
        if datetime.now() > deadline:
            return jsonify({"ok": False, "error": "A szavazási időszak lejárt."}), 400

        # Upsert vote
        existing = conn.execute(
            "SELECT id FROM resolution_votes WHERE issue_id = %s AND user_id = %s",
            (issue_id, current_user.id),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE resolution_votes SET vote = %s WHERE id = %s",
                (vote, existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO resolution_votes (issue_id, user_id, vote) VALUES (%s, %s, %s)",
                (issue_id, current_user.id, vote),
            )
        conn.commit()

        # Return updated counts
        counts = conn.execute(
            "SELECT vote, COUNT(*) AS cnt FROM resolution_votes WHERE issue_id = %s GROUP BY vote",
            (issue_id,)
        ).fetchall()
        yes_count = 0
        no_count = 0
        for c in counts:
            if c["vote"]:
                yes_count = c["cnt"]
            else:
                no_count = c["cnt"]

        return jsonify({"ok": True, "yes": yes_count, "no": no_count, "user_vote": vote})
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

        try:
            notify_comment(issue_id, current_user.display_name)
        except Exception:
            pass

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


@app.route("/api/map-issues")
def api_map_issues():
    """GeoJSON for map markers — public for landing, filtered for dashboard."""
    district = request.args.get("district", type=int)
    conn = get_db()
    try:
        if district:
            rows = conn.execute(
                "SELECT i.id, i.title, i.category, i.vote_score, i.status, i.lat, i.lng, "
                "d.number AS district_number "
                "FROM issues i JOIN districts d ON i.district_id = d.id "
                "WHERE i.lat IS NOT NULL AND i.lng IS NOT NULL AND d.number = %s "
                "ORDER BY i.vote_score DESC LIMIT 200",
                (district,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT i.id, i.title, i.category, i.vote_score, i.status, i.lat, i.lng, "
                "d.number AS district_number "
                "FROM issues i JOIN districts d ON i.district_id = d.id "
                "WHERE i.lat IS NOT NULL AND i.lng IS NOT NULL "
                "ORDER BY i.vote_score DESC LIMIT 200"
            ).fetchall()

        features = []
        for r in rows:
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [r["lng"], r["lat"]]},
                "properties": {
                    "id": r["id"], "title": r["title"], "category": r["category"],
                    "votes": r["vote_score"], "status": r["status"],
                    "district": r["district_number"],
                },
            })
        return jsonify({"type": "FeatureCollection", "features": features})
    finally:
        conn.close()


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


# ── Routes: Admin ──
@app.route("/admin")
@admin_required
def admin_dashboard():
    conn = get_db()
    try:
        total_issues = conn.execute("SELECT COUNT(*) AS cnt FROM issues").fetchone()["cnt"]
        active_issues = conn.execute("SELECT COUNT(*) AS cnt FROM issues WHERE status != 'done'").fetchone()["cnt"]
        solved_issues = conn.execute("SELECT COUNT(*) AS cnt FROM issues WHERE status = 'done'").fetchone()["cnt"]
        hidden_issues = conn.execute("SELECT COUNT(*) AS cnt FROM issues WHERE is_hidden = TRUE").fetchone()["cnt"]
        total_users = conn.execute("SELECT COUNT(*) AS cnt FROM users WHERE is_active = TRUE").fetchone()["cnt"]
        banned_users = conn.execute("SELECT COUNT(*) AS cnt FROM users WHERE is_banned = TRUE").fetchone()["cnt"]
        total_comments = conn.execute("SELECT COUNT(*) AS cnt FROM comments").fetchone()["cnt"]
        hidden_comments = conn.execute("SELECT COUNT(*) AS cnt FROM comments WHERE is_hidden = TRUE").fetchone()["cnt"]

        # Recent issues
        recent = conn.execute(
            "SELECT i.*, d.number AS district_number, "
            "COALESCE(u.display_name, 'Körzeti lakos') AS author_name, u.email AS author_email "
            "FROM issues i JOIN districts d ON i.district_id = d.id "
            "JOIN users u ON i.user_id = u.id "
            "ORDER BY i.created_at DESC LIMIT 20"
        ).fetchall()

        # District breakdown
        district_stats = conn.execute(
            "SELECT d.number, d.name, "
            "COUNT(CASE WHEN i.status != 'done' THEN 1 END) AS active, "
            "COUNT(CASE WHEN i.status = 'done' THEN 1 END) AS solved, "
            "COUNT(i.id) AS total "
            "FROM districts d LEFT JOIN issues i ON i.district_id = d.id "
            "GROUP BY d.number, d.name ORDER BY d.number"
        ).fetchall()

        return render_template("admin/dashboard.html",
            total_issues=total_issues, active_issues=active_issues,
            solved_issues=solved_issues, hidden_issues=hidden_issues,
            total_users=total_users, banned_users=banned_users,
            total_comments=total_comments, hidden_comments=hidden_comments,
            recent=recent, district_stats=district_stats,
            category_labels=CATEGORIES, urgency_labels=URGENCY_LABELS,
        )
    finally:
        conn.close()


@app.route("/admin/issues")
@admin_required
def admin_issues():
    status = request.args.get("status", "all")
    page = request.args.get("page", 1, type=int)
    per_page = 30
    offset = (page - 1) * per_page

    conn = get_db()
    try:
        where = "TRUE"
        params = []
        if status == "hidden":
            where = "i.is_hidden = TRUE"
        elif status != "all":
            where = "i.status = %s AND i.is_hidden = FALSE"
            params.append(status)

        issues = conn.execute(
            f"SELECT i.*, d.number AS district_number, "
            f"COALESCE(u.display_name, 'Körzeti lakos') AS author_name, u.email AS author_email "
            f"FROM issues i JOIN districts d ON i.district_id = d.id "
            f"JOIN users u ON i.user_id = u.id "
            f"WHERE {where} ORDER BY i.created_at DESC LIMIT %s OFFSET %s",
            params + [per_page, offset],
        ).fetchall()

        total = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM issues i WHERE {where}", params
        ).fetchone()["cnt"]

        return render_template("admin/issues.html",
            issues=issues, status=status, page=page,
            total=total, per_page=per_page,
            category_labels=CATEGORIES, urgency_labels=URGENCY_LABELS,
        )
    finally:
        conn.close()


@app.route("/admin/issue/<int:issue_id>/action", methods=["POST"])
@admin_required
def admin_issue_action(issue_id):
    action = request.form.get("action")
    conn = get_db()
    try:
        if action == "hide":
            conn.execute("UPDATE issues SET is_hidden = TRUE WHERE id = %s", (issue_id,))
        elif action == "unhide":
            conn.execute("UPDATE issues SET is_hidden = FALSE WHERE id = %s", (issue_id,))
        elif action in ("new", "progress", "done"):
            update = "UPDATE issues SET status = %s, updated_at = NOW()"
            params = [action, issue_id]
            if action == "done":
                update += ", resolved_at = NOW()"
            update += " WHERE id = %s"
            conn.execute(update, params)
            try:
                notify_status_change(issue_id, action)
            except Exception:
                pass
        elif action == "delete":
            conn.execute("DELETE FROM issues WHERE id = %s", (issue_id,))
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()
    return redirect(request.referrer or url_for("admin_issues"))


@app.route("/admin/users")
@admin_required
def admin_users():
    conn = get_db()
    try:
        users = conn.execute(
            "SELECT u.*, d.number AS district_number, d.name AS district_name, "
            "(SELECT COUNT(*) FROM issues WHERE user_id = u.id) AS issue_count, "
            "(SELECT COUNT(*) FROM comments WHERE user_id = u.id) AS comment_count "
            "FROM users u LEFT JOIN districts d ON u.district_id = d.id "
            "ORDER BY u.created_at DESC"
        ).fetchall()
        return render_template("admin/users.html", users=users)
    finally:
        conn.close()


@app.route("/admin/user/<int:user_id>/action", methods=["POST"])
@admin_required
def admin_user_action(user_id):
    action = request.form.get("action")
    conn = get_db()
    try:
        if action == "ban":
            conn.execute("UPDATE users SET is_banned = TRUE, is_active = FALSE WHERE id = %s", (user_id,))
        elif action == "unban":
            conn.execute("UPDATE users SET is_banned = FALSE, is_active = TRUE WHERE id = %s", (user_id,))
        elif action == "make_admin":
            conn.execute("UPDATE users SET is_admin = TRUE WHERE id = %s", (user_id,))
        elif action == "remove_admin":
            conn.execute("UPDATE users SET is_admin = FALSE WHERE id = %s", (user_id,))
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()
    return redirect(request.referrer or url_for("admin_users"))


@app.route("/admin/comments")
@admin_required
def admin_comments():
    conn = get_db()
    try:
        comments = conn.execute(
            "SELECT c.*, i.title AS issue_title, "
            "COALESCE(u.display_name, 'Körzeti lakos') AS author_name, u.email AS author_email "
            "FROM comments c JOIN issues i ON c.issue_id = i.id "
            "JOIN users u ON c.user_id = u.id "
            "ORDER BY c.created_at DESC LIMIT 100"
        ).fetchall()
        return render_template("admin/comments.html", comments=comments)
    finally:
        conn.close()


@app.route("/admin/comment/<int:comment_id>/action", methods=["POST"])
@admin_required
def admin_comment_action(comment_id):
    action = request.form.get("action")
    conn = get_db()
    try:
        if action == "hide":
            conn.execute("UPDATE comments SET is_hidden = TRUE WHERE id = %s", (comment_id,))
        elif action == "unhide":
            conn.execute("UPDATE comments SET is_hidden = FALSE WHERE id = %s", (comment_id,))
        elif action == "delete":
            comment = conn.execute("SELECT issue_id FROM comments WHERE id = %s", (comment_id,)).fetchone()
            if comment:
                conn.execute("DELETE FROM comments WHERE id = %s", (comment_id,))
                conn.execute(
                    "UPDATE issues SET comment_count = GREATEST(comment_count - 1, 0) WHERE id = %s",
                    (comment["issue_id"],)
                )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()
    return redirect(request.referrer or url_for("admin_comments"))


# ── Init & Run ──
with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=FLASK_DEBUG)
