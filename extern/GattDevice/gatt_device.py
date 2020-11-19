
# FIXME: on some weird occasions bluepy might freeze (?). At the moment we allow in that case, multiple subprocesses / threads to span, could have memory leak, should be investigated. We could as well just exit in that case -- with a special flag?
# Later: bug might be corrected (faulty preexec_fn), but leaving terminate/kill/duplicate until deemed safe

# NB: several hotfix here related to bluepy, not pretty. At the moment working with 1.3.0. Might consider newer version, e.g. for https://github.com/IanHarvey/bluepy/pull/355

from bluepy.btle import Peripheral, ADDR_TYPE_RANDOM, ADDR_TYPE_PUBLIC, AssignedNumbers, BTLEException
import time, timeit, threading, sys

# for bluepy hack
from bluepy.btle import ScanEntry, BTLEDisconnectError, helperExe, DBG

# sligthly changed function depending on python
if (sys.version_info > (3, 0)):
    import subprocess
    from subprocess import TimeoutExpired
else:
    import subprocess32 as subprocess
    from subprocess32 import TimeoutExpired

import os, select

# copied from https://github.com/IanHarvey/bluepy/pull/374 -- adding timeout for connect
class MyPeripheral(Peripheral):
    # how long to wait upon close for the process to gravciously terminate killing it? 
    WAIT_PROCESS = 2
    def __init__(self, deviceAddr=None, addrType=ADDR_TYPE_PUBLIC, iface=None, timeout=None):
        Peripheral.__init__(self)

        if isinstance(deviceAddr, ScanEntry):
            self._connect(deviceAddr.addr, deviceAddr.addrType, deviceAddr.iface, timeout)
        elif deviceAddr is not None:
            self._connect(deviceAddr, addrType, iface, timeout)
            

    # hotfix: disable preexec_fun to avoid hang upon Popen, close_fds for all
    def _startHelper(self,iface=None):
        if self._helper is None:
            self._stderr = open(os.devnull, "w")
            args=[helperExe]
            if iface is not None: args.append(str(iface))
            self._helper = subprocess.Popen(args,
                                            close_fds=True, # already there for python3
                                            stdin=subprocess.PIPE,
                                            stdout=subprocess.PIPE,
                                            stderr=self._stderr,
                                            universal_newlines=True)
            self._poller = select.poll()
            self._poller.register(self._helper.stdout, select.POLLIN)

            
    def _connect(self, addr, addrType=ADDR_TYPE_PUBLIC, iface=None, timeout=None):
        if len(addr.split(":")) != 6:
            raise ValueError("Expected MAC address, got %s" % repr(addr))
        if addrType not in (ADDR_TYPE_PUBLIC, ADDR_TYPE_RANDOM):
            raise ValueError("Expected address type public or random, got {}".format(addrType))
        self._startHelper(iface)
        self.addr = addr
        self.addrType = addrType
        self.iface = iface
        if iface is not None:
            self._writeCmd("conn %s %s %s\n" % (addr, addrType, "hci"+str(iface)))
        else:
            self._writeCmd("conn %s %s\n" % (addr, addrType))
        rsp = self._getResp('stat', timeout)
        if rsp is None:
            raise BTLEDisconnectError("Timed out while trying to connect to peripheral %s, addr type: %s" %
                                      (addr, addrType), rsp)
        while rsp['state'][0] == 'tryconn':
            rsp = self._getResp('stat', timeout)
            if rsp is None:
                raise BTLEDisconnectError("Timed out while trying to connect to peripheral %s, addr type: %s" %
                                          (addr, addrType), rsp)
        if rsp['state'][0] != 'conn':
            self._stopHelper()
            raise BTLEDisconnectError("Failed to connect to peripheral %s, addr type: %s" % (addr, addrType), rsp)

    def connect(self, addr, addrType=ADDR_TYPE_PUBLIC, iface=None, timeout=None):
        if isinstance(addr, ScanEntry):
            self._connect(addr.addr, addr.addrType, addr.iface, timeout)
        elif addr is not None:
            self._connect(addr, addrType, iface, timeout)

    # hotfix, hardcode a timeout for wait, then just kill as nothing is relevant at this stage, see https://github.com/IanHarvey/bluepy/issues/344
    def _stopHelper(self):
        if self._helper is not None:
            DBG("Stopping ", helperExe)
            self._poller.unregister(self._helper.stdout)
            self._helper.stdin.write("quit\n")
            self._helper.stdin.flush()
            try:
                self._helper.wait(MyPeripheral.WAIT_PROCESS)
            except TimeoutExpired:
                self._helper.kill()
            self._helper = None
        if self._stderr is not None:
            self._stderr.close()
            self._stderr = None
            
    # hotfix to avoid hanging, disable "stat", see https://github.com/IanHarvey/bluepy/issues/390
    def disconnect(self):
        if self._helper is None:
            # actually might want to cleanup other objects
            self.setDelegate(None)
            self._stopHelper()
            return
        # Unregister the delegate first
        self.setDelegate(None)
        self._writeCmd("disc\n")
        #self._getResp('stat')
        self._stopHelper()

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
        # how long a connection should last before aborting?
        self.con_timeout = 20
        # for emergency, how long to wait before once connection started before killing bluepy subprocess?
        self.con_start_timeout = 30
        self.last_con_start = 0
        # for emergency emergency, how long to wait before repeating terminating signal?
        self.terminate_timeout = 2
        self.last_terminate = 0
        # pointer to last launched thread and current thread to have proper garbage collector
        self.last_thread = None
        self.thread = None
        # will point to BLE Peripheral once connected
        self.per = None    
        # we might go the hard way to reset ble connection. 0: no killing, 1: sigtermng, 2: sigkillng
        self.killing =  0
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

    def connect_chars(self):
        """
        To be overloaded if necessary, take care to list services / characteristics of interest.
        TODO: better way to build on GattDevice
        """
        if self.per is not None:
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

    def connect(self):
        """ Attempt to (re)connect to device if not active. """
        # don't try to go further if already connected are getting to it
        with self.lock:
            if self.connected or self.connecting:
                return
            self.connecting = True
            self.killing = 0
            self.last_con_start = timeit.default_timer()
        # attempt to connect in separate thread if option set
        if self.reconnect:
            with self.lock:
                self.last_thread = self.thread
                self.thread = threading.Thread(target=self._do_connect)
            self.thread.start()
        else:
            self._do_connect()
          
    def _do_connect(self):
        """ The actual function for connection, connect() should be called to handle reconnect and threading. """
        # FIXME: only pyhthon 3 for ident
        print("connecting to device " + str(self.addr))

        if self.last_thread is not None:
            if self.verbose:
                print("waiting for previous thread to exit properly")
            try:
                # FIXME: yes, hardcoded value
                self.last_thread.join(MyPeripheral.WAIT_PROCESS)
            except Exception as e:
                print("Something went wrong while waiting for previous thread to terminate: " + str(e))

        with self.lock:
            if self.per is not None:
                del(self.per)
                self.per = None
        try:
            self.per = MyPeripheral()
            self.per.connect(self.addr, addrType=ADDR_TYPE_RANDOM if self.addr_type == 0 else  ADDR_TYPE_PUBLIC, timeout=self.con_timeout)
            if self.verbose:
                print("...connected to device")
            self.connect_chars()
            if self.verbose:
                print("connection ready")
            with self.lock:
                self.connected = True
            
        except Exception as e:
            print("Something went wrong while connecting: " + str(e))
            try:
                # attempts explicit disconnect, just in case (testing per because maybe it was removed in isConnected() if connection timed out))
                with self.lock:
                    if self.per and self.killing == 0:
                        self.per.disconnect()
            except Exception as e:
                 print("exception while cleanup: " + str(e))
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
            if not self.connected and self.reconnect:
                # bluez helper can stall, check if we should try abort a connection
                if self.per and self.connecting and timeit.default_timer() - self.last_con_start >= self.con_start_timeout and self.killing == 0:
                    # will try sigterm
                    self.killing = 1
                    if self.per._helper:
                        try:
                            self.per._helper.terminate()
                        except Exception as e: 
                            print("exception while terminating: " + str(e))
                    # wait a bit before going kill
                    self.last_terminate = timeit.default_timer()
                elif self.per and self.connecting and timeit.default_timer() - self.last_terminate >= self.terminate_timeout and self.killing > 0:
                    # we already tried to issue the command once, and we lost the pointer to subprocess, no choice but to give up and allow duplicate thread
                    if self.killing >= 2 and not self.per._helper:
                        print("HOTFIX: could not stop old thread, give up allow new thread")
                        self.connecting = False
                        attempt_connect = True
                    
                    elif self.killing >= 1:
                        self.killing = 2
                        try:
                            if self.per._helper:
                                self.per._helper.kill()
                        except Exception as e: 
                            print("exception while killing: " + str(e))
                    self.last_terminate = timeit.default_timer()
                    # NB here we count on the thread to terminate nicely on its end and set back self.connecting flag to False
                elif not self.connecting and timeit.default_timer() - self.last_con_attempt >= self.con_attempt_timeout:
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
 
