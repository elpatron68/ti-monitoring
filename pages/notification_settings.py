import dash
from dash import html, dcc, callback, Input, Output, State, no_update, clientside_callback, ClientsideFunction, ALL, ctx
from mylibrary import *
import os
import json
import requests
import hashlib
import yaml
import pandas as pd

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

def load_all_cis():
    """Lädt alle verfügbaren CIs"""
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

def filter_cis(cis_data, filter_text):
    """Filtert CIs basierend auf dem Filtertext"""
    if not cis_data or not filter_text or not filter_text.strip():
        return cis_data
    
    filter_lower = filter_text.lower().strip()
    filtered_cis = []
    
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
    
    return filtered_cis

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
                selected_cis = []
                if config_encrypted:
                    try:
                        decrypted_data = decrypt_config_json(bytes(config_encrypted))
                        if decrypted_data:
                            if 'urls' in decrypted_data:
                                urls = decrypted_data['urls']
                            if 'selected_cis' in decrypted_data:
                                selected_cis = decrypted_data['selected_cis']
                    except Exception as e:
                        print(f"Fehler beim Entschlüsseln des Profils {profile_id}: {e}")
                
                profiles.append({
                    'id': profile_id,
                    'name': name,
                    'type': profile_type,
                    'urls': urls,
                    'selected_cis': selected_cis,
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

def update_profile_in_db(email, profile_id, name, urls, profile_type='whitelist', selected_cis=None):
    """Aktualisiert ein vorhandenes Profil in der Datenbank"""
    try:
        email_hash = hash_email_with_salt(email)
        
        with get_db_conn() as conn, conn.cursor() as cur:
            # Suche User
            cur.execute("SELECT id FROM users WHERE email_hash=%s AND deleted_at IS NULL", (email_hash,))
            row = cur.fetchone()
            if not row:
                return {'success': False, 'error': 'User nicht gefunden'}
            user_id = row[0]
            
            # Verschlüssele Profil-Daten
            config_data = {'urls': urls}
            if selected_cis:
                config_data['selected_cis'] = selected_cis
            config_encrypted = encrypt_config_json(config_data)
            
            # Profil aktualisieren
            cur.execute(
                "UPDATE notification_profiles SET name=%s, type=%s, config_encrypted=%s WHERE id=%s AND user_id=%s",
                (name, profile_type, config_encrypted, profile_id, user_id)
            )
            conn.commit()
            
            return {'success': True, 'message': f'Profil "{name}" wurde erfolgreich aktualisiert!'}
    except Exception as e:
        print(f"Fehler beim Aktualisieren des Profils: {e}")
        return {'success': False, 'error': str(e)}

def serve_layout():
    return html.Div([
        
        # Auth status store - mit session_storage für Persistierung
        dcc.Store(id='auth-status', data={'authenticated': False}, storage_type='session'),
        
        # User ID store
        dcc.Store(id='user-id-store', data=None, storage_type='session'),
        
        # Profiles store
        dcc.Store(id='profiles-store', data=[]),
        
        # CI data store
        dcc.Store(id='available-cis-data', data=[]),
        
        # Selected CIs store
        dcc.Store(id='selected-cis-data', data=[]),
        
        # CI filter text store
        dcc.Store(id='ci-filter-text', data=''),
        
        # Edit profile ID store
        dcc.Store(id='edit-profile-id', data=None),
        
        # Main content
        html.Div([
            html.H1('Benachrichtigungseinstellungen'),
            
            # Login form
            html.Div(id='login-form', className='box', children=[
                html.H3('Anmelden'),
                html.P('Geben Sie Ihre E-Mail-Adresse ein, um einen Einmalcode zu erhalten.'),
                html.Div([
                    html.Label('E-Mail-Adresse:', className='form-label'),
                    dcc.Input(
                        id='email-input',
                        type='email',
                        placeholder='ihre@email.com',
                        className='form-control'
                    ),
                    html.Div(className='button-group', children=[
                        html.Button('Einmalcode anfordern', id='request-otp-button', className='button'),
                    ]),
                    html.Div(id='otp-request-result')
                ], className='form-group'),
                html.Div([
                    html.Label('Einmalcode:', className='form-label'),
                    dcc.Input(
                        id='otp-input',
                        type='text',
                        placeholder='123456',
                        className='form-control'
                    ),
                    html.Div(className='button-group', children=[
                        html.Button('Anmelden', id='verify-otp-button', className='button'),
                    ]),
                    html.Div(id='login-error')
                ], className='form-group')
            ]),
            
            # Authenticated content
            html.Div(id='authenticated-content', style={'display': 'none'}, children=[
                html.Div([
                    html.H3('Willkommen!'),
                    html.P('Sie sind erfolgreich angemeldet.'),
                    html.Div(className='button-group', children=[
                        html.Button('Abmelden', id='logout-button', className='button'),
                    ])
                ], className='box'),
                
                # Profile management
                html.Div([
                    html.H4('Profil-Verwaltung'),
                    html.Div(className='button-group', children=[
                        html.Button('Neues Profil anlegen', id='add-profile-button', className='button'),
                    ]),
                    
                    # Profile form
                    html.Div(id='profile-form', style={'display': 'none'}, children=[
                        html.H5(id='profile-form-title', children='Profil erstellen'),
                        html.Div([
                            html.Label('Profilname:', className='form-label'),
                            dcc.Input(
                                id='profile-name',
                                type='text',
                                placeholder='Mein Profil',
                                className='form-control'
                            ),
                        ], className='form-group'),
                        html.Div([
                            html.Label('Profil-Typ:', className='form-label'),
                            dcc.Dropdown(
                                id='profile-type',
                                options=[
                                    {'label': 'Whitelist (nur ausgewählte CIs)', 'value': 'whitelist'},
                                    {'label': 'Blacklist (alle außer ausgewählte CIs)', 'value': 'blacklist'}
                                ],
                                value='whitelist'
                            ),
                        ], className='form-group'),
                        html.Div([
                            html.Label('Konfigurationsobjekte:', className='form-label'),
                            dcc.Input(
                                id='ci-filter-input',
                                type='text',
                                placeholder='CIs filtern (z.B. "CI-0000" oder "gematik")',
                                className='form-control'
                            ),
                            html.Div(className='button-group', children=[
                                html.Button('Alle aktivieren', id='select-all-cis-button', className='button'),
                                html.Button('Alle deaktivieren', id='deselect-all-cis-button', className='button')
                            ]),
                            html.Div(id='ci-filter-info', className='text-muted small'),
                            html.Div(id='ci-checkboxes-container', className='ci-checkboxes-container')
                        ], className='form-group'),
                        html.Div([
                            html.Label('Benachrichtigungs-URLs (eine pro Zeile):', className='form-label'),
                            dcc.Textarea(
                                id='profile-urls',
                                placeholder='https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<CHAT_ID>&text=...\nhttps://hooks.slack.com/services/...',
                                className='form-control',
                                rows=4
                            ),
                        ], className='form-group'),
                        html.Div(className='button-group', children=[
                            html.Button('Speichern', id='save-profile-button', className='button'),
                            html.Button('Abbrechen', id='cancel-profile-button', className='button')
                        ])
                    ])
                ], className='box'),
                
                # Profiles container
                html.Div(id='profiles-container')
            ])
        ])
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

# Callback to load all available CIs
@callback(
    Output('available-cis-data', 'data'),
    [Input('auth-status', 'data')]
)
def load_available_cis(auth_data):
    if not auth_data or not auth_data.get('authenticated', False):
        return []
    
    try:
        cis_data = load_all_cis()
        return cis_data
    except Exception as e:
        print(f"Error loading CIs: {e}")
        return []

# Callback to store filter text
@callback(
    Output('ci-filter-text', 'data'),
    [Input('ci-filter-input', 'value')],
    prevent_initial_call=False
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
    filtered_cis = filter_cis(available_cis_data, filter_text)
    filtered_count = len(filtered_cis)
    
    return f'Filter: "{filter_text}" - {filtered_count} von {total_cis} CIs angezeigt'

# Callback to render CI checkboxes
@callback(
    Output('ci-checkboxes-container', 'children'),
    [Input('available-cis-data', 'data'),
     Input('selected-cis-data', 'data'),
     Input('ci-filter-text', 'data')]
)
def render_ci_checkboxes(cis_data, selected_cis, filter_text):
    if not cis_data:
        return html.P('Lade CIs...', className='text-muted text-center')
    
    try:
        # Filter CIs based on filter text
        filtered_cis = filter_cis(cis_data, filter_text) if filter_text else cis_data
        
        # Create checkboxes for each filtered CI
        checkbox_children = []
        for ci_info in filtered_cis:
            ci_id = ci_info.get('ci', '')
            ci_name = ci_info.get('name', '')
            ci_org = ci_info.get('organization', '')
            ci_product = ci_info.get('product', '')
            
            # Check if this CI is selected
            is_checked = ci_id in (selected_cis or [])
            
            # Create checkbox with label
            checkbox = html.Div([
                dcc.Checklist(
                    id={'type': 'ci-checkbox', 'ci': ci_id},
                    options=[{'label': '', 'value': ci_id}],
                    value=[ci_id] if is_checked else [],
                    className='me-2'
                ),
                html.Label([
                    html.Strong(ci_id),
                    html.Br(),
                    html.Span(f"{ci_name}", className='text-dark small'),
                    html.Br(),
                    html.Span(f"{ci_org} - {ci_product}", className='text-muted small')
                ], className='cursor-pointer')
            ], className='d-flex align-items-start mb-2 p-2 border rounded')
            
            checkbox_children.append(checkbox)
        
        if not checkbox_children:
            return html.P('Keine CIs gefunden', className='text-muted text-center')
        
        return checkbox_children
        
    except Exception as e:
        return html.P(f'Fehler beim Laden der CIs: {str(e)}', className='text-danger text-center')

# Callback to collect selected CIs from checkboxes
@callback(
    Output('selected-cis-data', 'data', allow_duplicate=True),
    [Input({'type': 'ci-checkbox', 'ci': ALL}, 'value')],
    [State('available-cis-data', 'data')],
    prevent_initial_call='initial_duplicate'
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

# Callback to select all CIs
@callback(
    Output('selected-cis-data', 'data', allow_duplicate=True),
    [Input('select-all-cis-button', 'n_clicks')],
    [State('available-cis-data', 'data'),
     State('ci-filter-text', 'data')],
    prevent_initial_call=True
)
def select_all_cis(n_clicks, available_cis_data, filter_text):
    """Select all available CIs"""
    if not n_clicks or not available_cis_data:
        return no_update
    
    # Filter CIs based on filter text
    filtered_cis = filter_cis(available_cis_data, filter_text) if filter_text else available_cis_data
    
    # Get all CI IDs from filtered CIs
    all_ci_ids = [ci_info.get('ci', '') for ci_info in filtered_cis if ci_info.get('ci')]
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

# Profile deletion callback - handles individual profile deletion
@callback(
    Output('profiles-container', 'children', allow_duplicate=True),
    Input({'type': 'delete-profile-button', 'index': ALL}, 'n_clicks'),
    State({'type': 'delete-profile-button', 'index': ALL}, 'id'),
    State('auth-status', 'data'),
    prevent_initial_call=True
)
def handle_profile_deletion(n_clicks_list, button_ids_list, auth_data):
    # Check if any button was clicked
    if not any(n_clicks_list):
        return no_update
    
    # Find which button was clicked (the one with n_clicks > 0)
    clicked_index = None
    for i, n_clicks in enumerate(n_clicks_list):
        if n_clicks and n_clicks > 0:
            clicked_index = i
            break
    
    if clicked_index is None:
        return no_update
    
    # Get the profile ID from the clicked button
    clicked_button_id = button_ids_list[clicked_index]
    profile_id = clicked_button_id['index']
    
    # Check authentication
    if not auth_data or not auth_data.get('authenticated', False):
        return no_update
    
    email = auth_data.get('email', '')
    if not email:
        return no_update
    
    # Delete the profile
    result = delete_profile_from_db(email, profile_id)
    
    if result['success']:
        # Reload profiles from database
        db_profiles = load_profiles_from_db(email)
        if db_profiles:
            profile_list = []
            for i, profile in enumerate(db_profiles):
                # Count selected CIs
                ci_count = len(profile.get('selected_cis', []))
                
                profile_list.append(html.Div([
                    html.H5(f"Profil: {profile['name']}"),
                    html.P(f"Typ: {profile['type']}"),
                    html.P(f"Konfigurationsobjekte: {ci_count}"),
                    html.P(f"URLs: {', '.join(profile['urls'])}"),
                    html.P(f"Erstellt: {profile['created_at']}"),
                    html.Div(className='button-group', children=[
                        html.Button('Bearbeiten', 
                                  id={'type': 'edit-profile-button', 'index': profile["id"]},
                                  className='button'),
                        html.Button('Löschen', 
                                  id={'type': 'delete-profile-button', 'index': profile["id"]},
                                  className='button')
                    ])
                ], className='box'))
            
            return profile_list
        else:
            return []
    else:
        print(f"Error deleting profile: {result.get('error', 'Unknown error')}")
        return no_update

# Profile edit callback - handles profile editing
@callback(
    [Output('profile-form', 'style', allow_duplicate=True),
     Output('profile-form-title', 'children', allow_duplicate=True),
     Output('profile-name', 'value', allow_duplicate=True),
     Output('profile-type', 'value', allow_duplicate=True),
     Output('profile-urls', 'value', allow_duplicate=True),
     Output('selected-cis-data', 'data', allow_duplicate=True),
     Output('edit-profile-id', 'data', allow_duplicate=True)],
    Input({'type': 'edit-profile-button', 'index': ALL}, 'n_clicks'),
    State({'type': 'edit-profile-button', 'index': ALL}, 'id'),
    State('profiles-store', 'data'),
    prevent_initial_call=True
)
def handle_profile_edit(n_clicks_list, button_ids_list, profiles_data):
    # Check if any button was clicked
    if not any(n_clicks_list):
        return no_update, no_update, no_update, no_update, no_update, no_update, no_update
    
    # Find which button was clicked (the one with n_clicks > 0)
    clicked_index = None
    for i, n_clicks in enumerate(n_clicks_list):
        if n_clicks and n_clicks > 0:
            clicked_index = i
            break
    
    if clicked_index is None:
        return no_update, no_update, no_update, no_update, no_update, no_update, no_update
    
    # Get the profile ID from the clicked button
    clicked_button_id = button_ids_list[clicked_index]
    profile_id = clicked_button_id['index']
    
    # Find the profile in profiles_data
    profile = None
    for p in profiles_data:
        if p['id'] == profile_id:
            profile = p
            break
    
    if profile is None:
        return no_update, no_update, no_update, no_update, no_update, no_update, no_update
    
    # Prepare form values
    profile_name = profile.get('name', '')
    profile_type = profile.get('type', 'whitelist')
    profile_urls = '\n'.join(profile.get('urls', []))
    selected_cis = profile.get('selected_cis', [])
    
    return (
        {'display': 'block'},
        'Profil bearbeiten',
        profile_name,
        profile_type,
        profile_urls,
        selected_cis,
        profile_id
    )

# Profiles callback - handles display, adding, editing, and deleting profiles
@callback(
    [Output('profiles-container', 'children'),
     Output('profile-form', 'style'),
     Output('profile-form-title', 'children'),
     Output('profile-name', 'value'),
     Output('profile-type', 'value'),
     Output('profile-urls', 'value'),
     Output('profiles-store', 'data'),
     Output('selected-cis-data', 'data'),
     Output('edit-profile-id', 'data')],
    [Input('auth-status', 'data'),
     Input('add-profile-button', 'n_clicks'),
     Input('cancel-profile-button', 'n_clicks'),
     Input('save-profile-button', 'n_clicks')],
    [State('profile-form', 'style'),
     State('profile-form-title', 'children'),
     State('profile-name', 'value'),
     State('profile-urls', 'value'),
     State('profile-type', 'value'),
     State('profiles-store', 'data'),
     State('selected-cis-data', 'data'),
     State('edit-profile-id', 'data')],
    prevent_initial_call=False
)
def handle_profiles(auth_data, add_clicks, cancel_clicks, save_clicks, form_style, form_title, profile_name, profile_urls, profile_type, profiles_data, selected_cis, edit_profile_id):
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
                    # Count selected CIs
                    ci_count = len(profile.get('selected_cis', []))
                    
                    profile_list.append(html.Div([
                        html.H5(f"Profil: {profile['name']}"),
                        html.P(f"Typ: {profile['type']}"),
                        html.P(f"Konfigurationsobjekte: {ci_count}"),
                        html.P(f"URLs: {', '.join(profile['urls'])}"),
                        html.P(f"Erstellt: {profile['created_at']}"),
                        html.Div(className='button-group', children=[
                            html.Button('Bearbeiten', 
                                      id={'type': 'edit-profile-button', 'index': profile["id"]},
                                      className='button'),
                            html.Button('Löschen', 
                                      id={'type': 'delete-profile-button', 'index': profile["id"]},
                                      className='button')
                        ])
                    ], className='box'))
                
                return profile_list, {'display': 'none'}, 'Profil erstellen', '', 'whitelist', '', db_profiles, [], None
            else:
                return [], {'display': 'none'}, 'Profil erstellen', '', 'whitelist', '', [], [], None
        else:
            return [], {'display': 'none'}, 'Profil erstellen', '', 'whitelist', '', [], [], None
    
    triggered_id = ctx.triggered[0]['prop_id'].split('.')[0]
    print(f"DEBUG: Profile callback triggered by: {triggered_id}")
    
    # Handle auth-status changes (when user logs in)
    if triggered_id == 'auth-status':
        print(f"DEBUG: Auth status changed: {auth_data}")
        if not auth_data or not auth_data.get('authenticated', False):
            return [], {'display': 'none'}, 'Profil erstellen', '', 'whitelist', '', [], [], None
        
        # Load profiles from database using email from auth data
        email = auth_data.get('email', '') if auth_data else ''
        print(f"DEBUG: Loading profiles for email: {email}")
        db_profiles = load_profiles_from_db(email) if email else []
        print(f"DEBUG: Loaded {len(db_profiles)} profiles from DB")
        
        if db_profiles:
            profile_list = []
            for i, profile in enumerate(db_profiles):
                # Count selected CIs
                ci_count = len(profile.get('selected_cis', []))
                
                profile_list.append(html.Div([
                    html.H5(f"Profil: {profile['name']}"),
                    html.P(f"Typ: {profile['type']}"),
                    html.P(f"Konfigurationsobjekte: {ci_count}"),
                    html.P(f"URLs: {', '.join(profile['urls'])}"),
                    html.P(f"Erstellt: {profile['created_at']}"),
                    html.Div(className='button-group', children=[
                        html.Button('Bearbeiten', 
                                      id={'type': 'edit-profile-button', 'index': profile["id"]},
                                      className='button'),
                        html.Button('Löschen', 
                                      id={'type': 'delete-profile-button', 'index': profile["id"]},
                                      className='button')
                    ])
                ], className='box'))
            
            return profile_list, {'display': 'none'}, 'Profil erstellen', '', 'whitelist', '', db_profiles, [], None
        else:
            return [], {'display': 'none'}, 'Profil erstellen', '', 'whitelist', '', [], [], None
    
    # Handle save profile button clicks
    if triggered_id == 'save-profile-button' and save_clicks and save_clicks > 0:
        print(f"DEBUG: Save profile triggered, auth_data: {auth_data}")
        if not auth_data or not auth_data.get('authenticated', False):
            print("DEBUG: Not authenticated, cannot save profile")
            return [], {'display': 'none'}, 'Profil erstellen', '', 'whitelist', '', [], [], None
        
        email = auth_data.get('email', '') if auth_data else ''
        print(f"DEBUG: Email from auth_data: {email}")
        if not email:
            print("DEBUG: No email found in auth_data")
            return [], {'display': 'none'}, 'Profil erstellen', '', 'whitelist', '', [], [], None
        
        # Validate inputs
        if not profile_name or not profile_name.strip():
            print("DEBUG: No profile name provided")
            return [], {'display': 'none'}, 'Profil erstellen', '', 'whitelist', '', [], [], None
        
        # Parse URLs
        urls = []
        if profile_urls and profile_urls.strip():
            urls = [url.strip() for url in profile_urls.split('\n') if url.strip()]
        
        print(f"DEBUG: Saving profile '{profile_name.strip()}' with {len(urls)} URLs and {len(selected_cis or [])} CIs for email {email}")
        
        # Check if we're editing an existing profile
        if edit_profile_id:
            # Update existing profile
            result = update_profile_in_db(email, edit_profile_id, profile_name.strip(), urls, profile_type or 'whitelist', selected_cis)
        else:
            # Save new profile
            result = save_profile_to_db(email, profile_name.strip(), urls, profile_type or 'whitelist', selected_cis)
        
        print(f"DEBUG: Save result: {result}")
        if result['success']:
            # Reload profiles from database
            db_profiles = load_profiles_from_db(email)
            print(f"DEBUG: Reloaded {len(db_profiles)} profiles after save")
            if db_profiles:
                profile_list = []
                for i, profile in enumerate(db_profiles):
                    # Count selected CIs
                    ci_count = len(profile.get('selected_cis', []))
                    
                    profile_list.append(html.Div([
                        html.H5(f"Profil: {profile['name']}"),
                        html.P(f"Typ: {profile['type']}"),
                        html.P(f"Konfigurationsobjekte: {ci_count}"),
                        html.P(f"URLs: {', '.join(profile['urls'])}"),
                        html.P(f"Erstellt: {profile['created_at']}"),
                        html.Div(className='button-group', children=[
                            html.Button('Bearbeiten', 
                                      id={'type': 'edit-profile-button', 'index': profile["id"]},
                                      className='button'),
                            html.Button('Löschen', 
                                      id={'type': 'delete-profile-button', 'index': profile["id"]},
                                      className='button')
                        ])
                    ], className='box'))
                
                return profile_list, {'display': 'none'}, 'Profil erstellen', '', 'whitelist', '', db_profiles, [], None
            else:
                return [], {'display': 'none'}, 'Profil erstellen', '', 'whitelist', '', [], [], None
        else:
            print(f"DEBUG: Save failed: {result.get('error', 'Unknown error')}")
            return [], {'display': 'none'}, 'Profil erstellen', '', 'whitelist', '', [], [], None
    
    # Handle add profile button clicks
    if triggered_id == 'add-profile-button' and add_clicks and add_clicks > 0:
        print("DEBUG: Add profile button clicked")
        return no_update, {'display': 'block'}, 'Profil erstellen', '', 'whitelist', '', no_update, [], None
    
    # Handle cancel profile button clicks
    if triggered_id == 'cancel-profile-button' and cancel_clicks and cancel_clicks > 0:
        print("DEBUG: Cancel profile button clicked")
        return no_update, {'display': 'none'}, 'Profil erstellen', '', 'whitelist', '', no_update, [], None
    
    return no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update

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