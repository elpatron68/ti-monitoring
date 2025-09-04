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

def init_user_notifications_schema() -> None:
    """Erstellt Tabellen für Benutzer, OTP, Sessions und Notification-Profile (idempotent)."""
    with get_db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

            CREATE TABLE IF NOT EXISTS users (
              id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
              email_hash TEXT UNIQUE,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              deleted_at TIMESTAMPTZ
            );

            CREATE TABLE IF NOT EXISTS user_otps (
              id BIGSERIAL PRIMARY KEY,
              user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              code_hash TEXT NOT NULL,
              expires_at TIMESTAMPTZ NOT NULL,
              consumed_at TIMESTAMPTZ
            );

            CREATE TABLE IF NOT EXISTS sessions (
              id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
              user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              issued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              expires_at TIMESTAMPTZ,
              revoked_at TIMESTAMPTZ,
              user_agent TEXT,
              ip TEXT
            );

            CREATE TABLE IF NOT EXISTS notification_profiles (
              id BIGSERIAL PRIMARY KEY,
              user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              name TEXT NOT NULL,
              type TEXT NOT NULL CHECK (type IN ('whitelist','blacklist')),
              config_encrypted BYTEA,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS notification_profile_cis (
              profile_id BIGINT NOT NULL REFERENCES notification_profiles(id) ON DELETE CASCADE,
              ci TEXT NOT NULL,
              PRIMARY KEY (profile_id, ci)
            );

            CREATE TABLE IF NOT EXISTS destinations (
              id BIGSERIAL PRIMARY KEY,
              profile_id BIGINT NOT NULL REFERENCES notification_profiles(id) ON DELETE CASCADE,
              provider TEXT NOT NULL,
              config_encrypted BYTEA NOT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        conn.commit()

def _hash_otp(code: str) -> str:
    return hashlib.sha256(code.encode('utf-8')).hexdigest()

def _generate_otp_code() -> str:
    return f"{secrets.randbelow(1000000):06d}"

def get_profile_salt():
    """Lädt den Profil-Salt aus der .env Datei"""
    try:
        return os.getenv('TI_PROFILE_SALT', 'default-salt-change-me')
    except:
        return 'default-salt-change-me'

def hash_email_with_salt(email):
    """Erstellt einen SHA-256 Hash der E-Mail-Adresse mit Salt"""
    salt = get_profile_salt()
    return hashlib.sha256((email.lower() + salt).encode('utf-8')).hexdigest()

def ensure_user(email: str) -> Optional[str]:
    """Erzeugt oder liefert user.id für die E-Mail."""
    email_hash = hash_email_with_salt(email)
    with get_db_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE email_hash=%s AND deleted_at IS NULL", (email_hash,))
        row = cur.fetchone()
        if row:
            return str(row[0])
        cur.execute("INSERT INTO users(email_hash) VALUES(%s) RETURNING id", (email_hash,))
        new_id = cur.fetchone()[0]
        conn.commit()
        return str(new_id)

def create_otp_for_user(email: str, ttl_minutes: int = 10) -> str:
    """Erstellt einen OTP-Code, speichert den Hash und gibt den Klartext zurück (per Mail zu senden)."""
    user_id = ensure_user(email)
    code = _generate_otp_code()
    code_hash = _hash_otp(code)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    with get_db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO user_otps(user_id, code_hash, expires_at) VALUES(%s,%s,%s)
            """,
            (user_id, code_hash, expires_at)
        )
        conn.commit()
    return code

def verify_otp_and_create_session(email: str, code: str, session_days: int = 30) -> Optional[str]:
    """Verifiziert OTP und erzeugt eine Session. Liefert session.id oder None."""
    email_hash = hash_email_with_salt(email)
    with get_db_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE email_hash=%s AND deleted_at IS NULL", (email_hash,))
        u = cur.fetchone()
        if not u:
            return None
        user_id = u[0]
        cur.execute(
            """
            SELECT id, code_hash, expires_at, consumed_at
            FROM user_otps
            WHERE user_id=%s
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id,)
        )
        row = cur.fetchone()
        if not row:
            return None
        otp_id, code_hash, expires_at, consumed_at = row
        now = datetime.now(timezone.utc)
        if consumed_at is not None or expires_at is None or now > expires_at:
            return None
        if _hash_otp(code) != code_hash:
            return None
        # consume otp
        cur.execute("UPDATE user_otps SET consumed_at=%s WHERE id=%s", (now, otp_id))
        # create session
        expires = now + timedelta(days=session_days)
        cur.execute(
            "INSERT INTO sessions(user_id, issued_at, expires_at) VALUES(%s,%s,%s) RETURNING id",
            (user_id, now, expires)
        )
        session_id = cur.fetchone()[0]
        conn.commit()
        return str(session_id)

