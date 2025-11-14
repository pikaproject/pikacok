# * @author        Yasir Aris M <yasiramunandar@gmail.com>
# * @date          2023-06-21 22:12:27
# * @projectName   MissKatyPyro
# * Copyright ©YasirPedia All rights reserved
import asyncio
import contextlib
import json
import logging
import re
import sys
from os import environ
from typing import Optional
from urllib.parse import quote_plus

import httpx
import cloudscraper
from bs4 import BeautifulSoup
import requests
from pykeyboard import InlineButton, InlineKeyboard
from pyrogram import Client, enums
from pyrogram.errors import (
    ListenerTimeout,
    MediaCaptionTooLong,
    MediaEmpty,
    MessageIdInvalid,
    MessageNotModified,
    PhotoInvalidDimensions,
    WebpageCurlFailed,
    WebpageMediaEmpty,
)
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)

from database.imdb_db import (
    DEFAULT_IMDB_LAYOUT,
    add_imdbset,
    get_imdb_layout,
    is_imdbset,
    remove_imdbset,
    reset_imdb_layout,
    toggle_imdb_layout,
)
from misskaty import app
from misskaty.helper import GENRES_EMOJI, Cache, fetch, gtranslate, get_random_string, search_jw
from utils import demoji

LOGGER = logging.getLogger("MissKaty")
LIST_CARI = Cache(filename="imdb_cache.db", path="cache", in_memory=False)
IMDB_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
SOLVER_API_URL = environ.get("SOLVER_API_URL", "https://solver.pika.web.id/")
IMDB_SPLASH_IMAGE = "https://img.yasirweb.eu.org/file/270955ef0d1a8a16831a9.jpg"
IMDB_LAYOUT_FIELDS = [
    ("title", "🎬 Judul / Title"),
    ("duration", "⏱ Durasi / Duration"),
    ("category", "📛 Kategori / Category"),
    ("rating", "⭐️ Peringkat / Rating"),
    ("release", "🗓 Rilis / Release"),
    ("genre", "🎭 Genre"),
    ("country", "🌍 Negara / Country"),
    ("language", "🗣 Bahasa / Language"),
    ("cast_info", "🎭 Info Cast / Cast Info"),
    ("plot", "📜 Plot / Summary"),
    ("keywords", "🏷 Kata Kunci / Keywords"),
    ("awards", "🏆 Penghargaan / Awards"),
    ("availability", "📺 Tersedia di / Available On"),
    ("imdb_by", "🤖 IMDb By Tagline"),
    ("button_open_imdb", "🔗 Tombol Open IMDb"),
    ("button_trailer", "🎞 Tombol Trailer"),
]
IMDB_LAYOUT_LABELS = dict(IMDB_LAYOUT_FIELDS)
IMDB_BUTTON_OPEN_TEXT = "ðŸŽ¬ Open IMDB"
IMDB_BUTTON_TRAILER_TEXT = "â–¶ï¸ Trailer"
IMDB_EMPTY_LAYOUT_NOTICE = {
    "id": (
        "⚠️ Semua bagian detail IMDb kamu sedang disembunyikan. "
        "Gunakan /imdbset untuk mengaktifkannya lagi."
    ),
    "en": (
        "⚠️ All IMDb detail sections are currently hidden. "
        "Use /imdbset to enable them again."
    ),
}


def _build_imdb_settings_caption(user_name: str) -> str:
    return (
        f"Halo {user_name}!\n"
        "Kelola preferensi IMDb Search kamu di sini.\n\n"
        "• 🎛 Edit Layout → pilih informasi apa saja yang tampil di hasil detail.\n"
        "• 🚩 Language → set bahasa default saat memakai /imdb.\n\n"
        "Sentuh salah satu tombol di bawah untuk memulai."
    )


def _build_imdb_settings_keyboard(user_id: int) -> InlineKeyboard:
    buttons = InlineKeyboard(row_width=1)
    buttons.row(InlineButton("🎛 Edit Layout", f"imdbslayout#{user_id}"))
    buttons.row(InlineButton("🚩 Language", f"imdbset#{user_id}"))
    buttons.row(InlineButton("❌ Close", f"close#{user_id}"))
    return buttons


def _build_layout_caption(layout: dict) -> str:
    total_fields = len(IMDB_LAYOUT_FIELDS)
    enabled_fields = [
        label for key, label in IMDB_LAYOUT_FIELDS if layout.get(key, True)
    ]
    disabled_fields = [
        label for key, label in IMDB_LAYOUT_FIELDS if not layout.get(key, True)
    ]
    caption = (
        "Hidupkan atau matikan bagian IMDb berikut sesuai kebutuhanmu.\n"
        f"Status saat ini: {len(enabled_fields)}/{total_fields} bagian aktif.\n"
    )
    if enabled_fields:
        caption += f"\n✅ Aktif: {', '.join(enabled_fields)}"
    if disabled_fields:
        caption += f"\n🚫 Nonaktif: {', '.join(disabled_fields)}"
    caption += "\n\nTap tombol untuk toggle atau reset jika ingin kembali ke default."
    return caption


def _build_layout_keyboard(user_id: int, layout: dict) -> InlineKeyboard:
    buttons = InlineKeyboard(row_width=2)
    layout_buttons = []
    for key, label in IMDB_LAYOUT_FIELDS:
        status = "✅" if layout.get(key, True) else "🚫"
        layout_buttons.append(
            InlineButton(f"{status} {label}", f"imdblayouttoggle#{key}#{user_id}")
        )
    if layout_buttons:
        buttons.add(*layout_buttons)
    buttons.row(
        InlineButton("🔁 Reset", f"imdblayoutreset#{user_id}"),
        InlineButton("⬅️ Back", f"imdbsettings#{user_id}"),
    )
    buttons.row(InlineButton("❌ Close", f"close#{user_id}"))
    return buttons


