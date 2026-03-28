"""
Zalaegerszeg Hangja — Közösségi Platform
Flask application with all routes.
"""

import hashlib
import os
import secrets
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
from PIL import Image
import io

from lib.config import (
    FLASK_SECRET_KEY, FLASK_DEBUG, UPLOAD_DIR, MAX_UPLOAD_MB,
    ADMIN_ALERT_EMAIL,
)
from lib.database import get_db, init_db
from lib.ai import (
    categorize_issue, check_duplicates, quick_categorize,
    CATEGORIES, URGENCY_LABELS,
)
from lib.moderation import censor_text
from lib.notifications import notify_vote, notify_comment, notify_status_change
from lib.email import send_email
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
        self.is_banned = row.get("is_banned", False)
        self.theme = row.get("theme", "system") or "system"
        self.district = DistrictInfo(district_row) if district_row else None

    @property
    def is_shadowbanned(self):
        """User is shadowbanned if reputation drops below -10."""
        return self.reputation <= -10 and not self.is_admin

    @property
    def is_restricted(self):
        """User is restricted (rate limited) if reputation is below 0."""
        return self.reputation < 0 and not self.is_admin

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


# ── Security alert emails ──
SECURITY_EVENT_LABELS = {
    "login_fail": "Sikertelen bejelentkezés",
    "login_ok": "Sikeres bejelentkezés",
    "register_ok": "Regisztráció",
    "password_reset_attempt": "Jelszó-visszaállítási próba",
    "password_reset_requested": "Jelszó-visszaállítás kérés",
    "password_reset_ok": "Jelszó visszaállítva",
    "address_change": "Címmódosítás",
    "shadowban": "Shadowban aktiválás",
    "content_rejected": "Tartalom elutasítva",
    "rate_limited": "Rate limit elérve",
}

_alert_throttle = {}  # {event_type: last_sent_datetime}
_ALERT_COOLDOWN = timedelta(minutes=10)


def send_security_alert(event_type, details="", ip=""):
    """Send email alert for suspicious security events (throttled)."""
    if not ADMIN_ALERT_EMAIL:
        return
    now = datetime.now()
    last_sent = _alert_throttle.get(event_type)
    if last_sent and (now - last_sent) < _ALERT_COOLDOWN:
        return
    _alert_throttle[event_type] = now

    label = SECURITY_EVENT_LABELS.get(event_type, event_type)
    subject = f"\u26a0 Z! Biztonsági figyelmeztetés: {label}"
    html_body = (
        f"<h2>Biztonsági figyelmeztetés</h2>"
        f"<p><strong>Esemény:</strong> {label}</p>"
        f"<p><strong>IP cím:</strong> {ip}</p>"
        f"<p><strong>Részletek:</strong> {details}</p>"
        f"<p><strong>Időpont:</strong> {now.strftime('%Y-%m-%d %H:%M:%S')}</p>"
        f'<p style="color:#999; font-size:12px;">Ez egy automatikus értesítés a Zalaegerszeg Hangja platformról.</p>'
    )
    try:
        send_email(ADMIN_ALERT_EMAIL, subject, html_body)
    except Exception:
        pass


@app.before_request
def track_page_view():
    """Track page views for stats (skip static files and API calls)."""
    if request.path.startswith("/static") or request.path.startswith("/api"):
        return
    if request.method != "GET":
        return
    try:
        ip_hash = hashlib.sha256(request.remote_addr.encode()).hexdigest()[:16]
        uid = current_user.id if hasattr(current_user, "id") and current_user.is_authenticated else None
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO page_views (path, ip_hash, user_id) VALUES (%s, %s, %s)",
                (request.path[:255], ip_hash, uid),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://*.tile.openstreetmap.org https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://unpkg.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https://*.tile.openstreetmap.org; "
        "connect-src 'self' https://api.openweathermap.org https://unpkg.com https://*.tile.openstreetmap.org"
    )
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
            log_security("rate_limited", f"ip={ip} event=login_fail", ip)
            send_security_alert("rate_limited", f"ip={ip} event=login_fail", ip)
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


