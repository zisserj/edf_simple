import bppy as bp
from bppy.model.sync_statement import *
from bppy.model.b_thread import *
from bppy.model.event_set import *
import numpy as np
np.set_printoptions(legacy=False)
from bppy import BEvent as E
from scipy.stats import expon
from collections.abc import Iterable
from enum import Flag, auto

in_oper_f_r = 10e-4 # per hour (exp)
on_demand_f_r = 10e-2 # per attempt
repair_rate = 10e-1 # per hour (exp)

class Status(Flag):
  ON = auto()
  OFF = auto()
  BROKEN = auto()

class CType(Flag):
  CON = auto()
  SOURCE = auto()
  SHARED = auto()

class Component:
  def __init__(self, name, ctype):
     self.name = name
     self.ctype = ctype
  def __repr__(self) -> str:
     return f'({self.ctype.name}) {self.name}'
 


@bp.thread
def clock(initial_component_states):
    comps = initial_component_states
    repairs = []
    t = 0
    while t < 10e4:
        in_oper = [k for k, v in comps.items() if v == Status.ON]
        next_fails = expon.rvs(scale=1/in_oper_f_r, size=len(in_oper))
        next_repairs = expon.rvs(scale=1/repair_rate, size=len(repairs))
        next_events = np.concatenate([next_fails, next_repairs])
        c_idx = np.argmin(next_events)
        t += next_events[c_idx]
        if c_idx < len(in_oper): # in-operation failure
          c_obj = in_oper[c_idx]
          comps[c_obj] = Status.BROKEN
          e_name = 'o_fail'
        else: # repair
          c_obj = repairs[c_idx - len(in_oper)]
          repairs.remove(c_obj)
          comps[c_obj] = Status.OFF
          e_name = 'repaired'
        yield sync(request=E(e_name, {'c': c_obj,'time': t}))
        # actions stalling clock (could be replaced by priority)
        e = E('')
        while e.name != 'tick':
          e = yield sync(request=E('tick'), waitFor=All(), priority=0)
          if e in EventSet(lambda x: x.name == 'req_repair'):
            repairs.append(e.data['c'])
    yield sync(block=All(), priority=100)

'''
Sends repair requests in case of component failure, potentially trigger on-demand failures
'''
@bp.thread
def component_bt(c_obj, init_status):
    status = init_status
    rel_events = EventSet(lambda x: x.data.get('c') and x.data['c'] == c_obj)
    while True:
      e = yield sync(waitFor=rel_events) # should on/off requests be blocked when broken?
      if e in EventSet(lambda x: x.name in ['req_on', 'req_off']):
        state_str = e.name.split('_')[1]
        new_status = Status.ON if state_str == 'on' else Status.OFF
        if status in [Status.ON, Status.OFF] and new_status != status: # actually requires update
          failed_on_demand = np.random.rand() <= on_demand_f_r
          if failed_on_demand:
            status = Status.BROKEN
            yield sync(request=E('d_fail', {'c': c_obj}), priority=10)
            yield sync(request=E('req_repair', {'c': c_obj}), priority=5)
          else:
            status = new_status
            yield sync(request=E(state_str, {'c':c_obj}))
      elif e in EventSet(lambda x: x.name.endswith('fail')): # in-operation
        status = Status.BROKEN
        yield sync(request=E('req_repair', {'c': c_obj}), priority=7)
      elif e.name == 'repaired':
        status = Status.OFF

# @bp.thread
# def toggle(c):
#     yield sync(waitFor=EventSet(lambda e: e.name == 'repaired' and e.data['c'] == c))
#     yield sync(request=E('req_on', data={'c':c}))

@bp.thread
def line_bt(name, comps):
    status = Status.ON
    events = EventSet(lambda x: x.data.get('c') and x.data['c'] in comps.keys()) # or l

    def update_status():
      if Status.BROKEN in comps.values():
        status = Status.BROKEN
      elif Status.OFF in comps.values():
        status = Status.OFF
      else:
        status = Status.ON

    while True:
      e = yield sync(waitFor=events)
      if status == Status.ON and 'fail' in e.name:
        status = Status.BROKEN
        yield sync(request=E('line_mal', {'l': name}))
        for c in comps:
          if c.ctype != CType.SHARED:
            yield sync(request=E('req_off', {'c': c}))
            #e = yield sync(waitFor=E('off', {'c': c})) #wait for sucessful shutdown?
      if status == Status.OFF | Status.BROKEN and e.name == 'repaired':
        comps[e.data['c']] = Status.OFF
        update_status()
        print(comps)
        if status in [Status.OFF, Status.ON]:
          yield sync(request=E('line_func', {'l': name}))
          # for testing, turn line on?
          for c in comps:
            yield sync(request=E('req_on', {'c': c}))
    '''
    if line was on and component breaks:
      announce line malfunction v
      turn off everything v
      if fails:
        short-circuit
    if line was off and component breaks:
      turn off connectors
      if fails:
        short-circuit
    if line was off and component repaired:
      if more broken components: v
        do nothing
      else:
        announce line operational v
    (testing )if line was off and now operational
      turn line on
    '''
# todo: line manager



cnames = ['grid', 'cb_up_1', 'transfo1'] #, 'cb_dw_1', 'busbar']
ctypes = [CType.SHARED, CType.CON, CType.SOURCE] #, CType.CON, CType.SHARED]

line = {Component(n, t): Status.ON for n, t in zip(cnames, ctypes)}
t_c = list(line.keys())[0]
prog = bp.BProgram(bthreads=[clock(line)] + [component_bt(*c) for c in line.items()] + [line_bt('l1', line)],
                   listener=bp.PrintBProgramRunnerListener(),
                   event_selection_strategy=bp.PriorityBasedEventSelectionStrategy(default_priority=5))
prog.run() 