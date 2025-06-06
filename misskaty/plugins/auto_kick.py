import os
from datetime import datetime, timedelta, timezone
from pyrogram import Client, filters
from pyrogram.types import *
from database import dbname
from misskaty import app
from misskaty.core.keyboard import ikb
from misskaty.helper.functions import extract_user_and_reason
from misskaty.helper.localization import use_chat_lang
from pyrogram.errors import PeerIdInvalid

kickdb = dbname["auto_kick"]
DEFAULT_KICK_TIME_MINUTES = int(os.getenv("DEFAULT_KICK_TIME_HOURS", "1"))

@app.on_cmd(["autokick"], self_admin=True, group_only=True)
@app.adminsOnly("can_restrict_members")
@use_chat_lang()
async def AutoKick(client: Client, ctx: Message, strings) -> "Message":
    user_id, reason = await extract_user_and_reason(ctx)
    try:
        user = await app.get_users(user_id)
    except PeerIdInvalid:
        return await ctx.reply_msg(f"❌ User Tidak Ditemukan")
    args = ctx.text.split()[1:]

    # Coba ambil target dari reply
    target_user: User = None
    if ctx.reply_to_message and ctx.reply_to_message.from_user:
        target_user = ctx.reply_to_message.from_user
    elif args:
        identifier = args[0]
        try:
            user_id = int(identifier)
            target_user = user
        except ValueError:
            try:
                target_user = await app.get_users(identifier)
            except Exception:
                return await ctx.reply("❌ Tidak bisa menemukan pengguna dari input itu.")
    else:
        return await ctx.reply(f"Usage:\n`/autokick <user_id|@username>` [menit]\nAtau reply ke user.")

    try:
        kick_time = int(args[1]) if len(args) > 1 else DEFAULT_KICK_TIME_MINUTES
    except ValueError:
        return await ctx.reply("❌ Waktu kick harus berupa angka (dalam menit).")

    kick_datetime = datetime.now(timezone.utc) + timedelta(minutes=kick_time)

    kickdb.insert_one({
        "chat_id": ctx.chat.id,
        "user_id": target_user.id,
        "kick_time": kick_datetime,
    })

    await ctx.reply(
        f"✅ User [{target_user.first_name}](tg://user?id={target_user.id}) akan dikick dalam `{kick_time}` menit.",
        quote=True,
        disable_web_page_preview=True
    )



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