import logging
import os
from datetime import datetime, timedelta
from typing import List, Optional
from pathlib import Path
from pydantic import BaseModel, Field
from openai import AsyncOpenAI
from config import Config

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
    notes: str = Field(description="Notes or additional information to add about the client")


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
        Classify if message is about Session, Client Edit, or Query
        
        Returns:
            "log_session", "client_update", "consultation", or "add_service"
        """
        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": """You are an expert assistant for massage therapists. Classify the therapist's message intent:

- LOG_SESSION: Recording a completed session (contains client, service, price, complaints)
- CLIENT_UPDATE: Adding notes about client WITHOUT session/payment details
- CONSULTATION: Asking about client history or looking up information
- ADD_SERVICE: Defining a new service type in their catalog

Key indicators:
- LOG_SESSION: mentions price, completed session, "сделали", "приходила", service type
- CLIENT_UPDATE: ONLY preferences, interests, characteristics WITHOUT purchase details
- CONSULTATION: questions about clients, "кто", "когда", "сколько"
- ADD_SERVICE: defining new service, "добавь услугу"

Respond with only one word: "log_session", "client_update", "consultation", or "add_service"."""
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
            return classification if classification in ["log_session", "client_update", "consultation", "add_service"] else "log_session"
            
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
2. Notes/information to add about the client (preferences, interests, characteristics, etc.)

IMPORTANT:
- The client name should be the person's full name
- Notes should be descriptive information about the client
- Return data in the specified JSON format."""
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
                            "notes": {"type": "string"}
                        },
                        "required": ["client_name", "notes"],
                        "additionalProperties": False
                    }
                }},
                temperature=0
            )
            
            import json
            result = json.loads(response.choices[0].message.content)
            client_edit_data = ClientEditData(**result)
            
            logger.info(f"Parsed client edit: {client_edit_data.client_name}")
            return client_edit_data
            
        except Exception as e:
            logger.error(f"Client edit parsing failed: {e}")
            return None
    
    @staticmethod
    async def parse_session(text: str, current_date: str, service_names: List[str] = None) -> Optional[SessionData]:
        """
        Parse massage session information from transcribed text
        
        Args:
            text: Transcribed text
            current_date: Current date in YYYY-MM-DD format
            service_names: List of known service names for matching (optional)
            
        Returns:
            SessionData object or None if parsing failed
        """
        try:
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

Today's date is: {current_date}{services_context}

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
