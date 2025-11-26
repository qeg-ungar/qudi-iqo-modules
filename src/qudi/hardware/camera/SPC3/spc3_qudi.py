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
    """Hardware class for Andors SPC3

    Example config for copy-paste:

    andor_ultra_camera:
        module.Class: 'camera.andor.iXon897_ultra.IxonUltra'
        options:
            dll_location: 'C:\\camera\\andor.dll' # path to library file
            default_exposure: 1.0
            default_read_mode: 'IMAGE'
            default_temperature: -70
            default_cooler_on: True
            default_acquisition_mode: 'SINGLE_SCAN'
            default_trigger_mode: 'INTERNAL'

    """

    _camera_mode = ConfigOption("camera_mode", missing="error")
    _dll_location = ConfigOption("dll_location", missing="error")
    _default_exposure = ConfigOption("default_exposure", 0.02)
    _default_hardware_integration = ConfigOption("default_hardware_integration", 52)
    _default_NFrames = ConfigOption("default_NFrames", 1)
    _default_NIntegFrames = ConfigOption("default_NIntegFrames", 1000)
    _default_NCounters = ConfigOption("default_NCounters", 1)
    _default_Force8bit = ConfigOption("default_Force8bit", SPC3.State.DISABLED)
    _default_Half_array = ConfigOption("default_Half_array", SPC3.State.DISABLED)
    _default_Signed_data = ConfigOption("default_Signed_data", SPC3.State.DISABLED)
    _trigger_mode = ConfigOption("default_trigger_mode", 0)

    _HardwareIntegration = _default_hardware_integration
    _exposure = _default_exposure
    _NFrames = _default_NFrames
    _NIntegFrames = _default_NIntegFrames
    _NCounters = _default_NCounters
    _Force8bit = _default_Force8bit
    _Half_array = _default_Half_array
    _Signed_data = _default_Signed_data
    _HardwareIntegration_Normal = 1040  # 10.4 us
    _Nrows = 32
    _Ncols = 64

    _live = False
    _acquiring = False
    _continuous = False
    _camera_name = "SPC3"

    def on_activate(self):
        """Initialisation performed during activation of the module."""

        # Advanced Camera Mode
        if self._camera_mode == 1:
            self.spc3 = SPC3(1, "", self._dll_location)
            self.spc3.SetCameraPar(
                float(self._HardwareIntegration) * 10**8,  # in 10ns units #causes bug
                self._NFrames,
                self._NIntegFrames,
                self._NCounters,
                self._Force8bit,
                self._Half_array,
                self._Signed_data,
            )

        ### GATING OPTIONS FOR ADVANCED MODE ###
        # SetGateMode(self, counter, Mode):jup
        # SetGateValues(self, Shift, Length):
        # SetDualGate(self, DualGate_State, StartShift, FirstGateWidth, SecondGateWidth, Gap):
        # SetTripleGate(self,TripleGate_State,StartShift,FirstGateWidth,SecondGateWidth,ThirdGateWidth,Gap1,Gap2,):
        # SetCoarseGateValues(self, Counter, Start, Stop):

        # Normal Camera Mode
        else:
            self.spc3 = SPC3(0, "", self._dll_location)
            self.spc3.SetCameraPar(
                self._HardwareIntegration_Normal,
                self._NFrames,
                self._NIntegFrames,
                self._NCounters,
                self._Force8bit,
                self._Half_array,
                self._Signed_data,
            )
        
        if self._trigger_mode >= 0:
            self.spc3.SetSyncInState(SPC3.State.ENABLED, self._trigger_mode) # enable triggering (1 per trigger pulse)
            self.spc3.SetTriggerOutState(SPC3.TriggerMode.FRAME) # output trigger per frame

        self.spc3.ApplySettings()
        self._Ncols = self._Ncols >> self._Half_array

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
        return self.spc3._num_rows, self.spc3.row_size

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
        """Start a single acquisition

        @return bool: Success ?
        """
        if self._live:
            return False
        else:
            self._acquiring = True
            self.spc3.SnapGetImageBuffer()
            self._acquiring = False

        return True

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
        """Return an array of last acquired image.

        @return numpy array: image data in format [[row],[row]...]

        Each pixel might be a float, integer or sub pixels
        """

        image_array = np.zeros(self._Nrows * self._Ncols)
        if self._live:
            image_array = self.spc3.LiveGetImg()
        return image_array[0]  # counter1 frame

    def set_exposure(self, exposure):
        """Set the exposure time in seconds

        @param float time: desired new exposure time

        @return bool: Success?
        """
        self._exposure = exposure
        self.spc3.SetCameraPar(
            # self._exposure,
            65535,
            self._NFrames,
            self._NIntegFrames,
            self._NCounters,
            self._Force8bit,
            self._Half_array,
            self._Signed_data,
        )
        self.spc3.ApplySettings()
        return True

    def get_exposure(self):
        """Get the exposure time in seconds

        @return float exposure time
        """
        return self._exposure

    def get_actual_exposure(self):
        """Get the actual exposure time in seconds

        @return float exposure time
        """
        return self._NIntegFrames * (self._HardwareIntegration_Normal / 100) / 1000

    def set_hardware_integration(self, integration_ns):
        print(type(integration_ns))
        self.spc3.SetCameraPar(
            c_uint16(integration_ns),
            self._NFrames,
            self._NIntegFrames,
            self._NCounters,
            self._Force8bit,
            self._Half_array,
            self._Signed_data,
        )
        self.spc3.ApplySettings()
        return True

    def set_binning(self, binning):
        self._NIntegFrames = binning
        self.spc3.SetCameraPar(
            self._HardwareIntegration_Normal,
            self._NFrames,
            self._NIntegFrames,
            self._NCounters,
            self._Force8bit,
            self._Half_array,
            self._Signed_data,
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

    def background_subtraction(self):
        """Start background subtraction

        @return bool: Success ?
        """
        if self._live:
            return False
        else:
            self.spc3.SnapPrepare()
            self.spc3.SnapAcquire()
            BackgroundImg = self.spc3.AverageImg(1)
            self.spc3.SetBackgroundSubtraction(SPC3.State.DISABLED)
            self.spc3.ApplySettings()
            self.spc3.SetBackgroundImg(BackgroundImg)
            self.spc3.SetBackgroundSubtraction(SPC3.State.ENABLED)
            self.spc3.ApplySettings()
            return True

    def stop_background_subtraction(self):
        """Stop background subtraction

        @return bool: Success ?
        """
        if self._live:
            return False
        else:
            self.spc3.SetBackgroundSubtraction(SPC3.State.DISABLED)
            self.spc3.ApplySettings()
            return True

    def read_spc3_file(self, path):
        """read_spc3_file - Reads a .spc3 data file and converts it to an np array"""
        frames, header = self.spc3.ReadSPC3DataFile(path)
        return frames
