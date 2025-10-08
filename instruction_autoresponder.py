"""
Модуль инструкции для автоответчика
Содержит функцию для отображения подробной инструкции по использованию автоответчика
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_autoresponder_instruction_text():
    """
    Возвращает текст инструкции для автоответчика
    
    Returns:
        str: Текст инструкции
    """
    instruction_text = """<b>📼 Автоответчик</b>



🔘 В первую очередь вам следует сформировать текстовое сообщение, которое будет отправляться с вашего телеграмм аккаунта пользователю, что напишет вам в личные сообщения.
Допустим: "Приветствую ! Я не на рабочем месте, смогу ответить вам в течении двух часов."

🔘 Для одного и того же пользователя, что будет писать вам в личные сообщения, Автоответчик будет срабатывать раз в 10 секунд (тем самым предотвращая агрессивный спам ответов на каждое его сообщение)

🔘 Затем нажав на кнопку "Активировать" вы перемещаетесь в раздел, где должны выбрать аккаунты, на которых вы хотите подключить функцию Автоответчика и подтвердить ваш выбор.

🔘 Кнопка "Остановить" прекращает работу функции раздела "Автоответчик".
"""
    
    return instruction_text


def get_autoresponder_instruction_keyboard():
    """
    Возвращает клавиатуру для инструкции автоответчика
    
    Returns:
        InlineKeyboardMarkup: Клавиатура с кнопками
    """
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    
    # Кнопка для возврата к разделу выбора инструкций
    markup.inline_keyboard.append([
        InlineKeyboardButton(text="Вернуться 🔙", callback_data="instructions")
    ])
    
    return markup


def get_autoresponder_instruction_keyboard_en():
    """
    Возвращает английскую клавиатуру для инструкции автоответчика
    
    Returns:
        InlineKeyboardMarkup: Клавиатура с кнопками на английском языке
    """
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    
    # Кнопка для возврата к разделу выбора инструкций
    markup.inline_keyboard.append([
        InlineKeyboardButton(text="Back 🔙", callback_data="instructions")
    ])
    
    return markup


def get_autoresponder_instruction_text_en():
    """
    Возвращает английский текст инструкции для автоответчика
    
    Returns:
        str: Текст инструкции на английском языке
    """
    instruction_text = """<b>📼 Autoresponder</b>



🔘 First, prepare a text message that will be sent from your Telegram account to the user who writes to you in private messages.
For example: "Hello! I'm not at work, I can reply within two hours."

🔘 For the same user who keeps messaging you in private, the Autoresponder will trigger once every 10 seconds (to prevent aggressive spam replies to each of their messages).

🔘 Then, by clicking the "Activate" button, you move to the section where you should select the accounts on which you want to enable the Autoresponder feature and confirm your choice.

🔘 The "Stop" button stops the Autoresponder section.
"""
    
    return instruction_text


async def send_autoresponder_instruction(bot, chat_id, user_id=None, language="ru"):
    """
    Отправляет инструкцию по автоответчику пользователю
    
    Args:
        bot: Экземпляр бота
        chat_id: ID чата для отправки
        user_id: ID пользователя (для определения стиля изображений)
        language: Язык интерфейса ("ru" или "en")
    """
    try:
        # Получаем текст и клавиатуру в зависимости от языка
        if language == "en":
            text = get_autoresponder_instruction_text_en()
            keyboard = get_autoresponder_instruction_keyboard_en()
        else:
            text = get_autoresponder_instruction_text()
            keyboard = get_autoresponder_instruction_keyboard()
        
        # Отправляем сообщение с инструкцией
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
    except Exception as e:
        # В случае ошибки отправляем простое сообщение
        fallback_text = "Инструкция по автоответчику временно недоступна." if language == "ru" else "Autoresponder instructions are temporarily unavailable."
        await bot.send_message(
            chat_id=chat_id,
            text=fallback_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )