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
import datetime
import json

# Change root logger level from WARNING (default) to NOTSET in order for all messages to be delegated.
logging.getLogger().setLevel(logging.NOTSET)

# Add stdout handler, with level INFO
console = logging.StreamHandler(sys.stdout)
console.setLevel(logging.INFO)
formater = logging.Formatter('%(name)-13s: %(levelname)-8s %(message)s')
console.setFormatter(formater)
logging.getLogger().addHandler(console)

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

#ToDO Extend this
# Unused
bands = ["160M", "80M", "40M", "30M", "20M", "17M", "15M", "12M", "10M", "6M", "2M", "70CM"]

data_statement = " (False "
for d in data_mode:
    data_statement = data_statement + " or mode = '" + d + "' "
data_statement = data_statement + " ) and "
log.debug (data_statement)
conditions["DATA"] = data_statement

cw_statement = " (False "
for d in cw_mode:
    cw_statement = cw_statement + " or mode = '" + d + "' "
cw_statement = cw_statement + " ) and "
log.debug (cw_statement)
conditions["CW"] = cw_statement

phone_statement = " (False "
for d in phone_mode:
    phone_statement = phone_statement + " or mode = '" + d + "' "
phone_statement = phone_statement + " ) and "
log.debug (phone_statement)
conditions["PHONE"] = phone_statement

am_statement = " (False "
for d in am_mode:
    am_statement = am_statement + " or mode = '" + d + "' "
am_statement = am_statement + " ) and "
log.debug (am_statement)
conditions["AM"] = am_statement

ssb_statement = " (False "
for d in ssb_mode:
    ssb_statement = ssb_statement + " or mode = '" + d + "' "
ssb_statement = ssb_statement + " ) and "
log.debug (ssb_statement)
conditions["SSB"] = ssb_statement

rtty_statement = " (False "
for d in rtty_mode:
    rtty_statement = rtty_statement + " or mode = '" + d + "' "
rtty_statement = rtty_statement + " ) and "
log.debug (rtty_statement)
conditions["RTTY"] = rtty_statement


conn = sqlite3.connect ("/Users/darryl/Documents/MLDX_Logs/MacLoggerDX.sql")



cur = conn.cursor()



def doSTATS_QSL ():
    global awards

    # Compund statement with multiple SQL superimposed on each other

    log.info ("      Any mode, No Maritime")
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

    awards['STATS_QSL'] = {'Total': details[0], 'LoTW_Total': details[1], 'eQSL_Total': details[2], 'LoTWeQSL_Total': details[3]}
    log.info ("        Total, LoTW, eQSL, LOTW+eQSL - %s" %(awards['CQWAZ_MIXED']['Contacts']))



def doSTATS_BANDS ():
    global awards

    log.info ("      QSO by Band")
    expr = "select count(*), band_rx "
    expr += conditions ['from']
    expr += " true group by band_rx"

    res = cur.execute (expr)
    details = res.fetchall()
    combined = []
    for count, band in details:
        combined.append ({'Count': count, 'Band': band})

    awards['STATS_BANDS'] = combined
    log.info ("        Bands - %s" %(['STATS_BANDS']))

def doSTATS_MODES ():
    global awards

    log.info ("      QSO by Mode")
    expr = "select count(*), mode "
    expr += conditions ['from']
    expr += " true group by mode"

    res = cur.execute (expr)
    details = res.fetchall()
    combined = []
    for count, mode in details:
        combined.append ({'Count': count, 'Mode': mode})
    awards['STATS_MODES'] = combined
    log.info ("        Modes - %s" %(['STATS_MODES']))

def doSTATS_DXCCBYDATE ():
    global awards

    log.info ("      DXCC BY DATE")
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
    awards['STATS_DXCCBYDATE'] = []
    for dxcc, day in res.fetchall():
        if dxcc != last_dxcc:
            day = str(datetime.datetime.fromtimestamp(day))
            awards['STATS_DXCCBYDATE'].append ({'DXCC':dxcc, 'Day':day})
            last_dxcc = dxcc
    log.info ("        Modes - %s" %(awards['STATS_DXCCBYDATE']))




