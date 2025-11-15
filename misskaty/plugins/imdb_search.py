# * @author        Yasir Aris M <yasiramunandar@gmail.com>
# * @date          2023-06-21 22:12:27
# * @projectName   MissKatyPyro
# * Copyright ©YasirPedia All rights reserved
import asyncio
import contextlib
import html
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
    clear_custom_imdb_template,
    clear_imdb_by,
    get_custom_imdb_template,
    get_imdb_by,
    get_imdb_layout,
    is_imdbset,
    remove_imdbset,
    reset_imdb_layout,
    set_custom_imdb_template,
    set_imdb_by,
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
    ("title", "Judul"),
    ("duration", "Durasi"),
    ("category", "Kategori"),
    ("rating", "Peringkat"),
    ("release", "Rilis"),
    ("genre", "Genre"),
    ("country", "Negara"),
    ("language", "Bahasa"),
    ("cast_info", "Info Cast"),
    ("plot", "Plot"),
    ("keywords", "Kata Kunci"),
    ("awards", "Penghargaan"),
    ("availability", "Tersedia di"),
    ("imdb_by", "IMDb By"),
    ("button_open_imdb", "Open IMDb"),
    ("button_trailer", "Trailer"),
]
IMDB_LAYOUT_LABELS = dict(IMDB_LAYOUT_FIELDS)
IMDB_BUTTON_OPEN_TEXT = "🎬 Open IMDB"
IMDB_BUTTON_TRAILER_TEXT = "▶️ Trailer"
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

CUSTOM_TEMPLATE_PLACEHOLDERS = [
    ("title", "Judul utama"),
    ("title_with_year", "Judul + tahun"),
    ("title_link", "Judul + tahun versi tautan"),
    ("aka", "Judul alternatif (AKA)"),
    ("type", "Jenis konten (Movie, Series, dll)"),
    ("year", "Rentang/tahun perilisan"),
    ("duration", "Durasi (diterjemahkan untuk ID)"),
    ("duration_raw", "Durasi asli dari IMDb"),
    ("category", "Rating konten (PG-13, dll)"),
    ("rating_value", "Nilai rating IMDb"),
    ("rating_count", "Total penilai"),
    ("rating_text", "Ringkasan rating sesuai bahasa"),
    ("release", "Tanggal rilis"),
    ("release_url", "Tautan tanggal rilis"),
    ("release_link", "Tanggal rilis versi tautan"),
    ("genres", "Genre dalam bentuk hashtag"),
    ("genres_list", "Genre dipisah koma"),
    ("countries", "Daftar negara + hashtag"),
    ("countries_list", "Daftar negara biasa"),
    ("languages", "Daftar bahasa + hashtag"),
    ("languages_list", "Daftar bahasa biasa"),
    ("directors", "Daftar sutradara"),
    ("writers", "Daftar penulis"),
    ("cast", "Daftar pemeran"),
    ("plot", "Plot / summary"),
    ("keywords", "Daftar kata kunci versi hashtag"),
    ("keywords_list", "Daftar kata kunci dipisah koma"),
    ("awards", "Informasi penghargaan"),
    ("availability", "Info layanan streaming"),
    ("ott", "Data mentah dari pencarian OTT"),
    ("imdb_by", "Tagline @username bot"),
    ("imdb_url", "URL halaman IMDb"),
    ("trailer_url", "URL trailer"),
    ("poster_url", "URL poster"),
    ("imdb_code", "ID IMDb (misal tt1234567)"),
    ("locale", "Kode bahasa (id/en)"),
]

CUSTOM_TEMPLATE_BUTTON_PATTERN = re.compile(r"\[([^\[\]]+)\]\(([^)]+)\)")
PLACEHOLDER_HELP_TEXT = "\n".join(
    f"• <code>{{{key}}}</code> - {desc}"
    for key, desc in CUSTOM_TEMPLATE_PLACEHOLDERS
)
PLACEHOLDER_HELP_TEXT += (
    "\n• <code>{nama_placeholder_html}</code> - versi aman HTML "
    "(otomatis tersedia untuk setiap placeholder teks)."
)