def get_user_id_by_session(session_id: str) -> Optional[str]:
    with get_db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT user_id, revoked_at, expires_at FROM sessions WHERE id=%s",
            (session_id,)
        )
        row = cur.fetchone()
        if not row:
            return None
        user_id, revoked_at, expires_at = row
        now = datetime.now(timezone.utc)
        if revoked_at is not None or (expires_at is not None and now > expires_at):
            return None
        return str(user_id)

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

def send_db_notifications():
    """
    Sends notifications via Apprise for all active notification profiles from the database.
    This replaces the file-based notification system with a database-driven approach.
    
    Returns:
        dict: Summary of notifications sent
    """
    try:
        # Initialize counters
        profiles_processed = 0
        notifications_sent = 0
        errors = 0
        
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                # Get all notification profiles with their CIs and destinations (no is_active column in schema)
                query = """
                SELECT 
                    np.id as profile_id,
                    np.name as profile_name,
                    np.type as profile_type,
                    npci.ci,
                    d.id as destination_id,
                    d.provider,
                    d.config_encrypted
                FROM notification_profiles np
                LEFT JOIN notification_profile_cis npci ON np.id = npci.profile_id
                LEFT JOIN destinations d ON np.id = d.profile_id
                ORDER BY np.id, npci.ci, d.id
                """
                
                cur.execute(query)
                rows = cur.fetchall()
                
                if not rows:
                    print("No active notification profiles found in database")
                    return {
                        'profiles_processed': 0,
                        'notifications_sent': 0,
                        'errors': 0,
                        'message': 'No active profiles found'
                    }
                
                # Group by profile
                profiles = {}
                for row in rows:
                    profile_id, profile_name, profile_type, ci, dest_id, provider, config_encrypted = row
                    
                    if profile_id not in profiles:
                        profiles[profile_id] = {
                            'name': profile_name,
                            'type': profile_type or 'whitelist',
                            'cis': set(),
                            'destinations': []
                        }
                    
                    if ci:
                        profiles[profile_id]['cis'].add(ci)
                    
                    if dest_id and provider and config_encrypted:
                        # Decrypt destination config
                        config = {}
                        if is_encryption_ready():
                            try:
                                config = decrypt_config_json(config_encrypted)
                            except Exception as e:
                                print(f"WARN: Failed to decrypt destination config for id {dest_id}: {e}")
                                continue
                        else:
                            try:
                                config = _json.loads(config_encrypted.decode('utf-8'))
                            except Exception:
                                continue
                        
                        # Extract Apprise URLs from config
                        urls = config.get('urls', [])
                        if urls:
                            profiles[profile_id]['destinations'].append({
                                'id': dest_id,
                                'provider': provider,
                                'urls': urls
                            })
                
                # Get current CI changes
                ci_data = get_data_of_all_cis('')  # file_name not used anymore
                changes = ci_data[ci_data['availability_difference'] != 0]
                changes_sorted = changes.sort_values(by='availability_difference')
                
                # Process each profile
                for profile_id, profile_data in profiles.items():
                    try:
                        profiles_processed += 1
                        profile_name = profile_data['name']
                        profile_type = (profile_data.get('type') or 'whitelist').lower()
                        profile_cis = list(profile_data['cis'])
                        destinations = profile_data['destinations']
                        
                        if not destinations:
                            print(f"Profile {profile_name} has no destinations, skipping")
                            continue
                        
                        # Filter changes for this profile according to type
                        if profile_type == 'whitelist':
                            if not profile_cis:
                                print(f"Profile {profile_name} whitelist has no CIs, skipping")
                                continue
                            relevant_changes = changes_sorted[changes_sorted['ci'].isin(profile_cis)]
                        elif profile_type == 'blacklist':
                            if profile_cis:
                                relevant_changes = changes_sorted[~changes_sorted['ci'].isin(profile_cis)]
                            else:
                                # Empty blacklist means allow all
                                relevant_changes = changes_sorted
                        else:
                            # Fallback behaves like whitelist
                            if not profile_cis:
                                print(f"Profile {profile_name} unknown type uses whitelist semantics but has no CIs, skipping")
                                continue
                            relevant_changes = changes_sorted[changes_sorted['ci'].isin(profile_cis)]
                        number_of_relevant_changes = len(relevant_changes)
                        
                        if number_of_relevant_changes == 0:
                            print(f"Profile {profile_name}: No relevant changes found")
                            continue
                        
                        # Create notification message
                        message = create_notification_message(relevant_changes, profile_name, '/')
                        subject = f'TI-Monitoring: {number_of_relevant_changes} Änderungen der Verfügbarkeit'
                        
                        # Send to all destinations for this profile
                        apobj = apprise.Apprise()
                        for dest in destinations:
                            for url in dest['urls']:
                                apobj.add(url)
                        
                        if apobj.notify(title=subject, body=message, body_format=apprise.NotifyFormat.HTML):
                            notifications_sent += 1
                            print(f"Profile {profile_name}: Sent notification about {number_of_relevant_changes} changes to {len(destinations)} destinations")
                        else:
                            errors += 1
                            print(f"Profile {profile_name}: Failed to send notification")
                            
                    except Exception as e:
                        errors += 1
                        print(f"Error processing profile {profile_id}: {e}")
                        continue
        
        return {
            'profiles_processed': profiles_processed,
            'notifications_sent': notifications_sent,
            'errors': errors,
            'message': f'Processed {profiles_processed} profiles, sent {notifications_sent} notifications, {errors} errors'
        }
        
    except Exception as e:
        print(f"Error in send_db_notifications: {e}")
        return {
            'profiles_processed': 0,
            'notifications_sent': 0,
            'errors': 1,
            'message': f'Error: {e}'
        }

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
        

