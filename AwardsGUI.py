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

# sudo port install py311-tkinter


# https://www.geeksforgeeks.org/python-gui-tkinter/
from tkinter import *
from tkinter import ttk 
import uuid

import macloggerdx_awards


hierarchy = macloggerdx_awards.awards

root = Tk()
root.geometry("900x900")
tree = ttk.Treeview(root)
ttk.Style().configure('Treeview', rowheight=30)
tree["columns"] = ('one') #("one", "two", 'three')
tree.column("one")
#tree.column("one", width=100)
#tree.column("two", width=100)
tree.heading("one", text="a")
#tree.heading("two", text="b")
#tree.heading("three", text="c")

#def add_node(k, v, key):
#    for i, j in v.items():
#        print ("--%s %s "%(i,j))
#        tree.insert(k, 1, key + '.' + i, text=i + ' (' + str(k) + ')')
#        if isinstance(j, dict):
#            add_node(i, j, key + '.' + i)#

#for k, v in hierarchy.items():
 #   tree.insert("", 1, k, text=k)
#    print ("%s %s " % (k,v))
#    if k == 'STATS':
#        add_node(k, v, k)


def json_tree(tree, parent, dictionary):
    # https://gist.github.com/lukestanley/8525f9fdcb903a43376a35a77575edff
    for key in dictionary:
        uid = uuid.uuid4()
        if isinstance(dictionary[key], dict):
            tree.insert(parent, 'end', uid, text=key)
            json_tree(tree, uid, dictionary[key])
        elif isinstance(dictionary[key], list):
            tree.insert(parent, 'end', uid, text=key + '[]')
            json_tree(tree,
                      uid,
                      dict([(i, x) for i, x in enumerate(dictionary[key])]))
        else:
            value = dictionary[key]
            if value is None:
                value = 'None'
            tree.insert(parent, 'end', uid, text=key, value=(value, None))

json_tree(tree, '', hierarchy)



tree.pack(expand=True, fill='both')
root.mainloop()