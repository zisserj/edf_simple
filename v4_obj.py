import bppy as bp
from bppy.model.sync_statement import *
from bppy.model.b_thread import *
from bppy.model.event_set import *
from collections.abc import Iterable
from enum import auto, Flag

E = bp.BEvent

class TEvent(BEvent):

    def __init__(self, t: float, name="", data={}):
        super().__init__(name, data)
        self.t = float(t)
        if not (t, float):
            raise ValueError('Inappropriate type for time') 

    def __repr__(self):
        return super().__repr__() + f' t={self.t:.2f}'

    def __eq__(self, other):
        if not super().__eq__(other): # different BEvents
            return False
        if isinstance(other, TEvent): # time equiv
            return self.t == other.t
        return self.t == 0 # "now" TEvent to BEvent 

    def __hash__(self):
        return super().__hash__() + hash(self.t)
    
    def to_now(self):
        return BEvent(self.name, self.data)

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
        if not (isinstance(event, TEvent)):
            return super().is_satisfied(event, statement)

        # reduces time passed from statement timed requests
        t_passed = event.t
        if 'request' in statement: 
            if isinstance(statement['request'], Iterable):
                requests = statement['request']
            elif isinstance(statement['request'], BEvent):
                requests = [statement['request']]
            new_events = [self.advance_time(e, t_passed) for e in requests]
            statement['request'] = new_events
        # normal selected event sat conditions after time passing
        return super().is_satisfied(self.advance_time(event, t_passed), statement)


    def selectable_events(self, statements):
        possible_events = super().selectable_events(statements)
        blocked = set()
        # not a timed_event, or not a blocked timed event
        for statement in statements:
            if 'block' in statement:
                if isinstance(statement.get('block'), BEvent):
                    possible_events = [e for e in possible_events if not isinstance(e, TEvent) or e.to_now() != statement.get('block')]
                else:
                    possible_events = [e for e in possible_events if not isinstance(e, TEvent) or e.to_now() not in statement.get('block')]
        if len(possible_events) == 0:
            return set()
        timed_events = {
            e: e.t if isinstance(e, TEvent) else 0
            for e in possible_events
        }
        next_t = min(timed_events.values())
        if self.elapsed + next_t > self.max_time:  # block events if max_time is surpassed
            return set()
        possible_events = [
            e for e, t in timed_events.items()
            if abs(t - next_t) < self.time_eps
        ]
        return possible_events

    def advance_time(self, event, passed_t):
        if not isinstance(event, TEvent):
            return event
        new_t = event.t - passed_t
        new_event = copy(event)
        if new_t <= self.time_eps:
            return new_event.to_now()
         # type: ignore
        new_event.t = new_t
        return new_event

    def select(self, statements, external_events_queue=[]):
        event = super().select(statements, external_events_queue)
        if not isinstance(event, TEvent):
            return event
        self.elapsed += event.t
        return event


class ContextualBProgram(bp.BProgram):
    def __init__(self, context, effect,
                 bthreads=None,
                 source_name=None,
                 event_selection_strategy=None,
                 listener=None):
        super().__init__(bthreads, source_name, event_selection_strategy, listener)
        self.context = context
        self.effect = effect
        
    def next_event(self):
        e = super().next_event()
        if e: # dont wan't to throw exceptions at the program end
            self.effect(self.context, e)
        return e