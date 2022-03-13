from telethon import TelegramClient, sync, events, errors
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest
import re, signal, sys, asyncio
from datetime import datetime
import logging
import DBAccess
import Msg
from monitorEnv import *
from parser import *

# Версия программы
prog_version = '20201115'

# конфигурационные данные: int(user telegram ID), int(channel telegram ID) , строка поиска
target_channel = {}
dialog_ids = {}
search_str = {}
search_str_view = {}

# Перечень контактов типа person, которым бот уже ответил
silent_list = []

# Лок для использования общего ресурса: target_channel, dialog_ids, search_str
lock_cfg = asyncio.Lock()


# БД конфигурации мониторов
confdb = DBAccess.DB()


logging.basicConfig(format='[%(levelname) 5s/%(asctime)s] %(name)s: %(message)s',level=logging.INFO)
logger = logging.getLogger('monitor.py')

client = TelegramClient(session_name, api_id, api_hash)
client.start()
client.get_dialogs()

botID = int(botID)

# Коды ошибок  и переменных
_CHANNEL_IS_PRIVATE = 200
_SUBSCRIBE_ERROR = 1000
_SUBSCRIBE_OK = 100
_ALREADY_SUBSCRIBED = 100
_LEAVE_OK = 50
_LEAVE_ERROR = 30
_USED_YET = 20
_OK = 300
_FAIL = 400


_OPERATION_JOIN = 10000
_OPERATION_LEAVE = 20000

def IsInt(s):
    try:
        int(s)
        return True
    except ValueError:
        return False


def get_conf():
  global target_channel, dialog_ids, search_str, search_str_view
  target_channel = {}
  dialog_ids = {}
  search_str = {}
  search_str_view = {}
  logger.info('----------Чтение конфигурации из базы---------------')
  input = confdb.GetMonitors()
  for row in input:
     # the life of a hash is only for the program scope and it can change as soon as the program has ended.
     item_id = hash(str(row[0])+str(row[1])+str(row[2])) 
     target_channel[item_id] = int(row[0])
     dialog_ids[item_id] = int(row[1])
     search_str[item_id] = str(row[2])
     search_str_view[item_id] = str(row[3])
     logger.info(datetime.now().strftime("%d-%m-%Y %H:%M:%S") + " customer id: " + str(target_channel[item_id]) + " | chat: " +
           str(dialog_ids[item_id]) + " | search string: " + search_str[item_id])
  logger.info('----------Чтение конфигурации завершено.---------------')

# Отсылка сообщения боту (команда SENDTO)
async def sendto(userID, text):
    jsonMsg = Msg.Msg()
    if jsonMsg.getjson("SENDTO", {"userID": userID, "text":text}):
        try:
           await client.send_message(botID, jsonMsg.json)
        except:
           logger.exception('Ошибка при отсылке сообщения боту (команда SENDTO): ')


# Отсылка сообщения боту  FWDTO
async def fwdto(fwd_to, message):
    jsonMsg = Msg.Msg()
    if jsonMsg.getjson("FWDTO", {"userIDs":fwd_to, "channel-id":message.to_id.channel_id, "message-id":message.id}):
        try:
           await client.send_message(botID, jsonMsg.json)
           await message.forward_to(botID)
        except:
           logger.exception('Ошибка при отсылке сообщения боту (команда FWDTO): ')


# Отсылка сообщения боту (формирование и отсылка ответа на команду LSMON)
async def REtoLsmon(userID, mons):
    jsonMsg = Msg.Msg()
    if jsonMsg.getjson("SHOWMON", {"userID": userID, "mons":mons}):
        try:
           await client.send_message(botID, jsonMsg.json)
        except:
           logger.exception('Ошибка при отсылке сообщения боту (формирование и отсылка ответа на команду LSMON): ')


