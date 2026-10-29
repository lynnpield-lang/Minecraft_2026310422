"""3D 마인크래프트 샌드박스 - 메인 게임

실행: python minecraft_3d.py   (필요 패키지: pygame-ce, PyOpenGL)
구성: mc3d_world.py (월드·렌더러) / mc3d_entities.py (물리·몹) / minecraft_3d.py (게임 진행·UI)
"""
import json
from array import array
import math
import os
import random
import zlib

import OpenGL
OpenGL.ERROR_CHECKING = False      # GL 함수를 부를 때마다 하는 오류 검사를 꺼서 훨씬 빨라진다
import pygame
from pygame.locals import *
from OpenGL.GL import *
from OpenGL.GLU import *

from mc3d_world import *
from mc3d_entities import *
from mc3d_render import Graphics, SHADOW_RADIUS, eye_to_world

SAVE_FILE_3D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "savegame_3d.json")
BLOCK_REACH = 5.0
ATTACK_REACH = 3.5
FONT_NAMES = "malgungothic,applesdgothicneo,applegothic,nanumgothic,arial"

DEFAULT_HOTBAR = [GRASS, DIRT, STONE, WOOD, PLANKS, WORKBENCH, TORCH, PORK_RAW, SAND]
START_INVENTORY = {
    GRASS: 32, DIRT: 32, STONE: 32, WOOD: 16, PLANKS: 16,
    WORKBENCH: 1, TORCH: 12, PORK_RAW: 3, SAND: 16, COAL_ORE: 8, IRON_ORE: 4, APPLE: 2,
}
WEATHER_NAMES = {"clear": "맑음", "rain": "비", "storm": "폭풍우"}
WEATHER_CHANGES = {
    "clear": (("clear", 0.55), ("rain", 0.35), ("storm", 0.10)),
    "rain": (("clear", 0.6), ("rain", 0.2), ("storm", 0.2)),
    "storm": (("rain", 0.6), ("clear", 0.4)),
}
MOB_DROPS = {"pig": (PORK_RAW, 1, 2), "zombie": (ROTTEN_FLESH, 0, 2), "creeper": (GUNPOWDER, 1, 2),
             "glowbeast": (GLOW_BERRY, 1, 3)}
GLOW_ITEMS = {TORCH, LANTERN, CRYSTAL} | GLOW_PLANTS      # 손에 들면 막대 끝이 빛나는 아이템
MAX_WISPS = 70
SKIN, SHIRT, PANTS, SHOES = (0.93, 0.74, 0.6), (0.2, 0.62, 0.72), (0.25, 0.3, 0.62), (0.3, 0.27, 0.25)
ARMOR_TINT = {IRON_ARMOR: (0.78, 0.8, 0.84), DIAMOND_ARMOR: (0.35, 0.88, 0.9)}
ALL_ITEMS = [item for item in ITEM_NAMES if item != AIR]          # 크리에이티브 인벤토리
MODE_NAMES = {"survival": "서바이벌", "creative": "크리에이티브"}
RECIPE_ROWS = 14                   # 조합창에 한 번에 보이는 줄 수 (휠로 스크롤)
CLOUD_Y, CLOUD_CELL, CLOUD_RANGE = 780, 24, 24


def parse_seed(text):
    """입력한 시드 문자열 → 정수. 숫자면 그대로, 글자면 해시값, 비어 있으면 무작위"""
    text = text.strip()
    if not text:
        return random.randrange(1, 2 ** 31)
    try:
        return int(text)
    except ValueError:
        return zlib.crc32(text.encode("utf-8"))


