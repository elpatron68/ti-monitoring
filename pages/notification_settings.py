import dash
from dash import html, dcc, Input, Output, State, callback, no_update, callback_context, ALL
import json
from mylibrary import *
import yaml
import os
import apprise
import secrets
from datetime import datetime

# Modern button styles (unchanged)
MODERN_BUTTON_STYLES = {
    'primary': {
        'backgroundColor': '#007bff',
        'color': 'white',
        'border': 'none',
        'padding': '10px 20px',
        'borderRadius': '8px',
        'fontSize': '14px',
        'fontWeight': '500',
        'cursor': 'pointer',
        'transition': 'all 0.3s ease',
        'boxShadow': '0 2px 4px rgba(0, 123, 255, 0.2)',
        'margin': '5px'
    },
    'secondary': {
        'backgroundColor': '#6c757d',
        'color': 'white',
        'border': 'none',
        'padding': '10px 20px',
        'borderRadius': '8px',
        'fontSize': '14px',
        'fontWeight': '500',
        'cursor': 'pointer',
        'transition': 'all 0.3s ease',
        'boxShadow': '0 2px 4px rgba(108, 117, 125, 0.2)',
        'margin': '5px'
    },
    'success': {
        'backgroundColor': '#28a745',
        'color': 'white',
        'border': 'none',
        'padding': '10px 20px',
        'borderRadius': '8px',
        'fontSize': '14px',
        'fontWeight': '500',
        'cursor': 'pointer',
        'transition': 'all 0.3s ease',
        'boxShadow': '0 2px 4px rgba(40, 167, 69, 0.2)',
        'margin': '5px'
    },
    'danger': {
        'backgroundColor': '#dc3545',
        'color': 'white',
        'border': 'none',
        'padding': '10px 20px',
        'borderRadius': '8px',
        'fontSize': '14px',
        'fontWeight': '500',
        'cursor': 'pointer',
        'transition': 'all 0.3s ease',
        'boxShadow': '0 2px 4px rgba(220, 53, 69, 0.2)',
        'margin': '5px'
    },
    'warning': {
        'backgroundColor': '#ffc107',
        'color': '#212529',
        'border': 'none',
        'padding': '10px 20px',
        'borderRadius': '8px',
        'fontSize': '14px',
        'fontWeight': '500',
        'cursor': 'pointer',
        'transition': 'all 0.3s ease',
        'boxShadow': '0 2px 4px rgba(255, 193, 7, 0.2)',
        'margin': '5px'
    }
}

def get_button_style(button_type='primary'):
    return MODERN_BUTTON_STYLES[button_type].copy()

def get_error_style(visible=True):
    base_style = {
        'color': '#e74c3c',
        'marginBottom': '15px',
        'fontWeight': '500',
        'padding': '10px',
        'backgroundColor': '#fdf2f2',
        'borderRadius': '6px',
        'border': '1px solid #fecaca'
    }
    base_style['display'] = 'block' if visible else 'none'
    return base_style

def load_config():
    """Load configuration from YAML file"""
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        return config
    except (FileNotFoundError, Exception):
        return {}

def load_core_config():
    """Load core configuration from YAML file"""
    config = load_config()
    return config.get('core', {})

