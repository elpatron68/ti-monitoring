from mylibrary import *
from myconfig import *
import yaml
import os

def load_config():
    """Load configuration from YAML file"""
    config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'config.yaml')
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

import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

def comma_format(x, pos):
    return str(x).replace('.', ',')

# Load core configurations
core_config = load_core_config()

# Get file_name from YAML as primary source, fallback to myconfig.py
file_name = core_config.get('file_name') or file_name

# specify the file name if it differs from the name in the config file
#file_name = 'data_2025_KW34.hdf5'
# get basic data and availability data for all cis
all_data = []
for index, ci in get_data_of_all_cis(file_name).iterrows():
    availability_data = get_availability_data_of_ci(file_name, ci['ci'])
    # selection of time window
    #availability_data = availability_data[availability_data['times']>pd.Timestamp('2025-08-18T06:00:0.0').tz_localize('Europe/Berlin')]
    #availability_data = availability_data[availability_data['times']<pd.Timestamp('2025-08-22T18:01:0.0').tz_localize('Europe/Berlin')]
    # get first and last timestamp of window
    first_timestamp = availability_data['times'].iloc[0]
    last_timestamp = availability_data['times'].iloc[-1]
    expected_number_of_data_points = int(round(pd.Timedelta(last_timestamp - first_timestamp).total_seconds())/300)
    number_of_dropped_data_points = expected_number_of_data_points - len(availability_data['values'])
    entry = {
        "ci_name" : ci['ci'] + ', ' + ci['name'] + '\n' + ci['organization'],
        "available" : len(availability_data[availability_data['values']==1]),
        "unavailable" : len(availability_data[availability_data['values']==0]),
        "unknown" : number_of_dropped_data_points,
        "first_timestamp" : first_timestamp,
        "last_timestamp" : last_timestamp,
        "expected_number_of_data_points" : expected_number_of_data_points
    }
    all_data.append(entry)
all_data = pd.DataFrame(all_data)

# plot cis that were unavailable
plot_data = all_data[all_data['unavailable']>0].sort_values(by = 'unavailable')

data_start = plot_data['first_timestamp'].min().strftime('%d.%m.%Y %H:%M:%S Uhr')
data_end = plot_data['last_timestamp'].max().strftime('%d.%m.%Y %H:%M:%S Uhr')
names = plot_data['ci_name']
data = plot_data['unavailable'].values*5/60
fig, ax = plt.subplots(figsize = (15, 10))
ax.tick_params(labelsize = 8)
ax.tick_params(axis='x', labelsize = 12)
barh = ax.barh(names, data, 0.5)
ax.bar_label(barh, labels=[f"{value:,.2f}".replace('.', ',') for value in data])
ax.text(
    data.max()/4,
    len(data)/6,
    """Die Berechung der Ausfallzeiten erfolgte durch Multiplikation
der Anzahl der Datenpunkte 'nicht verfügbar' mit 5 Minuten,
der Dauer eines Abfrageintervalls. Die Daten wurden von der
öffentlichen TI-Lage-Schnittstelle der gematik GmbH abgerufen.
Bei der Interpretation sind demensprechend die Hinweise in der
Dokumentation der Schnittstelle zu berücksichtigen. Weitere
Informationen unter https://github.com/gematik/api-tilage.
Alle Angaben ohne Gewähr."""
)
ax.set_title("Störungen zentraler TI-Komponenten\nim Zeitraum " + data_start + ' bis ' + data_end)
ax.set_xlabel('Störungsdauer in Stunden')
ax.xaxis.set_major_formatter(FuncFormatter(comma_format))
plt.tight_layout()
#plt.show()
export_file_path = 'examples/data_analysis/plot_unavailable_cis.png'
plt.savefig(export_file_path, dpi = 600)

# export plot data to csv file
#plot_data.to_csv('data.csv')