class _SafeTemplateDict(dict):
    def __missing__(self, key):
        return ""


def _extract_template_buttons(
    text: str,
) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    buttons = []

    def _repl(match: re.Match) -> str:
        label = (match.group(1) or "").strip()
        url = (match.group(2) or "").strip()
        if label and url:
            buttons.append((label, url))
        return ""

    cleaned = CUSTOM_TEMPLATE_BUTTON_PATTERN.sub(_repl, text or "")
    if not buttons:
        return cleaned.strip(), None
    rows = []
    current_row = []
    for label, url in buttons:
        current_row.append(InlineKeyboardButton(label, url=url))
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    return cleaned.strip(), InlineKeyboardMarkup(rows)


def _render_custom_template(
    template: str, context: dict
) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    try:
        rendered = template.format_map(_SafeTemplateDict(context))
    except Exception as exc:
        raise ValueError(str(exc)) from exc
    rendered = rendered.strip()
    return _extract_template_buttons(rendered)


def _build_imdb_settings_caption(user_name: str) -> str:
    return (
        f"Halo {user_name}!\n"
        "Kelola preferensi IMDb Search kamu di sini.\n\n"
        "• 🎛 Edit Layout → pilih informasi apa saja yang tampil di hasil detail.\n"
        "• 🧩 Custom Layout → pakai template HTML sendiri.\n"
        "• 📝 IMDb By → atur nama/username yang muncul di kredit.\n"
        "• 🚩 Language → set bahasa default saat memakai /imdb.\n\n"
        "Sentuh salah satu tombol di bawah untuk memulai."
    )


def _build_imdb_settings_keyboard(user_id: int) -> InlineKeyboard:
    buttons = InlineKeyboard(row_width=1)
    buttons.row(InlineButton("🎛 Edit Layout", f"imdbslayout#{user_id}"))
    buttons.row(InlineButton("🧩 Custom Layout", f"imdbcustom#{user_id}"))
    buttons.row(InlineButton("📝 IMDb By", f"imdbbycfg#{user_id}"))
    buttons.row(InlineButton("🚩 Language", f"imdbset#{user_id}"))
    buttons.row(InlineButton("❌ Close", f"close#{user_id}"))
    return buttons


def _build_layout_caption(layout: dict, custom_active: bool = False) -> str:
    text = "Silahkan edit layout IMDb anda, tekan reset untuk kembali ke default."
    if custom_active:
        text += (
            "\n\n⚠️ Custom template sedang aktif jadi pengaturan ini akan "
            "diabaikan sampai template manual dihapus."
        )
    return text


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


async def _render_custom_layout_menu(query: CallbackQuery, user_id: int) -> None:
    template = await get_custom_imdb_template(user_id)
    status = "Aktif ✅" if template else "Belum diatur ❌"
    caption = (
        "<b>Custom Layout IMDb</b>\n"
        f"Status: <b>{status}</b>\n\n"
        "• Pakai <code>/imdbtemplate set</code> lalu balas pesan yang berisi "
        "template HTML kamu atau tulis templatenya setelah perintah.\n"
        "• Hapus dengan <code>/imdbtemplate remove</code>.\n"
        "• Format tombol: <code>[Label](https://contoh.com)</code>.\n\n"
        "Catatan: ketika template aktif, pengaturan layout bawaan diabaikan."
    )
    buttons = InlineKeyboard(row_width=1)
    if template:
        buttons.row(InlineButton("🗑 Hapus Template", f"imdbcustomrm#{user_id}"))
    buttons.row(
        InlineButton("⬅️ Back", f"imdbsettings#{user_id}"),
        InlineButton("❌ Close", f"close#{user_id}"),
    )
    with contextlib.suppress(MessageIdInvalid, MessageNotModified):
        await query.message.edit_caption(
            caption, reply_markup=buttons, parse_mode=enums.ParseMode.HTML
        )


