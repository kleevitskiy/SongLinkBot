#!/usr/bin/env python3
"""
Telegram music-link bot using MusicLink instead of the deprecated Odesli API.

Compatible with python-telegram-bot 13.x.

Usage:
    python3 SongLinkBot.py <TELEGRAM_BOT_TOKEN> <MUSICLINK_API_KEY>

Optional environment variables:
    TELEGRAM_BOT_TOKEN
    MUSICLINK_API_KEY
    WELCOME_MESSAGE_FILE
"""

import html
import logging
import os
import re
import sys
from typing import Dict, Optional, Tuple
from urllib.parse import parse_qs, quote, urlparse

import requests
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
    ParseMode,
    Update,
)
from telegram.ext import (
    CallbackContext,
    CommandHandler,
    Filters,
    InlineQueryHandler,
    MessageHandler,
    Updater,
)


MUSICLINK_API_BASE = "https://api.ml.jadquir.com/v1"
MUSICLINK_PUBLIC_BASE = "https://ml.jadquir.com"
ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
REQUEST_TIMEOUT_SECONDS = 15

# Ordered list: this is also the order shown in Telegram responses.
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
    "amazon_store": "Amazon Store",
}

# MusicLink documents GET /lookup/:platform/:id. The aliases make the bot
# tolerant of naming differences for Apple Music and MusicLink routes.
API_PLATFORM_ALIASES = {
    "spotify": ("spotify",),
    "apple_music": ("apple_music", "apple-music", "apple"),
    "deezer": ("deezer",),
    "tidal": ("tidal",),
    "musiclink": ("musiclink", "ml"),
    "isrc": ("isrc",),
}

ISRC_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}\d{7}$", re.IGNORECASE)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
LOGGER = logging.getLogger(__name__)

HTTP = requests.Session()
HTTP.headers.update({"User-Agent": "SongLinkTelegramBot/2.0"})


def get_required_setting(name: str, argv_index: int) -> str:
    """Read a secret from the environment first, then from argv."""
    value = os.getenv(name)
    if value:
        return value

    if len(sys.argv) > argv_index and sys.argv[argv_index].strip():
        return sys.argv[argv_index].strip()

    raise SystemExit(
        f"Missing {name}. Set it as an environment variable or pass it "
        f"as command-line argument #{argv_index}."
    )


BOT_TOKEN = get_required_setting("TELEGRAM_BOT_TOKEN", 1)
MUSICLINK_API_KEY = get_required_setting("MUSICLINK_API_KEY", 2)

WELCOME_MESSAGE_FILE = os.getenv("WELCOME_MESSAGE_FILE", "WelcomeMessageShort.md")
try:
    with open(WELCOME_MESSAGE_FILE, "r", encoding="utf-8") as welcome_file:
        WELCOME_MESSAGE = welcome_file.read()
except OSError:
    WELCOME_MESSAGE = (
        "Send me a Spotify, Apple Music, Deezer or TIDAL track link, "
        "or use the Search button."
    )

SEARCH_KEYBOARD = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton(
                "\N{RIGHT-POINTING MAGNIFYING GLASS}Search",
                # Telegram does not accept an empty current-chat inline query.
                switch_inline_query_current_chat=" ",
            )
        ]
    ]
)


def normalize_country(language_code: Optional[str]) -> str:
    """
    Convert a Telegram language code into an iTunes country code.

    Telegram normally provides a language such as 'en' or 'ru', not a country.
    Therefore, only explicit language-region values are used as countries.
    Otherwise, use the broadly available US storefront.
    """
    if not language_code:
        return "US"

    parts = language_code.replace("_", "-").split("-")
    if len(parts) >= 2 and len(parts[-1]) == 2:
        return parts[-1].upper()

    return "US"


def extract_url(message_text: str, entity) -> Optional[str]:
    """Extract URL or text-link entities correctly, including Unicode offsets."""
    if entity.type == "text_link":
        return entity.url

    if entity.type == "url":
        return entity.parse_text(message_text)

    return None


