"""3D 마인크래프트 - 엔티티 모듈

플레이어·몹·낙하 블록이 함께 쓰는 물리 엔진(Entity),
몹 AI(수동 / 중립 / 적대), 파티클을 담당한다.
"""
import math
import random
from array import array

from OpenGL.GL import *

from mc3d_world import *

GRAVITY = 0.016          # 블록/프레임²
MAX_FALL_SPEED = 0.6
JUMP_SPEED = 0.26         # 약 2칸 높이까지 뛴다 (울퉁불퉁한 지형용)


# ==============================================================================
# 1. 공용 물리 엔진
# ==============================================================================
class Entity:
    """AABB 충돌, 중력, 마찰(관성), 물 부력, 낙하 거리, 울퉁불퉁한 지형 오르내리기 계산"""

    def __init__(self, x, y, z, radius, height):
        self.x, self.y, self.z = float(x), float(y), float(z)
        self.r = radius
        self.h = height
        self.vx = self.vy = self.vz = 0.0
        self.on_ground = False
        self.in_water = False
        self.head_in_water = False
        self.hit_wall = False
        self.fall_dist = 0.0
        self.floats = False       # True 면 물속에서 수면으로 떠오름
        self.can_step = True      # 1칸 턱은 걸어서 올라감 (다각형 비탈 지형)
        self.view_offset = 0.0    # 턱을 오르내릴 때 화면 높이가 순간이동하지 않도록 남겨 두는 차이
        self.air_frames = 0       # 땅에서 떨어진 지 몇 프레임 (가장자리에서 늦게 눌러도 점프되게)
        self.flying = False       # 크리에이티브 비행: 중력 없이 위아래 속도를 직접 정한다

    @property
    def view_y(self):
        """화면에 그릴 높이: 실제 높이 + 아직 따라가는 중인 차이"""
        return self.y + self.view_offset

    def can_jump(self):
        return not self.in_water and self.vy <= 0.0 and self.air_frames <= 5

    def collides(self, world, x, y, z):
        return body_collides(world, x, y, z, self.r, self.h)

    def knockback(self, from_x, from_z, power):
        dx, dz = self.x - from_x, self.z - from_z
        n = math.hypot(dx, dz) or 1.0
        self.vx += dx / n * power
        self.vz += dz / n * power
        self.vy = max(self.vy, 0.18)

    def step_up(self, world, nx, nz):
        """1칸 턱에 막히면 그 위로 올라선다 (비탈을 걷는 느낌).
        땅 위(또는 막 떨어진 직후)면 1칸까지, 점프 중이면 발끝이 0.6칸 안에 걸칠 때 턱에 올라선다"""
        if not self.can_step or (self.in_water and not self.on_ground):
            return False                          # 얕은 물가(바닥에 발이 닿음)에서는 오를 수 있다
        sy = math.floor(self.y + 0.001) + 1.0
        rise = sy - self.y
        grounded = (self.on_ground or self.air_frames <= 3) and self.vy <= 0.01
        if not (rise <= 0.6 or (grounded and rise <= 1.05)):
            return False
        if self.collides(world, nx, sy, nz):
            return False
        self.view_offset -= rise
        self.y = sy
        self.vy = max(self.vy, 0.0)
        return True

    def step_down(self, world):
        """걸어서 1칸 턱을 내려갈 때 공중에 뜨지 않고 바로 아래 땅에 붙는다"""
        ny = math.ceil(self.y - 0.001) - 1.0
        drop = self.y - ny
        if drop <= 0 or drop > 1.05 or self.collides(world, self.x, ny, self.z):
            return False
        if not self.collides(world, self.x, ny - 0.03, self.z):
            return False
        self.view_offset += drop
        self.y = ny
        self.vy = 0.0
        return True

    def physics(self, world, wish_x, wish_z, swim_up=False):
        """한 프레임 이동. 착지했을 때 받을 낙하 피해량을 반환"""
        was_ground = self.on_ground
        self.in_water = block_at(world, self.x, self.y + 0.3, self.z) == WATER
        self.head_in_water = block_at(world, self.x, self.y + self.h * 0.85, self.z) == WATER

        # 마찰: 원하는 속도로 서서히 수렴 (접지력 지면 > 물 > 공중)
        grip = 0.18 if self.flying else (0.1 if self.in_water else (0.25 if self.on_ground else 0.06))
        self.vx += (wish_x - self.vx) * grip
        self.vz += (wish_z - self.vz) * grip

        if self.flying:
            self.fall_dist = 0.0                  # 비행 중엔 중력도 낙하 거리도 없다
        elif self.in_water:
            self.vy -= 0.006                      # 중력 - 부력 → 천천히 가라앉음
            if self.floats and self.head_in_water:
                self.vy += 0.012
            if swim_up:
                self.vy += 0.016
            if (swim_up or self.floats) and self.hit_wall:
                self.vy = max(self.vy, 0.12)       # 물가로 기어오르기
            self.vy *= 0.85                       # 물 저항
            self.fall_dist = 0.0
        else:
            self.vy = max(-MAX_FALL_SPEED, self.vy - GRAVITY)

        # 블록 안에 끼었으면 빈 곳으로 밀어냄 (머리 위로 모래가 떨어진 경우 등)
        if self.collides(world, self.x, self.y, self.z):
            for dy in (1.0, 2.0, -1.0):
                ny = math.floor(self.y) + dy
                if not self.collides(world, self.x, ny, self.z):
                    self.y = ny
                    self.vy = max(self.vy, 0.0)
                    break

        # 축별로 이동하고 충돌하면 블록 경계에 붙인다
        self.hit_wall = False
        nx = self.x + self.vx
        if self.collides(world, nx, self.y, self.z) and not self.step_up(world, nx, self.z):
            nx = math.floor(nx + self.r) - self.r - 0.001 if self.vx > 0 else math.floor(nx - self.r) + 1 + self.r + 0.001
            if self.collides(world, nx, self.y, self.z):
                nx = self.x
            self.vx = 0.0
            self.hit_wall = True
        self.x = nx

        nz = self.z + self.vz
        if self.collides(world, self.x, self.y, nz) and not self.step_up(world, self.x, nz):
            nz = math.floor(nz + self.r) - self.r - 0.001 if self.vz > 0 else math.floor(nz - self.r) + 1 + self.r + 0.001
            if self.collides(world, self.x, self.y, nz):
                nz = self.z
            self.vz = 0.0
            self.hit_wall = True
        self.z = nz

        prev_y = self.y
        ny = self.y + self.vy
        if self.collides(world, self.x, ny, self.z):
            ny = math.floor(ny) + 1.0 if self.vy < 0 else math.floor(ny + self.h) - self.h - 0.001
            if self.collides(world, self.x, ny, self.z):
                ny = self.y
            self.vy = 0.0
        self.y = ny
        self.on_ground = self.collides(world, self.x, self.y - 0.03, self.z)
        if not self.on_ground and was_ground and self.can_step and self.vy <= 0 and not self.in_water:
            self.on_ground = self.step_down(world)
        self.air_frames = 0 if self.on_ground else self.air_frames + 1
        self.view_offset = max(-1.2, min(1.2, self.view_offset)) * 0.72   # 화면 높이가 서서히 따라감
        if abs(self.view_offset) < 0.005:
            self.view_offset = 0.0

        damage = 0
        if self.on_ground:
            if self.fall_dist > 3.0:              # 3칸 넘게 떨어지면 1칸당 1 피해
                damage = int(self.fall_dist - 3.0)
            self.fall_dist = 0.0
        elif self.y < prev_y and not self.in_water:
            self.fall_dist += prev_y - self.y
        return damage


