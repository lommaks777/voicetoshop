import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.enums import ParseMode
import pytz

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

# Onboarding state tracking (in-memory)
onboarding_states = {}  # {tg_id: "AWAITING_SHEET_URL"}


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


@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Handle /start command - onboarding or welcome back"""
    tg_id = message.from_user.id
    user_exists = await db_service.user_exists(tg_id)
    
    if user_exists:
        await message.answer(
            "Добро пожаловать! 🙋‍♀️\n\n"
            "Отправьте голосовое сообщение о сеансе массажа, и я занесу данные в вашу таблицу.\n\n"
            "Команды:\n"
            "/client <имя> - посмотреть информацию о клиенте"
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
            "Отправьте /start для регистрации."
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
            parse_mode=ParseMode.HTML
        )
        return
    
    client_name = parts[1].strip()
    logger.info(f"Looking up client: '{client_name}'")
    
    try:
        # Get client info from sheets
        client_info = await sheets_service.get_client(sheet_id, client_name)
        
        if not client_info:
            await message.answer(f"❌ Клиент '{client_name}' не найден")
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
        
        await message.answer(response, parse_mode=ParseMode.HTML)
        
    except Exception as e:
        logger.error(f"Error getting client info: {e}", exc_info=True)
        await message.answer(f"❌ Ошибка получения данных: {str(e)}")


@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    """Show bot statistics (admin feature)"""
    try:
        total_users = await db_service.get_total_users()
        
        await message.answer(
            f"📊 <b>Статистика бота</b>\n\n"
            f"👥 Всего пользователей: {total_users}",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        await message.answer("❌ Ошибка получения статистики")


@dp.message(F.text)
async def handle_text(message: Message):
    """Handle text messages - onboarding URL or client lookup"""
    tg_id = message.from_user.id
    
    # Check if user is in onboarding
    if onboarding_states.get(tg_id) == "AWAITING_SHEET_URL":
        await process_sheet_url(message)
        return
    
    # Check if user is registered
    context = await get_user_context(tg_id)
    if not context:
        await message.answer(
            "❌ Вы не зарегистрированы.\n\n"
            "Отправьте /start для регистрации."
        )
        return
    
    # Handle regular text (future: could be natural language queries)
    await message.answer(
        "Для записи сеанса отправьте голосовое сообщение.\n\n"
        "Для просмотра клиента используйте: /client <имя>"
    )


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
            # Register user in database
            result = await db_service.add_user(tg_id, sheet_id)
            
            if result:
                # Clear onboarding state
                onboarding_states.pop(tg_id, None)
                
                await processing_msg.edit_text(
                    f"✅ <b>Готово!</b>\n\n"
                    f"Ваша таблица подключена.\n"
                    f"Теперь можете отправлять голосовые сообщения о сеансах массажа.",
                    parse_mode=ParseMode.HTML
                )
                
                logger.info(f"User onboarded: TG_ID {tg_id}, Sheet {sheet_id}")
            else:
                await processing_msg.edit_text(
                    "❌ Ошибка сохранения данных. Попробуйте позже."
                )
        else:
            await processing_msg.edit_text(msg, parse_mode=ParseMode.HTML)
            
    except Exception as e:
        logger.error(f"Error processing sheet URL: {e}")
        await processing_msg.edit_text(
            "❌ Произошла ошибка при проверке таблицы.\n\n"
            "Попробуйте еще раз или обратитесь в поддержку."
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
            "Отправьте /start для регистрации."
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
        
        # Classify message type
        message_type = await ai_service.classify_message(transcription)
        
        if message_type == "log_session":
            await handle_session(message, processing_msg, transcription, sheet_id, tg_id)
        elif message_type == "client_update":
            await handle_client_update(message, processing_msg, transcription, sheet_id, tg_id)
        elif message_type == "consultation":
            await processing_msg.edit_text(
                "Для просмотра информации о клиенте используйте команду:\n"
                "/client <имя клиента>"
            )
        else:
            # Default to session logging
            await handle_session(message, processing_msg, transcription, sheet_id, tg_id)
            
    except Exception as e:
        logger.error(f"Error processing voice message: {e}")
        await processing_msg.edit_text(f"❌ Ошибка обработки сообщения: {str(e)}")


async def handle_session(message: Message, processing_msg: Message, transcription: str, sheet_id: str, tg_id: int):
    """Handle session logging flow"""
    try:
        # Get current date
        tz = pytz.timezone(Config.TIMEZONE)
        current_date = datetime.now(tz).strftime('%Y-%m-%d')
        
        # Get service names for context (optional)
        service_names = await sheets_service.get_services(sheet_id)
        
        # Parse session data
        session_data = await ai_service.parse_session(transcription, current_date, service_names)
        
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
            await sheets_service.log_session(sheet_id, {
                'client_name': session_data.client_name,
                'service_name': session_data.service_name,
                'price': session_data.price,
                'duration': session_data.duration,
                'medical_notes': session_data.medical_notes,
                'session_notes': session_data.session_notes,
                'preference_notes': session_data.preference_notes,
                'next_appointment_date': session_data.next_appointment_date
            })
            
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
            
            await processing_msg.edit_text(response, parse_mode=ParseMode.HTML)
            
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
        
        # For now, we don't have a separate method to update only notes
        # This functionality can be added in Phase 2
        await processing_msg.edit_text(
            "ℹ️ Обновление заметок о клиенте будет доступно в следующей версии.\n\n"
            "Пока можно записать сеанс с заметками через голосовое сообщение."
        )
        
        logger.info(f"User <TG_ID:{tg_id}> attempted client update")
        
    except Exception as e:
        logger.error(f"Error handling client update: {e}")
        await processing_msg.edit_text(f"❌ Ошибка обновления информации: {str(e)}")


async def on_startup():
    """Initialize services on startup"""
    logger.info("Starting Massage CRM Bot...")
    
    # Initialize database
    await db_service.initialize(Config.DATABASE_PATH)
    logger.info("Database service initialized")
    
    # Initialize Google Sheets
    await sheets_service.initialize()
    logger.info("Google Sheets service initialized")
    
    logger.info("Bot is ready!")


async def on_shutdown():
    """Cleanup on shutdown"""
    logger.info("Shutting down bot...")
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
