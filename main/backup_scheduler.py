import schedule
import time
from datetime import datetime
from .backup_manager import BackupManager
from .error_handling import BackupError

class BackupScheduler:
    """Schedule and manage regular backups"""
    
    def __init__(self, backup_manager: BackupManager):
        """Initialize backup scheduler"""
        self.backup_manager = backup_manager
        self.schedule = schedule.Scheduler()
        self.running = False
        
    def add_daily_backup(self, hour: int, minute: int) -> None:
        """Add daily backup at specified time"""
        try:
            self.schedule.every().day.at(f"{hour:02d}:{minute:02d}").do(
                self._run_backup, "daily"
            )
            print(f"Scheduled daily backup at {hour:02d}:{minute:02d}")
        except Exception as e:
            raise BackupError(f"Failed to schedule daily backup: {str(e)}")
    
    def add_weekly_backup(self, day: str, hour: int, minute: int) -> None:
        """Add weekly backup on specified day"""
        try:
            days = {
                'monday': schedule.every().monday,
                'tuesday': schedule.every().tuesday,
                'wednesday': schedule.every().wednesday,
                'thursday': schedule.every().thursday,
                'friday': schedule.every().friday,
                'saturday': schedule.every().saturday,
                'sunday': schedule.every().sunday
            }
            
            if day.lower() not in days:
                raise BackupError(f"Invalid day: {day}")
            
            days[day.lower()].at(f"{hour:02d}:{minute:02d}").do(
                self._run_backup, "weekly"
            )
            print(f"Scheduled weekly backup on {day} at {hour:02d}:{minute:02d}")
        except Exception as e:
            raise BackupError(f"Failed to schedule weekly backup: {str(e)}")
    
    def start(self) -> None:
        """Start the backup scheduler"""
        if self.running:
            raise BackupError("Backup scheduler is already running")
            
        self.running = True
        print("Starting backup scheduler...")
        
        while self.running:
            try:
                self.schedule.run_pending()
                time.sleep(60)  # Check every minute
            except Exception as e:
                print(f"Error in backup scheduler: {str(e)}")
    
    def stop(self) -> None:
        """Stop the backup scheduler"""
        self.running = False
        print("Backup scheduler stopped")
    
    def _run_backup(self, backup_type: str) -> None:
        """Run backup with type information"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            print(f"Starting {backup_type} backup at {timestamp}")
            
            backup_result = self.backup_manager.create_backup()
            
            if backup_result['success']:
                print(f"{backup_type.title()} backup completed successfully")
            else:
                print(f"{backup_type.title()} backup failed: {backup_result['error']}")
                
        except Exception as e:
            print(f"Error during {backup_type} backup: {str(e)}")
