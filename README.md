# yaqd-pi

[![PyPI](https://img.shields.io/pypi/v/yaqd-pi)](https://pypi.org/project/yaqd-pi)
[![Conda](https://img.shields.io/conda/vn/conda-forge/yaqd-pi)](https://anaconda.org/conda-forge/yaqd-pi)
[![yaq](https://img.shields.io/badge/framework-yaq-orange)](https://yaq.fyi/)
[![black](https://img.shields.io/badge/code--style-black-black)](https://black.readthedocs.io/)
[![ver](https://img.shields.io/badge/calver-YYYY.M.MICRO-blue)](https://calver.org/)
[![log](https://img.shields.io/badge/change-log-informational)](https://github.com/yaq-project/yaqd-pi/blob/main/CHANGELOG.md)

yaq daemons for Princeton Instruments spectrographs and cameras.

This package contains the following daemon(s):

- https://yaq.fyi/daemons/pi-proem

# yaqd-pi-proem: Spectrometer configuration

Wavelength mappings are calculated using grating equation.  The diffracted angle $\beta$, incidence angle $\alpha$, and wavelength $\lambda$ are related by:
$$ \frac{m \lambda}{d} = \sin \beta - \sin \alpha, $$
where $m$ is the diffraction order and $d$ is the grating groove spacing.
_Note that with a transmissive grating, the incidence angle is internal to the grating and will be affected by refraction._

The diffracted rays are related to the camera pixel position by:
$$ x-x_0 = f \tan \beta, $$
where $x_0$ is the (hypothetical) position of the 0$^{th}$-order ray, and $f$ is the focal length of the imaging optic.

Using both equations, we can relate imaging position to wavelength:
$$ \tan^{-1} \frac{x-x_0}{f} = \sin^{-1}\left(\frac{m\lambda}{d} - \sin \alpha \right)$$
or
$$ \lambda(x; x_0, f, m, d, \alpha) = \frac{d}{m} \sin \left[ \tan^{-1} \left(\frac{x-x_0}{f}\right) \right] + \sin\alpha$$
To set these parameters, confer the configuration file schema.

## An example calibration routine

To perform a single-point calibration, send in a known wavelength and find the position on the camera

## maintainers

- [Jason Scheeler](https://github.com/jscheeler1)
