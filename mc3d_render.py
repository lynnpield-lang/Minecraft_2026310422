"""3D 마인크래프트 - 그래픽 효과 모듈 (셰이더팩 느낌)

햇빛 그림자(섀도 맵), 셰이더로 그린 하늘·뭉게구름·해·달·별,
화면 후처리(블룸, 햇살 갓레이, 톤 매핑, 색 보정, 비네트)를 담당한다.
그래픽 환경이 지원하지 않으면 enabled=False 가 되고, 게임은 예전 방식으로 그린다.
"""
import math

import OpenGL
OpenGL.ERROR_CHECKING = False
from OpenGL.GL import *

GL_RGBA16F = 0x881A                  # 밝기 1 을 넘는 색(HDR)을 담는 텍스처 형식
SHADOW_SIZE = 2048                   # 그림자 지도 해상도
SHADOW_RADIUS = 80.0                 # 플레이어 주변 이 거리(칸)까지 그림자를 그린다
FOV_Y = 70.0                         # 세로 시야각 (게임의 gluPerspective 와 같아야 한다)


# ==============================================================================
# 1. 행렬 도우미 (행 우선 4×4, 길이 16 리스트)
# ==============================================================================
def mat_mul(a, b):
    return [sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4)) for r in range(4) for c in range(4)]


def _norm(v):
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
    return v[0] / n, v[1] / n, v[2] / n


def _cross(a, b):
    return a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def camera_basis(yaw, pitch):
    """카메라의 (오른쪽, 위, 앞) 월드 방향 - 게임의 glRotatef(-pitch, x) · glRotatef(yaw, y) 와 같은 방향"""
    ry, rp = math.radians(yaw), math.radians(pitch)
    fwd = (math.sin(ry) * math.cos(rp), math.sin(rp), -math.cos(ry) * math.cos(rp))
    right = (math.cos(ry), 0.0, math.sin(ry))
    up = (-math.sin(ry) * math.sin(rp), math.cos(rp), math.cos(ry) * math.sin(rp))
    return right, up, fwd


def eye_to_world(yaw, pitch, cam):
    """눈 좌표 → 월드 좌표 행렬 (카메라 보기 행렬의 역행렬)"""
    r, u, f = camera_basis(yaw, pitch)
    return [r[0], u[0], -f[0], cam[0],
            r[1], u[1], -f[1], cam[1],
            r[2], u[2], -f[2], cam[2],
            0.0, 0.0, 0.0, 1.0]


def _transpose(m):
    return [m[c * 4 + r] for r in range(4) for c in range(4)]


# ==============================================================================
# 2. GL 도우미
# ==============================================================================
def _program(vs, fs):
    from OpenGL.GL import shaders
    return shaders.compileProgram(shaders.compileShader(vs, GL_VERTEX_SHADER),
                                  shaders.compileShader(fs, GL_FRAGMENT_SHADER), validate=False)


def _texture(w, h, internal, fmt, typ, filt=GL_LINEAR):
    tex = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, tex)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, filt)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, filt)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
    glTexImage2D(GL_TEXTURE_2D, 0, internal, w, h, 0, fmt, typ, None)
    glBindTexture(GL_TEXTURE_2D, 0)
    return tex


def _framebuffer(color=None, depth=None):
    fbo = glGenFramebuffers(1)
    glBindFramebuffer(GL_FRAMEBUFFER, fbo)
    if color:
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, color, 0)
    else:
        glDrawBuffer(GL_NONE)
        glReadBuffer(GL_NONE)
    if depth:
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_TEXTURE_2D, depth, 0)
    ok = glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE
    glBindFramebuffer(GL_FRAMEBUFFER, 0)
    if not ok:
        raise RuntimeError("framebuffer incomplete")
    return fbo


def _quad():
    """화면 전체를 덮는 사각형 (텍스처 좌표 0~1)"""
    glBegin(GL_QUADS)
    for x, y in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        glTexCoord2f((x + 1) * 0.5, (y + 1) * 0.5)
        glVertex3f(x, y, 0.0)
    glEnd()


