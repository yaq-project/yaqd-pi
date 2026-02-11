from matplotlib.widgets import Slider, CheckButtons
from matplotlib.colors import Normalize, LogNorm
import matplotlib.pyplot as plt
import yaqc
import numpy as np
import click
import logging
import pathlib

from functools import partial
from _spec import spec_from_toml


plt.style.use("dark_background")
log_level = logging.INFO
# norm = LogNorm
norm = Normalize


@click.command()
@click.option("--host", default="127.0.0.1", help="host of yaqd-pi-proem. defaults to 127.0.0.1")
@click.argument("port", type=int)
@click.option("--spec", default="")
def main(port: int, host, spec):
    logger = logging.getLogger("GUI")
    logger.setLevel(log_level)
    logger.addHandler(logging.StreamHandler())

    cam = yaqc.Client(port=port, host=host)

    logger.info(cam)
    x = cam.get_mappings()["x_index"]
    y = cam.get_mappings()["y_index"]

    fig, (ax, opt1, opt2, opt3) = plt.subplots(
        nrows=4, height_ratios=[10, 1, 1, 1], gridspec_kw={"hspace": 0.05}, layout="tight"
    )

    try:
        y0 = cam.get_measured()["mean"]
    except KeyError:
        y0 = np.zeros((x * y).shape)
    art = ax.matshow(y0, cmap="viridis")
    fig.colorbar(art, ax=ax)

    # spec wavelength labels
    # TODO: buttons to select what x-axis to use
    if spec:
        spec = spec_from_toml(pathlib.Path(spec))
        _x, wavelength = spec.mapping(x.squeeze())
        coords = list(zip(*sorted(zip(wavelength, _x))))  # interp needs sorted values

        mapping = lambda x: spec.mapping(x)[1]
        inverse_mapping = partial(np.interp, xp=wavelength, fp=_x)
        spec_ax = ax.secondary_xaxis(
            "bottom", 
            functions=(mapping, inverse_mapping)
        )
        spec_ax.set_xlabel("wavelength (nm)")

    integration = Slider(
        opt1, "integration time (ms)", 33, 1e3, valstep=1, valinit=cam.get_exposure_time()
    )
    acquisition = Slider(
        opt2, "acquisitions (2^x)", 0, 8, valinit=int(np.log2(cam.get_readout_count())), valstep=1
    )
    measure_button = CheckButtons(
        opt3,
        labels=["call measure"],
        label_props=dict(fontsize=[20]),
        frame_props=dict(facecolor="white"),
    )

    state = {"current": 0, "next": 0}
    title = "ID {}"

    def update_plot(data):
        if ax.get_title() != title.format(data["measurement_id"]):
            try:
                ax.set_title(f"ID {data['measurement_id']}")
                if data["measurement_id"]:
                    art.set_data(data["mean"].clip(min=600))
                    art.set_norm(norm())
            except Exception as e:
                logger.error("", exc_info=e, stack_info=True)
                return
            fig.canvas.draw_idle()

    def submit(measure=False):
        try:
            if "call measure" in measure_button.get_checked_labels() or measure:
                if state["current"] >= state["next"]:
                    state["next"] = cam.measure()
            measured = cam.get_measured()
            state["current"] = measured["measurement_id"]
            if state["current"]:
                update_plot(measured)
        except Exception as e:
            logger.error(state, exc_info=e)
            if e == ConnectionError or e == ConnectionRefusedError:
                pass

    timer = fig.canvas.new_timer(interval=200)

    @timer.add_callback
    def update():
        submit()

    def update_integration_time(arg):
        print(f"updating to {arg}")
        cam.set_exposure_time(arg)

    def update_acquisition(arg):
        cam.set_readout_count(2**arg)

    integration.on_changed(update_integration_time)
    acquisition.on_changed(update_acquisition)

    timer.start()
    plt.show()


if __name__ == "__main__":
    main()
