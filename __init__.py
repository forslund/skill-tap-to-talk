import pyaudio
import struct
import math
import time
from threading import Thread

from mycroft import MycroftSkill
from mycroft.messagebus.message import Message
from mycroft.util.signal import create_signal


INITIAL_TAP_THRESHOLD = 0.220
MIN_TAP_THRESHOLD = 0.220
FORMAT = pyaudio.paInt16 
SHORT_NORMALIZE = (1.0/32768.0)
CHANNELS = 2
RATE = 44100  
INPUT_BLOCK_TIME = 0.05
INPUT_FRAMES_PER_BLOCK = int(RATE*INPUT_BLOCK_TIME)
# if we get this many noisy blocks in a row, increase the threshold
OVERSENSITIVE = 15.0/INPUT_BLOCK_TIME                    
# if we get this many quiet blocks in a row, decrease the threshold
UNDERSENSITIVE = 120.0/INPUT_BLOCK_TIME 
# if the noise was longer than this many blocks, it's not a 'tap'
MAX_TAP_BLOCKS = 0.15/INPUT_BLOCK_TIME

def get_rms( block ):
    # RMS amplitude is defined as the square root of the 
    # mean over time of the square of the amplitude.
    # so we need to convert this string of bytes into 
    # a string of 16-bit samples...

    # we will get one short out for each 
    # two chars in the string.
    count = len(block)/2
    format = "%dh"%(count)
    shorts = struct.unpack( format, block )

    # iterate over the block.
    sum_squares = 0.0
    for sample in shorts:
        # sample is a signed short in +/- 32768. 
        # normalize it to 1.0
        n = sample * SHORT_NORMALIZE
        sum_squares += n*n

    return math.sqrt( sum_squares / count )

class SkillClapStop(MycroftSkill):
    def __init__(self):
        super().__init__()
        self.pa = pyaudio.PyAudio()
        self.stream = self.open_mic_stream()
        self.tap_threshold = INITIAL_TAP_THRESHOLD
        self.noisycount = MAX_TAP_BLOCKS+1 
        self.quietcount = 0 
        self.errorcount = 0

        self.last_tap = 0
        self.running = True
        self.thread = Thread(target=self.listen_thread)
        self.thread.start()

    def shutdown(self):
        self.running = False
        self.thread.join()
        self.stream.close()

    def find_input_device(self):
        device_index = None            
        for i in range( self.pa.get_device_count() ):     
            devinfo = self.pa.get_device_info_by_index(i)   
            print( "Device %d: %s"%(i,devinfo["name"]) )

            for keyword in ["mic","input"]:
                if keyword in devinfo["name"].lower():
                    print( "Found an input: device %d - %s"%(i,devinfo["name"]) )
                    device_index = i
                    return device_index

        if device_index == None:
            print( "No preferred input found; using default input device." )

        return device_index

    def open_mic_stream( self ):
        device_index = self.find_input_device()

        stream = self.pa.open(   format = FORMAT,
                                 channels = CHANNELS,
                                 rate = RATE,
                                 input = True,
                                 input_device_index = device_index,
                                 frames_per_buffer = INPUT_FRAMES_PER_BLOCK)

        return stream

    def tap_detected(self):
        now = time.monotonic()
        print('tap at {}'.format(now))
        if now - self.last_tap < 2:
            create_signal('startListening')
            self.last_tap = 0
        else:
            self.last_tap = time.monotonic()

    def listen_thread(self):
        while(self.running):
            self.listen()

    def listen(self):
        try:
            block = self.stream.read(INPUT_FRAMES_PER_BLOCK)
        except IOError as e:
            # dammit. 
            self.errorcount += 1
            print( "(%d) Error recording: %s"%(self.errorcount,e) )
            self.noisycount = 1
            return

        amplitude = get_rms( block )
        if amplitude > self.tap_threshold:
            print(amplitude)
            # noisy block
            self.quietcount = 0
            self.noisycount += 1
            if self.noisycount > OVERSENSITIVE:
                # turn down the sensitivity
                self.tap_threshold *= 1.1
            
        else:            
            # quiet block.

            if 1 <= self.noisycount <= MAX_TAP_BLOCKS:
                self.tap_detected()
            self.noisycount = 0
            self.quietcount += 1
            if self.quietcount > UNDERSENSITIVE:
                # turn up the sensitivity
                self.tap_threshold *= 0.9
                self.tap_threshold = max(self.tap_threshold, MIN_TAP_THRESHOLD)

def create_skill():
    return SkillClapStop()
