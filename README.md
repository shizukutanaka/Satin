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
- Enhanced configuration versioning
- Enhanced backup scheduler
- Enhanced caching system

### Enhanced Caching System

Satin now includes an enhanced caching system that:

1. Supports async operations
2. Provides detailed cache statistics
3. Optimizes memory usage
4. Manages disk cache efficiently
5. Includes cache warmup

To use the enhanced cache system:

```python
from main.cache_manager import CacheManager
from main.logging_manager import Logger

# Initialize logger and cache manager
logger = Logger()
cache_manager = CacheManager()

# Create a cached function
@cache_manager.cache
async def expensive_operation(param):
    # Simulate expensive operation
    await asyncio.sleep(1)
    return f"Result for {param}"

# Use the cached function
result = await expensive_operation("test")

# Get cache statistics
stats = cache_manager.get_cache_stats()
print(f"Cache hit rate: {stats['hit_rate']}%")
print(f"Average latency: {stats['average_latency']}ms")

# Clear cache
cache_manager.clear_cache()
```

### Enhanced Backup Scheduler

Satin now includes an enhanced backup scheduler that:

1. Provides detailed backup history
2. Sends notifications for backup events
3. Validates backup success/failure
4. Automatically clears old backups
5. Supports daily and weekly backups

To use the enhanced backup scheduler:

```python
from main.backup_scheduler import BackupScheduler
from main.notification_system import NotificationSystem
from main.backup_manager import BackupManager
from main.logging_manager import Logger

# Initialize components
logger = Logger()
notification_system = NotificationSystem(logger)
backup_manager = BackupManager(logger)

# Initialize backup scheduler
scheduler = BackupScheduler(backup_manager, notification_system)

# Schedule daily backup at 2 AM
scheduler.add_daily_backup(2, 0)

# Schedule weekly backup on Sunday at 3 AM
scheduler.add_weekly_backup("sunday", 3, 0)

# Start the scheduler
scheduler.start()

# Get backup history
history = scheduler.get_backup_history()

# Clear backup history
scheduler.clear_backup_history()
```

### Enhanced Configuration Version Management

Satin now includes enhanced configuration version management that:

1. Saves versions with optional descriptions
2. Limits version history to prevent disk space issues
3. Compares different versions
4. Automatically backs up before restoration
5. Provides detailed version information

To use the enhanced version management:

```python
from main.config_version_manager import save_config_version, list_config_versions, restore_config_version, compare_versions

# Save current configuration with description
version_path = save_config_version(description="before_update")

# List all versions with details
versions = list_config_versions()
for version in versions:
    print(f"{version['timestamp']} - {version['size']} bytes")

# Restore a specific version
restore_config_version(versions[0]['path'])

# Compare two versions
comparison = compare_versions(versions[0]['path'], versions[1]['path'])
print(f"Differences found: {len(comparison['differences'])}")
```

### Avatar Persona / Dialogue

The autonomous 3D avatar's spoken lines (idle chatter, rest phrases and
time-aware greetings) are no longer hardcoded — they are loaded from
`config/persona.json` and can be customized without editing source code. The
system supports per-language dialogue with the same fallback chain as the UI
i18n (requested language → `default_lang` → `en`), picks lines without
repeating the previous one, and greets the user differently by time of day
(morning / afternoon / evening / night).

```jsonc
// config/persona.json
{
  "name": "Satin",
  "default_lang": "ja",
  "dialogue": {
    "ja": {
      "talk":  ["こんにちは！", "走るの大好き！"],
      "rest":  ["ふう…ちょっと休憩。"],
      "greeting": {
        "morning":   ["おはよう！"],
        "afternoon": ["こんにちは！"],
        "evening":   ["こんばんは。"],
        "night":     ["こんな時間まで…おつかれさま。"]
      }
    },
    "en": { "talk": ["Hello!"], "rest": ["Phew, a short break."] }
  }
}
```

```python
from main.persona import get_persona

persona = get_persona()          # loads config/persona.json once (cached)
print(persona.name)              # "Satin"
print(persona.greeting())        # time-aware: "おはよう！" in the morning
print(persona.talk())            # a random idle line (never repeats the last)
```

If `config/persona.json` is missing or malformed, the avatar falls back to
built-in default phrases, so the feature degrades gracefully.

#### Replies to what you say

When you type a comment to the avatar (the autonomous + TTS companion view), it
now **replies** instead of just reading your words back. Replies are driven by
configurable keyword rules in the `responses` section of `config/persona.json` —
no LLM or network is involved, so it works fully offline:

