import logging
import os
from datetime import datetime, timedelta
from typing import List, Optional, Literal
from pathlib import Path
from pydantic import BaseModel, Field
from openai import AsyncOpenAI
from config import Config
import pytz

logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = AsyncOpenAI(api_key=Config.OPENAI_API_KEY)


def normalize_product_name(name: str) -> str:
    """
    Normalize product name for consistent inventory matching
    """
    # Convert to lowercase
    name = name.lower().strip()
    
    # Common replacements for consistency
    replacements = {
        'трусики': 'трусы',
        'трусики сеточка': 'трусы сетка',
        'сеточка': 'сетка',
        'чёрные': 'черные',
        'чёрный': 'черный',
    }
    
    for old, new in replacements.items():
        name = name.replace(old, new)
    
    # Remove extra spaces
    name = ' '.join(name.split())
    
    # Capitalize first letter of each word
    name = ' '.join(word.capitalize() for word in name.split())
    
    return name


class ClientEditData(BaseModel):
    """Client information edit data"""
    client_name: str = Field(description="Client full name")
    target_field: Literal['anamnesis', 'notes', 'contacts'] = Field(description="Target field to update")
    content_to_append: str = Field(description="Content to append to the client record")


class NewClientData(BaseModel):
    """New client registration data"""
    client_name: str = Field(description="Client full name")
    phone_contact: Optional[str] = Field(default=None, description="Phone number or contact info")
    notes: Optional[str] = Field(default=None, description="Preferences, likes, general notes about client")
    anamnesis: Optional[str] = Field(default=None, description="Medical information, health conditions, contraindications")


class BookingData(BaseModel):
    """Future booking/appointment data"""
    client_name: str = Field(description="Client full name")
    date: str = Field(description="Appointment date in YYYY-MM-DD format")
    time: str = Field(description="Appointment time in HH:MM format (24-hour)")
    service_name: Optional[str] = Field(default=None, description="Type of service")
    duration: Optional[int] = Field(default=None, description="Duration in minutes", gt=0)
    notes: Optional[str] = Field(default=None, description="Special instructions or notes")
    phone_contact: Optional[str] = Field(default=None, description="Phone number or contact info")


class ClientQueryData(BaseModel):
    """Client information query data"""
    client_name: str = Field(description="Client name to search for")
    query_topic: Literal['general', 'medical', 'financial', 'history'] = Field(
        description="Category of query to determine response focus"
    )


# Pydantic Models for Structured Outputs

class SupplyItem(BaseModel):
    """Single item in a supply restock"""
    name: str = Field(description="Product name, matched to existing inventory")
    size: str = Field(description="Size designation (e.g., S, M, L, XL)")
    quantity: int = Field(description="Quantity being restocked, must be greater than 0", gt=0)


class SupplyData(BaseModel):
    """Complete supply transaction data"""
    items: List[SupplyItem] = Field(description="List of items being restocked")


class ClientInfo(BaseModel):
    """Customer information"""
    name: str = Field(description="Full client name")
    instagram: Optional[str] = Field(default=None, description="Instagram handle")
    telegram: Optional[str] = Field(default=None, description="Telegram username or ID")
    notes: Optional[str] = Field(default=None, description="Additional notes about the client")


class SaleInfo(BaseModel):
    """Sale transaction details for a single item"""
    item_name: str = Field(description="Product name being sold")
    size: str = Field(description="Product size")
    quantity: int = Field(description="Quantity sold", gt=0)
    price: float = Field(description="Unit price for this item", gt=0)


class ReminderInfo(BaseModel):
    """Reminder scheduling information"""
    days_from_now: int = Field(description="Number of days from today to set the reminder")
    text: str = Field(description="Reminder message text")


class SaleData(BaseModel):
    """Complete sale transaction data - supports multiple items"""
    client: ClientInfo
    items: List[SaleInfo] = Field(description="List of items being sold in this transaction")
    reminder: Optional[ReminderInfo] = Field(default=None, description="Optional reminder to schedule")


