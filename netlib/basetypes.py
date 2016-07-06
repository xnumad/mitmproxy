from __future__ import absolute_import, print_function, division
import abc

import six
from typing import Any
from typing import List


@six.add_metaclass(abc.ABCMeta)
class Serializable(object):
    """
    Abstract Base Class that defines an API to save an object's state and restore it later on.
    """

    @classmethod
    @abc.abstractmethod
    def from_state(cls, state):
        """
        Create a new object from the given state.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def get_state(self):
        """
        Retrieve object state.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def set_state(self, state):
        """
        Set object state to the given state.
        """
        raise NotImplementedError()

    def copy(self):
        return self.from_state(self.get_state())


def _is_list(cls):
    # The typing module is broken on Python 3.5.0, fixed on 3.5.1.
    is_list_bugfix = getattr(cls, "__origin__", False) == getattr(List[Any], "__origin__", True)
    return issubclass(cls, List) or is_list_bugfix


class StateObject(Serializable):

    """
    An object with serializable state.

    State attributes can either be serializable types(str, tuple, bool, ...)
    or StateObject instances themselves.
    """

    _stateobject_attributes = None
    """
    An attribute-name -> class-or-type dict containing all attributes that
    should be serialized. If the attribute is a class, it must implement the
    Serializable protocol.
    """

    def get_state(self):
        """
        Retrieve object state.
        """
        state = {}
        for attr, cls in six.iteritems(self._stateobject_attributes):
            val = getattr(self, attr)
            if val is None:
                state[attr] = None
            elif hasattr(val, "get_state"):
                state[attr] = val.get_state()
            elif _is_list(cls):
                state[attr] = [x.get_state() for x in val]
            elif not six.PY2 and cls == str:
                state[attr] = val.encode()
            else:
                state[attr] = val
        return state

    def set_state(self, state):
        """
        Load object state from data returned by a get_state call.
        """
        state = state.copy()
        for attr, cls in six.iteritems(self._stateobject_attributes):
            val = state.pop(attr)
            if state.get(attr) is None:
                setattr(self, attr, val)
            else:
                curr = getattr(self, attr)
                if hasattr(curr, "set_state"):
                    curr.set_state(val)
                elif hasattr(cls, "from_state"):
                    obj = cls.from_state(val)
                    setattr(self, attr, obj)
                elif _is_list(cls):
                    cls = cls.__parameters__[0] if cls.__parameters__ else cls.__args__[0]
                    setattr(self, attr, [cls.from_state(x) for x in val])
                elif not six.PY2 and cls == str:
                    setattr(self, attr, val.decode())
                else:  # primitive types such as int, str, ...
                    setattr(self, attr, cls(val))
        if state:
            raise RuntimeWarning("Unexpected State in __setstate__: {}".format(state))
