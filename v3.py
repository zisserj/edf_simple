
import numpy as np
from scipy.stats import expon
from v3_obj import *

in_oper_f_r = 10e-4  # per hour (exp)
on_demand_f_r = 10e-2  # per attempt
repair_rate = 10e-1  # per hour (exp)


def c_event(c, e_name, t=0):
    if t > 0:
        return TEvent(t, e_name, data={'c': c})
    return E(e_name, data={'c': c})
l_event = lambda l, e_name: E(e_name, data={'l': l})
ls_set = lambda ls: EventSet(lambda e: e.data.get('l') in ls)
c_set = lambda c: EventSet(lambda e: e.data.get('c') == c)


'''Random failure during operation'''
@bp.thread
def component_decay(c, decay_scale):
    while True:
        yield sync(waitFor=c_event(c, 'on'))
        yield sync(request=c_event(c, 'o_fail', expon.rvs(scale=decay_scale)),
                   waitFor=[c_event(c, 'd_fail'), c_event(c, 'off')])

'''Requests repair after failure, blocks toggle when down'''
@bp.thread
def component_repair(c, repair_scale):
    while True:
        yield sync(waitFor=EventSet(
            lambda e: ('fail' in e.name and e.data.get('c') == c)))
        yield sync(request=c_event(c, 'req_repair'),
                   block=[c_event(c, n) for n in ['o_fail', 'on', 'off']])
        yield sync(request=c_event(c, 'repaired', expon.rvs(scale=repair_scale)),
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
        yield sync(request=c_event(c, event_name), waitFor="t passed")


'''(for testing) Restart component after repair with a short delay'''
@bp.thread
def restart_component(c):
    while True:
        yield sync(waitFor=c_event(c, 'repaired'))
        yield sync(request=c_event(c, 'req_on', 10))

'''Keeps track of inidividual line components'''
@bp.thread
def line_status(
        name,
        cs_status,
        status=Status.OFF):  # initial status can technically be inferred
    while True:
        line_events = EventSet(lambda e: e.data.get('c') in cs_status.keys(
        ) and e.name in ['on', 'off', 'repaired', 'o_fail', 'd_fail'])
        e = yield sync(waitFor=line_events)
        c = e.data['c']
        if e.name in ['o_fail', 'd_fail']:
            cs_status[c] = Status.BROKEN
            if status != Status.BROKEN:
                status = Status.BROKEN
                yield sync(request=l_event(name, 'line_fail'),
                           block=line_events)
        elif e.name == 'off':
            cs_status[c] = Status.OFF
            if status == Status.ON:
                status = Status.OFF
                yield sync(request=l_event(name, 'line_off'),
                           block=line_events)
        elif e.name == 'repaired':
            cs_status[c] = Status.OFF
            if not Status.BROKEN in cs_status.values():
                status = Status.OFF
                yield sync(request=l_event(name, 'line_operational'),
                           block=line_events)
        elif e.name == 'on':
            cs_status[c] = Status.ON
            if all([s == Status.ON for s in cs_status.values()]):
                status = Status.ON
                yield sync(request=l_event(name, 'line_on'), block=line_events)


'''Restarts line after its repaired'''
@bp.thread
def restart_line(name, cs_status):  # need just names here
    while True:
        yield sync(waitFor=l_event(name, 'line_operational'))
        for c in cs_status.keys():
            yield sync(request=c_event(c, 'req_on'))

'''Starts line on request'''
@bp.thread
def start_line(name, cs_status):
    while True:
        yield sync(waitFor=l_event(name, 'line_req_on'))
        for c in cs_status.keys():
            yield sync(request=c_event(c, 'req_on'))

'''Disables all running components in a working line upon a failure'''
@bp.thread
def disable_line_on_fail(name, cs_status):
    while True:
        yield sync(waitFor=l_event(name, 'line_fail'))
        for c in cs_status.keys():
            yield sync(request=c_event(c, 'req_off'))
        # TODO: only non-shared, potential for short-circuit

'''Stops line on request'''
@bp.thread
def stop_line(name, cs_status):
    while True:
        yield sync(waitFor=l_event(name, 'line_req_off'))
        for c in cs_status.keys():
            yield sync(request=c_event(c, 'req_off'))

def find_next_functional(status, start, ascending=True):
    idx = start
    inc = 1 if ascending else -1
    while status[idx] == Status.BROKEN: # find next functional line
        idx += inc
        if idx >= len(status) or idx < 0: # not found
            return -1
    return idx

'''Prioritizes starting the first functioning line'''
@bp.thread
def line_manager(lines_names):
    current_use = 0
    status = [Status.OFF for l in lines_names]
    force_next = lambda e_name: {'request': E(e_name), 'block': AllExcept(E(e_name))} 
    # turn on first line at start
    yield sync(request=l_event(lines_names[current_use], 'line_req_on'))
    
    while True:
        e = yield sync(waitFor=ls_set(lines_names))
        idx = lines_names.index(e.data['l'])
        if e.name == 'line_fail':
            status[idx] = Status.BROKEN
            if current_use == idx:
                next_idx = find_next_functional(status, idx)
                if next_idx == -1:
                    yield sync(force_next('system_down'))
                else:
                    current_use = idx
                    yield sync(request=l_event(lines_names[idx], 'line_req_on'), block=ls_set(lines_names))
        elif e.name in ['line_off', 'line_operational']:
            status[idx] = Status.OFF
            if idx <= current_use:
                current_use = idx
                yield sync(request=l_event(lines_names[idx], 'line_req_on'), block=ls_set(lines_names))
        elif e.name == 'line_on':
            status[idx] = Status.ON
            if idx < current_use:
                yield sync(request=l_event(lines_names[current_use], 'line_req_off'), block=ls_set(lines_names))
                current_use = idx


'''
if line was on and component breaks:
  announce line malfunction v
  turn off non-shared v
  if fails:
    short-circuit
'''

@bp.thread
def start(c):
    yield sync(request=c_event(c, 'req_on'))


cnames = ['grid', 'cb_up_1', 'transfo1']
ctypes = [CType.SHARED, CType.CON, CType.SOURCE]

comps = [Component(n, t) for n, t in zip(cnames, ctypes)]
lines = [{c: Status.OFF for c in l} for l in [comps[:2], comps[::2]]]
#t_c = line[0]

bt_c_params = {
    component_decay: [1 / in_oper_f_r],
    component_repair: [1 / repair_rate],
    component_toggle: [on_demand_f_r],
    #restart_component: [],
    #start: []
}

l_bthreads = [
    bt(lname, lcomp) for bt, (lname, lcomp) in itertools.product(
            [line_status, restart_line, disable_line_on_fail, start_line],
            zip(['l1', 'l2'], lines))
]
c_bthreads = [
    bt(c, *params)
    for c, (bt, params) in itertools.product(comps, bt_c_params.items())
]
prog = bp.BProgram(bthreads=c_bthreads + l_bthreads + [line_manager(['l1', 'l2'])],
                   listener=bp.PrintBProgramRunnerListener(),
                   event_selection_strategy=AlarmEventSelection(max_time=250))
prog.run()
