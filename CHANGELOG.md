# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Nginx reverse proxy with Let's Encrypt SSL certificate support
- Automated SSL certificate renewal with Certbot
- Configuration options for SSL domain and email via .env file
- init-letsencrypt.sh script for initial certificate setup

### Changed
- Updated Dockerfile to use Gunicorn as the web server instead of Flask development server
- Added Gunicorn to requirements.txt
- Created docker-compose.yml for easier deployment
- Updated README.md with Gunicorn deployment information
- Enhanced docker-compose.yml with nginx and certbot services

## [1.2.1] - 2024-05-21

### Fixed
- Resolved issue with confirmation dialog appearing incorrectly when loading notification settings page

## [1.2.0] - 2024-05-20

### Added
- Web-based interface for managing notification settings
- Password protection for notification settings page
- Support for environment variables via .env file
- Docker deployment support with Dockerfile and docker-compose.yml

### Changed
- Updated notification system to use Apprise library for supporting 90+ notification services
- Improved configuration management with YAML support
- Enhanced documentation with detailed setup instructions

## [1.1.0] - 2024-05-15

### Added
- Support for Apprise notification library (90+ services)
- Backward compatibility with existing email configuration
- Enhanced notification profiles with blacklist/whitelist support

## [1.0.0] - 2024-05-10

### Added
- Initial release of TI-Monitoring
- Core functionality for fetching and archiving TI component availability
- Email notification system
- Web application for displaying component status and statistics