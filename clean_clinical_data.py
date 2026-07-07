import os

import mysql.connector
from dotenv import load_dotenv

load_dotenv()


def db_config():
    return {
        "host": os.getenv("MYSQL_HOST", "srv2220.hstgr.io"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER", "u367206649_clinic_user"),
        "password": os.getenv("MYSQL_PASSWORD", "Clinic@2026!"),
        "database": os.getenv("MYSQL_DATABASE", "u367206649_clinic"),
        "autocommit": False,
    }


def main():
    tables = [
        "appointments",
        "prescriptions",
        "patients",
        "patient_id_sequences",
        "prescription_sequences",
    ]
    conn = mysql.connector.connect(**db_config())
    cursor = conn.cursor()
    try:
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        for table in tables:
            cursor.execute(f"TRUNCATE TABLE {table}")
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()
    print("Clinical data deleted permanently. Users and product catalog were kept.")


if __name__ == "__main__":
    main()
    
