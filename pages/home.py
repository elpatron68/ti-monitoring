import dash
from dash import html
from mylibrary import *
from myconfig import *
import yaml
import os
import functools
import time

# Configuration cache for home page
_home_config_cache = {}
_home_config_cache_timestamp = 0
_home_config_cache_ttl = 300  # 5 seconds cache TTL

def load_config():
    """Load configuration from YAML file with caching"""
    global _home_config_cache, _home_config_cache_timestamp
    
    current_time = time.time()
    if (not _home_config_cache or 
        current_time - _home_config_cache_timestamp > _home_config_cache_ttl):
        
        config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                _home_config_cache = yaml.safe_load(f) or {}
            _home_config_cache_timestamp = current_time
        except (FileNotFoundError, Exception):
            _home_config_cache = {}
            _home_config_cache_timestamp = current_time
    
    return _home_config_cache

def load_core_config():
    """Load core configuration from cached config"""
    config = load_config()
    return config.get('core', {})

dash.register_page(__name__, path='/')

@functools.lru_cache(maxsize=32)
def create_accordion_element(group_name, group_data):
    """Create accordion element with caching for repeated groups"""
    return html.Div(className='accordion-element', children = [
        html.Div(
            className='accordion-element-title',
            children = [
                html.Span(
                    className='availability-icon ' + (
                        'available' if sum(group_data['current_availability']) == len(group_data)
                        else 'unavailable' if sum(group_data['current_availability']) == 0
                        else 'impaired'
                    ),
                ),
                html.Span(
                    className = 'group-name',
                    children = group_name + ' (' + str(sum(group_data['current_availability'] == 1)) + '/' + str(len(group_data)) + ')'
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
                ]) for _, row in group_data.iterrows()
            ])
        ])
    ])

def serve_layout():
    # Load core configurations (now cached)
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
    
    # Optimize DataFrame operations
    grouped = cis.groupby('product')
    
    # Create accordion elements efficiently
    accordion_elements = []
    for group_name, group_data in grouped:
        accordion_elements.append(create_accordion_element(group_name, group_data))
    
    layout = html.Div([
        html.P('Hier finden Sie eine nach Produkten gruppierte Übersicht sämtlicher TI-Komponenten. Neue Daten werden alle 5 Minuten bereitgestellt. Laden Sie die Seite neu, um die Ansicht zu aktualisieren.'),
        html.Div(className='accordion', children=accordion_elements)
    ])
    
    return layout

layout = serve_layout