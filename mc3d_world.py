"""3D 마인크래프트 - 월드 모듈

상수, 블록/아이템 정의, 조합법, 끝없이 이어지는 시드 기반 지형 생성(World),
블록 질의(충돌·시야·레이캐스트), 청크 단위 렌더러(디스플레이 리스트)를 담당한다.
"""
import ctypes
import math
import random
import time
from array import array

import OpenGL
OpenGL.ERROR_CHECKING = False      # 어느 모듈이 먼저 불러도 GL 오류 검사는 끈다 (속도)
from OpenGL.GL import *
from OpenGL.raw.GL.VERSION.GL_1_1 import glVertexPointer as _gl_vertex_ptr, glColorPointer as _gl_color_ptr, \
    glNormalPointer as _gl_normal_ptr, glTexCoordPointer as _gl_tex_ptr, glDrawArrays as _gl_draw_arrays
from OpenGL.raw.GL.VERSION.GL_1_4 import glSecondaryColorPointer as _gl_lcol_ptr
from OpenGL.raw.GL.VERSION.GL_1_5 import glBindBuffer as _gl_bind_buffer
from itertools import chain

# ==============================================================================
# 1. 기본 설정
# ==============================================================================
SCREEN_WIDTH = 1000
SCREEN_HEIGHT = 650
FPS = 60

WORLD_H = 1280        # Y축 높이 (가로 방향은 끝없이 이어진다)
SEA_LEVEL = 48        # 해수면 높이
SNOW_LINE = SEA_LEVEL + 105  # 이보다 높은 산꼭대기는 눈
GEN_CHUNK = 16                       # 지형 생성·저장 청크 한 변 (16×16 기둥)
CHUNK_SIZE = 8                       # 렌더링 청크 한 변
RENDER_DISTANCE = 11                 # 플레이어 주변 몇 렌더링 청크까지 그릴지
LOAD_RADIUS = (RENDER_DISTANCE + 1) * CHUNK_SIZE // GEN_CHUNK + 1   # 몇 생성 청크까지 미리 만들지
DAY_LENGTH = 360.0                   # 낮+밤 한 바퀴 (초)
SAVE_VERSION = 8

# ------------------------------------------------------------------------------
# 블록 ID
# ------------------------------------------------------------------------------
AIR = 0
GRASS = 1
DIRT = 2
STONE = 3
WOOD = 4
LEAVES = 5
COAL_ORE = 6
IRON_ORE = 7
BRICK = 8
GLASS = 9
BEDROCK = 10
WATER = 11
SAND = 12
PLANKS = 13
WORKBENCH = 14
TORCH = 15
DIAMOND_ORE = 16
CACTUS = 17
SNOW = 18
CLAY = 19
GOLD_ORE = 20
GRAVEL = 21
SANDSTONE = 22
TALL_GRASS = 23
FLOWER_RED = 24
FLOWER_YELLOW = 25
LANTERN = 26
TNT = 27
CRYSTAL = 28
ICE = 29
GLOW_MOSS = 30       # 판도라 같은 발광 생태계
GLOW_VINE = 31
GLOW_SHROOM = 32
SPIRAL_PLANT = 33
LUMEN_ORE = 34
GLOW_CAP = 35
SHROOM_STEM = 36
LUMEN_LAMP = 37

# 아이템 ID (인벤토리 및 도구)
STICK = 101
WOOD_PICKAXE = 102
STONE_PICKAXE = 103
IRON_PICKAXE = 104
DIAMOND_PICKAXE = 105
WOOD_SWORD = 106
STONE_SWORD = 107
IRON_SWORD = 108
DIAMOND_SWORD = 109
PORK_RAW = 110
PORK_COOKED = 111
APPLE = 112
DIAMOND = 113
ROTTEN_FLESH = 114
IRON_INGOT = 115
GOLD_INGOT = 116
GOLDEN_APPLE = 117
WOOD_AXE = 118
STONE_AXE = 119
IRON_AXE = 120
DIAMOND_AXE = 121
IRON_ARMOR = 122
DIAMOND_ARMOR = 123
GUNPOWDER = 124
GLOW_BERRY = 125

DECOR_BLOCKS = {TALL_GRASS, FLOWER_RED, FLOWER_YELLOW}  # 풀·꽃: 지나갈 수 있고, 블록을 놓으면 덮어쓴다
GLOW_PLANTS = {GLOW_MOSS, GLOW_VINE, GLOW_SHROOM, SPIRAL_PLANT}    # 빛나는 식물: 지나갈 수 있다
LIGHT_BLOCKS = {TORCH: 9, LANTERN: 14, CRYSTAL: 8, GLOW_MOSS: 4, GLOW_VINE: 6, GLOW_SHROOM: 7,  # 빛을 내는 블록과
                SPIRAL_PLANT: 6, LUMEN_ORE: 6, GLOW_CAP: 6, LUMEN_LAMP: 14}                   # 빛이 닿는 거리
LIGHT_COLORS = {                    # 블록마다 다른 빛 색
    TORCH: (1.0, 0.72, 0.42), LANTERN: (1.0, 0.78, 0.5), CRYSTAL: (0.75, 0.5, 1.0),
    GLOW_MOSS: (0.25, 0.95, 0.85), GLOW_VINE: (0.3, 0.7, 1.0), GLOW_SHROOM: (0.85, 0.35, 1.0),
    SPIRAL_PLANT: (1.0, 0.45, 0.35), LUMEN_ORE: (0.35, 0.75, 1.0), GLOW_CAP: (0.45, 0.55, 1.0),
    LUMEN_LAMP: (0.7, 0.95, 1.0),
}
WARM_LIGHT = LIGHT_COLORS[TORCH]
LIGHT_SPARSE = {GLOW_MOSS: 4, GLOW_VINE: 3, GLOW_SHROOM: 2, GLOW_CAP: 8, LUMEN_ORE: 3}   # 무리 지어 있는 광원은 몇 개 중 하나만 계산 (최적화)
NON_SOLID_BLOCKS = {AIR, WATER, TORCH, LANTERN, CRYSTAL} | DECOR_BLOCKS | GLOW_PLANTS   # 통과 가능한 블록 (충돌 없음)
TRANSPARENT_BLOCKS = {AIR, WATER, GLASS, LEAVES, TORCH, LANTERN, CRYSTAL} | DECOR_BLOCKS | GLOW_PLANTS   # 시선을 가리지 않는 블록
GRAVITY_BLOCKS = {SAND, GRAVEL, WOOD, CACTUS}           # 받침이 사라지면 떨어지는 블록
NEEDS_GROUND = {TORCH, LANTERN, CRYSTAL, GLOW_SHROOM, SPIRAL_PLANT} | DECOR_BLOCKS  # 받침이 사라지면 부서지는 블록
PICKAXE_BLOCKS = {STONE, COAL_ORE, IRON_ORE, GOLD_ORE, DIAMOND_ORE, BRICK, CLAY, SANDSTONE, ICE, LUMEN_ORE, LUMEN_LAMP}  # 곡괭이로 빨라짐
AXE_BLOCKS = {WOOD, PLANKS, WORKBENCH, LEAVES, CACTUS, SHROOM_STEM, GLOW_CAP}  # 도끼로 빨라지는 블록

# 블록별 채굴 소요 시간 (초, 맨손 기준)
BLOCK_MINING_TIME = {
    LEAVES: 0.25, GLASS: 0.35, TORCH: 0.1, SAND: 0.6, DIRT: 0.75, GRASS: 0.85,
    CACTUS: 0.6, SNOW: 0.4, CLAY: 2.5, PLANKS: 1.4, WORKBENCH: 1.8, WOOD: 2.2, BRICK: 3.0, STONE: 4.5,
    COAL_ORE: 5.0, IRON_ORE: 6.5, GOLD_ORE: 7.0, DIAMOND_ORE: 9.0,
    GRAVEL: 0.7, SANDSTONE: 3.5, TALL_GRASS: 0.05, FLOWER_RED: 0.05, FLOWER_YELLOW: 0.05,
    LANTERN: 0.5, TNT: 0.3, CRYSTAL: 1.2, ICE: 1.5,
    GLOW_MOSS: 0.1, GLOW_VINE: 0.15, GLOW_SHROOM: 0.05, SPIRAL_PLANT: 0.05, LUMEN_ORE: 5.5, GLOW_CAP: 0.5,
    SHROOM_STEM: 1.5, LUMEN_LAMP: 0.6,
    BEDROCK: math.inf, WATER: math.inf, AIR: math.inf,
}

# 곡괭이 채굴 속도 배율
PICKAXE_POWER = {WOOD_PICKAXE: 2.5, STONE_PICKAXE: 5.0, IRON_PICKAXE: 8.5, DIAMOND_PICKAXE: 14.0}

# 도끼 채굴 속도 배율 (원목·목재·나뭇잎)
AXE_POWER = {WOOD_AXE: 2.5, STONE_AXE: 4.0, IRON_AXE: 6.0, DIAMOND_AXE: 9.0}

# 무기 공격력 (맨손은 1). 도끼도 꽤 아프다
WEAPON_DAMAGE = {WOOD_SWORD: 3, STONE_SWORD: 5, IRON_SWORD: 8, DIAMOND_SWORD: 12,
                 WOOD_AXE: 3, STONE_AXE: 4, IRON_AXE: 6, DIAMOND_AXE: 9}

# 갑옷: 인벤토리에 있으면 몹·폭발·떨어진 블록 피해를 이 비율만큼 줄인다 (가장 좋은 것 하나)
ARMOR_REDUCTION = {IRON_ARMOR: 0.4, DIAMOND_ARMOR: 0.6}

# 음식 허기 회복량 (황금 사과는 체력도 8 회복)
FOOD_VALUES = {PORK_RAW: 3, PORK_COOKED: 8, APPLE: 4, ROTTEN_FLESH: 2, GOLDEN_APPLE: 4, GLOW_BERRY: 5}

ITEM_NAMES = {
    AIR: "빈 칸", GRASS: "잔디 블록", DIRT: "흙", STONE: "돌", WOOD: "참나무 원목 (중력)",
    LEAVES: "나뭇잎", COAL_ORE: "석탄 광석", IRON_ORE: "철 광석", BRICK: "벽돌", GLASS: "유리",
    BEDROCK: "기반암", WATER: "물", SAND: "모래 (중력)", PLANKS: "참나무 목재", WORKBENCH: "작업대",
    TORCH: "횃불", DIAMOND_ORE: "다이아몬드 광석", CACTUS: "선인장 (접촉 피해)",
    SNOW: "눈", CLAY: "붉은 점토", GOLD_ORE: "금 광석", GRAVEL: "자갈 (중력)", SANDSTONE: "사암",
    TALL_GRASS: "키 큰 풀", FLOWER_RED: "양귀비", FLOWER_YELLOW: "민들레", LANTERN: "랜턴 (밝은 빛)",
    TNT: "TNT (우클릭으로 점화)", CRYSTAL: "빛나는 수정", ICE: "얼음",
    GLOW_MOSS: "발광 이끼 (어디든 붙음)", GLOW_VINE: "발광 덩굴 (천장에 매닮)", GLOW_SHROOM: "발광 버섯",
    SPIRAL_PLANT: "나선초 (빛나는 풀)", LUMEN_ORE: "루멘 광석 (푸른 빛)", GLOW_CAP: "발광 버섯갓",
    SHROOM_STEM: "거대 버섯 줄기", LUMEN_LAMP: "루멘 등 (밝은 빛)", GLOW_BERRY: "빛열매 (허기 +5)",
    STICK: "막대기", WOOD_PICKAXE: "나무 곡괭이 (x2.5)", STONE_PICKAXE: "돌 곡괭이 (x5)",
    IRON_PICKAXE: "철 곡괭이 (x8.5)", DIAMOND_PICKAXE: "다이아 곡괭이 (x14)",
    WOOD_SWORD: "나무 검 (공격력 3)", STONE_SWORD: "돌 검 (공격력 5)",
    IRON_SWORD: "철 검 (공격력 8)", DIAMOND_SWORD: "다이아 검 (공격력 12)",
    PORK_RAW: "생 돼지고기 (허기 +3)", PORK_COOKED: "구운 돼지고기 (허기 +8)",
    APPLE: "사과 (허기 +4)", DIAMOND: "다이아몬드", ROTTEN_FLESH: "썩은 살점 (허기 +2)",
    IRON_INGOT: "철괴", GOLD_INGOT: "금괴", GOLDEN_APPLE: "황금 사과 (허기 +4, 체력 +8)",
    WOOD_AXE: "나무 도끼 (나무 x2.5)", STONE_AXE: "돌 도끼 (나무 x4)", IRON_AXE: "철 도끼 (나무 x6)",
    DIAMOND_AXE: "다이아 도끼 (나무 x9)", IRON_ARMOR: "철 갑옷 (피해 -40%)",
    DIAMOND_ARMOR: "다이아 갑옷 (피해 -60%)", GUNPOWDER: "화약",
}

# 블록 색상: 단색 또는 (윗면, 옆면)
BLOCK_COLORS = {
    GRASS: ((0.33, 0.47, 0.22), (0.40, 0.31, 0.22)),
    DIRT: (0.40, 0.31, 0.22),
    STONE: (0.50, 0.49, 0.47),
    WOOD: ((0.58, 0.46, 0.32), (0.33, 0.25, 0.18)),
    LEAVES: (0.22, 0.36, 0.16),
    COAL_ORE: (0.30, 0.30, 0.30),
    IRON_ORE: (0.62, 0.55, 0.49),
    BRICK: (0.58, 0.32, 0.26),
    GLASS: (0.78, 0.86, 0.90),
    BEDROCK: (0.20, 0.20, 0.20),
    WATER: (0.13, 0.30, 0.40),
    SAND: (0.80, 0.73, 0.56),
    PLANKS: (0.66, 0.52, 0.36),
    WORKBENCH: ((0.62, 0.48, 0.32), (0.48, 0.35, 0.23)),
    TORCH: (0.95, 0.75, 0.30),
    DIAMOND_ORE: (0.42, 0.70, 0.72),
    CACTUS: ((0.36, 0.50, 0.30), (0.29, 0.43, 0.25)),
    SNOW: (0.90, 0.92, 0.95),
    CLAY: (0.68, 0.45, 0.34),
    GOLD_ORE: (0.74, 0.65, 0.40),
    GRAVEL: (0.48, 0.46, 0.44),
    SANDSTONE: ((0.80, 0.72, 0.55), (0.74, 0.65, 0.49)),
    TALL_GRASS: (0.36, 0.50, 0.22),
    FLOWER_RED: (0.72, 0.18, 0.16),
    FLOWER_YELLOW: (0.88, 0.76, 0.26),
    LANTERN: (0.98, 0.80, 0.45),
    TNT: ((0.80, 0.78, 0.74), (0.68, 0.24, 0.18)),
    CRYSTAL: (0.66, 0.52, 0.90),
    ICE: (0.70, 0.82, 0.90),
    GLOW_MOSS: (0.30, 0.95, 0.85),
    GLOW_VINE: (0.35, 0.75, 1.0),
    GLOW_SHROOM: (0.82, 0.40, 1.0),
    SPIRAL_PLANT: (1.0, 0.50, 0.38),
    LUMEN_ORE: (0.36, 0.62, 0.82),
    GLOW_CAP: ((0.28, 0.30, 0.60), (0.20, 0.17, 0.40)),
    SHROOM_STEM: ((0.80, 0.80, 0.74), (0.72, 0.72, 0.68)),
    LUMEN_LAMP: (0.75, 0.95, 1.0),
}
BLOCK_ALPHA = {WATER: 0.55, GLASS: 0.4}   # 반투명 블록

# 블록이 아닌 아이템의 아이콘 색
ITEM_COLORS = {
    STICK: (0.55, 0.38, 0.2),
    WOOD_PICKAXE: (0.7, 0.52, 0.3), WOOD_SWORD: (0.7, 0.52, 0.3),
    STONE_PICKAXE: (0.6, 0.6, 0.6), STONE_SWORD: (0.6, 0.6, 0.6),
    IRON_PICKAXE: (0.88, 0.88, 0.88), IRON_SWORD: (0.88, 0.88, 0.88),
    DIAMOND_PICKAXE: (0.35, 0.92, 0.92), DIAMOND_SWORD: (0.35, 0.92, 0.92),
    PORK_RAW: (0.95, 0.6, 0.6), PORK_COOKED: (0.7, 0.42, 0.25), APPLE: (0.85, 0.12, 0.12),
    DIAMOND: (0.4, 0.95, 0.95), ROTTEN_FLESH: (0.55, 0.45, 0.2),
    IRON_INGOT: (0.85, 0.85, 0.88), GOLD_INGOT: (0.98, 0.82, 0.25), GOLDEN_APPLE: (1.0, 0.8, 0.2),
    WOOD_AXE: (0.7, 0.52, 0.3), STONE_AXE: (0.6, 0.6, 0.6), IRON_AXE: (0.88, 0.88, 0.88),
    DIAMOND_AXE: (0.35, 0.92, 0.92), IRON_ARMOR: (0.82, 0.82, 0.86), DIAMOND_ARMOR: (0.35, 0.92, 0.92),
    GUNPOWDER: (0.35, 0.35, 0.38), GLOW_BERRY: (0.35, 0.85, 1.0),
}

# 조합법 ("bench": True 이면 작업대 근처에서만 제작 가능)
RECIPES = [
    {"result": PLANKS, "count": 4, "req": {WOOD: 1}, "name": "목재 x4", "bench": False},
    {"result": STICK, "count": 4, "req": {PLANKS: 2}, "name": "막대기 x4", "bench": False},
    {"result": WORKBENCH, "count": 1, "req": {PLANKS: 4}, "name": "작업대", "bench": False},
    {"result": TORCH, "count": 4, "req": {COAL_ORE: 1, STICK: 1}, "name": "횃불 x4", "bench": False},
    {"result": PORK_COOKED, "count": 1, "req": {PORK_RAW: 1, COAL_ORE: 1}, "name": "구운 돼지고기", "bench": False},
    {"result": GLASS, "count": 1, "req": {SAND: 1, COAL_ORE: 1}, "name": "유리", "bench": True},
    {"result": BRICK, "count": 2, "req": {DIRT: 2, COAL_ORE: 1}, "name": "벽돌 x2", "bench": True},
    {"result": WOOD_PICKAXE, "count": 1, "req": {PLANKS: 3, STICK: 2}, "name": "나무 곡괭이", "bench": True},
    {"result": WOOD_SWORD, "count": 1, "req": {PLANKS: 2, STICK: 1}, "name": "나무 검", "bench": True},
    {"result": STONE_PICKAXE, "count": 1, "req": {STONE: 3, STICK: 2}, "name": "돌 곡괭이", "bench": True},
    {"result": STONE_SWORD, "count": 1, "req": {STONE: 2, STICK: 1}, "name": "돌 검", "bench": True},
    {"result": IRON_PICKAXE, "count": 1, "req": {IRON_ORE: 3, STICK: 2}, "name": "철 곡괭이", "bench": True},
    {"result": IRON_SWORD, "count": 1, "req": {IRON_ORE: 2, STICK: 1}, "name": "철 검", "bench": True},
    {"result": DIAMOND_PICKAXE, "count": 1, "req": {DIAMOND: 3, STICK: 2}, "name": "다이아 곡괭이", "bench": True},
    {"result": DIAMOND_SWORD, "count": 1, "req": {DIAMOND: 2, STICK: 1}, "name": "다이아 검", "bench": True},
    {"result": IRON_INGOT, "count": 1, "req": {IRON_ORE: 1, COAL_ORE: 1}, "name": "철괴 (제련)", "bench": True},
    {"result": GOLD_INGOT, "count": 1, "req": {GOLD_ORE: 1, COAL_ORE: 1}, "name": "금괴 (제련)", "bench": True},
    {"result": GOLDEN_APPLE, "count": 1, "req": {APPLE: 1, GOLD_INGOT: 4}, "name": "황금 사과", "bench": True},
    {"result": LANTERN, "count": 1, "req": {IRON_INGOT: 1, TORCH: 1}, "name": "랜턴", "bench": True},
    {"result": TNT, "count": 1, "req": {GUNPOWDER: 4, SAND: 4}, "name": "TNT", "bench": True},
    {"result": SANDSTONE, "count": 1, "req": {SAND: 4}, "name": "사암", "bench": False},
    {"result": WOOD_AXE, "count": 1, "req": {PLANKS: 3, STICK: 2}, "name": "나무 도끼", "bench": True},
    {"result": STONE_AXE, "count": 1, "req": {STONE: 3, STICK: 2}, "name": "돌 도끼", "bench": True},
    {"result": IRON_AXE, "count": 1, "req": {IRON_INGOT: 3, STICK: 2}, "name": "철 도끼", "bench": True},
    {"result": DIAMOND_AXE, "count": 1, "req": {DIAMOND: 3, STICK: 2}, "name": "다이아 도끼", "bench": True},
    {"result": IRON_ARMOR, "count": 1, "req": {IRON_INGOT: 8}, "name": "철 갑옷", "bench": True},
    {"result": DIAMOND_ARMOR, "count": 1, "req": {DIAMOND: 8}, "name": "다이아 갑옷", "bench": True},
    {"result": LUMEN_LAMP, "count": 1, "req": {LUMEN_ORE: 2, GLASS: 1}, "name": "루멘 등", "bench": True},
    {"result": PLANKS, "count": 3, "req": {SHROOM_STEM: 1}, "name": "목재 x3 (버섯 줄기)", "bench": False},
]


