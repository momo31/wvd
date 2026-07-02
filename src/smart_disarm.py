"""smart_disarm.py - 스마트 상자 개봉 (함정 해제 미니게임 타이밍 예측)

기존 script.py 를 수정하지 않고 분리한 독립 모듈. 캡처/탭/시각/로거/종료판정을
주입(dependency injection)받아 동작하므로 단위 검증과 점진 통합이 쉽다.

설계 근거 (analyze/ 의 실측 109장 + 시뮬레이션):
- 게임 내 등속, 게임 간 속도 변동 → 3점 등속 외삽(closed-form). curve_fit 불필요.
- 정적 위치노이즈 σ≈0.24px(작음) → 서브픽셀·5점회귀 이득 미미 → 3점 채택.
- 주 노이즈는 (a)모션블러 누락 ~10% (b)흰 물체 거짓양성 ~29% → 커서 3중 필터.
- 안전구간 폭 가변(138~283px) → margin 은 폭 비례.
- 약점은 빠른 게임(시뮬 성공률↓) → '어려운 게임 우회'를 설정 옵션으로 제공.

운영 audit 개정 (26.07 실측 232탭 + 로그 3,145호출 분석 반영):
- 막대가 없는 화면(상자 UI 잔류 등)에서 호출되면 즉시 반환해야 한다.
  기존엔 7회 캡처(~5.6s)+폴백 스팸을 무한 반복해 한 상자에서 약 8시간 연속 스턱 발생
  (01:24~09:32, 3,119회 연속 미검출 후 자연 해소).
  → bar 미확인 상태의 미검출 허용을 nobar_max_miss 로 축소, 폴백 스팸 금지.
- 탭 적중률 27%의 주범은 계통 지연 미보정: (a) 샘플 시각을 캡처 '종료'로 기록,
  (b) audit 캡처가 sleep~press 사이에 끼어 실제 탭을 캡처 1회분(~0.8s) 지연,
  (c) input_delay 0.10s 는 adb input tap 실측 지연 대비 과소.
  → (a) capture_grab_frac 로 프레임 취득 시점 추정, (b) audit 캡처를 press 이후로
  이동, (c) press 소요를 실측 EMA 로 자동 보정(_PRESS_LAT).
- dt~0.8s 로 반주기(1.4~2.1s)에 근접해 3점 외삽이 앨리어싱에 취약
  → 4번째 샘플로 fold 역예측 검증(est_verify_tol) 후 불합격 추정 폐기.

감속-정지 역학 (26.07 사용자 확인):
- Disarm 탭 후 커서는 즉시 멈추지 않고 약 1초 이내 감속하며 정지하고,
  판정은 '정지 위치'가 안전구간 안인지로 결정된다.
- 따라서 조준은 주입 순간이 아니라 정지 위치가 중심에 오도록 해야 한다.
  선형 감속 가정 시 정지거리 D = v*stop_time/2 → 리드 = stop_time/2 (속도 무관 상수).
- 리드만큼 가까운 구간이 실행 불가가 되므로 plan_tap 은 '실행 가능한' 후보 중
  최선을 고르고, 없으면 한 주기 뒤 후보까지 본다(pw_thresh 상향과 세트).
- 탭 직후 프레임을 감속 모델로 역산해 정지 위치를 추정하고, 목표중심과의
  오프셋을 EMA(_STOP_LEAD)로 되먹여 리드를 자동 보정한다. 이 신호는 press 지연
  오차·프레임 취득 시점 오차·감속 편차를 한 관측치로 흡수한다.

운영하며 보완할 값은 DisarmConfig 에 모아두었다(실측 재수집 후 튜닝).
"""
import time
import numpy as np
import cv2


