import dash
from dash import Dash, html, dcc
from mylibrary import *
from myconfig import *

app = Dash(__name__, use_pages=True, title='TI-Monitoring')
server = app.server

# Add external CSS for Material Icons
app.config.external_stylesheets = [
    'https://fonts.googleapis.com/icon?family=Material+Icons'
]

def serve_layout():
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
                html.Span('Die Bereitstellung der abgebildeten Informationen erfolgt ohne Gewähr. Als Grundlage dienen Daten der gematik GmbH, die sich über eine öffentlich erreichbare Schnittstelle abrufen lassen. Weitere Informationen dazu hier: '),
                html.A('https://github.com/gematik/api-tilage', href='https://github.com/gematik/api-tilage', target='_blank'),
                html.Span('.')
            ]),
		]),
		html.Div(id = 'footer', children = [
            html.Div([html.A('Home', href='https://lukas-schmidt-russnak.de', target='_blank')]),
            html.Div([html.A('Dokumentation', href='https://github.com/lsr-dev/ti-monitoring', target='_blank')]),
            html.Div([html.A('Datenschutz', href='https://lukas-schmidt-russnak.de/datenschutz/', target='_blank')]),
            html.Div([html.A('Impressum', href='https://lukas-schmidt-russnak.de/impressum/', target='_blank')]),
            html.Div('© Lukas Schmidt-Russnak')
        ])
    ])
    return layout

app.layout = serve_layout

if __name__ == '__main__':
    app.run(debug=False)