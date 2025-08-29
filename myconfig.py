# URL for API - NOW CONFIGURED IN config.yaml
#url = "https://ti-lage.prod.ccs.gematik.solutions/lageapi/v1/tilage/bu/PU"

# path to hdf5 file for saving the availability data - NOW CONFIGURED IN config.yaml
#file_name = "data.hdf5"

# switching email notofications on/off
notifications = False

# configuration for notofications - NOW CONFIGURED IN config.yaml
#notifications_config_file = 'notifications.json'

# smtp settings for email notifications
smtp_settings = {
    'host' : '********',
    'port' : 587,
    'user' : '********',
    'password' : '********',
    'from' : '********'
}

# home url for dash app - NOW CONFIGURED IN config.yaml
#home_url = 'https://ti-monitoring.lukas-schmidt-russnak.de'

# time frame for statistics in web app - NOW CONFIGURED IN config.yaml
stats_delta_hours = 12

def main():
    return

if __name__ == '__main__':
    main()