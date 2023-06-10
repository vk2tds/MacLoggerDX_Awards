#!/opt/local/bin/python3

# This code was developed for MacOS but should work under Windows and Linux

# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public 
# License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty 
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
# You should have received a copy of the GNU General Public License along with this program. If not, 
# see <https://www.gnu.org/licenses/>.

# Having said that, it would be great to know if this software gets used. If you want, buy me a coffee, or send me some hardware
# Darryl Smith, VK2TDS. darryl@radio-active.net.au Copyright 2023

#https://nitratine.net/blog/post/how-to-import-a-pyqt5-ui-file-in-a-python-gui/


from PyQt6 import uic
from PyQt6 import QtWidgets, uic
from PyQt6 import QtGui, QtCore, QtWidgets
from PyQt6.QtWidgets import QMainWindow, QApplication, QPushButton, QWidget, QTabWidget,QVBoxLayout, QTableView, QSizePolicy, QGridLayout
import sys

import macloggerdx_awards
from collections import OrderedDict
from dateutil import parser
import datetime




# class MainWindow(QtWidgets.QMainWindow):
#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)
#         window = uic.loadUi("MainWindow.ui", self)
#         self.show()
#         self.refreshButton.clicked.connect (self.refreshButtonClicked)

#         self.refreshButtonClicked()





#     def refreshButtonClicked (self):
#         #print ('ButtonStart')
#         macloggerdx_awards.analysis.start()
#         hierarchy = macloggerdx_awards.analysis.awards
#         #setTreeView (self, hierarchy)
#         rawtable = macloggerdx_awards.analysis.rawtable
#         setTableView(self, rawtable)
#         setTableViewLegend(self)
#         #print ('ButtonFinish')        



# class StandardItem (QtGui.QStandardItem):
#     def __init__(self, txt='', font_size=12, set_bold=False, color=QtGui.QColor(0, 0, 0)):
#         super().__init__()

#         fnt = QtGui.QFont('Open Sans', font_size)
#         fnt.setBold(set_bold)
#         self.setEditable(False)
#         self.setForeground(color)
#         self.setFont(fnt)
#         self.setText(txt)
# class StandardItemRed (QtGui.QStandardItem):
#     def __init__(self, txt='', font_size=12, set_bold=False, color=QtGui.QColor(255, 0, 0)):
#         super().__init__()

#         fnt = QtGui.QFont('Open Sans', font_size)
#         fnt.setBold(set_bold)
#         self.setEditable(False)
#         self.setForeground(color)
#         self.setFont(fnt)
#         self.setText(txt)
# class StandardItemGreen (QtGui.QStandardItem):
#     def __init__(self, txt='', font_size=12, set_bold=False, color=QtGui.QColor(0, 255, 0)):
#         super().__init__()

#         fnt = QtGui.QFont('Open Sans', font_size)
#         fnt.setBold(set_bold)
#         self.setEditable(False)
#         self.setForeground(color)
#         self.setFont(fnt)
#         self.setText(txt)
# class StandardItemOrange (QtGui.QStandardItem):
#     def __init__(self, txt='', font_size=12, set_bold=False, color=QtGui.QColor(128, 128, 0)):
#         super().__init__()

#         fnt = QtGui.QFont('Open Sans', font_size)
#         fnt.setBold(set_bold)
#         self.setEditable(False)
#         self.setForeground(color)
#         self.setFont(fnt)
#         self.setText(txt)



# class TableModel(QtCore.QAbstractTableModel):
#     def __init__(self, data, hheaders, vheaders):
#         super(TableModel, self).__init__()
#         self._data = data
#         self._hheaders = hheaders
#         self._vheaders = vheaders



#     def rowCount(self, index):
#         # The length of the outer list.
#         return len(self._data)

#     def columnCount(self, index):
#         # The following takes the first sub-list, and returns
#         # the length (only works if all rows are an equal length)
#         return len(self._data[0])
    