async def _render_imdb_by_menu(query: CallbackQuery, user_id: int) -> None:
    current = await get_imdb_by(user_id)
    if current:
        status = f"Aktif ✅ (<code>{html.escape(current)}</code>)"
    else:
        status = "Belum diatur ❌"
    caption = (
        "<b>Pengaturan IMDb By</b>\n"
        f"Status: {status}\n\n"
        "<b>Cara pakai:</b>\n"
        "• Kirim <code>/imdbby @usernamekamu</code> atau teks lain.\n"
        "• Atau balas pesan berisi teks lalu kirim <code>/imdbby</code>.\n"
        "• Gunakan <code>/imdbby reset</code> untuk kembali ke default bot.\n\n"
        "Teks ini akan menggantikan label \"IMDb by\" di hasil pencarian."
    )
    buttons = InlineKeyboard(row_width=1)
    if current:
        buttons.row(InlineButton("🔁 Reset ke Default", f"imdbbyreset#{user_id}"))
    buttons.row(
        InlineButton("⬅️ Back", f"imdbsettings#{user_id}"),
        InlineButton("❌ Close", f"close#{user_id}"),
    )
    with contextlib.suppress(MessageIdInvalid, MessageNotModified):
        await query.message.edit_caption(
            caption, reply_markup=buttons, parse_mode=enums.ParseMode.HTML
        )


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


@app.on_cb("imdbcustom")
async def imdb_custom_settings(_, query: CallbackQuery):
    _, uid = query.data.split("#")
    if query.from_user.id != int(uid):
        return await query.answer("Access Denied!", True)
    await _render_custom_layout_menu(query, query.from_user.id)


@app.on_cb("imdbcustomrm")
async def imdb_custom_remove(_, query: CallbackQuery):
    _, uid = query.data.split("#")
    if query.from_user.id != int(uid):
        return await query.answer("Access Denied!", True)
    await clear_custom_imdb_template(query.from_user.id)
    await query.answer("Template custom dihapus.", show_alert=True)
    await _render_custom_layout_menu(query, query.from_user.id)


@app.on_cb("imdbbycfg")
async def imdb_by_config(_, query: CallbackQuery):
    _, uid = query.data.split("#")
    if query.from_user.id != int(uid):
        return await query.answer("Access Denied!", True)
    await _render_imdb_by_menu(query, query.from_user.id)


@app.on_cb("imdbbyreset")
async def imdb_by_reset(_, query: CallbackQuery):
    _, uid = query.data.split("#")
    if query.from_user.id != int(uid):
        return await query.answer("Access Denied!", True)
    await clear_imdb_by(query.from_user.id)
    await query.answer("IMDb by disetel ke default.", show_alert=True)
    await _render_imdb_by_menu(query, query.from_user.id)


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


