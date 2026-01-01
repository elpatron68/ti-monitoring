import dash
from dash import html, dcc, callback, Input, Output, State, clientside_callback, ALL
import plotly.express as px
import plotly.graph_objects as go
from mylibrary import *
import yaml
import os
import functools
import time
import gc
import pandas as pd
import json

# Configuration cache for home page with size limit
_home_config_cache = {}
_home_config_cache_timestamp = 0
_home_config_cache_ttl = 300  # 5 seconds cache TTL
_home_config_cache_max_size = 10  # Limit cache size

# Lightweight layout cache to avoid recomputing heavy DOM trees frequently
_home_layout_cache = None
_home_layout_cache_ts = 0
_home_layout_cache_ttl = 60  # seconds

# Limit how many items we render per product group to keep DOM small
_max_items_per_group = 50

def load_config():
    """Load configuration from YAML file with caching"""
    global _home_config_cache, _home_config_cache_timestamp

    current_time = time.time()
    if (not _home_config_cache or
        current_time - _home_config_cache_timestamp > _home_config_cache_ttl):

        config_path = os.path.join(os.path.dirname(__file__), '..', 'config.yaml')
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                _home_config_cache = yaml.safe_load(f) or {}
            _home_config_cache_timestamp = current_time

            # Limit cache size
            if len(_home_config_cache) > _home_config_cache_max_size:
                # Keep only the most recent entries
                keys = list(_home_config_cache.keys())[:_home_config_cache_max_size]
                _home_config_cache = {k: _home_config_cache[k] for k in keys}
        except (FileNotFoundError, Exception):
            _home_config_cache = {}
            _home_config_cache_timestamp = current_time

    return _home_config_cache

def load_core_config():
    """Load core configuration from cached config"""
    config = load_config()
    return config.get('core', {})

dash.register_page(__name__, path='/')

# No callback needed - table is scrollable

def create_incidents_table(incidents_data, show_all=False):
    """Erstellt eine erweiterbare Tabelle mit den letzten Incidents"""
    if not incidents_data:
        return html.P("Keine Incidents verfügbar.")

    # Show limited incidents by default for performance
    display_incidents = incidents_data if show_all else incidents_data[:10]

    # Create table rows
    table_rows = []
    for incident in display_incidents:
        # Determine status styling
        status_class = 'incident-ongoing' if incident['status'] == 'ongoing' else 'incident-resolved'
        status_text = 'Noch gestört' if incident['status'] == 'ongoing' else 'Wieder aktiv'

        # Format duration
        duration_hours = incident['duration_minutes'] / 60.0
        if duration_hours < 1:
            duration_text = f"{incident['duration_minutes']:.0f} Min"
        else:
            duration_text = f"{duration_hours:.1f} Std"

        # Format timestamps
        start_time = pd.to_datetime(incident['incident_start']).tz_convert('Europe/Berlin').strftime('%d.%m.%Y %H:%M')
        end_time = ''
        if incident['incident_end']:
            end_time = pd.to_datetime(incident['incident_end']).tz_convert('Europe/Berlin').strftime('%d.%m.%Y %H:%M')
        else:
            end_time = 'Laufend'

        table_rows.append(html.Tr([
            html.Td([
                html.A(incident['ci'], href=f'/plot?ci={incident["ci"]}', className='ci-link'),
                html.Br(),
                html.Span(incident['name'], className='ci-name')
            ]),
            html.Td([
                html.Span(incident['organization'], className='org-name'),
                html.Br(),
                html.Span(incident['product'], className='product-name')
            ]),
            html.Td(start_time, style={'whiteSpace': 'nowrap'}),
            html.Td(end_time, style={'whiteSpace': 'nowrap'}),
            html.Td(duration_text, style={'whiteSpace': 'nowrap'}),
            html.Td([
                html.Span(status_text, className=f'status-badge {status_class}')
            ])
        ]))

    # No expand button needed - table is scrollable

    return html.Div([
        html.Table([
            html.Thead([
                html.Tr([
                    html.Th("CI"),
                    html.Th("Organisation"),
                    html.Th("Beginn"),
                    html.Th("Ende"),
                    html.Th("Dauer"),
                    html.Th("Status")
                ])
            ]),
            html.Tbody(table_rows)
        ], className='incidents-table')
    ], className='incidents-table-container')

