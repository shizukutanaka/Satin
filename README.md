# Satin

Satin is a powerful and flexible configuration management system designed for managing complex applications and services.

## Features

- Multi-language support
- Advanced error handling
- Task scheduling
- Plugin system
- Performance monitoring
- Configuration validation
- Automatic backups
- Backup scheduling
- Environment variable support
- Dynamic plugin loading

### Plugin System

Satin now includes a robust plugin system that:

1. Automatically loads plugins from the plugins directory
2. Supports plugin configuration
3. Provides plugin reloading
4. Includes error handling and logging

To use the plugin system:

```python
from main.plugin_manager import PluginManager
from main.logging_manager import Logger

# Initialize logger and plugin manager
logger = Logger()
plugin_manager = PluginManager(logger)

# Load all plugins
plugin_manager.load_plugins()

# Get a specific plugin
my_plugin = plugin_manager.get_plugin("my_plugin")

# Reload all plugins
plugin_manager.reload_all_plugins()

# Get all loaded plugins
all_plugins = plugin_manager.get_all_plugins()
```

### Backup Scheduling

Satin now includes a backup scheduler that:

1. Schedules daily backups at specific times
2. Schedules weekly backups on specific days
3. Monitors backup success/failure
4. Provides backup history

To use the backup scheduler:

```python
from main.backup_scheduler import BackupScheduler
from main.backup_manager import BackupManager

# Initialize backup manager and scheduler
backup_manager = BackupManager()
scheduler = BackupScheduler(backup_manager)

# Schedule daily backup at 2 AM
scheduler.add_daily_backup(2, 0)

# Schedule weekly backup on Sunday at 3 AM
scheduler.add_weekly_backup('sunday', 3, 0)

# Start the scheduler
scheduler.start()
```

### Configuration Validation

Satin now includes a configuration validator that:

1. Validates configuration files against the schema
2. Checks for valid logging levels
3. Ensures UI theme configurations are correct
4. Verifies network port settings

To use the validator:

```python
from main.config_validator import ConfigValidator

validator = ConfigValidator("path/to/config.json")
validator.validate()
```

## Getting Started

### Prerequisites

- Python 3.8+
- Git

### Platform-Specific Requirements

#### Windows
- Windows 10 or later
- PowerShell 5.1 or later
- Visual C++ Redistributable

#### Mac
- macOS 10.14 (Mojave) or later
- Homebrew (for dependency management)
- Xcode Command Line Tools

### Installation

#### Windows
1. Clone the repository:
```bash
git clone https://github.com/shizukutanaka/Satin.git
```

2. Install dependencies:
```bash
pip install -r setup/win/requirements.txt
```

3. Run the Windows setup:
```bash
setup\win\setup.bat
```

#### Mac
1. Clone the repository:
```bash
git clone https://github.com/shizukutanaka/Satin.git
```

2. Install dependencies:
```bash
pip install -r setup/mac/requirements.txt
```

3. Run the Mac setup:
```bash
setup/mac/setup.sh
```

### Usage

#### Windows
```bash
# Launch Satin
launch\win\run_satin.bat

# Backup configuration
launch\win\backup_satin.bat

# View configuration
main\win\config_manager_enhanced.py
```

#### Mac
```bash
# Launch Satin
launch/mac/run_satin.sh

# Backup configuration
launch/mac/backup_satin.sh

# View configuration
main/mac/config_manager_enhanced.py
```

### Installation

1. Clone the repository:
```bash
git clone https://github.com/shizukutanaka/Satin.git
```

2. Install dependencies:
```bash
pip install -r setup/requirements.txt
```

### Configuration

The main configuration file is located at `config/config.json`. You can override settings using environment variables or by modifying the JSON file.

### Usage

Run the application:
```bash
python launch/run_satin.py
```

## Directory Structure

```
satin/
├── config/           # Configuration files
│   ├── config.json   # Main configuration
│   └── plugins/      # Plugin configurations
├── launch/          # Launch scripts
│   ├── win/         # Windows launch scripts
│   │   ├── backup_satin.bat
│   │   └── run_satin.bat
│   └── mac/         # Mac launch scripts
│       ├── backup_satin.sh
│       └── run_satin.sh
├── main/             # Main application code
│   ├── win/         # Windows main files
│   │   └── config_manager_enhanced.py
│   ├── mac/         # Mac main files
│   │   └── config_manager_enhanced.py
│   ├── config/       # Configuration management
│   ├── i18n/        # Internationalization
│   ├── optimize/     # Performance optimization
│   └── task_scheduler/ # Task scheduling
├── plugins/          # Custom plugins
├── setup/           # Setup scripts
│   ├── win/        # Windows setup
│   │   └── setup.bat
│   └── mac/        # Mac setup
│       └── setup.sh
├── backup/         # Backup scripts
│   ├── win/       # Windows backup
│   │   └── backup_satin.bat
│   └── mac/       # Mac backup
│       └── backup_satin.sh
└── locales/         # Language files
```

## Contributing

### Platform-Specific Guidelines

#### Windows
- Use `.bat` files for scripts
- Use Windows line endings (CRLF)
- Use Windows-style paths (\)
- Test on Windows 10 or later

#### Mac
- Use `.sh` files for scripts
- Use Unix line endings (LF)
- Use Unix-style paths (/)
- Test on macOS 10.14 or later

1. Fork the repository
2. Create your feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

MIT License

## Support

For support, please open an issue in the GitHub repository.
