#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  variables.py
#  
#

from PyQt5.QtCore import Qt, QModelIndex, QSortFilterProxyModel, pyqtSlot, pyqtSignal
from PyQt5.QtGui import QStandardItemModel, QStandardItem, QFont, QColor
import utils

import numpy as np
import scipy
import scipy.interpolate


class VariablesModel(QStandardItemModel):
    variable_fields = ["name", "set", "value", "iterator", "start", "stop", "increment", "comment", "scan index", "nesting level"]
    variable_types = [str, str, float, bool, float, float, float, str, int, int]

    def __init__(self):
        super().__init__()
        self.setHorizontalHeaderLabels(self.variable_fields)
        self.dataChanged.connect(self.update_values)

    def clear(self):
        self.removeRows(0, self.rowCount())

    def add_group(self, name):
        new_item = QStandardItem(name)

        font = QFont()
        font.setBold(True)
        font.setFamily('Helvetica')
        new_item.setData(font,Qt.FontRole)

        new_row = [new_item]

        # Add the rest of the columns as inert cells
        for i in range(len(self.variable_fields)-1):
            it = QStandardItem()
            it.setFlags(Qt.NoItemFlags)
            new_row.append(it)
        self.appendRow(new_row)
        self.dataChanged.emit(QModelIndex(),QModelIndex())

        return new_item.index()

    def add_variable(self, parent_idx, **kwargs):
        parent = self.itemFromIndex(parent_idx)
        new_row = []
        for i in range(len(self.variable_fields)):
            field = self.variable_fields[i]
            ftype = self.variable_types[i]
            it = QStandardItem()
            it.setTextAlignment(Qt.AlignTop)
            if ftype == bool:
                it.setCheckable(True)
            if field == "set":
                try:
                    float(kwargs[field]) # If it's numeric value, it can be converted
                    it.setData(utils.NumericVariable, utils.VariableTypeRole)
                except ValueError: # It's not a numeric value, treat as code
                    it.setData(utils.CodeVariable,utils.VariableTypeRole)
                except KeyError: #Field is not defined
                    pass
                except TypeError: # "set" field is None, this occurs for iterating variables
                    pass

            if field in ["value", "scan index", "nesting level"]:
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)

            if kwargs is not None and field in kwargs:
                if ftype == bool and kwargs[field]:
                    it.setCheckState(Qt.Checked)
                else:
                    it.setData(kwargs[field],Qt.DisplayRole)
            new_row.append(it)
        parent.appendRow(new_row)
        self.dataChanged.emit(QModelIndex(), QModelIndex())

    def is_iterator(self, var_index:QModelIndex):
        return var_index.parent().child(var_index.row(),self.variable_fields.index("iterator")).data(Qt.CheckStateRole) == Qt.Checked

    def make_iterating(self, var_index:QModelIndex):
        var_iterator_index = var_index.parent().child(var_index.row(),self.variable_fields.index("iterator"))
        # set the nesting level to be the maximum of the current iterating variables
        new_nesting_level = len(self.get_iterating_variables())
        self.setData(var_iterator_index.parent().child(var_iterator_index.row(), self.variable_fields.index("nesting level")), new_nesting_level)
        self.setData(var_iterator_index.parent().child(var_iterator_index.row(), self.variable_fields.index("scan index")), "0")
        self.blockSignals(True)
        self.setData(var_iterator_index, Qt.Checked, Qt.CheckStateRole)
        self.blockSignals(False)
        #print(var_iterator_index.isValid())
        #self.dataChanged.emit(var_iterator_index, var_iterator_index) # This causes segmentation fault, if whe emit a change for the whole model the problem is gone.
        self.dataChanged.emit(QModelIndex(), QModelIndex())

    def make_static(self, var_index:QModelIndex):
        var_iterator_index = var_index.parent().child(var_index.row(),self.variable_fields.index("iterator"))
        if not self.is_code_var(var_index):
            var_set = self.data(var_index.parent().child(var_index.row(),self.variable_fields.index("set")))
            self.setData(var_iterator_index.parent().child(var_iterator_index.row(), self.variable_fields.index("value")), var_set)
        self.blockSignals(True) # Signal is separated from dataChange to avoid segfault. See make_iterating for details.
        self.setData(var_iterator_index, Qt.Unchecked, Qt.CheckStateRole)
        self.blockSignals(False)
        self.sort_nesting_levels()
        self.dataChanged.emit(QModelIndex(), QModelIndex())

    def increase_nesting_level(self, var_index: QModelIndex):
        nesting_level_index = var_index.parent().child(var_index.row(), self.variable_fields.index("nesting level"))
        old_nesting_level = float(self.data(nesting_level_index))
        self.blockSignals(True)
        self.setData(nesting_level_index, old_nesting_level+1.5)
        self.sort_nesting_levels()
        self.blockSignals(False)
        self.dataChanged.emit(QModelIndex(), QModelIndex())

    def decrease_nesting_level(self, var_index: QModelIndex):
        nesting_level_index = var_index.parent().child(var_index.row(), self.variable_fields.index("nesting level"))
        old_nesting_level = float(self.data(nesting_level_index))
        self.blockSignals(True)
        self.setData(nesting_level_index, old_nesting_level-1.5)
        self.sort_nesting_levels()
        self.blockSignals(False)
        self.dataChanged.emit(QModelIndex(), QModelIndex())

    def sort_nesting_levels(self):

        # build a dict where key is nesting level and value is the nesting level QModelIndex
        nesting_level_indices = {}
        num_groups = self.rowCount()
        for g in range(num_groups):
            group_index = self.index(g,0)
            num_variables = self.rowCount(group_index)
            for v in range(num_variables):
                # If it is an iterating variable
                if self.index(v,self.variable_fields.index("iterator"),group_index).data(Qt.CheckStateRole) == Qt.Checked:
                    nesting_level_index = self.index(v, self.variable_fields.index("nesting level"), group_index)
                    nesting_level_indices[float(nesting_level_index.data())] = nesting_level_index

        old_levels = list(nesting_level_indices.keys())
        old_levels.sort()
        new_level = 0
        for old_nesting_level in old_levels:
            self.setData(nesting_level_indices[old_nesting_level], new_level)
            new_level += 1

    def is_code_var(self, var_index):
        # The variable type is part of the "set" cell only so we must refer to it directly
        # This function works if the var_index is any cell of the variable's row
        var_type = var_index.parent().child(var_index.row(),self.variable_fields.index("set")).data(utils.VariableTypeRole)
        return var_type == utils.CodeVariable

    def variable_exists(self, var_name) -> bool:
        num_groups = self.rowCount()
        for g in range(num_groups):
            group_index = self.index(g,0)
            num_variables = self.rowCount(group_index)
            for v in range(num_variables):
                if var_name == self.index(v, self.variable_fields.index("name"), group_index).data():
                    return True
        return False


    def set_var_type(self, var_index:QModelIndex, var_type):
        # The variable type is part of the "set" cell only so we must refer to it directly
        # This function works if the var_index is any cell of the variable's row
        var_set_idx = var_index.parent().child(var_index.row(),self.variable_fields.index("set"))
        self.setData(var_set_idx, var_type, utils.VariableTypeRole)

    def get_group_list(self):
        group_list = []
        for j in range(self.rowCount()):
            group_list.append(self.item(j,0).data(Qt.DisplayRole))
        return group_list

    def load_variables_from_pystruct(self, variables_dict):
        self.blockSignals(True)
        groups = variables_dict.keys()
        for group in groups:
            group_index = self.add_group(group)
            variables_list = variables_dict[group]
            for variable in variables_list:
                self.add_variable(group_index,**variable)
        self.blockSignals(False)
        self.dataChanged.emit(QModelIndex(), QModelIndex())

    # returns the full data of this map in a plain python format for the purpose of saving or processing
    def get_variables_pystruct(self):
        parsed_variables = {}
        for i in range(self.rowCount()):
            group_index = self.index(i,0)
            group_item = self.itemFromIndex(group_index)
            group_name = group_index.data()
            group_variables = []
            for j in range(group_item.rowCount()):
                variable = {}
                for k in range(len(self.variable_fields)):
                    field_name = self.variable_fields[k]
                    if field_name != "iterator":
                        variable[field_name] = group_item.child(j,k).data(Qt.DisplayRole)
                    else:
                        variable[field_name] = (group_item.child(j, k).data(Qt.CheckStateRole) == Qt.Checked)
                group_variables.append(variable)

                parsed_variables[group_name] = group_variables
        return parsed_variables

    # returns a dictionary of all variables and their values. This includes iterating variables.
    def get_variables_dict(self):
        variables = {}
        num_groups = self.rowCount()
        for g in range(num_groups):
            group_index = self.index(g,0)
            num_variables = self.rowCount(group_index)
            for v in range(num_variables):
                var_name = self.index(v, self.variable_fields.index("name"), group_index).data()
                var_value = self.index(v, self.variable_fields.index("value"), group_index).data()
                variables[var_name] = float(var_value)

        return variables

    def get_iterating_variables(self):
        iter_vars = {}
        num_groups = self.rowCount()
        for g in range(num_groups):
            group_index = self.index(g,0)
            #print(group_index.data())
            num_variables = self.rowCount(group_index)
            for v in range(num_variables):
                # If it is an iterating variable
                if self.index(v,self.variable_fields.index("iterator"),group_index).data(Qt.CheckStateRole) == Qt.Checked:
                    try:
                        var_name = self.index(v, self.variable_fields.index("name"), group_index).data()
                        start = float(self.index(v, self.variable_fields.index("start"), group_index).data())
                        stop = float(self.index(v, self.variable_fields.index("stop"), group_index).data())
                        if start >= stop : raise ValueError # Error fixed: When stop value is greater than start value, an error ocurred and the program crashed
                        increment = float(self.index(v, self.variable_fields.index("increment"), group_index).data())
                        nesting_lvl = int(self.index(v, self.variable_fields.index("nesting level"), group_index).data())
                        scan_index = int(self.index(v, self.variable_fields.index("scan index"), group_index).data())
                        # TODO: replace this with something that doesn't require allocating memory. Lazy Asaf from the past didn't do it.
                        num_values = len(np.arange(start, stop + increment, increment))
                        iter_vars[var_name] = {"start": start, "stop": stop, "increment": increment, "nesting level": nesting_lvl, "num_values": num_values, "scan_index":scan_index}
                    except (TypeError, ValueError, ZeroDivisionError): # When values are not well defined
                        # ToDo: give an indication of the problem (i.e. paint fields red maybe).
                        return { }

        return iter_vars

    def reset_indices(self):
        self.blockSignals(False)
        num_groups = self.rowCount()
        for g in range(num_groups):
            group_index = self.index(g,0)
            num_variables = self.rowCount(group_index)
            for v in range(num_variables):
                # If it is an iterating variable
                if self.index(v,self.variable_fields.index("iterator"),group_index).data(Qt.CheckStateRole) == Qt.Checked:
                    idx = self.index(v, self.variable_fields.index("scan index"), group_index)
                    self.setData(idx, "0", Qt.DisplayRole)
        self.blockSignals(False)
        self.update_values()


    def set_iterating_variables_indices(self, scanvars_indices):
        # print("Setting indices to: "+str(scanvars_indices))
        self.blockSignals(True)
        for (var_name,idx) in scanvars_indices.items():
            # only one item should be returned since variable names should be unique
            item = self.findItems(var_name, flags=Qt.MatchRecursive, column=0)[0] # type: QStandardItem
            item.parent().child(item.row(), column=self.variable_fields.index("scan index")).setData(str(idx), Qt.DisplayRole)

        self.blockSignals(False)
        self.update_values()

    def to_number(self, expr, variables=None):
        if variables is None:
            variables = self.get_variables_dict()

        return_value = None
        try:
            return_value = eval(expr,variables)
        except (SyntaxError, ValueError):
            pass

        return return_value

    @pyqtSlot()
    def update_values(self):
        value_changed = False # Flag to decide if dataChanged signal should be emitted

        to_do = [] # reference to non-numerical variables
        variables_dict = {'np':np, 'int':int, 'scipy':scipy, 'print':print}

        # __builtins__ is added so eval treats 'variables' as we want
        # (it doesn't add the builtin python variables)
        variables_dict["__builtins__"] = {}

        self.blockSignals(True)

        # Loop through all variables to find the numerical ones
        num_groups = self.rowCount()
        for g in range(num_groups):
            # print("g=%d"%g)
            group_index = self.index(g,0)
            num_variables = self.rowCount(group_index)
            # print("num_vars=%d"%num_variables)
            for v in range(num_variables):
                name_idx = self.index(v, self.variable_fields.index("name"), group_index)
                var_name = name_idx.data()

                # Set iterating variables
                if self.is_iterator(name_idx):
                    var_start = self.index(v, self.variable_fields.index("start"), group_index).data()
                    var_stop = self.index(v, self.variable_fields.index("stop"), group_index).data()
                    var_increment = self.index(v, self.variable_fields.index("increment"), group_index).data()
                    var_scan_index = self.index(v, self.variable_fields.index("scan index"), group_index).data()
                    val_idx = self.index(v, self.variable_fields.index("value"), group_index)

                    try:
                        fstart = float(var_start)
                        fstop = float(var_stop)
                        finc = float(var_increment)

                        if fstart >= fstop:
                            raise ValueError("El valor de 'start' debe ser menor que 'stop'.") # Error fixed: When stop value is greater than start value, an error ocurred and the program crashed

                        if finc == 0:
                            raise ValueError("El incremento no puede ser 0.")

                        if finc < 0:
                            raise ValueError("El incremento no puede ser negativo.")

                        isidx = int(var_scan_index)

                        # TODO: isn't this rounding too strict?
                        try:
                            curr_val = round(np.arange(fstart, fstop+finc, finc)[isidx],10) # To remove rounding errors
                        except IndexError:
                            curr_val = round(np.arange(fstart, fstop+finc, finc)[0],10)

                        if "%.9g"%curr_val != self.data(val_idx):
                            #print("Iter var Changed from %s to %g"%(self.data(val_idx), curr_val))
                            self.setData(val_idx, "%.9g"%curr_val)
                            value_changed = True
                        variables_dict[var_name] = curr_val

                        # If no errors during conversion, set default style
                        self.update_style(name_idx)
                        # Bug fixed: When stop is greater than start, the program crashed. Not anymore.
                        self.update_style(self.index(v, self.variable_fields.index("start"), group_index), error=False)
                        self.update_style(self.index(v, self.variable_fields.index("stop"), group_index), error=False)
                    except (TypeError, ValueError):
                        self.update_style(name_idx, error=True)
                        # Bug fixed: When stop is greater than start, the program crashed. Not anymore.
                        self.update_style(self.index(v, self.variable_fields.index("start"), group_index), error=True)
                        self.update_style(self.index(v, self.variable_fields.index("stop"), group_index), error=True)

                # Set numerical variables
                else:
                    var_set = self.index(v,self.variable_fields.index("set"),group_index).data()
                    if type(var_set) == str:
                        # print("%d %d %s=%s" % (g, v, var_name, var_set))
                        try:
                            var_val = float(var_set)  # Cast variables which are numerical
                            val_idx = self.index(v, self.variable_fields.index("value"), group_index)
                            if "%.9g"%var_val != self.data(val_idx):
                                #print("Numeric var Changed from %s to %g"%(self.data(val_idx), var_val))
                                self.setData(val_idx, "%.9g"%var_val)
                                value_changed = True
                                self.update_style(name_idx)
                            variables_dict[var_name] = var_val
                        except ValueError:
                            to_do.append((g,v))

        # Now we do our best to parse code variables
        retry_attempts = 0
        while len(to_do) > 0:
            g, v = to_do.pop()
            group_index = self.index(g, 0)
            var_set = self.index(v, self.variable_fields.index("set"), group_index).data()
            if type(var_set) == str:
                var_set = var_set.replace("return","_return_ =")
                loc_dict = {}
                try:
                    exec(var_set,variables_dict,loc_dict)
                    var_val = loc_dict["_return_"]
                    val_idx = self.index(v, self.variable_fields.index("value"), group_index)
                    var_name_idx = self.index(v, self.variable_fields.index("name"), group_index)
                    self.update_style(var_name_idx)
                    var_name = var_name_idx.data()
                    if "%.9g" % var_val != self.data(val_idx):
                        #print("Code var Changed from %s to %g"%(self.data(val_idx), var_val))
                        self.setData(val_idx, "%.9g" % var_val)
                        value_changed = True
                    variables_dict[var_name] = var_val
                    retry_attempts = 0
                except (NameError, TypeError, KeyError, SyntaxError) as e:
                    # Return to To-Do list if this doesn't work (if there is no error, it should eventually work once
                    # all the required variables are evaluated)
                    to_do.insert(0,(g,v))
                    retry_attempts += 1
                    if len(to_do) <= retry_attempts:  # Avoid infinite retrys, give up all hope after trying everything
                        print("Error: Variable set cannot be numerically evaluated: %s %s" % (str(to_do), e))

                        for g,v in to_do:
                            group_index = self.index(g, 0)
                            name_index = self.index(v, self.variable_fields.index("name"), group_index)
                            self.update_style(name_index, error=True)
                        break

        self.blockSignals(False)
        if value_changed:
            self.dataChanged.emit(QModelIndex(),QModelIndex())
            # ToDo: maybe it's more efficient to call dataChanged for each QModelIndex that was changed]

    def update_style(self, name_index:QModelIndex, error=False):
        color = QColor()
        font = QFont()
        if self.is_code_var(name_index) and not self.is_iterator(name_index):
            font.setItalic(True)

        if not error:
            self.itemFromIndex(name_index).setBackground(Qt.white)
            self.itemFromIndex(name_index).setFont(font)
        elif error:
            color.setNamedColor("#ffc5c7")
            font.setStrikeOut(True)
            self.itemFromIndex(name_index).setBackground(color)
            self.itemFromIndex(name_index).setFont(font)


