

from PyQt5.QtGui import QSyntaxHighlighter, QFont, QDoubleValidator, QTextCharFormat, QMouseEvent, QBrush, QColor, QStandardItem
from PyQt5.QtWidgets import QStyledItemDelegate, QWidget, QLineEdit, QTextEdit, QStyleOptionViewItem, QVBoxLayout, QHBoxLayout, QFormLayout, QMenu, QMessageBox, QListWidget, QListWidgetItem, QSlider, QDialog, QCheckBox, QSizePolicy, QLabel
from PyQt5.QtCore import QModelIndex, QAbstractItemModel, Qt, pyqtSlot, QPoint, QObject, QEvent, QRegExp
from PyQt5.uic import loadUiType
import numpy as np
import utils
import hardware
from routines import RoutinesModel
from playlist import PlaylistModel, PlaylistMoveRoutineProxyModel


# Not using matplotlib because it's slow. Use pyqtgraph instead.
import matplotlib
# Make sure that we are using QT5
matplotlib.use('Qt5Agg')
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import matplotlib.colors as mcolors


# pyQtGraph
#import pyqtgraph as pg

# This class was created so that code variables have syntax highlighting
class VariableEditDelegate(QStyledItemDelegate):
    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex):
        variable_type = index.data(utils.VariableTypeRole)
        if variable_type == utils.CodeVariable:

            font = QFont()
            font.setFamily('Courier')
            font.setFixedPitch(True)
            font.setPointSize(9)

            editor = QTextEdit(parent)
            editor.setFont(font)
            editor.setTabChangesFocus(True)
            editor.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

            self.highlighter = Highlighter(editor.document())

            return editor

        else:
            editor = QLineEdit(parent)
            editor.setValidator(QDoubleValidator())
            return editor

    def setEditorData(self, editor, index: QModelIndex):
        variable_type = index.data(utils.VariableTypeRole)
        data = index.model().data(index, Qt.EditRole)
        if variable_type == utils.CodeVariable:
            editor.setPlainText(data)
        else:
            editor.setText(data)

    def setModelData(self, editor, model: QAbstractItemModel, index: QModelIndex):
        variable_type = index.data(utils.VariableTypeRole)
        if variable_type == utils.CodeVariable:
            text = editor.toPlainText()
        else:
            text = editor.text()
        model.setData(index, text, Qt.EditRole)

    def updateEditorGeometry(self, editor: QTextEdit, option: QStyleOptionViewItem, index: QModelIndex):
        editor.setGeometry(option.rect)


# source https://github.com/baoboa/pyqt5/blob/master/examples/richtext/syntaxhighlighter.py
class Highlighter(QSyntaxHighlighter):
    def __init__(self, parent=None):
        super(Highlighter, self).__init__(parent)

        keywordFormat = QTextCharFormat()
        keywordFormat.setForeground(Qt.darkBlue)
        keywordFormat.setFontWeight(QFont.Bold)

        keywordPatterns = ["\\bfor\\b", "\\bclass\\b", "\\bin\\b", "\\breturn\\b",
                           "\\bnot\\b", "\\bdef\\b", "\\blambda\\b"]

        self.highlightingRules = [(QRegExp(pattern), keywordFormat)
                for pattern in keywordPatterns]

        classFormat = QTextCharFormat()
        classFormat.setFontWeight(QFont.Bold)
        classFormat.setForeground(Qt.darkMagenta)
        self.highlightingRules.append((QRegExp("\\bQ[A-Za-z]+\\b"),
                classFormat))

        singleLineCommentFormat = QTextCharFormat()
        singleLineCommentFormat.setForeground(Qt.red)
        self.highlightingRules.append((QRegExp("#[^\n]*"), singleLineCommentFormat))

        self.multiLineCommentFormat = QTextCharFormat()
        self.multiLineCommentFormat.setForeground(Qt.red)

        quotationFormat = QTextCharFormat()
        quotationFormat.setForeground(Qt.darkGreen)
        self.highlightingRules.append((QRegExp("\".*\""), quotationFormat))
        self.highlightingRules.append((QRegExp("'.*'"), quotationFormat))

        functionFormat = QTextCharFormat()
        functionFormat.setFontItalic(True)
        functionFormat.setForeground(Qt.blue)
        self.highlightingRules.append((QRegExp("\\b[A-Za-z0-9_]+(?=\\()"), functionFormat))

        self.commentStartExpression = QRegExp("/\\*")
        self.commentEndExpression = QRegExp("\\*/")

    def highlightBlock(self, text):
        for pattern, format in self.highlightingRules:
            expression = QRegExp(pattern)
            index = expression.indexIn(text)
            while index >= 0:
                length = expression.matchedLength()
                self.setFormat(index, length, format)
                index = expression.indexIn(text, index + length)

        self.setCurrentBlockState(0)

        startIndex = 0
        if self.previousBlockState() != 1:
            startIndex = self.commentStartExpression.indexIn(text)

        while startIndex >= 0:
            endIndex = self.commentEndExpression.indexIn(text, startIndex)

            if endIndex == -1:
                self.setCurrentBlockState(1)
                commentLength = len(text) - startIndex
            else:
                commentLength = endIndex - startIndex + self.commentEndExpression.matchedLength()

            self.setFormat(startIndex, commentLength, self.multiLineCommentFormat)
            startIndex = self.commentStartExpression.indexIn(text, startIndex + commentLength)


