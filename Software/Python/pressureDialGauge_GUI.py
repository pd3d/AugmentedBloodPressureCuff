'''
*
* Read pressure sensor and display readings on a dial gauge
*
* Adapted from: John Harrison's original work
* Link: http://cratel.wichita.edu/cratel/python/code/SimpleVoltMeter
*
* VERSION: 0.4.10
*   - MODIFIED: Switched entire communication protocol from PySerial in favor of PyBluez
*   - ADDED   : Program now closes BT port on exit
*   - ADDED   : Change sampling frequency
*   - ADDED   : Ability to call this program from external GUI
*   - ADDED   : Ability to select stethoscope address from external GUI
*   - ADDED   : Tell stethoscope what name to record session under
*   - MODIFIED: Major cleanup of code to better implement in GUI 2.0 [INCOMPLETE]
*
* KNOWN ISSUES:
*   - Searching for stethoscope puts everything on hold.    (Inherent limitation of PyBluez)
*   - If no BT device is connected, pushing exit will
*     throw an error.                                       (Program still closes fine)
* 
* AUTHOR                    :   Mohammad Odeh
* DATE                      :   Mar. 07th, 2017 Year of Our Lord
* LAST CONTRIBUTION DATE    :   Feb. 02nd, 2018 Year of Our Lord
*
'''

# ************************************************************************
# IMPORT MODULES
# ************************************************************************

# Python modules
import  sys, time, bluetooth, serial, argparse                  # 'nuff said
import  Adafruit_ADS1x15                                        # Required library for ADC converter
from    PyQt4               import QtCore, QtGui, Qt            # PyQt4 libraries required to render display
from    PyQt4.Qwt5          import Qwt                          # Same here, boo-boo!
from    numpy               import interp                       # Required for mapping values
from    threading           import Thread                       # Run functions in "parallel"
from    os                  import getcwd, path, makedirs       # Pathname manipulation for saving data output

# PD3D modules
from    dial                        import Ui_MainWindow        # Imports pre-built dial guage from dial.py
from    timeStamp                   import fullStamp            # Show date/time on console output
from    stethoscopeProtocol         import *			# import all functions from the stethoscope protocol
from    bluetoothProtocol_teensy32  import *			# import all functions from the bluetooth protocol -teensy3.2
import  stethoscopeDefinitions      as     definitions

# ************************************************************************
# CONSTRUCT ARGUMENT PARSER 
# ************************************************************************
ap = argparse.ArgumentParser()

ap.add_argument( "-f", "--frequency", type=int, default=0.25,
                help="Set sampling frequency (in secs).\nDefault=1" )
ap.add_argument( "-d", "--debug", action='store_true',
                help="Invoke flag to enable debugging" )
ap.add_argument( "--directory", type=str, default='output',
                help="Set directory" )
ap.add_argument( "--destination", type=str, default="output.txt",
                help="Set destination" )
ap.add_argument( "--stethoscope", type=str, default="00:06:66:D0:E4:94",
                help="Choose stethoscope" )
ap.add_argument( "-m", "--mode", type=str, default="SIM",
                help="Mode to operate under; SIM: Simulation || REC: Recording" )

args = vars( ap.parse_args() )

# ************************************************************************
# SETUP PROGRAM
# ************************************************************************

class MyWindow(QtGui.QMainWindow):

    pressureValue = 0
    lastPressureValue = 0
    
    def __init__( self, parent=None ):

        # Initialize program and extract dial GUI
        QtGui.QWidget.__init__( self, parent )
        self.ui = Ui_MainWindow()
        self.ui.setupUi( self )
        self.thread = Worker( self )

        # Close rfObject socket on exit
        self.ui.pushButtonQuit.clicked.connect( self.cleanUp )

        # Setup gauge-needle dimensions
        self.ui.Dial.setOrigin( 90.0 )
        self.ui.Dial.setScaleArc( 0.0, 340.0 )
        self.ui.Dial.update()
        self.ui.Dial.setNeedle( Qwt.QwtDialSimpleNeedle(
                                                        Qwt.QwtDialSimpleNeedle.Arrow,
                                                        True, Qt.QColor(Qt.Qt.red),
                                                        Qt.QColor(Qt.Qt.gray).light(130)
                                                        )
                                )

        self.ui.Dial.setScaleOptions( Qwt.QwtDial.ScaleTicks |
                                      Qwt.QwtDial.ScaleLabel | Qwt.QwtDial.ScaleBackbone )

        # Small ticks are length 5, medium are 15, large are 20
        self.ui.Dial.setScaleTicks( 5, 15, 20 )
        
        # Large ticks show every 20, put 10 small ticks between
        # each large tick and every 5 small ticks make a medium tick
        self.ui.Dial.setScale( 10.0, 10.0, 20.0 )
        self.ui.Dial.setRange( 0.0, 300.0 )
        self.ui.Dial.setValue( 0 )

        # Unpack argumnet parser parameters as attributes
        self.directory = args["directory"]
        self.destination = args["destination"]
        self.address = args["stethoscope"]
        self.mode = args["mode"]

        # List all available BT devices
        self.ui.pushButtonPair.setEnabled( True )
        self.ui.pushButtonPair.setText(QtGui.QApplication.translate("MainWindow", "Click to Connect", None, QtGui.QApplication.UnicodeUTF8))
        self.ui.pushButtonPair.clicked.connect( lambda: self.connectStethoscope() )

