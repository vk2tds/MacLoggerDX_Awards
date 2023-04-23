import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTableWidget, 
    QTableWidgetItem, QDockWidget, QFormLayout, 
    QLineEdit, QWidget, QPushButton, QSpinBox, 
    QMessageBox, QToolBar, QMessageBox,
    QTreeView
)

from PyQt6.QtCore import Qt,QSize
from PyQt6.QtGui import QIcon, QAction

#https://pythonspot.com/pyqt5-tabs/

from PyQt6.QtWidgets import QMainWindow, QApplication, QPushButton, QWidget, QTabWidget,QVBoxLayout
from PyQt6.QtGui import QIcon, QStandardItemModel, QStandardItem, QFont, QColor
from PyQt6.QtCore import pyqtSlot
from collections import OrderedDict
import uuid
import pprint 


import macloggerdx_awards



hierarchy = macloggerdx_awards.awards
print (hierarchy)


class MainWindow(QMainWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowTitle('Employees')
        self.setWindowIcon(QIcon('./assets/usergroup.png'))
        self.setGeometry(100, 100, 600, 400)



        self.table_widget = MyTableWidget(self)
        self.setCentralWidget(self.table_widget)
        
        self.show()



        # self.table = QTableWidget(self)
        # self.setCentralWidget(self.table)

        # self.table.setColumnCount(3)
        # self.table.setColumnWidth(0, 150)
        # self.table.setColumnWidth(1, 150)
        # self.table.setColumnWidth(2, 50)

        # self.table.setHorizontalHeaderLabels(employees[0].keys())
        # self.table.setRowCount(len(employees))

        # row = 0
        # for e in employees:
        #     self.table.setItem(row, 0, QTableWidgetItem(e['First Name']))
        #     self.table.setItem(row, 1, QTableWidgetItem(e['Last Name']))
        #     self.table.setItem(row, 2, QTableWidgetItem(str(e['Age'])))
        #     row += 1

        # dock = QDockWidget('New Employee')
        # dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        # self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

        # # create form
        # form = QWidget()
        # layout = QFormLayout(form)
        # form.setLayout(layout)


        # self.first_name = QLineEdit(form)
        # self.last_name = QLineEdit(form)
        # self.age = QSpinBox(form, minimum=18, maximum=67)
        # self.age.clear()

        # layout.addRow('First Name:', self.first_name)
        # layout.addRow('Last Name:', self.last_name)
        # layout.addRow('Age:', self.age)

        # btn_add = QPushButton('Add')
        # btn_add.clicked.connect(self.add_employee)
        # layout.addRow(btn_add)

        # # add delete & edit button
        # toolbar = QToolBar('main toolbar')
        # toolbar.setIconSize(QSize(16,16))
        # self.addToolBar(toolbar)


        # delete_action = QAction(QIcon('./assets/remove.png'), '&Delete', self)
        # delete_action.triggered.connect(self.delete)
        # toolbar.addAction(delete_action)
        #dock.setWidget(form)





    def delete(self):
        current_row = self.table.currentRow()
        if current_row < 0:
            return QMessageBox.warning(self, 'Warning','Please select a record to delete')

        button = QMessageBox.question(
            self,
            'Confirmation',
            'Are you sure that you want to delete the selected row?',
            QMessageBox.StandardButton.Yes |
            QMessageBox.StandardButton.No
        )
        if button == QMessageBox.StandardButton.Yes:
            self.table.removeRow(current_row)

    def valid(self):
        first_name = self.first_name.text().strip()
        last_name = self.last_name.text().strip()

        
        if not first_name:
            QMessageBox.critical(self, 'Error', 'Please enter the first name')
            self.first_name.setFocus()
            return False

        if not last_name:
            QMessageBox.critical(self, 'Error', 'Please enter the last name')
            self.last_name.setFocus()
            return False

        try:
            age = int(self.age.text().strip())
        except ValueError:
            QMessageBox.critical(self, 'Error', 'Please enter a valid age')
            self.age.setFocus()
            return False

        if age <= 0 or age >= 67:
            QMessageBox.critical(
                self, 'Error', 'The valid age is between 1 and 67')
            return False

        return True

    def reset(self):
        self.first_name.clear()
        self.last_name.clear()
        self.age.clear()

    def add_employee(self):
        if not self.valid():
            return

        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(
            self.first_name.text().strip())
        )
        self.table.setItem(
            row, 1, QTableWidgetItem(self.last_name.text())
        )
        self.table.setItem(
            row, 2, QTableWidgetItem(self.age.text())
        )

        self.reset()