#     def headerData(self, section, orientation, role):           # <<<<<<<<<<<<<<< NEW DEF
#         # row and column headers
#         if role == QtCore.Qt.ItemDataRole.DisplayRole:
#             if orientation == QtCore.Qt.Orientation.Horizontal:
#                 return self._hheaders[section] 
#             if orientation == QtCore.Qt.Orientation.Vertical:
#                 return self._vheaders[section]

#         return QtCore.QVariant()


# class TableModelLegend(QtCore.QAbstractTableModel):
#     def __init__(self, data):
#         super(TableModelLegend, self).__init__()
#         self._data = data
        


#     def data(self, index, role):
#         if role == QtCore.Qt.ItemDataRole.DisplayRole:
#             # See below for the nested-list data structure.
#             # .row() indexes into the outer list,
#             # .column() indexes into the sub-list
#             value = self._data[index.row()][index.column()]
#             return value
#         if role == QtCore.Qt.ItemDataRole.BackgroundRole:
#             #value = self._data[index.row()][index.column()]
#             return QtGui.QColor(COLORS[index.column()])
            
#         if role == QtCore.Qt.ItemDataRole.ToolTipRole:
#             value = self._data[index.row()][index.column()]

#     def rowCount(self, index):
#         # The length of the outer list.
#         return len(self._data)

#     def columnCount(self, index):
#         # The following takes the first sub-list, and returns
#         # the length (only works if all rows are an equal length)
#         return len(self._data[0])
    


# def json_tree(tree, parent, dictionary, tag):
#     # https://gist.github.com/lukestanley/8525f9fdcb903a43376a35a77575edff
#     for key in dictionary:
#         if isinstance(dictionary[key], dict):
#             me = StandardItem (key)

#             if 'Fields' in dictionary[key] and 'Fields_Count' in dictionary[key]:
#                 el = dictionary[key]
#                 show = False
#                 me.appendRow ([QtGui.QStandardItem ('Fields'),QtGui.QStandardItem (str(el['Fields']) + '/' + str(el['Fields_Count']) + ' ' + str(round((int(el['Fields']) / int(el['Fields_Count'])) * 100,2))+ '%') ])
#             if 'Grids' in dictionary[key] and 'Grids_Count' in dictionary[key]:
#                 el = dictionary[key]
#                 show = False
#                 me.appendRow ([QtGui.QStandardItem ('Grids'),QtGui.QStandardItem (str(el['Grids']) + '/' + str(el['Grids_Count']) + ' ' + str(round((int(el['Grids']) / int(el['Grids_Count'])) * 100,2))+ '%') ])



#             if 'Contacts' in dictionary[key] and 'Required' in dictionary[key]:
#                 # If the sub-entry from here contains Contacts and Required, then create one and colour it
#                 details = "%s/%s (%.1f%%)" % (str(dictionary[key]['Contacts']), str(dictionary[key]['Required']),
#                                           ((dictionary[key]['Contacts']/dictionary[key]['Required']*100)) )
#                 c = ''
#                 if dictionary[key]['Contacts'] >= dictionary[key]['Required']:
#                     me.appendRow( [StandardItem('Contacts/Required'), StandardItemGreen(details)])
#                     c = 'AWARD-GOOD'
#                 elif (dictionary[key]['Contacts'] / dictionary[key]['Required']) > 0.75:
#                     me.appendRow( [StandardItem('Contacts/Required'), StandardItemOrange(details)])
#                     c = 'AWARD-ALMOST'
#                 else:
#                     me.appendRow( [StandardItem('Contacts/Required'), StandardItemRed(details)])
#                     c = 'AWARD-NONE'                    

#             parent.appendRow (me)
#             json_tree (tree, me, dictionary[key], '')



#         if isinstance(dictionary[key], list):
#             # http://pharma-sas.com/common-manipulation-of-qtreeview-using-pyqt5/

#             k = QtGui.QStandardItem (key)
#             parent.appendRow (k)

#             details = []
#             dk = dictionary[key]
#             if len(dk) > 0:

