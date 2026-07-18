#!/usr/bin/env python3
import html
import logging
import os
import re
import sys
from typing import Optional
from urllib.parse import parse_qs, quote, urlparse

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, InlineQueryHandler, MessageHandler, filters

MUSICLINK_API_BASE = "https://api.ml.jadquir.com/v1"
MUSICLINK_PUBLIC_BASE = "https://ml.jadquir.com"
ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
REQUEST_TIMEOUT = 15.0

PLATFORM_LABELS = {
    "musiclink": "MusicLink",
    "spotify": "Spotify",
    "apple_music": "Apple Music",
    "youtube_music": "YouTube Music",
    "youtube": "YouTube",
    "amazon_music": "Amazon Music",
    "deezer": "Deezer",
    "tidal": "TIDAL",
    "soundcloud": "SoundCloud",
    "yandex": "Yandex Music",
    "qobuz": "Qobuz",
    "pandora": "Pandora",
    "anghami": "Anghami",
    "audiomack": "Audiomack",
    "boomplay": "Boomplay",
    "napster": "Napster",
    "shazam": "Shazam",
}

API_PLATFORM_ALIASES = {
    "spotify": ("spotify",),
    "apple_music": ("apple_music", "apple-music", "apple"),
    "deezer": ("deezer",),
    "tidal": ("tidal",),
    "isrc": ("isrc",),
}

ISRC_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}\d{7}$", re.IGNORECASE)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
LOGGER = logging.getLogger(__name__)


def required_setting(name: str, argv_index: int) -> str:
    value = os.getenv(name)
    if value:
        return value.strip()
    if len(sys.argv) > argv_index and sys.argv[argv_index].strip():
        return sys.argv[argv_index].strip()
    raise SystemExit(f"Missing {name}. Set it as an environment variable or pass it as command-line argument {argv_index}.")


BOT_TOKEN = required_setting("TELEGRAM_BOT_TOKEN", 1)
MUSICLINK_API_KEY = required_setting("MUSICLINK_API_KEY", 2)

welcome_file = os.getenv("WELCOME_MESSAGE_FILE", "WelcomeMessageShort.md")
try:
    with open(welcome_file, encoding="utf-8") as f:
        WELCOME_MESSAGE = f.read()
except OSError:
    WELCOME_MESSAGE = "Send me a Spotify, Apple Music, Deezer or TIDAL track link, or use the Search button."

SEARCH_KEYBOARD = InlineKeyboardMarkup(
    [[InlineKeyboardButton("🔎 Search", switch_inline_query_current_chat=" ")]]
)


def normalize_country(language_code: Optional[str]) -> str:
    if not language_code:
        return "US"
    parts = language_code.replace("_", "-").split("-")
    if len(parts) >= 2 and len(parts[-1]) == 2:
        return parts[-1].upper()
    return "US"


def parse_music_input(value: str) -> Optional[tuple[str, str]]:
    value = value.strip()

    if ISRC_RE.fullmatch(value):
        return "isrc", value.upper()

    spotify_uri = re.fullmatch(r"spotify:track:([A-Za-z0-9]+)", value)
    if spotify_uri:
        return "spotify", spotify_uri.group(1)

    parsed = urlparse(value)
    host = parsed.netloc.lower().split(":", 1)[0]
    parts = [part for part in parsed.path.split("/") if part]

    # Inline search results use a public MusicLink URL whose ``q`` parameter
    # contains the original Apple Music track URL. Unwrap it before resolving.
    if host in {"ml.jadquir.com", "www.ml.jadquir.com"}:
        wrapped_urls = parse_qs(parsed.query).get("q")
        if wrapped_urls:
            wrapped_url = wrapped_urls[0].strip()
            if wrapped_url and wrapped_url != value:
                return parse_music_input(wrapped_url)

    if host in {"open.spotify.com", "play.spotify.com"} and len(parts) >= 2 and parts[0] == "track":
        return "spotify", parts[1]

    if host.endswith("music.apple.com") or host == "itunes.apple.com":
        query = parse_qs(parsed.query)
        track_ids = query.get("i")
        if track_ids and track_ids[0].isdigit():
            return "apple_music", track_ids[0]
        if parts and parts[-1].isdigit() and "song" in parts:
            return "apple_music", parts[-1]

    if host in {"deezer.com", "www.deezer.com", "link.deezer.com"} and "track" in parts:
        index = parts.index("track")
        if len(parts) > index + 1 and parts[index + 1].isdigit():
            return "deezer", parts[index + 1]

    if host in {"tidal.com", "listen.tidal.com"} and "track" in parts:
        index = parts.index("track")
        if len(parts) > index + 1 and parts[index + 1].isdigit():
            return "tidal", parts[index + 1]

    return None


