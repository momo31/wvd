# -*- coding: utf-8 -*-
"""smart_disarm 수정 검증 하니스 (2026-07-15 적중률+위생 수정분).

SmartDisarm 의 주입 구조(cap/press/now/is_done)를 이용해 실제 run() 루프를
합성 프레임(삼각파 커서 + 막대/안전구간 + ROI 패턴)으로 구동하고,
ChallengeCheck 경로까지 도달시켜 아래 4개 수정의 동작을 검증한다.

  1. 자가 학습 템플릿 연쇄 저장 방지(elif 체인) - 실패 탭 1회에 템플릿 1장만 저장
  2. sim>=0.92 필터가 is_failed 도 해제 - 무변화 화면에서의 +0.05 오보정 차단
  3. +0.05 강제 상향은 meas(정지위치 역산) 실패 탭에만 - 이중 보정 차단
  4. smallgame 경로 절대화(_SMALLGAME_DIR) - 하니스는 이 변수를 임시 폴더로 패치
  5. (26-07-16) 무측정 실패 보정 3중 제한 - 고정 +0.05 를
     (1) 측정 공백 연속일 때만 (2) 방향 근거(press RTT 이상/잔차 EWMA) 있을 때만
     (3) 축소 폭 ±blind_fail_step(0.025) 으로만 개입하도록 교체

사용법 (저장소 루트에서):
  python tools/test_smart_disarm_fixes.py
      현재 작업트리 코드로 S1~S4 검증.
  python tools/test_smart_disarm_fixes.py --old-ref 95b47d2
      수정 전 코드(git ref)를 같은 시나리오로 실행해 버그 재현까지 A/B 확인.
      (수정 1~3 재현은 95b47d2, 수정 5 재현은 14ad773~b6572f6 도 동일하게 유효)

시나리오:
  S1 genuine+meas   : 탭 후 ROI 실제 변화 + 탭 직후 커서 검출(meas 성공)
  S2 brightness     : 탭 후 ROI 밝기 +12 (diff>=3, sim>=0.92) - 무변화로 간주해야 함
  S3 genuine+nomeas : ROI 변화 + 탭 직후 커서 미검출(meas 실패), 세션 첫 탭
                      - 신코드: 공백 연속 아님 → 맹목 보정 생략 / 구코드: +0.05
  S4a~d             : 같은 상자 내 측정 공백 연속 상태의 무측정 실패
                      a) 잔차 EWMA +60px → +0.025  b) -60px → -0.025
                      c) 근거 없음(+10px) → 생략   d) press RTT 이상 → +0.025
  S5a~d (26-07-16)  : 2프레임 정지 실측 + 실패 확정 재조준 (DecelWorld: 감속-정지 +
                      라운드 재도전 물리)
                      a) 감속 0.35s 개체(모델 1.0 과 편차): 탭1 미스 → 감속시간
                         역산/정지 실측 → 재조준 → 탭2 명중 (동일 조준 반복 미스 제거)
                      b) 감속 1.0s 개체(모델 일치): 탭1 명중, Ts 역산 ≈1.0, 재조준
                         미발동 (회귀 없음)
                      c) 실패 후 커서 조기 리셋: 후프레임의 신규 커서 → 역행/해 없음
                         → 측정 폐기 (오염 방어)
                      d) 성공 탭 + ChallengeCheck diff 오탐: 실측 err≈0 → 재조준
                         자기제한 (오탐 무해화)
  S5e               : 반사 가드 유닛 — 감속 중 끝점 반사가 낄 수 있는 주입(벽거리 <
                      최대주행)은 허구 Ts 해를 막기 위해 측정 폐기, 반사 불가능 확정
                      주입은 감속시간(1.0s/0.3s) 정확 역산 유지 (_measure_after_tap
                      직접 구동)

의존: numpy, opencv-python (requirements.txt 와 동일).
실행 시간: 시나리오당 약 5~10초 (탭 타이밍을 실시간으로 시뮬레이션).
"""
import argparse
import glob
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np
import cv2

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(REPO, "src")

SPAN = (16, 896)          # 막대 x 범위
SAFES = [(150, 300), (600, 760)]
BAR_Y = (40, 140)         # 막대 y 범위 (detect 영역 0:180 내부, ROI 170:250 과 비겹침)
V = 400.0                 # 커서 속도(px/s)


