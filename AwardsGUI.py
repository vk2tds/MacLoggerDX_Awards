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

# sudo port install py311-tkinter


# https://www.geeksforgeeks.org/python-gui-tkinter/
from tkinter import *
from tkinter import ttk 
import uuid

import macloggerdx_awards


hierarchy = macloggerdx_awards.awards

root = Tk()
root.title ('AwardsGUI')
root.geometry("1000x1000")


tabControl = ttk.Notebook(root)
  
tab1 = ttk.Frame(tabControl)
tab2 = ttk.Frame(tabControl)
tab3 = ttk.Frame(tabControl)
  
tabControl.add(tab1, text ='Hierarchy')
tabControl.add(tab2, text ='DXCC Challenge')
tabControl.add(tab3, text ='DXCC Grid')

tabControl.pack(expand = 1, fill ="both")

# ttk.Label(tab1, 
#           text ="Welcome to \
#           GeeksForGeeks").grid(column = 0, 
#                                row = 0,
#                                padx = 30,
#                                pady = 30)  
# ttk.Label(tab2,
#           text ="Lets dive into the\
#           world of computers").grid(column = 0,
#                                     row = 0, 
#                                     padx = 30,
#                                     pady = 30)




tree = ttk.Treeview(tab1)
ttk.Style().configure('Treeview', rowheight=30)
tree["columns"] = ('one') #("one", "two", 'three')
tree.column("one")
#tree.column("one", width=100)
#tree.column("two", width=100)
tree.heading("one", text="Details")
#tree.heading("two", text="b")
#tree.heading("three", text="c")

tree.tag_configure('AWARD-GOOD', background='green')
tree.tag_configure('AWARD-ALMOST', background='orange')
tree.tag_configure('AWARD-NONE', background='red')

def open_top(parent):
    tree.item(parent, open=True)  # open parent
    for child in tree.get_children(parent):
        tree.item(child, open=True)  # open parent
        #open_children(child)    # recursively open children


def open_children(parent):
    tree.item(parent, open=True)  # open parent
    for child in tree.get_children(parent):
        open_children(child)    # recursively open children

def json_tree(tree, parent, dictionary, tag):
    # https://gist.github.com/lukestanley/8525f9fdcb903a43376a35a77575edff
    for key in dictionary:
        uid = uuid.uuid4()
        #print (key)
        if isinstance(dictionary[key], dict):
            tree.insert(parent, 'end', uid, text=key)
            if 'Contacts' in dictionary[key] and 'Required' in dictionary[key]:
                # If the sub-entry from here contains Contacts and Required, then create one and colour it
                details = "%s/%s (%.1f%%)" % (str(dictionary[key]['Contacts']), str(dictionary[key]['Required']),
                                          ((dictionary[key]['Contacts']/dictionary[key]['Required']*100)) )
                c = ''
                if dictionary[key]['Contacts'] >= dictionary[key]['Required']:
                    c = 'AWARD-GOOD'
                elif (dictionary[key]['Contacts'] / dictionary[key]['Required']) > 0.75:
                    c = 'AWARD-ALMOST'
                else:
                    c = 'AWARD-NONE'                    
                #print (details)
                tree.insert (uid, 'end', uuid.uuid4(), text='Details', value=(details, None), tag=c)
                k = dictionary[key]
            json_tree(tree, uid, dictionary[key],'')
        elif isinstance(dictionary[key], list):
            tree.insert(parent, 'end', uid, text=str(key) + '[]')
            json_tree(tree,
                      uid,
                      dict([(i, x) for i, x in enumerate(dictionary[key])]),
                      '')
        else:
            value = dictionary[key]
            if value is None:
                value = 'None'
            tree.insert(parent, 'end', uid, text=key, value=(value, None), tag=tag) # value=(value, None) is a hack to not make strings go to different columns on space delimiter 

json_tree(tree, '', hierarchy, '')

print (hierarchy['ARRL']['DXCC']['Table'])

quote = hierarchy['ARRL']['DXCC']['Table']

S = Scrollbar(tab2)
T = Text(tab2, width=900)
T.tag_configure('font', font=('Courier', 11, 'bold'))
S.pack(side=RIGHT, fill=Y)
T.pack(side=LEFT, fill=Y)
S.config(command=T.yview)
T.config(yscrollcommand=S.set)
T.insert(END, quote, 'font')

#Text (tab2, , font= ("Courier", 14), )

r = hierarchy['ARRL']['DXCC']['RawTable']


# for x in range(len(r)):
#     for y in range(len(r[0])):
#         frameGrid = Frame(
#             master=tab3,
#             relief=RAISED,
#             borderwidth=2
#             )
#         frameGrid.grid(row=x, column=y)        
#         labelGrid = Label(master=frameGrid, text=r[x][y])
#         labelGrid.pack()







tree.pack(expand=True, fill='both')

#open_children(tree.focus())
open_top(tree.focus())

root.mainloop()
print ('Done)')