def parse_music_input(value: str) -> Optional[Tuple[str, str]]:
    """
    Convert a supported URL or ISRC into a MusicLink platform and identifier.

    Supported inputs:
      - Spotify track URL/URI
      - Apple Music song URL containing ?i=<track_id>
      - Deezer track URL
      - TIDAL track URL
      - MusicLink song URL/public id
      - bare ISRC
    """
    value = value.strip()

    if ISRC_RE.fullmatch(value):
        return "isrc", value.upper()

    spotify_uri = re.fullmatch(r"spotify:track:([A-Za-z0-9]+)", value)
    if spotify_uri:
        return "spotify", spotify_uri.group(1)

    try:
        parsed = urlparse(value)
    except ValueError:
        return None

    host = parsed.netloc.lower().split(":", 1)[0]
    path_parts = [part for part in parsed.path.split("/") if part]

    if host in {"open.spotify.com", "play.spotify.com"}:
        if len(path_parts) >= 2 and path_parts[0] == "track":
            return "spotify", path_parts[1]

    if host.endswith("music.apple.com") or host == "itunes.apple.com":
        query = parse_qs(parsed.query)
        track_ids = query.get("i")
        if track_ids and track_ids[0].isdigit():
            return "apple_music", track_ids[0]

        # Some Apple URLs can point directly to /song/.../<track_id>.
        if len(path_parts) >= 2 and path_parts[-1].isdigit():
            if "song" in path_parts:
                return "apple_music", path_parts[-1]

    if host in {"deezer.com", "www.deezer.com", "link.deezer.com"}:
        if "track" in path_parts:
            track_index = path_parts.index("track")
            if len(path_parts) > track_index + 1:
                track_id = path_parts[track_index + 1]
                if track_id.isdigit():
                    return "deezer", track_id

    if host in {"tidal.com", "listen.tidal.com"}:
        if "track" in path_parts:
            track_index = path_parts.index("track")
            if len(path_parts) > track_index + 1:
                track_id = path_parts[track_index + 1]
                if track_id.isdigit():
                    return "tidal", track_id

    if host == "ml.jadquir.com":
        # Common forms include /song/artist/title and /.../<public_id>.
        # MusicLink's own public_id is used when it is visibly present.
        if len(path_parts) >= 2 and path_parts[0] in {"ml", "song"}:
            candidate = path_parts[-1]
            if candidate:
                return "musiclink", candidate

    return None


