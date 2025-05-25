import os
import glob
import json
import shutil
import datetime
from typing import Dict, List, Optional
from utils_profile import profile_time, log_info, log_error
from .error_handling import ConfigError

VERSIONS_DIR = "config_versions"
MAX_VERSIONS = 10  # 最大バージョン数

@profile_time
def save_config_version(config_path: str = "config.json", description: Optional[str] = None) -> str:
    """
    Save a configuration snapshot with version management
    
    Args:
        config_path: Path to the configuration file
        description: Optional description for this version
        
    Returns:
        Path to the saved version file
    """
    try:
        if not os.path.exists(config_path):
            raise ConfigError(f"Configuration file not found: {config_path}")
            
        os.makedirs(VERSIONS_DIR, exist_ok=True)
        now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        base = os.path.basename(config_path)
        
        # Create version filename
        version_suffix = f"{now}"
        if description:
            version_suffix += f"_{description.replace(' ', '_')}"
        
        dest = os.path.join(VERSIONS_DIR, f"{base}.{version_suffix}.bak")
        
        # Copy file and preserve metadata
        shutil.copy2(config_path, dest)
        
        # Clean up old versions if we exceed max versions
        cleanup_old_versions(config_path)
        
        log_info(f"Saved configuration version: {dest}")
        return dest
        
    except Exception as e:
        log_error(f"Error saving configuration version: {str(e)}")
        raise ConfigError(f"Failed to save configuration version: {str(e)}")

@profile_time
def list_config_versions(config_path: str = "config.json") -> List[Dict[str, Any]]:
    """
    List all configuration versions with details
    
    Args:
        config_path: Path to the configuration file
        
    Returns:
        List of version dictionaries with details
    """
    try:
        base = os.path.basename(config_path)
        pattern = os.path.join(VERSIONS_DIR, f"{base}.*.bak")
        files = sorted(glob.glob(pattern))
        
        versions = []
        for f in files:
            # Extract version details from filename
            filename = os.path.basename(f)
            timestamp = filename.replace(f"{base}.", "").replace(".bak", "")
            
            # Get modification time
            mod_time = datetime.datetime.fromtimestamp(os.path.getmtime(f))
            
            versions.append({
                'path': f,
                'timestamp': timestamp,
                'mod_time': mod_time.strftime("%Y-%m-%d %H:%M:%S"),
                'size': os.path.getsize(f)
            })
        
        log_info(f"Found {len(versions)} configuration versions")
        return versions
        
    except Exception as e:
        log_error(f"Error listing configuration versions: {str(e)}")
        raise ConfigError(f"Failed to list configuration versions: {str(e)}")

@profile_time
def restore_config_version(version_path: str, config_path: str = "config.json") -> None:
    """
    Restore configuration from a specific version
    
    Args:
        version_path: Path to the version file to restore
        config_path: Path to restore the configuration to
    """
    try:
        if not os.path.exists(version_path):
            raise ConfigError(f"Version file not found: {version_path}")
            
        if not os.path.exists(config_path):
            raise ConfigError(f"Target configuration file not found: {config_path}")
            
        # Backup current config before restoring
        save_config_version(config_path, description="before_restore")
        
        # Restore the version
        shutil.copy2(version_path, config_path)
        log_info(f"Restored configuration from: {version_path}")
        
    except Exception as e:
        log_error(f"Error restoring configuration version: {str(e)}")
        raise ConfigError(f"Failed to restore configuration version: {str(e)}")

