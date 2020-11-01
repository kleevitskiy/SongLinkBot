FROM telegrambotimage:latest
ADD SongLinkBot.py /
ADD WelcomeMessageShort.md /
ENTRYPOINT [ "python3", "./SongLinkBot.py"]
