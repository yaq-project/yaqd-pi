# mypy: ignore-errors

# scratchwork for implementing spectrometer mapping
import numpy as np
from scipy.interpolate import interp1d

spec = dict(
    gpmm=200,
    grating_aoi_deg=5,
    focal_length=75,
    grating_refractive_index=1.6,
    spectral_range=[0.36, 0.841],
)
mm_per_pixel = 0.016

groove_spacing = 1e3 / spec["gpmm"]  # um
aoi = np.radians(spec["grating_aoi_deg"])
ws = np.linspace(spec["spectral_range"][0], spec["spectral_range"][1], 2048)  # um
f = spec["focal_length"]  # mm
n = spec["grating_refractive_index"]
# calculate diffraction angles
aods = np.arcsin(n * np.sin(aoi) - (ws / groove_spacing))
# convert angles to spatial positions
xs = f * np.tan(aods)  # mm
# position (relative to 0 order transmission) = f * np.tan(np.arcsin(c1-lambda/a))
# position (relative to camera center) = f * np.tan(np.arcsin(c1-lambda/a)) + c2
# np.atan((x-c2) / f) = np.asin(c1-lambda/a)
# np.sin(np.atan((x-c2)/f)) = c1-lambda/a
# lambda = LHS
# reference position from minimum value
xs_rel = np.abs(xs - xs.min())  # mm
# map wavelengths onto detector by interpolating
spec_divided = xs_rel / mm_per_pixel
# inversion of grating equation--input position, output color
g = interp1d(spec_divided, ws)
num_pixels = np.round(spec_divided[0], 0)
pixels = np.arange(num_pixels)
out = g(pixels) * 1000

# out = out[
#     self._mappings["x_index"][0][:]
# ]  # keep horizontal mappings equal size so wt5 file doesn't get confused
# return np.round(out, 2)  # account for physical orientation of camera


# from yaqd-wright-ingaas
def _gen_mappings(self):
    """Get map."""
    # translate inputs into appropriate internal units
    spec_inclusion_angle_rad = np.radians(self._config["inclusion_angle"])
    spec_focal_length_tilt_rad = np.radians(self._config["focal_length_tilt"])
    pixel_width_mm = 0.050  # 50 microns
    # create array
    i_pixel = np.arange(256)  # 256 pixels
    # calculate terms
    x = np.arcsin(
        (1e-6 * self._config["order"] * self._config["grooves_per_mm"] * self.spec_position)
        / (2 * np.cos(spec_inclusion_angle_rad / 2.0))
    )
    A = np.sin(x - spec_inclusion_angle_rad / 2)
    B = np.sin(
        (spec_inclusion_angle_rad)
        + x
        - (spec_inclusion_angle_rad / 2)
        - np.arctan(
            (
                pixel_width_mm * (i_pixel - self._config["calibration_pixel"])
                + self._config["focal_length"] * spec_focal_length_tilt_rad
            )
            / (self._config["focal_length"] * np.cos(spec_focal_length_tilt_rad))
        )
    )
    out = ((A + B) * 1e6) / (self._config["order"] * self._config["grooves_per_mm"])
    return out