# ==============================================================================
# 2. 플레이어
# ==============================================================================
class Player(Entity):
    EYE = 1.62

    def __init__(self, x, y, z):
        super().__init__(x, y, z, 0.3, 1.8)
        self.yaw = 0.0
        self.pitch = 0.0
        self.max_hp = 20
        self.hp = 20
        self.max_hunger = 20
        self.hunger = 20
        self.max_oxygen = 10
        self.oxygen = 10.0
        self.exhaustion = 0.0     # 4 쌓이면 허기 1 감소
        self.regen_timer = 0.0
        self.drown_timer = 0.0
        self.invincible = 0.0     # 피격 후 무적 시간
        self.hurt_flash = 0.0
        self.death_cause = ""
        self.creative = False     # 크리에이티브 모드: 피해 없음, 몹이 공격하지 않음

    def hurt(self, amount, cause):
        if self.creative or amount <= 0 or self.hp <= 0 or self.invincible > 0:
            return False
        self.hp = max(0, self.hp - amount)
        self.invincible = 0.5
        self.hurt_flash = 0.35
        if self.hp == 0:
            self.death_cause = cause
        return True


# ==============================================================================
# 3. 몹 (수동: 돼지 / 중립: 늑대 / 적대: 좀비, 크리퍼)
# ==============================================================================
MOB_TYPES = {
    "pig": {"hp": 10, "speed": 0.035, "size": (0.8, 0.9), "group": "passive"},
    "wolf": {"hp": 8, "speed": 0.065, "size": (0.6, 0.85), "group": "neutral", "attack": 2},
    "zombie": {"hp": 20, "speed": 0.045, "size": (0.6, 1.9), "group": "hostile", "attack": 3, "sight": 16},
    "creeper": {"hp": 12, "speed": 0.042, "size": (0.6, 1.7), "group": "hostile", "sight": 12},
    "glowbeast": {"hp": 14, "speed": 0.05, "size": (0.9, 1.4), "group": "passive"},
}
MOB_NAMES = {"pig": "돼지", "wolf": "늑대", "zombie": "좀비", "creeper": "크리퍼", "glowbeast": "빛사슴"}
CREEPER_FUSE_RANGE = 2.6
CREEPER_FUSE_TIME = 1.5

