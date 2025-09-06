import os
import psycopg2
from psycopg2.extras import execute_values
import h5py
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
    # Load database configuration from config.yaml
    config = load_config()
    tsdb_config = config.get('core', {}).get('timescaledb', {})
    
    host = tsdb_config.get('host', 'db')
    port = tsdb_config.get('port', 5432)
    db = tsdb_config.get('dbname', 'timonitor')
    user = tsdb_config.get('user', 'timonitor')
    pwd = tsdb_config.get('password', 'timonitor')
    
    return psycopg2.connect(host=host, port=port, dbname=db, user=user, password=pwd)

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
    if not os.path.exists(hdf5_path):
        return 0
    init_timescaledb_schema()
    inserted = 0
    batch = []
    batch_size = 5000
    processed = 0
    with get_db_conn() as conn, conn.cursor() as cur:
        with h5py.File(hdf5_path, 'r', swmr=True) as f:
            if 'availability' not in f:
                return 0
            availability = f['availability']
            for ci in availability.keys():
                ci_group = availability[ci]
                for ts_key in ci_group.keys():
                    try:
                        ts = float(ts_key)
                        ds = ci_group[ts_key]
                        val = int(ds[()]) if isinstance(ds, h5py.Dataset) else int(ds)
                        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                        batch.append((ci, dt, val))
                        processed += 1
                        if len(batch) >= batch_size:
                            cur.executemany(
                                "INSERT INTO measurements (ci, ts, status) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                                batch,
                            )
                            inserted += cur.rowcount
                            batch.clear()
                        if max_rows is not None and processed >= max_rows:
                            break
                    except Exception:
                        continue
                if max_rows is not None and processed >= max_rows:
                    break
            if batch:
                cur.executemany(
                    "INSERT INTO measurements (ci, ts, status) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                    batch,
                )
                inserted += cur.rowcount
                batch.clear()
    return inserted

def setup_timescaledb_retention(keep_days: int = 185) -> None:
    """Setzt eine Retention-Policy (drop_chunks) auf measurements; idempotent."""
    with get_db_conn() as conn, conn.cursor() as cur:
        # add_retention_policy ist idempotent mit if_not_exists => TRUE
        sql = f"SELECT add_retention_policy('measurements', INTERVAL '{int(keep_days)} days', if_not_exists => TRUE);"
        cur.execute(sql)

