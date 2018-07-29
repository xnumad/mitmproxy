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
        self.death_time: float = None

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

    def kill(self):
        self.death_time = time.time()

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
            dead = [stream for stream in self.streams.values() if stream.death_time]
            for stream in dead:
                if stream.death_time <= time.time() - 10:
                    self.streams.pop(stream.stream_id, None)


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
                        # TODO make async/re-entry so we can handle other streams!
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

                    # omit priority information because it is too complex to synchronize
                    other.send_headers(
                        server_stream_id,
                        headers=headers.items(),
                        end_stream=h2_event.stream_ended,
                    )
                    yield commands.SendData(send_to_other, other.data_to_send())

                elif isinstance(h2_event, h2events.ResponseReceived):
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
                        yield commands.SendData(send_to_source, source.data_to_send())
                        other.reset_stream(eid, h2.errors.ErrorCodes.REFUSED_STREAM)
                        yield commands.SendData(send_to_other, other.data_to_send())
                        yield commands.Log("HTTP body too large. Limit is {}.".format(bsl), "info")
                    else:
                        streaming = (
                            (from_client and self.streams[eid].flow.request.stream) or
                            (not from_client and self.streams[eid].flow.response and self.streams[eid].flow.response.stream)
                        )
                        if streaming:
                            stream_id = self.streams[eid].server_stream_id if from_client else self.streams[eid].stream_id
                            self.unfinished_bodies[other] = (stream_id, h2_event.data, False)
                            yield from self._send_body(send_to_other, other)
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
                        if streaming:
                            stream_id = self.streams[eid].server_stream_id if from_client else self.streams[eid].stream_id
                            self.unfinished_bodies[other] = (stream_id, b'', True, eid)
                            yield from self._send_body(send_to_other, other)
                        else:
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
                                kill_id = None
                            else:
                                self.streams[eid].flow.response.data.content = content
                                self.streams[eid].flow.response.timestamp_end = time.time()
                                yield commands.Hook("response", self.streams[eid].flow)
                                content = self.streams[eid].flow.response.data.content
                                stream_id = self.streams[eid].stream_id
                                kill_id = eid

                            self.unfinished_bodies[other] = (stream_id, content, True, kill_id)
                            yield from self._send_body(send_to_other, other)

                elif isinstance(h2_event, h2events.StreamReset):
                    if eid in self.streams:
                        self.streams[eid].kill()
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
                        yield from self._send_body(send_to_source, source)
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

    def _send_body(self, send_to_endpoint, endpoint):
        stream_id, content, end_stream, kill_id = self.unfinished_bodies[endpoint]

        max_outbound_frame_size = endpoint.max_outbound_frame_size
        position = 0
        while position < len(content):
            frame_chunk = content[position:position + max_outbound_frame_size]
            if endpoint.local_flow_control_window(stream_id) < len(frame_chunk):
                self.unfinished_bodies[endpoint] = (stream_id, content[position:], end_stream, kill_id)
                return
            endpoint.send_data(stream_id, frame_chunk)
            yield commands.SendData(send_to_endpoint, endpoint.data_to_send())
            position += max_outbound_frame_size

        del self.unfinished_bodies[endpoint]

        if end_stream:
            endpoint.end_stream(stream_id)
            yield commands.SendData(send_to_endpoint, endpoint.data_to_send())
        if kill_id:
            self.streams[kill_id].kill()
