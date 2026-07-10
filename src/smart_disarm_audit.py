"""smart_disarm_audit.py - 스마트 개봉 audit (개발/검증 전용)

[제거 방법] 개발이 끝나면 이 파일 하나만 삭제하면 audit 전체가 사라진다.
smart_disarm.py 는 이 모듈을 선택적으로 import 하므로, 파일이 없으면 auditor=None 이 되어
모든 audit hook 이 no-op 으로 동작한다(본체 기능에는 영향 없음).

기능:
- A. 결과 요약 로그   : 개봉 종료 시 결과/캡처수/탭수 한 줄 요약 (logger)
- B. 오버레이 캡처    : 탭 시점 화면에 검출(안전구간/목표/margin/추정·실제 커서)을 그려 저장
- C. 샘플별 debug 로그: 매 측정 t/x/속도/방향, 추정값 (logger, debug)

[저장 위치]
- 오버레이 이미지(B): audit/smart_disarm/disarm_<tag>_<tap>_<hit|miss>.png  (프로젝트 루트 기준)
- 요약/샘플 로그(A,C): 기존 logger 경유 -> logs/log_*.txt + GUI 로그창
"""
import os
import glob
import time
import cv2
from datetime import datetime


class SmartDisarmAuditor:
    def __init__(self, logger, out_dir="audit/smart_disarm",
                 capture=True, sample_log=True, _=None):
        self.log = logger
        self.out_dir = out_dir
        self.capture = capture
        self.sample_log = sample_log
        self._t = _ or (lambda s: s)
        self.shots = 0
        self.tap_count = 0
        self.tag = "init"
        if self.capture:
            try:
                os.makedirs(out_dir, exist_ok=True)
            except Exception as e:
                self.log.warning(self._t("[audit] 출력 폴더 생성 실패: {a}").format(a=e))
                self.capture = False
        if self.capture:
            try:
                # 무한 증식 방지. 개수 기준으로 지우면 진행 중인 평가 세션의 초기 프레임까지
                # 지울 수 있으므로, 로그 보존 정책과 동일한 3일 age 기준 + 넉넉한 상한을 쓴다.
                now = time.time()
                files = sorted(glob.glob(os.path.join(out_dir, "disarm_*.png")),
                               key=os.path.getmtime)
                drop = [f for f in files if now - os.path.getmtime(f) > 3 * 86400]
                keep_cnt = len(files) - len(drop)
                if keep_cnt > 2000:
                    fresh = [f for f in files if f not in drop]
                    drop += fresh[:keep_cnt - 2000]
                for f in drop:
                    os.remove(f)
            except Exception as e:
                self.log.warning(self._t("[audit] 오래된 파일 정리 실패: {a}").format(a=e))

    # --- hooks (smart_disarm.SmartDisarm 가 호출) ---
    def on_start(self):
        self.shots = 0
        self.tap_count = 0
        # datetime.now()는 audit 전용 파일명 태그용 (본체는 주입된 now_fn 사용)
        self.tag = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log.info(self._t("[audit] 스마트 개봉 시작 (tag={a})").format(a=self.tag))

    def on_sample(self, t, x, v, d):
        self.shots += 1
        if self.sample_log:
            self.log.debug(self._t("[audit] sample t={a:.3f} x={b} v={c:.0f} dir={d}")
                           .format(a=t, b=x, c=v, d=d))

    def on_estimate(self, est):
        if est and self.sample_log:
            self.log.debug(self._t("[audit] est x={a:.0f} speed={b:.0f} dir={c}")
                           .format(a=est["x"], b=est["speed"], c=est["dir"]))

    def on_tap(self, img, actual_cursor_x, plan, est, safes, rng, backcast_x=None):
        """actual_cursor_x: 탭 직후 프레임의 실측 커서(감속 중).
        backcast_x: 감속 모델로 추정한 '정지 위치' — 게임 판정 기준이므로 hit/miss 도 이것으로 라벨링."""
        self.tap_count += 1
        hit = None
        c, half, margin = plan["center"], plan["half"], plan["margin"]
        judge_x = backcast_x if backcast_x is not None else actual_cursor_x
        if judge_x is not None:
            hit = abs(judge_x - c) <= max(2.0, half - margin)
        self.log.info(self._t("[audit] 탭 #{a}: 목표x={b:.0f} 정지추정x={c} 실측커서x={e} 적중={d}")
                      .format(a=self.tap_count, b=c,
                              c=(round(backcast_x) if backcast_x is not None else "?"),
                              e=(actual_cursor_x if actual_cursor_x is not None else "?"),
                              d=("O" if hit else ("X" if hit is not None else "?"))))
        if self.capture and img is not None:
            self._save_overlay(img, actual_cursor_x, plan, est, safes, rng, hit, backcast_x)

    def on_result(self, result):
        self.log.info(self._t("[audit] 결과: {a} | 유효샘플 {b}건 | 탭 {c}회 (tag={d})")
                      .format(a=result, b=self.shots, c=self.tap_count, d=self.tag))

    def on_end_frame(self, img):
        """종료(결과/전환) 시점의 전체 프레임 저장.
        '종료'는 함정 발동으로 끝난 경우를 포함하므로, 실제 회피 성공 여부를
        사후 라벨링할 수 있는 유일한 근거가 이 프레임이다."""
        if self.capture and img is not None:
            try:
                cv2.imwrite(os.path.join(self.out_dir, f"disarm_{self.tag}_end.png"), img)
            except Exception as e:
                self.log.warning(self._t("[audit] 종료 프레임 저장 실패: {a}").format(a=e))

    # --- 오버레이 그리기 ---
    def _save_overlay(self, img, cur_x, plan, est, safes, rng, hit, backcast_x=None):
        try:
            vis = img[0:180].copy()
            c = int(plan["center"]); half = plan["half"]; margin = plan["margin"]
            for (a, b) in safes:                                   # 안전구간(분홍)
                cv2.rectangle(vis, (int(a), 5), (int(b), 170), (255, 0, 255), 1)
            lo, hi = int(c - max(2.0, half - margin)), int(c + max(2.0, half - margin))
            cv2.rectangle(vis, (lo, 30), (hi, 145), (0, 255, 0), 1)  # 허용영역(초록)
            cv2.line(vis, (c, 0), (c, 179), (0, 255, 255), 1)        # 목표중심(노랑)
            cv2.line(vis, (int(est["x"]), 0), (int(est["x"]), 179), (255, 128, 0), 1)  # 추정커서(파랑)
            if cur_x is not None:                                   # 탭 직후 실측커서(청록, 얇게)
                cv2.line(vis, (int(cur_x), 0), (int(cur_x), 179), (200, 200, 0), 1)
            if backcast_x is not None:                              # 정지위치 추정(적중 초록/빗나감 빨강)
                cv2.line(vis, (int(backcast_x), 0), (int(backcast_x), 179),
                         (0, 255, 0) if hit else (0, 0, 255), 2)
            lab = "unk" if hit is None else ("hit" if hit else "miss")
            name = f"disarm_{self.tag}_{self.tap_count}_{lab}.png"
            cv2.imwrite(os.path.join(self.out_dir, name), vis)
        except Exception as e:
            self.log.warning(self._t("[audit] 오버레이 저장 실패: {a}").format(a=e))


def make_auditor(logger, _=None, **kw):
    """smart_disarm 에서 호출하는 팩토리. 실패해도 None 반환(본체 보호)."""
    try:
        return SmartDisarmAuditor(logger=logger, _=_, **kw)
    except Exception:
        return None