async def CheckChannel(channel_ID, operation):
    if operation == _OPERATION_JOIN:
        # Добавляется отслеживание, если канала нет в моих подписках - пытаемся добавить
        dialogs = await client.get_dialogs()
        channels = []
        for dialog in dialogs:
          channels.append(int(dialog.id))
        if channels.count(int(channel_ID)) == 0:
           logger.info('  Такого канала в моих подписках нет, попробуем подписаться...')
           try:
              await client(JoinChannelRequest(int(channel_ID)))
           except errors.ChannelPrivateError:
              logger.exception('  Подписаться не получилось. Канал приватный.')
              return _CHANNEL_IS_PRIVATE
           except Exception:
              logger.exception('  Подписаться не получилось. Ошибка:')
              return _SUBSCRIBE_ERROR
           else:
              logger.info('  Получилось подписаться на канал.')
              return _SUBSCRIBE_OK
        else:
            logger.info('  Такой канал в моих подписках есть.')
            return _ALREADY_SUBSCRIBED
    elif operation == _OPERATION_LEAVE:
        # Удалено отслеживание, если канала больше нет ни в одном активном отслеживании - от него нужно отписаться
        # лок lock_cfg устанавается в вызывающей функции delmon
        try:
            # Python never implicitly copies objects. When you set dict2 = dict1, you are making them refer to the same exact dict object, so when you mutate it, all references to it keep referring to the object in its current state.
            dialog_ids_local = dialog_ids.copy()
        except:
            logger.exception('  Ошибка в функции CheckChannel при копировании текущей конфигурации в локальные переменные: ')
        if not (int(channel_ID) in dialog_ids_local.values()):
            logger.info('  Такого канала в активных отслеживаниях нет, попробуем отписаться...')
            try:
               await client(LeaveChannelRequest(int(channel_ID)))
            except Exception:
               logger.exception('  Отписаться не получилось. Ошибка:')
               return _LEAVE_ERROR
            else:
               logger.info('  Получилось отписаться от канала.')
               return _LEAVE_OK
        else:
             logger.info('Канал присутствует в существующих активных отслеживаниях, отписаться нельзя.')
             return _USED_YET
    else:
        logger.error('Неизвестная операция (код ' + str(operation) + ') передана в функцию проверки кинала.')


# Команда NEWMON - реакция
async def newmon(userID, channel_ID, searchStr_view):
    global target_channel, dialog_ids, search_str, search_str_view 
    logger.info('  От бота пришла команда NEWMON с параметрами userID=' + str(userID) + "; channel_ID=" + str(channel_ID) + "; searchStr=" + searchStr_view)
    searchStr = ParseSearchStr(searchStr_view.lower())
    if searchStr == '':
        return "При добавлении отслеживания случилась ошибка: поисковый запрос не содержит значимых слов."
    else:
        await lock_cfg.acquire()
        try:
            exitcode = await CheckChannel(int(channel_ID), _OPERATION_JOIN)
            if exitcode == _CHANNEL_IS_PRIVATE:
                return "❌ При добавлении отслеживания случилась ошибка: канал приватный, поэтому его отслеживание невозможно."
            elif exitcode == _SUBSCRIBE_ERROR:
                return "❌ При добавлении отслеживания случилась ошибка: невозможно подписаться на канал."
            else:
                ## БАГ! Бот присылает 13-значный номер канала со знаком, а монитор в свойстве message.to_id.channel_id выдает 10 значное беззнаковое. Пока ХЗ как это победить, поэтому костыль - тупо брать последние 10 знаков из того, что посылает бот
                channel_ID_10 = int(str(channel_ID)[-10:])
                if confdb.AddMon(userID, channel_ID_10, searchStr, searchStr_view):
                   ## Добавили монитор, ура!
                   item_id = hash(str(userID) + str(channel_ID_10) + str(searchStr)) 
                   target_channel[item_id] = int(userID)
                   dialog_ids[item_id] = int(channel_ID_10)
                   search_str[item_id] = str(searchStr)
                   search_str_view[item_id] = str(searchStr_view)
                   logger.info('  Добавлена новая запись в конфигурацию.')
                   logger.info(" customer id: " + str(target_channel[item_id]) + " | chat: " +
                         str(dialog_ids[item_id]) + " | search string: " + search_str[item_id] + 
                         " | search string view: " + search_str_view[item_id])
                   res = "✅ Отслеживание успешно добавлено!"
                else:
                   logger.info('  Попытка добавить дубль уже имеющегося отслеживания.')
                   res = "❌ При добавлении записи об отслеживании в конфигурацию произошла ошибка: такое отслеживание у вас уже есть."
        except:
           logger.exception('  При добавлении записи об отслеживании в конфигурацию произошла ошибка: ')
           res = "❌ При добавлении отслеживания случилась ошибка."
        finally:
           lock_cfg.release()
        return res

