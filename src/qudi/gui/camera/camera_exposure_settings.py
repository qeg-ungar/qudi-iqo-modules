# -*- coding: utf-8 -*-
__all__ = ("CameraExposureDock",)

from PySide2 import QtCore, QtWidgets
from qudi.util.widgets.scientific_spinbox import ScienDSpinBox
from qudi.util.widgets.slider import DoubleSlider
from qudi.util.widgets.advanced_dockwidget import AdvancedDockWidget
from qudi.interface.simple_laser_interface import ControlMode


class CameraExposureDock(AdvancedDockWidget):
    """ """

    sigControlModeChanged = QtCore.Signal(object)
    sigBackgroundSubtractionToggled = QtCore.Signal(bool)
    sigIntegrationChanged = QtCore.Signal(float)  # Value in nanoseconds
    sigBinningChanged = QtCore.Signal(int)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # generate main widget and layout
        main_widget = QtWidgets.QWidget()
        main_layout = QtWidgets.QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(15)
        main_widget.setLayout(main_layout)
        self.setWidget(main_widget)

        # Camera Mode Group
        mode_group_box = QtWidgets.QGroupBox("Camera Mode")
        mode_group_box.setMinimumHeight(70)
        mode_layout = QtWidgets.QHBoxLayout()
        mode_layout.setContentsMargins(10, 15, 10, 10)
        mode_group_box.setLayout(mode_layout)

        button_group = QtWidgets.QButtonGroup(self)
        self.normal_mode_radio_button = QtWidgets.QRadioButton("Normal")
        self.advanced_mode_radio_button = QtWidgets.QRadioButton("Advanced")
        button_group.addButton(self.normal_mode_radio_button)
        button_group.addButton(self.advanced_mode_radio_button)

        mode_layout.addWidget(self.normal_mode_radio_button)
        mode_layout.addWidget(self.advanced_mode_radio_button)

        self.normal_mode_radio_button.clicked.connect(self._on_normal_mode_clicked)
        self.advanced_mode_radio_button.clicked.connect(self._on_advanced_mode_clicked)

        # Set normal mode as default
        self.normal_mode_radio_button.setChecked(True)

        main_layout.addWidget(mode_group_box)

        # Background Subtraction Button
        self.background_subtraction_button = QtWidgets.QPushButton(
            "Background Subtraction: OFF"
        )
        self.background_subtraction_button.setCheckable(True)
        self.background_subtraction_button.setMinimumHeight(35)
        self.background_subtraction_button.clicked[bool].connect(
            self._on_background_subtraction_toggled
        )
        main_layout.addWidget(self.background_subtraction_button)

        # Hardware Integration Group
        # Range: 10 ns to 655340 ns (1 to 65534 * 10 ns)
        # Display in microseconds for readability
        integration_group_box = QtWidgets.QGroupBox("Hardware Integration")
        integration_group_box.setMinimumHeight(100)
        integration_layout = QtWidgets.QVBoxLayout()
        integration_layout.setContentsMargins(10, 15, 10, 10)
        integration_layout.setSpacing(8)
        integration_group_box.setLayout(integration_layout)

        # Setpoint row with slider
        setpoint_row = QtWidgets.QHBoxLayout()
        setpoint_row.setSpacing(10)

        self.integration_spinbox = ScienDSpinBox()
        self.integration_spinbox.setDecimals(3)  # Show 3 decimal places for µs
        self.integration_spinbox.setMinimum(0.010)  # 10 ns = 0.010 µs
        self.integration_spinbox.setMaximum(655.340)  # 655340 ns = 655.340 µs
        self.integration_spinbox.setSingleStep(0.010)  # 10 ns steps
        self.integration_spinbox.setSuffix(" µs")
        self.integration_spinbox.setValue(10.40)  # Default to normal mode value
        self.integration_spinbox.valueChanged.connect(
            self._on_integration_spinbox_changed
        )

        setpoint_row.addWidget(self.integration_spinbox, 1)
        integration_layout.addLayout(setpoint_row)

        # Slider - values in nanoseconds internally
        self.integration_slider = DoubleSlider(QtCore.Qt.Horizontal)
        self.integration_slider.set_granularity(100000)  # High precision for 10ns steps
        self.integration_slider.setRange(10, 655340)  # 10 ns to 655340 ns
        self.integration_slider.setValue(10400)  # 10.40 µs in nanoseconds
        self.integration_slider.setMinimumHeight(25)
        self.integration_slider.setMaximumHeight(40)
        self.integration_slider.valueChanged.connect(
            self._on_integration_slider_changed
        )
        integration_layout.addWidget(self.integration_slider)

        main_layout.addWidget(integration_group_box)

        # Hardware Binning Group
        # Range: 1 to 65534 (no units)
        binning_group_box = QtWidgets.QGroupBox("Hardware Binning")
        binning_group_box.setMinimumHeight(100)
        binning_layout = QtWidgets.QVBoxLayout()
        binning_layout.setContentsMargins(10, 15, 10, 10)
        binning_layout.setSpacing(8)
        binning_group_box.setLayout(binning_layout)

        # Setpoint row
        binning_setpoint_row = QtWidgets.QHBoxLayout()
        binning_setpoint_row.setSpacing(10)

        self.binning_spinbox = ScienDSpinBox()
        self.binning_spinbox.setDecimals(0)
        self.binning_spinbox.setMinimum(1)
        self.binning_spinbox.setMaximum(65534)
        self.binning_spinbox.setValue(1)
        self.binning_spinbox.valueChanged.connect(self._on_binning_spinbox_changed)

        binning_setpoint_row.addWidget(self.binning_spinbox, 1)
        binning_layout.addLayout(binning_setpoint_row)

        # Slider
        self.binning_slider = DoubleSlider(QtCore.Qt.Horizontal)
        self.binning_slider.set_granularity(100000)  # High precision for full range
        self.binning_slider.setRange(1, 65534)
        self.binning_slider.setValue(1)
        self.binning_slider.setMinimumHeight(25)
        self.binning_slider.setMaximumHeight(40)
        self.binning_slider.valueChanged.connect(self._on_binning_slider_changed)
        binning_layout.addWidget(self.binning_slider)

        main_layout.addWidget(binning_group_box)

        # Add stretch to push everything to the top
        main_layout.addStretch(1)

        # Set size policies to allow resizing
        main_widget.setSizePolicy(
            QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding
        )

        # Set minimum size for the dock widget itself
        self.setMinimumHeight(400)

        # Initialize in normal mode
        self._set_normal_mode()

    def _on_normal_mode_clicked(self):
        """Handle normal mode button click"""
        self._set_normal_mode()
        self.sigControlModeChanged.emit(ControlMode.POWER)

    def _on_advanced_mode_clicked(self):
        """Handle advanced mode button click"""
        self._set_advanced_mode()
        self.sigControlModeChanged.emit(ControlMode.CURRENT)

    def _set_normal_mode(self):
        """Set controls to normal mode - integration locked to 10.40 µs"""
        # Lock integration to 10.40 µs (10400 ns)
        self.integration_spinbox.setValue(10.40)
        self.integration_spinbox.setEnabled(False)
        self.integration_slider.setValue(10400)
        self.integration_slider.setEnabled(False)

        # Enable binning controls
        self.binning_spinbox.setEnabled(True)
        self.binning_slider.setEnabled(True)

    def _set_advanced_mode(self):
        """Set controls to advanced mode - all controls enabled"""
        self.integration_spinbox.setEnabled(True)
        self.integration_slider.setEnabled(True)
        self.binning_spinbox.setEnabled(True)
        self.binning_slider.setEnabled(True)

    def _on_integration_spinbox_changed(self, value):
        """Sync slider when spinbox changes (convert µs to ns)"""
        value_ns = value * 1000  # Convert µs to ns
        # Round to nearest 10 ns
        value_ns = round(value_ns / 10) * 10

        self.integration_slider.blockSignals(True)
        self.integration_slider.setValue(value_ns)
        self.integration_slider.blockSignals(False)

        # Emit signal with value in nanoseconds
        self.sigIntegrationChanged.emit(value_ns)

    def _on_integration_slider_changed(self, value):
        """Sync spinbox when slider changes (convert ns to µs)"""
        # Round to nearest 10 ns
        value_ns = round(value / 10) * 10
        value_us = value_ns / 1000  # Convert ns to µs

        self.integration_spinbox.blockSignals(True)
        self.integration_spinbox.setValue(value_us)
        self.integration_spinbox.blockSignals(False)

        # Emit signal with value in nanoseconds
        self.sigIntegrationChanged.emit(value_ns)

    def _on_binning_spinbox_changed(self, value):
        """Sync slider when spinbox changes"""
        self.binning_slider.blockSignals(True)
        self.binning_slider.setValue(int(value))
        self.binning_slider.blockSignals(False)

        # Emit signal
        self.sigBinningChanged.emit(int(value))

    def _on_binning_slider_changed(self, value):
        """Sync spinbox when slider changes"""
        int_value = int(round(value))

        self.binning_spinbox.blockSignals(True)
        self.binning_spinbox.setValue(int_value)
        self.binning_spinbox.blockSignals(False)

        # Emit signal
        self.sigBinningChanged.emit(int_value)

    def _on_background_subtraction_toggled(self, checked):
        """Handle background subtraction button toggle"""
        if checked:
            self.background_subtraction_button.setText("Background Subtraction: ON")
        else:
            self.background_subtraction_button.setText("Background Subtraction: OFF")
        self.sigBackgroundSubtractionToggled.emit(checked)

    def set_integration_value(self, value_ns):
        """Set integration value from external source (value in nanoseconds)"""
        value_us = value_ns / 1000
        self.integration_spinbox.blockSignals(True)
        self.integration_slider.blockSignals(True)
        self.integration_spinbox.setValue(value_us)
        self.integration_slider.setValue(value_ns)
        self.integration_spinbox.blockSignals(False)
        self.integration_slider.blockSignals(False)

    def set_binning_value(self, value):
        """Set binning value from external source"""
        self.binning_spinbox.blockSignals(True)
        self.binning_slider.blockSignals(True)
        self.binning_spinbox.setValue(value)
        self.binning_slider.setValue(value)
        self.binning_spinbox.blockSignals(False)
        self.binning_slider.blockSignals(False)

    def get_integration_value_ns(self):
        """Get current integration value in nanoseconds"""
        return int(self.integration_spinbox.value() * 100)

    def get_binning_value(self):
        """Get current binning value"""
        return int(self.binning_spinbox.value())
