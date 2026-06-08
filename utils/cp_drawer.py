import pickle
import math

with open('matrices_data.pkl', 'rb') as f:
    Rsig_regID, Rsig_nwP_grid_pos, regID_array_Rsigs, regID_array_Psigs = pickle.load(f)

import os
import sys
from PIL import Image, ImageDraw

mask = Image.new("L", (1024, 888), 0)
mask_draw = ImageDraw.Draw(mask)
hex_radius_ratio = 1 / math.sqrt(3)
center_x = 1024 / 2
center_y = 888 / 2
radius = min(1024, 888) * hex_radius_ratio
vertices = []
for i in range(6):
    angle_deg = i * 60
    angle_rad = math.radians(angle_deg)
    x = center_x + radius * math.cos(angle_rad)
    y = center_y + radius * math.sin(angle_rad)
    vertices.append((x, y))
mask_draw.polygon(vertices, fill=255)
black_bg = Image.new("RGBA", (1024, 888), "#00000000")

# CL list
Y = "#FFFF00FF"
B = "#0000FFFF"
L = "#00FFFFFF"
M = "#FF00FFFF"

CLs = (B, L, M, Y)

Rs = (12, 15, 18, 21)

hor_KPs = 11
vert_KPs = 9
REG_Amount = 55
#
# def draw_markers_on_image(image_path, output_path, grid_cols=11, grid_rows=9, marker_color="red", outline_width=2):


input_folder = "../testfolder"
output_folder = "../marked"

files = [f for f in os.listdir(input_folder) if f.lower().endswith(".tga")]

files.sort()

for regID in range(0, REG_Amount):
    input_path = os.path.join(input_folder, files[regID])
    output_path = os.path.join(output_folder, files[regID])
    # draw_markers_on_image(input_path, output_path.replace('.tga','.png'))

    img = Image.open(input_path).convert("RGBA")  # переводим в RGB, чтобы избежать проблем с альфа-каналом

    draw = ImageDraw.Draw(img)
    width, height = img.size

    step_x = width / hor_KPs
    step_y = height / vert_KPs

    for i in range(hor_KPs):  # столбцы
        for j in range(vert_KPs):  # строки
            cx = (i + 0.5) * step_x
            cy = (j + 0.5) * step_y
            outer_radius = Rs[regID_array_Psigs[regID][i][j][0]]
            draw.ellipse(
                [cx - outer_radius, cy - outer_radius, cx + outer_radius, cy + outer_radius],
                outline=CLs[regID_array_Psigs[regID][i][j][1]],
                width=2
            )
            # inner_radius = 9
            # draw.ellipse(
            #     [cx - inner_radius, cy - inner_radius, cx + inner_radius, cy + inner_radius],
            #     fill='#ffffff'
            # )
    img = Image.composite(img, black_bg, mask)
    img.save(output_path.replace('.tga', '.png'), format="PNG")
    print(f"Обработано: {os.path.basename(input_path)} -> {output_path}")
