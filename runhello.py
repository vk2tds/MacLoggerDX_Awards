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


# http://colorbrewer2.org/#type=diverging&scheme=RdBu&n=11
COLORS = ['#e0e0e0', '#f1b6da', '#b8e186', '#92c5de', '#d1e5f0', '#f7f7f7', '#fddbc7', '#f4a582', '#d6604d', '#b2182b', '#67001f']


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        window = uic.loadUi("MainWindow.ui", self)
        self.show()
        self.refreshButton.clicked.connect (self.refreshButtonClicked)

        self.refreshButtonClicked()



    def autoResize(self):
        margins = self.contentsMargins()
        height = self.height()
        width = self.width()

        #self.x()

        #self.tabWidget1.setFixedHeight(height- int((margins.top() + margins.bottom())/2))
        self.tabWidget1.setFixedHeight(height- 50)
        self.tabWidget1.setFixedWidth (width- 50)
        
        self.treeView.setFixedHeight(self.tabWidget1.height()-50)
        self.treeView.setFixedWidth (self.tabWidget1.width()-50)
        self.tableView.setFixedHeight(self.tabWidget1.height()-200)
        self.tableView.setFixedWidth (self.tabWidget1.width()-50)

        self.tableViewLegend.setFixedWidth (self.tabWidget1.width()-50)
        self.tableViewLegend.setFixedHeight(50)


    def refreshButtonClicked (self):
        #print ('ButtonStart')
        macloggerdx_awards.analysis.start()
        hierarchy = macloggerdx_awards.analysis.awards
        rawtable = macloggerdx_awards.analysis.rawtable
        setTreeView (self, hierarchy)
        setTableView(self, rawtable)
        setTableViewLegend(self)
        #print ('ButtonFinish')        



    def resizeEvent(self, event):
        self.autoResize()



class StandardItem (QtGui.QStandardItem):
    def __init__(self, txt='', font_size=12, set_bold=False, color=QtGui.QColor(0, 0, 0)):
        super().__init__()

        fnt = QtGui.QFont('Open Sans', font_size)
        fnt.setBold(set_bold)
        self.setEditable(False)
        self.setForeground(color)
        self.setFont(fnt)
        self.setText(txt)
class StandardItemRed (QtGui.QStandardItem):
    def __init__(self, txt='', font_size=12, set_bold=False, color=QtGui.QColor(255, 0, 0)):
        super().__init__()

        fnt = QtGui.QFont('Open Sans', font_size)
        fnt.setBold(set_bold)
        self.setEditable(False)
        self.setForeground(color)
        self.setFont(fnt)
        self.setText(txt)
class StandardItemGreen (QtGui.QStandardItem):
    def __init__(self, txt='', font_size=12, set_bold=False, color=QtGui.QColor(0, 255, 0)):
        super().__init__()

        fnt = QtGui.QFont('Open Sans', font_size)
        fnt.setBold(set_bold)
        self.setEditable(False)
        self.setForeground(color)
        self.setFont(fnt)
        self.setText(txt)
class StandardItemOrange (QtGui.QStandardItem):
    def __init__(self, txt='', font_size=12, set_bold=False, color=QtGui.QColor(128, 128, 0)):
        super().__init__()

        fnt = QtGui.QFont('Open Sans', font_size)
        fnt.setBold(set_bold)
        self.setEditable(False)
        self.setForeground(color)
        self.setFont(fnt)
        self.setText(txt)