class SessionData(BaseModel):
    """Massage session data for logging"""
    client_name: str = Field(description="Client full name")
    service_name: str = Field(description="Type of massage/treatment performed")
    price: float = Field(description="Amount charged for session", gt=0)
    duration: Optional[int] = Field(default=None, description="Session length in minutes")
    medical_notes: Optional[str] = Field(default=None, description="Medical complaints, pain, health conditions")
    session_notes: Optional[str] = Field(default=None, description="Technical details of this session's treatment")
    preference_notes: Optional[str] = Field(default=None, description="Non-medical preferences about session delivery")
    phone_contact: Optional[str] = Field(default=None, description="Phone number or contact info")
    next_appointment_date: Optional[str] = Field(default=None, description="Next appointment date in YYYY-MM-DD format")


class AIService:
    """OpenAI integration for transcription and NLP"""
    
    @staticmethod
    async def detect_timezone(city_name: str) -> Optional[str]:
        """
        Detect IANA timezone identifier from city name using AI
        
        Args:
            city_name: City name provided by user (in any language)
            
        Returns:
            IANA timezone identifier string or None if detection fails
        """
        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": """You are a timezone detection expert. Given a city name, return ONLY the IANA timezone identifier.

Examples:
- Москва → Europe/Moscow
- Санкт-Петербург → Europe/Moscow
- Новосибирск → Asia/Novosibirsk
- Владивосток → Asia/Vladivostok
- Екатеринбург → Asia/Yekaterinburg
- Иркутск → Asia/Irkutsk
- Красноярск → Asia/Krasnoyarsk
- Калининград → Europe/Kaliningrad
- London → Europe/London
- New York → America/New_York
- Tokyo → Asia/Tokyo
- Sydney → Australia/Sydney

Rules:
- Return ONLY the timezone identifier (e.g., "Europe/Moscow")
- If city is ambiguous or unknown, return "Europe/Moscow" as safe default
- No explanations, just the timezone string

Respond with ONLY the timezone identifier."""
                    },
                    {
                        "role": "user",
                        "content": city_name
                    }
                ],
                temperature=0
            )
            
            timezone = response.choices[0].message.content.strip()
            logger.info(f"Detected timezone for '{city_name}': {timezone}")
            
            # Validate timezone format (should be Continent/City)
            if '/' in timezone and len(timezone.split('/')) == 2:
                return timezone
            else:
                logger.warning(f"Invalid timezone format returned: {timezone}")
                return None
                
        except Exception as e:
            logger.error(f"Timezone detection failed for '{city_name}': {e}")
            return None
    
    @staticmethod
    async def transcribe_audio(audio_file_path: str) -> Optional[str]:
        """
        Transcribe audio file using Whisper API
        
        Args:
            audio_file_path: Path to audio file
            
        Returns:
            Transcribed text or None if failed
        """
        try:
            with open(audio_file_path, 'rb') as audio_file:
                transcript = await client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="json"
                )
            
            text = transcript.text
            logger.info(f"Transcription successful: {text[:100]}...")
            return text
            
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return None
    
    @staticmethod
    async def classify_message(text: str) -> str:
        """  
        Classify if message is about Session, Client Edit, Booking, Query, or Add New Client
        
        Returns:
            "log_session", "client_update", "consultation", "booking", "client_query", "add_service", or "add_client"
        """
        try:
            # Get current date context for classification
            tz = pytz.timezone(Config.TIMEZONE)
            current_datetime = datetime.now(tz)
            current_date = current_datetime.strftime('%Y-%m-%d')
            current_weekday = current_datetime.strftime('%A')
            
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": f"""You are an expert assistant for massage therapists. Classify the therapist's message intent.

Today is {current_date} ({current_weekday}).

Classify into ONE of these categories:

- LOG_SESSION: Recording a COMPLETED session (past tense, mentions price/payment)
  Examples: "Приходила Анна, заплатила 3000", "Сделал массаж Ивану за 2500"
  Indicators: past tense verbs, completed action, payment mentioned

- BOOKING: Scheduling a FUTURE appointment (future tense, imperative, time references)
  Examples: "Запиши Ольгу на завтра в 14:00", "Book Mike for Tuesday 10 AM"
  Indicators: imperative mood, future time references ("завтра", "во вторник", "next week")

- CLIENT_QUERY: Asking for information about a client
  Examples: "Кто такая Анна?", "Что у Ивана с спиной?", "Напомни про Ольгу"
  Indicators: questions ("кто", "что", "когда"), information requests

- ADD_CLIENT: Adding a NEW client to database with contact info and preferences
  Examples: "Запиши клиента в контакты", "Добавь нового клиента", "Создай карту клиента"
  Indicators: explicit request to add/create client, includes name + contact info, no session details