# ------------------------------------------------------------------------

    def connectStethoscope( self ):
        """
        Connects to stethoscope.
        """
        self.thread.deviceBTAddress = str( self.address )
        self.ui.Dial.setEnabled( True )
        self.ui.pushButtonPair.setEnabled( False )

        # Create logfile
        self.setup_log()
        
        # set timeout function for updates
        self.ctimer = QtCore.QTimer()
        self.ctimer.start( 10 )
        QtCore.QObject.connect( self.ctimer, QtCore.SIGNAL( "timeout()" ), self.UpdateDisplay )

# ------------------------------------------------------------------------
 
    def UpdateDisplay(self):
        """
        Updates DialGauge display with the most recent pressure readings.
        """
        
        if self.pressureValue != self.lastPressureValue:
            self.ui.Dial.setValue( self.pressureValue )
            self.lastPressureValue = self.pressureValue

# ------------------------------------------------------------------------

    def scan_rfObject( self ):
        """
        Scan for available BT devices.
        Returns a list of tuples (num, name)
        """
        available = []
        BT_name, BT_address = findSmartDevice( self.address )
        if BT_name != 0:
            available.append( (BT_name[0], BT_address[0]) )
            return( available )

# ------------------------------------------------------------------------

    def setup_log( self ):
        """
        Setup directory and create logfile.
        """
        
        # Create data output folder/file
        self.dataFileDir = getcwd() + "/dataOutput/" + self.directory
        self.dataFileName = self.dataFileDir + "/" + self.destination
        if( path.exists(self.dataFileDir) ) == False:
            makedirs( self.dataFileDir )
            print( fullStamp() + " Created data output folder" )

        # Write basic information to the header of the data output file
        with open( self.dataFileName, "w" ) as f:
            f.write( "Date/Time: " + fullStamp() + "\n" )
            f.write( "Scenario: #" + str(scenarioNumber) + "\n" )
            f.write( "Device Name: " + deviceName + "\n" )
            f.write( "Stethoscope ID: " + self.address + "\n" )
            f.write( "Units: seconds, kPa, mmHg" + "\n" )
            f.close()
            print( fullStamp() + " Created data output .txt file" )

# ------------------------------------------------------------------------

    def cleanUp( self ):
        """
        Clean up at program exit.
        Stops recording and closes communication with device
        """
        
        try:
            print( fullStamp() + " Stopping Recording" )
            stopRecording( self.thread.rfObject )                   #
            QtCore.QThread.sleep( 2 )                               # this delay may be essential
            closeBTPort( self.thread.rfObject )                     # 
        except:
            print( fullStamp() + " Device never connected. Closing Dial." )

# ************************************************************************
# CLASS FOR OPTIONAL INDEPENDENT THREAD
# ************************************************************************

class Worker( QtCore.QThread ):

    deviceBTAddress = 'none'

    # Create flags for what mode we are running
    normal = True
    playback = False
    
    # Define sasmpling frequency (units: sec) controls writing frequency
    wFreq = args["frequency"]
    wFreqTrigger = time.time()
    
    def __init__( self, parent = None ):
        QtCore.QThread.__init__( self, parent )
        # self.exiting = False # not sure what this line is for
        print( fullStamp() + " Initializing Worker Thread" )
        self.owner = parent
        self.start()

# ------------------------------------------------------------------------

    def __del__(self):
        print( fullStamp() + " Exiting Worker Thread" )

