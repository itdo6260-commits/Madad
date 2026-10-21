import os
import sqlite3
from flask import Flask, jsonify, request, render_template, g

app = Flask(__name__)
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "madad.db")

CATEGORIES = ["Groceries", "Education", "Transport", "Community Support", "Blood Donation"]
URGENCIES = ["Low", "Medium", "High"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS help_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    location TEXT NOT NULL,
    lat REAL,
    lng REAL,
    urgency TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Open',
    requester_name TEXT NOT NULL,
    volunteer_name TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);
"""

SEED = [
    ("Groceries for elderly neighbor", "Need someone to pick up weekly groceries for my 78-year-old neighbor.", "Groceries", "Banjara Hills", 17.4156, 78.4347, "High", "Open", "Ayesha", None),
    ("Math tutor for Class 9", "Looking for a volunteer to help a student with algebra twice a week.", "Education", "Gachibowli", 17.4401, 78.3489, "Medium", "Open", "Rahul", None),
    ("Ride to hospital appointment", "Need a ride to a morning check-up and back home.", "Transport", "Secunderabad", 17.4399, 78.4983, "High", "Open", "Farida", None),
    ("Blood donor needed (O+)", "Donor needed at a city hospital this week. Contact details are shared after you accept.", "Blood Donation", "Ameerpet", 17.4375, 78.4483, "High", "Open", "Imran", None),
    ("Clean up the park", "Organising a Saturday clean-up of the neighbourhood park. Need 5 helpers.", "Community Support", "Madhapur", 17.4486, 78.3908, "Low", "Open", "Sana", None),
    ("Donate school books", "A local school needs used textbooks for Classes 6 to 8.", "Education", "Kukatpally", 17.4948, 78.3996, "Medium", "Open", "Kiran", None),
    ("Help carrying groceries upstairs", "No lift in our building and I have a leg injury.", "Groceries", "Charminar", 17.3616, 78.4747, "Medium", "Open", "Zoya", None),
    ("Evening reading buddy", "Read with a visually impaired student for 30 minutes.", "Education", "Dilsukhnagar", 17.3688, 78.5247, "Low", "Open", "Meera", None),
    ("Delivered rice and lentils", "Delivered a ration pack to a family in need.", "Groceries", "Banjara Hills", 17.4170, 78.4360, "Medium", "Completed", "Hassan", "Bilal"),
    ("Drop to railway station", "Needed a ride before sunrise to catch a train.", "Transport", "Secunderabad", 17.4380, 78.4970, "High", "Completed", "Nadia", "Bilal"),
]


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)
    if conn.execute("SELECT COUNT(*) FROM help_requests").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO help_requests (title, description, category, location, lat, lng, urgency, status, requester_name, volunteer_name) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            SEED,
        )
        conn.execute("UPDATE help_requests SET completed_at = CURRENT_TIMESTAMP WHERE status = 'Completed'")
    conn.commit()
    conn.close()


init_db()


def clean(value, limit):
    return str(value or "").strip()[:limit]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/requests", methods=["GET"])
def list_requests():
    sql = "SELECT * FROM help_requests WHERE 1=1"
    args = []
    for field in ("category", "urgency", "status"):
        val = request.args.get(field, "").strip()
        if val:
            sql += f" AND {field} = ?"
            args.append(val)
    q = request.args.get("q", "").strip()
    if q:
        sql += " AND (title LIKE ? OR description LIKE ? OR location LIKE ?)"
        args += [f"%{q}%"] * 3
    if request.args.get("sort") == "newest":
        sql += " ORDER BY id DESC"
    else:
        sql += (" ORDER BY CASE urgency WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 ELSE 2 END,"
                " CASE status WHEN 'Open' THEN 0 WHEN 'Accepted' THEN 1 ELSE 2 END, id DESC")
    rows = db().execute(sql, args).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/requests", methods=["POST"])
def create_request():
    d = request.get_json(silent=True) or {}
    title = clean(d.get("title"), 100)
    desc = clean(d.get("description"), 500)
    name = clean(d.get("name"), 40)
    location = clean(d.get("location"), 80)
    category = d.get("category")
    urgency = d.get("urgency")
    if not (title and desc and name and location):
        return jsonify(error="Please fill in all fields."), 400
    if category not in CATEGORIES or urgency not in URGENCIES:
        return jsonify(error="Invalid category or urgency."), 400
    try:
        lat, lng = float(d.get("lat")), float(d.get("lng"))
    except (TypeError, ValueError):
        lat = lng = None
    cur = db().execute(
        "INSERT INTO help_requests (title, description, category, location, lat, lng, urgency, requester_name) VALUES (?,?,?,?,?,?,?,?)",
        (title, desc, category, location, lat, lng, urgency, name),
    )
    db().commit()
    row = db().execute("SELECT * FROM help_requests WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201


@app.route("/api/requests/<int:rid>/accept", methods=["POST"])
def accept_request(rid):
    name = clean((request.get_json(silent=True) or {}).get("name"), 40)
    if not name:
        return jsonify(error="Enter your name first."), 400
    row = db().execute("SELECT requester_name FROM help_requests WHERE id = ?", (rid,)).fetchone()
    if row is None:
        return jsonify(error="Request not found."), 404
    if row["requester_name"].lower() == name.lower():
        return jsonify(error="You can't accept your own request."), 400
    # Atomic: only succeeds if still Open, so two volunteers can't both claim it
    cur = db().execute(
        "UPDATE help_requests SET status='Accepted', volunteer_name=? WHERE id=? AND status='Open'", (name, rid))
    db().commit()
    if cur.rowcount == 0:
        return jsonify(error="Someone else already accepted this request."), 409
    return jsonify(ok=True)


@app.route("/api/requests/<int:rid>/complete", methods=["POST"])
def complete_request(rid):
    name = clean((request.get_json(silent=True) or {}).get("name"), 40)
    cur = db().execute(
        "UPDATE help_requests SET status='Completed', completed_at=CURRENT_TIMESTAMP "
        "WHERE id=? AND status='Accepted' AND volunteer_name=?", (rid, name))
    db().commit()
    if cur.rowcount == 0:
        return jsonify(error="Only the assigned volunteer can complete an accepted request."), 403
    return jsonify(ok=True)


@app.route("/api/stats")
def stats():
    c = db()
    one = lambda sql: c.execute(sql).fetchone()[0]
    return jsonify(
        total=one("SELECT COUNT(*) FROM help_requests"),
        open=one("SELECT COUNT(*) FROM help_requests WHERE status='Open'"),
        completed=one("SELECT COUNT(*) FROM help_requests WHERE status='Completed'"),
        volunteers=one("SELECT COUNT(DISTINCT volunteer_name) FROM help_requests WHERE volunteer_name IS NOT NULL"),
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
