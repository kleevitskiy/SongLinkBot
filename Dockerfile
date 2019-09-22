FROM python:3
ENV BOT_TOKEN token
ADD SongLinkBot.py /
ADD WelcomeMessageShort.md /
RUN pip install telepot
RUN pip install requests
CMD [ "python", "./SongLinkBot.py", "$BOT_TOKEN" ]