# ------------------------------------------------------------------------

    def run(self):
        """
        This method is called by self.start() in __init__()
        """

        while( self.deviceBTAddress == 'none'):                                 # While no device is selected ...
            time.sleep( 0.1 )                                                   # Do nothing

        try:
            self.rfObject = createBTPort( self.deviceBTAddress, port )          # Establish communication
            print( fullStamp() + " Opened " + str(self.deviceBTAddress) )       # Print Diagnostic information

            QtCore.QThread.sleep( 2 )                                           # Delay for stability

            self.status = statusEnquiry( self.rfObject )                        # Send an enquiry byte

            if( self.status == True ):
                # Update labels
                self.owner.ui.pushButtonPair.setText( QtGui.QApplication.translate( "MainWindow",
                                                                                    "Paired",
                                                                                    None,
                                                                                    QtGui.QApplication.UnicodeUTF8) )
                startCustomRecording( self.rfObject, self.owner.destination )   # Start recording
            
            self.startTime = time.time()                                        # Time since the initial reading
            
            while True:
                self.owner.pressureValue = self.readPressure()                  # 

        except Exception as instance:
            print( fullStamp() + " Failed to connect" )                         # Indicate error
            print( fullStamp() + " Exception or Error Caught" )                 # ...
            print( fullStamp() + " Error Type " + str(type(instance)) )         # ...
            print( fullStamp() + " Error Arguments " + str(instance.args) )     # ...

# ------------------------------------------------------------------------

    def readPressure(self):

        # Compute pressure
        V_analog  = ADC.read_adc( 0, gain=GAIN )                                # Convert analog readings to digital
        V_digital = interp( V_analog, [1235, 19279.4116], [0.16, 2.41] )        # Map the readings
        pressure  = ( V_digital/V_supply - 0.04 )/0.018                         # Convert voltage to SI pressure readings
        mmHg = pressure*760/101.3                                               # Convert SI pressure to mmHg

        # Check if we should write to file or not yet
        if( time.time() - self.wFreqTrigger ) >= self.wFreq:
            
            self.wFreqTrigger = time.time()                                     # Reset wFreqTrigger

            # Write to file
            dataStream = "%.02f, %.2f, %.2f\n" %( time.time()-self.startTime,   # Format readings
                                                  pressure, mmHg )              # into desired form
            with open( self.owner.dataFileName, "a" ) as f:
                f.write( dataStream )                                           # Write to file
                f.close()                                                       # Close file

        # Error handling in case BT communication fails (1)    
        try:
            # Entering simulation pressure interval
            if (mmHg >= 55) and (mmHg <= 105) and (self.playback == False):
                self.normal = False                                             # Turn OFF normal playback
                self.playback = True                                            # Turn on simulation

##                # Send start playback command from a separate thread
##                Thread( target=startBlending,                                   # Send start byte
##                        args=(self.rfObject, definitions.KOROT,) ).start()      #  ...

            # Leaving simulation pressure interval
            elif ((mmHg < 55) or (mmHg > 105)) and (self.normal == False):
                self.normal = True                                              # Turn ON normal playback
                self.playback = False                                           # Turn OFF simulation

##                # Send stop playback command from a separate thread
##                Thread( target=stopBlending,                                    # Send stop byte
##                        args=(self.rfObject,) ).start()                         # ...
                
        # Error handling in case BT communication fails (2)        
        except Exception as instance:
            print( "" )                                                         # ...
            print( fullStamp() + " Exception or Error Caught" )                 # ...
            print( fullStamp() + " Error Type " + str(type(instance)) )         # Indicate the error
            print( fullStamp() + " Error Arguments " + str(instance.args) )     # ...
            print( fullStamp() + " Closing/Reopening Ports..." )                # ...

            self.rfObject.close()                                               # Close communications
            self.rfObject = createBTPort( self.deviceBTAddress, port )          # Reopen communications

            print( fullStamp() + " Successful" )

        # Return pressure readings in either case
        finally:
            return( mmHg )                                                      # Return pressure readings in mmHg


# ************************************************************************
# ===========================> SETUP PROGRAM <===========================
# ************************************************************************
port = 1                                                                        # Port number to use in communication
deviceName = "ABPC"                                                             # Designated device name
scenarioNumber = 1                                                              # Device number

V_supply = 3.3                                                                  # Supply voltage to the pressure sensor

ADC = Adafruit_ADS1x15.ADS1115()                                                # Initialize ADC
GAIN = 1                                                                        # Read values in the range of +/-4.096V

# ************************************************************************
# =========================> MAKE IT ALL HAPPEN <=========================
# ************************************************************************

def main():
    
    print( fullStamp() + " Booting DialGauge" )
    app = QtGui.QApplication(sys.argv)
    MyApp = MyWindow()
    MyApp.show()
    sys.exit(app.exec_())
    
if __name__ == "__main__":
    sys.exit( main() )
