__all__ = ["PiProem"]

import asyncio
import numpy as np
import time

from yaqd_core import HasMapping, HasMeasureTrigger, IsSensor, IsDaemon
from instrumental.drivers.cameras.picam import sdk, PicamEnums, list_instruments, PicamError
from instrumental import Q_
from scipy.interpolate import interp1d


def process_frames(method, raw_arrs):
    # raw_arrs should be a 3D np array, with dim 0 being number of frames
    if method == "average" or method == 'mean':
        proc_arrs = raw_arrs[:].mean(axis=0)
    elif method == "sum":
        proc_arrs = raw_arrs[:].sum(axis=0)
    else:
        raise KeyError("sample processing method not recognized")
    return proc_arrs


class PiProem(HasMapping, HasMeasureTrigger, IsSensor, IsDaemon):
    _kind = "pi-proem"

    def __init__(self, name, config, config_filepath):
        super().__init__(name, config, config_filepath)
        if config.get("emulate"):
            self.logger.debug("Starting Emulated camera")
            sdk.connect_demo_camera(PicamEnums.Model.ProEMHS512BExcelon, "demo")

        self._channel_names = ["image"]
        self._channel_units = {"image": "counts"}

        self._channel_mappings = {"image": ["y_index", "x_index", "wavelengths"]}
        self._mapping_units = {"y_index": "None", "x_index": "None", "wavelengths": "nm"}

        # find devices
        deviceArray = list_instruments()
        if len(deviceArray) == 0:
            raise PicamError("No devices found.")

        # create sdk.PicamCamera() object
        self.proem = deviceArray[0].create()
        # set key parameters to default values upon startup
        self.set_roi({"left":0, "bottom":512, "width":512, "height":512, "x_binning":1, "y_binning":1})
        self.set_spectrometer_mode("spatial")
        # make the static wavelengths to pixel mapping an attribute of the daemon; don't update self._mappings as this changes between spatial and spectral
        self._mappings["wavelengths"] = self._gen_mapping()
        self.set_em_gain(1)
        self.set_exposure_time(33)
        self.set_readout_count(1)
        self.set_frame_processing_method("average")
        print("successful start up.")
        self._set_temperature()

    def set_roi(self, roi: dict):
        # because the camera is rotated 90 deg, all of the roi params will be flipped under the hood
        # so the output arrays and shapes make sense to the user as the camera is currently placed.
        # i.e. The goal is to have a new user never know the camera is rotated.
        # so, left <--> bottom
        # top <--> left
        # width <--> height
        # x_binning <--> y_binning
        if roi["height"] % roi["y_binning"] != 0 or roi["width"] % roi["x_binning"] != 0:
            print(
                """Pixel binning and extent(s) of roi are not compatible. Check there is no remainder in both width/x_bin and height/y_bin.
                      ***Leaving roi unchanged.***"""
            )
        elif self._state["spectrometer_mode"] == "spectral" and roi["x_binning"] != 1:
            print(
                """You're in spectral mode and you wish to bin spectral axis, or have not changed x_binning from spatial mode yet.
                     Consider doing set_roi() and changing x_binning=1.
                     ***leaving roi unchanged.*** """)
        elif roi["bottom"] < roi["height"]:
            print("""The height of ROI requested is too large for where beginning bottom pixel is indicated.
                     This would create a mapping with negative pixels and will not allow for image capture.
                     ***Leaving roi unchanged.*** """)
        else:
            self.proem.set_roi(x=512-roi["bottom"], y=roi["left"],
                               width=roi["height"], height=roi["width"],
                               x_binning=roi["y_binning"],
                               y_binning=roi["x_binning"])
        
            pld_roi = self.proem.params.Rois.get_value()[0]
            self._state["roi"] = {"left":pld_roi.y, "width": pld_roi.height,
                                  "bottom":512-pld_roi.x, "height":pld_roi.width,
                                  "x_binning":pld_roi.y_binning,
                                  "y_binning":pld_roi.x_binning}
            
            self._mappings["y_index"] = np.arange(self._state["roi"]["bottom"] - (self._state["roi"]["height"] // self._state["roi"]["y_binning"]), self._state["roi"]["bottom"], dtype="i2")[:, None]
            self._mappings["x_index"] = np.arange(self._state["roi"]["left"], self._state["roi"]["left"] + (self._state["roi"]["width"] // self._state["roi"]["x_binning"]), dtype="i2")[None, :]
            self._mappings["wavelengths"] = self._gen_mapping()[None, :]

            self._channel_shapes = {
                "image": (
                    self._state["roi"]["height"] // self._state["roi"]["y_binning"],
                    self._state["roi"]["width"] // self._state["roi"]["x_binning"],
                ),
            }
            # channel indexing is (y_index, x_index)

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

    def set_adc_analog_gain(self, gain: str):
        self.proem.params.AdcAnalogGain.set_value(getattr(PicamEnums.AdcAnalogGain, gain))
        self._state["adc_analog_gain"] = self.proem.params.AdcAnalogGain.get_value().name

    def get_adc_analog_gain(self):
        return self._state["adc_analog_gain"] 
    
    def set_adc_quality(self, quality: str):
        self.proem.params.AdcQuality.set_value(getattr(PicamEnums.AdcQuality, quality))
        self._state["adc_quality"] = self.proem.params.AdcQuality.get_value().name
        
    def get_adc_quality(self):
        return self._state["adc_quality"] 
    
    def set_adc_speed(self, speed: float):
        self.proem.params.AdcSpeed.set_value(speed)
        self._state["adc_speed"] = self.proem.params.AdcSpeed.get_value()
        
    def get_adc_speed(self):
        return self._state["adc_speed"] 
    
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

    def set_trigger_response(self, trigger_response: str):
        self.proem.params.TriggerResponse.set_value(
            getattr(PicamEnums.TriggerResponse, trigger_response)
        )
        self._state["trigger_response"] = self.proem.params.TriggerResponse.get_value().name

    def get_trigger_response(self):
        return self._state["trigger_response"]

    def set_frame_processing_method(self, method: str):
        self._state["frame_processing_method"] = method

    def get_frame_processing_method(self):
        return self._state["frame_processing_method"]

    def _gen_mapping(self):
        "get map corresponding to static aoi and wavelength range."
        # define input paramaters
        mm_per_pixel = 0.016
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
        out = out[self._mappings["x_index"][0][:]] # keep horizontal mappings equal size so wt5 file doesn't get confused
        return np.round(out, 2) # account for physical orientation of camera
    
    def _set_temperature(self):
        self.proem.params.SensorTemperatureSetPoint.set_value(
            self._config["sensor_temperature_setpoint"]
        )
        sensor_temp_status = self.proem.params.SensorTemperatureStatus.get_value().name
        if sensor_temp_status == "Locked":
            self.logger.info("Sensor temp stabilized.")
            self._state[
                "sensor_temperature"
            ] = self.proem.params.SensorTemperatureReading.get_value()
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
            time.sleep(5)
            diff = set_temp - sensor_temp
        self.logger.info("Sensor temp stabilized.")
        self._state["sensor_temperature"] = sensor_temp

    def get_sensor_temperature(self):
        return self.proem.params.SensorTemperatureReading.get_value()

    def close(self):
        self.proem.close()
    
    async def _grab_image(self, kwds, timeout): #timeout in ms
        print("about to start capture")
        self.proem.start_capture(**kwds)
        print("capture started")
        # putting this sleep in here is probably not the ideal way to fix the timeout problem -- having constant communication between bluesky, the daemon, instrumental, and 
        # picam would be better which is what I tried at first but it's just too complicated and there are many things happening under the hood (for picam) that I don't understand
        # well enough to get the code to work the ideal way. The sleep function basically is just saying "don't try to grab the data until the exposure is over"
        await asyncio.sleep(timeout.magnitude / 1000)
        try:
            print("about to get captured image")
            img = self.proem.get_captured_image()
        except Exception as e:
            print("yaqc error: ",  e)
            await asyncio.sleep(0.020)
        if not isinstance(img, np.ndarray):
            return np.asarray(img)
        else:
            return img

    async def _measure(self):
        kwds = {'n_frames': self.get_readout_count(),
                'exposure_time': Q_(self.get_exposure_time(), 'ms')}
        timeout = kwds['n_frames'] * kwds['exposure_time'] + Q_(500, 'ms')
        raw_arr = await self._grab_image(kwds, timeout)
        if kwds["n_frames"] != 1:
            print("about to return image. raw arr has shape: ", raw_arr.shape)
            return {"image": np.rot90(process_frames(self._state["frame_processing_method"], raw_arr), 1)}
        else:
            print("about to return image. raw arr has shape: ", raw_arr.shape)
            return {"image": np.rot90(raw_arr, 1)} #np.rot90 acctouns for physical rotation of camera

if __name__ == "__main__":
    PiProem.main()
