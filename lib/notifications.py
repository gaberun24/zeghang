"""
Push notification sender — uses pywebpush to deliver Web Push notifications.
Falls back silently if pywebpush is not installed or VAPID keys are missing.
"""

import json
from lib.config import VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY, VAPID_EMAIL
from lib.database import get_db


def send_push(user_id, title, body, url="/dashboard"):
    """Send a push notification to a specific user (if subscribed)."""
    if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
        return

    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        return

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT push_subscription FROM users WHERE id = %s AND push_subscription IS NOT NULL",
            (user_id,),
        ).fetchone()
        if not row or not row["push_subscription"]:
            return

        subscription = json.loads(row["push_subscription"])
        payload = json.dumps({"title": title, "body": body, "url": url})

        try:
            webpush(
                subscription_info=subscription,
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": f"mailto:{VAPID_EMAIL}"},
                timeout=10,
            )
        except WebPushException:
            # Subscription expired or invalid — clean it up
            conn.execute(
                "UPDATE users SET push_subscription = NULL WHERE id = %s",
                (user_id,),
            )
            conn.commit()
    finally:
        conn.close()


def notify_vote(issue_id, voter_name, direction):
    """Notify issue author when someone votes on their issue."""
    conn = get_db()
    try:
        issue = conn.execute(
            "SELECT user_id, title FROM issues WHERE id = %s", (issue_id,)
        ).fetchone()
        if not issue:
            return

        # Check if user wants vote notifications
        user = conn.execute(
            "SELECT notify_votes FROM users WHERE id = %s", (issue["user_id"],)
        ).fetchone()
        if not user or not user["notify_votes"]:
            return

        arrow = "↑" if direction == 1 else "↓"
        send_push(
            issue["user_id"],
            f"{arrow} Szavazat a bejelentésedre",
            f"{voter_name} szavazott: \u201e{issue['title'][:60]}\u201d",
            f"/issue/{issue_id}",
        )
    finally:
        conn.close()


def notify_comment(issue_id, commenter_name):
    """Notify issue author when someone comments on their issue."""
    conn = get_db()
    try:
        issue = conn.execute(
            "SELECT user_id, title FROM issues WHERE id = %s", (issue_id,)
        ).fetchone()
        if not issue:
            return

        user = conn.execute(
            "SELECT notify_comments FROM users WHERE id = %s", (issue["user_id"],)
        ).fetchone()
        if not user or not user["notify_comments"]:
            return

        send_push(
            issue["user_id"],
            "💬 Új hozzászólás",
            f"{commenter_name}: \u201e{issue['title'][:60]}\u201d",
            f"/issue/{issue_id}",
        )
    finally:
        conn.close()


def notify_status_change(issue_id, new_status):
    """Notify issue author when status changes."""
    status_labels = {"progress": "Vizsgálat alatt", "done": "Megoldva ✓"}
    conn = get_db()
    try:
        issue = conn.execute(
            "SELECT user_id, title FROM issues WHERE id = %s", (issue_id,)
        ).fetchone()
        if not issue:
            return

        user = conn.execute(
            "SELECT notify_status FROM users WHERE id = %s", (issue["user_id"],)
        ).fetchone()
        if not user or not user["notify_status"]:
            return

        label = status_labels.get(new_status, new_status)
        send_push(
            issue["user_id"],
            f"📋 Státuszváltozás: {label}",
            f"\u201e{issue['title'][:60]}\u201d \u2014 {label}",
            f"/issue/{issue_id}",
        )
    finally:
        conn.close()
