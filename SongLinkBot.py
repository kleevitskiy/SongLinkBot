import sys
import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram import InlineQueryResultArticle, InputTextMessageContent
from telegram import ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, InlineQueryHandler, ChosenInlineResultHandler, Filters

BOT_TOKEN = sys.argv[1]
WelcomeMessage = open('WelcomeMessageShort.md').read()
SearchKeyboard = InlineKeyboardMarkup([
    [InlineKeyboardButton('\N{Right-Pointing Magnifying Glass}Search', switch_inline_query_current_chat=' ')]
    # switch_inline_query_current_chat cannot be empty!!!
])


def on_start(update, context):
    update.message.reply_text(WelcomeMessage, parse_mode=ParseMode.MARKDOWN, reply_markup=SearchKeyboard)


def on_message(update, context):
    if not update.message.reply_markup:
        for e in update.message.entities:
            if e.type == 'url':
                url = update.message.text[e.offset:e.offset + e.length]
                user_country = update.message.from_user.language_code
                links = get_links(user_country, url)
                if links:
                    update.message.reply_text(links, parse_mode=ParseMode.MARKDOWN, reply_markup=SearchKeyboard)
                else:
                    update.message.reply_text("I've found nothing\N{Disappointed Face}", reply_markup=SearchKeyboard)
                break


def get_links(user_country, url):
    def format_answer(response):
        links = response['linksByPlatform']
        answer = "I've found it on the following services:\n"
        if 'yandex' in links:
            answer = answer + '[Yandex](' + links['yandex']['url'] + ')\n'
        if 'appleMusic' in links:
            answer = answer + '[Apple Music](' + links['appleMusic']['url'] + ')\n'
        if 'google' in links:
            answer = answer + '[Google Play Music](' + links['google']['url'] + ')\n'
        if 'youtube' in links:
            answer = answer + '[YouTube](' + links['youtube']['url'] + ')\n'
        if 'youtubeMusic' in links:
            answer = answer + '[YouTube Music](' + links['youtubeMusic']['url'] + ')\n'
        if 'soundcloud' in links:
            answer = answer + '[SoundCloud](' + links['soundcloud']['url'] + ')\n'
        if 'spotify' in links:
            answer = answer + '[Spotify](' + links['spotify']['url'] + ')\n'
        if 'pandora' in links:
            answer = answer + '[Pandora](' + links['pandora']['url'] + ')\n'
        if 'deezer' in links:
            answer = answer + '[Deezer](' + links['deezer']['url'] + ')\n'
        return answer

    BaseSLAPIURL = 'https://api.song.link/v1-alpha.1/links'
    s = requests.session()
    payload = {'userCountry': user_country, 'url': url}
    r = s.get(BaseSLAPIURL, params=payload)
    if r:
        return format_answer(r.json())
    else:
        return None


def on_inlinequery(update, context):
    BaseITAPIURL = 'https://itunes.apple.com/search'
    query = update.inline_query.query
    user_country = update.inline_query.from_user.language_code
    s = requests.session()
    payload = {'term': query, 'country': user_country, 'media': 'music', 'limit': '10'}
    r = s.get(BaseITAPIURL, params=payload)
    tracks = []
    if r:
        for t in r.json()['results']:
            track = InlineQueryResultArticle(
                id=t['trackId'],
                title=t['trackName'] + ' - ' + t['artistName'],
                input_message_content=InputTextMessageContent('https://song.link/i/'+str(t['trackId'])),
                thumb_url=t['artworkUrl60'],
                reply_markup=SearchKeyboard)
            tracks.append(track)
    update.inline_query.answer(tracks,cache_time=30)


updater = Updater(BOT_TOKEN, use_context=True)
dp = updater.dispatcher
dp.add_handler(CommandHandler("start", on_start))
dp.add_handler(MessageHandler(Filters.text, on_message))
dp.add_handler(InlineQueryHandler(on_inlinequery))
updater.start_polling()
print('Listening ...')
updater.idle()