async def _build_imdb_context(
    client: Client,
    soup: BeautifulSoup,
    metadata: dict,
    imdb_url: str,
    ott: str,
    locale: str,
    imdb_code: str,
    imdb_by_override: Optional[str] = None,
) -> dict:
    metadata = metadata or {}
    context = {key: "" for key, _ in CUSTOM_TEMPLATE_PLACEHOLDERS}
    title = metadata.get("name") or "N/A"
    title_text = soup.title.text if soup and soup.title else ""
    year_match = re.findall(r"\d{4}\W\d{4}|\d{4}-?", title_text)
    year = year_match[0] if year_match else "N/A"
    title_with_year = f"{title} [{year}]"
    context["title"] = title
    context["title_with_year"] = title_with_year
    context["title_link"] = f"<a href='{imdb_url}'>{html.escape(title_with_year)}</a>"
    context["aka"] = metadata.get("alternateName") or ""
    context["type"] = metadata.get("@type", "") or ""
    context["year"] = year
    context["imdb_url"] = imdb_url
    context["poster_url"] = metadata.get("image") or ""
    context["imdb_code"] = imdb_code
    context["ott"] = ott or ""
    context["availability"] = ott or ""
    context["locale"] = locale
    username = getattr(getattr(client, "me", None), "username", None)
    if not username:
        try:
            me = await client.get_me()
            username = me.username
        except Exception:
            username = None
    default_tagline = f"@{username}" if username else ""
    context["imdb_by"] = imdb_by_override or default_tagline
    runtime_node = soup.select('li[data-testid="title-techspec_runtime"]') if soup else []
    if runtime_node:
        runtime_container = runtime_node[0].find(
            class_="ipc-metadata-list-item__content-container"
        )
        if runtime_container:
            runtime_text = runtime_container.text.strip()
            context["duration_raw"] = runtime_text
            if locale == "id":
                translated = (await gtranslate(runtime_text, "auto", "id")).text
                context["duration"] = translated
            else:
                context["duration"] = runtime_text
    category = metadata.get("contentRating")
    if category:
        context["category"] = category
    rating_data = metadata.get("aggregateRating") or {}
    rating_value = rating_data.get("ratingValue")
    rating_count = rating_data.get("ratingCount")
    if rating_value is not None:
        context["rating_value"] = str(rating_value)
    if rating_count is not None:
        context["rating_count"] = str(rating_count)
    if rating_value and rating_count:
        if locale == "id":
            context["rating_text"] = (
                f"{rating_value}/10 dari {rating_count} pengguna"
            )
        else:
            context["rating_text"] = (
                f"{rating_value}/10 from {rating_count} users"
            )
    release_section = soup.select('li[data-testid="title-details-releasedate"]') if soup else []
    if release_section:
        release_node = release_section[0].find(
            class_="ipc-metadata-list-item__list-content-item ipc-metadata-list-item__list-content-item--link"
        )
        if release_node:
            release_text = release_node.text.strip()
            release_href = release_node.get("href", "")
            release_url = f"https://www.imdb.com{release_href}"
            context["release"] = release_text
            context["release_url"] = release_url
            context["release_link"] = f"<a href='{release_url}'>{html.escape(release_text)}</a>"
    genres = metadata.get("genre") or []
    if isinstance(genres, str):
        genres = [genres]
    if genres:
        genre_tags = "".join(
            f"{GENRES_EMOJI[g]} #{g.replace('-', '_').replace(' ', '_')}, "
            if g in GENRES_EMOJI
            else f"#{g.replace('-', '_').replace(' ', '_')}, "
            for g in genres
        )
        context["genres"] = genre_tags[:-2]
        context["genres_list"] = ", ".join(genres)
    origin_section = soup.select('li[data-testid="title-details-origin"]') if soup else []
    if origin_section:
        country_tags = []
        country_names = []
        for country in origin_section[0].findAll(
            class_="ipc-metadata-list-item__list-content-item ipc-metadata-list-item__list-content-item--link"
        ):
            name = country.text.strip()
            if not name:
                continue
            country_names.append(name)
            country_tags.append(
                f"{demoji(name)} #{name.replace(' ', '_').replace('-', '_')}"
            )
        if country_tags:
            context["countries"] = ", ".join(country_tags)
        if country_names:
            context["countries_list"] = ", ".join(country_names)
    language_section = soup.select('li[data-testid="title-details-languages"]') if soup else []
    if language_section:
        lang_tags = []
        lang_names = []
        for lang in language_section[0].findAll(
            class_="ipc-metadata-list-item__list-content-item ipc-metadata-list-item__list-content-item--link"
        ):
            name = lang.text.strip()
            if not name:
                continue
            lang_names.append(name)
            lang_tags.append(f"#{name.replace(' ', '_').replace('-', '_')}")
        if lang_tags:
            context["languages"] = ", ".join(lang_tags)
        if lang_names:
            context["languages_list"] = ", ".join(lang_names)
    people = _extract_people_from_imdb(soup, metadata)
    if people["directors"]:
        context["directors"] = _format_people_list(people["directors"])
    if people["writers"]:
        context["writers"] = _format_people_list(people["writers"])
    if people["cast"]:
        context["cast"] = _format_people_list(people["cast"], limit=10)
    description = metadata.get("description")
    if description:
        if locale == "id":
            context["plot"] = (await gtranslate(description, "auto", "id")).text
        else:
            context["plot"] = description
    keywords_raw = metadata.get("keywords") or ""
    if keywords_raw:
        keywords_list = [
            keyword.strip() for keyword in keywords_raw.split(",") if keyword.strip()
        ]
        if keywords_list:
            context["keywords_list"] = ", ".join(keywords_list)
            keywords_tags = "".join(
                f"#{kw.replace(' ', '_').replace('-', '_')}, " for kw in keywords_list
            )
            context["keywords"] = keywords_tags[:-2]
    awards_section = soup.select('li[data-testid="award_information"]') if soup else []
    if awards_section:
        award_text = (
            awards_section[0]
            .find(class_="ipc-metadata-list-item__list-content-item")
            .text
        )
        if award_text:
            if locale == "id":
                context["awards"] = (await gtranslate(award_text, "auto", "id")).text
            else:
                context["awards"] = award_text
    trailer = metadata.get("trailer") or {}
    if trailer.get("url"):
        context["trailer_url"] = trailer["url"]
    for key, value in list(context.items()):
        if isinstance(value, str) and not key.endswith("_html"):
            context[f"{key}_html"] = html.escape(value)
    return context


