# coding: utf-8
#
from asyncio import Future, get_event_loop
from logzero import logger
from weditor.web.device import get_device
from tornado.websocket import websocket_connect, WebSocketHandler
import pyaudio
import time
import threading
import math
import struct

cached_devices = {}

class BaseHandler(WebSocketHandler):
    def check_origin(self, origin: str):
        return True

class ClientHandler(object):
    conn = None
    handlers = None
    strs = None
    d = None
    
    def __init__(self, id: str, name: str):
        self.handlers = []
        self.strs = {}
        self.id = id + "/" + name
        self.d = get_device(id)
        ws_addr = self.d.device.address.replace("http://", "ws://") # yapf: disable
        url = ws_addr + "/" + name
        
        websocket_connect(url, callback=self.on_open, on_message_callback=self.on_message, connect_timeout=10)
        
        cached_devices[self.id] = self
    
    def on_open(self, future: Future = None):
        logger.info("client open")
        try:
            self.conn = future.result()
        except:
            self.on_close()
    
    def on_message(self, message):
        if message is None:
            self.on_close()
        else:
            # logger.debug("client message: %s", message)
            for handler in self.handlers:
                try:
                    handler.write_message(message, isinstance(message, bytes))
                except:
                    pass
            if isinstance(message, str) and message.__contains__(" "):
                key, val = message.split(" ", maxsplit=1)
                self.strs[key] = val
    
    def on_close(self):
        logger.info("client close")
        
        for handler in self.handlers:
            handler.close()
        
        self.handlers.clear()
        del cached_devices[self.id]
    
    def add_handler(self, handler: BaseHandler):
        for key, val in self.strs.items():
            handler.write_message(key + " " + val)
        self.handlers.append(handler)
    
    def del_handler(self, handler: BaseHandler):
        self.handlers.remove(handler)
    
    def write_message(self, message):
        if self.conn is not None:
            return self.conn.write_message(message, isinstance(message, bytes))

def get_client(id, name):
    key = id + "/" + name
    c = cached_devices.get(key)
    if c is None:
        c = ClientHandler(id, name)
    return c

class MiniCapHandler(BaseHandler):
    id = ""
    d = None
    def open(self):
        self.id = self.get_query_argument("deviceId")
        self.d = get_client(self.id, 'minicap')
        self.d.add_handler(self)
        
        logger.info("MiniCap opened: %s", self.id)

    def on_message(self, message):
        # logger.info("MiniCap message: %s", message)
        self.d.write_message(message)

    def on_close(self):
        logger.info("MiniCap closed")
        self.d.del_handler(self)
        self.d = None

class MiniTouchHandler(BaseHandler):
    id = ""
    d = None
    def open(self):
        self.id = self.get_query_argument("deviceId")
        self.d = get_client(self.id, "minitouch")
        self.d.add_handler(self)
        
        logger.info("MiniTouch opened: %s", id)

    def on_message(self, message):
        # logger.info("MiniTouch message: %s", message)
        self.d.write_message(message)

    def on_close(self):
        logger.info("MiniTouch closed")
        self.d.del_handler(self)
        self.d = None

class Sound(object):
    audio: pyaudio.PyAudio = None
    stream: pyaudio.Stream = None
    handlers: list = None
    music: bytes = None
    thrd: threading.Thread = None
    running: bool = True
    
    def __init__(self) -> None:
        self.handlers = []
    
    def getChannels(self, device):
        if self.audio is None:
            self.audio = pyaudio.PyAudio()
        
        if device is None:
            info = self.audio.get_default_input_device_info()
        else:
            info = self.audio.get_device_info_by_index(device)
        
        return info["maxInputChannels"]
    
    def open(self, input_device_index=None, channels=2, rate=44100, frames=None):
        if self.audio is None or self.stream is None:
            if frames is None:
                frames = int(rate * 0.05) # 每秒20帧

            if self.audio is None:
                self.audio = pyaudio.PyAudio()
            
            try:
                self.stream = self.audio.open(format=pyaudio.paInt16, channels=channels, rate=rate, input=True, frames_per_buffer=frames, stream_callback=self.callback, input_device_index=input_device_index)
                self.stream.start_stream()
                # raise Exception("Test Exception")
                logger.info("Successfully opened the recording function")
            except:
                logger.warn("Failed to open the recording function, channels: %d", channels)
                self.close()
                music = bytearray(frames * channels * 2)
                offset = 0
                n = (frames / 50)
                for i in range(frames):
                    angle = math.radians(i * 360.0 / n)
                    if channels > 0:
                        struct.pack_into("h", music, offset, int(math.sin(angle) * 30000))
                        offset += 2
                    if channels > 1:
                        struct.pack_into("h", music, offset, int(math.cos(angle) * 30000))
                        offset += 2

                self.music = bytes(music)

                def do_timeout():
                    while self.running:
                        self.callback(self.music, frames)
                        time.sleep(5)

                self.thrd = threading.Thread(target=do_timeout,args=(),name='循环子线程')
                self.thrd.start()
    
    def callback(self, in_data, frame_count, time_info = None, status = None):
        for h in self.handlers:
            h.loop.call_soon_threadsafe(h.write_message, in_data, True)
        
        return b"", pyaudio.paContinue
    
    def add_handler(self, handler: BaseHandler):
        logger.info("sound add_handler")
        self.handlers.append(handler)
    
    def del_handler(self, handler: BaseHandler):
        logger.info("sound del_handler")
        self.handlers.remove(handler)

    def close(self):
        if self.stream is not None:
            self.stream.stop_stream()
            self.stream = None
        if self.audio is not None:
            self.audio.terminate()
            self.audio = None
        if self.thrd is not None:
            self.running = False
            self.thrd.join()
            self.thrd = None

sound: Sound = Sound()

class MiniSoundHandler(BaseHandler):
    loop = None
    
    def open(self):
        self.loop = get_event_loop()
        sound.add_handler(self)

    def on_message(self, message):
        pass

    def on_close(self):
        sound.del_handler(self)
