import os
from datetime import datetime, timedelta, timezone
from pyrogram import Client, filters
from pyrogram.types import *
from database import dbname
from misskaty import app

kickdb = dbname["auto_kick"]
COMMAND_PREFIX = os.getenv("PREFIX", ".")
DEFAULT_KICK_TIME_MINUTES = int(os.getenv("DEFAULT_KICK_TIME_HOURS", "1"))

async def kick_command(client: Client, message: Message):
    # Verifikasi admin
    member = await client.get_chat_member(message.chat.id, message.from_user.id)
    if member.status not in ("creator", "administrator"):
        return await message.reply("❌ Kamu harus admin grup untuk pakai perintah ini.")

    args = message.text.split()[1:]

    # Coba ambil target dari reply
    target_user: User = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
    elif args:
        identifier = args[0]
        try:
            # Coba user_id langsung
            user_id = int(identifier)
            target_user = await client.get_users(user_id)
        except ValueError:
            # Kalau bukan angka, coba @username
            try:
                target_user = await client.get_users(identifier)
            except Exception:
                return await message.reply("❌ Tidak bisa menemukan pengguna dari input itu.")
    else:
        return await message.reply(f"Usage:\n`{COMMAND_PREFIX}auto_kick <user_id|@username>` [menit]\nAtau reply ke user.")

    # Cek waktu kick (default atau custom)
    try:
        kick_time = int(args[1]) if len(args) > 1 else DEFAULT_KICK_TIME_MINUTES
    except ValueError:
        return await message.reply("❌ Waktu kick harus berupa angka (dalam menit).")

    kick_datetime = datetime.now(timezone.utc) + timedelta(minutes=kick_time)

    kickdb.insert_one({
        "chat_id": message.chat.id,
        "user_id": target_user.id,
        "kick_time": kick_datetime,
    })

    await message.reply(
        f"✅ User [{target_user.first_name}](tg://user?id={target_user.id}) akan dikick dalam `{kick_time}` menit.",
        quote=True,
        disable_web_page_preview=True
    )

@app.on_message(filters.command("cancel_kick", prefixes=COMMAND_PREFIX) & filters.group)
async def cancel_kick_command(client: Client, message: Message):
    # Verifikasi admin
    member = await client.get_chat_member(message.chat.id, message.from_user.id)
    if member.status not in ("creator", "administrator"):
        return await message.reply("❌ Kamu harus admin grup untuk pakai perintah ini.")

    args = message.text.split()[1:]
    target_user: User = None

    # Coba dari reply
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
    elif args:
        identifier = args[0]
        try:
            user_id = int(identifier)
            target_user = await client.get_users(user_id)
        except ValueError:
            try:
                target_user = await client.get_users(identifier)
            except Exception:
                return await message.reply("❌ Tidak bisa menemukan pengguna dari input itu.")
    else:
        return await message.reply(f"Usage:\n`{COMMAND_PREFIX}cancel_kick <user_id|@username>`\nAtau reply ke user.")

    result = kickdb.find_one_and_delete({
        "chat_id": message.chat.id,
        "user_id": target_user.id
    })

    if result:
        await message.reply(
            f"✅ Kick untuk [{target_user.first_name}](tg://user?id={target_user.id}) dibatalkan.",
            disable_web_page_preview=True
        )
    else:
        await message.reply("⚠️ Tidak ditemukan jadwal kick untuk user ini.")



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