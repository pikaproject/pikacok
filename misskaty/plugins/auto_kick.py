import os
import re
from datetime import datetime, timedelta, timezone
from pyrogram import Client, filters
from pyrogram.types import *
from database import dbname
from misskaty import app
from misskaty.helper.localization import use_chat_lang
from pyrogram.errors import PeerIdInvalid
from logging import getLogger
from misskaty.vars import SUDO
from misskaty.core.decorator.permissions import (
    admins_in_chat,
    list_admins,
    member_permissions,
)
from misskaty.vars import COMMAND_HANDLER
LOGGER = getLogger("MissKaty")
kickdb = dbname["auto_kick"]
DEFAULT_KICK_TIME_MINUTES = int(os.getenv("DEFAULT_KICK_TIME_HOURS", "1"))

@app.on_message(filters.command(["autokick"], COMMAND_HANDLER))
#@app.adminsOnly("can_restrict_members")
async def handle_autokick(client: Client, ctx: Message) -> "Message":
    chat_type = ctx.chat.type.value
    if ctx.from_user.id not in (await list_admins(ctx.chat.id)):
        return await ctx.reply("❌ Anda tidak memiliki izin untuk menggunakan perintah ini.")
    if chat_type == "private":
        return await ctx.reply("Perintah ini hanya bisa digunakan di grup atau channel.")
    args = ctx.text.split()[1:]
    time_args = None
    if not args and not ctx.reply_to_message:
        return await ctx.reply(
            "Usage:\n"
            "<code>/autokick {id|@username} {waktu}</code> → atur autokick\n\n"
            "<code>/autokick cancel {id|@username}</code> → batalkan autokick\n\n"
            "<code>/autokick check {id|@username}</code> → cek sisa waktu autokick\n\n"
            "Atau bisa dengan reply user dengan perintah."
        )

    subcommand = args[0].lower() if args else None
    identifier = args[1] if len(args) > 1 else None
    if subcommand not in ["cancel", "check"]:
        identifier = subcommand
        time_args = args[1] if len(args) > 1 else None

    target_user: User = None
    if ctx.reply_to_message and ctx.reply_to_message.from_user:
        target_user = ctx.reply_to_message.from_user
        if not args:
            return await ctx.reply("❌ Harap masukkan waktu autokick, atau subcommand check/cancel")

    elif identifier:
        try:
            target_user = await app.get_users(int(identifier) if identifier.isdigit() else identifier)
        except Exception:
            return await ctx.reply(f"❌ Tidak bisa menemukan user dari input (<code>{identifier}</code>), coba dengan mereply pesan dari user diikuti dengan waktu.")
    else:
        return await ctx.reply("❌ Harap reply ke user atau beri user_id/username.")

    if target_user.id == client.me.id:
        return await ctx.reply("Saya tidak bisa set autokick untuk diri sendiri -_-")
    elif target_user.id in SUDO:
        return await ctx.reply("Saya tidak bisa autokick Owner saya hehe")
    elif target_user.id in (await list_admins(ctx.chat.id)):
        return await ctx.reply("Saya tidak bisa autokick Admin di grup ini, baka !")

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
            if time_args:
                kick_time = parse_time_string(time_args)
            else:
                kick_time = parse_time_string(subcommand)
        except ValueError as e:
            return await ctx.reply(f"❌ {e}")

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

def parse_time_string(s: str) -> int:
    """Ubah string seperti '1d2h30m' jadi total menit (int)."""
    pattern = re.compile(r'(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?')
    match = pattern.fullmatch(s.strip().lower())
    if not match:
        raise ValueError("Format waktu tidak valid. Gunakan format seperti contoh 1d atau 1d30h atau 30m.")
    days, hours, minutes = match.groups()
    total_minutes = (
        (int(days) * 1440 if days else 0) +
        (int(hours) * 60 if hours else 0) +
        (int(minutes) if minutes else 0)
    )
    if total_minutes == 0:
        raise ValueError("Waktu tidak boleh 0.")
    return total_minutes

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
            user = await app.get_users(int(user_id))
            name = user.first_name
            await app.ban_chat_member(chat_id=int(chat_id), user_id=int(user_id))
            await app.unban_chat_member(chat_id, user_id)
            await app.send_message(chat_id=int(chat_id), text=f"User <a href='tg://user?id={user_id}'>{name}</a> berhasil dikick oleh auto kick.",)
        except Exception as e:
            LOGGER.info(f"[ERROR] Gagal kick user {user_id} dari chat {chat_id}: {e}")
            app.send_message(int(chat_id), f"User <a href='tg://user?id={user_id}'>{name}</a> Gagal dikick oleh auto kick, pastikan saya sudah dijadikan admin dan diberikan izin untuk kick member.")
        finally:
            await kickdb.delete_one({"_id": kick["_id"]})
    if not found:
        LOGGER.info("[INFO] Tidak ada kick yang harus dilakukan.")