def call_musiclink(platform: str, identifier: str) -> Optional[dict]:
    """Call MusicLink, trying documented/compatible aliases where necessary."""
    aliases = API_PLATFORM_ALIASES.get(platform)
    if not aliases:
        return None

    headers = {
        "Authorization": f"Bearer {MUSICLINK_API_KEY}",
        "Accept": "application/json",
    }

    for alias in aliases:
        endpoint = (
            f"{MUSICLINK_API_BASE}/lookup/"
            f"{quote(alias, safe='')}/{quote(identifier, safe='')}"
        )

        try:
            response = HTTP.get(
                endpoint,
                headers=headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException:
            LOGGER.exception("MusicLink request failed")
            return None

        # Try another alias only when this route/identifier form is unknown.
        if response.status_code in {400, 404, 405}:
            LOGGER.debug(
                "MusicLink rejected alias %s with HTTP %s",
                alias,
                response.status_code,
            )
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
        except (requests.RequestException, ValueError):
            LOGGER.exception(
                "Invalid MusicLink response: HTTP %s, body=%r",
                response.status_code,
                response.text[:500],
            )
            return None

        results = payload.get("data")
        if payload.get("success") and isinstance(results, list) and results:
            return results[0]

        return None

    return None


def format_links(result: dict) -> Optional[str]:
    """Format MusicLink's result as Telegram-safe HTML."""
    links = result.get("links")
    if not isinstance(links, dict):
        return None

    lines = ["I've found it on the following services:"]

    for platform, label in PLATFORM_LABELS.items():
        platform_url = links.get(platform)
        if isinstance(platform_url, str) and platform_url.startswith(("https://", "http://")):
            lines.append(
                f'<a href="{html.escape(platform_url, quote=True)}">'
                f"{html.escape(label)}</a>"
            )

    if len(lines) == 1:
        return None

    return "\n".join(lines)


def get_links(value: str) -> Optional[str]:
    """Resolve a pasted URL or ISRC and return a formatted response."""
    parsed_input = parse_music_input(value)
    if not parsed_input:
        return None

    platform, identifier = parsed_input
    result = call_musiclink(platform, identifier)
    if not result:
        return None

    return format_links(result)


def musiclink_prefilled_url(source_url: str) -> str:
    """
    Build a free public MusicLink URL for inline-search results.

    This intentionally avoids consuming one authenticated API request for every
    result returned while the user types an inline query.
    """
    return f"{MUSICLINK_PUBLIC_BASE}/?q={quote(source_url, safe='')}"


def on_start(update: Update, context: CallbackContext) -> None:
    del context
    if update.effective_message:
        update.effective_message.reply_text(
            WELCOME_MESSAGE,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=SEARCH_KEYBOARD,
            disable_web_page_preview=True,
        )


def on_message(update: Update, context: CallbackContext) -> None:
    del context
    message = update.effective_message
    if not message or not message.text:
        return

    # Ignore messages generated by this bot's own inline results.
    if message.reply_markup:
        return

    candidates = []

    for entity in message.entities or []:
        if entity.type in {"url", "text_link"}:
            url = extract_url(message.text, entity)
            if url:
                candidates.append(url)

    # Also allow the user to send a bare ISRC or Spotify URI.
    stripped_text = message.text.strip()
    if ISRC_RE.fullmatch(stripped_text) or stripped_text.startswith("spotify:track:"):
        candidates.append(stripped_text)

    if not candidates:
        return

    for candidate in candidates:
        links = get_links(candidate)
        if links:
            message.reply_text(
                links,
                parse_mode=ParseMode.HTML,
                reply_markup=SEARCH_KEYBOARD,
                disable_web_page_preview=True,
            )
            return

    message.reply_text(
        "I couldn't resolve this track. Please send a Spotify, Apple Music, "
        "Deezer or TIDAL track link, or a valid ISRC.",
        reply_markup=SEARCH_KEYBOARD,
    )


def on_inline_query(update: Update, context: CallbackContext) -> None:
    del context
    inline_query = update.inline_query
    if not inline_query:
        return

    query = inline_query.query.strip()
    if not query:
        inline_query.answer([], cache_time=5)
        return

    country = normalize_country(inline_query.from_user.language_code)

    try:
        response = HTTP.get(
            ITUNES_SEARCH_URL,
            params={
                "term": query,
                "country": country,
                "media": "music",
                "entity": "song",
                "limit": 10,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        LOGGER.exception("iTunes Search request failed")
        inline_query.answer([], cache_time=5)
        return

    tracks = []

    for track in payload.get("results", []):
        track_id = track.get("trackId")
        track_name = track.get("trackName")
        artist_name = track.get("artistName")
        apple_url = track.get("trackViewUrl")

        if not all((track_id, track_name, artist_name, apple_url)):
            continue

        artwork_url = track.get("artworkUrl100") or track.get("artworkUrl60")
        universal_url = musiclink_prefilled_url(apple_url)

        tracks.append(
            InlineQueryResultArticle(
                id=str(track_id),
                title=f"{track_name} — {artist_name}",
                description=track.get("collectionName"),
                thumb_url=artwork_url,
                input_message_content=InputTextMessageContent(
                    universal_url,
                    disable_web_page_preview=False,
                ),
                reply_markup=SEARCH_KEYBOARD,
            )
        )

    inline_query.answer(
        tracks,
        cache_time=60,
        is_personal=False,
    )


def on_error(update: object, context: CallbackContext) -> None:
    LOGGER.error(
        "Unhandled Telegram error for update %r",
        update,
        exc_info=context.error,
    )


def main() -> None:
    updater = Updater(BOT_TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", on_start))
    dispatcher.add_handler(
        MessageHandler(
            Filters.text & ~Filters.command,
            on_message,
        )
    )
    dispatcher.add_handler(InlineQueryHandler(on_inline_query))
    dispatcher.add_error_handler(on_error)

    updater.start_polling(drop_pending_updates=True)
    LOGGER.info("Listening...")
    updater.idle()


if __name__ == "__main__":
    main()
