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


#python3 -m pip install -U numpy

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
from dateutil import parser
import numpy as np




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







class analysis():
    def __init__(self):
    
        self.database_name = "/Users/darryl/Documents/MLDX_Logs/MacLoggerDX.sql"
        self.qso_table = 'qso_table_v008'
        self.dxcc_file = "dxcc.txt"
        self.dxcc_uri = "http://www.arrl.org/files/file/DXCC/2019_Current_Deleted(3).txt"
        self.staticCols = ['Country', '160M', '80M', '40M', '30M', '20M', '17M', '15M', '12M', '10M', '6M']
        self.lotwUserActivity = 'lotw-user-activity.csv'

        self.conditions = {"no_maritime": " not call like '%/MM' and ",
                    "LoTW": " qsl_received like '%LoTW%' and ",
                    "Card": " qsl_received like '%CardC%' and ",
                    "eQSL": " qsl_received like '%eQSL%' and ",
                    "LoTWeQSL": " (qsl_received like '%LoTW%' or qsl_received like '%eQSL%') and ",
                    "LoTWCard": " (qsl_received like '%LoTW%' or qsl_received like '%Card%') and ",
                    "LoTWeQSLCard": " (qsl_received like '%LoTW%' or qsl_received like '%eQSL%' or qsl_received like '%CardC%') and ",
                    "startDXCC": " select count (distinct dxcc_country) ",
                    "startCQWAZ": " select count ( distinct iif (substr(cq_zone,1,1) == '0', substr(cq_zone,2), cq_zone)) ",
                    "startCQWAZ_BAND": " select distinct count(distinct iif (substr(cq_zone,1,1) == '0', substr(cq_zone,2), cq_zone)), mode , band_rx from ( select  count(*) as c, cq_zone, mode, band_rx ",
                    "stopCQWAZ_BAND": " group by  cq_zone, mode, band_rx ) group by mode, band_rx ",
                    "WAS": " (dxcc_id = 291 or dxcc_id = 6 or dxcc_id = 110) and ",
                    "from": " from " + self.qso_table + " where ",
                    "end": " True "}


        self.data_mode = ["LSB-D", "LSB-D2", "LSB-D3", "USB-D", "USB-D2", "USB-D3", "FM-D", "FM-D2", "FM-D3", "AM-D", "AM-D2", "AM-D3", "DIGITAL", 
                "FSK", "FSK-R", "RTTY", "RTTY-R", "RTTY-L", "RTTY-U", "Packet", "PKT-FM", "PKT-U", "PKT-L", "Data", "Data-L", "Data-R", 
                "Data-U", "Data-FM", "Data-FMN", "PSK", "PSK-R", "FT8", "Spectral", ]
        self.cw_mode = ["CW", "CW-R", "CW Wide", "CW Narrow", "UCW", "LCW"]
        self.phone_mode = ["DV", "P25", "C4FM", "FDV", "DRM", "LSB", "LSB Sync", "USB", "USB Sync", "Double SB", "FM", "FM Wide", "FM Narrow", 
                    "AM", "AM Wide", "AM Narrow", "AM Sync"]
        self.am_mode = ["AM", "AM Wide", "AM Narrow", "AM Sync"]
        self.ssb_mode = ["LSB", "LSB Sync", "USB", "USB Sync"]
        self.rtty_mode = ["RTTY", "RTTY-R", "RTTY-L", "RTTY-U"]
        self.all_mode = self.data_mode + self.cw_mode + self.phone_mode 
        self.oceania = (247,176,489,460,511,190,46,160,157,375,191,234,188,162,512,175,508,509,298,185,507,177,166,20,103,123,174,197,110,138,9,515,297,163,282,301,31,48,490,22,173,168,345,150,153,38,147,171,189,303,35,172,513,327,158,270,170,34,133,16)
        self.commonwealth = (223, 114,265,122,279,106,294,233,257,402,322,181,379,406,464,33,452,250,205,274,493,201,4,165,207,468,470,450,286,430,432,440,
            424,482,458,454,60,77,97,95,98,94,66,249,211,252,12,65,96,89,64,69,82,62,111,153,235,238,240,241,141,129,90,372,
            305,324,11,142,283,315,215,159,299,247,381,160,157,191,234,188,185,507,163,282,301,31,48,490,345,150,35,38,147,189,172,513,
            158,270,170,34,133, 16, 190, 46, 176, 489, 460)


        #ToDO Extend this
        # Unused
        self.bands = ["160M", "80M", "40M", "30M", "20M", "17M", "15M", "12M", "10M", "6M", "2M", "70CM"]

        self.data_statement = " (False "
        for d in self.data_mode:
            self.data_statement = self.data_statement + " or mode = '" + d + "' "
        self.data_statement = self.data_statement + " ) and "
        self.conditions["DATA"] = self.data_statement

        self.cw_statement = " (False "
        for d in self.cw_mode:
            self.cw_statement = self.cw_statement + " or mode = '" + d + "' "
        self.cw_statement = self.cw_statement + " ) and "
        self.conditions["CW"] = self.cw_statement

        self.phone_statement = " (False "
        for d in self.phone_mode:
            self.phone_statement = self.phone_statement + " or mode = '" + d + "' "
        self.phone_statement = self.phone_statement + " ) and "
        self.conditions["PHONE"] = self.phone_statement

        self.am_statement = " (False "
        for d in self.am_mode:
            self.am_statement = self.am_statement + " or mode = '" + d + "' "
        self.am_statement = self.am_statement + " ) and "
        self.conditions["AM"] = self.am_statement

        self.ssb_statement = " (False "
        for d in self.ssb_mode:
            self.ssb_statement = self.ssb_statement + " or mode = '" + d + "' "
        self.ssb_statement = self.ssb_statement + " ) and "
        #log.debug (ssb_statement)
        self.conditions["SSB"] = self.ssb_statement

        self.rtty_statement = " (False "
        for d in self.rtty_mode:
            self.rtty_statement = self.rtty_statement + " or mode = '" + d + "' "
        self.rtty_statement = self.rtty_statement + " ) and "
        #log.debug (rtty_statement)
        self.conditions["RTTY"] = self.rtty_statement



    def doDatabase(self):
        #ToDo: Move database name to settings
        self.conn = sqlite3.connect (self.database_name)
        self.cur = self.conn.cursor()

    def doGetDXCC_Continent(self):
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

        if not os.path.exists(self.dxcc_file):
            dxcc_file, headers = urllib.request.urlretrieve(self.dxcc_uri, filename=self.dxcc_file)

        continents = {}
        with open(self.dxcc_file, mode="r", encoding="UTF-8") as dxcc_in:
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

    def doSTATS_QSL (self):
        expr = "With A as "
        expr += "(select  count(call) as COUNT_ALL "
        expr += self.conditions['from']
        expr += self.conditions['no_maritime'] + " True), "

        expr += "B as "
        expr += "(select  count(call) as COUNT_LOTW "
        expr += self.conditions['from']
        expr += self.conditions['LoTW']
        expr += self.conditions['no_maritime'] + " True), "

        expr += "C as "
        expr += "(select  count(call) as COUNT_EQSL "
        expr += self.conditions['from']
        expr += self.conditions['eQSL']
        expr += self.conditions['no_maritime'] + " True), "

        expr += "D as "
        expr += "(select  count(call) as COUNT_CARD "
        expr += self.conditions['from']
        expr += self.conditions['Card']
        expr += self.conditions['no_maritime'] + " True), "

        expr += "E as "
        expr += "(select count(call) as COUNT_LOTWEQSL " 
        expr += self.conditions['from']
        expr += self.conditions['LoTWeQSL']
        expr += self.conditions['no_maritime'] + " True) "
        expr += " select * from A, B, C, D, E"

        res = self.cur.execute (expr)
        details = res.fetchone()

        self.awards['STATS']['STATS_QSL'] = {'Total': details[0], 'LoTW_Total': details[1], 'eQSL_Total': details[2], 'Card_Total': details[3], 'LoTWeQSL_Total': details[4],
                                        'Notes': ' Any mode, no Maritime'}

    def doSTATS_BANDS (self):
        expr = "select count(*), band_rx "
        expr += self.conditions ['from']
        expr += " true group by band_rx"

        res = self.cur.execute (expr)
        details = res.fetchall()
        
        self.awards['STATS']['STATS_BANDS'] = {}
        for count, band in details:
            self.awards['STATS']['STATS_BANDS'][band] = count


    def doSTATS_MODES (self):
        expr = "select count(*), mode "
        expr += self.conditions ['from']
        expr += " true group by mode"

        res = self.cur.execute (expr)
        details = res.fetchall()
        self.awards['STATS']['STATS_MODES'] = {}
        for count, mode in details:
            self.awards['STATS']['STATS_MODES'][mode] = count


    def doSTATS_LOTWSTATS (self):
        expr = "select qsl_sent, qsl_received "
        expr += self.conditions ['from']
        expr +=  self.conditions['LoTWCard']
        expr += ' true'

        res = self.cur.execute (expr)
        details = res.fetchall()
        self.awards['STATS']['STATS_LOTWSTATS'] = {}
        date_format = "%Y-%m-%d"

        ds = []
        for tx, rx in details:
            if 'Uploaded to LoTW ' in tx:
                tx_1 = tx[tx.index ('Uploaded to LoTW ')+17:]
                tx_2 = tx_1[:10]
                if 'LoTW:' in rx:
                    rx_1 = rx[rx.index ('LoTW:')+5:]
                    rx_2 = rx_1[:8]
                    rx_3 = rx_2[:4] + '-' + rx_2[4:6] + '-' + rx_2[6:]
                    t = datetime.datetime.strptime (tx_2, date_format)
                    r = datetime.datetime.strptime (rx_3, date_format)
                    delta = r-t
                    ds.append (delta.days)
                #print (tx_2, rx_3, delta.days)
        self.awards['STATS']['STATS_LOTWSTATS']['Mean'] = np.mean(ds)
        self.awards['STATS']['STATS_LOTWSTATS']['Median'] = np.median(ds)
        self.awards['STATS']['STATS_LOTWSTATS']['StandardDeviation'] = np.std(ds)

        bins = [0] * 180
        for bin in ds:
            if bin > len(bins)-1:
                bin = len(bins)-1
            bins[bin] += 1
        
        print (bins)




        print (self.awards['STATS']['STATS_LOTWSTATS'])




    def doSTATS_GRIDS (self):
        # https://www.amsat.org/amsat/articles/houston-net/grids.html
        self.awards['STATS']['STATS_GRIDS'] = {}
        self.awards['STATS']['STATS_GRIDS']['Notes'] = 'Fields are two letter grids squares. Grids are four letter ones. Does not check for QSL'

        expr = "select count(*), substr(grid,1,2) "
        expr += self.conditions ['from']
        expr += " grid is not NULL and grid != '' group by substr(grid,1,2)"

        res = self.cur.execute (expr)
        details = res.fetchall()
        self.awards['STATS']['STATS_GRIDS']['Fields'] = len(details)
        self.awards['STATS']['STATS_GRIDS']['Fields_Count'] = '324'

        expr = "select count(*), substr(grid,1,4) "
        expr += self.conditions ['from']
        expr += " grid is not NULL and grid != '' group by substr(grid,1,4)"

        res = self.cur.execute (expr)
        details = res.fetchall()
        self.awards['STATS']['STATS_GRIDS']['Grids'] = len(details)
        self.awards['STATS']['STATS_GRIDS']['Grids_Count'] = '32400'

    def doSTATS_MISSINGDXCCCONFIRM (self):
        expr = "select dxcc_country"
        expr += self.conditions ['from'] 
        expr += " dxcc_country not in "
        expr += "(select DISTINCT dxcc_country "
        expr += self.conditions ['from'] 
        expr += self.conditions['LoTWCard']
        expr += self.conditions['no_maritime'] + " True) "
        expr += ' AND ' + self.conditions['no_maritime'] + " True "

        res = self.cur.execute (expr)

        self.awards['STATS']['STATS_MISSINGDXCCCONFIRM'] = {}

        i = 1
        for k in res:
            self.awards['STATS']['STATS_MISSINGDXCCCONFIRM']["%s " % (k[0])] = 'Missing QSL'
            i += 1

    def doCQWAZ_MIXED (self):
        expr = self.conditions['startCQWAZ'] + self.conditions['from'] + self.conditions['no_maritime'] + self.conditions['LoTWeQSLCard'] + "cq_zone != '' and cq_zone != '1-5' and " + self.conditions['end']
        res = self.cur.execute (expr)
        self.awards['CQ']['CQWAZ']['CQWAZ_MIXED'] = {'Contacts':res.fetchone()[0], 'Required':40}


    def doCQWAZ_BAND(self, band):
        expr = self.conditions['startCQWAZ_BAND'] + self.conditions['from'] + self.conditions['no_maritime'] + self.conditions['LoTWeQSLCard'] + " band_rx = '" + band + "' and " + "cq_zone != '' and cq_zone != '1-5' and " + self.conditions['end'] + self.conditions['stopCQWAZ_BAND']
        res = self.cur.execute (expr)
        w = res.fetchall()
        x = []
        for a,b,c in w:
            x.append ({'Contacts': a, 'Required':40, 'Band': b, 'Mode': c})
        self.awards['CQ']['CQWAZ']['CQWAZ_' + band] = x


    def doSTATS_DXCCBYDATE (self):
        expr = "select dxcc_country, qso_done"
        expr += self.conditions ['from'] 
        expr += " dxcc_country in "
        expr += "(select DISTINCT dxcc_country "
        expr += self.conditions ['from'] 
        expr += self.conditions['LoTWCard']
        expr += self.conditions['no_maritime'] + " True) "
        expr += " AND " + self.conditions['LoTW']
        expr += self.conditions['no_maritime'] + " True "
        expr += "order by dxcc_country, qso_done"

        res = self.cur.execute (expr)

        last_dxcc = ""
        self.awards['STATS']['STATS_DXCCBYDATE'] = {}
        stats = {}
        for dxcc, day in res.fetchall():
            if dxcc != last_dxcc:
                day = str(datetime.datetime.fromtimestamp(day))
                stats[dxcc] = day[:19]
                last_dxcc = dxcc
        stats = {k: v for k, v in sorted(stats.items(), key=lambda item: item[1])}    
        i = 1
        for k in stats:
            self.awards['STATS']['STATS_DXCCBYDATE']["%03d " % (i) + k] = stats[k]
            i += 1

    def doCQWAZ(self, band):
        expr = self.conditions['startCQWAZ'] + self.conditions['from'] + self.conditions['no_maritime'] + self.conditions['LoTWeQSLCard'] + " band_rx = '" + band + "' and " + "cq_zone != '' and cq_zone != '1-5' and " + self.conditions['end']
        res = self.cur.execute (expr)
        self.awards['CQ']['CQWAZ']['CQWAZ_' + band] = {'Contacts':res.fetchone()[0], 'Required':40}

    def doCQWAZ_MODE (self, mode):
        expr = self.conditions['startCQWAZ'] + self.conditions['from'] + self.conditions['no_maritime'] + self.conditions['LoTWeQSLCard'] + self.conditions[mode] + "cq_zone != '' and cq_zone != '1-5' and " + self.conditions['end']
        res = self.cur.execute (expr)
        self.awards['CQ']['CQWAZ']['CQWAZ_' + mode] = {'Contacts':res.fetchone()[0], 'Required':40}

    def doDXCC_MIXED(self):
        expr = self.conditions['startDXCC'] + self.conditions['from'] + self.conditions['no_maritime'] + self.conditions['LoTWCard'] + self.conditions['end']
        res = self.cur.execute (expr)
        self.awards['ARRL']['DXCC']['DXCC_MIXED'] = {'Contacts':res.fetchone()[0], 'Required':100}

    def doDXCC_MODE(self, mode):
        expr = self.conditions['startDXCC'] + self.conditions['from'] + self.conditions['no_maritime'] + self.conditions['LoTWCard'] + self.conditions[mode] + self.conditions['end']
        res = self.cur.execute (expr)
        self.awards['ARRL']['DXCC']['DXCC_' + mode] = {'Contacts':res.fetchone()[0], 'Required':100}

    def doDXCC_BAND(self, band):
        expr = self.conditions['startDXCC'] + self.conditions['from'] + self.conditions['no_maritime'] + self.conditions['LoTWCard'] +  " band_rx = '" + band + "' and " + self.conditions['end']
        res = self.cur.execute (expr)
        self.awards['ARRL']['DXCC'][band] = {'Contacts':res.fetchone()[0], 'Required':100}

    def doDXCC_MISSINGQSL(self):
        expr = "SELECT distinct dxcc_country FROM " + self.qso_table + " where " + self.conditions['no_maritime'] + " True " + "EXCEPT "
        expr = expr + "SELECT distinct dxcc_country FROM " + self.qso_table + " where " + self.conditions['no_maritime'] + self.conditions['LoTWCard'] + " True"
        res = self.cur.execute (expr)
        output = res.fetchall()
        self.awards['ARRL']['DXCC']['DXCC_MISSINGQSL'] = {'DXCC': output, 'Count': len(output)}

    def doDXCC_CONFIRMEDCOUNTRYCOUNTS(self):
        expr = 'select distinct count(*) as C, dxcc_country from ' + self.qso_table + ' where '
        expr = expr + self.conditions['no_maritime'] + self.conditions['LoTWCard'] + ' True '
        expr = expr + 'group by dxcc_country order by c DESC'
        
        res = self.cur.execute (expr)
        calls = res.fetchall()
        self.awards['ARRL']['DXCC']['DXCC_CONFIRMEDCOUNTRYCOUNT'] = []
        for count, dxcc in calls:
            self.awards['ARRL']['DXCC']['DXCC_CONFIRMEDCOUNTRYCOUNT'].append ({'DXCC': dxcc, 'Count': count})

    def doCQWPX_MODE(self, mode_desc, count, modes, details):
        combined = []
        for band,y in details.items(): # key, value
            log.debug (band)
            for mode, prefixes in y.items():
                log.debug (mode)
                if mode in modes:
                    combined = list(set(combined) | set(prefixes))
        self.awards['CQ']['CQWPX']['CQWPX_'+mode_desc] = {'Contacts':len(combined), 'Required':count}

    def doCQWPX_BAND(self, target_band, full_mode, count, details):
        combined = []
        for band,y in details.items(): # key, value
            if band == target_band:
                for mode, prefixes in y.items(): # we dont need band
                    combined = list(set(combined) | set(prefixes))
        if not 'CQWPX_'+target_band in self.awards['CQ']['CQWPX']:
            self.awards['CQ']['CQWPX']['CQWPX_'+target_band] = {}
        self.awards['CQ']['CQWPX']['CQWPX_'+target_band][full_mode] = {'Contacts':len(combined), 'Required':count}


    def doGetDXCC_table(self):
        dxcc_lotw_confirmed = 'select count(call), band_tx, dxcc_country from ' + self.qso_table + ' where '
        dxcc_card_confirmed = 'select count(call), band_tx, dxcc_country from ' + self.qso_table + ' where '
        dxcc_qso_confirmed = 'select count(call), band_tx, dxcc_country from ' + self.qso_table + ' where '

        dxcc_lotw_confirmed += self.conditions['no_maritime'] + self.conditions['LoTW'] + ' True '
        dxcc_card_confirmed += self.conditions['no_maritime'] + self.conditions['Card'] + ' not ' + self.conditions['LoTW'] + ' True '
        dxcc_qso_confirmed += self.conditions['no_maritime'] + ' True '

        dxcc_lotw_confirmed += ' group by dxcc_country, band_tx'
        dxcc_card_confirmed += ' group by dxcc_country, band_tx'
        dxcc_qso_confirmed += ' group by dxcc_country, band_tx'

        self.awards['ARRL']['DXCC']['Table'] = {}

        working = {}
        res = self.cur.execute (dxcc_qso_confirmed)
        detailsQ = res.fetchall()
        for count, band_tx, dxcc_country in detailsQ:
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
                working[dxcc_country][band_tx] = str(count) + ',0,0'

        res = self.cur.execute (dxcc_lotw_confirmed)
        detailsL = res.fetchall()
        for count, band_tx, dxcc_country in detailsL:
            s = working[dxcc_country][band_tx]
            (qso, lotw, card) = s.split(',')
            lotw = count
            working[dxcc_country][band_tx] = str(qso) + ',' + str(lotw)+',' + str(card)

        res = self.cur.execute (dxcc_card_confirmed)
        detailsC = res.fetchall()
        for count, band_tx, dxcc_country in detailsC:
            s = working[dxcc_country][band_tx]
            (qso, lotw, card) = s.split(',')
            card = count
            working[dxcc_country][band_tx] = str(qso) + ',' + str(lotw)+',' + str(card)

        for country in working:
            for band in working[country]:
                s = working[country][band]
                if s is None or s == '':
                    working[country][band] = '-'
                elif ',' in s:
                    (qso, lotw, card) = s.split(',')
                    working[country][band] = '%s/%s/%s' % (lotw, card, qso)
                else:
                    working[country][band] = '0/' + s
        tab = []
        for country in working:
            tabC = [country]
            for band in working[country]:
                tabC.append (working[country][band])
            tab.append (tabC)

        challengeQ = 0
        challengeL = 0
        challengeC = 0
        sumQ = {}
        sumC = {}
        sumL = {}
        for row in tab:
            c = 0
            for line in row:
                if c != 0:
                    col = self.staticCols[c]
                    if not col in sumQ:
                        sumQ[col] = 0
                    if not col in sumL:
                        sumL[col] = 0
                    if not col in sumC:
                        sumC[col] = 0
                    if line != '-':
                        (L,C,Q) = line.split('/')
                        if int(L) > 0:
                            sumL[col] += 1
                            challengeL += 1
                        if int(C) > 0:
                            sumC[col] += 1
                            challengeC += 1
                        if int(Q) > 0:
                            sumQ[col] += 1
                            challengeQ += 1
                c += 1
        header = ['country' + '\r\n' +  str ( challengeL) + '/' + str(challengeC) + '/' + str(challengeQ)]

        required = []
        for row in tab:
            c = 0
            for line in row:
                if c != 0:
                    if line != '-':
                        #print (line)
                        (L,C,Q) = line.split('/')
                        if int(L) == 0 and int(C) == 0:
                            required.append ({'Country': row[0], 'Band': self.staticCols[c]})             
                c += 1

        for line in required:
            country = line['Country']
            band = line['Band']
            query = "select call, qso_start from "+ self.qso_table + ' where '
            query += " not call like '%/MM' "
            query += "and band_tx = '" + band + "' and dxcc_country = '" + country + "'"

            res = self.cur.execute (query)
            details = res.fetchall()

            line['Calls'] = details

        #http://www.hb9bza.net/lotw-users-list
        last_lotw = {}
        file = open (self.lotwUserActivity, 'r')
        for line in file:
            (call, d,t) = line.split(',')
            last_lotw[call] = parser.parse ('%sT%s' %(d,t)) 
        file.close()

        r = 0
        for row in tab:
            c = 0
            for line in row:
                if c != 0:
                    if line != '-':
                        #print (line)
                        (L,C,Q) = line.split('/')
                        if int(L) == 0 and int(C) == 0:
                            for ret in required:
                                if ret['Country'] == row[0] and ret['Band'] == self.staticCols[c]:
                                    #line = l
                                    for (call,when) in ret['Calls']:
                                        line = line + '\r\n'
                                        line = line + call + ',' + str(when) + ','
                                        if call in last_lotw:
                                            #print ('Found')
                                            line = line + str(last_lotw[call])
                                        tab[r][c] = line
                c += 1
            r += 1
        for col in sumQ:
            h = col + '\r\n'
            h += str ( sumL[col]) + '/' + str(sumQ[col]) + '/' + str (sumQ[col])
            header.append (h)
        self.awards['ARRL']['DXCC']['Table'] = tabulate.tabulate(tab, headers=header)

        header = [header]
        for r in tab:
            header.append (r)
        self.awards['ARRL']['DXCC']['RawTable'] = header

    def doCQWPX_CONTINENT(self, continent, mode,count):
        # https://cq-amateur-radio.com/cq_awards/cq_wpx_awards/cq-wpx-award-rules-022017.pdf
        co = "("
        for code in self.continents:
            if self.continents[code] == continent: 
                co += " dxcc_id = " + str(code) + " or "
        co += "false) "

        if mode == "DIGITAL":
            co += ' and ' + self.conditions["DATA"] + ' True '

        expr = "select DISTINCT call, dxcc_id from " + self.qso_table + " where " + self.conditions['LoTWCard'] + co
        res = self.cur.execute (expr)

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
            if r is not None:
                if not r.group() in prefixes:
                    prefixes.append(r.group())
            else:
                r = re.search("^[0-9][A-Z]+[0-9]+", c)
                if not r.group() in prefixes:
                    prefixes.append(r.group())
        self.awards['CQ']['CQWPX']['CONTINENTS'][continent][mode] = {'Contacts': len(prefixes), 'Required': count, 'Notes': 'Contacts are prefixes'}

    def doCQWPX(self, mode):
        # https://cq-amateur-radio.com/cq_awards/cq_wpx_awards/cq-wpx-award-rules-022017.pdf
        details = {'160M': {}, '80M': {}, '40M': {}, '30M': {}, '20M': {}, '17M': {}, '15M': {}, '12M': {}, 
                '10M': {}, '6M': {}, '2M': {}, '70CM': {}, '23CM': {}, '3C': {}}
        expr = "select DISTINCT call, band_rx, mode from " + self.qso_table + " where " + self.conditions['LoTWCard'] + " True "
        if mode == 'DIGITAL':
            expr += ' and ' + self.conditions['DATA'] + ' True'
        res = self.cur.execute (expr)
        
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


    def doNZART_NZAWARD(self):
        expr = 'select distinct call ' + self.conditions['from'] + "call like 'ZL%' order by call"
        res = self.cur.execute (expr)
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

        self.awards['NZART']['NZAWARD'].update ( all)


    def doNZART_NZCENTURYAWARD(self):
        expr = 'select distinct grid ' + self.conditions['from'] 
        expr += "call like 'ZL%' and (grid like 'RE%' or grid like 'RF%' or grid like 'QD%' or grid like 'RD%' or grid like 'AE%' or grid like 'AF%') order by grid"
        res = self.cur.execute (expr)
        details = res.fetchall()

        grids = []
        for grid in details:
            grid = grid[0]
            #print (grid)
            if len(grid) == 6:
                grids.append (grid)
        self.awards['NZART']['NZCENTURYAWARD'].update ( {'Contacts': len(grids), "Required": 100})

    def doNZART_TIKI(self):
        expr = "select distinct count(call), band_rx "  + self.conditions['from'] + " call like '%ZL%' group by band_rx"
        res = self.cur.execute (expr)
        details = res.fetchall()

        r = {}
        c = 0
        for count, band in details:
            r[band] = {'Contacts': count, 'Required': 5 }
            if count >= 5:
                c += 1

        self.awards['NZART']['TIKI'].update ( {'Bands': r, 'Contacts': c, 'Required': 5})

    def doNZART_WORKEDALLPACIFIC(self):
        co = "("
        for code in self.continents:
            if self.continents[code] == 'OC': 
                co += " dxcc_id = " + str(code) + " or "
        co += "false) "

        expr = 'select  count(distinct dxcc_country), band_rx  ' + self.conditions['from'] + co + "group by band_rx"
        res = self.cur.execute (expr)
        details = res.fetchall()

        r = {}
        c = 0
        for count, band in details:
            r[band] = {'Contacts': count, 'Required': 30 }
            if count >= 30:
                c += 1

        self.awards['NZART']['WORKEDALLPACIFIC'].update ({'Bands': r, 'Contacts': c, 'Required': 5})

    def doINIT_Awards(self):
        self.awards = {}
        self.awards['CQ'] = {'CQWAZ': {'Name': 'CQ - Worked All Zones'}, 'CQWPX': {'Name': 'CQ - Worked Prefixes'}}
        self.awards['STATS'] = {}
        self.awards['ARRL'] = {}
        self.awards['ARRL']['DXCC'] = {}
        self.awards['NZART'] = {'NZAWARD': {'Name': 'NZART NZ Award - Work about 101 ZL\'s'},
                            'NZCENTURYAWARD': {'Name': 'NZART Century Award - Work 100 Grid Squares'},
                            'TIKI': {'Name': 'NZART TIKI Award - Work 5 ZL callsigns on 5 Bands'},
                            'WORKEDALLPACIFIC': {'Name': 'NZARD Worked All Pacific - Work at least 30 DXCC'}}
        self.awards['ARRL']['DXCC']['Notes'] = "LoTW or Paper QSL Cards only; No Maritime Mobile; No Repeaters - Assuming None; No Satellite - Assuming none"
        self.awards['RSGB'] = {'COMMONWEALTHCENTURY': {'Name': 'RSGB Commonwealth Century - Work 40 Commonwealth DXCC on each of 5 bands with extensions'}}
        self.awards['WIA'] = {'GRID': {'Name': 'WIA Grid - Work 100 VK Grid Squares'}, 
                        'WORKEDALLVK': {'Name': 'WIA Worked All VK - Work a combination of VK prefixes on a combination of bands'}}

    def doAWARDS_DXCC(self):
        self.doDXCC_MIXED ()
        self.doDXCC_MODE ("PHONE")
        self.doDXCC_MODE ("CW")
        self.doDXCC_MODE ("DATA")
        self.doDXCC_BAND ("160M")
        self.doDXCC_BAND ("80M")
        self.doDXCC_BAND ("40M")
        self.doDXCC_BAND ("30M")
        self.doDXCC_BAND ("20M")
        self.doDXCC_BAND ("17M")
        self.doDXCC_BAND ("15M")
        self.doDXCC_BAND ("12M")
        self.doDXCC_BAND ("10M")
        self.doDXCC_BAND ("6M")
        self.doDXCC_BAND ("2M")
        self.doDXCC_BAND ("70CM")
        self.awards['ARRL']['DXCC']['70CM']['Notes'] = 'Satellites Now Permitted - Still not checked'
        self.doDXCC_BAND ("23CM")
        self.awards['ARRL']['DXCC']['23CM']['Notes'] = 'Satellites Now Permitted - Still not checked'
        self.doDXCC_BAND ("12CM")
        self.awards['ARRL']['DXCC']['12CM']['Notes'] = 'Satellites Now Permitted - Still not checked'
        self.doDXCC_BAND ("3CM")
        self.awards['ARRL']['DXCC']['3CM']['Notes'] = 'Satellites Now Permitted - Still not checked'

        self.doDXCC_MISSINGQSL ()
        self.doDXCC_CONFIRMEDCOUNTRYCOUNTS ()
        self.doGetDXCC_table()


        self.awards['ARRL']['DXCC']['Satellite'] = {'Notes': 'ToDo: No Satellite Log Analysis has been done'}

        self.awards['ARRL']['DXCC']['5BDXCC'] = { 'Notes': 'Any Mode, 100 each on 80M, 40M, 20M, 15M, 10M; then endorceable for 160M, 30M, 17M, 12M, 6M, 2M'}

        self.awards['ARRL']['DXCC']['5BDXCC']['Primary'] = {}
        self.awards['ARRL']['DXCC']['5BDXCC']['Primary']['80M'] = {'Contacts': self.awards['ARRL']['DXCC']['80M']['Contacts'], 'Required':100}
        self.awards['ARRL']['DXCC']['5BDXCC']['Primary']['40M'] = {'Contacts': self.awards['ARRL']['DXCC']['40M']['Contacts'], 'Required':100}
        self.awards['ARRL']['DXCC']['5BDXCC']['Primary']['20M'] = {'Contacts': self.awards['ARRL']['DXCC']['20M']['Contacts'], 'Required':100}
        self.awards['ARRL']['DXCC']['5BDXCC']['Primary']['15M'] = {'Contacts': self.awards['ARRL']['DXCC']['15M']['Contacts'], 'Required':100}
        self.awards['ARRL']['DXCC']['5BDXCC']['Primary']['10M'] = {'Contacts': self.awards['ARRL']['DXCC']['10M']['Contacts'], 'Required':100}

        self.awards['ARRL']['DXCC']['5BDXCC']['Endorcements'] = {}
        self.awards['ARRL']['DXCC']['5BDXCC']['Endorcements']['160M'] = {'Contacts': self.awards['ARRL']['DXCC']['160M']['Contacts'], 'Required':100}
        self.awards['ARRL']['DXCC']['5BDXCC']['Endorcements']['30M'] = {'Contacts': self.awards['ARRL']['DXCC']['30M']['Contacts'], 'Required':100}
        self.awards['ARRL']['DXCC']['5BDXCC']['Endorcements']['17M'] = {'Contacts': self.awards['ARRL']['DXCC']['17M']['Contacts'], 'Required':100}
        self.awards['ARRL']['DXCC']['5BDXCC']['Endorcements']['12M'] = {'Contacts': self.awards['ARRL']['DXCC']['12M']['Contacts'], 'Required':100}
        self.awards['ARRL']['DXCC']['5BDXCC']['Endorcements']['6M'] = {'Contacts': self.awards['ARRL']['DXCC']['6M']['Contacts'], 'Required':100}
        self.awards['ARRL']['DXCC']['5BDXCC']['Endorcements']['2M'] = {'Contacts': self.awards['ARRL']['DXCC']['2M']['Contacts'], 'Required':100}


        challenge = self.awards['ARRL']['DXCC']['160M']['Contacts'] + self.awards['ARRL']['DXCC']['80M']['Contacts'] + self.awards['ARRL']['DXCC']['40M']['Contacts'] + self.awards['ARRL']['DXCC']['30M']['Contacts'] + \
            self.awards['ARRL']['DXCC']['20M']['Contacts'] + self.awards['ARRL']['DXCC']['17M']['Contacts'] + self.awards['ARRL']['DXCC']['15M']['Contacts'] + self.awards['ARRL']['DXCC']['12M']['Contacts'] + \
            self.awards['ARRL']['DXCC']['10M']['Contacts'] + self.awards['ARRL']['DXCC']['6M']['Contacts']
        self.awards['ARRL']['DXCC']['DXCC_CHALLENGE'] = {'Contacts': challenge, 'Required': 1000}



    def doAWARDS_CQWAZ(self):
        self.awards['CQ']['CQWAZ']['Notes'] = 'LoTW, eQSL or Paper QSL Cards only; No Satellite; Assuming eQSL is Authenticity Guarenteed; Assuming no satellites. Assuming dates OK '
        self.awards['CQ']['CQWAZ']['URL'] = 'https://cq-amateur-radio.com/cq_awards/cq_waz_awards/june2022-Final-with-color-break-for-Jose-to-review-Rev-B.pdf'
        self.doCQWAZ_MIXED ()
        self.awards['CQ']['CQWAZ']['Satellite'] = {'Notes': 'No Analysis has been done'}
        self.awards['CQ']['CQWAZ']['SSTV'] = {'Notes': 'No Analysis has been done'}
        self.awards['CQ']['CQWAZ']['EME'] = {'Notes': 'No Analysis has been done'}
        self.doCQWAZ_MODE ("DATA")
        self.doCQWAZ_MODE ("RTTY")
        self.doCQWAZ_MODE ("CW")
        self.doCQWAZ_MODE ("SSB")
        self.doCQWAZ_MODE ("AM")
        self.doCQWAZ_BAND ("160M") #doCQWAZ ("160M")
        self.doCQWAZ_BAND ("80M")
        self.doCQWAZ_BAND ("40M")
        self.doCQWAZ_BAND ("30M")
        self.doCQWAZ_BAND ("20M")
        self.doCQWAZ_BAND ("17M")
        self.doCQWAZ_BAND ("15M")
        self.doCQWAZ_BAND ("12M")
        self.doCQWAZ_BAND ("10M")
        self.doCQWAZ_BAND ("6M") #doCQWAZ ("6M")



    def doAWARDS_CQWPX(self):
        self.awards['CQ']['CQWPX']['CONTINENTS'] = {}
        self.awards['CQ']['CQWPX']['CONTINENTS']['MIXED'] = {}
        self.awards['CQ']['CQWPX']['CONTINENTS']['DIGITAL'] = {}
        self.awards['CQ']['CQWPX']['CONTINENTS'] = {'NA': {'MIXED': {}, 'DIGITAL': {}}, 'SA': {'MIXED': {}, 'DIGITAL': {}}, 'EU': {'MIXED': {}, 'DIGITAL': {}}, 'AS': {'MIXED': {}, 'DIGITAL': {}}, 'AF': {'MIXED': {}, 'DIGITAL': {}}, 'OC': {'MIXED': {}, 'DIGITAL': {}}}
        cqwpxDetails = self.doCQWPX('MIXED') # For everything
        cqwpxDetailsDigital = self.doCQWPX('DIGITAL') # For everything

        self.doCQWPX_MODE ("Mixed", 400, self.all_mode, cqwpxDetails )
        self.doCQWPX_MODE ("CW", 300, self.cw_mode, cqwpxDetails )
        self.doCQWPX_MODE ("SSB", 300, self.ssb_mode, cqwpxDetails )
        self.doCQWPX_MODE ("Digital", 300, self.data_mode, cqwpxDetails )

        self.doCQWPX_BAND ("160M", 'MIXED', 50, cqwpxDetails)
        self.doCQWPX_BAND ("80M", 'MIXED', 175, cqwpxDetails)
        self.doCQWPX_BAND ("160M", 'MIXED', 175, cqwpxDetails)
        self.doCQWPX_BAND ("40M", 'MIXED', 250, cqwpxDetails)
        self.doCQWPX_BAND ("30M", 'MIXED', 250, cqwpxDetails)
        self.doCQWPX_BAND ("20M", 'MIXED', 300, cqwpxDetails)
        self.doCQWPX_BAND ("17M", 'MIXED', 300, cqwpxDetails)
        self.doCQWPX_BAND ("15M", 'MIXED', 300, cqwpxDetails)
        self.doCQWPX_BAND ("12M", 'MIXED', 300, cqwpxDetails)
        self.doCQWPX_BAND ("10M", 'MIXED', 300, cqwpxDetails)
        self.doCQWPX_BAND ("6M", 'MIXED', 250, cqwpxDetails)

        self.doCQWPX_BAND ("160M", 'DIGITAL', 50, cqwpxDetailsDigital)
        self.doCQWPX_BAND ("80M", 'DIGITAL', 175, cqwpxDetailsDigital)
        self.doCQWPX_BAND ("160M", 'DIGITAL', 175, cqwpxDetailsDigital)
        self.doCQWPX_BAND ("40M", 'DIGITAL', 250, cqwpxDetailsDigital)
        self.doCQWPX_BAND ("30M", 'DIGITAL', 250, cqwpxDetailsDigital)
        self.doCQWPX_BAND ("20M", 'DIGITAL', 300, cqwpxDetailsDigital)
        self.doCQWPX_BAND ("17M", 'DIGITAL', 300, cqwpxDetailsDigital)
        self.doCQWPX_BAND ("15M", 'DIGITAL', 300, cqwpxDetailsDigital)
        self.doCQWPX_BAND ("12M", 'DIGITAL', 300, cqwpxDetailsDigital)
        self.doCQWPX_BAND ("10M", 'DIGITAL', 300, cqwpxDetailsDigital)
        self.doCQWPX_BAND ("6M", 'DIGITAL', 250, cqwpxDetailsDigital)

        self.doCQWPX_CONTINENT ("NA", "MIXED", 160)
        self.doCQWPX_CONTINENT ("SA", "MIXED", 95)
        self.doCQWPX_CONTINENT ("EU", "MIXED", 160)
        self.doCQWPX_CONTINENT ("AF", "MIXED", 90)
        self.doCQWPX_CONTINENT ("AS", "MIXED", 75)
        self.doCQWPX_CONTINENT ("OC", "MIXED", 60)

        self.doCQWPX_CONTINENT ("NA", "DIGITAL", 160)
        self.doCQWPX_CONTINENT ("SA", "DIGITAL", 95)
        self.doCQWPX_CONTINENT ("EU", "DIGITAL", 160)
        self.doCQWPX_CONTINENT ("AF", "DIGITAL", 90)
        self.doCQWPX_CONTINENT ("AS", "DIGITAL", 75)
        self.doCQWPX_CONTINENT ("OC", "DIGITAL", 60)

    def doAWARDS_NZART(self):
        self.doNZART_NZAWARD()
        self.doNZART_NZCENTURYAWARD()
        self.doNZART_TIKI()
        self.doNZART_WORKEDALLPACIFIC()

    def doWIA_WORKEDALLVK (self):
        # Complex award with combo of calls worked and either bands or DXCC entities
        expr = 'with '
        select = 'select * from '

        for area in ('VK0',):
            expr += '%sC as' % (area)
            expr += '(select count( distinct call) '
            expr += self.conditions['from']
            expr += 'call like "%s%%" and ' % (area)
            expr += self.conditions['LoTWCard']
            expr += self.conditions['no_maritime'] + " True), \n"

            expr += '%sB as' % (area)
            expr += '(select count( distinct dxcc_country) '
            expr += self.conditions['from']
            expr += 'call like "%s%%" and ' % (area)
            expr += self.conditions['LoTWCard']
            expr += self.conditions['no_maritime'] + " True), \n"

            select += '%sC, %sB, ' % (area, area)

        for area in ('VK1', 'VK2', 'VK3', 'VK4', 'VK5', 'VK6', 'VK7', 'VK8'):

            expr += '%sC as' % (area)
            expr += '(select count( distinct call) '
            expr += self.conditions['from']
            expr += 'call like "%s%%" and ' % (area)
            expr += self.conditions['LoTWCard']
            expr += self.conditions['no_maritime'] + " True), \n"

            expr += '%sB as' % (area)
            expr += '(select count( distinct band_tx) '
            expr += self.conditions['from']
            expr += 'call like "%s%%" and ' % (area)
            expr += self.conditions['LoTWCard']
            expr += self.conditions['no_maritime'] + " True), \n"

            select += '%sC, %sB, ' % (area, area)

        for area in ('VK9',):

            expr += '%sC as' % (area)
            expr += '(select count( distinct call) '
            expr += self.conditions['from']
            expr += 'call like "%s%%" and ' % (area)
            expr += self.conditions['LoTWCard']
            expr += self.conditions['no_maritime'] + " True), \n"

            expr += '%sB as' % (area)
            expr += '(select count( distinct dxcc_country) '
            expr += self.conditions['from']
            expr += 'call like "%s%%" and ' % (area)
            expr += self.conditions['LoTWCard']
            expr += self.conditions['no_maritime'] + " True), \n"

            select += '%sC, %sB, ' % (area, area)

        expr = expr[:len(expr)-3]
        expr += select
        expr = expr[:len(expr)-2]

        res = self.cur.execute (expr)
        details = res.fetchone()

        self.awards['WIA']['WORKEDALLVK']['AREAS'] = {}
        self.awards['WIA']['WORKEDALLVK']['Notes'] = 'For VK ops only. Different rules for DX'

        calls = (3,3,10,10,10,10,10,3,3,4)
        div = (2,2,3,3,3,3,3,2,2,3)

        count_calls = 0
        count_diversity = 0 

        i = 0
        j = 0
        for area in ('VK0','VK1', 'VK2', 'VK3', 'VK4', 'VK5', 'VK6', 'VK7', 'VK8', 'VK9'):
            self.awards['WIA']['WORKEDALLVK']['AREAS'][area] = {'Notes': 'Diversity is Bands, or DXCC for VK0 and VK9',
                                                        'Calls': {},
                                                        'Diversity': {}}
            self.awards['WIA']['WORKEDALLVK']['AREAS'][area]['Calls']['Contacts'] = details[i]
            self.awards['WIA']['WORKEDALLVK']['AREAS'][area]['Calls']['Required'] = calls[j]
            if details[i] >= calls[j]: 
                count_calls += 1
            i += 1
            self.awards['WIA']['WORKEDALLVK']['AREAS'][area]['Diversity']['Contacts'] = details[i]
            self.awards['WIA']['WORKEDALLVK']['AREAS'][area]['Diversity']['Required'] = div[j]
            if details[i] >= div[j]:
                count_diversity += 1    
            i += 1
            j += 1

            self.awards['WIA']['WORKEDALLVK']['CONTACTS'] = {'Contacts': count_calls, 
                                                        'Required': 10, 
                                                        'Notes': 'Contacts is number of AREAS met with callsign'}
            self.awards['WIA']['WORKEDALLVK']['DIVERSITY'] = {'Contacts': count_diversity, 
                                                        'Required': 10, 
                                                        'Notes': 'Diversity is number of AREAS met with band or DXCC'}

    def doWIA_GRID(self):
        expr = 'select count(distinct  substr(grid,1,4)) ' + self.conditions['from'] + self.conditions['no_maritime'] + self.conditions['LoTWCard'] +  ' grid is not NULL'
        res = self.cur.execute (expr)
        self.awards['WIA']['GRID']['Contacts'] = res.fetchone()[0]
        self.awards['WIA']['GRID']['Required'] = 100 
        self.awards['WIA']['GRID']['Max'] = 1800
        self.awards['WIA']['GRID']['Notes'] = 'Assumes HF only'

    def doAWARDS_WIA(self):
        self.awards['WIA']['WIAOCEANIA'] = {}
        self.awards['WIA']['WIAWORKEDALLCONTINENTS'] = {'Note': 'Physical cards only. I mean, SERIOUSLY?'}
        self.doWIA_GRID()
        self.doWIA_WORKEDALLVK()

    def doRSGB_COMMONWEALTHCENTURY(self):
        co = "("
        for code in self.commonwealth:
            co += " dxcc_id = " + str(code) + " or "
        co += "false) "

        expr = 'select distinct call, dxcc_id, dxcc_country, band_rx  ' + self.conditions['from'] + co + ' and ' + self.conditions['LoTWeQSLCard'] + ' true '
        res = self.cur.execute (expr)
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
        self.awards['RSGB']['COMMONWEALTHCENTURY'].update (returns)


    def doAWARDS_RSGB(self):
        self.doRSGB_COMMONWEALTHCENTURY()


    def doSTATS(self):
        self.doSTATS_QSL()
        self.doSTATS_BANDS()
        self.doSTATS_MODES()
        self.doSTATS_DXCCBYDATE()
        self.doSTATS_MISSINGDXCCCONFIRM()
        self.doSTATS_GRIDS()
        self.doSTATS_LOTWSTATS()


    def start(self):
        global continents
        global table
        global rawtable

        #self.doINIT()
        self.doDatabase()
        self.doINIT_Awards()
        self.continents = self.doGetDXCC_Continent() 

        self.doAWARDS_DXCC()
        self.doAWARDS_CQWAZ()
        self.doAWARDS_CQWPX()
        self.doAWARDS_NZART()
        self.doAWARDS_RSGB()
        self.doAWARDS_WIA()
        self.doSTATS()


        # # Does not view well in Safari
        # xml = dicttoxml(awards)
        # f=open ("demofile2.xml", "w")
        # f.write (parseString(xml).toprettyxml())
        # f.close()


        self.table = self.awards['ARRL']['DXCC']['Table']
        self.rawtable = self.awards['ARRL']['DXCC']['RawTable']

        self.awards['ARRL']['DXCC'].pop('Table')
        self.awards['ARRL']['DXCC'].pop('RawTable')



#print (awards)
analysis = analysis()

if __name__ == "__main__":
    analysis.start()
    #pp.pprint (awards)
    
    
    # print (awards['ARRL']['DXCC']['Table'])

    #pp.pprint (awards['NZART'])

    #j = json.dumps(awards, indent = 8)
    #print (j)
