QUAD_VS = """
#version 120
varying vec2 v_uv;
void main() {
    v_uv = gl_MultiTexCoord0.xy;
    gl_Position = vec4(gl_Vertex.xy, 0.0, 1.0);
}
"""

# ==============================================================================
# 3. 그림자 지도: 해 쪽에서 내려다본 깊이를 그려 두고, 지형 셰이더가 그늘인지 비교한다
# ==============================================================================
SHADOW_VS = """
#version 120
uniform float u_time;
void main() {
    vec4 pos = gl_Vertex;
    float mat = gl_MultiTexCoord0.z;
    if (mat > 0.01 && mat < 1.5) {                       // 지형 셰이더와 같이 풀·잎을 흔든다 (그림자가 어긋나지 않게)
        float t = u_time * 1.6 + pos.x * 0.35 + pos.z * 0.27;
        pos.x += sin(t) * 0.07 * mat;
        pos.z += cos(t * 0.8 + 1.3) * 0.05 * mat;
    }
    if (mat < -0.5 || mat > 3.5) pos = vec4(0.0, -99999.0, 0.0, 1.0);   // 물·먼 풍경은 그림자를 만들지 않는다
    gl_Position = gl_ModelViewProjectionMatrix * pos;
}
"""
SHADOW_FS = """
#version 120
void main() { gl_FragColor = vec4(1.0); }
"""


class ShadowMap:
    def __init__(self):
        self.depth = _texture(SHADOW_SIZE, SHADOW_SIZE, GL_DEPTH_COMPONENT24, GL_DEPTH_COMPONENT, GL_FLOAT)
        glBindTexture(GL_TEXTURE_2D, self.depth)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_COMPARE_MODE, GL_COMPARE_R_TO_TEXTURE)   # 하드웨어 비교 + 부드러운 경계
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_COMPARE_FUNC, GL_LEQUAL)
        glBindTexture(GL_TEXTURE_2D, 0)
        self.fbo = _framebuffer(depth=self.depth)
        self.program = _program(SHADOW_VS, SHADOW_FS)
        self.loc_time = glGetUniformLocation(self.program, "u_time")
        self.light = None                 # 마지막으로 그린 그림자 지도의 (투영 · 보기) 행렬

    def begin(self, sun_dir, center, time_s):
        """해 방향에서 center 주변을 내려다보는 직교 투영으로 깊이만 그리기 시작한다"""
        f = _norm((-sun_dir[0], -sun_dir[1], -sun_dir[2]))       # 해에서 땅을 보는 방향
        r = _norm(_cross(f, (0.0, 0.0, 1.0)))
        u = _cross(r, f)
        view = [r[0], r[1], r[2], 0.0,
                u[0], u[1], u[2], 0.0,
                -f[0], -f[1], -f[2], 0.0,
                0.0, 0.0, 0.0, 1.0]
        # 중심을 그림자 텍셀 격자에 맞춰 움직여야 걸을 때 그림자 경계가 떨리지 않는다
        texel = 2 * SHADOW_RADIUS / SHADOW_SIZE
        cx, cy, cz = _dot(center, r), _dot(center, u), _dot(center, (-f[0], -f[1], -f[2]))
        cx, cy = round(cx / texel) * texel, round(cy / texel) * texel
        R, depth = SHADOW_RADIUS, 420.0
        l, rr, b, t, n, fa = cx - R, cx + R, cy - R, cy + R, -cz - depth, -cz + depth
        proj = [2 / (rr - l), 0, 0, -(rr + l) / (rr - l),
                0, 2 / (t - b), 0, -(t + b) / (t - b),
                0, 0, -2 / (fa - n), -(fa + n) / (fa - n),
                0, 0, 0, 1]
        self.light = mat_mul(proj, view)
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
        glViewport(0, 0, SHADOW_SIZE, SHADOW_SIZE)
        glClear(GL_DEPTH_BUFFER_BIT)
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadMatrixf(_transpose(proj))
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadMatrixf(_transpose(view))
        glUseProgram(self.program)
        glUniform1f(self.loc_time, time_s)
        glEnable(GL_POLYGON_OFFSET_FILL)
        glPolygonOffset(1.1, 3.0)

    def end(self, screen_w, screen_h):
        glDisable(GL_POLYGON_OFFSET_FILL)
        glUseProgram(0)
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()
        glMatrixMode(GL_MODELVIEW)
        glPopMatrix()
        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        glViewport(0, 0, screen_w, screen_h)

    def eye_matrix(self, inv_view):
        """눈 좌표 → 그림자 지도 텍스처 좌표(0~1) 행렬"""
        bias = [0.5, 0, 0, 0.5,
                0, 0.5, 0, 0.5,
                0, 0, 0.5, 0.5,
                0, 0, 0, 1]
        return mat_mul(bias, mat_mul(self.light, inv_view))


