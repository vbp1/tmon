import telegram
import telegram.ext
from BotEnv import *      # Переменные окружения: токены, настройки, итд.
import logging
import re
from telegram import LabeledPrice, ReplyKeyboardMarkup, InlineKeyboardButton, \
    InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.error import (TelegramError, Unauthorized, BadRequest, 
                            TimedOut, ChatMigrated, NetworkError)
from telegram.utils.request import Request
from telegram.ext import messagequeue as mq, updater
from telegram.ext import CommandHandler, Updater, MessageHandler, Filters, \
    PreCheckoutQueryHandler, ConversationHandler, CallbackQueryHandler
from datetime import datetime
import random
import signal, os, asyncio
import Msg

# Версия бота
bot_version = '20200613'

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger('bot-UI.py')

# Меню 
menu_keyboard = [['🔍 Добавить отслеживание'], ['📋 Список отслеживаний']]


now = datetime.now()
messages_to_fwd = {} # Идентификаторы пересылаемых сообщений

q = mq.MessageQueue(all_burst_limit=10, all_time_limit_ms=3000)  # anti-flood control: 10 сообщений за 3000мс
request = Request(con_pool_size=8)

GETCHANNEL = 100
GETSEARCHSTR = 200

# anti-flood control
class MQBot(telegram.bot.Bot):
    def __init__(self, *args, is_queued_def=True, mqueue=None, **kwargs):
        super(MQBot, self).__init__(*args, **kwargs)
        self._is_messages_queued_default = is_queued_def
        self._msg_queue = mqueue or mq.MessageQueue()

    def __del__(self):
        try:
            self._msg_queue.stop()
        except:
            pass

    @mq.queuedmessage
    def send_message(self, *args, **kwargs):
        return super(MQBot, self).send_message(*args, **kwargs)

    @mq.queuedmessage
    def forward_message(self, *args, **kwargs):
        return super(MQBot, self).forward_message(*args, **kwargs)


def error(update, context):
    logger.warning('Update "%s" caused error "%s"', update, context.error)


def IsInt(s):
    try:
        int(s)
        return True
    except ValueError:
        return False



# Обработчик команды пользователя /start
def Start(update, context):
    markup = ReplyKeyboardMarkup(menu_keyboard, resize_keyboard=True)
    context.bot.send_message(chat_id=update.message.chat_id, text='👋 Привет!', reply_markup=markup)


# Обработка команды пользователя "Добавить отслеживание": Начало
def AddMon(update, context):
    logger.info('Команда добавить отслеживание от пользователя')
    context.bot.send_message(chat_id=update.message.chat_id, text='ОК, для начала определимся где будем искать.\n' + 
                             'Перешлите мне любое сообщение из канала, для которого Вы хотите добавить отслеживание.\n' +
                             '❗️ <b>ВАЖНО ❗️ Это должно быть сообщение напрямую опубликованное на этом канале (НЕ пересланное, например, туда из другого канала)!</b>' + 
                             '\n\nЕсли раздумали - \nнажмите на /cancel',
                             parse_mode=telegram.ParseMode.HTML,
                             reply_markup=ReplyKeyboardRemove())
    return GETCHANNEL


# Обработка команды пользователя "Добавить отслеживание": Определение канала
def GetChannel(update, context):
    logger.info('Команда добавить отслеживание от пользователя: пользователь прислал сообщение из канала.')
    try:
        if update.message.forward_from_chat.type == 'channel':
            logger.info('update.message.forward_from_chat = ' + str(update.message.forward_from_chat))
            ## БАГ! Не различает частные и публичные каналы. 
            context.user_data['add_channel_id'] = int(update.message.forward_from_chat.id)
            update.message.forward(int(MonitorID))
            context.bot.send_message(chat_id=update.message.chat_id, text='👍 ОК, Вы выбрали для отслеживания канал [<b>' +
                                     update.message.forward_from_chat.title + '</b>]. \nПродолжаем, теперь Вам нужно определиться ' + 
                                     'с тем, что будем искать: напишите через пробел слова, которые я буду искать в сообщениях ' + 
                                     'на указанном Вами канале. Если хотя бы одно из этих слов встретится в сообщении - я перешлю его Вам.' +
                                     '\n В словах допустимы только буквы и цифры, если нужно искать словосочетание' +
                                     '- напишите его слова через знак плюс (между словами и знаками плюс в словосочетании не должно быть пробела). ' +
                                     'Слова, состоящие менее чем из трех букв, допустимы только в словосочетаниях.' + 
                                     '\nПример запроса:\n<i>жена муж сказала зеленые+тапочки под+кроватью у+стола</i>' +
                                     '\n\nЕсли раздумали - \nнажмите на /cancel',
                                     parse_mode=telegram.ParseMode.HTML)
            logger.info('Кажется, с присланным каналом все OK, продолжаем...')
        else:
            logger.info('Присланное сообщение не из канала.')
            context.bot.send_message(chat_id=update.message.chat_id, text='🤷‍♂️ Увы, но я ищу только в публичных каналах...' + 
                                     '\nА то, что Вы прислали - не из публичного канала.' + 
                                     '\nПопробуем еще раз?' + '\n\nЕсли раздумали - \nнажмите на /cancel')
            return GETCHANNEL
    except:
        logger.exception('Ошибка при попытке обработки присланного пользователем канала.')
        context.bot.send_message(chat_id=update.message.chat_id, text='🤷‍♂️ Увы, но я ищу только в публичных каналах...' + 
                                     '\nА то, что Вы прислали - не из публичного канала.' + 
                                     '\nПопробуем еще раз?' + '\n\nЕсли раздумали - \nнажмите на /cancel')
        return GETCHANNEL
    return GETSEARCHSTR


