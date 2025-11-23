# Quick Start Guide

Get the Massage Therapist CRM bot running in 10 minutes.

## Prerequisites

- Python 3.11+
- Telegram account
- Google Cloud account
- OpenAI API account

## Step-by-Step Setup

### 1. Install Dependencies (2 min)

```bash
cd voicetoshop
pip install -r requirements.txt
```

### 2. Create Telegram Bot (2 min)

1. Open Telegram, search for `@BotFather`
2. Send `/newbot`
3. Follow prompts to create bot
4. Copy the token (looks like `123456:ABC-DEF...`)

### 3. Setup Google Service Account (3 min)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create new project or select existing
3. Enable **Google Sheets API**
4. Go to **IAM & Admin** → **Service Accounts**
5. Click **Create Service Account**
6. Name it `massage-crm-bot`, click Create
7. Skip roles (click Continue twice)
8. Click on the service account email
9. Go to **Keys** tab → **Add Key** → **Create New Key** → **JSON**
10. Download the JSON file
11. Copy the `client_email` from JSON (save for later)
12. Encode the JSON file:
    ```bash
    base64 -w 0 /path/to/service-account-key.json > encoded.txt
    # Copy contents of encoded.txt
    ```

### 4. Create Template Google Sheet (2 min)

1. Create [new Google Sheet](https://sheets.google.com/)
2. Rename it to "Massage CRM Template"
3. Create 3 tabs (rename Sheet1, add 2 more):

**Tab 1: Clients**
```
Name | Phone_Contact | Anamnesis | Notes | LTV | Last_Visit_Date | Next_Reminder
```

**Tab 2: Sessions**
```
Date | Client_Name | Service_Type | Duration | Price | Session_Notes
```

**Tab 3: Services**
```
Service_Name | Default_Price | Default_Duration
```

Add sample service:
```
Массаж шейно-воротниковой зоны | 1500 | 30
```

4. Click **Share** → Change to **Anyone with link can view**
5. Copy the sheet URL

### 5. Configure Environment (1 min)

Create `.env` file:

```bash
cp .env.example .env
nano .env  # or use your favorite editor
```

Fill in:
```env
BOT_TOKEN=<your_telegram_bot_token>
OPENAI_API_KEY=<your_openai_api_key>
GOOGLE_SHEETS_CREDENTIALS_BASE64=<base64_encoded_json>
TEMPLATE_SHEET_URL=<your_template_sheet_url>
DATABASE_PATH=./users.db
TIMEZONE=Europe/Moscow
```

### 6. Run Bot (1 min)

```bash
python bot.py
```

You should see:
```
Starting Massage CRM Bot...
Database service initialized
Google Sheets service initialized
Bot is ready!
```

## Test the Bot

### Test Onboarding

1. Open Telegram, find your bot
2. Send `/start`
3. You should see onboarding instructions with service account email
4. Copy the template sheet:
   - Open template URL
   - File → Make a copy
5. Share your copy:
   - Click Share button
   - Add service account email as **Editor**
6. Send sheet URL to bot
7. Bot should respond: "✅ Готово!"

### Test Session Logging

Send voice message (or text for testing):
```
Приходила Ольга, жалуется на шею. Сделали ШВЗ за 1500. 
Ей понравилось.
```

Bot should:
1. Show "🎧 Обрабатываю..."
2. Return confirmation with client, service, price
3. Update your Google Sheet

### Test Client Lookup

```
/client Ольга
```

Should show client info with session history.

## Troubleshooting

### "Configuration validation failed"
- Check all env vars are set
- Verify no extra spaces in .env

### "Permission denied"
- Ensure service account added as **Editor**, not Viewer
- Check you copied correct `client_email`

### "OpenAI API Error"
- Verify API key is valid
- Check you have credits in OpenAI account

### "Sheet not found"
- Verify sheet URL is correct
- Ensure sheet is not deleted
- Check sheet ID in URL matches what you sent

## Production Deployment

### Option 1: Docker (Recommended)

```bash
# Build image
docker build -t massage-crm-bot .

# Run container
docker run -d \
  --name massage-crm-bot \
  --env-file .env \
  -v $(pwd)/users.db:/app/users.db \
  massage-crm-bot
```

### Option 2: Systemd Service

Create `/etc/systemd/system/massage-crm-bot.service`:

```ini
[Unit]
Description=Massage CRM Telegram Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/massage-crm-bot/voicetoshop
Environment="PATH=/home/ubuntu/.local/bin:/usr/bin"
EnvironmentFile=/home/ubuntu/massage-crm-bot/voicetoshop/.env
ExecStart=/usr/bin/python3 bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable massage-crm-bot
sudo systemctl start massage-crm-bot
sudo systemctl status massage-crm-bot
```

### Option 3: Railway/Heroku

1. Create `Procfile`:
   ```
   worker: python voicetoshop/bot.py
   ```

2. Deploy:
   ```bash
   # Railway
   railway up
   
   # Heroku
   heroku create
   git push heroku main
   ```

## Monitoring

### Check logs
```bash
# Docker
docker logs -f massage-crm-bot

# Systemd
journalctl -u massage-crm-bot -f

# Direct
tail -f /var/log/massage-crm-bot.log
```

### Check database
```bash
sqlite3 users.db "SELECT COUNT(*) FROM users WHERE is_active=1;"
```

### Health check
Send `/stats` to bot to see user count.

## Support

- 📖 Full docs: `README.md`
- 🔄 Migration guide: `MIGRATION.md`
- ✅ Implementation details: `IMPLEMENTATION_SUMMARY.md`
- 🐛 Issues: Open GitHub issue

## Next Steps

1. ✅ Test with multiple users
2. ✅ Monitor error rates
3. ✅ Collect user feedback
4. ✅ Plan Phase 2 features (appointments, analytics)

---

**You're all set!** 🎉

Start inviting massage therapists to use your CRM bot.
