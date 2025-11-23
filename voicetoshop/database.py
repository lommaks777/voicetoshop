import aiosqlite
import logging
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class DatabaseService:
    """Async SQLite database service for user registry"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.db_path = None
            cls._instance._initialized = False
        return cls._instance
    
    async def initialize(self, db_path: str = "./users.db"):
        """Initialize database connection and create schema if needed"""
        if self._initialized:
            return
        
        self.db_path = db_path
        
        # Ensure parent directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        
        await self.init_db()
        self._initialized = True
        logger.info(f"Database service initialized at {db_path}")
    
    async def init_db(self):
        """Create database schema if not exists"""
        async with aiosqlite.connect(self.db_path) as db:
            # Create users table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    tg_id INTEGER PRIMARY KEY,
                    sheet_id TEXT NOT NULL UNIQUE,
                    timezone TEXT DEFAULT 'Europe/Moscow',
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_active_at TIMESTAMP
                )
            """)
            
            # Create index for performance
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_active_users 
                ON users(is_active, last_active_at)
            """)
            
            # Add timezone column to existing tables (migration)
            try:
                await db.execute("""
                    ALTER TABLE users ADD COLUMN timezone TEXT DEFAULT 'Europe/Moscow'
                """)
                logger.info("Added timezone column to users table")
            except Exception:
                # Column already exists, ignore
                pass
            
            await db.commit()
            logger.info("Database schema initialized")
    
    async def add_user(self, tg_id: int, sheet_id: str) -> bool:
        """
        Register new user or update sheet_id if exists
        
        Args:
            tg_id: Telegram user ID
            sheet_id: Google Spreadsheet ID
            
        Returns:
            True if successful, False on error
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO users (tg_id, sheet_id, created_at) 
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(tg_id) DO UPDATE SET 
                        sheet_id = excluded.sheet_id,
                        is_active = TRUE
                """, (tg_id, sheet_id))
                
                await db.commit()
                logger.info(f"User registered/updated: TG_ID {tg_id}")
                return True
        except Exception as e:
            logger.error(f"Failed to add user {tg_id}: {e}")
            return False
    
    async def get_user_sheet_id(self, tg_id: int) -> Optional[str]:
        """
        Retrieve user's sheet_id for request context
        
        Args:
            tg_id: Telegram user ID
            
        Returns:
            sheet_id string or None if not found/inactive
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    "SELECT sheet_id FROM users WHERE tg_id = ? AND is_active = TRUE",
                    (tg_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    return row[0] if row else None
        except Exception as e:
            logger.error(f"Failed to get sheet_id for user {tg_id}: {e}")
            return None
    
    async def user_exists(self, tg_id: int) -> bool:
        """
        Check if user exists in database
        
        Args:
            tg_id: Telegram user ID
            
        Returns:
            True if user exists and is active
        """
        sheet_id = await self.get_user_sheet_id(tg_id)
        return sheet_id is not None
    
    async def update_last_active(self, tg_id: int) -> None:
        """
        Update user's last activity timestamp
        
        Args:
            tg_id: Telegram user ID
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "UPDATE users SET last_active_at = CURRENT_TIMESTAMP WHERE tg_id = ?",
                    (tg_id,)
                )
                await db.commit()
        except Exception as e:
            logger.error(f"Failed to update last_active for user {tg_id}: {e}")
    
    async def deactivate_user(self, tg_id: int) -> bool:
        """
        Soft delete user (retain data for audit)
        
        Args:
            tg_id: Telegram user ID
            
        Returns:
            True if successful, False on error
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "UPDATE users SET is_active = FALSE WHERE tg_id = ?",
                    (tg_id,)
                )
                await db.commit()
                logger.info(f"User deactivated: TG_ID {tg_id}")
                return True
        except Exception as e:
            logger.error(f"Failed to deactivate user {tg_id}: {e}")
            return False
    
    async def get_total_users(self) -> int:
        """Get total number of active users"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    "SELECT COUNT(*) FROM users WHERE is_active = TRUE"
                ) as cursor:
                    row = await cursor.fetchone()
                    return row[0] if row else 0
        except Exception as e:
            logger.error(f"Failed to get total users: {e}")
            return 0
    
    async def get_all_active_users(self) -> list:
        """Get all active users with their sheet_id and timezone"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    "SELECT tg_id, sheet_id, timezone FROM users WHERE is_active = TRUE"
                ) as cursor:
                    rows = await cursor.fetchall()
                    return [
                        {'tg_id': row[0], 'sheet_id': row[1], 'timezone': row[2] or 'Europe/Moscow'}
                        for row in rows
                    ]
        except Exception as e:
            logger.error(f"Failed to get all active users: {e}")
            return []
    
    async def get_user_timezone(self, tg_id: int) -> Optional[str]:
        """
        Retrieve user's timezone
        
        Args:
            tg_id: Telegram user ID
            
        Returns:
            Timezone string or 'Europe/Moscow' as fallback
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    "SELECT timezone FROM users WHERE tg_id = ? AND is_active = TRUE",
                    (tg_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row and row[0]:
                        return row[0]
                    return 'Europe/Moscow'  # Default fallback
        except Exception as e:
            logger.error(f"Failed to get timezone for user {tg_id}: {e}")
            return 'Europe/Moscow'
    
    async def update_user_timezone(self, tg_id: int, timezone: str) -> bool:
        """
        Update user's timezone
        
        Args:
            tg_id: Telegram user ID
            timezone: IANA timezone identifier
            
        Returns:
            True if successful, False on error
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "UPDATE users SET timezone = ? WHERE tg_id = ?",
                    (timezone, tg_id)
                )
                await db.commit()
                logger.info(f"Updated timezone for user {tg_id} to {timezone}")
                return True
        except Exception as e:
            logger.error(f"Failed to update timezone for user {tg_id}: {e}")
            return False


# Global instance
db_service = DatabaseService()
