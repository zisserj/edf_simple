

import numpy as np
from scipy.stats import expon
from v3_obj import *


x = TE(10, 'tick')
@bp.thread
def c3():
  for i in range(3):
    yield sync(request=x)
@bp.thread
def c4():
  yield sync(request=TE(8, 'mything'), waitFor=E('tick'))
  yield sync(request=E('c4 prog'))

@bp.thread
def c5():
  yield sync(request=TE(6, 'tick'))
  
strat = AlarmEventSelection(max_time=30)
prog = bp.BProgram(bthreads=[c3(), c4(), c5()],
                   listener=bp.PrintBProgramRunnerListener(),
                   event_selection_strategy=strat)
prog.run()


