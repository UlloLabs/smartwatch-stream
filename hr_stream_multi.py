# -*- coding: utf-8 -*-

# Note: code based on stream_breathing_amp_multi
import asyncio, argparse, struct, signal, timeit, struct, sys
from bleak import BleakClient
from pylsl import StreamInfo, StreamOutlet

# long UUID for standard HR characteristic
CHARACTERISTIC_UUID_HR = "00002a37-0000-1000-8000-00805f9b34fb"

# Notice that we might push several IBI at once to LSL output, and effective IBI sampling rate might vary a lot.

# how often we expect to get new data from device (Hz)
DEFAULT_SAMPLINGRATE_HR = 1
DEFAULT_SAMPLINGRATE_IBI = 1

# data format changed between version
if (sys.version_info > (3, 0)):
    PYTHON_VERSION = 3
else:
    PYTHON_VERSION = 2

class HRMBleak():
    """
    Experimeting with bleak and asyncio. 
    FIXME: better usage of asyncio...
    """
    def __init__(self, addr, verbose=False, callback=None, loop_interval=5):
        """
        addr: MAC adresse
        char_id: GATT characteristic ID
        verbose: debug info to stdout
        callback: function that will be called upon new samples, with a a list of samples in parameters. First value will be HR, others, if any, IBI
        loop_interval: how often sampling rate is shown and connectivity is checked
        """
        self.hr = 0
        # this one is a list, because we could retrieve several IBI at once
        self.ibi = []
        # hack here, because IBI values are mixed with HR /sometimes/ we need another check beside the return of waitForNotification in GattDevice to detect new ones
        self.newIBI = False
        self.addr = addr
        self.char_id = CHARACTERISTIC_UUID_HR
        self.verbose = verbose
        self.samples_in = 0
        self.callback = callback
        self.loop_interval = loop_interval
        self.client = BleakClient(self.addr)

    def launch(self):
        """
        blocking call, connect and then wait for notifications
        """
        asyncio.run(self._main())

    def _ble_handler(self, sender, data):
        """
        Handler for incoming BLE Gatt data, update values, print if verbose
        """
        if len(data) >= 2:
            self.samples_in+=1
            if PYTHON_VERSION  == 2:
                self.hr = ord(data[1])
            else:
                self.hr = data[1]
            # we might get additionnal IBI data
            self.newIBI = False
            if len(data) >= 4:
                self.newIBI = True
                self.ibi = []
                data = data[2:]
                while len(data) >= 2:
                    # UINT16 format, units of IBI interval is 1/1024 sec
                    ibi = struct.unpack('H', data[0:2])[0] / 1024.
                    self.ibi.append(ibi)
                    data = data[2:]
            if self.verbose :
                print ("BPM: " + str(self.hr) + "/ IBI: " + str(self.ibi))

            if self.callback is not None:
                values = [self.hr]
                if self.newIBI:
                    values = values + self.ibi
                self.callback(values)

    async def connect(self):
        """
        Establish connection with the device
        """
        if not self.isConnected():
            print("Connecting to %s" % self.addr)
            try:
                await self.client.connect()
                print(f"Connected: {self.client.is_connected}")
            except Exception as e:
                print(e)

    async def _main(self):
            print("launch the loop")
            while True:
                try:
                    start_time = timeit.default_timer()
                    if not self.isConnected():
                        await self.connect()
                        if self.isConnected():
                            print("start notify")
                            await self.client.start_notify(self.char_id, self._ble_handler)
                            print("notify started")
                        else:
                            print("could not connect")
                    # sleep used to debug sampling rate but also to make the script work in the background, and how often we check connectivity
                    # TODO: take into account the time taken for connection?
                    await asyncio.sleep(self.loop_interval)
                    tick = timeit.default_timer()
                    # debug info for sampling rate
                    sampling_rate_in=0
                    if start_time != tick:
                        sampling_rate_in = self.samples_in / float(tick-start_time)
                    print("Samples incoming at: %s Hz" % sampling_rate_in)
                    self.samples_in = 0
                except Exception as e:
                    print("Exception during belt loop")
                    print(e)

    async def _terminate(self):
        await self.client.stop_notify(self.char_id)
        await self.client.disconnect()

    def setCallback(self, callback):
        """
        For delayed callback init. Warning: will replace existing callback
        callback: function that will be called upon new samples, with a a list of samples in parameters. First value will be HR, others, if any, IBI
        """
        self.callback = callback
        
    def isConnected(self):
        """
        Return flag whether we are connected or not to the device
        """
        return self.client.is_connected
    
    def terminate(self):
        """
        Gracefully end BLE connection
        FIXME: we should await...
        """
        try:
            asyncio.run(self._terminate())
        except Exception as e:
            print(e)
    