IMDB_FIELD_LABELS = {
    "id": {
        "title": "📹 Judul",
        "aka": "📢 AKA",
        "duration": "Durasi",
        "category": "Kategori",
        "rating": "Peringkat",
        "release": "Rilis",
        "genre": "Genre",
        "country": "Negara",
        "language": "Bahasa",
        "cast_header": "🙎 Info Cast",
        "directors": "Sutradara",
        "writers": "Penulis",
        "cast": "Pemeran",
        "plot": "📜 Plot",
        "keywords": "🔥 Kata Kunci",
        "awards": "🏆 Penghargaan",
        "availability": "Tersedia di",
        "imdb_by": "©️ IMDb by",
    },
    "en": {
        "title": "📹 Title",
        "aka": "📢 AKA",
        "duration": "Duration",
        "category": "Category",
        "rating": "Rating",
        "release": "Release",
        "genre": "Genre",
        "country": "Country",
        "language": "Language",
        "cast_header": "🙎 Cast Info",
        "directors": "Director",
        "writers": "Writer",
        "cast": "Stars",
        "plot": "📜 Summary",
        "keywords": "🔥 Keywords",
        "awards": "🏆 Awards",
        "availability": "Available On",
        "imdb_by": "©️ IMDb by",
    },
}


def _compose_default_caption(
    context: dict, layout: dict, locale: str
) -> str:
    labels = IMDB_FIELD_LABELS["id" if locale == "id" else "en"]
    res = ""
    if layout.get("title"):
        title_markup = context.get("title_link") or html.escape(
            context.get("title_with_year") or context.get("title") or "N/A"
        )
        type_value = html.escape(context.get("type") or "N/A")
        res += f"<b>{labels['title']}:</b> {title_markup} (<code>{type_value}</code>)\n"
        if context.get("aka"):
            res += f"<b>{labels['aka']}:</b> <code>{html.escape(context['aka'])}</code>\n\n"
        else:
            res += "\n"
    if layout.get("duration") and context.get("duration"):
        res += (
            f"<b>{labels['duration']}:</b> "
            f"<code>{html.escape(context['duration'])}</code>\n"
        )
    if layout.get("category") and context.get("category"):
        res += (
            f"<b>{labels['category']}:</b> "
            f"<code>{html.escape(context['category'])}</code> \n"
        )
    if layout.get("rating") and (
        context.get("rating_text") or context.get("rating_value")
    ):
        rating_line = context.get("rating_text")
        if not rating_line:
            rating_line = context.get("rating_value") or ""
            if context.get("rating_count"):
                rating_line = (
                    f"{rating_line}/10 ({context['rating_count']} votes)"
                )
        res += (
            f"<b>{labels['rating']}:</b> "
            f"<code>{html.escape(rating_line)}</code>\n"
        )
    if layout.get("release") and (
        context.get("release_link") or context.get("release")
    ):
        release_markup = (
            context.get("release_link")
            or html.escape(context.get("release"))
        )
        res += f"<b>{labels['release']}:</b> {release_markup}\n"
    if layout.get("genre") and context.get("genres"):
        res += f"<b>{labels['genre']}:</b> {html.escape(context['genres'])}\n"
    if layout.get("country") and context.get("countries"):
        res += (
            f"<b>{labels['country']}:</b> "
            f"{html.escape(context['countries'])}\n"
        )
    if layout.get("language") and context.get("languages"):
        res += (
            f"<b>{labels['language']}:</b> "
            f"{html.escape(context['languages'])}\n"
        )
    if layout.get("cast_info") and (
        context.get("directors")
        or context.get("writers")
        or context.get("cast")
    ):
        res += f"\n<b>{labels['cast_header']}:</b>\n"
        if context.get("directors"):
            res += (
                f"<b>{labels['directors']}:</b> "
                f"{context['directors']}\n"
            )
        if context.get("writers"):
            res += (
                f"<b>{labels['writers']}:</b> "
                f"{context['writers']}\n"
            )
        if context.get("cast"):
            res += (
                f"<b>{labels['cast']}:</b> "
                f"{context['cast']}\n\n"
            )
    if layout.get("plot") and context.get("plot"):
        res += (
            f"<b>{labels['plot']}:</b>\n"
            f"<blockquote><code>{html.escape(context['plot'])}</code></blockquote>\n\n"
        )
    if layout.get("keywords") and context.get("keywords"):
        res += (
            f"<b>{labels['keywords']}:</b>\n"
            f"<blockquote>{html.escape(context['keywords'])}</blockquote>\n"
        )
    if layout.get("awards") and context.get("awards"):
        res += (
            f"<b>{labels['awards']}:</b>\n"
            f"<blockquote><code>{html.escape(context['awards'])}</code></blockquote>\n"
        )
    if layout.get("availability") and context.get("availability"):
        res += f"{labels['availability']}:\n{context['availability']}\n"
    if layout.get("imdb_by") and context.get("imdb_by"):
        res += f"<b>{labels['imdb_by']}</b> {html.escape(context['imdb_by'])}"
    return res or IMDB_EMPTY_LAYOUT_NOTICE["id" if locale == "id" else "en"]


