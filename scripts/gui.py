# mypy: ignore errors
from matplotlib.widgets import Slider, CheckButtons
from matplotlib.colors import Normalize
import matplotlib.pyplot as plt
import yaqc
import numpy as np
import click


@click.command()
@click.option("--host", default="127.0.0.1", help="host of yaqd-pi-proem. defaults to 127.0.0.1")
@click.argument("port", type=int)
def main(port: int, host):
    cam = yaqc.Client(port=port, host=host)

    x = cam.get_mappings()["x_index"]
    y = cam.get_mappings()["y_index"]

    fig, (ax, opt1, opt2, opt3) = plt.subplots(nrows=4, height_ratios=[10, 1, 1, 1])

    try:
        y0 = cam.get_measured()["mean"]
    except KeyError:
        y0 = np.zeros((x * y).shape)
    art = ax.matshow(y0)
    fig.colorbar(art, ax=ax)

    integration = Slider(
        opt1, "integration time (ms)", 33, 1e3, valstep=1, valinit=cam.get_exposure_time()
    )
    acquisition = Slider(opt2, "acquisitions (2^x)", 0, 8, valinit=0, valstep=1)
    measure_button = CheckButtons(opt3, labels=["call measure"], label_props=dict(fontsize=[20]))

    state = {"current": 0, "next": 0}

    def update_line(data):
        art.set_data(data)
        art.set_norm(Normalize())
        fig.canvas.draw_idle()

    def submit(measure=False):
        try:
            if "call measure" in measure_button.get_checked_labels() or measure:
                if state["current"] >= state["next"]:
                    state["next"] = cam.measure()
            measured = cam.get_measured()
            y = measured["mean"]
            state["current"] = measured["measurement_id"]
            update_line(y)
        except ConnectionError:
            pass

    submit(measure=True)
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


# <3> ERR : 2025-06-12T16:07:35-0500 : proem : Caught exception: <class 'NameError'> in message set_exposure_time
