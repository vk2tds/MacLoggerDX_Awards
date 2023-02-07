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
              "startDXCC": "select count (distinct dxcc_country) ",
              "startCQWAZ": "select count (distinct cq_zone) ",
              "startCQWAZ_BAND": "select distinct count(*), mode , band_rx from ( select  count(*) as c, cq_zone, mode, band_rx ",
              "stopCQWAZ_BAND": " group by  cq_zone, mode, band_rx ) group by mode, band_rx",
              "from": "from qso_table_v007  where ",
              "end": "True"}

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
#res = cur.execute ('select count(*) from qso_table_v007')
#print (res.fetchall())


#expr = conditions['startDXCC'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTW'] + conditions['end']
#res = cur.execute (expr)
#print (res.fetchone())


def doCQWAZ_BAND(band):
    global awards

    log.info ("      %s - Per Mode, Any Band" %(band))
    expr = conditions['startCQWAZ_BAND'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTWeQSL'] + " band_rx = '" + band + "' and " + conditions['end'] + conditions['stopCQWAZ_BAND']
    res = cur.execute (expr)
    awards['CQWAZ_' + band] = res.fetchall()
    log.info ("        Confirmed (/40) - %s" %(awards['CQWAZ_' + band]))

def doCQWAZ(band):
    global awards

    log.info ("      %s - Any Mode, Any Band" % (band))
    expr = conditions['startCQWAZ'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTWeQSL'] + " band_rx = '" + band + "' and " + conditions['end']
    res = cur.execute (expr)
    awards['CQWAZ_' + band] = res.fetchone()[0]
    log.info ("        Confirmed (/40) - %s" %(awards['CQWAZ_' + band]))

def doCQWAZ_MODE (mode):
    global awards

    log.info ("      %s - Any Mode, Any Band" % (mode))
    expr = conditions['startCQWAZ'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTWeQSL'] + conditions[mode] + conditions['end']
    res = cur.execute (expr)
    awards['CQWAZ_' + mode] = res.fetchone()[0]
    log.info ("        Confirmed (/40) - %s" %(awards['CQWAZ_' + mode]))

def doDXCC_MODE(mode):
    global awards

    log.info ("      %s - Not Digital, Any Band" % (mode))
    expr = conditions['startDXCC'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTW'] + conditions[mode] + conditions['end']
    res = cur.execute (expr)
    awards['DXCC_' + mode] = res.fetchone()[0]
    log.info ("        Confirmed (/100) - %s" %(awards['DXCC_' + mode]))

def doDXCC_BAND(band):
    global awards

    log.info ("      %s - Any Mode" % (band))
    expr = conditions['startDXCC'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTW'] +  " band_rx = '" + band + "' and " + conditions['end']
    res = cur.execute (expr)
    awards['DXCC_' + band] = res.fetchone()[0]
    log.info ("        Confirmed (/100) - %s" %(awards['DXCC_' + band]))




awards = {}


log.info ("DXCC: General Conditions")
log.info ("      LoTW or Paper QSL Cards only")
log.info ("      No Maritime Mobile")
log.info ("      No Repeaters")
log.info ("      No Satellite ")
log.info ("      Mixed - Any Mode, Any Band")
expr = conditions['startDXCC'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTW'] + conditions['end']
res = cur.execute (expr)
awards['DXCC_MIXED'] = res.fetchone()[0]
log.info ("        Confirmed (/100) - %s" %(awards['DXCC_MIXED']))

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
log.info ("      Satellite Now Permitted")
doDXCC_BAND ("70CM")
doDXCC_BAND ("23CM")
doDXCC_BAND ("12CM")
doDXCC_BAND ("3CM")


log.info ("      Satellite - Any Mode, Any Band")
log.info ("      5BDXCC - Any Mode, 100 each on 80M, 40M, 20M, 15M, 10M; then endorceable for 160M, 30M, 17M, 12M, 6M, 2M")
log.info ("        Confirmed (/100)= (%s, %s, %s, %s, %s) then (%s, %s, %s, %s, %s, %s)" % (awards['DXCC_80M'], awards['DXCC_40M'], awards['DXCC_20M'], \
                   awards['DXCC_15M'], awards['DXCC_10M'],  awards['DXCC_160M'], awards['DXCC_30M'], awards['DXCC_17M'], awards['DXCC_12M'], awards['DXCC_6M'], awards['DXCC_2M']))


log.info ("      DXCC Challenge - Any mode. 160M-6M. 1000 Entries")
log.info ("        Confirmed (/1000) - %s" % (awards['DXCC_160M'] + awards['DXCC_80M'] + awards['DXCC_40M'] + awards['DXCC_30M'] + awards['DXCC_20M'] + awards['DXCC_17M'] + awards['DXCC_15M'] + awards['DXCC_12M'] + awards['DXCC_10M'] + awards['DXCC_6M']))






log.info ("CQ WAZ: General Conditions")
log.info ("      LoTW, eQSL or Paper QSL Cards only")
log.info ("      No Satellite ")
log.info ("      ***Assuming all eQSL is Authenticity Guarenteed***")

log.info ("      Mixed - Any Mode, Any Band")
expr = conditions['startCQWAZ'] + conditions['from'] + conditions['no_maritime'] + conditions['LoTWeQSL'] + conditions['end']
res = cur.execute (expr)
awards['CQWAZ_MIXED'] = res.fetchone()[0]
log.info ("        Confirmed (/40) - %s" %(awards['CQWAZ_MIXED']))

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




pp.pprint (awards)