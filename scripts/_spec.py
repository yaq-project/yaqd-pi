"""
temporary storage for spectral mapping rules for the camera
plan is to use happi for mapping in the future
"""

from typing import NamedTuple
import numpy as np
import tomllib


class ProemSpec(NamedTuple):
    gpmm: int | float
    grating_aoi_deg: float
    fl_mm: int | float
    beta_0_deg: float
    center: int | float
    order: int
    mm_per_pixel: int = 0.016

    # tie the mapping to the class
    def mapping(self, var=None):
        m = self.order

        groove_spacing = 1e6 / self.gpmm  # nm
        f = self.fl_mm  # mm

        # $$ \delta x = f \tan \left( \beta - \beta_0 \right), $$
        # $$ \lambda(\delta x; f, m, d, \alpha, \beta_0) = \frac{d}{m} \sin \left[ \beta_0 + \tan^{-1} \left(\frac{\delta x}{f}\right) \right] + \sin\alpha $$
        # ind = np.arange(512, dtype=float)
        if var is None:
            var = np.arange(512, dtype=float)
        dx = (var - self.center) * self.mm_per_pixel  # mm

        return var, groove_spacing / m * (
            np.sin(self.beta_0_deg * np.pi / 180 + np.arctan(dx / f))
            + np.sin(self.grating_aoi_deg * np.pi / 180)
        )


def spec_from_toml(path, key: str = None) -> ProemSpec:
    toml = tomllib.loads(path.read_text())
    if key is None:  # defaults to first item
        key = [k for k in toml.keys()][0]
    print(f"using key: {key}")
    return ProemSpec(**toml[key])
