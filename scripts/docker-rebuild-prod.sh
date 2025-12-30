#!/usr/bin/env bash
set -euo pipefail

# Projekt-Root relativ zu diesem Skript ermitteln
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Prüfe, ob Docker im Rootless-Modus läuft
check_rootless_docker() {
  if docker info 2>/dev/null | grep -q "rootless"; then
    return 0
  fi
  return 1
}

# Prüfe, ob unprivilegierte Ports bereits konfiguriert sind
check_unprivileged_ports() {
  local current_value
  current_value=$(sysctl -n net.ipv4.ip_unprivileged_port_start 2>/dev/null || echo "1024")
  if [[ "$current_value" -le 80 ]]; then
    return 0
  fi
  return 1
}

# Callback-Validierung (strict) – bricht bei Fehlern ab
if command -v python3 >/dev/null 2>&1; then
  echo "Running callback validation..."
  python3 "${REPO_ROOT}/scripts/validate_callbacks.py" --strict || {
    echo "Callback validation failed. Aborting rebuild." >&2
    exit 1
  }
fi

# Prüfe Rootless Docker und Port-Konfiguration
if check_rootless_docker; then
  echo "Docker läuft im Rootless-Modus."
  if ! check_unprivileged_ports; then
    echo ""
        echo "WARNUNG: Rootless Docker kann Port 80 nicht binden, da dieser ein privilegierter Port ist."
        echo "Um Port 80 zu verwenden, muss der Systemparameter angepasst werden:"
        echo ""
        echo "  sudo sysctl -w net.ipv4.ip_unprivileged_port_start=80"
        echo ""
        echo "Um diese Änderung dauerhaft zu machen, fügen Sie folgende Zeile zu /etc/sysctl.conf hinzu:"
        echo "  net.ipv4.ip_unprivileged_port_start=80"
        echo ""
        echo "Dann führen Sie aus:"
        echo "  sudo sysctl -p"
        echo ""
        echo "Alternativ können Sie die Ports in docker-compose.yml auf nicht-privilegierte Ports ändern"
        echo "(z.B. 8080:80 und 8443:443)."
        echo ""
        echo "Versuche trotzdem fortzufahren..."
        echo ""
    fi
fi

GIT_TAG=$(git describe --tags --always 2>/dev/null || echo "")
GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "")

# Führe Docker Compose aus und fange Port-Fehler ab
if ! docker compose -f docker-compose.yml down && \
  docker compose -f docker-compose.yml build \
    --build-arg TI_VERSION="$GIT_TAG" \
    --build-arg TI_COMMIT="$GIT_SHA" && \
  docker compose -f docker-compose.yml up -d; then
  echo ""
  echo "FEHLER: Docker Compose konnte nicht erfolgreich ausgeführt werden."
  if check_rootless_docker && ! check_unprivileged_ports; then
    echo ""
    echo "Dieser Fehler könnte durch Rootless Docker und privilegierte Ports verursacht worden sein."
    echo "Bitte setzen Sie den Systemparameter wie oben beschrieben."
    echo ""
  fi
  exit 1
fi