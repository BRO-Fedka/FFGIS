import socket
import json
import threading
import time
import math
import datetime
from common import PlaneMM, MapMarkModel
from typing import Dict,Any
import os
from dotenv import load_dotenv
load_dotenv()


class GameServer:
    def __init__(self, host, port, max_objects=int(os.getenv('MAX_OBJECTS')),
                 broadcast_interval=float(os.getenv('BROADCAST_INTERVAL')),
                 object_timeout=float(os.getenv('OBJ_TIMEOUT')), subscriber_timeout=float(os.getenv('SUBSCRIBER_TIMEOUT'))):
        self.host = host
        self.port = port
        self.max_objects = max_objects
        self.broadcast_interval = broadcast_interval
        self.object_timeout = object_timeout
        self.subscriber_timeout = subscriber_timeout

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.objects:Dict[Any,MapMarkModel] = {}
        self.subscribers = {}
        self.lock = threading.Lock()
        self.running = False

    def start(self):
        try:
            self.sock.bind((self.host, self.port))
        except OSError as e:
            print(f"[SERVER] Ошибка привязки: {e}. Порт {self.port} занят.")
            return
        self.running = True
        print(f"[SERVER] Запущен на {self.host}:{self.port}")
        threading.Thread(target=self._broadcast_loop, daemon=True).start()
        self._main_loop()

    def _main_loop(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
            except Exception as e:
                print(f"[SERVER] Ошибка приёма: {e}")
                continue
            self._handle_message(data, addr)

    def _handle_message(self, data, addr):
        # print('HNDL')
        try:
            msg = data.decode('utf-8').strip()
        except UnicodeDecodeError:
            print(f"[SERVER] Некорректные данные от {addr}")
            return
        # print('case')
        if msg == 'SUBSCRIBE':
            with self.lock:
                self.subscribers[addr] = time.time()
            print(f"[SERVER] Подписчик добавлен: {addr}")
            return
        if msg == 'UNSUBSCRIBE':
            with self.lock:
                self.subscribers.pop(addr, None)
            print(f"[SERVER] Подписчик удалён: {addr}")
            return
        if msg == 'PING':
            # print('ping')
            with self.lock:
                if addr in self.subscribers:
                    self.subscribers[addr] = time.time()
            return
        # print('obj')
        try:
            obj = json.loads(msg)
        except json.JSONDecodeError:
            print(f"[SERVER] Ошибка JSON от {addr}: {msg[:100]}")
            return
        # print('MM')
        if not PlaneMM.is_valid_json(obj):
            print(f"[SERVER] Некорректный объект от {addr}: {obj}")
            return
        # print('MM')
        id = str(obj['id'])
        name = str(obj['name'])


        with self.lock:
            if len(self.objects) >= self.max_objects and id not in self.objects:
                print(f"[SERVER] Лимит объектов, '{id}' отклонён")
                return
            if not id in self.objects.keys():
                mm = PlaneMM(id, name)
                self.objects[id] = mm
                print("NEW OBJ")
            self.objects[id].update_data_from_json(obj)
            print(f"[SERVER] Обновлён '{id}'")

    def _get_current_state(self):
        now_dt = datetime.datetime.now()
        now = time.time()
        with self.lock:
            expired = [id for id, mm in self.objects.items()
                       if (now_dt - mm.last_update).total_seconds() > self.object_timeout]
            for id in expired:
                del self.objects[id]
                print(f"[SERVER] Объект '{id}' удалён по таймауту")
            dead = [a for a, t in self.subscribers.items()
                    if now - t > self.subscriber_timeout]
            for a in dead:
                del self.subscribers[a]
                print(f"[SERVER] Подписчик {a} удалён по таймауту")
            state = []
            for mm in self.objects.values():
                state.append(mm.get_json())
            return state, list(self.subscribers.keys())

    def _broadcast_loop(self):
        while self.running:
            # print('RUN')
            time.sleep(self.broadcast_interval)
            state, subs = self._get_current_state()
            if not subs: continue
            data = json.dumps(state).encode('utf-8')
            for addr in subs:
                try:
                    # print("SENT",data)
                    self.sock.sendto(data, addr)
                except Exception as e:
                    print(f"[SERVER] Ошибка отправки {addr}: {e}")

    def shutdown(self):
        self.running = False
        self.sock.close()

if __name__ == '__main__':
    server = GameServer(host=os.getenv('HOST'), port=int(os.getenv('PORT')))
    try:
        server.start()
    except KeyboardInterrupt:
        server.shutdown()
        print("[SERVER] Остановлен")