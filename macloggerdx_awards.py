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



conditions = {"no_maritime": " not call like '%/MM' and ",
              "LoTW": " qsl_received like '%LoTW%' and ",
              "eQSL": " qsl_received like '%eQSL%' and ",
              "LoTWeQSL": " (qsl_received like '%LoTW%' or qsl_received like '%eQSL%') and ",
              "startDXCC": " select count (distinct dxcc_country) ",
              "startCQWAZ": " select count (distinct cq_zone) ",
              "startCQWAZ_BAND": " select distinct count(*), mode , band_rx from ( select  count(*) as c, cq_zone, mode, band_rx ",
              "stopCQWAZ_BAND": " group by  cq_zone, mode, band_rx ) group by mode, band_rx ",
              "from": " from qso_table_v007  where ",
              "end": " True "}

# mode == FT8, USB, LSB, etc
# band_tx == 20M

#/usr/libexec/PlistBuddy ~/Documents/MLDX_Logs/mode_mapping.plist 



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








def doSTATS_QSL ():
    global awards

    # Compund statement with multiple SQL superimposed on each other

    #log.info ("      Any mode, No Maritime")
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
    #log.info ("        Total, LoTW, eQSL, LOTW+eQSL - %s" %(awards['STATS']['STATS_QSL']))



def doSTATS_BANDS ():
    global awards

    #log.info ("      QSO by Band")
    expr = "select count(*), band_rx "
    expr += conditions ['from']
    expr += " true group by band_rx"

    res = cur.execute (expr)
    details = res.fetchall()
    combined = []
    for count, band in details:
        combined.append ({'Count': count, 'Band': band})

    awards['STATS']['STATS_BANDS'] = combined
    #log.info ("        Bands - %s" %(['STATS_BANDS']))

def doSTATS_MODES ():
    global awards

    #log.info ("      QSO by Mode")
    expr = "select count(*), mode "
    expr += conditions ['from']
    expr += " true group by mode"

    res = cur.execute (expr)
    details = res.fetchall()
    combined = []
    for count, mode in details:
        combined.append ({'Count': count, 'Mode': mode})
    awards['STATS']['STATS_MODES'] = combined
    #log.info ("        Modes - %s" %(['STATS_MODES']))

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

    res = cur.execute (expr)

    last_dxcc = ""
    awards['STATS']['STATS_DXCCBYDATE'] = []
    for dxcc, day in res.fetchall():
        if dxcc != last_dxcc:
            day = str(datetime.datetime.fromtimestamp(day))
            awards['STATS']['STATS_DXCCBYDATE'].append ({'DXCC':dxcc, 'Day':day})
            last_dxcc = dxcc
    #log.info ("        Modes - %s" %(awards['STATS']['STATS_DXCCBYDATE']))




