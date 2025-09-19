import os
import psycopg2
from psycopg2.extras import execute_values
import pandas as pd
import yaml
from datetime import datetime, timezone, timedelta
from typing import Optional
import hashlib
import secrets
import hmac
import json
import apprise
from dotenv import load_dotenv
from cryptography.fernet import Fernet

def load_config():
    """Load configuration from YAML file"""
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
        if not os.path.exists(config_path):
            return {}
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        return {}

def get_db_conn():
    """Create a DB connection using environment variables only.

    Required env vars (e.g. from .env / Compose):
      POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD

    No fallback to config.yaml to avoid conflicting sources.
    """
    # Ensure .env is loaded (no-op if already loaded)
    load_env_file()
    host = os.getenv('POSTGRES_HOST')
    port = os.getenv('POSTGRES_PORT')
    db = os.getenv('POSTGRES_DB')
    user = os.getenv('POSTGRES_USER')
    pwd = os.getenv('POSTGRES_PASSWORD')

    missing = [k for k, v in {
        'POSTGRES_HOST': host,
        'POSTGRES_PORT': port,
        'POSTGRES_DB': db,
        'POSTGRES_USER': user,
        'POSTGRES_PASSWORD': pwd,
    }.items() if not v]

    if missing:
        msg = (
            f"Missing required DB env vars: {', '.join(missing)}. "
            "Please set them in .env or environment (POSTGRES_HOST/PORT/DB/USER/PASSWORD). "
            "Note: config.yaml timescaledb settings are no longer used."
        )
        print(msg)
        raise RuntimeError(msg)

    try:
        return psycopg2.connect(host=host, port=int(port), dbname=db, user=user, password=pwd)
    except Exception as e:
        print(f"Failed to connect to DB at {host}:{port}/{db} as {user}: {e}")
        raise

def init_timescaledb_schema():
    with get_db_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE EXTENSION IF NOT EXISTS timescaledb;
            CREATE TABLE IF NOT EXISTS measurements (
              ci TEXT NOT NULL,
              ts TIMESTAMPTZ NOT NULL,
              status SMALLINT NOT NULL,
              PRIMARY KEY (ci, ts)
            );
            SELECT create_hypertable('measurements','ts', if_not_exists => TRUE);
            
            CREATE TABLE IF NOT EXISTS ci_metadata (
              ci TEXT PRIMARY KEY,
              name TEXT,
              organization TEXT,
              product TEXT,
              bu TEXT,
              tid TEXT,
              pdt TEXT,
              comment TEXT,
              updated_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        # Optional: continuous aggregates, retention policies can be added later

def write_measurements(rows):
    """rows: iterable of (ci, ts(datetime|str|epoch), status:int)"""
    if not rows:
        return 0
    with get_db_conn() as conn, conn.cursor() as cur:
        execute_values(cur,
            "INSERT INTO measurements (ci, ts, status) VALUES %s ON CONFLICT DO NOTHING",
            rows
        )
        return cur.rowcount

def update_ci_metadata(ci_data):
    """Aktualisiert CI-Metadaten in TimescaleDB."""
    if not ci_data:
        return 0
    with get_db_conn() as conn, conn.cursor() as cur:
        execute_values(cur,
            """INSERT INTO ci_metadata (ci, name, organization, product, bu, tid, pdt, comment) 
               VALUES %s 
               ON CONFLICT (ci) DO UPDATE SET 
                 name = EXCLUDED.name,
                 organization = EXCLUDED.organization,
                 product = EXCLUDED.product,
                 bu = EXCLUDED.bu,
                 tid = EXCLUDED.tid,
                 pdt = EXCLUDED.pdt,
                 comment = EXCLUDED.comment,
                 updated_at = NOW()""",
            ci_data
        )
        return cur.rowcount

def ingest_hdf5_to_timescaledb(hdf5_path: str, max_rows: Optional[int] = None) -> int:
    """Streamt availability aus HDF5 und schreibt idempotent nach TimescaleDB.
    max_rows: optionales Limit zur Drosselung pro Lauf.
    """
    # Function is obsolete and will be removed
    return 0

def setup_timescaledb_retention(keep_days: int = 185) -> None:
    """Setzt eine Retention-Policy (drop_chunks) auf measurements; idempotent."""
    with get_db_conn() as conn, conn.cursor() as cur:
        # add_retention_policy ist idempotent mit if_not_exists => TRUE
        sql = f"SELECT add_retention_policy('measurements', INTERVAL '{int(keep_days)} days', if_not_exists => TRUE);"
        cur.execute(sql)

def init_otp_database_schema():
    """Initialize database schema for multi-user OTP system"""
    with get_db_conn() as conn, conn.cursor() as cur:
        # Create users table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                email_hash TEXT NOT NULL,
                email_salt TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                last_login TIMESTAMPTZ,
                failed_login_attempts INTEGER DEFAULT 0,
                locked_until TIMESTAMPTZ
            );
        """)
        
        # Create otp_codes table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS otp_codes (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                otp_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                used BOOLEAN DEFAULT FALSE,
                ip_address TEXT
            );
        """)
        
        # Create notification_profiles table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notification_profiles (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                type TEXT NOT NULL CHECK (type IN ('whitelist', 'blacklist')),
                ci_list TEXT[] DEFAULT '{}',
                apprise_urls TEXT[] DEFAULT '{}',
                apprise_urls_hash TEXT[],
                apprise_urls_salt TEXT[],
                email_notifications BOOLEAN DEFAULT FALSE,
                email_address TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                last_tested_at TIMESTAMPTZ,
                test_result TEXT,
                unsubscribe_token TEXT UNIQUE
            );
        """)
        
        # Create indexes for better performance
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_email_hash ON users(email_hash);
            CREATE INDEX IF NOT EXISTS idx_otp_codes_user_id ON otp_codes(user_id);
            CREATE INDEX IF NOT EXISTS idx_otp_codes_expires_at ON otp_codes(expires_at);
            CREATE INDEX IF NOT EXISTS idx_notification_profiles_user_id ON notification_profiles(user_id);
            CREATE INDEX IF NOT EXISTS idx_notification_profiles_unsubscribe_token ON notification_profiles(unsubscribe_token);
        """)

def run_db_migrations():
    """Run idempotent DB migrations for production upgrades.

    - Ensure columns and indexes on notification_profiles
    - Ensure users/otp_codes tables and indexes exist
    """
    with get_db_conn() as conn, conn.cursor() as cur:
        # 1) Ensure users table exists (first - referenced by others)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                email_hash TEXT NOT NULL,
                email_salt TEXT NOT NULL,
                email_encrypted TEXT,
                email_enc_salt TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                last_login TIMESTAMPTZ,
                failed_login_attempts INTEGER DEFAULT 0,
                locked_until TIMESTAMPTZ
            )
        """)
        # Add columns for encrypted email if missing
        cur.execute("""
            ALTER TABLE IF EXISTS users
              ADD COLUMN IF NOT EXISTS email_encrypted TEXT,
              ADD COLUMN IF NOT EXISTS email_enc_salt TEXT
        """)

        # 2) Ensure otp_codes table and indexes
        cur.execute("""
            CREATE TABLE IF NOT EXISTS otp_codes (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                otp_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                used BOOLEAN DEFAULT FALSE,
                ip_address TEXT
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_otp_codes_user_id ON otp_codes(user_id)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_otp_codes_expires_at ON otp_codes(expires_at)
        """)

        # 3) Ensure notification_profiles table exists (latest schema)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notification_profiles (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                type TEXT NOT NULL CHECK (type IN ('whitelist', 'blacklist')),
                ci_list TEXT[] DEFAULT '{}',
                apprise_urls TEXT[] DEFAULT '{}',
                apprise_urls_hash TEXT[],
                apprise_urls_salt TEXT[],
                email_notifications BOOLEAN DEFAULT FALSE,
                email_address TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                last_tested_at TIMESTAMPTZ,
                test_result TEXT,
                unsubscribe_token TEXT UNIQUE
            )
        """)
        # Ensure new columns on notification_profiles
        cur.execute("""
            ALTER TABLE IF EXISTS notification_profiles
              ADD COLUMN IF NOT EXISTS apprise_urls_hash TEXT[],
              ADD COLUMN IF NOT EXISTS apprise_urls_salt TEXT[],
              ADD COLUMN IF NOT EXISTS email_notifications BOOLEAN DEFAULT FALSE,
              ADD COLUMN IF NOT EXISTS email_address TEXT,
              ADD COLUMN IF NOT EXISTS unsubscribe_token TEXT UNIQUE
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_notification_profiles_unsubscribe_token
              ON notification_profiles(unsubscribe_token)
        """)

        # 5) Ensure notification_logs table for extended statistics
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notification_logs (
                id SERIAL PRIMARY KEY,
                profile_id INTEGER REFERENCES notification_profiles(id) ON DELETE CASCADE,
                ci TEXT NOT NULL,
                notification_type TEXT NOT NULL CHECK (notification_type IN ('incident', 'recovery')),
                sent_at TIMESTAMPTZ DEFAULT NOW(),
                delivery_status TEXT DEFAULT 'sent' CHECK (delivery_status IN ('sent', 'failed', 'pending')),
                error_message TEXT,
                recipient_type TEXT CHECK (recipient_type IN ('email', 'apprise')),
                recipient_count INTEGER DEFAULT 1
            )
        """)
        
        # Indexes for performance
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_notification_logs_sent_at 
              ON notification_logs(sent_at)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_notification_logs_profile_ci 
              ON notification_logs(profile_id, ci)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_notification_logs_type_status 
              ON notification_logs(notification_type, delivery_status)
        """)

        # 6) Ensure page_views table for visitor statistics
        cur.execute("""
            CREATE TABLE IF NOT EXISTS page_views (
                id SERIAL PRIMARY KEY,
                page TEXT NOT NULL,
                session_id TEXT NOT NULL,
                user_agent_hash TEXT,
                referrer TEXT,
                ts TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        
        # Indexes for page_views performance
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_page_views_ts 
              ON page_views(ts)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_page_views_page 
              ON page_views(page)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_page_views_session 
              ON page_views(session_id)
        """)

        # Sanitize existing PII: replace plain emails with hashes where detectable
        try:
            cur.execute("""
                UPDATE users
                SET email = email_hash
                WHERE email ~ '^[^@]+@[^@]+\.[^@]+$'
            """)
            # Null out any stored profile email addresses
            cur.execute("""
                ALTER TABLE IF EXISTS notification_profiles
                  ALTER COLUMN email_address DROP NOT NULL
            """)
            cur.execute("""
                UPDATE notification_profiles
                SET email_address = NULL
                WHERE email_address IS NOT NULL
            """)
        except Exception as _e:
            # best-effort; continue
            pass
        conn.commit()

def get_timescaledb_ci_data() -> pd.DataFrame:
    """Lädt CI-Daten aus TimescaleDB für Statistiken."""
    with get_db_conn() as conn:
        # Lade alle CIs mit ihren aktuellen Status und Metadaten
        query = """
        WITH latest_status AS (
            SELECT DISTINCT ON (ci) 
                ci, 
                ts, 
                status,
                LAG(status) OVER (PARTITION BY ci ORDER BY ts) as prev_status
            FROM measurements 
            ORDER BY ci, ts DESC
        ),
        ci_metadata AS (
            SELECT 
                ci,
                name,
                organization,
                product,
                bu,
                tid,
                pdt,
                comment
            FROM ci_metadata
        )
        SELECT 
            ls.ci,
            ls.status as current_availability,
            ls.ts as time,
            COALESCE(cm.name, '') as name,
            COALESCE(cm.organization, '') as organization,
            COALESCE(cm.product, '') as product,
            COALESCE(cm.bu, '') as bu,
            COALESCE(cm.tid, '') as tid,
            COALESCE(cm.pdt, '') as pdt,
            COALESCE(cm.comment, '') as comment,
            CASE 
                WHEN ls.status = 1 AND ls.prev_status = 0 THEN 1 
                ELSE 0 
            END as availability_difference
        FROM latest_status ls
        LEFT JOIN ci_metadata cm ON ls.ci = cm.ci
        ORDER BY ls.ci
        """
        with conn.cursor() as cur:
            cur.execute(query)
            results = cur.fetchall()
            return pd.DataFrame(results, columns=[
                'ci', 'current_availability', 'time', 'name', 'organization', 'product', 
                'bu', 'tid', 'pdt', 'comment', 'availability_difference'
            ])

def get_recent_incidents(limit: int = 5) -> list:
    """Lädt die letzten Incidents aus TimescaleDB mit Status-Informationen."""
    import gc
    
    with get_db_conn() as conn:
        incidents_query = """
        WITH incident_transitions AS (
            SELECT 
                ci,
                ts,
                status,
                LAG(status) OVER (PARTITION BY ci ORDER BY ts) as prev_status,
                LEAD(ts) OVER (PARTITION BY ci ORDER BY ts) as next_ts
            FROM measurements
            ORDER BY ci, ts
        ),
        incidents AS (
            SELECT 
                ci,
                ts as incident_start,
                next_ts as incident_end,
                CASE 
                    WHEN next_ts IS NOT NULL THEN 
                        EXTRACT(EPOCH FROM (next_ts - ts)) / 60.0
                    ELSE 
                        EXTRACT(EPOCH FROM (NOW() - ts)) / 60.0
                END as duration_minutes,
                CASE 
                    WHEN next_ts IS NULL THEN 'ongoing'
                    ELSE 'resolved'
                END as status
            FROM incident_transitions
            WHERE status = 0 AND prev_status = 1
        )
        SELECT 
            i.ci,
            i.incident_start,
            i.incident_end,
            i.duration_minutes,
            i.status,
            cm.name,
            cm.organization,
            cm.product
        FROM incidents i
        LEFT JOIN ci_metadata cm ON i.ci = cm.ci
        ORDER BY i.incident_start DESC
        LIMIT %s
        """
        
        with conn.cursor() as cur:
            cur.execute(incidents_query, (limit,))
            results = cur.fetchall()
            
            incidents = []
            for row in results:
                incidents.append({
                    'ci': row[0],
                    'incident_start': row[1],
                    'incident_end': row[2],
                    'duration_minutes': float(row[3]) if row[3] else 0.0,
                    'status': row[4],
                    'name': row[5] or 'Unbekannt',
                    'organization': row[6] or 'Unbekannt',
                    'product': row[7] or 'Unbekannt'
                })
            
            # Clean up
            del results
            gc.collect()
            
            return incidents

