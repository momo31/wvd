# -*- coding: utf-8 -*-
"""smart_disarm 수정 검증 하니스 (2026-07-15 적중률+위생 수정분).

SmartDisarm 의 주입 구조(cap/press/now/is_done)를 이용해 실제 run() 루프를
합성 프레임(삼각파 커서 + 막대/안전구간 + ROI 패턴)으로 구동하고,
ChallengeCheck 경로까지 도달시켜 아래 4개 수정의 동작을 검증한다.

  1. 자가 학습 템플릿 연쇄 저장 방지(elif 체인) - 실패 탭 1회에 템플릿 1장만 저장
  2. sim>=0.92 필터가 is_failed 도 해제 - 무변화 화면에서의 +0.05 오보정 차단
  3. +0.05 강제 상향은 meas(정지위치 역산) 실패 탭에만 - 이중 보정 차단
  4. smallgame 경로 절대화(_SMALLGAME_DIR) - 하니스는 이 변수를 임시 폴더로 패치

사용법 (저장소 루트에서):
  python tools/test_smart_disarm_fixes.py
      현재 작업트리 코드로 S1~S3 검증.
  python tools/test_smart_disarm_fixes.py --old-ref 95b47d2
      수정 전 코드(git ref)를 같은 시나리오로 실행해 버그 재현까지 A/B 확인.
      (수정 전 커밋을 지정해야 재현 검증이 의미가 있다. 예: 95b47d2)

시나리오:
  S1 genuine+meas   : 탭 후 ROI 실제 변화 + 탭 직후 커서 검출(meas 성공)
  S2 brightness     : 탭 후 ROI 밝기 +12 (diff>=3, sim>=0.92) - 무변화로 간주해야 함
  S3 genuine+nomeas : ROI 변화 + 탭 직후 커서 미검출(meas 실패) - +0.05 보조 보정 대상

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


class World:
    """합성 게임 화면. 커서는 실시간 삼각파로 움직인다."""
    def __init__(self, roi_after, cursor_after_press=True):
        self.t0 = time.monotonic()
        self.pressed_at = None
        self.press_count = 0
        self.press_pos = None
        self.roi_after = roi_after
        self.cursor_after_press = cursor_after_press
        self.frame_idx = 0

    def _ended(self):
        return self.pressed_at is not None and time.monotonic() - self.pressed_at > 0.8

    def cursor_x(self, t):
        span = SPAN[1] - SPAN[0]
        u = (V * t) % (2 * span)
        return SPAN[0] + (u if u <= span else 2 * span - u)

    def is_done(self, img):
        return self._ended()

    def press(self, pos):
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
            if self.pressed_at is None or self.cursor_after_press:
                cx = int(self.cursor_x(t))
                img[BAR_Y[0]:BAR_Y[1], max(0, cx - 7):cx + 7] = (240, 240, 240)  # 흰 커서
            # 도전 횟수 ROI: 1프레임=T(진입, 4회 템플릿), 탭 전=P0, 탭 후=시나리오별
            if self.frame_idx == 1:
                roi = make_pattern("T")
            elif self.pressed_at is None:
                roi = make_pattern("P0")
            else:
                roi = self.roi_after
            img[170:250, 20:150] = roi
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


def run_scenario(mod, name, roi_after_kind, cursor_after_press, verbose=False):
    tmp = tempfile.mkdtemp(prefix="sdtest_")
    res_dir = os.path.join(tmp, "resources", "images")
    cwd0 = os.getcwd()
    try:
        os.chdir(tmp)  # 구코드(CWD 상대 경로) 격리. 신코드는 _SMALLGAME_DIR 패치로 동일 위치 사용.
        if hasattr(mod, "_SMALLGAME_DIR"):
            mod._SMALLGAME_DIR = res_dir
        mod._PRESS_LAT["ema"] = None
        mod._STOP_LEAD["adj"] = 0.0

        cfg = mod.DisarmConfig()
        cfg.sample_interval = 0.25   # 합성 캡처는 즉답이므로 실측 캡처 주기를 흉내
        w = World(make_pattern(roi_after_kind), cursor_after_press)
        log = RecLogger(verbose)
        ok = mod.SmartDisarm(w.cap, w.press, time.monotonic, log,
                             is_done_fn=w.is_done, config=cfg).run()
        files = sorted(os.path.basename(f)
                       for f in glob.glob(os.path.join(res_dir, "smallgame_*.png")))
        adj = mod._STOP_LEAD["adj"]
        print(f"  {name}: ok={ok} taps={w.press_count} adj={adj:+.3f} files={files}")
        return dict(ok=ok, taps=w.press_count, adj=adj, files=files, log=log)
    finally:
        os.chdir(cwd0)
        shutil.rmtree(tmp, ignore_errors=True)


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
    check(r["log"].has("강제 상향은 생략"), "meas 존재 시 +0.05 생략 로그", fails)
    check(not r["log"].has("강제 상향합니다"), "+0.05 강제 상향 미적용", fails)
    check(abs(r["adj"]) <= 0.081, "adj 는 부호 있는 보정 1스텝 이내", fails)

    print("== [현행 코드] S2 brightness(sim>=0.92): 실패 판정 해제 ==")
    r = run_scenario(new, "S2", "P0b", True, args.verbose)
    check(r["log"].has("실패 판정·템플릿 저장 모두 스킵"), "sim 필터가 실패 판정까지 해제", fails)
    check(not r["log"].has("탭 실패(도전 횟수 감소 감지)"), "실패 경고 없음", fails)
    check("smallgame_3.png" not in r["files"], "템플릿 미저장", fails)

    print("== [현행 코드] S3 genuine+meas없음: 무부호 +0.05 보조 보정 1회 ==")
    r = run_scenario(new, "S3", "P1", False, args.verbose)
    check(r["log"].has("강제 상향합니다"), "+0.05 강제 상향 적용", fails)
    check(abs(r["adj"] - 0.05) < 1e-9, f"adj == +0.05 정확히 (실측 {r['adj']:+.3f})", fails)

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