def load_apprise_services():
    """Load Apprise services from JSON file"""
    services_file = os.path.join(os.path.dirname(__file__), '..', 'apprise_services.json')
    try:
        with open(services_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('services', {})
    except (FileNotFoundError, Exception) as e:
        print(f"Error loading apprise services: {e}")
        return {}

def serve_layout():
    """Clean, refactored layout with separate stores"""
    return html.Div([
        html.H2('Benachrichtigungseinstellungen', style={
            'color': '#2c3e50',
            'fontWeight': '600',
            'marginBottom': '30px',
            'borderBottom': '2px solid #3498db',
            'paddingBottom': '10px'
        }),

        # Info-Box über Benachrichtigungsfunktionen
        html.Div([
            html.Div([
                html.H4('ℹ️ Über diese Funktion', style={
                    'color': '#2c3e50',
                    'marginBottom': '15px',
                    'fontSize': '18px'
                }),
                html.P([
                    'Du hast hier die Möglichkeit, dich bei Ausfällen und Wiederverfügbarkeit von Kompontenten der Telematik Infrastruktur informieren zu lassen. ',
                    'Dabei stehen dir von AWS bis Zulip über 100 verschiedene Wege zur Verfügung, unter anderem natürlich auch E-Mail oder SMS, Teams, Whatsapp, Slack, Telegram.'
                ], style={'marginBottom': '15px', 'lineHeight': '1.6'}),
                html.P([
                    'Um deine persönlichen Benachrichtigungen zu verwalten, musst du dir hier einen Account per One-Time-Passwort anlegen. ',
                    'Anschließend kannst du Benachrichtigungen für die Telematik-Komponenten ("Configuration-Items"), die dich interessieren, konfigurieren.'
                ], style={'marginBottom': '15px', 'lineHeight': '1.6'}),
                html.P([
                    html.Strong([
                        'Im ti-stats.net ',
                        html.A('ti-stats.net Wiki', href='https://github.com/elpatron68/ti-monitoring/wiki/Benachrichtigungsoptionen', target='_blank'),
                        ' findest du eine einfache Schritt-für -Schritt Anleitung zur Einrichtung einer Benachrichtigung.'
                    ])
                ], style={'marginBottom': '15px', 'lineHeight': '1.6'}),
                html.P([
                    'Jede verschickte Benachrichtigung enthält zwei Links, mit denen sowohl der jeweilige Benachrichtigungstyp (z.B. "Slack") als auch alle Benachrichtigungen deines Accounts wieder abgeschaltet werden können (unsubscribe).'
                ], style={'marginBottom': '15px', 'lineHeight': '1.6'}),
                html.P([
                    'Deine E-Mail-Adresse und deine Apprise URLs werden selbstverständlich verschlüsselt (Hash + Salt) gespeichert. Beachte jedoch, dass insbesondere Apprise URLs sehr schützenswürdige Daten wie z.B. API-Keys enthalten können, die nicht in die Hände Unbefugter gelangen sollten. Bedenke das, bevor du ein Benachrichtigungsprofil anlegst.'
                ], style={'marginBottom': '15px', 'lineHeight': '1.6'}),
                html.P([
                    'Alternativ kannst du die TI-Stats App auf deinem eigenen Server installieren oder dem Mastodon-Account ',
                    html.A('@tistatus@mastodon.ti-stats.net', href='https://mastodon.ti-stats.net/@tistatus', target='_blank'),
                    ' folgen, der Statusänderungen aller CIs zeitnah meldet.'
                ], style={'marginBottom': '0', 'lineHeight': '1.6'})
            ], style={'padding': '20px'})
        ], style={
            'backgroundColor': '#e8f4fd',
            'border': '1px solid #3498db',
            'borderRadius': '12px',
            'marginBottom': '30px',
            'boxShadow': '0 2px 4px rgba(52, 152, 219, 0.1)'
        }, className='info-box'),

        # === STORES (Single source of truth) ===
        dcc.Store(id='auth-state-store', data={'authenticated': False}),
        dcc.Store(id='otp-state-store', data={'step': 'login', 'email': ''}),
        dcc.Store(id='ui-state-store', data={'show_login': True, 'show_otp': False, 'show_settings': False}),
        dcc.Store(id='available-cis-data', data=None),
        dcc.Store(id='selected-cis-data', data=[]),
        dcc.Store(id='profile-selected-cis', data=[]),
        dcc.Store(id='current-profile-id', data=None),
        dcc.Store(id='ci-filter-text', data=''),
        dcc.Store(id='delete-profile-status', data=''),
        dcc.Store(id='redirect-trigger', data=None),
        dcc.Store(id='apprise-services-data', data=None),
        # Trigger zum einmaligen Laden der CI-Liste nach Seitenaufruf
        dcc.Interval(id='ci-load-once', interval=200, n_intervals=0, max_intervals=1),

        # === UI CONTAINERS (Controlled by stores) ===
        # Login container
        html.Div(id='otp-login-container', children=[
            html.H3('OTP-Anmeldung erforderlich'),
            html.P('Bitte gib deine E-Mail-Adresse ein, um einen OTP-Code zu erhalten.'),
            dcc.Input(id='email-input', type='email', placeholder='E-Mail-Adresse eingeben', style={'width': '100%', 'marginBottom': '15px', 'padding': '12px', 'borderRadius': '8px'}),
            html.Button('OTP anfordern', id='request-otp-button', n_clicks=0, style=get_button_style('primary')),
            html.Div(id='otp-request-error', style={'color': '#e74c3c', 'marginTop': '15px'})
        ], style={'display': 'block', 'padding': '20px', 'backgroundColor': 'white', 'borderRadius': '12px', 'boxShadow': '0 4px 6px rgba(0, 0, 0, 0.1)', 'marginBottom': '20px'}),

        # OTP code container
        html.Div(id='otp-code-container', children=[
            html.H3('OTP-Code eingeben'),
            html.P(id='otp-instructions', children='Bitte gib den 6-stelligen Code ein.'),
            dcc.Input(id='otp-code-input', type='text', placeholder='6-stelliger Code', style={'width': '100%', 'marginBottom': '15px', 'padding': '12px', 'borderRadius': '8px'}),
            html.Button('Anmelden', id='verify-otp-button', n_clicks=0, style=get_button_style('primary')),
            html.Button('Neuen Code anfordern', id='resend-otp-button', n_clicks=0, style=get_button_style('secondary')),
            html.Div(id='otp-verify-error', style={'color': '#e74c3c', 'marginTop': '15px'})
        ], style={'display': 'none', 'padding': '20px', 'backgroundColor': 'white', 'borderRadius': '12px', 'boxShadow': '0 4px 6px rgba(0, 0, 0, 0.1)', 'marginBottom': '20px'}),

        # Settings container
        html.Div(id='settings-container', children=[
            html.Div(id='user-info', children='', style={'marginBottom': '20px', 'padding': '15px', 'borderRadius': '8px'}, className='user-info-card'),
            html.P('Verwalte deine Benachrichtigungsprofile unten.'),
            html.Div(id='profiles-container'),
            html.Button('Neues Profil hinzufügen', id='add-profile-button', n_clicks=0, style=get_button_style('success')),

            # Profile form (hidden by default)
            html.Div(id='profile-form-container', children=[
                html.H3('Neues Profil erstellen'),
                dcc.Input(id='profile-name-input', placeholder='Profilname', style={'width': '100%', 'marginBottom': '15px', 'padding': '12px', 'borderRadius': '8px', 'boxSizing': 'border-box'}),
                html.Div([
                    html.Label('Benachrichtigungstyp:'),
                    dcc.RadioItems(id='notification-type-radio', options=[
                        {'label': 'Whitelist', 'value': 'whitelist'},
                        {'label': 'Blacklist', 'value': 'blacklist'}
                    ], value='whitelist', inline=True)
                ], style={'marginBottom': '15px'}),
                html.Div([
                    html.Label('Benachrichtigungsmethode:'),
                    dcc.RadioItems(id='notification-method-radio', options=[
                        {'label': 'Apprise (Erweitert)', 'value': 'apprise'},
                        {'label': 'E-Mail (Einfach)', 'value': 'email'}
                    ], value='apprise', inline=True)
                ], style={'marginBottom': '15px'}),

                # CI Selection Section
                html.Div([
                    html.Label('Konfigurationsobjekte:'),
                    html.Div([
                        dcc.Input(id='ci-filter-input', type='text', placeholder='CIs filtern (z.B. "CI-0000" oder "gematik")',
                                style={'flex': '1', 'padding': '8px 12px', 'borderRadius': '6px', 'marginRight': '10px', 'boxSizing': 'border-box'}),
                        html.Button('Alle auswählen', id='select-all-cis-button', n_clicks=0, style=get_button_style('secondary')),
                        html.Button('Alle abwählen', id='deselect-all-cis-button', n_clicks=0, style=get_button_style('secondary'))
                    ], style={'display': 'flex', 'gap': '10px', 'marginBottom': '10px'}),
                    html.Div(id='ci-filter-info', style={'fontSize': '12px', 'color': '#7f8c8d', 'marginBottom': '8px'}),
                    html.Div(id='ci-load-status', style={'fontSize': '12px', 'color': '#e74c3c', 'marginBottom': '8px'}),
                    html.Div(id='ci-checkboxes-container', style={
                        'maxHeight': '200px', 'overflowY': 'auto',
                        'borderRadius': '8px', 'padding': '15px'
                    }, className='ci-checkboxes-container')
                ], style={'marginBottom': '15px'}),

                # Apprise Service Selection
                html.Div([
                    html.Label('Apprise Service auswählen:', style={'marginBottom': '8px', 'fontWeight': '500'}),
                    dcc.Dropdown(
                        id='apprise-service-dropdown',
                        placeholder='Service auswählen...',
                        style={'marginBottom': '10px'}
                    ),
                    html.Div(id='apprise-wiki-link', style={'marginBottom': '10px'}, className='apprise-wiki-link'),
                    html.Div([
                        dcc.Input(
                            id='apprise-url-input',
                            type='text',
                            placeholder='Apprise URL hier eingeben oder bearbeiten...',
                            style={'flex': '1', 'padding': '8px 12px', 'borderRadius': '6px', 'marginRight': '10px', 'fontFamily': 'monospace', 'boxSizing': 'border-box'},
                            className='apprise-url-input'
                        ),
                        html.Button('Zur Liste hinzufügen', id='add-url-button', n_clicks=0, style=get_button_style('success'))
                    ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '15px'})
                ], style={'marginBottom': '15px', 'padding': '15px', 'borderRadius': '8px'}, className='apprise-service-selection'),

                dcc.Textarea(id='apprise-urls-textarea', placeholder='Apprise URLs (eine pro Zeile)',
                           style={'width': '100%', 'height': '100px', 'marginBottom': '15px', 'padding': '12px', 'borderRadius': '8px', 'fontFamily': 'monospace', 'boxSizing': 'border-box'}),
                html.Div(id='form-error', style={'color': '#e74c3c', 'marginBottom': '15px'}),
                html.Div([
                    html.Button('Profil speichern', id='save-profile-button', n_clicks=0, style=get_button_style('success')),
                    html.Button('Abbrechen', id='cancel-profile-button', n_clicks=0, style=get_button_style('secondary'))
                ], style={'display': 'flex', 'gap': '10px'})
            ], style={'display': 'none', 'marginTop': '20px', 'padding': '20px', 'backgroundColor': 'white', 'borderRadius': '12px', 'border': '1px solid #e9ecef'}),

            # Apprise test section
            html.Hr(style={'margin': '30px 0'}),
            html.H3('Apprise-Benachrichtigung testen'),
            html.P('Gib eine Apprise-URL ein, um zu testen, ob dein Benachrichtigungssystem funktioniert.'),
            dcc.Input(id='test-apprise-url', type='text', placeholder='z.B. mmost://username:password@mattermost.example.org/channel',
                     style={'width': '100%', 'marginBottom': '15px', 'padding': '12px', 'borderRadius': '8px', 'fontFamily': 'monospace'}),
            html.Button('Benachrichtigung testen', id='test-notification-button', n_clicks=0, style=get_button_style('warning')),
            html.Div(id='test-result', style={'marginTop': '15px'})
        ], style={'display': 'none'})
    ], style={'maxWidth': '900px', 'margin': '0 auto', 'padding': '20px'})

# === SEPARATED CALLBACKS (One responsibility each) ===

# 0. Load Apprise Services
@callback(
    Output('apprise-services-data', 'data'),
    [Input('ci-load-once', 'n_intervals')],
    prevent_initial_call=False
)
def load_apprise_services_callback(_n):
    """Load Apprise services data"""
    return load_apprise_services()

# 0b. Populate Apprise Service Dropdown
@callback(
    Output('apprise-service-dropdown', 'options'),
    [Input('apprise-services-data', 'data')],
    prevent_initial_call=False
)
def populate_apprise_dropdown(services_data):
    """Populate the Apprise service dropdown"""
    if not services_data:
        return []

    # Group services by category
    categories = {}
    for service_id, service_info in services_data.items():
        category = service_info.get('category', 'Other')
        if category not in categories:
            categories[category] = []

        categories[category].append({
            'label': f"{service_info.get('name', service_id)} - {service_info.get('description', '')}",
            'value': service_id
        })

    # Create options with categories
    options = []
    for category in sorted(categories.keys()):
        # Add category header
        options.append({
            'label': f"📁 {category}",
            'value': f"category_{category}",
            'disabled': True
        })

        # Add services in this category
        for service in sorted(categories[category], key=lambda x: x['label']):
            options.append(service)

    return options

# 0c. Handle Apprise Service Selection
@callback(
    [Output('apprise-url-input', 'value'),
     Output('apprise-wiki-link', 'children')],
    [Input('apprise-service-dropdown', 'value')],
    [State('apprise-services-data', 'data')],
    prevent_initial_call=True
)
def handle_service_selection(selected_service, services_data):
    """Handle service selection and populate URL input and wiki link"""
    if not selected_service or not services_data:
        return '', ''

    # Skip category headers
    if selected_service.startswith('category_'):
        return '', ''

    service_info = services_data.get(selected_service)
    if service_info:
        example_url = service_info.get('example', '')
        wiki_url = service_info.get('wiki_url', '')

        # Create wiki link if available
        wiki_link = ''
        if wiki_url:
            wiki_link = html.A(
                '📖 Apprise Wiki - Detaillierte Anleitung',
                href=wiki_url,
                target='_blank',
                style={
                    'color': '#60a5fa',
                    'textDecoration': 'none',
                    'fontSize': '12px',
                    'fontWeight': '500'
                }
            )

        return example_url, wiki_link

    return '', ''

# 0d. Add URL to Textarea (integrated with existing callback)
@callback(
    Output('apprise-urls-textarea', 'value'),
    [Input('add-url-button', 'n_clicks'),
     Input({'type': 'edit-profile', 'profile_id': ALL}, 'n_clicks'),
     Input('add-profile-button', 'n_clicks')],
    [State('apprise-url-input', 'value'),
     State('apprise-urls-textarea', 'value'),
     State('auth-status', 'data')],
    prevent_initial_call=True
)
def handle_url_management(n_clicks, edit_clicks_list, add_clicks, url_input, current_textarea, auth_data):
    """Handle URL management (add new URLs and edit profile URLs)"""
    ctx = callback_context
    if not ctx.triggered:
        return no_update

    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

    # Handle add URL button
    if trigger_id == 'add-url-button' and n_clicks:
        if not url_input or not url_input.strip():
            return no_update

        # Get current URLs
        current_urls = []
        if current_textarea:
            current_urls = [url.strip() for url in current_textarea.split('\n') if url.strip()]

        # Add new URL if not already present
        new_url = url_input.strip()
        if new_url not in current_urls:
            current_urls.append(new_url)

        # Return updated textarea content
        return '\n'.join(current_urls)

    # Handle profile edit/add
    if trigger_id.startswith('{') or trigger_id == 'add-profile-button':
        if trigger_id == 'add-profile-button':
            return ''  # Empty URLs for new profile

        # Handle edit profile - load URLs from database
        try:
            triggered_id = json.loads(trigger_id)
            if triggered_id.get('type') == 'edit-profile':
                profile_id = triggered_id.get('profile_id')
                if profile_id and auth_data and auth_data.get('authenticated'):
                    with get_db_conn() as conn, conn.cursor() as cur:
                        cur.execute(
                            """
                            SELECT apprise_urls, apprise_urls_salt, email_notifications
                            FROM notification_profiles
                            WHERE id = %s
                            """,
                            (int(profile_id),)
                        )
                        row = cur.fetchone()
                        if row:
                            apprise_urls, apprise_urls_salt, email_notifications = row
                            if not email_notifications and apprise_urls:
                                try:
                                    encryption_key = os.getenv('ENCRYPTION_KEY')
                                    if encryption_key:
                                        encryption_key = encryption_key.encode()
                                    else:
                                        encryption_key = generate_encryption_key()
                                    decrypted_urls = []
                                    salts = list(apprise_urls_salt or [])
                                    for idx, enc in enumerate(list(apprise_urls)):
                                        try:
                                            salt = salts[idx] if salts and len(salts) > idx else None
                                            dec = decrypt_data(enc, salt, encryption_key) if salt else None
                                            if dec:
                                                decrypted_urls.append(dec)
                                        except Exception:
                                            continue
                                    return '\n'.join(decrypted_urls)
                                except Exception:
                                    pass
        except Exception:
            pass

        return no_update

    return no_update

# 1. UI State Management (based on auth store)
@callback(
    [Output('otp-login-container', 'style'),
     Output('otp-code-container', 'style'),
     Output('settings-container', 'style')],
    [Input('ui-state-store', 'data')]
)
def update_ui_visibility(ui_state):
    """Update UI visibility based on state store"""
    if not ui_state:
        return [{'display': 'block'}, {'display': 'none'}, {'display': 'none'}]

    login_style = {'display': 'block'} if ui_state.get('show_login') else {'display': 'none'}
    otp_style = {'display': 'block'} if ui_state.get('show_otp') else {'display': 'none'}
    settings_style = {'display': 'block'} if ui_state.get('show_settings') else {'display': 'none'}

    return [login_style, otp_style, settings_style]

# 2. OTP Request Handler
@callback(
    [Output('otp-state-store', 'data'),
     Output('otp-request-error', 'children')],
    [Input('request-otp-button', 'n_clicks')],
    [State('email-input', 'value'),
     State('otp-state-store', 'data'),
     State('ui-state-store', 'data')],
    prevent_initial_call=True
)
def handle_otp_request(n_clicks, email, otp_state, ui_state):
    """Handle OTP request (single responsibility)"""
    if not n_clicks or not email:
        return [no_update, no_update]

    try:
        # Validate email
        if '@' not in email or '.' not in email:
            return [no_update, 'Bitte gib eine gültige E-Mail-Adresse ein.']

        # Call API
        import requests
        response = requests.post('http://localhost:8050/api/auth/otp/request',
                               json={'email': email}, timeout=10)

        if response.status_code == 200:
            # Success - update OTP state (UI will be updated by separate callback)
            new_otp_state = {'step': 'verify', 'email': email}
            return [new_otp_state, '']
        else:
            error_msg = response.json().get('error', 'Unbekannter Fehler') if response.content else 'Unbekannter Fehler'
            return [no_update, f'Fehler: {error_msg}']

    except Exception as e:
        return [no_update, f'Fehler beim Senden: {str(e)}']

# 2b. Bridge: OTP/Auth state → UI state (OTP nach Request, Settings nach Verifikation)
@callback(
    Output('ui-state-store', 'data'),
    [Input('otp-state-store', 'data'),
     Input('auth-status', 'data')],
    prevent_initial_call=False
)
def sync_ui_from_otp_state(otp_state, auth_state):
    """Synchronize UI visibility with OTP/Auth flow state.

    - When otp_state.step == 'verify', show OTP input view
    - When otp_state.step == 'login', show login view
    - When auth_state.authenticated is True, show settings
    """
    # Authenticated user → show settings
    if auth_state and isinstance(auth_state, dict) and auth_state.get('authenticated'):
        return {'show_login': False, 'show_otp': False, 'show_settings': True}

    if not otp_state or not isinstance(otp_state, dict):
        return no_update

    step = otp_state.get('step')
    if step == 'verify':
        return {'show_login': False, 'show_otp': True, 'show_settings': False}
    if step == 'login':
        return {'show_login': True, 'show_otp': False, 'show_settings': False}

    return no_update

# 3. OTP Verification Handler
@callback(
    [Output('auth-state-store', 'data'),
     Output('auth-status', 'data'),
     Output('otp-verify-error', 'children'),
     Output('otp-code-input', 'value')],
    [Input('verify-otp-button', 'n_clicks')],
    [State('email-input', 'value'),
     State('otp-code-input', 'value')],
    prevent_initial_call=True
)
def handle_otp_verification(n_clicks, email, otp_code):
    """Handle OTP verification with direct UI update"""
    if not n_clicks or not email or not otp_code:
        return [no_update, no_update, no_update, no_update]

    try:
        user = get_user_by_email(email)
        if not user:
            return [no_update, no_update, 'Benutzer nicht gefunden.', no_update]

        user_id = user[0]

        if is_account_locked(user_id):
            return [no_update, no_update, 'Konto ist gesperrt.', no_update]

        if validate_otp(user_id, otp_code):
            # Success - set auth states; UI will switch to settings via bridge
            auth_state = {'authenticated': True, 'user_id': user_id, 'email': email}
            print(f"DEBUG: OTP verification successful, setting auth_state: {auth_state}")
            return [auth_state, auth_state, '', '']
        else:
            return [no_update, no_update, 'Ungültiger OTP-Code.', no_update]

    except Exception as e:
        return [no_update, no_update, f'Fehler: {str(e)}', no_update]

# Allow requesting a new OTP from the OTP screen
@callback(
    Output('otp-instructions', 'children'),
    [Input('resend-otp-button', 'n_clicks')],
    [State('email-input', 'value')],
    prevent_initial_call=True
)
def handle_resend_otp(resend_clicks, email):
    if not resend_clicks or not email:
        return no_update
    try:
        import requests
        response = requests.post('http://localhost:8050/api/auth/otp/request',
                                 json={'email': email}, timeout=10)
        if response.status_code == 200:
            # Inform the user that a new code was sent
            return 'Ein neuer OTP-Code wurde an deine E-Mail gesendet.'
        else:
            error_msg = response.json().get('error', 'Unbekannter Fehler') if response.content else 'Unbekannter Fehler'
            return f'Fehler beim Senden: {error_msg}'
    except Exception as e:
        return f'Fehler beim Senden: {str(e)}'

# 4. Auth State to UI State Bridge (for initial load only)
@callback(
    Output('user-info', 'children'),
    [Input('auth-state-store', 'data'),
     Input('auth-status', 'data'),
     Input('_pages_location', 'pathname')],
    prevent_initial_call=False
)
def update_ui_from_auth(auth_state, auth_status, _pathname):
    """Update user info when auth state changes (UI state handled separately)"""
    print(f"DEBUG: update_ui_from_auth called with auth_state: {auth_state}, auth_status: {auth_status}")
    # Use auth_status (persistent) if auth_state is not available
    current_auth = auth_state if (auth_state and auth_state.get('authenticated')) else auth_status
    print(f"DEBUG: current_auth: {current_auth}")

    if not current_auth or not current_auth.get('authenticated'):
        return ''

    # Authenticated - show user info with logout and delete account
    email = current_auth.get('email', 'Unbekannt')
    user_info = html.Div([
        html.Span(f'Eingeloggt als: {email}', style={'fontWeight': '500'}),
        html.Div([
            html.Button('Konto löschen', id='delete-account-button', n_clicks=0, style=get_button_style('danger')),
            html.Button('Abmelden', id='logout-button-integrated', n_clicks=0, style=get_button_style('secondary')),
            dcc.ConfirmDialog(
                id='confirm-delete-account',
                message='Soll Ihr Benutzerkonto mit allen Profilen unwiderruflich gelöscht werden?'
            ),
            html.Div(id='delete-account-status', style={'marginLeft': '12px'})
        ], style={'display': 'flex', 'alignItems': 'center', 'gap': '10px'})
    ], style={'display': 'flex', 'justifyContent': 'space-between', 'alignItems': 'center'})

    return user_info


# 7. Logout Handler
@callback(
    Output('redirect-trigger', 'data'),
    [Input('logout-button-integrated', 'n_clicks')],
    prevent_initial_call=True
)
def handle_logout(logout_integrated_clicks):
    """Handle logout (single responsibility)"""
    if not logout_integrated_clicks:
        return no_update

    # Trigger redirect (auth reset will be handled by clientside)
    return {'redirect': True, 'timestamp': str(datetime.now())}

# 7b. Delete account (single callback handling open-confirm and delete)
@callback(
    [Output('confirm-delete-account', 'displayed'),
     Output('delete-account-status', 'children')],
    [Input('delete-account-button', 'n_clicks'),
     Input('confirm-delete-account', 'submit_n_clicks')],
    [State('auth-status', 'data')],
    prevent_initial_call=True
)
def handle_delete_account(delete_clicks, confirm_submits, auth_data):
    ctx = callback_context
    if not ctx.triggered:
        return no_update, no_update

    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

    # Step 1: Open confirm dialog
    if trigger_id == 'delete-account-button':
        return True, no_update

    # Step 2: Perform deletion after confirmation
    if trigger_id == 'confirm-delete-account':
        if not auth_data or not auth_data.get('authenticated'):
            return False, html.Span('Nicht authentifiziert.', style=get_error_style(True))

        user_email = auth_data.get('email')
        try:
            user = get_user_by_email(user_email)
            if not user:
                return False, html.Span('Benutzer nicht gefunden.', style=get_error_style(True))

            user_id = user[0]
            # Lösche alle Profile des Benutzers
            with get_db_conn() as conn, conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM notification_profiles
                    WHERE user_id = %s
                """, (user_id,))
                cur.execute("""
                    DELETE FROM users
                    WHERE id = %s
                """, (user_id,))

            return False, html.Span('Konto und Profile wurden gelöscht. Bitte Seite neu laden.', style={'color': '#16a085', 'fontWeight': '500'})
        except Exception as e:
            return False, html.Span(f'Fehler beim Löschen: {str(e)}', style=get_error_style(True))

    return no_update, no_update

# 7. Apprise Test Handler
@callback(
    Output('test-result', 'children'),
    [Input('test-notification-button', 'n_clicks')],
    [State('test-apprise-url', 'value'),
     State('auth-status', 'data')],
    prevent_initial_call=True
)
def test_apprise_notification(n_clicks, apprise_url, auth_state):
    """Test Apprise notification (single responsibility)"""
    if not n_clicks:
        return no_update

    if not auth_state or not auth_state.get('authenticated'):
        return html.Span('Nicht authentifiziert', style=get_error_style(True))

    if not apprise_url or not apprise_url.strip():
        return html.Div('Bitte gib eine Apprise-URL zum Testen ein.', style={'color': 'orange'})

    try:
        # Test the URL
        apobj = apprise.Apprise()
        if not apobj.add(apprise_url.strip()):
            return html.Div('Ungültiges Apprise-URL-Format.', style={'color': 'red'})

        result = apobj.notify(
            title='TI-Stats Test-Benachrichtigung',
            body='Dies ist eine Test-Benachrichtigung. Wenn du diese erhältst, funktioniert deine Konfiguration!',
            body_format=apprise.NotifyFormat.TEXT
        )

        if result:
            return html.Div('✅ Test-Benachrichtigung erfolgreich gesendet!', style={'color': 'green'})
        else:
            return html.Div('❌ Test-Benachrichtigung konnte nicht gesendet werden.', style={'color': 'red'})

    except Exception as e:
        return html.Div(f'❌ Fehler: {str(e)}', style={'color': 'red'})

# 8. Profile Form Toggle
@callback(
    Output('profile-form-container', 'style'),
    [Input('add-profile-button', 'n_clicks'),
     Input('cancel-profile-button', 'n_clicks'),
     Input({'type': 'edit-profile', 'profile_id': ALL}, 'n_clicks')],
    prevent_initial_call=True
)
def toggle_profile_form(add_clicks, cancel_clicks, edit_clicks_list):
    ctx = callback_context
    if not ctx.triggered:
        return {'display': 'none'}

    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

    if trigger_id == 'add-profile-button' and add_clicks:
        return {'display': 'block', 'marginTop': '20px', 'padding': '20px', 'backgroundColor': 'white', 'borderRadius': '12px', 'border': '1px solid #e9ecef'}
    if trigger_id == 'cancel-profile-button' and cancel_clicks:
        return {'display': 'none'}
    # Any edit-profile click → show form (robust JSON parsing, unabhängig von Key-Reihenfolge)
    if trigger_id.startswith('{'):
        try:
            trig_obj = json.loads(trigger_id)
            if trig_obj.get('type') == 'edit-profile':
                return {'display': 'block', 'marginTop': '20px', 'padding': '20px', 'backgroundColor': 'white', 'borderRadius': '12px', 'border': '1px solid #e9ecef'}
        except Exception:
            return {'display': 'none'}

    return {'display': 'none'}

# 9. Profile Save Handler
@callback(
    [Output('form-error', 'children')],
    [Input('save-profile-button', 'n_clicks')],
    [State('profile-name-input', 'value'),
     State('notification-type-radio', 'value'),
     State('notification-method-radio', 'value'),
     State('apprise-urls-textarea', 'value'),
     State('selected-cis-data', 'data'),
     State('auth-status', 'data')],
    prevent_initial_call=True
)
def save_profile(n_clicks, name, notification_type, notification_method, apprise_urls, selected_cis, auth_status):
    """Save profile (single responsibility)"""
    if not n_clicks:
        return no_update

    if not auth_status or not auth_status.get('authenticated'):
        return ['Nicht authentifiziert.']

    if not name or not name.strip():
        return ['Profilname ist erforderlich.']

    try:
        user_id = auth_status.get('user_id')
        email_notifications = notification_method == 'email'
        email_address = auth_status.get('email') if email_notifications else None

        # Process Apprise URLs
        url_items = []
        if notification_method == 'apprise' and apprise_urls:
            url_items = [url.strip() for url in apprise_urls.split('\n') if url.strip()]
            if url_items and not validate_apprise_urls(url_items):
                return 'Eine oder mehrere Apprise-URLs sind ungültig.'

        # Update falls current_profile_id gesetzt ist, sonst Create
        # Entscheiden, ob Update (wenn Name bereits existiert) oder Create
        profile_id = None
        with get_db_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT id FROM notification_profiles
                WHERE user_id = %s AND name = %s
            """, (user_id, name))
            row = cur.fetchone()
            if row:
                profile_id = row[0]
        if profile_id:
            ok = update_notification_profile(int(profile_id), user_id, name, notification_type, selected_cis or [], url_items, email_notifications, email_address)
            return ['✅ Profil erfolgreich aktualisiert!' if ok else 'Fehler beim Aktualisieren des Profils.']
        else:
            new_id = create_notification_profile(user_id, name, notification_type, selected_cis or [], url_items, email_notifications, email_address)
            return ['✅ Profil erfolgreich erstellt!' if new_id else 'Fehler beim Erstellen des Profils.']

    except Exception as e:
        return [f'Fehler: {str(e)}']

