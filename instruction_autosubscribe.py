"""
Модуль инструкции для автоподписки
Содержит функции для отображения подробной инструкции по использованию раздела "Автоподписка".
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_autosubscribe_instruction_text():
    """
    Возвращает текст инструкции для автоподписки (RU)
    """
    return (
        "<b>💬 Автоподписка</b>\n\n\n\n"
        "🔘 В первую очередь вам нужно выбрать аккаунт, на котором вы хотите запустить сервис Автоподписки по группам/чатам/каналам.\n\n"
        "🔘 После выбора телеграмм аккаунта в разделе \"Выберите аккаунт для автоподписки:\" вы перемещаетесь в следующий раздел, где вам следует отправить список @username или ссылок в виде \"https://t.me/...\" на которые будет происходиться автоматическая подписка.\n\n"
        "🔘Не отправляйте в этом разделе @username или ссылки на чаты путём пересылания их из \"Избранное\" или других диалогов ― @username или ссылки \"https://t.me/...\" должны быть отправлены боту в этом разделе непосредственно вводом и отправкой сообщения. Поэтому, лучше всего заранее приготовить список в \"Избранное\", затем скопировать его и вставить в этот раздел.\n"
        "Учтите, что бот не в силах проходить капчи вместо вас. Это попросту невозможно в связи с Telegramp API ограничениями.\n\n\n"
        "🔘 Формат того, как должен выглядеть список:\n\n"
        "❌ \n@username1, @username2, @username3 ...\n\n"
        "✅\n@username1\n@username2\n@username3\n\n\n"
        "🔘 После ввода @username или ссылок \"https://t.me/...\", сервис автоподписки на чаты/каналы будет запущен:\n"
        "-Нажав кнопку \"Назад\" вы свернёте этот раздел и он будет работать в фоновом режиме.\n"
        "-Нажав кнопку \"Завершить\" и полностью прекращаете работу сервиса \"Автоподписка\"."
    )


def get_autosubscribe_instruction_keyboard():
    """
    Возвращает клавиатуру с кнопкой "Вернуться"
    """
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append([
        InlineKeyboardButton(text="Вернуться 🔙", callback_data="instructions")
    ])
    return markup


async def send_autosubscribe_instruction(bot, chat_id, user_id=None, language="ru"):
    """
    Отправляет инструкцию по автоподписке пользователю (RU)
    """
    try:
        text = get_autosubscribe_instruction_text()
        keyboard = get_autosubscribe_instruction_keyboard()
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await bot.send_message(chat_id=chat_id, text="Инструкция по автоподписке временно недоступна.")


