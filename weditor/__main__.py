#! /usr/bin/env python
# -*- encoding: utf-8 -*-

from __future__ import absolute_import, print_function

import argparse
import os
import signal
import subprocess
import sys
import time
import webbrowser

import requests
import tornado.escape
import tornado.ioloop
import tornado.web
import tornado.websocket
from logzero import logger
from tornado.log import enable_pretty_logging
from .web.device import stop_device

from .web.handlers.mini import MiniCapHandler, MiniTouchHandler, MiniSoundHandler, sound, MiniPlayerHandler, player, sysInfoThread, stop_sys_info, CameraHandler, camera_stop

from .web.handlers.page import (
    BaseHandler, DeviceConnectHandler, SysInfoHandler,
    DeviceHierarchyHandler, DeviceHierarchyHandlerV2, DeviceScreenshotHandler, shotThread, shotQueue,
    DeviceWidgetListHandler, setChannels, MainHandler, VersionHandler, WidgetPreviewHandler,
    DeviceSizeHandler, DeviceTouchHandler, DevicePingHandler, DevicePressHandler, DeviceTextHandler, ListHandler, DeviceScreenrecordHandler, FloatWindowHandler)
from .web.handlers.proxy import StaticProxyHandler
from .web.handlers.shell import PythonShellHandler
from .web.utils import current_ip, tostr
from .web.version import __version__

enable_pretty_logging()

__dir__ = os.path.dirname(os.path.abspath(__file__))

is_closing = False

if os.name == "nt":
    os.environ["HOME"] = os.path.expanduser("~")
PID_FILEPATH = os.path.expandvars("$HOME/.weditor/weditor.pid")
os.makedirs(os.path.dirname(PID_FILEPATH), exist_ok=True)


def signal_handler(signum, frame):
    global is_closing
    print('exiting...')
    is_closing = True


def stop_server():
    tornado.ioloop.IOLoop.instance().stop()


def try_exit():
    global is_closing
    if is_closing:  # clean up here
        stop_server()
        logger.info('exit success')


class QuitHandler(BaseHandler):
    def get(self):
        stop_server()
        self.write({"success": True, "description": "Successfully quited"})


class CropHandler(BaseHandler):
    def get(self):
        """ used for crop image """
        pass

if os.name == "nt":
    uploadPath = "D:\\code\\uploads"
else:
    uploadPath = os.path.expandvars("$HOME/uploads")

if not os.path.isdir(uploadPath):
    os.makedirs(uploadPath)

def make_app(settings={}):
    application = tornado.web.Application(
        [
            (r"/", MainHandler),
            (r"/downloads/", ListHandler, {"path": uploadPath}),
            (r"/downloads/(.+)", tornado.web.StaticFileHandler, {"path": uploadPath}),
            (r"/api/v1/version", VersionHandler),
            (r"/api/v1/connect", DeviceConnectHandler),
            (r"/api/v1/size", DeviceSizeHandler),
            (r"/api/v1/touch", DeviceTouchHandler),
            (r"/api/v1/ping", DevicePingHandler),
            (r"/api/v1/press", DevicePressHandler),
            (r"/api/v1/text", DeviceTextHandler),
            (r"/api/v1/crop", CropHandler),
            (r"/api/v1/sysInfo", SysInfoHandler),
            (r"/api/v1/devices/([^/]+)/screenshot", DeviceScreenshotHandler),
            (r"/api/v1/devices/([^/]+)/screenrecord/([^/]+)", DeviceScreenrecordHandler, {"path": uploadPath}),
            (r"/api/v1/devices/([^/]+)/floatwindow/([^/]+)", FloatWindowHandler),
            (r"/api/v1/devices/([^/]+)/hierarchy", DeviceHierarchyHandler),
            # (r"/api/v1/devices/([^/]+)/exec", DeviceCodeDebugHandler),
            (r"/api/v1/devices/([^/]+)/widget", DeviceWidgetListHandler),
            (r"/api/v1/widgets", DeviceWidgetListHandler),  # add widget
            (r"/api/v1/widgets/([^/]+)", DeviceWidgetListHandler),
            # v2
            (r"/api/v2/devices/([^/]+)/hierarchy", DeviceHierarchyHandlerV2),
            # widgets
            (r"/widgets/([^/]+)", WidgetPreviewHandler),
            (r"/widgets/(.+/.+)", tornado.web.StaticFileHandler, {
                "path": "./widgets"
            }),
            # cache static assets
            (r"/(unpkg.com/.*)", StaticProxyHandler),
            (r"/(cdn.jsdelivr.net/.*)", StaticProxyHandler),
            # (r"/ws/v1/build", BuildWSHandler),
            (r"/ws/v1/python", PythonShellHandler),
            (r"/ws/v1/camera", CameraHandler),
            (r"/ws/v1/minicap", MiniCapHandler),
            (r"/ws/v1/minitouch", MiniTouchHandler),
            (r"/ws/v1/minisound", MiniSoundHandler),
            (r"/ws/v1/miniplayer", MiniPlayerHandler),
            (r"/quit", QuitHandler),
        ],
        **settings)
    return application


def get_running_version(addr: str):
    """
    Returns:
        None if not running
        version string if running
    """
    try:
        r = requests.get(f"{addr}/api/v1/version",
                         timeout=2.0)
        if r.status_code == 200:
            return r.json().get("version", "dev")
    except requests.exceptions.ConnectionError:
        pass
    except Exception as e:
        print("Unknown error: %r" % e)