#                 for el in dk:
#                     # print ('el', el)
#                     if type(el) == dict:
#                         # print ('*** DICT ***')
#                         show = True
#                         if 'DXCC' in el and 'Count' in el:
#                             show = False
#                             k.appendRow ([QtGui.QStandardItem (str(el['DXCC'])),QtGui.QStandardItem (str(el['Count']))] )

#                         for fm in el:
#                             if show == False and (fm == 'DXCC' or fm == 'Count'):
#                                 True
#                             else: 
#                                 #print ('fm', fm, el[fm])                        
#                                 k.appendRow ([QtGui.QStandardItem ('D' + str(fm)),QtGui.QStandardItem (str(el[fm]))] )
#                     elif type(el) == tuple:
#                         # print ('*** TUPLE ***')
#                         for fm in el:
#                             #print ('fm', fm)                        
#                             k.appendRow (QtGui.QStandardItem (str(fm)) )
#                     elif type(el) == list:
#                         # print ('*** LIST ***')
#                         for fm in el:
#                             k.appendRow ([QtGui.QStandardItem ('L' + str(fm))] )
#                     else:
#                         print ('el', el, type(el))
#                         kdslkdslfkds (1000324)

#         else:
#             value = dictionary[key]
#             # print ('else', key, dictionary[key])
#             if type(value) != dict:

#                 if not key in ('Contacts', 'Required', 'Fields', 'Fields_Count', 'Grids', 'Grids_Count'):
#                     parent.appendRow ([QtGui.QStandardItem ('P' + str(key)),QtGui.QStandardItem (str(dictionary[key]))] )





# def setTreeView(window, hierarchy):
#     tv = window.treeView

#     tv.setModel(None)
#     tv.setHeaderHidden(True)

#     treeModel = QtGui.QStandardItemModel()
#     treeModel.setHorizontalHeaderLabels(['Name', 'Details'])
#     rootNode = treeModel.invisibleRootItem()

#     awards = StandardItem('Awards')
#     json_tree(rootNode, awards, hierarchy, '')
#     rootNode.appendRow(awards)

#     tv.expandAll()
#     tv.setModel(treeModel)
#     tv.expandAll()
#     tv.resizeColumnToContents(0)



def getKey(vals):
    html = ''
    html += '<table>'
    html += '<tr>'
    html += '<td bgcolor = ' + bgColors.Null.value+ '>Blank</td>'
    html += '<td bgcolor = ' + bgColors.Lotw.value+ '>LoTW</td>'
    html += '<td bgcolor = ' + bgColors.QslNone.value+ '>No QSL</td>'
    html += '<td bgcolor = ' + bgColors.QslOutbox.value+ '>QSL Outbox</td>'
    html += '<td bgcolor = ' + bgColors.QslCard.value+ '>Have Card</td>'
    html += '<td bgcolor = ' + bgColors.QslSent.value+ '>QSL Sent</td>'
    html += '<td bgcolor = ' + bgColors.BureauSent.value+ '>Bureau Send</td>'
    html += '<td bgcolor = ' + bgColors.BureauOutbox.value+ '>Bureau Outbox</td>'
    html += '<td bgcolor = ' + bgColors.OqrsSent.value+ '>OQRS Sent</td>'
    html += '<td bgcolor = ' + bgColors.OqrsOutbox.value+ '>OQRS Outbox</td>'
    html += '</tr>'
    html += '<tr>'
    html += '<td>' + str(vals['Null']) + '</td>'
    html += '<td>' + str(vals['Lotw']) + '</td>'
    html += '<td>' + str(vals['QslNone']) + '</td>'
    html += '<td>' + str(vals['QslOutbox']) + '</td>'
    html += '<td>' + str(vals['QslCard']) + '</td>'
    html += '<td>' + str(vals['QslSent']) + '</td>'
    html += '<td>' + str(vals['BureauSent']) + '</td>'
    html += '<td>' + str(vals['BureauOutbox']) + '</td>'
    html += '<td>' + str(vals['OqrsSent']) + '</td>'
    html += '<td>' + str(vals['OqrsOutbox']) + '</td>'
    html += '</tr>'

    html += '</table>'

    return html

