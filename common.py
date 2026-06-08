import datetime
import math


class MMBrokenData(Exception):
    pass


class MapMarkModel:
    max_speed = 40.0
    def __init__(self, id, name = ''):
        self.id = id
        self.name = name
        self.regID = None
        self.xm = None
        self.ym = None
        self.last_update = datetime.datetime.now()

    def get_json(self):
        packet = {}
        packet['id'] = str(self.id)
        packet['name'] = str(self.name)
        packet['xm'] = float(self.xm)
        packet['ym'] = float(self.ym)
        packet['regID'] = int(self.regID)

        packet['ludt'] = self.last_update.timestamp()

        return packet

    @staticmethod
    def is_valid_json(obj):
        if not isinstance(obj, dict): return False
        return all(k in obj for k in ('name','id', 'xm', 'ym','regID'))

    def predict_position(self):
        pass

    def is_valid_transition(self,xm,ym,regID):
        delta = datetime.datetime.now() - self.last_update
        if xm is None or ym is None:
            return  True

        if regID ==  self.regID:
            if math.dist((self.xm,self.ym),(xm,ym))/delta.total_seconds() > self.max_speed:
                return False
        return True

    def update_data_from_json(self,data):
        if self.is_valid_json(data):
            self.update_data(*(data[k] for k in ('xm','ym','regID')))
        else:
            raise MMBrokenData

    def update_data(self, xm,ym,regID,pos_predict = True):
        if xm is None or ym is None or (not type(xm) in (float,int)) or (not type(ym) in (float,int)): #  or  not self.is_valid_transition(xm,ym,regID)
            if pos_predict: self.predict_position()
        else:
            self.xm = xm
            self.ym = ym
            # print("LOL")
        if type(regID) != int or (regID < 0 or regID > 54):
            raise MMBrokenData
        self.regID = regID
        self.last_update = datetime.datetime.now()


class PlaneMM(MapMarkModel):
    def __init__(self, id,name=''):
        super().__init__(id,name=name)
        self.direction = None
        self.sensor_speed = None
        self.fuel_level = None
        self.altitude = None
        self.is_landed = False

    @staticmethod
    def is_valid_json(obj):
        if MapMarkModel.is_valid_json(obj) and all(k in obj for k in ('dir','spd', 'fuel', 'alt','land')):
            return True
        else:
            return False

    def predict_position(self):
        if not self.sensor_speed is None:
            delta = datetime.datetime.now() - self.last_update
            if not None in (self.xm,self.ym,self.sensor_speed):
                self.xm += delta.total_seconds() * self.sensor_speed * math.sin(self.direction/180*math.pi)
                self.ym += delta.total_seconds() * self.sensor_speed * -math.cos(self.direction/180*math.pi)

    def update_data(self, xm,ym,regID,dir,spd,fuel,alt,land,raise_exceptions = True,pos_predict = True):
        # print(xm)
        super().update_data(xm,ym,regID,pos_predict)
        # print(type(dir))
        if( not type(dir) in (float,int)) or (dir < 0 or dir > 360):
            if raise_exceptions: raise MMBrokenData
        else:
            self.direction = dir
        if (not type(spd) in (float,int) )or (spd < 0 or spd > self.max_speed):
            if raise_exceptions: raise MMBrokenData
        else:
            self.sensor_speed = spd
        if (not type(fuel) in (float,int)) or (fuel < 0 or fuel > 1):
            if raise_exceptions: raise MMBrokenData
        else:
            self.fuel_level = fuel
        if( not type(alt) in (float,int)) or (alt < 0 or alt > 100):
            if raise_exceptions: raise MMBrokenData
        else:
            self.altitude = alt
        if type(land) != bool:
            if raise_exceptions: raise MMBrokenData
        else:
            self.is_landed = land

    def update_data_from_json(self,data,pos_predict = True):
        if self.is_valid_json(data):
            self.update_data(*(data[k] for k in ('xm','ym','regID','dir','spd','fuel','alt','land')),pos_predict)
        else:
            raise MMBrokenData

    def get_json(self):
        packet = super().get_json()
        packet['dir'] = float(self.direction)
        packet['spd'] = float(self.sensor_speed)
        packet['fuel'] = float(self.fuel_level)
        packet['alt'] = float(self.altitude)
        packet['land'] = bool(self.is_landed)
        print(packet)
        return packet