# ==============================================================================
# 4. 하늘: 화면 전체에 시선 방향마다 하늘색, 해·달, 별, 흘러가는 뭉게구름을 계산한다
# ==============================================================================
SKY_FS = """
#version 120
varying vec2 v_uv;
uniform vec3 u_right, u_up, u_fwd;
uniform vec2 u_tan;              // 가로·세로 시야각 절반의 tan
uniform vec3 u_sun;              // 해 방향 (월드)
uniform vec3 u_horizon, u_zenith, u_sun_color;
uniform float u_time, u_cover, u_night, u_cam_y, u_cloud_y, u_day;

float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), f.x), f.y);
}
float fbm(vec2 p) {
    float v = 0.0, a = 0.5;
    for (int i = 0; i < 5; i++) { v += a * noise(p); p = p * 2.03 + vec2(17.3, 9.1); a *= 0.5; }
    return v;
}

void main() {
    vec2 ndc = v_uv * 2.0 - 1.0;
    vec3 dir = normalize(u_fwd + ndc.x * u_tan.x * u_right + ndc.y * u_tan.y * u_up);
    float h = dir.y;
    vec3 sky = mix(u_horizon, u_zenith, pow(clamp(h, 0.0, 1.0), 0.5));
    if (h < 0.0) sky = u_horizon * (1.0 + h * 0.35);                  // 지평선 아래는 옅은 안개
    float sd = max(dot(dir, u_sun), 0.0);
    sky += u_sun_color * (pow(sd, 6.0) * 0.18 + pow(sd, 48.0) * 0.35);   // 해 주변 빛무리
    float md = max(dot(dir, -u_sun), 0.0);

    // 별 (밤)
    if (u_night > 0.02 && h > 0.0) {
        vec3 c = floor(dir * 260.0);
        float s = hash(c.xy + c.z * 37.0);
        sky += vec3(step(0.9975, s) * (0.5 + 0.5 * hash(c.zy))) * u_night * h;
    }
    // 해·달 원반 (밝기 1을 넘겨 블룸이 번지게)
    sky += u_sun_color * smoothstep(0.99955, 0.9997, sd) * 12.0 * (1.0 - u_night);
    sky += vec3(0.85, 0.9, 1.0) * smoothstep(0.99965, 0.9998, md) * 1.6 * u_night;

    // 뭉게구름: 구름층 높이의 평면에 노이즈를 그리고, 해 쪽으로 조금 옮긴 노이즈와 비교해 그늘을 넣는다
    if (h > 0.015) {
        float t = (u_cloud_y - u_cam_y) / h;
        vec2 p = (dir.xz * t) * 0.0009 + vec2(u_time * 0.004, u_time * 0.0015);
        vec2 warp = vec2(fbm(p * 1.7 + 3.1), fbm(p * 1.7 - 5.3));        // 비틀어서 몽글몽글한 뭉게구름 모양으로
        float d = fbm(p + warp * 0.45);
        float c = smoothstep(1.0 - u_cover, 1.0 - u_cover + 0.2, d);
        if (c > 0.001) {
            float d2 = fbm(p + warp * 0.45 + u_sun.xz * 0.05);
            float lit = clamp(0.8 + (d - d2) * 4.0, 0.5, 1.35);           // 해 쪽은 밝고 반대쪽 아랫면은 그늘
            vec3 base = vec3(1.0, 0.99, 0.97) * (0.2 + 1.2 * u_day) * mix(0.78, 1.0, smoothstep(0.0, 0.25, d - (1.0 - u_cover)));
            vec3 cloud = base * lit + u_sun_color * pow(sd, 4.0) * 0.45;
            float fade = exp(-t * 0.00018);
            sky = mix(sky, cloud, c * fade);
        }
    }
    gl_FragColor = vec4(sky, 1.0);
}
"""