@app.route("/elfelejtett-jelszo", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        ip = request.remote_addr
        if check_rate_limit(ip, event_type="password_reset_attempt", max_attempts=3, window_seconds=600):
            log_security("rate_limited", f"ip={ip} event=password_reset_attempt", ip)
            send_security_alert("rate_limited", f"ip={ip} event=password_reset_attempt", ip)
            flash("Túl sok próbálkozás. Kérjük, várj 10 percet.", "error")
            return render_template("forgot_password.html")
        log_security("password_reset_attempt", f"ip={ip}", ip)

        email = request.form.get("email", "").strip().lower()
        # Always show success message (don't reveal if email exists)
        flash("Ha ez az email cím regisztrálva van, hamarosan kapsz egy jelszó-visszaállító linket.", "success")

        if email:
            conn = get_db()
            try:
                user = conn.execute(
                    "SELECT id FROM users WHERE email = %s AND is_active = TRUE",
                    (email,)
                ).fetchone()

                if user:
                    # Generate cryptographically secure token
                    token = secrets.token_urlsafe(48)
                    expires = datetime.now() + timedelta(hours=1)

                    # Invalidate old tokens
                    conn.execute(
                        "UPDATE password_resets SET used = TRUE WHERE user_id = %s AND used = FALSE",
                        (user["id"],)
                    )

                    conn.execute(
                        "INSERT INTO password_resets (user_id, token, expires_at) VALUES (%s, %s, %s)",
                        (user["id"], token, expires),
                    )
                    conn.commit()

                    # Send email
                    reset_url = request.host_url.rstrip("/") + url_for("reset_password", token=token)
                    html = f"""
                    <div style="font-family:Arial,sans-serif; max-width:500px; margin:0 auto; padding:2rem;">
                        <div style="text-align:center; margin-bottom:2rem;">
                            <div style="display:inline-block; background:#0F3460; color:white; font-weight:700; padding:8px 14px; border-radius:8px; font-size:18px;">Z!</div>
                            <h2 style="margin-top:1rem; color:#0F3460;">Jelszó visszaállítás</h2>
                        </div>
                        <p>Valaki (remélhetőleg te) jelszó-visszaállítást kért erre a fiókra.</p>
                        <p>Kattints az alábbi gombra az új jelszó beállításához:</p>
                        <div style="text-align:center; margin:2rem 0;">
                            <a href="{reset_url}" style="background:#4a7c59; color:white; padding:12px 32px; border-radius:8px; text-decoration:none; font-weight:600; font-size:16px;">
                                Új jelszó beállítása
                            </a>
                        </div>
                        <p style="font-size:13px; color:#888;">A link 1 órán belül lejár. Ha nem te kérted, nyugodtan hagyd figyelmen kívül ezt az emailt.</p>
                        <hr style="border:none; border-top:1px solid #eee; margin:2rem 0;">
                        <p style="font-size:12px; color:#aaa; text-align:center;">Zalaegerszeg Hangja — Közösségi platform</p>
                    </div>
                    """
                    send_email(email, "Jelszó visszaállítás — Zalaegerszeg Hangja", html)
                    log_security("password_reset_requested", f"email={email}", request.remote_addr)
            except Exception:
                conn.rollback()
            finally:
                conn.close()

        return redirect(url_for("forgot_password"))

    return render_template("forgot_password.html")


@app.route("/jelszo-visszaallitas/<token>", methods=["GET", "POST"])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    conn = get_db()
    try:
        reset = conn.execute(
            "SELECT * FROM password_resets WHERE token = %s AND used = FALSE AND expires_at > NOW()",
            (token,)
        ).fetchone()

        if not reset:
            flash("Érvénytelen vagy lejárt visszaállítási link. Kérj újat.", "error")
            return redirect(url_for("forgot_password"))

        if request.method == "POST":
            password = request.form.get("password", "")
            password2 = request.form.get("password2", "")

            if len(password) < 8:
                flash("A jelszónak legalább 8 karakter hosszúnak kell lennie.", "error")
                return render_template("reset_password.html", token=token)

            if password != password2:
                flash("A két jelszó nem egyezik.", "error")
                return render_template("reset_password.html", token=token)

            pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            conn.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s",
                (pw_hash, reset["user_id"]),
            )
            conn.execute(
                "UPDATE password_resets SET used = TRUE WHERE id = %s",
                (reset["id"],)
            )
            conn.commit()

            log_security("password_reset_ok", f"user_id={reset['user_id']}", request.remote_addr)
            flash("Jelszó sikeresen megváltoztatva! Most már bejelentkezhetsz.", "success")
            return redirect(url_for("login"))

        return render_template("reset_password.html", token=token)
    finally:
        conn.close()


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

        # Shadowban: hide shadowbanned users' posts from others
        if tab != "mine":
            where_clauses.append(
                "(i.user_id = %s OR NOT EXISTS ("
                "  SELECT 1 FROM users sb WHERE sb.id = i.user_id AND sb.is_shadowbanned = TRUE"
                "))"
            )
            params.append(current_user.id)

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

    # Rate limit: restricted users (rep < 0) can post max 1/day
    if current_user.is_restricted:
        conn_rl = get_db()
        try:
            today_count = conn_rl.execute(
                "SELECT COUNT(*) AS cnt FROM issues WHERE user_id = %s AND created_at::date = CURRENT_DATE",
                (current_user.id,)
            ).fetchone()
            if today_count["cnt"] >= 1:
                return jsonify({"ok": False, "error": "Napi bejelentési limit elérve. Próbáld újra holnap."}), 429
        finally:
            conn_rl.close()

    # Normal users: max 10 issues per day (anti-spam)
    elif not current_user.is_admin:
        conn_rl = get_db()
        try:
            today_count = conn_rl.execute(
                "SELECT COUNT(*) AS cnt FROM issues WHERE user_id = %s AND created_at::date = CURRENT_DATE",
                (current_user.id,)
            ).fetchone()
            if today_count["cnt"] >= 10:
                return jsonify({"ok": False, "error": "Napi bejelentési limit elérve (max. 10)."}), 429
        finally:
            conn_rl.close()

    if category not in CATEGORIES:
        category = "other"

    conn = get_db()
    try:
        # AI processing
        ai_result = categorize_issue(title, description)

        # Content moderation — reject invalid submissions
        if ai_result.get("rejected"):
            reason = ai_result.get("rejection_reason", "A bejelentés nem közterületi probléma.")
            log_security("content_rejected", f"user={current_user.id} reason={reason}", request.remote_addr)
            send_security_alert("content_rejected", f"user={current_user.id} reason={reason}", request.remote_addr)
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
        MAGIC_BYTES = {
            b"\xff\xd8\xff": ".jpg",
            b"\x89PNG\r\n\x1a\n": ".png",
            b"GIF87a": ".gif",
            b"GIF89a": ".gif",
            b"RIFF": ".webp",
        }
        for photo in photos:
            if photo and photo.filename:
                ext = os.path.splitext(photo.filename)[1].lower()
                if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                    # Validate file content (magic bytes)
                    header = photo.read(16)
                    photo.seek(0)
                    if not any(header.startswith(magic) for magic in MAGIC_BYTES):
                        continue  # Skip invalid files silently

                    os.makedirs(UPLOAD_DIR, exist_ok=True)

                    # Resize & compress with Pillow
                    img = Image.open(photo)
                    img = img.convert("RGB")  # RGBA/palette → RGB for JPEG
                    max_dim = 1920
                    if img.width > max_dim or img.height > max_dim:
                        img.thumbnail((max_dim, max_dim), Image.LANCZOS)

                    filename = f"{uuid.uuid4().hex}.jpg"
                    img.save(
                        os.path.join(UPLOAD_DIR, filename),
                        format="JPEG",
                        quality=85,
                        optimize=True,
                    )
                    conn.execute(
                        "INSERT INTO issue_media (issue_id, filename, original_name, mime_type) "
                        "VALUES (%s, %s, %s, %s)",
                        (issue_id, filename, secure_filename(photo.filename), "image/jpeg"),
                    )

        conn.commit()
        return jsonify({"ok": True, "issue_id": issue_id})
    except Exception:
        conn.rollback()
        return jsonify({"ok": False, "error": "Hiba történt a bejelentés mentése során."}), 500
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
            "WHERE c.issue_id = %s AND c.is_hidden = FALSE "
            "AND (u.is_shadowbanned = FALSE OR c.user_id = %s) "
            "ORDER BY c.created_at ASC",
            (issue_id, current_user.id)
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
        # Auto-shadowban check: recalculate issue author's reputation
        issue_author = conn.execute(
            "SELECT user_id FROM issues WHERE id = %s", (issue_id,)
        ).fetchone()
        if issue_author:
            author_rep = conn.execute(
                "SELECT COALESCE(("
                "  SELECT SUM(CASE WHEN v.direction = 1 THEN 2 WHEN v.direction = -1 THEN -1 ELSE 0 END) "
                "  FROM votes v JOIN issues i ON v.issue_id = i.id WHERE i.user_id = %s"
                "), 0) + COALESCE(("
                "  SELECT COUNT(*) FROM comments c WHERE c.user_id = %s AND c.is_hidden = FALSE"
                "), 0) + COALESCE(("
                "  SELECT COUNT(*) * 5 FROM issues i WHERE i.user_id = %s AND i.status = 'done'"
                "), 0) AS rep",
                (issue_author["user_id"], issue_author["user_id"], issue_author["user_id"]),
            ).fetchone()
            rep = author_rep["rep"] if author_rep else 0
            should_shadowban = rep <= -10
            conn.execute(
                "UPDATE users SET is_shadowbanned = %s WHERE id = %s AND is_admin = FALSE",
                (should_shadowban, issue_author["user_id"]),
            )
            if should_shadowban:
                log_security("shadowban", f"user_id={issue_author['user_id']} rep={rep}", request.remote_addr)
                send_security_alert("shadowban", f"user_id={issue_author['user_id']} rep={rep}", request.remote_addr)

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

    # Rate limit comments for restricted users
    if current_user.is_restricted:
        conn_rl = get_db()
        try:
            recent = conn_rl.execute(
                "SELECT COUNT(*) AS cnt FROM comments WHERE user_id = %s AND created_at > NOW() - INTERVAL '1 hour'",
                (current_user.id,)
            ).fetchone()
            if recent["cnt"] >= 3:
                return jsonify({"ok": False, "error": "Túl sok hozzászólás. Próbáld újra később."}), 429
        finally:
            conn_rl.close()

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


