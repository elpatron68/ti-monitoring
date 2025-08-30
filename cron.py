# Import packages
from mylibrary import *
import yaml
import os
import time

def load_config():
    """Load configuration from YAML file"""
    config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        return config
    except FileNotFoundError:
        return {}
    except Exception:
        return {}

def load_core_config():
    """Load core configuration from YAML file"""
    config = load_config()
    return config.get('core', {})

def main():
    # Load core configurations
    core_config = load_core_config()
    
    # Get configurations from YAML
    config_file_name = core_config.get('file_name')
    config_url = core_config.get('url')
    config_home_url = core_config.get('home_url')
    config_notifications_file = core_config.get('notifications_config_file')
    
    if not config_file_name or not config_url:
        print("Error: Required configuration missing in config.yaml")
        print(f"file_name: {config_file_name}")
        print(f"url: {config_url}")
        return
    
    print(f"Using file: {config_file_name}")
    print(f"Using URL: {config_url}")
    
    # Main loop - run every 5 minutes
    while True:
        try:
            print(f"Running cron job at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            initialize_data_file(config_file_name)
            update_file(config_file_name, config_url)
            
            # Check if notifications are enabled
            if config_notifications_file and os.path.exists(config_notifications_file):
                try:
                    with open(config_notifications_file, 'r') as f:
                        notifications_config = yaml.safe_load(f)
                    # notifications_config is a list, so we check if it's not empty instead of looking for 'enabled'
                    if notifications_config and len(notifications_config) > 0:
                        send_apprise_notifications(config_file_name, config_notifications_file, config_home_url)
                except Exception as e:
                    print(f"Error with notifications: {e}")
            
            print(f"Cron job completed at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            print("Sleeping for 5 minutes...")
            
            # Sleep for 5 minutes (300 seconds)
            time.sleep(300)
            
        except KeyboardInterrupt:
            print("Cron job interrupted, exiting...")
            break
        except Exception as e:
            print(f"Error in cron job: {e}")
            print("Sleeping for 5 minutes before retry...")
            time.sleep(300)

if __name__ == '__main__':
    main()