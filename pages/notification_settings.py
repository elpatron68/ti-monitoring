import dash
from dash import html, dcc, callback, Input, Output, State, no_update, clientside_callback, ClientsideFunction
from mylibrary import *
import os
import json
import requests
import hashlib
import yaml

dash.register_page(__name__, path='/notifications')

def get_profile_salt():
    """Lädt den Profil-Salt aus der .env Datei"""
    try:
        return os.getenv('TI_PROFILE_SALT', 'default-salt-change-me')
    except:
        return 'default-salt-change-me'

def hash_email_with_salt(email):
    """Erstellt einen SHA-256 Hash der E-Mail-Adresse mit Salt"""
    salt = get_profile_salt()
    return hashlib.sha256((email.lower() + salt).encode('utf-8')).hexdigest()

def load_profiles_from_db(email):
    """Lädt Profile aus der Datenbank anhand des E-Mail-Hashes"""
    try:
        email_hash = hash_email_with_salt(email)
        
        with get_db_conn() as conn, conn.cursor() as cur:
            # Suche User anhand des E-Mail-Hashes
            cur.execute("SELECT id FROM users WHERE email_hash=%s AND deleted_at IS NULL", (email_hash,))
            row = cur.fetchone()
            if not row:
                return []
            user_id = row[0]
            
            cur.execute(
                "SELECT id, name, type, created_at, config_encrypted FROM notification_profiles WHERE user_id=%s ORDER BY id DESC",
                (user_id,)
            )
            rows = cur.fetchall()
            profiles = []
            for row in rows:
                profile_id, name, profile_type, created_at, config_encrypted = row
                
                # Entschlüssele Profil-Daten
                urls = []
                if config_encrypted:
                    try:
                        decrypted_data = decrypt_config_json(bytes(config_encrypted))
                        if decrypted_data and 'urls' in decrypted_data:
                            urls = decrypted_data['urls']
                    except Exception as e:
                        print(f"Fehler beim Entschlüsseln des Profils {profile_id}: {e}")
                
                profiles.append({
                    'id': profile_id,
                    'name': name,
                    'type': profile_type,
                    'urls': urls,
                    'created_at': created_at.strftime('%Y-%m-%d %H:%M:%S') if created_at else 'Unbekannt'
                })
            
            return profiles
    except Exception as e:
        print(f"Fehler beim Laden der Profile: {e}")
        return []

def save_profile_to_db(email, name, urls, profile_type='whitelist', selected_cis=None):
    """Speichert ein Profil in der Datenbank"""
    try:
        email_hash = hash_email_with_salt(email)
        
        with get_db_conn() as conn, conn.cursor() as cur:
            # Suche oder erstelle User
            cur.execute("SELECT id FROM users WHERE email_hash=%s AND deleted_at IS NULL", (email_hash,))
            row = cur.fetchone()
            if not row:
                # User erstellen
                cur.execute("INSERT INTO users (email_hash, created_at) VALUES (%s, NOW()) RETURNING id", (email_hash,))
                user_id = cur.fetchone()[0]
            else:
                user_id = row[0]
            
            # Verschlüssele Profil-Daten
            config_data = {'urls': urls}
            if selected_cis:
                config_data['selected_cis'] = selected_cis
            config_encrypted = encrypt_config_json(config_data)
            
            # Profil speichern
            cur.execute(
                "INSERT INTO notification_profiles (user_id, name, type, config_encrypted, created_at) VALUES (%s, %s, %s, %s, NOW())",
                (user_id, name, profile_type, config_encrypted)
            )
            conn.commit()
            
            return {'success': True, 'message': f'Profil "{name}" wurde erfolgreich gespeichert!'}
    except Exception as e:
        print(f"Fehler beim Speichern des Profils: {e}")
        return {'success': False, 'error': str(e)}

def delete_profile_from_db(email, profile_id):
    """Löscht ein Profil aus der Datenbank"""
    try:
        email_hash = hash_email_with_salt(email)
        
        with get_db_conn() as conn, conn.cursor() as cur:
            # Suche User
            cur.execute("SELECT id FROM users WHERE email_hash=%s AND deleted_at IS NULL", (email_hash,))
            row = cur.fetchone()
            if not row:
                return {'success': False, 'error': 'User nicht gefunden'}
            user_id = row[0]
            
            # Lösche Profil
            cur.execute(
                "DELETE FROM notification_profiles WHERE id=%s AND user_id=%s",
                (profile_id, user_id)
            )
            conn.commit()
            
            return {'success': True, 'message': 'Profil wurde erfolgreich gelöscht!'}
    except Exception as e:
        print(f"Fehler beim Löschen des Profils: {e}")
        return {'success': False, 'error': str(e)}