class SequenceEditor(QWidget):

    def __init__(self, model: RoutinesModel):
        super().__init__()
        self.setLayout(QVBoxLayout())
        self.layout().setSpacing(2)
        self.layout().setAlignment(Qt.AlignTop)
        self.model = model

        self.model.dataChanged.connect(self.data_changed)

        self.model.cleared.connect(self.model_cleared)

        self.routine_row = None

    def add_channel_widget(self, row, track_name, channel: hardware.Channel):
        track = SequenceChannel(row, track_name, channel, self)
        self.layout().addWidget(track)

    @pyqtSlot()
    def model_cleared(self):
        self.clear()

    # Remove all widgets: this is used when the sequence editor is loaded with a new routine so the old one must go
    def clear(self):
        for i in reversed(range(self.layout().count())):
            widget = self.layout().itemAt(i).widget() # type: SequenceChannel
            widget.clear()
            widget.setParent(None)
            widget.destroy()

    def get_current_routine_item(self):
        if self.routine_row is not None:
            return self.model.item(self.routine_row, 0)
        return None

    def set_routine(self, routine_row: int):

        self.clear()

        self.routine_row = routine_row
        root_index = self.model.index(self.routine_row,0) # type: QModelIndex
        routine_item = self.model.itemFromIndex(root_index)


        for i in range(routine_item.rowCount()):
            channel_item = routine_item.child(i)
            channel = channel_item.data(utils.ChannelRole) # type: cards.Channel
            self.add_channel_widget(i, channel_item.data(Qt.DisplayRole), channel)

            for j in range(channel_item.rowCount()):
                event_item = channel_item.child(j)
                self.layout().itemAt(i).widget().add_event(event_item)

        self.model.dataChanged.emit(QModelIndex(), QModelIndex()) # send data changed notification to everything to set up new gui elements

    @pyqtSlot()
    def data_changed(self):
        pass
        # print("routine model data changed")


class SequenceChannel(QWidget):
    ui_form, ui_base = loadUiType('uis/track-widget.ui')

    def __init__(self, row, name, channel, sequence_editor):
        super().__init__()
        self.ui = self.ui_form()
        self.ui.setupUi(self)
        self.ui.track_label.setText(name)
        self.channel = channel
        self.row = row
        self.sequence_editor = sequence_editor # type: SequenceEditor
        self.ui.track_offset.editingFinished.connect(self.offset_edited)
        self.sequence_editor.model.dataChanged.connect(self.data_changed)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        self.add_event()

    def get_model_item(self):
        current_routine_index = self.sequence_editor.get_current_routine_item() # type: QStandardItem
        return current_routine_index.child(self.row)

    # if event_item is None, a new item will be added to the model
    # event_item will be None if the event was added through a double click of the empty track
    def add_event(self, event_item=None):
        if self.channel.card.type == utils.DigitalTrack:
            self.ui.track_container.addWidget(DigitalSequenceEvent(self,event_item))
        elif self.channel.card.type == utils.AnalogTrack:
            self.ui.track_container.addWidget(AnalogSequenceEvent(self,event_item))

    def position_of_event(self, sequence_event):
        return self.ui.track_container.indexOf(sequence_event)

    # def row(self):
    #     return self.sequence_editor.layout().indexOf(self)

    @pyqtSlot()
    def offset_edited(self):
        self.get_model_item().setData(self.ui.track_offset.text(), utils.TrackOffsetRole)

    @pyqtSlot()
    def data_changed(self):
        # Update offset
        if self.get_model_item() is not None:
            self.ui.track_offset.setText(self.get_model_item().data(utils.TrackOffsetRole))

    def clear(self):
        for event_i in reversed(range(self.ui.track_container.count())):
            event = self.ui.track_container.itemAt(event_i).widget() # type: SequenceEvent
            event.delete_widget()