- CLIENT_UPDATE: Adding notes about EXISTING client WITHOUT session/payment details
  Examples: "У Ольги аллергия на мёд", "Иван просил пожестче"
  Indicators: declarative statements about client attributes, no session/payment context

- CONSULTATION: General consultation request
  Examples: "Посоветуй что делать", "Как лучше?"
  Indicators: asking for advice, not about specific client

- ADD_SERVICE: Defining a new service type
  Examples: "Добавь услугу: Антицеллюлитный массаж"
  Indicators: explicitly adding service to catalog

Key distinctions:
- Past tense + payment = LOG_SESSION
- Future time + scheduling = BOOKING
- Question about client = CLIENT_QUERY
- "Add client"/"new client" + contact info = ADD_CLIENT
- Statement about existing client = CLIENT_UPDATE

Respond with only one word: "log_session", "booking", "client_query", "add_client", "client_update", "consultation", or "add_service"."""
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                ],
                temperature=0
            )
            
            classification = response.choices[0].message.content.strip().lower()
            logger.info(f"Message classified as: {classification}")
            
            valid_intents = ["log_session", "client_update", "consultation", "add_service", "booking", "client_query", "add_client"]
            return classification if classification in valid_intents else "log_session"
            
        except Exception as e:
            logger.error(f"Classification failed: {e}")
            return "log_session"  # Default to session logging
    
    @staticmethod
    async def parse_supply(text: str, existing_products: List[str]) -> Optional[SupplyData]:
        """
        Parse supply/restock information from transcribed text
        
        Args:
            text: Transcribed text
            existing_products: List of existing product names for fuzzy matching
            
        Returns:
            SupplyData object or None if parsing failed
        """
        try:
            # Create product list context
            products_context = "\n".join([f"- {p}" for p in existing_products]) if existing_products else "No existing products"
            
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": f"""You are a warehouse assistant extracting product restock information.

Existing products in inventory:
{products_context}

IMPORTANT: 
- Extract the EXACT product type mentioned (e.g., "Трусы", "Топ", "Купальник") - DO NOT change product types
- If user says "топ" (top), extract it as "Топ", NOT "Трусы" (panties)
- If user says "трусы" (panties), extract it as "Трусы", NOT "Топ" (top)
- You MAY match color/material to existing products (e.g., "Черные Сетка")
- Normalize terminology: use "Трусы" instead of "Трусики", "Сетка" instead of "Сеточка"
- ONLY include items with quantity GREATER THAN 0. Skip items with 0 quantity.

EXAMPLES:
Input: "добавь черный топ сеткой M 5 штук"
Output: {{items: [{{name: "Черный Топ Сетка", size: "M", quantity: 5}}]}}

Input: "добавь черные трусики сеткой M 5 штук"
Output: {{items: [{{name: "Черные Трусы Сетка", size: "M", quantity: 5}}]}}

Extract all items being restocked with their names, sizes, and quantities.
Return data in the specified JSON format."""
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                ],
                response_format={"type": "json_schema", "json_schema": {
                    "name": "supply_data",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "items": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "size": {"type": "string"},
                                        "quantity": {"type": "integer"}
                                    },
                                    "required": ["name", "size", "quantity"],
                                    "additionalProperties": False
                                }
                            }
                        },
                        "required": ["items"],
                        "additionalProperties": False
                    }
                }},
                temperature=0
            )
            
            import json
            result = json.loads(response.choices[0].message.content)
            supply_data = SupplyData(**result)
            
            # Normalize product names
            for item in supply_data.items:
                item.name = normalize_product_name(item.name)
            
            logger.info(f"Parsed supply data: {len(supply_data.items)} items")
            return supply_data
            
        except Exception as e:
            logger.error(f"Supply parsing failed: {e}")
            return None
    
    @staticmethod
    async def parse_sale(text: str, current_date: str) -> Optional[SaleData]:
        """
        Parse sale/customer transaction information from transcribed text
        
        Args:
            text: Transcribed text
            current_date: Current date in YYYY-MM-DD format
            
        Returns:
            SaleData object or None if parsing failed
        """
        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": f"""You are a CRM assistant extracting customer sale information.

Today's date is: {current_date}

Extract information for MULTIPLE items if mentioned:

