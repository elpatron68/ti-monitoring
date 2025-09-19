#!/usr/bin/env bash
set -euo pipefail

# CI-Ausfall-Simulator für TI-Monitoring
# Simuliert einen Ausfall einer CI und sendet eine Test-Benachrichtigung
#
# Verwendung:
#   ./scripts/simulate_ci_outage.sh [CI_ID] [DURATION_MINUTES]
#
# Beispiele:
#   ./scripts/simulate_ci_outage.sh CI-0000034 5
#   ./scripts/simulate_ci_outage.sh CI-0000123 10

# Farben für Output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Hilfsfunktionen
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Funktion: Hilfe anzeigen
show_help() {
    cat << EOF
CI-Ausfall-Simulator für TI-Monitoring

VERWENDUNG:
    $0 [CI_ID] [DURATION_MINUTES]

PARAMETER:
    CI_ID            Configuration Item ID (z.B. CI-0000034)
    DURATION_MINUTES Ausfalldauer in Minuten (Standard: 5)

BEISPIELE:
    $0 CI-0000034 5      # 5 Minuten Ausfall für CI-0000034
    $0 CI-0000123 10     # 10 Minuten Ausfall für CI-0000123
    $0 CI-0000034        # 5 Minuten Ausfall (Standard-Dauer)

VORAUSSETZUNGEN:
    - Virtuelles Environment aktiviert (.venv)
    - Docker Container laufen (db, ti-monitoring-web, ti-monitoring-cron)
    - APPRISE_TEST_URL in .env konfiguriert
    - CI muss in der Datenbank existieren

EOF
}

