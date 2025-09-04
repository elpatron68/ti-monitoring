import dash
from dash import Dash, html, dcc
from mylibrary import *
import yaml
import os
import functools
import time
from flask import jsonify, request, make_response
import apprise
import psutil
import gc

app = Dash(__name__, use_pages=True, title='TI-Monitoring', suppress_callback_exceptions=True)
# Dash: erlaubte Initial-Duplicates für Callbacks mit allow_duplicate
app.config.prevent_initial_callbacks = 'initial_duplicate'
server = app.server

# Pages werden automatisch von Dash geladen (use_pages=True)

# Debug endpoint to inspect registered pages
@server.route('/debug/pages')
def debug_pages():
    try:
        return jsonify({'pages': list(dash.page_registry.keys())})
    except Exception as e:
        return make_response(jsonify({'error': str(e)}), 500)

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

def build_layout(*args, **kwargs):
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
        header_title = header_config.get('title', 'TI-Monitoring')
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
        
        # Debug: log registered pages once
        try:
            import logging as _logging
            _logging.getLogger("pages").setLevel(_logging.INFO)
            _logging.getLogger("pages").info("Registered pages: %s", list(dash.page_registry.keys()))
        except Exception:
            pass

        # Create layout
        _layout_cache = html.Div([
            html.Header(children = [
                html.Div(id='logo-wrapper', children = [
                    html.A(href=app_home_url, children = [
                        html.Img(id='logo', src=logo_path, alt=logo_alt, height=logo_height, width=logo_width)
                    ])
                ]),
                html.H1(children=header_title),
                # Add navigation links with Material icons
                html.Nav(children=[
                    html.A(html.I(className='material-icons', children='home'), href='/', className='nav-icon'),
                    html.A(html.I(className='material-icons', children='analytics'), href='/stats', className='nav-icon'),
                    html.A(html.I(className='material-icons', children='notifications'), href='/notifications', className='nav-icon'),
                    html.A(html.I(className='material-icons', children='description'), href='/logs', className='nav-icon')
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
            html.Div(id = 'footer', children = footer_elements)
        ])
        
        _layout_cache_timestamp = current_time
        
        # Force garbage collection periodically
        if int(current_time) % 300 == 0:  # Every 5 minutes
            gc.collect()
    
    return _layout_cache

# This is the correct way to set the layout - it should be the function itself, not the result of calling it
app.layout = build_layout

 

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
            layout = build_layout()
            if not layout:
                layout_status = "warning"
                layout_error = "Empty layout"
        except Exception as e:
            layout_status = "unhealthy"
            layout_error = str(e)
        
        # System metrics
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        
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

# --- MVP API stubs (Auth & Notifications) ---

@server.route('/api/auth/request_otp', methods=['POST'])
def api_request_otp():
    try:
        data = request.get_json(force=True) or {}
        email = (data.get('email') or '').strip().lower()
        if not email:
            return make_response(jsonify({'error': 'email required'}), 400)
        try:
            init_user_notifications_schema()
        except Exception:
            pass
        code = create_otp_for_user(email)
        # Versand per Apprise (konfigurierbar)
        core_cfg = load_core_config()
        otp_tpl = (core_cfg or {}).get('otp_apprise_url_template')
        if not otp_tpl:
            # Dev-Fallback (Resend): resend://TOKEN:from@example.com/{email}
            otp_tpl = 'resend://REDACTED:ti-mon@ypex.online/{email}'
        apprise_url = otp_tpl.replace('{email}', email)
        apobj = apprise.Apprise()
        if apobj.add(apprise_url):
            apobj.notify(
                title='Ihr Anmeldecode',
                body=f'Ihr Einmalcode lautet: {code} (gültig 10 Minuten)',
                body_format=apprise.NotifyFormat.TEXT
            )
        else:
            print(f"WARN: Konnte Apprise-URL nicht hinzufügen: {apprise_url}")
        return jsonify({'status': 'ok'})
    except Exception as e:
        return make_response(jsonify({'error': str(e)}), 500)

@server.route('/api/auth/session', methods=['GET'])
def api_session_status():
    try:
        session_id = request.cookies.get('session_id')
        user_id = get_user_id_by_session(session_id) if session_id else None
        if user_id:
            return jsonify({'status': 'ok'})
        return make_response(jsonify({'error': 'unauthorized'}), 401)
    except Exception as e:
        return make_response(jsonify({'error': str(e)}), 500)

@server.route('/api/auth/verify_otp', methods=['POST'])
def api_verify_otp():
    try:
        data = request.get_json(force=True) or {}
        email = (data.get('email') or '').strip().lower()
        code = (data.get('code') or '').strip()
        if not email or not code:
            return make_response(jsonify({'error': 'email and code required'}), 400)
        session_id = verify_otp_and_create_session(email, code)
        if not session_id:
            return make_response(jsonify({'error': 'invalid_or_expired_code'}), 401)
        resp = make_response(jsonify({'status': 'ok'}))
        resp.set_cookie('session_id', session_id, httponly=True, samesite='Lax')
        return resp
    except Exception as e:
        return make_response(jsonify({'error': str(e)}), 500)

@server.route('/api/account', methods=['DELETE'])
def api_delete_account():
    try:
        session_id = request.cookies.get('session_id')
        user_id = get_user_id_by_session(session_id) if session_id else None
        if not user_id:
            return make_response(jsonify({'error': 'unauthorized'}), 401)
        with get_db_conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE users SET deleted_at=NOW() WHERE id=%s", (user_id,))
            conn.commit()
        resp = make_response(jsonify({'status': 'ok'}))
        resp.delete_cookie('session_id')
        return resp
    except Exception as e:
        return make_response(jsonify({'error': str(e)}), 500)

@server.route('/api/notifications/profiles', methods=['GET','POST'])
def api_profiles():
    session_id = request.cookies.get('session_id')
    user_id = get_user_id_by_session(session_id) if session_id else None
    if not user_id:
        return make_response(jsonify({'error': 'unauthorized'}), 401)
    try:
        with get_db_conn() as conn, conn.cursor() as cur:
            if request.method == 'GET':
                cur.execute(
                    "SELECT id, name, type, created_at FROM notification_profiles WHERE user_id=%s ORDER BY id DESC",
                    (user_id,)
                )
                rows = cur.fetchall()
                items = [
                    {'id': r[0], 'name': r[1], 'type': r[2], 'created_at': r[3].isoformat() if r[3] else None}
                    for r in rows
                ]
                return jsonify(items)
            else:
                data = request.get_json(force=True) or {}
                name = (data.get('name') or '').strip()
                ntype = (data.get('type') or 'whitelist').strip()
                if not name or ntype not in ('whitelist','blacklist'):
                    return make_response(jsonify({'error': 'invalid_payload'}), 400)
                cur.execute(
                    "INSERT INTO notification_profiles(user_id, name, type) VALUES(%s,%s,%s) RETURNING id",
                    (user_id, name, ntype)
                )
                pid = cur.fetchone()[0]
                conn.commit()
                return jsonify({'id': pid, 'name': name, 'type': ntype})
    except Exception as e:
        return make_response(jsonify({'error': str(e)}), 500)

@server.route('/api/notifications/profiles/<int:profile_id>', methods=['GET','PUT','DELETE'])
def api_profile_detail(profile_id: int):
    session_id = request.cookies.get('session_id')
    user_id = get_user_id_by_session(session_id) if session_id else None
    if not user_id:
        return make_response(jsonify({'error': 'unauthorized'}), 401)
    try:
        with get_db_conn() as conn, conn.cursor() as cur:
            if request.method == 'GET':
                cur.execute(
                    "SELECT id, name, type, created_at FROM notification_profiles WHERE id=%s AND user_id=%s",
                    (profile_id, user_id)
                )
                r = cur.fetchone()
                if not r:
                    return make_response(jsonify({'error': 'not_found'}), 404)
                return jsonify({'id': r[0], 'name': r[1], 'type': r[2], 'created_at': r[3].isoformat() if r[3] else None})
            elif request.method == 'PUT':
                data = request.get_json(force=True) or {}
                name = (data.get('name') or '').strip()
                ntype = (data.get('type') or '').strip()
                if ntype and ntype not in ('whitelist','blacklist'):
                    return make_response(jsonify({'error': 'invalid_payload'}), 400)
                sets = []
                vals = []
                if name:
                    sets.append('name=%s'); vals.append(name)
                if ntype:
                    sets.append('type=%s'); vals.append(ntype)
                if not sets:
                    return jsonify({'status': 'noop'})
                vals.extend([profile_id, user_id])
                cur.execute(f"UPDATE notification_profiles SET {', '.join(sets)} WHERE id=%s AND user_id=%s", tuple(vals))
                conn.commit()
                return jsonify({'status': 'ok'})
            else:
                cur.execute("DELETE FROM notification_profiles WHERE id=%s AND user_id=%s", (profile_id, user_id))
                conn.commit()
                return jsonify({'status': 'ok'})
    except Exception as e:
        return make_response(jsonify({'error': str(e)}), 500)

@server.route('/api/notifications/destinations', methods=['GET','POST'])
def api_destinations():
    session_id = request.cookies.get('session_id')
    user_id = get_user_id_by_session(session_id) if session_id else None
    if not user_id:
        return make_response(jsonify({'error': 'unauthorized'}), 401)
    try:
        with get_db_conn() as conn, conn.cursor() as cur:
            if request.method == 'GET':
                profile_id = request.args.get('profile_id', type=int)
                if not profile_id:
                    return make_response(jsonify({'error': 'profile_id required'}), 400)
                # ensure ownership
                cur.execute("SELECT 1 FROM notification_profiles WHERE id=%s AND user_id=%s", (profile_id, user_id))
                if not cur.fetchone():
                    return make_response(jsonify({'error': 'not_found'}), 404)
                cur.execute(
                    "SELECT id, provider, config_encrypted, created_at FROM destinations WHERE profile_id=%s ORDER BY id DESC",
                    (profile_id,)
                )
                rows = cur.fetchall()
                items = []
                for r in rows:
                    # MVP: config redacted
                    items.append({'id': r[0], 'provider': r[1], 'created_at': r[3].isoformat() if r[3] else None, 'config_preview': True})
                return jsonify(items)
            else:
                data = request.get_json(force=True) or {}
                profile_id = data.get('profile_id')
                provider = (data.get('provider') or '').strip()
                cfg = data.get('config') or {}
                if not profile_id or not provider:
                    return make_response(jsonify({'error': 'invalid_payload'}), 400)
                # ensure ownership
                cur.execute("SELECT 1 FROM notification_profiles WHERE id=%s AND user_id=%s", (profile_id, user_id))
                if not cur.fetchone():
                    return make_response(jsonify({'error': 'not_found'}), 404)
                import json as _json
                try:
                    if 'encrypt_config_json' in globals() and 'is_encryption_ready' in globals() and is_encryption_ready():
                        payload = encrypt_config_json(cfg)
                    else:
                        payload = _json.dumps(cfg, ensure_ascii=False).encode('utf-8')
                except Exception:
                    payload = _json.dumps(cfg, ensure_ascii=False).encode('utf-8')
                cur.execute(
                    "INSERT INTO destinations(profile_id, provider, config_encrypted) VALUES(%s,%s,%s) RETURNING id",
                    (profile_id, provider, payload)
                )
                did = cur.fetchone()[0]
                conn.commit()
                return jsonify({'id': did, 'provider': provider})
    except Exception as e:
        return make_response(jsonify({'error': str(e)}), 500)

@server.route('/api/notifications/destinations/<int:destination_id>', methods=['GET','PUT','DELETE'])
def api_destination_detail(destination_id: int):
    session_id = request.cookies.get('session_id')
    user_id = get_user_id_by_session(session_id) if session_id else None
    if not user_id:
        return make_response(jsonify({'error': 'unauthorized'}), 401)
    try:
        with get_db_conn() as conn, conn.cursor() as cur:
            # ensure ownership via join
            base_sql = (
                "SELECT d.id, d.profile_id, p.user_id, d.provider, d.config_encrypted, d.created_at "
                "FROM destinations d JOIN notification_profiles p ON d.profile_id=p.id WHERE d.id=%s"
            )
            cur.execute(base_sql, (destination_id,))
            r = cur.fetchone()
            if not r or str(r[2]) != str(user_id):
                return make_response(jsonify({'error': 'not_found'}), 404)
            if request.method == 'GET':
                import json as _json
                cfg = {}
                try:
                    raw = (r[4] or b'{ }')
                    if hasattr(raw, 'tobytes'):
                        raw = raw.tobytes()
                    # Prefer decrypt when available
                    if 'decrypt_config_json' in globals() and raw:
                        dec = decrypt_config_json(bytes(raw))
                        if dec:
                            cfg = dec
                        else:
                            cfg = _json.loads(bytes(raw).decode('utf-8'))
                    else:
                        cfg = _json.loads(bytes(raw).decode('utf-8'))
                except Exception:
                    cfg = {}
                return jsonify({'id': r[0], 'profile_id': r[1], 'provider': r[3], 'config': cfg, 'created_at': r[5].isoformat() if r[5] else None})
            elif request.method == 'PUT':
                data = request.get_json(force=True) or {}
                provider = data.get('provider')
                cfg = data.get('config')
                sets = []
                vals = []
                if provider:
                    sets.append('provider=%s'); vals.append(provider)
                if cfg is not None:
                    import json as _json
                    try:
                        if 'encrypt_config_json' in globals() and 'is_encryption_ready' in globals() and is_encryption_ready():
                            payload = encrypt_config_json(cfg)
                        else:
                            payload = _json.dumps(cfg, ensure_ascii=False).encode('utf-8')
                    except Exception:
                        payload = _json.dumps(cfg, ensure_ascii=False).encode('utf-8')
                    sets.append('config_encrypted=%s'); vals.append(payload)
                if not sets:
                    return jsonify({'status': 'noop'})
                vals.append(destination_id)
                cur.execute(f"UPDATE destinations SET {', '.join(sets)} WHERE id=%s", tuple(vals))
                conn.commit()
                return jsonify({'status': 'ok'})
            else:
                cur.execute("DELETE FROM destinations WHERE id=%s", (destination_id,))
                conn.commit()
                return jsonify({'status': 'ok'})
    except Exception as e:
        return make_response(jsonify({'error': str(e)}), 500)

@server.route('/api/notifications/profiles/<int:profile_id>/cis', methods=['GET','PUT'])
def api_profile_cis(profile_id: int):
    session_id = request.cookies.get('session_id')
    user_id = get_user_id_by_session(session_id) if session_id else None
    if not user_id:
        return make_response(jsonify({'error': 'unauthorized'}), 401)
    try:
        with get_db_conn() as conn, conn.cursor() as cur:
            # ownership check
            cur.execute("SELECT 1 FROM notification_profiles WHERE id=%s AND user_id=%s", (profile_id, user_id))
            if not cur.fetchone():
                return make_response(jsonify({'error': 'not_found'}), 404)
            if request.method == 'GET':
                cur.execute("SELECT ci FROM notification_profile_cis WHERE profile_id=%s ORDER BY ci", (profile_id,))
                rows = cur.fetchall()
                return jsonify([r[0] for r in rows])
            else:
                data = request.get_json(force=True) or {}
                ci_list = data.get('ci_list') or []
                if not isinstance(ci_list, list):
                    return make_response(jsonify({'error': 'invalid_payload'}), 400)
                # replace set atomically
                cur.execute("DELETE FROM notification_profile_cis WHERE profile_id=%s", (profile_id,))
                if ci_list:
                    execute_values(cur,
                        "INSERT INTO notification_profile_cis(profile_id, ci) VALUES %s",
                        [(profile_id, str(ci)) for ci in ci_list]
                    )
                conn.commit()
                return jsonify({'status': 'ok', 'count': len(ci_list)})
    except Exception as e:
        return make_response(jsonify({'error': str(e)}), 500)

@server.route('/api/notifications/test', methods=['POST'])
def api_notifications_test():
    session_id = request.cookies.get('session_id')
    user_id = get_user_id_by_session(session_id) if session_id else None
    if not user_id:
        return make_response(jsonify({'error': 'unauthorized'}), 401)
    try:
        data = request.get_json(force=True) or {}
        url = (data.get('url') or '').strip()
        destination_id = data.get('destination_id')
        profile_id = data.get('profile_id')
        title = (data.get('title') or 'TI-Monitoring Test-Benachrichtigung').strip()
        body = (data.get('body') or 'Dies ist eine Test-Benachrichtigung von TI-Monitoring.').strip()

        urls_to_notify = []

        if url:
            urls_to_notify.append(url)
        elif destination_id:
            with get_db_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT d.id, d.profile_id, p.user_id, d.provider, d.config_encrypted FROM destinations d JOIN notification_profiles p ON d.profile_id=p.id WHERE d.id=%s",
                    (destination_id,)
                )
                r = cur.fetchone()
                if not r or str(r[2]) != str(user_id):
                    return make_response(jsonify({'error': 'not_found'}), 404)
                import json as _json
                try:
                    raw = (r[4] or b'{ }')
                    if hasattr(raw, 'tobytes'):
                        raw = raw.tobytes()
                    if 'decrypt_config_json' in globals() and raw:
                        dec = decrypt_config_json(bytes(raw))
                        if dec:
                            cfg = dec
                        else:
                            cfg = _json.loads(bytes(raw).decode('utf-8'))
                    else:
                        cfg = _json.loads(bytes(raw).decode('utf-8'))
                except Exception:
                    cfg = {}
                urls = cfg.get('urls') or []
                urls_to_notify.extend([str(u) for u in urls if u])
        elif profile_id:
            with get_db_conn() as conn, conn.cursor() as cur:
                # ensure ownership
                cur.execute("SELECT 1 FROM notification_profiles WHERE id=%s AND user_id=%s", (profile_id, user_id))
                if not cur.fetchone():
                    return make_response(jsonify({'error': 'not_found'}), 404)
                cur.execute("SELECT config_encrypted FROM destinations WHERE profile_id=%s", (profile_id,))
                rows = cur.fetchall()
                import json as _json
                for (blob,) in rows:
                    try:
                        raw = (blob or b'{ }')
                        if hasattr(raw, 'tobytes'):
                            raw = raw.tobytes()
                        if 'decrypt_config_json' in globals() and raw:
                            dec = decrypt_config_json(bytes(raw))
                            if dec:
                                cfg = dec
                            else:
                                cfg = _json.loads(bytes(raw).decode('utf-8'))
                        else:
                            cfg = _json.loads(bytes(raw).decode('utf-8'))
                    except Exception:
                        cfg = {}
                    urls = cfg.get('urls') or []
                    urls_to_notify.extend([str(u) for u in urls if u])
        else:
            return make_response(jsonify({'error': 'invalid_payload'}), 400)

        # Deduplicate
        urls_to_notify = list(dict.fromkeys(urls_to_notify))
        if not urls_to_notify:
            return make_response(jsonify({'error': 'no_urls_found'}), 400)

        apobj = apprise.Apprise()
        added = 0
        for u in urls_to_notify:
            try:
                if apobj.add(u):
                    added += 1
            except Exception:
                pass
        if added == 0:
            return make_response(jsonify({'error': 'no_valid_urls'}), 400)

        ok = apobj.notify(title=title, body=body, body_format=apprise.NotifyFormat.TEXT)
        return jsonify({'status': 'ok' if ok else 'failed', 'targets': added})
    except Exception as e:
        return make_response(jsonify({'error': str(e)}), 500)

if __name__ == '__main__':
    app.run(debug=False)