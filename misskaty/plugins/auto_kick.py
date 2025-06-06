import os
from datetime import datetime, timedelta, timezone
from pyrogram import Client, filters
from pyrogram.types import *
from database import dbname
from misskaty import app
from misskaty.helper.localization import use_chat_lang
from pyrogram.errors import PeerIdInvalid
from logging import getLogger
from misskaty.vars import SUDO
LOGGER = getLogger("MissKaty")
kickdb = dbname["auto_kick"]
DEFAULT_KICK_TIME_MINUTES = int(os.getenv("DEFAULT_KICK_TIME_HOURS", "1"))

@app.on_cmd(["autokick"], self_admin=True, group_only=True)
@app.adminsOnly("can_restrict_members")
@use_chat_lang()
async def handle_autokick(client: Client, ctx: Message, strings) -> "Message":
    args = ctx.text.split()[1:]

    if not args and not ctx.reply_to_message:
        return await ctx.reply(
            "Usage:\n"
            "`/autokick <menit>` → atur autokick dari reply\n"
            "`/autokick cancel <id|@username>` → batalkan autokick\n"
            "`/autokick check <id|@username>` → cek sisa waktu autokick"
        )

    subcommand = args[0].lower() if args else None
    identifier = args[1] if len(args) > 1 else None
    target_user: User = None
    if ctx.reply_to_message and ctx.reply_to_message.from_user:
        target_user = ctx.reply_to_message.from_user
    elif identifier:
        try:
            target_user = await app.get_users(int(identifier) if identifier.isdigit() else identifier)
        except Exception:
            return await ctx.reply(f"❌ Tidak bisa menemukan user dari input ({identifier}), coba dengan mereply pesan dari user.")
    else:
        return await ctx.reply("❌ Harap reply ke user atau beri user_id/username.")

    if subcommand == "cancel":
        result = await kickdb.delete_one({
            "chat_id": ctx.chat.id,
            "user_id": target_user.id
        })
        if result.deleted_count:
            return await ctx.reply(
                f"✅ Autokick untuk [{target_user.first_name}](tg://user?id={target_user.id}) dibatalkan.",
                disable_web_page_preview=True
            )
        else:
            return await ctx.reply(
                f"⚠️ Tidak ditemukan autokick untuk [{target_user.first_name}](tg://user?id={target_user.id}).",
                disable_web_page_preview=True
            )

    elif subcommand == "check":
        doc = await kickdb.find_one({
            "chat_id": ctx.chat.id,
            "user_id": target_user.id
        })

        if doc:
            kick_time = doc["kick_time"]
            if kick_time.tzinfo is None:
                kick_time = kick_time.replace(tzinfo=timezone.utc)

            remaining = kick_time - datetime.now(timezone.utc)
            total_minutes = int(remaining.total_seconds() // 60)
            hours, minutes = divmod(total_minutes, 60)

            time_str = f"{hours} jam {minutes} menit" if hours else f"{minutes} menit"
            return await ctx.reply(
                f"⏳ [{target_user.first_name}](tg://user?id={target_user.id}) akan dikick dalam {time_str}.",
                disable_web_page_preview=True
            )
        else:
            return await ctx.reply(
                f"✅ Tidak ada jadwal autokick untuk [{target_user.first_name}](tg://user?id={target_user.id}).",
                disable_web_page_preview=True
            )

    else:
        try:
            kick_time = int(subcommand) if subcommand and subcommand.isdigit() else DEFAULT_KICK_TIME_MINUTES
        except ValueError:
            return await ctx.reply("❌ Masukkan waktu dalam menit, atau gunakan `cancel` / `check`.")

        kick_datetime = datetime.now(timezone.utc) + timedelta(minutes=kick_time)

        await kickdb.insert_one({
            "chat_id": ctx.chat.id,
            "user_id": target_user.id,
            "kick_time": kick_datetime,
        })

        return await ctx.reply(
            f"✅ [{target_user.first_name}](tg://user?id={target_user.id}) akan dikick dalam `{kick_time}` menit.",
            disable_web_page_preview=True
        )

async def check_kicks():
    now = datetime.now(timezone.utc)
    LOGGER.info(f"[INFO] Memeriksa kick yang harus dilakukan... {now}")
    found = False
    async for kick in kickdb.find({"kick_time": {"$lte": now}}):
        found = True
        chat_id = kick.get("chat_id")
        user_id = kick.get("user_id")
        if not chat_id or not user_id:
            LOGGER.info(f"[WARNING] Lewati entri invalid: {kick}")
            await kickdb.delete_one({"_id": kick["_id"]})
            continue
        try:
            await app.ban_chat_member(chat_id=int(chat_id), user_id=int(user_id))
            await app.unban_chat_member(chat_id, user_id)
            await app.send_message(chat_id=int(chat_id), text=f"User {user_id} berhasil dikick oleh auto kick.",)
        except Exception as e:
            LOGGER.info(f"[ERROR] Gagal kick user {user_id} dari chat {chat_id}: {e}")
            app.send_message(int(chat_id), f"User {user_id} Gagal dikick oleh auto kick, pastikan saya sudah dijadikan admin dan diberikan izin untuk kick member.")
        finally:
            await kickdb.delete_one({"_id": kick["_id"]})
    if not found:
        LOGGER.info("[INFO] Tidak ada kick yang harus dilakukan.")