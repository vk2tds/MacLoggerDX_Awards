import sys
import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTableWidget, 
    QTableWidgetItem, QDockWidget, QFormLayout, 
    QLineEdit, QWidget, QPushButton, QSpinBox, 
    QMessageBox, QToolBar, QMessageBox,
    QTreeView
)

from PyQt6.QtCore import Qt,QSize, QAbstractTableModel
from PyQt6.QtGui import QIcon, QAction

#https://pythonspot.com/pyqt5-tabs/

from PyQt6.QtWidgets import QMainWindow, QApplication, QPushButton, QWidget, QTabWidget,QVBoxLayout, QTableView, QSizePolicy, QGridLayout
from PyQt6.QtGui import QIcon, QStandardItemModel, QStandardItem, QFont, QColor
from PyQt6.QtCore import pyqtSlot, Qt
from PyQt6 import QtCore
from collections import OrderedDict
import uuid
import pprint 
from dateutil import parser
import datetime


#from PyQt6.QtWidgets import *
#from PyQt6.QtGui import *
#from PyQt6.QtCore import *



#sudo pip3 install python-dateutil

import macloggerdx_awards



hierarchy = macloggerdx_awards.awards
rawtable = macloggerdx_awards.rawtable


class MainWindow(QMainWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowTitle('Employees')
        self.setWindowIcon(QIcon('./assets/usergroup.png'))
        self.setGeometry(100, 100, 600, 400)



        self.table_widget = MyTableWidget(self)
        self.setCentralWidget(self.table_widget)
        
        self.show()

# http://colorbrewer2.org/#type=diverging&scheme=RdBu&n=11
COLORS = ['#e0e0e0', '#f1b6da', '#b8e186', '#92c5de', '#d1e5f0', '#f7f7f7', '#fddbc7', '#f4a582', '#d6604d', '#b2182b', '#67001f']

class TableModel(QAbstractTableModel):
    def __init__(self, data):
        super(TableModel, self).__init__()
        self._data = data

    def data(self, index, role):
        if role == Qt.ItemDataRole.DisplayRole:
            # See below for the nested-list data structure.
            # .row() indexes into the outer list,
            # .column() indexes into the sub-list
            return self._data[index.row()][index.column()]
        if role == Qt.ItemDataRole.BackgroundRole:
            value = self._data[index.row()][index.column()]
            if value == '-':
                return QColor(COLORS[0])
            if '/' in value:
                (a,b) = value.split('/',1)
                if a == '0':
                    return QColor(COLORS[1])
                return QColor(COLORS[2])
        if role == Qt.ItemDataRole.ToolTipRole:
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





class MyTableWidget(QWidget):
    
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        
        # Initialize tab screen
        self.tabs = QTabWidget()
        self.tab2 = QWidget()
        self.tab3 = QWidget()

        self.tabs.resize(300,200)
        
        # Add tabs
        self.tabs.addTab(self.tab2,"Tab 2")
        self.tabs.addTab(self.tab3,"Tab 3")


        
        # Add tabs to widget
        self.layout.addWidget(self.tabs)
        self.setLayout(self.layout)



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

        self.table = QTableView()
        self.model = TableModel(newdata)
        self.model.setHeaderData (1, Qt.Orientation.Horizontal, 'AAA')
        self.model.setHeaderData (2, Qt.Orientation.Horizontal, 'BBB')
        self.model.setHeaderData (2, Qt.Orientation.Vertical, 'CCC')
        self.table.setModel(self.model)
        self.table.setParent (self.tab2)
        self.table.resize (1000,800)


        self.tab2.myLayout = QGridLayout()
        self.tab2.myLayout.addWidget (self.table)



        # table = TableView(v, len(v['Country']), len(v))
        # table.setParent (self.tab2)
        # #table.resize(table.sizeHint());
        # table.show()

        # layout = QVBoxLayout()
        # layout.addWidget(table)
        # self.tab2.setLayout(layout)



        treeView = QTreeView()
        treeView.setHeaderHidden(True)



        treeModel = QStandardItemModel()
        treeModel.setHorizontalHeaderLabels(['Name', 'Details'])
        rootNode = treeModel.invisibleRootItem()

        awards = StandardItem('Awards')
        json_tree(rootNode, awards, hierarchy, '')
        rootNode.appendRow(awards)


        treeView.expandAll()
        treeView.setParent (self.tab3)
        treeView.setModel(treeModel)
        treeView.expandAll()
        treeView.resizeColumnToContents(0)

        # Create first tab
        self.tab3.layout = QVBoxLayout(self)
        self.tab3.setLayout(self.tab3.layout)





def json_tree(tree, parent, dictionary, tag):
    # https://gist.github.com/lukestanley/8525f9fdcb903a43376a35a77575edff
    for key in dictionary:
        if isinstance(dictionary[key], dict):
            me = StandardItem (key)

            if 'Fields' in dictionary[key] and 'Fields_Count' in dictionary[key]:
                el = dictionary[key]
                show = False
                me.appendRow ([QStandardItem ('Fields'),QStandardItem (str(el['Fields']) + '/' + str(el['Fields_Count']) + ' ' + str(round((int(el['Fields']) / int(el['Fields_Count'])) * 100,2))+ '%') ])
            if 'Grids' in dictionary[key] and 'Grids_Count' in dictionary[key]:
                el = dictionary[key]
                show = False
                me.appendRow ([QStandardItem ('Grids'),QStandardItem (str(el['Grids']) + '/' + str(el['Grids_Count']) + ' ' + str(round((int(el['Grids']) / int(el['Grids_Count'])) * 100,2))+ '%') ])



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

            k = QStandardItem (key)
            parent.appendRow (k)

            details = []
            dk = dictionary[key]
            if len(dk) > 0:
                # print (type(dk))
                # print (dk)
                # print (type(dk[0]))
                # print (dk[0])

                for el in dk:
                    # print ('el', el)
                    if type(el) == dict:
                        print ('*** DICT ***')
                        show = True
                        if 'DXCC' in el and 'Count' in el:
                            show = False
                            k.appendRow ([QStandardItem (str(el['DXCC'])),QStandardItem (str(el['Count']))] )

                        for fm in el:
                            if show == False and (fm == 'DXCC' or fm == 'Count'):
                                True
                            else: 
                                #print ('fm', fm, el[fm])                        
                                k.appendRow ([QStandardItem ('D' + str(fm)),QStandardItem (str(el[fm]))] )
                    elif type(el) == tuple:
                        print ('*** TUPLE ***')
                        for fm in el:
                            #print ('fm', fm)                        
                            k.appendRow (QStandardItem (str(fm)) )
                    elif type(el) == list:
                        print ('*** LIST ***')
                        for fm in el:
                            #print (fm)
                            #print ('fm', fm)                        
                            k.appendRow ([QStandardItem ('L' + str(fm))] )
                            #if len(fm) > 1:
                            #     details.append (QStandardItem (fm[1]))
                    else:
                        print ('el', el, type(el))
                        kdslkdslfkds (1000324)

        else:
            value = dictionary[key]
            # print ('else', key, dictionary[key])
            if type(value) != dict:

                if not key in ('Contacts', 'Required', 'Fields', 'Fields_Count', 'Grids', 'Grids_Count'):
                    parent.appendRow ([QStandardItem ('P' + str(key)),QStandardItem (str(dictionary[key]))] )

            


class StandardItem (QStandardItem):
    def __init__(self, txt='', font_size=12, set_bold=False, color=QColor(0, 0, 0)):
        super().__init__()

        fnt = QFont('Open Sans', font_size)
        fnt.setBold(set_bold)

        self.setEditable(False)
        self.setForeground(color)
        self.setFont(fnt)
        self.setText(txt)

class StandardItemRed (QStandardItem):
    def __init__(self, txt='', font_size=12, set_bold=False, color=QColor(255, 0, 0)):
        super().__init__()

        fnt = QFont('Open Sans', font_size)
        fnt.setBold(set_bold)

        self.setEditable(False)
        self.setForeground(color)
        self.setFont(fnt)
        self.setText(txt)
class StandardItemGreen (QStandardItem):
    def __init__(self, txt='', font_size=12, set_bold=False, color=QColor(0, 255, 0)):
        super().__init__()

        fnt = QFont('Open Sans', font_size)
        fnt.setBold(set_bold)

        self.setEditable(False)
        self.setForeground(color)
        self.setFont(fnt)
        self.setText(txt)
class StandardItemOrange (QStandardItem):
    def __init__(self, txt='', font_size=12, set_bold=False, color=QColor(0, 0, 255)):
        super().__init__()

        fnt = QFont('Open Sans', font_size)
        fnt.setBold(set_bold)

        self.setEditable(False)
        self.setForeground(color)
        self.setFont(fnt)
        self.setText(txt)


class TableView(QTableWidget):
    # https://pythonbasics.org/pyqt-table/
    def __init__(self, data, *args):
        QTableWidget.__init__(self, *args)
        self.data = data
        self.setData()
        self.resizeColumnsToContents()
        self.resizeRowsToContents()
 
    def setData(self): 
        horHeaders = []
        for n, key in enumerate(self.data.keys()):
            horHeaders.append(key)
            for m, item in enumerate(self.data[key]):
                newitem = QTableWidgetItem(item)
                self.setItem(m, n, newitem)
        self.setHorizontalHeaderLabels(horHeaders)



if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())