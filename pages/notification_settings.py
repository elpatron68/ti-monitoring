import dash
from dash import html, dcc, Input, Output, State, callback, no_update
import json
from mylibrary import *
from myconfig import *

dash.register_page(__name__, path='/notifications')

# Global variable to store authentication status (in production, use session or database)
auth_status = {'authenticated': False}

def serve_layout():
    layout = html.Div([
        html.H2('Notification Settings'),
        # Store for authentication status
        dcc.Store(id='auth-status', storage_type='memory', data=auth_status),
        
        # Login form (shown when not authenticated)
        html.Div(id='login-container', children=[
            html.H3('Login Required'),
            html.P('Please enter the password to access notification settings.'),
            dcc.Input(
                id='password-input',
                type='password',
                placeholder='Enter password',
                style={'width': '100%', 'margin-bottom': '10px'}
            ),
            html.Button('Login', id='login-button', n_clicks=0),
            html.Div(id='login-error', style={'color': 'red', 'margin-top': '10px'})
        ]),
        
        # Settings interface (hidden when not authenticated)
        html.Div(id='settings-container', children=[
            html.P('Manage your notification profiles below.'),
            
            # Display existing profiles
            html.Div(id='profiles-container'),
            
            # Add new profile button
            html.Button('Add New Profile', id='add-profile-button', n_clicks=0),
            
            # Profile form (hidden by default)
            html.Div(id='profile-form-container', children=[
                html.H3('Profile Details'),
                dcc.Store(id='editing-profile-index'),
                dcc.Input(
                    id='profile-name-input',
                    placeholder='Profile Name',
                    style={'width': '100%', 'margin-bottom': '10px'}
                ),
                html.Div([
                    html.Label('Notification Type:'),
                    dcc.RadioItems(
                        id='notification-type-radio',
                        options=[
                            {'label': 'Whitelist', 'value': 'whitelist'},
                            {'label': 'Blacklist', 'value': 'blacklist'}
                        ],
                        value='whitelist',
                        inline=True
                    )
                ], style={'margin-bottom': '10px'}),
                dcc.Textarea(
                    id='ci-list-textarea',
                    placeholder='Configuration Item IDs (one per line)',
                    style={'width': '100%', 'height': '100px', 'margin-bottom': '10px'}
                ),
                dcc.Textarea(
                    id='apprise-urls-textarea',
                    placeholder='Apprise URLs (one per line)',
                    style={'width': '100%', 'height': '100px', 'margin-bottom': '10px'}
                ),
                html.Div(id='form-error', style={'color': 'red', 'margin-bottom': '10px'}),
                html.Button('Save Profile', id='save-profile-button', n_clicks=0),
                html.Button('Cancel', id='cancel-profile-button', n_clicks=0, style={'margin-left': '10px'})
            ], style={'display': 'none'}),
            
            # Delete confirmation modal
            dcc.ConfirmDialog(
                id='delete-confirm',
                message='Are you sure you want to delete this profile?'
            )
        ], style={'display': 'none'})
    ])
    
    return layout

layout = serve_layout

# Callback to handle login
@callback(
    [Output('login-container', 'style'),
     Output('settings-container', 'style'),
     Output('login-error', 'children'),
     Output('auth-status', 'data')],
    [Input('login-button', 'n_clicks')],
    [State('password-input', 'value'),
     State('auth-status', 'data')]
)
def handle_login(n_clicks, password, auth_data):
    if n_clicks > 0 and password:
        if validate_password(password):
            auth_data['authenticated'] = True
            return [{'display': 'none'}, {'display': 'block'}, '', auth_data]
        else:
            return [no_update, no_update, 'Invalid password. Please try again.', auth_data]
    return [no_update, no_update, '', auth_data]

# Callback to load and display profiles
@callback(
    Output('profiles-container', 'children'),
    [Input('auth-status', 'data'),
     Input('save-profile-button', 'n_clicks'),
     Input('delete-confirm', 'submit_n_clicks')]
)
def display_profiles(auth_data, save_clicks, delete_clicks):
    if not auth_data.get('authenticated', False):
        return []
    
    try:
        config = get_notification_config(notifications_config_file)
        if not config:
            return html.P('No notification profiles found. Add a new profile to get started.')
        
        profile_cards = []
        for i, profile in enumerate(config):
            # Count items
            ci_count = len(profile.get('ci_list', []))
            url_count = len(profile.get('apprise_urls', []))
            
            card = html.Div([
                html.H4(profile.get('name', 'Unnamed Profile')),
                html.P(f"Type: {profile.get('type', 'whitelist').title()}"),
                html.P(f"Configuration Items: {ci_count}"),
                html.P(f"Notification URLs: {url_count}"),
                html.Button('Edit', id={'type': 'edit-profile', 'index': i}, n_clicks=0),
                html.Button('Delete', id={'type': 'delete-profile', 'index': i}, n_clicks=0, 
                           style={'margin-left': '10px', 'background-color': '#dc3545'})
            ], className='box', style={'margin-bottom': '10px'})
            
            profile_cards.append(card)
        
        return profile_cards
    except Exception as e:
        return html.P(f'Error loading profiles: {str(e)}')

