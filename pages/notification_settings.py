import dash
from dash import html, dcc, Input, Output, State, callback, no_update, callback_context
import json
from mylibrary import *
import yaml
import os
import apprise
import secrets

# Modern button styles
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

# Hover effects for buttons
def get_button_style(button_type='primary'):
    base_style = MODERN_BUTTON_STYLES[button_type].copy()
    return base_style

# Error div styles
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
    if visible:
        base_style['display'] = 'block'
    else:
        base_style['display'] = 'none'
    return base_style

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

dash.register_page(__name__, path='/notifications')

# Store for authenticated user
auth_status = {'authenticated': False, 'user_id': None, 'email': None}

def serve_layout():
    layout = html.Div([
        html.H2('Benachrichtigungseinstellungen', style={
            'color': '#2c3e50',
            'fontWeight': '600',
            'marginBottom': '30px',
            'borderBottom': '2px solid #3498db',
            'paddingBottom': '10px'
        }),
        # Store for authentication status (persistent in browser)
        dcc.Store(id='auth-status', storage_type='session', data=auth_status),
        
        # OTP Login form (shown when not authenticated)
        html.Div(id='otp-login-container', children=[
            html.H3('OTP-Anmeldung erforderlich', style={'color': '#2c3e50', 'marginBottom': '20px'}),
            html.P('Bitte geben Sie Ihre E-Mail-Adresse ein, um einen OTP-Code zu erhalten.', style={'color': '#7f8c8d', 'marginBottom': '20px'}),
            dcc.Input(
                id='email-input',
                type='email',
                placeholder='E-Mail-Adresse eingeben',
                style={
                    'width': '100%', 
                    'marginBottom': '15px',
                    'padding': 'clamp(8px, 2vw, 12px)',
                    'border': '2px solid #e9ecef',
                    'borderRadius': '8px',
                    'fontSize': 'clamp(12px, 2.5vw, 14px)',
                    'transition': 'border-color 0.3s ease',
                    'boxSizing': 'border-box'
                }
            ),
            html.Button('OTP anfordern', id='request-otp-button', n_clicks=0, style=get_button_style('primary')),
            html.Div(id='otp-request-error', style={'color': '#e74c3c', 'marginTop': '15px', 'fontWeight': '500'})
        ], style={
            'width': '100%',
            'maxWidth': '900px',
            'margin': '0 auto',
            'padding': 'clamp(20px, 4vw, 30px)',
            'backgroundColor': 'white',
            'borderRadius': '12px',
            'boxShadow': '0 4px 6px rgba(0, 0, 0, 0.1)',
            'boxSizing': 'border-box'
        }),
        
        # OTP Code form (shown after email is entered)
        html.Div(id='otp-code-container', children=[
            html.H3('OTP-Code eingeben', style={'color': '#2c3e50', 'marginBottom': '20px'}),
            html.P(id='otp-instructions', children='Bitte geben Sie den 6-stelligen Code ein, den Sie per E-Mail erhalten haben.', style={'color': '#7f8c8d', 'marginBottom': '20px'}),
            dcc.Input(
                id='otp-code-input',
                type='text',
                placeholder='6-stelliger Code',
                style={
                    'width': '100%', 
                    'marginBottom': '15px',
                    'padding': 'clamp(8px, 2vw, 12px)',
                    'border': '2px solid #e9ecef',
                    'borderRadius': '8px',
                    'fontSize': 'clamp(12px, 2.5vw, 14px)',
                    'transition': 'border-color 0.3s ease',
                    'boxSizing': 'border-box'
                }
            ),
            html.Button('Anmelden', id='verify-otp-button', n_clicks=0, style=get_button_style('primary')),
            html.Button('Neuen Code anfordern', id='resend-otp-button', n_clicks=0, style=get_button_style('secondary')),
            html.Div(id='otp-verify-error', style={'color': '#e74c3c', 'marginTop': '15px', 'fontWeight': '500'})
        ], style={
            'width': '100%',
            'maxWidth': '900px',
            'margin': '0 auto',
            'padding': 'clamp(20px, 4vw, 30px)',
            'backgroundColor': 'white',
            'borderRadius': '12px',
            'boxShadow': '0 4px 6px rgba(0, 0, 0, 0.1)',
            'boxSizing': 'border-box',
            'display': 'none'
        }),
        
        # Settings interface (hidden when not authenticated)
        html.Div(id='settings-container', children=[
            html.Div(id='user-info', style={
                'marginBottom': '20px',
                'padding': '15px',
                'backgroundColor': '#f8f9fa',
                'borderRadius': '8px',
                'display': 'flex',
                'justifyContent': 'space-between',
                'alignItems': 'center'
            }),
            
            html.P('Verwalten Sie Ihre Benachrichtigungsprofile unten.', style={
                'color': '#7f8c8d',
                'fontSize': '16px',
                'marginBottom': '25px'
            }),
            
            # Display existing profiles
            html.Div(id='profiles-container'),
            
            # Add new profile button
            html.Button('Neues Profil hinzufügen', id='add-profile-button', n_clicks=0, style=get_button_style('success')),
            
            # Profile form (hidden by default)
            html.Div(id='profile-form-container', children=[
                html.H3('Profildetails', style={
                    'color': '#2c3e50',
                    'marginBottom': '20px',
                    'borderBottom': '2px solid #3498db',
                    'paddingBottom': '10px'
                }),
                dcc.Store(id='editing-profile-index'),
                dcc.Store(id='editing-profile-id'),
                dcc.Store(id='available-cis-data'),
                dcc.Store(id='selected-cis-data', data=[]),
                dcc.Store(id='ci-filter-text', data=''),
                dcc.Input(
                    id='profile-name-input',
                    placeholder='Profilname',
                    style={
                        'width': '100%', 
                        'marginBottom': '15px',
                        'padding': '12px',
                        'border': '2px solid #e9ecef',
                        'borderRadius': '8px',
                        'fontSize': '14px',
                        'transition': 'border-color 0.3s ease',
                        'boxSizing': 'border-box'
                    }
                ),
                html.Div([
                    html.Label('Benachrichtigungstyp:', style={
                        'display': 'block',
                        'marginBottom': '10px',
                        'fontWeight': '500',
                        'color': '#2c3e50'
                    }),
                    dcc.RadioItems(
                        id='notification-type-radio',
                        options=[
                            {'label': 'Whitelist', 'value': 'whitelist'},
                            {'label': 'Blacklist', 'value': 'blacklist'}
                        ],
                        value='whitelist',
                        inline=True,
                        style={
                            'marginBottom': '15px',
                            'width': '100%',
                            'display': 'flex',
                            'gap': '20px'
                        }
                    )
                ], style={
                    'marginBottom': '15px',
                    'width': '100%'
                }),
                html.Div([
                    html.Label('Konfigurationsobjekte:', style={
                        'display': 'block',
                        'marginBottom': '10px',
                        'fontWeight': '500',
                        'color': '#2c3e50'
                    }),
                    html.Div([
                        dcc.Input(
                            id='ci-filter-input',
                            type='text',
                            placeholder='CIs filtern (z.B. "CI-0000" oder "gematik")',
                            style={
                                'flex': '1',
                                'minWidth': '0',
                                'padding': '8px 12px',
                                'border': '2px solid #e9ecef',
                                'borderRadius': '6px',
                                'fontSize': '14px',
                                'marginRight': '10px',
                                'transition': 'border-color 0.3s ease',
                                'boxSizing': 'border-box'
                            }
                        ),
                        html.Button('Alle aktivieren', id='select-all-cis-button', n_clicks=0, style=get_button_style('secondary')),
                        html.Button('Alle deaktivieren', id='deselect-all-cis-button', n_clicks=0, style=get_button_style('secondary'))
                    ], style={
                        'display': 'flex',
                        'gap': '10px',
                        'marginBottom': '10px',
                        'alignItems': 'center',
                        'width': '100%',
                        'boxSizing': 'border-box'
                    }),
                    html.Div(id='ci-filter-info', style={
                        'width': '100%',
                        'fontSize': '12px',
                        'color': '#7f8c8d',
                        'marginBottom': '8px',
                        'fontStyle': 'italic'
                    }),
                    html.Div(id='ci-checkboxes-container', style={
                        'width': '100%',
                        'maxHeight': '200px',
                        'overflowY': 'auto',
                        'border': '2px solid #e9ecef',
                        'borderRadius': '8px',
                        'padding': '15px',
                        'backgroundColor': '#f8f9fa',
                        'boxSizing': 'border-box'
                    })
                ], style={
                    'marginBottom': '15px',
                    'width': '100%'
                }),
                html.Div([
                    html.Label('Benachrichtigungsmethode:', style={
                        'display': 'block',
                        'marginBottom': '10px',
                        'fontWeight': '500',
                        'color': '#2c3e50'
                    }),
                    dcc.RadioItems(
                        id='notification-method-radio',
                        options=[
                            {'label': 'Apprise (Erweitert)', 'value': 'apprise'},
                            {'label': 'E-Mail (Einfach)', 'value': 'email'}
                        ],
                        value='apprise',
                        inline=True,
                        style={
                            'marginBottom': '15px',
                            'width': '100%',
                            'display': 'flex',
                            'gap': '20px'
                        }
                    )
                ], style={
                    'marginBottom': '15px',
                    'width': '100%'
                }),
                html.Div(id='apprise-section', children=[
                    dcc.Textarea(
                        id='apprise-urls-textarea',
                        placeholder='Apprise URLs (eine pro Zeile)',
                        style={
                            'width': '100%', 
                            'height': '100px', 
                            'marginBottom': '15px',
                            'padding': '12px',
                            'border': '2px solid #e9ecef',
                            'borderRadius': '8px',
                            'fontSize': '14px',
                            'fontFamily': 'monospace',
                            'resize': 'vertical',
                            'transition': 'border-color 0.3s ease',
                            'boxSizing': 'border-box'
                        }
                    )
                ]),
                html.Div(id='email-section', children=[
                    html.P('Die E-Mail wird an Ihre Anmeldeadresse gesendet.', style={
                        'color': '#7f8c8d',
                        'fontSize': '14px',
                        'marginBottom': '15px'
                    })
                ], style={'display': 'none'}),
                html.Div(id='form-error', style={
                    **get_error_style(visible=False),
                    'width': '100%'
                }),
                html.Div([
                    html.Button('Profil speichern', id='save-profile-button', n_clicks=0, style=get_button_style('success')),
                    html.Button('Abbrechen', id='cancel-profile-button', n_clicks=0, style=get_button_style('secondary'))
                ], style={
                    'display': 'flex', 
                    'gap': '10px',
                    'justifyContent': 'flex-end',
                    'width': '100%'
                })
            ], style={
                'display': 'none',
                'width': '100%',
                'backgroundColor': 'white',
                'padding': 'clamp(15px, 3vw, 25px)',
                'borderRadius': '12px',
                'boxShadow': '0 4px 6px rgba(0, 0, 0, 0.1)',
                'marginTop': '20px',
                'border': '1px solid #e9ecef'
            }),
            
            # Delete confirmation modal
            dcc.ConfirmDialog(
                id='delete-confirm',
                message='Sind Sie sicher, dass Sie dieses Profil löschen möchten?'
            ),
            
            # Store for delete index
            dcc.Store(id='delete-index-store', data=None),
            # Test Apprise notification button
            html.Div([
                html.H3('Apprise-Benachrichtigung testen', style={
                    'color': '#2c3e50',
                    'marginBottom': '15px',
                    'borderBottom': '2px solid #3498db',
                    'paddingBottom': '10px'
                }),
                html.P('Geben Sie eine Apprise-URL ein, um zu testen, ob Ihr Benachrichtigungssystem funktioniert.', style={
                    'color': '#7f8c8d',
                    'marginBottom': '15px'
                }),
                dcc.Input(
                    id='test-apprise-url',
                    type='text',
                    placeholder='e.g., mmost://username:password@mattermost.medisoftware.org/channel',
                    style={
                        'width': '100%', 
                        'marginBottom': '15px',
                        'padding': '12px',
                        'border': '2px solid #e9ecef',
                        'borderRadius': '8px',
                        'fontSize': '14px',
                        'fontFamily': 'monospace',
                        'transition': 'border-color 0.3s ease',
                        'boxSizing': 'border-box'
                    }
                ),
                html.Button('Benachrichtigung testen', id='test-notification-button', n_clicks=0, style=get_button_style('warning')),
                html.Div(id='test-result', style={
                    'width': '100%',
                    'marginTop': '15px'
                })
            ], style={
                'width': '100%',
                'marginTop': '30px', 
                'padding': 'clamp(15px, 3vw, 25px)', 
                'border': '1px solid #e9ecef', 
                'borderRadius': '12px',
                'backgroundColor': 'white',
                'boxShadow': '0 2px 4px rgba(0, 0, 0, 0.05)'
            })
        ], style={'display': 'none'})
            ], style={
            'width': '100%',
            'maxWidth': '900px',
            'minWidth': '320px',
            'margin': '0 auto',
            'padding': 'clamp(10px, 3vw, 20px)',
            'fontFamily': '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
            'boxSizing': 'border-box'
        })
    
    return layout

