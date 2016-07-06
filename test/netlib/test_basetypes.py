from netlib import basetypes

from typing import List


class SerializableDummy(basetypes.Serializable):
    def __init__(self, i):
        self.i = i

    def get_state(self):
        return self.i

    def set_state(self, i):
        self.i = i

    def from_state(self, state):
        return type(self)(state)


class TestSerializable(object):

    def test_copy(self):
        a = SerializableDummy(42)
        assert a.i == 42
        b = a.copy()
        assert b.i == 42

        a.set_state(1)
        assert a.i == 1
        assert b.i == 42


class Child(basetypes.StateObject):
    def __init__(self, x):
        self.x = x

    _stateobject_attributes = dict(
        x=int
    )

    @classmethod
    def from_state(cls, state):
        obj = cls(None)
        obj.set_state(state)
        return obj


class Container(basetypes.StateObject):
    def __init__(self):
        self.child = None
        self.children = None

    _stateobject_attributes = dict(
        child=Child,
        children=List[Child],
    )

    @classmethod
    def from_state(cls, state):
        obj = cls()
        obj.set_state(state)
        return obj


class TestStateObject(object):
    def test_simple(self):
        a = Child(42)
        b = a.copy()
        assert b.get_state() == {"x": 42}
        a.set_state({"x": 44})
        assert a.x == 44
        assert b.x == 42

    def test_container(self):
        a = Container()
        a.child = Child(42)
        b = a.copy()
        assert a.child.x == b.child.x
        b.child.x = 44
        assert a.child.x != b.child.x

    def test_container_list(self):
        a = Container()
        a.children = [Child(42), Child(44)]
        assert a.get_state() == {
            "child": None,
            "children": [{"x": 42}, {"x": 44}]
        }
        assert len(a.copy().children) == 2
