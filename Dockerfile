FROM telegrambotimage:latest
ENV BOT_TOKEN token
ADD SongLinkBot.py /
ADD WelcomeMessageShort.md /
ENTRYPOINT [ "python", "./SongLinkBot.py"]
