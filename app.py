import dash
from dash import Dash, html, dcc, Input, Output, callback
from mylibrary import *
import yaml
import os
import subprocess
import functools
import time
from flask import jsonify, request, redirect, url_for, Response, abort
from markupsafe import escape
from urllib.parse import urlparse
from io import BytesIO
import re
try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = None
    ImageDraw = None
    ImageFont = None
import hashlib
import secrets
import psutil
import gc

# Run idempotent DB migrations on startup
try:
    run_db_migrations()
except Exception as _e:
    # Avoid blocking startup; errors will be visible in logs
    print(f"DB migration warning: {_e}")

# Ensure initial downtimes exist on startup (DB upsert)
try:
    from cron import update_downtimes_file  # local import to avoid cycles
    update_downtimes_file()
except Exception as _e:
    print(f"Downtimes init warning: {_e}")

# Precompute incident heatmap data at startup to avoid empty initial graph
try:
    from mylibrary import get_incident_heatmap_data
    import json as _json
    import time as _time
    _hm_df = get_incident_heatmap_data(30)
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    os.makedirs(data_dir, exist_ok=True)
    _hm_path = os.path.join(data_dir, 'incident_heatmap.json')
    _payload = {
        'ts': _time.time(),
        'data': (
            _hm_df[['weekday','hour','count','ci_list']]
            .to_dict('records') if _hm_df is not None and hasattr(_hm_df, 'to_dict') else []
        )
    }
    with open(_hm_path, 'w', encoding='utf-8') as _f:
        _json.dump(_payload, _f, ensure_ascii=False)
except Exception as _e:
    print(f"Heatmap init warning: {_e}")

app = Dash(
    __name__,
    use_pages=True,
    title='TI-Stats',
    suppress_callback_exceptions=True,
    meta_tags=[
        {"name": "viewport", "content": "width=device-width, initial-scale=1"},
        {"name": "theme-color", "content": "#0f172a"},
        {"name": "description", "content": "Verfügbarkeit, Statistiken und Benachrichtigungen für TI-Komponenten."},
        {"property": "og:type", "content": "website"},
        {"property": "og:title", "content": "TI-Stats"},
        {"property": "og:description", "content": "Verfügbarkeit, Statistiken und Benachrichtigungen für TI-Komponenten."},
        {"name": "twitter:card", "content": "summary_large_image"}
    ],
    external_scripts=[
        {"src": "https://plausible.elpatron.me/js/script.js", "defer": True, "data-domain": "ti-stats.net"}
    ]
)
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