async def _edit_imdb_result_message(
    query: CallbackQuery,
    caption: str,
    thumb: Optional[str],
    markup: Optional[InlineKeyboardMarkup],
) -> None:
    if thumb:
        try:
            await query.message.edit_media(
                InputMediaPhoto(
                    thumb, caption=caption, parse_mode=enums.ParseMode.HTML
                ),
                reply_markup=markup,
            )
            return
        except (PhotoInvalidDimensions, WebpageMediaEmpty):
            poster = thumb.replace(".jpg", "._V1_UX360.jpg")
            await query.message.edit_media(
                InputMediaPhoto(
                    poster, caption=caption, parse_mode=enums.ParseMode.HTML
                ),
                reply_markup=markup,
            )
            return
        except (
            MediaEmpty,
            MediaCaptionTooLong,
            WebpageCurlFailed,
            MessageNotModified,
        ):
            await query.message.reply(
                caption, parse_mode=enums.ParseMode.HTML, reply_markup=markup
            )
            return
        except Exception as err:
            LOGGER.error(f"Error while displaying IMDB Data. ERROR: {err}")
    with contextlib.suppress(MessageIdInvalid, MessageNotModified):
        await query.message.edit_caption(
            caption, parse_mode=enums.ParseMode.HTML, reply_markup=markup
        )


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