def get_timescaledb_statistics_data() -> dict:
    """Lädt erweiterte Statistiken aus TimescaleDB."""
    import gc
    
    with get_db_conn() as conn:
        # Gesamtstatistiken mit korrekter Zeitberechnung
        stats_query = """
        WITH time_bounds AS (
            SELECT 
                MIN(ts) as earliest_ts,
                MAX(ts) as latest_ts,
                COUNT(*) as total_datapoints,
                EXTRACT(EPOCH FROM (MAX(ts) - MIN(ts))) / 60.0 as total_recording_minutes
            FROM measurements
        ),
        ci_time_stats AS (
            SELECT 
                ci,
                COUNT(*) as datapoints,
                MIN(ts) as first_seen,
                MAX(ts) as last_seen,
                -- Vereinfachte Berechnung: 5 Minuten pro Datensatz
                SUM(CASE WHEN status = 1 THEN 5.0 ELSE 0 END) as uptime_minutes,
                SUM(CASE WHEN status = 0 THEN 5.0 ELSE 0 END) as downtime_minutes
            FROM measurements
            GROUP BY ci
        ),
        incident_stats AS (
            SELECT 
                ci,
                COUNT(*) as incidents,
                SUM(CASE WHEN status = 0 THEN 5.0 ELSE 0 END) as downtime_minutes
            FROM (
                SELECT 
                    ci,
                    status,
                    LAG(status) OVER (PARTITION BY ci ORDER BY ts) as prev_status
                FROM measurements
            ) t
            WHERE status = 0 AND prev_status = 1
            GROUP BY ci
        )
        SELECT 
            (SELECT COUNT(DISTINCT ci) FROM measurements) as total_cis,
            (SELECT COUNT(DISTINCT ci) FROM measurements m1 
             WHERE m1.ci IN (
                 SELECT ci FROM measurements m2 
                 WHERE m2.ts = (SELECT MAX(ts) FROM measurements m3 WHERE m3.ci = m2.ci)
                 AND m2.status = 1
             )) as currently_available,
            (SELECT total_datapoints FROM time_bounds) as total_datapoints,
            (SELECT total_recording_minutes FROM time_bounds) as total_recording_minutes,
            (SELECT earliest_ts FROM time_bounds) as earliest_timestamp,
            (SELECT latest_ts FROM time_bounds) as latest_timestamp,
            (SELECT SUM(uptime_minutes) FROM ci_time_stats) as overall_uptime_minutes,
            (SELECT SUM(downtime_minutes) FROM ci_time_stats) as overall_downtime_minutes,
            (SELECT SUM(incidents) FROM incident_stats) as total_incidents,
            (SELECT CASE 
                WHEN SUM(incidents) > 0 THEN SUM(downtime_minutes) / SUM(incidents)
                ELSE 0 
             END FROM incident_stats) as mttr_minutes_mean
        """
        
        with conn.cursor() as cur:
            cur.execute(stats_query)
            result = cur.fetchone()
            stats_result = {
                'total_cis': result[0] if result[0] else 0,
                'currently_available': result[1] if result[1] else 0,
                'total_datapoints': result[2] if result[2] else 0,
                'total_recording_minutes': result[3] if result[3] else 0,
                'earliest_timestamp': result[4] if result[4] else None,
                'latest_timestamp': result[5] if result[5] else None,
                'overall_uptime_minutes': result[6] if result[6] else 0,
                'overall_downtime_minutes': result[7] if result[7] else 0,
                'total_incidents': result[8] if result[8] else 0,
                'mttr_minutes_mean': result[9] if result[9] else 0
            }

        # Datenbankgröße in MB bestimmen
        database_size_mb = 0.0
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_database_size(current_database()) AS size_bytes")
                size_row = cur.fetchone()
                if size_row and size_row[0] is not None:
                    database_size_mb = float(size_row[0]) / (1024.0 * 1024.0)
        except Exception:
            # Still allow stats to be returned even if size query fails
            database_size_mb = 0.0
        
        # CI-spezifische Metriken mit korrekter Zeitberechnung
        ci_metrics_query = """
        WITH         ci_time_stats AS (
            SELECT 
                ci,
                COUNT(*) as datapoints,
                MIN(ts) as first_seen,
                MAX(ts) as last_seen,
                -- Vereinfachte Berechnung: 5 Minuten pro Datensatz
                SUM(CASE WHEN status = 1 THEN 5.0 ELSE 0 END) as uptime_minutes,
                SUM(CASE WHEN status = 0 THEN 5.0 ELSE 0 END) as downtime_minutes
            FROM measurements
            GROUP BY ci
        ),
        incident_metrics AS (
            SELECT 
                ci,
                COUNT(*) as incidents
            FROM (
                SELECT 
                    ci,
                    status,
                    LAG(status) OVER (PARTITION BY ci ORDER BY ts) as prev_status
                FROM measurements
            ) t
            WHERE status = 0 AND prev_status = 1
            GROUP BY ci
        )
        SELECT 
            cts.ci,
            cts.datapoints,
            cts.uptime_minutes,
            cts.downtime_minutes,
            cts.first_seen,
            cts.last_seen,
            COALESCE(im.incidents, 0) as incidents,
            CASE 
                WHEN (cts.uptime_minutes + cts.downtime_minutes) > 0 THEN 
                    (cts.uptime_minutes / (cts.uptime_minutes + cts.downtime_minutes)) * 100
                ELSE 100.0
            END as availability_percentage
        FROM ci_time_stats cts
        LEFT JOIN incident_metrics im ON cts.ci = im.ci
        ORDER BY COALESCE(im.incidents, 0) DESC, availability_percentage ASC
        LIMIT 10
        """
        
        with conn.cursor() as cur:
            cur.execute(ci_metrics_query)
            results = cur.fetchall()
            ci_metrics = pd.DataFrame(results, columns=[
                'ci', 'datapoints', 'uptime_minutes', 'downtime_minutes', 
                'first_seen', 'last_seen', 'incidents', 'availability_percentage'
            ])
            
            # Clean up large result set immediately
            del results
            gc.collect()
        
        # Berechne Gesamtverfügbarkeit
        overall_uptime = float(stats_result['overall_uptime_minutes']) if stats_result['overall_uptime_minutes'] is not None else 0
        overall_downtime = float(stats_result['overall_downtime_minutes']) if stats_result['overall_downtime_minutes'] is not None else 0
        total_time = overall_uptime + overall_downtime
        overall_availability = (overall_uptime / total_time * 100) if total_time > 0 else 100.0
        
        # Convert DataFrame to dict and clean up
        top_unstable_cis = ci_metrics.to_dict('records')
        del ci_metrics
        gc.collect()
        
        return {
            'total_cis': int(stats_result['total_cis']),
            'currently_available': int(stats_result['currently_available']),
            'currently_unavailable': int(stats_result['total_cis']) - int(stats_result['currently_available']),
            'total_datapoints': int(stats_result['total_datapoints']),
            'total_recording_minutes': float(stats_result['total_recording_minutes']),
            'earliest_timestamp': stats_result['earliest_timestamp'],
            'latest_timestamp': stats_result['latest_timestamp'],
            'overall_uptime_minutes': float(overall_uptime),
            'overall_downtime_minutes': float(overall_downtime),
            'overall_availability_percentage_rollup': float(overall_availability),
            'total_incidents': int(stats_result['total_incidents']),
            'mttr_minutes_mean': float(stats_result['mttr_minutes_mean']),
            'database_size_mb': float(database_size_mb),
            'top_unstable_cis': top_unstable_cis,
            'calculated_at': time.time()
        }
# Import packages
import numpy as np
import pandas as pd

import requests, json, time, pytz, os
from datetime import datetime
from tzlocal import get_localzone
import smtplib
from email.message import EmailMessage
from email.mime.text import MIMEText
import apprise
import threading
from collections import OrderedDict
import re
import html as htmllib

# Add dotenv import
from dotenv import load_dotenv
import hmac

# Note: HDF5 cache removed - now using TimescaleDB only

def generate_salt():
    """Generate a random salt for hashing"""
    import random
    import string
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(64))

def hash_with_salt(data, salt):
    """Hash data with salt using SHA-256"""
    import random
    import string
    
    if not data or not salt or data == "" or salt == "":
        # Generate a fallback salt if none provided
        if not salt:
            salt = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(64))
        if not data:
            raise ValueError("Data cannot be empty")
    return hashlib.sha256((str(data) + str(salt)).encode()).hexdigest()

def generate_otp():
    """Generate a 6-digit numeric OTP"""
    import random
    return str(random.randint(100000, 999999))

def generate_encryption_key():
    """Generate a encryption key for sensitive data"""
    return Fernet.generate_key()

def encrypt_data(data, key):
    """Encrypt data using Fernet encryption"""
    if not data:
        return None, None
    f = Fernet(key)
    salt = generate_salt()
    encrypted_data = f.encrypt((data + salt).encode())
    return encrypted_data.decode(), salt

def decrypt_data(encrypted_data, salt, key):
    """Decrypt data using Fernet encryption"""
    if not encrypted_data or not salt or not key:
        return None
    try:
        f = Fernet(key)
        decrypted_data = f.decrypt(encrypted_data.encode())
        # Remove the salt from the end
        original_data = decrypted_data.decode()[:-len(salt)]
        return original_data
    except Exception:
        return None

def create_user(email):
    """Create a new user with hashed email"""
    salt = generate_salt()
    if not salt:
        raise Exception("Failed to generate salt for user")
    email_hash = hash_with_salt(email.lower(), salt)
    # Encrypt email for reversible use in notifications
    encryption_key = os.getenv('ENCRYPTION_KEY')
    if encryption_key:
        encryption_key = encryption_key.encode()
    else:
        encryption_key = generate_encryption_key()
    email_encrypted, email_enc_salt = encrypt_data(email.lower(), encryption_key)
    
    with get_db_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute("""
                INSERT INTO users (email, email_hash, email_salt, email_encrypted, email_enc_salt)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (email_hash, email_hash, salt, email_encrypted, email_enc_salt))
            user_id = cur.fetchone()[0]
            return user_id
        except psycopg2.IntegrityError:
            # User already exists, get the existing user
            cur.execute("""
                SELECT id FROM users WHERE email_hash = %s AND email_salt = %s
            """, (email_hash, salt))
            result = cur.fetchone()
            return result[0] if result else None

def get_user_by_email(email):
    """Get user by email"""
    with get_db_conn() as conn, conn.cursor() as cur:
        # We need to check all users to find a match
        cur.execute("""
            SELECT id, email, email_hash, email_salt, failed_login_attempts, locked_until, email_encrypted, email_enc_salt
            FROM users
        """)
        users = cur.fetchall()
        
        email_lower = email.lower()
        for user in users:
            user_id, user_email, email_hash, email_salt, failed_attempts, locked_until, email_encrypted, email_enc_salt = user
            # Hash the provided email with the user's salt
            provided_email_hash = hash_with_salt(email_lower, email_salt)
            if hmac.compare_digest(email_hash, provided_email_hash):
                return user
                
        return None

def generate_otp_for_user(user_id, ip_address=None):
    """Generate and store OTP for user"""
    try:
        otp = generate_otp()
        salt = generate_salt()
        
        # Debug: Check if otp and salt are valid
        print(f"Debug: otp={otp}, salt={salt}")
        
        if not otp or not salt:
            raise Exception(f"OTP or salt generation failed: otp={otp}, salt={salt}")
        
        otp_hash = hash_with_salt(otp, salt)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        
        with get_db_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO otp_codes (user_id, otp_hash, salt, expires_at, ip_address)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (user_id, otp_hash, salt, expires_at, ip_address))
            result = cur.fetchone()
            if result:
                otp_id = result[0]
                return otp, otp_id
            else:
                raise Exception("Failed to insert OTP into database")
    except Exception as e:
        print(f"Error in generate_otp_for_user: {e}")
        return None, None

def validate_otp(user_id, otp):
    """Validate OTP for user"""
    with get_db_conn() as conn, conn.cursor() as cur:
        # Get the most recent unused OTP for the user
        cur.execute("""
            SELECT id, otp_hash, salt, expires_at FROM otp_codes
            WHERE user_id = %s AND used = FALSE AND expires_at > NOW()
            ORDER BY created_at DESC LIMIT 1
        """, (user_id,))
        result = cur.fetchone()
        
        if not result:
            return False
            
        otp_id, otp_hash, salt, expires_at = result
        
        # Hash the provided OTP with the stored salt
        provided_otp_hash = hash_with_salt(otp, salt)
        
        # Check if hashes match
        if hmac.compare_digest(otp_hash, provided_otp_hash):
            # Mark OTP as used
            cur.execute("""
                UPDATE otp_codes SET used = TRUE WHERE id = %s
            """, (otp_id,))
            # Update user's last login
            cur.execute("""
                UPDATE users SET last_login = NOW(), failed_login_attempts = 0
                WHERE id = %s
            """, (user_id,))
            return True
        else:
            # Increment failed login attempts
            cur.execute("""
                UPDATE users SET failed_login_attempts = failed_login_attempts + 1
                WHERE id = %s
            """, (user_id,))
            return False

def lock_user_account(user_id, lock_duration_minutes=30):
    """Lock user account after too many failed attempts"""
    lock_until = datetime.now(timezone.utc) + timedelta(minutes=lock_duration_minutes)
    
    with get_db_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE users SET locked_until = %s WHERE id = %s
        """, (lock_until, user_id))