def init_otp_database_schema():
    """Initialize database schema for multi-user OTP system"""
    with get_db_conn() as conn, conn.cursor() as cur:
        # Create users table - modified to match existing schema
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                email TEXT,
                email_hash TEXT,
                email_salt TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                deleted_at TIMESTAMPTZ,
                last_login TIMESTAMPTZ,
                failed_login_attempts INTEGER DEFAULT 0,
                locked_until TIMESTAMPTZ
            );
        """)
        
        # Create otp_codes table - modified to use UUID for user_id
        cur.execute("""
            CREATE TABLE IF NOT EXISTS otp_codes (
                id SERIAL PRIMARY KEY,
                user_id UUID REFERENCES users(id) ON DELETE CASCADE,
                otp_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                used BOOLEAN DEFAULT FALSE,
                ip_address TEXT
            );
        """)
        
        # Create notification_profiles table - modified to use UUID for user_id
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notification_profiles (
                id SERIAL PRIMARY KEY,
                user_id UUID REFERENCES users(id) ON DELETE CASCADE,
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

# Add dotenv import
from dotenv import load_dotenv
import hmac

# Note: HDF5 cache removed - now using TimescaleDB only

def generate_salt():
    """Generate a random salt for hashing"""
    return secrets.token_hex(32)

def hash_with_salt(data, salt):
    """Hash data with salt using SHA-256"""
    return hashlib.sha256((data + salt).encode()).hexdigest()

def generate_otp():
    """Generate a 6-digit numeric OTP"""
    return str(secrets.randbelow(1000000)).zfill(6)

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
    email_hash = hash_with_salt(email.lower(), salt)
    
    with get_db_conn() as conn, conn.cursor() as cur:
        try:
            cur.execute("""
                INSERT INTO users (email, email_hash, email_salt)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (email.lower(), email_hash, salt))
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
            SELECT id, email, email_hash, email_salt, failed_login_attempts, locked_until
            FROM users
        """)
        users = cur.fetchall()
        
        email_lower = email.lower()
        for user in users:
            user_id, user_email, email_hash, email_salt, failed_attempts, locked_until = user
            # If email_salt is None or empty (for existing users), we can't verify the email
            # In this case, we'll assume the user is valid if email matches
            if email_salt is None or email_salt == '':
                # For backward compatibility with existing users
                if user_email and user_email.lower() == email_lower:
                    return user
            else:
                # Hash the provided email with the user's salt
                try:
                    provided_email_hash = hash_with_salt(email_lower, email_salt)
                    if hmac.compare_digest(email_hash, provided_email_hash):
                        return user
                except Exception:
                    # If hashing fails, fall back to simple email comparison
                    if user_email and user_email.lower() == email_lower:
                        return user
                
        return None

def generate_otp_for_user(user_id, ip_address=None):
    """Generate and store OTP for user"""
    otp = generate_otp()
    salt = generate_salt()
    otp_hash = hash_with_salt(otp, salt)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    
    with get_db_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO otp_codes (user_id, otp_hash, salt, expires_at, ip_address)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (user_id, otp_hash, salt, expires_at, ip_address))
        otp_id = cur.fetchone()[0]
        return otp, otp_id

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
    Gets general data for a specific configuration item from hdf5 file or TimescaleDB

    Args:
        file_name (str): Path to hdf5 file (used for fallback)
        ci (str): ID of the desired confirguration item

    Returns:
        DataFrame: General data of the desired configuration item
    """
    # Check if TimescaleDB is enabled
    config = load_config()
    use_timescaledb = config.get('core', {}).get('timescaledb', {}).get('enabled', False)
    
    if use_timescaledb:
        try:
            # Try to get data from TimescaleDB first
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
                if not df.empty:
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
        # Handle string timestamps
        utc_time = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%fZ')
        utc_time = utc_time.replace(tzinfo=pytz.UTC)
    
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
        href = home_url + '/plot?ci=' + str(change['ci'])
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
        html_str += '<span style=color:green> *ist wieder verfügbar*</span>'
    elif change['availability_difference'] == -1:
        html_str += '<span style=color:red> *ist nicht mehr verfügbar*</span>'
    else:
        html_str += ' keine Veränderung'
    html_str += + emoji + ' '
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
    message += '<p>bei der letzten Überprüfung hat sich die Verfügbarkeit der folgenden von Ihnen abonierten Komponenten geändert:</p>'

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
        message += create_html_list_item_for_change(change, home_url)
        
    if home_url:    
        message += f'</ul><p>Den aktuellen Status aller Komponenten können Sie unter <a href="{home_url}">{home_url}</a> einsehen.</p>'
    message += '<p>Weitere Hintergrundinformationen finden Sie im <a href="https://fachportal.gematik.de/ti-status">Fachportal der gematik GmbH</a>.</p><p>Viele Grüße<br>TI-Monitoring</p></body></html>'
    
    return message

def load_apprise_config(notifications_config_file):
    """
    Loads and potentially converts notification configuration for Apprise

    Args:
        notifications_config_file (str): Path to json file with notification configurations

    Returns:
        list: List of notification configurations with Apprise URLs
    """
    with open(notifications_config_file, 'r', encoding='utf-8') as f:
        notification_config = json.load(f)
    
    # Convert legacy configuration to Apprise format if needed
    for config in notification_config:
        # If apprise_urls doesn't exist but recipients does, convert recipients to mailto URLs
        if 'apprise_urls' not in config and 'recipients' in config:
            config['apprise_urls'] = [f"mailto://{recipient}" for recipient in config['recipients']]
        # If neither exists, create empty list
        elif 'apprise_urls' not in config:
            config['apprise_urls'] = []
            
    return notification_config

def send_apprise_notifications(file_name, notifications_config_file, home_url):
    """
    Sends notifications via Apprise for each notification configuration about all
    changes that are relevant for the respective configuration

    Args:
        file_name (str): Path to hdf5 file
        notifications_config_file (str): Path to json file with notification configurations
        home_url (str): base url of dash app

    Returns:
        None
    """
    # Load and potentially convert configuration
    notification_config = load_apprise_config(notifications_config_file)
    
    # Get changes
    ci_data = get_data_of_all_cis(file_name)
    changes = ci_data[ci_data['availability_difference']!=0]
    changes_sorted = changes.sort_values(by = 'availability_difference')
    
    # Process each configuration
    for config in notification_config:
        try:
            # Filter relevant changes
            if (config['type'] == 'whitelist'):
                relevant_changes = changes_sorted[changes_sorted['ci'].isin(config['ci_list'])]
            elif (config['type'] == 'blacklist'):
                relevant_changes = changes_sorted[~changes_sorted['ci'].isin(config['ci_list'])]
                
            number_of_relevant_changes = len(relevant_changes)
            if number_of_relevant_changes > 0:
                # Create notification message
                message = create_notification_message(relevant_changes, config['name'], home_url)
                subject = f'TI-Monitoring: {number_of_relevant_changes} Änderungen der Verfügbarkeit'
                
                # Send via Apprise
                apobj = apprise.Apprise()
                for url in config['apprise_urls']:
                    apobj.add(url)
                apobj.notify(title=subject, body=message, body_format=apprise.NotifyFormat.HTML)
        except Exception as e:
            print(f'Sending notification for profile failed: {e}')
            pass

