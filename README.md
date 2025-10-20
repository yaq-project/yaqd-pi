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

A cone of diffracted rays are captured with a lens and Fourier mapped on the camera.
The lens and camera are aligned such that the normal ray hits the center of the camera.
The diffracted rays angles are related to the camera pixel position by:
$$ \delta x = f \tan \left( \beta - \beta_0 \right), $$

$$ \implies \beta = \beta_0 + \tan^{-1} \frac{\delta x}{f} $$
where $f$ is the focal length of the imaging optic, and $\beta_0$ the angle of the color that propagates along the optic axis of lens.
$\delta x$ is the position along the plane of the camera, relative to the $\beta_0$ ray.

Using both equations, we can relate imaging position to wavelength:
$$ \beta_0 + \tan^{-1} \frac{\delta x}{f} = \sin^{-1}\left(\frac{m\lambda}{d} - \sin \alpha \right) $$
or
$$ \lambda(\delta x; f, m, d, \alpha, \beta_0) = \frac{d}{m} \sin \left[ \beta_0 + \tan^{-1} \left(\frac{\delta x}{f}\right) \right] + \sin\alpha $$
To set these parameters, confer the configuration file schema.

## An example calibration routine

TODO
To perform a single-point calibration, send in a known wavelength and find the position on the camera.

A more convenient approximation measures displacement from the nominal ray.
Suppose the lens is aligned so that a normal ray hits the center of the camera.
We can then describe deviations from the camera center in terms of the normal ray:
$$ \delta x = f \tan \left(\beta - \beta_0 \right) $$
Where $\beta_0$ is the special normal ray (that in turn is related to a special color).
Since angles are small, we can use the paraxial approximation:
$$ \delta x \approx f \frac{\beta - \beta_0}{}$$
