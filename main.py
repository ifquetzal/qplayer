# To debug segmentation faults
#import faulthandler
#faulthandler.enable()

from PyQt5.uic import loadUiType
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
import sys
import config
import json
import os

from variables import *
from routines import *
from playlist import *
from widgets import *
from sequence import Sequence
from scheduler import Scheduler
from hardware import Hardware

class ControlSystemGUI(QMainWindow):
    def __init__(self, config_path, parent=None):
        self.config = config.Config(config_path)
        self.hardware = self.config.get_hardware()

        QMainWindow.__init__(self, parent)
        ui_main_window, main_window = loadUiType('uis/control-system.ui')
        self.ui = ui_main_window()
        self.ui.setupUi(self)
        self.setWindowIcon(QIcon('icons' + os.path.sep + 'pyPlayer_icon.svg'))

        # MODELS
        self.variables_model = VariablesModel()
        self.routines_model = RoutinesModel(self.variables_model, self.hardware)
        self.playlist_model = PlaylistModel(self.variables_model, self.routines_model)

        # DATABASE
        self.database = self.config.get_database()

        # PUBLISHER
        self.publisher = self.config.get_publisher()

        # SEQUENCE MANAGER
        self.sequence = Sequence(self.variables_model, self.routines_model, self.playlist_model)
        self.scheduler = Scheduler(self.sequence, self.hardware, self.database)
        self.scheduler.add_sequence_stopped_listener(self.sequence_stopped)
        self.scheduler.add_sequence_end_listener(self.sequence_finished)
        self.scheduler.add_sequence_start_listener(self.sequence_started)
        self.scheduler.add_sequence_iteration_finished_listener(self.sequence_iteration_finished)

        # UI SETUP
        self.sequence_editor = SequenceEditor(self.routines_model)
        self.ui.sequence_editor_scroll_area.setWidget(self.sequence_editor)

        self.ui.run_number_label.setText(str(self.database.get_latest_run_id()+1))

        # PROXY MODELS
        self.static_variables_model = VariablesProxyModel(["name","set","value","comment"], True, False, True)
        self.static_variables_model.setSourceModel(self.variables_model)
        self.iterator_variables_model = VariablesProxyModel(["name","value","start","stop","increment","scan index", "nesting level"], False, True, False)
        self.iterator_variables_model.setSourceModel(self.variables_model)

        # ADD MODELS TO VIEWS
        self.ui.static_variables_view.setModel(self.static_variables_model)
        self.ui.iterator_variables_view.setModel(self.iterator_variables_model)
        self.ui.routine_combo_box.setModel(self.routines_model)
        self.ui.playlist_view.setModel(self.playlist_model)
        self.ui.playlist_selection_combo_box.setModel(self.playlist_model)

        # VIEWS SETUP
        self.ui.static_variables_view.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.ui.iterator_variables_view.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.ui.static_variables_view.header().setSectionResizeMode(1,QHeaderView.Stretch)
        self.ui.static_variables_view.setItemDelegateForColumn(1, VariableEditDelegate())

        self.iterator_sliders_widget = IteratorSlidersWidget(self.sequence)
        self.ui.iterator_sliders_container.addWidget(self.iterator_sliders_widget)

        # Inspector setup
        self.inspector_widget = InspectorWidget(self.sequence)
        self.ui.inspector_container.addWidget(self.inspector_widget)

        # SIGNALS
        ## General
        self.ui.save_button.clicked.connect(self.save_sequence)
        self.ui.saveas_button.clicked.connect(self.save_sequence_as)
        self.ui.load_button.clicked.connect(self.load_sequence)
        self.ui.new_button.clicked.connect(self.new_sequence)
        self.ui.play_button.clicked.connect(self.play_sequence)
        self.ui.play_once_button.clicked.connect(self.play_sequence_once)
        self.ui.stop_button.clicked.connect(self.stop_sequence)
        self.ui.iterate_button.clicked.connect(self.iterate_sequence)
        self.ui.tabWidget.currentChanged.connect(self.tab_changed)
        self.ui.playlist_selection_combo_box.currentIndexChanged.connect(self.playlist_model.set_active_playlist)

        ## Variables
        self.ui.add_variable_group_button.clicked.connect(self.add_variable_group)
        self.ui.add_variable_button.clicked.connect(self.add_variable)
        self.ui.static_variables_view.customContextMenuRequested.connect(self.static_variables_context_menu_requested)
        self.ui.iterator_variables_view.customContextMenuRequested.connect(self.iterator_variables_context_menu_requested)
        self.variables_model.dataChanged.connect(self.iterator_variables_model.invalidate)
        self.variables_model.dataChanged.connect(self.static_variables_model.invalidate)
        self.variables_model.dataChanged.connect(self.iterator_sliders_widget.update_sliders)

        ## Sequence Editor
        self.ui.add_routine_button.clicked.connect(self.add_routine)
        self.ui.config_routine_button.clicked.connect(self.config_routine)
        self.ui.remove_routine_button.clicked.connect(self.remove_routine)
        self.ui.routine_combo_box.currentIndexChanged.connect(self.changed_routine)
        self.variables_model.dataChanged.connect(self.routines_model.update_values)
        ## Playlist
        self.ui.playlist_view.customContextMenuRequested.connect(self.playlist_context_menu_requested)
        self.ui.add_playlist_button.clicked.connect(self.add_playlist)
        self.variables_model.dataChanged.connect(self.playlist_model.update_values)
        ## Inspector
        self.variables_model.dataChanged.connect(self.inspector_widget.update_plot)
        self.ui.fix_scale.toggled.connect(self.inspector_widget.fix_scale_toggled)
        self.ui.select_all_channels.clicked.connect(self.inspector_widget.select_all_channels)
        self.ui.select_none_channels.clicked.connect(self.inspector_widget.select_none_channels)


        # UTILITY VARIABLES
        self.var_idx = 0
        self.group_idx = 0
        self.routine_idx = 0
        self.completed_iterations = 0
        self.iteration_start_run_id = 0
        self.delete_completed_iterations()

        self.current_filename = None # This variable is populated when loading/saving a sequence

        #self.load_sequence()

    ###########
    # GENERAL #
    ###########

    @pyqtSlot()
    def save_sequence(self):
        if self.current_filename is None:
            sequences_path = self.config.get_sequences_path()
            file_name, _ = QFileDialog.getSaveFileName(self, "Select file to save", sequences_path,
                                                       filter="Sequence File (*.json)")
            if file_name:

                # Append extension if not there yet
                if not file_name.endswith(".json"):
                    file_name += ".json"

                self.current_filename = file_name

        if self.current_filename is not None:
            sequence = self.sequence.sequence_to_dict()
            with open(self.current_filename, 'w') as outfile:
                json.dump(sequence, outfile, indent=2)

    @pyqtSlot()
    def save_sequence_as(self):
        sequences_path = self.config.get_sequences_path()
        file_path, _ = QFileDialog.getSaveFileName(self, "Select file to save as", sequences_path,
                                                   filter="Sequence File (*.json)")
        if file_path: # This is None if no file is selected
            file_name = file_path.split(os.sep)[-1]
            self.ui.filename_label.setText(file_name)

            # Append extension if not there yet
            if not file_path.endswith(".json"):
                file_path += ".json"

            self.current_filename = file_path

            sequence = self.sequence.sequence_to_dict()
            with open(self.current_filename, 'w') as outfile:
                json.dump(sequence, outfile, indent=2)

    @pyqtSlot()
    def load_sequence(self):
        sequences_path = self.config.get_sequences_path()
        file_path, _ = QFileDialog.getOpenFileName(self,"Select file to load", sequences_path,
                                                   "Sequence File (*.json)")
        if file_path: # This is None if no file is selected
            file_name = file_path.split(os.sep)[-1]
            self.ui.filename_label.setText(file_name)
            with open(file_path, 'r') as infile:
                sequence = json.load(infile)
                self.sequence.load_sequence_from_dict(sequence)
                self.current_filename = file_path
                self.inspector_widget.update_plot()

    def new_sequence(self):
        reply = QMessageBox.question(self, 'Message',
                                           "Are you sure to remove the current sequence?", QMessageBox.Yes |
                                           QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.sequence.clear()
            self.current_filename = None
            self.inspector_widget.update_plot()

    # This function is called by the scheduler
    def sequence_started(self, run_id, vars_dict, iter_dict):
        parameters = {'variables': vars_dict, 'iterators': iter_dict, 'run_id': run_id}
        id_dict = {'run_id':run_id}
        self.publisher.publish(f'starting@{json.dumps(id_dict)}@{json.dumps(parameters)}')
        self.ui.run_number_label.setText(str(run_id))

    # This function is called by the scheduler
    def sequence_stopped(self, run_id):
        self.ui.run_number_label.setText(str(run_id))
        self.uncheck_buttons()
        self.ui.stop_button.setChecked(True)

    # This function is called by the scheduler
    def sequence_finished(self, run_id, vars_dict, iter_dict):
        parameters = {'variables': vars_dict, 'iterators': iter_dict, 'run_id': run_id}
        id_dict = {'run_id':run_id}
        self.publisher.publish(f'finished@{json.dumps(id_dict)}@{json.dumps(parameters)}')

    # This function is called by the scheduler
    def sequence_iteration_finished(self):
        self.completed_iterations += 1
        self.ui.completed_iterations_label.setText("Completed Iterations: "+str(self.completed_iterations))
        iters_dict = {'iteration_start_run_id': self.iteration_start_run_id, 'completed_iterations': self.completed_iterations}
        self.publisher.publish(f'iteration_finished@{json.dumps(iters_dict)}')


    def delete_completed_iterations(self):
        self.ui.completed_iterations_label.setText("")
        self.ui.iteration_start_label.setText("")
        self.completed_iterations = 0

    def uncheck_buttons(self):
        self.ui.play_once_button.setChecked(False)
        self.ui.play_button.setChecked(False)
        self.ui.iterate_button.setChecked(False)
        self.ui.stop_button.setChecked(False)

    @pyqtSlot()
    def play_sequence_once(self):
        self.uncheck_buttons()
        self.ui.play_once_button.setChecked(True)
        self.scheduler.play_once()
        self.enable_inputs()
        self.delete_completed_iterations()

    @pyqtSlot()
    def play_sequence(self):
        self.uncheck_buttons()
        self.ui.play_button.setChecked(True)
        self.scheduler.play_continuous()
        self.enable_inputs()
        self.delete_completed_iterations()

    @pyqtSlot()
    def stop_sequence(self):
        self.uncheck_buttons()
        self.ui.stop_button.setChecked(True)
        self.scheduler.stop()
        self.enable_inputs()

    @pyqtSlot()
    def iterate_sequence(self):
        self.uncheck_buttons()
        self.ui.iterate_button.setChecked(True)
        self.iteration_start_run_id = self.scheduler.run_id
        if self.scheduler.iterate():
            self.disable_inputs()
            self.delete_completed_iterations()
            self.ui.iteration_start_label.setText("Iteration start: %d"%self.iteration_start_run_id)
            # TODO: check if shuffle is enabled
        else :
            self.uncheck_buttons()
            print('No iteration variable')


    @pyqtSlot(int)
    def tab_changed(self, tab_index):
        if self.ui.tabWidget.tabText(tab_index) == "Inspector":
            self.inspector_widget.build_inspector()
        else:
            self.inspector_widget.set_inactive()

        if self.ui.tabWidget.tabText(tab_index) == "Playlists":
            self.playlist_model.update_values()

    # Blocks inputs during interations
    def disable_inputs(self):
        pass # TODO

    # Enable inputs after interation has ended
    def enable_inputs(self):
        pass # TODO

    #############
    # VARIABLES #
    #############

    @pyqtSlot()
    def add_variable_group(self):
        self.variables_model.add_group( "default%02d" %self.group_idx)
        self.group_idx += 1

    @pyqtSlot()
    def add_variable(self):
        selected_indexes = self.ui.static_variables_view.selectedIndexes()
        if len(selected_indexes) > 0:
            parent_idx = selected_indexes[0] # type: QModelIndex

            # We only want variables to be children of groups, not of variables so we
            # find the parent if a variable is selected
            if parent_idx.parent().isValid():
                parent_idx = parent_idx.parent()

            parent = self.static_variables_model.mapToSource(parent_idx) # type: QStandardItem
            while self.variables_model.variable_exists("var%02d" % self.var_idx):
                self.var_idx += 1
            self.variables_model.add_variable(parent, name="var%02d" % self.var_idx, iterator=False,value="0")
            self.var_idx += 1

    @pyqtSlot(QPoint)
    def iterator_variables_context_menu_requested(self, pos):
        menu = QMenu()
        no_iterate_action = menu.addAction("Set as static")
        menu.addSeparator()
        increase_nesting_lvl =  menu.addAction("Increase nesting level")
        decrease_nesting_lvl = menu.addAction("Decrease nesting level")

        idx = self.ui.iterator_variables_view.indexAt(pos) # type: QModelIndex
        src_idx = self.iterator_variables_model.mapToSource(idx)

        if src_idx.parent().isValid(): # if a variable is selected

            action = menu.exec(self.ui.iterator_variables_view.mapToGlobal(pos))
            if action == no_iterate_action:
                self.variables_model.make_static(src_idx)
            elif action == increase_nesting_lvl:
                self.variables_model.increase_nesting_level(src_idx)
            elif action == decrease_nesting_lvl:
                self.variables_model.decrease_nesting_level(src_idx)

    @pyqtSlot(QPoint)
    def static_variables_context_menu_requested(self, pos):
        menu = QMenu()

        idx = self.ui.static_variables_view.indexAt(pos) # type: QModelIndex
        src_idx = self.static_variables_model.mapToSource(idx) # type: QModelIndex

        if src_idx.parent().isValid(): # if a variable is selected

            variable_type_action = None
            new_variable_type = None
            if self.variables_model.is_code_var(src_idx):
                variable_type_action = menu.addAction("Set as numeric variable")
                new_variable_type = utils.NumericVariable
            else:
                variable_type_action = menu.addAction("Set as code variable")
                new_variable_type = utils.CodeVariable


            iterate_action = menu.addAction("Iterate")
            move_to_menu = menu.addMenu("Move to group")

            group_list = self.variables_model.get_group_list()
            move_actions = {}
            for gr_idx in range(len(group_list)):
                group_name = group_list[gr_idx]
                new_action = move_to_menu.addAction(group_name)
                move_actions[new_action] = gr_idx

            delete_action = menu.addAction("Delete variable")

            action = menu.exec(self.ui.static_variables_view.mapToGlobal(pos)) # type: QMenu
            if action == variable_type_action:
                self.variables_model.set_var_type(src_idx, new_variable_type)
            elif action == iterate_action:
                self.variables_model.make_iterating(src_idx)
            elif action == delete_action:
                self.variables_model.removeRow(src_idx.row(),src_idx.parent())
            elif action in move_actions:
                taken_row = self.variables_model.itemFromIndex(src_idx.parent()).takeRow(src_idx.row())
                dest_item = self.variables_model.item(move_actions[action], 0)
                dest_item.insertRow(0,taken_row)
        elif src_idx.isValid(): # if a variable group is selected
            add_var_action = menu.addAction("Add variable")
            delete_action  = menu.addAction("Delete group")
            action = menu.exec(self.ui.static_variables_view.mapToGlobal(pos))  # type: QMenu
            if action == add_var_action:
                self.add_variable()
            elif action == delete_action:
                curr_name = self.variables_model.data(src_idx,Qt.DisplayRole)
                txt, ok = QInputDialog.getText(self, "Delete group",
                                               "Are you sure you want to delete the routine named '%s'?\n"
                                               "If yes, type the name of the group to confirm." % curr_name)
                if ok and txt == curr_name:
                    self.variables_model.removeRow(src_idx.row(),src_idx.parent())

    ###################
    # SEQUENCE EDITOR #
    ###################

    @pyqtSlot()
    def add_routine(self):

        dialog = RoutinePropertiesDialog(self.hardware.get_cards(), self.routines_model)
        rslt = dialog.exec()

        if rslt == QDialog.Accepted:
            name = dialog.name
            active_channels = dialog.active_channels
            routine_item = self.routines_model.add_routine(name, active_channels)
            new_row = routine_item.row()
            self.ui.routine_combo_box.setCurrentIndex(new_row)
            self.sequence_editor.set_routine(new_row)

    @pyqtSlot(int)
    def changed_routine(self, row):
        if row >= 0:
            self.sequence_editor.set_routine(row)
        else:
            self.sequence_editor.clear()

    @pyqtSlot()
    def config_routine(self):
        cb = self.ui.routine_combo_box # type: QComboBox
        root_index = cb.rootModelIndex()
        row = cb.currentIndex()
        element_index = self.routines_model.index(row,0,root_index) # type: QModelIndex
        if element_index.isValid():
            dialog = RoutinePropertiesDialog(self.hardware.get_cards(), self.routines_model, element_index)
            rslt = dialog.exec()

            if rslt == QDialog.Accepted:
                self.routines_model.setData(element_index, dialog.name) # Update routine name
                active_channels = dialog.active_channels
                self.routines_model.set_active_channels(element_index, active_channels) # Update active channels
                self.sequence_editor.set_routine(row)
        else:
            QMessageBox.information(self,"No routine","Please create a routine first")

    @pyqtSlot()
    def remove_routine(self):
        cb = self.ui.routine_combo_box # type: QComboBox
        curr_name = cb.currentText()
        root_index = cb.rootModelIndex()
        row = cb.currentIndex()
        txt, ok = QInputDialog.getText(self, "Delete routine", "Are you sure you want to delete the routine named '%s'?\n"
                                                               "If yes, type the name of the routine to confirm."%curr_name)
        if ok and txt == curr_name:
            self.routines_model.removeRow(row,root_index)

    ############
    # PLAYLIST #
    ############

    @pyqtSlot(QPoint)
    def playlist_context_menu_requested(self, pos):
        menu = QMenu()

        idx = self.ui.playlist_view.indexAt(pos) # type: QModelIndex

        if idx.isValid() and idx.column() == 0:
            if idx.parent().isValid(): # regular item
                remove_action = menu.addAction("Remove")
                move_action = menu.addAction("Move")
            else: # playlist
                rename_playlist_action = menu.addAction("Rename Playlist")
                delete_playlist_action = menu.addAction("Delete Playlist")
            routines = self.routines_model.get_routine_names()
            add_routine_actions = {}
            add_gap_action = menu.addAction("Add gap")

            if idx.data(utils.PlaylistItemTypeRole) == utils.Gap:
                modify_gap_action = menu.addAction("Modify gap duration")

            menu.addSection("Add:")
            for r in routines:
                add_routine_actions[r] = menu.addAction(r)

            action = menu.exec(self.ui.playlist_view.mapToGlobal(pos))

            if action in add_routine_actions.values():
                self.playlist_model.add_playlist_item(idx,action.text())
                self.ui.playlist_view.expandAll()
            elif action == add_gap_action:
                duration, ok = QInputDialog.getText(self,"Insert gap","Gap duration:")
                if ok:
                    self.playlist_model.add_gap(idx, duration)
                    self.ui.playlist_view.expandAll()

            if idx.data(utils.PlaylistItemTypeRole) == utils.Gap and action == modify_gap_action:
                old_duration = self.playlist_model.itemFromIndex(idx).data(utils.GapDurationRole)
                duration, ok = QInputDialog.getText(self,"Modify gap","Gap duration:",text=old_duration)
                if ok:
                    self.playlist_model.modify_gap(idx, duration)
                    self.ui.playlist_view.expandAll()

            if idx.parent().isValid():  # regular item
                if action == remove_action:
                    if self.playlist_model.hasChildren(idx):
                        curr_name = self.playlist_model.itemFromIndex(idx).data(Qt.DisplayRole)
                        button = QMessageBox.question(self, "Remove routine",
                                                       "The routine '%s' that you are trying to delete has children?\n"
                                                       "Are you sure you want to remove it with all of its children?" % curr_name,
                                                       QMessageBox.Ok | QMessageBox.Cancel, QMessageBox.Cancel)
                        if button == QMessageBox.Ok:
                            self.playlist_model.removeRow(idx.row(), idx.parent())
                    else:
                        self.playlist_model.removeRow(idx.row(), idx.parent())

                elif action == move_action:
                    dialog = MoveRoutineDialog(self.playlist_model, idx)
                    rslt = dialog.exec()

                    if rslt == QDialog.Accepted:
                        print("Accepted")
            else: #playlist
                if action == delete_playlist_action:
                    curr_name = self.playlist_model.itemFromIndex(idx).data(Qt.DisplayRole)
                    txt, ok = QInputDialog.getText(self, "Delete playlist",
                                                   "Are you sure you want to delete the playlist named '%s'?\n"
                                                   "If yes, type the name of the playlist to confirm." % curr_name)
                    if ok and txt == curr_name:
                        self.playlist_model.removeRow(idx.row(), idx.parent())
                elif action == rename_playlist_action:
                    current_name = idx.data(Qt.DisplayRole)
                    existing_playlists = self.playlist_model.get_playlists_names()
                    existing_playlists.pop(existing_playlists.index(current_name)) # Remove current name
                    dialog = UniqueTextInputDialog("New playlist name", existing_playlists, current_name)
                    rslt = dialog.exec()
                    if rslt == QDialog.Accepted:
                        new_name = dialog.name
                        # TODO: ensure unique name
                        if new_name != current_name:
                            self.playlist_model.rename_playlist(idx, new_name)


        else:
            print("Not a valid item")


    @pyqtSlot()
    def add_playlist(self):
        existing_playlists = self.playlist_model.get_playlists_names()
        dialog = UniqueTextInputDialog("New playlist name",existing_playlists)
        rslt = dialog.exec()
        if rslt == QDialog.Accepted:
            name = dialog.name
            self.playlist_model.add_playlist(name, "0", "-", "-", "-")
        # TODO: ensure unique names


    #############
    # INSPECTOR #
    #############

if __name__ == "__main__":
    import argparse
    import asyncio
    from qasync import QEventLoop

    parser = argparse.ArgumentParser(description='Quantum Player.')
    parser.add_argument('config_file', help='Path to JSON config file.')
    args = parser.parse_args()

    app = QApplication([]) # We pass an empty list to QApplication instead of sys.argv because we use sys.argv in our program
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    config_path = args.config_file
    myapp = ControlSystemGUI(config_path)
    myapp.show()
    with loop:
        loop.run_forever()

    """
    app = QApplication(sys.argv)
    myapp = ControlSystemGUI()
    myapp.show()
    sys.exit(app.exec_())
    """