class SequenceEvent(QWidget):

    ui_file = None

    def __init__(self, sequence_track, event_item):
        super().__init__()

        self.sequence_track = sequence_track # type: SequenceChannel
        self.event_item = event_item

        if self.event_item is None:
            self.event_item = QStandardItem()
            self.sequence_track.get_model_item().appendRow(self.event_item)
            self.initialize_event_item(self.event_item) # we init after append so that the item has a reference to the model

        self.event_item.model().dataChanged.connect(self.data_changed)

        self.ui_form, self.ui_base = loadUiType(self.ui_file)
        self.ui = self.ui_form()
        self.ui.setupUi(self)

        self.setContextMenuPolicy(Qt.CustomContextMenu)

        self.customContextMenuRequested.connect(self.context_menu_requested)

        #self.event_item.emitDataChanged()

    def initialize_event_item(self, event_item):
        pass

    @pyqtSlot()
    def data_changed(self):
        pass

    @pyqtSlot(QPoint)
    def context_menu_requested(self,pos):
        menu = QMenu()
        delete_event_action = menu.addAction("Delete event")
        move_right_action = menu.addAction("Move right")
        move_left_action = menu.addAction("Move left")
        action = menu.exec(self.mapToGlobal(pos))  # type: QMenu

        if action == delete_event_action:
            self.delete_event()
        elif action == move_right_action:
            # TODO: move events
            print("Not implemented!")
        elif action == move_left_action:
            # TODO: move events
            print("Not implemented!")

    def mouseDoubleClickEvent(self, event: QEvent):
        print(self.sequence_track.position_of_event(self))

    def delete_event(self):
        self.event_item.model().removeRow(self.event_item.row(),self.event_item.parent().index())
        self.delete_widget()

    def delete_widget(self):
        self.setParent(None)

class DigitalSequenceEvent(SequenceEvent):
    ui_file = "uis/digital-event.ui"

    def __init__(self, sequence_track, event_item):
        super().__init__(sequence_track, event_item)
        self.ui.state_button.toggled.connect(self.toggled)
        self.ui.event_duration.editingFinished.connect(self.duration_edited)

        self.data_changed()

    # Initialize the event item in the model
    def initialize_event_item(self, event_item: QStandardItem):
        event_item.model().init_digital_event_item(event_item)

    @pyqtSlot()
    def data_changed(self):
        # Update button state
        try:
            checked_state = self.event_item.checkState()
        except RuntimeError: # The item was deleted
            self.delete_widget()
            return
        self.ui.state_button.setChecked(checked_state)

        # Update duration
        self.ui.event_duration.setText(self.event_item.data(utils.EventDurationRole))
        brush = self.event_item.background() # type: QBrush
        self.ui.event_duration.setStyleSheet("QLineEdit { background: "+brush.color().name()+" }")

        # Update start and duration label
        try:
            self.ui.start_label.setText("%g" % (self.event_item.data(utils.EventStartRole)))
        except TypeError:
            self.ui.start_label.setText("-")
        try:
            self.ui.duration_label.setText("%g"%(self.event_item.data(utils.EventDurationRoleNum)))
        except TypeError:
            self.ui.duration_label.setText("-")

    @pyqtSlot(bool)
    def toggled(self, checked):
        if checked:
            self.event_item.setCheckState(Qt.Checked)
        else:
            self.event_item.setCheckState(Qt.Unchecked)

    @pyqtSlot()
    def duration_edited(self):
        self.event_item.setData(self.ui.event_duration.text(), utils.EventDurationRole)


