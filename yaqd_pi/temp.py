from instrumental.drivers.cameras.picam import PicamEnums, list_instruments, PicamError  # type: ignore
from time import sleep
import numpy as np

exposure_time = 33  # ms
n_frames = 1

deviceArray = list_instruments()
proem = deviceArray[0].create()

proem.params.ExposureTime.set_value(exposure_time)  # ms

proem.params.ReadoutCount.set_value(n_frames)
proem.params.ExposureTime.get_value()

proem.start_capture()
# sleep(exposure_time / 1000 * n_frames)
img = proem.get_captured_image()
# img = np.asarray(img)

import matplotlib.pyplot as plt

art = plt.matshow(img)
plt.colorbar(art)

plt.show()
