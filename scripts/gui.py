from matplotlib.widgets import Slider, CheckButtons
from matplotlib.colors import Normalize, LogNorm
import matplotlib.pyplot as plt
import yaqc
import numpy as np
import click
import logging


log_level = logging.INFO
norm = Normalize


@click.command()
@click.option("--host", default="127.0.0.1", help="host of yaqd-pi-proem. defaults to 127.0.0.1")
@click.argument("port", type=int)
def main(port: int, host):
    logger = logging.getLogger("GUI")
    logger.setLevel(log_level)
    logger.addHandler(logging.StreamHandler())

    cam = yaqc.Client(port=port, host=host)

    logger.info(cam)
    x = cam.get_mappings()["x_index"]
    y = cam.get_mappings()["y_index"]

    fig, (ax, opt1, opt2, opt3) = plt.subplots(
        nrows=4, height_ratios=[10, 1, 1, 1], gridspec_kw={"hspace": 0.1}
    )

    try:
        y0 = cam.get_measured()["mean"]
    except KeyError:
        y0 = np.zeros((x * y).shape)
    art = ax.matshow(y0, cmap="viridis")
    fig.colorbar(art, ax=ax)

    integration = Slider(
        opt1, "integration time (ms)", 33, 1e3, valstep=1, valinit=cam.get_exposure_time()
    )
    acquisition = Slider(
        opt2, "acquisitions (2^x)", 0, 8, valinit=int(np.log2(cam.get_readout_count())), valstep=1
    )
    measure_button = CheckButtons(opt3, labels=["call measure"], label_props=dict(fontsize=[20]))

    state = {"current": 0, "next": 0}
    title = "ID {}"

    def update_line(data):
        if ax.get_title() != title.format(data["measurement_id"]):
            try:
                ax.set_title(f"ID {data['measurement_id']}")
                art.set_data(data["mean"])
            except Exception as e:
                logger.error("", exc_info=e, stack_info=True)
                return
            art.set_norm(norm())
            fig.canvas.draw_idle()

    def submit(measure=False):
        try:
            if "call measure" in measure_button.get_checked_labels() or measure:
                if state["current"] >= state["next"]:
                    state["next"] = cam.measure()
            measured = cam.get_measured()
            state["current"] = measured["measurement_id"]
            update_line(measured)
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

    plt.tight_layout()
    timer.start()
    plt.show()


if __name__ == "__main__":
    main()