def make_pattern(kind):
    """도전 횟수 ROI(80x130) 패턴. T/P0/P1 은 상호 상관 ~0, P0b 는 P0+12(상관 1.0)."""
    p = np.zeros((80, 130, 3), np.uint8)
    if kind == "T":       # 세로 줄무늬 (진입 프레임 = 4회 템플릿으로 저장됨)
        p[:, ::2] = (200, 50, 40)
    elif kind == "P0":    # 가로 줄무늬 (탭 전 상태)
        p[::2, :] = (40, 200, 60)
    elif kind == "P0b":   # P0 + 밝기 12 (absdiff=12, TM_CCOEFF_NORMED=1.0)
        p = np.clip(make_pattern("P0").astype(np.int16) + 12, 0, 255).astype(np.uint8)
    elif kind == "P1":    # 체커보드 (탭 후 '진짜' 변화)
        yy, xx = np.mgrid[0:80, 0:130]
        p[((yy // 8 + xx // 8) % 2) == 0] = (200, 200, 80)
    return p


def fold_x(x):
    """막대 끝점 반사(triangle fold) 좌표."""
    span = SPAN[1] - SPAN[0]
    u = (x - SPAN[0]) % (2 * span)
    return SPAN[0] + (u if u <= span else 2 * span - u)


def round_pattern(n):
    """라운드별 도전횟수 ROI 패턴(차감 흉내). 주기·색을 바꿔 상호 상관을 낮게 유지."""
    p = np.zeros((80, 130, 3), np.uint8)
    yy, xx = np.mgrid[0:80, 0:130]
    k = 5 + 3 * (n % 5)
    color = [(40, 200, 60), (200, 200, 80), (60, 80, 220), (180, 60, 180),
             (80, 220, 200)][n % 5]
    p[((yy // k + xx // k) % 2) == 0] = color
    return p


class World:
    """합성 게임 화면. 커서는 실시간 삼각파로 움직이고, press 주입 후에는
    선형 감속(decel_time)으로 미끄러지다 정지한다(실게임 감속-정지 역학)."""
    def __init__(self, roi_after, cursor_after_press=True, press_delay=0.0,
                 decel_time=1.0):
        self.t0 = time.monotonic()
        self.pressed_at = None
        self.press_count = 0
        self.press_pos = None
        self.roi_after = roi_after
        self.cursor_after_press = cursor_after_press
        self.press_delay = press_delay   # press RTT 이상(늦은 주입) 시뮬레이션용
        self.decel_time = decel_time     # 주입~정지 감속 시간(s)
        self.frame_idx = 0

    def _ended(self):
        return self.pressed_at is not None and time.monotonic() - self.pressed_at > 0.8

    def cursor_x(self, t):
        span = SPAN[1] - SPAN[0]
        u = (V * t) % (2 * span)
        return SPAN[0] + (u if u <= span else 2 * span - u)

    def cursor_free(self, t):
        """자유 주행 위치와 진행 방향."""
        span = SPAN[1] - SPAN[0]
        u = (V * t) % (2 * span)
        if u <= span:
            return SPAN[0] + u, +1
        return SPAN[0] + (2 * span - u), -1

    def cursor_decel(self, t):
        """press 주입 이후: 주입 시점 위치/방향에서 선형 감속 이동."""
        tp = self.pressed_at - self.t0
        x0, d = self.cursor_free(tp)
        Td = self.decel_time
        tt = min(max(t - tp, 0.0), Td)
        travel = V * (tt - tt * tt / (2.0 * Td)) if Td > 0 else 0.0
        return fold_x(x0 + d * travel)

    def is_done(self, img):
        return self._ended()

    def press(self, pos):
        if self.press_delay:
            time.sleep(self.press_delay)   # 주입 지연: p1-p0 를 부풀린다
        self.press_count += 1
        self.press_pos = pos
        if self.pressed_at is None:
            self.pressed_at = time.monotonic()
        return True

    def cap(self):
        self.frame_idx += 1
        t = time.monotonic() - self.t0
        img = np.zeros((1600, 900, 3), np.uint8)
        if not self._ended():
            img[BAR_Y[0]:BAR_Y[1], SPAN[0]:SPAN[1]] = (0, 0, 200)      # 빨강 막대
            for a, b in SAFES:
                img[BAR_Y[0]:BAR_Y[1], a:b] = (0, 220, 220)            # 노랑 안전구간
            if self.pressed_at is None:
                cx = int(self.cursor_x(t))
                img[BAR_Y[0]:BAR_Y[1], max(0, cx - 7):cx + 7] = (240, 240, 240)  # 흰 커서
            elif self.cursor_after_press:
                cx = int(self.cursor_decel(t))
                img[BAR_Y[0]:BAR_Y[1], max(0, cx - 7):cx + 7] = (240, 240, 240)
            # 도전 횟수 ROI: 1프레임=T(진입, 4회 템플릿), 탭 전=P0, 탭 후=시나리오별
            if self.frame_idx == 1:
                roi = make_pattern("T")
            elif self.pressed_at is None:
                roi = make_pattern("P0")
            else:
                roi = self.roi_after
            img[170:250, 20:150] = roi
        return img


class DecelWorld:
    """감속-정지 + 라운드(재도전) 상태 기계를 갖춘 합성 게임 (S5 시나리오용).

    press 주입 → 커서 선형 감속(decel_time) 정지 → 정지 위치가 안전구간 안이면
    성공(hold_hit 뒤 화면 전환=종료), 밖이면 실패(hold_miss 동안 정지 표시 후
    커서를 왼쪽 끝에서 재주행 = 같은 자물쇠 재도전). ROI 는 라운드 인덱스별
    패턴으로 도전 횟수 차감을 흉내 낸다(실패 시 항상, 성공 시 roi_change_on_hit)."""
    def __init__(self, decel_time, hold_miss=1.2, hold_hit=0.4,
                 roi_change_on_hit=False, max_rounds=6):
        self.t0 = time.monotonic()
        self.decel_time = decel_time
        self.hold_miss = hold_miss
        self.hold_hit = hold_hit
        self.roi_change_on_hit = roi_change_on_hit
        self.max_rounds = max_rounds
        self.press_count = 0
        self.roi_idx = 0
        self.run_start = 0.0      # 현재 라운드 주행 시작(월드 시각)
        self.phase = "run"        # run / tapped / ended
        self.press_t = None       # 주입 시각(월드 시각)
        self.inject = None        # 주입 시점 (위치, 방향)
        self.stop_x = None
        self.hits = []            # 탭별 명중 여부

    def _now(self):
        return time.monotonic() - self.t0

    def _free(self, t):
        span = SPAN[1] - SPAN[0]
        u = (V * (t - self.run_start)) % (2 * span)
        if u <= span:
            return SPAN[0] + u, +1
        return SPAN[0] + (2 * span - u), -1

    def _advance(self, t):
        """정지 유지 시간이 끝나면 라운드 전이(lazy 상태 기계)."""
        if self.phase != "tapped":
            return
        dwell = t - (self.press_t + self.decel_time)
        if dwell < 0:
            return
        if self.hits[-1]:
            if dwell >= self.hold_hit:
                self.phase = "ended"                  # 성공: 화면 전환
        elif dwell >= self.hold_miss:
            if len(self.hits) >= self.max_rounds:
                self.phase = "ended"                  # 기회 소진(함정) 흉내
            else:
                self.phase = "run"                    # 같은 자물쇠 재도전
                self.run_start = t
                self.press_t = None

    def _cursor(self, t):
        if self.phase == "run":
            return self._free(t)[0]
        x0, d = self.inject
        Td = self.decel_time
        tt = min(max(t - self.press_t, 0.0), Td)
        travel = V * (tt - tt * tt / (2.0 * Td)) if Td > 0 else 0.0
        return fold_x(x0 + d * travel)

    def is_done(self, img):
        self._advance(self._now())
        return self.phase == "ended"

    def press(self, pos):
        t = self._now()
        self._advance(t)
        self.press_count += 1
        if self.phase != "run":
            return True                               # 정지/전환 중 탭은 무시
        x0, d = self._free(t)
        self.inject = (x0, d)
        self.press_t = t
        self.stop_x = fold_x(x0 + d * (V * self.decel_time / 2.0))
        hit = any(a <= self.stop_x <= b for (a, b) in SAFES)
        self.hits.append(hit)
        if (not hit) or self.roi_change_on_hit:
            self.roi_idx += 1                         # 도전 횟수 차감 표시(패턴 교체)
        self.phase = "tapped"
        return True

    def cap(self):
        t = self._now()
        self._advance(t)
        img = np.zeros((1600, 900, 3), np.uint8)
        if self.phase == "ended":
            return img                                # 전환: 막대/커서/ROI 소실
        img[BAR_Y[0]:BAR_Y[1], SPAN[0]:SPAN[1]] = (0, 0, 200)
        for a, b in SAFES:
            img[BAR_Y[0]:BAR_Y[1], a:b] = (0, 220, 220)
        cx = int(self._cursor(t))
        img[BAR_Y[0]:BAR_Y[1], max(0, cx - 7):cx + 7] = (240, 240, 240)
        img[170:250, 20:150] = round_pattern(self.roi_idx)
        return img


class RecLogger:
    def __init__(self, verbose=False):
        self.lines = []
        self.verbose = verbose

    def _rec(self, lvl, msg):
        self.lines.append(f"{lvl}:{msg}")
        if self.verbose:
            print(f"    [{lvl}] {msg}")

    def info(self, m, *a, **k): self._rec("I", str(m))
    def debug(self, m, *a, **k): self._rec("D", str(m))
    def warning(self, m, *a, **k): self._rec("W", str(m))
    def error(self, m, *a, **k): self._rec("E", str(m))

    def has(self, sub):
        return any(sub in l for l in self.lines)


def load_module(tag, path):
    spec = importlib.util.spec_from_file_location(f"smart_disarm_{tag}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_old_module(ref):
    """git ref 의 src/smart_disarm.py 를 임시 파일로 꺼내 별도 모듈로 로드."""
    out = subprocess.run(["git", "show", f"{ref}:src/smart_disarm.py"],
                         cwd=REPO, capture_output=True)
    if out.returncode != 0:
        raise RuntimeError(f"git show 실패: {out.stderr.decode(errors='ignore').strip()}")
    path = os.path.join(tempfile.gettempdir(),
                        f"smart_disarm_{ref.replace('/', '_')}.py")
    with open(path, "wb") as f:
        f.write(out.stdout)
    return load_module("old", path)


def run_scenario(mod, name, roi_after_kind, cursor_after_press, verbose=False,
                 press_delay=0.0, seed=None, world=None):
    """seed: 보정 상태 사전 주입(dict). 지원 키:
       press_ema(세션 EMA) / resid(상자 내 잔차) / prev_meas(같은 상자 직전 탭 측정 여부)
       world: World 대신 사용할 합성 게임(예: DecelWorld). None 이면 기본 World."""
    tmp = tempfile.mkdtemp(prefix="sdtest_")
    res_dir = os.path.join(tmp, "resources", "images")
    cwd0 = os.getcwd()
    try:
        os.chdir(tmp)  # 구코드(CWD 상대 경로) 격리. 신코드는 _SMALLGAME_DIR 패치로 동일 위치 사용.
        if hasattr(mod, "_SMALLGAME_DIR"):
            mod._SMALLGAME_DIR = res_dir
        mod._PRESS_LAT["ema"] = None
        mod._STOP_LEAD["adj"] = 0.0
        if hasattr(mod, "_RESID"):
            mod._RESID["ewma"] = None
        if hasattr(mod, "_PREV_TAP_MEAS"):
            mod._PREV_TAP_MEAS["ok"] = True
        seed = seed or {}
        if "press_ema" in seed:
            mod._PRESS_LAT["ema"] = seed["press_ema"]
        if "resid" in seed and hasattr(mod, "_RESID"):
            mod._RESID["ewma"] = seed["resid"]
        if "prev_meas" in seed and hasattr(mod, "_PREV_TAP_MEAS"):
            mod._PREV_TAP_MEAS["ok"] = seed["prev_meas"]

        cfg = mod.DisarmConfig()
        cfg.stop_time = 1.0          # 시나리오 기대값(월드 감속·리드 수치)은 구 프라이어 1.0 기준으로
                                     # 저작됨 — 필드 기본값 재튜닝(26.07-28: 0.57)과 무관하게
                                     # 로직 회귀만 검증하도록 하니스에서 고정한다.
        cfg.sample_interval = 0.25   # 합성 캡처는 즉답이므로 실측 캡처 주기를 흉내
        w = world if world is not None else World(
            make_pattern(roi_after_kind), cursor_after_press, press_delay)
        log = RecLogger(verbose)
        smart_disarm = mod.SmartDisarm(
            w.cap, w.press, time.monotonic, log,
            is_done_fn=w.is_done, config=cfg,
        )
        if "resid" in seed and hasattr(smart_disarm, "_resid_ewma"):
            smart_disarm._resid_ewma = seed["resid"]
        if "prev_meas" in seed and hasattr(smart_disarm, "_prev_tap_meas"):
            smart_disarm._prev_tap_meas = seed["prev_meas"]
        ok = smart_disarm.run()
        files = sorted(os.path.basename(f)
                       for f in glob.glob(os.path.join(res_dir, "smallgame_*.png")))
        adj = mod._STOP_LEAD["adj"]
        resid = (
            smart_disarm._resid_ewma
            if hasattr(smart_disarm, "_resid_ewma")
            else (mod._RESID["ewma"] if hasattr(mod, "_RESID") else None)
        )
        print(f"  {name}: ok={ok} taps={w.press_count} adj={adj:+.3f} files={files}")
        return dict(ok=ok, taps=w.press_count, adj=adj, files=files, log=log,
                    resid=resid, world=w)
    finally:
        os.chdir(cwd0)
        shutil.rmtree(tmp, ignore_errors=True)


def run_measure_unit(mod, name, est_x, x1, x2, verbose=False):
    """_measure_after_tap 를 detect 스텁으로 직접 구동하는 마이크로 검증.
    프레임 자리에 detect 결과 dict 를 그대로 전달한다(detect=identity 몽키패치).
    타이밍: 주입 t=100.0, 전프레임 +0.22s, 후프레임 +0.72s (실기 캡처 시점 근사)."""
    log = RecLogger(verbose)
    cfg = mod.DisarmConfig()
    cfg.stop_time = 1.0   # 단일 외삽 폴백 기대값이 구 프라이어(1.0) 기준 — 위 run_scenario 와 동일 사유
    sd = mod.SmartDisarm(lambda: None, lambda p: True, time.monotonic, log, config=cfg)
    sd.detect = lambda img: img
    rng, safes = (16, 896), [(605, 745)]
    mkframe = lambda cx: dict(bar=rng, y=(40, 140), cursors=[(cx, 10)], safes=safes)
    est = {"x": float(est_x), "speed": 1165.0, "dir": +1}
    p0 = 100.0
    meas = sd._measure_after_tap(mkframe(x1), p0 + 0.22, p0, p0 + 0.05, p0,
                                 est, safes, rng,
                                 frame2=(mkframe(x2), p0 + 0.72, None))
    shown = "None" if meas is None else {
        k: (round(v, 3) if isinstance(v, float) else v) for k, v in meas.items()}
    print(f"  {name}: meas={shown}")
    return meas, log


def check(cond, desc, fails):
    print(f"    {'PASS' if cond else 'FAIL'}: {desc}")
    if not cond:
        fails.append(desc)


def main():
    ap = argparse.ArgumentParser(description="smart_disarm 수정 검증 하니스")
    ap.add_argument("--old-ref", default=None,
                    help="수정 전 코드의 git ref (예: 95b47d2). 지정 시 버그 재현 A/B 실행.")
    ap.add_argument("-v", "--verbose", action="store_true", help="시나리오 로그 전체 출력")
    args = ap.parse_args()

    new = load_module("new", os.path.join(SRC, "smart_disarm.py"))
    fails = []

    print("== [현행 코드] S1 genuine+meas: elif 단일 저장 + 무부호 보정 생략 ==")
    r = run_scenario(new, "S1", "P1", True, args.verbose)
    check(r["taps"] >= 1, "탭이 실행됨", fails)
    check("smallgame_3.png" in r["files"], "smallgame_3 저장됨", fails)
    check("smallgame_2.png" not in r["files"] and "smallgame_1.png" not in r["files"],
          "연쇄 저장 없음 (2/1 미생성)", fails)
    check(r["log"].has("강제 상향은 생략") or r["log"].has("추가 재조준은 생략")
          or r["log"].has("정지 실측 확정 → 재조준"),
          "meas 존재 시 무부호 보정 대신 측정 기반 경로", fails)
    check(not r["log"].has("강제 상향합니다") and not r["log"].has("측정 공백 연속)!"),
          "무부호 보정 미적용", fails)
    check(abs(r["adj"]) <= 0.1, "adj 는 측정 기반 소보정 이내", fails)
    check(r["resid"] is not None, "측정 잔차 EWMA 갱신됨", fails)

    print("== [현행 코드] S2 brightness(sim>=0.92): 실패 판정 해제 ==")
    r = run_scenario(new, "S2", "P0b", True, args.verbose)
    check(r["log"].has("실패 판정·템플릿 저장 모두 스킵"), "sim 필터가 실패 판정까지 해제", fails)
    check(not r["log"].has("탭 실패(도전 횟수 감소 감지)"), "실패 경고 없음", fails)
    check("smallgame_3.png" not in r["files"], "템플릿 미저장", fails)

    print("== [현행 코드] S3 genuine+meas없음(세션 첫 탭): 공백 연속 아님 → 생략 ==")
    r = run_scenario(new, "S3", "P1", False, args.verbose)
    check(r["log"].has("측정 공백 연속이 아니므로"), "공백 연속 아님 → 생략 로그", fails)
    check(not r["log"].has("리드 보정치를 강제 상향"), "구식 +0.05 미적용", fails)
    check(abs(r["adj"]) < 1e-9, f"adj == 0 (실측 {r['adj']:+.3f})", fails)

    print("== [현행 코드] S4a 공백 연속+잔차 +60px: +0.025 적용 ==")
    r = run_scenario(new, "S4a", "P1", False, args.verbose,
                     seed=dict(prev_meas=False, resid=60.0))
    check(r["log"].has("리드 보정 +0.025s 적용") and r["log"].has("잔차 추이"),
          "+0.025 적용(근거: 잔차 추이)", fails)
    check(abs(r["adj"] - 0.025) < 1e-9, f"adj == +0.025 (실측 {r['adj']:+.3f})", fails)
    check(r["resid"] is not None and abs(r["resid"] - 30.0) < 1e-6,
          f"EWMA 근거 소비 감쇠 60→30 (실측 {r['resid']})", fails)

    print("== [현행 코드] S4b 공백 연속+잔차 -60px: -0.025 적용 ==")
    r = run_scenario(new, "S4b", "P1", False, args.verbose,
                     seed=dict(prev_meas=False, resid=-60.0))
    check(r["log"].has("리드 보정 -0.025s 적용"), "-0.025 적용(음의 방향 보정 가능)", fails)
    check(abs(r["adj"] + 0.025) < 1e-9, f"adj == -0.025 (실측 {r['adj']:+.3f})", fails)
    check(r["resid"] is not None and abs(r["resid"] + 30.0) < 1e-6,
          f"EWMA 근거 소비 감쇠 -60→-30 (실측 {r['resid']})", fails)

    print("== [현행 코드] S4c 공백 연속+근거 없음(잔차 +10px): 생략 ==")
    r = run_scenario(new, "S4c", "P1", False, args.verbose,
                     seed=dict(prev_meas=False, resid=10.0))
    check(r["log"].has("보정 방향 근거가 없어"), "방향 근거 없음 → 생략 로그", fails)
    check(abs(r["adj"]) < 1e-9, f"adj == 0 (실측 {r['adj']:+.3f})", fails)

    print("== [현행 코드] S4d 공백 연속+press 지연 이상(0.12s): +0.025 적용 ==")
    r = run_scenario(new, "S4d", "P1", False, args.verbose, press_delay=0.12,
                     seed=dict(prev_meas=False, press_ema=0.001))
    check(r["log"].has("press 지연 이상"), "RTT 이상 근거 로그", fails)
    check(abs(r["adj"] - 0.025) < 1e-9, f"adj == +0.025 (실측 {r['adj']:+.3f})", fails)

    print("== [현행 코드] S4e blind 근거 소비 감쇠: 동결 EWMA 반복 소비 시 자연 정지 ==")
    # 26-07-17 실전 재현: 측정 기아로 EWMA -268px 동결 → blind 14연속 -0.025 표류.
    # 감쇠 적용 후에는 4회 발동(-268→-134→-67→-33.5→-16.75) 뒤 근거 소진으로 생략.
    new._PRESS_LAT["ema"] = 0.02
    sd_unit = new.SmartDisarm(lambda: None, lambda p: True, time.monotonic, RecLogger())
    sd_unit._resid_ewma = -268.0
    steps = [round(sd_unit._blind_fail_step(0.02)[0], 3) for _ in range(6)]
    check(steps == [-0.025] * 4 + [0.0, 0.0],
          f"4회 발동 후 근거 소진으로 자연 정지 (실측 {steps})", fails)
    check(abs(sd_unit._resid_ewma + 16.75) < 0.01,
          f"EWMA -268 → -16.75 (실측 {sd_unit._resid_ewma:+.2f})", fails)

    print("== [현행 코드] S5a 감속 0.35s 개체: 실측 재조준 후 재도전 명중 ==")
    r = run_scenario(new, "S5a", None, True, args.verbose,
                     world=DecelWorld(decel_time=0.35, hold_miss=1.2))
    w = r["world"]
    check(len(w.hits) >= 2 and not w.hits[0], "탭1 은 미스(모델-개체 감속 편차 재현)", fails)
    check(w.hits[-1] and r["ok"], "재조준 후 명중으로 종료", fails)
    check(len(w.hits) <= 3, f"수렴 3탭 이내 (실측 {len(w.hits)}탭)", fails)
    check(r["log"].has("2프레임 감속 실측") or r["log"].has("2프레임 정지 확정"),
          "2프레임 실측 경로 사용", fails)
    check(r["log"].has("정지 실측 확정 → 재조준"), "실패 확정 재조준 발동", fails)
    check(r["adj"] <= -0.2, f"리드가 실측만큼 당겨짐 (실측 {r['adj']:+.3f})", fails)

    print("== [현행 코드] S5b 감속 1.0s 개체(모델 일치): 탭1 명중, 재조준 미발동 ==")
    r = run_scenario(new, "S5b", None, True, args.verbose,
                     world=DecelWorld(decel_time=1.0, hold_miss=1.2))
    w = r["world"]
    check(w.hits and w.hits[0] and r["ok"], "탭1 명중(회귀 없음)", fails)
    check(len(w.hits) == 1, f"탭 1회로 종료 (실측 {len(w.hits)}탭)", fails)
    check(r["log"].has("2프레임 감속 실측"), "감속시간 역산 경로 사용(Ts≈1.0 재현)", fails)
    check(not r["log"].has("정지 실측 확정 → 재조준"), "재조준 미발동", fails)
    check(abs(r["adj"]) <= 0.1, f"adj 소보정 이내 (실측 {r['adj']:+.3f})", fails)

    print("== [현행 코드] S5c 실패 후 커서 조기 리셋: 신규 커서 측정 폐기 ==")
    # hold_miss=0.05: 후프레임(+0.5s) 시점에 확실히 리셋 이후(경계 레이스 방지).
    # 리셋 커서는 끝점 재출발이라 역행(검출 시) 또는 커서 불특정(끝점 미검출)으로
    # 나타난다 — 어느 쪽이든 전프레임 단일 외삽(자기기만)이 되살아나면 안 된다.
    # 마지막 탭은 종료 전환을 만나 무해한 단일 외삽 EMA 소보정(<=1스텝)만 남는다.
    r = run_scenario(new, "S5c", None, True, args.verbose,
                     world=DecelWorld(decel_time=0.35, hold_miss=0.05, max_rounds=2))
    check(r["log"].has("신규 커서 의심") or r["log"].has("후프레임 커서 불특정"),
          "리셋 커서 → 측정 폐기 로그", fails)
    check(not r["log"].has("정지 실측 확정 → 재조준"), "오염 재조준 없음", fails)
    check(abs(r["adj"]) <= 0.03, f"adj 오염 없음(EMA 1스텝 이내, 실측 {r['adj']:+.3f})", fails)

    print("== [현행 코드] S5d 성공 탭 + diff 오탐: 실측 err≈0 → 재조준 자기제한 ==")
    r = run_scenario(new, "S5d", None, True, args.verbose,
                     world=DecelWorld(decel_time=1.0, hold_hit=1.5,
                                      roi_change_on_hit=True))
    w = r["world"]
    check(w.hits and w.hits[0] and r["ok"], "탭1 실제로는 명중", fails)
    check(r["log"].has("탭 실패"), "ChallengeCheck 는 오탐(실패 판정) 발생", fails)
    check(abs(r["adj"]) <= 0.1, f"오탐에도 리드 오염 자기제한 (실측 {r['adj']:+.3f})", fails)

    print("== [현행 코드] S5e 반사 가드 유닛: 반사 창 폐기 / 안전 창 실측 유지 ==")
    # 반사 창(v=1165, 주입 450, 벽거리 446 < 최대주행 650): 실제 감속 1.0s 커서가
    # 벽 반사 후 x2=805 로 복귀 — 가드 없으면 허구 Ts=0.574 가 trusted 로 수용된다.
    m, lg = run_measure_unit(new, "S5e-1(반사창)", 450, 678, 805, args.verbose)
    check(m is None and lg.has("반사 개입 가능"), "반사 개입 가능 구간 → 측정 폐기", fails)
    # 안전 창(주입 92, 벽거리 804): 실제 감속 1.0s 프레임 값 → Ts·정지 정확 역산
    m, lg = run_measure_unit(new, "S5e-2(정상감속)", 92, 320, 629, args.verbose)
    check(m is not None and m.get("trusted") and m.get("ts")
          and abs(m["ts"] - 1.0) < 0.05, "안전 창: 감속 1.0s 정확 역산", fails)
    check(m is not None and abs(m["settle"] - 675) < 8,
          f"정지 추정 675±8 (실측 {m and round(m['settle'])})", fails)
    # 안전 창 + 짧은 감속 개체(0.30s, 195139 유형): 후프레임 전에 이미 정지
    m, lg = run_measure_unit(new, "S5e-3(짧은감속)", 92, 254, 267, args.verbose)
    check(m is not None and m.get("trusted") and m.get("ts")
          and abs(m["ts"] - 0.30) < 0.03, "안전 창: 감속 0.30s 정확 역산", fails)
    check(m is not None and abs(m["settle"] - 267) < 2, "정지 위치 실측(=후프레임)", fails)
    # 반사 창이어도 '정지 확정'(두 프레임 동일)은 가드보다 먼저 실측 채택되어야 한다
    # (26.07-17 실전에서 가드 선행 배치가 정지 확정을 차단해 커버리지 19% 급락).
    m, lg = run_measure_unit(new, "S5e-4(반사창+정지)", 450, 283, 284, args.verbose)
    check(m is not None and m.get("trusted") and m.get("ts") is None
          and abs(m["settle"] - 284) < 1, "반사 창에서도 정지 확정은 실측 채택", fails)
    check(not lg.has("반사 개입 가능"), "정지 확정이 가드에 선행", fails)
    # 반사 창 + 역행(신규 커서): 가드가 아닌 '역행' 사유로 폐기(더 정확한 진단)
    m, lg = run_measure_unit(new, "S5e-5(반사창+역행)", 450, 500, 300, args.verbose)
    check(m is None and lg.has("신규 커서 의심") and not lg.has("반사 개입 가능"),
          "역행 폐기가 가드에 선행", fails)

    if args.old_ref:
        old = load_old_module(args.old_ref)

        print(f"== [구코드 {args.old_ref}] S1: 연쇄 저장 버그 + 이중 보정 재현 ==")
        r = run_scenario(old, "S1(old)", "P1", True, args.verbose)
        check({"smallgame_1.png", "smallgame_2.png", "smallgame_3.png"} <= set(r["files"]),
              "구코드에서 3/2/1 연쇄 저장 재현", fails)
        check(r["log"].has("강제 상향합니다"), "구코드는 meas 있어도 +0.05 (이중 보정) 재현", fails)

        print(f"== [구코드 {args.old_ref}] S2: sim 필터 자기모순 재현 ==")
        r = run_scenario(old, "S2(old)", "P0b", True, args.verbose)
        check(r["log"].has("횟수 차감 없음으로 간주") and r["log"].has("강제 상향합니다"),
              "구코드는 '차감 없음 간주'하면서 +0.05 적용(자기모순) 재현", fails)

        print(f"== [구코드 {args.old_ref}] S3: 첫 무측정 실패에도 무조건 +0.05 재현 ==")
        r = run_scenario(old, "S3(old)", "P1", False, args.verbose)
        check(r["log"].has("강제 상향합니다"), "구코드는 조건 없이 +0.05 적용 재현", fails)
        check(abs(r["adj"] - 0.05) < 1e-9, f"구코드 adj == +0.05 (실측 {r['adj']:+.3f})", fails)

    print()
    if fails:
        print(f"결과: FAIL {len(fails)}건")
        for f in fails:
            print(f"  - {f}")
        sys.exit(1)
    print("결과: 전체 PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
