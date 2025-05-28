import time
import pyvisa 
    
class KeithleyControl():
    def __init__(self, moduleType):
        self.moduleType = moduleType
        if self.moduleType in ["1CH", "1ch", "2200"]:
            self.moduleNo = "USB0::1510::8704::1358266::0::INSTR"
        elif self.moduleType in ["2CH", "2ch", "2230"]:
            self.moduleNo = "USB0::1510::8736::9010039::0::INSTR"
        else:
            ErrorMessage(1)
        self.PSModule = pyvisa.ResourceManager("@py").open_resource(self.moduleNo)
        self.Initialize()
        
    def Initialize(self):
        self.Off()
        self.SetVoltage(0)
        return "ok"

    def ErrorMessage(self, errMsgNo):
        errMsg = ["Module not found", "Invalid power supply naming", "Voltage range is 0-30V", "Voltage range is 0-60V", ""]
        print(f"++++++ KeythleyControl::ERROR::{errMsg[errMsgNo]} ++++++")
        
    def SplitVoltage(self, voltage):
        if voltage > 60 or voltage < 0:
            ErrorMessage(3)
        return [min(voltage, 30.), max(voltage-30., 0.)]
    
    def GetVoltage(self):
        if self.moduleType in ["1CH", "1ch", "2200"]:
            voltage = self.PSModule.query("MEAS:VOLT?")
            current = self.PSModule.query("MEAS:CURR?")
            
        elif self.moduleType in ["2CH", "2ch", "2230"]:
            voltage = self.PSModule.query("MEAS:VOLT? ALL")
            current = self.PSModule.query("MEAS:CURR? ALL")
       
        else:
            self.ErrorMessage(1)
            
        return [voltage, current]

    def SetVoltage(self, voltage):
        if self.moduleType in ["1CH", "1ch", "2200"]:
            if voltage > 30:
                ErrorMessage(2)
            voltageValue = voltage
            self.PSModule.write(f"VOLT {voltageValue:.4f}")
            self.PSModule.write(f"CURR 1")
            
        elif self.moduleType in ["2CH", "2ch", "2230"]:
            if voltage > 60:
                ErrorMessage(3)
            voltageValues = self.SplitVoltage(voltage)
            self.PSModule.write(f"APPLY CH1,{voltageValues[0]:.4f},1")
            self.PSModule.write(f"APPLY CH2,{voltageValues[1]:.4f},1")
        
        else:
            self.ErrorMessage(1)
        
        time.sleep(3)
        return "ok"
        
    def On(self):
        if self.moduleType in ["1CH", "1ch", "2200"]:
            self.PSModule.write("OUTPUT ON")
            
        elif self.moduleType in ["2CH", "2ch", "2230"]:
            self.PSModule.write("INST:SEL CH1")
            self.PSModule.write("CHANNEL:OUTPUT ON")
            self.PSModule.write("INST:SEL CH2")
            self.PSModule.write("CHANNEL:OUTPUT ON")
   
        else:
            self.ErrorMessage(1)

    def Off(self):
        if self.moduleType in ["1CH", "1ch", "2200"]:
            self.PSModule.write("OUTPUT OFF")
            
        elif self.moduleType in ["2CH", "2ch", "2230"]:
            self.PSModule.write("INST:SEL CH1")
            self.PSModule.write("CHANNEL:OUTPUT OFF")
            self.PSModule.write("INST:SEL CH2")
            self.PSModule.write("CHANNEL:OUTPUT OFF")
   
        else:
            self.ErrorMessage(1)

#k1 = KeithleyControl("1CH")
#k1.SetVoltage(20)
#k1.On()

#k2 = KeithleyControl("2CH")
#k2.SetVoltage(40)
#k2.On()



