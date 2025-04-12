# coding: utf-8
#
from asyncio import Future, get_event_loop, ensure_future
from logzero import logger
from ..device import get_device
from tornado.websocket import websocket_connect, WebSocketHandler
from tornado.ioloop import PeriodicCallback
import pyaudio
import time
import threading
import math
import struct
import psutil
import os
import json
import queue
import cv2

cached_devices = {}

class BaseHandler(WebSocketHandler):
    isSent = True
    msg = None
    bin = None
    
    def check_origin(self, origin: str):
        return True
    
    def send_message(self, msg, bin=False):
        if self.isSent:
            self.isSent = False
            try:
                fut = self.write_message(msg, bin)
            
                async def wrapper() -> None:
                    try:
                        await fut
                    except:
                        pass
                    
                    self.isSent = True
                    
                    if self.msg is not None:
                        msg = self.msg
                        bin = self.bin
                        self.msg = None
                        self.bin = None
                        self.send_message(msg, bin)

                ensure_future(wrapper())
            except:
                self.isSent = True
        else:
            self.msg = msg
            self.bin = bin

class ClientHandler(object):
    conn = None
    handlers = None
    strs = None
    d = None
    last = None
    isMinicap = None
    timeoutDisconn = None
    
    def __init__(self, id: str, name: str):
        self.handlers = []
        self.strs = {}
        self.id = id + "/" + name
        self.d = get_device(id)
        self.isMinicap = (name == 'minicap')
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
            bin = isinstance(message, bytes)
            if bin:
                self.last = message

            for handler in self.handlers:
                try:
                    if bin:
                        handler.send_message(message, True)
                    else:
                        handler.write_message(message, False)
                except:
                    pass
            if self.isMinicap and isinstance(message, str) and message.__contains__(" "):
                key, val = message.split(" ", maxsplit=1)
                self.strs[key] = val
    
    def on_close(self):
        del cached_devices[self.id]
        
        for handler in self.handlers:
            handler.close()
        
        if self.timeoutDisconn is not None:
            self.timeoutDisconn.stop()
            self.timeoutDisconn = None
        
        logger.info("client close")
        self.conn = None

    def add_handler(self, handler: BaseHandler):
        for key, val in self.strs.items():
            handler.write_message(key + " " + val)
        if self.last is not None:
            handler.send_message(self.last, True)
        if self.timeoutDisconn is not None:
            self.timeoutDisconn.stop()
            self.timeoutDisconn = None
        self.handlers.append(handler)
    
    def del_handler(self, handler: BaseHandler):
        self.handlers.remove(handler)
        if self.conn is not None and len(self.handlers) == 0 and self.timeoutDisconn is None:
            def do_timeout():
                self.conn.close(0, 'OK')
            
            self.timeoutDisconn = PeriodicCallback(do_timeout, 5000)
            self.timeoutDisconn.start()
    
    def write_message(self, message):
        if self.conn is not None:
            return self.conn.write_message(message, isinstance(message, bytes))

def get_client(id, name):
    key = id + "/" + name
    c = cached_devices.get(key)
    if c is None:
        c = ClientHandler(id, name)
    return c

sysInfoRunning = True

def stop_sys_info():
    global sysInfoRunning
    sysInfoRunning = False

sysInfoData = {}

def get_sys_info():
    global sysInfoData
    return sysInfoData

def sys_info_thread():
    global sysInfoRunning
    global sysInfoData
    
    while sysInfoRunning:
        sysInfo = {}
        sysInfo['cpuCount'] = psutil.cpu_count()
        sysInfo['cpuPercent'] = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        sysInfo['memTotal'] = mem.total
        sysInfo['memPercent'] = mem.percent
        disks = psutil.disk_partitions(False)
        usages = []
        map = {}
        for part in disks:
            if map.get(part.device) is not None:
                continue
            map[part.device] = True
            
            if part.opts.split(',').count('rw') > 0:
                usages.append(psutil.disk_usage(part.mountpoint))
        
        total = 0
        used = 0
        for usage in usages:
            total += usage.total
            used += usage.used
        sysInfo['diskCount'] = len(usages)
        sysInfo['diskTotal'] = total
        sysInfo['diskUsed'] = used
        sysInfo['diskPercent'] = 0
        if total > 0:
            sysInfo['diskPercent'] = used * 100 / total
        
        sysInfoData = sysInfo
        
        sysInfo = '@HostInfo ' + json.dumps(sysInfo, separators=(',',':'))
        for id in cached_devices:
            if id.endswith('/minicap'):
                c = cached_devices[id]
                for h in c.handlers:
                    h.loop.call_soon_threadsafe(h.write_message, sysInfo, False)

sysInfoThread = threading.Thread(target=sys_info_thread, name='SysInfo')

