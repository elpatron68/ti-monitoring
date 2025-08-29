import dash
from dash import html
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

dash.register_page(__name__, path='/')

def serve_layout():
    # Load core configurations
    core_config = load_core_config()
    
    # Get file_name from YAML as primary source, fallback to myconfig.py
    config_file_name = core_config.get('file_name') or file_name
    config_url = core_config.get('url')
    
    # Check if data file exists and initialize if needed
    if not os.path.exists(config_file_name):
        try:
            # Create data directory if it doesn't exist
            os.makedirs(os.path.dirname(config_file_name), exist_ok=True)
            # Initialize empty data file
            initialize_data_file(config_file_name)
            print(f"Initialized data file: {config_file_name}")
        except Exception as e:
            print(f"Error initializing data file: {e}")
    
    # Try to get data
    try:
        cis = get_data_of_all_cis(config_file_name)
    except Exception as e:
        print(f"Error reading data: {e}")
        cis = pd.DataFrame()  # Empty DataFrame
    
    # Check if DataFrame is empty
    if cis.empty:
        # Try to load data from API if URL is available
        if config_url:
            try:
                print(f"Loading data from API: {config_url}")
                update_file(config_file_name, config_url)
                # Try to read data again
                cis = get_data_of_all_cis(config_file_name)
                print(f"Loaded {len(cis)} records from API")
            except Exception as e:
                print(f"Error loading data from API: {e}")
        
        # If still empty, show message
        if cis.empty:
            layout = html.Div([
                html.P('Keine Daten verfügbar. Versuche Daten von der API zu laden...'),
                html.P('Falls das Problem weiterhin besteht, überprüfen Sie die API-Verbindung.'),
                html.P(f'API URL: {config_url or "Nicht konfiguriert"}'),
                html.P(f'Daten-Datei: {config_file_name}')
            ])
            return layout
    
    # Check if 'product' column exists
    if 'product' not in cis.columns:
        layout = html.Div([
            html.P('Daten sind verfügbar, aber die Spalte "product" fehlt. Möglicherweise ist die Datenstruktur fehlerhaft.'),
            html.P('Verfügbare Spalten: ' + ', '.join(cis.columns.tolist())),
            html.P(f'Anzahl Datensätze: {len(cis)}')
        ])
        return layout
    
    grouped = cis.groupby('product')
    products = []
    for index, row in cis.iterrows():
        product = row['product']
        if product not in products:
            products.append(product)
    layout = html.Div([
        html.P('Hier finden Sie eine nach Produkten gruppierte Übersicht sämtlicher TI-Komponenten. Neue Daten werden alle 5 Minuten bereitgestellt. Laden Sie die Seite neu, um die Ansicht zu aktualisieren.'),
        html.Div(className='accordion', children = [
            html.Div(className='accordion-element', children = [
                html.Div(
                    className='accordion-element-title',
                    children = [
                        html.Span(
                            className='availability-icon ' + (
                                'available' if sum(group['current_availability']) == len(group)
                                else 'unavailable' if sum(group['current_availability']) == 0
                                else 'impaired'
                            ),
                        ),
                        html.Span(
                            className = 'group-name',
                            children = group_name + ' (' + str(sum(group['current_availability'] == 1)) + '/' + str(len(group)) + ')'
                        ),
                        html.Span(className = 'expand-collapse-icon', children='+')
                    ]
                ),
                html.Div(className='accordion-element-content', children = [
                    html.Ul(children = [
                        html.Li([
                            html.Span(
                                className='availability-icon ' + (
                                    'available' if row['current_availability'] == 1 
                                    else 'unavailable'
                                )
                            ),
                            html.Div([
                                html.A(str(row['ci']), href='/plot?ci=' + str(row['ci'])),
                                ': ' + row['name'] + ', ' + row['organization'] + ', ' + pretty_timestamp(row['time'])
                            ])
                        ]) for _, row in group.iterrows()
                    ])
                ])
            ]) for group_name, group in grouped
        ])
    ])
    return layout

layout = serve_layout