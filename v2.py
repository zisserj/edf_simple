import bppy as bp
from bppy.model.sync_statement import *
from bppy.model.b_thread import *
from bppy.model.event_set import *
import numpy as np
np.set_printoptions(legacy=False)
from bppy import BEvent as E
from scipy.stats import expon
from enum import Flag, auto

in_oper_f_r = 10e-4 # per hour (exp)
on_demand_f_r = 10e-2 # per attempt
repair_rate = 10e-1 # per hour (exp)

class TEvent(BEvent):
  def __init__(self, t, name="", data={}):
     super().__init__(name, data)
     self.t = t
  def __repr__(self):
     return super().__repr__() + f' t={self.t:.2f}'

TE = TEvent

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
 
class AlarmEventSelection(bp.SimpleEventSelectionStrategy):
  def __init__(self, max_time, time_eps=1e-5) -> None:
    super().__init__()
    self.max_time = max_time
    self.time_eps = time_eps
    self.elapsed = 0

  def is_satisfied(self, event, statement):
    if super().is_satisfied(event, statement):
      return True
    t = event.t if isinstance(event, TEvent) else 0
    # any timed request is satisfied by time passing
    # imo slightly more clean than needing to waitFor all timed events
    if isinstance(statement.get('request'), TEvent):
      return t > 0
    if (hasattr(statement.get('request', EmptyEventSet()), '__iter__')
      and any([isinstance(e, TEvent) for e in statement.get('request', EmptyEventSet())])):
      return t > 0

  def selectable_events(self, statements):
    possible_events = super().selectable_events(statements)
    if len(possible_events) == 0:
      return set()
    timed_events = {e: e.t if isinstance(e, TEvent) else 0 for e in possible_events}
    next_t = min(timed_events.values())
    if self.elapsed + next_t > self.max_time: # block events if max_time is surpassed
      return set()
    possible_events = [e for e, t in timed_events.items() if abs(t-next_t) < self.time_eps]
    self.elapsed += next_t
    return possible_events
  

@bp.thread
def c1():
  for i in range(3):
    next = expon.rvs(scale=5)
    yield sync(request=TE(t=next, name='c1_rv'))
    yield sync(request=E('c1'))
@bp.thread
def c2():
  for i in range(3):
    yield sync(waitFor=E('c1_rv'))
    yield sync(request=E('c2'))

prog = bp.BProgram(bthreads=[c1(), c2()],
                   listener=bp.PrintBProgramRunnerListener(),
                   event_selection_strategy=AlarmEventSelection(max_time=30))
prog.run()

def c_event(c, e_name, t=0):
  if t > 0:
    return TEvent(t, e_name, data={'c':c})
  return E(e_name, data={'c':c})
l_event = lambda l, e_name: E(e_name, data={'l': l})
ls_set = lambda ls: EventSet(lambda e: e.data.get('l') in ls)
c_set = lambda c: EventSet(lambda e: e.data.get('c') == c)

'''Random failure during operation'''
@bp.thread
def component_decay(c, decay_scale):
  while True:
    yield sync(waitFor=c_event(c, 'on'))
    e = E()
    while e != c_event(c, 'o_fail'):
      e = yield sync(request=c_event(c, 'o_fail', expon.rvs(scale=decay_scale)))

'''Requests repair after failure, blocks toggle when down'''
@bp.thread
def component_repair(c, repair_scale):
  while True:
    yield sync(waitFor=EventSet(lambda e: ('fail' in e.name and e.data.get('c')==c)))
    yield sync(request=c_event(c, 'req_repair'),
              block=[c_event(c, n) for n in ['o_fail', 'on', 'off']])
    e = E()
    while e != c_event(c, 'repaired'):
      e = yield sync(request=c_event(c, 'repaired', t=expon.rvs(scale=repair_scale)),
                 block=[c_event(c, n) for n in ['o_fail', 'on', 'off']])
# @bp.thread
# def component_status(c, status=Status.OFF):
#   while True:
#     blocked_events = []
#     e = yield sync(waitFor=[c_event(c, n) for n in ['on', 'off', 'repaired', 'o_fail', 'd_fail']])
#     if e.name in ['on']:
#       status = Status.ON
#     elif e.name in ['off', 'repaired']
#       status = Status.OFF
#     else:
#       status = Status.BROKEN