@app.route("/api/streets")
def api_streets():
    """Return unique street names for autocomplete."""
    from districts import STREETS
    names = sorted(set(f"{e['nev']} {e['tipus']}" for e in STREETS))
    return jsonify(names)


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


# ── Admin: Stats ──
@app.route("/admin/stats")
@admin_required
def admin_stats():
    conn = get_db()
    try:
        # View counts
        total_views = conn.execute("SELECT COUNT(*) AS cnt FROM page_views").fetchone()["cnt"]
        today_views = conn.execute(
            "SELECT COUNT(*) AS cnt FROM page_views WHERE created_at >= CURRENT_DATE"
        ).fetchone()["cnt"]
        week_views = conn.execute(
            "SELECT COUNT(*) AS cnt FROM page_views WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'"
        ).fetchone()["cnt"]
        month_views = conn.execute(
            "SELECT COUNT(*) AS cnt FROM page_views WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'"
        ).fetchone()["cnt"]

        # Daily views (last 30 days)
        daily_views_rows = conn.execute(
            "SELECT DATE(created_at) AS d, COUNT(*) AS cnt "
            "FROM page_views WHERE created_at >= CURRENT_DATE - INTERVAL '30 days' "
            "GROUP BY DATE(created_at) ORDER BY d"
        ).fetchall()
        daily_views = [{"date": str(r["d"]), "count": r["cnt"]} for r in daily_views_rows]
        max_daily = max((d["count"] for d in daily_views), default=1)

        # Daily registrations (last 30 days)
        daily_reg_rows = conn.execute(
            "SELECT DATE(created_at) AS d, COUNT(*) AS cnt "
            "FROM users WHERE created_at >= CURRENT_DATE - INTERVAL '30 days' "
            "GROUP BY DATE(created_at) ORDER BY d"
        ).fetchall()
        daily_registrations = [{"date": str(r["d"]), "count": r["cnt"]} for r in daily_reg_rows]
        max_reg = max((d["count"] for d in daily_registrations), default=1)

        # Category stats
        total_issues = conn.execute("SELECT COUNT(*) AS cnt FROM issues").fetchone()["cnt"]
        cat_rows = conn.execute(
            "SELECT category, COUNT(*) AS cnt FROM issues GROUP BY category ORDER BY cnt DESC"
        ).fetchall()
        category_stats = [{"label": CATEGORIES.get(r["category"], r["category"]), "count": r["cnt"]} for r in cat_rows]

        # Urgency stats
        urg_colors = {"low": "#16a34a", "medium": "#d97706", "high": "#ea580c", "urgent": "#dc2626"}
        urg_rows = conn.execute(
            "SELECT COALESCE(ai_urgency, 'low') AS urg, COUNT(*) AS cnt FROM issues GROUP BY urg ORDER BY cnt DESC"
        ).fetchall()
        urgency_stats = [
            {"key": r["urg"], "label": URGENCY_LABELS.get(r["urg"], r["urg"]),
             "count": r["cnt"], "color": urg_colors.get(r["urg"], "#64748b")}
            for r in urg_rows
        ]

        # Top users
        top_users_rows = conn.execute(
            "SELECT u.display_name AS name, d.number AS district, "
            "u.reputation, "
            "(SELECT COUNT(*) FROM issues WHERE user_id = u.id) AS issues, "
            "(SELECT COUNT(*) FROM votes WHERE user_id = u.id) AS votes, "
            "(SELECT COUNT(*) FROM comments WHERE user_id = u.id) AS comments "
            "FROM users u LEFT JOIN districts d ON u.district_id = d.id "
            "WHERE u.is_active = TRUE "
            "ORDER BY u.reputation DESC LIMIT 10"
        ).fetchall()
        top_users = [dict(r.items()) for r in top_users_rows]

        # District activity
        district_rows = conn.execute(
            "SELECT d.id, d.number, d.name, d.population AS residents, "
            "COUNT(DISTINCT i.id) AS issues, "
            "COALESCE(SUM(ABS(i.vote_score)), 0) AS votes, "
            "(SELECT COUNT(*) FROM users WHERE district_id = d.id AND is_active = TRUE) AS active_users "
            "FROM districts d LEFT JOIN issues i ON i.district_id = d.id "
            "GROUP BY d.id, d.number, d.name, d.population ORDER BY d.number"
        ).fetchall()
        district_activity = []
        for r in district_rows:
            pop = r["residents"] or 1
            part = round(r["active_users"] / pop * 100, 1) if pop > 0 else 0
            district_activity.append({
                "number": r["number"], "name": r["name"],
                "residents": r["active_users"], "issues": r["issues"],
                "votes": r["votes"], "participation": min(part, 100),
            })

        return render_template("admin/stats.html",
            total_views=total_views, today_views=today_views,
            week_views=week_views, month_views=month_views,
            daily_views=daily_views, max_daily=max_daily,
            daily_registrations=daily_registrations, max_reg=max_reg,
            total_issues=total_issues,
            category_stats=category_stats, urgency_stats=urgency_stats,
            top_users=top_users, district_activity=district_activity,
        )
    finally:
        conn.close()


