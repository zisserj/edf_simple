

import numpy as np
from scipy.stats import expon
from v4_obj import *


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
#prog.run()

ctx = [Status.OFF]

def update_status(current, e):
  if e.name == 'on':
    current[0] = Status.ON
    return True
  elif e.name == 'off':
    current[0] = Status.OFF
    return True
  return False
  
  
@bp.thread
def b1():
  for i in range(3):
    yield sync(request=TE(5, 'on'), waitFor=E('tick'))

@bp.thread
def b2():
  while True:
    yield sync(waitFor=E('on'))
    yield sync(request=TE(10, 'off'))

@bp.thread
def b3():
  yield sync(request=TE(10, 'off'))



strat = AlarmEventSelection(max_time=30)
prog = ContextualBProgram(
                   context=ctx, effect=update_status,
                   bthreads=[b1(), b2()],
                   listener=bp.PrintBProgramRunnerListener(),
                   event_selection_strategy=strat)
prog.run()