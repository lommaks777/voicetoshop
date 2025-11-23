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
    
    # OpenAI Configuration
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    
    # Google Sheets Configuration
    GOOGLE_SHEETS_CREDENTIALS_BASE64 = os.getenv("GOOGLE_SHEETS_CREDENTIALS_BASE64")
    
    # Template Sheet URL (public read-only template for users to copy)
    TEMPLATE_SHEET_URL = os.getenv("TEMPLATE_SHEET_URL", "https://docs.google.com/spreadsheets/d/YOUR_TEMPLATE_ID/edit")
    
    # Database Configuration
    DATABASE_PATH = os.getenv("DATABASE_PATH", "./users.db")
    
    # Timezone Configuration
    TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")
    
    @classmethod
    def validate(cls):
        """Validate that all required configuration is present"""
        missing = []
        
        if not cls.BOT_TOKEN:
            missing.append("BOT_TOKEN")
        if not cls.OPENAI_API_KEY:
            missing.append("OPENAI_API_KEY")
        if not cls.GOOGLE_SHEETS_CREDENTIALS_BASE64:
            missing.append("GOOGLE_SHEETS_CREDENTIALS_BASE64")
        
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
        
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
    def get_service_account_email(cls) -> str:
        """Extract client_email from decoded credentials for onboarding instructions"""
        try:
            creds = cls.get_google_credentials()
            return creds.get("client_email", "service-account@project.iam.gserviceaccount.com")
        except Exception as e:
            logger.error(f"Failed to extract service account email: {e}")
            return "service-account@project.iam.gserviceaccount.com"


# Validate configuration on module import
try:
    Config.validate()
except Exception as e:
    logger.error(f"Configuration validation failed: {e}")
    raise