def _build_imdb_action_markup(
    layout: dict, imdb_url: str, trailer_url: Optional[str]
) -> Optional[InlineKeyboardMarkup]:
    buttons = []
    if layout.get("button_open_imdb"):
        buttons.append(InlineKeyboardButton(IMDB_BUTTON_OPEN_TEXT, url=imdb_url))
    if layout.get("button_trailer") and trailer_url:
        buttons.append(InlineKeyboardButton(IMDB_BUTTON_TRAILER_TEXT, url=trailer_url))
    if buttons:
        return InlineKeyboardMarkup([buttons])
    return None


def _scrape_imdb_html(imdb_url: str) -> str:
    session = requests.Session()
    session.headers.update(IMDB_HEADERS)
    waf_hint = None
    for _ in range(3):
        resp = session.get(imdb_url, timeout=20)
        waf_hint = resp.headers.get("x-amzn-waf-action")
        if resp.status_code != 202 and waf_hint != "challenge" and resp.text.strip():
            return resp.text
    scraper = cloudscraper.create_scraper()
    resp = scraper.get(imdb_url, timeout=30, headers=IMDB_HEADERS)
    resp.raise_for_status()
    return resp.text


async def _fetch_imdb_html_via_scraper(imdb_url: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _scrape_imdb_html, imdb_url)