class TableModel(QtCore.QAbstractTableModel):
    def __init__(self, data, hheaders, vheaders):
        super(TableModel, self).__init__()
        self._data = data
        self._hheaders = hheaders
        self._vheaders = vheaders

    def data(self, index, role):
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            # See below for the nested-list data structure.
            # .row() indexes into the outer list,
            # .column() indexes into the sub-list
            value = self._data[index.row()][index.column()]
            if '/' in value:
                (l,c,q) = value.split('/',2)
                return ('%s/%s' %(l,q))
            else:
                    return value
        if role == QtCore.Qt.ItemDataRole.BackgroundRole:
            value = self._data[index.row()][index.column()]
            if value == '-':
                return QtGui.QColor(COLORS[0])
            if '/' in value:
                #print (value)
                (l,c,q) = value.split('/',2)
                if int(c) > 0 and int(l) == 0:
                    #asdfjk
                    return QtGui.QColor(COLORS[4]) # We only have cards
                if int(l) == 0: # Check to see if we have OQRS coming. Or cards sent
                    for qrs in oqrs:
                        if qrs['Country'] == self._vheaders[index.row()]:
                            s = self._hheaders[index.column()]
                            if '\r\n' in s:
                                s = s[:s.index('\r\n')]
                            if qrs['Band'] == s:
                                # if we are OQRS
                                return QtGui.QColor(COLORS[6])                
                    for qrs in tosendoqrs:
                        if qrs['Country'] == self._vheaders[index.row()]:
                            s = self._hheaders[index.column()]
                            if '\r\n' in s:
                                s = s[:s.index('\r\n')]
                            if qrs['Band'] == s:
                                # if we are OQRS
                                return QtGui.QColor(COLORS[8])                
                    for qts in qsltosend:
                        if qts['Country'] == self._vheaders[index.row()]:
                            s = self._hheaders[index.column()]
                            if '\r\n' in s:
                                s = s[:s.index('\r\n')]
                            if qts['Band'] == s:
                                # if we are OQRS
                                return QtGui.QColor(COLORS[3])                

                    for sent in qslsent:
                        if sent['Country'] == self._vheaders[index.row()]:
                            s = self._hheaders[index.column()]
                            if '\r\n' in s:
                                s = s[:s.index('\r\n')]
                            if sent['Band'] == s:
                                # if we are OQRS
                                return QtGui.QColor(COLORS[7])                

                    return QtGui.QColor(COLORS[1]) # no LOTW Confirmations
                return QtGui.QColor(COLORS[2])
        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            value = self._data[index.row()][index.column()]
            if '/' in value:
                (l,c,q) = value.split('/',2)
                if int(c) > 0: # we have some cards
                    ret = '<div style="color:green;">Cards: ' + c + '</div>\r\n'
                    return ret    
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
                    return ret

    def rowCount(self, index):
        # The length of the outer list.
        return len(self._data)

    def columnCount(self, index):
        # The following takes the first sub-list, and returns
        # the length (only works if all rows are an equal length)
        return len(self._data[0])
    

    def headerData(self, section, orientation, role):           # <<<<<<<<<<<<<<< NEW DEF
        # row and column headers
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            if orientation == QtCore.Qt.Orientation.Horizontal:
                return self._hheaders[section] 
            if orientation == QtCore.Qt.Orientation.Vertical:
                return self._vheaders[section]

        return QtCore.QVariant()


class TableModelLegend(QtCore.QAbstractTableModel):
    def __init__(self, data):
        super(TableModelLegend, self).__init__()
        self._data = data
        


    def data(self, index, role):
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            # See below for the nested-list data structure.
            # .row() indexes into the outer list,
            # .column() indexes into the sub-list
            value = self._data[index.row()][index.column()]
            return value
        if role == QtCore.Qt.ItemDataRole.BackgroundRole:
            #value = self._data[index.row()][index.column()]
            return QtGui.QColor(COLORS[index.column()])
            
        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            value = self._data[index.row()][index.column()]

    def rowCount(self, index):
        # The length of the outer list.
        return len(self._data)

    def columnCount(self, index):
        # The following takes the first sub-list, and returns
        # the length (only works if all rows are an equal length)
        return len(self._data[0])
    

    # def headerData(self, section, orientation, role):           # <<<<<<<<<<<<<<< NEW DEF
    #     # row and column headers
    #     if role == QtCore.Qt.ItemDataRole.DisplayRole:
    #         if orientation == QtCore.Qt.Orientation.Horizontal:
    #             return self._hheaders[section] 
    #         if orientation == QtCore.Qt.Orientation.Vertical:
    #             return self._vheaders[section]

    #     return QtCore.QVariant()





