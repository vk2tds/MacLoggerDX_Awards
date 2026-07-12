#!/usr/local/python3

# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
# You should have received a copy of the GNU General Public License along with this program. If not,
# see <https://www.gnu.org/licenses/>.

# Darryl Smith, VK2TDS. darryl@radio-active.net.au Copyright 2023

# Turns the nested `awards` dict from macloggerdx_awards.analysis into a plain
# tree of nodes the hierarchy.html template can render as collapsible sections,
# colour-coding each award by how close it is to complete. This replaces the
# recursive QStandardItemModel building (json_tree) that used to live in qtAwards.py.

_SUMMARY_KEYS = ('Fields', 'Fields_Count', 'Grids', 'Grids_Count', 'Contacts', 'Required')


def _progress_badge(node):
    if 'Contacts' in node and 'Required' in node:
        contacts, required = node['Contacts'], node['Required']
        pct = (contacts / required * 100) if required else 0
        if contacts >= required:
            level = 'good'
        elif pct > 75:
            level = 'almost'
        else:
            level = 'none'
        return {'text': '%s/%s (%.1f%%)' % (contacts, required, pct), 'level': level}
    if 'Fields' in node and 'Fields_Count' in node:
        pct = int(node['Fields']) / int(node['Fields_Count']) * 100
        return {'text': 'Fields %s/%s (%.1f%%)' % (node['Fields'], node['Fields_Count'], pct), 'level': 'info'}
    if 'Grids' in node and 'Grids_Count' in node:
        pct = int(node['Grids']) / int(node['Grids_Count']) * 100
        return {'text': 'Grids %s/%s (%.1f%%)' % (node['Grids'], node['Grids_Count'], pct), 'level': 'info'}
    return None


def build_tree(dictionary):
    """Returns a list of {label, badge, children, leaves, list_values} nodes for one dict level.

    Note: the key is 'list_values', not 'items' -- Jinja's dot-notation resolves
    attributes before dict keys, and every dict already has a real `.items()`
    method, so a key literally named 'items' would never be reachable as `node.items`.
    """
    nodes = []
    for key, value in dictionary.items():
        if isinstance(value, dict):
            node = {
                'label': key,
                'badge': _progress_badge(value),
                'children': build_tree(value),
                'leaves': [(k, v) for k, v in value.items()
                           if not isinstance(v, (dict, list)) and k not in _SUMMARY_KEYS],
                'list_values': None,
            }
            nodes.append(node)
        elif isinstance(value, list):
            nodes.append({'label': key, 'badge': None, 'children': None, 'leaves': None,
                           'list_values': _render_list(value)})
    return nodes


_MAX_LIST_ITEMS = 25


def _render_list(items):
    rendered = []
    for el in items[:_MAX_LIST_ITEMS]:
        if isinstance(el, dict):
            rendered.append(', '.join('%s: %s' % (k, v) for k, v in el.items()))
        elif isinstance(el, (tuple, list)):
            rendered.append(', '.join(str(v) for v in el))
        else:
            rendered.append(str(el))
    if len(items) > _MAX_LIST_ITEMS:
        rendered.append('... %d more' % (len(items) - _MAX_LIST_ITEMS))
    return rendered
