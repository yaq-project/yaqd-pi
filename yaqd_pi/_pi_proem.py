__all__ = ["PiProem"]

import asyncio
import os
import numpy as np

from time import sleep
from yaqd_core import IsDaemon, IsSensor, HasMeasureTrigger, HasMapping
from typing import Dict, Any, List
from instrumental.drivers.cameras import picam as sdk
from instrumental.drivers.cameras.picam import PicamError

class PiProem(HasMapping, HasMeasureTrigger, IsSensor, IsDaemon):
    _kind = "pi-proem"

    def __init__(self, name, config, config_filepath):
        super().__init__(name, config, config_filepath)
        self._channel_names = ["image", "spectral_image"] # is spectral_image needed or is that unecessary here?
        self._channel_mappings = {"image": ["x_index", "y_index"],
                                  "spectral_image": ["wm", "y_index"]}
        self._mapping_units = {"x_index": "None", "y_index": "None", 
                               "wm": ["eV", "nm", "um"]}
        self._channel_units = {"image": "counts", "spectral_image": "counts"}        
        self.picam = sdk.Picam(usedemo=True) # Initializes picam sdk;
        # setting usedemo=True is the only way for sdk.Picam() to not throw an error\
        # when using a virtual camera. If there is a real camera connected,
        # I believe not putting any args in sdk.Picam() will function.
            
        # find devices
        deviceArray, deviceCount = self.picam.get_available_camera_IDs()
        if deviceCount == 0:
            raise PicamError("No devices found.")
            
        # create sdk.PicamCamera() object
        self.picam.open_camera(deviceArray[1], 'proEM')
        self.proem = self.picam.cameras['proEM']
        self.parameters = self.proem.enums.Parameter
            
        # Perform any unique initialization
        self.proem.set_adc_gain(self._config["adc_analog_gain"])
        self.proem.set_param(self.parameters.AdcEMGain, self._config["em_gain"])
        self.proem.set_exposure_time(str(self._config["exposure_time"]) + " ms")
        
        #roi is currently in config, so just run on startup
        self._set_roi()
        self._set_temperature()
        
    def _set_roi(self):
        roi_keys = ["roi_x_binning", "roi_y_binning", "roi_width",
                    "roi_left", "roi_height", "roi_top"]
        x_binning, y_binning, width, left, height, top = [
            self._config[k] for k in roi_keys]
        
        max_width = self.proem.get_param(self.parameters.SensorActiveWidth)
        max_height = self.proem.get_param(self.parameters.SensorActiveHeight)
        
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
        
        # create PicamRois data structure 
        roi = sdk.PicamRoi(left, width, height, top, x_binning, y_binning)
        self.proem.set_frames([roi]) # set_frames() checks to make sure binning is integer multiple of width, height
        
    def _set_temperature(self):
        self.proem.set_temperature_setpoint(str(self._config["sensor_temperature_setpoint"]) + ' degC')
        sensor_temp_status = self.proem.get_temperature_status().name
        if sensor_temp_status == 'Locked':
            self.logger.info("Sensor temp stabilized.")
        else:         
            self._loop.run_in_executor(None, self._check_temp_stabilized)
 
    def _check_temp_stabilized(self):
        set_temp = self.proem.get_temperature_setpoint().magnitude
        sensor_temp = self.proem.get_param(self.parameters.SensorTemperatureReading)
        diff = set_temp - sensor_temp
        while abs(diff) > 0.2:
            self.logger.info(f"Sensor is cooling.\
                             Target: {set_temp} C. Current: {sensor_temp} C.")
            sleep(5)
            set_temp = self.proem.get_temperature_setpoint().magnitude
            sensor_temp = self.proem.get_param(self.parameters.SensorTemperatureReading)
            diff = set_temp - sensor_temp
        sensor_temp_status = self.proem.get_temperature_status().name
        if sensor_temp_status == 'Locked':
            self.logger.info("Sensor temp stabilized.")
       
    def acquire_and_show(self):
        # putting this simple function here now, can increase complexity as we see fit
        from matplotlib.pyplot import imshow
        data = self.proem.get_data()
        imshow(data)
                  
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
