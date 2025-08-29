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
    Gets current data from API and updates hdf5 file

    Args:
        file_name (str): Path to hdf5 file
        url (str): URL of API

    Returns:
        None
    """
    data = json.loads(requests.get(url).text)
    df = pd.DataFrame(data)
    with h5.File(file_name, "a") as f:
        for idx in range(len(df)):
            ci = df.iloc[idx]
            # availybility
            group_av = f.require_group("availability/" + str(ci["ci"]))
            av = int(ci["availability"])
            utc_time = datetime.strptime(ci["time"], '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=pytz.UTC)
            timestamp = utc_time.timestamp()
            ds = group_av.require_dataset(str(timestamp),shape=(),dtype=int)
            ds[()] = av
            # configuration items
            group_ci = f.require_group("configuration_items/" + str(ci["ci"]))
            str_256 = h5.string_dtype(encoding='utf-8', length=256)
            for property in ["tid", "bu", "organization", "pdt", "product", "name", "comment", "time"]:
                ds = group_ci.require_dataset(property, shape=(), dtype=str_256)
                ds[()] = ci[property]
            if "current_availability" in group_ci:
                prev_av = group_ci["current_availability"][()]
                av_diff = av - prev_av
            else:
                av_diff = 0
            ds = group_ci.require_dataset("availability_difference",shape=(),dtype=int)
            ds[()] = av_diff
            ds = group_ci.require_dataset("current_availability",shape=(),dtype=int)
            ds[()] = av

def get_availability_data_of_ci(file_name, ci):
    """
    Gets availability data for a specific configuration item from hdf5 file

    Args:
        file_name (str): Path to hdf5 file
        ci (str): ID of the desired confirguration item

    Returns:
        DataFrame: Time series of the availability of the desired configuration item
    """
    all_ci_data = []
    with h5.File(file_name, 'r') as f:
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

def get_data_of_all_cis(file_name):
    """
    Gets general data for all configuration items from hdf5 file such as organization
    and product as well as current availability and availability difference

    Args:
        file_name (str): Path to hdf5 file

    Returns:
        DataFrame: Basic information about all configuration items
    """
    all_ci_data = []
    with h5.File(file_name, 'r') as f:
        group = f["configuration_items"]
        cis = group.keys()
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
            #df = pd.DataFrame(ci_data)
            all_ci_data.append(ci_data)
    return pd.DataFrame(all_ci_data)

def get_data_of_ci(file_name, ci):
    """
    Gets general data for a specific configuration item from hdf5 file

    Args:
        file_name (str): Path to hdf5 file
        ci (str): ID of the desired confirguration item

    Returns:
        DataFrame: General data of the desired configuration item
    """
    all_ci_data = []
    with h5.File(file_name, 'r') as f:
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

def main():
    return

if __name__ == '__main__':
    main()