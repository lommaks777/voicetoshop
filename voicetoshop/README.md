# Massage Therapist CRM Bot

Multi-tenant SaaS CRM system for massage therapists. Each user owns their data in their personal Google Sheet.

## Architecture

- **Multi-Tenant**: Each therapist has their own Google Sheet
- **Data Ownership**: Users create and own their sheets, grant access to bot
- **Privacy-First**: No medical data stored in bot infrastructure
- **Stateless**: Bot acts as interface, all data in user's sheets

## Features

- 🎤 Voice-to-text session logging
- 📊 Client management with medical history (anamnesis)
- 💰 Financial tracking (LTV, session prices)
- 📅 Appointment reminders
- 🔐 Secure multi-user architecture

## Setup

### 1. Install Dependencies

```bash
cd voicetoshop
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and fill in:

```bash
cp .env.example .env
```

Required variables:
- `BOT_TOKEN`: Telegram bot token from @BotFather
- `OPENAI_API_KEY`: OpenAI API key for Whisper + GPT
- `GOOGLE_SHEETS_CREDENTIALS_BASE64`: Base64-encoded service account JSON
- `TEMPLATE_SHEET_URL`: Public template sheet URL

### 3. Create Template Sheet

1. Create a new Google Sheet
2. Add three tabs with exact names:
   - **Clients**: Headers: `Name | Phone_Contact | Anamnesis | Notes | LTV | Last_Visit_Date | Next_Reminder`
   - **Sessions**: Headers: `Date | Client_Name | Service_Type | Duration | Price | Session_Notes`
   - **Services**: Headers: `Service_Name | Default_Price | Default_Duration`
3. Share sheet as "Anyone with link can view"
4. Copy URL to `TEMPLATE_SHEET_URL` in .env

### 4. Setup Google Service Account

1. Create a Google Cloud Project
2. Enable Google Sheets API
3. Create Service Account
4. Download JSON key
5. Base64 encode the key:
   ```bash
   base64 -w 0 service-account-key.json
   ```
6. Paste result into `GOOGLE_SHEETS_CREDENTIALS_BASE64`

### 5. Run Bot

```bash
python bot.py
```

## User Workflow

### Onboarding

1. User sends `/start` to bot
2. Bot provides onboarding instructions with service account email
3. User copies template sheet
4. User shares their copy with bot's service account (Editor access)
5. User sends sheet URL to bot
6. Bot validates access and registers user

### Session Logging

**Voice Input Example:**
> "Приходила новенькая, Ольга, жалуется на шею и остеохондроз. Сделали ШВЗ 30 минут за 1500. Ей понравилось, но просила в следующий раз масло без запаха."

**Bot Actions:**
1. Transcribes voice via Whisper API
2. Extracts:
   - Client: Ольга
   - Service: ШВЗ (Массаж шейно-воротниковой зоны)
   - Price: 1500₽
   - Medical notes: "Жалобы на шею, остеохондроз"
   - Preference notes: "Просит масло без запаха"
3. Writes to Google Sheets:
   - **Sessions** tab: Appends new session
   - **Clients** tab: Updates client (or creates if new)
     - Appends to Anamnesis: "25.10: Жалобы на шею, остеохондроз"
     - Appends to Notes: "Просит масло без запаха"
     - Updates LTV: +1500₽
     - Updates Last_Visit_Date

### Client Lookup

```
/client Ольга
```

Shows:
- Contact info
- Full anamnesis history
- Preferences
- LTV
- Last visit date
- Recent session history

## Architecture Changes from Original

### Removed
- `ALLOWED_USER_ID` - no longer single-user
- `GOOGLE_SHEET_KEY` - each user has own sheet
- Global spreadsheet object in sheets.py
- Global lock (multi-user safe)
- Inventory management logic

### Added
- `database.py` - SQLite user registry
- `TEMPLATE_SHEET_URL` config
- `DATABASE_PATH` config
- Multi-tenant sheets service
- `SessionData` Pydantic model
- `parse_session()` AI method
- User context middleware
- Onboarding flow
- Privacy-compliant logging

### Refactored
- `sheets.py`: All methods accept `sheet_id` parameter
- `ai.py`: Classification updated for massage domain
- `bot.py`: Complete rewrite for multi-user
- `config.py`: Removed single-user validation

## Data Flow

```
User Voice → Whisper API → Transcription
           ↓
    GPT-4 Classification → Intent
           ↓
    GPT-4 Extraction → SessionData
           ↓
    sheets_service.log_session(sheet_id, data)
           ↓
    User's Google Sheet (Sessions + Clients tabs)
```

## Privacy & Compliance

- **No Medical Data in Logs**: Client names and medical notes never logged
- **Pseudonymous Logging**: Only Telegram IDs logged (e.g., "User <TG_ID:12345> logged session")
- **User Data Sovereignty**: All data in user-owned Google Sheets
- **Revocable Access**: Users can remove bot access anytime
- **GDPR Aligned**: Minimal data collection, user control, data portability

## Database Schema

```sql
CREATE TABLE users (
    tg_id INTEGER PRIMARY KEY,          -- Telegram User ID
    sheet_id TEXT NOT NULL UNIQUE,      -- Google Sheet ID
    is_active BOOLEAN DEFAULT TRUE,     -- Soft delete flag
    created_at TIMESTAMP,               -- Registration date
    last_active_at TIMESTAMP            -- Last activity
);
```

## Google Sheets Structure

### Clients Tab
| Name | Phone_Contact | Anamnesis | Notes | LTV | Last_Visit_Date | Next_Reminder |
|------|---------------|-----------|-------|-----|-----------------|---------------|
| Ольга | +7... | 25.10: Жалобы на шею | Просит масло без запаха | 1500 | 2023-10-25 | |

### Sessions Tab
| Date | Client_Name | Service_Type | Duration | Price | Session_Notes |
|------|-------------|--------------|----------|-------|---------------|
| 2023-10-25 | Ольга | ШВЗ | 30 | 1500 | Клиент доволен |

### Services Tab
| Service_Name | Default_Price | Default_Duration |
|-------------|---------------|------------------|
| Массаж шейно-воротниковой зоны | 1500 | 30 |

## Troubleshooting

### "Permission denied" error
- User needs to share sheet with service account as **Editor**, not Viewer
- Check service account email in bot's onboarding message

### "Sheet not found" error
- Verify sheet URL is correct
- Ensure sheet is not deleted
- Check sheet ID extraction

### "Transcription failed"
- Check OpenAI API key
- Verify audio file format (Telegram voice is .ogg)
- Check API quota

### Database errors
- Ensure `DATABASE_PATH` directory exists and is writable
- Check SQLite file permissions

## Development

### Running Tests
```bash
pytest tests/
```

### Code Structure
```
voicetoshop/
├── bot.py              # Main bot logic, handlers
├── config.py           # Environment configuration
├── database.py         # SQLite user registry
├── services/
│   ├── ai.py          # OpenAI integration (Whisper, GPT)
│   └── sheets.py      # Google Sheets operations
├── requirements.txt    # Python dependencies
└── .env               # Environment variables (create from .env.example)
```

## License

MIT

## Support

For issues or questions, please open a GitHub issue or contact support.
