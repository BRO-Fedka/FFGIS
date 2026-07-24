import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import math
import time
import threading
import queue
from PIL import Image, ImageTk, ImageDraw
from collections import defaultdict
from common import PlaneMM
from typing import Dict, Any
from dotenv import load_dotenv
from shapely.geometry import Point, Polygon

cx = 1092
cy = cx * math.sqrt(3) / 2
vertices = [
    (cx + cx * math.cos(i * math.pi / 3),
     cy + cx * math.sin(i * math.pi / 3))
    for i in range(6)
]
hexagon = Polygon(vertices)


def check_if_inside(px, py):
    point = Point(px, py)

    if hexagon.contains(point) or hexagon.touches(point):
        return (px, py)

    nearest = hexagon.exterior.interpolate(hexagon.exterior.project(point))
    return (nearest.x, nearest.y)


load_dotenv()
HEX_WIDTH = 1024
HEX_HEIGHT = 888
m_per_pix = 2184 / 1024

class PMMView:
    def __init__(self, planemm, canvas):
        self.mm = planemm
        self.canvas = canvas
        self.mark_img_pi = None
        self.mark_img_item = None
        self.canvas_items = []
        self.is_selected = False
        self.x = None
        self.y = None
        self.dir = None

    def select(self):
        self.is_selected = True

    def unselect(self):
        self.is_selected = False

    def does_contain(self, item):
        return item in self.canvas_items

    def get_coords(self, hex_grid, lod_scale):
        reg_id = self.mm.regID
        coords = hex_grid.get(str(reg_id))
        if not coords:
            return (None, None)
        hex_x, hex_y = hex_to_xy(coords["q"], coords["r"], lod_scale)
        if self.x is None or self.y is None:
            self.x = self.mm.xm
            self.y = self.mm.ym
        rel_x = self.x * lod_scale / m_per_pix
        rel_y = self.y * lod_scale / m_per_pix
        wx = hex_x + rel_x
        wy = hex_y + rel_y
        return wx, wy

    def delete(self):
        for item in self.canvas_items:
            self.canvas.delete(item)

    def update(self):
        if self.x is None or self.y is None or self.dir is None:
            self.x = self.mm.xm
            self.y = self.mm.ym
            self.dir = self.mm.direction
        else:
            self.x = self.x + (self.mm.xm - self.x) * 0.1
            self.y = self.y + (self.mm.ym - self.y) * 0.1
            self.dir = self.dir + ((self.mm.direction - self.dir + 180) % 360 - 180) * 0.06
        self.x,self.y = check_if_inside(self.x,self.y)

    def draw_marker(self, lod_scale, hex_grid, marker_icons_pil, offset_x, offset_y, canvas: tk.Canvas):

        wx, wy = self.get_coords(hex_grid, lod_scale)
        # print(wx,wy)
        icon_type = 'planeB' if self.mm.id == self.mm.name else 'planeR'
        icon_pil = marker_icons_pil.get(icon_type)
        if icon_pil:
            icon_w = icon_h = 16
            scaled_icon = icon_pil.resize((icon_w, icon_h), Image.LANCZOS)
            angle = self.mm.direction
            rotated = scaled_icon.rotate(-angle, expand=True, resample=Image.BICUBIC)
            self.mark_img_pi = ImageTk.PhotoImage(rotated)
            if self.mark_img_item is None:
                self.mark_img_item = self.canvas.create_image(
                    wx + offset_x, wy + offset_y,
                    anchor="center", image=self.mark_img_pi, tags="marker"
                )
                self.canvas_items.append(self.mark_img_item)
                # print("Create")
            else:
                canvas.itemconfig(self.mark_img_item, image=self.mark_img_pi)
                canvas.coords(self.mark_img_item, wx + offset_x, wy + offset_y)
                canvas.lift(self.mark_img_item)
                # print('updt')


def hex_to_xy(q, r, scale=1.0):
    """Координаты левого верхнего угла гекса в пикселях (до масштабирования)."""
    x = q * HEX_WIDTH * 0.75
    y = (r * HEX_HEIGHT + (q % 2) * (HEX_HEIGHT) / 2)
    extra_scale_cof = 1 if scale > 0.1 else 0.99
    return x * scale * extra_scale_cof, y * scale * extra_scale_cof


def scale_image(img, scale):
    if img is None:
        return None
    w, h = int(img.width * scale), int(img.height * scale)
    if w < 1 or h < 1:
        return None
    return img.resize((w, h), Image.LANCZOS)