# Parameter prüfen
if [[ $# -eq 0 ]] || [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
    show_help
    exit 0
fi

CI_ID="$1"
DURATION_MINUTES="${2:-5}"

# Parameter validieren
if [[ -z "$CI_ID" ]]; then
    log_error "CI_ID ist erforderlich"
    exit 1
fi

if ! [[ "$DURATION_MINUTES" =~ ^[0-9]+$ ]] || [[ "$DURATION_MINUTES" -lt 1 ]]; then
    log_error "DURATION_MINUTES muss eine positive Zahl sein"
    exit 1
fi

log_info "Starte CI-Ausfall-Simulation für $CI_ID (Dauer: ${DURATION_MINUTES} Minuten)"

# .env Datei laden
if [[ ! -f ".env" ]]; then
    log_error ".env Datei nicht gefunden. Bitte erstellen Sie eine .env Datei basierend auf .env.example"
    exit 1
fi

source .env

# APPRISE_TEST_URL prüfen
if [[ -z "${APPRISE_TEST_URL:-}" ]]; then
    log_error "APPRISE_TEST_URL ist nicht in .env konfiguriert"
    log_info "Fügen Sie APPRISE_TEST_URL zu Ihrer .env Datei hinzu, z.B.:"
    log_info "APPRISE_TEST_URL=mailtos://smtp.example.com?to=test@example.com&subject=TI-Monitoring Test"
    exit 1
fi

# Docker Container Status prüfen
log_info "Prüfe Docker Container Status..."
CONTAINER_STATUS=$(docker compose ps --format "table {{.Service}}\t{{.Status}}" | grep -E "(db|ti-monitoring-web|ti-monitoring-cron)" | wc -l)
if [[ "$CONTAINER_STATUS" -lt 3 ]]; then
    log_error "Nicht alle erforderlichen Container sind gestartet"
    log_info "Aktueller Status:"
    docker compose ps
    log_info "Bitte starten Sie die Container mit:"
    log_info "scripts/docker-rebuild-dev.sh"
    exit 1
fi

# Prüfe ob Container tatsächlich laufen (nicht nur existieren)
RUNNING_CONTAINERS=$(docker compose ps --format "table {{.Service}}\t{{.Status}}" | grep -E "(db|ti-monitoring-web|ti-monitoring-cron)" | grep -E "(Up|healthy)" | wc -l)
if [[ "$RUNNING_CONTAINERS" -lt 3 ]]; then
    log_error "Nicht alle Container laufen ordnungsgemäß"
    log_info "Aktueller Status:"
    docker compose ps
    exit 1
fi
log_success "Alle Docker Container laufen ordnungsgemäß"

# Datenbankverbindung testen
log_info "Teste Datenbankverbindung..."
if ! docker compose exec -T db psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "SELECT 1;" > /dev/null 2>&1; then
    log_error "Datenbankverbindung fehlgeschlagen"
    exit 1
fi
log_success "Datenbankverbindung erfolgreich"

# CI in Datenbank prüfen
log_info "Prüfe ob CI $CI_ID in der Datenbank existiert..."
CI_EXISTS=$(docker compose exec -T db psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -t -c "SELECT COUNT(*) FROM ci_metadata WHERE ci = '$CI_ID';" | tr -d ' \n')
if [[ "$CI_EXISTS" != "1" ]]; then
    log_error "CI $CI_ID existiert nicht in der Datenbank"
    log_info "Verfügbare CIs:"
    docker compose exec -T db psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "SELECT ci, name FROM ci_metadata LIMIT 10;"
    exit 1
fi
log_success "CI $CI_ID gefunden"

# Aktuellen Status der CI abrufen
log_info "Rufe aktuellen Status von $CI_ID ab..."
CURRENT_STATUS=$(docker compose exec -T db psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -t -c "SELECT status FROM measurements WHERE ci = '$CI_ID' ORDER BY ts DESC LIMIT 1;" | tr -d ' \n')
if [[ -z "$CURRENT_STATUS" ]]; then
    log_error "Keine Messungen für CI $CI_ID gefunden"
    exit 1
fi

log_info "Aktueller Status von $CI_ID: $CURRENT_STATUS"

if [[ "$CURRENT_STATUS" == "0" ]]; then
    log_warning "CI $CI_ID ist bereits nicht verfügbar (Status: 0)"
    log_info "Simulation wird trotzdem fortgesetzt..."
fi

# Ausfall simulieren (Status auf 0 setzen)
log_info "Simuliere Ausfall von $CI_ID..."
TIMESTAMP=$(date -u '+%Y-%m-%d %H:%M:%S')
docker compose exec -T db psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "INSERT INTO measurements (ci, ts, status) VALUES ('$CI_ID', '$TIMESTAMP', 0);"

if [[ $? -eq 0 ]]; then
    log_success "Ausfall von $CI_ID simuliert (Status: 0)"
else
    log_error "Fehler beim Simulieren des Ausfalls"
    exit 1
fi

# Test-Benachrichtigung senden
log_info "Sende Test-Benachrichtigung über APPRISE_TEST_URL..."

# Python-Script für Benachrichtigung erstellen
cat > /tmp/test_notification.py << EOF
#!/usr/bin/env python3
import os
import sys
import apprise
from datetime import datetime
import re
import html as htmllib
import logging
logging.basicConfig(level=logging.DEBUG)

def send_test_notification():
    try:
        # APPRISE_TEST_URL aus Umgebungsvariable laden
        apprise_url = os.getenv('APPRISE_TEST_URL')
        if not apprise_url:
            print("ERROR: APPRISE_TEST_URL nicht gesetzt")
            return False
        
        # Apprise-Objekt erstellen
        apobj = apprise.Apprise()
        if not apobj.add(apprise_url):
            print(f"ERROR: Ungültige APPRISE_TEST_URL: {apprise_url}")
            return False
        
        # Test-Nachricht erstellen
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        subject = f"TI-Monitoring Test-Benachrichtigung - CI-Ausfall Simulation"
        
        body_html = f"""
<h2>🔧 TI-Monitoring Test-Benachrichtigung</h2>

<p><strong>Zeit:</strong> {timestamp}</p>
<p><strong>CI:</strong> {os.getenv('CI_ID')}</p>
<p><strong>Status:</strong> <span style="color: red;">❌ Nicht verfügbar (simuliert)</span></p>
<p><strong>Dauer:</strong> {os.getenv('DURATION_MINUTES')} Minuten</p>

<h3>📋 Details</h3>
<p>Dies ist eine Test-Benachrichtigung zur Simulation eines CI-Ausfalls.</p>
<p>Die CI wurde manuell auf Status 0 (nicht verfügbar) gesetzt und wird nach {os.getenv('DURATION_MINUTES')} Minuten automatisch wieder auf Status 1 (verfügbar) gesetzt.</p>

<h3>🔧 Technische Informationen</h3>
<ul>
    <li><strong>Skript:</strong> simulate_ci_outage.sh</li>
    <li><strong>APPRISE_URL:</strong> {apprise_url[:50]}...</li>
    <li><strong>Simulation ID:</strong> test-{int(datetime.now().timestamp())}</li>
    <li><a href="https://ti-stats.net">Zur App</a></li>
    <li><a href="https://mastodon.ti-stats.net/@tistatus">Unser Mastodon</a></li>
    
</ul>

<hr>
<p><em>Diese Nachricht wurde automatisch vom TI-Monitoring CI-Ausfall-Simulator generiert.</em></p>
"""

        def html_to_text(s: str) -> str:
            def repl_a(m):
                href, text = m.group(1), m.group(2)
                return f"{text} ({href})"
            s = re.sub(r"<a [^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", repl_a, s, flags=re.I|re.S)
            s = re.sub(r"<\s*br\s*/?\s*>", "\n", s, flags=re.I)
            s = re.sub(r"</\s*p\s*>", "\n\n", s, flags=re.I)
            s = re.sub(r"<\s*p\s*[^>]*>", "", s, flags=re.I)
            s = re.sub(r"<\s*li\s*[^>]*>", "- ", s, flags=re.I)
            s = re.sub(r"</\s*li\s*>", "\n", s, flags=re.I)
            s = re.sub(r"<[^>]+>", "", s)
            try:
                s = htmllib.unescape(s)
            except Exception:
                pass
            s = re.sub(r"\n{3,}", "\n\n", s).strip()
            return s

        scheme = apprise_url.split('://', 1)[0].lower()
        email_schemes = { 'mailto', 'gmail', 'ses', 'sendgrid', 'outlook', 'resend' }
        mastodon_schemes = { 'toots', 'mastodon', 'mastodons' }

        print(f"Scheme: {scheme}")
        if scheme in email_schemes:
            body = body_html
            body_fmt = apprise.NotifyFormat.HTML
            title_to_send = subject
        elif scheme in mastodon_schemes:
            # Merge title into body and trim aggressively
            body = html_to_text((subject + "\n\n" + body_html).strip())
            max_len = 460
            if len(body) > max_len:
                body = body[:max_len].rstrip() + '…'
            body_fmt = apprise.NotifyFormat.TEXT
            title_to_send = ''
        else:
            body = html_to_text(body_html)
            body_fmt = apprise.NotifyFormat.MARKDOWN
            title_to_send = subject
        print(f"Body format: {body_fmt}; length={len(body)} title_len={len(title_to_send)}")
        
        # Benachrichtigung senden
        success = apobj.notify(
            title=title_to_send,
            body=body,
            body_format=body_fmt
        )
        print(f"notify() returned: {success}")
        
        if success:
            print("SUCCESS: Test-Benachrichtigung erfolgreich gesendet")
            return True
        else:
            print("ERROR: Fehler beim Senden der Test-Benachrichtigung")
            return False
            
    except Exception as e:
        print(f"ERROR: Ausnahme beim Senden der Test-Benachrichtigung: {e}")
        return False

if __name__ == "__main__":
    success = send_test_notification()
    sys.exit(0 if success else 1)
EOF

# Python-Script ausführen (immer .venv nutzen)
export CI_ID DURATION_MINUTES APPRISE_TEST_URL
if .venv/bin/python /tmp/test_notification.py; then
    log_success "Test-Benachrichtigung erfolgreich gesendet"
else
    log_error "Fehler beim Senden der Test-Benachrichtigung"
    exit 1
fi

# Cleanup
rm -f /tmp/test_notification.py

# Wartezeit anzeigen
log_info "Warte ${DURATION_MINUTES} Minuten bis zur automatischen Wiederherstellung..."

# Fortschrittsanzeige
for ((i=1; i<=DURATION_MINUTES; i++)); do
    echo -n "."
    sleep 60
    if [[ $((i % 5)) -eq 0 ]]; then
        echo -e " ${i}/${DURATION_MINUTES} Minuten"
    fi
done
echo ""

# CI wieder verfügbar machen (Status auf 1 setzen)
log_info "Stelle $CI_ID wieder her (Status: 1)..."
TIMESTAMP=$(date -u '+%Y-%m-%d %H:%M:%S')
docker compose exec -T db psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c "INSERT INTO measurements (ci, ts, status) VALUES ('$CI_ID', '$TIMESTAMP', 1);"

if [[ $? -eq 0 ]]; then
    log_success "CI $CI_ID erfolgreich wiederhergestellt (Status: 1)"
else
    log_error "Fehler beim Wiederherstellen von $CI_ID"
    exit 1
fi

# Zusammenfassung
echo ""
log_success "🎉 CI-Ausfall-Simulation abgeschlossen!"
echo ""
echo -e "${BLUE}Zusammenfassung:${NC}"
echo -e "  CI: ${YELLOW}$CI_ID${NC}"
echo -e "  Ausfalldauer: ${YELLOW}${DURATION_MINUTES} Minuten${NC}"
echo -e "  Status: ${GREEN}Wiederhergestellt${NC}"
echo -e "  Benachrichtigung: ${GREEN}Gesendet${NC}"
echo ""
echo -e "${BLUE}Nächste Schritte:${NC}"
echo -e "  - Prüfen Sie Ihr E-Mail-Postfach/Notification-System"
echo -e "  - Überprüfen Sie die TI-Monitoring Web-App auf Änderungen"
echo -e "  - Logs können in den Docker-Containern eingesehen werden"
echo ""
