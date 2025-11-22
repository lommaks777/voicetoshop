import os
import base64
import json
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class Config:
    """Configuration management for VoiceStock Bot"""
    
    # Telegram Configuration
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID")
    
    # OpenAI Configuration
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    
    # Google Sheets Configuration
    GOOGLE_SHEETS_CREDENTIALS_BASE64 = os.getenv("GOOGLE_SHEETS_CREDENTIALS_BASE64")
    GOOGLE_SHEET_KEY = os.getenv("GOOGLE_SHEET_KEY")
    
    # Timezone Configuration
    TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")
    
    @classmethod
    def validate(cls):
        """Validate that all required configuration is present"""
        missing = []
        
        if not cls.BOT_TOKEN:
            missing.append("BOT_TOKEN")
        if not cls.ALLOWED_USER_ID:
            missing.append("ALLOWED_USER_ID")
        if not cls.OPENAI_API_KEY:
            missing.append("OPENAI_API_KEY")
        if not cls.GOOGLE_SHEETS_CREDENTIALS_BASE64:
            missing.append("GOOGLE_SHEETS_CREDENTIALS_BASE64")
        if not cls.GOOGLE_SHEET_KEY:
            missing.append("GOOGLE_SHEET_KEY")
        
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
        
        # Validate ALLOWED_USER_ID is numeric
        try:
            int(cls.ALLOWED_USER_ID)
        except ValueError:
            raise ValueError("ALLOWED_USER_ID must be a valid integer")
        
        logger.info("Configuration validated successfully")
    
    @classmethod
    def get_google_credentials(cls):
        """Decode and return Google Sheets credentials as dict"""
        try:
            decoded = base64.b64decode(cls.GOOGLE_SHEETS_CREDENTIALS_BASE64)
            credentials = json.loads(decoded)
            logger.info("Google credentials decoded successfully")
            return credentials
        except Exception as e:
            logger.error(f"Failed to decode Google credentials: {e}")
            raise ValueError(f"Invalid GOOGLE_SHEETS_CREDENTIALS_BASE64: {e}")
    
    @classmethod
    def get_allowed_user_id(cls):
        """Get allowed user ID as integer"""
        return int(cls.ALLOWED_USER_ID)


# Validate configuration on module import
try:
    Config.validate()
except Exception as e:
    logger.error(f"Configuration validation failed: {e}")
    raise