def serve_layout():
    return html.Div([
        
        # Auth status store - mit session_storage für Persistierung
        dcc.Store(id='auth-status', data={'authenticated': False}, storage_type='session'),
        
        # User ID store
        dcc.Store(id='user-id-store', data=None, storage_type='session'),
        
        # Profiles store
        dcc.Store(id='profiles-store', data=[]),
        
        # Main content
        html.Div([
            html.H1('Benachrichtigungseinstellungen', className='mb-4'),
            
            # Login form
            html.Div(id='login-form', children=[
                html.H3('Anmelden'),
                html.P('Geben Sie Ihre E-Mail-Adresse ein, um einen Einmalcode zu erhalten.'),
                html.Div([
                    html.Label('E-Mail-Adresse:', className='form-label'),
                    dcc.Input(
                        id='email-input',
                        type='email',
                        placeholder='ihre@email.com',
                        className='form-control mb-3'
                    ),
                    html.Button('Einmalcode anfordern', id='request-otp-button', className='btn btn-primary mb-3'),
                    html.Div(id='otp-request-result')
                ]),
                html.Div([
                    html.Label('Einmalcode:', className='form-label'),
                    dcc.Input(
                        id='otp-input',
                        type='text',
                        placeholder='123456',
                        className='form-control mb-3'
                    ),
                    html.Button('Anmelden', id='verify-otp-button', className='btn btn-success mb-3'),
                    html.Div(id='login-error')
                ])
            ]),
            
            # Authenticated content
            html.Div(id='authenticated-content', style={'display': 'none'}, children=[
                html.H3('Willkommen!'),
                html.P('Sie sind erfolgreich angemeldet.'),
                html.Button('Abmelden', id='logout-button', className='btn btn-secondary mb-4'),
                
                # Profile management
                html.H4('Profil-Verwaltung'),
                html.Button('Neues Profil anlegen', id='add-profile-button', className='btn btn-primary mb-3'),
                
                # Profile form
                html.Div(id='profile-form', style={'display': 'none'}, children=[
                    html.H5('Profil erstellen'),
                    html.Div([
                        html.Label('Profilname:', className='form-label'),
                        dcc.Input(
                            id='profile-name',
                            type='text',
                            placeholder='Mein Profil',
                            className='form-control mb-3'
                        ),
                        html.Label('Profil-Typ:', className='form-label'),
                        dcc.Dropdown(
                            id='profile-type',
                            options=[
                                {'label': 'Whitelist (nur ausgewählte CIs)', 'value': 'whitelist'},
                                {'label': 'Blacklist (alle außer ausgewählte CIs)', 'value': 'blacklist'}
                            ],
                            value='whitelist',
                            className='mb-3'
                        ),
                        html.Label('Konfigurationsobjekte:', className='form-label'),
                        html.Div([
                            dcc.Input(
                                id='ci-filter-input',
                                type='text',
                                placeholder='CIs filtern (z.B. "CI-0000" oder "gematik")',
                                className='form-control mb-2'
                            ),
                            html.Div([
                                html.Button('Alle aktivieren', id='select-all-cis-button', className='btn btn-outline-secondary btn-sm me-2'),
                                html.Button('Alle deaktivieren', id='deselect-all-cis-button', className='btn btn-outline-secondary btn-sm')
                            ], className='mb-2'),
                            html.Div(id='ci-checkboxes-container', className='border p-3 mb-3', style={'maxHeight': '200px', 'overflowY': 'auto'})
                        ]),
                        html.Label('Benachrichtigungs-URLs (eine pro Zeile):', className='form-label'),
                        dcc.Textarea(
                            id='profile-urls',
                            placeholder='https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT_ID>&text=...\nhttps://hooks.slack.com/services/...',
                            className='form-control mb-3',
                            rows=4
                        ),
                        html.Div([
                            html.Button('Speichern', id='save-profile-button', className='btn btn-success me-2'),
                            html.Button('Abbrechen', id='cancel-profile-button', className='btn btn-secondary')
                        ])
                    ])
                ]),
                
                # Profiles container
                html.Div(id='profiles-container')
            ])
        ], className='container mt-4')
    ])

layout = serve_layout