```jsonc
// config/persona.json  →  "responses"
"responses": {
  "ja": {
    "rules": [
      { "keywords": ["こんにちは", "やあ"], "replies": ["こんにちは！会えてうれしいな。"] },
      { "keywords": ["ありがとう"],         "replies": ["どういたしまして！"] }
    ],
    "fallback": ["なるほど、そうなんだ。", "うんうん、聞いてるよ。"]
  }
}
```

```python
from main.persona import get_persona

persona = get_persona()
persona.respond("こんにちは")        # -> a greeting reply from the matching rule
persona.respond("今日はどうかな")     # -> a generic acknowledgment from "fallback"
```

Rules are matched in order (first keyword hit wins, case-insensitive substring),
replies never repeat the previous line, and if no rule matches the avatar gives a
friendly fallback acknowledgment. If the persona is unavailable or returns nothing
the avatar falls back to echoing your text, preserving the original behavior.

#### Conversation history

Every exchange (your comment + the avatar's reply) is recorded to the avatar
event log (`avatar_event_log.jsonl`), so conversations show up in the existing
event tooling — the timeline viewer, the Flask dashboard's `/logs` page, and the
event report. You can also read the history programmatically:

```python
from main.conversation_log import get_conversation_log

log = get_conversation_log()
log.recent(10)        # last 10 conversation events (dicts, oldest first)
log.recent_texts(10)  # ["You: こんにちは", "Avatar: こんにちは！会えてうれしいな。", ...]
```

Logging failures (e.g. disk full) never interrupt the avatar's speech or UI.

#### Headless chat (CLI)

You can talk to the avatar from a terminal — no GUI, GPU or display required —
which is handy on a server, over SSH, or in CI. The chat uses the same persona,
rule-based responses and conversation logging as the 3D avatar:

```bash
python satin_launcher.py --chat          # uses the configured default language
python main/persona_cli.py --lang en     # force a language, skip dep checks
```

```text
Satin: こんにちは！調子はどう？
コマンド: /help 一覧 | /history 履歴 | /name 名前 | /quit 終了
You: こんにちは
Satin: やっほー！元気だった？
You: /quit
Satin: またね！いつでも来てね。
```

Commands: `/help`, `/history` (recent conversation), `/name`, `/quit`
(`/exit`, `/q`). EOF (Ctrl-D) or Ctrl-C also ends the session cleanly. The loop
accepts injectable input/output functions, so it is fully unit-testable.

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

### Environment Variable Overrides

Following the [12-factor](https://12factor.net/config) convention (as used by
Dynaconf and Pydantic-Settings), any nested configuration key can be overridden
at runtime with a `SATIN_`-prefixed environment variable. Use a double
underscore (`__`) to descend into nested sections:

```bash
# settings.log_level = "DEBUG"
export SATIN_SETTINGS__LOG_LEVEL=DEBUG

# settings.backup.max_backups = 10
export SATIN_SETTINGS__BACKUP__MAX_BACKUPS=10

# settings.debug_mode = true   (values are type-cast automatically)
export SATIN_SETTINGS__DEBUG_MODE=true
```

```python
from main.utils_config import get_config

cfg = get_config()
print(cfg["settings"]["log_level"])  # "DEBUG" when the env var above is set
```

Notes:

- Values are automatically cast (`true`/`false` → bool, integers, floats,
  comma-separated lists, JSON objects/arrays).
- Overrides are applied **at read time only** — they are never written back to
  `config.json` when you call `update_config()` / `save_config()`.
- The legacy short aliases (e.g. `SATIN_LOG_LEVEL`) continue to work and take
  precedence over the dynamic `SECTION__KEY` form.

#### `.env` files

A `.env` file in the working directory is auto-loaded the first time the
config is read (no extra call needed), so you can keep local overrides out of
your shell profile:

```dotenv
# .env
SATIN_SETTINGS__LOG_LEVEL=DEBUG
SATIN_SETTINGS__BACKUP__MAX_BACKUPS=10
```

- Real environment variables always win over `.env` values (the file provides
  defaults, not overrides).
- Set `SATIN_DISABLE_DOTENV=1` to skip auto-loading, or call
  `config.env.load_dotenv(path, override=True)` explicitly for full control.

#### Layered (multi-environment) config

Set `SATIN_ENV` to select an environment-specific overlay file that is
deep-merged over the base `config.json` (as in Dynaconf/Hydra):

```
config/
  config.json              # base, always loaded
  config.production.json   # loaded & merged when SATIN_ENV=production
  config.development.json  # loaded & merged when SATIN_ENV=development
```

```bash
export SATIN_ENV=production
```

The overlay only needs to contain the keys it changes; everything else falls
through to the base. The full precedence chain, lowest to highest, is:

```
base config.json  <  config.<env>.json  <  .env file  <  real environment vars
```

If no `SATIN_ENV` is set, or the matching overlay file is absent, only the base
config is loaded.

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