def create_accordion_element(group_name, group_data):
    """Create accordion element for a group of CIs"""
    # Ensure group_data is a DataFrame and handle it properly
    if hasattr(group_data, 'empty') and group_data.empty:
        return html.Div(className='accordion-element', children=[
            html.Div(className='accordion-element-title', children=[
                html.Span(className='availability-icon unavailable'),
                html.Span(className='group-name', children=f'{group_name} (0/0)'),
                html.Span(className='expand-collapse-icon', children='+')
            ]),
            html.Div(className='accordion-element-content', children=[
                html.P('Keine Daten verfügbar für diese Gruppe.')
            ])
        ])

    # Calculate availability statistics
    current_availability_sum = group_data['current_availability'].sum()
    total_count = len(group_data)
    available_count = (group_data['current_availability'] == 1).sum()

    # Determine availability status
    if current_availability_sum == total_count:
        availability_class = 'available'
    elif current_availability_sum == 0:
        availability_class = 'unavailable'
    else:
        availability_class = 'impaired'

    # Apply per-group item limit
    limited_group_data = group_data.head(_max_items_per_group)

    # Compute remaining count for hint
    remaining = max(0, len(group_data) - len(limited_group_data))

    return html.Div(className='accordion-element', children = [
        html.Div(
            className='accordion-element-title',
            children = [
                html.Span(
                    className=f'availability-icon {availability_class}',
                ),
                html.Span(
                    className = 'group-name',
                    children = f'{group_name} ({available_count}/{total_count})'
                ),
                html.Span(className='expand-collapse-icon', children='+')
            ]
        ),
        html.Div(className='accordion-element-content', children = [
            html.Ul(children = [
                html.Li([
                    html.Span(
                        className='availability-icon ' + (
                            'available' if row['current_availability'] == 1
                            else 'unavailable'
                        )
                    ),
                    html.Div([
                        html.A(str(row['ci']), href='/plot?ci=' + str(row['ci'])),
                        ': ' + row['name'] + ', ' + row['organization'] + ', ' + pretty_timestamp(row['time'])
                    ])
                ]) for _, row in limited_group_data.iterrows()
            ]),
            (html.Div(
                ['… und ', html.Strong(str(remaining)), ' weitere Einträge, siehe ', html.A('Statistiken', href='/stats')]
            ) if remaining > 0 else None)
        ])
    ])