# Команда DELMON - реакция
async def delmon(userID, channel_ID, searchStr):
    global target_channel, dialog_ids, search_str
    logger.info('  От бота пришла команда DELMON с параметрами userID=' + str(userID) + "; channel_ID=" + str(channel_ID) + "; searchStr=" + searchStr)
    logger.info('  Пытаюсь выполнить.')
    await lock_cfg.acquire()
    try:
        if confdb.DelMon(userID, channel_ID, searchStr):
            ## Удалили монитор, ура!
            logger.info('  Из базы запись удалена.')
            item_id = hash(str(userID) + str(channel_ID) + str(searchStr))
            try:
                target_channel.pop(item_id)
                dialog_ids.pop(item_id)
                search_str.pop(item_id)
            except KeyError:
                logger.exception('  Ошибка при удалении записи из текущей конфигурации: ')
                res = "❌ При удалении отслеживания из текущей конфигурации случилась ошибка."
            else:
                logger.info('  Из текущей конфигурации запись удалена.')
                res = "✅ Отслеживание успешно удалено!"
            await CheckChannel(int(channel_ID), _OPERATION_LEAVE)
        else:
            logger.error('  При удалении монитора в базе такой не нашелся. Странно...')
            logger.error('  Команда DELMON с параметрами userID=' + str(userID) + "; channel_ID=" + str(channel_ID) + "; searchStr=" + searchStr)
            res = "❌ При удалении отслеживания из текущей конфигурации случилась ошибка: такое отслеживание не найдено в моей базе."
    except:
        logger.exception('  При удалении записи об отслеживании из конфигурации произошла ошибка: ')
        res = "❌ При удалении отслеживания случилась ошибка."
    finally:
        lock_cfg.release()
    return res

# Команда LSMON - реакция
async def lsmon(userID):
    logger.info('  От бота пришла команда LSMON с параметром userID=' + str(userID))
    logger.info('  Пытаюсь выполнить.')
    await lock_cfg.acquire()
    try:
       # Python never implicitly copies objects. When you set dict2 = dict1, you are making them refer to the same exact dict object, so when you mutate it, all references to it keep referring to the object in its current state.
       dialog_ids_local = dialog_ids.copy()
       target_channel_local = target_channel.copy()
       search_str_local = search_str.copy()
       search_str_view_local = search_str_view.copy()
    except:
       logger.exception('  Ошибка в функции lsmon при копировании текущей конфигурации в локальные переменные: ')
    finally:
       lock_cfg.release() 
    res = []
    if int(userID) in target_channel_local.values():
         logger.info('  Найдено как минимум одно отслеживание у этого пользователя.')
         new_tch_ids = {k: v for k, v in target_channel_local.items() if v == int(userID)}
         for i in new_tch_ids.keys():
            logger.info("  Найдено отслеживание:  customer id: " + str(new_tch_ids[i]) + " : chat ID: " + str(dialog_ids_local[i]) + " : search string: " + search_str_local[i])
            chat_entity = await client.get_entity(int(dialog_ids_local[i]))
            chat_title = chat_entity.title
            res.append([dialog_ids_local[i], chat_title, search_str_local[i], search_str_view_local[i]])
    return res

# Команда RMUSR - реакция
async def rmusr(userID):
    global target_channel, dialog_ids, search_str
    logger.info('  От бота пришла команда RMUSR с параметром userID=' + str(userID))
    logger.info('  Пытаюсь выполнить.')
    await lock_cfg.acquire()
    res = 1
    try:
        ch_to_del = {k: v for k, v in target_channel.items() if v == int(userID)}
        for i in ch_to_del.keys():
            logger.info("  Найдено отслеживание:  customer id: " + str(ch_to_del[i]) + " : chat ID: " + str(dialog_ids[i]) + " : search string: " + search_str[i] + ". Пытаюсь удалить.")
            try:
                if confdb.DelMon(ch_to_del[i], dialog_ids[i], search_str[i]):
                    ## Удалили монитор, ура!
                    logger.info('  Из базы запись удалена.')
                    channelID = dialog_ids[i]
                    try:
                        target_channel.pop(i)
                        dialog_ids.pop(i)
                        search_str.pop(i)
                    except KeyError:
                        logger.exception('  Ошибка при удалении записи из текущей конфигурации: ')
                        res = 0
                    else:
                        logger.info('  Из текущей конфигурации запись удалена.')
                        res = res * 1
                    await CheckChannel(int(channelID), _OPERATION_LEAVE)
                else:
                    logger.error('  При удалении монитора в базе такой не нашелся. Странно...')
                    logger.error('  Монитор с параметрами userID=' + str(ch_to_del[i]) + "; channel_ID=" + str(dialog_ids[i]) + "; searchStr=" + search_str[i])
                    res = 0
            except:
                logger.exception('  При удалении записи об отслеживании из конфигурации произошла ошибка: ')
                res = 0
    finally:
        lock_cfg.release()
    if res:
        logger.info('Все отслеживания пользователя {} удалены успешно.'.format(userID))
    else:
        logger.error('Во время удаления отслеживания пользователя {} были замечены ошибки. Вероятно, не все отслеживания удалены.'.format(userID))
    return res