# ── Admin: Health ──
@app.route("/admin/health")
@admin_required
def admin_health():
    import platform
    import sys
    import shutil
    import flask as flask_mod

    # CPU & Memory
    try:
        import psutil
        cpu_percent = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        memory = {
            "percent": mem.percent,
            "used_gb": round(mem.used / (1024**3), 1),
            "total_gb": round(mem.total / (1024**3), 1),
        }
        disk_usage = psutil.disk_usage("/")
        disk = {
            "percent": round(disk_usage.percent, 1),
            "used_gb": round(disk_usage.used / (1024**3), 1),
            "total_gb": round(disk_usage.total / (1024**3), 1),
        }
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        delta = datetime.now() - boot_time
        days = delta.days
        hours = delta.seconds // 3600
        uptime = f"{days}n {hours}ó" if days > 0 else f"{hours}ó"
    except ImportError:
        cpu_percent = 0
        memory = {"percent": 0, "used_gb": 0, "total_gb": 0}
        disk = {"percent": 0, "used_gb": 0, "total_gb": 0}
        uptime = "psutil nem telepített"

    # Services check
    services = []
    # PostgreSQL
    try:
        conn = get_db()
        pg_ver = conn.execute("SELECT version()").fetchone()[0]
        pg_version = pg_ver.split(",")[0] if pg_ver else "?"
        conn.close()
        services.append({"name": "PostgreSQL", "ok": True, "detail": pg_version})
    except Exception as e:
        pg_version = "?"
        services.append({"name": "PostgreSQL", "ok": False, "detail": str(e)[:80]})

    # OpenAI
    try:
        from lib.config import OPENAI_API_KEY
        services.append({
            "name": "OpenAI API",
            "ok": bool(OPENAI_API_KEY),
            "detail": "API kulcs beállítva" if OPENAI_API_KEY else "Hiányzó API kulcs",
        })
    except Exception:
        services.append({"name": "OpenAI API", "ok": False, "detail": "Konfiguráció hiba"})

    # Brevo
    try:
        from lib.config import BREVO_API_KEY
        services.append({
            "name": "Brevo Email",
            "ok": bool(BREVO_API_KEY),
            "detail": "API kulcs beállítva" if BREVO_API_KEY else "Hiányzó API kulcs",
        })
    except Exception:
        services.append({"name": "Brevo Email", "ok": False, "detail": "Nincs konfigurálva"})

    # Upload dir
    upload_ok = os.path.isdir(UPLOAD_DIR)
    total_u, used_u, free_u = shutil.disk_usage(UPLOAD_DIR) if upload_ok else (0, 0, 0)
    services.append({
        "name": "Feltöltések mappa",
        "ok": upload_ok,
        "detail": f"{UPLOAD_DIR} ({round(used_u / (1024**2), 1)} MB használt)" if upload_ok else "Mappa nem létezik",
    })

    # DB table sizes
    db_tables = []
    try:
        conn = get_db()
        tables = ["users", "issues", "votes", "comments", "districts", "page_views", "resolution_votes", "security_log"]
        for t in tables:
            try:
                row_count = conn.execute(f"SELECT COUNT(*) AS cnt FROM {t}").fetchone()["cnt"]
                size_row = conn.execute(
                    "SELECT pg_size_pretty(pg_total_relation_size(%s)) AS s", (t,)
                ).fetchone()
                db_tables.append({"name": t, "rows": row_count, "size": size_row["s"]})
            except Exception:
                db_tables.append({"name": t, "rows": "?", "size": "?"})
        conn.close()
    except Exception:
        pass

    return render_template("admin/health.html",
        cpu_percent=cpu_percent,
        memory=memory,
        disk=disk,
        uptime=uptime,
        services=services,
        db_tables=db_tables,
        python_version=sys.version.split()[0],
        flask_version=flask_mod.__version__,
        pg_version=pg_version,
        os_info=f"{platform.system()} {platform.release()}",
        server_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


# ── Admin: Security Log ──
@app.route("/admin/security")
@admin_required
def admin_security():
    page = request.args.get("page", 1, type=int)
    event_filter = request.args.get("type", "")
    per_page = 50
    conn = get_db()
    try:
        where = ""
        params = []
        if event_filter:
            where = "WHERE event_type = %s"
            params = [event_filter]

        total = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM security_log {where}", params
        ).fetchone()["cnt"]

        events = conn.execute(
            f"SELECT * FROM security_log {where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
            params + [per_page, (page - 1) * per_page],
        ).fetchall()

        today_fails = conn.execute(
            "SELECT COUNT(*) AS cnt FROM security_log WHERE event_type = 'login_fail' AND created_at >= CURRENT_DATE"
        ).fetchone()["cnt"]

        unique_fail_ips = conn.execute(
            "SELECT COUNT(DISTINCT ip_address) AS cnt FROM security_log WHERE event_type = 'login_fail' AND created_at >= CURRENT_DATE"
        ).fetchone()["cnt"]

        event_types = conn.execute(
            "SELECT event_type, COUNT(*) AS cnt FROM security_log GROUP BY event_type ORDER BY cnt DESC"
        ).fetchall()

        return render_template("admin/security.html",
            events=events, total=total, page=page, per_page=per_page,
            pages=(total + per_page - 1) // per_page,
            today_fails=today_fails, unique_fail_ips=unique_fail_ips,
            event_types=event_types, current_filter=event_filter,
            event_labels=SECURITY_EVENT_LABELS,
        )
    finally:
        conn.close()


@app.route("/api/settings/theme", methods=["POST"])
@login_required
def update_theme():
    data = request.get_json()
    theme = data.get("theme", "system")
    if theme not in ("system", "light", "dark"):
        theme = "system"
    conn = get_db()
    try:
        conn.execute("UPDATE users SET theme = %s WHERE id = %s", (theme, current_user.id))
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


# ── Init & Run ──
with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=FLASK_DEBUG)
