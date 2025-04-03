# coding: utf-8
#

import base64
import io
import json
import os
import math
import traceback
import time
import tornado
import re
import threading
import queue
import asyncio
import concurrent.futures
import zipfile
from logzero import logger
from PIL import Image
from tornado.escape import json_decode
from tornado.ioloop import IOLoop
from tornado.concurrent import Future

from ..device import get_device
from .mini import get_sys_info
from ..version import __version__

pathjoin = os.path.join


channels = 2

def setChannels(c):
    global channels
    channels = c

async def run_in_executor(func, *args):
    with concurrent.futures.ThreadPoolExecutor() as pool:
        loop = asyncio.get_event_loop()
        ret = await loop.run_in_executor(pool, func, *args)
        return ret

class BaseHandler(tornado.web.RequestHandler):
    def set_default_headers(self):
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "*")
        self.set_header("Access-Control-Allow-Credentials",
                        "true")  # allow cookie
        self.set_header('Access-Control-Allow-Methods',
                        'POST, GET, PUT, DELETE, OPTIONS')

    def options(self, *args):
        self.set_status(204)  # no body
        self.finish()

    def check_origin(self, origin):
        """ allow cors request """
        return True


class VersionHandler(BaseHandler):
    def get(self):
        global channels
        ret = {
            'name': "weditor",
            'version': __version__,
            'channels': channels,
        }
        self.write(ret)


class MainHandler(BaseHandler):
    def get(self):
        self.render("index.html", channels=channels)


class SysInfoHandler(BaseHandler):
    def get(self):
        self.write(get_sys_info())


async def pipe(reader, writer):
    try:
        while not reader.at_eof():
            writer.write(await reader.read(2048))
    finally:
        writer.close()

async def handle_client(local_reader, local_writer):
    try:
        remote_reader, remote_writer = await asyncio.open_connection(
            '127.0.0.1', 7912)
        pipe1 = pipe(local_reader, remote_writer)
        pipe2 = pipe(remote_reader, local_writer)
        await asyncio.gather(pipe1, pipe2)
    finally:
        local_writer.close()

atx_tunnels = {}
async def atx_tunnel(host):
    global atx_tunnels

    if host != '127.0.0.1' and atx_tunnels.get(host) is None:
        atx_tunnels[host] = await asyncio.start_server(handle_client, host, 7912)
        logger.info('atx tunnel host is %s', host)

class DeviceConnectHandler(BaseHandler):
    async def post(self):
        platform = self.get_argument("platform").lower()
        device_url = self.get_argument("deviceUrl")

        is_atx = False
        try:
            await atx_tunnel(self.request.host_name)
            is_atx = True
        except Exception as e:
            logger.warning("atx tunnel error: %s", e)

        try:
            id = platform + ":" + device_url
            d = get_device(id)
            if d is not None and d.device is not None:
                d.device._prepare_atx_agent()
                ret = {
                    "deviceId": id,
                    'success': True,
                    'isAtx': is_atx,
                }
                if platform == "android":
                    ret['deviceAddress'] = d.device.address.replace("http://", "ws://") # yapf: disable
                    ret['miniCapUrl'] = "ws://" + self.request.host + "/ws/v1/minicap?deviceId=" + id
                    ret['miniTouchUrl'] = "ws://" + self.request.host + "/ws/v1/minitouch?deviceId=" + id
                self.write(ret)
            else:
                self.write({"success": False, "description": "ADB connect failure"})
        except RuntimeError as e:
            self.set_status(500)
            self.write({
                "success": False,
                "description": str(e),
            })
        except Exception as e:
            logger.warning("device connect error: %s", e)
            self.set_status(500)
            self.write({
                "success": False,
                "description": traceback.format_exc(),
            })

class DeviceHierarchyHandler(BaseHandler):
    async def get(self, device_id):
        d = get_device(device_id)
        ret = await run_in_executor(d.dump_hierarchy)
        self.write(ret)


class DeviceHierarchyHandlerV2(BaseHandler):
    async def get(self, device_id):
        d = get_device(device_id)
        ret = await run_in_executor(d.dump_hierarchy2)
        self.write(ret)


class WidgetPreviewHandler(BaseHandler):
    def get(self, id):
        self.render("widget_preview.html", id=id)