# Callback to show profile form
@callback(
    [Output('profile-form-container', 'style'),
     Output('editing-profile-index', 'data'),
     Output('profile-name-input', 'value'),
     Output('notification-type-radio', 'value'),
     Output('ci-list-textarea', 'value'),
     Output('apprise-urls-textarea', 'value')],
    [Input('add-profile-button', 'n_clicks'),
     Input({'type': 'edit-profile', 'index': dash.ALL}, 'n_clicks')],
    [State('auth-status', 'data')]
)
def show_profile_form(add_clicks, edit_clicks, auth_data):
    if not auth_data.get('authenticated', False):
        return [{'display': 'none'}, None, '', 'whitelist', '', '']
    
    # Check if add button was clicked
    ctx = dash.callback_context
    if not ctx.triggered:
        return [{'display': 'none'}, None, '', 'whitelist', '', '']
    
    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    if button_id == 'add-profile-button':
        # Show empty form for new profile
        return [{'display': 'block'}, None, '', 'whitelist', '', '']
    else:
        # Show form with existing profile data for editing
        try:
            button_data = json.loads(button_id.replace("'", '"'))
            index = button_data['index']
            
            config = get_notification_config(notifications_config_file)
            if 0 <= index < len(config):
                profile = config[index]
                name = profile.get('name', '')
                notification_type = profile.get('type', 'whitelist')
                ci_list = '\n'.join(profile.get('ci_list', []))
                apprise_urls = '\n'.join(profile.get('apprise_urls', []))
                
                return [{'display': 'block'}, index, name, notification_type, ci_list, apprise_urls]
        except Exception:
            pass
    
    return [{'display': 'none'}, None, '', 'whitelist', '', '']

# Callback to save profile
@callback(
    [Output('profile-form-container', 'style', allow_duplicate=True),
     Output('form-error', 'children'),
     Output('save-profile-button', 'n_clicks')],
    [Input('save-profile-button', 'n_clicks'),
     Input('cancel-profile-button', 'n_clicks')],
    [State('editing-profile-index', 'data'),
     State('profile-name-input', 'value'),
     State('notification-type-radio', 'value'),
     State('ci-list-textarea', 'value'),
     State('apprise-urls-textarea', 'value'),
     State('auth-status', 'data')],
    prevent_initial_call=True
)
def handle_profile_form(save_clicks, cancel_clicks, edit_index, name, notification_type, ci_list, apprise_urls, auth_data):
    # Check which button was clicked
    ctx = dash.callback_context
    if not ctx.triggered:
        return [no_update, '', 0]
    
    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    # Handle cancel button
    if button_id == 'cancel-profile-button':
        return [{'display': 'none'}, '', 0]
    
    # Handle save button
    if button_id == 'save-profile-button' and save_clicks > 0:
        # Validate inputs
        if not name:
            return [no_update, 'Profile name is required.', 0]
        
        # Process CI list
        ci_items = [ci.strip() for ci in ci_list.split('\n') if ci.strip()]
        
        # Process Apprise URLs
        url_items = [url.strip() for url in apprise_urls.split('\n') if url.strip()]
        
        # Validate Apprise URLs
        if url_items and not validate_apprise_urls(url_items):
            return [no_update, 'One or more Apprise URLs are invalid.', 0]
        
        # Create profile object
        profile = {
            'name': name,
            'type': notification_type,
            'ci_list': ci_items,
            'apprise_urls': url_items
        }
        
        try:
            # Load existing config
            config = get_notification_config(notifications_config_file)
            
            if edit_index is not None and 0 <= edit_index < len(config):
                # Update existing profile
                config[edit_index] = profile
            else:
                # Add new profile
                config.append(profile)
            
            # Save config
            if save_notification_config(notifications_config_file, config):
                return [{'display': 'none'}, '', 0]  # Hide form and reset clicks
            else:
                return [no_update, 'Error saving configuration.', 0]
        except Exception as e:
            return [no_update, f'Error: {str(e)}', 0]
    
    return [no_update, '', 0]

# Callback to handle delete confirmation
@callback(
    [Output('delete-confirm', 'displayed'),
     Output('delete-confirm', 'message')],
    [Input({'type': 'delete-profile', 'index': dash.ALL}, 'n_clicks')],
    prevent_initial_call=True
)
def show_delete_confirm(delete_clicks):
    ctx = dash.callback_context
    if not ctx.triggered:
        return [False, '']
    
    # Get the triggered input that caused this callback
    triggered_input = ctx.triggered[0]
    
    # Only show confirmation if a delete button was actually clicked (n_clicks > 0)
    if triggered_input['value'] <= 0:
        return [False, '']
    
    try:
        button_id = triggered_input['prop_id'].split('.')[0]
        button_data = json.loads(button_id.replace("'", '"'))
        index = button_data['index']
        
        config = get_notification_config(notifications_config_file)
        if 0 <= index < len(config):
            profile_name = config[index].get('name', 'Unnamed Profile')
            message = f'Are you sure you want to delete the profile "{profile_name}"?'
            return [True, message]
    except Exception:
        pass
    
    return [False, '']

# Callback to delete profile
@callback(
    Output('delete-confirm', 'submit_n_clicks'),
    [Input('delete-confirm', 'submit_n_clicks')],
    [State('delete-confirm', 'triggered')],
    prevent_initial_call=True
)
def delete_profile(submit_n_clicks, triggered):
    if not triggered or submit_n_clicks == 0:
        return 0
    
    try:
        # Extract index from triggered data
        if isinstance(triggered, list) and len(triggered) > 0:
            trigger = triggered[0]
            if 'prop_id' in trigger:
                button_id = trigger['prop_id'].split('.')[0]
                # Fix the JSON parsing
                if button_id.startswith('{') and button_id.endswith('}'):
                    button_data = json.loads(button_id)
                else:
                    button_data = json.loads(button_id.replace("'", '"'))
                index = button_data['index']
                
                # Load config
                config = get_notification_config(notifications_config_file)
                
                # Remove profile at index
                if 0 <= index < len(config):
                    config.pop(index)
                    
                    # Save updated config
                    save_notification_config(notifications_config_file, config)
    except Exception:
        pass
    
    return submit_n_clicks