import re
from pyrogram import enums, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from misskaty import app
from misskaty.vars import COMMAND_HANDLER
from pyrogram.enums import ParseMode

async def is_authorized_user(channel_id, user_id):
    try:
        member = await app.get_chat_member(channel_id, user_id)
        return member.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]
    except:
        return False

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

@app.on_message(filters.command(["post"], COMMAND_HANDLER))
async def post_with_buttons(client, message):
    replied = message.reply_to_message
    preview = False

    if not replied:
        return await message.reply(f"⚠️ Kamu harus balas pesan yang ingin kamu post ke channel.", quote=True)
    if len(message.command) < 2:
        return await message.reply("⚠️ Kamu harus menyertakan target channel.\nContoh: `/post @namachannel` atau `/post -10012345`\nAtau gunakan `/post check` untuk preview pesan sebelum dipost.", quote=True)

    target_channel = message.command[1]
    if target_channel == "check":
        preview = True

    if not preview:
        if not target_channel.startswith("@") and not target_channel.startswith("-100"):
            return await message.reply("⚠️ Format channel tidak valid. Gunakan `@username` atau `-100...`", quote=True)
        if not target_channel.startswith("@") and target_channel.startswith("-100"):
            target_channel = int(target_channel)

        try:
            await client.get_chat(target_channel)
        except:
            return await message.reply(f"⚠️ Channel tidak ditemukan atau tidak valid, pastikan bot sudah dijadikan admin di channel tersebut", quote=True)
        
        if not await is_authorized_user(target_channel, message.from_user.id):
            return await message.reply("⚠️ Kamu tidak memiliki izin untuk mengirim pesan ke channel ini.", quote=True)

    if preview:
        target_channel = message.chat.id
    reply_text = replied.caption if replied and replied.caption else replied.text if replied else ""
    full_text = (reply_text or "") + "\n"
    caption, keyboard = parse_buttons_layout(full_text)
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

    if reply_markup and not caption.strip() and not (
        replied and (replied.photo 
                     or replied.video 
                     or replied.document 
                     or replied.audio)
                    ):
        return await message.reply(
            "⚠️ Tidak ada teks atau media dalam pesan yang di-reply.\n"
            "Telegram tidak mengizinkan pesan yang hanya berisi tombol tanpa text atau media."
        )

    if replied.photo:
        await client.send_photo(
            chat_id=target_channel,
            photo=replied.photo.file_id,
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    elif replied.video:
        await client.send_video(
            chat_id=target_channel,
            video=replied.video.file_id,
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    elif replied.document:
        await client.send_document(
            chat_id=target_channel,
            document=replied.document.file_id,
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    elif replied.audio:
        await client.send_audio(
            chat_id=target_channel,
            audio=replied.audio.file_id,
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    else:
        await client.send_message(
            chat_id=target_channel,
            text=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
    if preview:
        await message.reply("✅ Ini adalah preview pesan yang akan dipost ke channel")
    else:
        await message.reply(f"✅ Berhasil kirim pesan ke channel {target_channel} !.")
    
