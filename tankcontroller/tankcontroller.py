from flask import Flask, render_template, request, jsonify, url_for, json
import os, sys

import threading
import time
from util import FBDTON, FBDRTRG, FBDTP, FBDFTRG

import wifi
from wificontrol import Connect
import commands

import Adafruit_GPIO.SPI as SPI
import Adafruit_MAX31855.MAX31855 as MAX31855
import RPi.GPIO as GPIO

SETTINGJSON = 'setting.json'
app = Flask(__name__)

def farenheight2celcius(farenheight):
    return (farenheight - 32) * (5.0 / 9.0)

def celcius2farenheight(celcius):
    return (9.0/5.0 * celcius + 32)

deltaTemp = 1.0
### setting values
deviceSetting = {
    'setTemperature' : 40.58,
    'farenheight' : False,
    'heaterAuto' : True,
    'buzzerTimer' : 20,
    'ssid' : 'defaultssid',
    'psk' : 'defaultpsk'
    }

### status values
deviceStatus = {
    'currTemp' : 100,
    'buzzer' : False,
    'pumpStatus' : False,
    'heaterStatus' : False,
    'reserveTime': 100,
    'downCount': False,
}

sensorStatus = dict()

### GPIO pin definition
PUMP = 17
HEATER = 27
BUZZER = 18

PUMPSWITCH = 22
BUZEERSWITCH = 23

RELAYON = GPIO.LOW
RELAYOFF = GPIO.HIGH

### GPIO init
GPIO.setmode(GPIO.BCM) # Broadcom pin-numbering scheme
GPIO.setwarnings(False)
GPIO.setup(PUMP, GPIO.OUT)
GPIO.output(PUMP, RELAYOFF)

GPIO.setup(HEATER, GPIO.OUT)
GPIO.output(HEATER, RELAYOFF)

GPIO.setup(BUZZER, GPIO.OUT)
GPIO.output(BUZZER, RELAYOFF)