1. Client information:
   - name: Client's full name
   - instagram: Instagram username ONLY (without "Пользователь Instagram:" prefix)
   - telegram: Telegram username ONLY (without "Пользователь Telegram:" prefix)
   - notes: Personal characteristics, preferences, AND future purchase wishes
   
2. Items (array of ALREADY PURCHASED products):
   - ONLY extract products that were ALREADY BOUGHT/PURCHASED
   - CRITICAL: DO NOT include items client "wants", "will buy", "interested in" - those go to notes
   - Look for past tense: "купила", "купил", "bought", "purchased"
   - For EACH purchased product: name, size, quantity, price
   - If price is mentioned once for multiple items, apply it to each item
   - All items must have a price > 0
   
3. Reminder (if mentioned):
   - Convert relative dates to number of days

CRITICAL RULES FOR ITEMS vs NOTES:
- Items array: ONLY products with COMPLETED purchase ("купила", "bought")
- Notes field: Future wishes ("хочет купить", "интересуется", "wants to buy"), preferences, characteristics
- If no price mentioned for purchased items, this is an error - price is REQUIRED for items
- Normalize product names: "Трусы" instead of "Трусики", "Сетка" instead of "Сеточка"

EXAMPLES:

Input: "Светлана купила черные трусы M и бежевые трусы M по 40 долларов каждая"
Output:
- client: {{
    name: "Светлана",
    instagram: null,
    telegram: null,
    notes: null
  }}
- items: [
    {{item_name: "Черные Трусы", size: "M", quantity: 1, price: 40}},
    {{item_name: "Бежевые Трусы", size: "M", quantity: 1, price: 40}}
  ]

Input: "Анна купила черные трусы M за 35 долларов. Любит яркие цвета."
Output:
- client: {{
    name: "Анна",
    notes: "Любит яркие цвета"
  }}
- items: [
    {{item_name: "Черные Трусы", size: "M", quantity: 1, price: 35}}
  ]

Input: "Анастасия купила черные трусы M и бежевые трусы M по 25 долларов. Укажи в описании, что она хочет купить топ бежевый L и топ черный L"
Output:
- client: {{
    name: "Анастасия",
    notes: "Хочет купить топ бежевый L и топ черный L"
  }}
- items: [
    {{item_name: "Черные Трусы", size: "M", quantity: 1, price: 25}},
    {{item_name: "Бежевые Трусы", size: "M", quantity: 1, price: 25}}
  ]
  (Note: tops are NOT in items because they are future wishes, not purchases)

Return data in the specified JSON format."""
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                ],
                response_format={"type": "json_schema", "json_schema": {
                    "name": "sale_data",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "client": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "instagram": {"type": ["string", "null"]},
                                    "telegram": {"type": ["string", "null"]},
                                    "notes": {"type": ["string", "null"]}
                                },
                                "required": ["name", "instagram", "telegram", "notes"],
                                "additionalProperties": False
                            },
                            "items": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "item_name": {"type": "string"},
                                        "size": {"type": "string"},
                                        "quantity": {"type": "integer"},
                                        "price": {"type": "number"}
                                    },
                                    "required": ["item_name", "size", "quantity", "price"],
                                    "additionalProperties": False
                                }
                            },
                            "reminder": {
                                "type": ["object", "null"],
                                "properties": {
                                    "days_from_now": {"type": "integer"},
                                    "text": {"type": "string"}
                                },
                                "required": ["days_from_now", "text"],
                                "additionalProperties": False
                            }
                        },
                        "required": ["client", "items", "reminder"],
                        "additionalProperties": False
                    }
                }},
                temperature=0
            )
            
            import json
            result = json.loads(response.choices[0].message.content)
            sale_data = SaleData(**result)
            
            # Normalize product names for all items
            for item in sale_data.items:
                item.item_name = normalize_product_name(item.item_name)
            
            logger.info(f"Parsed sale data: {sale_data.client.name} - {len(sale_data.items)} items")
            return sale_data
            
        except Exception as e:
            logger.error(f"Sale parsing failed: {e}")
            return None
    
    @staticmethod
    async def parse_client_edit(text: str) -> Optional[ClientEditData]:
        """
        Parse client edit information from transcribed text
        
        Args:
            text: Transcribed text
            
        Returns:
            ClientEditData object or None if parsing failed
        """
        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": """You are a CRM assistant extracting client information updates.