async def _send_template_instructions(message: Message, user_id: int) -> None:
    template = await get_custom_imdb_template(user_id)
    status = "Aktif ✅" if template else "Belum diatur ❌"
    #preview = ""
    if template:
        snippet = html.escape(template[:800])
        #preview = f"\n\n<b>Template Saat Ini:</b>\n<code>{snippet}</code>"
    text = (
        "<b>Custom Layout IMDb</b>\n"
        f"Status: <b>{status}</b>\n\n"
        "<b>Perintah:</b>\n"
        "• <code>/imdbtemplate set</code> + template di pesan yang sama.\n"
        "• Atau balas pesan berisi template dengan <code>/imdbtemplate set</code>.\n"
        "• <code>/imdbtemplate remove</code> untuk menghapus.\n"
        "• <code>/imdbtemplate show</code> untuk melihat template.\n"
        "• Tombol dapat dibuat dengan format <code>[Label](https://contoh.com)</code>.\n\n"
        "<b>Placeholder:</b>\n"
        f"{PLACEHOLDER_HELP_TEXT}\n"
        "Contoh penggunaan: <code><blockquote>{plot_html}</blockquote></code>"
        # f"{preview}"
    )
    await message.reply_msg(
        text,
        parse_mode=enums.ParseMode.HTML,
        disable_web_page_preview=True,
    )


@app.on_cmd("imdbtemplate")
async def imdb_template_cmd(_, message: Message):
    if message.sender_chat:
        return await message.reply_msg(
            "Cannot identify user, please use in private chat.", del_in=7
        )
    if not message.from_user:
        return
    user_id = message.from_user.id
    raw = message.text or message.caption or ""
    parts = raw.split(None, 2)
    if len(parts) == 1:
        return await _send_template_instructions(message, user_id)
    action = parts[1].lower()
    if action in {"set", "save"}:
        template_body = parts[2] if len(parts) > 2 else None
        if not template_body and message.reply_to_message:
            template_body = (
                message.reply_to_message.text
                or message.reply_to_message.caption
            )
        if not template_body or not template_body.strip():
            return await message.reply_msg(
                "Silakan tulis template setelah perintah atau balas pesan yang "
                "berisi template.",
                del_in=10,
            )
        template_body = template_body.strip()
        if len(template_body) > 3500:
            return await message.reply_msg(
                "Template terlalu panjang. Maksimal 3500 karakter.",
                del_in=10,
            )
        await set_custom_imdb_template(user_id, template_body)
        return await message.reply_msg(
            "Custom layout IMDb tersimpan. Gunakan /imdb untuk mencoba.",
            del_in=8,
        )
    if action in {"remove", "reset", "clear", "delete"}:
        await clear_custom_imdb_template(user_id)
        return await message.reply_msg(
            "Template custom telah dihapus.", del_in=8
        )
    if action in {"show", "view"}:
        template = await get_custom_imdb_template(user_id)
        if not template:
            return await message.reply_msg(
                "Belum ada template custom yang tersimpan.", del_in=8
            )
        return await message.reply_msg(
            f"<b>Template Saat Ini:</b>\n<code>{html.escape(template)}</code>",
            parse_mode=enums.ParseMode.HTML,
            disable_web_page_preview=True,
        )
    await message.reply_msg(
        "Perintah tidak dikenal. Kirim <code>/imdbtemplate</code> untuk panduan.",
        parse_mode=enums.ParseMode.HTML,
        del_in=8,
    )