async def _fetch_imdb_html_via_solver(imdb_url: str) -> Optional[str]:
    solver_url = SOLVER_API_URL
    if not solver_url:
        return None
    solver_url = solver_url.rstrip("/")
    try:
        resp = await fetch.get(
            solver_url, params={"url": imdb_url}, timeout=60, headers=IMDB_HEADERS
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        LOGGER.warning("Solver API HTTP error for %s: %s", imdb_url, exc)
        return None
    text = getattr(resp, "text", "")
    if not text or not text.strip():
        LOGGER.warning("Solver API returned empty body for %s", imdb_url)
        return None
    return text


async def _fetch_imdb_html(
    imdb_url: str,
) -> tuple[str, int, Optional[str], bool]:
    resp = await fetch.get(imdb_url, headers=IMDB_HEADERS)
    status_code = getattr(resp, "status_code", 0)
    headers = getattr(resp, "headers", {}) or {}
    waf_action = headers.get("x-amzn-waf-action") if headers else None
    text = getattr(resp, "text", "") or ""
    if status_code >= 400:
        resp.raise_for_status()
    used_fallback = False
    if status_code == 202 or waf_action or not text.strip():
        LOGGER.warning(
            "IMDB returned status=%s waf=%s for %s; retrying via cloudscraper",
            status_code,
            waf_action,
            imdb_url,
        )
        text = await _fetch_imdb_html_via_scraper(imdb_url)
        used_fallback = True
    return text, status_code, waf_action, used_fallback


def _parse_imdb_metadata(html: str) -> tuple[BeautifulSoup, Optional[dict]]:
    soup = BeautifulSoup(html, "lxml")
    script_tag = soup.find("script", attrs={"type": "application/ld+json"})
    if not script_tag:
        return soup, None
    raw = script_tag.string
    if raw is None and script_tag.contents:
        raw = script_tag.contents[0]
    if not raw:
        return soup, None
    try:
        return soup, json.loads(raw)
    except json.JSONDecodeError:
        LOGGER.exception("Failed to decode IMDB metadata JSON.")
    return soup, None


async def _get_imdb_page(imdb_url: str) -> tuple[BeautifulSoup, dict]:
    html, status_code, waf_action, used_fallback = await _fetch_imdb_html(imdb_url)
    soup, metadata = _parse_imdb_metadata(html)
    if metadata:
        return soup, metadata
    LOGGER.warning(
        "IMDB metadata missing on first parse (status=%s, waf=%s, fallback=%s) for %s",
        status_code,
        waf_action,
        used_fallback,
        imdb_url,
    )
    solver_html = await _fetch_imdb_html_via_solver(imdb_url)
    if solver_html:
        soup, metadata = _parse_imdb_metadata(solver_html)
        if metadata:
            LOGGER.info("Fetched IMDB metadata via Solver API for %s", imdb_url)
            return soup, metadata
    if not used_fallback:
        html = await _fetch_imdb_html_via_scraper(imdb_url)
        soup, metadata = _parse_imdb_metadata(html)
        if metadata:
            return soup, metadata
    raise ValueError(
        f"Tidak dapat mengambil metadata IMDB (status={status_code}, waf={waf_action}, solver={bool(solver_html)})."
    )


def _format_people_list(people_list, limit=None):
    if not people_list:
        return ""
    if limit is not None:
        people_list = people_list[:limit]
    formatted = []
    for person in people_list:
        name = person.get("name")
        if not name:
            continue
        url = person.get("url")
        clean_name = demoji(name)
        if url:
            formatted.append(f"<a href='{url}'>{clean_name}</a>")
        else:
            formatted.append(clean_name)
    return ", ".join(formatted)


def _extract_people_from_imdb(soup: BeautifulSoup, metadata: dict) -> dict:
    people = {"directors": [], "writers": [], "cast": []}
    seen = {key: set() for key in people}

    def add_person(
        section: str, name: Optional[str], url: Optional[str] = None
    ) -> None:
        if not name:
            return
        key = (url or name).lower()
        if key in seen[section]:
            return
        seen[section].add(key)
        people[section].append({"name": name, "url": url})

    next_script = soup.find("script", id="__NEXT_DATA__")
    if next_script and next_script.string:
        try:
            next_data = json.loads(next_script.string)
        except json.JSONDecodeError:
            next_data = {}
        main_column = (
            next_data.get("props", {})
            .get("pageProps", {})
            .get("mainColumnData", {})
        )
        for section in main_column.get("crewV2") or []:
            grouping = (section.get("grouping") or {}).get("text", "").lower()
            for credit in section.get("credits") or []:
                name_info = credit.get("name") or {}
                name_text = (name_info.get("nameText") or {}).get("text")
                imdb_id = name_info.get("id")
                url = f"https://www.imdb.com/name/{imdb_id}/" if imdb_id else None
                if "director" in grouping:
                    add_person("directors", name_text, url)
                elif "writer" in grouping:
                    add_person("writers", name_text, url)
        for section in main_column.get("castV2") or []:
            for credit in section.get("credits") or []:
                name_info = credit.get("name") or {}
                name_text = (name_info.get("nameText") or {}).get("text")
                imdb_id = name_info.get("id")
                url = f"https://www.imdb.com/name/{imdb_id}/" if imdb_id else None
                add_person("cast", name_text, url)
            if people["cast"]:
                break

    def iter_people(field):
        if not field:
            return []
        if isinstance(field, list):
            return field
        return [field]

    if not people["directors"]:
        for item in iter_people(metadata.get("director")):
            name = item.get("name")
            url = item.get("url")
            add_person("directors", name, url)

    if not people["writers"]:
        for item in iter_people(metadata.get("creator")):
            if item.get("@type") != "Person":
                continue
            name = item.get("name")
            url = item.get("url")
            add_person("writers", name, url)

    if not people["cast"]:
        for item in iter_people(metadata.get("actor")):
            name = item.get("name")
            url = item.get("url")
            add_person("cast", name, url)

    return people


# IMDB Choose Language
@app.on_cmd("imdb")
async def imdb_choose(_, ctx: Message):
    if len(ctx.command) == 1:
        return await ctx.reply_msg(
            f"ℹ️ Please add query after CMD!\nEx: <code>/{ctx.command[0]} Jurassic World</code>",
            del_in=7,
        )
    if ctx.sender_chat:
        return await ctx.reply_msg(
            "Cannot identify user, please use in private chat.", del_in=7
        )
    kuery = ctx.text.split(None, 1)[1]
    is_imdb, lang = await is_imdbset(ctx.from_user.id)
    if is_imdb:
        if lang == "eng":
            return await imdb_search_en(kuery, ctx)
        else:
            return await imdb_search_id(kuery, ctx)
    buttons = InlineKeyboard()
    ranval = get_random_string(4)
    LIST_CARI.add(ranval, kuery, timeout=15)
    buttons.row(
        InlineButton("🇺🇸 English", f"imdbcari#eng#{ranval}#{ctx.from_user.id}"),
        InlineButton("🇮🇩 Indonesia", f"imdbcari#ind#{ranval}#{ctx.from_user.id}"),
    )
    buttons.row(InlineButton("🚩 Set Default Language", f"imdbset#{ctx.from_user.id}"))
    buttons.row(InlineButton("❌ Close", f"close#{ctx.from_user.id}"))
    await ctx.reply_photo(
        IMDB_SPLASH_IMAGE,
        caption=f"Hi {ctx.from_user.mention}, Please select the language you want to use on IMDB Search. If you want use default lang for every user, click third button. So no need click select lang if use CMD.\n\nTimeout: 10s",
        reply_markup=buttons,
        quote=True,
    )


@app.on_cmd("imdbset")
async def imdb_settings_cmd(_, message: Message):
    if message.sender_chat:
        return await message.reply_msg(
            "Cannot identify user, please use in private chat.", del_in=7
        )
    if not message.from_user:
        return
    buttons = _build_imdb_settings_keyboard(message.from_user.id)
    caption = _build_imdb_settings_caption(message.from_user.mention)
    await message.reply_photo(
        IMDB_SPLASH_IMAGE, caption=caption, reply_markup=buttons, quote=True
    )


@app.on_cb("imdbsettings")
async def imdb_settings_callback(_, query: CallbackQuery):
    _, uid = query.data.split("#")
    if query.from_user.id != int(uid):
        return await query.answer("Access Denied!", True)
    buttons = _build_imdb_settings_keyboard(query.from_user.id)
    caption = _build_imdb_settings_caption(query.from_user.mention)
    with contextlib.suppress(MessageIdInvalid, MessageNotModified):
        await query.message.edit_caption(caption, reply_markup=buttons)


@app.on_cb("imdbslayout")
async def imdb_layout_menu(_, query: CallbackQuery):
    if not query.data.startswith("imdbslayout#"):
        return
    _, uid = query.data.split("#", 1)
    if query.from_user.id != int(uid):
        return await query.answer("Access Denied!", True)
    layout = await get_imdb_layout(query.from_user.id)
    caption = _build_layout_caption(layout)
    keyboard = _build_layout_keyboard(query.from_user.id, layout)
    with contextlib.suppress(MessageIdInvalid, MessageNotModified):
        await query.message.edit_caption(caption, reply_markup=keyboard)


@app.on_cb("imdblayouttoggle")
async def imdb_layout_toggle(_, query: CallbackQuery):
    _, field, uid = query.data.split("#")
    if query.from_user.id != int(uid):
        return await query.answer("Access Denied!", True)
    try:
        layout = await toggle_imdb_layout(query.from_user.id, field)
    except KeyError:
        return await query.answer("Invalid field!", True)
    caption = _build_layout_caption(layout)
    keyboard = _build_layout_keyboard(query.from_user.id, layout)
    with contextlib.suppress(MessageIdInvalid, MessageNotModified):
        await query.message.edit_caption(caption, reply_markup=keyboard)
    status = "Aktif" if layout.get(field) else "Nonaktif"
    await query.answer(
        f"{IMDB_LAYOUT_LABELS.get(field, field)} → {status}", show_alert=False
    )


@app.on_cb("imdblayoutreset")
async def imdb_layout_reset_btn(_, query: CallbackQuery):
    _, uid = query.data.split("#")
    if query.from_user.id != int(uid):
        return await query.answer("Access Denied!", True)
    layout = await reset_imdb_layout(query.from_user.id)
    caption = _build_layout_caption(layout)
    keyboard = _build_layout_keyboard(query.from_user.id, layout)
    with contextlib.suppress(MessageIdInvalid, MessageNotModified):
        await query.message.edit_caption(caption, reply_markup=keyboard)
    await query.answer("Layout dikembalikan ke default.", show_alert=True)


@app.on_cb("imdbset")
async def imdblangset(_, query: CallbackQuery):
    _, uid = query.data.split("#")
    if query.from_user.id != int(uid):
        return await query.answer("⚠️ Access Denied!", True)
    buttons = InlineKeyboard()
    buttons.row(
        InlineButton("🇺🇸 English", f"setimdb#eng#{query.from_user.id}"),
        InlineButton("🇮🇩 Indonesia", f"setimdb#ind#{query.from_user.id}"),
    )
    is_imdb, _ = await is_imdbset(query.from_user.id)
    if is_imdb:
        buttons.row(
            InlineButton("🗑 Remove UserSetting", f"setimdb#rm#{query.from_user.id}")
        )
    buttons.row(InlineButton("❌ Close", f"close#{query.from_user.id}"))
    with contextlib.suppress(MessageIdInvalid, MessageNotModified):
        await query.message.edit_caption(
            "<i>Please select available language below..</i>", reply_markup=buttons
        )


@app.on_cb("setimdb")
async def imdbsetlang(_, query: CallbackQuery):
    _, lang, uid = query.data.split("#")
    if query.from_user.id != int(uid):
        return await query.answer("⚠️ Access Denied!", True)
    _, langset = await is_imdbset(query.from_user.id)
    if langset == lang:
        return await query.answer(f"⚠️ Your Setting Already in ({langset})!", True)
    with contextlib.suppress(MessageIdInvalid, MessageNotModified):
        if lang == "eng":
            await add_imdbset(query.from_user.id, lang)
            await query.message.edit_caption(
                "Language interface for IMDB has been changed to English."
            )
        elif lang == "ind":
            await add_imdbset(query.from_user.id, lang)
            await query.message.edit_caption(
                "Bahasa tampilan IMDB sudah diubah ke Indonesia."
            )
        else:
            await remove_imdbset(query.from_user.id)
            await query.message.edit_caption(
                "UserSetting for IMDB has been deleted from database."
            )


async def imdb_search_id(kueri, message):
    BTN = []
    k = await message.reply_photo(
        "https://img.yasirweb.eu.org/file/270955ef0d1a8a16831a9.jpg",
        caption=f"🔎 Menelusuri <code>{kueri}</code> di database IMDb ...",
        quote=True,
    )
    msg = ""
    buttons = InlineKeyboard(row_width=4)
    with contextlib.redirect_stdout(sys.stderr):
        try:
            r = await fetch.get(
                f"https://v3.sg.media-imdb.com/suggestion/titles/x/{quote_plus(kueri)}.json"
            )
            r.raise_for_status()
            res = r.json().get("d")
            if not res:
                return await k.edit_caption(
                    f"⛔️ Tidak ditemukan hasil untuk kueri: <code>{kueri}</code>"
                )
            msg += (
                f"🎬 Ditemukan ({len(res)}) hasil untuk kueri: <code>{kueri}</code>\n\n"
            )
            for num, movie in enumerate(res, start=1):
                title = movie.get("l")
                if year := movie.get("yr"):
                    year = f"({year})"
                elif year := movie.get("y"):
                    year = f"({year})"
                else:
                    year = "(N/A)"
                typee = movie.get("q", "N/A").replace("feature", "movie").title()
                movieID = re.findall(r"tt(\d+)", movie.get("id"))[0]
                msg += f"{num}. {title} {year} - {typee}\n"
                BTN.append(
                    InlineKeyboardButton(
                        text=num,
                        callback_data=f"imdbres_id#{message.from_user.id}#{movieID}",
                    )
                )
            BTN.extend(
                (
                    InlineKeyboardButton(
                        text="🚩 Language",
                        callback_data=f"imdbset#{message.from_user.id}",
                    ),
                    InlineKeyboardButton(
                        text="❌ Close",
                        callback_data=f"close#{message.from_user.id}",
                    ),
                )
            )
            buttons.add(*BTN)
            await k.edit_caption(msg, reply_markup=buttons)
        except httpx.HTTPError as exc:
            await k.edit_caption(f"HTTP Exception for IMDB Search - <code>{exc}</code>")
        except (MessageIdInvalid, MessageNotModified):
            pass
        except Exception as err:
            await k.edit_caption(
                f"Ooppss, gagal mendapatkan daftar judul di IMDb. Mungkin terkena rate limit atau down.\n\n<b>ERROR:</b> <code>{err}</code>"
            )


async def imdb_search_en(kueri, message):
    BTN = []
    k = await message.reply_photo(
        "https://img.yasirweb.eu.org/file/270955ef0d1a8a16831a9.jpg",
        caption=f"🔎 Searching <code>{kueri}</code> in IMDb Database...",
        quote=True,
    )
    msg = ""
    buttons = InlineKeyboard(row_width=4)
    with contextlib.redirect_stdout(sys.stderr):
        try:
            r = await fetch.get(
                f"https://v3.sg.media-imdb.com/suggestion/titles/x/{quote_plus(kueri)}.json"
            )
            r.raise_for_status()
            res = r.json().get("d")
            if not res:
                return await k.edit_caption(
                    f"⛔️ Result not found for keywords: <code>{kueri}</code>"
                )
            msg += (
                f"🎬 Found ({len(res)}) result for keywords: <code>{kueri}</code>\n\n"
            )
            for num, movie in enumerate(res, start=1):
                title = movie.get("l")
                if year := movie.get("yr"):
                    year = f"({year})"
                elif year := movie.get("y"):
                    year = f"({year})"
                else:
                    year = "(N/A)"
                typee = movie.get("q", "N/A").replace("feature", "movie").title()
                movieID = re.findall(r"tt(\d+)", movie.get("id"))[0]
                msg += f"{num}. {title} {year} - {typee}\n"
                BTN.append(
                    InlineKeyboardButton(
                        text=num,
                        callback_data=f"imdbres_en#{message.from_user.id}#{movieID}",
                    )
                )
            BTN.extend(
                (
                    InlineKeyboardButton(
                        text="🚩 Language",
                        callback_data=f"imdbset#{message.from_user.id}",
                    ),
                    InlineKeyboardButton(
                        text="❌ Close",
                        callback_data=f"close#{message.from_user.id}",
                    ),
                )
            )
            buttons.add(*BTN)
            await k.edit_caption(msg, reply_markup=buttons)
        except httpx.HTTPError as exc:
            await k.edit_caption(f"HTTP Exception for IMDB Search - <code>{exc}</code>")
        except (MessageIdInvalid, MessageNotModified):
            pass
        except Exception as err:
            await k.edit_caption(
                f"Failed when requesting movies title. Maybe got rate limit or down.\n\n<b>ERROR:</b> <code>{err}</code>"
            )


@app.on_cb("imdbcari")
async def imdbcari(_, query: CallbackQuery):
    BTN = []
    _, lang, msg, uid = query.data.split("#")
    if lang == "ind":
        if query.from_user.id != int(uid):
            return await query.answer("⚠️ Akses Ditolak!", True)
        try:
            kueri = LIST_CARI.get(msg)
            del LIST_CARI[msg]
        except KeyError:
            return await query.message.edit_caption("⚠️ Callback Query Sudah Expired!")
        with contextlib.suppress(MessageIdInvalid, MessageNotModified):
            await query.message.edit_caption(
                "<i>🔎 Sedang mencari di Database IMDB..</i>"
            )
        msg = ""
        buttons = InlineKeyboard(row_width=4)
        with contextlib.redirect_stdout(sys.stderr):
            try:
                r = await fetch.get(
                    f"https://v3.sg.media-imdb.com/suggestion/titles/x/{quote_plus(kueri)}.json"
                )
                r.raise_for_status()
                res = r.json().get("d")
                if not res:
                    return await query.message.edit_caption(
                        f"⛔️ Tidak ditemukan hasil untuk kueri: <code>{kueri}</code>"
                    )
                msg += f"🎬 Ditemukan ({len(res)}) hasil dari: <code>{kueri}</code> ~ {query.from_user.mention}\n\n"
                for num, movie in enumerate(res, start=1):
                    title = movie.get("l")
                    if year := movie.get("yr"):
                        year = f"({year})"
                    elif year := movie.get("y"):
                        year = f"({year})"
                    else:
                        year = "(N/A)"
                    typee = movie.get("q", "N/A").replace("feature", "movie").title()
                    movieID = re.findall(r"tt(\d+)", movie.get("id"))[0]
                    msg += f"{num}. {title} {year} - {typee}\n"
                    BTN.append(
                        InlineKeyboardButton(
                            text=num, callback_data=f"imdbres_id#{uid}#{movieID}"
                        )
                    )
                BTN.extend(
                    (
                        InlineKeyboardButton(
                            text="🚩 Language", callback_data=f"imdbset#{uid}"
                        ),
                        InlineKeyboardButton(
                            text="❌ Close", callback_data=f"close#{uid}"
                        ),
                    )
                )
                buttons.add(*BTN)
                await query.message.edit_caption(msg, reply_markup=buttons)
            except httpx.HTTPError as exc:
                await query.message.edit_caption(
                    f"HTTP Exception for IMDB Search - <code>{exc}</code>"
                )
            except (MessageIdInvalid, MessageNotModified):
                pass
            except Exception as err:
                await query.message.edit_caption(
                    f"Ooppss, gagal mendapatkan daftar judul di IMDb. Mungkin terkena rate limit atau down.\n\n<b>ERROR:</b> <code>{err}</code>"
                )
    else:
        if query.from_user.id != int(uid):
            return await query.answer("⚠️ Access Denied!", True)
        try:
            kueri = LIST_CARI.get(msg)
            del LIST_CARI[msg]
        except KeyError:
            return await query.message.edit_caption("⚠️ Callback Query Expired!")
        await query.message.edit_caption("<i>🔎 Looking in the IMDB Database..</i>")
        msg = ""
        buttons = InlineKeyboard(row_width=4)
        with contextlib.redirect_stdout(sys.stderr):
            try:
                r = await fetch.get(
                    f"https://v3.sg.media-imdb.com/suggestion/titles/x/{quote_plus(kueri)}.json"
                )
                r.raise_for_status()
                res = r.json().get("d")
                if not res:
                    return await query.message.edit_caption(
                        f"⛔️ Result not found for keywords: <code>{kueri}</code>"
                    )
                msg += f"🎬 Found ({len(res)}) result for keywords: <code>{kueri}</code> ~ {query.from_user.mention}\n\n"
                for num, movie in enumerate(res, start=1):
                    title = movie.get("l")
                    if year := movie.get("yr"):
                        year = f"({year})"
                    elif year := movie.get("y"):
                        year = f"({year})"
                    else:
                        year = "(N/A)"
                    typee = movie.get("q", "N/A").replace("feature", "movie").title()
                    movieID = re.findall(r"tt(\d+)", movie.get("id"))[0]
                    msg += f"{num}. {title} {year} - {typee}\n"
                    BTN.append(
                        InlineKeyboardButton(
                            text=num, callback_data=f"imdbres_en#{uid}#{movieID}"
                        )
                    )
                BTN.extend(
                    (
                        InlineKeyboardButton(
                            text="🚩 Language", callback_data=f"imdbset#{uid}"
                        ),
                        InlineKeyboardButton(
                            text="❌ Close", callback_data=f"close#{uid}"
                        ),
                    )
                )
                buttons.add(*BTN)
                await query.message.edit_caption(msg, reply_markup=buttons)
            except httpx.HTTPError as exc:
                await query.message.edit_caption(
                    f"HTTP Exception for IMDB Search - <code>{exc}</code>"
                )
            except (MessageIdInvalid, MessageNotModified):
                pass
            except Exception as err:
                await query.message.edit_caption(
                    f"Failed when requesting movies title. Maybe got rate limit or down.\n\n<b>ERROR:</b> <code>{err}</code>"
                )

@app.on_cb("imdbres_id")
async def imdb_id_callback(self: Client, query: CallbackQuery):
    i, userid, movie = query.data.split("#")
    if query.from_user.id != int(userid):
        return await query.answer("Akses Ditolak!", True)
    with contextlib.redirect_stdout(sys.stderr):
        try:
            await query.message.edit_caption("⏳ Permintaan kamu sedang diproses.. ")
            imdb_url = f"https://www.imdb.com/title/tt{movie}/"
            sop, r_json = await _get_imdb_page(imdb_url)
            ott = await search_jw(
                r_json.get("alternateName") or r_json.get("name"), "ID"
            )
            layout = await get_imdb_layout(query.from_user.id)
            typee = r_json.get("@type", "")
            tahun = (
                re.findall(r"\d{4}\W\d{4}|\d{4}-?", sop.title.text)[0]
                if re.findall(r"\d{4}\W\d{4}|\d{4}-?", sop.title.text)
                else "N/A"
            )
            parts = []
            if layout.get("title"):
                title_block = (
                    f"<b>📹 Judul:</b> <a href='{imdb_url}'>{r_json.get('name')} "
                    f"[{tahun}]</a> (<code>{typee}</code>)\n"
                )
                if aka := r_json.get("alternateName"):
                    title_block += f"<b>📢 AKA:</b> <code>{aka}</code>\n\n"
                else:
                    title_block += "\n"
                parts.append(title_block)
            if layout.get("duration"):
                durasi = sop.select('li[data-testid="title-techspec_runtime"]')
                if durasi:
                    runtime_text = (
                        durasi[0]
                        .find(class_="ipc-metadata-list-item__content-container")
                        .text
                    )
                    translated = (await gtranslate(runtime_text, "auto", "id")).text
                    parts.append(f"<b>Durasi:</b> <code>{translated}</code>\n")
            if layout.get("category") and (kategori := r_json.get("contentRating")):
                parts.append(f"<b>Kategori:</b> <code>{kategori}</code> \n")
            if layout.get("rating") and (rating := r_json.get("aggregateRating")):
                parts.append(
                    f"<b>Peringkat:</b> <code>{rating['ratingValue']}⭐️ dari "
                    f"{rating['ratingCount']} pengguna</code>\n"
                )
            if layout.get("release"):
                release = sop.select('li[data-testid="title-details-releasedate"]')
                if release:
                    rilis_node = release[0].find(
                        class_="ipc-metadata-list-item__list-content-item ipc-metadata-list-item__list-content-item--link"
                    )
                    if rilis_node:
                        rilis = rilis_node.text
                        rilis_url = rilis_node["href"]
                        parts.append(
                            f"<b>Rilis:</b> "
                            f"<a href='https://www.imdb.com{rilis_url}'>{rilis}</a>\n"
                        )
            if layout.get("genre") and (genres := r_json.get("genre")):
                genre_str = "".join(
                    f"{GENRES_EMOJI[g]} #{g.replace('-', '_').replace(' ', '_')}, "
                    if g in GENRES_EMOJI
                    else f"#{g.replace('-', '_').replace(' ', '_')}, "
                    for g in genres
                )
                parts.append(f"<b>Genre:</b> {genre_str[:-2]}\n")
            if layout.get("country"):
                negara = sop.select('li[data-testid="title-details-origin"]')
                if negara:
                    country = "".join(
                        f"{demoji(c.text)} #{c.text.replace(' ', '_').replace('-', '_')}, "
                        for c in negara[0].findAll(
                            class_="ipc-metadata-list-item__list-content-item ipc-metadata-list-item__list-content-item--link"
                        )
                    )
                    if country:
                        parts.append(f"<b>Negara:</b> {country[:-2]}\n")
            if layout.get("language"):
                bahasa = sop.select('li[data-testid="title-details-languages"]')
                if bahasa:
                    language = "".join(
                        f"#{lang.text.replace(' ', '_').replace('-', '_')}, "
                        for lang in bahasa[0].findAll(
                            class_="ipc-metadata-list-item__list-content-item ipc-metadata-list-item__list-content-item--link"
                        )
                    )
                    if language:
                        parts.append(f"<b>Bahasa:</b> {language[:-2]}\n")
            if layout.get("cast_info"):
                people = _extract_people_from_imdb(sop, r_json)
                if any(people.values()):
                    cast_block = "\n<b>🙎 Info Cast:</b>\n"
                    if people["directors"]:
                        cast_block += (
                            f"<b>Sutradara:</b> "
                            f"{_format_people_list(people['directors'])}\n"
                        )
                    if people["writers"]:
                        cast_block += (
                            f"<b>Penulis:</b> "
                            f"{_format_people_list(people['writers'])}\n"
                        )
                    if people["cast"]:
                        cast_block += (
                            f"<b>Pemeran:</b> "
                            f"{_format_people_list(people['cast'], limit=10)}\n\n"
                        )
                    parts.append(cast_block)
            if layout.get("plot") and (deskripsi := r_json.get("description")):
                summary = (await gtranslate(deskripsi, "auto", "id")).text
                parts.append(
                    f"<b>📜 Plot:</b>\n<blockquote><code>{summary}</code></blockquote>\n\n"
                )
            if layout.get("keywords") and (keywd := r_json.get("keywords")):
                key_ = "".join(
                    f"#{i.replace(' ', '_').replace('-', '_')}, "
                    for i in keywd.split(",")
                )
                parts.append(
                    f"<b>🔥 Kata Kunci:</b>\n<blockquote>{key_[:-2]}</blockquote>\n"
                )
            if layout.get("awards"):
                award = sop.select('li[data-testid="award_information"]')
                if award:
                    awards = (
                        award[0]
                        .find(class_="ipc-metadata-list-item__list-content-item")
                        .text
                    )
                    translated_award = (await gtranslate(awards, "auto", "id")).text
                    parts.append(
                        f"<b>🏆 Penghargaan:</b>\n"
                        f"<blockquote><code>{translated_award}</code></blockquote>\n"
                    )
            if layout.get("availability") and ott:
                parts.append(f"Tersedia di:\n{ott}\n")
            if layout.get("imdb_by"):
                parts.append(f"<b>©️ IMDb by</b> @{self.me.username}")
            if not parts:
                parts.append(IMDB_EMPTY_LAYOUT_NOTICE["id"])
            res_str = "".join(parts)
            trailer = r_json.get("trailer") or {}
            markup = _build_imdb_action_markup(layout, imdb_url, trailer.get("url"))
            if thumb := r_json.get("image"):
                try:
                    await query.message.edit_media(
                        InputMediaPhoto(
                            thumb, caption=res_str, parse_mode=enums.ParseMode.HTML
                        ),
                        reply_markup=markup,
                    )
                except (PhotoInvalidDimensions, WebpageMediaEmpty):
                    poster = thumb.replace(".jpg", "._V1_UX360.jpg")
                    await query.message.edit_media(
                        InputMediaPhoto(
                            poster, caption=res_str, parse_mode=enums.ParseMode.HTML
                        ),
                        reply_markup=markup,
                    )
                except (
                    MediaEmpty,
                    MediaCaptionTooLong,
                    WebpageCurlFailed,
                    MessageNotModified,
                ):
                    await query.message.reply(
                        res_str, parse_mode=enums.ParseMode.HTML, reply_markup=markup
                    )
                except Exception as err:
                    LOGGER.error(
                        f"Terjadi error saat menampilkan data IMDB. ERROR: {err}"
                    )
            else:
                await query.message.edit_caption(
                    res_str, parse_mode=enums.ParseMode.HTML, reply_markup=markup
                )
        except httpx.HTTPError as exc:
            await query.message.edit_caption(
                f"HTTP Exception for IMDB Search - <code>{exc}</code>"
            )
        except (AttributeError, ValueError) as err:
            await query.message.edit_caption(
                f"Maaf, gagal mendapatkan info data dari IMDB. {err}"
            )
        except (MessageNotModified, MessageIdInvalid):
            pass


@app.on_cb("imdbres_en")
async def imdb_en_callback(self: Client, query: CallbackQuery):
    i, userid, movie = query.data.split("#")
    if query.from_user.id != int(userid):
        return await query.answer("Access Denied!", True)
    with contextlib.redirect_stdout(sys.stderr):
        try:
            await query.message.edit_caption("<i>⏳ Getting IMDb source..</i>")
            imdb_url = f"https://www.imdb.com/title/tt{movie}/"
            sop, r_json = await _get_imdb_page(imdb_url)
            ott = await search_jw(
                r_json.get("alternateName") or r_json.get("name"), "US"
            )
            layout = await get_imdb_layout(query.from_user.id)
            typee = r_json.get("@type", "")
            tahun = (
                re.findall(r"\d{4}\W\d{4}|\d{4}-?", sop.title.text)[0]
                if re.findall(r"\d{4}\W\d{4}|\d{4}-?", sop.title.text)
                else "N/A"
            )
            parts = []
            if layout.get("title"):
                title_block = (
                    f"<b>📹 Judul:</b> <a href='{imdb_url}'>{r_json.get('name')} "
                    f"[{tahun}]</a> (<code>{typee}</code>)\n"
                )
                if aka := r_json.get("alternateName"):
                    title_block += f"<b>📢 AKA:</b> <code>{aka}</code>\n\n"
                else:
                    title_block += "\n"
                parts.append(title_block)
            if layout.get("duration"):
                durasi = sop.select('li[data-testid="title-techspec_runtime"]')
                if durasi:
                    runtime_text = (
                        durasi[0]
                        .find(class_="ipc-metadata-list-item__content-container")
                        .text
                    )
                    parts.append(f"<b>Duration:</b> <code>{runtime_text}</code>\n")
            if layout.get("category") and (kategori := r_json.get("contentRating")):
                parts.append(f"<b>Category:</b> <code>{kategori}</code> \n")
            if layout.get("rating") and (rating := r_json.get("aggregateRating")):
                parts.append(
                    f"<b>Rating:</b> <code>{rating['ratingValue']}⭐️ from "
                    f"{rating['ratingCount']} users</code>\n"
                )
            if layout.get("release"):
                release = sop.select('li[data-testid="title-details-releasedate"]')
                if release:
                    rilis_node = release[0].find(
                        class_="ipc-metadata-list-item__list-content-item ipc-metadata-list-item__list-content-item--link"
                    )
                    if rilis_node:
                        rilis = rilis_node.text
                        rilis_url = rilis_node["href"]
                        parts.append(
                            f"<b>Release:</b> "
                            f"<a href='https://www.imdb.com{rilis_url}'>{rilis}</a>\n"
                        )
            if layout.get("genre") and (genres := r_json.get("genre")):
                genre_str = "".join(
                    f"{GENRES_EMOJI[g]} #{g.replace('-', '_').replace(' ', '_')}, "
                    if g in GENRES_EMOJI
                    else f"#{g.replace('-', '_').replace(' ', '_')}, "
                    for g in genres
                )
                parts.append(f"<b>Genre:</b> {genre_str[:-2]}\n")
            if layout.get("country"):
                negara = sop.select('li[data-testid="title-details-origin"]')
                if negara:
                    country = "".join(
                        f"{demoji(c.text)} #{c.text.replace(' ', '_').replace('-', '_')}, "
                        for c in negara[0].findAll(
                            class_="ipc-metadata-list-item__list-content-item ipc-metadata-list-item__list-content-item--link"
                        )
                    )
                    if country:
                        parts.append(f"<b>Country:</b> {country[:-2]}\n")
            if layout.get("language"):
                bahasa = sop.select('li[data-testid="title-details-languages"]')
                if bahasa:
                    language = "".join(
                        f"#{lang.text.replace(' ', '_').replace('-', '_')}, "
                        for lang in bahasa[0].findAll(
                            class_="ipc-metadata-list-item__list-content-item ipc-metadata-list-item__list-content-item--link"
                        )
                    )
                    if language:
                        parts.append(f"<b>Language:</b> {language[:-2]}\n")
            if layout.get("cast_info"):
                people = _extract_people_from_imdb(sop, r_json)
                if any(people.values()):
                    cast_block = "\n<b>🙎 Cast Info:</b>\n"
                    if people["directors"]:
                        cast_block += (
                            f"<b>Director:</b> "
                            f"{_format_people_list(people['directors'])}\n"
                        )
                    if people["writers"]:
                        cast_block += (
                            f"<b>Writer:</b> "
                            f"{_format_people_list(people['writers'])}\n"
                        )
                    if people["cast"]:
                        cast_block += (
                            f"<b>Stars:</b> "
                            f"{_format_people_list(people['cast'], limit=10)}\n\n"
                        )
                    parts.append(cast_block)
            if layout.get("plot") and (description := r_json.get("description")):
                parts.append(
                    f"<b>📜 Summary:</b>\n<blockquote><code>{description}</code></blockquote>\n\n"
                )
            if layout.get("keywords") and (keywd := r_json.get("keywords")):
                key_ = "".join(
                    f"#{i.replace(' ', '_').replace('-', '_')}, "
                    for i in keywd.split(",")
                )
                parts.append(
                    f"<b>🔥 Keywords:</b>\n<blockquote>{key_[:-2]}</blockquote>\n"
                )
            if layout.get("awards"):
                award = sop.select('li[data-testid="award_information"]')
                if award:
                    awards = (
                        award[0]
                        .find(class_="ipc-metadata-list-item__list-content-item")
                        .text
                    )
                    parts.append(
                        f"<b>🏆 Awards:</b>\n"
                        f"<blockquote><code>{awards}</code></blockquote>\n"
                    )
            if layout.get("availability") and ott:
                parts.append(f"Available On:\n{ott}\n")
            if layout.get("imdb_by"):
                parts.append(f"<b>©️ IMDb by</b> @{self.me.username}")
            if not parts:
                parts.append(IMDB_EMPTY_LAYOUT_NOTICE["en"])
            res_str = "".join(parts)
            trailer = r_json.get("trailer") or {}
            markup = _build_imdb_action_markup(layout, imdb_url, trailer.get("url"))
            if thumb := r_json.get("image"):
                try:
                    await query.message.edit_media(
                        InputMediaPhoto(
                            thumb, caption=res_str, parse_mode=enums.ParseMode.HTML
                        ),
                        reply_markup=markup,
                    )
                except (PhotoInvalidDimensions, WebpageMediaEmpty):
                    poster = thumb.replace(".jpg", "._V1_UX360.jpg")
                    await query.message.edit_media(
                        InputMediaPhoto(
                            poster, caption=res_str, parse_mode=enums.ParseMode.HTML
                        ),
                        reply_markup=markup,
                    )
                except (
                    MediaCaptionTooLong,
                    WebpageCurlFailed,
                    MediaEmpty,
                    MessageNotModified,
                ):
                    await query.message.reply(
                        res_str, parse_mode=enums.ParseMode.HTML, reply_markup=markup
                    )
                except Exception as err:
                    LOGGER.error(f"Error while displaying IMDB Data. ERROR: {err}")
            else:
                await query.message.edit_caption(
                    res_str, parse_mode=enums.ParseMode.HTML, reply_markup=markup
                )
        except httpx.HTTPError as exc:
            await query.message.edit_caption(
                f"HTTP Exception for IMDB Search - <code>{exc}</code>"
            )
        except (AttributeError, ValueError) as err:
            await query.message.edit_caption(
                f"Sorry, failed getting data from IMDB. {err}"
            )
        except (MessageNotModified, MessageIdInvalid):
            pass