def get_version_info() -> str:
    """Return a concise version string with Git tag and short commit id.

    Resolution order:
    - Environment variables: TI_VERSION and TI_COMMIT
    - Git (if available): latest tag and short SHA
    - Fallback: "unbekannt"
    """
    # Env first (useful in containerized builds)
    env_version = os.getenv('TI_VERSION')
    env_commit = os.getenv('TI_COMMIT')
    if env_version or env_commit:
        if env_version and env_commit:
            return f"{env_version} ({env_commit[:7]})"
        return env_version or env_commit[:7]

    # Try Git
    try:
        tag = None
        try:
            tag = subprocess.check_output(
                ['git', 'describe', '--tags', '--abbrev=0'], stderr=subprocess.DEVNULL
            ).decode('utf-8').strip()
        except Exception:
            # No tag present; fall back to describe always
            pass

        sha = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'], stderr=subprocess.DEVNULL
        ).decode('utf-8').strip()

        if tag:
            return f"{tag} ({sha})"
        return sha if sha else "unbekannt"
    except Exception:
        return "unbekannt"

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
        
        # home_url entfernt – Logo-Link führt auf Startseite
        app_home_url = '/'
        
        # Get header configurations
        header_title = header_config.get('title', 'TI-Stats')
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
            # Canonical link + location for dynamic updates
            dcc.Location(id='loc'),
            html.Link(id='canonical-link', rel='canonical', href='/'),
            html.Link(rel='me', href='https://mastodon.ti-stats.net/@tistatus'),
            html.Header(children = [
                html.Div(children=[
                    html.Div(id='logo-wrapper', children = [
                        html.A(href=app_home_url, children = [
                            html.Img(id='logo', src=logo_path, alt=logo_alt, height=logo_height, width=logo_width)
                        ])
                    ], style={'display': 'flex', 'alignItems': 'center', 'gap': '12px'}),
                    html.H1(children=header_title, style={'margin': '0', 'fontSize': '1.6rem'})
                ], style={'display': 'flex', 'alignItems': 'center', 'gap': '16px'}),
                # Hamburger-Menü (rechts)
                html.Div(children=[
                    html.Details(children=[
                        html.Summary(
                            html.I(className='material-icons', children='menu'),
                            style={'listStyle': 'none', 'cursor': 'pointer', 'padding': '6px 8px', 'borderRadius': '8px', 'border': '1px solid #e0e0e0'},
                            className='hamburger-menu-trigger'  # Add CSS class for easier identification
                        ),
                        html.Div(id='hamburger-menu-content', children=[
                            html.A(
                                [
                                    html.Span(html.I(className='material-icons', children='home'), style={'marginRight': '10px'}),
                                    html.Span('Start')
                                ],
                                href='/',
                                style={'display': 'flex', 'alignItems': 'center', 'padding': '10px 12px', 'textDecoration': 'none', 'color': '#2c3e50', 'borderRadius': '6px'}
                            ),
                            html.A(
                                [
                                    html.Span(html.I(className='material-icons', children='analytics'), style={'marginRight': '10px'}),
                                    html.Span('Statistiken')
                                ],
                                href='/stats',
                                style={'display': 'flex', 'alignItems': 'center', 'padding': '10px 12px', 'textDecoration': 'none', 'color': '#2c3e50', 'borderRadius': '6px'}
                            ),
                            html.A(
                                [
                                    html.Span(html.I(className='material-icons', children='notifications'), style={'marginRight': '10px'}),
                                    html.Span('Benachrichtigungen')
                                ],
                                href='/notifications',
                                style={'display': 'flex', 'alignItems': 'center', 'padding': '10px 12px', 'textDecoration': 'none', 'color': '#2c3e50', 'borderRadius': '6px'}
                            ),
                            # Admin link (hidden by default, shown for admin users)
                            html.A(
                                [
                                    html.Span(html.I(className='material-icons', children='admin_panel_settings'), style={'marginRight': '10px'}),
                                    html.Span('Admin')
                                ],
                                href='/admin',
                                id='admin-menu-link',
                                style={'display': 'none', 'alignItems': 'center', 'padding': '10px 12px', 'textDecoration': 'none', 'color': '#e74c3c', 'borderRadius': '6px'}
                            )
                        ], style={'position': 'absolute', 'right': '0', 'marginTop': '8px', 'background': '#ffffff', 'border': '1px solid #e0e0e0', 'borderRadius': '10px', 'padding': '8px', 'boxShadow': '0 8px 24px rgba(0,0,0,0.12)', 'minWidth': '220px', 'display': 'grid', 'rowGap': '4px'})
                    ], style={'position': 'relative'})
                ], style={'marginLeft': 'auto'})
            ], style={'display': 'flex', 'alignItems': 'center', 'gap': '16px', 'padding': '8px 12px'}),
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
            html.Div(id = 'footer', children = footer_elements + [
                html.Div(
                    get_version_info(),
                    style={
                        'fontSize': '0.85rem',
                        'color': '#64748b',
                        'marginTop': '6px',
                        'flexBasis': '100%',
                        'textAlign': 'center'
                    }
                )
            ]),
            
            # Global auth status store (used across all pages)
            dcc.Store(id='auth-status', storage_type='local'),
            
            # Visitor tracking script
            html.Script(src='/assets/visitor-tracking.js')
        ])
        
        _layout_cache_timestamp = current_time
        
        # Force garbage collection periodically
        if int(current_time) % 300 == 0:  # Every 5 minutes
            gc.collect()
    
    return _layout_cache