@app.on_cmd("imdbby")
async def imdb_by_cmd(_, message: Message):
    if message.sender_chat:
        return await message.reply_msg(
            "Cannot identify user, please use in private chat.", del_in=7
        )
    if not message.from_user:
        return
    user_id = message.from_user.id
    raw = message.text or message.caption or ""
    parts = raw.split(None, 1)
    value = parts[1].strip() if len(parts) > 1 else ""
    if not value and message.reply_to_message:
        value = (
            (message.reply_to_message.text or message.reply_to_message.caption or "")
        ).strip()
    if not value:
        current = await get_imdb_by(user_id)
        current_text = (
            f"<code>{html.escape(current)}</code>" if current else "Default bot username"
        )
        return await message.reply_msg(
            (
                "<b>Pengaturan IMDb By</b>\n"
                f"Saat ini: {current_text}\n\n"
                "Kirim <code>/imdbby @usernamekamu</code> atau balas pesan berisi teks "
                "untuk mengganti label. Gunakan <code>/imdbby reset</code> untuk "
                "kembali ke default."
            ),
            parse_mode=enums.ParseMode.HTML,
            disable_web_page_preview=True,
        )
    if value.lower() in {"reset", "default", "clear"}:
        await clear_imdb_by(user_id)
        return await message.reply_msg(
            "IMDb by dikembalikan ke default bot.", del_in=8
        )
    if len(value) > 64:
        return await message.reply_msg(
            "Teks terlalu panjang. Maksimal 64 karakter.", del_in=8
        )
    await set_imdb_by(user_id, value)
    await message.reply_msg(
        f'IMDb by diganti menjadi: <code>{html.escape(value)}</code>',
        parse_mode=enums.ParseMode.HTML,
        disable_web_page_preview=True,
        del_in=8,
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
    custom_active = bool(await get_custom_imdb_template(query.from_user.id))
    caption = _build_layout_caption(layout, custom_active)
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
    custom_active = bool(await get_custom_imdb_template(query.from_user.id))
    caption = _build_layout_caption(layout, custom_active)
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
    custom_active = bool(await get_custom_imdb_template(query.from_user.id))
    caption = _build_layout_caption(layout, custom_active)
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
    _, userid, movie = query.data.split("#")
    if query.from_user.id != int(userid):
        return await query.answer("Akses Ditolak!", True)
    with contextlib.redirect_stdout(sys.stderr):
        try:
            await query.message.edit_caption("<i>⏳ Permintaan kamu sedang diproses.. </i>")
            imdb_url = f"https://www.imdb.com/title/tt{movie}/"
            sop, r_json = await _get_imdb_page(imdb_url)
            ott = await search_jw(
                r_json.get("alternateName") or r_json.get("name"), "ID"
            )
            layout = await get_imdb_layout(query.from_user.id)
            custom_template = await get_custom_imdb_template(query.from_user.id)
            custom_imdb_by = await get_imdb_by(query.from_user.id)
            context = await _build_imdb_context(
                self, sop, r_json, imdb_url, ott, "id", f"tt{movie}", custom_imdb_by
            )
            caption = ""
            markup = None
            if custom_template:
                try:
                    caption, markup = _render_custom_template(
                        custom_template, context
                    )
                    if not caption:
                        caption = (
                            context.get("title_link")
                            or context.get("title_with_year")
                            or "IMDb Result"
                        )
                except ValueError as exc:
                    LOGGER.warning(
                        "Invalid IMDb custom template for %s: %s",
                        query.from_user.id,
                        exc,
                    )
                    await query.answer(
                        "Template IMDb kamu error. Cek /imdbtemplate untuk memperbaiki.",
                        show_alert=True,
                    )
                    caption = ""
                    markup = None
            if not caption:
                caption = _compose_default_caption(context, layout, "id")
                markup = _build_imdb_action_markup(
                    layout, imdb_url, context.get("trailer_url")
                )
            thumb = r_json.get("image")
            await _edit_imdb_result_message(query, caption, thumb, markup)
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
    _, userid, movie = query.data.split("#")
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
            custom_template = await get_custom_imdb_template(query.from_user.id)
            custom_imdb_by = await get_imdb_by(query.from_user.id)
            context = await _build_imdb_context(
                self, sop, r_json, imdb_url, ott, "en", f"tt{movie}", custom_imdb_by
            )
            caption = ""
            markup = None
            if custom_template:
                try:
                    caption, markup = _render_custom_template(
                        custom_template, context
                    )
                    if not caption:
                        caption = (
                            context.get("title_link")
                            or context.get("title_with_year")
                            or "IMDb Result"
                        )
                except ValueError as exc:
                    LOGGER.warning(
                        "Invalid IMDb custom template for %s: %s",
                        query.from_user.id,
                        exc,
                    )
                    await query.answer(
                        "Custom IMDb template error. Check /imdbtemplate.",
                        show_alert=True,
                    )
                    caption = ""
                    markup = None
            if not caption:
                caption = _compose_default_caption(context, layout, "en")
                markup = _build_imdb_action_markup(
                    layout, imdb_url, context.get("trailer_url")
                )
            thumb = r_json.get("image")
            await _edit_imdb_result_message(query, caption, thumb, markup)
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