def json_tree(tree, parent, dictionary, tag):
    # https://gist.github.com/lukestanley/8525f9fdcb903a43376a35a77575edff
    for key in dictionary:
        if isinstance(dictionary[key], dict):
            me = StandardItem (key)

            if 'Fields' in dictionary[key] and 'Fields_Count' in dictionary[key]:
                el = dictionary[key]
                show = False
                me.appendRow ([QtGui.QStandardItem ('Fields'),QtGui.QStandardItem (str(el['Fields']) + '/' + str(el['Fields_Count']) + ' ' + str(round((int(el['Fields']) / int(el['Fields_Count'])) * 100,2))+ '%') ])
            if 'Grids' in dictionary[key] and 'Grids_Count' in dictionary[key]:
                el = dictionary[key]
                show = False
                me.appendRow ([QtGui.QStandardItem ('Grids'),QtGui.QStandardItem (str(el['Grids']) + '/' + str(el['Grids_Count']) + ' ' + str(round((int(el['Grids']) / int(el['Grids_Count'])) * 100,2))+ '%') ])



            if 'Contacts' in dictionary[key] and 'Required' in dictionary[key]:
                # If the sub-entry from here contains Contacts and Required, then create one and colour it
                details = "%s/%s (%.1f%%)" % (str(dictionary[key]['Contacts']), str(dictionary[key]['Required']),
                                          ((dictionary[key]['Contacts']/dictionary[key]['Required']*100)) )
                c = ''
                if dictionary[key]['Contacts'] >= dictionary[key]['Required']:
                    me.appendRow( [StandardItem('Contacts/Required'), StandardItemGreen(details)])
                    c = 'AWARD-GOOD'
                elif (dictionary[key]['Contacts'] / dictionary[key]['Required']) > 0.75:
                    me.appendRow( [StandardItem('Contacts/Required'), StandardItemOrange(details)])
                    c = 'AWARD-ALMOST'
                else:
                    me.appendRow( [StandardItem('Contacts/Required'), StandardItemRed(details)])
                    c = 'AWARD-NONE'                    

            parent.appendRow (me)
            json_tree (tree, me, dictionary[key], '')



        if isinstance(dictionary[key], list):
            # http://pharma-sas.com/common-manipulation-of-qtreeview-using-pyqt5/

            k = QtGui.QStandardItem (key)
            parent.appendRow (k)

            details = []
            dk = dictionary[key]
            if len(dk) > 0:

                for el in dk:
                    # print ('el', el)
                    if type(el) == dict:
                        # print ('*** DICT ***')
                        show = True
                        if 'DXCC' in el and 'Count' in el:
                            show = False
                            k.appendRow ([QtGui.QStandardItem (str(el['DXCC'])),QtGui.QStandardItem (str(el['Count']))] )

                        for fm in el:
                            if show == False and (fm == 'DXCC' or fm == 'Count'):
                                True
                            else: 
                                #print ('fm', fm, el[fm])                        
                                k.appendRow ([QtGui.QStandardItem ('D' + str(fm)),QtGui.QStandardItem (str(el[fm]))] )
                    elif type(el) == tuple:
                        # print ('*** TUPLE ***')
                        for fm in el:
                            #print ('fm', fm)                        
                            k.appendRow (QtGui.QStandardItem (str(fm)) )
                    elif type(el) == list:
                        # print ('*** LIST ***')
                        for fm in el:
                            k.appendRow ([QtGui.QStandardItem ('L' + str(fm))] )
                    else:
                        print ('el', el, type(el))
                        kdslkdslfkds (1000324)

        else:
            value = dictionary[key]
            # print ('else', key, dictionary[key])
            if type(value) != dict:

                if not key in ('Contacts', 'Required', 'Fields', 'Fields_Count', 'Grids', 'Grids_Count'):
                    parent.appendRow ([QtGui.QStandardItem ('P' + str(key)),QtGui.QStandardItem (str(dictionary[key]))] )

def setTableView (window, rawtable):
    #tv.setModel (TableModel)

    tv = window.tableView
    tv.setModel (None)

    r = rawtable

    staticCols = ['160M', '80M', '40M', '30M', '20M', '17M', '15M', '12M', '10M', '6M']

    newdata = [[0 for x in range(len(staticCols))] for y in range(len(r)-1)] 
    v = OrderedDict()
    hor = []
    ver = []
    j = 0
    lotw_confirmed = 0
    lotw_unconfirmed = 0


    for row in r:
        newRow = []
        if j == 0: # First row only
            i = 0
            for col in row:
                if i != 0: # ignore first column of data
                    v[staticCols[i-1]] = []
                    if '\r\n' in col:
                        (a,b) = col.split('\r\n')
                        if '/' in b:
                            (l,c,q) = b.split('/',2)
                            hor.append ('%s\r\n%s/%s' % (a,l,q))
                        else:
                            hor.append (col)    
    
                    else:
                        hor.append (col)
                i += 1
        else:
            i = 0
            for col in row:
                if i == 0:
                    ver.append (col)
                else: 
                    newdata[j-1][i-1] = col
                    v[staticCols[i-1]].append (col)
                    if '\r\n' in col:
                        (a,b) = col.split('\r\n',1)
                        lotw_unconfirmed += 1
                    else:
                        if col != '-':
                            lotw_confirmed += 1
                i += 1
        j += 1

    # expand later... https://www.pythonguis.com/tutorials/pyqt6-qtableview-modelviews-numpy-pandas/

    #print ('Confirmed', lotw_confirmed, 'total', lotw_confirmed + lotw_unconfirmed)

    window.tabWidget1.setTabText (1, 'DXCC Status - ' + str(lotw_confirmed) + '/' + str(lotw_confirmed + lotw_unconfirmed))


    model = TableModel(newdata, hor, ver)
    tv.setModel(model)


def setTableViewLegend (window):
    #tv.setModel (TableModel)

    tv = window.tableViewLegend
    tv.setModel (None)

    staticCols = ['Blank', 'No QSL', 'LoTW', 'QSL to Send', 'QSL Card', '17M', 'OQRS', 'QSL Sent', 'ToDo OQRS', '6M']

    newdata = [[staticCols[x] for x in range(len(staticCols))] for y in range(1)] 

    model = TableModelLegend(newdata)
    tv.setModel(model)


