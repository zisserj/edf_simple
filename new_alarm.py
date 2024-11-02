

import numpy as np
from scipy.stats import expon
from v3_obj import *


x = TE(2, 'tick')
@bp.thread
def c3():
  for i in range(3):
    yield sync(request=x)
    
@bp.thread
def c4(to_delete):
  yield sync(request=TE(5, 'mything'), waitFor=E('tick'))
  prog.remove_bthread(to_delete)
  yield sync(request=E('c3 removed'))

@bp.thread
def c5():
  yield sync(request=TE(6, 'new_thing'))
  prog.add_bthread(c3())

c3_instance = c3()
strat = AlarmEventSelection(max_time=30)
prog = bp.BProgram(bthreads=[c3_instance, c4(c3_instance)],
                   listener=bp.PrintBProgramRunnerListener(),
                   event_selection_strategy=strat)
prog.run()


