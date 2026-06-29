import json
import os
import csv
from datetime import date
from functools import wraps
from io import BytesIO, StringIO

import mysql.connector
from openpyxl import load_workbook
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory, session
from flask_cors import CORS
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

# Backend Config: Flask API, MySQL connection, CORS, sessions, and static frontend hosting.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "frontend"))
cors_origins = [origin.strip() for origin in os.getenv("FRONTEND_ORIGINS", "").split(",") if origin.strip()]

app = Flask(__name__, static_folder=None)
app.secret_key = os.getenv("SECRET_KEY", "change-this-secret-key")
app.config.update(
    SESSION_COOKIE_SAMESITE=os.getenv("SESSION_COOKIE_SAMESITE", "Lax"),
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
)
if cors_origins:
    CORS(app, origins=cors_origins, supports_credentials=True)
else:
    CORS(app, supports_credentials=True)
database_ready = False


# Database Helpers: all MySQL reads/writes pass through these functions.
def db_config():
    return {
        "host": os.getenv("MYSQL_HOST", "localhost"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER", "root"),
        "password": os.getenv("MYSQL_PASSWORD", ""),
        "database": os.getenv("MYSQL_DATABASE", "clinic"),
        "autocommit": False,
    }


def get_db():
    return mysql.connector.connect(**db_config())


def query_all(sql, params=None):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(sql, params or ())
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def query_one(sql, params=None):
    rows = query_all(sql, params)
    return rows[0] if rows else None


def execute(sql, params=None):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(sql, params or ())
    conn.commit()
    new_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return new_id


def create_tables():
    statements = [
        """
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(80) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            role ENUM('receptionist', 'doctor') NOT NULL,
            full_name VARCHAR(140) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS patients (
            id INT AUTO_INCREMENT PRIMARY KEY,
            patient_id VARCHAR(40) NOT NULL UNIQUE,
            name VARCHAR(160) NOT NULL,
            age INT NOT NULL,
            gender ENUM('Female', 'Male', 'Other') NOT NULL,
            phone VARCHAR(30) NOT NULL,
            date_of_visit DATE NOT NULL,
            location_area VARCHAR(180) NOT NULL,
            main_concern TEXT NOT NULL,
            created_by VARCHAR(80) NOT NULL,
            deleted_at TIMESTAMP NULL DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_patient_search (name, phone, patient_id),
            INDEX idx_patient_gender (gender),
            INDEX idx_visit_date (date_of_visit)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS appointments (
            id INT AUTO_INCREMENT PRIMARY KEY,
            patient_db_id INT NOT NULL,
            appointment_date DATE NOT NULL,
            appointment_time VARCHAR(20) NOT NULL,
            doctor_name VARCHAR(120) DEFAULT 'Doctor',
            status ENUM('Scheduled', 'Completed', 'Cancelled') DEFAULT 'Scheduled',
            notes TEXT,
            created_by VARCHAR(80) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_db_id) REFERENCES patients(id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS product_catalog (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(220) NOT NULL,
            category ENUM('Medicine', 'Skin Care', 'Hair Care') NOT NULL DEFAULT 'Medicine',
            default_dose VARCHAR(120),
            default_notes VARCHAR(220),
            created_by VARCHAR(80) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY unique_catalog_item (name, category),
            INDEX idx_catalog_name (name),
            INDEX idx_catalog_category (category)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS prescriptions (
            id INT AUTO_INCREMENT PRIMARY KEY,
            prescription_no VARCHAR(40) NOT NULL UNIQUE,
            patient_db_id INT NOT NULL,
            prescription_date DATE NOT NULL,
            follow_up_date DATE,
            medicines JSON,
            skin_products JSON,
            hair_products JSON,
            session_recommended VARCHAR(140),
            session_type VARCHAR(180),
            treatment_notes TEXT,
            receptionist_instructions TEXT,
            created_by VARCHAR(80) NOT NULL,
            deleted_at TIMESTAMP NULL DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_db_id) REFERENCES patients(id),
            INDEX idx_prescription_date (prescription_date)
        )
        """,
    ]
    conn = get_db()
    cursor = conn.cursor()
    for statement in statements:
        cursor.execute(statement)
    conn.commit()
    cursor.close()
    conn.close()
    ensure_soft_delete_columns()


def ensure_soft_delete_columns():
    conn = get_db()
    cursor = conn.cursor()
    database = os.getenv("MYSQL_DATABASE", "clinic")
    for table in ["patients", "prescriptions"]:
        cursor.execute(
            """
            SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME='deleted_at'
            """,
            (database, table),
        )
        exists = cursor.fetchone()[0]
        if not exists:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN deleted_at TIMESTAMP NULL DEFAULT NULL")
    conn.commit()
    cursor.close()
    conn.close()


def seed_users():
    users = [
        ("reception", "Reception@123", "receptionist", "Receptionist"),
        ("doctor", "Doctor@123", "doctor", "Doctor"),
    ]
    for username, password, role, full_name in users:
        existing = query_one("SELECT id FROM users WHERE username=%s", (username,))
        if not existing:
            execute(
                "INSERT INTO users (username, password_hash, role, full_name) VALUES (%s, %s, %s, %s)",
                (username, generate_password_hash(password), role, full_name),
            )


def init_database():
    create_tables()
    seed_users()


# Auth Helpers: session login and optional role checking for protected API routes.
@app.before_request
def ensure_database_ready():
    global database_ready
    if not database_ready and request.path.startswith("/api/"):
        init_database()
        database_ready = True


def login_required(role=None):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if "user" not in session:
                return jsonify({"error": "Login required"}), 401
            if role and session["user"]["role"] != role:
                return jsonify({"error": "Access denied"}), 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def normalize_json_list(value):
    if isinstance(value, list):
        return value
    return []


def row_dates_to_string(row):
    for key, value in list(row.items()):
        if hasattr(value, "isoformat"):
            row[key] = value.isoformat()
    return row


def parse_json_field(value):
    if isinstance(value, str):
        return json.loads(value or "[]")
    return value or []


def next_patient_id():
    prefix = f"PT-{date.today().strftime('%Y%m%d')}-"
    row = query_one(
        "SELECT patient_id FROM patients WHERE patient_id LIKE %s ORDER BY patient_id DESC LIMIT 1",
        (f"{prefix}%",),
    )
    if not row:
        return f"{prefix}001"
    try:
        number = int(str(row["patient_id"]).replace(prefix, "")) + 1
    except ValueError:
        number = 1
    return f"{prefix}{number:03d}"


def rows_to_csv(rows, headers):
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def catalog_rows_from_upload(file_storage):
    filename = (file_storage.filename or "").lower()
    rows = []
    if filename.endswith(".xlsx"):
        workbook = load_workbook(BytesIO(file_storage.read()), data_only=True)
        sheet = workbook.active
        headers = [str(cell.value or "").strip().lower().replace(" ", "_") for cell in next(sheet.iter_rows(max_row=1))]
        for values in sheet.iter_rows(min_row=2, values_only=True):
            row = dict(zip(headers, values))
            if row.get("name"):
                rows.append(row)
    else:
        content = file_storage.read().decode("utf-8-sig")
        reader = csv.DictReader(StringIO(content))
        rows = [row for row in reader if row.get("name")]
    return rows


# Frontend Routes: Flask can serve the ready frontend directly when deployed together.
@app.route("/")
def home():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/<path:filename>")
def frontend_file(filename):
    return send_from_directory(FRONTEND_DIR, filename)


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "database": os.getenv("MYSQL_DATABASE", "clinic")})


