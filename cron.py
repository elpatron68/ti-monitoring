# Import packages
from mylibrary import *
from myconfig import *
import yaml
import os

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
    
    # Get configurations from YAML as primary source, fallback to myconfig.py
    config_file_name = core_config.get('file_name') or file_name
    config_url = core_config.get('url') or url
    config_home_url = core_config.get('home_url') or home_url
    config_notifications_file = core_config.get('notifications_config_file') or notifications_config_file
    
    initialize_data_file(config_file_name)
    update_file(config_file_name, config_url)
    if notifications:
        # Use Apprise notifications instead of email notifications
        send_apprise_notifications(config_file_name, config_notifications_file, config_home_url)

if __name__ == '__main__':
    main()