# Обработка команды пользователя "Добавить отслеживание": Строка поиска
def GetSearchStr(update, context):
    inputstr = str(update.message.text).strip()
    # Нужно подумать как сделать нормальное добавление сложной поисковой строки
    res = []
    res.append(re.search('[^(\w \+)]', inputstr))
    res.append(re.search('( \+)|(\+ )', inputstr))
    res.append(re.search('( [\w ]{1,2} )|(^[\w ]{1,2} )|( [\w ]{1,2}$)', inputstr))
    if inputstr == '' or re.search('[^(\w \+)]', inputstr) or re.search('( \+)|(\+ )', inputstr) or re.search('( [\w ]{1,2} )|(^[\w ]{1,2} )|( [\w ]{1,2}$)', inputstr):
        logger.error('Неправильная поисковая фраза. Прислано: ' + inputstr + 'regexp checks: ' + str(res))
        context.bot.send_message(chat_id=update.message.chat_id, text='😕 Так не пойдет... <b>В словах допустимы только буквы и цифры. Слова должны идти через пробел. Если нужно искать словосочетание - его слова должны идти через знак плюс (между словами и знаками плюс в словосочетании не должно быть пробела). Слова, состоящие менее чем из трех букв допускаются только в словосочетаниях.</b>.\nПопробуем еще раз?' + '\n\nЕсли раздумали - нажмите на /cancel', parse_mode=telegram.ParseMode.HTML)
        return GETSEARCHSTR
    else:
        jsonMsg = Msg.Msg()
        logger.info('Пересылаю монитору строку поиска: ' + inputstr)
        try:
            channelID = context.user_data.pop('add_channel_id')
        except:
            logger.exception('Ошибка при попытке вытащить значение add_channel из context.user_data.')
            markup = ReplyKeyboardMarkup(menu_keyboard, resize_keyboard=True)
            context.bot.send_message(chat_id=update.message.chat_id, text='😕 Что то пошло не так... Добавление отслеживания отменено.', 
                                 reply_markup=markup)
        else:
            if jsonMsg.getjson("NEWMON", {"userID":update.message.chat_id, "channel_ID": channelID, "searchStr": inputstr}):
                SendMsgToUser(update, context, MonitorID, jsonMsg.json)
                logger.info('Отслеживание успешно отправлено монитору.')
                markup = ReplyKeyboardMarkup(menu_keyboard, resize_keyboard=True)
                context.bot.send_message(chat_id=update.message.chat_id, 
                             text='👍 ОК, отслеживание успешно отправлено на обработку. Ждем пару секунд (ну или минут, но не дольше😉)', 
                             reply_markup=markup)
            else:
                markup = ReplyKeyboardMarkup(menu_keyboard, resize_keyboard=True)
                context.bot.send_message(chat_id=update.message.chat_id, text='😕 Что то пошло не так... Добавление отслеживания отменено.', reply_markup=markup)
        return ConversationHandler.END


# Обработка команды пользователя "Добавить отслеживание": /cancel
def Cancel(update, context):
    markup = ReplyKeyboardMarkup(menu_keyboard, resize_keyboard=True)
    context.bot.send_message(chat_id=update.message.chat_id, text='🆗 ОК, все отменено!', reply_markup=markup)
    return ConversationHandler.END