BLACK = (0.05, 0.05, 0.05)


class Mob3D(Entity):
    def __init__(self, x, y, z, kind, hp=None):
        info = MOB_TYPES[kind]
        width, height = info["size"]
        super().__init__(x, y, z, width / 2, height)
        self.kind = kind
        self.group = info["group"]
        self.max_hp = info["hp"]
        self.hp = info["hp"] if hp is None else hp
        self.speed = info["speed"]
        self.attack = info.get("attack", 0)
        self.sight = info.get("sight", 0)
        self.floats = True
        self.facing = random.uniform(0, 360)

        self.wander_dir = (0.0, 0.0)
        self.wander_timer = random.uniform(0.5, 3.0)
        self.hurt_timer = 0.0
        self.flee_timer = 0.0
        self.flee_from = (x, z)
        self.angry_timer = 0.0      # 중립몹 분노 시간
        self.memory = 0.0           # 적대몹이 플레이어를 놓친 뒤 추적을 유지하는 시간
        self.sight_tick = random.randint(0, 9)
        self.sight_cache = False
        self.attack_cd = 0.0
        self.fuse = 0.0
        self.burn_timer = 0.0
        self.burning = False
        self.killed_by_player = False

    # --------------------------------------------------------------------------
    def sees(self, world, player, dist):
        """시선 판정은 비싸므로 10프레임마다 갱신"""
        if dist < 2.5:
            return True
        self.sight_tick -= 1
        if self.sight_tick <= 0:
            self.sight_tick = 10
            self.sight_cache = can_see(world, self.x, self.y + self.h * 0.85, self.z,
                                       player.x, player.y + Player.EYE, player.z)
        return self.sight_cache

    def wander(self, world, dt):
        self.wander_timer -= dt
        if self.wander_timer <= 0:
            self.wander_timer = random.uniform(2.0, 5.0)
            if random.random() < 0.35:
                self.wander_dir = (0.0, 0.0)
            else:
                a = random.uniform(0, 2 * math.pi)
                self.wander_dir = (math.sin(a) * self.speed * 0.6, math.cos(a) * self.speed * 0.6)
        wx, wz = self.wander_dir
        if wx or wz:
            # 절벽이나 물로 걸어 들어가지 않도록 앞쪽 지형 확인
            n = math.hypot(wx, wz)
            ax, az = self.x + wx / n * 0.8, self.z + wz / n * 0.8
            by = math.floor(self.y)
            has_floor = any(is_solid(world, math.floor(ax), by - k, math.floor(az)) for k in (0, 1, 2, 3))
            if not has_floor or block_at(world, ax, self.y - 0.5, az) == WATER:
                self.wander_dir = (0.0, 0.0)
                self.wander_timer = 0.3
        return self.wander_dir

    def update(self, world, player, env, dt):
        """AI + 물리. 게임에 넘길 이벤트 목록 [("attack", mob), ("explode", mob)] 반환"""
        events = []
        self.hurt_timer = max(0.0, self.hurt_timer - dt)
        self.flee_timer = max(0.0, self.flee_timer - dt)
        self.angry_timer = max(0.0, self.angry_timer - dt)
        self.memory = max(0.0, self.memory - dt)
        self.attack_cd = max(0.0, self.attack_cd - dt)

        dx, dz = player.x - self.x, player.z - self.z
        dist = math.hypot(dx, dz)
        alive = player.hp > 0 and not player.creative       # 크리에이티브 플레이어는 공격 대상이 아니다

        # 1) 플레이어 인식: 시야 거리 + 블록에 가려지지 않은 시선, 놓쳐도 3초간 기억
        if self.group == "hostile" and alive and dist < self.sight and self.sees(world, player, dist):
            self.memory = 3.0
        if self.group == "neutral":
            chase = alive and self.angry_timer > 0 and dist < 24
        else:
            chase = alive and self.memory > 0

        # 2) 행동 결정
        wish_x = wish_z = 0.0
        fusing = self.kind == "creeper" and chase and dist < CREEPER_FUSE_RANGE
        if self.flee_timer > 0:                      # 맞은 수동몹: 공격자 반대쪽으로 도망
            ax, az = self.x - self.flee_from[0], self.z - self.flee_from[1]
            n = math.hypot(ax, az) or 1.0
            wish_x, wish_z = ax / n * self.speed * 1.8, az / n * self.speed * 1.8
        elif fusing:                                 # 크리퍼: 멈춰서 점화
            self.fuse += dt
            if self.fuse >= CREEPER_FUSE_TIME:
                events.append(("explode", self))
                self.hp = 0
        elif chase:
            if dist > 0.6:
                wish_x, wish_z = dx / dist * self.speed, dz / dist * self.speed
            in_reach = dist < self.r + player.r + 0.7 and abs(player.y - self.y) < 1.5
            if self.attack and in_reach and self.attack_cd <= 0:
                events.append(("attack", self))
                self.attack_cd = 1.0
        else:
            wish_x, wish_z = self.wander(world, dt)
        if self.kind == "creeper" and not fusing:
            self.fuse = max(0.0, self.fuse - dt)

        if chase and self.flee_timer <= 0:
            self.facing = math.degrees(math.atan2(dx, dz))
        elif wish_x or wish_z:
            self.facing = math.degrees(math.atan2(wish_x, wish_z))

        # 3) 햇빛 아래 좀비는 탄다
        self.burning = False
        if self.kind == "zombie" and env["sun_burn"] and not self.in_water and \
                sky_exposed(world, self.x, self.y + self.h, self.z):
            self.burning = True
            self.burn_timer += dt
            if self.burn_timer >= 1.0:
                self.burn_timer = 0.0
                self.hp -= 1
                self.hurt_timer = 0.2

        # 4) 벽에 막히면 점프해서 1칸 턱을 오른다
        if self.hit_wall and self.on_ground and (wish_x or wish_z):
            self.vy = JUMP_SPEED
        damage = self.physics(world, wish_x, wish_z)
        if damage:
            self.hp -= damage
            self.hurt_timer = 0.3
        return events

    def take_hit(self, dmg, from_x, from_z, by_player):
        self.hp -= dmg
        self.hurt_timer = 0.3
        self.killed_by_player = by_player
        self.knockback(from_x, from_z, 0.3 if by_player else 0.5)
        if self.group == "passive":
            self.flee_timer = 4.0
            self.flee_from = (from_x, from_z)
        elif self.group == "neutral" and by_player:
            self.angry_timer = 20.0
        elif self.group == "hostile" and by_player:
            self.memory = 5.0

    # --------------------------------------------------------------------------
    def parts(self):
        """(x, y, z, w, h, d, 색) 목록 - 몹 기준 좌표, +z 가 앞"""
        if self.kind == "pig":
            pink, dark = (0.95, 0.68, 0.68), (0.85, 0.5, 0.55)
            legs = [(lx, 0, lz, 0.2, 0.3, 0.2, dark) for lx in (-0.3, 0.1) for lz in (-0.38, 0.2)]
            return legs + [(-0.4, 0.3, -0.45, 0.8, 0.5, 0.9, pink), (-0.3, 0.4, 0.42, 0.6, 0.5, 0.42, pink),
                           (-0.15, 0.48, 0.84, 0.3, 0.2, 0.08, dark),
                           (-0.22, 0.72, 0.84, 0.1, 0.08, 0.02, BLACK), (0.12, 0.72, 0.84, 0.1, 0.08, 0.02, BLACK)]
        if self.kind == "wolf":
            grey, light = (0.78, 0.76, 0.74), (0.9, 0.88, 0.85)
            eye = (0.9, 0.1, 0.1) if self.angry_timer > 0 else BLACK
            legs = [(lx, 0, lz, 0.14, 0.4, 0.14, grey) for lx in (-0.22, 0.08) for lz in (-0.35, 0.2)]
            return legs + [(-0.25, 0.38, -0.42, 0.5, 0.4, 0.8, grey), (-0.2, 0.45, 0.35, 0.4, 0.4, 0.35, grey),
                           (-0.1, 0.48, 0.7, 0.2, 0.16, 0.15, light),
                           (-0.18, 0.85, 0.45, 0.1, 0.12, 0.08, grey), (0.08, 0.85, 0.45, 0.1, 0.12, 0.08, grey),
                           (-0.06, 0.55, -0.7, 0.12, 0.12, 0.3, grey),
                           (-0.15, 0.7, 0.7, 0.08, 0.06, 0.02, eye), (0.07, 0.7, 0.7, 0.08, 0.06, 0.02, eye)]
        if self.kind == "glowbeast":                          # 판도라의 여섯 다리 짐승: 어두운 몸에 빛나는 줄무늬
            body, glow, eye = (0.10, 0.14, 0.24), (0.30, 0.90, 1.0), (0.85, 0.95, 1.0)
            legs = [(lx, 0, lz, 0.12, 0.55, 0.12, body) for lx in (-0.3, 0.18) for lz in (-0.45, -0.05, 0.35)]
            stripes = [(-0.31, 0.72 + k * 0.1, -0.5 + k * 0.05, 0.62, 0.04, 0.08, glow, True) for k in range(3)]
            return legs + stripes + [
                (-0.3, 0.55, -0.6, 0.6, 0.45, 1.15, body), (-0.18, 0.75, 0.55, 0.36, 0.34, 0.4, body),
                (-0.02, 1.0, -0.55, 0.04, 0.04, 1.05, glow, True),                       # 등줄기
                (-0.2, 1.09, 0.62, 0.05, 0.3, 0.05, glow, True), (0.15, 1.09, 0.62, 0.05, 0.3, 0.05, glow, True),
                (-0.27, 1.35, 0.6, 0.12, 0.04, 0.05, glow, True), (0.15, 1.35, 0.6, 0.12, 0.04, 0.05, glow, True),
                (-0.17, 0.92, 0.95, 0.08, 0.06, 0.02, eye, True), (0.09, 0.92, 0.95, 0.08, 0.06, 0.02, eye, True)]
        if self.kind == "zombie":
            skin, shirt, pants = (0.3, 0.6, 0.3), (0.15, 0.55, 0.6), (0.25, 0.25, 0.6)
            return [(-0.25, 0, -0.12, 0.24, 0.75, 0.24, pants), (0.01, 0, -0.12, 0.24, 0.75, 0.24, pants),
                    (-0.25, 0.75, -0.13, 0.5, 0.7, 0.26, shirt), (-0.25, 1.45, -0.25, 0.5, 0.45, 0.5, skin),
                    (-0.37, 1.27, -0.06, 0.12, 0.12, 0.7, skin), (0.25, 1.27, -0.06, 0.12, 0.12, 0.7, skin),
                    (-0.15, 1.65, 0.25, 0.1, 0.06, 0.02, BLACK), (0.05, 1.65, 0.25, 0.1, 0.06, 0.02, BLACK)]
        green = (0.2, 0.75, 0.25)
        if self.fuse > 0 and int(self.fuse * 8) % 2 == 0:      # 점화 중 깜빡임
            green = (0.95, 0.95, 0.95)
        legs = [(lx, 0, lz, 0.2, 0.35, 0.18, green) for lx in (-0.25, 0.05) for lz in (-0.3, 0.12)]
        return legs + [(-0.22, 0.35, -0.14, 0.44, 0.9, 0.28, green), (-0.25, 1.25, -0.25, 0.5, 0.45, 0.5, green),
                       (-0.17, 1.5, 0.25, 0.12, 0.1, 0.02, BLACK), (0.05, 1.5, 0.25, 0.12, 0.1, 0.02, BLACK),
                       (-0.06, 1.32, 0.25, 0.12, 0.16, 0.02, BLACK)]

    def draw(self):
        glPushMatrix()
        glTranslatef(self.x, self.view_y, self.z)
        glRotatef(self.facing, 0.0, 1.0, 0.0)
        if self.kind == "creeper" and self.fuse > 0:
            s = 1.0 + self.fuse * 0.08
            glScalef(s, s, s)
        hurt = self.hurt_timer > 0
        light = getattr(self, "light_cache", None) or (1.0, 0.0)
        parts = self.parts()
        key = (hurt, light[:2], parts)
        if getattr(self, "mesh_key", None) != key:            # 모습·빛이 바뀔 때만 정점 배열을 다시 만든다
            lit, glowing = (light[0], light[1], 0.0), (1.0, 1.0, MAT_GLOW)
            data = array("f")                                 # 몸 전체를 배열 하나로 모아 한 번에 그린다 (최적화)
            for x, y, z, w, h, d, col, *glow in parts:
                if hurt:
                    col = (min(1.0, col[0] * 0.5 + 0.6), col[1] * 0.4, col[2] * 0.4)
                add_box(data, x, y, z, w, h, d, col, glowing if glow else lit)    # 빛나는 부분은 스스로 빛나는 재질
            self.mesh_key, self.mesh = key, data
        draw_client_arrays(self.mesh)
        glPopMatrix()


