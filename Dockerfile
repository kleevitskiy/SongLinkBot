FROM python:3
ADD SongLinkBot.py /
ADD WelcomeMessageShort.md /
RUN pip install telepot
RUN pip install requests
CMD [ "python", "./SongLinkBot.py" ]