# Реакция на сообщение от бота UI
async def bot_action(message): 
  jsonMsg = Msg.Msg()
  if jsonMsg.getcmd(str(message.message)):
    try:
        if jsonMsg.cmd == "NEWMON":
           res = await newmon(jsonMsg.args["userID"], jsonMsg.args["channel_ID"], str(jsonMsg.args["searchStr"]))
           await sendto(jsonMsg.args["userID"], res)
        elif jsonMsg.cmd == "DELMON":
           res = await delmon(jsonMsg.args["userID"], jsonMsg.args["channel_ID"], str(jsonMsg.args["searchStr"]))
           await sendto(jsonMsg.args["userID"], res)
        elif jsonMsg.cmd == "LSMON":
           res = await lsmon(jsonMsg.args["userID"])
           await REtoLsmon(jsonMsg.args["userID"], res)
        elif jsonMsg.cmd == "RMUSR":
           res = await rmusr(jsonMsg.args["userID"])
        elif jsonMsg.cmd == "":
           logger.error('  От бота пришла пустая команда. ')
        else:
           logger.error('  Не распознана пришедшая от бота команда: ' + jsonMsg.cmd)
    except:
        logger.exception('  Ошибка при работе с командами: ')


# Реакция на сообщение, появившееся в одном из каналов, на которые подписан робот
async def usr_action(message): 
  if hasattr(message.to_id, 'channel_id'):
    await lock_cfg.acquire()
    try:
       # Python never implicitly copies objects. When you set dict2 = dict1, you are making them refer to the same exact dict object, so when you mutate it, all references to it keep referring to the object in its current state.
       dialog_ids_local = dialog_ids.copy()
       target_channel_local = target_channel.copy()
       search_str_local = search_str.copy()
    except:
       logger.exception('  Ошибка в функции usr_action при копировании текущей конфигурации в локальные переменные: ')
    finally:
       lock_cfg.release() 
    logger.info('  Пришло сообщение из канала ' + str(message.to_id.channel_id))
    if int(message.to_id.channel_id) in dialog_ids_local.values():
         fwd_to = []
         logger.info('  Найдено как минимум одно совпадение отслеживаемого канала.')
         new_dialog_ids = {k: v for k, v in dialog_ids_local.items() if v == int(message.to_id.channel_id)}
         for i in new_dialog_ids.keys():
            logger.info("  Найдено совпадение отслеживаемого канала для customer id: " +
              str(target_channel_local[i]) + " : chat ID: " + str(new_dialog_ids[i]) + " : search string: " + search_str_local[i])
            res = re.search(str(search_str_local[i]), str(message.message).lower())
            if res:
               fwd_to.append(target_channel_local[i])
               logger.info(' Будет переслано для ' + str(target_channel_local[i]) + ': ' + 
                    str(dialog_ids_local[i]) + ' : ' + str(search_str_local[i]) + " : " + str(res))
         if len(fwd_to) > 0:
            await fwdto(fwd_to, message)
  await message.mark_read()
  return 0


@client.on(events.NewMessage)
async def normal_handler(event):     
    if event.is_private:
        if (not event.message.out) and event.message.from_id:
            from_user = await client.get_entity(event.message.from_id)
            if (from_user.id == botID) and (not event.message.fwd_from):
                logger.info('  Сообщение от бота. Содержание: '+ str(event.message.message))
                await bot_action(event.message)
                await event.message.mark_read()
            else:
                if from_user.id != botID:
                    logger.info('  Сообщение от пользователя ' + str(from_user.username) + '[ID ' + str(from_user.id) + ']')
                    logger.info('  Содержание сообщения: '+ str(event.message.message))
                    if from_user.id not in silent_list:
                        await event.message.respond('Этот аккаунт является техническим. Сообщения, направленные на него, никем не читаются. Если Вам нужно связаться с владельцем этого аккаунта - пишите на @vbponomarev.')
                        silent_list.append(from_user.id)
                    await event.message.mark_read()
    else:
       logger.info('  Hook сработал! Вызов обрабатывающей функции.')
       await usr_action(event.message)
       logger.info('  Обработка завершена.\n')


async def sigterm_handler():
    global confdb
    logger.info(' Получен сигнал SIGTERM.\n')
    await client.disconnect()
    del confdb
    loop = asyncio.get_event_loop()
    loop.shutdown_asyncgens()
    logger.info(' Выход из программы.\n')
    try:
       loop.close()
    except:
       pass

logger.info('Запуск монитора, версия {}'.format(prog_version))

get_conf()

loop = asyncio.get_event_loop()
loop.add_signal_handler(getattr(signal, 'SIGTERM'), asyncio.async, sigterm_handler())

logger.warning('----------Начало работы приложения---------------\n')

client.catch_up()

client.run_until_disconnected()


