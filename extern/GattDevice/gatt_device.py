
from bluepy.btle import Peripheral, ADDR_TYPE_RANDOM, ADDR_TYPE_PUBLIC, AssignedNumbers, BTLEException
import time, timeit, threading, sys

class GattDevice(object):    
    def __init__(self, addr, addr_type, service_id, char_id, handler = None, reconnect = False, verbose = False):
        """
        addr: MAC adresse
        addr_type: BLE adresse can be random (0) or public (1)
        service_id: GATT service ID
        char_id: GATT characteristic ID
        handler: callback function for notification -- dummy one by default
        reconnect: will loop connection indefinitely, launching in in separate thread, upon init and in case BLE breaks. Side effect: if set init function will return immediately, before actually being connected, otherwise blocking call until a connexion attempt has been made
        verbose: print various debug info on stdout
        """
        self.addr = addr
        self.addr_type = addr_type
        self.service_id = service_id
        self.char_id = char_id
        self.reconnect = reconnect
        # we cannot change that yet, how between two connection attempts (in seconds)
        self.connected = False
        self.connecting = False
        self.reco_timeout = 2
        self.last_con = 0
        # will point to BLE Peripheral once connected
        self.per = None    
        if handler is None:
            self.handler = self.dummy_handler
        else:
            self.handler = handler
        self.verbose = verbose
        
        self.connect()
      
    def dummy_handler(self, cHandle, data):
        """
        Process new data upon waitForNotification(). Client should create and call their own hanlder, here just print
        """
        print("get data: " + str(data) + ", from: " + str(cHandle))
      
    def connect(self):
        """ Attempt to (re)connect to device if not active. """
        # don't try to go further if already connected are getting to it
        if self.connected or self.connecting:
            return
        self.connecting = True
        # attempt to connect in separate thread if option set
        if self.reconnect:
            threading.Thread(target=self._do_connect).start()
        else:
            self._do_connect()
          
    def _do_connect(self):
        """ The actual function for connection, connect() should be called to handle reconnect and threading. """
        # we don't do double connections
        if self.connected:
          return
      
         # first resolve said stream type on the network
        self.last_con = timeit.default_timer()
        
        print("connecting to device " + str(self.addr))

        try:
            self.per = Peripheral(self.addr, addrType=ADDR_TYPE_RANDOM if self.addr_type == 0 else  ADDR_TYPE_PUBLIC)
            if self.verbose:
                print("...connected")
            service, = [s for s in self.per.getServices() if s.uuid==self.service_id] # expect list with one entry, fetch it directly (same for below)
            if self.verbose:
                print("Got service")
            ccc, = service.getCharacteristics(forUUID=self.char_id)
            if self.verbose:
                print("Got characteristic")
            # try to find within desrciptors of this characteristic the one that enables config
            cccid = AssignedNumbers.client_characteristic_configuration
            desc, = ccc.getDescriptors(forUUID=cccid)
            if self.verbose:
                print("Got descriptor, writing init sequence")
            # sligthly changed function depending on python
            if (sys.version_info > (3, 0)):
                notif_val = b"\x01\x00"
            else:
                notif_val = '\1\0'
            self.per.writeCharacteristic(desc.handle, notif_val)
            self.per.delegate.handleNotification = self.handler
            self.connected = True
            
        except:
            e = sys.exc_info()[0]
            print("Something went wrong while connecting: " + str(e))
            self.connected = False
       
        # exiting threaded function
        self.connecting = False
        
    def isConnected(self):
        """ getter for state of the connection + try to reco periodically if option set and necessary. """
        if self.reconnect and not self.connected and abs(self.last_con-timeit.default_timer())>=self.reco_timeout:
            self.connect() 
        return self.connected
        
    def process(self, timeout):
        """
        Wait for incoming data. Note: might disconnect upon attempt. Warning: device might send values faster than expected sampling rate.
        timeout: in seconds, for how long should we wait before function returns. 0: blocking call until get new data.
        return True if got notified, False otherwise (Note that handler function is executed before this one returns. Note also that the return value cannot really be used to fill gaps when the sampling rate is not met, because it often happen than several values can be sent in a row by the BLE device to catch up with a gap in notification...)
        """
        newVal = False
        # nothing to if not connected -- but still blocking with timeout
        if not self.isConnected()       :
            if timeout > 0:
                time.sleep(timeout)   
        else:
            try:
                if timeout > 0:
                    newVal = self.per.waitForNotifications(timeout)
                else:
                    newVal = self.per.waitForNotifications()
            except BTLEException:
                # error occured, disconnect
                try:
                    # attempts explicit disconnect, just in case
                    self.per.disconnect()
                except:
                    pass # silently away with any more troubles
                self.connected = False
                if self.verbose:
                    print("disconnected")
        return newVal
 