# ==============================================================================
# 4. 떨어지는 블록 (모래, 원목, 선인장)
# ==============================================================================
class FallingBlock(Entity):
    def __init__(self, bx, by, bz, block_id):
        super().__init__(bx + 0.5, by, bz + 0.5, 0.45, 0.95)
        self.can_step = False
        self.block_id = block_id
        self.age = 0

    def update(self, world):
        """착지하면 True"""
        self.physics(world, 0.0, 0.0)
        self.age += 1
        return self.on_ground and self.age > 1

    def draw(self):
        top, side = block_face_colors(self.block_id)
        draw_box(self.x - 0.5, self.y, self.z - 0.5, 1.0, 1.0, 1.0, side, top)


class PrimedTNT(Entity):
    """점화된 TNT: 중력을 받으며 깜빡이다가 fuse 초 뒤에 터진다"""

    def __init__(self, bx, by, bz, fuse=3.0):
        super().__init__(bx + 0.5, by, bz + 0.5, 0.45, 0.95)
        self.can_step = False
        self.fuse = fuse
        self.vy = 0.12

    def update(self, world, dt):
        """터질 때가 되면 True"""
        self.physics(world, 0.0, 0.0)
        self.fuse -= dt
        return self.fuse <= 0

    def draw(self):
        flash = int(self.fuse * 6) % 2 == 0
        top, side = block_face_colors(TNT)
        if flash:
            top = side = (1.0, 1.0, 1.0)
        s = 1.0 + max(0.0, 0.6 - self.fuse) * 0.25                 # 터지기 직전 부풀어 오름
        draw_box(self.x - 0.5 * s, self.y, self.z - 0.5 * s, s, s, s, side, top)


