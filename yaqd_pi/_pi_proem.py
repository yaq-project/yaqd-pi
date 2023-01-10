__all__ = ["PiProem"]

import asyncio

import numpy as np

from yaqd_core import HasMapping, HasMeasureTrigger, IsSensor, IsDaemon
from instrumental.drivers.cameras.picam import sdk, PicamEnums, list_instruments, PicamError
from instrumental import Q_
from scipy.interpolate import interp1d


class PiProem(HasMapping, HasMeasureTrigger, IsSensor, IsDaemon):
    _kind = "pi-proem"

    def __init__(self, name, config, config_filepath):
        super().__init__(name, config, config_filepath)
        if config.get("emulate"):
            self.logger.debug("Starting Emulated camera")
            sdk.connect_demo_camera(PicamEnums.Model.ProEMHS512BExcelon, "demo")
            
        self._channel_names = ["image"]
        self._channel_units = {"image": "counts"}
        self._channel_mappings = {"image": ["y_index", "x_index", "wavelength"]}
        self._mapping_units = {"y_index": "None", "x_index": "None", "wavelength": "nm"}
        
        # find devices
        deviceArray = list_instruments()
        if len(deviceArray) == 0:
            raise PicamError("No devices found.")
            
        # create sdk.PicamCamera() object
        self.proem = deviceArray[0].create()
        # make the static wavelength to pixel mapping an attribute of the daemon; don't update self._mappings as this changes between spatial and spectral
        self.static_mapping = self._gen_mapping()
        # set key parameters to default values upon startup
        self.set_spectrometer_mode("spatial")
        self.set_roi({"left":0, "top":0, "width":512, "height":512, "x_binning":1, "y_binning":1})
        self.set_em_gain(1)
        self.set_exposure_time(33)
        self.set_readout_count(1)
    
        self._set_temperature()
        
    def set_roi(self, roi):
        if roi["width"] % roi["x_binning"] != 0 or roi["height"] % roi["y_binning"] != 0:
            print("""Pixel binning and extent(s) of roi are not compatible. Check there is no remainder in both width/x_bin and height/y_bin.
                      ***Leaving roi unchanged.***""")
        elif self._state["spectrometer_mode"] == "spectral" and roi["x_binning"] != 1:
            print("""You're in spectral mode and you wish to bin spectral axis, or have not changed x_binning from spatial mode yet.
                     Consider doing set_roi() and changing x_binning=1.
                     ***leaving roi unchanged.*** """)
        else:
            self.proem.set_roi(x=roi["left"], y=roi["top"], width=roi["width"],height=roi["height"],
                               x_binning=roi["x_binning"],
                               y_binning=roi["y_binning"])
        
            pld_roi = self.proem.params.Rois.get_value()[0]
            self._state["roi"] = {"left":pld_roi.x, "width": pld_roi.width,
                                  "top":pld_roi.y, "height":pld_roi.height,
                                  "x_binning":pld_roi.x_binning,
                                  "y_binning":pld_roi.y_binning}
            if self._state["spectrometer_mode"] == "spatial":
                self._mappings = {"y_index": np.arange(
                               self._state["roi"]["top"], self._state["roi"]["top"] + self._state["roi"]["height"] // self._state["roi"]["y_binning"], dtype="i2")[:, None],
                              "x_index": np.arange(
                               self._state["roi"]["left"], self._state["roi"]["left"] + self._state["roi"]["width"] // self._state["roi"]["x_binning"], dtype="i2")[None, :]
                              }
            if self._state["spectrometer_mode"] == "spectral":
                self._mappings = {"y_index": np.arange(
                              self._state["roi"]["top"], self._state["roi"]["top"] + self._state["roi"]["height"] // self._state["roi"]["y_binning"], dtype="i2")[:, None],
                             "wavelength": self.static_mapping[None, :]
                             } 
            self._channel_shapes = {"image": (self._state["roi"]["height"] // self._state["roi"]["y_binning"], self._state["roi"]["width"] // self._state["roi"]["x_binning"]),
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
    
    def set_spectrometer_mode(self, mode: str):
        if mode == "spatial":
            self._mappings = {"y_index": np.arange(
                           self._state["roi"]["top"], self._state["roi"]["top"] + self._state["roi"]["height"] // self._state["roi"]["y_binning"], dtype="i2")[:, None],
                          "x_index": np.arange(
                           self._state["roi"]["left"], self._state["roi"]["left"] + self._state["roi"]["width"] // self._state["roi"]["x_binning"], dtype="i2")[None, :]
                          }
            self._state["spectrometer_mode"] = mode
        if mode == "spectral":
            if self._state["roi"]["x_binning"] != 1:
                print("""You're now in spectral mode and would bin spectral axis with current roi settings.
                     Consider changing x_binning=1 via set_roi().
                     ***leaving spectrometer_mode unchanged.*** """)
            else:
                self._mappings = {"y_index": np.arange(
                     self._state["roi"]["top"], self._state["roi"]["top"] + self._state["roi"]["height"] // self._state["roi"]["y_binning"], dtype="i2")[:, None],
                    "wavelength": self.static_mapping[None, :]
                    }
                self._state["spectrometer_mode"] = mode
        
    def get_spectrometer_mode(self):
        return self._state["spectrometer_mode"]
    
    def set_trigger_response(self, trigger_response: str):
        self.proem.params.TriggerResponse.set_value(getattr(PicamEnums.TriggerResponse, trigger_response))
        self._state["trigger_response"] = self.proem.params.TriggerResponse.get_value().name
        
    def get_trigger_response(self):
        return self._state["trigger_response"]

    ### you will want to check that the changes work on the lab machine as well--
    
    def _gen_mapping(self):
        "get map corresponding to static aoi and wavelength range."
        # define input paramaters
        mm_per_pixel = 0.016
        v = 200 # g/mm; grating groove spacing
        a = (v * 10**-3)**-1 # um/g
        aoi = np.radians(self._config["grating_aoi"])
        ws = np.linspace(self._config["spectral_range"][0], self._config["spectral_range"][1], 2048) # um
        f = 85 # mm; focal length of focusing lens
        n = 1.6 # rough index of refraction of grating
        # calculate output angles
        aods = np.arcsin(n * np.sin(aoi) - (ws / a))
        # convert angle to space
        xs = f * np.tan(aods)
        rel_xs = np.abs(xs - xs.min()) # start from 0 and count up in length
        # map spatially correlated wavelengths onto detector by interpolating
        spec_divided = rel_xs / mm_per_pixel
        g = interp1d(spec_divided, ws)
        num_pixels = np.round(spec_divided[0], 0)
        pixels = np.arange(num_pixels)
        out = g(pixels) * 1000
        return np.flip(out) # account for physical orientation of spectrometer
    
    def _set_temperature(self):
        self.proem.params.SensorTemperatureSetPoint.set_value(self._config["sensor_temperature_setpoint"])
        sensor_temp_status = self.proem.params.SensorTemperatureStatus.get_value().name
        if sensor_temp_status == 'Locked':
            self.logger.info("Sensor temp stabilized.")
        else:         
            self._loop.run_in_executor(None, self._check_temp_stabilized)
 
    def _check_temp_stabilized(self):
        set_temp = self.proem.params.SensorTemperatureSetPoint.get_value()
        sensor_temp = self.proem.params.SensorTemperatureReading.get_value()
        diff = set_temp - sensor_temp
        while abs(diff) > 0.5:
            self.logger.info(f"Sensor is cooling.\
                             Target: {set_temp} C. Current: {sensor_temp} C.")
            set_temp = self.proem.params.SensorTemperatureSetPoint.get_value() # call again just to make sure
            sensor_temp = self.proem.params.SensorTemperatureReading.get_value()
            diff = set_temp - sensor_temp
        
        sensor_temp_status = self.proem.params.SensorTemperatureStatus().name
            
    def get_sensor_temperature(self):
        return self.proem.params.SensorTemperatureReading.get_value()
    
    def close(self):
        self.proem.close()
    
    def _grab_image(self, kwds, timeout):
        img = self.proem.grab_image(**kwds, timeout=timeout)
        if not isinstance(img, np.ndarray):
            return np.asarray(img)
        else:
            return img
    
    async def _measure(self):
        kwds = {'n_frames': self.get_readout_count(),
                'exposure_time': Q_(self.get_exposure_time(), 'ms')}
        timeout = kwds['n_frames'] * kwds['exposure_time'] + Q_(50, 'ms')
        if self._state["spectrometer_mode"] == "spatial":
            spat = self._grab_image(kwds, timeout)
            return {"image": spat}
        if self._state["spectrometer_mode"] == "spectral":
            spec = self._grab_image(kwds, timeout)
            return {"image": spec}

           
    async def update_state(self):
        """Continually monitor and update the current daemon state."""
        while True:
            sensor_temp_status = self.proem.params.SensorTemperatureStatus.get_value().name
            if sensor_temp_status == 'Locked':
                self.logger.debug("Sensor temp stabilized.")
            else:
                self.logger.error("Sensor temp not stabilized. Something is wrong.")
            await asyncio.sleep(60)

if __name__ == "__main__":
    PiProem.main()