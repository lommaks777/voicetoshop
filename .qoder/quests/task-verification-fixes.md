# Stress Test Failure Remediation

## Overview

This design addresses critical failures discovered during stress testing of the Telegram massage CRM bot. The issues span data validation, error handling, and user feedback mechanisms.

---

## Issue Classification

| Test ID | Issue | Severity | Category |
|---------|-------|----------|----------|
| 2.3 | Invalid dates accepted (32/33 Dec, "позавчера") | CRITICAL | Data Validation |
| 2.4 | Empty bookings created without name/time | CRITICAL | Required Field Validation |
| 3.1 | Generic error on permission denial | MEDIUM | Error Messaging |
| 3.3 | Header row restoration not implemented | LOW | Data Recovery |
| 4.2 | Long audio notes (45s) fail to save | CRITICAL | Audio Processing |
| 4.3 | Timezone change confirmation missing | MEDIUM | User Feedback |
| 4.4 | Audio notes with client name fail | CRITICAL | Parsing Logic |

---

## Issue Analysis

### Test 2.3: Invalid Date Validation

**Current Behavior:** AI accepts impossible dates (32 Dec, 33 Dec, "позавчера") without validation

**Root Cause:** 
- AI `parse_booking()` generates dates without calendar validation
- No post-processing validation before database insertion
- Relative date logic lacks bounds checking

**Impact:** Data corruption in Schedule sheet, impossible appointments in calendar views

---

### Test 2.4: Missing Required Fields

**Current Behavior:** Bot creates booking with "не указано" client and "00:00" time when essential data missing

**Root Cause:**
- AI parsing returns partial data structures
- No validation gate before `add_booking()` call
- Default values used instead of rejecting incomplete input

**Impact:** Pollutes Schedule with unusable records, degrades data quality

---

### Test 3.1: Permission Denied Error Message

**Current Behavior:** Shows raw API error: `{'code': 403, 'message': 'The caller does not have permission', 'status': 'PERMISSION_DENIED'}`

**Root Cause:**
- Permission exception partially handled in session flow
- Booking flow shows raw error dict instead of user-friendly message
- Inconsistent error handling across operation types

**Impact:** Poor user experience, non-actionable error feedback

---

### Test 3.3: Header Row Recovery

**Current Behavior:** When headers deleted, data appends to wrong row; headers not restored

**Root Cause:**
- `_ensure_worksheets()` only creates missing worksheets, not missing headers
- No header integrity check before write operations
- Data positioning relies on row count, not header presence

**Impact:** Data misalignment, column mapping breaks

---

### Test 4.2: Long Audio Transcription Failure

**Current Behavior:** 45-second audio fails with "ошибка обновления информации"

**Root Cause Analysis Needed:**
- Possible Whisper API timeout on long audio
- Client update parsing failure on lengthy transcription
- Sheet API cell size limit (50,000 chars per cell)
- Network timeout during audio download/upload

**Impact:** Lost data, user frustration, cannot record detailed notes

---

### Test 4.3: Timezone Change Feedback Gap

**Current Behavior:** 
- Shows "определяю часовой пояс" but never confirms
- Booking created correctly but user uncertain of timezone change
- Second attempt shows "думаю…" indefinitely

**Root Cause:**
- `/set_timezone` implementation incomplete
- Timezone detection succeeds but confirmation message missing
- Async race condition or exception swallowed

**Impact:** User uncertainty, perceived system failure

---

### Test 4.4: Audio Notes with Client Name

**Current Behavior:** Audio note "Добавь заметки Аркадий Балитшея" fails with "ошибка обновления информации"

**Root Cause:**
- Similar to Test 4.2, likely in client update flow
- AI classification or parsing issue
- Exception in `handle_client_update()` not surfaced properly

**Impact:** Cannot add voice notes to client records

---

## Solution Design

### 1. Date Validation Layer

**Objective:** Reject calendar-invalid and past dates before database operations

#### Validation Rules

