# Installation von TI-Monitoring

Diese Anleitung beschreibt die Installation von TI-Monitoring sowohl für Docker als auch für Python venv.

## Voraussetzungen

### Für Docker-Installation
- Docker
- Docker Compose

### Für Python venv-Installation
- Python 3.9 oder höher
- pip
- python3-venv (Ubuntu/Debian)

## Gemeinsame Vorbereitung

### 1. Repository klonen

```bash
git clone https://github.com/lsr-dev/ti-monitoring.git
cd ti-monitoring
```

### 2. Data-Verzeichnis anlegen

```bash
mkdir data
```

### 3. Konfigurationsdateien einrichten

#### .env Datei konfigurieren

```bash
cp .env.example .env
```

Bearbeiten Sie die `.env` Datei und passen Sie folgende Werte an:
```env
# Password for notification settings page
NOTIFICATION_SETTINGS_PASSWORD=IhrSicheresPasswortHier

# SSL configuration (nur für Docker mit HTTPS)
SSL_DOMAIN=ti-monitoring.example.com
SSL_EMAIL=admin@example.com
```

#### notifications.json konfigurieren

```bash
cp notifications.json.example notifications.json
```

Bearbeiten Sie die `notifications.json` Datei und passen Sie Ihre Benachrichtigungsprofile an:
```json
[
  {
    "name": "Team Complete",
    "type": "whitelist",
    "ci_list": [
      "CI001",
      "CI002",
      "CI003"
    ],
    "apprise_urls": [
      "mailto://user:pass@gmail.com",
      "tgram://bottoken/ChatID"
    ]
  }
]
```

#### config.yaml konfigurieren

```bash
cp config.yaml.example config.yaml
```

Bearbeiten Sie die `config.yaml` Datei und passen Sie folgende Werte an:

```yaml
# Core configuration
core:
  # URL for API (Standard gematik API)
  url: "https://ti-lage.prod.ccs.gematik.solutions/lageapi/v1/tilage/bu/PU"
  
  # Path to hdf5 file for saving the availability data 
  file_name: "data/data.hdf5"
  
  # Home URL for dash app (Ihre Domain)
  home_url: "https://ti-monitoring.example.com"
  
  # Time frame for statistics in web app
  stats_delta_hours: 12
  
  # Configuration file for notifications
  notifications_config_file: "notifications.json"
```

## Installation mit Docker (Empfohlen)

### Entwicklungsumgebung (docker-compose-dev.yml)

Die Entwicklungsumgebung ist für lokale Tests und Entwicklung optimiert:

```bash
# Container starten
docker compose -f docker-compose-dev.yml up -d

# Status überprüfen
docker compose -f docker-compose-dev.yml ps

# Logs überprüfen
docker compose -f docker-compose-dev.yml logs ti-monitoring-web
docker compose -f docker-compose-dev.yml logs ti-monitoring-cron

# Zugriff testen
curl http://localhost:8050
```

**Features der Entwicklungsumgebung:**
- ✅ Port 8050 direkt auf localhost gemappt
- ✅ Optimierte Logging-Ausgabe für Cron-Container
- ✅ Einfache Konfiguration ohne HTTPS
- ✅ Ideal für lokale Entwicklung und Tests

### Produktionsumgebung (docker-compose.yml)

Die Produktionsumgebung ist für den Live-Betrieb mit HTTPS optimiert:

#### 1. Vorbereitung

```bash
# SSL-Domain in .env konfigurieren
echo "SSL_DOMAIN=ihre-domain.com" >> .env
echo "SSL_EMAIL=admin@ihre-domain.com" >> .env

# Nginx-Konfiguration vorbereiten
mkdir -p nginx/conf.d
mkdir -p letsencrypt-config
```

#### 2. Container starten

```bash
# Container starten
docker compose up -d

# Status überprüfen
docker compose ps
```

#### 3. HTTPS mit Let's Encrypt einrichten

```bash
# Erste Zertifikate anfordern
./init-letsencrypt.sh

# Zertifikate erneuern (automatisch alle 12 Stunden)
docker compose logs certbot
```

#### 4. Logs überprüfen

```bash
# Web-Container
docker compose logs ti-monitoring-web

# Cron-Container
docker compose logs ti-monitoring-cron

# Nginx
docker compose logs nginx

# Certbot
docker compose logs certbot
```

#### 5. Zugriff testen

- HTTP: `http://ihre-domain.com` (wird zu HTTPS weitergeleitet)
- HTTPS: `https://ihre-domain.com`

**Features der Produktionsumgebung:**
- ✅ Nginx Reverse Proxy mit HTTPS
- ✅ Automatische Let's Encrypt-Zertifikate
- ✅ Ports 80/443 für HTTP/HTTPS
- ✅ Automatische Zertifikatserneuerung
- ✅ Sichere Produktionskonfiguration

