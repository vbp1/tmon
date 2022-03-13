FROM centos:7
LABEL author="Vadim Ponomarev <vbponomarev@gmail.com>"
LABEL version=Dev
LABEL state = DevEnv
RUN yum install -y python3
RUN yum clean all
RUN pip3 install telethon
RUN  pip3 install nltk
ENV bothome /bothome
ENV LANG en_US.UTF-8
RUN mkdir ${bothome}
WORKDIR ${bothome} 
RUN python3 -m nltk.downloader stopwords
CMD python3 monitor.py