def check_save_file():
    """'none' / 'ok' / 'old'(이전 버전) / 'broken'"""
    if not os.path.exists(SAVE_FILE_3D):
        return "none"
    try:
        with open(SAVE_FILE_3D, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return "broken"
    if not isinstance(data, dict) or data.get("version") != SAVE_VERSION or \
            data.get("size") != [WORLD_H]:
        return "old"
    return "ok"


class Minecraft3D:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("3D 마인크래프트")
        pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), OPENGL | DOUBLEBUF)
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont(FONT_NAMES, 13)
        self.bold_font = pygame.font.SysFont(FONT_NAMES, 16, bold=True)
        self.large_font = pygame.font.SysFont(FONT_NAMES, 32, bold=True)
        self.text_cache = {}

        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LEQUAL)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glFogi(GL_FOG_MODE, GL_LINEAR)

        self.renderer = ChunkRenderer()
        self.far = FarTerrain()      # 렌더 거리 밖의 거친 풍경
        self.shader = LightShader()     # 해·달·하늘빛·횃불 빛을 계산하는 셰이더
        self.gfx = Graphics(SCREEN_WIDTH, SCREEN_HEIGHT) if self.shader.enabled else None   # 그림자·하늘·후처리
        self.state = "MENU"          # MENU / CONTROLS / SEED / PLAYING
        self.save_status = check_save_file()
        self.menu_message = ""
        self.notice = ""
        self.notice_timer = 0.0
        self.mouse_locked = False
        self.seed_text = ""          # 시드 입력 화면에서 친 글자
        self.new_mode = "survival"   # 새 월드를 만들 때 고른 게임 모드
        self.mode = "survival"
        self.survival_inventory = None
        star_rng = random.Random(7)
        self.stars = []              # 밤하늘 별 (하늘 구에 고정된 방향)
        while len(self.stars) < 450:
            v = (star_rng.uniform(-1, 1), star_rng.uniform(-1, 1), star_rng.uniform(-1, 1))
            n = math.sqrt(sum(c * c for c in v))
            if 0.2 < n <= 1.0:
                self.stars.append((v[0] / n, v[1] / n, v[2] / n, star_rng.uniform(0.4, 1.0)))
        self.cloud_mesh, self.cloud_key = None, None
        self.frame = 0
        self.world = None            # 새 게임 / 불러오기 때 시드로 만든다

    # ==========================================================================
    # 게임 상태 초기화
    # ==========================================================================
    def make_world(self, seed, edits):
        """시드로 끝없는 월드를 준비한다. 청크는 플레이어 주변에서 그때그때 만든다"""
        self.show_loading(f"월드 준비 중...  (시드 {seed})")
        self.seed = seed
        self.world = World(seed, edits)        # 플레이어가 바꿨던 블록은 청크가 만들어질 때 다시 적용
        self.renderer.reset()
        self.far.reset()
        self.cloud_noise = make_fbm(random.Random(seed + 99), (5, 2), (3, 1))
        delete_mesh(self.cloud_mesh)
        self.cloud_mesh, self.cloud_key = None, None

    def build_nearby_chunks(self):
        p = self.player
        self.world.ensure_around(p.x, p.z, progress=lambda f: self.show_loading("지형 생성 중...", f))
        self.world.changed.clear()
        near = RENDER_DISTANCE if not self.shader.enabled else 6    # 먼 풍경이 있으면 가까운 곳만 미리 그린다
        self.renderer.prebuild(self.world, p.x, p.z, lambda f: self.show_loading("지형 그리는 중...", f), near)
        if self.shader.enabled:
            self.far.prebuild(self.world, p.x, p.z, lambda f: self.show_loading("먼 풍경 그리는 중...", f))

    def stream_chunks(self):
        """플레이어가 움직이면 앞쪽 빈 청크를 프레임마다 하나씩 만들고, 먼 청크는 버린다"""
        p = self.player
        for key in self.world.ensure_around(p.x, p.z, budget=1):
            self.renderer.mark_generated(*key)
        for x, z in self.world.changed:
            self.renderer.mark_dirty(x, z)
        self.world.changed.clear()
        self.unload_timer -= 1
        if self.unload_timer <= 0:
            self.unload_timer = 120
            self.world.unload_far(p.x, p.z, LOAD_RADIUS + 3)

    def init_game(self, seed, mode="survival"):
        self.make_world(seed, {})
        self.spawn = find_spawn(self.world)
        self.player = Player(*self.spawn)
        self.hotbar = list(DEFAULT_HOTBAR)
        self.selected_slot = 0
        self.inventory = dict(START_INVENTORY)
        self.mode, self.survival_inventory = mode, None
        self.apply_mode()
        self.day_time = DAY_LENGTH * 0.05
        self.weather = "clear"
        self.weather_timer = random.uniform(90, 150)
        self.reset_runtime_state()
        self.mobs = []
        self.build_nearby_chunks()
        for kind, count in (("pig", 5), ("wolf", 3), ("zombie", 2), ("creeper", 2)):
            for _ in range(count):
                self.try_spawn_mob(kind, 12, 28, attempts=40)

    @property
    def creative(self):
        return self.mode == "creative"

    def apply_mode(self):
        """모드에 맞게 플레이어와 인벤토리를 맞춘다. 서바이벌 인벤토리는 따로 보관했다가 돌려준다"""
        p = self.player
        p.creative = self.creative
        if self.creative:
            if self.survival_inventory is None:
                self.survival_inventory = dict(self.inventory)
            self.inventory = {item: 1 for item in ALL_ITEMS}        # 모든 아이템 무한
            p.hp, p.hunger, p.oxygen = p.max_hp, p.max_hunger, p.max_oxygen
        else:
            p.flying = False
            if self.survival_inventory is not None:
                self.inventory = self.survival_inventory
                self.survival_inventory = None

    def toggle_mode(self):
        self.mode = "survival" if self.creative else "creative"
        self.apply_mode()
        self.show_notice(f"게임 모드: {MODE_NAMES[self.mode]}")

    def consume(self, item):
        """아이템 하나 사용. 크리에이티브에서는 줄지 않는다"""
        if not self.creative:
            self.inventory[item] -= 1

    def reset_runtime_state(self):
        """저장하지 않는 일시적인 상태 (새 게임 / 불러오기 / 리스폰 공통)"""
        self.target_block = None
        self.target_face = None
        self.target_mob = None
        self.mining_target = None
        self.mining_progress = 0.0
        self.click_lock = True        # 메뉴 클릭이 곧바로 채굴로 이어지지 않도록, 버튼을 뗄 때까지 무시
        self.attack_cd = 0.0
        self.particles = []
        self.wisps = []              # 떠다니는 빛 정령
        self.wisp_timer = 0.0
        self.falling_blocks = []
        self.leaf_decay = {}
        self.raindrops = []
        self.lightning_timer = 8.0
        self.flash = 0.0
        self.spawn_timer = 2.0
        self.unload_timer = 120
        self.sprinting = False
        self.show_inventory = False
        self.show_pause = False
        self.near_bench = False
        self.primed = []             # 점화된 TNT
        self.break_cd = 0.0          # 크리에이티브 연속 파괴 간격
        self.last_space = -1000      # 스페이스 두 번 누르기(비행) 판정
        self.walk_phase = 0.0        # 걸음 위상 (팔·다리 흔들기)
        self.walk_amount = 0.0       # 얼마나 걷고 있나 (0~1)
        self.swing = 0.0             # 팔 휘두르기 진행 (1 → 0)
        self.recipe_scroll = 0

    def start_playing(self):
        self.state = "PLAYING"
        self.show_pause = False
        self.show_inventory = False
        self.click_lock = True
        self.menu_message = ""
        self.lock_mouse(True)

    def respawn(self):
        yaw = self.player.yaw
        self.player = Player(*self.spawn)
        self.player.yaw = yaw
        self.mining_target = None
        self.mining_progress = 0.0
        self.click_lock = True

    def lock_mouse(self, locked):
        self.mouse_locked = locked
        pygame.mouse.set_visible(not locked)
        pygame.event.set_grab(locked)

    def try_spawn_mob(self, kind, min_dist, max_dist, attempts=10):
        p = self.player
        for _ in range(attempts):
            a = random.uniform(0, 2 * math.pi)
            d = random.uniform(min_dist, max_dist)
            x, z = int(p.x + math.sin(a) * d), int(p.z + math.cos(a) * d)
            if not self.world.is_loaded(x, z):
                continue
            y, top = column_top(self.world, x, z)
            if MOB_TYPES[kind]["group"] != "hostile" and top != GRASS:
                continue
            if kind == "glowbeast" and self.world.biome_at(x, z) != "glowforest":
                continue
            if top in (WATER, LEAVES, WOOD, CACTUS, BEDROCK) or y + 3 >= WORLD_H:
                continue
            self.mobs.append(Mob3D(x + 0.5, y + 1, z + 0.5, kind))
            return True
        return False

    # ==========================================================================
    # 저장 / 불러오기
    # ==========================================================================
    def save_game(self):
        if self.player.hp <= 0:
            self.respawn()
        p = self.player
        data = {
            "version": SAVE_VERSION,
            "size": [WORLD_H],
            "player": {"x": p.x, "y": p.y, "z": p.z, "yaw": p.yaw, "pitch": p.pitch, "hp": p.hp,
                       "hunger": p.hunger, "oxygen": p.oxygen, "exhaustion": p.exhaustion},
            "spawn": list(self.spawn),
            "inventory": {str(k): v for k, v in (self.survival_inventory if self.creative else self.inventory).items()
                          if v > 0},
            "mode": self.mode, "flying": self.player.flying,
            "hotbar": self.hotbar,
            "selected": self.selected_slot,
            "day_time": self.day_time,
            "weather": self.weather,
            "weather_timer": self.weather_timer,
            "mobs": [{"kind": m.kind, "x": m.x, "y": m.y, "z": m.z, "hp": m.hp} for m in self.mobs if m.hp > 0],
            "seed": self.seed,                                                  # 지형은 시드로 다시 만든다
            "edits": [list(e) for e in self.world.all_edits()],                   # 플레이어가 바꾼 블록만 저장
        }
        try:
            with open(SAVE_FILE_3D, "w", encoding="utf-8") as f:
                json.dump(data, f)
            self.save_status = "ok"
            self.show_notice("월드가 저장되었습니다.")
        except OSError as e:
            self.show_notice(f"저장 실패: {e}")

    def load_game(self):
        try:
            with open(SAVE_FILE_3D, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            self.menu_message = f"불러오기 실패: {e}"
            return False
        if data.get("version") != SAVE_VERSION or data.get("size") != [WORLD_H]:
            self.menu_message = "이전 버전 세이브 파일이라 불러올 수 없습니다. 새 게임을 시작하세요."
            return False
        try:
            seed = int(data["seed"])
            edits = {(int(x), int(y), int(z)): int(b) for x, y, z, b in data["edits"]}
            pd = data["player"]
            player = Player(pd["x"], pd["y"], pd["z"])
            player.yaw, player.pitch = pd["yaw"], pd["pitch"]
            player.hp, player.hunger = pd["hp"], pd["hunger"]
            player.oxygen, player.exhaustion = pd.get("oxygen", 10.0), pd.get("exhaustion", 0.0)
            hotbar = [int(i) for i in data["hotbar"]][:9]
            mobs = [Mob3D(m["x"], m["y"], m["z"], m["kind"], m["hp"])
                    for m in data.get("mobs", []) if m.get("kind") in MOB_TYPES]
            inventory = {int(k): v for k, v in data["inventory"].items()}
        except (KeyError, TypeError, ValueError, IndexError) as e:
            self.menu_message = f"세이브 파일 형식 오류: {e}"
            return False

        self.make_world(seed, edits)
        self.player = player
        self.mode = data.get("mode", "survival") if data.get("mode") in MODE_NAMES else "survival"
        self.spawn = tuple(data.get("spawn", find_spawn(self.world)))
        self.inventory = inventory
        self.survival_inventory = None
        self.apply_mode()
        self.player.flying = self.creative and bool(data.get("flying"))
        self.hotbar = hotbar + [AIR] * (9 - len(hotbar))
        self.selected_slot = min(max(0, data.get("selected", 0)), 8)
        self.day_time = data.get("day_time", 0.0)
        self.weather = data.get("weather", "clear") if data.get("weather") in WEATHER_NAMES else "clear"
        self.weather_timer = data.get("weather_timer", 120.0)
        self.mobs = mobs
        self.reset_runtime_state()
        if self.player.hp <= 0:
            self.respawn()
        self.build_nearby_chunks()
        self.start_playing()
        return True

    def show_notice(self, text, seconds=2.0):
        self.notice = text
        self.notice_timer = seconds
        print(text)

    # ==========================================================================
    # 메인 루프
    # ==========================================================================
    def run(self):
        running = True
        while running:
            dt = min(self.clock.tick(FPS) / 1000.0, 0.1)
            self.notice_timer = max(0.0, self.notice_timer - dt)
            for event in pygame.event.get():
                if event.type == QUIT:
                    if self.state == "PLAYING":
                        self.save_game()
                    running = False
                elif self.state == "MENU":
                    if self.handle_menu_event(event) == "quit":
                        running = False
                elif self.state == "CONTROLS":
                    if event.type in (KEYDOWN, MOUSEBUTTONDOWN):
                        self.state = "MENU"
                elif self.state == "SEED":
                    self.handle_seed_event(event)
                elif self.state == "PLAYING":
                    self.handle_playing_event(event)
            if not running:
                break
            if self.state == "PLAYING":
                self.update_game(dt)
            self.render()
            pygame.display.flip()
        self.renderer.release()
        pygame.quit()

    # ==========================================================================
    # 입력 처리
    # ==========================================================================
    def menu_buttons(self):
        return [("continue", "이어하기", pygame.Rect(360, 260, 280, 50), self.save_status == "ok"),
                ("new", "새로운 게임 시작", pygame.Rect(360, 330, 280, 50), True),
                ("controls", "조작법 및 가이드", pygame.Rect(360, 400, 280, 50), True),
                ("quit", "게임 종료", pygame.Rect(360, 470, 280, 50), True)]

    def pause_buttons(self):
        return [("resume", "계속하기", pygame.Rect(400, 260, 200, 44)),
                ("save", "월드 저장하기", pygame.Rect(400, 320, 200, 44)),
                ("menu", "저장 후 메인 메뉴", pygame.Rect(400, 380, 200, 44)),
                ("mode", f"모드 전환 (지금: {MODE_NAMES[self.mode]})", pygame.Rect(370, 440, 260, 44))]

    def death_buttons(self):
        return [("respawn", "리스폰", pygame.Rect(400, 330, 200, 44)),
                ("menu", "저장 후 메인 메뉴", pygame.Rect(400, 390, 200, 44))]

    def handle_menu_event(self, event):
        if event.type != MOUSEBUTTONDOWN or event.button != 1:
            return None
        for key, _, rect, enabled in self.menu_buttons():
            if not rect.collidepoint(event.pos) or not enabled:
                continue
            if key == "continue":
                self.load_game()
            elif key == "new":
                self.seed_text = ""
                self.state = "SEED"
            elif key == "controls":
                self.state = "CONTROLS"
            elif key == "quit":
                return "quit"
        return None

    def seed_buttons(self):
        return [("mode", f"게임 모드: {MODE_NAMES[self.new_mode]}  (클릭해서 바꾸기)", pygame.Rect(320, 345, 360, 42)),
                ("start", "이 시드로 시작", pygame.Rect(300, 410, 190, 46)),
                ("random", "무작위 시드로 시작", pygame.Rect(510, 410, 190, 46)),
                ("back", "뒤로", pygame.Rect(420, 476, 160, 40))]

    def handle_seed_event(self, event):
        """시드 입력: 숫자나 글자를 치고 Enter. 비워 두면 무작위 시드"""
        action = None
        if event.type == KEYDOWN:
            if event.key in (K_RETURN, K_KP_ENTER):
                action = "start"
            elif event.key == K_ESCAPE:
                action = "back"
            elif event.key == K_BACKSPACE:
                self.seed_text = self.seed_text[:-1]
            elif event.unicode and event.unicode.isprintable() and len(self.seed_text) < 20:
                self.seed_text += event.unicode
        elif event.type == MOUSEBUTTONDOWN and event.button == 1:
            for key, _, rect in self.seed_buttons():
                if rect.collidepoint(event.pos):
                    action = key
        if action == "back":
            self.state = "MENU"
        elif action == "mode":
            self.new_mode = "creative" if self.new_mode == "survival" else "survival"
        elif action in ("start", "random"):
            self.init_game(parse_seed(self.seed_text if action == "start" else ""), self.new_mode)
            self.start_playing()

    def handle_playing_event(self, event):
        p = self.player
        if event.type == KEYDOWN:
            if event.key == K_ESCAPE and p.hp > 0:
                if self.show_inventory:
                    self.toggle_inventory(False)
                else:
                    self.show_pause = not self.show_pause
                    self.lock_mouse(not self.show_pause)
            elif event.key == K_e and not self.show_pause and p.hp > 0:
                self.toggle_inventory(not self.show_inventory)
            elif K_1 <= event.key <= K_9:
                self.selected_slot = event.key - K_1
            elif event.key == K_SPACE and self.creative and not self.show_pause:
                now = pygame.time.get_ticks()
                if now - self.last_space < 300:                     # 스페이스 두 번: 비행 켜기/끄기
                    p.flying = not p.flying
                    p.vy = 0.0
                    self.last_space = -1000
                else:
                    self.last_space = now
        elif event.type == MOUSEWHEEL and self.show_inventory:
            top = max(0, len(RECIPES) - RECIPE_ROWS)
            self.recipe_scroll = max(0, min(top, self.recipe_scroll - event.y))
        elif event.type == MOUSEWHEEL and p.hp > 0:
            self.selected_slot = (self.selected_slot - event.y) % len(self.hotbar)
        elif event.type == MOUSEMOTION and self.mouse_locked:
            dx, dy = event.rel
            p.yaw = (p.yaw + dx * 0.18) % 360.0
            p.pitch = max(-89.0, min(89.0, p.pitch - dy * 0.18))
        elif event.type == MOUSEBUTTONDOWN and event.button in (1, 3):
            if p.hp <= 0:
                self.handle_death_click(event.pos)
            elif self.show_pause:
                self.handle_pause_click(event.pos)
            elif self.show_inventory:
                if event.button == 1:
                    self.handle_inventory_click(event.pos)
            elif not self.mouse_locked:
                self.lock_mouse(True)
                self.click_lock = True
            elif event.button == 1:
                self.handle_left_click()
            else:
                self.handle_right_click()
        elif event.type == MOUSEBUTTONUP and event.button == 1:
            self.click_lock = False
            self.mining_target = None
            self.mining_progress = 0.0

    def toggle_inventory(self, open_it):
        self.show_inventory = open_it
        self.lock_mouse(not open_it)
        if open_it:
            self.near_bench = self.is_near_workbench()

    def handle_pause_click(self, pos):
        for key, _, rect in self.pause_buttons():
            if not rect.collidepoint(pos):
                continue
            if key == "resume":
                self.show_pause = False
                self.click_lock = True
                self.lock_mouse(True)
            elif key == "save":
                self.save_game()
            elif key == "mode":
                self.toggle_mode()
            elif key == "menu":
                self.save_game()
                self.show_pause = False
                self.state = "MENU"
                self.lock_mouse(False)

    def handle_death_click(self, pos):
        for key, _, rect in self.death_buttons():
            if not rect.collidepoint(pos):
                continue
            if key == "respawn":
                self.respawn()
                self.lock_mouse(True)
            else:
                self.save_game()
                self.state = "MENU"
                self.lock_mouse(False)

    def held_item(self):
        item = self.hotbar[self.selected_slot]
        return item if self.inventory.get(item, 0) > 0 else AIR

    def handle_left_click(self):
        # 블록 채굴은 update_mining() 에서 버튼을 누르고 있는 동안 진행된다
        if not self.click_lock and self.target_mob is not None:
            self.attack_mob(self.target_mob)

    def attack_mob(self, mob):
        if self.attack_cd > 0:
            return
        self.swing = 1.0
        p = self.player
        mob.take_hit(WEAPON_DAMAGE.get(self.held_item(), 1), p.x, p.z, by_player=True)
        self.attack_cd = 0.45
        p.exhaustion += 0.1
        self.burst(mob.x, mob.y + mob.h * 0.6, mob.z, (0.9, 0.15, 0.15), 6)
        if mob.kind == "wolf":       # 늑대 무리는 함께 화낸다
            for other in self.mobs:
                if other.kind == "wolf" and math.hypot(other.x - mob.x, other.z - mob.z) < 12:
                    other.angry_timer = 20.0

    def handle_right_click(self):
        p = self.player
        item = self.held_item()

        # 1) 음식 섭취 (황금 사과는 배불러도 먹을 수 있고 체력도 회복)
        if item in FOOD_VALUES and (p.hunger < p.max_hunger or item == GOLDEN_APPLE) and not self.creative:
            self.inventory[item] -= 1
            p.hunger = min(p.max_hunger, p.hunger + FOOD_VALUES[item])
            if item == GOLDEN_APPLE:
                p.hp = min(p.max_hp, p.hp + 8)
                self.burst(p.x, p.y + 1.3, p.z, (1.0, 0.85, 0.2), 16)
            self.burst(p.x, p.y + 1.3, p.z, (1.0, 0.5, 0.4), 8)
            return

        # 2) 작업대 사용 / TNT 점화
        if self.target_block is not None and self.target_mob is None:
            bx, by, bz = self.target_block
            target = self.world.get(bx, by, bz)
            if target == WORKBENCH and item not in BLOCK_COLORS:
                self.toggle_inventory(True)
                return
            if target == TNT:
                self.set_block(bx, by, bz, AIR)
                self.primed.append(PrimedTNT(bx, by, bz))
                return

        # 3) 블록 설치
        if self.target_face is None or item not in BLOCK_COLORS:
            return
        fx, fy, fz = self.target_face
        if not (0 <= fy < WORLD_H and self.world.is_loaded(fx, fz)):
            return
        if self.world.get(fx, fy, fz) not in {AIR, WATER} | DECOR_BLOCKS:   # 풀·꽃은 덮어쓴다
            return
        if item in DECOR_BLOCKS:                                  # 풀·꽃은 흙이나 잔디 위에만
            if self.world.get(fx, fy - 1, fz) not in (GRASS, DIRT):
                return
        elif item == GLOW_VINE:                                   # 덩굴은 단단한 블록·잎·덩굴 아래에 매단다
            above = self.world.get(fx, fy + 1, fz)
            if above in NON_SOLID_BLOCKS and above != GLOW_VINE:
                return
        elif item == GLOW_MOSS:                                   # 이끼는 단단한 면 어디에나 붙는다
            if all(self.world.get(fx + dx, fy + dy, fz + dz) in NON_SOLID_BLOCKS for dx, dy, dz in SUPPORT_SIDES):
                return
        elif item in NEEDS_GROUND:                                # 횃불·랜턴은 단단한 바닥 위에만
            if not is_solid(self.world, fx, fy - 1, fz):
                return
        elif self.box_hits_entity(fx, fy, fz):
            return
        self.set_block(fx, fy, fz, item)
        self.consume(item)
        self.swing = 1.0
        self.update_support(fx, fy, fz)       # 공중에 놓은 모래·원목은 떨어진다

    def box_hits_entity(self, bx, by, bz):
        for e in [self.player] + self.mobs:
            if e.x + e.r > bx and e.x - e.r < bx + 1 and e.z + e.r > bz and e.z - e.r < bz + 1 \
                    and e.y + e.h > by and e.y < by + 1:
                return True
        return False

    # ==========================================================================
    # 인벤토리 / 조합
    # ==========================================================================
    def give(self, item, count=1):
        """아이템 획득. 핫바에 없으면 빈 칸에 자동 배치"""
        if item is None or count <= 0:
            return
        self.inventory[item] = self.inventory.get(item, 0) + count
        if item in self.hotbar:
            return
        for i, slot in enumerate(self.hotbar):
            if slot == AIR or self.inventory.get(slot, 0) <= 0:
                self.hotbar[i] = item
                return

    def is_near_workbench(self):
        p = self.player
        px, py, pz = int(p.x), int(p.y), int(p.z)
        for y in range(max(0, py - 2), min(WORLD_H, py + 4)):
            for x in range(px - 4, px + 5):
                for z in range(pz - 4, pz + 5):
                    if self.world.get(x, y, z) == WORKBENCH:
                        return True
        return False

    def can_craft(self, rec):
        if rec["bench"] and not self.near_bench:
            return False
        return all(self.inventory.get(it, 0) >= cnt for it, cnt in rec["req"].items())

    def recipe_rects(self):
        """지금 보이는 조합법과 그 칸 (휠로 스크롤)"""
        shown = RECIPES[self.recipe_scroll:self.recipe_scroll + RECIPE_ROWS]
        return [(rec, pygame.Rect(70, 110 + i * 29, 470, 25)) for i, rec in enumerate(shown)]

    def inventory_slots(self):
        items = sorted(it for it, cnt in self.inventory.items() if cnt > 0 and it != AIR)
        return [(it, pygame.Rect(570 + (i % 7) * 52, 110 + (i // 7) * 52, 48, 48)) for i, it in enumerate(items)]

    def hotbar_rects(self):
        start_x = (SCREEN_WIDTH - (9 * 48 - 4)) // 2
        return [pygame.Rect(start_x + i * 48, SCREEN_HEIGHT - 60, 44, 44) for i in range(9)]

    def handle_inventory_click(self, pos):
        for rec, rect in self.recipe_rects():
            if rect.collidepoint(pos):
                if self.can_craft(rec):
                    for it, cnt in rec["req"].items():
                        self.inventory[it] -= cnt
                    self.give(rec["result"], rec["count"])
                return
        for item, rect in self.inventory_slots():
            if rect.collidepoint(pos):
                # 선택된 핫바 칸에 넣기 (이미 핫바에 있으면 자리 교환)
                sel = self.selected_slot
                if item in self.hotbar:
                    j = self.hotbar.index(item)
                    self.hotbar[j], self.hotbar[sel] = self.hotbar[sel], self.hotbar[j]
                else:
                    self.hotbar[sel] = item
                return
        for i, rect in enumerate(self.hotbar_rects()):
            if rect.collidepoint(pos):
                self.selected_slot = i
                return

    # ==========================================================================
    # 블록 변경과 블록 물리 (낙하, 받침, 나뭇잎 소멸)
    # ==========================================================================
    def set_block(self, x, y, z, bid):
        old = self.world.get(x, y, z)
        if not self.world.set(x, y, z, bid):      # 바뀐 블록은 world 가 기록해 두고 저장한다
            return
        self.renderer.mark_dirty(x, z)
        reach = max(LIGHT_BLOCKS.get(old, 0), LIGHT_BLOCKS.get(bid, 0))
        if reach:                                 # 그 블록의 빛이 닿는 범위만 다시 그린다
            self.renderer.mark_radius(x, z, reach + 1)
        if bid in NON_SOLID_BLOCKS:
            self.update_support(x, y + 1, z)
        if bid in NON_SOLID_BLOCKS and bid != GLOW_VINE and self.world.get(x, y - 1, z) == GLOW_VINE:
            self.set_block(x, y - 1, z, AIR)      # 매달린 곳이 사라진 덩굴은 아래로 줄줄이 끊어진다
        if old == WOOD:
            self.queue_leaf_decay(x, y, z)

    def update_support(self, x, y, z):
        """(x, y, z) 블록 아래가 비었으면 떨어뜨리거나 부순다"""
        if not 1 <= y < WORLD_H:
            return
        bid = self.world.get(x, y, z)
        if self.world.get(x, y - 1, z) not in NON_SOLID_BLOCKS:
            return
        if bid in GRAVITY_BLOCKS:
            self.falling_blocks.append(FallingBlock(x, y, z, bid))
            self.set_block(x, y, z, AIR)          # 그 위 블록도 연쇄적으로 검사됨
        elif bid in NEEDS_GROUND:
            self.set_block(x, y, z, AIR)
            if bid != TALL_GRASS:
                self.give(bid)

    def queue_leaf_decay(self, x, y, z):
        for ly in range(max(0, y - 4), min(WORLD_H, y + 5)):
            for lx in range(x - 4, x + 5):
                for lz in range(z - 4, z + 5):
                    if self.world.get(lx, ly, lz) == LEAVES and (lx, ly, lz) not in self.leaf_decay:
                        self.leaf_decay[(lx, ly, lz)] = random.uniform(1.0, 5.0)

    def wood_nearby(self, x, y, z, radius):
        for ly in range(max(0, y - radius), min(WORLD_H, y + radius + 1)):
            for lx in range(x - radius, x + radius + 1):
                for lz in range(z - radius, z + radius + 1):
                    if self.world.get(lx, ly, lz) == WOOD:
                        return True
        return False

    def update_blocks(self, dt):
        p = self.player
        for fb in self.falling_blocks[:]:
            if fb.update(self.world):
                self.falling_blocks.remove(fb)
                self.land_block(fb)
        for t in self.primed[:]:
            if t.update(self.world, dt):
                self.primed.remove(t)
                self.explode(t.x, t.y + 0.5, t.z, 3.6)

        for pos in list(self.leaf_decay):
            self.leaf_decay[pos] -= dt
            if self.leaf_decay[pos] > 0:
                continue
            del self.leaf_decay[pos]
            x, y, z = pos
            if self.world.get(x, y, z) != LEAVES or self.wood_nearby(x, y, z, 4):
                continue
            self.set_block(x, y, z, AIR)
            self.burst(x + 0.5, y + 0.5, z + 0.5, BLOCK_COLORS[LEAVES], 5)
            if random.random() < 0.06 and math.hypot(p.x - x, p.z - z) < 12:
                self.give(APPLE)

    def land_block(self, fb):
        bx, bz = math.floor(fb.x), math.floor(fb.z)
        by = int(round(fb.y))
        for y in (by, by + 1):
            if 0 <= y < WORLD_H and self.world.get(bx, y, bz) in NON_SOLID_BLOCKS:
                if self.world.get(bx, y, bz) == TORCH:
                    self.give(TORCH)
                self.set_block(bx, y, bz, fb.block_id)
                p = self.player
                if p.x + p.r > bx and p.x - p.r < bx + 1 and p.z + p.r > bz and p.z - p.r < bz + 1 \
                        and p.y < y + 1 and p.y + p.h > y:
                    p.hurt(self.armored(3 if fb.block_id == WOOD else 1), "떨어진 블록")
                return
        self.burst(fb.x, fb.y + 0.5, fb.z, block_face_colors(fb.block_id)[1], 10)

    def explode(self, cx, cy, cz, radius):
        removed = []
        r = int(math.ceil(radius))
        for y in range(max(0, int(cy) - r), min(WORLD_H, int(cy) + r + 1)):
            for x in range(math.floor(cx) - r, math.floor(cx) + r + 2):
                for z in range(math.floor(cz) - r, math.floor(cz) + r + 2):
                    if (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 + (z + 0.5 - cz) ** 2 > radius * radius:
                        continue
                    b = self.world.get(x, y, z)
                    if b == TNT and self.world.set(x, y, z, AIR):          # 옆의 TNT 는 곧 따라 터진다
                        self.renderer.mark_dirty(x, z)
                        self.primed.append(PrimedTNT(x, y, z, fuse=random.uniform(0.4, 1.0)))
                        continue
                    if b not in (AIR, WATER, BEDROCK) and self.world.set(x, y, z, AIR):
                        self.renderer.mark_dirty(x, z)
                        removed.append((x, y, z, b))
        for x, y, z, b in removed:
            if b == WOOD:
                self.queue_leaf_decay(x, y, z)
            self.update_support(x, y + 1, z)

        # 거리에 따라 피해와 넉백
        p = self.player
        reach = radius * 2.4
        d = math.dist((p.x, p.y + 0.9, p.z), (cx, cy, cz))
        if d < reach:
            p.hurt(self.armored(int((1 - d / reach) * 18) + 1), "폭발")
            p.knockback(cx, cz, 0.6)
        for m in self.mobs:
            d = math.dist((m.x, m.y + m.h / 2, m.z), (cx, cy, cz))
            if d < reach and m.hp > 0:
                m.take_hit(int((1 - d / reach) * 18) + 1, cx, cz, by_player=False)
        for _ in range(50):
            col = random.choice([(1.0, 0.55, 0.1), (0.4, 0.4, 0.4), (0.9, 0.9, 0.8)])
            self.particles.append(Particle3D(cx, cy, cz, col, spread=0.25))
        self.flash = 0.2

    # ==========================================================================
    # 게임 업데이트
    # ==========================================================================
    def update_game(self, dt):
        p = self.player
        if self.show_pause or self.show_inventory:
            return
        if p.hp > 0 and not self.mouse_locked:     # 창 포커스를 잃으면 멈춤
            return
        self.update_particles()
        if p.hp <= 0:
            return
        self.attack_cd = max(0.0, self.attack_cd - dt)
        self.stream_chunks()
        self.update_time_weather(dt)
        self.update_targeting()
        self.update_mining(dt)
        self.update_player()
        self.update_survival(dt)
        self.update_mobs(dt)
        self.update_blocks(dt)
        self.update_rain()
        self.update_spawning(dt)
        self.update_wisps(dt)
        if p.hp <= 0:
            self.on_death()

    def on_death(self):
        p = self.player
        self.burst(p.x, p.y + 1.0, p.z, (0.8, 0.1, 0.1), 25)
        self.mining_target = None
        self.mining_progress = 0.0
        self.show_inventory = False
        self.show_pause = False
        self.lock_mouse(False)

    def update_targeting(self):
        p = self.player
        dx, dy, dz = look_vector(p.yaw, p.pitch)
        ex, ey, ez = p.x, p.y + Player.EYE, p.z
        block, face, t_block = raycast_blocks(self.world, ex, ey, ez, dx, dy, dz, BLOCK_REACH)
        self.target_block, self.target_face = block, face
        self.target_mob = None
        best = min(t_block, ATTACK_REACH)
        for m in self.mobs:
            t = ray_box(ex, ey, ez, dx, dy, dz, (m.x - m.r, m.y, m.z - m.r), (m.x + m.r, m.y + m.h, m.z + m.r))
            if t is not None and t < best:
                best = t
                self.target_mob = m

    def mining_time(self, bid):
        base = BLOCK_MINING_TIME.get(bid, 1.0)
        if bid in PICKAXE_BLOCKS:
            base /= PICKAXE_POWER.get(self.held_item(), 1.0)
        elif bid in AXE_BLOCKS:
            base /= AXE_POWER.get(self.held_item(), 1.0)
        return base

    def armor(self):
        """인벤토리에 있는 가장 좋은 갑옷의 피해 감소율"""
        return max((cut for item, cut in ARMOR_REDUCTION.items() if self.inventory.get(item, 0) > 0), default=0.0)

    def armored(self, damage):
        return max(1, round(damage * (1 - self.armor())))

    def update_mining(self, dt):
        pressed = pygame.mouse.get_pressed()[0]
        if not pressed:
            self.click_lock = False
        if not pressed or self.click_lock or self.target_block is None or self.target_mob is not None:
            self.mining_target = None
            self.mining_progress = 0.0
            return
        if self.creative:                                 # 크리에이티브: 누르는 즉시 부서진다 (0.2초 간격)
            self.break_cd -= dt
            if self.break_cd <= 0:
                self.break_block(*self.target_block)
                self.break_cd = 0.2
                self.swing = 1.0
            self.mining_target = None
            return
        if self.target_block != self.mining_target:      # 조준이 바뀌면 새 블록부터 다시
            self.mining_target = self.target_block
            self.mining_progress = 0.0
        bx, by, bz = self.mining_target
        bid = self.world.get(bx, by, bz)
        t = self.mining_time(bid)
        if t == math.inf:
            self.mining_progress = 0.0
            return
        self.mining_progress += dt / t
        self.player.exhaustion += 0.03 * dt
        if random.random() < 0.3:
            self.burst(bx + 0.5, by + 0.5, bz + 0.5, block_face_colors(bid)[0], 1)
        if self.mining_progress >= 1.0:
            self.break_block(bx, by, bz)
            self.mining_target = None
            self.mining_progress = 0.0

    def break_block(self, x, y, z):
        bid = self.world.get(x, y, z)
        drop = {DIAMOND_ORE: DIAMOND, GRASS: DIRT, TALL_GRASS: AIR}.get(bid, bid)
        if bid == LEAVES:
            drop = APPLE if random.random() < 0.1 else LEAVES
        if bid == GLOW_VINE and random.random() < 0.3 and not self.creative:
            self.give(GLOW_BERRY)                          # 덩굴의 빛나는 열매
        if drop != AIR and not self.creative:              # 크리에이티브는 드롭 없음
            self.give(drop)
        self.set_block(x, y, z, AIR)
        self.burst(x + 0.5, y + 0.5, z + 0.5, block_face_colors(bid)[0], 12)

    def update_player(self):
        p = self.player
        keys = pygame.key.get_pressed()
        rad = math.radians(p.yaw)
        fx, fz = math.sin(rad), -math.cos(rad)
        rx, rz = math.cos(rad), math.sin(rad)
        mx = mz = 0.0
        if keys[K_w]:
            mx += fx; mz += fz
        if keys[K_s]:
            mx -= fx; mz -= fz
        if keys[K_a]:
            mx -= rx; mz -= rz
        if keys[K_d]:
            mx += rx; mz += rz

        shift = keys[K_LSHIFT] or keys[K_RSHIFT]
        if p.flying:                                              # 비행: Space 위, Shift 아래, Ctrl 빠르게
            self.sprinting = False
            speed = 0.42 if (keys[K_LCTRL] or keys[K_RCTRL]) else 0.22
            target = (0.24 if keys[K_SPACE] else 0.0) - (0.24 if shift else 0.0)
            p.vy += (target - p.vy) * 0.35
        else:
            self.sprinting = shift and keys[K_w] and (p.hunger > 6 or self.creative) and not p.in_water
            speed = 0.04 if p.in_water else (0.115 if self.sprinting else 0.08)
        n = math.hypot(mx, mz)
        wish_x, wish_z = (mx / n * speed, mz / n * speed) if n else (0.0, 0.0)

        if keys[K_SPACE] and p.can_jump() and not p.flying:
            p.vy = JUMP_SPEED
            p.exhaustion += 0.2 if self.sprinting else 0.05

        old_x, old_z = p.x, p.z
        damage = p.physics(self.world, wish_x, wish_z, swim_up=keys[K_SPACE])
        if p.flying and p.on_ground and shift:                   # 비행 중 땅에 내려앉으면 비행 끝
            p.flying = False
        moved = math.hypot(p.x - old_x, p.z - old_z)
        self.walk_phase += moved * 2.6
        target = min(1.0, moved / 0.08) if p.on_ground else 0.3
        self.walk_amount += (target - self.walk_amount) * 0.2
        self.swing = max(0.0, self.swing - 0.09)
        if self.mining_target is not None and self.swing <= 0:      # 캐는 동안 계속 휘두른다
            self.swing = 1.0
        p.exhaustion += moved * (0.1 if self.sprinting else 0.015 if p.in_water else 0.01)
        if damage > 0:
            p.hurt(damage, "낙사")

    def update_survival(self, dt):
        p = self.player
        p.invincible = max(0.0, p.invincible - dt)
        p.hurt_flash = max(0.0, p.hurt_flash - dt)
        if self.creative:                             # 배고픔·산소·체력이 줄지 않고, 아이템은 무한
            p.hp, p.hunger, p.oxygen, p.exhaustion = p.max_hp, p.max_hunger, p.max_oxygen, 0.0
            for item in ALL_ITEMS:
                if self.inventory.get(item, 0) < 1:
                    self.inventory[item] = 1
            return

        # 허기: 행동할수록 피로도가 쌓이고, 4가 쌓이면 허기 1 감소
        p.exhaustion += 0.02 * dt
        while p.exhaustion >= 4.0:
            p.exhaustion -= 4.0
            p.hunger = max(0, p.hunger - 1)

        # 배부르면 자연 회복, 굶으면 피해
        p.regen_timer += dt
        if p.regen_timer >= 3.0:
            p.regen_timer = 0.0
            if p.hunger >= 18 and p.hp < p.max_hp:
                p.hp += 1
                p.exhaustion += 1.5
            elif p.hunger == 0:
                p.hurt(1, "굶주림")

        # 산소와 익사
        if p.head_in_water:
            p.oxygen = max(0.0, p.oxygen - dt / 1.5)
            if p.oxygen <= 0:
                p.drown_timer += dt
                if p.drown_timer >= 1.0:
                    p.drown_timer = 0.0
                    p.hurt(2, "익사")
        else:
            p.oxygen = min(p.max_oxygen, p.oxygen + dt * 5)
            p.drown_timer = 0.0

        # 선인장 접촉 피해
        r = p.r + 0.05
        for by in range(math.floor(p.y - 0.05), math.floor(p.y + p.h) + 1):
            for bx in range(math.floor(p.x - r), math.floor(p.x + r) + 1):
                for bz in range(math.floor(p.z - r), math.floor(p.z + r) + 1):
                    if block_at(self.world, bx, by, bz) == CACTUS:
                        p.hurt(1, "선인장")

    def update_mobs(self, dt):
        p = self.player
        env = {"sun_burn": self.light_level() > 0.75 and self.weather == "clear"}
        for m in self.mobs:
            if not self.world.is_loaded(m.x, m.z):        # 아직/이미 없는 청크 위의 몹은 멈춘다
                continue
            for kind, mob in m.update(self.world, p, env, dt):
                if kind == "attack":
                    if p.hurt(self.armored(mob.attack), MOB_NAMES[mob.kind]):
                        p.knockback(mob.x, mob.z, 0.3)
                elif kind == "explode":
                    self.explode(mob.x, mob.y + 0.8, mob.z, 2.6)
            if m.burning and random.random() < 0.3:
                self.burst(m.x, m.y + m.h, m.z, (1.0, 0.5, 0.1), 1)
        self.separate_entities()

        for m in self.mobs[:]:
            if m.hp <= 0:
                if m.killed_by_player and m.kind in MOB_DROPS:
                    item, lo, hi = MOB_DROPS[m.kind]
                    self.give(item, random.randint(lo, hi))
                self.burst(m.x, m.y + m.h / 2, m.z, (0.85, 0.85, 0.85), 15)
                self.mobs.remove(m)
            elif math.hypot(m.x - p.x, m.z - p.z) > (40 if m.group == "hostile" else 120):
                self.mobs.remove(m)

    def separate_entities(self):
        """플레이어와 몹, 몹끼리 겹치지 않도록 서로 밀어낸다"""
        ents = [self.player] + self.mobs
        for i, a in enumerate(ents):
            for b in ents[i + 1:]:
                if a.y >= b.y + b.h or b.y >= a.y + a.h:
                    continue
                dx, dz = b.x - a.x, b.z - a.z
                d = math.hypot(dx, dz)
                min_d = a.r + b.r
                if d >= min_d:
                    continue
                if d < 1e-4:
                    dx, dz, d = 1.0, 0.0, 1.0
                push = (min_d - d) * 0.15
                a.vx -= dx / d * push
                a.vz -= dz / d * push
                b.vx += dx / d * push
                b.vz += dz / d * push

    def update_spawning(self, dt):
        self.spawn_timer -= dt
        if self.spawn_timer > 0:
            return
        self.spawn_timer = 2.0
        passive = sum(1 for m in self.mobs if m.group != "hostile")
        hostile = len(self.mobs) - passive
        if passive < 8 and random.random() < 0.3:
            glow = self.world.biome_at(self.player.x, self.player.z) == "glowforest"
            self.try_spawn_mob(random.choice(["glowbeast", "glowbeast", "pig"] if glow else ["pig", "pig", "wolf"]),
                               16, 30)
        if (self.light_level() < 0.3 or self.weather == "storm") and hostile < 10:
            self.try_spawn_mob(random.choice(["zombie", "zombie", "creeper"]), 14, 28)

    def update_wisps(self, dt):
        """빛나는 식물 근처에 떠다니는 빛 정령: 밤이나 어두운 동굴에서만 나타난다"""
        p = self.player
        for w in self.wisps:
            w.update(dt)
        self.wisps = [w for w in self.wisps if w.life > 0 and abs(w.x - p.x) < 48 and abs(w.z - p.z) < 48]
        self.wisp_timer -= dt
        if self.wisp_timer > 0 or len(self.wisps) >= MAX_WISPS:
            return
        self.wisp_timer = 0.12
        x0, z0 = math.floor(p.x), math.floor(p.z)
        sources = [t for t in self.world.torches_in(x0 - 24, z0 - 24, x0 + 24, z0 + 24)
                   if t[5] in GLOW_PLANTS or t[5] == GLOW_CAP]
        if not sources:
            return
        for _ in range(3):
            tx, ty, tz, _, col, _ = random.choice(sources)
            x, y, z = tx + random.uniform(-3, 3), ty + random.uniform(0.5, 3.0), tz + random.uniform(-3, 3)
            if self.world.get(math.floor(x), math.floor(y), math.floor(z)) != AIR:
                continue
            if self.light_level() > 0.45 and sample_light(self.world, x, y, z)[0] > 0.3:
                continue                                  # 밝은 낮의 야외엔 보이지 않는다
            if random.random() < 0.35:                    # 하얀 영혼 씨앗 / 그 식물 빛깔의 반딧불이
                col = (0.85, 0.95, 1.0)
            self.wisps.append(Wisp(x, y, z, col))

    def update_particles(self):
        for pt in self.particles:
            pt.update()
        self.particles = [pt for pt in self.particles if pt.life > 0][-600:]

    def burst(self, x, y, z, color, count):
        for _ in range(count):
            self.particles.append(Particle3D(x, y, z, color))

    # ==========================================================================
    # 시간 / 날씨
    # ==========================================================================
    def day_phase(self):
        """0 = 해 뜸(06시), 0.25 = 정오, 0.5 = 해 짐, 0.75 = 자정"""
        return (self.day_time % DAY_LENGTH) / DAY_LENGTH

    def light_level(self):
        sun = math.sin(self.day_phase() * 2 * math.pi)
        return max(0.0, min(1.0, (sun + 0.15) / 0.45))

    def brightness(self):
        b = 0.22 + 0.78 * self.light_level()
        b *= {"clear": 1.0, "rain": 0.8, "storm": 0.65}[self.weather]
        return min(1.0, b + self.flash)

    def sky_color(self):
        sun = math.sin(self.day_phase() * 2 * math.pi)
        r, g, b = 0.50, 0.68, 0.88
        glow = max(0.0, 1.0 - abs(sun) / 0.25)        # 해 뜰 녘/질 녘 노을
        r, g, b = r + (0.95 - r) * glow * 0.6, g + (0.55 - g) * glow * 0.6, b + (0.35 - b) * glow * 0.6
        grey = {"clear": 0.0, "rain": 0.6, "storm": 0.8}[self.weather]
        r, g, b = r + (0.5 - r) * grey, g + (0.52 - g) * grey, b + (0.56 - b) * grey
        if not self.shader.enabled:                   # 셰이더가 없으면 화면을 덮어서 어둡게 한다 (render_hud)
            return r, g, b
        day = max(self.light_level(), glow * 0.45)    # 밤하늘은 어둡게, 노을은 남긴다
        night = (0.02, 0.03, 0.07)
        return tuple(n + (c - n) * day + self.flash for n, c in zip(night, (r, g, b)))

    def to_eye(self, v):
        """월드 방향 벡터 → 카메라(눈) 좌표계 방향 (셰이더의 빛 방향용)"""
        p = self.player
        ty, tp = math.radians(p.yaw), math.radians(-p.pitch)
        x, y, z = v
        x, z = x * math.cos(ty) + z * math.sin(ty), -x * math.sin(ty) + z * math.cos(ty)
        y, z = y * math.cos(tp) - z * math.sin(tp), y * math.sin(tp) + z * math.cos(tp)
        return x, y, z

    @property
    def hdr(self):
        """그림자·HDR·후처리를 쓰는가"""
        return self.gfx is not None and self.gfx.enabled

    def sun_world(self):
        a = self.day_phase() * 2 * math.pi
        n = math.sqrt(1 + 0.25 ** 2)
        return math.cos(a) / n, math.sin(a) / n, 0.25 / n          # 동쪽에서 떠서 서쪽으로

    def light_settings(self, sky, fog_start, fog_end):
        """시간대·날씨에 따른 해/달 빛, 하늘 주변광, 횃불 등 이번 프레임의 빛 설정"""
        sun = self.sun_world()
        moon = (-sun[0], -sun[1], -sun[2])
        weather = {"clear": 1.0, "rain": 0.55, "storm": 0.4}[self.weather]
        sun_k = max(0.0, min(1.0, sun[1] * 4 + 0.15)) * weather
        warm = max(0.0, min(1.0, sun[1] * 2.5))                 # 해가 낮으면 노을빛
        if self.hdr:                                            # 셰이더팩: 강하고 따뜻한 햇빛, 푸르스름한 그늘
            sun_col = tuple((lo + (hi - lo) * warm) * 1.6 * sun_k
                            for lo, hi in zip((1.0, 0.42, 0.16), (1.0, 0.88, 0.7)))
            night, noon = (0.07, 0.09, 0.16), (0.27, 0.36, 0.52)
        else:
            sun_col = tuple((lo + (hi - lo) * warm) * 0.85 * sun_k
                            for lo, hi in zip((1.0, 0.5, 0.25), (1.0, 0.95, 0.86)))
            night, noon = (0.11, 0.12, 0.2), (0.46, 0.49, 0.55)      # 하늘에서 고르게 오는 빛 (밤 / 낮)
        moon_k = max(0.0, min(1.0, -sun[1] * 4)) * weather
        day = self.light_level()
        ambient = tuple((nc + (dc - nc) * day) * (0.6 + 0.4 * weather) for nc, dc in zip(night, noon))
        return {
            "u_sun_dir": self.to_eye(sun), "u_moon_dir": self.to_eye(moon), "u_up": self.to_eye((0, 1, 0)),
            "u_sun_color": sun_col, "u_moon_color": (0.2 * moon_k, 0.25 * moon_k, 0.4 * moon_k),
            "u_ambient": ambient, "u_block_color": LIGHT_COLORS.get(self.held_item(), WARM_LIGHT),
            "u_hand": 1.0 if self.held_item() in LIGHT_BLOCKS else 0.0, "u_flash": self.flash * 2.5,
            "u_fog_color": sky, "u_fog": (fog_start, fog_end), "u_time": pygame.time.get_ticks() / 1000.0,
        }

    def setup_fallback_light(self, settings):
        """셰이더를 못 쓰는 그래픽 환경: OpenGL 기본 조명으로 해 방향 명암만 준다"""
        a = self.day_phase() * 2 * math.pi
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glEnable(GL_COLOR_MATERIAL)
        glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)
        glLightfv(GL_LIGHT0, GL_POSITION, (math.cos(a), max(0.2, math.sin(a)), 0.25, 0.0))
        glLightfv(GL_LIGHT0, GL_DIFFUSE, (*settings["u_sun_color"], 1.0))
        glLightModelfv(GL_LIGHT_MODEL_AMBIENT, (*settings["u_ambient"], 1.0))

    def update_time_weather(self, dt):
        self.day_time += dt
        self.weather_timer -= dt
        if self.weather_timer <= 0:
            options = WEATHER_CHANGES[self.weather]
            self.weather = random.choices([w for w, _ in options], weights=[c for _, c in options])[0]
            self.weather_timer = random.uniform(60, 150)
        if self.weather == "storm":
            self.lightning_timer -= dt
            if self.lightning_timer <= 0:
                self.lightning_timer = random.uniform(5, 14)
                self.flash = 0.25
        self.flash = max(0.0, self.flash - dt)

    def update_rain(self):
        p = self.player
        target = {"clear": 0, "rain": 180, "storm": 320}[self.weather]
        del self.raindrops[target:]
        while len(self.raindrops) < target:
            self.raindrops.append([p.x + random.uniform(-14, 14), p.y + random.uniform(0, 14),
                                   p.z + random.uniform(-14, 14)])
        wind = 0.06 if self.weather == "storm" else 0.0
        for d in self.raindrops:
            d[0] += wind
            d[1] -= 0.5
            hit = block_at(self.world, d[0], d[1], d[2]) != AIR or \
                is_solid(self.world, math.floor(d[0]), math.floor(d[1]), math.floor(d[2]))
            if hit or d[1] < p.y - 6:
                d[0] = p.x + random.uniform(-14, 14)
                d[1] = p.y + random.uniform(8, 14)
                d[2] = p.z + random.uniform(-14, 14)

    # ==========================================================================
    # 3D 렌더링
    # ==========================================================================
    def render(self):
        if self.state != "PLAYING":
            glClearColor(0.0, 0.0, 0.0, 1.0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            if self.state == "MENU":
                self.render_menu()
            elif self.state == "SEED":
                self.render_seed()
            else:
                self.render_controls()
            return

        p = self.player
        hdr = self.hdr
        sky = (0.1, 0.25, 0.5) if p.head_in_water else self.sky_color()
        if hdr and not p.head_in_water:
            sky = (sky[0] * 1.05, sky[1] * 1.12, sky[2] * 1.12)    # 셰이더팩 하늘: 맑고 푸른 지평선
        eye = (p.x, p.view_y + Player.EYE, p.z)
        sun = self.sun_world()
        now = pygame.time.get_ticks() / 1000.0
        ceiling = self.view_ceiling()

        # 1) 그림자 지도: 해가 떠 있고 땅 위에 있을 때, 두 프레임에 한 번 (그 사이엔 지난 지도와 그때 행렬을 그대로 쓴다)
        shadow_on = hdr and sun[1] > 0.06 and ceiling == math.inf and not p.head_in_water
        if shadow_on and (self.frame % 2 == 0 or self.gfx.shadow.light is None):
            self.gfx.shadow.begin(sun, eye, now)
            self.renderer.draw_shadow(p.x, p.z, SHADOW_RADIUS)
            self.gfx.shadow.end(SCREEN_WIDTH, SCREEN_HEIGHT)
        if hdr:
            self.gfx.begin_scene()                              # 이제부터 HDR 장면 버퍼에 그린다
        glClearColor(*sky, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(70.0, SCREEN_WIDTH / float(SCREEN_HEIGHT), 0.05, 3000.0)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        glRotatef(-p.pitch, 1.0, 0.0, 0.0)
        glRotatef(p.yaw, 0.0, 1.0, 0.0)
        glTranslatef(-p.x, -(p.view_y + Player.EYE), -p.z)

        clear = {"clear": 1.0, "rain": 0.25, "storm": 0.1}[self.weather]
        if hdr:
            zenith = (sky[0] * 0.3, sky[1] * 0.55, sky[2] * 0.92)      # 머리 위는 짙은 파랑
            sun_col = self.light_settings(sky, 0, 1)["u_sun_color"]
            night = max(0.0, 1.0 - self.light_level() * 2.5) * clear
            self.gfx.draw_sky(p.yaw, p.pitch, eye[1], sun, sky, zenith, sun_col, now,
                              {"clear": 0.5, "rain": 0.85, "storm": 0.97}[self.weather], night,
                              self.light_level(), CLOUD_Y)
        else:
            self.render_sky(sky)

        # 안개: 주변 지형은 또렷한 색 그대로, 렌더 거리 끝의 좁은 띠에서만 실루엣으로 바뀌고 (섬·산이 서서히 나타난다),
        # 그 너머 먼 풍경 실루엣은 더 멀어질수록 하늘에 녹아든다. 비·폭풍·물속은 짙게
        reach = RENDER_DISTANCE * CHUNK_SIZE
        if p.head_in_water:
            fog_start, fog_end, far = (0.0, 5.0, (12.0, 14.0)) if hdr else (2.0, 12.0, (12.0, 14.0))
        elif hdr:                                     # 셰이더팩: 대기 원근 (멀수록 엷게 하늘빛) - 지형이 멀리까지 겹겹이 보인다
            k = {"clear": 1.0, "rain": 0.35, "storm": 0.22}[self.weather]
            fog_start, fog_end = 40.0 * k, 900.0 * k
            far = ((LOD_RADIUS - 160) * max(k, 0.3), (LOD_RADIUS - 20) * max(k, 0.3))
        else:
            k = {"clear": 1.0, "rain": 0.75, "storm": 0.6}[self.weather]
            fog_start, fog_end = reach * (0.8 if k == 1.0 else 0.5) * k, reach * k   # 주변은 선명하게, 끝에서만 실루엣으로
            far = (reach * k, (LOD_RADIUS - 20) * {"clear": 1.0, "rain": 0.45, "storm": 0.3}[self.weather])
        glEnable(GL_FOG)                              # 셰이더를 안 쓰는 파티클·비에 쓰는 안개
        glFogfv(GL_FOG_COLOR, (*sky, 1.0))
        glFogf(GL_FOG_START, fog_start)
        glFogf(GL_FOG_END, fog_end)

        # 빛을 받는 것들: 지형, 몹, 떨어지는 블록 (셰이더가 해·달·하늘빛·횃불 빛을 계산)
        settings = self.light_settings(sky, fog_start, fog_end)
        settings["u_cam"] = (p.x, p.view_y + Player.EYE, p.z)
        settings["u_lod_clip"] = float(min(LOD_CLIP, self.renderer.missing_dist - CHUNK_SIZE))   # 빈 청크 자리는 먼 지형이 메운다
        settings["u_far"] = far
        settings["u_hdr"] = 1.0 if hdr else 0.0
        settings["u_shadow_on"] = 1.0 if shadow_on and self.gfx.shadow.light else 0.0
        if settings["u_shadow_on"]:
            settings["u_shadow_mat"] = tuple(self.gfx.shadow.eye_matrix(eye_to_world(p.yaw, p.pitch, eye)))
            self.gfx.bind_shadow()
        if self.shader.enabled:
            self.shader.set_frame(settings)
            self.shader.use(True)
        if self.shader.enabled:
            self.far.update(self.world, p.x, p.z)
            if ceiling == math.inf:                   # 깊은 동굴 속에선 먼 풍경이 바위에 가려 보이지 않는다
                self.far.draw(p.x, p.z, p.yaw)
        else:
            self.setup_fallback_light(settings)
        drawn = self.renderer.draw(self.world, p.x, p.z, p.yaw, p.pitch, p.view_y + Player.EYE, ceiling)
        self.frame += 1
        for thing in self.mobs + self.falling_blocks + self.primed:
            # 몹 위치의 빛은 몇 프레임에 한 번만 다시 계산 (최적화)
            if getattr(thing, "light_cache", None) is None or (self.frame + id(thing)) % 12 == 0:
                thing.light_cache = sample_light(self.world, thing.x, thing.view_y + thing.h * 0.6, thing.z)
            glMultiTexCoord3f(GL_TEXTURE0, thing.light_cache[0], thing.light_cache[1], 0.0)
            glSecondaryColor3f(*thing.light_cache[2:5])
            thing.draw()
        if p.hp > 0:
            self.render_body()
        if not hdr:                                   # 셰이더팩 하늘은 구름을 하늘 셰이더에서 그린다
            self.render_clouds()
        self.shader.use(False)
        glDisable(GL_LIGHTING)

        self.render_particles()
        self.render_wisps()
        self.shader.use(True)
        self.renderer.draw_translucent(drawn)
        self.shader.use(False)
        if self.target_block is not None and self.target_mob is None:
            self.render_target_highlight()
        self.render_rain()
        glDisable(GL_FOG)
        if p.hp > 0 and not self.show_inventory:
            self.render_hand(settings)

        if hdr:                                       # 블룸·햇살·톤 매핑을 거쳐 화면으로
            sun_uv, front = self.gfx.sun_screen(p.yaw, p.pitch, sun)
            rays = front * clear * max(0.0, min(1.0, sun[1] * 3.0)) * (0.0 if p.head_in_water or ceiling != math.inf else 1.0)
            sc = settings["u_sun_color"]
            m = max(sc) or 1.0
            self.gfx.finish(1.15, sun_uv, rays, (sc[0] / m * 0.9, sc[1] / m * 0.8, sc[2] / m * 0.6))
        self.render_hud()

    def render_sky(self, sky):
        """하늘: 위로 갈수록 짙어지는 색, 둥근 해·달과 빛무리, 밤하늘 별"""
        p = self.player
        a = self.day_phase() * 2 * math.pi
        n = math.sqrt(1 + 0.25 ** 2)
        sun = (math.cos(a) / n, math.sin(a) / n, 0.25 / n)
        clear = {"clear": 1.0, "rain": 0.25, "storm": 0.1}[self.weather]
        glDepthMask(GL_FALSE)
        glDisable(GL_DEPTH_TEST)
        glPushMatrix()
        glTranslatef(p.x, p.view_y + Player.EYE, p.z)

        # 하늘 돔: 지평선은 밝고 머리 위는 짙게. 하늘색이 바뀔 때만 정점 배열을 다시 만든다
        key = tuple(round(c, 3) for c in sky)
        if getattr(self, "dome_key", None) != key:
            zenith = tuple(c * 0.68 for c in sky)
            horizon = tuple(min(1.0, c * 1.1 + 0.05) for c in sky)
            rings = [-0.35, 0.0, 0.12, 0.3, 0.55, 0.8, 1.0]
            data = array("f")
            for lo, hi in zip(rings, rings[1:]):
                for i in range(24):
                    for ang, e in ((i, lo), (i + 1, lo), (i + 1, hi), (i, hi)):
                        ang = ang / 24 * 2 * math.pi
                        t = max(0.0, e) ** 0.7
                        r = math.sqrt(max(0.0, 1 - e * e)) * 250
                        data.extend((math.cos(ang) * r, e * 250, math.sin(ang) * r,
                                     *(h + (zc - h) * t for h, zc in zip(horizon, zenith)), 0, 1, 0, 1, 0, 0))
            self.dome_key, self.dome = key, data
        draw_client_arrays(self.dome)

        # 별: 밤에만, 하늘과 함께 돈다
        night = max(0.0, 1.0 - self.light_level() * 2.5) * clear
        if night > 0.02:
            glPushMatrix()
            glRotatef(math.degrees(a), 0, 0, 1)
            glPointSize(2.0)
            glBegin(GL_POINTS)
            for x, y, z, b in self.stars:
                glColor4f(1.0, 1.0, 0.95, night * b)
                glVertex3f(x * 240, y * 240, z * 240)
            glEnd()
            glPopMatrix()

        # 해·달: 둥근 원반 + 은은한 빛무리
        for d, size, col, glow in ((sun, 12, (1.0, 0.95, 0.75), 0.5), (tuple(-c for c in sun), 8, (0.9, 0.92, 1.0), 0.18)):
            if d[1] < -0.15:
                continue
            cx, cy, cz = d[0] * 230, d[1] * 230, d[2] * 230
            ux, uy, uz = -d[1], d[0], 0.0                                   # 방향에 수직인 두 축
            vx, vy, vz = d[1] * uz - d[2] * uy, d[2] * ux - d[0] * uz, d[0] * uy - d[1] * ux
            for radius, alpha_c, alpha_e in ((size * 5, glow * clear, 0.0), (size, clear, clear)):
                glBegin(GL_TRIANGLE_FAN)
                glColor4f(*col, alpha_c)
                glVertex3f(cx, cy, cz)
                glColor4f(*col, alpha_e)
                for i in range(25):
                    ang = i / 24 * 2 * math.pi
                    ca, sa = math.cos(ang) * radius, math.sin(ang) * radius
                    glVertex3f(cx + ux * ca + vx * sa, cy + uy * ca + vy * sa, cz + uz * ca + vz * sa)
                glEnd()
        glPopMatrix()
        glEnable(GL_DEPTH_TEST)
        glDepthMask(GL_TRUE)

    def view_ceiling(self):
        """깊은 동굴 속(하늘빛이 없고 원래 땅보다 한참 아래)이면 머리 위 이 높이부터는 그리지 않는다"""
        p = self.player
        x, z = math.floor(p.x), math.floor(p.z)
        heights = self.world.heights.get((x >> 4, z >> 4))
        eye = p.view_y + Player.EYE
        if heights is None or self.player_light()[0] > 0.05 or eye > heights[((x & 15) << 4) | (z & 15)] - 10:
            return math.inf
        return eye + 24

    def player_light(self):
        p = self.player
        if self.frame % 6 == 0 or not hasattr(self, "p_light"):
            self.p_light = sample_light(self.world, p.x, p.view_y + 1.0, p.z)
        return self.p_light

    def shirt_color(self):
        """갑옷이 있으면 가장 좋은 갑옷 색, 없으면 셔츠 색"""
        worn = [a for a in ARMOR_TINT if self.inventory.get(a, 0) > 0]
        return ARMOR_TINT[max(worn, key=lambda a: ARMOR_REDUCTION[a])] if worn else SHIRT

    def render_body(self):
        """1인칭 몸: 아래를 보면 몸통과 다리가 보인다. 머리는 카메라 자리라 그리지 않는다"""
        p = self.player
        sky, block, *lcol = self.player_light()
        glMultiTexCoord3f(GL_TEXTURE0, sky, block, 0.0)
        glSecondaryColor3f(*lcol)
        shirt = self.shirt_color()
        leg = math.sin(self.walk_phase) * 38 * self.walk_amount
        glPushMatrix()
        glTranslatef(p.x, p.view_y, p.z)
        glRotatef(180 - p.yaw, 0, 1, 0)                       # 몸은 바라보는 쪽(+z)으로
        glTranslatef(0, 0, -0.2)                              # 눈보다 살짝 뒤에 몸통이 있다
        for side, ang in ((-1, leg), (1, -leg)):              # 다리 (엉덩이를 축으로 흔들림)
            glPushMatrix()
            glTranslatef(side * 0.12, 0.75, 0)
            glRotatef(ang, 1, 0, 0)
            draw_box(-0.12, -0.75, -0.12, 0.24, 0.62, 0.24, PANTS)
            draw_box(-0.12, -0.75, -0.12, 0.24, 0.13, 0.24, SHOES)
            glPopMatrix()
        draw_box(-0.25, 0.75, -0.13, 0.5, 0.68, 0.26, shirt)  # 몸통
        glPushMatrix()                                        # 왼팔 (오른팔은 화면 앞에 따로 그린다)
        glTranslatef(-0.37, 1.38, 0)
        glRotatef(-leg * 0.8, 1, 0, 0)
        draw_box(-0.12, -0.66, -0.12, 0.24, 0.66, 0.24, SKIN)
        draw_box(-0.125, -0.28, -0.125, 0.25, 0.3, 0.25, shirt)
        glPopMatrix()
        glPopMatrix()

    def render_hand(self, settings):
        """1인칭 오른팔과 든 아이템. 지형에 파묻히지 않도록 깊이를 비우고 화면 바로 앞에 그린다"""
        p = self.player
        glClear(GL_DEPTH_BUFFER_BIT)
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()
        if self.shader.enabled:
            self.shader.set_frame({"u_fog": (100.0, 200.0)})              # 손은 안개에 묻히지 않게
            self.shader.use(True)
        else:
            self.setup_fallback_light(settings)
        sky, block, *lcol = self.player_light()
        glMultiTexCoord3f(GL_TEXTURE0, sky, block, 0.0)
        glSecondaryColor3f(*lcol)
        bob = self.walk_amount
        sw = math.sin((1 - self.swing) * math.pi) if self.swing > 0 else 0.0
        glTranslatef(0.42 + math.sin(self.walk_phase) * 0.03 * bob - sw * 0.12,
                     -0.42 - abs(math.cos(self.walk_phase)) * 0.035 * bob + sw * 0.08, -0.62)
        glRotatef(-sw * 55, 1, 0, 0)                          # 아래로 내려치기
        glRotatef(8 + sw * 20, 0, 1, 0)
        shirt = self.shirt_color()
        draw_box(-0.07, -0.07, -0.5, 0.14, 0.14, 0.5, SKIN)   # 팔뚝 (앞쪽이 -z)
        draw_box(-0.075, -0.075, -0.18, 0.15, 0.15, 0.3, shirt)
        item = self.held_item()
        if item != AIR:
            glTranslatef(0, 0.06, -0.5)
            if item in BLOCK_COLORS and item not in DECOR_BLOCKS and item not in GLOW_ITEMS:
                top, side = block_face_colors(item)
                glRotatef(25, 0, 1, 0)
                draw_box(-0.11, 0.0, -0.11, 0.22, 0.22, 0.22, side, top)
            elif item in GLOW_ITEMS:
                draw_box(-0.025, 0.0, -0.025, 0.05, 0.28, 0.05, (0.55, 0.38, 0.2))
                glMultiTexCoord3f(GL_TEXTURE0, 1.0, 1.0, MAT_GLOW)
                draw_box(-0.04, 0.26, -0.04, 0.08, 0.07, 0.08, BLOCK_COLORS[item])
            else:                                             # 도구·무기·재료: 손잡이 + 머리
                col = ITEM_COLORS.get(item, (0.7, 0.7, 0.7))
                glRotatef(-35, 1, 0, 0)
                if item in PICKAXE_POWER or item in AXE_POWER or item in WEAPON_DAMAGE or item == STICK:
                    draw_box(-0.02, -0.05, -0.02, 0.04, 0.42, 0.04, (0.55, 0.38, 0.2))
                    if item in PICKAXE_POWER:
                        draw_box(-0.16, 0.34, -0.025, 0.32, 0.06, 0.05, col)
                    elif item in AXE_POWER:
                        draw_box(-0.02, 0.26, -0.025, 0.14, 0.14, 0.05, col)
                    elif item in WEAPON_DAMAGE:
                        draw_box(-0.03, 0.12, -0.015, 0.06, 0.42, 0.03, col)
                else:
                    draw_box(-0.07, 0.0, -0.07, 0.14, 0.12, 0.14, col)
        self.shader.use(False)
        glDisable(GL_LIGHTING)
        glPopMatrix()

    def render_clouds(self):
        """천천히 흘러가는 구름층. 구름 모양은 노이즈로 정하고, 카메라가 칸을 넘을 때만 다시 만든다"""
        if not self.shader.enabled:
            return
        p = self.player
        drift = pygame.time.get_ticks() / 1000.0 * 1.2
        ccx = math.floor((p.x - drift) / CLOUD_CELL)
        ccz = math.floor(p.z / CLOUD_CELL)
        if self.cloud_key != (ccx, ccz):
            self.cloud_key = (ccx, ccz)
            delete_mesh(self.cloud_mesh)
            cover = {"clear": 0.6, "rain": 0.5, "storm": 0.45}[self.weather]
            cells = {(gx, gz) for gx in range(ccx - CLOUD_RANGE, ccx + CLOUD_RANGE + 1)
                     for gz in range(ccz - CLOUD_RANGE, ccz + CLOUD_RANGE + 1)
                     if self.cloud_noise(gx, gz) > cover}
            tris = []
            for gx, gz in cells:
                skip = [d for d, (dx, dz) in (((1, 0, 0), (1, 0)), ((-1, 0, 0), (-1, 0)),
                                              ((0, 0, 1), (0, 1)), ((0, 0, -1), (0, -1)))
                        if (gx + dx, gz + dz) in cells]
                tris += box_tris(gx * CLOUD_CELL, CLOUD_Y, gz * CLOUD_CELL, CLOUD_CELL, 8, CLOUD_CELL,
                                 (0.97, 0.97, 1.0), 0.86, (1.0, 0.0, MAT_CLOUD), skip)
            self.cloud_mesh = upload_mesh(tris)
        glPushMatrix()
        glTranslatef(drift, 0, 0)
        glDepthMask(GL_FALSE)
        draw_mesh(self.cloud_mesh)
        glDepthMask(GL_TRUE)
        glPopMatrix()

    def render_particles(self):
        if not self.particles:
            return
        rad = math.radians(self.player.yaw)
        rx, rz = math.cos(rad), math.sin(rad)
        glBegin(GL_QUADS)
        for pt in self.particles:
            pt.emit(rx, rz)
        glEnd()

    def render_wisps(self):
        """빛 정령: 더하기 혼합이라 겹칠수록 밝고, 깊이는 쓰지 않는다"""
        if not self.wisps:
            return
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE)
        glDepthMask(GL_FALSE)
        glDisable(GL_FOG)
        glEnable(GL_POINT_SMOOTH)
        for size, halo in ((11.0, True), (3.5, False)):   # 퍼지는 빛무리 위에 밝은 알갱이
            glPointSize(size)
            glBegin(GL_POINTS)
            for w in self.wisps:
                w.emit(halo)
            glEnd()
        glDisable(GL_POINT_SMOOTH)
        glPointSize(1.0)
        glEnable(GL_FOG)
        glDepthMask(GL_TRUE)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    def render_rain(self):
        if not self.raindrops:
            return
        wind = 0.06 if self.weather == "storm" else 0.0
        glLineWidth(1.5)
        glColor4f(0.7, 0.78, 0.95, 0.75)
        glBegin(GL_LINES)
        for x, y, z in self.raindrops:
            glVertex3f(x, y, z)
            glVertex3f(x - wind * 2, y + 0.9, z)
        glEnd()

    def render_target_highlight(self):
        bx, by, bz = self.target_block
        e = 0.003
        x0, y0, z0, x1, y1, z1 = bx - e, by - e, bz - e, bx + 1 + e, by + 1 + e, bz + 1 + e
        # 채굴 진행에 따라 어두워지는 균열 표시
        if self.mining_progress > 0:
            glColor4f(0.0, 0.0, 0.0, 0.15 + self.mining_progress * 0.55)
            glBegin(GL_QUADS)
            for _, _, _, verts in FACES:
                for vx, vy, vz in verts:
                    glVertex3f(x0 + vx * (x1 - x0), y0 + vy * (y1 - y0), z0 + vz * (z1 - z0))
            glEnd()
        glLineWidth(2.0)
        glColor4f(0.0, 0.0, 0.0, 0.8)
        glBegin(GL_LINES)
        for x, z in ((x0, z0), (x1, z0), (x1, z1), (x0, z1)):
            glVertex3f(x, y0, z); glVertex3f(x, y1, z)
        for y in (y0, y1):
            for (ax, az), (bx2, bz2) in (((x0, z0), (x1, z0)), ((x1, z0), (x1, z1)),
                                         ((x1, z1), (x0, z1)), ((x0, z1), (x0, z0))):
                glVertex3f(ax, y, az); glVertex3f(bx2, y, bz2)
        glEnd()

    # ==========================================================================
    # 2D HUD / 화면
    # ==========================================================================
    def begin_2d(self):
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        glOrtho(0, SCREEN_WIDTH, SCREEN_HEIGHT, 0, -1, 1)
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_FOG)

    def end_2d(self):
        glEnable(GL_DEPTH_TEST)
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()
        glMatrixMode(GL_MODELVIEW)
        glPopMatrix()

    def render_hud(self):
        p = self.player
        W, H = SCREEN_WIDTH, SCREEN_HEIGHT
        self.begin_2d()

        darkness = 0.0 if self.shader.enabled else (1.0 - self.brightness()) * 0.85   # 셰이더가 없을 때만 화면을 덮어 어둡게
        if darkness > 0.01:
            draw_2d_rect(0, 0, W, H, (0.0, 0.0, 0.05, darkness))
        if p.head_in_water:
            draw_2d_rect(0, 0, W, H, (0.05, 0.2, 0.55, 0.35))
        if self.flash > 0:
            draw_2d_rect(0, 0, W, H, (1.0, 1.0, 0.9, min(0.6, self.flash * 3)))
        if p.hurt_flash > 0:
            draw_2d_rect(0, 0, W, H, (0.8, 0.0, 0.0, p.hurt_flash))

        if not (self.show_inventory or self.show_pause or p.hp <= 0):
            cx, cy = W // 2, H // 2
            glLineWidth(2.0)
            glColor4f(1.0, 1.0, 1.0, 1.0)
            glBegin(GL_LINES)
            glVertex2f(cx - 8, cy); glVertex2f(cx + 8, cy)
            glVertex2f(cx, cy - 8); glVertex2f(cx, cy + 8)
            glEnd()
            self.render_target_info()

        self.render_status_bars()
        self.render_info_text()
        if self.show_inventory:
            self.render_inventory()
        self.render_hotbar()
        if self.show_pause:
            self.render_pause()
        if p.hp <= 0:
            self.render_death()
        if self.notice_timer > 0:
            self.draw_text_center(self.notice, pygame.Rect(0, 120, W, 30), (255, 255, 160), self.bold_font)
        self.end_2d()

    def render_target_info(self):
        cx, cy = SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2
        if self.target_mob is not None:
            m = self.target_mob
            name = MOB_NAMES[m.kind] + (" (화남)" if m.angry_timer > 0 else "")
            self.draw_text_center(f"{name}  HP {max(0, m.hp)}/{m.max_hp}", pygame.Rect(cx - 100, cy + 16, 200, 18),
                                  (255, 200, 200))
            draw_2d_rect(cx - 50, cy + 36, 100, 6, (0.2, 0.2, 0.2, 0.8))
            draw_2d_rect(cx - 50, cy + 36, int(100 * max(0, m.hp) / m.max_hp), 6, (0.9, 0.2, 0.2, 1.0))
            return
        if self.target_block is None:
            return
        bx, by, bz = self.target_block
        bid = self.world.get(bx, by, bz)
        t = self.mining_time(bid)
        if t == math.inf:
            self.draw_text_center(f"{ITEM_NAMES.get(bid, '?')} - 파괴 불가", pygame.Rect(cx - 150, cy + 16, 300, 18),
                                  (255, 120, 120))
            return
        self.draw_text_center(f"{ITEM_NAMES.get(bid, '?')}  ({t:.1f}초)", pygame.Rect(cx - 150, cy + 16, 300, 18),
                              (255, 255, 200))
        if self.mining_progress > 0:
            draw_2d_rect(cx - 82, cy + 38, 164, 14, (0.1, 0.1, 0.1, 0.8))
            draw_2d_rect(cx - 80, cy + 40, int(160 * min(1.0, self.mining_progress)), 10, (0.2, 0.9, 0.2, 1.0))

    def render_status_bars(self):
        p = self.player
        if self.creative:                                 # 크리에이티브엔 체력·배고픔 칸이 없다
            return
        rects = self.hotbar_rects()
        left, right = rects[0].x, rects[-1].right
        y = rects[0].y - 24
        for i in range(10):
            hx = left + i * 17
            draw_2d_rect(hx, y, 14, 12, (0.15, 0.15, 0.15, 0.85))
            v = p.hp - i * 2
            if v >= 1:
                draw_2d_rect(hx + 1, y + 1, 12 if v >= 2 else 6, 10, (0.9, 0.1, 0.1, 1.0))
        for i in range(10):
            hx = right - 14 - i * 17
            draw_2d_rect(hx, y, 14, 12, (0.15, 0.15, 0.15, 0.85))
            v = p.hunger - i * 2
            if v >= 1:
                w = 12 if v >= 2 else 6
                draw_2d_rect(hx + 13 - w, y + 1, w, 10, (0.85, 0.55, 0.2, 1.0))
        if p.head_in_water or p.oxygen < p.max_oxygen:
            for i in range(math.ceil(p.oxygen)):
                draw_2d_rect(right - 14 - i * 17 + 2, y - 16, 10, 10, (0.55, 0.8, 1.0, 1.0))

    def render_info_text(self):
        p = self.player
        hour_f = (self.day_phase() * 24 + 6) % 24
        day = int(self.day_time // DAY_LENGTH) + 1
        lines = [
            f"{day}일차  {int(hour_f):02d}:{int(hour_f % 1 * 60):02d}  날씨: {WEATHER_NAMES[self.weather]}"
            + (f"   방어 {int(self.armor() * 100)}%" if self.armor() and not self.creative else "")
            + f"   모드: {MODE_NAMES[self.mode]}" + ("  [비행 중]" if self.player.flying else ""),
            f"위치 X {p.x:.1f}  Y {p.y:.1f}  Z {p.z:.1f}   바이옴: {BIOME_NAMES[self.world.biome_at(p.x, p.z)]}   시드 {self.seed}",
            f"FPS {self.clock.get_fps():.0f}   렌더링 청크 {self.renderer.visible_count}   불러온 지형 청크 {len(self.world.chunks)}"
            f"   몹 {len(self.mobs)}",
            "[E] 인벤토리·조합  [ESC] 일시정지  좌클릭: 채굴(누르기)/공격  우클릭: 설치·먹기·작업대  Shift: 달리기",
        ]
        for i, line in enumerate(lines):
            self.draw_text_2d(line, 12, 10 + i * 18, (240, 240, 240))

    def render_hotbar(self):
        rects = self.hotbar_rects()
        draw_2d_rect(rects[0].x - 4, rects[0].y - 4, rects[-1].right - rects[0].x + 8, 52, (0.08, 0.08, 0.08, 0.8))
        for i, (rect, item) in enumerate(zip(rects, self.hotbar)):
            selected = i == self.selected_slot
            draw_2d_rect(rect.x, rect.y, rect.w, rect.h, (0.2, 0.2, 0.2, 0.9))
            draw_2d_box_outline(rect.x, rect.y, rect.w, rect.h,
                                (1.0, 1.0, 1.0, 1.0) if selected else (0.4, 0.4, 0.4, 1.0), 3.0 if selected else 1.0)
            cnt = self.inventory.get(item, 0)
            if item != AIR and cnt > 0:
                self.draw_item_icon(item, rect.x + 6, rect.y + 6, rect.w - 12)
                if not self.creative:
                    self.draw_text_2d(str(cnt), rect.right - 18, rect.bottom - 16, (255, 255, 255))
        if not self.show_inventory:
            item = self.held_item()
            name = ITEM_NAMES.get(item, "아이템") if item != AIR else "빈 칸"
            self.draw_text_center(name, pygame.Rect(0, rects[0].y - 66, SCREEN_WIDTH, 18), (255, 255, 255))

    def draw_item_icon(self, item, x, y, size):
        s = size
        if item in BLOCK_COLORS:
            top, side = block_face_colors(item)
            draw_2d_rect(x + s * 0.15, y + s * 0.15, s * 0.7, s * 0.7, (*side, 1.0))
            draw_2d_rect(x + s * 0.15, y + s * 0.15, s * 0.7, s * 0.25, (*top, 1.0))
            return
        col = (*ITEM_COLORS.get(item, (0.7, 0.7, 0.7)), 1.0)
        brown = (0.55, 0.38, 0.2, 1.0)
        if item in PICKAXE_POWER:
            draw_2d_rect(x + s * 0.45, y + s * 0.25, s * 0.1, s * 0.65, brown)
            draw_2d_rect(x + s * 0.15, y + s * 0.15, s * 0.7, s * 0.14, col)
        elif item in AXE_POWER:
            draw_2d_rect(x + s * 0.45, y + s * 0.15, s * 0.1, s * 0.75, brown)
            draw_2d_rect(x + s * 0.2, y + s * 0.15, s * 0.3, s * 0.3, col)
        elif item in ARMOR_REDUCTION:
            draw_2d_rect(x + s * 0.25, y + s * 0.3, s * 0.5, s * 0.55, col)
            draw_2d_rect(x + s * 0.12, y + s * 0.18, s * 0.28, s * 0.2, col)
            draw_2d_rect(x + s * 0.6, y + s * 0.18, s * 0.28, s * 0.2, col)
        elif item in (IRON_INGOT, GOLD_INGOT):
            draw_2d_rect(x + s * 0.15, y + s * 0.4, s * 0.7, s * 0.25, col)
        elif item in WEAPON_DAMAGE:
            draw_2d_rect(x + s * 0.43, y + s * 0.08, s * 0.14, s * 0.55, col)
            draw_2d_rect(x + s * 0.28, y + s * 0.62, s * 0.44, s * 0.08, (0.3, 0.3, 0.3, 1.0))
            draw_2d_rect(x + s * 0.45, y + s * 0.7, s * 0.1, s * 0.22, brown)
        elif item == STICK:
            draw_2d_rect(x + s * 0.45, y + s * 0.15, s * 0.1, s * 0.7, brown)
        else:
            draw_2d_rect(x + s * 0.25, y + s * 0.25, s * 0.5, s * 0.5, col)

    def render_inventory(self):
        W, H = SCREEN_WIDTH, SCREEN_HEIGHT
        draw_2d_rect(0, 0, W, H, (0.0, 0.0, 0.0, 0.55))
        draw_2d_rect(50, 60, 900, 520, (0.18, 0.22, 0.26, 0.96))
        draw_2d_box_outline(50, 60, 900, 520, (0.7, 0.8, 0.9, 1.0), 2.0)
        bench_txt = "작업대 근처 - 모든 조합 가능" if self.near_bench else "작업대가 필요한 조합은 잠김 (작업대 4칸 이내)"
        self.draw_text_2d(f"조합  ({bench_txt})", 70, 78, (255, 220, 100), self.bold_font)
        self.draw_text_2d("인벤토리 - 숫자키로 핫바 칸 선택 후 아이템 클릭", 570, 78, (255, 220, 100), self.bold_font)

        mouse = pygame.mouse.get_pos()
        for rec, rect in self.recipe_rects():
            ok = self.can_craft(rec)
            hover = rect.collidepoint(mouse) and ok
            col = (0.25, 0.55, 0.25, 1.0) if hover else ((0.18, 0.35, 0.18, 1.0) if ok else (0.22, 0.22, 0.22, 1.0))
            draw_2d_rect(rect.x, rect.y, rect.w, rect.h, col)
            req = ", ".join(f"{ITEM_NAMES.get(it, '?').split(' (')[0]} {self.inventory.get(it, 0)}/{cnt}"
                            for it, cnt in rec["req"].items())
            tag = "  [작업대]" if rec["bench"] else ""
            self.draw_text_2d(f"{rec['name']}  <-  {req}{tag}", rect.x + 10, rect.y + 5,
                              (255, 255, 255) if ok else (150, 150, 150))

        hovered = None
        for item, rect in self.inventory_slots():
            in_hotbar = item in self.hotbar
            draw_2d_rect(rect.x, rect.y, rect.w, rect.h, (0.12, 0.12, 0.12, 1.0))
            draw_2d_box_outline(rect.x, rect.y, rect.w, rect.h,
                                (1.0, 0.9, 0.4, 1.0) if in_hotbar else (0.45, 0.45, 0.45, 1.0), 1.5)
            self.draw_item_icon(item, rect.x + 6, rect.y + 4, rect.w - 12)
            self.draw_text_2d("∞" if self.creative else str(self.inventory[item]), rect.right - 20, rect.bottom - 16,
                              (255, 255, 255))
            if rect.collidepoint(mouse):
                hovered = item
        if hovered is not None:
            self.draw_text_2d(ITEM_NAMES.get(hovered, "?"), 570, 552, (255, 255, 255), self.bold_font)
        self.draw_text_2d(f"[E]/[ESC] 닫기  휠: 조합 목록 스크롤 ({self.recipe_scroll + 1}~"
                          f"{min(len(RECIPES), self.recipe_scroll + RECIPE_ROWS)}/{len(RECIPES)})", 70, 552, (200, 200, 200))

    def render_pause(self):
        draw_2d_rect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, (0.0, 0.0, 0.0, 0.7))
        self.draw_text_center("게임 일시정지", pygame.Rect(0, 170, SCREEN_WIDTH, 40), (255, 255, 255), self.large_font)
        for _, label, rect in self.pause_buttons():
            self.draw_button(rect, label)

    def render_death(self):
        draw_2d_rect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, (0.4, 0.0, 0.0, 0.6))
        self.draw_text_center("사망했습니다!", pygame.Rect(0, 200, SCREEN_WIDTH, 40), (255, 255, 255), self.large_font)
        self.draw_text_center(f"원인: {self.player.death_cause}  (인벤토리는 유지됩니다)",
                              pygame.Rect(0, 260, SCREEN_WIDTH, 24), (255, 220, 220), self.bold_font)
        for _, label, rect in self.death_buttons():
            self.draw_button(rect, label)

    def render_menu(self):
        self.begin_2d()
        draw_2d_rect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, (0.45, 0.68, 0.88, 1.0))
        self.draw_text_center("3D MINECRAFT SANDBOX", pygame.Rect(0, 120, SCREEN_WIDTH, 40), (255, 255, 255),
                              self.large_font)
        self.draw_text_center("블록 물리 · 몹 AI · 생존 · 날씨와 낮/밤 · 청크 렌더링",
                              pygame.Rect(0, 180, SCREEN_WIDTH, 24), (240, 240, 240), self.bold_font)
        for _, label, rect, enabled in self.menu_buttons():
            self.draw_button(rect, label, enabled)
        message = self.menu_message or {
            "old": "기존 세이브는 이전 버전이라 이어할 수 없습니다. 새 게임을 저장하면 덮어씁니다.",
            "broken": "세이브 파일이 손상되어 이어할 수 없습니다.",
        }.get(self.save_status, "")
        if message:
            self.draw_text_center(message, pygame.Rect(0, 545, SCREEN_WIDTH, 20), (255, 240, 200), self.bold_font)
        self.end_2d()

    def render_seed(self):
        self.begin_2d()
        draw_2d_rect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, (0.45, 0.68, 0.88, 1.0))
        self.draw_text_center("새 월드 만들기", pygame.Rect(0, 150, SCREEN_WIDTH, 40), (255, 255, 255), self.large_font)
        self.draw_text_center("시드를 입력하세요. 같은 시드는 언제나 같은 지형·기후의 월드를 만듭니다. (비워 두면 무작위)",
                              pygame.Rect(0, 215, SCREEN_WIDTH, 24), (240, 240, 240), self.bold_font)
        tip = ("서바이벌: 체력·배고픔·몹 공격이 있고 직접 캐고 만들어야 합니다" if self.new_mode == "survival" else
               "크리에이티브: 피해 없음 · 모든 아이템 무한 · 즉시 파괴 · 스페이스 두 번으로 비행")
        self.draw_text_center(tip, pygame.Rect(0, 525, SCREEN_WIDTH, 24), (255, 240, 200), self.bold_font)
        box = pygame.Rect(320, 280, 360, 50)
        draw_2d_rect(box.x, box.y, box.w, box.h, (0.1, 0.1, 0.12, 0.85))
        draw_2d_box_outline(box.x, box.y, box.w, box.h, (1, 1, 1, 0.9), 2)
        cursor = "|" if pygame.time.get_ticks() // 500 % 2 == 0 else ""
        self.draw_text_center((self.seed_text or "") + cursor, box, (255, 255, 255), self.large_font)
        for _, label, rect in self.seed_buttons():
            self.draw_button(rect, label)
        self.end_2d()

    def show_loading(self, title, progress=None):
        """긴 작업(월드 생성, 청크 만들기) 중에 보여 주는 화면"""
        glClearColor(0.0, 0.0, 0.0, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        self.begin_2d()
        draw_2d_rect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, (0.12, 0.16, 0.2, 1.0))
        self.draw_text_center(title, pygame.Rect(0, 270, SCREEN_WIDTH, 40), (255, 255, 255), self.large_font)
        if progress is not None:
            draw_2d_rect(300, 340, 400, 16, (0.3, 0.3, 0.3, 1.0))
            draw_2d_rect(300, 340, 400 * progress, 16, (0.4, 0.85, 0.4, 1.0))
        self.end_2d()
        pygame.display.flip()
        pygame.event.pump()

    def render_controls(self):
        self.begin_2d()
        draw_2d_rect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, (0.15, 0.18, 0.22, 1.0))
        self.draw_text_2d("조작법 & 게임 가이드", 50, 30, (255, 220, 100), self.large_font)
        guides = [
            "- 마우스: 시점 회전   W A S D: 이동   Space: 점프 / 물속에서 헤엄쳐 오르기   Shift: 달리기(허기 소모)",
            "- 좌클릭 누르고 있기: 블록 채굴 (블록마다 시간이 다름)   좌클릭(몹 조준): 공격",
            "- 우클릭: 블록 설치 / 음식 먹기 / 작업대 열기   1~9, 휠: 핫바 선택",
            "- E: 인벤토리·조합창 (숫자키로 핫바 칸을 고른 뒤 아이템을 클릭하면 그 칸에 들어감)",
            "- ESC: 일시정지 & 저장   창을 닫으면 자동 저장",
            "",
            "* 생존: 체력 20, 허기 20. 움직이면 허기가 줄고, 허기 18 이상이면 체력 회복, 0이면 굶주림 피해",
            "* 물속에서는 산소가 줄고, 다 떨어지면 익사 피해. 3칸 넘게 떨어지면 낙하 피해. 선인장은 아픔",
            "* 몹: 돼지(맞으면 도망) / 늑대(때리면 무리가 함께 공격) / 좀비(보이면 추적, 낮에 불탐) / 크리퍼(접근 후 폭발)",
            "* 블록 물리: 모래·원목·선인장은 받침이 사라지면 떨어지고, 나무를 베면 주변 나뭇잎이 서서히 사라짐",
            "* 낮/밤 6분 주기, 밤과 폭풍우에는 적대몹 출현. 날씨는 맑음 / 비 / 폭풍우로 바뀜",
            "* 도구·검·유리·벽돌은 작업대 4칸 이내에서만 제작 가능. 곡괭이는 돌·광석 채굴만 빨라짐",
            "",
            "채굴 시간(맨손): 나뭇잎 0.25초 / 모래 0.6 / 흙 0.75 / 목재 1.4 / 원목 2.2 / 돌 4.5 / 철 6.5 / 다이아 9.0",
            "",
            "[아무 키나 누르거나 클릭하면 메인 메뉴로 돌아갑니다]",
        ]
        for i, g in enumerate(guides):
            self.draw_text_2d(g, 50, 90 + i * 30, (240, 240, 240), self.bold_font)
        self.end_2d()

    def draw_button(self, rect, label, enabled=True):
        hover = rect.collidepoint(pygame.mouse.get_pos()) and enabled
        col = (0.28, 0.62, 0.28, 1.0) if hover else ((0.28, 0.28, 0.28, 1.0) if enabled else (0.2, 0.2, 0.2, 1.0))
        draw_2d_rect(rect.x, rect.y, rect.w, rect.h, col)
        draw_2d_box_outline(rect.x, rect.y, rect.w, rect.h, (0.8, 0.8, 0.8, 1.0) if hover else (0.5, 0.5, 0.5, 1.0), 2.0)
        self.draw_text_center(label, rect, (255, 255, 255) if enabled else (130, 130, 130), self.bold_font)

    # --------------------------------------------------------------------------
    # 텍스트 (렌더링한 글자 텍스처를 캐시해서 재사용)
    # --------------------------------------------------------------------------
    def text_texture(self, text, color, font):
        key = (text, id(font), color)
        entry = self.text_cache.get(key)
        if entry is None:
            if len(self.text_cache) > 400:
                glDeleteTextures([tex for tex, _, _ in self.text_cache.values()])
                self.text_cache.clear()
            surf = font.render(text, True, color)
            w, h = surf.get_size()
            data = pygame.image.tobytes(surf, "RGBA", True)
            tex = glGenTextures(1)
            glBindTexture(GL_TEXTURE_2D, tex)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, data)
            entry = (tex, w, h)
            self.text_cache[key] = entry
        return entry

    def draw_text_2d(self, text, x, y, color, font=None):
        tex, w, h = self.text_texture(text, color, font or self.font)
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, tex)
        glColor4f(1.0, 1.0, 1.0, 1.0)
        glBegin(GL_QUADS)
        glTexCoord2f(0, 0); glVertex2f(x, y + h)
        glTexCoord2f(1, 0); glVertex2f(x + w, y + h)
        glTexCoord2f(1, 1); glVertex2f(x + w, y)
        glTexCoord2f(0, 1); glVertex2f(x, y)
        glEnd()
        glDisable(GL_TEXTURE_2D)

    def draw_text_center(self, text, rect, color, font=None):
        font = font or self.font
        w, h = font.size(text)
        self.draw_text_2d(text, rect.centerx - w // 2, rect.centery - h // 2, color, font)


# 2D 렌더링 헬퍼
def draw_2d_rect(x, y, w, h, color):
    glColor4f(*color)
    glBegin(GL_QUADS)
    glVertex2f(x, y); glVertex2f(x + w, y); glVertex2f(x + w, y + h); glVertex2f(x, y + h)
    glEnd()


def draw_2d_box_outline(x, y, w, h, color, line_w=1.5):
    glLineWidth(line_w)
    glColor4f(*color)
    glBegin(GL_LINE_LOOP)
    glVertex2f(x, y); glVertex2f(x + w, y); glVertex2f(x + w, y + h); glVertex2f(x, y + h)
    glEnd()


if __name__ == "__main__":
    Minecraft3D().run()