#app = QtWidgets.QApplication(sys.argv)
#window = MainWindow()




details = [
    ['OQRS','Sent', 'Marshall Islands', '15M', 'V7/N7XR', ''],
    ['OQRS','Sent', 'Marshall Islands', '17M', 'V7/N7XR', ''],
    #['OQRS','Outbox', 'Viet Nam', '10M', 'XV1X', ''],
    
    ['OQRS','Sent', 'Malawi', '15M', '7Q7EMH', ''],
    ['OQRS','Outbox', 'Micronesia', '15M', 'V63WJR', 'Anything September'],
    ['OQRS','Sent', 'Malawi', '20M', '7Q7EMH', ''],
    ['OQRS','Sent', 'Belarus', '12M', 'EW8W', ''],
    ['OQRS','Sent', 'Belarus', '30M', 'EW8W', ''],
    ['OQRS','Sent', 'Viet Nam', '15M', 'XV1X', ''],
    ['OQRS','Sent', 'Viet Nam', '30M', '3W1T', ''],
    ['OQRS','Sent', 'North Cook Islands', '17M', 'E51WL', '4/jun/2023'],
    ['OQRS','Sent', 'India', '10M', 'VU2GRM', ''],
  


    ['QSL','Outbox', 'Malta', '17M', '9H1ET', 'x2'],
    ['QSL','Outbox', 'Solomon Islands', '40M', 'H44MS', ''],
    ['QSL','Outbox', 'Gibraltar', '15M', 'ZB2R', 'Direct only'],
    ['QSL','Outbox', 'Venezuela', '10M', 'YV5DR', ''],

    ['QSL','Outbox', 'Latvia', '12M', 'YL3CW', ''],
    ['QSL','Outbox', 'Cyprus', '15M', '5B4AJG', ''],
    ['QSL','Outbox', 'Ceuta & Melilla', '15M', 'EA9PD', 'US$3 - emailed about LoTW'],
    ['QSL','Outbox', 'Brunei Darussalam', '15M', 'V85T', ''],
    ['QSL','Outbox', 'Azores', '17M', 'CU7AA', ''],
    ['QSL','Outbox', 'Balearic Islands', '17M', 'EA6SA', ''],
    ['QSL','Outbox', 'Venezuela', '12M', 'YV2AVT', ''],
    ['QSL','Outbox', 'Lithuania', '17M', 'LY3BES', ''],  

    ['QSL','Sent', 'Moldova', '15M', 'ER3RE', 'A$5 April 2023'],
    ['QSL','Sent', 'Lithuania', '15M', 'LY3PW', 'A$5 April 2023'],
    ['QSL','Sent', 'Czech Republic', '15M', 'OK1DBE', '8 May 2023'],

    ['Bureau','Outbox', 'Turkey', '15M', 'TC100YEAR', ''],
    ['Bureau','Outbox', 'Balearic Islands', '30M', 'EA6TH', ''],
    ['Bureau','Outbox', 'Azores', '17M', 'CU7AA', ''],
    ['Bureau','Outbox', 'Croatia', '30M', '9A1CCB', 'Radio Club'],
    ['Bureau','Outbox', 'Latvia', '12M', 'YL3CW', ''],
    ['Bureau','Outbox', 'Slovak Republic', '20M', 'OM3CND', ''],
    ['Bureau','Outbox', 'Luxembourg', '30M', 'LX1JH', ''],
    ['Bureau','Outbox', 'Netherlands', '15M', 'PA3ATZ', ''],
    ['Bureau','Outbox', 'Venezuela', '10M', 'YV5DR', ''],
    ['Bureau','Sent', 'Argentina', '12M', 'LU6XQB', 'Via OQRS'],

    # West Malaysia - 30M - 9M2EGE - Direct
    # Slovak Republic - 20M - OM3CND 
    # Portugal - 20M - CT2GSW
    # Netherlands - 15M - PA3ATZ
    #['Bureau','Outbox', 'Belarus', '17M', 'EU1FQ', ''],
    #['Bureau','Outbox', 'Balearic Islands', '15M', 'EA6TH', ''],
    # France 12M F4BKV OQRS? Needs to upload to ClubLog
    #['OQRS','Sent', 'South Africa', '20M', 'VU2GRM', 'ZS6WN'],
    #['OQRS','Sent', 'South Cook Islands', '20M', 'E51CIK', ''],
    #['OQRS','Sent', 'East Malaysia', '30M', '9M8DEN', ''],
    #['OQRS','Sent', 'South Cook Islands', '17M', 'E51WEG', ''],
    #['QSL','Outbox', 'Estonia', '20M', 'ES4IN', ''],
    #['QSL','Outbox', 'Cuba', '12M', 'CO8LY', 'Emailed and waiting for him to add to LoTW'],
    #['QSL','Outbox', 'Belarus', '17M', 'EU1FQ', ''],
    #['QSL','Sent', 'Costa Rica', '10M', 'TI3NEL', 'A$5 April 2023'],
    # ['OQRS','Sent', 'Central Kiribati', '15M', 'T31TT', '2/jun/2023'],
    # ['OQRS','Sent', 'Central Kiribati', '17M', 'T31TT', '2/jun/2023'],
    # ['OQRS','Sent', 'Central Kiribati', '20M', 'T31TT', '2/jun/2023'],
    # ['OQRS','Sent', 'Central Kiribati', '40M', 'T31TT', '8/jun/2023'],
    # ['OQRS','Sent', 'Central Kiribati', '12M', 'T31TT', '8/jun/2023'],
    # ['OQRS','Sent', 'Central Kiribati', '30M', 'T31TT', '8/jun/2023'],




]    




