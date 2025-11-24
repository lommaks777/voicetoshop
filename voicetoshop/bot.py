import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
import json
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import Config
from database import db_service
from services.sheets import sheets_service
from services.ai import ai_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize bot and dispatcher
bot = Bot(token=Config.BOT_TOKEN)
dp = Dispatcher()

# Initialize scheduler
scheduler = AsyncIOScheduler(timezone=pytz.timezone(Config.TIMEZONE))

# Onboarding state tracking (in-memory)
onboarding_states = {}  # {tg_id: "AWAITING_SHEET_URL" or "AWAITING_CITY"}
onboarding_sheet_ids = {}  # {tg_id: sheet_id} - temporary storage during onboarding


def get_main_menu() -> ReplyKeyboardMarkup:
    """
    Create persistent main menu keyboard with 2 buttons
    
    Returns:
        ReplyKeyboardMarkup with main menu buttons
    """
    keyboard = [
        [KeyboardButton(text="📅 План на сегодня"), KeyboardButton(text="❓ Помощь")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def get_undo_keyboard() -> InlineKeyboardMarkup:
    """
    Create inline keyboard with undo help button
    
    Returns:
        InlineKeyboardMarkup with help button
    """
    keyboard = [
        [InlineKeyboardButton(text="❌ Отменить действие", callback_data="undo_last")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


async def get_user_context(tg_id: int) -> dict:
    """
    Get user context (sheet_id) from database
    
    Returns:
        dict with 'tg_id' and 'sheet_id' if user registered, None otherwise
    """
    sheet_id = await db_service.get_user_sheet_id(tg_id)
    
    if sheet_id:
        # Update last active timestamp
        await db_service.update_last_active(tg_id)
        return {'tg_id': tg_id, 'sheet_id': sheet_id}
    
    return None


async def process_text_input(message: Message, text: str, processing_msg: Message, sheet_id: str, tg_id: int):
    """
    Shared business logic for processing text input (from voice transcription or direct text)
    
    Args:
        message: Original Telegram message object
        text: Text to process (transcription or direct text input)
        processing_msg: Status message to update with results
        sheet_id: User's Google Sheets ID
        tg_id: User's Telegram ID
    """
    try:
        # Privacy-compliant logging (no message content, only length)
        logger.info(f"User <TG_ID:{tg_id}> processing text input, length: {len(text)} chars")
        
        # Classify message type
        message_type = await ai_service.classify_message(text)
        logger.info(f"Message classified as: {message_type}")
        
        # Route to appropriate handler based on classification
        if message_type == "log_session":
            await handle_session(message, processing_msg, text, sheet_id, tg_id)
        elif message_type == "client_update":
            await handle_client_update(message, processing_msg, text, sheet_id, tg_id)
        elif message_type == "booking":
            await handle_booking(message, processing_msg, text, sheet_id, tg_id)
        elif message_type == "client_query":
            await handle_client_query(message, processing_msg, text, sheet_id, tg_id)
        elif message_type == "add_client":
            await handle_add_client(message, processing_msg, text, sheet_id, tg_id)
        elif message_type == "consultation":
            await processing_msg.edit_text(
                "Для просмотра информации о клиенте используйте команду:\n"
                "/client <имя клиента>"
            )
        else:
            # Default to session logging
            await handle_session(message, processing_msg, text, sheet_id, tg_id)
            
    except Exception as e:
        logger.error(f"Error processing text input: {e}", exc_info=True)
        await processing_msg.edit_text(f"❌ Ошибка обработки сообщения: {str(e)}")


@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Handle /start command - onboarding or welcome back"""
    tg_id = message.from_user.id
    user_exists = await db_service.user_exists(tg_id)
    
    if user_exists:
        await message.answer(
            "Добро пожаловать! 🙋‍♀️\n\n"
            "Отправьте голосовое или текстовое сообщение о сеансе массажа, и я занесу данные в вашу таблицу.\n\n"
            "Команды:\n"
            "/client <имя> - посмотреть информацию о клиенте",
            reply_markup=get_main_menu()
        )
    else:
        await start_onboarding(message)


async def start_onboarding(message: Message):
    """Start onboarding flow for new user"""
    tg_id = message.from_user.id
    onboarding_states[tg_id] = "AWAITING_SHEET_URL"
    
    service_email = Config.get_service_account_email()
    template_url = Config.TEMPLATE_SHEET_URL
    
    await message.answer(
        f"Привет! Я твой ИИ-помощник для управления клиентами массажа. 💆‍♀️\n\n"
        f"Чтобы начать:\n\n"
        f"📋 <b>Шаг 1:</b> Скопируй этот шаблон себе\n"
        f"{template_url}\n\n"
        f"🔑 <b>Шаг 2:</b> Нажми \"Настройки доступа\" (кнопка Share) и добавь моего робота как <b>Редактора (Editor)</b>:\n"
        f"<code>{service_email}</code>\n\n"
        f"📤 <b>Шаг 3:</b> Пришли мне ссылку на твою таблицу",
        parse_mode=ParseMode.HTML
    )


@dp.message(Command("client"))
async def cmd_client(message: Message):
    """Handle /client command - view client info"""
    tg_id = message.from_user.id
    logger.info(f"User <TG_ID:{tg_id}> called /client command")
    
    # Check if user is registered
    context = await get_user_context(tg_id)
    if not context:
        await message.answer(
            "❌ Вы не зарегистрированы.\n\n"
            "Отправьте /start для регистрации.",
            reply_markup=get_main_menu()
        )
        return
    
    sheet_id = context['sheet_id']
    
    # Extract client name from command
    text = message.text or ""
    parts = text.split(maxsplit=1)
    
    logger.info(f"Command text: '{text}', parts: {parts}")
    
    if len(parts) < 2:
        await message.answer(
            "❌ Укажите имя клиента\n\n"
            "<b>Использование:</b> /client Анна Иванова",
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_menu()
        )
        return
    
    client_name = parts[1].strip()
    logger.info(f"Looking up client: '{client_name}'")
    
    try:
        # Get client info from sheets
        client_info = await sheets_service.get_client(sheet_id, client_name)
        
        if not client_info:
            await message.answer(f"❌ Клиент '{client_name}' не найден", reply_markup=get_main_menu())
            return
        
        # Privacy-compliant logging
        logger.info(f"User <TG_ID:{tg_id}> looked up client")
        
        # Format response
        response = f"📋 <b>Информация о клиенте</b>\n\n"
        response += f"👤 <b>Имя:</b> {client_info['name']}\n"
        
        if client_info.get('phone_contact'):
            response += f"📱 <b>Контакт:</b> {client_info['phone_contact']}\n"
        
        if client_info.get('anamnesis'):
            response += f"\n🏥 <b>Анамнез:</b>\n{client_info['anamnesis']}\n"
        
        if client_info.get('notes'):
            response += f"\n📝 <b>Заметки:</b>\n{client_info['notes']}\n"
        
        if client_info.get('ltv'):
            response += f"\n💰 <b>LTV:</b> {client_info['ltv']}₽\n"
        
        if client_info.get('last_visit_date'):
            response += f"📅 <b>Последний визит:</b> {client_info['last_visit_date']}\n"
        
        if client_info.get('next_reminder'):
            response += f"🔔 <b>Следующая запись:</b> {client_info['next_reminder']}\n"
        
        # Show session history
        session_history = client_info.get('session_history', [])
        if session_history:
            response += f"\n📊 <b>История сеансов:</b>\n"
            for session in session_history[-5:]:  # Last 5 sessions
                response += f"  • {session['date']}: {session['service']} ({session['price']}₽)\n"
        
        # Show future bookings
        next_bookings = client_info.get('next_bookings', [])
        if next_bookings:
            response += f"\n🗓 <b>Будущие записи:</b>\n"
            for booking in next_bookings:
                date_formatted = booking['date']  # Already in YYYY-MM-DD format
                time_str = booking['time']
                service_str = booking.get('service', '')
                
                response += f"  • {date_formatted} в {time_str}"
                if service_str:
                    response += f" ({service_str})"
                response += "\n"
        else:
            response += f"\n🗓 <b>Будущие записи:</b> Нет\n"
        
        # Add ambiguity warning if applicable
        if client_info.get('_is_ambiguous', False):
            alternatives = client_info.get('_alternatives', [])
            if alternatives:
                response += f"\n⚠️ <b>Найдено несколько совпадений:</b> {', '.join(alternatives)}\n"
                response += f"Использована: {client_info['name']}\n"
                response += f"Если это не та клиентка, уточните запрос."
        
        await message.answer(response, parse_mode=ParseMode.HTML, reply_markup=get_main_menu())
        
    except Exception as e:
        logger.error(f"Error getting client info: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка получения данных: {str(e)}", reply_markup=get_main_menu())


@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    """Show bot statistics (admin feature)"""
    try:
        total_users = await db_service.get_total_users()
        
        await message.answer(
            f"📊 <b>Статистика бота</b>\n\n"
            f"👥 Всего пользователей: {total_users}",
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_menu()
        )
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        await message.answer("❌ Ошибка получения статистики", reply_markup=get_main_menu())


@dp.message(Command("set_timezone"))
async def cmd_set_timezone(message: Message):
    """Handle /set_timezone command - update user timezone"""
    tg_id = message.from_user.id
    logger.info(f"User <TG_ID:{tg_id}> called /set_timezone command")
    
    # Check if user is registered
    context = await get_user_context(tg_id)
    if not context:
        await message.answer(
            "❌ Вы не зарегистрированы.\n\n"
            "Отправьте /start для регистрации.",
            reply_markup=get_main_menu()
        )
        return
    
    # Extract city name from command
    text = message.text or ""
    parts = text.split(maxsplit=1)
    
    if len(parts) < 2:
        await message.answer(
            "❌ Укажите название города\n\n"
            "<b>Использование:</b> /set_timezone Москва\n\n"
            "<b>Примеры:</b>\n"
            "  /set_timezone Санкт-Петербург\n"
            "  /set_timezone Новосибирск\n"
            "  /set_timezone Владивосток",
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_menu()
        )
        return
    
    city = parts[1].strip()
    logger.info(f"Updating timezone for city: '{city}'")
    
    # Show processing message
    processing_msg = await message.answer("🌍 Определяю часовой пояс...")
    
    try:
        # Detect timezone using AI
        timezone = await ai_service.detect_timezone(city)
        
        if not timezone:
            await processing_msg.edit_text(
                f"❌ Не удалось определить часовой пояс для города '{city}'.\n\n"
                "Попробуйте указать более крупный город в вашем регионе.",
                reply_markup=get_main_menu()
            )
            return
        
        # Update timezone in database
        success = await db_service.update_user_timezone(tg_id, timezone)
        
        if success:
            await processing_msg.edit_text(
                f"✅ <b>Часовой пояс обновлён</b>\n\n"
                f"🌍 Город: {city}\n"
                f"⏰ Часовой пояс: {timezone}\n\n"
                f"Утренние уведомления будут приходить в 09:00 по вашему местному времени.",
                parse_mode=ParseMode.HTML,
                reply_markup=get_main_menu()
            )
            logger.info(f"User <TG_ID:{tg_id}> updated timezone to {timezone}")
        else:
            await processing_msg.edit_text(
                "❌ Ошибка обновления часового пояса. Попробуйте позже.",
                reply_markup=get_main_menu()
            )
        
    except Exception as e:
        logger.error(f"Error updating timezone: {e}")
        await processing_msg.edit_text(
            f"❌ Ошибка обновления: {str(e)}",
            reply_markup=get_main_menu()
        )


@dp.message(F.text == "📅 План на сегодня")
async def menu_daily_plan(message: Message):
    """Handle 'План на сегодня' button - show daily schedule"""
    tg_id = message.from_user.id
    logger.info(f"User <TG_ID:{tg_id}> requested daily plan")
    
    # Check if user is registered
    context = await get_user_context(tg_id)
    if not context:
        await message.answer(
            "❌ Вы не зарегистрированы.\n\n"
            "Отправьте /start для регистрации.",
            reply_markup=get_main_menu()
        )
        return
    
    sheet_id = context['sheet_id']
    
    try:
        # Get user's timezone and today's date
        user_timezone_str = await db_service.get_user_timezone(tg_id)
        try:
            user_tz = pytz.timezone(user_timezone_str)
            user_local_time = datetime.now(user_tz)
            today_date = user_local_time.strftime('%Y-%m-%d')
            today_display = user_local_time.strftime('%d.%m')
        except Exception as tz_error:
            logger.warning(f"Failed to parse timezone '{user_timezone_str}': {tz_error}, using default")
            from config import Config
            tz = pytz.timezone(Config.TIMEZONE)
            user_local_time = datetime.now(tz)
            today_date = user_local_time.strftime('%Y-%m-%d')
            today_display = user_local_time.strftime('%d.%m')
        
        # Get daily schedule
        appointments = await sheets_service.get_daily_schedule(sheet_id, today_date)
        
        if not appointments:
            await message.answer(
                f"📅 <b>План на сегодня ({today_display}):</b>\n\n"
                "У вас нет запланированных сеансов.\n\n"
                "Хорошего дня! ☀️",
                parse_mode=ParseMode.HTML,
                reply_markup=get_main_menu()
            )
            return
        
        # Format message
        response = f"📅 <b>План на сегодня ({today_display}):</b>\n\n"
        
        for appointment in appointments:
            time = appointment.get('time', '')
            client_name = appointment.get('client_name', 'Неизвестно')
            service_type = appointment.get('service_type', '')
            duration = appointment.get('duration', '')
            notes = appointment.get('notes', '')
            
            response += f"<b>{time}</b> — {client_name}"
            if service_type:
                response += f" ({service_type})"
            response += "\n"
            
            if duration:
                try:
                    dur_int = int(duration)
                    response += f"{dur_int} минут\n"
                except:
                    pass
            
            if notes:
                response += f"❗ <b>Заметка:</b> {notes}\n"
            
            response += "\n"
        
        response += "Хорошего рабочего дня! ☀️"
        
        await message.answer(
            response,
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_menu()
        )
        
    except Exception as e:
        logger.error(f"Error getting daily plan: {e}", exc_info=True)
        await message.answer(
            "❌ Ошибка получения плана на сегодня.",
            reply_markup=get_main_menu()
        )


@dp.message(F.text == "❓ Помощь")
async def menu_help(message: Message):
    """Handle 'Помощь' button - send usage instructions and sheet link"""
    tg_id = message.from_user.id
    logger.info(f"User <TG_ID:{tg_id}> requested help")
    
    # Check if user is registered to show sheet link
    context = await get_user_context(tg_id)
    
    help_text = (
        "❓ <b>Как использовать бота</b>\n\n"
        "<b>📝 Запись сеанса:</b>\n"
        "Отправьте голосовое или текстовое сообщение с информацией:\n"
        "• Имя клиента\n"
        "• Услуга (например, ШВЗ, массаж спины)\n"
        "• Цена\n"
        "• Длительность (опционально)\n"
        "• Заметки (опционально)\n\n"
        "<b>📅 Создание записи:</b>\n"
        "Скажите: \"Запись на Анну завтра в 14:00\"\n\n"
        "<b>📝 Добавление заметки к клиенту:</b>\n"
        "Скажите: \"Анна боится массажа шеи\"\n\n"
        "<b>🔍 Информация о клиенте:</b>\n"
        "<code>/client Анна Иванова</code>\n\n"
        "<b>🌍 Настройка часового пояса:</b>\n"
        "<code>/set_timezone Москва</code>\n\n"
    )
    
    # Add sheet link if user is registered
    if context:
        sheet_id = context['sheet_id']
        sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        help_text += (
            f"<b>📊 Моя База Клиентов:</b>\n"
            f"🔗 <a href='{sheet_url}'>Открыть таблицу</a>\n\n"
        )
    
    help_text += "💡 <b>Совет:</b> Говорите естественно, я понимаю контекст!"
    
    await message.answer(
        help_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_menu(),
        disable_web_page_preview=True
    )


@dp.callback_query(F.data == "undo_last")
async def handle_undo_last(callback: CallbackQuery):
    """Handle undo last action click"""
    tg_id = callback.from_user.id
    logger.info(f"User <TG_ID:{tg_id}> requested undo")
    
    # Get user context
    context = await get_user_context(tg_id)
    if not context:
        await callback.answer("Пожалуйста, зарегистрируйтесь")
        return
    
    sheet_id = context['sheet_id']
    last_action_json = await db_service.get_last_action(tg_id)
    if not last_action_json:
        await callback.answer("Нет действия для отмены", show_alert=True)
        return
    
    # Parse and perform undo
    try:
        action = json.loads(last_action_json)
    except Exception:
        await callback.answer("Данные для отмены повреждены", show_alert=True)
        return
    
    ok = await sheets_service.undo_last_action(sheet_id, action)
    if ok:
        await db_service.clear_last_action(tg_id)
        await callback.answer("✅ Последнее действие отменено")
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    else:
        await callback.answer("❌ Не удалось отменить", show_alert=True)


@dp.message(F.text)
async def handle_text(message: Message):
    """Handle text messages - onboarding URL, city input, or CRM operations"""
    tg_id = message.from_user.id
    
    # Check if user is in onboarding - sheet URL stage
    if onboarding_states.get(tg_id) == "AWAITING_SHEET_URL":
        await process_sheet_url(message)
        return
    
    # Check if user is in onboarding - city input stage
    if onboarding_states.get(tg_id) == "AWAITING_CITY":
        await process_city_input(message)
        return
    
    # Check if message is a command (starts with /)
    if message.text and message.text.startswith("/"):
        # Let command handlers process it
        return
    
    # Check if user is registered
    context = await get_user_context(tg_id)
    if not context:
        await message.answer(
            "❌ Вы не зарегистрированы.\n\n"
            "Отправьте /start для регистрации.",
            reply_markup=get_main_menu()
        )
        return
    
    sheet_id = context['sheet_id']
    
    # Send processing message
    processing_msg = await message.answer("⌛ Думаю...", reply_markup=get_main_menu())
    
    try:
        # Privacy-compliant logging (no message content, only length)
        logger.info(f"User <TG_ID:{tg_id}> sent text message, length: {len(message.text)} chars")
        
        # Process text input using shared logic
        await process_text_input(message, message.text, processing_msg, sheet_id, tg_id)
        
    except Exception as e:
        logger.error(f"Error processing text message: {e}", exc_info=True)
        await processing_msg.edit_text(f"❌ Ошибка обработки: {str(e)}")


async def process_sheet_url(message: Message):
    """Process sheet URL during onboarding"""
    tg_id = message.from_user.id
    url = message.text.strip()
    
    # Show processing message
    processing_msg = await message.answer("🔄 Проверяю доступ к таблице...")
    
    try:
        # Validate and connect to sheet
        success, msg, sheet_id = await sheets_service.validate_and_connect(url)
        
        if success:
            # Store sheet_id temporarily and transition to city collection
            onboarding_sheet_ids[tg_id] = sheet_id
            onboarding_states[tg_id] = "AWAITING_CITY"
            
            await processing_msg.edit_text(
                f"✅ Таблица проверена!\n\n"
                f"В каком городе вы работаете? (Нужно для настройки времени уведомлений)\n\n"
                f"Примеры: Москва, Санкт-Петербург, Новосибирск",
                parse_mode=ParseMode.HTML
            )
            
            logger.info(f"Sheet validated for TG_ID {tg_id}, awaiting city input")
        else:
            await processing_msg.edit_text(msg, parse_mode=ParseMode.HTML)
            
    except Exception as e:
        logger.error(f"Error processing sheet URL: {e}")
        await processing_msg.edit_text(
            "❌ Произошла ошибка при проверке таблицы.\n\n"
            "Попробуйте еще раз или обратитесь в поддержку."
        )


async def process_city_input(message: Message):
    """Process city name during onboarding and complete registration"""
    tg_id = message.from_user.id
    city = message.text.strip()
    
    # Retrieve temporarily stored sheet_id
    sheet_id = onboarding_sheet_ids.get(tg_id)
    if not sheet_id:
        await message.answer(
            "❌ Произошла ошибка. Пожалуйста, начните заново с /start"
        )
        return
    
    # Show processing message
    processing_msg = await message.answer("🌍 Определяю часовой пояс...")
    
    try:
        # Detect timezone using AI
        timezone = await ai_service.detect_timezone(city)
        
        if not timezone:
            # Fallback to default timezone
            timezone = 'Europe/Moscow'
            logger.warning(f"Failed to detect timezone for city '{city}', using default: {timezone}")
        
        # Register user in database
        result = await db_service.add_user(tg_id, sheet_id)
        
        if result:
            # Update timezone
            await db_service.update_user_timezone(tg_id, timezone)
            
            # Clear onboarding state
            onboarding_states.pop(tg_id, None)
            onboarding_sheet_ids.pop(tg_id, None)
            
            await processing_msg.edit_text(
                f"✅ <b>Готово!</b>\n\n"
                f"Ваша таблица подключена.\n"
                f"Часовой пояс: {timezone}\n\n"
                f"Теперь можете отправлять голосовые или текстовые сообщения о сеансах массажа.",
                parse_mode=ParseMode.HTML
            )
            
            # Send welcome message with menu
            await message.answer(
                "Используйте меню ниже для быстрого доступа к функциям:",
                reply_markup=get_main_menu()
            )
            
            logger.info(f"User onboarded: TG_ID {tg_id}, Sheet {sheet_id}, Timezone {timezone}")
        else:
            await processing_msg.edit_text(
                "❌ Ошибка сохранения данных. Попробуйте позже."
            )
            
    except Exception as e:
        logger.error(f"Error processing city input: {e}")
        await processing_msg.edit_text(
            "❌ Произошла ошибка. Попробуйте позже или обратитесь в поддержку."
        )


@dp.message(F.voice)
async def handle_voice(message: Message):
    """Handle voice messages - main session logging flow"""
    tg_id = message.from_user.id
    
    # Check if user is registered
    context = await get_user_context(tg_id)
    if not context:
        await message.answer(
            "❌ Вы не зарегистрированы.\n\n"
            "Отправьте /start для регистрации.",
            reply_markup=get_main_menu()
        )
        return
    
    sheet_id = context['sheet_id']
    
    # Send processing message
    processing_msg = await message.answer("🎧 Обрабатываю голосовое сообщение...")
    
    try:
        # Download voice file
        voice_file = await bot.get_file(message.voice.file_id)
        voice_path = f"/tmp/voice_{message.message_id}.ogg"
        await bot.download_file(voice_file.file_path, voice_path)
        
        # Transcribe audio
        transcription = await ai_service.transcribe_audio(voice_path)
        
        # Clean up audio file
        if os.path.exists(voice_path):
            os.remove(voice_path)
        
        if not transcription:
            await processing_msg.edit_text("🤷‍♂️ Не удалось распознать аудио. Попробуйте еще раз.")
            return
        
        # Privacy-compliant logging (no transcription content, only length)
        logger.info(f"User <TG_ID:{tg_id}> sent voice message, transcription length: {len(transcription)} chars")
        
        # Process transcription using shared logic
        await process_text_input(message, transcription, processing_msg, sheet_id, tg_id)
            
    except Exception as e:
        logger.error(f"Error processing voice message: {e}")
        await processing_msg.edit_text(f"❌ Ошибка обработки сообщения: {str(e)}")


async def handle_session(message: Message, processing_msg: Message, transcription: str, sheet_id: str, tg_id: int):
    """Handle session logging flow"""
    try:
        # Get user's timezone and calculate local date
        user_timezone_str = await db_service.get_user_timezone(tg_id)
        try:
            user_tz = pytz.timezone(user_timezone_str)
            user_now = datetime.now(user_tz)
            user_current_date = user_now.strftime('%Y-%m-%d')
        except Exception as tz_error:
            logger.warning(f"Failed to parse timezone '{user_timezone_str}': {tz_error}, using server time")
            tz = pytz.timezone(Config.TIMEZONE)
            user_current_date = datetime.now(tz).strftime('%Y-%m-%d')
        
        # Get service names for context (optional)
        service_names = await sheets_service.get_services(sheet_id)
        
        # Parse session data with user's local date
        session_data = await ai_service.parse_session(transcription, user_current_date, service_names, user_current_date)
        
        if not session_data:
            await processing_msg.edit_text(
                "❌ Не удалось извлечь информацию о сеансе.\n\n"
                "Укажите:\n"
                "• Имя клиента\n"
                "• Услугу (например, ШВЗ, массаж спины)\n"
                "• Цену",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Log session to Google Sheets
        try:
            action = await sheets_service.log_session(sheet_id, {
                'client_name': session_data.client_name,
                'service_name': session_data.service_name,
                'price': session_data.price,
                'duration': session_data.duration,
                'medical_notes': session_data.medical_notes,
                'session_notes': session_data.session_notes,
                'preference_notes': session_data.preference_notes,
                'next_appointment_date': session_data.next_appointment_date
            })
            await db_service.set_last_action(tg_id, json.dumps(action))
            
            # Privacy-compliant logging
            logger.info(f"User <TG_ID:{tg_id}> logged a session")
            
            # Format response
            response = "✅ <b>Сеанс записан</b>\n\n"
            response += f"👤 <b>Клиент:</b> {session_data.client_name}\n"
            response += f"💆‍♀️ <b>Услуга:</b> {session_data.service_name}\n"
            response += f"💰 <b>Цена:</b> {session_data.price}₽\n"
            
            if session_data.duration:
                response += f"⏱️ <b>Длительность:</b> {session_data.duration} мин\n"
            
            if session_data.next_appointment_date:
                response += f"\n🗓️ <b>Следующая запись:</b> {session_data.next_appointment_date}\n"
            
            await processing_msg.edit_text(
                response, 
                parse_mode=ParseMode.HTML,
                reply_markup=get_undo_keyboard()
            )
            
        except PermissionError:
            service_email = Config.get_service_account_email()
            await processing_msg.edit_text(
                f"🚫 <b>Я потерял доступ к вашей таблице</b>\n\n"
                f"Проверьте, что:\n"
                f"1. Таблица не удалена\n"
                f"2. Мой робот имеет доступ Редактора:\n"
                f"   <code>{service_email}</code>\n\n"
                f"Если вы удалили доступ, откройте таблицу и снова добавьте меня.",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Error logging session: {e}")
            await processing_msg.edit_text(
                f"❌ Ошибка записи в таблицу:\n{str(e)}"
            )
            
    except Exception as e:
        logger.error(f"Error handling session: {e}")
        await processing_msg.edit_text(f"❌ Ошибка обработки сеанса: {str(e)}")


async def handle_client_update(message: Message, processing_msg: Message, transcription: str, sheet_id: str, tg_id: int):
    """Handle client information update flow"""
    try:
        # Parse client edit data
        client_edit_data = await ai_service.parse_client_edit(transcription)
        
        if not client_edit_data:
            await processing_msg.edit_text(
                "❌ Не удалось извлечь информацию о клиенте.\n\n"
                "Укажите имя клиента и заметку.",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Update client info in sheets
            result = await sheets_service.update_client_info(sheet_id, {
                'client_name': client_edit_data.client_name,
                'target_field': client_edit_data.target_field,
                'content_to_append': client_edit_data.content_to_append
            })
            
            if result.get('success'):
                action = result.get('action')
                if action:
                    await db_service.set_last_action(tg_id, json.dumps(action))
            # Map field names to Russian
            field_names = {
                'anamnesis': 'Анамнез',
                'notes': 'Заметки',
                'contacts': 'Контакты'
            }
            field_name = field_names.get(client_edit_data.target_field, 'Заметки')
            
            response = f"📝 <b>Заметка добавлена в карту клиента</b>\n\n"
            response += f"👤 <b>Клиент:</b> {client_edit_data.client_name}\n"
            response += f"📖 <b>Раздел:</b> {field_name}\n\n"
            response += f"✅ Добавлено: \"{client_edit_data.content_to_append}\""
            
            await processing_msg.edit_text(
                response, 
                parse_mode=ParseMode.HTML,
                reply_markup=get_undo_keyboard()
            )
            logger.info(f"User <TG_ID:{tg_id}> updated client info")
        else:
            await processing_msg.edit_text(
                "❌ Ошибка обновления информации."
            )
        
    except Exception as e:
        logger.error(f"Error handling client update: {e}")
        await processing_msg.edit_text(f"❌ Ошибка обновления информации: {str(e)}")


async def handle_booking(message: Message, processing_msg: Message, transcription: str, sheet_id: str, tg_id: int):
    """Handle future booking/appointment creation flow"""
    try:
        # Get user's timezone and calculate local date
        user_timezone_str = await db_service.get_user_timezone(tg_id)
        try:
            user_tz = pytz.timezone(user_timezone_str)
            user_now = datetime.now(user_tz)
            user_current_date = user_now.strftime('%Y-%m-%d')
        except Exception as tz_error:
            logger.warning(f"Failed to parse timezone '{user_timezone_str}': {tz_error}, using server time")
            tz = pytz.timezone(Config.TIMEZONE)
            user_current_date = datetime.now(tz).strftime('%Y-%m-%d')
        
        # Parse booking data with user's local date
        booking_data = await ai_service.parse_booking(transcription, user_current_date, user_current_date)
        
        if not booking_data:
            await processing_msg.edit_text(
                "❌ Не удалось извлечь информацию о записи.\n\n"
                "Укажите:\n"
                "• Имя клиента\n"
                "• Дату (например, 'завтра', 'во вторник')\n"
                "• Время (например, '14:00', '3 PM')",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Add booking to sheets
        try:
            action = await sheets_service.add_booking(sheet_id, {
                'client_name': booking_data.client_name,
                'date': booking_data.date,
                'time': booking_data.time,
                'service_name': booking_data.service_name,
                'duration': booking_data.duration,
                'notes': booking_data.notes,
                'phone_contact': booking_data.phone_contact
            })
            await db_service.set_last_action(tg_id, json.dumps(action))
            
            # Privacy-compliant logging
            logger.info(f"User <TG_ID:{tg_id}> created a booking")
            
            # Format date for display (DD.MM and weekday)
            try:
                date_obj = datetime.strptime(booking_data.date, '%Y-%m-%d')
                date_display = date_obj.strftime('%d.%m')
                weekday_names = {
                    'Monday': 'Понедельник',
                    'Tuesday': 'Вторник',
                    'Wednesday': 'Среда',
                    'Thursday': 'Четверг',
                    'Friday': 'Пятница',
                    'Saturday': 'Суббота',
                    'Sunday': 'Воскресенье'
                }
                weekday_en = date_obj.strftime('%A')
                weekday = weekday_names.get(weekday_en, weekday_en)
            except:
                date_display = booking_data.date
                weekday = ''
            
            # Format response
            response = "✅ <b>Запись создана</b>\n\n"
            response += f"📅 {date_display}"
            if weekday:
                response += f" ({weekday})"
            response += f" в {booking_data.time}\n"
            response += f"👤 <b>Клиент:</b> {booking_data.client_name}\n"
            
            if booking_data.phone_contact:
                response += f"📱 <b>Телефон:</b> <code>{booking_data.phone_contact}</code>\n"
            
            if booking_data.service_name:
                response += f"💆‍♀️ <b>Услуга:</b> {booking_data.service_name}\n"
            
            if booking_data.duration:
                response += f"⏱️ <b>Длительность:</b> {booking_data.duration} мин\n"
            
            if booking_data.notes:
                response += f"\n📝 <b>Заметка:</b> {booking_data.notes}"
            
            await processing_msg.edit_text(
                response, 
                parse_mode=ParseMode.HTML,
                reply_markup=get_undo_keyboard()
            )
            
        except PermissionError:
            service_email = Config.get_service_account_email()
            await processing_msg.edit_text(
                f"🚫 <b>Я потерял доступ к вашей таблице</b>\n\n"
                f"Проверьте, что:\n"
                f"1. Таблица не удалена\n"
                f"2. Мой робот имеет доступ Редактора:\n"
                f"   <code>{service_email}</code>\n\n"
                f"Если вы удалили доступ, откройте таблицу и снова добавьте меня.",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Error adding booking: {e}")
            await processing_msg.edit_text(
                f"❌ Ошибка создания записи:\n{str(e)}"
            )
            
    except Exception as e:
        logger.error(f"Error handling booking: {e}")
        await processing_msg.edit_text(f"❌ Ошибка обработки записи: {str(e)}")


async def handle_client_query(message: Message, processing_msg: Message, transcription: str, sheet_id: str, tg_id: int):
    """Handle client information query flow"""
    try:
        # Parse client query data
        client_query_data = await ai_service.parse_client_query(transcription)
        
        if not client_query_data:
            await processing_msg.edit_text(
                "❌ Не удалось понять запрос.\n\n"
                "Укажите имя клиента.",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Get client info from sheets
        client_info = await sheets_service.get_client(sheet_id, client_query_data.client_name)
        
        if not client_info:
            await processing_msg.edit_text(f"❌ Клиент '{client_query_data.client_name}' не найден")
            return
        
        # Privacy-compliant logging
        logger.info(f"User <TG_ID:{tg_id}> queried client info")
        
        # Format response - phone contact first for easy copying
        response = f"👤 <b>{client_info['name']}</b>\n"
        
        # Always show phone field
        phone = client_info.get('phone_contact', '').strip()
        if phone:
            response += f"📱 <code>{phone}</code>\n\n"
        else:
            response += f"📱 Телефон не указан\n\n"
        
        if client_info.get('anamnesis'):
            response += f"🏥 <b>Анамнез:</b>\n{client_info['anamnesis']}\n\n"
        
        if client_info.get('notes'):
            response += f"📝 <b>Заметки:</b>\n{client_info['notes']}\n\n"
        
        if client_info.get('ltv'):
            try:
                ltv_value = float(client_info['ltv'])
                ltv_formatted = f"{ltv_value:,.0f}".replace(',', ' ')
                response += f"💰 <b>LTV:</b> {ltv_formatted}₽\n"
            except:
                response += f"💰 <b>LTV:</b> {client_info['ltv']}₽\n"
        
        if client_info.get('last_visit_date'):
            response += f"📅 <b>Последний визит:</b> {client_info['last_visit_date']}\n"
        
        if client_info.get('next_reminder'):
            response += f"🔔 <b>Следующая запись:</b> {client_info['next_reminder']}\n"
        
        # Show session history
        session_history = client_info.get('session_history', [])
        if session_history:
            response += f"\n📋 <b>Последние сеансы:</b>\n"
            for session in session_history[-5:]:  # Last 5 sessions
                response += f"  • {session['date']}: {session['service']} ({session['price']}₽)\n"
        
        # Show future bookings
        next_bookings = client_info.get('next_bookings', [])
        if next_bookings:
            response += f"\n🗓 <b>Будущие записи:</b>\n"
            for booking in next_bookings:
                date_formatted = booking['date']  # Already in YYYY-MM-DD format
                time_str = booking['time']
                service_str = booking.get('service', '')
                
                response += f"  • {date_formatted} в {time_str}"
                if service_str:
                    response += f" ({service_str})"
                response += "\n"
        else:
            response += f"\n🗓 <b>Будущие записи:</b> Нет\n"
        
        # Add ambiguity warning if applicable
        if client_info.get('_is_ambiguous', False):
            alternatives = client_info.get('_alternatives', [])
            if alternatives:
                response += f"\n⚠️ <b>Найдено несколько совпадений:</b> {', '.join(alternatives)}\n"
                response += f"Использована: {client_info['name']}\n"
                response += f"Если это не та клиентка, уточните запрос."
        
        await processing_msg.edit_text(response, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Error handling client query: {e}")
        await processing_msg.edit_text(f"❌ Ошибка получения данных: {str(e)}")


async def handle_add_client(message: Message, processing_msg: Message, transcription: str, sheet_id: str, tg_id: int):
    """Handle new client registration flow"""
    try:
        # Parse new client data
        new_client_data = await ai_service.parse_new_client(transcription)
        
        if not new_client_data:
            await processing_msg.edit_text(
                "❌ Не удалось извлечь информацию о клиенте.\n\n"
                "Укажите хотя бы имя клиента.",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Add client to sheets
        result = await sheets_service.add_new_client(sheet_id, {
            'client_name': new_client_data.client_name,
            'phone_contact': new_client_data.phone_contact,
            'notes': new_client_data.notes,
            'anamnesis': new_client_data.anamnesis
        })
        
        if result.get('success'):
            action = result.get('action')
            if action:
                await db_service.set_last_action(tg_id, json.dumps(action))
            response = f"✅ <b>Клиент добавлен в базу</b>\n\n"
            response += f"👤 <b>Имя:</b> {new_client_data.client_name}\n"
            
            if new_client_data.phone_contact:
                response += f"📱 <b>Контакт:</b> {new_client_data.phone_contact}\n"
            
            if new_client_data.notes:
                response += f"📝 <b>Предпочтения:</b> {new_client_data.notes}\n"
            
            if new_client_data.anamnesis:
                response += f"🏥 <b>Анамнез:</b> {new_client_data.anamnesis}\n"
            
            await processing_msg.edit_text(
                response, 
                parse_mode=ParseMode.HTML,
                reply_markup=get_undo_keyboard()
            )
            logger.info(f"User <TG_ID:{tg_id}> added new client to database")
        else:
            # If client already exists, update contact info if provided
            if new_client_data.phone_contact:
                try:
                    result_update = await sheets_service.update_client_info(sheet_id, {
                        'client_name': new_client_data.client_name,
                        'target_field': 'contacts',
                        'content_to_append': new_client_data.phone_contact
                    })
                    if result_update.get('success'):
                        action = result_update.get('action')
                        if action:
                            await db_service.set_last_action(tg_id, json.dumps(action))
                        response = (
                            "📝 <b>Контакт обновлен</b>\n\n"
                            f"👤 <b>Клиент:</b> {new_client_data.client_name}\n"
                            f"📱 <b>Телефон:</b> <code>{new_client_data.phone_contact}</code>"
                        )
                        await processing_msg.edit_text(
                            response,
                            parse_mode=ParseMode.HTML,
                            reply_markup=get_undo_keyboard()
                        )
                    else:
                        await processing_msg.edit_text(
                            "❌ Ошибка обновления контакта."
                        )
                except Exception as e:
                    logger.error(f"Error updating existing client contact: {e}")
                    await processing_msg.edit_text(
                        "❌ Ошибка обновления контакта."
                    )
            else:
                await processing_msg.edit_text(
                    f"⚠️ Клиент <b>{new_client_data.client_name}</b> уже существует в базе.\n\n"
                    f"Добавьте информацию в свободной форме, чтобы я понял, что нужно обновить (например, 'телефон', 'заметки', 'анамнез').",
                    parse_mode=ParseMode.HTML
                )
        
    except Exception as e:
        logger.error(f"Error handling add client: {e}")
        await processing_msg.edit_text(f"❌ Ошибка добавления клиента: {str(e)}")


async def send_morning_briefs():
    """
    Send daily schedule summary to users at their local 09:00 AM
    Runs every hour and checks each user's local time
    """
    logger.info("Starting hourly morning brief check...")
    
    try:
        # Get all active users with their timezones
        users = await db_service.get_all_active_users()
        logger.info(f"Checking {len(users)} active users for morning briefs")
        
        # Get current UTC time
        utc_now = datetime.utcnow()
        
        sent_count = 0
        error_count = 0
        skipped_count = 0
        
        for user in users:
            tg_id = user['tg_id']
            sheet_id = user['sheet_id']
            timezone_str = user['timezone']
            
            try:
                # Calculate user's local time
                try:
                    user_tz = pytz.timezone(timezone_str)
                    user_local_time = pytz.utc.localize(utc_now).astimezone(user_tz)
                except Exception as tz_error:
                    logger.warning(f"Invalid timezone '{timezone_str}' for user {tg_id}: {tz_error}, using default")
                    user_tz = pytz.timezone('Europe/Moscow')
                    user_local_time = pytz.utc.localize(utc_now).astimezone(user_tz)
                
                # Check if it's 9 AM in user's local time
                if user_local_time.hour != 9:
                    skipped_count += 1
                    continue
                
                # Get today's date in user's timezone
                today_date = user_local_time.strftime('%Y-%m-%d')
                today_display = user_local_time.strftime('%d.%m')
                
                # Get daily schedule
                appointments = await sheets_service.get_daily_schedule(sheet_id, today_date)
                
                # Only send if there are appointments
                if not appointments:
                    logger.info(f"No appointments for user {tg_id}, skipping")
                    skipped_count += 1
                    continue
                
                # Format message
                message = f"🌅 <b>Доброе утро! План на сегодня ({today_display}):</b>\n\n"
                
                for appointment in appointments:
                    time = appointment.get('time', '')
                    client_name = appointment.get('client_name', 'Неизвестно')
                    service_type = appointment.get('service_type', '')
                    duration = appointment.get('duration', '')
                    notes = appointment.get('notes', '')
                    
                    message += f"<b>{time}</b> — {client_name}"
                    if service_type:
                        message += f" ({service_type})"
                    message += "\n"
                    
                    if duration:
                        try:
                            dur_int = int(duration)
                            message += f"{dur_int} минут\n"
                        except:
                            pass
                    
                    if notes:
                        message += f"❗ <b>Заметка:</b> {notes}\n"
                    
                    message += "\n"
                
                message += "Хорошего рабочего дня! ☀️"
                
                # Send message
                await bot.send_message(
                    chat_id=tg_id,
                    text=message,
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_main_menu()
                )
                
                sent_count += 1
                logger.info(f"Sent morning brief to user {tg_id} (timezone: {timezone_str}) with {len(appointments)} appointments")
                
                # Small delay to avoid rate limiting
                await asyncio.sleep(0.5)
                
            except Exception as e:
                error_count += 1
                logger.error(f"Failed to send morning brief to user {tg_id}: {e}")
                continue
        
        logger.info(f"Morning brief check completed: {sent_count} sent, {skipped_count} skipped (wrong hour or no appointments), {error_count} errors")
        
    except Exception as e:
        logger.error(f"Error in send_morning_briefs: {e}")


async def on_startup():
    """Initialize services on startup"""
    logger.info("Starting Massage CRM Bot...")
    
    # Initialize database
    await db_service.initialize(Config.DATABASE_PATH)
    logger.info("Database service initialized")
    
    # Initialize Google Sheets
    await sheets_service.initialize()
    logger.info("Google Sheets service initialized")
    
    # Start scheduler
    scheduler.add_job(
        send_morning_briefs,
        trigger='cron',
        minute=0,  # Run every hour at :00 minute
        id='morning_briefs',
        replace_existing=True,
        misfire_grace_time=3600  # 1 hour grace period
    )
    scheduler.start()
    logger.info("Scheduler started - morning briefs will check hourly for users at local 09:00")
    
    logger.info("Bot is ready!")


async def on_shutdown():
    """Cleanup on shutdown"""
    logger.info("Shutting down bot...")
    
    # Shutdown scheduler
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down")
    
    await bot.session.close()


async def main():
    """Main entry point"""
    try:
        await on_startup()
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        await on_shutdown()


if __name__ == "__main__":
    asyncio.run(main())
