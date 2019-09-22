FROM python:3
ADD SongLinkBot.py /
RUN pip install telepot
RUN pip install requests
CMD [ "python", "./SongLinkBot.py" ]
