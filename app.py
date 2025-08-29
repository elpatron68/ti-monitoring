import dash
from dash import Dash, html, dcc
from mylibrary import *
from myconfig import *
import yaml
import os

app = Dash(__name__, use_pages=True, title='TI-Monitoring')
server = app.server

# Add external CSS for Material Icons
app.config.external_stylesheets = [
    'https://fonts.googleapis.com/icon?family=Material+Icons'
]

def load_footer_config():
    """Load footer configuration from YAML file"""
    config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        return config.get('footer', {})
    except FileNotFoundError:
        # Return default configuration if file doesn't exist
        return {
            'home': {'label': 'Home', 'link': 'https://lukas-schmidt-russnak.de', 'enabled': True, 'new_tab': True},
            'documentation': {'label': 'Dokumentation', 'link': 'https://github.com/lsr-dev/ti-monitoring', 'enabled': True, 'new_tab': True},
            'privacy': {'label': 'Datenschutz', 'link': 'https://lukas-schmidt-russnak.de/datenschutz/', 'enabled': True, 'new_tab': True},
            'imprint': {'label': 'Impressum', 'link': 'https://lukas-schmidt-russnak.de/impressum/', 'enabled': True, 'new_tab': True},
            'copyright': {'text': '© Lukas Schmidt-Russnak', 'enabled': True}
        }
    except Exception:
        # Return default configuration if there's any other error
        return {
            'home': {'label': 'Home', 'link': 'https://lukas-schmidt-russnak.de', 'enabled': True, 'new_tab': True},
            'documentation': {'label': 'Dokumentation', 'link': 'https://github.com/lsr-dev/ti-monitoring', 'enabled': True, 'new_tab': True},
            'privacy': {'label': 'Datenschutz', 'link': 'https://lukas-schmidt-russnak.de/datenschutz/', 'enabled': True, 'new_tab': True},
            'imprint': {'label': 'Impressum', 'link': 'https://lukas-schmidt-russnak.de/impressum/', 'enabled': True, 'new_tab': True},
            'copyright': {'text': '© Lukas Schmidt-Russnak', 'enabled': True}
        }

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

def serve_layout():
    # Load footer configuration
    footer_config = load_footer_config()
    
    # Build footer elements
    footer_elements = []
    
    # Add home link if enabled
    if 'home' in footer_config:
        element = create_footer_element(footer_config['home'])
        if element:
            footer_elements.append(element)
    
    # Add documentation link if enabled
    if 'documentation' in footer_config:
        element = create_footer_element(footer_config['documentation'])
        if element:
            footer_elements.append(element)
    
    # Add privacy link if enabled
    if 'privacy' in footer_config:
        element = create_footer_element(footer_config['privacy'])
        if element:
            footer_elements.append(element)
    
    # Add imprint link if enabled
    if 'imprint' in footer_config:
        element = create_footer_element(footer_config['imprint'])
        if element:
            footer_elements.append(element)
    
    # Add copyright if enabled
    if 'copyright' in footer_config:
        element = create_footer_element(footer_config['copyright'])
        if element:
            footer_elements.append(element)
    
    layout = html.Div([
        html.Header(children = [
            html.Div(id='logo-wrapper', children = [
                html.A(href=home_url, children = [
                    html.Img(id='logo', src='assets/logo.svg')
                ])
            ]),
            html.H1(children='TI-Monitoring'),
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
                html.Span('Die Bereitstellung der abgebildeten Informationen erfolgt ohne Gewähr. Als Grundlage dieren Daten der gematik GmbH, die sich über eine öffentlich erreichbare Schnittstelle abrufen lassen. Weitere Informationen dazu hier: '),
                html.A('https://github.com/gematik/api-tilage', href='https://github.com/gematik/api-tilage', target='_blank'),
                html.Span('.')
            ]),
		]),
		html.Div(id = 'footer', children = footer_elements)
    ])
    return layout

app.layout = serve_layout

if __name__ == '__main__':
    app.run(debug=False)