# Обработка команды пользователя "Список отслеживаний"
def LsMon(update, context):
    logger.info('Команда LSMON от пользователя, пересылаю монитору')
    jsonMsg = Msg.Msg()
    if jsonMsg.getjson("LSMON", {"userID":update.message.chat_id}):
        SendMsgToUser(update, context, MonitorID, jsonMsg.json)


# Деактивация всех отслеживаний пользователя
def DelAllUserMons(update, context, userID):
    logger.info('Деактивация всех отслеживаний пользователя {}'.format(userID))
    jsonMsg = Msg.Msg()
    if jsonMsg.getjson("RMUSR", {"userID":userID}):
        SendMsgToUser(update, context, MonitorID, jsonMsg.json)


# Обработка команды пользователя удалить отслеживание
def DelMon(update, context):
    logger.info('Команда удаления отслеживания от пользователя: ' + update.message.text)
    cmd = str(update.message.text)
    i = int(cmd.split('_')[2])
    monsIndex = 'mons_' + str(update.message.chat_id)
    logger.info('monsIndex = ' + monsIndex)
    logger.info('context.bot_data[mons]: ' + str(context.bot_data[monsIndex]))
    try:
        mon = context.bot_data[monsIndex][i]
    except:
        logger.exception('Такой монитор не найден в списке context.user_data')
        SendMsgToUser(update, context, update.message.chat_id, '😕 Упс... Что то пошло не так. Наверное, можно попробовать еще раз нажать ' +
        'на кнопку [' + str(menu_keyboard[1][0]) +'] и попробовать удалить это отслеживание снова (если оно уже не удалено).')
    else:
        logger.info('mon = ' + str(mon))
        jsonMsg = Msg.Msg()
        if jsonMsg.getjson("DELMON", {"userID":update.message.chat_id, "channel_ID": mon[0], "searchStr": mon[2]}):
            SendMsgToUser(update, context, MonitorID, jsonMsg.json)
        else:
            SendMsgToUser(update, context, update.message.chat_id, '😕 Упс... Что то пошло не так. Наверное, можно попробовать еще раз нажать ' +
                          'на кнопку [' + str(menu_keyboard[1][0]) +'] и попробовать удалить это отслеживание снова (если оно уже не удалено).')


# Пересылка пришедшего сообщения списку пользователей
def FwdMsgToUsers(update, context, fwdto):
    for i in fwdto:
        logger.info('Пересылаю сообщение ' + str(update.message.forward_from_message_id) + ' из чата ' + 
                 str(update.message.forward_from_chat) + ' пользователю ' + str(i))
        try:
            promise = update.message.forward(int(i)) 
            e = promise.done
            e.wait()
            result = promise.result()
        except Unauthorized:
            # Если пользователь отключил бота - деактивируем все отслеживания такого пользователя
            logger.warning('Пользователь {} запретил боту отправку сообщений. Деактивируем все отслеживания этого пользователя.'.format(i))
            DelAllUserMons(update, context, int(i))
        except:
            logger.exception('Не удалось переслать сообщение ' + str(update.message.forward_from_message_id) + ' из чата ' + 
                 str(update.message.forward_from_chat) + ' пользователю ' + str(i))


# Отсылка сообщения пользователю
def SendMsgToUser(update, context, userID, text):
    # logger.info('Пересылаю сообщение ' + str(text) + ' пользователю ' + str(userID))
    try:
        promise = context.bot.send_message(chat_id=int(userID), text=text, parse_mode=telegram.ParseMode.HTML)
        e = promise.done
        e.wait()
        result = promise.result()
    except Unauthorized:
        # Если пользователь отключил бота - деактивируем все отслеживания такого пользователя
        logger.warning('Пользователь {} запретил боту отправку сообщений. Деактивируем все отслеживания этого пользователя.'.format(userID))
        DelAllUserMons(update, context, int(userID))
    except:
        logger.exception('Не удалось отослать сообщение ' + str(text) + ' пользователю ' + str(userID))


