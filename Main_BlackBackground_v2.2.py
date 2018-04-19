# coding=UTF-8

from PyQt4.QtGui import QMainWindow
from PyQt4 import QtCore,QtGui
import os
import sys
import time
import datetime
import logging
import logging.config
from ConfigParser import SafeConfigParser
import pymssql

import frmTagInfo
from frmTagInfo import Ui_MainWindow
import SocketModule
import ReaderModule
import SuperIOModule
import clr

import pyping

class WorkerThread(QtCore.QThread):
    def __init__(self):
        QtCore.QThread.__init__(self)
        self.gpio = SuperIOModule.GPIO()

    def monitor(self):
        #
        try:
            self.gpio.set_gpio(self.gpio.green_light, self.gpio.on)
            print "Green Light On Process Success"
            while True:
                if self.gpio.detect_sensor():
                    self.emit(QtCore.SIGNAL('detect'))
                    break

                time.sleep(0.5)
                QtCore.QCoreApplication.processEvents()
        except:
            pass

class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self, parent=None):
        super(MainWindow, self).__init__(parent)
        self.setupUi(self)

        self.gpio = SuperIOModule.GPIO()
        # set gpio initial
        self.gpio.set_gpio(self.gpio.green_light, self.gpio.off)
        self.gpio.set_gpio(self.gpio.red_light, self.gpio.off)
        self.gpio.set_gpio(self.gpio.yellow_light, self.gpio.off)
        sys.setrecursionlimit(10000000)

        # logging setting
        logging.config.fileConfig('logging.conf')
        self.logger = logging.getLogger('root')

        # Connect Mode
        self.socketMode = 0x01
        self.rs232Mode = 0x02
        self.Mode = self.socketMode

        # Inventory Mode
        self.InventoryStart = 0x00
        self.InventoryStop = 0x01
        self.InventoryMode = self.InventoryStart

        # Idel Time & DB update
        self.idleStart = 0
        self.idleEnd = 0
        self.isUpdateDB = False

        # ConfigParser
        self.configManager = SafeConfigParser()
        self.configManager.read('config.ini')

        # Restore Config
        self.cfgIp = self.configManager.get('Network', 'ip')
        self.cfgPort = self.configManager.get('Network', 'port')
        self.readerId = self.configManager.get('Reader', 'id')
        self.antenna = self.configManager.get('Reader', 'antenna').split(',')
        self.configMode = self.configManager.get('Mode', 'mode')

        self.dbIp = self.configManager.get('Database', 'IP')
        self.dbPort = self.configManager.get('Database', 'Port')
        self.dbUser = self.configManager.get('Database', 'User')
        self.dbPass = self.configManager.get('Database', 'Pass')
        self.dbDb = self.configManager.get('Database', 'DB')
        self.dbTable = self.configManager.get('Database', 'Table')

        self.epcCol = self.configManager.get('Column', 'EPC')
        self.tidCol = self.configManager.get('Column', 'TID')
        self.readerIdCol = self.configManager.get('Column', 'ReaderID')
        self.timeCol = self.configManager.get('Column', 'Time')

        # Socket Mode
        self.socket = SocketModule.SocketModule(self.cfgIp, int(self.cfgPort))

        # Reader
        self.reader = ReaderModule.ReaderModule()

        # buttons
        self.btnRefresh.clicked.connect(self.btn_refresh_click)

        # tableView
        self.model = QtGui.QStandardItemModel(self.tableView)
        self.model.setColumnCount(3)
        self.model.setHeaderData(0, QtCore.Qt.Horizontal, 'EPC')
        # self.model.setHeaderData(1, QtCore.Qt.Horizontal, 'TID')
        self.model.setHeaderData(1, QtCore.Qt.Horizontal, 'ReaderID')
        self.model.setHeaderData(2, QtCore.Qt.Horizontal, 'Time')
        self.tableView.setModel(self.model)
        self.tableView.setColumnWidth(0, 150)
        # self.tableView.setColumnWidth(1, 245)
        self.tableView.setColumnWidth(1, 240)
        self.tableView.setColumnWidth(2, 250)
        self.tags = []

        # other UI setting
        self.btnInventoryStart.setDisabled(True)
        self.btnInventoryStop.setDisabled(True)

        # pictrue
        from PyQt4.QtGui import QPixmap
        pixmap = QPixmap(os.getcwd() + "/scannel_logo.jpg")
        self.lbLogo.setPixmap(pixmap)
        self.lbLogo.setScaledContents(True)

        # clr add reference initial
        clr.AddReference('EncodeTagLib')
        from EncodeTagLib import EncodeTag
        self.encodeTag = EncodeTag('0000000003171215', '01215A01')

        # Socket Mode Connect Initial
        if self.cfgIp == "" and self.cfgPort == "":
            if self.cfgIp == "":
                print "IPAddress is required"
            if self.cfgPort == "":
                print "Port is required"
        else:
            # new Socket
            self.socket = SocketModule.SocketModule(self.cfgIp, int(self.cfgPort))
            try:
                self.socket.connect()
            except Exception as err:
                self.logger.debug(err.message)
            # Log
            self.logger.debug("socket connect status: " + str(self.socket.isConnect()))

        # check db server
        self.check_dbserver_alive()

    """
    Close Window
    """
    def closeEvent(self, event):
        reply = QtGui.QMessageBox.question(self, 'Message', "Are you sure to quit?", QtGui.QMessageBox.Yes, QtGui.QMessageBox.No)
        if reply == QtGui.QMessageBox.Yes:
            self.socket.disConnect()
            event.accept()
        else:
            event.ignore()
            

    """
    Check connect status
    """
    def check_connect(self):
        if self.socket.isConnect() == False and self.rs232.isConnect() == False:
            return False
        else:
            return True

    """
    Check db server alive or not
    """
    def check_dbserver_alive(self):
        if self.dbIp and self.dbPort and self.dbUser and self.dbPass:
            try:
                server = "{0}:{1}".format(self.dbIp, self.dbPort)
                with pymssql.connect(server, self.dbUser, self.dbPass, self.dbDb, 2) as conn:
                    self.gpio.set_gpio(self.gpio.yellow_light, self.gpio.on)
            except Exception as ex:
                self.logger.debug(ex.message)
        # dbConnectStatus = pyping.ping(self.dbIp)
        # if dbConnectStatus == 0:
        #     self.gpio.set_gpio(self.gpio.yellow_light, self.gpio.on)
        # else:
        #     self.gpio.set_gpio(self.gpio.yellow_light, self.gpio.off)

    """
    Read Tag Process
    """
    def read_data(self):
        print 'Read Data'
        # Check Connection
        if not self.check_connect():
            self.logger.debug("No Connection!")
            print "No Connection"
            return False
        print "Connection Mode: " + str(self.Mode)
        # Send Command
        i = 0
        while True:
            if self.gpio.detect_no_sensor():
                self.updateDB()
                self.emit(QtCore.SIGNAL('monitor'))
                break
            try:
                if self.Mode == self.socketMode:
                    if i == 0:
                        for currantenna in self.antenna:
                            if currantenna == '1':
                                data = self.socket.sendCmd(self.reader.setWorkingAntenna(self.reader.working_antenna1))
                                self.logger.debug("SetWorkingAntenna1")
                            if currantenna == '2':
                                data = self.socket.sendCmd(self.reader.setWorkingAntenna(self.reader.working_antenna2))
                                self.logger.debug("SetWorkingAntenna2")
                            if currantenna == '3':
                                data = self.socket.sendCmd(self.reader.setWorkingAntenna(self.reader.working_antenna3))
                                self.logger.debug("SetWorkingAntenna3")
                            if currantenna == '4':
                                data = self.socket.sendCmd(self.reader.setWorkingAntenna(self.reader.working_antenna4))
                                self.logger.debug("SetWorkingAntenna4")
                        self.btnRefresh.click()

                    i += 1
                    time.sleep(0.005)
                    self.logger.debug("Send Read Data Command(cmd_read)!")
                    data = self.socket.sendCmd(self.reader.readTag(self.reader.cmd_read_type_tid, 0x00, 0x06))
                    if len(data) > 0:
                        self.logger.debug("Get Response")
                    msgTranArr = self.reader.analyzeData(data)
                    self.logger.debug("Tag Count: " + str(len(msgTranArr)))
                    self.analyze_data(msgTranArr)
                    self.logger.debug("----------Analyze Complete------------")
                else:
                    self.rs232.sendCmd(self.reader.setWorkingAntenna(self.reader.working_antenna1))
                    self.rs232.sendCmd(self.reader.cmd_realtimeInventory(0x00))
            except Exception as err:
                self.logger.debug("=====Error: {0}".format(err.message))

            QtCore.QCoreApplication.processEvents()

    """
    Realtime Inventory Process
    """
    def inventory_data(self):
        self.logger.debug("Sensor Detect and Start Inventory Data!")

        # Check Connection
        if not self.check_connect():
            self.logger.debug("No Connection!")
            print "No Connection"
            return False
        print "Connection Mode: " + str(self.Mode)

        # Send Command
        i = 0
        while True:
            if self.gpio.detect_no_sensor():
                if not self.isUpdateDB:
                    self.updateDB()
                self.logger.debug("No Sensor Detect and Start Monitor!")
                self.emit(QtCore.SIGNAL('monitor'))
                break
            try:
                if self.Mode == self.socketMode:
                    if i == 0:
                        for currantenna in self.antenna:
                            if currantenna == '1':
                                data = self.socket.sendCmd(self.reader.setWorkingAntenna(self.reader.working_antenna1))
                                self.logger.debug("SetWorkingAntenna1")
                            if currantenna == '2':
                                data = self.socket.sendCmd(self.reader.setWorkingAntenna(self.reader.working_antenna2))
                                self.logger.debug("SetWorkingAntenna2")
                            if currantenna == '3':
                                data = self.socket.sendCmd(self.reader.setWorkingAntenna(self.reader.working_antenna3))
                                self.logger.debug("SetWorkingAntenna3")
                            if currantenna == '4':
                                data = self.socket.sendCmd(self.reader.setWorkingAntenna(self.reader.working_antenna4))
                                self.logger.debug("SetWorkingAntenna4")
                        self.btnRefresh.click()

                    i += 1
                    time.sleep(0.005)
                    self.logger.debug("Send Realtime Inventory Command!")
                    data = self.socket.sendCmd(self.reader.realtimeInventory(self.reader.realtimeInventoryRepeat))
                    if data:
                        if len(data) > 0:
                            self.logger.debug("Get Response")
                        msgTranArr = self.reader.analyzeData(data)
                        self.logger.debug("Tag Count: " + str(len(msgTranArr)))
                        self.analyze_data(msgTranArr)
                        self.logger.debug("----------Analyze Complete------------") 
                else:
                    self.rs232.sendCmd(self.reader.setWorkingAntenna(self.reader.working_antenna1))
                    self.rs232.sendCmd(self.reader.cmd_realtimeInventory(0x00))
            except Exception as err:
                self.logger.debug("=====Error: {0}".format(err.message))

            QtCore.QCoreApplication.processEvents()

    """
    Analyze Data Process
    """
    def analyze_data(self, msgTranlist):
        for msgTran in msgTranlist:
            if msgTran.cmd == 0x00:
                self.logger.debug("Error: Checksum is not correct!")
                continue
            elif msgTran.cmd == 0x81:
                self.process_read_tag(msgTran.databarr)
                continue
            elif msgTran.cmd == 0x89:
                self.process_realtime_inventory(msgTran.databarr)
                continue
            elif msgTran.cmd == 0x67:
                self.process_set_reader_id(msgTran.databarr)
                continue
            elif msgTran.cmd == 0x68:
                self.process_get_reader_id(msgTran.databarr)
                continue
            elif msgTran.cmd == 0x71:
                self.process_set_baudrate(msgTran.databarr)
                continue
            elif msgTran.cmd == 0x76:
                self.process_set_output_power(msgTran.databarr)
                continue
            elif msgTran.cmd == 0x77:
                self.process_get_output_power(msgTran.databarr)
                continue
            else:
                self.logger.debug("Cannot Recognize")

    """
    Return Data Process
    """

    def process_set_reader_id(self, databarr):
        self.process_error_code(databarr)

    def process_get_reader_id(self, databarr):
        readerIdStr = ""
        for d in databarr:
            readerIdStr += hex(d)[2:].upper() + " "
        self.txtGetReaderId.setText(readerIdStr)

    def process_set_baudrate(self, databarr):
        if self.process_error_code(databarr):
            self.configManager.set('RS232', 'baudrate', self.cmbSetBauRate.currentText())
            self.configManager.write(open('config.ini', 'wb'))
            self.cmbBaudrate.setCurrentIndex(self.rs232.getBaudRate().index(self.cmbSetBauRate.currentText()))

    def process_set_work_antenna(self, databarr):
        self.process_error_code(databarr)

    def process_get_work_antenna(self, databarr):
        antenna = databarr[0]
        if antenna == 0x00:
            print "Antenna1"
            self.set_antenna_active_change(1)
            return False
        if antenna == 0x01:
            print "Antenna2"
            self.set_antenna_active_change(2)
            return False
        if antenna == 0x02:
            print "Antenna3"
            self.set_antenna_active_change(3)
            return False
        if antenna == 0x03:
            print "Antenna4"
            self.set_antenna_active_change(4)
            return False

    def set_antenna_active_change(self, antNum):
        if antNum == 1:
            self.chkAnt1.setChecked(True)
            self.chkAnt2.setChecked(False)
            return False
        elif antNum == 2:
            self.chkAnt1.setChecked(False)
            self.chkAnt2.setChecked(True)
            return False

    def process_set_output_power(self, databarr):
        self.process_error_code(databarr)

    def process_get_output_power(self, databarr):
        if len(databarr) == 1:
            print "CurrentOutputPower: " + str(databarr[0])
            self.txtDbm.setText(str(databarr[0]))
            return False
        elif len(databarr) == 4:
            for d in databarr:
                print d
            return False
        else:
            print "Error"

    def process_read_tag(self, databarr):
        dataLen = len(databarr)
        if dataLen == 1:
            self.process_error_code(databarr)
        else:
            """
            N:len(databarr)
            0:2bytes[Tag Count]
            2:DataLen[]
            3~N-4:PC(2),EPC(),CRC(2),ReadData()
            N-3:ReadLen
            N-2:AntId
            N-2:ReadCount
            """
            nDataLen = databarr[dataLen - 3]
            nEpcLen = databarr[2] - nDataLen - 4
            # PC
            strPC = ""
            for b in range(3, 5):
                strPC += str(hex(databarr[b]))[2:].zfill(2) + ' '
            strPC = strPC.upper()
            # EPC
            strEPC = ""
            epcEnd = 5 + nEpcLen
            if epcEnd <= dataLen:
                for b in range(5, epcEnd):
                    strEPC += str(hex(databarr[b]))[2:].zfill(2) + ' '
            strEPC = strEPC.upper()
            # CRC
            strCRC = ""
            crcEnd = 5 + nEpcLen + 2
            if crcEnd <= dataLen:
                for b in range(5 + nEpcLen, crcEnd):
                    strCRC += str(hex(databarr[b]))[2:].zfill(2) + ' '
            strCRC = strCRC.upper()
            # TID
            strData = ""
            tidDataEnd = 7 + nEpcLen + nDataLen
            if tidDataEnd <= dataLen:
                for b in range(7 + nEpcLen, tidDataEnd):
                    strData += str(hex(databarr[b]))[2:].zfill(2) + ' '
            strData = strData.upper()
            # AntID
            strAntId = databarr[dataLen - 2]
            # Read Count
            strReadCount = databarr[dataLen - 1]
            self.logger.debug("PC: {0} | EPC: {1} | CRC: {2} | TID: {3}".format(strPC, strEPC, strCRC, strData))
            i = self.model.rowCount()
            # Detect Duplicate
            # EPC = PC + EPC
            strEPC = strPC + strEPC
            hasExist = False
            if len(self.tags) > 0:
                for tag in self.tags:
                    if strEPC in tag:
                        hasExist = True
                        break
            if not hasExist:
                # Update Tags
                self.tags.append(strEPC)
                # Update TableView
                epcColVal = strEPC.replace(' ', '')
                # EPC Decode
                barcode_info = self.encodeTag.ToBarcode(epcColVal)
                barcode = epcColVal
                if barcode_info:
                    if barcode_info.Text:
                        barcode = barcode_info.Text
                # Tid
                tidColVal = strData.replace(' ', '')
                timeColVal = datetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S')
                self.model.setItem(i, 0, QtGui.QStandardItem(barcode))
                self.model.setItem(i, 1, QtGui.QStandardItem(tidColVal))
                self.model.setItem(i, 2, QtGui.QStandardItem(self.readerId))
                dtNow = datetime.datetime.now()
                hIn24Format = dtNow.strftime('%H')
                if int(hIn24Format) >= 12:
                    amPmStr = 'PM'
                else:
                    amPmStr = 'AM'
                self.model.setItem(i, 3, QtGui.QStandardItem(dtNow.strftime('%m/%d/%Y %I:%M ') + amPmStr))
                self.tableView.setModel(self.model)
                # Sql Server
                # self.check_dbserver_alive()
                if self.dbIp and self.dbPort and self.dbUser and self.dbPass:
                    try:
                        server = "{0}:{1}".format(self.dbIp, self.dbPort)
                        insertSql = "INSERT INTO {0} VALUES (%s, %s, %s, %s)".format(self.dbTable)
                        with pymssql.connect(server, self.dbUser, self.dbPass, self.dbDb, 2) as conn:
                            self.gpio.set_gpio(self.gpio.yellow_light, self.gpio.on)
                            with conn.cursor(as_dict=True) as cursor:
                                cursor.execute(insertSql, (barcode, tidColVal, self.readerId, timeColVal))
                                conn.commit()
                    except Exception as ex:
                        print 'DB Error: {0}'.format(ex.message)
                        self.logger.debug('DB Error: {0}'.format(ex.message))
                        self.gpio.set_gpio(self.gpio.yellow_light, self.gpio.off)

            # update Tag Count
            self.lbInventoryQuantity.setText(str(self.model.rowCount()).zfill(4))

    """
    RealTimeInventoryDataAnalyze
    """
    def process_realtime_inventory(self, databarr):
        dataLen = len(databarr)
        if dataLen == 1:
            print "Datalen: 1"
            self.process_error_code(databarr)
            return False
        elif dataLen == 7:
            self.logger.debug("Get Total Count Response!")
            nReadRate = databarr[1] * 256 + databarr[2]
            nDataCount = databarr[3] * 256 * 256 * 256 + databarr[4] * 256 * 256 + databarr[5] * 256 + databarr[6]
            # TODO: calculate related average value
        else:
            nEpcLen = dataLen - 2
            rssiLocation = 1 + nEpcLen
            strEPC = ""
            # EPC= PC + EPC
            for b in range(1, 1 + nEpcLen):
                strEPC += str(hex(databarr[b]))[2:].zfill(2) + " "
            strEPC = strEPC.upper()
            dRSSI = databarr[rssiLocation]
            strRSSI = '- ' + str(hex(dRSSI)) + ' dBM'
            self.logger.debug('Tag: ' + strEPC)
            i = self.model.rowCount()
            # Detect Duplicate
            hasExist = False
            if len(self.tags) > 0:
                for tag in self.tags:
                    if strEPC in tag:
                        hasExist = True
                        if self.idleStart == 0:
                            self.idleStart = time.clock()
                        self.idleEnd = time.clock()
                        idleTime = self.idleEnd - self.idleStart
                        if idleTime > 10 and not self.isUpdateDB:
                            self.updateDB()
                            self.isUpdateDB = True
                        break
            if not hasExist:
                # Update Tags
                self.tags.append(strEPC)
                # Update TableView
                epcColVal = strEPC.replace(' ', '')
                barcode_info = self.encodeTag.ToBarcode(epcColVal)
                barcode = epcColVal
                if barcode_info:
                    if barcode_info.Text:
                        barcode = barcode_info.Text
                
                timeColVal = datetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S.%f ')
                self.model.setItem(i, 0, QtGui.QStandardItem(barcode))
                self.model.setItem(i, 1, QtGui.QStandardItem(self.readerId))
                dtNow = datetime.datetime.now()
                hIn24Format = dtNow.strftime('%H')
                if int(hIn24Format) >= 12:
                    amPmStr = 'PM'
                else:
                    amPmStr = 'AM'
                self.model.setItem(i, 2, QtGui.QStandardItem(dtNow.strftime('%Y/%m/%d %H:%M:%S.%f ') + amPmStr))
                self.tableView.setModel(self.model)

                #Caculate Time Consuming
                firstTimeTag_string = self.model.data( self.model.index(0, 2) ).toString()
                lastTimeTag_string = self.model.data( self.model.index(i, 2) ).toString()
                firstTimeTag_minute = float(str(firstTimeTag_string).split(":")[1])
                lastTimeTag_minute = float(str(lastTimeTag_string).split(":")[1])
                firstTimeTag_second = float(str(firstTimeTag_string).split(":")[2][:-3])
                lastTimeTag_second = float(str(lastTimeTag_string).split(":")[2][:-3])
        

                passingTime = round(lastTimeTag_second - firstTimeTag_second + (lastTimeTag_minute-firstTimeTag_minute)*60, 4)


            # update Tag Count
            self.lbInventoryQuantity.setText(str(self.model.rowCount()).zfill(4))
            self.lbTimeConsume.setText(str(passingTime) + " sec.")

    """
    ErrorCode Logging
    """
    def process_error_code(self, databarr):
        rtncode = databarr[0]
        if rtncode == 0x10:
            self.logger.debug("Success")
            return True
        else:
            # print "Error"
            # switch Error Code
            if rtncode == 0x11:
                self.logger.debug("Command Fail")
                return False
            elif rtncode == 0x20:
                self.logger.debug("MCU Reset Error")
                return False
            elif rtncode == 0x21:
                self.logger.debug("CW On Error")
                return False
            elif rtncode == 0x22:
                self.logger.debug("Antenna Mission Error")
                return False
            elif rtncode == 0x23:
                self.logger.debug("Write Flash Error")
                return False
            elif rtncode == 0x24:
                self.logger.debug("Read Flash Error")
                return False
            elif rtncode == 0x25:
                self.loggger.debug("Set Output Power Error")
                return False
            elif rtncode == 0x31:
                self.logger.debug("Tag Inventory Error")
                return False
            elif rtncode == 0x32:
                self.logger.debug("Tag Read Error")
                return False
            elif rtncode == 0x33:
                self.logger.debug("Tag Write Error")
                return False
            elif rtncode == 0x34:
                self.logger.debug("Tag Lock Error")
                return False
            elif rtncode == 0x35:
                self.logger.debug("Tag Kill Error")
                return False
            elif rtncode == 0x36:
                self.logger.debug("No Tag Error")
                return False
            elif rtncode == 0x37:
                self.logger.debug("Inventory Ok But Access Fail")
                return False
            elif rtncode == 0x38:
                self.logger.debug("Buffer Is Empty Error")
                return False
            elif rtncode == 0x40:
                self.logger.debug("Access Or Password Error")
                return False
            elif rtncode == 0x41:
                self.logger.debug("Parameter Invalid")
                return False
            elif rtncode == 0x42:
                self.logger.debug("Parameter Invalid WordCnt Too Long")
                return False
            elif rtncode == 0x43:
                self.logger.debug("Parameter Invalid Membank Out Of Range")
                return False
            elif rtncode == 0x44:
                self.logger.debug("Parameter Invalid Lock Region Out Of Range")
                return False
            elif rtncode == 0x45:
                self.logger.debug("Parameter Invalid Lock Action Out Of Range")
                return False
            elif rtncode == 0x46:
                self.logger.debug("Parameter Reader Address Invalid")
                return False
            elif rtncode == 0x47:
                self.logger.debug("Parameter Invalid AntennaId Out Of Range")
                return False
            elif rtncode == 0x48:
                self.logger.debug("Parameter Invalid Output Power Out Of Range")
                return False
            elif rtncode == 0x49:
                self.logger.debug("Parameter Invalid Frequency Region Out Of Range")
                return False
            elif rtncode == 0x4A:
                self.logger.debug("Parameter Invalid Baudrate Out Of Range")
                return False
            elif rtncode == 0x4B:
                self.logger.debug("Parameter Beeper Mode Out Of Range")
                return False
            elif rtncode == 0x4C:
                self.logger.debug("Parameter Epc Match Len Too Long")
                return False
            elif rtncode == 0x4D:
                self.logger.debug("Parameter Epc Match Len Error")
                return False
            elif rtncode == 0x4E:
                self.logger.debug("Parameter Invalid Epc Match Mode")
                return False
            elif rtncode == 0x4F:
                self.logger.debug("Parameter Invalid Frequency Range")
                return False
            elif rtncode == 0x50:
                self.logger.debug("Fail To Get RN16 From Tag")
                return False
            elif rtncode == 0x51:
                self.logger.debug("Parameter Invalid Drm Mode")
                return False
            elif rtncode == 0x52:
                self.logger.debug("Pll Lock Fail")
                return False
            elif rtncode == 0x53:
                self.logger.debug("Rf Chip Fail To Response")
                return False
            elif rtncode == 0x54:
                self.logger.debug("Fail To Achieve Desired Output Power")
                return False
            elif rtncode == 0x55:
                self.logger.debug("Copyright Authentication Fail")
                return False
            elif rtncode == 0x56:
                self.logger.debug("Spectrum Regulation Error")
                return False
            elif rtncode == 0x57:
                self.logger.debug("Output Power Too Low")
                return False

    """
    Update DB
    """
    def updateDB(self):
        row = self.model.rowCount()
        multiInsertData = ""
        timeColVal_DB = datetime.datetime.now().strftime('%Y/%m/%d %H:%M:%S')
        # Sql Server
        if self.dbIp and self.dbPort and self.dbUser and self.dbPass:
            try:
                server = "{0}:{1}".format(self.dbIp, self.dbPort)
                
                for i in range(0, row):
                    barcode = self.model.data( self.model.index(i, 0) ).toString()
                    readerId = self.model.data( self.model.index(i, 1) ).toString()
                    timeResult = self.model.data( self.model.index(i, 2) ).toString().split(".")
                    multiInsertData = multiInsertData + "('" + barcode + "','" + readerId + "','" + timeResult[0] + "'),"

                multiInsertData = multiInsertData[:-1]
                insertSql = "INSERT INTO {0} ({1}, {2}, {3}) VALUES {4}".format(self.dbTable, self.epcCol, self.readerIdCol, self.timeCol, str(multiInsertData))
                with pymssql.connect(server, self.dbUser, self.dbPass, self.dbDb, 2) as conn:
                    with conn.cursor(as_dict=True) as cursor:
                        cursor.execute(insertSql)
                        conn.commit()

            except Exception as ex:
                print 'DB Error: {0}'.format(ex.message)
                self.logger.debug('DB Error: {0}'.format(ex.message))
                self.gpio.set_gpio(self.gpio.yellow_light, self.gpio.off)
        
    """
    Refresh TableView
    """
    def btn_refresh_click(self):
        self.model.removeRows(0, self.model.rowCount())
        self.tableView.setModel(self.model)
        self.lbInventoryQuantity.setText(str(0).zfill(4))
        self.lbTimeConsume.setText("0.0000 sec.")
        self.tags[:] = []
        self.idleStart = 0
        self.idleEnd = 0
        self.isUpdateDB = False



if __name__ == '__main__':
    app = frmTagInfo.QtGui.QApplication(sys.argv)

    # new object
    window = MainWindow()
    monitorThread = WorkerThread()

    # signal definition
    # when main ui thread click tcp or rs232 connect
    app.connect(window, QtCore.SIGNAL('monitor'), monitorThread.monitor)
    # when sensor detect
    # app.connect(monitorThread, QtCore.SIGNAL('detect'), window.read_data)
    app.connect(monitorThread, QtCore.SIGNAL('detect'), window.inventory_data)

    # object show and start
    window.show()
    monitorThread.start()
    if window.socket.isConnect():
        print "Set Monitor Mode"
        window.emit(QtCore.SIGNAL('monitor'))


    # window.tabMain.show()
    sys.exit(app.exec_())