def serve_layout():
    # Return cached layout if fresh
    global _home_layout_cache, _home_layout_cache_ts
    now_ts = time.time()
    if _home_layout_cache is not None and (now_ts - _home_layout_cache_ts) < _home_layout_cache_ttl:
        return _home_layout_cache
    # Load core configurations (now cached)
    core_config = load_core_config()

    # TimescaleDB mode - no file_name needed
    config_file_name = None
    config_url = core_config.get('url')

    # Load incidents data from statistics.json
    incidents_data = []
    try:
        statistics_file_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'statistics.json')
        if os.path.exists(statistics_file_path):
            with open(statistics_file_path, 'r', encoding='utf-8') as f:
                stats = json.load(f)
                incidents_data = stats.get('recent_incidents', [])
    except Exception as e:
        print(f"Error loading incidents data: {e}")
        incidents_data = []

    # Try to get data from TimescaleDB
    try:
        cis = get_data_of_all_cis_from_timescaledb()
    except Exception as e:
        print(f"Error reading data from TimescaleDB: {e}")
        cis = pd.DataFrame()  # Empty DataFrame

    # Check if DataFrame is empty
    if cis.empty:
        # Try to load data from API if URL is available
        if config_url:
            try:
                print(f"Loading data from API: {config_url}")
                # For TimescaleDB mode, we don't need to call update_file
                # The cron job should handle API updates
                print("API updates are handled by the cron job in TimescaleDB mode")
            except Exception as e:
                print(f"Error loading data from API: {e}")

        # If still empty, show message
        if cis.empty:
            layout = html.Div([
                html.P('Keine Daten verfügbar. Versuche Daten von der API zu laden...'),
                html.P('Falls das Problem weiterhin besteht, überprüfen Sie die API-Verbindung.'),
                html.P(f'API URL: {config_url or "Nicht konfiguriert"}'),
                html.P('Datenbank: TimescaleDB')
            ])
            return layout

    # Check if 'product' column exists
    if 'product' not in cis.columns:
        layout = html.Div([
            html.P('Daten sind verfügbar, aber die Spalte "product" fehlt. Möglicherweise ist die Datenstruktur fehlerhaft.'),
            html.P('Verfügbare Spalten: ' + ', '.join(cis.columns.tolist())),
            html.P(f'Anzahl Datensätze: {len(cis)}')
        ])
        return layout

    # Optimize DataFrame operations
    try:
        grouped = cis.groupby('product')
    except Exception as e:
        layout = html.Div([
            html.P('Fehler beim Gruppieren der Daten nach Produkt.'),
            html.P(f'Fehler: {str(e)}'),
            html.P(f'Verfügbare Spalten: {", ".join(cis.columns.tolist()) if not cis.empty else "Keine"}')
        ])
        return layout



    # Create accordion elements efficiently
    accordion_elements = []
    for group_name, group_data in grouped:
        accordion_elements.append(create_accordion_element(group_name, group_data))

    # Force garbage collection after processing large DataFrames
    gc.collect()

    # Clean up large DataFrames immediately after use
    if 'cis' in locals():
        del cis
    if 'grouped' in locals():
        del grouped
    gc.collect()

    # Create incidents table (show first 5 by default)
    incidents_table = create_incidents_table(incidents_data, show_all=False)

    # Canonical URL & JSON-LD (Organization/WebSite/HomePage)
    from flask import request as _flask_request
    _base = _flask_request.url_root.rstrip('/')
    _canonical = f"{_base}/"
    _og_image = f"{_base}/og-image.png?title=TI-Stats&subtitle=Verf%C3%BCgbarkeit%20und%20Statistiken&hours=24"
    _jsonld = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "url": _canonical,
        "name": "TI-Stats – Verfügbarkeit und Statistiken",
        "inLanguage": "de",
        "isPartOf": {"@type": "WebSite", "url": _base, "name": "TI-Stats"}
    }

    layout = html.Div([
        # SEO head helpers
        html.Link(rel='canonical', href=_canonical),
        html.Meta(name='og:url', content=_canonical),
        html.Meta(name='og:image', content=_og_image),
        html.Meta(name='twitter:image', content=_og_image),
        html.Script(type='application/ld+json', children=[json.dumps(_jsonld)]),
        html.P([
            'Diese Seite informiert dich über den aktuellen Status und langfristige Verfügbarkeits-Trends von IT-Diensten des deutschen öffentlichen Gesundheitssystems (Telematik Infrastruktur, TI). Das Projekt basiert auf Lukas Schmidt-Russnaks ',
            html.A('TI-Monitoring', href='https://ti-monitoring.de'),
            ', welches mit Statistiken, Benachrichtigungen etc. umfangreich erweitert und angepasst wurde. Daten werden alle 5 Minuten aktualisiert und derzeit für 6 Monate gespeichert.'
        ]),

        html.P([
            'Du hast auch die Möglichkeit, Benachrichtigungen individuell zu ',
            html.A('abonnieren', href='/notifications'),
            '. Diese werden dir über deinen persönlichen Apprise-Link gesendet, wenn sich der Status einer der abonierten Komponenten ändert.'
        ]),

        html.Div([
            html.Span('Oder folge den TI-Stats Bots auf Mastodon oder Bluesky: ', style={'marginRight': '6px'}),
            html.Span([
                html.A([
                    html.Img(src='/assets/mastodon.svg', alt='Mastodon', style={'verticalAlign': 'middle'}),
                    html.Span(' @ti-stats@mastodon.ti-stats.net', style={'verticalAlign': 'middle'})
                ], href='https://mastodon.ti-stats.net/@tistatus', target='_blank', rel='me noopener noreferrer'),
                html.Span(' · '),
                html.A([
                    html.Img(src='/assets/bluesky.svg', alt='Bluesky', style={'verticalAlign': 'middle'}),
                    html.Span(' @ti-stats@bsky.social', style={'verticalAlign': 'middle'})
                ], href='https://bsky.app/profile/ti-stats.bsky.social', target='_blank', rel='noopener noreferrer')
            ], className='social-links')
        ]) ,
        html.P([
        ]),
        # Incidents section
        html.Div([
            html.H3("Letzte Incidents", className='incidents-title'),
            html.Div([
                dcc.Store(id='incidents-data-store', data=incidents_data),
                html.Div(id='incidents-table-container', children=incidents_table)
            ], className='incidents-container')
        ], className='incidents-section'),

        # Alle CIs mit Downtimes (5 sichtbar, scrollbar) – Style analog zu Incidents
        html.Div([
            html.H3("Alle TI-Komponenten", className='ci-all-title'),
            html.Div([
                dcc.Input(
                    id='ci-all-filter',
                    type='text',
                    placeholder='CIs filtern (CI, Organisation oder Produkt)',
                    style={
                        'width': '100%',
                        'boxSizing': 'border-box',
                        'marginBottom': '16px',
                        'padding': '8px 12px',
                        'borderRadius': '6px',
                        # Kontrast im Dark Mode: Farben von der Umgebung erben
                        'backgroundColor': 'transparent',
                        'color': 'inherit',
                        'border': '1px solid rgba(128,128,128,0.35)'
                    },
                    className='incidents-filter-input'
                ),
                # Sortierzustand (Spalte & Richtung) persistieren
                dcc.Store(id='ci-sort-state', data={'by': 'ci', 'asc': True}),
                html.Div(id='ci-all-table-container', style={
                    'maxHeight': '260px',  # ~5 Zeilen sichtbar
                    'overflowY': 'auto'
                })
            ], className='incidents-container')
        ], className='incidents-section'),

        # Heatmap: zeitliche Verteilung der Incidents (letzte 30 Tage)
        html.Div([
            html.H3("Zeitliche Verteilung der Incidents (30 Tage)", className='stats-title'),
            dcc.Store(id='incident-heatmap-cache', data=None),
            dcc.Interval(id='incident-heatmap-refresh', interval=900000, n_intervals=0),
            html.Div([
                dcc.Graph(id='incident-heatmap', config={'displayModeBar': False})
            ], className='incidents-container'),
        ], className='incidents-section')
        ,
        html.Div([
            html.Span('Hinweis', style={'fontWeight': '600', 'marginRight': '6px'}),
            html.Br(),
            html.Span('Zu den ausführlichen '),
            html.A('Statistiken', href='/stats')
        ], className='warning-message')
    ])

    # Cache and return
    _home_layout_cache = layout
    _home_layout_cache_ts = time.time()
    return layout

