#Main file
import time
import requests
import telepot
from telepot.loop import MessageLoop
from telepot.delegate import (
    per_chat_id, create_open, pave_event_space)

BOT_TOKEN = "902181386:AAG8Hx5ov7Qqoon3KYFYBwwI-Ok2DMs7v1Q"
BaseAPIURL = 'https://api.song.link/v1-alpha.1/links'

WelcomeMessage = open('WelcomeMessageShort.md').read()

def format_answer(response):
    links = response['linksByPlatform']
    answer = 'I''ve found it on the following services:\N{Grinning Face}\n'
    if 'yandex' in links:
        answer = answer + '[Yandex](' +links['yandex']['url'] + ')\n'
    if 'appleMusic' in links:
        answer = answer + '[Apple Music](' +links['appleMusic']['url'] + ')\n'
    if 'google' in links:
        answer = answer + '[Google Play Music](' +links['google']['url'] + ')\n'
    if 'youtube' in links:
        answer = answer + '[YouTube](' +links['youtube']['url'] + ')\n'
    if 'youtubeMusic' in links:
        answer = answer + '[YouTube Music](' +links['youtubeMusic']['url'] + ')\n'
    if 'soundcloud' in links:
        answer = answer + '[SoundCloud](' +links['soundcloud']['url'] + ')\n'
    if 'spotify' in links:
        answer = answer + '[Spotify](' +links['spotify']['url'] + ')\n'
    if 'pandora' in links:
        answer = answer + '[Pandora](' +links['pandora']['url'] + ')\n'
    if 'deezer' in links:
        answer = answer + '[Deezer](' +links['deezer']['url'] + ')\n'
    return answer

class Traveler(telepot.helper.ChatHandler):
    def __init__(self, *args, **kwargs):
        super(Traveler, self).__init__(*args, **kwargs)

    def open(self, initial_msg, seed):
            self.sender.sendMessage(WelcomeMessage, parse_mode = 'Markdown')
            if initial_msg['text'].lower() == '/start':
                return True  # prevent on_message() from being called on the initial message
            else:
                return False

    def on_chat_message(self, msg):
        if msg['text'].lower() == '/start':
            self.sender.sendMessage(WelcomeMessage, parse_mode='Markdown')
        else:
            s = requests.session()
            payload = {'userCountry': msg['from']['language_code'], 'url': msg['text']}
            r = s.get(BaseAPIURL,params = payload)
            if r:
                r_message = format_answer(r.json())
                self.sender.sendMessage(r_message, parse_mode = 'Markdown')
            else:
                self.sender.sendMessage('I''ve found nothing\N{Disappointed Face}')


bot = telepot.DelegatorBot(BOT_TOKEN, [pave_event_space()(per_chat_id(), create_open, Traveler, timeout=600),])
MessageLoop(bot).run_as_thread()
print('Listening ...')
while 1:
    time.sleep(10)