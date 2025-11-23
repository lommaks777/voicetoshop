import asyncio
import logging
import re
from datetime import datetime
from typing import List, Dict, Optional, Any, Tuple
import gspread_asyncio
from google.oauth2.service_account import Credentials
from config import Config

logger = logging.getLogger(__name__)


class SheetsService:
    """Multi-tenant Async Google Sheets service for massage therapist CRM"""
    
    # Worksheet names for massage therapist CRM
    CLIENTS_SHEET = "Clients"
    SESSIONS_SHEET = "Sessions"
    SERVICES_SHEET = "Services"
    
    def __init__(self):
        self.agcm = None
        self._initialized = False
    
    def _get_creds(self):
        """Get Google credentials"""
        creds_dict = Config.get_google_credentials()
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        return Credentials.from_service_account_info(creds_dict, scopes=scopes)
    
    async def initialize(self):
        """Initialize the Google Sheets client manager"""
        if self._initialized:
            return
        
        try:
            self.agcm = gspread_asyncio.AsyncioGspreadClientManager(self._get_creds)
            self._initialized = True
            logger.info("Google Sheets service initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Google Sheets: {e}")
            raise
    
    async def _get_spreadsheet(self, sheet_id: str):
        """
        Get spreadsheet object by ID (dynamic per-user)
        
        Args:
            sheet_id: Google Spreadsheet ID
            
        Returns:
            Spreadsheet object
            
        Raises:
            PermissionError: If access is denied
            ValueError: If sheet_id is invalid
        """
        try:
            agc = await self.agcm.authorize()
            return await agc.open_by_key(sheet_id)
        except gspread_asyncio.gspread.exceptions.APIError as e:
            if e.response.status_code == 403:
                raise PermissionError("Access to sheet denied. User may have revoked permissions.")
            elif e.response.status_code == 404:
                raise ValueError(f"Sheet not found: {sheet_id}")
            else:
                raise
        except Exception as e:
            logger.error(f"Failed to open spreadsheet {sheet_id}: {e}")
            raise
    
    async def validate_and_connect(self, sheet_url: str) -> Tuple[bool, str, Optional[str]]:
        """
        Validate sheet URL and test write access (onboarding helper)
        
        Args:
            sheet_url: Google Sheets URL from user
            
        Returns:
            Tuple of (success, message, sheet_id)
        """
        try:
            # Extract sheet ID from URL
            sheet_id = self._extract_sheet_id(sheet_url)
            
            if not sheet_id:
                return False, "❌ Это не ссылка на Google Таблицу. Пришли ссылку вида:\nhttps://docs.google.com/spreadsheets/d/...", None
            
            # Try to open sheet
            try:
                spreadsheet = await self._get_spreadsheet(sheet_id)
            except PermissionError:
                return False, "❌ Я не могу открыть вашу таблицу.\n\nПроверьте, что вы добавили моего робота как Редактора (Editor).", None
            except ValueError:
                return False, "❌ Таблица не найдена. Проверьте ссылку.", None
            
            # Test write access
            try:
                # Try to get first worksheet
                worksheets = await spreadsheet.worksheets()
                if not worksheets:
                    return False, "❌ Таблица пустая. Скопируйте шаблон.", None
                
                first_ws = worksheets[0]
                # Test write by updating a test cell
                await first_ws.update('Z1', [['Connected']])
                
                logger.info(f"Successfully validated sheet: {sheet_id}")
                return True, "✅ Подключение успешно!", sheet_id
                
            except Exception as e:
                logger.error(f"Write test failed for sheet {sheet_id}: {e}")
                return False, "❌ У меня только доступ для чтения.\n\nДайте мне права Редактора (Editor), не Читателя (Viewer).", None
                
        except Exception as e:
            logger.error(f"Validation error: {e}")
            return False, f"❌ Ошибка проверки: {str(e)}", None
    
    def _extract_sheet_id(self, url: str) -> Optional[str]:
        """
        Extract sheet ID from Google Sheets URL
        
        Supports formats:
        - https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit
        - https://docs.google.com/spreadsheets/d/{SHEET_ID}
        """
        patterns = [
            r'docs\.google\.com/spreadsheets/d/([a-zA-Z0-9-_]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        return None
    
    async def _ensure_worksheets(self, sheet_id: str):
        """Ensure required worksheets exist with proper headers"""
        try:
            spreadsheet = await self._get_spreadsheet(sheet_id)
            worksheets = await spreadsheet.worksheets()
            worksheet_names = [ws.title for ws in worksheets]
            
            headers = {
                self.CLIENTS_SHEET: ["Name", "Phone_Contact", "Anamnesis", "Notes", "LTV", "Last_Visit_Date", "Next_Reminder"],
                self.SESSIONS_SHEET: ["Date", "Client_Name", "Service_Type", "Duration", "Price", "Session_Notes"],
                self.SERVICES_SHEET: ["Service_Name", "Default_Price", "Default_Duration"]
            }
            
            for sheet_name, header_row in headers.items():
                if sheet_name not in worksheet_names:
                    logger.info(f"Creating missing worksheet: {sheet_name}")
                    ws = await spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=len(header_row))
                    await ws.update('A1', [header_row])
                    
        except Exception as e:
            logger.error(f"Failed to ensure worksheets: {e}")
            # Non-critical, will handle in individual operations
    
    async def log_session(self, sheet_id: str, session_data: Dict[str, Any]) -> None:
        """
        Log a massage session (core operation)
        
        Args:
            sheet_id: User's Google Sheet ID
            session_data: Dict with keys:
                - client_name (str)
                - service_name (str)
                - price (float)
                - duration (int, optional)
                - medical_notes (str, optional)
                - session_notes (str, optional)
                - preference_notes (str, optional)
                - next_appointment_date (str, optional, YYYY-MM-DD)
        """
        try:
            spreadsheet = await self._get_spreadsheet(sheet_id)
            
            # Ensure worksheets exist
            await self._ensure_worksheets(sheet_id)
            
            # Get worksheets
            sessions_ws = await spreadsheet.worksheet(self.SESSIONS_SHEET)
            clients_ws = await spreadsheet.worksheet(self.CLIENTS_SHEET)
            
            # Current date
            current_date = datetime.now().strftime('%Y-%m-%d')
            current_date_short = datetime.now().strftime('%d.%m')
            
            # 1. Append to Sessions tab
            session_row = [
                current_date,
                session_data['client_name'],
                session_data['service_name'],
                session_data.get('duration', ''),
                session_data['price'],
                session_data.get('session_notes', '')
            ]
            await sessions_ws.append_row(session_row)
            logger.info(f"Logged session for client: {session_data['client_name']}")
            
            # 2. Upsert client in Clients tab
            await self._upsert_client(
                clients_ws=clients_ws,
                client_name=session_data['client_name'],
                medical_notes=session_data.get('medical_notes', ''),
                preference_notes=session_data.get('preference_notes', ''),
                price=session_data['price'],
                current_date=current_date,
                current_date_short=current_date_short,
                next_appointment_date=session_data.get('next_appointment_date', '')
            )
            
        except PermissionError:
            logger.error(f"Permission denied for sheet {sheet_id}")
            raise
        except Exception as e:
            logger.error(f"Failed to log session: {e}")
            raise
    
    async def _upsert_client(
        self,
        clients_ws,
        client_name: str,
        medical_notes: str,
        preference_notes: str,
        price: float,
        current_date: str,
        current_date_short: str,
        next_appointment_date: str
    ):
        """Upsert client record with session data"""
        try:
            # Get all client records
            all_values = await clients_ws.get_all_values()
            
            if not all_values or len(all_values) < 1:
                # No data, create header
                headers = ["Name", "Phone_Contact", "Anamnesis", "Notes", "LTV", "Last_Visit_Date", "Next_Reminder"]
                await clients_ws.update('A1', [headers])
                all_values = [headers]
            
            headers = all_values[0]
            
            # Find existing client
            existing_row_index = None
            existing_data = None
            
            for idx, row_data in enumerate(all_values[1:], start=2):
                # Pad row if needed
                while len(row_data) < len(headers):
                    row_data.append('')
                
                record = dict(zip(headers, row_data))
                if record.get('Name', '').strip().lower() == client_name.strip().lower():
                    existing_row_index = idx
                    existing_data = record
                    break
            
            if existing_row_index:
                # Update existing client
                current_anamnesis = existing_data.get('Anamnesis', '').strip()
                current_notes = existing_data.get('Notes', '').strip()
                current_ltv = float(existing_data.get('LTV', 0) or 0)
                
                # Append medical notes with date prefix
                if medical_notes:
                    if current_anamnesis:
                        updated_anamnesis = f"{current_anamnesis}\n{current_date_short}: {medical_notes}"
                    else:
                        updated_anamnesis = f"{current_date_short}: {medical_notes}"
                else:
                    updated_anamnesis = current_anamnesis
                
                # Append preference notes
                if preference_notes:
                    if current_notes:
                        updated_notes = f"{current_notes}\n{preference_notes}"
                    else:
                        updated_notes = preference_notes
                else:
                    updated_notes = current_notes
                
                # Update LTV
                updated_ltv = current_ltv + price
                
                # Update row
                updated_row = [
                    client_name,
                    existing_data.get('Phone_Contact', ''),
                    updated_anamnesis,
                    updated_notes,
                    updated_ltv,
                    current_date,
                    next_appointment_date or existing_data.get('Next_Reminder', '')
                ]
                
                await clients_ws.update(f'A{existing_row_index}:G{existing_row_index}', [updated_row])
                logger.info(f"Updated existing client: {client_name}")
                
            else:
                # Create new client
                new_anamnesis = f"{current_date_short}: {medical_notes}" if medical_notes else ""
                
                new_row = [
                    client_name,
                    '',  # Phone_Contact (empty initially)
                    new_anamnesis,
                    preference_notes or '',
                    price,
                    current_date,
                    next_appointment_date or ''
                ]
                
                await clients_ws.append_row(new_row)
                logger.info(f"Created new client: {client_name}")
                
        except Exception as e:
            logger.error(f"Failed to upsert client {client_name}: {e}")
            raise
    
    async def get_client(self, sheet_id: str, client_name: str) -> Optional[Dict[str, Any]]:
        """
        Get client information with session history
        
        Args:
            sheet_id: User's Google Sheet ID
            client_name: Client name to lookup
            
        Returns:
            Dict with client data and session history, or None if not found
        """
        try:
            spreadsheet = await self._get_spreadsheet(sheet_id)
            
            # Get clients worksheet
            clients_ws = await spreadsheet.worksheet(self.CLIENTS_SHEET)
            all_values = await clients_ws.get_all_values()
            
            if not all_values or len(all_values) < 2:
                return None
            
            headers = all_values[0]
            
            # Find client
            for row_data in all_values[1:]:
                while len(row_data) < len(headers):
                    row_data.append('')
                
                record = dict(zip(headers, row_data))
                if record.get('Name', '').strip().lower() == client_name.strip().lower():
                    # Get session history
                    sessions_ws = await spreadsheet.worksheet(self.SESSIONS_SHEET)
                    sessions_data = await sessions_ws.get_all_values()
                    
                    session_history = []
                    if len(sessions_data) > 1:
                        session_headers = sessions_data[0]
                        for session_row in sessions_data[1:]:
                            while len(session_row) < len(session_headers):
                                session_row.append('')
                            session_record = dict(zip(session_headers, session_row))
                            
                            if session_record.get('Client_Name', '').strip().lower() == client_name.strip().lower():
                                session_history.append({
                                    'date': session_record.get('Date', ''),
                                    'service': session_record.get('Service_Type', ''),
                                    'price': session_record.get('Price', ''),
                                    'notes': session_record.get('Session_Notes', '')
                                })
                    
                    return {
                        'name': record.get('Name', ''),
                        'phone_contact': record.get('Phone_Contact', ''),
                        'anamnesis': record.get('Anamnesis', ''),
                        'notes': record.get('Notes', ''),
                        'ltv': record.get('LTV', ''),
                        'last_visit_date': record.get('Last_Visit_Date', ''),
                        'next_reminder': record.get('Next_Reminder', ''),
                        'session_history': session_history
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get client {client_name}: {e}")
            return None
    
    async def get_services(self, sheet_id: str) -> List[str]:
        """
        Get list of service names from user's Services tab
        
        Args:
            sheet_id: User's Google Sheet ID
            
        Returns:
            List of service names
        """
        try:
            spreadsheet = await self._get_spreadsheet(sheet_id)
            
            # Ensure worksheets exist
            await self._ensure_worksheets(sheet_id)
            
            services_ws = await spreadsheet.worksheet(self.SERVICES_SHEET)
            records = await services_ws.get_all_records()
            
            service_names = [record.get('Service_Name', '') for record in records if record.get('Service_Name')]
            logger.info(f"Retrieved {len(service_names)} services for sheet {sheet_id}")
            return service_names
            
        except Exception as e:
            logger.error(f"Failed to get services: {e}")
            return []


# Global instance
sheets_service = SheetsService()