class AnalogSequenceEvent(SequenceEvent):
    ui_file = "uis/analog-event.ui"

    def __init__(self, sequence_track, event_item):

        # load uis for each kind of function
        self.function_types = ["constant", "linear", "exp", "sin"]
        self.uis = {}
        self.widgets = {}
        for ftype in self.function_types:
            w = QWidget()
            ui_form, ui_base = loadUiType("uis/analog-event-"+ftype+".ui")
            ui = ui_form()
            ui.setupUi(w)
            self.uis[ftype] = ui
            self.widgets[ftype] = w

        super().__init__(sequence_track, event_item)

        self.ui.function_selection_combobox.installEventFilter(self) # To discard mouse wheel events

        self.ui.function_selection_combobox.addItems(self.function_types)
        self.ui.function_selection_combobox.currentTextChanged.connect(self.update_function_type)

        # Maybe more elegant way to do this but this will do
        self.uis['constant'].duration.editingFinished.connect(self.const_duration_edited)
        self.uis['constant'].val.editingFinished.connect(self.const_val_edited)

        self.uis['linear'].duration.editingFinished.connect(self.lin_duration_edited)
        self.uis['linear'].start_val.editingFinished.connect(self.lin_start_val_edited)
        self.uis['linear'].end_val.editingFinished.connect(self.lin_end_val_edited)

        self.uis['exp'].duration.editingFinished.connect(self.exp_duration_edited)
        self.uis['exp'].start_val.editingFinished.connect(self.exp_start_val_edited)
        self.uis['exp'].end_val.editingFinished.connect(self.exp_end_val_edited)
        self.uis['exp'].gamma.editingFinished.connect(self.exp_gamma_edited)

        self.uis['sin'].duration.editingFinished.connect(self.sin_duration_edited)
        self.uis['sin'].frequency.editingFinished.connect(self.sin_frequency_edited)
        self.uis['sin'].amplitude.editingFinished.connect(self.sin_amplitude_edited)
        self.uis['sin'].phase.editingFinished.connect(self.sin_phase_edited)
        self.uis['sin'].offset.editingFinished.connect(self.sin_offset_edited)

        try:
            self.data_changed()
        except RuntimeError as e:
            print("RuntimeError %s"%e)

    # Event filter to discard wheel events that change the type of ramp accidentaly
    def eventFilter(self, obj: QObject, event: QEvent):
        if obj == self.ui.function_selection_combobox and event.type() == QEvent.Wheel:
            return True
        else:
            return False

    @pyqtSlot()
    def data_changed(self):

        ftype = self.event_item.data(utils.AEventFunctionRole)
        self.ui.function_selection_combobox.setCurrentText(ftype)

        if not self.ui.event_params_layout.isEmpty():
            widget = self.ui.event_params_layout.itemAt(0).widget()  # type: QWidget
            widget.setParent(None)
        self.ui.event_params_layout.addWidget(self.widgets[ftype])

        # they all must have duration so we can set that for all
        self.uis[ftype].duration.setText(self.event_item.data(utils.EventDurationRole))
        # Get bg color duration
        brush = self.event_item.background()  # type: QBrush
        self.uis[ftype].duration.setStyleSheet("QLineEdit { background: " + brush.color().name() + " }")

        if ftype == "constant":
            self.uis[ftype].val.setText(self.event_item.data(utils.AEventValueRole))

            # Set style
            color = self.event_item.data(utils.AEventValueBackgroundRole)  # type: QBrush
            if color is not None and type(color) is QColor:
                self.uis[ftype].val.setStyleSheet("QLineEdit { background: " + color.name() + " }")
        elif ftype == "linear":
            self.uis[ftype].start_val.setText(self.event_item.data(utils.AEventStartValRole))
            self.uis[ftype].end_val.setText(self.event_item.data(utils.AEventEndValRole))
        elif ftype == "exp":
            self.uis[ftype].start_val.setText(self.event_item.data(utils.AEventStartValRole))
            self.uis[ftype].end_val.setText(self.event_item.data(utils.AEventEndValRole))
            self.uis[ftype].gamma.setText(self.event_item.data(utils.AEventGammaRole))
        elif ftype == "sin":
            self.uis[ftype].frequency.setText(self.event_item.data(utils.AEventFrequencyRole))
            self.uis[ftype].amplitude.setText(self.event_item.data(utils.AEventAmplitudeRole))
            self.uis[ftype].offset.setText(self.event_item.data(utils.AEventOffsetRole))
            self.uis[ftype].phase.setText(self.event_item.data(utils.AEventPhaseRole))

        # Update start and duration label
        try:
            self.ui.start_label.setText("%g"%(self.event_item.data(utils.EventStartRole)))
        except TypeError:
            self.ui.start_label.setText("-")
        try:
            self.ui.duration_label.setText("%g"%(self.event_item.data(utils.EventDurationRoleNum)))
        except TypeError:
            self.ui.duration_label.setText("-")

    @pyqtSlot(str)
    def update_function_type(self, text):
        self.event_item.setData(text, utils.AEventFunctionRole)

    def initialize_event_item(self, event_item: QStandardItem):
        event_item.model().init_analog_event_item(event_item)

    def const_duration_edited(self):
        self.event_item.setData(self.uis['constant'].duration.text(), utils.EventDurationRole)

    def const_val_edited(self):
        self.event_item.setData(self.uis['constant'].val.text(), utils.AEventValueRole)

    def lin_duration_edited(self):
        self.event_item.setData(self.uis['linear'].duration.text(), utils.EventDurationRole)

    def lin_start_val_edited(self):
        self.event_item.setData(self.uis['linear'].start_val.text(), utils.AEventStartValRole)

    def lin_end_val_edited(self):
        self.event_item.setData(self.uis['linear'].end_val.text(), utils.AEventEndValRole)

    def exp_duration_edited(self):
        self.event_item.setData(self.uis['exp'].duration.text(), utils.EventDurationRole)

    def exp_start_val_edited(self):
        self.event_item.setData(self.uis['exp'].start_val.text(), utils.AEventStartValRole)

    def exp_end_val_edited(self):
        self.event_item.setData(self.uis['exp'].end_val.text(), utils.AEventEndValRole)

    def exp_gamma_edited(self):
        self.event_item.setData(self.uis['exp'].gamma.text(), utils.AEventGammaRole)

    def sin_duration_edited(self):
        self.event_item.setData(self.uis['sin'].duration.text(), utils.EventDurationRole)

    def sin_frequency_edited(self):
        self.event_item.setData(self.uis['sin'].frequency.text(), utils.AEventFrequencyRole)

    def sin_amplitude_edited(self):
        self.event_item.setData(self.uis['sin'].amplitude.text(), utils.AEventAmplitudeRole)

    def sin_phase_edited(self):
        self.event_item.setData(self.uis['sin'].phase.text(), utils.AEventPhaseRole)

    def sin_offset_edited(self):
        self.event_item.setData(self.uis['sin'].offset.text(), utils.AEventOffsetRole)