# This is the correct way to set the layout - it should be the function itself, not the result of calling it
app.layout = serve_layout
# ---------------------------------------------------------------------------
# Security hardening: validate Dash update endpoint and set security headers
# ---------------------------------------------------------------------------

_MAX_UPDATE_PAYLOAD_BYTES = int(os.getenv('TI_MAX_UPDATE_PAYLOAD', '1048576'))  # 1 MiB default

def _expected_origin_tuple(req: "request"):
    """Return (scheme, hostname, port) representing the external origin.

    Respects reverse proxy headers X-Forwarded-Proto/Host when present.
    """
    # Prefer proxy headers if provided by frontend proxy (e.g., nginx)
    proto = (req.headers.get('X-Forwarded-Proto') or req.scheme or 'http').split(',')[0].strip()
    xf_host = req.headers.get('X-Forwarded-Host')
    host = (xf_host or req.headers.get('Host') or req.host or '').split(',')[0].strip()
    # Extract hostname and optional port
    if ':' in host:
        hostname, port_str = host.rsplit(':', 1)
        try:
            port = int(port_str)
        except Exception:
            port = 443 if proto == 'https' else 80
    else:
        hostname = host
        port = 443 if proto == 'https' else 80
    return proto, hostname, port

def _same_origin(req: "request") -> bool:
    try:
        origin = req.headers.get('Origin')
        if not origin:
            # Fallback to Referer if Origin missing
            ref = req.headers.get('Referer', '')
            origin = ref if ref else None
        if not origin:
            return True  # allow non-CORS requests (same-origin navigation)
        o = urlparse(origin)
        exp_proto, exp_host, exp_port = _expected_origin_tuple(req)
        o_port = o.port or (443 if o.scheme == 'https' else 80)
        return (o.scheme, o.hostname, o_port) == (exp_proto, exp_host, exp_port)
    except Exception:
        return False

@server.before_request
def _harden_dash_update_component():
    # Only scope to Dash update endpoint
    if request.path != '/_dash-update-component':
        return None

    # Method restriction
    if request.method != 'POST':
        abort(405)

    # Content-Type validation
    ctype = request.headers.get('Content-Type', '')
    if 'application/json' not in ctype:
        abort(415)

    # Same-origin check to prevent CSRF from other sites
    if not _same_origin(request):
        abort(403)

    # Size limit
    clen = request.content_length or 0
    if clen > _MAX_UPDATE_PAYLOAD_BYTES:
        abort(413)

    # Basic payload validation (shape & limits) – keep permissive for Dash
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400)

    # Known Dash keys
    allowed_keys = {
        'output', 'outputs', 'inputs', 'state', 'changedPropIds',
        'triggered', 'callback_context', 'outputs_list'
    }
    # Reject clearly unexpected structures (but allow unknown extras up to a small limit)
    if len([k for k in data.keys() if k not in allowed_keys]) > 3:
        abort(400)

    # Limit list sizes to mitigate abuse
    for key in ('inputs', 'state', 'outputs'):
        val = data.get(key)
        if isinstance(val, list) and len(val) > 500:
            abort(400)

    return None

@server.after_request
def _set_security_headers(resp: Response):
    try:
        resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
        resp.headers.setdefault('X-Frame-Options', 'DENY')
        resp.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        resp.headers.setdefault('Permissions-Policy', 'geolocation=(), microphone=(), camera=()')
        # Basic CSP tuned for Dash/Plotly usage
        csp = (
            "default-src 'self'; "
            "img-src 'self' data: blob: https:; "
            "style-src 'self' 'unsafe-inline' https:; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https:; "
            "font-src 'self' https: data:; "
            "connect-src 'self' https: data:; "
            "frame-ancestors 'none'"
        )
        resp.headers.setdefault('Content-Security-Policy', csp)
        # HSTS only when behind https
        if request.is_secure:
            resp.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
    except Exception:
        pass
    return resp


