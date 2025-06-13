"""
simple imports to test functionality of instrumental-lib
this was used to inform on daemon methods like _measure
"""

from instrumental.drivers.cameras.picam import PicamEnums, PicamCamera, list_instruments, PicamError  # type: ignore

deviceArray = list_instruments()
proem: PicamCamera = deviceArray[0].create()


def measure(n_frames, exposure_time_ms):
    proem.params.ReadoutCount.set_value(n_frames)
    proem.params.ExposureTime.set_value(exposure_time_ms)  # ms
    proem.commit_parameters()
    readouts = []  # readouts[readout][readout_frame][frame roi]
    running = True
    proem._dev.StartAcquisition()
    while running:
        try:
            # wait is blocking, so we might as well allow errors
            available_data, status = proem._dev.WaitForAcquisitionUpdate(10)
        except PicamError as e:
            if e.code == PicamEnums.Error.TimeOutOccurred:
                print(e)
            else:
                print(e)
                proem._dev.StopAcquisition()
                raise e
        else:
            running = status.running
            print(status.running, available_data.readout_count)
            if available_data.readout_count > 0:
                readouts.extend(proem._extract_available_data(available_data, copy=True))
    return readouts


# print(proem._dev.AreParametersCommitted())
# proem.commit_parameters()
# print(proem._dev.AreParametersCommitted())