class RoutinePropertiesDialog(QDialog):
    ui_form, ui_base = loadUiType('uis/routine-properties-dialog.ui')

    def __init__(self, cards, model: RoutinesModel, index: QModelIndex=None):
        self.model = model

        super().__init__()
        self.ui = self.ui_form()
        self.ui.setupUi(self)

        self.ui.all_button.clicked.connect(self.selectAll)
        self.ui.none_button.clicked.connect(self.selectNone)
        self.ui.button_box.accepted.connect(self.submitted)

        channel_list = self.ui.channel_list  # type: QListWidget

        active_channels  = []
        self.old_name = None

        if index is not None:
            num_channles = self.model.rowCount(index)

            self.old_name = index.data(Qt.DisplayRole)
            self.ui.routine_name.setText(self.old_name)

            for r in range(num_channles):
                chan_index = model.index(r,0,index)
                chan = chan_index.data(utils.ChannelRole)
                active_channels.append(chan)

        for card in cards.values():
            for chan in card.channels:
                new_item = QListWidgetItem(card.name+"-"+chan.name)
                new_item.setData(utils.ChannelRole, chan)
                new_item.setFlags(new_item.flags() | Qt.ItemIsUserCheckable )
                if chan in active_channels:
                    new_item.setCheckState(Qt.Checked)
                else:
                    new_item.setCheckState(Qt.Unchecked)
                channel_list.addItem(new_item)


    @pyqtSlot()
    def selectAll(self):
        channel_list = self.ui.channel_list  # type: QListWidget
        for i in range(channel_list.count()):
            channel_list.item(i).setCheckState(Qt.Checked)

    @pyqtSlot()
    def selectNone(self):
        channel_list = self.ui.channel_list  # type: QListWidget
        for i in range(channel_list.count()):
            channel_list.item(i).setCheckState(Qt.Unchecked)

    @pyqtSlot()
    def submitted(self):
        existing_routine_names = self.model.get_routine_names()
        print(existing_routine_names)
        try:
            existing_routine_names.remove(self.old_name)
        except ValueError:
            pass

        if len(self.name) == 0:
            message_box = QMessageBox(self)
            message_box.setText("Routine name must not be empty.");
            message_box.exec()
        elif self.name in existing_routine_names:
            message_box = QMessageBox(self)
            message_box.setText("Routine name must be unique.");
            message_box.exec()
        else:
            self.accept()

    @property
    def name(self):
        return self.ui.routine_name.text()

    @property
    def active_channels(self):

        channel_list = self.ui.channel_list  # type: QListWidget

        active_channels_ = []

        for i in range(channel_list.count()):
            item = channel_list.item(i) # type: QListWidgetItem
            if item.checkState() == Qt.Checked:
                active_channels_.append(item.data(utils.ChannelRole))

        return active_channels_