GPIO.setup(PUMPSWITCH, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(BUZEERSWITCH, GPIO.IN, pull_up_down=GPIO.PUD_UP)

def loadSetting():
    SITE_ROOT = os.path.realpath(os.path.dirname(__file__))
    json_url = os.path.join(SITE_ROOT, 'static/data', 'setting.json')

    # check file exits
    if(not os.path.isfile(json_url)):
        print('there is no setting file, program will load default setting')
        # default setting
        global deviceSetting
        print(json.dumps(deviceSetting))
        saveSetting()
    else:
        deviceSetting = json.load(open(json_url))
        # print setting data
        print('Temperature Setting is ' + str(deviceSetting['setTemperature']) + ' celcius')
        print('Temperature unit is ' + (deviceSetting['farenheight'] and 'Farenheight' or 'Celcius'))
        print((deviceSetting['heaterAuto'] and 'Automatic' or 'Manual') + ' heater control')
        print('Buzzer interval time ' + str(deviceSetting['buzzerTimer']) + 'secs')
        print('ssid is ' + deviceSetting['ssid'])
        print('psk is ' + deviceSetting['psk'])

def saveSetting():
    SITE_ROOT = os.path.realpath(os.path.dirname(__file__))
    json_url = os.path.join(SITE_ROOT, 'static/data', 'setting.json')
    with open(json_url, 'w') as f:
        json.dump(deviceSetting, f)

class Controller(threading.Thread):

    BUZZERHOLDINGTIME = 5000

    def __init__(self, ):
        threading.Thread.__init__(self)

        ### FBD variables

        self.ringTP = FBDTP(5000)

        self.buzzerTP = FBDTP(Controller.BUZZERHOLDINGTIME)
        self.buzeerOffTrg = FBDFTRG()

        self.buzzerOnCommand = False
        self.buzzerOffCommand = False

        self.heaterHigherTON = FBDTON(2000)
        self.heaterHigherTrg = FBDRTRG()

        self.heaterLowerTON = FBDTON(2000)
        self.heaterLowerTrg = FBDRTRG()

        self.pumpSwitchTON = FBDTON(400)
        self.pumpSwitchTrg = FBDRTRG()

        self.buzzerSwitchTON = FBDTON(400)
        self.buzzerSwitchTrg = FBDRTRG()

        # Threading Event instance
        self.event = threading.Event()
        self.start()
        print('thread is started')


    def buzzerForceOn(self):
        self.buzzerOnCommand = True

    def buzzerForceOff(self):
        self.buzzerOffCommand = True

    def run(self):
        try:
            while not self.event.isSet():

                ### get temperature from sensor
                global sensorStatus
                sensorStatus = sensor.readState()
                deviceStatus['currTemp'] = sensor.readTempC()
                internal = sensor.readInternalC()

                self.pumpSwitchTON.input = not GPIO.input(PUMPSWITCH)
                self.pumpSwitchTON.proc()
                self.pumpSwitchTrg.input = self.pumpSwitchTON.output
                self.pumpSwitchTrg.proc()
                if(self.pumpSwitchTrg.output):
                    print('pump switch is detected')
                    deviceStatus['pumpStatus'] = not deviceStatus['pumpStatus']

                ### buzzer control logic
                self.buzzerSwitchTON.input = not GPIO.input(BUZEERSWITCH)
                self.buzzerSwitchTON.proc()
                self.buzzerSwitchTrg.input = self.buzzerSwitchTON.output
                self.buzzerSwitchTrg.proc()

                if(self.buzzerSwitchTrg.output or self.buzzerOnCommand):
                    print('buzzer switch is detected')
                    if(not deviceStatus['downCount']):
                        self.buzzerTP.preset = deviceSetting['buzzerTimer'] * 1000
                        self.buzzerTP.input = True
                    else:
                        self.buzzerTP.reset()
                        self.ringTP.reset()
                        self.buzeerOffTrg.reset()

                self.buzzerOnCommand = False
                self.buzzerOffCommand = False

                self.buzzerTP.proc()
                self.buzzerTP.input = False

                self.buzeerOffTrg.input = self.buzzerTP.output
                self.buzeerOffTrg.proc()
                self.ringTP.input = self.buzeerOffTrg.output
                self.ringTP.proc()

                deviceStatus['buzzer'] = self.ringTP.output
                if (self.buzzerTP.output == True or deviceStatus['buzzer'] == True):
                    deviceStatus['downCount'] = True
                else:
                    deviceStatus['downCount'] = False

                if(deviceStatus['downCount'] == True):
                    deviceStatus['reserveTime'] = self.buzzerTP.getReserveTime()
                    print(deviceStatus['reserveTime'])
                else:
                    deviceStatus['reserveTime'] = deviceSetting['buzzerTimer']

                self.buzzerOnCommand = False
                self.buzzerOffCommand = False

                ### Heater Automatic Control
                self.heaterHigherTON.input = (deviceStatus['currTemp'] > (deviceSetting['setTemperature'] + deltaTemp))
                self.heaterHigherTON.proc()

                self.heaterLowerTON.input = (deviceStatus['currTemp'] < (deviceSetting['setTemperature'] - deltaTemp))
                self.heaterLowerTON.proc()

                if(self.heaterHigherTON.output and deviceSetting['heaterAuto']):
                    deviceStatus['heaterStatus'] = False

                if(self.heaterLowerTON.output and deviceSetting['heaterAuto']):
                    deviceStatus['heaterStatus'] = True

                if((sensorStatus['openCircuit'] or sensorStatus['shortGND']) or (sensorStatus['shortVCC'] or sensorStatus['fault'])):
                    deviceStatus['heaterStatus'] = False

                ### Real GPIO control
                if(deviceStatus['heaterStatus']):
                    GPIO.output(HEATER, RELAYON)
                else:
                    GPIO.output(HEATER, RELAYOFF)

                if(deviceStatus['buzzer']):
                    GPIO.output(BUZZER, RELAYON)
                else:
                    GPIO.output(BUZZER, RELAYOFF)

                if(deviceStatus['pumpStatus']):
                    GPIO.output(PUMP, RELAYON)
                else:
                    GPIO.output(PUMP, RELAYOFF)

                time.sleep(0.2)
        except:
            print('station proc error')
            pass

@app.route('/togglebuzzer')
def togglebuzzer():
    result = dict()
    controller.buzzerForceOn()
    result['command'] = 'ON'
    '''
    if(deviceStatus['buzzer']):
        controller.buzzerForceOff()
        result['command'] = 'OFF'
    else:
        controller.buzzerForceOn()
        result['command'] = 'ON'
    '''

    return jsonify(result=result)


@app.route('/getstatus')
def currstatus():

    result = dict()

    ###
    result['farenheight'] = deviceSetting['farenheight']

    if(deviceSetting['farenheight']):
        result['currTemp'] = celcius2farenheight(deviceStatus['currTemp'])
        result['setTemperature'] = celcius2farenheight(deviceSetting['setTemperature'])
    else:
        result['currTemp'] = deviceStatus['currTemp']
        result['setTemperature'] = deviceSetting['setTemperature']

    if ((sensorStatus['openCircuit'] or sensorStatus['shortGND']) or (
        sensorStatus['shortVCC'] or sensorStatus['fault'])):
        result['currTemp'] = 'thermo error'

    ###
    result['buzzer'] = deviceStatus['buzzer']
    result['buzzerTimer'] = deviceStatus['reserveTime']

    ###
    result['pumpStatus'] = deviceStatus['pumpStatus']

    ###
    result['heaterStatus'] = deviceStatus['heaterStatus']
    result['heaterAuto'] = deviceSetting['heaterAuto']

    return jsonify(result)

@app.route('/turnpump')
def turnPump():
    result = dict()
    deviceStatus['pumpStatus'] = not deviceStatus['pumpStatus']
    result['pump'] = (deviceStatus['pumpStatus'] == True and 'On' or 'Off')
    return jsonify(result=result)

@app.route('/heater/<number>')
def heaterControl(number):
    result = dict()
    try:
        heaterNumber = int(number)
        if(heaterNumber == 1):
            if(deviceSetting['heaterAuto'] == True):
                print('Heater is in automatic control mode, you can only control heater in only manual mode!')
                result['fail'] = 'invalid control mode'
            else:
                deviceStatus['heaterStatus'] = not deviceStatus['heaterStatus']
                result['heaterStatus'] = deviceStatus['heaterStatus']
        else:
            print('Invalid argument!')
            result['fail'] = 'invalid argument'
    except:
        print('Invalid argument!')
        result['fail'] = 'invalid argument'

    return jsonify(result)

@app.route('/controlmode')
def toggleControlMode():

    print('control mode is executed')

    result = dict()
    deviceSetting['heaterAuto'] = not deviceSetting['heaterAuto']
    result['heatercontrol'] = (deviceSetting['heaterAuto'] == True and 'automatic control' or 'manual control')
    saveSetting()
    return jsonify(result)

@app.route('/switchtempunit')
def switchTempUnit():
    deviceSetting['farenheight'] = not deviceSetting['farenheight']
    result = dict()
    result['farenheight'] = deviceSetting['farenheight']
    saveSetting()
    return jsonify(result=result)

@app.route('/settemperature')
def setTemperature():
    arg = request.args.get('setTemperature')
    result = dict()
    # convert to double
    try:
        if(not deviceStatus['downCount']):
            newTemp = float(arg)
            if(deviceSetting['farenheight']):
                deviceSetting['setTemperature'] = farenheight2celcius(newTemp)
            else:
                deviceSetting['setTemperature'] = newTemp
            result['setTemperature'] = deviceSetting['setTemperature']
            saveSetting()
    except:
        print('Invalid argument')
        result['fail'] = 'Invalid argument'
    return jsonify(result=result)

@app.route('/buzzerTimer')
def buzzerTimer():
    arg = request.args.get('buzzerTimer')
    result = dict()
    # convert to double
    try:
        deviceSetting['buzzerTimer'] = int(arg)
        result['buzzerTimer'] = deviceSetting['buzzerTimer']
        saveSetting()
    except:
        print('Invalid argument')
        result['fail'] = 'Invalid argument'
    return jsonify(result=result)

###
@app.route('/')
def index():
    return render_template('control.html')

@app.route('/setting')
def setting():
    return render_template('setting.html')


@app.route('/getnetworkaddr')
def geteth0addr():
    result = dict()
    result['eth0'] = commands.getoutput('ifconfig eth0 |grep "inet\ addr" |cut -d: -f2 |cut -d" " -f1')
    result['wlan0'] = commands.getoutput('ifconfig wlan0 |grep "inet\ addr" |cut -d: -f2 |cut -d" " -f1')
    return jsonify(result)

@app.route('/wificonnect')
def wificonnect():
    result = dict()

    ssid = request.args.get('ssid')
    psk = request.args.get('psk')

    # turn off wifi
    command = "sudo ifdown 'wlan0'"
    os.system(command)
    time.sleep(2)
    # turn on Wifi
    command = "sudo ifup --force 'wlan0'"
    os.system(command)

    try:
        if(psk == None):
            print('none psk')
            if(not Connect(ssid)):
                result['fail'] = 'none configured'
            else:
                deviceSetting['ssid'] = ssid
                deviceSetting['psk'] = psk
                saveSetting()
                result['wlan0'] = commands.getoutput('ifconfig wlan0 |grep "inet\ addr" |cut -d: -f2 |cut -d" " -f1')
        else:
            print('full psk')
            if(not Connect(ssid, psk)):
                result['fail'] = 'none configured'
            else:
                deviceSetting['ssid'] = ssid
                deviceSetting['psk'] = psk
                saveSetting()
                result['wlan0'] = commands.getoutput('ifconfig wlan0 |grep "inet\ addr" |cut -d: -f2 |cut -d" " -f1')
    except:
        result['fail'] = 'none configured'
    return jsonify(result)

@app.route('/getaplist')
def getAPList():

    APlist = []
    cells = wifi.Cell.all('wlan0')
    for cell in cells:
        APlist.append(cell.ssid)
    print(APlist)
    return jsonify(aplist=APlist)

if __name__ == '__main__':
    try:

        SPI_PORT   = 0
        SPI_DEVICE = 0
        sensor = MAX31855.MAX31855(spi=SPI.SpiDev(SPI_PORT, SPI_DEVICE))

        controller = Controller()
        loadSetting()
        app.run(host='0.0.0.0', port=80, debug=False, threaded=True)

    except KeyboardInterrupt: # If CTRL+C is pressed, exit cleanly:
        pass
    finally:
        controller.event.set()
        time.sleep(2)
