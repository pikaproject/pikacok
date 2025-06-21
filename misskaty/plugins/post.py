import re
from pyrogram import enums, filters
from pyrogram.errors import UserIsBlocked, UserNotParticipant
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from misskaty import BOT_USERNAME, app
from misskaty.core.decorator.errors import capture_err
from misskaty.vars import COMMAND_HANDLER
from pyrogram.enums import ParseMode

TARGET_CHANNEL = -1002688639436

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
    if not replied:
        await message.reply("Harus reply ke pesan berisi teks atau media.")
        return
    
    html_text = replied.caption if replied.caption else replied.text
    if not html_text:
        await message.reply("Pesan tidak berisi teks/caption.")
        return

    cleaned_html, keyboard = parse_buttons_layout(html_text)
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

    if reply_markup and not cleaned_html.strip():
        return await message.reply(
            "⚠️ Tidak ada teks atau media dalam pesan yang di-reply.\n"
            "Telegram tidak mengizinkan pesan yang hanya berisi tombol."
        )

    if replied.photo:
        await client.send_photo(
            chat_id=TARGET_CHANNEL,
            photo=replied.photo.file_id,
            caption=cleaned_html,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    elif replied.video:
        await client.send_video(
            chat_id=TARGET_CHANNEL,
            video=replied.video.file_id,
            caption=cleaned_html,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    elif replied.document:
        await client.send_document(
            chat_id=TARGET_CHANNEL,
            document=replied.document.file_id,
            caption=cleaned_html,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    elif replied.audio:
        await client.send_audio(
            chat_id=TARGET_CHANNEL,
            audio=replied.audio.file_id,
            caption=cleaned_html,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    else:
        await client.send_message(
            chat_id=TARGET_CHANNEL,
            text=cleaned_html,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )

    await message.reply("✅ Dikirim ke channel.")
    
