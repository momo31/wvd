"""smart_disarm.py - 스마트 상자 개봉 (함정 해제 미니게임 타이밍 예측)

기존 script.py 를 수정하지 않고 분리한 독립 모듈. 캡처/탭/시각/로거/종료판정을
주입(dependency injection)받아 동작하므로 단위 검증과 점진 통합이 쉽다.

설계 근거 (analyze/ 의 실측 109장 + 시뮬레이션):
- 게임 내 등속, 게임 간 속도 변동 → 3점 등속 외삽(closed-form). curve_fit 불필요.
- 정적 위치노이즈 σ≈0.24px(작음) → 서브픽셀·5점회귀 이득 미미 → 3점 채택.
- 주 노이즈는 (a)모션블러 누락 ~10% (b)흰 물체 거짓양성 ~29% → 커서 3중 필터.
- 안전구간 폭 가변(138~283px) → margin 은 폭 비례.
- 약점은 빠른 게임(시뮬 성공률↓) → '어려운 게임 우회'를 설정 옵션으로 제공.

운영하며 보완할 값은 DisarmConfig 에 모아두었다(실측 재수집 후 튜닝).
"""
import time
import numpy as np
import cv2


class DisarmConfig:
    """운영 튜닝 파라미터 (실데이터 확보 후 조정). 인스턴스로 복제해 덮어쓰기 가능."""
    # --- 타이밍 ---
    sample_interval = 0.0      # 샘플 간 추가 대기(s). 0=캡처 속도대로(권장, Δt=캡처비용)
    input_delay = 0.10         # 탭 명령~실제 입력 지연(s). 운영 측정 후 보정.
    pw_thresh = 1.5            # 이 시간 이내 도달하는 안전구간만 노림(s)
    # --- margin ---
    margin_ratio = 0.10        # 안전구간 폭의 비율 (시뮬 최적 ~0.10)
    margin_speed_k = 0.0       # 속도 의존 가산: margin += k*v*Δt (빠른게임 여유). 0=비활성
    margin_min = 4.0           # 최소 margin(px)
    # --- 커서 검출 필터 (거짓양성 방어) ---
    cursor_w_min = 6
    cursor_w_max = 22
    white_thr = 185            # 흰 커서 min(R,G,B) 임계 (실측: 150~215에서 둔감)
    continuity_pad = 60.0      # 직전 위치 연속성 허용 = v*Δt + 이 여유(px)
    # --- 추정 견고화 ---
    eps = 2.0                  # 방향/데드존 임계(px). 노이즈로 인한 거짓반전 차단.
    straightness_tol = 12.0    # 등속 3점 직선성 검증 허용 잔차(px). 초과 시 폐기.
    # --- 안전/폴백 ---
    max_total_samples = 40     # 전체 캡처 상한(무한루프 방지)
    max_consecutive_miss = 6   # 연속 검출 실패 허용
    bypass_fast_game = False   # [옵션] 빠른(어려운) 게임은 폴백으로 우회 (사용자 선택)
    fast_game_k = 2.5          # 반주기 < fast_game_k*Δt 이면 '빠른 게임'으로 판정
    fast_game_fail_limit = 3   # 빠른게임 판정/실패가 이만큼 누적되면 폴백 트리거
    settle_after_tap = 1.0     # 탭 후 결과 안정 대기(s)
    # 입력 좌표: 게임은 막대가 아니라 고정 'Disarm' 버튼을 누른다(기존 script.py disarm=[515,934]).
    # 커서 x는 '언제 누를지' 타이밍 판단용일 뿐, 실제 탭은 이 버튼. 통합 시 오버라이드.
    disarm_button = (515, 934)