# === AEAD Encryption Helpers (Env-Key) ===
def _get_secret_key_bytes() -> bytes:
    try:
        import base64 as _b64
        key_b64 = (os.environ.get('TI_SECRET_KEY') or '').strip()
        if not key_b64:
            return b''
        return _b64.urlsafe_b64decode(key_b64.encode('utf-8'))
    except Exception:
        return b''

def is_encryption_ready() -> bool:
    return bool(_get_secret_key_bytes())

def derive_aead_key() -> bytes:
    key = _get_secret_key_bytes()
    if len(key) >= 32:
        return key[:32]
    return (key + b'\x00' * 32)[:32]

def aead_encrypt(plaintext: bytes, aad: bytes = b'') -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = derive_aead_key()
    if not key:
        return plaintext
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext, aad)
    return nonce + ct

def aead_decrypt(blob: bytes, aad: bytes = b'') -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key = derive_aead_key()
    if not key:
        return blob
    if not blob or len(blob) < 13:
        return b''
    nonce, ct = blob[:12], blob[12:]
    try:
        return AESGCM(key).decrypt(nonce, ct, aad)
    except Exception:
        return b''

def encrypt_config_json(config_obj: dict) -> bytes:
    import json as _json
    payload = _json.dumps(config_obj, ensure_ascii=False).encode('utf-8')
    return aead_encrypt(payload)

def decrypt_config_json(blob: bytes) -> dict:
    import json as _json
    try:
        data = aead_decrypt(blob)
        if not data:
            return {}
        return _json.loads(data.decode('utf-8'))
    except Exception:
        return {}
