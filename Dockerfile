FROM python:3
ADD SongLinkBot.py /
RUN pip install telepot
CMD [ "python", "./SongLinkBot.py" ]