def send_notifications(file_name, notifications_config_file, smtp_settings, home_url):
    """
    Sends email notifications for each notification configuration about all
    changes that are relevant for the respective configuration

    Args:
        file_name (str): Path to hdf5 file
        notifications_config_file (str): Path to json file with notification configurations
        smtp_settings (dict): host, port, username, password and sender address (from)
        home_url (str): base url of dash app

    Returns:
        None
    """
    # get notification config
    with open(notifications_config_file, 'r', encoding='utf-8') as f:
        notification_config = json.load(f)
    # get changes 
    ci_data = get_data_of_all_cis(file_name)
    changes = ci_data[ci_data['availability_difference']!=0]
    changes_sorted = changes.sort_values(by = 'availability_difference')
    # filter relevant changes for each config and send mails
    for config in notification_config:
        try:
            if (config['type'] == 'whitelist'):
                relevant_changes = changes_sorted[changes_sorted['ci'].isin(config['ci_list'])]
            elif (config['type'] == 'blacklist'):
                relevant_changes = changes_sorted[~changes_sorted['ci'].isin(config['ci_list'])]
            number_of_relevant_changes = len(relevant_changes)
            if number_of_relevant_changes > 0:
                message = '<html lang="de"><body><p>Hallo ' + str(config['name']) + ',</p>'
                message += '<p>bei der letzten Überprüfung hat sich die Verfügbarkeit der folgenden von Ihnen abonierten Komponenten geändert:</p><ul>'
                for index, change in relevant_changes.iterrows():
                    message += create_html_list_item_for_change(change, home_url)
                if home_url:    
                    message += '</ul><p>Den aktuellen Status aller Komponenten können Sie unter <a href="' + home_url + '">' + home_url + '</a> einsehen.</p>'
                message += '<p>Weitere Hintergrundinformationen finden Sie im <a href="https://fachportal.gematik.de/ti-status">Fachportal der gematik GmbH</a>.</p><p>Viele Grüße<br>TI-Monitoring</p></body></html>'
                subject = 'TI-Monitoring: ' + str(number_of_relevant_changes) + ' Änderungen der Verfügbarkeit'
                recipients = config['recipients']
                send_mail(smtp_settings, recipients, subject, message)
        except:
            print('Sending notification for profile failed. Please check notifications config file.')
            pass

def load_env_file():
    """
    Load environment variables from .env file
    
    Returns:
        bool: True if .env file was loaded, False otherwise
    """
    return load_dotenv()

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
                       np.apprise_urls, np.email_notifications, np.email_address,
                       u.email as user_email
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
                    profile_id, user_id, profile_name, profile_type, ci_list, apprise_urls, email_notifications, email_address, user_email = profile
                    
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
                        subject = f'TI-Monitoring: {number_of_relevant_changes} Änderungen der Verfügbarkeit'
                        
                        # Add unsubscribe link to the message
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
                                unsubscribe_link = f"{unsubscribe_base_url}/{unsubscribe_token}"
                                message += f'<p><a href="{unsubscribe_link}">Abmelden von diesem Benachrichtigungsprofil</a></p>'
                        
                        # Send via Apprise if Apprise URLs are configured
                        if apprise_urls and len(apprise_urls) > 0:
                            apobj = apprise.Apprise()
                            for url in apprise_urls:
                                apobj.add(url)
                            apobj.notify(title=subject, body=message, body_format=apprise.NotifyFormat.HTML)
                        
                        # Send via simple email if email notifications are enabled
                        if email_notifications and email_address:
                            apobj = apprise.Apprise()
                            # Use mailto URL for simple email
                            email_url = f"mailto://{email_address}"
                            apobj.add(email_url)
                            apobj.notify(title=subject, body=message, body_format=apprise.NotifyFormat.HTML)
                        
                        profiles_processed += 1
                        
                except Exception as e:
                    print(f'Error sending notification for profile {profile_id}: {e}')
                    continue
                    
    except Exception as e:
        print(f'Error in send_db_notifications: {e}')
        
    return profiles_processed