# API Routes: authentication, patients, appointments, prescriptions, medicine library, exports, and backups.
@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    username = data.get("username", "").strip()
    password = data.get("password", "")
    user = query_one("SELECT * FROM users WHERE username=%s", (username,))
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid username or password"}), 401
    session["user"] = {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "full_name": user["full_name"],
    }
    return jsonify({"user": session["user"]})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "Logged out"})


@app.route("/api/me")
def me():
    return jsonify({"user": session.get("user")})


@app.route("/api/dashboard")
@login_required()
def dashboard():
    today = date.today().isoformat()
    total_patients = query_one("SELECT COUNT(*) AS count FROM patients")["count"]
    today_patients = query_one("SELECT COUNT(*) AS count FROM patients WHERE date_of_visit=%s", (today,))["count"]
    appointments = query_one("SELECT COUNT(*) AS count FROM appointments WHERE appointment_date=%s", (today,))["count"]
    prescriptions = query_one("SELECT COUNT(*) AS count FROM prescriptions")["count"]
    return jsonify(
        {
            "totalPatients": total_patients,
            "todayPatients": today_patients,
            "todayAppointments": appointments,
            "prescriptions": prescriptions,
        }
    )


@app.route("/api/patients", methods=["GET", "POST"])
@login_required()
def patients():
    if request.method == "POST":
        if session["user"]["role"] != "receptionist":
            return jsonify({"error": "Only receptionist can register patients"}), 403
        data = request.get_json(force=True)
        required = ["name", "age", "gender", "phone", "date_of_visit", "location_area", "main_concern"]
        missing = [field for field in required if not str(data.get(field, "")).strip()]
        if missing:
            return jsonify({"error": "Missing fields", "fields": missing}), 400
        patient_id = data.get("patient_id", "").strip() or next_patient_id()
        new_id = execute(
            """
            INSERT INTO patients
            (patient_id, name, age, gender, phone, date_of_visit, location_area, main_concern, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                patient_id,
                data["name"].strip(),
                int(data["age"]),
                data["gender"],
                data["phone"].strip(),
                data["date_of_visit"],
                data["location_area"].strip(),
                data["main_concern"].strip(),
                session["user"]["username"],
            ),
        )
        return jsonify({"message": "Patient registered", "id": new_id, "patient_id": patient_id}), 201

    search = request.args.get("search", "").strip()
    gender = request.args.get("gender", "").strip()
    sql = "SELECT * FROM patients WHERE 1=1"
    params = []
    if search:
        sql += " AND (name LIKE %s OR phone LIKE %s OR patient_id LIKE %s)"
        like = f"%{search}%"
        params.extend([like, like, like])
    if gender:
        sql += " AND gender=%s"
        params.append(gender)
    sql += " ORDER BY created_at DESC"
    rows = [row_dates_to_string(row) for row in query_all(sql, tuple(params))]
    return jsonify(rows)


@app.route("/api/patients/<int:patient_id>", methods=["PUT", "DELETE"])
@login_required("receptionist")
def patient_detail(patient_id):
    existing = query_one("SELECT id FROM patients WHERE id=%s", (patient_id,))
    if not existing:
        return jsonify({"error": "Patient not found"}), 404
    if request.method == "DELETE":
        execute("UPDATE patients SET deleted_at=NOW() WHERE id=%s", (patient_id,))
        return jsonify({"message": "Patient deleted"})

    data = request.get_json(force=True)
    required = ["name", "age", "gender", "phone", "date_of_visit", "location_area", "main_concern"]
    missing = [field for field in required if not str(data.get(field, "")).strip()]
    if missing:
        return jsonify({"error": "Missing fields", "fields": missing}), 400
    execute(
        """
        UPDATE patients
        SET name=%s, age=%s, gender=%s, phone=%s, date_of_visit=%s, location_area=%s, main_concern=%s
        WHERE id=%s
        """,
        (
            data["name"].strip(),
            int(data["age"]),
            data["gender"],
            data["phone"].strip(),
            data["date_of_visit"],
            data["location_area"].strip(),
            data["main_concern"].strip(),
            patient_id,
        ),
    )
    return jsonify({"message": "Patient updated", "id": patient_id})


@app.route("/api/patients/<int:patient_id>/restore", methods=["POST"])
@login_required("receptionist")
def restore_patient(patient_id):
    existing = query_one("SELECT id FROM patients WHERE id=%s", (patient_id,))
    if not existing:
        return jsonify({"error": "Patient not found"}), 404
    execute("UPDATE patients SET deleted_at=NULL WHERE id=%s", (patient_id,))
    return jsonify({"message": "Patient restored", "id": patient_id})


@app.route("/api/appointments", methods=["GET", "POST"])
@login_required("receptionist")
def appointments():
    if request.method == "POST":
        data = request.get_json(force=True)
        new_id = execute(
            """
            INSERT INTO appointments
            (patient_db_id, appointment_date, appointment_time, doctor_name, status, notes, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                int(data["patient_db_id"]),
                data["appointment_date"],
                data["appointment_time"],
                data.get("doctor_name", "Doctor"),
                data.get("status", "Scheduled"),
                data.get("notes", ""),
                session["user"]["username"],
            ),
        )
        return jsonify({"message": "Appointment saved", "id": new_id}), 201

    rows = query_all(
        """
        SELECT a.*, p.patient_id, p.name, p.phone
        FROM appointments a
        JOIN patients p ON p.id = a.patient_db_id
        ORDER BY a.appointment_date DESC, a.appointment_time DESC
        """
    )
    return jsonify([row_dates_to_string(row) for row in rows])


