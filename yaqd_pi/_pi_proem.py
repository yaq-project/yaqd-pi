__all__ = ["PiProem"]

import asyncio
import os
import numpy as np

from time import sleep
from yaqd_core import IsDaemon, IsSensor, HasMeasureTrigger, HasMapping
from typing import Dict, Any, List
from instrumental.drivers.cameras.picam import sdk, PicamEnums, list_instruments, PicamError


class PiProem(HasMapping, HasMeasureTrigger, IsSensor, IsDaemon):
    _kind = "pi-proem"

    def __init__(self, name, config, config_filepath):
        super().__init__(name, config, config_filepath)
        self.logger.debug("Hello, I am initializieng")
        self._channel_names = ["image"]
        self._channel_mappings = {"image": ["x_index", "y_index"]}
        self._mapping_units = {"x_index": "None", "y_index": "None", 
                               "wm": ["eV", "nm", "um"]}# this threw an error
        # when calling c.get_mapping_units()
        self._channel_units = {"image": "counts"}        
        self._channel_shapes = {"image": (512,512)}
        self.picam = sdk
  
        # find devices
        deviceArray = list_instruments()
        if len(deviceArray) == 0:
            raise PicamError("No devices found.")
            
        # create sdk.PicamCamera() object
        self.proem = deviceArray[0].create()
            
        # Perform any unique initialization
        self.proem.params.AdcAnalogGain.set_value(getattr(PicamEnums.AdcAnalogGain, self._config["adc_analog_gain"]))
        self.proem.params.AdcEMGain.set_value(self._config["em_gain"])
        self.proem.params.ExposureTime.set_value(self._config["exposure_time"])
        
        # roi is currently in config, so just run on startup
        # should eventually be able to change roi dynamically though to avoid
        # having to restart daemon every time the roi needs to be changed.
        self._set_roi()
        self._set_temperature()
        
    def _set_roi(self):
	#extract roi parameters from config
        roi_keys = ["roi_x_binning", "roi_y_binning", "roi_width",
                    "roi_left", "roi_height", "roi_top"]
        x_binning, y_binning, width, left, height, top = [
            self._config[k] for k in roi_keys]
        
        max_width = self.proem.params.SensorActiveWidth.get_value()
        max_height = self.proem.params.SensorActiveHeight.get_value()
        
        # make sure roi falls somewhere on sensor
        self.logger.debug(f"{max_width}, {max_height}, {x_binning}, {y_binning}, {width}, {left}, {height}, {top}")
        
        # finally set roi through instrumental function
        self.proem.set_roi(x=left, width=width, height=height, y=top,
			   x_binning=x_binning, y_binning=y_binning)
        
        
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
        while abs(diff) > 0.2:
            self.logger.info(f"Sensor is cooling.\
                             Target: {set_temp} C. Current: {sensor_temp} C.")
            sleep(5)
            set_temp = self.proem.params.SensorTemperatureSetPoint.get_value() # call again just to make sure
            sensor_temp = self.proem.params.SensorTemperatureReading.get_value()
            diff = set_temp - sensor_temp
        sensor_temp_status = self.proem.params.SensorTemperatureStatus().name
        if sensor_temp_status == 'Locked':
            self.logger.info("Sensor temp stabilized.")
       
    async def _measure(self):
            print(self.proem.grab_image().shape)
            return {"image": self.proem.grab_image()}
       
    # def start_live_Video(self):
    #     self.proem.start_live_video()

    # def stop_live_Video(self):
    #     self.proem.stop_live_video()
           
    # async def update_state(self):
    #     """Continually monitor and update the current daemon state."""
    #     # If there is no state to monitor continuously, delete this function
    #     while True:
    #         # Perform any updates to internal state
    #         self._busy = False
    #         # There must be at least one `await` in this loop
    #         # This one waits for something to trigger the "busy" state
    #         # (Setting `self._busy = True)
    #         # Otherwise, you can simply `await asyncio.sleep(0.01)`
    #         await self._busy_sig.wait()
