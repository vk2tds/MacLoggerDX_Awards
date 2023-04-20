#!/usr/local/python3

# This code was developed for MacOS but should work under Windows and Linux

# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public 
# License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty 
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
# You should have received a copy of the GNU General Public License along with this program. If not, 
# see <https://www.gnu.org/licenses/>.

# Having said that, it would be great to know if this software gets used. If you want, buy me a coffee, or send me some hardware
# Darryl Smith, VK2TDS. darryl@radio-active.net.au Copyright 2023

# mode == FT8, USB, LSB, etc
# band_tx == 20M
#/usr/libexec/PlistBuddy ~/Documents/MLDX_Logs/mode_mapping.plist 

import sqlite3
import logging
import logging.handlers
import pprint
import sys
import re 
import os
import urllib.request
import datetime
import json
from dicttoxml import dicttoxml
from xml.dom.minidom import parseString
from collections import OrderedDict
import tabulate




# Change root logger level from WARNING (default) to NOTSET in order for all messages to be delegated.
logging.getLogger().setLevel(logging.NOTSET)

# Add stdout handler, with level INFO
console = logging.StreamHandler(sys.stdout)
console.setLevel(logging.INFO)
formater = logging.Formatter('%(name)-13s: %(levelname)-8s %(message)s')
console.setFormatter(formater)
logging.getLogger().addHandler(console)
logging.getLogger("dicttoxml").setLevel(logging.WARNING)
log = logging.getLogger("app." + __name__)

pp = pprint.PrettyPrinter(indent=4)



qso_table = 'qso_table_v008'

conditions = {"no_maritime": " not call like '%/MM' and ",
              "LoTW": " qsl_received like '%LoTW%' and ",
              "eQSL": " qsl_received like '%eQSL%' and ",
              "LoTWeQSL": " (qsl_received like '%LoTW%' or qsl_received like '%eQSL%') and ",
              "startDXCC": " select count (distinct dxcc_country) ",
              "startCQWAZ": " select count ( distinct iif (substr(cq_zone,1,1) == '0', substr(cq_zone,2), cq_zone)) ",
              "startCQWAZ_BAND": " select distinct count(distinct iif (substr(cq_zone,1,1) == '0', substr(cq_zone,2), cq_zone)), mode , band_rx from ( select  count(*) as c, cq_zone, mode, band_rx ",
              "stopCQWAZ_BAND": " group by  cq_zone, mode, band_rx ) group by mode, band_rx ",
              "WAS": " (dxcc_id = 291 or dxcc_id = 6 or dxcc_id = 110) and ",
              "from": " from " + qso_table + " where ",
              "end": " True "}

#select distinct state, band_rx, mode from qso_table_v008 
#where (dxcc_id = 291 or dxcc_id = 6 or dxcc_id = 110) 
#group by band_rx, mode, state







def doINIT():
    global conditions
    global data_mode
    global phone_mode
    global cw_mode
    global am_mode
    global ssb_mode
    global rtty_mode
    global all_mode

    global oceania
    global commonwealth
    global bands

    data_mode = ["LSB-D", "LSB-D2", "LSB-D3", "USB-D", "USB-D2", "USB-D3", "FM-D", "FM-D2", "FM-D3", "AM-D", "AM-D2", "AM-D3", "DIGITAL", 
            "FSK", "FSK-R", "RTTY", "RTTY-R", "RTTY-L", "RTTY-U", "Packet", "PKT-FM", "PKT-U", "PKT-L", "Data", "Data-L", "Data-R", 
            "Data-U", "Data-FM", "Data-FMN", "PSK", "PSK-R", "FT8", "Spectral", ]

    cw_mode = ["CW", "CW-R", "CW Wide", "CW Narrow", "UCW", "LCW"]

    phone_mode = ["DV", "P25", "C4FM", "FDV", "DRM", "LSB", "LSB Sync", "USB", "USB Sync", "Double SB", "FM", "FM Wide", "FM Narrow", 
                "AM", "AM Wide", "AM Narrow", "AM Sync"]

    am_mode = ["AM", "AM Wide", "AM Narrow", "AM Sync"]

    ssb_mode = ["LSB", "LSB Sync", "USB", "USB Sync"]

    rtty_mode = ["RTTY", "RTTY-R", "RTTY-L", "RTTY-U"]

    all_mode = data_mode + cw_mode + phone_mode 

    oceania = (247,176,489,460,511,190,46,160,157,375,191,234,188,162,512,175,508,509,298,185,507,177,166,20,103,123,174,197,110,138,9,515,297,163,282,301,31,48,490,22,173,168,345,150,153,38,147,171,189,303,35,172,513,327,158,270,170,34,133,16)
    commonwealth = (223, 114,265,122,279,106,294,233,257,402,322,181,379,406,464,33,452,250,205,274,493,201,4,165,207,468,470,450,286,430,432,440,
        424,482,458,454,60,77,97,95,98,94,66,249,211,252,12,65,96,89,64,69,82,62,111,153,235,238,240,241,141,129,90,372,
        305,324,11,142,283,315,215,159,299,247,381,160,157,191,234,188,185,507,163,282,301,31,48,490,345,150,35,38,147,189,172,513,
        158,270,170,34,133, 16, 190, 46, 176, 489, 460)

    #ToDO Extend this
    # Unused
    bands = ["160M", "80M", "40M", "30M", "20M", "17M", "15M", "12M", "10M", "6M", "2M", "70CM"]

    data_statement = " (False "
    for d in data_mode:
        data_statement = data_statement + " or mode = '" + d + "' "
    data_statement = data_statement + " ) and "
    #log.debug (data_statement)
    conditions["DATA"] = data_statement

    cw_statement = " (False "
    for d in cw_mode:
        cw_statement = cw_statement + " or mode = '" + d + "' "
    cw_statement = cw_statement + " ) and "
    #log.debug (cw_statement)
    conditions["CW"] = cw_statement

    phone_statement = " (False "
    for d in phone_mode:
        phone_statement = phone_statement + " or mode = '" + d + "' "
    phone_statement = phone_statement + " ) and "
    #log.debug (phone_statement)
    conditions["PHONE"] = phone_statement

    am_statement = " (False "
    for d in am_mode:
        am_statement = am_statement + " or mode = '" + d + "' "
    am_statement = am_statement + " ) and "
    #log.debug (am_statement)
    conditions["AM"] = am_statement

    ssb_statement = " (False "
    for d in ssb_mode:
        ssb_statement = ssb_statement + " or mode = '" + d + "' "
    ssb_statement = ssb_statement + " ) and "
    #log.debug (ssb_statement)
    conditions["SSB"] = ssb_statement

    rtty_statement = " (False "
    for d in rtty_mode:
        rtty_statement = rtty_statement + " or mode = '" + d + "' "
    rtty_statement = rtty_statement + " ) and "
    #log.debug (rtty_statement)
    conditions["RTTY"] = rtty_statement


