# === CI SELECTION CALLBACKS ===

# 10. Load Available CIs (DB only, informative status)
@callback(
    [Output('available-cis-data', 'data'),
     Output('ci-load-status', 'children')],
    [Input('auth-status', 'data'),
     Input('auth-state-store', 'data'),
     Input('ui-state-store', 'data'),
     Input('ci-load-once', 'n_intervals')]
)
def load_available_cis(auth_status, auth_state, ui_state, _n):
    """Load available CIs from DB when authenticated. Show cause on failure."""
    current_auth = auth_status if (auth_status and auth_status.get('authenticated')) else auth_state
    # Wenn UI bereits Einstellungen zeigt, versuchen zu laden (zusätzlicher Trigger)
    if (ui_state and ui_state.get('show_settings') and (not current_auth or not current_auth.get('authenticated'))):
        # In diesem Fall verlassen wir uns auf persistentes auth-status; ohne Auth keine CIs
        pass
    if not current_auth or not current_auth.get('authenticated'):
        return [], ''

    try:
        from mylibrary import get_data_of_all_cis
        cis_df = get_data_of_all_cis('')
        ci_list: list = []
        if hasattr(cis_df, 'empty') and not cis_df.empty:
            for _, row in cis_df.iterrows():
                ci_list.append({
                    'ci': str(row.get('ci', '')),
                    'name': str(row.get('name', '')),
                    'organization': str(row.get('organization', '')),
                    'product': str(row.get('product', ''))
                })
            return ci_list, ''
        return [], 'Keine CIs gefunden (ci_metadata leer).'
    except Exception as e:
        return [], f'Fehler beim Laden der CIs aus der Datenbank: {str(e)}'

