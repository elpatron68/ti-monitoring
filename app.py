from dash import Dash, html, dcc
from mylibrary import *
import yaml
import os
import functools
import time

app = Dash(__name__, use_pages=True, title='TI-Monitoring')
server = app.server

# Add local CSS for Material Icons

# Configuration cache
_config_cache = {}
_config_cache_timestamp = 0
_config_cache_ttl = 300  # 5 seconds cache TTL

# Layout cache
_layout_cache = {}
_layout_cache_timestamp = 0
_layout_cache_ttl = 60  # 1 minute cache TTL

def load_config():
    """Load configuration from YAML file with caching"""
    global _config_cache, _config_cache_timestamp
    
    current_time = time.time()
    if (not _config_cache or 
        current_time - _config_cache_timestamp > _config_cache_ttl):
        
        config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                _config_cache = yaml.safe_load(f) or {}
            _config_cache_timestamp = current_time
        except (FileNotFoundError, Exception):
            _config_cache = {}
            _config_cache_timestamp = current_time
    
    return _config_cache

def load_footer_config():
    """Load footer configuration from cached config"""
    config = load_config()
    return config.get('footer', {})

def load_core_config():
    """Load core configuration from cached config"""
    config = load_config()
    return config.get('core', {})

def load_header_config():
    """Load header configuration from cached config"""
    core_config = load_core_config()
    return core_config.get('header', {})

def create_footer_element(config_item):
    """Create a footer element based on configuration"""
    if not config_item.get('enabled', True):
        return None
    
    if 'text' in config_item:  # Copyright element
        return html.Div(config_item['text'])
    
    # Link element
    link_attrs = {'href': config_item['link']}
    if config_item.get('new_tab', False):
        link_attrs['target'] = '_blank'
    
    return html.Div([html.A(config_item['label'], **link_attrs)])

def build_footer_elements(footer_config):
    """Build footer elements efficiently"""
    footer_elements = []
    
    # Pre-define footer sections for faster iteration
    footer_sections = ['home', 'documentation', 'privacy', 'imprint', 'copyright']
    
    for section in footer_sections:
        if section in footer_config:
            element = create_footer_element(footer_config[section])
            if element:
                footer_elements.append(element)
    
    return footer_elements

@functools.lru_cache(maxsize=1)
def get_cached_layout(config_hash):
    """Get cached layout based on configuration hash"""
    return None  # Will be implemented below

def serve_layout():
    # Check layout cache first
    global _layout_cache, _layout_cache_timestamp
    
    current_time = time.time()
    if (not _layout_cache or 
        current_time - _layout_cache_timestamp > _layout_cache_ttl):
        
        # Load configurations (now cached)
        footer_config = load_footer_config()
        core_config = load_core_config()
        header_config = load_header_config()
        
        # Get home_url from config.yaml
        app_home_url = core_config.get('home_url', 'https://ti-monitoring.lukas-schmidt-russnak.de')
        
        # Get header configurations
        header_title = header_config.get('title', 'TI-Monitoring')
        logo_config = header_config.get('logo', {})
        logo_path = logo_config.get('path', 'assets/logo.svg')
        logo_alt = logo_config.get('alt', 'Logo')
        logo_height = logo_config.get('height', 50)
        logo_width = logo_config.get('width', 50)
        
        # Build footer elements efficiently
        footer_elements = build_footer_elements(footer_config)
        
        # Get home page content
        try:
            from pages.home import serve_layout as home_layout
            home_content = home_layout()
        except Exception as e:
            home_content = html.Div([
                html.P('Fehler beim Laden der Home-Seite.'),
                html.P(f'Fehler: {str(e)}')
            ])
        
        # Create layout
        _layout_cache = html.Div([
            html.Header(children = [
                html.Div(id='logo-wrapper', children = [
                    html.A(href=app_home_url, children = [
                        html.Img(id='logo', src=logo_path, alt=logo_alt, height=logo_height, width=logo_width)
                    ])
                ]),
                html.H1(children=header_title),
                # Add navigation links with Material icons
                html.Nav(children=[
                    html.A(html.I(className='material-icons', children='home'), href='/', className='nav-icon'),
                    html.A(html.I(className='material-icons', children='settings'), href='/notifications', className='nav-icon')
                ], className='navigation')
            ]),
            html.Main(children = [
                html.Div(id='page-container', children=[
                    dcc.Loading(
                        id = 'spinner',
                        overlay_style = {"visibility":"visible", "filter": "blur(2px)"},
                        type = "circle",
                        children = [home_content]
                    )
                ]),
                html.Div(className = 'box', children = [
                    html.H3('Disclaimer'),
                    html.Span('Die Bereitstellung der abgebildeten Informationen erfolgt ohne Gewähr. Als Grundlage dienen Daten der gematik GmbH, die sich über eine öffentlich erreichbare Schnittstelle abrufen lassen. Weitere Informationen dazu hier: '),
                    html.A('https://github.com/gematik/api-tilage', href='https://github.com/gematik/api-tilage', target='_blank'),
                    html.Span('.')
                ]),
            ]),
            html.Div(id = 'footer', children = footer_elements)
        ])
        
        _layout_cache_timestamp = current_time
    
    return _layout_cache

app.layout = serve_layout

if __name__ == '__main__':
    app.run(debug=False)