import dash
from dash import html, dcc, callback, Input, Output, State, no_update
from mylibrary import *
import os

dash.register_page(__name__, path='/notifications-simple')

def serve_layout():
    return html.Div([
        html.H1('Notifications (Simple Test)', className='text-center mb-4'),
        
        # Test button
        html.Button('Test Button', id='test-button', className='btn btn-primary'),
        html.Div(id='test-output', className='mt-3'),
        
        # Profile container
        html.Div(id='simple-profiles-container', className='mt-4')
    ], className='container mt-4')

layout = serve_layout

# Simple test callback
@callback(
    Output('test-output', 'children'),
    Input('test-button', 'n_clicks'),
    prevent_initial_call=True
)
def handle_test_button(n_clicks):
    if n_clicks:
        return html.Div(f'Button clicked {n_clicks} times!', className='alert alert-success')
    return no_update

# Simple profiles callback
@callback(
    Output('simple-profiles-container', 'children'),
    Input('test-button', 'n_clicks'),
    prevent_initial_call=False
)
def handle_simple_profiles(n_clicks):
    print(f"DEBUG: Simple profiles callback called with n_clicks={n_clicks}")
    
    return html.Div([
        html.H4('Profile Test'),
        html.P('This is a simple test to verify callbacks work.'),
        html.P(f'Button clicks: {n_clicks or 0}')
    ], className='border p-3')