# 11. CI Filter Handler
@callback(
    Output('ci-filter-text', 'data'),
    [Input('ci-filter-input', 'value')]
)
def update_ci_filter(filter_text):
    """Update CI filter text"""
    return filter_text or ''

# 12. CI Filter Info Display
@callback(
    Output('ci-filter-info', 'children'),
    [Input('ci-filter-text', 'data'),
     Input('available-cis-data', 'data')]
)
def update_filter_info(filter_text, available_cis):
    """Show filter information"""
    if not available_cis:
        return ''

    total_cis = len(available_cis)
    if not filter_text:
        return f'Zeige alle {total_cis} Configuration Items'

    # Count filtered results
    filtered_count = 0
    filter_lower = filter_text.lower()
    for ci in available_cis:
        if (filter_lower in ci.get('ci', '').lower() or
            filter_lower in ci.get('name', '').lower() or
            filter_lower in ci.get('organization', '').lower() or
            filter_lower in ci.get('product', '').lower()):
            filtered_count += 1

    return f'Filter: "{filter_text}" - {filtered_count} von {total_cis} CIs angezeigt'

# 13. Render CI Checkboxes
@callback(
    Output('ci-checkboxes-container', 'children'),
    [Input('available-cis-data', 'data'),
     Input('ci-filter-text', 'data'),
     Input('selected-cis-data', 'data')]
)
def render_ci_checkboxes(available_cis, filter_text, selected_cis):
    """Render CI checkboxes with filtering"""
    if available_cis is None:
        return html.P('Lade CIs...', style={'textAlign': 'center'})
    if isinstance(available_cis, list) and len(available_cis) == 0:
        return html.P('Keine CIs gefunden', style={'textAlign': 'center'})

    # Filter CIs
    filtered_cis = available_cis or []
    if filter_text:
        filter_lower = filter_text.lower()
        filtered_cis = []
        for ci in available_cis:
            if (filter_lower in ci.get('ci', '').lower() or
                filter_lower in ci.get('name', '').lower() or
                filter_lower in ci.get('organization', '').lower() or
                filter_lower in ci.get('product', '').lower()):
                filtered_cis.append(ci)

    # Create checkboxes
    checkboxes = []
    for ci_info in filtered_cis:  # Show all CIs
        ci_id = ci_info.get('ci', '')
        is_checked = ci_id in (selected_cis or [])

        checkbox = html.Div([
            dcc.Checklist(
                id={'type': 'ci-checkbox', 'ci': ci_id},
                options=[{'label': '', 'value': ci_id}],
                value=[ci_id] if is_checked else [],
                style={'marginRight': '10px'}
            ),
            html.Label([
                html.Strong(ci_id),
                html.Br(),
                html.Span(ci_info.get('name', ''), style={'fontSize': '14px'}),
                html.Br(),
                html.Span(f"{ci_info.get('organization', '')} - {ci_info.get('product', '')}",
                         style={'fontSize': '12px', 'color': '#7f8c8d'})
            ])
        ], style={'display': 'flex', 'alignItems': 'flex-start', 'marginBottom': '10px',
                  'padding': '8px', 'backgroundColor': 'white', 'borderRadius': '6px', 'border': '1px solid #e9ecef'})

        checkboxes.append(checkbox)

    if not checkboxes:
        return html.P('Keine CIs gefunden', style={'textAlign': 'center'})

    return checkboxes