def is_account_locked(user_id):
    """Check if user account is locked"""
    with get_db_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT locked_until FROM users WHERE id = %s
        """, (user_id,))
        result = cur.fetchone()
        if result and result[0]:
            return result[0] > datetime.now(timezone.utc)
        return False

def update_file(file_name, url):
    """
    Gets current data from API and updates TimescaleDB

    Args:
        file_name (str): Path to hdf5 file (kept for compatibility, not used)
        url (str): URL of API

    Returns:
        None
    """
    try:
        # Get data from API
        response = requests.get(url, timeout=30)  # Add timeout
        response.raise_for_status()  # Raise exception for bad status codes
        data = json.loads(response.text)
        df = pd.DataFrame(data)
        
        # Prepare data for TimescaleDB
        measurements_data = []
        ci_metadata_data = []
        
        # Process all configuration items
        for idx in range(len(df)):
            ci = df.iloc[idx]
            ci_id = str(ci["ci"])
            
            # Availability data
            av = int(ci["availability"])
            utc_time = datetime.strptime(ci["time"], '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=pytz.UTC)
            
            # Prepare TimescaleDB data
            measurements_data.append((ci_id, utc_time, av))
            ci_metadata_data.append((
                ci_id,
                str(ci.get("name", "")),
                str(ci.get("organization", "")),
                str(ci.get("product", "")),
                str(ci.get("bu", "")),
                str(ci.get("tid", "")),
                str(ci.get("pdt", "")),
                str(ci.get("comment", ""))
            ))
        
        # Write to TimescaleDB
        if measurements_data:
            try:
                init_timescaledb_schema()
                write_measurements(measurements_data)
                update_ci_metadata(ci_metadata_data)
                print(f"Written {len(measurements_data)} measurements and {len(ci_metadata_data)} CI metadata to TimescaleDB")
            except Exception as e:
                print(f"TimescaleDB write failed: {e}")
                raise
        
    except requests.RequestException as e:
        print(f"Error fetching data from API: {e}")
        raise
    except Exception as e:
        print(f"Error updating data: {e}")
        raise

def get_availability_data_of_ci(file_name, ci):
    """
    Gets availability data for a specific configuration item from TimescaleDB

    Args:
        file_name (str): Path to hdf5 file (kept for compatibility, not used)
        ci (str): ID of the desired confirguration item

    Returns:
        DataFrame: Time series of the availability of the desired configuration item
    """
    try:
        # Get data from TimescaleDB
        with get_db_conn() as conn:
            query = """
            SELECT 
                ts as times,
                status as values
            FROM measurements 
            WHERE ci = %s 
            ORDER BY ts
            """
            with conn.cursor() as cur:
                cur.execute(query, [ci])
                results = cur.fetchall()
                df = pd.DataFrame(results, columns=['times', 'values'])
            if not df.empty:
                # Convert times to Europe/Berlin timezone
                df['times'] = pd.to_datetime(df['times']).dt.tz_convert('Europe/Berlin')
                return df
            else:
                return pd.DataFrame()
    except Exception as e:
        print(f"Error reading availability data for CI {ci} from TimescaleDB: {e}")
        return pd.DataFrame()

def get_data_of_all_cis(file_name):
    """
    Gets general data for all configuration items from TimescaleDB

    Args:
        file_name (str): Path to hdf5 file (kept for compatibility, not used)

    Returns:
        DataFrame: Basic information about all configuration items
    """
    try:
        # Get data from TimescaleDB
        with get_db_conn() as conn:
            query = """
            SELECT 
                cm.ci,
                COALESCE(cm.name, '') as name,
                COALESCE(cm.organization, '') as organization,
                COALESCE(cm.product, '') as product,
                COALESCE(cm.bu, '') as bu,
                COALESCE(cm.tid, '') as tid,
                COALESCE(cm.pdt, '') as pdt,
                COALESCE(cm.comment, '') as comment,
                ls.status as current_availability,
                ls.ts as time,
                CASE 
                    WHEN ls.status = 1 AND ls.prev_status = 0 THEN 1 
                    WHEN ls.status = 0 AND ls.prev_status = 1 THEN -1
                    ELSE 0 
                END as availability_difference
            FROM ci_metadata cm
            LEFT JOIN (
                SELECT DISTINCT ON (ci) 
                    ci, 
                    ts, 
                    status,
                    LAG(status) OVER (PARTITION BY ci ORDER BY ts) as prev_status
                FROM measurements 
                ORDER BY ci, ts DESC
            ) ls ON cm.ci = ls.ci
            ORDER BY cm.ci
            """
            with conn.cursor() as cur:
                cur.execute(query)
                results = cur.fetchall()
                df = pd.DataFrame(results, columns=[
                    'ci', 'name', 'organization', 'product', 'bu', 'tid', 'pdt', 'comment',
                    'current_availability', 'time', 'availability_difference'
                ])
            return df
    except Exception as e:
        print(f"Error reading all CIs from TimescaleDB: {e}")
        return pd.DataFrame()

def get_data_of_all_cis_from_timescaledb():
    """
    Gets general data for all configuration items from TimescaleDB
    
    Returns:
        DataFrame: General data of all configuration items
    """
    try:
        # Use the existing get_data_of_all_cis function which already has the right structure
        return get_data_of_all_cis(None)
    except Exception as e:
        print(f"Error getting data from TimescaleDB: {e}")
        return pd.DataFrame()

def get_data_of_ci(file_name, ci):
    """
    Gets general data for a specific configuration item from TimescaleDB.

    Note: Database connectivity is configured exclusively via environment
    variables (e.g. provided by Docker Compose .env). The file_name argument
    is retained for backwards compatibility but is ignored.

    Args:
        file_name (str): Unused. Kept for backwards compatibility.
        ci (str): ID of the desired configuration item

    Returns:
        DataFrame: General data of the desired configuration item
    """
    try:
        with get_db_conn() as conn:
            query = """
            SELECT 
                cm.ci,
                cm.name,
                cm.organization,
                cm.product,
                cm.bu,
                cm.tid,
                cm.pdt,
                cm.comment,
                ls.status as current_availability,
                ls.ts as time,
                CASE 
                    WHEN ls.status = 1 AND ls.prev_status = 0 THEN 1 
                    ELSE 0 
                END as availability_difference
            FROM ci_metadata cm
            LEFT JOIN (
                SELECT DISTINCT ON (ci) 
                    ci, 
                    ts, 
                    status,
                    LAG(status) OVER (PARTITION BY ci ORDER BY ts) as prev_status
                FROM measurements 
                WHERE ci = %s
                ORDER BY ci, ts DESC
            ) ls ON cm.ci = ls.ci
            WHERE cm.ci = %s
            """
            with conn.cursor() as cur:
                cur.execute(query, [ci, ci])
                results = cur.fetchall()
                df = pd.DataFrame(results, columns=[
                    'ci', 'name', 'organization', 'product', 'bu', 'tid', 'pdt', 'comment',
                    'current_availability', 'time', 'availability_difference'
                ])
            return df
    except Exception as e:
        print(f"Error reading CI {ci} from TimescaleDB: {e}")
        return pd.DataFrame()

def pretty_timestamp(timestamp):
    """
    Converts UTC timestamp to pretty formatted local time

    Args:
        timestamp (str or pandas.Timestamp): UTC timestamp from API or database

    Returns:
        str: pretty formatted timestamp in local time
    """
    # Handle pandas Timestamp objects
    if hasattr(timestamp, 'to_pydatetime'):
        utc_time = timestamp.to_pydatetime()
        if utc_time.tzinfo is None:
            utc_time = utc_time.replace(tzinfo=pytz.UTC)
    else:
        # Handle string timestamps - try multiple formats
        formats = [
            '%Y-%m-%dT%H:%M:%S.%fZ',
            '%Y-%m-%d %H:%M:%S.%f%z',
            '%Y-%m-%d %H:%M:%S%z',
            '%Y-%m-%dT%H:%M:%S%z'
        ]
        utc_time = None
        for fmt in formats:
            try:
                utc_time = datetime.strptime(timestamp, fmt)
                if utc_time.tzinfo is None:
                    utc_time = utc_time.replace(tzinfo=pytz.UTC)
                break
            except ValueError:
                continue
        
        if utc_time is None:
            # Fallback: return timestamp as-is
            return str(timestamp)
    
    berlin_time = utc_time.astimezone(pytz.timezone('Europe/Berlin'))
    formatted_time = berlin_time.strftime('%d.%m.%Y %H:%M:%S Uhr')
    return formatted_time

def send_mail(smtp_settings, recipients, subject, html_message):
    """
    Sends a html-formatted mail to a specified reciepient using SMTP

    Args:
        smtp_settings (dict): host, port, username, password and sender address (from)
        recipients (list of str): list of email addresses
        subject (str): mail subject
        html_message (str): html content of mail

    Returns:
        None
    """
    msg = EmailMessage()
    msg.add_alternative(html_message, subtype='html')
    msg['Subject'] = subject
    msg['From'] = smtp_settings['from']
    msg['Bcc'] = recipients
    s = smtplib.SMTP(
        host = smtp_settings['host'],
        port = smtp_settings['port']
    )
    s.ehlo()
    s.starttls()
    s.login(
        user = smtp_settings['user'],
        password = smtp_settings['password']
    )
    s.send_message(msg)
    s.quit()

def create_html_list_item_for_change(change, home_url):
    """
    Creates a html list item element for a configuration item with changed availability status

    Args:
        change (DataFrame): data for an individual configuration item containing information
        such as organization and product as well as current availability and availability difference
        home_url (str): base url of dash app

    Returns:
        str: html list item element
    """
    if home_url:
        href = str(home_url) + '/plot?ci=' + str(change['ci'])
    else:
        href = ''
    # Emoji je nach Änderungstyp bestimmen
    emoji = 'ℹ️'
    if change['availability_difference'] == -1:
        emoji = '🚨'
    elif change['availability_difference'] == 1:
        emoji = '✅'

    html_str = '<li>' + ' <strong><a href="' + href + '">' + str(change['ci']) + '</a></strong>: ' + str(change['product']) + ', ' + str(change['name']) + ', ' + str(change['organization']) + ' '
    if change['availability_difference'] == 1:
        html_str += '<span style=color:green>&nbsp;*ist wieder verfügbar*</span>'
    elif change['availability_difference'] == -1:
        html_str += '<span style=color:red>&nbsp;*ist nicht mehr verfügbar*</span>'
    else:
        html_str += ' keine Veränderung'
    html_str += emoji + ' '
    html_str += '- Stand: ' + str(pretty_timestamp(change['time'])) + '</li>'
    return html_str

def create_notification_message(changes, recipient_name, home_url):
    """
    Creates an HTML formatted message for notifications

    Args:
        changes (DataFrame): DataFrame with availability changes
        recipient_name (str): Name of the recipient
        home_url (str): Base URL of the dashboard

    Returns:
        str: HTML formatted message
    """
    message = f'<html lang="de"><body><p>Hallo {recipient_name},</p>'
    message += '<p>bei der letzten Überprüfung hat sich die Verfügbarkeit der folgenden von dir abonierten Komponenten geändert:</p>'

    # Kurze Emoji-Zusammenfassung (Anzahl Incidents / Entwarnungen)
    try:
        incidents_count = int((changes['availability_difference'] == -1).sum()) if 'availability_difference' in changes.columns else 0
        recoveries_count = int((changes['availability_difference'] == 1).sum()) if 'availability_difference' in changes.columns else 0
        if incidents_count or recoveries_count:
            message += f'<p><strong>Übersicht:</strong> 🚨 {incidents_count} | ✅ {recoveries_count}</p>'
    except Exception:
        pass

    message += '<ul>'
    
    for index, change in changes.iterrows():
        list_item = create_html_list_item_for_change(change, home_url)
        if list_item:
            message += str(list_item)
        
    if home_url:    
        message += f'</ul><p>Den aktuellen Status aller Komponenten kannst du unter <a href="{home_url}">{home_url}</a> einsehen.</p>'
    message += '<p>Weitere Hintergrundinformationen findest du im <a href="https://fachportal.gematik.de/ti-status">Fachportal der gematik GmbH</a>.</p>'
    message += '<p>👉 <a href="https://ti-stats.net">https://ti-stats.net</a></p></body></html>'
    
    return message

# Legacy file-based notifications removed (notifications.json)
# Legacy send_notifications() function removed - only send_db_notifications() is used now

def load_env_file():
    """
    Load environment variables from .env file
    
    Returns:
        bool: True if .env file was loaded, False otherwise
    """
    # Try default lookup first (current working dir or parents)
    loaded = load_dotenv()
    if loaded:
        return True
    # Try explicit common paths used in containers
    for path in (os.path.join(os.getcwd(), '.env'), '/app/.env'): 
        try:
            if os.path.exists(path) and load_dotenv(dotenv_path=path, override=False):
                print(f"Loaded .env from {path}")
                return True
        except Exception:
            continue
    print("Warning: .env not found; expecting POSTGRES_* vars in environment")
    return False

def validate_password(provided_password):
    """
    Validate provided password against environment variable using time-constant comparison
    
    Args:
        provided_password (str): Password provided by user
        
    Returns:
        bool: True if password is valid, False otherwise
    """
    load_env_file()  # Ensure environment variables are loaded
    expected_password = os.getenv('NOTIFICATION_SETTINGS_PASSWORD')
    
    if expected_password is None:
        return False
    
    # Use time-constant comparison to prevent timing attacks
    return hmac.compare_digest(provided_password, expected_password)

def get_notification_config(file_path):
    """
    Read and parse notification configuration
    
    Args:
        file_path (str): Path to notifications.json file
        
    Returns:
        list: List of notification configurations
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"Error reading notification config: {e}")
        return []