"""
Clientseitiger Callback, um den Canonical-Link dynamisch anhand der aktuellen URL zu setzen.
"""
dash.clientside_callback(
    """
    function(pathname) {
      try {
        var u = new URL(window.location.href);
        var href = u.origin + u.pathname + u.search; // garantiert korrekt encodiert
        var el = document.querySelector("link[rel='canonical']") || document.getElementById('canonical-link');
        if (el) { el.setAttribute('href', href); }
      } catch(e) {}
      return '';
    }
    """,
    Output('footer', 'title'),  # Dummy-Output
    Input('loc', 'pathname'),
    prevent_initial_call=False
)

# ----------------------------------------------------------------------------
# SEO: Robots.txt & Sitemap.xml
# ----------------------------------------------------------------------------
@server.route('/robots.txt')
def robots_txt():
    base = request.url_root.rstrip('/')
    content = f"""
User-agent: *
Allow: /
Sitemap: {base}/sitemap.xml
""".strip() + "\n"
    return Response(content, mimetype='text/plain')


@server.route('/sitemap.xml')
def sitemap_xml():
    from datetime import datetime
    base = request.url_root.rstrip('/')
    pages = [
        ("/", "weekly"),
        ("/stats", "daily"),
        ("/notifications", "weekly"),
        ("/plot", "daily"),
    ]
    # Include CI detail pages directly as final target URL /plot?ci=<ci>
    try:
        df = get_timescaledb_ci_data()
        if df is not None and hasattr(df, 'empty') and not df.empty and 'ci' in df.columns:
            # Limit to avoid huge sitemaps
            ci_values = df['ci'].dropna().astype(str).unique().tolist()[:1000]
            for ci in ci_values:
                # Vorsicht: sitemap ist XML – CI-Wert wird nicht als HTML dargestellt
                pages.append((f"/plot?ci={ci}", "hourly"))
    except Exception:
        # Fail silently; base pages are still provided
        pass
    lastmod = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    urls = "".join([
        f"<url><loc>{base}{path}</loc><changefreq>{freq}</changefreq><lastmod>{lastmod}</lastmod></url>"
        for path, freq in pages
    ])
    xml = f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n" \
          f"<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">{urls}</urlset>\n"
    return Response(xml, mimetype='application/xml')


# ----------------------------------------------------------------------------
# SEO: Pretty URL Redirect /ci/<ci> -> /plot?ci=<ci>
# ----------------------------------------------------------------------------
@server.route('/ci/<path:ci>')
def ci_redirect(ci: str):
    # Only allow a conservative subset in CI to avoid reflected content in redirects
    # Keep alnum, dash, underscore, dot and colon
    allowed = ('-', '_', '.', ':')
    safe_ci = ''.join([c for c in ci if c.isalnum() or c in allowed])
    return redirect(f"/plot?ci={escape(safe_ci)}", code=301)


