import time
import functools
import queue
import threading
from typing import Dict, Callable, Any, List  # noqa

import h2.exceptions
from h2 import connection
from h2 import events as h2events

from mitmproxy import exceptions
from mitmproxy import http
from mitmproxy import flow
from mitmproxy.proxy.protocol import base
from mitmproxy.proxy.protocol import http as httpbase
import mitmproxy.net.http
from mitmproxy.net import tcp
from mitmproxy.coretypes import basethread
from mitmproxy.net.http import http2, headers
from mitmproxy.utils import human

from mitmproxy.proxy2 import events, commands
from mitmproxy.proxy2.context import Context
from mitmproxy.proxy2.layer import Layer
from mitmproxy.proxy2.utils import expect



# class SafeH2Connection(connection.H2Connection):
#
#     def __init__(self, conn, *args, **kwargs):
#         super().__init__(*args, **kwargs)
#         self.conn = conn
#
#
#     def safe_send_headers(self, raise_zombie: Callable, stream_id: int, headers: headers.Headers, **kwargs):
#         self.send_headers(stream_id, headers.fields, **kwargs)
#         self.conn.send(self.data_to_send())
#
#     def safe_send_body(self, raise_zombie: Callable, stream_id: int, chunks: List[bytes]):
#         for chunk in chunks:
#             position = 0
#             while position < len(chunk):
#                 self.lock.acquire()
#                 raise_zombie(self.lock.release)
#                 max_outbound_frame_size = self.max_outbound_frame_size
#                 frame_chunk = chunk[position:position + max_outbound_frame_size]
#                 if self.local_flow_control_window(stream_id) < len(frame_chunk):  # pragma: no cover
#                     self.lock.release()
#                     time.sleep(0.1)
#                     continue
#                 self.send_data(stream_id, frame_chunk)
#                 try:
#                     self.conn.send(self.data_to_send())
#                 except Exception as e:  # pragma: no cover
#                     raise e
#                 finally:
#                     self.lock.release()
#                 position += max_outbound_frame_size
#         self.end_stream(stream_id)
#         self.conn.send(self.data_to_send())


