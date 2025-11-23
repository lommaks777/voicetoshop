# Upgrade Guide - Client Booking System

## Overview
This upgrade adds 4 major features to your Massage Therapist CRM Bot:
1. **Future Booking** - Schedule appointments via voice/text
2. **Client Lookup** - Query client information by voice
3. **Client Edit** - Update client notes without logging a session
4. **Daily Summary** - Automated morning schedule briefings

## Prerequisites
- Python 3.8+
- Existing voicetoshop bot installation
- All dependencies in `requirements.txt` installed

## Deployment Steps

### 1. Backup Your Database
```bash
cd /path/to/voicetoshop
cp users.db users.db.backup
```

### 2. Update Dependencies (if needed)
All required dependencies are already in `requirements.txt`. Verify installation:
```bash
pip install -r requirements.txt
```

### 3. Database Migration
The database migration happens automatically on first startup. The bot will:
- Add `timezone` column to users table
- Set default timezone to 'Europe/Moscow' for existing users
- Create index for performance

**No manual action required** - migration is backward compatible.

### 4. Google Sheets Template Update
Update your template sheet to include the new **Schedule** worksheet:

**Option A: Let the bot create it**
- The bot automatically creates the Schedule worksheet for new bookings
- Existing users: created on first booking attempt

**Option B: Manually create it**
Add a new worksheet named "Schedule" with these columns:
```
Date | Time | Client_Name | Service_Type | Duration | Status | Notes
```

### 5. Restart the Bot
```bash
# Stop the current bot process
# Then start it again
python bot.py
```

You should see in the logs:
```
Database service initialized
Google Sheets service initialized
Scheduler started - morning briefs will be sent at 09:00 daily
Bot is ready!
```

## Configuration

### Timezone Configuration
The daily summary is sent at 09:00 in the timezone specified in your `.env` file:

```env
TIMEZONE=Europe/Moscow
```

To change the summary time, you'll need to modify `bot.py` line ~705:
```python
scheduler.add_job(
    send_morning_briefs,
    trigger='cron',
    hour=9,  # Change this to desired hour
    minute=0,
    ...
)
```

### Morning Brief Behavior
By default, the bot:
- Sends messages **only** if appointments exist for the day
- Skips users with no appointments (silent)
- Runs at 09:00 Moscow time for all users

## New Features Usage

### 1. Creating Bookings (Voice or Text)
Users can now schedule appointments via voice:

**Russian Examples:**
- "Запиши Ольгу на завтра в 14:00"
- "Добавь Анну в пятницу в 15:30, массаж лица"
- "Новый клиент во вторник в 10 утра"

**English Examples:**
- "Book Mike for Tuesday 10 AM"
- "Schedule Anna for tomorrow at 3 PM"

**Response:**
```
✅ Запись создана

📅 25.10 (Среда) в 14:00
👤 Иван Иванов
💆‍♂️ Массаж спины
⏱️ 60 минут
```

### 2. Client Information Queries (Voice or Text)
Users can ask about clients:

**Examples:**
- "Кто такая Анна?"
- "Что у Ивана с спиной?"
- "Напомни про Ольгу"

**Response:**
```
👤 Анна Петрова

🏥 Анамнез:
(15.09): Боль в шее

📝 Заметки:
Любит массаж средней силы

💰 LTV: 15,000₽
📅 Последний визит: 10.10.2023
```

### 3. Client Updates (Voice or Text)
Users can add notes without logging a session:

**Examples:**
- "У Ольги аллергия на мёд" (adds to Anamnesis)
- "Иван просил пожестче" (adds to Notes)
- "Телефон Анны +7 999 123 45 67" (adds to Contacts)

**Response:**
```
📝 Заметка добавлена в карту клиента Ольга

📖 Раздел: Анамнез

✅ Добавлено: "Аллергия на мёд"
```

### 4. Daily Morning Briefs (Automatic)
Every morning at 09:00, users receive:

```
🌅 Доброе утро! План на сегодня (25.10):

10:00 — Анна (Массаж лица)
60 минут
❗ Заметка: Аллергия на цитрусовые

14:00 — Михаил (Спортивный массаж)
90 минут

Хорошего рабочего дня! ☀️
```

**Note:** Only sent if appointments exist for that day.

## Verification

