# Data receiver

# receives data from zmq address
# import time
import numpy as np
from threading import Event
from PyQt6 import QtCore

# import pyqtgraph as pg
# from pyqtgraph.dockarea import DockArea, Dock
import zmq

# import base64
# import blosc
# import ast
import struct
import pickle as pickle


class DataWorker(QtCore.QObject):
    data = QtCore.pyqtSignal(object)
    finished = QtCore.pyqtSignal()

    def __init__(self, deserializer):
        QtCore.QObject.__init__(self)
        self.deserializer = deserializer
        self._stop_readout = Event()
        self._send_data = None

    def connect_zmq(self, frontend_address, socket_type):
        self.context = zmq.Context()
        self.receiver = self.context.socket(socket_type)  # subscriber
        self.socket_type = socket_type
        # A subscriber has to set to not filter any data
        if self.socket_type == zmq.SUB:
            self.receiver.setsockopt_string(zmq.SUBSCRIBE, "")
        # Buffer only 10 messages, then throw data away
        self.receiver.set_hwm(10)
        self.receiver.connect(frontend_address)

    def receive_data(self):  # pragma: no cover; no covered since qt event loop
        """Infinite loop via QObject.moveToThread(), does not block event loop"""
        while not self._stop_readout.wait(0.01):  # use wait(), do not block
            # if self._send_data:
            #     if self.socket_type != zmq.DEALER:
            #         raise RuntimeError('You send data without a bidirectional '
            #                            'connection! Define a bidirectional '
            #                            'connection.')
            #     self.receiver.send_json(self._send_data)
            #     self._send_data = None
            try:
                data_serialized = self.receiver.recv(flags=zmq.NOBLOCK)
                raw, meta = self.deserializer(data_serialized)
                self.data.emit({"raw": raw, "meta": meta})
            except zmq.Again:
                pass
        self.finished.emit()

    def shutdown(self):
        self._stop_readout.set()

    def send_data(self, data):  # FIXME: not thread safe
        self._send_data = data


class TJReceiver:
    def __init__(self, frontend):
        self.socket_type = zmq.SUB
        self.frontend_address = frontend
        self.thread = QtCore.QThread()
        self.worker = DataWorker(self.deserialize_data)
        self.worker.moveToThread(self.thread)

    def start(self):
        # Connect to ZMQ publisher
        self.worker.connect_zmq(self.frontend_address, self.socket_type)
        # Quit thread on worker finished
        self.worker.finished.connect(self.thread.quit)
        # Activate data handle
        # self.worker.data.connect(self.handle_data_if_active)

        # Start receive data loop when thread starts
        self.thread.started.connect(self.worker.receive_data)
        # Print on thread finished info
        # self.thread.finished.connect(self.finished_info)
        self.thread.start()  # start thread

    def shutdown(self):
        # Set signal to quit receive loop; can take some time
        self.worker.shutdown()
        # Tell thread to exit, loop is/should be terminated already
        self.thread.exit()
        # Delay needed if thread did not exit yet, otherwise message:
        # QThread: Destroyed while thread is still running
        self.thread.wait(500)

    # def deserialize_data(self, data):
    #     ''' Has to convert the data do a python dict '''
    #     # return zmq.utils.jsonapi.loads(data, object_hook=self.json_numpy_obj_hook)
    #     print(self.simple_dec(data))
    #     self.data_deserialized = self.simple_dec(data)
    #     return self.simple_dec(data) [1]
    def deserialize_data(self, data):
        raw, meta = self.simple_dec(data)
        return raw, meta

    def simple_dec(self, data_buffer):
        len_buffer = data_buffer[-4:]
        length = struct.unpack("I", len_buffer)[0]

        meta = pickle.loads(data_buffer[-4 - length : -4])

        if "data_meta" in meta:
            dtype = meta["data_meta"]["dtype"]
            shape = meta["data_meta"]["shape"]
            data = np.frombuffer(data_buffer[: -4 - length], dtype).reshape(shape)
        else:
            data = None

        return data, meta