# ----------------------------------------------------------------------------
# SEO: Dynamic Open Graph Image (1200x630) – /og-image.png
# ----------------------------------------------------------------------------
@server.route('/og-image.png')
def og_image():
    """Generate a branded OG image.

    Query params:
    - title: main title text
    - subtitle: secondary line
    - ci: configuration item id (shown as badge)
    """
    try:
        width, height = 1200, 630
        title = request.args.get('title', 'TI-Stats')
        subtitle = request.args.get('subtitle', 'Verfügbarkeit und Statistiken der TI-Komponenten')
        ci = request.args.get('ci')
        hours = int(request.args.get('hours', '24'))

        if Image is None:
            # Fallback static response when Pillow is unavailable
            return Response(b'', mimetype='image/png', status=204)

        # Background
        img = Image.new('RGB', (width, height), '#0f172a')  # slate-900
        draw = ImageDraw.Draw(img)

        # Simple radial-like vignette
        try:
            # Overlay gradient rectangles for subtle depth
            for i in range(0, height, 10):
                opacity = int(120 * (1 - i / height))
                color = (30, 41, 59, max(0, opacity))  # slate-800 alpha
                overlay = Image.new('RGBA', (width, 10), color)
                img.paste(overlay, (0, i), overlay)
        except Exception:
            pass

        # Load fonts (fallback to default)
        def load_font(preferred: str, size: int):
            try:
                return ImageFont.truetype(preferred, size)
            except Exception:
                return None

        font_bold = (
            load_font('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 120)
            or ImageFont.load_default()
        )
        font_reg = (
            load_font('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 42)
            or ImageFont.load_default()
        )
        font_badge = (
            load_font('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 42)
            or ImageFont.load_default()
        )

        # Measurement helper for accurate width/height
        def measure(draw_obj, text, font):
            try:
                x0, y0, x1, y1 = draw_obj.textbbox((0, 0), text, font=font)
                return (x1 - x0, y1 - y0)
            except Exception:
                return draw_obj.textsize(text, font=font)

        # Optional logo (favicon.png)
        try:
            assets_path = os.path.join(os.path.dirname(__file__), 'assets', 'favicon.png')
            if os.path.exists(assets_path):
                logo = Image.open(assets_path).convert('RGBA')
                logo = logo.resize((128, 128))
                img.paste(logo, (64, 64), logo)
        except Exception:
            pass

        # Title/subtitle positions
        text_x = 220
        text_y = 64
        draw.text((text_x, text_y), title, font=font_bold, fill='#e2e8f0')  # slate-200
        draw.text((text_x, text_y + 120), subtitle, font=font_reg, fill='#94a3b8')  # slate-400

        # CI badge + metrics (keep original spacing roughly)
        metrics_y = text_y + 200
        if ci:
            badge_text = f"CI: {ci}"
            # Measure text size
            tw, th = measure(draw, badge_text, font_badge)
            pad_x, pad_y = 22, 14
            bx, by = text_x, metrics_y
            bw, bh = tw + pad_x * 2, th + pad_y * 2
            # Rounded rectangle background
            try:
                from PIL import ImageDraw as _ID
                draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=14, fill='#1e293b')  # slate-800
            except Exception:
                draw.rectangle([bx, by, bx + bw, by + bh], fill='#1e293b')
            draw.text((bx + pad_x, by + pad_y), badge_text, font=font_badge, fill='#93c5fd')  # blue-300

            # Fetch metrics from DB (best-effort)
            try:
                import pandas as _pd
                from datetime import timedelta as _td
                with get_db_conn() as conn:
                    with conn.cursor() as cur:
                        # Pull last N hours measurements for specific CI
                        cur.execute("""
                            SELECT ts, status
                            FROM measurements
                            WHERE ci = %s AND ts >= NOW() - INTERVAL %s
                            ORDER BY ts ASC
                        """, (ci, f"{int(max(1, hours))} hours",))
                        rows = cur.fetchall()
                df = _pd.DataFrame(rows, columns=['ts', 'status']) if rows else _pd.DataFrame(columns=['ts','status'])
                availability = 0.0
                incidents = 0
                mttr_min = 0.0
                mtbf_hr = 0.0
                if not df.empty:
                    df['ts'] = _pd.to_datetime(df['ts'])
                    df['status'] = df['status'].astype(int)
                    # Availability percent
                    availability = float(df['status'].mean() * 100.0)
                    # Incidents: 1->0 transitions
                    df['prev'] = df['status'].shift(1)
                    incidents = int(((df['prev'] == 1) & (df['status'] == 0)).sum())
                    # MTTR/MTBF (rough estimation): compute durations of 0 and 1 segments
                    df['grp'] = (df['status'] != df['status'].shift(1)).cumsum()
                    seg = df.groupby('grp').agg(start=('ts','min'), end=('ts','max'), val=('status','first'))
                    seg['dur_min'] = (seg['end'] - seg['start']).dt.total_seconds() / 60.0
                    total_downtime = seg.loc[seg['val'] == 0, 'dur_min'].sum() if not seg.empty else 0.0
                    total_uptime = seg.loc[seg['val'] == 1, 'dur_min'].sum() if not seg.empty else 0.0
                    num_outages = max(1, len(seg.loc[seg['val'] == 0])) if not seg.empty else 1
                    num_uptimes = max(1, len(seg.loc[seg['val'] == 1])) if not seg.empty else 1
                    mttr_min = float(total_downtime / num_outages)
                    mtbf_hr = float((total_uptime / num_uptimes) / 60.0)

                # Render metrics block
                metrics_lines = [
                    f"Verfügbarkeit {hours}h: {availability:.2f}%",
                    f"Incidents: {incidents}",
                    f"MTTR: {mttr_min:.1f} Min",
                    f"MTBF: {mtbf_hr:.1f} Std",
                ]
                line_y = by + bh + 28
                line_gap = 56
                for line in metrics_lines:
                    draw.text((text_x, line_y), line, font=font_reg, fill='#cbd5e1')
                    line_y += line_gap
            except Exception:
                # Non-fatal
                pass

        # Footer brand
        draw.text((64, height - 64), 'ti-stats.net', font=font_reg, fill='#64748b')  # slate-500

        # Output
        buf = BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        resp = Response(buf.getvalue(), mimetype='image/png')
        resp.headers['Cache-Control'] = 'public, max-age=600'
        return resp
    except Exception:
        # Avoid reflecting query parameters in error text
        return Response("Error generating image", mimetype='text/plain', status=500)

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
        
        # Database health
        db_status = "healthy"
        db_error = None
        try:
            with get_db_conn() as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
                _ = cur.fetchone()
        except Exception as e:
            db_status = "unhealthy"
            db_error = str(e)
        
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
                },
                "database": {
                    "status": db_status,
                    "error": db_error
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

# Unsubscribe endpoint
@server.route('/unsubscribe/<token>')
def unsubscribe(token):
    """Unsubscribe endpoint.

    - Ohne Query-Param entfernt der Endpoint das gesamte Profil (Bestand).
    - Mit Query-Param u=<hash> wird nur die einzelne Apprise-URL am Hash gelöscht.
    """
    try:
        # Query-Param für per-URL-Opt-Out
        url_hash = request.args.get('u')
        
        # Get profile by token
        profile = get_profile_by_unsubscribe_token(token)
        if not profile:
            return '''
            <!DOCTYPE html>
            <html>
            <head><title>Ungültiger Link</title></head>
            <body>
                <h2>Ungültiger Link</h2>
                <p>Der von dir aufgerufene Link ist ungültig oder wurde bereits verwendet.</p>
            </body>
            </html>
            ''', 404
        
        profile_id, user_id, name, email_notifications, email_address = profile

        # Per-URL-Opt-Out
        if url_hash:
            if remove_apprise_url_by_token_and_hash(token, url_hash):
                safe_name = escape(name)
                return f'''
                <!DOCTYPE html>
                <html>
                <head><title>Kanal abgemeldet</title></head>
                <body>
                    <h2>Kanal abgemeldet</h2>
                    <p>Die ausgewählte Benachrichtigungs‑URL wurde erfolgreich aus dem Profil "{safe_name}" entfernt.</p>
                    <p>Du kannst die übrigen Kanäle in den <a href="/notifications">Benachrichtigungseinstellungen</a> verwalten.</p>
                </body>
                </html>
                ''', 200
            else:
                return '''
                <!DOCTYPE html>
                <html>
                <head><title>Nichts zu entfernen</title></head>
                <body>
                    <h2>Nichts zu entfernen</h2>
                    <p>Die angegebene URL konnte nicht gefunden werden. Der Link ist möglicherweise abgelaufen oder bereits verwendet.</p>
                </body>
                </html>
                ''', 404

        # Profil-Opt-Out (Bestand)
        if delete_profile_by_unsubscribe_token(token):
            safe_name = escape(name)
            return f'''
            <!DOCTYPE html>
            <html>
            <head><title>Abmeldung erfolgreich</title></head>
            <body>
                <h2>Abmeldung erfolgreich</h2>
                <p>Das Benachrichtigungsprofil "{safe_name}" wurde erfolgreich gelöscht.</p>
                <p>Du erhältst keine weiteren Benachrichtigungen von diesem Profil.</p>
            </body>
            </html>
            ''', 200
        else:
            return '''
            <!DOCTYPE html>
            <html>
            <head><title>Fehler bei der Abmeldung</title></head>
            <body>
                <h2>Fehler bei der Abmeldung</h2>
                <p>Beim Löschen des Profils ist ein Fehler aufgetreten. Bitte versuche es später erneut.</p>
            </body>
            </html>
            ''', 500
            
    except Exception as e:
        return f'''
        <!DOCTYPE html>
        <html>
        <head><title>Fehler</title></head>
        <body>
            <h2>Fehler</h2>
            <p>Ein Fehler ist aufgetreten: {str(e)}</p>
        </body>
        </html>
        ''', 500

# API endpoint for requesting OTP
@server.route('/api/auth/otp/request', methods=['POST'])
def request_otp():
    """Request OTP for email"""
    try:
        data = request.get_json()
        email = data.get('email')
        
        if not email:
            return jsonify({'error': 'E-Mail-Adresse ist erforderlich'}), 400
        
        # Validate email format
        if '@' not in email or '.' not in email:
            return jsonify({'error': 'Ungültige E-Mail-Adresse'}), 400
        
        # Check if user exists, create if not
        user = get_user_by_email(email)
        if user:
            user_id = user[0]
        else:
            user_id = create_user(email)
        
        if not user_id:
            return jsonify({'error': 'Fehler beim Erstellen des Benutzers'}), 500
        
        # Generate OTP
        otp, otp_id = generate_otp_for_user(user_id, request.remote_addr)
        
        if not otp or not otp_id:
            return jsonify({'error': 'Fehler beim Generieren des OTP-Codes'}), 500
        
        # Send OTP via Apprise (using the template from config)
        config = load_config()
        otp_template = config.get('core', {}).get('otp_apprise_url_template')
        
        if not otp_template:
            return jsonify({'error': 'OTP-Template nicht konfiguriert'}), 500
        
        # Debug: Check values before formatting
        print(f"Debug: email={email}, otp={otp}, template={otp_template}")
        
        # Ensure email and otp are strings
        if not email or not otp:
            return jsonify({'error': 'E-Mail oder OTP ist leer'}), 500
        
        try:
            # Format the template with user email and OTP
            apprise_url = otp_template.format(email=str(email), otp=str(otp))
            
            # Send OTP notification
            apobj = apprise.Apprise()
            apobj.add(apprise_url)
            apobj.notify(
                title='TI-Stats OTP-Code',
                body=f'Ihr OTP-Code für TI-Stats lautet: {otp}\n\nDieser Code ist 10 Minuten gültig.',
                body_format=apprise.NotifyFormat.TEXT
            )
        except Exception as e:
            return jsonify({'error': f'Fehler beim Formatieren der Apprise-URL: {str(e)}'}), 500
        
        return jsonify({'message': 'OTP-Code wurde gesendet'}), 200
        
    except Exception as e:
        return jsonify({'error': f'Fehler beim Senden des OTP-Codes: {str(e)}'}), 500

# API endpoint for validating OTP
@server.route('/api/auth/otp/validate', methods=['POST'])
def validate_otp_api():
    """Validate OTP code"""
    try:
        data = request.get_json()
        email = data.get('email')
        otp_code = data.get('otp')
        
        if not email or not otp_code:
            return jsonify({'error': 'E-Mail und OTP-Code sind erforderlich'}), 400
        
        # Get user by email
        user = get_user_by_email(email)
        if not user:
            return jsonify({'error': 'Benutzer nicht gefunden'}), 404
        
        user_id = user[0]
        
        # Check if account is locked
        if is_account_locked(user_id):
            return jsonify({'error': 'Konto ist gesperrt. Bitte versuche es später erneut.'}), 423
        
        # Validate OTP
        if validate_otp(user_id, otp_code):
            # Authentication successful
            return jsonify({
                'message': 'Authentifizierung erfolgreich',
                'user_id': user_id,
                'email': email
            }), 200
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
                    return jsonify({'error': 'Zu viele fehlgeschlagene Versuche. Konto ist jetzt gesperrt.'}), 423
            
            return jsonify({'error': 'Ungültiger OTP-Code'}), 401
            
    except Exception as e:
        return jsonify({'error': f'Fehler bei der Verifizierung: {str(e)}'}), 500

# API endpoint for logout
@server.route('/api/auth/logout', methods=['POST'])
def logout():
    """End user session"""
    # In a session-based implementation, we would clear the session here
    # For now, we just return a success message
    return jsonify({'message': 'Erfolgreich abgemeldet'}), 200

# API endpoint for listing user profiles
@server.route('/api/profiles', methods=['GET'])
def list_profiles():
    """List user profiles"""
    # In a real implementation, we would check authentication here
    # For now, we'll just return an empty list
    return jsonify([]), 200

# API endpoint for tracking page views
@server.route('/api/track', methods=['POST'])
def track_page_view():
    """Track a page view for visitor statistics"""
    try:
        data = request.get_json()
        if not data or 'page' not in data:
            return jsonify({'error': 'Missing page parameter'}), 400
        
        page = str(data['page'])
        session_id = data.get('session_id')
        user_agent = str(data.get('user_agent', ''))
        referrer = data.get('referrer')

        # Sanitize inputs: allow only safe URL/path characters and limit length
        def _sanitize(s: str, max_len: int = 512) -> str:
            if not isinstance(s, str):
                s = str(s)
            s = s[:max_len]
            # remove control characters
            s = re.sub(r"[\x00-\x1f\x7f]", "", s)
            # keep a conservative set of URL characters
            return re.sub(r"[^A-Za-z0-9_\-\./:?&=%#]", "", s)

        page = _sanitize(page, 256)
        user_agent = _sanitize(user_agent, 256)
        referrer = _sanitize(referrer or '', 512) or None
        
        # Generate session ID if not provided
        if not session_id:
            session_id = secrets.token_urlsafe(32)
        
        # Hash user agent for privacy
        user_agent_hash = None
        if user_agent:
            user_agent_hash = hashlib.sha256(user_agent.encode()).hexdigest()[:16]
        
        # Log the page view
        log_page_view(page, session_id, user_agent_hash, referrer)
        
        return jsonify({'session_id': session_id, 'status': 'tracked'}), 200
        
    except Exception as e:
        print(f"Error tracking page view: {e}")
        return jsonify({'error': 'Internal server error'}), 500

# Callback to show/hide admin link in hamburger menu
@callback(
    Output('admin-menu-link', 'style'),
    [Input('auth-status', 'data')],
    prevent_initial_call=False
)
def toggle_admin_menu_link(auth_data):
    """Show admin link only for authenticated admin users"""
    if not auth_data or not auth_data.get('authenticated'):
        return {'display': 'none'}
    
    user_email = auth_data.get('email', '')
    if is_admin_user(user_email):
        return {'display': 'flex', 'alignItems': 'center', 'padding': '10px 12px', 'textDecoration': 'none', 'color': '#e74c3c', 'borderRadius': '6px'}
    else:
        return {'display': 'none'}

# Pages are automatically registered via dash.register_page in their respective files

if __name__ == '__main__':
    app.run(debug=False)