class UDPListener(threading.Thread):
    def __init__(self, host, port, data_queue):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        # TODO TEMP
        self.queue = data_queue

    def run(self):
        import socket
        import json
        import threading
        import time

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # self.host и self.port теперь — адрес сервера, куда отправляем подписку и пинг
        server_addr = (self.host, self.port)

        # Подписываемся на рассылку
        sock.sendto(b'SUBSCRIBE', server_addr)
        print(f"Подписан на сервер {server_addr}")

        # Пинг-поток, чтобы сервер не отписал нас по таймауту
        def pinger():
            while True:
                try:
                    sock.sendto(b'PING', server_addr)
                except:
                    pass
                time.sleep(2.0)

        threading.Thread(target=pinger, daemon=True).start()

        # Бесконечно принимаем маркеры и кладём в очередь
        while True:
            # print('?')
            try:
                data, _ = sock.recvfrom(65535)
                markers = json.loads(data.decode("utf-8"))
                # print(markers)
                self.queue.put(("markers", markers))
            except Exception as e:
                import logging
                logging.exception("")
                print("UDP error:", e)


lods = [
    {"scale": 1.0, "label": "100%"},
    {"scale": 0.5, "label": "50%"},
    {"scale": 0.25, "label": "25%"},
    {"scale": 0.1, "label": "10%"}
]


