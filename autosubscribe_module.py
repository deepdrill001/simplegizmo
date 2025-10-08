import asyncio
import re
from typing import List, Optional, Callable, Awaitable

try:
    # Colorized CLI output (optional)
    from colorama import Fore, Style, init as colorama_init

    colorama_init(autoreset=True)
    COLOR_GREEN = Fore.GREEN
    COLOR_YELLOW = Fore.YELLOW
    COLOR_RED = Fore.RED
    COLOR_RESET = Style.RESET_ALL
except Exception:  # pragma: no cover - color is optional
    COLOR_GREEN = ""
    COLOR_YELLOW = ""
    COLOR_RED = ""
    COLOR_RESET = ""

# Telethon imports
try:
    from telethon.tl.functions.channels import JoinChannelRequest
    from telethon.errors import (
        FloodWaitError,
        UserAlreadyParticipantError,
        InviteRequestSentError,
        ChatWriteForbiddenError,
        ChatAdminRequiredError,
        ChannelPrivateError,
    )
except Exception as import_error:  # Defer import errors until call time
    JoinChannelRequest = None  # type: ignore
    FloodWaitError = type("FloodWaitError", (), {})  # type: ignore
    UserAlreadyParticipantError = type("UserAlreadyParticipantError", (), {})  # type: ignore
    InviteRequestSentError = type("InviteRequestSentError", (), {})  # type: ignore
    ChatWriteForbiddenError = type("ChatWriteForbiddenError", (), {})  # type: ignore
    ChatAdminRequiredError = type("ChatAdminRequiredError", (), {})  # type: ignore
    ChannelPrivateError = type("ChannelPrivateError", (), {})  # type: ignore


# Configuration per README_button_autosubscribe.md
join_interval: int = 10  # seconds between joins
batch_size: int = 5  # number of chats per batch
pause_duration: int = 15 * 60  # pause between batches (seconds)


def print_in_green(text: str) -> str:
    return f"{COLOR_GREEN}{text}{COLOR_RESET}"


def print_in_yellow(text: str) -> str:
    return f"{COLOR_YELLOW}{text}{COLOR_RESET}"


def print_in_red(text: str) -> str:
    return f"{COLOR_RED}{text}{COLOR_RESET}"


async def get_chat_links_from_saved_messages(client) -> List[str]:
    """Collect chat links and @usernames from 'Saved Messages'.

    Rules (per README):
    - Extract `https://t.me/...` links.
    - Extract @usernames (min length 5, alnum + underscore)
    - Include @username as `@name` if not already present as https link and not an email-like pattern with username@...
    - Preserve chronological order from oldest to newest.
    """
    chat_links: List[str] = []
    messages = []

    async for message in client.iter_messages("me"):
        messages.append(message)

    for message in reversed(messages):  # process from oldest
        try:
            content = getattr(message, "message", "") or ""
        except Exception:
            content = ""

        if not content:
            continue

        links = re.findall(r"https://t\.me/\S+", content)
        usernames = re.findall(r"@([a-zA-Z0-9_]{5,})", content)
        chat_links.extend(links)

        for username in usernames:
            already_has_link = any(link.startswith(f"https://t.me/{username}") for link in links)
            looks_like_email = re.search(rf"\b{re.escape(username)}@", content) is not None
            handle = f"@{username}"
            if not already_has_link and not looks_like_email and handle not in chat_links:
                chat_links.append(handle)

    return chat_links


async def countdown_timer(seconds: int) -> None:
    """Display a simple countdown with a red timer, sleeping asynchronously."""
    remaining = max(0, int(seconds))
    while remaining:
        minutes, secs = divmod(remaining, 60)
        timer = f"{minutes:02d}:{secs:02d}"
        print(f"\r{COLOR_RED}Пауза: {timer}{COLOR_RESET}", end="")
        await asyncio.sleep(1)
        remaining -= 1
    print("\r" + " " * 80, end="\r")


async def is_user_in_chat(client, chat: str) -> bool:
    """Return True if the user is already in the chat; False otherwise."""
    try:
        chat_info = await client.get_entity(chat)
        # Telethon entities may have attributes left/kicked
        if getattr(chat_info, "left", False) or getattr(chat_info, "kicked", False):
            return False
        return True
    except Exception as error:
        print(f"Ошибка при проверке участия в чате: {error}")
        return False