@profile_time
def compare_versions(version1: str, version2: str) -> Dict[str, Any]:
    """
    Compare two configuration versions
    
    Args:
        version1: Path to first version file
        version2: Path to second version file
        
    Returns:
        Dictionary with comparison results
    """
    try:
        if not os.path.exists(version1) or not os.path.exists(version2):
            raise ConfigError("One or both version files not found")
            
        with open(version1, 'r', encoding='utf-8') as f1:
            config1 = json.load(f1)
            
        with open(version2, 'r', encoding='utf-8') as f2:
            config2 = json.load(f2)
            
        # Compare configurations
        differences = {}
        for key in set(config1.keys()).union(config2.keys()):
            if config1.get(key) != config2.get(key):
                differences[key] = {
                    'old': config1.get(key),
                    'new': config2.get(key)
                }
                
        log_info(f"Found {len(differences)} differences between versions")
        return {
            'version1': version1,
            'version2': version2,
            'differences': differences
        }
        
    except Exception as e:
        log_error(f"Error comparing versions: {str(e)}")
        raise ConfigError(f"Failed to compare versions: {str(e)}")

@profile_time
def cleanup_old_versions(config_path: str = "config.json") -> None:
    """
    Remove old versions to keep within MAX_VERSIONS limit
    
    Args:
        config_path: Path to the configuration file
    """
    try:
        base = os.path.basename(config_path)
        pattern = os.path.join(VERSIONS_DIR, f"{base}.*.bak")
        files = sorted(glob.glob(pattern))
        
        if len(files) > MAX_VERSIONS:
            # Keep only the newest MAX_VERSIONS files
            files_to_remove = files[:-MAX_VERSIONS]
            for f in files_to_remove:
                os.remove(f)
                log_info(f"Removed old version: {f}")
                
    except Exception as e:
        log_error(f"Error cleaning up old versions: {str(e)}")
        raise ConfigError(f"Failed to clean up old versions: {str(e)}")

if __name__ == "__main__":
    print("[INFO] Configuration Version Management Tool")
    
    while True:
        print("\nMenu:")
        print("1. Save current configuration version")
        print("2. List configuration versions")
        print("3. Restore configuration version")
        print("4. Compare two versions")
        print("5. Exit")
        
        choice = input("Select an option (1-5): ")
        
        if choice == "1":
            desc = input("Enter description (optional): ")
            save_config_version(description=desc if desc else None)
            
        elif choice == "2":
            versions = list_config_versions()
            if versions:
                print("\nAvailable versions:")
                for i, version in enumerate(versions):
                    print(f"{i+1}. {version['timestamp']} ({version['mod_time']}) - {version['size']} bytes")
            
        elif choice == "3":
            versions = list_config_versions()
            if versions:
                idx = input(f"Enter version number to restore (1-{len(versions)}): ")
                if idx.isdigit() and 1 <= int(idx) <= len(versions):
                    restore_config_version(versions[int(idx)-1]['path'])
            
        elif choice == "4":
            versions = list_config_versions()
            if len(versions) >= 2:
                print("\nAvailable versions:")
                for i, version in enumerate(versions):
                    print(f"{i+1}. {version['timestamp']}")
                
                idx1 = input("Enter first version number: ")
                idx2 = input("Enter second version number: ")
                
                if idx1.isdigit() and idx2.isdigit():
                    v1 = versions[int(idx1)-1]['path']
                    v2 = versions[int(idx2)-1]['path']
                    differences = compare_versions(v1, v2)
                    print("\nDifferences:")
                    for key, diff in differences['differences'].items():
                        print(f"\nKey: {key}")
                        print(f"Old: {diff['old']}")
                        print(f"New: {diff['new']}")
            
        elif choice == "5":
            break
            
        else:
            print("Invalid choice. Please try again.")

if __name__ == "__main__":
    print("[INFO] 設定ファイル バージョン管理ツール")
    ans = input("現在のconfig.jsonをバージョン保存しますか？ [y/N]: ")
    if ans.lower() == "y":
        save_config_version()
    ans2 = input("バージョン一覧を表示しますか？ [y/N]: ")
    if ans2.lower() == "y":
        files = list_config_versions()
        if files:
            idx = input(f"復元したい番号を指定(0-{len(files)-1}) またはEnterでスキップ: ")
            if idx.isdigit() and 0 <= int(idx) < len(files):
                restore_config_version(files[int(idx)])