layout = serve_layout

# Callback to handle OTP request
@callback(
    [Output('otp-login-container', 'style'),
     Output('otp-code-container', 'style'),
     Output('otp-request-error', 'children'),
     Output('otp-instructions', 'children')],
    [Input('request-otp-button', 'n_clicks')],
    [State('email-input', 'value')]
)
def handle_otp_request(n_clicks, email):
    if n_clicks and n_clicks > 0:
        if not email:
            return [no_update, no_update, 'Bitte geben Sie eine E-Mail-Adresse ein.', no_update]
        
        try:
            # Validate email format
            if '@' not in email or '.' not in email:
                return [no_update, no_update, 'Bitte geben Sie eine gültige E-Mail-Adresse ein.', no_update]
            
            # Check if user exists, create if not
            user = get_user_by_email(email)
            if user:
                user_id = user[0]
            else:
                user_id = create_user(email)
            
            if not user_id:
                return [no_update, no_update, 'Fehler beim Erstellen des Benutzers.', no_update]
            
            # Generate OTP
            otp, otp_id = generate_otp_for_user(user_id)
            
            # Send OTP via Apprise (using the template from config)
            config = load_config()
            otp_template = config.get('core', {}).get('otp_apprise_url_template')
            
            if otp_template:
                # Format the template with user email and OTP
                apprise_url = otp_template.format(email=email, otp=otp)
                
                # Send OTP notification
                apobj = apprise.Apprise()
                apobj.add(apprise_url)
                apobj.notify(
                    title='TI-Monitoring OTP-Code',
                    body=f'Ihr OTP-Code für TI-Monitoring lautet: {otp}\n\nDieser Code ist 10 Minuten gültig.',
                    body_format=apprise.NotifyFormat.TEXT
                )
            
            instructions = f'Bitte geben Sie den 6-stelligen Code ein, den Sie per E-Mail an {email} erhalten haben.'
            return [{'display': 'none'}, {'display': 'block'}, '', instructions]
            
        except Exception as e:
            return [no_update, no_update, f'Fehler beim Senden des OTP-Codes: {str(e)}', no_update]
    
    return [no_update, no_update, '', no_update]