class MoveRoutineDialog(QDialog):
    ui_form, ui_base = loadUiType('uis/move-routine-dialog.ui')

    def __init__(self, playlist_model: PlaylistModel, index: QModelIndex=None):
        self.playlist_model = playlist_model
        self.index_to_move = index
        self.model = PlaylistMoveRoutineProxyModel(index)
        self.model.setSourceModel(self.playlist_model)

        super().__init__()
        self.ui = self.ui_form()
        self.ui.setupUi(self)

        self.ui.button_box.accepted.connect(self.submitted)

        self.ui.tree_view.setModel(self.model)
        self.ui.tree_view.expandAll()

    @pyqtSlot()
    def submitted(self):
        new_parent_index = self.model.mapToSource(self.ui.tree_view.currentIndex()) # type: QModelIndex
        self.playlist_model.move_branch(self.index_to_move,new_parent_index)

        self.accept()

class UniqueTextInputDialog(QDialog):
    ui_form, ui_base = loadUiType('uis/text-input-dialog.ui')

    def __init__(self, text_label, existing_values, initial_text = ""):
        self.existing_values = existing_values

        super().__init__()
        self.ui = self.ui_form()
        self.ui.setupUi(self)


        self.ui.button_box.accepted.connect(self.submitted)
        self.ui.text_label.setText(text_label)
        self.ui.text_line_edit.setText(initial_text)

    @property
    def name(self):
        return self.ui.text_line_edit.text()

    @pyqtSlot()
    def submitted(self):
        if len(self.name) == 0:
            message_box = QMessageBox(self)
            message_box.setText("Name must not be empty.");
            message_box.exec()
        elif self.name in self.existing_values:
            message_box = QMessageBox(self)
            message_box.setText("Name must be unique.");
            message_box.exec()
        else:
            self.accept()


