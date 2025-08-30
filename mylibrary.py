# Import packages
import numpy as np
import pandas as pd
import h5py as h5
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
import os
from dotenv import load_dotenv
import hmac

# Global cache for HDF5 data with size limit
_hdf5_cache = OrderedDict()
_cache_lock = threading.Lock()
_cache_timestamp = None
_cache_ttl = 300  # 5 minutes cache TTL
_cache_max_size = 50  # Maximum number of entries in cache

def clear_hdf5_cache():
    """Clear the HDF5 cache to force fresh data reading"""
    global _hdf5_cache, _cache_timestamp
    with _cache_lock:
        _hdf5_cache.clear()
        _cache_timestamp = None

def initialize_data_file(file_name):
    """
    Creates hdf5 file if necessary and builds up basic group structure
    
    Args:
        file_name (str): Path to hdf5 file

    Returns:
        None
    """
    if not(os.path.isfile(file_name)):
        with h5.File(file_name, "w") as f:
            f.create_group("availability")
            f.create_group("configuration_items")

def update_file(file_name, url):
    """
    Gets current data from API and updates hdf5 file with optimized performance

    Args:
        file_name (str): Path to hdf5 file
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
        
        # Batch process data for better performance
        with h5.File(file_name, "a") as f:
            # Pre-define data types
            str_256 = h5.string_dtype(encoding='utf-8', length=256)
            
            # Process all configuration items in batch
            for idx in range(len(df)):
                ci = df.iloc[idx]
                ci_id = str(ci["ci"])
                
                # Availability data
                group_av = f.require_group("availability/" + ci_id)
                av = int(ci["availability"])
                utc_time = datetime.strptime(ci["time"], '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=pytz.UTC)
                timestamp = utc_time.timestamp()
                
                # Create dataset efficiently
                ds = group_av.require_dataset(str(timestamp), shape=(), dtype=int)
                ds[()] = av
                
                # Configuration items
                group_ci = f.require_group("configuration_items/" + ci_id)
                
                # Batch create all properties
                properties = ["tid", "bu", "organization", "pdt", "product", "name", "comment", "time"]
                for property_name in properties:
                    if property_name in ci:
                        ds = group_ci.require_dataset(property_name, shape=(), dtype=str_256)
                        ds[()] = str(ci[property_name])
                
                # Calculate availability difference
                if "current_availability" in group_ci:
                    prev_av = group_ci["current_availability"][()]
                    av_diff = av - prev_av
                else:
                    av_diff = 0
                
                # Set availability data
                group_ci.require_dataset("availability_difference", shape=(), dtype=int)[()] = av_diff
                group_ci.require_dataset("current_availability", shape=(), dtype=int)[()] = av
        
        # Clear cache after updating file to ensure fresh data
        clear_hdf5_cache()
        
    except requests.RequestException as e:
        print(f"Error fetching data from API: {e}")
        raise
    except Exception as e:
        print(f"Error updating HDF5 file: {e}")
        raise

def get_availability_data_of_ci(file_name, ci):
    """
    Gets availability data for a specific configuration item from hdf5 file

    Args:
        file_name (str): Path to hdf5 file
        ci (str): ID of the desired confirguration item

    Returns:
        DataFrame: Time series of the availability of the desired configuration item
    """
    try:
        # Use SWMR mode to allow multiple readers
        with h5.File(file_name, 'r', swmr=True) as f:
            group = f["availability/" + ci]
            ci_data = {}
            times = []
            values = []
            for name, dataset in group.items():
                if isinstance(dataset, h5.Dataset):
                    time = pd.to_datetime(float(name), unit='s').tz_localize('UTC').tz_convert('Europe/Berlin')
                    times.append(time)
                    values.append(int(dataset[()]))
            ci_data["times"] = np.array(times)
            ci_data["values"] = np.array(values)
            return pd.DataFrame(ci_data)
    except Exception as e:
        print(f"Error reading availability data for CI {ci} from HDF5 file {file_name}: {e}")
        return pd.DataFrame()

def get_data_of_all_cis(file_name):
    """
    Gets general data for all configuration items from hdf5 file such as organization
    and product as well as current availability and availability difference

    Args:
        file_name (str): Path to hdf5 file

    Returns:
        DataFrame: Basic information about all configuration items
    """
    global _hdf5_cache, _cache_timestamp
    
    # Check cache first
    current_time = time.time()
    with _cache_lock:
        if (file_name in _hdf5_cache and 
            _cache_timestamp and 
            current_time - _cache_timestamp < _cache_ttl):
            return _hdf5_cache[file_name].copy()
    
    # If not in cache or expired, read from file
    all_ci_data = []
    try:
        # Use SWMR mode to allow multiple readers
        with h5.File(file_name, 'r', swmr=True) as f:
            group = f["configuration_items"]
            cis = list(group.keys())  # Convert to list to avoid iterator issues
            for ci in cis:
                group = f["configuration_items/"+ci]
                ci_data = {}
                ci_data["ci"] = ci
                for name in group:
                    dataset = group[name]
                    value = dataset[()]
                    # Handle scalar bytes (decode)
                    if isinstance(value, bytes):
                        value = value.decode('utf-8')
                    ci_data[name] = value
                all_ci_data.append(ci_data)
        
        # Update cache with size limit
        result_df = pd.DataFrame(all_ci_data)
        with _cache_lock:
            # Remove oldest entries if cache is at max size
            while len(_hdf5_cache) >= _cache_max_size:
                _hdf5_cache.popitem(last=False)  # Remove oldest entry
                
            _hdf5_cache[file_name] = result_df.copy()
            _cache_timestamp = current_time
            
            # Move to end to mark as most recently used
            _hdf5_cache.move_to_end(file_name)
        
        return result_df
        
    except Exception as e:
        print(f"Error reading HDF5 file {file_name}: {e}")
        # Return cached data if available, even if expired
        with _cache_lock:
            if file_name in _hdf5_cache:
                print(f"Returning cached data due to error")
                # Move to end to mark as most recently used
                _hdf5_cache.move_to_end(file_name)
                return _hdf5_cache[file_name].copy()
        # If no cache available, return empty DataFrame
        return pd.DataFrame()

def get_data_of_ci(file_name, ci):
    """
    Gets general data for a specific configuration item from hdf5 file

    Args:
        file_name (str): Path to hdf5 file
        ci (str): ID of the desired confirguration item

    Returns:
        DataFrame: General data of the desired configuration item
    """
    try:
        # Use SWMR mode to allow multiple readers
        with h5.File(file_name, 'r', swmr=True) as f:
            group = f["configuration_items/"+ci]
            ci_data = {}
            ci_data["ci"] = ci
            for name in group:
                dataset = group[name]
                value = dataset[()]
                # Handle scalar bytes (decode)
                if isinstance(value, bytes):
                    value = value.decode('utf-8')
                ci_data[name] = value
        return pd.DataFrame([ci_data])
    except Exception as e:
        print(f"Error reading CI {ci} from HDF5 file {file_name}: {e}")
        return pd.DataFrame()

def pretty_timestamp(timestamp_str):
    """
    Converts UTC timestamp of API to pretty formatted timestamp in local time

    Args:
        timestamp_str (str): UTC timestamp from API

    Returns:
        str: pretty formatted timestamp in local time
    """
    utc_time = datetime.strptime(timestamp_str, '%Y-%m-%dT%H:%M:%S.%fZ')
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
    html_str = '<li><strong><a href="' + href + '">' + str(change['ci']) + '</a></strong>: ' + str(change['product']) + ', ' + str(change['name']) + ', ' + str(change['organization']) + ' '
    if change['availability_difference'] == 1:
        html_str += '<span style=color:green>ist wieder verfügbar</span>'
    elif change['availability_difference'] == -1:
        html_str += '<span style=color:red>ist nicht mehr verfügbar</span>'
    else:
        html_str += 'keine Veränderung'
    html_str += ', Stand: ' + str(pretty_timestamp(change['time'])) + '</li>'
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
    message += '<p>bei der letzten Überprüfung hat sich die Verfügbarkeit der folgenden von Ihnen abonierten Komponenten geändert:</p><ul>'
    
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