# OTP request callback
@callback(
    Output('otp-request-result', 'children'),
    Input('request-otp-button', 'n_clicks'),
    State('email-input', 'value'),
    prevent_initial_call=True
)
def handle_otp_request(n_clicks, email):
    if not n_clicks or not email:
        return ""
    
    try:
        # Call the API to request OTP
        response = requests.post('http://localhost:8050/api/auth/request_otp', 
                               json={'email': email}, 
                               timeout=10)
        
        if response.status_code == 200:
            return html.Div([
                html.P('Einmalcode wurde an Ihre E-Mail-Adresse gesendet.', 
                      className='alert alert-success')
            ])
        else:
            return html.Div([
                html.P(f'Fehler beim Senden des Einmalcodes: {response.text}', 
                      className='alert alert-danger')
            ])
    except Exception as e:
        return html.Div([
            html.P(f'Fehler beim Senden des Einmalcodes: {str(e)}', 
                  className='alert alert-danger')
        ])

# Auth status callback - handles login and logout
@callback(
    [Output('auth-status', 'data'),
     Output('user-id-store', 'data')],
    [Input('verify-otp-button', 'n_clicks'),
     Input('logout-button', 'n_clicks')],
    [State('email-input', 'value'),
     State('otp-input', 'value'),
     State('auth-status', 'data'),
     State('user-id-store', 'data')],
    prevent_initial_call=False
)
def handle_auth_status(verify_clicks, logout_clicks, email, otp, current_auth, current_user_id):
    ctx = dash.callback_context
    
    # Initial call - check if we have existing auth data
    if not ctx.triggered:
        if current_auth and current_auth.get('authenticated', False):
            return current_auth, current_user_id
        return {'authenticated': False}, current_user_id
    
    triggered_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    if triggered_id == 'logout-button' and logout_clicks and logout_clicks > 0:
        return {'authenticated': False}, current_user_id
    elif triggered_id == 'verify-otp-button' and verify_clicks and verify_clicks > 0:
        # Verify OTP with API
        if not email or not otp:
            return {'authenticated': False}, current_user_id
        
        try:
            response = requests.post('http://localhost:8050/api/auth/verify_otp', 
                                   json={'email': email, 'code': otp}, 
                                   timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'ok':
                    return {'authenticated': True, 'email': email}, current_user_id
                else:
                    return {'authenticated': False}, current_user_id
            else:
                return {'authenticated': False}, current_user_id
        except Exception as e:
            print(f"Error verifying OTP: {e}")
            return {'authenticated': False}, current_user_id
    
    return no_update, no_update

# Profiles callback - handles display, adding, editing, and deleting profiles
@callback(
    [Output('profiles-container', 'children'),
     Output('profile-form', 'style'),
     Output('profile-name', 'value'),
     Output('profile-urls', 'value'),
     Output('profiles-store', 'data')],
    [Input('auth-status', 'data'),
     Input('add-profile-button', 'n_clicks'),
     Input('cancel-profile-button', 'n_clicks'),
     Input('save-profile-button', 'n_clicks')],
    [State('profile-form', 'style'),
     State('profile-name', 'value'),
     State('profile-urls', 'value'),
     State('profile-type', 'value'),
     State('profiles-store', 'data')],
    prevent_initial_call=False
)
def handle_profiles(auth_data, add_clicks, cancel_clicks, save_clicks, form_style, profile_name, profile_urls, profile_type, profiles_data):
    ctx = dash.callback_context
    print(f"DEBUG: handle_profiles called with triggered: {ctx.triggered}")
    
    # Initial call - check if we have existing auth data
    if not ctx.triggered:
        print("DEBUG: Initial call - no trigger")
        if auth_data and auth_data.get('authenticated', False):
            email = auth_data.get('email', '') if auth_data else ''
            print(f"DEBUG: Loading profiles for email: {email}")
            db_profiles = load_profiles_from_db(email) if email else []
            print(f"DEBUG: Loaded {len(db_profiles)} profiles from DB")
            
            if db_profiles:
                profile_list = []
                for i, profile in enumerate(db_profiles):
                    profile_list.append(html.Div([
                        html.H5(f"Profil: {profile['name']}"),
                        html.P(f"Typ: {profile['type']}"),
                        html.P(f"URLs: {', '.join(profile['urls'])}"),
                        html.P(f"Erstellt: {profile['created_at']}")
                    ], className='border p-3 mb-3'))
                
                return profile_list, {'display': 'none'}, '', '', []
            else:
                return [], {'display': 'none'}, '', '', []
        else:
            return [], {'display': 'none'}, '', '', []
    
    triggered_id = ctx.triggered[0]['prop_id'].split('.')[0]
    print(f"DEBUG: Profile callback triggered by: {triggered_id}")
    
    # Handle auth-status changes (when user logs in)
    if triggered_id == 'auth-status':
        print(f"DEBUG: Auth status changed: {auth_data}")
        if not auth_data or not auth_data.get('authenticated', False):
            return [], {'display': 'none'}, '', '', []
        
        # Load profiles from database using email from auth data
        email = auth_data.get('email', '') if auth_data else ''
        print(f"DEBUG: Loading profiles for email: {email}")
        db_profiles = load_profiles_from_db(email) if email else []
        print(f"DEBUG: Loaded {len(db_profiles)} profiles from DB")
        
        if db_profiles:
            profile_list = []
            for i, profile in enumerate(db_profiles):
                profile_list.append(html.Div([
                    html.H5(f"Profil: {profile['name']}"),
                    html.P(f"Typ: {profile['type']}"),
                    html.P(f"URLs: {', '.join(profile['urls'])}"),
                    html.P(f"Erstellt: {profile['created_at']}")
                ], className='border p-3 mb-3'))
            
            return profile_list, {'display': 'none'}, '', '', []
        else:
            return [], {'display': 'none'}, '', '', []
    
    # Handle save profile button clicks
    if triggered_id == 'save-profile-button' and save_clicks and save_clicks > 0:
        print(f"DEBUG: Save profile triggered, auth_data: {auth_data}")
        if not auth_data or not auth_data.get('authenticated', False):
            print("DEBUG: Not authenticated, cannot save profile")
            return [], {'display': 'none'}, '', '', []
        
        email = auth_data.get('email', '') if auth_data else ''
        print(f"DEBUG: Email from auth_data: {email}")
        if not email:
            print("DEBUG: No email found in auth_data")
            return [], {'display': 'none'}, '', '', []
        
        # Validate inputs
        if not profile_name or not profile_name.strip():
            print("DEBUG: No profile name provided")
            return [], {'display': 'none'}, '', '', []
        
        # Parse URLs
        urls = []
        if profile_urls and profile_urls.strip():
            urls = [url.strip() for url in profile_urls.split('\n') if url.strip()]
        
        print(f"DEBUG: Saving profile '{profile_name.strip()}' with {len(urls)} URLs for email {email}")
        # Save to database
        result = save_profile_to_db(email, profile_name.strip(), urls, profile_type or 'whitelist')
        print(f"DEBUG: Save result: {result}")
        if result['success']:
            # Reload profiles from database
            db_profiles = load_profiles_from_db(email)
            print(f"DEBUG: Reloaded {len(db_profiles)} profiles after save")
            if db_profiles:
                profile_list = []
                for i, profile in enumerate(db_profiles):
                    profile_list.append(html.Div([
                        html.H5(f"Profil: {profile['name']}"),
                        html.P(f"Typ: {profile['type']}"),
                        html.P(f"URLs: {', '.join(profile['urls'])}"),
                        html.P(f"Erstellt: {profile['created_at']}")
                    ], className='border p-3 mb-3'))
                
                return profile_list, {'display': 'none'}, '', '', []
            else:
                return [], {'display': 'none'}, '', '', []
        else:
            print(f"DEBUG: Save failed: {result.get('error', 'Unknown error')}")
            return [], {'display': 'none'}, '', '', []
    
    # Handle add profile button clicks
    if triggered_id == 'add-profile-button' and add_clicks and add_clicks > 0:
        print("DEBUG: Add profile button clicked")
        return [], {'display': 'block', 'border': '1px solid #ccc', 'padding': '20px', 'marginTop': '20px', 'borderRadius': '5px'}, '', '', []
    
    # Handle cancel profile button clicks
    if triggered_id == 'cancel-profile-button' and cancel_clicks and cancel_clicks > 0:
        print("DEBUG: Cancel profile button clicked")
        return [], {'display': 'none'}, '', '', []
    
    return no_update, no_update, no_update, no_update, no_update


# UI visibility callback
@callback(
    [Output('login-form', 'style'),
     Output('authenticated-content', 'style')],
    [Input('auth-status', 'data')],
    prevent_initial_call=False
)
def update_ui_visibility(auth_data):
    if auth_data and auth_data.get('authenticated', False):
        return {'display': 'none'}, {'display': 'block'}
    else:
        return {'display': 'block'}, {'display': 'none'}