| Rule | Description | Example |
|------|-------------|---------|
| Calendar validity | Day must exist in month/year | Reject: 32 Dec, 30 Feb |
| Future-only | Booking date >= current date | Reject: "позавчера", yesterday |
| Range bounds | Date within reasonable future (e.g., 2 years) | Reject: bookings in 2100 |

#### Implementation Strategy

**Location:** Post-AI parsing, pre-database insertion

**Validation Flow:**

```
AI parse_booking() → Date Validator → add_booking() or rejection message
```

**Validator Behavior:**

1. Parse AI-generated date string (YYYY-MM-DD format)
2. Verify calendar validity using datetime library
3. Compare against user's local current date
4. Provide specific error message on failure

**Error Message Templates:**

| Failure Type | User Message |
|--------------|--------------|
| Invalid calendar date | "❌ Дата {date} не существует в календаре. Проверьте день и месяц." |
| Past date | "❌ Нельзя создать запись на прошедшую дату ({date}). Укажите будущую дату." |
| Ambiguous relative | "❌ Не удалось определить дату из '{input}'. Укажите конкретную дату или день недели." |

---

### 2. Required Field Validation

**Objective:** Prevent booking creation without essential fields (name, date, time)

#### Validation Gates

**Pre-Insertion Check:**

| Field | Validation | Rejection Condition |
|-------|------------|---------------------|
| client_name | Non-empty, not "не указано" | Empty, whitespace, placeholder text |
| date | Valid YYYY-MM-DD | Missing, invalid format |
| time | Valid HH:MM | Missing, "00:00" (unless explicitly requested) |

#### Implementation Strategy

**Validation Point:** After AI parsing, before `add_booking()` call

**Rejection Flow:**

```
parse_booking() → Field Validator → [PASS: create booking] / [FAIL: request clarification]
```

**Clarification Prompt:**

When validation fails, bot must ask user for missing information:

```
❌ Не хватает информации для создания записи:

{missing_fields_list}

Пожалуйста, укажите все данные.
```

**Example Missing Fields List:**

- ❓ Имя клиента не указано
- ❓ Время записи отсутствует
- ❓ Дата не определена

---

### 3. Unified Permission Error Handling

**Objective:** Consistent, actionable error messages across all Google Sheets operations

#### Error Message Standard

**Template for Permission Denial:**

```
🚫 **Я потерял доступ к вашей таблице**

Проверьте, что:
1. Таблица не удалена
2. Мой робот имеет доступ Редактора:
   {service_account_email}

Если вы удалили доступ, откройте таблицу и снова добавьте меня.
```

#### Implementation Strategy

**Location:** Exception handlers in all operation flows

**Affected Flows:**
- `handle_session()` ✅ (already implemented)
- `handle_booking()` → needs implementation
- `handle_client_update()` → needs implementation
- `handle_add_client()` → needs implementation

**Centralized Error Handler:**

Create shared error response function to ensure consistency:

```
async format_permission_error() → formatted message string
```

All operation handlers must catch `PermissionError` and use this formatter.

---

### 4. Header Integrity Verification

**Objective:** Detect and restore missing headers before data operations

#### Detection Strategy

**Pre-Write Check:**

Before any append or update operation:

1. Read first row of target worksheet
2. Compare against expected header schema
3. Restore if missing or mismatched

#### Header Restoration Logic

**Restoration Trigger Conditions:**

| Condition | Action |
|-----------|--------|
| Row 1 completely empty | Write full header row |
| Row 1 contains data but no headers | Insert new row 1, shift data down |
| Column count mismatch | Append missing columns to row 1 |

**Expected Header Schemas:**

| Worksheet | Headers |
|-----------|---------|
| Sessions | Date, Client_Name, Service_Type, Duration, Price, Session_Notes |
| Clients | Name, Contact, Anamnesis, Notes, LTV, Last_Visit_Date, Next_Reminder |
| Schedule | Date, Time, Client_Name, Service_Type, Duration, Status, Notes, Phone_Contact |
| Services | Service_Name, Default_Price, Default_Duration |