if __name__ == "__main__":
    # make sure to catch SIGINT and also catch SIGTERM signals with KeyboardInterrupt, to cleanup properly later
    signal.signal(signal.SIGINT, signal.default_int_handler)
    signal.signal(signal.SIGTERM, signal.default_int_handler)

    # retrieve MAC address
    parser = argparse.ArgumentParser(description='Stream heart rate of bluetooth BLE compatible devices using LSL')
    parser.add_argument("-m", "--mac-address", help="MAC address of the  device.", default="F6:4A:06:35:E9:BA", type=str)
    parser.add_argument("-n", "--name", help="LSL id on the network", default="smartwatch", type=str)
    parser.add_argument("-s", "--streaming", help="int describing what is streamed : 0 - nothing, 1 - HR, 2 - IBI, 3 - both", default="3", type=int)
    parser.add_argument("-v", "--verbose", action='store_true', help="Print more verbose information.")
    parser.add_argument("-sr-hr", help="Expected sampling late for HR values. An integer, default: %s" % DEFAULT_SAMPLINGRATE_HR, default=DEFAULT_SAMPLINGRATE_HR, type=int)
    parser.add_argument("-sr-ibi", help="Expected sampling late for IBI values. An integer, default: %s" % DEFAULT_SAMPLINGRATE_IBI, default=DEFAULT_SAMPLINGRATE_IBI, type=int)
    args = parser.parse_args()

    parser.set_defaults()
    args = parser.parse_args()

    # init LSL streams
    streaming_hr = (args.streaming == 1 or args.streaming == 3)
    streaming_ibi = (args.streaming == 2 or args.streaming == 3)
    outlet_hr = None
    outlet_ibi = None
    if streaming_hr :
        print("Streaming HR data")
        type_hr = "heart_rate"
        info_hr = StreamInfo(args.name, type_hr, 1, args.sr_hr, 'float32', '%s_%s_%s' % (args.name, type_hr, args.mac_address))
        outlet_hr = StreamOutlet(info_hr)

    if streaming_ibi :
        print("Streaming IBI data")
        type_ibi = 'heart_ibi'
        info_ibi = StreamInfo(args.name, type_ibi, 1, args.sr_ibi, 'float32', '%s_%s_%s' % (args.name, type_ibi, args.mac_address))
        outlet_ibi = StreamOutlet(info_ibi)

    
    def stream(data):
        """
        will be called by hrm
        TODO: check parameters (number, types)
        FIXME: not well separated with hrm object
        """
        # fetch values from list
        hr_value = None
        ibi_value = []
        if len(data) > 0:
            hr_value = data[0]
        if len(data) > 1:
            ibi_values = data[1:]
        if streaming_hr and hr_value is not None:
            outlet_hr.push_sample([hr_value])
        if streaming_ibi and len(ibi_value) > 0:
            for ibi in ibi_value:
                outlet_ibi.push_sample([ibi])

    hrm = HRMBleak(args.mac_address, verbose = args.verbose, callback=stream)

    # delegate the main loop to Bbelt
    try:
        hrm.launch()
    except KeyboardInterrupt:
        print("Catching Ctrl-C or SIGTERM, bye!")
    finally:
        # disconnected and erase outlet before letting be
        hrm.terminate()
        del outlet_hr
        del outlet_ibi
        print("terminated")