class InspectorWidget(QWidget):
    def __init__(self, sequence=None):
        self.sequence = sequence

        super().__init__()

        self.setLayout(QHBoxLayout())

        plot_widget = QWidget()
        plot_widget.setLayout(QVBoxLayout())
        self.layout().addWidget(plot_widget)

        self.fig = Figure()
        self.axes = self.fig.add_subplot(111)
        self.fc = FigureCanvas(self.fig)
        self.fc.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Expanding)
        self.toolbar = NavigationToolbar(self.fc, self)
        plot_widget.layout().addWidget(self.fc)
        plot_widget.layout().addWidget(self.toolbar)

        # Checkbox panel for channel visibility
        self.checkbox_panel = QWidget()
        self.checkbox_panel.setLayout(QVBoxLayout())
        self.checkbox_panel.layout().setContentsMargins(0, 0, 0, 0)
        self.layout().addWidget(self.checkbox_panel)



        """
        # pyQtGraph
        pg.setConfigOption('background', 'w')
        pg.setConfigOption('foreground', 'k')

        self.plot = pg.PlotWidget()
        self.layout().addWidget(self.plot)
        """

        self.channel_checkboxes = {}  # Maps (chan_name, chan_index) -> QCheckBox
        self.channel_line_map = {}  # Maps channel tuple -> matplotlib line object
        self.channel_color_map = {}  # Maps channel tuple -> fixed hex color string
        self.active = False
        self.fix_scale = False

    def build_inspector(self):
        self.active = True
        self.clear_checkboxes()
        self.update_plot()

    def clear_checkboxes(self):
        """Remove all checkboxes from the panel"""
        for checkbox in self.channel_checkboxes.values():
            checkbox.deleteLater()
        self.channel_checkboxes.clear()
        self.channel_line_map.clear()
        self.channel_color_map.clear()
        layout = self.checkbox_panel.layout()
        while layout.count():
            layout.takeAt(0)

    def select_all_channels(self):
        for checkbox in self.channel_checkboxes.values():
            checkbox.setChecked(True)

    def select_none_channels(self):
        for checkbox in self.channel_checkboxes.values():
            checkbox.setChecked(False)

    def set_inactive(self):
        self.active = False

    def format_sequence_for_plotting(self, compiled_sequence):
        pl_points = {}

        for chan in compiled_sequence:
            pl_points[chan] = []
            events = compiled_sequence[chan]['events']
            for i in range(len(events)):
                event = events[i]

                # Add edges to value changes
                if len(pl_points[chan]) > 0:
                    pl_points[chan].append((event['time'], pl_points[chan][-1][1]))

                if event['type'] == 'boolean':
                    pl_points[chan].append((event['time'], event['state']))
                    pl_points[chan].append((event['time']+event['duration'], event['state']))
                elif event['type'] == 'constant':
                    pl_points[chan].append((event['time'], event['value']))
                    pl_points[chan].append((event['time']+event['duration'], event['value']))
                elif event['type'] == 'linear':
                    pl_points[chan].append((event['time'], event['start_val']))
                    pl_points[chan].append((event['time']+event['duration'], event['end_val']))
                elif event['type'] == 'sin':
                    N = 500  # TODO: get this from card maybe
                    t = np.linspace(event['time'], event['time']+event['duration'], N)
                    y = event['amplitude'] * np.sin(2 * np.pi * event['frequency'] * (t-t[0]) + event['phase']) + event['offset']
                    pl_points[chan].extend(zip(t, y))
                elif event['type'] == 'exp':
                    N = 500  # TODO: get this from card maybe
                    t = np.linspace(event['time'], event['time']+event['duration'], N)
                    egd = np.exp(event['gamma'] * event['duration'])
                    c1 = (-event['start_val'] + event['end_val']) / (egd - 1)
                    c2 = (-event['end_val'] + event['start_val']*egd) / (egd - 1)
                    y = c1 * np.exp( event['gamma'] * (t-t[0]) ) + c2
                    pl_points[chan].extend(zip(t, y))


        return pl_points

    def update_plot(self):
        if self.active:
            csequence = self.sequence.playlist.compile_active_playlist()
            if csequence is None:
                self.axes.cla()
                self.fig.canvas.draw_idle()
                return
            pl_points = self.format_sequence_for_plotting(csequence)

            # Create checkboxes for channels not yet in the panel
            for chan in pl_points:
                if chan not in self.channel_checkboxes:
                    chan_key, chan_index = chan
                    # Get descriptive name from channel object
                    channel = csequence[chan]['chan']
                    chan_display_name = channel.name
                    checkbox = QCheckBox(f"{chan_display_name}")
                    checkbox.setChecked(True)
                    checkbox.stateChanged.connect(self.update_plot)
                    self.checkbox_panel.layout().insertWidget(0, checkbox)
                    self.channel_checkboxes[chan] = checkbox
                    prop_cycle = matplotlib.rcParams['axes.prop_cycle']
                    colors = [c['color'] for c in prop_cycle]
                    self.channel_color_map[chan] = colors[len(self.channel_color_map) % len(colors)]

            if self.fix_scale:
                xlim = self.axes.get_xlim()
                ylim = self.axes.get_ylim()
            self.axes.cla()
            self.axes.set_xlabel('Time (ms)')

            # Collect y-axis labels and positions
            y_ticks = []
            y_tick_labels = []

            for chan in pl_points:
                chan_key, chan_index = chan

                # Only plot if checkbox is checked
                if chan in self.channel_checkboxes and not self.channel_checkboxes[chan].isChecked():
                    continue

                # Get descriptive name from channel object
                channel = csequence[chan]['chan']
                chan_display_name = channel.name

                trace = np.array(pl_points[chan])
                if len(trace) > 0:
                    t, y = trace[:, 0], trace[:, 1]
                    line, = self.axes.plot(t, 0.8*y+chan_index, color=self.channel_color_map[chan])
                    self.channel_line_map[chan] = line
                    y_ticks.append(chan_index)
                    y_tick_labels.append(chan_display_name)

            # Set y-axis with channel labels
            self.axes.set_yticks(y_ticks)
            self.axes.set_yticklabels(y_tick_labels)

            # Apply color styling to checkboxes
            for chan, checkbox in self.channel_checkboxes.items():
                if chan in self.channel_color_map:
                    checkbox.setStyleSheet(f"QCheckBox {{ color: {self.channel_color_map[chan]}; }}")

            if self.fix_scale:
                self.axes.set_xlim(xlim)
                self.axes.set_ylim(ylim)

            self.fig.canvas.draw_idle()

    def fix_scale_toggled(self):
        self.fix_scale = not self.fix_scale
        self.update_plot()