# class Http2Layer(base.Layer):
#
#     def _handle_event(self, event, source_conn, other_conn, is_server):
#         self.log(
#             "HTTP2 Event from {}".format("server" if is_server else "client"),
#             "debug",
#             [repr(event)]
#         )
#
#         eid = None
#         if hasattr(event, 'stream_id'):
#             if is_server and event.stream_id % 2 == 1:
#                 eid = self.server_to_client_stream_ids[event.stream_id]
#             else:
#                 eid = event.stream_id
#
#         if isinstance(event, events.RequestReceived):
#             return self._handle_request_received(eid, event)
#         elif isinstance(event, events.ResponseReceived):
#             return self._handle_response_received(eid, event)
#         elif isinstance(event, events.DataReceived):
#             return self._handle_data_received(eid, event, source_conn)
#         elif isinstance(event, events.StreamEnded):
#             return self._handle_stream_ended(eid)
#         elif isinstance(event, events.StreamReset):
#             return self._handle_stream_reset(eid, event, is_server, other_conn)
#         elif isinstance(event, events.RemoteSettingsChanged):
#             return self._handle_remote_settings_changed(event, other_conn)
#         elif isinstance(event, events.ConnectionTerminated):
#             return self._handle_connection_terminated(event, is_server)
#         elif isinstance(event, events.PushedStreamReceived):
#             return self._handle_pushed_stream_received(event)
#         elif isinstance(event, events.PriorityUpdated):
#             return self._handle_priority_updated(eid, event)
#         elif isinstance(event, events.TrailersReceived):
#             raise NotImplementedError('TrailersReceived not implemented')
#
#         # fail-safe for unhandled events
#         return True
#
#     def _handle_request_received(self, eid, event):
#         headers = mitmproxy.net.http.Headers([[k, v] for k, v in event.headers])
#         self.streams[eid] = Http2SingleStreamLayer(self, self.connections[self.client_conn], eid, headers)
#         self.streams[eid].timestamp_start = time.time()
#         self.streams[eid].no_body = (event.stream_ended is not None)
#         if event.priority_updated is not None:
#             self.streams[eid].priority_exclusive = event.priority_updated.exclusive
#             self.streams[eid].priority_depends_on = event.priority_updated.depends_on
#             self.streams[eid].priority_weight = event.priority_updated.weight
#             self.streams[eid].handled_priority_event = event.priority_updated
#         self.streams[eid].start()
#         self.streams[eid].request_arrived.set()
#         return True
#
#     def _handle_response_received(self, eid, event):
#         headers = mitmproxy.net.http.Headers([[k, v] for k, v in event.headers])
#         self.streams[eid].queued_data_length = 0
#         self.streams[eid].timestamp_start = time.time()
#         self.streams[eid].response_headers = headers
#         self.streams[eid].response_arrived.set()
#         return True
#
#     def _handle_connection_terminated(self, event, is_server):
#         self.log("HTTP/2 connection terminated by {}: error code: {}, last stream id: {}, additional data: {}".format(
#             "server" if is_server else "client",
#             event.error_code,
#             event.last_stream_id,
#             event.additional_data), "info")
#
#         if event.error_code != h2.errors.ErrorCodes.NO_ERROR:
#             # Something terrible has happened - kill everything!
#             self.connections[self.client_conn].close_connection(
#                 error_code=event.error_code,
#                 last_stream_id=event.last_stream_id,
#                 additional_data=event.additional_data
#             )
#             self.client_conn.send(self.connections[self.client_conn].data_to_send())
#             self._kill_all_streams()
#         else:
#             """
#             Do not immediately terminate the other connection.
#             Some streams might be still sending data to the client.
#             """
#         return False
#
#     def _handle_pushed_stream_received(self, event):
#         # pushed stream ids should be unique and not dependent on race conditions
#         # only the parent stream id must be looked up first
#
#         parent_eid = self.server_to_client_stream_ids[event.parent_stream_id]
#         with self.connections[self.client_conn].lock:
#             self.connections[self.client_conn].push_stream(parent_eid, event.pushed_stream_id, event.headers)
#             self.client_conn.send(self.connections[self.client_conn].data_to_send())
#
#         headers = mitmproxy.net.http.Headers([[k, v] for k, v in event.headers])
#         layer = Http2SingleStreamLayer(self, self.connections[self.client_conn], event.pushed_stream_id, headers)
#         self.streams[event.pushed_stream_id] = layer
#         self.streams[event.pushed_stream_id].timestamp_start = time.time()
#         self.streams[event.pushed_stream_id].pushed = True
#         self.streams[event.pushed_stream_id].parent_stream_id = parent_eid
#         self.streams[event.pushed_stream_id].timestamp_end = time.time()
#         self.streams[event.pushed_stream_id].request_arrived.set()
#         self.streams[event.pushed_stream_id].request_data_finished.set()
#         self.streams[event.pushed_stream_id].start()
#         return True
#
#     def _handle_priority_updated(self, eid, event):
#         if not self.config.options.http2_priority:
#             self.log("HTTP/2 PRIORITY frame suppressed. Use --http2-priority to enable forwarding.", "debug")
#             return True
#
#         if eid in self.streams and self.streams[eid].handled_priority_event is event:
#             # this event was already handled during stream creation
#             # HeadersFrame + Priority information as RequestReceived
#             return True
#
#         with self.connections[self.server_conn].lock:
#             mapped_stream_id = event.stream_id
#             if mapped_stream_id in self.streams and self.streams[mapped_stream_id].server_stream_id:
#                 # if the stream is already up and running and was sent to the server,
#                 # use the mapped server stream id to update priority information
#                 mapped_stream_id = self.streams[mapped_stream_id].server_stream_id
#
#             if eid in self.streams:
#                 self.streams[eid].priority_exclusive = event.exclusive
#                 self.streams[eid].priority_depends_on = event.depends_on
#                 self.streams[eid].priority_weight = event.weight
#
#             self.connections[self.server_conn].prioritize(
#                 mapped_stream_id,
#                 weight=event.weight,
#                 depends_on=self._map_depends_on_stream_id(mapped_stream_id, event.depends_on),
#                 exclusive=event.exclusive
#             )
#             self.server_conn.send(self.connections[self.server_conn].data_to_send())
#         return True
#
#     def _map_depends_on_stream_id(self, stream_id, depends_on):
#         mapped_depends_on = depends_on
#         if mapped_depends_on in self.streams and self.streams[mapped_depends_on].server_stream_id:
#             # if the depends-on-stream is already up and running and was sent to the server
#             # use the mapped server stream id to update priority information
#             mapped_depends_on = self.streams[mapped_depends_on].server_stream_id
#         if stream_id == mapped_depends_on:
#             # looks like one of the streams wasn't opened yet
#             # prevent self-dependent streams which result in ProtocolError
#             mapped_depends_on += 2
#         return mapped_depends_on
#
#     def _cleanup_streams(self):
#         death_time = time.time() - 10
#
#         zombie_streams = [(stream_id, stream) for stream_id, stream in list(self.streams.items()) if stream.zombie]
#         outdated_streams = [stream_id for stream_id, stream in zombie_streams if stream.zombie <= death_time]
#
#         for stream_id in outdated_streams:  # pragma: no cover
#             self.streams.pop(stream_id, None)
#
#     def _kill_all_streams(self):
#         for stream in self.streams.values():
#             stream.kill()
#
#     def __call__(self):
#         self._initiate_server_conn()
#         self._complete_handshake()
#
#         conns = [c.connection for c in self.connections.keys()]
#
#         try:
#             while True:
#                 r = tcp.ssl_read_select(conns, 0.1)
#                 for conn in r:
#                     source_conn = self.client_conn if conn == self.client_conn.connection else self.server_conn
#                     other_conn = self.server_conn if conn == self.client_conn.connection else self.client_conn
#                     is_server = (source_conn == self.server_conn)
#
#                     with self.connections[source_conn].lock:
#                         try:
#                             raw_frame = b''.join(http2.read_raw_frame(source_conn.rfile))
#                         except:
#                             # read frame failed: connection closed
#                             self._kill_all_streams()
#                             return
#
#                         if self.connections[source_conn].state_machine.state == h2.connection.ConnectionState.CLOSED:
#                             self.log("HTTP/2 connection entered closed state already", "debug")
#                             return
#
#                         incoming_events = self.connections[source_conn].receive_data(raw_frame)
#                         source_conn.send(self.connections[source_conn].data_to_send())
#
#                         for event in incoming_events:
#                             if not self._handle_event(event, source_conn, other_conn, is_server):
#                                 # connection terminated: GoAway
#                                 self._kill_all_streams()
#                                 return
#
#                     self._cleanup_streams()
#         except Exception as e:  # pragma: no cover
#             self.log(repr(e), "info")
#             self._kill_all_streams()


