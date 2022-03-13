FROM nginx:stable
LABEL author="Vadim Ponomarev <vbponomarev@gmail.com>"
LABEL version=1
HEALTHCHECK --interval=60s --timeout=10s --retries=3 CMD curl -sSk https://127.0.0.1:8443 || exit 1
RUN apt-get update && apt-get install -y curl && apt-get clean
ENV sslhome /etc/ssl
ENV LANG en_US.UTF-8
RUN apt-get update && apt-get install -y curl && apt-get clean
RUN mkdir -p ${sslhome} 