def doDatabase():
    global conn
    global cur

    #ToDo: Move database name to settings
    conn = sqlite3.connect ("/Users/darryl/Documents/MLDX_Logs/MacLoggerDX.sql")
    cur = conn.cursor()




def doGetDXCC_Continent():
    # https://gitlab.com/andreas_krueger_py/call_to_dxcc/-/blob/master/call_to_dxcc/__init__.py

    #  This Function: ->
    #
    #  Copyright 2019 Andreas Krüger, DJ3EI
    #
    #  Licensed under the Apache License, Version 2.0 (the "License");
    #  you may not use this file except in compliance with the License.
    #  You may obtain a copy of the License at
    #
    #      http://www.apache.org/licenses/LICENSE-2.0
    #
    #  Unless required by applicable law or agreed to in writing, software
    #  distributed under the License is distributed on an "AS IS" BASIS,
    #  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
    #  See the License for the specific language governing permissions and
    #  limitations under the License.

    dxcc_file = "dxcc.txt"
    if not os.path.exists(dxcc_file):
        dxcc_uri = "http://www.arrl.org/files/file/DXCC/2019_Current_Deleted(3).txt"
        dxcc_file, headers = urllib.request.urlretrieve(dxcc_uri, filename="dxcc.txt")

    continents = {}
    with open(dxcc_file, mode="r", encoding="UTF-8") as dxcc_in:
        dxcc_txt = dxcc_in.read()
        parse_state = "SEARCHING_FOR_LIST"
        table_top = re.compile("[_ ]+")
        empty_line = re.compile(" *")
        data_line = re.compile(r"\s+([0-9A-Z,_\-\/]+)" \
                            r"(?:\#?\*?\(\d+\),?)*\#?\^?\*?\s+" \
                            r"(.*?)\s+" \
                            r"([A-Z]{2}(?:,[A-Z]{2})?)\s+" \
                            r"(\d{2}(?:[,\-]\d{2})?|\([A-Z]\))\s+" \
                            r"(\d{2}(?:[,\-]\d{2})?|\([A-Z]\))\s+0*(\d+?)(?:\s*?)")
        for line in dxcc_txt.splitlines():
            if parse_state == "SEARCHING_FOR_LIST":
                if table_top.fullmatch(line):
                    parse_state = "TABLE"
            elif empty_line.fullmatch(line):
                break
            else:
                split = data_line.fullmatch(line)
                if not split:
                    if "Spratly Is." in line:
                        pass # This is messy. Don't care about it.
                    else:
                        raise RuntimeError("Ooops. Code is broken, cannot handle: \"{}\".".format(line))
                else:
                    call_prefixes, name, continent, dxcc_number = split.group(1), split.group(2), split.group(3), int(split.group(6))
                    # print((call_prefixes, name, continent, dxcc_number))
                    continents[dxcc_number] = continent
    return continents


def doGetDXCC_table():


    dxcc_lotw_confirmed = 'select count(call), band_tx, dxcc_country from ' + qso_table + ' where '
    dxcc_qso_confirmed = 'select count(call), band_tx, dxcc_country from ' + qso_table + ' where '

    dxcc_lotw_confirmed += conditions['no_maritime'] + conditions['LoTW'] + ' True '
    dxcc_qso_confirmed += conditions['no_maritime'] + ' True '

    dxcc_lotw_confirmed += ' group by dxcc_country, band_tx'
    dxcc_qso_confirmed += ' group by dxcc_country, band_tx'

    awards['ARRL']['DXCC']['Table'] = {}
    working = {}

    res = cur.execute (dxcc_qso_confirmed)
    details = res.fetchall()

    for count, band_tx, dxcc_country in details:
        if not dxcc_country in working:
            working[dxcc_country] = OrderedDict()
            working[dxcc_country]['160M'] = None
            working[dxcc_country]['80M'] = None
            working[dxcc_country]['40M'] = None
            working[dxcc_country]['30M'] = None
            working[dxcc_country]['20M'] = None
            working[dxcc_country]['17M'] = None
            working[dxcc_country]['15M'] = None
            working[dxcc_country]['12M'] = None
            working[dxcc_country]['10M'] = None
            working[dxcc_country]['6M'] = None
        if band_tx in working[dxcc_country]:
            working[dxcc_country][band_tx] = str(count)

    res = cur.execute (dxcc_lotw_confirmed)
    details = res.fetchall()

    for count, band_tx, dxcc_country in details:

        #print ( dxcc_country, band_tx, working[dxcc_country][band_tx] )
        working[dxcc_country][band_tx] =  working[dxcc_country][band_tx] + "," + str(count)

    for country in working:
        for band in working[country]:
            s = working[country][band]
            if s is None or s == '':
                working[country][band] = '-'
            elif ',' in s:
                (qso, lotw) = s.split(',')
                working[country][band] = '%s/%s' % (lotw, qso)
            else:
                print (s)
                working[country][band] = '0/' + s

    #pprint.pprint (working)
    tab = []
    for country in working:
        tabC = [country]
        for band in working[country]:
            tabC.append (working[country][band])
        tab.append (tabC)
    header = ['Country', '160M', '80M', '40M', '30M', '17M', '15M', '12M', '10M', '6M']

    awards['ARRL']['DXCC']['Table'] = tabulate.tabulate(tab, headers=header)

def doSTATS_QSL ():
    global awards

    expr = "With A as "
    expr += "(select  count(call) as COUNT_ALL "
    expr += conditions['from']
    expr += conditions['no_maritime'] + " True), "

    expr += "B as "
    expr += "(select  count(call) as COUNT_LOTW "
    expr += conditions['from']
    expr += conditions['LoTW']
    expr += conditions['no_maritime'] + " True), "

    expr += "C as "
    expr += "(select  count(call) as COUNT_EQSL "
    expr += conditions['from']
    expr += conditions['eQSL']
    expr += conditions['no_maritime'] + " True), "

    expr += "D as "
    expr += "(select count(call) as COUNT_LOTWEQSL " 
    expr += conditions['from']
    expr += conditions['LoTWeQSL']
    expr += conditions['no_maritime'] + " True) "
    expr += " select * from A, B, C, D"

    res = cur.execute (expr)
    details = res.fetchone()


    awards['STATS']['STATS_QSL'] = {'Total': details[0], 'LoTW_Total': details[1], 'eQSL_Total': details[2], 'LoTWeQSL_Total': details[3],
                                    'Notes': ' Any mode, no Maritime'}