def save_notification_config(file_path, config):
    """
    Save notification configuration to file
    
    Args:
        file_path (str): Path to notifications.json file
        config (list): List of notification configurations
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving notification config: {e}")
        return False

def validate_apprise_urls(urls):
    """
    Validate Apprise URLs
    
    Args:
        urls (list): List of Apprise URLs
        
    Returns:
        bool: True if all URLs are valid, False otherwise
    """
    try:
        for url in urls:
            apobj = apprise.Apprise()
            if not apobj.add(url):
                return False
        return True
    except Exception:
        return False

def get_user_notification_profiles(user_id):
    """Get all notification profiles for a user"""
    with get_db_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT id, name, type, ci_list, apprise_urls, email_notifications, email_address, created_at, updated_at
            FROM notification_profiles
            WHERE user_id = %s
            ORDER BY created_at DESC
        """, (user_id,))
        return cur.fetchall()

def is_admin_user(email):
    """Check if user has admin privileges based on config.yaml"""
    try:
        config = load_config()
        admin_email = config.get('core', {}).get('admin_email', '')
        return email == admin_email
    except Exception:
        return False

def log_notification(profile_id, ci, notification_type, delivery_status, recipient_type, error_message=None):
    """Log notification attempt for statistics"""
    try:
        with get_db_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO notification_logs 
                (profile_id, ci, notification_type, delivery_status, recipient_type, error_message)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (profile_id, ci, notification_type, delivery_status, recipient_type, error_message))
            conn.commit()
    except Exception as e:
        print(f"Error logging notification: {e}")