# Callback to handle OTP verification
@callback(
    [Output('otp-code-container', 'style', allow_duplicate=True),
     Output('settings-container', 'style'),
     Output('otp-verify-error', 'children'),
     Output('auth-status', 'data'),
     Output('user-info', 'children')],
    [Input('verify-otp-button', 'n_clicks')],
    [State('email-input', 'value'),
     State('otp-code-input', 'value'),
     State('auth-status', 'data')],
    prevent_initial_call=True
)
def handle_otp_verification(n_clicks, email, otp_code, auth_data):
    if n_clicks and n_clicks > 0:
        if not email or not otp_code:
            return [no_update, no_update, 'Bitte geben Sie E-Mail und OTP-Code ein.', no_update, no_update]
        
        try:
            # Get user by email
            user = get_user_by_email(email)
            if not user:
                return [no_update, no_update, 'Benutzer nicht gefunden.', no_update, no_update]
            
            user_id = user[0]
            
            # Check if account is locked
            if is_account_locked(user_id):
                return [no_update, no_update, 'Konto ist gesperrt. Bitte versuchen Sie es später erneut.', no_update, no_update]
            
            # Validate OTP
            if validate_otp(user_id, otp_code):
                # Authentication successful
                auth_data['authenticated'] = True
                auth_data['user_id'] = user_id
                auth_data['email'] = email
                
                user_info = html.Div([
                    html.Span(f'Eingeloggt als: {email}', style={'fontWeight': '500'}),
                    html.Button('Abmelden', id='logout-button', n_clicks=0, style={
                        **get_button_style('secondary'),
                        'padding': '5px 10px',
                        'fontSize': '12px',
                        'marginLeft': '15px'
                    })
                ])
                
                return [{'display': 'none'}, {'display': 'block'}, '', auth_data, user_info]
            else:
                # OTP validation failed
                # Check if we should lock the account
                with get_db_conn() as conn, conn.cursor() as cur:
                    cur.execute("""
                        SELECT failed_login_attempts FROM users WHERE id = %s
                    """, (user_id,))
                    failed_attempts = cur.fetchone()[0] if cur.fetchone() else 0
                    
                    if failed_attempts >= 5:
                        lock_user_account(user_id)
                        return [no_update, no_update, 'Zu viele fehlgeschlagene Versuche. Konto ist jetzt gesperrt.', no_update, no_update]
                
                return [no_update, no_update, 'Ungültiger OTP-Code. Bitte versuchen Sie es erneut.', no_update, no_update]
                
        except Exception as e:
            return [no_update, no_update, f'Fehler bei der Verifizierung: {str(e)}', no_update, no_update]
    
    return [no_update, no_update, '', no_update, no_update]