Extract:
1. Client name (the person being discussed)
2. Target field to update:
   - "anamnesis" for medical information (allergies, conditions, pain, medical history)
   - "notes" for preferences, likes/dislikes, non-medical information
   - "contacts" for phone numbers or contact information
3. Content to append

IMPORTANT for phone numbers:
- Convert spoken numbers to digits
- "плюс семь девять девять девять" → "+7999"
- "восемь девятьсот пять" → "8905"
- Keep formatting symbols: +, -, spaces

Examples:
- "У Ольги аллергия на мёд" → target_field: "anamnesis", content: "Аллергия на мёд"
- "Иван просил пожестче" → target_field: "notes", content: "Просил пожестче"
- "Телефон Анны плюс семь девять девять девять один два три" → target_field: "contacts", content: "+7999123"
- "Контакт Марии восемь девятьсот пятьдесят" → target_field: "contacts", content: "8950"

Return data in the specified JSON format."""
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                ],
                response_format={"type": "json_schema", "json_schema": {
                    "name": "client_edit_data",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "client_name": {"type": "string"},
                            "target_field": {"type": "string", "enum": ["anamnesis", "notes", "contacts"]},
                            "content_to_append": {"type": "string"}
                        },
                        "required": ["client_name", "target_field", "content_to_append"],
                        "additionalProperties": False
                    }
                }},
                temperature=0
            )
            
            import json
            result = json.loads(response.choices[0].message.content)
            client_edit_data = ClientEditData(**result)
            
            logger.info(f"Parsed client edit: {client_edit_data.client_name} - {client_edit_data.target_field}")
            return client_edit_data
            
        except Exception as e:
            logger.error(f"Client edit parsing failed: {e}")
            return None
    
    @staticmethod
    async def parse_booking(text: str, current_date: str, user_current_date: Optional[str] = None) -> Optional[BookingData]:
        """
        Parse booking/appointment information from transcribed text
        
        Args:
            text: Transcribed text
            current_date: Server current date in YYYY-MM-DD format (for backward compatibility)
            user_current_date: User's local current date in YYYY-MM-DD format (preferred)
            
        Returns:
            BookingData object or None if parsing failed
        """
        try:
            # Use user's local date if provided, otherwise fall back to server date
            reference_date = user_current_date or current_date
            
            # Calculate reference dates for the AI
            tz = pytz.timezone(Config.TIMEZONE)
            today = datetime.strptime(reference_date, '%Y-%m-%d')
            weekday = today.strftime('%A')
            
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": f"""You are a scheduling assistant extracting appointment booking information.

Today is {reference_date} ({weekday}).

Extract:
1. client_name: Full client name
2. date: Appointment date in YYYY-MM-DD format
   - "tomorrow" → {(today + timedelta(days=1)).strftime('%Y-%m-%d')}
   - "today" → {reference_date}
   - "next Monday", "next Tuesday", etc. → calculate next occurrence of that weekday
   - "завтра" → {(today + timedelta(days=1)).strftime('%Y-%m-%d')}
   - "в понедельник", "во вторник" → next occurrence of that day
3. time: Appointment time in HH:MM format (24-hour)
   - "10 AM" → "10:00"
   - "3 PM" → "15:00"
   - "14:00" → "14:00"
4. service_name: Type of massage/service (optional)
5. duration: Duration in minutes (optional)
6. notes: Special instructions (optional)
7. phone_contact: Client's phone number (optional)
   - CRITICAL: Convert spoken numbers to digits
   - "плюс семь девять девять девять" → "+7999"
   - "восемь девятьсот пять" → "8905"
   - "ноль" / "нолик" → "0"

Examples:
- "Запиши Ольгу на завтра в 14:00" → date: tomorrow's date, time: "14:00"
- "Book Mike for Tuesday 10 AM" → date: next Tuesday, time: "10:00"
- "Добавь Анну в пятницу в 15:30, массаж лица" → date: next Friday, time: "15:30", service: "Массаж лица"
- "Запиши Марию на понедельник в 10:00, телефон плюс семь девять ноль ноль" → date: next Monday, time: "10:00", phone_contact: "+7900"