def get_notification_profile(profile_id, user_id):
    """Get a specific notification profile for a user"""
    with get_db_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT id, name, type, ci_list, apprise_urls, email_notifications, email_address, created_at, updated_at
            FROM notification_profiles
            WHERE id = %s AND user_id = %s
        """, (profile_id, user_id))
        return cur.fetchone()

def create_notification_profile(user_id, name, profile_type, ci_list, apprise_urls, email_notifications, email_address):
    """Create a new notification profile for a user with encrypted Apprise URLs"""
    unsubscribe_token = secrets.token_urlsafe(32)
    
    # Encrypt Apprise URLs
    encrypted_urls = []
    url_hashes = []
    url_salts = []
    
    # Get encryption key from environment or generate one
    encryption_key = os.getenv('ENCRYPTION_KEY')
    if encryption_key:
        encryption_key = encryption_key.encode()
    else:
        encryption_key = generate_encryption_key()
    
    for url in apprise_urls:
        if url:
            encrypted_url, salt = encrypt_data(url, encryption_key)
            if encrypted_url:
                encrypted_urls.append(encrypted_url)
                url_salts.append(salt)
                # Hash the URL for searching without decrypting
                url_hash = hash_with_salt(url, salt)
                url_hashes.append(url_hash)
    
    with get_db_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO notification_profiles 
            (user_id, name, type, ci_list, apprise_urls, apprise_urls_hash, apprise_urls_salt, 
             email_notifications, email_address, unsubscribe_token)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (user_id, name, profile_type, ci_list, encrypted_urls, url_hashes, url_salts, 
              email_notifications, email_address, unsubscribe_token))
        return cur.fetchone()[0]

def update_notification_profile(profile_id, user_id, name, profile_type, ci_list, apprise_urls, email_notifications, email_address):
    """Update an existing notification profile with encrypted Apprise URLs"""
    # Encrypt Apprise URLs
    encrypted_urls = []
    url_hashes = []
    url_salts = []
    
    # Get encryption key from environment or generate one
    encryption_key = os.getenv('ENCRYPTION_KEY')
    if encryption_key:
        encryption_key = encryption_key.encode()
    else:
        encryption_key = generate_encryption_key()
    
    for url in apprise_urls:
        if url:
            encrypted_url, salt = encrypt_data(url, encryption_key)
            if encrypted_url:
                encrypted_urls.append(encrypted_url)
                url_salts.append(salt)
                # Hash the URL for searching without decrypting
                url_hash = hash_with_salt(url, salt)
                url_hashes.append(url_hash)
    
    with get_db_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            UPDATE notification_profiles 
            SET name = %s, type = %s, ci_list = %s, apprise_urls = %s, apprise_urls_hash = %s, apprise_urls_salt = %s,
                email_notifications = %s, email_address = %s, updated_at = NOW()
            WHERE id = %s AND user_id = %s
        """, (name, profile_type, ci_list, encrypted_urls, url_hashes, url_salts, 
              email_notifications, email_address, profile_id, user_id))
        return cur.rowcount > 0

def delete_notification_profile(profile_id, user_id):
    """Delete a notification profile"""
    with get_db_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            DELETE FROM notification_profiles 
            WHERE id = %s AND user_id = %s
        """, (profile_id, user_id))
        return cur.rowcount > 0

def get_profile_by_unsubscribe_token(token):
    """Get a notification profile by its unsubscribe token"""
    with get_db_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT id, user_id, name, email_notifications, email_address
            FROM notification_profiles
            WHERE unsubscribe_token = %s
        """, (token,))
        return cur.fetchone()

def delete_profile_by_unsubscribe_token(token):
    """Delete a notification profile by its unsubscribe token"""
    with get_db_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            DELETE FROM notification_profiles 
            WHERE unsubscribe_token = %s
        """, (token,))
        return cur.rowcount > 0

def log_page_view(page, session_id, user_agent_hash=None, referrer=None):
    """Log a page view for visitor statistics"""
    try:
        with get_db_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO page_views (page, session_id, user_agent_hash, referrer)
                VALUES (%s, %s, %s, %s)
            """, (page, session_id, user_agent_hash, referrer))
            conn.commit()
    except Exception as e:
        print(f"Error logging page view: {e}")

def get_visitor_statistics():
    """Get visitor statistics from page_views table"""
    try:
        with get_db_conn() as conn:
            # Basic visitor stats
            stats_query = """
            WITH daily_stats AS (
                SELECT 
                    DATE(ts) as date,
                    COUNT(DISTINCT session_id) as unique_visitors,
                    COUNT(*) as page_views
                FROM page_views
                WHERE ts >= NOW() - INTERVAL '30 days'
                GROUP BY DATE(ts)
                ORDER BY date DESC
            ),
            page_stats AS (
                SELECT 
                    page,
                    COUNT(*) as views,
                    COUNT(DISTINCT session_id) as unique_visitors
                FROM page_views
                WHERE ts >= NOW() - INTERVAL '30 days'
                GROUP BY page
                ORDER BY views DESC
            ),
            browser_stats AS (
                SELECT 
                    user_agent_hash,
                    COUNT(*) as views,
                    COUNT(DISTINCT session_id) as unique_visitors
                FROM page_views
                WHERE ts >= NOW() - INTERVAL '30 days'
                  AND user_agent_hash IS NOT NULL
                GROUP BY user_agent_hash
                ORDER BY views DESC
                LIMIT 10
            )
            SELECT 
                (SELECT COUNT(DISTINCT session_id) FROM page_views WHERE ts >= NOW() - INTERVAL '30 days') as total_unique_visitors_30d,
                (SELECT COUNT(*) FROM page_views WHERE ts >= NOW() - INTERVAL '30 days') as total_page_views_30d,
                (SELECT COUNT(DISTINCT session_id) FROM page_views WHERE ts >= CURRENT_DATE) as unique_visitors_today,
                (SELECT COUNT(*) FROM page_views WHERE ts >= CURRENT_DATE) as page_views_today
            """
            
            with conn.cursor() as cur:
                cur.execute(stats_query)
                basic_stats = cur.fetchone()
                
                # Get daily breakdown
                cur.execute("""
                    SELECT 
                        DATE(ts) as date,
                        COUNT(DISTINCT session_id) as unique_visitors,
                        COUNT(*) as page_views
                    FROM page_views
                    WHERE ts >= NOW() - INTERVAL '30 days'
                    GROUP BY DATE(ts)
                    ORDER BY date DESC
                    LIMIT 30
                """)
                daily_data = cur.fetchall()
                
                # Get page popularity
                cur.execute("""
                    SELECT 
                        page,
                        COUNT(*) as views,
                        COUNT(DISTINCT session_id) as unique_visitors
                    FROM page_views
                    WHERE ts >= NOW() - INTERVAL '30 days'
                    GROUP BY page
                    ORDER BY views DESC
                    LIMIT 10
                """)
                page_data = cur.fetchall()
                
                # Get browser stats
                cur.execute("""
                    SELECT 
                        user_agent_hash,
                        COUNT(*) as views,
                        COUNT(DISTINCT session_id) as unique_visitors
                    FROM page_views
                    WHERE ts >= NOW() - INTERVAL '30 days'
                      AND user_agent_hash IS NOT NULL
                    GROUP BY user_agent_hash
                    ORDER BY views DESC
                    LIMIT 10
                """)
                browser_data = cur.fetchall()
                
                return {
                    'total_unique_visitors_30d': basic_stats[0] or 0,
                    'total_page_views_30d': basic_stats[1] or 0,
                    'unique_visitors_today': basic_stats[2] or 0,
                    'page_views_today': basic_stats[3] or 0,
                    'daily_breakdown': [{'date': str(row[0]), 'unique_visitors': row[1], 'page_views': row[2]} for row in daily_data],
                    'popular_pages': [{'page': row[0], 'views': row[1], 'unique_visitors': row[2]} for row in page_data],
                    'browser_stats': [{'user_agent_hash': row[0], 'views': row[1], 'unique_visitors': row[2]} for row in browser_data],
                    'calculated_at': time.time()
                }
                
    except Exception as e:
        print(f"Error getting visitor statistics: {e}")
        return {
            'total_unique_visitors_30d': 0,
            'total_page_views_30d': 0,
            'unique_visitors_today': 0,
            'page_views_today': 0,
            'daily_breakdown': [],
            'popular_pages': [],
            'browser_stats': [],
            'calculated_at': time.time()
        }

# ------------------------------
# Message formatting helpers for Apprise channels
# ------------------------------

def extract_apprise_scheme(apprise_url: str) -> str:
    """Return lower-case scheme of an Apprise URL (text before ://)."""
    try:
        if not apprise_url:
            return ''
        return str(apprise_url).split('://', 1)[0].lower()
    except Exception:
        return ''

def _convert_html_links_to_text(html_str: str) -> str:
    """Convert <a href="..">text</a> to 'text (URL)' for plain text/markdown."""
    try:
        def repl(match):
            url = match.group(1)
            text = match.group(2)
            return f"{text} ({url})"
        return re.sub(r"<a [^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", repl, html_str, flags=re.IGNORECASE|re.DOTALL)
    except Exception:
        return html_str

