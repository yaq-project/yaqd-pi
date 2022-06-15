__all__ = ["PiProem"]

import asyncio

import numpy as np

from yaqd_core import HasMapping, HasMeasureTrigger, IsSensor, IsDaemon
from instrumental.drivers.cameras.picam import sdk, PicamEnums, list_instruments, PicamError
from instrumental import Q_


class PiProem(HasMapping, HasMeasureTrigger, IsSensor, IsDaemon):
    _kind = "pi-proem"

    def __init__(self, name, config, config_filepath):
        super().__init__(name, config, config_filepath)
        if config.get("emulate"):
            self.logger.debug("Starting Emulated camera")
            sdk.connect_demo_camera(PicamEnums.Model.ProEMHS512BExcelon, "demo")
        self._channel_names = ["image"]
        self._channel_mappings = {"image": ["y_index", "x_index"]}
        self._mapping_units = {"y_index": "None", "x_index": "None"}
        self._channel_units = {"image": "counts"}

        # find devices
        deviceArray = list_instruments()
        if len(deviceArray) == 0:
            raise PicamError("No devices found.")

        # create sdk.PicamCamera() object
        self.proem = deviceArray[0].create()
        # set roi to default values upon startup
        self.set_roi(
            {"left": 0, "top": 0, "width": 512, "height": 512, "x_binning": 1, "y_binning": 1}
        )

        self._set_temperature()

    def set_roi(self, roi):
        if roi["width"] % roi["x_binning"] != 0 or roi["height"] % roi["y_binning"] != 0:
            print(
                """Pixel binning and extent(s) of roi are not compatible. Check there is no remainder in both width/x_bin and height/y_bin.
                      ***Leaving roi unchanged.***"""
            )
        else:
            self.proem.set_roi(
                x=roi["left"],
                y=roi["top"],
                width=roi["width"],
                height=roi["height"],
                x_binning=roi["x_binning"],
                y_binning=roi["y_binning"],
            )

            pld_roi = self.proem.params.Rois.get_value()[0]
            self._state["roi"] = {
                "left": pld_roi.x,
                "width": pld_roi.width,
                "top": pld_roi.y,
                "height": pld_roi.height,
                "x_binning": pld_roi.x_binning,
                "y_binning": pld_roi.y_binning,
            }
            self._mappings = {
                "y_index": np.arange(
                    self._state["roi"]["top"],
                    self._state["roi"]["top"]
                    + self._state["roi"]["height"] // self._state["roi"]["y_binning"],
                    dtype="i2",
                )[:, None],
                "x_index": np.arange(
                    self._state["roi"]["left"],
                    self._state["roi"]["left"]
                    + self._state["roi"]["width"] // self._state["roi"]["x_binning"],
                    dtype="i2",
                )[None, :],
            }
            # if binning != 1 the pixel indices will be effected. E.g. for roi of 512, 512 with y_bin=2, x_bin=1 the mappings
            # will give an x_index array out of 0, 1, ..., 512 and y_index an array of 0, 1, ... 256. So all the pixels in an array
            # which has been binned EXCEPT the first will be effected.

            self._channel_shapes = {
                "image": (
                    self._state["roi"]["height"] // self._state["roi"]["y_binning"],
                    self._state["roi"]["width"] // self._state["roi"]["x_binning"],
                )
            }
            # For an roi of left=0,top=0,width=512,height=512,x_bin=2,y_bin=4 the grab_image returns an array with shape (128, 256)
            # which is the opposite of what I would think. I believe for this I will have to change the channel_mappings to
            # y_index, x_index. This isn't a big deal it will just take some getting used to. But it actually makes sense if you
            # think about it from a matrix/(row, col) perspective so I actually kinda like it.

    def get_roi(self):
        return self._state["roi"]

    def set_em_gain(self, em_gain: int):
        self.proem.params.AdcEMGain.set_value(em_gain)
        self._state["em_gain"] = self.proem.params.AdcEMGain.get_value()

    def get_em_gain(self):
        return self._state["em_gain"]

    def set_exposure_time(self, exposure_time: float):
        self.proem.params.ExposureTime.set_value(exposure_time)
        self._state["exposure_time"] = self.proem.params.ExposureTime.get_value()

    def get_exposure_time(self):
        return self._state["exposure_time"]

    def set_readout_count(self, readout_count: int):
        self.proem.params.ReadoutCount.set_value(readout_count)
        self._state["readout_count"] = self.proem.params.ReadoutCount.get_value()

    def get_readout_count(self):
        return self._state["readout_count"]

    # chose to use readout_count as terminology equivalent to # of frames recorded per PICam custom.
    # in instrumental there is a distinction between n_frames and readout_count where readout_count is
    # essentially the number of scans to do.

    def set_adc_analog_gain(self, gain: str):
        self.proem.params.AdcAnalogGain.set_value(getattr(PicamEnums.AdcAnalogGain, gain))
        self._state["adc_analog_gain"] = self.proem.params.AdcAnalogGain.get_value().name

    def get_adc_analog_gain(self):
        return self._state["adc_analog_gain"]

    def _set_temperature(self):
        self.proem.params.SensorTemperatureSetPoint.set_value(
            self._config["sensor_temperature_setpoint"]
        )
        sensor_temp_status = self.proem.params.SensorTemperatureStatus.get_value().name
        if sensor_temp_status == "Locked":
            self.logger.info("Sensor temp stabilized.")
        else:
            self._loop.run_in_executor(None, self._check_temp_stabilized)

    def _check_temp_stabilized(self):
        set_temp = self.proem.params.SensorTemperatureSetPoint.get_value()
        sensor_temp = self.proem.params.SensorTemperatureReading.get_value()
        diff = set_temp - sensor_temp
        while abs(diff) > 0.5:
            self.logger.info(
                f"Sensor is cooling.\
                             Target: {set_temp} C. Current: {sensor_temp} C."
            )
            set_temp = (
                self.proem.params.SensorTemperatureSetPoint.get_value()
            )  # call again just to make sure
            sensor_temp = self.proem.params.SensorTemperatureReading.get_value()
            diff = set_temp - sensor_temp

        sensor_temp_status = self.proem.params.SensorTemperatureStatus().name

    def get_sensor_temperature(self):
        return self.proem.params.SensorTemperatureReading.get_value()

    def close(self):
        self.proem.close()

    # The below generates a pixel-to-wavelength mapping given an angle of incidence
    # on the prism and a desired wavelength range. It will only map onto 512 pixels.
    # I'm positive this is not the cleanest implementation, but it's a start.
    # def _gen_mapping(self):
    #     from scipy.interpolate import interp1d
    #     n_air = 1.0003
    #     alpha = np.radians(60) # angle of prism apex
    #     theta_0_deg = self._config["prism_AOI"] # angle of incidence
    #     theta_0 = np.radians(theta_0_deg)
    #     d = 85 # mm; focal length of spectrometer lenses
    #     num_pixels = 512
    #     mm_per_pixel = 0.016

    #     min_lam = self._config["spectral_axis_range"][0]
    #     max_lam = self._config["spectral_axis_range"][1]
    #     lam = np.linspace(min_lam, max_lam, 2048) # microns for Sellmeier equation
    #     lam_nm = lam * 1000

    #     def n_F2(lam_nm): #lam in nm
    #         lam = lam_nm / 1000
    #         A = (1.34533359 * lam**2) / (lam**2 - 0.00997743871)
    #         B = (0.209073176 * lam**2) / (lam**2 - 0.0470450767)
    #         C = (0.937357162 * lam**2) / (lam**2 - 111.886764)
    #         n = np.sqrt(1 + A + B + C)
    #         return n

    #     n = n_F2(lam_nm)
    #     # --- calculates spatial displacement for given color and microscope params ---
    #     theta_0p = np.arcsin((n_air / n) * np.sin(theta_0))
    #     beta = np.radians(90) - theta_0p
    #     gamma = np.radians(180) - (beta + alpha)
    #     theta_1 = np.radians(90) - gamma
    #     theta_1p = np.arcsin((n / n_air) * np.sin(theta_1))
    #     theta_2 = theta_1p - alpha
    #     yy = d * np.tan(theta_2)
    #     y = np.abs(yy-yy.max())
    #     # --- interpolates spatial displacement calculated above onto evenly spaced detector ---
    #     pix = y / mm_per_pixel # 16 um per pixel
    #     f = interp1d(pix, lam_nm)
    #     pixels = np.arange(num_pixels)
    #     lam_nm_new = f(pixels)
    #     return lam_nm_new

    def _grab_image(self, kwds, timeout):
        img = self.proem.grab_image(**kwds, timeout=timeout)
        if not isinstance(img, np.ndarray):
            return np.asarray(img)
        else:
            return img

    async def _measure(self):
        kwds = {
            "n_frames": self.get_readout_count(),
            "exposure_time": Q_(self.get_exposure_time(), "ms"),
        }
        timeout = kwds["n_frames"] * kwds["exposure_time"] + Q_(50, "ms")
        img = self._grab_image(kwds, timeout)
        return {"image": img}

    # When the camera can be successfully operated in spectroscopy mode, there
    # should be an option to return a "spectral_image" with the x pixels returned
    # as the correct wavelenght value, and y pixels still spatial. May need to
    # eventually account for tilt along vertical axis. (This will be done with
    # the gen_mappings method-will need to figure out how to get the spatial
    # and spectral modes to work together though.)

    async def update_state(self):
        """Continually monitor and update the current daemon state."""
        while True:
            sensor_temp_status = self.proem.params.SensorTemperatureStatus.get_value().name
            if sensor_temp_status == "Locked":
                self.logger.debug("Sensor temp stabilized.")
            else:
                self.logger.error("Sensor temp not stabilized. Something is wrong.")
            await asyncio.sleep(60)


if __name__ == "__main__":
    PiProem.main()
