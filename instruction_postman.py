"""
Модуль инструкции для почты
Содержит функцию для отображения подробной инструкции по использованию почты
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_postman_instruction_text():
    """
    Возвращает текст инструкции для почты
    
    Returns:
        str: Текст инструкции
    """
    instruction_text = """<b>📨 Почта</b>



🔘 Нажав кнопку "Активировать" вы перемещаетесь в раздел, где должны выбрать аккаунты, с которых вы хотите получать уведомления о новых входящих сообщениях.

🔘 После выбора аккаунта вы нажимаете кнопку "Далее", где должны выбрать лишь один аккаунт. Выбранный вами аккаунт будет выполнять функцию отправки поступившего сообщения с выбранных аккаунтов в предыдущем разделе, и перенаправлять это сообщение на @username, что вы укажете в следующем разделе.

🔘 Затем нажав кнопку "Подтвердить" вы перемещаетесь в раздел, где должны ввести @username аккаунта, на который вам будут приходить уведомления о новых сообщениях в виде содержимого этого сообщения, @username пользователя что отправил вам сообщение, а так же @username вашего аккаунта, на который вам пришло сообщение.
Пример:

----------------------------------
📤 @username_отправителя --->
----------------------------------



Добрый день.
Я заинтересован в ваших услугах.
Предлагаю обсудить детали сотрудничества.



---------------------------------
---> @username_получателя 📥
---------------------------------


🔘 Кнопка "Остановить" прекращает работу функции раздела "Почта"."""
    
    return instruction_text


def get_postman_instruction_keyboard():
    """
    Возвращает клавиатуру для инструкции почты
    
    Returns:
        InlineKeyboardMarkup: Клавиатура с кнопками
    """
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    
    # Кнопка для возврата к разделу выбора инструкций
    markup.inline_keyboard.append([
        InlineKeyboardButton(text="Вернуться 🔙", callback_data="instructions")
    ])
    
    return markup


def get_postman_instruction_text_en():
    """
    Возвращает английский текст инструкции для почты
    
    Returns:
        str: Английский текст инструкции
    """
    instruction_text = """<b>📨 Mailbox</b>

    

🔘 By clicking the "Activate" button you move to the section where you should select accounts from which you want to receive notifications about new incoming messages.

🔘 After selecting accounts you click the "Next" button, where you should select only one account. The account you selected will perform the function of sending the received message from the selected accounts in the previous section, and redirect this message to @username that you specify in the next section.

🔘 Then by clicking the "Confirm" button you move to the section where you should enter @username of the account to which you will receive notifications about new messages in the form of the content of this message, @username of the user who sent you the message, as well as @username of your account to which you received the message.
Example:

------------------------
📤 @sender_username --->
------------------------



Good day.
I am interested in your services.
I suggest discussing cooperation details.



---------------------------
---> @recipient_username 📥
---------------------------


🔘 The "Stop" button stops the function of the "Mailbox" section."""
    
    return instruction_text


def get_postman_instruction_keyboard_en():
    """
    Возвращает английскую клавиатуру для инструкции почты
    
    Returns:
        InlineKeyboardMarkup: Клавиатура с кнопками на английском языке
    """
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    
    # Кнопка для возврата к разделу выбора инструкций
    markup.inline_keyboard.append([
        InlineKeyboardButton(text="Back 🔙", callback_data="instructions")
    ])
    
    return markup


async def send_postman_instruction(bot, chat_id, user_id=None, language="ru"):
    """
    Отправляет инструкцию по почте пользователю
    
    Args:
        bot: Экземпляр бота
        chat_id: ID чата для отправки
        user_id: ID пользователя (для определения стиля изображений)
        language: Язык интерфейса ("ru" или "en")
    """
    try:
        # Получаем текст и клавиатуру в зависимости от языка
        if language == "en":
            text = get_postman_instruction_text_en()
            keyboard = get_postman_instruction_keyboard_en()
        else:
            text = get_postman_instruction_text()
            keyboard = get_postman_instruction_keyboard()
        
        # Отправляем сообщение с инструкцией
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        
    except Exception as e:
        # В случае ошибки отправляем простое сообщение
        fallback_text = "Инструкция по почте временно недоступна." if language == "ru" else "Mailbox instructions are temporarily unavailable."
        await bot.send_message(
            chat_id=chat_id,
            text=fallback_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )