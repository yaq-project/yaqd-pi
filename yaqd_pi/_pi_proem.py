__all__ = ["PiProem"]

import asyncio
import os
import numpy as np

from time import sleep
from yaqd_core import IsDaemon, IsSensor, HasMeasureTrigger, HasMapping
from typing import Dict, Any, List
from instrumental.drivers.cameras import picam as sdk, PicamEnums, list_instruments, PicamError

class PiProem(HasMapping, HasMeasureTrigger, IsSensor, IsDaemon):
    _kind = "pi-proem"

    def __init__(self, name, config, config_filepath):
        super().__init__(name, config, config_filepath)
        self._channel_names = ["image", "spectral_image"] 
        # Putting in spectral_image as a channel here to denote when the
        # prism is inserted into the beam line. Can then get xaxis readouts in 
        # color units instead of pixel units
        self._channel_mappings = {"image": ["x_index", "y_index"],
                                  "spectral_image": ["wm", "y_index"]}
        self._mapping_units = {"x_index": "None", "y_index": "None", 
                               "wm": ["eV", "nm", "um"]}
        self._channel_units = {"image": "counts", "spectral_image": "counts"}        
        self.picam = sdk
  
        # find devices
        deviceArray = self.picam.list_instruments()
        if len(deviceArray) == 0:
            raise PicamError("No devices found.")
            
        # create sdk.PicamCamera() object
        self.proem = list_instruments()[0].create()
            
        # Perform any unique initialization
        self.proem.params.AdcAnalogGain.set_value(getattr(PicamEnums.AdcAnalogGain), self._config["adc_analog_gain"])
        self.proem.params.AdcEMGain.set_value(self._config["em_gain"])
        self.proem.params.ExposureTime.set_value(self._config["exposure_time"])
        
        #roi is currently in config, so just run on startup
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
        
        # handle defaults
        if left is None:
            left = 1
        if top is None:
            top = 1
        if width is None:
            width = max_width - left + 1
        if height is None:
            height = max_height - top + 1
        
        # make sure roi falls somewhere on sensor
        self.logger.debug(f"{max_width}, {max_height}, {x_binning}, {y_binning}, {width}, {left}, {height}, {top}")
        w_extent = width * x_binning + (left-1)
        h_extent = height * y_binning + (top-1)
        if w_extent > max_width:
            raise ValueError(f"width extends over {w_extent}, max is {max_width}")
        if h_extent > max_height:
            raise ValueError(f"height extends over {h_extent}, max is {max_height}")
        
        # finally set roi through instrumental function
        self.proem.set_roi(x=left, width=width, height=height, y=top,
			   x_binning=x_binning, y_binning=y_binning)
        
        
    def _set_temperature(self):
        self.proem.params.SensorTemperatureSetpoint.set_value(self._config["sensor_temperature_setpoint"])
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
            set_temp = self.proem.params.SensorTemperatureSetpoint.get_value() # call again just to make sure
            sensor_temp = self.proem.params.SensorTemperatureReading.get_value()
            diff = set_temp - sensor_temp
        sensor_temp_status = self.proem.params.SensorTemperatureStatus().name
        if sensor_temp_status == 'Locked':
            self.logger.info("Sensor temp stabilized.")
       
    def acquire_and_show(self):
        # putting this simple function here now, can increase complexity as we see fit
        from matplotlib.pyplot import imshow
        data = self.proem.grab_image()
        imshow(data)
       
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