# class Http2SingleStreamLayer(httpbase._HttpTransmissionLayer, basethread.BaseThread):
#
#     def __init__(self, ctx, h2_connection, stream_id: int, request_headers: mitmproxy.net.http.Headers) -> None:
#         super().__init__(
#             ctx, name="Http2SingleStreamLayer-{}".format(stream_id)
#         )
#         self.h2_connection = h2_connection
#         self.zombie: float = None
#         self.client_stream_id: int = stream_id
#         self.server_stream_id: int = None
#         self.request_headers = request_headers
#         self.response_headers: mitmproxy.net.http.Headers = None
#         self.pushed = False
#
#         self.timestamp_start: float = None
#         self.timestamp_end: float = None
#
#         self.request_arrived = threading.Event()
#         self.request_data_queue: queue.Queue[bytes] = queue.Queue()
#         self.request_queued_data_length = 0
#         self.request_data_finished = threading.Event()
#
#         self.response_arrived = threading.Event()
#         self.response_data_queue: queue.Queue[bytes] = queue.Queue()
#         self.response_queued_data_length = 0
#         self.response_data_finished = threading.Event()
#
#         self.no_body = False
#
#         self.priority_exclusive: bool = None
#         self.priority_depends_on: int = None
#         self.priority_weight: int = None
#         self.handled_priority_event: Any = None
#
#     def kill(self):
#         if not self.zombie:
#             self.zombie = time.time()
#             self.request_data_finished.set()
#             self.request_arrived.set()
#             self.response_arrived.set()
#             self.response_data_finished.set()
#
#     def connect(self):  # pragma: no cover
#         raise exceptions.Http2ProtocolException("HTTP2 layer should already have a connection.")
#
#     def disconnect(self):  # pragma: no cover
#         raise exceptions.Http2ProtocolException("Cannot dis- or reconnect in HTTP2 connections.")
#
#     def set_server(self, address):  # pragma: no cover
#         raise exceptions.SetServerNotAllowedException(repr(address))
#
#     def check_close_connection(self, flow):
#         # This layer only handles a single stream.
#         # RFC 7540 8.1: An HTTP request/response exchange fully consumes a single stream.
#         return True
#
#     @property
#     def data_queue(self):
#         if self.response_arrived.is_set():
#             return self.response_data_queue
#         else:
#             return self.request_data_queue
#
#     @property
#     def queued_data_length(self):
#         if self.response_arrived.is_set():
#             return self.response_queued_data_length
#         else:
#             return self.request_queued_data_length
#
#     @queued_data_length.setter
#     def queued_data_length(self, v):
#         self.request_queued_data_length = v
#
#     @property
#     def data_finished(self):
#         if self.response_arrived.is_set():
#             return self.response_data_finished
#         else:
#             return self.request_data_finished
#
#     def raise_zombie(self, pre_command=None):  # pragma: no cover
#         connection_closed = self.h2_connection.state_machine.state == h2.connection.ConnectionState.CLOSED
#         if self.zombie is not None or connection_closed:
#             if pre_command is not None:
#                 pre_command()
#             raise exceptions.Http2ZombieException("Connection already dead")
#
#     @detect_zombie_stream
#     def read_request_headers(self, flow):
#         self.request_arrived.wait()
#         self.raise_zombie()
#
#         if self.pushed:
#             flow.metadata['h2-pushed-stream'] = True
#
#         first_line_format, method, scheme, host, port, path = http2.parse_headers(self.request_headers)
#         return http.HTTPRequest(
#             first_line_format,
#             method,
#             scheme,
#             host,
#             port,
#             path,
#             b"HTTP/2.0",
#             self.request_headers,
#             None,
#             timestamp_start=self.timestamp_start,
#             timestamp_end=self.timestamp_end,
#         )
#
#     @detect_zombie_stream
#     def read_request_body(self, request):
#         if not request.stream:
#             self.request_data_finished.wait()
#
#         while True:
#             try:
#                 yield self.request_data_queue.get(timeout=0.1)
#             except queue.Empty:  # pragma: no cover
#                 pass
#             if self.request_data_finished.is_set():
#                 self.raise_zombie()
#                 while self.request_data_queue.qsize() > 0:
#                     yield self.request_data_queue.get()
#                 break
#             self.raise_zombie()
#
#
#     @detect_zombie_stream
#     def send_request_body(self, request, chunks):
#         if self.pushed:
#             # nothing to do here
#             return
#
#         if not self.no_body:
#             self.connections[self.server_conn].safe_send_body(
#                 self.raise_zombie,
#                 self.server_stream_id,
#                 chunks
#             )
#
#     @detect_zombie_stream
#     def send_request(self, message):
#         self.send_request_headers(message)
#         self.send_request_body(message, [message.content])
#
#     @detect_zombie_stream
#     def read_response_headers(self):
#         self.response_arrived.wait()
#
#         self.raise_zombie()
#
#         status_code = int(self.response_headers.get(':status', 502))
#         headers = self.response_headers.copy()
#         headers.pop(":status", None)
#
#         return http.HTTPResponse(
#             http_version=b"HTTP/2.0",
#             status_code=status_code,
#             reason=b'',
#             headers=headers,
#             content=None,
#             timestamp_start=self.timestamp_start,
#             timestamp_end=self.timestamp_end,
#         )
#
#     @detect_zombie_stream
#     def read_response_body(self, request, response):
#         while True:
#             try:
#                 yield self.response_data_queue.get(timeout=0.1)
#             except queue.Empty:  # pragma: no cover
#                 pass
#             if self.response_data_finished.is_set():
#                 self.raise_zombie()
#                 while self.response_data_queue.qsize() > 0:
#                     yield self.response_data_queue.get()
#                 break
#             self.raise_zombie()
#
#     @detect_zombie_stream
#     def send_response_headers(self, response):
#         headers = response.headers.copy()
#         headers.insert(0, ":status", str(response.status_code))
#         with self.connections[self.client_conn].lock:
#             self.connections[self.client_conn].safe_send_headers(
#                 self.raise_zombie,
#                 self.client_stream_id,
#                 headers
#             )
#
#     @detect_zombie_stream
#     def send_response_body(self, _response, chunks):
#         self.connections[self.client_conn].safe_send_body(
#             self.raise_zombie,
#             self.client_stream_id,
#             chunks
#         )