class DisarmConfig:
    """운영 튜닝 파라미터 (실데이터 확보 후 조정). 인스턴스로 복제해 덮어쓰기 가능."""
    # --- 타이밍 ---
    sample_interval = 0.0      # 샘플 간 추가 대기(s). 0=캡처 속도대로(권장, Δt=캡처비용)
    input_delay = 0.35         # press(adb input tap) 소요 초기 추정(s). 첫 탭 이후 실측 EMA 로 대체.
    press_inject_lead = 0.05   # input 명령 완료 직전에 실제 탭이 주입된다고 보는 리드(s)
    press_ema_alpha = 0.35     # press 소요 실측 EMA 계수
    capture_grab_frac = 0.6    # 캡처 시간창에서 프레임 취득 시점 추정 비율(0=시작, 1=종료)
    capture_dt_prior = 0.8     # 첫 샘플 전 캡처 주기 사전값(s). 실측 median 0.81 기반.
                               # (기존 0.25는 2번째 샘플의 연속성 필터 반경을 과소하게 만들었음)
    pw_thresh = 2.6            # 실행가능 최소시점부터 이 시간 이내 도달하는 후보만 노림(s).
                               # 정지 리드 때문에 가까운 후보가 자주 탈락하므로 한 주기(≈3.3s) 안에서
                               # 다음 교차가 항상 창에 들어오도록 1.5→2.6 상향.
    # --- 감속-정지 (판정은 '정지 위치' 기준: 사용자 확인) ---
    stop_time = 0.0            # 탭 주입~정지까지 시간 추정(s). 0이면 비활성(즉시 정지 판정 기준).
    stop_lead_alpha = 0.30     # 정지위치 오프셋 EMA 로 리드를 자동 보정하는 계수
    stop_adj_step_max = 0.08   # 1회 보정 한도(s)
    stop_adj_total_max = 0.35  # 누적 보정 한도(s, 초기 리드 대비 ±)
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
    est_verify_tol = 80.0      # 4번째 샘플 fold 역예측 검증 허용 잔차(px). 초과 시 추정 폐기.
    # --- 안전/폴백 ---
    max_total_samples = 40     # 전체 캡처 상한(무한루프 방지)
    max_consecutive_miss = 6   # (막대를 한 번이라도 본 뒤) 연속 검출 실패 허용
    nobar_max_miss = 2         # 막대를 한 번도 못 본 상태의 미검출 허용. 초과 시 비게임 화면으로 보고 즉시 반환.
    bypass_fast_game = False   # [옵션] 빠른(어려운) 게임은 폴백으로 우회 (사용자 선택)
    fast_game_k = 2.5          # 반주기 < fast_game_k*Δt 이면 '빠른 게임'으로 판정
    fast_game_fail_limit = 3   # 빠른게임 판정/실패가 이만큼 누적되면 폴백 트리거
    settle_after_tap = 1.0     # 탭 후 결과 안정 대기(s)
    # 입력 좌표: 게임은 막대가 아니라 고정 'Disarm' 버튼을 누른다(기존 script.py disarm=[515,934]).
    # 커서 x는 '언제 누를지' 타이밍 판단용일 뿐, 실제 탭은 이 버튼. 통합 시 오버라이드.
    disarm_button = (515, 934)


# press(adb input tap) 소요 실측 EMA. 세션(프로세스) 단위로 유지되어
# 상자마다 새 SmartDisarm 인스턴스를 만들어도 보정값이 승계된다.
_PRESS_LAT = {"ema": None}

# 정지 리드(stop_time/2)에 대한 세션 보정치(s). 탭 직후 프레임에서 역산한
# '정지 위치 - 목표중심' 오프셋을 되먹여 계통 잔차를 자동 흡수한다.
_STOP_LEAD = {"adj": 0.0}