# 14. Handle CI Selection
@callback(
    Output('selected-cis-data', 'data'),
    [Input({'type': 'ci-checkbox', 'ci': dash.ALL}, 'value'),
     Input('select-all-cis-button', 'n_clicks'),
     Input('deselect-all-cis-button', 'n_clicks'),
     Input('profile-selected-cis', 'data')],
    [State('available-cis-data', 'data'),
     State('ci-filter-text', 'data')],
    prevent_initial_call=False
)
def handle_ci_selection(checkbox_values, select_all_clicks, deselect_all_clicks, profile_selected_cis, available_cis, filter_text):
    """Handle CI selection changes"""
    ctx = callback_context
    if not ctx.triggered or not available_cis:
        return profile_selected_cis or []

    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]

    # Initialize from profile-selected-cis on edit load
    if trigger_id == 'profile-selected-cis':
        return profile_selected_cis or []

    # Handle select all
    if trigger_id == 'select-all-cis-button' and select_all_clicks:
        # Select all filtered CIs
        if filter_text:
            filter_lower = filter_text.lower()
            return [ci['ci'] for ci in available_cis if
                   (filter_lower in ci.get('ci', '').lower() or
                    filter_lower in ci.get('name', '').lower() or
                    filter_lower in ci.get('organization', '').lower() or
                    filter_lower in ci.get('product', '').lower())]
        else:
            return [ci['ci'] for ci in available_cis]

    # Handle deselect all
    if trigger_id == 'deselect-all-cis-button' and deselect_all_clicks:
        return []

    # Handle individual checkbox changes
    if 'ci-checkbox' in trigger_id:
        selected_cis = []
        for checkbox_value in checkbox_values:
            if checkbox_value:
                selected_cis.extend(checkbox_value)
        return list(set(selected_cis))  # Remove duplicates

    return profile_selected_cis or []

