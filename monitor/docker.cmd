docker build -t vbponomarev/monitor:Dev .

docker run  -t -d --restart=always --name monitor-dev -v /home/vbponomarev/monitor:/bothome vbponomarev/monitor:Dev

docker kill --signal=SIGHUP mytgbot
