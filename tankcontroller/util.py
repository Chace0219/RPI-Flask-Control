import os
import sys
import time
import datetime

import csv
import xml.etree.ElementTree
import random, string

### function to generate random string for Mqtt clientid
def randomword(length):
   return ''.join(random.choice(string.ascii_uppercase + string.digits) for i in range(length))

def randomint(length):
   return ''.join(random.choice(string.digits) for i in range(length))

millis = lambda: int(round(time.time() * 1000))
seconds = lambda: int(round(time.time()))

def str_to_bool(s):
    if s == 'true':
         return True
    elif s == 'false':
         return False
    else:
         raise ValueError # evil ValueError that doesn't tell you what the wrong value was


class FBDTON():

    def __init__(self, presettime=3000):
        self.input = False
        self.prev = False
        self.output = False
        self.elapsed = 0
        self.preset = presettime

    def proc(self):
        if(self.input != self.prev):
            self.prev = self.input
            if(self.input == True):
                self.elapsed = millis()

        if(self.input == True):
            if((self.elapsed + self.preset) <= millis()):
                self.output = True
        else:
            self.elapsed = millis()
            self.output = False

class FBDTP():
    def __init__(self, presettime=3000):
        self.input = False
        self.prev = False
        self.output = False
        self.elapsed = 0
        self.preset = presettime

    def reset(self):
        self.input = False
        self.prev = False
        self.output = False
        self.elapsed = millis()

    def proc(self):
        if(self.input != self.prev):
            self.prev = self.input
            if(self.input == True):
                self.elapsed = self.preset + millis()

        if(self.elapsed > millis()):
            self.output = True
        else:
            self.elapsed = millis()
            self.output = False

    def getReserveTime(self):
        if((self.elapsed - millis()) > 0):
            return int((self.elapsed - millis()) / 1000)
        else:
            return 0

class FBDRTRG():
    def __init__(self):
        self.input = False
        self.output = False
        self.prev = False

    def proc(self):
        self.output = False
        if(self.input != self.prev):
            self.prev = self.input
            if(self.input == True):
                self.output = True
        return

    def reset(self):
        self.input = False
        self.output = False
        self.prev = False

class FBDFTRG():
    def __init__(self):
        self.input = False
        self.output = False
        self.prev = False

    def proc(self):
        self.output = False
        if(self.input != self.prev):
            self.prev = self.input
            if(self.input == False):
                self.output = True
        return

    def reset(self):
        self.input = False
        self.output = False
        self.prev = False
