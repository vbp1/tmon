import json, sys
import logging
from datetime import datetime

class Msg:

    def __init__(self):
        self.logger = logging.getLogger('Msg.py')
        self.cmd = ""
        self.args = {}
        self.json = ""


    def getjson(self, input_cmd, input_args):
       data = {"cmd":input_cmd, "args":input_args}
       try:
         self.json = json.dumps(data, ensure_ascii=False)
         self.cmd = input_cmd
         self.args = input_args
         return 1
       except:
         self.logger.exception('Возникла ошибка при преобразовании команды в JSON: ')
         return 0
    
    def getcmd(self, input_json):
       try:
         msg_raw = json.loads(input_json)
         self.cmd = msg_raw["cmd"]
         self.args = msg_raw["args"]
         self.json = input_json
         return 1
       except:
         self.logger.exception('Возникла ошибка при преобразовании JSON в команду: ')
         return 0