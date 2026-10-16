# -*- coding: utf-8 -*-

"""
This module acts like a laser.

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

import math
import time
import random

from qudi.core.configoption import ConfigOption
from qudi.interface.simple_laser_interface_dlnsec import SimpleLaserInterface
from qudi.interface.simple_laser_interface_dlnsec import (
    LaserState,
    ShutterState,
    ControlMode,
    TriggerMode,
)
from qudi.hardware.laser.dlnsec_laser import DLnsec


class DlnsecLaser(SimpleLaserInterface):
    """
    las = DlnsecLaser()
    las.get_power()

    Lazor dummy

    Example config for copy-paste:

    dlnsec_laser:
        module.Class: 'laser.dlnsec_laser_qudi.DlnsecLaser'
        options:
            port: 'COM4'
    """

    port_interface = ConfigOption(name="port", default="COM4", missing="warn")
    max_power_mw = ConfigOption(name="max_power_mw", default=110.0, missing="warn")

    def __init__(self, **kwargs):
        """ """
        super().__init__(**kwargs)
        self.lstate = LaserState.OFF
        self.shutter = ShutterState.NO_SHUTTER
        self.mode = ControlMode.POWER
        self.triggermode = TriggerMode.LAS
        self.current_setpoint = 0
        # DLNSEC power is controlled as a percentage of max output power.
        self.power_setpoint = 0.0

    def on_activate(self):
        """Activate module."""

        self.laser = DLnsec(self.port_interface)

    def on_deactivate(self):
        """Deactivate module."""
        self.laser.close()

    def get_power_range(self):
        """Return optical power range

        @return float[2]: power range (min, max)
        """
        return 0.0, 100.0

    def get_power(self):
        """Return laser power

        @return float: Laser power in mW
        """
        # The underlying DLnsec driver returns the device power setting in percent (0..100).
        # Convert that to mW based on the configured max power.
        return (float(self.laser.get_power()) / 100.0) * self.max_power_mw

    def get_power_setpoint(self):
        """Return optical power setpoint.

        @return float: power setpoint in percent of max power
        """
        return self.power_setpoint

    def set_power(self, power):
        """Set power setpoint.

        @param float power: power to set (percent of max power)
        """
        power_percent = float(power)
        power_percent = max(0.0, min(100.0, power_percent))
        self.power_setpoint = power_percent
        # DLnsec expects integer percent (0..100).
        self.laser.power(int(round(power_percent)))

    def get_current_unit(self):
        """Get unit for laser current.

        @return str: unit
        """
        return "%"

    def get_current_range(self):
        """Get laser current range.

        @return float[2]: laser current range
        """
        return 0, 100

    def get_current(self):
        """Get actual laser current

        @return float: laser current in current units
        """
        return 0

    def get_current_setpoint(self):
        """Get laser current setpoint

        @return float: laser current setpoint
        """
        return self.current_setpoint

    def set_current(self, current):
        """Set laser current setpoint

        @param float current: desired laser current setpoint
        """
        # DLNSEC GUI/hardware uses power(%) control. Keep current setpoint as an auxiliary value
        # without affecting the active power setpoint.
        self.current_setpoint = float(current)

    def allowed_control_modes(self):
        """Get supported control modes

        @return frozenset: set of supported ControlMode enums
        """
        # DLNSEC is operated via power; current mode is not supported.
        return frozenset({ControlMode.POWER})

    def get_control_mode(self):
        """Get the currently active control mode

        @return ControlMode: active control mode enum
        """
        return self.mode

    def set_control_mode(self, control_mode):
        """Set the active control mode

        @param ControlMode control_mode: desired control mode enum
        """
        self.mode = control_mode
        # modes = {1: "POW", 3: "LAS", 4: "INT", 5: "EXT", 6: "STOP"}
        # self.laser.set_mode(modes[self.mode])

    def allowed_trigger_modes(self):
        """Get supported trigger modes

        @return frozenset: set of supported TriggerMode enums
        """
        # return frozenset({TriggerMode.LAS, TriggerMode.INT, TriggerMode.EXT, TriggerMode.STOP})
        return {TriggerMode.LAS, TriggerMode.INT, TriggerMode.EXT, TriggerMode.STOP}

    def get_trigger_mode(self):
        """Get the currently active trigger mode

        @return TriggerMode: active trigger mode enum
        """
        return self.triggermode  # no hardware command for this

    def set_trigger_mode(self, trigger_mode):
        """Set the active trigger mode

        @param TriggerMode trigger_mode: desired trigger mode enum
        """
        self.triggermode = trigger_mode
        if trigger_mode == TriggerMode.LAS:
            self.laser.set_mode("LAS")
        elif trigger_mode == TriggerMode.INT:
            self.laser.set_mode("INT")
        elif trigger_mode == TriggerMode.EXT:
            self.laser.set_mode("EXT")
        else:
            self.laser.set_mode("STOP")

    def on(self):
        """Turn on laser.

        @return LaserState: actual laser state
        """
        time.sleep(1)
        self.laser.on()
        # self.laser.set_mode("LAS")
        self.lstate = LaserState.ON
        return self.lstate

    def off(self):
        """Turn off laser.

        @return LaserState: actual laser state
        """
        time.sleep(1)
        self.laser.off()
        self.lstate = LaserState.OFF
        return self.lstate

    def get_laser_state(self):
        """Get laser state

        @return LaserState: current laser state
        """
        return self.lstate

    def set_laser_state(self, state):
        """Set laser state.

        @param LaserState state: desired laser state enum
        """
        time.sleep(1)
        self.lstate = state
        if state == LaserState.ON:
            self.on()
        elif state == LaserState.OFF:
            self.off()
        return self.lstate

    def get_shutter_state(self):
        """Get laser shutter state

        @return ShutterState: actual laser shutter state
        """
        # DLNSEC has no shutter.
        return ShutterState.NO_SHUTTER

    def set_shutter_state(self, state):
        """Set laser shutter state.

        @param ShutterState state: desired laser shutter state
        """
        # DLNSEC has no shutter. Keep reporting NO_SHUTTER.
        self.shutter = ShutterState.NO_SHUTTER
        return self.shutter

    def get_temperatures(self):
        """Get all available temperatures.

        @return dict: dict of temperature names and value in degrees Celsius
        """
        return {"psu": 32.2 * random.gauss(1, 0.1), "head": 42.0 * random.gauss(1, 0.2)}

    def get_extra_info(self):
        """Multiple lines of dignostic information

        @return str: much laser, very useful
        """
        return "Best laser ever, 10/10 would fry eyeball again"