def note_press_duration(dur, alpha=0.35):
    """press(adb input tap) 실측 소요를 EMA 에 공급. script.py 의 일반 Press() 가
    상시 호출해 미니게임 첫 탭 전에 지연 추정을 예열(pre-seed)한다."""
    if dur <= 0 or dur > 3.0:   # 타임아웃/복구가 섞인 이상치는 제외
        return
    ema = _PRESS_LAT["ema"]
    _PRESS_LAT["ema"] = dur if ema is None else (1 - alpha) * ema + alpha * dur


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

    @staticmethod
    def _propagate(x, v, d, dt, xmin, xmax):
        """(x, 속도v, 방향d)에서 dt초 후(음수면 과거) 위치와 그 시점의 진행 방향.
        끝점 반사(triangle fold) 반영. 반환: (pos, dir).
        시간 역행(dt<0)은 방향 반전 재생과 같으므로 결과 방향을 되반전해 돌려준다."""
        rev = dt < 0
        if rev:
            d, dt = -d, -dt
        span = float(xmax - xmin)
        if span <= 0 or v <= 0 or d == 0:
            return float(x), (-d if rev else d)
        p0 = float(x) - xmin
        if d < 0:                      # 왼쪽 진행은 거울 변환으로 오른쪽 진행에 귀결
            p0 = span - p0
        u = (p0 + v * dt) % (2.0 * span)
        if u < 0:
            u += 2.0 * span
        if u > span:
            pos, dend = 2.0 * span - u, -1
        else:
            pos, dend = u, +1
        if d < 0:                      # 거울 복원
            pos, dend = span - pos, -dend
        if rev:
            dend = -dend
        return xmin + pos, dend

    def _est_consistent(self, est, samples, xmin, xmax):
        """dt가 반주기에 근접하면 3점 외삽이 앨리어싱으로 오염될 수 있다.
        직전(4번째) 샘플을 fold 역예측해 잔차가 크면 추정을 폐기한다."""
        t_prev, x_prev = samples[-4]
        dt_back = t_prev - samples[-1][0]
        pred, _d = self._propagate(est["x"], est["speed"], est["dir"], dt_back, xmin, xmax)
        return abs(pred - x_prev) <= self.cfg.est_verify_tol

    def reach_time(self, x, v, d, c, xmin, xmax):
        """현재(x,방향d,속도v)에서 목표 c 도달까지 시간. 끝점 반전 고려(전역 예측)."""
        if d > 0:
            return (c - x) / v if c >= x else ((xmax - x) + (xmax - c)) / v
        else:
            return (x - c) / v if c <= x else ((x - xmin) + (c - xmin)) / v

    def plan_tap(self, est, safes, xmin, xmax, dt, min_reach=0.0):
        """실행 가능한(reach >= min_reach) 후보 중 가장 이른 도달을 선택.
        정지 리드 때문에 가까운 교차가 실행 불가면 다음 주기 후보까지 본다.
        반환: 목표·margin·reach 또는 None."""
        x, v, d = est["x"], est["speed"], est["dir"]
        period = 2.0 * (xmax - xmin) / v
        best = None
        for k in (0, 1):
            for (a, b) in safes:
                c = (a + b) / 2
                half = (b - a) / 2
                margin = max(self.cfg.margin_min, half * self.cfg.margin_ratio
                             + self.cfg.margin_speed_k * v * dt)
                tt = self.reach_time(x, v, d, c, xmin, xmax) + k * period
                if tt < min_reach or tt > min_reach + self.cfg.pw_thresh:
                    continue
                if best is None or tt < best["reach"]:
                    best = {"reach": tt, "center": c, "half": half, "margin": margin}
            if best is not None:
                break
        return best

    # ===================== 메인 루프 =====================
    def run(self):
        cfg = self.cfg
        samples = []          # [(t, x)] 검출 성공만
        prev_x = None
        v_est = 0.0
        last_dt = cfg.sample_interval or cfg.capture_dt_prior
        shots = 0
        miss = 0
        fast_hits = 0
        bar_seen = False      # 이번 실행에서 막대/안전구간을 한 번이라도 검출했는가
        last_safes = None
        last_range = None
        self.log.info(self._t("스마트 개봉 시작..."))
        # 평가용 보정 상태 스냅숏: 이 상자의 첫 탭이 어떤 보정값으로 조준되는지 기록
        self.log.debug(self._t("보정 상태: press EMA={a}, 정지리드={b:.3f}s(adj {c:+.3f}), grab_frac={d}, stop_time={e}s")
                       .format(a=(("%.3f s" % _PRESS_LAT["ema"]) if _PRESS_LAT["ema"] is not None else "미실측"),
                               b=self._stop_lead(), c=_STOP_LEAD["adj"],
                               d=cfg.capture_grab_frac, e=cfg.stop_time))
        if self.audit: self.audit.on_start()

        while shots < cfg.max_total_samples:
            t0 = self.now()
            img = self.cap()
            t1 = self.now()
            # 프레임 취득은 캡처 시간창의 중후반(프로세스 기동 후, 전송 전)에 일어난다.
            # 종료 시각을 그대로 쓰면 측정 시각이 계통적으로 늦어져 탭이 통째로 늦는다.
            t = t0 + cfg.capture_grab_frac * (t1 - t0)
            shots += 1

            if img is None:
                miss += 1
                if miss > cfg.max_consecutive_miss:
                    return self._give_up("캡처 연속 실패")
                continue

            # 게임 종료 판정: 첫 캡처(오호출 즉시 반환)에서만 무조건 확인한다.
            # 미니게임은 우리 탭 없이는 끝나지 않으므로 정상 샘플링 중에는 검사하지 않고
            # (전체 화면 매칭 2회 = 루프당 ~0.2s 절약), 막대가 소실됐을 때만 재확인한다.
            if shots == 1 and self.is_done and self.is_done(img):
                self.log.info(self._t("개봉 완료/화면 전환 감지. 종료."))
                if self.audit:
                    self.audit.on_result(self._t("종료(즉시)"))
                self._audit_end_frame(img)
                return True

            d = self.detect(img)
            if not d or len(d["safes"]) == 0:
                if shots > 1 and self.is_done and self.is_done(img):
                    self.log.info(self._t("막대 소실 + 화면 전환 감지. 종료."))
                    if self.audit:
                        self.audit.on_result(self._t("종료(막대 소실)"))
                    self._audit_end_frame(img)
                    return True
                miss += 1
                # 막대를 한 번도 못 봤다면 미니게임 화면이 아닐 공산이 크다(상자 UI 잔류 등).
                # 이 경우 빠르게 반환해야 상위(StateChest)가 복구를 진행할 수 있다.
                # (실측: 미검출 7회 대기+폴백 스팸을 반복하다 한 상자에서 약 8시간 연속 스턱)
                limit = cfg.max_consecutive_miss if bar_seen else cfg.nobar_max_miss
                if miss > limit:
                    if not bar_seen:
                        self.press(list(cfg.disarm_button))   # 게이지 시작/진행 유도 1회만
                        return self._give_up("막대 미검출(비게임 화면 추정)", allow_fallback=False)
                    return self._give_up("막대/안전구간 미검출")
                continue
            bar_seen = True
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
            if est is not None and len(samples) >= 4 and not self._est_consistent(est, samples, xmin, xmax):
                self.log.debug(self._t("추정 검증 실패(4점 fold 잔차 초과). 재측정."))
                est = None
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

            # 판정은 '정지 위치' 기준: 주입 후에도 커서가 v*stop_time/2 만큼 미끄러지므로
            # 그만큼(정지 리드) 이르게 탭해야 한다. 리드 때문에 실행 불가해진 가까운 후보는
            # plan_tap 이 걸러내고 다음 주기 후보로 대체한다.
            elapsed_now = self.now() - t
            min_reach = elapsed_now + self._press_latency() + self._stop_lead() + 0.05
            plan = self.plan_tap(est, last_safes, xmin, xmax, last_dt, min_reach=min_reach)
            if plan is None:
                self._pace(t0)
                continue

            # press_wait: 마지막 측정(t) 기준. 경과 + press 지연(실측 EMA) + 정지 리드 보정.
            elapsed_since_meas = self.now() - t
            press_wait = plan["reach"] - elapsed_since_meas - self._press_latency() - self._stop_lead()
            if press_wait <= 0:
                self._pace(t0)                  # 이미 지남 → 다음 기회
                continue
            if press_wait > cfg.pw_thresh + 0.1:
                self._pace(t0)                  # 계획 오차 방어선(정상적으론 도달하지 않음)
                continue

            # 탭 실행. press 앞에는 어떤 작업(캡처 등)도 끼우지 않는다 — 전부 탭 지연이 된다.
            time.sleep(press_wait)
            p0 = self.now()
            self.press(list(self.cfg.disarm_button))   # 타이밍 맞춰 고정 Disarm 버튼 탭
            p1 = self.now()
            self._update_press_latency(p1 - p0)
            self.log.info(self._t("개봉 탭: 목표구간중심x={a:.0f} margin={b:.0f} pw={c:.3f}s 속도={d:.0f}px/s press={e:.3f}s 리드={f:.3f}s")
                          .format(a=plan["center"], b=plan["margin"], c=press_wait, d=est["speed"],
                                  e=p1 - p0, f=self._stop_lead()))

            # 탭 직후 프레임: 정지위치 역산(리드 자동보정) + audit + 조기 종료판정 겸용
            aimg = None
            a_content = None
            if self.audit or self.is_done:
                a0 = self.now()
                aimg = self.cap()
                a1 = self.now()
                a_content = a0 + cfg.capture_grab_frac * (a1 - a0)
            meas = self._measure_after_tap(aimg, a_content, p0, p1, samples[-1][0],
                                           est, last_safes, (xmin, xmax))
            if meas is not None:
                self._update_stop_lead(meas, plan)
            if self.audit:
                try:
                    self.audit.on_tap(aimg, (meas["measured"] if meas else None), plan, est,
                                      last_safes, (xmin, xmax),
                                      backcast_x=(meas["settle"] if meas else None))
                except Exception as e:
                    self.log.warning(self._t("[audit] 탭 기록 실패: {a}").format(a=e))
            if self.is_done and aimg is not None and self.is_done(aimg):
                # 주의: '종료'는 함정 발동으로 끝난 경우도 포함한다(실제 회피 여부는 종료 프레임으로 판별).
                self.log.info(self._t("개봉 종료 감지."))
                if self.audit: self.audit.on_result(self._t("종료"))
                self._audit_end_frame(aimg)
                return True

            rest = cfg.settle_after_tap - (self.now() - p1)
            if rest > 0:
                time.sleep(rest)
            after = self.cap()
            if self.is_done and after is not None and self.is_done(after):
                self.log.info(self._t("개봉 종료 감지."))
                if self.audit: self.audit.on_result(self._t("종료"))
                self._audit_end_frame(after)
                return True
            # 아직 진행 중이면 상태 리셋하고 계속 (함정이 여러 단계일 수 있음)
            samples.clear(); prev_x = None; v_est = 0.0

        return self._give_up("샘플 상한 초과")

    def _measure_after_tap(self, aimg, a_content, p0, p1, t_meas, est, safes, rng):
        """탭 직후 프레임에서 커서를 측정하고, 감속 모델(선형, stop_time)로
        '주입 시점 위치'와 '정지 위치'를 추정. 반환 dict(measured, inject, settle, dir_tap, v) 또는 None."""
        try:
            if aimg is None or a_content is None:
                self.log.debug(self._t("[측정] 탭 후 프레임 없음 → 보정 생략."))
                return None
            d = self.detect(aimg)
            if not d:
                self.log.debug(self._t("[측정] 탭 후 막대 미검출(화면 전환 중 추정) → 보정 생략."))
                return None
            # 자물쇠가 이미 넘어가 구간 배치가 달라졌다면 이 프레임은 비교 불가
            if len(d["safes"]) != len(safes) or any(
                    abs(na - oa) > 12 or abs(nb - ob) > 12
                    for (na, nb), (oa, ob) in zip(d["safes"], safes)):
                self.log.debug(self._t("[측정] 안전구간 배치 변화(다음 자물쇠 추정) → 보정 생략."))
                return None
            # 막대 범위 안의 폭 필터 통과 후보가 정확히 1개일 때만 채택.
            # (범위 밖 흰 UI 거짓양성/다중 후보로 인한 오염 방지. 애매하면 측정 포기.)
            bx0, bx1 = d["bar"]
            cand = [x for (x, w) in d["cursors"]
                    if self.cfg.cursor_w_min <= w <= self.cfg.cursor_w_max and bx0 <= x <= bx1]
            if len(cand) != 1:
                self.log.debug(self._t("[측정] 커서 후보 {a}개(1개 아님) → 보정 생략.").format(a=len(cand)))
                return None
            measured = int(cand[0])
            v = est["speed"]
            Ts = max(1e-3, self.cfg.stop_time)
            tap_time = p0 + max(0.0, (p1 - p0) - self.cfg.press_inject_lead)
            # est 방향은 마지막 샘플 시점 기준 → 주입 시점 방향을 전방 전파로 구한다
            # (반사 홀수 회 개입 시 방향 반전. 감속 중에는 방향이 유지된다고 가정.)
            _px, dir_tap = self._propagate(est["x"], v, est["dir"],
                                           tap_time - t_meas, rng[0], rng[1])
            # 주입 후 경과 t_rel 동안의 감속 이동거리(선형 감속: 속도 v → 0, 소요 Ts)
            t_rel = max(0.0, a_content - tap_time)
            tt = min(t_rel, Ts)
            travel = v * (tt - tt * tt / (2.0 * Ts))     # 주입~프레임 이동거리(px)
            total = v * Ts / 2.0                         # 주입~정지 총 이동거리(px)
            # _propagate 로 fold 유지 이동: speed=거리, dt=±1s 로 '거리만큼' 전/후진
            inject, _d1 = self._propagate(measured, travel, dir_tap, -1.0, rng[0], rng[1])
            settle, _d2 = self._propagate(measured, max(0.0, total - travel), dir_tap, 1.0,
                                          rng[0], rng[1])
            return {"measured": measured, "inject": inject, "settle": settle,
                    "dir_tap": dir_tap, "v": v}
        except Exception as e:
            self.log.warning(self._t("[audit] 탭 후 측정 실패: {a}").format(a=e))
            return None

    # ===================== 보조 =====================
    def _pace(self, t0):
        if self.cfg.sample_interval > 0:
            rest = self.cfg.sample_interval - (self.now() - t0)
            if rest > 0:
                time.sleep(rest)

    def _press_latency(self):
        """press 명령 발행~실제 탭 주입까지 예상 지연(s). 실측 EMA 우선, 없으면 초기값."""
        base = _PRESS_LAT["ema"] if _PRESS_LAT["ema"] is not None else self.cfg.input_delay
        return max(0.05, base - self.cfg.press_inject_lead)

    def _stop_lead(self):
        """정지 리드(s): 주입 후 정지까지 커서가 더 미끄러지는 시간거리 보상.
        선형 감속 가정 시 stop_time/2. 세션 보정치(_STOP_LEAD)로 계통 잔차를 흡수한다."""
        if self.cfg.stop_time <= 0:
            return 0.0
        return max(0.0, self.cfg.stop_time / 2.0 + _STOP_LEAD["adj"])

    def _update_stop_lead(self, meas, plan):
        """정지 위치 추정 - 목표중심 오프셋(진행방향 부호)을 EMA 로 되먹여 리드 자동 보정.
        (+)면 목표를 지나 멈춤 = 탭이 늦음 → 리드 증가. press 지연 오차·프레임 시점
        오차·감속 편차가 모두 이 한 관측치로 흡수된다."""
        if self.cfg.stop_time <= 0:
            return
        err_px = (meas["settle"] - plan["center"]) * meas["dir_tap"]
        if abs(err_px) > plan["half"] + 150:     # 반사/오검출 개연성이 큰 대편차는 제외
            return
        step = self.cfg.stop_lead_alpha * err_px / max(1.0, meas["v"])
        step = max(-self.cfg.stop_adj_step_max, min(self.cfg.stop_adj_step_max, step))
        adj = max(-self.cfg.stop_adj_total_max,
                  min(self.cfg.stop_adj_total_max, _STOP_LEAD["adj"] + step))
        _STOP_LEAD["adj"] = adj
        self.log.debug(self._t("정지위치 오프셋 {a:+.0f}px → 리드 보정 {b:+.3f}s (누적 {c:+.3f}s)")
                       .format(a=err_px, b=step, c=adj))

    def _update_press_latency(self, dur):
        note_press_duration(dur, self.cfg.press_ema_alpha)
        if _PRESS_LAT["ema"] is not None:
            self.log.debug(self._t("press 지연 실측 {a:.3f}s (EMA {b:.3f}s)")
                           .format(a=dur, b=_PRESS_LAT["ema"]))

    def _audit_end_frame(self, img):
        """종료(결과/전환) 프레임을 audit 에 저장 - 실제 함정 발동 여부의 라벨링 근거."""
        try:
            if self.audit and hasattr(self.audit, "on_end_frame"):
                self.audit.on_end_frame(img)
        except Exception:
            pass

    def _do_fallback(self, reason):
        self.log.info(self._t("폴백 실행({a}).").format(a=reason))
        if self.fallback:
            if self.audit: self.audit.on_result(self._t("폴백: ") + reason)
            self.fallback()
            return True
        return self._give_up(reason + self._t(" (폴백 미설정)"))

    def _give_up(self, reason, allow_fallback=True):
        self.log.warning(self._t("스마트 개봉 중단: {a}").format(a=reason))
        if self.audit: self.audit.on_result(self._t("중단: ") + reason)
        if allow_fallback and self.cfg.bypass_fast_game and self.fallback:
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
    print(f"  등속 추정: {est}  (기대 speed~500 dir=+1)")
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