#displayAll(oqrs, qslsent)


#app.exec()



# http://colorbrewer2.org/#type=diverging&scheme=RdBu&n=11
# COLORS = ['#e0e0e0', '#f1b6da', '#b8e186', '#92c5de', '#d1e5f0', '#f7f7f7', '#fddbc7', '#f4a582', '#d6604d', '#b2182b', '#67001f']


from enum import Enum

class bgColors (Enum):
    BureauSent = '#f7f7f7'
    BureauOutbox = '#b2182b'
    OqrsSent = '#fddbc7'
    OqrsOutbox = '#d6604d'
    QslSent = '#f4a582'
    QslOutbox = '#92c5de'
    QslNone = '#f1b6da'
    QslCard = '#d1e5f0'
    Null = '#e0e0e0'
    Lotw = '#b8e186'



def challengeTableCell(value, country, band):
    roleText = ''
    roleToolTip = ''
    roleBackground = ''

    # roleText
    v = ''
    if '\r\n' in value:
        #print ('value', value)
        x = value.split ('\r\n')
        v = x[0]
    else:
        v = value  

    if '/' in v:
        (l,c,q) = v.split('/',2)
        roleText = ('%s/%s' %(l,q))
    else:
        roleText = ''
        



    # roleBackground
    if value == '-':
        roleBackground =  bgColors.Null
    if '/' in value:
        #print (value)
        (l,c,q) = value.split('/',2) # lotw, Cards, QSOs
        if int(c) > 0 and int(l) == 0:
            roleBackground = bgColors.QslCard # We only have cards
        elif int(l) == 0: # Check to see if we have OQRS coming. Or cards sent
            for dType, dSubtype, dCountry, dBand, dCallsign, dComments in details:
                if dCountry == country:
                    if dBand == band:
                        # s = self._hheaders[index.column()]
                        # if '\r\n' in s:
                        #     s = s[:s.index('\r\n')]
                        # if dBand == s:
                            #print (dBand, s, dType)
                            if dType == 'Bureau':
                                if dSubtype == 'Sent':
                                    roleBackground = bgColors.BureauSent                
                                if dSubtype == 'Outbox':
                                    roleBackground = bgColors.BureauOutbox      
                            if dType == 'OQRS':
                                if dSubtype == 'Sent':
                                    roleBackground =  bgColors.OqrsSent                
                                if dSubtype == 'Outbox':
                                    roleBackground =  bgColors.OqrsOutbox        
                            if dType == 'QSL':
                                if dSubtype == 'Sent':
                                    roleBackground =  bgColors.QslSent      
                                if dSubtype == 'Outbox':
                                    roleBackground =  bgColors.QslOutbox         
            if roleBackground == '':
                roleBackground =  bgColors.QslNone # no LOTW Confirmations
        if roleBackground == '':
            roleBackground =  bgColors.Lotw
        
    # roleToolTip
    if '/' in value:
        (l,c,q) = value.split('/',2)
        if int(c) > 0: # we have some cards
            roleToolTip = '<div style="color:green;">Cards: ' + c + '</div>\r\n'
        if l == '0':
            ret = ''
            for line in value.split('\r\n'):
                if ',' in line:
                    #ret += line + '\r\n'
                    (call, when, lhen) = line.split(',',2)
                    (a,b) = when.split('.',1)
                    wint = int(a)
                    if lhen == '':
                        lint = 'NEVER'
                    else:
                        True
                        lint = lhen
                        #lint = int(lhen)
                    dt = datetime.datetime.fromtimestamp(wint)
                    dtd = datetime.datetime.now() - dt
                    if dtd.days < 14:
                        ret += '<div style="color:green;">' + (('%s: %s %s') % (str(dt), call, str(lint))).replace (' ', '&nbsp;') + '</div>\r\n'
                    elif dtd.days < 28:
                        ret += '<div style="color:orange;">' + (('%s: %s %s') % (str(dt), call, str(lint))).replace (' ', '&nbsp;') + '</div>\r\n'
                    elif dtd.days < 90:
                        ret += '<div style="color:red;">' + (('%s: %s %s') % (str(dt), call, str(lint))).replace (' ', '&nbsp;') + '</div>\r\n'
                    else:
                        ret += '<div style="color:black;">' + (('%s: %s %s') % (str(dt), call, str(lint))).replace (' ', '&nbsp;') + '</div>\r\n'
            roleToolTip = ret

    html = ''
    if roleBackground == '':
        html += '<td>'
    else:
        html += '<td bgcolor=' + roleBackground.value + '>'

    if len(roleToolTip) > 0:
        html += '<div class="tooltip">'
    html += roleText 
    if len(roleToolTip) > 0:
        html += '<span class="tooltiptext">'
        html += roleToolTip
        html += '</span>'
        html += '</div>'
    html += '</td>'
    return html


