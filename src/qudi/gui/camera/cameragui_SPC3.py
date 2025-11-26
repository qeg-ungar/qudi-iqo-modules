# -*- coding: utf-8 -*-
"""
This module contains a GUI for operating the spectrometer camera logic module.

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
import datetime

from qudi.core.module import GuiBase
from qudi.core.connector import Connector
from qudi.util.widgets.plotting.image_widget import ImageWidget
from qudi.util.datastorage import TextDataStorage
from qudi.util.paths import get_artwork_dir
from qudi.gui.camera.camera_settings_dialog import CameraSettingsDialog
from .camera_exposure_settings import CameraExposureDock

class CameraMainWindow(QtWidgets.QMainWindow):
    """ QMainWindow object for qudi CameraGui module """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Create menu bar
        menu_bar = QtWidgets.QMenuBar()
        menu = menu_bar.addMenu('File')
        self.action_save_frame = QtWidgets.QAction('Save Frame')
        path = os.path.join(get_artwork_dir(), 'icons', 'document-save')
        self.action_save_frame.setIcon(QtGui.QIcon(path))
        menu.addAction(self.action_save_frame)
        menu.addSeparator()
        self.action_show_settings = QtWidgets.QAction('Settings')
        path = os.path.join(get_artwork_dir(), 'icons', 'configure')
        self.action_show_settings.setIcon(QtGui.QIcon(path))
        menu.addAction(self.action_show_settings)
        menu.addSeparator()
        self.action_close = QtWidgets.QAction('Close')
        path = os.path.join(get_artwork_dir(), 'icons', 'application-exit')
        self.action_close.setIcon(QtGui.QIcon(path))
        self.action_close.triggered.connect(self.close)
        menu.addAction(self.action_close)
        self.setMenuBar(menu_bar)

        self.action_view_controls = QtWidgets.QAction('Show Controls')
        self.action_view_controls.setCheckable(True)
        self.action_view_controls.setChecked(True)
        menu.addAction(self.action_view_controls)

        # Create toolbar
        toolbar = QtWidgets.QToolBar()
        toolbar.setAllowedAreas(QtCore.Qt.AllToolBarAreas)
        self.action_start_video = QtWidgets.QAction('Start Video')
        self.action_start_video.setCheckable(True)
        toolbar.addAction(self.action_start_video)
        
        # Replace capture frame with continuous acquisition
        self.action_continuous_acquisition = QtWidgets.QAction('Start Continuous Acquisition')
        self.action_continuous_acquisition.setCheckable(True)
        toolbar.addAction(self.action_continuous_acquisition)
        
        self.addToolBar(QtCore.Qt.TopToolBarArea, toolbar)

        self.settings_dockwidget = CameraSettingsDockWidget()
        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea, self.settings_dockwidget)

        # Create central widget
        self.image_widget = ImageWidget()
        # FIXME: The camera hardware is currently transposing the image leading to this dirty hack
        self.image_widget.image_item.setOpts(False, axisOrder='row-major')
        self.setCentralWidget(self.image_widget)


class ContinuousAcquisitionDialog(QtWidgets.QDialog):
    """Dialog for setting up continuous acquisition parameters"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Continuous Acquisition Settings')
        self.setMinimumWidth(500)
        
        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)
        
        # File path section
        path_group = QtWidgets.QGroupBox('Save Location')
        path_layout = QtWidgets.QVBoxLayout()
        path_group.setLayout(path_layout)
        
        # Directory selection
        dir_layout = QtWidgets.QHBoxLayout()
        dir_label = QtWidgets.QLabel('Directory:')
        self.dir_line_edit = QtWidgets.QLineEdit()
        self.dir_line_edit.setPlaceholderText('Select directory for saved files...')
        self.dir_browse_button = QtWidgets.QPushButton('Browse...')
        self.dir_browse_button.clicked.connect(self._browse_directory)
        dir_layout.addWidget(dir_label)
        dir_layout.addWidget(self.dir_line_edit, 1)
        dir_layout.addWidget(self.dir_browse_button)
        path_layout.addLayout(dir_layout)
        
        # Filename prefix
        filename_layout = QtWidgets.QHBoxLayout()
        filename_label = QtWidgets.QLabel('Filename Prefix:')
        self.filename_line_edit = QtWidgets.QLineEdit()
        self.filename_line_edit.setPlaceholderText('frame')
        self.filename_line_edit.setText('frame')
        filename_layout.addWidget(filename_label)
        filename_layout.addWidget(self.filename_line_edit, 1)
        path_layout.addLayout(filename_layout)
        
        # Info label
        info_label = QtWidgets.QLabel('Files will be saved as: <prefix>.spc3')
        info_label.setStyleSheet('color: gray; font-style: italic;')
        path_layout.addWidget(info_label)
        
        layout.addWidget(path_group)
        
        # Button box
        self.button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)
    
    def _browse_directory(self):
        """Open directory browser"""
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            'Select Directory for Continuous Acquisition',
            self.dir_line_edit.text() or os.path.expanduser('~')
        )
        if directory:
            self.dir_line_edit.setText(directory)
    
    def get_settings(self):
        """Return the configured settings"""
        return {
            'directory': self.dir_line_edit.text(),
            'filename_prefix': self.filename_line_edit.text() or 'frame'
        }


