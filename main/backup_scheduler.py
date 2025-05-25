import schedule
import time
from datetime import datetime
from .backup_manager import BackupManager
from .error_handling import BackupError
from .notification_system import NotificationSystem
from typing import Dict, List, Optional

class BackupScheduler:
    """Schedule and manage regular backups with notifications"""
    
    def __init__(self, backup_manager: BackupManager, notification_system: NotificationSystem):
        """Initialize backup scheduler"""
        self.backup_manager = backup_manager
        self.schedule = schedule.Scheduler()
        self.running = False
        self.notification_system = notification_system
        self.backup_history: List[Dict[str, Any]] = []
        self.max_history = 30  # Keep last 30 backups
        
    def add_daily_backup(self, hour: int, minute: int) -> None:
        """Add daily backup at specified time"""
        try:
            self.schedule.every().day.at(f"{hour:02d}:{minute:02d}").do(
                self._run_backup, "daily", hour, minute
            )
            self.notification_system.send_notification(
                title="Backup Scheduler",
                message=f"Daily backup scheduled at {hour:02d}:{minute:02d}",
                level="info"
            )
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
                self._run_backup, "weekly", hour, minute, day
            )
            self.notification_system.send_notification(
                title="Backup Scheduler",
                message=f"Weekly backup scheduled on {day} at {hour:02d}:{minute:02d}",
                level="info"
            )
        except Exception as e:
            raise BackupError(f"Failed to schedule weekly backup: {str(e)}")
    
    def get_backup_history(self) -> List[Dict[str, Any]]:
        """Get backup history"""
        return self.backup_history.copy()
    
    def clear_backup_history(self) -> None:
        """Clear backup history"""
        self.backup_history.clear()
        self.notification_system.send_notification(
            title="Backup Scheduler",
            message="Backup history cleared",
            level="info"
        )
    
    def _run_backup(self, backup_type: str, hour: int, minute: int, day: Optional[str] = None) -> None:
        """Run backup with type information"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Send start notification
            self.notification_system.send_notification(
                title="Backup Started",
                message=f"{backup_type.title()} backup started at {backup_time}",
                level="info"
            )
            
            backup_result = self.backup_manager.create_backup()
            
            # Create history entry
            history_entry = {
                'timestamp': timestamp,
                'type': backup_type,
                'time': backup_time,
                'success': backup_result['success'],
                'error': backup_result.get('error')
            }
            
            # Add to history
            self.backup_history.append(history_entry)
            if len(self.backup_history) > self.max_history:
                self.backup_history.pop(0)  # Remove oldest entry
            
            # Send completion notification
            if backup_result['success']:
                self.notification_system.send_notification(
                    title="Backup Completed",
                    message=f"{backup_type.title()} backup completed successfully",
                    level="success"
                )
            else:
                self.notification_system.send_notification(
                    title="Backup Failed",
                    message=f"{backup_type.title()} backup failed: {backup_result['error']}",
                    level="error"
                )
                
        except Exception as e:
            error_msg = f"Error during {backup_type} backup: {str(e)}"
            self.notification_system.send_notification(
                title="Backup Error",
                message=error_msg,
                level="error"
            )
            raise BackupError(error_msg)
        
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
        self.notification_system.send_notification(
            title="Backup Scheduler",
            message="Backup scheduler started",
            level="info"
        )
        
        while self.running:
            try:
                self.schedule.run_pending()
                time.sleep(60)  # Check every minute
            except Exception as e:
                error_msg = f"Error in backup scheduler: {str(e)}"
                self.notification_system.send_notification(
                    title="Backup Scheduler Error",
                    message=error_msg,
                    level="error"
                )
                raise BackupError(error_msg)
    
    def stop(self) -> None:
        """Stop the backup scheduler"""
        self.running = False
        self.notification_system.send_notification(
            title="Backup Scheduler",
            message="Backup scheduler stopped",
            level="info"
        )
    
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
