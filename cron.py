# Import packages
from mylibrary import *
from myconfig import *

def main():
    initialize_data_file(file_name)
    update_file(file_name, url)
    if notifications:
        # Use Apprise notifications instead of email notifications
        send_apprise_notifications(file_name, notifications_config_file, home_url)

if __name__ == '__main__':
    main()