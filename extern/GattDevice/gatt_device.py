
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
        TODO: to make sure that bluez helper does not hang, after some time we kill directly blupy helper process... not so pretty
        """
        self.addr = addr
        self.addr_type = addr_type
        self.service_id = service_id
        self.char_id = char_id
        self.reconnect = reconnect
        # we cannot change that yet, how between two connection attempts (in seconds)
        self.connected = False
        self.connecting = False
        # how to wait before two attempts?
        self.con_attempt_timeout = 2
        self.last_con_attempt = 0
        # how long to wait before once connection started before killing bluepy subprocess?
        self.con_start_timeout = 30
        self.last_con_start = 0
        # will point to BLE Peripheral once connected
        self.per = None    
        if handler is None:
            self.handler = self.dummy_handler
        else:
            self.handler = handler
        self.verbose = verbose
        # make sure we don't have race condition while testing for flag
        self.lock = threading.RLock()
        self.connect()
      
    def dummy_handler(self, cHandle, data):
        """
        Process new data upon waitForNotification(). Client should create and call their own hanlder, here just print
        """
        print("get data: " + str(data) + ", from: " + str(cHandle))
      
    def connect(self):
        """ Attempt to (re)connect to device if not active. """
        # don't try to go further if already connected are getting to it
        with self.lock:
            if self.connected or self.connecting:
                return
            self.connecting = True
            self.last_con_start = timeit.default_timer()
        # attempt to connect in separate thread if option set
        if self.reconnect:
            threading.Thread(target=self._do_connect).start()
        else:
            self._do_connect()
          
    def _do_connect(self):
        """ The actual function for connection, connect() should be called to handle reconnect and threading. """
        # FIXME: only pyhthon 3 for ident
        print("connecting to device " + str(self.addr))

        try:
            self.per = Peripheral()
            self.per.connect(self.addr, addrType=ADDR_TYPE_RANDOM if self.addr_type == 0 else  ADDR_TYPE_PUBLIC)
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
            with self.lock:
                self.connected = True
            
        except Exception as e:
            print("Something went wrong while connecting: " + str(e))
            try:
                # attempts explicit disconnect, just in case (testing per because maybe it was removed in isConnected() if connection timed out))
                with self.lock:
                    if self.per:
                        self.per.disconnect()
            except:
                 pass # silently away with any more troubles
            with self.lock:
                self.connected = False
       
        # will wait a bit before next attempt
        self.last_con_attempt = timeit.default_timer()
        with self.lock:
            self.connecting = False

    def isConnected(self):
        """ getter for state of the connection + try to reco periodically if option set and necessary. """
        attempt_connect = False
        with self.lock:
            # bluez helper can stall, check if we should abort a connection
            if self.per and not self.connected and self.connecting and timeit.default_timer() - self.last_con_start >= self.con_start_timeout:
                try:
                    if self.per._helper:
                        self.per._helper.kill()
                    del(self.per)
                except Exception as e: 
                    print("exception while cleanup: " + str(e))
                self.per = None
                # NB here we count on the thread to terminate nicely on its end and set back self.connecting flag to False
            if self.reconnect and not self.connected and not self.connecting and timeit.default_timer() - self.last_con_attempt >= self.con_attempt_timeout:
                attempt_connect = True
        if attempt_connect:
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
                with self.lock:
                    self.connected = False
                if self.verbose:
                    print("disconnected")
        return newVal
 