class DeviceWidgetListHandler(BaseHandler):
    __store_dir = os.path.expanduser("~/.weditor/widgets")

    def generate_id(self):
        os.makedirs(self.__store_dir, exist_ok=True)
        names = [
            name for name in os.listdir(self.__store_dir)
            if os.path.isdir(os.path.join(self.__store_dir, name))
        ]
        return "%05d" % (len(names) + 1)

    def get(self, widget_id: str):
        data_dir = os.path.join(self.__store_dir, widget_id)
        with open(pathjoin(data_dir, "hierarchy.xml"), "r",
                  encoding="utf-8") as f:
            hierarchy = f.read()

        with open(os.path.join(data_dir, "meta.json"), "rb") as f:
            meta_info = json.load(f)
            meta_info['hierarchy'] = hierarchy
            self.write(meta_info)

    def json_parse(self, source):
        with open(source, "r", encoding="utf-8") as f:
            return json.load(f)

    def put(self, widget_id: str):
        """ update widget data """
        data = json_decode(self.request.body)
        target_dir = os.path.join(self.__store_dir, widget_id)
        with open(pathjoin(target_dir, "hierarchy.xml"), "w",
                  encoding="utf-8") as f:
            f.write(data['hierarchy'])

        # update meta
        meta_path = pathjoin(target_dir, "meta.json")
        meta = self.json_parse(meta_path)
        meta["xpath"] = data['xpath']
        with open(meta_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(meta, indent=4, ensure_ascii=False))

        self.write({
            "success": True,
            "description": f"widget {widget_id} updated",
        })

    def post(self):
        data = json_decode(self.request.body)
        widget_id = self.generate_id()
        target_dir = os.path.join(self.__store_dir, widget_id)
        os.makedirs(target_dir, exist_ok=True)

        image_fd = io.BytesIO(base64.b64decode(data['screenshot']))
        im = Image.open(image_fd)
        im.save(pathjoin(target_dir, "screenshot.jpg"))

        lx, ly, rx, ry = bounds = data['bounds']
        im.crop(bounds).save(pathjoin(target_dir, "template.jpg"))

        cx, cy = (lx + rx) // 2, (ly + ry) // 2
        # TODO(ssx): missing offset
        # pprint(data)
        widget_data = {
            "resource_id": data["resourceId"],
            "text": data['text'],
            "description": data["description"],
            "target_size": [rx - lx, ry - ly],
            "package": data["package"],
            "activity": data["activity"],
            "class_name": data['className'],
            "rect": dict(x=lx, y=ly, width=rx-lx, height=ry-ly),
            "window_size": data['windowSize'],
            "xpath": data['xpath'],
            "target_image": {
                "size": [rx - lx, ry - ly],
                "url": f"http://localhost:17310/widgets/{widget_id}/template.jpg",
            },
            "device_image": {
                "size": im.size,
                "url": f"http://localhost:17310/widgets/{widget_id}/screenshot.jpg",
            },
            # "hierarchy": data['hierarchy'],
        } # yapf: disable

        with open(pathjoin(target_dir, "meta.json"), "w",
                  encoding="utf-8") as f:
            json.dump(widget_data, f, ensure_ascii=False, indent=4)

        with open(pathjoin(target_dir, "hierarchy.xml"), "w",
                  encoding="utf-8") as f:
            f.write(data['hierarchy'])

        self.write({
            "success": True,
            "id": widget_id,
            "note": data['text'] or data['description'],  # 备注
            "data": widget_data,
        })

def screenshot():
    while True:
        req = shotQueue.get()
        if req is None:
            break
        logger.warn("screenshot begin")
        try:
            d = get_device("android:")
            buffer = io.BytesIO()
            d.screenshot().convert("RGB").save(buffer, format='JPEG')
            b64data = base64.b64encode(buffer.getvalue())
            code = 200
            msg = "OK"
            data = {
                "type": "jpeg",
                "encoding": "base64",
                "data": b64data.decode('utf-8'),
            }
        except EnvironmentError as e:
            code = 500
            msg = "Environment Error"
            data = {"description": str(e)}
        except RuntimeError as e:
            code = 500
            msg = "Gone"
            data = {"description": traceback.format_exc()}
        logger.warn("screenshot end")
        
        while True:
            req.loop.call_soon_threadsafe(req.set_status_and_write, code, msg, data)
            try:
                req = shotQueue.get_nowait()
            except:
                break

shotThread = threading.Thread(target=screenshot, name='Screenshot')
shotQueue = queue.Queue(maxsize=10)

class DeviceScreenshotHandler(BaseHandler):
    loop: IOLoop = None
    future: Future = None
    async def get(self, serial):
        self.future = Future()
        self.loop = self.future.get_loop()
        shotQueue.put(self)
        await self.future

    def set_status_and_write(self, code, msg, data):
        self.set_status(code, msg)
        self.write(data)
        self.future.set_result(None)

