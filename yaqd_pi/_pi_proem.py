__all__ = ["PiProem"]

import asyncio
import numpy as np
from time import sleep

from yaqd_core import HasMapping, HasMeasureTrigger

from scipy.interpolate import interp1d  # type: ignore
from ._roi import ROI_native, ROI_UI, ui_to_native, native_to_ui


class PiProem(HasMapping, HasMeasureTrigger):
    _kind = "pi-proem"

    def __init__(self, name, config, config_filepath):
        super().__init__(name, config, config_filepath)

        if config.get("emulate"):
            from instrumental.drivers.cameras.picam import sdk  # type: ignore

            self.logger.info("Starting Emulated camera")
            sdk.connect_demo_camera(PicamEnums.Model.ProEMHS512BExcelon, "demo")

        self._channel_names = ["mean"]
        self._channel_units = {"mean": "counts"}

        self._channel_mappings = {"mean": ["y_index", "x_index", "wavelengths"]}
        self._mapping_units = {"y_index": "None", "x_index": "None", "wavelengths": "nm"}

        # somehow instrumental overrides our logger...
        # I need to import these only after our daemon logger is initiated
        # DDK 2025-06-05
        from instrumental.drivers.cameras.picam import (
            list_instruments,
            PicamError,
            PicamCamera,
            PicamEnums,
        )  # type: ignore

        self.PicamEnums = PicamEnums
        self.PicamError = PicamError
        # open camera
        deviceArray = list_instruments()
        if len(deviceArray) == 0:
            raise PicamError("No devices found.")
        self.proem: PicamCamera = deviceArray[0].create()

        self.parameters = list(self.proem.params.parameters.keys())
        self.enum_keys = set(self.get_parameters()) & set(self.PicamEnums._get_enum_dict())

        # register properties
        self.set_exposure_time, self.get_exposure_time, _ = self.gen_param("ExposureTime")
        self.set_readout_count, self.get_readout_count, _ = self.gen_param("ReadoutCount")
        self.set_analog_gain, self.get_analog_gain, self.get_analog_gain_types = self.gen_param(
            "AdcAnalogGain"
        )
        self.set_adc_quality, self.get_adc_quality, self.get_adc_quality_types = self.gen_param(
            "AdcQuality"
        )
        self.set_adc_speed, self.get_adc_speed, _ = self.gen_param("AdcSpeed")
        self.set_em_gain, self.get_em_gain, _ = self.gen_param("AdcEMGain")

        self.set_roi(ROI_UI()._asdict())
        # make the static wavelengths to pixel mapping an attribute of the daemon;
        # don't update self._mappings as this changes between spatial and spectral
        self._mappings["wavelengths"] = self._gen_mapping()
        # initialize with default parameters
        self._set_temperature()

    async def update_state(self):
        """commit parameters when it is safe to do so"""
        while True:
            if not self._busy:
                if not self.proem._dev.AreParametersCommitted():
                    self.proem.commit_parameters()
                await asyncio.sleep(0.5)
            else:
                try:
                    await asyncio.wait_for(self._not_busy_sig.wait(), 1)
                except asyncio.TimeoutError:
                    continue

    async def _measure(self):
        readouts = []  # readouts[readout][readout_frame][frame roi]
        running = True
        expected_readouts = self.get_readout_count()
        wait = min(self.get_exposure_time(), 50)  # ms
        self.proem._dev.StartAcquisition()
        while running:
            try:
                # wait is blocking, so use short waits and ignore timeouts
                available_data, status = self.proem._dev.WaitForAcquisitionUpdate(wait)
            # except self.PicamError as e:
            except Exception as e:
                if e.code == self.PicamEnums.Error.TimeOutOccurred:
                    await asyncio.sleep(0)
                    self.logger.debug("waiting")
                    continue
                else:
                    self.proem._dev.StopAcquisition()
                    self.logger.error(exc_info=e)
                    raise e
            else:
                running = status.running
                self.logger.debug(f"running {running}, readouts {available_data.readout_count}")
                if available_data.readout_count > 0:
                    readouts.extend(self.proem._extract_available_data(available_data, copy=True))
        if (actual := len(readouts)) != expected_readouts:
            self.logger.warning(f"expected {expected_readouts} images, but got {actual}")
        return {"mean": np.rot90(np.asarray(readouts).mean(axis=(0, 1, 2)), 1)}

    def _gen_mapping(self):
        """get map corresponding to static aoi and wavelength range."""
        # define input paramaters
        mm_per_pixel = self.proem.params.PixelHeight.get_value() / 1e3
        v = 200  # g/mm; grating groove spacing
        a = (v * 10**-3) ** -1  # um/g
        aoi = np.radians(self._config["grating_aoi"])
        ws = np.linspace(
            self._config["spectral_range"][0], self._config["spectral_range"][1], 2048
        )  # um
        f = 85  # mm; focal length of focusing lens
        n = 1.6  # rough grating index of refraction
        # calculate output angles
        aods = np.arcsin(n * np.sin(aoi) - (ws / a))
        # convert angle to space
        xs = f * np.tan(aods)
        rel_xs = np.abs(xs - xs.min())  # start from 0 and count up in length
        # map spatially correlated wavelengths onto detector by interpolating
        spec_divided = rel_xs / mm_per_pixel
        g = interp1d(spec_divided, ws)
        num_pixels = np.round(spec_divided[0], 0)
        pixels = np.arange(num_pixels)
        out = g(pixels) * 1000
        out = out[
            self._mappings["x_index"][0][:]
        ]  # keep horizontal mappings equal size so wt5 file doesn't get confused
        return np.round(out, 2)  # account for physical orientation of camera

    # --- properties ------------------------------------------------------------------------------

    def set_roi(self, _roi: dict[str, int]):
        roi = ROI_UI(**_roi)
        try:
            # assert roi.height % roi.y_binning == 0 and roi.width % roi.x_binning == 0
            # assert not (self._state["spectrometer_mode"] == "spectral" and roi.x_binning != 1)
            assert roi.bottom >= roi.height
        except AssertionError as e:
            self.logger.error(e, exc_info=True)
            raise e

        self.proem.set_roi(**ui_to_native(roi)._asdict())
        # register new mappings
        # TODO: indexing is weird?
        new = self.get_roi()  # ui

        self._mappings["y_index"] = np.arange(
            new["bottom"] - (new["height"] // new["y_binning"]),
            new["bottom"],
            dtype="i2",
        )[:, None]
        self._mappings["x_index"] = np.arange(
            new["left"],
            new["left"] + (new["width"] // new["x_binning"]),
            dtype="i2",
        )[None, :]
        self._mappings["wavelengths"] = self._gen_mapping()[None, :]

        # channel indexing is (y_index, x_index)
        # ignore 2D shape types until https://github.com/yaq-project/yaq-python/pull/82 is implemented
        self._channel_shapes = {
            "mean": (
                new["height"] // new["y_binning"],
                new["width"] // new["x_binning"],
            ),  # type: ignore
        }

    def get_roi(self) -> dict:
        _roi = self.proem.params.Rois.get_value()[0]
        roi = ROI_native(*[getattr(_roi, k) for k in ROI_native._fields])
        return native_to_ui(roi)._asdict()

    def gen_param(self, param):
        """dynamic setter, getter creation for parameters"""
        my_param = self.proem.params.parameters[param]

        if param in self.enum_keys:
            param_enums = getattr(self.PicamEnums, param)
            _set = lambda val: my_param.set_value(param_enums[val])
            _get = lambda _: my_param.get_value().name
            parameter_type = lambda _: [i.name for i in param_enums]
        else:
            _set = lambda val: my_param.set_value(val)
            _get = lambda _: my_param.get_value()
            parameter_type = None

        # wrap functions with error reporting
        def get_parameter():
            try:
                value = _get(None)
            except Exception as e:
                self.logger.error(f"get {param}")
                self.logger.error(e, exc_info=True)
                raise e
            return value

        def set_parameter(val):
            try:
                _set(val)
            except Exception as e:
                self.logger.error(f"set {param} {val}")
                self.logger.error(e, exc_info=True)
                raise e

        return set_parameter, get_parameter, parameter_type

    def get_parameters(self) -> list[str]:
        return self.parameters

    def set_spectrometer_mode(self, mode: str):
        # In its current implementation,
        # spectrometer_mode changes the ROI to maximum along spectral axis,
        # and is a plot hint to communicate what mapping to use
        # future plan is to remove the automatic mapping and retain old ROI
        # DDK 2025-06-10
        roi = ROI_UI(**self.get_roi())
        if mode == "spatial":
            self._mappings["x_index"] = (
                np.arange(0, roi.width // roi.x_binning, dtype="i2")[None, :] + roi.left
            )
            self._mappings["wavelengths"] = self._gen_mapping()[None, :]

            self._state["spectrometer_mode"] = mode
        if mode == "spectral":
            if roi.x_binning == 1:
                self.logger.error("need x_binning ==1")
                raise ValueError
            self.proem.set_roi(y=0, height=512)  # sets roi on the camera level, not daemon level
            roi = ROI_UI(**self.get_roi())

            self._mappings["x_index"] = (
                np.arange(
                    0,
                    roi.width // roi.x_binning,
                    dtype="i2",
                )[None, :]
                + roi.left
            )
            self._mappings["wavelengths"] = self._gen_mapping()[None, :]
            self._state["spectrometer_mode"] = mode

    def get_spectrometer_mode(self):
        return self._state["spectrometer_mode"]

    def _set_temperature(self):
        self.proem.params.SensorTemperatureSetPoint.set_value(
            self._config["sensor_temperature_setpoint"]
        )
        sensor_temp_status = self.proem.params.SensorTemperatureStatus.get_value().name
        if sensor_temp_status == "Locked":
            self.logger.info("Sensor temp stabilized.")
            self._state["sensor_temperature"] = (
                self.proem.params.SensorTemperatureReading.get_value()
            )
        else:
            self._loop.run_in_executor(None, self._check_temp_stabilized())

    def _check_temp_stabilized(self):
        set_temp = self.proem.params.SensorTemperatureSetPoint.get_value()
        sensor_temp = self.proem.params.SensorTemperatureReading.get_value()
        diff = set_temp - sensor_temp
        while abs(diff) > 0.1:
            self.logger.info(
                f"Sensor is cooling.\
                             Target: {set_temp} C. Current: {sensor_temp} C."
            )
            sensor_temp = self.proem.params.SensorTemperatureReading.get_value()
            self._state["sensor_temperature"] = sensor_temp
            sleep(5)
            diff = set_temp - sensor_temp
        self.logger.info("Sensor temp stabilized.")
        self._state["sensor_temperature"] = sensor_temp

    def get_sensor_temperature(self):
        return self.proem.params.SensorTemperatureReading.get_value()

    def get_exposure_time_units(self):
        return "ms"

    def get_adc_speed_units(self):
        return "MHz"

    def get_em_gain_limits(self):
        return [1.0, 100.0]

    def close(self):
        self.proem.close()


if __name__ == "__main__":
    PiProem.main()