# Callback to resend OTP
@callback(
    Output('otp-request-error', 'children', allow_duplicate=True),
    [Input('resend-otp-button', 'n_clicks')],
    [State('email-input', 'value')],
    prevent_initial_call=True
)
def handle_resend_otp(n_clicks, email):
    if n_clicks and n_clicks > 0:
        if not email:
            return 'Bitte geben Sie eine E-Mail-Adresse ein.'
        
        try:
            # Get user by email
            user = get_user_by_email(email)
            if not user:
                return 'Benutzer nicht gefunden.'
            
            user_id = user[0]
            
            # Generate new OTP
            otp, otp_id = generate_otp_for_user(user_id)
            
            # Send OTP via Apprise (using the template from config)
            config = load_config()
            otp_template = config.get('core', {}).get('otp_apprise_url_template')
            
            if otp_template:
                # Format the template with user email and OTP
                apprise_url = otp_template.format(email=email, otp=otp)
                
                # Send OTP notification
                apobj = apprise.Apprise()
                apobj.add(apprise_url)
                apobj.notify(
                    title='TI-Monitoring OTP-Code (Neu)',
                    body=f'Ihr neuer OTP-Code für TI-Monitoring lautet: {otp}\n\nDieser Code ist 10 Minuten gültig.',
                    body_format=apprise.NotifyFormat.TEXT
                )
            
            return 'Neuer OTP-Code wurde gesendet.'
            
        except Exception as e:
            return f'Fehler beim Senden des OTP-Codes: {str(e)}'
    
    return ''

# Callback to handle Enter key in password input
@callback(
    Output('verify-otp-button', 'n_clicks'),
    [Input('otp-code-input', 'n_submit')],
    [State('verify-otp-button', 'n_clicks')]
)
def handle_enter_key(n_submit, current_clicks):
    if n_submit and n_submit > 0:
        return (current_clicks or 0) + 1
    return current_clicks

# Callback to load all available CIs
@callback(
    Output('available-cis-data', 'data'),
    [Input('auth-status', 'data')]
)
def load_available_cis(auth_data):
    if not auth_data or not auth_data.get('authenticated', False):
        return []
    
    try:
        # Try to load CIs from the JSON file first (faster)
        ci_list_file_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'ci_list.json')
        
        if os.path.exists(ci_list_file_path):
            try:
                with open(ci_list_file_path, 'r', encoding='utf-8') as f:
                    ci_list = json.load(f)
                print(f"Loaded {len(ci_list)} CIs from JSON file")
                return ci_list
            except Exception as e:
                print(f"Error loading from JSON file: {e}, falling back to TimescaleDB")
        
        # Fallback: Load from TimescaleDB if JSON doesn't exist or fails
        from mylibrary import get_data_of_all_cis
        cis_df = get_data_of_all_cis('')  # file_name parameter not used anymore
        
        if not cis_df.empty:
            # Convert to list of dictionaries with ci and name
            ci_list = []
            for _, row in cis_df.iterrows():
                ci_info = {
                    'ci': str(row.get('ci', '')),
                    'name': str(row.get('name', '')),
                    'organization': str(row.get('organization', '')),
                    'product': str(row.get('product', ''))
                }
                ci_list.append(ci_info)
            return ci_list
        else:
            return []
    except Exception as e:
        print(f"Error loading CIs: {e}")
        return []

# Callback to render CI checkboxes
@callback(
    Output('ci-checkboxes-container', 'children'),
    [Input('available-cis-data', 'data'),
     Input('editing-profile-index', 'data'),
     Input('ci-filter-text', 'data')],
    [State('auth-status', 'data')]
)
def render_ci_checkboxes(cis_data, editing_index, filter_text, auth_data):
    if not auth_data or not auth_data.get('authenticated', False) or not cis_data:
        return html.P('Loading CIs...', style={'color': '#7f8c8d', 'textAlign': 'center'})
    
    try:
        # Load existing profile data if editing
        selected_cis = []
        if editing_index is not None:
            core_config = load_core_config()
            config_file = core_config.get('notifications_config_file', 'notifications.json')
            config = get_notification_config(config_file)
            if 0 <= editing_index < len(config):
                selected_cis = config[editing_index].get('ci_list', [])
        
        # Filter CIs based on filter text
        filtered_cis = []
        if filter_text and filter_text.strip():
            filter_lower = filter_text.lower().strip()
            for ci_info in cis_data:
                ci_id = ci_info.get('ci', '').lower()
                ci_name = ci_info.get('name', '').lower()
                ci_org = ci_info.get('organization', '').lower()
                ci_product = ci_info.get('product', '').lower()
                
                # Check if any field contains the filter text
                if (filter_lower in ci_id or 
                    filter_lower in ci_name or 
                    filter_lower in ci_org or 
                    filter_lower in ci_product):
                    filtered_cis.append(ci_info)
        else:
            # No filter, show all CIs
            filtered_cis = cis_data
        
        # Create checkboxes for each filtered CI
        checkbox_children = []
        for ci_info in filtered_cis:
            ci_id = ci_info.get('ci', '')
            ci_name = ci_info.get('name', '')
            ci_org = ci_info.get('organization', '')
            ci_product = ci_info.get('product', '')
            
            # Check if this CI is selected
            is_checked = ci_id in selected_cis
            
            # Create checkbox with label
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
                    html.Span(f"{ci_name}", style={'color': '#2c3e50', 'fontSize': '14px'}),
                    html.Br(),
                    html.Span(f"{ci_org} - {ci_product}", style={'color': '#7f8c8d', 'fontSize': '12px'})
                ], style={'cursor': 'pointer', 'marginLeft': '5px'})
            ], style={
                'display': 'flex',
                'alignItems': 'flex-start',
                'marginBottom': '10px',
                'padding': '8px',
                'borderRadius': '6px',
                'backgroundColor': 'white',
                'border': '1px solid #e9ecef'
            })
            
            checkbox_children.append(checkbox)
        
        if not checkbox_children:
            return html.P('No CIs found', style={'color': '#7f8c8d', 'textAlign': 'center'})
        
        return checkbox_children
        
    except Exception as e:
        return html.P(f'Error loading CIs: {str(e)}', style={'color': '#e74c3c', 'textAlign': 'center'})