async def _subscribe_over_list(
    client,
    chat_links: List[str],
    reporter: Optional[Callable[[str], Awaitable[None]]] = None,
    guard: Optional[Callable[[], Awaitable[bool]]] = None,
) -> None:
    processed_in_batch = 0
    for chat_link in chat_links:
        # Крошечная уступка циклу событий, чтобы UI-бот оставался отзывчивым
        await asyncio.sleep(0)
        # Периодически проверяем доступ (trial/лицензия). Если guard вернул False — останавливаемся
        if guard is not None:
            try:
                should_continue = await guard()
            except Exception:
                should_continue = True
            if not should_continue:
                try:
                    if reporter is not None:
                        await reporter("Доступ истёк. Автоподписка остановлена.")
                except Exception:
                    pass
                return
        try:
            if await is_user_in_chat(client, chat_link):
                print(f"Уже подписаны на {chat_link}, пропускаем.")
                continue
            if JoinChannelRequest is None:
                raise RuntimeError("Telethon is not available: JoinChannelRequest import failed")
            try:
                await client(JoinChannelRequest(chat_link))
                success_text = f"Успешно подписались на {chat_link}"
                print(print_in_green(success_text))
                if reporter is not None:
                    try:
                        await reporter(success_text)
                    except Exception:
                        pass
                processed_in_batch += 1
            except UserAlreadyParticipantError:
                print(f"Уже подписаны на {chat_link}, пропускаем.")
            except InviteRequestSentError:
                print(print_in_yellow(f"Заявка успешно подана на {chat_link}"))
            # Сон после каждого join не блокирует event loop
            await asyncio.sleep(join_interval)
        except FloodWaitError as e:  # type: ignore[attr-defined]
            wait_seconds = int(getattr(e, "seconds", 0) or 0)
            log_text = f"Telegram API ограничение: требуется подождать {wait_seconds} секунд."
            print(print_in_red(log_text))
            if reporter is not None:
                try:
                    await reporter(log_text)
                except Exception:
                    pass
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
        except ChatWriteForbiddenError:
            print(print_in_red(f"Не удалось подписаться на {chat_link}: доступ запрещен."))
        except ChatAdminRequiredError:
            print(print_in_red(f"Не удалось подписаться на {chat_link}: требуется админ-доступ."))
        except ChannelPrivateError:
            print(print_in_red(f"Не удалось подписаться на {chat_link}: канал приватный или вы заблокированы."))
        except Exception as error:
            print(print_in_red(f"Ошибка при подписке на {chat_link}: {error}"))
        if processed_in_batch == batch_size:
            # Логика перерыва: сначала сообщаем общую длительность, затем каждые 5 минут оставшееся время
            pause_minutes = int(pause_duration // 60)
            start_text = f"Перерыв {pause_minutes} минут"
            print(print_in_yellow(start_text))
            if reporter is not None:
                try:
                    await reporter(start_text)
                except Exception:
                    pass

            five_min_seconds = 5 * 60
            steps = pause_duration // five_min_seconds
            remainder = pause_duration % five_min_seconds

            # Каждые 5 минут информируем о оставшемся времени (20, 15, 10, 5 ...)
            for i in range(int(steps) - 1, 0, -1):
                # Спим пачками по 5 минут, но цикл событий свободен
                await asyncio.sleep(five_min_seconds)
                # Проверка доступа на каждом тике перерыва
                if guard is not None:
                    should_continue = True
                    try:
                        should_continue = await guard()
                    except Exception:
                        should_continue = True
                    if not should_continue:
                        try:
                            if reporter is not None:
                                await reporter("Доступ истёк. Автоподписка остановлена.")
                        except Exception:
                            pass
                        return
                remaining_minutes = i * 5
                tick_text = f"До истечения перерыва осталось {remaining_minutes} минут"
                print(print_in_yellow(tick_text))
                if reporter is not None:
                    try:
                        await reporter(tick_text)
                    except Exception:
                        pass

            if remainder > 0:
                await asyncio.sleep(int(remainder))

            processed_in_batch = 0


async def subscribe_to_chats_from_saved(
    client,
    reporter: Optional[Callable[[str], Awaitable[None]]] = None,
    guard: Optional[Callable[[], Awaitable[bool]]] = None,
) -> None:
    """Subscribe the current account to chats found in Saved Messages.

    Follows pacing and batching rules from README.
    """
    print()  # blank line before start
    print("Получаем список чатов из 'Избранное'...")
    chat_links = await get_chat_links_from_saved_messages(client)
    print(f"Найдено {len(chat_links)} ссылок на чаты.")

    await _subscribe_over_list(client, chat_links, reporter, guard)

    done_text = "Весь список был успешно обработан. Автоподписка завершена."
    print(print_in_green(done_text))
    if reporter is not None:
        try:
            await reporter(done_text)
        except Exception:
            pass
    print()  # blank line after finish


async def subscribe_to_chats_list(
    client,
    raw_list: List[str],
    reporter: Optional[Callable[[str], Awaitable[None]]] = None,
    guard: Optional[Callable[[], Awaitable[bool]]] = None,
) -> None:
    """Subscribe using a provided list of @usernames or https://t.me links.

    - Normalizes inputs: strips spaces, extracts @handles and https links
    - Preserves order and removes duplicates
    - Applies same pacing and batching as from Saved Messages
    """
    normalized: List[str] = []
    seen = set()

    for item in raw_list:
        if not item:
            continue
        text = item.strip()
        # Extract links and @usernames from the line
        links = re.findall(r"https://t\.me/\S+", text)
        usernames = re.findall(r"@([a-zA-Z0-9_]{5,})", text)
        # Prefer explicit links first
        for link in links:
            if link not in seen:
                seen.add(link)
                normalized.append(link)
        for name in usernames:
            handle = f"@{name}"
            # Avoid adding handle if exact link already included
            if f"https://t.me/{name}" in seen:
                continue
            if handle not in seen:
                seen.add(handle)
                normalized.append(handle)

    print(f"Получен список из {len(normalized)} чатов/каналов для подписки")
    await _subscribe_over_list(client, normalized, reporter, guard)
    done_text = "Весь список был успешно обработан. Автоподписка завершена."
    print(print_in_green(done_text))
    if reporter is not None:
        try:
            await reporter(done_text)
        except Exception:
            pass
    print()


__all__ = [
    "join_interval",
    "batch_size",
    "pause_duration",
    "print_in_green",
    "print_in_yellow",
    "print_in_red",
    "get_chat_links_from_saved_messages",
    "countdown_timer",
    "is_user_in_chat",
    "subscribe_to_chats_from_saved",
    "subscribe_to_chats_list",
]