class dets():
    def __init__(self, details):
        self.details = {}
        i = 0
        for d in details:
            self.details[i] = {'Details': d, 'Processed': False, 'Excess': False}
        
            i += 1
        details

    def remove(self, country, band, html):
        for i in self.details:
            d = self.details[i]['Details']
            # if country[:3] == 'Ceu' and d[2][:3] == 'Ceu':
            #     print (country[:10], d[2][:10])
            #     if (d[2] == country) and (d[3] == band):
            #         print ('Success')
            if (d[2] == country) and (d[3] == band):
                if bgColors.Lotw.value in html:
                    print ('Remove', d)
                    self.details[i]['Processed'] = True
                    self.details[i]['Excess'] = True
                elif bgColors.QslCard.value in html:
                    print ('Remove', d)
                    self.details[i]['Processed'] = True
                    self.details[i]['Excess'] = True
                elif bgColors.OqrsSent.value in html:
                    #print ('Remove', d)
                    self.details[i]['Processed'] = True
                elif bgColors.OqrsOutbox.value in html:
                    #print ('Remove', d)
                    self.details[i]['Processed'] = True
                elif bgColors.BureauOutbox.value in html:
                    #print ('Remove', d)
                    self.details[i]['Processed'] = True
                elif bgColors.BureauSent.value in html:
                    #print ('Remove', d)
                    self.details[i]['Processed'] = True
                elif bgColors.QslOutbox.value in html:
                    #print ('Remove', d)
                    self.details[i]['Processed'] = True
                elif bgColors.QslSent.value in html:
                    #print ('Remove', d)
                    self.details[i]['Processed'] = True
                
                #else:
                #    #print ('Dont remove', d)
                #    self.details[i]['Processed'] = True

    def report (self):
        removeHtml = ''
        removeHtml += '<table>'

        anything = False
        for i in self.details:
            if (self.details[i]['Processed'] != True) or (self.details[i]['Excess'] == True):
                anything = True
                r = self.details[i]['Details']
                #print (r)
                removeHtml += '<tr>'
                removeHtml += '<td>' + r[0] + '</td>' # Type
                removeHtml += '<td>' + r[1] + '</td>' # Subtype
                removeHtml += '<td>' + r[2] + '</td>' # Country
                removeHtml += '<td>' + r[3] + '</td>' # Band
                removeHtml += '<td>' + r[4] + '</td>' # Call
                removeHtml += '<td>' + r[5] + '</td>' # Notes
                removeHtml += '</tr>'
            i += 1
        removeHtml += '</table>'
        removeHtml += '<p>'
        if not anything:
            return ''
        return removeHtml