# ==============================================================================
# 5. 후처리: 밝은 곳 번짐(블룸), 햇살(갓레이), 톤 매핑, 색 보정, 비네트
# ==============================================================================
BRIGHT_FS = """
#version 120
varying vec2 v_uv;
uniform sampler2D u_tex;
uniform vec2 u_px;
void main() {
    vec3 c = (texture2D(u_tex, v_uv + vec2(-u_px.x, -u_px.y)).rgb + texture2D(u_tex, v_uv + vec2(u_px.x, -u_px.y)).rgb
            + texture2D(u_tex, v_uv + vec2(-u_px.x, u_px.y)).rgb + texture2D(u_tex, v_uv + vec2(u_px.x, u_px.y)).rgb) * 0.25;
    float l = dot(c, vec3(0.299, 0.587, 0.114));
    gl_FragColor = vec4(c * smoothstep(0.85, 1.8, l), 1.0);
}
"""
BLUR_FS = """
#version 120
varying vec2 v_uv;
uniform sampler2D u_tex;
uniform vec2 u_dir;
void main() {
    vec3 c = texture2D(u_tex, v_uv).rgb * 0.227;
    c += (texture2D(u_tex, v_uv + u_dir * 1.385).rgb + texture2D(u_tex, v_uv - u_dir * 1.385).rgb) * 0.316;
    c += (texture2D(u_tex, v_uv + u_dir * 3.231).rgb + texture2D(u_tex, v_uv - u_dir * 3.231).rgb) * 0.070;
    gl_FragColor = vec4(c, 1.0);
}
"""
RAYS_FS = """
#version 120
varying vec2 v_uv;
uniform sampler2D u_tex;
uniform sampler2D u_depth;
uniform vec2 u_sun;
void main() {
    vec2 delta = (v_uv - u_sun) / 32.0;
    vec2 p = v_uv;
    float decay = 1.0, sum = 0.0;
    for (int i = 0; i < 32; i++) {
        p -= delta;
        float sky = step(0.99999, texture2D(u_depth, p).r);              // 하늘이 보이는 곳에서만 빛이 새어 나온다
        sum += sky * min(dot(texture2D(u_tex, p).rgb, vec3(0.33)), 3.0) * decay;
        decay *= 0.955;
    }
    gl_FragColor = vec4(vec3(sum / 32.0), 1.0);
}
"""
COMPOSITE_FS = """
#version 120
varying vec2 v_uv;
uniform sampler2D u_scene;
uniform sampler2D u_bloom;
uniform sampler2D u_rays;
uniform float u_exposure, u_rays_on;
uniform vec3 u_ray_color;
uniform vec2 u_sun;
void main() {
    vec3 c = texture2D(u_scene, v_uv).rgb;
    c += texture2D(u_bloom, v_uv).rgb * 0.22;
    float near = 1.0 - smoothstep(0.0, 0.9, length((v_uv - u_sun) * vec2(1.6, 1.0)));
    c += u_ray_color * texture2D(u_rays, v_uv).r * u_rays_on * (0.35 + 0.65 * near);
    c *= u_exposure;
    c = (c * (2.51 * c + 0.03)) / (c * (2.43 * c + 0.59) + 0.14);       // ACES 톤 매핑: 밝은 곳도 하얗게 날지 않는다
    float l = dot(c, vec3(0.299, 0.587, 0.114));
    c = mix(vec3(l), c, 1.12);                                           // 살짝 선명한 색
    c = c * vec3(1.03, 1.0, 0.96) + vec3(0.006, 0.004, 0.0);             // 따뜻한 색감
    vec2 v = v_uv - 0.5;
    c *= 1.0 - 0.22 * pow(dot(v, v) * 2.2, 1.3);                         // 비네트
    gl_FragColor = vec4(clamp(c, 0.0, 1.0), 1.0);
}
"""