@app.route("/api/prescriptions", methods=["GET", "POST"])
@login_required()
def prescriptions():
    if request.method == "POST":
        if session["user"]["role"] != "doctor":
            return jsonify({"error": "Only doctor can save prescriptions"}), 403
        data = request.get_json(force=True)
        patient_db_id = int(data["patient_db_id"])
        prescription_no = f"RX-{date.today().strftime('%Y%m%d')}-{patient_db_id}-{query_one('SELECT COUNT(*) AS count FROM prescriptions')['count'] + 1}"
        new_id = execute(
            """
            INSERT INTO prescriptions
            (prescription_no, patient_db_id, prescription_date, follow_up_date, medicines, skin_products,
             hair_products, session_recommended, session_type, treatment_notes, receptionist_instructions, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                prescription_no,
                patient_db_id,
                data["prescription_date"],
                data.get("follow_up_date") or None,
                json.dumps(normalize_json_list(data.get("medicines"))),
                json.dumps(normalize_json_list(data.get("skin_products"))),
                json.dumps(normalize_json_list(data.get("hair_products"))),
                data.get("session_recommended", ""),
                data.get("session_type", ""),
                data.get("treatment_notes", ""),
                data.get("receptionist_instructions", ""),
                session["user"]["username"],
            ),
        )
        return jsonify({"message": "Prescription saved", "id": new_id, "prescription_no": prescription_no}), 201

    rows = query_all(
        """
        SELECT pr.*, p.patient_id, p.name AS patient_name, p.age, p.gender, p.phone, p.location_area, p.main_concern
        FROM prescriptions pr
        JOIN patients p ON p.id = pr.patient_db_id
        ORDER BY pr.created_at DESC
        """
    )
    for row in rows:
        row_dates_to_string(row)
        for field in ["medicines", "skin_products", "hair_products"]:
            row[field] = parse_json_field(row[field])
    return jsonify(rows)


@app.route("/api/sessions")
@login_required()
def sessions():
    search = request.args.get("search", "").strip()
    params = []
    sql = """
        SELECT pr.*, p.patient_id, p.name AS patient_name, p.age, p.gender, p.phone, p.location_area, p.main_concern
        FROM prescriptions pr
        JOIN patients p ON p.id = pr.patient_db_id
        WHERE 1=1
    """
    if search:
        sql += " AND (p.name LIKE %s OR p.patient_id LIKE %s)"
        like = f"%{search}%"
        params.extend([like, like])
    sql += " ORDER BY pr.prescription_date DESC, pr.created_at DESC"
    rows = query_all(sql, tuple(params))
    for row in rows:
        row_dates_to_string(row)
        for field in ["medicines", "skin_products", "hair_products"]:
            row[field] = parse_json_field(row[field])
    return jsonify(rows)


@app.route("/api/sessions/<int:session_id>", methods=["PUT", "DELETE"])
@login_required()
def session_detail(session_id):
    if session["user"]["role"] not in ["receptionist", "doctor"]:
        return jsonify({"error": "Access denied"}), 403
    existing = query_one("SELECT id FROM prescriptions WHERE id=%s", (session_id,))
    if not existing:
        return jsonify({"error": "Session not found"}), 404
    if request.method == "DELETE":
        execute("UPDATE prescriptions SET deleted_at=NOW() WHERE id=%s", (session_id,))
        return jsonify({"message": "Session deleted", "id": session_id})

    data = request.get_json(force=True)
    execute(
        """
        UPDATE prescriptions
        SET follow_up_date=%s, session_recommended=%s, session_type=%s,
            treatment_notes=%s, receptionist_instructions=%s
        WHERE id=%s
        """,
        (
            data.get("follow_up_date") or None,
            data.get("session_recommended", ""),
            data.get("session_type", ""),
            data.get("treatment_notes", ""),
            data.get("receptionist_instructions", ""),
            session_id,
        ),
    )
    return jsonify({"message": "Session updated", "id": session_id})


@app.route("/api/sessions/<int:session_id>/restore", methods=["POST"])
@login_required()
def restore_session(session_id):
    existing = query_one("SELECT id FROM prescriptions WHERE id=%s", (session_id,))
    if not existing:
        return jsonify({"error": "Session not found"}), 404
    execute("UPDATE prescriptions SET deleted_at=NULL WHERE id=%s", (session_id,))
    return jsonify({"message": "Session restored", "id": session_id})


@app.route("/api/prescriptions/<int:prescription_id>", methods=["PUT", "DELETE"])
@login_required("doctor")
def prescription_detail(prescription_id):
    existing = query_one("SELECT id, prescription_no FROM prescriptions WHERE id=%s", (prescription_id,))
    if not existing:
        return jsonify({"error": "Prescription not found"}), 404
    if request.method == "DELETE":
        execute("UPDATE prescriptions SET deleted_at=NOW() WHERE id=%s", (prescription_id,))
        return jsonify({"message": "Prescription deleted"})

    data = request.get_json(force=True)
    execute(
        """
        UPDATE prescriptions
        SET patient_db_id=%s, prescription_date=%s, follow_up_date=%s, medicines=%s, skin_products=%s,
            hair_products=%s, session_recommended=%s, session_type=%s, treatment_notes=%s,
            receptionist_instructions=%s
        WHERE id=%s
        """,
        (
            int(data["patient_db_id"]),
            data["prescription_date"],
            data.get("follow_up_date") or None,
            json.dumps(normalize_json_list(data.get("medicines"))),
            json.dumps(normalize_json_list(data.get("skin_products"))),
            json.dumps(normalize_json_list(data.get("hair_products"))),
            data.get("session_recommended", ""),
            data.get("session_type", ""),
            data.get("treatment_notes", ""),
            data.get("receptionist_instructions", ""),
            prescription_id,
        ),
    )
    return jsonify({"message": "Prescription updated", "id": prescription_id, "prescription_no": existing["prescription_no"]})


@app.route("/api/reports")
@login_required()
def reports():
    gender_rows = query_all("SELECT gender, COUNT(*) AS count FROM patients GROUP BY gender")
    concern_rows = query_all(
        "SELECT main_concern, COUNT(*) AS count FROM patients GROUP BY main_concern ORDER BY count DESC LIMIT 8"
    )
    return jsonify({"byGender": gender_rows, "topConcerns": concern_rows})


@app.route("/api/catalog", methods=["GET", "POST"])
@login_required()
def catalog():
    if request.method == "POST":
        data = request.get_json(force=True)
        name = data.get("name", "").strip()
        if not name:
            return jsonify({"error": "Name is required"}), 400
        execute(
            """
            INSERT INTO product_catalog (name, category, default_dose, default_notes, created_by)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE default_dose=VALUES(default_dose), default_notes=VALUES(default_notes)
            """,
            (
                name,
                data.get("category", "Medicine"),
                data.get("default_dose", ""),
                data.get("default_notes", ""),
                session["user"]["username"],
            ),
        )
        return jsonify({"message": "Catalog item saved"}), 201

    search = request.args.get("search", "").strip()
    params = []
    sql = "SELECT * FROM product_catalog WHERE 1=1"
    if search:
        sql += " AND name LIKE %s"
        params.append(f"%{search}%")
    sql += " ORDER BY name ASC"
    rows = [row_dates_to_string(row) for row in query_all(sql, tuple(params))]
    return jsonify(rows)


@app.route("/api/catalog/upload", methods=["POST"])
@login_required()
def upload_catalog():
    uploaded = request.files.get("file")
    if not uploaded:
        return jsonify({"error": "Upload CSV or XLSX file"}), 400
    rows = catalog_rows_from_upload(uploaded)
    saved = 0
    for row in rows:
        name = str(row.get("name") or row.get("medicine") or row.get("product") or "").strip()
        if not name:
            continue
        category = str(row.get("category") or "Medicine").strip()
        if category.lower().startswith("skin"):
            category = "Skin Care"
        elif category.lower().startswith("hair"):
            category = "Hair Care"
        else:
            category = "Medicine"
        execute(
            """
            INSERT INTO product_catalog (name, category, default_dose, default_notes, created_by)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE default_dose=VALUES(default_dose), default_notes=VALUES(default_notes)
            """,
            (
                name,
                category,
                str(row.get("dose") or row.get("default_dose") or ""),
                str(row.get("notes") or row.get("default_notes") or ""),
                session["user"]["username"],
            ),
        )
        saved += 1
    return jsonify({"message": "Catalog uploaded", "saved": saved})


@app.route("/api/export/<kind>")
@login_required()
def export_csv(kind):
    if kind == "patients":
        rows = [row_dates_to_string(row) for row in query_all("SELECT * FROM patients ORDER BY created_at DESC")]
        csv_text = rows_to_csv(rows, ["patient_id", "name", "age", "gender", "phone", "date_of_visit", "location_area", "main_concern", "created_at"])
    elif kind == "prescriptions":
        rows = [row_dates_to_string(row) for row in query_all("SELECT * FROM prescriptions ORDER BY created_at DESC")]
        csv_text = rows_to_csv(rows, ["prescription_no", "patient_db_id", "prescription_date", "follow_up_date", "medicines", "skin_products", "hair_products", "session_recommended", "session_type", "treatment_notes", "receptionist_instructions", "created_at"])
    elif kind == "sessions":
        rows = [row_dates_to_string(row) for row in query_all("SELECT prescription_no, prescription_date, follow_up_date, session_recommended, session_type, treatment_notes FROM prescriptions ORDER BY prescription_date DESC")]
        csv_text = rows_to_csv(rows, ["prescription_no", "prescription_date", "follow_up_date", "session_recommended", "session_type", "treatment_notes"])
    else:
        return jsonify({"error": "Unknown export"}), 404
    return app.response_class(csv_text, mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=clinic-{kind}.csv"})


@app.route("/api/backup")
@login_required()
def backup():
    data = {
        "patients": [row_dates_to_string(row) for row in query_all("SELECT * FROM patients")],
        "appointments": [row_dates_to_string(row) for row in query_all("SELECT * FROM appointments")],
        "prescriptions": [row_dates_to_string(row) for row in query_all("SELECT * FROM prescriptions")],
        "catalog": [row_dates_to_string(row) for row in query_all("SELECT * FROM product_catalog")],
    }
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=["table", "payload"])
    writer.writeheader()
    for table, rows in data.items():
        for row in rows:
            writer.writerow({"table": table, "payload": json.dumps(row, default=str)})
    return app.response_class(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=clinic-backup.csv"})


@app.route("/api/backup/import", methods=["POST"])
@login_required()
def import_backup():
    uploaded = request.files.get("file")
    if not uploaded:
        return jsonify({"error": "Upload backup CSV"}), 400
    content = uploaded.read().decode("utf-8-sig")
    imported = 0
    for row in csv.DictReader(StringIO(content)):
        table = row.get("table")
        payload = json.loads(row.get("payload") or "{}")
        if table == "patients":
            execute(
                """
                INSERT INTO patients (patient_id, name, age, gender, phone, date_of_visit, location_area, main_concern, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE name=VALUES(name), age=VALUES(age), gender=VALUES(gender), phone=VALUES(phone),
                date_of_visit=VALUES(date_of_visit), location_area=VALUES(location_area), main_concern=VALUES(main_concern)
                """,
                (payload.get("patient_id"), payload.get("name"), payload.get("age"), payload.get("gender"), payload.get("phone"), payload.get("date_of_visit"), payload.get("location_area"), payload.get("main_concern"), session["user"]["username"]),
            )
            imported += 1
        elif table == "catalog":
            execute(
                """
                INSERT INTO product_catalog (name, category, default_dose, default_notes, created_by)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE default_dose=VALUES(default_dose), default_notes=VALUES(default_notes)
                """,
                (payload.get("name"), payload.get("category"), payload.get("default_dose"), payload.get("default_notes"), session["user"]["username"]),
            )
            imported += 1
        elif table == "appointments":
            execute(
                """
                INSERT INTO appointments (patient_db_id, appointment_date, appointment_time, doctor_name, status, notes, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    payload.get("patient_db_id"),
                    payload.get("appointment_date"),
                    payload.get("appointment_time"),
                    payload.get("doctor_name", "Doctor"),
                    payload.get("status", "Scheduled"),
                    payload.get("notes", ""),
                    session["user"]["username"],
                ),
            )
            imported += 1
        elif table == "prescriptions":
            execute(
                """
                INSERT INTO prescriptions
                (prescription_no, patient_db_id, prescription_date, follow_up_date, medicines, skin_products,
                 hair_products, session_recommended, session_type, treatment_notes, receptionist_instructions, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE follow_up_date=VALUES(follow_up_date), medicines=VALUES(medicines),
                skin_products=VALUES(skin_products), hair_products=VALUES(hair_products), session_recommended=VALUES(session_recommended),
                session_type=VALUES(session_type), treatment_notes=VALUES(treatment_notes),
                receptionist_instructions=VALUES(receptionist_instructions)
                """,
                (
                    payload.get("prescription_no"),
                    payload.get("patient_db_id"),
                    payload.get("prescription_date"),
                    payload.get("follow_up_date") or None,
                    payload.get("medicines") or "[]",
                    payload.get("skin_products") or "[]",
                    payload.get("hair_products") or "[]",
                    payload.get("session_recommended", ""),
                    payload.get("session_type", ""),
                    payload.get("treatment_notes", ""),
                    payload.get("receptionist_instructions", ""),
                    session["user"]["username"],
                ),
            )
            imported += 1
    return jsonify({"message": "Backup imported", "imported": imported})


if __name__ == "__main__":
    init_database()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
