import pyaudio
import time

RATE = 44100
CHANNELS = 2
SECONDS = 0.05
CHUNK_LENGTH = int(RATE * SECONDS)
FORMAT = pyaudio.paInt16

audio = pyaudio.PyAudio()

player = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE, output=True)
player.start_stream()

def callback(in_data, frame_count, time_info = None, status = None):
    player.write(in_data, frame_count)
    return b"", pyaudio.paContinue

capture = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK_LENGTH, stream_callback=callback)
capture.start_stream()

while True:
    try:
        time.sleep(1)
    except KeyboardInterrupt:
        break

capture.stop_stream()
player.stop_stream()
audio.close()