class Graphics:
    """그림자 + 하늘 + 후처리. 지원하지 않는 환경이면 enabled=False"""

    def __init__(self, width, height):
        self.w, self.h = width, height
        self.enabled = False
        try:
            self._setup()
            self.enabled = True
        except Exception as e:
            print("고급 그래픽 효과를 쓸 수 없어 기본 렌더링으로 그립니다:", e)

    def _setup(self):
        w, h = self.w, self.h
        self.shadow = ShadowMap()
        self.scene_color = _texture(w, h, GL_RGBA16F, GL_RGBA, GL_FLOAT)
        self.scene_depth = _texture(w, h, GL_DEPTH_COMPONENT24, GL_DEPTH_COMPONENT, GL_FLOAT, GL_NEAREST)
        self.scene_fbo = _framebuffer(self.scene_color, self.scene_depth)
        self.qw, self.qh = w // 4, h // 4
        self.bloom = [_texture(self.qw, self.qh, GL_RGBA16F, GL_RGBA, GL_FLOAT) for _ in range(2)]
        self.bloom_fbo = [_framebuffer(t) for t in self.bloom]
        self.rays = _texture(self.qw, self.qh, GL_RGBA16F, GL_RGBA, GL_FLOAT)
        self.rays_fbo = _framebuffer(self.rays)
        self.p_sky = _program(QUAD_VS, SKY_FS)
        self.p_bright = _program(QUAD_VS, BRIGHT_FS)
        self.p_blur = _program(QUAD_VS, BLUR_FS)
        self.p_rays = _program(QUAD_VS, RAYS_FS)
        self.p_comp = _program(QUAD_VS, COMPOSITE_FS)
        self.loc = {}
        for prog in (self.p_sky, self.p_bright, self.p_blur, self.p_rays, self.p_comp):
            glUseProgram(prog)
            for name, unit in (("u_tex", 0), ("u_scene", 0), ("u_bloom", 1), ("u_rays", 2), ("u_depth", 1)):
                loc = glGetUniformLocation(prog, name)
                if loc >= 0:
                    glUniform1i(loc, unit)
        glUseProgram(0)

    def _uniform(self, prog, name, value):
        key = (prog, name)
        loc = self.loc.get(key)
        if loc is None:
            loc = self.loc[key] = glGetUniformLocation(prog, name)
        if loc < 0:
            return
        if isinstance(value, (int, float)):
            glUniform1f(loc, value)
        elif len(value) == 2:
            glUniform2f(loc, *value)
        else:
            glUniform3f(loc, *value)

    # ---- 장면 ---------------------------------------------------------------
    def begin_scene(self):
        glBindFramebuffer(GL_FRAMEBUFFER, self.scene_fbo)
        glViewport(0, 0, self.w, self.h)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

    def draw_sky(self, yaw, pitch, cam_y, sun, horizon, zenith, sun_color, time_s, cover, night, day, cloud_y):
        r, u, f = camera_basis(yaw, pitch)
        ty = math.tan(math.radians(FOV_Y / 2))
        p = self.p_sky
        glUseProgram(p)
        for name, value in (("u_right", r), ("u_up", u), ("u_fwd", f), ("u_tan", (ty * self.w / self.h, ty)),
                            ("u_sun", sun), ("u_horizon", horizon), ("u_zenith", zenith), ("u_sun_color", sun_color),
                            ("u_time", time_s), ("u_cover", cover), ("u_night", night), ("u_cam_y", cam_y),
                            ("u_cloud_y", cloud_y), ("u_day", day)):
            self._uniform(p, name, value)
        glDisable(GL_DEPTH_TEST)
        glDepthMask(GL_FALSE)
        _quad()
        glDepthMask(GL_TRUE)
        glEnable(GL_DEPTH_TEST)
        glUseProgram(0)

    def sun_screen(self, yaw, pitch, sun):
        """해의 화면 위치 (0~1) 와 화면 앞쪽에 있는 정도"""
        r, u, f = camera_basis(yaw, pitch)
        ez = _dot(sun, f)
        if ez <= 0.05:
            return (0.5, 2.0), 0.0
        ty = math.tan(math.radians(FOV_Y / 2))
        x = _dot(sun, r) / ez / (ty * self.w / self.h)
        y = _dot(sun, u) / ez / ty
        return ((x + 1) * 0.5, (y + 1) * 0.5), min(1.0, ez * 2.0)

    def finish(self, exposure, sun_uv, rays_on, ray_color):
        """장면 → (블룸, 햇살) → 톤 매핑해서 화면으로"""
        glDisable(GL_DEPTH_TEST)
        glDepthMask(GL_FALSE)
        glDisable(GL_BLEND)
        glActiveTexture(GL_TEXTURE0)
        # 블룸: 1/4 크기로 밝은 곳만 → 가로 흐림 → 세로 흐림
        glViewport(0, 0, self.qw, self.qh)
        glBindFramebuffer(GL_FRAMEBUFFER, self.bloom_fbo[0])
        glUseProgram(self.p_bright)
        self._uniform(self.p_bright, "u_px", (1.0 / self.w, 1.0 / self.h))
        glBindTexture(GL_TEXTURE_2D, self.scene_color)
        _quad()
        glUseProgram(self.p_blur)
        for src, dst, d in ((0, 1, (1.5 / self.qw, 0.0)), (1, 0, (0.0, 1.5 / self.qh)),
                            (0, 1, (3.0 / self.qw, 0.0)), (1, 0, (0.0, 3.0 / self.qh))):
            glBindFramebuffer(GL_FRAMEBUFFER, self.bloom_fbo[dst])
            self._uniform(self.p_blur, "u_dir", d)
            glBindTexture(GL_TEXTURE_2D, self.bloom[src])
            _quad()
        # 햇살: 해 쪽으로 하늘 밝기를 모은다
        if rays_on > 0.01:
            glBindFramebuffer(GL_FRAMEBUFFER, self.rays_fbo)
            glUseProgram(self.p_rays)
            self._uniform(self.p_rays, "u_sun", sun_uv)
            glActiveTexture(GL_TEXTURE1)
            glBindTexture(GL_TEXTURE_2D, self.scene_depth)
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, self.scene_color)
            _quad()
        # 합치기
        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        glViewport(0, 0, self.w, self.h)
        glUseProgram(self.p_comp)
        for name, value in (("u_exposure", exposure), ("u_rays_on", rays_on), ("u_ray_color", ray_color),
                            ("u_sun", sun_uv)):
            self._uniform(self.p_comp, name, value)
        glActiveTexture(GL_TEXTURE2)
        glBindTexture(GL_TEXTURE_2D, self.rays)
        glActiveTexture(GL_TEXTURE1)
        glBindTexture(GL_TEXTURE_2D, self.bloom[0])
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self.scene_color)
        _quad()
        glUseProgram(0)
        for unit in (GL_TEXTURE2, GL_TEXTURE1, GL_TEXTURE0):
            glActiveTexture(unit)
            glBindTexture(GL_TEXTURE_2D, 0)
        glDepthMask(GL_TRUE)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)

    def bind_shadow(self, unit=GL_TEXTURE3):
        """지형 셰이더가 쓸 그림자 지도를 텍스처 3번에 둔다"""
        glActiveTexture(unit)
        glBindTexture(GL_TEXTURE_2D, self.shadow.depth)
        glActiveTexture(GL_TEXTURE0)