async def call_musiclink(platform: str, identifier: str) -> Optional[dict]:
    aliases = API_PLATFORM_ALIASES.get(platform)
    if not aliases:
        return None

    headers = {
        "Authorization": f"Bearer {MUSICLINK_API_KEY}",
        "Accept": "application/json",
        "User-Agent": "SongLinkTelegramBot/3.0",
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        for alias in aliases:
            endpoint = f"{MUSICLINK_API_BASE}/lookup/{quote(alias, safe='')}/{quote(identifier, safe='')}"
            try:
                response = await client.get(endpoint, headers=headers)
            except httpx.HTTPError:
                LOGGER.exception("MusicLink request failed")
                return None

            if response.status_code in {400, 404, 405}:
                continue
            if response.status_code == 401:
                LOGGER.error("MusicLink rejected the API key")
                return None
            if response.status_code == 429:
                LOGGER.warning("MusicLink API rate limit reached")
                return None

            try:
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError):
                LOGGER.exception("Invalid MusicLink response: HTTP %s, body=%r", response.status_code, response.text[:500])
                return None

            results = payload.get("data")
            if payload.get("success") and isinstance(results, list) and results:
                return results[0]
            return None

    return None


def format_links(result: dict) -> Optional[str]:
    links = result.get("links")
    if not isinstance(links, dict):
        return None

    lines = ["I've found it on the following services:"]
    for platform, label in PLATFORM_LABELS.items():
        platform_url = links.get(platform)
        if isinstance(platform_url, str) and platform_url.startswith(("https://", "http://")):
            lines.append(f'<a href="{html.escape(platform_url, quote=True)}">{html.escape(label)}</a>')

    return "\n".join(lines) if len(lines) > 1 else None


async def resolve_links(value: str) -> Optional[str]:
    parsed = parse_music_input(value)
    if not parsed:
        return None
    platform, identifier = parsed
    result = await call_musiclink(platform, identifier)
    return format_links(result) if result else None


def prefilled_musiclink_url(source_url: str) -> str:
    return f"{MUSICLINK_PUBLIC_BASE}/?q={quote(source_url, safe='')}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    if update.effective_message:
        await update.effective_message.reply_text(
            WELCOME_MESSAGE,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=SEARCH_KEYBOARD,
            disable_web_page_preview=True,
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    message = update.effective_message
    if not message or not message.text:
        return

    candidates: list[str] = []
    for entity in message.entities or []:
        if entity.type == "text_link" and entity.url:
            candidates.append(entity.url)
        elif entity.type == "url":
            candidates.append(message.parse_entity(entity))

    text = message.text.strip()
    if ISRC_RE.fullmatch(text) or text.startswith("spotify:track:"):
        candidates.append(text)

    if not candidates:
        return

    for candidate in candidates:
        answer = await resolve_links(candidate)
        if answer:
            await message.reply_text(
                answer,
                parse_mode=ParseMode.HTML,
                reply_markup=SEARCH_KEYBOARD,
                disable_web_page_preview=True,
            )
            return

    await message.reply_text(
        "I couldn't resolve this track. Send a Spotify, Apple Music, Deezer or TIDAL track link, or a valid ISRC.",
        reply_markup=SEARCH_KEYBOARD,
    )


async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    query_object = update.inline_query
    if not query_object:
        return

    query = query_object.query.strip()
    if not query:
        await query_object.answer([], cache_time=5)
        return

    country = normalize_country(query_object.from_user.language_code)

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(
                ITUNES_SEARCH_URL,
                params={"term": query, "country": country, "media": "music", "entity": "song", "limit": 10},
                headers={"User-Agent": "SongLinkTelegramBot/3.0"},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        LOGGER.exception("iTunes Search request failed")
        await query_object.answer([], cache_time=5)
        return

    results = []
    for track in payload.get("results", []):
        track_id = track.get("trackId")
        track_name = track.get("trackName")
        artist_name = track.get("artistName")
        apple_url = track.get("trackViewUrl")

        if not all((track_id, track_name, artist_name, apple_url)):
            continue

        results.append(
            InlineQueryResultArticle(
                id=str(track_id),
                title=f"{track_name} — {artist_name}",
                description=track.get("collectionName"),
                thumbnail_url=track.get("artworkUrl100") or track.get("artworkUrl60"),
                input_message_content=InputTextMessageContent(prefilled_musiclink_url(apple_url)),
                reply_markup=SEARCH_KEYBOARD,
            )
        )

    await query_object.answer(results, cache_time=60, is_personal=False)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    LOGGER.error("Unhandled Telegram error for update %r", update, exc_info=context.error)


def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(InlineQueryHandler(inline_query))
    application.add_error_handler(error_handler)

    LOGGER.info("Listening...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
