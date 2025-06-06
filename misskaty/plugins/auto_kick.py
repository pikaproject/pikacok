import os
from datetime import datetime, timedelta, timezone
from pyrogram import Client, filters
from pyrogram.types import *
from database import dbname
from misskaty import app
from misskaty.helper.localization import use_chat_lang
from pyrogram.errors import PeerIdInvalid
from logging import getLogger
LOGGER = getLogger("MissKaty")
kickdb = dbname["auto_kick"]
DEFAULT_KICK_TIME_MINUTES = int(os.getenv("DEFAULT_KICK_TIME_HOURS", "1"))

@app.on_cmd(["autokick"], self_admin=True, group_only=True)
@app.adminsOnly("can_restrict_members")
@use_chat_lang()
async def AutoKick(client: Client, ctx: Message, strings) -> "Message":
    args = ctx.text.split()[1:]

    target_user: User = None

    # 1. Coba ambil dari reply
    if ctx.reply_to_message and ctx.reply_to_message.from_user:
        target_user = ctx.reply_to_message.from_user

    # 2. Kalau tidak reply, ambil dari argumen
    elif args:
        identifier = args[0]
        try:
            user_id = int(identifier)
            target_user = await app.get_users(user_id)
        except ValueError:
            try:
                target_user = await app.get_users(identifier)
            except PeerIdInvalid:
                return await ctx.reply("❌ Username tidak valid atau user tidak ditemukan.")
            except Exception:
                return await ctx.reply("❌ Gagal mendapatkan user dari input.")
    else:
        return await ctx.reply(
            "Usage:\n`/autokick <user_id|@username>` [menit]\nAtau balas pesan pengguna."
        )

    if not target_user:
        return await ctx.reply("❌ Target user tidak ditemukan.")

    # 3. Ambil waktu kick
    try:
        kick_time = int(args[1]) if len(args) > 1 else DEFAULT_KICK_TIME_MINUTES
    except ValueError:
        return await ctx.reply("❌ Waktu kick harus berupa angka (dalam menit).")

    kick_datetime = datetime.now(timezone.utc) + timedelta(minutes=kick_time)

    # 4. Simpan ke MongoDB (async_pymongo)
    await kickdb.insert_one({
        "chat_id": ctx.chat.id,
        "user_id": target_user.id,
        "kick_time": kick_datetime,
    })

    return await ctx.reply(
        f"✅ User [{target_user.first_name}](tg://user?id={target_user.id}) akan dikick dalam `{kick_time}` menit.",
        quote=True,
        disable_web_page_preview=True
    )


async def check_kicks():
    now = datetime.now(timezone.utc)
    LOGGER.info(f"[INFO] Memeriksa kick yang harus dilakukan... {now}")

    found = False
    async for kick in kickdb.find({"kick_time": {"$lte": now}}):
        found = True
        chat_id = kick["chat_id"]
        user_id = kick["user_id"]

        try:
            await app.kick_chat_member(chat_id, user_id)
            await app.unban_chat_member(chat_id, user_id)
            LOGGER.info(f"[INFO] Berhasil kick user {user_id} dari chat {chat_id}")
        except Exception as e:
            LOGGER.info(f"[ERROR] Gagal kick user {user_id} dari chat {chat_id}: {e}")
        finally:
            await kickdb.delete_one({"_id": kick["_id"]})

    if not found:
        LOGGER.info("[INFO] Tidak ada kick yang harus dilakukan.")