def block_face_colors(bid):
    """블록의 (윗면 색, 옆면 색)"""
    col = BLOCK_COLORS.get(bid, (0.6, 0.6, 0.6))
    if isinstance(col[0], tuple):
        return col[0], col[1]
    return col, col


# ==============================================================================
# 2. 월드 생성 - 시드 하나로 기후(온도·습도)와 지형(대륙·침식·능선)을 정하고,
#    그 조합으로 바이옴을 고른다. 노이즈가 좌표 해시로 계산되므로 월드는 끝없이 이어지고,
#    같은 시드면 어느 청크를 언제 만들어도 언제나 같은 지형이 나온다.
# ==============================================================================
BIOME_NAMES = {
    "ocean": "바다", "beach": "해변", "river": "강", "plains": "평원", "forest": "숲",
    "taiga": "타이가", "snowy": "설원", "desert": "사막", "savanna": "사바나", "jungle": "정글",
    "swamp": "늪", "badlands": "악지(메사)", "mountains": "산맥", "glowforest": "발광숲 (판도라)",
}
BIOME_GRASS = {                     # 바이옴마다 다른 풀·잎 색
    "plains": (0.38, 0.50, 0.24), "forest": (0.27, 0.42, 0.19), "taiga": (0.26, 0.38, 0.26),
    "snowy": (0.42, 0.48, 0.40), "savanna": (0.56, 0.52, 0.31), "jungle": (0.24, 0.46, 0.16),
    "swamp": (0.33, 0.37, 0.21), "mountains": (0.36, 0.45, 0.29), "river": (0.35, 0.49, 0.24),
    "beach": (0.40, 0.50, 0.27), "desert": (0.52, 0.52, 0.32), "badlands": (0.52, 0.48, 0.31),
    "ocean": (0.36, 0.48, 0.25), "glowforest": (0.16, 0.30, 0.29),
}
GROUND_COVER = {                    # 바이옴별 (키 큰 풀, 꽃) 확률
    "plains": (0.16, 0.03), "forest": (0.10, 0.012), "savanna": (0.22, 0.004), "jungle": (0.24, 0.006),
    "taiga": (0.06, 0.002), "swamp": (0.14, 0.004), "mountains": (0.05, 0.006), "beach": (0.02, 0.0),
    "river": (0.03, 0.0), "glowforest": (0.14, 0.0),
}
TREE_CHANCE = {
    "forest": ("oak", 0.06), "plains": ("oak", 0.005), "taiga": ("spruce", 0.05), "snowy": ("spruce", 0.008),
    "jungle": ("jungle", 0.035), "savanna": ("acacia", 0.008), "swamp": ("swamp", 0.025),
    "mountains": ("spruce", 0.008), "desert": ("cactus", 0.008), "badlands": ("cactus", 0.002),
    "glowforest": ("glow", 0.03),
}
H_SCALE = 1.6                       # 가로(평면) 지형 배율: 클수록 산·언덕이 넓게 퍼진다
AQUIFER_CELL = 48                   # 지하수면이 같은 구역 한 변 (구역마다 지하 호수 높이가 다르다)
CARVER_RADIUS = 10                  # 동굴·협곡은 최대 이만큼 떨어진 청크에서 출발해 넘어올 수 있다


def _smooth(t):
    return t * t * (3 - 2 * t)


def _lerp(a, b, t):
    return a + (b - a) * t


def _clamp01(v):
    return max(0.0, min(1.0, v))


