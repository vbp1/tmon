import nltk
from nltk.stem.snowball import RussianStemmer
from nltk.corpus import stopwords
import unicodedata

import logging


logger_py = logging.getLogger('parser.py')


# Парсинг слова
def ParseEntry(word, use_stopwords):
    if 'CYRILLIC' in unicodedata.name(word[0]):
        stemmer = RussianStemmer(False)
        stemmed_word = stemmer.stem(word)
        if use_stopwords:
            stop_words = stopwords.words('russian')
            stop_words.extend(['что', 'это', 'так', 'вот', 'быть', 'как', 'в', 'к', 'на'])
        else:
            stop_words = []
        if not (word in stop_words):
            if word.find(stemmed_word) != -1:
                return stemmed_word
            else:
                res = '(' + word + '|' + stemmed_word + ')'
                return res
        else:
            return ''
    else:
        return word


# Парсинг поискового запроса
def ParseStr(searchStr, splitters, replacers, use_stopwords):
    resStr = ''
    splitter = splitters.pop(0)
    replacer = replacers.pop(0)
    use_stopwords_now = use_stopwords.pop(0)
    entries = str(searchStr).split(splitter)
    entries_count = len(entries)
    for entry in entries:
        if entry != "":
            ## КОСТЫЛЬ, потом подумать как сделать изячнее
            if resStr == '':
                mod1 = ''
            else:
                mod1 = replacer
            if entries_count > 1:
                mod2 = '('
                mod3 = ')'
            else:
                mod2 = ''
                mod3 = ''
            if splitters != []:
                if str(entry).find(splitters[0]) != -1:
                    add_entry = ParseStr(entry.strip(), splitters, replacers, use_stopwords)
                else:
                    add_entry = ParseEntry(entry.strip(), use_stopwords_now)
            else:
                    add_entry = ParseEntry(entry.strip(), use_stopwords_now)
            if add_entry != '':
                resStr = resStr + mod1 + mod2 + add_entry + mod3
    return resStr


def ParseSearchStr(searchStr_raw):
    logger_py.info('  Парсинг поискового запроса: ' + searchStr_raw)
    splitters = [' ', '+']
    replacers = ['|', '.*']
    use_stopwords = [1, 0]
    searchStr = ParseStr(searchStr_raw, splitters, replacers, use_stopwords)
    logger_py.info('Распарсили. searchStr = ' + searchStr)
    return searchStr