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
    SCHEDULE_SHEET = "Schedule"
    
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
                self.CLIENTS_SHEET: ["Name", "Contact", "Anamnesis", "Notes", "LTV", "Last_Visit_Date", "Next_Reminder"],
                self.SESSIONS_SHEET: ["Date", "Client_Name", "Service_Type", "Duration", "Price", "Session_Notes"],
                self.SERVICES_SHEET: ["Service_Name", "Default_Price", "Default_Duration"],
                self.SCHEDULE_SHEET: ["Date", "Time", "Client_Name", "Service_Type", "Duration", "Status", "Notes", "Phone_Contact"]
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
            
            # 1. Append to Sessions tab with strict positioning
            session_row = [
                current_date,
                session_data['client_name'],
                session_data['service_name'],
                str(session_data.get('duration', '')),
                str(session_data['price']),
                str(session_data.get('session_notes', ''))
            ]
            
            # Get all values to calculate next row position
            all_sessions = await sessions_ws.get_all_values()
            next_row = len(all_sessions) + 1
            
            # Use explicit range to prevent column shift
            await sessions_ws.update(range_name=f"A{next_row}", values=[session_row])
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
                headers = ["Name", "Contact", "Anamnesis", "Notes", "LTV", "Last_Visit_Date", "Next_Reminder"]
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
                    existing_data.get('Contact', ''),
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
        Get client information with session history, ambiguity detection, and future bookings
        
        Args:
            sheet_id: User's Google Sheet ID
            client_name: Client name to lookup (supports partial matching)
            
        Returns:
            Dict with client data, session history, future bookings, and ambiguity flags:
            - All standard client fields (name, phone_contact, anamnesis, etc.)
            - _is_ambiguous: Boolean flag indicating multiple matches
            - _alternatives: List of alternative client names if ambiguous
            - next_bookings: List of future appointments from Schedule tab
            Returns None if not found
        """
        try:
            spreadsheet = await self._get_spreadsheet(sheet_id)
            
            # Get clients worksheet
            clients_ws = await spreadsheet.worksheet(self.CLIENTS_SHEET)
            all_values = await clients_ws.get_all_values()
            
            if not all_values or len(all_values) < 2:
                return None
            
            headers = all_values[0]
            search_name_lower = client_name.strip().lower()
            
            # Phase 1: Find all matching clients
            matches = []
            for row_data in all_values[1:]:
                while len(row_data) < len(headers):
                    row_data.append('')
                
                record = dict(zip(headers, row_data))
                client_full_name = record.get('Name', '').strip()
                
                # Case-insensitive substring matching
                if search_name_lower in client_full_name.lower():
                    matches.append((client_full_name, record))
            
            # Phase 2: Handle match results
            if len(matches) == 0:
                return None
            
            is_ambiguous = False
            alternatives = []
            selected_record = None
            
            if len(matches) == 1:
                # Single match - no ambiguity
                selected_record = matches[0][1]
            else:
                # Multiple matches - apply selection strategy
                is_ambiguous = True
                
                # Priority 1: Exact match (case-insensitive)
                exact_match = None
                for name, record in matches:
                    if name.lower() == search_name_lower:
                        exact_match = (name, record)
                        is_ambiguous = False  # Exact match is not ambiguous
                        break
                
                if exact_match:
                    selected_record = exact_match[1]
                    # All other matches are alternatives
                    alternatives = [name for name, _ in matches if name != exact_match[0]]
                else:
                    # Priority 2: Most recent visit date
                    # Sort by Last_Visit_Date (most recent first)
                    from datetime import datetime
                    
                    def parse_date_safe(date_str):
                        """Parse date string safely, return None if invalid"""
                        try:
                            if date_str and date_str.strip():
                                return datetime.strptime(date_str.strip(), '%Y-%m-%d')
                        except:
                            pass
                        return None
                    
                    # Sort matches by date (None dates go to end)
                    sorted_matches = sorted(
                        matches,
                        key=lambda x: parse_date_safe(x[1].get('Last_Visit_Date', '')) or datetime.min,
                        reverse=True
                    )
                    
                    selected_record = sorted_matches[0][1]
                    alternatives = [name for name, _ in sorted_matches[1:]]
            
            # Phase 3: Get session history for selected client
            selected_name = selected_record.get('Name', '')
            sessions_ws = await spreadsheet.worksheet(self.SESSIONS_SHEET)
            sessions_data = await sessions_ws.get_all_values()
            
            session_history = []
            if len(sessions_data) > 1:
                session_headers = sessions_data[0]
                for session_row in sessions_data[1:]:
                    while len(session_row) < len(session_headers):
                        session_row.append('')
                    session_record = dict(zip(session_headers, session_row))
                    
                    if session_record.get('Client_Name', '').strip().lower() == selected_name.strip().lower():
                        session_history.append({
                            'date': session_record.get('Date', ''),
                            'service': session_record.get('Service_Type', ''),
                            'price': session_record.get('Price', ''),
                            'notes': session_record.get('Session_Notes', '')
                        })
            
            # Phase 4: Get future bookings from Schedule tab
            from datetime import datetime
            import pytz
            
            next_bookings = []
            try:
                # Try to get Schedule worksheet
                schedule_ws = await spreadsheet.worksheet(self.SCHEDULE_SHEET)
                schedule_data = await schedule_ws.get_all_values()
                
                if len(schedule_data) > 1:
                    schedule_headers = schedule_data[0]
                    
                    # Get current date (use timezone-aware comparison)
                    try:
                        tz = pytz.timezone('Europe/Moscow')  # Default timezone
                        current_date = datetime.now(tz).date()
                    except:
                        current_date = datetime.now().date()
                    
                    for schedule_row in schedule_data[1:]:
                        while len(schedule_row) < len(schedule_headers):
                            schedule_row.append('')
                        
                        schedule_record = dict(zip(schedule_headers, schedule_row))
                        
                        # Case-insensitive name matching (stripped)
                        record_client_name = schedule_record.get('Client_Name', '').strip()
                        if record_client_name.lower() != selected_name.strip().lower():
                            continue
                        
                        # Date comparison: parse date string and compare
                        date_str = schedule_record.get('Date', '').strip()
                        if not date_str:
                            continue
                        
                        try:
                            # Parse YYYY-MM-DD format
                            record_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                            
                            # Include all records where record_date >= current_date
                            if record_date >= current_date:
                                # Check status (skip cancelled)
                                status = schedule_record.get('Status', '').strip().lower()
                                if status == 'cancelled':
                                    continue
                                
                                next_bookings.append({
                                    'date': date_str,
                                    'time': schedule_record.get('Time', ''),
                                    'service': schedule_record.get('Service_Type', ''),
                                    'duration': schedule_record.get('Duration', ''),
                                    'notes': schedule_record.get('Notes', '')
                                })
                        except ValueError:
                            # Invalid date format, skip this record
                            continue
                    
                    # Sort by date + time ascending
                    next_bookings.sort(key=lambda x: (x['date'], x['time']))
                    
            except Exception as schedule_error:
                # Schedule sheet doesn't exist or other error - not critical
                logger.debug(f"Could not fetch Schedule data: {schedule_error}")
            
            # Phase 5: Return result with ambiguity metadata and future bookings
            return {
                'name': selected_record.get('Name', ''),
                'phone_contact': selected_record.get('Contact', ''),
                'anamnesis': selected_record.get('Anamnesis', ''),
                'notes': selected_record.get('Notes', ''),
                'ltv': selected_record.get('LTV', ''),
                'last_visit_date': selected_record.get('Last_Visit_Date', ''),
                'next_reminder': selected_record.get('Next_Reminder', ''),
                'session_history': session_history,
                'next_bookings': next_bookings,
                '_is_ambiguous': is_ambiguous,
                '_alternatives': alternatives
            }
            
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
    
    async def _ensure_client_exists(self, spreadsheet, booking_data: Dict[str, Any]) -> None:
        """
        Check if client exists in Clients worksheet, create if not
        
        Args:
            spreadsheet: Google Spreadsheet object
            booking_data: Booking data containing client_name and phone_contact
        """
        try:
            clients_ws = await spreadsheet.worksheet(self.CLIENTS_SHEET)
            all_values = await clients_ws.get_all_values()
            
            if not all_values or len(all_values) < 1:
                # No data, create header
                headers = ["Name", "Contact", "Anamnesis", "Notes", "LTV", "Last_Visit_Date", "Next_Reminder"]
                await clients_ws.update('A1', [headers])
                all_values = [headers]
            
            headers = all_values[0]
            client_name = booking_data['client_name']
            phone_contact = booking_data.get('phone_contact', '')
            
            # Check if client already exists
            client_exists = False
            for row_data in all_values[1:]:
                while len(row_data) < len(headers):
                    row_data.append('')
                
                record = dict(zip(headers, row_data))
                if record.get('Name', '').strip().lower() == client_name.strip().lower():
                    client_exists = True
                    break
            
            # Create new client if doesn't exist
            if not client_exists:
                new_row = [
                    client_name,
                    phone_contact,
                    '',  # Anamnesis
                    '',  # Notes
                    0,   # LTV
                    '',  # Last_Visit_Date
                    booking_data['date']  # Next_Reminder - set to booking date
                ]
                
                await clients_ws.append_row(new_row)
                logger.info(f"Auto-created client card for: {client_name}")
                
        except Exception as e:
            logger.error(f"Failed to ensure client exists: {e}")
            # Non-critical error, continue with booking anyway
            pass
    
    async def add_booking(self, sheet_id: str, booking_data: Dict[str, Any]) -> None:
        """
        Add a future appointment to the Schedule worksheet
        Also creates client card in Clients worksheet if client doesn't exist
        
        Args:
            sheet_id: User's Google Sheet ID
            booking_data: Dict with keys:
                - client_name (str)
                - date (str, YYYY-MM-DD)
                - time (str, HH:MM)
                - service_name (str, optional)
                - duration (int, optional)
                - notes (str, optional)
                - phone_contact (str, optional)
        """
        try:
            spreadsheet = await self._get_spreadsheet(sheet_id)
            
            # Ensure worksheets exist (including Schedule)
            await self._ensure_worksheets(sheet_id)
            
            # Get Schedule worksheet
            schedule_ws = await spreadsheet.worksheet(self.SCHEDULE_SHEET)
            
            # Check if client exists in Clients worksheet, create if not
            await self._ensure_client_exists(spreadsheet, booking_data)
            
            # Prepare row data with strict positioning
            booking_row = [
                str(booking_data['date']),
                str(booking_data['time']),
                str(booking_data['client_name']),
                str(booking_data.get('service_name') or 'Не указано'),
                str(booking_data.get('duration', '')),
                'Confirmed',
                str(booking_data.get('notes', '')),
                str(booking_data.get('phone_contact', ''))
            ]
            
            # Get all values to calculate next row position
            all_bookings = await schedule_ws.get_all_values()
            next_row = len(all_bookings) + 1
            
            # Use explicit range to prevent column shift
            await schedule_ws.update(range_name=f"A{next_row}", values=[booking_row])
            logger.info(f"Added booking for {booking_data['client_name']} on {booking_data['date']} at {booking_data['time']}")
            
        except PermissionError:
            logger.error(f"Permission denied for sheet {sheet_id}")
            raise
        except Exception as e:
            logger.error(f"Failed to add booking: {e}")
            raise
    
    async def update_client_info(self, sheet_id: str, edit_data: Dict[str, Any]) -> bool:
        """
        Update client information by appending to existing data
        
        Args:
            sheet_id: User's Google Sheet ID
            edit_data: Dict with keys:
                - client_name (str)
                - target_field (str): 'anamnesis', 'notes', or 'contacts'
                - content_to_append (str)
                
        Returns:
            True if successful, False otherwise
        """
        try:
            spreadsheet = await self._get_spreadsheet(sheet_id)
            
            # Ensure worksheets exist
            await self._ensure_worksheets(sheet_id)
            
            clients_ws = await spreadsheet.worksheet(self.CLIENTS_SHEET)
            all_values = await clients_ws.get_all_values()
            
            if not all_values or len(all_values) < 1:
                # No data, create header and new client
                headers = ["Name", "Contact", "Anamnesis", "Notes", "LTV", "Last_Visit_Date", "Next_Reminder"]
                await clients_ws.update('A1', [headers])
                all_values = [headers]
            
            headers = all_values[0]
            client_name = edit_data['client_name']
            target_field = edit_data['target_field']
            content = edit_data['content_to_append']
            
            # Map target_field to column name
            field_mapping = {
                'anamnesis': 'Anamnesis',
                'notes': 'Notes',
                'contacts': 'Contact'
            }
            
            if target_field not in field_mapping:
                raise ValueError(f"Invalid target_field: {target_field}")
            
            column_name = field_mapping[target_field]
            
            # Check if column exists, if not add it
            if column_name not in headers:
                logger.warning(f"Column '{column_name}' not found in headers, adding it")
                headers.append(column_name)
                # Update header row in sheet
                await clients_ws.update('A1', [headers])
                # Refresh all_values to include new column
                all_values = await clients_ws.get_all_values()
            
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
            
            # Get current date for timestamp
            current_date_short = datetime.now().strftime('%d.%m')
            
            if existing_row_index:
                # Update existing client
                current_value = existing_data.get(column_name, '').strip()
                
                # Append with timestamp (except Contact)
                if column_name == 'Contact':
                    updated_value = content.strip()
                else:
                    if current_value:
                        updated_value = f"{current_value}\n({current_date_short}): {content}"
                    else:
                        updated_value = f"({current_date_short}): {content}"
                
                # Find column index
                col_index = headers.index(column_name)
                col_letter = chr(65 + col_index)  # A=65 in ASCII
                
                # Update the specific cell
                await clients_ws.update(f'{col_letter}{existing_row_index}', [[updated_value]])
                logger.info(f"Updated {column_name} for existing client: {client_name}")
                
            else:
                # Create new client with the information
                new_row = [''] * len(headers)
                new_row[headers.index('Name')] = client_name
                
                # Set the target field
                if column_name == 'Contact':
                    new_row[headers.index(column_name)] = content.strip()
                else:
                    new_row[headers.index(column_name)] = f"({current_date_short}): {content}"
                
                await clients_ws.append_row(new_row)
                logger.info(f"Created new client: {client_name} with {column_name}")
            
            return True
            
        except PermissionError:
            logger.error(f"Permission denied for sheet {sheet_id}")
            raise
        except Exception as e:
            logger.error(f"Failed to update client info: {e}")
            return False
    
    async def add_new_client(self, sheet_id: str, client_data: Dict[str, Any]) -> bool:
        """
        Add a new client to the database without a session
        
        Args:
            sheet_id: User's Google Sheet ID
            client_data: Dict with keys:
                - client_name (str)
                - phone_contact (str, optional)
                - notes (str, optional)
                - anamnesis (str, optional)
                
        Returns:
            True if successful, False otherwise
        """
        try:
            spreadsheet = await self._get_spreadsheet(sheet_id)
            
            # Ensure worksheets exist
            await self._ensure_worksheets(sheet_id)
            
            clients_ws = await spreadsheet.worksheet(self.CLIENTS_SHEET)
            all_values = await clients_ws.get_all_values()
            
            if not all_values or len(all_values) < 1:
                # No data, create header
                headers = ["Name", "Contact", "Anamnesis", "Notes", "LTV", "Last_Visit_Date", "Next_Reminder"]
                await clients_ws.update('A1', [headers])
                all_values = [headers]
            
            headers = all_values[0]
            client_name = client_data['client_name']
            
            # Check if client already exists
            existing_client = None
            for row_data in all_values[1:]:
                while len(row_data) < len(headers):
                    row_data.append('')
                
                record = dict(zip(headers, row_data))
                if record.get('Name', '').strip().lower() == client_name.strip().lower():
                    existing_client = record.get('Name', '').strip()
                    break
            
            if existing_client:
                # Client already exists
                logger.warning(f"Client {client_name} already exists")
                return False
            
            # Create new client row
            new_row = [
                client_name,
                client_data.get('phone_contact', ''),
                client_data.get('anamnesis', ''),
                client_data.get('notes', ''),
                0,  # LTV starts at 0
                '',  # Last_Visit_Date empty
                ''   # Next_Reminder empty
            ]
            
            await clients_ws.append_row(new_row)
            logger.info(f"Created new client: {client_name}")
            
            return True
            
        except PermissionError:
            logger.error(f"Permission denied for sheet {sheet_id}")
            raise
        except Exception as e:
            logger.error(f"Failed to add new client: {e}")
            return False
    
    async def get_daily_schedule(self, sheet_id: str, target_date: str) -> List[Dict[str, Any]]:
        """
        Get appointments for a specific date from Schedule worksheet
        
        Args:
            sheet_id: User's Google Sheet ID
            target_date: Date in YYYY-MM-DD format
            
        Returns:
            List of appointment dictionaries sorted by time
        """
        try:
            spreadsheet = await self._get_spreadsheet(sheet_id)
            
            # Try to get Schedule worksheet
            try:
                schedule_ws = await spreadsheet.worksheet(self.SCHEDULE_SHEET)
            except Exception:
                # Schedule sheet doesn't exist yet
                logger.info(f"Schedule sheet not found for {sheet_id}, returning empty list")
                return []
            
            # Get all records
            all_values = await schedule_ws.get_all_values()
            
            if not all_values or len(all_values) < 2:
                return []
            
            headers = all_values[0]
            appointments = []
            
            for row_data in all_values[1:]:
                # Pad row if needed
                while len(row_data) < len(headers):
                    row_data.append('')
                
                record = dict(zip(headers, row_data))
                
                # Filter by date and status
                if record.get('Date') == target_date and record.get('Status', '').lower() != 'cancelled':
                    appointments.append({
                        'time': record.get('Time', ''),
                        'client_name': record.get('Client_Name', ''),
                        'service_type': record.get('Service_Type', ''),
                        'duration': record.get('Duration', ''),
                        'notes': record.get('Notes', '')
                    })
            
            # Sort by time
            appointments.sort(key=lambda x: x['time'])
            
            logger.info(f"Retrieved {len(appointments)} appointments for {target_date}")
            return appointments
            
        except Exception as e:
            logger.error(f"Failed to get daily schedule: {e}")
            return []


# Global instance
sheets_service = SheetsService()