#### Implementation Strategy

**Location:** `sheets_service._ensure_headers()` - new method called by all write operations

**Behavior:**

- Non-destructive: preserve existing data
- Idempotent: safe to call multiple times
- Logged: record header restorations for debugging

---

### 5. Long Audio Processing Resilience

**Objective:** Successfully process and store audio transcriptions up to 60 seconds

#### Root Cause Investigation Needed

**Diagnostic Steps:**

1. Add detailed logging to audio processing pipeline
2. Measure transcription time for various audio lengths
3. Test Whisper API timeout limits
4. Verify Google Sheets cell character limits
5. Check for exception swallowing in async handlers

#### Mitigation Strategies

**Strategy 1: Timeout Extension**

- Increase HTTP client timeout for Whisper API calls
- Add retry logic with exponential backoff

**Strategy 2: Content Length Validation**

- After transcription, check character count
- If exceeds safe threshold (e.g., 40,000 chars), truncate with warning

**Strategy 3: Error Surfacing**

- Ensure all exceptions in `handle_client_update()` are logged
- Return specific error messages instead of generic "ошибка обновления"

**Strategy 4: Chunking (if needed)**

- For extremely long transcriptions, split into multiple append operations
- Preserve chronological order with timestamps

#### Expected Behavior After Fix

| Audio Length | Expected Outcome |
|--------------|------------------|
| 0-30 seconds | ✅ Process normally |
| 30-60 seconds | ✅ Process with extended timeout |
| 60+ seconds | ⚠️ Warning message + truncated save or rejection |

---

### 6. Timezone Update Confirmation

**Objective:** Provide immediate, clear feedback when timezone changes

#### Issue Diagnosis

**Investigation Points:**

1. Check if `detect_timezone()` completes successfully
2. Verify `update_user_timezone()` database commit
3. Ensure confirmation message sends after DB update
4. Test for exception in message formatting

#### Confirmation Message Enhancement

**Success Response Template:**

```
✅ **Часовой пояс обновлён**

🌍 Город: {city}
⏰ Часовой пояс: {timezone}

Утренние уведомления будут приходить в 09:00 по вашему местному времени.
```

**Timing Diagnostics:**

Add logging checkpoints:

1. "Timezone detection started for city: {city}"
2. "Timezone detected: {timezone}"
3. "Database update initiated"
4. "Database update confirmed"
5. "Sending confirmation message"

#### Fallback Behavior

If timezone detection takes >5 seconds:

```
⏳ Определяю часовой пояс для {city}...

Это может занять несколько секунд.
```

Followed by confirmation or error within 10 seconds maximum.

---

### 7. Audio Notes with Client Name Parsing

**Objective:** Reliably extract and save client notes from voice messages

#### Root Cause Analysis

**Hypothesis:**

Issue likely in one of these layers:

1. **Classification:** Misclassifies as different intent
2. **Parsing:** `parse_client_edit()` fails to extract client name
3. **Update:** `update_client_info()` throws exception
4. **Transcription:** Whisper misunderstands client name

#### Diagnostic Logging Enhancement

**Log Points to Add:**

- Message classification result
- Parsed client edit data (sanitized)
- Database query result for client lookup
- Sheet update operation status

#### Test Case Coverage

| Input | Expected client_name | Expected target_field | Expected content |
|-------|---------------------|----------------------|------------------|
| "Добавь заметки Аркадий Балитшея" | "Аркадий Балитшея" | notes | (context-dependent) |
| "У Марии аллергия на мёд" | "Мария" | anamnesis | "Аллергия на мёд" |
| "Иван любит сильный массаж" | "Иван" | notes | "Любит сильный массаж" |

#### Error Handling Improvement

**Current:** "❌ Ошибка обновления информации"

**Improved Error Messages:**

