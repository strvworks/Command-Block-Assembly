"""Events"""

from ._core import PreambleInsn, ConstructorInsn, SingleCommandInsn
from ..core_types import (VirtualString,
                          AdvEventRef,
                          TagEventRef,
                          EventRef,
                          Selector,
                          SelectorType,
                          )
from ..core import IRFunction, VisibleFunction
import commands as c

class CreateAdvEvent(ConstructorInsn):
    """Creates an advancement-based event object."""

    args = [VirtualString]
    argnames = 'event_name'
    argdocs = ["The event name"]
    rettype = AdvEventRef
    insn_name = 'adv_event'

    def construct(self):
        return AdvEventRef(str(self.event_name))

class CreateTagEvent(ConstructorInsn):
    """Creates a tag-based event object."""

    args = [VirtualString]
    argnames = 'tag_name'
    argdocs = ["The function tag name"]
    rettype = TagEventRef
    insn_name = 'tag_event'

    def construct(self):
        return TagEventRef(str(self.tag_name))

class AddEventCondition(PreambleInsn):
    """Add a condition to an event that must be true for the event handler
    to be invoked."""

    args = [AdvEventRef, VirtualString, VirtualString]
    argnames = 'event path value'
    argdocs = ["Event to add the condition to", "JSON path in the advancement",
               "Value that must match"]
    insn_name = 'add_event_condition'

    def preapply(self, preamble):
        self.event.add_condition(tuple(str(self.path).split('.')),
                                 str(self.value))

class EventHandler(PreambleInsn):
    """Add an event handler to the given event specification."""

    args = [IRFunction, EventRef]
    argnames = 'handler event'
    argdocs = ["Event handler", "Event"]
    top_preamble_only = True
    insn_name = 'event_handler'

    def preapply(self, preamble):
        if not self.event.is_tag:
            self.handler.add_advancement_revoke(self.event)

    def declare(self):
        self.handler.usage()

    def postapply(self, out, top):
        assert not self.handler.is_inline
        out.write_event_handler(self.handler, self.event)

class FireEventInsn(SingleCommandInsn):
    """Fires a tag-based event to all listeners."""

    args = [TagEventRef]
    argnames = 'event'
    argdocs = ["Tag event to fire"]
    insn_name = 'fire_event'

    def get_cmd(self, func):
        return c.FunctionTag(c.NSName(self.event.name))

class RevokeEventAdvancement(SingleCommandInsn):
    """(Internal) Revokes an advancement to allow an event to re-fire."""

    args = [IRFunction]
    argnames = 'func'
    argdocs = ["Handler"]
    insn_name = 'revoke_event_adv'

    def get_cmd(self, func):
        # Advancement name = handler func name
        return c.Advancement('revoke', Selector.new(SelectorType.SENDER) \
                             .as_resolve(),
                           'only', c.AdvancementRef(self.func.global_name))

class SetupInsn(PreambleInsn):
    """Tags a function as being part of the setup phase. It is called whenever
    the datapack is reloaded."""

    args = [VisibleFunction]
    argnames = 'func'
    argdocs = ["The setup function"]
    top_preamble_only = True
    insn_name = 'setupfn'

    def declare(self):
        self.func.usage()

    def preapply(self, preamble):
        pass

    def postapply(self, out, top):
        assert not self.func.is_inline
        out.write_setup_function(self.func)
