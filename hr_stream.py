from bluepy.btle import AssignedNumbers
from pylsl import StreamInfo, StreamOutlet

# pointing to local libs
import sys, os
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.realpath(__file__)), './extern/GattDevice'))
from gatt_device import GattDevice

import struct, argparse, timeit

# Notice that we might push several IBI at once to LSL output, and effective IBI sampling rate might vary a lot.

# TODO
# - check smartwatch sampling rate
# - we might get more than one IBI at times, depending on smartwatches
# - better handle both python version? check data format

# how often we expect to get new data from device (Hz)
SAMPLINGRATE_HR = 1
SAMPLINGRATE_IBI = 1

# data format changed between version
if (sys.version_info > (3, 0)):
    PYTHON_VERSION = 3
else:
    PYTHON_VERSION = 2

class HRM(GattDevice):
    def __init__(self, addr, addr_type, service_id, char_id, reconnect = False, verbose = False):
        """
        addr: MAC adresse
        addr_type: BLE adresse can be random (0) or public (1)
        service_id: GATT service ID
        char_id: GATT characteristic ID
        reconnect: will loop connection indefinitely, launching in in separate thread, upon init and in case BLE breaks. Side effect: if set init function will return immediately, before actually being connected, otherwise blocking call until a connexion attempt has been made
        verbose: debug info to stdout
        """
        super(HRM, self).__init__(addr, addr_type, service_id, char_id, handler=self.print_hr, reconnect=reconnect, verbose=verbose)    
        self.hr = 0
        # this one is a list, because we could retrieve several IBI at once
        self.ibi = [0]
        # hack here, because IBI values are mixed with HR /sometimes/ we need another check beside the return of waitForNotification in GattDevice to detect new ones
        self.newIBI = False

    def print_hr(self, cHandle, data):
        if len(data) >= 2:
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
            if args.verbose :
                print (args.name + " > BPM: " + str(self.hr) + "/ IBI: " + str(self.ibi))

if __name__=="__main__":

    # retrieve MAC address
    parser = argparse.ArgumentParser(description='Stream heart rate of bluetooth BLE compatible devices using LSL.')
    parser.add_argument("-m", "--mac-address", help="MAC address of the  device.", default="F6:4A:06:35:E9:BA", type=str)
    parser.add_argument("-n", "--name", help="LSL id on the network", default="EchoBlue", type=str)
    parser.add_argument("-s", "--streaming", help="int describing what is streamed : 0 - nothing, 1 - HR, 2 - IBI, 3 - both", default="3", type=int)
    parser.add_argument("-a", "--address-type", help="type : 0 = random, 1 = public", default="0", type=int)
    parser.add_argument("-v", "--verbose", action='store_true', help="Print more verbose information.")
    parser.add_argument("-r", "--reconnect", action='store_true', help="Automatically try to reconnect upon start or when connexion breaks, sending last values in the meantime.")
    parser.set_defaults(verbose=True)
    args = parser.parse_args()

    streaming_hr = (args.streaming == 1 or args.streaming == 3)
    streaming_ibi = (args.streaming == 2 or args.streaming == 3)

    service_id = AssignedNumbers.heart_rate
    char_id = AssignedNumbers.heart_rate_measurement
    
    hrm = HRM(args.mac_address, args.address_type, service_id, char_id, reconnect = args.reconnect, verbose = args.verbose)

    # used for showing effective sampling rate
    samples_hr_in = 0
    samples_ibi_in = 0
    debug_last_show = timeit.default_timer()
    
     # if "reconnect" set, will init the connetion in a separate thread, start streaming dummy values in the meantime
    if hrm.connected or args.reconnect:
        if streaming_hr :
            print("Streaming HR data")
            type_hr = "heart_rate"
            info_hr = StreamInfo(args.name, type_hr, 1, SAMPLINGRATE_HR, 'float32', '%s_%s_%s' % (args.name, type_hr, args.mac_address))
            outlet_hr = StreamOutlet(info_hr)

        if streaming_ibi :
            print("Streaming IBI data")
            type_ibi = 'heart_ibi'
            info_ibi = StreamInfo(args.name, type_ibi, 1, SAMPLINGRATE_IBI, 'float32', '%s_%s_%s' % (args.name, type_ibi, args.mac_address))
            outlet_ibi = StreamOutlet(info_ibi)

        # infinite loop if option set to reconnect automatically, otherwise loop while connected
        while args.reconnect or hrm.isConnected():
            newValHR = hrm.process(1./SAMPLINGRATE_HR) # at least one HR per sample, use this sampling rate
            newValIBI = newValHR and hrm.newIBI # only get new IBI if got new values from Gatt
            
            # depending on option, stream only when get new values, or continuously last value upon reconnect                
            if streaming_hr and (newValHR or not hrm.isConnected()):
                outlet_hr.push_sample([hrm.hr])
                    
            if streaming_ibi:
                # push all values if got new ones
                if newValIBI:
                    for ibi in hrm.ibi:
                        outlet_ibi.push_sample([ibi])
                # only last one if disconnected
                elif not hrm.isConnected():
                    outlet_ibi.push_sample([hrm.ibi[-1]])

            # debug info about incoming sampling rate
            if args.verbose:
                if newValHR:
                    samples_hr_in += 1
                if newValIBI:
                    samples_ibi_in += len(hrm.ibi)

                tick = timeit.default_timer()
                if tick-debug_last_show >= 1:
                    print("Samples HR incoming at: " + str(samples_hr_in) + "Hz and samples IBI at: " + str(samples_ibi_in) + "Hz")
                    samples_hr_in=0
                    samples_ibi_in=0
                    debug_last_show=tick
                
        # once here got disconnected, erase outlet before letting be
        if streaming_hr :
            del info_hr
            del outlet_hr
        if streaming_ibi :
            del info_ibi
            del outlet_ibi
        
        if args.verbose:
            print("terminated")