layout = serve_layout


def _format_minutes_to_human(minutes: float) -> str:
    try:
        m = float(minutes or 0.0)
        if m < 60:
            return f"{m:.0f} Min"
        h = m / 60.0
        if h < 24:
            return f"{h:.1f} Std"
        d = h / 24.0
        return f"{d:.1f} Tg"
    except Exception:
        return "0 Min"


@callback(
    Output('ci-all-table-container', 'children'),
    [Input('incidents-data-store', 'data'), Input('ci-all-filter', 'value'), Input('ci-sort-state', 'data')],
    prevent_initial_call=False
)
def render_ci_all_table(_, filter_text, sort_state):
    try:
        # Daten inkl. Downtimes aus DB laden
        df = get_all_cis_with_downtimes()
        if df is None or df.empty:
            return html.Div('Keine CIs verfügbar.')

        # Sortierung (Standard: CI ASC; per Store überschreibbar)
        try:
            df = df.copy()
            df['ci'] = df['ci'].astype(str)
            by = (sort_state or {}).get('by', 'ci')
            asc = bool((sort_state or {}).get('asc', True))
            if by in ['ci', 'organization', 'product', 'name']:
                df = df.sort_values([by, 'ci'] if by != 'ci' else ['ci'], ascending=[asc, True] if by != 'ci' else asc)
            elif by == 'downtime_7d_min':
                df = df.sort_values(['downtime_7d_min', 'ci'], ascending=[asc, True])
            elif by == 'downtime_30d_min':
                df = df.sort_values(['downtime_30d_min', 'ci'], ascending=[asc, True])
            elif by == 'current_availability':
                df = df.sort_values(['current_availability', 'ci'], ascending=[asc, True])
            else:
                df = df.sort_values('ci')
        except Exception:
            pass

        # Sortierung bleibt CI ASC (stabil, bis sortierbare Header neu implementiert)

        # Filter anwenden über CI und Organisation/Produkt/Name
        if filter_text:
            f = str(filter_text).strip().lower()
            def match_row(r):
                try:
                    return (
                        f in str(r.get('ci','')).lower() or
                        f in str(r.get('organization','')).lower() or
                        f in str(r.get('product','')).lower() or
                        f in str(r.get('name','')).lower()
                    )
                except Exception:
                    return False
            try:
                df = df[[match_row(row) for _, row in df.iterrows()]]
            except Exception:
                pass

        # Alle CIs anzeigen (Sicht wird durch Scroll-Container begrenzt)
        df_display = df

        # Tabellenzeilen bauen
        rows = []
        for _, row in df_display.iterrows():
            status = int(row.get('current_availability') or 0)
            status_class = 'available' if status == 1 else 'unavailable'
            status_text = 'Verfügbar' if status == 1 else 'Gestört'

            rows.append(html.Tr([
                html.Td([
                    html.A(str(row.get('ci', '')), href=f"/plot?ci={str(row.get('ci',''))}", className='ci-link'),
                    html.Br(),
                    html.Span(str(row.get('name', '')), className='ci-name')
                ]),
                html.Td([
                    html.Span(str(row.get('organization', '')), className='org-name'),
                    html.Br(),
                    html.Span(str(row.get('product', '')), className='product-name')
                ]),
                html.Td(_format_minutes_to_human(row.get('downtime_7d_min'))),
                html.Td(_format_minutes_to_human(row.get('downtime_30d_min'))),
                html.Td(html.Span(status_text, className=f'status-badge {status_class}'))
            ]))

        # Sortierbare Header (einfaches clientseitiges State-Pattern via hidden dcc.Store)
        def sort_header(label, col_key, current, min_width=None):
            is_active = (current.get('by') == col_key)
            asc_active = is_active and current.get('asc', True)
            desc_active = is_active and not current.get('asc', True)
            arrow_style_base = {'border': 'none', 'background': 'transparent', 'cursor': 'pointer', 'padding': '0 4px', 'fontSize': '10px', 'lineHeight': '1'}
            asc_style = arrow_style_base | ({'color': '#60a5fa'} if asc_active else {'color': 'inherit'})
            desc_style = arrow_style_base | ({'color': '#60a5fa'} if desc_active else {'color': 'inherit'})
            th_style = {'whiteSpace': 'nowrap', 'verticalAlign': 'middle', 'paddingRight': '8px', 'paddingLeft': '8px', 'minWidth': min_width or 'auto'}
            return html.Th([
                html.Span(label),
                html.Span([
                    html.Button('▲', id={'type': 'ci-sort', 'col': col_key, 'dir': 'asc'}, n_clicks=0, style=asc_style, className='table-sort-btn'),
                    html.Button('▼', id={'type': 'ci-sort', 'col': col_key, 'dir': 'desc'}, n_clicks=0, style=desc_style, className='table-sort-btn')
                ], style={'float': 'right', 'display': 'inline-flex', 'gap': '2px'})
            ], style=th_style)

        header = html.Thead([
            html.Tr([
                sort_header('CI', 'ci', sort_state or {}, min_width='120px'),
                sort_header('Organisation · Produkt', 'organization', sort_state or {}, min_width='260px'),
                sort_header('Down 7 Tage', 'downtime_7d_min', sort_state or {}, min_width='140px'),
                sort_header('Down 30 Tage', 'downtime_30d_min', sort_state or {}, min_width='140px'),
                sort_header('Status', 'current_availability', sort_state or {}, min_width='120px')
            ])
        ])
        table = html.Table([
            header,
            html.Tbody(rows)
        ], className='incidents-table')

        return table
    except Exception as e:
        return html.Div(f'Fehler beim Laden der CI-Tabelle: {str(e)}', style={'color': 'red'})