def challengeTable (r):

    dxccCount = 0
    dxccCountUnconfirmed = 0
    dxccChallengeCountUnconfirmed = 0
    dxccChallengeCount = 0
    dxccCategories = {}


    staticCols = ['160M', '80M', '40M', '30M', '20M', '17M', '15M', '12M', '10M', '6M']

    newdata = [[0 for x in range(len(staticCols))] for y in range(len(r)-1)] 
    v = OrderedDict()
    hor = []
    ver = []
    j = 0
    lotw_confirmed = 0
    lotw_unconfirmed = 0

    workingDetails = details

    myDets = dets(details)

    removeMe = []

    html = 'Remove List<p>'
    html += '<table>'

    for row in r:
        newRow = []
        if j == 0: # First row only
            html += '<th>'
            i = 0
            for col in row:
                if i != 0: # ignore first column of data
                    v[staticCols[i-1]] = []
                    if '\r\n' in col:
                        (a,b) = col.split('\r\n')
                        if '/' in b:
                            (l,c,q) = b.split('/',2)
                            html += '<td>' + ('%s\r\n%s/%s' % (a,l,q)) + '</td>'
                        else:
                            html += '<td>' + col + '</td>'
    
                    else:
                        html += '<td>' + col + '</td>'

                i += 1
            html += '</th>'
        else:
            i = 0
            html += '<tr>'
            country = ''
            hasDxcc = False
            hasDxccUnconfirmed = False
            for col in row:
                if i == 0:
                    country = col
                    html += '<td>' + col + '</td>'
                else:
                    newdata[j-1][i-1] = col
                    v[staticCols[i-1]].append (col)
                    if '\r\n' in col:
                        (a,b) = col.split('\r\n',1)
                        lotw_unconfirmed += 1
                    else:
                        if col != '-':
                            lotw_confirmed += 1
                    if col is None:
                        html += '<td>xxx</td>'
                    else:
                        code = challengeTableCell (col, country, staticCols[i-1])
                        for val in [e for e in bgColors]:
                            if val.value in code:
                                if not val.name in dxccCategories:
                                    dxccCategories[val.name] = 0
                                dxccCategories[val.name] += 1

                        if (bgColors.Lotw.value in code) or (bgColors.QslCard.value in code):
                            hasDxcc = True
                            dxccChallengeCount += 1
                        if not bgColors.Null.value in code:
                            hasDxccUnconfirmed = True
                            dxccChallengeCountUnconfirmed += 1
                        myDets.remove (country, staticCols[i-1], code)
                        html += code
                i += 1
            if hasDxcc:
                dxccCount += 1
            if hasDxccUnconfirmed:
                dxccCountUnconfirmed += 1
            html += '</tr>'
        j += 1


    print ('dxccCount', dxccCount)
    print ('dxccChallengeCount', dxccChallengeCount)
    print ('dxccCategories', dxccCategories)


    html += '</table>'

    Cat = '<p>'
    Cat += getKey(dxccCategories) 
    Cat += '<p>'



    moreHtml = ''
    moreHtml += '<p>'
    moreHtml += '<table>'

    moreHtml += '<tr><td>DXCC Count Confirmed</td>'
    moreHtml += '<td>'
    moreHtml += str(dxccCount)
    moreHtml += '</td></tr>'

    moreHtml += '<tr><td>DXCC Count With Unconfirmed</td>'
    moreHtml += '<td>'
    moreHtml += str(dxccCountUnconfirmed)
    moreHtml += '</td></tr>'

    moreHtml += '<tr><td>DXCC Challenge Count Confirmed</td>'
    moreHtml += '<td>'
    moreHtml += str(dxccChallengeCount)
    moreHtml += '</td></tr>'

    moreHtml += '<tr><td>DXCC Challenge Count With Unconfirmed</td>'
    moreHtml += '<td>'
    moreHtml += str(dxccChallengeCountUnconfirmed)
    moreHtml += '</td></tr>'


    moreHtml += '</table>'
    moreHtml += '<p>'


    
    
    removeHtml = myDets.report()



    return moreHtml + Cat + removeHtml +  html