# Обработчик нового сообщения от монитора
def MonitorMsgHandler(update, context):
    global messages_to_fwd
    if update.message.forward_from_message_id:
        # Пришло сообщение для пересылки клиентам
        logger.info('Новое сообщение от монитора. Это сообщение для пересылки клиентам. ')
        ## БАГ! Монитор присылает 10-значный номер канала, а python-telegram-bot в свойстве update.message.forward_from_chat.id выдает 13 значное знаковое. Пока ХЗ как это победить, поэтому костыль - тупо брать последние 10 знаков из update.message.forward_from_chat.id
        msgid = str(update.message.forward_from_chat.id)[-10:] + str(update.message.forward_from_message_id)
        if msgid in messages_to_fwd.keys():
            logger.info('Сообщение с идентификатором ' + msgid + ' найдено в списке сообщений к пересылке.')
            fwdto = messages_to_fwd.pop(msgid)
            FwdMsgToUsers(update, context, fwdto)
        else:
            logger.error('Сообщение с идентификатором ' + msgid + ' НЕ найдено в списке сообщений к пересылке.')
    else:
        logger.info('Новое сообщение от монитора: ' + update.message.text)
        # Пришла команда
        jsonMsg = Msg.Msg() 
        if jsonMsg.getcmd(str(update.message.text)):
            logger.info('Команда: ' + jsonMsg.cmd)
            logger.info('Аргументы:' + str(jsonMsg.args))
            if jsonMsg.cmd == 'FWDTO':
                userIDs = jsonMsg.args["userIDs"]
                channelid = str(jsonMsg.args["channel-id"])
                messageid = str(jsonMsg.args["message-id"])
                messages_to_fwd[channelid + messageid] = userIDs
            elif jsonMsg.cmd == 'SENDTO':
                ## Разбор команды sendto
                userID = jsonMsg.args["userID"]
                text = jsonMsg.args["text"]
                SendMsgToUser(update, context, userID, text)
            elif jsonMsg.cmd == 'SHOWMON':
                ## Разбор ответа на команду lsmon 
                userID = jsonMsg.args["userID"]
                mons = jsonMsg.args["mons"]
                if mons != []:
                    i = 0
                    monsIndex = 'mons_' + str(userID)
                    logger.info('monsIndex = ' + monsIndex)
                    context.bot_data[monsIndex] = {}
                    for mon in mons:
                        i = i + 1
                        context.bot_data[monsIndex][i] = mon
                        text = "🔍 <b>Отслеживание #" + str(i) + '\nКанал: </b>' + str(mon[1]) + '\n<b>Ищем: </b>' + str(mon[3]) + '\n\nУдалить отслеживание: /delete_mon_' + str(i)
                        SendMsgToUser(update, context, userID, text)
                    logger.info('context.bot_data[mons]: ' + str(context.bot_data[monsIndex]))
                else:
                    logger.info('У пользователя ' + str(userID) + ' нет отслеживаний.')
                    text=('🤷‍♂️ Пока Вы не завели ни одного отслеживания.')
                    SendMsgToUser(update, context, userID, text)
            else:
                logger.error('Ошибка, от монитора пришла неизвестная команда ' + jsonMsg.cmd)


def main():
    logger.info('Запуск бота, версия {}'.format(bot_version))

    testbot = MQBot(API_TOKEN, request=request, mqueue=q)
    updater = Updater(bot=testbot, use_context=True)
    dp = updater.dispatcher

    jobs = updater.job_queue

#   Проверка работы JobQueue
#    for i in jobs.get_jobs_by_name(Hash_period):
#       testbot.send_message(chatId, 'Jobs:')
#       testbot.send_message(chatId, str(i))
#       i.run(dp)

    AddMonConversationHandler = ConversationHandler(
        entry_points=[MessageHandler(Filters.private & Filters.text(menu_keyboard[0]), AddMon)],
        states={
            GETCHANNEL: [MessageHandler(Filters.private & Filters.forwarded, GetChannel)], 
            GETSEARCHSTR: [MessageHandler(Filters.private & Filters.text & (~ Filters.command('cancel')), GetSearchStr)]
        },
        fallbacks=[MessageHandler(Filters.private & Filters.command('cancel'), Cancel)]
    )

    dp.add_handler(CommandHandler(command = 'start', callback = Start, filters = Filters.private))
    dp.add_error_handler(error)
    dp.add_handler(MessageHandler(Filters.private & Filters.user(MonitorID), MonitorMsgHandler))
    dp.add_handler(AddMonConversationHandler)
    dp.add_handler(MessageHandler(Filters.private & Filters.text(menu_keyboard[1]), LsMon))
    dp.add_handler(MessageHandler(Filters.private & Filters.command & Filters.regex(r'^/delete_mon_\d+$'), DelMon))
    dp.add_handler(CommandHandler(command = 'cancel', callback = Start, filters = Filters.private))

    updater.start_webhook(listen='0.0.0.0',
                          port=8000,
                          url_path=hookpath)

    logger.info('updater.start_webhook()')
    updater.idle()

    updater.stop()
    logger.info('updater.stop()')
    os.kill(os.getpid(), signal.SIGTERM)


if __name__ == '__main__':
    main()