class MapApp:
    def __init__(self):
        with open(os.getenv('GRID_FILE'), "r", encoding="utf-8") as f:
            grid_data = json.load(f)

        self.hex_grid = grid_data['hexes']  # {regID: {"q":..., "r":...}}

        # Состояние
        self.lod_index = 3  # 0-3
        self.lod_scale = lods[self.lod_index]["scale"]
        self.offset_x = 0  # смещение начала координат сцены относительно Canvas
        self.offset_y = 0
        self.drag_start = None
        self.last_mouse_pos = None
        self.keys_pressed = set()

        # Данные меток (последние полученные и для анимации)
        self.markers_data: Dict[Any, PMMView] = {}  # id -> dict с полными данными
        # self.marker_items = {}  # id -> canvas-объекты для текущего LOD
        # Изображения гексов (PIL) для разных LOD
        self.hex_images = {}  # regID -> {lod: ImageTk.PhotoImage}
        self.marker_icons_pil = {}  # type -> PIL Image (оригинал)

        # Сеть
        self.data_queue = queue.Queue()
        self.listener = UDPListener(os.getenv('HOST'), int(os.getenv('PORT')), self.data_queue)

        # Построение GUI
        self.root = tk.Tk()
        self.root.title("Hex Map Viewer")
        self.root.geometry("1280x720")

        # Canvas
        self.canvas = tk.Canvas(self.root, bg="#2E2E2E", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Панель инструментов
        toolbar = ttk.Frame(self.root)
        toolbar.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(toolbar, text="Zoom:").pack(side=tk.LEFT, padx=5)
        self.zoom_var = tk.StringVar()
        zoom_combo = ttk.Combobox(toolbar, textvariable=self.zoom_var,
                                  values=[l["label"] for l in lods],
                                  state="readonly", width=6)
        zoom_combo.current(self.lod_index)
        zoom_combo.pack(side=tk.LEFT)
        zoom_combo.bind("<<ComboboxSelected>>", self.on_zoom_combo)

        # Привязки управления
        self.canvas.bind("<Button-1>", self.on_left_click)
        self.canvas.bind("<B1-Motion>", self.on_left_drag)
        self.canvas.bind("<Shift-Button-1>", self.on_shift_click)
        self.canvas.bind("<Shift-B1-Motion>", self.on_shift_drag)
        self.canvas.bind("<Control-Button-1>", self.on_ctrl_click)
        self.canvas.bind("<Double-Button-1>", self.on_double_click)
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.root.bind("<KeyPress>", self.on_key_press)
        self.root.bind("<KeyRelease>", self.on_key_release)

        # Загрузка ресурсов
        self.load_hex_images()
        self.load_marker_icons()

        # Запуск UDP
        self.listener.start()

        # Первое отображение и старт цикла анимации
        self.redraw_hexes()
        self.process_udp_queue()
        self.process_keyboard()
        self.animate()

    def animate(self):

        for mid, mv in self.markers_data.items():
            mv.update()
        self.redraw_all_markers()
        self.root.after(30, self.animate)

    def run(self):
        self.root.mainloop()

    def load_hex_images(self):
        import os
        hex_images_list = os.listdir(os.getenv("HEX_IMAGES_PATH"))
        hex_images_list.sort()
        # delarr = []
        # for hin in hex_images_list:
        #     if 'home' in hin.lower():
        #         delarr.append(hin)
        # for _ in delarr:
        #     hex_images_list.remove(_)
        hex_names = list(map(lambda hin: hin.replace('Hex.tga', '').replace('Map', ''), hex_images_list))
        print(list(enumerate(hex_names)))

        for reg_id_str, coords in self.hex_grid.items():
            reg_id = int(reg_id_str)
            img_path = os.path.join(os.getenv("HEX_IMAGES_PATH"), hex_images_list[reg_id])
            if not os.path.exists(img_path):
                print(f"Missing hex image: {img_path}")
                continue
            pil_img = Image.open(img_path).convert("RGBA")
            self.hex_images[reg_id] = {}
            # Создаём уменьшенные копии для всех LOD
            for lod, level in enumerate(lods):
                scale = level["scale"]
                scaled = pil_img.resize(
                    (int(HEX_WIDTH * scale), int(HEX_HEIGHT * scale)),
                    Image.LANCZOS
                )
                self.hex_images[reg_id][lod] = ImageTk.PhotoImage(scaled)

    def load_marker_icons(self):
        folder = os.getenv("MARKER_IMAGES_PATH")
        if not os.path.isdir(folder):
            return
        for fname in os.listdir(folder):
            if fname.lower().endswith('.png'):
                type_name = os.path.splitext(fname)[0]
                img = Image.open(os.path.join(folder, fname)).convert("RGBA")
                self.marker_icons_pil[type_name] = img
        print(f"Loaded marker icons: {list(self.marker_icons_pil.keys())}")

    def redraw_hexes(self):
        self.canvas.delete("hex")
        for reg_id, lod_dict in self.hex_images.items():
            if self.lod_index in lod_dict:
                photo = lod_dict[self.lod_index]
                coords = self.hex_grid[str(reg_id)]
                x, y = hex_to_xy(coords["q"], coords["r"], self.lod_scale)
                self.canvas.create_image(x + self.offset_x, y + self.offset_y,
                                         anchor="nw", image=photo, tags="hex")
        # Перерисовать маркеры (они привязаны к положению гексов)
        self.redraw_all_markers()

    def redraw_all_markers(self):
        for mid, mv in self.markers_data.items():
            mv.draw_marker(self.lod_scale, self.hex_grid, self.marker_icons_pil, self.offset_x, self.offset_y,
                           self.canvas)

        # ... (остальная логика отрисовки иконки/треугольника/точки с использованием wx, wy и self.offset_x)

    def update_marker_positions(self, markers_list):
        # print(markers_list)
        received_ids = set()
        for m in markers_list:
            mid = m["id"]
            received_ids.add(mid)
            is_new_m = False
            if not mid in self.markers_data.keys():
                is_new_m = True
                self.markers_data[mid] = PMMView(PlaneMM(mid, m['name']), self.canvas)
            self.markers_data[mid].mm.update_data_from_json(m, False)
            if is_new_m:
                self.markers_data[mid].draw_marker(self.lod_scale, self.hex_grid, self.marker_icons_pil, self.offset_x,
                                                   self.offset_y, self.canvas)

        # Удаляем метки, которых нет в новом пакете
        for mid in list(self.markers_data.keys()):
            print(mid)
            if not mid in received_ids:
                print('del', mid)
                self.markers_data[mid].delete()
                del self.markers_data[mid]
                # self.markers_data.pop(mid)

    def on_left_click(self, event):
        # Начинаем перетаскивание (pan) или выделение?
        # Проверим, не нажат ли Shift/Ctrl в данный момент
        if (event.state & 0x0001):  # Shift нажат
            self.start_rubberband(event)
            return
        if (event.state & 0x0004):  # Ctrl нажат
            self.toggle_marker_selection(event)
            return
        # Иначе - pan
        self.drag_start = (event.x, event.y)

    def on_left_drag(self, event):
        if self.drag_start:
            dx = event.x - self.drag_start[0]
            dy = event.y - self.drag_start[1]
            self.offset_x += dx
            self.offset_y += dy
            self.drag_start = (event.x, event.y)
            self.canvas.move("all", dx, dy)  # перемещаем все объекты
            # Обновим сохранённые позиции анимации

    def on_shift_click(self, event):
        self.start_rubberband(event)

    def on_shift_drag(self, event):
        if not hasattr(self, 'rubberband_rect'):
            return
        x0, y0 = self.rubberband_start
        self.canvas.coords(self.rubberband_rect, x0, y0, event.x, event.y)

    def start_rubberband(self, event):
        self.rubberband_start = (event.x, event.y)
        self.rubberband_rect = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline="white", dash=(2, 2), tag="rubberband"
        )
        self.canvas.bind("<ButtonRelease-1>", self.end_rubberband)

    def end_rubberband(self, event):
        if hasattr(self, 'rubberband_rect'):
            x1, y1, x2, y2 = self.canvas.coords(self.rubberband_rect)
            self.canvas.delete("rubberband")
            del self.rubberband_rect
            # Выделяем маркеры, попадающие в прямоугольник
            for mid, mv in self.markers_data.items():
                coords = mv.get_coords(self.hex_grid, self.lod_scale)
                if coords:
                    cx, cy = coords[0], coords[1]  # для изображения coords - это [x,y]
                    if min(x1, x2) <= cx <= max(x1, x2) and min(y1, y2) <= cy <= max(y1, y2):
                        mv.select()
            self.canvas.unbind("<ButtonRelease-1>")

    def on_ctrl_click(self, event):
        self.toggle_marker_selection(event)

    def toggle_marker_selection(self, event):
        # Переключить выделение маркера под курсором
        item = self.canvas.find_closest(event.x, event.y)
        for mid, mv in self.markers_data.items():
            if mv.does_contain(item):
                if mv.is_selected:
                    mv.unselect()
                else:
                    mv.select()

    def on_double_click(self, event):
        # Открыть окно с деталями выделенных маркеров
        selected = []
        for mid, mv in self.markers_data.items():
            if mv.is_selected:
                selected.append(selected)
        if selected:
            self.show_details(selected)

    def show_details(self, marker_ids):
        pass
        # TODO
        # win = tk.Toplevel(self.root)
        # win.title("Marker Details")
        # columns = ("ID", "Type", "Name", "regID", "X/Y", "Dir")
        # tree = ttk.Treeview(win, columns=columns, show="headings")
        # for col in columns:
        #     tree.heading(col, text=col)
        #     tree.column(col, width=80)
        # for mid in marker_ids:
        #     data = self.markers_data.get(mid)
        #     if data:
        #         tree.insert("", "end", values=(
        #             data["id"],
        #             data.get("type", ""),
        #             data.get("name", ""),
        #             data["regID"],
        #             f"{data['x']:.1f},{data['y']:.1f}",
        #             f"{data.get('dir', 0):.0f}°"
        #         ))
        # tree.pack(fill=tk.BOTH, expand=True)

    def on_mousewheel(self, event):
        """Зум колёсиком мыши с сохранением позиции под курсором."""
        delta = event.delta
        if delta > 0:
            new_lod = max(0, self.lod_index - 1)
        else:
            new_lod = min(len(lods) - 1, self.lod_index + 1)

        if new_lod != self.lod_index:
            self.zoom_to_lod(new_lod, event.x, event.y)

    def on_zoom_combo(self, event):
        """Зум через выпадающий список (зум к центру канваса)."""
        selected = self.zoom_var.get()
        for i, lev in enumerate(lods):
            if lev["label"] == selected:
                canvas_center_x = self.canvas.winfo_width() / 2
                canvas_center_y = self.canvas.winfo_height() / 2
                self.zoom_to_lod(i, canvas_center_x, canvas_center_y)
                break

    def zoom_to_lod(self, new_lod, target_x, target_y):
        old_scale = self.lod_scale
        new_scale = lods[new_lod]["scale"]

        # Вычисляем мировые координаты точки под курсором ДО зума
        world_x = (target_x - self.offset_x) / old_scale
        world_y = (target_y - self.offset_y) / old_scale

        # Меняем LOD
        self.lod_index = new_lod
        self.lod_scale = new_scale
        self.zoom_var.set(lods[new_lod]["label"])

        # Вычисляем новый offset так, чтобы мировые координаты остались под курсором
        self.offset_x = target_x - world_x * new_scale
        self.offset_y = target_y - world_y * new_scale

        self.redraw_hexes()
        self.redraw_all_markers()

    def on_key_press(self, event):
        self.keys_pressed.add(event.keysym)

    def on_key_release(self, event):
        self.keys_pressed.discard(event.keysym)

    def process_keyboard(self):
        speed = 10
        dx = dy = 0
        if 'w' in self.keys_pressed or 'W' in self.keys_pressed or 'Up' in self.keys_pressed:
            dy += speed
        if 's' in self.keys_pressed or 'S' in self.keys_pressed or 'Down' in self.keys_pressed:
            dy -= speed
        if 'a' in self.keys_pressed or 'A' in self.keys_pressed or 'Left' in self.keys_pressed:
            dx += speed
        if 'd' in self.keys_pressed or 'D' in self.keys_pressed or 'Right' in self.keys_pressed:
            dx -= speed
        if dx != 0 or dy != 0:
            self.offset_x += dx
            self.offset_y += dy
            self.canvas.move("all", dx, dy)

        self.root.after(20, self.process_keyboard)

    def process_udp_queue(self):
        try:
            while True:
                msg_type, data = self.data_queue.get_nowait()
                if msg_type == "markers":
                    self.update_marker_positions(data)
        except queue.Empty:
            pass
        self.root.after(100, self.process_udp_queue)