class VariablesProxyModel(QSortFilterProxyModel):
    def __init__(self, accepted_fields, show_static, show_iterator, show_empty_groups):
        super().__init__()
        self.accepted_fields = accepted_fields
        self.show_iterator = show_iterator
        self.show_static = show_static
        self.show_empty_groups = show_empty_groups

    def filterAcceptsColumn(self, source_column: int, source_parent: QModelIndex):
        return VariablesModel.variable_fields[source_column] in self.accepted_fields

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex):
        if source_parent.isValid():  # This is a variable
            row_idx = source_parent.child(source_row,
                                          VariablesModel.variable_fields.index("iterator"))  # Index of iterator cell
            if self.sourceModel().data(row_idx, Qt.CheckStateRole) == Qt.Checked:
                return self.show_iterator
            else:
                return self.show_static

        else:  # This is a group
            group_item = self.sourceModel().item(source_row,0) # type: QStandardItem
            visible_contents = 0
            rows = group_item.rowCount()
            col = VariablesModel.variable_fields.index("iterator")
            for j in range(rows):
                if group_item.child(j,col).data(Qt.CheckStateRole) == Qt.Checked and self.show_iterator:
                    visible_contents += 1
                elif group_item.child(j,col).data(Qt.CheckStateRole) == Qt.Unchecked and self.show_static:
                    visible_contents += 1

            if visible_contents == 0:
                return self.show_empty_groups
            else:
                return True