def startup():
    global rawtable
    global table

    analy = macloggerdx_awards.analysis
    analy.start()
    #macloggerdx_awards.analysis.start()
    #rawtable = macloggerdx_awards.analysis.rawtable

    rawtable = analy.rawtable
    table = challengeTable(rawtable)


startup()

tablestyle = '''table, th, td {
  border: 1px solid black;
  border-collapse: collapse;
}

/* Tooltip container */
.tooltip {
  position: relative;
  display: inline-block;
  border-bottom: 1px dotted black; /* If you want dots under the hoverable text */
}

/* Tooltip text */
.tooltip .tooltiptext {
  visibility: hidden;
  
  background-color: #555;
  color: #fff;
  text-align: center;
  padding: 5px 0;
  border-radius: 6px;

  /* Position the tooltip text */
  position: absolute;
  z-index: 1;
  bottom: 125%;
  left: 50%;
  margin-left: -60px;

  /* Fade in tooltip */
  opacity: 0;
  transition: opacity 0.3s;
}

/* Tooltip arrow */
.tooltip .tooltiptext::after {
  content: "";
  position: absolute;
  top: 100%;
  left: 50%;
  margin-left: -5px;
  border-width: 5px;
  border-style: solid;
  border-color: #555 transparent transparent transparent;
}

/* Show the tooltip text when you mouse over the tooltip container */
.tooltip:hover .tooltiptext {
  visibility: visible;
  opacity: 1;
}



'''


from http.server import HTTPServer, BaseHTTPRequestHandler

class MyHandler(BaseHTTPRequestHandler):
    # https://parsiya.net/blog/2020-11-15-customizing-pythons-simplehttpserver/
    # https://armantutorial.wordpress.com/2022/08/13/how-to-make-a-web-server-in-python/
    def do_GET(self):
        # send 200 response
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        # send response headers
        self.end_headers()
        # send the body of the response


        self.wfile.write(bytes("<html>", "utf-8"))
        self.wfile.write(bytes("<head>", "utf-8"))
        self.wfile.write(bytes("<title></title>", "utf-8"))
        self.wfile.write(bytes("<title></title>", "utf-8"))
        self.wfile.write(bytes("<style>" + tablestyle + "</style>", "utf-8"))
        self.wfile.write(bytes("</head>", "utf-8"))
        self.wfile.write(bytes("<body>", "utf-8"))
        self.wfile.write (bytes(table, "utf-8"))

        self.wfile.write(bytes("</body>", "utf-8"))
        self.wfile.write(bytes("</html>", "utf-8"))

httpd = HTTPServer(('localhost', 10000), MyHandler)
httpd.serve_forever()

