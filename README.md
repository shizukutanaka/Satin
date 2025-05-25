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
- Environment variable support

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