class MyTableWidget(QWidget):
    
    def __init__(self, parent):
        super(QWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        
        # Initialize tab screen
        self.tabs = QTabWidget()
        self.tab1 = QWidget()
        self.tab2 = QWidget()
        self.tab3 = QWidget()

        self.tabs.resize(300,200)
        
        # Add tabs
        self.tabs.addTab(self.tab1,"Tab 1")
        self.tabs.addTab(self.tab2,"Tab 2")
        self.tabs.addTab(self.tab3,"Tab 3")


        # Create first tab
        self.tab1.layout = QVBoxLayout(self)
        self.pushButton1 = QPushButton("PyQt5 button")
        self.tab1.layout.addWidget(self.pushButton1)
        self.tab1.setLayout(self.tab1.layout)
        
        # Add tabs to widget
        self.layout.addWidget(self.tabs)
        self.setLayout(self.layout)
        


        r = hierarchy['ARRL']['DXCC']['RawTable']

        staticCols = ['Country', '160M', '80M', '40M', '30M', '20M', '17M', '15M', '12M', '10M', '6M']

        v = OrderedDict()
        j = 0
        for row in r:
            i = 0
            for col in row:
                if j == 0:
                    v[staticCols[i]] = []
                v[staticCols[i]].append (col)
                i += 1
            j += 1

        table = TableView(v, len(v['Country']), len(v))
        table.setParent (self.tab2)
        #table.resize(table.sizeHint());
        table.show()

        layout = QVBoxLayout()
        layout.addWidget(table)
        self.tab2.setLayout(layout)








        # Create first tab
        self.tab3.layout = QVBoxLayout(self)
        self.tab3.setLayout(self.tab1.layout)

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
        # treeView.doubleClicked.connect(self.getValue)

        #self.setCentralWidget(treeView)








        
        # data = {'col1':['1','2','3','4'],
        # 'col2':['1','2','1','3'],
        # 'col3':['1','1','2','1']}
        # table = TableView(data, 4, 3)
        # table.setParent (self.tab2)
        # table.show()


    # @pyqtSlot()
    # def on_click(self):
    #     print("\n")
    #     for currentQTableWidgetItem in self.tableWidget.selectedItems():
    #         print(currentQTableWidgetItem.row(), currentQTableWidgetItem.column(), currentQTableWidgetItem.text())



def json_tree(tree, parent, dictionary, tag):
    # https://gist.github.com/lukestanley/8525f9fdcb903a43376a35a77575edff
    for key in dictionary:
        if isinstance(dictionary[key], dict):
            # tree.insert(parent, 'end', uid, text=key)

            # json_tree(tree, uid, dictionary[key],'')


                        #entry = StandardItem (item)
                        #parent.appendRow (entry)



            # for item in dictionary[key]:
            #     me = StandardItem (item)
            #     parent.appendRow (me)
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
                #print (details)
                #me.appendRow( QStandardItem(details))
                #tree.insert (uid, 'end', uuid.uuid4(), text='Details', value=(details, None), tag=c)
                #k = dictionary[key]



            parent.appendRow (me)
            json_tree (tree, me, dictionary[key], '')



        if isinstance(dictionary[key], list):
            # http://pharma-sas.com/common-manipulation-of-qtreeview-using-pyqt5/
            #print (dictionary[key])

            k = QStandardItem (key)
            parent.appendRow (k)

            details = []
            dk = dictionary[key]
            if len(dk) > 0:
                print (type(dk))
                print (dk)
                print (type(dk[0]))
                print (dk[0])

                for el in dk:
                    print ('el', el)
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
                                print ('fm', fm, el[fm])                        
                                k.appendRow ([QStandardItem ('D' + str(fm)),QStandardItem (str(el[fm]))] )
                            #if len(fm) > 1:
                            #     details.append (QStandardItem (fm[1]))
                    elif type(el) == tuple:
                        print ('*** TUPLE ***')
                        for fm in el:
                            print ('fm', fm)                        
                            k.appendRow (QStandardItem (str(fm)) )
                            #if len(fm) > 1:
                            #     details.append (QStandardItem (fm[1]))
                    elif type(el) == list:
                        print ('*** LIST ***')
                        for fm in el:
                            print ('fm', fm, el[fm])                        
                            k.appendRow ([QStandardItem ('L' + str(fm)),QStandardItem (str(el[fm]))] )
                            #if len(fm) > 1:
                            #     details.append (QStandardItem (fm[1]))
                    else:
                        print ('el', el, type(el))
                        kdslkdslfkds (1000324)

                #parent.appendRows (details)
                #k.appendRows (details)
                return 
                if type(dk[0]) == list:
                    print ('*** LIST ***')
                    for item in dk[0]:
                        print (item)
                        #entry = StandardItem (item)
                        #parent.appendRow (entry)
                        details.append (QStandardItem (item))
                        #details.append (QStandardItem (dk[0][item]))
                        parent.appendRow (details)

                if type(dk[0]) == tuple:
                    print ('*** TUPLE ***')
                    for item in dk[0]:
                        print ('tuple', item, len(item))
                        #entry = StandardItem (item)
                        #parent.appendRow (entry)
                        details.append (QStandardItem (item))
                        #details.append (QStandardItem (dk[0][item]))
                        parent.appendRow (details)
                    print (dk[456])
                elif type(dk[0]) == list:
                    for item in dk[0]:
                        print (item)
                        #entry = StandardItem (item)
                        #parent.appendRow (entry)
                        details.append (QStandardItem (item))
                        #details.append (QStandardItem (dk[0][item]))
                    parent.appendRow (details)


                else:

                    print ('--type', type(dk[0]))                    

                    for item in dk[0]:
                        print (item, type(item))
                        #entry = StandardItem (item)
                        #parent.appendRow (entry)
                        details.append (QStandardItem (item))
                        details.append (QStandardItem (dk[0][item]))
                    parent.appendRow (details)
            # tree.insert(parent, 'end', uid, text=str(key) + '[]')
            # json_tree(tree,
            #         uid,
            #         dict([(i, x) for i, x in enumerate(dictionary[key])]),
            #         '')
        else:
            value = dictionary[key]
            print ('else', key, dictionary[key])
            if type(value) != dict:

                if not key in ('Contacts', 'Required', 'Fields', 'Fields_Count', 'Grids', 'Grids_Count'):
                    parent.appendRow ([QStandardItem ('P' + str(key)),QStandardItem (str(dictionary[key]))] )

            
            #if value is None:
            #    value = 'None'
            #tree.insert(parent, 'end', uid, text=key, value=(value, None), tag=tag) # value=(value, None) is a hack to not make strings go to different columns on space delimiter 


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
        #for n, key in enumerate(sorted(self.data.keys())):
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