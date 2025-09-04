# Import packages
from mylibrary import *
import yaml
import os
import time
import gc
import sys
import json
import pandas as pd
import numpy as np
import pytz
# h5py removed - using TimescaleDB only

# Enhanced logging setup with file logging and daily rotation
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime
import os
from datetime import timezone

# Global logger instance
_logger = None

def setup_logger():
    """Setup logger with file rotation and console output"""
    global _logger
    
    if _logger is not None:
        return _logger
    
    try:
        # Create data directory if it doesn't exist
        data_dir = os.path.join(os.path.dirname(__file__), 'data')
        os.makedirs(data_dir, exist_ok=True)
        
        # Setup logger
        _logger = logging.getLogger('cron')
        _logger.setLevel(logging.INFO)
        
        # Clear any existing handlers
        _logger.handlers.clear()
        
        # Create formatter with timezone
        class TimezoneFormatter(logging.Formatter):
            def formatTime(self, record, datefmt=None):
                # Convert to Europe/Berlin timezone
                dt = datetime.fromtimestamp(record.created, tz=pytz.timezone('Europe/Berlin'))
                if datefmt:
                    return dt.strftime(datefmt)
                else:
                    return dt.strftime('%Y-%m-%d %H:%M:%S %Z')
        
        formatter = TimezoneFormatter('%(asctime)s - %(levelname)s - %(message)s')
        
        # File handler with daily rotation
        log_file = os.path.join(data_dir, 'cron.log')
        file_handler = TimedRotatingFileHandler(
            log_file, 
            when='midnight', 
            interval=1, 
            backupCount=30,  # Keep 30 days of logs
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        _logger.addHandler(file_handler)
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        _logger.addHandler(console_handler)
        
        return _logger
        
    except Exception as e:
        print(f"Error setting up logger: {e}")
        return None

def log(message, level='INFO'):
    """Log a message with timestamp"""
    logger = setup_logger()
    if logger:
        if level.upper() == 'ERROR':
            logger.error(message)
        elif level.upper() == 'WARNING':
            logger.warning(message)
        else:
            logger.info(message)
    else:
        # Fallback to print if logger setup failed
        timestamp = datetime.now(tz=pytz.timezone('Europe/Berlin')).strftime('%Y-%m-%d %H:%M:%S %Z')
        print(f"{timestamp} - {level} - {message}")

def load_core_config():
    """Load core configuration from config.yaml"""
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        return config.get('core', {})
    except Exception as e:
        log(f"ERROR loading core configuration: {e}")
        return {}



def calculate_recording_duration():
    """Calculate the total recording duration from TimescaleDB availability data"""
    try:
        with get_db_conn() as conn:
            # Get earliest and latest timestamps from TimescaleDB
            query = """
            SELECT 
                MIN(ts) as earliest_ts,
                MAX(ts) as latest_ts,
                COUNT(*) as total_measurements
            FROM measurements
            """
            result = pd.read_sql_query(query, conn)
            
            if result.empty or result['earliest_ts'].iloc[0] is None:
                log("No data found in TimescaleDB")
                return 0, None, None
            
            earliest_ts = result['earliest_ts'].iloc[0]
            latest_ts = result['latest_ts'].iloc[0]
            total_measurements = result['total_measurements'].iloc[0]
            
            # Calculate duration
            duration_seconds = (latest_ts - earliest_ts).total_seconds()
            duration_minutes = duration_seconds / 60
            
            # Convert to Europe/Berlin timezone
            earliest_dt = earliest_ts.tz_convert('Europe/Berlin')
            latest_dt = latest_ts.tz_convert('Europe/Berlin')
            
            log(f"Collected {total_measurements} measurements from TimescaleDB")
            log(f"Recording duration: {duration_minutes:.1f} minutes ({duration_minutes/60/24:.1f} days)")
            log(f"Earliest: {earliest_dt}, Latest: {latest_dt}")
            
            return duration_minutes, earliest_dt, latest_dt
            
    except Exception as e:
        log(f"Error calculating recording duration from TimescaleDB: {e}")
        return 0, None, None

def compute_incident_and_availability_metrics():
    """
    Compute per-CI and aggregated availability metrics using TimescaleDB data.
    - Treat each timestamp's value (0/1) as status until the next timestamp (right-open interval).
    - For the last timestamp, extend interval to 'now'.
    - Incidents are 1->0 transitions; repair is 0->1.
    Returns dict with rollups and per_ci details.
    """
    metrics = {
        'overall_uptime_minutes': 0.0,
        'overall_downtime_minutes': 0.0,
        'overall_availability_percentage_rollup': 0.0,
        'total_incidents': 0,
        'mttr_minutes_mean': 0.0,
        'mtbf_minutes_mean': 0.0,
        'top_unstable_cis_by_incidents': [],
        'top_downtime_cis': [],
        'per_ci_metrics': {}
    }
    try:
        with get_db_conn() as conn:
            # Get all CIs with their availability data (simplified MTTR/MTBF calculation)
            query = """
            WITH ci_metrics AS (
                SELECT 
                    ci,
                    ts,
                    status,
                    LAG(status) OVER (PARTITION BY ci ORDER BY ts) as prev_status,
                    LEAD(ts) OVER (PARTITION BY ci ORDER BY ts) as next_ts
                FROM measurements
                ORDER BY ci, ts
            ),
            ci_availability AS (
                SELECT 
                    ci,
                    SUM(CASE 
                        WHEN next_ts IS NOT NULL THEN 
                            EXTRACT(EPOCH FROM (next_ts - ts)) / 60.0
                        ELSE 
                            EXTRACT(EPOCH FROM (NOW() - ts)) / 60.0
                    END * status) as uptime_minutes,
                    SUM(CASE 
                        WHEN next_ts IS NOT NULL THEN 
                            EXTRACT(EPOCH FROM (next_ts - ts)) / 60.0
                        ELSE 
                            EXTRACT(EPOCH FROM (NOW() - ts)) / 60.0
                    END * (1 - status)) as downtime_minutes,
                    SUM(CASE 
                        WHEN prev_status = 1 AND status = 0 THEN 1 
                        ELSE 0 
                    END) as incidents
                FROM ci_metrics
                GROUP BY ci
            )
            SELECT 
                ca.ci,
                ca.uptime_minutes,
                ca.downtime_minutes,
                ca.incidents,
                -- Simple MTTR/MTBF calculation based on downtime and incidents
                CASE 
                    WHEN ca.incidents > 0 THEN ca.downtime_minutes / ca.incidents
                    ELSE 0
                END as mttr_minutes,
                CASE 
                    WHEN ca.incidents > 1 THEN ca.uptime_minutes / ca.incidents
                    ELSE 0
                END as mtbf_minutes,
                CASE 
                    WHEN (ca.uptime_minutes + ca.downtime_minutes) > 0 THEN
                        (ca.uptime_minutes / (ca.uptime_minutes + ca.downtime_minutes)) * 100
                    ELSE 0
                END as availability_percentage,
                cm.name,
                cm.organization
            FROM ci_availability ca
            LEFT JOIN ci_metadata cm ON ca.ci = cm.ci
            ORDER BY ca.ci
            """
            
            result = pd.read_sql_query(query, conn)
            
            if result.empty:
                log("No availability data found in TimescaleDB")
                return metrics
            
            # Process results
            total_mttr_values = []
            
            for _, row in result.iterrows():
                ci = row['ci']
                uptime_minutes = float(row['uptime_minutes']) if row['uptime_minutes'] else 0.0
                downtime_minutes = float(row['downtime_minutes']) if row['downtime_minutes'] else 0.0
                incidents = int(row['incidents']) if row['incidents'] else 0
                availability_pct = float(row['availability_percentage']) if row['availability_percentage'] else 0.0
                mttr_minutes = float(row['mttr_minutes']) if row['mttr_minutes'] is not None else 0.0
                mtbf_minutes = float(row['mtbf_minutes']) if row['mtbf_minutes'] is not None else 0.0
                
                # Store per-CI metrics
                metrics['per_ci_metrics'][ci] = {
                    'uptime_minutes': uptime_minutes,
                    'downtime_minutes': downtime_minutes,
                    'availability_percentage': availability_pct,
                    'incidents': incidents,
                    'mttr_minutes': mttr_minutes,
                    'mtbf_minutes': mtbf_minutes,
                    'name': row.get('name', ''),
                    'organization': row.get('organization', '')
                }
                
                # Add to overall totals
                metrics['overall_uptime_minutes'] += uptime_minutes
                metrics['overall_downtime_minutes'] += downtime_minutes
                metrics['total_incidents'] += incidents
                
                # Collect MTTR values for overall calculation
                if mttr_minutes > 0:
                    total_mttr_values.append(mttr_minutes)
            
            # Calculate overall availability percentage
            total_overall_minutes = metrics['overall_uptime_minutes'] + metrics['overall_downtime_minutes']
            if total_overall_minutes > 0:
                metrics['overall_availability_percentage_rollup'] = (
                    metrics['overall_uptime_minutes'] / total_overall_minutes * 100
                )
            
            # Calculate overall MTTR and MTBF
            if total_mttr_values:
                metrics['mttr_minutes_mean'] = sum(total_mttr_values) / len(total_mttr_values)
            else:
                metrics['mttr_minutes_mean'] = 0.0
                
            # MTBF removed from global stats - now calculated per CI in plots
            metrics['mtbf_minutes_mean'] = 0.0
                
            log(f"MTTR values: {len(total_mttr_values)}")
            if total_mttr_values:
                log(f"MTTR mean: {metrics['mttr_minutes_mean']:.2f} minutes")
            log("MTBF: Now calculated per CI in plots (removed from global stats)")
            
            # Create top unstable CIs list
            top_unstable = sorted(
                metrics['per_ci_metrics'].items(),
                key=lambda x: x[1]['incidents'],
                reverse=True
            )[:10]
            
            metrics['top_unstable_cis_by_incidents'] = [
                {
                    'ci': ci,
                    'incidents': data['incidents'],
                    'availability_percentage': data['availability_percentage'],
                    'name': data['name'],
                    'organization': data['organization']
                }
                for ci, data in top_unstable
            ]
            
            # Create top downtime CIs list
            top_downtime = sorted(
                metrics['per_ci_metrics'].items(),
                key=lambda x: x[1]['downtime_minutes'],
                reverse=True
            )[:10]
            
            metrics['top_downtime_cis'] = [
                {
                    'ci': ci,
                    'downtime_minutes': data['downtime_minutes'],
                    'availability_percentage': data['availability_percentage'],
                    'name': data['name'],
                    'organization': data['organization']
                }
                for ci, data in top_downtime
            ]
            
            log(f"Computed metrics for {len(metrics['per_ci_metrics'])} CIs from TimescaleDB")
            return metrics
            
    except Exception as e:
        log(f"Error computing incident and availability metrics from TimescaleDB: {e}")
        return metrics

def format_duration_minutes(minutes):
    """Format duration in minutes to human readable string"""
    if minutes < 60:
        return f"{minutes:.1f} Minuten"
    elif minutes < 1440:  # 24 hours
        hours = minutes / 60
        return f"{hours:.1f} Stunden"
    else:
        days = minutes / 1440
        return f"{days:.1f} Tage"

def calculate_overall_statistics(cis):
    """
    Calculate overall statistics for all Configuration Items including:
    - Total number of CIs
    - Currently available/unavailable CIs
    - Overall availability percentage
    - Recording duration
    - Database size
    - Incident metrics
    """
    try:
        log("Calculating overall statistics...")
        
        # Basic CI counts
        total_cis = len(cis)
        currently_available = len(cis[cis['current_availability'] == 1]) if 'current_availability' in cis.columns else 0
        currently_unavailable = total_cis - currently_available
        
        # Get recording duration from TimescaleDB
        total_recording_minutes, earliest_timestamp, latest_timestamp = calculate_recording_duration()
        
        # Get database size from TimescaleDB
        database_size_mb = 0
        try:
            with get_db_conn() as conn:
                # Get raw size in bytes and convert to MB
                query = "SELECT pg_database_size(current_database()) as size_bytes"
                result = pd.read_sql_query(query, conn)
                if not result.empty:
                    size_bytes = result['size_bytes'].iloc[0]
                    database_size_mb = size_bytes / (1024 * 1024)  # Convert bytes to MB
                    log(f"Database size: {database_size_mb:.2f} MB")
        except Exception as e:
            log(f"Error getting database size: {e}")
        
        # Compute incident and availability metrics from TimescaleDB
        availability_metrics = compute_incident_and_availability_metrics()
        
        # Get current time in Europe/Berlin
        current_time = pd.Timestamp.now(tz=pytz.timezone('Europe/Berlin'))
        
        # Calculate data age
        data_age_hours = 0
        data_age_formatted = "Unbekannt"
        if latest_timestamp is not None:
            # Ensure both timestamps are timezone-aware
            if latest_timestamp.tzinfo is None:
                latest_timestamp = latest_timestamp.tz_localize('UTC')
            if current_time.tzinfo is None:
                current_time = current_time.tz_localize('UTC')
            
            time_diff = current_time - latest_timestamp
            data_age_hours = time_diff.total_seconds() / 3600
            if data_age_hours < 1:
                data_age_formatted = "Aktuell"
            elif data_age_hours < 24:
                data_age_formatted = f"{data_age_hours:.1f} Stunden"
            else:
                data_age_formatted = f"{data_age_hours/24:.1f} Tage"
            log(f"Data age: {data_age_formatted} (latest: {latest_timestamp})")
        
        return {
            'total_cis': total_cis,
            'currently_available': currently_available,
            'currently_unavailable': currently_unavailable,
            'overall_availability_percentage': availability_metrics.get('overall_availability_percentage_rollup', 0.0),
            'total_recording_minutes': total_recording_minutes,
            'earliest_timestamp': earliest_timestamp,
            'latest_timestamp': latest_timestamp,
            'data_age_hours': data_age_hours,
            'data_age_formatted': data_age_formatted,
            'database_size_mb': database_size_mb,
            'total_incidents': availability_metrics.get('total_incidents', 0),
            'mttr_minutes_mean': availability_metrics.get('mttr_minutes_mean', 0.0),
            'mtbf_minutes_mean': availability_metrics.get('mtbf_minutes_mean', 0.0),
            'top_unstable_cis_by_incidents': availability_metrics.get('top_unstable_cis_by_incidents', []),
            'top_downtime_cis': availability_metrics.get('top_downtime_cis', []),
            'per_ci_metrics': availability_metrics.get('per_ci_metrics', {}),
            'calculated_at': time.time()
        }
        
    except Exception as e:
        log(f"Error calculating overall statistics: {e}")
        return {}

def update_statistics_file():
    """Update the statistics JSON file with current data from TimescaleDB"""
    try:
        log("Updating statistics file...")
        
        # Get current CI data from TimescaleDB
        log("Retrieving CI data from TimescaleDB...")
        cis = get_data_of_all_cis('')  # file_name parameter not used anymore
        if cis.empty:
            log("ERROR: No CI data available for statistics calculation")
            return False
        
        log(f"Retrieved {len(cis)} CIs from TimescaleDB")
        log(f"CI columns: {list(cis.columns)}")
        
        # Calculate statistics from TimescaleDB using mylibrary function
        log("Calculating overall statistics...")
        stats = get_timescaledb_statistics_data()
        if not stats:
            log("ERROR: Failed to calculate statistics")
            return False
        
        # Get recent incidents data
        log("Retrieving recent incidents...")
        recent_incidents = get_recent_incidents(limit=10)  # Get more for potential expansion
        stats['recent_incidents'] = recent_incidents
        log(f"Retrieved {len(recent_incidents)} recent incidents")
        
        # Add timestamp for when statistics were calculated (UTC)
        stats['last_updated'] = datetime.now(timezone.utc).isoformat()
        
        # Force garbage collection after heavy computation
        import gc
        gc.collect()
        log("Memory cleanup completed after statistics calculation")
        
        # Save to JSON file
        statistics_file_path = os.path.join(os.path.dirname(__file__), 'data', 'statistics.json')
        try:
            with open(statistics_file_path, 'w', encoding='utf-8') as f:
                json.dump(stats, f, indent=2, ensure_ascii=False, default=str)
            log(f"Statistics saved to {statistics_file_path}")
            return True
        except Exception as e:
            log(f"ERROR saving statistics file: {e}")
            return False
            
    except Exception as e:
        log(f"ERROR in update_statistics_file: {e}")
        return False



def main():
    """Main cron job function - TimescaleDB only version"""
    try:
        log("Starting TI-Monitoring cron job (TimescaleDB only)")
        

        
        # Load configuration
        core_config = load_core_config()
        if not core_config:
            log("ERROR: Could not load core configuration")
            return
        
        # Get configurations from YAML with validation
        config_url = core_config.get('url')
        # home_url entfernt – nicht mehr benötigt
        config_home_url = None
        retention_months = core_config.get('retention_months', 6)

        
        log(f"Configuration values:")
        log(f"  url: {config_url}")
        # log(f"  home_url: {config_home_url}")
        log(f"  retention_months: {retention_months} months")
        
        if not config_url:
            log("ERROR: Required configuration missing in config.yaml")
            log(f"  url: {config_url}")
            return
        
        log(f"Configuration validation passed")
        log(f"Using URL: {config_url}")
        
        # Initialize counters
        iteration_count = 0
        last_stats_update_time = 0
        last_notification_time = 0
        last_retention_time = 0
        
        # Main loop
        while True:
            try:
                iteration_count += 1
                now_epoch = time.time()
                log(f"=== Iteration {iteration_count} ===")
                
                # Update data from API to TimescaleDB
                try:
                    log("Calling update_file...")
                    update_file('', config_url)  # file_name parameter not used anymore
                    log("update_file completed")
                except Exception as e:
                    log(f"ERROR in update_file: {e}")
                

                
                # Update statistics file hourly
                if now_epoch - last_stats_update_time > 3600:  # Every hour
                    try:
                        log("Updating statistics file (hourly)...")
                        update_statistics_file()
                        last_stats_update_time = now_epoch
                        log("Statistics update completed")
                    except Exception as e:
                        log(f"ERROR in statistics update: {e}")
                
                # Send notifications every 5 minutes
                if now_epoch - last_notification_time > 300:  # Every 5 minutes
                    try:
                        log("Sending DB-based notifications...")
                        result = send_db_notifications()
                        log(f"DB notifications result: {result['message']}")
                        
                        # Fallback to file-based notifications if no DB profiles exist
                        if result['profiles_processed'] == 0:
                            log("No DB profiles found, trying file-based notifications...")
                            config_notifications_file = os.path.join(os.path.dirname(__file__), 'notifications.json')
                            if os.path.exists(config_notifications_file):
                                with open(config_notifications_file, 'r', encoding='utf-8') as f:
                                    notifications_config = json.load(f)
                                
                                if notifications_config and len(notifications_config) > 0:
                                    log("Sending file-based notifications...")
                                    send_apprise_notifications('', config_notifications_file, None)  # home_url entfällt
                                    log("File-based notifications sent successfully")
                                else:
                                    log("No file-based notifications configured")
                            else:
                                log("No notifications file found")
                        
                        last_notification_time = now_epoch
                    except Exception as e:
                        log(f"ERROR in notifications: {e}")
                
                # Run retention policy daily
                if now_epoch - last_retention_time > 86400:  # Every 24 hours
                    try:
                        log("Running retention policy...")
                        # TimescaleDB retention is handled by drop_chunks policy
                        log("Retention policy completed (handled by TimescaleDB drop_chunks)")
                        last_retention_time = now_epoch
                    except Exception as e:
                        log(f"ERROR in retention policy: {e}")
                
                # Clean up old logs
                try:
                    cleanup_old_logs()
                except Exception as e:
                    log(f"ERROR in cleanup_old_logs: {e}")
                
                # Wait 5 minutes before next iteration
                log("Waiting 5 minutes before next iteration...")
                time.sleep(300)
                
            except KeyboardInterrupt:
                log("Received keyboard interrupt, shutting down...")
                break
            except Exception as e:
                log(f"ERROR in main loop iteration: {e}")
                time.sleep(60)  # Wait 1 minute before retrying
                
    except Exception as e:
        log(f"FATAL ERROR in main: {e}")
        sys.exit(1)

def cleanup_old_logs():
    """Clean up old log files"""
    try:
        data_dir = os.path.join(os.path.dirname(__file__), 'data')
        log_files = [f for f in os.listdir(data_dir) if f.startswith('cron.log')]
        
        for log_file in log_files:
            if log_file != 'cron.log':  # Keep current log
                file_path = os.path.join(data_dir, log_file)
                file_age = time.time() - os.path.getmtime(file_path)
                if file_age > 30 * 24 * 3600:  # 30 days
                    os.remove(file_path)
                    log(f"Removed old log file: {log_file}")
                    
    except Exception as e:
        log(f"Error in cleanup_old_logs: {e}")

if __name__ == "__main__":
    main()
