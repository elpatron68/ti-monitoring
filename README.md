# TI-Monitoring

Dieses Tool dient der Überwachung verschiedener Komponenten der Telematikinfrastruktur (TI).
Es ist modular aufgebaut, sodass sich je nach Bedarf und Systemleistung auch nur einzelne Funktionen nutzen lassen.

Die Funktionen lassen sich wie folgt zusammenfassen:

* __Abruf und Archivierung__<br>
Die Kernfunktionalität besteht in der regelmäßigen Abfrage des Verfügbarkeitsstatus sämtlicher zentraler TI-Komponenten über eine öffentliche Schnittstelle der gematik GmbH. Die Ergebnisse werden strukturiert in einer hdf5-Datei gespeichert. So können auch für längere Beobachtungszeiträume statistische Auswertungen durchgeführt werden, um beispielsweise die Einhaltung von SLAs zu beurteilen.
* __Benachrichtigungen__<br>
Bei Änderungen der Verfügbarkeit können Benachrichtigungen versendet werden. Das System unterstützt nun über 90 verschiedene Benachrichtigungsdienste durch die Integration von Apprise, darunter:
  - E-Mail (über mailto:// URLs)
  - Telegram
  - Slack
  - Discord
  - Microsoft Teams
  - und viele weitere
* __Web-App__<br>
Der aktuelle Status sämtlicher TI-Komponenten lässt sich nach Produkten gruppiert in einer interaktiven Web-App einsehen. Darüber hinaus kann für die einzelnen Komponenten eine Statistik der letzten Stunden aufgerufen werden.

## Requirements

Das Projekt verwendet eine requirements.txt Datei zur Verwaltung der Abhängigkeiten. Um alle benötigten Pakete zu installieren, führen Sie folgenden Befehl aus:

```bash
pip install -r requirements.txt
```

Die requirements.txt Datei enthält alle notwendigen Abhängigkeiten, darunter:

- numpy, pandas, h5py für Datenverarbeitung
- requests für HTTP-Anfragen
- pytz, tzlocal für Zeitzone-Handling
- dash, plotly für die Webanwendung
- apprise für Benachrichtigungen
- python-dotenv für Umgebungsvariablen-Management
- matplotlib für Beispiele und Entwicklung

## Einrichtung der Python-Umgebung
Das Tool kann beispielweise auf einem (virtuellen) Server, NAS oder (idealerweise permanent laufenden) Rechner installiert werden. Systemanforderungen und Einrichtungsaufwand variieren je nach Umfang der genutzten Funktionen. Für die 
Grundfunktionalität (Abruf und Archivierung von Verfügbarkeitsinformationen) sind lediglich die Pakete erforderlich, die in der Datei `mylibrary.py` importiert werden. Nur im Falle der App sind weitere Pakete (z.B. `dash`) zu installieren sowie ein Webserver (z.B. nginx) und ggf. ein Applikationsserver (z.B. uWSGi). Weitere Details zur Funktionsweise und Konfiguration finden sich weiter unten. Allgemein empfiehlt sich die Erstellung einer virtuellen Python-Umgebung. Dies geschieht beispielsweise unter Ubuntu 24.04 LTS mit dem User `lukas` wie folgt:

```bash
sudo apt update && sudo apt upgrade
sudo apt install python3-venv
python3 -m venv /home/lukas/myenv
source /home/lukas/myenv/bin/activate
pip install -r requirements.txt
```

## Abruf und Archivierung
Abruf und Archivierung erfolgen durch das Skript `cron.py`, das alle fünf Minuten durch einen Cronjob ausgeführt werden sollte. Um möglichst die aktuellsten Daten abzugreifen,  empfiehlt sich ein minimaler Versatz zum Bereitstellungszeitpunkt der Daten:
```
# m h  dom mon dow   command
2-59/5 * * * * /bin/bash -c 'source myenv/bin/activate && python cron.py'
```
Die Daten werden aufbereitet und in der Datei `data.hdf5` gespeichert. Existiert diese noch nicht, wird sie beim ersten Ausführen des Skriptes `cron.py` automatisch erzeugt.

Innerhalb der Datei wird folgende Gruppenstruktur aufgebaut:

```
.
+-- availability
|   +-- CI-0000001
|   +-- CI-0000002
|   +-- ...
+-- configuration_items
    +-- CI-0000001
    +-- CI-0000002
    +-- ...
```

Die Gruppen `availability` und `configuration_items` enthalten jeweils für jedes Konfigurationsobjekt (z.B. `CI-0000001`) eine gleichnamige Untergruppe.

Die Untergruppe des Konfigurationsobjektes in der Gruppe `availability` enthält Datensätze mit der Verfügbarkeit als Integer (0: nicht verfügbar, 1: verfügbar). Der Name des Datensatzes entspricht der Unix-Zeit des Datenpunktes. Bei Aktualisierungen wird ein neuer Datensatz hinzugefügt.

Die Untergruppe des Konfigurationsobjektes in der Gruppe `configuration_items` enthält mehrere Datensätze mit allegemeinen Eigenschaften wie `name`, `product` und `organization`. Außerdem die aktuelle Verfügbarkeit `current_availability` sowie die Veränderung der Verfügbarkeit `availability_difference` in Bezug auf den vorherigen Wert (-1: nicht mehr verfügbar, 0: keine Veränderung, 1: wieder verfügbar). Bei Aktualisierungen werden die vorhandenen Datensätze überschrieben.

Je nach Systemleistung kann es sinnvoll sein, die Datei `data.hdf5` von Zeit zu Zeit archivieren. Hierzu kann die Datei beispielsweise per Cronjob in ein Archiv-Verzeichnis verschoben werden.

## Benachrichtigungen

Auf Wunsch können bei Änderungen der Verfügbarkeit Benachrichtigungen versendet werden. Das System unterstützt nun über 90 verschiedene Benachrichtigungsdienste durch die Integration von Apprise, darunter:

- E-Mail (über mailto:// URLs)
- Telegram
- Slack
- Discord
- Microsoft Teams
- und viele weitere

Die Benachrichtigungen werden ebenfalls über das Skript `cron.py` versendet, sofern in der Datei `myconfig.py` die Variable `notifications` den Wert `True` besitzt.

In der Datei `notifications.json` können mehrere Profile definiert werden. Ein Profil besteht aus folgenden Eigenschaften:

| Name | Beschreibung |
| ----------- | ----------- |
| name | Name des Profils (wird in der Anrede verwendet) |
| apprise_urls | Liste mit mindestens einer Apprise-URL (z.B. `["mailto://user:pass@gmail.com", "tgram://bottoken/ChatID"]`) |
| ci_list | Liste von Konfigurationsobjekten (z.B. `["CI-000001", "CI-0000002"]`) |
| type | entweder `blacklist` oder `whitelist` (legt fest, wie die Liste der Konfigurationsobjekte behandelt wird) |

Die neue Konfigurationsstruktur ist abwärtskompatibel - bestehende E-Mail-Konfigurationen mit dem Feld `recipients` funktionieren weiterhin.

### Web-Oberfläche für Benachrichtigungseinstellungen

Ab Version 1.2.0 steht eine webbasierte Oberfläche zur Verwaltung der Benachrichtigungseinstellungen zur Verfügung. Über die Seite "Notification Settings" in der Web-App können Benachrichtigungsprofile erstellt, bearbeitet und gelöscht werden.

Die Seite ist durch ein einfaches Passwortschutzsystem gesichert. Das Passwort wird über eine Umgebungsvariable `NOTIFICATION_SETTINGS_PASSWORD` konfiguriert, die in einer `.env` Datei im Projektverzeichnis gespeichert wird.

Um den Passwortschutz zu konfigurieren:

1. Kopieren Sie die Datei `.env.example` in `.env`:
   ```bash
   cp .env.example .env
   ```

2. Bearbeiten Sie die `.env` Datei und setzen Sie ein sicheres Passwort:
   ```bash
   NOTIFICATION_SETTINGS_PASSWORD=IhrSicheresPasswortHier
   ```

3. Stellen Sie sicher, dass die `.env` Datei nicht in das Git-Repository eingeschlossen wird (bereits in `.gitignore` enthalten).

Nach der Konfiguration können Sie über den Navigationslink "Notification Settings" auf die Einstellungsseite zugreifen und sich mit dem konfigurierten Passwort anmelden.

In der neuesten Version wurde ein Fehler behoben, bei dem der Bestätigungsdialog zum Löschen von Profilen beim Laden der Seite fälschlicherweise angezeigt wurde. Dieses Problem wurde in Version 1.2.1 behoben.

## Docker Deployment

Das TI-Monitoring kann auch als Docker-Container betrieben werden. Dazu ist ein Dockerfile sowie eine docker-compose.yml Datei im Projekt enthalten.

### Docker Compose

Die einfachste Methode ist die Verwendung von Docker Compose:

```bash
docker-compose up -d
```

### Environment Variables

Für die Konfiguration im Docker-Betrieb sollten Umgebungsvariablen verwendet werden:

- `NOTIFICATIONS_ENABLED`: Aktiviert/Deaktiviert Benachrichtigungen
- `NOTIFICATION_SETTINGS_PASSWORD`: Passwort für die Benachrichtigungseinstellungen
- `TI_API_URL`: URL der gematik API
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`: Für SMTP-Konfiguration (wenn verwendet)

### Volumes

Folgende Volumes sollten gemountet werden um Datenpersistenz zu gewährleisten:

- `/app/data.hdf5`: Die Datenbankdatei
- `/app/myconfig.py`: Die Konfigurationsdatei
- `/app/notifications.json`: Die Benachrichtigungskonfiguration
- `/app/.env`: Die Umgebungsvariablendatei

## Web-App
Der aktuelle Status verschiedener Komponenten kann optional auch in Form einer Web-App auf Basis des [Dash-Frameworks](https://dash.plotly.com) bereitgestellt werden. Die App kann z.B. in Kombination mit uWSGi und nginx (ähnlich [wie hier beschrieben](https://carpiero.medium.com/host-a-dashboard-using-python-dash-and-linux-in-your-own-linux-server-85d891e960bc) veröffentlicht werden.

Auf der Startseite der App werden die Komponenten nach Produkt gruppiert dargestellt. Durch Anklicken der Gruppen lassen sich die jeweiligen Komponenten einblenden.
![Screenshot aus der App: Startseite der App (Beispiel)](docs/img/App%20Home%20Beispiel.png "Startseite der App (Beispiel)")
![Screenshot aus der App: Startseite der App mit Störung (Beispiel)](docs/img/App%20Home%20Beispiel%20Störung.png "Startseite der App mit Störung (Beispiel)")
Per Klick auf die ID einer Komponente lässt sich eine Statistik der letzten Stunden aufrufen.
![Screenshot aus der App: Statistik für eine Komponente (Beispiel)](docs/img/App%20Statistik%20Beispiel.png "Statistik für eine Komponente (Beispiel)")
Um eine gute Performance zu gewährleisten, kann das Zeitfenster der Statistik über die Variable `stats_delta_hours` in der Datei `myconfig.py` reduziert werden. Zudem kann es ratsam sein, die Datei `data.hdf5` regelmäßig zu archivieren bzw. zu leeren.

Soll die Web-App überhaupt nicht genutzt werden, sind folgende Ordner bzw. Dateien irrelevant und können entfernt werden:

* assets
* pages
* app.py

---
**DISCLAIMER**

Es handelt sich um ein privates Projekt ohne offiziellen Support. Jegliche Nutzung erfolgt auf eigene Verantwortung. 

Die Daten werden über eine öffentlich erreichbare Schnittstelle der gematik GmbH abgerufen. Eine ausführliche Beschreibung diser Schnittstelle ist öffentlich auf GitHub verfügbar: [https://github.com/gematik/api-tilage](https://github.com/gematik/api-tilage).

---