import re
from pyrogram import enums, filters
from pyrogram.errors import UserIsBlocked, UserNotParticipant, PeerIdInvalid
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from misskaty import BOT_USERNAME, app
from misskaty.core.decorator.errors import capture_err
from misskaty.vars import COMMAND_HANDLER
from pyrogram.enums import ParseMode

def parse_buttons_layout(text):
    pattern = re.compile(r"\[([^\]]+)\]\((https?://[^\)]+)\)")
    buttons_layout = []
    cleaned_lines = []

    for line in text.splitlines():
        matches = pattern.findall(line)
        if matches:
            row = []
            for label, url in matches:
                row.append(InlineKeyboardButton(label, url=url))
            buttons_layout.append(row)
            cleaned_lines.append("")
        else:
            cleaned_lines.append(line)
    cleaned_text = "\n".join(filter(None, cleaned_lines)).strip()
    return cleaned_text, buttons_layout if buttons_layout else None

@app.on_message(filters.command(["post"], COMMAND_HANDLER) & filters.reply)
async def post_with_buttons(client, message):
    replied = message.reply_to_message

    if len(message.command) < 2:
        return await message.reply("⚠️ Kamu harus menyertakan target channel.\nContoh: `/post @namachannel`", quote=True)

    target_channel = message.command[1]
    if not target_channel.startswith("@") and not target_channel.startswith("-"):
        return await message.reply("⚠️ Format channel tidak valid. Gunakan `@username` atau `-100...`", quote=True)
    if not target_channel.startswith("@") and target_channel.startswith("-"):
        target_channel = int(target_channel)
    try:
        await client.get_chat(target_channel)
    except PeerIdInvalid:
        return await message.reply("⚠️ Channel tidak ditemukan atau tidak valid, pastikan bot sudah dijadikan admin di channel tersebut", quote=True)
    except Exception as e:
        return await message.reply(f"⚠️ Terjadi kesalahan saat mengakses channel: {str(e)}", quote=True)

    html_text = replied.caption if replied and replied.caption else replied.text if replied else ""
    command_text = message.text or message.caption or ""

    full_text = (html_text or "") + "\n" + command_text
    cleaned_html, keyboard = parse_buttons_layout(full_text)
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

    if reply_markup and not cleaned_html.strip() and not (
        replied and (replied.photo 
                     or replied.video 
                     or replied.document 
                     or replied.audio)
                    ):
        return await message.reply(
            "⚠️ Tidak ada teks atau media dalam pesan yang di-reply.\n"
            "Telegram tidak mengizinkan pesan yang hanya berisi tombol."
        )

    if replied.photo:
        await client.send_photo(
            chat_id=target_channel,
            photo=replied.photo.file_id,
            caption=cleaned_html,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    elif replied.video:
        await client.send_video(
            chat_id=target_channel,
            video=replied.video.file_id,
            caption=cleaned_html,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    elif replied.document:
        await client.send_document(
            chat_id=target_channel,
            document=replied.document.file_id,
            caption=cleaned_html,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    elif replied.audio:
        await client.send_audio(
            chat_id=target_channel,
            audio=replied.audio.file_id,
            caption=cleaned_html,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    else:
        await client.send_message(
            chat_id=target_channel,
            text=cleaned_html,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )

    await message.reply("✅ Dikirim ke channel.")
    