class MiniCapHandler(BaseHandler):
    id = ""
    d = None
    loop = None
    
    def open(self):
        self.loop = get_event_loop()
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
        
        try:
            if device is None:
                info = self.audio.get_default_input_device_info()
            else:
                info = self.audio.get_device_info_by_index(device)
            
            return info["maxInputChannels"]
        except:
            logger.error('Get Input device of channels error')
            return 1
    
    def open(self, input_device_index=None, channels=2, rate=48000, frames=None):
        if self.audio is None or self.stream is None:
            if frames is None:
                frames = 2048 # int(rate * 0.05) # 每秒20帧

            if self.audio is None:
                self.audio = pyaudio.PyAudio()
            
            try:
                self.stream = self.audio.open(format=pyaudio.paInt16, channels=channels, rate=rate, input=True, frames_per_buffer=frames, stream_callback=self.callback, input_device_index=input_device_index)
                self.stream.start_stream()
                # raise Exception("Test Exception")
                logger.info("Successfully opened the recording function, device: %s, channels: %s", str(input_device_index), str(channels))
            except:
                logger.warn("Failed to open the recording function, device: %s, channels: %s", str(input_device_index), str(channels))
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

                self.thrd = threading.Thread(target=do_timeout,args=(),name='AudioRecorder')
                self.thrd.start()
    
    def callback(self, in_data, frame_count, time_info = None, status = None):
        for h in self.handlers:
            h.loop.call_soon_threadsafe(h.send_message, in_data, True)
        
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

class Player(object):
    running: bool = True
    isRecord: bool = False
    msgQueue = None
    deviceIndex: int = None

    def init(self):
        self.msgQueue = queue.Queue(maxsize=50)
        self.thrd = threading.Thread(target=self.callback,args=(),name='AudioPlayer')
        self.thrd.start()

    def start(self):
        if self.isRecord:
            return False
        else:
            self.isRecord = True
            return True

    def callback(self):
        while self.running:
            if self.isRecord:
                audio = pyaudio.PyAudio()

                try:
                    rate = 48000
                    frames = 2048 # int(rate * 0.05) # 每秒20帧
                    stream = audio.open(format=pyaudio.paInt16, channels=2, rate=rate, output=True, frames_per_buffer=frames, output_device_index=self.deviceIndex)
                    stream.start_stream()
                    logger.info('start player device: %s', self.deviceIndex)
                    while self.running:
                        msg = self.msgQueue.get()
                        if msg is None:
                            break
                        else:
                            stream.write(msg)
                    logger.info('stop player device: %s', self.deviceIndex)
                    stream.stop_stream()
                except Exception as e:
                    logger.error("Unknown error: %r" % e)

                audio.terminate()
                
                try:
                    while self.msgQueue.get_nowait():
                        pass
                except:
                    pass
                
                self.isRecord = False
            else:
                time.sleep(0.05)
        else:
            return None

    def write(self, message):
        try:
            self.msgQueue.put_nowait(message)
        except:
            pass

    def stop(self):
        if self.isRecord:
            self.msgQueue.put(None)

    def close(self):
        self.msgQueue.put(None)
        self.running = False
        self.thrd.join()
        self.thrd = None

player: Player = Player()

class MiniPlayerHandler(BaseHandler):
    isOpen: bool = False

    def open(self):
        ret = player.start()
        if ret:
            self.isOpen = True
            self.write_message('OpenSuccess', False)
        else:
            self.write_message('OpenFailure', False)

    def on_message(self, message):
        if self.isOpen:
            player.write(message)
    
    def on_close(self):
        if self.isOpen:
            self.isOpen = False
            player.stop()


cameras = {}

class Camera(object):
    handlers: list = None
    thrd: threading.Thread = None
    path: str = None
    width: int = None
    height: int = None
    fps: int = None
    
    def __init__(self, path, width, height, fps):
        self.path = path
        self.width = width
        self.height = height
        self.fps = fps
        self.handlers = []
        cameras[self.path] = self
        self.thrd = threading.Thread(target=self.callback,args=(),name='Camera:'+path)
        self.thrd.start()
    
    def callback(self):
        time.sleep(0.2)
        
        while len(self.handlers) > 0:
            cap = cv2.VideoCapture(self.path)
            
            cap.set(cv2.CAP_PROP_FPS, self.fps)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            
            if not cap.isOpened():
                cap.release()
                time.sleep(5)
                continue
            
            logger.info("camera begin: %s, width: %d, height: %d, fps: %d", self.path, self.width, self.height, self.fps)
            
            t1 = time.time()
            
            while len(self.handlers) > 0:
                t2 = time.time()
                t = t1 - t2
                if t > 0:
                    time.sleep(t)
                    t1 += 0.05
                else:
                    t1 = t2 + 0.05
                
                ret, frame = cap.read()
                if ret:
                    _, frame = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
                    frame = frame.tobytes()
                    # logger.info('camera frame: %d', len(frame))
                    
                    self.send_message(frame)
                else:
                    break
            
            logger.info("camera end: %s", self.path)
            
            cap.release()
        
        del cameras[self.path]
    
    def add_handler(self, handler: BaseHandler):
        self.handlers.append(handler)
    
    def del_handler(self, handler: BaseHandler):
        self.handlers.remove(handler)

    def send_message(self, in_data):
        for h in self.handlers:
            h.loop.call_soon_threadsafe(h.send_message, in_data, True)

class CameraHandler(BaseHandler):
    loop = None
    c: Camera = None
    
    def open(self):
        self.loop = get_event_loop()
        
        path = self.get_query_argument("path")
        width = int(self.get_query_argument("width", '640'))
        height = int(self.get_query_argument("height", '480'))
        fps = int(self.get_query_argument("fps", '15'))
        self.c = cameras.get(path)
        if self.c is None:
            self.c = Camera(path, width, height, fps)
        self.c.add_handler(self)

    def on_message(self, message):
        pass
    
    def on_close(self):
        self.c.del_handler(self)
