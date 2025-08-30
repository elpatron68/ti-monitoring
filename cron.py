# Import packages
from mylibrary import *
import yaml
import os
import time
import gc
import sys

# Enhanced logging setup
def log(message):
    """Enhanced logging function with timestamp"""
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] {message}")
    sys.stdout.flush()  # Force output to be displayed immediately

def load_config():
    """Load configuration from YAML file"""
    log("Starting configuration loading...")
    config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
    log(f"Config path: {config_path}")
    log(f"Current working directory: {os.getcwd()}")
    log(f"Config file exists: {os.path.exists(config_path)}")
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        log(f"Configuration loaded successfully. Keys: {list(config.keys())}")
        return config
    except FileNotFoundError as e:
        log(f"ERROR: Config file not found: {e}")
        return {}
    except Exception as e:
        log(f"ERROR: Failed to load config: {e}")
        return {}

def load_core_config():
    """Load core configuration from YAML file"""
    log("Loading core configuration...")
    config = load_config()
    core_config = config.get('core', {})
    log(f"Core config loaded. Keys: {list(core_config.keys())}")
    return core_config

def main():
    log("=== CRON JOB STARTING ===")
    log("Starting main function...")
    
    # Load core configurations
    core_config = load_core_config()
    
    # Get configurations from YAML
    config_file_name = core_config.get('file_name')
    config_url = core_config.get('url')
    config_home_url = core_config.get('home_url')
    config_notifications_file = core_config.get('notifications_config_file')
    
    log(f"Configuration values:")
    log(f"  file_name: {config_file_name}")
    log(f"  url: {config_url}")
    log(f"  home_url: {config_home_url}")
    log(f"  notifications_file: {config_notifications_file}")
    
    if not config_file_name or not config_url:
        log("ERROR: Required configuration missing in config.yaml")
        log(f"  file_name: {config_file_name}")
        log(f"  url: {config_url}")
        return
    
    log(f"Configuration validation passed")
    log(f"Using file: {config_file_name}")
    log(f"Using URL: {config_url}")
    
    # Main loop - run every 5 minutes
    iteration_count = 0
    log("Entering main loop...")
    while True:
        try:
            iteration_count += 1
            log(f"=== ITERATION {iteration_count} ===")
            log(f"Running cron job at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            log("Calling initialize_data_file...")
            initialize_data_file(config_file_name)
            log("initialize_data_file completed")
            
            log("Calling update_file...")
            update_file(config_file_name, config_url)
            log("update_file completed")
            
            # Check if notifications are enabled
            log("Checking notifications...")
            if config_notifications_file and os.path.exists(config_notifications_file):
                log(f"Notifications file exists: {config_notifications_file}")
                try:
                    with open(config_notifications_file, 'r') as f:
                        notifications_config = yaml.safe_load(f)
                    log(f"Notifications config loaded: {len(notifications_config) if notifications_config else 0} profiles")
                    # notifications_config is a list, so we check if it's not empty instead of looking for 'enabled'
                    if notifications_config and len(notifications_config) > 0:
                        log("Sending notifications...")
                        send_apprise_notifications(config_file_name, config_notifications_file, config_home_url)
                        log("Notifications sent successfully")
                    else:
                        log("No notification profiles found")
                except Exception as e:
                    log(f"ERROR with notifications: {e}")
            else:
                log(f"Notifications file not found or not specified: {config_notifications_file}")
            
            log(f"Cron job completed at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Force garbage collection every 10 iterations to prevent memory buildup
            if iteration_count % 10 == 0:
                log("Performing garbage collection...")
                gc.collect()
                log("Garbage collection completed")
            
            log("Sleeping for 5 minutes...")
            
            # Sleep for 5 minutes (300 seconds)
            time.sleep(300)
            
        except KeyboardInterrupt:
            log("Cron job interrupted, exiting...")
            break
        except Exception as e:
            log(f"ERROR in cron job: {e}")
            log(f"Exception type: {type(e).__name__}")
            import traceback
            log(f"Traceback: {traceback.format_exc()}")
            log("Sleeping for 5 minutes before retry...")
            time.sleep(300)

if __name__ == '__main__':
    log("Script started - __name__ == '__main__'")
    try:
        main()
    except Exception as e:
        log(f"FATAL ERROR in main: {e}")
        import traceback
        log(f"Traceback: {traceback.format_exc()}")
        sys.exit(1)
else:
    log(f"Script imported - __name__ == '{__name__}'")