__all__ = ["PiProem"]

import asyncio
import numpy as np
from time import sleep

# ignore types until https://github.com/yaq-project/yaq-python/pull/82 is implemented
from yaqd_core import HasMapping, HasMeasureTrigger  # type: ignore

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
        self._channel_shapes:dict[str, tuple[int, ...]] = dict()

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

        # register properties
        self.set_exposure_time, self.get_exposure_time = self.gen_param("ExposureTime")
        self.set_readout_count, self.get_readout_count = self.gen_param("ReadoutCount")
        self.set_adc_analog_gain, self.get_adc_analog_gain = self.gen_param("AdcAnalogGain")
        self.set_em_gain, self.get_em_gain = self.gen_param("AdcEMGain")
        self.set_adc_quality, self.get_adc_quality = self.gen_param("AdcQuality")
        self.set_adc_speed, self.get_adc_speed = self.gen_param("AdcSpeed")

        # properties = [
        #     "ExposureTime",
        #     "AdcEMGain",
        #     "ReadoutCount",
        #     "AdcAnalogGain",
        #     "AdcSpeed",
        #     "AdcQuality",
        # ]
        # for prop in properties:
        #     setattr(self, f"set_{prop}", self.gen_set_param(prop))
        #     setattr(self, f"get_{prop}", self.get_get_param(prop))

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
                    self.logger.error(e)
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

        if roi.height % roi.y_binning != 0 or roi.width % roi.x_binning != 0:
            self.logger.error(
                """Pixel binning and extent(s) of roi are not compatible. Check there is no remainder in both width/x_bin and height/y_bin.
                      ***Leaving roi unchanged.***"""
            )
        elif self._state["spectrometer_mode"] == "spectral" and roi.x_binning != 1:
            self.logger.error(
                """You're in spectral mode and you wish to bin spectral axis, or have not changed x_binning from spatial mode yet.
                     Consider doing set_roi() and changing x_binning=1.
                     ***leaving roi unchanged.*** """
            )
        elif roi.bottom < roi.height:
            self.logger.error(
                """The height of ROI requested is too large for where beginning bottom pixel is indicated.
                     This would create a mapping with negative pixels and will not allow for image capture.
                     ***Leaving roi unchanged.*** """
            )
        else:
            self.proem.set_roi(**ui_to_native(roi)._asdict())
            # register new mappings
            native = self.proem.params.Rois.get_value()[0]
            roi_native = ROI_native(
                native.x, native.y, native.width, native.height, native.y_binning, native.x_binning
            )
            self._state["roi"] = native_to_ui(roi_native)._asdict()

            # TODO: better to do orientation stuff after the fact
            self._mappings["y_index"] = np.arange(
                self._state["roi"]["bottom"]
                - (self._state["roi"]["height"] // self._state["roi"]["y_binning"]),
                self._state["roi"]["bottom"],
                dtype="i2",
            )[:, None]
            self._mappings["x_index"] = np.arange(
                self._state["roi"]["left"],
                self._state["roi"]["left"]
                + (self._state["roi"]["width"] // self._state["roi"]["x_binning"]),
                dtype="i2",
            )[None, :]
            self._mappings["wavelengths"] = self._gen_mapping()[None, :]

            self._channel_shapes = {
                "image": (
                    self._state["roi"]["height"] // self._state["roi"]["y_binning"],
                    self._state["roi"]["width"] // self._state["roi"]["x_binning"],
                ),
            }
            # channel indexing is (y_index, x_index)

    def get_roi(self) -> dict:
        _roi = self.proem.params.Rois.get_value()[0]
        roi = ROI_native(*[getattr(_roi, k) for k in ROI_native._fields])
        return native_to_ui(roi)._asdict()

    def gen_param(self, param):
        my_param = self.proem.params.parameters[param]

        def set_parameter(val):
            try:
                # NOTE: to apply must use commit_parameters;
                # update_state takes care of this
                my_param.set_value(val)
            except self.PicamError as e:
                self.logger.error(e)

        def get_parameter():
            return my_param.get_value()

        return set_parameter, get_parameter

    def get_parameters(self) -> list[str]:
        return [p for p in self.proem._dev.parameters.keys()]

    def set_spectrometer_mode(self, mode: str):
        if mode == "spatial":
            # when going to spatial mode from spectral, there's not a good way to have the roi
            # return to the previous spatial roi since I need to change horizontal mappings
            # concurrently. I will live with this for now. It's another simple set_roi command
            # to get it back where the user wants it.
            self._mappings["x_index"] = np.arange(
                self._state["roi"]["left"],
                self._state["roi"]["left"]
                + (self._state["roi"]["width"] // self._state["roi"]["x_binning"]),
                dtype="i2",
            )[None, :]
            self._mappings["wavelengths"] = self._gen_mapping()[None, :]

            self._channel_shapes = {
                "image": (
                    self._state["roi"]["height"] // self._state["roi"]["y_binning"],
                    self._state["roi"]["width"] // self._state["roi"]["x_binning"],
                ),
            }
            self._state["spectrometer_mode"] = mode
        if mode == "spectral":
            if self._state["roi"]["x_binning"] != 1:
                print(
                    """You're now in spectral mode and would bin spectral axis with current roi settings.
                     Consider changing x_binning=1 via set_roi().
                     ***leaving spectrometer_mode unchanged.*** """
                )
            else:
                self.proem.set_roi(
                    y=0, height=512
                )  # sets roi on the camera level, not daemon level
                self._state["roi"] = {
                    "left": 0,
                    "width": 512,
                    "bottom": self._state["roi"]["bottom"],
                    "height": self._state["roi"]["height"],
                    "x_binning": self._state["roi"]["x_binning"],
                    "y_binning": self._state["roi"]["y_binning"],
                }  # sets roi on daemon level

                self._mappings["x_index"] = np.arange(
                    self._state["roi"]["left"],
                    self._state["roi"]["left"]
                    + (self._state["roi"]["width"] // self._state["roi"]["x_binning"]),
                    dtype="i2",
                )[None, :]
                self._mappings["wavelengths"] = self._gen_mapping()[None, :]

                self._channel_shapes = {
                    "image": (
                        self._state["roi"]["height"] // self._state["roi"]["y_binning"],
                        self._mappings["wavelengths"].size,
                    ),
                }
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

    def close(self):
        self.proem.close()


if __name__ == "__main__":
    PiProem.main()
