# -*- coding: utf-8 -*-
"""Custom camera GUI variant.

This is a copy of qudi's generic camera GUI with one targeted change:
- After a snap/capture finishes, optionally prompt to save the most recent
  SPC3 snap as a `.spc3` file to a predefined directory.

The original GUI in `qudi.gui.camera.cameragui` is left untouched.

Example config for copy-paste:

camera_gui:
    module.Class: 'camera.cameragui_SPC3.CameraGui'
    connect:
        camera_logic: camera_logic

Notes
-----
- Saving is manual (prompted after snap), not auto-save.
- Requires the connected camera hardware to implement
  `save_last_snap_to_file(filepath, n_frames=None)`.
"""

import os
import datetime

import numpy as np

from PySide2 import QtCore, QtWidgets, QtGui

from qudi.core.module import GuiBase
from qudi.core.connector import Connector
from qudi.util.widgets.plotting.image_widget import ImageWidget
from qudi.util.datastorage import TextDataStorage
from qudi.util.paths import get_artwork_dir
from qudi.gui.camera.camera_settings_dialog import CameraSettingsDialog
from qudi.logic.camera_logic import CameraLogic


class CameraMainWindow(QtWidgets.QMainWindow):
    """QMainWindow object for qudi CameraGui module"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Create menu bar
        menu_bar = QtWidgets.QMenuBar()
        menu = menu_bar.addMenu("File")

        self.action_load_spc3 = QtWidgets.QAction("Load SPC3...")
        try:
            path = os.path.join(get_artwork_dir(), "icons", "document-open")
            if os.path.exists(path):
                self.action_load_spc3.setIcon(QtGui.QIcon(path))
        except Exception:
            pass
        menu.addAction(self.action_load_spc3)

        menu.addSeparator()
        self.action_save_frame = QtWidgets.QAction("Save Frame")
        path = os.path.join(get_artwork_dir(), "icons", "document-save")
        self.action_save_frame.setIcon(QtGui.QIcon(path))
        menu.addAction(self.action_save_frame)
        menu.addSeparator()
        self.action_show_settings = QtWidgets.QAction("Settings")
        path = os.path.join(get_artwork_dir(), "icons", "configure")
        self.action_show_settings.setIcon(QtGui.QIcon(path))
        menu.addAction(self.action_show_settings)
        menu.addSeparator()
        self.action_close = QtWidgets.QAction("Close")
        path = os.path.join(get_artwork_dir(), "icons", "application-exit")
        self.action_close.setIcon(QtGui.QIcon(path))
        self.action_close.triggered.connect(self.close)
        menu.addAction(self.action_close)
        self.setMenuBar(menu_bar)

        # Create toolbar
        toolbar = QtWidgets.QToolBar()
        toolbar.setAllowedAreas(QtCore.Qt.AllToolBarAreas)
        self.action_start_video = QtWidgets.QAction("Start Video")
        self.action_start_video.setCheckable(True)
        toolbar.addAction(self.action_start_video)
        self.action_capture_frame = QtWidgets.QAction("Snap")
        self.action_capture_frame.setCheckable(True)
        toolbar.addAction(self.action_capture_frame)

        self.action_continuous = QtWidgets.QAction("Continuous")
        self.action_continuous.setCheckable(True)
        toolbar.addAction(self.action_continuous)

        self.action_background_subtraction = QtWidgets.QAction("Background Subtraction")
        self.action_background_subtraction.setCheckable(True)
        self.action_background_subtraction.setToolTip(
            "Subtract an averaged SPC3 background image from live video frames"
        )
        toolbar.addAction(self.action_background_subtraction)

        # SPC3: snap frame count control (NFrames)
        self.snap_frames_label = QtWidgets.QLabel("Snap Frames")
        self.snap_frames_spinbox = QtWidgets.QSpinBox()
        self.snap_frames_spinbox.setRange(1, 65534)
        self.snap_frames_spinbox.setValue(1)
        self.snap_frames_spinbox.setEnabled(False)
        self.snap_frames_label.setEnabled(False)
        self.snap_frames_spinbox.setToolTip(
            "Number of frames acquired per Snap (SPC3 only)"
        )

        # Snap frame browsing controls (enabled only for multi-frame snaps)
        self.snap_frame_label = QtWidgets.QLabel("Frame")
        self.snap_frame_spinbox = QtWidgets.QSpinBox()
        self.snap_frame_spinbox.setRange(0, 0)
        self.snap_frame_spinbox.setEnabled(False)
        self.snap_frame_label.setEnabled(False)
        toolbar.addSeparator()
        toolbar.addWidget(self.snap_frames_label)
        toolbar.addWidget(self.snap_frames_spinbox)
        toolbar.addSeparator()
        toolbar.addWidget(self.snap_frame_label)
        toolbar.addWidget(self.snap_frame_spinbox)
        self.addToolBar(QtCore.Qt.TopToolBarArea, toolbar)

        # Create central widget
        self.image_widget = ImageWidget()
        # FIXME: The camera hardware is currently transposing the image leading to this dirty hack
        self.image_widget.image_item.setOpts(False, axisOrder="row-major")
        self.setCentralWidget(self.image_widget)


class CameraGui(GuiBase):
    """Main camera gui class (custom save-on-snap variant)."""

    _camera_logic = Connector(name="camera_logic", interface=CameraLogic)

    sigStartStopVideoToggled = QtCore.Signal(bool)
    sigCaptureFrameTriggered = QtCore.Signal()
    sigContinuousToggled = QtCore.Signal(bool)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mw = None
        self._settings_dialog = None
        self._pending_snap_save_prompt = False
        self._snap_sequence = None
        self._loaded_spc3_filepath = None
        self._loaded_spc3_header = None
        self._last_spc3_open_dir = None

        self._bg_sub_enabled = False
        self._bg_sub_filepath = None
        self._bg_image = None
        self._bg_image_counts = None
        self._bg_sub_warned = False
        self._continuous_active = False
        self._supports_snap_frames = False

    def on_activate(self):
        """Initializes all needed UI files and establishes the connectors."""
        logic = self._camera_logic()

        # Create main window
        self._mw = CameraMainWindow()
        # Create settings dialog
        self._settings_dialog = CameraSettingsDialog(self._mw)
        # Connect the action of the settings dialog with this module
        self._settings_dialog.accepted.connect(self._update_settings)
        self._settings_dialog.rejected.connect(self._keep_former_settings)
        self._settings_dialog.button_box.button(
            QtWidgets.QDialogButtonBox.Apply
        ).clicked.connect(self._update_settings)

        # Fill in data from logic
        logic_busy = logic.module_state() == "locked"
        self._mw.action_start_video.setChecked(logic_busy)
        self._mw.action_capture_frame.setChecked(logic_busy)
        self._update_frame(logic.last_frame)
        self._keep_former_settings()

        # connect main window actions
        self._mw.action_start_video.triggered[bool].connect(self._start_video_clicked)
        self._mw.action_capture_frame.triggered.connect(self._capture_frame_clicked)
        self._mw.action_show_settings.triggered.connect(
            lambda: self._settings_dialog.exec_()
        )
        self._mw.action_save_frame.triggered.connect(self._save_frame)
        self._mw.action_load_spc3.triggered.connect(self._load_spc3_clicked)
        self._mw.action_background_subtraction.triggered[bool].connect(
            self._background_subtraction_toggled
        )
        self._mw.snap_frame_spinbox.valueChanged.connect(self._snap_frame_index_changed)
        self._mw.action_continuous.triggered[bool].connect(self._continuous_clicked)
        self._mw.snap_frames_spinbox.valueChanged.connect(self._snap_frames_changed)

        # connect update signals from logic
        logic.sigFrameChanged.connect(self._update_frame)
        logic.sigAcquisitionFinished.connect(self._acquisition_finished)

        # connect GUI signals to logic slots
        self.sigStartStopVideoToggled.connect(logic.toggle_video)
        self.sigCaptureFrameTriggered.connect(logic.capture_frame)
        self.sigContinuousToggled.connect(logic.toggle_continuous)

        cont_sig = getattr(logic, "sigContinuousStateChanged", None)
        if cont_sig is not None:
            try:
                cont_sig.connect(self._continuous_state_changed)
            except Exception:
                pass

        # Initial state
        self._continuous_state_changed(bool(getattr(logic, "continuous_active", False)))
        self._init_snap_frames_control()
        self.show()

    def on_deactivate(self):
        """De-initialisation performed during deactivation of the module."""
        logic = self._camera_logic()
        # disconnect all signals
        self.sigCaptureFrameTriggered.disconnect()
        self.sigStartStopVideoToggled.disconnect()
        self.sigContinuousToggled.disconnect()
        logic.sigAcquisitionFinished.disconnect(self._acquisition_finished)
        logic.sigFrameChanged.disconnect(self._update_frame)

        cont_sig = getattr(logic, "sigContinuousStateChanged", None)
        if cont_sig is not None:
            try:
                cont_sig.disconnect(self._continuous_state_changed)
            except Exception:
                pass

        self._mw.action_save_frame.triggered.disconnect()
        self._mw.action_load_spc3.triggered.disconnect()
        self._mw.action_background_subtraction.triggered.disconnect()
        self._mw.action_show_settings.triggered.disconnect()
        self._mw.action_capture_frame.triggered.disconnect()
        self._mw.action_start_video.triggered.disconnect()
        self._mw.action_continuous.triggered.disconnect()
        self._mw.snap_frame_spinbox.valueChanged.disconnect()
        self._mw.snap_frames_spinbox.valueChanged.disconnect()
        self._mw.close()

    def show(self):
        """Make window visible and put it above all other windows."""
        self._mw.show()
        self._mw.raise_()
        self._mw.activateWindow()

    def _update_settings(self):
        """Write new settings from the gui to the file."""
        logic = self._camera_logic()
        logic.set_exposure(self._settings_dialog.exposure_spinbox.value())
        logic.set_gain(self._settings_dialog.gain_spinbox.value())

    def _keep_former_settings(self):
        """Keep the old settings and restores them in the gui."""
        logic = self._camera_logic()
        self._settings_dialog.exposure_spinbox.setValue(logic.get_exposure())
        self._settings_dialog.gain_spinbox.setValue(logic.get_gain())

    def _capture_frame_clicked(self):
        if self._continuous_active:
            return
        self._mw.action_start_video.setDisabled(True)
        self._mw.action_capture_frame.setDisabled(True)
        self._mw.action_continuous.setDisabled(True)
        self._mw.action_show_settings.setDisabled(True)
        self._set_snap_frames_control_enabled(False)
        self._pending_snap_save_prompt = True
        self.sigCaptureFrameTriggered.emit()

    def _acquisition_finished(self):
        self._mw.action_start_video.setChecked(False)
        self._mw.action_start_video.setEnabled(True)
        self._mw.action_capture_frame.setChecked(False)
        self._mw.action_capture_frame.setEnabled(True)
        self._mw.action_show_settings.setEnabled(True)
        if not self._continuous_active:
            self._mw.action_continuous.setEnabled(True)

        self._set_snap_frames_control_enabled(
            self._supports_snap_frames
            and (self._camera_logic().module_state() == "idle")
        )

        # If this snap produced a multi-frame sequence, enable browsing.
        self._refresh_snap_sequence()

        if self._pending_snap_save_prompt:
            self._pending_snap_save_prompt = False
            self._prompt_save_spc3_after_snap()

    def _start_video_clicked(self, checked):
        if checked and self._continuous_active:
            # Don't allow live mode while continuous is running
            self._mw.action_start_video.blockSignals(True)
            try:
                self._mw.action_start_video.setChecked(False)
            finally:
                self._mw.action_start_video.blockSignals(False)
            return

        if checked:
            self._mw.action_show_settings.setDisabled(True)
            self._mw.action_capture_frame.setDisabled(True)
            self._mw.action_continuous.setDisabled(True)
            self._mw.action_start_video.setText("Stop Video")

            self._set_snap_frames_control_enabled(False)

            # Video/live mode overrides snap browsing.
            self._set_snap_browsing_enabled(False)
        else:
            self._mw.action_start_video.setText("Start Video")
            self._mw.action_continuous.setEnabled(True)
            self._set_snap_frames_control_enabled(
                self._supports_snap_frames
                and (self._camera_logic().module_state() == "idle")
            )
        self.sigStartStopVideoToggled.emit(checked)

    def _continuous_clicked(self, checked):
        self.sigContinuousToggled.emit(bool(checked))

    def _continuous_state_changed(self, active):
        self._continuous_active = bool(active)

        self._mw.action_continuous.blockSignals(True)
        try:
            self._mw.action_continuous.setChecked(self._continuous_active)
        finally:
            self._mw.action_continuous.blockSignals(False)

        if self._continuous_active:
            self._mw.action_continuous.setText("Stop Continuous")
            self._mw.action_start_video.setDisabled(True)
            self._mw.action_capture_frame.setDisabled(True)
            self._mw.action_show_settings.setDisabled(True)
            self._set_snap_browsing_enabled(False)
            self._set_snap_frames_control_enabled(False)
        else:
            self._mw.action_continuous.setText("Continuous")
            self._mw.action_start_video.setEnabled(True)
            self._mw.action_capture_frame.setEnabled(True)
            self._mw.action_show_settings.setEnabled(True)
            self._mw.action_continuous.setEnabled(True)
            self._set_snap_frames_control_enabled(
                self._supports_snap_frames
                and (self._camera_logic().module_state() == "idle")
            )

    def _set_snap_frames_control_enabled(self, enabled: bool):
        enabled = bool(enabled)
        self._mw.snap_frames_label.setEnabled(enabled)
        self._mw.snap_frames_spinbox.setEnabled(enabled)

    def _init_snap_frames_control(self):
        """Enable and initialize the Snap Frames control if the camera supports it."""
        logic = self._camera_logic()

        camera = getattr(logic, "_camera", None)
        camera = camera() if callable(camera) else None

        getter = getattr(logic, "get_snap_frames", None)
        setter = getattr(logic, "set_snap_frames", None)
        if callable(getter) and callable(setter):
            self._supports_snap_frames = True
            try:
                n = int(getter())
            except Exception:
                n = 1
            self._mw.snap_frames_spinbox.blockSignals(True)
            try:
                self._mw.snap_frames_spinbox.setValue(max(1, min(int(n), 65534)))
            finally:
                self._mw.snap_frames_spinbox.blockSignals(False)

            self._set_snap_frames_control_enabled(
                (not self._continuous_active) and (logic.module_state() == "idle")
            )
            return

        # Fallback: hardware supports API directly (older logic variants)
        cam_get = getattr(camera, "get_snap_frames", None)
        cam_set = getattr(camera, "set_snap_frames", None)
        if camera is not None and callable(cam_get) and callable(cam_set):
            self._supports_snap_frames = True
            try:
                n = int(cam_get())
            except Exception:
                n = 1
            self._mw.snap_frames_spinbox.blockSignals(True)
            try:
                self._mw.snap_frames_spinbox.setValue(max(1, min(int(n), 65534)))
            finally:
                self._mw.snap_frames_spinbox.blockSignals(False)

            self._set_snap_frames_control_enabled(
                (not self._continuous_active) and (logic.module_state() == "idle")
            )
            return

        self._supports_snap_frames = False
        self._set_snap_frames_control_enabled(False)

    def _snap_frames_changed(self, value):
        """Apply snap frame count to SPC3 hardware/logic."""
        if not self._supports_snap_frames:
            return

        logic = self._camera_logic()
        if logic.module_state() != "idle":
            # Revert to current value (best-effort).
            try:
                current = int(getattr(logic, "get_snap_frames")())
            except Exception:
                current = int(value)
            self._mw.snap_frames_spinbox.blockSignals(True)
            try:
                self._mw.snap_frames_spinbox.setValue(current)
            finally:
                self._mw.snap_frames_spinbox.blockSignals(False)
            return

        setter = getattr(logic, "set_snap_frames", None)
        if callable(setter):
            ok = bool(setter(int(value)))
            if not ok:
                self._init_snap_frames_control()
            return

        # Fallback: set directly on hardware
        camera = getattr(logic, "_camera", None)
        camera = camera() if callable(camera) else None
        cam_set = getattr(camera, "set_snap_frames", None)
        if callable(cam_set):
            ok = bool(cam_set(int(value)))
            if not ok:
                self._init_snap_frames_control()
            return

    def _update_frame(self, frame_data):
        if (
            self._bg_sub_enabled
            and self._mw.action_start_video.isChecked()
            and (frame_data is not None)
            and (self._bg_image is not None)
        ):
            try:
                arr = np.asarray(frame_data)
                bg = self._bg_image

                # If shapes don't match, attempt a simple transpose auto-fix.
                if arr.shape != bg.shape:
                    try:
                        bg_t = np.asarray(bg).T
                    except Exception:
                        bg_t = None
                    if bg_t is not None and arr.shape == bg_t.shape:
                        bg = bg_t
                        self._bg_image = bg_t
                    else:
                        if not self._bg_sub_warned:
                            self._bg_sub_warned = True
                            self.log.warning(
                                "Background subtraction skipped (shape mismatch): "
                                f"frame={arr.shape}, bg={self._bg_image.shape}"
                            )
                        self._mw.image_widget.set_image(frame_data)
                        return

                out = arr.astype(np.float32, copy=False) - bg
                out = np.clip(out, 0, None)

                self._mw.image_widget.set_image(out)
                return
            except Exception as e:
                # Best-effort: never auto-disable based on a single bad frame.
                if not self._bg_sub_warned:
                    self._bg_sub_warned = True
                    self.log.warning(
                        "Background subtraction skipped for this frame: "
                        f"{type(e).__name__}: {e}"
                    )
                self._mw.image_widget.set_image(frame_data)
                return

        self._mw.image_widget.set_image(frame_data)

    def _set_background_subtraction_enabled(self, enabled: bool):
        enabled = bool(enabled)
        self._bg_sub_enabled = enabled

        # Also propagate to logic so snap acquisitions (capture_frame) can apply it.
        try:
            logic = self._camera_logic()
            setter = getattr(logic, "set_background_subtraction", None)
            if callable(setter):
                if enabled:
                    setter(True, self._bg_image)
                else:
                    setter(False, None)
        except Exception:
            # GUI-side subtraction (live video) should still work even if the
            # logic doesn't implement or accept this hook.
            pass

        # Also propagate a counts-domain background image to the hardware so
        # other modules that talk to the camera directly (e.g. spad_optimize_logic)
        # can apply subtraction consistently.
        try:
            logic = self._camera_logic()
            camera = getattr(logic, "_camera", None)
            camera = camera() if callable(camera) else None
            cam_set = getattr(camera, "set_background_subtraction_counts", None)
            if callable(cam_set):
                if enabled:
                    cam_set(True, self._bg_image_counts)
                else:
                    cam_set(False, None)
        except Exception:
            pass

        self._mw.action_background_subtraction.blockSignals(True)
        try:
            self._mw.action_background_subtraction.setChecked(enabled)
        finally:
            self._mw.action_background_subtraction.blockSignals(False)

        if not enabled:
            self._bg_sub_filepath = None
            self._bg_image = None
            self._bg_image_counts = None
            self._bg_sub_warned = False

    def _background_subtraction_toggled(self, checked: bool):
        checked = bool(checked)
        if not checked:
            self._set_background_subtraction_enabled(False)
            return

        start_dir = self._last_spc3_open_dir
        if not start_dir:
            logic = self._camera_logic()
            camera = getattr(logic, "_camera", None)
            camera = camera() if callable(camera) else None
            get_dir = getattr(camera, "get_default_save_directory", None)
            if callable(get_dir):
                try:
                    start_dir = (get_dir() or "").strip() or None
                except Exception:
                    start_dir = None
        if not start_dir:
            start_dir = self.module_default_data_dir

        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self._mw,
            "Select Background SPC3 File",
            start_dir,
            "SPC3 Files (*.spc3);;All Files (*)",
        )
        if not path:
            self._set_background_subtraction_enabled(False)
            return

        path = os.path.normpath(str(path))
        self._last_spc3_open_dir = os.path.dirname(path)

        try:
            from qudi.hardware.camera.SPC3.spc import SPC3

            frames, _header = SPC3.ReadSPC3DataFile(path)

            if getattr(frames, "ndim", 0) == 4:
                seq = np.asarray(frames)[0]
            elif getattr(frames, "ndim", 0) == 3:
                seq = np.asarray(frames)
            elif getattr(frames, "ndim", 0) == 2:
                seq = np.asarray(frames)[None, ...]
            else:
                raise ValueError(
                    f"Unexpected frames array ndim={getattr(frames, 'ndim', None)}"
                )

            if seq.shape[0] < 1:
                raise ValueError("No frames found in background file")

            bg_counts = seq.astype(np.float32).mean(axis=0)
            if bg_counts.ndim != 2:
                raise ValueError(f"Unexpected background image ndim={bg_counts.ndim}")

            # Match background units to whatever the live frame display uses.
            logic = self._camera_logic()
            camera = getattr(logic, "_camera", None)
            camera = camera() if callable(camera) else None

            display_units = None
            if camera is not None:
                get_units = getattr(camera, "get_display_units", None)
                if callable(get_units):
                    try:
                        display_units = str(get_units())
                    except Exception:
                        display_units = None

            # Exposure time encoded in the SPC3 file header (best-effort).
            bg_exp_s = None
            try:
                hw_int = float(getattr(_header, "HwIntTime", 0.0) or 0.0)
                summed = float(getattr(_header, "SummedFrames", 1.0) or 1.0)
                if hw_int > 0 and summed > 0:
                    bg_exp_s = hw_int * summed
            except Exception:
                bg_exp_s = None

            # Current exposure of the connected camera (best-effort).
            cur_exp_s = None
            try:
                if camera is not None:
                    get_exp = getattr(camera, "get_exposure", None)
                    if callable(get_exp):
                        cur_exp_s = float(get_exp() or 0.0)
            except Exception:
                cur_exp_s = None

            # Counts-domain background scaled to current exposure (for snap stacks).
            bg_counts_scaled = bg_counts
            if bg_exp_s and cur_exp_s and bg_exp_s > 0 and cur_exp_s > 0:
                bg_counts_scaled = bg_counts * (cur_exp_s / bg_exp_s)

            bg = bg_counts
            if display_units == "cps":
                if bg_exp_s and bg_exp_s > 0:
                    bg = bg_counts / float(bg_exp_s)
                else:
                    self.log.warning(
                        "Background file has no valid exposure in header; "
                        "background will be treated as cps but may be mis-scaled."
                    )
            elif display_units == "counts":
                # If the live display is in raw counts, scale the background to the
                # current exposure so subtraction is meaningful across mismatched files.
                bg = bg_counts_scaled

            self.log.info(
                "Background loaded for subtraction: "
                f"path={path}, n_frames={int(seq.shape[0])}, shape={tuple(bg.shape)}, "
                f"display_units={display_units or 'unknown'}, bg_exp_s={bg_exp_s}"
            )

        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self._mw,
                "Background Subtraction",
                f"Failed to load background SPC3 file:\n{path}\n\n{type(e).__name__}: {e}",
            )
            self._set_background_subtraction_enabled(False)
            return

        self._bg_sub_filepath = path
        self._bg_image = bg
        self._bg_image_counts = bg_counts_scaled
        self._bg_sub_warned = False
        self._set_background_subtraction_enabled(True)

        self.log.info(f"Background subtraction enabled. File: {path}")

    def _set_snap_browsing_enabled(self, enabled, n_frames=0):
        enabled = bool(enabled) and int(n_frames) > 1
        self._mw.snap_frame_label.setEnabled(enabled)
        self._mw.snap_frame_spinbox.setEnabled(enabled)
        if enabled:
            self._mw.snap_frame_spinbox.setRange(0, int(n_frames) - 1)
        else:
            self._mw.snap_frame_spinbox.setRange(0, 0)
            self._mw.snap_frame_spinbox.setValue(0)

    def _refresh_snap_sequence(self):
        """Try to fetch the last snap stack from hardware (SPC3 only)."""
        logic = self._camera_logic()

        camera = getattr(logic, "_camera", None)
        camera = camera() if callable(camera) else None

        get_seq = getattr(camera, "get_last_snap_sequence", None)
        if camera is None or not callable(get_seq):
            self._snap_sequence = None
            self._set_snap_browsing_enabled(False)
            return

        seq = get_seq()
        if seq is None:
            self._snap_sequence = None
            self._set_snap_browsing_enabled(False)
            return

        try:
            n_frames = int(seq.shape[0])
        except Exception:
            self._snap_sequence = None
            self._set_snap_browsing_enabled(False)
            return

        self._snap_sequence = seq

        # We're now showing a hardware snap sequence (not a loaded file).
        self._loaded_spc3_filepath = None
        self._loaded_spc3_header = None

        self._set_snap_browsing_enabled(True, n_frames=n_frames)

        # Default to the last frame (what the logic already shows).
        if n_frames > 1:
            self._mw.snap_frame_spinbox.blockSignals(True)
            try:
                self._mw.snap_frame_spinbox.setValue(n_frames - 1)
            finally:
                self._mw.snap_frame_spinbox.blockSignals(False)

    def _snap_frame_index_changed(self, idx):
        if self._snap_sequence is None:
            return
        try:
            idx = int(idx)
            idx = max(0, min(idx, int(self._snap_sequence.shape[0]) - 1))
            frame = self._snap_sequence[idx]
        except Exception:
            return

        # Snap browsing frames come straight from the hardware snap stack and are
        # raw counts. For a consistent display (and correct background subtraction),
        # scale to match the camera display units before rendering.
        logic = self._camera_logic()
        camera = getattr(logic, "_camera", None)
        camera = camera() if callable(camera) else None

        display_units = None
        if camera is not None:
            get_units = getattr(camera, "get_display_units", None)
            if callable(get_units):
                try:
                    display_units = str(get_units())
                except Exception:
                    display_units = None

        out = frame
        if display_units == "cps":
            exp_s = None
            try:
                exp_s = float(logic.get_exposure() or 0.0)
            except Exception:
                exp_s = None
            if exp_s and exp_s > 0:
                out = np.asarray(frame).astype(np.float64, copy=False) / float(exp_s)

        # Apply background subtraction for snap browsing (independent of live video).
        if self._bg_sub_enabled and (out is not None) and (self._bg_image is not None):
            try:
                arr = np.asarray(out)
                bg = self._bg_image

                if arr.shape != bg.shape:
                    bg_t = None
                    try:
                        bg_t = np.asarray(bg).T
                    except Exception:
                        bg_t = None
                    if bg_t is not None and arr.shape == bg_t.shape:
                        bg = bg_t
                        self._bg_image = bg_t
                    else:
                        if not self._bg_sub_warned:
                            self._bg_sub_warned = True
                            self.log.warning(
                                "Background subtraction skipped (shape mismatch): "
                                f"frame={arr.shape}, bg={self._bg_image.shape}"
                            )
                        self._mw.image_widget.set_image(out)
                        return

                arr_f = arr.astype(np.float32, copy=False)
                out_sub = arr_f - bg
                out_sub = np.clip(out_sub, 0, None)
                self._mw.image_widget.set_image(out_sub)
                return
            except Exception as e:
                if not self._bg_sub_warned:
                    self._bg_sub_warned = True
                    self.log.warning(
                        "Background subtraction skipped for this frame: "
                        f"{type(e).__name__}: {e}"
                    )

        self._mw.image_widget.set_image(out)

    def _load_spc3_clicked(self):
        """Load an SPC3 acquisition file from disk and enable frame browsing."""
        start_dir = self._last_spc3_open_dir
        if not start_dir:
            logic = self._camera_logic()
            camera = getattr(logic, "_camera", None)
            camera = camera() if callable(camera) else None
            get_dir = getattr(camera, "get_default_save_directory", None)
            if callable(get_dir):
                try:
                    start_dir = (get_dir() or "").strip() or None
                except Exception:
                    start_dir = None
        if not start_dir:
            start_dir = self.module_default_data_dir

        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self._mw,
            "Open SPC3 File",
            start_dir,
            "SPC3 Files (*.spc3);;All Files (*)",
        )
        if not path:
            return

        self._last_spc3_open_dir = os.path.dirname(path)
        self._load_spc3_file(path)

    def _load_spc3_file(self, filepath: str):
        filepath = os.path.normpath(str(filepath))
        if not os.path.exists(filepath):
            QtWidgets.QMessageBox.warning(
                self._mw,
                "Load Error",
                f"File not found:\n{filepath}",
            )
            return

        try:
            from qudi.hardware.camera.SPC3.spc import SPC3

            frames, header = SPC3.ReadSPC3DataFile(filepath)
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self._mw,
                "Load Error",
                f"Failed to load SPC3 file:\n{filepath}\n\n{type(e).__name__}: {e}",
            )
            return

        try:
            # ReadSPC3DataFile returns (counters, frames, rows, cols) in the common case.
            if getattr(frames, "ndim", 0) == 4:
                seq = frames[0]
            elif getattr(frames, "ndim", 0) == 3:
                seq = frames
            elif getattr(frames, "ndim", 0) == 2:
                seq = frames[None, ...]
            else:
                raise ValueError(
                    f"Unexpected frames array ndim={getattr(frames, 'ndim', None)}"
                )

            n_frames = int(seq.shape[0])
            if n_frames < 1:
                raise ValueError("No frames found in file")
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self._mw,
                "Load Error",
                f"SPC3 file content is not understood:\n{filepath}\n\n{type(e).__name__}: {e}",
            )
            return

        self._loaded_spc3_filepath = filepath
        self._loaded_spc3_header = header

        self._snap_sequence = seq
        self._set_snap_browsing_enabled(True, n_frames=n_frames)

        # Default to the last frame.
        self._mw.snap_frame_spinbox.blockSignals(True)
        try:
            self._mw.snap_frame_spinbox.setValue(n_frames - 1)
        finally:
            self._mw.snap_frame_spinbox.blockSignals(False)

        try:
            self._update_frame(self._snap_sequence[n_frames - 1])
        except Exception:
            pass

    def _prompt_save_spc3_after_snap(self):
        """Optionally save the most recent SPC3 snap buffer as a .spc3 file and/or averaged image."""
        logic = self._camera_logic()

        camera = getattr(logic, "_camera", None)
        camera = camera() if callable(camera) else None

        save_method = getattr(camera, "save_last_snap_to_file", None)
        can_save_spc3 = camera is not None and callable(save_method)
        can_save_avg = self._snap_sequence is not None

        if not can_save_spc3 and not can_save_avg:
            return

        # Build a dialog with checkboxes for both save options.
        dlg = QtWidgets.QDialog(self._mw)
        dlg.setWindowTitle("Snap Complete")
        layout = QtWidgets.QVBoxLayout(dlg)
        layout.addWidget(QtWidgets.QLabel("Snap acquisition complete.\n\nSelect what to save:"))

        cb_spc3 = QtWidgets.QCheckBox("Save as .spc3 file")
        cb_spc3.setChecked(can_save_spc3)
        cb_spc3.setEnabled(can_save_spc3)
        layout.addWidget(cb_spc3)

        bg_suffix = " (with background subtraction)" if self._bg_sub_enabled else ""
        cb_avg = QtWidgets.QCheckBox(f"Save averaged image{bg_suffix} (PNG + DAT)")
        cb_avg.setChecked(can_save_avg)
        cb_avg.setEnabled(can_save_avg)
        layout.addWidget(cb_avg)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return

        if can_save_spc3 and cb_spc3.isChecked():
            directory = ""
            get_dir = getattr(camera, "get_default_save_directory", None)
            if callable(get_dir):
                directory = (get_dir() or "").strip()
            if not directory:
                directory = self.module_default_data_dir

            os.makedirs(directory, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            stem = os.path.join(directory, f"spc3_snap_{ts}")
            ok = bool(save_method(stem))
            if not ok:
                QtWidgets.QMessageBox.warning(
                    self._mw,
                    "Save Error",
                    "Failed to save .spc3 file.\n\nCheck log for details.",
                )

        if can_save_avg and cb_avg.isChecked():
            self._save_snap_averaged_image()

    def _save_snap_averaged_image(self):
        """Save the averaged snap image (PNG + DAT), mirroring the Save Frame logic."""
        if self._snap_sequence is None:
            self.log.error("No snap sequence available. Nothing to save.")
            return

        logic = self._camera_logic()
        camera = getattr(logic, "_camera", None)
        camera = camera() if callable(camera) else None

        # Average raw counts over all frames.
        avg = np.asarray(self._snap_sequence).astype(np.float64).mean(axis=0)

        # Convert to display units (same as _snap_frame_index_changed).
        display_units = None
        if camera is not None:
            get_units = getattr(camera, "get_display_units", None)
            if callable(get_units):
                try:
                    display_units = str(get_units())
                except Exception:
                    display_units = None

        if display_units == "cps":
            exp_s = None
            try:
                exp_s = float(logic.get_exposure() or 0.0)
            except Exception:
                exp_s = None
            if exp_s and exp_s > 0:
                avg = avg / float(exp_s)

        # Apply background subtraction (same logic as _snap_frame_index_changed).
        if self._bg_sub_enabled and self._bg_image is not None:
            try:
                bg = self._bg_image
                if avg.shape != bg.shape:
                    bg_t = np.asarray(bg).T
                    if avg.shape == bg_t.shape:
                        bg = bg_t
                        self._bg_image = bg_t
                    else:
                        self.log.warning(
                            "Background subtraction skipped when saving averaged image "
                            f"(shape mismatch): avg={avg.shape}, bg={self._bg_image.shape}"
                        )
                        bg = None
                if bg is not None:
                    avg = np.clip(avg - bg, 0, None)
            except Exception as e:
                self.log.warning(
                    f"Background subtraction skipped when saving averaged image: "
                    f"{type(e).__name__}: {e}"
                )

        try:
            ds = TextDataStorage(root_dir=self.module_default_data_dir)
            timestamp = datetime.datetime.now()
            tag = logic.create_tag(timestamp)

            parameters = {
                "gain": logic.get_gain(),
                "exposure": logic.get_exposure(),
                "n_frames_averaged": int(self._snap_sequence.shape[0]),
                "background_subtraction": self._bg_sub_enabled,
            }

            file_path, _, _ = ds.save_data(
                avg,
                metadata=parameters,
                nametag=tag,
                timestamp=timestamp,
                column_headers="Averaged Image (columns is X, rows is Y)",
            )
            figure = logic.draw_2d_image(avg, cbar_range=None)
            ds.save_thumbnail(figure, file_path=file_path.rsplit(".", 1)[0])
            self.log.info(f"Averaged snap image saved to: {file_path}")
        except Exception as e:
            self.log.error(f"Failed to save averaged image: {type(e).__name__}: {e}")
            QtWidgets.QMessageBox.warning(
                self._mw,
                "Save Error",
                f"Failed to save averaged image.\n\n{type(e).__name__}: {e}",
            )

    def _save_frame(self):
        logic = self._camera_logic()
        ds = TextDataStorage(root_dir=self.module_default_data_dir)
        timestamp = datetime.datetime.now()
        tag = logic.create_tag(timestamp)

        parameters = {}
        parameters["gain"] = logic.get_gain()
        parameters["exposure"] = logic.get_exposure()

        data = logic.last_frame
        if data is not None:
            file_path, _, _ = ds.save_data(
                data,
                metadata=parameters,
                nametag=tag,
                timestamp=timestamp,
                column_headers="Image (columns is X, rows is Y)",
            )
            figure = logic.draw_2d_image(data, cbar_range=None)
            ds.save_thumbnail(figure, file_path=file_path.rsplit(".", 1)[0])
        else:
            self.log.error("No Data acquired. Nothing to save.")
        return