class CameraSettingsDockWidget(QtWidgets.QDockWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowTitle('Camera settings')


class CameraGui(GuiBase):
    """ Main camera gui class.

    Example config for copy-paste:

    camera_gui:
        module.Class: 'camera.cameragui.CameraGui'
        connect:
            camera_logic: camera_logic

    """

    _camera_logic = Connector(name='camera_logic', interface='CameraLogic')

    sigStartStopVideoToggled = QtCore.Signal(bool)
    sigContinuousAcquisitionToggled = QtCore.Signal(bool, dict)  # (enabled, settings)
    sigBackgroundSubtractionToggled = QtCore.Signal(bool)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mw = None
        self._settings_dialog = None
        self._continuous_acq_dialog = None
        self._continuous_acq_settings = None

    def on_activate(self):
        """ Initializes all needed UI files and establishes the connectors.
        """
        logic = self._camera_logic()

        # Create main window
        self._mw = CameraMainWindow()
        
        # Create settings dialog
        self._settings_dialog = CameraSettingsDialog(self._mw)
        
        # Create continuous acquisition dialog
        self._continuous_acq_dialog = ContinuousAcquisitionDialog(self._mw)
        
        # Connect the action of the settings dialog with this module
        self._settings_dialog.accepted.connect(self._update_settings)
        self._settings_dialog.rejected.connect(self._keep_former_settings)
        self._settings_dialog.button_box.button(QtWidgets.QDialogButtonBox.Apply).clicked.connect(
            self._update_settings
        )

        self.control_dock_widget = CameraExposureDock()
        self.control_dock_widget.setFeatures(
            QtWidgets.QDockWidget.DockWidgetClosable | QtWidgets.QDockWidget.DockWidgetMovable
        )
        self.control_dock_widget.setAllowedAreas(QtCore.Qt.AllDockWidgetAreas)
        self._mw.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.control_dock_widget)
        
        self.control_dock_widget.visibilityChanged.connect(self._mw.action_view_controls.setChecked)
        self._mw.action_view_controls.triggered[bool].connect(self.control_dock_widget.setVisible)
        
        # Connect background subtraction signal
        self.control_dock_widget.sigBackgroundSubtractionToggled.connect(
            self._background_subtraction_toggled
        )

        # TODO: get advanced mode working
        # self.control_dock_widget.sigControlModeChanged.connect(
        #     self._update_settings
        # )
        self.control_dock_widget.sigIntegrationChanged.connect(
            self._update_settings
        )
        self.control_dock_widget.sigBinningChanged.connect(
            self._update_settings
        )

        # Fill in data from logic
        logic_busy = logic.module_state() == 'locked'
        self._mw.action_start_video.setChecked(logic_busy)
        self._mw.action_continuous_acquisition.setChecked(False)
        self._update_frame(logic.last_frame)
        self._keep_former_settings()

        # connect main window actions
        self._mw.action_start_video.triggered[bool].connect(self._start_video_clicked)
        self._mw.action_continuous_acquisition.triggered[bool].connect(
            self._continuous_acquisition_clicked
        )
        self._mw.action_show_settings.triggered.connect(lambda: self._settings_dialog.exec_())
        self._mw.action_save_frame.triggered.connect(self._save_frame)
        
        # connect update signals from logic
        logic.sigFrameChanged.connect(self._update_frame)
        logic.sigAcquisitionFinished.connect(self._acquisition_finished)
        
        # connect GUI signals to logic slots
        self.sigStartStopVideoToggled.connect(logic.toggle_video)


        self.sigContinuousAcquisitionToggled.connect(logic.toggle_continuous_acquisition)
        self.sigBackgroundSubtractionToggled.connect(logic.toggle_background_subtraction)
        
        self.show()

    def on_deactivate(self):
        """ De-initialisation performed during deactivation of the module.
        """
        logic = self._camera_logic()
        # disconnect all signals
        self.sigContinuousAcquisitionToggled.disconnect()
        self.sigStartStopVideoToggled.disconnect()
        self.sigBackgroundSubtractionToggled.disconnect()
        logic.sigAcquisitionFinished.disconnect(self._acquisition_finished)
        logic.sigFrameChanged.disconnect(self._update_frame)
        self._mw.action_save_frame.triggered.disconnect()
        self._mw.action_show_settings.triggered.disconnect()
        self._mw.action_continuous_acquisition.triggered.disconnect()
        self._mw.action_start_video.triggered.disconnect()
        self.control_dock_widget.sigBackgroundSubtractionToggled.disconnect()
        self._mw.close()

    def show(self):
        """Make window visible and put it above all other windows.
        """
        self._mw.show()
        self._mw.raise_()
        self._mw.activateWindow()

    def _update_settings(self):
        """ Write new settings from the gui to the file. """
        logic = self._camera_logic()
        # logic.set_integration(self.control_dock_widget.get_integration_value_ns())
        logic.set_binning(self.control_dock_widget.get_binning_value())

    def _keep_former_settings(self):
        """ Keep the old settings and restores them in the gui. """
        logic = self._camera_logic()
        self._settings_dialog.exposure_spinbox.setValue(logic.get_exposure())
        self._settings_dialog.gain_spinbox.setValue(logic.get_gain())

    def _continuous_acquisition_clicked(self, checked):
        """Handle continuous acquisition button click"""
        if checked:
            # Show dialog to get settings
            if self._continuous_acq_dialog.exec_() == QtWidgets.QDialog.Accepted:
                self._continuous_acq_settings = self._continuous_acq_dialog.get_settings()
                
                # Validate settings
                if not self._continuous_acq_settings['directory']:
                    QtWidgets.QMessageBox.warning(
                        self._mw,
                        'Invalid Settings',
                        'Please select a directory for saving files.'
                    )
                    self._mw.action_continuous_acquisition.setChecked(False)
                    return
                
                # Disable other controls
                self._mw.action_start_video.setDisabled(True)
                self._mw.action_show_settings.setDisabled(True)
                self._mw.action_continuous_acquisition.setText('Stop Continuous Acquisition')
                
                # Emit signal to start continuous acquisition
                self.sigContinuousAcquisitionToggled.emit(True, self._continuous_acq_settings)
            else:
                # User cancelled dialog
                self._mw.action_continuous_acquisition.setChecked(False)
        else:
            # Stop continuous acquisition
            self._mw.action_continuous_acquisition.setText('Start Continuous Acquisition')
            self._mw.action_start_video.setEnabled(True)
            self._mw.action_show_settings.setEnabled(True)
            self.sigContinuousAcquisitionToggled.emit(False, {})

    def _acquisition_finished(self):
        self._mw.action_start_video.setChecked(False)
        self._mw.action_start_video.setEnabled(True)
        self._mw.action_continuous_acquisition.setChecked(False)
        self._mw.action_continuous_acquisition.setEnabled(True)
        self._mw.action_continuous_acquisition.setText('Start Continuous Acquisition')
        self._mw.action_show_settings.setEnabled(True)

    def _start_video_clicked(self, checked):
        if checked:
            self._mw.action_show_settings.setDisabled(True)
            self._mw.action_continuous_acquisition.setDisabled(True)
            self._mw.action_start_video.setText('Stop Video')
        else:
            self._mw.action_start_video.setText('Start Video')
        self.sigStartStopVideoToggled.emit(checked)

    def _update_frame(self, frame_data):
        """
        """
        self._mw.image_widget.set_image(frame_data)

    def _background_subtraction_toggled(self, enabled):
        """Handle background subtraction toggle from control dock"""
        self.sigBackgroundSubtractionToggled.emit(enabled)
        if enabled:
            self.log.info('Background subtraction enabled')
        else:
            self.log.info('Background subtraction disabled')

    def _save_frame(self):
        logic = self._camera_logic()
        ds = TextDataStorage(root_dir=self.module_default_data_dir)
        timestamp = datetime.datetime.now()
        tag = logic.create_tag(timestamp)

        parameters = {}
        parameters['gain'] = logic.get_gain()
        parameters['exposure'] = logic.get_exposure()

        data = logic.last_frame
        if data is not None:
            file_path, _, _ = ds.save_data(data, metadata=parameters, nametag=tag,
                                       timestamp=timestamp, column_headers='Image (columns is X, rows is Y)')
            figure = logic.draw_2d_image(data, cbar_range=None)
            ds.save_thumbnail(figure, file_path=file_path.rsplit('.', 1)[0])
        else:
            self.log.error('No Data acquired. Nothing to save.')
        return