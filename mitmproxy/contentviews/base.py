# Default view cutoff *in lines*
import inspect
import traceback
import typing

from mitmproxy import exceptions
from mitmproxy.net import http
from mitmproxy.utils import strutils

VIEW_CUTOFF = 512

TTextType = typing.AnyStr  # FIXME: This should be either bytes or str ultimately.
TViewLine = typing.List[typing.Tuple[str, TTextType]]
TViewResult = typing.Tuple[str, typing.Iterator[TViewLine]]


class View:
    name = None  # type: str
    prompt = None  # type: typing.Tuple[str,str]
    content_types = []  # type: typing.List[str]
    registered_views = []

    def __call__(self, data: bytes, **metadata) -> TViewResult:
        """
        Transform raw data into human-readable output.

        Args:
            data: the data to decode/format.
            metadata: optional keyword-only arguments for metadata. Implementations must not
                rely on a given argument being present.

        Returns:
            A (description, content generator) tuple.

            The content generator yields lists of (style, text) tuples, where each list represents
            a single line. ``text`` is a unfiltered byte string which may need to be escaped,
            depending on the used output.

        Caveats:
            The content generator must not yield tuples of tuples,
            because urwid cannot process that. You have to yield a *list* of tuples per line.
        """
        raise NotImplementedError()  # pragma: no cover

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # noinspection PyTypeChecker
        views.add(cls)  # type: ignore

    @classmethod
    def unregister(cls):
        views.remove(cls)


class ViewManager:
    _views: typing.List[typing.Type[View]]
    _content_type_map: typing.Dict[str, typing.List[typing.Type[View]]]

    def __init__(self):
        self._views = []
        self._content_type_map = {}

    def __iter__(self):
        return iter(self._views)

    def add(self, view: typing.Type[View]) -> None:
        for x in self._views:
            if view.name == x.name:
                if inspect.getfile(view) == inspect.getfile(x):
                    # module has been reloaded, so we can remove the old one.
                    self.remove(x)
                else:
                    raise exceptions.ContentViewException("Duplicate view: " + view.name)

        # TODO: auto-select a replacement shortcut
        prompt_taken = any(x.prompt == view.prompt for x in self._views)
        if prompt_taken:
            raise exceptions.ContentViewException("Duplicate view shortcut: " + view.prompt[1])

        self._views.append(view)
        for ct in view.content_types:
            self._content_type_map.setdefault(ct, []).append(view)

    def remove(self, view: typing.Type[View]) -> None:
        self._views.remove(view)
        for ct in view.content_types:
            self._content_type_map[ct].remove(view)

    @property
    def view_prompts(self) -> typing.List[str]:
        return [x.prompt for x in self._views]

    def get(self, name: str) -> typing.Optional[typing.Type[View]]:
        for x in self._views:
            if x.name.lower() == name.lower():
                return x
        return None

    def get_by_shortcut(self, c: str) -> typing.Optional[typing.Type[View]]:
        for x in self._views:
            if x.prompt[1] == c:
                return x
        return None


views = ViewManager()


def safe_to_print(lines, encoding="utf8"):
    """
    Wraps a content generator so that each text portion is a *safe to print* unicode string.
    """
    for line in lines:
        clean_line = []
        for (style, text) in line:
            if isinstance(text, bytes):
                text = text.decode(encoding, "replace")
            text = strutils.escape_control_characters(text)
            clean_line.append((style, text))
        yield clean_line


def get_content_view(viewmode: typing.Type[View], data: bytes, **metadata):
    """
        Args:
            viewmode: the view to use.
            data, **metadata: arguments passed to View instance.

        Returns:
            A (description, content generator, error) tuple.
            If the content view raised an exception generating the view,
            the exception is returned in error and the flow is formatted in raw mode.
            In contrast to calling the views directly, text is always safe-to-print unicode.
    """
    try:
        ret = viewmode()(data, **metadata)
        if ret is None:
            ret = "Couldn't parse: falling back to Raw", views.get("raw")()(data, **metadata)[1]
        desc, content = ret
        error = None
    # Third-party viewers can fail in unexpected ways...
    except Exception:
        desc = "Couldn't parse: falling back to Raw"
        _, content = views.get("raw")()(data, **metadata)
        error = "{} Content viewer failed: \n{}".format(
            getattr(viewmode, "name"),
            traceback.format_exc()
        )

    return desc, safe_to_print(content), error


def get_message_content_view(viewname: str, message):
    """
    Like get_content_view, but also handles message encoding.
    """
    viewmode = views.get(viewname)
    if not viewmode:
        viewmode = views.get("auto")
    try:
        content = message.content
    except ValueError:
        content = message.raw_content
        enc = "[cannot decode]"
    else:
        if isinstance(message, http.Message) and content != message.raw_content:
            enc = "[decoded {}]".format(
                message.headers.get("content-encoding")
            )
        else:
            enc = None

    if content is None:
        return "", iter([[("error", "content missing")]]), None

    metadata = {}
    if isinstance(message, http.Request):
        metadata["query"] = message.query
    if isinstance(message, http.Message):
        metadata["headers"] = message.headers

    description, lines, error = get_content_view(
        viewmode, content, **metadata
    )

    if enc:
        description = "{} {}".format(enc, description)

    return description, lines, error