def doCQWAZ_MIXED ():
    global awards

    #log.info ("      Mixed - Any Mode, Any Band")
    expr = conditions['startCQWAZ'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTWeQSL'] + conditions['end']
    res = cur.execute (expr)
    awards['CQ']['CQWAZ']['CQWAZ_MIXED'] = {'Contacts':res.fetchone()[0], 'Required':40}
    #log.info ("        Confirmed (/40) - %s" %(awards['CQ']['CQWAZ']['CQWAZ_MIXED']['Contacts']))


def doCQWAZ_BAND(band):
    global awards

    #log.info ("      %s - Per Mode, Any Band" %(band))
    expr = conditions['startCQWAZ_BAND'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTWeQSL'] + " band_rx = '" + band + "' and " + conditions['end'] + conditions['stopCQWAZ_BAND']
    res = cur.execute (expr)
    w = res.fetchall()
    x = []
    for a,b,c in w:
        x.append ({'Contacts': a, 'Required':40, 'Band': b, 'Mode': c})
    awards['CQ']['CQWAZ']['CQWAZ_' + band] = x
    #log.info ("        Confirmed (/40) - %s" %(awards['CQ']['CQWAZ']['CQWAZ_' + band]))

def doCQWAZ(band):
    global awards

    #log.info ("      %s - Any Mode, Any Band" % (band))
    expr = conditions['startCQWAZ'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTWeQSL'] + " band_rx = '" + band + "' and " + conditions['end']
    res = cur.execute (expr)
    awards['CQ']['CQWAZ']['CQWAZ_' + band] = {'Contacts':res.fetchone()[0], 'Required':40}
    #log.info ("        Confirmed (/40) - %s" %(awards['CQ']['CQWAZ']['CQWAZ_' + band]['Contacts']))

def doCQWAZ_MODE (mode):
    global awards

    #log.info ("      %s - Any Mode, Any Band" % (mode))
    expr = conditions['startCQWAZ'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTWeQSL'] + conditions[mode] + conditions['end']
    res = cur.execute (expr)
    awards['CQ']['CQWAZ']['CQWAZ_' + mode] = {'Contacts':res.fetchone()[0], 'Required':40}
    #log.info ("        Confirmed (/40) - %s" %(awards['CQ']['CQWAZ']['CQWAZ_' + mode]['Contacts']))

def doDXCC_MIXED():
    global awards
    #log.info ("      Mixed - Any Mode, Any Band")
    expr = conditions['startDXCC'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTW'] + conditions['end']
    res = cur.execute (expr)
    awards['ARRL']['DXCC']['DXCC_MIXED'] = {'Contacts':res.fetchone()[0], 'Required':100}
    #log.info ("        Confirmed (/100) - %s" %(awards['ARRL']['DXCC']['DXCC_MIXED']['Contacts']))


def doDXCC_MODE(mode):
    global awards

    #log.info ("      %s - Not Digital, Any Band" % (mode))
    expr = conditions['startDXCC'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTW'] + conditions[mode] + conditions['end']
    res = cur.execute (expr)
    awards['ARRL']['DXCC']['DXCC_' + mode] = {'Contacts':res.fetchone()[0], 'Required':100}
    #log.info ("        Confirmed (/100) - %s" %(awards['ARRL']['DXCC']['DXCC_' + mode]['Contacts']))

def doDXCC_BAND(band):
    global awards

    expr = conditions['startDXCC'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTW'] +  " band_rx = '" + band + "' and " + conditions['end']
    res = cur.execute (expr)
    awards['ARRL']['DXCC'][band] = {'Contacts':res.fetchone()[0], 'Required':100}
    #log.info ("      %s - Any Mode" % (band))
    #log.info ("        Confirmed (/100) - %s" %(awards['ARRL']['DXCC']['DXCC_' + band]['Contacts']))

def doDXCC_MISSINGQSL():
    global awards

    expr = "SELECT distinct dxcc_country FROM qso_table_v007 where " + conditions['no_maritime'] + " True " + "EXCEPT "
    expr = expr + "SELECT distinct dxcc_country FROM qso_table_v007 where " + conditions['no_maritime'] + conditions['LoTW'] + " True"
    res = cur.execute (expr)
    output = res.fetchall()
    awards['ARRL']['DXCC']['DXCC_MISSINGQSL'] = {'DXCC': output, 'Count': len(output)}
    #log.info ("        %s" %(awards['ARRL']['DXCC']['DXCC_MISSINGQSL']))


def doCQWPX_MODE(mode_desc, count, modes, details):
    global awards

    combined = []
    for band,y in details.items(): # key, value
        log.debug (band)
        for mode, prefixes in y.items():
            log.debug (mode)
            if mode in modes:
                #print (prefixes)
                combined = list(set(combined) | set(prefixes))
                #count = count + len(prefixes)
    awards['CQ']['CQWPX']['CQWPX_'+mode_desc] = {'Contacts':len(combined), 'Required':count}

def doCQWPX_BAND(target_band, full_mode, count, details):
    global awards

    combined = []
    for band,y in details.items(): # key, value
        if band == target_band:
            log.debug (band)
            for mode, prefixes in y.items():
                #log.debug (mode)
                #print (prefixes)
                combined = list(set(combined) | set(prefixes))
                #count = count + len(prefixes)
    if not 'CQWPX_'+target_band in awards['CQ']['CQWPX']:
        awards['CQ']['CQWPX']['CQWPX_'+target_band] = {}
    awards['CQ']['CQWPX']['CQWPX_'+target_band][full_mode] = {'Contacts':len(combined), 'Required':count}

    #log.info ("      %s - Any Mode" % (target_band))
    #log.info ("        Confirmed (/%s) - %s" %(count, len(combined)))


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

    expr = "select DISTINCT call, dxcc_id from qso_table_v007 where " + conditions['LoTW'] + co
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


    awards['CQ']['CQWPX']['CONTINENTS'][continent][mode] = {'Prefixes': len(prefixes), 'Required': count}


def doCQWPX(mode):
    # https://cq-amateur-radio.com/cq_awards/cq_wpx_awards/cq-wpx-award-rules-022017.pdf
    global awards
    #global cur

    details = {'160M': {}, '80M': {}, '40M': {}, '30M': {}, '20M': {}, '17M': {}, '15M': {}, '12M': {}, 
               '10M': {}, '6M': {}, '2M': {}, '70CM': {}, '23CM': {}, '3C': {}}



    log.info ("      WPX - Any Mode" )
    #expr = conditions['startDXCC'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTW'] +  " band_rx = '" + band + "' and " + conditions['end']
    expr = "select DISTINCT call, band_rx, mode from qso_table_v007 where " + conditions['LoTW'] + " True "
    if mode == 'DIGITAL':
        expr += ' and ' + conditions['DATA'] + ' True'
    #print (expr)
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
    #log.info ("NZART: NZ AWARD")

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
    all['ZL1'] = {'Contatcs': len (zl['ZL1']), 'Required': 35}
    all['ZL2'] = {'Contatcs': len (zl['ZL2']), 'Required': 35}
    all['ZL3'] = {'Contatcs': len (zl['ZL3']), 'Required': 20}
    all['ZL4'] = {'Contatcs': len (zl['ZL4']), 'Required': 10}
    all['ZL789'] = {'Contatcs': len (zl['ZL789']), 'Required': 1, 'Notes': 'Special Conditions'}
    all['Notes'] = 'Require ZL1,2,3&4 and one contact with an external teritory etc'

    awards['NZART']['NZAWARD'] = all


def doNZART_NZCENTURYAWARD():
    global awards
    log.info ("NZART: NZ CENTURY AWARD")

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
    #print (grid)

    awards['NZART']['NZCENTURYAWARD'] = {'Contacts': len(grids), "Required": 100}
    #log.info ("    Details %s" % (awards['NZART']['NZCENTURYAWARD']))


def doNZART_TIKI():
    global awards
    log.info ("NZART: TIKI")

    expr = "select distinct count(call), band_rx "  + conditions['from'] + " call like '%ZL%' group by band_rx"
    res = cur.execute (expr)
    details = res.fetchall()

    r = {}
    c = 0
    for count, band in details:
        r[band] = {'Contacts': count, 'Required': 5 }
        if count >= 5:
            c += 1

    awards['NZART']['TIKI'] = {'Bands': r, 'BandsQualified': c, 'Required': 5}
    #log.info ("    Details %s" % (awards['NZART']['TIKI']))



def doNZART_WORKEDALLPACIFIC():
    global awards
    log.info ("NZART: WORKEDALLPACIFIC")

    co = "("
    #for code in oceania:
    #    co += " dxcc_id = " + str(code) + " or "
    #co += "false) "

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

    awards['NZART']['WORKEDALLPACIFIC'] = {'Bands': r, 'BandsQualified': c, 'Required': 5}

    #print (expr)
    #print (details)



def doINIT_Awards():
    global awards    

    awards = {}
    awards['CQ'] = {}
    awards['CQ']['CQWAZ'] = {}
    awards['CQ']['CQWPX'] = {}
    awards['STATS'] = {}
    awards['ARRL'] = {}
    awards['ARRL']['DXCC'] = {}
    awards['NZART'] = {}
    awards['NZART']['NZAWARD'] = {}
    awards['NZART']['NZCENTURYAWARD'] = {}
    awards['NZART']['TIKI'] = {}
    awards['NZART']['WORKEDALLPACIFIC'] = {}
    awards['ARRL']['DXCC']['Notes'] = "LoTW or Paper QSL Cards only; No Maritime Mobile; No Repeaters - Assuming None; No Satellite - Assuming none"


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

    awards['ARRL']['DXCC']['Satellite'] = {'Notes': 'ToDo: No Satellite Log Analysis has been done'}

    awards['ARRL']['DXCC']['5BDXCC'] = { 'Notes': 'Any Mode, 100 each on 80M, 40M, 20M, 15M, 10M; then endorceable for 160M, 30M, 17M, 12M, 6M, 2M'}

    awards['ARRL']['DXCC']['5BDXCC']['Primary'] = {}
    awards['ARRL']['DXCC']['5BDXCC']['Primary']['80M'] = {'Contacts': awards['ARRL']['DXCC']['80M']['Contacts'], 'Count':100}
    awards['ARRL']['DXCC']['5BDXCC']['Primary']['40M'] = {'Contacts': awards['ARRL']['DXCC']['40M']['Contacts'], 'Count':100}
    awards['ARRL']['DXCC']['5BDXCC']['Primary']['20M'] = {'Contacts': awards['ARRL']['DXCC']['20M']['Contacts'], 'Count':100}
    awards['ARRL']['DXCC']['5BDXCC']['Primary']['15M'] = {'Contacts': awards['ARRL']['DXCC']['15M']['Contacts'], 'Count':100}
    awards['ARRL']['DXCC']['5BDXCC']['Primary']['10M'] = {'Contacts': awards['ARRL']['DXCC']['10M']['Contacts'], 'Count':100}

    awards['ARRL']['DXCC']['5BDXCC']['Endorcements'] = {}
    awards['ARRL']['DXCC']['5BDXCC']['Endorcements']['160M'] = {'Contacts': awards['ARRL']['DXCC']['160M']['Contacts'], 'Count':100}
    awards['ARRL']['DXCC']['5BDXCC']['Endorcements']['30M'] = {'Contacts': awards['ARRL']['DXCC']['30M']['Contacts'], 'Count':100}
    awards['ARRL']['DXCC']['5BDXCC']['Endorcements']['17M'] = {'Contacts': awards['ARRL']['DXCC']['17M']['Contacts'], 'Count':100}
    awards['ARRL']['DXCC']['5BDXCC']['Endorcements']['12M'] = {'Contacts': awards['ARRL']['DXCC']['12M']['Contacts'], 'Count':100}
    awards['ARRL']['DXCC']['5BDXCC']['Endorcements']['6M'] = {'Contacts': awards['ARRL']['DXCC']['6M']['Contacts'], 'Count':100}
    awards['ARRL']['DXCC']['5BDXCC']['Endorcements']['2M'] = {'Contacts': awards['ARRL']['DXCC']['2M']['Contacts'], 'Count':100}


    #log.info ("      DXCC Challenge - Any mode. 160M-6M. 1000 Entries")
    challenge = awards['ARRL']['DXCC']['160M']['Contacts'] + awards['ARRL']['DXCC']['80M']['Contacts'] + awards['ARRL']['DXCC']['40M']['Contacts'] + awards['ARRL']['DXCC']['30M']['Contacts'] + \
        awards['ARRL']['DXCC']['20M']['Contacts'] + awards['ARRL']['DXCC']['17M']['Contacts'] + awards['ARRL']['DXCC']['15M']['Contacts'] + awards['ARRL']['DXCC']['12M']['Contacts'] + \
        awards['ARRL']['DXCC']['10M']['Contacts'] + awards['ARRL']['DXCC']['6M']['Contacts']
    #log.info ("        Confirmed (/1000) - %s" % (challenge))
    awards['ARRL']['DXCC']['DXCC_CHALLENGE'] = {'Contacts': challenge, 'Required': 1000}



def doAWARDS_CQWAZ():
    global awards

    awards['CQ']['CQWAZ'] = {'Notes': 'LoTW, eQSL or Paper QSL Cards only; No Satellite; Assuming eQSL is Authenticity Guarenteed; Assuming no satellites. Assuming dates OK ', 
                             'URL': 'https://cq-amateur-radio.com/cq_awards/cq_waz_awards/june2022-Final-with-color-break-for-Jose-to-review-Rev-B.pdf'}


    #log.info ("CQ WAZ: General Conditions")
    #log.info ("      https://cq-amateur-radio.com/cq_awards/cq_waz_awards/june2022-Final-with-color-break-for-Jose-to-review-Rev-B.pdf")
    #log.info ("      LoTW, eQSL or Paper QSL Cards only")
    #log.info ("      No Satellite ")
    #log.info ("      ***Assuming all eQSL is Authenticity Guarenteed***")
    #log.info ("      ***Assuming no satellite***")
    #log.info ("      ***Assuming dates OK***")


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
    awards['CQ']['CQWPX']['CONTINENTS'] = {'NA': {}, 'SA': {}, 'EU': {}, 'AS': {}, 'AF': {}, 'OC': {}}

    awards['CQ']['CQWPX']['CONTINENTS']['NA']['MIXED'] = {}
    awards['CQ']['CQWPX']['CONTINENTS']['SA']['MIXED'] = {}
    awards['CQ']['CQWPX']['CONTINENTS']['EU']['MIXED'] = {}
    awards['CQ']['CQWPX']['CONTINENTS']['AS']['MIXED'] = {}
    awards['CQ']['CQWPX']['CONTINENTS']['AF']['MIXED'] = {}
    awards['CQ']['CQWPX']['CONTINENTS']['OC']['MIXED'] = {}

    awards['CQ']['CQWPX']['CONTINENTS']['NA']['DIGITAL'] = {}
    awards['CQ']['CQWPX']['CONTINENTS']['SA']['DIGITAL'] = {}
    awards['CQ']['CQWPX']['CONTINENTS']['EU']['DIGITAL'] = {}     
    awards['CQ']['CQWPX']['CONTINENTS']['AS']['DIGITAL'] = {}
    awards['CQ']['CQWPX']['CONTINENTS']['AF']['DIGITAL'] = {}
    awards['CQ']['CQWPX']['CONTINENTS']['OC']['DIGITAL'] = {}



    log.info ("CQ WPX: General Conditions")
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

    log.info ("NZART Awards")
    doNZART_NZAWARD()
    doNZART_NZCENTURYAWARD()
    doNZART_TIKI()
    doNZART_WORKEDALLPACIFIC()

def doSTATS():
    global awards

    # Not contests but interesting information to show
    doSTATS_QSL()
    doSTATS_BANDS()
    doSTATS_MODES()
    doSTATS_DXCCBYDATE()





if True:
    doINIT()
    doDatabase()
    doINIT_Awards()
    continents = doGetDXCC_Continent() 

    doAWARDS_DXCC()
    doAWARDS_CQWAZ()
    doAWARDS_CQWPX()

    doAWARDS_NZART()
    doSTATS()


    # Does not view well in Safari
    xml = dicttoxml(awards)
    f=open ("demofile2.xml", "w")
    f.write (parseString(xml).toprettyxml())
    f.close()


    pp.pprint (awards)

    #pp.pprint (awards['NZART'])

    #j = json.dumps(awards, indent = 8)
    #print (j)
