# Sortier-Callback: toggelt Sortierzustand bei Header-Klicks
@callback(
    Output('ci-sort-state', 'data'),
    Input({'type': 'ci-sort', 'col': ALL, 'dir': ALL}, 'n_clicks'),
    State('ci-sort-state', 'data'),
    prevent_initial_call=True
)
def toggle_ci_sort(_clicks, state):
    ctx = dash.callback_context
    state = state or {'by': 'ci', 'asc': True}
    if not ctx.triggered:
        return state
    trig = ctx.triggered[0]['prop_id'].split('.')[0]
    try:
        obj = json.loads(trig)
        col = obj.get('col')
        direction = obj.get('dir')
    except Exception:
        return state
    if not col or direction not in ('asc', 'desc'):
        return state
    return {'by': col, 'asc': direction == 'asc'}


# Heatmap Callback (mit einfachem Cache im Store)
@callback(
    [Output('incident-heatmap-cache', 'data'), Output('incident-heatmap', 'figure')],
    [Input('incident-heatmap-refresh', 'n_intervals')],
    [State('incident-heatmap-cache', 'data')],
    prevent_initial_call=False
)
def render_incident_heatmap(_tick, cache_data):
    try:
        import pandas as _pd
        # Cache-Struktur: { 'ts': epoch, 'data': [{weekday,hour,count,ci_list}, ...] }
        df = None
        if cache_data and isinstance(cache_data, dict) and 'data' in cache_data:
            try:
                df = _pd.DataFrame(cache_data['data'])
            except Exception:
                df = None
        refresh_df = False
        if df is None or df.empty:
            refresh_df = True
        else:
            # Optional: Cache Expiry (15 Min)
            try:
                import time as _time
                ts = float(cache_data.get('ts', 0))
                refresh_df = (_time.time() - ts) > 900
            except Exception:
                refresh_df = True
        # Zusätzlich: falls beim App-Start eine vorab generierte Datei existiert, als initialen Cache laden
        if (df is None or df.empty) and not refresh_df:
            try:
                import os as _os, json as _json
                _hm_path = _os.path.join(_os.path.dirname(__file__), '..', 'data', 'incident_heatmap.json')
                if _os.path.exists(_hm_path):
                    with open(_hm_path, 'r', encoding='utf-8') as _f:
                        file_cache = _json.load(_f)
                    if file_cache and isinstance(file_cache, dict) and 'data' in file_cache:
                        df = _pd.DataFrame(file_cache['data'])
                        cache_data = file_cache
            except Exception:
                pass
        if refresh_df:
            df = get_incident_heatmap_data(30)
        # Achsen-Labels fest definieren
        hours = list(range(0,24))
        x_labels = [f"{h:02d}:00" for h in hours]
        wdays = ['Mo','Di','Mi','Do','Fr','Sa','So']

        # Zellen initialisieren (immer), damit Achsen korrekt sind
        z = [[0 for _ in hours] for _ in wdays]
        text = [["" for _ in hours] for _ in wdays]
        if df is None:
            df = _pd.DataFrame(columns=['weekday','hour','count','ci_list'])

        # Datentypen erzwingen und Labels bilden
        weekday_labels = {1:'Mo',2:'Di',3:'Mi',4:'Do',5:'Fr',6:'Sa',7:'So'}
        try:
            df['weekday'] = _pd.to_numeric(df.get('weekday'), errors='coerce').fillna(0).astype(int)
            df['hour'] = _pd.to_numeric(df.get('hour'), errors='coerce').fillna(-1).astype(int)
            df['count'] = _pd.to_numeric(df.get('count'), errors='coerce').fillna(0).astype(int)
        except Exception:
            pass
        df['wlabel'] = df['weekday'].map(weekday_labels)

        # Tooltip-Text: Anzahl + Beispiel-CIs
        def tip(row):
            cis = row.get('ci_list') or []
            preview = ', '.join([str(c) for c in cis[:8]])
            extra = '' if len(cis) <= 8 else f" …(+{len(cis)-8})"
            return f"{row['wlabel']} {int(row['hour']):02d}:00\nIncidents: {int(row['count'])}\nCIs: {preview}{extra}"

        if not df.empty:
            try:
                df['tooltip'] = df.apply(tip, axis=1)
                # Pivot über Pandas (robust)
                pv = df.pivot_table(index='wlabel', columns='hour', values='count', aggfunc='sum', fill_value=0)
                pv = pv.reindex(index=wdays, columns=hours, fill_value=0)
                z = pv.values.tolist()
                tool = df.pivot_table(index='wlabel', columns='hour', values='tooltip', aggfunc='first')
                tool = tool.reindex(index=wdays, columns=hours)
                text = tool.fillna("").values.tolist()
            except Exception:
                pass

        # Farbenbereich an reale Daten anpassen
        # Maxwert aus Matrix berechnen (robuster)
        max_count = max([max(row) if row else 0 for row in z]) if z else 0
        fig = go.Figure(data=go.Heatmap(
            z=z,
            x=x_labels,  # 0-23
            y=wdays,     # Mo-So
            colorscale='YlOrRd',
            hoverinfo='text',
            text=text,
            colorbar=dict(title='Incidents'),
            zmin=0,
            zmax=max_count if max_count > 0 else 1
        ))
        fig.update_layout(
            height=360,
            margin=dict(l=40,r=20,t=30,b=40),
            xaxis=dict(title='Stunde', type='category', categoryorder='array', categoryarray=x_labels),
            yaxis=dict(title='Wochentag', type='category', categoryorder='array', categoryarray=wdays),
            # Make backgrounds transparent so CSS can provide proper light/dark contrast
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)'
        )
        # Neues Cache-Paket bauen
        try:
            import time as _time
            cache_out = {'ts': _time.time(), 'data': df[['weekday','hour','count','ci_list']].to_dict('records')}
        except Exception:
            cache_out = cache_data
        return cache_out, fig
    except Exception:
        return cache_data, go.Figure(data=[], layout=go.Layout(height=260, margin=dict(l=20,r=20,t=30,b=20)))