'''Induce potential failure on demand'''
@bp.thread
def component_toggle(c, on_demand_scale):
  while True:
    e = yield sync(waitFor=[c_event(c, n) for n in ['req_on', 'req_off']])
    status_str = e.name.split('_')[1]
    new_status = Status.ON if status_str == 'on' else Status.OFF
    failed_on_demand = np.random.rand() <= on_demand_scale
    event_name = 'd_fail' if failed_on_demand else status_str
    # if req_off or interaction failure, any of the events tied to malfunction also satisfy it
    if new_status == Status.OFF or failed_on_demand:
      extra_sat_events = [c_event(c, n) for n in ['o_fail', 'req_repair', 'repaired']] #unsure about this one
    else:
      extra_sat_events = []
    yield sync(request=c_event(c, event_name), waitFor=extra_sat_events)

'''Restart component after repair with a short delay'''
@bp.thread
def restart_component(c):
  while True:
    yield sync(waitFor=c_event(c,'repaired'))
    t_left = 10
    e = E()
    while e != c_event(c, 'req_on'): # adds passed time
      e = yield sync(request=c_event(c, 'req_on', t_left))
      t_left -= e.t

'''Keeps track of inidividual line components'''
@bp.thread
def line_status(name, cs_status, status=Status.OFF): # initial status can technically be inferred
  while True:
    line_events = EventSet(lambda e: e.data.get('c') in cs_status.keys()
                  and e.name in ['on', 'off', 'repaired', 'o_fail', 'd_fail'])
    e = yield sync(waitFor=line_events)
    c = e.data['c']
    if e.name in ['o_fail', 'd_fail']:
      cs_status[c] = Status.BROKEN
      if status != Status.BROKEN:
        status = Status.BROKEN
        yield sync(request=l_event(name, 'line_fail'), block=line_events)
    elif e.name == 'off':
      cs_status[c] = Status.OFF
      if status == Status.ON:
        status = Status.OFF
        yield sync(request=l_event(name, 'line_off'), block=line_events)
    elif e.name == 'repaired':
      cs_status[c] = Status.OFF
      if not Status.BROKEN in cs_status.values():
        status = Status.OFF
        yield sync(request=l_event(name, 'line_operational'), block=line_events)
    elif e.name == 'on':
      cs_status[c] = Status.ON
      if all([s == Status.ON for s in cs_status.values()]):
        status = Status.ON
        yield sync(request=l_event(name, 'line_on'), block=line_events)

'''Restarts line after its repaired'''
@bp.thread
def restart_line(name, cs_status, status=Status.OFF): # need just names here
  while True:
    yield sync(waitFor=l_event(name, 'line_operational'))
    for c in cs_status.keys():
      yield sync(request=c_event(c, 'req_on'))

'''Disables all running components in an online line upon a failure'''
@bp.thread
def line_fail_disable(name, cs_status):
  while True:
    yield sync(waitFor=l_event(name, 'line_fail'))
    for c in cs_status.keys():
      yield sync(request=c_event(c, 'req_off'))

'''Prioritizes starting the first functioning line'''
@bp.thread
def line_manager(line_names):
  current_line = 0
  status = {l: Status.OFF for l in line_names}
  while True:
    e = yield sync(waitFor=ls_set)
    l = e.data['l']
    if e.name == 'line_fail':
      pass
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
    do nothing v
  else:
    announce line operational v
(testing )if line was off and now operational
  turn line on v
'''
@bp.thread
def start(c):
  yield sync(request=c_event(c, 'req_on'))
  
cnames = ['grid', 'cb_up_1', 'transfo1']
ctypes = [CType.SHARED, CType.CON, CType.SOURCE]

comps = [Component(n, t) for n, t in zip(cnames, ctypes)][:2]
line = {c: Status.OFF for c in comps}
#t_c = line[0]

bt_c_params ={component_decay:  [1/in_oper_f_r],
              component_repair: [1/repair_rate],
              component_toggle: [on_demand_f_r],
              #restart_component: [],
              start: []}
bt_l_params = [bt('l1', line) for bt in [line_status, restart_line, line_fail_disable]]
c_bthreads = [bt(c, *params) for c,(bt, params) in itertools.product(comps, bt_c_params.items())]
prog = bp.BProgram(bthreads=c_bthreads + bt_l_params,
                   listener=bp.PrintBProgramRunnerListener(),
                   event_selection_strategy=AlarmEventSelection(max_time=750))
prog.run()