Return data in the specified JSON format."""
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                ],
                response_format={"type": "json_schema", "json_schema": {
                    "name": "booking_data",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "client_name": {"type": "string"},
                            "date": {"type": "string"},
                            "time": {"type": "string"},
                            "service_name": {"type": ["string", "null"]},
                            "duration": {"type": ["integer", "null"]},
                            "notes": {"type": ["string", "null"]},
                            "phone_contact": {"type": ["string", "null"]}
                        },
                        "required": ["client_name", "date", "time", "service_name", "duration", "notes", "phone_contact"],
                        "additionalProperties": False
                    }
                }},
                temperature=0
            )
            
            import json
            result = json.loads(response.choices[0].message.content)
            booking_data = BookingData(**result)
            
            logger.info(f"Parsed booking: {booking_data.client_name} on {booking_data.date} at {booking_data.time}")
            return booking_data
            
        except Exception as e:
            logger.error(f"Booking parsing failed: {e}")
            return None
    
    @staticmethod
    async def parse_client_query(text: str) -> Optional[ClientQueryData]:
        """
        Parse client query information from transcribed text
        
        Args:
            text: Transcribed text
            
        Returns:
            ClientQueryData object or None if parsing failed
        """
        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": """You are a CRM assistant extracting client query information.

Extract:
1. client_name: Name of the client being asked about
2. query_topic: Category of the query
   - "general" - general information request
   - "medical" - asking about medical history, complaints, anamnesis
   - "financial" - asking about payments, LTV, pricing
   - "history" - asking about session history, last visit

Examples:
- "Кто такая Анна?" → client_name: "Анна", query_topic: "general"
- "Что у Ивана с спиной?" → client_name: "Иван", query_topic: "medical"
- "Когда Ольга последний раз приходила?" → client_name: "Ольга", query_topic: "history"
- "What's Maria's LTV?" → client_name: "Maria", query_topic: "financial"

Return data in the specified JSON format."""
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                ],
                response_format={"type": "json_schema", "json_schema": {
                    "name": "client_query_data",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "client_name": {"type": "string"},
                            "query_topic": {"type": "string", "enum": ["general", "medical", "financial", "history"]}
                        },
                        "required": ["client_name", "query_topic"],
                        "additionalProperties": False
                    }
                }},
                temperature=0
            )
            
            import json
            result = json.loads(response.choices[0].message.content)
            client_query_data = ClientQueryData(**result)
            
            logger.info(f"Parsed client query: {client_query_data.client_name} - {client_query_data.query_topic}")
            return client_query_data
            
        except Exception as e:
            logger.error(f"Client query parsing failed: {e}")
            return None
    
    @staticmethod
    async def parse_new_client(text: str) -> Optional[NewClientData]:
        """
        Parse new client registration information from transcribed text
        
        Args:
            text: Transcribed text
            
        Returns:
            NewClientData object or None if parsing failed
        """
        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": """You are a CRM assistant extracting NEW client registration information.

Extract:
1. client_name: Full client name (capitalize properly)
2. phone_contact: Phone number or other contact info (Telegram, Instagram, WhatsApp, etc.)
   - CRITICAL: Convert spoken numbers to digits
   - "плюс семь один два три" → "+7123"
   - "восемь девятьсот пять" → "8905"
   - "ноль" / "нолик" → "0"
   - Keep @ for Telegram/Instagram handles
   - Keep formatting: +, -, spaces
3. notes: Client preferences, what they like, general information
   - Examples: "Любит массаж лица", "предпочитает утро"
4. anamnesis: Medical information, health conditions, contraindications
   - Examples: "аллергия на мёд", "остеохондроз"

IMPORTANT:
- Separate medical info (anamnesis) from preferences (notes)
- Convert ALL spoken phone numbers to digits
- Extract ALL provided information

Examples:
"Запиши клиента. Имя Полина, телефон плюс семь один два три. Любит массаж лица."
→ client_name: "Полина", phone_contact: "+7123", notes: "Любит массаж лица", anamnesis: null

"Добавь новую клиентку Анна, Instagram @anna_k, аллергия на масла"
→ client_name: "Анна", phone_contact: "Instagram @anna_k", notes: null, anamnesis: "Аллергия на масла"

"Клиент Мария, номер восемь девятьсот пять ноль ноль"
→ client_name: "Мария", phone_contact: "8950 00", notes: null, anamnesis: null