# Callback to reset selected CIs when form is opened/closed
@callback(
    Output('selected-cis-data', 'data', allow_duplicate=True),
    [Input('profile-form-container', 'style')],
    [State('editing-profile-index', 'data')],
    prevent_initial_call=True
)
def reset_selected_cis(form_style, editing_index):
    """Reset selected CIs when form is opened or closed"""
    if form_style and form_style.get('display') == 'none':
        # Form is closed, reset selection
        return []
    elif editing_index is not None:
        # Form is opened for editing, load existing selection
        try:
            core_config = load_core_config()
            config_file = core_config.get('notifications_config_file', 'notifications.json')
            config = get_notification_config(config_file)
            if 0 <= editing_index < len(config):
                return config[editing_index].get('ci_list', [])
        except Exception:
            pass
    return []

# Callback to select all CIs
@callback(
    Output('selected-cis-data', 'data', allow_duplicate=True),
    [Input('select-all-cis-button', 'n_clicks')],
    [State('available-cis-data', 'data')],
    prevent_initial_call=True
)
def select_all_cis(n_clicks, available_cis_data):
    """Select all available CIs"""
    if not n_clicks or not available_cis_data:
        return no_update
    
    # Get all CI IDs from available CIs
    all_ci_ids = [ci_info.get('ci', '') for ci_info in available_cis_data if ci_info.get('ci')]
    return all_ci_ids

# Callback to deselect all CIs
@callback(
    Output('selected-cis-data', 'data', allow_duplicate=True),
    [Input('deselect-all-cis-button', 'n_clicks')],
    prevent_initial_call=True
)
def deselect_all_cis(n_clicks):
    """Deselect all CIs"""
    if not n_clicks:
        return no_update
    
    # Return empty list to deselect all
    return []

# Callback to store filter text
@callback(
    Output('ci-filter-text', 'data'),
    [Input('ci-filter-input', 'value')],
    prevent_initial_call=True
)
def update_filter_text(filter_text):
    """Store the filter text for CI filtering"""
    return filter_text or ''

# Callback to update filter info display
@callback(
    Output('ci-filter-info', 'children'),
    [Input('ci-filter-text', 'data'),
     Input('available-cis-data', 'data')]
)
def update_filter_info(filter_text, available_cis_data):
    """Update the filter information display"""
    if not available_cis_data:
        return ''
    
    total_cis = len(available_cis_data)
    
    if not filter_text or not filter_text.strip():
        return f'Zeige alle {total_cis} Configuration Items'
    
    # Count filtered results
    filter_lower = filter_text.lower().strip()
    filtered_count = 0
    for ci_info in available_cis_data:
        ci_id = ci_info.get('ci', '').lower()
        ci_name = ci_info.get('name', '').lower()
        ci_org = ci_info.get('organization', '').lower()
        ci_product = ci_info.get('product', '').lower()
        
        if (filter_lower in ci_id or 
            filter_lower in ci_name or 
            filter_lower in ci_org or 
            filter_lower in ci_product):
            filtered_count += 1
    
    return f'Filter: "{filter_text}" - {filtered_count} von {total_cis} CIs angezeigt'

# Callback to collect selected CIs from checkboxes
@callback(
    Output('selected-cis-data', 'data'),
    [Input({'type': 'ci-checkbox', 'ci': dash.ALL}, 'value')],
    [State('available-cis-data', 'data')],
    prevent_initial_call=True
)
def update_selected_cis(checkbox_values, available_cis_data):
    """Update the selected CIs when checkboxes change"""
    if not available_cis_data:
        return []
    
    # Collect all selected CIs from the checkbox values
    selected_cis = []
    for checkbox_value in checkbox_values:
        if checkbox_value:  # If checkbox has a value (is checked)
            selected_cis.extend(checkbox_value)
    
    # Remove duplicates
    selected_cis = list(set(selected_cis))
    
    return selected_cis

# Callback to update checkbox states when selected-cis-data changes
@callback(
    Output('ci-checkboxes-container', 'children', allow_duplicate=True),
    [Input('selected-cis-data', 'data')],
    [State('available-cis-data', 'data'),
     State('editing-profile-index', 'data'),
     State('ci-filter-text', 'data')],
    prevent_initial_call=True
)
def update_checkbox_states(selected_cis, available_cis_data, editing_index, filter_text):
    """Update all checkbox states when selected-cis-data changes"""
    if not available_cis_data:
        return no_update
    
    try:
        # Load existing profile data if editing
        existing_selected_cis = []
        if editing_index is not None:
            core_config = load_core_config()
            config_file = core_config.get('notifications_config_file', 'notifications.json')
            config = get_notification_config(config_file)
            if 0 <= editing_index < len(config):
                existing_selected_cis = config[editing_index].get('ci_list', [])
        
        # Use current selection from store, fallback to existing if editing
        current_selected_cis = selected_cis if selected_cis is not None else existing_selected_cis
        
        # Filter CIs based on filter text
        filtered_cis = []
        if filter_text and filter_text.strip():
            filter_lower = filter_text.lower().strip()
            for ci_info in available_cis_data:
                ci_id = ci_info.get('ci', '').lower()
                ci_name = ci_info.get('name', '').lower()
                ci_org = ci_info.get('organization', '').lower()
                ci_product = ci_info.get('product', '').lower()
                
                # Check if any field contains the filter text
                if (filter_lower in ci_id or 
                    filter_lower in ci_name or 
                    filter_lower in ci_org or 
                    filter_lower in ci_product):
                    filtered_cis.append(ci_info)
        else:
            # No filter, show all CIs
            filtered_cis = available_cis_data
        
        # Create checkboxes for each filtered CI
        checkbox_children = []
        for ci_info in filtered_cis:
            ci_id = ci_info.get('ci', '')
            ci_name = ci_info.get('name', '')
            ci_org = ci_info.get('organization', '')
            ci_product = ci_info.get('product', '')
            
            # Check if this CI is selected
            is_checked = ci_id in current_selected_cis
            
            # Create checkbox with label
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
                    html.Span(f"{ci_name}", style={'color': '#2c3e50', 'fontSize': '14px'}),
                    html.Br(),
                    html.Span(f"{ci_org} - {ci_product}", style={'color': '#7f8c8d', 'fontSize': '12px'})
                ], style={'cursor': 'pointer', 'marginLeft': '5px'})
            ], style={
                'display': 'flex',
                'alignItems': 'flex-start',
                'marginBottom': '10px',
                'padding': '8px',
                'borderRadius': '6px',
                'backgroundColor': 'white',
                'border': '1px solid #e9ecef'
            })
            
            checkbox_children.append(checkbox)
        
        if not checkbox_children:
            return html.P('No CIs found', style={'color': '#7f8c8d', 'textAlign': 'center'})
        
        return checkbox_children
        
    except Exception as e:
        return html.P(f'Error updating checkboxes: {str(e)}', style={'color': '#e74c3c', 'textAlign': 'center'})

