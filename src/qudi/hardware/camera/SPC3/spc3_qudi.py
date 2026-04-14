# -*- coding: utf-8 -*-

"""
Qudi hardware module for the MPD SPC3 SPAD camera.

Wraps the vendor-provided SPC3 Python SDK (spc.py) and exposes it through the
qudi CameraInterface.  spc.py must NOT be modified — all adaptation happens here.

---

Copyright (c) 2021, the qudi developers. See the AUTHORS.md file at the top-level
directory of this distribution and on
<https://github.com/Ulm-IQO/qudi-iqo-modules/>

This file is part of qudi.

Qudi is free software: you can redistribute it and/or modify it under the terms of
the GNU Lesser General Public License as published by the Free Software Foundation,
either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
PURPOSE.  See the GNU Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public License along with
qudi.  If not, see <https://www.gnu.org/licenses/>.
"""

import os
import time
import struct
import numpy as np
from ctypes import (
    c_int,
    c_short,
    c_void_p,
    c_uint32,
    c_uint16,
    POINTER,
    byref,
)

from qudi.core.configoption import ConfigOption
from qudi.interface.camera_interface import CameraInterface
from qudi.hardware.camera.SPC3.spc import SPC3


class SPC3_Qudi(CameraInterface):
    """Qudi hardware module for the MPD SPC3 SPAD camera.

    Example config for copy-paste (matches SPUD202603.cfg):

    camera_SPC3:
        module.Class: 'camera.SPC3.spc3_qudi.SPC3_Qudi'
        options:
            camera_mode: 'Advanced'    # 'Normal' or 'Advanced'
            exposure: 1040             # HIT in clock cycles (10 ns each)
            nframes: 1                 # Frames per snap acquisition (1-65534)
            nintegframes: 1            # Temporal binning: integrated frames per output (1-65534)
            ncounters: 1               # Counters per pixel (1-3)
            force8bit: 'Disabled'      # 'Enabled' or 'Disabled' (Advanced mode only)
            half_array: 'Enabled'      # 'Enabled' (32x32) or 'Disabled' (32x64)
            signed_data: 'Disabled'    # 'Enabled' or 'Disabled'
            trigger_mode: 'no_trigger'       # 'no_trigger' | 'single_trigger' | 'multiple_trigger'
            trigger_frames_per_pulse: 1      # Frames per SYNC_IN pulse (1-100, multiple_trigger only)
            gate_mode: 'off'                 # 'off' | 'coarse' (counter 1 only, Advanced mode)
            coarse_gate_start: 0             # Gate ON start in clock cycles (10 ns each)
            coarse_gate_stop: 100            # Gate ON stop in clock cycles (10 ns each)

    Additional optional config keys (not required, sensible defaults apply):
            display_units: 'counts'          # 'counts' or 'cps'
            save_directory: ''               # Pre-populated save directory in GUI

    Unit convention
    ---------------
    - ALL public time values (exposure, integration) are in **seconds**.
    - The config ``exposure`` parameter is in **clock cycles** (10 ns each).
    - Internally ``SetCameraPar`` uses clock cycles for the HIT parameter.
    - ``exposure_seconds = NIntegFrames × HIT_cycles × 10 ns``
    """

    # ── Config options ─────────────────────────────────────────────────
    _camera_mode = ConfigOption("camera_mode", "Advanced")
    _cfg_exposure = ConfigOption("exposure", 1040)  # clock cycles
    _cfg_nframes = ConfigOption("nframes", 1)
    _cfg_nintegframes = ConfigOption("nintegframes", 1)
    _cfg_ncounters = ConfigOption("ncounters", 1)
    _cfg_force8bit = ConfigOption("force8bit", "Disabled")
    _cfg_half_array = ConfigOption("half_array", "Enabled")
    _cfg_signed_data = ConfigOption("signed_data", "Disabled")
    _cfg_display_units = ConfigOption("display_units", "counts")
    _cfg_trigger_mode = ConfigOption("trigger_mode")  # required
    _cfg_trigger_frames_per_pulse = ConfigOption("trigger_frames_per_pulse")  # required
    _cfg_save_directory = ConfigOption("save_directory", "")
    _cfg_gate_mode = ConfigOption("gate_mode")  # required
    _cfg_coarse_gate_start = ConfigOption("coarse_gate_start")  # required
    _cfg_coarse_gate_stop = ConfigOption("coarse_gate_stop")  # required

    # ── Constants ──────────────────────────────────────────────────────
    _HIT_NORMAL = 1040  # Fixed HIT for Normal mode (clock cycles)
    _CLOCK_PERIOD = 10e-9  # 10 ns per clock cycle
    _NROWS = 32  # Pixel array is always 32 rows
    _TRIGGER_WAIT_TIMEOUT_S = 60.0
    _LIVE_THROTTLE_S = 0.01

    # ══════════════════════════════════════════════════════════════════
    #  Module lifecycle
    # ══════════════════════════════════════════════════════════════════

    def on_activate(self):
        """Initialisation performed during activation of the module."""

        # ── Resolve DLL path ───────────────────────────────────────────
        # spc.py locates the DLL via the class attribute ``lib_root_dir``.
        # Override it so the path is absolute and independent of the
        # working directory qudi happens to run from.
        SPC3.lib_root_dir = os.path.join(os.path.dirname(__file__), "lib")

        # ── Parse binary config options ────────────────────────────────
        self._force8bit = self._to_state(self._cfg_force8bit, "force8bit")
        self._half_array = self._to_state(self._cfg_half_array, "half_array")
        self._signed_data = self._to_state(self._cfg_signed_data, "signed_data")

        # ── Derived geometry ───────────────────────────────────────────
        self._ncols = 32 if self._half_array else 64

        # ── Internal state from config ─────────────────────────────────
        self._hit = int(self._cfg_exposure)  # HIT in clock cycles
        self._NFrames = int(self._cfg_nframes)
        self._NIntegFrames = int(self._cfg_nintegframes)
        self._NCounters = int(self._cfg_ncounters)
        self._display_units = str(self._cfg_display_units)
        self._trigger_mode = str(self._cfg_trigger_mode)
        self._trigger_frames_per_pulse = max(
            1, min(int(self._cfg_trigger_frames_per_pulse), 100)
        )
        gate_mode_raw = str(self._cfg_gate_mode).strip().lower()
        if gate_mode_raw not in ("off", "coarse"):
            raise ValueError(
                "gate_mode must be one of {'off','coarse'} (case-insensitive), "
                f"got {self._cfg_gate_mode!r}"
            )
        self._gate_mode = gate_mode_raw
        self._coarse_gate_start = int(self._cfg_coarse_gate_start)
        self._coarse_gate_stop = int(self._cfg_coarse_gate_stop)

        # ── Acquisition state flags ────────────────────────────────────
        self._live = False
        self._acquiring = False
        self._continuous = False

        # ── Cached frames for GUI ─────────────────────────────────────
        self._last_live_frame = None
        self._last_frame = None
        self._last_live_ts = 0.0

        # ── Cached snap stack for browsing (counter, frame, row, col) ─
        self._last_snap_frames = None

        # ── Loaded-file viewer state ───────────────────────────────────
        self._loaded_frames = None
        self._loaded_header = None
        self._loaded_filepath = None

        # ── Continuous trigger logging state ───────────────────────────
        self._cont_waiting_for_trigger = False

        # ── Construct SPC3 SDK object ──────────────────────────────────
        mode = (
            SPC3.CameraMode.ADVANCED
            if self._camera_mode == "Advanced"
            else SPC3.CameraMode.NORMAL
        )
        try:
            self._spc = SPC3(mode)
        except Exception as e:
            self.log.error(f"Failed to initialise SPC3 camera: {e}")
            return

        if self._camera_mode == "Advanced":
            self._spc.SetAdvancedMode(SPC3.State.ENABLED)

        # Step 1: Send camera parameters and commit so that HIT is
        # established before the SDK validates gate ranges.
        self._spc.SetCameraPar(
            self._effective_hit(),
            self._NFrames,
            self._NIntegFrames,
            self._NCounters,
            self._force8bit,
            self._half_array,
            self._signed_data,
        )
        self._spc.ApplySettings()

        # Step 2: Apply trigger and gate settings, then commit again.
        self._apply_trigger_settings()
        self._apply_gate_settings()
        self._spc.ApplySettings()

        # ── Log summary ───────────────────────────────────────────────
        exp_s = self._get_exposure_seconds()
        hit_us = self._effective_hit() * self._CLOCK_PERIOD * 1e6
        self.log.info(
            f"SPC3 activated ({self._camera_mode} mode): "
            f"HIT={self._effective_hit()} cycles ({hit_us:.2f} µs), "
            f"NInteg={self._NIntegFrames}, exposure={exp_s * 1e3:.2f} ms, "
            f"NFrames (snap)={self._NFrames}, "
            f"array={self._NROWS}×{self._ncols}, "
            f"trigger={self._trigger_mode} (fps={self._trigger_frames_per_pulse}), "
            f"gate={self._gate_mode}"
        )

    def on_deactivate(self):
        """Deinitialisation performed during deactivation of the module."""
        if self._live:
            try:
                self._spc.LiveSetModeOFF()
            except Exception:
                pass
            self._live = False

        if self._continuous:
            try:
                self._spc.ContAcqToFileStop()
            except Exception:
                pass
            self._continuous = False

        self._acquiring = False

        try:
            self._spc.Destr()
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════════
    #  CameraInterface — required abstract methods
    # ══════════════════════════════════════════════════════════════════

    def get_name(self):
        """Return an identifier for the camera."""
        try:
            cam_id, serial = self._spc.GetSerial()
            return f"SPC3 {serial}"
        except Exception:
            return "SPC3"

    def get_size(self):
        """Return image size as (rows, cols)."""
        return self._NROWS, self._ncols

    def support_live_acquisition(self):
        """SPC3 supports free-running live mode."""
        return True

    def start_live_acquisition(self):
        """Start free-running live acquisition."""
        if self._acquiring or self._continuous:
            self.log.error("Cannot start live: acquisition already in progress")
            return False
        try:
            self._spc.LiveSetModeON()
            self._live = True
            return True
        except Exception as e:
            self.log.error(f"Failed to start live acquisition: {e}")
            return False

    def start_single_acquisition(self):
        """Perform a snap acquisition.

        Executes: SnapPrepare → (wait for trigger) → SnapAcquire → extract buffer.

        @return bool: True on success, False otherwise.
        """
        if self._live:
            self.log.error("Cannot snap: live mode is active")
            return False
        if self._acquiring:
            self.log.error("Cannot snap: acquisition already in progress")
            return False

        try:
            self._acquiring = True

            # Ensure all settings (gate, trigger) are committed
            self._commit_settings()

            # Snapshot the gate settings that were applied to this acquisition.
            self._last_acq_gate_mode = self._gate_mode
            self._last_acq_coarse_gate_start = self._coarse_gate_start
            self._last_acq_coarse_gate_stop = self._coarse_gate_stop

            # Prepare camera for snap
            self._spc.SnapPrepare()

            # Wait for external trigger if configured (with timeout).
            if self._trigger_mode in ("single_trigger", "multiple_trigger"):
                self.log.info(
                    f"Waiting for external trigger ({self._trigger_mode}, "
                    f"timeout={self._TRIGGER_WAIT_TIMEOUT_S:.1f}s)..."
                )
                if not self._wait_for_trigger(self._TRIGGER_WAIT_TIMEOUT_S):
                    raise TimeoutError("No external trigger received")
                self.log.info("Trigger received")

            # Acquire (blocks until all frames are downloaded)
            self._spc.SnapAcquire()

            # Extract frames from the camera.
            # NOTE: The SDK's internal snap buffer layout (returned by
            # SPC3_Get_Image_Buffer) has proven unreliable to decode robustly
            # across firmware/SDK variants (dtype/stride/padding quirks,
            # especially with Half_array). The old, working module used
            # SPC3_Get_Img_Position per frame/counter; that path is slower but
            # robust and matches the live-mode geometry.
            frames = self._snap_get_frames_by_position()

            # Cache a representative 2-D image for the generic camera GUI.
            # BufferToFrames returns (counters, frames, rows, cols).
            self._last_frame = self._select_display_frame(frames)

            # Cache the full stack so the GUI can browse multi-frame snaps.
            # Keep the same shape as returned by the SDK wrapper:
            # (counters, frames, rows, cols)
            self._last_snap_frames = np.asarray(frames).copy()

            self._acquiring = False
            self.log.info(f"Snap complete: shape={frames.shape}, dtype={frames.dtype}")
            return True

        except Exception as e:
            self._acquiring = False
            self.log.error(f"Snap acquisition failed: {type(e).__name__}: {e}")
            return False

    def get_last_snap_sequence(self, counter_index=0):
        """Return last snap as a 3-D stack for browsing.

        @param int counter_index: which counter to view (default 0)
        @return numpy.ndarray|None: shape (frames, rows, cols) or None if unavailable
        """
        if self._last_snap_frames is None:
            return None

        arr = np.asarray(self._last_snap_frames)
        if arr.ndim == 4:
            c = int(counter_index)
            c = max(0, min(c, arr.shape[0] - 1))
            return arr[c]
        if arr.ndim == 3:
            return arr
        return None

    def _snap_get_frames_by_position(self):
        """Extract snap frames via SPC3_Get_Img_Position (robust path).

        Returns:
            numpy.ndarray: shape (counters, frames, rows, cols)

        This matches the approach used by the known-good legacy module.
        It avoids assumptions about the internal snap buffer layout.
        """

        num_frames = int(
            getattr(self._spc, "_snap_num_frames", self._NFrames) or self._NFrames
        )
        num_counters = int(
            getattr(self._spc, "_num_counters", self._NCounters) or self._NCounters
        )
        num_pixels = int(
            getattr(self._spc, "_num_pixels", 0) or (1024 if self._half_array else 2048)
        )

        # SDK expects a buffer of at least 4kB. The vendor wrapper uses
        # row_size * _num_rows (typically 32 * 64 = 2048) elements.
        row_size = int(getattr(self._spc, "row_size", 32) or 32)
        num_rows_raw = int(getattr(self._spc, "_num_rows", 64) or 64)
        buf_len = row_size * num_rows_raw

        # The C signature is effectively:
        #   int SPC3_Get_Img_Position(void* h, uint16_t* Img, uint32_t pos, uint16_t counter)
        # Use uint16 for compatibility (also works for 8-bit mode; values are truncated).
        f = self._spc.dll.SPC3_Get_Img_Position
        f.argtypes = [
            c_void_p,
            np.ctypeslib.ndpointer(dtype=np.uint16, ndim=1, flags="C_CONTIGUOUS"),
            c_uint32,
            c_uint16,
        ]
        f.restype = c_int

        frames_out = np.empty(
            (num_counters, num_frames, self._NROWS, self._ncols), dtype=np.uint16
        )

        for counter_idx in range(1, num_counters + 1):
            for frame_idx in range(1, num_frames + 1):
                data = np.zeros(buf_len, dtype=np.uint16)
                ec = f(self._spc.c_handle, data, frame_idx, counter_idx)
                self._spc._checkError(ec)

                # BufferToFrames may see padding (e.g. Half_array) and interpret
                # the raw buffer as multiple frames. We always take the first.
                reshaped = SPC3.BufferToFrames(data, num_pixels, 1)
                img2d = np.asarray(reshaped)[0, 0]
                frames_out[counter_idx - 1, frame_idx - 1] = img2d

        return frames_out

    def stop_acquisition(self):
        """Stop live or single acquisition."""
        if self._live:
            try:
                self._spc.LiveSetModeOFF()
            except Exception as e:
                self.log.error(f"Failed to stop live acquisition: {e}")
        self._live = False
        self._acquiring = False
        return True

    def get_acquired_data(self):
        """Return the current live frame (counter 1) for GUI display.

        During continuous acquisition the last cached live frame is returned as
        a static preview.
        """
        frame = None

        if self._live:
            # Guard against extremely fast polling intervals (CameraLogic uses a QTimer in ms).
            # If called too frequently, return the cached frame instead of hammering the SDK.
            now = time.monotonic()
            if (
                self._last_live_frame is None
                or (now - self._last_live_ts) >= self._LIVE_THROTTLE_S
            ):
                try:
                    # Vendor SDK LiveGetImg returns a single-counter stack with shape
                    # (frames, rows, cols). With default live acquisition it's 1 frame.
                    live_stack = self._spc.LiveGetImg()
                    if live_stack.ndim == 3:
                        frame = live_stack[0]
                    else:
                        frame = live_stack
                    self._last_live_frame = np.array(frame, copy=True)
                    self._last_live_ts = now
                except Exception as e:
                    self.log.error(f"LiveGetImg failed: {e}")
            if frame is None and self._last_live_frame is not None:
                frame = self._last_live_frame.copy()

        if frame is None:
            # When not live, show last snap frame if available.
            if self._last_frame is not None:
                frame = self._last_frame.copy()
            else:
                frame = np.zeros((self._NROWS, self._ncols), dtype=np.uint16)

        # Scale to counts per second if requested
        if self._display_units == "cps":
            exp_s = self._get_exposure_seconds()
            if exp_s > 0:
                frame = frame.astype(np.float64) / exp_s

        # Ensure 2-D for GUI display
        if frame.ndim == 1:
            frame = frame.reshape(self._NROWS, self._ncols)

        return frame

    @staticmethod
    def _select_display_frame(frames):
        """Pick a single 2-D frame from an SPC3 snap buffer.

        Expected input shape is (counters, frames, rows, cols).
        """
        arr = np.asarray(frames)
        if arr.ndim == 4:
            return arr[0, -1]
        if arr.ndim == 3:
            return arr[-1]
        if arr.ndim == 2:
            return arr
        raise ValueError(f"Unexpected frame array ndim={arr.ndim}")

    def _is_triggered(self):
        """Correct trigger polling (work around SDK wrapper bug in spc.py)."""
        try:
            f = self._spc.dll.SPC3_IsTriggered
            f.argtypes = [c_void_p, POINTER(c_short)]
            f.restype = c_int
            is_triggered = c_short(0)
            ec = f(self._spc.c_handle, byref(is_triggered))
            self._spc._checkError(ec)
            return bool(is_triggered.value)
        except Exception as e:
            self.log.error(f"Trigger poll failed: {e}")
            return False

    def _wait_for_trigger(self, timeout_s=None):
        if timeout_s is None:
            timeout_s = self._TRIGGER_WAIT_TIMEOUT_S
        start = time.monotonic()
        while not self._is_triggered():
            if (time.monotonic() - start) > timeout_s:
                return False
            time.sleep(0.01)
        return True

    def set_exposure(self, exposure):
        """Set exposure time in seconds.

        Adjusts NIntegFrames to achieve the requested exposure while keeping
        the hardware integration time (HIT) unchanged.

            exposure = NIntegFrames × HIT_cycles × 10 ns

        @param float exposure: desired exposure in seconds
        @return float: actual achieved exposure in seconds
        """
        hit_s = self._effective_hit() * self._CLOCK_PERIOD
        n = max(1, min(int(round(exposure / hit_s)), 65534))
        self._NIntegFrames = n
        self._apply_camera_settings()
        return self._get_exposure_seconds()

    def get_exposure(self):
        """Return exposure time in seconds."""
        return self._get_exposure_seconds()

    def set_gain(self, gain):
        """Not applicable for SPAD camera."""
        return 0

    def get_gain(self):
        """Not applicable for SPAD camera."""
        return 0

    def get_ready_state(self):
        """Return True when camera is idle and ready for a new acquisition."""
        return not (self._live or self._acquiring or self._continuous)

    # ══════════════════════════════════════════════════════════════════
    #  SPC3‑specific public methods (called by camera_logic_SPC3)
    # ══════════════════════════════════════════════════════════════════

    # ── Display units ──────────────────────────────────────────────────

    def get_display_units(self):
        """Return 'counts' or 'cps'."""
        return self._display_units

    def set_display_units(self, units):
        """Set display scaling mode.

        @param str units: 'counts' or 'cps'
        @return bool: Success
        """
        if units not in ("counts", "cps"):
            self.log.error(f"Invalid display units '{units}'. Use 'counts' or 'cps'")
            return False
        self._display_units = units
        self.log.info(f"Display units set to: {units}")
        return True

    # ── Hardware integration time ──────────────────────────────────────

    def set_hardware_integration(self, seconds):
        """Set HIT in seconds (Advanced mode only).

        Internally converts to clock cycles for SetCameraPar.

        @param float seconds: HIT in seconds
        @return bool: Success
        """
        if self._camera_mode != "Advanced":
            self.log.warning("HIT is fixed in Normal mode (10.4 µs)")
            return False

        cycles = max(1, min(int(round(seconds / self._CLOCK_PERIOD)), 65534))
        self._hit = cycles
        self._apply_camera_settings()
        self.log.info(
            f"HIT set to {cycles} cycles ({cycles * self._CLOCK_PERIOD * 1e6:.2f} µs)"
        )
        return True

    # ── Temporal binning ───────────────────────────────────────────────

    def set_binning(self, binning):
        """Set temporal binning (NIntegFrames).

        @param int binning: number of frames to integrate (1-65534)
        @return bool: Success
        """
        self._NIntegFrames = max(1, min(int(binning), 65534))
        self._apply_camera_settings()
        return True

    def get_binning(self):
        """Return current NIntegFrames value."""
        return self._NIntegFrames

    # ── Snap frames (NFrames) ─────────────────────────────────────────

    def get_snap_frames(self):
        """Return the number of frames captured per snap acquisition (1-65534)."""
        try:
            return int(self._NFrames)
        except Exception:
            return 1

    def set_snap_frames(self, n_frames):
        """Set the number of frames per snap acquisition (NFrames).

        This updates the camera parameters via SetCameraPar and commits the
        settings. The change is only allowed while the camera is idle.

        @param int n_frames: 1..65534
        @return bool: Success
        """
        if not self.get_ready_state():
            self.log.error(
                "Cannot set snap frames while acquisition is active (live/snap/continuous)"
            )
            return False

        try:
            n = max(1, min(int(n_frames), 65534))
        except Exception:
            self.log.error(f"Invalid n_frames value: {n_frames!r}")
            return False

        if n == int(getattr(self, "_NFrames", 1) or 1):
            return True

        self._NFrames = n
        self._apply_camera_settings()
        self.log.info(f"Snap frames (NFrames) set to {self._NFrames}")
        return True

    # ── Save directory ─────────────────────────────────────────────────

    def get_default_save_directory(self):
        """Return the default save directory from config, or empty string."""
        return self._cfg_save_directory

    # ── Trigger ────────────────────────────────────────────────────────

    def get_trigger_mode(self):
        """Return 'no_trigger', 'single_trigger', or 'multiple_trigger'."""
        return self._trigger_mode

    def get_trigger_frames_per_pulse(self):
        """Return frames per SYNC_IN pulse (1-100)."""
        return self._trigger_frames_per_pulse

    def set_trigger_mode(self, mode, frames_per_pulse=1):
        """Set trigger mode and apply immediately.

        @param str mode: 'no_trigger' | 'single_trigger' | 'multiple_trigger'
        @param int frames_per_pulse: 1-100 (multiple_trigger only)
        """
        valid = ("no_trigger", "single_trigger", "multiple_trigger")
        if mode not in valid:
            self.log.error(f"Invalid trigger mode '{mode}'. Must be one of {valid}")
            return
        self._trigger_mode = mode
        self._trigger_frames_per_pulse = max(1, min(int(frames_per_pulse), 100))
        self._apply_trigger_settings()
        self._commit_settings()

    # ── Continuous acquisition ─────────────────────────────────────────

    def continuous_acquisition(self, filename):
        """Start streaming acquisition data to file.

        Settings must already be committed (on_activate or via set_* methods).
        Do NOT call ApplySettings() here — calling it immediately before
        ContAcqToFileStart can reset the camera into an idle state that
        prevents data generation.

        @param str filename: path stem (SDK appends .spc3)
        @return bool: Success
        """
        if self._continuous:
            self.log.error("Continuous acquisition already active")
            return False
        if self._live or self._acquiring:
            self.log.error("Cannot start continuous: another acquisition is active")
            return False

        try:
            filename = os.path.normpath(str(filename))
            if filename.lower().endswith(".spc3"):
                filename = filename[:-5]

            directory = os.path.dirname(filename)
            if directory:
                os.makedirs(directory, exist_ok=True)

            # Snapshot the gate settings that will apply for this run.
            self._cont_gate_mode = self._gate_mode
            self._cont_coarse_gate_start = self._coarse_gate_start
            self._cont_coarse_gate_stop = self._coarse_gate_stop

            self._spc.ContAcqToFileStart(filename)
            self._continuous = True
            self._cont_filename = filename
            self.log.info(f"ContAcqToFileStart -> {filename}")

            # Snap-like messaging for triggered continuous acquisition.
            self._cont_waiting_for_trigger = False
            if self._trigger_mode in ("single_trigger", "multiple_trigger"):
                self._cont_waiting_for_trigger = True
                extra = ""
                if self._trigger_mode == "multiple_trigger":
                    extra = f", frames_per_pulse={self._trigger_frames_per_pulse}"
                self.log.info(
                    f"Waiting for external trigger ({self._trigger_mode}{extra})..."
                )
                # If a trigger already happened, report immediately.
                try:
                    if self._is_triggered():
                        self.log.info("Trigger received")
                        self._cont_waiting_for_trigger = False
                except Exception:
                    pass

            # Best-effort: patch the output header early so even an interrupted
            # run preserves the gate metadata in the file header.
            try:
                expected = filename + ".spc3"
                if os.path.exists(expected):
                    self._patch_spc3_coarse_gate_header(
                        expected,
                        gate_mode=getattr(self, "_cont_gate_mode", None),
                        start_cycles=getattr(self, "_cont_coarse_gate_start", None),
                        stop_cycles=getattr(self, "_cont_coarse_gate_stop", None),
                    )
            except Exception:
                pass
            return True
        except Exception as e:
            self._continuous = False
            self.log.error(f"Failed to start continuous acquisition: {e}")
            return False

    def stop_continuous_acquisition(self):
        """Stop streaming and close the output file."""
        if self._continuous:
            try:
                self._spc.ContAcqToFileStop()
            except Exception as e:
                self.log.error(f"Failed to stop continuous acquisition: {e}")

            # After closing the file, stamp coarse gate metadata (SDK currently
            # leaves these fields at 0 even when gating is active).
            try:
                stem = getattr(self, "_cont_filename", "")
                for out_path in self._list_written_spc3_paths(stem):
                    self._patch_spc3_coarse_gate_header(
                        out_path,
                        gate_mode=getattr(self, "_cont_gate_mode", None),
                        start_cycles=getattr(self, "_cont_coarse_gate_start", None),
                        stop_cycles=getattr(self, "_cont_coarse_gate_stop", None),
                    )
            except Exception:
                pass
            self._continuous = False
            self._cont_waiting_for_trigger = False
        return True

    def get_continuous_memory(self):
        """Dump camera memory to disk during continuous acquisition.

        @return int: bytes read in this call
        """
        if self._continuous:
            # Log trigger receipt once when running in triggered modes.
            if getattr(self, "_cont_waiting_for_trigger", False):
                try:
                    if self._is_triggered():
                        self.log.info("Trigger received")
                        self._cont_waiting_for_trigger = False
                except Exception:
                    pass
            return self._spc.ContAcqToFileGetMemory()
        return 0

    # ── File I/O ───────────────────────────────────────────────────────

    def save_frames_to_file(self, frames, filepath):
        """Save snap frames to .spc3 via SDK SaveImgDisk.

        @param numpy.ndarray frames: shape (counters, frames, rows, cols)
        @param str filepath: output path (.spc3 extension optional)
        @return bool: Success
        """
        try:
            filepath = os.path.normpath(filepath)
            if filepath.endswith(".spc3"):
                filepath = filepath[:-5]
            directory = os.path.dirname(filepath)
            if directory:
                os.makedirs(directory, exist_ok=True)

            n_frames = frames.shape[1]
            self._spc.SaveImgDisk(
                1, n_frames, filepath, SPC3.OutFileFormat.SPC3_FILEFORMAT
            )

            expected = filepath + ".spc3"
            if os.path.exists(expected):
                self._patch_spc3_coarse_gate_header(expected)
                return True

            self.log.error(f"SaveImgDisk completed but file not found: {expected}")
            return False

        except Exception as e:
            self.log.error(f"Failed to save frames: {e}")
            return False

    def save_last_snap_to_file(self, filepath, n_frames=None):
        """Save the most recent snap acquisition buffer to a .spc3 file.

        This is intended for *manual* saving right after a snap has completed.
        The SPC3 SDK save routine operates on the device/SDK internal snap buffer
        populated by the last SnapAcquire().

        @param str filepath: output path (.spc3 extension optional)
        @param int|None n_frames: number of frames to write (defaults to configured NFrames)
        @return bool: Success
        """
        try:
            filepath = os.path.normpath(str(filepath))
            if filepath.lower().endswith(".spc3"):
                filepath = filepath[:-5]

            directory = os.path.dirname(filepath)
            if directory:
                os.makedirs(directory, exist_ok=True)

            if n_frames is None:
                n_frames = int(
                    getattr(self._spc, "_snap_num_frames", self._NFrames)
                    or self._NFrames
                )
            n_frames = max(1, min(int(n_frames), 65534))

            self._spc.SaveImgDisk(
                1, n_frames, filepath, SPC3.OutFileFormat.SPC3_FILEFORMAT
            )

            expected = filepath + ".spc3"
            if os.path.exists(expected):
                self._patch_spc3_coarse_gate_header(
                    expected,
                    gate_mode=getattr(self, "_last_acq_gate_mode", None),
                    start_cycles=getattr(self, "_last_acq_coarse_gate_start", None),
                    stop_cycles=getattr(self, "_last_acq_coarse_gate_stop", None),
                )
                return True

            self.log.error(f"SaveImgDisk completed but file not found: {expected}")
            return False

        except Exception as e:
            self.log.error(f"Failed to save last snap: {e}")
            return False

    def load_acquisition_file(self, filepath):
        """Load a .spc3 file for frame-by-frame viewing.

        @param str filepath: path to file
        @return bool: Success
        """
        try:
            filepath = os.path.normpath(filepath)

            self._loaded_frames, self._loaded_header = SPC3.ReadSPC3DataFile(filepath)

            self._loaded_filepath = filepath

            n_c, n_f, n_r, n_col = self._loaded_frames.shape
            self.log.info(f"Loaded {n_f} frames ({n_r}×{n_col}) from {filepath}")
            return True

        except Exception as e:
            self.log.error(f"Failed to load {filepath}: {e}")
            return False

    def _resolve_written_spc3_path(self, filepath_stem):
        """Resolve the actual .spc3 path written by the SDK.

        The SPC3 SDK typically appends the extension and may also append digits
        if the target already exists. We resolve to the most-recent matching file.

        @param str filepath_stem: path without extension
        @return str: path to an existing .spc3 file
        """
        filepath_stem = os.path.normpath(str(filepath_stem))
        if not filepath_stem:
            raise ValueError("filepath_stem is empty")

        expected = filepath_stem + ".spc3"
        if os.path.exists(expected):
            return expected

        directory = os.path.dirname(expected) or os.curdir
        base = os.path.basename(filepath_stem)

        try:
            entries = os.listdir(directory)
        except FileNotFoundError:
            return expected

        base_l = base.lower()
        candidates = [
            os.path.join(directory, name)
            for name in entries
            if name.lower().startswith(base_l) and name.lower().endswith(".spc3")
        ]
        if not candidates:
            return expected
        return max(candidates, key=os.path.getmtime)

    def _list_written_spc3_paths(self, filepath_stem):
        """List all .spc3 files written for a given stem.

        The SPC3 SDK may split a long run into multiple files by appending an
        integer suffix: <stem>.spc3, <stem>2.spc3, <stem>3.spc3, ...

        We return only files whose name matches exactly <base><digits>.spc3
        (digits may be empty), ignoring unrelated similarly-named files.

        @param str filepath_stem: path without extension
        @return list[str]: existing .spc3 paths, sorted by numeric suffix
        """
        filepath_stem = os.path.normpath(str(filepath_stem))
        if not filepath_stem:
            return []
        if filepath_stem.lower().endswith(".spc3"):
            filepath_stem = filepath_stem[:-5]

        directory = os.path.dirname(filepath_stem) or os.curdir
        base = os.path.basename(filepath_stem)
        base_l = base.lower()

        try:
            names = os.listdir(directory)
        except FileNotFoundError:
            return []

        hits = []
        for name in names:
            name_l = name.lower()
            if not name_l.endswith(".spc3"):
                continue
            if not name_l.startswith(base_l):
                continue

            suffix = name[len(base) : -5]
            if suffix and not suffix.isdigit():
                continue

            idx = int(suffix) if suffix else 1
            hits.append((idx, os.path.join(directory, name)))

        hits.sort(key=lambda t: t[0])
        return [p for _, p in hits]

    def _patch_spc3_coarse_gate_header(
        self,
        filepath,
        gate_mode=None,
        start_cycles=None,
        stop_cycles=None,
    ):
        """Stamp coarse-gate metadata into an existing .spc3 header.

        Empirically, the SPC3 SDK leaves the coarse-gate header bytes at 0 even
        when SetGateMode(COARSE) is active. The file format reserves:
          metadata[232]   : coarse gate 1 enabled (uint8)
          metadata[233:235]: coarse gate 1 start (uint16, 10 ns cycles)
          metadata[235:237]: coarse gate 1 stop  (uint16, 10 ns cycles)

        This method patches the header in-place so SPC3.ReadSPC3DataFile() will
        report gating correctly.

        @return bool: True if patched, False if skipped/failed.
        """
        filepath = os.path.normpath(str(filepath))
        if not os.path.exists(filepath):
            return False

        # Only stamp when gate is enabled; leave files untouched otherwise.
        if gate_mode is None:
            gate_mode = getattr(self, "_gate_mode", "off")
        if gate_mode != "coarse":
            return False

        if start_cycles is None:
            start_cycles = getattr(self, "_coarse_gate_start", 0)
        if stop_cycles is None:
            stop_cycles = getattr(self, "_coarse_gate_stop", 0)

        start = int(start_cycles)
        stop = int(stop_cycles)
        start = max(0, min(start, 65535))
        stop = max(0, min(stop, 65535))

        try:
            with open(filepath, "r+b") as f:
                # signature (8 bytes) + metadata (1024 bytes)
                f.seek(8 + 232)
                f.write(
                    struct.pack(
                        "<BHHBHHBHH",
                        1,
                        start,
                        stop,
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                    )
                )
            return True
        except Exception as e:
            self.log.warning(f"Failed to patch coarse gate metadata in {filepath}: {e}")
            return False

    # ── Gate control ───────────────────────────────────────────────────

    def get_gate_mode(self):
        """Return 'off' or 'coarse'."""
        return self._gate_mode

    def get_coarse_gate_values(self):
        """Return (start, stop) in clock cycles."""
        return self._coarse_gate_start, self._coarse_gate_stop

    def set_coarse_gate(self, start_cycles, stop_cycles):
        """Set coarse gate window and apply immediately.

        @param int start_cycles: gate ON start (clock cycles)
        @param int stop_cycles: gate ON stop (clock cycles)
        """
        self._gate_mode = "coarse"
        self._coarse_gate_start = int(start_cycles)
        self._coarse_gate_stop = int(stop_cycles)
        self._apply_gate_settings()
        self._spc.ApplySettings()

    def disable_gate(self):
        """Set counter 1 back to continuous (ungated) mode."""
        self._gate_mode = "off"
        self._apply_gate_settings()
        self._spc.ApplySettings()

    # ══════════════════════════════════════════════════════════════════
    #  Private helpers
    # ══════════════════════════════════════════════════════════════════

    @staticmethod
    def _to_state(value, name=""):
        """Convert config string/bool/int to SPC3 State enum (0 or 1)."""
        if value in (1, True, "Enabled", "enabled", "ENABLED"):
            return SPC3.State.ENABLED
        if value in (0, False, "Disabled", "disabled", "DISABLED"):
            return SPC3.State.DISABLED
        raise ValueError(f"{name}: expected Enabled/Disabled, got {value!r}")

    def _effective_hit(self):
        """Return active HIT in clock cycles."""
        if self._camera_mode == "Advanced":
            return self._hit
        return self._HIT_NORMAL

    def _get_exposure_seconds(self):
        """Calculate exposure: NIntegFrames × HIT × 10 ns."""
        return self._NIntegFrames * self._effective_hit() * self._CLOCK_PERIOD

    def _apply_camera_settings(self):
        """Send current camera parameters to hardware and commit."""
        self._spc.SetCameraPar(
            self._effective_hit(),
            self._NFrames,
            self._NIntegFrames,
            self._NCounters,
            self._force8bit,
            self._half_array,
            self._signed_data,
        )
        self._commit_settings()

    def _apply_trigger_settings(self):
        """Configure the SYNC_IN trigger on the camera."""
        if self._trigger_mode == "no_trigger":
            self._spc.SetSyncInState(SPC3.State.DISABLED, 0)
        elif self._trigger_mode == "single_trigger":
            self._spc.SetSyncInState(SPC3.State.ENABLED, 0)
        elif self._trigger_mode == "multiple_trigger":
            self._spc.SetSyncInState(SPC3.State.ENABLED, self._trigger_frames_per_pulse)
        else:
            self.log.warning(f"Unknown trigger_mode '{self._trigger_mode}', disabling")
            self._spc.SetSyncInState(SPC3.State.DISABLED, 0)

    def _apply_gate_settings(self):
        """Configure coarse gating on counter 1."""
        if self._gate_mode not in ("off", "coarse"):
            raise ValueError(
                "Internal gate_mode must be 'off' or 'coarse', "
                f"got {self._gate_mode!r}"
            )

        if self._gate_mode != "off" and self._camera_mode != "Advanced":
            self.log.warning(
                "Coarse gating requires Advanced mode — gate will NOT be applied"
            )
            self._spc.SetGateMode(1, SPC3.GateMode.CONTINUOUS)
            return

        if self._gate_mode == "coarse":
            hit = self._effective_hit()
            start = max(0, min(self._coarse_gate_start, hit - 6))
            stop = max(start + 1, min(self._coarse_gate_stop, hit - 5))
            if start != self._coarse_gate_start or stop != self._coarse_gate_stop:
                self.log.warning(
                    f"Gate values clamped: start={start}, stop={stop} (HIT={hit})"
                )
            self._coarse_gate_start = start
            self._coarse_gate_stop = stop
            self._spc.SetGateMode(1, SPC3.GateMode.COARSE)
            self._spc.SetCoarseGateValues(1, start, stop)
            self.log.info(
                f"Gate: coarse counter 1 — "
                f"start={start * 10} ns, stop={stop * 10} ns "
                f"(cycles {start}–{stop} of {hit})"
            )
        else:
            self._spc.SetGateMode(1, SPC3.GateMode.CONTINUOUS)

    def _commit_settings(self):
        """Re-apply gate settings then commit everything to hardware.

        SetCameraPar resets the SDK pending-settings queue, so the gate
        configuration must be re-issued before every ApplySettings() call.
        """
        self._apply_trigger_settings()
        self._apply_gate_settings()
        self._spc.ApplySettings()
