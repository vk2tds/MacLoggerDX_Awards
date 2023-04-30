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
hierarchy = macloggerdx_awards.awards
rawtable = macloggerdx_awards.rawtable


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        window = uic.loadUi("MainWindow.ui", self)
        self.show()

    def autoResize(self):
        #self.document().setTextWidth(self.viewport().width())
        margins = self.contentsMargins()
        #height = int(self.document().size().height() + margins.top() + margins.bottom())
        height = self.height()
        width = self.width()
        #self.setFixedHeight(height)
        print (height)

        self.tabWidget1.setFixedHeight(height-50)
        self.tabWidget1.setFixedWidth (width-50)
        self.treeView.setFixedHeight(self.tabWidget1.height()-50)
        self.treeView.setFixedWidth (self.tabWidget1.width()-50)
        self.tableView.setFixedHeight(self.tabWidget1.height()-50)
        self.tableView.setFixedWidth (self.tabWidget1.width()-50)

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
    def __init__(self, txt='', font_size=12, set_bold=False, color=QtGui.QColor(0, 255, 0)):
        super().__init__()

        fnt = QtGui.QFont('Open Sans', font_size)
        fnt.setBold(set_bold)
        self.setEditable(False)
        self.setForeground(color)
        self.setFont(fnt)
        self.setText(txt)



class TableModel(QtCore.QAbstractTableModel):
    def __init__(self, data):
        super(TableModel, self).__init__()
        self._data = data

    def data(self, index, role):
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            # See below for the nested-list data structure.
            # .row() indexes into the outer list,
            # .column() indexes into the sub-list
            return self._data[index.row()][index.column()]
        if role == QtCore.Qt.ItemDataRole.BackgroundRole:
            value = self._data[index.row()][index.column()]
            if value == '-':
                return QtGui.QColor(COLORS[0])
            if '/' in value:
                (a,b) = value.split('/',1)
                if a == '0':
                    return QtGui.QColor(COLORS[1])
                return QtGui.QColor(COLORS[2])
        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            value = self._data[index.row()][index.column()]
            if '/' in value:
                (a,b) = value.split('/',1)
                if a == '0':
                    ret = ''
                    for line in value.split('\r\n'):
                        if ',' in line:
                            #ret += line + '\r\n'
                            (call, when, lhen) = line.split(',',2)
                            print (len(when))
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
                            print (ret)
                    return ret

    def rowCount(self, index):
        # The length of the outer list.
        return len(self._data)

    def columnCount(self, index):
        # The following takes the first sub-list, and returns
        # the length (only works if all rows are an equal length)
        return len(self._data[0])





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
                        print ('*** DICT ***')
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
                        print ('*** TUPLE ***')
                        for fm in el:
                            #print ('fm', fm)                        
                            k.appendRow (QtGui.QStandardItem (str(fm)) )
                    elif type(el) == list:
                        print ('*** LIST ***')
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



def setTableView (tv):
    #tv.setModel (TableModel)



    r = rawtable

    staticCols = ['Country', '160M', '80M', '40M', '30M', '20M', '17M', '15M', '12M', '10M', '6M']

    newdata = [[0 for x in range(len(staticCols))] for y in range(len(r))] 
    v = OrderedDict()
    j = 0
    for row in r:
        i = 0
        newRow = []
        for col in row:
            newdata[j][i] = col
            if j == 0:
                v[staticCols[i]] = []
            c = col
            if j == 0:
                if '\r\n' in c:
                    (a,b) = c.split('\r\n')
                    c = b
            v[staticCols[i]].append (c)
            i += 1
        j += 1

    # expand later... https://www.pythonguis.com/tutorials/pyqt6-qtableview-modelviews-numpy-pandas/

    model = TableModel(newdata)
    model.setHeaderData (1, QtCore.Qt.Orientation.Horizontal, 'AAA')
    model.setHeaderData (2, QtCore.Qt.Orientation.Horizontal, 'BBB')
    model.setHeaderData (2, QtCore.Qt.Orientation.Vertical, 'CCC')
    tv.setModel(model)

def setTreeView(tv):
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


setTreeView (window.treeView)
setTableView(window.tableView)


app.exec()