# Callback to handle logout
@callback(
    [Output('otp-login-container', 'style', allow_duplicate=True),
     Output('settings-container', 'style', allow_duplicate=True),
     Output('otp-code-container', 'style', allow_duplicate=True),
     Output('auth-status', 'data', allow_duplicate=True),
     Output('email-input', 'value'),
     Output('otp-code-input', 'value')],
    [Input('logout-button', 'n_clicks')],
    [State('auth-status', 'data')],
    prevent_initial_call=True
)
def handle_logout(n_clicks, auth_data):
    if n_clicks and n_clicks > 0:
        # Reset authentication status
        auth_data['authenticated'] = False
        auth_data['user_id'] = None
        auth_data['email'] = None
        
        # Reset form inputs
        return [
            {'display': 'block'},  # Show login container
            {'display': 'none'},   # Hide settings container
            {'display': 'none'},   # Hide OTP code container
            auth_data,             # Reset auth data
            '',                    # Clear email input
            ''                     # Clear OTP input
        ]
    
    return [no_update, no_update, no_update, no_update, no_update, no_update]

# Callback to load and display profiles from database
@callback(
    Output('profiles-container', 'children'),
    [Input('auth-status', 'data'),
     Input('save-profile-button', 'n_clicks'),
     Input('delete-confirm', 'submit_n_clicks')]
)
def display_profiles(auth_data, save_clicks, delete_clicks):
    if not auth_data.get('authenticated', False):
        return []
    
    user_id = auth_data.get('user_id')
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
            return html.P('Keine Benachrichtigungsprofile gefunden. Fügen Sie ein neues Profil hinzu, um zu beginnen.')
        
        profile_cards = []
        for profile in profiles:
            profile_id, name, notification_type, ci_list, apprise_urls, email_notifications = profile
            
            # Count items
            ci_count = len(ci_list) if ci_list else 0
            url_count = len(apprise_urls) if apprise_urls else 0
            notification_method = 'E-Mail' if email_notifications else 'Apprise'
            
            card = html.Div([
                html.H4(name or 'Unbenanntes Profil', style={
                    'color': '#2c3e50',
                    'marginBottom': '15px',
                    'fontWeight': '600',
                    'borderBottom': '1px solid #ecf0f1',
                    'paddingBottom': '10px'
                }),
                html.Div([
                    html.P(f"Typ: {notification_type.title() if notification_type else 'Whitelist'}", style={
                        'color': '#7f8c8d',
                        'margin': '5px 0',
                        'fontSize': '14px'
                    }),
                    html.P(f"Benachrichtigungsmethode: {notification_method}", style={
                        'color': '#7f8c8d',
                        'margin': '5px 0',
                        'fontSize': '14px'
                    }),
                    html.P(f"Konfigurationsobjekte: {ci_count}", style={
                        'color': '#7f8c8d',
                        'margin': '5px 0',
                        'fontSize': '14px'
                    }),
                    html.P(f"Benachrichtigungs-URLs: {url_count}", style={
                        'color': '#7f8c8d',
                        'margin': '5px 0',
                        'fontSize': '14px'
                    })
                ], style={'marginBottom': '20px'}),
                html.Div([
                    html.Button('Bearbeiten', id={'type': 'edit-profile', 'profile_id': profile_id}, n_clicks=0, style=get_button_style('secondary')),
                    html.Button('Löschen', id={'type': 'delete-profile', 'profile_id': profile_id}, n_clicks=0, 
                               style=get_button_style('danger'))
                ], style={
                    'display': 'flex', 
                    'gap': '10px',
                    'justifyContent': 'flex-end',
                    'width': '100%'
                })
            ], className='profile-card', style={
                'width': '100%',
                'backgroundColor': 'white',
                'padding': 'clamp(15px, 3vw, 25px)',
                'borderRadius': '12px',
                'boxShadow': '0 2px 4px rgba(0, 0, 0, 0.1)',
                'marginBottom': '20px',
                'border': '1px solid #e9ecef',
                'transition': 'transform 0.2s ease, box-shadow 0.2s ease'
            })
            
            profile_cards.append(card)
        
        # Wrap profile cards in a container with consistent width
        return html.Div(profile_cards, style={
            'width': '100%',
            'display': 'flex',
            'flexDirection': 'column',
            'gap': '20px'
        })
    except Exception as e:
        return html.P(f'Fehler beim Laden der Profile: {str(e)}')