After deployment, verify each feature:

### 1. Check Database Migration
```bash
sqlite3 users.db "PRAGMA table_info(users);"
```
You should see the `timezone` column.

### 2. Test Booking
Send a voice message: "Запиши тест на завтра в 10 утра"
- Should create appointment in Schedule sheet
- Should receive confirmation message

### 3. Test Client Query
Send a voice message: "Кто такой [имя клиента]?"
- Should return client information
- Should show session history

### 4. Test Client Update
Send a voice message: "У [имя] аллергия на..."
- Should append to client's anamnesis
- Should confirm update

### 5. Check Scheduler
Look for this in logs on startup:
```
Scheduler started - morning briefs will be sent at 09:00 daily
```

### 6. Test Morning Brief (Optional)
Manually trigger the morning brief:
```python
# In Python console
import asyncio
from bot import send_morning_briefs
asyncio.run(send_morning_briefs())
```

## Rollback Procedure

If you need to rollback:

### 1. Restore Database Backup
```bash
cd /path/to/voicetoshop
cp users.db.backup users.db
```

### 2. Revert Code Changes
```bash
git checkout HEAD~1 database.py services/ai.py services/sheets.py bot.py
```

### 3. Restart Bot
```bash
python bot.py
```

## Troubleshooting

### Issue: Schedule sheet not created
**Solution:** The bot creates it automatically on first booking. To manually create:
1. Open your Google Sheet
2. Add new worksheet named "Schedule"
3. Add headers: Date, Time, Client_Name, Service_Type, Duration, Status, Notes

### Issue: Morning briefs not sending
**Check:**
1. Scheduler started (check logs)
2. Users have appointments for today
3. Bot has permission to send messages
4. Timezone configured correctly

**Debug:**
```python
# Check if scheduler is running
print(scheduler.running)
# List scheduled jobs
print(scheduler.get_jobs())
```

### Issue: Booking time parsing errors
**Common causes:**
- Ambiguous date references ("Monday" when today is Monday)
- Invalid time formats

**Solution:** Be explicit in voice messages:
- "завтра в 14:00" instead of "в понедельник"
- Use 24-hour format or clear AM/PM

### Issue: Client not found for query
**Causes:**
- Name spelling difference
- Client hasn't been logged yet

**Solution:**
- Check exact name in Clients sheet
- Try different name variations

### Issue: Database migration failed
**Check logs for:**
- Database file permissions
- Disk space
- SQLite version

**Manual migration:**
```bash
sqlite3 users.db "ALTER TABLE users ADD COLUMN timezone TEXT DEFAULT 'Europe/Moscow';"
```

## Performance Considerations

### Database
- Current architecture supports ~1000 concurrent users
- For larger scale, consider PostgreSQL migration

### Google Sheets API
- Rate limits: 100 requests per 100 seconds per user
- Bot implements delays to avoid rate limiting
- Large appointment lists may take longer to process

### Scheduler
- Morning brief processes users sequentially
- 0.5s delay between sends to avoid Telegram rate limits
- ~1000 users = ~8 minutes to complete all sends

## Monitoring

### Key Metrics to Watch
1. **Morning brief delivery rate** (check logs daily)
2. **Booking creation success rate**
3. **API errors** (Google Sheets, OpenAI, Telegram)
4. **Database query performance**

### Log Locations
All logs include timestamps and severity levels:
```
INFO - Database service initialized
INFO - Sent morning brief to user 123456 with 3 appointments
ERROR - Failed to send morning brief to user 789012: [error]
```

### Recommended Monitoring
- Set up log aggregation (ELK, Datadog, etc.)
- Alert on ERROR-level logs
- Monitor scheduler job execution
- Track API quota usage

## Support

If you encounter issues:
1. Check logs for specific error messages
2. Verify all dependencies installed correctly
3. Ensure Google Sheets permissions are correct
4. Review the IMPLEMENTATION_NOTES.md for details

## Future Enhancements

Potential Phase 2 features:
- Per-user timezone support
- Appointment conflict detection
- Client reminders (sent to clients)
- Google Calendar integration
- Analytics dashboard
- Multi-language support

---

**Version:** 1.0.0  
**Last Updated:** November 23, 2025  
**Compatibility:** Python 3.8+, Aiogram 3.13+