class Http2Stream:

    def __init__(self, h2_event, client_conn, server_conn) -> None:

        if isinstance(h2_event, h2.events.RequestReceived):
            self.stream_id = h2_event.stream_id
        else:
            self.stream_id = h2_event.pushed_stream_id

        self.server_stream_id: int = None
        self.pushed = False

        if isinstance(h2_event, h2.events.RequestReceived) and h2_event.priority_updated is not None:
            self.priority_exclusive = h2_event.priority_updated.exclusive
            self.priority_depends_on = h2_event.priority_updated.depends_on
            self.priority_weight = h2_event.priority_updated.weight
            self.handled_priority_event = h2_event.priority_updated
        else:
            self.priority_exclusive: bool = None
            self.priority_depends_on: int = None
            self.priority_weight: int = None
            self.handled_priority_event: Any = None

        self.timestamp_start: float = None
        self.timestamp_end: float = None

        self.request_arrived = threading.Event()
        self.request_data_queue: queue.Queue[bytes] = queue.Queue()
        self.request_queued_data_length = 0
        self.request_data_finished = threading.Event()

        self.response_arrived = threading.Event()
        self.response_data_queue: queue.Queue[bytes] = queue.Queue()
        self.response_queued_data_length = 0
        self.response_data_finished = threading.Event()

        self.flow = http.HTTPFlow(
            client_conn,
            server_conn,
            live=self,
            mode='regular',
        )

        headers = mitmproxy.net.http.Headers([[k, v] for k, v in h2_event.headers])
        first_line_format, method, scheme, host, port, path = http2.parse_headers(headers)
        self.flow.request = http.HTTPRequest(
            first_line_format,
            method,
            scheme,
            host,
            port,
            path,
            b"HTTP/2.0",
            headers,
            None,
            timestamp_start=self.timestamp_start,
            timestamp_end=self.timestamp_end,
        )

    @property
    def data_queue(self):
        if self.response_arrived.is_set():
            return self.response_data_queue
        else:
            return self.request_data_queue

    @property
    def queued_data_length(self):
        if self.response_arrived.is_set():
            return self.response_queued_data_length
        else:
            return self.request_queued_data_length

    @queued_data_length.setter
    def queued_data_length(self, v):
        self.request_queued_data_length = v

    @property
    def data_finished(self):
        if self.response_arrived.is_set():
            return self.response_data_finished
        else:
            return self.request_data_finished

