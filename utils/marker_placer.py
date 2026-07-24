from typing import NamedTuple
import random

random.seed(0)
CAM_RECT = (300, 300)

hor_KPs = 11
vert_KPs = 9
REG_Amount = 55
Rsig_regID = {}
Rsig_nwP_grid_pos = {}
regID_array_Rsigs = {}
regID_array_Psigs = {}
for regID in range(REG_Amount):
    regID_array_Rsigs[regID] = [[None] * (vert_KPs - 1) for _ in range(0, hor_KPs - 1)]

for regID in range(REG_Amount):
    regID_array_Psigs[regID] = [[None] * (vert_KPs) for _ in range(0, hor_KPs)]

VALUES = list(range(16))


def Rsig_via_nums(nwpsig, nepsig, swpsig, sepsig):
    return ((nwpsig // 4, nwpsig % 4), (nepsig // 4, nepsig % 4), (swpsig // 4, swpsig % 4), (sepsig // 4, sepsig % 4))


attempts = 0
while True:
    attempts += 1
    matrices = []
    used_blocks = set()
    failed = False

    for regID in range(REG_Amount):
        matrix = [[0] * hor_KPs for _ in range(vert_KPs)]
        for y in range(vert_KPs):
            for x in range(hor_KPs):
                if y > 0 and x > 0:
                    v1 = matrix[y - 1][x - 1]
                    v2 = matrix[y - 1][x]
                    v3 = matrix[y][x - 1]

                    allowed = []
                    for val in VALUES:
                        block = (v1, v2, v3, val)
                        if block not in used_blocks:
                            allowed.append(val)

                    if not allowed:
                        failed = True
                        break

                    val = random.choice(allowed)
                else:
                    val = random.choice(VALUES)

                matrix[y][x] = val
                regID_array_Psigs[regID][x][y] = (val // 4, val % 4)

                if y > 0 and x > 0:
                    block = (matrix[y - 1][x - 1], matrix[y - 1][x],
                             matrix[y][x - 1], matrix[y][x])
                    used_blocks.add(block)
                    rsig = Rsig_via_nums(matrix[y - 1][x - 1], matrix[y - 1][x], matrix[y][x - 1], matrix[y][x])
                    Rsig_regID[rsig] = regID
                    Rsig_nwP_grid_pos[rsig] = (x - 1, y - 1)
                    regID_array_Rsigs[regID][x - 1][y - 1] = rsig

            if failed:
                break
        if failed:
            break

    if not failed:
        break

import pickle

# ... ваш исходный код ...

# После завершения цикла while (успешная генерация)
print(attempts, len(used_blocks))
# Сохраняем оба словаря в один файл
with open('matrices_data.pkl', 'wb') as f:
    pickle.dump((Rsig_regID, Rsig_nwP_grid_pos, regID_array_Rsigs, regID_array_Psigs), f)

print("Словари сохранены в 'matrices_data.pkl'")
