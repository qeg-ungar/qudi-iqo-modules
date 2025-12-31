# -*- coding: utf-8 -*-

"""
This file contains a gui for the laser controller logic.

Copyright (c) 2021, the qudi developers. See the AUTHORS.md file at the top-level directory of this
distribution and on <https://github.com/Ulm-IQO/qudi-iqo-modules/>

This file is part of qudi.

Qudi is free software: you can redistribute it and/or modify it under the terms of
the GNU Lesser General Public License as published by the Free Software Foundation,
either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public License along with qudi.
If not, see <https://www.gnu.org/licenses/>.
"""

import os
from PySide2 import QtCore, QtWidgets, QtGui

from qudi.core.connector import Connector
from qudi.core.module import GuiBase
from qudi.interface.simple_laser_interface_dlnsec import (
    TriggerMode,
    ShutterState,
    LaserState,
)
from qudi.util.paths import get_artwork_dir

from qudi.logic.laser_logic_dlnsec import LaserLogic

from .laser_control_dockwidget_dlnsec import LaserControlDockWidgetDlnsec
from .laser_plot_dockwidgets import LaserOutputDockWidget


class LaserMainWindow(QtWidgets.QMainWindow):
    """The main window for the LaserGui"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowTitle("qudi: Laser")

        # Create extra info dialog
        self.extra_info_dialog = QtWidgets.QDialog(self, QtCore.Qt.Dialog)
        self.extra_info_dialog.setWindowTitle("Laser Info")
        self.extra_info_label = QtWidgets.QLabel()
        self.extra_info_label.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
        extra_info_button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok
        )
        extra_info_button_box.setCenterButtons(True)
        extra_info_button_box.accepted.connect(self.extra_info_dialog.accept)
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.extra_info_label)
        layout.addWidget(extra_info_button_box)
        self.extra_info_dialog.setLayout(layout)
        layout.setSizeConstraint(layout.SetFixedSize)

        # create menu bar and actions
        menu_bar = QtWidgets.QMenuBar(self)
        self.setMenuBar(menu_bar)

        menu = menu_bar.addMenu("File")
        self.action_close = QtWidgets.QAction("Close")
        path = os.path.join(get_artwork_dir(), "icons", "application-exit")
        self.action_close.setIcon(QtGui.QIcon(path))
        self.action_close.triggered.connect(self.close)
        menu.addAction(self.action_close)

        menu = menu_bar.addMenu("View")
        self.action_view_controls = QtWidgets.QAction("Show Controls")
        self.action_view_controls.setCheckable(True)
        self.action_view_controls.setChecked(True)
        menu.addAction(self.action_view_controls)
        self.action_view_output_graph = QtWidgets.QAction("Show Output Graph")
        self.action_view_output_graph.setCheckable(True)
        self.action_view_output_graph.setChecked(True)
        menu.addAction(self.action_view_output_graph)
        self.action_view_temperature_graph = QtWidgets.QAction("Show Temperature Graph")
        self.action_view_temperature_graph.setCheckable(True)
        self.action_view_temperature_graph.setChecked(True)
        menu.addAction(self.action_view_temperature_graph)
        menu.addSeparator()
        self.action_view_default = QtWidgets.QAction("Restore Default")
        menu.addAction(self.action_view_default)

        # Create status bar
        status_bar = QtWidgets.QStatusBar(self)
        status_bar.setStyleSheet("QStatusBar::item { border: 0px}")
        self.setStatusBar(status_bar)
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QGridLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setColumnStretch(1, 1)
        widget.setLayout(layout)
        font = QtGui.QFont()
        font.setBold(True)
        font.setPointSize(12)
        label = QtWidgets.QLabel("Laser:")
        label.setFont(font)
        label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        layout.addWidget(label, 0, 0)
        self.shutter_label = QtWidgets.QLabel("Shutter:")
        self.shutter_label.setFont(font)
        self.shutter_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        layout.addWidget(self.shutter_label, 1, 0)
        self.laser_status_label = QtWidgets.QLabel("???")
        self.laser_status_label.setFont(font)
        layout.addWidget(self.laser_status_label, 0, 1)
        self.shutter_status_label = QtWidgets.QLabel("???")
        self.shutter_status_label.setFont(font)
        layout.addWidget(self.shutter_status_label, 1, 1)
        status_bar.addPermanentWidget(widget, 1)

    def set_laser_state(self, state):
        if state == LaserState.ON:
            text = "RUNNING"
        elif state == LaserState.OFF:
            text = "OFF"
        elif state == LaserState.LOCKED:
            text = "INTERLOCKED"
        else:
            text = "???"
        self.laser_status_label.setText(text)

    def set_shutter_state(self, state):
        if state == ShutterState.OPEN:
            text = "OPEN"
        elif state == ShutterState.CLOSED:
            text = "CLOSED"
        elif state == ShutterState.NO_SHUTTER:
            text = "no shutter"
        else:
            text = "???"
        self.shutter_status_label.setText(text)
        if state == ShutterState.NO_SHUTTER:
            if self.shutter_label.isVisible():
                self.shutter_label.hide()
                self.shutter_status_label.hide()
        elif not self.shutter_label.isVisible():
            self.shutter_label.show()
            self.shutter_status_label.show()


class LaserGui(GuiBase):
    """Main gui class for controlling a laser.

    Example config for copy-paste:

    laser_gui:
        module.Class: 'laser.laser_gui.LaserGui'
        connect:
            laser_logic: laser_logic
    """

    # declare connectors
    _laser_logic = Connector(name="laser_logic", interface=LaserLogic)

    sigLaserToggled = QtCore.Signal(bool)
    sigTriggerModeChanged = QtCore.Signal(object)
    sigPowerChanged = QtCore.Signal(float, object)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._mw = None
        self.control_dock_widget = None
        self.output_graph_dock_widget = None

    def on_activate(self):
        """Definition and initialisation of the GUI plus staring the measurement."""
        logic = self._laser_logic()
        # initialize data and start the laser data query loop
        logic._initialize_data()
        logic.start_query_loop()
        #####################
        # create main window
        self._mw = LaserMainWindow()
        self._mw.setDockNestingEnabled(True)
        # set up dock widgets
        self.control_dock_widget = LaserControlDockWidgetDlnsec()
        self.control_dock_widget.setFeatures(
            QtWidgets.QDockWidget.DockWidgetClosable
            | QtWidgets.QDockWidget.DockWidgetMovable
        )
        self.control_dock_widget.setAllowedAreas(QtCore.Qt.AllDockWidgetAreas)
        self._mw.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.control_dock_widget)

        self.control_dock_widget.visibilityChanged.connect(
            self._mw.action_view_controls.setChecked
        )
        self._mw.action_view_controls.triggered[bool].connect(
            self.control_dock_widget.setVisible
        )
        self.control_dock_widget.power_slider.setRange(*logic.power_range)
        self.control_dock_widget.power_setpoint_spinbox.setRange(*logic.power_range)

        self.output_graph_dock_widget = LaserOutputDockWidget()
        self.output_graph_dock_widget.setFeatures(
            QtWidgets.QDockWidget.AllDockWidgetFeatures
        )
        self.output_graph_dock_widget.setAllowedAreas(QtCore.Qt.AllDockWidgetAreas)
        self._mw.addDockWidget(
            QtCore.Qt.RightDockWidgetArea, self.output_graph_dock_widget
        )
        self.output_graph_dock_widget.visibilityChanged.connect(
            self._mw.action_view_output_graph.setChecked
        )
        self._mw.action_view_output_graph.triggered[bool].connect(
            self.output_graph_dock_widget.setVisible
        )
        self.output_graph_dock_widget.plot_widget.setLabel("left", "Power", units="mW")
        # DLNSEC: no current plot
        self.output_graph_dock_widget.plot_widget.getAxis("right").setVisible(False)
        self.output_graph_dock_widget.set_current_data(y=None)

        # DLNSEC: no temperature plot
        self._mw.action_view_temperature_graph.setVisible(False)
        self._mw.action_view_temperature_graph.setEnabled(False)

        self.restore_default_view()

        # Initialize data from logic
        self._mw.extra_info_label.setText(logic.extra_info)
        self._shutter_state_updated(logic.shutter_state)
        self._laser_state_updated(logic.laser_state)
        self._trigger_mode_updated(logic.trigger_mode)
        self._power_setpoint_updated(logic.power_setpoint, None)
        self._data_updated(logic.data)

        # connect control dockwidget signals
        self.control_dock_widget.laser_button.clicked[bool].connect(self._laser_clicked)
        self.control_dock_widget.sigTriggerModeChanged.connect(
            self._trigger_mode_clicked
        )
        self.control_dock_widget.power_slider.doubleSliderMoved.connect(
            self._power_slider_moving
        )
        self.control_dock_widget.power_slider.sliderReleased.connect(
            self._power_slider_moved
        )
        self.control_dock_widget.power_setpoint_spinbox.editingFinished.connect(
            self._power_setpoint_edited
        )

        # connect remaining main window actions
        self._mw.action_view_default.triggered.connect(self.restore_default_view)

        # connect external signals to logic
        self.sigLaserToggled.connect(logic.set_laser_state)
        self.sigPowerChanged.connect(logic.set_power)
        self.sigTriggerModeChanged.connect(logic.set_trigger_mode)

        # connect update signals from logic
        logic.sigPowerSetpointChanged.connect(
            self._power_setpoint_updated, QtCore.Qt.QueuedConnection
        )
        logic.sigTriggerModeChanged.connect(
            self._trigger_mode_updated, QtCore.Qt.QueuedConnection
        )
        logic.sigLaserStateChanged.connect(
            self._laser_state_updated, QtCore.Qt.QueuedConnection
        )
        logic.sigShutterStateChanged.connect(
            self._shutter_state_updated, QtCore.Qt.QueuedConnection
        )
        logic.sigDataChanged.connect(self._data_updated, QtCore.Qt.QueuedConnection)

        self.show()

    def on_deactivate(self):
        """Deactivate the module properly."""
        self._mw.close()
        self.output_graph_dock_widget.visibilityChanged.disconnect()
        self._mw.action_view_output_graph.triggered[bool].disconnect()

        # disconnect all signals
        logic = self._laser_logic()
        logic.sigPowerSetpointChanged.disconnect(self._power_setpoint_updated)
        logic.sigTriggerModeChanged.disconnect(self._trigger_mode_updated)
        logic.sigLaserStateChanged.disconnect(self._laser_state_updated)
        logic.sigShutterStateChanged.disconnect(self._shutter_state_updated)
        logic.sigDataChanged.disconnect(self._data_updated)

        self.control_dock_widget.visibilityChanged.disconnect()
        self._mw.action_view_controls.triggered.disconnect()
        self.control_dock_widget.laser_button.clicked[bool].disconnect()
        self.control_dock_widget.sigTriggerModeChanged.disconnect()
        self.control_dock_widget.power_slider.doubleSliderMoved.disconnect()
        self.control_dock_widget.power_slider.sliderReleased.disconnect()
        self.control_dock_widget.power_setpoint_spinbox.editingFinished.disconnect()
        self._mw.action_view_default.triggered.disconnect()
        self.sigLaserToggled.disconnect()
        self.sigPowerChanged.disconnect()
        self.sigTriggerModeChanged.disconnect()

    def show(self):
        """Make window visible and put it above all other windows."""
        self._mw.show()
        self._mw.raise_()
        self._mw.activateWindow()

    def restore_default_view(self):
        """Restore the arrangement of DockWidgets to the default"""
        # Show any hidden dock widgets
        self.control_dock_widget.show()
        self.output_graph_dock_widget.show()

        # re-dock any floating dock widgets
        self.output_graph_dock_widget.setFloating(False)

        # Arrange docks widgets
        self._mw.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.control_dock_widget)
        self._mw.addDockWidget(
            QtCore.Qt.RightDockWidgetArea, self.output_graph_dock_widget
        )

    @QtCore.Slot(bool)
    def _laser_clicked(self, checked):
        """Laser button callback. Disables button and sends a signal to the logic. Logic
        response will enable the button again.

        @param bool checked: Button check state after click
        """
        self.control_dock_widget.laser_button.setEnabled(False)
        self.sigLaserToggled.emit(checked)

    @QtCore.Slot(object)
    def _trigger_mode_clicked(self, mode):
        """Trigger mode button group callback. Disables trigger mode buttons and sends a signal to the
        logic. Logic response will enable the buttons again.

        @param TriggerMode mode: Selected TriggerMode enum
        """
        self.control_dock_widget.trigger_las_radio_button.setEnabled(False)
        self.control_dock_widget.trigger_ext_radio_button.setEnabled(False)
        self.sigTriggerModeChanged.emit(mode)

    @QtCore.Slot(float)
    def _power_slider_moving(self, value):
        """ToDo: Document"""
        self.control_dock_widget.power_setpoint_spinbox.setValue(value)

    @QtCore.Slot()
    def _power_slider_moved(self):
        """ToDo: Document"""
        value = self.control_dock_widget.power_slider.value()
        self.control_dock_widget.power_setpoint_spinbox.setValue(value)
        self.sigPowerChanged.emit(value, self.module_uuid)

    @QtCore.Slot()
    def _power_setpoint_edited(self):
        """ToDo: Document"""
        value = self.control_dock_widget.power_setpoint_spinbox.value()
        self.control_dock_widget.power_slider.setValue(value)
        self.sigPowerChanged.emit(value, self.module_uuid)

    @QtCore.Slot(float, object)
    def _power_setpoint_updated(self, value, caller_id):
        if caller_id != self.module_uuid:
            self.control_dock_widget.power_setpoint_spinbox.setValue(value)
            self.control_dock_widget.power_slider.setValue(value)

    @QtCore.Slot(object)
    def _trigger_mode_updated(self, mode, *_args):
        """Update trigger mode controls based on current trigger mode."""
        if mode == TriggerMode.LAS:
            self.control_dock_widget.trigger_las_radio_button.setChecked(True)
        elif mode == TriggerMode.EXT:
            self.control_dock_widget.trigger_ext_radio_button.setChecked(True)

        # Re-enable buttons after logic response.
        self.control_dock_widget.trigger_las_radio_button.setEnabled(True)
        self.control_dock_widget.trigger_ext_radio_button.setEnabled(True)

    @QtCore.Slot(object)
    def _laser_state_updated(self, state):
        self._mw.set_laser_state(state)
        if state == LaserState.ON:
            self.control_dock_widget.laser_button.setChecked(True)
            self.control_dock_widget.laser_button.setEnabled(True)
            if not self.control_dock_widget.laser_button.isVisible():
                self.control_dock_widget.laser_button.setVisible(True)
        elif state == LaserState.OFF:
            self.control_dock_widget.laser_button.setChecked(False)
            self.control_dock_widget.laser_button.setEnabled(True)
            if not self.control_dock_widget.laser_button.isVisible():
                self.control_dock_widget.laser_button.setVisible(True)
        elif state == LaserState.LOCKED:
            self.control_dock_widget.laser_button.setEnabled(False)
            self.control_dock_widget.laser_button.setChecked(False)
            if self.control_dock_widget.laser_button.isVisible():
                self.control_dock_widget.laser_button.setVisible(False)
        else:
            self.control_dock_widget.laser_button.setEnabled(False)
            if self.control_dock_widget.laser_button.isVisible():
                self.control_dock_widget.laser_button.setVisible(False)

    @QtCore.Slot(object)
    def _shutter_state_updated(self, state):
        self._mw.set_shutter_state(state)
        # DLNSEC has no shutter control in the GUI.

    @QtCore.Slot(dict)
    def _data_updated(self, data):
        try:
            x = data.pop("time")
        except KeyError:
            self.log.error("No time data given in data dict.")
            return

        y = data.pop("power", None)
        self.output_graph_dock_widget.set_power_data(y=y, x=x)
        self.control_dock_widget.power_spinbox.setValue(-1 if y is None else y[-1])

        # DLNSEC: no current plot.
        self.output_graph_dock_widget.set_current_data(y=None)
