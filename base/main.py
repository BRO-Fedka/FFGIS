import cv2
import numpy as np
import dxcam
import socket
import json
import threading
import math
import time
from PIL import Image, ImageDraw
import statistics
from typing import NamedTuple, Tuple
import pickle
import sys
import os
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

if parent_dir not in sys.path:
   sys.path.append(parent_dir)
from common import PlaneMM
from dotenv import load_dotenv

load_dotenv()

with open('matrices_data.pkl', 'rb') as f:
    Rsig_regID, Rsig_nwP_grid_pos, regID_array_Rsigs, regID_array_Psigs = pickle.load(f)


def toBGR(h):
    h = h[1:]
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))[::-1]


def create_circle_template(r):
    pil_image = Image.new('L', (50, 50), color=0)
    draw = ImageDraw.Draw(pil_image)
    Rs = (12, 15, 18, 21)
    outer_radius = Rs[r]
    cx = 25
    cy = 25
    draw.ellipse([cx - outer_radius, cy - outer_radius, cx + outer_radius, cy + outer_radius], outline=255, width=2)
    template = np.array(pil_image)
    return template


CM_TEMPLATES = [create_circle_template(i) for i in range(0, 4)]

sending_data = {}


def udp_client():
    """Отправка пустого JSON на сервер каждую секунду"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_address = (os.getenv('HOST'), int(os.getenv('PORT')))

    while True:
        try:
            message = json.dumps(sending_data)
            sock.sendto(message.encode(), server_address)
            time.sleep(1)
        except Exception as e:
            import logging
            logging.exception('')
            # TODO serv+base -> offive
            time.sleep(1)


from dataclasses import dataclass


@dataclass
class ColorMark():
    cl_id: int
    r_id: int
    x: float
    y: float
    pos: Tuple[int, int] = None

    def is_content(self):
        return (not self.cl_id is None) and (not self.r_id is None)

    def get_signature(self):
        return (self.r_id, self.cl_id)


class User:
    def __init__(self, player_name: str):
        self.player_name = player_name


alt_sensor_pos = (403, 995)
spd_sensor_pos = (531, 995)
thrtl_sensor_pos = (659, 995)


class Processor:
    def __init__(self, user: User):
        self.RegID = None
        self.user = user
        self.mark = PlaneMM(user.player_name, user.player_name)
        self.is_in_plane = False

    def get_data(self):
        if self.is_in_plane:
            try:

                packet = self.mark.get_json()
                # print("KIK")
            except:
                import logging
                logging.exception('')
                packet = {}
        else:
            packet = {}

        return packet

    def process(self, frame):
        # print("PROC")
        if frame is None:
            print("SHIT FRAME")
            return
        ker = np.ones((3, 3), np.uint8)
        enormous_ker = np.ones((51, 51), np.uint8)
        height, width = frame.shape[:2]
        hsv_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        lower = np.array([0, 0, 150])
        upper = np.array([180, 40, 255])
        map_opened_test = cv2.inRange(hsv_frame, lower, upper)
        lower = np.array([13, 33, 114])
        upper = np.array([22, 46, 122])
        map_bg = cv2.inRange(hsv_frame, lower, upper)
        lower = np.array([0, 0, 0])
        upper = np.array([180, 25, 14])
        map_ui = cv2.inRange(hsv_frame, lower, upper)
        map_opened_test = cv2.bitwise_or(cv2.bitwise_or(map_bg, map_ui), map_opened_test)
        map_opened_test = cv2.dilate(map_opened_test, enormous_ker)
        map_opened_test = cv2.erode(map_opened_test, enormous_ker)
        total_pixels = frame.shape[0] * frame.shape[1]
        white_pixels = cv2.countNonZero(map_opened_test)
        relative_white = white_pixels / total_pixels
        # cv2.imshow("hsv",map_opened_test)
        is_map_opened = relative_white > 0.9
        if hsv_frame[alt_sensor_pos[::-1]][2] > 228 and hsv_frame[alt_sensor_pos[::-1]][2] > 228:
            self.is_in_plane = True
        elif is_map_opened and self.is_in_plane:
            self.is_in_plane = True
        else:
            self.is_in_plane = False

        map_rect = hsv_frame[height - 324:height, 0:324]
        # MASKS here
        if True:
            lower = np.array([0, 70, 70])
            upper = np.array([180, 255, 255])
            maskSV = cv2.inRange(map_rect, lower, upper)
            lower = np.array([120 - 8, 0, 0])
            upper = np.array([120 + 8, 255, 255])
            maskB = cv2.inRange(map_rect, lower, upper)

            lower = np.array([150 - 10, 0, 0])
            upper = np.array([150 + 10, 255, 255])
            maskM = cv2.inRange(map_rect, lower, upper)

            lower = np.array([90 - 8, 0, 0])
            upper = np.array([90 + 8, 255, 255])
            maskL = cv2.inRange(map_rect, lower, upper)

            lower = np.array([30 - 4, 0, 0])
            upper = np.array([30 + 4, 255, 255])
            maskY = cv2.inRange(map_rect, lower, upper)

            lower = np.array([11 - 8, 90, 160])
            upper = np.array([11 + 3, 255, 255])
            maskO = cv2.inRange(map_rect, lower, upper)
            for _ in range(0, 3): maskO = cv2.dilate(maskO, ker)
            for _ in range(0, 3): maskO = cv2.erode(maskO, ker)

        cmasks = [maskB, maskL, maskM, maskY]
        cmasks = list(
            map(lambda m: np.pad(cv2.bitwise_and(maskSV, m), pad_width=50, mode="constant", constant_values=0), cmasks))
        centers_rect = np.zeros_like(maskSV)
        x_centers = []
        y_centers = []
        x_grid_step = 96
        y_grid_step = 100
        defined_cm = []
        # cv2.imshow(f'mSV', maskSV)
        for i, mask in enumerate(cmasks):
            # cv2.imshow(f'm{i}', mask)
            for t_i in range(0, 4):
                tm_map = cv2.matchTemplate(mask, CM_TEMPLATES[t_i], cv2.TM_CCOEFF_NORMED)
                ret, thresh = cv2.threshold(tm_map, 0.4, 1, cv2.THRESH_BINARY)
                thresh = thresh.astype(np.uint8)
                contours, hierarchy = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                for contour in contours:
                    M = cv2.moments(contour)
                    area = M['m00']
                    if area > 1:
                        cx = (M['m10'] / M['m00'])
                        cy = (M['m01'] / M['m00'])
                        cx += -50 + 25
                        cy += -50 + 25
                        x_centers.append(cx % x_grid_step)
                        y_centers.append(cy % y_grid_step)
                        defined_cm.append(ColorMark(i, t_i, cx, cy))
                        try:
                            centers_rect[int(cy), int(cx)] = 255
                        except:
                            pass
        x_centers.sort()
        y_centers.sort()

        grid_shift_x = None
        grid_shift_y = None
        cm_array = [[None] * 5 for _ in range(0, 5)]
        xm = None
        ym = None
        regID = None
        if len(x_centers) > 0:
            # print(x_centers)
            # print(y_centers)
            grid_shift_x = x_centers[len(x_centers) // 2]
            grid_shift_y = y_centers[len(y_centers) // 2]
            grid_shift_x = round(grid_shift_x)
            grid_shift_y = round(grid_shift_y)
            for x in range(0, 5):
                for y in range(0, 5):
                    for cm in defined_cm:
                        cx = grid_shift_x - x_grid_step + x_grid_step * x
                        cy = grid_shift_y - y_grid_step + y_grid_step * y
                        if abs(cm.x - cx) < 10 and abs(cm.y - cy) < 10:
                            cm_array[x][y] = cm
                            break
            RegID = -1
            is_Achtung = False
            for x in range(0, 5 - 1):
                for y in range(0, 5 - 1):
                    cms = (cm_array[x][y], cm_array[x + 1][y], cm_array[x][y + 1], cm_array[x + 1][y + 1])
                    if cms.count(None) == 0:
                        signature = tuple(map(lambda cm: cm.get_signature(), cms))
                        regID = Rsig_regID[signature]
                        pos = Rsig_nwP_grid_pos[signature]
                        for sx in (0, 1):
                            for sy in (0, 1):
                                if cm_array[x + sx][y + sy].pos != None and cm_array[x + sx][y + sy].pos != (
                                pos[0] + sx, pos[1] + sy):
                                    is_Achtung = True
                                cm_array[x + sx][y + sy].pos = (pos[0] + sx, pos[1] + sy)
                        if RegID != -1 and RegID != regID:
                            is_Achtung = True
                        RegID = regID
            if is_Achtung:
                print("ACHTUNG")
                # TODO

            centers_rect = cv2.cvtColor(centers_rect, cv2.COLOR_GRAY2RGB)
            for i in range(0, 5):
                for j in range(0, 5):
                    cx = grid_shift_x - x_grid_step + x_grid_step * i
                    cy = grid_shift_y - y_grid_step + y_grid_step * j
                    Y = toBGR("#FFFF00FF")
                    B = toBGR("#0000FFFF")
                    L = toBGR("#00FFFFFF")
                    M = toBGR("#FF00FFFF")

                    CLs = (B, L, M, Y)

                    Rs = (12, 15, 18, 21)
                    if cm_array[i][j] is None: continue

                    outer_radius = Rs[cm_array[i][j].r_id] if not cm_array[i][j].r_id is None else 5
                    cv2.circle(centers_rect, center=(cx, cy), radius=outer_radius, color=CLs[cm_array[i][j].cl_id],
                               thickness=2)

            # Maask O
            contours, hierarchy = cv2.findContours(maskO, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            maskO = cv2.cvtColor(maskO, cv2.COLOR_GRAY2BGR)

            candidates_for_pm = []
            for contour in contours:
                M = cv2.moments(contour)
                area = M['m00']
                if area > 40:
                    cx = (M['m10'] / M['m00'])
                    cy = (M['m01'] / M['m00'])
                    cx, cy = round(cx), round(cy)
                    candidates_for_pm.append((cx, cy))
                    maskO = cv2.circle(maskO, (cx, cy), 2, (0, 0, 255))
            candidates_for_pm.sort(key=lambda c: abs(c[0] * math.sqrt(3)) + abs(c[1]))

            if candidates_for_pm:
                playermark = candidates_for_pm[0]
                if math.dist(playermark, (162, 162)) < 4:
                    playermark = (162, 162)
                maskO = cv2.circle(maskO, playermark, 2, (255, 0, 0))
            else:
                playermark = (162, 162)
            centers_rect = cv2.circle(centers_rect, playermark, 2, (255, 0, 0))
            # cv2.imshow("o", (maskO))

            cm_list = [item for row in cm_array for item in row]
            while None in cm_list:
                cm_list.remove(None)
            cm_list.sort(key=lambda cm: math.dist(playermark, (cm.x, cm.y)))
            while cm_list and cm_list[0].pos is None:
                cm_list.pop(0)
            if cm_list:
                # cm_list[0]
                shift = (playermark[0] - cm_list[0].x, playermark[1] - cm_list[0].y)
                m_per_pix = 2184 / 1024
                w, h = 1024, 888
                step_x = w / 11
                step_y = h / 9
                cx = (cm_list[0].pos[0] + 0.5) * step_x
                cy = (cm_list[0].pos[1] + 0.5) * step_y
                pix_pos = shift[0] + cx, shift[1] + cy
                # pix_pos =  cx,cy
                # self.x_m = pix_pos[0]*m_per_pix
                # self.y_m = pix_pos[1]*m_per_pix
                xm = pix_pos[0] * m_per_pix
                ym = pix_pos[1] * m_per_pix
                # print(pix_pos)
                regID = RegID
                # self.RegID = RegID

        if regID is None or regID < -1:
            regID = self.mark.regID

            # print('LOL')
        spd = None
        fuel = None
        alt = None
        dir = None

        def get_sensor_bar(y, x1, x2):
            sensor_img = frame[y:y + 1, x1: x2]
            sensor_gray = cv2.cvtColor(sensor_img, cv2.COLOR_BGR2GRAY)
            ret, binary = cv2.threshold(sensor_gray, 200, 255, cv2.THRESH_BINARY)

            masked = binary
            white_pixels = np.argwhere(masked > 0)
            if len(white_pixels) > 0:
                lvl_x = np.max(white_pixels[:, 1])

                return float(lvl_x / (x2 - x1))
            return None

        def get_sensor_angle(sensor_center):
            sensor_r = 64
            cx, cy = sensor_center
            sensor_img = frame[cy - sensor_r: cy + sensor_r + 1,
                         cx - sensor_r: cx + sensor_r + 1]
            sensor_gray = cv2.cvtColor(sensor_img, cv2.COLOR_BGR2GRAY)
            ret, binary = cv2.threshold(sensor_gray, 200, 255, cv2.THRESH_BINARY)
            center = (sensor_r + sensor_r + 1) // 2

            mask = np.zeros((sensor_r * 2 + 1, sensor_r * 2 + 1), dtype=np.uint8)
            cv2.circle(mask, (center, center), 30, 255, 2)

            masked = cv2.bitwise_and(binary, binary, mask=mask)
            # cv2.imshow('alt',masked)
            white_pixels = np.argwhere(masked > 0)
            if len(white_pixels) > 0:
                centroid_y = np.mean(white_pixels[:, 0])
                centroid_x = np.mean(white_pixels[:, 1])
                dx = centroid_x - center
                dy = centroid_y - center
                angle_rad = np.arctan2(dy, dx)
                angle_deg = np.degrees(angle_rad)
                angle_deg_positive = ((angle_deg + 360 + 90) % 360)
                return angle_deg_positive
            return None

        def get_compass_orientation(sensor_center):
            sensor_r = 64
            cx, cy = sensor_center
            sensor_img = hsv_frame[cy - sensor_r: cy + sensor_r + 1,
                         cx - sensor_r: cx + sensor_r + 1]
            lower = np.array([11 - 8, 90, 160])
            upper = np.array([11 + 3, 255, 255])
            binary = cv2.inRange(sensor_img, lower, upper)
            center = (sensor_r + sensor_r + 1) // 2
            # cv2.imshow('bin', binary)
            mask = np.zeros((sensor_r * 2 + 1, sensor_r * 2 + 1), dtype=np.uint8)
            cv2.circle(mask, (center, center), 47, 255, 2)

            masked = cv2.bitwise_and(binary, binary, mask=mask)
            # cv2.imshow('comp',masked)
            white_pixels = np.argwhere(masked > 0)
            if len(white_pixels) > 0:
                centroid_y = np.mean(white_pixels[:, 0])
                centroid_x = np.mean(white_pixels[:, 1])
                dx = centroid_x - center
                dy = centroid_y - center
                angle_rad = np.arctan2(dy, dx)
                angle_deg = np.degrees(angle_rad)
                angle_deg_positive = ((angle_deg + 360 + 90) % 360)
                return angle_deg_positive
            return None

        if self.is_in_plane:
            alt = get_sensor_angle(alt_sensor_pos)
            if alt:
                alt = float(alt / 360 * 100)
            spd = get_sensor_angle(spd_sensor_pos)
            if spd:
                knots_to_ms = 1 / 6.81
                spd = float(spd / 360 * 200 * knots_to_ms)
            compass_center_pos = (1830, 89)
            cam_dir = get_sensor_angle(compass_center_pos)
            comp_dir = get_compass_orientation(compass_center_pos)
            if comp_dir and cam_dir:
                dir = float((cam_dir - comp_dir + 360) % 360)
            fuel = get_sensor_bar(130, 22, 167)

        if self.is_in_plane:
            try:
                # print(xm,ym,regID,dir,spd,fuel,alt)
                if spd is None or alt is None:
                    is_landed = self.mark.is_landed
                else:
                    is_landed = (spd * 6.81 < 50 and alt < 20) or spd * 6.81 < 30 or alt < 10

                self.mark.update_data(xm, ym, regID, dir, spd, fuel, alt, is_landed, False)  # TODO land
            except:
                import logging
                logging.exception("")

        # cv2.imshow(f"crect", centers_rect)
        cl_mask = cv2.bitwise_or(cv2.bitwise_or(maskB, maskM), cv2.bitwise_or(maskL, maskY))
        mask = cv2.bitwise_and(maskSV, cl_mask)


class ScreenStreamer:
    def __init__(self):
        self.camera = dxcam.create()

    def read(self):
        frame_rgb = self.camera.grab()
        if frame_rgb is None:
            return None

        return cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

    def by_by(self):
        self.camera.release()


class VideoStreamer:
    def __init__(self, video_path, fps=30):
        self.cap = cv2.VideoCapture(video_path)
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))

        self.window_name = "Video Player "
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)

        self.target_frame = None  # кадр, на который нужно перемотать (если не None)
        self.delay = int(1000 / fps)
        cv2.createTrackbar("Position", self.window_name, 0, self.total_frames - 1, self.on_trackbar)

    def on_trackbar(self, pos):
        self.target_frame = pos

    def read(self):
        if self.target_frame is not None:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.target_frame)
            target_frame = None

        ret, frame = self.cap.read()
        if not ret:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            return

        info_frame = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
        status = "PLAY"
        view_frame = frame.copy()
        info_text = f"Frame: {info_frame}/{self.total_frames} | {status}"
        cv2.putText(view_frame, info_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (0, 255, 0), 2)

        cv2.imshow(self.window_name, view_frame)

        current_frame = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
        cv2.setTrackbarPos("Position", self.window_name, current_frame)

        wait_ms = self.delay
        return frame

    def by_by(self):
        pass


import tkinter as tk
import sys


def get_user_info():
    """
    Opens a simple tkinter window with name and discord fields.
    The 'Continue' button is disabled until both fields are non-empty.
    If the window is closed, the program exits.
    Returns a tuple (name, discord).
    """
    root = tk.Tk()
    root.title("User Info")

    # Variables to hold the input
    name_var = tk.StringVar()
    discord_var = tk.StringVar()

    # Store the result after the user presses Continue
    result = []

    def check_fields(*args):
        """Enable the Continue button only when both fields are non-empty."""
        if name_var.get().strip() and discord_var.get().strip():
            continue_btn.config(state='normal')
        else:
            continue_btn.config(state='disabled')

    def on_continue():
        """Called when the Continue button is pressed."""
        result.append(name_var.get().strip())
        result.append(discord_var.get().strip())
        root.destroy()

    def on_close():
        """Called when the window is closed via the X button."""
        sys.exit(0)  # Stop the entire program

    # GUI layout
    tk.Label(root, text="Name:").grid(row=0, column=0, padx=10, pady=5, sticky='e')
    tk.Entry(root, textvariable=name_var).grid(row=0, column=1, padx=10, pady=5)

    tk.Label(root, text="Discord:").grid(row=1, column=0, padx=10, pady=5, sticky='e')
    tk.Entry(root, textvariable=discord_var).grid(row=1, column=1, padx=10, pady=5)

    continue_btn = tk.Button(root, text="Continue", command=on_continue, state='disabled')
    continue_btn.grid(row=2, column=0, columnspan=2, pady=10)

    # Trace changes in the entry fields to update button state
    name_var.trace_add('write', check_fields)
    discord_var.trace_add('write', check_fields)
    name_var.set("BRO_Fedka")
    discord_var.set("bro_fedka")
    # Handle window close event
    root.protocol("WM_DELETE_WINDOW", on_close)

    # Start the GUI loop
    root.mainloop()

    # If we reach here, the user pressed Continue (root.destroy was called)
    return tuple(result)


def main():
    global sending_data
    user_info = get_user_info()
    udp_thread = threading.Thread(target=udp_client, daemon=True)
    udp_thread.start()

    user = User(user_info[0])
    streamer = ScreenStreamer() # VideoStreamer('E:\FFGIS\data/video.mp4')
    processor = Processor(user)

    while True:
        frame = streamer.read()

        processor.process(frame)
        sending_data = processor.get_data()

        cv2.waitKey(16)

    streamer.by_by()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
