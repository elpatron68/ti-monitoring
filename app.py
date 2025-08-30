import dash
from dash import Dash, html, dcc
from mylibrary import *
import yaml
import os
import functools
import time
from flask import jsonify
import psutil
import gc

app = Dash(__name__, use_pages=True, title='TI-Monitoring')
server = app.server

# Add local CSS for Material Icons

# Configuration cache with size limit
_config_cache = {}
_config_cache_timestamp = 0
_config_cache_ttl = 300  # 5 seconds cache TTL
_config_cache_max_size = 10  # Limit cache size

# Layout cache with size limit
_layout_cache = {}
_layout_cache_timestamp = 0
_layout_cache_ttl = 60  # 1 minute cache TTL
_layout_cache_max_size = 5  # Limit cache size

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
            
            # Limit cache size
            if len(_config_cache) > _config_cache_max_size:
                # Keep only the most recent entries
                keys = list(_config_cache.keys())[:_config_cache_max_size]
                _config_cache = {k: _config_cache[k] for k in keys}
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
                        children = [dash.page_container]
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
        
        # Force garbage collection periodically
        if int(current_time) % 300 == 0:  # Every 5 minutes
            gc.collect()
    
    return _layout_cache

# This is the correct way to set the layout - it should be the function itself, not the result of calling it
app.layout = serve_layout

# Health check endpoint
@server.route('/health')
def health_check():
    """Health check endpoint for monitoring the application status"""
    try:
        # Check configuration loading
        config_status = "healthy"
        config_error = None
        try:
            config = load_config()
            if not config:
                config_status = "warning"
                config_error = "Empty configuration"
        except Exception as e:
            config_status = "unhealthy"
            config_error = str(e)
        
        # Check layout generation
        layout_status = "healthy"
        layout_error = None
        try:
            layout = serve_layout()
            if not layout:
                layout_status = "warning"
                layout_error = "Empty layout"
        except Exception as e:
            layout_status = "unhealthy"
            layout_error = str(e)
        
        # System metrics
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        
        # Overall health status
        overall_status = "healthy"
        if config_status == "unhealthy" or layout_status == "unhealthy":
            overall_status = "unhealthy"
        elif config_status == "warning" or layout_status == "warning":
            overall_status = "warning"
        
        health_data = {
            "status": overall_status,
            "timestamp": time.time(),
            "uptime": time.time() - _config_cache_timestamp if _config_cache_timestamp > 0 else 0,
            "components": {
                "configuration": {
                    "status": config_status,
                    "error": config_error,
                    "cache_age": time.time() - _config_cache_timestamp if _config_cache_timestamp > 0 else None,
                    "cache_ttl": _config_cache_ttl
                },
                "layout": {
                    "status": layout_status,
                    "error": layout_error,
                    "cache_age": time.time() - _layout_cache_timestamp if _layout_cache_timestamp > 0 else None,
                    "cache_ttl": _layout_cache_ttl
                }
            },
            "system": {
                "cpu_percent": cpu_percent,
                "memory_percent": memory.percent,
                "memory_available": memory.available,
                "memory_total": memory.total
            }
        }
        
        status_code = 200 if overall_status == "healthy" else (503 if overall_status == "unhealthy" else 200)
        return jsonify(health_data), status_code
        
    except Exception as e:
        error_data = {
            "status": "unhealthy",
            "timestamp": time.time(),
            "error": f"Health check failed: {str(e)}"
        }
        return jsonify(error_data), 503

if __name__ == '__main__':
    app.run(debug=False)