FROM centos:7-latest
LABEL author="Vadim Ponomarev <vbponomarev@gmail.com>"
LABEL version=1
HEALTHCHECK --interval=60s --timeout=10s --retries=3 CMD curl -sS http://127.0.0.1:8000 || exit 1
RUN yum install -y python3
RUN yum clean all
RUN pip3 install python-telegram-bot==13.0 emoji
ENV appdir /app
ENV LANG en_US.UTF-8
RUN mkdir ${appdir}
WORKDIR ${appdir} 
EXPOSE 8000
CMD python3 bot.py