def doSTATS_BANDS ():
    global awards

    expr = "select count(*), band_rx "
    expr += conditions ['from']
    expr += " true group by band_rx"

    res = cur.execute (expr)
    details = res.fetchall()
    combined = []
    
    awards['STATS']['STATS_BANDS'] = {}
    for count, band in details:
        #combined.append ({'Count': count, 'Band': band})
        awards['STATS']['STATS_BANDS'][band] = count

    #awards['STATS']['STATS_BANDS'] = combined

def doSTATS_MODES ():
    global awards

    #log.info ("      QSO by Mode")
    expr = "select count(*), mode "
    expr += conditions ['from']
    expr += " true group by mode"

    res = cur.execute (expr)
    details = res.fetchall()
    combined = []
    awards['STATS']['STATS_MODES'] = {}
    for count, mode in details:
        #combined.append ({'Count': count, 'Mode': mode})
        awards['STATS']['STATS_MODES'][mode] = count
    #log.info ("        Modes - %s" %(['STATS_MODES']))


def doSTATS_GRIDS ():
    global awards
    
    # https://www.amsat.org/amsat/articles/houston-net/grids.html
    awards['STATS']['STATS_GRIDS'] = {}
    awards['STATS']['STATS_GRIDS']['Notes'] = 'Fields are two letter grids squares. Grids are four letter ones. Does not check for QSL'

    expr = "select count(*), substr(grid,1,2) "
    expr += conditions ['from']
    expr += " grid is not NULL and grid != '' group by substr(grid,1,2)"

    res = cur.execute (expr)
    details = res.fetchall()
    combined = []
    awards['STATS']['STATS_GRIDS']['Fields'] = len(details)
    awards['STATS']['STATS_GRIDS']['Fields_Count'] = '324'

    expr = "select count(*), substr(grid,1,4) "
    expr += conditions ['from']
    expr += " grid is not NULL and grid != '' group by substr(grid,1,4)"

    res = cur.execute (expr)
    details = res.fetchall()
    combined = []
    awards['STATS']['STATS_GRIDS']['Grids'] = len(details)
    awards['STATS']['STATS_GRIDS']['Grids_Count'] = '32400'


def doSTATS_MISSINGDXCCCONFIRM ():
    global awards

    expr = "select dxcc_country"
    expr += conditions ['from'] 
    expr += " dxcc_country not in "
    expr += "(select DISTINCT dxcc_country "
    expr += conditions ['from'] 
    expr += conditions['LoTW']
    expr += conditions['no_maritime'] + " True) "
    expr += ' AND ' + conditions['no_maritime'] + " True "

    res = cur.execute (expr)

    awards['STATS']['STATS_MISSINGDXCCCONFIRM'] = {}

    i = 1
    for k in res:
        awards['STATS']['STATS_MISSINGDXCCCONFIRM']["%s " % (k[0])] = 'Missing QSL'
        i += 1



 


def doSTATS_DXCCBYDATE ():
    global awards

    #log.info ("      DXCC BY DATE")
    expr = "select dxcc_country, qso_done"
    expr += conditions ['from'] 
    expr += " dxcc_country in "
    expr += "(select DISTINCT dxcc_country "
    expr += conditions ['from'] 
    expr += conditions['LoTW']
    expr += conditions['no_maritime'] + " True) "
    expr += " AND " + conditions['LoTW']
    expr += conditions['no_maritime'] + " True "
    expr += "order by dxcc_country, qso_done"

    #print (expr)

    res = cur.execute (expr)

    last_dxcc = ""
    awards['STATS']['STATS_DXCCBYDATE'] = {}
    stats = {}
    for dxcc, day in res.fetchall():
        if dxcc != last_dxcc:
            day = str(datetime.datetime.fromtimestamp(day))
            #awards['STATS']['STATS_DXCCBYDATE'].append ({'DXCC':dxcc, 'Day':day})
            stats[dxcc] = day[:19]
            last_dxcc = dxcc
    #log.info ("        Modes - %s" %(awards['STATS']['STATS_DXCCBYDATE']))
    stats = {k: v for k, v in sorted(stats.items(), key=lambda item: item[1])}    
    i = 1
    for k in stats:
        awards['STATS']['STATS_DXCCBYDATE']["%03d " % (i) + k] = stats[k]
        i += 1


