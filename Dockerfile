FROM telegrambotimage:latest
ADD SongLinkBot.py /
ADD WelcomeMessageShort.md /
ENTRYPOINT [ "python", "./SongLinkBot.py"]
