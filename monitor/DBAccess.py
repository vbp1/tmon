import sqlite3, sys
import logging
from datetime import datetime

class DB:

    def __init__(self):
        self.logger = logging.getLogger('DBAccess.py')
        try:
            self.conn = sqlite3.connect('monitor.db', check_same_thread=False)
            self.curs = self.conn.cursor()
        except:
            self.logger.exception('Возникла ошибка при открытии БД.')
        finally:
            self.logger.info('БД открыта успешно.')

    def __del__(self):
        try:
           self.curs.close()
           self.conn.close()
        except:
           self.logger.exception('Возникла ошибка при закрытии БД: ')
        finally:
           self.logger.info('БД закрыта успешно.')

# Перечень всех активных мониторов всех пользователей
    def GetMonitors(self):
        self.curs.execute("""SELECT userID, channelID, searchStr, searchStr_view FROM monitors WHERE IsActive = 'True'""")
        return self.curs.fetchall()

# Добавление монитора
    def AddMon(self, uid, cid, sstr, sstr_view):
        AddTime = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        self.curs.execute("""SELECT userID FROM monitors
                             WHERE IsActive = 'True' AND userID = :uid AND channelID = :cid AND searchStr = :sstr""", 
                             {'uid': uid, 'cid': cid, 'sstr': sstr})
        status = self.curs.fetchall()
        if status == []:
            self.curs.execute("""INSERT INTO monitors (userID, channelID, searchStr, searchStr_view, AddTime, DelTime, IsActive)
                                 VALUES (:uid, :cid, :sstr, :sstr_view, :AddTime, NULL, 'True')""", 
                                 {'uid': uid, 'cid': cid, 'sstr': sstr, 'sstr_view': sstr_view, 'AddTime':AddTime})
            self.conn.commit()
            return 1
        else:
            return 0

# Удаление монитора
    def DelMon(self, uid, cid, sstr):
        DelTime = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        self.curs.execute("""UPDATE monitors SET 
                             DelTime = :DelTime, IsActive = 'False'
                             WHERE IsActive = 'True' AND userID = :uid AND channelID = :cid AND searchStr = :sstr""", 
                             {'DelTime': DelTime, 'uid': uid, 'cid': cid, 'sstr': sstr})
        self.conn.commit()
        return self.curs.rowcount
