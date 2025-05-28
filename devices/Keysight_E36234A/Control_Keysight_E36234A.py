import time
import pyvisa 
    
class KeysightControl():
    def __init__(self, moduleNo="USB0::10893::13314::MY61003256::0::INSTR"):
        self.moduleNo = moduleNo
        self.PSModule = pyvisa.ResourceManager("@py").open_resource(self.moduleNo)
        self.Initialize()
        
    def Initialize(self):
        self.Off()
        self.SetVoltage(1, 0)
        self.SetVoltage(2, 0)
        return "ok"

    def ErrorMessage(self, errMsgNo):
        errMsg = ["Module not found", 
                  "Invalid power supply naming", 
                  "Voltage range is 0-60V", 
                  "Invalid power supply channel", 
                  ""]
        print(f'++++++ KeysightControl::ERROR::{errMsg[errMsgNo]} ++++++')
    
    def GetVoltage(self):
        measures = [0,0] #Voltages, currents
        measures[0] = float(self.PSModule.query("MEAS:VOLT? CH1"))
        measures[1] = float(self.PSModule.query("MEAS:VOLT? CH2"))
        return measures

    def GetCurrent(self):
        measures = [0,0] #Voltages, currents
        measures[0] = float(self.PSModule.query("MEAS:CURR? CH1"))
        measures[1] = float(self.PSModule.query("MEAS:CURR? CH2"))
        return measures

    def SetVoltage(self, channel, voltage):
        if voltage > 60 or voltage < 0:
            ErrorMessage(2)
        if channel not in [1,2]:
            ErrorMessage(3)
        self.PSModule.write(f'APPLY CH{channel},{voltage:.4f},1')
        time.sleep(1)
        return "ok"
        
    def On(self, channel=-1):
        if channel in [1,2]:
            self.PSModule.write(f'INST:SEL CH{channel}')
            self.PSModule.write("OUTPUT ON")
        if channel == -1:
            for channel in [1,2]:
                self.PSModule.write(f'INST:SEL CH{channel}')
                self.PSModule.write("OUTPUT ON")
        
    def Off(self, channel=-1):
        if channel in [1,2]:
            self.PSModule.write(f'INST:SEL CH{channel}')
            self.PSModule.write("OUTPUT OFF")
        if channel == -1:
            for channel in [1,2]:
                self.PSModule.write(f'INST:SEL CH{channel}')
                self.PSModule.write("OUTPUT OFF")

    def Close(self):
        self.PSModule.close()
        exit(0)

   
"""
k = KeysightControl()
k.SetVoltage(0, 20)
#print(k.GetVoltage())
k.On(0)
time.sleep(2)
k.SetVoltage(1, 40)
k.On(1)
time.sleep(2)
k.Off()
"""
