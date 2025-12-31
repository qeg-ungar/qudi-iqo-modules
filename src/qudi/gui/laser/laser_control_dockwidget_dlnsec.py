# -*- coding: utf-8 -*-

"""DLNSEC-specific laser control dock widget.

This is intentionally separate from the generic laser control dock widget, because the DLNSEC
laser uses trigger modes (LAS/EXT/...) rather than a Power/Current control-mode selection.
"""

__all__ = ("LaserControlDockWidgetDlnsec",)

from PySide2 import QtCore, QtWidgets

from qudi.util.widgets.scientific_spinbox import ScienDSpinBox
from qudi.util.widgets.slider import DoubleSlider
from qudi.util.widgets.advanced_dockwidget import AdvancedDockWidget
from qudi.interface.simple_laser_interface_dlnsec import TriggerMode


class LaserControlDockWidgetDlnsec(AdvancedDockWidget):
    sigTriggerModeChanged = QtCore.Signal(object)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        main_widget = QtWidgets.QWidget()
        main_layout = QtWidgets.QGridLayout()
        main_layout.setContentsMargins(1, 1, 1, 1)
        main_widget.setLayout(main_layout)
        self.setWidget(main_widget)

        self.laser_button = QtWidgets.QPushButton("Laser")
        self.laser_button.setCheckable(True)
        main_layout.addWidget(self.laser_button, 0, 0, 1, 2)

        group_box = QtWidgets.QGroupBox("Trigger Mode")
        layout = QtWidgets.QHBoxLayout()
        group_box.setLayout(layout)

        button_group = QtWidgets.QButtonGroup(self)
        self.trigger_las_radio_button = QtWidgets.QRadioButton("LAS")
        self.trigger_ext_radio_button = QtWidgets.QRadioButton("EXT")
        button_group.addButton(self.trigger_las_radio_button)
        button_group.addButton(self.trigger_ext_radio_button)
        layout.addWidget(self.trigger_las_radio_button)
        layout.addWidget(self.trigger_ext_radio_button)

        self.trigger_las_radio_button.clicked.connect(
            lambda: self.sigTriggerModeChanged.emit(TriggerMode.LAS)
        )
        self.trigger_ext_radio_button.clicked.connect(
            lambda: self.sigTriggerModeChanged.emit(TriggerMode.EXT)
        )

        main_layout.addWidget(group_box, 1, 0, 1, 2)

        group_box = QtWidgets.QGroupBox("Power")
        layout = QtWidgets.QVBoxLayout()
        layout.setAlignment(QtCore.Qt.AlignCenter)
        group_box.setLayout(layout)

        self.power_spinbox = ScienDSpinBox()
        self.power_spinbox.setDecimals(2)
        self.power_spinbox.setMinimum(-1)
        self.power_spinbox.setSuffix("mW")
        self.power_spinbox.setMinimumWidth(75)
        self.power_spinbox.setReadOnly(True)
        self.power_spinbox.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.power_spinbox.setFocusPolicy(QtCore.Qt.NoFocus)
        self.power_spinbox.setMouseTracking(False)
        self.power_spinbox.setKeyboardTracking(False)
        layout.addWidget(self.power_spinbox)

        self.power_setpoint_spinbox = ScienDSpinBox()
        self.power_setpoint_spinbox.setDecimals(2)
        self.power_setpoint_spinbox.setMinimum(0)
        self.power_setpoint_spinbox.setSuffix("%")
        self.power_setpoint_spinbox.setMinimumWidth(75)
        layout.addWidget(self.power_setpoint_spinbox)

        self.power_slider = DoubleSlider(QtCore.Qt.Vertical)
        self.power_slider.set_granularity(10000)  # 0.01% precision
        self.power_slider.setMinimumHeight(200)
        self.power_slider.setSizePolicy(
            QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding
        )
        layout.addWidget(self.power_slider)
        main_layout.addWidget(group_box, 2, 0)

        main_widget.setSizePolicy(
            QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Expanding
        )