def cmd_quit(port=17310):
    try:
        requests.get(f"http://127.0.0.1:{port}/quit", timeout=3)
        logger.info("weditor quit successfully")
    except requests.ConnectionError:
        logger.info("weditor already stopped")
    except requests.Timeout:
        logger.info("kill through pid file")
        if not os.path.isfile(PID_FILEPATH):
            logger.warning("Pidfile: %s not exist", PID_FILEPATH)
            return
        
        with open(PID_FILEPATH, "r") as f:
            pid = int(f.read())
            if os.name == "nt": # windows
                subprocess.call(f"taskkill /PID {pid} /T /F") # /F: 强制 /T: 包含子进程
            else:
                os.kill(pid, signal.SIGKILL)
        os.unlink(PID_FILEPATH)
        logger.info("weditor was killed")


def run_web(debug=False, port=17310, open_browser=False, force_quit=False):
    base_url = f"http://127.0.0.1:{port}"
    version = get_running_version(base_url)
    if version:
        if force_quit:
            logger.info(f"quit previous weditor server (version: {version})")
            requests.get(base_url + "/quit")
            time.sleep(.5)
        else:
            sys.exit(f"Another weditor({version}) is already running")

    if open_browser:
        webbrowser.open(f'http://127.0.0.1:{port}', new=2)

    application = make_app({
        'static_path': os.path.join(__dir__, 'static'),
        'template_path': os.path.join(__dir__, 'templates'),
        'debug': debug,
    })
    print('listening on http://%s:%d' % (current_ip(), port))
    if debug:
        logger.info("enable debug mode")
    signal.signal(signal.SIGINT, signal_handler)
    application.listen(port, '0.0.0.0')

    with open(PID_FILEPATH, "w") as f:
        f.write(str(os.getpid()))

    player.init()

    tornado.ioloop.PeriodicCallback(try_exit, 100).start()
    tornado.ioloop.IOLoop.instance().start()
    # tornado.ioloop.IOLoop.instance().add_callback(consume_queue)

    stop_sys_info()
    sound.close()
    player.close()
    camera_stop()
    stop_device(uploadPath)
    shotQueue.put(None)
    shotThread.join(5)
    sysInfoThread.join(5)
    
    if sys.platform == 'linux':
        os.system("daemon --stop --name logcat")
        os.system("daemon --stop --name dmesg")
    
    if os.path.exists(PID_FILEPATH):
        os.unlink(PID_FILEPATH)

    sys.exit("Exited")

def create_shortcut():
    if os.name != 'nt':
        sys.exit("Shortcut only available in Windows")

    import pythoncom  # pyint: disable=import-error
    from win32com.shell import shell
    from win32com.shell import shellcon
    # Refs
    # - https://github.com/pearu/iocbio/blob/master/installer/utils.py
    # - https://blog.csdn.net/thundor/article/details/5968581
    ilist = shell.SHGetSpecialFolderLocation(0, shellcon.CSIDL_DESKTOP)
    dtpath = shell.SHGetPathFromIDList(ilist).decode('utf-8')

    shortcut = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None,
                                          pythoncom.CLSCTX_INPROC_SERVER,
                                          shell.IID_IShellLink)
    launch_path = sys.executable
    shortcut.SetPath(launch_path)
    shortcut.SetArguments("-m weditor")
    shortcut.SetDescription(launch_path)
    shortcut.SetIconLocation(sys.executable, 0)
    shortcut.QueryInterface(pythoncom.IID_IPersistFile).Save(
        dtpath + "\\WEditor.lnk", 0)
    print("Shortcut created. " + dtpath + "\\WEditor.lnk")


def main():
    # yapf: disable
    ap = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument("-d", "--device", type=int, default=None, help="sound input device index")
    ap.add_argument("-P", "--play", type=int, default=None, help="sound output device index")
    ap.add_argument("-c", "--channels", type=int, default=None, help="capture sound channel number")
    ap.add_argument("-v", "--version", action="store_true", help="show version")
    ap.add_argument('-q', '--quiet', action='store_true', help='quite mode, no open new browser')
    ap.add_argument('-p', '--port', type=int, default=17310, help='local listen port for weditor')
    ap.add_argument("-f", "--force-quit", action='store_true', help="force quit before start")
    ap.add_argument('--debug', action='store_true', help='open debug mode')
    ap.add_argument('--shortcut', action='store_true', help='create shortcut in desktop')
    ap.add_argument("--quit", action="store_true", help="stop weditor")
    args = ap.parse_args()
    # yapf: enable

    if args.version:
        print(__version__)
        return

    if args.shortcut:
        create_shortcut()
        return
    
    if args.quit:
        cmd_quit(args.port)
        return

    if sys.platform == 'win32' and sys.version_info[:2] >= (3, 8):
        import asyncio
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    if args.channels is None:
        args.channels = sound.getChannels(args.device)
        if args.channels == 0 or args.channels > 2:
            args.channels = 2
    elif args.channels > 2:
        args.channels = 2

    setChannels(args.channels)
    sound.open(input_device_index=args.device, channels=args.channels)
    if args.play is None:
        player.deviceIndex = args.device
    else:
        player.deviceIndex = args.play
    shotThread.start()
    sysInfoThread.start()

    open_browser = not args.quiet and not args.debug
    run_web(args.debug, args.port, open_browser, args.force_quit)

if __name__ == '__main__':
    main()