# Callback to show profile form
@callback(
    [Output('profile-form-container', 'style'),
     Output('editing-profile-id', 'data'),
     Output('profile-name-input', 'value'),
     Output('notification-type-radio', 'value'),
     Output('notification-method-radio', 'value'),
     Output('apprise-urls-textarea', 'value'),
     Output('apprise-section', 'style'),
     Output('email-section', 'style')],
    [Input('add-profile-button', 'n_clicks'),
     Input({'type': 'edit-profile', 'profile_id': dash.ALL}, 'n_clicks')],
    [State('auth-status', 'data')]
)
def show_profile_form(add_clicks, edit_clicks, auth_data):
    if not auth_data.get('authenticated', False):
        return [{'display': 'none'}, None, '', 'whitelist', 'apprise', '', {'display': 'block'}, {'display': 'none'}]
    
    # Check if add button was clicked
    ctx = callback_context
    if not ctx.triggered:
        return [{'display': 'none'}, None, '', 'whitelist', 'apprise', '', {'display': 'block'}, {'display': 'none'}]
    
    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    if button_id == 'add-profile-button':
        # Show empty form for new profile
        return [{'display': 'block'}, None, '', 'whitelist', 'apprise', '', {'display': 'block'}, {'display': 'none'}]
    else:
        # Show form with existing profile data for editing
        try:
            button_data = json.loads(button_id.replace("'", '"'))
            profile_id = button_data['profile_id']
            
            # Load profile from database
            with get_db_conn() as conn, conn.cursor() as cur:
                cur.execute("""
                    SELECT name, type, ci_list, apprise_urls, email_notifications
                    FROM notification_profiles
                    WHERE id = %s
                """, (profile_id,))
                profile = cur.fetchone()
                
                if profile:
                    name, notification_type, ci_list, apprise_urls, email_notifications = profile
                    notification_method = 'email' if email_notifications else 'apprise'
                    apprise_urls_text = '\n'.join(apprise_urls) if apprise_urls else ''
                    
                    apprise_section_style = {'display': 'block'} if notification_method == 'apprise' else {'display': 'none'}
                    email_section_style = {'display': 'block'} if notification_method == 'email' else {'display': 'none'}
                    
                    return [
                        {'display': 'block'}, 
                        profile_id, 
                        name or '', 
                        notification_type or 'whitelist', 
                        notification_method,
                        apprise_urls_text,
                        apprise_section_style,
                        email_section_style
                    ]
        except Exception:
            pass
    
    return [{'display': 'none'}, None, '', 'whitelist', 'apprise', '', {'display': 'block'}, {'display': 'none'}]

# Callback to toggle between notification methods
@callback(
    [Output('apprise-section', 'style', allow_duplicate=True),
     Output('email-section', 'style', allow_duplicate=True)],
    [Input('notification-method-radio', 'value')],
    prevent_initial_call=True
)
def toggle_notification_method(method):
    if method == 'apprise':
        return [{'display': 'block'}, {'display': 'none'}]
    else:
        return [{'display': 'none'}, {'display': 'block'}]

# Callback to save profile
@callback(
    [Output('profile-form-container', 'style', allow_duplicate=True),
     Output('form-error', 'children'),
     Output('form-error', 'style'),
     Output('save-profile-button', 'n_clicks')],
    [Input('save-profile-button', 'n_clicks'),
     Input('cancel-profile-button', 'n_clicks')],
    [State('editing-profile-id', 'data'),
     State('profile-name-input', 'value'),
     State('notification-type-radio', 'value'),
     State('notification-method-radio', 'value'),
     State('apprise-urls-textarea', 'value'),
     State('selected-cis-data', 'data'),
     State('auth-status', 'data')],
    prevent_initial_call=True
)
def handle_profile_form(save_clicks, cancel_clicks, edit_id, name, notification_type, notification_method, apprise_urls, selected_cis, auth_data):
    # Check which button was clicked
    ctx = callback_context
    if not ctx.triggered:
        return [no_update, '', get_error_style(visible=False), 0]
    
    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    # Handle cancel button
    if button_id == 'cancel-profile-button':
        return [{'display': 'none'}, '', get_error_style(visible=False), 0]
    
    # Handle save button
    if button_id == 'save-profile-button' and save_clicks > 0:
        # Validate inputs
        if not name:
            return [no_update, 'Profilname ist erforderlich.', get_error_style(visible=True), 0]
        
        user_id = auth_data.get('user_id')
        if not user_id:
            return [no_update, 'Benutzer nicht authentifiziert.', get_error_style(visible=True), 0]
        
        # Get selected CIs from the selected-cis-data store
        ci_items = selected_cis if selected_cis else []
        
        # Process notification method
        email_notifications = notification_method == 'email'
        email_address = auth_data.get('email') if email_notifications else None
        
        # Process Apprise URLs only if using Apprise method
        url_items = []
        if notification_method == 'apprise':
            url_items = [url.strip() for url in apprise_urls.split('\n') if url.strip()]
            
            # Validate Apprise URLs
            if url_items and not validate_apprise_urls(url_items):
                return [no_update, 'Eine oder mehrere Apprise-URLs sind ungültig.', get_error_style(visible=True), 0]
        
        try:
            # Save profile to database
            with get_db_conn() as conn, conn.cursor() as cur:
                if edit_id:
                    # Update existing profile
                    cur.execute("""
                        UPDATE notification_profiles 
                        SET name = %s, type = %s, ci_list = %s, apprise_urls = %s, 
                            email_notifications = %s, email_address = %s, updated_at = NOW()
                        WHERE id = %s AND user_id = %s
                    """, (name, notification_type, ci_items, url_items, email_notifications, email_address, edit_id, user_id))
                else:
                    # Generate unsubscribe token
                    unsubscribe_token = secrets.token_urlsafe(32)
                    
                    # Add new profile
                    cur.execute("""
                        INSERT INTO notification_profiles 
                        (user_id, name, type, ci_list, apprise_urls, email_notifications, email_address, unsubscribe_token)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (user_id, name, notification_type, ci_items, url_items, email_notifications, email_address, unsubscribe_token))
            
            return [{'display': 'none'}, '', get_error_style(visible=False), 0]  # Hide form and reset clicks
        except Exception as e:
            return [no_update, f'Fehler beim Speichern: {str(e)}', get_error_style(visible=True), 0]
    
    return [no_update, '', get_error_style(visible=False), 0]

# Callback to handle delete confirmation
@callback(
    [Output('delete-confirm', 'displayed'),
     Output('delete-confirm', 'message'),
     Output('delete-index-store', 'data')],
    [Input({'type': 'delete-profile', 'profile_id': dash.ALL}, 'n_clicks')],
    prevent_initial_call=True
)
def show_delete_confirm(delete_clicks):
    ctx = callback_context
    if not ctx.triggered:
        return [False, '', None]
    
    # Get the triggered input that caused this callback
    triggered_input = ctx.triggered[0]
    
    # Only show confirmation if a delete button was actually clicked (n_clicks > 0)
    if triggered_input['value'] <= 0:
        return [False, '', None]
    
    try:
        button_id = triggered_input['prop_id'].split('.')[0]
        button_data = json.loads(button_id.replace("'", '"'))
        profile_id = button_data['profile_id']
        
        # Get profile name for confirmation message
        with get_db_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT name FROM notification_profiles WHERE id = %s
            """, (profile_id,))
            result = cur.fetchone()
            profile_name = result[0] if result else 'Unbenanntes Profil'
        
        message = f'Sind Sie sicher, dass Sie das Profil "{profile_name}" löschen möchten?'
        return [True, message, profile_id]
    except Exception as e:
        print(f"Error in show_delete_confirm: {e}")
    
    return [False, '', None]

