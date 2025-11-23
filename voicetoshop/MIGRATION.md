# Migration Guide: Single-User to Multi-User SaaS

## Overview

This guide explains how to migrate from the old single-user warehouse bot to the new multi-user massage therapist CRM.

## What Changed

### Architecture
- **Old**: One bot serves one user with one Google Sheet
- **New**: One bot serves multiple users, each with their own Google Sheet

### Data Model
- **Old**: Inventory (Products, Sizes, Stock)
- **New**: Sessions (Clients, Services, Medical Notes)

### Environment Variables

**Removed:**
- `ALLOWED_USER_ID` - no longer needed (multi-user)
- `GOOGLE_SHEET_KEY` - each user has their own sheet

**Added:**
- `TEMPLATE_SHEET_URL` - public template for users to copy
- `DATABASE_PATH` - SQLite database location

## Migration Options

### Option 1: Fresh Start (Recommended)

**Best for**: New business domain (massage therapy vs. inventory)

1. Deploy new bot version
2. Create template Google Sheet with massage-specific tabs
3. Set `TEMPLATE_SHEET_URL` in environment
4. Users go through onboarding to connect their sheets

**Pros:**
- Clean separation
- No data migration needed
- Domain-specific structure

**Cons:**
- Old data stays in old system
- Users need to onboard

### Option 2: Keep Old Bot Running

**Best for**: If you need to support existing single-user deployment

1. Deploy new bot as separate instance (new bot token)
2. Old bot continues serving original user
3. New bot serves new multi-user base

**Pros:**
- No disruption to existing user
- Zero migration risk

**Cons:**
- Two bots to maintain
- Duplicate infrastructure

### Option 3: Migrate Existing User to New System

**Best for**: Single existing user wants to continue with new system

**Steps:**

1. **Backup existing data**
   ```bash
   # Export current Google Sheet to Excel/CSV
   ```

2. **Create new sheet from template**
   - Copy new template structure (Clients, Sessions, Services)
   - Manually map old data to new structure:
     - Old "Clients" → New "Clients" (update columns)
     - Old "Transactions" → New "Sessions" (filter by type="Sale")
     - Old "Inventory" → Delete (not relevant for massage)

3. **Onboard in new bot**
   - Send `/start` to new bot
   - Follow onboarding flow
   - Connect new sheet

4. **Verify data**
   - Test session logging
   - Check client lookup
   - Verify LTV calculations

5. **Decommission old bot**
   - Stop old bot process
   - Archive old code

## Data Mapping Reference

### Old → New Table Mapping

**Clients Tab:**
| Old Column | New Column | Notes |
|------------|------------|-------|
| Name | Name | Direct mapping |
| Instagram | Phone_Contact | Combine contact info |
| Telegram | Phone_Contact | Combine contact info |
| Description | Notes | Preferences only |
| Transactions | (deleted) | Replaced by Sessions tab |
| Reminder_Date | Next_Reminder | Direct mapping |
| Reminder_Text | (deleted) | Simplified reminders |

**New: Sessions Tab** (from old Transactions)
| Old Column (Transactions) | New Column | Notes |
|---------------------------|------------|-------|
| Timestamp → Date | Date | Convert format |
| Client_Name | Client_Name | Direct mapping |
| Item_Name | Service_Type | Rename context |
| Price | Price | Direct mapping |
| (none) | Duration | New field |
| (none) | Session_Notes | New field |

**Services Tab** (NEW)
- Manually create based on common massage services
- Example entries:
  - "Массаж спины", 2000, 60
  - "Массаж шейно-воротниковой зоны", 1500, 30

### Inventory → Services Conversion

The old "Inventory" tab tracked physical products. The new "Services" tab tracks service types.

**Not migrated:**
- Product SKUs
- Sizes
- Stock quantities

**New approach:**
- Services don't have "stock"
- Services have default prices and durations
- AI extracts service type from voice

## Testing Migration

1. **Create test sheet** with sample data
2. **Run session logging** test:
   ```
   Voice: "Сделал массаж Тест Клиенту за 1000 рублей"
   Expected: Session logged, client created/updated
   ```
3. **Run client lookup** test:
   ```
   Command: /client Тест Клиент
   Expected: Shows client info with session history
   ```
4. **Verify permission handling**:
   - Remove bot access from sheet
   - Send voice message
   - Expected: Permission error with instructions

## Rollback Plan

If migration fails:

1. **Stop new bot**
   ```bash
   pkill -f "python bot.py"
   ```

2. **Restore old bot**
   ```bash
   git checkout <old-commit-hash>
   python bot.py
   ```

3. **Restore old .env**
   - Re-add `ALLOWED_USER_ID`
   - Re-add `GOOGLE_SHEET_KEY`

4. **Verify old bot works**
   - Send test voice message
   - Check inventory update

## Post-Migration Checklist

- [ ] Old bot stopped
- [ ] New bot running
- [ ] Database initialized (`users.db` exists)
- [ ] Template sheet created and public
- [ ] Service account has correct permissions
- [ ] Test onboarding flow works
- [ ] Test session logging works
- [ ] Test client lookup works
- [ ] Error handling tested (permission errors)
- [ ] Logs show privacy-compliant format (no medical data)

## Support

For migration issues:
1. Check logs: `tail -f bot.log`
2. Verify environment variables
3. Test Google Sheets API access
4. Check database file permissions

## Timeline Recommendation

- **Week 1**: Deploy new bot, create template
- **Week 2**: Test with 1-2 pilot users
- **Week 3**: Open to all users
- **Week 4**: Decommission old bot (if applicable)

## Breaking Changes

⚠️ **Warning**: These are breaking changes from old version

1. **No backward compatibility** with old inventory model
2. **Different command structure** (no /edit for inventory)
3. **New onboarding required** for all users
4. **Different sheet structure** - cannot use old sheets directly
5. **Removed features**:
   - Supply/restock tracking
   - Inventory queries
   - Stock level warnings
   - Undo functionality (temporary)

## Benefits of Migration

✅ **For Users:**
- Own their data (data sovereignty)
- Can access/edit in Google Sheets directly
- No central server stores medical data
- Can revoke bot access anytime

✅ **For Developers:**
- Scalable multi-tenant architecture
- No data migration on user growth
- Reduced infrastructure costs (no central database)
- GDPR/HIPAA aligned

✅ **For Business:**
- SaaS model enables revenue growth
- Lower operational risk (users own data)
- Easier compliance audits
- Horizontal scalability
