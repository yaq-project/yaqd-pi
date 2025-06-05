from collections import namedtuple


# rois are expressed in a transformed coordinate system (x -> y, y -> x)
# so the end user does not deal with the camera rotation
# this issue should be superceded with mappings...
ROI_native = namedtuple("ROI_native", ["x", "y", "width", "height", "y_binning", "x_binning"])

ROI_UI = namedtuple("ROI_UI", ["bottom", "left", "width", "height", "y_binning", "x_binning"])


def ui_to_native(roi: ROI_UI) -> ROI_native:
    return ROI_native(
        x=512 - roi.bottom,
        y=roi.left,
        width=roi.height,
        height=roi.width,
        x_binning=roi.y_binning,
        y_binning=roi.x_binning,
    )


def native_to_ui(native: ROI_native) -> ROI_UI:
    return ROI_UI(
        **{
            "left": native.y,
            "width": native.height,
            "bottom": 512 - native.x,
            "height": native.width,
            "x_binning": native.y_binning,
            "y_binning": native.x_binning,
        }
    )