**Hinweis**: Die Produktionsumgebung verwendet bereits die optimierte Konfiguration mit ungepufferter Logging-Ausgabe und direktem Port-Zugriff für Debugging-Zwecke.

### Unterschiede zwischen Dev und Prod

| Feature | Entwicklung | Produktion |
|---------|-------------|------------|
| Ports | 8050 → localhost | 80/443 → Internet |
| HTTPS | Nein | Ja (Let's Encrypt) |
| Nginx | Nein | Ja (Reverse Proxy) |
| Logging | Optimiert | Standard |
| Sicherheit | Lokal | Produktionssicher |

## Installation mit Python venv

### 1. Virtuelle Umgebung erstellen

```bash
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# oder
.venv\Scripts\activate     # Windows
```

### 2. Abhängigkeiten installieren

```bash
pip install -r requirements.txt
```

### 3. Cron-Job einrichten
Das Skript `cron.py` läuft selbstständig dauerhaft im Hintergrund und ruft alle 5 Minuten neue Daten ab. Es sollte nur **einmal gestartet** werden, nicht alle 5 Minuten neu ausgeführt.

Fügen Sie folgenden Eintrag in Ihre crontab ein:

```bash
crontab -e
```

Eintrag hinzufügen:

```cron
# m h  dom mon dow   command
@reboot cd /path/to/ti-monitoring && source .venv/bin/activate && python cron.py
```

**Wichtig**: Verwenden Sie `@reboot` anstatt `*/5 * * * *`, da das Skript kontinuierlich läuft und nicht alle 5 Minuten neu gestartet werden soll.

Alternativ können Sie das Skript manuell starten:

```bash
cd /path/to/ti-monitoring
source .venv/bin/activate
nohup python cron.py > cron.log 2>&1 &
```

### 4. Web-App starten (optional)

```bash
# Im Hintergrund starten
nohup python app.py > app.log 2>&1 &

# Oder mit Gunicorn (empfohlen für Produktion)
pip install gunicorn
gunicorn --bind 0.0.0.0:8050 --workers 2 app:server
```

### 5. Nginx konfigurieren (optional)

Erstellen Sie eine Nginx-Konfiguration für die Web-App:

```nginx
server {
    listen 80;
    server_name ti-monitoring.example.com;
    
    location / {
        proxy_pass http://127.0.0.1:8050;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## Verifikation der Installation

### 1. Datenbank überprüfen

Nach dem ersten Lauf des Cron-Jobs sollte die Datei `data/data.hdf5` erstellt worden sein:
```bash
ls -la data/
```

### 2. Web-Interface testen

- Öffnen Sie die Web-App in Ihrem Browser
- Überprüfen Sie, ob TI-Komponenten angezeigt werden
- Testen Sie die Benachrichtigungseinstellungen

### 3. Cron-Job überprüfen

```bash
# Für Docker
docker compose logs ti-monitoring-cron --tail=50

# Für Python venv
tail -f /var/log/cron.log  # oder wo Ihre Cron-Logs landen
```

## Fehlerbehebung

### Häufige Probleme

#### Docker-Container startet nicht

```bash
# Logs überprüfen
docker compose logs

# Container neu starten
docker compose down
docker compose up -d
```

#### Berechtigungsprobleme mit data-Verzeichnis

```bash
# Berechtigungen korrigieren
sudo chown -R $USER:$USER data/
chmod 755 data/
```

#### Cron-Job funktioniert nicht

- Überprüfen Sie die crontab-Einträge: `crontab -l`
- Testen Sie das Skript manuell: `python cron.py`
- Überprüfen Sie die Logs

#### Web-App ist nicht erreichbar

- Überprüfen Sie, ob der Port 8050 freigegeben ist
- Testen Sie mit: `curl http://localhost:8050`
- Überprüfen Sie Firewall-Einstellungen

### Logs überprüfen

```bash
# Docker
docker compose logs -f

# Python venv
tail -f app.log  # falls mit nohup gestartet
```

## Nächste Schritte

Nach erfolgreicher Installation:

1. **Benachrichtigungen konfigurieren**: Passen Sie `notifications.json` an
2. **Monitoring einrichten**: Überwachen Sie die Logs und Performance
3. **Backup-Strategie**: Planen Sie regelmäßige Backups der `data.hdf5`
4. **Updates**: Halten Sie das System aktuell

## Support

Bei Problemen:
1. Überprüfen Sie die Logs
2. Konsultieren Sie die README.md
3. Erstellen Sie ein Issue auf GitHub mit detaillierten Logs