def setTreeView(window, hierarchy):
    tv = window.treeView

    tv.setModel(None)
    tv.setHeaderHidden(True)

    treeModel = QtGui.QStandardItemModel()
    treeModel.setHorizontalHeaderLabels(['Name', 'Details'])
    rootNode = treeModel.invisibleRootItem()

    awards = StandardItem('Awards')
    json_tree(rootNode, awards, hierarchy, '')
    rootNode.appendRow(awards)

    tv.expandAll()
    tv.setModel(treeModel)
    tv.expandAll()
    tv.resizeColumnToContents(0)







app = QtWidgets.QApplication(sys.argv)
window = MainWindow()

tosendoqrs = [        
         {'Country': 'Angola', 'Band': '20M', 'Call':'D2UY'},
         {'Country': 'Angola', 'Band': '17M', 'Call':'D2UY'},
         {'Country': 'Angola', 'Band': '12M', 'Call':'D2UY'},
         {'Country': 'Viet Nam', 'Band': '10M', 'Call':'XV1X'},
         {'Country': 'Cetuna', 'Band': '15M', 'Call':'EA9PD'},
         {'Country': 'Malawi', 'Band': '15M', 'Call':'7Q7EMH'},
         {'Country': 'Micronesia', 'Band': '15M', 'Call':'V63WJR'}, # Anything september

]


oqrs = [ {'Country': 'South Cook Islands', 'Band': '20M', 'Call':'E51CIK'},
         {'Country': 'South Cook Islands', 'Band': '17M', 'Call':'E51WEG'},
         {'Country': 'Malawi', 'Band': '17M', 'Call':'7Q7EMH'},
         {'Country': 'Malawi', 'Band': '20M', 'Call':'7Q7EMH'},
         {'Country': 'East Malaysia', 'Band': '30M', 'Call':'9M8DEN'},
         {'Country': 'Belarus', 'Band': '30M', 'Call':'EW8W'},
         {'Country': 'Viet Nam', 'Band': '15M', 'Call':'XV1X'},
         {'Country': 'India', 'Band': '10M', 'Call':'VU2GRM'},
         {'Country': 'Viet Nam', 'Band': '30M', 'Call':'3W1T'},
]

qslsent = [ {'Country': 'Costa Rica', 'Band': '10M', 'Call':'TI3NEL', 'When': 'A$5 April 2023'},
            {'Country': 'Moldova' , 'Band': '15M', 'Call':'ER3RE', 'When': 'A$5 April 2023'},
            {'Country': 'Lithuania' , 'Band': '15M', 'Call':'LY3PW', 'When': 'A$5 April 2023'},
            {'Country': 'Czech Republic' , 'Band': '15M', 'Call':'OK1DBE', 'When': '8 May 2023'},
]

qsltosend = [ {'Country': 'Malta', 'Band': '17M', 'Call':'9H1ET', 'Comments': 'x2'},
              {'Country': 'Solomon Islands', 'Band': '40M', 'Call':'H44MS', 'Comments': ''},
              {'Country': 'Gibraltar', 'Band': '15M', 'Call':'ZB2R', 'Comments': ''},  
              {'Country': 'Venezuela', 'Band': '10M', 'Call':'YV5DR', 'Comments': ''},  
              {'Country': 'Crete', 'Band': '15M', 'Call':'SV9MBH', 'Comments': ''},  
              {'Country': 'Guam', 'Band': '40M', 'Call':'KG6JDX', 'Comments': ''},  
              {'Country': 'Guam', 'Band': '12M', 'Call':'KG6JDX', 'Comments': ''},  
              {'Country': 'Luxemburg', 'Band': '30M', 'Call':'LX1JH', 'Comments': ''},  
              {'Country': 'Latvia', 'Band': '12M', 'Call':'YL3CW', 'Comments': ''},  
              {'Country': 'Cyprus', 'Band': '15M', 'Call':'5B4AJG', 'Comments': ''},  
              {'Country': 'Argentina', 'Band': '12M', 'Call':'LU6XQB', 'Comments': 'OQRS Free but via bearu'},  
              {'Country': 'Azores', 'Band': '17M', 'Call':'CU7AA', 'Comments': ''}, 
              {'Country': 'Balearic Islands', 'Band': '17M', 'Call':'EA6SA', 'Comments': ''}, 
              {'Country': 'Balearic Islands', 'Band': '30M', 'Call':'EA6TH', 'Comments': ''}, 
              {'Country': 'Belarus', 'Band': '17M', 'Call':'EU1FQ', 'Comments': ''}, 

            ]



#displayAll(oqrs, qslsent)









app.exec()