class HTTP2Layer(Layer):
    context: Context = None

    def __init__(self, context: Context):
        super().__init__(context)
        assert context.server.connected

    @expect(events.Start)
    def start(self, _) -> commands.TCommandGenerator:
        client_config = h2.config.H2Configuration(
            client_side=False,
            header_encoding=False,
            validate_outbound_headers=False,
            validate_inbound_headers=False)
        self.client_conn = connection.H2Connection(config=client_config)
        self.client_conn.initiate_connection()
        yield commands.SendData(self.context.client, self.client_conn.data_to_send())

        server_config = h2.config.H2Configuration(
            client_side=True,
            header_encoding=False,
            validate_outbound_headers=False,
            validate_inbound_headers=False)
        self.server_conn = connection.H2Connection(config=server_config)
        self.server_conn.initiate_connection()
        yield commands.SendData(self.context.server, self.server_conn.data_to_send())

        self.streams: Dict[int, Http2Stream] = dict()
        self.server_to_client_stream_ids: Dict[int, int] = dict([(0, 0)])
        self.unfinished_bodies: Dict[connection.H2H2Connection, tuple] = dict()

        yield commands.Log("HTTP/2 connection started")

        self._handle_event = self.process_data

    _handle_event = start

    @expect(events.DataReceived, events.ConnectionClosed)
    def process_data(self, event: events.Event) -> commands.TCommandGenerator:
        if isinstance(event, events.DataReceived):
            from_client = event.connection == self.context.client
            if from_client:
                source = self.client_conn
                other = self.server_conn
                send_to_source = self.context.client
                send_to_other = self.context.server
            else:
                source = self.server_conn
                other = self.client_conn
                send_to_source = self.context.server
                send_to_other = self.context.client

            received_h2_events = source.receive_data(event.data)
            yield commands.SendData(send_to_source, source.data_to_send())

            for h2_event in received_h2_events:
                yield commands.Log(
                    "HTTP/2 event from {}: {}".format("client" if from_client else "server", h2_event)
                )

                eid = None
                if hasattr(h2_event, 'stream_id'):
                    if not from_client and h2_event.stream_id % 2 == 1:
                        eid = self.server_to_client_stream_ids[h2_event.stream_id]
                    else:
                        eid = h2_event.stream_id

                if isinstance(h2_event, h2events.RequestReceived):
                    self.streams[eid] = Http2Stream(h2_event, self.context.client, self.context.server)
                    self.streams[eid].timestamp_start = time.time()
                    self.streams[eid].request_arrived.set()

                    yield commands.Hook("requestheaders", self.streams[eid].flow)

                    while other.open_outbound_streams + 1 >= other.remote_settings.max_concurrent_streams:
                        # wait until we get a free slot for a new outgoing stream
                        # TODO make async so we can handle other streams!
                        # time.sleep(0.1)
                        break

                    server_stream_id = other.get_next_available_stream_id()
                    self.streams[eid].server_stream_id = server_stream_id
                    self.server_to_client_stream_ids[server_stream_id] = h2_event.stream_id

                    if h2_event.stream_ended:
                        self.streams[eid].request_data_finished.set()

                    headers = self.streams[eid].flow.request.headers.copy()
                    headers.insert(0, ":path", self.streams[eid].flow.request.path)
                    headers.insert(0, ":method", self.streams[eid].flow.request.method)
                    headers.insert(0, ":scheme", self.streams[eid].flow.request.scheme)
                    headers.pop("if-none-match", None)
                    headers.pop("if-modified-since", None)

                    other.send_headers(
                        server_stream_id,
                        headers=headers.items(),
                        end_stream=h2_event.stream_ended,
                        priority_exclusive=self.streams[eid].priority_exclusive,
                        priority_depends_on=self.streams[eid].priority_depends_on,
                        priority_weight=self.streams[eid].priority_weight,
                    )
                    yield commands.SendData(send_to_other, other.data_to_send())

                elif isinstance(h2_event, h2events.ResponseReceived):
                    yield commands.Log(f"response received {eid} {h2_event.stream_id}")
                    self.streams[eid].queued_data_length = 0
                    self.streams[eid].timestamp_start = time.time()
                    self.streams[eid].response_arrived.set()

                    headers = mitmproxy.net.http.Headers([[k, v] for k, v in h2_event.headers])
                    status_code = int(headers.get(':status', 502))
                    headers.pop(":status", None)

                    self.streams[eid].flow.response = http.HTTPResponse(
                        http_version=b"HTTP/2.0",
                        status_code=status_code,
                        reason=b'',
                        headers=headers,
                        content=None,
                        timestamp_start=self.streams[eid].timestamp_start,
                        timestamp_end=self.streams[eid].timestamp_end,
                    )

                    yield commands.Hook("responseheaders", self.streams[eid].flow)

                    if self.streams[eid].flow.response.stream:
                        self.streams[eid].flow.response.data.content = None

                    headers = self.streams[eid].flow.response.headers
                    headers.insert(0, ":status", str(self.streams[eid].flow.response.status_code))

                    other.send_headers(
                        self.streams[eid].stream_id,
                        headers=headers.items(),
                    )
                    yield commands.SendData(send_to_other, other.data_to_send())

                elif isinstance(h2_event, h2events.DataReceived):
                    bsl = human.parse_size(self.context.options.body_size_limit)
                    if bsl and self.streams[eid].queued_data_length > bsl:
                        self.streams[eid].kill()
                        source.reset_stream(eid, h2.errors.ErrorCodes.REFUSED_STREAM)
                        yield commands.SendData(send_to_other, other.data_to_send())
                        yield commands.Log("HTTP body too large. Limit is {}.".format(bsl), "info")
                    else:
                        streaming = (
                            (from_client and self.streams[eid].flow.request.stream) or
                            (not from_client and self.streams[eid].flow.response and self.streams[eid].flow.response.stream)
                        )
                        if streaming:
                            source.acknowledge_received_data(h2_event.flow_controlled_length, eid)
                            yield commands.SendData(send_to_source, source.data_to_send())

                            stream_id = self.streams[eid].server_stream_id if from_client else self.streams[eid].stream_id
                            other.send_data(stream_id, h2_event.data) # TODO: this assumes the max frame size matches
                            yield commands.SendData(send_to_other, other.data_to_send())
                        else:
                            self.streams[eid].data_queue.put(h2_event.data)
                            self.streams[eid].queued_data_length += len(h2_event.data)

                    source.acknowledge_received_data(h2_event.flow_controlled_length, h2_event.stream_id)
                    yield commands.SendData(send_to_source, source.data_to_send())

                elif isinstance(h2_event, h2events.StreamEnded):
                    self.streams[eid].timestamp_end = time.time()
                    self.streams[eid].data_finished.set()

                    if from_client and self.streams[eid].request_data_finished:
                        # end_stream already communicated via request send_headers
                        pass
                    else:
                        streaming = (
                            (from_client and self.streams[eid].flow.request.stream) or
                            (not from_client and self.streams[eid].flow.response and self.streams[eid].flow.response.stream)
                        )
                        if not streaming:
                            content = b""
                            while True:
                                try:
                                    content += self.streams[eid].data_queue.get_nowait()
                                except queue.Empty:
                                    break

                            if from_client:
                                self.streams[eid].flow.request.data.content = content
                                self.streams[eid].flow.request.timestamp_end = time.time()
                                yield commands.Hook("request", self.streams[eid].flow)
                                content = self.streams[eid].flow.request.data.content
                                stream_id = self.streams[eid].server_stream_id
                            else:
                                self.streams[eid].flow.response.data.content = content
                                self.streams[eid].flow.response.timestamp_end = time.time()
                                yield commands.Hook("response", self.streams[eid].flow)
                                content = self.streams[eid].flow.response.data.content
                                stream_id = self.streams[eid].stream_id

                            self.unfinished_bodies[other] = (stream_id, content)
                            yield from self._send_body(other, send_to_other)

                elif isinstance(h2_event, h2events.StreamReset):
                    if eid in self.streams:
                        if h2_event.error_code == h2.errors.ErrorCodes.CANCEL:
                            try:
                                stream_id = self.streams[eid].server_stream_id if from_client else self.streams[eid].stream_id
                                if stream_id:
                                    other.reset_stream(stream_id, h2_event.error_code)
                            except h2.exceptions.StreamClosedError:  # pragma: no cover
                                # stream is already closed - good
                                pass
                            yield commands.SendData(send_to_other, other.data_to_send())

                elif isinstance(h2_event, h2events.RemoteSettingsChanged):
                    new_settings = dict([(key, cs.new_value) for (key, cs) in h2_event.changed_settings.items()])
                    other.update_settings(new_settings)
                    yield commands.SendData(send_to_other, other.data_to_send())

                elif isinstance(h2_event, h2events.ConnectionTerminated):
                    yield commands.Log(f"HTTP/2 Connection terminated: {h2_event}, {h2_event.additional_data}")
                    pass
                elif isinstance(h2_event, h2events.PushedStreamReceived):
                    parent_eid = self.server_to_client_stream_ids[h2_event.parent_stream_id]
                    other.push_stream(parent_eid, h2_event.pushed_stream_id, h2_event.headers)
                    yield commands.SendData(send_to_other, other.data_to_send())

                    self.streams[h2_event.pushed_stream_id] = Http2Stream(h2_event, self.context.client, self.context.server)
                    self.streams[h2_event.pushed_stream_id].timestamp_start = time.time()
                    self.streams[h2_event.pushed_stream_id].pushed = True
                    self.streams[h2_event.pushed_stream_id].parent_stream_id = parent_eid
                    self.streams[h2_event.pushed_stream_id].timestamp_end = time.time()
                    self.streams[h2_event.pushed_stream_id].request_arrived.set()
                    self.streams[h2_event.pushed_stream_id].request_data_finished.set()

                    yield commands.Hook("requestheaders", self.streams[h2_event.pushed_stream_id].flow)

                elif isinstance(h2_event, h2events.WindowUpdated):
                    if source in self.unfinished_bodies:
                        self._send_body(source, send_to_source)
                elif isinstance(h2_event, h2events.PriorityUpdated):
                    pass
                elif isinstance(h2_event, h2events.TrailersReceived):
                    raise NotImplementedError('TrailersReceived not implemented')

        elif isinstance(event, events.ConnectionClosed):
            yield commands.Log("Connection closed abnormally")
            if event.connection == self.context.server:
                yield commands.CloseConnection(self.context.client)
            self._handle_event = self.done

    @expect(events.DataReceived, events.ConnectionClosed)
    def done(self, _):
        yield from ()

    def _send_body(self, other, send_to_other):
        stream_id, content = self.unfinished_bodies[other]

        max_outbound_frame_size = other.max_outbound_frame_size
        position = 0
        while position < len(content):
            frame_chunk = content[position:position + max_outbound_frame_size]
            if other.local_flow_control_window(stream_id) < len(frame_chunk):
                self.unfinished_bodies[other] = (stream_id, content[position:])
                return
            other.send_data(stream_id, frame_chunk)
            yield commands.SendData(send_to_other, other.data_to_send())
            position += max_outbound_frame_size

        del self.unfinished_bodies[other]
        other.end_stream(stream_id)
        yield commands.SendData(send_to_other, other.data_to_send())