# 15. Load and Display Profiles
@callback(
    Output('profiles-container', 'children'),
    [Input('auth-status', 'data'),
     Input('save-profile-button', 'n_clicks'),
     Input('delete-profile-status', 'data')],  # Refresh after save/delete
    prevent_initial_call=False
)
def display_profiles(auth_state, save_clicks, delete_status):
    """Load and display user profiles"""
    if not auth_state or not auth_state.get('authenticated'):
        return []

    user_id = auth_state.get('user_id')
    if not user_id:
        return html.P('Fehler: Benutzer nicht authentifiziert.')

    try:
        # Load profiles from database
        with get_db_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, type, ci_list, apprise_urls, email_notifications
                FROM notification_profiles
                WHERE user_id = %s
                ORDER BY created_at DESC
            """, (user_id,))
            profiles = cur.fetchall()

        if not profiles:
            return html.P('Keine Benachrichtigungsprofile gefunden. Füge ein neues Profil hinzu, um zu beginnen.')

        profile_cards = []
        for profile in profiles:
            profile_id, name, notification_type, ci_list, apprise_urls, email_notifications = profile

            # Count items
            ci_count = len(ci_list) if ci_list else 0
            url_count = len(apprise_urls) if apprise_urls else 0
            notification_method = 'E-Mail' if email_notifications else 'Apprise'

            card = html.Div([
                html.H4(name or 'Unbenanntes Profil', style={'color': '#2c3e50', 'marginBottom': '15px'}),
                html.P(f"Typ: {notification_type.title() if notification_type else 'Whitelist'}", style={'margin': '5px 0'}),
                html.P(f"Methode: {notification_method}", style={'margin': '5px 0'}),
                html.P(f"CIs: {ci_count}", style={'margin': '5px 0'}),
                html.P(f"URLs: {url_count}", style={'margin': '5px 0'}),
                html.Div([
                    html.Button('Bearbeiten', id={'type': 'edit-profile', 'profile_id': str(profile_id)},
                              n_clicks=0, style=get_button_style('secondary')),
                    html.Button('Löschen', id={'type': 'delete-profile', 'profile_id': str(profile_id)},
                              n_clicks=0, style=get_button_style('danger')),
                    dcc.ConfirmDialog(
                        id={'type': 'confirm-delete-profile', 'profile_id': str(profile_id)},
                        message='Soll dieses Profil unwiderruflich gelöscht werden?'
                    )
                ], style={'display': 'flex', 'gap': '10px', 'justifyContent': 'flex-end'})
            ], style={
                'padding': '20px', 'borderRadius': '12px',
                'boxShadow': '0 2px 4px rgba(0, 0, 0, 0.1)', 'marginBottom': '15px'
            }, className='profile-card')

            profile_cards.append(card)

        return profile_cards

    except Exception as e:
        return html.P(f'Fehler beim Laden der Profile: {str(e)}', style={'color': '#e74c3c'})

# 16. Handle Edit Profile clicks: populate form and show it
@callback(
    [Output('profile-name-input', 'value'),
     Output('notification-type-radio', 'value'),
     Output('notification-method-radio', 'value'),
     Output('profile-selected-cis', 'data'),
     Output('current-profile-id', 'data')],
    [Input({'type': 'edit-profile', 'profile_id': ALL}, 'n_clicks'),
     Input('add-profile-button', 'n_clicks')],
    [State('auth-status', 'data')],
    prevent_initial_call=True
)
def handle_edit_profile(edit_clicks_list, add_clicks, auth_data):
    ctx = callback_context
    if not ctx.triggered:
        return no_update, no_update, no_update, no_update, no_update

    trigger = ctx.triggered[0]['prop_id']
    # Add new profile clicked → just show empty form values
    if trigger.startswith('add-profile-button'):
        return '', 'whitelist', 'apprise', [], None

    # Find which edit button was clicked
    try:
        triggered_id = json.loads(trigger.split('.')[0])
    except Exception:
        return no_update, no_update, no_update, no_update, no_update

    if not auth_data or not auth_data.get('authenticated'):
        return no_update, no_update, no_update, no_update, no_update

    profile_id = triggered_id.get('profile_id')
    if not profile_id:
        return no_update, no_update, no_update, no_update, no_update

    # Load profile from DB
    try:
        with get_db_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT name, type, ci_list, apprise_urls, apprise_urls_salt, email_notifications
                FROM notification_profiles
                WHERE id = %s
                """,
                (int(profile_id),)
            )
            row = cur.fetchone()
            if not row:
                return '', 'whitelist', 'apprise', [], None
            name, profile_type, ci_list, apprise_urls, apprise_urls_salt, email_notifications = row
            method = 'email' if email_notifications else 'apprise'
            # Decrypt apprise URLs for editing
            urls_text = ''
            if method == 'apprise' and apprise_urls:
                try:
                    encryption_key = os.getenv('ENCRYPTION_KEY')
                    if encryption_key:
                        encryption_key = encryption_key.encode()
                    else:
                        encryption_key = generate_encryption_key()
                    decrypted_urls = []
                    salts = list(apprise_urls_salt or [])
                    for idx, enc in enumerate(list(apprise_urls)):
                        try:
                            salt = salts[idx] if salts and len(salts) > idx else None
                            dec = decrypt_data(enc, salt, encryption_key) if salt else None
                            if dec:
                                decrypted_urls.append(dec)
                        except Exception:
                            continue
                    urls_text = '\n'.join(decrypted_urls)
                except Exception:
                    urls_text = ''
            return name or '', (profile_type or 'whitelist'), method, (ci_list or []), str(profile_id)
    except Exception:
        return '', 'whitelist', 'apprise', [], None

