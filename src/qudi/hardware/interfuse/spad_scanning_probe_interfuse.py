from PySide2 import QtCore
import numpy as np

from qudi.interface.scanning_probe_interface import (
    ScanningProbeInterface,
    ScanConstraints,
    ScannerAxis,
    ScannerChannel,
    ScanData,
    ScanSettings,
    BackScanCapability,
)
from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption


class CameraScanningProbeInterfuse(ScanningProbeInterface):
    """
    Barebones interfuse for scanning with a camera and analog output (AO) stage.
    """

    _spad = Connector(
        name="spad", interface="CameraInterface"
    )  # Replace with your SPAD interface
    _laser = Connector(name="laser", interface="LaserInterface")
    _ao = Connector(
        name="analog_output", interface="ProcessSetpointInterface"
    )  # Analog output for stage

    _position_ranges = ConfigOption(
        name="position_ranges",
        default={"x": [0, 100e-6], "y": [0, 100e-6]},
        missing="error",
    )
    _resolution_ranges = ConfigOption(
        name="resolution_ranges",
        default={"x": [1, 100], "y": [1, 100]},
        missing="error",
    )
    _ao_channel_mapping = ConfigOption(
        name="ao_channel_mapping", default={"x": "ao0", "y": "ao1"}, missing="error"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._scan_data = None
        self._constraints = None
        self._target_pos = {"x": 0.0, "y": 0.0}

    def on_activate(self):
        # Setup constraints for axes and camera channel
        axes = [
            ScannerAxis(
                name="x",
                unit="m",
                position=self._make_constraint("x", self._position_ranges),
                resolution=self._make_constraint(
                    "x", self._resolution_ranges, enforce_int=True
                ),
            ),
            ScannerAxis(
                name="y",
                unit="m",
                position=self._make_constraint("y", self._position_ranges),
                resolution=self._make_constraint(
                    "y", self._resolution_ranges, enforce_int=True
                ),
            ),
        ]
        channels = [ScannerChannel(name="camera", unit="counts", dtype="float64")]
        self._constraints = ScanConstraints(
            axis_objects=tuple(axes),
            channel_objects=tuple(channels),
            back_scan_capability=BackScanCapability.NONE,
            has_position_feedback=False,
            square_px_only=False,
        )

    def _make_constraint(self, axis, ranges, enforce_int=False):
        from qudi.util.constraints import ScalarConstraint

        return ScalarConstraint(
            default=ranges[axis][0], bounds=tuple(ranges[axis]), enforce_int=enforce_int
        )

    @property
    def constraints(self):
        return self._constraints

    def reset(self):
        pass

    @property
    def scan_settings(self):
        if self._scan_data:
            return self._scan_data.settings
        else:
            return None

    @property
    def back_scan_settings(self):
        return None

    def configure_scan(self, settings: ScanSettings):
        self._constraints.check_settings(settings)
        self._scan_data = ScanData.from_constraints(settings, self._constraints)

    def configure_back_scan(self, settings: ScanSettings):
        pass

    def move_absolute(self, position, velocity=None, blocking=False):
        # Move the stage using analog output, similar to ni_scanning_probe_interfuse
        ao = self._ao()
        for axis in position:
            if axis in self._ao_channel_mapping:
                channel = self._ao_channel_mapping[axis]
                value = float(position[axis])
                ao.set_setpoint(channel, value)
        self._target_pos = position.copy()
        return self._target_pos

    def move_relative(self, distance, velocity=None, blocking=False):
        pos = {ax: self._target_pos[ax] + distance[ax] for ax in distance}
        return self.move_absolute(pos, velocity=velocity, blocking=blocking)

    def get_target(self):
        return self._target_pos

    def get_position(self):
        # No feedback, just return target
        return self._target_pos

    def start_scan(self):
        if self._scan_data is None:
            self.log.error("Scan Data is None. Configure scan first.")
            return
        self._start_scan()

    # @QtCore.Slot()
    # def _start_scan(self):
    #     # Simple scan loop: move stage, acquire image, store in ScanData
    #     settings = self._scan_data.settings
    #     x_vals = np.linspace(
    #         settings.range[0][0], settings.range[0][1], settings.resolution[0]
    #     )
    #     y_vals = np.linspace(
    #         settings.range[1][0], settings.range[1][1], settings.resolution[1]
    #     )
    #     images = np.zeros(
    #         (settings.resolution[0], settings.resolution[1], 32, 32), dtype=np.float32
    #     )
    #     for i, x in enumerate(x_vals):
    #         for j, y in enumerate(y_vals):
    #             pos = {"x": float(x), "y": float(y)}
    #             self.move_absolute(pos, blocking=True)
    #             img = self._camera().start_single_acquisition()
    #             images[i, j] = img
    #     self._scan_data.data = {"camera": images}
    def get_frames(self, n_frames=1, background_subtract=True):
        """
        Acquire n_frames from the SPAD/camera, optionally subtracting background if enabled.
        Returns a numpy array of shape (n_frames, height, width) or (height, width) if n_frames==1.
        """
        spad = self._spad()
        spad._NFrames = n_frames
        frames = spad.start_single_acquisition()
        frames = np.array(frames).astype('float32')

        # Handle background subtraction if enabled
        if background_subtract and getattr(spad, "_background_subtraction_enabled", False):
            if not hasattr(spad, "_background_image") or spad._background_image is None:
                raise ValueError("Background subtraction is enabled, but no background image is set.")
            h, w = spad.get_size() if hasattr(spad, "get_size") else frames.shape[-2:]
            bg_frame = np.array(spad._background_image).reshape(h, w)
            if frames.ndim == 3:
                frames = frames - bg_frame
                frames = np.clip(frames, 0, None)
            else:
                frames = frames - bg_frame
                frames = np.clip(frames, 0, None)

        if n_frames == 1 and frames.ndim == 3:
            return frames[0]
        return frames
    
    @QtCore.Slot()
    def _start_scan(self):
        # Z-scan: move stage in Z, acquire images, store in ScanData
        settings = self._scan_data.settings

        # Get scan axis info
        z_idx = None
        for idx, axis in enumerate(settings.axes):
            if axis == "z":
                z_idx = idx
                break
        if z_idx is None:
            self.log.error("No 'z' axis found in scan settings.")
            return

        # Build Z scan sequence
        z_range = settings.range[z_idx]
        z_res = settings.resolution[z_idx]
        z_vals = np.linspace(z_range[0], z_range[1], z_res)

        # Get current position for x/y (keep fixed)
        pos_dict = {ax: float(val) for ax, val in zip(settings.axes, settings.position)}
        if "x" not in pos_dict:
            pos_dict["x"] = 0.0
        if "y" not in pos_dict:
            pos_dict["y"] = 0.0

        # Image shape (assume 32x32, or query from camera)
        img_shape = (32, 32)
        if hasattr(self._spad(), "get_size"):
            img_shape = self._spad().get_size()

        # Preallocate image stack
        img_samples_Z = np.zeros((z_res, img_shape[0], img_shape[1]), dtype=np.float32)

        for idx, z_sample in enumerate(z_vals):
            pos_dict["z"] = float(z_sample)
            self.move_absolute(pos_dict, blocking=True)
            img = self._spad().start_single_acquisition()
            # If camera returns a batch, take the first frame or mean
            if img.ndim == 3 and img.shape[0] > 1:
                img = img[0]
            img_samples_Z[idx, :, :] = img.astype(np.float32)
            self.log.info(f"Captured frame {idx+1}/{z_res} at z={z_sample:.3e}")

        self._scan_data.data = {"camera": img_samples_Z}

    def stop_scan(self):
        pass

    def get_scan_data(self):
        return self._scan_data

    def get_back_scan_data(self):
        return None

    def emergency_stop(self):
        pass
