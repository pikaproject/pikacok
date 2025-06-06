import os
from datetime import datetime, timedelta, timezone
from pyrogram import Client, filters
from pyrogram.types import *
from database import dbname
from misskaty import app

kickdb = dbname["auto_kick"]
COMMAND_PREFIX = os.getenv("PREFIX", ".")
DEFAULT_KICK_TIME_HOURS = int(os.getenv("DEFAULT_KICK_TIME_HOURS", "720"))

@app.on_message(filters.command("auto_kick", prefixes=COMMAND_PREFIX) & filters.group)
async def kick_command(client: Client, message: Message):
    member = await client.get_chat_member(message.chat.id, message.from_user.id)
    is_admin = member.status in ("creator", "administrator")
    if not is_admin:
        await message.reply("You must be a group admin to use this command!")
        return
    args = message.text.split()[1:]
    if len(args) < 1 or len(args) > 2:
        await message.reply(f"Usage: {COMMAND_PREFIX}auto_kick <user_id> [kick_time_in_hours]")
        return
    user_id = args[0]
    kick_time = args[1] if len(args) == 2 else DEFAULT_KICK_TIME_HOURS

    kick_time = int(kick_time)
    kick_datetime = datetime.now(timezone.utc) + timedelta(minutes=kick_time)
    kickdb.insert_one({"chat_id": message.chat.id, "user_id": int(user_id), "kick_time": kick_datetime})

    await message.reply(f"User {user_id} will be kicked in {kick_time} minutes.")


async def check_kicks():
    now = datetime.now(timezone.utc)
    kicks = list(kickdb.find({"kick_time": {"$lte": now}}))
    for kick in kicks:
        chat_id = kick["chat_id"]
        user_id = kick["user_id"]
        try:
            await app.kick_chat_member(chat_id, user_id)
            await app.unban_chat_member(chat_id, user_id)
        except Exception as e:
            print(f"[ERROR] Gagal kick {user_id} dari {chat_id}: {e}")
        finally:
            kickdb.delete_one({"_id": kick["_id"]})