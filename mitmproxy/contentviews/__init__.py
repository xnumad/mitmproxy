"""
Mitmproxy Content Views
=======================

mitmproxy includes a set of content views which can be used to
format/decode/highlight data. While they are currently used for HTTP message
bodies only, the may be used in other contexts in the future, e.g. to decode
protobuf messages sent as WebSocket frames.

Thus, the View API is very minimalistic. The only arguments are `data` and
`**metadata`, where `data` is the actual content (as bytes). The contents on
metadata depend on the protocol in use. For HTTP, the message headers are
passed as the ``headers`` keyword argument. For HTTP requests, the query
parameters are passed as the ``query`` keyword argument.
"""
from .base import View, views, VIEW_CUTOFF, get_content_view, get_message_content_view

__all__ = [
    "View", "views", "VIEW_CUTOFF",
    "get_content_view", "get_message_content_view",
]
