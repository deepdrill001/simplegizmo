        
import os
import time
import re
import json
import asyncio
import shutil
import os
import sys
import random
import socket
import ast
import threading
import logging
from datetime import datetime, timezone
from collections import defaultdict
from telethon import TelegramClient, functions, types, events
from telethon.errors import RPCError
from asyncio import TimeoutError as ConnectionError
from telethon.errors import SessionPasswordNeededError, PasswordHashInvalidError, AuthRestartError
from telethon.sync import TelegramClient
from telethon.tl.functions.messages import GetDialogFiltersRequest, UpdateDialogFilterRequest
from telethon.tl.types import DialogFilter, DialogFilterDefault
from telethon.errors import SessionPasswordNeededError, PasswordHashInvalidError, AuthRestartError, FilterIncludeEmptyError
from telethon.errors import RPCError
from asyncio import TimeoutError as ConnectionError
from datetime import datetime, timezone
from telethon import events
from pathlib import Path
from autosubscribe_module import subscribe_to_chats_from_saved, subscribe_to_chats_list

# Aiogram импорты
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    Message, CallbackQuery,
    FSInputFile
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError, TelegramConflictError
from aiogram.filters import Command
from aiogram import F

# Константы
TOKEN = "7563674409:AAEW6uMHgZYn0b4GDFblAYSNaWn6ZQYb3yA"
KEYS_FILE = "key.json"
LICENSE_FILE = "license.json"
LICENSE_DURATION_DAYS = 30
MAX_ACCOUNTS_PER_USER = 10  # Глобальный дефолт (не используется для pro/premium/basic)

def get_max_sessions_for_license(user_id: int) -> int:
    """Возвращает лимит сессий на ключ для текущего типа лицензии пользователя.

    pro=15, premium=10, basic=5, trial=3, owner/admin=бесконечность (возвращаем очень большое число).
    """
    license_type = user_states.get(f"{user_id}_license_type")
    
    # Определяем тип лицензии только для owner и admin - это критично для правильного отображения
    if not license_type:
        license_type = detect_license_type(user_id)
        if license_type in ["owner", "admin"]:
            user_states[f"{user_id}_license_type"] = license_type
    
    if license_type in ("owner", "admin"):
        return 10**9
    if license_type == "trial":
        return 3
    if license_type == "pro":
        return 15
    if license_type == "premium":
        return 10
    if license_type == "basic":
        return 5
    # Неопределённый — используем консервативный минимум
    return 5
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
OWNER_DIR = os.path.join(PROJECT_ROOT, "owner")

# Настройка логирования Telethon для подавления ненужных сообщений
def setup_telethon_logging():
    """Настраивает логирование Telethon для фильтрации ненужных сообщений"""
    # Создаем кастомный фильтр для логов
    class TelethonLogFilter(logging.Filter):
        def filter(self, record):
            # Фильтруем сообщения об ошибках auth_key
            if "auth_key failed" in str(record.msg):
                return False
            # Фильтруем сообщения о новых ключах
            if "new auth_key" in str(record.msg):
                return False
            # Фильтруем сообщения о nonce hash
            if "nonce hash" in str(record.msg):
                return False
            # Фильтруем известные баги Telethon v1.40.0
            msg_str = str(record.msg)
            if ("Should not be applying the difference" in msg_str or
                "Called end_get_diff on an entry" in msg_str or
                "Fatal error handling updates" in msg_str):
                print(f"🐛 Подавлен известный баг Telethon v1.40.0: {msg_str[:100]}...")
                return False
            return True
    
    # Настраиваем логирование Telethon
    telethon_logger = logging.getLogger('telethon')
    telethon_logger.setLevel(logging.WARNING)
    
    # Добавляем фильтр
    telethon_logger.addFilter(TelethonLogFilter())
    
    # Настраиваем логирование для других модулей Telethon
    for logger_name in ['telethon.network', 'telethon.crypto']:
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.ERROR)
        logger.addFilter(TelethonLogFilter())

# Инициализируем логирование при импорте
setup_telethon_logging()


# Функции для работы с cookies.json
async def get_all_dialogs_usernames(client):
    """
    Получает все @username диалогов/чатов/групп/каналов для авторизованного аккаунта
    и возвращает их в структурированном виде для cookies.json
    """
    try:
        #print("🔍 Получение всех диалогов для cookies.json...")
        
        # Проверяем, подключен ли клиент
        if not client.is_connected():
            print("⚠️ Клиент не подключен, подключаемся...")
            await client.connect()
        
        # Проверяем авторизацию
        if not await client.is_user_authorized():
            print("❌ Клиент не авторизован")
            return None
        
        print("✅ Клиент подключен и авторизован, получаем диалоги...")
        all_dialogs = await client.get_dialogs(limit=10000)
        #print(f"📊 Получено {len(all_dialogs)} диалогов")
        
        # Структура для cookies.json
        dialogs_data = {
            "personal_chats": [],      # Личные чаты и диалоги
            "groups_channels": [],     # Группы, каналы, боты
            "added_later": [],         # Новые диалоги, добавленные позже
        }
        
        for dialog in all_dialogs:
            entity = dialog.entity
            username = getattr(entity, 'username', None)
            
            if username:
                # Определяем тип сущности
                # Используем строковые проверки для совместимости
                entity_type = str(type(entity))
                
                if "User" in entity_type:
                    try:
                        if getattr(entity, 'bot', False):
                            # Боты
                            dialogs_data["groups_channels"].append(f"@{username}")
                        else:
                            # Личные чаты
                            dialogs_data["personal_chats"].append(f"@{username}")
                    except Exception as e:
                        # Если не удается определить, бот это или нет, добавляем в personal_chats
                        print(f"  ⚠️ Не удалось определить тип пользователя для {username}: {e}")
                        dialogs_data["personal_chats"].append(f"@{username}")
                elif "Chat" in entity_type:
                    # Группы
                    dialogs_data["groups_channels"].append(f"@{username}")
                elif "Channel" in entity_type:
                    try:
                        if getattr(entity, 'megagroup', False):
                            # Супергруппы
                            dialogs_data["groups_channels"].append(f"@{username}")
                        elif getattr(entity, 'broadcast', False):
                            # Каналы
                            dialogs_data["groups_channels"].append(f"@{username}")
                        else:
                            # Обычные каналы
                            dialogs_data["groups_channels"].append(f"@{username}")
                    except Exception as e:
                        # Если не удается определить тип канала, добавляем в groups_channels
                        print(f"  ⚠️ Не удалось определить тип канала для {username}: {e}")
                        dialogs_data["groups_channels"].append(f"@{username}")
                
                # Слишком шумно: подробный вывод каждого диалога отключён
        
        print(f"✅ Получено диалогов: personal_chats={len(dialogs_data['personal_chats'])}, groups_channels={len(dialogs_data['groups_channels'])}")
        print(f"📋 Примеры personal_chats: {dialogs_data['personal_chats'][:5] if dialogs_data['personal_chats'] else 'нет'}")
        print(f"📋 Примеры groups_channels: {dialogs_data['groups_channels'][:5] if dialogs_data['groups_channels'] else 'нет'}")
        print(f"🆕 Новые диалоги: {len(dialogs_data['added_later'])}")
        return dialogs_data
        
    except Exception as e:
        print(f"❌ Ошибка при получении диалогов: {e}")
        import traceback
        traceback.print_exc()
        return None

def update_cookies_json(user_id, session_name, dialogs_data):
    """
    Обновляет файл cookies.json с информацией о диалогах авторизованного аккаунта
    """
    try:
        cookies_file = "cookies.json"
        print(f"📝 Обновление cookies.json для пользователя {user_id}, сессия {session_name}")
        
        # Загружаем существующие данные
        existing_data = {}
        if os.path.exists(cookies_file):
            try:
                with open(cookies_file, "r", encoding="utf-8") as f:
                    existing_data = json.load(f)
                print(f"📂 Загружен существующий cookies.json с {len(existing_data)} пользователями")
            except (json.JSONDecodeError, FileNotFoundError):
                print("📂 Создаем новый cookies.json")
                existing_data = {}
        else:
            print("📂 Создаем новый cookies.json")
        
        # Обновляем данные для пользователя
        user_id_str = str(user_id)
        if user_id_str not in existing_data:
            existing_data[user_id_str] = {}
            print(f"👤 Добавлен новый пользователь {user_id_str}")
        else:
            print(f"👤 Обновляем существующего пользователя {user_id_str}")
        
        # Проверяем, есть ли уже сессия с таким именем
        final_session_name = session_name
        counter = 1
        
        while final_session_name in existing_data[user_id_str]:
            # Если сессия уже существует, добавляем счетчик
            counter += 1
            final_session_name = f"{session_name} ({counter})"
            print(f"🔄 Сессия {session_name} уже существует, переименовываем в {final_session_name}")
        
        # Добавляем дату авторизации
        from datetime import datetime
        current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Создаем данные сессии с новыми полями
        session_data = {
            "personal_chats": dialogs_data["personal_chats"],
            "groups_channels": dialogs_data["groups_channels"],
            "added_later": dialogs_data.get("added_later", []),
        }
        
        
        # Добавляем сессию с уникальным именем
        existing_data[user_id_str][final_session_name] = session_data
        print(f"📱 Добавлена сессия {final_session_name} с датой {current_date}")
        
        # Сохраняем обновленные данные
        with open(cookies_file, "w", encoding="utf-8") as f:
            json.dump(existing_data, f, ensure_ascii=False, indent=2)
        
        print(f"✅ Обновлен cookies.json для пользователя {user_id}, сессия {final_session_name}")
        print(f"📊 Структура: {len(existing_data)} пользователей, {len(existing_data.get(user_id_str, {}))} сессий")
        print(f"📋 Категории диалогов: personal_chats (личные чаты), groups_channels (группы/каналы)")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка обновления cookies.json: {e}")
        import traceback
        traceback.print_exc()
        return False



# Новые функции для работы с индивидуальными файлами пользователей
# (будут определены после всех необходимых функций)

# Глобальные переменные для системы реконнектеров
connection_monitor_task = None
reconnection_attempts = {}  # {client_id: attempt_count}
max_reconnection_delay = 60  # Максимальная задержка между попытками
base_reconnection_delay = 5  # Базовая задержка
internet_connection_status = True
last_internet_check = 0
disabled_clients = set()  # {(user_id, session_name)} помеченные как отключенные навсегда (деавторизованы/нет .session)
disabled_session_names = set()  # {session_name} глобальная метка по имени сессии

# Функции системы реконнектеров
async def check_internet_connection():
    """Проверяет доступность интернета с кешированием результата"""
    global internet_connection_status, last_internet_check
    
    current_time = time.time()
    
    # Проверяем интернет каждые 30 секунд
    if current_time - last_internet_check > 30:
        internet_connection_status = is_internet_available()
        last_internet_check = current_time
    
    return internet_connection_status

async def ensure_client_connected(client, session_name, user_id=None, max_retries=None):
    """
    Универсальная функция для обеспечения подключения клиента с бесконечными попытками.
    
    Args:
        client: TelegramClient
        session_name: Имя сессии
        user_id: ID пользователя для логирования
        max_retries: Максимальное количество попыток (None = бесконечно)
    
    Returns:
        bool: True если подключение успешно, False если достигнут лимит попыток
    """
    client_id = f"{user_id}_{session_name}"
    attempt = 0
    
    while max_retries is None or attempt < max_retries:
        try:
            # Проверяем текущее состояние
            if client.is_connected() and await client.is_user_authorized():
                # Сбрасываем счетчик попыток при успешном подключении
                if client_id in reconnection_attempts:
                    del reconnection_attempts[client_id]
                return True
            
            # Проверяем интернет соединение
            if not await check_internet_connection():
                delay = min(base_reconnection_delay * (2 ** min(attempt, 4)), max_reconnection_delay)
                # Отключили отправку в чат уведомления об отсутствии интернета по запросу пользователя
                print(f"🌐 Нет интернет соединения. Повторная попытка через {delay}с...")
                await asyncio.sleep(delay)
                attempt += 1
                continue
            
            # Тихий режим: логируем только в консоль
            print(f"🔄 Переподключение клиента {session_name} (попытка {attempt + 1})...")
            
            # Отключаем, если подключен
            if client.is_connected():
                await client.disconnect()
            
            # Оптимизированная экспоненциальная задержка
            if attempt > 0:
                # Более агрессивные таймауты для первых попыток
                if attempt == 1:
                    delay = 1  # Первая попытка - всего 1 секунда
                elif attempt == 2:
                    delay = 2  # Вторая попытка - 2 секунды  
                elif attempt == 3:
                    delay = 3  # Третья попытка - 3 секунды
                else:
                    delay = min(base_reconnection_delay * (2 ** min(attempt - 3, 4)), max_reconnection_delay)
                await asyncio.sleep(delay)
            
            # Пытаемся подключиться с таймаутом
            try:
                await asyncio.wait_for(client.connect(), timeout=15.0)
            except asyncio.TimeoutError:
                print(f"⏰ Таймаут подключения для {session_name}, переходим к следующей попытке")
                continue
            
            # Проверяем авторизацию с таймаутом
            try:
                is_auth = await asyncio.wait_for(client.is_user_authorized(), timeout=10.0)
            except asyncio.TimeoutError:
                print(f"⏰ Таймаут авторизации для {session_name}, переходим к следующей попытке")
                is_auth = False
            
            if is_auth:
                # Тихий режим: логируем только в консоль
                print(f"✅ Клиент {session_name} успешно переподключен")
                
                # Сбрасываем счетчик попыток
                if client_id in reconnection_attempts:
                    del reconnection_attempts[client_id]
                return True
            else:
                if user_id:
                    await log_to_telegram(user_id, f"❌ Клиент {session_name} не авторизован после подключения", "connection_manager")
                else:
                    print(f"❌ Клиент {session_name} не авторизован после подключения")
                
        except Exception as e:
            error_str = str(e)
            # Специальная обработка известных ошибок Telethon v1.40.0
            if ("Should not be applying the difference" in error_str or 
                "Called end_get_diff on an entry" in error_str or
                "KeyError:" in error_str and "getting_diff_for" in error_str):
                print(f"⚠️ Обнаружен баг Telethon v1.40.0 для {session_name}, принудительное переподключение...")
                try:
                    await client.disconnect()
                    await asyncio.sleep(1)  # Короткая пауза
                    await client.connect()
                    if await client.is_user_authorized():
                        print(f"✅ Восстановлено подключение для {session_name} после Telethon-бага")
                        if client_id in reconnection_attempts:
                            del reconnection_attempts[client_id]
                        return True
                except Exception:
                    pass
            
            if user_id:
                await log_to_telegram(user_id, f"❌ Ошибка переподключения {session_name}: {e}", "connection_manager")
            else:
                print(f"❌ Ошибка переподключения {session_name}: {e}")
        
        # Увеличиваем счетчик попыток
        reconnection_attempts[client_id] = attempt + 1
        attempt += 1
        
        # Если установлен лимит попыток и мы его достигли
        if max_retries is not None and attempt >= max_retries:
            if user_id:
                await log_to_telegram(user_id, f"❌ Достигнут лимит попыток переподключения для {session_name}", "connection_manager")
            else:
                print(f"❌ Достигнут лимит попыток переподключения для {session_name}")
            return False
    
    return False

async def ensure_client_connected_simple(client, session_name, user_id=None):
    """Простая функция для переподключения клиента (для обратной совместимости)"""
    return await ensure_client_connected(client, session_name, user_id, max_retries=3)

class ConnectionManager:
    """Менеджер подключений для централизованного управления реконнектерами"""
    
    def __init__(self):
        self.monitor_tasks = {}  # {user_id: asyncio.Task}
        self.client_states = {}  # {user_id: {session_name: {"connected": bool, "last_check": float}}}
        self.reconnection_locks = {}  # {client_id: asyncio.Lock}
    
    async def start_monitoring(self, user_id):
        """Запускает мониторинг подключений для пользователя"""
        if user_id not in self.monitor_tasks or self.monitor_tasks[user_id].done():
            self.monitor_tasks[user_id] = asyncio.create_task(self._monitor_user_connections(user_id))
    
    async def stop_monitoring(self, user_id):
        """Останавливает мониторинг подключений для пользователя"""
        if user_id in self.monitor_tasks:
            self.monitor_tasks[user_id].cancel()
            try:
                await self.monitor_tasks[user_id]
            except asyncio.CancelledError:
                pass
            del self.monitor_tasks[user_id]
    
    async def _monitor_user_connections(self, user_id):
        """Мониторинг подключений для конкретного пользователя"""
        while True:
            try:
                # Проверяем все активные клиенты пользователя
                if user_id in active_clients:
                    for session_name, client in active_clients[user_id].items():
                        client_id = f"{user_id}_{session_name}"
                        
                        # Создаем блокировку для этого клиента, если её нет
                        if client_id not in self.reconnection_locks:
                            self.reconnection_locks[client_id] = asyncio.Lock()
                        
                        # Проверяем подключение без блокировки других операций
                        asyncio.create_task(self._check_and_reconnect_client(user_id, session_name, client))
                
                # Проверяем каждые 10 секунд
                await asyncio.sleep(10)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Ошибка в мониторе подключений для пользователя {user_id}: {e}")
                await asyncio.sleep(5)
    
    async def _check_and_reconnect_client(self, user_id, session_name, client):
        """Проверяет и переподключает клиента при необходимости"""
        client_id = f"{user_id}_{session_name}"
        
        try:
            # Используем блокировку для предотвращения одновременных переподключений
            async with self.reconnection_locks.get(client_id, asyncio.Lock()):
                # Проверяем состояние клиента
                is_connected = False
                is_authorized = False
                
                try:
                    is_connected = client.is_connected()
                    if is_connected:
                        is_authorized = await asyncio.wait_for(client.is_user_authorized(), timeout=5.0)
                except Exception:
                    is_connected = False
                    is_authorized = False
                
                # Если клиент не подключен или не авторизован, переподключаем
                if not is_connected or not is_authorized:
                    await ensure_client_connected(client, session_name, user_id)
                    
        except Exception as e:
            print(f"Ошибка при проверке клиента {session_name}: {e}")

# Глобальный экземпляр менеджера подключений
connection_manager = ConnectionManager()

# ----------------------
# Хранилище прогресса автоподписки (перезапуск-устойчивое)
# ----------------------

def get_autosub_state_path(user_id):
    try:
        license_type = user_states.get(f"{user_id}_license_type") or detect_license_type(user_id)
    except Exception:
        license_type = None
    try:
        user_dir = get_user_dir(user_id, license_type)
    except Exception:
        # Фолбэк в папку проекта
        user_dir = os.path.join(get_project_root(), "user")
    os.makedirs(user_dir, exist_ok=True)
    return os.path.join(user_dir, "autosubscribe_state.json")

def load_autosub_state(user_id):
    path = get_autosub_state_path(user_id)
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
                return data
    except Exception:
        pass
    return {}

def save_autosub_state(user_id, data):
    path = get_autosub_state_path(user_id)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# ---- Trial autosubscribe limit helpers ----
def get_autosub_trial_processed_total(user_id) -> int:
    """Возвращает суммарное количество обработанных элементов автоподписки по всем аккаунтам пользователя."""
    try:
        state = load_autosub_state(user_id)
        total = 0
        for phone_key, acc in state.items():
            if not isinstance(acc, dict):
                continue
            processed = acc.get("processed", [])
            if isinstance(processed, list):
                total += len(processed)
        return int(total)
    except Exception:
        return 0

def get_autosub_trial_remaining(user_id, limit: int = 10) -> int:
    try:
        used = get_autosub_trial_processed_total(user_id)
        return max(0, int(limit) - int(used))
    except Exception:
        return 0

def normalize_autosub_list(raw_list):
    # Повторяем логику нормализации как в autosubscribe_module
    normalized = []
    seen = set()
    for item in raw_list:
        if not item:
            continue
        text = item.strip()
        links = re.findall(r"https://t\.me/\S+", text)
        usernames = re.findall(r"@([a-zA-Z0-9_]{5,})", text)
        for link in links:
            if link not in seen:
                seen.add(link)
                normalized.append(link)
        for name in usernames:
            handle = f"@{name}"
            if f"https://t.me/{name}" in seen:
                continue
            if handle not in seen:
                seen.add(handle)
                normalized.append(handle)
    return normalized

def autosub_progress_remove_item(user_id, phone, text_line):
    try:
        # Извлекаем первый встреченный @handle или ссылку https://t.me/...
        link_match = re.search(r"https://t\.me/\S+", text_line)
        user_match = re.search(r"@([a-zA-Z0-9_]{5,})", text_line)
        key = None
        if link_match:
            key = link_match.group(0)
        elif user_match:
            key = f"@{user_match.group(1)}"
        if not key:
            return
        state = load_autosub_state(user_id)
        acc = state.get(str(phone)) or {}
        remaining = acc.get("remaining", [])
        processed = acc.get("processed", [])
        if key in remaining:
            remaining.remove(key)
            processed.append(key)
            acc["remaining"] = remaining
            acc["processed"] = processed
            state[str(phone)] = acc
            save_autosub_state(user_id, state)
    except Exception:
        pass

def autosub_progress_clear_account(user_id, phone):
    try:
        state = load_autosub_state(user_id)
        phone_key = str(phone)
        if phone_key in state:
            del state[phone_key]
            save_autosub_state(user_id, state)
    except Exception:
        pass

# Функции для сохранения и восстановления состояний
def clean_state_for_serialization(state_data):
    """
    Очищает состояние от несериализуемых объектов (Event, TelegramClient, etc.)
    """
    if not isinstance(state_data, dict):
        return state_data
    
    cleaned_state = {}
    for key, value in state_data.items():
        try:
            if isinstance(value, dict):
                cleaned_state[key] = clean_state_for_serialization(value)
            elif isinstance(value, list):
                cleaned_state[key] = [
                    clean_state_for_serialization(item) if isinstance(item, dict) else item 
                    for item in value
                ]
            elif hasattr(value, '__class__') and 'Event' in str(type(value)):
                # Пропускаем объекты Event
                continue
            elif hasattr(value, '__class__') and 'TelegramClient' in str(type(value)):
                # Пропускаем объекты TelegramClient
                continue
            elif hasattr(value, '__class__') and 'asyncio.Task' in str(type(value)):
                # Пропускаем объекты Task
                continue
            elif hasattr(value, '__class__') and 'threading.Event' in str(type(value)):
                # Пропускаем объекты threading.Event
                continue
            elif hasattr(value, '__class__') and 'coroutine' in str(type(value)):
                # Пропускаем корутины
                continue
            elif hasattr(value, '__class__') and 'function' in str(type(value)):
                # Пропускаем функции
                continue
            else:
                # Проверяем, можно ли сериализовать объект
                try:
                    json.dumps(value)
                    cleaned_state[key] = value
                except (TypeError, ValueError):
                    # Если объект не сериализуется, пропускаем его
                    continue
        except Exception as e:
            # Если произошла ошибка при обработке значения, пропускаем его
            print(f"⚠️ Пропущено значение {key} из-за ошибки: {e}")
            continue
    
    return cleaned_state

def update_service_state(service_type, user_id, state_data):
    """
    Безопасно обновляет состояние конкретного сервиса для пользователя
    в индивидуальном файле reconnect_state.json
    
    Args:
        service_type: "mailing_states", "autoresponder_states", "postman_states", или "active_tasks_info"
        user_id: ID пользователя
        state_data: Данные состояния для обновления (None для удаления)
    """
    try:
        # Загружаем существующее состояние пользователя
        existing_state = load_user_reconnect_state_individual(user_id) or {
            "mailing_states": {},
            "autoresponder_states": {},
            "postman_states": {},
            "autosubscribe_states": {},
            "user_sessions": {},
            "active_tasks_info": {}
        }
        
        # Убеждаемся, что нужная секция существует
        if service_type not in existing_state:
            existing_state[service_type] = {}
        
        user_id_str = str(user_id)
        
        if state_data is None:
            # Удаляем состояние
            existing_state[service_type].pop(user_id_str, None)
            print(f"🗑️ Удалено состояние {service_type} для пользователя {user_id}")
        else:
            # Очищаем состояние от несериализуемых объектов
            cleaned_state_data = clean_state_for_serialization(state_data)
            
            # Обновляем состояние
            existing_state[service_type][user_id_str] = cleaned_state_data
            print(f"✏️ Обновлено состояние {service_type} для пользователя {user_id}")
        
        # Сохраняем обновленное состояние в индивидуальный файл пользователя
        save_user_reconnect_state_individual(user_id, existing_state)
            
    except Exception as e:
        print(f"❌ Ошибка обновления состояния {service_type} для пользователя {user_id}: {e}")


def save_reconnect_state():
    """Сохраняет информацию об активных сессиях для восстановления после перезапуска"""
    try:
        # Собираем всех пользователей, у которых есть активные состояния
        users_with_states = set()
        
        # Добавляем пользователей с активными состояниями рассылки
        for user_id in mailing_states.keys():
            users_with_states.add(user_id)
        
        # Добавляем пользователей с активными состояниями автоответчика
        for user_id in autoresponder_states.keys():
            users_with_states.add(user_id)
        
        # Добавляем пользователей с активными состояниями почты
        for user_id in postman_states.keys():
            users_with_states.add(user_id)
        
        # Добавляем пользователей с активными сессиями
        for user_id in user_sessions.keys():
            users_with_states.add(user_id)
        
        # Сохраняем состояние для каждого пользователя в его индивидуальный файл
        for user_id in users_with_states:
            try:
                # Создаем структуру данных для пользователя
                user_state_data = {
                    "mailing_states": {},
                    "autoresponder_states": {},
                    "postman_states": {},
                    "autosubscribe_states": {},
                    "user_sessions": {},
                    "active_tasks_info": {}
                }
                
                # Добавляем состояние рассылки (только если оно действительно активно или есть выбранные аккаунты)
                if user_id in mailing_states:
                    cleaned_mailing_state = clean_state_for_serialization(mailing_states[user_id])
                    ms_active = bool(cleaned_mailing_state.get("active", False))
                    ms_selected = cleaned_mailing_state.get("selected_accounts", []) or []
                    if ms_active or len(ms_selected) > 0:
                        user_state_data["mailing_states"][str(user_id)] = {
                            "selected_accounts": ms_selected,
                            "active": ms_active,
                            "minimized": cleaned_mailing_state.get("minimized", False),
                            "logging_enabled": cleaned_mailing_state.get("logging_enabled", True)
                        }
                
                # Добавляем состояние автоответчика
                if user_id in autoresponder_states:
                    auto_state = autoresponder_states[user_id]
                    if auto_state.get("active", False):
                        cleaned_auto_state = clean_state_for_serialization(auto_state)
                        user_state_data["autoresponder_states"][str(user_id)] = {
                            "selected_accounts": cleaned_auto_state.get("selected_accounts", []),
                            "active": cleaned_auto_state.get("active", False),
                            "minimized": cleaned_auto_state.get("minimized", False)
                        }
                
                # Добавляем состояние почты
                if user_id in postman_states:
                    post_state = postman_states[user_id]
                    if post_state.get("active", False):
                        cleaned_post_state = clean_state_for_serialization(post_state)
                        user_state_data["postman_states"][str(user_id)] = {
                            "selected_accounts": cleaned_post_state.get("selected_accounts", []),
                            "selected_postman": cleaned_post_state.get("selected_postman"),
                            "notify_username": cleaned_post_state.get("notify_username"),
                            "active": cleaned_post_state.get("active", False),
                            "minimized": cleaned_post_state.get("minimized", False)
                        }
                
                # Добавляем состояние автоподписки (по phone per-user)
                try:
                    # Если есть запущенные задачи autosubscribe:{phone} или сохранённый remaining
                    autosub_states = {}
                    accounts = load_user_accounts(user_id)
                    for acc in (accounts or []):
                        phone = acc.get("phone")
                        if not phone:
                            continue
                        task_key = f"autosubscribe:{phone}"
                        is_running = user_id in active_tasks and task_key in active_tasks[user_id] and not active_tasks[user_id][task_key].done()
                        has_remaining = bool(load_autosub_state(user_id).get(str(phone), {}).get("remaining"))
                        if is_running or has_remaining:
                            autosub_states[phone] = {
                                "active": True,
                                "phone": phone,
                                "minimized": bool(user_states.get(f"{user_id}_autosub_minimized_{phone}"))
                            }
                    if autosub_states:
                        user_state_data["autosubscribe_states"][str(user_id)] = autosub_states
                except Exception:
                    pass

                # Добавляем user_sessions (с фильтрацией autosubscribe, если он не активен и нечего возобновлять)
                if user_id in user_sessions:
                    try:
                        session_copy = dict(user_sessions[user_id])
                    except Exception:
                        session_copy = user_sessions[user_id]
                    # Удаляем раздел autosubscribe из user_sessions, если нет активных задач и remaining пустой для всех аккаунтов
                    try:
                        has_running_autosub = (
                            user_id in active_tasks and any(
                                (not task.done() and not task.cancelled()) and name.startswith("autosubscribe:")
                                for name, task in active_tasks[user_id].items()
                            )
                        )
                        has_remaining_autosub = False
                        try:
                            accounts = load_user_accounts(user_id)
                        except Exception:
                            accounts = []
                        for acc in (accounts or []):
                            ph = acc.get("phone")
                            if not ph:
                                continue
                            try:
                                if load_autosub_state(user_id).get(str(ph), {}).get("remaining"):
                                    has_remaining_autosub = True
                                    break
                            except Exception:
                                continue
                        if not has_running_autosub and not has_remaining_autosub:
                            if isinstance(session_copy, dict) and "autosubscribe" in session_copy:
                                session_copy.pop("autosubscribe", None)
                    except Exception:
                        pass
                    cleaned_user_session = clean_state_for_serialization(session_copy)
                    if cleaned_user_session:
                        user_state_data["user_sessions"][str(user_id)] = cleaned_user_session
                
                # Добавляем информацию об активных задачах
                if user_id in active_tasks:
                    active_task_names = []
                    for task_name, task in active_tasks[user_id].items():
                        if not task.done() and not task.cancelled():
                            active_task_names.append(task_name)
                    if active_task_names:
                        user_state_data["active_tasks_info"][str(user_id)] = active_task_names
                
                # Сохраняем в индивидуальный файл пользователя
                save_user_reconnect_state_individual(user_id, user_state_data)
                    
            except Exception as e:
                print(f"Ошибка сохранения reconnect_state.json для пользователя {user_id}: {e}")
          
    except Exception as e:
        print(f"❌ Ошибка сохранения состояния: {e}")

async def stop_all_auto_resume_tasks():
    """Останавливает все задачи автовосстановления"""
    print("🔄 Остановка всех задач автовосстановления...")
    
    for user_id, tasks in auto_resume_tasks.items():
        for service_type, task in tasks.items():
            if not task.done():
                print(f"🛑 Останавливаем задачу {service_type} для пользователя {user_id}")
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    print(f"⚠️ Ошибка при остановке задачи {service_type} для пользователя {user_id}: {e}")
    
    # Очищаем словарь задач
    auto_resume_tasks.clear()
    print("✅ Все задачи автовосстановления остановлены")

def load_reconnect_state():
    """Загружает и восстанавливает состояния сессий после перезапуска"""
    try:
        # Мигрируем папки пользователей без суффикса в папки с правильным суффиксом
        #print("🔄 Проверка и миграция папок пользователей...")
        root = get_project_root()
        user_base_dir = os.path.join(root, "user")
        
        if os.path.exists(user_base_dir):
            for item in os.listdir(user_base_dir):
                # Проверяем папки без суффикса (только цифры)
                if item.isdigit():
                    user_id = int(item)
                    migrate_user_folder_if_needed(user_id)
        
        # Очищаем пустые папки после миграции
        cleanup_orphaned_folders()
        
        # Инициализируем пустую структуру данных
        state_data = {
            "mailing_states": {},
            "autoresponder_states": {},
            "postman_states": {},
            "user_sessions": {},
            "active_tasks_info": {}
        }
        
        # Загружаем из индивидуальных файлов пользователей
        if os.path.exists(user_base_dir):
            for item in os.listdir(user_base_dir):
                if item.endswith(("_trial", "_pro", "_premium", "_basic", "_admin", "_owner")):
                    user_id = int(item.split("_")[0])
                    user_reconnect_data = load_user_reconnect_state_individual(user_id)
                    if user_reconnect_data:
                        # Объединяем данные из индивидуального файла
                        for key in ["mailing_states", "autoresponder_states", "postman_states", "autosubscribe_states", "user_sessions", "active_tasks_info"]:
                            if key in user_reconnect_data and user_id not in state_data.get(key, {}):
                                if key not in state_data:
                                    state_data[key] = {}
                                state_data[key][str(user_id)] = user_reconnect_data[key].get(str(user_id), {})
        
        # Восстанавливаем состояния автоподписки (и авто-резюм при active=true)
        restored_autosub = 0
        for user_id_str, autosub_state in state_data.get("autosubscribe_states", {}).items():
            user_id = int(user_id_str)
            if not isinstance(autosub_state, dict):
                continue
            for phone, info in autosub_state.items():
                try:
                    if info.get("active"):
                        remaining = load_autosub_state(user_id).get(str(phone), {}).get("remaining", [])
                        if remaining:
                            user_states[f"{user_id}_autosub_phone"] = phone
                            minimized_at_resume = bool(info.get("minimized", False))
                            if minimized_at_resume:
                                user_states[f"{user_id}_autosub_minimized_{phone}"] = True
                            async def resume_autosub(user_id=user_id, phone=phone):
                                try:
                                    config = load_config(user_id)
                                    api_id = config.get("api_id")
                                    api_hash = config.get("api_hash")
                                    accounts = load_user_accounts(user_id)
                                    account = next((a for a in accounts if a.get("phone") == phone), None)
                                    if not account or not api_id or not api_hash:
                                        return
                                    session_name = account.get("name") or account.get("phone")
                                    license_type = user_states.get(f"{user_id}_license_type") or detect_license_type(user_id)
                                    client = await get_or_create_client(user_id, session_name, api_id, api_hash, license_type)
                                    if not client:
                                        return
                                    rem = load_autosub_state(user_id).get(str(phone), {}).get("remaining", [])
                                    if not rem:
                                        return
                                    async def reporter_stub(text: str):
                                        # Префикс аккаунта
                                        acc_label = None
                                        try:
                                            for acc in accounts:
                                                if acc.get("phone") == phone:
                                                    acc_label = acc.get("username") or acc.get("name") or acc.get("phone")
                                                    break
                                        except Exception:
                                            pass
                                        # Сначала обновляем состояния перерывов/FloodWait и прогресса
                                        try:
                                            if text.startswith("Перерыв ") and text.endswith(" минут"):
                                                minutes_str = text.replace("Перерыв ", "").replace(" минут", "").strip()
                                                total_minutes = int(minutes_str)
                                                user_states[f"{user_id}_autosub_break_{phone}_started_ts"] = int(asyncio.get_event_loop().time())
                                                user_states[f"{user_id}_autosub_break_{phone}_total_sec"] = total_minutes * 60
                                            elif text.startswith("До истечения перерыва осталось ") and text.endswith(" минут"):
                                                minutes_left = int(text.replace("До истечения перерыва осталось ", "").replace(" минут", "").strip())
                                                user_states[f"{user_id}_autosub_break_{phone}_started_ts"] = int(asyncio.get_event_loop().time())
                                                user_states[f"{user_id}_autosub_break_{phone}_total_sec"] = minutes_left * 60
                                            elif text.startswith("Telegram API ограничение: требуется подождать ") and text.endswith(" секунд."):
                                                seconds_str = text.replace("Telegram API ограничение: требуется подождать ", "").replace(" секунд.", "").strip()
                                                total_seconds = int(seconds_str)
                                                user_states[f"{user_id}_autosub_flood_{phone}_started_ts"] = int(asyncio.get_event_loop().time())
                                                user_states[f"{user_id}_autosub_flood_{phone}_total_sec"] = total_seconds
                                            else:
                                                m_ok = re.match(r"^Успешно подписались на (.+)$", text.strip())
                                                if m_ok:
                                                    autosub_progress_remove_item(user_id, phone, m_ok.group(1))
                                                if text.strip() == "Весь список был успешно обработан. Автоподписка завершена." or "Автоподписка завершена." in text:
                                                    user_states[f"{user_id}_autosub_last_done_{phone}"] = True
                                        except Exception:
                                            pass

                                        # Если автоподписка свернута — не логируем в чат, но фиксируем финалку для показа при разворачивании
                                        try:
                                            if user_states.get(f"{user_id}_autosub_minimized_{phone}"):
                                                if text.strip() == "Весь список был успешно обработан. Автоподписка завершена." or "Автоподписка завершена." in text:
                                                    user_states[f"{user_id}_autosub_done_{phone}"] = True
                                                    if acc_label:
                                                        user_states[f"{user_id}_autosub_done_label_{phone}"] = acc_label
                                                    user_states[f"{user_id}_autosub_done_pending"] = {
                                                        "phone": phone,
                                                        "label": acc_label
                                                    }
                                                return
                                        except Exception:
                                            pass

                                        # Повторная страховочная проверка свернутости перед отправкой в чат
                                        try:
                                            if user_states.get(f"{user_id}_autosub_minimized_{phone}"):
                                                return
                                        except Exception:
                                            pass

                                        # Отправка лога напрямую пользователю (если не свернуто)
                                        try:
                                            prefixed = f"{acc_label}: {text}" if acc_label else text
                                            # Если только что был явный разворот — прикрепим клавиатуру
                                            if user_states.pop(f"{user_id}_autosub_unminimized_{phone}", None) or user_states.pop(f"{user_id}_autosub_attach_keyboard_{phone}", None):
                                                await bot.send_message(chat_id=user_id, text=prefixed, reply_markup=get_autosub_active_keyboard())
                                            else:
                                                await bot.send_message(chat_id=user_id, text=prefixed)
                                        except Exception:
                                            pass
                                    async def run_resume():
                                        try:
                                            # Лицензионный guard при авто-возобновлении автоподписки
                                            if not is_license_valid(user_id):
                                                try:
                                                    await handle_access_expired(user_id)
                                                except Exception:
                                                    pass
                                                return
                                            # Guard-функция для периодической проверки доступа во время резюма
                                            async def _license_guard_resume() -> bool:
                                                try:
                                                    return bool(is_license_valid(user_id))
                                                except Exception:
                                                    return True

                                            await subscribe_to_chats_list(client, rem, reporter_stub, _license_guard_resume)
                                        except asyncio.CancelledError:
                                            return
                                        except Exception:
                                            pass
                                    await start_task(user_id, f"autosubscribe:{phone}", run_resume())
                                except asyncio.CancelledError:
                                    return
                                except Exception:
                                    pass
                            # Сохраняем задачу автоподписки в реестр авто-возобновления,
                            # чтобы корректно её отменять при завершении приложения
                            resume_task = asyncio.create_task(resume_autosub())
                            if user_id not in auto_resume_tasks:
                                auto_resume_tasks[user_id] = {}
                            auto_resume_tasks[user_id][f"autosubscribe:{phone}"] = resume_task
                            restored_autosub += 1
                except Exception:
                    pass
        if restored_autosub:
            print(f"🔄 Автоматически возобновлено автоподписок: {restored_autosub}")

        #print("🔄 Восстановление состояний после перезапуска из индивидуальных файлов пользователей...")
        
        # Восстанавливаем состояния рассылки
        restored_mailing = 0
        for user_id_str, mailing_state in state_data.get("mailing_states", {}).items():
            user_id = int(user_id_str)
            mailing_states[user_id] = mailing_state
            # Восстанавливаем флаг активности из сохраненного состояния
            is_active = mailing_state.get("active", False)
            is_minimized = mailing_state.get("minimized", False)
            mailing_states[user_id]["active"] = is_active
            mailing_states[user_id]["minimized"] = is_minimized
            
            # НЕ запускаем автовосстановление для неактивных состояний
            # Только сохраняем состояние в памяти
            if is_active and not is_minimized:
                # Добавляем флаг восстановления
                mailing_states[user_id]["_restored"] = True
                
                # Запускаем мониторинг для пользователя
                monitoring_task = asyncio.create_task(connection_manager.start_monitoring(user_id))
                
                # Автоматически возобновляем рассылку
                mailing_task = asyncio.create_task(auto_resume_mailing(user_id))
                
                # Сохраняем задачи для корректного завершения
                if user_id not in auto_resume_tasks:
                    auto_resume_tasks[user_id] = {}
                auto_resume_tasks[user_id]["monitoring"] = monitoring_task
                auto_resume_tasks[user_id]["mailing"] = mailing_task
                
                restored_mailing += 1
            elif is_active and is_minimized:
                # Для свернутых рассылок восстанавливаем состояние и запускаем мониторинг
                print(f"📋 Восстановлено состояние свернутой рассылки для пользователя {user_id}")
                
                # Запускаем мониторинг для пользователя (но не рассылку)
                monitoring_task = asyncio.create_task(connection_manager.start_monitoring(user_id))
                
                # Сохраняем задачу мониторинга для корректного завершения
                if user_id not in auto_resume_tasks:
                    auto_resume_tasks[user_id] = {}
                auto_resume_tasks[user_id]["monitoring"] = monitoring_task
                
                # Восстанавливаем user_sessions для корректного отображения UI
                if user_id not in user_sessions:
                    user_sessions[user_id] = {}
                if "pushmux" not in user_sessions[user_id]:
                    user_sessions[user_id]["pushmux"] = {}
                user_sessions[user_id]["pushmux"]["minimized"] = True
                
                # Автоматически возобновляем рассылку в фоновом режиме
                mailing_task = asyncio.create_task(auto_resume_mailing(user_id))
                auto_resume_tasks[user_id]["mailing"] = mailing_task
        
        # Восстанавливаем состояния автоответчика
        restored_autoresponder = 0
        for user_id_str, auto_state in state_data.get("autoresponder_states", {}).items():
            user_id = int(user_id_str)
            autoresponder_states[user_id] = auto_state
            # Восстанавливаем флаг активности из сохраненного состояния
            is_active = auto_state.get("active", False)
            is_minimized = auto_state.get("minimized", False)
            autoresponder_states[user_id]["active"] = is_active
            autoresponder_states[user_id]["minimized"] = is_minimized
            
            if is_active and not is_minimized:
                # Добавляем флаг восстановления
                autoresponder_states[user_id]["_restored"] = True
                
                # Запускаем мониторинг для пользователя
                monitoring_task = asyncio.create_task(connection_manager.start_monitoring(user_id))
                
                # Автоматически возобновляем автоответчик
                autoresponder_task = asyncio.create_task(auto_resume_autoresponder(user_id))
                
                # Сохраняем задачи для корректного завершения
                if user_id not in auto_resume_tasks:
                    auto_resume_tasks[user_id] = {}
                if "monitoring" not in auto_resume_tasks[user_id]:
                    auto_resume_tasks[user_id]["monitoring"] = monitoring_task
                auto_resume_tasks[user_id]["autoresponder"] = autoresponder_task
                
                restored_autoresponder += 1
            elif is_active and is_minimized:
                # Для свернутых автоответчиков запускаем только мониторинг
                print(f"📋 Восстановлено состояние свернутого автоответчика для пользователя {user_id}")
                
                # Запускаем мониторинг для пользователя (но не автоответчик)
                monitoring_task = asyncio.create_task(connection_manager.start_monitoring(user_id))
                
                # Сохраняем задачу мониторинга для корректного завершения
                if user_id not in auto_resume_tasks:
                    auto_resume_tasks[user_id] = {}
                auto_resume_tasks[user_id]["monitoring"] = monitoring_task
        
        # Восстанавливаем состояния почты
        restored_mailboxer = 0
        for user_id_str, post_state in state_data.get("postman_states", {}).items():
            user_id = int(user_id_str)
            postman_states[user_id] = post_state
            # Восстанавливаем флаг активности из сохраненного состояния
            is_active = post_state.get("active", False)
            is_minimized = post_state.get("minimized", False)
            postman_states[user_id]["active"] = is_active
            postman_states[user_id]["minimized"] = is_minimized
            
            if is_active and not is_minimized:
                # Добавляем флаг восстановления
                postman_states[user_id]["_restored"] = True
                
                # Запускаем мониторинг для пользователя
                monitoring_task = asyncio.create_task(connection_manager.start_monitoring(user_id))
                
                # Автоматически возобновляем почту
                mailboxer_task = asyncio.create_task(auto_resume_mailboxer(user_id))
                
                # Сохраняем задачи для корректного завершения
                if user_id not in auto_resume_tasks:
                    auto_resume_tasks[user_id] = {}
                if "monitoring" not in auto_resume_tasks[user_id]:
                    auto_resume_tasks[user_id]["monitoring"] = monitoring_task
                auto_resume_tasks[user_id]["mailboxer"] = mailboxer_task
                
                restored_mailboxer += 1
            elif is_active and is_minimized:
                # Для свернутой почты запускаем только мониторинг
                print(f"📋 Восстановлено состояние свернутой почты для пользователя {user_id}")
                
                # Запускаем мониторинг для пользователя (но не почту)
                monitoring_task = asyncio.create_task(connection_manager.start_monitoring(user_id))
                
                # Сохраняем задачу мониторинга для корректного завершения
                if user_id not in auto_resume_tasks:
                    auto_resume_tasks[user_id] = {}
                auto_resume_tasks[user_id]["monitoring"] = monitoring_task
        
        # Восстанавливаем user_sessions для корректного отображения UI
        restored_user_sessions = 0
        for user_id_str, user_session in state_data.get("user_sessions", {}).items():
            user_id = int(user_id_str)
            user_sessions[user_id] = user_session
            restored_user_sessions += 1
        
        if restored_mailing or restored_autoresponder or restored_mailboxer:
            print(f"✅ Восстановлено: рассылка ({restored_mailing}), автоответчик ({restored_autoresponder}), почта ({restored_mailboxer})")
        
        # НЕ удаляем файл состояния после восстановления - он нужен для отслеживания
        # os.remove(state_file)
        
        # Теперь загружаем из индивидуальных файлов пользователей
        #print("🔄 Загрузка состояний из индивидуальных файлов пользователей...")
        restored_from_individual = 0
        
        root = get_project_root()
        user_base_dir = os.path.join(root, "user")
        
        if os.path.exists(user_base_dir):
            for item in os.listdir(user_base_dir):
                if item.endswith(("_trial", "_pro", "_premium", "_basic", "_admin", "_owner")):
                    user_id = int(item.split("_")[0])
                    user_reconnect_file = os.path.join(user_base_dir, item, "reconnect_state.json")
                    
                    if os.path.exists(user_reconnect_file):
                        try:
                            with open(user_reconnect_file, "r", encoding="utf-8") as f:
                                user_state_data = json.load(f)
                            
                            # Восстанавливаем состояния для конкретного пользователя
                            if user_id_str := str(user_id):
                                # Восстанавливаем состояния рассылки
                                if user_state_data.get("mailing_states", {}).get(user_id_str, {}).get("active", False):
                                    mailing_states[user_id] = user_state_data["mailing_states"][user_id_str]
                                    restored_from_individual += 1
                                
                                # Восстанавливаем состояния автоответчика
                                if user_state_data.get("autoresponder_states", {}).get(user_id_str, {}).get("active", False):
                                    autoresponder_states[user_id] = user_state_data["autoresponder_states"][user_id_str]
                                    restored_from_individual += 1
                                
                                # Восстанавливаем состояния почты
                                if user_state_data.get("postman_states", {}).get(user_id_str, {}).get("active", False):
                                    postman_states[user_id] = user_state_data["postman_states"][user_id_str]
                                    restored_from_individual += 1
                                
                                # Восстанавливаем user_sessions
                                if user_state_data.get("user_sessions", {}).get(user_id_str):
                                    user_sessions[user_id] = user_state_data["user_sessions"][user_id_str]
                                
                        except Exception as e:
                            print(f"Ошибка загрузки {user_reconnect_file}: {e}")
        
        #if restored_from_individual > 0:
            #print(f"✅ Восстановлено {restored_from_individual} состояний из индивидуальных файлов пользователей")
        
        # Восстанавливаем типы лицензий из freetrial.json
        try:
            freetrial_data = load_freetrial()
            restored_licenses = 0
            for user_id_str in freetrial_data:
                if is_freetrial_valid(int(user_id_str)):
                    user_id = int(user_id_str)
                    user_states[f"{user_id}_license_type"] = "trial"
                    restored_licenses += 1
            if restored_licenses > 0:
                print(f"✅ Восстановлено {restored_licenses} типов лицензий из freetrial.json")
        except Exception as e:
            print(f"❌ Ошибка восстановления типов лицензий: {e}")
        
    except Exception as e:
        print(f"❌ Ошибка восстановления состояния: {e}")
async def auto_resume_mailing(user_id):
    """Автоматически возобновляет рассылку после перезапуска"""
    try:
        await asyncio.sleep(0.5)  # минимальная задержка для инициализации
        
        if user_id not in mailing_states or not mailing_states[user_id].get("active"):
            return
        
        state = mailing_states[user_id]
        
        # Получаем выбранные аккаунты в начале функции
        selected_accounts = state.get("selected_accounts", [])
        
        if not selected_accounts:
            return
        
        # Проверяем, была ли рассылка свернута
        is_minimized = state.get("minimized", False)
        if is_minimized:
            print(f"📱 Рассылка для пользователя {user_id} была свернута - проверяем состояние перерывов")
            
            # Проверяем, есть ли активные перерывы
            resume_state = load_resume_state(user_id=user_id)
            if resume_state and resume_state.get("accounts"):
                now = int(time.time())
                accounts_on_break = [
                    acc for acc in resume_state["accounts"] 
                    if acc.get("break_until_timestamp") and acc["break_until_timestamp"] > now
                ]
                
                if accounts_on_break:
                    print(f"🔄 Найдены активные перерывы для {len(accounts_on_break)} аккаунтов - не запускаем рассылку")
                    # Запускаем только таймеры перерывов, не рассылку
                    break_tasks = []
                    for account in accounts_on_break:
                        # Мигрируем username если его нет
                        config = load_config(user_id)
                        config_accounts = config.get("accounts", []) if config else []
                        account = migrate_account_username(account, config_accounts)
                        
                        display_name = get_display_name(account)
                        break_seconds_left = account['break_seconds_left']
                        break_started_ts = account.get('break_started_ts')
                        
                        print(f"🕐 Запуск таймера для {display_name}: {break_seconds_left} секунд")
                        
                        # Создаем задачу для countdown_timer
                        task_name = f"break_timer_{account.get('phone', display_name)}"
                        task_coro = countdown_timer(
                            break_seconds_left, 
                            display_name, 
                            {},  # timers dict
                            selected_account=account,
                            user_id=user_id,
                            break_started_ts=break_started_ts
                        )
                        task = asyncio.create_task(task_coro)
                        
                        # Регистрируем задачу в системе управления для возможности отмены
                        if user_id not in active_tasks:
                            active_tasks[user_id] = {}
                        active_tasks[user_id][task_name] = task
                        
                        break_tasks.append(task)
                    
                    # Ждем завершения всех таймеров
                    if break_tasks:
                        try:
                            await asyncio.gather(*break_tasks, return_exceptions=True)
                        except Exception as e:
                            print(f"Ошибка в таймерах перерывов: {e}")
                    
                    print(f"✅ Перерывы завершены, завершаем работу")
                    return
                else:
                    print(f"🔄 Нет активных перерывов - запускаем рассылку")
                    # Для свернутых рассылок запускаем без логирования в Telegram
                    # Получаем конфигурацию пользователя
                    config = load_config(user_id)
                    if config and "api_id" in config and "api_hash" in config:
                        # Передаем список телефонов, а не аккаунтов
                        await execute_mailing(user_id, state, selected_accounts, config["api_id"], config["api_hash"])
                    else:
                        print(f"❌ Не удалось загрузить конфигурацию для пользователя {user_id}")
                    # НЕ возвращаемся здесь - продолжаем выполнение для восстановления логирования
        
        #if not is_minimized:
        #    await log_to_telegram(user_id, "🔄 Автоматическое возобновление рассылки после перезапуска...", "mailing")
        
        # Получаем лицензию пользователя
        license_type = detect_license_type(user_id)
        
        # Проверяем, есть ли частично завершенная рассылка
        # Ищем в resume_process.json для определения прогресса
        resume_file = get_user_dir(user_id, license_type) + "/resume_process.json"
        print(f"📁 Проверяем файл: {resume_file}")
        if os.path.exists(resume_file):
            try:
                with open(resume_file, 'r', encoding='utf-8') as f:
                    resume_data = json.load(f)
                
                print(f"📋 Загружен resume_process.json: {resume_data}")
                
                # Проверяем, есть ли аккаунты с прогрессом
                total_progress = 0
                total_messages = 0
                if "accounts" in resume_data:
                    for account_data in resume_data["accounts"]:
                        if isinstance(account_data, dict) and "message_count" in account_data:
                            total_progress += account_data["message_count"]
                            total_messages += 30  # Максимум 30 сообщений на аккаунт
                            print(f"📊 Аккаунт {account_data.get('phone', 'неизвестно')}: {account_data['message_count']}/30")
                
                print(f"📊 Общий прогресс: {total_progress}/{total_messages}")
                
                if total_progress > 0:
                    # Проверяем, есть ли аккаунты на перерыве
                    accounts_on_break = []
                    accounts_completed = []
                    accounts_at_limit = []
                    
                    for account_data in resume_data["accounts"]:
                        if isinstance(account_data, dict):
                            phone = account_data.get('phone', 'неизвестно')
                            nickname = account_data.get('nickname', phone)
                            message_count = account_data.get('message_count', 0)
                            break_seconds_left = account_data.get('break_seconds_left', 0)
                            
                            if message_count >= 30 and break_seconds_left > 0:
                                # Аккаунт завершил рассылку и находится на перерыве
                                accounts_on_break.append({
                                    'phone': phone,
                                    'nickname': nickname,
                                    'break_seconds_left': break_seconds_left
                                })
                            elif message_count >= 30 and break_seconds_left <= 0:
                                # Аккаунт достиг лимита, но перерыв уже закончился
                                accounts_at_limit.append({
                                    'phone': phone,
                                    'nickname': nickname,
                                    'message_count': message_count
                                })
                            elif message_count < 30:
                                # Аккаунт не завершил рассылку
                                accounts_completed.append(account_data)
                    
                    # Показываем статус всех аккаунтов
                    status_message = "📊 Статус аккаунтов после перезапуска:\n"
                    for account_data in resume_data["accounts"]:
                        if isinstance(account_data, dict):
                            phone = account_data.get('phone', 'неизвестно')
                            nickname = account_data.get('nickname', phone)
                            message_count = account_data.get('message_count', 0)
                            break_seconds_left = account_data.get('break_seconds_left', 0)
                            
                            if message_count >= 30 and break_seconds_left > 0:
                                hours = break_seconds_left // 3600
                                minutes = (break_seconds_left % 3600) // 60
                                seconds = break_seconds_left % 60
                                status_message += f"📊 Аккаунт {phone}: {message_count}/30 (перерыв {hours:02d}:{minutes:02d}:{seconds:02d}) 🟡\n"
                            elif message_count >= 30:
                                status_message += f"📊 Аккаунт {phone}: {message_count}/30 (лимит достигнут) 🔴\n"
                            else:
                                status_message += f"📊 Аккаунт {phone}: {message_count}/30 (активен) 🟢\n"
                    
                    print(status_message.strip())
                    # Убираем отправку статуса в чат при разворачивании рассылки
                    # if not is_minimized:
                    #     await log_to_telegram(user_id, status_message.strip(), "mailing")
                    
                    if accounts_on_break and not accounts_completed and not accounts_at_limit:
                        # Все аккаунты на перерыве - запускаем индивидуальные таймеры
                        print(f"🔄 Все аккаунты находятся на перерыве, запускаем индивидуальные таймеры...")
                        
                        # Запускаем countdown_timer для каждого аккаунта на перерыве
                        break_tasks = []
                        for account in accounts_on_break:
                            # Мигрируем username если его нет
                            config = load_config(user_id)
                            config_accounts = config.get("accounts", []) if config else []
                            account = migrate_account_username(account, config_accounts)
                            
                            display_name = get_display_name(account)
                            break_seconds_left = account['break_seconds_left']
                            break_started_ts = account.get('break_started_ts')
                            
                            print(f"🕐 Запуск таймера для {display_name}: {break_seconds_left} секунд")
                            
                            # Создаем задачу для countdown_timer
                            task_name = f"break_timer_{account.get('phone', display_name)}"
                            task_coro = countdown_timer(
                                break_seconds_left, 
                                display_name, 
                                {},  # timers dict
                                selected_account=account,
                                user_id=user_id,
                                break_started_ts=break_started_ts
                            )
                            task = asyncio.create_task(task_coro)
                            
                            # Регистрируем задачу в системе управления для возможности отмены
                            if user_id not in active_tasks:
                                active_tasks[user_id] = {}
                            active_tasks[user_id][task_name] = task
                            
                            break_tasks.append(task)
                        
                        # Ждем завершения всех таймеров
                        if break_tasks:
                            try:
                                await asyncio.gather(*break_tasks, return_exceptions=True)
                            except Exception as e:
                                print(f"Ошибка в таймерах перерывов: {e}")
                        
                        # После окончания перерыва завершаем - не запускаем новую рассылку
                        
                    
                    elif accounts_at_limit and not accounts_completed and not accounts_on_break:
                        # Все аккаунты достигли лимита и перерыв уже закончился
                        print(f"🔄 Все аккаунты достигли лимита, сбрасываем счетчики и запускаем рассылку...")
                        if not is_minimized:
                            await log_to_telegram(user_id, f"🔄 Все аккаунты достигли лимита, сбрасываем счетчики и запускаем рассылку...", "mailing")
                        
                        # Сбрасываем счетчики сообщений для всех аккаунтов
                        for account_data in resume_data["accounts"]:
                            if isinstance(account_data, dict):
                                account_data["message_count"] = 0
                                account_data["break_seconds_left"] = 0
                                account_data["break_until_timestamp"] = 0
                        
                        # Сохраняем обновленное состояние
                        save_resume_state(resume_data, user_id=user_id)
                        
                        # Запускаем обычную рассылку
                        await start_task(user_id, "mailing", async_mailing_flow(user_id, license_type))
                        return
                    
                    elif total_progress < total_messages:
                        # Есть частично завершенная рассылка
                        print(f"🔄 Найден прогресс рассылки: {total_progress}/{total_messages}")
                        #if not is_minimized:
                        #    await log_to_telegram(user_id, f"🔄 Найден прогресс рассылки: {total_progress}/{total_messages}", "mailing")
                    
                    # Если есть аккаунты на перерыве, показываем их статус
                    if accounts_on_break:
                        break_status_message = "📊 Статус перерывов:\n"
                        for account in accounts_on_break:
                            # Мигрируем username если его нет
                            config = load_config(user_id)
                            config_accounts = config.get("accounts", []) if config else []
                            account = migrate_account_username(account, config_accounts)
                            
                            # Используем break_until_timestamp для точного расчета времени
                            break_until_timestamp = account.get('break_until_timestamp', 0)
                            
                            if break_until_timestamp > 0:
                                remaining_seconds = int(break_until_timestamp - time.time())
                                if remaining_seconds > 0:
                                    hours = remaining_seconds // 3600
                                    minutes = (remaining_seconds % 3600) // 60
                                    seconds = remaining_seconds % 60
                                    display_name = get_display_name(account)
                                    break_status_message += f"{display_name}: до конца перерыва осталось {hours:02d}:{minutes:02d}:{seconds:02d} 🟡\n"
                                else:
                                    # Fallback на break_seconds_left если время истекло
                                    hours = account['break_seconds_left'] // 3600
                                    minutes = (account['break_seconds_left'] % 3600) // 60
                                    seconds = account['break_seconds_left'] % 60
                                    display_name = get_display_name(account)
                                    break_status_message += f"{display_name}: до конца перерыва осталось {hours:02d}:{minutes:02d}:{seconds:02d} 🟡\n"
                            else:
                                # Fallback на break_seconds_left если timestamp недоступен
                                hours = account['break_seconds_left'] // 3600
                                minutes = (account['break_seconds_left'] % 3600) // 60
                                seconds = account['break_seconds_left'] % 60
                                display_name = get_display_name(account)
                                break_status_message += f"{display_name}: до конца перерыва осталось {hours:02d}:{minutes:02d}:{seconds:02d} 🟡\n"
                        
                        # Отправку статуса перерывов в чат отключили по запросу пользователя.
                    
                    # Получаем полные объекты аккаунтов
                    all_accounts = load_user_accounts(user_id)
                    print(f"🔍 Все аккаунты пользователя {user_id}: {[acc.get('phone') for acc in all_accounts]}")
                    print(f"🔍 Выбранные аккаунты: {selected_accounts}")
                    
                    selected_accounts_objects = [acc for acc in all_accounts if acc.get("phone") in selected_accounts]
                    print(f"🔍 Найдено объектов аккаунтов: {len(selected_accounts_objects)}")
                    
                    if not selected_accounts_objects:
                        print(f"❌ Не удалось найти объекты аккаунтов для {selected_accounts}")
                        if not is_minimized:
                            await log_to_telegram(user_id, f"❌ Не удалось найти объекты аккаунтов", "mailing")
                        # Запускаем обычную рассылку как fallback
                        await start_task(user_id, "mailing", async_mailing_flow(user_id, license_type))
                        return
                    
                    # Получаем API данные из config.json
                    config_path = get_user_dir(user_id, license_type) + "/config.json"
                    if not os.path.exists(config_path):
                        print(f"❌ Файл config.json не найден: {config_path}")
                        if not is_minimized:
                            await log_to_telegram(user_id, f"❌ Файл config.json не найден", "mailing")
                        await start_task(user_id, "mailing", async_mailing_flow(user_id, license_type))
                        return
                    
                    try:
                        with open(config_path, 'r', encoding='utf-8') as f:
                            config_data = json.load(f)
                        api_id = config_data.get("api_id")
                        api_hash = config_data.get("api_hash")
                        print(f"✅ API данные загружены: api_id={api_id}, api_hash={api_hash[:10]}...")
                    except Exception as e:
                        print(f"❌ Ошибка чтения config.json: {e}")
                        if not is_minimized:
                            await log_to_telegram(user_id, f"❌ Ошибка чтения config.json", "mailing")
                        await start_task(user_id, "mailing", async_mailing_flow(user_id, license_type))
                        return
                    
                    if not api_id or not api_hash:
                        print(f"❌ Не удалось получить API данные из config.json")
                        if not is_minimized:
                            await log_to_telegram(user_id, f"❌ Не удалось получить API данные", "mailing")
                        # Запускаем обычную рассылку как fallback
                        await start_task(user_id, "mailing", async_mailing_flow(user_id, license_type))
                        return
                    
                    #if not is_minimized:
                    #    await log_to_telegram(user_id, f"✅ API данные загружены, создаем клиенты для всех аккаунтов...", "mailing")
                    
                    # Загружаем параметры рассылки для правильного возобновления
                    print(f"📋 Загружаем параметры рассылки для пользователя {user_id}")
                    mailing_params = load_mailing_parameters(user_id)
                    if not mailing_params:
                        print(f"❌ Не удалось загрузить параметры рассылки для пользователя {user_id}")
                        if not is_minimized:
                            await log_to_telegram(user_id, f"❌ Не удалось загрузить параметры рассылки", "mailing")
                        # Запускаем обычную рассылку как fallback
                        await start_task(user_id, "mailing", async_mailing_flow(user_id, license_type))
                        return

                    # Получаем необходимые параметры
                    template_list = mailing_params.get("templates", [])
                    template_index = mailing_params.get("template_index", 0)
                    selected_folder = mailing_params.get("selected_folder")
                    timers = mailing_params.get("timers", {})

                    # Если параметры пустые, пытаемся получить их из resume_process.json и config.json
                    if not template_list or len(template_list) == 0:
                        print(f"📋 Список шаблонов пуст в mailing_parameters.json, загружаем из config.json")
                        # Загружаем шаблоны из config.json для первого аккаунта
                        if selected_accounts_objects:
                            first_account = selected_accounts_objects[0]
                            template_list = get_templates_from_config(config_data, first_account.get('phone'))
                            print(f"✅ Загружено {len(template_list)} шаблонов из config.json для аккаунта {first_account.get('phone')}")
                        else:
                            print(f"❌ Нет аккаунтов для загрузки шаблонов")
                            if not is_minimized:
                                await log_to_telegram(user_id, f"❌ Не удалось загрузить шаблоны", "mailing")
                            # Запускаем обычную рассылку как fallback
                            await start_task(user_id, "mailing", async_mailing_flow(user_id, license_type))
                            return
                    
                    if not selected_folder:
                        print(f"📋 Папка не выбрана в mailing_parameters.json, загружаем из resume_process.json")
                        # Берем папку из первого аккаунта в resume_process.json
                        if "accounts" in resume_data and len(resume_data["accounts"]) > 0:
                            first_account = resume_data["accounts"][0]
                            if "folder" in first_account and first_account["folder"]:
                                selected_folder = first_account["folder"]
                                print(f"✅ Загружена папка из resume_process.json: {selected_folder}")
                            else:
                                print(f"❌ Папка не найдена в resume_process.json")
                                if not is_minimized:
                                    await log_to_telegram(user_id, f"❌ Папка не выбрана, запускаем обычную рассылку", "mailing")
                                await start_task(user_id, "mailing", async_mailing_flow(user_id, license_type))
                                return
                        else:
                            print(f"❌ Аккаунты не найдены в resume_process.json")
                            if not is_minimized:
                                await log_to_telegram(user_id, f"❌ Папка не выбрана, запускаем обычную рассылку", "mailing")
                            await start_task(user_id, "mailing", async_mailing_flow(user_id, license_type))
                            return
                    
                    # Если template_index не задан, берем из первого аккаунта в resume_process.json
                    if template_index is None:
                        print(f"📋 template_index не задан в mailing_parameters.json, загружаем из resume_process.json")
                        if "accounts" in resume_data and len(resume_data["accounts"]) > 0:
                            first_account = resume_data["accounts"][0]
                            if "template_index" in first_account:
                                template_index = first_account["template_index"]
                                print(f"✅ Загружен template_index из resume_process.json: {template_index}")
                            else:
                                template_index = 0
                                print(f"✅ Установлен template_index по умолчанию: 0")
                        else:
                            template_index = 0
                            print(f"✅ Установлен template_index по умолчанию: 0")
                    
                    if template_index >= len(template_list):
                        template_index = 0  # Сбрасываем на начало

                    print(f"📋 Параметры загружены: шаблонов={len(template_list)}, индекс={template_index}, папка={selected_folder}")
                    print(f"📋 Шаблоны: {template_list}")
                    print(f"📋 Папка: {selected_folder}")
                    #if not is_minimized:
                    #    await log_to_telegram(user_id, f"📋 Параметры загружены, запускаем возобновление...", "mailing")
                    
                    # Инициализируем состояние рассылки для возобновления
                    if user_id not in mailing_states:
                        mailing_states[user_id] = {}
                    
                    # Проверяем, была ли рассылка свернута
                    minimized = mailing_params.get("minimized", False)
                    
                    mailing_states[user_id].update({
                        "step": "running",
                        "selected_accounts": selected_accounts,
                        "template_mode": "resume",
                        "template_index": template_index,
                        "selected_folder": selected_folder,
                        "logging_enabled": not minimized,  # Логирование отключено, если рассылка свернута
                        "minimized": minimized,  # Сохраняем флаг свернутости
                        "alternate_templates": True,
                        "ignore_breaks": False,  # Сбрасываем флаг игнорирования перерывов для обычного запуска
                        "resume_state": resume_data
                    })
                    
                    # Обновляем user_sessions для корректного отображения кнопок
                    if user_id not in user_sessions:
                        user_sessions[user_id] = {}
                    if "pushmux" not in user_sessions[user_id]:
                        user_sessions[user_id]["pushmux"] = {}
                    user_sessions[user_id]["pushmux"]["minimized"] = minimized
                    user_sessions[user_id]["pushmux"]["active"] = True
                    
                    print(f"🔧 DEBUG: Обновлен user_sessions для пользователя {user_id}: minimized={minimized}, active=True")
                    print(f"🔧 DEBUG: user_sessions[{user_id}] = {user_sessions[user_id]}")
                    
                    # Сохраняем состояние активных сессий для восстановления после перезапуска
                    save_reconnect_state()
                    
                    print(f"🔧 DEBUG: Состояние сохранено в reconnect_state.json")
                    
                    # Запускаем возобновление для всех аккаунтов
                    #print(f"🚀 Запускаем возобновление для {len(selected_accounts_objects)} аккаунтов")
                    #if not is_minimized:
                    #    await log_to_telegram(user_id, f"🚀 Запускаем возобновление для {len(selected_accounts_objects)} аккаунтов", "mailing")
                    
                    # Создаем задачи для всех аккаунтов
                    tasks = []
                    for account in selected_accounts_objects:
                        try:
                            print(f"🔌 Создаем клиент для аккаунта {account.get('phone')} ({account.get('name')})")
                            
                            # Создаем клиент для каждого аккаунта
                            client = await get_or_create_client(user_id, account.get('name'), api_id, api_hash, license_type)
                            if not client:
                                print(f"❌ Не удалось создать клиент для аккаунта {account.get('phone')}")
                                if not is_minimized:
                                    await log_to_telegram(user_id, f"❌ Не удалось создать клиент для аккаунта {account.get('phone')}", "mailing")
                                continue
                            
                            print(f"✅ Клиент успешно создан для аккаунта {account.get('phone')}")
                            
                            # Получаем шаблоны для этого аккаунта
                            account_templates = get_templates_from_config(config_data, account.get('phone'))
                            if not account_templates:
                                print(f"❌ Нет шаблонов для аккаунта {account.get('phone')}")
                                continue
                            
                            # Получаем состояние аккаунта из resume_process.json
                            account_state = next((a for a in resume_data["accounts"] if a["phone"] == account.get("phone")), None)
                            if not account_state:
                                print(f"❌ Не найдено состояние для аккаунта {account.get('phone')}")
                                continue
                            
                            # Получаем параметры для этого аккаунта
                            account_template_index = account_state.get("template_index", 0)
                            account_folder = account_state.get("folder")
                            account_message_count = account_state.get("message_count", 0)
                            account_chat_index = account_state.get("chat_index", 0)
                            
                            print(f"📋 Аккаунт {account.get('phone')}: шаблонов={len(account_templates)}, индекс={account_template_index}, папка={account_folder}, сообщений={account_message_count}, чат_индекс={account_chat_index}")
                            
                            # Проверяем, достиг ли аккаунт лимита сообщений
                            if account_message_count >= 30:
                                print(f"⚠️ Аккаунт {account.get('phone')} достиг лимита сообщений ({account_message_count}/30), пропускаем")
                                continue
                            
                            # Проверяем, находится ли аккаунт на перерыве
                            account_break_seconds_left = account_state.get("break_seconds_left", 0)
                            account_break_until_timestamp = account_state.get("break_until_timestamp", 0)
                            now = int(time.time())
                            
                            if account_break_until_timestamp and account_break_until_timestamp > now:
                                print(f"⚠️ Аккаунт {account.get('phone')} находится на перерыве до {account_break_until_timestamp}, пропускаем")
                                continue
                            
                            # Создаем задачу для этого аккаунта
                            task = await start_task(
                                user_id,
                                f"mailing_{account.get('phone')}",
                                main_flow_resume(
                                    account,  # Аккаунт
                                    client,  # Клиент
                                    account_templates,  # Шаблоны для этого аккаунта
                                    account_template_index,  # Индекс шаблона для этого аккаунта
                                    account_folder,  # Папка для этого аккаунта
                                    timers,  # Таймеры
                                    account_chat_index,  # start_index - продолжаем с индекса чата
                                    0,  # break_breaks
                                    not mailing_params.get("minimized", False),  # logging_enabled - отключаем логирование если свернуто
                                    True,  # alternate_templates_enabled
                                    user_id,
                                    False,  # ignore_breaks
                                    mailing_params.get("minimized", False)  # minimized - передаем флаг свернутости
                                )
                            )
                            tasks.append(task)
                            print(f"✅ Задача создана для аккаунта {account.get('phone')}")
                            
                        except Exception as e:
                            print(f"❌ Ошибка при создании задачи для аккаунта {account.get('phone')}: {e}")
                            if not is_minimized:
                                await log_to_telegram(user_id, f"❌ Ошибка при создании задачи для аккаунта {account.get('phone')}: {e}", "mailing")
                            continue
                    
                    if not tasks:
                        print(f"❌ Не удалось создать задачи для возобновления")
                        # Отправку сообщения в чат отключили по запросу пользователя.
                        await start_task(user_id, "mailing", async_mailing_flow(user_id, license_type))
                        return
                    
                    #print(f"✅ Создано {len(tasks)} задач для возобновления рассылки")
                    #if not is_minimized:
                    #    await log_to_telegram(user_id, f"✅ Создано {len(tasks)} задач для возобновления рассылки", "mailing")
                    
                    # Ждем завершения всех задач
                    await asyncio.gather(*tasks, return_exceptions=True)
                    return
                    
            except Exception as e:
                print(f"❌ Ошибка при чтении resume_process.json: {e}")
                if not is_minimized:
                    await log_to_telegram(user_id, f"❌ Ошибка чтения прогресса рассылки: {e}", "mailing")
        
        # Если нет частично завершенной рассылки или произошла ошибка
        print("🔄 Нет частично завершенной рассылки, запускаем обычную рассылку")
        if not is_minimized:
            await log_to_telegram(user_id, "🔄 Нет частично завершенной рассылки, запускаем обычную рассылку", "mailing")
        # Вместо прямого вызова запускаем через start_task для корректной регистрации
        await start_task(user_id, "mailing", async_mailing_flow(user_id, license_type))
        return
        
    except Exception as e:
        print(f"❌ Ошибка автовосстановления рассылки для пользователя {user_id}: {e}")

async def auto_resume_autoresponder(user_id):
    """Автоматически возобновляет автоответчик после перезапуска"""
    try:
        await asyncio.sleep(0.5)  # минимальная задержка для инициализации
        
        if user_id not in autoresponder_states or not autoresponder_states[user_id].get("active"):
            return
        
        state = autoresponder_states[user_id]
        
        # Проверяем, был ли автоответчик свернут
        if state.get("minimized", False):
            print(f"📱 Автоответчик для пользователя {user_id} был свернут - автовосстановление не требуется")
            return
        
        selected_accounts = state.get("selected_accounts", [])
        
        # Если selected_accounts пустые, но автоответчик активен - пытаемся восстановить
        if not selected_accounts:
            print(f"⚠️ Восстановление автоответчика: selected_accounts пустые для пользователя {user_id}, пытаемся восстановить...")
            
            # Пытаемся восстановить selected_accounts из других источников
            # Сначала проверяем postman_states - там могут быть те же аккаунты
            if user_id in postman_states:
                postman_selected = postman_states[user_id].get("selected_accounts", [])
                if postman_selected:
                    print(f"🔄 Восстанавливаем selected_accounts из postman_states: {postman_selected}")
                    selected_accounts = postman_selected
                    # Обновляем состояние в памяти
                    autoresponder_states[user_id]["selected_accounts"] = selected_accounts
                    # Обновляем состояние в файле
                    update_service_state("autoresponder_states", user_id, autoresponder_states[user_id])
            
            # Если все еще пустые, пытаемся загрузить из конфигурации пользователя
            if not selected_accounts:
                try:
                    all_accounts = load_user_accounts(user_id)
                    if all_accounts:
                        # Берем все активные аккаунты
                        all_phones = [acc.get("phone") for acc in all_accounts if acc.get("phone")]
                        if all_phones:
                            print(f"🔄 Восстанавливаем selected_accounts из всех аккаунтов пользователя: {all_phones}")
                            selected_accounts = all_phones
                            # Обновляем состояние в памяти
                            autoresponder_states[user_id]["selected_accounts"] = selected_accounts
                            # Обновляем состояние в файле
                            update_service_state("autoresponder_states", user_id, autoresponder_states[user_id])
                except Exception as e:
                    print(f"❌ Ошибка при восстановлении аккаунтов из конфигурации: {e}")
        
        # Если все еще нет аккаунтов, деактивируем автоответчик
        if not selected_accounts:
            print(f"❌ Не удалось восстановить selected_accounts для пользователя {user_id}, деактивируем автоответчик")
            autoresponder_states[user_id]["active"] = False
            update_service_state("autoresponder_states", user_id, autoresponder_states[user_id])
            return
        
        #await log_to_telegram(user_id, "🔄 Автоматическое возобновление автоответчика после перезапуска...", "autoresponder")
        
        # Обновляем статистику для автовосстановления автоответчика
        # Учитываем, что автоответчик может уже иметь отправленные сообщения
        stats = load_user_stats(user_id)
        if stats.get("autoresponder_messages", 0) > 0:
            print(f"📊 Автоответчик уже имеет {stats['autoresponder_messages']} отправленных сообщений")
        
        # Запускаем автоответчик
        await run_autoresponder(user_id, selected_accounts)
        
    except Exception as e:
        print(f"❌ Ошибка автовосстановления автоответчика для пользователя {user_id}: {e}")

async def auto_resume_mailboxer(user_id):
    """Автоматически возобновляет почту после перезапуска"""
    try:
        await asyncio.sleep(0.3)  # минимальная задержка для инициализации
        
        if user_id not in postman_states or not postman_states[user_id].get("active"):
            return
        
        state = postman_states[user_id]
        
        # Проверяем, была ли почта свернута
        if state.get("minimized", False):
            print(f"📱 Почта для пользователя {user_id} была свернута - автовосстановление не требуется")
            return
        
        selected_accounts = state.get("selected_accounts", [])
        selected_postman = state.get("selected_postman")
        notify_username = state.get("notify_username")
        
        if not selected_accounts or not selected_postman:
            return
        
        #await log_to_telegram(user_id, "🔄 Автоматическое возобновление почты после перезапуска...", "mailboxer")
        
        # Получаем лицензию пользователя
        license_type = detect_license_type(user_id)
        
        # Получаем полные объекты аккаунтов
        all_accounts = load_user_accounts(user_id)
        print(f"🔍 Все аккаунты пользователя {user_id}: {[acc.get('phone') for acc in all_accounts]}")
        print(f"🔍 Выбранные аккаунты: {selected_accounts}")
        
        selected_accounts_objects = [acc for acc in all_accounts if acc.get("phone") in selected_accounts]
        print(f"🔍 Найдено объектов аккаунтов: {len(selected_accounts_objects)}")
        
        postman_account = next((acc for acc in all_accounts if acc.get("phone") == selected_postman), None)
        
        if not postman_account:
            await log_to_telegram(user_id, f"❌ Аккаунт-почтальон {selected_postman} не найден", "mailboxer")
            print(f"❌ Аккаунт-почтальон {selected_postman} не найден в списке аккаунтов")
            return
        
        print(f"✅ Аккаунт-почтальон найден: {postman_account.get('name')} ({postman_account.get('phone')})")
        
        # Обновляем статистику для автовосстановления почты
        # Учитываем, что почта может уже иметь полученные сообщения
        stats = load_user_stats(user_id)
        if stats.get("received_messages", 0) > 0:
            print(f"📊 Почта уже имеет {stats['received_messages']} полученных сообщений")
        
        # Запускаем почту
        await run_mailboxer(user_id, license_type, selected_accounts_objects, postman_account, None, notify_username)
        
    except Exception as e:
        print(f"❌ Ошибка автовосстановления почты для пользователя {user_id}: {e}")

# Функция для автоматического сохранения состояний
async def auto_save_states():
    """Периодически сохраняет состояния активных сессий"""
    while True:
        try:
            await asyncio.sleep(1)  # Сохраняем каждую секунду вместо 30 секунд
            
            # Проверяем корректность состояний перед сохранением
            for user_id in list(autoresponder_states.keys()):
                state = autoresponder_states[user_id]
                if state.get("active") and not state.get("selected_accounts"):
                    print(f"⚠️ Автосохранение: исправляем некорректное состояние автоответчика для пользователя {user_id}")
                    # Если автоответчик активен, но selected_accounts пустые - деактивируем
                    state["active"] = False
                    # Пытаемся восстановить selected_accounts из postman_states
                    if user_id in postman_states and postman_states[user_id].get("selected_accounts"):
                        state["selected_accounts"] = postman_states[user_id]["selected_accounts"]
                        print(f"✅ Восстановлены selected_accounts из postman_states: {state['selected_accounts']}")
            
            save_reconnect_state()
        except Exception as e:
            print(f"❌ Ошибка автосохранения состояний: {e}")
            await asyncio.sleep(5)  # При ошибке ждем 5 секунд вместо 60












# Инициализация aiogram бота
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Глобальные переменные состояния (инициализация)
user_sessions = {}
user_states = {}  # user_id -> state ("wait_license", "authorized")
user_languages = {}  # user_id -> "ru" or "en"
authorized_users = set()
licenses = {}
mailing_selected_accounts = {}
last_bot_message_id = {}  # user_id -> message_id
blacklisted_titles = ["FRESH", "TEST", "TEST1", "TEST2", "SEARCH", "SHORT", "HAND/SEARCH", "🔵", "BAN-WORD", "HAND", "ESCROW", "BAN WORD"]

# Простая система переподключения
reconnection_delay = 5  # секунды между попытками

# Новые глобальные переменные для асинхронной архитектуры (управление клиентами и задачами
active_tasks = {}  # {user_id: {task_name: asyncio.Task}}
active_clients = {}  # {user_id: {session_name: TelegramClient}}
task_status = {}  # {user_id: {task_name: "running"|"stopped"|"minimized"}}
log_queue = asyncio.Queue()  # Очередь для логов
mailing_states = {}  # Состояния рассылки для каждого пользователя
postman_states = {}  # Состояния почты для каждого пользователя
autoresponder_states = {}  # Состояния автоответчика для каждого пользователя
autoresponder_last_response = {}  # Антиспам: user_id -> {account_phone -> {chat_id: timestamp}}

# Новые переменные для централизованного управления клиентами
client_handlers = {}  # {user_id: {session_name: {handler_name: handler_func}}}
client_event_handlers = {}  # {user_id: {session_name: [handler_info]}}
client_lock = asyncio.Lock()  # Блокировка для безопасного доступа к клиентам

# Задачи автовосстановления
auto_resume_tasks = {}  # {user_id: {service_type: asyncio.Task}}

# Состояния FSM для aiogram
class UserStates(StatesGroup):
    waiting_language = State()
    waiting_license = State()
    authorized = State()
    waiting_account_selection = State()
    waiting_template_selection = State()
    waiting_folder_selection = State()
    waiting_postman_selection = State()
    waiting_group_id = State()
    waiting_notify_username = State()
    waiting_ignore_folders_choice = State()
    waiting_ignore_folders_selection = State()
    waiting_ignore_chats_choice = State()
    waiting_ignore_chats_folder_selection = State()
    waiting_ignore_chats_selection = State()

# Функции для управления асинхронными клиентами и задачами
async def get_or_create_client(user_id, session_name, api_id, api_hash, license_type=None):
    """Получает или создает TelegramClient для сессии с централизованным управлением"""
    async with client_lock:
        if user_id not in active_clients:
            active_clients[user_id] = {}
        
        if session_name not in active_clients[user_id]:
            # Определяем тип лицензии, если не передан
            if license_type is None:
                license_type = detect_license_type(user_id)
            
            session_path = get_session_path(user_id, "bot", session_name, license_type)
            
            # Проверяем, существует ли файл сессии
            if not os.path.exists(session_path):
                await log_to_telegram(user_id, f"Файл сессии не найден: {session_name}", "client_manager")
                return None
            
            client = TelegramClient(session_path, api_id, api_hash)
            
            try:
                await client.connect()
                if not await client.is_user_authorized():
                    await client.disconnect()
                    await log_to_telegram(user_id, f"Клиент не авторизован: {session_name}", "client_manager")
                    return None
                
                # Инициализируем структуры для этого клиента
                if user_id not in client_handlers:
                    client_handlers[user_id] = {}
                if user_id not in client_event_handlers:
                    client_event_handlers[user_id] = {}
                
                client_handlers[user_id][session_name] = {}
                client_event_handlers[user_id][session_name] = []
                
                active_clients[user_id][session_name] = client
                
                # Автоматически запускаем мониторинг подключений для пользователя
                await connection_manager.start_monitoring(user_id)
                            
            except Exception as e:
                await log_to_telegram(user_id, f"Ошибка создания клиента для {session_name}: {e}", "client_manager")
                return None
        
        return active_clients[user_id][session_name]

async def add_event_handler(user_id, session_name, event_type, handler_func):
    """Добавляет обработчик событий к клиенту"""
    async with client_lock:
        if user_id not in active_clients or session_name not in active_clients[user_id]:
            return False
        
        client = active_clients[user_id][session_name]
        
        try:
            # Добавляем обработчик к клиенту
            client.add_event_handler(handler_func, event_type)
            
            # Сохраняем ссылку на обработчик
            if user_id not in client_event_handlers:
                client_event_handlers[user_id] = {}
            if session_name not in client_event_handlers[user_id]:
                client_event_handlers[user_id][session_name] = []
            
            client_event_handlers[user_id][session_name].append({
                'event_type': event_type,
                'handler': handler_func
            })
            
            #await log_to_telegram(user_id, f"Добавлен обработчик событий для {session_name}", "client_manager")
            return True
            
        except Exception as e:
            await log_to_telegram(user_id, f"Ошибка добавления обработчика для {session_name}: {e}", "client_manager")
            return False

async def remove_event_handlers(user_id, session_name):
    """Удаляет все обработчики событий для клиента"""
    async with client_lock:
        if user_id not in client_event_handlers or session_name not in client_event_handlers[user_id]:
            return
        
        if user_id not in active_clients or session_name not in active_clients[user_id]:
            return
        
        client = active_clients[user_id][session_name]
        
        try:
            # Удаляем все обработчики
            for handler_info in client_event_handlers[user_id][session_name]:
                client.remove_event_handler(handler_info['handler'], handler_info['event_type'])
            
            client_event_handlers[user_id][session_name].clear()
            #await log_to_telegram(user_id, f"Удалены обработчики событий для {session_name}", "client_manager")
            
        except Exception as e:
            await log_to_telegram(user_id, f"Ошибка удаления обработчиков для {session_name}: {e}", "client_manager")

async def disconnect_client(user_id, session_name):
    """Безопасно отключает клиента"""
    async with client_lock:
        if user_id not in active_clients or session_name not in active_clients[user_id]:
            return
        
        try:
            # Удаляем обработчики событий
            await remove_event_handlers(user_id, session_name)
            
            # Отключаем клиента
            client = active_clients[user_id][session_name]
            
            # Проверяем, подключен ли клиент
            if client.is_connected():
                await client.disconnect()
            
            # Удаляем из активных клиентов
            del active_clients[user_id][session_name]
            
            # Очищаем структуры
            if user_id in client_handlers and session_name in client_handlers[user_id]:
                del client_handlers[user_id][session_name]
            if user_id in client_event_handlers and session_name in client_event_handlers[user_id]:
                del client_event_handlers[user_id][session_name]
            
            print(f"✅ Клиент {session_name} отключен")
            
        except Exception as e:
            print(f"❌ Ошибка отключения клиента {session_name}: {e}")

async def disconnect_all_clients(user_id):
    """Отключает все клиенты пользователя"""
    async with client_lock:
        if user_id not in active_clients:
            return
        
        session_names = list(active_clients[user_id].keys())
        for session_name in session_names:
            await disconnect_client(user_id, session_name)

async def stop_all_mailing_tasks(user_id):
    """Быстро останавливает все задачи рассылки для пользователя"""
    if user_id not in active_tasks:
        return
    
    mailing_tasks = [task_name for task_name in active_tasks[user_id].keys() if task_name.startswith("mailing_")]
    if not mailing_tasks:
        return
    
    # Отменяем все задачи одновременно
    tasks_to_cancel = []
    for task_name in mailing_tasks:
        task = active_tasks[user_id][task_name]
        tasks_to_cancel.append(task)
        del active_tasks[user_id][task_name]
        if task_name in task_status.get(user_id, {}):
            task_status[user_id][task_name] = "stopped"
    
    # Отменяем все задачи параллельно
    for task in tasks_to_cancel:
        task.cancel()

async def stop_task(user_id, task_name):
    """Останавливает задачу"""
    if user_id in active_tasks and task_name in active_tasks[user_id]:
        task = active_tasks[user_id][task_name]
        task.cancel()
        # Не ждем завершения задачи - просто отменяем и удаляем
        del active_tasks[user_id][task_name]
        if task_name in task_status.get(user_id, {}):
            task_status[user_id][task_name] = "stopped"

async def start_task(user_id, task_name, coro):
    """Запускает асинхронную задачу"""
    if user_id not in active_tasks:
        active_tasks[user_id] = {}
    if user_id not in task_status:
        task_status[user_id] = {}
    
    # Останавливаем предыдущую задачу с тем же именем
    if task_name in active_tasks[user_id]:
        await stop_task(user_id, task_name)
    
    # Создаем новую задачу
    task = asyncio.create_task(coro)
    active_tasks[user_id][task_name] = task
    task_status[user_id][task_name] = "running"
    
    return task

async def telegram_logger():
    """Централизованный логгер для отправки сообщений в Telegram"""
    while True:
        try:
            log_entry = await log_queue.get()
            if log_entry is None:  # Сигнал остановки
                break
            
            user_id, message, task_name = log_entry
            
            # Отправляем сообщение в Telegram
            try:
                await bot.send_message(chat_id=user_id, text=message)
            except Exception as e:
                print(f"Ошибка отправки лога в Telegram: {e}")
            
            log_queue.task_done()
            
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Ошибка в telegram_logger: {e}")
            
async def log_to_telegram(user_id, message, task_name="general"):
    """Добавляет сообщение в очередь логов"""
    # Проверяем, не свернута ли рассылка (только для task_name="mailing")
    # Другие типы сообщений (например, "bug_notification") отправляются независимо от флага свёрнутости
    if task_name == "mailing":
        # Проверяем состояние рассылки
        if user_id in mailing_states:
            state = mailing_states[user_id]
            if state.get("minimized", False):
                # Если рассылка свернута, не отправляем сообщения
                return
        
        # Проверяем состояние сессии
        if user_id in user_sessions:
            session = user_sessions[user_id].get("pushmux", {})
            if session.get("minimized", False):
                # Если рассылка свернута, не отправляем сообщения
                return
    
    await log_queue.put((user_id, message, task_name))

async def safe_message_answer(message: types.Message, text: str, reply_markup=None, max_retries: int = 5):
    """Безопасно отправляет сообщение пользователю с экспоненциальными ретраями при сетевых ошибках."""
    delay_seconds = 1.0
    for attempt in range(max_retries):
        try:
            return await message.answer(text, reply_markup=reply_markup)
        except (TelegramNetworkError, ConnectionError, asyncio.TimeoutError) as e:
            # Сетевые сбои: ждём и пробуем снова
            await asyncio.sleep(delay_seconds)
            delay_seconds = min(delay_seconds * 2, 11)
        except TelegramAPIError as e:
            # Непоправимая ошибка Telegram API — выходим
            raise
    # Если все попытки исчерпаны — последний вызов даст исключение наружу
    return await message.answer(text, reply_markup=reply_markup)

async def edit_text_or_safe_send(message: types.Message, text: str, reply_markup=None):
    """Пытается заменить содержимое текущего сообщения: сначала заголовок (caption) медиа, затем текст.
    Если редактирование невозможно — отправляет новое сообщение как запасной вариант."""
    # Сначала пробуем редактировать caption (актуально для фото/медиа)
    try:
        return await message.edit_caption(text, reply_markup=reply_markup)
    except TelegramAPIError as e_cap:
        cap_err = str(e_cap).lower()
        if "message is not modified" in cap_err:
            return message
        # Если не получилось редактировать caption — пробуем редактировать текст
        try:
            return await message.edit_text(text, reply_markup=reply_markup)
        except TelegramAPIError as e_txt:
            txt_err = str(e_txt).lower()
            if "message is not modified" in txt_err:
                return message
            # В крайних случаях — отправляем новое сообщение (например, если нельзя редактировать)
            return await safe_message_answer(message, text, reply_markup=reply_markup)

async def delete_and_send_image(message: types.Message, image_filenames, caption: str, reply_markup=None, user_id=None):
    """Удаляет предыдущее сообщение и отправляет изображение из папки img с подписью и клавиатурой.
    Если файл(ы) не найдены, отправляет текст с той же клавиатурой.
    image_filenames может быть строкой или списком строк (приоритет по порядку).
    user_id - ID пользователя для определения стиля изображений.
    """
    import asyncio
    from aiogram.exceptions import TelegramAPIError, TelegramNetworkError
    
    # Приводим к списку
    if isinstance(image_filenames, str):
        candidates = [image_filenames]
    else:
        candidates = list(image_filenames)

    # Пытаемся удалить предыдущее сообщение (если это медиа/текст — нам нужно новое)
    try:
        await message.delete()
    except Exception as e:
        print(f"⚠️ Не удалось удалить предыдущее сообщение: {e}")

    # Пытаемся отправить первое существующее изображение с учетом стиля пользователя
    for filename in candidates:
        # Получаем путь к изображению с учетом стиля
        image_path = get_image_path(filename, user_id)
        full_path = Path(__file__).parent / image_path
        
        if full_path.exists():
            try:
                # Добавляем уникальный параметр к изображению, чтобы избежать кэширования
                photo_file = FSInputFile(str(full_path))
                if user_id:
                    # Добавляем user_id и временную метку как уникальный параметр
                    timestamp = int(time.time())
                    photo_file.filename = f"{user_id}_{timestamp}_{os.path.basename(full_path)}"
                
                # Retry логика для отправки фото
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        sent_message = await bot.send_photo(
                            chat_id=message.chat.id,
                            photo=photo_file,
                            caption=caption,
                            reply_markup=reply_markup
                        )
                        print(f"✅ Изображение {filename} успешно отправлено")
                        return sent_message
                    except TelegramNetworkError as e:
                        print(f"🌐 Сетевая ошибка при отправке {filename} (попытка {attempt + 1}/{max_retries}): {e}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2 ** attempt)  # Экспоненциальная задержка
                        else:
                            print(f"❌ Не удалось отправить {filename} после {max_retries} попыток")
                            break
                    except TelegramAPIError as e:
                        print(f"🚫 Telegram API ошибка при отправке {filename}: {e}")
                        break
                    except Exception as e:
                        print(f"💥 Неожиданная ошибка при отправке {filename}: {e}")
                        break
            except Exception as e:
                print(f"❌ Ошибка при подготовке файла {filename}: {e}")
                continue

    # Фолбэк: если ни один файл не найден или не удалось отправить — отправляем текст
    try:
        sent_message = await safe_message_answer(message, caption, reply_markup=reply_markup)
        print(f"📝 Отправлено текстовое сообщение как фолбэк")
        return sent_message
    except Exception as e:
        print(f"💥 Критическая ошибка: не удалось отправить даже текстовое сообщение: {e}")
        return None

async def try_send_image(message: types.Message, image_filenames, caption: str, reply_markup=None, user_id=None):
    """Пытается отправить изображение без удаления предыдущего сообщения. Если файл не найден — тихо пропускает."""
    # Приводим к списку
    if isinstance(image_filenames, str):
        candidates = [image_filenames]
    else:
        candidates = list(image_filenames)

    for filename in candidates:
        # Получаем путь к изображению с учетом стиля
        image_path = get_image_path(filename, user_id)
        full_path = Path(__file__).parent / image_path
        
        if full_path.exists():
            try:
                await bot.send_photo(
                    chat_id=message.chat.id,
                    photo=FSInputFile(str(full_path)),
                    caption=caption,
                    reply_markup=reply_markup
                )
            except Exception:
                pass
            return

def get_mailing_active_keyboard():
    """Возвращает клавиатуру для активной рассылки"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Стоп ⭕️"), KeyboardButton(text="Свернуть ↪️")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def get_autosub_active_keyboard():
    """Возвращает клавиатуру для активной автоподписки"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Завершить"), KeyboardButton(text="Назад")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )


def truncate_preview(text: str, max_length: int = 40) -> str:
    """Возвращает укороченный текст шаблона для кнопки.
    Если текст длиннее max_length, обрезает и добавляет троеточие.
    Пустые/некорректные значения заменяет на '...'.
    """
    try:
        if not isinstance(text, str):
            return "..."
        text_stripped = text.strip()
        if not text_stripped:
            return "..."
        if len(text_stripped) <= max_length:
            return text_stripped
        return text_stripped[: max_length - 3] + "..."
    except Exception:
        return "..."

def get_mailing_minimized_keyboard():
    """Возвращает клавиатуру для свернутой рассылки"""
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.keyboard = [
        [KeyboardButton(text="Развернуть 📋"), KeyboardButton(text="Стоп ⭕️")]
    ]
    return markup

async def async_mailing_flow(user_id, license_type):
    """Асинхронная рассылка через Telegram интерфейс"""
    try:
        # Доп. проверка доступа на случай истечения во время работы меню
        if not is_license_valid(user_id):
            await handle_access_expired(user_id)
            return
        # Логируем запуск рассылки
        log_mailing_activity(user_id, "launch")
        
        # Проверяем, что состояние существует
        if user_id not in mailing_states:
            await log_to_telegram(user_id, "Ошибка: состояние рассылки не найдено.", "mailing")
            return
        
        state = mailing_states[user_id]
        
        # Получаем доступные аккаунты
        accounts = load_user_accounts(user_id)
        if not accounts:
            await log_to_telegram(user_id, "Нет авторизованных аккаунтов для рассылки.", "mailing")
            return
        
        # Загружаем конфигурацию
        user_dir = get_user_dir(user_id, license_type)
        config_path = os.path.join(user_dir, "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        api_id = config.get("api_id")
        api_hash = config.get("api_hash")
        
        if not api_id or not api_hash:
            await log_to_telegram(user_id, "Ошибка: не найден API_ID или API_HASH.", "mailing")
            return
        
        # Если состояние "running", запускаем рассылку
        if state["step"] == "running":
            # Устанавливаем флаг активности для сохранения состояния
            state["active"] = True
            await execute_mailing(user_id, state, accounts, api_id, api_hash)
            return
        
        # Для других состояний просто ждем обновления через callback
        await log_to_telegram(user_id, "Ожидание настройки рассылки...", "mailing")
        
        # Ждем, пока состояние не изменится на "running"
        while state["step"] != "running":
            if not is_license_valid(user_id):
                await handle_access_expired(user_id)
                return
            await asyncio.sleep(1)
            if user_id not in mailing_states:
                await log_to_telegram(user_id, "Рассылка отменена.", "mailing")
                return
        
        # Запускаем рассылку
        # Устанавливаем флаг активности для сохранения состояния
        state["active"] = True
        await execute_mailing(user_id, state, accounts, api_id, api_hash)
        
    except asyncio.CancelledError:
        #await log_to_telegram(user_id, "Рассылка остановлена.", "mailing")
        raise
    except Exception as e:
        await log_to_telegram(user_id, f"Ошибка в рассылке: {e}", "mailing")

async def execute_mailing(user_id, state, accounts, api_id, api_hash):
    """Выполняет основную логику рассылки с использованием централизованного управления клиентами"""
    try:
        # Ранний выход при истёкшей подписке/триале
        if not is_license_valid(user_id):
            await handle_access_expired(user_id)
            return
        selected_account_phones = state.get("selected_accounts", [])
        
        if not selected_account_phones:
            if not state.get("minimized", False):
                await log_to_telegram(user_id, "Нет выбранных аккаунтов для рассылки.", "mailing")
            return
        
        # Если accounts - это список телефонов, загружаем конфигурацию
        if accounts and isinstance(accounts[0], str):
            config = load_config(user_id)
            if not config or "accounts" not in config:
                if not state.get("minimized", False):
                    await log_to_telegram(user_id, "Не удалось загрузить конфигурацию аккаунтов.", "mailing")
                return
            # Фильтруем аккаунты по выбранным телефонам
            selected_accounts = [acc for acc in config["accounts"] if acc.get('phone') in selected_account_phones]
        else:
            # Фильтруем аккаунты по выбранным телефонам
            selected_accounts = [acc for acc in accounts if acc.get('phone') in selected_account_phones]
        
        if not selected_accounts:
            if not state.get("minimized", False):
                await log_to_telegram(user_id, "Выбранные аккаунты не найдены.", "mailing")
            return
        
        
        
        # Создаем задачи для параллельной рассылки
        mailing_tasks = []
        
        for account in selected_accounts:
            session_name = account.get('name') or account.get('phone')
            
            
            # Создаем задачу для рассылки с этого аккаунта
            task = asyncio.create_task(
                send_mailing_from_account(user_id, account, state, api_id, api_hash, selected_accounts)
            )
            mailing_tasks.append(task)
        
        # Ждем завершения всех задач рассылки
        try:
            await asyncio.gather(*mailing_tasks, return_exceptions=True)
        except Exception as e:
            # Логируем ошибки только если рассылка не свернута
            if not state.get("minimized", False):
                await log_to_telegram(user_id, f"Ошибка в процессе рассылки: {e}", "mailing")
        
        # Завершаем рассылку
        state["step"] = "completed"
        state["active"] = False  # Убираем флаг активности после завершения
        
        # Логируем только если рассылка не свернута
        if not state.get("minimized", False):
            await log_to_telegram(user_id, "Рассылка завершена.", "mailing")
        
    except asyncio.CancelledError:
        #await log_to_telegram(user_id, "Рассылка остановлена пользователем.", "mailing")
        raise
    except Exception as e:
        # Логируем ошибки только если рассылка не свернута
        if not state.get("minimized", False):
            await log_to_telegram(user_id, f"Ошибка выполнения рассылки: {e}", "mailing")

async def check_safety_guard_1(user_id, resume_state):
    """
    Первый предохранитель: решает, показывать ли меню действий перед возобновлением
    Возвращает True если нужно показать меню (есть, что возобновлять)
    """
    # Показываем меню, если есть валидное сохранённое состояние с аккаунтами
    return bool(resume_state and resume_state.get("accounts"))

async def show_safety_guard_1_menu(user_id, resume_state):
    """
    Показывает меню первого предохранителя с информацией о лимитах и перерывах
    """
    now = int(time.time())
    accounts = resume_state["accounts"]
    
    # Формируем списки лимитов и перерывов
    limits_list = [
        f"{acc['nickname']} - {acc.get('message_count', 0)}/30"
        for acc in accounts
        if (not acc.get("break_until_timestamp")) and acc.get("message_count", 0) < 30
    ]
    
    breaks_list = []
    for acc in accounts:
        if acc.get("break_until_timestamp") and acc["break_until_timestamp"] > now:
            remaining = acc['break_until_timestamp'] - now
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60
            seconds = remaining % 60
            breaks_list.append(f"{acc['nickname']} - {hours:02d}:{minutes:02d}:{seconds:02d}")
    
    # Формируем сообщение
    message_text = "🚧     🚧     🚧     🚧     🚧     🚧     🚧\n\n"
    
    if limits_list:
        message_text += "Лимиты:\n"
        for line in limits_list:
            message_text += f"• {line}\n"
        message_text += "\n"
    
    if breaks_list:
        message_text += "Перерывы:\n"
        for line in breaks_list:
            message_text += f"• {line}\n"
        message_text += "\n"
    
    message_text += "🚧     🚧     🚧     🚧     🚧     🚧     🚧"
    
    # Создаем inline клавиатуру
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ Ждать перерыв", callback_data="safety_guard_wait")],
        [InlineKeyboardButton(text="🚀 Принудительно продолжить", callback_data="safety_guard_force")],
        [InlineKeyboardButton(text="🔄 Сбросить все лимиты", callback_data="safety_guard_reset")],
        [InlineKeyboardButton(text="Вернуться 🔙", callback_data="mailing_summary_yes")]
    ])
    
    return message_text, markup

async def send_mailing_from_account(user_id, account, state, api_id, api_hash, selected_accounts=None):
    """Рассылка сообщений с одного аккаунта по всем папкам, используя логику CLI-версии"""
    session_name = account.get('name') or account.get('phone')
    try:
        if not is_license_valid(user_id):
            await handle_access_expired(user_id)
            return

        license_type = detect_license_type(user_id)
        client = await get_or_create_client(user_id, session_name, api_id, api_hash, license_type)
        if not client:
            await log_to_telegram(user_id, f"Не удалось подключиться к аккаунту {session_name}. Проверьте, что сессия существует и авторизована.", "mailing")
            return

        templates = get_templates_from_config(load_config(user_id), account.get('phone'))
        
        # Загружаем текущее состояние из resume_process.json
        resume_state = load_resume_state(user_id=user_id)
        account_phone = account.get('phone')
        
        # 🛡️ ПРИНУДИТЕЛЬНО ЗАГРУЖАЕМ ИЗ resume_process.json
        # При переподключении ВСЕГДА берем данные из файла, никаких исключений!
        resume_state = load_resume_state(user_id=user_id)
        message_count = 0  # Значение по умолчанию
        
        if resume_state and "accounts" in resume_state:
            acc_state = next((a for a in resume_state["accounts"] if a["phone"] == account_phone), None)
            if acc_state:
                template_index = acc_state.get("template_index", 0)
                selected_folder = acc_state.get("folder", {"id": 1, "title": "1"})
                start_index = acc_state.get("chat_index", 0)
                message_count = acc_state.get("message_count", 0)
                break_seconds_left = acc_state.get("break_seconds_left", 0)
                break_until_timestamp = acc_state.get("break_until_timestamp")
            else:
                # Если аккаунт не найден в resume_state, используем настройки
                template_index = 0
                selected_folder = {"id": 1, "title": "1"}
                start_index = 0
                message_count = 0
                break_seconds_left = 0
                break_until_timestamp = 0
        else:
            # Если resume_state не существует, используем настройки
            template_index = 0
            selected_folder = {"id": 1, "title": "1"}
            start_index = 0
            message_count = 0
            break_seconds_left = 0
            break_until_timestamp = 0

        # Определяем template_index в зависимости от режима, если не resume
        template_mode = state.get("template_mode")
        if template_mode is None:
            template_mode = "select"  # По умолчанию используем режим select
        if template_mode != "resume":
            if template_mode == "custom":
                # В режиме custom используем сохраненные шаблоны для каждого аккаунта
                account_templates = state.get("account_templates", {})
                template_choice = account_templates.get(account_phone)
                if isinstance(template_choice, str) and template_choice.startswith("IDX_"):
                    try:
                        template_index = int(template_choice.replace("IDX_", ""))
                    except Exception:
                        template_index = 0
                elif template_choice == "T1":
                    template_index = 0
                elif template_choice == "T2":
                    template_index = 1
                else:
                    template_index = 0
            elif template_mode == "select":
                # В режиме select используем чередование шаблонов
                if selected_accounts:
                    try:
                        account_index = selected_accounts.index(account)
                        template_type = state.get("template_type", "T1")
                        if template_type == "T1":
                            template_index = account_index % 2  # 0,1,0,1...
                        else:  # T2
                            template_index = (account_index + 1) % 2  # 1,0,1,0...
                    except ValueError:
                        template_index = 0
                else:
                    template_index = state.get("template_index", 0)
        
        if template_index is None:
            template_index = 0

        alternate_templates = state.get("alternate_templates", False)
        if alternate_templates and len(templates) > 1 and selected_accounts:
            try:
                account_index = selected_accounts.index(account)
                template_index = account_index % len(templates)
            except ValueError:
                template_index = 0

        if template_index >= len(templates):
            template_index = 0
        template_list = templates
        folders = await list_folders(client)
        if not folders:
            return

        # Загружаем настройки игнорирования
        ignore_settings = load_ignore_settings(user_id)
        ignore_folders = ignore_settings.get("ignore_folders", {})
        ignore_chats = ignore_settings.get("ignore_chats", {})
        
        # Фильтруем папки с учетом игнорируемых
        filtered_folders = filter_folders_by_ignore(folders, ignore_folders, account_phone)
        
        if not filtered_folders:
            return

        # Определяем папку в зависимости от режима, если не resume
        if template_mode != "resume":
            # Если папка не была определена ранее, определяем её сейчас
            if selected_folder.get("folder_index") is not None:
                # Используем сохраненный индекс папки
                folder_keys = list(filtered_folders.keys())
                folder_index = selected_folder.get("folder_index", 0)
                if folder_index >= len(folder_keys):
                    folder_index = 0  # Если индекс выходит за пределы, берем первую папку
                selected_folder = filtered_folders[folder_keys[folder_index]]
            elif selected_folder.get("id") == 1 and selected_folder.get("title") == "1":
                # Это заглушка, нужно определить реальную папку
                folder_keys = list(filtered_folders.keys())
                if template_mode == "select" and selected_accounts:
                    try:
                        account_index = selected_accounts.index(account)
                        folder_set = state.get("folder_set", "F1")
                        folder_offset = int(folder_set[1]) - 1  # F1=0, F2=1, F3=2, F4=3, F5=4
                        folder_index = (account_index + folder_offset) % len(folder_keys)
                        selected_folder = filtered_folders[folder_keys[folder_index]]
                    except (ValueError, IndexError):
                        selected_folder = filtered_folders[folder_keys[0]]
                else:
                    selected_folder = filtered_folders[folder_keys[0]]
            folder_keys = list(filtered_folders.keys())
        else:
            # В режиме resume ищем папку по индексу в списке папок
            folder_keys = list(filtered_folders.keys())
            # Определяем индекс папки из resume_state
            folder_index = selected_folder.get('folder_index', 0)
            if folder_index >= len(folder_keys):
                folder_index = 0  # Если индекс выходит за пределы, берем первую папку
            selected_folder = filtered_folders[folder_keys[folder_index]]
        # Обновляем состояние в resume_process.json
        # Определяем folder_index для сохранения
        folder_keys = list(filtered_folders.keys())
        folder_index = 0
        for idx, (key, folder_info) in enumerate(filtered_folders.items()):
            if folder_info['id'] == selected_folder['id']:
                folder_index = idx
                break
        
        folder_for_save = {"folder_index": folder_index, "title": selected_folder["title"]}
        update_account_resume_state(
            account_phone, 
            template_index=template_index, 
            folder=folder_for_save, 
            chat_index=start_index, 
            message_count=message_count,
            break_seconds_left=break_seconds_left,
            break_until_timestamp=break_until_timestamp,
            user_id=user_id
        )

        timers = {}
        logging_enabled = state.get("logging_enabled", True)
        alternate_templates_enabled = state.get("alternate_templates", True)

        # Добавляем nickname в объект аккаунта для совместимости с CLI-версией
        account_with_nickname = account.copy()
        account_with_nickname['nickname'] = account.get('nickname', account.get('name', account.get('phone')))
        
        # Используем логику CLI-версии
        if template_mode == "resume" and resume_state:
            # Запускаем в режиме возобновления
            # Сбрасываем флаг ignore_breaks для обычного запуска (не принудительного)
            ignore_breaks = False  # Всегда False для обычного запуска
            minimized = state.get("minimized", False)  # Получаем флаг свернутости
            await main_flow_resume(
                account_with_nickname, client, template_list, template_index, selected_folder, timers,
                start_index, break_seconds_left, logging_enabled, alternate_templates_enabled, user_id, ignore_breaks, minimized
            )
        else:
            # Запускаем в обычном режиме
            minimized = state.get("minimized", False)  # Получаем флаг свернутости
            await main_flow(
                account_with_nickname, client, template_list, template_index, selected_folder, timers,
                logging_enabled, start_index, message_count, alternate_templates_enabled, user_id, minimized
            )

    except Exception as e:
        await log_to_telegram(user_id, f"Ошибка рассылки с аккаунта {session_name}: {e}", "mailing")


def get_accounts_menu(user_id):
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    license_type = user_states.get(f"{user_id}_license_type")
    
    # Определяем тип лицензии только для owner и admin - это критично для правильного отображения
    if not license_type:
        license_type = detect_license_type(user_id)
        if license_type in ["owner", "admin"]:
            user_states[f"{user_id}_license_type"] = license_type
    
    sessions_count = get_sessions_count(user_id)
    
    if license_type in ["owner", "admin"]:
        markup.inline_keyboard.append([InlineKeyboardButton(text="Авторизация 🆕", callback_data="add_account")])
    elif license_type == "trial":
        # Для пробного периода максимум 3 аккаунта
        max_allowed = get_max_sessions_for_license(user_id)
        markup.inline_keyboard.append([InlineKeyboardButton(text=f"               Авторизация 🆕     ({sessions_count}/{max_allowed})", callback_data="add_account")])
    else:
        max_allowed = get_max_sessions_for_license(user_id)
        markup.inline_keyboard.append([InlineKeyboardButton(text=f"               Авторизация 🆕     ({sessions_count}/{max_allowed})", callback_data="add_account")])
    
    markup.inline_keyboard.append([InlineKeyboardButton(text="Деавторизация 🚮", callback_data="deauth_account")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="back_to_manage")])
    return markup

def get_deauth_accounts_menu(user_id):
    accounts = load_user_accounts(user_id)
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    if not accounts:
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="back_to_accounts_menu")])
        return markup
    for acc in accounts:
        if acc.get("username"):
            label = f"@{acc['username']}"
        elif acc.get("name"):
            label = acc["name"]
        else:
            label = acc.get("phone")
        markup.inline_keyboard.append([InlineKeyboardButton(text=label, callback_data=f"deauth_{acc.get('phone')}")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="back_to_accounts_menu")])
    return markup

def get_accounts_manage_menu():
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    # 1. В самом верху одна кнопка
    markup.inline_keyboard.append([InlineKeyboardButton(text="Аккаунты 👥", callback_data="accounts_menu")])
    # 2. Ниже две кнопки в ряд
    markup.inline_keyboard.append([
        InlineKeyboardButton(text="Рассылка 🧑‍💻", callback_data="message_mailing"),
        InlineKeyboardButton(text="Почта 📨", callback_data="postman")
    ])
    # 3. Ниже две кнопки в ряд
    markup.inline_keyboard.append([
        InlineKeyboardButton(text="Автоответчик 📼", callback_data="autoresponder"),
        InlineKeyboardButton(text="Мультитул ⚒️", callback_data="multitool")
    ])
    # 4. Ниже две кнопки в ряд
    markup.inline_keyboard.append([
        InlineKeyboardButton(text="Парсинг 🧲", callback_data="parsing"),
        InlineKeyboardButton(text="Поиск чатов 🔍", callback_data="chat_search")
    ])
    # 5. Ниже две кнопки в ряд
    markup.inline_keyboard.append([
        InlineKeyboardButton(text="Автоподписка 💬", callback_data="autosubscribe"),
        InlineKeyboardButton(text="Панель аналитики 📈 ", callback_data="analytics")
    ])
    # 6. В самом низу одна кнопка
    markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="back_to_menu")])
    return markup

async def send_accounts_manage_menu_with_image(bot, chat_id, caption="Управление аккаунтами."):
    """Отправляет меню управления аккаунтами с изображением manage.png"""
    try:
        # Получаем статистику пользователя
        user_id = chat_id  # В Telegram chat_id = user_id для личных сообщений
        stats_caption = get_user_stats_display(user_id)
        
        # Получаем путь к изображению с учетом стиля пользователя
        image_path = get_image_path("manage.png", user_id)
        full_path = Path(__file__).parent / image_path
        
        if full_path.exists():
            # Отправляем фото с меню
            await bot.send_photo(
                chat_id=chat_id,
                photo=FSInputFile(str(full_path)),
                caption=stats_caption,
                reply_markup=get_accounts_manage_menu()
            )
        else:
            # Если изображение не найдено, отправляем обычное сообщение
            await bot.send_message(
                chat_id=chat_id,
                text=stats_caption,
                reply_markup=get_accounts_manage_menu()
            )
    except Exception as e:
        # В случае ошибки отправляем обычное сообщение
        await bot.send_message(
            chat_id=chat_id,
            text=caption,
            reply_markup=get_accounts_manage_menu()
        )

def get_main_inline_menu():
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Управление аккаунтами 🕹️", callback_data="manage_accounts")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Партнерская программа 🤝", callback_data="partner_program")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Инструкция ❓", callback_data="instructions")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Free NFT 🎁", callback_data="free_nft")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Настройки ⚙️", callback_data="settings")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Подписка 🪪", callback_data="subscription")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Помощь 🆘", url="https://t.me/crypto_andromeda")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Выйти ✖️", callback_data="logout")])
    return markup

def get_logout_confirmation_menu():
    """Меню подтверждения выхода из системы"""
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append([
        InlineKeyboardButton(text="Да", callback_data="logout_confirm"),
        InlineKeyboardButton(text="Нет", callback_data="logout_cancel")
    ])
    return markup

def get_logout_confirmation_menu_en():
    """Английская версия меню подтверждения выхода"""
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append([
        InlineKeyboardButton(text="Yes", callback_data="logout_confirm"),
        InlineKeyboardButton(text="No", callback_data="logout_cancel")
    ])
    return markup

def get_accounts_for_templates_menu(user_id):
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="back_to_manage")])
    return markup

def get_templates_list_menu(phone, templates):
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    for idx, _ in enumerate(templates, 1):
        markup.inline_keyboard.append([InlineKeyboardButton(text=f"Шаблон 📄 #{idx}", callback_data=f"show_template|{phone}|{idx}")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Добавить шаблон ➕", callback_data=f"add_template|{phone}")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="back_to_templates_select_account")])
    return markup

def get_back_to_templates_select_account_menu():
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="back_to_templates_select_account")])
    return markup

back_menu_auth = InlineKeyboardMarkup(inline_keyboard=[])
back_menu_auth.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="back_to_accounts_menu")])

back_menu = InlineKeyboardMarkup(inline_keyboard=[])
back_menu.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="back_to_menu")])

def get_back_only_menu():
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться", callback_data="back_to_menu")])
    return markup

def get_settings_menu():
    """Меню настроек"""
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Стиль 🎨", callback_data="change_style")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Язык 🇺🇸🇷🇺", callback_data="change_language")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Изображения 🖼️", callback_data="toggle_images")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="back_to_menu")])
    return markup

def get_settings_menu_en():
    """Английская версия меню настроек"""
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Style 🎨", callback_data="change_style")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Language 🇺🇸🇷🇺", callback_data="change_language")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Images 🖼️", callback_data="toggle_images")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Back 🔙", callback_data="back_to_menu")])
    return markup

def get_style_menu():
    """Меню выбора стиля"""
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Robo 🤖", callback_data="style_robo")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Fallout ☢️", callback_data="style_fallout")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="back_to_settings")])
    return markup

def get_style_menu_en():
    """Английская версия меню выбора стиля"""
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Robo 🤖", callback_data="style_robo")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Fallout ☢️", callback_data="style_fallout")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Back 🔙", callback_data="back_to_settings")])
    return markup

def get_instructions_menu():
    """Меню инструкций"""
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Статистика 📊", callback_data="instruction_statistics")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Рассылка 🧑‍💻", callback_data="instruction_mailing")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Почта 📨", callback_data="instruction_postman")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Автоответчик 📼", callback_data="instruction_autoresponder")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Мультитул ⚒️", callback_data="instruction_multitool")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Парсинг 🧲", callback_data="instruction_parsing")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Поиск чатов 🔍", callback_data="instruction_chat_search")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Автоподписка 💬", callback_data="instruction_autosubscribe")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Панель аналитики 📈 ", callback_data="instruction_analytics")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="back_to_menu")])
    return markup

def mailing_message_menu(user_id=None):
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    # Проверяем состояние раздела "Рассылка"
    if user_id is not None:
        # Проверяем состояние рассылки в mailing_states
        mailing_state = mailing_states.get(user_id, {})
        is_active = mailing_state.get("active", False)
        is_minimized = mailing_state.get("minimized", False)
        
        # Дополнительная проверка через user_sessions для совместимости
        session_minimized = user_sessions.get(user_id, {}).get("pushmux", {}).get("minimized", False)
        
        # Если рассылка активна и свернута - показываем "Развернуть"
        if is_active and (is_minimized or session_minimized):
            markup.inline_keyboard.append([InlineKeyboardButton(text="Развернуть ↩️", callback_data="mailing_expand")])
        else:
            # Если не свернуто или не активно — показываем "Старт ▶️"
            markup.inline_keyboard.append([InlineKeyboardButton(text="Старт ▶️", callback_data="mailing_start")])
    else:
        # Если user_id не передан — показываем "Старт ▶️" по умолчанию
        markup.inline_keyboard.append([InlineKeyboardButton(text="Старт ▶️", callback_data="mailing_start")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Шаблоны 📝", callback_data="mailing_templates")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="back_to_manage")])
    return markup

# --- 1. Новый get_postman_menu ---
def get_postman_menu(user_id=None):
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    mailboxer_active = False
    if user_id is not None:
        # Проверяем состояние почты в postman_states
        postman_state = postman_states.get(user_id, {})
        mailboxer_active = postman_state.get("active", False)
        
        # Дополнительная проверка: если mailboxer активен в состоянии, но нет в сессии,
        # то считаем его активным (это случай автовосстановления)
        if not mailboxer_active:
            session = user_sessions.get(user_id, {})
            mailboxer_active = "mailboxer" in session
    
    if mailboxer_active:
        markup.inline_keyboard.append([
            InlineKeyboardButton(text="Остановить ⭕️", callback_data="postman_stop")
        ])
    else:
        markup.inline_keyboard.append([
            InlineKeyboardButton(text="Активировать ✔️", callback_data="postman_activate")
        ])
    markup.inline_keyboard.append([
        InlineKeyboardButton(text="Вернуться 🔙", callback_data="back_to_manage")
    ])
    return markup

def get_autoresponder_menu(user_id=None):
    """Главное меню автоответчика"""
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    
    # Инициализируем autoresponder_states для пользователя, если его там нет
    if user_id and user_id not in autoresponder_states:
        autoresponder_states[user_id] = {"active": False, "selected_accounts": []}
        update_service_state("autoresponder_states", user_id, autoresponder_states[user_id])
    
    # Проверяем, есть ли активные автоответчики
    is_active = autoresponder_states.get(user_id, {}).get("active", False)
    selected_accounts = autoresponder_states.get(user_id, {}).get("selected_accounts", [])
    
    # Дополнительная проверка: если автоответчик активен, но selected_accounts пустые,
    # то считаем что автоответчик не работает корректно
    if is_active and not selected_accounts:
        print(f"⚠️ Автоответчик помечен как активный, но selected_accounts пустые для пользователя {user_id}")
        # Автоматически деактивируем автоответчик
        if user_id in autoresponder_states:
            autoresponder_states[user_id]["active"] = False
            update_service_state("autoresponder_states", user_id, autoresponder_states[user_id])
        else:
            # Если пользователя нет в autoresponder_states, создаем запись с active = False
            autoresponder_states[user_id] = {"active": False, "selected_accounts": []}
            update_service_state("autoresponder_states", user_id, autoresponder_states[user_id])
        is_active = False
    
    if is_active:
        markup.inline_keyboard.append([
            InlineKeyboardButton(text="Остановить ⭕️", callback_data="autoresponder_stop")
        ])
    else:
        # Проверяем, есть ли шаблоны
        if user_id and has_autoresponder_templates(user_id):
            markup.inline_keyboard.append([
                InlineKeyboardButton(text="Активировать ✔️", callback_data="autoresponder_activate")
            ])
        else:
            markup.inline_keyboard.append([
                InlineKeyboardButton(text="Активировать ✔️", callback_data="autoresponder_no_templates")
            ])
    
    markup.inline_keyboard.append([
        InlineKeyboardButton(text="Шаблоны 📄", callback_data="autoresponder_templates")
    ])
    markup.inline_keyboard.append([
        InlineKeyboardButton(text="Вернуться 🔙", callback_data="back_to_manage")
    ])
    return markup

def get_autoresponder_accounts_menu(user_id, action="activate"):
    """Меню выбора аккаунтов для автоответчика"""
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    accounts = get_active_accounts_by_sessions(user_id)
    
    if action == "activate":
        selected_accounts = autoresponder_states.get(user_id, {}).get("selected_accounts", [])
        
        for acc in accounts:
            phone = acc.get("phone")
            if acc.get("username"):
                label = f"@{acc['username']}"
            elif acc.get("name"):
                label = acc["name"]
            else:
                label = phone
            
            # Добавляем галочку если аккаунт выбран
            if phone in selected_accounts:
                label += " ✅"
                
            markup.inline_keyboard.append([
                InlineKeyboardButton(text=label, callback_data=f"autoresponder_toggle_account|{phone}")
            ])
        
        if accounts:
            markup.inline_keyboard.append([
                InlineKeyboardButton(text="Выбрать все", callback_data="autoresponder_select_all")
            ])
            markup.inline_keyboard.append([
                InlineKeyboardButton(text="Подтвердить", callback_data="autoresponder_confirm")
            ])
    else:  # templates
        for acc in accounts:
            phone = acc.get("phone")
            if acc.get("username"):
                label = f"@{acc['username']}"
            elif acc.get("name"):
                label = acc["name"]
            else:
                label = phone
                
            markup.inline_keyboard.append([
                InlineKeyboardButton(text=label, callback_data=f"autoresponder_account_templates|{phone}")
            ])
    
    markup.inline_keyboard.append([
        InlineKeyboardButton(text="Вернуться 🔙", callback_data="autoresponder")
    ])
    return markup
def get_autoresponder_account_template_menu(user_id, account_phone):
    """Меню шаблона для конкретного аккаунта"""
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    
    template = get_autoresponder_template(user_id, account_phone)
    if template:
        # Показываем только действия над шаблоном
        markup.inline_keyboard.append([
            InlineKeyboardButton(text="Удалить 🗑", callback_data=f"autoresponder_delete_template|{account_phone}"),
            InlineKeyboardButton(text="Редактировать ✍️", callback_data=f"autoresponder_edit_template|{account_phone}")
        ])
    # Кнопка назад к выбору аккаунтов 
    markup.inline_keyboard.append([
        InlineKeyboardButton(text="Вернуться 🔙", callback_data="autoresponder_account_templates")
    ])
    return markup
    
def get_autoresponder_template_actions_menu(account_phone):
    """Меню действий с шаблоном"""
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append([
        InlineKeyboardButton(text="Удалить 🗑", callback_data=f"autoresponder_delete_template|{account_phone}"),
        InlineKeyboardButton(text="Редактировать ✍️", callback_data=f"autoresponder_edit_template|{account_phone}")
    ])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="autoresponder_account_templates")])
    return markup

def get_language_menu():
    """Меню выбора языка"""
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append([
        InlineKeyboardButton(text="RU 🇷🇺", callback_data="language_ru"),
        InlineKeyboardButton(text="ENG 🇺🇸", callback_data="language_en")
    ])
    return markup

def get_style_menu(language="ru", user_id=None):
    """Меню выбора стиля"""
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    
    # Получаем текущий стиль пользователя
    current_style = get_user_style(user_id) if user_id else None
    
    # Формируем текст стиля
    if current_style == "robo":
        style_text = "🤖 Robo"
    elif current_style == "fallout":
        style_text = "☢️ Fallout"
    else:
        style_text = "Не выбран"
    
    if language == "ru":
        title = f"Выберите стиль интерфейса:"
        markup.inline_keyboard.append([
            InlineKeyboardButton(text="🤖 Robo", callback_data="style_robo"),
            InlineKeyboardButton(text="☢️ Fallout", callback_data="style_fallout")
        ])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="back_to_language")])
    else:
        title = f"Choose interface style:"
        markup.inline_keyboard.append([
            InlineKeyboardButton(text="🤖 Robo", callback_data="style_robo"),
            InlineKeyboardButton(text="☢️ Fallout", callback_data="style_fallout")
        ])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Back 🔙", callback_data="back_to_language")])
    
    return markup, title

def get_start_menu():
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Вход 🚪 ", callback_data="start_auth")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Пробный период 24ч 🧨", callback_data="free_trial")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Связаться с нами ☎️", url="https://t.me/luxurydynasty")])
    return markup

def get_start_menu_en():
    """Английская версия стартового меню"""
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Login 🚪 ", callback_data="start_auth")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Free Trial 24h 🧨", callback_data="free_trial")])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Contact Us ☎️", url="https://t.me/luxurydynasty")])
    return markup


def get_back_to_start_menu():
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="back_to_start")])
    return markup

def get_back_to_start_menu_en():
    """Английская версия кнопки возврата"""
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Back 🔙", callback_data="back_to_start")])
    return markup

def get_back_to_referral_menu():
    """Кнопка возврата к экрану реферала ("Есть реферальный код?")"""
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="back_to_referral")])
    return markup

def get_back_to_referral_menu_en():
    """Английская версия кнопки возврата к экрану реферала"""
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Back 🔙", callback_data="back_to_referral")])
    return markup

def ensure_event_loop():
    import asyncio
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

def is_log_line(line):
    # Определяет строки логов статусов отправки
    return line.startswith("/ Успешно 🟢") or line.startswith("/ Неудачно 🔴")

def load_keys():
    """Загружает содержимое key.json как есть (для обратной совместимости)."""
    if not os.path.exists(KEYS_FILE):
        return {}
    try:
        with open(KEYS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def load_key_groups():
    """Загружает ключи по группам: owner, admin, pro, premium, basic, trial.

    Возвращает dict с ключами-группами и списками строк-ключей.
    Поддерживает старые форматы:
    - если в key.json лежит список, трактуем его как basic
    - если присутствует устаревшая группа 'user', считаем её basic
    """
    raw = load_keys()
    groups = {
        "owner": [],
        "admin": [],
        "pro": [],
        "premium": [],
        "basic": [],
        "trial": [],
    }
    try:
        if isinstance(raw, dict):
            for k in ["owner", "admin", "pro", "premium", "basic", "trial"]:
                if k in raw and isinstance(raw[k], list):
                    groups[k] = [str(x) for x in raw[k]]
            # Миграция со старого поля 'user'
            if "user" in raw and isinstance(raw["user"], list):
                groups["basic"] = list({*groups["basic"], *[str(x) for x in raw["user"]]})
        elif isinstance(raw, list):
            # Старый формат: просто список ключей пользователей – трактуем как basic
            groups["basic"] = [str(x) for x in raw]
    except Exception:
        pass
    return groups

def load_licenses():
    if not os.path.exists(LICENSE_FILE):
        return {}
    try:
        with open(LICENSE_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return {}
            licenses = json.loads(content)
            return licenses
    except Exception as e:
        return {}

def load_freetrial():
    """Загружает данные о пробном периоде пользователей"""
    if not os.path.exists("freetrial.json"):
        return {}
    try:
        with open("freetrial.json", "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except Exception as e:
        return {}

def load_referrals():
    """Загружает реферальные коды"""
    if not os.path.exists("referrals.json"):
        return {"referrals": []}
    try:
        with open("referrals.json", "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return {"referrals": []}
            return json.loads(content)
    except Exception as e:
        return {"referrals": []}

def save_referrals(referrals_data):
    """Сохраняет реферальные коды"""
    try:
        with open("referrals.json", "w", encoding="utf-8") as f:
            json.dump(referrals_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения referrals.json: {e}")

def load_invites():
    """Загружает данные о приглашениях пользователей"""
    if not os.path.exists("invites.json"):
        return {}
    try:
        with open("invites.json", "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except Exception as e:
        return {}

def save_invites(invites_data):
    """Сохраняет данные о приглашениях пользователей"""
    try:
        with open("invites.json", "w", encoding="utf-8") as f:
            json.dump(invites_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения invites.json: {e}")

def is_valid_referral_code(code):
    """Проверяет, является ли код валидным реферальным кодом"""
    referrals_data = load_referrals()
    return code in referrals_data.get("referrals", [])

def has_user_used_referral(user_id):
    """Проверяет, активировал ли пользователь реферальный бонус ранее (по любому коду)"""
    try:
        invites_data = load_invites()
        user_id_str = str(user_id)
        for code, users in invites_data.items():
            if isinstance(users, dict) and user_id_str in users:
                return True
        return False
    except Exception:
        return False

def get_referral_bonus_seconds(user_id):
    """Возвращает бонус в секундах за реферальный код, если он активирован пользователем"""
    return 259200 if has_user_used_referral(user_id) else 0

def add_invite(referral_code, invited_id):
    """Добавляет приглашение в систему по реферальному коду"""
    invites_data = load_invites()
    invited_id_str = str(invited_id)
    current_time = int(time.time())
    
    if referral_code not in invites_data:
        invites_data[referral_code] = {}
    
    # Добавляем пользователя: храним и unix, и строковую дату с TZ
    invites_data[referral_code][invited_id_str] = {
        "activated_at": current_time,
        "date": _format_now_with_gmt()
    }
    save_invites(invites_data)

def find_referrer_by_code(code):
    """Находит реферера по реферальному коду"""
    # Теперь реферальный код напрямую связан с приглашениями
    # Возвращаем None, так как у нас нет прямой связи кода с реферером
    # В будущем можно добавить отдельную таблицу связи кодов с пользователями
    return None

def get_referral_stats_by_code(code):
    """Получает статистику по реферальному коду"""
    invites_data = load_invites()
    if code in invites_data:
        return {
            "total_invited": len(invites_data[code]),
            "invited_users": invites_data[code],
            "referral_code": code
        }
    return None

def get_user_referral_expiry(user_id):
    """Получает время истечения реферального периода для пользователя"""
    invites_data = load_invites()
    current_time = int(time.time())
    
    for code, users in invites_data.items():
        if str(user_id) in users:
            activation_time = users[str(user_id)]
            # 72 часа = 259200 секунд
            expiry_time = activation_time + 259200
            time_left = expiry_time - current_time
            
            if time_left > 0:
                return {
                    "referral_code": code,
                    "activation_time": activation_time,
                    "expiry_time": expiry_time,
                    "time_left": time_left,
                    "is_expired": False
                }
            else:
                return {
                    "referral_code": code,
                    "activation_time": activation_time,
                    "expiry_time": expiry_time,
                    "time_left": 0,
                    "is_expired": True
                }
    
    return None

def is_referral_expired(user_id):
    """Проверяет, истек ли реферальный период у пользователя"""
    expiry_info = get_user_referral_expiry(user_id)
    if expiry_info:
        return expiry_info["is_expired"]
    return True  # Если нет информации о реферале, считаем что истек

def get_referral_time_left_formatted(user_id):
    """Получает оставшееся время реферального периода в читаемом формате"""
    expiry_info = get_user_referral_expiry(user_id)
    if not expiry_info or expiry_info["is_expired"]:
        return "Истек"
    
    time_left = expiry_info["time_left"]
    hours = time_left // 3600
    minutes = (time_left % 3600) // 60
    seconds = time_left % 60
    
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

def get_user_style(user_id):
    """Получает текущий стиль пользователя"""
    # Сначала пытаемся загрузить настройки с текущим license_type
    settings = load_user_settings(user_id)
    style = settings.get("style")
    
    # Если стиль не найден, пытаемся определить тип лицензии и загрузить из правильной папки
    if not style:
        try:
            # Определяем тип лицензии по существующим папкам
            license_type = detect_license_type(user_id)
            if license_type:
                # Сохраняем определенный тип лицензии для будущего использования
                user_states[f"{user_id}_license_type"] = license_type
                # Пытаемся загрузить из папки с правильным типом лицензии
                user_dir = get_user_dir(user_id, license_type, create_dir=False)
                settings_file = os.path.join(user_dir, "settings.json")
                if os.path.exists(settings_file):
                    with open(settings_file, "r", encoding="utf-8") as f:
                        settings = json.load(f)
                        style = settings.get("style")
                        if style:
                            return style
        except Exception:
            pass

        # Если стиль все еще не найден, пробуем загрузить из папки без суффикса лицензии
        try:
            # Пытаемся загрузить из папки пользователя без суффикса
            user_dir = get_user_dir(user_id, None, create_dir=False)
            settings_file = os.path.join(user_dir, "settings.json")
            if os.path.exists(settings_file):
                with open(settings_file, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                    style = settings.get("style")
        except Exception:
            pass
    
    return style

def set_user_style(user_id, style):
    """Устанавливает стиль пользователя"""
    if style not in ["robo", "fallout"]:
        return False
    
    # Пытаемся сохранить в текущую папку пользователя
    settings = load_user_settings(user_id)
    settings["style"] = style
    success = update_user_settings(user_id, settings)
    
    # Если не удалось сохранить, пытаемся определить тип лицензии и сохранить в правильную папку
    if not success:
        try:
            # Определяем тип лицензии по существующим папкам
            license_type = detect_license_type(user_id)
            if license_type:
                # Сохраняем определенный тип лицензии для будущего использования
                user_states[f"{user_id}_license_type"] = license_type
                # Пытаемся сохранить в папку с правильным типом лицензии
                user_dir = get_user_dir(user_id, license_type, create_dir=True)
                settings_file = os.path.join(user_dir, "settings.json")
                
                # Загружаем существующие настройки или создаем новые
                current_settings = {}
                if os.path.exists(settings_file):
                    try:
                        with open(settings_file, "r", encoding="utf-8") as f:
                            current_settings = json.load(f) or {}
                    except Exception:
                        current_settings = {}
                
                # Обновляем стиль
                current_settings["style"] = style
                
                # Сохраняем
                with open(settings_file, "w", encoding="utf-8") as f:
                    json.dump(current_settings, f, ensure_ascii=False, indent=2)
                success = True
                print(f"Стиль {style} сохранен в папку с типом лицензии {license_type}")
            else:
                # Если тип лицензии не определен, сохраняем в папку без суффикса
                user_dir = get_user_dir(user_id, None, create_dir=True)
                settings_file = os.path.join(user_dir, "settings.json")
                
                # Загружаем существующие настройки или создаем новые
                current_settings = {}
                if os.path.exists(settings_file):
                    try:
                        with open(settings_file, "r", encoding="utf-8") as f:
                            current_settings = json.load(f) or {}
                    except Exception:
                        current_settings = {}
                
                # Обновляем стиль
                current_settings["style"] = style
                
                # Сохраняем
                with open(settings_file, "w", encoding="utf-8") as f:
                    json.dump(current_settings, f, ensure_ascii=False, indent=2)
                success = True
        except Exception as e:
            print(f"Ошибка сохранения стиля для пользователя {user_id}: {e}")
            success = False
    
    return success

def get_image_path(image_name, user_id=None):
    """Получает путь к изображению с учетом стиля пользователя"""
    if user_id is None:
        # Если user_id не передан, возвращаем путь без стиля
        return f"img/{image_name}"
    
    style = get_user_style(user_id)
    
    # Если стиль не установлен, возвращаем путь без стиля
    if not style:
        # Пытаемся найти файл в стилях по умолчанию (robo, fallout)
        for fallback_style in ["robo", "fallout"]:
            fallback_path = f"img/{fallback_style}/{image_name}"
            if os.path.exists(fallback_path):
                return fallback_path
        return f"img/{image_name}"
    
    # Проверяем, существует ли изображение в папке стиля
    style_path = f"img/{style}/{image_name}"
    if os.path.exists(style_path):
        return style_path
    
    # Если изображение не найдено в папке стиля, пробуем стили по умолчанию
    for fallback_style in ["robo", "fallout"]:
        fallback_path = f"img/{fallback_style}/{image_name}"
        if os.path.exists(fallback_path):
            return fallback_path
    
    # Финальный фолбэк — путь без стиля
    return f"img/{image_name}"

def format_referral_stats_for_display(user_id):
    """Форматирует статистику рефералов для отображения пользователю"""
    stats = get_user_referral_stats(user_id)
    expiry_info = get_user_referral_expiry(user_id)
    
    if not stats["used_referral_codes"]:
        return "У вас нет активных реферальных кодов"
    
    result = f"📊 Ваша реферальная статистика:\n\n"
    
    for code_info in stats["used_referral_codes"]:
        code = code_info["code"]
        activation_time = code_info["activation_time"]
        expiry_time = code_info["expiry_time"]
        
        # Форматируем время
        activation_date = time.strftime("%d.%m.%Y %H:%M", time.localtime(activation_time))
        expiry_date = time.strftime("%d.%m.%Y %H:%M", time.localtime(expiry_time))
        
        result += f"🔑 Код: {code}\n"
        result += f"📅 Активирован: {activation_date}\n"
        result += f"⏰ Истекает: {expiry_date}\n"
        
        if expiry_info and not expiry_info["is_expired"]:
            time_left = get_referral_time_left_formatted(user_id)
            result += f"⏳ Осталось: {time_left}\n"
        else:
            result += f"❌ Истек\n"
        
        result += "\n"
    
    return result

def generate_referral_code():
    """Генерирует новый уникальный реферальный код"""
    import random
    import string
    
    while True:
        # Генерируем код из 16 символов (буквы и цифры)
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))
        
        # Проверяем, что код уникален
        if not is_valid_referral_code(code):
            return code

def add_referral_code_to_user(user_id, code):
    """Добавляет реферальный код пользователю"""
    # Эта функция больше не нужна с новой структурой
    # Реферальные коды теперь напрямую связаны с приглашениями
    pass

def get_user_referral_stats(user_id):
    """Получает статистику рефералов пользователя"""
    # Теперь статистика работает по-другому - нужно искать пользователя в invites
    invites_data = load_invites()
    user_id_str = str(user_id)
    
    # Ищем, какие реферальные коды использовал этот пользователь
    used_codes = []
    total_invited = 0
    
    for code, users in invites_data.items():
        if user_id_str in users:
            entry = users[user_id_str]
            if isinstance(entry, dict):
                activation_time = entry.get("activated_at", 0)
            else:
                activation_time = int(entry) if isinstance(entry, int) else 0
            used_codes.append({
                "code": code,
                "activation_time": activation_time,
                "expiry_time": activation_time + 259200  # 72 часа
            })
            total_invited += 1
    
    return {
        "used_referral_codes": used_codes,
        "total_invited": total_invited
    }

def get_referral_menu():
    """Меню для реферальной системы"""
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append([
        InlineKeyboardButton(text="Ввести код", callback_data="enter_referral"),
        InlineKeyboardButton(text="Пропустить", callback_data="skip_referral")
    ])
    markup.inline_keyboard.append([
        InlineKeyboardButton(text="Вернуться 🔙", callback_data="back_to_start")
    ])
    return markup

def get_referral_menu_en():
    """Английская версия меню для реферальной системы"""
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append([
        InlineKeyboardButton(text="Enter referral code", callback_data="enter_referral"),
        InlineKeyboardButton(text="Skip", callback_data="skip_referral")
    ])
    markup.inline_keyboard.append([
        InlineKeyboardButton(text="Back 🔙", callback_data="back_to_start")
    ])
    return markup

def load_user_languages():
    """Загружает сохраненные языковые настройки пользователей из settings.json.

    Поддержка старого формата: если есть legacy language.json и нет settings.json,
    читаем язык из language.json.
    """
    all_languages = {}
    
    # Загружаем из индивидуальных файлов пользователей
    root = get_project_root()
    user_base_dir = os.path.join(root, "user")
    
    if os.path.exists(user_base_dir):
        for item in os.listdir(user_base_dir):
            # Загружаем как из папок с суффиксами, так и без них
            if item.endswith(("_trial", "_pro", "_premium", "_basic", "_admin", "_owner")) or item.isdigit():
                user_id = item.split("_")[0] if "_" in item else item
                # Новый формат
                settings_file = os.path.join(user_base_dir, item, "settings.json")
                # Legacy формат
                language_file = os.path.join(user_base_dir, item, "language.json")
                try:
                    if os.path.exists(settings_file):
                        with open(settings_file, "r", encoding="utf-8") as f:
                            content = f.read().strip()
                            if content:
                                data = json.loads(content)
                                all_languages[user_id] = data.get("language", "ru")
                    elif os.path.exists(language_file):
                        with open(language_file, "r", encoding="utf-8") as f:
                            content = f.read().strip()
                            if content:
                                data = json.loads(content)
                                all_languages[user_id] = data.get("language", "ru")
                except Exception as e:
                    print(f"Ошибка загрузки настроек пользователя из {item}: {e}")
    
    return all_languages

def save_user_languages():
    """Сохраняет языковые настройки пользователей в settings.json для каждого пользователя"""
    try:
        # Убираем сохранение в корневой файл - теперь работаем только с индивидуальными файлами
        # with open("user_languages.json", "w", encoding="utf-8") as f:
        #     json.dump(user_languages, f, ensure_ascii=False, indent=2)
        
        # Сохраняем в индивидуальные файлы пользователей
        for user_id, language in user_languages.items():
            try:
                # Пытаемся сохранить в существующую суффиксную папку, иначе в plain
                root = get_project_root()
                user_base_dir = os.path.join(root, "user")
                target_dir = None
                for suf in ("_owner", "_admin", "_pro", "_premium", "_basic", "_trial"):
                    candidate = os.path.join(user_base_dir, f"{user_id}{suf}")
                    if os.path.isdir(candidate):
                        target_dir = candidate
                        break
                if target_dir is None:
                    target_dir = os.path.join(user_base_dir, str(user_id))
                    os.makedirs(target_dir, exist_ok=True)

                settings_file = os.path.join(target_dir, "settings.json")
                settings = {"language": language}
                with open(settings_file, "w", encoding="utf-8") as f:
                    json.dump(settings, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"Ошибка сохранения settings.json для пользователя {user_id}: {e}")
                
    except Exception as e:
        print(f"Ошибка сохранения языковых настроек: {e}")

def get_user_language(user_id):
    """Возвращает язык пользователя из settings.json. Обёртка для обратной совместимости."""
    settings = load_user_settings(user_id)
    return settings.get("language", user_languages.get(user_id, "ru"))

def set_user_language(user_id, language):
    """Ставит language в settings.json. Обёртка для совместимости."""
    ok = update_user_settings(user_id, {"language": language})
    if ok:
        user_languages[user_id] = language
    return ok

def save_single_user_language(user_id, language):
    """Сохраняет language через update_user_settings и обновляет логи. Совместимость с существующими вызовами."""
    ok = update_user_settings(user_id, {"language": language})
    if ok:
        user_languages[user_id] = language
        # Обновляем язык в логах
        update_user_main_info(user_id, language=language)
    return ok

async def send_bug_message_to_all():
    """Отправляет сообщение о багах всем пользователям"""
    try:
        # Получаем всех пользователей с языковыми настройками
        users_to_notify = list(user_languages.keys())
        
        if not users_to_notify:
            print("ℹ️ Нет пользователей для уведомления о багах")
            return
        
        print(f"🔔 Отправка сообщения о багах {len(users_to_notify)} пользователям...")
        
        for user_id in users_to_notify:
            try:
                # Определяем язык пользователя
                user_lang = user_languages.get(user_id, "ru")
                
                if user_lang == "ru":
                    message_text = "❗️ Заметили баг либо отсутствие логики в каких-то кнопках, выборках или функциях ? Сообщите нам: @crypto_andromeda"
                else:
                    message_text = "❗️ Found a bug or missing logic in some buttons, selections or functions? Let us know: @crypto_andromeda"
                
                # Отправляем через log_to_telegram
                # task_name="bug_notification" - это исключение из правила свёрнутости рассылки
                # Сообщения о багах отправляются независимо от флага minimized
                await log_to_telegram(user_id, message_text, "bug_notification")
                
            except Exception as e:
                print(f"❌ Ошибка отправки пользователю {user_id}: {e}")
        
        print("✅ Сообщения о багах отправлены всем пользователям")
        
    except Exception as e:
        print(f"❌ Ошибка при отправке сообщений о багах: {e}")

async def bug_message_scheduler():
    """Планировщик для отправки сообщений о багах каждые 24-72 часа"""
    print("🔔 Запуск планировщика сообщений о багах...")
    
    while True:
        try:
            # Случайная задержка от 24 до 72 часов
            import random
            hours = random.uniform(24, 72)
            seconds = int(hours * 3600)
            
            print(f"⏰ Следующее сообщение о багах через {hours:.1f} часов ({seconds} секунд)")
            await asyncio.sleep(seconds)
            
            # Отправляем сообщение всем пользователям
            await send_bug_message_to_all()
            
        except asyncio.CancelledError:
            print("🔔 Планировщик сообщений о багах остановлен")
            break
        except Exception as e:
            print(f"❌ Ошибка в планировщике сообщений о багах: {e}")
            await asyncio.sleep(3600)  # Ждем час при ошибке

def save_freetrial(freetrial_data):
    """Сохраняет данные о пробном периоде пользователей"""
    try:
        with open("freetrial.json", "w", encoding="utf-8") as f:
            json.dump(freetrial_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения freetrial.json: {e}")

def reconcile_freetrial_sessions(user_id):
    """Синхронизирует список sessions в freetrial.json с фактическими аккаунтами из user/<id>_trial/config.json"""
    try:
        # Применимо только для trial
        if user_states.get(f"{user_id}_license_type") != "trial":
            return
        ft = load_freetrial()
        user_key = str(user_id)
        if user_key not in ft:
            return
        accounts = load_user_accounts(user_id)
        expected_names = set()
        for acc in accounts:
            name_or_phone = acc.get("name") or acc.get("phone")
            if name_or_phone:
                expected_names.add(name_or_phone)
        sessions = ft[user_key].get("sessions", [])
        new_sessions = [s for s in sessions if s in expected_names]
        if new_sessions != sessions:
            ft[user_key]["sessions"] = new_sessions
            save_freetrial(ft)
            print(f"✅ [SYNC] freetrial.json очищен: {sessions} -> {new_sessions}")
    except Exception as e:
        print(f"⚠️ [SYNC] Ошибка синхронизации freetrial.json: {e}")

def update_freetrial(user_id):
    """Активирует пробный период для пользователя"""
    # Проверяем, есть ли у пользователя активная лицензия
    licenses = load_licenses()
    if str(user_id) in licenses:
        # Если у пользователя есть лицензия, не активируем пробный период
        print(f"Пользователь {user_id} имеет лицензию, пробный период не активируется")
        return None
    
    freetrial_data = load_freetrial()
    # Если запись уже существует, не перезаписываем activated_at (активация только один раз)
    if str(user_id) not in freetrial_data:
        now = int(time.time())
        freetrial_data[str(user_id)] = {
            "activated_at": now,
            "date": _format_now_with_gmt(),
            "sessions": [],
            "authorized": True
        }
        save_freetrial(freetrial_data)
        # Обновляем логи с unix timestamp пробного периода
        update_user_main_info(user_id, freetrial=now)
        
        # Создаем config.json с API_ID и API_HASH для пробного периода
        try:
            user_dir = get_user_dir(user_id, "trial", create_dir=True)
            config_path = os.path.join(user_dir, "config.json")
            if not os.path.exists(config_path):
                config = {
                    "api_id": 22133941,
                    "api_hash": "c226d2309461ee258c2aefc4dd19b743",
                    "accounts": []
                }
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка создания config.json для пробного периода пользователя {user_id}: {e}")
    save_freetrial(freetrial_data)
    
    return freetrial_data[str(user_id)]

def is_freetrial_valid(user_id):
    """Проверяет, действителен ли пробный период пользователя"""
    # Сначала проверяем, есть ли у пользователя активная лицензия
    licenses = load_licenses()
    if str(user_id) in licenses:
        # Если у пользователя есть лицензия, пробный период недействителен
        return False
    
    freetrial_data = load_freetrial()
    user_data = freetrial_data.get(str(user_id))
    if not user_data:
        return False
    # Если явно указан authorized=false — считаем недействительным, пока пользователь не войдет снова
    if user_data.get("authorized") is False:
        return False
    
    now = int(time.time())
    activated_at = user_data.get("activated_at", 0)
    # Пробный период длится 24 часа (86400 секунд)
    return (now - activated_at) < 86400

def get_freetrial_time_left(user_id):
    """Возвращает оставшееся время пробного периода в секундах"""
    freetrial_data = load_freetrial()
    user_data = freetrial_data.get(str(user_id))
    if not user_data:
        return 0
    
    now = int(time.time())
    activated_at = user_data.get("activated_at", 0)
    time_left = 86400 - (now - activated_at)
    return max(0, time_left)

def save_licenses(licenses):
    try:
        with open(LICENSE_FILE, "w", encoding="utf-8") as f:
            json.dump(licenses, f, ensure_ascii=False, indent=2)
        
    except Exception as e:
        print(f"empty")

def update_license(user_id, license_code):
    licenses = load_licenses()
    now = int(time.time())

    # Найдём самую раннюю дату активации для данного кода
    earliest_ts = None
    for _uid, _data in licenses.items():
        try:
            if isinstance(_data, dict) and _data.get("license_code") == license_code:
                ts = int(_data.get("activated_at", 0) or 0)
                if ts > 0 and (earliest_ts is None or ts < earliest_ts):
                    earliest_ts = ts
        except Exception:
            pass
    if earliest_ts is None:
        earliest_ts = now

    # Обновляем/создаём запись текущего пользователя
    record = licenses.get(str(user_id)) or {}
    record["license_code"] = license_code
    record["activated_at"] = int(earliest_ts)
    record["date"] = _format_ts_with_gmt(int(earliest_ts))
    if "sessions" not in record or not isinstance(record.get("sessions"), list):
        record["sessions"] = []
    # Флаг авторизации: активируем при успешном вводе ключа
    record["authorized"] = True
    licenses[str(user_id)] = record

    # Нормализуем все записи с этим же кодом к earliest_ts
    for _uid, _data in list(licenses.items()):
        try:
            if isinstance(_data, dict) and _data.get("license_code") == license_code:
                if int(_data.get("activated_at", 0) or 0) != int(earliest_ts):
                    _data["activated_at"] = int(earliest_ts)
                    _data["date"] = _format_ts_with_gmt(int(earliest_ts))
        except Exception:
            pass

    save_licenses(licenses)

# --- Mailing parameters persistent store ---
def get_mailing_parameters_path(user_id, license_type=None):
    if license_type is None:
        license_type = user_states.get(f"{user_id}_license_type")
        # НЕ определяем тип лицензии автоматически - это должно происходить только при выборе лицензии
        # if not license_type:
        #     license_type = detect_license_type(user_id)
        #     if license_type:
        #         user_states[f"{user_id}_license_type"] = license_type
    
    user_dir = get_user_dir(user_id, license_type, create_dir=False)
    return os.path.join(user_dir, "mailing_parameters.json")
    
def load_mailing_parameters(user_id):
    """Load persistent mailing parameters for a user. Returns dict or default structure."""
    license_type = user_states.get(f"{user_id}_license_type")
    # Фолбэк-детекция типа лицензии, если он ещё не установлен (важно для восстановления после рестартов)
    if not license_type:
        try:
            license_type = detect_license_type(user_id)
            if license_type:
                user_states[f"{user_id}_license_type"] = license_type
        except Exception:
            license_type = None
    
    path = get_mailing_parameters_path(user_id, license_type)
    if not os.path.exists(path):
        # Provide default structure as in user's attached example
        return {
            "user_id": str(user_id),
            "license_type": detect_license_type(user_id),
            "mailing_parameters": {
                "selected_accounts": [],
                "template_mode": None,
                "template_index": None,
                "selected_folder": None,
                "logging_enabled": True,
                "alternate_templates": False,
                "account_templates": {},
                "ignore_folders": {},
                "ignore_chats": {},
            "last_updated": datetime.now(timezone.utc).isoformat()
            }
        }
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return {
                    "user_id": str(user_id),
                    "license_type": detect_license_type(user_id),
                    "mailing_parameters": {
                        "selected_accounts": [],
                        "template_mode": None,
                        "template_index": None,
                        "selected_folder": None,
                        "logging_enabled": True,
                        "alternate_templates": False,
                        "account_templates": {},
                        "ignore_folders": {},
                        "ignore_chats": {},
                        "last_updated": datetime.now(timezone.utc).isoformat()
                    }
                }
            return json.loads(content)
    except Exception:
        return {
            "user_id": str(user_id),
            "license_type": detect_license_type(user_id),
            "mailing_parameters": {
                "selected_accounts": [],
                "template_mode": None,
                "template_index": None,
                "selected_folder": None,
                "logging_enabled": True,
                "alternate_templates": False,
                "account_templates": {},
                "ignore_folders": {},
                "ignore_chats": {},
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
        }

def save_mailing_parameters(user_id):
    """Persist current in-memory mailing_states[user_id] to mailing_parameters.json"""
    license_type = user_states.get(f"{user_id}_license_type")
    # Фолбэк-детекция типа лицензии, если ещё не установлен
    if not license_type:
        try:
            license_type = detect_license_type(user_id)
            if license_type:
                user_states[f"{user_id}_license_type"] = license_type
        except Exception:
            license_type = None
    
    state = mailing_states.get(user_id)
    if state is None:
        return
    path = get_mailing_parameters_path(user_id, license_type)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = load_mailing_parameters(user_id)
    mp = data.setdefault("mailing_parameters", {})
    # Map in-memory state to persisted fields
    mp.update({
        "selected_accounts": state.get("selected_accounts", []),
        "template_mode": state.get("template_mode"),
        "template_index": state.get("template_index"),
        "selected_folder": state.get("selected_folder"),
        "logging_enabled": state.get("logging_enabled", True),
        "alternate_templates": state.get("alternate_templates", False),
        "account_templates": state.get("account_templates", {}),
        "ignore_folders": state.get("ignore_folders", {}),
        "ignore_chats": state.get("ignore_chats", {}),
        "folder_set": state.get("folder_set"),
        "template_type": state.get("template_type"),
        "account_folders": state.get("account_folders", {}),
        "step": state.get("step"),
        "last_updated": datetime.now(timezone.utc).isoformat(),
    })
    # Also store optional flags used in flows
    for key in ["summary_enabled", "minimized", "ignore_breaks"]:
        if key in state:
            mp[key] = state.get(key)
    payload = {
        "user_id": str(user_id),
        "license_type": detect_license_type(user_id),
        "mailing_parameters": mp,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

async def ensure_mailing_state(user_id):
    """Ensure mailing_states[user_id] exists; try restoring from mailing_parameters.json.
    Returns True if state exists or restored, False otherwise.
    """
    license_type = user_states.get(f"{user_id}_license_type")
    # НЕ определяем тип лицензии автоматически - это должно происходить только при выборе лицензии
    # if not license_type:
    #     license_type = detect_license_type(user_id)
    #     if license_type:
    #         user_states[f"{user_id}_license_type"] = license_type
    
    if user_id in mailing_states:
        return True
    data = load_mailing_parameters(user_id)
    mp = data.get("mailing_parameters", {}) if isinstance(data, dict) else {}
    if not mp:
        return False
    
    # Специальная обработка для шага "select_alternate_templates"
    # Если пользователь был на этом шаге, нужно показать правильное меню
    step = mp.get("step", "select_accounts")
    original_step = step  # Сохраняем оригинальный шаг
    
    # Если шаг не установлен, но есть template_mode и alternate_templates, 
    # значит пользователь уже выбрал чередование шаблонов
    if step is None and mp.get("template_mode") is not None and "alternate_templates" in mp:
        # Пользователь уже выбрал чередование шаблонов, нужно показать правильное меню
        template_mode = mp.get("template_mode")
        if template_mode == "select":
            # Переходим к выбору типа шаблона
            step = "select_template_type"
        elif template_mode == "custom":
            # Переходим к выбору логирования
            step = "select_logging"
        else:
            # Для других режимов переходим к выбору логирования
            step = "select_logging"
    elif step == "select_alternate_templates":
        # Пользователь был на шаге выбора чередования шаблонов
        # Нужно показать правильное меню в зависимости от template_mode
        template_mode = mp.get("template_mode")
        if template_mode == "select":
            # Переходим к выбору типа шаблона
            step = "select_template_type"
        elif template_mode == "custom":
            # Переходим к выбору логирования
            step = "select_logging"
        else:
            # Для других режимов переходим к выбору логирования
            step = "select_logging"
    
    # Restore subset of state
    mailing_states[user_id] = {
        "step": step,
        "original_step": original_step,  # Сохраняем оригинальный шаг для специальной обработки
        "selected_accounts": mp.get("selected_accounts", []),
        "template_mode": mp.get("template_mode"),
        "template_index": mp.get("template_index"),
        "selected_folder": mp.get("selected_folder"),
        "logging_enabled": mp.get("logging_enabled", True),
        "alternate_templates": mp.get("alternate_templates", False),
        "account_templates": mp.get("account_templates", {}),
        "ignore_folders": mp.get("ignore_folders", {}),
        "ignore_chats": mp.get("ignore_chats", {}),
        "folder_set": mp.get("folder_set"),
        "template_type": mp.get("template_type"),
        "account_folders": mp.get("account_folders", {}),
        "summary_enabled": mp.get("summary_enabled", False),
        "minimized": mp.get("minimized", False),
        "ignore_breaks": mp.get("ignore_breaks", False),
        "resume_state": None,
    }
    
    # Если восстановили состояние с шагом, который требует показа меню,
    # устанавливаем флаг для автоматического показа
    if step in ["select_template_type", "select_logging"]:
        mailing_states[user_id]["needs_menu_display"] = True
    
    return True

def clear_mailing_parameters_file(user_id):
    """Clear the mailing parameters file when mailing is fully stopped/reset."""
    license_type = user_states.get(f"{user_id}_license_type")
    # НЕ определяем тип лицензии автоматически - это должно происходить только при выборе лицензии
    # if not license_type:
    #     license_type = detect_license_type(user_id)
    #     if license_type:
    #         user_states[f"{user_id}_license_type"] = license_type
    
    path = get_mailing_parameters_path(user_id, license_type)
    try:
        if os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump({
                    "user_id": str(user_id),
                    "license_type": detect_license_type(user_id),
                    "mailing_parameters": {
                        "selected_accounts": [],
                        "template_mode": None,
                        "template_index": None,
                        "selected_folder": None,
                        "logging_enabled": True,
                        "alternate_templates": False,
                        "account_templates": {},
                        "ignore_folders": {},
                        "ignore_chats": {},
                        "last_updated": datetime.now(timezone.utc).isoformat()
                    }
                }, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def add_session_to_license(user_id, session_name):
    """Добавляет сессию в license.json или freetrial.json в зависимости от типа лицензии"""
    license_type = user_states.get(f"{user_id}_license_type")
    
    # НЕ определяем тип лицензии автоматически - это должно происходить только при выборе лицензии
    # if not license_type:
    #     license_type = detect_license_type(user_id)
    #     if license_type:
    #         user_states[f"{user_id}_license_type"] = license_type
    
    if license_type == "trial":
        # Для пробного периода добавляем сессию в freetrial.json
        freetrial_data = load_freetrial()
        if str(user_id) in freetrial_data:
            if "sessions" not in freetrial_data[str(user_id)]:
                freetrial_data[str(user_id)]["sessions"] = []
            
            if session_name not in freetrial_data[str(user_id)]["sessions"]:
                freetrial_data[str(user_id)]["sessions"].append(session_name)
                save_freetrial(freetrial_data)
        return
    
    # Для обычных лицензий
    licenses = load_licenses()
    if str(user_id) in licenses:
        sessions = licenses[str(user_id)].setdefault("sessions", [])
        if session_name not in sessions:
            sessions.append(session_name)
        save_licenses(licenses)

def remove_session_from_license(user_id, session_name):
    """Удаляет сессию из license.json или freetrial.json в зависимости от типа лицензии"""
    license_type = user_states.get(f"{user_id}_license_type")
    
    # НЕ определяем тип лицензии автоматически - это должно происходить только при выборе лицензии
    # if not license_type:
    #     license_type = detect_license_type(user_id)
    #     if license_type:
    #         user_states[f"{user_id}_license_type"] = license_type
    
    if license_type == "trial":
        # Для пробного периода удаляем сессию из freetrial.json
        freetrial_data = load_freetrial()
        if str(user_id) in freetrial_data:
            sessions = freetrial_data[str(user_id)].get("sessions", [])
            if session_name in sessions:
                sessions.remove(session_name)
                save_freetrial(freetrial_data)
        return
    
    # Для обычных лицензий
    licenses = load_licenses()
    if str(user_id) in licenses:
        sessions = licenses[str(user_id)].get("sessions", [])
        if session_name in sessions:
            sessions.remove(session_name)
        save_licenses(licenses)
        
def can_add_session(user_id):
    # Сначала определяем тип лицензии
    license_type = user_states.get(f"{user_id}_license_type")
    # НЕ определяем тип лицензии автоматически - это должно происходить только при выборе лицензии
    # if not license_type:
    #     license_type = detect_license_type(user_id)
    #     # Сохраняем определенный тип лицензии для будущего использования
    #     if license_type:
    #         user_states[f"{user_id}_license_type"] = license_type
    
    # Для owner и admin ключей ограничения нет, не проверяем лицензию
    if license_type in ["owner", "admin"]:
        return True, ""
    
    # Для пробного периода проверяем ограничения
    if license_type == "trial":
        if not is_freetrial_valid(user_id):
            return False, "Пробный период истёк."
        
        # Для пробного периода максимум 3 сессии
        freetrial_data = load_freetrial()
        user_data = freetrial_data.get(str(user_id), {})
        sessions = user_data.get("sessions", [])
        if len(sessions) >= get_max_sessions_for_license(user_id):
            return False, "Достигнут лимит сессий для пробного периода (3)."
        
        return True, ""
    
    # Для обычных пользователей проверяем лицензию
    licenses = load_licenses()
    lic = licenses.get(str(user_id))
    if not lic:
        return False, "Лицензия не найдена."
    
    license_code = lic["license_code"]
    # Суммируем все сессии по этому ключу
    total_sessions = 0
    for l in licenses.values():
        if l.get("license_code") == license_code:
            total_sessions += len(l.get("sessions", []))
    max_allowed = get_max_sessions_for_license(user_id)
    if total_sessions >= max_allowed:
        return False, f"Достигнут лимит сессий для вашего ключа ({max_allowed})."
    
    now = int(time.time())
    base_end_ts = lic.get("activated_at", 0) + LICENSE_DURATION_DAYS * 86400
    effective_end_ts = base_end_ts + get_referral_bonus_seconds(user_id)
    if now > effective_end_ts:
        return False, "Срок действия вашей лицензии истёк."
    
    return True, ""

# Функции для работы с шаблонами автоответчика
def get_autoresponder_templates_path(user_id, license_type=None):
    """Получить путь к файлу шаблонов автоответчика"""
    if license_type is None:
        license_type = user_states.get(f"{user_id}_license_type")
        # НЕ определяем тип лицензии автоматически - это должно происходить только при выборе лицензии
        # if not license_type:
        #     license_type = detect_license_type(user_id)
        #     if license_type:
        #         user_states[f"{user_id}_license_type"] = license_type
    
    user_dir = get_user_dir(user_id, license_type, create_dir=False)
    return os.path.join(user_dir, "autoresponder_templates.json")

def load_autoresponder_templates(user_id):
    """Загрузить шаблоны автоответчика для пользователя"""
    license_type = user_states.get(f"{user_id}_license_type")
    # НЕ определяем тип лицензии автоматически - это должно происходить только при выборе лицензии
    # if not license_type:
    #     license_type = detect_license_type(user_id)
    #     if license_type:
    #         user_states[f"{user_id}_license_type"] = license_type
    
    templates_path = get_autoresponder_templates_path(user_id, license_type)
    try:
        if os.path.exists(templates_path):
            with open(templates_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    except Exception:
        return {}

def save_autoresponder_templates(user_id, templates):
    """Сохранить шаблоны автоответчика для пользователя"""
    license_type = user_states.get(f"{user_id}_license_type")
    # НЕ определяем тип лицензии автоматически - это должно происходить только при выборе лицензии
    # if not license_type:
    #     license_type = detect_license_type(user_id)
    #     if license_type:
    #         user_states[f"{user_id}_license_type"] = license_type
    
    templates_path = get_autoresponder_templates_path(user_id, license_type)
    try:
        with open(templates_path, 'w', encoding='utf-8') as f:
            json.dump(templates, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def get_autoresponder_template(user_id, account_phone):
    """Получить шаблон автоответчика для конкретного аккаунта"""
    license_type = user_states.get(f"{user_id}_license_type")
    # НЕ определяем тип лицензии автоматически - это должно происходить только при выборе лицензии
    # if not license_type:
    #     license_type = detect_license_type(user_id)
    #     if license_type:
    #         user_states[f"{user_id}_license_type"] = license_type
    
    templates = load_autoresponder_templates(user_id)
    return templates.get(account_phone, "")

def set_autoresponder_template(user_id, account_phone, template_text):
    """Установить шаблон автоответчика для конкретного аккаунта"""
    license_type = user_states.get(f"{user_id}_license_type")
    # НЕ определяем тип лицензии автоматически - это должно происходить только при выборе лицензии
    # if not license_type:
    #     license_type = detect_license_type(user_id)
    #     if license_type:
    #         user_states[f"{user_id}_license_type"] = license_type
    
    templates = load_autoresponder_templates(user_id)
    templates[account_phone] = template_text
    save_autoresponder_templates(user_id, templates)

def delete_autoresponder_template(user_id, account_phone):
    """Удалить шаблон автоответчика для конкретного аккаунта"""
    license_type = user_states.get(f"{user_id}_license_type")
    # НЕ определяем тип лицензии автоматически - это должно происходить только при выборе лицензии
    # if not license_type:
    #     license_type = detect_license_type(user_id)
    #     if license_type:
    #         user_states[f"{user_id}_license_type"] = license_type
    
    templates = load_autoresponder_templates(user_id)
    if account_phone in templates:
        del templates[account_phone]
        save_autoresponder_templates(user_id, templates)

def has_autoresponder_templates(user_id):
    """Проверить, есть ли у пользователя шаблоны автоответчика"""
    license_type = user_states.get(f"{user_id}_license_type")
    # НЕ определяем тип лицензии автоматически - это должно происходить только при выборе лицензии
    # if not license_type:
    #     license_type = detect_license_type(user_id)
    #     if license_type:
    #         user_states[f"{user_id}_license_type"] = license_type
    
    templates = load_autoresponder_templates(user_id)
    return bool(templates)

def get_active_accounts_by_sessions(user_id):
    """Возвращает список аккаунтов (dict), для которых реально есть .session файл"""
    license_type = user_states.get(f"{user_id}_license_type")
    # НЕ определяем тип лицензии автоматически - это должно происходить только при выборе лицензии
    # if not license_type:
    #     license_type = detect_license_type(user_id)
    #     # Сохраняем определенный тип лицензии для будущего использования
    #     if license_type:
    #         user_states[f"{user_id}_license_type"] = license_type
    
    # Убираем папку "bot" и используем прямую папку sessions
    sessions_dir = os.path.join(get_user_subdir(user_id, "", license_type, create_dir=False), "sessions")
    session_names = set()
    if os.path.exists(sessions_dir):
        for fname in os.listdir(sessions_dir):
            if fname.endswith(".session"):
                session_names.add(fname[:-8])
    
    # Теперь ищем аккаунты из config.json, у которых name совпадает с .session
    accounts = load_user_accounts(user_id)
    active_accounts = []
    for acc in accounts:
        name = acc.get("name")
        if name and name in session_names:
            active_accounts.append(acc)
    return active_accounts

def get_active_sessions(user_id):
    license_type = user_states.get(f"{user_id}_license_type")
    # НЕ определяем тип лицензии автоматически - это должно происходить только при выборе лицензии
    # if not license_type:
    #     license_type = detect_license_type(user_id)
    #         # Сохраняем определенный тип лицензии для будущего использования
    #         if license_type:
    #             user_states[f"{user_id}_license_type"] = license_type
    
    # Убираем папку "bot" и используем прямую папку sessions
    sessions_dir = os.path.join(get_user_subdir(user_id, "", license_type, create_dir=False), "sessions")
    result = []
    if os.path.exists(sessions_dir):
        for fname in os.listdir(sessions_dir):
            if fname.endswith(".session"):
                name = fname[:-8]  # убираем .session
                result.append(name)
    return result

def get_sessions_count(user_id):
    license_type = user_states.get(f"{user_id}_license_type")
    # Определяем тип лицензии только для owner и admin - это критично для правильного отображения
    if not license_type:
        license_type = detect_license_type(user_id)
        if license_type in ["owner", "admin"]:
            user_states[f"{user_id}_license_type"] = license_type
    
    if license_type in ["owner", "admin"]:
        return len(load_user_accounts(user_id))
    
    # Для пробного периода считаем по freetrial.json
    if license_type == "trial":
        # Перед подсчётом пытаемся привести freetrial в консистентное состояние
        try:
            reconcile_freetrial_sessions(user_id)
        except Exception:
            pass
        freetrial_data = load_freetrial()
        user_data = freetrial_data.get(str(user_id), {})
        return len(user_data.get("sessions", []))
    
    # Для pro/premium/basic считаем по license.json по ключу
    licenses = load_licenses()
    lic = licenses.get(str(user_id))
    if not lic:
        return 0
    license_code = lic.get("license_code")
    total_sessions = 0
    for l in licenses.values():
        if l.get("license_code") == license_code:
            total_sessions += len(l.get("sessions", []))
    return total_sessions

def load_user_accounts(user_id):
    license_type = user_states.get(f"{user_id}_license_type")
    # Определяем тип лицензии если он не установлен
    if not license_type:
        license_type = detect_license_type(user_id)
        if license_type:
            user_states[f"{user_id}_license_type"] = license_type
    
    user_dir = get_user_dir(user_id, license_type, create_dir=False)
    config_path = os.path.join(user_dir, "config.json")
    if not os.path.exists(config_path):
        #print(f"🔍 [LOAD_USER_ACCOUNTS] Файл config.json не найден: {config_path}")
        return []
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        accounts = config.get("accounts", [])
        #print(f"🔍 [LOAD_USER_ACCOUNTS] Загружено {len(accounts)} аккаунтов из config.json для пользователя {user_id}")
        
        # Фильтруем пустые аккаунты!
        filtered_accounts = [acc for acc in accounts if acc and acc.get("phone")]
        #print(f"🔍 [LOAD_USER_ACCOUNTS] После фильтрации: {len(filtered_accounts)} аккаунтов")
        
        return filtered_accounts
    except Exception as e:
        #print(f"🔍 [LOAD_USER_ACCOUNTS] Ошибка загрузки аккаунтов для пользователя {user_id}: {e}")
        return []

def save_user_accounts(user_id, accounts):
    license_type = user_states.get(f"{user_id}_license_type")
    # НЕ определяем тип лицензии автоматически - это должно происходить только при выборе лицензии
    # if not license_type:
    #     license_type = detect_license_type(user_id)
    #     # Сохраняем определенный тип лицензии для будущего использования
    #     if license_type:
    #         user_states[f"{user_id}_license_type"] = license_type
    
    user_dir = get_user_dir(user_id, license_type, create_dir=True)
    config_path = os.path.join(user_dir, "config.json")
    config = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception:
            config = {}
    config["accounts"] = accounts
    # --- добавлено ---
    if accounts and "api_id" in accounts[0] and "api_hash" in accounts[0]:
        config["api_id"] = accounts[0]["api_id"]
        config["api_hash"] = accounts[0]["api_hash"]
    # --- конец ---
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    
    # Обновляем информацию об аккаунтах в логах
    update_user_accounts_info(user_id)

def load_user_stats(user_id):
    """Загружает статистику пользователя из count.json"""
    try:
        license_type = detect_license_type(user_id)
        user_dir = get_user_dir(user_id, license_type, create_dir=True)
        stats_path = os.path.join(user_dir, "count.json")
        
        if os.path.exists(stats_path):
            with open(stats_path, "r", encoding="utf-8") as f:
                return json.load(f)
        else:
            # Создаем файл с начальными значениями
            initial_stats = {
                "sent_messages": 0,  # Отправлено сообщений из рассылки
                "received_messages": 0,  # Получено входящих сообщений из почты
                "autoresponder_messages": 0,  # Отправлено автоответчиком
                "last_updated": int(time.time())
            }
            save_user_stats(user_id, initial_stats)
            return initial_stats
    except Exception as e:
        print(f"❌ Ошибка загрузки статистики для пользователя {user_id}: {e}")
        return {
            "sent_messages": 0,
            "received_messages": 0,
            "autoresponder_messages": 0,
            "last_updated": int(time.time())
        }

def save_user_stats(user_id, stats):
    """Сохраняет статистику пользователя в count.json"""
    try:
        license_type = detect_license_type(user_id)
        user_dir = get_user_dir(user_id, license_type, create_dir=True)
        stats_path = os.path.join(user_dir, "count.json")
        
        stats["last_updated"] = int(time.time())
        
        with open(stats_path, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ Ошибка сохранения статистики для пользователя {user_id}: {e}")

def increment_user_stat(user_id, stat_type, increment=1):
    """Увеличивает значение статистики пользователя"""
    try:
        stats = load_user_stats(user_id)
        old_value = stats.get(stat_type, 0)
        
        if stat_type == "sent_messages":
            stats["sent_messages"] += increment
        elif stat_type == "received_messages":
            stats["received_messages"] += increment
        elif stat_type == "autoresponder_messages":
            stats["autoresponder_messages"] += increment
        
        save_user_stats(user_id, stats)
        print(f"📊 Статистика обновлена: {stat_type} {old_value} → {stats[stat_type]} (user_id: {user_id})")
    except Exception as e:
        print(f"❌ Ошибка обновления статистики {stat_type} для пользователя {user_id}: {e}")

def calculate_saved_time_and_money(user_id):
    """Рассчитывает сэкономленное время и деньги на основе статистики"""
    try:
        stats = load_user_stats(user_id)
        accounts = load_user_accounts(user_id)
        num_accounts = len(accounts) if accounts else 1
        
        # Формула для времени: 1 сообщение = 10 секунд
        total_messages = stats["sent_messages"]
        time_per_message = 10  # секунд
        
        # Простое умножение: общее количество сообщений × 10 секунд
        total_time_seconds = total_messages * time_per_message
        
        # Переводим в часы и минуты
        total_hours = total_time_seconds // 3600
        total_minutes = (total_time_seconds % 3600) // 60
        
        # Формула для денег: 1 сообщение = $0.02
        cost_per_message = 0.02
        total_money = total_messages * cost_per_message
        
        return {
            "saved_time_hours": total_hours,
            "saved_time_minutes": total_minutes,
            "saved_money": round(total_money, 1)
        }
    except Exception as e:
        print(f"❌ Ошибка расчета экономии для пользователя {user_id}: {e}")
        return {
            "saved_time_hours": 0,
            "saved_time_minutes": 0,
            "saved_money": 0.0
        }

def get_user_stats_display(user_id):
    """Возвращает отформатированную строку статистики для отображения"""
    try:
        stats = load_user_stats(user_id)
        savings = calculate_saved_time_and_money(user_id)
        
        stats_text = f"""📊 Статистика:

• Отправлено сообщений: {stats['sent_messages']}

• Получено входящих сообщений: {stats['received_messages']}

• Отправлено автоответчиком сообщений: {stats['autoresponder_messages']}

• Сэкономлено времени: {savings['saved_time_hours']} ч {savings['saved_time_minutes']} мин

• Сэкономлено денег: {savings['saved_money']}$"""
        
        return stats_text
    except Exception as e:
        print(f"❌ Ошибка формирования статистики для пользователя {user_id}: {e}")
        return "📊 Статистика:\n\nОшибка загрузки статистики"

# ==================== ФУНКЦИИ ДЛЯ РАБОТЫ С ЛОГИРОВАНИЕМ ====================

def load_logs_data():
    """Загружает данные логирования из logs.json"""
    try:
        logs_path = os.path.join(PROJECT_ROOT, "logs.json")
        if os.path.exists(logs_path):
            with open(logs_path, "r", encoding="utf-8") as f:
                return json.load(f)
        else:
            # Создаем файл с пустой структурой
            initial_logs = {}
            save_logs_data(initial_logs)
            return initial_logs
    except Exception as e:
        print(f"❌ Ошибка загрузки logs.json: {e}")
        return {}

def save_logs_data(logs_data):
    """Сохраняет данные логирования в logs.json"""
    try:
        logs_path = os.path.join(PROJECT_ROOT, "logs.json")
        with open(logs_path, "w", encoding="utf-8") as f:
            json.dump(logs_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ Ошибка сохранения logs.json: {e}")

def _format_now_without_tz() -> str:
    """Возвращает текущую дату/время в формате 'DD.MM.YYYY, HH:MM' (без часового пояса)."""
    try:
        return datetime.now().strftime("%d.%m.%Y, %H:%M")
    except Exception:
        return datetime.now().strftime("%d.%m.%Y, %H:%M")

def _format_now_with_gmt() -> str:
    """Возвращает текущую дату/время в формате 'DD.MM.YYYY, HH:MM GMT+X'."""
    try:
        local_dt = datetime.now().astimezone()
        tz_offset = local_dt.utcoffset() or None
        hours = int(tz_offset.total_seconds() // 3600) if tz_offset else 0
        gmt_part = f"GMT{hours:+d}"
        return f"{local_dt.strftime('%d.%m.%Y, %H:%M')} {gmt_part}"
    except Exception:
        # Фолбэк без TZ
        return datetime.now().strftime("%d.%m.%Y, %H:%M")

def _format_ts_with_gmt(timestamp: int) -> str:
    """Возвращает дату/время указанного timestamp в формате 'DD.MM.YYYY, HH:MM GMT+X'."""
    try:
        local_dt = datetime.fromtimestamp(int(timestamp)).astimezone()
        tz_offset = local_dt.utcoffset() or None
        hours = int(tz_offset.total_seconds() // 3600) if tz_offset else 0
        gmt_part = f"GMT{hours:+d}"
        return f"{local_dt.strftime('%d.%m.%Y, %H:%M')} {gmt_part}"
    except Exception:
        return _format_now_with_gmt()

def get_or_create_user_logs(user_id):
    """Получает или создает структуру логов для пользователя"""
    logs_data = load_logs_data()
    user_id_str = str(user_id)
    
    if user_id_str not in logs_data:
        # Создаем новую структуру для пользователя
        logs_data[user_id_str] = {
            "MAIN_INFO": {
                "registration": _format_now_without_tz(),
                "language": "",
                "freetrial": 0,
                "referral": "",
                "license_type": "",
                "license_key": "",
                "accounts_id": [],
                "accounts_usernames": [],
                "accounts_phone_numbers": []
            },
            "MAILING_INFO": {
                "mailing_launched_times": 0,
                "messages_sent_total": 0
            },
            "MAILBOX_INFO": {
                "mailbox_launched_times": 0,
                "messages_received_total": 0
            },
            "AUTORESPONDER_INFO": {
                "autoresponder_launched_times": 0,
                "messages_total_responded": 0
            },
            "CLICKED": {}
        }
        save_logs_data(logs_data)
    
    return logs_data[user_id_str]

def update_user_main_info(user_id, **kwargs):
    """Обновляет основную информацию пользователя в логах"""
    try:
        logs_data = load_logs_data()
        user_id_str = str(user_id)
        
        if user_id_str not in logs_data:
            get_or_create_user_logs(user_id)
        
        for key, value in kwargs.items():
            if key in logs_data[user_id_str]["MAIN_INFO"]:
                logs_data[user_id_str]["MAIN_INFO"][key] = value
        
        save_logs_data(logs_data)
    except Exception as e:
        print(f"❌ Ошибка обновления основной информации для пользователя {user_id}: {e}")

def log_button_click(user_id, button_name):
    """Логирует нажатие кнопки пользователем"""
    try:
        logs_data = load_logs_data()
        user_id_str = str(user_id)
        
        if user_id_str not in logs_data:
            get_or_create_user_logs(user_id)
        
        if "CLICKED" not in logs_data[user_id_str]:
            logs_data[user_id_str]["CLICKED"] = {}
        
        if button_name not in logs_data[user_id_str]["CLICKED"]:
            logs_data[user_id_str]["CLICKED"][button_name] = 0
        
        logs_data[user_id_str]["CLICKED"][button_name] += 1
        save_logs_data(logs_data)
    except Exception as e:
        print(f"❌ Ошибка логирования нажатия кнопки {button_name} для пользователя {user_id}: {e}")

def log_mailing_activity(user_id, action_type, **kwargs):
    """Логирует активность рассылки"""
    try:
        logs_data = load_logs_data()
        user_id_str = str(user_id)
        
        if user_id_str not in logs_data:
            get_or_create_user_logs(user_id)
        
        if action_type == "launch":
            logs_data[user_id_str]["MAILING_INFO"]["mailing_launched_times"] += 1
        elif action_type == "message_sent":
            increment = kwargs.get("increment", 1)
            logs_data[user_id_str]["MAILING_INFO"]["messages_sent_total"] += increment
        elif action_type == "add_chat":
            chat = kwargs.get("chat")
            if chat and chat not in logs_data[user_id_str]["MAILING_INFO"]["chats"]:
                logs_data[user_id_str]["MAILING_INFO"]["chats"].append(chat)

        
        save_logs_data(logs_data)
    except Exception as e:
        print(f"❌ Ошибка логирования активности рассылки для пользователя {user_id}: {e}")

def log_mailbox_activity(user_id, action_type, **kwargs):
    """Логирует активность почты"""
    try:
        logs_data = load_logs_data()
        user_id_str = str(user_id)
        
        if user_id_str not in logs_data:
            get_or_create_user_logs(user_id)
        
        if action_type == "launch":
            logs_data[user_id_str]["MAILBOX_INFO"]["mailbox_launched_times"] += 1
        elif action_type == "message_received":
            increment = kwargs.get("increment", 1)
            logs_data[user_id_str]["MAILBOX_INFO"]["messages_received_total"] += increment
        
        save_logs_data(logs_data)
    except Exception as e:
        print(f"❌ Ошибка логирования активности почты для пользователя {user_id}: {e}")

def log_autoresponder_activity(user_id, action_type, **kwargs):
    """Логирует активность автоответчика"""
    try:
        logs_data = load_logs_data()
        user_id_str = str(user_id)
        
        if user_id_str not in logs_data:
            get_or_create_user_logs(user_id)
        
        if action_type == "launch":
            logs_data[user_id_str]["AUTORESPONDER_INFO"]["autoresponder_launched_times"] += 1
        elif action_type == "message_responded":
            increment = kwargs.get("increment", 1)
            logs_data[user_id_str]["AUTORESPONDER_INFO"]["messages_total_responded"] += increment

        
        save_logs_data(logs_data)
    except Exception as e:
        print(f"❌ Ошибка логирования активности автоответчика для пользователя {user_id}: {e}")

def update_user_accounts_info(user_id):
    """Обновляет информацию об аккаунтах пользователя в логах"""
    try:
        accounts = load_user_accounts(user_id)
        print(f"🔍 [UPDATE_ACCOUNTS_INFO] Загружено {len(accounts) if accounts else 0} аккаунтов для пользователя {user_id}")
        
        if not accounts:
            print(f"🔍 [UPDATE_ACCOUNTS_INFO] Нет аккаунтов для пользователя {user_id}, пропускаем обновление")
            return
        
        accounts_id = []
        accounts_usernames = []
        accounts_phone_numbers = []
        
        for account in accounts:
            if account.get("phone"):
                accounts_phone_numbers.append(account["phone"])
            if account.get("user_id"):
                accounts_id.append(str(account["user_id"]))
            if account.get("username"):
                accounts_usernames.append(f"@{account['username']}")
        
        print(f"🔍 [UPDATE_ACCOUNTS_INFO] Подготовлены данные для logs.json: {len(accounts_id)} ID, {len(accounts_usernames)} username, {len(accounts_phone_numbers)} phone")
        
        update_user_main_info(
            user_id,
            accounts_id=accounts_id,
            accounts_usernames=accounts_usernames,
            accounts_phone_numbers=accounts_phone_numbers
        )
        
        print(f"🔍 [UPDATE_ACCOUNTS_INFO] Данные обновлены в logs.json для пользователя {user_id}")
    except Exception as e:
        print(f"❌ Ошибка обновления информации об аккаунтах для пользователя {user_id}: {e}")

def update_user_account_info_in_logs(user_id, name, phone, username, user_id_telegram):
    """Сразу сохраняет информацию о новом аккаунте в logs.json"""
    try:
        logs_data = load_logs_data()
        user_id_str = str(user_id)
        
        if user_id_str not in logs_data:
            # Создаем новую структуру для пользователя
            logs_data[user_id_str] = {
                "MAIN_INFO": {
                    "registration": _format_now_without_tz(),
                    "language": "",
                    "freetrial": 0,
                    "referral": "",
                    "license_type": "",
                    "license_key": "",
                    "accounts_id": [],
                    "accounts_usernames": [],
                    "accounts_phone_numbers": []
                },
                "MAILING_INFO": {
                    "mailing_launched_times": 0,
                    "messages_sent_total": 0
                },
                "MAILBOX_INFO": {
                    "mailbox_launched_times": 0,
                    "messages_received_total": 0
                },
                "AUTORESPONDER_INFO": {
                    "autoresponder_launched_times": 0,
                    "messages_total_responded": 0
                },
                "CLICKED": {}
            }
        
        # Добавляем информацию о новом аккаунте
        if user_id_telegram:
            logs_data[user_id_str]["MAIN_INFO"]["accounts_id"].append(str(user_id_telegram))
        if username:
            logs_data[user_id_str]["MAIN_INFO"]["accounts_usernames"].append(f"@{username}")
        if phone:
            logs_data[user_id_str]["MAIN_INFO"]["accounts_phone_numbers"].append(phone)
        
        save_logs_data(logs_data)
        print(f"✅ Добавлена информация об аккаунте для пользователя {user_id}: {name} ({phone})")
    except Exception as e:
        print(f"❌ Ошибка добавления информации об аккаунте для пользователя {user_id}: {e}")

def get_user_analytics(user_id):
    """Возвращает аналитику пользователя на основе логов"""
    try:
        logs_data = load_logs_data()
        user_id_str = str(user_id)
        
        if user_id_str not in logs_data:
            return None
        
        user_logs = logs_data[user_id_str]
        
        # Анализируем активность
        total_clicks = sum(user_logs.get("CLICKED", {}).values())
        most_clicked_button = max(user_logs.get("CLICKED", {}).items(), key=lambda x: x[1]) if user_logs.get("CLICKED") else None
        
        # Анализируем рассылку
        mailing_launches = user_logs.get("MAILING_INFO", {}).get("mailing_launched_times", 0)
        messages_sent = user_logs.get("MAILING_INFO", {}).get("messages_sent_total", 0)
        
        # Анализируем почту
        mailbox_launches = user_logs.get("MAILBOX_INFO", {}).get("mailbox_launched_times", 0)
        messages_received = user_logs.get("MAILBOX_INFO", {}).get("messages_received_total", 0)
        
        # Анализируем автоответчик
        autoresponder_launches = user_logs.get("AUTORESPONDER_INFO", {}).get("autoresponder_launched_times", 0)
        messages_responded = user_logs.get("AUTORESPONDER_INFO", {}).get("messages_total_responded", 0)
        
        return {
            "total_clicks": total_clicks,
            "most_clicked_button": most_clicked_button,
            "mailing_activity": {
                "launches": mailing_launches,
                "messages_sent": messages_sent,
                "avg_messages_per_launch": messages_sent / mailing_launches if mailing_launches > 0 else 0
            },
            "mailbox_activity": {
                "launches": mailbox_launches,
                "messages_received": messages_received,
                "avg_messages_per_launch": messages_received / mailbox_launches if mailbox_launches > 0 else 0
            },
            "autoresponder_activity": {
                "launches": autoresponder_launches,
                "messages_responded": messages_responded,
                "avg_messages_per_launch": messages_responded / autoresponder_launches if autoresponder_launches > 0 else 0
            }
        }
    except Exception as e:
        print(f"❌ Ошибка получения аналитики для пользователя {user_id}: {e}")
        return None

def get_project_root():
    return os.path.dirname(os.path.abspath(__file__))

def get_user_dir(user_id, license_type=None, create_dir=False):
    if user_id is None:
        raise ValueError("user_id не должен быть None!")
    
    if license_type is None:
        license_type = user_states.get(f"{user_id}_license_type")
        # Автоматически определяем тип лицензии по существующим папкам, если пользователь авторизован
        if not license_type and user_states.get(user_id) == "authorized":
            license_type = detect_license_type(user_id)
            if license_type:
                user_states[f"{user_id}_license_type"] = license_type
    
    root = get_project_root()
    if license_type == "owner":
        candidate = os.path.join(root, "owner")
    elif license_type == "trial":
        base_dir = os.path.join(root, "user")
        candidate = os.path.join(base_dir, f"{user_id}_trial")
    elif license_type == "admin":
        base_dir = os.path.join(root, "user")
        candidate = os.path.join(base_dir, f"{user_id}_admin")
    elif license_type == "pro":
        base_dir = os.path.join(root, "user")
        candidate = os.path.join(base_dir, f"{user_id}_pro")
    elif license_type == "premium":
        base_dir = os.path.join(root, "user")
        candidate = os.path.join(base_dir, f"{user_id}_premium")
    elif license_type == "basic":
        base_dir = os.path.join(root, "user")
        candidate = os.path.join(base_dir, f"{user_id}_basic")
    else:
        # Если тип лицензии не определен (None), не создаем plain, если уже есть суффиксная папка
        base_dir = os.path.join(root, "user")
        if os.path.isdir(os.path.join(base_dir, f"{user_id}_owner")):
            candidate = os.path.join(base_dir, f"{user_id}_owner")
        elif os.path.isdir(os.path.join(base_dir, f"{user_id}_admin")):
            candidate = os.path.join(base_dir, f"{user_id}_admin")
        elif os.path.isdir(os.path.join(base_dir, f"{user_id}_pro")):
            candidate = os.path.join(base_dir, f"{user_id}_pro")
        elif os.path.isdir(os.path.join(base_dir, f"{user_id}_premium")):
            candidate = os.path.join(base_dir, f"{user_id}_premium")
        elif os.path.isdir(os.path.join(base_dir, f"{user_id}_basic")):
            candidate = os.path.join(base_dir, f"{user_id}_basic")
        elif os.path.isdir(os.path.join(base_dir, f"{user_id}_trial")):
            candidate = os.path.join(base_dir, f"{user_id}_trial")
        else:
            # Только если нет ни одной суффиксной, используем plain
            candidate = os.path.join(base_dir, str(user_id))
    
    # Миграция со старого суффикса _user на _basic
    try:
        if license_type == "basic":
            legacy_dir = os.path.join(base_dir, f"{user_id}_user")
            if os.path.exists(legacy_dir) and not os.path.exists(candidate):
                os.rename(legacy_dir, candidate)
    except Exception as _:
        pass
    
    # Создаем папку только если явно запрошено или пользователь авторизован
    # ВАЖНО: нессуффиксные папки (license_type is None) создаем только при явном флаге force
    allow_plain_create = bool(user_states.get(f"{user_id}_force_plain_create"))
    if (create_dir or user_states.get(user_id) == "authorized"):
        if license_type is None and not allow_plain_create:
            # Не создавать нессуффиксную папку без явного флага
            pass
        else:
            os.makedirs(candidate, exist_ok=True)
    
    return candidate

def get_user_subdir(user_id, subdir, license_type=None, create_dir=False):

    if license_type is None:
        license_type = user_states.get(f"{user_id}_license_type")
        # Автоматически определяем тип лицензии по существующим папкам, если пользователь авторизован
        if not license_type and user_states.get(user_id) == "authorized":
            license_type = detect_license_type(user_id)
            if license_type:
                user_states[f"{user_id}_license_type"] = license_type

    user_dir = get_user_dir(user_id, license_type, create_dir)
    
    # Убираем папку "bot" и создаем сразу папку "sessions"
    if subdir == "bot":
        path = user_dir  # Используем корневую папку пользователя
    else:
        path = os.path.join(user_dir, subdir)
    
    # Создаем папки только если явно запрошено или пользователь авторизован
    if create_dir or user_states.get(user_id) == "authorized":
        os.makedirs(os.path.join(path, "sessions"), exist_ok=True)
    
    return path

def get_session_path(user_id, subdir, session_name, license_type=None):
    """Путь к .session файлу в подпапке"""
    if license_type is None:
        license_type = user_states.get(f"{user_id}_license_type")
        # Автоматически определяем тип лицензии по существующим папкам, если пользователь авторизован
        if not license_type and user_states.get(user_id) == "authorized":
            license_type = detect_license_type(user_id)
            if license_type:
                user_states[f"{user_id}_license_type"] = license_type
    
    # Убираем папку "bot" и создаем сразу папку "sessions"
    if subdir == "bot":
        return os.path.join(get_user_subdir(user_id, "", license_type, create_dir=False), "sessions", f"{session_name}.session")
    else:
        return os.path.join(get_user_subdir(user_id, subdir, license_type, create_dir=False), "sessions", f"{session_name}.session")

def remove_session_from_all_subdirs(user_id, session_name, license_type=None):
    """Удаляет .session файл и .session-journal файл из sessions"""
    if license_type is None:
        license_type = user_states.get(f"{user_id}_license_type")
        # Автоматически определяем тип лицензии по существующим папкам, если пользователь авторизован
        if not license_type and user_states.get(user_id) == "authorized":
            license_type = detect_license_type(user_id)
            if license_type:
                user_states[f"{user_id}_license_type"] = license_type
    
    # Убираем папку "bot" и используем пустую строку для прямого доступа к sessions
    session_path = get_session_path(user_id, "bot", session_name, license_type)
    journal_path = session_path.replace('.session', '.session-journal')
    wal_path = session_path + "-wal"
    shm_path = session_path + "-shm"
    
    # Удаляем .session файл
    if os.path.exists(session_path):
        try:
            os.remove(session_path)
            print(f"✅ Удален .session файл: {session_path}")
        except Exception as e:
            print(f"❌ Ошибка удаления {session_path}: {e}")
    
    # Удаляем .session-journal файл (важно для освобождения блокировки SQLite)
    if os.path.exists(journal_path):
        try:
            os.remove(journal_path)
            print(f"✅ Удален .session-journal файл: {journal_path}")
        except Exception as e:
            print(f"❌ Ошибка удаления {journal_path}: {e}")
    # Удаляем SQLite доп. файлы
    for extra in (wal_path, shm_path):
        if os.path.exists(extra):
            try:
                os.remove(extra)
                print(f"✅ Удален файл: {extra}")
            except Exception as e:
                print(f"❌ Ошибка удаления {extra}: {e}")
    
    # Также удаляем сессию из соответствующего файла (license.json или freetrial.json)
    remove_session_from_license(user_id, session_name)

def ensure_session_permissions(session_path: str):
    """Гарантирует права на запись для файла .session, его журналов и каталога."""
    try:
        if not session_path:
            return
        sessions_dir = os.path.dirname(session_path)
        try:
            if sessions_dir and os.path.exists(sessions_dir):
                os.chmod(sessions_dir, 0o700)
        except Exception:
            pass
        targets = [
            session_path,
            session_path.replace('.session', '.session-journal'),
            session_path + '-wal',
            session_path + '-shm',
        ]
        for path in targets:
            try:
                if path and os.path.exists(path):
                    os.chmod(path, 0o600)
            except Exception:
                pass
    except Exception:
        pass

def detect_license_type(user_id):
    """Определяет тип лицензии по существующим папкам пользователя и по ключу в license.json."""
    # Сначала проверяем сохраненный тип лицензии
    saved_license_type = user_states.get(f"{user_id}_license_type")
    if saved_license_type:
        # Если это trial, убедимся что он ещё действителен
        if saved_license_type == "trial" and not is_freetrial_valid(user_id):
            # Просроченный trial — не возвращаем его как активный тип
            pass
        else:
            return saved_license_type
    
    # Проверяем owner только если user_id == "owner" или 0
    if str(user_id) in ["owner", "0"]:
        root = get_project_root()
        if os.path.exists(os.path.join(root, "owner")):
            return "owner"
    
    # Проверяем существующие папки пользователя для определения типа лицензии
    root = get_project_root()
    user_base_dir = os.path.join(root, "user")
    
    # Проверяем папки с суффиксами
    if os.path.exists(os.path.join(user_base_dir, f"{user_id}_owner")):
        return "owner"
    if os.path.exists(os.path.join(user_base_dir, f"{user_id}_admin")):
        return "admin"
    if os.path.exists(os.path.join(user_base_dir, f"{user_id}_pro")):
        return "pro"
    if os.path.exists(os.path.join(user_base_dir, f"{user_id}_premium")):
        return "premium"
    if os.path.exists(os.path.join(user_base_dir, f"{user_id}_basic")):
        return "basic"
    if os.path.exists(os.path.join(user_base_dir, f"{user_id}_trial")):
        return "trial"
    
    # Проверяем license.json для определения типа по ключу ПЕРЕД проверкой пробного периода
    licenses = load_licenses()
    lic = licenses.get(str(user_id))
    if lic:
        # Если авторизация отключена — не подтягиваем тип из license.json
        if lic.get("authorized") is False:
            pass
        else:
            license_code = lic.get("license_code")
            groups = load_key_groups()
            if license_code == "andromedasysmode" or license_code in groups.get("owner", []):
                return "owner"
            if license_code == "andromedamodeadmin" or license_code in groups.get("admin", []):
                return "admin"
            if license_code in groups.get("pro", []):
                return "pro"
            if license_code in groups.get("premium", []):
                return "premium"
            if license_code in groups.get("basic", []):
                return "basic"
    
    # Проверяем пробный период ТОЛЬКО если нет лицензии
    if is_freetrial_valid(user_id):
        return "trial"
    
    # По умолчанию возвращаем None - папка еще не создана
    return None

def migrate_user_folder_if_needed(user_id):
    """Мигрирует папку пользователя без суффикса в папку с правильным суффиксом, если это необходимо."""
    root = get_project_root()
    user_base_dir = os.path.join(root, "user")
    
    # Проверяем, существует ли папка без суффикса
    old_folder = os.path.join(user_base_dir, str(user_id))
    if not os.path.exists(old_folder):
        return
    
    # Определяем правильный тип лицензии
    license_type = detect_license_type(user_id)
    if not license_type:
        return
    
    # Проверяем, существует ли уже правильная папка
    new_folder = os.path.join(user_base_dir, f"{user_id}_{license_type}")
    if os.path.exists(new_folder):
        # Если новая папка уже существует, удаляем старую
        try:
            shutil.rmtree(old_folder)
            print(f"✅ Удалена старая папка {old_folder} (уже существует {new_folder})")
        except Exception as e:
            print(f"❌ Ошибка удаления старой папки {old_folder}: {e}")
        return
    
    # Переименовываем папку
    try:
        os.rename(old_folder, new_folder)
        print(f"✅ Мигрирована папка пользователя {user_id}: {old_folder} -> {new_folder}")
    except Exception as e:
        print(f"❌ Ошибка миграции папки пользователя {user_id}: {e}")

def cleanup_orphaned_folders():
    """Очищает пустые папки без суффикса, которые могли остаться после миграции."""
    root = get_project_root()
    user_base_dir = os.path.join(root, "user")
    
    if not os.path.exists(user_base_dir):
        return
    
    cleaned_count = 0
    for item in os.listdir(user_base_dir):
        # Проверяем папки без суффикса (только цифры)
        if item.isdigit():
            folder_path = os.path.join(user_base_dir, item)
            try:
                # Проверяем, пуста ли папка
                if os.path.isdir(folder_path) and not os.listdir(folder_path):
                    os.rmdir(folder_path)
                    print(f"✅ Удалена пустая папка: {folder_path}")
                    cleaned_count += 1
            except Exception as e:
                print(f"❌ Ошибка удаления пустой папки {folder_path}: {e}")
    
    if cleaned_count > 0:
        print(f"🧹 Очищено {cleaned_count} пустых папок")


def safe_rmtree(path: str):
    """Безопасное удаление каталога с попыткой исправить права и повторить удаление."""
    try:
        if not path or not os.path.exists(path):
            return
        def _on_rm_error(func, p, exc_info):
            try:
                if os.path.isdir(p):
                    os.chmod(p, 0o700)
                else:
                    os.chmod(p, 0o600)
                func(p)
            except Exception:
                pass
        shutil.rmtree(path, onerror=_on_rm_error)
    except Exception as e:
        print(f"❌ Ошибка безопасного удаления каталога {path}: {e}")

def delete_all_user_dirs(user_id):
    """Удаляет все варианты папок пользователя: без суффикса и c суффиксами (_trial, _basic, _premium, _pro, _admin, _user)."""
    try:
        root = get_project_root()
        user_base_dir = os.path.join(root, "user")
        candidates = [
            str(user_id),
            f"{user_id}_trial",
            f"{user_id}_basic",
            f"{user_id}_premium",
            f"{user_id}_pro",
            f"{user_id}_admin",
            f"{user_id}_user",
        ]
        deleted = []
        for name in candidates:
            path = os.path.join(user_base_dir, name)
            if os.path.exists(path):
                safe_rmtree(path)
                deleted.append(path)
        if deleted:
            print(f"🗑️ Удалены папки пользователя {user_id}: {deleted}")
        else:
            print(f"ℹ️ Папки пользователя {user_id} для удаления не найдены")
    except Exception as e:
        print(f"❌ Ошибка удаления папок пользователя {user_id}: {e}")



def is_license_valid(user_id):
    # Сначала проверяем сохраненный тип лицензии
    license_type = user_states.get(f"{user_id}_license_type")
    if license_type in ["owner", "admin"]:
        return True
    
    # Если нет сохраненного типа, определяем его
    if not license_type:
        license_type = detect_license_type(user_id)
        if license_type in ["owner", "admin"]:
            # Сохраняем определенный тип лицензии
            user_states[f"{user_id}_license_type"] = license_type
            return True
    
    # Проверяем пробный период
    # Если trial активен по времени — доступ есть независимо от сохранённого типа
    if is_freetrial_valid(user_id):
        return True
    # Если сохранён trial, но он уже истёк — доступ запрещён
    if license_type == "trial":
        return False
    
    # Для обычных лицензий (pro/premium/basic) проверяем лицензию
    licenses = load_licenses()
    lic = licenses.get(str(user_id))
    if not lic:
        return False
    # Если явно указан authorized=false — доступ запрещен до повторной авторизации
    if lic.get("authorized") is False:
        return False
    
    groups = load_key_groups()
    license_code = lic.get("license_code")
    # Разрешены только pro/premium/basic
    if license_code not in set(groups.get("pro", []) + groups.get("premium", []) + groups.get("basic", [])):
        return False
    
    # Проверяем срок действия с учетом бонуса реферала
    now = int(time.time())
    base_end_ts = lic.get("activated_at", 0) + LICENSE_DURATION_DAYS * 86400
    effective_end_ts = base_end_ts + get_referral_bonus_seconds(user_id)
    if now > effective_end_ts:
        return False
    
    return True


# ==================== ДОБАВЛЕНО: Централизованная обработка истечения доступа ====================
async def handle_access_expired(user_id: int, reason: str | None = None):
    """Останавливает все активные сервисы пользователя и возвращает его в стартовое меню.

    reason: "trial" или "license" для выбора текста уведомления. Если None, определяется автоматически.
    """
    try:
        # Определяем причину, если не передана
        if reason is None:
            try:
                licenses = load_licenses()
            except Exception:
                licenses = {}
            try:
                ft = load_freetrial()
            except Exception:
                ft = {}
            if str(user_id) in licenses and not is_license_valid(user_id):
                reason = "license"
            elif str(user_id) in ft and not is_freetrial_valid(user_id):
                reason = "trial"
            else:
                reason = "license"

        # Сообщение пользователю
        if reason == "trial":
            notify_text = "Пробный период закончился. Ваши активные сервисы остановлены."
        else:
            notify_text = "Подписка закончилась. Ваши активные сервисы остановлены."

        # 1) Останавливаем все активные задачи пользователя
        try:
            if user_id in active_tasks:
                for task_name in list(active_tasks[user_id].keys()):
                    try:
                        await stop_task(user_id, task_name)
                    except Exception:
                        pass
        except Exception:
            pass

        # 2) Останавливаем mailboxer (если запущен)
        try:
            mailboxer = user_sessions.get(user_id, {}).get("mailboxer")
            if mailboxer:
                if "stop_event" in mailboxer and mailboxer["stop_event"]:
                    try:
                        mailboxer["stop_event"].set()
                    except Exception:
                        pass
        except Exception:
            pass

        # 3) Сбрасываем состояния сервисов и сохраняем в файлы
        try:
            if user_id in mailing_states:
                try:
                    mailing_states[user_id]["active"] = False
                except Exception:
                    pass
                update_service_state("mailing_states", user_id, mailing_states.get(user_id))
        except Exception:
            pass
        try:
            if user_id in postman_states:
                try:
                    postman_states[user_id]["active"] = False
                except Exception:
                    pass
                update_service_state("postman_states", user_id, None)
        except Exception:
            pass
        try:
            if user_id in autoresponder_states:
                try:
                    autoresponder_states[user_id]["active"] = False
                except Exception:
                    pass
                update_service_state("autoresponder_states", user_id, autoresponder_states.get(user_id))
        except Exception:
            pass

        # 4) Отправляем уведомление и показываем стартовое меню
        try:
            await bot.send_message(chat_id=user_id, text=notify_text)
        except Exception:
            pass

        try:
            # Выбираем язык
            lang = user_languages.get(user_id, "ru")
            markup = get_start_menu() if lang == "ru" else get_start_menu_en()
            # Пытаемся отправить стартовую картинку
            image_path = get_image_path("start_menu.png", user_id)
            full_path = Path(__file__).parent / image_path
            if full_path.exists():
                await bot.send_photo(
                    chat_id=user_id,
                    photo=FSInputFile(str(full_path)),
                    caption=("Выберите действие:" if lang == "ru" else "Choose an action:"),
                    reply_markup=markup
                )
            else:
                await bot.send_message(
                    chat_id=user_id,
                    text=("Выберите действие:" if lang == "ru" else "Choose an action:"),
                    reply_markup=markup
                )
        except Exception:
            pass

        # Переключаем состояние, чтобы пользователь мог ввести ключ при желании
        try:
            user_states[user_id] = "wait_license"
        except Exception:
            pass
    except Exception as e:
        try:
            print(f"❌ Ошибка handle_access_expired для пользователя {user_id}: {e}")
        except Exception:
            pass


async def periodic_access_guard():
    """Периодически проверяет статусы лицензий/триалов и завершает процессы для истекших пользователей."""
    while True:
        try:
            await asyncio.sleep(1800)  # каждые 30 минут
            # Берём копию списка авторизованных пользователей
            users = list(authorized_users)
            for uid in users:
                try:
                    if not is_license_valid(uid):
                        await handle_access_expired(uid)
                except Exception:
                    continue
        except asyncio.CancelledError:
            break
        except Exception as e:
            try:
                print(f"⚠️ periodic_access_guard ошибка: {e}")
            except Exception:
                pass

#@dp.message(Command("check_dialogs"))
#async def check_dialogs_command(message: Message):
#    """Команда для ручной проверки новых диалогов"""
#    user_id = message.from_user.id
#    
#    try:
#        # Проверяем, авторизован ли пользователь
#        if user_id not in authorized_users:
#            await message.answer("❌ Вы не авторизованы. Используйте /start для начала работы.")
#            return
#        
#        await message.answer("🔄 Запускаю ручную проверку новых диалогов...")
#        
#        # Принудительно проверяем все аккаунты пользователя
#        if user_id in active_clients:
#            for session_name in active_clients[user_id]:
#                try:
#                    await check_new_dialogs_for_client(user_id, session_name)
#                except Exception as e:
#                    print(f"❌ Ошибка ручной проверки для {session_name}: {e}")
#            
#            await message.answer("✅ Ручная проверка новых диалогов завершена!")
#        else:
#            await message.answer("ℹ️ У вас нет активных аккаунтов для проверки.")
#            
#    except Exception as e:
#        await message.answer(f"❌ Ошибка при ручной проверке диалогов: {e}")

@dp.message(Command("start"))
async def handle_start(message: Message):
    user_id = message.from_user.id
    
    # Логируем нажатие кнопки "Старт"
    log_button_click(user_id, "Старт")
    
    # Проверяем, выбрал ли пользователь язык
    if user_id not in user_languages:
        user_states[user_id] = "waiting_language"
        await message.answer(
            "Выберите язык / Select language:",
            reply_markup=get_language_menu()
        )
        return
    
    # Убеждаемся, что у пользователя есть языковая настройка (защита от ошибок)
    if user_id not in user_languages:
        user_languages[user_id] = "ru"  # По умолчанию русский
        save_user_languages()  # Сохраняем языковую настройку
    
    # Проверяем, авторизован ли пользователь
    license_type = user_states.get(f"{user_id}_license_type")
    
    # Определяем тип лицензии только если он уже был сохранен ранее
    # НЕ определяем автоматически при первом запуске
    if license_type:
        user_dir = get_user_dir(user_id, license_type)
        config_path = os.path.join(user_dir, "config.json")
        is_authorized = False
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                if config.get("api_id") and config.get("api_hash"):
                    is_authorized = True
            except Exception:
                pass
        if is_authorized:
            user_states[user_id] = "authorized"
            # Попытка отправить изображение с главным меню
            try:
                # Получаем путь к изображению с учетом стиля пользователя
                image_path = get_image_path("start_menu.png", user_id)
                full_path = Path(__file__).parent / image_path
                caption = "Вы уже авторизованы." if user_languages[user_id] == "ru" else "You are already authorized."
                if full_path.exists():
                    await bot.send_photo(
                        chat_id=message.chat.id,
                        photo=FSInputFile(str(full_path)),
                        caption=caption,
                        reply_markup=get_main_inline_menu()
                    )
                else:
                    await message.answer(
                        caption,
                        reply_markup=get_main_inline_menu()
                    )
            except Exception:
                await message.answer(
                    "Вы уже авторизованы." if user_languages[user_id] == "ru" else "You are already authorized.",
                    reply_markup=get_main_inline_menu()
                )
            return
    
    # Если не авторизован — не создаём папку!
    user_states[user_id] = None
    await delete_and_send_image(
        message,
        "start_menu.png",
        "🔑 Подписка:\n Basic 15$ | Premium 20$ | PRO 25$\n\n🧩 Количество аккаунтов:\nBasic x5 | Premium x10 | PRO x15\n\n⏳ Срок действия:\n 30 дней с момента активации ключа\n\n\n" if user_languages.get(user_id, "ru") == "ru" else "🔑 Subscription:\n Basic 15$ | Premium 20$ | PRO 25$\n\n🧩 Accounts:\n Basic x5 | Premium x10 | PRO x15\n\n⏳ Duration:\n 30 days from key activation\n\n\n",
        reply_markup=get_start_menu(),
        user_id=user_id
    )



@dp.message(F.text == "Стоп ⭕️")
async def handle_mailing_stop(message: types.Message):
    user_id = message.from_user.id
    
    # Получаем номера телефонов пользователя для остановки задач по аккаунтам
    user_phones = []
    try:
        user_accounts = load_user_accounts(user_id)
        if user_accounts:
            user_phones = [acc.get("phone") for acc in user_accounts if acc.get("phone")]
    except Exception:
        pass
    
    # ОСТАНАВЛИВАЕМ ВСЕ АКТИВНЫЕ ТАЙМЕРЫ И ЗАДАЧИ РАССЫЛКИ
    if user_id in active_tasks:
        for task_name in list(active_tasks[user_id].keys()):
            should_stop = (
                task_name.startswith("mailing") or 
                task_name.startswith("break_timer_") or 
                "timer" in task_name.lower() or 
                "countdown" in task_name.lower()
            )
            # Также останавливаем задачи, содержащие номера телефонов пользователя
            if not should_stop and user_phones:
                should_stop = any(phone in task_name for phone in user_phones)
            
            if should_stop:
                print(f"🛑 Останавливаем задачу: {task_name}")
                await stop_task(user_id, task_name)
    
    # ОСТАНАВЛИВАЕМ ЗАДАЧИ АВТОВОССТАНОВЛЕНИЯ
    if user_id in auto_resume_tasks:
        for service_type in list(auto_resume_tasks[user_id].keys()):
            if service_type in ["mailing", "monitoring"]:
                task = auto_resume_tasks[user_id][service_type]
                if not task.done():
                    print(f"🛑 Останавливаем задачу автовосстановления: {service_type}")
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                del auto_resume_tasks[user_id][service_type]
    
    # ОСТАНАВЛИВАЕМ МОНИТОРИНГ ПОДКЛЮЧЕНИЙ
    try:
        await connection_manager.stop_monitoring(user_id)
        print(f"🛑 Остановлен мониторинг подключений для пользователя {user_id}")
    except Exception as e:
        print(f"⚠️ Ошибка при остановке мониторинга: {e}")
    
    # Останавливаем рассылку
    if user_id in active_tasks and "mailing" in active_tasks[user_id]:
        # --- ДОБАВЛЕНО: Сохраняем актуальное состояние для Resume process ---
        from copy import deepcopy
        resume_state = load_resume_state(user_id=user_id)
        if resume_state and "accounts" in resume_state:
            # Для каждого аккаунта вызываем update_account_resume_state с последними значениями
            for acc in resume_state["accounts"]:
                phone = acc["phone"]
                # Получаем последние значения из acc
                chat_index = acc.get("chat_index", 0)
                message_count = acc.get("message_count", 0)
                update_account_resume_state(phone, chat_index=chat_index, message_count=message_count, user_id=user_id)
        # --- КОНЕЦ ДОБАВЛЕНИЯ ---
        await stop_task(user_id, "mailing")
    
    # Очищаем состояние рассылки
    if user_id in mailing_states:
        # Сначала деактивируем рассылку
        mailing_states[user_id]["active"] = False
        mailing_states[user_id]["step"] = "stopped"
        print(f"🛑 Деактивирована рассылка для пользователя {user_id}")
        # Затем полностью удаляем состояние
        del mailing_states[user_id]
        # Безопасно обновляем состояние в файле
        update_service_state("mailing_states", user_id, None)
    # Сбрасываем файл параметров рассылки
    clear_fn = globals().get("clear_mailing_parameters_file")
    if callable(clear_fn):
        try:
            clear_fn(user_id)
        except Exception:
            pass
    
    # Очищаем состояния перерывов для всех аккаунтов пользователя
    try:
        resume_state = load_resume_state(user_id=user_id)
        if resume_state and "accounts" in resume_state:
            for acc in resume_state["accounts"]:
                phone = acc["phone"]
                # Очищаем все поля связанные с перерывами
                update_account_resume_state(
                    phone, 
                    break_seconds_left=0, 
                    break_until_timestamp=0, 
                    break_started_ts=0,
                    user_id=user_id
                )
                print(f"🧹 Очищены состояния перерывов для аккаунта {phone}")
    except Exception as e:
        print(f"⚠️ Ошибка при очистке состояний перерывов: {e}")
    
    # Очищаем сессии пользователя
    if user_id in user_sessions and "pushmux" in user_sessions[user_id]:
        del user_sessions[user_id]["pushmux"]
    
    # Сохраняем состояние активных сессий для восстановления после перезапуска
    save_reconnect_state()
    
    await safe_message_answer(
        message,
        "Рассылка остановлена.",
        reply_markup=ReplyKeyboardRemove()
    )
    # Отправляем меню управления аккаунтами с изображением и актуальной статистикой
    await send_accounts_manage_menu_with_image(bot, message.chat.id, "Выберите действие:")

async def handle_autosub_minimize_alias(message: types.Message):
    user_id = message.from_user.id
    # Даже если автоподписка уже остановлена (например, по достижении лимита),
    # позволяем кнопке «Назад» вернуть пользователя в меню выбора аккаунтов
    # Определяем текущий выбранный телефон и ставим флаг свернутости именно для него
    phone = user_states.get(f"{user_id}_autosub_phone") or user_states.get(f"{user_id}_autosub_running_phone")
    if phone:
        user_states[f"{user_id}_autosub_minimized_{phone}"] = True
    # Убираем клавиатуру без отправки временного сообщения
    try:
        await bot.send_chat_action(message.chat.id, "typing")
        # Пытаемся отредактировать последнюю клавиатуру, если возможно, иначе просто продолжаем
        # Ничего не отправляем в чат
    except Exception:
        pass
    # Сообщаем пользователю о свертывании автоподписки и убираем reply-клавиатуру
    try:
        await safe_message_answer(
            message,
            "Автоподписка свёрнута и работает в фоновом режиме ↪️",
            reply_markup=ReplyKeyboardRemove()
        )
    except Exception:
        pass
    # Отрисовываем меню выбора аккаунта для автоподписки
    accounts = load_user_accounts(user_id)
    if not accounts:
        await send_accounts_manage_menu_with_image(bot, message.chat.id, "Выберите действие:")
        return
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    selected_phone = user_states.get(f"{user_id}_autosub_phone")
    for acc in accounts:
        label = acc.get("username") or acc.get("name") or acc.get("phone")
        label_fixed = f"{label: <5}"
        markup.inline_keyboard.append([
            InlineKeyboardButton(text=f"{label_fixed}", callback_data=f"autosub_acc_{acc.get('phone')}")
        ])
    markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="back_to_manage")])
    try:
        await delete_and_send_image(
            message,
            "accounts.png",
            "Выберите аккаунт для автоподписки:",
            reply_markup=markup,
            user_id=user_id
        )
    except TelegramAPIError as e:
        if "message is not modified" not in str(e):
            # Фолбэк: если нельзя отправить фото/редактировать, просто отправим текст
            await safe_message_answer(message, "Выберите аккаунт для автоподписки:", reply_markup=markup)

@dp.message(F.text.in_(["Назад"]))
async def handle_autosub_back(message: types.Message):
    # Поведение идентично «Свернуть» для автоподписки: сворачиваем и показываем меню
    await handle_autosub_minimize_alias(message)

@dp.message(F.text.in_(["Развернуть 📋", "развернуть 📋", "Развернуть", "развернуть"]))
async def handle_autosub_unminimize(message: types.Message):
    user_id = message.from_user.id
    # Показываем активную клавиатуру
    # Снимаем флаг свернутости и показываем активную клавиатуру без лишнего текста
    try:
        phone = user_states.get(f"{user_id}_autosub_running_phone") or user_states.get(f"{user_id}_autosub_phone")
        if phone:
            user_states.pop(f"{user_id}_autosub_minimized_{phone}", None)
    except Exception:
        pass
    # Показываем только клавиатуру без лишнего текста и оставляем сообщение,
    # чтобы клавиатура не пропадала
    try:
        await safe_message_answer(message, "\u2063", reply_markup=get_autosub_active_keyboard())
    except Exception:
        pass
    # Если во время свёрнутости был завершён список — сообщаем об этом вне очереди
    try:
        phone = user_states.get(f"{user_id}_autosub_running_phone") or user_states.get(f"{user_id}_autosub_phone")
        if phone:
            # Если пользователь явно завершил прошлую сессию — не показываем финальное сообщение
            if user_states.get(f"{user_id}_autosub_finished_{phone}"):
                user_states.pop(f"{user_id}_autosub_finished_{phone}", None)
                return
            done_flag = user_states.pop(f"{user_id}_autosub_done_{phone}", None)
            pending = user_states.pop(f"{user_id}_autosub_done_pending", None)
            if done_flag or (isinstance(pending, dict) and (pending.get("phone") == phone or not pending.get("phone"))):
                # Определим метку аккаунта
                acc_label = None
                try:
                    if isinstance(pending, dict) and pending.get("label"):
                        acc_label = pending.get("label")
                    else:
                        accounts = load_user_accounts(user_id)
                        for acc in accounts:
                            if acc.get("phone") == phone:
                                acc_label = acc.get("username") or acc.get("name") or acc.get("phone")
                                break
                except Exception:
                    pass
                done_text = "Весь список был успешно обработан. Автоподписка завершена."
                prefixed_text = f"{acc_label}: {done_text}" if acc_label else done_text
                await safe_message_answer(message, prefixed_text)
            # Если активен FloodWait — сообщаем оставшееся время вне очереди (однократно)
            try:
                f_started_key = f"{user_id}_autosub_flood_{phone}_started_ts"
                f_total_key = f"{user_id}_autosub_flood_{phone}_total_sec"
                f_started_ts = user_states.get(f_started_key)
                f_total_sec = user_states.get(f_total_key)
                if isinstance(f_started_ts, int) and isinstance(f_total_sec, int) and f_total_sec > 0:
                    now_ts = int(asyncio.get_event_loop().time())
                    elapsed = max(0, now_ts - f_started_ts)
                    remaining = max(0, f_total_sec - elapsed)
                    if remaining > 0:
                        # Определяем метку аккаунта
                        acc_label2 = None
                        try:
                            accounts = load_user_accounts(user_id)
                            for acc in accounts:
                                if acc.get("phone") == phone:
                                    acc_label2 = acc.get("username") or acc.get("name") or acc.get("phone")
                                    break
                        except Exception:
                            pass
                        prefix2 = f"{acc_label2}: " if acc_label2 else ""
                        await safe_message_answer(
                            message,
                            f"{prefix2}Telegram API ограничение: требуется подождать {remaining} секунд.",
                            reply_markup=get_autosub_active_keyboard()
                        )
                        # Не очищаем ключи, чтобы можно было показать при следующем разворачивании
            except Exception:
                pass
            else:
                # Повторяем финалку при каждом разворачивании до старта новой сессии
                replay_flag = user_states.get(f"{user_id}_autosub_last_done_{phone}")
                replay_label = user_states.get(f"{user_id}_autosub_last_done_label_{phone}")
                if replay_flag:
                    acc_label = replay_label
                    if not acc_label:
                        try:
                            accounts = load_user_accounts(user_id)
                            for acc in accounts:
                                if acc.get("phone") == phone:
                                    acc_label = acc.get("username") or acc.get("name") or acc.get("phone")
                                    break
                        except Exception:
                            pass
                    done_text = "Весь список был успешно обработан. Автоподписка завершена."
                    prefixed_text = f"{acc_label}: {done_text}" if acc_label else done_text
                    await safe_message_answer(message, prefixed_text)
    except Exception:
        pass

@dp.message(F.text.in_(["Завершить"]))
async def handle_autosub_finish(message: types.Message):
    user_id = message.from_user.id
    # Определяем текущий аккаунт
    phone = user_states.get(f"{user_id}_autosub_running_phone") or user_states.get(f"{user_id}_autosub_phone")
    # Останавливаем задачу в фоне, чтобы меню пришло мгновенно
    try:
        if phone and user_id in active_tasks:
            task_key = f"autosubscribe:{phone}"
            if task_key in active_tasks[user_id]:
                asyncio.create_task(stop_task(user_id, task_key))
    except Exception:
        pass
    # Обновляем reconnect_state: снимаем active для этого phone
    try:
        existing = load_user_reconnect_state_individual(user_id) or {}
        autos = existing.get("autosubscribe_states", {})
        uid = str(user_id)
        if uid in autos and phone and str(phone) in autos[uid]:
            autos[uid][str(phone)]["active"] = False
            save_user_reconnect_state_individual(user_id, existing)
    except Exception:
        pass
    # Мгновенно убираем клавиатуру и показываем меню выбора аккаунта для автоподписки
    try:
        await safe_message_answer(message, "Автоподписка остановлена.", reply_markup=ReplyKeyboardRemove())
        accounts = load_user_accounts(user_id)
        if not accounts:
            await send_accounts_manage_menu_with_image(bot, message.chat.id, "Выберите действие:")
        else:
            markup = InlineKeyboardMarkup(inline_keyboard=[])
            for acc in accounts:
                label = acc.get("username") or acc.get("name") or acc.get("phone")
                label_fixed = f"{label: <5}"
                markup.inline_keyboard.append([
                    InlineKeyboardButton(text=f"{label_fixed}", callback_data=f"autosub_acc_{acc.get('phone')}")
                ])
            markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="back_to_manage")])
            await delete_and_send_image(
                message,
                "accounts.png",
                "Выберите аккаунт для автоподписки:",
                reply_markup=markup,
                user_id=user_id
            )
    except Exception:
        pass
    # Чистим связанные временные состояния (после UI)
    try:
        if f"{user_id}_autosub_phone" in user_states:
            del user_states[f"{user_id}_autosub_phone"]
        if f"{user_id}_autosub_input_message_id" in user_states:
            del user_states[f"{user_id}_autosub_input_message_id"]
        if phone:
            user_states[f"{user_id}_autosub_finished_{phone}"] = True
            user_states.pop(f"{user_id}_autosub_done_{phone}", None)
            user_states.pop(f"{user_id}_autosub_done_label_{phone}", None)
            # Очищаем персистентный прогресс для этого аккаунта
            autosub_progress_clear_account(user_id, phone)
        user_states.pop(f"{user_id}_autosub_done_pending", None)
        user_states.pop(f"{user_id}_autosub_running_phone", None)
    except Exception:
        pass
@dp.message(F.text.in_(["Свернуть ↪️", "свернуть ↪️", "Свернуть", "свернуть"]))
async def handle_mailing_minimize(message: types.Message):
    user_id = message.from_user.id
    print(f"Обработчик Свернуть вызван для user_id: {user_id}")

    # Обновляем состояние
    if user_id in mailing_states:
        mailing_states[user_id]["logging_enabled"] = False
        mailing_states[user_id]["minimized"] = True  # Добавляем флаг свернутости
        print(f"Состояние обновлено: logging_enabled = False для user_id: {user_id}")
        # Сохраняем параметры рассылки
        save_fn = globals().get("save_mailing_parameters")
        if callable(save_fn):
            try:
                save_fn(user_id)
            except Exception:
                pass

    if user_id not in user_sessions:
        user_sessions[user_id] = {}
    if "pushmux" not in user_sessions[user_id]:
        user_sessions[user_id]["pushmux"] = {}
    user_sessions[user_id]["pushmux"]["minimized"] = True
    
    # Сохраняем состояние активных сессий для восстановления после перезапуска
    save_reconnect_state()

    # Отправляем сообщение с меню управления и удаляем клавиатуру
    await safe_message_answer(
        message,
        "Рассылка свернута и продолжает работать в фоновом режиме.",
        reply_markup=ReplyKeyboardRemove()
    )
    # Отправляем меню с изображением (с безопасным фолбэком)
    await send_accounts_manage_menu_with_image(bot, message.chat.id, "Выберите действие:")
    
@dp.callback_query()
async def handle_callback(call: CallbackQuery):
    user_id = call.from_user.id
    data = call.data
    
    # Логируем нажатие кнопки
    log_button_click(user_id, data)

    # --- Вспомогательные функции для восстановления состояния рассылки после рестарта ---
    def _requires_mailing_state(callback_data: str) -> bool:
        # Требует состояния для большинства шагов рассылки и игнор-меню.
        # Исключения: действия, которые сами инициализируют состояние
        if callback_data in {"message_mailing", "mailing_start", "mailing_templates", "mailing_continue_no_templates", "mailing_cancel_no_templates"}:
            return False
        prefixes = (
            "mailing_",            # все шаги рассылки
            "ignore_folders",      # меню игнора папок
            "ignore_chats",        # меню игнора чатов
            "custom_folder_",      # произвольные папки
            "select_folder_",      # выбор папок
            "select_chat_",        # выбор чатов
        )
        return callback_data.startswith(prefixes)

    # Если это колбек, требующий состояния рассылки, пробуем восстановить его из файла
    if _requires_mailing_state(data):
        try:
            # Ленивая загрузка из файла, если в памяти пусто
            if user_id not in mailing_states:
                # ВАЖНО: функции объявлены ниже; импорт здесь невозможен, поэтому используем forward-lookup через globals
                ensure_fn = globals().get("ensure_mailing_state")
                if callable(ensure_fn):
                    restored = await ensure_fn(user_id)
                    if not restored and user_id not in mailing_states:
                        await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
                        return
        except Exception:
            # При любой ошибке восстановления — ведём себя так же, как раньше
            if user_id not in mailing_states:
                await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
                return

    # Обработка выбора языка
    if data == "language_ru":
        # Сохраняем язык только для текущего пользователя
        save_single_user_language(user_id, "ru")
        user_states[user_id] = None
        
        # После выбора языка проверяем, авторизован ли пользователь
        # Автоматически определяем тип лицензии по существующим папкам
        is_authorized = False
        license_type = user_states.get(f"{user_id}_license_type")
        
        # Если тип лицензии не определен, пытаемся определить его автоматически
        if not license_type:
            license_type = detect_license_type(user_id)
            if license_type:
                user_states[f"{user_id}_license_type"] = license_type
        
        # Мигрируем папку пользователя, если это необходимо
        migrate_user_folder_if_needed(user_id)
        
        if license_type:
            user_dir = get_user_dir(user_id, license_type)
            config_path = os.path.join(user_dir, "config.json")
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                    if config.get("api_id") and config.get("api_hash"):
                        is_authorized = True
                except Exception:
                    pass
        
        if is_authorized:
            user_states[user_id] = "authorized"
            # Показываем главное меню с изображением
            try:
                # Получаем путь к изображению с учетом стиля пользователя
                image_path = get_image_path("start_menu.png", user_id)
                full_path = Path(__file__).parent / image_path
                if full_path.exists():
                    await bot.send_photo(
                        chat_id=call.message.chat.id,
                        photo=FSInputFile(str(full_path)),
                        caption="Вы уже авторизованы.",
                        reply_markup=get_main_inline_menu()
                    )
                else:
                    await edit_text_or_safe_send(
                        call.message,
                        "Вы уже авторизованы.",
                        reply_markup=get_main_inline_menu()
                    )
            except Exception:
                await edit_text_or_safe_send(
                    call.message,
                    "Вы уже авторизованы.",
                    reply_markup=get_main_inline_menu()
                )
        else:
            # Показываем меню выбора стиля
            style_markup, style_title = get_style_menu("ru", user_id)
            await edit_text_or_safe_send(
                call.message,
                style_title,
                reply_markup=style_markup
            )
        return
    
    elif data == "language_en":
        # Сохраняем язык только для текущего пользователя
        save_single_user_language(user_id, "en")
        user_states[user_id] = None
        
        # После выбора языка проверяем, авторизован ли пользователь
        # Автоматически определяем тип лицензии по существующим папкам
        is_authorized = False
        license_type = user_states.get(f"{user_id}_license_type")
        
        # Если тип лицензии не определен, пытаемся определить его автоматически
        if not license_type:
            license_type = detect_license_type(user_id)
            if license_type:
                user_states[f"{user_id}_license_type"] = license_type
        
        # Мигрируем папку пользователя, если это необходимо
        migrate_user_folder_if_needed(user_id)
        
        if license_type:
            user_dir = get_user_dir(user_id, license_type)
            config_path = os.path.join(user_dir, "config.json")
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                    if config.get("api_id") and config.get("api_hash"):
                        is_authorized = True
                except Exception:
                    pass
        
        if is_authorized:
            user_states[user_id] = "authorized"
            # Показываем главное меню с изображением
            try:
                # Получаем путь к изображению с учетом стиля пользователя
                image_path = get_image_path("start_menu.png", user_id)
                full_path = Path(__file__).parent / image_path
                if full_path.exists():
                    await bot.send_photo(
                        chat_id=call.message.chat.id,
                        photo=FSInputFile(str(full_path)),
                        caption="You are already authorized.",
                        reply_markup=get_main_inline_menu()
                    )
                else:
                    await edit_text_or_safe_send(
                        call.message,
                        "You are already authorized.",
                        reply_markup=get_main_inline_menu()
                    )
            except Exception:
                await edit_text_or_safe_send(
                    call.message,
                    "You are already authorized.",
                    reply_markup=get_main_inline_menu()
                )
        else:
            # Показываем меню выбора стиля
            style_markup, style_title = get_style_menu("en", user_id)
            await edit_text_or_safe_send(
                call.message,
                style_title,
                reply_markup=style_markup
            )
        return

    # Обработка выбора стиля
    elif data == "style_robo":
        # Устанавливаем стиль Robo
        set_user_style(user_id, "robo")
        user_states[user_id] = None
        
        # После выбора стиля проверяем, авторизован ли пользователь
        is_authorized = False
        license_type = user_states.get(f"{user_id}_license_type")
        
        if license_type:
            user_dir = get_user_dir(user_id, license_type)
            config_path = os.path.join(user_dir, "config.json")
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                    if config.get("api_id") and config.get("api_hash"):
                        is_authorized = True
                except Exception:
                    pass
        
        if is_authorized:
            user_states[user_id] = "authorized"
            # Показываем главное меню с изображением
            try:
                 await delete_and_send_image(
                    call.message,
                    "start_menu.png",
                    "Вы уже авторизованы." if user_languages.get(user_id, "ru") == "ru" else "You are already authorized.",
                    reply_markup=get_main_inline_menu(),
                    user_id=user_id
                )
            except Exception:
                await edit_text_or_safe_send(
                    call.message,
                    "Вы уже авторизованы." if user_languages.get(user_id, "ru") == "ru" else "You are already authorized.",
                    reply_markup=get_main_inline_menu()
                )
        else:
            # Удаляем сообщение выбора стиля и отправляем изображение со стартовым меню
            language = user_languages.get(user_id, "ru")
            if language == "ru":
                caption = "🔑 Подписка:\nBasic 15$ | Premium 20$ | PRO 25$\n\n🧩 Количество аккаунтов:\nBasic x5 | Premium x10 | PRO x15\n\n⏳ Срок действия:\n30 дней с момента активации ключа\n\n\n"
                markup = get_start_menu()
            else:
                caption = "🔑 Subscription:\nBasic 15$ | Premium 20$ | PRO 25$\n\n🧩 Accounts:\nBasic x5 | Premium x10 | PRO x15\n\n⏳ Duration:\n30 days from key activation\n\n\n"
                markup = get_start_menu_en()
            
            await delete_and_send_image(
                call.message,
                "start_menu.png",
                caption,
                reply_markup=markup,
                user_id=user_id
            )
        return

    elif data == "style_fallout":
        # Устанавливаем стиль Fallout
        set_user_style(user_id, "fallout")
        user_states[user_id] = None
        
        # После выбора языка проверяем, авторизован ли пользователь
        # НЕ определяем тип лицензии здесь - это должно происходить только при выборе лицензии
        is_authorized = False
        license_type = user_states.get(f"{user_id}_license_type")
        
        if license_type:
            user_dir = get_user_dir(user_id, license_type)
            config_path = os.path.join(user_dir, "config.json")
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                    if config.get("api_id") and config.get("api_hash"):
                        is_authorized = True
                except Exception:
                    pass
        
        if is_authorized:
            user_states[user_id] = "authorized"
            # Показываем главное меню с изображением
            try:
                await delete_and_send_image(
                    call.message,
                    "start_menu.png",
                    "Вы уже авторизованы." if user_languages.get(user_id, "ru") == "ru" else "You are already authorized.",
                    reply_markup=get_main_inline_menu(),
                    user_id=user_id
                )
            except Exception:
                await edit_text_or_safe_send(
                    call.message,
                    "Вы уже авторизованы." if user_languages.get(user_id, "ru") == "ru" else "You are already authorized.",
                    reply_markup=get_main_inline_menu()
                )
        else:
            # Удаляем сообщение выбора стиля и отправляем изображение со стартовым меню
            language = user_languages.get(user_id, "ru")
            if language == "ru":
                caption = "🔑 Подписка:\nBasic 15$ | Premium 20$ | PRO 25$\n\n🧩 Количество аккаунтов:\nBasic x5 | Premium x10 | PRO x15\n\n⏳ Срок действия:\n30 дней с момента активации ключа\n\n\n"
                markup = get_start_menu()
            else:
                caption = "🔑 Subscription:\nBasic 15$ | Premium 20$ | PRO 25$\n\n🧩 Accounts:\nBasic x5 | Premium x10 | PRO x15\n\n⏳ Duration:\n30 days from key activation\n\n\n"
                markup = get_start_menu_en()
            
            await delete_and_send_image(
                call.message,
                "start_menu.png",
                caption,
                reply_markup=markup,
                user_id=user_id
            )
        return

    # Обработка пробного периода
    elif data == "free_trial":
        try:
            freetrial_data = load_freetrial()
            user_key = str(user_id)
            now = int(time.time())

            # Если пользователь уже активировал пробный период
            if user_key in freetrial_data:
                activated_at = int(freetrial_data[user_key].get("activated_at", 0))
                # Проверяем, не истёк ли пробный период (24 часа)
                if now - activated_at >= 86400:
                    await call.answer("Срок действия вашего пробного периода истёк.", show_alert=True)
                    return
                # Если запись есть, но authorized=false (после выхода) — реактивируем и готовим папки
                if freetrial_data[user_key].get("authorized") is False:
                    try:
                        # Включаем авторизацию в freetrial.json
                        freetrial_data[user_key]["authorized"] = True
                        save_freetrial(freetrial_data)
                    except Exception:
                        pass

                    user_states[f"{user_id}_license_type"] = "trial"
                    user_states[user_id] = "authorized"

                    # Подготовка папок/файлов для повторной активации trial
                    root = get_project_root()
                    user_base_dir = os.path.join(root, "user")
                    old_dir = os.path.join(user_base_dir, str(user_id))
                    new_dir = os.path.join(user_base_dir, f"{user_id}_trial")

                    # Сохранить старые настройки (если есть) из plain
                    old_settings_data = {}
                    old_settings_file = os.path.join(old_dir, "settings.json")
                    if os.path.exists(old_settings_file):
                        try:
                            with open(old_settings_file, "r", encoding="utf-8") as f:
                                old_settings_data = json.load(f) or {}
                        except Exception:
                            pass

                    # Переименовать plain -> _trial, при необходимости удалить существующую целевую
                    try:
                        if os.path.exists(old_dir):
                            if os.path.exists(new_dir):
                                shutil.rmtree(new_dir, ignore_errors=True)
                            os.rename(old_dir, new_dir)
                        else:
                            os.makedirs(new_dir, exist_ok=True)
                    except Exception:
                        try:
                            if os.path.exists(new_dir):
                                shutil.rmtree(new_dir, ignore_errors=True)
                            if os.path.exists(old_dir):
                                shutil.copytree(old_dir, new_dir)
                                shutil.rmtree(old_dir, ignore_errors=True)
                            else:
                                os.makedirs(new_dir, exist_ok=True)
                        except Exception:
                            os.makedirs(new_dir, exist_ok=True)

                    # Создать/перезаписать config.json для trial
                    try:
                        config_path = os.path.join(new_dir, "config.json")
                        config_data = {"api_id": 22133941, "api_hash": "c226d2309461ee258c2aefc4dd19b743", "accounts": []}
                        with open(config_path, "w", encoding="utf-8") as f:
                            json.dump(config_data, f, ensure_ascii=False, indent=2)
                    except Exception:
                        pass

                    # Обновить settings.json с сохранением стиля/языка и восстановлением autosubscribe_limit
                    try:
                        settings_file = os.path.join(new_dir, "settings.json")
                        settings_data = {"language": user_languages.get(user_id, "ru")}
                        if "style" in old_settings_data:
                            settings_data["style"] = old_settings_data["style"]
                        # Вытаскиваем текущий счетчик из freetrial.json, если есть
                        try:
                            ft_tmp = load_freetrial()
                            rec_tmp = ft_tmp.get(user_key) or {}
                            if isinstance(rec_tmp.get("autosubscribe_limit"), int):
                                settings_data["autosubscribe_limit"] = rec_tmp["autosubscribe_limit"]
                        except Exception:
                            pass
                        with open(settings_file, "w", encoding="utf-8") as f:
                            json.dump(settings_data, f, ensure_ascii=False, indent=2)
                    except Exception:
                        pass

                    # На всякий случай уберем оставшийся plain, если есть
                    try:
                        if os.path.exists(old_dir) and os.path.isdir(old_dir):
                            shutil.rmtree(old_dir, ignore_errors=True)
                    except Exception:
                        pass

                    try:
                        await delete_and_send_image(
                            call.message,
                            "start_menu.png",
                            "Выберите действие:" if user_languages.get(user_id, "ru") == "ru" else "Select action:",
                            reply_markup=get_main_inline_menu(),
                            user_id=user_id
                        )
                    except TelegramAPIError as e:
                        if "message is not modified" not in str(e):
                            raise
                    return

                # Обычный случай: уже активирован и авторизован — просто впускаем в кабинет
                user_states[f"{user_id}_license_type"] = "trial"
                user_states[user_id] = "authorized"
                # Синхронизируем autosubscribe_limit из freetrial.json в settings.json (не затирая существующее)
                try:
                    ft_sync = load_freetrial()
                    rec_sync = ft_sync.get(user_key) or {}
                    if isinstance(rec_sync.get("autosubscribe_limit"), int):
                        settings_now = load_user_settings(user_id, "trial") or {}
                        if not isinstance(settings_now.get("autosubscribe_limit"), int):
                            update_user_settings(user_id, {"autosubscribe_limit": rec_sync["autosubscribe_limit"]}, "trial")
                except Exception:
                    pass
                await delete_and_send_image(
                    call.message,
                    "start_menu.png",
                    "Выберите действие:" if user_languages.get(user_id, "ru") == "ru" else "Select action:",
                    reply_markup=get_main_inline_menu(),
                    user_id=user_id
                )
                return

            # Иначе первая активация
            update_freetrial(user_id)
            # Явно убедимся, что authorized=true
            try:
                ft2 = load_freetrial()
                rec = ft2.get(user_key) or {}
                rec["authorized"] = True
                # Инициализируем счетчик autosubscribe_limit если не задан
                if not isinstance(rec.get("autosubscribe_limit"), int):
                    rec["autosubscribe_limit"] = 0
                ft2[user_key] = rec
                save_freetrial(ft2)
            except Exception:
                pass
            user_states[f"{user_id}_license_type"] = "trial"
            user_states[user_id] = "authorized"
            
            # Обновляем основную информацию пользователя в логах
            update_user_main_info(
                user_id,
                license_type="trial"
            )

            # Подготовка папок/файлов для trial (как раньше)
            root = get_project_root()
            user_base_dir = os.path.join(root, "user")
            old_dir = os.path.join(user_base_dir, str(user_id))  # Папка без суффикса
            new_dir = os.path.join(user_base_dir, f"{user_id}_trial")  # Папка с суффиксом
            
            # Загружаем существующие настройки из старой папки ДО её удаления
            old_settings_data = {}
            old_settings_file = os.path.join(old_dir, "settings.json")
            if os.path.exists(old_settings_file):
                try:
                    with open(old_settings_file, "r", encoding="utf-8") as f:
                        old_settings_data = json.load(f) or {}
                except Exception as e:
                    print(f"Ошибка загрузки старых настроек: {e}")
            
            # Если существует старая папка без суффикса — переименовываем в суффиксную
            if os.path.exists(old_dir):
                try:
                    # Если целевая уже есть, удалим её перед переименованием
                    if os.path.exists(new_dir):
                        shutil.rmtree(new_dir)
                    os.rename(old_dir, new_dir)
                except Exception as e:
                    print(f"Ошибка переименования папки: {e}")
                    try:
                        # Фоллбэк: копируем содержимое и удаляем исходную
                        if os.path.exists(new_dir):
                            shutil.rmtree(new_dir)
                        shutil.copytree(old_dir, new_dir)
                        shutil.rmtree(old_dir)
                    except Exception as ee:
                        print(f"Ошибка копирования при фоллбэке: {ee}")
                        # Если не удалось — создадим пустую целевую
                        os.makedirs(new_dir, exist_ok=True)
            else:
                # Если старой папки нет, создаем новую
                os.makedirs(new_dir, exist_ok=True)
            
            # Создаем config.json с API данными
            config_path = os.path.join(new_dir, "config.json")
            
            # API данные для пробного периода (такие же как у обычных пользователей)
            config_data = {
                "api_id": 22133941,
                "api_hash": "c226d2309461ee258c2aefc4dd19b743",
                "accounts": []
            }
            
            # Сохраняем config.json
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)
            
            # Создаем settings.json в папке пользователя с сохранением стиля
            settings_file = os.path.join(new_dir, "settings.json")
            settings_data = {"language": user_languages.get(user_id, "ru")}
            
            # Сохраняем стиль из старых настроек
            if "style" in old_settings_data:
                settings_data["style"] = old_settings_data["style"]
                #print(f"Сохранен стиль из старых настроек: {old_settings_data['style']}")
            
            with open(settings_file, "w", encoding="utf-8") as f:
                json.dump(settings_data, f, ensure_ascii=False, indent=2)
            
            message = "Пробный период активирован💥" if user_languages.get(user_id, "ru") == "ru" else "Free trial activated💥"
            await call.answer(message, show_alert=True)
            
            # Защитное правило: гарантируем отсутствие plain-папки после активации trial
            try:
                if os.path.exists(old_dir) and os.path.isdir(old_dir):
                    shutil.rmtree(old_dir, ignore_errors=True)
            except Exception:
                pass
            try:
                await delete_and_send_image(
                    call.message,
                    "start_menu.png",
                    "Выберите действие:" if user_languages.get(user_id, "ru") == "ru" else "Select action:",
                    reply_markup=get_main_inline_menu(),
                    user_id=user_id
                )
            except TelegramAPIError as e:
                if "message is not modified" not in str(e):
                    raise
        except Exception as e:
            print(f"Ошибка активации пробного периода: {e}")
            await call.answer("Ошибка активации пробного периода", show_alert=True)
        return

    if data == "start_auth":
        try:
            markup = get_referral_menu() if user_languages.get(user_id, "ru") == "ru" else get_referral_menu_en()
            # Отправляем сообщение и сохраняем его ID для последующего удаления
            sent_message = await delete_and_send_image(
                call.message,
                "password.png",
                "Есть реферальный код ? Получите 72 часа бесплатно !" if user_languages.get(user_id, "ru") == "ru" else "Have a referral code? Get 72 hours free!",
                reply_markup=markup,
                user_id=user_id
            )
            # Сохраняем ID сообщения для последующего удаления
            user_states[f"{user_id}_referral_message_id"] = sent_message.message_id
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        user_states[user_id] = "wait_referral_choice"
        return

    elif data == "enter_referral":
        # Если пользователь уже активировал реферальный бонус ранее, не даем вводить код снова
        if has_user_used_referral(user_id):
            await call.answer("Вы уже вводили реферальный код.", show_alert=True)
            return
        try:
            markup = get_back_to_referral_menu() if user_languages.get(user_id, "ru") == "ru" else get_back_to_referral_menu_en()
            # Отправляем сообщение и сохраняем его ID для последующего удаления
            sent_message = await delete_and_send_image(
                call.message,
                "password.png",
                "📩 Введите реферальный код:" if user_languages.get(user_id, "ru") == "ru" else "Enter referral code:",
                reply_markup=markup,
                user_id=user_id
            )
            # Сохраняем ID сообщения для последующего удаления
            user_states[f"{user_id}_referral_input_message_id"] = sent_message.message_id
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        user_states[user_id] = "wait_referral_code"
        return

    elif data == "skip_referral":
        try:
            markup = get_back_to_referral_menu() if user_languages.get(user_id, "ru") == "ru" else get_back_to_referral_menu_en()
            # Отправляем сообщение и сохраняем его ID для последующего удаления
            sent_message = await delete_and_send_image(
                call.message,
                "password.png",
                "🪪 Введите лицензионный ключ:" if user_languages.get(user_id, "ru") == "ru" else "Enter license code:",
                reply_markup=markup,
                user_id=user_id
            )
            # Сохраняем ID сообщения для последующего удаления
            user_states[f"{user_id}_password_message_id"] = sent_message.message_id
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        user_states[user_id] = "wait_license"
        return

    elif data == "back_to_language":
        # Возвращаемся к выбору языка
        user_states[user_id] = "waiting_language"
        try:
            await edit_text_or_safe_send(
                call.message,
                "Выберите язык / Select language:",
                reply_markup=get_language_menu()
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "back_to_start":
        # Возврат в главное стартовое меню
        if user_id not in user_languages:
            user_languages[user_id] = "ru"  # По умолчанию русский
            save_user_languages()
        try:
            markup = get_start_menu() if user_languages.get(user_id, "ru") == "ru" else get_start_menu_en()
            await delete_and_send_image(
                call.message,
                "start_menu.png",
                "🔑 Подписка:\n Basic 15$ | Premium 20$ | PRO 25$\n\n🧩 Количество аккаунтов:\nBasic x5 | Premium x10 | PRO x15\n\n⏳ Срок действия:\n 30 дней с момента активации ключа\n\n\n" if user_languages.get(user_id, "ru") == "ru" else "🔑 Subscription:\n Basic 15$ | Premium 20$ | PRO 25$\n\n🧩 Accounts:\n Basic x5 | Premium x10 | PRO x15\n\n⏳ Duration:\n 30 days from key activation\n\n\n",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        user_states[user_id] = None
        return

    elif data == "back_to_referral":
        # Возврат на экран реферала "Есть реферальный код?" из ввода кода/лицензии
        try:
            referral_markup = get_referral_menu() if user_languages.get(user_id, "ru") == "ru" else get_referral_menu_en()
            await delete_and_send_image(
                call.message,
                "password.png",
                "Есть реферальный код ? Получите 72 часа бесплатно !" if user_languages.get(user_id, "ru") == "ru" else "Have a referral code? Get 72 hours free!",
                reply_markup=referral_markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        user_states[user_id] = "wait_referral_choice"
        return

    # Обработка новых кнопок в меню управления аккаунтами
    elif data == "multitool":
        await call.answer("Мультитул ⚒️ - функция в разработке", show_alert=True)
        return
    
    elif data == "parsing":
        await call.answer("Парсинг 🧲 - функция в разработке", show_alert=True)
        return
    
    elif data == "chat_search":
        await call.answer("Поиск чатов 🔍 - функция в разработке", show_alert=True)
        return
    
    elif data == "autosubscribe":
        # Быстрый гейт доступа
        if not is_license_valid(user_id):
            try:
                ft = load_freetrial()
            except Exception:
                ft = {}
            if str(user_id) in ft and not is_freetrial_valid(user_id):
                alert_text = "Пробный период закончился. Ваши активные сервисы остановлены."
            else:
                alert_text = "Подписка закончилась. Ваши активные сервисы остановлены."
            try:
                await call.answer(alert_text, show_alert=True)
            except Exception:
                pass
            await handle_access_expired(user_id)
            return

        # Если у пользователя trial и достигнут лимит автоподписки — блокируем сразу вход в раздел
        try:
            license_type = detect_license_type(user_id)
            if str(license_type).endswith("trial") or str(license_type) == "trial":
                # Читаем лимит из settings.json: как только достигнет 5 — блокируем
                if get_user_autosub_limit(user_id) >= 5:
                    try:
                        await call.answer(
                            "Достигнут лимит автоподписки для пробного периода. Для безлимитного использования приобретите лицензионный ключ.",
                            show_alert=True
                        )
                    except Exception:
                        pass
                    return
        except Exception:
            pass

        accounts = load_user_accounts(user_id)
        if not accounts:
            await call.answer("Нет авторизованных аккаунтов.", show_alert=True)
            return

        # Рендерим меню выбора аккаунта
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        selected_phone = user_states.get(f"{user_id}_autosub_phone")
        for acc in accounts:
            label = acc.get("username") or acc.get("name") or acc.get("phone")
            label_fixed = f"{label: <5}"
            markup.inline_keyboard.append([
                InlineKeyboardButton(text=f"{label_fixed}", callback_data=f"autosub_acc_{acc.get('phone')}")
            ])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="back_to_manage")])

        try:
            await delete_and_send_image(
                call.message,
                "accounts.png",
                "Выберите аккаунт для автоподписки:",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return
    
    elif data == "analytics":
        await call.answer("Панель аналитики 📈  - функция в разработке", show_alert=True)
        return

    # Обработка новых кнопок в главном меню
    elif data == "partner_program":
        try:
            await delete_and_send_image(
                call.message,
                ["affiliate.png", "affiliate.jpg"],
                "SOON 🔜",
                reply_markup=get_back_only_menu(),
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return
    
    elif data == "instructions":
        try:
            await delete_and_send_image(
                call.message,
                "tutorial.png",
                "Выберите раздел для получения инструкции:" if user_languages.get(user_id, "ru") == "ru" else "Select section to get instructions:",
                reply_markup=get_instructions_menu(),
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return
    
    elif data == "free_nft":
        try:
            await delete_and_send_image(
                call.message,
                "freenft.png",
                "SOON 🔜",
                reply_markup=get_back_only_menu(),
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return
    
    elif data == "settings":
        try:
            await delete_and_send_image(
                call.message,
                "settings.png",
                "Настройки:" if user_languages.get(user_id, "ru") == "ru" else "Settings:",
                reply_markup=get_settings_menu(),
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    # Обработчики для меню настроек
    elif data == "change_language":
        try:
            # Создаем markup с кнопками языков и кнопкой "Вернуться"
            markup = InlineKeyboardMarkup(inline_keyboard=[])
            markup.inline_keyboard.append([
                InlineKeyboardButton(text="RU 🇷🇺", callback_data="language_ru_settings"),
                InlineKeyboardButton(text="ENG 🇺🇸", callback_data="language_en_settings")
            ])
            markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="back_to_settings")])
            
            await delete_and_send_image(
                call.message,
                "settings.png",
                "Выберите язык интерфейса:" if user_languages.get(user_id, "ru") == "ru" else "Choose interface language:",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "language_ru_settings":
        # Сохраняем язык и возвращаемся в настройки
        save_single_user_language(user_id, "ru")
        try:
            markup = get_settings_menu() if user_languages.get(user_id, "ru") == "ru" else get_settings_menu_en()
            await delete_and_send_image(
                call.message,
                "settings.png",
                "🇷🇺 Русский язык активирован!" if user_languages.get(user_id, "ru") == "ru" else "🇷🇺 Russian language activated!",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "language_en_settings":
        # Сохраняем язык и возвращаемся в настройки
        save_single_user_language(user_id, "en")
        try:
            markup = get_settings_menu() if user_languages.get(user_id, "ru") == "ru" else get_settings_menu_en()
            await delete_and_send_image(
                call.message,
                "settings.png",
                "🇺🇸 English language activated!" if user_languages.get(user_id, "ru") == "ru" else "🇺🇸 English language activated!",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return
    
    elif data == "toggle_images":
        await call.answer("SOON 🔜", show_alert=True)
        return

    elif data == "change_style":
        try:
            language = user_languages.get(user_id, "ru")
            # Меню выбора стиля в настройках: используем отдельные callback-и, чтобы не пересекаться с онбордингом
            markup = InlineKeyboardMarkup(inline_keyboard=[])
            if language == "ru":
                markup.inline_keyboard.append([
                    InlineKeyboardButton(text="🤖 Robo", callback_data="style_robo_settings"),
                    InlineKeyboardButton(text="☢️ Fallout", callback_data="style_fallout_settings")
                ])
                markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="back_to_settings")])
                title = "Выберите стиль интерфейса:"
            else:
                markup.inline_keyboard.append([
                    InlineKeyboardButton(text="🤖 Robo", callback_data="style_robo_settings"),
                    InlineKeyboardButton(text="☢️ Fallout", callback_data="style_fallout_settings")
                ])
                markup.inline_keyboard.append([InlineKeyboardButton(text="Back 🔙", callback_data="back_to_settings")])
                title = "Choose interface style:"
            await delete_and_send_image(
                call.message,
                "settings.png",
                title,
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "style_robo_settings":
        try:
            # Устанавливаем стиль robo для пользователя и остаёмся на экране выбора стиля (в настройках)
            set_user_style(user_id, "robo")
            language = user_languages.get(user_id, "ru")
            markup = InlineKeyboardMarkup(inline_keyboard=[])
            if language == "ru":
                markup.inline_keyboard.append([
                    InlineKeyboardButton(text="🤖 Robo", callback_data="style_robo_settings"),
                    InlineKeyboardButton(text="☢️ Fallout", callback_data="style_fallout_settings")
                ])
                markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="back_to_settings")])
                title = "Выберите стиль интерфейса:"
            else:
                markup.inline_keyboard.append([
                    InlineKeyboardButton(text="🤖 Robo", callback_data="style_robo_settings"),
                    InlineKeyboardButton(text="☢️ Fallout", callback_data="style_fallout_settings")
                ])
                markup.inline_keyboard.append([InlineKeyboardButton(text="Back 🔙", callback_data="back_to_settings")])
                title = "Choose interface style:"
            await delete_and_send_image(
                call.message,
                "settings.png",
                title,
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "style_fallout_settings":
        try:
            # Устанавливаем стиль fallout для пользователя и остаёмся на экране выбора стиля (в настройках)
            set_user_style(user_id, "fallout")
            language = user_languages.get(user_id, "ru")
            markup = InlineKeyboardMarkup(inline_keyboard=[])
            if language == "ru":
                markup.inline_keyboard.append([
                    InlineKeyboardButton(text="🤖 Robo", callback_data="style_robo_settings"),
                    InlineKeyboardButton(text="☢️ Fallout", callback_data="style_fallout_settings")
                ])
                markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="back_to_settings")])
                title = "Выберите стиль интерфейса:"
            else:
                markup.inline_keyboard.append([
                    InlineKeyboardButton(text="🤖 Robo", callback_data="style_robo_settings"),
                    InlineKeyboardButton(text="☢️ Fallout", callback_data="style_fallout_settings")
                ])
                markup.inline_keyboard.append([InlineKeyboardButton(text="Back 🔙", callback_data="back_to_settings")])
                title = "Choose interface style:"
            await delete_and_send_image(
                call.message,
                "settings.png",
                title,
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    # Обработчики для меню инструкций
    elif data == "instruction_statistics":
        await call.answer("SOON 🔜", show_alert=True)
        return
    
    elif data == "instruction_mailing":
        try:
            # Импортируем модуль инструкции рассылки
            from instruction_mailing import send_mailing_instruction
            
            # Определяем язык пользователя
            language = user_languages.get(user_id, "ru")
            
            # Удаляем предыдущее сообщение и отправляем 10 сообщений по порядку
            try:
                await call.message.delete()
            except Exception:
                pass
            await send_mailing_instruction(
                bot=bot,
                chat_id=call.message.chat.id,
                user_id=user_id,
                language=language
            )
        except Exception as e:
            # В случае ошибки показываем простое сообщение
            await call.answer("Ошибка загрузки инструкции. Попробуйте позже.", show_alert=True)
            print(f"Ошибка загрузки инструкции рассылки: {e}")
        return
    
    elif data == "instruction_postman":
        try:
            # Импортируем модуль инструкции почты
            from instruction_postman import get_postman_instruction_text, get_postman_instruction_keyboard, get_postman_instruction_text_en, get_postman_instruction_keyboard_en
            
            # Определяем язык пользователя
            language = user_languages.get(user_id, "ru")
            
            # Получаем текст и клавиатуру в зависимости от языка
            if language == "en":
                text = get_postman_instruction_text_en()
                keyboard = get_postman_instruction_keyboard_en()
            else:
                text = get_postman_instruction_text()
                keyboard = get_postman_instruction_keyboard()
            
            # Удаляем предыдущее сообщение и отправляем ТОЛЬКО текст с клавиатурой
            try:
                await call.message.delete()
            except Exception:
                pass
            await bot.send_message(
                chat_id=call.message.chat.id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except Exception as e:
            # В случае ошибки показываем простое сообщение
            await call.answer("Ошибка загрузки инструкции. Попробуйте позже.", show_alert=True)
            print(f"Ошибка загрузки инструкции почты: {e}")
        return
    
    elif data == "instruction_autoresponder":
        try:
            # Импортируем модуль инструкции автоответчика
            from instruction_autoresponder import get_autoresponder_instruction_text, get_autoresponder_instruction_keyboard, get_autoresponder_instruction_text_en, get_autoresponder_instruction_keyboard_en
            
            # Определяем язык пользователя
            language = user_languages.get(user_id, "ru")
            
            # Получаем текст и клавиатуру в зависимости от языка
            if language == "en":
                text = get_autoresponder_instruction_text_en()
                keyboard = get_autoresponder_instruction_keyboard_en()
            else:
                text = get_autoresponder_instruction_text()
                keyboard = get_autoresponder_instruction_keyboard()
            
            # Удаляем предыдущее сообщение и отправляем ТОЛЬКО текст с клавиатурой
            try:
                await call.message.delete()
            except Exception:
                pass
            await bot.send_message(
                chat_id=call.message.chat.id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except Exception as e:
            # В случае ошибки показываем простое сообщение
            await call.answer("Ошибка загрузки инструкции. Попробуйте позже.", show_alert=True)
            print(f"Ошибка загрузки инструкции автоответчика: {e}")
        return
    
    elif data == "instruction_multitool":
        await call.answer("SOON 🔜", show_alert=True)
        return
    
    elif data == "instruction_parsing":
        await call.answer("SOON 🔜", show_alert=True)
        return
    
    elif data == "instruction_chat_search":
        await call.answer("SOON 🔜", show_alert=True)
        return
    
    elif data == "instruction_autosubscribe":
        try:
            from instruction_autosubscribe import send_autosubscribe_instruction
            try:
                await call.message.delete()
            except Exception:
                pass
            await send_autosubscribe_instruction(
                bot=bot,
                chat_id=call.message.chat.id,
                user_id=user_id,
                language=user_languages.get(user_id, "ru"),
            )
        except Exception as e:
            await call.answer("Ошибка загрузки инструкции. Попробуйте позже.", show_alert=True)
            print(f"Ошибка загрузки инструкции автоподписки: {e}")
        return
    
    elif data == "instruction_analytics":
        await call.answer("SOON 🔜", show_alert=True)
        return

    if data == "manage_accounts":
        try:
            # Удаляем старое сообщение и отправляем новое с изображением
            await call.message.delete()
            caption = "📊 Статистика:" if user_languages.get(user_id, "ru") == "ru" else "Account management."
            await send_accounts_manage_menu_with_image(bot, call.message.chat.id, caption)
        except Exception as e:
            # Игнорируем ошибки удаления сообщения (сообщение уже удалено или недоступно)
            print(f"Не удалось удалить сообщение: {e}")
        user_states[user_id] = "manage_accounts"

    elif data == "back_to_menu":
        try:
            await delete_and_send_image(
                call.message,
                "start_menu.png",
                "Вы вернулись в главное меню." if user_languages.get(user_id, "ru") == "ru" else "You returned to the main menu.",
                reply_markup=get_main_inline_menu(),
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        user_states[user_id] = "authorized"

    elif data == "back_to_settings":
        try:
            markup = get_settings_menu() if user_languages.get(user_id, "ru") == "ru" else get_settings_menu_en()
            await delete_and_send_image(
                call.message,
                "settings.png",
                "Настройки:" if user_languages.get(user_id, "ru") == "ru" else "Settings:",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "accounts_menu":
        # Формируем текстовый список аккаунтов
        accounts = get_active_accounts_by_sessions(user_id)
        if accounts:
            acc_lines = []
            for acc in accounts:
                if acc.get("username"):
                    acc_lines.append(f"@{acc['username']}")
                elif acc.get("name"):
                    acc_lines.append(acc["name"])
                else:
                    acc_lines.append(acc.get("phone", ""))
            accs_text = "\n".join(acc_lines)
            caption = f"Аккаунты:\n\n{accs_text}" if user_languages.get(user_id, "ru") == "ru" else f"Accounts:\n\n{accs_text}"
        else:
            caption = "Нет авторизованных аккаунтов." if user_languages.get(user_id, "ru") == "ru" else "Accounts:\n\nNo authorized accounts."
        # Удаляем предыдущее сообщение и отправляем одно фото-сообщение с подписью и клавиатурой
        try:
            await delete_and_send_image(
                call.message,
                "accounts.png",
                caption,
                reply_markup=get_accounts_menu(user_id),
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        user_states[user_id] = "accounts_menu"

    elif data == "back_to_manage":
        try:
            # Удаляем старое сообщение и отправляем новое с изображением
            await call.message.delete()
            caption = "📊 Статистика:" if user_languages.get(user_id, "ru") == "ru" else "Account management."
            await send_accounts_manage_menu_with_image(bot, call.message.chat.id, caption)
        except Exception as e:
            # Игнорируем ошибки удаления сообщения (сообщение уже удалено или недоступно)
            print(f"Не удалось удалить сообщение: {e}")
        user_states[user_id] = "manage_accounts"

    elif data == "back_to_accounts_menu":
        # Получаем список аккаунтов по наличию .session файлов и формируем подпись
        accounts = get_active_accounts_by_sessions(user_id)
        if accounts:
            acc_lines = []
            for acc in accounts:
                if acc.get("username"):
                    acc_lines.append(f"@{acc['username']}")
                elif acc.get("name"):
                    acc_lines.append(acc["name"])
                else:
                    acc_lines.append(acc.get("phone", ""))
            accs_text = "\n".join(acc_lines)
            caption = f"Аккаунты:\n\n{accs_text}" if user_languages.get(user_id, "ru") == "ru" else f"Accounts:\n\n{accs_text}"
        else:
            caption = "Нет авторизованных аккаунтов." if user_languages.get(user_id, "ru") == "ru" else "Accounts:\n\nNo authorized accounts."
        try:
            await delete_and_send_image(
                call.message,
                "accounts.png",
                caption,
                reply_markup=get_accounts_menu(user_id),
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        user_states[user_id] = "accounts_menu"

    elif data == "add_account":
        accounts = load_user_accounts(user_id)
        max_allowed = get_max_sessions_for_license(user_id)
        if len(accounts) >= max_allowed:
            message = "Вы уже добавили максимальное количество аккаунтов." if user_languages.get(user_id, "ru") == "ru" else "You have already added the maximum number of accounts."
            await call.answer(message, show_alert=True)
        else:
            try:
                # Отправляем сообщение и сохраняем его ID для последующего удаления
                sent_message = await delete_and_send_image(
                    call.message,
                    "nonexistent_image.png",  # Несуществующее изображение для fallback на текст
                    "В целях вашей собственной безопасности рекомендуем вам установить на все Telegram аккаунты 2FA и код пароль, а так же привязать ним к электронную почту 🔐\n\nВведите номер телефона:" if user_languages.get(user_id, "ru") == "ru" else "Phone number:",
                    reply_markup=back_menu_auth,
                    user_id=user_id
                )
                # Сохраняем ID сообщения для последующего удаления
                user_states[f"{user_id}_phone_message_id"] = sent_message.message_id
            except TelegramAPIError as e:
                if "message is not modified" not in str(e):
                    raise
            user_states[user_id] = "wait_phone"

    elif data == "deauth_account":
        try:
            # Используем delete_and_send_image чтобы заменить предыдущее сообщение
            await delete_and_send_image(
                call.message,
                "nonexistent_image.png",  # Несуществующее изображение для fallback на текст
                "Выберите аккаунт для деавторизации:" if user_languages.get(user_id, "ru") == "ru" else "Select account to deauthorize:",
                reply_markup=get_deauth_accounts_menu(user_id),
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        user_states[user_id] = "deauth_menu"

    elif data.startswith("deauth_"):
        phone = data.replace("deauth_", "")
        accounts = load_user_accounts(user_id)
        # Проверяем, не используется ли аккаунт сейчас в каком-либо сервисе
        active_services = []
        try:
            # Рассылка
            if (
                mailing_states.get(user_id, {}).get("active")
                and phone in (mailing_states.get(user_id, {}).get("selected_accounts") or [])
            ):
                active_services.append("Рассылка")

            # Автоответчик
            if (
                autoresponder_states.get(user_id, {}).get("active")
                and phone in (autoresponder_states.get(user_id, {}).get("selected_accounts") or [])
            ):
                active_services.append("Автоответчик")

            # Почта (mailboxer/postman)
            if postman_states.get(user_id, {}).get("active"):
                sel_accs = postman_states.get(user_id, {}).get("selected_accounts") or []
                sel_postman = postman_states.get(user_id, {}).get("selected_postman")
                if phone in sel_accs or phone == sel_postman:
                    active_services.append("Почта")

            # Автоподписка (по активным задачам вида autosubscribe:{phone})
            user_tasks = active_tasks.get(user_id, {}) if 'active_tasks' in globals() else {}
            for t_name, t in list(user_tasks.items()):
                if t_name == f"autosubscribe:{phone}" and not t.done() and not t.cancelled():
                    active_services.append("Автоподписка")
                    break
        except Exception:
            # В случае ошибки не блокируем деавторизацию
            pass

        if active_services:
            services_list = ", ".join([f'"{name}"' for name in active_services])
            alert_text = (
                f"Для деавторизации аккаунта остановите его работу в сервисе {services_list}."
            )
            await call.answer(alert_text, show_alert=True)
            return
        # Найти имя сессии по номеру телефона
        session_name = None
        for acc in accounts:
            if acc.get("phone") == phone:
                session_name = acc.get("name", phone)
                break

        # 1) Перед деавторизацией аккуратно гасим все сервисы для этого аккаунта
        try:
            # 1.1 Останавливаем общие задачи сервисов, если они могут затрагивать этот аккаунт
            # Рассылка
            try:
                if user_id in mailing_states and (
                    phone in (mailing_states.get(user_id, {}).get("selected_accounts") or [])
                ):
                    await stop_task(user_id, "mailing")
            except Exception:
                pass
            # Автоответчик
            try:
                if user_id in autoresponder_states and (
                    phone in (autoresponder_states.get(user_id, {}).get("selected_accounts") or [])
                ):
                    await stop_task(user_id, "autoresponder")
            except Exception:
                pass
            # Почта (mailboxer)
            try:
                if user_id in postman_states:
                    sel_accs = postman_states.get(user_id, {}).get("selected_accounts") or []
                    sel_postman = postman_states.get(user_id, {}).get("selected_postman")
                    if phone in sel_accs or phone == sel_postman:
                        await stop_task(user_id, "mailboxer")
            except Exception:
                pass
            # Автоподписка конкретного телефона
            try:
                await stop_task(user_id, f"autosubscribe:{phone}")
            except Exception:
                pass
            # 1.2 Останавливаем трекер диалогов и снимаем обработчики событий для этой сессии
            if session_name:
                try:
                    await stop_task(user_id, f"dialogs_monitor_{session_name}")
                except Exception:
                    pass
                try:
                    await remove_event_handlers(user_id, session_name)
                except Exception:
                    pass
                # 1.3 Отключаем именно этого клиента
                try:
                    await disconnect_client(user_id, session_name)
                except Exception:
                    pass
        except Exception:
            # Не блокируем деавторизацию, даже если остановка сервисов дала сбой
            pass
        
        # Загружаем полную конфигурацию пользователя
        license_type = user_states.get(f"{user_id}_license_type")
        if not license_type:
            license_type = detect_license_type(user_id)
            if license_type:
                user_states[f"{user_id}_license_type"] = license_type
        
        user_dir = get_user_dir(user_id, license_type)
        config_path = os.path.join(user_dir, "config.json")
        
        # Загружаем существующую конфигурацию
        config = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception:
                config = {}
        
        print(f"🔍 [DEAUTH] Загружена конфигурация для пользователя {user_id}: {len(config.get('accounts', []))} аккаунтов")
        print(f"🔍 [DEAUTH] Деавторизуем аккаунт с телефоном: {phone}")
        
        # Удаляем только деавторизуемый аккаунт, сохраняя все остальные данные
        if "accounts" in config:
            original_count = len(config["accounts"])
            config["accounts"] = [acc for acc in config["accounts"] if acc.get("phone") != phone]
            new_count = len(config["accounts"])
            print(f"🔍 [DEAUTH] Удален аккаунт: было {original_count}, стало {new_count}")
        
        # Сохраняем обновленную конфигурацию
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        
        print(f"🔍 [DEAUTH] Конфигурация сохранена с {len(config.get('accounts', []))} аккаунтами")
        
        # Удаляем .session файл по имени сессии
        sessions_dir = os.path.join(get_user_subdir(user_id, "bot", license_type), "sessions")
        if session_name:
            session_path = os.path.join(sessions_dir, f"{session_name}.session")
            if os.path.exists(session_path):
                try:
                    os.remove(session_path)
                except Exception as e:
                    print(f"Ошибка при удалении {session_path}: {e}")
                    # Удаляем сессию из license.json
        remove_session_from_all_subdirs(user_id, session_name)
        remove_session_from_license(user_id, session_name)
        
        # Помечаем сессию как деавторизованную в cookies.json (НЕ УДАЛЯЕМ!)
        try:
            cookies_file = "cookies.json"
            if os.path.exists(cookies_file):
                with open(cookies_file, "r", encoding="utf-8") as f:
                    cookies_data = json.load(f)
                
                user_id_str = str(user_id)
                if user_id_str in cookies_data and session_name in cookies_data[user_id_str]:
                    # Добавляем пометку о деавторизации
                    from datetime import datetime
                    deauth_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    # Добавляем поле deauthorized с датой
                    cookies_data[user_id_str][session_name]["deauthorized"] = deauth_date
                    
                    with open(cookies_file, "w", encoding="utf-8") as f:
                        json.dump(cookies_data, f, ensure_ascii=False, indent=2)
                    
                    print(f"✅ Сессия {session_name} помечена как деавторизованная в cookies.json")
        except Exception as e:
            print(f"⚠️ Не удалось обновить cookies.json: {e}")
        
        # Обновляем информацию об аккаунтах в логах после удаления
        update_user_accounts_info(user_id)
        
        # Получаем обновлённый список аккаунтов
        updated_accounts = load_user_accounts(user_id)
        if not updated_accounts:
            if user_languages.get(user_id, "ru") == "ru":
                text = "Нет аккаунтов для деавторизации."
            else:
                text = "No accounts to deauthorize."
        else:
            if user_languages.get(user_id, "ru") == "ru":
                text = "Выберите аккаунт для деавторизации:"
            else:
                text = "Select account to deauthorize:"
        try:
            # Используем delete_and_send_image чтобы заменить предыдущее сообщение
            await delete_and_send_image(
                call.message,
                "nonexistent_image.png",  # Несуществующее изображение для fallback на текст
                text,
                reply_markup=get_deauth_accounts_menu(user_id)
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        user_states[user_id] = "deauth_menu"

    elif data == "subscription":
        license_type = user_states.get(f"{user_id}_license_type")
        if not license_type:
            license_type = detect_license_type(user_id)
            if license_type:
                user_states[f"{user_id}_license_type"] = license_type
        
        if license_type == "owner":
            await call.answer("OWNER 🏆", show_alert=True)
        elif license_type == "admin":
            await call.answer("ADMIN 🎗", show_alert=True)
        elif license_type == "trial":
            # Для пробного периода показываем оставшееся время
            time_left = get_freetrial_time_left(user_id)
            if time_left > 0:
                hours = time_left // 3600
                minutes = (time_left % 3600) // 60
                seconds = time_left % 60
                if user_languages.get(user_id, "ru") == "ru":
                    msg = f"Пробный период: {hours:02d}:{minutes:02d}:{seconds:02d}"
                else:
                    msg = f"Free trial: {hours:02d}:{minutes:02d}:{seconds:02d}"
                await call.answer(msg, show_alert=True)
            else:
                message = "Пробный период истёк." if user_languages.get(user_id, "ru") == "ru" else "Free trial expired."
                await call.answer(message, show_alert=True)
        else:
            lic = load_licenses().get(str(user_id))
            if lic:
                activated_at = lic.get("activated_at", 0)
                now = int(time.time())
                base_end_ts = activated_at + LICENSE_DURATION_DAYS * 86400
                effective_end_ts = base_end_ts + get_referral_bonus_seconds(user_id)
                seconds_left = effective_end_ts - now
                if seconds_left > 0:
                    days = seconds_left // 86400
                    hours = (seconds_left % 86400) // 3600
                    minutes = (seconds_left % 3600) // 60
                    if user_languages.get(user_id, "ru") == "ru":
                        msg = f"Осталось: {days} дней {hours} часов {minutes} минут"
                    else:
                        msg = f"Remaining: {days} days {hours} hours {minutes} minutes"
                    await call.answer(msg, show_alert=True)
                else:
                    message = "Срок действия вашей лицензии истёк." if user_languages.get(user_id, "ru") == "ru" else "Your license has expired."
                    await call.answer(message, show_alert=True)
            else:
                message = "Лицензия не найдена." if user_languages.get(user_id, "ru") == "ru" else "License not found."
                await call.answer(message, show_alert=True)

    elif data == "logout":
        try:
            if user_languages.get(user_id, "ru") == "ru":
                text = "⚠️ Внимание:\nВыход приведёт к деавторизации ваших Telegram аккаунтов из бота, а так же к удалению всех текстовых шаблонов.\n\nВы уверены, что хотите выйти ?"
            else:
                text = "⚠️ Warning:\nLogging out will deauthorize your Telegram accounts from the bot and also delete all text templates.\n\nAre you sure you want to log out?"
            markup = get_logout_confirmation_menu() if user_languages.get(user_id, "ru") == "ru" else get_logout_confirmation_menu_en()
            # Используем delete_and_send_image чтобы заменить текущее сообщение на предупреждение
            await delete_and_send_image(
                call.message,
                "nonexistent_image.png",  # Несуществующее изображение для fallback на текст
                text,
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "logout_confirm":
        # Быстро подтверждаем колбэк и мгновенно возвращаем пользователя в стартовое меню.
        # Вся тяжёлая очистка выполняется в фоне, чтобы не блокировать UI.
        try:
            await call.answer()
        except Exception:
            pass
        # Мгновенно переключаем UI на стартовое меню
        try:
            await delete_and_send_image(
                call.message,
                "start_menu.png",
                "🔑 Подписка:\nBasic 15$ | Premium 20$ | PRO 25$\n\n🧩 Количество аккаунтов:\nBasic x5 | Premium x10 | PRO x15\n\n⏳ Срок действия:\n30 дней с момента активации ключа\n\n\n",
                reply_markup=get_start_menu(),
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise

        async def _perform_logout_flow(user_id_inner: int):
            try:
                user_states[user_id_inner] = "wait_license"
                try:
                    await connection_manager.stop_monitoring(user_id_inner)
                except Exception:
                    pass
                # Останавливаем потенциально активные сервисы заранее, чтобы они не держали ресурсы
                try:
                    await stop_task(user_id_inner, "autoresponder")
                except Exception:
                    pass
                # Останавливаем рассылку (если запускалась как задача "mailing")
                try:
                    await stop_task(user_id_inner, "mailing")
                except Exception:
                    pass
                # Останавливаем автоподписку для всех аккаунтов пользователя
                try:
                    if user_id_inner in active_tasks:
                        for tname in list(active_tasks[user_id_inner].keys()):
                            if tname.startswith("autosubscribe:"):
                                try:
                                    await stop_task(user_id_inner, tname)
                                except Exception:
                                    pass
                except Exception:
                    pass
                # Останавливаем трекер диалогов по всем сессиям
                try:
                    if user_id_inner in active_clients:
                        for _session_name in list(active_clients[user_id_inner].keys()):
                            try:
                                await stop_task(user_id_inner, f"dialogs_monitor_{_session_name}")
                            except Exception:
                                pass
                except Exception:
                    pass
                # Дополнительно пытаемся остановить mailboxer как задачу (если он был зарегистрирован в active_tasks)
                try:
                    await stop_task(user_id_inner, "mailboxer")
                except Exception:
                    pass
                try:
                    if user_id_inner in active_clients:
                        for _session_name in list(active_clients[user_id_inner].keys()):
                            try:
                                await remove_event_handlers(user_id_inner, _session_name)
                            except Exception:
                                pass
                except Exception:
                    pass
                try:
                    if user_id_inner in active_clients:
                        for _session_name in list(active_clients[user_id_inner].keys()):
                            try:
                                await stop_task(user_id_inner, f"dialogs_monitor_{_session_name}")
                            except Exception:
                                pass
                except Exception:
                    pass

                # Пытаемся аккуратно отключить все клиенты, но не зависаем бесконечно
                try:
                    await asyncio.wait_for(disconnect_all_clients(user_id_inner), timeout=8)
                except Exception:
                    # При таймауте/ошибке продолжаем выход, выполняя мягкую очистку структур
                    try:
                        if user_id_inner in active_clients:
                            active_clients[user_id_inner].clear()
                    except Exception:
                        pass

                if user_id_inner in active_tasks:
                    for task_name in list(active_tasks[user_id_inner].keys()):
                        await stop_task(user_id_inner, task_name)

                if user_id_inner in mailing_states:
                    del mailing_states[user_id_inner]
                    update_service_state("mailing_states", user_id_inner, None)
                if user_id_inner in postman_states:
                    del postman_states[user_id_inner]
                    update_service_state("postman_states", user_id_inner, None)
                if user_id_inner in autoresponder_states:
                    del autoresponder_states[user_id_inner]
                    update_service_state("autoresponder_states", user_id_inner, None)

                license_type_in = user_states.get(f"{user_id_inner}_license_type")
                if not license_type_in:
                    license_type_in = detect_license_type(user_id_inner)
                    if license_type_in:
                        user_states[f"{user_id_inner}_license_type"] = license_type_in
                user_dir_in = get_user_dir(user_id_inner, license_type_in)
                config_path_in = os.path.join(user_dir_in, "config.json")
                if os.path.exists(config_path_in):
                    try:
                        with open(config_path_in, "r", encoding="utf-8") as f:
                            config_in = json.load(f)
                        config_in.pop("api_id", None)
                        config_in.pop("api_hash", None)
                        with open(config_path_in, "w", encoding="utf-8") as f:
                            json.dump(config_in, f, ensure_ascii=False, indent=2)
                    except Exception:
                        pass

                # Даем шанс задачам/клиентам полностью завершиться, чтобы не трогать .session во время записи
                try:
                    for _ in range(5):  # до ~5 секунд ожидания при необходимости
                        has_active_tasks = False
                        try:
                            if user_id_inner in active_tasks and any(
                                (t is not None and not t.done()) for t in active_tasks[user_id_inner].values()
                            ):
                                has_active_tasks = True
                        except Exception:
                            has_active_tasks = False
                        has_active_clients = bool(user_id_inner in active_clients and active_clients[user_id_inner])
                        if not has_active_tasks and not has_active_clients:
                            break
                        await asyncio.sleep(1)
                except Exception:
                    pass

                try:
                    root = get_project_root()
                    base_user_dir = os.path.join(root, "user")
                    plain_dir_in = os.path.join(base_user_dir, str(user_id_inner))
                    suffix_dir_in = None
                    if user_dir_in and os.path.isdir(user_dir_in):
                        suffix_dir_in = user_dir_in
                    else:
                        for suf in ["_owner", "_admin", "_pro", "_premium", "_basic", "_trial"]:
                            candidate = os.path.join(base_user_dir, f"{user_id_inner}{suf}")
                            if os.path.isdir(candidate):
                                suffix_dir_in = candidate
                                break
                    if suffix_dir_in:
                        if os.path.exists(plain_dir_in):
                            shutil.rmtree(plain_dir_in, ignore_errors=True)
                        os.rename(suffix_dir_in, plain_dir_in)
                    else:
                        user_states[f"{user_id_inner}_force_plain_create"] = True
                        os.makedirs(plain_dir_in, exist_ok=True)
                    settings_path_in = os.path.join(plain_dir_in, "settings.json")
                    if not os.path.exists(settings_path_in):
                        with open(settings_path_in, "w", encoding="utf-8") as f:
                            json.dump({}, f, ensure_ascii=False, indent=2)
                    for item in os.listdir(plain_dir_in):
                        full_path = os.path.join(plain_dir_in, item)
                        if os.path.abspath(full_path) == os.path.abspath(settings_path_in):
                            continue
                        if os.path.isfile(full_path) or os.path.islink(full_path):
                            try:
                                os.remove(full_path)
                            except Exception:
                                pass
                        elif os.path.isdir(full_path):
                            try:
                                shutil.rmtree(full_path, ignore_errors=True)
                            except Exception:
                                pass
                    # При выходе отмечаем authorized=false и в license.json, и в freetrial.json (если записи есть)
                    try:
                        licenses = load_licenses()
                        rec = licenses.get(str(user_id_inner))
                        if isinstance(rec, dict):
                            rec["authorized"] = False
                            licenses[str(user_id_inner)] = rec
                            save_licenses(licenses)
                    except Exception:
                        pass
                    try:
                        ft = load_freetrial()
                        rec2 = ft.get(str(user_id_inner))
                        if isinstance(rec2, dict):
                            rec2["authorized"] = False
                            ft[str(user_id_inner)] = rec2
                            save_freetrial(ft)
                    except Exception:
                        pass
                except Exception:
                    pass
                try:
                    user_states.pop(f"{user_id_inner}_force_plain_create", None)
                except Exception:
                    pass

                try:
                    root = get_project_root()
                    base_user_dir = os.path.join(root, "user")
                    for suf in ("_owner", "_admin", "_pro", "_premium", "_basic", "_trial"):
                        extra = os.path.join(base_user_dir, f"{user_id_inner}{suf}")
                        if os.path.isdir(extra):
                            try:
                                shutil.rmtree(extra, ignore_errors=True)
                            except Exception:
                                pass
                except Exception:
                    pass

                try:
                    user_states.pop(f"{user_id_inner}_license_type", None)
                except Exception:
                    pass

                mailboxer_in = user_sessions.get(user_id_inner, {}).get("mailboxer")
                if mailboxer_in:
                    if "stop_event" in mailboxer_in and mailboxer_in["stop_event"]:
                        stop_event = mailboxer_in["stop_event"]
                        stop_event.set()
                    if "process" in mailboxer_in and mailboxer_in["process"]:
                        p = mailboxer_in["process"]
                        if p.is_alive():
                            p.terminate()
                            p.join(timeout=5)
                    print(f"[LOGOUT] Начинаем удаление обработчиков для user_id: {user_id_inner}")
                    if user_id_inner in active_clients:
                        print(f"[LOGOUT] Активные клиенты для user_id {user_id_inner}: {list(active_clients[user_id_inner].keys())}")
                        for session_name in active_clients[user_id_inner].keys():
                            print(f"[LOGOUT] Удаляем обработчики для: {session_name}")
                            await remove_event_handlers(user_id_inner, session_name)
                    else:
                        print(f"[LOGOUT] Нет активных клиентов для user_id {user_id_inner}")
                    accounts = load_user_accounts(user_id_inner)
                    for acc in accounts:
                        session_name = acc.get("name")
                        if session_name:
                            print(f"[LOGOUT] Удаляем обработчики для аккаунта: {session_name}")
                            await remove_event_handlers(user_id_inner, session_name)
                    user_sessions[user_id_inner].pop("mailboxer")

                # UI уже переключён мгновенно выше, повторно не трогаем
            except Exception:
                pass

        asyncio.create_task(_perform_logout_flow(user_id))
        return

    elif data == "logout_cancel":
        # Пользователь отменил выход - возвращаемся в главное меню с изображением
        try:
            await delete_and_send_image(
                call.message,
                "start_menu.png",
                "Добро пожаловать!" if user_languages.get(user_id, "ru") == "ru" else "Welcome!",
                reply_markup=get_main_inline_menu(),
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return



    elif data == "mailing_templates":
        accounts = get_active_accounts_by_sessions(user_id)
        if not accounts:
            message = "Нет авторизованных аккаунтов." if user_languages.get(user_id, "ru") == "ru" else "No authorized accounts."
            await call.answer(message, show_alert=True)
            return
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        for acc in accounts:
            if acc.get("username"):
                label = f"@{acc['username']}"
            elif acc.get("name"):
                label = acc["name"]
            else:
                label = acc.get("phone")
            markup.inline_keyboard.append([InlineKeyboardButton(text=label, callback_data=f"template_acc_{acc.get('phone')}")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="message_mailing")])
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Выберите аккаунт для добавления/изменения шаблона:" if user_languages.get(user_id, "ru") == "ru" else "Select account to add/edit template:",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        user_states[user_id] = "select_template_account"

    elif data == "back_to_templates_select_account":
        accounts = load_user_accounts(user_id)
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        for acc in accounts:
            if acc.get("username"):
                label = f"@{acc['username']}"
            elif acc.get("name"):
                label = acc["name"]
            else:
                label = acc.get("phone")
            markup.inline_keyboard.append([InlineKeyboardButton(text=label, callback_data=f"template_acc_{acc.get('phone')}")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="message_mailing")])
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Выберите аккаунт для добавления/изменения шаблона:" if user_languages.get(user_id, "ru") == "ru" else "Select account to add/edit template:",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        user_states[user_id] = "select_template_account"

    elif data.startswith("template_acc_"):
        phone = data.replace("template_acc_", "")
        accounts = load_user_accounts(user_id)
        acc = next((a for a in accounts if a.get("phone") == phone), None)
        if not acc:
            message = "Аккаунт не найден." if user_languages.get(user_id, "ru") == "ru" else "Account not found."
            await call.message.answer(message)
            return
        templates = []
        i = 1
        while True:
            key = f"template{i}"
            if key in acc:
                templates.append(acc[key])
                i += 1
            else:
                break
        if not templates:
            user_states[user_id] = f"wait_template_{phone}"
            try:
                # Отправляем сообщение и сохраняем его ID для последующего удаления
                sent_message = await delete_and_send_image(
                    call.message,
                    "mailing.png",
                    "Введите текстовый шаблон:" if user_languages.get(user_id, "ru") == "ru" else "Enter text template:",
                    reply_markup=get_back_to_templates_select_account_menu(),
                    user_id=user_id
                )
                # Сохраняем ID сообщения для последующего удаления
                user_states[f"{user_id}_template_message_id"] = sent_message.message_id
            except TelegramAPIError as e:
                if "message is not modified" not in str(e):
                    raise
        else:
            try:
                # Отправляем сообщение и сохраняем его ID для последующего удаления
                sent_message = await delete_and_send_image(
                    call.message,
                    "mailing.png",
                    "Выберите шаблон для просмотра/редактирования:" if user_languages.get(user_id, "ru") == "ru" else "Select template to view/edit:",
                    reply_markup=get_templates_list_menu(phone, templates),
                    user_id=user_id
                )
                # Сохраняем ID сообщения для последующего удаления
                user_states[f"{user_id}_template_message_id"] = sent_message.message_id
            except TelegramAPIError as e:
                if "message is not modified" not in str(e):
                    raise
            user_states[user_id] = f"templates_list_{phone}"

    elif data.startswith("add_template|"):
        _, phone = data.split("|", 1)
        user_states[user_id] = f"wait_template_{phone}"
        try:
            # Отправляем сообщение и сохраняем его ID для последующего удаления
            sent_message = await delete_and_send_image(
                call.message,
                "mailing.png",
                "Введите текстовый шаблон:",
                reply_markup=get_back_to_templates_select_account_menu(),
                user_id=user_id
            )
            # Сохраняем ID сообщения для последующего удаления
            user_states[f"{user_id}_template_message_id"] = sent_message.message_id
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise

    elif data.startswith("show_template|"):
        _, phone, idx = data.split("|", 2)
        idx = int(idx)
        accounts = load_user_accounts(user_id)
        acc = next((a for a in accounts if a.get("phone") == phone), None)
        if not acc:
            try:
                await edit_text_or_safe_send(
                    call.message,
                    "Аккаунт не найден. Вернитесь и выберите аккаунт снова.",
                    reply_markup=get_accounts_for_templates_menu(user_id)
                )
            except TelegramAPIError as e:
                if "message is not modified" not in str(e):
                    raise
            user_states[user_id] = "select_template_account"
            return
        key = f"template{idx}"
        template_text = acc.get(key, "Шаблон не найден.")
        view_menu = InlineKeyboardMarkup(inline_keyboard=[])
        view_menu.inline_keyboard.append([
            InlineKeyboardButton(text="Удалить 🗑", callback_data=f"delete_template|{phone}|{idx}"),
            InlineKeyboardButton(text="Редактировать ✍️", callback_data=f"edit_template|{phone}|{idx}")
        ])
        view_menu.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data=f"back_to_templates|{phone}")])
        try:
            # Отправляем сообщение и сохраняем его ID для последующего удаления
            sent_message = await delete_and_send_image(
                call.message,
                "mailing.png",
                f"Шаблон #{idx}\n\n\n{template_text}",
                reply_markup=view_menu,
                user_id=user_id
            )
            # Сохраняем ID сообщения для последующего удаления
            user_states[f"{user_id}_template_message_id"] = sent_message.message_id
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        user_states[user_id] = f"template_view_{phone}_{idx}"
    elif data.startswith("delete_template|"):
        _, phone, idx = data.split("|", 2)
        idx = int(idx)
        accounts = load_user_accounts(user_id)
        for acc in accounts:
            if acc.get("phone") == phone:
                key = f"template{idx}"
                if key in acc:
                    del acc[key]
                    i = idx + 1
                    while f"template{i}" in acc:
                        acc[f"template{i-1}"] = acc[f"template{i}"]
                        del acc[f"template{i}"]
                        i += 1
        save_user_accounts(user_id, accounts)
        acc = next((a for a in accounts if a.get("phone") == phone), None)
        templates = []
        i = 1
        while True:
            key = f"template{i}"
            if key in acc:
                templates.append(acc[key])
                i += 1
            else:
                break
        if templates:
            # Отправляем сообщение и сохраняем его ID для последующего удаления
            sent_message = await delete_and_send_image(
                call.message,
                "mailing.png",
                "Выберите шаблон для просмотра/редактирования:",
                reply_markup=get_templates_list_menu(phone, templates),
                user_id=user_id
            )
            # Сохраняем ID сообщения для последующего удаления
            user_states[f"{user_id}_template_message_id"] = sent_message.message_id
            user_states[user_id] = f"templates_list_{phone}"
        else:
            # Отправляем сообщение и сохраняем его ID для последующего удаления
            sent_message = await delete_and_send_image(
                call.message,
                "mailing.png",
                "Введите текстовый шаблон:",
                reply_markup=get_back_to_templates_select_account_menu(),
                user_id=user_id
            )
            # Сохраняем ID сообщения для последующего удаления
            user_states[f"{user_id}_template_message_id"] = sent_message.message_id
            user_states[user_id] = f"wait_template_{phone}"

    elif data.startswith("edit_template|"):
        _, phone, idx = data.split("|", 2)
        user_states[user_id] = f"edit_template_{phone}_{idx}"
        try:
            # Отправляем сообщение и сохраняем его ID для последующего удаления
            sent_message = await delete_and_send_image(
                call.message,
                "mailing.png",
                "Введите новый текст для шаблона:",
                reply_markup=get_back_to_templates_select_account_menu()
            )
            # Сохраняем ID сообщения для последующего удаления
            user_states[f"{user_id}_template_message_id"] = sent_message.message_id
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
    elif data.startswith("back_to_templates|"):
        phone = data.replace("back_to_templates|", "")
        accounts = load_user_accounts(user_id)
        acc = next((a for a in accounts if a.get("phone") == phone), None)
        templates = []
        i = 1
        while True:
            key = f"template{i}"
            if key in acc:
                templates.append(acc[key])
                i += 1
            else:
                break
        try:
            # Отправляем сообщение и сохраняем его ID для последующего удаления
            sent_message = await delete_and_send_image(
                call.message,
                "mailing.png",
                "Выберите шаблон для просмотра/редактирования:",
                reply_markup=get_templates_list_menu(phone, templates)
            )
            # Сохраняем ID сообщения для последующего удаления
            user_states[f"{user_id}_template_message_id"] = sent_message.message_id
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        user_states[user_id] = f"templates_list_{phone}"

    elif data == "message_mailing":
        # При входе в раздел — быстрый гейт доступа
        if not is_license_valid(user_id):
            try:
                ft = load_freetrial()
            except Exception:
                ft = {}
            if str(user_id) in ft and not is_freetrial_valid(user_id):
                alert_text = "Пробный период закончился. Ваши активные сервисы остановлены."
            else:
                alert_text = "Подписка закончилась. Ваши активные сервисы остановлены."
            try:
                await call.answer(alert_text, show_alert=True)
            except Exception:
                pass
            await handle_access_expired(user_id)
            return
        # Отправляем одно фото-сообщение с подписью и меню
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Рассылка." if user_languages.get(user_id, "ru") == "ru" else "Mailing.",
                reply_markup=mailing_message_menu(user_id),
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        user_states[user_id] = "mailing_menu"
        
        # Инициализируем состояние рассылки
        if user_id not in mailing_states:
            mailing_states[user_id] = {
                "step": "mailing_menu",
                "selected_accounts": [],
                "template_mode": None,
                "template_index": None,
                "selected_folder": None,
                "logging_enabled": True,
                "alternate_templates": True,
                "resume_state": None
            }


    elif data == "mailing_expand":
        # Снимаем флаг свернутости
        session = user_sessions.get(user_id, {}).get("pushmux")
        if session:
            session["minimized"] = False

        # Восстанавливаем логирование и активность
        if user_id in mailing_states:
            mailing_states[user_id]["logging_enabled"] = True
            mailing_states[user_id]["minimized"] = False

        # Сохраняем состояние активных сессий для восстановления после перезапуска
        save_reconnect_state()

        # Отправляем основное сообщение
        await call.message.answer(
            "Рассылка развёрнута. Логирование в чат возобновлено." if user_languages.get(user_id, "ru") == "ru" else "Mailing is active again. Logging to chat resumed.",
            reply_markup=get_mailing_active_keyboard()
        )
        
        # Проверяем состояние перерывов аккаунтов
        break_info = get_accounts_break_status(user_id)
        if break_info:
            # Формируем сообщение о перерывах
            if user_languages.get(user_id, "ru") == "ru":
                break_message = "📋 Аккаунты находятся на перерыве:\n\n"
            else:
                break_message = "📋 Accounts are on break:\n\n"
            for account in break_info:
                break_message += f"{account['nickname']} - {account['time_left']} 🟡\n"
            
            await call.message.answer(break_message)
        
        return
    # --- Запуск рассылки ---
    elif data == "mailing_start":
        # Всегда начинаем с выбора аккаунтов, сбрасываем предыдущее состояние
        if user_id in mailing_states:
            # Сбрасываем состояние рассылки
            mailing_states[user_id] = {
                "step": "select_accounts",
                "selected_accounts": [],
                "template_mode": None,
                "template_index": None,
                "selected_folder": None,
                "logging_enabled": True,
                "alternate_templates": True,
                "resume_state": None
            }

        # --- Проверка доступа перед запуском ---
        if not is_license_valid(user_id):
            try:
                ft = load_freetrial()
            except Exception:
                ft = {}
            if str(user_id) in ft and not is_freetrial_valid(user_id):
                alert_text = "Пробный период закончился. Ваши активные сервисы остановлены."
            else:
                alert_text = "Подписка закончилась. Ваши активные сервисы остановлены."
            try:
                await call.answer(alert_text, show_alert=True)
            except Exception:
                pass
            await handle_access_expired(user_id)
            return

        accounts = load_user_accounts(user_id)
        if not accounts:
            await call.answer("Нет авторизованных аккаунтов.", show_alert=True)
            return

        # --- ПРОВЕРКУ ШАБЛОНОВ переносим на этап "Далее" ---

        if user_id not in user_sessions:
            user_sessions[user_id] = {}

        # Проверка: если pushmux уже запущен — не запускать второй раз
        if "pushmux" in user_sessions[user_id]:
            pushmux_session = user_sessions[user_id]["pushmux"]
            if "process" in pushmux_session:
                proc = pushmux_session["process"]
                if proc.poll() is None:
                    await call.answer("", show_alert=False)
                    return
                else:
                    user_sessions[user_id].pop("pushmux")
            else:
                # Если процесс отсутствует, очищаем сессию
                user_sessions[user_id].pop("pushmux")


        # Инициализируем состояние рассылки
        if user_id not in mailing_states:
            mailing_states[user_id] = {
                "step": "select_accounts",
                "selected_accounts": [],
                "template_mode": None,
                "template_index": None,
                "selected_folder": None,
                "logging_enabled": True,
                "alternate_templates": True,
                "resume_state": None
            }
            # Сохраняем состояние в файл сразу после инициализации
            save_fn = globals().get("save_mailing_parameters")
            if callable(save_fn):
                try:
                    save_fn(user_id)
                except Exception:
                    pass
        
        # Создаем клавиатуру для выбора аккаунтов
        accounts = load_user_accounts(user_id)
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        for acc in accounts:
            nickname = (f"@{acc['username']}" if acc.get('username') else (acc.get('name') or acc.get('phone')))
            markup.inline_keyboard.append([InlineKeyboardButton(
                text=nickname, 
                callback_data=f"mailing_acc_{acc.get('phone')}"
            )])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Выбрать все", callback_data="mailing_select_all")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Далее ➡️", callback_data="mailing_next", disabled=True)])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="message_mailing")])
        
        try:
            # Отправляем сообщение и сохраняем его ID для последующего удаления
            sent_message = await delete_and_send_image(
                call.message,
                "mailing.png",
                "Выберите аккаунты для рассылки:",
                reply_markup=markup,
                user_id=user_id

            )
            # Сохраняем ID сообщения для последующего удаления
            user_states[f"{user_id}_mailing_message_id"] = sent_message.message_id
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        
        return


    elif data == "mailing_continue_no_templates":
        accounts = load_user_accounts(user_id)
        if not accounts:
            await call.answer("Нет авторизованных аккаунтов.", show_alert=True)
            return

        if user_id in user_sessions:
            await call.answer("", show_alert=False)
            return

        # Инициализируем состояние рассылки
        if user_id not in mailing_states:
            mailing_states[user_id] = {
                "step": "select_accounts",
                "selected_accounts": [],
                "template_mode": None,
                "template_index": None,
                "selected_folder": None,
                "logging_enabled": True,
                "alternate_templates": True,
                "resume_state": None
            }
            # Сохраняем состояние в файл сразу после инициализации
            save_fn = globals().get("save_mailing_parameters")
            if callable(save_fn):
                try:
                    save_fn(user_id)
                except Exception:
                    pass
        
        # Создаем клавиатуру для выбора аккаунтов
        accounts = load_user_accounts(user_id)
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        for acc in accounts:
            nickname = (f"@{acc['username']}" if acc.get('username') else (acc.get('name') or acc.get('phone')))
            markup.inline_keyboard.append([InlineKeyboardButton(
                text=nickname, 
                callback_data=f"mailing_acc_{acc.get('phone')}"
            )])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Выбрать все", callback_data="mailing_select_all")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Далее ➡️", callback_data="mailing_next", disabled=True)])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="message_mailing")])
        
        try:
            # Отправляем сообщение и сохраняем его ID для последующего удаления
            sent_message = await delete_and_send_image(
                call.message,
                "mailing.png",
                "Выберите аккаунты для рассылки:",
                reply_markup=markup,
                user_id=user_id
            )
            # Сохраняем ID сообщения для последующего удаления
            user_states[f"{user_id}_mailing_message_id"] = sent_message.message_id
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        
        user_states[user_id] = "mailing_menu"
        return



    elif data == "mailing_cancel_no_templates":
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Рассылка отменена.",
                reply_markup=mailing_message_menu(user_id)
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        user_states[user_id] = "mailing_menu"
        return
    



    # --- Обработчики для рассылки ---
    elif data == "mailing_select_all":
        if user_id not in mailing_states:
            mailing_states[user_id] = {
                "step": "select_accounts",
                "selected_accounts": [],
                "template_mode": None,
                "template_index": None,
                "selected_folder": None,
                "logging_enabled": True,
                "alternate_templates": True,
                "resume_state": None
            }
            # Сохраняем состояние в файл сразу после инициализации
            save_fn = globals().get("save_mailing_parameters")
            if callable(save_fn):
                try:
                    save_fn(user_id)
                except Exception:
                    pass
        
        # Выбираем все аккаунты
        accounts = load_user_accounts(user_id)
        mailing_states[user_id]["selected_accounts"] = [acc.get('phone') for acc in accounts]
        # Сохраняем изменения выбора аккаунтов
        save_fn = globals().get("save_mailing_parameters")
        if callable(save_fn):
            try:
                save_fn(user_id)
            except Exception:
                pass
        
        # Обновляем только клавиатуру с новыми галочками, не пересоздавая сообщение
        await update_mailing_accounts_keyboard(call, user_id, mailing_states[user_id]["selected_accounts"])
        return

    elif data.startswith("mailing_acc_"):
        phone = data.replace("mailing_acc_", "")
        if user_id not in mailing_states:
            mailing_states[user_id] = {
                "step": "select_accounts",
                "selected_accounts": [],
                "template_mode": None,
                "template_index": None,
                "selected_folder": None,
                "logging_enabled": True,
                "alternate_templates": True,
                "resume_state": None
            }
        
        state = mailing_states[user_id]
        selected = state.get("selected_accounts", [])
        
        # Переключаем выбор
        if phone in selected:
            selected.remove(phone)
        else:
            if len(selected) < 10:  # Ограничиваем количество аккаунтов
                selected.append(phone)
        
        state["selected_accounts"] = selected
        # Сохраняем изменения выбора аккаунтов
        save_fn = globals().get("save_mailing_parameters")
        if callable(save_fn):
            try:
                save_fn(user_id)
            except Exception:
                pass
        
        # Обновляем только клавиатуру с новыми галочками, не пересоздавая сообщение
        await update_mailing_accounts_keyboard(call, user_id, selected)
        return

    elif data == "mailing_next":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        selected_accounts = state.get("selected_accounts", [])
        
        if not selected_accounts:
            await call.answer("Выберите хотя бы один аккаунт.", show_alert=True)
            return
        # Проверяем наличие шаблонов у выбранных аккаунтов и показываем алерт здесь
        try:
            all_accounts = load_user_accounts(user_id) or []
            acc_by_phone = {acc.get("phone"): acc for acc in all_accounts}
            without_templates_display = []
            for ph in selected_accounts:
                acc = acc_by_phone.get(ph)
                if not acc:
                    continue
                has_template = any(key.startswith("template") for key in acc)
                if not has_template:
                    uname = acc.get("username")
                    if isinstance(uname, str) and uname.strip():
                        uname_clean = uname.strip()
                        if not uname_clean.startswith("@"):
                            uname_clean = "@" + uname_clean
                        display_name = uname_clean
                    else:
                        display_name = acc.get("name") or acc.get("phone") or "Без имени"
                    without_templates_display.append(display_name)
            if without_templates_display:
                if len(without_templates_display) == 1:
                    await call.answer(
                        f'У аккаунта {without_templates_display[0]} нет ни одного текстового сообщения в разделе "Шаблоны".',
                        show_alert=True
                    )
                else:
                    names = ", ".join(without_templates_display)
                    await call.answer(
                        f'У аккаунтов {names} нет ни одного текстового сообщения в разделе "Шаблоны".',
                        show_alert=True
                    )
                return
        except Exception:
            pass
        
        # Переходим к запросу "Последняя сводка"
        state["step"] = "select_summary"
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        save_fn = globals().get("save_mailing_parameters")
        if callable(save_fn):
            try:
                save_fn(user_id)
            except Exception:
                pass
        
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Да", callback_data="mailing_summary_yes")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Нет", callback_data="mailing_summary_no")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="mailing_start")])
        
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Последняя сводка:",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return



    # --- Обработчики для "Последняя сводка" ---
    elif data == "mailing_summary_yes":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        state = mailing_states[user_id]
        state["summary_enabled"] = True
        state["step"] = "summary_shown"
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        save_fn = globals().get("save_mailing_parameters")
        if callable(save_fn):
            try:
                save_fn(user_id)
            except Exception:
                pass
        summary_text = generate_summary_text(user_id)
        
        if summary_text and summary_text != "Статус предыдущего запуска не определён." and summary_text != "Нет активных процессов рассылки.":
            message_text = f"📊 Последняя сводка:\n\n{summary_text}"
        elif summary_text == "Нет активных процессов рассылки.":
            message_text = "ℹ️ Нет активных процессов рассылки."
        elif summary_text == "Статус предыдущего запуска не определён.":
            message_text = "ℹ️ Статус предыдущего запуска не определён."
        else:
            message_text = "ℹ️ Нет данных для отображения."
        
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Далее", callback_data="mailing_summary_next")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться", callback_data="mailing_summary_back")])
        
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                message_text,
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "mailing_summary_next":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        state = mailing_states[user_id]
        state["step"] = "select_mode"
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        save_fn = globals().get("save_mailing_parameters")
        if callable(save_fn):
            try:
                save_fn(user_id)
            except Exception:
                pass
        
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Ручная настройка", callback_data="mailing_mode_custom")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Автоматическая настройка", callback_data="mailing_mode_select")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Возобновить процесс", callback_data="mailing_mode_resume")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="mailing_next")])
        
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Выберите режим работы:",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "mailing_summary_back":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        state = mailing_states[user_id]
        state["summary_enabled"] = False
        state["step"] = "select_mode"
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        save_fn = globals().get("save_mailing_parameters")
        if callable(save_fn):
            try:
                save_fn(user_id)
            except Exception:
                pass
        
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Ручная настройка", callback_data="mailing_mode_custom")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Автоматическая настройка", callback_data="mailing_mode_select")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Возобновить процесс", callback_data="mailing_mode_resume")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="mailing_next")])
        
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Выберите режим работы:",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "mailing_summary_no":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        state = mailing_states[user_id]
        state["summary_enabled"] = False
        state["step"] = "select_mode"
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        save_fn = globals().get("save_mailing_parameters")
        if callable(save_fn):
            try:
                save_fn(user_id)
            except Exception:
                pass
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Ручная настройка", callback_data="mailing_mode_custom")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Автоматическая настройка", callback_data="mailing_mode_select")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Возобновить процесс", callback_data="mailing_mode_resume")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="mailing_next")])
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Выберите режим работы:",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "mailing_mode_custom":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        state["template_mode"] = "custom"
        state["step"] = "select_alternate_templates"
        state["account_templates"] = {}
        state["account_folders"] = {}
        state["current_account_index"] = 0
        # Persist
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        
        # Сохраняем настройки игнорирования
        save_ignore_settings(user_id, state.get("ignore_folders", {}), state.get("ignore_chats", {}))
        
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Да", callback_data="mailing_alternate_templates_yes")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Нет", callback_data="mailing_alternate_templates_no")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="message_mailing")])
        
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Включить чередование шаблонов?:",
                reply_markup=markup,
                user_id=user_id
                
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "mailing_mode_select":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        state["template_mode"] = "select"
        state["step"] = "select_alternate_templates"
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        
        # Сохраняем настройки игнорирования
        save_ignore_settings(user_id, state.get("ignore_folders", {}), state.get("ignore_chats", {}))
        
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Да", callback_data="mailing_alternate_templates_yes")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Нет", callback_data="mailing_alternate_templates_no")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="message_mailing")])
        
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Включить чередование шаблонов?:",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return
    elif data == "mailing_mode_resume":
        # Загружаем состояние из пользовательской директории
        resume_state = load_resume_state(user_id=user_id)
        ignore_settings = load_ignore_settings(user_id)
        
        # Проверяем, есть ли сохраненное состояние
        if not resume_state or not resume_state.get("accounts"):
            await call.answer("Нет сохраненного состояния для возобновления.", show_alert=True)
            return
        
        # Инициализируем состояние рассылки
        if user_id not in mailing_states:
            mailing_states[user_id] = {}
        state = mailing_states[user_id]
        
        if resume_state:
            state.update(resume_state)
        if ignore_settings:
            state["ignore_folders"] = ignore_settings.get("ignore_folders", {})
            state["ignore_chats"] = ignore_settings.get("ignore_chats", {})
        
        # ПРЕДОХРАНИТЕЛЬ 1: Проверяем условия срабатывания
        print(f"Проверяем предохранитель для user_id {user_id}")
        print(f"Resume state: {resume_state}")
        
        if await check_safety_guard_1(user_id, resume_state):
            print(f"Предохранитель сработал для user_id {user_id}")
            # Показываем меню предохранителя
            message_text, markup = await show_safety_guard_1_menu(user_id, resume_state)
            
            try:
                await delete_and_send_image(
                    call.message,
                    "mailing.png",
                    message_text,
                    reply_markup=markup,
                    user_id=user_id
                )
            except TelegramAPIError as e:
                if "message is not modified" not in str(e):
                    raise
            return
        else:
            print(f"Предохранитель НЕ сработал для user_id {user_id}")
        
        # Если предохранитель не сработал, продолжаем как обычно
        state["template_mode"] = "resume"
        state["step"] = "running"
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        save_fn = globals().get("save_mailing_parameters")
        if callable(save_fn):
            try:
                save_fn(user_id)
            except Exception:
                pass
        
        license_type = detect_license_type(user_id)
        await start_task(user_id, "mailing", async_mailing_flow(user_id, license_type))
        
        await call.message.answer(
            "Запуск процесса. Ожидайте...",
            reply_markup=get_mailing_active_keyboard()
        )
        
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Запуск процесса. Ожидайте...",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[])
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    # ОБРАБОТЧИКИ ПРЕДОХРАНИТЕЛЯ 1
    elif data == "safety_guard_wait":
        # Ждать перерыв - дождаться окончания самого длинного перерыва
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        resume_state = load_resume_state(user_id=user_id)
        
        if not resume_state or not resume_state.get("accounts"):
            await call.answer("Ошибка: нет сохраненного состояния для возобновления.", show_alert=True)
            return
        
        # Находим самый длинный перерыв
        max_break_time = 0
        max_break_timestamp = 0
        for account_data in resume_state["accounts"]:
            if account_data.get("break_until_timestamp", 0) > 0:
                break_remaining = account_data["break_until_timestamp"] - time.time()
                if break_remaining > max_break_time:
                    max_break_time = break_remaining
                    max_break_timestamp = account_data["break_until_timestamp"]
        
        if max_break_time <= 0:
            await call.answer("Нет активных перерывов для ожидания.", show_alert=True)
            return
        
        # ОБНОВЛЯЕМ СОСТОЯНИЕ В mailing_states
        state.update(resume_state)
        
        # Запускаем таймер обратного отсчета для всех аккаунтов
        await call.message.answer(
            f"⏳ Ожидание окончания перерыва: {int(max_break_time // 3600):02d}:{int((max_break_time % 3600) // 60):02d}:{int(max_break_time % 60):02d}\n\n",
            reply_markup=get_mailing_active_keyboard()
        )
        
        # Запускаем таймер обратного отсчета прямо здесь
        #await call.message.edit_text(
        #    "⏳ Ожидание окончания перерыва...",
        #    reply_markup=InlineKeyboardMarkup(inline_keyboard=[])
        #)
        
        # Ждем окончания самого длинного перерыва
        last_minute_logged = max_break_time // 60  # Отслеживаем последнюю минуту, для которой было отправлено сообщение
        
        while max_break_time > 0:
            # Проверяем, не была ли нажата кнопка "Стоп"
            if user_id not in mailing_states:
                await log_to_telegram(user_id, "⏹️ Ожидание перерыва прервано.", "mailing")
                return
            
            await asyncio.sleep(1)
            max_break_time -= 1
            
            # Отправляем обновление каждый час
            #current_minutes = max_break_time // 60
            #if current_minutes != last_minute_logged and current_minutes > 0 and current_minutes % 60 == 0:
            #       # Показываем время для каждого аккаунта отдельно
            #    for account_data in resume_state["accounts"]:
            #        if account_data.get("break_until_timestamp", 0) > 0:
            #            nickname = account_data.get('nickname', 'Unknown')
            #            remaining = account_data["break_until_timestamp"] - time.time()
            #            if remaining > 0:
            #                hours = int(remaining // 3600)
            #                minutes = int((remaining % 3600) // 60)
            #                seconds = int(remaining % 60)
            #                message = f"{nickname}: до конца перерыва осталось {hours:02d}:{minutes:02d}:{seconds:02d} 🟡"                 
            #                # Отправляем в Telegram
            #                await log_to_telegram(user_id, message, "mailing")               
            #    last_minute_logged = current_minutes
        
        # После окончания перерыва сбрасываем все состояния
        for account_data in resume_state["accounts"]:
            account_data["message_count"] = 0
            account_data["break_seconds_left"] = 0
            account_data["break_until_timestamp"] = 0
        
        # Сохраняем обновленное состояние
        save_resume_state(resume_state, user_id=user_id)
        
        # Обновляем состояние в mailing_states
        state.update(resume_state)

        await log_to_telegram(user_id, "❎ Перерыв завершён", "mailing")

        # Запускаем рассылку
        state["template_mode"] = "resume"
        state["step"] = "running"
        
        license_type = detect_license_type(user_id)
        await start_task(user_id, "mailing", async_mailing_flow(user_id, license_type))
        
        return
        
        # Показываем сообщение о ожидании
        try:
            await edit_text_or_safe_send(
                call.message,
                f"⏳ Ожидание окончания перерыва...\n"
                f"Самый длинный перерыв: {int(max_break_time // 60):02d}:{int(max_break_time % 60):02d}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[])
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        
        # ОБНОВЛЯЕМ СОСТОЯНИЕ В mailing_states
        state.update(resume_state)
        
        # Запускаем рассылку после ожидания
        state["template_mode"] = "resume"
        state["step"] = "running"
        
        license_type = detect_license_type(user_id)
        await start_task(user_id, "mailing", async_mailing_flow(user_id, license_type))
        
        return
    elif data == "safety_guard_force":
        # Принудительно продолжить - игнорировать перерывы
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        resume_state = load_resume_state(user_id=user_id)
        
        if not resume_state or not resume_state.get("accounts"):
            await call.answer("Ошибка: нет сохраненного состояния для возобновления.", show_alert=True)
            return
        
        # Сбрасываем все перерывы и обнуляем лимит для тех, у кого уже 30/30
        for account_data in resume_state["accounts"]:
            account_data["break_until_timestamp"] = 0
            account_data["break_seconds_left"] = 0
            # Если лимит уже достигнут, начинаем новый цикл отправки
            if account_data.get("message_count", 0) >= 30:
                account_data["message_count"] = 0
        
        # Сохраняем обновленное состояние
        save_resume_state(resume_state, user_id=user_id)
        
        # ОБНОВЛЯЕМ СОСТОЯНИЕ В mailing_states
        state.update(resume_state)
        
        # Останавливаем активные таймеры
        if user_id in active_tasks:
            for task_name in list(active_tasks[user_id].keys()):
                if "timer" in task_name.lower() or "countdown" in task_name.lower():
                    await stop_task(user_id, task_name)
        
        # Запускаем рассылку
        state["template_mode"] = "resume"
        state["step"] = "running"
        state["ignore_breaks"] = True  # Добавляем флаг игнорирования перерывов
        
        license_type = detect_license_type(user_id)
        await start_task(user_id, "mailing", async_mailing_flow(user_id, license_type))
        
        # Отправляем reply клавиатуру для управления рассылкой
        await call.message.answer(
            "🚀 Принудительное продолжение рассылки.",
            reply_markup=get_mailing_active_keyboard()
        )
        
        # Показываем сообщение о принудительном продолжении
        #try:
        #    await call.message.edit_text(
        #        "🚀 Принудительное продолжение рассылки...\n"
        #        "Все перерывы игнорированы.",
        #        reply_markup=InlineKeyboardMarkup(inline_keyboard=[])
        #    )
        #except TelegramAPIError as e:
        #    if "message is not modified" not in str(e):
        #        raise
        return

    elif data == "safety_guard_reset":
        # Сбросить все лимиты - обнулить message_count и break
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        resume_state = load_resume_state(user_id=user_id)
        
        if not resume_state or not resume_state.get("accounts"):
            await call.answer("Ошибка: нет сохраненного состояния для возобновления.", show_alert=True)
            return
        
        # Сбрасываем все лимиты и перерывы (устанавливаем 0 вместо None)
        for account_data in resume_state["accounts"]:
            account_data["message_count"] = 0
            account_data["break_until_timestamp"] = 0
            account_data["break_seconds_left"] = 0
        
        # Сохраняем обновленное состояние
        save_resume_state(resume_state, user_id=user_id)
        
        # ОБНОВЛЯЕМ СОСТОЯНИЕ В mailing_states
        state.update(resume_state)
        
        # Останавливаем активные таймеры
        if user_id in active_tasks:
            for task_name in list(active_tasks[user_id].keys()):
                if "timer" in task_name.lower() or "countdown" in task_name.lower():
                    await stop_task(user_id, task_name)
        
        # Запускаем рассылку
        state["template_mode"] = "resume"
        state["step"] = "running"
        state["ignore_breaks"] = True  # Добавляем флаг игнорирования перерывов
        
        license_type = detect_license_type(user_id)
        await start_task(user_id, "mailing", async_mailing_flow(user_id, license_type))
        
        # Отправляем reply клавиатуру для управления рассылкой
        await call.message.answer(
            "🔄 Лимиты успешно сброшены",
            reply_markup=get_mailing_active_keyboard()
        )
        
        # Показываем сообщение о сбросе лимитов
        #try:
        #    await call.message.edit_text(
        #        "🔄 Все лимиты сброшены! Запуск рассылки...",
        #        reply_markup=InlineKeyboardMarkup(inline_keyboard=[])
        #    )
        #except TelegramAPIError as e:
        #    if "message is not modified" not in str(e):
        #        raise
        return

    elif data == "mailing_templates_yes":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        state["alternate_templates"] = True
        # Дублируем флаг для согласованности с путями, где читается alternate_templates_enabled
        state["alternate_templates_enabled"] = True
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        state["template_index"] = 0  # Устанавливаем начальный индекс шаблона
        
        # Проверяем, является ли это режимом select configuration
        if state.get("template_mode") == "select":
            state["step"] = "select_template_type"
            
            # Загружаем шаблоны и отображаем их превью вместо T1/T2
            all_accounts = load_user_accounts(user_id)
            # Берём первый выбранный аккаунт для превью шаблонов
            selected_phones = state.get("selected_accounts", [])
            selected_accounts = [acc for acc in all_accounts if acc.get("phone") in selected_phones]
            preview_account = selected_accounts[0] if selected_accounts else (all_accounts[0] if all_accounts else {})
            template1 = preview_account.get("template1", "...")
            template2 = preview_account.get("template2", "...")

            # Динамический список шаблонов для режима select
            templates = get_templates_from_config(load_config(user_id), preview_account.get('phone')) if preview_account else []
            markup = InlineKeyboardMarkup(inline_keyboard=[])
            if templates:
                for idx, t in enumerate(templates):
                    markup.inline_keyboard.append([
                        InlineKeyboardButton(text=truncate_preview(t), callback_data=f"mailing_template_type_idx_{idx}")
                    ])
            else:
                # Нет ни одного шаблона — показываем уведомление и кнопку назад
                markup.inline_keyboard.append([InlineKeyboardButton(text="Нет шаблонов", callback_data="mailing_mode_select")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="mailing_mode_select")])
            
            try:
                await delete_and_send_image(
                    call.message,
                    "mailing.png",
                    "Выберите текстовое сообщение:",
                    reply_markup=markup,
                    user_id=user_id
                )
            except TelegramAPIError as e:
                if "message is not modified" not in str(e):
                    raise
            return
        elif state.get("template_mode") == "custom":
            # Для режима custom переходим к выбору шаблонов для каждого аккаунта
            state["step"] = "select_custom_templates"
            state["current_account_index"] = 0
            state["account_templates"] = {}
            state["account_folders"] = {}
            
            # Начинаем с первого аккаунта
            selected_phones = state.get("selected_accounts", [])
            if not selected_phones:
                await call.answer("Ошибка: нет выбранных аккаунтов.", show_alert=True)
                return
            
            # Получаем полные объекты аккаунтов по номерам телефонов
            all_accounts = load_user_accounts(user_id)
            selected_accounts = [acc for acc in all_accounts if acc.get("phone") in selected_phones]
            
            if not selected_accounts:
                await call.answer("Ошибка: не удалось найти выбранные аккаунты.", show_alert=True)
                return
            
            first_account = selected_accounts[0]
            account_nickname = first_account.get("username") or first_account.get("name") or first_account.get("phone")
            
            # Загружаем шаблоны выбранного аккаунта и показываем превью
            templates = get_templates_from_config(load_config(user_id), first_account.get('phone'))

            markup = InlineKeyboardMarkup(inline_keyboard=[])
            if templates:
                for idx, t in enumerate(templates):
                    markup.inline_keyboard.append([
                        InlineKeyboardButton(text=truncate_preview(t), callback_data=f"custom_template_idx_{idx}")
                    ])
            else:
                markup.inline_keyboard.append([InlineKeyboardButton(text="Нет шаблонов", callback_data="mailing_mode_custom")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="mailing_mode_custom")])
            
            try:
                await delete_and_send_image(
                    call.message,
                    "mailing.png",
                    f"Выберите текстовое сообщение для аккаунта {account_nickname}:",
                    reply_markup=markup,
                    user_id=user_id
                )
            except TelegramAPIError as e:
                if "message is not modified" not in str(e):
                    raise
            return
        else:
            # Для других режимов оставляем старый поток
            state["step"] = "select_logging"
            
            markup = InlineKeyboardMarkup(inline_keyboard=[])
            markup.inline_keyboard.append([InlineKeyboardButton(text="Да", callback_data="mailing_logging_yes")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="Нет", callback_data="mailing_logging_no")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="mailing_mode_custom")])
            
            try:
                await delete_and_send_image(
                    call.message,
                    "mailing.png",
                    "Добавить логирование статусов отправки сообщений?",
                    reply_markup=markup,
                    user_id=user_id
                )
            except TelegramAPIError as e:
                if "message is not modified" not in str(e):
                    raise
            return

    elif data.startswith("mailing_template_type_idx_"):
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        try:
            idx = int(data.replace("mailing_template_type_idx_", ""))
        except Exception:
            await call.answer("Некорректный индекс шаблона.", show_alert=True)
            return

        state = mailing_states[user_id]
        state["template_index"] = max(0, idx)
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        state["step"] = "select_folder_set"

        # Переходим к выбору папки (динамический список уже реализован в ветках выбора папок)
        # Для единообразия отправим пользователя в блок выбора папок для выбранного типа (T1/T2 не важен, дальше идёт общая логика)
        # Используем ту же отрисовку, что и при выборе типов: сформируем клавиатуру папок для первого выбранного аккаунта
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        try:
            selected_phones = state.get("selected_accounts", [])
            accounts = load_user_accounts(user_id)
            base_account = next((acc for acc in accounts if acc.get("phone") in selected_phones), None)
            if base_account:
                license_type = detect_license_type(user_id)
                user_dir = get_user_dir(user_id, license_type)
                config_path = os.path.join(user_dir, "config.json")
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                api_id = config.get("api_id")
                api_hash = config.get("api_hash")
                session_name = base_account.get("name") or base_account.get("phone")
                client = await get_or_create_client(user_id, session_name, api_id, api_hash, license_type)
                folders = await list_folders(client) if client else {}
            else:
                folders = {}
        except Exception:
            folders = {}

        if folders:
            for i, folder in folders.items():
                real_index_zero_based = i - 1
                markup.inline_keyboard.append([
                    InlineKeyboardButton(text=folder.get('title', str(i)), callback_data=f"mailing_folder_set_idx_{real_index_zero_based}")
                ])
        else:
            markup.inline_keyboard.append([InlineKeyboardButton(text="F1", callback_data="mailing_folder_set_f1")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="F2", callback_data="mailing_folder_set_f2")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="F3", callback_data="mailing_folder_set_f3")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="F4", callback_data="mailing_folder_set_f4")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="F5", callback_data="mailing_folder_set_f5")])

        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="mailing_mode_select")])

        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Выберите папку:",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "mailing_templates_no":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        state["alternate_templates"] = False
        # Дублируем флаг для согласованности с путями, где читается alternate_templates_enabled
        state["alternate_templates_enabled"] = False
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        state["template_index"] = 0  # Устанавливаем начальный индекс шаблона
        
        # Проверяем, является ли это режимом select configuration
        if state.get("template_mode") == "select":
            state["step"] = "select_template_type"
            
            # Загружаем шаблоны и отображаем их превью вместо T1/T2
            all_accounts = load_user_accounts(user_id)
            selected_phones = state.get("selected_accounts", [])
            selected_accounts = [acc for acc in all_accounts if acc.get("phone") in selected_phones]
            preview_account = selected_accounts[0] if selected_accounts else (all_accounts[0] if all_accounts else {})
            templates = get_templates_from_config(load_config(user_id), preview_account.get('phone')) if preview_account else []

            markup = InlineKeyboardMarkup(inline_keyboard=[])
            if templates:
                for idx, t in enumerate(templates):
                    markup.inline_keyboard.append([
                        InlineKeyboardButton(text=truncate_preview(t), callback_data=f"mailing_template_type_idx_{idx}")
                    ])
            else:
                markup.inline_keyboard.append([InlineKeyboardButton(text="Нет шаблонов", callback_data="mailing_mode_select")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="mailing_mode_select")])
            
            try:
                await delete_and_send_image(
                    call.message,
                    "mailing.png",
                    "Выберите текстовое сообщение:",
                    reply_markup=markup,
                    user_id=user_id
                )
            except TelegramAPIError as e:
                if "message is not modified" not in str(e):
                    raise
            return
        elif state.get("template_mode") == "custom":
            # Для режима custom переходим к выбору шаблонов для каждого аккаунта
            state["step"] = "select_custom_templates"
            state["current_account_index"] = 0
            state["account_templates"] = {}
            state["account_folders"] = {}
            
            # Начинаем с первого аккаунта
            selected_phones = state.get("selected_accounts", [])
            if not selected_phones:
                await call.answer("Ошибка: нет выбранных аккаунтов.", show_alert=True)
                return
            
            # Получаем полные объекты аккаунтов по номерам телефонов
            all_accounts = load_user_accounts(user_id)
            selected_accounts = [acc for acc in all_accounts if acc.get("phone") in selected_phones]
            
            if not selected_accounts:
                await call.answer("Ошибка: не удалось найти выбранные аккаунты.", show_alert=True)
                return
            
            first_account = selected_accounts[0]
            account_nickname = first_account.get("username") or first_account.get("name") or first_account.get("phone")
            
            # Загружаем шаблоны выбранного аккаунта и показываем превью
            markup = InlineKeyboardMarkup(inline_keyboard=[])
            templates = get_templates_from_config(load_config(user_id), first_account.get('phone'))
            if templates:
                for idx, t in enumerate(templates):
                    markup.inline_keyboard.append([
                        InlineKeyboardButton(text=truncate_preview(t), callback_data=f"custom_template_idx_{idx}")
                    ])
            else:
                markup.inline_keyboard.append([InlineKeyboardButton(text="Нет шаблонов", callback_data="mailing_mode_custom")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="mailing_mode_custom")])
            
            try:
                await delete_and_send_image(
                    call.message,
                    "mailing.png",
                    f"Выберите текстовое сообщение для аккаунта {account_nickname}:",
                    reply_markup=markup,
                    user_id=user_id
                )
            except TelegramAPIError as e:
                if "message is not modified" not in str(e):
                    raise
            return
        else:
            # Для других режимов оставляем старый поток
            state["step"] = "select_logging"
            
            markup = InlineKeyboardMarkup(inline_keyboard=[])
            markup.inline_keyboard.append([InlineKeyboardButton(text="Да", callback_data="mailing_logging_yes")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="Нет", callback_data="mailing_logging_no")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="mailing_mode_custom")])
            
            try:
                await delete_and_send_image(
                    call.message,
                    "mailing.png",
                    "Добавить логирование статусов отправки сообщений?",
                    reply_markup=markup,
                    user_id=user_id
                )
            except TelegramAPIError as e:
                if "message is not modified" not in str(e):
                    raise
            return

    # --- Новые обработчики для чередования шаблонов ---
    elif data == "mailing_alternate_templates_yes":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        
        # Специальная обработка для восстановленного состояния
        if state.get("original_step") == "select_alternate_templates":
            # Пользователь был на шаге выбора чередования шаблонов
            # Нужно показать правильное меню в зависимости от template_mode
            template_mode = state.get("template_mode")
            if template_mode == "select":
                state["step"] = "select_template_type"
            elif template_mode == "custom":
                state["step"] = "select_logging"
            else:
                state["step"] = "select_logging"
            # Убираем флаг оригинального шага
            state.pop("original_step", None)
        
        # Если template_mode не установлен, но есть selected_accounts,
        # значит пользователь выбрал режим, но не сохранил его
        if state.get("template_mode") is None and state.get("selected_accounts"):
            # Устанавливаем режим по умолчанию
            state["template_mode"] = "select"
        
        state["alternate_templates"] = True
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        
        # Проверяем режим
        if state.get("template_mode") == "select":
            state["step"] = "select_template_type"
            
            # Динамический список шаблонов
            all_accounts = load_user_accounts(user_id)
            selected_phones = state.get("selected_accounts", [])
            selected_accounts = [acc for acc in all_accounts if acc.get("phone") in selected_phones]
            preview_account = selected_accounts[0] if selected_accounts else (all_accounts[0] if all_accounts else {})
            templates = get_templates_from_config(load_config(user_id), preview_account.get('phone')) if preview_account else []
            markup = InlineKeyboardMarkup(inline_keyboard=[])
            if templates:
                for idx, t in enumerate(templates):
                    markup.inline_keyboard.append([
                        InlineKeyboardButton(text=truncate_preview(t), callback_data=f"mailing_template_type_idx_{idx}")
                    ])
            else:
                markup.inline_keyboard.append([InlineKeyboardButton(text="Нет шаблонов", callback_data="mailing_mode_select")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="mailing_mode_select")])
            
            try:
                await delete_and_send_image(
                    call.message,
                    "mailing.png",
                    "Выберите текстовое сообщение:",
                    reply_markup=markup,
                    user_id=user_id
                )
            except TelegramAPIError as e:
                if "message is not modified" not in str(e):
                    raise
            return
        elif state.get("template_mode") == "custom":
            # Для режима custom переходим к выбору шаблонов для каждого аккаунта
            state["step"] = "select_custom_templates"
            state["current_account_index"] = 0
            state["account_templates"] = {}
            state["account_folders"] = {}
            
            # Начинаем с первого аккаунта
            selected_phones = state.get("selected_accounts", [])
            if not selected_phones:
                await call.answer("Ошибка: нет выбранных аккаунтов.", show_alert=True)
                return
            
            # Получаем полные объекты аккаунтов по номерам телефонов
            all_accounts = load_user_accounts(user_id)
            selected_accounts = [acc for acc in all_accounts if acc.get("phone") in selected_phones]
            
            if not selected_accounts:
                await call.answer("Ошибка: не удалось найти выбранные аккаунты.", show_alert=True)
                return
            
            first_account = selected_accounts[0]
            account_nickname = first_account.get("username") or first_account.get("name") or first_account.get("phone")
            
            # Загружаем шаблоны выбранного аккаунта и показываем превью
            template1 = first_account.get("template1", "...")
            template2 = first_account.get("template2", "...")

            markup = InlineKeyboardMarkup(inline_keyboard=[])
            templates = get_templates_from_config(load_config(user_id), first_account.get('phone'))
            if templates:
                for idx, t in enumerate(templates):
                    markup.inline_keyboard.append([
                        InlineKeyboardButton(text=truncate_preview(t), callback_data=f"custom_template_idx_{idx}")
                    ])
            else:
                markup.inline_keyboard.append([InlineKeyboardButton(text="Нет шаблонов", callback_data="mailing_mode_custom")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="mailing_mode_custom")])
            
            try:
                await delete_and_send_image(
                    call.message,
                    "mailing.png",
                    f"Выберите текстовое сообщение для аккаунта {account_nickname}:",
                    reply_markup=markup,
                    user_id=user_id
                )
            except TelegramAPIError as e:
                if "message is not modified" not in str(e):
                    raise
            return
    elif data == "mailing_alternate_templates_no":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        
        # Специальная обработка для восстановленного состояния
        if state.get("original_step") == "select_alternate_templates":
            # Пользователь был на шаге выбора чередования шаблонов
            # Нужно показать правильное меню в зависимости от template_mode
            template_mode = state.get("template_mode")
            if template_mode == "select":
                state["step"] = "select_template_type"
            elif template_mode == "custom":
                state["step"] = "select_logging"
            else:
                state["step"] = "select_logging"
            # Убираем флаг оригинального шага
            state.pop("original_step", None)
        
        # Если template_mode не установлен, но есть selected_accounts,
        # значит пользователь выбрал режим, но не сохранил его
        if state.get("template_mode") is None and state.get("selected_accounts"):
            # Устанавливаем режим по умолчанию
            state["template_mode"] = "select"
        
        state["alternate_templates"] = False
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        
        # Проверяем режим
        if state.get("template_mode") == "select":
            state["step"] = "select_template_type"
            
            # Динамический список шаблонов
            all_accounts = load_user_accounts(user_id)
            selected_phones = state.get("selected_accounts", [])
            selected_accounts = [acc for acc in all_accounts if acc.get("phone") in selected_phones]
            preview_account = selected_accounts[0] if selected_accounts else (all_accounts[0] if all_accounts else {})
            templates = get_templates_from_config(load_config(user_id), preview_account.get('phone')) if preview_account else []
            markup = InlineKeyboardMarkup(inline_keyboard=[])
            if templates:
                for idx, t in enumerate(templates):
                    markup.inline_keyboard.append([
                        InlineKeyboardButton(text=truncate_preview(t), callback_data=f"mailing_template_type_idx_{idx}")
                    ])
            else:
                t1 = preview_account.get("template1", "...")
                t2 = preview_account.get("template2", "...")
                markup.inline_keyboard.append([InlineKeyboardButton(text=truncate_preview(t1), callback_data="mailing_template_type_idx_0")])
                markup.inline_keyboard.append([InlineKeyboardButton(text=truncate_preview(t2), callback_data="mailing_template_type_idx_1")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="mailing_mode_select")])
            
            try:
                await delete_and_send_image(
                    call.message,
                    "mailing.png",
                    "Выберите текстовое сообщение:",
                    reply_markup=markup,
                    user_id=user_id
                )
            except TelegramAPIError as e:
                if "message is not modified" not in str(e):
                    raise
            return
        elif state.get("template_mode") == "custom":
            # Для режима custom переходим к выбору шаблонов для каждого аккаунта
            state["step"] = "select_custom_templates"
            state["current_account_index"] = 0
            state["account_templates"] = {}
            state["account_folders"] = {}
            
            # Начинаем с первого аккаунта
            selected_phones = state.get("selected_accounts", [])
            if not selected_phones:
                await call.answer("Ошибка: нет выбранных аккаунтов.", show_alert=True)
                return
            
            # Получаем полные объекты аккаунтов по номерам телефонов
            all_accounts = load_user_accounts(user_id)
            selected_accounts = [acc for acc in all_accounts if acc.get("phone") in selected_phones]
            
            if not selected_accounts:
                await call.answer("Ошибка: не удалось найти выбранные аккаунты.", show_alert=True)
                return
            
            first_account = selected_accounts[0]
            account_nickname = first_account.get("username") or first_account.get("name") or first_account.get("phone")
            
            markup = InlineKeyboardMarkup(inline_keyboard=[])
            markup.inline_keyboard.append([InlineKeyboardButton(text="T1", callback_data="custom_template_t1")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="T2", callback_data="custom_template_t2")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="mailing_mode_custom")])
            
            try:
                await delete_and_send_image(
                    call.message,
                    "mailing.png",
                    f"Выберите текстовое сообщение для аккаунта {account_nickname}:",
                    reply_markup=markup,
                    user_id=user_id
                )
            except TelegramAPIError as e:
                if "message is not modified" not in str(e):
                    raise
            return

    # --- Обработчики для выбора шаблонов в режиме custom ---
    elif data == "custom_template_t1":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        selected_phones = state.get("selected_accounts", [])
        current_index = state.get("current_account_index", 0)
        
        if current_index >= len(selected_phones):
            await call.answer("Ошибка: неверный индекс аккаунта.", show_alert=True)
            return
        
        # Получаем полные объекты аккаунтов по номерам телефонов
        all_accounts = load_user_accounts(user_id)
        selected_accounts = [acc for acc in all_accounts if acc.get("phone") in selected_phones]
        
        if current_index >= len(selected_accounts):
            await call.answer("Ошибка: неверный индекс аккаунта.", show_alert=True)
            return
        
        # Сохраняем выбор шаблона для текущего аккаунта
        current_account = selected_accounts[current_index]
        account_phone = current_account.get("phone")
        state["account_templates"][account_phone] = "IDX_0"
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        
        # Переходим к выбору папки для этого аккаунта
        state["step"] = "select_custom_folder"
        account_nickname = current_account.get("username") or current_account.get("name") or current_account.get("phone")
        
        # Формируем список реальных папок для текущего аккаунта
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        try:
            license_type = detect_license_type(user_id)
            user_dir = get_user_dir(user_id, license_type)
            config_path = os.path.join(user_dir, "config.json")
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            api_id = config.get("api_id")
            api_hash = config.get("api_hash")
            session_name = current_account.get("name") or current_account.get("phone")
            client = await get_or_create_client(user_id, session_name, api_id, api_hash, license_type)
            folders = await list_folders(client) if client else {}
        except Exception:
            folders = {}

        if folders:
            # Сохраняем список папок для последующего использования при сохранении выбора
            try:
                state["last_folder_list"] = folders
            except Exception:
                pass
            for i, folder in folders.items():
                real_index_zero_based = i - 1
                markup.inline_keyboard.append([
                    InlineKeyboardButton(text=folder.get('title', str(i)), callback_data=f"custom_folder_idx_{real_index_zero_based}")
                ])
        else:
            # Фоллбек на фиксированные значения
            markup.inline_keyboard.append([InlineKeyboardButton(text="F1", callback_data="custom_folder_f1")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="F2", callback_data="custom_folder_f2")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="F3", callback_data="custom_folder_f3")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="F4", callback_data="custom_folder_f4")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="F5", callback_data="custom_folder_f5")])

        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="custom_template_back")])
        
        try:
                await delete_and_send_image(
                    call.message,
                    "mailing.png",
                    f"Выберите папку для аккаунта {account_nickname}:",
                    reply_markup=markup,
                    user_id=user_id
                )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "custom_template_t2":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        selected_phones = state.get("selected_accounts", [])
        current_index = state.get("current_account_index", 0)
        
        if current_index >= len(selected_phones):
            await call.answer("Ошибка: неверный индекс аккаунта.", show_alert=True)
            return
        
        # Получаем полные объекты аккаунтов по номерам телефонов
        all_accounts = load_user_accounts(user_id)
        selected_accounts = [acc for acc in all_accounts if acc.get("phone") in selected_phones]
        
        if current_index >= len(selected_accounts):
            await call.answer("Ошибка: неверный индекс аккаунта.", show_alert=True)
            return
        
        # Сохраняем выбор шаблона для текущего аккаунта
        current_account = selected_accounts[current_index]
        account_phone = current_account.get("phone")
        state["account_templates"][account_phone] = "IDX_1"
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        
        # Переходим к выбору папки для этого аккаунта
        state["step"] = "select_custom_folder"
        account_nickname = current_account.get("username") or current_account.get("name") or current_account.get("phone")
        
        # Формируем список реальных папок для текущего аккаунта
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        try:
            license_type = detect_license_type(user_id)
            user_dir = get_user_dir(user_id, license_type)
            config_path = os.path.join(user_dir, "config.json")
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            api_id = config.get("api_id")
            api_hash = config.get("api_hash")
            session_name = current_account.get("name") or current_account.get("phone")
            client = await get_or_create_client(user_id, session_name, api_id, api_hash, license_type)
            folders = await list_folders(client) if client else {}
        except Exception:
            folders = {}

        if folders:
            # Сохраняем список папок для последующего использования при сохранении выбора
            try:
                state["last_folder_list"] = folders
            except Exception:
                pass
            for i, folder in folders.items():
                real_index_zero_based = i - 1
                markup.inline_keyboard.append([
                    InlineKeyboardButton(text=folder.get('title', str(i)), callback_data=f"custom_folder_idx_{real_index_zero_based}")
                ])
        else:
            # Фоллбек на фиксированные значения
            markup.inline_keyboard.append([InlineKeyboardButton(text="F1", callback_data="custom_folder_f1")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="F2", callback_data="custom_folder_f2")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="F3", callback_data="custom_folder_f3")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="F4", callback_data="custom_folder_f4")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="F5", callback_data="custom_folder_f5")])

        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="custom_template_back")])
        
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                f"Выберите папку для аккаунта {account_nickname}:",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data.startswith("custom_template_idx_"):
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        try:
            idx = int(data.replace("custom_template_idx_", ""))
        except Exception:
            await call.answer("Некорректный индекс шаблона.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        selected_phones = state.get("selected_accounts", [])
        current_index = state.get("current_account_index", 0)
        if current_index >= len(selected_phones):
            await call.answer("Ошибка: неверный индекс аккаунта.", show_alert=True)
            return
        
        all_accounts = load_user_accounts(user_id)
        selected_accounts = [acc for acc in all_accounts if acc.get("phone") in selected_phones]
        if current_index >= len(selected_accounts):
            await call.answer("Ошибка: неверный индекс аккаунта.", show_alert=True)
            return
        current_account = selected_accounts[current_index]
        account_phone = current_account.get("phone")
        state["account_templates"][account_phone] = f"IDX_{idx}"
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        
        # Переходим к выбору папки для этого аккаунта
        state["step"] = "select_custom_folder"
        account_nickname = current_account.get("username") or current_account.get("name") or current_account.get("phone")
        
        # Формируем список реальных папок для текущего аккаунта
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        try:
            license_type = detect_license_type(user_id)
            user_dir = get_user_dir(user_id, license_type)
            config_path = os.path.join(user_dir, "config.json")
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            api_id = config.get("api_id")
            api_hash = config.get("api_hash")
            session_name = current_account.get("name") or current_account.get("phone")
            client = await get_or_create_client(user_id, session_name, api_id, api_hash, license_type)
            folders = await list_folders(client) if client else {}
        except Exception:
            folders = {}

        if folders:
            # Сохраняем список папок для последующего использования при сохранении выбора
            try:
                state["last_folder_list"] = folders
            except Exception:
                pass
            for i, folder in folders.items():
                real_index_zero_based = i - 1
                markup.inline_keyboard.append([
                    InlineKeyboardButton(text=folder.get('title', str(i)), callback_data=f"custom_folder_idx_{real_index_zero_based}")
                ])
        else:
            # Фоллбек на фиксированные значения
            markup.inline_keyboard.append([InlineKeyboardButton(text="F1", callback_data="custom_folder_f1")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="F2", callback_data="custom_folder_f2")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="F3", callback_data="custom_folder_f3")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="F4", callback_data="custom_folder_f4")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="F5", callback_data="custom_folder_f5")])

        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="custom_template_back")])
        
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                f"Выберите папку для аккаунта {account_nickname}:",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        
        # Переходим к выбору папки для этого аккаунта
        state["step"] = "select_custom_folder"
        account_nickname = current_account.get("username") or current_account.get("name") or current_account.get("phone")
        
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="F1", callback_data="custom_folder_f1")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="F2", callback_data="custom_folder_f2")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="F3", callback_data="custom_folder_f3")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="F4", callback_data="custom_folder_f4")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="F5", callback_data="custom_folder_f5")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="custom_template_back")])
        
        try:
                await delete_and_send_image(
                    call.message,
                    "mailing.png",
                    f"Выберите папку для аккаунта {account_nickname}:",
                    reply_markup=markup,
                    user_id=user_id
                )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    # --- Обработчики для выбора папок в режиме custom ---
    elif data.startswith("custom_folder_idx_"):
        try:
            idx = int(data.replace("custom_folder_idx_", ""))
        except Exception:
            await call.answer("Некорректный индекс папки.", show_alert=True)
            return
        # Сохраняем как IDX_n, чтобы далее можно было восстановить индекс
        await handle_custom_folder_selection(call, user_id, f"IDX_{idx}")
        return
    elif data == "custom_folder_f1":
        await handle_custom_folder_selection(call, user_id, "F1")
        return

    elif data == "custom_folder_f2":
        await handle_custom_folder_selection(call, user_id, "F2")
        return

    elif data == "custom_folder_f3":
        await handle_custom_folder_selection(call, user_id, "F3")
        return

    elif data == "custom_folder_f4":
        await handle_custom_folder_selection(call, user_id, "F4")
        return

    elif data == "custom_folder_f5":
        await handle_custom_folder_selection(call, user_id, "F5")
        return
    elif data == "custom_template_back":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        selected_phones = state.get("selected_accounts", [])
        current_index = state.get("current_account_index", 0)
        
        if current_index >= len(selected_phones):
            await call.answer("Ошибка: неверный индекс аккаунта.", show_alert=True)
            return
        
        # Получаем полные объекты аккаунтов по номерам телефонов
        all_accounts = load_user_accounts(user_id)
        selected_accounts = [acc for acc in all_accounts if acc.get("phone") in selected_phones]
        
        if current_index >= len(selected_accounts):
            await call.answer("Ошибка: неверный индекс аккаунта.", show_alert=True)
            return
        
        # Возвращаемся к выбору шаблона для текущего аккаунта
        current_account = selected_accounts[current_index]
        account_nickname = current_account.get("username") or current_account.get("name") or current_account.get("phone")
        
        # Загружаем шаблоны текущего аккаунта и показываем превью
        template1 = current_account.get("template1", "...")
        template2 = current_account.get("template2", "...")

        # Динамический список шаблонов для текущего аккаунта при возврате назад
        templates = get_templates_from_config(load_config(user_id), current_account.get('phone'))

        markup = InlineKeyboardMarkup(inline_keyboard=[])
        if templates:
            for idx, t in enumerate(templates):
                markup.inline_keyboard.append([
                    InlineKeyboardButton(text=truncate_preview(t), callback_data=f"custom_template_idx_{idx}")
                ])
        else:
            markup.inline_keyboard.append([InlineKeyboardButton(text="Нет шаблонов", callback_data="mailing_mode_custom")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="mailing_mode_custom")])
        
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                f"Выберите текстовое сообщение для аккаунта {account_nickname}:",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "mailing_logging_yes":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        state["logging_enabled"] = True
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        state["step"] = "ignore_folders_choice"
        
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Да", callback_data="ignore_folders_yes")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Нет", callback_data="ignore_folders_no")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="mailing_templates_yes")])
        
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Игнорировать рассылку в определенных папках?",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "mailing_logging_no":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        state["logging_enabled"] = False
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        state["step"] = "ignore_folders_choice"
        
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Да", callback_data="ignore_folders_yes")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Нет", callback_data="ignore_folders_no")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="mailing_templates_yes")])
        
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Игнорировать рассылку в определенных папках?",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    # --- Обработчики для выбора типа шаблона (только для режима select configuration) ---
    elif data == "mailing_template_type_t1":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        state["template_type"] = "T1"
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        state["step"] = "select_folder_set"
        
        # Динамически получаем реальные папки для первого выбранного аккаунта
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        try:
            selected_phones = state.get("selected_accounts", [])
            accounts = load_user_accounts(user_id)
            base_account = None
            for acc in accounts:
                if acc.get("phone") in selected_phones:
                    base_account = acc
                    break
            if base_account:
                license_type = detect_license_type(user_id)
                user_dir = get_user_dir(user_id, license_type)
                config_path = os.path.join(user_dir, "config.json")
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                api_id = config.get("api_id")
                api_hash = config.get("api_hash")
                session_name = base_account.get("name") or base_account.get("phone")
                client = await get_or_create_client(user_id, session_name, api_id, api_hash, license_type)
                folders = await list_folders(client) if client else {}
            else:
                folders = {}
        except Exception:
            folders = {}

        if folders:
            for idx, folder in folders.items():
                # idx начинается с 1 в list_folders; приведем к 0-базовому в callback
                real_index_zero_based = idx - 1
                markup.inline_keyboard.append([
                    InlineKeyboardButton(text=folder.get('title', str(idx)), callback_data=f"mailing_folder_set_idx_{real_index_zero_based}")
                ])
        else:
            # Фолбэк на фиксированные F1..F5
            markup.inline_keyboard.append([InlineKeyboardButton(text="F1", callback_data="mailing_folder_set_f1")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="F2", callback_data="mailing_folder_set_f2")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="F3", callback_data="mailing_folder_set_f3")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="F4", callback_data="mailing_folder_set_f4")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="F5", callback_data="mailing_folder_set_f5")])

        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="mailing_templates_yes")])
        
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Выберите папку:",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "mailing_template_type_t2":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        state["template_type"] = "T2"
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        state["step"] = "select_folder_set"
        
        # Динамически получаем реальные папки для первого выбранного аккаунта
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        try:
            selected_phones = state.get("selected_accounts", [])
            accounts = load_user_accounts(user_id)
            base_account = None
            for acc in accounts:
                if acc.get("phone") in selected_phones:
                    base_account = acc
                    break
            if base_account:
                license_type = detect_license_type(user_id)
                user_dir = get_user_dir(user_id, license_type)
                config_path = os.path.join(user_dir, "config.json")
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                api_id = config.get("api_id")
                api_hash = config.get("api_hash")
                session_name = base_account.get("name") or base_account.get("phone")
                client = await get_or_create_client(user_id, session_name, api_id, api_hash, license_type)
                folders = await list_folders(client) if client else {}
            else:
                folders = {}
        except Exception:
            folders = {}

        if folders:
            for idx, folder in folders.items():
                real_index_zero_based = idx - 1
                markup.inline_keyboard.append([
                    InlineKeyboardButton(text=folder.get('title', str(idx)), callback_data=f"mailing_folder_set_idx_{real_index_zero_based}")
                ])
        else:
            # Фолбэк на фиксированные F1..F5
            markup.inline_keyboard.append([InlineKeyboardButton(text="F1", callback_data="mailing_folder_set_f1")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="F2", callback_data="mailing_folder_set_f2")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="F3", callback_data="mailing_folder_set_f3")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="F4", callback_data="mailing_folder_set_f4")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="F5", callback_data="mailing_folder_set_f5")])

        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="mailing_templates_yes")])
        
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Выберите папку:",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    # --- Обработчики для выбора набора папок ---
    elif data == "mailing_folder_set_f1":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        state["folder_set"] = "F1"
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        state["step"] = "select_logging"

        # Если ранее был выбран динамический индекс папки, конвертируем его в F1..F5 для совместимости
        dyn_idx = state.get("folder_set_idx")
        if isinstance(dyn_idx, int):
            # F индекс — это смещение 1..5 от базовой папки dyn_idx
            # Оставляем в state только "folder_set" как F1..F5 (по умолчанию F1)
            state.pop("folder_set_idx", None)
        
        # Определяем правильную кнопку "Вернуться" в зависимости от выбранного типа шаблона
        template_type = state.get("template_type", "T1")
        back_callback = "mailing_template_type_t2" if template_type == "T2" else "mailing_template_type_t1"
        
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Да", callback_data="mailing_logging_yes")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Нет", callback_data="mailing_logging_no")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data=back_callback)])
        
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Добавить логирование статусов отправки сообщений?",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "mailing_folder_set_f2":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        state["folder_set"] = "F2"
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        state["step"] = "select_logging"
        dyn_idx = state.get("folder_set_idx")
        if isinstance(dyn_idx, int):
            state.pop("folder_set_idx", None)
        
        # Определяем правильную кнопку "Вернуться" в зависимости от выбранного типа шаблона
        template_type = state.get("template_type", "T1")
        back_callback = "mailing_template_type_t2" if template_type == "T2" else "mailing_template_type_t1"
        
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Да", callback_data="mailing_logging_yes")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Нет", callback_data="mailing_logging_no")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data=back_callback)])
        
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Добавить логирование статусов отправки сообщений?",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return
    elif data == "mailing_folder_set_f3":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        state["folder_set"] = "F3"
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        state["step"] = "select_logging"
        dyn_idx = state.get("folder_set_idx")
        if isinstance(dyn_idx, int):
            state.pop("folder_set_idx", None)
        
        # Определяем правильную кнопку "Вернуться" в зависимости от выбранного типа шаблона
        template_type = state.get("template_type", "T1")
        back_callback = "mailing_template_type_t2" if template_type == "T2" else "mailing_template_type_t1"
        
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Да", callback_data="mailing_logging_yes")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Нет", callback_data="mailing_logging_no")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data=back_callback)])
        
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Добавить логирование статусов отправки сообщений?",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "mailing_folder_set_f4":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        state["folder_set"] = "F4"
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        state["step"] = "select_logging"
        dyn_idx = state.get("folder_set_idx")
        if isinstance(dyn_idx, int):
            state.pop("folder_set_idx", None)
        
        # Определяем правильную кнопку "Вернуться" в зависимости от выбранного типа шаблона
        template_type = state.get("template_type", "T1")
        back_callback = "mailing_template_type_t2" if template_type == "T2" else "mailing_template_type_t1"
        
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Да", callback_data="mailing_logging_yes")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Нет", callback_data="mailing_logging_no")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data=back_callback)])
        
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Добавить логирование статусов отправки сообщений?",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "mailing_folder_set_f5":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        state["folder_set"] = "F5"
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        state["step"] = "select_logging"
        dyn_idx = state.get("folder_set_idx")
        if isinstance(dyn_idx, int):
            state.pop("folder_set_idx", None)

    # Новый обработчик для динамического выбора базовой папки по реальным названиям
    elif data.startswith("mailing_folder_set_idx_"):
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        try:
            idx_str = data.replace("mailing_folder_set_idx_", "")
            base_index = int(idx_str)  # 0-базовый индекс реальной папки
        except Exception:
            try:
                await call.answer("Некорректный индекс папки.", show_alert=True)
            except Exception:
                pass
            return

        state = mailing_states[user_id]
        # Сохраняем базовый индекс выбранной реальной папки
        state["folder_set_idx"] = base_index
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        state["step"] = "select_logging"

        # Определяем правильную кнопку "Вернуться" в зависимости от выбранного типа шаблона
        template_type = state.get("template_type", "T1")
        back_callback = "mailing_template_type_t2" if template_type == "T2" else "mailing_template_type_t1"

        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Да", callback_data="mailing_logging_yes")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Нет", callback_data="mailing_logging_no")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data=back_callback)])

        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Добавить логирование статусов отправки сообщений?",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return
        
        # Определяем правильную кнопку "Вернуться" в зависимости от выбранного типа шаблона
        template_type = state.get("template_type", "T1")
        back_callback = "mailing_template_type_t2" if template_type == "T2" else "mailing_template_type_t1"
        
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Да", callback_data="mailing_logging_yes")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Нет", callback_data="mailing_logging_no")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data=back_callback)])
        
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Добавить логирование статусов отправки сообщений?",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "mailing_start_command":
        # Гейт по подписке/триалу на финальном шаге запуска рассылки
        if not is_license_valid(user_id):
            try:
                ft = load_freetrial()
            except Exception:
                ft = {}
            if str(user_id) in ft and not is_freetrial_valid(user_id):
                alert_text = "Пробный период закончился. Ваши активные сервисы остановлены."
            else:
                alert_text = "Подписка закончилась. Ваши активные сервисы остановлены."
            try:
                await call.answer(alert_text, show_alert=True)
            except Exception:
                pass
            await handle_access_expired(user_id)
            return
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return

        state = mailing_states[user_id]
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        
        # Создаем состояние для сохранения в resume_process.json
        resume_state = {
            "accounts": [],
            "logging_enabled": state.get("logging_enabled", True),
            "alternate_templates_enabled": state.get("alternate_templates", True),
            "sync_break_finished": False,
            "ignore_folders": state.get("ignore_folders", {}),
            "ignore_chats": state.get("ignore_chats", {})
        }
        
        accounts = load_user_accounts(user_id)
        selected_phones = state.get("selected_accounts", [])
        # --- FIX: Ensure selected_accounts is always defined and valid ---
        selected_accounts = [acc for acc in accounts if acc.get("phone") in selected_phones]
        
        for acc in accounts:
            if acc.get("phone") in selected_phones:
                phone = acc["phone"]
                nickname = acc.get("nickname", acc.get("name", phone))
                
                # Определяем template_index в зависимости от режима
                template_mode = state.get("template_mode")
                if template_mode == "custom":
                    # В режиме custom используем сохраненные шаблоны для каждого аккаунта
                    account_templates = state.get("account_templates", {})
                    template_choice = account_templates.get(phone)
                    if isinstance(template_choice, str) and template_choice.startswith("IDX_"):
                        try:
                            template_index = int(template_choice.replace("IDX_", ""))
                        except Exception:
                            template_index = 0
                    elif template_choice == "T1":
                        template_index = 0
                    elif template_choice == "T2":
                        template_index = 1
                    else:
                        template_index = 0
                elif template_mode == "select":
                    # В авто-режиме стартуем от выбранного template_index и инкрементируем по аккаунтам,
                    # оборачивая по количеству шаблонов конкретного аккаунта
                    try:
                        account_index = selected_accounts.index(acc)
                    except (ValueError, IndexError):
                        account_index = 0
                    try:
                        template_list = get_templates_for_account(acc)
                        count_templates = max(1, len(template_list))
                    except Exception:
                        count_templates = 1
                    base_template_index = state.get("template_index", 0)
                    template_index = (base_template_index + account_index) % count_templates
                elif template_mode == "resume":
                    # В режиме resume используем сохраненный индекс
                    template_index = state.get("template_index", 0)
                else:
                    # По умолчанию используем режим select
                    template_index = 0
                
                # Определяем папку в зависимости от режима
                folder = None
                if template_mode == "custom":
                    account_folders = state.get("account_folders", {})
                    folder_choice = account_folders.get(phone, "F1")
                    # Поддерживаем форматы: F1..F5 и IDX_n (0-базовый индекс реальной папки)
                    folder_index = 0
                    if isinstance(folder_choice, str):
                        if folder_choice.startswith("IDX_"):
                            try:
                                folder_index = int(folder_choice.replace("IDX_", ""))
                            except ValueError:
                                folder_index = 0
                        elif folder_choice.startswith("F") and len(folder_choice) > 1:
                            try:
                                folder_index = int(folder_choice[1]) - 1
                            except ValueError:
                                folder_index = 0
                    folder = {"folder_index": folder_index, "title": folder_choice}
                elif template_mode == "select":
                    # В режиме select используем смещение папок
                    try:
                        account_index = selected_accounts.index(acc)
                        # Поддержка динамически выбранной базовой папки (folder_set_idx) или F1..F5
                        if isinstance(state.get("folder_set_idx"), int):
                            base_index = state.get("folder_set_idx")  # 0-базовый индекс реальной папки
                            folder_index = base_index + account_index
                        else:
                            folder_set = state.get("folder_set", "F1")
                            folder_offset = int(folder_set[1]) - 1  # F1=0, F2=1, F3=2, F4=3, F5=4
                            folder_index = account_index + folder_offset
                        folder = {"folder_index": folder_index, "title": f"Folder_{folder_index + 1}"}
                    except (ValueError, IndexError):
                        folder = {"folder_index": 0, "title": "F1"}
                else:
                    # По умолчанию используем первую папку
                    folder = {"folder_index": 0, "title": "F1"}
                
                resume_state["accounts"].append({
                    "phone": phone,
                    "nickname": nickname,
                    "username": acc.get('username', ''),
                    "template_index": template_index,
                    "folder": folder,
                    "chat_index": 0,
                    "break_seconds_left": 0,
                    "break_until_timestamp": 0,
                    "message_count": 0
                })
        
        # Сохраняем состояние в пользовательскую директорию
        save_resume_state(resume_state, user_id=user_id)
        state["step"] = "running"

        # Запускаем рассылку
        license_type = detect_license_type(user_id)
        await start_task(user_id, "mailing", async_mailing_flow(user_id, license_type))

        # Отправляем сообщение с reply-клавиатурой "Стоп" и "Свернуть"
        await call.message.answer(
            "Запуск процесса. Ожидайте...",
            reply_markup=get_mailing_active_keyboard()
        )

        # (Можно оставить или убрать это сообщение с inline-кнопкой)
        #try:
            #await call.message.edit_text(
                #"Запуск процесса. Ожидайте...",
                #reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                #])
            #)
        #except TelegramAPIError as e:
            #if "message is not modified" not in str(e):
                #raise
        return

    # --- Обработчики для игнорирования папок ---
    elif data == "ignore_folders_yes":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        state["step"] = "ignore_folders_selection"
        state["current_account_index"] = 0
        state["ignore_folders"] = {}
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        
        # Начинаем с первого аккаунта
        selected_accounts = state.get("selected_accounts", [])
        if not selected_accounts:
            await call.answer("Ошибка: нет выбранных аккаунтов.", show_alert=True)
            return
        
        await show_folder_selection_for_account(call, user_id, selected_accounts[0])
        return

    elif data == "ignore_folders_no":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        state["ignore_folders"] = {}
        state["step"] = "ignore_chats_choice"
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Да", callback_data="ignore_chats_yes")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Нет", callback_data="ignore_chats_no")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="ignore_folders_back")])
        
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Игнорировать рассылку в определенных чатах?",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "ignore_folders_back":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        state["step"] = "ignore_folders_choice"
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Да", callback_data="ignore_folders_yes")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Нет", callback_data="ignore_folders_no")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="mailing_templates_yes")])
        
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Игнорировать рассылку в определенных папках?",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "to_ignore_chats_question":
        # Явный переход к вопросу про игнор чатов из выбора папок
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        state = mailing_states[user_id]
        state["step"] = "ignore_chats_choice"
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Да", callback_data="ignore_chats_yes")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Нет", callback_data="ignore_chats_no")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="ignore_folders_back")])
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Игнорировать рассылку в определенных чатах?",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "to_final_settings":
        # Унифицированный переход к Итоговым настройкам с показом лоадера при больших объёмах
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        # Оценка тяжести (сумма папок и чатов)
        try:
            state_snapshot = mailing_states.get(user_id, {})
            ignore_folders_map = state_snapshot.get("ignore_folders", {}) or {}
            total_ignored_folders = sum(len(v or []) for v in ignore_folders_map.values())
            ignore_chats_map = state_snapshot.get("ignore_chats", {}) or {}
            total_ignored_chats = 0
            for _acc, _folders in (ignore_chats_map.items() if isinstance(ignore_chats_map, dict) else []):
                for _fid, _chats in (_folders.items() if isinstance(_folders, dict) else []):
                    total_ignored_chats += len(_chats or [])
            is_heavy = (total_ignored_folders + total_ignored_chats) > 5
        except Exception:
            is_heavy = False

        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="START", callback_data="mailing_start_command")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="ignore_chats_back")])

        if is_heavy:
            try:
                loader_msg = await delete_and_send_image(
                    call.message,
                    "mailing.png",
                    "Загрузка итоговых настроек, ожидайте... 🔄",
                    reply_markup=None,
                    user_id=user_id
                )
            except Exception:
                loader_msg = call.message
            try:
                final_text = await generate_final_settings_text(user_id)
            except Exception:
                final_text = "Ошибка при формировании итоговых настроек."
            try:
                await delete_and_send_image(
                    loader_msg,
                    "mailing.png",
                    final_text,
                    reply_markup=markup,
                    user_id=user_id
                )
            except TelegramAPIError as e:
                if "message is not modified" not in str(e):
                    raise
        else:
            try:
                await delete_and_send_image(
                    call.message,
                    "mailing.png",
                    await generate_final_settings_text(user_id),
                    reply_markup=markup,
                    user_id=user_id
                )
            except TelegramAPIError as e:
                if "message is not modified" not in str(e):
                    raise
        return

    # --- Обработчики для игнорирования чатов ---
    elif data == "ignore_chats_yes":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        state["step"] = "ignore_chats_folder_selection"
        state["current_account_index"] = 0
        state["ignore_chats"] = {}
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        
        # Начинаем с первого аккаунта
        selected_accounts = state.get("selected_accounts", [])
        if not selected_accounts:
            await call.answer("Ошибка: нет выбранных аккаунтов.", show_alert=True)
            return
        
        await show_folder_selection_for_chats(call, user_id, selected_accounts[0])
        return

    elif data == "ignore_chats_no":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        state["ignore_chats"] = {}
        state["step"] = "start_mailing"
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        
        # Сохраняем настройки игнорирования
        save_ignore_settings(user_id, state.get("ignore_folders", {}), state.get("ignore_chats", {}))
        
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="START", callback_data="mailing_start_command")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="ignore_chats_back")])
        
        # Если игнора много (более 5 элементов суммарно: папки+чаты) — показываем лоадер
        try:
            state_snapshot = mailing_states.get(user_id, {})
            ignore_folders_map = state_snapshot.get("ignore_folders", {}) or {}
            total_ignored_folders = sum(len(v or []) for v in ignore_folders_map.values())
            ignore_chats_map = state_snapshot.get("ignore_chats", {}) or {}
            total_ignored_chats = 0
            for _acc, _folders in (ignore_chats_map.items() if isinstance(ignore_chats_map, dict) else []):
                for _fid, _chats in (_folders.items() if isinstance(_folders, dict) else []):
                    total_ignored_chats += len(_chats or [])
            is_heavy = (total_ignored_folders + total_ignored_chats) > 5
        except Exception:
            is_heavy = False

        if is_heavy:
            try:
                loader_msg = await delete_and_send_image(
                    call.message,
                    "mailing.png",
                    "Загрузка итоговых настроек, ожидайте... 🔄",
                    reply_markup=None,
                    user_id=user_id
                )
            except Exception:
                loader_msg = call.message
            # Генерируем и показываем финальные настройки, заменив лоадер
            try:
                final_text = await generate_final_settings_text(user_id)
            except Exception:
                final_text = "Ошибка при формировании итоговых настроек."
            try:
                await delete_and_send_image(
                    loader_msg,
                    "mailing.png",
                    final_text,
                    reply_markup=markup,
                    user_id=user_id
                )
            except TelegramAPIError as e:
                if "message is not modified" not in str(e):
                    raise
        else:
            try:
                await delete_and_send_image(
                    call.message,
                    "mailing.png",
                    await generate_final_settings_text(user_id),
                    reply_markup=markup,
                    user_id=user_id
                )
            except TelegramAPIError as e:
                if "message is not modified" not in str(e):
                    raise
        return

    elif data == "ignore_chats_back":
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        state["step"] = "ignore_chats_choice"
        
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Да", callback_data="ignore_chats_yes")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Нет", callback_data="ignore_chats_no")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="ignore_folders_back")])
        
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Игнорировать рассылку в определенных чатах?",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    # --- Обработчики для выбора папок для игнорирования ---
    elif data.startswith("ignore_folder_"):
        # Формат: ignore_folder_{account_phone}_{folder_id}
        parts = data.split("_")
        if len(parts) >= 4:
            account_phone = parts[2]
            folder_id = int(parts[3])
            
            if user_id not in mailing_states:
                await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
                return
            
            state = mailing_states[user_id]
            if "ignore_folders" not in state:
                state["ignore_folders"] = {}
            if account_phone not in state["ignore_folders"]:
                state["ignore_folders"][account_phone] = []
            
            if folder_id not in state["ignore_folders"][account_phone]:
                state["ignore_folders"][account_phone].append(folder_id)
                try:
                    await call.answer(f"Папка добавлена в игнорируемые", show_alert=False)
                except Exception:
                    pass
            else:
                state["ignore_folders"][account_phone].remove(folder_id)
                try:
                    await call.answer(f"Папка убрана из игнорируемых", show_alert=False)
                except Exception:
                    pass
            
            try:
                save_mailing_parameters(user_id)
            except Exception:
                pass
            
            # Обновляем только клавиатуру с новым состоянием галочек (без resolver)
            await update_folder_selection_keyboard(call, user_id, account_phone)
        
        return

    elif data.startswith("next_folder_account_"):
        # Переходим к следующему аккаунту
        account_phone = data.replace("next_folder_account_", "")
        
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        selected_accounts = state.get("selected_accounts", [])
        current_index = state.get("current_account_index", 0)
        
        # Переходим к следующему аккаунту
        current_index += 1
        
        if current_index >= len(selected_accounts):
            # Все аккаунты обработаны, переходим к выбору чатов
            state["step"] = "ignore_chats_choice"
            markup = InlineKeyboardMarkup(inline_keyboard=[])
            markup.inline_keyboard.append([InlineKeyboardButton(text="Да", callback_data="ignore_chats_yes")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="Нет", callback_data="ignore_chats_no")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="ignore_folders_back")])
            
            try:
                await delete_and_send_image(
                    call.message,
                    "mailing.png",
                    "Игнорировать рассылку в определенных чатах?",
                    reply_markup=markup,
                    user_id=user_id
                )
            except TelegramAPIError as e:
                if "message is not modified" not in str(e):
                    raise
        else:
            # Показываем выбор папок для следующего аккаунта
            state["current_account_index"] = current_index
            try:
                save_mailing_parameters(user_id)
            except Exception:
                pass
            await show_folder_selection_for_account(call, user_id, selected_accounts[current_index])
        
        return

    elif data.startswith("back_to_prev_folder_account_"):
        # Возвращаемся к предыдущему аккаунту в выборе папок
        account_phone = data.replace("back_to_prev_folder_account_", "")
        
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        selected_accounts = state.get("selected_accounts", [])
        current_index = state.get("current_account_index", 0)
        
        # Переходим к предыдущему аккаунту
        current_index -= 1
        
        if current_index < 0:
            # Если мы на первом аккаунте, возвращаемся к выбору: Игнорировать в папках? (Да/Нет)
            state["step"] = "ignore_folders_choice"
            markup = InlineKeyboardMarkup(inline_keyboard=[])
            markup.inline_keyboard.append([InlineKeyboardButton(text="Да", callback_data="ignore_folders_yes")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="Нет", callback_data="ignore_folders_no")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="mailing_templates_yes")])
            
            try:
                await delete_and_send_image(
                    call.message,
                    "mailing.png",
                    "Игнорировать рассылку в определенных папках?",
                    reply_markup=markup,
                    user_id=user_id
                )
            except TelegramAPIError as e:
                if "message is not modified" not in str(e):
                    raise
        else:
            # Показываем выбор папок для предыдущего аккаунта
            state["current_account_index"] = current_index
            try:
                save_mailing_parameters(user_id)
            except Exception:
                pass
            await show_folder_selection_for_account(call, user_id, selected_accounts[current_index])
        
        return

    # --- Обработчики для выбора чатов для игнорирования ---
    elif data.startswith("select_chat_folder_"):
        if data == "dummy":
            try:
                await call.answer()
            except Exception:
                pass
            return
        # Формат: select_chat_folder_{account_phone}_{folder_id}
        parts = data.split("_")
        if len(parts) >= 5:
            account_phone = parts[3]
            folder_id = int(parts[4])
            
            # Показать лоадер: удаляем текущий экран и отправляем «Загрузка чатов 🔄» с кнопками Далее/Вернуться
            try:
                loading_markup = InlineKeyboardMarkup(inline_keyboard=[])
                loading_markup.inline_keyboard.append([InlineKeyboardButton(text="Далее", callback_data=f"next_chat_folder_{account_phone}_{folder_id}")])
                loading_markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data=f"back_to_chat_folders_{account_phone}")])
                # Определяем текущую страницу (по сохранённому состоянию), по умолчанию 0
                try:
                    _state = mailing_states.get(user_id, {})
                    _page = int((_state.get("chat_pages", {}) or {}).get(account_phone, {}).get(str(int(folder_id)), 0))
                except Exception:
                    _page = 0
                _title_text = f"Страница {_page + 1}\n\n\nЗагрузка чатов, ожидайте... 🔄"
                loading_message = await delete_and_send_image(
                    call.message,
                    "mailing.png",
                    _title_text,
                    reply_markup=loading_markup,
                    user_id=user_id
                )
            except Exception:
                loading_message = None

            # После загрузки — показать список чатов, заменив лоадер, если он есть
            # Инкрементируем токен загрузки, чтобы можно было отменить устаревшую выдачу при навигации
            try:
                state = mailing_states.get(user_id, {})
                state["chat_load_token"] = int(state.get("chat_load_token", 0)) + 1
                mailing_states[user_id] = state
            except Exception:
                pass
            await show_chat_selection_for_folder(call, user_id, account_phone, folder_id, existing_message=loading_message)
        
        return

    elif data.startswith("back_to_prev_account_chats_"):
        # Возврат к выбору чатов предыдущего аккаунта
        prev_account_phone = data.replace("back_to_prev_account_chats_", "")
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        state = mailing_states[user_id]
        selected_accounts = state.get("selected_accounts", [])
        if prev_account_phone not in selected_accounts:
            # Если что-то пошло не так — вернёмся к выбору игнорирования чатов
            return await delete_and_send_image(
                call.message,
                "mailing.png",
                "Игнорировать рассылку в определенных чатах?",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Да", callback_data="ignore_chats_yes")],
                    [InlineKeyboardButton(text="Нет", callback_data="ignore_chats_no")],
                    [InlineKeyboardButton(text="Вернуться 🔙", callback_data="ignore_folders_back")],
                ]),
                user_id=user_id
            )
        current_index = state.get("current_account_index", 0)
        try:
            idx = selected_accounts.index(prev_account_phone)
        except ValueError:
            idx = current_index
        # Целимся в предыдущий аккаунт относительно текущего (если возможно)
        target_index = max(0, idx - 1)
        # ВАЖНО: синхронизируем индекс текущего аккаунта при возврате,
        # чтобы последующий "Далее" вел на верный следующий аккаунт
        state["current_account_index"] = target_index
        try:
            save_mailing_parameters(user_id)
        except Exception:
            pass
        # Если уже на первом аккаунте — вернёмся к экрану выбора: Игнорировать в чатах? (Да/Нет)
        if idx == 0 and target_index == 0:
            return await delete_and_send_image(
                call.message,
                "mailing.png",
                "Игнорировать рассылку в определенных чатах?",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Да", callback_data="ignore_chats_yes")],
                    [InlineKeyboardButton(text="Нет", callback_data="ignore_chats_no")],
                    [InlineKeyboardButton(text="Вернуться 🔙", callback_data="ignore_folders_back")],
                ]),
                user_id=user_id
            )
        target_phone = selected_accounts[target_index]
        # Пытаемся открыть последнюю выбранную папку, если она известна, иначе возвращаемся к выбору папок
        last_map = state.get("last_folder_for_account", {}) or {}
        last_folder = last_map.get(target_phone)
        if last_folder is not None:
            # Покажем лоадер, как при "Далее/Вернуться" раньше
            try:
                loading_markup = InlineKeyboardMarkup(inline_keyboard=[])
                loading_markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data=f"back_to_chat_folders_{target_phone}")])
                _title_text = f"Загрузка чатов, ожидайте... 🔄"
                loading_message = await delete_and_send_image(
                    call.message,
                    "mailing.png",
                    _title_text,
                    reply_markup=loading_markup,
                    user_id=user_id
                )
            except Exception:
                loading_message = None
            # Инкремент токена загрузки, чтобы отменить устаревшие экраны
            try:
                state = mailing_states.get(user_id, {})
                state["chat_load_token"] = int(state.get("chat_load_token", 0)) + 1
                mailing_states[user_id] = state
            except Exception:
                pass
            try:
                await show_chat_selection_for_folder(call, user_id, target_phone, int(last_folder), existing_message=loading_message)
                return
            except Exception:
                pass
        await show_folder_selection_for_chats(call, user_id, target_phone)
        return

    elif data.startswith("ignore_chat_"):
        # Формат: ignore_chat_{account_phone}_{folder_id}_{chat_id}
        parts = data.split("_")
        if len(parts) >= 5:
            account_phone = parts[2]
            folder_id = parts[3]
            chat_id = int(parts[4])
            
            if user_id not in mailing_states:
                await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
                return
            
            state = mailing_states[user_id]
            if "ignore_chats" not in state:
                state["ignore_chats"] = {}
            if account_phone not in state["ignore_chats"]:
                state["ignore_chats"][account_phone] = {}
            if folder_id not in state["ignore_chats"][account_phone]:
                state["ignore_chats"][account_phone][folder_id] = []
            
            if chat_id not in state["ignore_chats"][account_phone][folder_id]:
                state["ignore_chats"][account_phone][folder_id].append(chat_id)
                try:
                    await call.answer(f"Чат добавлен в игнорируемые", show_alert=False)
                except Exception:
                    pass
            else:
                state["ignore_chats"][account_phone][folder_id].remove(chat_id)
                try:
                    await call.answer(f"Чат убран из игнорируемые", show_alert=False)
                except Exception:
                    pass
            
            try:
                save_mailing_parameters(user_id)
            except Exception:
                pass
            
            # Быстрое локальное обновление клавиатуры без повторной загрузки чатов
            try:
                existing_markup = call.message.reply_markup
                if existing_markup and getattr(existing_markup, 'inline_keyboard', None):
                    updated_keyboard = []
                    current_selected = set(state["ignore_chats"][account_phone][folder_id])
                    for row in existing_markup.inline_keyboard:
                        new_row = []
                        for btn in row:
                            try:
                                cb = getattr(btn, 'callback_data', None)
                                text = getattr(btn, 'text', '')
                                if cb and cb.startswith(f"ignore_chat_{account_phone}_{folder_id}_"):
                                    # Извлекаем chat_id из callback_data
                                    chat_id_str = cb.split("_")[-1]
                                    chat_id_val = int(chat_id_str)
                                    base_text = text.replace(" ✅", "").rstrip()
                                    mark = " ✅" if chat_id_val in current_selected else ""
                                    new_btn = InlineKeyboardButton(text=f"{base_text}{mark}", callback_data=cb)
                                    new_row.append(new_btn)
                                else:
                                    new_row.append(btn)
                            except Exception:
                                new_row.append(btn)
                        updated_keyboard.append(new_row)
                    new_markup = InlineKeyboardMarkup(inline_keyboard=updated_keyboard)
                    try:
                        await call.message.edit_reply_markup(reply_markup=new_markup)
                    except Exception as e:
                        if "message is not modified" in str(e):
                            pass
                        else:
                            print(f"Ошибка обновления клавиатуры чатов: {e}")
                else:
                    # Фоллбек к прежней логике при отсутствии текущей клавиатуры
                    await update_chat_selection_keyboard(call, user_id, account_phone, int(folder_id))
            except Exception as e:
                print(f"Ошибка локального обновления клавиатуры чатов: {e}")
                await update_chat_selection_keyboard(call, user_id, account_phone, int(folder_id))
        
        return

    elif data.startswith("more_chats_"):
        # Пагинация по чатам: more_chats_{account_phone}_{folder_id}_{page}
        parts = data.split("_")
        if len(parts) >= 5:
            account_phone = parts[2]
            folder_id = int(parts[3])
            page = int(parts[4])
            if user_id not in mailing_states:
                await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
                return
            state = mailing_states[user_id]
            # Удаляем предыдущее сообщение и отправляем «Загрузка чатов 🔄» с нужными кнопками
            try:
                loading_markup = InlineKeyboardMarkup(inline_keyboard=[])
                # На экране загрузки НЕ показываем пагинацию
                loading_markup.inline_keyboard.append([InlineKeyboardButton(text="Далее", callback_data=f"next_chat_folder_{account_phone}_{folder_id}")])
                loading_markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data=f"back_to_chat_folders_{account_phone}")])
                _title_text = f"Страница {page + 1}\n\n\nЗагрузка чатов, ожидайте... 🔄"
                loading_message = await delete_and_send_image(
                    call.message,
                    "mailing.png",
                    _title_text,
                    reply_markup=loading_markup,
                    user_id=user_id
                )
            except Exception:
                pass
            if "chat_pages" not in state:
                state["chat_pages"] = {}
            if account_phone not in state["chat_pages"]:
                state["chat_pages"][account_phone] = {}
            state["chat_pages"][account_phone][str(folder_id)] = page
            try:
                save_mailing_parameters(user_id)
            except Exception:
                pass
            # Инкрементируем токен загрузки, чтобы отменить возможные конкурирующие загрузки
            try:
                state = mailing_states.get(user_id, {})
                state["chat_load_token"] = int(state.get("chat_load_token", 0)) + 1
                mailing_states[user_id] = state
            except Exception:
                pass
            await show_chat_selection_for_folder(call, user_id, account_phone, folder_id, existing_message=loading_message if 'loading_message' in locals() else None)
        return

    elif data.startswith("next_chat_account_"):
        # Переходим к следующему аккаунту для выбора чатов
        account_phone = data.replace("next_chat_account_", "")
        
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        selected_accounts = state.get("selected_accounts", [])
        current_index = state.get("current_account_index", 0)
        
        # Переходим к следующему аккаунту
        current_index += 1
        
        if current_index >= len(selected_accounts):
            # Все аккаунты обработаны, завершаем настройку
            state["step"] = "start_mailing"
            save_ignore_settings(user_id, state.get("ignore_folders", {}), state.get("ignore_chats", {}))
            
            markup = InlineKeyboardMarkup(inline_keyboard=[])
            markup.inline_keyboard.append([InlineKeyboardButton(text="START", callback_data="mailing_start_command")])
            markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="ignore_chats_back")])
            
            # Оценка «тяжести» итогов (суммарно: папки+чаты)
            try:
                state_snapshot = mailing_states.get(user_id, {})
                ignore_folders_map = state_snapshot.get("ignore_folders", {}) or {}
                total_ignored_folders = sum(len(v or []) for v in ignore_folders_map.values())
                ignore_chats_map = state_snapshot.get("ignore_chats", {}) or {}
                total_ignored_chats = 0
                for _acc, _folders in (ignore_chats_map.items() if isinstance(ignore_chats_map, dict) else []):
                    for _fid, _chats in (_folders.items() if isinstance(_folders, dict) else []):
                        total_ignored_chats += len(_chats or [])
                is_heavy = (total_ignored_folders + total_ignored_chats) > 5
            except Exception:
                is_heavy = False

            if is_heavy:
                try:
                    loader_msg = await delete_and_send_image(
                        call.message,
                        "mailing.png",
                        "Загрузка итоговых настроек, ожидайте... 🔄",
                        reply_markup=None,
                        user_id=user_id
                    )
                except Exception:
                    loader_msg = call.message
                try:
                    final_text = await generate_final_settings_text(user_id)
                except Exception:
                    final_text = "Ошибка при формировании итоговых настроек."
                try:
                    await delete_and_send_image(
                        loader_msg,
                        "mailing.png",
                        final_text,
                        reply_markup=markup,
                        user_id=user_id
                    )
                except TelegramAPIError as e:
                    if "message is not modified" not in str(e):
                        raise
            else:
                try:
                    await delete_and_send_image(
                        call.message,
                        "mailing.png",
                        await generate_final_settings_text(user_id),
                        reply_markup=markup,
                        user_id=user_id
                    )
                except TelegramAPIError as e:
                    if "message is not modified" not in str(e):
                        raise
        else:
            # Переходим к следующему аккаунту
            state["current_account_index"] = current_index
            try:
                save_mailing_parameters(user_id)
            except Exception:
                pass
            target_phone = selected_accounts[current_index]
            # Всегда начинаем со выбора папки на новом аккаунте
            try:
                save_mailing_parameters(user_id)
            except Exception:
                pass
            await show_folder_selection_for_chats(call, user_id, target_phone)
        
        return
    elif data.startswith("next_chat_folder_"):
        # Переходим к следующей папке или аккаунту
        parts = data.split("_")
        if len(parts) >= 5:
            account_phone = parts[3]
            folder_id = parts[4]
            
            # Любая навигация дальше должна отменять текущую загрузку чатов
            try:
                state = mailing_states.get(user_id, {})
                state["chat_load_token"] = int(state.get("chat_load_token", 0)) + 1
                mailing_states[user_id] = state
            except Exception:
                pass

            # Проверяем, есть ли еще папки в текущем аккаунте
            state = mailing_states.get(user_id, {})
            selected_accounts = state.get("selected_accounts", [])
            current_index = state.get("current_account_index", 0)
            
            # Получаем аккаунт для проверки папок
            accounts = load_user_accounts(user_id)
            account = None
            for acc in accounts:
                if acc.get('phone') == account_phone:
                    account = acc
                    break
            
            if account:
                # Подключаемся к аккаунту для получения папок
                license_type = detect_license_type(user_id)
                user_dir = get_user_dir(user_id, license_type)
                config_path = os.path.join(user_dir, "config.json")
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                
                api_id = config.get("api_id")
                api_hash = config.get("api_hash")
                
                session_name = account.get('name') or account.get('phone')
                client = await get_or_create_client(user_id, session_name, api_id, api_hash, license_type)
                
                if client:
                    folders = await list_folders(client)
                    if folders:
                        # Ищем следующую папку после текущей
                        folder_ids = list(folders.keys())
                        try:
                            current_folder_index = folder_ids.index(int(folder_id))
                            if current_folder_index + 1 < len(folder_ids):
                                # Есть следующая папка в этом аккаунте
                                next_folder_id = folder_ids[current_folder_index + 1]
                                await show_chat_selection_for_folder(call, user_id, account_phone, next_folder_id)
                                return
                        except ValueError:
                            pass
            
            # Если нет больше папок в этом аккаунте, переходим к следующему аккаунту
            current_index += 1
            state["current_account_index"] = current_index
            
            if current_index >= len(selected_accounts):
                # Все аккаунты обработаны, завершаем настройку
                state["step"] = "start_mailing"
                save_ignore_settings(user_id, state.get("ignore_folders", {}), state.get("ignore_chats", {}))
                
                markup = InlineKeyboardMarkup(inline_keyboard=[])
                markup.inline_keyboard.append([InlineKeyboardButton(text="START", callback_data="mailing_start_command")])
                markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="ignore_chats_back")])
                
                try:
                    await delete_and_send_image(
                        call.message,
                        "mailing.png",
                        await generate_final_settings_text(user_id),
                        reply_markup=markup,
                        user_id=user_id
                    )
                except TelegramAPIError as e:
                    if "message is not modified" not in str(e):
                        raise
            else:
                # Переходим к выбору папки для следующего аккаунта
                try:
                    save_mailing_parameters(user_id)
                except Exception:
                    pass
                await show_folder_selection_for_chats(call, user_id, selected_accounts[current_index])
        
        return

    elif data.startswith("proceed_chats_"):
        # Переход к выбору чатов по текущей (последней выбранной) папке
        account_phone = data.replace("proceed_chats_", "")
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        state = mailing_states[user_id]
        # Попытка использовать последнюю папку; если нет — открыть выбор папок
        last_map = state.get("last_folder_for_account", {}) or {}
        last_folder = last_map.get(account_phone)
        if last_folder is None:
            return await show_folder_selection_for_chats(call, user_id, account_phone)
        try:
            folder_id = int(last_folder)
        except Exception:
            return await show_folder_selection_for_chats(call, user_id, account_phone)
        # Показать экраны чатов (с поддержкой лоадера, если он нужен в этой ветке — не используем)
        await show_chat_selection_for_folder(call, user_id, account_phone, folder_id)
        return

    elif data.startswith("select_chat_folder_"):
        # Обработчик для кнопки "Вернуться" в разделе выбора чатов
        # Формат: select_chat_folder_{account_phone}_{folder_id}
        parts = data.split("_")
        if len(parts) >= 5:
            account_phone = parts[3]
            folder_id = int(parts[4])
            
            await show_chat_selection_for_folder(call, user_id, account_phone, folder_id)
        
        return

    elif data.startswith("back_to_chat_folders_"):
        # Обработчик для кнопки "Вернуться" в разделе выбора чатов
        account_phone = data.replace("back_to_chat_folders_", "")
        # Возврат должен отменить текущую загрузку чатов (если она идёт)
        try:
            state = mailing_states.get(user_id, {})
            state["chat_load_token"] = int(state.get("chat_load_token", 0)) + 1
            mailing_states[user_id] = state
        except Exception:
            pass
        await show_folder_selection_for_chats(call, user_id, account_phone)
        return

    elif data == "mailing_stop":
        # Останавливаем рассылку
        if user_id in active_tasks:
            for task_name in list(active_tasks[user_id].keys()):
                if task_name.startswith("mailing") or "timer" in task_name.lower() or "countdown" in task_name.lower():
                    await stop_task(user_id, task_name)
        
        # Очищаем состояние рассылки
        if user_id in mailing_states:
            del mailing_states[user_id]
            # Безопасно обновляем состояние в файле
            update_service_state("mailing_states", user_id, None)
        
        # Показываем меню управления аккаунтами с актуальной статистикой
        try:
            await delete_and_send_image(
                call.message,
                "manage.png",
                get_user_stats_display(user_id),
                reply_markup=get_accounts_manage_menu()
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    # --- Конец обработчиков для рассылки ---

    # --- Обработчики кнопок "Вернуться" для рассылки ---
    elif data == "mailing_next":
        # Возврат к выбору аккаунтов
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        state["step"] = "select_accounts"
        
        # Обновляем клавиатуру для выбора аккаунтов
        accounts = load_user_accounts(user_id)
        selected = state.get("selected_accounts", [])
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        
        for acc in accounts:
            nickname = acc.get('username') or acc.get('name') or acc.get('phone')
            mark = " ✅" if acc.get('phone') in selected else ""
            markup.inline_keyboard.append([InlineKeyboardButton(
                text=f"{nickname}{mark}", 
                callback_data=f"mailing_acc_{acc.get('phone')}"
            )])
        
        # Кнопка "Далее" активна только если выбран хотя бы 1 аккаунт
        if selected:
            markup.inline_keyboard.append([InlineKeyboardButton(text="Далее ➡️", callback_data="mailing_next")])
        else:
            markup.inline_keyboard.append([InlineKeyboardButton(text="Далее ➡️", callback_data="mailing_next", disabled=True)])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="message_mailing")])
        
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Выберите аккаунты для рассылки:",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "mailing_back_to_mode":
        # Возврат к запросу "Последняя сводка"
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        state["step"] = "select_summary"
        
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Да", callback_data="mailing_summary_yes")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Нет", callback_data="mailing_summary_no")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="mailing_start")])
        
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Последняя сводка:",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "mailing_templates_yes":
        # Возврат к выбору шаблонов
        if user_id not in mailing_states:
            await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
            return
        
        state = mailing_states[user_id]
        state["step"] = "select_templates"
        
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Да", callback_data="mailing_templates_yes")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Нет", callback_data="mailing_templates_no")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="mailing_back_to_mode")])
        
        try:
            await edit_text_or_safe_send(
                call.message,
                "Включить чередование шаблонов?",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    if data == "postman":
        # При входе в раздел — быстрый гейт доступа
        if not is_license_valid(user_id):
            try:
                ft = load_freetrial()
            except Exception:
                ft = {}
            if str(user_id) in ft and not is_freetrial_valid(user_id):
                alert_text = "Пробный период закончился. Ваши активные сервисы остановлены."
            else:
                alert_text = "Подписка закончилась. Ваши активные сервисы остановлены."
            try:
                await call.answer(alert_text, show_alert=True)
            except Exception:
                pass
            await handle_access_expired(user_id)
            return
        try:
            await delete_and_send_image(
                call.message,
                "mailbox.png",
                "Почтовый ящик." if user_languages.get(user_id, "ru") == "ru" else "Mailbox.",
                reply_markup=get_postman_menu(user_id),
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        user_states[user_id] = "postman_menu"
        return

    elif data == "autoresponder":
        # При входе в раздел — быстрый гейт доступа
        if not is_license_valid(user_id):
            try:
                ft = load_freetrial()   
            except Exception:
                ft = {}
            if str(user_id) in ft and not is_freetrial_valid(user_id):
                alert_text = "Пробный период закончился. Ваши активные сервисы остановлены."
            else:
                alert_text = "Подписка закончилась. Ваши активные сервисы остановлены."
        
            try:
                await call.answer(alert_text, show_alert=True)
            except Exception:
                pass
            await handle_access_expired(user_id)
            return
        # НЕ очищаем выбранные аккаунты при входе в раздел, если автоответчик активен
        # Это позволяет сохранить состояние при переходах между разделами
        if user_id in autoresponder_states and autoresponder_states[user_id].get("active"):
            # Если автоответчик активен, проверяем и восстанавливаем selected_accounts если нужно
            if not autoresponder_states[user_id].get("selected_accounts"):
                print(f"⚠️ Восстановление selected_accounts при входе в автоответчик для пользователя {user_id}")
                # Пытаемся восстановить из postman_states
                if user_id in postman_states and postman_states[user_id].get("selected_accounts"):
                    autoresponder_states[user_id]["selected_accounts"] = postman_states[user_id]["selected_accounts"]
                    print(f"✅ Восстановлены selected_accounts из postman_states: {autoresponder_states[user_id]['selected_accounts']}")
                    # Сохраняем обновленное состояние
                    update_service_state("autoresponder_states", user_id, autoresponder_states[user_id])
        elif user_id in autoresponder_states:
            # Если автоответчик не активен, очищаем selected_accounts
            autoresponder_states[user_id]["selected_accounts"] = []
        
        try:
            await delete_and_send_image(
                call.message,
                "autoresponder.png",
                "Автоответчик." if user_languages.get(user_id, "ru") == "ru" else "Autoresponder.",
                reply_markup=get_autoresponder_menu(user_id),
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "autoresponder_no_templates":
        message = "Сначала создайте шаблоны в разделе 'Шаблоны'" if user_languages.get(user_id, "ru") == "ru" else "First create templates in the 'Templates' section"
        await call.answer(message, show_alert=True)
        return
    elif data == "autoresponder_activate":
        # Проверка доступа перед запуском мастера выбора аккаунтов автоответчика
        if not is_license_valid(user_id):
            try:
                ft = load_freetrial()
            except Exception:
                ft = {}
            if str(user_id) in ft and not is_freetrial_valid(user_id):
                alert_text = "Пробный период закончился. Ваши активные сервисы остановлены."
            else:
                alert_text = "Подписка закончилась. Ваши активные сервисы остановлены."
            try:
                await call.answer(alert_text, show_alert=True)
            except Exception:
                pass
            await handle_access_expired(user_id)
            return
        # Инициализируем состояние автоответчика
        if user_id not in autoresponder_states:
            autoresponder_states[user_id] = {"selected_accounts": []}
        
        try:
            await delete_and_send_image(
                call.message,
                "autoresponder.png",
                "Выберите аккаунты для автоответчика:" if user_languages.get(user_id, "ru") == "ru" else "Select accounts for autoresponder:",
                reply_markup=get_autoresponder_accounts_menu(user_id, "activate"),
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data.startswith("autoresponder_toggle_account|"):
        phone = data.split("|")[1]
        
        # Инициализируем состояние если нужно
        if user_id not in autoresponder_states:
            autoresponder_states[user_id] = {"selected_accounts": []}
        
        selected = autoresponder_states[user_id].get("selected_accounts", [])
        
        # Переключаем выбор
        if phone in selected:
            selected.remove(phone)
        else:
            selected.append(phone)
        
        autoresponder_states[user_id]["selected_accounts"] = selected
        
        # Обновляем только клавиатуру с новыми галочками, не пересоздавая сообщение
        await update_autoresponder_accounts_keyboard(call, user_id, selected)
        return

    elif data == "autoresponder_select_all":
        accounts = get_active_accounts_by_sessions(user_id)
        all_phones = [acc.get("phone") for acc in accounts]
        
        if user_id not in autoresponder_states:
            autoresponder_states[user_id] = {}
        
        current_selected = autoresponder_states[user_id].get("selected_accounts", [])
        
        # Если все выбраны - снимаем выбор, иначе выбираем все
        if len(current_selected) == len(all_phones):
            autoresponder_states[user_id]["selected_accounts"] = []
        else:
            autoresponder_states[user_id]["selected_accounts"] = all_phones
        
        # Обновляем только клавиатуру с новыми галочками, не пересоздавая сообщение
        await update_autoresponder_accounts_keyboard(call, user_id, autoresponder_states[user_id]["selected_accounts"])
        return

    elif data == "autoresponder_confirm":
        if not is_license_valid(user_id):
            try:
                ft = load_freetrial()
            except Exception:
                ft = {}
            if str(user_id) in ft and not is_freetrial_valid(user_id):
                alert_text = "Пробный период закончился. Ваши активные сервисы остановлены."
            else:
                alert_text = "Подписка закончилась. Ваши активные сервисы остановлены."
            try:
                await call.answer(alert_text, show_alert=True)
            except Exception:
                pass
            await handle_access_expired(user_id)
            return
        selected_accounts = autoresponder_states.get(user_id, {}).get("selected_accounts", [])
        
        
        
        if not selected_accounts:
            message = "Выберите хотя бы один аккаунт" if user_languages.get(user_id, "ru") == "ru" else "Select at least one account"
            await call.answer(message, show_alert=True)
            return
        
        # Проверяем, есть ли шаблоны для выбранных аккаунтов
        missing_templates = []
        for phone in selected_accounts:
            template = get_autoresponder_template(user_id, phone)
            if not template:
                # Получаем имя аккаунта для отображения
                accounts = get_active_accounts_by_sessions(user_id)
                account = None
                for acc in accounts:
                    if isinstance(acc, dict) and acc.get("phone") == phone:
                        account = acc
                        break
                if account:
                    name = account.get("username") or account.get("name") or phone
                    missing_templates.append(name)
                else:
                    missing_templates.append(phone)
        
        if missing_templates:
            if user_languages.get(user_id, "ru") == "ru":
                message = f"Отсутствуют шаблоны для аккаунтов: {', '.join(missing_templates)}"
            else:
                message = f"Missing templates for accounts: {', '.join(missing_templates)}"
            await call.answer(message, show_alert=True)
            return
        
        # Запускаем автоответчик
        await start_task(user_id, "autoresponder", run_autoresponder(user_id, selected_accounts))
        
        # Устанавливаем флаг активности
        if user_id not in autoresponder_states:
            autoresponder_states[user_id] = {}
        autoresponder_states[user_id]["active"] = True
        autoresponder_states[user_id]["selected_accounts"] = selected_accounts
        
        # Сохраняем состояние в файл
        update_service_state("autoresponder_states", user_id, autoresponder_states[user_id])
        
        try:
            await delete_and_send_image(
                call.message,
                "autoresponder.png",
                f"📼 Автоответчик активирован.",
                reply_markup=get_autoresponder_menu(user_id),
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "autoresponder_stop":
        # Сначала обновляем состояние, потом UI
        if user_id not in autoresponder_states:
            autoresponder_states[user_id] = {"active": False, "selected_accounts": []}
        else:
            autoresponder_states[user_id]["active"] = False
        update_service_state("autoresponder_states", user_id, autoresponder_states[user_id])
        
        try:
            await delete_and_send_image(
                call.message,
                "autoresponder.png",
                "🛑 Автоответчик остановлен.",
                reply_markup=get_autoresponder_menu(user_id),
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        # Запускаем мягкую остановку автоответчика в фоне, чтобы не блокировать UI
        asyncio.create_task(stop_autoresponder(user_id))
        return

    elif data == "autoresponder_templates":
        try:
            await delete_and_send_image(
                call.message,
                "autoresponder.png",
                "Выберите аккаунт для настройки шаблона:",
                reply_markup=get_autoresponder_accounts_menu(user_id, "templates"),
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "autoresponder_account_templates":
        # Возврат к выбору аккаунтов для настройки шаблона
        try:
            await delete_and_send_image(
                call.message,
                "autoresponder.png",
                "Выберите аккаунт для настройки шаблона:",
                reply_markup=get_autoresponder_accounts_menu(user_id, "templates"),
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data.startswith("autoresponder_account_templates|"):
        phone = data.split("|")[1]

        # Если для аккаунта уже есть шаблон — показываем его сразу с действиями
        template = get_autoresponder_template(user_id, phone)
        if template:
            try:
                await delete_and_send_image(
                    call.message,
                    "autoresponder.png",
                    f"Шаблон автоответчика:\n\n{template}",
                    reply_markup=get_autoresponder_template_actions_menu(phone),
                    user_id=user_id
                )
            except TelegramAPIError as e:
                if "message is not modified" not in str(e):
                    raise
            return

        # Если шаблона нет — сразу просим ввести текст шаблона
        user_states[f"{user_id}_autoresponder_phone"] = phone
        try:
            sent_message = await delete_and_send_image(
                call.message,
                "autoresponder.png",
                "Введите текстовое сообщение для автоответчика:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[\
                    InlineKeyboardButton(text="Вернуться 🔙", callback_data="autoresponder_templates")\
                ]]),
                user_id=user_id
            )
            user_states[f"{user_id}_autoresponder_input_message_id"] = sent_message.message_id
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        user_states[user_id] = "waiting_autoresponder_message"
        return

    elif data.startswith("autoresponder_add_template|"):
        phone = data.split("|")[1]
        
        # Сохраняем информацию о том, для какого аккаунта добавляем шаблон
        user_states[f"{user_id}_autoresponder_phone"] = phone
        
        try:
            # Отправляем сообщение и сохраняем его ID для последующего удаления
            sent_message = await delete_and_send_image(
                call.message,
                "autoresponder.png",
                "Введите текстовое сообщение для автоответчика:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="Вернуться 🔙", callback_data=f"autoresponder_account_templates|{phone}")
                ]]),
                user_id=user_id
            )
            # Сохраняем ID сообщения для последующего удаления
            user_states[f"{user_id}_autoresponder_input_message_id"] = sent_message.message_id
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        
        # Устанавливаем состояние ожидания сообщения
        user_states[user_id] = "waiting_autoresponder_message"
        return

    elif data.startswith("autoresponder_show_template|"):
        phone = data.split("|")[1]
        template = get_autoresponder_template(user_id, phone)
        
        try:
            await delete_and_send_image(
                call.message,
                "autoresponder.png",
                f"Шаблон автоответчика:\n\n{template}",
                reply_markup=get_autoresponder_template_actions_menu(phone),
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data.startswith("autoresponder_edit_template|"):
        phone = data.split("|")[1]
        
        # Сохраняем информацию о том, какой шаблон редактируем
        user_states[f"{user_id}_autoresponder_phone"] = phone
        
        current_template = get_autoresponder_template(user_id, phone)
        
        try:
            # Отправляем сообщение и сохраняем его ID для последующего удаления
            sent_message = await delete_and_send_image(
                call.message,
                "autoresponder.png",
                f"Текущий шаблон:\n{current_template}\n\nВведите новое текстовое сообщение для автоответчика:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="Вернуться 🔙", callback_data=f"autoresponder_show_template|{phone}")
                ]]),
                user_id=user_id
            )
            # Сохраняем ID сообщения для последующего удаления
            user_states[f"{user_id}_autoresponder_input_message_id"] = sent_message.message_id
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        
        # Устанавливаем состояние ожидания сообщения
        user_states[user_id] = "waiting_autoresponder_message"
        return

    elif data.startswith("autoresponder_delete_template|"):
        phone = data.split("|")[1]
        
        delete_autoresponder_template(user_id, phone)
        
        try:
            await delete_and_send_image(
                call.message,
                "autoresponder.png",
                f"Шаблон для аккаунта {phone} удален",
                reply_markup=get_autoresponder_account_template_menu(user_id, phone),
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    


    elif data.startswith("postman_acc_"):
        phone = data.replace("postman_acc_", "")
        state = user_states.get(user_id, {})
        selected = state.get("selected_accounts", [])
        # Переключаем выбор
        if phone in selected:
            selected.remove(phone)
        else:
            selected.append(phone)
        state["selected_accounts"] = selected
        state["postman_step"] = "select_accounts"  # <-- сохраняем текущий шаг
        user_states[user_id] = state

        accounts = load_user_accounts(user_id)
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        
        # Добавляем кнопку "Выбрать все"
        all_selected = len(selected) == len(accounts)
        markup.inline_keyboard.append([InlineKeyboardButton(
            text="Выбрать все" if all_selected else "Выбрать все",
            callback_data="postman_select_all"
        )])
        
        for acc in accounts:
            label = acc.get("username") or acc.get("name") or acc.get("phone")
            mark = " ✅" if acc.get("phone") in selected else ""
            label_fixed = f"{label: <5}"  # 5 — можно увеличить при необходимости
            markup.inline_keyboard.append([InlineKeyboardButton(text=f"{label_fixed}{mark}", callback_data=f"postman_acc_{acc.get('phone')}")])
        # Обновляем только клавиатуру с новыми галочками, не пересоздавая сообщение
        await update_postman_accounts_keyboard(call, user_id, selected)
        return


    elif data == "postman_select_all":
        state = user_states.get(user_id, {})
        accounts = load_user_accounts(user_id)
        selected = state.get("selected_accounts", [])
        
        # Если все выбраны - снимаем выбор со всех, иначе выбираем все
        if len(selected) == len(accounts):
            selected = []
        else:
            selected = [acc.get("phone") for acc in accounts]
        
        state["selected_accounts"] = selected
        state["postman_step"] = "select_accounts"
        user_states[user_id] = state
        
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        
        for acc in accounts:
            label = acc.get("username") or acc.get("name") or acc.get("phone")
            mark = " ✅" if acc.get("phone") in selected else ""
            label_fixed = f"{label: <5}"
            markup.inline_keyboard.append([InlineKeyboardButton(text=f"{label_fixed}{mark}", callback_data=f"postman_acc_{acc.get('phone')}")])
        
        # Добавляем кнопку "Выбрать все"
        all_selected = len(selected) == len(accounts)
        markup.inline_keyboard.append([InlineKeyboardButton(
            text="Выбрать все" if all_selected else "Выбрать все",
            callback_data="postman_select_all"
        )])
        
        # Обновляем только клавиатуру с новыми галочками, не пересоздавая сообщение
        await update_postman_accounts_keyboard(call, user_id, selected)
        return


    


    elif data == "postman_activate":
        # Проверка доступа перед началом конфигурирования почтальона
        if not is_license_valid(user_id):
            try:
                ft = load_freetrial()
            except Exception:
                ft = {}
            if str(user_id) in ft and not is_freetrial_valid(user_id):
                alert_text = "Пробный период закончился. Ваши активные сервисы остановлены."
            else:
                alert_text = "Подписка закончилась. Ваши активные сервисы остановлены."
            try:
                await call.answer(alert_text, show_alert=True)
            except Exception:
                pass
            await handle_access_expired(user_id)
            return
        # Проверяем, не активен ли mailboxer
        session = user_sessions.get(user_id, {})
        if "mailboxer" in session:
            # Если mailboxer уже активен, показываем меню с кнопкой "Остановить"
            try:
                await delete_and_send_image(
                    call.message,
                    "mailbox.png",
                    "Почтовый ящик:",
                    reply_markup=get_postman_menu(user_id)
                )
            except TelegramAPIError as e:
                if "message is not modified" not in str(e):
                    raise
            return
        
        accounts = load_user_accounts(user_id)
        if not accounts:
            await call.answer("Нет авторизованных аккаунтов.", show_alert=True)
            return

        license_type = user_states.get(f"{user_id}_license_type")
        if not license_type:
            license_type = detect_license_type(user_id)

        state = user_states.get(user_id)
        if not isinstance(state, dict):
            state = {}
        state["postman_step"] = "select_accounts"
        if "selected_accounts" not in state:
            state["selected_accounts"] = []
        selected = state["selected_accounts"]
        user_states[user_id] = state
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        
        for acc in accounts:
            label = acc.get("username") or acc.get("name") or acc.get("phone")
            mark = " ✅" if acc.get("phone") in selected else ""
            label_fixed = f"{label: <5}"  # 5 — можно увеличить при необходимости
            markup.inline_keyboard.append([InlineKeyboardButton(text=f"{label_fixed}{mark}", callback_data=f"postman_acc_{acc.get('phone')}")])
        
        # Добавляем кнопку "Выбрать все"
        all_selected = len(selected) == len(accounts)
        markup.inline_keyboard.append([InlineKeyboardButton(
            text="Выбрать все" if all_selected else "Выбрать все",
            callback_data="postman_select_all"
        )])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Далее ➡️", callback_data="postman_next", disabled=not selected)])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="postman")])
        try:
            await delete_and_send_image(
                call.message,
                "mailbox.png",
                "Выберите аккаунты, с которых получать уведомления:",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return



    elif data == "postman_next":
        if not is_license_valid(user_id):
            try:
                ft = load_freetrial()
            except Exception:
                ft = {}
            if str(user_id) in ft and not is_freetrial_valid(user_id):
                alert_text = "Пробный период закончился. Ваши активные сервисы остановлены."
            else:
                alert_text = "Подписка закончилась. Ваши активные сервисы остановлены."
            try:
                await call.answer(alert_text, show_alert=True)
            except Exception:
                pass
            await handle_access_expired(user_id)
            return
        state = user_states.get(user_id, {})
        selected = state.get("selected_accounts", [])
        if not selected:
            await call.answer("Выберите хотя бы один аккаунт.", show_alert=True)
            return
        accounts = load_user_accounts(user_id)
        # Показываем ВСЕ аккаунты для выбора почтальона
        state["postman_step"] = "select_postman"
        state["selected_accounts"] = selected
        user_states[user_id] = state

        markup = InlineKeyboardMarkup(inline_keyboard=[])
        for acc in accounts:
            label = acc.get("username") or acc.get("name") or acc.get("phone")
            mark = " ✅" if state.get("postman_selected") == acc.get("phone") else ""
            label_fixed = f"{label: <5}"
            markup.inline_keyboard.append([InlineKeyboardButton(text=f"{label_fixed}{mark}", callback_data=f"postman_postman_{acc.get('phone')}")])
        if state.get("postman_selected"):
            markup.inline_keyboard.append([InlineKeyboardButton(text="Подтвердить ☑️", callback_data="postman_confirm_postman")])
        else:
            markup.inline_keyboard.append([InlineKeyboardButton(text="Подтвердить ☑️", callback_data="postman_confirm_postman", disabled=True)])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="postman_activate")])
        try:
            await delete_and_send_image(
                call.message,
                "mailbox.png",
                "Выберите аккаунт-почтальон (только один):",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return



    elif data.startswith("postman_postman_"):
        phone = data.replace("postman_postman_", "")
        state = user_states.get(user_id, {})
        selected = state.get("selected_accounts", [])
        state["postman_selected"] = phone
        user_states[user_id] = state

        accounts = load_user_accounts(user_id)
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        for acc in accounts:
            label = acc.get("username") or acc.get("name") or acc.get("phone")
            mark = " ✅" if state.get("postman_selected") == acc.get("phone") else ""
            label_fixed = f"{label: <5}"
            markup.inline_keyboard.append([InlineKeyboardButton(text=f"{label_fixed}{mark}", callback_data=f"postman_postman_{acc.get('phone')}")])
        if state.get("postman_selected"):
            markup.inline_keyboard.append([InlineKeyboardButton(text="Подтвердить ☑️", callback_data="postman_confirm_postman")])
        else:
            markup.inline_keyboard.append([InlineKeyboardButton(text="Подтвердить ☑️", callback_data="postman_confirm_postman", disabled=True)])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="postman_activate")])
        try:
            await delete_and_send_image(
                call.message,
                "mailbox.png",
                "Выберите аккаунт-почтальон (только один):",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return



    elif data == "postman_confirm_postman":
        if not is_license_valid(user_id):
            try:
                ft = load_freetrial()
            except Exception:
                ft = {}
            if str(user_id) in ft and not is_freetrial_valid(user_id):
                alert_text = "Пробный период закончился. Ваши активные сервисы остановлены."
            else:
                alert_text = "Подписка закончилась. Ваши активные сервисы остановлены."
            try:
                await call.answer(alert_text, show_alert=True)
            except Exception:
                pass
            await handle_access_expired(user_id)
            return
        state = user_states.get(user_id, {})
        postman_selected = state.get("postman_selected")
        if not postman_selected:
            await call.answer("Выберите почтальона.", show_alert=True)
            return
        state["postman_step"] = "wait_username"
        user_states[user_id] = state
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="postman_next")])
        
        try:
            # Отправляем сообщение и сохраняем его ID для последующего удаления
            sent_message = await delete_and_send_image(
                call.message,
                "mailbox.png",
                "Введите @username, на который хотите получать уведомления:",
                reply_markup=markup,
                user_id=user_id
            )
            # Сохраняем ID сообщения для последующего удаления
            user_states[f"{user_id}_postman_username_message_id"] = sent_message.message_id
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return
    elif data == "postman_stop":
        # Остановить почтальйона
        session = user_sessions.get(user_id)
        if session and "mailboxer" in session:
            mailboxer = session["mailboxer"]
            
            # Проверяем наличие stop_event
            if "stop_event" in mailboxer and mailboxer["stop_event"]:
                stop_event = mailboxer["stop_event"]
                stop_event.set()
            
            # Если был процесс — завершить (на будущее)
            if "process" in mailboxer and mailboxer["process"]:
                p = mailboxer["process"]
                if p.is_alive():
                    p.terminate()
                    p.join(timeout=5)
        
        # Удаляем обработчики событий для всех клиентов mailboxer
        print(f"[POSTMAN_STOP] Начинаем удаление обработчиков для user_id: {user_id}")
        
        # Простой подход: удаляем обработчики для всех активных клиентов пользователя
        if user_id in active_clients:
            print(f"[POSTMAN_STOP] Активные клиенты для user_id {user_id}: {list(active_clients[user_id].keys())}")
            for session_name in active_clients[user_id].keys():
                print(f"[POSTMAN_STOP] Удаляем обработчики для: {session_name}")
                await remove_event_handlers(user_id, session_name)
        else:
            print(f"[POSTMAN_STOP] Нет активных клиентов для user_id {user_id}")
        
        # Также удаляем обработчики для всех аккаунтов пользователя
        accounts = load_user_accounts(user_id)
        for acc in accounts:
            session_name = acc.get("name")
            if session_name:
                print(f"[POSTMAN_STOP] Удаляем обработчики для аккаунта: {session_name}")
                await remove_event_handlers(user_id, session_name)
        
        # Безопасно удаляем mailboxer из сессии, если она существует
        if session and "mailboxer" in session:
            # Дожидаемся завершения фоновой задачи, если она есть
            mb = session["mailboxer"]
            task = mb.get("task") if isinstance(mb, dict) else None
            if task is not None:
                try:
                    await asyncio.wait([task], timeout=5)
                except Exception:
                    pass
            session.pop("mailboxer")
        
        # Очищаем состояние почты
        if user_id in postman_states:
            del postman_states[user_id]
            # Безопасно обновляем состояние в файле
            update_service_state("postman_states", user_id, None)
        
        # Очищаем состояние пользователя
        state = user_states.get(user_id)
        if isinstance(state, dict) and "postman_step" in state:
            state.pop("postman_step", None)
            state.pop("selected_accounts", None)
            state.pop("postman_selected", None)
            state.pop("postman_username", None)
            user_states[user_id] = state
        
        # Обновить меню
        try:
            try:
                await delete_and_send_image(
                    call.message,
                    "mailbox.png",
                    "Почтовый ящик:",
                    reply_markup=get_postman_menu(user_id),
                    user_id=user_id
                )
            except TelegramNetworkError:
                # Мягко игнорируем сетевую ошибку, UI обновится при восстановлении связи
                pass
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data.startswith("autosub_acc_"):
        phone = data.replace("autosub_acc_", "")
        user_states[f"{user_id}_autosub_phone"] = phone

        # Trial-гейт: если лимит уже исчерпан, не даем перейти дальше и показываем alert
        try:
            license_type = detect_license_type(user_id)
            if str(license_type).endswith("trial") or str(license_type) == "trial":
                if get_user_autosub_limit(user_id) >= 5:
                    try:
                        await call.answer(
                            "Достигнут лимит автоподписки для пробного периода. Для безлимитного использования приобретите лицензионный ключ.",
                            show_alert=True
                        )
                    except Exception:
                        pass
                    return
        except Exception:
            pass

        # Удаляем сообщение с меню выбора аккаунта перед разворачиванием/переходом
        try:
            await call.message.delete()
        except Exception:
            pass

        # Если в фоне список уже завершился во время свёрнутости — отправим сохранённое сообщение сразу
        try:
            # Проверяем как по ключу phone, так и по агрегированному ключу
            done_flag = user_states.pop(f"{user_id}_autosub_done_{phone}", None)
            pending = user_states.pop(f"{user_id}_autosub_done_pending", None)
            # Если пользователь явно завершил прошлую сессию — не показываем финальное сообщение, а идём к вводу нового списка
            if user_states.get(f"{user_id}_autosub_finished_{phone}"):
                done_flag = None
                pending = None
            if done_flag or (isinstance(pending, dict) and (pending.get("phone") == phone or not pending.get("phone"))):
                # Определим метку аккаунта
                acc_label = None
                try:
                    if isinstance(pending, dict) and pending.get("label"):
                        acc_label = pending.get("label")
                    else:
                        accounts = load_user_accounts(user_id)
                        for acc in accounts:
                            if acc.get("phone") == phone:
                                acc_label = acc.get("username") or acc.get("name") or acc.get("phone")
                                break
                except Exception:
                    pass
                done_text = "Весь список был успешно обработан. Автоподписка завершена."
                prefixed_text = f"{acc_label}: {done_text}" if acc_label else done_text
                # Снимаем свёрнутость и показываем активную клавиатуру
                user_states.pop(f"{user_id}_autosub_minimized", None)
                await bot.send_message(
                    chat_id=call.message.chat.id,
                    text=prefixed_text,
                    reply_markup=get_autosub_active_keyboard()
                )
                # Не переходим к вводу списка
                try:
                    await call.answer("Возобновлено", show_alert=False)
                except Exception:
                    pass
                return
            # Если флагов нет — продолжаем обычный сценарий (ввод списка)
            else:
                # Если был явный финиш — очищаем маркер и продолжаем обычный сценарий (переход к вводу списка)
                user_states.pop(f"{user_id}_autosub_finished_{phone}", None)
        except Exception:
            pass

        # Если автоподписка уже запущена и выбран тот же аккаунт —
        # разворачиваем интерфейс и продолжаем логирование в чат, не переходя к вводу списка
        try:
            running_phone = user_states.get(f"{user_id}_autosub_running_phone")
            task_key = f"autosubscribe:{phone}"
            if (
                (user_id in active_tasks and task_key in active_tasks[user_id])
                or (load_autosub_state(user_id).get(str(phone), {}).get("remaining"))
            ):
                user_states.pop(f"{user_id}_autosub_minimized_{phone}", None)
                # Помечаем, что пользователь явно развернул логирование для этого телефона
                user_states[f"{user_id}_autosub_unminimized_{phone}"] = True
                # Если во время свёрнутости был завершён список — сообщим об этом вне очереди
                try:
                    if user_states.pop(f"{user_id}_autosub_done_{phone}", None):
                        # Определим метку аккаунта для префикса
                        acc_label = None
                        try:
                            accounts = load_user_accounts(user_id)
                            for acc in accounts:
                                if acc.get("phone") == phone:
                                    acc_label = acc.get("username") or acc.get("name") or acc.get("phone")
                                    break
                        except Exception:
                            pass
                        done_text = "Весь список был успешно обработан. Автоподписка завершена."
                        prefixed_text = f"{acc_label}: {done_text}" if acc_label else done_text
                        await bot.send_message(
                            chat_id=call.message.chat.id,
                            text=prefixed_text,
                            reply_markup=get_autosub_active_keyboard()
                        )
                        # Продолжаем, чтобы также показать информацию о возможном перерыве (если есть)
                except Exception:
                    pass
                # Если финалку показывали до сворачивания — повторим одноразово при разворачивании
                try:
                    replay_flag = user_states.get(f"{user_id}_autosub_last_done_{phone}")
                    replay_label = user_states.get(f"{user_id}_autosub_last_done_label_{phone}")
                    if replay_flag:
                        acc_label = replay_label
                        if not acc_label:
                            try:
                                accounts = load_user_accounts(user_id)
                                for acc in accounts:
                                    if acc.get("phone") == phone:
                                        acc_label = acc.get("username") or acc.get("name") or acc.get("phone")
                                        break
                            except Exception:
                                pass
                        done_text = "Весь список был успешно обработан. Автоподписка завершена."
                        prefixed_text = f"{acc_label}: {done_text}" if acc_label else done_text
                        await bot.send_message(
                            chat_id=call.message.chat.id,
                            text=prefixed_text,
                            reply_markup=get_autosub_active_keyboard()
                        )
                except Exception:
                    pass
                # Если есть активный перерыв — вне очереди сообщим точное оставшееся время ТОЛЬКО для этого аккаунта
                try:
                    started_key = f"{user_id}_autosub_break_{phone}_started_ts"
                    total_key = f"{user_id}_autosub_break_{phone}_total_sec"
                    started_ts = user_states.get(started_key)
                    total_sec = user_states.get(total_key)
                    if isinstance(started_ts, int) and isinstance(total_sec, int) and total_sec > 0:
                        now_ts = int(asyncio.get_event_loop().time())
                        elapsed = max(0, now_ts - started_ts)
                        remaining = max(0, total_sec - elapsed)
                        remaining_min = max(0, (remaining + 59) // 60)
                        if remaining_min > 0:
                            # Префикс аккаунта
                            acc_label3 = None
                            try:
                                accounts = load_user_accounts(user_id)
                                for acc in accounts:
                                    if acc.get("phone") == phone:
                                        acc_label3 = acc.get("username") or acc.get("name") or acc.get("phone")
                                        break
                            except Exception:
                                pass
                            prefix3 = f"{acc_label3}: " if acc_label3 else ""
                            await bot.send_message(
                                chat_id=call.message.chat.id,
                                text=f"{prefix3}До истечения перерыва осталось {remaining_min} минут",
                                reply_markup=get_autosub_active_keyboard()
                            )
                        else:
                            await bot.send_message(
                                chat_id=call.message.chat.id,
                                text="Автоподписка развёрнута ↩️",
                                reply_markup=get_autosub_active_keyboard()
                            )
                    else:
                        await bot.send_message(
                            chat_id=call.message.chat.id,
                            text="Автоподписка развёрнута ↩️",
                            reply_markup=get_autosub_active_keyboard()
                        )
                    # Убрано: не отправляем подсказку "Продолжаю обработку списка. Осталось: N"
                    try:
                        _ = load_autosub_state(user_id).get(str(phone), {}).get("remaining", [])
                        # намеренно ничего не отправляем в чат
                    except Exception:
                        pass
                    # Дополнительно, если есть активное ограничение FloodWait — сообщим оставшиеся секунды
                    try:
                        f_started_key = f"{user_id}_autosub_flood_{phone}_started_ts"
                        f_total_key = f"{user_id}_autosub_flood_{phone}_total_sec"
                        f_started_ts = user_states.get(f_started_key)
                        f_total_sec = user_states.get(f_total_key)
                        if isinstance(f_started_ts, int) and isinstance(f_total_sec, int) and f_total_sec > 0:
                            now_ts2 = int(asyncio.get_event_loop().time())
                            elapsed2 = max(0, now_ts2 - f_started_ts)
                            remaining2 = max(0, f_total_sec - elapsed2)
                            if remaining2 > 0:
                                # Определяем метку аккаунта
                                acc_label2 = None
                                try:
                                    accounts = load_user_accounts(user_id)
                                    for acc in accounts:
                                        if acc.get("phone") == phone:
                                            acc_label2 = acc.get("username") or acc.get("name") or acc.get("phone")
                                            break
                                except Exception:
                                    pass
                                prefix2 = f"{acc_label2}: " if acc_label2 else ""
                                await bot.send_message(
                                    chat_id=call.message.chat.id,
                                    text=f"{prefix2}Telegram API ограничение: требуется подождать {remaining2} секунд.",
                                    reply_markup=get_autosub_active_keyboard()
                                )
                                # Не очищаем ключи, чтобы можно было показать при следующем разворачивании
                    except Exception:
                        pass
                except Exception:
                    pass
                try:
                    await call.answer("Возобновлено", show_alert=False)
                except Exception:
                    pass
                return
        except Exception:
            pass

        # Сразу переходим к вводу списка @username/ссылок без галочек и кнопки «Далее»
        user_states[user_id] = "waiting_autosub_list"

        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="autosubscribe")])
        try:
            sent_message = await delete_and_send_image(
                call.message,
                "mailing.png",
                "Отправьте список @username или https://t.me/… (по одному в строке):",
                reply_markup=markup,
                user_id=user_id
            )
            user_states[f"{user_id}_autosub_input_message_id"] = sent_message.message_id
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return

    elif data == "autosub_next":
        # Проверки
        if not is_license_valid(user_id):
            try:
                ft = load_freetrial()
            except Exception:
                ft = {}
            if str(user_id) in ft and not is_freetrial_valid(user_id):
                alert_text = "Пробный период закончился. Ваши активные сервисы остановлены."
            else:
                alert_text = "Подписка закончилась. Ваши активные сервисы остановлены."
            try:
                await call.answer(alert_text, show_alert=True)
            except Exception:
                pass
            await handle_access_expired(user_id)
            return

        phone = user_states.get(f"{user_id}_autosub_phone")
        if not phone:
            await call.answer("Сначала выберите аккаунт.", show_alert=True)
            return

        # Если автоподписка уже запущена и выбран тот же аккаунт —
        # разворачиваем интерфейс и продолжаем логирование в чат, не переходя к вводу списка
        try:
            running_phone = user_states.get(f"{user_id}_autosub_running_phone")
            task_key = f"autosubscribe:{phone}"
            if (
                (user_id in active_tasks and task_key in active_tasks[user_id])
                or (load_autosub_state(user_id).get(str(phone), {}).get("remaining"))
            ):
                # Снимаем флаг свернутости и помечаем, что клавиатуру надо прикрепить к ближайшему логу
                user_states.pop(f"{user_id}_autosub_minimized_{phone}", None)
                user_states[f"{user_id}_autosub_attach_keyboard_{phone}"] = True
                try:
                    await call.answer("Возобновлено", show_alert=False)
                except Exception:
                    pass
                return
        except Exception:
            pass

        # Переходим к вводу списка @username/ссылок
        user_states[user_id] = "waiting_autosub_list"

        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="autosubscribe")])
        try:
            sent_message = await delete_and_send_image(
                call.message,
                "mailing.png",
                "Отправьте список @username или https://t.me/… (по одному в строке):",
                reply_markup=markup,
                user_id=user_id
            )
            user_states[f"{user_id}_autosub_input_message_id"] = sent_message.message_id
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
        return
@dp.message()
async def handle_all(message: Message):
    global last_bot_message_id
    user_id = message.from_user.id
    state = user_states.get(user_id)


    if state == "wait_license":
        # Сначала удаляем сообщение "Введите лицензионный ключ:" с password.png
        # и показываем результат обработки ключа
        try:
            # Получаем ID сохраненного сообщения с password.png
            password_message_id = user_states.get(f"{user_id}_password_message_id")
            if password_message_id:
                # Удаляем сообщение "Введите лицензионный ключ:" с password.png
                await bot.delete_message(chat_id=message.chat.id, message_id=password_message_id)
                # Очищаем ID сообщения из состояния
                del user_states[f"{user_id}_password_message_id"]
        except Exception:
            pass  # Игнорируем ошибки при удалении
        
        license_code = message.text.strip()
        key_groups = load_key_groups()

        
        # Обработка OWNER лицензии
        if license_code == "andromedasysmode" or license_code in key_groups.get("owner", []):
            user_states[user_id] = "authorized"
            user_states[f"{user_id}_license_type"] = "owner"
            
            # Обновляем основную информацию пользователя в логах
            update_user_main_info(
                user_id,
                license_type="owner",
                license_key=license_code,
                registration_date=datetime.now().strftime("%d.%m.%Y")
            )
            
            # Получаем пути к папкам
            root = get_project_root()
            user_base_dir = os.path.join(root, "user")
            old_dir = os.path.join(user_base_dir, str(user_id))  # Папка без суффикса
            new_dir = os.path.join(user_base_dir, f"{user_id}_owner")  # Папка с суффиксом
            
            # Загружаем существующие настройки из старой папки ДО её переименования
            old_settings_data = {}
            if os.path.exists(old_dir):
                old_settings_file = os.path.join(old_dir, "settings.json")
                if os.path.exists(old_settings_file):
                    try:
                        with open(old_settings_file, "r", encoding="utf-8") as f:
                            old_settings_data = json.load(f) or {}
                    except Exception as e:
                        print(f"Ошибка загрузки старых настроек: {e}")
            
            # Если существует старая папка без суффикса, переименовываем её
            if os.path.exists(old_dir):
                try:
                    os.rename(old_dir, new_dir)
                    print(f"Папка переименована: {old_dir} -> {new_dir}")
                except Exception as e:
                    print(f"Ошибка переименования папки: {e}")
                    # Если не удалось переименовать, создаем новую
                    os.makedirs(new_dir, exist_ok=True)
            else:
                # Если старой папки нет, создаем новую
                os.makedirs(new_dir, exist_ok=True)
            
            # Создаем config.json в папке пользователя
            config_path = os.path.join(new_dir, "config.json")
            config = {}
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                except Exception:
                    config = {}
            
            # Также создаем config.json в папке owner
            owner_dir = os.path.join(root, "owner")
            owner_config_path = os.path.join(owner_dir, "config.json")
            config = {}
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                except Exception:
                    config = {}
            config["api_id"] = 29875596
            config["api_hash"] = "9300a583f2e76cc3650b69e24e350da4"
            
            # Сохраняем config.json в папке пользователя
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            
            # Сохраняем config.json в папке owner
            with open(owner_config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            
            # Создаем settings.json в папке пользователя с сохранением стиля
            settings_file = os.path.join(new_dir, "settings.json")
            
            # Загружаем существующие настройки из старой папки, если они есть
            old_settings_data = {}
            if os.path.exists(old_dir):
                old_settings_file = os.path.join(old_dir, "settings.json")
                if os.path.exists(old_settings_file):
                    try:
                        with open(old_settings_file, "r", encoding="utf-8") as f:
                            old_settings_data = json.load(f) or {}
                    except Exception as e:
                        print(f"Ошибка загрузки старых настроек: {e}")
            
            settings_data = {"language": user_languages.get(user_id, "ru")}
            
            # Сохраняем стиль из старых настроек или ставим дефолтный
            if "style" in old_settings_data:
                settings_data["style"] = old_settings_data["style"]
                print(f"Сохранен стиль из старых настроек: {old_settings_data['style']}")
            else:
                settings_data["style"] = "robo"
                print("Стиль не найден в старых настройках. Установлен стиль по умолчанию: robo")
            
            with open(settings_file, "w", encoding="utf-8") as f:
                json.dump(settings_data, f, ensure_ascii=False, indent=2)
            await delete_and_send_image(
                message,
                "start_menu.png",
                "Ваша лицензия активирована как OWNER.",
                reply_markup=get_main_inline_menu(),
                user_id=user_id
            )
            return
            
        # Обработка ADMIN лицензии
        elif license_code == "andromedamodeadmin" or license_code in key_groups.get("admin", []):
            user_states[user_id] = "authorized"
            user_states[f"{user_id}_license_type"] = "admin"
            
            # Обновляем основную информацию пользователя в логах
            update_user_main_info(
                user_id,
                license_type="admin",
                license_key=license_code
            )
            
            # Получаем пути к папкам
            root = get_project_root()
            user_base_dir = os.path.join(root, "user")
            old_dir = os.path.join(user_base_dir, str(user_id))  # Папка без суффикса
            new_dir = os.path.join(user_base_dir, f"{user_id}_admin")  # Папка с суффиксом
            
            # Загружаем существующие настройки из старой папки ДО её переименования
            old_settings_data = {}
            if os.path.exists(old_dir):
                old_settings_file = os.path.join(old_dir, "settings.json")
                if os.path.exists(old_settings_file):
                    try:
                        with open(old_settings_file, "r", encoding="utf-8") as f:
                            old_settings_data = json.load(f) or {}
                    except Exception as e:
                        print(f"Ошибка загрузки старых настроек: {e}")
            
            # Если существует старая папка без суффикса, переименовываем её
            if os.path.exists(old_dir):
                try:
                    os.rename(old_dir, new_dir)
                    print(f"Папка переименована: {old_dir} -> {new_dir}")
                except Exception as e:
                    print(f"Ошибка переименования папки: {e}")
                    # Если не удалось переименовать, создаем новую
                    os.makedirs(new_dir, exist_ok=True)
            else:
                # Если старой папки нет, создаем новую
                os.makedirs(new_dir, exist_ok=True)
            
            config_path = os.path.join(new_dir, "config.json")
            # --- Формируем config.json как у user ---
            if not os.path.exists(config_path):
                config = {
                    "api_id": 20179612,
                    "api_hash": "97152305c69703ef16f9eb14b3c15f25",
                    "accounts": []
                }
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
            else:
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                except Exception:
                    config = {}
                config["api_id"] = 20179612
                config["api_hash"] = "97152305c69703ef16f9eb14b3c15f25"
                if "accounts" not in config:
                    config["accounts"] = []
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
            
            # Создаем settings.json в папке пользователя с сохранением стиля
            settings_file = os.path.join(new_dir, "settings.json")
            settings_data = {"language": user_languages.get(user_id, "ru")}
            
            # Сохраняем стиль из старых настроек или ставим дефолтный
            if "style" in old_settings_data:
                settings_data["style"] = old_settings_data["style"]
                print(f"Сохранен стиль из старых настроек: {old_settings_data['style']}")
            else:
                settings_data["style"] = "robo"
                print("Стиль не найден в старых настройках. Установлен стиль по умолчанию: robo")
            
            with open(settings_file, "w", encoding="utf-8") as f:
                json.dump(settings_data, f, ensure_ascii=False, indent=2)
            
            await delete_and_send_image(
                message,
                "start_menu.png",
                "Ваша лицензия активирована как ADMIN.",
                reply_markup=get_main_inline_menu(),
                user_id=user_id
            )
            return
            
        # Обработка pro/premium/basic ключей
        elif license_code in set(key_groups.get("pro", []) + key_groups.get("premium", []) + key_groups.get("basic", [])):
            # Проверка и обновление license.json
            update_license(user_id, license_code)
            licenses = load_licenses()
            lic = licenses.get(str(user_id))
            now = int(time.time())
            if lic:
                base_end_ts = lic.get("activated_at", 0) + LICENSE_DURATION_DAYS * 86400
                effective_end_ts = base_end_ts + get_referral_bonus_seconds(user_id)
                if now > effective_end_ts:
                    await delete_and_send_image(
                        message,
                        "start_menu.png",
                        "Срок действия вашей лицензии истёк.",
                        reply_markup=get_start_menu(),
                        user_id=user_id
                    )
                    user_states[user_id] = None
                    return
            user_states[user_id] = "authorized"
            # Определяем тип лицензии по группе ключа
            if license_code in key_groups.get("pro", []):
                user_states[f"{user_id}_license_type"] = "pro"
                suffix = "_pro"
                default_api_id = 22133941
                default_api_hash = "c226d2309461ee258c2aefc4dd19b743"
                license_type = "pro"
            elif license_code in key_groups.get("premium", []):
                user_states[f"{user_id}_license_type"] = "premium"
                suffix = "_premium"
                default_api_id = 22133941
                default_api_hash = "c226d2309461ee258c2aefc4dd19b743"
                license_type = "premium"
            else:
                user_states[f"{user_id}_license_type"] = "basic"
                suffix = "_basic"
                default_api_id = 22133941
                default_api_hash = "c226d2309461ee258c2aefc4dd19b743"
                license_type = "basic"
            
            # Обновляем основную информацию пользователя в логах
            update_user_main_info(
                user_id,
                license_type=license_type,
                license_key=license_code
            )
            
            # Получаем пути к папкам
            root = get_project_root()
            user_base_dir = os.path.join(root, "user")
            old_dir = os.path.join(user_base_dir, str(user_id))  # Папка без суффикса
            new_dir = os.path.join(user_base_dir, f"{user_id}{suffix}")  # Папка с суффиксом

            # При успешной авторизации выставляем authorized=true явно (на случай миграций)
            try:
                lic_rec = licenses.get(str(user_id)) or {}
                lic_rec["authorized"] = True
                licenses[str(user_id)] = lic_rec
                save_licenses(licenses)
            except Exception:
                pass
            
            # Загружаем существующие настройки из старой папки ДО её переименования
            old_settings_data = {}
            if os.path.exists(old_dir):
                old_settings_file = os.path.join(old_dir, "settings.json")
                if os.path.exists(old_settings_file):
                    try:
                        with open(old_settings_file, "r", encoding="utf-8") as f:
                            old_settings_data = json.load(f) or {}
                    except Exception as e:
                        print(f"Ошибка загрузки старых настроек: {e}")
            
            # Если существует старая папка без суффикса, переименовываем её
            if os.path.exists(old_dir):
                try:
                    os.rename(old_dir, new_dir)
                    print(f"Папка переименована: {old_dir} -> {new_dir}")
                except Exception as e:
                    print(f"Ошибка переименования папки: {e}")
                    # Если не удалось переименовать, создаем новую
                    os.makedirs(new_dir, exist_ok=True)
            else:
                # Если старой папки нет, создаем новую
                os.makedirs(new_dir, exist_ok=True)
            
            # --- ДОБАВЬ: создаём config.json, если его нет ---
            config_path = os.path.join(new_dir, "config.json")
            if not os.path.exists(config_path):
                config = {
                    "api_id": 22133941,
                    "api_hash": "c226d2309461ee258c2aefc4dd19b743",
                    "accounts": []
                }
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
            
            # Создаем settings.json в папке пользователя с сохранением стиля
            settings_file = os.path.join(new_dir, "settings.json")
            
            settings_data = {"language": user_languages.get(user_id, "ru")}
            
            # Сохраняем стиль из старых настроек или ставим дефолтный
            if "style" in old_settings_data:
                settings_data["style"] = old_settings_data["style"]
                print(f"Сохранен стиль из старых настроек: {old_settings_data['style']}")
            else:
                settings_data["style"] = "robo"
                print("Стиль не найден в старых настройках. Установлен стиль по умолчанию: robo")
            
            with open(settings_file, "w", encoding="utf-8") as f:
                json.dump(settings_data, f, ensure_ascii=False, indent=2)
            
            # --- КОНЕЦ ДОБАВЛЕНИЯ ---
            # Если пользователь вводил реферальный код на предыдущем шаге, активируем бонус сейчас и очищаем временные данные
            referral_code_tmp = user_states.get(f"{user_id}_referral_code")
            if user_states.get(f"{user_id}_referral_used") and referral_code_tmp and not has_user_used_referral(user_id):
                add_invite(referral_code_tmp, user_id)
            if f"{user_id}_referral_used" in user_states:
                del user_states[f"{user_id}_referral_used"]
            if f"{user_id}_referral_code" in user_states:
                del user_states[f"{user_id}_referral_code"]
            await delete_and_send_image(
                message,
                "start_menu.png",
                "Ваша лицензия активирована.",
                reply_markup=get_main_inline_menu(),
                user_id=user_id
            )
            return
            
        # Обработка trial лицензии (для пользователей с реферальными кодами)
        elif user_states.get(f"{user_id}_referral_used") and license_code in key_groups.get("trial", []):
            user_states[user_id] = "authorized"
            user_states[f"{user_id}_license_type"] = "trial"
            
            # Получаем реферальный код
            referral_code = user_states.get(f"{user_id}_referral_code", "")
            
            # Создаем папку пользователя для trial
            root = get_project_root()
            user_base_dir = os.path.join(root, "user")
            old_dir = os.path.join(user_base_dir, str(user_id))  # Папка без суффикса
            new_dir = os.path.join(user_base_dir, f"{user_id}_trial")  # Папка с суффиксом
            
            # Загружаем существующие настройки из старой папки ДО её переименования
            old_settings_data = {}
            if os.path.exists(old_dir):
                old_settings_file = os.path.join(old_dir, "settings.json")
                if os.path.exists(old_settings_file):
                    try:
                        with open(old_settings_file, "r", encoding="utf-8") as f:
                            old_settings_data = json.load(f) or {}
                    except Exception as e:
                        print(f"Ошибка загрузки старых настроек: {e}")
            
            # Если существует старая папка без суффикса, переименовываем её
            if os.path.exists(old_dir):
                try:
                    os.rename(old_dir, new_dir)
                    print(f"Папка переименована: {old_dir} -> {new_dir}")
                except Exception as e:
                    print(f"Ошибка переименования папки: {e}")
                    # Если не удалось переименовать, создаем новую
                    os.makedirs(new_dir, exist_ok=True)
            else:
                # Если старой папки нет, создаем новую
                os.makedirs(new_dir, exist_ok=True)
            
            # Создаем config.json в папке пользователя
            config_path = os.path.join(new_dir, "config.json")
            config = {"accounts": []}
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            
            # Создаем settings.json в папке пользователя с сохранением стиля
            settings_file = os.path.join(new_dir, "settings.json")
            
            # Загружаем существующие настройки из старой папки, если они есть
            old_settings_data = {}
            if os.path.exists(old_dir):
                old_settings_file = os.path.join(old_dir, "settings.json")
                if os.path.exists(old_settings_file):
                    try:
                        with open(old_settings_file, "r", encoding="utf-8") as f:
                            old_settings_data = json.load(f) or {}
                    except Exception as e:
                        print(f"Ошибка загрузки старых настроек: {e}")
            
            settings_data = {"language": user_languages.get(user_id, "ru")}
            
            # Сохраняем стиль из старых настроек
            if "style" in old_settings_data:
                settings_data["style"] = old_settings_data["style"]
                print(f"Сохранен стиль из старых настроек: {old_settings_data['style']}")
            
            with open(settings_file, "w", encoding="utf-8") as f:
                json.dump(settings_data, f, ensure_ascii=False, indent=2)
            
            # Очищаем временные данные реферала
            if f"{user_id}_referral_used" in user_states:
                del user_states[f"{user_id}_referral_used"]
            if f"{user_id}_referral_code" in user_states:
                del user_states[f"{user_id}_referral_code"]
            
            await delete_and_send_image(
                message,
                "start_menu.png",
                f"🎉 Реферальный код принят! Вам предоставлено 72 часа бесплатного использования.",
                reply_markup=get_main_inline_menu(),
                user_id=user_id
            )
            return
        else:
            # Неверный ключ
            await delete_and_send_image(
                message,
                "start_menu.png",
                "Неверный лицензионный ключ. Попробуйте еще раз или обратитесь к администратору.",
                reply_markup=get_back_to_start_menu(),
                user_id=user_id
            )
            return

    elif state == "waiting_autoresponder_message":
        # Обработка ввода шаблона автоответчика
        template_text = message.text.strip()
        
        # Получаем номер телефона из состояния
        phone = user_states.get(f"{user_id}_autoresponder_phone")
        
        if not phone:
            await message.answer("Ошибка: не найден номер телефона для шаблона")
            user_states[user_id] = "authorized"
            return
        
        if not template_text:
            await message.answer("Пожалуйста, введите текст шаблона")
            return
        
        # Сначала удаляем сообщение "Введите текстовое сообщение для автоответчика:"
        try:
            # Получаем ID сохраненного сообщения с запросом ввода текста
            input_message_id = user_states.get(f"{user_id}_autoresponder_input_message_id")
            if input_message_id:
                # Удаляем сообщение "Введите текстовое сообщение для автоответчика:"
                await bot.delete_message(chat_id=message.chat.id, message_id=input_message_id)
                # Очищаем ID сообщения из состояния
                del user_states[f"{user_id}_autoresponder_input_message_id"]
        except Exception:
            pass  # Игнорируем ошибки при удалении
        
        # Удаляем введенное сообщение
        try:
            await message.delete()
        except Exception:
            pass
        
        # Сохраняем шаблон
        set_autoresponder_template(user_id, phone, template_text)
        
        # Очищаем временные данные
        if f"{user_id}_autoresponder_phone" in user_states:
            del user_states[f"{user_id}_autoresponder_phone"]
        
        # Возвращаем к авторизованному состоянию
        user_states[user_id] = "authorized"
        
        # Показываем сохраненный шаблон и действия
        saved_template = get_autoresponder_template(user_id, phone)
        sent_message = await delete_and_send_image(
            message,
            "autoresponder.png",
            f"Шаблон автоответчика:\n\n{saved_template}",
            reply_markup=get_autoresponder_template_actions_menu(phone),
            user_id=user_id
        )
        # Сохраняем ID сообщения для последующего удаления
        user_states[f"{user_id}_autoresponder_message_id"] = sent_message.message_id
        return

    elif state == "waiting_autosub_list":
        # Пользователь присылает список @username / ссылок для автоподписки
        text = (message.text or "").strip()
        phone = user_states.get(f"{user_id}_autosub_phone")
        if not phone:
            await message.answer("Ошибка: не выбран аккаунт для автоподписки")
            user_states[user_id] = "authorized"
            return

        # Лицензионный guard: блокируем старт автоподписки при истёкшем trial/лицензии
        if not is_license_valid(user_id):
            try:
                await handle_access_expired(user_id)
            except Exception:
                pass
            user_states[user_id] = "authorized"
            return

        # Trial-гейт: ограничиваем количество обрабатываемых элементов на основе settings.autosubscribe_limit
        trial_remaining = None
        try:
            license_type = detect_license_type(user_id)
            if str(license_type).endswith("trial") or str(license_type) == "trial":
                used = get_user_autosub_limit(user_id)
                trial_remaining = max(0, 5 - used)
                if used >= 5 or trial_remaining <= 0:
                    try:
                        await safe_message_answer(
                            message,
                            "⚠️ Достигнут лимит автоподписки для пробного периода. Для безлимитного использования приобретите лицензионный ключ.",
                        )
                    except Exception:
                        pass
                    user_states[user_id] = "authorized"
                    return
        except Exception:
            pass

        # Удаляем сообщение-запрос
        try:
            input_message_id = user_states.get(f"{user_id}_autosub_input_message_id")
            if input_message_id:
                await bot.delete_message(chat_id=message.chat.id, message_id=input_message_id)
                del user_states[f"{user_id}_autosub_input_message_id"]
        except Exception:
            pass

        # Удаляем введенное сообщение
        try:
            await message.delete()
        except Exception:
            pass

        # Разбираем список строк (не ограничиваем длину для trial — ограничения по успехам применяются в процессе)
        raw_list = [line.strip() for line in text.splitlines() if line.strip()]
        if not raw_list:
            await message.answer("Список пуст. Отправьте @username или ссылки на строки.")
            return
        # Сохраняем нормализованный список как оставшиеся (перезапуск-устойчиво)
        try:
            normalized_for_state = normalize_autosub_list(raw_list)
            state_persist = load_autosub_state(user_id)
            acc_state = state_persist.get(str(phone)) or {}
            acc_state["remaining"] = normalized_for_state
            acc_state.setdefault("processed", [])
            state_persist[str(phone)] = acc_state
            save_autosub_state(user_id, state_persist)
        except Exception:
            pass

        # Готовим клиент
        config = load_config(user_id)
        api_id = config.get("api_id")
        api_hash = config.get("api_hash")
        if not api_id or not api_hash:
            await message.answer("Не найдены API ID/HASH в config.json")
            user_states[user_id] = "authorized"
            return

        accounts = load_user_accounts(user_id)
        account = next((a for a in accounts if a.get("phone") == phone), None)
        if not account:
            await message.answer("Аккаунт не найден")
            user_states[user_id] = "authorized"
            return

        session_name = account.get("name") or account.get("phone")
        license_type = user_states.get(f"{user_id}_license_type") or detect_license_type(user_id)
        client = await get_or_create_client(user_id, session_name, api_id, api_hash, license_type)
        if not client:
            await message.answer("Не удалось создать клиента для аккаунта")
            user_states[user_id] = "authorized"
            return

        # Запускаем автоподписку по списку в фоне
        async def run_autosub_list():
            try:
                # Фиксируем номер телефона аккаунта для связывания сообщений и таймера
                current_phone = user_states.get(f"{user_id}_autosub_phone")
                # Сформируем удобную метку аккаунта
                current_label = None
                try:
                    accounts = load_user_accounts(user_id)
                    for acc in accounts:
                        if acc.get("phone") == current_phone:
                            current_label = acc.get("username") or acc.get("name") or acc.get("phone")
                            break
                except Exception:
                    pass

                async def reporter(text: str):
                    try:
                        # Отдаём управление циклу событий для реактивности UI
                        await asyncio.sleep(0)
                        # Сначала всегда обновляем состояние перерыва, даже если свернуто
                        try:
                            if text.startswith("Перерыв ") and text.endswith(" минут"):
                                # Если лимит trial достигнут, подавляем сообщения о перерыве
                                try:
                                    license_type_local = detect_license_type(user_id)
                                    if (str(license_type_local).endswith("trial") or str(license_type_local) == "trial") and get_user_autosub_limit(user_id) >= 5:
                                        return
                                except Exception:
                                    pass
                                minutes_str = text.replace("Перерыв ", "").replace(" минут", "").strip()
                                total_minutes = int(minutes_str)
                                user_states[f"{user_id}_autosub_break_{current_phone}_started_ts"] = int(asyncio.get_event_loop().time())
                                user_states[f"{user_id}_autosub_break_{current_phone}_total_sec"] = total_minutes * 60
                            elif text.startswith("До истечения перерыва осталось ") and text.endswith(" минут"):
                                minutes_left = int(text.replace("До истечения перерыва осталось ", "").replace(" минут", "").strip())
                                user_states[f"{user_id}_autosub_break_{current_phone}_started_ts"] = int(asyncio.get_event_loop().time())
                                user_states[f"{user_id}_autosub_break_{current_phone}_total_sec"] = minutes_left * 60
                            # Отслеживаем FloodWait: "Telegram API ограничение: требуется подождать X секунд."
                            elif text.startswith("Telegram API ограничение: требуется подождать ") and text.endswith(" секунд."):
                                try:
                                    seconds_str = text.replace("Telegram API ограничение: требуется подождать ", "").replace(" секунд.", "").strip()
                                    total_seconds = int(seconds_str)
                                    user_states[f"{user_id}_autosub_flood_{current_phone}_started_ts"] = int(asyncio.get_event_loop().time())
                                    user_states[f"{user_id}_autosub_flood_{current_phone}_total_sec"] = total_seconds
                                except Exception:
                                    pass
                        except Exception:
                            pass

                        # Если свернуто, не логируем в чат (per-phone)
                        if user_states.get(f"{user_id}_autosub_minimized_{current_phone}"):
                            return

                        # Прикрепляем клавиатуру к ближайшему сообщению после разворота, иначе обычное сообщение
                        if user_states.pop(f"{user_id}_autosub_attach_keyboard_{current_phone}", None) or user_states.pop(f"{user_id}_autosub_unminimized_{current_phone}", None):
                            prefixed = f"{current_label}: {text}" if current_label else text
                            try:
                                await bot.send_message(
                                    chat_id=message.chat.id,
                                    text=prefixed,
                                    reply_markup=get_autosub_active_keyboard()
                                )
                            except Exception:
                                pass
                        else:
                            prefixed = f"{current_label}: {text}" if current_label else text
                            try:
                                await bot.send_message(chat_id=message.chat.id, text=prefixed)
                            except Exception:
                                pass

                # Прогресс: переносим обработанные элементы в persisted-state и инкрементируем settings.autosubscribe_limit
                        try:
                            m_ok = re.match(r"^Успешно подписались на (.+)$", text.strip())
                            if m_ok and current_phone:
                                autosub_progress_remove_item(user_id, current_phone, m_ok.group(1))
                                # Инкремент глобального счетчика в settings.json — ТОЛЬКО при фактической подписке
                                try:
                                    increment_user_autosub_limit(user_id, 1)
                                except Exception:
                                    pass
                        except Exception:
                            pass

                        # Если достигнут лимит trial (5), немедленно останавливаем автоподписку
                        try:
                            license_type_local2 = detect_license_type(user_id)
                            if (str(license_type_local2).endswith("trial") or str(license_type_local2) == "trial") and get_user_autosub_limit(user_id) >= 5:
                                # Если не свернуто — уведомим пользователя в чате о достижении лимита
                                try:
                                    minimized_flag = bool(user_states.get(f"{user_id}_autosub_minimized_{current_phone}"))
                                except Exception:
                                    minimized_flag = False
                                if not minimized_flag:
                                    try:
                                        await safe_message_answer(
                                            message,
                                            "⚠️ Достигнут лимит автоподписки для пробного периода. Для безлимитного использования приобретите лицензионный ключ.",
                                            reply_markup=get_autosub_active_keyboard()
                                        )
                                    except Exception:
                                        pass
                                # Помечаем как завершенную для корректного UI
                                try:
                                    user_states[f"{user_id}_autosub_finished_{current_phone}"] = True
                                except Exception:
                                    pass
                                try:
                                    import asyncio as _asyncio
                                    _asyncio.create_task(stop_task(user_id, f"autosubscribe:{current_phone}"))
                                except Exception:
                                    pass
                                return
                        except Exception:
                            pass

                        # Фиксируем факт завершения списка для последующего одноразового повторного показа
                        try:
                            if (text.strip() == "Весь список был успешно обработан. Автоподписка завершена." or "Автоподписка завершена." in text):
                                user_states[f"{user_id}_autosub_last_done_{current_phone}"] = True
                                if current_label:
                                    user_states[f"{user_id}_autosub_last_done_label_{current_phone}"] = current_label
                        except Exception:
                            pass

                        # Если автоподписка свернута и пришло финальное сообщение — сохраняем его для выдачи при развороте
                        try:
                            if user_states.get(f"{user_id}_autosub_minimized_{current_phone}") and (text.strip() == "Весь список был успешно обработан. Автоподписка завершена." or "Автоподписка завершена." in text):
                                user_states[f"{user_id}_autosub_done_{current_phone}"] = True
                                if current_label:
                                    user_states[f"{user_id}_autosub_done_label_{current_phone}"] = current_label
                                # Дублируем в агрегированный ключ на случай несовпадения phone при повторном входе
                                user_states[f"{user_id}_autosub_done_pending"] = {
                                    "phone": current_phone,
                                    "label": current_label
                                }
                                # Не логируем в чат, просто выходим
                                return
                        except Exception:
                            pass

                        # (перенесено выше) отправка сообщений пользователю уже выполнена
                    except Exception:
                        pass
                # Очистим маркеры последнего завершения для текущего аккаунта — начинается новая сессия
                try:
                    if current_phone:
                        user_states.pop(f"{user_id}_autosub_last_done_{current_phone}", None)
                        user_states.pop(f"{user_id}_autosub_last_done_label_{current_phone}", None)
                        user_states.pop(f"{user_id}_autosub_finished_{current_phone}", None)
                except Exception:
                    pass
                # Guard-функция для периодической проверки доступа
                async def _license_guard() -> bool:
                    try:
                        return bool(is_license_valid(user_id))
                    except Exception:
                        return True

                await subscribe_to_chats_list(client, raw_list, reporter, _license_guard)
            except Exception as e:
                print(f"[AUTOSUBSCRIBE_LIST] Ошибка: {e}")

        # Запуск как управляемой задачи с возможностью Стоп/Свернуть (per-phone)
        await start_task(user_id, f"autosubscribe:{phone}", run_autosub_list())
        # Сохраняем, с какого аккаунта сейчас идёт автоподписка
        try:
            running_phone = user_states.get(f"{user_id}_autosub_phone")
            if running_phone:
                user_states[f"{user_id}_autosub_running_phone"] = running_phone
        except Exception:
            pass

        # Снимаем флаг свернутости на старте только для данного аккаунта
        try:
            user_states.pop(f"{user_id}_autosub_minimized_{phone}", None)
        except Exception:
            pass
        # Показать клавиатуру управления как в рассылке
        try:
            await safe_message_answer(
                message,
                "Автоподписка запущена. Вы можете свернуть или остановить процесс.",
                reply_markup=get_autosub_active_keyboard()
            )
        except Exception:
            pass
        # Оставляем состояние прежним UI-wise; управление кнопками через ReplyKeyboard
        return

    if state == "wait_referral_code":
        # Сначала удаляем сообщение "Введите реферальный код" и введенное сообщение
        try:
            # Получаем ID сохраненного сообщения с запросом ввода реферального кода
            referral_message_id = user_states.get(f"{user_id}_referral_input_message_id")
            if referral_message_id:
                # Удаляем сообщение "Введите реферальный код"
                await bot.delete_message(chat_id=message.chat.id, message_id=referral_message_id)
                # Очищаем ID сообщения из состояния
                del user_states[f"{user_id}_referral_input_message_id"]
        except Exception:
            pass  # Игнорируем ошибки при удалении
        
        # Удаляем введенное сообщение
        try:
            await message.delete()
        except Exception:
            pass
        
        referral_code = message.text.strip()
        
        # Проверяем валидность реферального кода
        if is_valid_referral_code(referral_code):
            # Реферальный код валиден - отмечаем это и переходим к вводу лицензии
            user_states[f"{user_id}_referral_used"] = True
            user_states[f"{user_id}_referral_code"] = referral_code
            
            # Сохраняем реферальный код в логи
            update_user_main_info(user_id, referral=referral_code)
            
            # Переходим к запросу лицензионного ключа
            markup = get_back_to_referral_menu() if user_languages.get(user_id, "ru") == "ru" else get_back_to_referral_menu_en()
            markup = get_back_to_referral_menu() if user_languages.get(user_id, "ru") == "ru" else get_back_to_referral_menu_en()
            # Отправляем сообщение и сохраняем его ID для последующего удаления
            sent_message = await delete_and_send_image(
                message,
                "password.png",
                "🪪 Введите лицензионный ключ:",
                reply_markup=markup,
                user_id=user_id
            )
            # Сохраняем ID сообщения для последующего удаления
            user_states[f"{user_id}_password_message_id"] = sent_message.message_id
            user_states[user_id] = "wait_license"
        else:
            # Реферальный код невалиден - возвращаем к выбору
            markup = get_referral_menu() if user_languages.get(user_id, "ru") == "ru" else get_referral_menu_en()
            await delete_and_send_image(
                message,
                "password.png",
                "❌ Неверный реферальный код. Попробуйте еще раз или нажмите 'Пропустить'.",
                reply_markup=markup,
                user_id=user_id
            )
            user_states[user_id] = "wait_referral_choice"
        return

        





    if state == "wait_phone":
        phone = message.text.strip()
        
        # Сначала удаляем сообщение "Введите номер телефона:" и введенное сообщение
        try:
            # Получаем ID сохраненного сообщения
            phone_message_id = user_states.get(f"{user_id}_phone_message_id")
            if phone_message_id:
                # Удаляем сообщение "Введите номер телефона:"
                await bot.delete_message(chat_id=message.chat.id, message_id=phone_message_id)
                # Очищаем ID сообщения из состояния
                del user_states[f"{user_id}_phone_message_id"]
        except Exception:
            pass  # Игнорируем ошибки при удалении
        
        # Удаляем введенное сообщение
        try:
            await message.delete()
        except Exception:
            pass
        
        user_states[f"{user_id}_new_phone"] = phone

        # --- ДОБАВЬТЕ ПРОВЕРКУ ЛИМИТА СЕССИЙ ПЕРЕД АВТОРИЗАЦИЕЙ ---
        can_add, msg = can_add_session(user_id)
        if not can_add:
            await message.answer(
                msg,
                reply_markup=get_accounts_menu(user_id)
            )
            user_states[user_id] = "accounts_menu"
            return
        # --- КОНЕЦ ВСТАВКИ ---

        try:
            from telethon.sync import TelegramClient
            license_type = user_states.get(f"{user_id}_license_type")
            if not license_type:
                license_type = detect_license_type(user_id)
            user_dir = get_user_dir(user_id, license_type)
            sessions_dir = os.path.join(get_user_subdir(user_id, "bot", license_type), "sessions")
            os.makedirs(sessions_dir, exist_ok=True)
            config_path = os.path.join(user_dir, "config.json")
            session_path = os.path.join(sessions_dir, f"{phone}")

            # Создаем config.json если он не существует
            if not os.path.exists(config_path):
                config = {"accounts": []}
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
            else:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            api_id = config.get("api_id")
            api_hash = config.get("api_hash")

            if not api_id or not api_hash:
                await message.answer(
                    "Ошибка: не найден API_ID или API_HASH. Пройдите авторизацию заново.",
                    reply_markup=get_back_to_start_menu()
                )
                user_states[user_id] = None
                return

            # Проверяем, существует ли уже сессия
            if os.path.exists(session_path + ".session"):
                client = TelegramClient(session_path, api_id, api_hash)
                try:
                    await asyncio.wait_for(client.connect(), timeout=30.0)
                    if await client.is_user_authorized():
                        await client.disconnect()
                        await message.answer(
                            f"Аккаунт {phone} уже авторизован и добавлен!",
                            reply_markup=get_accounts_menu(user_id)
                        )
                        user_states[user_id] = "accounts_menu"
                        user_states.pop(f"{user_id}_new_phone", None)
                        user_states.pop(f"{user_id}_phone_code_hash", None)
                        return
                    else:
                        await client.disconnect()
                        os.remove(session_path + ".session")
                except asyncio.TimeoutError:
                    await client.disconnect()
                    print(f"Таймаут при проверке существующей сессии для пользователя {user_id}")
                    if os.path.exists(session_path + ".session"):
                        os.remove(session_path + ".session")
                except Exception as e:
                    print(f"Ошибка при проверке существующей сессии: {e}")
                    if os.path.exists(session_path + ".session"):
                        os.remove(session_path + ".session")

            # Отправляем код подтверждения
            client = TelegramClient(session_path, api_id, api_hash)
            try:
                await asyncio.wait_for(client.connect(), timeout=30.0)
                sent = await asyncio.wait_for(client.send_code_request(phone), timeout=30.0)
                user_states[f"{user_id}_phone_code_hash"] = sent.phone_code_hash
                await client.disconnect()
            except asyncio.TimeoutError:
                await client.disconnect()
                raise Exception("Таймаут при отправке кода. Проверьте интернет-соединение.")
            except Exception as e:
                await client.disconnect()
                raise e
                
        except Exception as e:
            print(f"Ошибка при отправке кода для пользователя {user_id}: {e}")
            await message.answer(
                f"Ошибка при отправке кода: {str(e)}\nПопробуйте ещё раз.",
                reply_markup=back_menu_auth
            )
            user_states[user_id] = "wait_phone"
            return

        # Отправляем сообщение и сохраняем его ID для последующего удаления
        sent_message = await message.answer(
            "Введите код подтверждения из Telegram:",  # изменено здесь
            reply_markup=back_menu_auth
        )
        # Сохраняем ID сообщения для последующего удаления
        user_states[f"{user_id}_code_message_id"] = sent_message.message_id
        user_states[user_id] = "wait_code"
        return

    if state == "wait_code":
        code = message.text.strip()
        
        # Сначала удаляем сообщение "Введите код подтверждения из Telegram:" и введенное сообщение
        try:
            # Получаем ID сохраненного сообщения
            code_message_id = user_states.get(f"{user_id}_code_message_id")
            if code_message_id:
                # Удаляем сообщение "Введите код подтверждения из Telegram:"
                await bot.delete_message(chat_id=message.chat.id, message_id=code_message_id)
                # Очищаем ID сообщения из состояния
                del user_states[f"{user_id}_code_message_id"]
        except Exception:
            pass  # Игнорируем ошибки при удалении
        
        # Удаляем введенное сообщение
        try:
            await message.delete()
        except Exception:
            pass
        
        phone = user_states.get(f"{user_id}_new_phone")
        phone_code_hash = user_states.get(f"{user_id}_phone_code_hash")
        if not phone or not phone_code_hash:
            await message.answer(
                "Ошибка: номер телефона или phone_code_hash не найден. Начните заново.",
                reply_markup=back_menu_auth
            )
            user_states[user_id] = None
            return

        try:
            from telethon.sync import TelegramClient
            from telethon.errors import SessionPasswordNeededError
            license_type = user_states.get(f"{user_id}_license_type")
            if not license_type:
                license_type = detect_license_type(user_id)
            user_dir = get_user_dir(user_id, license_type)
            sessions_dir = os.path.join(get_user_subdir(user_id, "bot", license_type), "sessions")
            os.makedirs(sessions_dir, exist_ok=True)
            config_path = os.path.join(user_dir, "config.json")
            session_path = os.path.join(sessions_dir, f"{phone}")

            # Создаем config.json если он не существует
            if not os.path.exists(config_path):
                config = {"accounts": []}
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
            else:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            api_id = config.get("api_id")
            api_hash = config.get("api_hash")

            if not api_id or not api_hash:
                await message.answer(
                    "Ошибка: не найден API_ID или API_HASH. Пройдите авторизацию заново.",
                    reply_markup=get_back_to_start_menu()
                )
                user_states[user_id] = None
                return

            # Подключаемся к Telegram и авторизуемся
            client = TelegramClient(session_path, api_id, api_hash)
            try:
                await asyncio.wait_for(client.connect(), timeout=30.0)
                
                if not await client.is_user_authorized():
                    try:
                        await asyncio.wait_for(client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash), timeout=30.0)
                    except SessionPasswordNeededError:
                        await client.disconnect()
                        user_states[user_id] = "wait_password"
                        user_states[f"{user_id}_2fa_phone"] = phone
                        bot_message = await message.answer(
                            "2FA:",
                            reply_markup=back_menu_auth
                        )
                        # Сохраняем ID сообщения "2FA:" для последующего удаления
                        user_states[f"{user_id}_2fa_message_id"] = bot_message.message_id
                        return
                
                # Получаем информацию о пользователе
                me = await asyncio.wait_for(client.get_me(), timeout=30.0)
                username = me.username if hasattr(me, "username") and me.username else None
                name = me.first_name if hasattr(me, "first_name") and me.first_name else None
                user_id_telegram = me.id if hasattr(me, "id") else None
                session_name = name  # Всегда используем имя
                new_session_path = os.path.join(sessions_dir, f"{session_name}")

                # Если имя сессии отличается, переименовать файл
                if session_path != new_session_path:
                    if os.path.exists(session_path + ".session"):
                        os.rename(session_path + ".session", new_session_path + ".session")
                    session_path = new_session_path

                # ПОЛУЧАЕМ ВСЕ @USERNAME ДИАЛОГОВ ДО ОТКЛЮЧЕНИЯ КЛИЕНТА
                dialogs_data = await get_all_dialogs_usernames(client)
                
                await client.disconnect()
                # На случай ре-авторизации: снимем принудительные метки отключения
                try:
                    if (user_id, session_name) in disabled_clients:
                        disabled_clients.discard((user_id, session_name))
                    if session_name in disabled_session_names:
                        disabled_session_names.discard(session_name)
                except Exception:
                    pass

                # Добавляем сессию в license.json
                add_session_to_license(user_id, session_name)

                # Обновляем config.json с новым аккаунтом
                accounts = config.get("accounts", [])
                found = False
                for acc in accounts:
                    if acc.get("phone") == phone:
                        acc["name"] = name
                        if username:
                            acc["username"] = username
                        if user_id_telegram:
                            acc["user_id"] = user_id_telegram
                        found = True
                if not found:
                    new_account = {
                        "name": name,
                        "phone": phone,
                    }
                    if username:
                        new_account["username"] = username
                    if user_id_telegram:
                        new_account["user_id"] = user_id_telegram
                    accounts.append(new_account)
                config["accounts"] = accounts
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
                    
            except asyncio.TimeoutError:
                await client.disconnect()
                raise Exception("Таймаут при авторизации. Проверьте интернет-соединение.")
            except Exception as e:
                await client.disconnect()
                raise e
                
        except Exception as e:
            print(f"Ошибка авторизации для пользователя {user_id}: {e}")
            user_states.pop(f"{user_id}_phone_code_hash", None)
            user_states.pop(f"{user_id}_new_phone", None)
            user_states[user_id] = "wait_phone"
            await message.answer(
                f"Ошибка авторизации: {str(e)}\nКод устарел или введён номер телефона, с которого был запущен бот. Введите номер телефона еще раз:",
                reply_markup=back_menu_auth
            )
            return

        # Создаем resume_process.json при первой авторизации
        resume_state_file = os.path.join(user_dir, "resume_process.json")
        if not os.path.exists(resume_state_file):
            initial_resume_state = {
                "accounts": {},
                "global_state": {
                    "last_activity": int(time.time()),
                    "version": "1.0"
                }
            }
            with open(resume_state_file, "w", encoding="utf-8") as f:
                json.dump(initial_resume_state, f, ensure_ascii=False, indent=2)
        
        # Сразу сохраняем информацию об аккаунте в logs.json
        update_user_account_info_in_logs(user_id, name, phone, username, user_id_telegram)
        
        # ОБНОВЛЯЕМ COOKIES.JSON С ПОЛУЧЕННЫМИ ДАННЫМИ
        if dialogs_data:
            update_cookies_json(user_id, session_name, dialogs_data)
        
        await message.answer(
            f"Аккаунт {phone} успешно добавлен!",
            reply_markup=get_accounts_menu(user_id)
        )
        user_states[user_id] = "accounts_menu"
        user_states.pop(f"user_id_new_phone", None)
        user_states.pop(f"{user_id}_api_id", None)
        user_states[user_id] = "authorized"
        authorized_users.add(user_id)
        return



    if state == "wait_password":
        # Удаляем сообщение "2FA:" и сообщение пользователя с паролем
        try:
            # Удаляем сообщение "2FA:" от бота
            bot_2fa_message_id = user_states.get(f"{user_id}_2fa_message_id")
            if bot_2fa_message_id:
                await bot.delete_message(chat_id=message.chat.id, message_id=bot_2fa_message_id)
                # Очищаем ID сообщения из состояния
                del user_states[f"{user_id}_2fa_message_id"]
        except Exception:
            pass  # Игнорируем ошибки при удалении
        
        # Удаляем сообщение пользователя с паролем
        try:
            await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)
        except Exception:
            pass  # Игнорируем ошибки при удалении
        
        password = message.text.strip()
        phone = user_states.get(f"{user_id}_2fa_phone")
        license_type = user_states.get(f"{user_id}_license_type")
        if not license_type:
            license_type = detect_license_type(user_id)
        user_dir = get_user_dir(user_id, license_type)
        sessions_dir = os.path.join(get_user_subdir(user_id, "bot", license_type), "sessions")
        config_path = os.path.join(user_dir, "config.json")
        session_path = os.path.join(sessions_dir, f"{phone}")

        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        api_id = config.get("api_id")
        api_hash = config.get("api_hash")

        try:
            from telethon.sync import TelegramClient
            client = TelegramClient(session_path, api_id, api_hash)
            try:
                await asyncio.wait_for(client.connect(), timeout=30.0)
                await asyncio.wait_for(client.sign_in(password=password), timeout=30.0)
                me = await asyncio.wait_for(client.get_me(), timeout=30.0)
                username = me.username if hasattr(me, "username") and me.username else None
                name = me.first_name if hasattr(me, "first_name") and me.first_name else None
                user_id_telegram = me.id if hasattr(me, "id") else None
                session_name = name  # Всегда используем имя
                new_session_path = os.path.join(sessions_dir, f"{session_name}")
            except asyncio.TimeoutError:
                await client.disconnect()
                raise Exception("Таймаут при авторизации 2FA. Проверьте интернет-соединение.")
            except Exception as e:
                await client.disconnect()
                raise e

            if session_path != new_session_path:
                if os.path.exists(session_path + ".session"):
                    os.rename(session_path + ".session", new_session_path + ".session")
                session_path = new_session_path

            # ПОЛУЧАЕМ ВСЕ @USERNAME ДИАЛОГОВ ДО ОТКЛЮЧЕНИЯ КЛИЕНТА
            dialogs_data = await get_all_dialogs_usernames(client)

            await client.disconnect()

            # --- ДОБАВЬТЕ ЗАПИСЬ СЕССИИ В LICENSE.JSON ---
            add_session_to_license(user_id, session_name)
            # --- КОНЕЦ ВСТАВКИ ---
        except Exception as e:
            print(f"Ошибка 2FA авторизации для пользователя {user_id}: {e}")
            # Очищаем ID сообщения 2FA при ошибке, чтобы пользователь мог попробовать снова
            if user_id in last_bot_message_id:
                del last_bot_message_id[user_id]
            # Очищаем ID сообщения 2FA из состояния при ошибке
            user_states.pop(f"{user_id}_2fa_message_id", None)
            await message.answer(
                f"Ошибка авторизации (2FA): {str(e)}\nПопробуйте ещё раз. Введите пароль:",
                reply_markup=back_menu_auth
            )
            user_states[user_id] = "wait_password"
            return

        accounts = config.get("accounts", [])
        found = False
        for acc in accounts:
            if acc.get("phone") == phone:
                acc["name"] = name
                if username:
                    acc["username"] = username
                if user_id_telegram:
                    acc["user_id"] = user_id_telegram
                found = True
        if not found:
            new_account = {
                "name": name,
                "phone": phone,
            }
            if username:
                new_account["username"] = username
            if user_id_telegram:
                new_account["user_id"] = user_id_telegram
            accounts.append(new_account)
        config["accounts"] = accounts
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        # Создаем resume_process.json при первой авторизации (2FA)
        resume_state_file = os.path.join(user_dir, "resume_process.json")
        if not os.path.exists(resume_state_file):
            initial_resume_state = {
                "accounts": {},
                "global_state": {
                    "last_activity": int(time.time()),
                    "version": "1.0"
                }
            }
            with open(resume_state_file, "w", encoding="utf-8") as f:
                json.dump(initial_resume_state, f, ensure_ascii=False, indent=2)
        
        # Сразу сохраняем информацию об аккаунте в logs.json
        update_user_account_info_in_logs(user_id, name, phone, username, user_id_telegram)
        
        # ОБНОВЛЯЕМ COOKIES.JSON С ПОЛУЧЕННЫМИ ДАННЫМИ
        if dialogs_data:
            update_cookies_json(user_id, session_name, dialogs_data)
        
        await message.answer(
            f"Аккаунт {phone} успешно добавлен!",
            reply_markup=get_accounts_menu(user_id)
        )
        user_states[user_id] = "accounts_menu"
        user_states.pop(f"{user_id}_2fa_phone", None)
        user_states.pop(f"{user_id}_new_phone", None)
        user_states.pop(f"{user_id}_phone_code_hash", None)
        # Очищаем ID сообщения 2FA после успешной авторизации
        user_states.pop(f"{user_id}_2fa_message_id", None)
        if user_id in last_bot_message_id:
            del last_bot_message_id[user_id]
        return







    # --- Добавление шаблона ---
    if isinstance(state, str) and state.startswith("wait_template_"):
        phone = state.replace("wait_template_", "")
        template_text = message.text.strip()
        
        # Сначала удаляем сообщение "Введите текстовый шаблон:" с mailing.png
        # и показываем результат обработки шаблона
        try:
            # Получаем ID сохраненного сообщения с mailing.png
            template_message_id = user_states.get(f"{user_id}_template_message_id")
            if template_message_id:
                # Удаляем сообщение "Введите текстовый шаблон:" с mailing.png
                await bot.delete_message(chat_id=message.chat.id, message_id=template_message_id)
                # Очищаем ID сообщения из состояния
                del user_states[f"{user_id}_template_message_id"]
        except Exception:
            pass  # Игнорируем ошибки при удалении
        
        # Удаляем введенное сообщение
        try:
            await message.delete()
        except Exception:
            pass
        
        accounts = load_user_accounts(user_id)
        acc = next((a for a in accounts if a.get("phone") == phone), None)
        if not acc:
            await message.answer("Аккаунт не найден.")
            user_states[user_id] = "select_template_account"
            return
        i = 1
        while f"template{i}" in acc:
            i += 1
        acc[f"template{i}"] = template_text
        save_user_accounts(user_id, accounts)
        await message.answer(
            f"Шаблон сохранён для аккаунта {phone}.",
            reply_markup=get_templates_list_menu(phone, [acc[f"template{j}"] for j in range(1, i+1)])
        )
        user_states[user_id] = f"templates_list_{phone}"
        return

    # --- Редактирование шаблона ---
    if isinstance(state, str) and state.startswith("edit_template_"):
        # state: edit_template_{phone}_{idx}
        m = re.match(r"edit_template_(.+)_(\d+)", state)
        if not m:
            await message.answer("Ошибка состояния шаблона.")
            user_states[user_id] = "select_template_account"
            return
        phone, idx = m.group(1), m.group(2)
        template_text = message.text.strip()
        
        # Сначала удаляем сообщение "Введите новый текст для шаблона:" с mailing.png
        # и показываем результат обработки шаблона
        try:
            # Получаем ID сохраненного сообщения с mailing.png
            template_message_id = user_states.get(f"{user_id}_template_message_id")
            if template_message_id:
                # Удаляем сообщение "Введите новый текст для шаблона:" с mailing.png
                await bot.delete_message(chat_id=message.chat.id, message_id=template_message_id)
                # Очищаем ID сообщения из состояния
                del user_states[f"{user_id}_template_message_id"]
        except Exception:
            pass  # Игнорируем ошибки при удалении
        
        # Удаляем введенное сообщение
        try:
            await message.delete()
        except Exception:
            pass
        
        accounts = load_user_accounts(user_id)
        acc = next((a for a in accounts if a.get("phone") == phone), None)
        if not acc:
            await message.answer("Аккаунт не найден.")
            user_states[user_id] = "select_template_account"
            return
        key = f"template{idx}"
        acc[key] = template_text
        save_user_accounts(user_id, accounts)
        # Показываем обновлённый список шаблонов
        templates = []
        i = 1
        while True:
            k = f"template{i}"
            if k in acc:
                templates.append(acc[k])
                i += 1
            else:
                break
        await message.answer(
            f"Шаблон #{idx} обновлён.",
            reply_markup=get_templates_list_menu(phone, templates)
        )
        user_states[user_id] = f"templates_list_{phone}"
        return
    
    


    # --- Ввод username для почтальона и запуск "Почта" ---

    elif isinstance(state, dict) and state.get("postman_step") == "wait_username":
        username = message.text.strip()
        state["postman_username"] = username
        user_states[user_id] = state
        
        # Сначала удаляем сообщение "Введите @username, на который хотите получать уведомления:"
        try:
            # Получаем ID сохраненного сообщения с запросом @username
            username_message_id = user_states.get(f"{user_id}_postman_username_message_id")
            if username_message_id:
                # Удаляем сообщение "Введите @username, на который хотите получать уведомления:"
                await bot.delete_message(chat_id=message.chat.id, message_id=username_message_id)
                # Очищаем ID сообщения из состояния
                del user_states[f"{user_id}_postman_username_message_id"]
        except Exception:
            pass  # Игнорируем ошибки при удалении
        
        # Удаляем введенное сообщение
        try:
            await message.delete()
        except Exception:
            pass
        
        # --- Запуск mailboxer в фоне ---
        selected_accounts = [acc for acc in load_user_accounts(user_id) if acc.get("phone") in state.get("selected_accounts", [])]
        postman_account = next((acc for acc in load_user_accounts(user_id) if acc.get("phone") == state.get("postman_selected")), None)
        group_id = None  # если нужен id группы, подставьте здесь
        notify_username = username
        stop_event = threading.Event()
        if user_id not in user_sessions:
            user_sessions[user_id] = {}
        user_sessions[user_id]["mailboxer"] = {
            "process": None,  # сюда можно сохранить объект процесса, если используется multiprocessing
            "stop_event": stop_event,
            "task": None,
        }
        
        # Запускаем mailboxer в фоне
        print("Запуск run_mailboxer в фоне...")
        _task = asyncio.create_task(run_mailboxer(
            user_id,
            user_states.get(f"{user_id}_license_type"),
            selected_accounts,
            postman_account,
            group_id,
            notify_username,
            stop_event
        ))
        # Сохраняем ссылку на задачу, чтобы корректно дождаться её при остановке
        user_sessions[user_id]["mailboxer"]["task"] = _task
        
        # Отправляем сообщение и сохраняем его ID для последующего удаления
        sent_message = await delete_and_send_image(
            message,
            "mailbox.png",
            f"Отстук почты на {username} активирован.",
            reply_markup=get_postman_menu(user_id),
            user_id=user_id
        )
        # Сохраняем ID сообщения для последующего удаления
        user_states[f"{user_id}_postman_message_id"] = sent_message.message_id


def print_in_white(text):
    return f"\033[97m{text}\033[0m"

def print_in_red(text):
    return f"\033[91m{text}\033[0m"

def print_in_yellow(text):
    return f"\033[93m{text}\033[0m"

def print_in_green(text):
    return f"\033[92m{text}\033[0m"


def is_internet_available():
    """Проверяет доступность интернета"""
    try:
        # Пытаемся подключиться к публичному DNS-серверу Google
        socket.create_connection(("8.8.8.8", 53), timeout=5)
        return True
    except OSError:
        return False
    

def print_separator():
    print("\n" + "-" * 50 + "\n")


def get_templates_for_account(account):
    templates = []
    i = 1
    while True:
        key = f"template{i}"
        if key in account:
            templates.append(account[key])
            i += 1
        else:
            break
    return templates

def get_templates_from_config(config_data, phone):
    """Загружает шаблоны для конкретного аккаунта из config.json по номеру телефона"""
    templates = []
    
    # Ищем аккаунт в массиве accounts
    if "accounts" in config_data:
        for account in config_data["accounts"]:
            if account.get("phone") == phone:
                # Нашли нужный аккаунт, извлекаем шаблоны
                i = 1
                while True:
                    key = f"template{i}"
                    if key in account:
                        templates.append(account[key])
                        i += 1
                    else:
                        break
                break
    
    return templates

def load_config(user_id):
    """Загружает config.json для пользователя"""
    try:
        license_type = detect_license_type(user_id)
        config_path = get_user_dir(user_id, license_type) + "/config.json"
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    except Exception as e:
        print(f"❌ Ошибка загрузки config.json для пользователя {user_id}: {e}")
        return {}

async def get_folder_by_index(client, folder_index):
    """Получает папку по индексу для режима select"""
    try:
        folders = await list_folders(client)
        if not folders:
            return {"id": 1, "title": "Default"}
        
        folder_keys = list(folders.keys())
        if 0 <= folder_index < len(folder_keys):
            return folders[folder_keys[folder_index]]
        else:
            return folders[folder_keys[0]] if folder_keys else {"id": 1, "title": "Default"}
    except Exception:
        return {"id": 1, "title": "Default"}


def save_resume_state(state, filename=None, user_id=None):
    """Сохранение состояния рассылки в resume_process.json"""
    if filename is None:
        if user_id is None:
            filename = resume_state_file
        else:
            user_dir = get_user_dir(user_id, detect_license_type(user_id))
            filename = os.path.join(user_dir, "resume_process.json")
    
    # Создаем директорию если не существует
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def load_resume_state(filename=None, user_id=None):
    """Загрузка состояния рассылки из resume_process.json"""
    if filename is None:
        if user_id is None:
            filename = resume_state_file
        else:
            user_dir = get_user_dir(user_id, detect_license_type(user_id))
            filename = os.path.join(user_dir, "resume_process.json")
    
    if not os.path.exists(filename):
        return None
    try:
        with open(filename, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return None
            return json.loads(content)
    except Exception:
        return None

def get_display_name(account):
    """Возвращает правильное отображение имени аккаунта: username без @, если есть, иначе nickname"""
    username = account.get('username', '')
    if username and not username.startswith('@'):
        return username
    elif username and username.startswith('@'):
        return username[1:]  # Убираем @
    else:
        return account.get("nickname", account.get("phone", "Неизвестно"))

def migrate_account_username(account, config_accounts):
    """Мигрирует username из config в account, если его нет"""
    if 'username' not in account or not account['username']:
        # Ищем соответствующий аккаунт в конфиге
        for config_acc in config_accounts:
            if config_acc.get('phone') == account.get('phone'):
                if config_acc.get('username'):
                    account['username'] = config_acc['username']
                break
    return account

def get_accounts_break_status(user_id):
    """Возвращает информацию о перерывах аккаунтов в формате для отображения"""
    resume_state = load_resume_state(user_id=user_id)
    if not resume_state or "accounts" not in resume_state:
        return []
    
    # Загружаем конфиг для миграции username
    config = load_config(user_id)
    config_accounts = config.get("accounts", []) if config else []
    
    current_time = int(time.time())
    break_info = []
    
    for account in resume_state["accounts"]:
        # Мигрируем username если его нет
        account = migrate_account_username(account, config_accounts)
        
        # Проверяем, находится ли аккаунт на перерыве
        if account.get("break_until_timestamp", 0) > current_time:
            # Аккаунт на перерыве
            break_until = account["break_until_timestamp"]
            seconds_left = break_until - current_time
            
            # Форматируем оставшееся время
            hours = seconds_left // 3600
            minutes = (seconds_left % 3600) // 60
            seconds = seconds_left % 60
            
            time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            display_name = get_display_name(account)
            
            break_info.append({
                "nickname": display_name,
                "time_left": time_str,
                "seconds_left": seconds_left
            })
    
    # Сортируем по оставшемуся времени (сначала те, у кого больше времени)
    break_info.sort(key=lambda x: x["seconds_left"], reverse=True)
    return break_info
async def get_folder_name_by_id(client, folder_id):
    """Получает название папки по её ID"""
    try:
        folders = await list_folders(client)
        for folder_data in folders.values():
            if folder_data.get('id') == folder_id:
                return folder_data.get('title', f'Folder_{folder_id}')
        return f'Folder_{folder_id}'
    except Exception:
        return f'Folder_{folder_id}'

async def get_chat_name_by_id(client, chat_id):
    """Получает название чата по его ID"""
    try:
        chat = await client.get_entity(chat_id)
        if hasattr(chat, 'title') and chat.title:
            return chat.title
        elif hasattr(chat, 'username') and chat.username:
            return f"@{chat.username}"
        elif hasattr(chat, 'first_name') and chat.first_name:
            return chat.first_name
        else:
            return f'Chat_{chat_id}'
    except Exception:
        return f'Chat_{chat_id}'
def calculate_text_length_with_buttons(text: str) -> int:
    """Подсчитывает общую длину текста с учетом кнопок START и Вернуться"""
    # Примерная длина кнопок (START + Вернуться + разметка)
    buttons_length = len("START") + len("Вернуться") + 50  # +50 для разметки клавиатуры
    return len(text) + buttons_length

def truncate_chat_names_dynamically(chat_names: list, max_total_length: int, current_text_length: int) -> list:
    """Динамически сокращает названия чатов для умещения в лимит"""
    if not chat_names:
        return chat_names
    
    # Вычисляем доступную длину для всех названий чатов
    available_length = max_total_length - current_text_length
    
    # Если текущая длина уже превышает лимит, сокращаем все названия до минимума
    if current_text_length >= max_total_length:
        return [name[:10] + "..." if len(name) > 10 else name for name in chat_names]
    
    # Подсчитываем текущую длину всех названий чатов
    current_chat_names_length = sum(len(name) for name in chat_names)
    
    # Если названия чатов уже помещаются, возвращаем как есть
    if current_chat_names_length <= available_length:
        return chat_names
    
    # Вычисляем коэффициент сокращения
    truncation_ratio = available_length / current_chat_names_length
    
    # Сокращаем каждое название пропорционально
    truncated_names = []
    for name in chat_names:
        target_length = int(len(name) * truncation_ratio)
        # Минимальная длина - 10 символов
        target_length = max(10, target_length)
        if len(name) > target_length:
            truncated_names.append(name[:target_length-3] + "...")
        else:
            truncated_names.append(name)
    
    return truncated_names

async def generate_final_settings_text(user_id):
    """Генерирует итоговый текст настроек для отображения перед запуском рассылки"""
    if user_id not in mailing_states:
        return "Ошибка: состояние рассылки не найдено."
    
    state = mailing_states[user_id]
    # Восстановление недостающих полей состояния из mailing_parameters.json (после рестартов)
    try:
        persisted = load_mailing_parameters(user_id)
        mp = persisted.get("mailing_parameters", {}) if isinstance(persisted, dict) else {}
        if mp:
            # Список ключей, критичных для вывода итогов
            keys_to_restore = [
                "template_mode",
                "template_index",
                "template_type",
                "alternate_templates",
                "account_templates",
                "selected_folder",
                "folder_set",
                "account_folders",
                "ignore_folders",
                "ignore_chats",
                "logging_enabled",
                "selected_accounts",
            ]
            for k in keys_to_restore:
                # Жёстко синхронизируем критичные поля с persisted, если там есть значение
                if k in mp:
                    persisted_value = mp.get(k)
                    if persisted_value not in (None, {}, []):
                        state[k] = persisted_value
    except Exception:
        pass
    text_parts = [
        "📌     📌     📌     📌     📌     📌     📌",
        "",
        "          🧾 Итоговые настройки",
        "",
        ""
    ]
    
    # Выбранные аккаунты
    selected_accounts = state.get("selected_accounts", [])
    if selected_accounts:
        text_parts.append("-Выбранные аккаунты:")
        accounts = load_user_accounts(user_id)
        for phone in selected_accounts:
            account = next((acc for acc in accounts if acc.get('phone') == phone), None)
            nickname = (account.get('username') or account.get('name') or account.get('phone')) if account else phone
            nickname_display = f"@{str(nickname).lstrip('@')}"
            text_parts.append(nickname_display)
        text_parts.append("")
    
    # Режим работы
    text_parts.append("-Режим работы:")
    template_mode = state.get("template_mode")
    if template_mode == "custom":
        text_parts.append("Ручная настройка")
    elif template_mode == "select":
        text_parts.append("Автоматическая настройка")
    else:
        text_parts.append("Автоматическая настройка")
    text_parts.append("")
    
    # Чередование шаблонов
    text_parts.append("-Чередование шаблонов:")
    alternate_templates = state.get("alternate_templates", True)
    text_parts.append("Да" if alternate_templates else "Нет")
    text_parts.append("")
    
    # Текстовое сообщение для каждого аккаунта
    account_templates = state.get("account_templates", {})
    if account_templates:
        # Ручная настройка - показываем индивидуальные шаблоны
        text_parts.append("-Текстовое сообщение:")
        accounts = load_user_accounts(user_id)
        for phone in selected_accounts:
            account = next((acc for acc in accounts if acc.get('phone') == phone), None)
            if account:
                nickname = account.get('username') or account.get('name') or account.get('phone')
                template_choice = account_templates.get(phone)
                nickname_display = f"@{str(nickname).lstrip('@')}"
                if isinstance(template_choice, str) and template_choice.startswith("IDX_"):
                    try:
                        num = int(template_choice.replace('IDX_', '')) + 1
                    except ValueError:
                        num = 1
                    text_parts.append(f"{nickname_display}: Шаблон #{num}")
                else:
                    text_parts.append(f"{nickname_display}: {template_choice or 'Шаблон #1'}")
        text_parts.append("")
    else:
        # Автоматическая настройка — стартуем от выбранного пользователем шаблона
        # и инкрементируем по аккаунтам, оборачивая по количеству шаблонов КАЖДОГО аккаунта
        base_template_index = state.get("template_index")
        if base_template_index is None:
            base_template_index = 0  # по умолчанию первый шаблон
        text_parts.append("-Текстовое сообщение:")
        accounts = load_user_accounts(user_id)
        for idx, phone in enumerate(selected_accounts):
            account = next((acc for acc in accounts if acc.get('phone') == phone), None)
            if not account:
                continue
            nickname = account.get('username') or account.get('name') or account.get('phone')
            nickname_display = f"@{str(nickname).lstrip('@')}"
            try:
                template_list = get_templates_for_account(account)
                count_templates = max(1, len(template_list))
            except Exception:
                count_templates = 1
            # Глобальный счётчик = base + idx; локально оборачиваем по количеству шаблонов аккаунта
            template_num = ((base_template_index + idx) % count_templates) + 1
            text_parts.append(f"{nickname_display}: Шаблон #{template_num}")
        text_parts.append("")
    
    # Папка для каждого аккаунта
    account_folders = state.get("account_folders", {})
    if account_folders:
        # Ручная настройка - показываем индивидуальные папки
        text_parts.append("-Выбранная папка:")
        accounts = load_user_accounts(user_id)
        for phone in selected_accounts:
            account = next((acc for acc in accounts if acc.get('phone') == phone), None)
            if account:
                nickname = account.get('username') or account.get('name') or account.get('phone')
                folder_choice = account_folders.get(phone, "F1")
                nickname_display = f"@{str(nickname).lstrip('@')}"
                # Красивое отображение IDX_n как F{n+1}
                if isinstance(folder_choice, str) and folder_choice.startswith("IDX_"):
                    try:
                        n = int(folder_choice.replace("IDX_", ""))
                        # Если есть сохранённое название папки — показываем его
                        title_map = state.get("account_folder_titles", {})
                        folder_choice_display = title_map.get(phone)
                        if not folder_choice_display:
                            folder_choice_display = f"F{n+1}"
                    except ValueError:
                        folder_choice_display = "F1"
                else:
                    folder_choice_display = folder_choice
                text_parts.append(f"{nickname_display}: {folder_choice_display}")
        text_parts.append("")
    else:
        # Автоматическая настройка - показываем чередующиеся папки для каждого аккаунта
        folder_set = state.get("folder_set")
        if folder_set:
            text_parts.append("-Выбранная папка:")
            accounts_all = load_user_accounts(user_id)
            # Получаем список реальных папок через первый выбранный аккаунт
            folder_titles = []
            try:
                base_phone = selected_accounts[0] if selected_accounts else None
                base_account = next((acc for acc in accounts_all if acc.get('phone') == base_phone), None) if base_phone else None
                if base_account:
                    license_type = detect_license_type(user_id)
                    user_dir = get_user_dir(user_id, license_type)
                    config_path = os.path.join(user_dir, "config.json")
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                    api_id = config.get("api_id")
                    api_hash = config.get("api_hash")
                    session_name = base_account.get("name") or base_account.get("phone")
                    client = await get_or_create_client(user_id, session_name, api_id, api_hash, license_type)
                    folders_map = await list_folders(client) if client else {}
                    # folders_map: {1: {id, title}, 2: {...}, ...}
                    if folders_map:
                        # Сохраним порядок
                        for i in range(1, len(folders_map) + 1):
                            title = folders_map.get(i, {}).get('title')
                            if title:
                                folder_titles.append(title)
            except Exception:
                folder_titles = []

            for idx, phone in enumerate(selected_accounts):
                account = next((acc for acc in accounts_all if acc.get('phone') == phone), None)
                if account:
                    nickname = account.get('username') or account.get('name') or account.get('phone')
                    nickname_display = f"@{str(nickname).lstrip('@')}"
                    # Определяем смещение папки согласно выбору F1-F5
                    folder_offset = int(folder_set[1]) - 1  # F1=0, F2=1, F3=2, F4=3, F5=4
                    # Вычисляем индекс папки для текущего аккаунта
                    folder_index = idx + folder_offset
                    # Пытаемся отобразить реальное имя папки
                    if folder_titles:
                        real_title = folder_titles[folder_index % len(folder_titles)]
                        text_parts.append(f"{nickname_display}: {real_title}")
                    else:
                        text_parts.append(f"{nickname_display}: F{(folder_index % 5) + 1}")
            text_parts.append("")
        else:
            # Если нет индивидуальных папок, показываем общую
            selected_folder = state.get("selected_folder")
            if selected_folder:
                text_parts.append("-Выбранная папка:")
                accounts = load_user_accounts(user_id)
                phone = selected_accounts[0] if selected_accounts else None
                account = next((acc for acc in accounts if acc.get('phone') == phone), None) if phone else None
                nickname = (account.get('username') or account.get('name') or account.get('phone')) if account else ""
                nickname_display = f"@{str(nickname).lstrip('@')}" if nickname else ""
                text_parts.append(f"{nickname_display}: F{selected_folder}")
                text_parts.append("")
            else:
                # Фолбэк: если ни folder_set, ни selected_folder не заданы, используем folder_set_idx или F1
                base_index = state.get("folder_set_idx") if isinstance(state.get("folder_set_idx"), int) else 0
                # Попробуем получить реальные названия папок
                accounts_all = load_user_accounts(user_id)
                folder_titles = []
                try:
                    base_phone = selected_accounts[0] if selected_accounts else None
                    base_account = next((acc for acc in accounts_all if acc.get('phone') == base_phone), None) if base_phone else None
                    if base_account:
                        license_type = detect_license_type(user_id)
                        user_dir = get_user_dir(user_id, license_type)
                        config_path = os.path.join(user_dir, "config.json")
                        with open(config_path, "r", encoding="utf-8") as f:
                            config = json.load(f)
                        api_id = config.get("api_id")
                        api_hash = config.get("api_hash")
                        session_name = base_account.get("name") or base_account.get("phone")
                        client = await get_or_create_client(user_id, session_name, api_id, api_hash, license_type)
                        folders_map = await list_folders(client) if client else {}
                        if folders_map:
                            for i in range(1, len(folders_map) + 1):
                                title = folders_map.get(i, {}).get('title')
                                if title:
                                    folder_titles.append(title)
                except Exception:
                    folder_titles = []
                text_parts.append("-Выбранная папка:")
                accounts = accounts_all
                for idx, phone in enumerate(selected_accounts):
                    account = next((acc for acc in accounts if acc.get('phone') == phone), None)
                    if account:
                        nickname = account.get('username') or account.get('name') or account.get('phone')
                        nickname_display = f"@{str(nickname).lstrip('@')}"
                        folder_index = base_index + idx
                        if folder_titles:
                            real_title = folder_titles[folder_index % len(folder_titles)]
                            text_parts.append(f"{nickname_display}: {real_title}")
                        else:
                            text_parts.append(f"{nickname_display}: F{folder_index + 1}")
                text_parts.append("")
    
    # Логирование статусов сообщений
    logging_enabled = state.get("logging_enabled", True)
    text_parts.append("-Логирование статусов сообщений:")
    text_parts.append("Да" if logging_enabled else "Нет")
    text_parts.append("")
    
    # Игнорировать рассылку в папках
    ignore_folders = state.get("ignore_folders", {})
    has_ignore_folders = False
    if ignore_folders:
        for account_phone, folder_ids in ignore_folders.items():
            if folder_ids:
                has_ignore_folders = True
                break
    
    text_parts.append("-Игнорировать рассылку в папках:")
    if has_ignore_folders:
        for account_phone, folder_ids in ignore_folders.items():
            if folder_ids:
                accounts = load_user_accounts(user_id)
                account = next((acc for acc in accounts if acc.get('phone') == account_phone), None)
                if account:
                    nickname = (f"@{account['username']}" if account.get('username') else (account.get('name') or account.get('phone')))
                    # Получаем клиент для аккаунта
                    license_type = detect_license_type(user_id)
                    user_dir = get_user_dir(user_id, license_type)
                    config_path = os.path.join(user_dir, "config.json")
                    folder_names = []
                    try:
                        with open(config_path, "r", encoding="utf-8") as f:
                            config = json.load(f)
                        api_id = config.get("api_id")
                        api_hash = config.get("api_hash")
                        session_name = account.get('name') or account.get('phone')
                        client = await get_or_create_client(user_id, session_name, api_id, api_hash, license_type)
                        
                        if client:
                            for folder_id in folder_ids:
                                folder_name = await get_folder_name_by_id(client, folder_id)
                                folder_names.append(folder_name)
                        else:
                            # Если не удалось получить клиент, используем ID
                            for folder_id in folder_ids:
                                folder_names.append(f"Folder_{folder_id}")
                    except Exception:
                        # В случае ошибки используем ID
                        for folder_id in folder_ids:
                            folder_names.append(f"Folder_{folder_id}")
                    
                    # Объединяем все папки в одну строку через запятую
                    folder_list = ", ".join(folder_names)
                    text_parts.append(f"{nickname}: {folder_list}")
    else:
        text_parts.append("Нет")
    text_parts.append("")
    
    # Игнорировать рассылку в чатах
    ignore_chats = state.get("ignore_chats", {})
    has_ignore_chats = False
    if ignore_chats:
        for account_phone, folders in ignore_chats.items():
            for folder_id, chat_ids in folders.items():
                if chat_ids:
                    has_ignore_chats = True
                    break
            if has_ignore_chats:
                break
    
    text_parts.append("-Игнорировать рассылку в чатах:")
    if has_ignore_chats:
        # Сначала собираем все названия чатов без сокращения
        all_chat_names = []
        account_chat_mapping = {}  # {nickname: [chat_names]}
        
        for account_phone, folders in ignore_chats.items():
            accounts = load_user_accounts(user_id)
            account = next((acc for acc in accounts if acc.get('phone') == account_phone), None)
            if account:
                nickname = (f"@{account['username']}" if account.get('username') else (account.get('name') or account.get('phone')))
                # Получаем клиент для аккаунта
                license_type = detect_license_type(user_id)
                user_dir = get_user_dir(user_id, license_type)
                config_path = os.path.join(user_dir, "config.json")
                chat_names = []
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        config = json.load(f)
                    api_id = config.get("api_id")
                    api_hash = config.get("api_hash")
                    session_name = account.get('name') or account.get('phone')
                    client = await get_or_create_client(user_id, session_name, api_id, api_hash, license_type)
                    
                    if client:
                        for folder_id, chat_ids in folders.items():
                            if chat_ids:
                                for chat_id in chat_ids:
                                    chat_name = await get_chat_name_by_id(client, chat_id)
                                    chat_names.append(chat_name)
                    else:
                        # Если не удалось получить клиент, используем ID
                        for folder_id, chat_ids in folders.items():
                            if chat_ids:
                                for chat_id in chat_ids:
                                    chat_names.append(f"Chat_{chat_id}")
                except Exception:
                    # В случае ошибки используем ID
                    for folder_id, chat_ids in folders.items():
                        if chat_ids:
                            for chat_id in chat_ids:
                                chat_names.append(f"Chat_{chat_id}")
                
                if chat_names:
                    account_chat_mapping[nickname] = chat_names
                    all_chat_names.extend(chat_names)
        
        # Проверяем общую длину текста с кнопками
        current_text = "\n".join(text_parts)
        current_length = calculate_text_length_with_buttons(current_text)
        
        # Если превышает лимит, применяем динамическое сокращение
        MAX_LENGTH = 4096
        if current_length > MAX_LENGTH:
            # Сокращаем названия чатов динамически
            truncated_chat_names = truncate_chat_names_dynamically(all_chat_names, MAX_LENGTH, current_length)
            
            # Распределяем сокращенные названия обратно по аккаунтам
            truncated_index = 0
            for nickname, original_chat_names in account_chat_mapping.items():
                truncated_for_account = truncated_chat_names[truncated_index:truncated_index + len(original_chat_names)]
                truncated_index += len(original_chat_names)
                
                text_parts.append(f"{nickname}:")
                for chat_name in truncated_for_account:
                    text_parts.append(chat_name)
        else:
            # Если помещается, используем оригинальные названия с базовым сокращением
            for nickname, chat_names in account_chat_mapping.items():
                text_parts.append(f"{nickname}:")
                for chat_name in chat_names:
                    # Базовое сокращение до 20 символов
                    if isinstance(chat_name, str) and len(chat_name) > 20:
                        chat_name_display = chat_name[:20] + "..."
                    else:
                        chat_name_display = chat_name
                    text_parts.append(chat_name_display)
    else:
        text_parts.append("Нет")
    text_parts.append("")
    
    # Добавляем скрепочки в конце
    # Гарантируем пустую строку перед финальными скрепками
    if len(text_parts) > 0 and text_parts[-1] != "":
        text_parts.append("")
    text_parts.append("📌     📌     📌     📌     📌     📌     📌")
    
    return "\n".join(text_parts)


def generate_summary_text(user_id=None):
    """Генерирует текст сводки состояния рассылки"""
    try:
        state = load_resume_state(user_id=user_id)
        if not state or "accounts" not in state:
            return "Статус предыдущего запуска не определён."
        now = int(time.time())
        # Построим карту phone -> username из конфига, чтобы дополнить отсутствие username в resume_state
        phone_to_username = {}
        try:
            cfg = load_config(user_id)
            for acc_cfg in (cfg.get('accounts') or []):
                phone_val = acc_cfg.get('phone')
                uname_val = acc_cfg.get('username')
                if phone_val and uname_val:
                    # Сохраняем username без '@'
                    phone_to_username[phone_val] = uname_val[1:] if isinstance(uname_val, str) and uname_val.startswith('@') else uname_val
        except Exception:
            pass
        def _name_as_username(acc):
            uname = acc.get('username')
            if not uname and acc.get('phone') in phone_to_username:
                uname = phone_to_username.get(acc.get('phone'))
            if isinstance(uname, str) and uname.strip():
                uname = uname[1:] if uname.startswith('@') else uname
                return f"@{uname}"
            # Если username отсутствует — показываем телефон БЕЗ '@'
            phone = acc.get('phone', '') or ''
            return phone
        limits_list = [
            f"{_name_as_username(acc)} - {acc.get('message_count', 0)}/30"
            for acc in state["accounts"]
            if (not acc.get("break_until_timestamp")) and acc.get("message_count", 0) < 30
        ]
        breaks_list = [
            f"{_name_as_username(acc)} - {(acc['break_until_timestamp'] - now) // 3600:02d} {(acc['break_until_timestamp'] - now) % 3600 // 60:02d} {(acc['break_until_timestamp'] - now) % 60:02d}"
            for acc in state["accounts"]
            if acc.get("break_until_timestamp") and acc["break_until_timestamp"] > now
        ]
        summary_parts = []
        if limits_list and breaks_list:
            summary_parts.append("LIMITS:")
            summary_parts.append("")
            summary_parts.extend(limits_list)
            summary_parts.append("")
            summary_parts.append("")
            summary_parts.append("")
            summary_parts.append("BREAKS:")
            summary_parts.append("")
            summary_parts.extend(breaks_list)
        elif limits_list:
            summary_parts.append("LIMITS:")
            summary_parts.append("")
            summary_parts.extend(limits_list)
        elif breaks_list:
            summary_parts.append("BREAKS:")
            summary_parts.append("")
            summary_parts.extend(breaks_list)
        else:
            return "Нет активных процессов рассылки."
        return "\n".join(summary_parts)
    except Exception as e:
        return f"Ошибка при генерации сводки: {str(e)}"

    
# Визуальное отображение таймеров пауз
def print_timers(timers_dict):
    """Обновление таймеров в виде отдельных строк"""




# Визуальное отображение таймера перерывов между сессиями
async def countdown_timer(seconds, nickname, timers, selected_account=None, user_id=None, break_started_ts=None):
    """Таймер обратного отсчета с отображением в виде списка"""
    try:
        original_seconds = seconds  # Сохраняем изначальное время перерыва
        # Используем реальное время начала перерыва, если известно (сохранено в состоянии)
        if isinstance(break_started_ts, int) and break_started_ts > 0:
            start_time = break_started_ts
        else:
            start_time = int(asyncio.get_event_loop().time())
        # Устанавливаем базовую точку для часового логирования по уже прошедшим часам
        # При восстановлении после перезапуска не отправляем уведомления за уже прошедшие часы
        # Логирование происходит строго каждый час (3600+ секунд), а не при любом изменении elapsed_hours
        current_time = int(asyncio.get_event_loop().time())
        elapsed_time = current_time - start_time
        # Устанавливаем last_hour_logged в предыдущий час, чтобы следующий лог пришел через час
        last_hour_logged = (elapsed_time // 3600) - 1
        
        while seconds:
            mins, secs = divmod(seconds, 60)
            hours, mins = divmod(mins, 60)
            timer = f"{hours:02d}:{mins:02d}:{secs:02d}"
            timers[nickname] = timer  # Обновляем таймер для текущего аккаунта
            # Убираем отображение таймеров в консоли
            # print_timers(timers)  # Отображаем все таймеры
            
            # --- Логируем оставшееся время каждый час в Telegram ---
            current_time = int(asyncio.get_event_loop().time())
            elapsed_time = current_time - start_time
            elapsed_hours = elapsed_time // 3600
            
            # Отправляем уведомление только если прошёл полноценный новый час (3600+ секунд) с момента старта
            if user_id and elapsed_time >= 3600 and elapsed_hours > last_hour_logged:
                # Используем точное оставшееся время для уведомлений
                hh = f"{int(hours):02d}"
                mm = f"{int(mins):02d}"
                ss = f"{int(secs):02d}"
                # Получаем правильное отображение имени
                display_name = get_display_name(selected_account) if selected_account else nickname
                message = f"{display_name}: до конца перерыва осталось {hh}:{mm}:{ss} 🟡"
                
                
                # Отправляем в Telegram
                await log_to_telegram(user_id, message, "mailing")
                
                last_hour_logged = elapsed_hours
            
            # --- Сохраняем только оставшиеся секунды каждую секунду ---
            if selected_account:
                update_account_resume_state(
                    selected_account['phone'],
                    break_seconds_left=seconds,
                    break_started_ts=start_time,
                    user_id=user_id
                )
            await asyncio.sleep(1)
            seconds -= 1
        timers.pop(nickname, None)  # Удаляем таймер после завершения
        # Убираем отображение таймеров в консоли
        # print_timers(timers)  # Обновляем отображение таймеров
        # --- После окончания перерыва очищаем поля ---
        if selected_account:
            update_account_resume_state(
                selected_account['phone'],
                break_seconds_left=0,
                break_until_timestamp=0,
                user_id=user_id
            )
    except asyncio.CancelledError:
        # Задача была отменена (например, нажата кнопка Стоп)
        print(f"🛑 Таймер перерыва для {nickname} был остановлен")
        timers.pop(nickname, None)  # Удаляем таймер при отмене
        # Очищаем состояние перерыва при отмене
        if selected_account:
            update_account_resume_state(
                selected_account['phone'],
                break_seconds_left=0,
                break_until_timestamp=0,
                user_id=user_id
            )
        raise  # Пробрасываем исключение дальше


        
async def select_accounts(available_accounts):
    accounts_with_nicknames = await get_active_sessions_with_nicknames(available_accounts)
    while True:
        print_separator()
        print("Выберите аккаунт(ы):")
        for i, acc in enumerate(available_accounts, 1):
            nickname = acc.get('nickname', 'Не авторизовано')
            print(print_in_white(f"{i}. {nickname}"))
        print("0. Выход")
        choice = input("Выберите аккаунты: ").strip()
        if choice == "0" or choice.lower() == "exit":
            return []

        try:
            selected_indices = []
            for part in choice.split(","):
                part = part.strip()
                if "-" in part:  # Если это диапазон
                    start, end = map(int, part.split("-"))
                    if start > end:
                        print("Начало диапазона не может быть больше конца.")
                        break
                    selected_indices.extend(range(start, end + 1))
                else:  # Если это одиночное число
                    selected_indices.append(int(part))

            # Проверяем, что все выбранные индексы корректны
            if all(1 <= idx <= len(available_accounts) for idx in selected_indices):
                return [available_accounts[idx - 1] for idx in selected_indices]
            else:
                print("Один или несколько номеров аккаунтов неверны.")
        except ValueError:
            print("Пожалуйста, введите числа, разделённые запятыми, или диапазоны через дефис.")


async def select_template(selected_account):
    """Меню выбора шаблона сообщения"""
    while True:
        print(f"\nВыберите текстовое сообщение для аккаунта {selected_account['nickname']}:")
        print("1. Ru")
        print("2. Eng")

        choice = input("Введите номер сообщения: ").strip()
        if choice == "1":
            return selected_account["template1"]
        if choice == "2":
            return selected_account["template2"]
        print("Неверный выбор. Пожалуйста, введите 1 или 2")

async def list_folders(client):
    """Получение списка ID папок"""
    # --- Проверка и восстановление подключения ---
    if not client.is_connected() or not await client.is_user_authorized():
        print("Переподключение к Telegram...")
        try:
            if client.is_connected():
                await client.disconnect()
            await asyncio.sleep(5)
            await client.connect()
            
            if not await client.is_user_authorized():
                print(print_in_red("Не удалось переподключиться к Telegram. Ожидание..."))
                await asyncio.sleep(10)
                return {}
        except Exception as e:
            print(f"Ошибка переподключения: {e}. Ожидание...")
            await asyncio.sleep(10)
            return {}
    # --- Конец вставки ---
    try:
        result = await client(functions.messages.GetDialogFiltersRequest())
        folders = result.filters
    except Exception as e:
        # Если по какой-то причине не удалось получить папки, возвращаем пустой список, чтобы UI показал понятную обратную связь
        print(f"Ошибка получения папок: {e}")
        return {}

    folder_dict = {}
    valid_folders = []

    # Собираем только папки с непустым заголовком, корректно приводя title к строке
    for folder in folders:
        raw_title = getattr(folder, 'title', None)
        title_str = ""
        if isinstance(raw_title, str):
            title_str = raw_title.strip()
        elif hasattr(raw_title, 'text'):
            # На некоторых версиях клиентов title приходит как объект с полем text
            title_str = getattr(raw_title, 'text', '')
            title_str = title_str.strip() if isinstance(title_str, str) else ''
        elif raw_title is not None:
            title_str = str(raw_title).strip()

        if title_str:
            folder_id = getattr(folder, 'id', 'default')
            valid_folders.append((folder_id, title_str))

    # Сохраняем порядок, в котором вернул API (без дополнительной сортировки)
    for idx, (fid, title) in enumerate(valid_folders, 1):
        folder_dict[idx] = { 'id': fid, 'title': title }

    return folder_dict

async def get_active_sessions_with_nicknames(accounts):
    for account in accounts:
        # Используем только поле name для имени сессии
        session_name = account.get('name') or account.get('phone')
        session_file = os.path.join(sessions_dir, f"{session_name}.session")
        if os.path.exists(session_file):
            client = TelegramClient(session_file, account['api_id'], account['api_hash'])
            # --- Проверка и восстановление подключения ---
            if not client.is_connected() or not await client.is_user_authorized():
                try:
                    if client.is_connected():
                        await client.disconnect()
                    await asyncio.sleep(5)
                    await client.connect()
                    
                    if not await client.is_user_authorized():
                        print(f"Не удалось переподключить клиент {session_name}. Пропускаем...")
                        continue
                except Exception as e:
                    print(f"Ошибка переподключения клиента {session_name}: {e}. Пропускаем...")
                    continue
            # --- Конец вставки ---
            await client.connect()
            if await client.is_user_authorized():
                me = await client.get_me()
                account['nickname'] = (f"@{me.username}" if getattr(me, 'username', None) else (me.first_name or me.phone))
                account['last_login'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            await client.disconnect()
    return accounts
async def authenticate_client(selected_account):
    api_id = selected_account["api_id"]
    api_hash = selected_account["api_hash"]
    phone = selected_account["phone"]

    # Используем только поле name для имени сессии
    session_name = selected_account.get('name') or selected_account.get('phone')
    session_file = os.path.join(sessions_dir, f"{session_name}.session")
    # Создаем клиент с улучшенными настройками
    client = TelegramClient(
        session_file, 
        api_id, 
        api_hash,
        # Добавляем настройки для улучшения стабильности
        connection_retries=3,
        retry_delay=1,
        timeout=30,
        # Отключаем автоматическое переподключение для ручного управления
        auto_reconnect=False
    )

    max_attempts = 3
    attempt = 0
    
    while attempt < max_attempts:
        try:
            await client.connect()
            if not await client.is_user_authorized():
                try:
                    await client.send_code_request(phone)
                    code = input("Введите код подтверждения: ")
                    await client.sign_in(phone, code)
                    me = await client.get_me()
                    selected_account['nickname'] = (f"@{me.username}" if getattr(me, 'username', None) else (me.first_name or me.phone))
                    selected_account['last_login'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                except SessionPasswordNeededError:
                    # Обработка 2FA
                    password = input("Введите пароль 2FA: ").strip()
                    try:
                        await client.sign_in(password=password)
                        me = await client.get_me()
                        selected_account['nickname'] = (f"@{me.username}" if getattr(me, 'username', None) else (me.first_name or me.phone))
                        selected_account['last_login'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    except PasswordHashInvalidError:
                        print(f"❌ Неверный пароль 2FA для {phone}")
                        await client.disconnect()
                        return None
                except AuthRestartError:
                    print(f"🔄 Перезапуск авторизации для {phone}")
                    await client.disconnect()
                    await asyncio.sleep(2)
                    attempt += 1
                    continue
                except Exception as e:
                    error_msg = str(e).lower()
                    if "api_id/api_hash combination is invalid" in error_msg:
                        print(f"❌ Неверные API данные для {phone}")
                    elif "auth_key" in error_msg or "nonce" in error_msg:
                        # Игнорируем ошибки auth_key - они не критичны
                        print(f"⚠️  Временная ошибка авторизации для {phone}, повтор...")
                        await asyncio.sleep(2)
                        attempt += 1
                        continue
                    else:
                        print(f"❌ Ошибка авторизации для {phone}: {e}")
                    
                    await client.disconnect()
                    await asyncio.sleep(2)
                    attempt += 1
                    continue
            else:
                me = await client.get_me()
                selected_account['nickname'] = (f"@{me.username}" if getattr(me, 'username', None) else (me.first_name or me.phone))
                selected_account['last_login'] = datetime.now().strftime("%Y-%м-%д %H:%M:%S")
            return client
        except OSError as e:
            if "Cannot allocate memory" in str(e):
                print(f"❌ Критическая ошибка памяти для {phone}: {e}")
                return None
            else:
                print(f"⚠️  Сетевая ошибка для {phone}: {e}, повтор через 2 секунды...")
                await asyncio.sleep(2)
                attempt += 1
                
        except Exception as e:
            error_msg = str(e).lower()
            if "auth_key" in error_msg or "nonce" in error_msg:
                # Игнорируем ошибки auth_key
                print(f"⚠️  Временная ошибка ключа для {phone}, повтор...")
                await asyncio.sleep(2)
                attempt += 1
                continue
            else:
                print(f"❌ Неожиданная ошибка для {phone}: {e}")
                await asyncio.sleep(2)
                attempt += 1
    
    # Все попытки исчерпаны
    print(f"❌ Не удалось авторизовать {phone} после {max_attempts} попыток")
    return None






async def select_folder(folder_dict):
    """Меню выбора папки"""
    while True:
        for idx, folder in folder_dict.items():
            print(f"{idx}. {folder['title']}")

        choice = input("Введите номер папки: ").strip()
        try:
            choice = int(choice)
            if 1 <= choice <= len(folder_dict):
                return folder_dict[choice]
            else:
                print(f"Неверный номер папки: {choice}")
        except ValueError:
            print("Пожалуйста, введите число.")

async def get_chats_in_folder(client, folder_id, logging_enabled=True):
    """Получение списка чатов в папке"""
    # --- Проверка и восстановление подключения ---
    if not client.is_connected() or not await client.is_user_authorized():
        print("Переподключение к Telegram...")
        try:
            if client.is_connected():
                await client.disconnect()
            await asyncio.sleep(5)
            await client.connect()
            
            if not await client.is_user_authorized():
                print(print_in_red("Не удалось переподключиться к Telegram. Ожидание..."))
                await asyncio.sleep(10)
                return []
        except Exception as e:
            print(f"Ошибка переподключения: {e}. Ожидание...")
            await asyncio.sleep(10)
            return []
    # --- Конец вставки ---
    # Обновляем кэш сущностей перед получением чатов
    await client.get_dialogs()

    result = await client(functions.messages.GetDialogFiltersRequest())
    folders = result.filters
    peer_ids = []

    for folder in folders:
        if isinstance(folder, DialogFilter) and folder.id == folder_id:
            for peer in folder.include_peers:
                if hasattr(peer, 'chat_id'):
                    peer_ids.append(peer.chat_id)
                elif hasattr(peer, 'channel_id'):
                    peer_ids.append(peer.channel_id)
                elif hasattr(peer, 'user_id'):
                    peer_ids.append(peer.user_id)

    chats = []
    if peer_ids:
        for peer_id in peer_ids:
            try:
                await client.get_input_entity(peer_id)
                chat = await client.get_entity(peer_id)
                # Добавляем все чаты, которые удалось получить
                chats.append(chat)
            except Exception as e:
                if logging_enabled:
                    print(f"Не удалось получить информацию о чате с ID {peer_id}: {e}")
    return chats

def save_ignore_settings(user_id, ignore_folders=None, ignore_chats=None, filename=None):
    """Сохранение настроек игнорирования в resume_process.json"""
    if filename is None:
        user_dir = get_user_dir(user_id, detect_license_type(user_id))
        filename = os.path.join(user_dir, "resume_process.json")
    
    # Загружаем существующие данные
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    else:
        data = {}
    
    # Обновляем настройки игнорирования
    if ignore_folders is not None:
        data["ignore_folders"] = ignore_folders
    if ignore_chats is not None:
        data["ignore_chats"] = ignore_chats
    
    # Сохраняем обратно
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_ignore_settings(user_id, filename=None):
    """Загрузка настроек игнорирования из resume_process.json"""
    if filename is None:
        user_dir = get_user_dir(user_id, detect_license_type(user_id))
        filename = os.path.join(user_dir, "resume_process.json")
    
    if not os.path.exists(filename):
        return {"ignore_folders": {}, "ignore_chats": {}}
    
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {
                "ignore_folders": data.get("ignore_folders", {}),
                "ignore_chats": data.get("ignore_chats", {})
            }
    except Exception:
        return {"ignore_folders": {}, "ignore_chats": {}}

def filter_folders_by_ignore(folders, ignore_folders, account_phone):
    """Фильтрация папок с учетом игнорируемых"""
    if not ignore_folders or account_phone not in ignore_folders:
        return folders
    
    ignored_folder_ids = ignore_folders[account_phone]
    filtered_folders = {}
    
    for idx, folder in folders.items():
        if folder['id'] not in ignored_folder_ids:
            filtered_folders[idx] = folder
    
    return filtered_folders

def filter_chats_by_ignore(chats, ignore_chats, account_phone, folder_id):
    """Фильтрация чатов с учетом игнорируемых"""
    if not ignore_chats or account_phone not in ignore_chats:
        return chats
    
    account_ignore_chats = ignore_chats[account_phone]
    if str(folder_id) not in account_ignore_chats:
        return chats
    
    ignored_chat_ids = account_ignore_chats[str(folder_id)]
    filtered_chats = []
    
    for chat in chats:
        if chat.id not in ignored_chat_ids:
            filtered_chats.append(chat)
    
    return filtered_chats

def _shorten(text: str, max_len: int = 250) -> str:
    if not isinstance(text, str):
        text = str(text)
    if max_len <= 3:
        return text[:max_len]
    return text if len(text) <= max_len else (text[: max_len - 1] + "…")

async def show_folder_selection_for_account(call, user_id, account_phone):
    """Показывает выбор папок для игнорирования для конкретного аккаунта"""
    try:
        # Получаем аккаунт
        accounts = load_user_accounts(user_id)
        account = None
        for acc in accounts:
            if acc.get('phone') == account_phone:
                account = acc
                break
        
        if not account:
            await call.answer("Аккаунт не найден.", show_alert=True)
            return
        
        # Подключаемся к аккаунту
        license_type = detect_license_type(user_id)
        user_dir = get_user_dir(user_id, license_type)
        config_path = os.path.join(user_dir, "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        api_id = config.get("api_id")
        api_hash = config.get("api_hash")
        
        session_name = account.get('name') or account.get('phone')
        client = await get_or_create_client(user_id, session_name, api_id, api_hash, license_type)
        
        if not client:
            await call.answer(f"Не удалось подключиться к аккаунту {session_name}.", show_alert=True)
            return
        
        # Получаем папки
        folders = await list_folders(client)
        if not folders:
            try:
                await call.answer(f"Нет доступных папок для {session_name}.", show_alert=True)
            except Exception:
                # Игнорируем ошибки с устаревшими callback
                pass
            return
        
        # Получаем текущие настройки игнорирования
        state = mailing_states.get(user_id, {})
        ignore_folders = state.get("ignore_folders", {})
        account_ignore_folders = ignore_folders.get(account_phone, [])
        
        # Создаем клавиатуру с папками
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        for folder in folders.values():
            mark = " ✅" if folder['id'] in account_ignore_folders else ""
            markup.inline_keyboard.append([InlineKeyboardButton(
                text=f"{folder['title']}{mark}", 
                callback_data=f"ignore_folder_{account_phone}_{folder['id']}"
            )])
        
        # Определяем индекс текущего аккаунта для условного отображения пустышек
        try:
            _st = mailing_states.get(user_id, {})
            _idx = int(_st.get("current_account_index", 0))
        except Exception:
            _idx = 0
        
        # Новые кнопки навигации по аккаунтам в одном ряду
        nav_row = []
        if _idx > 0:
            nav_row.append(InlineKeyboardButton(text="Пред. аккаунт ⬇️", callback_data=f"back_to_prev_folder_account_{account_phone}"))
        
        # Для первого аккаунта - полный текст, для остальных - сокращённый
        next_text = "Следующий аккаунт ⬆️" if _idx == 0 else "След. аккаунт ⬆️"
        nav_row.append(InlineKeyboardButton(text=next_text, callback_data=f"next_folder_account_{account_phone}"))
        
        if nav_row:
            markup.inline_keyboard.append(nav_row)
        
        # Кнопка "Далее" должна быть выше "Вернуться"
        markup.inline_keyboard.append([InlineKeyboardButton(text="Далее", callback_data="to_ignore_chats_question")])
        # Возврат к верхнему уровню (вопросу про игнор папок)
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="ignore_folders_back")])
        
        await delete_and_send_image(
            call.message,
            "mailing.png",
            f"Выберите папки для игнорирования в аккаунте {(('@' + account['username']) if account.get('username') else session_name)}:",
            reply_markup=markup,
            user_id=user_id
        )
        
    except Exception as e:
        try:
            await call.answer(f"Ошибка: {e}", show_alert=True)
        except Exception:
            # Игнорируем ошибки с устаревшими callback
            pass
async def update_folder_selection_keyboard(call, user_id, account_phone):
    """Обновляет только клавиатуру выбора папок с актуальными галочками"""
    try:
        print(f"🔧 DEBUG: update_folder_selection_keyboard вызвана для user_id={user_id}, account_phone={account_phone}")
        
        # Получаем аккаунт
        accounts = load_user_accounts(user_id)
        account = None
        for acc in accounts:
            if acc.get('phone') == account_phone:
                account = acc
                break
        
        if not account:
            print(f"❌ DEBUG: Аккаунт не найден для {account_phone}")
            return
        
        print(f"✅ DEBUG: Аккаунт найден: {account.get('name')}")
        
        # Подключаемся к аккаунту
        license_type = detect_license_type(user_id)
        user_dir = get_user_dir(user_id, license_type)
        config_path = os.path.join(user_dir, "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        api_id = config.get("api_id")
        api_hash = config.get("api_hash")
        
        session_name = account.get('name') or account.get('phone')
        client = await get_or_create_client(user_id, session_name, api_id, api_hash, license_type)
        
        if not client:
            print(f"❌ DEBUG: Не удалось создать клиент для {session_name}")
            return
        
        print(f"✅ DEBUG: Клиент создан для {session_name}")
        
        # Получаем папки
        folders = await list_folders(client)
        if not folders:
            print(f"❌ DEBUG: Нет доступных папок для {session_name}")
            return
        
        print(f"✅ DEBUG: Получено {len(folders)} папок")
        
        # Получаем текущие настройки игнорирования
        state = mailing_states.get(user_id, {})
        ignore_folders = state.get("ignore_folders", {})
        account_ignore_folders = ignore_folders.get(account_phone, [])
        
        print(f"🔧 DEBUG: Текущие игнорируемые папки для {account_phone}: {account_ignore_folders}")
        
        # Создаем клавиатуру с папками
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        for folder in folders.values():
            mark = " ✅" if folder['id'] in account_ignore_folders else ""
            print(f"🔧 DEBUG: Папка {folder['title']} (ID: {folder['id']}): {'✅' if folder['id'] in account_ignore_folders else '❌'}")
            markup.inline_keyboard.append([InlineKeyboardButton(
                text=f"{folder['title']}{mark}", 
                callback_data=f"ignore_folder_{account_phone}_{folder['id']}"
            )])
        
        # Определяем индекс текущего аккаунта для условного отображения пустышек
        try:
            _st = mailing_states.get(user_id, {})
            _idx = int(_st.get("current_account_index", 0))
        except Exception:
            _idx = 0
        
        # Новые кнопки навигации по аккаунтам в одном ряду
        nav_row = []
        if _idx > 0:
            nav_row.append(InlineKeyboardButton(text="Пред. аккаунт ⬇️", callback_data=f"back_to_prev_folder_account_{account_phone}"))
        
        # Для первого аккаунта - полный текст, для остальных - сокращённый
        next_text = "Следующий аккаунт ⬆️" if _idx == 0 else "След. аккаунт ⬆️"
        nav_row.append(InlineKeyboardButton(text=next_text, callback_data=f"next_folder_account_{account_phone}"))
        
        if nav_row:
            markup.inline_keyboard.append(nav_row)
        
        # Кнопка "Далее" должна быть выше "Вернуться"
        markup.inline_keyboard.append([InlineKeyboardButton(text="Далее", callback_data="to_ignore_chats_question")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="ignore_folders_back")])
        
        print(f"🔧 DEBUG: Создана клавиатура с {len(markup.inline_keyboard)} кнопками")
        
        # Обновляем только клавиатуру существующего сообщения
        try:
            await call.message.edit_reply_markup(reply_markup=markup)
            print(f"✅ DEBUG: Клавиатура успешно обновлена")
        except Exception as e:
            # Если не удалось обновить клавиатуру, показываем ошибку
            print(f"❌ DEBUG: Ошибка обновления клавиатуры: {e}")
            
    except Exception as e:
        print(f"❌ DEBUG: Ошибка обновления клавиатуры папок: {e}")
        import traceback
        traceback.print_exc()

async def update_chat_selection_keyboard(call, user_id, account_phone, folder_id):
    """Обновляет только клавиатуру выбора чатов с актуальными галочками"""
    try:
        # Получаем аккаунт
        accounts = load_user_accounts(user_id)
        account = None
        for acc in accounts:
            if acc.get('phone') == account_phone:
                account = acc
                break
        
        if not account:
            return
        
        # Подключаемся к аккаунту
        license_type = detect_license_type(user_id)
        user_dir = get_user_dir(user_id, license_type)
        config_path = os.path.join(user_dir, "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        api_id = config.get("api_id")
        api_hash = config.get("api_hash")
        
        session_name = account.get('name') or account.get('phone')
        client = await get_or_create_client(user_id, session_name, api_id, api_hash, license_type)
        
        if not client:
            return
        
        # Получаем чаты в папке
        chats = await get_chats_in_folder(client, folder_id)
        if not chats:
            return
        
        # Получаем текущие настройки игнорирования чатов и номер страницы
        state = mailing_states.get(user_id, {})
        ignore_chats = state.get("ignore_chats", {})
        account_ignore_chats = ignore_chats.get(account_phone, {})
        folder_ignore_chats = account_ignore_chats.get(str(folder_id), [])
        chat_pages = state.get("chat_pages", {})
        account_pages = chat_pages.get(account_phone, {})
        current_page = int(account_pages.get(str(folder_id), 0))
        page_size = 20
        start_index = current_page * page_size
        end_index = start_index + page_size
        
        # Определяем индекс текущего аккаунта для условного отображения текста кнопок
        try:
            _idx = int(state.get("current_account_index", 0))
        except Exception:
            _idx = 0
        
        # Создаем клавиатуру с чатами
        markup = InlineKeyboardMarkup(inline_keyboard=[]) 
        visible_chats = chats[start_index:end_index]
        for i, chat in enumerate(visible_chats, start=start_index + 1):  # Сквозная нумерация
            chat_title = getattr(chat, 'title', None) or getattr(chat, 'username', None) or str(chat.id)
            chat_title = _shorten(chat_title, 22)
            mark = " ✅" if chat.id in folder_ignore_chats else ""
            markup.inline_keyboard.append([InlineKeyboardButton(
                text=f"{i}. {chat_title}{mark}", 
                callback_data=f"ignore_chat_{account_phone}_{folder_id}_{chat.id}"
            )])
        
        nav_row = []
        if current_page > 0:
            # Если нет следующих страниц, показываем полный текст "Предыдущая страница"
            prev_text = "Предыдущая страница ⬅️" if end_index >= len(chats) else "Пред. страница ⬅️"
            nav_row.append(InlineKeyboardButton(text=prev_text, callback_data=f"more_chats_{account_phone}_{folder_id}_{current_page - 1}"))
        else:
            # Страница 1: показываем сокращённую кнопку возврата к выбору папки
            nav_row.append(InlineKeyboardButton(
                text="Пред. страница ⬅️",
                callback_data=f"back_to_chat_folders_{account_phone}"
            ))
        if end_index < len(chats):
            # На странице 1 всегда сокращённый текст, далее — по прежней логике
            next_page_text = "След. страница ➡️" if current_page == 0 else ("Следующая страница ➡️" if _idx == 0 else "След. страница ➡️")
            nav_row.append(InlineKeyboardButton(text=next_page_text, callback_data=f"more_chats_{account_phone}_{folder_id}_{current_page + 1}"))
        if nav_row:
            markup.inline_keyboard.append(nav_row)
        
        markup.inline_keyboard.append([InlineKeyboardButton(text="Далее", callback_data=f"next_chat_folder_{account_phone}_{folder_id}")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data=f"back_to_chat_folders_{account_phone}")])
        
        # Обновляем только клавиатуру существующего сообщения
        try:
            await call.message.edit_reply_markup(reply_markup=markup)
        except Exception as e:
            # Подавляем повторное обновление без изменений
            if "message is not modified" in str(e):
                pass
            else:
                print(f"Ошибка обновления клавиатуры чатов: {e}")
            
    except Exception as e:
        print(f"Ошибка обновления клавиатуры чатов: {e}")

async def update_mailing_accounts_keyboard(call, user_id, selected_accounts):
    """Обновляет только клавиатуру выбора аккаунтов для рассылки с актуальными галочками"""
    try:
        print(f"🔧 DEBUG: update_mailing_accounts_keyboard вызвана для user_id={user_id}, selected_accounts={selected_accounts}")
        
        # Получаем аккаунты
        accounts = load_user_accounts(user_id)
        
        # Создаем клавиатуру с аккаунтами
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        for acc in accounts:
            nickname = (f"@{acc['username']}" if acc.get('username') else (acc.get('name') or acc.get('phone')))
            mark = " ✅" if acc.get('phone') in selected_accounts else ""
            markup.inline_keyboard.append([InlineKeyboardButton(
                text=f"{nickname}{mark}", 
                callback_data=f"mailing_acc_{acc.get('phone')}"
            )])
        
        markup.inline_keyboard.append([InlineKeyboardButton(text="Выбрать все", callback_data="mailing_select_all")])
        
        # Кнопка "Далее" активна только если выбран хотя бы 1 аккаунт
        if selected_accounts:
            markup.inline_keyboard.append([InlineKeyboardButton(text="Далее ➡️", callback_data="mailing_next")])
        else:
            markup.inline_keyboard.append([InlineKeyboardButton(text="Далее ➡️", callback_data="mailing_next", disabled=True)])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="message_mailing")])
        
        print(f"🔧 DEBUG: Создана клавиатура с {len(markup.inline_keyboard)} кнопками")
        
        # Обновляем только клавиатуру существующего сообщения
        try:
            await call.message.edit_reply_markup(reply_markup=markup)
            print(f"✅ DEBUG: Клавиатура рассылки успешно обновлена")
        except Exception as e:
            print(f"❌ DEBUG: Ошибка обновления клавиатуры рассылки: {e}")
            
    except Exception as e:
        print(f"❌ DEBUG: Ошибка обновления клавиатуры рассылки: {e}")
        import traceback
        traceback.print_exc()

async def update_postman_accounts_keyboard(call, user_id, selected_accounts):
    """Обновляет только клавиатуру выбора аккаунтов для почты с актуальными галочками"""
    try:
        print(f"🔧 DEBUG: update_postman_accounts_keyboard вызвана для user_id={user_id}, selected_accounts={selected_accounts}")
        
        # Получаем аккаунты
        accounts = load_user_accounts(user_id)
        
        # Создаем клавиатуру с аккаунтами (точно как в первоначальном показе)
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        
        # Сначала добавляем все аккаунты
        for acc in accounts:
            label = (f"@{acc['username']}" if acc.get("username") else (acc.get("name") or acc.get("phone")))
            mark = " ✅" if acc.get("phone") in selected_accounts else ""
            label_fixed = f"{label: <5}"  # 5 — можно увеличить при необходимости
            markup.inline_keyboard.append([InlineKeyboardButton(text=f"{label_fixed}{mark}", callback_data=f"postman_acc_{acc.get('phone')}")])
        
        # Затем добавляем кнопку "Выбрать все" (после аккаунтов, как в первоначальном показе)
        all_selected = len(selected_accounts) == len(accounts)
        markup.inline_keyboard.append([InlineKeyboardButton(
            text="Выбрать все" if all_selected else "Выбрать все",
            callback_data="postman_select_all"
        )])
        
        # Затем кнопка "Далее" (точно как в первоначальном показе)
        markup.inline_keyboard.append([InlineKeyboardButton(text="Далее ➡️", callback_data="postman_next", disabled=not selected_accounts)])
        
        # И наконец кнопка "Вернуться" (точно как в первоначальном показе)
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="postman")])
        
        print(f"🔧 DEBUG: Создана клавиатура почты с {len(markup.inline_keyboard)} кнопками")
        
        # Обновляем только клавиатуру существующего сообщения
        try:
            await call.message.edit_reply_markup(reply_markup=markup)
            print(f"✅ DEBUG: Клавиатура почты успешно обновлена")
        except Exception as e:
            print(f"❌ DEBUG: Ошибка обновления клавиатуры почты: {e}")
            
    except Exception as e:
        print(f"❌ DEBUG: Ошибка обновления клавиатуры почты: {e}")
        import traceback
        traceback.print_exc()

async def update_autoresponder_accounts_keyboard(call, user_id, selected_accounts):
    """Обновляет только клавиатуру выбора аккаунтов для автоответчика с актуальными галочками"""
    try:
        print(f"🔧 DEBUG: update_autoresponder_accounts_keyboard вызвана для user_id={user_id}, selected_accounts={selected_accounts}")
        
        # Создаем клавиатуру с аккаунтами
        markup = get_autoresponder_accounts_menu(user_id, "activate")
        
        print(f"🔧 DEBUG: Создана клавиатура автоответчика с {len(markup.inline_keyboard)} кнопками")
        
        # Обновляем только клавиатуру существующего сообщения
        try:
            await call.message.edit_reply_markup(reply_markup=markup)
            print(f"✅ DEBUG: Клавиатура автоответчика успешно обновлена")
        except Exception as e:
            print(f"❌ DEBUG: Ошибка обновления клавиатуры автоответчика: {e}")
            
    except Exception as e:
        print(f"❌ DEBUG: Ошибка обновления клавиатуры автоответчика: {e}")
        import traceback
        traceback.print_exc()

async def show_folder_selection_for_chats(call, user_id, account_phone):
    """Показывает выбор папки для игнорирования чатов в ней"""
    try:
        # Получаем аккаунт
        accounts = load_user_accounts(user_id)
        account = None
        for acc in accounts:
            if acc.get('phone') == account_phone:
                account = acc
                break
        
        if not account:
            try:
                await call.answer("Аккаунт не найден.", show_alert=True)
            except Exception:
                # Игнорируем ошибки с устаревшими callback
                pass
            return
        
        # Подключаемся к аккаунту
        license_type = detect_license_type(user_id)
        user_dir = get_user_dir(user_id, license_type)
        config_path = os.path.join(user_dir, "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        api_id = config.get("api_id")
        api_hash = config.get("api_hash")
        
        session_name = account.get('name') or account.get('phone')
        client = await get_or_create_client(user_id, session_name, api_id, api_hash, license_type)
        
        if not client:
            try:
                await call.answer(f"Не удалось подключиться к аккаунту {session_name}.", show_alert=True)
            except Exception:
                # Игнорируем ошибки с устаревшими callback
                pass
            return
        
        # Получаем папки
        folders = await list_folders(client)
        if not folders:
            try:
                await call.answer(f"Нет доступных папок для {session_name}.", show_alert=True)
            except Exception:
                # Игнорируем ошибки с устаревшими callback
                pass
            return
        
        # Создаем клавиатуру с папками
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        for folder in folders.values():
            markup.inline_keyboard.append([InlineKeyboardButton(
                text=folder['title'], 
                callback_data=f"select_chat_folder_{account_phone}_{folder['id']}"
            )])
        
        # Определяем индекс текущего аккаунта для условного отображения пустышек
        try:
            _st = mailing_states.get(user_id, {})
            _idx = int(_st.get("current_account_index", 0))
        except Exception:
            _idx = 0
        
        # Новые кнопки навигации по аккаунтам в одном ряду
        nav_row = []
        if _idx > 0:
            nav_row.append(InlineKeyboardButton(text="Пред. аккаунт ⬇️", callback_data=f"back_to_prev_account_chats_{account_phone}"))
        
        # Для первого аккаунта - полный текст, для остальных - сокращённый
        next_text = "Следующий аккаунт ⬆️" if _idx == 0 else "След. аккаунт ⬆️"
        nav_row.append(InlineKeyboardButton(text=next_text, callback_data=f"next_chat_account_{account_phone}"))
        
        if nav_row:
            markup.inline_keyboard.append(nav_row)
        
        # Кнопка "Далее" должна быть выше "Вернуться"
        markup.inline_keyboard.append([InlineKeyboardButton(text="Далее", callback_data="to_final_settings")])
        # Возврат к верхнему уровню (вопросу про игнор чатов)
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="ignore_chats_back")])
        
        await delete_and_send_image(
            call.message,
            "mailing.png",
            f"Выберите папку в которой находятся чаты для игнорирования в аккаунте {(('@' + account['username']) if account.get('username') else session_name)}:",
            reply_markup=markup,
            user_id=user_id
        )
        
    except Exception as e:
        try:
            await call.answer(f"Ошибка: {e}", show_alert=True)
        except Exception:
            # Игнорируем ошибки с устаревшими callback
            pass

async def show_chat_selection_for_folder(call, user_id, account_phone, folder_id, existing_message=None):
    """Показывает выбор чатов для игнорирования в конкретной папке"""
    try:
        # Снимок токена загрузки на старт выполнения. Если по ходу он изменится — значит пользователь нажал Далее/Вернуться
        start_token = None
        try:
            start_token = int(mailing_states.get(user_id, {}).get("chat_load_token", 0))
        except Exception:
            start_token = 0
        # Получаем аккаунт
        accounts = load_user_accounts(user_id)
        account = None
        for acc in accounts:
            if acc.get('phone') == account_phone:
                account = acc
                break
        
        if not account:
            await call.answer("Аккаунт не найден.", show_alert=True)
            return
        
        # Подключаемся к аккаунту
        license_type = detect_license_type(user_id)
        user_dir = get_user_dir(user_id, license_type)
        config_path = os.path.join(user_dir, "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        api_id = config.get("api_id")
        api_hash = config.get("api_hash")
        
        session_name = account.get('name') or account.get('phone')
        client = await get_or_create_client(user_id, session_name, api_id, api_hash, license_type)
        
        if not client:
            await call.answer(f"Не удалось подключиться к аккаунту {session_name}.", show_alert=True)
            return
        
        # Сохраняем последнюю выбранную папку для этого аккаунта (для корректного возврата)
        try:
            state = mailing_states.get(user_id, {})
            if "last_folder_for_account" not in state:
                state["last_folder_for_account"] = {}
            state["last_folder_for_account"][account_phone] = str(folder_id)
            mailing_states[user_id] = state
            try:
                save_mailing_parameters(user_id)
            except Exception:
                pass
        except Exception:
            pass

        # Получаем чаты в папке
        chats = await get_chats_in_folder(client, folder_id)

        # Если за время загрузки пользователь нажал «Далее/Вернуться», отменяем вывод этого экрана
        try:
            current_token = int(mailing_states.get(user_id, {}).get("chat_load_token", 0))
        except Exception:
            current_token = start_token
        if current_token != start_token:
            # Не показываем устаревший экран
            return
        if not chats:
            try:
                await call.answer("Нет доступных чатов в этой папке.", show_alert=True)
            except Exception:
                # Игнорируем ошибки с устаревшими callback
                pass
            return
        
        # Получаем текущие настройки игнорирования чатов и номер страницы
        state = mailing_states.get(user_id, {})
        ignore_chats = state.get("ignore_chats", {})
        account_ignore_chats = ignore_chats.get(account_phone, {})
        # Всегда используем строковый ключ для folder_id
        folder_ignore_chats = account_ignore_chats.get(str(folder_id), [])
        if "chat_pages" not in state:
            state["chat_pages"] = {}
        if account_phone not in state["chat_pages"]:
            state["chat_pages"][account_phone] = {}
        current_page = int(state["chat_pages"][account_phone].get(str(folder_id), 0))
        page_size = 20
        start_index = current_page * page_size
        end_index = start_index + page_size
        
        # Определяем индекс текущего аккаунта для условного отображения текста кнопок
        try:
            _st = mailing_states.get(user_id, {})
            _idx = int(_st.get("current_account_index", 0))
        except Exception:
            _idx = 0
        
        # Создаем клавиатуру с чатами
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        visible_chats = chats[start_index:end_index]
        for i, chat in enumerate(visible_chats, start=start_index + 1):  # Сквозная нумерация
            chat_title = getattr(chat, 'title', None) or getattr(chat, 'username', None) or str(chat.id)
            chat_title = _shorten(chat_title, 22)
            mark = " ✅" if chat.id in folder_ignore_chats else ""
            markup.inline_keyboard.append([InlineKeyboardButton(
                text=f"{i}. {chat_title}{mark}", 
                callback_data=f"ignore_chat_{account_phone}_{folder_id}_{chat.id}"
            )])
        
        # Пагинация в одном ряду: слева "Пред. страница", справа "След. страница"
        nav_row = []
        if current_page > 0:
            # Если нет следующих страниц, показываем полный текст "Предыдущая страница"
            prev_text = "Предыдущая страница ⬅️" if end_index >= len(chats) else "Пред. страница ⬅️"
            nav_row.append(InlineKeyboardButton(
                text=prev_text,
                callback_data=f"more_chats_{account_phone}_{folder_id}_{current_page - 1}"
            ))
        else:
            # Страница 1: показываем сокращённую кнопку возврата к выбору папки
            nav_row.append(InlineKeyboardButton(
                text="Пред. страница ⬅️",
                callback_data=f"back_to_chat_folders_{account_phone}"
            ))
        # Кнопка следующей страницы
        if end_index < len(chats):
            if current_page == 0:
                next_page_text = "След. страница ➡️"
            else:
                # Для не первой страницы оставляем прежнюю логику текста
                next_page_text = "Следующая страница ➡️" if _idx == 0 else "След. страница ➡️"
            nav_row.append(InlineKeyboardButton(
                text=next_page_text,
                callback_data=f"more_chats_{account_phone}_{folder_id}_{current_page + 1}"
            ))
        if nav_row:
            markup.inline_keyboard.append(nav_row)
        
        # Новые кнопки навигации по аккаунтам в одном ряду
        nav_row_accounts = []
        if _idx > 0:
            nav_row_accounts.append(InlineKeyboardButton(text="Пред. аккаунт ⬇️", callback_data=f"back_to_prev_account_chats_{account_phone}"))
        
        # Для первого аккаунта - полный текст, для остальных - сокращённый
        next_text = "Следующий аккаунт ⬆️" if _idx == 0 else "След. аккаунт ⬆️"
        nav_row_accounts.append(InlineKeyboardButton(text=next_text, callback_data=f"next_chat_account_{account_phone}"))
        
        if nav_row_accounts:
            markup.inline_keyboard.append(nav_row_accounts)
        
        # Кнопка перехода в Итоговые настройки должна быть выше "Вернуться"
        markup.inline_keyboard.append([InlineKeyboardButton(text="Далее", callback_data="to_final_settings")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="to_ignore_chats_question")])
        
        # Формируем читаемую метку аккаунта и заголовок с номером страницы
        account_label = (f"@{account['username']}" if account.get('username') else (account.get('name') or account.get('phone')))
        title_text = (
            f"Страница {current_page + 1}\n\n\n"
            f"Выберите чаты для игнорирования на аккаунте {account_label}:"
        )
        await delete_and_send_image(
            (existing_message or call.message),
            "mailing.png",
            title_text,
            reply_markup=markup,
            user_id=user_id
        )
        
    except Exception as e:
        try:
            await call.answer(f"Ошибка: {e}", show_alert=True)
        except Exception:
            # Игнорируем ошибки с устаревшими callback
            pass

def migrate_accounts(accounts):
    changed = False
    for acc in accounts:
        if "name" not in acc or not acc["name"]:
            # Попробуем взять имя из username или phone
            acc["name"] = acc.get("username") or acc.get("phone")
            changed = True
    return changed



# 1. Расширяем функцию обновления состояния аккаунта
def update_account_resume_state(
    phone,
    template_index=None,
    folder=None,
    chat_index=None,
    break_seconds_left=None,
    break_until_timestamp=0,
    break_started_ts=None,
    message_count=None,
    username=None,
    filename=None,
    user_id=None
):
    if filename is None:
        if user_id is None:
            filename = resume_state_file
        else:
            user_dir = get_user_dir(user_id, detect_license_type(user_id))
            filename = os.path.join(user_dir, "resume_process.json")
    
    state = load_resume_state(filename, user_id)
    if not state:
        return
    for acc in state["accounts"]:
        if acc["phone"] == phone:
            if template_index is not None:
                acc["template_index"] = template_index
            if folder is not None:
                acc["folder"] = folder
            if chat_index is not None:
                acc["chat_index"] = chat_index
            if break_seconds_left is not None:
                acc["break_seconds_left"] = break_seconds_left
            if break_until_timestamp and break_until_timestamp > 0:
                acc["break_until_timestamp"] = break_until_timestamp
            if break_started_ts is not None:
                acc["break_started_ts"] = break_started_ts
            if message_count is not None:
                acc["message_count"] = message_count
            if username is not None:
                acc["username"] = username
    save_resume_state(state, filename, user_id)

async def send_messages(client, chats, message_template, nickname, start_index=0, message_count=0, timers=None, logging_enabled=True, selected_account=None, user_id=None, minimized=False):
    # 🔥 ПРИНУДИТЕЛЬНАЯ ПРОВЕРКА message_count ИЗ ФАЙЛА при запуске функции
    if selected_account and user_id:
        resume_state = load_resume_state(user_id=user_id)
        if resume_state and "accounts" in resume_state:
            for acc in resume_state["accounts"]:
                if acc.get("phone") == selected_account.get("phone"):
                    file_message_count = acc.get("message_count", 0)
                    if file_message_count != message_count:
                        print(f"🔥 ПЕРЕЗАПИСЫВАЕМ message_count для {selected_account.get('phone')}: {message_count} → {file_message_count} (из файла)")
                        message_count = file_message_count
                    break
    if timers is None:
        timers = {}

    while True:
        try:
            for i in range(start_index, len(chats)):
                chat = chats[i]
                try:
                    # Используем централизованную систему переподключения
                    session_name = selected_account.get('name') if selected_account else nickname
                    if not await ensure_client_connected(client, session_name, user_id):
                        # Если не удалось переподключиться, ждем и повторяем попытку
                        await asyncio.sleep(10)
                        continue

                    await client.send_message(chat, message_template)
                    message_count += 1
                    
                    # Обновляем статистику отправленных сообщений
                    if user_id:
                        increment_user_stat(user_id, "sent_messages", 1)
                        # Логируем отправку сообщения
                        log_mailing_activity(user_id, "message_sent", increment=1)
                    
                    # Динамически читаем актуальные флаги логирования/свернутости
                    try:
                        _ms = mailing_states.get(user_id, {}) if user_id is not None else {}
                        _logging_enabled = bool(_ms.get("logging_enabled", logging_enabled))
                        _minimized = bool(_ms.get("minimized", minimized))
                    except Exception:
                        _logging_enabled = logging_enabled
                        _minimized = minimized
                    if _logging_enabled and not _minimized:
                        if user_id:
                            await log_to_telegram(user_id, f"{nickname}: {chat.title if hasattr(chat, 'title') else chat.username} / Успешно 🟢 / {message_count}", "mailing")
                        else:
                            print(f"{print_in_white(nickname)}: {chat.title if hasattr(chat, 'title') else chat.username} / {print_in_green(f'Успешно 🟢 / {message_count}')}", flush=True)

                    # --- Сохраняем состояние после КАЖДОЙ успешной отправки для защиты от потери данных ---
                    if selected_account:
                        update_account_resume_state(selected_account['phone'], chat_index=i, message_count=message_count, user_id=user_id)
                        print(f"💾 Сохранено: {selected_account.get('phone')} → {message_count}/30")

                    delay = random.randint(13, 15)
                    timers[nickname] = delay

                    while delay > 0:
                        for ms in range(10, 0, -1):
                            timers[nickname] = f"{delay - 1}.{ms}" if ms < 10 else f"{delay}.0"
                            print_timers(timers)
                            await asyncio.sleep(0.1)
                        delay -= 1

                    timers.pop(nickname, None)
                    print_timers(timers)

                    if message_count >= 30:
                        return message_count, i + 1
                except Exception as e:
                    message_count += 1
                    
                    # --- Сохраняем состояние даже при ошибке для защиты от потери счетчика ---
                    if selected_account:
                        update_account_resume_state(selected_account['phone'], chat_index=i, message_count=message_count, user_id=user_id)
                        print(f"💾 Сохранено (ошибка): {selected_account.get('phone')} → {message_count}/30")
                    
                    try:
                        _ms = mailing_states.get(user_id, {}) if user_id is not None else {}
                        _logging_enabled = bool(_ms.get("logging_enabled", logging_enabled))
                        _minimized = bool(_ms.get("minimized", minimized))
                    except Exception:
                        _logging_enabled = logging_enabled
                        _minimized = minimized
                    if _logging_enabled and not _minimized:
                        if user_id:
                            await log_to_telegram(user_id, f"{nickname}: {chat.title if hasattr(chat, 'title') else chat.username} / Неудачно 🔴 / {message_count}", "mailing")
                        else:
                            print(f"{print_in_white(nickname)}: {print_in_yellow(chat.title if hasattr(chat, 'title') else chat.username)} / {print_in_yellow(f'Неудачно 🔴 / {message_count}')}", flush=True)
                    if message_count >= 30:
                        return message_count, i + 1

            return message_count, len(chats)
        except ConnectionError:
            # Используем централизованную систему переподключения
            session_name = selected_account.get('name') if selected_account else nickname
            await ensure_client_connected(client, session_name, user_id)
        except RPCError as e:
            if user_id:
                await log_to_telegram(user_id, f"Ошибка RPC: {e}. Переподключение...", "mailing")
            else:
                print(f"Ошибка RPC: {e}. Переподключение...")
            # Переподключаемся при RPC ошибках
            session_name = selected_account.get('name') if selected_account else nickname
            await ensure_client_connected(client, session_name, user_id)
        except Exception as e:
            if user_id:
                await log_to_telegram(user_id, f"Необработанная ошибка в клиенте: {e}. Переподключение...", "mailing")
            else:
                print(f"Необработанная ошибка в клиенте: {e}. Переподключение...")
            # Переподключаемся при любых ошибках
            session_name = selected_account.get('name') if selected_account else nickname
            await ensure_client_connected(client, session_name, user_id)


async def main_flow(selected_account, client, template_list, template_index, selected_folder, timers, logging_enabled, start_index=0, message_count=0, alternate_templates_enabled=True, user_id=None, minimized=False):
    # 🔥 ПРИНУДИТЕЛЬНАЯ ЗАГРУЗКА message_count ИЗ ФАЙЛА
    if selected_account and user_id:
        resume_state = load_resume_state(user_id=user_id)
        if resume_state and "accounts" in resume_state:
            for acc in resume_state["accounts"]:
                if acc.get("phone") == selected_account.get("phone"):
                    file_message_count = acc.get("message_count", 0)
                    if file_message_count != message_count:
                        print(f"🔥 main_flow ПЕРЕЗАПИСЫВАЕМ message_count для {selected_account.get('phone')}: {message_count} → {file_message_count} (из файла)")
                        message_count = file_message_count
                    break
    
    session_message_count = message_count  # Используем загруженное значение
    while True:
        try:
            if user_id is not None and not is_license_valid(user_id):
                await handle_access_expired(user_id)
                return
            # Используем централизованную систему переподключения
            if selected_account and selected_account.get('name'):
                session_name = selected_account.get('name')
            else:
                # Используем безопасный способ получения id клиента
                try:
                    session_name = f"client_{id(client)}"
                except:
                    session_name = "unknown_client"
            
            if not await ensure_client_connected(client, session_name, user_id):
                await asyncio.sleep(10)
                continue
            await client.get_dialogs()
            folder_dict = await list_folders(client)
            # Применяем игнор папок для текущего аккаунта
            try:
                ignore_settings = load_ignore_settings(user_id) if user_id else {"ignore_folders": {}, "ignore_chats": {}}
            except Exception:
                ignore_settings = {"ignore_folders": {}, "ignore_chats": {}}
            ignore_folders = ignore_settings.get("ignore_folders", {})
            filtered_folder_dict = filter_folders_by_ignore(folder_dict, ignore_folders, selected_account.get('phone'))
            folder_dict = filtered_folder_dict or {}
            folder_keys = list(folder_dict.keys())
            
            # Проверяем и восстанавливаем структуру папки если нужно
            if selected_folder and 'folder_index' in selected_folder:
                try:
                    # Проверяем, что folder_index валидный
                    if selected_folder['folder_index'] < len(folder_keys):
                        folder_key = folder_keys[selected_folder['folder_index']]
                        selected_folder = folder_dict[folder_key]
                        print(f"✅ Восстановлена структура папки в main_flow: {selected_folder}")
                    else:
                        error_msg = f"Ошибка: folder_index {selected_folder['folder_index']} выходит за пределы доступных папок"
                        if user_id:
                            await log_to_telegram(user_id, error_msg, "mailing")
                        else:
                            print(error_msg)
                        return
                except Exception as e:
                    error_msg = f"Ошибка при восстановлении структуры папки в main_flow: {e}"
                    if user_id:
                        await log_to_telegram(user_id, error_msg, "mailing")
                    else:
                        print(error_msg)
                    return
            
            # Проверяем, что у папки есть id
            if not selected_folder or 'id' not in selected_folder:
                error_msg = f"Ошибка: папка не содержит id в main_flow: {selected_folder}"
                if user_id:
                    await log_to_telegram(user_id, error_msg, "mailing")
                else:
                    print(error_msg)
                return
            
            folder_index = next((i for i, key in enumerate(folder_keys) if folder_dict[key]['id'] == selected_folder['id']), None)
            if folder_index is None:
                error_msg = f"Ошибка: выбранная папка с ID {selected_folder['id']} не найдена."
                if user_id:
                    await log_to_telegram(user_id, error_msg, "mailing")
                else:
                    print(error_msg)
                return

            session_message_count = message_count
            chats = []

            while True:
                # Проверка интернета встроена в ensure_client_connected
                if not await ensure_client_connected(client, session_name, user_id):
                    await asyncio.sleep(10)
                    continue

                selected_folder = folder_dict[folder_keys[folder_index]]
                if not chats:
                    chats = await get_chats_in_folder(client, selected_folder['id'], logging_enabled=logging_enabled)
                    # Применяем игнор чатов для текущей папки
                    try:
                        ignore_chats = ignore_settings.get("ignore_chats", {})
                        chats = filter_chats_by_ignore(chats, ignore_chats, selected_account.get('phone'), selected_folder['id'])
                    except Exception:
                        pass
                if not chats:
                    if user_id:
                        await log_to_telegram(user_id, f"В папке \"{selected_folder['title']}\" нет доступных чатов. Переход к следующей папке.", "mailing")
                    else:
                        sys.stdout.write("\033[2K\033[0G")
                        sys.stdout.flush()
                        print(f"В папке \"{selected_folder['title']}\" нет доступных чатов. Переход к следующей папке.")
                    folder_index = (folder_index + 1) % len(folder_keys)
                    start_index = 0
                    chats = []
                    continue

                remaining_chats = chats[start_index:]
                
                # Проверяем, что template_list не пустой и template_index валидный
                if not template_list or len(template_list) == 0:
                    error_msg = f"Ошибка: список шаблонов пуст для аккаунта {selected_account.get('name', 'неизвестно')}"
                    if user_id:
                        await log_to_telegram(user_id, error_msg, "mailing")
                    else:
                        print(error_msg)
                    return
                
                if template_index >= len(template_list):
                    template_index = 0  # Сбрасываем на начало
                
                message_template = template_list[template_index]

                # --- Передаём selected_account для обновления состояния ---
                # Для логов используем username без @ (требование)
                nickname = (selected_account.get('username') or selected_account.get('name') or selected_account.get('phone'))
                session_message_count, start_index = await send_messages(
                    client, chats, message_template, nickname, start_index, session_message_count, timers, logging_enabled, selected_account=selected_account, user_id=user_id, minimized=minimized
                )

                update_account_resume_state(selected_account['phone'], chat_index=start_index, break_seconds_left=0, user_id=user_id)

                if session_message_count >= 30:
                    nickname = (selected_account.get('username') or selected_account.get('name') or selected_account.get('phone'))
                    # --- Таймер перерыва от 8ч3мн до 8ч5мн  ---
                    break_time_seconds = random.randint(8 * 3600 + 3 * 60, 8 * 3600 + 5 * 60)
                    now_ts = int(time.time())
                    break_until_timestamp = now_ts + break_time_seconds
                    update_account_resume_state(
                        selected_account['phone'],
                        chat_index=start_index,
                        break_seconds_left=break_time_seconds,
                        break_until_timestamp=break_until_timestamp,
                        break_started_ts=now_ts,
                        user_id=user_id
                    )
                    
                    # Показываем первое сообщение с точным временем перерыва
                    hours = break_time_seconds // 3600
                    minutes = (break_time_seconds % 3600) // 60
                    seconds = break_time_seconds % 60
                    time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                    display_name = get_display_name(selected_account)
                    message = f"{display_name}: до конца перерыва осталось {time_str} 🟡"
                    if user_id:
                        await log_to_telegram(user_id, message, "mailing")
                    
                    # Создаем задачу для countdown_timer через систему управления задачами
                    task_name = f"break_timer_{selected_account.get('phone', nickname)}"
                    task = await start_task(
                        user_id, 
                        task_name, 
                        countdown_timer(break_time_seconds, nickname, timers, selected_account=selected_account, user_id=user_id, break_started_ts=now_ts)
                    )
                    # Ждем завершения таймера перерыва
                    await task
                    update_account_resume_state(selected_account['phone'], chat_index=start_index, break_seconds_left=0, break_until_timestamp=0, user_id=user_id)
                    # --- БЕЗОПАСНЫЙ СБРОС: сбрасываем message_count ТОЛЬКО если действительно достигли лимита ---
                    if session_message_count >= 30:
                        print(f"🔄 Сброс счетчика для аккаунта {selected_account.get('phone')}: завершен полный цикл 30/30 + перерыв")
                        session_message_count = 0
                        update_account_resume_state(selected_account['phone'], message_count=0, user_id=user_id)
                    else:
                        print(f"🛡️ Сохраняем счетчик для аккаунта {selected_account.get('phone')}: {session_message_count}/30 (неполный цикл)")
                    remaining_chats = chats[start_index:]
                    if remaining_chats:
                        nickname = (selected_account.get('username') or selected_account.get('name') or selected_account.get('phone'))
                        if user_id:
                            chat_list = "\n".join([f"{i}. {chat.title if hasattr(chat, 'title') else (chat.username or chat.first_name)}" for i, chat in enumerate(remaining_chats, start=start_index + 1)])
                            #await log_to_telegram(user_id, f"\"{selected_folder['title']}\" - {nickname}:\n{chat_list}", "mailing")
                        else:
                            print(f"\n\"{selected_folder['title']}\" - {nickname}:")
                            for i, chat in enumerate(remaining_chats, start=start_index + 1):
                                chat_title = chat.title if hasattr(chat, 'title') else (chat.username or chat.first_name)
                                print(f"{i}. {chat_title}")
                    else:
                        folder_index = (folder_index + 1) % len(folder_keys)
                        # При возврате к первой папке и включенном чередовании — переключаем шаблон и сохраняем
                        if folder_index == 0 and alternate_templates_enabled:
                            template_index = (template_index + 1) % len(template_list)
                            update_account_resume_state(selected_account['phone'], template_index=template_index, user_id=user_id)
                        start_index = 0
                        chats = []
                        continue
                    continue

                if start_index >= len(chats):
                    sys.stdout.write("\033[2K\033[0G")
                    sys.stdout.flush()
                    folder_index = (folder_index + 1) % len(folder_keys)
                    if folder_index == 0:
                        if alternate_templates_enabled:
                            template_index = (template_index + 1) % len(template_list)
                            update_account_resume_state(selected_account['phone'], template_index=template_index, user_id=user_id)
                        # Если alternate_templates_enabled == False, template_index не меняется!
                    selected_folder = folder_dict[folder_keys[folder_index]]
                    # Сохраняем folder_index вместо полной папки
                    folder_for_save = {"folder_index": folder_index, "title": selected_folder["title"]}
                    update_account_resume_state(selected_account['phone'], folder=folder_for_save, user_id=user_id)
                    start_index = 0
                    chats = []
                    nickname = (selected_account.get('username') or selected_account.get('name') or selected_account.get('phone'))
                    try:
                        _ms = mailing_states.get(user_id, {}) if user_id is not None else {}
                        _logging_enabled = bool(_ms.get("logging_enabled", logging_enabled))
                        _minimized = bool(_ms.get("minimized", minimized))
                    except Exception:
                        _logging_enabled = logging_enabled
                        _minimized = minimized
                    if user_id and _logging_enabled and not _minimized:
                        await log_to_telegram(user_id, f'{nickname}: переход к папке "{selected_folder["title"]}" 🗂', "mailing")
                    else:
                        sys.stdout.write("\033[2K\033[0G")
                        sys.stdout.flush()
                    try:
                        _ms = mailing_states.get(user_id, {}) if user_id is not None else {}
                        _logging_enabled = bool(_ms.get("logging_enabled", logging_enabled))
                        _minimized = bool(_ms.get("minimized", minimized))
                    except Exception:
                        _logging_enabled = logging_enabled
                        _minimized = minimized
                    if _logging_enabled and not _minimized:
                        print(f'\n{nickname}: переход к папке "{selected_folder["title"]}" 🗂')
                        print()
                    continue

        except ConnectionError:
            if user_id:
                await log_to_telegram(user_id, "Соединение потеряно. Переподключение...", "mailing")
            else:
                print("Соединение потеряно. Переподключение...")
            try:
                if client.is_connected():
                    await client.disconnect()
                await asyncio.sleep(5)
                await client.connect()
            except Exception as e:
                if user_id:
                    await log_to_telegram(user_id, f"Ошибка переподключения: {e}", "mailing")
                else:
                    print(f"Ошибка переподключения: {e}")
                await asyncio.sleep(10)
        except RPCError as e:
            # 🛡️ КРИТИЧЕСКАЯ ЗАЩИТА: Сохраняем состояние перед переподключением в main_flow
            if selected_account and user_id and session_message_count > 0:
                update_account_resume_state(
                    selected_account['phone'], 
                    chat_index=start_index, 
                    message_count=session_message_count, 
                    user_id=user_id
                )
                print(f"🛡️ Сохранено состояние main_flow перед RPC переподключением: {selected_account.get('phone')} → {session_message_count}/30")
            
            if user_id:
                await log_to_telegram(user_id, f"Ошибка RPC: {e}. Переподключение через 10 секунд...", "mailing")
            else:
                print(f"Ошибка RPC: {e}. Переподключение через 10 секунд...")
            await asyncio.sleep(10)
        except Exception as e:
            if user_id:
                await log_to_telegram(user_id, f"Необработанная ошибка в клиенте: {e}. Перезапуск через 10 секунд...", "mailing")
            else:
                print(f"Необработанная ошибка в клиенте: {e}. Перезапуск через 10 секунд...")
            await asyncio.sleep(10)
        
        


async def main_flow_resume(selected_account, client, template_list, template_index, selected_folder, timers, start_index, break_seconds_left, logging_enabled=True, alternate_templates_enabled=True, user_id=None, ignore_breaks=False, minimized=False):
    print(f"🔄 main_flow_resume: начало выполнения для аккаунта {selected_account.get('name', 'неизвестно')}")
    print(f"🔄 main_flow_resume: параметры - template_index={template_index}, start_index={start_index}")
    
    state = load_resume_state(user_id=user_id)
    acc_state = None
    if state:
        acc_state = next((a for a in state["accounts"] if a["phone"] == selected_account["phone"]), None)
        print(f"🔄 main_flow_resume: найдено состояние аккаунта: {acc_state is not None}")
    if acc_state:
        break_until_timestamp = acc_state.get("break_until_timestamp")
        message_count = acc_state.get("message_count", 0)
    else:
        break_until_timestamp = 0
        message_count = 0

    now = int(time.time())
    
    # --- Если перерыв был начат и НЕ игнорируем перерывы ---
    if not ignore_breaks and break_until_timestamp and break_until_timestamp > 0:
        left = break_until_timestamp - now
        if left > 0:
            nickname = (selected_account.get('username') or selected_account.get('name') or selected_account.get('phone'))
            account_phone = selected_account.get("phone")
            
            # Восстанавливаем корректную точку старта перерыва для часовых логов
            acc_break_started_ts = None
            # Получаем break_started_ts из файла
            resume_state_for_break = load_resume_state(user_id=user_id)
            if resume_state_for_break and "accounts" in resume_state_for_break:
                for acc in resume_state_for_break["accounts"]:
                    if acc.get("phone") == account_phone:
                        if acc.get("break_started_ts"):
                            acc_break_started_ts = int(acc["break_started_ts"])
                        else:
                            # Если не было сохранено, вычислим назад от break_until_timestamp
                            planned_duration = acc.get("break_seconds_left", left)
                            acc_break_started_ts = break_until_timestamp - planned_duration
                        break
            
            if acc_break_started_ts is None:
                acc_break_started_ts = break_until_timestamp - left
            # Создаем задачу для countdown_timer через систему управления задачами
            task_name = f"break_timer_{selected_account.get('phone', nickname)}"
            task = await start_task(
                user_id, 
                task_name, 
                countdown_timer(left, nickname, timers, selected_account=selected_account, user_id=user_id, break_started_ts=acc_break_started_ts)
            )
            # Ждем завершения таймера перерыва
            await task
            update_account_resume_state(selected_account['phone'], message_count=0, break_seconds_left=0, break_until_timestamp=0, user_id=user_id)
            message_count = 0
            # После завершения перерыва завершаем функцию - не продолжаем рассылку
            return
        else:
            update_account_resume_state(selected_account['phone'], break_seconds_left=0, break_until_timestamp=0, user_id=user_id)

    # --- Если лимит сообщений уже достигнут, но перерыв не был начат и НЕ игнорируем перерывы ---
    elif not ignore_breaks and message_count >= 30:
        print(f"⚠️ Аккаунт {selected_account.get('name', 'неизвестно')} достиг лимита сообщений ({message_count}/30), начинаем перерыв")
        break_time_seconds = random.randint(8 * 3600 + 3 * 60, 8 * 3600 + 5 * 60)
        break_until_timestamp = now + break_time_seconds
        update_account_resume_state(
            selected_account['phone'],
            break_seconds_left=break_time_seconds,
            break_until_timestamp=break_until_timestamp,
            user_id=user_id
        )
        
        # Показываем первое сообщение с точным временем перерыва
        hours = break_time_seconds // 3600
        minutes = (break_time_seconds % 3600) // 60
        seconds = break_time_seconds % 60
        time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        display_name = get_display_name(selected_account)
        message = f"{display_name}: до конца перерыва осталось {time_str} 🟡"
        if user_id:
            await log_to_telegram(user_id, message, "mailing")
        
        # Сохраняем и передаем время начала перерыва
        now_ts = int(time.time())
        update_account_resume_state(
            selected_account['phone'],
            break_started_ts=now_ts,
            user_id=user_id
        )
        # Создаем задачу для countdown_timer через систему управления задачами
        task_name = f"break_timer_{selected_account.get('phone', nickname)}"
        task = await start_task(
            user_id, 
            task_name, 
            countdown_timer(break_time_seconds, nickname, timers, selected_account=selected_account, user_id=user_id, break_started_ts=now_ts)
        )
        # Ждем завершения таймера перерыва
        await task
        update_account_resume_state(selected_account['phone'], message_count=0, break_seconds_left=0, break_until_timestamp=0, user_id=user_id)
        message_count = 0
        # После завершения перерыва завершаем функцию - не продолжаем рассылку
        return

    # --- Если нет перерыва и лимит не достигнут ---
    
    # Проверяем, что template_list не пустой и template_index валидный
    if not template_list or len(template_list) == 0:
        error_msg = f"Ошибка: список шаблонов пуст для аккаунта {selected_account.get('name', 'неизвестно')}"
        if user_id:
            await log_to_telegram(user_id, error_msg, "mailing")
        else:
            print(error_msg)
        return
    
    if template_index >= len(template_list):
        template_index = 0  # Сбрасываем на начало
    
    # Проверяем и восстанавливаем структуру папки
    if selected_folder and 'folder_index' in selected_folder:
        try:
            # Получаем актуальный список папок и применяем фильтр игнора
            folder_dict = await list_folders(client)
            try:
                ignore_settings = load_ignore_settings(user_id) if user_id else {"ignore_folders": {}, "ignore_chats": {}}
            except Exception:
                ignore_settings = {"ignore_folders": {}, "ignore_chats": {}}
            ignore_folders = ignore_settings.get("ignore_folders", {})
            folder_dict = filter_folders_by_ignore(folder_dict, ignore_folders, selected_account.get('phone')) or {}
            folder_keys = list(folder_dict.keys())
            
            # Проверяем, что folder_index валидный
            if selected_folder['folder_index'] < len(folder_keys):
                folder_key = folder_keys[selected_folder['folder_index']]
                selected_folder = folder_dict[folder_key]
                print(f"✅ Восстановлена структура папки: {selected_folder}")
            else:
                error_msg = f"Ошибка: folder_index {selected_folder['folder_index']} выходит за пределы доступных папок"
                if user_id:
                    await log_to_telegram(user_id, error_msg, "mailing")
                else:
                    print(error_msg)
                return
        except Exception as e:
            error_msg = f"Ошибка при восстановлении структуры папки: {e}"
            if user_id:
                await log_to_telegram(user_id, error_msg, "mailing")
            else:
                print(error_msg)
            return
    
    # Проверяем, что у папки есть id
    if not selected_folder or 'id' not in selected_folder:
        error_msg = f"Ошибка: папка не содержит id: {selected_folder}"
        if user_id:
            await log_to_telegram(user_id, error_msg, "mailing")
        else:
            print(error_msg)
        return
    
    # Используем централизованную систему переподключения
    if selected_account and selected_account.get('name'):
        session_name = selected_account.get('name')
    else:
        # Используем безопасный способ получения id клиента
        try:
            session_name = f"client_{id(client)}"
        except:
            session_name = "unknown_client"
    
    if not await ensure_client_connected(client, session_name, user_id):
        await asyncio.sleep(10)
        return

    # Дополнительная проверка лимита перед запуском main_flow
    if message_count >= 30 and not ignore_breaks:
        print(f"⚠️ Аккаунт {selected_account.get('name', 'неизвестно')} уже достиг лимита ({message_count}/30), пропускаем отправку")
        if user_id and not minimized:
            nickname = (selected_account.get('username') or selected_account.get('name') or selected_account.get('phone'))
            await log_to_telegram(user_id, f"{nickname}: лимит сообщений уже достигнут ({message_count}/30), пропускаем", "mailing")
        return
    
    print(f"🔄 main_flow_resume: запускаем main_flow для аккаунта {selected_account.get('name', 'неизвестно')} с message_count={message_count}")
    
    await main_flow(
        selected_account, client, template_list, template_index, selected_folder, timers,
        logging_enabled=logging_enabled, start_index=start_index, message_count=message_count,
        
        alternate_templates_enabled=alternate_templates_enabled, user_id=user_id, minimized=minimized
    )
async def main(user_id=None, license_type=None):
    global sessions_dir, resume_state_file, config_path
    if user_id is None or license_type is None:
        if len(sys.argv) > 2:
            user_id = sys.argv[1]
            license_type = sys.argv[2]
        else:
            print("Не переданы user_id и license_type!")
            return
    user_dir = get_user_dir(user_id, license_type)
    config_path = os.path.join(user_dir, "config.json")
    resume_state_file = os.path.join(user_dir, "resume_process.json")
    sessions_dir = os.path.join(get_user_subdir(user_id, "bot", license_type), "sessions")
    os.makedirs(sessions_dir, exist_ok=True)

    if not os.path.exists(config_path):
        print(f"Файл конфигурации {config_path} не найден")
        return

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # --- ДОБАВЛЕНО: Получаем api_id и api_hash из корня конфига ---
    global_api_id = config.get("api_id")
    global_api_hash = config.get("api_hash")

    accounts = config.get("accounts", [])
    # Обеспечиваем, что у аккаунтов есть поле name
    def _migrate_accounts_local(accs):
        changed = False
        for acc in accs:
            if "name" not in acc or not acc.get("name"):
                acc["name"] = acc.get("username") or acc.get("phone")
                changed = True
        return changed

    if _migrate_accounts_local(accounts):
        config["accounts"] = accounts
    #   with open(config_path, "w", encoding="utf-8") as f:
        #   json.dump(config, f, ensure_ascii=False, indent=2)

    # --- ДОБАВЛЕНО: Подставляем api_id и api_hash в каждый аккаунт ---
    for acc in accounts:
        if "api_id" not in acc:
            acc["api_id"] = global_api_id
        if "api_hash" not in acc:
            acc["api_hash"] = global_api_hash

    available_accounts = [
        acc for acc in accounts
        if all(k in acc for k in ["api_id", "api_hash", "phone"])
    ]

    selected_accounts = await select_accounts(available_accounts)
    if not selected_accounts:
        return

    # --- Новый блок: запрос Last summary ---
        print_separator()
    print("Last summary:\n1. Да\n2. Нет")
    summary_choice = input("Ваш выбор: ").strip()
    if summary_choice == "1":
        state = load_resume_state(resume_state_file)
        now = int(time.time())
        if state and "accounts" in state:
            limits_list = [
                f"{acc.get('nickname', acc.get('phone', ''))} - {acc.get('message_count', 0)}/30"
                for acc in state["accounts"]
                if (not acc.get("break_until_timestamp")) and acc.get("message_count", 0) < 30
            ]
            breaks_list = [
                f"{acc.get('nickname', acc.get('phone', ''))} - \033[91m{(acc['break_until_timestamp'] - now) // 3600:02d} {(acc['break_until_timestamp'] - now) % 3600 // 60:02d} {(acc['break_until_timestamp'] - now) % 60:02d}\033[0m"
                for acc in state["accounts"]
                if acc.get("break_until_timestamp") and acc["break_until_timestamp"] > now
            ]

            # --- Определяем, что выводить ---
            if limits_list and breaks_list:
                print_separator()
                print("LIMITS:")
                print()
                for line in limits_list:
                    print(line)
                print()
                print()
                print()
                print("BREAKS:")
                print()
                for line in breaks_list:
                    print(line)
            elif limits_list:
                print_separator()
                print("LIMITS:")
                print()
                for line in limits_list:
                    print(line)
            elif breaks_list:
                print_separator()
                print("BREAKS:")
                print()
                for line in breaks_list:
                    print(line)
    # --- Конец блока Last summary ---

    mode_choice = None
    while True:
        print_separator()
        print("Выберите режим работы:")
        print("1. Custom configuration")
        print("2. Select configuration")
        print("3. Resume process")
        mode_choice = input("Введите номер режима: ").strip()
        if mode_choice in {"1", "2", "3"}:
            if mode_choice == "3":
                state = load_resume_state(resume_state_file)
                if not state:
                    print("Статус предыдущего запуска не определён.")
                    continue
                break
            else:
                print("Неверный выбор. Введите 1, 2 или 3.")

    # 1. Custom configuration 
    if mode_choice == "1":
        timers = {}
        authorized_clients = {}
        templates = {}
        template_indices = {}
        folders = {}

        # --- Новый блок: запрос чередования шаблонов ---
        print_separator()
        print("Включить чередование шаблонов?:\n1. Да\n2. Нет")
        alternate_templates_choice = input("Ваш выбор: ").strip()
        alternate_templates_enabled = alternate_templates_choice == "1"
        # --- Конец блока ---

        # Авторизация выбранных аккаунтов
        for idx, account in enumerate(selected_accounts, start=1):
            client = await authenticate_client(account)
            if client:
                authorized_clients[account['phone']] = client
            else:
                print(f"Не удалось авторизовать аккаунт {account['phone']}. Пропускаем.")
                continue

        print_separator()

        # Выбор шаблонов сообщений для авторизованных аккаунтов
        for idx, account in enumerate(selected_accounts, start=1):
            if account['phone'] not in authorized_clients:
                continue  # Пропускаем неавторизованные аккаунты

            template_list = get_templates_for_account(account)
            print(f"Выберите текстовое сообщение для аккаунта {account.get('nickname', account['phone'])} / {idx}:")
            for i, template in enumerate(template_list, 1):
                print(f"{i}. {template.splitlines()[0][:50]}{'...' if len(template) > 50 else ''}")

            while True:
                choice = input("Введите номер сообщения: ").strip()
                if choice.isdigit() and 1 <= int(choice) <= len(template_list):
                    templates[account['phone']] = template_list
                    template_indices[account['phone']] = int(choice) - 1  # Индекс текущего шаблона
                    break
                else:
                    print(f"Неверный выбор. Введите число от 1 до {len(template_list)}")
            # Пустая строка только если это не последний аккаунт
            if idx != len(selected_accounts):
                print()
                print()
                print()

        print_separator()

        # Выбор папок для авторизованных аккаунтов
        for idx, account in enumerate(selected_accounts, start=1):
            if account['phone'] not in authorized_clients:
                continue  # Пропускаем неавторизованные аккаунты

            client = authorized_clients[account['phone']]
            print(f"Выберите папку для аккаунта {account.get('nickname', account['phone'])} / {idx}:")
            folder_dict = await list_folders(client)
            selected_folder = await select_folder(folder_dict)
            folders[account['phone']] = selected_folder
            if idx != len(selected_accounts):
                print()
                print()
                print()

        # --- Новый блок: запрос логирования ---
        logging_enabled = True
        while True:
            print_separator()
            print('Добавить логирование статусов отправки сообщений? : \n1. Да\n2. Нет\n')
            log_choice = input('Ваш выбор? : ').strip()
            if log_choice == "1":
                logging_enabled = True
                break
            elif log_choice == "2":
                logging_enabled = False
                break
            else:
                print("Введите 1 или 2.")
        # --- Конец блока запроса логирования ---

        # Запрос команды start
        while True:
            print_separator()
            command = input("Введите команду start: ").strip().lower()
            if command == "start":
                break
            else:
                print("Неверная команда. Введите 'start' для начала рассылки.")

        print_separator()  

        # Вывод выбранных папок и аккаунтов
        for account in selected_accounts:
            if account['phone'] in folders:
                selected_folder = folders[account['phone']]
                nickname = account.get('nickname', account['phone'])
                print(f'Вы выбрали папку "{selected_folder["title"]}" - {nickname}')
                
        print_separator()
        
        # Выводим чаты из выбранных папок для всех аккаунтов
        chats_per_account = {}
        for idx, account in enumerate(selected_accounts):
            if account['phone'] in folders and account['phone'] in authorized_clients:
                client = authorized_clients[account['phone']]
                selected_folder = folders[account['phone']]
                chats = await get_chats_in_folder(client, selected_folder['id'], logging_enabled=logging_enabled)
                chats_per_account[account['phone']] = chats

                # Формируем вывод для одного аккаунта
                output_lines = [f'"{idx+1}" - {account.get("nickname", account["phone"])}:']
                for i, chat in enumerate(chats, 1):
                    # Показываем только название чата или username
                    if hasattr(chat, "title") and chat.title:
                        chat_name = chat.title
                    elif hasattr(chat, "username") and chat.username:
                        chat_name = chat.username
                    elif hasattr(chat, "first_name") and chat.first_name:
                        chat_name = chat.first_name
                    else:
                        chat_name = str(chat.id)
                    output_lines.append(f"{i}. {chat_name}")
                print('\n'.join(output_lines))  # <--- Весь вывод одним print

                # Пустая строка только если это не последний аккаунт
                if idx != len(selected_accounts) - 1:
                    print()

        print_separator()

        # --- Сохраняем состояние для Resume process ---
        resume_state = {
            "accounts": [],
            "logging_enabled": logging_enabled,
            "alternate_templates_enabled": alternate_templates_enabled,
            "sync_break_finished": False  # <-- ДОБАВЬ ЭТУ СТРОКУ
        }
        for account in selected_accounts:
            phone = account['phone']
            nickname = account.get('nickname', phone)
            template_index = template_indices.get(phone, 0)
            folder = folders.get(phone, {})
            resume_state["accounts"].append({
                "phone": phone,
                "nickname": nickname,
                "username": account.get('username', ''),
                "template_index": template_index,
                "folder": folder,
                "chat_index": 0,  # Начинаем с первого чата
                "break_seconds_left": 0,  # Нет перерыва на старте
                "break_until_timestamp": 0,
                "message_count": 0
            })
        save_resume_state(resume_state, resume_state_file)
        # --- Конец блока сохранения состояния ---

        # Запуск рассылки сообщений для каждого аккаунта
        tasks = []
        for account in selected_accounts:
            if account['phone'] not in authorized_clients:
                continue  # Пропускаем неавторизованные аккаунты

            client = authorized_clients[account['phone']]
            template_list = templates[account['phone']]
            template_index = template_indices[account['phone']]
            selected_folder = folders[account['phone']]

            # --- Передаём флаг чередования шаблонов ---
            tasks.append(main_flow(
                account, client, template_list, template_index, selected_folder, timers, logging_enabled,
                alternate_templates_enabled=alternate_templates_enabled, user_id=user_id
            ))

        await asyncio.gather(*tasks)

    # 2. Select configuration 
    if mode_choice == "2":
        # --- Новый блок: запрос чередования шаблонов ---
        print_separator()
        print("Включить чередование шаблонов?:\n1. Да\n2. Нет")
        alternate_templates_choice = input("Ваш выбор: ").strip()
        alternate_templates_enabled = alternate_templates_choice == "1"
        # --- Конец блока ---

        while True:
            print_separator()
            print("Выберите текстовое сообщение:")
            print("1. T1")
            print("2. T2")
            t_choice = input("Введите номер шаблона: ").strip()
            if t_choice in {"1", "2"}:
                break
            else:
                print("Неверный выбор. Введите 1 или 2.")

        while True:
            print_separator()
            print("Выберите папку:")
            print("1. F1")
            print("2. F2")
            print("3. F3")
            print("4. F4")
            print("5. F5")
            f_choice = input("Введите номер набора папок: ").strip()
            if f_choice in {"1", "2", "3", "4", "5"}:
                break
            else:
                print("Неверный выбор. Введите число от 1 до 5.")

        timers = {}
        authorized_clients = {}
        templates = {}
        template_indices = {}
        folders = {}

        # Авторизация выбранных аккаунтов
        for idx, account in enumerate(selected_accounts, start=1):
            client = await authenticate_client(account)
            if client:
                authorized_clients[account['phone']] = client
            else:
                print(f"Не удалось авторизовать аккаунт {account['phone']}. Пропускаем.")
                continue

        # Автоматический выбор шаблонов
        for idx, account in enumerate(selected_accounts):
            template_list = get_templates_for_account(account)
            # Определяем стартовый шаблон (0 - template1, 1 - template2)
            if t_choice == "1":
                template_index = idx % 2  # 0,1,0,1...
            else:
                template_index = (idx + 1) % 2  # 1,0,1,0...
            templates[account['phone']] = template_list
            template_indices[account['phone']] = template_index

        # Автоматический выбор папок
        for idx, account in enumerate(selected_accounts):
            if account['phone'] not in authorized_clients:
                continue
            client = authorized_clients[account['phone']]
            folder_dict = await list_folders(client)
            folder_keys = list(folder_dict.keys())
            if not folder_keys:
                print(f"Нет папок для аккаунта {account.get('nickname', account['phone'])}")
                continue
            # Смещение индекса папки согласно выбору F1-F5
            folder_offset = int(f_choice) - 1
            folder_index = (idx + folder_offset) % len(folder_keys)
            selected_folder = folder_dict[folder_keys[folder_index]]
            folders[account['phone']] = selected_folder

        # --- Новый блок: запрос логирования ---
        logging_enabled = True
        while True:
            print_separator()
            print('Добавить логирование статусов отправки сообщений? : \n1. Да\n2. Нет\n')
            log_choice = input('Ваш выбор? : ').strip()
            if log_choice == "1":
                logging_enabled = True
                break
            elif log_choice == "2":
                logging_enabled = False
                break
            else:
                print("Введите 1 или 2.")
        # --- Конец блока запроса логирования ---

        # Запрос команды start
        while True:
            print_separator()
            command = input("Введите команду start: ").strip().lower()
            if command == "start":
                break
            else:
                print("Неверная команда. Введите 'start' для начала рассылки.")

        print_separator()        

        # Вывод выбранных папок и аккаунтов
        for account in selected_accounts:
            if account['phone'] in folders:
                selected_folder = folders[account['phone']]
                nickname = account.get('nickname', account['phone'])
                print(f'Вы выбрали папку "{selected_folder["title"]}" - {nickname}')

        print_separator()

        # --- Новый блок: выводим чаты из выбранных папок для всех аккаунтов ---
        chats_per_account = {}
        for idx, account in enumerate(selected_accounts):
            if account['phone'] in folders and account['phone'] in authorized_clients:
                client = authorized_clients[account['phone']]
                selected_folder = folders[account['phone']]
                chats = await get_chats_in_folder(client, selected_folder['id'], logging_enabled=logging_enabled)
                chats_per_account[account['phone']] = chats

                # Формируем вывод для одного аккаунта
                output_lines = [f'"{idx+1}" - {account.get("nickname", account["phone"])}:']
                for i, chat in enumerate(chats, 1):
                    # Показываем только название чата или username
                    if hasattr(chat, "title") and chat.title:
                        chat_name = chat.title
                    elif hasattr(chat, "username") and chat.username:
                        chat_name = chat.username
                    elif hasattr(chat, "first_name") and chat.first_name:
                        chat_name = chat.first_name
                    else:
                        chat_name = str(chat.id)
                    output_lines.append(f"{i}. {chat_name}")
                print('\n'.join(output_lines))  # <--- Весь вывод одним print

                # Пустая строка только если это не последний аккаунт
                if idx != len(selected_accounts) - 1:
                    print()

        print_separator()

    # --- Сохраняем состояние для Resume process ---
    resume_state = {
        "accounts": [],
        "logging_enabled": logging_enabled,
            "alternate_templates_enabled": alternate_templates_enabled,
        "sync_break_finished": False  # <-- ДОБАВЬ ЭТУ СТРОКУ
    }
    for account in selected_accounts:
        phone = account['phone']
        nickname = account.get('nickname', phone)
        template_index = template_indices.get(phone, 0)
        folder = folders.get(phone, {})
        resume_state["accounts"].append({
            "phone": phone,
            "nickname": nickname,
            "template_index": template_index,
            "folder": folder,
            "chat_index": 0,  # Начинаем с первого чата
            "break_seconds_left": 0,  # Нет перерыва на старте
            "break_until_timestamp": 0,
            "break_started_ts": 0,
            "message_count": 0
        })
        save_resume_state(resume_state, resume_state_file)
        # --- Конец блока сохранения состояния ---

        # Запуск рассылки сообщений для каждого аккаунта
        tasks = []
        for account in selected_accounts:
            if account['phone'] not in authorized_clients:
                continue

            client = authorized_clients[account['phone']]
            template_list = templates[account['phone']]
            template_index = template_indices[account['phone']]
            selected_folder = folders[account['phone']]

            # --- Передаём флаг чередования шаблонов ---
            tasks.append(main_flow(
                account, client, template_list, template_index, selected_folder, timers, logging_enabled,
                alternate_templates_enabled=alternate_templates_enabled, user_id=user_id
            ))

        if tasks:
            await asyncio.gather(*tasks)
        return
    



        logging_enabled = True
        while True:
            print('Добавить логирование статусов отправки сообщений? : \n1. Да\n2. Нет\n')
            log_choice = input('Ваш выбор? : ').strip()
            if log_choice == "1":
                logging_enabled = True
                break
            elif log_choice == "2":
                logging_enabled = False
                break
            else:
                print("Введите 1 или 2.")
        # --- Конец блока запроса логирования ---

    # 3. Resume process
    if mode_choice == "3":
        state = load_resume_state(resume_state_file)
        if not state:
            print("Статус предыдущего запуска не определён.")
            return

        timers = {}
        authorized_clients = {}
        tasks = []

        logging_enabled = state.get("logging_enabled", True)
        alternate_templates_enabled = state.get("alternate_templates_enabled", True)
        sync_break_finished = state.get("sync_break_finished", False)  # <-- ДОБАВЬ ЭТУ СТРОКУ

        print_separator()

        now = int(time.time())
        accounts = state["accounts"]

        # ПРЕДОХРАНИТЕЛЬ 1
        active_breaks = [
            acc.get("break_until_timestamp")
            for acc in accounts
            if acc.get("break_until_timestamp") and acc["break_until_timestamp"] > now
        ]
        break_start_times = [
            acc["break_until_timestamp"] - acc["break_seconds_left"]
            for acc in accounts
            if acc.get("break_until_timestamp") and acc.get("break_seconds_left")
        ]
        # --- Формируем limits_list и breaks_list ---
        limits_list = [
            f"{acc['nickname']} - {acc.get('message_count', 0)}/30"
            for acc in accounts
            if (not acc.get("break_until_timestamp")) and acc.get("message_count", 0) < 30
        ]
        breaks_list = [
            f"{acc['nickname']} - " + print_in_red(
                "{:02d} {:02d} {:02d}".format(
                    (acc['break_until_timestamp'] - now) // 3600,
                    ((acc['break_until_timestamp'] - now) % 3600) // 60,
                    (acc['break_until_timestamp'] - now) % 60,
                )
            )
            for acc in accounts
            if acc.get("break_until_timestamp") and acc["break_until_timestamp"] > now
        ]
        # Если есть активные перерывы и хотя бы один из них начался больше 5 минут назад
        if active_breaks and break_start_times and (now - min(break_start_times) > 1 * 60):
            if limits_list:
                print("LIMITS:")
                print()
                for line in limits_list:
                    print(line)
                print()
                print()
                print()
            if breaks_list:
                print("BREAKS:")
                print()
                for line in breaks_list:
                    print(line)
            print_separator()
            # 3. Меню выбора действия
            print("Выбрать:")
            print("1. Wait the break")
            print("2. Force continue")
            print("3. Refresh all state")
            action = input("Выберите действие: ").strip()
            if action == "2":
                print()
                # Просто продолжаем работу как обычно
            elif action == "3":
                print()
                for acc in accounts:
                    acc["message_count"] = 0
                    acc["break_seconds_left"] = 0
                    acc["break_until_timestamp"] = 0
                save_resume_state(state, resume_state_file)
            else:
                # 1 или любой другой ввод — ждём окончания самого длинного перерыва
                max_break_until = max(active_breaks)
                wait_seconds = max_break_until - now
                print()
                for acc in accounts:
                    nickname = acc.get('nickname', acc.get('name', acc.get('phone', 'Unknown')))
                    timers[nickname] = wait_seconds
                while wait_seconds > 0:
                    mins, secs = divmod(wait_seconds, 60)
                    hours, mins = divmod(mins, 60)
                    timer = f"{hours:02d}:{mins:02d}:{secs:02d}"
                    for acc in accounts:
                        nickname = acc.get('nickname', acc.get('name', acc.get('phone', 'Unknown')))
                        timers[nickname] = timer
                    print_timers(timers)
                    await asyncio.sleep(1)
                    wait_seconds -= 1
                timers.clear()
                print_timers(timers)
                for acc in accounts:
                    acc["message_count"] = 0
                    acc["break_seconds_left"] = 0
                    acc["break_until_timestamp"] = 0
                save_resume_state(state, resume_state_file)
        

        # ПРЕДОХРАНИТЕЛЬ 2
        now = int(time.time())
        any_break_finished = any(
            acc.get("break_until_timestamp") and acc["break_until_timestamp"] < now
            for acc in accounts
        )
        any_not_on_break_and_not_max = any(
            (not acc.get("break_until_timestamp")) and acc.get("message_count", 0) < 30
            for acc in accounts
        )
        # БЕЗОПАСНАЯ ЛОГИКА: сбрасываем ТОЛЬКО у аккаунтов, которые ДЕЙСТВИТЕЛЬНО завершили полный перерыв
        if any_break_finished and any_not_on_break_and_not_max:
            print("Обнаружены аккаунты с завершенными перерывами, проверяем каждый индивидуально...")
            for acc in accounts:
                # Сбрасываем ТОЛЬКО если аккаунт ДЕЙСТВИТЕЛЬНО достиг лимита 30/30 И его перерыв истек
                if (acc.get("message_count", 0) >= 30 and 
                    acc.get("break_until_timestamp") and 
                    acc["break_until_timestamp"] < now):
                    print(f"🔄 Сброс счетчика для аккаунта {acc.get('phone')}: перерыв завершен после достижения лимита 30/30")
                    acc["message_count"] = 0
                    acc["break_seconds_left"] = 0
                    acc["break_until_timestamp"] = 0
                else:
                    # НЕ сбрасываем счетчик для аккаунтов, которые не достигли лимита
                    print(f"🛡️ Сохраняем счетчик для аккаунта {acc.get('phone')}: {acc.get('message_count', 0)}/30")
            save_resume_state(state, resume_state_file)

        # --- В режиме реального времени обновляй sync_break_finished ---
        # Если хотя бы один аккаунт завершил перерыв, выставляем sync_break_finished = True
        # (НО только если есть хотя бы один не добравший лимит)
        if any_break_finished and any_not_on_break_and_not_max:
            state["sync_break_finished"] = True
            save_resume_state(state, resume_state_file)
        elif not any_break_finished:
            state["sync_break_finished"] = False
            save_resume_state(state, resume_state_file)

        # Восстанавливаем аккаунты и параметры из состояния
        for acc_state in state["accounts"]:
            account = next((a for a in available_accounts if a["phone"] == acc_state["phone"]), None)
            if not account:
                print(f"Аккаунт {acc_state['phone']} не найден в конфиге.")
                continue

            client = await authenticate_client(account)
            if not client:
                print(f"Не удалось авторизовать аккаунт {account['phone']}. Пропускаем.")
                continue
            
            authorized_clients[account['phone']] = client

            template_list = get_templates_from_config(load_config(user_id), account.get('phone'))
            template_index = acc_state.get("template_index", 0)
            selected_folder = acc_state.get("folder", {})
            chat_index = acc_state.get("chat_index", 0)
            start_index = chat_index + 1
            break_seconds_left = acc_state.get("break_seconds_left", 0)

            tasks.append(
                main_flow_resume(
                    account, client, template_list, template_index, selected_folder, timers, start_index, break_seconds_left,
                    logging_enabled=logging_enabled,
                    alternate_templates_enabled=alternate_templates_enabled, user_id=user_id
                )
            )

        if tasks:
            await asyncio.gather(*tasks)
        return


async def handle_incoming_messages(client, postman_client, group_id, selected_account, stop_event=None, notify_username=None):
    """
    Обрабатывает входящие сообщения для одного клиента.
    Использует централизованное управление клиентами.
    """
    print(">>> handle_incoming_messages: старт")
    last_sent = {}
    last_postman_sent_time = [0]
    private_recipient = notify_username
    nickname = selected_account.get('nickname', selected_account.get('name', 'Unknown'))

    # Создаем обработчик событий
    async def message_handler(event):
        try:
            # Проверяем, является ли сообщение исходящим
            if event.out:
                return  # Игнорируем исходящие сообщения

            # Проверяем, является ли сообщение личным (direct message)
            if not event.is_private:
                return  # Игнорируем сообщение без вывода в лог

            sender_id = event.sender_id
            message_text = event.text  # Получаем текст сообщения

            # Получаем информацию об отправителе
            sender = await event.get_sender()
            # --- Игнорируем сообщения от ботов ---
            if getattr(sender, "bot", False):
                return
            sender_username = f"@{sender.username}" if sender.username else f"no username"

            # Проверяем, было ли уже отправлено сообщение этому пользователю
            if sender_id in last_sent:
                # Проверяем, прошло ли 15 секунд с последнего отправления
                if time.time() - last_sent[sender_id] < 15:
                    return

            # Проверяем, прошло ли 15 секунд с момента последнего сообщения почтальона
            if time.time() - last_postman_sent_time[0] < 15:
                return

            # Лог входящего сообщения
            current_time = datetime.now().strftime("%H:%M")  # Получаем текущее время в формате ЧЧ:ММ

            # Форматирование сообщения для группы
            formatted_message_group = (
                f"\n-------------------------\n"
                f"{nickname} | {current_time}\n"
                f"-------------------------\n\n\n"
                f"\n{message_text}\n\n\n\n"
                f"-------------------------\n"
                f"@luxurydynasty\n"
                f"-------------------------\n"
            )

            # Форматирование сообщения для личных сообщений
            formatted_message_private = (
                f"\n-------------------------\n"
                f"{nickname} | {current_time}\n"
                f"-------------------------\n\n\n"
                f"\n{message_text}\n\n\n\n"
                f"-------------------------\n"
                f"{sender_username}\n"
                f"-------------------------\n"
            )

            print(formatted_message_group)

            # Почтальон отправляет сообщение в группу
            if group_id:
                await postman_client.send_message(group_id, formatted_message_group)

            # Почтальон отправляет сообщение в личные сообщения
            # Используем централизованную систему переподключения для почтальона
            postman_session_name = f"postman_{id(postman_client)}"
            if not await ensure_client_connected(postman_client, postman_session_name):
                print("Не удалось переподключить почтальона. Пропускаем отправку.")
                return
            try:
                await postman_client.send_message(private_recipient, formatted_message_private)
            except Exception as e:
                print(f"Не удалось отправить личное сообщение {private_recipient}: {e}")

            # Обновляем статистику входящих сообщений
            # Находим user_id по клиенту для обновления статистики
            user_id_for_stats = None
            for uid, clients_dict in active_clients.items():
                for sess_name, cl in clients_dict.items():
                    if cl == client:
                        user_id_for_stats = uid
                        break
                if user_id_for_stats:
                    break
            
            if user_id_for_stats:
                increment_user_stat(user_id_for_stats, "received_messages", 1)
                # Логируем получение сообщения почтой
                log_mailbox_activity(user_id_for_stats, "message_received", increment=1)
            
            # Обновляем время последнего отправленного сообщения
            last_sent[sender_id] = time.time()
            last_postman_sent_time[0] = time.time()  # Обновляем значение в списке

        except Exception as e:
            print(f"Ошибка при обработке сообщения: {e}")

    # Находим user_id и session_name для централизованного управления
    user_id = None
    session_name = selected_account.get('name')
    
    # Находим user_id по клиенту
    for uid, clients_dict in active_clients.items():
        for sess_name, cl in clients_dict.items():
            if cl == client:
                user_id = uid
                break
        if user_id:
            break
    
    # Добавляем обработчик через централизованное управление
    if user_id and session_name:
        await add_event_handler(user_id, session_name, events.NewMessage, message_handler)
    
    # Ждем сигнала остановки
    while True:
        if stop_event and stop_event.is_set():
            print(f"Получен сигнал остановки mailboxer для {nickname}")
            break
        
        try:
            # Используем централизованную систему переподключения
            if not await ensure_client_connected(client, session_name, user_id):
                await asyncio.sleep(10)
                continue
            
            # Ждем немного перед следующей проверкой
            await asyncio.sleep(1)
            
        except Exception as e:
            print(f"Ошибка в обработке сообщений для {nickname}: {e}")
            await asyncio.sleep(10)
    
    # Удаляем обработчик при завершении
    if user_id and session_name:
        await remove_event_handlers(user_id, session_name)
    
    print(f"Mailboxer завершил работу для {nickname}.")
async def run_autoresponder(user_id, selected_accounts):
    """Запуск автоответчика для выбранных аккаунтов"""
    try:
        if not is_license_valid(user_id):
            await handle_access_expired(user_id)
            return
        # Логируем запуск автоответчика
        log_autoresponder_activity(user_id, "launch")
        
        # Инициализируем состояние автоответчика
        if user_id not in autoresponder_states:
            autoresponder_states[user_id] = {}
        
        autoresponder_states[user_id]["active"] = True
        autoresponder_states[user_id]["selected_accounts"] = selected_accounts
        
        # Инициализируем антиспам (теперь инициализация происходит в каждом обработчике)
        
        
        # Загружаем конфигурацию пользователя для получения API ключей
        user_config = load_user_accounts(user_id)
        if not user_config:
            await log_to_telegram(user_id, "❌ Конфигурация пользователя не найдена", "autoresponder")
            return
        
        # Получаем API ключи из конфигурации пользователя
        user_dir = get_user_dir(user_id)
        config_path = os.path.join(user_dir, "config.json")
        if not os.path.exists(config_path):
            await log_to_telegram(user_id, "❌ Файл конфигурации не найден", "autoresponder")
            return
        
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            api_id = config.get("api_id")
            api_hash = config.get("api_hash")
            
            if not api_id or not api_hash:
                await log_to_telegram(user_id, "❌ API ключи не найдены в конфигурации", "autoresponder")
                return
        except Exception as e:
            await log_to_telegram(user_id, f"❌ Ошибка чтения конфигурации: {e}", "autoresponder")
            return
        
        # Получаем все аккаунты пользователя
        all_accounts = get_active_accounts_by_sessions(user_id)
        
        # Фильтруем аккаунты
        accounts_to_use = []
        for acc in all_accounts:
            if isinstance(acc, dict) and acc.get("phone") in selected_accounts:
                accounts_to_use.append(acc)
        
        # Запускаем автоответчик для каждого аккаунта
        tasks = []
        for account in accounts_to_use:
            task = asyncio.create_task(
                run_autoresponder_for_account(user_id, account, api_id, api_hash)
            )
            tasks.append(task)
        
        # Ждем завершения всех задач
        await asyncio.gather(*tasks, return_exceptions=True)
        
    except Exception as e:
        await log_to_telegram(user_id, f"❌ Ошибка в автоответчике: {e}", "autoresponder")
        # При ошибке сохраняем состояние с active = False, но сохраняем selected_accounts
        if user_id in autoresponder_states:
            autoresponder_states[user_id]["active"] = False
            # Сохраняем состояние с selected_accounts, но active = False
            update_service_state("autoresponder_states", user_id, autoresponder_states[user_id])
    finally:
        # В finally блоке НЕ очищаем состояние, так как это может быть нормальное завершение
        # Состояние будет очищено только в stop_autoresponder при явной остановке пользователем
        pass

async def run_autoresponder_for_account(user_id, account, api_id, api_hash):
    """Запуск автоответчика для одного аккаунта"""
    
    if not isinstance(account, dict):
        await log_to_telegram(user_id, f"❌ Ошибка: account не является словарем: {account}", "autoresponder")
        return
    
    phone = account.get("phone")
    session_name = account.get("name")  # Используем name как session_name
    nickname = account.get("username") or session_name or phone
    
    try:
        # Получаем или создаем клиент
        client = await get_or_create_client(user_id, session_name, api_id, api_hash)
        if not client:
            await log_to_telegram(user_id, f"❌ Не удалось подключить аккаунт {nickname}", "autoresponder")
            return
        
        # Используем централизованную систему переподключения
        if not await ensure_client_connected(client, session_name, user_id):
            await log_to_telegram(user_id, f"❌ Не удалось обеспечить подключение аккаунта {nickname}", "autoresponder")
            return
        
        # Получаем шаблон для этого аккаунта
        template = get_autoresponder_template(user_id, phone)
        if not template:
            await log_to_telegram(user_id, f"⚠️ Шаблон не найден для {nickname}", "autoresponder")
            return
        
        # Создаем обработчик входящих сообщений
        async def autoresponder_handler(event):
            try:
                # Проверяем, активен ли автоответчик
                if not autoresponder_states.get(user_id, {}).get("active", False):
                    return
                
                # Игнорируем исходящие сообщения
                if event.out:
                    return
                
                # ВАЖНО: Отвечаем ТОЛЬКО на личные сообщения!
                if not event.is_private:
                    # Логируем игнорируемые сообщения для отладки
                    chat_type = "группа/канал"
                    if hasattr(event, 'chat_id') and hasattr(event, 'sender_id'):
                        if event.chat_id != event.sender_id:
                            chat_type = "группа/канал"
                        else:
                            chat_type = "личный чат"
                    #await log_to_telegram(user_id, f"🔍 Игнорируем сообщение из {chat_type} (не личное)", "autoresponder")
                    return
                
                # Дополнительная проверка: убеждаемся, что это личный чат
                if hasattr(event, 'chat_id') and hasattr(event, 'sender_id'):
                    if event.chat_id != event.sender_id:
                       #await log_to_telegram(user_id, f"🔍 Игнорируем сообщение из группы/канала (chat_id != sender_id)", "autoresponder")
                        return  # Это не личный чат
                
                # Получаем отправителя
                sender = await event.get_sender()
                if not sender:
                    return
                
                # Игнорируем ботов и каналы
                if sender.bot or hasattr(sender, 'broadcast'):
                    return
                
                # Проверяем, что это обычный пользователь
                if not hasattr(sender, 'id'):
                    return
                
                sender_id = sender.id
                current_time = time.time()
                
                # Антиспам: проверяем, отвечали ли мы этому пользователю недавно с этого аккаунта
                if user_id not in autoresponder_last_response:
                    autoresponder_last_response[user_id] = {}
                if phone not in autoresponder_last_response[user_id]:
                    autoresponder_last_response[user_id][phone] = {}
                
                last_response_time = autoresponder_last_response[user_id][phone].get(sender_id, 0)
                if current_time - last_response_time < 10:  # 10 секунд антиспам
                    return
                
                # Дополнительная проверка активности перед отправкой
                if not autoresponder_states.get(user_id, {}).get("active", False):
                    return
                
                # Отправляем автоответ
                await event.reply(template)
                
                # Обновляем статистику автоответчика
                increment_user_stat(user_id, "autoresponder_messages", 1)
                # Логируем отправку автоответа
                log_autoresponder_activity(user_id, "message_responded", increment=1)
                
                # Обновляем время последнего ответа для этого аккаунта
                autoresponder_last_response[user_id][phone][sender_id] = current_time
                
                # Логируем
                sender_name = getattr(sender, 'username', None) or getattr(sender, 'first_name', 'Неизвестно')
                #await log_to_telegram(user_id, f"📤 Автоответ отправлен пользователю {sender_name} с аккаунта {nickname}", "autoresponder")
                
            except Exception as e:
                await log_to_telegram(user_id, f"❌ Ошибка автоответа для {nickname}: {e}", "autoresponder")
        
        # Добавляем обработчик
        await add_event_handler(user_id, session_name, events.NewMessage, autoresponder_handler)
        
        # Ждем пока автоответчик активен
        while autoresponder_states.get(user_id, {}).get("active", False):
            # Проверка истечения подписки/триала во время работы
            if not is_license_valid(user_id):
                await handle_access_expired(user_id)
                break
            # Используем централизованную систему переподключения
            if not await ensure_client_connected(client, session_name, user_id):
                await asyncio.sleep(10)
                continue
            
            await asyncio.sleep(1)
        
        # Удаляем обработчик при завершении
        await remove_event_handlers(user_id, session_name)
        #await log_to_telegram(user_id, f"🛑 Автоответчик остановлен для {nickname}", "autoresponder")
        
    except Exception as e:
        await log_to_telegram(user_id, f"❌ Критическая ошибка автоответчика для {nickname}: {e}", "autoresponder")

async def stop_autoresponder(user_id):
    """Остановка автоответчика"""
    try:
        # Состояние уже обновлено в обработчике autoresponder_stop
        # Даём обработчикам возможность завершиться, но не блокируем UI (минимальная задержка)
        await asyncio.sleep(0)
        
        # Останавливаем задачу автоответчика
        await stop_task(user_id, "autoresponder")
        
        #await log_to_telegram(user_id, "🛑 Автоответчик остановлен", "autoresponder")
        
    except Exception as e:
        await log_to_telegram(user_id, f"❌ Ошибка при остановке автоответчика: {e}", "autoresponder")

async def handle_custom_folder_selection(call, user_id, folder_name):
    """Обработчик выбора папки в режиме custom"""
    if user_id not in mailing_states:
        await call.answer("Ошибка: состояние рассылки не найдено.", show_alert=True)
        return
    
    state = mailing_states[user_id]
    selected_phones = state.get("selected_accounts", [])
    current_index = state.get("current_account_index", 0)
    
    if current_index >= len(selected_phones):
        await call.answer("Ошибка: неверный индекс аккаунта.", show_alert=True)
        return
    
    # Получаем полные объекты аккаунтов по номерам телефонов
    all_accounts = load_user_accounts(user_id)
    selected_accounts = [acc for acc in all_accounts if acc.get("phone") in selected_phones]
    
    if current_index >= len(selected_accounts):
        await call.answer("Ошибка: неверный индекс аккаунта.", show_alert=True)
        return
    
    # Сохраняем выбор папки для текущего аккаунта
    current_account = selected_accounts[current_index]
    account_phone = current_account.get("phone")
    # Если выбор сделан по индексу (IDX_n), пытаемся сохранить и человекочитаемое имя
    if isinstance(folder_name, str) and folder_name.startswith("IDX_"):
        try:
            idx = int(folder_name.replace("IDX_", ""))
        except ValueError:
            idx = 0
        folder_title = None
        try:
            folders = state.get("last_folder_list", {})
            # last_folder_list имеет ключи 1..N; idx 0-базовый
            if folders and (idx + 1) in folders:
                folder_title = folders[idx + 1].get('title')
        except Exception:
            folder_title = None
        # Сохраняем IDX_n, но параллельно кладём читабельное имя рядом
        state["account_folders"][account_phone] = folder_name
        if folder_title:
            if "account_folder_titles" not in state:
                state["account_folder_titles"] = {}
            state["account_folder_titles"][account_phone] = folder_title
    else:
        state["account_folders"][account_phone] = folder_name
    
    # Переходим к следующему аккаунту или к логированию
    current_index += 1
    state["current_account_index"] = current_index
    
    if current_index < len(selected_accounts):
        # Есть еще аккаунты для настройки
        next_account = selected_accounts[current_index]
        account_nickname = next_account.get("username") or next_account.get("name") or next_account.get("phone")

        # Динамический список шаблонов для следующего аккаунта
        templates = get_templates_from_config(load_config(user_id), next_account.get('phone'))

        markup = InlineKeyboardMarkup(inline_keyboard=[])
        if templates:
            for idx, t in enumerate(templates):
                markup.inline_keyboard.append([
                    InlineKeyboardButton(text=truncate_preview(t), callback_data=f"custom_template_idx_{idx}")
                ])
        else:
            template1 = next_account.get("template1", "...")
            template2 = next_account.get("template2", "...")
            markup.inline_keyboard.append([InlineKeyboardButton(text=truncate_preview(template1), callback_data="custom_template_idx_0")])
            markup.inline_keyboard.append([InlineKeyboardButton(text=truncate_preview(template2), callback_data="custom_template_idx_1")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="mailing_mode_custom")])
        
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                f"Выберите текстовое сообщение для аккаунта {account_nickname}:",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise
    else:
        # Все аккаунты настроены, переходим к логированию
        state["step"] = "select_logging"
        
        markup = InlineKeyboardMarkup(inline_keyboard=[])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Да", callback_data="mailing_logging_yes")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Нет", callback_data="mailing_logging_no")])
        markup.inline_keyboard.append([InlineKeyboardButton(text="Вернуться 🔙", callback_data="mailing_mode_custom")])
        
        try:
            await delete_and_send_image(
                call.message,
                "mailing.png",
                "Добавить логирование статусов отправки сообщений?",
                reply_markup=markup,
                user_id=user_id
            )
        except TelegramAPIError as e:
            if "message is not modified" not in str(e):
                raise


async def run_mailboxer(user_id, license_type, selected_accounts, postman_account, group_id, notify_username, stop_event=None):
    """
    Основная функция для запуска mailboxer как фонового процесса из бота.
    Использует централизованное управление клиентами для избежания блокировок .session файлов.
    """
    print("Mailboxer стартовал")
    clients = []
    postman_client = None
    tasks = []
    try:
        # Логируем запуск почты
        log_mailbox_activity(user_id, "launch")
        
        # Инициализируем состояние почты
        if user_id not in postman_states:
            postman_states[user_id] = {}
        
        postman_states[user_id]["active"] = True
        postman_states[user_id]["selected_accounts"] = [acc.get("phone") for acc in selected_accounts]
        postman_states[user_id]["selected_postman"] = postman_account.get("phone")
        postman_states[user_id]["notify_username"] = notify_username
        
        # Сохраняем состояние в файл
        update_service_state("postman_states", user_id, postman_states[user_id])
        
        # Получаем api_id и api_hash из config.json
        user_dir = get_user_dir(user_id, license_type)
        config_path = os.path.join(user_dir, "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        api_id = config.get("api_id")
        api_hash = config.get("api_hash")
        
        # Используем централизованное управление клиентами
        print(f"🔍 Создание клиентов для {len(selected_accounts)} аккаунтов...")
        for acc in selected_accounts:
            session_name = acc["name"]
            print(f"🔍 Создание клиента для {session_name} ({acc.get('phone')})...")
            client = await get_or_create_client(user_id, session_name, api_id, api_hash, license_type)
            if client is None:
                print(f"❌ Аккаунт {session_name} не авторизован или сессия повреждена. Пропуск.")
                continue
            print(f"✅ Клиент для {session_name} создан успешно")
            
            # Получаем информацию о пользователе
            try:
                me = await client.get_me()
                acc['nickname'] = me.username or me.first_name or me.phone or acc.get('name') or acc.get('phone')
            except Exception as e:
                print(f"Ошибка получения информации о пользователе {session_name}: {e}")
                acc['nickname'] = acc.get('name') or acc.get('phone')
            
            clients.append((client, acc))

        # Получаем или создаем клиента-почтальона
        postman_session_name = postman_account["name"]
        postman_client = await get_or_create_client(user_id, postman_session_name, api_id, api_hash, license_type)
        if postman_client is None:
            print(f"Почтальон {postman_session_name} не авторизован. Mailboxer не может работать.")
            return

        # Запускаем обработку сообщений для всех клиентов
        tasks = []
        for client, acc in clients:
            task = asyncio.create_task(
                handle_incoming_messages(client, postman_client, group_id, acc, stop_event, notify_username)
            )
            tasks.append(task)
        
        # Ждем завершения всех задач или сигнала остановки
        try:
            # Проверяем stop_event каждую секунду
            while stop_event is None or not stop_event.is_set():
                # Проверка истечения подписки/триала во время работы
                if not is_license_valid(user_id):
                    await handle_access_expired(user_id)
                    break
                # Проверяем, завершились ли все задачи
                done_tasks = [task for task in tasks if task.done()]
                if len(done_tasks) == len(tasks):
                    break
                
                # Ждем 1 секунду перед следующей проверкой
                await asyncio.sleep(1)
                
        except Exception as e:
            print(f"Ошибка в mailboxer: {e}")
        
        # Мягко завершаем: подаём сигнал остановки и ждём задачи
        if stop_event is not None:
            stop_event.set()
        # Ждём завершения задач с таймаутом
        try:
            await asyncio.wait(tasks, timeout=5)
        except Exception:
            pass
        # Отменяем оставшиеся
        for task in tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
    except Exception as e:
        print("Mailboxer завершён по ошибке", e)
    finally:
        # Завершаем состояние почты только если это не автовосстановление
        if user_id in postman_states:
            # Проверяем, не является ли это автовосстановлением
            # Если состояние было восстановлено из файла, не удаляем его
            if not postman_states[user_id].get("_restored", False):
                postman_states[user_id]["active"] = False
                # Безопасно обновляем состояние в файле
                update_service_state("postman_states", user_id, None)
            else:
                # Убираем флаг восстановления
                postman_states[user_id].pop("_restored", None)
        # Аккуратно отключаем всех клиентов, чтобы не оставлять фоновых задач Telethon
        try:
            for client, _acc in clients or []:
                try:
                    await client.disconnect()
                except Exception:
                    pass
            if postman_client is not None:
                try:
                    await postman_client.disconnect()
                except Exception:
                    pass
        except Exception:
            pass
        print("Mailboxer завершился")

# Новые функции для работы с настройками пользователя (settings.json)

def get_user_settings_file_path(user_id, license_type=None):
    """Путь к файлу settings.json пользователя"""
    if license_type is None:
        license_type = user_states.get(f"{user_id}_license_type")
        # НЕ определяем тип лицензии автоматически - это должно происходить только при выборе лицензии
        # if not license_type:
        #     license_type = detect_license_type(user_id)
        #     if license_type:
        #         user_states[f"{user_id}_license_type"] = license_type
    user_dir = get_user_dir(user_id, license_type, create_dir=False)
    return os.path.join(user_dir, "settings.json")

def load_user_settings(user_id, license_type=None):
    """Загружает settings.json пользователя. Возвращает dict. Поддерживает legacy language.json (language only)."""
    if license_type is None:
        license_type = user_states.get(f"{user_id}_license_type")
        # НЕ определяем тип лицензии автоматически - это должно происходить только при выборе лицензии
        # if not license_type:
        #     license_type = detect_license_type(user_id)
        #     if license_type:
        #         user_states[f"{user_id}_license_type"] = license_type
    
    try:
        settings_file = get_user_settings_file_path(user_id, license_type)
        if os.path.exists(settings_file):
            with open(settings_file, "r", encoding="utf-8") as f:
                return json.load(f)
        # Legacy поддержка языка
        legacy_language_file = os.path.join(os.path.dirname(settings_file), "language.json")
        if os.path.exists(legacy_language_file):
            with open(legacy_language_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {"language": data.get("language", "ru")}
    except Exception:
        pass
    return {}

def update_user_settings(user_id, updates: dict, license_type=None):
    """Обновляет (merge) настройки пользователя в settings.json."""
    if license_type is None:
        license_type = user_states.get(f"{user_id}_license_type")
        # НЕ определяем тип лицензии автоматически - это должно происходить только при выборе лицензии
        # if not license_type:
        #     license_type = detect_license_type(user_id)
        #     if license_type:
        #         user_states[f"{user_id}_license_type"] = license_type
    
    try:
        settings_file = get_user_settings_file_path(user_id, license_type)
        os.makedirs(os.path.dirname(settings_file), exist_ok=True)
        current = {}
        if os.path.exists(settings_file):
            try:
                with open(settings_file, "r", encoding="utf-8") as f:
                    current = json.load(f) or {}
            except Exception:
                current = {}
        current.update(updates or {})
        with open(settings_file, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Ошибка сохранения settings.json для пользователя {user_id}: {e}")
        return False

# ---- Autosubscribe limit in settings.json ----
def get_user_autosub_limit(user_id) -> int:
    try:
        settings = load_user_settings(user_id)
        value = settings.get("autosubscribe_limit", 0)
        # Робастный парсинг числа из settings.json
        try:
            if isinstance(value, (int, float)):
                return int(value)
            if isinstance(value, str):
                s = value.strip()
                import re as _re
                m = _re.search(r"-?\d+", s)
                return int(m.group(0)) if m else 0
            return 0
        except Exception:
            return 0
    except Exception:
        return 0

def increment_user_autosub_limit(user_id, increment_by: int = 1) -> int:
    try:
        current = get_user_autosub_limit(user_id)
        safe_increment = int(increment_by)
        # Жёсткий потолок 5/5 для trial
        try:
            license_type = detect_license_type(user_id)
        except Exception:
            license_type = None
        if (str(license_type).endswith("trial") or str(license_type) == "trial") and current >= 5:
            return 5
        new_value = max(0, int(current) + safe_increment)
        if str(license_type).endswith("trial") or str(license_type) == "trial":
            new_value = min(5, new_value)
        update_user_settings(user_id, {"autosubscribe_limit": new_value})
        # Дублируем счетчик в freetrial.json для устойчивости при ре-логине
        try:
            if str(license_type).endswith("trial") or str(license_type) == "trial":
                ft = load_freetrial()
                rec = ft.get(str(user_id)) or {}
                rec["autosubscribe_limit"] = new_value
                ft[str(user_id)] = rec
                save_freetrial(ft)
        except Exception:
            pass
        return new_value
    except Exception:
        return get_user_autosub_limit(user_id)

def get_user_reconnect_file_path(user_id, license_type=None):
    """Получает путь к файлу reconnect_state.json для пользователя"""
    if license_type is None:
        license_type = user_states.get(f"{user_id}_license_type")
        # Автоматически определяем тип лицензии по существующим папкам
        if not license_type:
            license_type = detect_license_type(user_id)
            if license_type:
                user_states[f"{user_id}_license_type"] = license_type
    
    user_dir = get_user_dir(user_id, license_type, create_dir=False)
    return os.path.join(user_dir, "reconnect_state.json")

def save_user_language_individual(user_id, language, license_type=None):
    """Совместимость: сохраняет язык через settings.json"""
    if license_type is None:
        license_type = user_states.get(f"{user_id}_license_type")
        # Автоматически определяем тип лицензии по существующим папкам
        if not license_type:
            license_type = detect_license_type(user_id)
            if license_type:
                user_states[f"{user_id}_license_type"] = license_type
    
    return update_user_settings(user_id, {"language": language}, license_type)

def load_user_language_individual(user_id, license_type=None):
    """Совместимость: читает язык из settings.json (или из глобали при ошибке)."""
    if license_type is None:
        license_type = user_states.get(f"{user_id}_license_type")
        # Автоматически определяем тип лицензии по существующим папкам
        if not license_type:
            license_type = detect_license_type(user_id)
            if license_type:
                user_states[f"{user_id}_license_type"] = license_type
    
    settings = load_user_settings(user_id, license_type)
    return settings.get("language", user_languages.get(user_id, "ru"))

def save_user_reconnect_state_individual(user_id, state_data, license_type=None):
    """Сохраняет состояние reconnect для пользователя в индивидуальный файл"""
    if license_type is None:
        license_type = user_states.get(f"{user_id}_license_type")
        # Автоматически определяем тип лицензии по существующим папкам
        if not license_type:
            license_type = detect_license_type(user_id)
            if license_type:
                user_states[f"{user_id}_license_type"] = license_type
    
    try:
        reconnect_file = get_user_reconnect_file_path(user_id, license_type)
        
        # Создаем директорию если её нет
        os.makedirs(os.path.dirname(reconnect_file), exist_ok=True)
        
        # Сохраняем в правильную папку
        with open(reconnect_file, "w", encoding="utf-8") as f:
            json.dump(state_data, f, ensure_ascii=False, indent=2)
        
        # Удаляем старый файл из папки без суффикса, если он существует
        if license_type:
            root = get_project_root()
            user_base_dir = os.path.join(root, "user")
            old_reconnect_file = os.path.join(user_base_dir, str(user_id), "reconnect_state.json")
            
            if os.path.exists(old_reconnect_file):
                try:
                    os.remove(old_reconnect_file)
                    print(f"✅ Удален старый файл reconnect_state.json: {old_reconnect_file}")
                except Exception as e:
                    print(f"⚠️ Не удалось удалить старый файл: {e}")
        
        return True
    except Exception as e:
        print(f"Ошибка сохранения reconnect_state.json для пользователя {user_id}: {e}")
        return False

def load_user_reconnect_state_individual(user_id, license_type=None):
    """Загружает состояние reconnect для пользователя из индивидуального файла"""
    if license_type is None:
        license_type = user_states.get(f"{user_id}_license_type")
        # Автоматически определяем тип лицензии по существующим папкам
        if not license_type:
            license_type = detect_license_type(user_id)
            if license_type:
                user_states[f"{user_id}_license_type"] = license_type
    
    try:
        # Сначала пытаемся загрузить из правильной папки с суффиксом
        reconnect_file = get_user_reconnect_file_path(user_id, license_type)
        
        if os.path.exists(reconnect_file):
            with open(reconnect_file, "r", encoding="utf-8") as f:
                return json.load(f)
        
        # Если файл не найден в правильной папке, ищем в папке без суффикса
        if license_type:
            root = get_project_root()
            user_base_dir = os.path.join(root, "user")
            old_reconnect_file = os.path.join(user_base_dir, str(user_id), "reconnect_state.json")
            
            if os.path.exists(old_reconnect_file):
                print(f"🔄 Найден файл reconnect_state.json в старой папке, переносим в правильную...")
                
                # Загружаем данные из старого файла
                with open(old_reconnect_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                # Сохраняем в правильную папку
                save_user_reconnect_state_individual(user_id, data, license_type)
                
                # Удаляем старый файл
                try:
                    os.remove(old_reconnect_file)
                    print(f"✅ Старый файл reconnect_state.json удален: {old_reconnect_file}")
                except Exception as e:
                    print(f"⚠️ Не удалось удалить старый файл: {e}")
                
                return data
                
    except Exception as e:
        print(f"Ошибка загрузки reconnect_state.json для пользователя {user_id}: {e}")
    
    return None

# ==================== СИСТЕМА PUSH-УВЕДОМЛЕНИЙ ====================

def load_notifications():
    """Загружает настройки уведомлений из notifications.json"""
    try:
        with open("notifications.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ Ошибка загрузки notifications.json: {e}")
        return {"notifications": []}

def save_notifications(notifications_data):
    """Сохраняет настройки уведомлений в notifications.json"""
    try:
        with open("notifications.json", "w", encoding="utf-8") as f:
            json.dump(notifications_data, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        print(f"❌ Ошибка сохранения notifications.json: {e}")
        return False

def get_user_saved_hours(user_id):
    """Получает количество сэкономленного времени в формате 'X часов Y минут' с правильным склонением"""
    try:
        # Получаем тип лицензии пользователя из папки
        user_license_type = None
        user_dir = "user"
        if os.path.exists(user_dir):
            for folder in os.listdir(user_dir):
                if folder.startswith(f"{user_id}_"):
                    user_license_type = folder.split("_")[1]
                    break
        
        # Если не нашли в папке, пробуем из user_states
        if not user_license_type:
            user_license_type = user_states.get(f"{user_id}_license_type")
            if not user_license_type:
                user_license_type = detect_license_type(user_id)
        
        # Загружаем данные о счетчике сообщений
        count_file = f"user/{user_id}_{user_license_type}/count.json"
        total_seconds = 0
        if os.path.exists(count_file):
            with open(count_file, "r", encoding="utf-8") as f:
                count_data = json.load(f)
                
            # Рассчитываем сэкономленное время на основе активности
            sent_messages = count_data.get("sent_messages", 0)
            received_messages = count_data.get("received_messages", 0)
            autoresponder_messages = count_data.get("autoresponder_messages", 0)
            
            # Формула: только отправленные сообщения (рассылка) = 10 секунд каждое
            total_seconds = sent_messages * 10  # 10 секунд на отправленное сообщение
            
        # Конвертируем в часы и минуты
        saved_hours = total_seconds // 3600
        saved_minutes = (total_seconds % 3600) // 60
        
        # Функция для правильного склонения
        def pluralize_hours(hours: int) -> str:
            n = abs(int(hours))
            if 11 <= (n % 100) <= 14:
                return "часов"
            last = n % 10
            if last == 1:
                return "час"
            if 2 <= last <= 4:
                return "часа"
            return "часов"

        def pluralize_minutes(minutes: int) -> str:
            n = abs(int(minutes))
            if 11 <= (n % 100) <= 14:
                return "минут"
            last = n % 10
            if last == 1:
                return "минута"
            if 2 <= last <= 4:
                return "минуты"
            return "минут"
        
        # Если меньше часа, показываем только минуты
        if saved_hours == 0:
            return f"{saved_minutes} {pluralize_minutes(saved_minutes)}"
        else:
            return f"{saved_hours} {pluralize_hours(saved_hours)} {saved_minutes} {pluralize_minutes(saved_minutes)}"
        
    except Exception as e:
        print(f"❌ Ошибка получения saved_hours для пользователя {user_id}: {e}")
        return "0 минут"

def get_user_days_left(user_id):
    """Получает оставшееся время до окончания лицензии в формате 'X дней Y часов' с правильным склонением"""
    try:
        # Функция для правильного склонения дней
        def pluralize_days(days: int) -> str:
            n = abs(int(days))
            if 11 <= (n % 100) <= 14:
                return "дней"
            last = n % 10
            if last == 1:
                return "день"
            if 2 <= last <= 4:
                return "дня"
            return "дней"
        
        # Функция для правильного склонения часов
        def pluralize_hours(hours: int) -> str:
            n = abs(int(hours))
            if 11 <= (n % 100) <= 14:
                return "часов"
            last = n % 10
            if last == 1:
                return "час"
            if 2 <= last <= 4:
                return "часа"
            return "часов"
        
        # Функция для правильного склонения минут
        def pluralize_minutes(minutes: int) -> str:
            n = abs(int(minutes))
            if 11 <= (n % 100) <= 14:
                return "минут"
            last = n % 10
            if last == 1:
                return "минута"
            if 2 <= last <= 4:
                return "минуты"
            return "минут"
        
        # Сначала проверяем Free Trial (приоритет для пользователей с пробным периодом)
        try:
            with open("freetrial.json", "r", encoding="utf-8") as f:
                freetrial_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            freetrial_data = {}
        
        if str(user_id) in freetrial_data:
            trial_data = freetrial_data[str(user_id)]
            activated_at = trial_data.get("activated_at", 0)
            
            # Trial длится 24 часа
            trial_end = activated_at + (24 * 3600)  # 24 часа в секундах
            current_time = int(time.time())
            time_left = trial_end - current_time
            
            if time_left <= 0:
                return "0 дней 0 часов"
            
            # Для Free Trial показываем только часы и минуты (без дней)
            hours_left = int(time_left // 3600)
            minutes_left = int((time_left % 3600) // 60)
            
            if hours_left == 0:
                return f"{minutes_left} {pluralize_minutes(minutes_left)}"
            else:
                return f"{hours_left} {pluralize_hours(hours_left)} {minutes_left} {pluralize_minutes(minutes_left)}"
        
        # Если пользователь не в Free Trial, проверяем платную лицензию
        try:
            with open(LICENSE_FILE, "r", encoding="utf-8") as f:
                licenses = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            licenses = {}
        
        if str(user_id) in licenses:
            license_data = licenses[str(user_id)]
            # Некоторые записи могут не иметь end_date — рассчитываем по activated_at + LICENSE_DURATION_DAYS
            end_dt = None
            try:
                if "end_date" in license_data:
                    end_dt = datetime.fromisoformat(license_data["end_date"].replace("Z", "+00:00"))
            except Exception:
                end_dt = None
            
            if end_dt is None:
                activated_at_ts = int(license_data.get("activated_at", 0))
                if activated_at_ts > 0:
                    # Учитываем бонус за реферальный код (+72 часа), если активирован раньше
                    end_ts = activated_at_ts + LICENSE_DURATION_DAYS * 24 * 3600 + get_referral_bonus_seconds(user_id)
                    end_dt = datetime.fromtimestamp(end_ts, tz=timezone.utc)
                else:
                    return "0 дней 0 часов"
            
            if end_dt is not None:
                current_date = datetime.now(timezone.utc)
                time_diff = end_dt - current_date
                if time_diff.total_seconds() <= 0:
                    return "0 дней 0 часов"
                total_days = int(time_diff.total_seconds() // (24 * 3600))
                remaining_hours = int((time_diff.total_seconds() % (24 * 3600)) // 3600)
                return f"{total_days} {pluralize_days(total_days)} {remaining_hours} {pluralize_hours(remaining_hours)}"
        
        return "0 дней 0 часов"
        
    except Exception as e:
        print(f"❌ Ошибка получения days_left для пользователя {user_id}: {e}")
        return "0 дней 0 часов"

def personalize_message(message, user_id):
    """Заменяет переменные в сообщении на персональные данные пользователя"""
    try:
        # Заменяем {saved_hours} на сэкономленное время в часах и минутах
        if "{saved_hours}" in message:
            saved_hours = get_user_saved_hours(user_id)
            message = message.replace("{saved_hours}", saved_hours)
        
        # Заменяем {days_left} на оставшееся время в днях и часах
        if "{days_left}" in message:
            days_left = get_user_days_left(user_id)
            message = message.replace("{days_left}", days_left)
        
        return message
        
    except Exception as e:
        print(f"❌ Ошибка персонализации сообщения: {e}")
        return message

def should_send_notification(template, user_id):
    """Проверяет, нужно ли отправлять уведомление пользователю"""
    try:
        # Проверяем target_audience
        target_audience = template.get("target_audience", "all")
        if target_audience != "all":
            # Получаем тип лицензии пользователя из папки
            user_license_type = None
            user_dir = "user"
            if os.path.exists(user_dir):
                for folder in os.listdir(user_dir):
                    if folder.startswith(f"{user_id}_"):
                        user_license_type = folder.split("_")[1]
                        break
            
            if not user_license_type:
                # Пытаемся определить из user_states
                user_license_type = user_states.get(f"{user_id}_license_type")
                if not user_license_type:
                    user_license_type = detect_license_type(user_id)
            
            if user_license_type and user_license_type not in target_audience.split(", "):
                print(f"❌ Пользователь {user_id} не в целевой аудитории: {user_license_type} vs {target_audience}")
                return False
        
        print(f"✅ Пользователь {user_id} подходит для отправки уведомления")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка проверки отправки уведомления: {e}")
        return False

async def send_push_notification(user_id, template):
    """Отправляет push-уведомление пользователю"""
    try:
        print(f"📤 Попытка отправки уведомления пользователю {user_id}")
        print(f"📝 Текст: {template['message']}")
        
        # Персонализируем сообщение
        personalized_message = personalize_message(template["message"], user_id)
        print(f"📝 Персонализированный текст: {personalized_message}")
        
        # Создаем клавиатуру с кнопками, если они есть
        keyboard = None
        if "buttons" in template and template["buttons"]:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[])
            for button in template["buttons"]:
                keyboard.inline_keyboard.append([
                    InlineKeyboardButton(text=button["text"], url=button["url"])
                ])
        
        # Отправляем сообщение
        if template.get("image") and template["image"] != "null":
            # Отправляем с изображением
            print(f"🖼️ Отправляем с изображением: {template['image']}")
            photo = FSInputFile(template["image"])
            await bot.send_photo(
                chat_id=user_id,
                photo=photo,
                caption=personalized_message,
                reply_markup=keyboard
            )
        else:
            # Отправляем только текст
            print(f"📨 Отправляем текстовое сообщение")
            await bot.send_message(
                chat_id=user_id,
                text=personalized_message,
                reply_markup=keyboard
            )
        
        # Обновляем аналитику
        template["analytics"]["delivered_count"] += 1
        
        print(f"✅ Push-уведомление успешно отправлено пользователю {user_id}")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка отправки push-уведомления пользователю {user_id}: {e}")
        print(f"🔍 Тип ошибки: {type(e).__name__}")
        return False

async def push_notification_scheduler():
    """Планировщик push-уведомлений - работает в фоне и отслеживает изменения"""
    print("🔔 Система push-уведомлений запущена")
    
    # Храним последнее время изменения файла
    last_modified_time = 0
    last_notifications_data = None
    
    while True:
        try:
            # Проверяем, изменился ли файл notifications.json
            current_modified_time = os.path.getmtime("notifications.json")
            
            if current_modified_time > last_modified_time or last_notifications_data is None:
                #print("📝 Обнаружены изменения в notifications.json")
                last_modified_time = current_modified_time
                last_notifications_data = load_notifications()
                
                # Получаем список всех пользователей из папки user/
                all_users = []
                user_dir = "user"
                if os.path.exists(user_dir):
                    for folder in os.listdir(user_dir):
                        if "_" in folder:  # Формат: user_id_license_type
                            user_id = folder.split("_")[0]
                            try:
                                all_users.append(int(user_id))
                            except ValueError:
                                continue
                
                #print(f"📊 Найдено {len(all_users)} пользователей для уведомлений")
                
                # Проверяем каждое уведомление
                for notification_group in last_notifications_data.get("notifications", []):
                    for template_name, template in notification_group.items():
                        if template_name.startswith("template") and template.get("title") != "null":
                            #print(f"🔍 Проверяем шаблон: {template_name}")
                            
                            # Проверяем расписание
                            schedule = template.get("schedule", {})
                            should_send_now = False
                            
                            if schedule.get("random", False):
                                # Случайная отправка
                                period = schedule.get("period", "1-7")
                                if period != "null":
                                    should_send_now = True  # Упрощенно для демонстрации
                            else:
                                # Проверяем конкретную дату
                                target_date = schedule.get("date")
                                if target_date and target_date != "null":
                                    try:
                                        # Парсим дату из формата "13.08.2025, 00:35 GMT+3"
                                        date_str = target_date.split(",")[0]  # "13.08.2025"
                                        time_str = target_date.split(",")[1].split("GMT")[0].strip()  # " 00:35 "
                                        
                                        # Создаем datetime объект
                                        from datetime import datetime
                                        target_datetime = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M")
                                        
                                        # Проверяем, наступило ли время отправки (только в указанную минуту)
                                        current_datetime = datetime.now()
                                        current_minute = current_datetime.strftime('%d.%m.%Y %H:%M')
                                        target_minute = target_datetime.strftime('%d.%m.%Y %H:%M')
                                        
                                        if current_minute == target_minute:
                                            should_send_now = True
                                            #print(f"⏰ Точное время отправки: {target_minute}")
                                        elif current_datetime > target_datetime:
                                            #print(f"⏭️ Время отправки прошло: {target_minute} (текущее: {current_minute})")
                                            pass
                                        else:
                                            #print(f"⏳ Время отправки еще не наступило: {target_minute} (текущее: {current_minute})")
                                            pass
                                        
                                    except Exception as e:
                                        print(f"❌ Ошибка парсинга даты: {e}")
                                        should_send_now = True  # Отправляем при ошибке парсинга
                            
                            if should_send_now:
                                # Проверяем, не было ли уже отправлено это уведомление
                                if not template.get("is_sent", False):
                                    print(f"📤 Начинаем отправку уведомления: {template_name}")
                                    
                                    # Проверяем каждого пользователя
                                    for user_id in all_users:
                                        if should_send_notification(template, user_id):
                                            print(f"📤 Отправляем уведомление пользователю {user_id}")
                                            await send_push_notification(user_id, template)
                                            # Небольшая задержка между отправками
                                            await asyncio.sleep(1)
                                    
                                    # Помечаем уведомление как отправленное
                                    template["is_sent"] = True
                                    print(f"✅ Уведомление {template_name} помечено как отправленное")
                                else:
                                    print(f"⏭️ Уведомление {template_name} уже было отправлено ранее")
                
                # Сохраняем обновленные данные
                save_notifications(last_notifications_data)
                #print("✅ Обработка уведомлений завершена")
            
            # Ждем 60 секунд перед следующей проверкой
            await asyncio.sleep(1)
            
        except Exception as e:
            print(f"❌ Ошибка в планировщике push-уведомлений: {e}")
            await asyncio.sleep(60)  # Ждем 1 минуту при ошибке

# ==================== КОНЕЦ СИСТЕМЫ PUSH-УВЕДОМЛЕНИЙ ====================

if __name__ == "__main__":
    print("Бот запущен.")
    
    # Функция для обработки сигналов завершения
    def signal_handler(signum, frame):
        print(f"\nReceived SIGINT signal")
        # Сигнал будет обработан в asyncio.run()
    
    # Регистрируем обработчик сигнала
    import signal
    signal.signal(signal.SIGINT, signal_handler)
    
    # Запускаем централизованный логгер и системы реконнектеров
    async def main():
        # Настраиваем логирование Telethon для подавления ненужных сообщений
        setup_telethon_logging()
        
        print("🚀 Инициализация системы реконнектеров...")
        
        # Проверяем интернет-соединение перед запуском
        print("🌐 Проверка интернет-соединения...")
        try:
            await check_internet_connection()
            print("✅ Интернет-соединение доступно")
        except Exception as e:
            print(f"❌ Ошибка интернет-соединения: {e}")
            print("🔍 Проверьте:")
            print("   - Подключение к интернету")
            print("   - Настройки DNS (попробуйте 8.8.8.8 или 1.1.1.1)")
            print("   - Файрвол/антивирус")
            print("   - VPN (если используется)")
            return
        
        # Восстанавливаем состояния после перезапуска
        load_reconnect_state()
        
        # Загружаем сохраненные языковые настройки пользователей
        global user_languages
        user_languages.update(load_user_languages())
        
        # Запускаем фоновые задачи
        logger_task = asyncio.create_task(telegram_logger())
        auto_save_task = asyncio.create_task(auto_save_states())
        access_guard_task = asyncio.create_task(periodic_access_guard())
        bug_scheduler_task = asyncio.create_task(bug_message_scheduler())
        push_notifications_task = asyncio.create_task(push_notification_scheduler())
        
        print("✅ Система реконнектеров активна")
        print("✅ Автосохранение состояний активно")
        print("✅ Автовосстановление после перезапуска активно")
        print("✅ Планировщик сообщений о багах активен")
        print("✅ Система push-уведомлений активен")
        
        try:
            # Запускаем aiogram бота
            print("🤖 Запуск Telegram бота...")
            await dp.start_polling(bot, skip_updates=True)
        except TelegramConflictError as e:
            print(f"❌ Конфликт сессии Telegram: {e}")
            print("🔍 Возможные причины:")
            print("   - Уже запущен другой экземпляр бота")
            print("   - Telegram API помнит предыдущую сессию")
            print("   - Попробуйте подождать несколько минут и перезапустить")
            print("   - Или перезапустите с другим токеном")
        except TelegramNetworkError as e:
            print(f"❌ Ошибка сети Telegram: {e}")
            print("🔍 Возможные причины:")
            print("   - Проблемы с api.telegram.org")
            print("   - Блокировка Telegram в вашем регионе")
            print("   - Проблемы с DNS")
            print("   - Неверный токен бота")
        except Exception as e:
            print(f"❌ Неожиданная ошибка: {e}")
            print(f"🔍 Тип ошибки: {type(e).__name__}")
        finally:
            print("🔄 Сохранение состояний перед завершением...")
            # Сохраняем состояния перед завершением
            save_reconnect_state()
            save_user_languages()  # Сохраняем языковые настройки
            
            # Останавливаем все задачи автовосстановления
            await stop_all_auto_resume_tasks()
            
            # Останавливаем все активные задачи
            print("🔄 Остановка всех активных задач...")
            for user_id in list(active_tasks.keys()):
                for task_name in list(active_tasks[user_id].keys()):
                    task = active_tasks[user_id][task_name]
                    if not task.done():
                        print(f"🛑 Останавливаем задачу {task_name} для пользователя {user_id}")
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
            
            # Отключаем все клиенты
            print("🔄 Отключение всех клиентов...")
            for user_id in list(active_clients.keys()):
                await disconnect_all_clients(user_id)
            
            # Останавливаем фоновые задачи
            auto_save_task.cancel()
            access_guard_task.cancel()
            bug_scheduler_task.cancel()
            push_notifications_task.cancel()
            await log_queue.put(None)
            
            try:
                await logger_task
                await auto_save_task
                await access_guard_task
                await bug_scheduler_task
                await push_notifications_task
            except asyncio.CancelledError:
                pass
            
            print("✅ Бот корректно завершен")
    
# Запускаем основную функцию
import asyncio
asyncio.run(main())