def convert_html_to_text(html_str: str) -> str:
    """Very small HTML→text converter for notifications (no external deps)."""
    s = html_str or ''
    # Links -> text (URL)
    s = _convert_html_links_to_text(s)
    # Line breaks / paragraphs / list items
    s = re.sub(r"<\s*br\s*/?\s*>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"</\s*p\s*>", "\n\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<\s*p\s*[^>]*>", "", s, flags=re.IGNORECASE)
    s = re.sub(r"<\s*li\s*[^>]*>", "- ", s, flags=re.IGNORECASE)
    s = re.sub(r"</\s*li\s*>", "\n", s, flags=re.IGNORECASE)
    # Strip remaining tags
    s = re.sub(r"<[^>]+>", "", s)
    # Unescape HTML entities
    try:
        s = htmllib.unescape(s)
    except Exception:
        pass
    # Collapse excessive blank lines
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s

def convert_html_to_markdown(html_str: str) -> str:
    """Crude HTML→Markdown conversion sufficient for short alerts."""
    # For our simple messages, plain text with leading '-' acts fine as Markdown
    return convert_html_to_text(html_str)

def sanitize_message_for_apprise(body_html: str, scheme: str):
    """Return (body, apprise.NotifyFormat) suitable for given scheme.

    - Email-like schemes keep HTML
    - Mastodon/Toots use TEXT (no HTML)
    - Others use MARKDOWN (HTML stripped)
    """
    email_schemes = { 'mailto', 'gmail', 'ses', 'sendgrid', 'outlook', 'resend' }
    mastodon_schemes = { 'toots', 'mastodon' }

    if scheme in email_schemes:
        return body_html or '', apprise.NotifyFormat.HTML

    if scheme in mastodon_schemes:
        txt = convert_html_to_text(body_html or '')
        # Keep toot short; many servers default to ~500 chars
        if len(txt) > 480:
            txt = txt[:480].rstrip() + '…'
        return txt, apprise.NotifyFormat.TEXT

    # Default: Markdown
    md = convert_html_to_markdown(body_html or '')
    return md, apprise.NotifyFormat.MARKDOWN

def prepare_apprise_payload(body_html: str, title: str, scheme: str, detail_url: str = None):
    """Return (title_to_send, body_to_send, format) tuned per scheme.

    - Email-like schemes: keep title + HTML body
    - Mastodon/Toots: merge title into body, trim to ~480 chars, send TEXT, empty title
    - Others: keep title, convert body to Markdown
    """
    email_schemes = { 'mailto', 'gmail', 'ses', 'sendgrid', 'outlook', 'resend' }
    mastodon_schemes = { 'toots', 'mastodon', 'mastodons' }

    if scheme in email_schemes:
        return title or '', (body_html or ''), apprise.NotifyFormat.HTML

    if scheme in mastodon_schemes:
        merged = convert_html_to_text(((title or '').strip() + '\n\n' if title else '') + (body_html or ''))
        link_tail = ''
        if detail_url:
            link_tail = f" Mehr: {detail_url}"
        max_len = 480
        if len(merged) + len(link_tail) > max_len:
            merged = merged[: max(0, max_len - len(link_tail) - 1)].rstrip() + '…'
        merged = merged + link_tail
        return '', merged, apprise.NotifyFormat.TEXT

    # Default: Markdown
    md = convert_html_to_markdown(body_html or '')
    return (title or ''), md, apprise.NotifyFormat.MARKDOWN

def remove_apprise_url_by_token_and_hash(token: str, url_hash: str) -> bool:
    """Remove a single apprise URL from a profile identified by unsubscribe token using stored url hash.

    Returns True if an URL was removed and profile updated; False otherwise.
    """
    if not token or not url_hash:
        return False
    with get_db_conn() as conn, conn.cursor() as cur:
        # Load arrays
        cur.execute(
            """
            SELECT id, apprise_urls, apprise_urls_hash, apprise_urls_salt
            FROM notification_profiles
            WHERE unsubscribe_token = %s
            """,
            (token,)
        )
        row = cur.fetchone()
        if not row:
            return False
        profile_id, urls, hashes, salts = row
        urls = list(urls or [])
        hashes = list(hashes or [])
        salts = list(salts or [])
        if not hashes or len(hashes) != len(urls):
            return False
        # Find index by hash
        try:
            idx = hashes.index(url_hash)
        except ValueError:
            return False
        # Remove the corresponding entries
        del urls[idx]
        del hashes[idx]
        if salts and len(salts) > idx:
            del salts[idx]
        # Update DB
        cur.execute(
            """
            UPDATE notification_profiles
            SET apprise_urls = %s, apprise_urls_hash = %s, apprise_urls_salt = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (urls, hashes, salts, profile_id)
        )
        return cur.rowcount > 0

def send_db_notifications():
    """
    Send notifications to all users using the new multi-user system.
    Returns the number of profiles processed.
    """
    profiles_processed = 0
    
    try:
        # Get all notification profiles from the database
        with get_db_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT np.id, np.user_id, np.name, np.type, np.ci_list,
                       np.apprise_urls, np.apprise_urls_hash, np.apprise_urls_salt,
                       np.email_notifications,
                       u.email_encrypted, u.email_enc_salt
                FROM notification_profiles np
                JOIN users u ON np.user_id = u.id
                WHERE (np.apprise_urls IS NOT NULL AND array_length(np.apprise_urls, 1) > 0) 
                   OR np.email_notifications = TRUE
            """)
            profiles = cur.fetchall()
            
            if not profiles:
                return 0
                
            # Get changes in CI status
            ci_data = get_data_of_all_cis('')
            changes = ci_data[ci_data['availability_difference'] != 0]
            changes_sorted = changes.sort_values(by='availability_difference')
            
            if len(changes_sorted) == 0:
                return len(profiles)
            
            # Process each profile
            for profile in profiles:
                try:
                    profile_id, user_id, profile_name, profile_type, ci_list, apprise_urls, apprise_urls_hash, apprise_urls_salt, email_notifications, email_encrypted, email_enc_salt = profile
                    
                    # Check if this user is an admin (for unsubscribe link logic)
                    is_admin = False
                    try:
                        # Get user email for admin check
                        decrypted_email = None
                        if email_encrypted and email_enc_salt:
                            encryption_key = os.getenv('ENCRYPTION_KEY')
                            if encryption_key:
                                encryption_key = encryption_key.encode()
                                decrypted_email = decrypt_data(email_encrypted, email_enc_salt, encryption_key)
                        
                        if decrypted_email:
                            is_admin = is_admin_user(decrypted_email)
                    except Exception:
                        # If admin check fails, assume regular user (include unsubscribe links)
                        pass
                    
                    # Filter relevant changes
                    if profile_type == 'whitelist':
                        relevant_changes = changes_sorted[changes_sorted['ci'].isin(ci_list)]
                    elif profile_type == 'blacklist':
                        relevant_changes = changes_sorted[~changes_sorted['ci'].isin(ci_list)]
                    else:
                        relevant_changes = changes_sorted
                        
                    number_of_relevant_changes = len(relevant_changes)
                    
                    if number_of_relevant_changes > 0:
                        # Create notification message
                        message = create_notification_message(relevant_changes, profile_name, '')
                        subject = f'TI-Stats: {str(number_of_relevant_changes)} Änderungen der Verfügbarkeit'
                        
                        # Prepare base unsubscribe token/link (profile-level)
                        config = load_config()
                        unsubscribe_base_url = config.get('core', {}).get('unsubscribe_base_url', '')
                        
                        if unsubscribe_base_url:
                            # Get the unsubscribe token for this profile
                            cur.execute("""
                                SELECT unsubscribe_token FROM notification_profiles WHERE id = %s
                            """, (profile_id,))
                            token_result = cur.fetchone()
                            if token_result:
                                unsubscribe_token = token_result[0]
                                profile_unsub_link = f"{unsubscribe_base_url}/{unsubscribe_token}"
                                # Hinweis: Profil-weites Opt-Out weiterhin anbieten
                                message_with_profile_unsub = str(message) + f'<p><a href="{profile_unsub_link}">Abmelden von diesem Benachrichtigungsprofil</a></p>'
                        
                        # Versand-Strategie: E-Mail (einfach) ist exklusiv; sonst benutzerdefinierte Apprise-URLs
                        # Detail-URL für öffentliche Ansicht ermitteln
                        try:
                            cfg_links = load_config().get('core', {}) or {}
                            detail_base = cfg_links.get('public_base_url') or cfg_links.get('home_url') or 'https://ti-stats.net'
                        except Exception:
                            detail_base = 'https://ti-stats.net'

                        if email_notifications:
                            # Senden über otp_apprise_url_template (ohne OTP, mit Empfänger-E-Mail)
                            try:
                                cfg = load_config()
                                otp_tpl = (cfg.get('core', {}) or {}).get('otp_apprise_url_template')
                                # Empfänger aus verschlüsseltem Benutzerkonto entschlüsseln
                                encryption_key = os.getenv('ENCRYPTION_KEY')
                                if encryption_key:
                                    encryption_key = encryption_key.encode()
                                else:
                                    encryption_key = generate_encryption_key()
                                recipient = ''
                                if email_encrypted and email_enc_salt:
                                    decrypted = decrypt_data(email_encrypted, email_enc_salt, encryption_key)
                                    if decrypted:
                                        recipient = decrypted
                                if otp_tpl:
                                    # {otp} ggf. mit leerem String befüllen
                                    try:
                                        apprise_url = otp_tpl.format(email=recipient, otp='')
                                    except Exception:
                                        # Minimal: nur {email} ersetzen
                                        apprise_url = otp_tpl.replace('{email}', recipient).replace('{otp}', '')
                                    apobj = apprise.Apprise()
                                    apobj.add(apprise_url)
                                    # Fester Betreff für einfache E-Mail
                                    simple_subject = 'TI-Monitor Statusänderung'
                                    # For admin users, don't include unsubscribe links
                                    if is_admin:
                                        body = message
                                    else:
                                        body = message_with_profile_unsub if unsubscribe_base_url else message
                                    apobj.notify(title=simple_subject, body=body, body_format=apprise.NotifyFormat.HTML)
                                else:
                                    print('otp_apprise_url_template not configured; skipping simple email notification')
                            except Exception as e:
                                print(f'Error sending simple email via otp_apprise_url_template for profile {profile_id}: {e}')
                        elif apprise_urls and len(apprise_urls) > 0:
                            # Benutzerdefinierte Apprise-URLs verwenden (vorher entschlüsseln)
                            # Entschlüsselungs-Schlüssel laden
                            encryption_key = os.getenv('ENCRYPTION_KEY')
                            if encryption_key:
                                encryption_key = encryption_key.encode()
                            else:
                                encryption_key = None

                            # URLs mit ihren Salts entschlüsseln (gleiche Reihenfolge wie gespeichert)
                            decrypted_urls = []
                            if apprise_urls_salt and len(apprise_urls_salt) == len(apprise_urls) and encryption_key:
                                for idx, enc_url in enumerate(apprise_urls):
                                    try:
                                        decrypted = decrypt_data(enc_url, apprise_urls_salt[idx], encryption_key)
                                    except Exception:
                                        decrypted = None
                                    decrypted_urls.append(decrypted)
                            else:
                                # Keine Entschlüsselung möglich
                                decrypted_urls = [None for _ in apprise_urls]

                            # Falls Hashes vorhanden sind, pro URL individuellen Opt-Out-Link beilegen
                            if unsubscribe_base_url and apprise_urls_hash and len(apprise_urls_hash) == len(apprise_urls):
                                # For admin users, skip unsubscribe links
                                if is_admin:
                                    # Send notifications without unsubscribe links for admin users
                                    for idx, _ in enumerate(apprise_urls):
                                        try:
                                            decrypted_url = decrypted_urls[idx]
                                            if not decrypted_url:
                                                # Entschlüsselung fehlgeschlagen -> als failed loggen
                                                for ci in relevant_changes['ci']:
                                                    notification_type = 'incident' if relevant_changes[relevant_changes['ci'] == ci]['availability_difference'].iloc[0] == -1 else 'recovery'
                                                    log_notification(profile_id, ci, notification_type, 'failed', 'apprise', 'Apprise URL decryption failed')
                                                continue

                                            # Send notification without unsubscribe links
                                            scheme = extract_apprise_scheme(decrypted_url)
                                            # Ersten relevanten CI für Detail-Link ermitteln
                                            try:
                                                primary_ci = str(relevant_changes['ci'].iloc[0]) if not relevant_changes.empty else ''
                                            except Exception:
                                                primary_ci = ''
                                            ci_detail_url = f"{detail_base.rstrip('/')}/plot?ci={primary_ci}" if primary_ci else detail_base
                                            title_to_send, body_sanitized, body_fmt = prepare_apprise_payload(str(message), subject, scheme, ci_detail_url)
                                            apobj = apprise.Apprise()
                                            apobj.add(decrypted_url)
                                            success = apobj.notify(title=title_to_send, body=body_sanitized, body_format=body_fmt)
                                            
                                            # Log notification attempt
                                            for ci in relevant_changes['ci']:
                                                notification_type = 'incident' if relevant_changes[relevant_changes['ci'] == ci]['availability_difference'].iloc[0] == -1 else 'recovery'
                                                log_notification(profile_id, ci, notification_type, 'sent' if success else 'failed', 'apprise', None if success else 'Apprise notify returned False')
                                                
                                        except Exception as e:
                                            print(f'Error sending admin notification to URL {idx} for profile {profile_id}: {e}')
                                            # Log failed notification
                                            for ci in relevant_changes['ci']:
                                                notification_type = 'incident' if relevant_changes[relevant_changes['ci'] == ci]['availability_difference'].iloc[0] == -1 else 'recovery'
                                                log_notification(profile_id, ci, notification_type, 'failed', 'apprise', str(e))
                                else:
                                    # Send notifications with unsubscribe links for regular users
                                    for idx, _ in enumerate(apprise_urls):
                                        try:
                                            decrypted_url = decrypted_urls[idx]
                                            if not decrypted_url:
                                                # Entschlüsselung fehlgeschlagen -> als failed loggen
                                                for ci in relevant_changes['ci']:
                                                    notification_type = 'incident' if relevant_changes[relevant_changes['ci'] == ci]['availability_difference'].iloc[0] == -1 else 'recovery'
                                                    log_notification(profile_id, ci, notification_type, 'failed', 'apprise', 'Apprise URL decryption failed')
                                                continue

                                            url_hash = apprise_urls_hash[idx]
                                            per_url_unsub_link = f"{unsubscribe_base_url}/{unsubscribe_token}?u={url_hash}"
                                            body = str(message) + f'<p><a href="{per_url_unsub_link}">Abmelden nur für diesen Kanal</a></p>'
                                            # Zusätzlich Profil-Opt-Out-Link anbieten, falls vorhanden
                                            body += f'<p style="margin-top:6px;"><a href="{profile_unsub_link}">Alle Benachrichtigungen dieses Profils abmelden</a></p>'
                                            scheme = extract_apprise_scheme(decrypted_url)
                                            try:
                                                primary_ci = str(relevant_changes['ci'].iloc[0]) if not relevant_changes.empty else ''
                                            except Exception:
                                                primary_ci = ''
                                            ci_detail_url = f"{detail_base.rstrip('/')}/plot?ci={primary_ci}" if primary_ci else detail_base
                                            title_to_send, body_sanitized, body_fmt = prepare_apprise_payload(body, subject, scheme, ci_detail_url)
                                            apobj = apprise.Apprise()
                                            apobj.add(decrypted_url)
                                            success = apobj.notify(title=title_to_send, body=body_sanitized, body_format=body_fmt)
                                            
                                            # Log notification attempt
                                            for ci in relevant_changes['ci']:
                                                notification_type = 'incident' if relevant_changes[relevant_changes['ci'] == ci]['availability_difference'].iloc[0] == -1 else 'recovery'
                                                log_notification(profile_id, ci, notification_type, 'sent' if success else 'failed', 'apprise', None if success else 'Apprise notify returned False')
                                                
                                        except Exception as e:
                                            print(f'Error sending notification to URL {idx} for profile {profile_id}: {e}')
                                            # Log failed notification
                                            for ci in relevant_changes['ci']:
                                                notification_type = 'incident' if relevant_changes[relevant_changes['ci'] == ci]['availability_difference'].iloc[0] == -1 else 'recovery'
                                                log_notification(profile_id, ci, notification_type, 'failed', 'apprise', str(e))
                            else:
                                # Fallback: eine Nachricht an alle URLs mit Profil-Opt-Out-Link
                                # For admin users, don't include unsubscribe links
                                if is_admin:
                                    body = message
                                else:
                                    body = message_with_profile_unsub if unsubscribe_base_url else message
                                for idx, _ in enumerate(apprise_urls):
                                    try:
                                        decrypted_url = decrypted_urls[idx]
                                        if not decrypted_url:
                                            for ci in relevant_changes['ci']:
                                                notification_type = 'incident' if relevant_changes[relevant_changes['ci'] == ci]['availability_difference'].iloc[0] == -1 else 'recovery'
                                                log_notification(profile_id, ci, notification_type, 'failed', 'apprise', 'Apprise URL decryption failed')
                                            continue
                                        scheme = extract_apprise_scheme(decrypted_url)
                                        try:
                                            primary_ci = str(relevant_changes['ci'].iloc[0]) if not relevant_changes.empty else ''
                                        except Exception:
                                            primary_ci = ''
                                        ci_detail_url = f"{detail_base.rstrip('/')}/plot?ci={primary_ci}" if primary_ci else detail_base
                                        title_to_send, body_sanitized, body_fmt = prepare_apprise_payload(str(body), subject, scheme, ci_detail_url)
                                        apobj = apprise.Apprise()
                                        apobj.add(decrypted_url)
                                        success = apobj.notify(title=title_to_send, body=body_sanitized, body_format=body_fmt)
                                        for ci in relevant_changes['ci']:
                                            notification_type = 'incident' if relevant_changes[relevant_changes['ci'] == ci]['availability_difference'].iloc[0] == -1 else 'recovery'
                                            log_notification(profile_id, ci, notification_type, 'sent' if success else 'failed', 'apprise', None if success else 'Apprise notify returned False')
                                    except Exception as e:
                                        print(f"Error sending notification (fallback) for profile {profile_id}: {e}")
                                        for ci in relevant_changes['ci']:
                                            notification_type = 'incident' if relevant_changes[relevant_changes['ci'] == ci]['availability_difference'].iloc[0] == -1 else 'recovery'
                                            log_notification(profile_id, ci, notification_type, 'failed', 'apprise', str(e))
                        
                        profiles_processed += 1
                        
                except Exception as e:
                    print(f'Error sending notification for profile {profile_id}: {e}')
                    import traceback
                    traceback.print_exc()
                    continue
                    
    except Exception as e:
        print(f'Error in send_db_notifications: {e}')
        
    return profiles_processed