# 17. Handle per-profile deletion (confirm + delete)
@callback(
    Output('delete-profile-status', 'data'),
    [Input({'type': 'delete-profile', 'profile_id': ALL}, 'n_clicks'),
     Input({'type': 'confirm-delete-profile', 'profile_id': ALL}, 'submit_n_clicks')],
    [State('auth-status', 'data')],
    prevent_initial_call=True
)
def handle_delete_profile(delete_clicks_list, submit_clicks_list, auth_data):
    ctx = callback_context
    if not ctx.triggered:
        return ''
    trigger = ctx.triggered[0]['prop_id']
    # Open dialog on delete click
    if 'delete-profile' in trigger:
        # Find matching confirm dialog and set displayed via client JS is not feasible here; we used ConfirmDialog components per card.
        # Returning empty string; the actual open is handled by the component when its 'displayed' is set by user action.
        return ''
    # Confirmed deletion
    if 'confirm-delete-profile' in trigger:
        if not auth_data or not auth_data.get('authenticated'):
            return ''
        try:
            obj = json.loads(trigger.split('.')[0])
            profile_id = int(obj.get('profile_id'))
            with get_db_conn() as conn, conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM notification_profiles
                    WHERE id = %s
                """, (profile_id,))
            return f'deleted:{profile_id}'
        except Exception:
            return ''
    return ''

# Register page at the end
try:
    dash.register_page(__name__, path='/notifications')
except:
    pass

# Clientside callback for logout redirect and auth reset
dash.clientside_callback(
    """
    function(redirect_data) {
        if (redirect_data && redirect_data.redirect) {
            // Reset auth in localStorage and redirect
            localStorage.setItem('auth-status', JSON.stringify({'authenticated': false}));
            window.location.href = '/';
        }
        return '';
    }
    """,
    Output('user-info', 'title'),  # Use harmless attribute as dummy output
    [Input('redirect-trigger', 'data')],
    prevent_initial_call=True
)

layout = serve_layout
