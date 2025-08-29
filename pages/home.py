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
    
    cis = get_data_of_all_cis(config_file_name)
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