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
        if config.get("emulate"):
            self.logger.debug("Starting Emulated camera")
            sdk.connect_demo_camera(PicamEnums.Model.ProEMHS512BExcelon, "demo")
        self._channel_names = ["image"]
        self._channel_mappings = {"image": ["x_index", "y_index"]}
        self._mapping_units = {"x_index": "None", "y_index": "None", 
                               "wm": ["eV", "nm", "um"]} # this threw an error when calling c.get_mapping_units()
        self._channel_units = {"image": "counts"}        
        self._channel_shapes = {"image": (512,512)}
  
        # find devices
        deviceArray = list_instruments()
        if len(deviceArray) == 0:
            raise PicamError("No devices found.")
            
        # create sdk.PicamCamera() object
        self.proem = deviceArray[0].create()
        
        self._set_temperature()
        
    def set_roi(self, roi):
        try:
            self.proem.set_roi(x=roi["left"], y=roi["top"],width=roi["width"],height=roi["height"],
                               x_binning=roi["x_binning"],
                               y_binning=roi["y_binning"])
        except Exception as e:
            print(e)
        pld_roi = self.proem.params.Rois.get_value()[0]
        self._state["roi"] = {"left":pld_roi.x, "width": pld_roi.width,
                              "top":pld_roi.y, "height":pld_roi.height,
                              "x_binning":pld_roi.x_binning,
                              "y_binning":pld_roi.y_binning}
    
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
    
    def set_adc_analog_gain(self, gain: str):
        self.proem.params.AdcAnalogGain.set_value(getattr(PicamEnums.AdcAnalogGain, gain))
        self._state["adc_analog_gain"] = self.proem.params.AdcAnalogGain.get_value().name
        
    def get_adc_analog_gain(self):
        return self._state["adc_analog_gain"]
    
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
            set_temp = self.proem.params.SensorTemperatureSetPoint.get_value() # call again just to make sure
            sensor_temp = self.proem.params.SensorTemperatureReading.get_value()
            diff = set_temp - sensor_temp
        sensor_temp_status = self.proem.params.SensorTemperatureStatus().name       
            
    def get_sensor_temperature(self):
        return self.proem.params.SensorTemperatureReading.get_value()
    
    def close(self):
        self.proem.close()
        
    async def _measure(self):
        img = self.proem.grab_image()
        print(img.shape)
        return {"image": img}
           
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