"""
Модуль инструкции для рассылки
Содержит функции для отображения подробной инструкции по использованию раздела "Рассылка".
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def _get_back_keyboard_ru():
    """
    Возвращает RU-клавиатуру с кнопкой назад для инструкций
    """
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append([
        InlineKeyboardButton(text="Вернуться 🔙", callback_data="instructions")
    ])
    return markup


def _get_back_keyboard_en():
    """
    Возвращает EN-клавиатуру с кнопкой назад для инструкций
    """
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append([
        InlineKeyboardButton(text="Back 🔙", callback_data="instructions")
    ])
    return markup


def _messages_ru():
    """
    Возвращает список из 10 сообщений инструкции (RU) в строгой последовательности
    """
    return [
        # 1
        (
            "<b>🧑‍💻 Рассылка</b>\n\n\n\n"
            "<b>Кратко о том, по какому принципу работает Авторассылка:</b>\n\n"
            "1) В первую очередь вы должны быть подписаны на группы/чаты, в которые планируете отправлять сообщения.\n\n"
            "2) На аккаунтах, с которых вы планируете делать рассылку у вас обязательно должны быть созданы папки, в которых будут находиться ваши чаты, по которым будет происходить рассылка.\n"
            "Чаты в папках НЕ должны быть закреплены. \n"
            "Это важно, так как закрепленные чаты бот игнорирует (он их попросту не видит). \n"
            "К сожалению, это API ограничение от Telegram и его невозможно обойти.\n\n"
            "3) В папках у вас может находится любое количество чатов, но за одну сессию с каждого выбранного аккаунта будет отправлено 30 сообщений. Затем бот остановится на перерыв 8 часов, после которого автоматически продолжит рассылку с той же папки и того чата, на котором он остановился в последний раз, достигнув лимита отправки 30 сообщений за одну сессию. \n"
            "Перед отправкой каждого сообщения будет произведена случайная пауза от 15 до 45 секунд (для имитации деятельности живого человека)\n"
            "Это сделано намеренно, поскольку лимит на отправку сообщений в группы/чаты с одного аккаунта равняется 100 сообщениям (за исключением, если у вас не приобретен Telegram Premium на аккаунте, с которого будут отправляться сообщения).\n"
            "Это API ограничение Telegram и его невозможно обойти. \n"
            "Мы крайне НЕ РЕКОМЕНДУЕМ вам пренебрегать лимитами.\n"
            "Мы не несем ответственность за ваши Telegram аккаунты, и тем более если вы самодеятельно принимаете решение их игнорировать.\n\n"
            "4) За 24 часа с каждого аккаунта будет отправлено 90 сообщений. Мы берём во внимание небольшую погрешность в 10 сообщений, чтобы уберечь вас от негативного опыта в виде блокировки ваших телеграмм аккаунтов. \n\n"
            "5) После того, как во все чаты из папки будут отправлены сообщения — бот автоматически перейдет к следующей папке.\n"
            "Если на вашем аккаунте было, допустим, 5 папок, тогда после отправки сообщений во все чаты из последней папки, бот начнёт цикл заново с 1 папки. \n"
            "Таким образом, бот автономно и циклически будет рассылать сообщения по чатам из папок до тех пор, пока вы сами не нажмёте кнопку «Остановить»."
        ),
        # 2
        (
            "<b>Теперь перейдём к описанию всех кнопок, режимов и выборок при настройке:</b>\n\n\n\n"
            "<b>Шаблоны</b>\n\n"
            "🔘 В первую очередь вам следует сформировать текстовое сообщение, которое будет отправляться с вашего телеграмм аккаунта по чатам/группам. \n"
            "На текущий момент допускается отправка лишь текстового сообщения (без медиа). \n"
            "Со временем будет доступна возможность отправлять сообщения с изображениями, .GIF или видео.\n\n\n\n"
            "<b>Активировать</b> \n\n"
            "🔘 Затем, нажав на кнопку \"Активировать\" вы перемещаетесь в раздел, где должны выбрать аккаунты, с которых будут отправляться сообщения."
        ),
        # 3
        (
            "<b>Последняя сводка</b>\n\n\n\n"
            "🔘 При нажатии на кнопку «Да» разделе «Последняя сводка» вы сможете увидеть, какие из аккаунтов находятся на перерыве и сколько времени до конца перерыва осталось для каждого аккаунта, а так же здесь будут отображены последние лимиты отправленных сообщений на ваших аккаунтах за последнюю запущенную сессию.\n\n"
            "🔘 Если вы запускаете рассылку в первый раз либо хотите пропустить этот раздел — нажимаете кнопку «Нет»."
        ),
        # 4
        (
            "<b>Выбор режима</b>\n\n\n\n"
            "🔘 <b>Ручная настройка.</b>\n"
            "В этом режиме вы сможете гибко выбрать папку и текстовое сообщение для каждого аккаунта.\n"
            "Таким образом, вы сможете выбрать для конкретного аккаунта с какой папки в нём начнётся рассылка, а так же текстовое сообщение (шаблон), которое будет рассылаться по чатам.\n"
            "Соответсвенно, для одного аккаунта вы можете выбрать 1(первую) папку и 3 шаблон, а для следующего аккаунта 4 папку и 1 шаблон. И так далее, по такому принципу.\n\n"
            "🔘 <b>Автоматическая настройка.</b>\n"
            "При выборе данного режима вы выберете папку и шаблон только для одного (самого первого аккаунта). \n"
            "Для всех остальных аккаунтов папки и шаблоны будут выбраны по принципу нарастающей:\n"
            "Если для первого аккаунта вы выбрали папку 1 и шаблон 1, то для следующего аккаунта будет автоматически выбрана 2 папка и 2 шаблон, затем для следующего аккаунта будет выбрана папка 3 и шаблон 3, и так далее.\n\n"
            "🔘 <b>Возобновить процесс.</b> \n"
            "На случай, если вы ошибочно остановили процесс рассылки (либо передумали и захотели продолжить рабочий процесс рассылки), то при выборе этого режима вы перемещаетесь в раздел, где сможете:\n"
            "✔️ Ждать перерыв.\n"
            "По окончанию самого длинного перерыва из всех аккаунтов — рассылка будет возобновлена.\n"
            "✔️ Принудительно продолжить.\n"
            "Произойдёт немедленное возобновление процесса Рассылки: \n"
            "-если аккаунт находился на перерыве, тогда перерыв будет завершён и рассылка для таких аккаунтов продолжится с последних чатов, на которых она была прервана.\n"
            "-для аккаунта, который не находился на перерыве а его лимит отправленных сообщений за текущую сессию не был достигнут 30 сообщений (допустим, 23/30) рассылка для такого аккаунта будет возобновлена, и как только аккаунт достигнет лимит 30 сообщений — он остановится на перерыв 8 часов.\n"
            "✔️ Сбросить все лимиты.\n"
            "Произойдёт полный сброс состояний для всех аккаунтов — лимиты отправленных сообщений за последнюю сессию обнулятся, а перерывы будут завершены:\n"
            "-если аккаунт находился на перерыве, тогда перерыв будет завершён и рассылка для таких аккаунтов продолжится с последних чатов, на которых она была прервана.\n"
            "-для аккаунта, который не находился на перерыве а его лимит отправленных сообщений за текущую сессию не был достигнут 30 сообщений (допустим, 23/30) — тогда лимит обнулится до 0, и с этого аккаунта снова будет отправлено 30 сообщений.\n"
            "Одновременно с этим произойдёт немедленный перезапуск рассылки с последних чатов, на которых аккаунты были остановлены."
        ),
        # 5
        (
            "<b>Включить логирование статусов отправки сообщений</b>\n\n\n\n"
            "🔘 Если вы выбираете «Да», тогда бот будет вам отправлять сообщения в чат о том, было ли успешно или неудачно отправлено сообщение в какой-либо из чатов. \n"
            "Например:\n"
            "@username_аккаунта: Название чата 1: Успшено / 1 \n"
            "@username_аккаунта: Название чата 2: Неудачно / 2\n\n"
            "🔘 Если вы выбираете «Нет», тогда бот не будет отправлять вам в чат сообщения об отправленных сообщениях."
        ),
        # 6
        (
            "<b>Включить чередование шаблонов</b>\n\n\n\n"
            "🔘 Если вы выбираете «Да», и на одном из ваших аккаунтов более одного шаблона (допустим, 3), тогда после того, как рассылка будет реализована по всем папкам и цикл начнётся заново с первой папки — на следующем круге бот будет рассылать уже следующее текстовое сообщение из списка сформированных вами шаблонов в разделе «Шаблоны».\n\n"
            "🔘 Если вы выбираете «Нет», тогда по всем чатам будет рассылаться фиксированно одно и то же текстовое сообщение, не зависимо от циклов."
        ),
        # 7
        (
            "<b>Выберите тип шаблона для аккаунта / Выберите папку для аккаунта</b>\n\n\n\n"
            "🔘 Выбранный шаблон будет использоваться в качестве рассылаемого текстового сообщения.\n\n"
            "🔘 Выбранная папка будет являться первой папкой, с которой бот начнёт рассылать сообщения по чатам."
        ),
        # 8
        (
            "<b>Игнорировать рассылку в определенных папках</b>\n\n\n\n"
            "🔘 Нажимая «Да» — здесь вы сможете выбрать папки, которые будут проигнорированы для рассылки.\n\n"
            "🔘 Нажимая «Нет» — вы пропускаете этот раздел"
        ),
        # 9
        (
            "<b>Игнорировать рассылку в определенных чатах</b>\n\n\n\n"
            "🔘 Нажимая «Да» — здесь вы сможете выбрать чаты, которые будут проигнорированы для рассылки.\n\n"
            "🔘 Если вы нажимаете «Нет» — вы пропускаете этот раздел."
        ),
        # 10
        (
            "<b>Итоговые настройки</b>\n\n\n\n"
            "🔘 В данном разделе для вашего удобства будут отображены все ваши выбранные параметры. \n\n"
            "🔘 Нажав кнопку “START” будет начат процесс рассылки.\n\n"
            
        ),
    ]


def _messages_en():
    """
    Возвращает список EN-сообщений (структура сохранена, краткие заглушки)
    """
    return [
        (
            "<b>🧑‍💻 Mailing</b>\n\n\n\n"
            "<b>How the Auto-Mailing works:</b>\n\n"
            "1) First, you must be subscribed to the groups/chats where you plan to send messages.\n\n"
            "2) On the accounts you plan to use for mailing, you <b>must</b> create folders that contain the chats for mailing.\n"
            "Chats in folders <b>must not</b> be pinned.\n"
            "Pinned chats are ignored by the bot (it simply does not see them).\n"
            "Unfortunately, this is a Telegram API limitation and cannot be bypassed.\n\n"
            "3) A folder may contain any number of chats, but within a single session each selected account will send 30 messages. Then the bot will pause for 8 hours and automatically resume from the same folder and chat where it stopped last time.\n"
            "Before each message a random delay of 15–45 seconds is applied (to imitate human behavior).\n"
            "This is intentional because the limit for sending messages to groups/chats from one account is 100 messages (unless you have Telegram Premium on that sending account).\n"
            "This is a Telegram API limitation and cannot be bypassed.\n"
            "We <b>strongly DO NOT RECOMMEND</b> ignoring limits.\n"
            "We are not responsible for your Telegram accounts, especially if you choose to ignore the limits.\n\n"
            "4) In 24 hours, each account will send 90 messages. We consider a small margin of ±10 messages to protect you from a negative experience like account restrictions.\n\n"
            "5) After messages are sent to all chats in the folder, the bot automatically moves to the next folder.\n"
            "If your account had, say, 5 folders, then after finishing the last folder the bot starts the cycle again from folder 1.\n"
            "Thus, the bot will keep sending messages cyclically until you press “Stop”."
        ),
        (
            "<b>Now let’s go through all buttons, modes and selections:</b>\n\n\n\n"
            "<b>Templates</b>\n\n"
            "🔘 First, prepare the text message that will be sent from your Telegram account to groups/chats.\n"
            "At the moment only plain text messages are supported (no media).\n"
            "In the future, images, GIFs and videos will be supported.\n\n\n\n"
            "<b>Activate</b> \n\n"
            "🔘 Then, by pressing \"Activate\", you move to the section where you select the accounts that will send the messages."
        ),
        (
            "<b>Last summary</b>\n\n\n\n"
            "🔘 By pressing “Yes” in the “Last summary” section you can see which accounts are on a break and how much time is left for each one, as well as the last sent-message limits from the previous session.\n\n"
            "🔘 If you are launching mailing for the first time or want to skip this section — press “No”."
        ),
        (
            "<b>Mode selection</b>\n\n\n\n"
            "🔘 <b>Manual setup.</b>\n"
            "In this mode you can flexibly choose the folder and the text template for each account.\n"
            "This way you can start mailing from a specific folder for a specific account, and pick which template will be used.\n"
            "For example: for one account choose folder 1 and template 3; for the next account folder 4 and template 1, and so on.\n\n"
            "🔘 <b>Automatic setup.</b>\n"
            "With this mode you choose a folder and a template only for the first account.\n"
            "For all the next accounts the folder and template will be selected incrementally: if for the first account you chose folder 1 and template 1, then for the second it will be folder 2 and template 2, for the third — folder 3 and template 3, and so on.\n\n"
            "🔘 <b>Resume process.</b>\n"
            "If you accidentally stopped mailing (or changed your mind and want to continue), here you can:\n"
            "✔️ Wait for break — after the longest break finishes among all accounts, mailing will resume.\n"
            "✔️ Force resume — immediate resumption:\n"
            "- if an account was on a break, the break ends and mailing continues from the last chat;\n"
            "- if an account was not on a break and its current session counter has not yet reached 30 messages (e.g., 23/30), it will continue and then go on an 8-hour break upon reaching 30.\n"
            "✔️ Reset all limits — complete reset of states for all accounts: last-session counters will reset to 0 and current breaks will end.\n"
            "- if an account was on a break, the break ends and mailing continues from the last chat;\n"
            "- if an account was not on a break and its session counter hadn’t reached 30 messages (e.g., 23/30), it resets to 0 and up to 30 messages will be sent again.\n"
            "At the same time, mailing restarts immediately from the last stopped chats."
        ),
        (
            "<b>Enable delivery status logging</b>\n\n\n\n"
            "🔘 If you choose “Yes”, the bot will send you messages indicating whether a message was sent successfully or not to a specific chat.\n"
            "Example:\n"
            "@your_account_username: Chat name 1: Success / 1\n"
            "@your_account_username: Chat name 2: Failed / 2\n\n"
            "🔘 If you choose “No”, the bot will not send delivery messages to the chat."
        ),
        (
            "<b>Enable template alternation</b>\n\n\n\n"
            "🔘 If you choose “Yes” and one of your accounts has more than one template (e.g., 3), then after mailing through all folders completes and the cycle starts again from the first folder, on the next cycle the bot will use the next template from your Templates list.\n\n"
            "🔘 If you choose “No”, the same fixed text template will be sent to all chats regardless of cycles."
        ),
        (
            "<b>Select template type for the account / Select folder for the account</b>\n\n\n\n"
            "🔘 The selected template will be used as the message text.\n\n"
            "🔘 The selected folder will be the first folder from which the bot starts mailing."
        ),
        (
            "<b>Ignore mailing in specific folders</b>\n\n\n\n"
            "🔘 Pressing “Yes” — you can choose folders to be ignored.\n\n"
            "🔘 Pressing “No” — you skip this section."
        ),
        (
            "<b>Ignore mailing in specific chats</b>\n\n\n\n"
            "🔘 Pressing “Yes” — you can choose chats to be ignored.\n\n"
            "🔘 Pressing “No” — you skip this section."
        ),
        (
            "<b>Final settings</b>\n\n\n\n"
            "🔘 For your convenience, all selected parameters will be displayed here.\n\n"
            "🔘 Press “START” to begin mailing.\n\n"
            
        ),
    ]


async def send_mailing_instruction(bot, chat_id, user_id=None, language="ru"):
    """
    Отправляет 10 сообщений инструкции по рассылке в строгой последовательности.

    На последнее сообщение добавляется клавиатура с кнопкой "Вернуться"/"Back".
    """
    try:
        if language == "en":
            messages = _messages_en()
            back_keyboard = _get_back_keyboard_en()
        else:
            messages = _messages_ru()
            back_keyboard = _get_back_keyboard_ru()

        # Отправляем первые 9 сообщений без клавиатуры
        for i, text in enumerate(messages, start=1):
            if i < len(messages):
                await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
            else:
                # Последнее сообщение с клавиатурой "Назад"
                await bot.send_message(chat_id=chat_id, text=text, reply_markup=back_keyboard, parse_mode="HTML")
    except Exception:
        # Фолбэк — краткое одно сообщение
        fallback_text = (
            "Инструкция по рассылке временно недоступна." if language == "ru" else "Mailing instructions are temporarily unavailable."
        )
        await bot.send_message(chat_id=chat_id, text=fallback_text)