# ==============================================================================
# 5. 파티클
# ==============================================================================
class Particle3D:
    def __init__(self, x, y, z, color, spread=0.08):
        self.x, self.y, self.z = x, y, z
        self.color = color
        self.vx = random.uniform(-spread, spread)
        self.vy = random.uniform(0.04, 0.15)
        self.vz = random.uniform(-spread, spread)
        self.life = random.randint(20, 35)

    def update(self):
        self.x += self.vx
        self.y += self.vy
        self.z += self.vz
        self.vy -= 0.007
        self.life -= 1

    def emit(self, rx, rz):
        """카메라를 향한 사각형 꼭짓점 (glBegin(GL_QUADS) 안에서 호출)"""
        s = 0.06
        glColor3f(*self.color)
        glVertex3f(self.x - rx * s, self.y - s, self.z - rz * s)
        glVertex3f(self.x + rx * s, self.y - s, self.z + rz * s)
        glVertex3f(self.x + rx * s, self.y + s, self.z + rz * s)
        glVertex3f(self.x - rx * s, self.y + s, self.z - rz * s)


class Wisp:
    """떠다니는 빛 정령 (반딧불이·영혼 씨앗): 빛나는 식물 근처를 천천히 맴돌다 사라진다"""

    def __init__(self, x, y, z, color):
        self.ox, self.oy, self.oz = x, y, z
        self.x, self.y, self.z = x, y, z
        self.color = color
        self.phase = random.uniform(0, 2 * math.pi)
        self.speed = random.uniform(0.3, 0.8)
        self.radius = random.uniform(0.6, 2.4)
        self.rise = random.uniform(-0.05, 0.12)       # 영혼 씨앗처럼 아주 천천히 떠오르기도 한다
        self.life = self.max_life = random.uniform(12, 30)
        self.size = random.uniform(0.035, 0.07)

    def update(self, dt):
        self.phase += dt * self.speed
        self.life -= dt
        self.oy += self.rise * dt
        p = self.phase
        self.x = self.ox + math.cos(p) * self.radius + math.sin(p * 2.3) * 0.25
        self.z = self.oz + math.sin(p * 0.8) * self.radius
        self.y = self.oy + math.sin(p * 1.7) * 0.45 + math.sin(p * 3.1) * 0.12

    def emit(self, halo):
        """둥근 점 하나 (glBegin(GL_POINTS) 안에서 호출). halo 면 흐릿하게 퍼지는 빛무리"""
        fade = min(1.0, self.life / 3.0, (self.max_life - self.life) / 2.0)
        twinkle = (0.65 + 0.35 * math.sin(self.phase * 7.0)) * fade
        r, g, b = self.color
        if halo:
            glColor4f(r, g, b, twinkle * 0.25)
        else:
            glColor4f(min(1.0, r + 0.35), min(1.0, g + 0.35), min(1.0, b + 0.35), twinkle)
        glVertex3f(self.x, self.y, self.z)


def add_box(out, x, y, z, w, h, d, col, light):
    """직육면체의 사각형 6개를 정점 배열(위치, 색, 법선, 빛)에 덧붙인다"""
    r, g, b = col
    sky, block, mat = light
    for (nx, ny, nz), _, _, verts in FACES:
        for vx, vy, vz in verts:
            out.extend((x + vx * w, y + vy * h, z + vz * d, r, g, b, nx, ny, nz, sky, block, mat))


def draw_box(x, y, z, w, h, d, col, top_col=None):
    """직육면체. 면마다 법선을 줘서 빛 셰이더가 방향에 따라 명암을 넣는다"""
    glBegin(GL_QUADS)
    glColor3f(*(top_col or col))
    glNormal3f(0, 1, 0)
    glVertex3f(x, y + h, z); glVertex3f(x + w, y + h, z); glVertex3f(x + w, y + h, z + d); glVertex3f(x, y + h, z + d)
    glColor3f(*col)
    glNormal3f(0, 0, 1)
    glVertex3f(x, y, z + d); glVertex3f(x + w, y, z + d); glVertex3f(x + w, y + h, z + d); glVertex3f(x, y + h, z + d)
    glNormal3f(0, 0, -1)
    glVertex3f(x, y, z); glVertex3f(x, y + h, z); glVertex3f(x + w, y + h, z); glVertex3f(x + w, y, z)
    glNormal3f(-1, 0, 0)
    glVertex3f(x, y, z); glVertex3f(x, y, z + d); glVertex3f(x, y + h, z + d); glVertex3f(x, y + h, z)
    glNormal3f(1, 0, 0)
    glVertex3f(x + w, y, z); glVertex3f(x + w, y + h, z); glVertex3f(x + w, y + h, z + d); glVertex3f(x + w, y, z + d)
    glNormal3f(0, -1, 0)
    glVertex3f(x, y, z); glVertex3f(x + w, y, z); glVertex3f(x + w, y, z + d); glVertex3f(x, y, z + d)
    glEnd()