def doCQWAZ_MIXED ():
    global awards

    log.info ("      Mixed - Any Mode, Any Band")
    expr = conditions['startCQWAZ'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTWeQSL'] + conditions['end']
    res = cur.execute (expr)
    awards['CQWAZ_MIXED'] = {'Contacts':res.fetchone()[0], 'Required':40}
    log.info ("        Confirmed (/40) - %s" %(awards['CQWAZ_MIXED']['Contacts']))


def doCQWAZ_BAND(band):
    global awards

    log.info ("      %s - Per Mode, Any Band" %(band))
    expr = conditions['startCQWAZ_BAND'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTWeQSL'] + " band_rx = '" + band + "' and " + conditions['end'] + conditions['stopCQWAZ_BAND']
    res = cur.execute (expr)
    w = res.fetchall()
    x = []
    for a,b,c in w:
        x.append ({'Contacts': a, 'Required':40, 'Band': b, 'Mode': c})
    awards['CQWAZ_' + band] = x
    log.info ("        Confirmed (/40) - %s" %(awards['CQWAZ_' + band]))

def doCQWAZ(band):
    global awards

    log.info ("      %s - Any Mode, Any Band" % (band))
    expr = conditions['startCQWAZ'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTWeQSL'] + " band_rx = '" + band + "' and " + conditions['end']
    res = cur.execute (expr)
    awards['CQWAZ_' + band] = {'Contacts':res.fetchone()[0], 'Required':40}
    log.info ("        Confirmed (/40) - %s" %(awards['CQWAZ_' + band]['Contacts']))

def doCQWAZ_MODE (mode):
    global awards

    log.info ("      %s - Any Mode, Any Band" % (mode))
    expr = conditions['startCQWAZ'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTWeQSL'] + conditions[mode] + conditions['end']
    res = cur.execute (expr)
    awards['CQWAZ_' + mode] = {'Contacts':res.fetchone()[0], 'Required':40}
    log.info ("        Confirmed (/40) - %s" %(awards['CQWAZ_' + mode]['Contacts']))

def doDXCC_MIXED():
    global awards
    log.info ("      Mixed - Any Mode, Any Band")
    expr = conditions['startDXCC'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTW'] + conditions['end']
    res = cur.execute (expr)
    awards['DXCC_MIXED'] = {'Contacts':res.fetchone()[0], 'Required':100}
    log.info ("        Confirmed (/100) - %s" %(awards['DXCC_MIXED']['Contacts']))


def doDXCC_MODE(mode):
    global awards

    log.info ("      %s - Not Digital, Any Band" % (mode))
    expr = conditions['startDXCC'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTW'] + conditions[mode] + conditions['end']
    res = cur.execute (expr)
    awards['DXCC_' + mode] = {'Contacts':res.fetchone()[0], 'Required':100}
    log.info ("        Confirmed (/100) - %s" %(awards['DXCC_' + mode]['Contacts']))

def doDXCC_BAND(band):
    global awards

    expr = conditions['startDXCC'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTW'] +  " band_rx = '" + band + "' and " + conditions['end']
    res = cur.execute (expr)
    awards['DXCC_' + band] = {'Contacts':res.fetchone()[0], 'Required':100}
    log.info ("      %s - Any Mode" % (band))
    log.info ("        Confirmed (/100) - %s" %(awards['DXCC_' + band]['Contacts']))

def doDXCC_MISSINGQSL():
    global awards


    expr = "SELECT distinct dxcc_country FROM qso_table_v007 where " + conditions['no_maritime'] + " True " + "EXCEPT "
    expr = expr + "SELECT distinct dxcc_country FROM qso_table_v007 where " + conditions['no_maritime'] + conditions['LoTW'] + " True"
    res = cur.execute (expr)
    awards['DXCC_MISSINGQSL'] = res.fetchall()
    log.info ("        %s" %(awards['DXCC_MISSINGQSL']))


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
    awards['CQWPX_'+mode_desc] = {'Contacts':len(combined), 'Required':count}
    log.info ("      %s - Any Band" % (mode_desc))
    log.info ("        Confirmed (/%s) - %s" %(count, len(combined)))

def doCQWPX_BAND(target_band, count, details):
    global awards

    combined = []
    for band,y in details.items(): # key, value
        if band == target_band:
            log.debug (band)
            for mode, prefixes in y.items():
                log.debug (mode)
                #print (prefixes)
                combined = list(set(combined) | set(prefixes))
                #count = count + len(prefixes)
    awards['CQWPX_'+target_band] = {'Contacts':len(combined), 'Required':count}

    log.info ("      %s - Any Mode" % (target_band))
    log.info ("        Confirmed (/%s) - %s" %(count, len(combined)))



def doCQWPX():
    # https://cq-amateur-radio.com/cq_awards/cq_wpx_awards/cq-wpx-award-rules-022017.pdf
    global awards

    details = dict()
    details['160M'] = dict()
    details['80M'] = dict()
    details['40M'] = dict()
    details['30M'] = dict()
    details['20M'] = dict()
    details['17M'] = dict()
    details['15M'] = dict()
    details['12M'] = dict()
    details['10M'] = dict()
    details['6M'] = dict()
    details['2M'] = dict()
    details['70CM'] = dict()
    details['23CM'] = dict()
    details['3CM'] = dict()






    log.info ("      WPX - Any Mode" )
    #expr = conditions['startDXCC'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTW'] +  " band_rx = '" + band + "' and " + conditions['end']
    expr = "select DISTINCT call, band_rx, mode from qso_table_v007 where " + conditions['LoTW'] + "True"
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






awards = {}

log.info ("DXCC: General Conditions")
log.info ("      LoTW or Paper QSL Cards only")
log.info ("      No Maritime Mobile")
log.info ("      No Repeaters - Assuming None")
log.info ("      No Satellite - Assuming none")

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
log.info ("      Satellite Now Permitted - Still not checked")
doDXCC_BAND ("70CM")
doDXCC_BAND ("23CM")
doDXCC_BAND ("12CM")
doDXCC_BAND ("3CM")
doDXCC_MISSINGQSL ()


log.info ("      Satellite - Any Mode, Any Band")
log.info ("      5BDXCC - Any Mode, 100 each on 80M, 40M, 20M, 15M, 10M; then endorceable for 160M, 30M, 17M, 12M, 6M, 2M")
log.info ("        Confirmed (/100)= (%s, %s, %s, %s, %s) then (%s, %s, %s, %s, %s, %s)" % (awards['DXCC_80M']['Contacts'], awards['DXCC_40M']['Contacts'], awards['DXCC_20M']['Contacts'], \
                   awards['DXCC_15M']['Contacts'], awards['DXCC_10M']['Contacts'],  awards['DXCC_160M']['Contacts'], awards['DXCC_30M']['Contacts'], awards['DXCC_17M']['Contacts'], awards['DXCC_12M']['Contacts'], awards['DXCC_6M']['Contacts'], awards['DXCC_2M']['Contacts']))


log.info ("      DXCC Challenge - Any mode. 160M-6M. 1000 Entries")
log.info ("        Confirmed (/1000) - %s" % (awards['DXCC_160M']['Contacts'] + awards['DXCC_80M']['Contacts'] + awards['DXCC_40M']['Contacts'] + awards['DXCC_30M']['Contacts'] + awards['DXCC_20M']['Contacts'] + awards['DXCC_17M']['Contacts'] + awards['DXCC_15M']['Contacts'] + awards['DXCC_12M']['Contacts'] + awards['DXCC_10M']['Contacts'] + awards['DXCC_6M']['Contacts']))
awards['DXCC_CHALLENGE'] = {'Contacts': awards['DXCC_160M']['Contacts'] + awards['DXCC_80M']['Contacts'] + awards['DXCC_40M']['Contacts'] + awards['DXCC_30M']['Contacts'] + awards['DXCC_20M']['Contacts'] + awards['DXCC_17M']['Contacts'] + awards['DXCC_15M']['Contacts'] + awards['DXCC_12M']['Contacts'] + awards['DXCC_10M']['Contacts'] + awards['DXCC_6M']['Contacts'], 'Required': 1000}


log.info ("CQ WAZ: General Conditions")
log.info ("      https://cq-amateur-radio.com/cq_awards/cq_waz_awards/june2022-Final-with-color-break-for-Jose-to-review-Rev-B.pdf")
log.info ("      LoTW, eQSL or Paper QSL Cards only")
log.info ("      No Satellite ")
log.info ("      ***Assuming all eQSL is Authenticity Guarenteed***")
log.info ("      ***Assuming no satellite***")
log.info ("      ***Assuming dates OK***")


doCQWAZ_MIXED ()


log.info ("      SSTV - Any Mode, Any Band")
log.info ("      Satellite - Any Mode, Any Band")
log.info ("      EME - Any Mode, Any Band")

doCQWAZ_MODE ("DATA")
doCQWAZ_MODE ("RTTY")
doCQWAZ_MODE ("CW")
doCQWAZ_MODE ("SSB")
doCQWAZ_MODE ("AM")
doCQWAZ ("160M")
doCQWAZ_BAND ("80M")
doCQWAZ_BAND ("40M")
doCQWAZ_BAND ("30M")
doCQWAZ_BAND ("20M")
doCQWAZ_BAND ("17M")
doCQWAZ_BAND ("15M")
doCQWAZ_BAND ("12M")
doCQWAZ_BAND ("10M")
doCQWAZ ("6M")



log.info ("CQ WPX: General Conditions")
cqwpxDetails = doCQWPX()
doCQWPX_MODE ("Mixed", 400, all_mode, cqwpxDetails )
doCQWPX_MODE ("CW", 300, cw_mode, cqwpxDetails )
doCQWPX_MODE ("SSB", 300, ssb_mode, cqwpxDetails )
doCQWPX_MODE ("Digital", 300, data_mode, cqwpxDetails )

doCQWPX_BAND ("160M", 50, cqwpxDetails)
doCQWPX_BAND ("80M", 175, cqwpxDetails)
doCQWPX_BAND ("160M", 175, cqwpxDetails)
doCQWPX_BAND ("40M", 250, cqwpxDetails)
doCQWPX_BAND ("30M", 250, cqwpxDetails)
doCQWPX_BAND ("20M", 300, cqwpxDetails)
doCQWPX_BAND ("17M", 300, cqwpxDetails)
doCQWPX_BAND ("15M", 300, cqwpxDetails)
doCQWPX_BAND ("12M", 300, cqwpxDetails)
doCQWPX_BAND ("10M", 300, cqwpxDetails)
doCQWPX_BAND ("6M", 250, cqwpxDetails)

log.info ("      North America" )
log.info ("      South America" )
log.info ("      Europe America" )
log.info ("      Africa America" )
log.info ("      Asia America" )
log.info ("      Oceania America" )


# Not contests but interesting information to show
doSTATS_QSL()
doSTATS_BANDS()
doSTATS_MODES()
doSTATS_DXCCBYDATE()



pp.pprint (awards)

#j = json.dumps(awards, indent = 8)
#print (j)