class SmartDisarm:
    def __init__(self, screenshot_fn, press_fn, now_fn, logger,
                 is_done_fn=None, fallback_fn=None, config=None, _=None, auditor=None):
        """
        screenshot_fn() -> BGR ndarray | None   : 화면 캡처
        press_fn([x, y]) -> bool                 : 좌표 탭 (None 안전)
        now_fn() -> float                        : 단조 시각(s) (캡처 직후 호출로 시각동기화)
        logger                                   : .info/.debug/.warning
        is_done_fn(img) -> bool                  : 미니게임 종료(개봉 완료/던전복귀) 판정 (선택)
        fallback_fn() -> None                    : 어려운 게임 폴백(기존 연타 등) (선택)
        config: DisarmConfig                     : 파라미터
        _ : 번역 함수(gettext). None이면 무번역.
        """
        self.cap = screenshot_fn
        self.press = press_fn
        self.now = now_fn
        self.log = logger
        self.is_done = is_done_fn
        self.fallback = fallback_fn
        self.cfg = config or DisarmConfig()
        self._t = _ or (lambda s: s)
        self.audit = auditor   # audit 모듈 주입(없으면 None -> 모든 audit hook no-op)

    # ===================== 화면 분석 =====================
    def detect(self, img):
        """막대 영역/커서 후보/안전구간 검출. 실패 시 None.
        반환: dict(bar=(x0,x1), y=(y0,y1), cursors=[(x,w)], safes=[(a,b)])"""
        if img is None:
            return None
        region = img[0:180]
        b = region[:, :, 0].astype(np.int16)
        g = region[:, :, 1].astype(np.int16)
        r = region[:, :, 2].astype(np.int16)
        # 막대(빨강/노랑 계열) 픽셀: R 우세
        barmask = (r > 100) & (r > b + 30)
        rows = barmask.sum(axis=1)
        if rows.max() == 0:
            return None
        ys = np.where(rows > rows.max() * 0.35)[0]
        # 막대 본체 = 가장 두꺼운 연속 띠. (아래쪽 빨강 체력바/하단 UI 를 분리)
        bands = self._clusters(ys, gap=4, as_center=False)
        y0, y1 = max(bands, key=lambda ab: ab[1] - ab[0])
        y0, y1 = int(y0), int(y1)
        cols_bar = np.where(barmask[y0:y1 + 1].sum(axis=0) > (y1 - y0 + 1) * 0.3)[0]
        if len(cols_bar) < 10:
            return None
        bar_x0, bar_x1 = int(cols_bar.min()), int(cols_bar.max())
        barh = y1 - y0 + 1

        mn = np.minimum(np.minimum(b, g), r)
        white = (mn > self.cfg.white_thr)[y0:y1 + 1]
        yellow = ((r > 150) & (g > 110) & (b < 130))[y0:y1 + 1]
        wc = white.sum(axis=0)
        yc = yellow.sum(axis=0)

        cursors = self._clusters(np.where(wc > barh * 0.45)[0], gap=12, as_center=True)
        safes_raw = self._clusters(np.where(yc > barh * 0.40)[0], gap=20, as_center=False)
        safes = [(a, b2) for (a, b2) in safes_raw if (b2 - a) >= 25]  # 너무 좁은 노이즈 제외
        return {"bar": (bar_x0, bar_x1), "y": (y0, y1), "cursors": cursors, "safes": safes}

    @staticmethod
    def _clusters(idx, gap, as_center):
        out = []
        if len(idx) == 0:
            return out
        s = p = int(idx[0])
        for c in idx[1:]:
            c = int(c)
            if c - p > gap:
                out.append(((s + p) // 2, p - s + 1) if as_center else (s, p))
                s = c
            p = c
        out.append(((s + p) // 2, p - s + 1) if as_center else (s, p))
        return out

    def pick_cursor(self, cursors, prev_x, v_est, dt):
        """거짓양성 3중 필터: 폭 → 연속성 → prev 최근접."""
        cand = [(x, w) for (x, w) in cursors if self.cfg.cursor_w_min <= w <= self.cfg.cursor_w_max]
        if not cand:
            return None
        if prev_x is not None:
            reach = abs(v_est) * dt + self.cfg.continuity_pad if v_est else self.cfg.continuity_pad
            near = [(x, w) for (x, w) in cand if abs(x - prev_x) <= reach]
            if near:
                cand = near
            cand.sort(key=lambda c: abs(c[0] - prev_x))
        return int(cand[0][0])

    # ===================== 추정 =====================
    def estimate(self, samples, xmin, xmax):
        """최근 3점으로 등속 속도/방향. 끝점 반전 거리공식 + 직선성 검증.
        반환 dict(x,speed,dir) 또는 None(재측정)."""
        (t1, x1), (t2, x2), (t3, x3) = samples[-3:]
        dt = t3 - t1
        if dt <= 0:
            return None
        x1 = min(max(x1, xmin), xmax); x2 = min(max(x2, xmin), xmax); x3 = min(max(x3, xmin), xmax)
        eps = self.cfg.eps
        dx12, dx23 = x2 - x1, x3 - x2
        if dx12 > eps and dx23 < -eps:           # 오른쪽 이동 중 xmax 반전
            dist, direction = (xmax - x1) + (xmax - x3), -1
        elif dx12 < -eps and dx23 > eps:         # 왼쪽 이동 중 xmin 반전
            dist, direction = (x1 - xmin) + (x3 - xmin), +1
        else:                                    # 반전 없음 → 직선성 검증
            if t2 > t1 and t3 > t2:
                pred_x2 = x1 + (x3 - x1) * (t2 - t1) / (t3 - t1)  # 등속 가정 시 x2 기대값
                if abs(pred_x2 - x2) > self.cfg.straightness_tol:
                    return None                  # 등속 직선 위반 → 이상치/숨은반전, 폐기
            dist = abs(x3 - x1)
            direction = +1 if x3 > x1 + eps else -1 if x3 < x1 - eps else 0
        speed = dist / dt
        if speed <= 1 or direction == 0:
            return None
        return {"x": x3, "speed": speed, "dir": direction}

    def reach_time(self, x, v, d, c, xmin, xmax):
        """현재(x,방향d,속도v)에서 목표 c 도달까지 시간. 끝점 반전 고려(전역 예측)."""
        if d > 0:
            return (c - x) / v if c >= x else ((xmax - x) + (xmax - c)) / v
        else:
            return (x - c) / v if c <= x else ((x - xmin) + (c - xmin)) / v

    def plan_tap(self, est, safes, xmin, xmax, dt):
        """두 안전구간 중 가장 이른 도달을 선택, press_wait·목표·margin 반환."""
        x, v, d = est["x"], est["speed"], est["dir"]
        best = None
        for (a, b) in safes:
            c = (a + b) / 2
            half = (b - a) / 2
            margin = max(self.cfg.margin_min, half * self.cfg.margin_ratio
                         + self.cfg.margin_speed_k * v * dt)
            tt = self.reach_time(x, v, d, c, xmin, xmax)
            if best is None or tt < best["reach"]:
                best = {"reach": tt, "center": c, "half": half, "margin": margin}
        return best

    # ===================== 메인 루프 =====================
    def run(self):
        cfg = self.cfg
        samples = []          # [(t, x)] 검출 성공만
        prev_x = None
        v_est = 0.0
        last_dt = cfg.sample_interval or 0.25
        shots = 0
        miss = 0
        fast_hits = 0
        last_safes = None
        last_range = None
        self.log.info(self._t("스마트 개봉 시작..."))
        if self.audit: self.audit.on_start()

        while shots < cfg.max_total_samples:
            t0 = self.now()
            img = self.cap()
            t = self.now()                     # 캡처 직후 시각(시각 동기화: 측정 x의 시각)
            shots += 1

            if img is None:
                miss += 1
                if miss > cfg.max_consecutive_miss:
                    return self._give_up("캡처 연속 실패")
                continue

            # 게임 종료 판정
            if self.is_done and self.is_done(img):
                self.log.info(self._t("개봉 완료/화면 전환 감지. 종료."))
                if self.audit: self.audit.on_result(self._t("성공(즉시종료)"))
                return True

            d = self.detect(img)
            if not d or len(d["safes"]) == 0:
                miss += 1
                if miss > cfg.max_consecutive_miss:
                    return self._give_up("막대/안전구간 미검출")
                continue
            last_safes = d["safes"]
            xmin, xmax = d["bar"]
            last_range = (xmin, xmax)

            cx = self.pick_cursor(d["cursors"], prev_x, v_est, last_dt)
            if cx is None:
                miss += 1                       # 모션블러 등으로 커서 누락 → 재측정
                if miss > cfg.max_consecutive_miss:
                    return self._give_up("커서 연속 미검출")
                continue
            miss = 0
            samples.append((t, cx))
            if self.audit: self.audit.on_sample(t, cx, abs(v_est), 1 if v_est >= 0 else -1)
            if prev_x is not None and t > t0:
                last_dt = max(1e-3, t - samples[-2][0]) if len(samples) >= 2 else last_dt
            prev_x = cx

            if len(samples) < 3:
                self._pace(t0)
                continue

            est = self.estimate(samples, xmin, xmax)
            if est is None:
                self._pace(t0)
                continue
            v_est = est["speed"] * est["dir"]
            if self.audit: self.audit.on_estimate(est)

            # aliasing / 빠른 게임 판정
            half_period = (xmax - xmin) / est["speed"]
            if half_period < cfg.fast_game_k * last_dt:
                fast_hits += 1
                self.log.debug(self._t("빠른 게임 의심(반주기 {a:.2f}s, Δt {b:.2f}s)")
                               .format(a=half_period, b=last_dt))
                if cfg.bypass_fast_game and fast_hits >= cfg.fast_game_fail_limit:
                    return self._do_fallback("빠른 게임 우회(옵션)")
                # 우회 안 하면 그래도 시도(샘플 신뢰 낮음) — 한 점 더 모아 재시도
                self._pace(t0)
                continue

            plan = self.plan_tap(est, last_safes, xmin, xmax, last_dt)
            if plan is None:
                self._pace(t0)
                continue

            # press_wait: 마지막 측정(t) 기준. 측정~지금 경과 + 입력지연 보정.
            elapsed_since_meas = self.now() - t
            press_wait = plan["reach"] - elapsed_since_meas - cfg.input_delay
            if press_wait <= 0:
                self._pace(t0)                  # 이미 지남 → 다음 기회
                continue
            if press_wait > cfg.pw_thresh:
                self._pace(t0)                  # 아직 멀음 → 더 가까운 기회 대기
                continue

            # 탭 실행
            if press_wait > 0:
                time.sleep(press_wait)
            if self.audit:
                _aimg = self.cap()
                _ad = self.detect(_aimg)
                _acur = self.pick_cursor(_ad["cursors"], est["x"], v_est, last_dt) if _ad else None
                self.audit.on_tap(_aimg, _acur, plan, est, last_safes, (xmin, xmax))
            ok = self.press(list(self.cfg.disarm_button))   # 타이밍 맞춰 고정 Disarm 버튼 탭
            self.log.info(self._t("개봉 탭: 목표구간중심x={a:.0f} margin={b:.0f} pw={c:.3f}s 속도={d:.0f}px/s")
                          .format(a=plan["center"], b=plan["margin"], c=press_wait, d=est["speed"]))
            time.sleep(cfg.settle_after_tap)

            # 결과 확인
            after = self.cap()
            if self.is_done and after is not None and self.is_done(after):
                self.log.info(self._t("개봉 성공/종료 감지."))
                if self.audit: self.audit.on_result(self._t("성공"))
                return True
            # 아직 진행 중이면 상태 리셋하고 계속 (함정이 여러 단계일 수 있음)
            samples.clear(); prev_x = None; v_est = 0.0

        return self._give_up("샘플 상한 초과")

    # ===================== 보조 =====================
    def _pace(self, t0):
        if self.cfg.sample_interval > 0:
            rest = self.cfg.sample_interval - (self.now() - t0)
            if rest > 0:
                time.sleep(rest)

    def _do_fallback(self, reason):
        self.log.info(self._t("폴백 실행({a}).").format(a=reason))
        if self.fallback:
            if self.audit: self.audit.on_result(self._t("폴백: ") + reason)
            self.fallback()
            return True
        return self._give_up(reason + self._t(" (폴백 미설정)"))

    def _give_up(self, reason):
        self.log.warning(self._t("스마트 개봉 중단: {a}").format(a=reason))
        if self.audit: self.audit.on_result(self._t("중단: ") + reason)
        if self.cfg.bypass_fast_game and self.fallback:
            self.fallback()
        return False


# ===================== 단독 검증 (실데이터/합성) =====================
if __name__ == "__main__":
    import glob, re, sys

    sd = SmartDisarm(lambda: None, lambda p: True, time.monotonic,
                     logger=type("L", (), {"info": lambda *a: None, "debug": lambda *a: None,
                                           "warning": lambda *a: None})())

    # 1) 실이미지 검출 검증
    files = sorted(glob.glob('img/chest_20260626_022348_*.png'),
                   key=lambda f: int(re.search(r'_(\d+)\.png', f).group(1)))
    print("[detect 검증]")
    series = []
    for f in files:
        img = cv2.imread(f)
        d = sd.detect(img)
        n = re.search(r'_(\d+)\.png', f).group(1)
        if d:
            cx = sd.pick_cursor(d["cursors"], series[-1] if series else None, 0, 0.25)
            series.append(cx)
            print(f"  f{n}: bar={d['bar']} 커서x={cx} 안전구간={d['safes']}")
        else:
            print(f"  f{n}: 미검출")

    # 2) 합성 등속 데이터로 estimate/plan 검증
    print("\n[estimate/plan 검증 (합성 등속)]")
    xmin, xmax = 16, 896
    safes = [(137, 314), (587, 764)]
    v = 500.0
    # 오른쪽 이동 중 3점
    smp = [(0.0, 300.0), (0.25, 425.0), (0.50, 550.0)]
    est = sd.estimate(smp, xmin, xmax)
    print(f"  등속 추정: {est}  (기대 speed≈500 dir=+1)")
    if est:
        plan = sd.plan_tap(est, safes, xmin, xmax, 0.25)
        print(f"  탭 계획: {plan}")
    # 반전 포함 3점 (오른끝에서 반전)
    smp2 = [(0.0, 850.0), (0.25, 890.0), (0.50, 800.0)]
    print(f"  반전 추정: {sd.estimate(smp2, xmin, xmax)}  (기대 dir=-1)")
    # 거짓반전(노이즈) 차단 검증: 직선인데 가운데 점이 튐
    smp3 = [(0.0, 300.0), (0.25, 470.0), (0.50, 550.0)]  # 등속이면 x2≈425인데 470(노이즈)
    print(f"  직선성검증(이상치 차단): {sd.estimate(smp3, xmin, xmax)}  (None이면 정상 차단)")
    sys.exit(0)