def doCQWAZ_MIXED ():
    global awards

    expr = conditions['startCQWAZ'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTWeQSL'] + "cq_zone != '' and cq_zone != '1-5' and " + conditions['end']
    res = cur.execute (expr)
    awards['CQ']['CQWAZ']['CQWAZ_MIXED'] = {'Contacts':res.fetchone()[0], 'Required':40}


def doCQWAZ_BAND(band):
    global awards

    expr = conditions['startCQWAZ_BAND'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTWeQSL'] + " band_rx = '" + band + "' and " + "cq_zone != '' and cq_zone != '1-5' and " + conditions['end'] + conditions['stopCQWAZ_BAND']
    res = cur.execute (expr)
    w = res.fetchall()
    x = []
    for a,b,c in w:
        x.append ({'Contacts': a, 'Required':40, 'Band': b, 'Mode': c})
    awards['CQ']['CQWAZ']['CQWAZ_' + band] = x

def doCQWAZ(band):
    global awards

    expr = conditions['startCQWAZ'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTWeQSL'] + " band_rx = '" + band + "' and " + "cq_zone != '' and cq_zone != '1-5' and " + conditions['end']
    res = cur.execute (expr)
    awards['CQ']['CQWAZ']['CQWAZ_' + band] = {'Contacts':res.fetchone()[0], 'Required':40}

def doCQWAZ_MODE (mode):
    global awards

    expr = conditions['startCQWAZ'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTWeQSL'] + conditions[mode] + "cq_zone != '' and cq_zone != '1-5' and " + conditions['end']
    res = cur.execute (expr)
    awards['CQ']['CQWAZ']['CQWAZ_' + mode] = {'Contacts':res.fetchone()[0], 'Required':40}

def doDXCC_MIXED():
    global awards

    expr = conditions['startDXCC'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTW'] + conditions['end']
    res = cur.execute (expr)
    awards['ARRL']['DXCC']['DXCC_MIXED'] = {'Contacts':res.fetchone()[0], 'Required':100}


def doDXCC_MODE(mode):
    global awards

    expr = conditions['startDXCC'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTW'] + conditions[mode] + conditions['end']
    res = cur.execute (expr)
    awards['ARRL']['DXCC']['DXCC_' + mode] = {'Contacts':res.fetchone()[0], 'Required':100}

def doDXCC_BAND(band):
    global awards

    expr = conditions['startDXCC'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTW'] +  " band_rx = '" + band + "' and " + conditions['end']
    res = cur.execute (expr)
    awards['ARRL']['DXCC'][band] = {'Contacts':res.fetchone()[0], 'Required':100}

def doDXCC_MISSINGQSL():
    global awards

    expr = "SELECT distinct dxcc_country FROM " + qso_table + " where " + conditions['no_maritime'] + " True " + "EXCEPT "
    expr = expr + "SELECT distinct dxcc_country FROM " + qso_table + " where " + conditions['no_maritime'] + conditions['LoTW'] + " True"
    res = cur.execute (expr)
    output = res.fetchall()
    awards['ARRL']['DXCC']['DXCC_MISSINGQSL'] = {'DXCC': output, 'Count': len(output)}
    #log.info ("        %s" %(awards['ARRL']['DXCC']['DXCC_MISSINGQSL']))

def doDXCC_CONFIRMEDCOUNTRYCOUNTS():
    global awards
    
    expr = 'select distinct count(*) as C, dxcc_country from ' + qso_table + ' where '
    expr = expr + conditions['no_maritime'] + conditions['LoTW'] + ' True '
    expr = expr + 'group by dxcc_country order by c DESC'
    #print (expr)
    
    res = cur.execute (expr)
    calls = res.fetchall()
    awards['ARRL']['DXCC']['DXCC_CONFIRMEDCOUNTRYCOUNT'] = []
    for count, dxcc in calls:
        awards['ARRL']['DXCC']['DXCC_CONFIRMEDCOUNTRYCOUNT'].append ({'DXCC': dxcc, 'Count': count})


def doCQWPX_MODE(mode_desc, count, modes, details):
    global awards

    combined = []
    for band,y in details.items(): # key, value
        log.debug (band)
        for mode, prefixes in y.items():
            log.debug (mode)
            if mode in modes:
                combined = list(set(combined) | set(prefixes))
    awards['CQ']['CQWPX']['CQWPX_'+mode_desc] = {'Contacts':len(combined), 'Required':count}

def doCQWPX_BAND(target_band, full_mode, count, details):
    global awards

    combined = []
    for band,y in details.items(): # key, value
        if band == target_band:
            for mode, prefixes in y.items(): # we dont need band
                combined = list(set(combined) | set(prefixes))
    if not 'CQWPX_'+target_band in awards['CQ']['CQWPX']:
        awards['CQ']['CQWPX']['CQWPX_'+target_band] = {}
    awards['CQ']['CQWPX']['CQWPX_'+target_band][full_mode] = {'Contacts':len(combined), 'Required':count}



def doCQWPX_CONTINENT(continent, mode,count):
    # https://cq-amateur-radio.com/cq_awards/cq_wpx_awards/cq-wpx-award-rules-022017.pdf
    global awards
    global cur

    co = "("
    for code in continents:
        if continents[code] == continent: 
            co += " dxcc_id = " + str(code) + " or "
    co += "false) "

    if mode == "DIGITAL":
        co += ' and ' + conditions["DATA"] + ' True '

    expr = "select DISTINCT call, dxcc_id from " + qso_table + " where " + conditions['LoTW'] + co
    res = cur.execute (expr)

    prefixes = []
    calls = res.fetchall()
    # https://regex101.com
    for c, d in calls: # Call, Band, Mode
        c = c.upper()
        if c[-2:] == "/P": # Remove /P from end of call since it doesnt mean anything, under the rules
            c = c[:-2]
        if c.find("/") >= 0:
            c = c[0:c.index("/")]
            if not c[-1].isnumeric(): # If prefix with a / doesnt have a number at the end, add a 0
                c += "0"
        r = re.search ("^[A-Z]+[0-9]+", c)
        #print (c, r)
        if r is not None:
            if not r.group() in prefixes:
                prefixes.append(r.group())
        else:
            r = re.search("^[0-9][A-Z]+[0-9]+", c)
            if not r.group() in prefixes:
                prefixes.append(r.group())
            #print (r.group())
    awards['CQ']['CQWPX']['CONTINENTS'][continent][mode] = {'Contacts': len(prefixes), 'Required': count, 'Notes': 'Contacts are prefixes'}


def doCQWPX(mode):
    # https://cq-amateur-radio.com/cq_awards/cq_wpx_awards/cq-wpx-award-rules-022017.pdf
    global awards

    details = {'160M': {}, '80M': {}, '40M': {}, '30M': {}, '20M': {}, '17M': {}, '15M': {}, '12M': {}, 
               '10M': {}, '6M': {}, '2M': {}, '70CM': {}, '23CM': {}, '3C': {}}

    #log.info ("      WPX - Any Mode" )
    expr = "select DISTINCT call, band_rx, mode from " + qso_table + " where " + conditions['LoTW'] + " True "
    if mode == 'DIGITAL':
        expr += ' and ' + conditions['DATA'] + ' True'
    res = cur.execute (expr)
    
    prefixes = []
    calls = res.fetchall()
    # https://regex101.com
    for c, b, m in calls: # Call, Band, Mode
        c = c.upper()
        b = b.upper()
        if c[-2:] == "/P": # Remove /P from end of call since it doesnt mean anything, under the rules
            c = c[:-2]
        if c.find("/") >= 0:
            c = c[0:c.index("/")]
            if not c[-1].isnumeric(): # If prefix with a / doesnt have a number at the end, add a 0
                c += "0"
        r = re.search ("^[A-Z]+[0-9]+", c)
        #print (c, r)
        if r is not None:
            if not r.group() in prefixes:
                prefixes.append(r.group())
            if not m in details[b]:
                details[b][m] = []
            if not r.group() in details[b][m]:
                details[b][m].append(r.group())
        else:
            r = re.search("^[0-9][A-Z]+[0-9]+", c)
            if not r.group() in prefixes:
                prefixes.append(r.group())
            #print (r.group())
            if not m in details[b]:
                details[b][m] = []
            if not r.group() in details[b][m]:
                details[b][m].append(r.group())
    return details


def doNZART_NZAWARD():
    global awards

    expr = 'select distinct call ' + conditions['from'] + "call like 'ZL%' order by call"
    res = cur.execute (expr)
    details = res.fetchall()

    zl = {}
    zl['ZL1'] = []
    zl['ZL2'] = []
    zl['ZL3'] = []
    zl['ZL4'] = []
    zl['ZL789'] = []

    # Simplistic. Ignore / for call areas and portable stations
    # Ignoring ZL6
    for call in details:
        if not "/" in call:
            call = call[0] #Dunno why
            if call[:3] == 'ZL1':
                zl['ZL1'].append (call)
            if call[:3] == 'ZL2':
                zl['ZL2'].append (call)
            if call[:3] == 'ZL3':
                zl['ZL3'].append (call)
            if call[:3] == 'ZL4':
                zl['ZL4'].append (call)
            if call[:3] == 'ZL7' or call[:3] == 'ZL8' or call[:3] == 'ZL9':
                zl['ZL4'].append (call)
    all = {}
    all['ZL1'] = {'Contacts': len (zl['ZL1']), 'Required': 35}
    all['ZL2'] = {'Contacts': len (zl['ZL2']), 'Required': 35}
    all['ZL3'] = {'Contacts': len (zl['ZL3']), 'Required': 20}
    all['ZL4'] = {'Contacts': len (zl['ZL4']), 'Required': 10}
    all['ZL789'] = {'Contacts': len (zl['ZL789']), 'Required': 1, 'Notes': 'Special Conditions'}
    all['Notes'] = 'Require ZL1,2,3&4 and one contact with an external teritory etc'

    awards['NZART']['NZAWARD'].update ( all)


def doNZART_NZCENTURYAWARD():
    global awards
    #log.info ("NZART: NZ CENTURY AWARD")

    expr = 'select distinct grid ' + conditions['from'] 
    expr += "call like 'ZL%' and (grid like 'RE%' or grid like 'RF%' or grid like 'QD%' or grid like 'RD%' or grid like 'AE%' or grid like 'AF%') order by grid"
    res = cur.execute (expr)
    details = res.fetchall()

    grids = []
    for grid in details:
        grid = grid[0]
        #print (grid)
        if len(grid) == 6:
            grids.append (grid)

    awards['NZART']['NZCENTURYAWARD'].update ( {'Contacts': len(grids), "Required": 100})


def doNZART_TIKI():
    global awards
    #log.info ("NZART: TIKI")

    expr = "select distinct count(call), band_rx "  + conditions['from'] + " call like '%ZL%' group by band_rx"
    res = cur.execute (expr)
    details = res.fetchall()

    r = {}
    c = 0
    for count, band in details:
        r[band] = {'Contacts': count, 'Required': 5 }
        if count >= 5:
            c += 1

    awards['NZART']['TIKI'].update ( {'Bands': r, 'Contacts': c, 'Required': 5})



def doNZART_WORKEDALLPACIFIC():
    global awards
    #log.info ("NZART: WORKEDALLPACIFIC")

    co = "("
    for code in continents:
        if continents[code] == 'OC': 
            co += " dxcc_id = " + str(code) + " or "
    co += "false) "

    expr = 'select  count(distinct dxcc_country), band_rx  ' + conditions['from'] + co + "group by band_rx"
    res = cur.execute (expr)
    details = res.fetchall()

    r = {}
    c = 0
    for count, band in details:
        r[band] = {'Contacts': count, 'Required': 30 }
        if count >= 30:
            c += 1

    awards['NZART']['WORKEDALLPACIFIC'].update ({'Bands': r, 'Contacts': c, 'Required': 5})

    #print (expr)
    #print (details)



def doINIT_Awards():
    global awards    

    awards = {}
    awards['CQ'] = {'CQWAZ': {'Name': 'CQ - Worked All Zones'}, 'CQWPX': {'Name': 'CQ - Worked Prefixes'}}
    awards['STATS'] = {}
    awards['ARRL'] = {}
    awards['ARRL']['DXCC'] = {}
    awards['NZART'] = {'NZAWARD': {'Name': 'NZART NZ Award - Work about 101 ZL\'s'},
                        'NZCENTURYAWARD': {'Name': 'NZART Century Award - Work 100 Grid Squares'},
                        'TIKI': {'Name': 'NZART TIKI Award - Work 5 ZL callsigns on 5 Bands'},
                        'WORKEDALLPACIFIC': {'Name': 'NZARD Worked All Pacific - Work at least 30 DXCC'}}
    awards['ARRL']['DXCC']['Notes'] = "LoTW or Paper QSL Cards only; No Maritime Mobile; No Repeaters - Assuming None; No Satellite - Assuming none"
    awards['RSGB'] = {'COMMONWEALTHCENTURY': {'Name': 'RSGB Commonwealth Century - Work 40 Commonwealth DXCC on each of 5 bands with extensions'}}
    awards['WIA'] = {'GRID': {'Name': 'WIA Grid - Work 100 VK Grid Squares'}, 
                     'WORKEDALLVK': {'Name': 'WIA Worked All VK - Work a combination of VK prefixes on a combination of bands'}}

def doAWARDS_DXCC():
    global awards

    doDXCC_MIXED ()
    doDXCC_MODE ("PHONE")
    doDXCC_MODE ("CW")
    doDXCC_MODE ("DATA")
    doDXCC_BAND ("160M")
    doDXCC_BAND ("80M")
    doDXCC_BAND ("40M")
    doDXCC_BAND ("30M")
    doDXCC_BAND ("20M")
    doDXCC_BAND ("17M")
    doDXCC_BAND ("15M")
    doDXCC_BAND ("12M")
    doDXCC_BAND ("10M")
    doDXCC_BAND ("6M")
    doDXCC_BAND ("2M")
    doDXCC_BAND ("70CM")
    awards['ARRL']['DXCC']['70CM']['Notes'] = 'Satellites Now Permitted - Still not checked'
    doDXCC_BAND ("23CM")
    awards['ARRL']['DXCC']['23CM']['Notes'] = 'Satellites Now Permitted - Still not checked'
    doDXCC_BAND ("12CM")
    awards['ARRL']['DXCC']['12CM']['Notes'] = 'Satellites Now Permitted - Still not checked'
    doDXCC_BAND ("3CM")
    awards['ARRL']['DXCC']['3CM']['Notes'] = 'Satellites Now Permitted - Still not checked'

    doDXCC_MISSINGQSL ()
    doDXCC_CONFIRMEDCOUNTRYCOUNTS ()
    doGetDXCC_table()


    awards['ARRL']['DXCC']['Satellite'] = {'Notes': 'ToDo: No Satellite Log Analysis has been done'}

    awards['ARRL']['DXCC']['5BDXCC'] = { 'Notes': 'Any Mode, 100 each on 80M, 40M, 20M, 15M, 10M; then endorceable for 160M, 30M, 17M, 12M, 6M, 2M'}

    awards['ARRL']['DXCC']['5BDXCC']['Primary'] = {}
    awards['ARRL']['DXCC']['5BDXCC']['Primary']['80M'] = {'Contacts': awards['ARRL']['DXCC']['80M']['Contacts'], 'Required':100}
    awards['ARRL']['DXCC']['5BDXCC']['Primary']['40M'] = {'Contacts': awards['ARRL']['DXCC']['40M']['Contacts'], 'Required':100}
    awards['ARRL']['DXCC']['5BDXCC']['Primary']['20M'] = {'Contacts': awards['ARRL']['DXCC']['20M']['Contacts'], 'Required':100}
    awards['ARRL']['DXCC']['5BDXCC']['Primary']['15M'] = {'Contacts': awards['ARRL']['DXCC']['15M']['Contacts'], 'Required':100}
    awards['ARRL']['DXCC']['5BDXCC']['Primary']['10M'] = {'Contacts': awards['ARRL']['DXCC']['10M']['Contacts'], 'Required':100}

    awards['ARRL']['DXCC']['5BDXCC']['Endorcements'] = {}
    awards['ARRL']['DXCC']['5BDXCC']['Endorcements']['160M'] = {'Contacts': awards['ARRL']['DXCC']['160M']['Contacts'], 'Required':100}
    awards['ARRL']['DXCC']['5BDXCC']['Endorcements']['30M'] = {'Contacts': awards['ARRL']['DXCC']['30M']['Contacts'], 'Required':100}
    awards['ARRL']['DXCC']['5BDXCC']['Endorcements']['17M'] = {'Contacts': awards['ARRL']['DXCC']['17M']['Contacts'], 'Required':100}
    awards['ARRL']['DXCC']['5BDXCC']['Endorcements']['12M'] = {'Contacts': awards['ARRL']['DXCC']['12M']['Contacts'], 'Required':100}
    awards['ARRL']['DXCC']['5BDXCC']['Endorcements']['6M'] = {'Contacts': awards['ARRL']['DXCC']['6M']['Contacts'], 'Required':100}
    awards['ARRL']['DXCC']['5BDXCC']['Endorcements']['2M'] = {'Contacts': awards['ARRL']['DXCC']['2M']['Contacts'], 'Required':100}


    challenge = awards['ARRL']['DXCC']['160M']['Contacts'] + awards['ARRL']['DXCC']['80M']['Contacts'] + awards['ARRL']['DXCC']['40M']['Contacts'] + awards['ARRL']['DXCC']['30M']['Contacts'] + \
        awards['ARRL']['DXCC']['20M']['Contacts'] + awards['ARRL']['DXCC']['17M']['Contacts'] + awards['ARRL']['DXCC']['15M']['Contacts'] + awards['ARRL']['DXCC']['12M']['Contacts'] + \
        awards['ARRL']['DXCC']['10M']['Contacts'] + awards['ARRL']['DXCC']['6M']['Contacts']
    awards['ARRL']['DXCC']['DXCC_CHALLENGE'] = {'Contacts': challenge, 'Required': 1000}



def doAWARDS_CQWAZ():
    global awards

    awards['CQ']['CQWAZ']['Notes'] = 'LoTW, eQSL or Paper QSL Cards only; No Satellite; Assuming eQSL is Authenticity Guarenteed; Assuming no satellites. Assuming dates OK '
    awards['CQ']['CQWAZ']['URL'] = 'https://cq-amateur-radio.com/cq_awards/cq_waz_awards/june2022-Final-with-color-break-for-Jose-to-review-Rev-B.pdf'

    doCQWAZ_MIXED ()

    awards['CQ']['CQWAZ']['Satellite'] = {'Notes': 'No Analysis has been done'}
    awards['CQ']['CQWAZ']['SSTV'] = {'Notes': 'No Analysis has been done'}
    awards['CQ']['CQWAZ']['EME'] = {'Notes': 'No Analysis has been done'}



    doCQWAZ_MODE ("DATA")
    doCQWAZ_MODE ("RTTY")
    doCQWAZ_MODE ("CW")
    doCQWAZ_MODE ("SSB")
    doCQWAZ_MODE ("AM")

    doCQWAZ_BAND ("160M") #doCQWAZ ("160M")
    doCQWAZ_BAND ("80M")
    doCQWAZ_BAND ("40M")
    doCQWAZ_BAND ("30M")
    doCQWAZ_BAND ("20M")
    doCQWAZ_BAND ("17M")
    doCQWAZ_BAND ("15M")
    doCQWAZ_BAND ("12M")
    doCQWAZ_BAND ("10M")
    doCQWAZ_BAND ("6M") #doCQWAZ ("6M")



def doAWARDS_CQWPX():
    global awards


    awards['CQ']['CQWPX']['CONTINENTS'] = {}
    awards['CQ']['CQWPX']['CONTINENTS']['MIXED'] = {}
    awards['CQ']['CQWPX']['CONTINENTS']['DIGITAL'] = {}
    awards['CQ']['CQWPX']['CONTINENTS'] = {'NA': {'MIXED': {}, 'DIGITAL': {}}, 'SA': {'MIXED': {}, 'DIGITAL': {}}, 'EU': {'MIXED': {}, 'DIGITAL': {}}, 'AS': {'MIXED': {}, 'DIGITAL': {}}, 'AF': {'MIXED': {}, 'DIGITAL': {}}, 'OC': {'MIXED': {}, 'DIGITAL': {}}}

    #log.info ("CQ WPX: General Conditions")
    cqwpxDetails = doCQWPX('MIXED') # For everything
    cqwpxDetailsDigital = doCQWPX('DIGITAL') # For everything

    doCQWPX_MODE ("Mixed", 400, all_mode, cqwpxDetails )
    doCQWPX_MODE ("CW", 300, cw_mode, cqwpxDetails )
    doCQWPX_MODE ("SSB", 300, ssb_mode, cqwpxDetails )
    doCQWPX_MODE ("Digital", 300, data_mode, cqwpxDetails )

    doCQWPX_BAND ("160M", 'MIXED', 50, cqwpxDetails)
    doCQWPX_BAND ("80M", 'MIXED', 175, cqwpxDetails)
    doCQWPX_BAND ("160M", 'MIXED', 175, cqwpxDetails)
    doCQWPX_BAND ("40M", 'MIXED', 250, cqwpxDetails)
    doCQWPX_BAND ("30M", 'MIXED', 250, cqwpxDetails)
    doCQWPX_BAND ("20M", 'MIXED', 300, cqwpxDetails)
    doCQWPX_BAND ("17M", 'MIXED', 300, cqwpxDetails)
    doCQWPX_BAND ("15M", 'MIXED', 300, cqwpxDetails)
    doCQWPX_BAND ("12M", 'MIXED', 300, cqwpxDetails)
    doCQWPX_BAND ("10M", 'MIXED', 300, cqwpxDetails)
    doCQWPX_BAND ("6M", 'MIXED', 250, cqwpxDetails)

    doCQWPX_BAND ("160M", 'DIGITAL', 50, cqwpxDetailsDigital)
    doCQWPX_BAND ("80M", 'DIGITAL', 175, cqwpxDetailsDigital)
    doCQWPX_BAND ("160M", 'DIGITAL', 175, cqwpxDetailsDigital)
    doCQWPX_BAND ("40M", 'DIGITAL', 250, cqwpxDetailsDigital)
    doCQWPX_BAND ("30M", 'DIGITAL', 250, cqwpxDetailsDigital)
    doCQWPX_BAND ("20M", 'DIGITAL', 300, cqwpxDetailsDigital)
    doCQWPX_BAND ("17M", 'DIGITAL', 300, cqwpxDetailsDigital)
    doCQWPX_BAND ("15M", 'DIGITAL', 300, cqwpxDetailsDigital)
    doCQWPX_BAND ("12M", 'DIGITAL', 300, cqwpxDetailsDigital)
    doCQWPX_BAND ("10M", 'DIGITAL', 300, cqwpxDetailsDigital)
    doCQWPX_BAND ("6M", 'DIGITAL', 250, cqwpxDetailsDigital)


    doCQWPX_CONTINENT ("NA", "MIXED", 160)
    doCQWPX_CONTINENT ("SA", "MIXED", 95)
    doCQWPX_CONTINENT ("EU", "MIXED", 160)
    doCQWPX_CONTINENT ("AF", "MIXED", 90)
    doCQWPX_CONTINENT ("AS", "MIXED", 75)
    doCQWPX_CONTINENT ("OC", "MIXED", 60)

    doCQWPX_CONTINENT ("NA", "DIGITAL", 160)
    doCQWPX_CONTINENT ("SA", "DIGITAL", 95)
    doCQWPX_CONTINENT ("EU", "DIGITAL", 160)
    doCQWPX_CONTINENT ("AF", "DIGITAL", 90)
    doCQWPX_CONTINENT ("AS", "DIGITAL", 75)
    doCQWPX_CONTINENT ("OC", "DIGITAL", 60)



def doAWARDS_NZART():
    global awards

    #log.info ("NZART Awards")
    doNZART_NZAWARD()
    doNZART_NZCENTURYAWARD()
    doNZART_TIKI()
    doNZART_WORKEDALLPACIFIC()



def doWIA_WORKEDALLVK ():
    global awards

    # Complex award with combo of calls worked and either bands or DXCC entities

    expr = 'with '
    select = 'select * from '

    for area in ('VK0',):

        expr += '%sC as' % (area)
        expr += '(select count( distinct call) '
        expr += conditions['from']
        expr += 'call like "%s%%" and ' % (area)
        expr += conditions['LoTW']
        expr += conditions['no_maritime'] + " True), \n"

        expr += '%sB as' % (area)
        expr += '(select count( distinct dxcc_country) '
        expr += conditions['from']
        expr += 'call like "%s%%" and ' % (area)
        expr += conditions['LoTW']
        expr += conditions['no_maritime'] + " True), \n"

        select += '%sC, %sB, ' % (area, area)

    for area in ('VK1', 'VK2', 'VK3', 'VK4', 'VK5', 'VK6', 'VK7', 'VK8'):

        expr += '%sC as' % (area)
        expr += '(select count( distinct call) '
        expr += conditions['from']
        expr += 'call like "%s%%" and ' % (area)
        expr += conditions['LoTW']
        expr += conditions['no_maritime'] + " True), \n"

        expr += '%sB as' % (area)
        expr += '(select count( distinct band_tx) '
        expr += conditions['from']
        expr += 'call like "%s%%" and ' % (area)
        expr += conditions['LoTW']
        expr += conditions['no_maritime'] + " True), \n"

        select += '%sC, %sB, ' % (area, area)

    for area in ('VK9',):

        expr += '%sC as' % (area)
        expr += '(select count( distinct call) '
        expr += conditions['from']
        expr += 'call like "%s%%" and ' % (area)
        expr += conditions['LoTW']
        expr += conditions['no_maritime'] + " True), \n"

        expr += '%sB as' % (area)
        expr += '(select count( distinct dxcc_country) '
        expr += conditions['from']
        expr += 'call like "%s%%" and ' % (area)
        expr += conditions['LoTW']
        expr += conditions['no_maritime'] + " True), \n"

        select += '%sC, %sB, ' % (area, area)

    expr = expr[:len(expr)-3]
    expr += select
    expr = expr[:len(expr)-2]

    res = cur.execute (expr)
    details = res.fetchone()

    awards['WIA']['WORKEDALLVK']['AREAS'] = {}
    awards['WIA']['WORKEDALLVK']['Notes'] = 'For VK ops only. Different rules for DX'

    calls = (3,3,10,10,10,10,10,3,3,4)
    div = (2,2,3,3,3,3,3,2,2,3)

    count_calls = 0
    count_diversity = 0 

    i = 0
    j = 0
    for area in ('VK0','VK1', 'VK2', 'VK3', 'VK4', 'VK5', 'VK6', 'VK7', 'VK8', 'VK9'):
        awards['WIA']['WORKEDALLVK']['AREAS'][area] = {'Notes': 'Diversity is Bands, or DXCC for VK0 and VK9',
                                                       'Calls': {},
                                                       'Diversity': {}}
        awards['WIA']['WORKEDALLVK']['AREAS'][area]['Calls']['Contacts'] = details[i]
        awards['WIA']['WORKEDALLVK']['AREAS'][area]['Calls']['Required'] = calls[j]
        if details[i] >= calls[j]: 
            count_calls += 1
        i += 1
        awards['WIA']['WORKEDALLVK']['AREAS'][area]['Diversity']['Contacts'] = details[i]
        awards['WIA']['WORKEDALLVK']['AREAS'][area]['Diversity']['Required'] = div[j]
        if details[i] >= div[j]:
            count_diversity += 1    
        i += 1
        j += 1

        awards['WIA']['WORKEDALLVK']['CONTACTS'] = {'Contacts': count_calls, 
                                                    'Required': 10, 
                                                    'Notes': 'Contacts is number of AREAS met with callsign'}
        awards['WIA']['WORKEDALLVK']['DIVERSITY'] = {'Contacts': count_diversity, 
                                                    'Required': 10, 
                                                    'Notes': 'Diversity is number of AREAS met with band or DXCC'}




def doWIA_GRID():
    global awards


    expr = 'select count(distinct  substr(grid,1,4)) ' + conditions['from'] + conditions['no_maritime'] + conditions['LoTW'] +  ' grid is not NULL'
    res = cur.execute (expr)
    awards['WIA']['GRID']['Contacts'] = res.fetchone()[0]
    awards['WIA']['GRID']['Required'] = 100 
    awards['WIA']['GRID']['Max'] = 1800
    awards['WIA']['GRID']['Notes'] = 'Assumes HF only'


def doAWARDS_WIA():
    global awards
    #awards['WIA'] = {'GRID': {}, 'WORKEDALLVK': {}}

    awards['WIA']['WIAOCEANIA'] = {}
    awards['WIA']['WIAWORKEDALLCONTINENTS'] = {'Note': 'Physical cards only. I mean, SERIOUSLY?'}
    doWIA_GRID()
    doWIA_WORKEDALLVK()



def doRSGB_COMMONWEALTHCENTURY():
    global awards


    co = "("
    for code in commonwealth:
        co += " dxcc_id = " + str(code) + " or "
    co += "false) "

    expr = 'select distinct call, dxcc_id, dxcc_country, band_rx  ' + conditions['from'] + co + ' and ' + conditions['LoTWeQSL'] + ' true '
    res = cur.execute (expr)
    details = res.fetchall()

    mods = {}
    mods[1] = {'VE1': "Canada VE1", 'VE2': "Canada VE2", 'VE3': "Canada VE3", 'VE4': "Canada VE4", 'VE5': "Canada VE5", 
               'VE6': "Canada VE6", 'VE7': "Canada VE7", 'VE8': "Canada VE8", 
               'VO1': "Canada VO1", 'VO2': "Canada VO2", 'VY1': "Canada VY1", 'VY2': "Canada VY2", }
    mods[150] = {'VK1': 'Australia VK1', 'VK2': 'Australia VK2', 'VK3': 'Australia VK3', 'VK4': 'Australia VK4', 
                 'VK5': 'Australia VK5', 'VK6': 'Australia VK6', 'VK7': 'Australia VK7', 'VK8': 'Australia VK8', }
    mods[170] = {'ZL1': 'New Zealand ZL1', 'ZL2': 'New Zealand ZL2', 'ZL3': 'New Zealand ZL3', 'ZL4': 'New Zealand ZL4'}


    counts = {'160M': {}, '80M': {}, '40M': {}, '30M': {}, '20M': {}, '17M': {}, '15M': {}, '12M': {}, '10M': {}}

    r = {}

    for call, dxcc_id, dxcc_country, band_rx in details:
        if dxcc_id in mods:
            if not '/' in call: #ToDo - Fix this. 
                if call[:3] in mods[dxcc_id]:
                    dxcc_country = mods[dxcc_id][call[:3]]
                    if band_rx in counts:
                        counts[band_rx][dxcc_country] = call # Sample callsign
        else:
            counts[band_rx][dxcc_country] = call # Sample callsign
    returns = {'Base': { 
                    '80M': { 'Contacts': len(counts['80M']), 'Required': 40 }, 
                    '40M': { 'Contacts': len(counts['40M']), 'Required': 40 }, 
                    '20M': { 'Contacts': len(counts['20M']), 'Required': 40 }, 
                    '15M': { 'Contacts': len(counts['15M']), 'Required': 40 }, 
                    '10M': { 'Contacts': len(counts['10M']), 'Required': 40 }
                    }, 
                'Extension': {
                    '160M': { 'Contacts': len(counts['160M']), 'Required': 40 }, 
                    '30M': { 'Contacts': len(counts['30M']), 'Required': 40 }, 
                    '17M': { 'Contacts': len(counts['17M']), 'Required': 40 }, 
                    '12M': { 'Contacts': len(counts['12M']), 'Required': 40 } 
                }
    }
    awards['RSGB']['COMMONWEALTHCENTURY'].update (returns)


def doAWARDS_RSGB():
    global awards
    doRSGB_COMMONWEALTHCENTURY()



def doSTATS():
    global awards

    # Not contests but interesting information to show
    doSTATS_QSL()
    doSTATS_BANDS()
    doSTATS_MODES()
    doSTATS_DXCCBYDATE()
    doSTATS_MISSINGDXCCCONFIRM()
    doSTATS_GRIDS()





if True:
    doINIT()
    doDatabase()
    doINIT_Awards()
    continents = doGetDXCC_Continent() 

    doAWARDS_DXCC()
    doAWARDS_CQWAZ()
    doAWARDS_CQWPX()
    doAWARDS_NZART()
    doAWARDS_RSGB()
    doAWARDS_WIA()
    doSTATS()


    # Does not view well in Safari
    xml = dicttoxml(awards)
    f=open ("demofile2.xml", "w")
    f.write (parseString(xml).toprettyxml())
    f.close()

if __name__ == "__main__":

    pp.pprint (awards)
    print (awards['ARRL']['DXCC']['Table'])

    #pp.pprint (awards['NZART'])

    #j = json.dumps(awards, indent = 8)
    #print (j)
















