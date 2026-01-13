# -*- coding: utf-8 -*-

# FIXME: This module is obviously taken from someone else and altered without attribution.
"""
This hardware module implement the camera spectrometer interface to use an Andor Camera.
It use a dll to interface with instruments via USB (only available physical interface)
This module does aim at replacing Solis.

---

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

from enum import Enum
from ctypes import *
import numpy as np

from qudi.core.configoption import ConfigOption
from qudi.interface.camera_interface import CameraInterface

from qudi.hardware.camera.SPC3.spc import SPC3


class SPC3_Qudi(CameraInterface):
    """Hardware class for SPC3 SPAD Camera

    Example config for copy-paste:

    camera_SPC3:
        module.Class: 'camera.SPC3.spc3_qudi.SPC3_Qudi'
        options:
            dll_location: 'C:\\Users\\...\\qudi-iqo-modules\\src\\qudi\\hardware\\camera\\SPC3\\lib\\Win\\'
            default_camera_mode: 'Normal'  # or 'Advanced'
            default_hardware_integration: 5200  # in units of 10ns clock cycles (52 us)
            default_NFrames: 100  # frames per Snap acquisition
            default_NIntegFrames: 1000  # temporal binning (integrated frames per output)
            default_NCounters: 1  # number of counters per pixel (1-3)
            default_Force8bit: 'Disabled'  # or 'Enabled' (Advanced mode only)
            default_Half_array: 'Disabled'  # or 'Enabled' (32x32 instead of 32x64)
            default_Signed_data: 'Disabled'  # or 'Enabled'

    Unit Convention:
        - ALL public parameters use SECONDS for time values (exposure, integration)
        - Binning is integer frame count (no units)
        - CRITICAL: SetCameraPar hardware integration parameter uses CLOCK CYCLES (each cycle = 10ns)

    Note on exposure time:
        - Normal mode: Hardware integration fixed at 10.4 µs (1040 clock cycles)
        - Advanced mode: Hardware integration configurable (1-65534 clock cycles)
        - Actual exposure = NIntegFrames × HardwareIntegration × 10ns

    """

    _camera_mode = ConfigOption("camera_mode", missing="error")
    _dll_location = ConfigOption("dll_location", missing="error")
    _default_hardware_integration = ConfigOption("default_hardware_integration", 5200)
    _default_NFrames = ConfigOption("default_NFrames", 1)
    _default_NIntegFrames = ConfigOption("default_NIntegFrames", 1000)
    _default_NCounters = ConfigOption("default_NCounters", 1)
    _default_Force8bit = ConfigOption("default_Force8bit", 0)
    _default_display_units = ConfigOption(
        "default_display_units", "counts"
    )  # 'counts' or 'cps'
    _default_Half_array = ConfigOption("default_Half_array", 0)
    _default_Signed_data = ConfigOption("default_Signed_data", 0)
    # _trigger_mode = ConfigOption("default_trigger_mode", 0)

    _HardwareIntegration = _default_hardware_integration
    _NFrames = _default_NFrames
    _NIntegFrames = _default_NIntegFrames
    _NCounters = _default_NCounters
    _Force8bit = _default_Force8bit
    _display_units = _default_display_units  # 'counts' or 'cps'
    _Half_array = _default_Half_array
    _Signed_data = _default_Signed_data

    _HardwareIntegration_Normal = (
        1040  # fixed to 10.4 us in Normal mode (in units of 10ns clock cycles)
    )
    _Nrows = 32
    _Ncols = 64
    _exposure = 0.02  # in seconds (for GUI display, calculated from NIntegFrames * HardwareIntegration * 10ns)

    # Valid parameter ranges from spc.py documentation
    _MIN_HARDWARE_INTEGRATION = 1  # clock cycles
    _MAX_HARDWARE_INTEGRATION = 65534  # clock cycles
    _MIN_FRAMES = 1
    _MAX_FRAMES = 65534
    _MIN_INTEG_FRAMES = 1
    _MAX_INTEG_FRAMES = 65534

    _live = False
    _acquiring = False
    _continuous = False
    _camera_name = "SPC3"
    _background_subtraction_enabled = (
        False  # Track software background subtraction state
    )

    def _to_binary(self, value, name):
        """Normalize binary config options to 0/1.

        Accepts 0/1, True/False, and 'Enabled'/'Disabled' variants.
        """
        if value in (1, True, "Enabled", "enabled", "ENABLED"):
            return 1
        if value in (0, False, "Disabled", "disabled", "DISABLED"):
            return 0
        raise ValueError(f"{name} config option must be 0/1 or Disabled/Enabled")

    def on_activate(self):
        """Initialisation performed during activation of the module."""

        # Normalize binary options using configured values
        force8bit = self._to_binary(self._Force8bit, "Force8bit")
        half_array = self._to_binary(self._Half_array, "Half_array")
        signed_data = self._to_binary(self._Signed_data, "Signed_data")

        # Advanced Camera Mode
        if self._camera_mode == "Advanced":
            self.spc3 = SPC3(1, "", self._dll_location)
            self.spc3.SetCameraPar(
                self._HardwareIntegration,
                self._NFrames,
                self._NIntegFrames,
                self._NCounters,
                force8bit,
                half_array,
                signed_data,
            )
            hardware_time = self._HardwareIntegration * 10e-9
            self.log.info(
                f"SPC3 initialized in Advanced mode: HW integration = {hardware_time*1e6:.2f} µs"
            )

        ### GATING OPTIONS FOR ADVANCED MODE ###
        # SetGateMode(self, counter, Mode)
        # SetGateValues(self, Shift, Length)
        # SetDualGate(self, DualGate_State, StartShift, FirstGateWidth, SecondGateWidth, Gap)
        # SetTripleGate(self,TripleGate_State,StartShift,FirstGateWidth,SecondGateWidth,ThirdGateWidth,Gap1,Gap2)
        # SetCoarseGateValues(self, Counter, Start, Stop)

        # Normal Camera Mode
        else:
            self.spc3 = SPC3(0, "", self._dll_location)
            self.spc3.SetCameraPar(
                self._HardwareIntegration_Normal,
                self._NFrames,
                self._NIntegFrames,
                self._NCounters,
                force8bit,
                half_array,
                signed_data,
            )
            hardware_time = self._HardwareIntegration_Normal * 10e-9
            self.log.info(
                f"SPC3 initialized in Normal mode: HW integration = {hardware_time*1e6:.2f} µs (fixed)"
            )

        ### TRIGGER MODE OPTIONS - SKIPPED FOR NOW ###
        # if self._trigger_mode >= 0:
        # self.spc3.SetSyncInState(
        # SPC3.State.ENABLED, self._trigger_mode
        # )  # enable triggering (1 per trigger pulse)
        # self.spc3.SetTriggerOutState(
        # SPC3.TriggerMode.FRAME
        # )  # output trigger per frame

        self.spc3.ApplySettings()
        self._Ncols = self._Ncols >> half_array

        # Calculate and log initial exposure time
        self._exposure = self._NIntegFrames * hardware_time
        self.log.info(
            f"Initial exposure: {self._exposure*1e3:.2f} ms ({self._NIntegFrames} frames × {hardware_time*1e6:.2f} µs)"
        )

    def _apply_camera_settings(self):
        """Apply current camera parameters to hardware"""
        force8bit = self._to_binary(self._Force8bit, "Force8bit")
        half_array = self._to_binary(self._Half_array, "Half_array")
        signed_data = self._to_binary(self._Signed_data, "Signed_data")

        if self._camera_mode == "Advanced":
            self.spc3.SetCameraPar(
                self._HardwareIntegration,
                self._NFrames,
                self._NIntegFrames,
                self._NCounters,
                force8bit,
                half_array,
                signed_data,
            )
        else:
            self.spc3.SetCameraPar(
                self._HardwareIntegration_Normal,
                self._NFrames,
                self._NIntegFrames,
                self._NCounters,
                force8bit,
                half_array,
                signed_data,
            )
        self.spc3.ApplySettings()

    def on_deactivate(self):
        """Deinitialisation performed during deactivation of the module."""
        # self._spc3.ContAcqToMemoryStop()
        if self._live:
            self.spc3.LiveSetModeOFF()
            self._live = False
        if self._acquiring:
            self._acquiring = False
        if self._continuous:
            self._continuous = False
            self.spc3.ContAcqToFileStop()
        self.spc3.Destr()

    def get_name(self):
        """Retrieve an identifier of the camera that the GUI can print

        @return string: name for the camera
        """
        return self.spc3.GetSerial()

    def get_size(self):
        """Retrieve size of the image in pixel

        @return tuple: Size (width, height)
        """
        # Return (height, width) to match numpy array shape convention
        # _Ncols is adjusted based on Half_array setting during activation
        return self._Nrows, self._Ncols

    def support_live_acquisition(self):
        """Return whether or not the camera can take care of live acquisition

        @return bool: True if supported, False if not
        """
        return True

    def start_live_acquisition(self):
        """Start a continuous acquisition

        @return bool: Success ?
        """
        self._live = True
        self._acquiring = False
        self.spc3.LiveSetModeON()

        return True

    def start_single_acquisition(self):
        """Perform snap acquisition using proper SDK sequence

        Executes: SnapPrepare → SnapAcquire → SnapGetImageBuffer
        Returns frames array.

        @return numpy array: Acquired frames, or None if failed
        """
        if self._live:
            self.log.error("Cannot snap: live mode is active")
            return None

        try:
            self._acquiring = True
            # Step 1: Prepare camera for snap
            self.spc3.SnapPrepare()

            # Step 2: Trigger acquisition (blocks until complete)
            self.spc3.SnapAcquire()

            # Step 3: Retrieve frames from buffer
            frames = self.spc3.SnapGetImageBuffer()

            self._acquiring = False

            if frames is None:
                self.log.error("SnapGetImageBuffer returned None")
                return None

            return frames
        except Exception as e:
            self._acquiring = False
            self.log.error(f"Snap acquisition failed: {e}")
            import traceback

            self.log.error(f"Traceback: {traceback.format_exc()}")
            return None

    def continuous_acquisition(self, filename):
        """Start a continuous acquisition to file

        @return bool: Success ?
        """
        if self._live or self._acquiring:
            return False
        else:
            self._continuous = True
            self.spc3.ContAcqToFileStart(filename)
        return True

    def stop_continuous_acquisition(self):
        """Stop continuous acquisition

        @return bool: Success ?
        """
        if self._continuous:
            self.spc3.ContAcqToFileStop()
            self._continuous = False
        return True

    def get_continuous_memory(self):
        """Get continuous acquisition memory data

        @return int: Total number of bytes read
        """
        if self._continuous:
            return self.spc3.ContAcqToFileGetMemory()
        else:
            return 0

    def stop_acquisition(self):
        """Stop/abort live or single acquisition

        @return bool: Success ?
        """
        if self._live:
            self.spc3.LiveSetModeOFF()
        self._live = False
        self._acquiring = False

    def get_acquired_data(self):
        """Return current live mode frame.

        This method is ONLY for live mode video display in the GUI.
        For snap mode, use start_single_acquisition() which returns frames directly.
        For continuous mode, data streams directly to file.

        @return numpy array: Live frame data with background subtraction and scaling applied
        """

        image_array = np.zeros(self._Nrows * self._Ncols)
        if self._live:
            image_array = self.spc3.LiveGetImg()

        # Extract counter 1 frame
        counter1_frame = image_array[0]

        # Apply software background subtraction if enabled
        if self._background_subtraction_enabled:
            if not hasattr(self, "_background_image") or self._background_image is None:
                return counter1_frame

            try:
                # Store original frame shape and flatten both to 1D for pixel-by-pixel subtraction
                original_shape = counter1_frame.shape
                frame_flat = counter1_frame.flatten()

                # Ensure background image matches size
                if self._background_image.size != frame_flat.size:
                    self.log.warning(
                        f"Background image size mismatch: frame={frame_flat.size}, background={self._background_image.size}"
                    )
                    return counter1_frame

                # Subtract background pixel-by-pixel (both 1D arrays)
                subtracted_flat = np.maximum(
                    frame_flat.astype(np.float32)
                    - self._background_image.astype(np.float32),
                    0,
                )

                # Reshape back to original shape
                counter1_frame = subtracted_flat.astype(counter1_frame.dtype).reshape(
                    original_shape
                )
            except Exception as e:
                self.log.error(f"Error applying background subtraction: {e}")
                import traceback

                self.log.error(traceback.format_exc())
                return image_array[0]  # Return unsubtracted frame

        # Scale to counts per second if enabled
        if self._display_units == "cps":
            # exposure_time = HardwareIntegration_cycles * 10ns * NIntegFrames
            exposure_time_seconds = (
                self._HardwareIntegration * 10e-9 * self._NIntegFrames
            )
            counter1_frame = (
                counter1_frame.astype(np.float32) / exposure_time_seconds
            ).astype(counter1_frame.dtype)

        # Ensure 2D shape for GUI display (rows, cols)
        if counter1_frame.ndim == 1:
            counter1_frame = counter1_frame.reshape(self._Nrows, self._Ncols)

        return counter1_frame

    def set_exposure(self, exposure):
        """Set the exposure time in seconds

        @param float exposure: desired new exposure time in seconds

        @return bool: Success?

        FORMULA: exposure_seconds = NIntegFrames × HardwareIntegration_cycles × 10ns_per_cycle
        Note: HardwareIntegration is in CLOCK CYCLES where each cycle = 10ns
        """
        # Calculate NIntegFrames needed to achieve desired exposure time
        # Actual exposure = NIntegFrames * HardwareIntegration_cycles * 10ns
        # IMPORTANT: HardwareIntegration is in CLOCK CYCLES (each cycle = 10ns)
        # For Normal mode: HardwareIntegration fixed at 1040 cycles (1040 × 10ns = 10.4 µs)
        # For Advanced mode: use configured _HardwareIntegration (in cycles)

        if self._camera_mode == "Advanced":
            hardware_time = self._HardwareIntegration * 10e-9  # convert to seconds
        else:
            hardware_time = (
                self._HardwareIntegration_Normal * 10e-9
            )  # convert to seconds

        # Calculate required NIntegFrames
        n_integ_frames = int(round(exposure / hardware_time))

        # Clamp to valid range
        n_integ_frames = max(
            self._MIN_INTEG_FRAMES, min(n_integ_frames, self._MAX_INTEG_FRAMES)
        )

        if n_integ_frames != int(round(exposure / hardware_time)):
            self.log.warning(
                f"Requested exposure {exposure}s clamped to {n_integ_frames} frames"
            )

        self._NIntegFrames = n_integ_frames
        self._exposure = n_integ_frames * hardware_time  # actual achieved exposure

        # Normalize binary options for safe re-application
        force8bit = self._to_binary(self._Force8bit, "Force8bit")
        half_array = self._to_binary(self._Half_array, "Half_array")
        signed_data = self._to_binary(self._Signed_data, "Signed_data")

        self.spc3.SetCameraPar(
            (
                self._HardwareIntegration
                if self._camera_mode == "Advanced"
                else self._HardwareIntegration_Normal
            ),
            self._NFrames,
            self._NIntegFrames,
            self._NCounters,
            force8bit,
            half_array,
            signed_data,
        )
        self.spc3.ApplySettings()
        return True

    def get_exposure(self):
        """Get the exposure time in seconds

        @return float exposure time

        FORMULA: exposure = NIntegFrames × HardwareIntegration_cycles × 10ns_per_cycle
        Each clock cycle = 10ns = 10e-9 seconds
        """
        # Calculate actual exposure time: NIntegFrames * HardwareIntegration_cycles * 10ns
        # HardwareIntegration is in clock cycles (10ns per cycle)
        if self._camera_mode == "Advanced":
            hardware_time = (
                self._HardwareIntegration * 10e-9
            )  # cycles × 10ns/cycle = seconds
        else:
            hardware_time = (
                self._HardwareIntegration_Normal * 10e-9
            )  # cycles × 10ns/cycle = seconds

        self._exposure = self._NIntegFrames * hardware_time
        return self._exposure

    # def get_actual_exposure(self):
    # """Get the actual exposure time in seconds

    # @return float exposure time
    # """
    # return self._NIntegFrames * (self._HardwareIntegration_Normal / 100) / 1000

    def set_hardware_integration(self, integration_seconds):
        """Set hardware integration time (only for Advanced mode)

        SetCameraPar first parameter uses CLOCK CYCLES (each cycle = 10ns).
        This method accepts SECONDS and converts to clock cycles.

        @param float integration_seconds: Hardware integration time in SECONDS
        @return bool: Success?

        Conversion formula: seconds × 1e9 ns/s ÷ 10 ns/cycle = clock_cycles
        """
        if self._camera_mode != "Advanced":
            self.log.warning(
                "Hardware integration time is fixed in Normal mode (10.4 us)"
            )
            return False

        # STEP 1: Convert SECONDS to NANOSECONDS (multiply by 1e9)
        integration_ns = integration_seconds * 1e9
        # STEP 2: Convert NANOSECONDS to CLOCK CYCLES (divide by 10, since each cycle = 10ns)
        integration_cycles = int(round(integration_ns / 10.0))

        # Clamp to valid range
        integration_cycles = max(
            self._MIN_HARDWARE_INTEGRATION,
            min(integration_cycles, self._MAX_HARDWARE_INTEGRATION),
        )

        self._HardwareIntegration = integration_cycles

        # Update exposure time calculation
        self._exposure = self._NIntegFrames * integration_cycles * 10e-9

        force8bit = self._to_binary(self._Force8bit, "Force8bit")
        half_array = self._to_binary(self._Half_array, "Half_array")
        signed_data = self._to_binary(self._Signed_data, "Signed_data")

        self.spc3.SetCameraPar(
            integration_cycles,
            self._NFrames,
            self._NIntegFrames,
            self._NCounters,
            force8bit,
            half_array,
            signed_data,
        )
        self.spc3.ApplySettings()
        return True

    def set_binning(self, binning):
        """Set temporal binning (NIntegFrames)

        @param int binning: Number of frames to integrate
        @return bool: Success?
        """
        # Clamp to valid range
        binning = max(self._MIN_INTEG_FRAMES, min(binning, self._MAX_INTEG_FRAMES))

        self._NIntegFrames = binning

        # Update exposure time
        if self._camera_mode == "Advanced":
            hardware_time = self._HardwareIntegration * 10e-9
        else:
            hardware_time = self._HardwareIntegration_Normal * 10e-9
        self._exposure = binning * hardware_time

        force8bit = self._to_binary(self._Force8bit, "Force8bit")
        half_array = self._to_binary(self._Half_array, "Half_array")
        signed_data = self._to_binary(self._Signed_data, "Signed_data")

        self.spc3.SetCameraPar(
            (
                self._HardwareIntegration
                if self._camera_mode == "Advanced"
                else self._HardwareIntegration_Normal
            ),
            self._NFrames,
            self._NIntegFrames,
            self._NCounters,
            force8bit,
            half_array,
            signed_data,
        )
        self.spc3.ApplySettings()
        return True

    # not applicable for SPAD
    def set_gain(self, gain):
        """Set the gain

        @param float gain: desired new gain

        @return float: new exposure gain
        """
        return 0

    def get_display_units(self):
        """Get the display units setting

        @return str: 'counts' or 'cps'
        """
        return self._display_units

    def set_display_units(self, units):
        """Set the display units

        @param str units: 'counts' or 'cps'
        @return bool: Success?
        """
        if units not in ["counts", "cps"]:
            self.log.error(f"Invalid display units: {units}. Must be 'counts' or 'cps'")
            return False
        self._display_units = units
        self.log.info(f"Display units set to: {units}")
        return True

    def get_gain(self):
        """Get the gain

        @return float: exposure gain
        """
        return 0

    def get_ready_state(self):
        """Is the camera ready for an acquisition ?

        @return bool: ready ?
        """
        if self._live:
            return False
        else:
            return True

    def capture_background_image(self):
        """Capture a background image for background subtraction.

        Uses live mode to capture multiple frames and averages them.
        This ensures the same NIntegFrames settings as normal live acquisition.
        Camera can be in live or idle mode.

        @return bool: Success ?
        """
        try:
            # Determine if we need to start/stop live mode
            was_live = self._live
            if not was_live:
                self.start_live_acquisition()
                import time

                time.sleep(0.5)  # Give hardware time to stabilize

            # Capture multiple live frames using NFrames from config
            num_frames_to_average = self._NFrames
            self.log.info(
                f"Capturing background: averaging {num_frames_to_average} frames"
            )
            frames_list = []

            for i in range(num_frames_to_average):
                image_array = self.spc3.LiveGetImg()
                counter0_frame = image_array[0]  # Shape: (rows, cols)
                frames_list.append(counter0_frame)

            # Stop live if we started it
            if not was_live:
                self.stop_acquisition()

            # Stack and average all frames
            frames_stack = np.stack(
                frames_list, axis=0
            )  # Shape: (num_frames, rows, cols)
            background_2d = np.mean(frames_stack, axis=0).astype(
                np.uint16
            )  # Shape: (rows, cols)

            # Flatten to 1D for storage
            self._background_image = background_2d.flatten()

            self.log.info(
                f"Background image captured: averaged {num_frames_to_average} frames"
            )
            return True
        except Exception as e:
            import traceback

            self.log.error(f"Failed to capture background image: {e}")
            self.log.error(f"Traceback: {traceback.format_exc()}")
            return False

    def enable_background_subtraction(self):
        """Enable software background subtraction.

        The background image must be captured first using capture_background_image().

        @return bool: Success ?
        """
        if not hasattr(self, "_background_image") or self._background_image is None:
            self.log.warning(
                "No background image captured. Call capture_background_image() first."
            )
            return False

        self._background_subtraction_enabled = True
        self.log.info("Background subtraction enabled")
        return True

    def disable_background_subtraction(self):
        """Disable software background subtraction.

        @return bool: Success ?
        """
        self._background_subtraction_enabled = False
        self.log.info("Software background subtraction disabled")
        return True

    def read_spc3_file(self, path):
        """Read a .spc3 data file and return frames array and header

        @param str path: Path to .spc3 file
        @return tuple: (frames array, header dict)
        """
        frames, header = self.spc3.ReadSPC3DataFile(path)
        return frames, header

    def save_frames_to_file(self, frames, filepath):
        """Save acquired snap frames to .spc3 file using SDK

        Uses SDK's SaveImgDisk to write directly from internal buffer.
        SDK may add .spc3 extension automatically.

        @param numpy array frames: Frames array (for shape info only)
        @param str filepath: Path to save file
        @return bool: Success?
        """
        try:
            import os

            # Normalize path to Windows format (handles spaces in directory names)
            filepath = os.path.normpath(filepath)

            # Remove .spc3 extension if present (SDK adds it automatically)
            if filepath.endswith(".spc3"):
                filepath = filepath[:-5]

            # Ensure directory exists
            directory = os.path.dirname(filepath)
            if directory and not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
                self.log.info(f"Created directory: {directory}")

            # Save using SDK (expects path WITHOUT extension)
            num_frames = self._NFrames
            self.log.info(
                f"Calling SaveImgDisk for frames 1-{num_frames} to '{filepath}'"
            )

            # SaveImgDisk(Start_Img, End_Img, filename, mode)
            self.spc3.SaveImgDisk(
                1, num_frames, filepath, SPC3.OutFileFormat.SPC3_FILEFORMAT
            )

            # SDK adds .spc3 extension automatically
            expected_file = filepath + ".spc3"
            if os.path.exists(expected_file):
                file_size = os.path.getsize(expected_file)
                self.log.info(
                    f"Successfully saved to {expected_file} ({file_size} bytes)"
                )
                return True
            else:
                self.log.error(
                    f"SaveImgDisk completed but file not found at {expected_file}"
                )
                return False
        except Exception as e:
            self.log.error(f"Failed to save frames: {e}")
            import traceback

            self.log.error(f"Traceback: {traceback.format_exc()}")
            return False

    def load_acquisition_file(self, filepath):
        """Load acquisition file for viewing

        Loads .npy files (from snap) or .spc3 files (from continuous acquisitions).
        Works with any image dimensions stored in the file.

        @param str filepath: Path to .npy or .spc3 file
        @return bool: Success?
        """
        try:
            import os

            # Normalize path to Windows format (handles spaces in directory names)
            filepath = os.path.normpath(filepath)

            # Load based on file extension
            if filepath.endswith(".npy"):
                # Numpy format (snap acquisitions)
                self._loaded_frames = np.load(filepath)
                self._loaded_header = {}  # No header in numpy files
            else:
                # SPC3 format (continuous acquisitions)
                self._loaded_frames, self._loaded_header = self.read_spc3_file(filepath)
            self._current_frame_index = 0
            self._loaded_filepath = filepath

            num_counters, num_frames, rows, cols = self._loaded_frames.shape
            self.log.info(f"Loaded {num_frames} frames ({rows}×{cols}) from {filepath}")
            return True
        except Exception as e:
            self.log.error(f"Failed to load file {filepath}: {e}")
            import traceback

            self.log.error(f"Traceback: {traceback.format_exc()}")
            return False

    def convert_spc3_to_numpy(self, spc3_filepath, numpy_filepath):
        """Convert SPC3 format file to numpy format

        @param str spc3_filepath: Path to input .spc3 file
        @param str numpy_filepath: Path to output .npy file
        @return bool: Success?
        """
        try:
            frames, header = self.read_spc3_file(spc3_filepath)
            np.save(numpy_filepath, frames)
            self.log.info(
                f"Converted {spc3_filepath} to numpy format: {numpy_filepath}"
            )
            return True
        except Exception as e:
            self.log.error(f"Failed to convert SPC3 to numpy: {e}")
            return False

    def get_loaded_frame_count(self):
        """Get number of frames in loaded file

        @return int: Number of frames, or 0 if no file loaded
        """
        if hasattr(self, "_loaded_frames") and self._loaded_frames is not None:
            # frames shape is (num_counters, num_frames, rows, cols)
            return self._loaded_frames.shape[1]
        return 0

    def get_loaded_frame(self, frame_index):
        """Get a specific frame from loaded file

        @param int frame_index: Frame index (0-based)
        @return numpy array: Frame data, or None if invalid
        """
        if not hasattr(self, "_loaded_frames") or self._loaded_frames is None:
            self.log.warning("No file loaded")
            return None

        num_frames = self._loaded_frames.shape[1]
        if frame_index < 0 or frame_index >= num_frames:
            self.log.warning(
                f"Frame index {frame_index} out of range [0, {num_frames-1}]"
            )
            return None

        # Extract counter 0, frame at index
        # Shape: (num_counters=1, num_frames, rows, cols)
        frame = self._loaded_frames[0, frame_index, :, :]  # Returns (rows, cols)
        self._current_frame_index = frame_index
        return frame

    def get_current_frame_index(self):
        """Get current frame index in loaded file

        @return int: Current frame index
        """
        if hasattr(self, "_current_frame_index"):
            return self._current_frame_index
        return 0

    def get_loaded_filepath(self):
        """Get path of currently loaded file

        @return str: Filepath, or None if no file loaded
        """
        if hasattr(self, "_loaded_filepath"):
            return self._loaded_filepath
        return None