class DeviceScreenrecordHandler(BaseHandler):
    root = None
    def initialize(self, path: str) -> None:
        self.root = path
    def get(self, serial, action):
        d = get_device(serial)
        if action == "start":
            self.write(d.start_screenrecord(self.root))
        elif action == "stop":
            self.write(d.stop_screenrecord(self.root))
        elif action == "status":
            self.write({"status": True, "message": "OK", "result": d.isScreenRecord})
        else:
            self.set_status(404)
            self.write("action " + action + " invalid")

class FloatWindowHandler(BaseHandler):
    def get(self, serial, action):
        d = get_device(serial)
        if action == "show":
            d.device.show_float_window(True)
            self.finish()
        elif action == "hide":
            d.device.show_float_window(False)
            self.finish()
        else:
            self.set_status(404)
            self.write("action " + action + " invalid")

class DeviceSizeHandler(BaseHandler):
    async def post(self):
        serial = self.get_argument("serial")
        d = get_device(serial)
        ret = await run_in_executor(d.device.window_size)
        w, h = ret
        self.write({"width": w, "height": h})

class DeviceTouchHandler(BaseHandler):
    async def post(self):
        serial = self.get_argument("serial")
        action = self.get_argument("action")
        x = int(self.get_argument("x"))
        y = int(self.get_argument("y"))
        d = get_device(serial)
        
        def run():
            if action == 'down':
                d.device.touch.down(x, y)
            elif action == 'move':
                d.device.touch.move(x, y)
            elif action == 'up':
                d.device.touch.up(x, y)
            else:
                d.device.click(x, y)
        
        await run_in_executor(run)
        self.write({"success": True})

reNum = re.compile('^\d+$')

class DevicePingHandler(BaseHandler):
    async def post(self):
        serial = self.get_argument("serial")
        d = get_device(serial)
        
        if d.device.retries_reset is None:
            d.device.retries_reset = 5

        ret = await run_in_executor(d.device.ping)
        self.write({"ret": ret})

class DevicePressHandler(BaseHandler):
    async def post(self):
        serial = self.get_argument("serial")
        key = self.get_argument("key")
        if reNum.match(key):
            key = int(key)
        logger.info("PRESS KEY = " + json.dumps(key))
        d = get_device(serial)
        
        ret = await run_in_executor(d.device.press, key)
        self.write({"ret": ret})

class DeviceTextHandler(BaseHandler):
    async def post(self):
        serial = self.get_argument("serial")
        text = self.get_argument("text")
        logger.info("TEXT = " + json.dumps(text))
        d = get_device(serial)
        
        def run():
            return d.device.shell(['input', 'text', text])[1] == 0
        
        ret = await run_in_executor(run)
        self.write({"ret": ret})

def formatsize(size: int):
    if size < 1024:
        return str(size)
    
    i = math.floor(math.log(size, 1024))
    unit = "BKMGT"
    return "{:.3f}".format(size / math.pow(1024, i)) + unit[i]

def filetime(item):
    return item["time"]

class ListHandler(BaseHandler):
    root = None
    def initialize(self, path: str) -> None:
        self.root = path
    async def get(self):
        dir = self.get_argument("dir", default="", strip=False)
        root = self.root
        if len(dir) > 0:
            root = os.path.join(self.root, dir)

        def run():
            files = []
            for name in os.listdir(root):
                file = os.path.join(root, name)
                st = os.stat(file)
                t = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))
                isdir = os.path.isdir(file)
                zip = file + '.zip'
                files.append({"name": name, "size": st.st_size, "fsize": formatsize(st.st_size), "time": t, "mtime": st.st_mtime, "isdir": isdir, "zip": isdir and (not os.path.exists(zip) or os.stat(zip).st_mtime < st.st_mtime)})
            files.sort(key=filetime, reverse=True)
            return files
        
        if int(self.get_argument("zip", default="0", strip=False)) == 0:
            files = await run_in_executor(run)
            self.render("list.html", files=files, dir=dir)
        else:
            zfile = root + '.zip'
            if os.path.exists(zfile):
                os.remove(zfile)
            
            def compress():
                with zipfile.ZipFile(zfile, 'w', zipfile.ZIP_DEFLATED) as zip:
                    for path, dirs, files in os.walk(root):
                        fpath = path.replace(root, '')
                        for file in files:
                            fname = os.path.join(path, file)
                            farc = os.path.join(fpath, file)
                            print(fname, farc)
                            zip.write(fname, farc)
            
            await run_in_executor(compress)
            self.redirect(dir + '.zip')