class IteratorSlidersWidget(QWidget):
    def __init__(self, sequence=None):
        self.sequence = sequence

        super().__init__()

        self.setLayout(QVBoxLayout())

        self.form_group = QWidget()
        self.form_group.setLayout(QFormLayout())
        self.layout().addWidget(self.form_group)

        self.slider_widgets = {}

    # This function is called whenever the variables model changes
    # Add or remove sliders when new iterating variables are added
    def update_sliders(self):
        iter_vars_dict = self.sequence.variables.get_iterating_variables()
        self.remove_unused_sliders(iter_vars_dict)

        for var in iter_vars_dict:

            try:
                num_vals = iter_vars_dict[var]['num_values']
                scan_index = iter_vars_dict[var]['scan_index']

                # if the slider already exists do not re-create
                if var in self.slider_widgets:
                    curr_slider = self.slider_widgets[var] # type: QSlider
                    if curr_slider.maximum() == num_vals-1: # check if the slider limits have changed
                        curr_slider.blockSignals(True)
                        curr_slider.setValue(scan_index)
                        curr_slider.blockSignals(False)
                    else:
                        curr_slider.setRange(0, num_vals-1)


                else:
                    # print("Adding new slider %s, current sliders %s"%(var, self.slider_widgets.keys()))
                    slider = QSlider(Qt.Horizontal)
                    slider.valueChanged.connect(self.slider_value_changed)
                    self.slider_widgets[var] = slider


                    slider.setRange(0, num_vals-1)

                    self.form_group.layout().addRow(var, slider)

            except (TypeError, ValueError): # When values are not well defined
                # ToDo: give an indication of the problem (i.e. paint fields red maybe).
                pass

        # sort sliders by nesting level
        ## get dict of nesting level --> var name
        nesting_levels = {}
        for var in iter_vars_dict:
            nesting_levels[int(iter_vars_dict[var]["nesting level"])] = var

        levels = list(nesting_levels.keys())
        levels.sort()

        i = 0
        j = 0 # There can be some empty rows because Qt is lazy to delete them so we keep track of them with j
        while i+j < self.form_group.layout().rowCount():
            try:
                var_name = self.form_group.layout().itemAt(i+j, QFormLayout.LabelRole).widget().text()
                if nesting_levels[i] == var_name:
                    # slider is in the correct place
                    i += 1
                else:
                    # move slide one place further
                    row = self.form_group.layout().takeRow(i+j) # type: QFormLayout.TakeRowResult
                    self.form_group.layout().insertRow(i+j+1, row.labelItem.widget(), row.fieldItem.widget())
            except AttributeError as e:
                # The widget has been removed so it cannot be found
                j += 1


        #self.slider_value_changed()

    # Only remove sliders of variables which are no longer scanning variables
    def remove_unused_sliders(self, iter_vars_dict):
        delete_list = []
        for var in self.slider_widgets:
            if var not in iter_vars_dict: # var is no longer an iterating variable -> remove slider
                widget = self.slider_widgets[var] # type: QWidget
                label = self.form_group.layout().labelForField(widget) # type: QLabel
                self.form_group.layout().removeWidget(widget)
                self.form_group.layout().removeWidget(label)
                widget.deleteLater()
                label.deleteLater()

                delete_list.append(var)

        for var in delete_list:
            del self.slider_widgets[var]

    @pyqtSlot()
    def slider_value_changed(self):
        scanvars_indices = {}
        for var in self.slider_widgets:
            scanvars_indices[var] = self.slider_widgets[var].value()

        self.sequence.variables.set_iterating_variables_indices(scanvars_indices)