def _mix(*nums):
    """정수 여러 개 → 섞인 정수 (청크마다 다른 난수 시드)"""
    h = 0x9E3779B9
    for n in nums:
        h = ((h ^ (n & 0xFFFFFFFFFFFF)) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
        h ^= h >> 29
    return h


def _hash2(ix, iz, salt):
    h = ((ix * 0x27D4EB2D) ^ (iz * 0x165667B1) ^ salt) & 0xFFFFFFFF
    h = ((h ^ (h >> 15)) * 0x2C1B3C6D) & 0xFFFFFFFF
    h = ((h ^ (h >> 12)) * 0x297A2D39) & 0xFFFFFFFF
    return (h ^ (h >> 15)) / 4294967295.0


def make_noise(salt, cell):
    """격자 크기 cell 의 부드러운 2D 값 노이즈 (0~1). 격자점 값은 좌표 해시라 범위 제한이 없다"""
    cache = {}

    def lattice(ix, iz):
        v = cache.get((ix, iz))
        if v is None:
            v = cache[(ix, iz)] = _hash2(ix, iz, salt)
        return v

    def sample(x, z):
        fx, fz = x / cell, z / cell
        ix, iz = math.floor(fx), math.floor(fz)
        tx, tz = _smooth(fx - ix), _smooth(fz - iz)
        top = _lerp(lattice(ix, iz), lattice(ix + 1, iz), tx)
        bottom = _lerp(lattice(ix, iz + 1), lattice(ix + 1, iz + 1), tx)
        return _lerp(top, bottom, tz)
    return sample


def make_fbm(rng, cells, weights):
    """크기가 다른 노이즈 여러 겹을 합친 프랙탈 노이즈 (큰 산맥 + 작은 굴곡)"""
    layers = [make_noise(rng.randrange(1 << 31), c) for c in cells]
    total = float(sum(weights))

    def sample(x, z):
        return sum(n(x, z) * w for n, w in zip(layers, weights)) / total
    return sample


def make_climate(seed):
    rng = random.Random(seed)
    return {
        "cont": make_fbm(rng, (256, 96, 40), (5, 2, 1)),      # 대륙성: 낮으면 바다, 높으면 내륙
        "erosion": make_fbm(rng, (180, 60), (3, 1)),          # 침식: 낮을수록 험한 산
        "ridge": make_fbm(rng, (96, 36), (3, 1)),             # 능선 (산등성이 모양)
        "temp": make_fbm(rng, (220, 72), (4, 1)),             # 온도
        "humid": make_fbm(rng, (200, 64), (4, 1)),            # 습도
        "hill": make_fbm(rng, (44, 16), (2, 1)),              # 언덕
        "detail": make_noise(rng.randrange(1 << 31), 7),
        "river": make_fbm(rng, (170, 64), (4, 1)),            # 강 (값이 0.5 근처인 곳)
        "canyon": make_noise(rng.randrange(1 << 31), 110),    # 악지 대협곡
        "magic": make_fbm(rng, (240, 80), (4, 1)),            # 발광숲 (판도라)
    }


def _column(cl, x, z):
    """(지면 높이, 바이옴) - 기후 값들을 섞어서 계산"""
    x, z = x / H_SCALE, z / H_SCALE                           # 평면 스케일을 키운다
    cont, ero = cl["cont"](x, z), cl["erosion"](x, z)
    temp, humid = cl["temp"](x, z), cl["humid"](x, z)
    hill, detail = cl["hill"](x, z), cl["detail"](x, z)
    ridge = 1.0 - abs(2.0 * cl["ridge"](x, z) - 1.0)

    # 1) 큰 지형: 바다 → 해안 → 내륙 → 산맥
    land = SEA_LEVEL + 1 + (cont - 0.42) * 30 + hill * 10 + detail * 1.8
    mount_w = _smooth(_clamp01((cont - 0.5) / 0.12)) * _smooth(_clamp01((0.5 - ero) / 0.14))
    h = land + mount_w * (ridge ** 1.6 * 165 + hill * 25)        # 산맥: 최대 약 200칸
    ocean_w = _smooth(_clamp01((0.42 - cont) / 0.06))
    h = _lerp(h, SEA_LEVEL - 6 - (0.42 - cont) * 60 + detail * 2, ocean_w)

    # 2) 기후로 바이옴 결정
    if ocean_w > 0.5:
        biome = "ocean"
    elif mount_w > 0.45:
        biome = "mountains"
    elif temp > 0.6:
        biome = "jungle" if humid > 0.58 else ("savanna" if humid > 0.45 else
                                               ("badlands" if cont > 0.5 else "desert"))
    elif temp < 0.36:
        biome = "taiga" if humid > 0.45 else "snowy"
    else:
        biome = "swamp" if humid > 0.64 and cont < 0.5 else ("forest" if humid > 0.5 else "plains")
    if biome in ("jungle", "forest", "swamp", "plains") and cl["magic"](x, z) > 0.62:
        biome = "glowforest"                                  # 밤이면 숲 전체가 빛나는 판도라 숲

    # 3) 바이옴별 지형 다듬기
    if biome == "desert":                                     # 사구
        h = _lerp(h, SEA_LEVEL + 4 + (math.sin(x * 0.15 + z * 0.06 + detail * 6) * 0.5 + 0.5) * 7 + hill * 4, 0.7)
    elif biome == "badlands":                                 # 계단식 고원 + 대협곡
        raw = h + 10 + hill * 12
        step = 7
        h = math.floor(raw / step) * step + max(0.0, raw % step - (step - 1.5)) / 1.5 * step
        cv = abs(cl["canyon"](x, z) - 0.5)
        if cv < 0.07:
            h = _lerp(h, SEA_LEVEL + 1, _smooth(_clamp01((0.07 - cv) / 0.03)))
    elif biome == "swamp":                                    # 물웅덩이가 많은 낮은 땅
        h = SEA_LEVEL - 0.6 + detail * 2.2

    # 4) 강이 땅을 깎는다: 높낮이가 있는 강둑 + 웅덩이와 여울이 섞인 울퉁불퉁한 물길
    rv = abs(cl["river"](x, z) - 0.5)
    if biome != "ocean" and rv < 0.05:
        bank = _smooth(_clamp01((0.05 - rv) / 0.03))
        core = _smooth(_clamp01((0.024 - rv) / 0.016))               # 물길 가운데일수록 깊다
        bed = SEA_LEVEL - 2 - core * (2.5 + hill * 6) - detail * 2.5
        shore = SEA_LEVEL + 1 + detail * 2.2 + hill * 2.5
        h = _lerp(h, _lerp(shore, bed, core), bank * (0.6 if biome == "mountains" else 1.0))
        if rv < 0.02 and h < SEA_LEVEL:
            biome = "river"
    if h > WORLD_H - 32:                                      # 꼭대기가 천장에 잘리지 않게 부드럽게 눌러 준다
        h = WORLD_H - 32 + 26 * (1 - math.exp(-(h - (WORLD_H - 32)) / 26))
    gh = int(max(4, min(WORLD_H - 4, h)))
    if biome not in ("ocean", "river", "swamp", "badlands", "snowy", "taiga") and SEA_LEVEL - 1 <= gh <= SEA_LEVEL + 1 \
            and cont < 0.47:
        biome = "beach"                                       # 모래 해변은 바닷가에만 (강·호숫가는 풀밭)
    return gh, biome


def _fill_column(data, i, gh, biome, v=0.5):
    """생성 청크 data 의 기둥 i (= lx*16 + lz) 를 채운다. 칸 번호는 y*256 + i. v 는 바닥 재질을 섞는 값 (0~1)"""
    if biome == "ocean" and gh < SEA_LEVEL - 8:
        surface, under, depth = GRAVEL, GRAVEL, 2        # 깊은 바닷속은 자갈
    elif biome in ("ocean", "beach"):
        surface, under, depth = SAND, SAND, 3
    elif biome == "river" or gh < SEA_LEVEL:            # 강·물웅덩이 바닥: 자갈, 흙, 점토, 모래가 섞인다
        surface = GRAVEL if v < 0.4 else DIRT if v < 0.68 else CLAY if v < 0.84 else SAND
        surface, under, depth = surface, (DIRT if surface == CLAY else surface), 2
    elif gh <= SEA_LEVEL + 1 and (v < 0.2 or v > 0.93):  # 물가 군데군데 자갈밭·모래톱
        surface, under, depth = (GRAVEL if v < 0.2 else SAND), DIRT, 3
    elif biome == "desert":
        surface, under, depth = SAND, SAND, 5
    elif biome == "badlands":
        surface, under, depth = CLAY, CLAY, 22          # 깊은 붉은 지층 (협곡 벽에 줄무늬)
    elif biome == "mountains" and gh >= SNOW_LINE:
        surface, under, depth = SNOW, STONE, 3
    elif biome == "mountains" and gh >= SEA_LEVEL + 70:
        surface, under, depth = STONE, STONE, 3
    elif biome == "snowy":
        surface, under, depth = SNOW, DIRT, 3
    else:
        surface, under, depth = GRASS, DIRT, 3
    data[i] = BEDROCK
    stone_top = gh - depth
    if stone_top >= 1:
        data[i + 256: i + ((stone_top + 1) << 8): 256] = bytes([STONE]) * stone_top
    u0 = max(1, stone_top + 1)
    if gh > u0:
        data[i + (u0 << 8): i + (gh << 8): 256] = bytes([under]) * (gh - u0)
    data[i + (gh << 8)] = surface
    if biome == "desert" and stone_top > 7:              # 사막 모래 아래 사암 층
        data[i + ((stone_top - 5) << 8): i + ((stone_top + 1) << 8): 256] = bytes([SANDSTONE]) * 6
    if gh < SEA_LEVEL:
        data[i + ((gh + 1) << 8): i + ((SEA_LEVEL + 1) << 8): 256] = bytes([WATER]) * (SEA_LEVEL - gh)


def _carve(data, heights, x0, z0, px, py, pz, rx, ry):
    """경로의 한 점 (타원체) 중 이 청크 안에 들어오는 부분만 판다"""
    xa, xb = max(x0, math.floor(px - rx)), min(x0 + 15, math.floor(px + rx))
    za, zb = max(z0, math.floor(pz - rx)), min(z0 + 15, math.floor(pz + rx))
    if xa > xb or za > zb:
        return
    for y in range(max(1, int(py - ry)), min(WORLD_H - 1, int(py + ry) + 1)):
        k = 1 - ((y + 0.5 - py) / ry) ** 2
        if k <= 0:
            continue
        r2 = rx * rx * k
        for x in range(xa, xb + 1):
            dx2 = (x + 0.5 - px) ** 2
            if dx2 > r2:
                continue
            for z in range(za, zb + 1):
                if dx2 + (z + 0.5 - pz) ** 2 > r2:
                    continue
                i = ((x - x0) << 4) | (z - z0)
                idx = (y << 8) | i
                b = data[idx]
                if b == AIR or b == WATER or b == BEDROCK:
                    continue
                data[idx] = AIR                                 # 물 밑도 판다: 강·바다와 이어진 동굴은 물에 잠긴다


# ------------------------------------------------------------------------------
# 판타지 지형 - 192×192 지역마다 시드로 부유섬·첨탑·거대 아치·나락 협곡을 배치하고,
# 청크를 만들 때 그 청크에 걸치는 부분만 기둥 단위로 채운다 (청크 경계를 넘어도 이어진다)
# ------------------------------------------------------------------------------
FEATURE_REGION = 192
FEATURE_REACH = 160                 # 지형 하나가 중심에서 뻗을 수 있는 최대 거리


def _fill(data, i, y0, y1, block):
    """기둥 i 의 y0 ~ y1-1 칸을 block 으로"""
    y0, y1 = max(1, y0), min(WORLD_H, y1)
    if y1 > y0:
        data[i + (y0 << 8): i + (y1 << 8): 256] = bytes([block]) * (y1 - y0)


def _cap(data, i, top, snowy):
    """맨 위를 잔디(눈)로, 그 아래 두 칸을 흙으로 덮는다"""
    if 0 < top < WORLD_H:
        data[i + (top << 8)] = SNOW if snowy else GRASS
        for y in (top - 1, top - 2):
            if y > 0 and data[i + (y << 8)] == STONE:
                data[i + (y << 8)] = STONE if snowy else DIRT


def _raster_island(world, data, heights, x0, z0, f):
    """부유섬: 위는 평평한 풀밭, 아래는 거꾸로 선 바위 원뿔. 가장자리에서 폭포가 떨어진다"""
    cx, cy, cz, R, noise, wf = f["x"], f["y"], f["z"], f["r"], f["noise"], f["waterfall"]
    for lx in range(16):
        for lz in range(16):
            x, z = x0 + lx, z0 + lz
            d = math.hypot(x + 0.5 - cx, z + 0.5 - cz)
            n = noise(x, z)
            edge = R * (0.72 + 0.4 * n)
            i = (lx << 4) | lz
            if wf and math.hypot(x + 0.5 - wf[0], z + 0.5 - wf[1]) < 1.3:         # 폭포: 섬 끝에서 땅까지 물기둥
                for y in range(heights[i] + 1, int(cy) + 2):
                    if data[i + (y << 8)] == AIR:
                        data[i + (y << 8)] = WATER
            if d >= edge:
                continue
            k = d / edge
            top = int(cy + 3 * (1 - k * k) + n * 2)
            bottom = int(cy - R * (0.5 + 0.6 * noise(x * 3 + 500, z * 3)) * (1 - k) ** 0.7) - 1
            _fill(data, i, bottom, top + 1, STONE)
            _cap(data, i, top, top >= SNOW_LINE)
            if (_hash3(x, top, z) % 1000) < 22 and k < 0.75 and top + 9 < WORLD_H:   # 섬 위의 나무
                f.setdefault("trees", []).append((x, top, z))


def _bridge(x1, y1, z1, x2, y2, z2, rng, rise=None, segs=((0.0, 1.0),)):
    """두 지점을 잇는 자연 돌다리 지형 정보. segs 는 실제로 있는 구간 (0~1) - 나머지는 무너져 끊긴 곳"""
    span = math.hypot(x2 - x1, z2 - z1)
    r = rng.uniform(1.8, 3.6) + span / rng.uniform(18, 34)          # 크기마다 두께도 제각각
    if rise is None:
        rise = span * rng.uniform(0.03, 0.14)
    return {"type": "bridge", "x1": x1, "y1": y1, "z1": z1, "x2": x2, "y2": y2, "z2": z2,
            "rise": rise, "r": r, "segs": segs, "noise": make_noise(rng.randrange(1 << 31), 7),
            "x": (x1 + x2) / 2, "z": (z1 + z2) / 2, "box": span / 2 + r * 3 + 4}


def _peak_shape(f, x, z):
    """암봉의 (높이, 경사, 중심에서의 상대 거리) - 바깥이면 None. 능선 몇 갈래 + 울퉁불퉁한 비탈"""
    cx, cz, base, H, Rb, ph, noise = f["x"], f["z"], f["base"], f["h"], f["r"], f["phase"], f["noise"]
    dx, dz = x + 0.5 - cx, z + 0.5 - cz
    d = math.hypot(dx, dz)
    if d > Rb * 1.4:
        return None
    th = math.atan2(dz, dx)
    m = 1 + 0.22 * math.sin(3 * th + ph) + 0.12 * math.sin(5 * th + 2.1 * ph) + 0.25 * (noise(x, z) - 0.5)
    q = d / (Rb * m)
    if q >= 1:
        return None
    t = 1 - q ** 0.8                                        # 반지름 = Rb·(1-t)^1.25 : 아래는 완만, 위는 가파름
    top = base + H * t + (noise(x * 3 + 77, z * 3) - 0.5) * H * 0.06
    slope = H * 0.8 * max(q, 0.02) ** -0.2 / (Rb * m)
    return top, slope, q


def _raster_peak(world, data, heights, x0, z0, f):
    """암봉: 산맥에 솟은 바위산. 완만한 아랫자락은 풀, 가파른 곳은 바위(지층 줄무늬), 꼭대기는 눈"""
    base, H, band = f["base"], f["h"], f["band"]
    for lx in range(16):
        for lz in range(16):
            shape = _peak_shape(f, x0 + lx, z0 + lz)
            if shape is None:
                continue
            top, slope, q = shape
            top = int(top)
            i = (lx << 4) | lz
            gh = heights[i]
            if top <= gh:
                continue
            _fill(data, i, min(gh, base) - 2, top + 1, STONE)
            for by in range(base + 3, top - 1, 9):                              # 지층 줄무늬 (절벽에 보인다)
                _fill(data, i, by, min(top - 1, by + 2), band)
            if top >= SNOW_LINE - 10 or (q < 0.12 and H > 120):
                _fill(data, i, top - 1, top + 1, SNOW)                          # 눈 덮인 꼭대기
            elif slope < 1.1:
                _cap(data, i, top, False)                                       # 완만한 자락은 풀밭


def _raster_bridge(world, data, heights, x0, z0, f):
    """자연 돌다리: 양 끝은 두껍게 땅(봉우리)에 박히고, 가운데는 얇아지며 위로 살짝 휜다. 윗면엔 풀"""
    x1, y1, z1, x2, y2, z2 = f["x1"], f["y1"], f["z1"], f["x2"], f["y2"], f["z2"]
    rise, r, noise = f["rise"], f["r"], f["noise"]
    L = math.hypot(x2 - x1, z2 - z1)
    ux, uz = (x2 - x1) / L, (z2 - z1) / L
    for lx in range(16):
        for lz in range(16):
            x, z = x0 + lx, z0 + lz
            px, pz = x + 0.5 - x1, z + 0.5 - z1
            a, b = px * ux + pz * uz, -px * uz + pz * ux
            if a < -r * 2 or a > L + r * 2:
                continue
            s = min(1.0, max(0.0, a / L))
            if not any(s0 <= s <= s1 for s0, s1 in f["segs"]):
                continue                                                        # 무너져 끊긴 구간
            end = 1 - math.sin(math.pi * s)                                     # 가운데 0, 양 끝 1
            width = r * (1 + 0.9 * end) * (0.85 + 0.3 * noise(x, z))
            if abs(b) > width:
                continue
            yc = y1 + (y2 - y1) * s + rise * math.sin(math.pi * s)
            half = width * math.sqrt(1 - (b / width) ** 2)
            i = (lx << 4) | lz
            lo, hi = int(yc - half * (1.1 + 1.6 * end)), int(yc + half * 0.55)
            if end > 0.75 or a < 0 or a > L:
                lo = min(lo, heights[i] - 2)                                    # 끝은 땅에 박힌다
            _fill(data, i, lo, hi + 1, STONE)
            _cap(data, i, hi, hi >= SNOW_LINE)


def _raster_abyss(world, data, heights, x0, z0, f):
    """나락 협곡(칼바람 나락): 바닥이 얼어붙은 깊은 심연 위로 좁은 돌다리가 걸쳐 있고 가장자리는 눈에 덮였다"""
    cx, cz, half_len, W, ux, uz, noise = f["x"], f["z"], f["len"], f["w"], f["ux"], f["uz"], f["noise"]
    rim = f["rim"]
    for lx in range(16):
        for lz in range(16):
            x, z = x0 + lx, z0 + lz
            px, pz = x + 0.5 - cx, z + 0.5 - cz
            a, b = px * ux + pz * uz, -px * uz + pz * ux
            if abs(a) > half_len + W:
                continue
            taper = math.sqrt(max(0.0, 1 - (a / half_len) ** 2))
            half_w = W / 2 * taper * (0.75 + 0.5 * noise(x, z))
            i = (lx << 4) | lz
            gh = heights[i]
            if gh <= SEA_LEVEL + 1:
                continue                                                        # 바다·강은 그대로
            if abs(b) < half_w:
                floor = 5 + int(noise(x * 2, z * 2) * 4)
                _fill(data, i, floor + 2, WORLD_H, AIR)                         # 하늘까지 뻥 뚫린 심연
                heights[i] = floor + 1
                _fill(data, i, floor, floor + 2, ICE)                           # 얼어붙은 바닥
                for ba, bw in f["bridges"]:                                     # 좁은 돌다리
                    if abs(a - ba) < bw:
                        sag = 3 * (1 - (b / max(half_w, 1)) ** 2)
                        deck = int(rim - 2 - sag)
                        thick = 2 + int(abs(b) / max(half_w, 1) * 4)
                        _fill(data, i, deck - thick, deck + 1, STONE)
                        data[i + (deck << 8)] = SNOW
            elif abs(b) < half_w + 8 and data[i + (gh << 8)] in (GRASS, DIRT, SAND, STONE):
                data[i + (gh << 8)] = SNOW                                      # 눈 덮인 가장자리


def _raster_lake(world, data, heights, x0, z0, f):
    """호수·연못: 가장자리가 울퉁불퉁한 물웅덩이. 주변 땅은 물가까지 완만하게 깎인다"""
    cx, cz, R, L, depth, noise = f["x"], f["z"], f["r"], f["level"], f["depth"], f["noise"]
    for lx in range(16):
        for lz in range(16):
            x, z = x0 + lx, z0 + lz
            d = math.hypot(x + 0.5 - cx, z + 0.5 - cz) / (R * (0.75 + 0.5 * noise(x, z)))
            if d >= 1.5:
                continue
            i = (lx << 4) | lz
            gh = heights[i]
            if d < 1.0:
                surf = min(L, gh)
                floor = min(surf - 1, int(L - depth * (1 - d * d) ** 0.6 - noise(x * 2 + 99, z * 2) * 1.5))
                h = _hash3(x, 3, z) % 10
                _fill(data, i, floor + 1, surf + 1, WATER)
                _fill(data, i, surf + 1, max(gh, surf) + 1, AIR)
                data[i + (floor << 8)] = CLAY if h < 2 else GRAVEL if h < 4 else SAND if d > 0.8 and h < 6 else DIRT
                if f["ice"]:
                    data[i + (surf << 8)] = ICE
                heights[i] = floor
            elif gh > L:                                                        # 물가: 수면까지 완만하게
                t = (d - 1.0) / 0.5
                top = int(L + t * t * (gh - L))
                if top < gh:
                    cover = data[i + (gh << 8)]
                    _fill(data, i, top + 1, gh + 1, AIR)
                    data[i + (top << 8)] = cover if cover in (GRASS, SNOW, SAND) else GRASS
                    heights[i] = top


FEATURE_RASTER = {"island": _raster_island, "peak": _raster_peak, "bridge": _raster_bridge, "abyss": _raster_abyss,
                  "lake": _raster_lake}


class World:
    """끝없이 이어지는 월드. 16×16 생성 청크를 플레이어 주변에서 필요할 때 만들고, 멀어지면 버린다.

    블록은 청크마다 bytearray 한 줄에 들어 있다 (칸 번호 = y*256 + (x%16)*16 + (z%16)).
    버린 청크는 시드로 다시 만들 수 있으므로, 플레이어가 바꾼 블록(edits)만 따로 기억한다.
    """

    def __init__(self, seed, edits=None):
        self.seed = seed
        self.climate = make_climate(seed)
        self.chunks = {}       # (cx, cz) -> bytearray
        self.biomes = {}       # (cx, cz) -> 기둥 256개의 바이옴 이름
        self.spill = {}        # (cx, cz) -> {(x, y, z): 블록}  옆 청크의 나무에서 넘어온 잎·줄기
        self.edits = {}        # (cx, cz) -> {(x, y, z): 블록}  플레이어가 바꾼 블록 (저장 대상)
        self.carvers = {}      # (cx, cz) -> 그 청크에서 출발하는 동굴·협곡 경로 (캐시)
        self.changed = []      # 생성 중에 이미 있던 청크가 바뀐 위치 (렌더러가 다시 그린다)
        self.torch_cache = {}  # (cx, cz) -> 그 청크 안 횃불 중심 좌표 목록
        self.heights = {}      # (cx, cz) -> 기둥 256개의 원래 지면 높이 (하늘빛 계산에 씀)
        self.features = {}     # (지역 x, 지역 z) -> 그 지역의 판타지 지형 목록 (캐시)
        self.aquifers = {}     # (구역 x, 구역 z) -> 지하수면 높이 (0 = 마른 땅속)
        self.near_water = {}   # (x//4, z//4) -> 강·바다 근처인가 (지하수면 = 해수면)
        for (x, y, z), b in (edits or {}).items():
            self.edits.setdefault((x >> 4, z >> 4), {})[(x, y, z)] = b

    # ---- 블록 읽기/쓰기 ------------------------------------------------------
    def get(self, x, y, z):
        """아직 만들지 않은 곳은 돌로 취급 (못 지나감)"""
        if y < 0:
            return BEDROCK
        if y >= WORLD_H:
            return AIR
        c = self.chunks.get((x >> 4, z >> 4))
        if c is None:
            return STONE
        return c[(y << 8) | ((x & 15) << 4) | (z & 15)]

    def set(self, x, y, z, b):
        key = (x >> 4, z >> 4)
        c = self.chunks.get(key)
        if c is None or not 0 <= y < WORLD_H:
            return False
        c[(y << 8) | ((x & 15) << 4) | (z & 15)] = b
        self.edits.setdefault(key, {})[(x, y, z)] = b
        self.torch_cache.pop(key, None)
        return True

    def torches_in(self, x0, z0, x1, z1):
        """사각형 범위 안의 광원 (x, y, z, 빛 거리) - 청크마다 찾아 둔 결과를 재사용"""
        found = []
        for cx in range(x0 >> 4, (x1 >> 4) + 1):
            for cz in range(z0 >> 4, (z1 >> 4) + 1):
                key = (cx, cz)
                if key not in self.torch_cache:
                    c = self.chunks.get(key)
                    if c is None:
                        continue
                    lst = []
                    for block, reach in LIGHT_BLOCKS.items():
                        i = c.find(block)
                        n, every, col = 0, LIGHT_SPARSE.get(block, 1), LIGHT_COLORS[block]
                        while i >= 0:
                            if n % every == 0:
                                lst.append(((cx << 4) + ((i >> 4) & 15) + 0.5, (i >> 8) + 0.6,
                                            (cz << 4) + (i & 15) + 0.5, reach, col, block))
                            n += 1
                            i = c.find(block, i + 1)
                    self.torch_cache[key] = lst
                found.extend(t for t in self.torch_cache[key] if x0 <= t[0] <= x1 + 1 and z0 <= t[2] <= z1 + 1)
        return found

    def all_edits(self):
        return [(x, y, z, b) for chunk_edits in self.edits.values() for (x, y, z), b in chunk_edits.items()]

    def is_loaded(self, x, z):
        return (math.floor(x) >> 4, math.floor(z) >> 4) in self.chunks

    def has_area(self, x0, z0, x1, z1):
        return all((cx, cz) in self.chunks for cx in range(x0 >> 4, (x1 >> 4) + 1)
                   for cz in range(z0 >> 4, (z1 >> 4) + 1))

    def biome_at(self, x, z):
        bx, bz = math.floor(x), math.floor(z)
        b = self.biomes.get((bx >> 4, bz >> 4))
        if b is None:
            return _column(self.climate, bx, bz)[1]
        return b[((bx & 15) << 4) | (bz & 15)]

    # ---- 청크 불러오기 / 버리기 ----------------------------------------------
    def ensure_around(self, x, z, radius=None, budget=None, progress=None):
        """(x, z) 주변 radius 청크 안의 빈 청크를 가까운 것부터 만든다. 만든 청크 목록 반환"""
        radius = LOAD_RADIUS if radius is None else radius
        ccx, ccz = math.floor(x) >> 4, math.floor(z) >> 4
        missing = [(dx * dx + dz * dz, ccx + dx, ccz + dz)
                   for dx in range(-radius, radius + 1) for dz in range(-radius, radius + 1)
                   if dx * dx + dz * dz <= radius * radius + 1 and (ccx + dx, ccz + dz) not in self.chunks]
        missing.sort()
        made = []
        for i, (_, cx, cz) in enumerate(missing):
            if budget is not None and len(made) >= budget:
                break
            self.generate(cx, cz)
            made.append((cx, cz))
            if progress and i % 4 == 0:
                progress(i / len(missing))
        return made

    def unload_far(self, x, z, radius):
        ccx, ccz = math.floor(x) >> 4, math.floor(z) >> 4
        for key in [k for k in self.chunks if (k[0] - ccx) ** 2 + (k[1] - ccz) ** 2 > radius * radius]:
            del self.chunks[key]
            del self.biomes[key]
            self.heights.pop(key, None)
            self.torch_cache.pop(key, None)

    # ---- 청크 생성 ------------------------------------------------------------
    def generate(self, cx, cz):
        x0, z0 = cx << 4, cz << 4
        data = bytearray(256 * WORLD_H)
        heights, biomes = [0] * 256, [""] * 256
        for lx in range(16):
            for lz in range(16):
                x, z = x0 + lx, z0 + lz
                gh, biome = _column(self.climate, x, z)
                i = (lx << 4) | lz
                heights[i], biomes[i] = gh, biome
                _fill_column(data, i, gh, biome, (_hash3((x + (z >> 3)) >> 2, 7, (z + (x >> 3)) >> 2) & 1023) / 1023)
        self.chunks[(cx, cz)] = data
        self.biomes[(cx, cz)] = biomes
        self.heights[(cx, cz)] = heights
        self.torch_cache.pop((cx, cz), None)
        rng = random.Random(_mix(self.seed, cx, cz, 1))
        trees = self._place_features(cx, cz, data, heights)
        self._place_ores(data, rng)
        caverns = []
        for ocx in range(cx - CARVER_RADIUS, cx + CARVER_RADIUS + 1):
            for ocz in range(cz - CARVER_RADIUS, cz + CARVER_RADIUS + 1):
                paths, rooms = self._carver_paths(ocx, ocz)
                for minx, maxx, minz, maxz, points in paths:
                    if maxx < x0 or minx > x0 + 15 or maxz < z0 or minz > z0 + 15:
                        continue
                    for px, py, pz, rx, ry in points:
                        _carve(data, heights, x0, z0, px, py, pz, rx, ry)
                caverns.extend(c for c in rooms if c[0] + c[3] >= x0 and c[0] - c[3] <= x0 + 15
                               and c[2] + c[3] >= z0 and c[2] - c[3] <= z0 + 15)
        self._flood_caves(x0, z0, data, heights)
        for cav in caverns:
            self._decorate_cavern(cx, cz, data, cav)
        self._decorate_caves(data, heights, random.Random(_mix(self.seed, cx, cz, 9)))
        self._decorate(cx, cz, data, heights, biomes, rng)
        for x, top, z in trees:                                          # 부유섬 위의 나무
            self._tree(cx, cz, data, random.Random(_mix(self.seed, x, z, 7)), "oak", x, top, z)
        for (x, y, z), b in self.spill.get((cx, cz), {}).items():
            idx = (y << 8) | ((x & 15) << 4) | (z & 15)
            if data[idx] == AIR:
                data[idx] = b
        for (x, y, z), b in self.edits.get((cx, cz), {}).items():
            data[(y << 8) | ((x & 15) << 4) | (z & 15)] = b

    def _region_features(self, rx, rz):
        """지역 (rx, rz) 의 판타지 지형 목록 (시드로 정해짐)"""
        key = (rx, rz)
        if key in self.features:
            return self.features[key]
        rng = random.Random(_mix(self.seed, rx, rz, 3))
        feats = []

        def spot(margin=24):
            return (rx * FEATURE_REGION + rng.uniform(margin, FEATURE_REGION - margin),
                    rz * FEATURE_REGION + rng.uniform(margin, FEATURE_REGION - margin))

        def ground(x, z):
            return _column(self.climate, math.floor(x), math.floor(z))[0]

        for _ in range(rng.choice((0, 1, 1, 2, 3))):                       # 부유섬
            x, z = spot()
            R = rng.uniform(14, 70)
            y = min(WORLD_H - 30, max(ground(x, z) + R * 1.2 + 30, SEA_LEVEL + 80) + rng.uniform(0, 220))
            a = rng.uniform(0, 2 * math.pi)
            wf = (x + math.cos(a) * R * 0.62, z + math.sin(a) * R * 0.62) if rng.random() < 0.5 else None
            feats.append({"type": "island", "x": x, "y": y, "z": z, "r": R, "waterfall": wf,
                          "noise": make_noise(rng.randrange(1 << 31), 9), "box": R * 1.15 + 2})
        peaks = []
        if rng.random() < 0.45:                                             # 암봉 무리: 능선이 뻗은 바위산 몇 개
            x, z = spot(70)
            band = rng.choice((STONE, STONE, CLAY, SANDSTONE))
            for _ in range(rng.randint(2, 4)):
                sx, sz = x + rng.uniform(-45, 45), z + rng.uniform(-45, 45)
                base = ground(sx, sz)
                if base <= SEA_LEVEL + 2:
                    continue
                tier = rng.random()                                         # 대부분 중간, 가끔 아주 높은 것
                H = rng.uniform(40, 80) if tier < 0.5 else (rng.uniform(80, 140) if tier < 0.85 else rng.uniform(140, 220))
                H = min(WORLD_H - 8 - base, H)
                Rb = H * rng.uniform(0.5, 0.75) + 6                         # 밑둥이 넓은 산 모양
                peak = {"type": "peak", "x": sx, "z": sz, "base": base, "h": H, "r": Rb,
                        "phase": rng.uniform(0, 6.3), "band": band, "noise": make_noise(rng.randrange(1 << 31), 9),
                        "box": Rb * 1.45 + 3}
                feats.append(peak)
                peaks.append(peak)
        # 자연 돌다리: 이웃한 두 봉우리의 허리, 또는 골짜기·협곡 양쪽의 높은 땅을 잇는다 (위로 살짝만 휜다)
        brng = random.Random(_mix(self.seed, rx, rz, 17))
        pairs = [(a, b) for k, a in enumerate(peaks) for b in peaks[k + 1:]
                 if 30 < math.hypot(a["x"] - b["x"], a["z"] - b["z"]) < 160]
        brng.shuffle(pairs)
        for a, b in pairs[:2]:                                              # 봉우리 허리를 잇는 다리
            if brng.random() < 0.75:
                feats.append(_bridge(a["x"], a["base"] + a["h"] * brng.uniform(0.3, 0.65), a["z"],
                                     b["x"], b["base"] + b["h"] * brng.uniform(0.3, 0.65), b["z"], brng))
        made = 0
        for _ in range(60):                                                 # 골짜기·협곡을 가로지르는 다리
            if made >= 2:
                break
            x, z = brng.uniform(60, FEATURE_REGION - 60) + rx * FEATURE_REGION, \
                brng.uniform(60, FEATURE_REGION - 60) + rz * FEATURE_REGION
            ang, span = brng.uniform(0, math.pi), brng.uniform(24, 160)
            ux, uz = math.cos(ang), math.sin(ang)
            x1, z1, x2, z2 = x - ux * span / 2, z - uz * span / 2, x + ux * span / 2, z + uz * span / 2
            g1, g2 = ground(x1, z1), ground(x2, z2)
            low = min(ground(x1 + (x2 - x1) * t, z1 + (z2 - z1) * t) for t in (0.3, 0.5, 0.7))
            if min(g1, g2) - low >= max(10, span * 0.15) and abs(g1 - g2) < span * 0.35 and low > SEA_LEVEL - 12:
                feats.append(_bridge(x1, g1 - 1, z1, x2, g2 - 1, z2, brng))
                made += 1
        for _ in range(brng.randint(1, 4)):                                 # 평지의 잘린 아치: 땅에서 솟다가 끊긴 바위
            x, z = brng.uniform(40, FEATURE_REGION - 40) + rx * FEATURE_REGION, \
                brng.uniform(40, FEATURE_REGION - 40) + rz * FEATURE_REGION
            ang, span = brng.uniform(0, math.pi), brng.uniform(18, 110)
            ux, uz = math.cos(ang), math.sin(ang)
            x1, z1, x2, z2 = x - ux * span / 2, z - uz * span / 2, x + ux * span / 2, z + uz * span / 2
            g1, g2 = ground(x1, z1), ground(x2, z2)
            if min(g1, g2) <= SEA_LEVEL + 1 or abs(g1 - g2) > 6 + span * 0.08:
                continue
            kind = brng.random()
            if kind < 0.45:
                segs = ((0.0, brng.uniform(0.3, 0.62)),)                    # 한쪽만 솟아 끊긴 것
            elif kind < 0.85:
                segs = ((0.0, brng.uniform(0.25, 0.42)), (brng.uniform(0.58, 0.75), 1.0))   # 가운데가 무너진 것
            else:
                segs = ((0.0, 1.0),)                                        # 온전한 아치
            feats.append(_bridge(x1, g1 - 2, z1, x2, g2 - 2, z2, brng, rise=span * brng.uniform(0.22, 0.5),
                                 segs=segs))
        if rng.random() < 0.18:                                             # 나락 협곡
            x, z = spot(60)
            if ground(x, z) > SEA_LEVEL + 4:
                ang = rng.uniform(0, math.pi)
                half_len = rng.uniform(75, 130)
                bridges = [(rng.uniform(-half_len * 0.5, half_len * 0.5), rng.uniform(1.6, 3.0))
                           for _ in range(rng.randint(1, 2))]
                feats.append({"type": "abyss", "x": x, "z": z, "len": half_len, "w": rng.uniform(18, 34),
                              "ux": math.cos(ang), "uz": math.sin(ang), "rim": ground(x, z), "bridges": bridges,
                              "noise": make_noise(rng.randrange(1 << 31), 11), "box": half_len + 30})
        lrng = random.Random(_mix(self.seed, rx, rz, 11))
        for _ in range(lrng.randint(2, 6)):                                 # 호수와 연못
            x, z = spot(30)
            big = lrng.random() < 0.4
            R = lrng.uniform(10, 30) if big else lrng.uniform(3, 7)
            center, biome = _column(self.climate, math.floor(x), math.floor(z))
            ring = [ground(x + math.cos(a) * R * 1.25, z + math.sin(a) * R * 1.25)
                    for a in (k * math.pi / 4 for k in range(8))]
            level = min(ring + [center]) - 1
            if biome in ("ocean", "river", "beach", "swamp") or level <= SEA_LEVEL + 1 or level > SEA_LEVEL + 160 \
                    or max(ring) - level > 30 or center - level > 14:
                continue
            feats.append({"type": "lake", "x": x, "z": z, "r": R, "level": level,
                          "depth": lrng.uniform(3, 7) if big else lrng.uniform(1.5, 3),
                          "ice": biome in ("snowy", "taiga") or level >= SNOW_LINE,
                          "noise": make_noise(lrng.randrange(1 << 31), 9), "box": R * 1.9 + 2})
        self.features[key] = feats
        return feats

    def _place_features(self, cx, cz, data, heights):
        """이 청크에 걸치는 판타지 지형을 그린다. 부유섬 위 나무 자리 목록을 돌려준다"""
        x0, z0 = cx << 4, cz << 4
        trees = []
        for rx in range((x0 - FEATURE_REACH) // FEATURE_REGION, (x0 + 16 + FEATURE_REACH) // FEATURE_REGION + 1):
            for rz in range((z0 - FEATURE_REACH) // FEATURE_REGION, (z0 + 16 + FEATURE_REACH) // FEATURE_REGION + 1):
                for f in self._region_features(rx, rz):
                    box = f["box"]
                    if f["x"] + box < x0 or f["x"] - box > x0 + 16 or f["z"] + box < z0 or f["z"] - box > z0 + 16:
                        continue
                    f.pop("trees", None)
                    FEATURE_RASTER[f["type"]](self, data, heights, x0, z0, f)
                    trees.extend(f.pop("trees", []))
        return trees

    def _aquifer_level(self, x, z):
        """지하수면: 이 높이 아래의 동굴은 물에 잠긴다. 강·바다 근처는 해수면, 그 밖은 구역마다 다른 지하 호수 높이"""
        near = self.near_water.get((x >> 2, z >> 2))         # 강·바다 근처인지는 4칸 격자로 한 번만 계산
        if near is None:
            cl = self.climate
            sx, sz = ((x >> 2) * 4 + 2) / H_SCALE, ((z >> 2) * 4 + 2) / H_SCALE
            near = cl["cont"](sx, sz) < 0.45 or abs(cl["river"](sx, sz) - 0.5) < 0.06
            self.near_water[(x >> 2, z >> 2)] = near
        if near:
            return SEA_LEVEL
        key = (x // AQUIFER_CELL, z // AQUIFER_CELL)
        level = self.aquifers.get(key)
        if level is None:
            r = random.Random(_mix(self.seed, key[0], key[1], 13))
            level = r.randint(10, SEA_LEVEL - 6) if r.random() < 0.45 else 0
            self.aquifers[key] = level
        return level

    def _flood_caves(self, x0, z0, data, heights):
        """지하수: 지하수면 아래 동굴은 물로 채운다. 지하수면이 다른 구역과 맞닿은 곳엔 돌 벽을 세우고,
        물 바로 아래 빈 동굴(물에 잠기지 않는 곳의 강·호수 바닥이 뚫린 자리)은 돌로 막는다"""
        lv = [[self._aquifer_level(x0 + lx, z0 + lz) for lz in range(-1, 17)] for lx in range(-1, 17)]
        air_water = bytes([AIR, WATER])
        for lx in range(16):
            for lz in range(16):
                i = (lx << 4) | lz
                level = lv[lx + 1][lz + 1]
                hi = max(level, lv[lx][lz + 1], lv[lx + 2][lz + 1], lv[lx + 1][lz], lv[lx + 1][lz + 2])
                for y in range(1, min(heights[i], hi + 1)):
                    idx = i + (y << 8)
                    if data[idx] == AIR:
                        data[idx] = WATER if y <= level else STONE
                col = data[i::256]
                y = col.find(air_water)
                while y >= 0:
                    data[i + (y << 8)] = STONE
                    y = col.find(air_water, y + 1)

    def _decorate_cavern(self, cx, cz, data, cav):
        """거대 공동 안: 지하 호수, 종유석·석순, 빛나는 수정"""
        ccx, ccy, ccz, rx, ry, lake, cid = cav
        x0, z0 = cx << 4, cz << 4
        rng = random.Random(_mix(self.seed, cid, cx, cz, 5))
        if lake is not None:
            for lx in range(16):
                for lz in range(16):
                    dx, dz = (x0 + lx + 0.5 - ccx) / rx, (z0 + lz + 0.5 - ccz) / rx
                    if dx * dx + dz * dz > 1.1:
                        continue
                    i = (lx << 4) | lz
                    for y in range(max(2, int(ccy - ry * 1.2)), int(lake) + 1):
                        if data[i + (y << 8)] == AIR:
                            data[i + (y << 8)] = WATER
        for _ in range(rng.randint(3, 8)):
            lx, lz = rng.randrange(16), rng.randrange(16)
            x, z = x0 + lx, z0 + lz
            if ((x + 0.5 - ccx) / rx) ** 2 + ((z + 0.5 - ccz) / rx) ** 2 > 0.75:
                continue
            i = (lx << 4) | lz
            y = int(ccy)
            if data[i + (y << 8)] != AIR:
                continue
            floor, ceil = y, y
            while floor > 2 and data[i + ((floor - 1) << 8)] in (AIR, WATER):
                floor -= 1
            while ceil < WORLD_H - 2 and data[i + ((ceil + 1) << 8)] == AIR:
                ceil += 1
            kind = rng.random()
            dry = data[i + ((floor - 1) << 8)] != WATER
            if kind < 0.22:                                                 # 천장에서 늘어진 종유석
                self._cone(cx, cz, data, x, ceil, z, rng.randint(4, 12), rng.uniform(1.2, 2.6), -1)
            elif kind < 0.4 and dry:                                        # 바닥에서 솟은 석순
                self._cone(cx, cz, data, x, floor, z, rng.randint(3, 10), rng.uniform(1.2, 2.4), 1)
            elif kind < 0.5 and dry:                                        # 빛나는 수정
                self._put(cx, cz, data, x, floor, z, CRYSTAL)
            elif kind < 0.58:                                               # 천장에서 쏟아지는 지하 폭포
                for wy in range(floor, ceil + 1):
                    data[i + (wy << 8)] = WATER
                if ceil + 1 < WORLD_H and data[i + ((ceil + 1) << 8)] == STONE:
                    data[i + ((ceil + 1) << 8)] = WATER
                for ax in range(max(0, lx - 2), min(16, lx + 3)):          # 떨어지는 자리의 웅덩이
                    for az in range(max(0, lz - 2), min(16, lz + 3)):
                        j = (ax << 4) | az
                        if (ax - lx) ** 2 + (az - lz) ** 2 <= 5 and data[j + ((floor - 1) << 8)] in TERRAIN_BLOCKS \
                                and data[j + (floor << 8)] in (AIR, WATER):
                            data[j + ((floor - 1) << 8)] = WATER
            elif kind < 0.7:                                                # 천장에서 늘어진 발광 덩굴
                for k in range(min(rng.randint(3, 12), ceil - floor - 1)):
                    if data[i + ((ceil - k) << 8)] != AIR:
                        break
                    data[i + ((ceil - k) << 8)] = GLOW_VINE
            elif dry:                                                       # 발광 버섯·이끼 군락
                plant = GLOW_SHROOM if kind < 0.85 else GLOW_MOSS
                for _ in range(rng.randint(3, 8)):
                    ax, az = lx + rng.randint(-2, 2), lz + rng.randint(-2, 2)
                    if 0 <= ax < 16 and 0 <= az < 16:
                        j = (ax << 4) | az
                        for fy in range(floor + 2, floor - 3, -1):          # 바닥 높이가 조금 달라도 찾는다
                            if data[j + (fy << 8)] == AIR and data[j + ((fy - 1) << 8)] in TERRAIN_BLOCKS:
                                data[j + (fy << 8)] = plant
                                break

    def _decorate_caves(self, data, heights, rng):
        """땅속 빈 공간마다: 바닥엔 발광 이끼·버섯, 천장엔 발광 덩굴, 벽엔 루멘 광석"""
        for _ in range(48):
            lx, lz = rng.randrange(16), rng.randrange(16)
            i = (lx << 4) | lz
            col = data[i::256].translate(CAVE_TABLE)          # 0 = 공기, 1 = 단단한 땅, 2 = 그 밖 (물 등)
            top = heights[i] - 5
            y = col.find(b"\x00", 3, max(3, top))
            while y >= 0:
                end = col.find(b"\x01", y, top + 1)
                if end < 0:
                    break
                if col[y - 1] == 1 and rng.random() < 0.7:
                    r = rng.random()
                    if r < 0.4:
                        data[i + (y << 8)] = GLOW_MOSS
                    elif r < 0.6:
                        data[i + (y << 8)] = GLOW_SHROOM
                    elif r < 0.85 and end - y >= 3:
                        for k in range(1, min(rng.randint(2, 8), end - y - 1) + 1):
                            data[i + ((end - k) << 8)] = GLOW_VINE
                    elif r < 0.92 and end - y >= 4:                         # 천장 틈에서 떨어지는 물줄기 + 물웅덩이
                        data[i + ((y - 1) << 8): i + (end << 8): 256] = bytes([WATER]) * (end - y + 1)
                    elif data[i + ((y - 1) << 8)] == STONE:
                        data[i + ((y - 1) << 8)] = LUMEN_ORE
                    if rng.random() < 0.25 and data[i + ((end) << 8)] == STONE:
                        data[i + (end << 8)] = LUMEN_ORE                    # 천장에 박힌 루멘 광석
                y = col.find(b"\x00", end, max(end, top))

    def _cone(self, cx, cz, data, x, y, z, h, r, direction):
        for k in range(h):
            rr = r * (1 - k / h) + 0.3
            ir = int(math.ceil(rr))
            for bx in range(x - ir, x + ir + 1):
                for bz in range(z - ir, z + ir + 1):
                    if (bx - x) ** 2 + (bz - z) ** 2 <= rr * rr:
                        self._put(cx, cz, data, bx, y + k * direction, bz, STONE)

    def _place_ores(self, data, rng):
        """광맥: 깊을수록 귀한 광석"""
        for ore, count, size, max_y in ((COAL_ORE, 6, 8, 100), (IRON_ORE, 4, 6, 60), (GOLD_ORE, 2, 5, 32),
                                        (DIAMOND_ORE, 1, 4, 18)):
            for _ in range(count):
                if ore == DIAMOND_ORE and rng.random() < 0.6:
                    continue
                x, z, y = rng.randrange(16), rng.randrange(16), rng.randint(2, max_y)
                for _ in range(size):
                    if 0 <= x < 16 and 0 <= z < 16 and 1 <= y < WORLD_H:
                        idx = (y << 8) | (x << 4) | z
                        if data[idx] == STONE:
                            data[idx] = ore
                    x += rng.randint(-1, 1); y += rng.randint(-1, 1); z += rng.randint(-1, 1)

    def _carver_paths(self, ocx, ocz):
        """청크 (ocx, ocz) 에서 출발하는 지렁이 동굴과 거대 협곡의 경로 (시드로 정해짐)"""
        key = (ocx, ocz)
        if key in self.carvers:
            return self.carvers[key]
        rng = random.Random(_mix(self.seed, ocx, ocz, 2))
        paths = []
        for _ in range((rng.random() < 0.5) + (rng.random() < 0.2)):              # 지렁이 동굴
            x, z = (ocx + rng.random()) * 16, (ocz + rng.random()) * 16
            gh = _column(self.climate, math.floor(x), math.floor(z))[0]
            y = rng.uniform(8, max(10, gh - 8))
            yaw, pitch, r = rng.uniform(0, 2 * math.pi), rng.uniform(-0.3, 0.3), rng.uniform(1.3, 2.8)
            points = []
            for _ in range(rng.randint(60, 140)):
                points.append((x, y, z, r, r * 0.85))
                yaw += rng.uniform(-0.35, 0.35)
                pitch = max(-0.6, min(0.6, pitch + rng.uniform(-0.2, 0.2)))
                r = max(1.1, min(3.4, r + rng.uniform(-0.25, 0.25)))
                x += math.cos(yaw) * math.cos(pitch)
                z += math.sin(yaw) * math.cos(pitch)
                y = max(4.0, min(WORLD_H - 10.0, y + math.sin(pitch)))
            paths.append(points)
        srng = random.Random(_mix(self.seed, ocx, ocz, 14))
        for _ in range(3):                                                          # 강바닥에서 땅속으로 이어지는 물굴
            x, z = (ocx + srng.random()) * 16, (ocz + srng.random()) * 16
            gh, biome = _column(self.climate, math.floor(x), math.floor(z))
            if biome != "river":
                continue
            if srng.random() < 0.45:
                y, yaw, pitch, r = gh - 1.0, srng.uniform(0, 2 * math.pi), -0.55, srng.uniform(1.6, 2.6)
                points = []
                for _ in range(srng.randint(40, 100)):
                    points.append((x, y, z, r, r * 0.8))
                    yaw += srng.uniform(-0.3, 0.3)
                    pitch = max(-0.7, min(0.25, pitch + srng.uniform(-0.15, 0.15)))
                    r = max(1.2, min(3.2, r + srng.uniform(-0.2, 0.2)))
                    x += math.cos(yaw) * math.cos(pitch)
                    z += math.sin(yaw) * math.cos(pitch)
                    y = max(6.0, y + math.sin(pitch))
                paths.append(points)
            break
        if rng.random() < 0.02:                                                     # 거대 협곡
            x, z = (ocx + rng.random()) * 16, (ocz + rng.random()) * 16
            yaw = rng.uniform(0, 2 * math.pi)
            length, depth = rng.randint(80, 150), rng.uniform(26, 42)
            points = []
            for i in range(length):
                t = i / length
                gh = _column(self.climate, math.floor(x), math.floor(z))[0]
                if gh <= SEA_LEVEL + 1:
                    break                                         # 바다·강에 닿으면 멈춤
                width = 2.0 + 4.5 * math.sin(math.pi * t)
                bottom = max(5.0, gh - depth * math.sin(math.pi * min(1.0, t * 1.4 + 0.1)))
                ry = (gh + 8 - bottom) / 2
                points.append((x, bottom + ry, z, width, ry))
                yaw += rng.uniform(-0.12, 0.12)
                x += math.cos(yaw)
                z += math.sin(yaw)
            if points:
                paths.append(points)
        rooms = []
        if rng.random() < 0.035:                                                    # 거대 공동
            x, z = (ocx + rng.random()) * 16, (ocz + rng.random()) * 16
            gh = _column(self.climate, math.floor(x), math.floor(z))[0]
            if gh > 45:
                rx, ry = rng.uniform(14, 28), rng.uniform(9, 17)
                y = rng.uniform(ry + 6, max(ry + 7, gh - ry - 14))
                points = [(x, y, z, rx, ry)]
                for _ in range(rng.randint(4, 7)):                                   # 울퉁불퉁하게 겹친 방들
                    points.append((x + rng.uniform(-rx, rx) * 0.6, y + rng.uniform(-ry, ry) * 0.4,
                                   z + rng.uniform(-rx, rx) * 0.6, rx * rng.uniform(0.45, 0.75),
                                   ry * rng.uniform(0.5, 0.9)))
                paths.append(points)
                lake = y - ry * 0.55 + rng.uniform(0, 3) if rng.random() < 0.5 else None
                rooms.append((x, y, z, rx * 1.3, ry, lake, _mix(ocx, ocz) & 0xFFFFFF))
        result = []
        for points in paths:
            result.append((min(p[0] - p[3] for p in points), max(p[0] + p[3] for p in points),
                           min(p[2] - p[3] for p in points), max(p[2] + p[3] for p in points), points))
        self.carvers[key] = (result, rooms)
        return result, rooms

    # ---- 나무와 바위 (옆 청크로 넘어가는 잎은 spill 에 기록) --------------------
    def _put(self, cx, cz, data, x, y, z, b, only_air=True):
        if not 0 <= y < WORLD_H:
            return
        key = (x >> 4, z >> 4)
        idx = (y << 8) | ((x & 15) << 4) | (z & 15)
        if key == (cx, cz):
            if not only_air or data[idx] == AIR:
                data[idx] = b
            return
        self.spill.setdefault(key, {})[(x, y, z)] = b
        other = self.chunks.get(key)
        if other is not None and other[idx] == AIR and (x, y, z) not in self.edits.get(key, ()):
            other[idx] = b
            self.changed.append((x, z))

    def _decorate(self, cx, cz, data, heights, biomes, rng):
        x0, z0 = cx << 4, cz << 4
        for lx in range(16):
            for lz in range(16):
                i = (lx << 4) | lz
                gh = heights[i]
                if gh + 18 >= WORLD_H:
                    continue
                top, above = data[(gh << 8) | i], data[((gh + 1) << 8) | i]
                if above != AIR or top not in (GRASS, SAND, SNOW, STONE):
                    continue
                biome = biomes[i]
                x, z = x0 + lx, z0 + lz
                if biome in ("plains", "mountains", "taiga") and rng.random() < 0.0025:
                    self._boulder(cx, cz, data, rng, x, gh + 1, z)
                    continue
                kind, chance = TREE_CHANCE.get(biome, (None, 0))
                tree_roll = rng.random() if kind is not None else 1.0
                if biome == "glowforest" and top == GRASS and tree_roll >= chance:
                    r = rng.random()                                     # 발광숲 바닥: 버섯·나선초·이끼·풀
                    if r < 0.3:
                        data[((gh + 1) << 8) | i] = (GLOW_SHROOM if r < 0.05 else SPIRAL_PLANT if r < 0.075
                                                     else GLOW_MOSS if r < 0.15 else TALL_GRASS)
                    continue
                if kind is None or tree_roll >= chance:
                    grass, flower = GROUND_COVER.get(biome, (0.0, 0.0))
                    r = rng.random()
                    if top == GRASS and r < grass:                       # 풀밭과 꽃
                        data[((gh + 1) << 8) | i] = TALL_GRASS
                    elif top == GRASS and r < grass + flower:
                        data[((gh + 1) << 8) | i] = FLOWER_RED if rng.random() < 0.5 else FLOWER_YELLOW
                    continue
                if (kind == "cactus") != (top == SAND) or top == STONE:
                    continue
                crowded = any(data[((gh + 1) << 8) | (ax << 4) | az] in (WOOD, CACTUS, SHROOM_STEM)
                              for ax in range(max(0, lx - 2), min(16, lx + 3))
                              for az in range(max(0, lz - 2), min(16, lz + 3)))
                if not crowded:
                    self._tree(cx, cz, data, rng, kind, x, gh, z)
        self._cliff_fall(data, heights, biomes, random.Random(_mix(self.seed, cx, cz, 15)))

    def _giant_shroom(self, cx, cz, data, rng, x, gh, z):
        """거대 발광 버섯: 굵은 줄기 + 둥근 갓 (갓 위를 걸을 수 있다) + 갓 아래로 늘어진 덩굴"""
        put = self._put
        h = rng.randint(6, 15)
        for ty in range(1, h + 1):
            put(cx, cz, data, x, gh + ty, z, SHROOM_STEM, only_air=False)
        top = gh + h
        R = min(7.0, 2.6 + h * 0.3)
        for dy, rr in ((0, R), (1, R - 0.6), (2, R - 1.7), (3, R - 3.2)):
            ir = int(math.ceil(rr))
            for lx in range(x - ir, x + ir + 1):
                for lz in range(z - ir, z + ir + 1):
                    if (lx - x) ** 2 + (lz - z) ** 2 <= rr * rr:
                        put(cx, cz, data, lx, top + dy, lz, GLOW_CAP)
        for _ in range(rng.randint(3, 8)):
            a = rng.uniform(0, 2 * math.pi)
            vx, vz = round(x + math.cos(a) * (R - 0.8)), round(z + math.sin(a) * (R - 0.8))
            for k in range(1, rng.randint(2, 5)):
                put(cx, cz, data, vx, top - k, vz, GLOW_VINE)

    def _cliff_fall(self, data, heights, biomes, rng):
        """가파른 절벽의 바위틈에서 솟아 떨어지는 폭포 + 떨어지는 자리의 웅덩이"""
        if rng.random() >= (0.55 if "mountains" in (biomes[0], biomes[136], biomes[255]) else 0.1):
            return
        soft = (AIR, TALL_GRASS, FLOWER_RED, FLOWER_YELLOW) + tuple(GLOW_PLANTS)
        for _ in range(80):
            lx, lz = rng.randrange(1, 15), rng.randrange(1, 15)
            i = (lx << 4) | lz
            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                j = ((lx + dx) << 4) | (lz + dz)
                low, top = heights[j], heights[i] - 1
                if top - low < 4 or low < SEA_LEVEL or data[j + ((low + 1) << 8)] not in soft \
                        or data[i + (heights[i] << 8)] not in TERRAIN_BLOCKS:
                    continue
                data[i + (top << 8)] = WATER                             # 바위틈의 샘
                for y in range(low + 1, top + 1):
                    if data[j + (y << 8)] in soft:
                        data[j + (y << 8)] = WATER
                px, pz = lx + dx, lz + dz
                for ax in range(max(0, px - 2), min(16, px + 3)):       # 웅덩이
                    for az in range(max(0, pz - 2), min(16, pz + 3)):
                        k = (ax << 4) | az
                        if (ax - px) ** 2 + (az - pz) ** 2 <= 5 and abs(heights[k] - low) <= 1 \
                                and data[k + ((heights[k] + 1) << 8)] in soft:
                            data[k + (heights[k] << 8)] = WATER
                            data[k + ((heights[k] + 1) << 8)] = AIR
                return

    def _boulder(self, cx, cz, data, rng, x, y, z):
        """둥근 바위 덩어리"""
        r = rng.uniform(1.2, 2.8)
        ir = int(math.ceil(r))
        for by in range(y - 1, y + ir + 1):
            for bx in range(x - ir, x + ir + 1):
                for bz in range(z - ir, z + ir + 1):
                    if (bx - x) ** 2 + ((by - y) * 1.3) ** 2 + (bz - z) ** 2 <= r * r:
                        self._put(cx, cz, data, bx, by, bz, STONE)

    def _tree(self, cx, cz, data, rng, kind, x, gh, z):
        put = self._put
        if kind == "cactus":
            for cy in range(1, rng.randint(2, 4) + 1):
                put(cx, cz, data, x, gh + cy, z, CACTUS)
            return
        if kind == "glow":
            if rng.random() < 0.45:
                self._giant_shroom(cx, cz, data, rng, x, gh, z)
                return
            kind = "glowtree"
        if kind == "glowtree":                                  # 덩굴이 늘어진 판도라 나무
            trunk = rng.randint(9, 14)
            for ty in range(1, trunk + 1):
                put(cx, cz, data, x, gh + ty, z, WOOD, only_air=False)
            top = gh + trunk
            for ly in range(top - 2, top + 2):
                r = 4.2 - max(0, ly - top) * 1.6
                for lx in range(x - 5, x + 6):
                    for lz in range(z - 5, z + 6):
                        if (lx - x) ** 2 + (lz - z) ** 2 <= r * r:
                            put(cx, cz, data, lx, ly, lz, LEAVES)
            for _ in range(rng.randint(6, 12)):                 # 잎 가장자리 아래로 늘어진 발광 덩굴
                a, d = rng.uniform(0, 2 * math.pi), rng.uniform(1.5, 3.9)
                vx, vz = round(x + math.cos(a) * d), round(z + math.sin(a) * d)
                for k in range(1, rng.randint(3, 8)):
                    put(cx, cz, data, vx, top - 2 - k, vz, GLOW_VINE)
            return
        trunk = {"oak": rng.randint(4, 6), "spruce": rng.randint(7, 11), "jungle": rng.randint(10, 15),
                 "acacia": rng.randint(4, 5), "swamp": rng.randint(4, 5)}[kind]
        tx, tz = x, z
        for ty in range(1, trunk + 1):
            if kind == "acacia" and ty == trunk - 1:            # 아카시아: 줄기가 옆으로 휜다
                tx += rng.choice((-1, 1)); tz += rng.choice((-1, 0, 1))
            put(cx, cz, data, tx, gh + ty, tz, WOOD, only_air=False)
        top = gh + trunk
        if kind == "spruce":                                     # 원뿔
            for ly in range(gh + 3, top + 2):
                r = min(3.2, (top + 1 - ly) * 0.45 + 0.6)
                for lx in range(x - 3, x + 4):
                    for lz in range(z - 3, z + 4):
                        if (lx - x) ** 2 + (lz - z) ** 2 <= r * r:
                            put(cx, cz, data, lx, ly, lz, LEAVES)
            return
        radius, height = {"oak": (2.6, 2), "jungle": (4.4, 3), "acacia": (3.6, 1), "swamp": (3.4, 2)}[kind]
        for ly in range(top - height + 1, top + 2):
            r = radius - max(0, ly - top) * 1.2
            for lx in range(tx - 5, tx + 6):
                for lz in range(tz - 5, tz + 6):
                    if (lx - tx) ** 2 + (lz - tz) ** 2 <= r * r:
                        put(cx, cz, data, lx, ly, lz, LEAVES)


TOP_TABLE = bytes(0 if i == AIR or i in DECOR_BLOCKS else 1 for i in range(256))


def column_top(world, x, z):
    """(맨 위 블록의 y, 블록 ID) - 풀·꽃은 건너뛴다. 기둥을 바이트열로 한 번에 훑는다"""
    c = world.chunks.get((x >> 4, z >> 4))
    if c is None:
        return 0, BEDROCK
    col = c[((x & 15) << 4) | (z & 15)::256]
    y = col.translate(TOP_TABLE).rfind(b"\x01")
    return (y, col[y]) if y >= 0 else (0, BEDROCK)


def find_spawn(world):
    """원점에서 가까운, 해수면 위 마른 땅 (가까운 고리부터 바깥으로 기후만 계산해서 찾는다)"""
    for radius in range(0, 4000, 8):
        for dx in range(-radius, radius + 1, 8):
            for dz in ((-radius, radius) if abs(dx) != radius else range(-radius, radius + 1, 8)):
                gh, biome = _column(world.climate, dx, dz)
                if biome in ("ocean", "river", "swamp") or not SEA_LEVEL + 1 <= gh < WORLD_H - 24:
                    continue
                world.ensure_around(dx, dz, radius=1)
                y, top = column_top(world, dx, dz)
                if top in (GRASS, SAND, DIRT, SNOW) and abs(y - gh) <= 3:      # 부유섬·첨탑 꼭대기는 피한다
                    return dx + 0.5, float(y + 1), dz + 0.5
    return 0.5, float(WORLD_H - 2), 0.5


# ==============================================================================
# 3. 블록 질의 (충돌, 시야, 레이캐스트)
# ==============================================================================
def is_solid(world, bx, by, bz):
    """바닥 아래와 아직 만들지 않은 청크는 벽으로 취급한다"""
    return world.get(bx, by, bz) not in NON_SOLID_BLOCKS


def block_at(world, x, y, z):
    return world.get(math.floor(x), math.floor(y), math.floor(z))


def body_collides(world, x, y, z, r, h):
    """발 위치 (x, y, z), 반지름 r, 키 h 인 AABB가 고체 블록과 겹치는지"""
    for by in range(math.floor(y), math.floor(y + h - 1e-6) + 1):
        for bx in range(math.floor(x - r), math.floor(x + r - 1e-6) + 1):
            for bz in range(math.floor(z - r), math.floor(z + r - 1e-6) + 1):
                if is_solid(world, bx, by, bz):
                    return True
    return False


def can_see(world, x1, y1, z1, x2, y2, z2):
    """두 점 사이 시선이 불투명 블록에 막히지 않는지"""
    dist = math.dist((x1, y1, z1), (x2, y2, z2))
    steps = int(dist / 0.3) + 1
    for i in range(1, steps):
        t = i / steps
        if block_at(world, x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, z1 + (z2 - z1) * t) not in TRANSPARENT_BLOCKS:
            return False
    return True


def sky_exposed(world, x, y, z):
    bx, bz = math.floor(x), math.floor(z)
    c = world.chunks.get((bx >> 4, bz >> 4))
    if c is None:
        return False
    return not c[(max(0, math.floor(y)) << 8) | ((bx & 15) << 4) | (bz & 15)::256].strip(b"\x00")


def look_vector(yaw, pitch):
    """카메라 시선 단위 벡터 (pitch 양수 = 위)"""
    ry, rp = math.radians(yaw), math.radians(pitch)
    return math.sin(ry) * math.cos(rp), math.sin(rp), -math.cos(ry) * math.cos(rp)


def raycast_blocks(world, ox, oy, oz, dx, dy, dz, max_dist):
    """DDA 복셀 레이캐스트 → (맞은 블록, 바로 앞 빈 칸, 거리). 못 맞추면 (None, None, inf)"""
    x, y, z = math.floor(ox), math.floor(oy), math.floor(oz)

    def setup(o, d, c):
        if d > 0:
            return (c + 1 - o) / d, 1 / d, 1
        if d < 0:
            return (o - c) / -d, -1 / d, -1
        return math.inf, math.inf, 0

    tx, ddx, sx = setup(ox, dx, x)
    ty, ddy, sy = setup(oy, dy, y)
    tz, ddz, sz = setup(oz, dz, z)
    prev = None
    t = 0.0
    while t <= max_dist:
        if 0 <= y < WORLD_H and world.get(x, y, z) not in (AIR, WATER):
            return (x, y, z), prev, t
        prev = (x, y, z)
        if tx <= ty and tx <= tz:
            x += sx; t = tx; tx += ddx
        elif ty <= tz:
            y += sy; t = ty; ty += ddy
        else:
            z += sz; t = tz; tz += ddz
    return None, None, math.inf


def ray_box(ox, oy, oz, dx, dy, dz, box_min, box_max):
    """광선과 AABB 교차 거리 (없으면 None)"""
    t_near, t_far = 0.0, math.inf
    for o, d, lo, hi in ((ox, dx, box_min[0], box_max[0]), (oy, dy, box_min[1], box_max[1]),
                         (oz, dz, box_min[2], box_max[2])):
        if abs(d) < 1e-9:
            if o < lo or o > hi:
                return None
            continue
        t1, t2 = (lo - o) / d, (hi - o) / d
        if t1 > t2:
            t1, t2 = t2, t1
        t_near, t_far = max(t_near, t1), min(t_far, t2)
        if t_near > t_far:
            return None
    return t_near


# ==============================================================================
# 4. 빛 - 꼭짓점마다 '하늘빛'(위가 얼마나 트였나)과 '블록빛'(가까운 횃불)을 미리 계산해 두고,
#    셰이더가 매 프레임 해·달 방향, 시간대, 날씨에 맞춰 최종 밝기를 정한다.
# ==============================================================================
LIGHT_RADIUS = max(LIGHT_BLOCKS.values())             # 가장 멀리 가는 블록 빛 거리 (랜턴)
SKY_FALLOFF = 6.0                                     # 지붕 아래로 이만큼 들어가면 하늘빛이 사라진다
OPAQUE_TABLE = bytes(0 if i in TRANSPARENT_BLOCKS else 1 for i in range(256))
LEAF_TABLE = bytes(1 if i == LEAVES else 0 for i in range(256))
CAVE_TABLE = bytes(0 if i == AIR else 1 if i in (STONE, DIRT, GRAVEL, COAL_ORE, IRON_ORE, GOLD_ORE, DIAMOND_ORE, CLAY,
                                                  SANDSTONE, LUMEN_ORE) else 2 for i in range(256))


class LightField:
    """(x0..x1, z0..z1) 기둥들의 '하늘이 시작되는 높이'와 주변 횃불 목록으로 빛을 계산한다"""

    def __init__(self, world, x0, z0, x1, z1):
        self.tops = {}
        for x in range(x0, x1 + 1):
            for z in range(z0, z1 + 1):
                c = world.chunks.get((x >> 4, z >> 4))
                if c is None:
                    self.tops[(x, z)] = (WORLD_H, 0)
                    continue
                col = c[((x & 15) << 4) | (z & 15)::256]
                self.tops[(x, z)] = (col.translate(OPAQUE_TABLE).rfind(b"\x01") + 1,
                                     col.translate(LEAF_TABLE).rfind(b"\x01") + 1)
        # 빛이 짧은 광원은 8칸 격자에 나눠 두고 가까운 칸만 본다 (발광 식물이 많은 곳의 최적화)
        self.big, self.small = [], {}
        for t in world.torches_in(x0 - LIGHT_RADIUS, z0 - LIGHT_RADIUS, x1 + LIGHT_RADIUS, z1 + LIGHT_RADIUS):
            if t[3] <= 8:
                key = (math.floor(t[0]) >> 3, math.floor(t[1]) >> 3, math.floor(t[2]) >> 3)
                self.small.setdefault(key, []).append(t)
            else:
                self.big.append(t)
        self.memo = {}
        self.near = {}
        self.ground = {}               # 원래 지면 높이: 이보다 위는 '야외'
        for x in range(x0, x1 + 1):
            for z in range(z0, z1 + 1):
                h = world.heights.get((x >> 4, z >> 4))
                if h is not None:
                    self.ground[(x, z)] = h[((x & 15) << 4) | (z & 15)]

    def at(self, x, y, z):
        """(하늘빛, 블록빛, 빛 색 r, g, b) - 빛은 0~1"""
        hit = self.memo.get((x, y, z))
        if hit is not None:
            return hit
        ax, az = math.floor(x - 0.5), math.floor(z - 0.5)
        total = best = 0.0
        for cx in (ax, ax + 1):
            for cz in (az, az + 1):
                top, leaf = self.tops.get((cx, cz), (WORLD_H, 0))
                d = top - y
                if d <= 0.3:
                    s = 1.0
                else:
                    s = 1.0 - (d - 0.3) / SKY_FALLOFF
                    if s < 0.0:
                        s = 0.0
                if leaf > y and leaf > top:
                    s *= 0.7                                   # 나뭇잎 그늘
                total += s
                if s > best:
                    best = s
        sky = total * 0.125 + best * 0.5
        if sky < 0.55:                 # 부유섬·아치 아래 야외는 옆에서 하늘빛이 든다 (동굴은 원래 땅보다 아래라 어둡다)
            g = min(self.ground.get((ax, az), WORLD_H), self.ground.get((ax + 1, az + 1), WORLD_H))
            if y >= g - 0.5:
                sky = 0.55
        lights = self.big
        if self.small:
            cell = (math.floor(x) >> 3, math.floor(y) >> 3, math.floor(z) >> 3)
            lights = self.near.get(cell)
            if lights is None:                             # 둘레 27칸의 광원을 한 번만 모아 둔다
                gx, gy, gz = cell
                small = self.small
                lights = self.big + [t for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)
                                     for t in small.get((gx + dx, gy + dy, gz + dz), ())]
                self.near[cell] = lights
        block = wr = wg = wb = ws = 0.0
        for tx, ty, tz, reach, col, _ in lights:
            dx, dy, dz = x - tx, y - ty, z - tz
            d2 = dx * dx + dy * dy + dz * dz
            if d2 < reach * reach:
                v = 1.0 - math.sqrt(d2) / reach
                if v > block:
                    block = v
                w = v * v                                      # 가까운 빛의 색이 더 진하게 섞인다
                wr += col[0] * w; wg += col[1] * w; wb += col[2] * w; ws += w
        hit = (sky, block) + ((wr / ws, wg / ws, wb / ws) if ws else WARM_LIGHT)
        self.memo[(x, y, z)] = hit
        return hit


def sample_light(world, x, y, z):
    """한 점의 (하늘빛, 블록빛) - 몹, 떨어지는 블록 등에 쓴다"""
    fx, fz = math.floor(x), math.floor(z)
    return LightField(world, fx - 1, fz - 1, fx + 1, fz + 1).at(x, y, z)


# 정점마다 넘기는 재질 값 (텍스처 좌표 z): 0 = 일반, 0~1 = 바람에 흔들리는 정도(풀·잎), -1 = 물, 2 = 스스로 빛남
MAT_WATER = -1.0
MAT_GLOW = 2.0
MAT_CLOUD = 3.0

VERTEX_SHADER = """
#version 120
uniform float u_time;
varying vec4 v_color;
varying vec3 v_normal;
varying vec3 v_eye;
varying vec3 v_world;
varying vec2 v_light;
varying float v_mat;
varying vec3 v_lcol;
varying vec4 v_shadow;       // 그림자 지도 좌표
uniform mat4 u_shadow_mat;   // 눈 좌표 → 그림자 지도 좌표
void main() {
    vec4 pos = gl_Vertex;
    v_lcol = gl_SecondaryColor.rgb;
    float mat = gl_MultiTexCoord0.z;
    if (mat > 0.01 && mat < 1.5) {                                   // 풀·나뭇잎: 바람에 흔들림
        float t = u_time * 1.6 + pos.x * 0.35 + pos.z * 0.27;
        pos.x += sin(t) * 0.07 * mat;
        pos.z += cos(t * 0.8 + 1.3) * 0.05 * mat;
    }
    if (mat < -0.5 && gl_Normal.y > 0.5) {                           // 물 윗면: 물결
        pos.y += (sin(u_time * 1.3 + pos.x * 0.6) + cos(u_time * 1.1 + pos.z * 0.7)) * 0.035 - 0.04;
    }
    vec4 eye = gl_ModelViewMatrix * pos;
    v_eye = eye.xyz;
    v_world = pos.xyz;
    v_color = gl_Color;
    v_normal = normalize(gl_NormalMatrix * gl_Normal);
    v_shadow = u_shadow_mat * vec4(eye.xyz + v_normal * (0.06 + 0.003 * length(eye.xyz)), 1.0);   // 법선 쪽으로 살짝 띄워 그림자 얼룩 방지
    v_light = gl_MultiTexCoord0.xy;
    v_mat = mat;
    gl_Position = gl_ProjectionMatrix * eye;
}
"""

FRAGMENT_SHADER = """
#version 120
varying vec4 v_color;
varying vec3 v_normal;
varying vec3 v_eye;
varying vec3 v_world;
varying vec2 v_light;
varying float v_mat;
varying vec3 v_lcol;         // 블록빛 색 (횃불은 주황, 발광 식물은 청록·보라…)
varying vec4 v_shadow;
uniform sampler2DShadow u_shadow_map;
uniform float u_shadow_on;   // 그림자 지도를 쓸 수 있으면 1
uniform float u_hdr;         // 1 이면 밝기를 누르지 않고 내보낸다 (후처리가 톤 매핑)
uniform vec3 u_sun_dir;      // 눈 좌표계의 해 방향
uniform vec3 u_moon_dir;
uniform vec3 u_up;           // 눈 좌표계의 위쪽
uniform vec3 u_sun_color;
uniform vec3 u_moon_color;
uniform vec3 u_ambient;      // 하늘에서 고르게 오는 빛
uniform vec3 u_block_color;  // 횃불 빛 색
uniform float u_hand;        // 손에 든 횃불 (0~1)
uniform float u_flash;       // 번개·폭발
uniform float u_time;
uniform vec3 u_fog_color;
uniform vec2 u_fog;          // 안개 시작, 끝 거리
uniform vec3 u_cam;          // 카메라 월드 위치
uniform float u_lod_clip;    // 먼 지형은 이 거리 안쪽을 그리지 않는다 (진짜 청크가 있는 곳)
uniform vec2 u_far;          // 실루엣이 하늘에 녹아들기 시작하는 거리, 다 녹는 거리

float hash(vec3 p) {
    p = fract(p * 0.3183099 + 0.1);
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}
float noise(vec3 x) {                                                // 표면의 잔 질감
    vec3 i = floor(x);
    vec3 f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(mix(hash(i), hash(i + vec3(1, 0, 0)), f.x), mix(hash(i + vec3(0, 1, 0)), hash(i + vec3(1, 1, 0)), f.x), f.y),
               mix(mix(hash(i + vec3(0, 0, 1)), hash(i + vec3(1, 0, 1)), f.x), mix(hash(i + vec3(0, 1, 1)), hash(i + vec3(1, 1, 1)), f.x), f.y), f.z);
}

float sun_shadow() {
    // 해가 가려졌는지 (0 그늘 ~ 1 햇빛). 다섯 곳을 비교해 경계를 부드럽게, 그림자 범위 끝에서는 서서히 사라진다
    if (u_shadow_on < 0.5) return 1.0;
    vec3 sc = v_shadow.xyz / v_shadow.w;
    float edge = max(abs(sc.x - 0.5), abs(sc.y - 0.5)) * 2.0;
    if (edge >= 1.0 || sc.z >= 1.0) return 1.0;
    float o = 1.2 / 2048.0, z = sc.z - 0.00025;
    float s = shadow2D(u_shadow_map, vec3(sc.xy, z)).r * 2.0
            + shadow2D(u_shadow_map, vec3(sc.xy + vec2(o, o), z)).r + shadow2D(u_shadow_map, vec3(sc.xy + vec2(-o, o), z)).r
            + shadow2D(u_shadow_map, vec3(sc.xy + vec2(o, -o), z)).r + shadow2D(u_shadow_map, vec3(sc.xy + vec2(-o, -o), z)).r;
    return mix(s / 6.0, 1.0, smoothstep(0.82, 1.0, edge));
}

void main() {
    vec3 n = normalize(v_normal);              // 메시를 만들 때 이미 빈 공간 쪽으로 맞춰 둔 법선
    vec3 view = normalize(-v_eye);
    float dist = length(v_eye);
    float sky = v_light.x;
    float block = v_light.y * v_light.y;
    bool water = v_mat < -0.5;
    bool lod = v_mat > 3.5;
    if (lod && length(v_world.xz - u_cam.xz) < u_lod_clip) discard;
    bool cloud = v_mat > 2.5 && !lod;

    if (water) {                                                     // 물결에 따라 법선이 흔들린다
        float t = u_time;
        vec3 w = vec3(cos(t * 1.3 + v_world.x * 0.6) * 0.12, 0.0, -sin(t * 1.1 + v_world.z * 0.7) * 0.12)
               + vec3(sin(v_world.z * 2.3 + t * 2.0), 0.0, cos(v_world.x * 2.1 - t * 1.7)) * 0.04;
        n = normalize(n + gl_NormalMatrix * w);
    }

    float hemi = 0.62 + 0.38 * dot(n, u_up);                         // 위를 보는 면이 더 밝다
    float sun = max(dot(n, u_sun_dir), 0.0);
    float moon = max(dot(n, u_moon_dir), 0.0);
    float sh = (sun > 0.0 && sky > 0.05 && !lod) ? sun_shadow() : 1.0;
    vec3 light = sky * (u_ambient * hemi + u_sun_color * sun * sh + u_moon_color * moon);

    float hand = u_hand * clamp(1.0 - dist / 13.0, 0.0, 1.0);       // 손에 든 횃불: 카메라에서 퍼지는 빛
    hand = pow(hand, 1.5) * (0.6 + 0.4 * max(dot(n, view), 0.0));
    float day = clamp(dot(u_ambient, vec3(0.333)) * 2.2, 0.0, 1.0);   // 낮 정도
    light += max(v_lcol * block * 1.25 * (1.0 - 0.65 * sky * day), u_block_color * hand * 1.4);   // 햇빛 아래선 블록빛이 묻힌다
    light += vec3(0.035, 0.035, 0.045) + vec3(u_flash) * (0.3 + 0.7 * sky);

    if (cloud) light = u_ambient * 1.5 + u_sun_color * (0.45 + 0.35 * sun) + u_moon_color * 0.5 + vec3(0.04);   // 구름은 햇빛이 스며 고르게 밝다
    vec3 base = v_color.rgb;
    if (!water && !cloud) {
        float g = noise(v_world * 3.1) * 0.6 + noise(v_world * 9.7) * 0.4;   // 흙·돌의 얼룩
        base *= 0.86 + 0.26 * g;
    }
    vec3 col = base * light;
    if (v_mat > 1.5 && v_mat < 2.5) {                                     // 스스로 빛나는 것: 밤·동굴일수록 또렷하고 숨쉬듯 깜빡인다
        float dark = max(1.0 - day, 1.0 - sky);
        float pulse = 0.86 + 0.14 * sin(u_time * 1.6 + v_world.x * 0.9 + v_world.z * 0.7 + v_world.y * 0.4);
        col = max(col, base * (0.75 + 0.6 * dark) * pulse);
    }
    float alpha = v_color.a;

    if (water && abs(dot(n, u_up)) < 0.5) {                          // 폭포: 아래로 흘러내리는 흰 물줄기
        float s = noise(vec3((v_world.x + v_world.z) * 3.0, v_world.y * 0.7 + u_time * 4.5, 0.0)) * 0.65
                + noise(vec3((v_world.x - v_world.z) * 7.0, v_world.y * 1.6 + u_time * 7.0, 1.0)) * 0.35;
        col = mix(col, vec3(0.86, 0.92, 0.95) * (light * 0.8 + 0.15), 0.2 + 0.55 * smoothstep(0.45, 0.8, s));
        alpha = max(alpha, 0.82);
    }
    if (water || v_color.a < 0.99) {                                 // 물·유리: 하늘 반사와 햇빛 반짝임
        float fres = pow(1.0 - max(dot(n, view), 0.0), 3.0);
        vec3 skyref = u_fog_color * (0.55 + 0.45 * sky);
        col = mix(col, skyref, fres * 0.75);
        vec3 r = reflect(-u_sun_dir, n);
        col += u_sun_color * pow(max(dot(r, view), 0.0), 64.0) * sky * sh * (1.2 + 2.5 * u_hdr);
        alpha = mix(alpha, 0.95, fres);
    }

    if (u_hdr < 0.5) {                                               // 후처리가 없으면 여기서 밝기를 누른다
        col = col / (1.0 + max(col - 1.0, 0.0) * 0.6);
        float lum = dot(col, vec3(0.299, 0.587, 0.114));
        col = mix(vec3(lum), col, 0.92);
    }

    // 대기 안개: 멀수록 하늘색에 묻히고, 해 쪽은 햇빛을 머금는다
    vec3 fogc = u_fog_color + u_sun_color * 0.25 * pow(max(dot(-view, u_sun_dir), 0.0), 8.0);
    if (!cloud) fogc *= clamp(sky * 1.6, 0.04, 1.0);                 // 동굴 속 안개는 어둡게
    // 멀어질수록 하늘빛에 물든 어두운 실루엣이 되고 (렌더 거리 끝 = 먼 풍경의 시작),
    // 먼 풍경의 실루엣은 더 멀어질수록 하늘에 녹아든다
    vec3 sil = mix(fogc * (0.55 + 0.28 * max(dot(n, u_up), 0.0)), col, 0.22);
    if (cloud) {
        float fc = clamp((dist - 1400.0) / 900.0, 0.0, 1.0);
        gl_FragColor = vec4(mix(col, fogc, fc), alpha * (1.0 - fc));
    } else if (u_hdr > 0.5) {
        // 대기 원근: 멀수록 지평선 하늘빛에 엷게 묻혀 산이 겹겹이 보이고, 먼 풍경 끝에서 하늘에 녹아든다
        float fa = 1.0 - exp(-max(dist - u_fog.x, 0.0) / u_fog.y);
        float ff = smoothstep(u_far.x, u_far.y, dist);
        gl_FragColor = vec4(mix(col, fogc, max(fa * 0.8, ff)), alpha);
    } else {
        float f = smoothstep(u_fog.x, u_fog.y, dist);
        float ff = smoothstep(u_far.x, u_far.y, dist);
        gl_FragColor = vec4(mix(mix(col, sil, f), fogc, ff), alpha);
    }
}
"""


class LightShader:
    """빛 셰이더. 만들 수 없는 환경이면 enabled=False 로 두고 기본 색만 그린다"""

    UNIFORMS = ("u_sun_dir", "u_moon_dir", "u_up", "u_sun_color", "u_moon_color", "u_ambient",
                "u_block_color", "u_hand", "u_flash", "u_fog_color", "u_fog", "u_time", "u_cam", "u_lod_clip", "u_far",
                "u_shadow_mat", "u_shadow_on", "u_hdr")

    def __init__(self):
        self.program = 0
        self.loc = {}
        try:
            from OpenGL.GL import shaders
            self.program = shaders.compileProgram(shaders.compileShader(VERTEX_SHADER, GL_VERTEX_SHADER),
                                                  shaders.compileShader(FRAGMENT_SHADER, GL_FRAGMENT_SHADER),
                                                  validate=False)
            self.loc = {name: glGetUniformLocation(self.program, name) for name in self.UNIFORMS}
            glUseProgram(self.program)
            glUniform1i(glGetUniformLocation(self.program, "u_shadow_map"), 3)   # 그림자 지도는 텍스처 3번
            glUseProgram(0)
        except Exception as e:                                   # 셰이더 미지원 그래픽 환경
            print("빛 셰이더를 만들 수 없어 기본 렌더링으로 그립니다:", e)
            self.program = 0

    @property
    def enabled(self):
        return bool(self.program)

    def use(self, on):
        if self.program:
            glUseProgram(self.program if on else 0)

    def set_frame(self, u):
        """u: 유니폼 이름 → 값(숫자 또는 튜플)"""
        if not self.program:
            return
        glUseProgram(self.program)
        for name, value in u.items():
            loc = self.loc[name]
            if loc < 0:
                continue
            if isinstance(value, (int, float)):
                glUniform1f(loc, value)
            elif len(value) == 2:
                glUniform2f(loc, *value)
            elif len(value) == 16:
                glUniformMatrix4fv(loc, 1, GL_TRUE, value)
            else:
                glUniform3f(loc, *value)
        glUseProgram(0)


# ==============================================================================
# 5. 청크 렌더러 - 8×8 렌더링 청크마다 다각형 메시를 디스플레이 리스트로 만들어 두고,
#    시야 안 청크만 그린다. 지형과 나뭇잎은 네모 대신 다각형 곡면(Surface Nets)으로 그린다.
# ==============================================================================
FACES = (
    # (이웃 방향, 밝기, 윗면 색 사용, 꼭짓점)
    ((0, 1, 0), 1.0, True, ((0, 1, 0), (1, 1, 0), (1, 1, 1), (0, 1, 1))),
    ((0, -1, 0), 0.5, False, ((0, 0, 0), (0, 0, 1), (1, 0, 1), (1, 0, 0))),
    ((0, 0, 1), 0.8, False, ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1))),
    ((0, 0, -1), 0.8, False, ((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0))),
    ((-1, 0, 0), 0.65, False, ((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0))),
    ((1, 0, 0), 0.65, False, ((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1))),
)
BUILD_BUDGET = 0.006                                  # 한 프레임에 청크 메시 만드는 데 쓸 시간 (초). 넘으면 다음 프레임에 이어서

TERRAIN_BLOCKS = {GRASS, DIRT, STONE, SAND, COAL_ORE, IRON_ORE, GOLD_ORE, DIAMOND_ORE, BEDROCK, SNOW, CLAY,
                  GRAVEL, SANDSTONE, ICE, LUMEN_ORE}
FOLIAGE_BLOCKS = {LEAVES}
CUBE_BLOCKS = {BRICK, GLASS, PLANKS, WORKBENCH, TNT, LUMEN_LAMP}   # 사람이 만든 블록만 네모 유지
TERRAIN_TABLE = bytes(1 if i in TERRAIN_BLOCKS else 0 for i in range(256))
FOLIAGE_TABLE = bytes(1 if i in FOLIAGE_BLOCKS else 0 for i in range(256))
CAP_TABLE = bytes(1 if i == GLOW_CAP else 0 for i in range(256))
SPECIAL_TABLE = bytes(0 if i in (AIR, GLOW_CAP) or i in TERRAIN_BLOCKS or i in FOLIAGE_BLOCKS else 1 for i in range(256))
SUPPORT_SIDES = ((0, -1, 0), (0, 1, 0), (1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1))
TERRAIN_JITTER = 0.16                                 # 꼭짓점을 흔들어 각진 바위 같은 면을 만든다
FOLIAGE_JITTER = 0.32
CLAY_BANDS = ((0.66, 0.43, 0.32), (0.74, 0.58, 0.44), (0.56, 0.36, 0.27),
              (0.80, 0.70, 0.56), (0.64, 0.47, 0.35), (0.52, 0.33, 0.26))
OCTAGON = tuple((math.cos(math.pi / 8 + i * math.pi / 4), math.sin(math.pi / 8 + i * math.pi / 4)) for i in range(8))


def _hash3(x, y, z):
    h = ((x * 73856093) ^ (y * 19349663) ^ (z * 83492791)) & 0xFFFFFFFF
    return ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF


def _shade(x, y, z):
    """블록마다 밝기를 살짝 달리해 질감 표현"""
    return 0.9 + _hash3(x, y, z) % 11 / 100.0


def _normal(a, b, c):
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    ln = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    return nx / ln, ny / ln, nz / ln


# 메시의 삼각형 하나 = (색 r,g,b,a, 법선, (꼭짓점 3개), (꼭짓점별 (하늘빛, 블록빛, 재질) 3개))
# 꼭짓점은 언제나 법선 쪽에서 볼 때 반시계 방향으로 둔다 → 뒷면 컬링으로 안 보이는 면을 건너뛸 수 있다
def _tri(out, col, alpha, normal, verts, lf, glow=0.0, mats=(0.0, 0.0, 0.0)):
    a, b, c = verts
    g = _normal(a, b, c)
    if g[0] * normal[0] + g[1] * normal[1] + g[2] * normal[2] < 0:
        verts, mats = (a, c, b), (mats[0], mats[2], mats[1])
    lights = []
    for v, m in zip(verts, mats):
        sky, block, r, g, b = lf.at(*v)
        lights.append((sky, max(block, glow), m, r, g, b))
    out.append(((col[0], col[1], col[2], alpha), normal, verts, lights))


def _quad(out, col, alpha, normal, verts, lf, glow=0.0, mats=(0.0, 0.0, 0.0, 0.0)):
    a, b, c, d = verts
    _tri(out, col, alpha, normal, (a, b, c), lf, glow, (mats[0], mats[1], mats[2]))
    _tri(out, col, alpha, normal, (a, c, d), lf, glow, (mats[0], mats[2], mats[3]))


def _box_quads(out, x, y, z, w, h, d, col, lf, glow=0.0, mat=0.0, faces=None):
    """상자의 면들. faces 를 주면 그 방향의 면만 (보이지 않는 면을 빼서 가볍게)"""
    for normal, _, _, verts in FACES:
        if faces is not None and normal not in faces:
            continue
        _quad(out, col, 1.0, normal, [(x + vx * w, y + vy * h, z + vz * d) for vx, vy, vz in verts], lf, glow,
              (mat,) * 4)


def _grass_tuft(out, x, y, z, h, col, lf, blades=6):
    """풀 한 포기: 가는 풀잎(삼각형) 여러 장을 조금씩 다른 자리·높이·기울기로 (양면).
    뿌리는 고정되고 끝만 바람에 흔들린다"""
    j = _hash3(x, y, z)
    up = (0.0, 1.0, 0.0)                                   # 풀은 땅처럼 위에서 빛을 받게
    for i in range(blades):
        k = _hash3(x + i * 31, y + i * 17, z - i * 13) ^ j
        bx = x + 0.12 + (k & 255) / 255.0 * 0.76
        bz = z + 0.12 + ((k >> 8) & 255) / 255.0 * 0.76
        ang = ((k >> 16) & 255) / 255.0 * math.pi
        lean = (((k >> 24) & 255) / 255.0 - 0.5) * 0.5
        hh = h * (0.6 + ((k >> 4) & 63) / 63.0 * 0.5)
        wx, wz = math.cos(ang) * 0.07, math.sin(ang) * 0.07
        tip = (bx + math.sin(ang) * lean, y + hh, bz - math.cos(ang) * lean)
        shade = 0.82 + ((k >> 10) & 31) / 31.0 * 0.3
        c = (col[0] * shade, col[1] * shade, col[2] * shade)
        a, b = (bx - wx, y, bz - wz), (bx + wx, y, bz + wz)
        for tri, m in (((a, b, tip), (0.0, 0.0, 1.0)), ((b, a, tip), (0.0, 0.0, 1.0))):
            lights = [lf.at(*v)[:2] + (mm,) + lf.at(*v)[2:] for v, mm in zip(tri, m)]
            out.append(((c[0], c[1], c[2], 1.0), up, tri, lights))


def _patch_box(out, x, y, z, side, u, v, w, d, h, col, lf, glow=0.0, mat=0.0):
    """받침 면에 붙은 납작한 조각 (받침 반대쪽 면만). side 는 받침 블록 쪽 방향, (u, v) 는 그 면 위 위치, h 는 두께"""
    sx, sy, sz = side
    outer = ((-sx, -sy, -sz),)
    if sy:
        _box_quads(out, x + u, y if sy < 0 else y + 1 - h, z + v, w, h, d, col, lf, glow, mat, outer)
    elif sx:
        _box_quads(out, x if sx < 0 else x + 1 - h, y + u, z + v, h, w, d, col, lf, glow, mat, outer)
    else:
        _box_quads(out, x + u, y + v, z if sz < 0 else z + 1 - h, w, d, h, col, lf, glow, mat, outer)


SIDE_FACES = ((0, 0, 1), (0, 0, -1), (1, 0, 0), (-1, 0, 0))   # 가는 줄기는 옆면만


class _FixedLight:
    """블록 하나 안의 작은 조각들은 빛을 한 번만 계산해 같이 쓴다 (최적화)"""

    def __init__(self, value):
        self.value = value

    def at(self, x, y, z):
        return self.value


def _glow_plant(out, world, b, x, y, z, lf):
    """빛나는 식물: 이끼, 덩굴, 버섯, 나선초. 빛나는 부분은 스스로 빛나는 재질(MAT_GLOW)"""
    lf = _FixedLight(lf.at(x + 0.5, y + 0.5, z + 0.5))
    j = _hash3(x, y, z)
    bright = BLOCK_COLORS[b]
    if b == GLOW_MOSS:                                   # 붙은 면 위의 어두운 이끼 + 빛나는 알갱이
        side = next((s for s in SUPPORT_SIDES if world.get(x + s[0], y + s[1], z + s[2]) not in NON_SOLID_BLOCKS),
                    (0, -1, 0))
        _patch_box(out, x, y, z, side, 0.03, 0.03, 0.94, 0.94, 0.04, (0.10, 0.24, 0.22), lf)
        for k in range(5):
            q = _hash3(x + k * 7, y - k * 3, z + k * 11)
            s = 0.06 + (q & 7) / 70.0
            _patch_box(out, x, y, z, side, 0.08 + ((q >> 4) & 63) / 80.0, 0.08 + ((q >> 10) & 63) / 80.0,
                       s, s, 0.05 + ((q >> 16) & 7) / 80.0, bright, lf, glow=1.0, mat=MAT_GLOW)
    elif b == GLOW_VINE:                                 # 가는 줄기 몇 가닥 + 빛나는 열매
        end = world.get(x, y - 1, z) != GLOW_VINE
        for k in range(3):
            q = _hash3(x - k * 5, y, z + k * 9)
            sx, sz = x + 0.2 + (q & 63) / 105.0, z + 0.2 + ((q >> 6) & 63) / 105.0
            low = y + (0.15 + ((q >> 12) & 7) / 20.0 if end else 0.0)
            _box_quads(out, sx, low, sz, 0.045, y + 1 - low, 0.045, (0.10, 0.26, 0.26), lf, mat=0.6, faces=SIDE_FACES)
            for m in range(2):
                by = low + ((q >> (15 + m * 3)) & 7) / 9.0 * (y + 0.85 - low)
                _box_quads(out, sx - 0.03, by, sz - 0.03, 0.1, 0.1, 0.1, bright, lf, glow=1.0, mat=MAT_GLOW)
            if end:
                _box_quads(out, sx - 0.05, low - 0.12, sz - 0.05, 0.14, 0.14, 0.14, bright, lf, glow=1.0, mat=MAT_GLOW)
    elif b == GLOW_SHROOM:                               # 버섯 2~4개: 흰 대 + 빛나는 갓
        for k in range(2 + j % 3):
            q = _hash3(x + k * 13, y, z - k * 7)
            mx, mz = x + 0.15 + (q & 63) / 120.0, z + 0.15 + ((q >> 6) & 63) / 120.0
            h = 0.15 + ((q >> 12) & 15) / 40.0
            r = 0.09 + ((q >> 16) & 7) / 50.0
            _box_quads(out, mx + r - 0.03, y, mz + r - 0.03, 0.06, h, 0.06, (0.78, 0.76, 0.72), lf, faces=SIDE_FACES)
            _box_quads(out, mx, y + h, mz, r * 2, 0.07, r * 2, bright, lf, glow=1.0, mat=MAT_GLOW)
            _box_quads(out, mx + r * 0.4, y + h + 0.07, mz + r * 0.4, r * 1.2, 0.05, r * 1.2, bright, lf,
                       glow=1.0, mat=MAT_GLOW)
    else:                                                # 나선초: 위로 감겨 올라가는 빛나는 잎
        cx, cz = x + 0.5, z + 0.5
        _box_quads(out, cx - 0.03, y, cz - 0.03, 0.06, 1.2, 0.06, (0.32, 0.18, 0.14), lf, mat=0.5, faces=SIDE_FACES)
        a0 = (j & 255) / 40.0
        for k in range(12):
            a = a0 + k * 0.62
            t = k / 11.0
            rr = 0.26 - t * 0.12
            c = (bright[0], bright[1] * (0.6 + 0.6 * t), bright[2] * (0.7 + 0.8 * t))
            _box_quads(out, cx + math.cos(a) * rr - 0.06, y + 0.1 + k * 0.1, cz + math.sin(a) * rr - 0.06,
                       0.12, 0.05, 0.12, c, lf, glow=1.0, mat=MAT_GLOW)


def _prism(out, cx, cz, y0, y1, r, side_col, cap_col, top_cap, bottom_cap, lf):
    """세로로 선 팔각기둥 (나무 줄기, 선인장)"""
    pts = [(cx + ox * r, cz + oz * r) for ox, oz in OCTAGON]
    for i in range(8):
        (ax, az), (bx, bz) = pts[i], pts[(i + 1) % 8]
        mid = math.pi / 4 * (i + 1)
        _quad(out, side_col, 1.0, (math.cos(mid), 0.0, math.sin(mid)),
              [(ax, y0, az), (bx, y0, bz), (bx, y1, bz), (ax, y1, az)], lf)    # _tri 가 감김 방향을 맞춘다
    for cap, y, ny in ((top_cap, y1, 1.0), (bottom_cap, y0, -1.0)):
        if cap:
            for i in range(8):
                (ax, az), (bx, bz) = pts[i], pts[(i + 1) % 8]
                _tri(out, cap_col, 1.0, (0.0, ny, 0.0), ((cx, y, cz), (ax, y, az), (bx, y, bz)), lf)


def _terrain_color(world, bid, ny, wy, x, z):
    """지형 색: 경사(ny), 높이(wy), 바이옴(x, z)에 따라 달라진다"""
    if bid == GRASS:
        grass, dirt = BIOME_GRASS.get(world.biome_at(x, z), BLOCK_COLORS[GRASS][0]), BLOCK_COLORS[DIRT]
        t = _clamp01((ny - 0.3) / 0.3)
        return _lerp(dirt[0], grass[0], t), _lerp(dirt[1], grass[1], t), _lerp(dirt[2], grass[2], t)
    if bid == SNOW:
        return BLOCK_COLORS[SNOW] if ny > 0.35 else BLOCK_COLORS[STONE]   # 가파른 절벽엔 눈이 안 쌓인다
    if bid == CLAY:
        return CLAY_BANDS[int(wy / 2) % len(CLAY_BANDS)]                  # 메사의 줄무늬 지층
    return block_face_colors(bid)[0]


def _cap_color(world, bid, ny, wy, x, z):
    """발광 버섯갓: 위는 푸른 보랏빛에 하늘색 반점, 아래(주름)는 어둡게"""
    top, under = BLOCK_COLORS[GLOW_CAP]
    if ny < -0.2:
        return under
    if _hash3(x, int(wy * 2), z) % 7 == 0:
        return 0.30, 0.62, 0.78
    return top


def _foliage_color(world, bid, ny, wy, x, z):
    g = BIOME_GRASS.get(world.biome_at(x, z), BLOCK_COLORS[LEAVES])
    return g[0] * 0.8, g[1] * 0.92, g[2] * 0.8


def _changes(col):
    """0/1 바이트열에서 값이 바뀌는 칸 번호 목록 (C 속도의 find 로 건너뛰며 찾는다)"""
    out, v, pos = [], col[0], 0
    while True:
        pos = col.find(b"\x00" if v else b"\x01", pos)
        if pos < 0:
            return out
        out.append(pos)
        v ^= 1


def _diff_spans(a, ca, b, cb):
    """두 기둥 a, b 의 값이 다른 높이 구간들 (y 범위). 바뀌는 지점 사이에서는 둘 다 값이 일정하다"""
    spans, p = [], 0
    for q in sorted(set(ca) | set(cb)) + [len(a)]:
        if q > p and a[p] != b[p]:
            spans.append((p - 2, q - 3))
        p = q
    return spans


def _surface_mesh(world, rx, rz, table, floor_solid, jitter, color_fn, lf, out, mat=0.0):
    """Surface Nets: 블록 경계면을 이웃 블록과 이어진 매끄러운 다각형 면으로 바꾼다.

    블록 중심을 표본점으로 보고, 표본 8개로 둘러싸인 칸마다 꼭짓점 하나를
    '경계를 지나는 모서리들의 중점 평균' 위치에 둔다. 서로 다른 두 블록 사이의
    모서리마다 그 모서리를 둘러싼 칸 4개의 꼭짓점을 이어 면을 만든다.
    """
    x0, z0 = rx * CHUNK_SIZE, rz * CHUNK_SIZE
    ox, oz = x0 - 1, z0 - 1
    span = CHUNK_SIZE + 2
    pad_lo = b"\x01\x01" if floor_solid else b"\x00\x00"
    below = b"\x00" if floor_solid else b"\x01"
    # 청크 + 테두리 1칸의 기둥마다 '이 무리에 속하는가'를 0/1 바이트열로 (칸 번호 = y + 2)
    cols, changes, hi = [], [], -1
    for x in range(ox, ox + span):
        row, crow = [], []
        for z in range(oz, oz + span):
            raw = world.chunks[(x >> 4, z >> 4)][((x & 15) << 4) | (z & 15)::256]
            col = pad_lo + raw.translate(table) + b"\x00\x00"
            hi = max(hi, col.rfind(b"\x01"))
            row.append(col)
            crow.append(_changes(col))
        cols.append(row)
        changes.append(crow)
    if hi < 0:
        return

    verts, vlight = {}, {}

    def V(i, j, k):
        key = (i, j, k)
        v = verts.get(key)
        if v is not None:
            return v
        a0, a1 = cols[i - ox], cols[i + 1 - ox]
        jj = j + 2
        c = (((a0[k - oz][jj], a0[k + 1 - oz][jj]), (a0[k - oz][jj + 1], a0[k + 1 - oz][jj + 1])),
             ((a1[k - oz][jj], a1[k + 1 - oz][jj]), (a1[k - oz][jj + 1], a1[k + 1 - oz][jj + 1])))
        sx = sy = sz = 0.0
        n = 0
        for b in (0, 1):
            for e in (0, 1):
                if c[0][b][e] != c[1][b][e]:
                    sx += 0.5; sy += b; sz += e; n += 1
        for a in (0, 1):
            for e in (0, 1):
                if c[a][0][e] != c[a][1][e]:
                    sx += a; sy += 0.5; sz += e; n += 1
        for a in (0, 1):
            for b in (0, 1):
                if c[a][b][0] != c[a][b][1]:
                    sx += a; sy += b; sz += 0.5; n += 1
        h = _hash3(i, j, k)
        jx = ((h & 255) / 255.0 - 0.5) * 2 * jitter
        jy = (((h >> 8) & 255) / 255.0 - 0.5) * 1.2 * jitter
        jz = (((h >> 16) & 255) / 255.0 - 0.5) * 2 * jitter
        n = n or 1
        v = (i + 0.5 + sx / n + jx, j + 0.5 + sy / n + jy, k + 0.5 + sz / n + jz)
        verts[key] = v
        lt = lf.at(*v)
        vlight[v] = lt[:2] + (mat,) + lt[2:]
        return v

    def emit(cells, sx, sy, sz, reverse):
        """cells 는 모서리를 한 바퀴 도는 칸 4개. reverse 면 반대로 돌아 면이 빈 공간 쪽을 보게 한다
        (삼각형 모양이 아니라 모서리 방향으로 앞뒤를 정해야 가늘게 휜 삼각형도 뒤집히지 않는다)"""
        bid = world.get(sx, min(max(sy, 0), WORLD_H - 1), sz)
        q = [V(*c) for c in (cells[::-1] if reverse else cells)]
        for tri in ((q[0], q[1], q[2]), (q[0], q[2], q[3])):
            nx, ny, nz = _normal(*tri)
            col = color_fn(world, bid, ny, (tri[0][1] + tri[1][1] + tri[2][1]) / 3, sx, sz)
            k = 0.94 + _hash3(sx, sy, sz) % 13 / 100.0                     # 면마다 살짝 다른 밝기 (각진 느낌)
            out.append(((col[0] * k, col[1] * k, col[2] * k, 1.0), (nx, ny, nz), tri,
                        [vlight[v] for v in tri]))

    for x in range(x0, x0 + CHUNK_SIZE):
        yield                                            # 한 줄마다 쉬어 간다 (프레임이 끊기지 않게)
        here, nxt = cols[x - ox], cols[x + 1 - ox]
        ch_here, ch_nxt = changes[x - ox], changes[x + 1 - ox]
        for z in range(z0, z0 + CHUNK_SIZE):
            col, col_x, col_z = here[z - oz], nxt[z - oz], here[z + 1 - oz]
            cc = ch_here[z - oz]
            # 면이 생길 수 있는 높이만 훑는다: 이 기둥의 값이 바뀌는 곳 + 옆 기둥과 값이 다른 구간
            spans = [(t - 3, t - 3) for t in cc]
            spans += _diff_spans(col, cc, col_x, ch_nxt[z - oz])
            spans += _diff_spans(col, cc, col_z, ch_here[z + 1 - oz])
            spans.sort()
            ys, last = [], -10
            for a, b in spans:
                a, b = max(a, -1, last + 1), min(b, WORLD_H - 1)
                if a <= b:
                    ys.append(range(a, b + 1))
                    last = b
            for y in (y for r in ys for y in r):
                s = col[y + 2]
                # 칸 순서대로 돌면 면의 앞쪽이 X모서리는 +x, Y모서리는 -y, Z모서리는 +z 를 본다
                if s != col_x[y + 2]:
                    src = (x, y, z) if s else (x + 1, y, z)
                    emit(((x, y - 1, z - 1), (x, y, z - 1), (x, y, z), (x, y - 1, z)), *src, not s)
                if s != col[y + 3]:
                    src = (x, y, z) if s else (x, y + 1, z)
                    emit(((x - 1, y, z - 1), (x, y, z - 1), (x, y, z), (x - 1, y, z)), *src, s)
                if s != col_z[y + 2]:
                    src = (x, y, z) if s else (x, y, z + 1)
                    emit(((x - 1, y - 1, z), (x, y - 1, z), (x, y, z), (x - 1, y, z)), *src, not s)


def _block_meshes(world, rx, rz, lf, opaque, translucent):
    """지형·나뭇잎이 아닌 블록: 물, 나무 줄기, 선인장, 횃불, 사람이 만든 네모 블록"""
    get = world.get
    for x in range(rx * CHUNK_SIZE, (rx + 1) * CHUNK_SIZE):
        yield
        for z in range(rz * CHUNK_SIZE, (rz + 1) * CHUNK_SIZE):
            raw = world.chunks[(x >> 4, z >> 4)][((x & 15) << 4) | (z & 15)::256]
            special = raw.translate(SPECIAL_TABLE)
            y = special.find(b"\x01")
            while y >= 0:
                b = raw[y]
                below, above = get(x, y - 1, z), get(x, y + 1, z)
                if b == TORCH:
                    _box_quads(opaque, x + 0.44, y, z + 0.44, 0.12, 0.5, 0.12, (0.55, 0.38, 0.2), lf)
                    _box_quads(opaque, x + 0.42, y + 0.5, z + 0.42, 0.16, 0.14, 0.16, (1.0, 0.85, 0.45), lf,
                               glow=1.0, mat=MAT_GLOW)
                elif b == LANTERN:
                    _box_quads(opaque, x + 0.3, y, z + 0.3, 0.4, 0.06, 0.4, (0.25, 0.25, 0.28), lf)
                    _box_quads(opaque, x + 0.33, y + 0.06, z + 0.33, 0.34, 0.38, 0.34, (1.0, 0.82, 0.45), lf,
                               glow=1.0, mat=MAT_GLOW)
                    _box_quads(opaque, x + 0.3, y + 0.44, z + 0.3, 0.4, 0.08, 0.4, (0.25, 0.25, 0.28), lf)
                elif b == CRYSTAL:                                       # 수정 결정 몇 개
                    j = _hash3(x, y, z)
                    for k in range(3):
                        ox, oz = ((j >> (k * 4)) & 15) / 30.0 + 0.2, ((j >> (k * 4 + 2)) & 15) / 30.0 + 0.2
                        h = 0.5 + ((j >> (k * 3)) & 7) / 10.0
                        _box_quads(opaque, x + ox, y, z + oz, 0.14, h, 0.14, BLOCK_COLORS[CRYSTAL], lf,
                                   glow=1.0, mat=MAT_GLOW)
                elif b == TALL_GRASS:
                    g = BIOME_GRASS.get(world.biome_at(x, z), BLOCK_COLORS[TALL_GRASS])
                    _grass_tuft(opaque, x, y, z, 0.55 + (_hash3(x, y, z) % 30) / 100.0, g, lf)
                elif b in (FLOWER_RED, FLOWER_YELLOW):
                    _grass_tuft(opaque, x, y, z, 0.5, (0.3, 0.55, 0.2), lf, blades=3)
                    _box_quads(opaque, x + 0.38, y + 0.45, z + 0.38, 0.24, 0.16, 0.24, BLOCK_COLORS[b], lf, mat=1.0)
                elif b in GLOW_PLANTS:
                    _glow_plant(opaque, world, b, x, y, z, lf)
                elif b in (WOOD, CACTUS, SHROOM_STEM):
                    top, side = block_face_colors(b)
                    y0 = y - 1.0 if below in TERRAIN_BLOCKS else y      # 비탈에서도 땅에 박히도록
                    r = {WOOD: 0.3, CACTUS: 0.4, SHROOM_STEM: 0.45}[b]
                    _prism(opaque, x + 0.5, z + 0.5, y0, y + 1, r, side, top, above != b, below != b and y0 == y, lf)
                elif b == WATER:
                    top_y = y + 1 if above == WATER else y + 0.88
                    for normal, _, _, vs in FACES:
                        n = get(x + normal[0], y + normal[1], z + normal[2])
                        if normal[1] < 0 or n == WATER or (normal[1] == 0 and n != AIR):
                            continue                             # 옆면은 공기 쪽만 (물가 윤곽선 방지)
                        _quad(translucent, BLOCK_COLORS[WATER], BLOCK_ALPHA[WATER], normal,
                              [(x + vx, y + (top_y - y) * vy, z + vz) for vx, vy, vz in vs], lf,
                              mats=(MAT_WATER,) * 4)
                else:                                            # 네모 블록 (벽돌, 유리, 목재, 작업대)
                    top, side = block_face_colors(b)
                    alpha = BLOCK_ALPHA.get(b, 1.0)
                    out = translucent if alpha < 1.0 else opaque
                    s = _shade(x, y, z)
                    glow, mats = (1.0, (MAT_GLOW,) * 4) if b == LUMEN_LAMP else (0.0, (0.0,) * 4)
                    for normal, _, use_top, vs in FACES:
                        n = get(x + normal[0], y + normal[1], z + normal[2])
                        if n == b or (n in CUBE_BLOCKS and n != GLASS):
                            continue
                        c = top if use_top else side
                        _quad(out, (c[0] * s, c[1] * s, c[2] * s), alpha, normal,
                              [(x + vx, y + vy, z + vz) for vx, vy, vz in vs], lf, glow, mats)
                y = special.find(b"\x01", y + 1)


def iter_chunk_mesh(world, rx, rz, opaque, translucent):
    """렌더링 청크 하나의 (불투명, 반투명) 삼각형을 조금씩 만든다. 사이사이 멈추므로 여러 프레임에 나눠 만들 수 있다"""
    x0, z0 = rx * CHUNK_SIZE, rz * CHUNK_SIZE
    lf = LightField(world, x0 - 2, z0 - 2, x0 + CHUNK_SIZE + 1, z0 + CHUNK_SIZE + 1)
    yield
    yield from _surface_mesh(world, rx, rz, TERRAIN_TABLE, True, TERRAIN_JITTER, _terrain_color, lf, opaque)
    yield from _surface_mesh(world, rx, rz, FOLIAGE_TABLE, False, FOLIAGE_JITTER, _foliage_color, lf, opaque, mat=0.35)
    yield from _surface_mesh(world, rx, rz, CAP_TABLE, False, FOLIAGE_JITTER * 0.5, _cap_color, lf, opaque,
                             mat=MAT_GLOW)
    yield from _block_meshes(world, rx, rz, lf, opaque, translucent)


def build_chunk_mesh(world, rx, rz):
    """렌더링 청크 하나의 (불투명, 반투명) 삼각형 목록 (한 번에)"""
    opaque, translucent = [], []
    for _ in iter_chunk_mesh(world, rx, rz, opaque, translucent):
        pass
    return opaque, translucent


STRIDE = 16 * 4               # 정점 하나 = 위치3 + 색4 + 법선3 + (하늘빛, 블록빛, 재질) + 블록빛 색3
ARRAY_STATES = (GL_VERTEX_ARRAY, GL_COLOR_ARRAY, GL_NORMAL_ARRAY, GL_TEXTURE_COORD_ARRAY, GL_SECONDARY_COLOR_ARRAY)


def _pack(tris):
    """삼각형 목록 → 정점 데이터 배열 (위치3, 색4, 법선3, 빛3, 빛 색3)"""
    pad = WARM_LIGHT
    return array("f", chain.from_iterable(v + c + n + (l if len(l) == 6 else l + pad)
                                          for c, n, verts, lights in tris for v, l in zip(verts, lights)))


def _upload_array(data):
    vbo = glGenBuffers(1)
    glBindBuffer(GL_ARRAY_BUFFER, vbo)
    glBufferData(GL_ARRAY_BUFFER, len(data) * 4, data.tobytes(), GL_STATIC_DRAW)
    glBindBuffer(GL_ARRAY_BUFFER, 0)
    return vbo, len(data) // 16


BAND = 16                     # 청크 메시를 이 높이 단위 띠로 나눠 두고, 안 보이는 높이의 띠는 그리지 않는다


def _upload(tris, banded=False):
    """삼각형 목록 → 그래픽 카드 정점 버퍼(VBO). (버퍼 번호, 정점 수, 띠 목록) 반환.
    banded 면 삼각형을 높이 띠 순서로 정렬하고 띠마다 (띠 번호, 첫 정점, 정점 수) 를 기록한다"""
    if not tris:
        return 0, 0, None
    bands = None
    if banded:
        keyed = sorted(((int(min(t[2][0][1], t[2][1][1], t[2][2][1])) // BAND, t) for t in tris), key=lambda e: e[0])
        tris = [t for _, t in keyed]
        bands, first, cur = [], 0, keyed[0][0]
        for k, (b, _) in enumerate(keyed):
            if b != cur:
                bands.append((cur, first * 3, (k - first) * 3))
                cur, first = b, k
        bands.append((cur, first * 3, (len(keyed) - first) * 3))
    data = _pack(tris)
    vbo = glGenBuffers(1)
    glBindBuffer(GL_ARRAY_BUFFER, vbo)
    glBufferData(GL_ARRAY_BUFFER, len(data) * 4, data.tobytes(), GL_STATIC_DRAW)
    glBindBuffer(GL_ARRAY_BUFFER, 0)
    return vbo, len(data) // 16, bands


_OFFSETS = tuple(ctypes.c_void_p(k) for k in (0, 12, 28, 40, 52))


def _draw_buffer(vbo, count):
    """청크마다 부르므로 PyOpenGL 포장 없이 GL 함수를 바로 부른다 (최적화)"""
    if not count:
        return
    p0, p1, p2, p3, p4 = _OFFSETS
    _gl_bind_buffer(GL_ARRAY_BUFFER, vbo)
    _gl_vertex_ptr(3, GL_FLOAT, STRIDE, p0)
    _gl_color_ptr(4, GL_FLOAT, STRIDE, p1)
    _gl_normal_ptr(GL_FLOAT, STRIDE, p2)
    _gl_tex_ptr(3, GL_FLOAT, STRIDE, p3)
    _gl_lcol_ptr(3, GL_FLOAT, STRIDE, p4)
    _gl_draw_arrays(GL_TRIANGLES, 0, count)


def _draw_bands(vbo, count, bands, ylo, yhi):
    """청크 메시 중 높이 ylo ~ yhi 에 걸치는 띠만 그린다 (붙어 있는 띠는 한 번에)"""
    if not count:
        return
    if bands is None or (bands[0][0] * BAND >= ylo and (bands[-1][0] + 1) * BAND <= yhi):
        _draw_buffer(vbo, count)
        return
    start = end = -1
    for b, first, n in bands:
        if b * BAND - 4 <= yhi and (b + 1) * BAND + 4 >= ylo:
            if start < 0:
                start = first
            end = first + n
    if start >= 0:
        p0, p1, p2, p3, p4 = _OFFSETS
        _gl_bind_buffer(GL_ARRAY_BUFFER, vbo)
        _gl_vertex_ptr(3, GL_FLOAT, STRIDE, p0)
        _gl_color_ptr(4, GL_FLOAT, STRIDE, p1)
        _gl_normal_ptr(GL_FLOAT, STRIDE, p2)
        _gl_tex_ptr(3, GL_FLOAT, STRIDE, p3)
        _gl_lcol_ptr(3, GL_FLOAT, STRIDE, p4)
        _gl_draw_arrays(GL_TRIANGLES, start, end - start)


def draw_client_arrays(data, mode=GL_QUADS):
    """파이썬 배열(정점마다 위치3 + 색3 + 법선3 + (하늘빛, 블록빛, 재질)3)을 한 번에 그린다 (몹 등)"""
    n = len(data) // 12
    if not n:
        return
    buf = (ctypes.c_float * len(data)).from_buffer(data)
    base = ctypes.addressof(buf)
    stride = 48
    _gl_bind_buffer(GL_ARRAY_BUFFER, 0)
    for state in (GL_VERTEX_ARRAY, GL_COLOR_ARRAY, GL_NORMAL_ARRAY, GL_TEXTURE_COORD_ARRAY):
        glEnableClientState(state)
    _gl_vertex_ptr(3, GL_FLOAT, stride, ctypes.c_void_p(base))
    _gl_color_ptr(3, GL_FLOAT, stride, ctypes.c_void_p(base + 12))
    _gl_normal_ptr(GL_FLOAT, stride, ctypes.c_void_p(base + 24))
    _gl_tex_ptr(3, GL_FLOAT, stride, ctypes.c_void_p(base + 36))
    _gl_draw_arrays(mode, 0, n)
    for state in (GL_VERTEX_ARRAY, GL_COLOR_ARRAY, GL_NORMAL_ARRAY, GL_TEXTURE_COORD_ARRAY):
        glDisableClientState(state)


def _delete_buffers(mesh):
    ids = [v for v in (mesh[0], mesh[3]) if v]
    if ids:
        glDeleteBuffers(len(ids), ids)


def box_tris(x, y, z, w, h, d, col, alpha, light, skip=()):
    """조명이 고정된 상자 하나의 삼각형 목록 (구름 등). skip 에 든 방향의 면은 뺀다"""
    tris = []
    for normal, _, _, verts in FACES:
        if normal in skip:
            continue
        a, b, c, e = [(x + vx * w, y + vy * h, z + vz * d) for vx, vy, vz in verts]
        for tri in ((a, b, c), (a, c, e)):
            g = _normal(*tri)
            if g[0] * normal[0] + g[1] * normal[1] + g[2] * normal[2] < 0:
                tri = (tri[0], tri[2], tri[1])
            tris.append(((col[0], col[1], col[2], alpha), normal, tri, (light, light, light)))
    return tris


def upload_mesh(tris):
    return _upload(tris)[:2]


def draw_mesh(mesh):
    for state in ARRAY_STATES:
        glEnableClientState(state)
    _draw_buffer(*mesh)
    for state in ARRAY_STATES:
        glDisableClientState(state)
    glBindBuffer(GL_ARRAY_BUFFER, 0)


def delete_mesh(mesh):
    if mesh and mesh[0]:
        glDeleteBuffers(1, [mesh[0]])


class ChunkRenderer:
    def __init__(self):
        self.lists = {}          # (rx, rz) -> (불투명 버퍼, 정점 수, 반투명 버퍼, 정점 수)
        self.dirty = set()       # 다시 만들어야 하는 렌더링 청크
        self.visible_count = 0
        self.pending = None      # 만들고 있는 청크: (key, 진행기, 불투명, 반투명)
        self.missing_dist = 1e9  # 아직 못 만든 가장 가까운 청크까지 거리 (그 안쪽까지 먼 지형이 메운다)
        self.missing_count = 0

    def reset(self):
        """월드가 통째로 바뀌었을 때 (새 게임 / 불러오기)"""
        self.release()
        self.dirty.clear()
        self.pending = None

    def release(self):
        for mesh in self.lists.values():
            _delete_buffers(mesh)
        self.lists.clear()

    def mark_dirty(self, x, z):
        """블록이 바뀐 청크와, 경계면 꼭짓점·빛을 함께 쓰는 이웃 청크(대각선 포함)를 다시 만들도록 표시"""
        self.mark_radius(x, z, 2)

    def mark_radius(self, x, z, r):
        """(x, z) 에서 r 칸 안에 걸치는 렌더링 청크를 모두 다시 만든다 (횃불을 놓거나 치웠을 때)"""
        for rx in range((x - r) // CHUNK_SIZE, (x + r) // CHUNK_SIZE + 1):
            for rz in range((z - r) // CHUNK_SIZE, (z + r) // CHUNK_SIZE + 1):
                self.dirty.add((rx, rz))

    def mark_generated(self, gcx, gcz):
        """새 생성 청크가 생기면 그 위와 테두리 렌더링 청크를 다시 만든다"""
        per = GEN_CHUNK // CHUNK_SIZE
        for rx in range(gcx * per - 1, gcx * per + per + 1):
            for rz in range(gcz * per - 1, gcz * per + per + 1):
                if (rx, rz) in self.lists:
                    self.dirty.add((rx, rz))

    @staticmethod
    def ready(world, rx, rz):
        x0, z0 = rx * CHUNK_SIZE, rz * CHUNK_SIZE
        return world.has_area(x0 - 2, z0 - 2, x0 + CHUNK_SIZE + 1, z0 + CHUNK_SIZE + 1)

    def prebuild(self, world, x, z, progress=None, radius=RENDER_DISTANCE):
        """게임 시작 전에 플레이어 주변 radius 청크를 미리 만든다 (로딩 화면). 나머지는 게임 중에 이어서 만든다"""
        crx, crz = math.floor(x) // CHUNK_SIZE, math.floor(z) // CHUNK_SIZE
        keys = [(crx + dx, crz + dz) for dx in range(-radius, radius + 1)
                for dz in range(-radius, radius + 1)
                if dx * dx + dz * dz <= (radius + 0.5) ** 2]
        for i, (rx, rz) in enumerate(keys):
            if self.ready(world, rx, rz):
                self._build(world, rx, rz)
                self.dirty.discard((rx, rz))
            if progress and i % 12 == 0:
                progress(i / len(keys))

    def _build(self, world, rx, rz):
        opaque, translucent = build_chunk_mesh(world, rx, rz)
        old = self.lists.get((rx, rz))
        if old:
            _delete_buffers(old)
        self.lists[(rx, rz)] = _upload(opaque, True) + _upload(translucent, True)

    def draw(self, world, cam_x, cam_z, yaw, pitch=0.0, cam_y=0.0, ceiling=math.inf):
        """렌더 거리 안 + 화면 시야각 안의 청크만, 그중에서도 화면 위아래로 보이는 높이 띠만 그린다.
        ceiling 보다 높은 띠는 그리지 않는다 (깊은 동굴 속에선 머리 위 땅을 건너뛴다). 그린 (청크, 높이 범위) 목록 반환"""
        fx, fz = math.sin(math.radians(yaw)), -math.cos(math.radians(yaw))
        # 가로 시야각(약 94도)의 절반 + 여유. 위/아래를 많이 볼수록 넓게 잡는다
        half_fov = math.radians(52 + max(0.0, abs(pitch) - 30) * 1.5)
        crx, crz = math.floor(cam_x) // CHUNK_SIZE, math.floor(cam_z) // CHUNK_SIZE
        limit = (RENDER_DISTANCE + 0.5) * CHUNK_SIZE
        candidates = []
        for rx in range(crx - RENDER_DISTANCE, crx + RENDER_DISTANCE + 1):
            for rz in range(crz - RENDER_DISTANCE, crz + RENDER_DISTANCE + 1):
                mx = (rx + 0.5) * CHUNK_SIZE - cam_x
                mz = (rz + 0.5) * CHUNK_SIZE - cam_z
                dist = math.hypot(mx, mz)
                if dist > limit:
                    continue
                if dist > CHUNK_SIZE * 1.5 and half_fov < math.pi:              # 화면 밖 청크 생략
                    ang = math.acos(max(-1.0, min(1.0, (mx * fx + mz * fz) / dist)))
                    if ang - math.asin(min(1.0, CHUNK_SIZE * 0.75 / dist)) > half_fov:
                        continue
                candidates.append((dist, rx, rz))
        candidates.sort()

        # 메시 만들기: 한 줄씩 만들다가 이번 프레임 예산을 다 쓰면 다음 프레임에 이어서 만든다
        missing = [d for d, rx, rz in candidates if (rx, rz) not in self.lists]
        self.missing_dist = missing[0] if missing else 1e9
        self.missing_count = len(missing)
        need = [(rx, rz) for _, rx, rz in candidates
                if ((rx, rz) in self.dirty or (rx, rz) not in self.lists) and self.ready(world, rx, rz)]
        budget = BUILD_BUDGET * (2 if len(need) > 20 else 1)        # 할 일이 많으면 (막 불러왔을 때) 더 빨리
        start = time.perf_counter()
        todo = iter(need)
        while time.perf_counter() - start < budget:
            if self.pending is None:
                key = next(todo, None)
                if key is None:
                    break
                self.dirty.discard(key)                  # 만드는 사이에 또 바뀌면 다시 표시된다
                opaque, translucent = [], []
                self.pending = (key, iter_chunk_mesh(world, key[0], key[1], opaque, translucent), opaque, translucent)
            key, steps, opaque, translucent = self.pending
            if next(steps, False) is False:              # 다 만들었으면 그래픽 카드로
                old = self.lists.get(key)
                if old:
                    _delete_buffers(old)
                self.lists[key] = _upload(opaque, True) + _upload(translucent, True)
                self.pending = None

        # 화면 위·아래 끝 각도 (세로 시야각 절반 35도 + 화면 모서리 여유)
        up, lo = math.radians(pitch + 50), math.radians(pitch - 50)
        t_up = math.tan(up) if up < math.radians(89) else None
        t_lo = math.tan(lo) if lo > math.radians(-89) else None
        drawn = []
        for dist, rx, rz in candidates:
            if (rx, rz) not in self.lists:
                continue
            dn, df = max(0.0, dist - CHUNK_SIZE * 0.75), dist + CHUNK_SIZE * 0.75
            if dn < 1.0:
                ylo, yhi = -math.inf, math.inf
            else:
                yhi = math.inf if t_up is None else cam_y + (df if t_up >= 0 else dn) * t_up
                ylo = -math.inf if t_lo is None else cam_y + (df if t_lo <= 0 else dn) * t_lo
            drawn.append(((rx, rz), ylo, min(yhi, ceiling)))
        glEnable(GL_CULL_FACE)                                   # 안 보이는 뒷면은 그리지 않는다
        for state in ARRAY_STATES:
            glEnableClientState(state)
        lists = self.lists
        for key, ylo, yhi in drawn:
            mesh = lists[key]
            _draw_bands(mesh[0], mesh[1], mesh[2], ylo, yhi)
        for state in ARRAY_STATES:
            glDisableClientState(state)
        glDisable(GL_CULL_FACE)
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        self.visible_count = len(drawn)

        # 멀리 벗어난 청크의 메시는 지운다
        far = RENDER_DISTANCE + 3
        for key in [k for k in self.lists if abs(k[0] - crx) > far or abs(k[1] - crz) > far]:
            _delete_buffers(self.lists.pop(key))
            self.dirty.discard(key)
        return drawn

    def draw_shadow(self, cam_x, cam_z, radius):
        """그림자 지도에 넣을 불투명 메시 (시야각과 상관없이 주변 전체)"""
        glEnable(GL_CULL_FACE)
        for state in ARRAY_STATES:
            glEnableClientState(state)
        r2 = (radius + CHUNK_SIZE) ** 2
        for (rx, rz), mesh in self.lists.items():
            if ((rx + 0.5) * CHUNK_SIZE - cam_x) ** 2 + ((rz + 0.5) * CHUNK_SIZE - cam_z) ** 2 < r2:
                _draw_buffer(mesh[0], mesh[1])
        for state in ARRAY_STATES:
            glDisableClientState(state)
        glDisable(GL_CULL_FACE)
        _gl_bind_buffer(GL_ARRAY_BUFFER, 0)

    def draw_translucent(self, drawn):
        """물·유리는 불투명 블록과 몹을 다 그린 뒤 반투명으로"""
        glDepthMask(GL_FALSE)
        for state in ARRAY_STATES:
            glEnableClientState(state)
        for key, ylo, yhi in drawn:
            mesh = self.lists[key]
            _draw_bands(mesh[3], mesh[4], mesh[5], ylo, yhi)
        for state in ARRAY_STATES:
            glDisableClientState(state)
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glDepthMask(GL_TRUE)


# ==============================================================================
# 6. 먼 풍경 - 렌더 거리 밖은 블록 없이 기후로 계산한 높이·바이옴만으로 8칸 간격의 거친 지형을 그린다.
#    산, 숲, 바다, 사막의 색이 멀리까지 보이고, 가까운 곳은 셰이더가 잘라내 진짜 청크가 대신 보인다.
# ==============================================================================
LOD_STEP = 8                          # 먼 지형 격자 간격 (칸)
LOD_TILE = 64                         # 타일 한 변 (칸) - 타일마다 메시 하나
LOD_RADIUS = 896                      # 이 거리까지 먼 지형을 그린다
LOD_BUDGET = 0.003                    # 한 프레임에 먼 지형 타일 만드는 데 쓸 시간 (초)
LOD_CLIP = RENDER_DISTANCE * CHUNK_SIZE - 6
LOD_GROUP = 4                         # 타일 4×4 를 버퍼 하나로 묶어 한 번에 그린다 (그리기 호출 줄이기)
MAT_LOD = 4.0
LOD_CANOPY = {"forest": 6, "jungle": 9, "taiga": 7, "glowforest": 8, "swamp": 3}   # 멀리서 본 숲 지붕 높이
LOD_WATER = (0.20, 0.36, 0.48)


def _lod_color(gh, biome, slope):
    """먼 지형 한 칸의 색: 바이옴, 높이, 경사로 정한다 (숲은 나뭇잎 색)"""
    if gh < SEA_LEVEL:
        return LOD_WATER
    if biome in ("desert", "beach"):
        return BLOCK_COLORS[SAND]
    if biome == "badlands":
        return CLAY_BANDS[int(gh / 2) % len(CLAY_BANDS)]
    if biome == "snowy" or gh >= SNOW_LINE:
        return 0.80, 0.83, 0.88                                 # 멀리 보이는 눈 (그늘진 눈밭)
    if biome == "mountains" and gh >= SEA_LEVEL + 70:
        return BLOCK_COLORS[STONE]
    g = BIOME_GRASS.get(biome, BLOCK_COLORS[GRASS][0])
    if biome in LOD_CANOPY:
        g = (g[0] * 0.72, g[1] * 0.85, g[2] * 0.72)
    rock = _clamp01((slope - 0.9) / 1.2)                        # 가파른 비탈은 바위색
    st = BLOCK_COLORS[STONE]
    return _lerp(g[0], st[0], rock), _lerp(g[1], st[1], rock), _lerp(g[2], st[2], rock)


def _lod_tri(out, a, b, c, col, center, light):
    """먼 풍경용 삼각형: center 에서 바깥쪽을 보도록 감김 방향을 맞춘다"""
    n = _normal(a, b, c)
    m = ((a[0] + b[0] + c[0]) / 3 - center[0], (a[1] + b[1] + c[1]) / 3 - center[1], (a[2] + b[2] + c[2]) / 3 - center[2])
    if n[0] * m[0] + n[1] * m[1] + n[2] * m[2] < 0:
        b, c, n = c, b, (-n[0], -n[1], -n[2])
    out.append(((col[0], col[1], col[2], 1.0), n, (a, b, c), (light, light, light)))


def _lod_feature(out, f, light):
    """판타지 지형의 거친 모양 (멀리서 실루엣으로만 보이므로 다각형 몇 개면 충분하다)"""
    rock, grass = BLOCK_COLORS[STONE], BIOME_GRASS["plains"]
    if f["type"] == "island":                                   # 평평한 윗면 + 아래로 둥글게 좁아지는 바위
        cx, cy, cz, R = f["x"], f["y"], f["z"], f["r"] * 0.85
        top, apex = (cx, cy + 2, cz), (cx, cy - f["r"] * 0.85, cz)
        ring = [(cx + math.cos(k * math.pi / 6) * R, cy + 1, cz + math.sin(k * math.pi / 6) * R) for k in range(12)]
        mid = [(cx + math.cos(k * math.pi / 6 + 0.26) * R * 0.62, cy - f["r"] * 0.35, cz + math.sin(k * math.pi / 6 + 0.26) * R * 0.62)
               for k in range(12)]
        inside = (cx, cy - f["r"] * 0.3, cz)
        for k in range(12):
            a, b, c, d = ring[k], ring[(k + 1) % 12], mid[(k + 1) % 12], mid[k]
            _lod_tri(out, top, a, b, grass, (cx, cy - 50, cz), light)
            _lod_tri(out, a, b, c, rock, inside, light)
            _lod_tri(out, a, c, d, rock, inside, light)
            _lod_tri(out, d, c, apex, rock, inside, light)
    elif f["type"] == "peak":                                   # 능선이 있는 산: 높이 고리 몇 개를 이은 것
        cx, cz, base, H = f["x"], f["z"], f["base"], f["h"]
        rings = []
        for t in (0.0, 0.35, 0.7):
            ring = []
            for k in range(12):
                th = k * math.pi / 6
                m = 1 + 0.22 * math.sin(3 * th + f["phase"]) + 0.12 * math.sin(5 * th + 2.1 * f["phase"])
                r = f["r"] * m * (1 - t) ** 1.25
                ring.append((cx + math.cos(th) * r, base + H * t, cz + math.sin(th) * r))
            rings.append(ring)
        apex, inside = (cx, base + H, cz), (cx, base + H * 0.3, cz)
        col = BLOCK_COLORS[SNOW] if base + H >= SNOW_LINE else rock
        green = BIOME_GRASS["mountains"]
        for level, (r0, r1) in enumerate(zip(rings, rings[1:])):
            c0 = green if level == 0 else rock                   # 아랫자락은 풀, 위는 바위
            for k in range(12):
                a, b, c, d = r0[k], r0[(k + 1) % 12], r1[(k + 1) % 12], r1[k]
                _lod_tri(out, a, b, c, c0, inside, light)
                _lod_tri(out, a, c, d, c0, inside, light)
        for k in range(12):
            _lod_tri(out, rings[-1][k], rings[-1][(k + 1) % 12], apex, col, inside, light)
    elif f["type"] == "bridge":                                 # 두 지점을 잇는 네모 관
        x1, y1, z1, x2, y2, z2, r = f["x1"], f["y1"], f["z1"], f["x2"], f["y2"], f["z2"], f["r"]
        L = math.hypot(x2 - x1, z2 - z1)
        ux, uz = (x2 - x1) / L, (z2 - z1) / L
        for s0, s1 in f["segs"]:
            _lod_bridge_part(out, f, s0, s1, rock, light)


def _lod_bridge_part(out, f, s0, s1, rock, light):
    """돌다리의 s0 ~ s1 구간을 네모 관으로 (끊긴 끝은 막는다)"""
    x1, y1, z1, x2, y2, z2, r = f["x1"], f["y1"], f["z1"], f["x2"], f["y2"], f["z2"], f["r"]
    L = math.hypot(x2 - x1, z2 - z1)
    ux, uz = (x2 - x1) / L, (z2 - z1) / L
    steps = max(2, int(10 * (s1 - s0)) + 1)
    secs = []
    for k in range(steps + 1):
        s_ = s0 + (s1 - s0) * k / steps
        end = 1 - math.sin(math.pi * s_)
        w = r * (1 + 0.9 * end)
        px, pz = x1 + (x2 - x1) * s_, z1 + (z2 - z1) * s_
        py = y1 + (y2 - y1) * s_ + f["rise"] * math.sin(math.pi * s_)
        secs.append([(px - uz * w * sb, py + w * sy, pz + ux * w * sb) for sb, sy in ((-1, -1.5), (1, -1.5), (1, 0.55), (-1, 0.55))])
    for k in range(steps):
        q0, q1 = secs[k], secs[k + 1]
        mid = tuple((sum(p[i] for p in q0) + sum(p[i] for p in q1)) / 8 for i in range(3))
        for e in range(4):
            a, b, c, d = q0[e], q0[(e + 1) % 4], q1[(e + 1) % 4], q1[e]
            _lod_tri(out, a, b, c, rock, mid, light)
            _lod_tri(out, a, c, d, rock, mid, light)
    for cap, nxt in ((secs[0], secs[1]), (secs[-1], secs[-2])):           # 끊긴 끝면
        far = tuple(sum(p[i] for p in nxt) / 4 for i in range(3))
        _lod_tri(out, cap[0], cap[1], cap[2], rock, far, light)
        _lod_tri(out, cap[0], cap[2], cap[3], rock, far, light)


class FarTerrain:
    def __init__(self):
        self.tiles = {}          # (tx, tz) -> 정점 데이터 배열
        self.groups = {}         # (gx, gz) -> (버퍼, 정점 수)  타일 4×4 묶음
        self.dirty = set()       # 다시 올려야 하는 묶음
        self.samples = {}        # 격자점 (gx, gz) -> (지면 높이, 바이옴)

    def reset(self):
        for mesh in self.groups.values():
            delete_mesh(mesh)
        self.tiles.clear()
        self.groups.clear()
        self.dirty.clear()
        self.samples.clear()

    def _flush(self):
        """타일이 바뀐 묶음의 버퍼를 다시 만든다"""
        for g in self.dirty:
            delete_mesh(self.groups.pop(g, None))
            parts = [self.tiles.get((g[0] * LOD_GROUP + i, g[1] * LOD_GROUP + j))
                     for i in range(LOD_GROUP) for j in range(LOD_GROUP)]
            data = array("f")
            for part in parts:
                if part:
                    data.extend(part)
            if data:
                self.groups[g] = _upload_array(data)
        self.dirty.clear()

    def _sample(self, world, gx, gz):
        s = self.samples.get((gx, gz))
        if s is None:
            s = self.samples[(gx, gz)] = _column(world.climate, gx * LOD_STEP, gz * LOD_STEP)
        return s

    def _build(self, world, tx, tz):
        n = LOD_TILE // LOD_STEP
        g0x, g0z = tx * n, tz * n
        grid = [[self._sample(world, g0x + i, g0z + j) for j in range(n + 1)] for i in range(n + 1)]

        def height(s):
            gh, biome = s
            if gh < SEA_LEVEL:
                return SEA_LEVEL + 0.4
            return max(SEA_LEVEL + 0.5, gh + LOD_CANOPY.get(biome, 0) - 1.5)   # 진짜 지형보다 살짝 낮게

        hs = [[height(s) for s in row] for row in grid]
        feats = []
        rx, rz = (tx * LOD_TILE) // FEATURE_REGION, (tz * LOD_TILE) // FEATURE_REGION
        for f in world._region_features(rx, rz):                       # 이 타일에 중심이 있는 판타지 지형
            if tx * LOD_TILE <= f["x"] < (tx + 1) * LOD_TILE and tz * LOD_TILE <= f["z"] < (tz + 1) * LOD_TILE:
                feats.append(f)
        tris, light = [], (1.0, 0.0, MAT_LOD)
        for i in range(n):
            for j in range(n):
                x, z = (g0x + i) * LOD_STEP, (g0z + j) * LOD_STEP
                p00, p10 = (x, hs[i][j], z), (x + LOD_STEP, hs[i + 1][j], z)
                p01, p11 = (x, hs[i][j + 1], z + LOD_STEP), (x + LOD_STEP, hs[i + 1][j + 1], z + LOD_STEP)
                slope = (max(hs[i][j], hs[i + 1][j], hs[i][j + 1], hs[i + 1][j + 1])
                         - min(hs[i][j], hs[i + 1][j], hs[i][j + 1], hs[i + 1][j + 1])) / LOD_STEP
                gh, biome = grid[i][j]
                c = _lod_color(gh, biome, slope)
                k = 0.95 + _hash3(x, 0, z) % 9 / 100.0
                col = (c[0] * k, c[1] * k, c[2] * k, 1.0)
                for tri in ((p00, p01, p11), (p00, p11, p10)):
                    nrm = _normal(*tri)
                    if nrm[1] < 0:
                        tri, nrm = (tri[0], tri[2], tri[1]), (-nrm[0], -nrm[1], -nrm[2])
                    tris.append((col, nrm, tri, (light, light, light)))
        for f in feats:
            _lod_feature(tris, f, light)
        self.tiles[(tx, tz)] = _pack(tris)
        self.dirty.add((tx // LOD_GROUP, tz // LOD_GROUP))

    def _wanted(self, x, z):
        ctx, ctz = math.floor(x) // LOD_TILE, math.floor(z) // LOD_TILE
        r = LOD_RADIUS // LOD_TILE + 1
        out = []
        for tx in range(ctx - r, ctx + r + 1):
            for tz in range(ctz - r, ctz + r + 1):
                d = math.hypot((tx + 0.5) * LOD_TILE - x, (tz + 0.5) * LOD_TILE - z)
                if d < LOD_RADIUS + LOD_TILE * 0.7:
                    out.append((d, tx, tz))
        out.sort()
        return out

    def prebuild(self, world, x, z, progress=None):
        wanted = [w for w in self._wanted(x, z) if w[0] < LOD_RADIUS * 0.6]
        for k, (_, tx, tz) in enumerate(wanted):
            if (tx, tz) not in self.tiles:
                self._build(world, tx, tz)
            if progress and k % 16 == 0:
                progress(k / len(wanted))
        self._flush()

    def update(self, world, x, z):
        """가까운 것부터 빠진 타일을 만들고 (프레임 예산 안에서), 멀어진 타일은 버린다"""
        wanted = self._wanted(x, z)
        start = time.perf_counter()
        for _, tx, tz in wanted:
            if (tx, tz) not in self.tiles:
                self._build(world, tx, tz)
                if time.perf_counter() - start > LOD_BUDGET:
                    break
        keep = {(tx, tz) for _, tx, tz in wanted}
        for key in [k for k in self.tiles if k not in keep]:
            del self.tiles[key]
            self.dirty.add((key[0] // LOD_GROUP, key[1] // LOD_GROUP))
        if self.dirty:
            self._flush()
        if len(self.samples) > 40000:
            self.samples.clear()

    def draw(self, cam_x, cam_z, yaw):
        """화면 쪽 타일만, 진짜 청크 영역에 완전히 들어가는 타일은 빼고 그린다"""
        fx, fz = math.sin(math.radians(yaw)), -math.cos(math.radians(yaw))
        glEnable(GL_CULL_FACE)
        for state in ARRAY_STATES:
            glEnableClientState(state)
        size = LOD_TILE * LOD_GROUP
        half = size * 0.71
        for (gx, gz), (vbo, count) in self.groups.items():
            mx, mz = (gx + 0.5) * size - cam_x, (gz + 0.5) * size - cam_z
            d = math.hypot(mx, mz)
            if d + half < LOD_CLIP:
                continue
            if d > half * 1.5 and (mx * fx + mz * fz) / d < -0.5:      # 완전히 뒤쪽인 묶음 생략
                continue
            _draw_buffer(vbo, count)
        for state in ARRAY_STATES:
            glDisableClientState(state)
        glDisable(GL_CULL_FACE)
        _gl_bind_buffer(GL_ARRAY_BUFFER, 0)
