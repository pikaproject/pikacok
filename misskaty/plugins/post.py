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
    original_html = await client.export_message_text(replied.chat.id, replied.id, parse_mode="html")
    if not original_html:
        await message.reply("Tidak ada teks yang bisa dikirim.")
        return
    cleaned_html, keyboard = parse_buttons_layout(original_html)

    await client.send_message(
        chat_id=TARGET_CHANNEL,
        text=cleaned_html,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
    )

    await message.reply("✅ Dikirim ke channel dengan format asli.")
    
