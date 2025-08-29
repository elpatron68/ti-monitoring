# Changelog

## [Unreleased]

### Added
- Web-based notification settings page with password protection
- Environment variable support for configuration via .env file
- Profile management interface (create, edit, delete notification profiles)
- Form validation for Apprise URLs and configuration items

## [1.1.0] - 2025-08-29

### Added
- Apprise notification system replacing email-only notifications
- Support for 90+ notification services (Telegram, Slack, Discord, etc.)
- Backward compatibility with existing email configurations
- Docker support for easier deployment
- requirements.txt file for dependency management

### Changed
- Updated notification configuration structure to use Apprise URLs
- Enhanced error handling and retry mechanisms
- Improved notification delivery reliability

### Deprecated
- Direct SMTP configuration (still supported for backward compatibility)

## [1.0.0] - 2024-XX-XX

### Added
- Initial release of TI-Monitoring
- Data fetching and archiving functionality
- Email notification system
- Web application dashboard