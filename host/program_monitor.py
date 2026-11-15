"""Isolate JTAG configuration from the Tk/serial process and allow USB settling."""
import time
from audit import Run
from program import program_latest

if __name__=='__main__':
    run=Run('monitor_program')
    try:
        result=program_latest(run)
        time.sleep(.5)
        run.event('usb_settled_after_programming',seconds=.5,programming=result)
    finally:run.manifest()