# Callback to delete profile
@callback(
    Output('delete-confirm', 'submit_n_clicks'),
    [Input('delete-confirm', 'submit_n_clicks')],
    [State('delete-index-store', 'data'),
     State('auth-status', 'data')],
    prevent_initial_call=True
)
def delete_profile(submit_n_clicks, delete_id, auth_data):
    if submit_n_clicks == 0 or delete_id is None:
        return 0
    
    user_id = auth_data.get('user_id')
    if not user_id:
        return 0
    
    try:
        # Delete profile from database
        with get_db_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                DELETE FROM notification_profiles 
                WHERE id = %s AND user_id = %s
            """, (delete_id, user_id))
            
        print(f"Successfully deleted profile with id {delete_id}")
    except Exception as e:
        print(f"Error in delete_profile: {e}")
    
    return submit_n_clicks

# Callback to test Apprise notification
@callback(
    Output('test-result', 'children'),
    [Input('test-notification-button', 'n_clicks')],
    [State('test-apprise-url', 'value'),
     State('auth-status', 'data')],
    prevent_initial_call=True
)
def test_apprise_notification(n_clicks, apprise_url, auth_data):
    if not auth_data.get('authenticated', False):
        return html.Div('Authentifizierung erforderlich.', style={'color': 'red'})
    
    if not apprise_url or not apprise_url.strip():
        return html.Div('Bitte geben Sie eine Apprise-URL zum Testen ein.', style={'color': 'orange'})
    
    try:
        # Create Apprise object and add the URL
        apobj = apprise.Apprise()
        
        # Add the URL and check if it was added successfully
        if not apobj.add(apprise_url.strip()):
            return html.Div([
                html.I(className='material-icons', children='error', style={'color': 'red', 'margin-right': '8px'}),
                html.Span('Ungültiges Apprise-URL-Format. Bitte überprüfen Sie die URL-Syntax.', style={'color': 'red'}),
                html.Br(),
                html.Span(f'URL: {apprise_url.strip()}', style={'color': 'gray', 'font-size': '0.9em'}),
                html.Br(),
                html.Br(),
                html.Span('Häufiges Mattermost-Format: mmost://username:password@mattermost.medisoftware.org/channel', style={'color': 'blue', 'font-size': '0.9em'}),
                html.Br(),
                html.Span('Beispiel: mmost://user:pass@mattermost.medisoftware.org/channel', style={'color': 'blue', 'font-size': '0.9em'})
            ])
        
        # Send test notification
        result = apobj.notify(
            title='TI-Monitoring Test-Benachrichtigung',
            body='Dies ist eine Test-Benachrichtigung von TI-Monitoring. Wenn Sie diese erhalten, funktioniert Ihre Apprise-Konfiguration korrekt!',
            body_format=apprise.NotifyFormat.TEXT
        )
        
        if result:
            return html.Div([
                html.I(className='material-icons', children='check_circle', style={'color': 'green', 'margin-right': '8px'}),
                html.Span('Test-Benachrichtigung erfolgreich gesendet! Überprüfen Sie Ihr Benachrichtigungsziel.', style={'color': 'green'}),
                html.Br(),
                html.Span(f'URL: {apprise_url.strip()}', style={'color': 'gray', 'font-size': '0.9em'}),
                html.Br(),
                html.Span('Hinweis: Wenn Sie die Nachricht nicht erhalten, überprüfen Sie Ihren Mattermost-Kanal und die Bot-Berechtigungen.', style={'color': 'blue', 'font-size': '0.9em'})
            ])
        else:
            return html.Div([
                html.I(className='material-icons', children='error', style={'color': 'red', 'margin-right': '8px'}),
                html.Span('Test-Benachrichtigung konnte nicht gesendet werden. Bitte überprüfen Sie Ihre Apprise-URL und Konfiguration.', style={'color': 'red'}),
                html.Br(),
                html.Span(f'URL: {apprise_url.strip()}', style={'color': 'gray', 'font-size': '0.9em'}),
                html.Br(),
                html.Br(),
                html.Span('Häufige Probleme:', style={'color': 'orange', 'font-weight': 'bold'}),
                html.Br(),
                html.Span('• Überprüfen Sie, ob der Mattermost-Server erreichbar ist', style={'color': 'orange'}),
                html.Br(),
                html.Span('• Überprüfen Sie Benutzername/Passwort-Anmeldedaten', style={'color': 'orange'}),
                html.Br(),
                html.Span('• Stellen Sie sicher, dass der Bot die Berechtigung hat, im Kanal zu posten', style={'color': 'orange'}),
                html.Br(),
                html.Span('• Überprüfen Sie die Mattermost-Server-Logs auf Fehler', style={'color': 'orange'})
            ])
            
    except Exception as e:
        return html.Div([
            html.I(className='material-icons', children='error', style={'color': 'red', 'margin-right': '8px'}),
            html.Span(f'Fehler beim Testen der Benachrichtigung: {str(e)}', style={'color': 'red'}),
            html.Br(),
            html.Span(f'URL: {apprise_url.strip()}', style={'color': 'gray', 'font-size': '0.9em'}),
            html.Br(),
            html.Br(),
            html.Span('Versuchen Sie stattdessen dieses Format:', style={'color': 'blue', 'font-weight': 'bold'}),
            html.Br(),
            html.Span('mmost://username:password@mattermost.medisoftware.org/channel', style={'color': 'blue', 'font-family': 'monospace'})
        ])