Return data in the specified JSON format."""
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                ],
                response_format={"type": "json_schema", "json_schema": {
                    "name": "new_client_data",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "client_name": {"type": "string"},
                            "phone_contact": {"type": ["string", "null"]},
                            "notes": {"type": ["string", "null"]},
                            "anamnesis": {"type": ["string", "null"]}
                        },
                        "required": ["client_name", "phone_contact", "notes", "anamnesis"],
                        "additionalProperties": False
                    }
                }},
                temperature=0
            )
            
            import json
            result = json.loads(response.choices[0].message.content)
            new_client_data = NewClientData(**result)
            
            logger.info(f"Parsed new client: {new_client_data.client_name}")
            return new_client_data
            
        except Exception as e:
            logger.error(f"New client parsing failed: {e}")
            return None
    
    @staticmethod
    async def parse_session(text: str, current_date: str, service_names: List[str] = None, user_current_date: Optional[str] = None) -> Optional[SessionData]:
        """
        Parse massage session information from transcribed text
        
        Args:
            text: Transcribed text
            current_date: Server current date in YYYY-MM-DD format (for backward compatibility)
            service_names: List of known service names for matching (optional)
            user_current_date: User's local current date in YYYY-MM-DD format (preferred)
            
        Returns:
            SessionData object or None if parsing failed
        """
        try:
            # Use user's local date if provided, otherwise fall back to server date
            reference_date = user_current_date or current_date
            
            # Create service context if available
            services_context = ""
            if service_names:
                services_context = f"\n\nKnown services:\n" + "\n".join([f"- {s}" for s in service_names])
            
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": f"""Extract data from a massage therapist's voice note about a completed session.

Today's date is: {reference_date}{services_context}

CRITICAL DISTINCTION:
- medical_notes: Medical complaints, pain, health conditions, contraindications
  Examples: "болит шея", "остеохондроз", "триггерные точки", "жалуется на"
  
- preference_notes: Non-medical preferences about session delivery
  Examples: "масло без запаха", "сильное давление", "просила", "любит"
  
- session_notes: Technical details of THIS session's treatment
  Examples: "проработали триггеры", "клиент доволен", "ей понравилось"

RULES:
- client_name: Extract full name (capitalize properly)
- service_name: Normalize common abbreviations:
  * "ШВЗ" → "Массаж шейно-воротниковой зоны"
  * If matches known service, use exact name from list
- price: REQUIRED. Extract numeric value.
- duration: Extract minutes if mentioned, else null
- phone_contact: Extract phone if mentioned
- next_appointment_date: Convert relative dates to YYYY-MM-DD:
  * "завтра" → tomorrow's date
  * "во вторник" → next Tuesday
  * "через неделю" → date + 7 days

Example:
Input: "Приходила новенькая, Ольга, жалуется на шею и остеохондроз. Сделали ШВЗ 30 минут за 1500. Ей понравилось, но просила в следующий раз масло без запаха."

Output:
{{
  "client_name": "Ольга",
  "service_name": "Массаж шейно-воротниковой зоны",
  "price": 1500,
  "duration": 30,
  "medical_notes": "Жалобы на шею, остеохондроз",
  "session_notes": "Клиент доволен",
  "preference_notes": "Просит масло без запаха",
  "phone_contact": null,
  "next_appointment_date": null
}}

Return data in the specified JSON format."""
                    },
                    {
                        "role": "user",
                        "content": text
                    }
                ],
                response_format={"type": "json_schema", "json_schema": {
                    "name": "session_data",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "client_name": {"type": "string"},
                            "service_name": {"type": "string"},
                            "price": {"type": "number"},
                            "duration": {"type": ["integer", "null"]},
                            "medical_notes": {"type": ["string", "null"]},
                            "session_notes": {"type": ["string", "null"]},
                            "preference_notes": {"type": ["string", "null"]},
                            "phone_contact": {"type": ["string", "null"]},
                            "next_appointment_date": {"type": ["string", "null"]}
                        },
                        "required": ["client_name", "service_name", "price", "duration", "medical_notes", "session_notes", "preference_notes", "phone_contact", "next_appointment_date"],
                        "additionalProperties": False
                    }
                }},
                temperature=0
            )
            
            import json
            result = json.loads(response.choices[0].message.content)
            session_data = SessionData(**result)
            
            logger.info(f"Parsed session data: {session_data.client_name} - {session_data.service_name}")
            return session_data
            
        except Exception as e:
            logger.error(f"Session parsing failed: {e}")
            return None


# Global instance
ai_service = AIService()
