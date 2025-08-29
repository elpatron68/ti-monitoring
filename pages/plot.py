import dash
from dash import html, dcc
import plotly.express as px
from mylibrary import *
from myconfig import *
import yaml
import os

def load_config():
    """Load configuration from YAML file"""
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
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

dash.register_page(__name__)


def serve_layout(ci=None, **other_unknown_query_strings):
    # Load core configurations
    core_config = load_core_config()
    
    # Get configurations from YAML as primary source, fallback to myconfig.py
    config_file_name = core_config.get('file_name') or file_name
    config_home_url = core_config.get('home_url') or home_url
    config_stats_delta_hours = core_config.get('stats_delta_hours') or stats_delta_hours
    
    # Handle case when ci is None (no query parameter provided)
    if ci is None:
        return html.Div([
            html.H2('Fehler: Keine Komponente angegeben'),
            html.P('Bitte geben Sie eine Komponenten-ID in der URL an, z.B. /plot?ci=12345'),
            html.A(href=config_home_url, children=[
                html.Button('Zurück zur Startseite', className='button')
            ])
        ])
    
    cutoff = (pd.Timestamp.now() - pd.Timedelta(hours=config_stats_delta_hours)).tz_localize(get_localzone())
    ci_data = get_availability_data_of_ci(config_file_name, ci)
    ci_data = ci_data[ci_data['times']>=cutoff]
    number_of_values = len(ci_data['values'])
    mean_availability = np.mean(ci_data['values'].values)
    first_timestamp = ci_data['times'].iloc[0].strftime('%d.%m.%Y %H:%M:%S Uhr')
    last_timestamp = ci_data['times'].iloc[-1].strftime('%d.%m.%Y %H:%M:%S Uhr')
    ci_data = ci_data.rename(columns={
        'times': 'Zeit',
        'values': 'Verfügbarkeit'
    })
    custom_colors = ['red' if v == 0 else 'green' for v in ci_data['Verfügbarkeit']]
    fig = px.scatter(
        ci_data,
        x = 'Zeit',
        y = 'Verfügbarkeit',
    )
    fig.update_traces(marker=dict(color=custom_colors))
    fig.update_yaxes(tickvals=[0, 1], ticktext=['0', '1'])
    fig.update_layout(yaxis=dict(range=[-0.1, 1.1]))
    ci_info = get_data_of_ci(config_file_name, ci)
    layout = [
        html.H2('Verfügbarkeit der Komponente ' + str(ci)),
        html.H3(ci_info['product'].iloc[0] + ', ' + ci_info['name'].iloc[0] + ', ' + ci_info['organization'].iloc[0]),
        html.A(href=config_home_url, children = [
            html.Button('Zurück', className = 'button')
        ]),
        html.Div(id = 'statistics', className = 'box', children = [
            html.H3('Statistik'),
            html.Ul([
                html.Li('Anzahl der Werte: ' + str(number_of_values)),
                html.Li('Erster Wert: ' + str(first_timestamp)),
                html.Li('Letzter Wert: ' + str(last_timestamp)),
                html.Li('Verfügbarkeit in diesem Zeitraum: ' + str(mean_availability * 100) + ' %')
            ])
        ]),
        dcc.Graph(figure=fig)
    ]
    return layout

layout = serve_layout