| Failure Point | User Message |
|---------------|--------------|
| Client name not parsed | "❌ Не удалось определить имя клиента. Укажите имя явно: 'У [Имя] ...' " |
| Client not found | "❌ Клиент '{name}' не найден. Проверьте написание имени." |
| Empty content | "❌ Не указана информация для добавления. Что записать в заметки?" |
| Sheet API error | "❌ Ошибка сохранения в таблицу: {specific_error}" |

---

## Implementation Priority

| Priority | Issues | Rationale |
|----------|--------|-----------|
| **P0 - Critical** | 2.3, 2.4, 4.2, 4.4 | Data corruption, core functionality broken |
| **P1 - High** | 3.1, 4.3 | Poor UX, user confusion |
| **P2 - Medium** | 3.3 | Edge case, recoverable manually |

---

## Testing Verification Plan

### Test Case Matrix

| Test ID | Verification Method | Success Criteria |
|---------|---------------------|------------------|
| 2.3 | Input "Запиши на 32 декабря" | Bot rejects with calendar error message |
| 2.3 | Input "Запиши на позавчера" | Bot rejects with past date error |
| 2.4 | Input "Запиши на массаж" | Bot asks for missing name and time |
| 3.1 | Revoke sheet access, attempt booking | User-friendly permission error displayed |
| 3.3 | Delete headers, create session | Headers automatically restored |
| 4.2 | Send 45-second audio note | Note saved successfully or specific error shown |
| 4.3 | Run `/set_timezone Владивосток` | Confirmation message received within 10s |
| 4.4 | Audio "Добавь заметки [Имя]" | Note added or specific error shown |

### Regression Testing

After fixes, re-run all passing tests to ensure no new issues introduced.

---

## Non-Functional Requirements

### Performance Targets

| Operation | Current | Target | Notes |
|-----------|---------|--------|-------|
| Date validation | N/A | <50ms | Synchronous, in-memory check |
| Header restoration | N/A | <500ms | One-time per session |
| Long audio processing | Fails | <15s for 60s audio | Whisper API dependent |

### Logging Standards

**All error paths must log:**

1. Error type and code
2. User action context (sanitized)
3. Timestamp
4. Recovery action taken

**Example Log Entry:**

```
ERROR: Date validation failed | User: <TG_ID:12345> | Input: "32 декабря" | Action: Rejected with calendar error
```

---

## Data Integrity Safeguards

### Validation Layer Architecture

```
User Input → AI Parsing → Validation Gate → Database Operation → Success Response
                              ↓ (on failure)
                         Error Message → User
```

**Validation Gate Responsibilities:**

- Enforce schema compliance
- Check business logic constraints
- Prevent impossible/corrupt data
- Provide actionable error messages

### Rollback Considerations

**For Critical Issues:**

If production data already contains invalid dates/empty bookings:

1. Create cleanup script to identify corrupt records
2. Manual review before deletion (may be legitimate edge cases)
3. Export audit log before cleanup

---

## Success Metrics

| Metric | Baseline | Target |
|--------|----------|--------|
| Invalid date acceptance rate | 100% | 0% |
| Empty booking creation rate | 100% | 0% |
| Permission error clarity score | 2/10 | 9/10 |
| Long audio processing success rate | 0% | >95% |
| Timezone update confirmation rate | 0% | 100% |

---

## Open Questions

1. **Test 4.2/4.4:** What is the exact exception thrown during long audio processing? (requires diagnostic logging)
2. **Test 3.3:** Should header restoration shift existing data down, or append below data? (UX decision)
3. **Test 2.3:** Should "позавчера" (day before yesterday) be valid for session logging vs booking? (different semantics)
4. **Test 4.2:** What is the actual Google Sheets cell character limit in practice? (need empirical test)

---

## Dependencies

### External Systems

- **OpenAI Whisper API:** Audio transcription timeout limits
- **Google Sheets API:** Cell size limits, rate limits, permission model
- **Python datetime library:** Date validation logic

### Internal Components

- `ai_service.parse_booking()`: Date generation logic
- `ai_service.parse_client_edit()`: Client name extraction
- `sheets_service._ensure_worksheets()`: Header management
- `bot.handle_client_update()`: Error handling flow
