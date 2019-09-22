FROM python:3
ADD SongLinkBot.py /
RUN pip install requests
RUN pip install telepot
CMD [ "python", "./SongLinkBot.py" ]
