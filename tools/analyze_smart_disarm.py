# -*- coding: utf-8 -*-
"""스마트 상자 개봉(smart_disarm) audit 평가 스크립트.

파밍 세션 후 실행하면 logs/ 와 audit/smart_disarm/ 을 읽어 개선 효과를 집계한다.

    python tools/analyze_smart_disarm.py            (저장소 루트 기준 기본 경로)
    python tools/analyze_smart_disarm.py --logs <로그폴더> --img <이미지폴더>

집계 항목:
  1. 호출 결과 분포(종료/중단 사유), 스턱 가드 발동, 무막대 즉시 반환 빈도
  2. 탭 적중률 - 신형식(정지 위치 기준)과 구형식(개선 전 기준) 분리, 이미지 라벨 대조,
     게임 판정(ChallengeCheck) 성공률 + 차감 인식 내역 + 구식 환산(차감 인식 제외)
  2b. 폭별 성적 - 목표구간 폭(pw*속도) 대역별 게임 판정 성공률, 협소 우회 폭 분포
  3. 보정 궤적 - press EMA, 정지 리드 adj, 정지위치 오프셋 분포와 stop_time 조정 제안,
     측정 커버리지(보정이 실제 작동한 탭 비율)와 생략 사유
  4. 캡처 성능 - 샘플 간격 dt, [cap] 소켓/서브프로세스 캡처 시간 (개선 전 기준선 0.806s)
  5. 종료 프레임(_end.png) 인벤토리 - 실제 함정 발동 여부의 수동 라벨링 대상

개선 전 기준선(2026-07-01~02 실측): 탭 적중 27%(구 기준), 샘플 dt median 0.806s.

게임 판정(ChallengeCheck) 정직 기준선: 07-19 58% → 07-28 41%.
07-18 새벽의 '81%'는 smallgame_3 미스매치로 차감(4→3, 3→2) 실패를 세지 못하던
시기의 과대 측정이다(26.07-28 로그를 같은 척도로 재환산하면 83%). 과거 세션과의
비교는 반드시 '구식 환산(차감 인식 제외)' 지표끼리 한다.
"""
import os
import re
import sys
import glob
import argparse

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RE_TS      = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
RE_START   = re.compile(r"\[audit\] 스마트 개봉 시작 \(tag=(\S+)\)")
RE_RESULT  = re.compile(r"\[audit\] 결과: (.+?) \| (?:캡처 (\d+)장|유효샘플 (\d+)건) \| 탭 (\d+)회 \(tag=(\S+)\)")
RE_SAMPLE  = re.compile(r"\[audit\] sample t=([\d.]+) x=(\d+)")
RE_TAP_NEW = re.compile(r"\[audit\] 탭 #(\d+): 목표x=([\d.]+) 정지추정x=(\S+) 실측커서x=(\S+) 적중=(\S)")
RE_TAP_OLD = re.compile(r"\[audit\] 탭 #(\d+): 목표x=([\d.]+) 실제커서x=(\S+) 적중=(\S)")
RE_TAPLOG  = re.compile(r"개봉 탭: 목표구간중심x=([\d.]+) margin=([\d.]+) pw=([\d.]+)s 속도=([\d.]+)px/s"
                        r"(?: press=([\d.]+)s)?(?: 리드=([\d.]+)s)?")
RE_NARROW  = re.compile(r"안전구간 협소\((\d+(?:\.\d+)?)px <= (\d+(?:\.\d+)?)px\)")
RE_OFFSET  = re.compile(r"정지위치 오프셋 ([+-]?\d+)px.*리드 보정 ([+-][\d.]+)s \(누적 ([+-][\d.]+)s\)")
RE_SNAP    = re.compile(r"보정 상태: press EMA=(.+?), 정지리드=([\d.]+)s\(adj ([+-][\d.]+)\), "
                        r"grab_frac=([\d.]+), stop_time=([\d.]+)s")
RE_PRESS   = re.compile(r"press 지연 실측 ([\d.]+)s \(EMA ([\d.]+)s\)")
RE_CAP_S   = re.compile(r"\[cap\] socket ([\d.]+)s")
RE_CAP_P   = re.compile(r"\[cap\] subprocess ([\d.]+)s")
RE_SKIP    = re.compile(r"\[측정\] (.+?)(?:→| -) 보정 생략")
RE_CHANCE  = re.compile(r"기회 매칭 점수: (.+?) → 판독")
# 게임 판정(ChallengeCheck) 기준 성공/실패 — audit 라벨(추정 기반)과 달리 실제 게임 결과.
# 무차감 = 기회 N->N 인식 또는 sim 필터. 차감 인식(N->N-1)은 동반되는 '탭 실패' 로그로
# 집계되므로 여기서 세지 않는다(이중 계상 방지).
RE_CC_NC   = re.compile(r"기회 인식 결과: 탭 전 (\d)회 -> 탭 후 (\d)회")
RE_CC_SIM  = re.compile(r"자가 학습 필터링")
RE_CC_FAIL = re.compile(r"\[ChallengeCheck\] 탭 실패")

COUNT_KEYS = [
    ("상자 처리 300초 초과",            "상자 300초 가드 재시작"),
    ("스마트 개봉 연속",                "연속 실패 가드 재시작"),
    ("구식 연타 방식으로 전환",          "구식 연타 강등 발동"),
    ("개봉 가능한 캐릭터가 없습니다",     "전원 공포로 상자 포기"),
    ("막대 미검출(비게임 화면 추정)",     "무막대 즉시 반환"),
    ("추정 검증 실패(4점 fold",         "4점 검증으로 추정 폐기"),
    # 무측정 실패 보정 (26.07-16 개선: 고정 +0.05 → 조건·부호·크기 3중 제한)
    ("리드 보정치를 강제 상향",          "무측정 실패 보정 +0.05 (구형식)"),
    ("측정 공백 연속)! 리드 보정",       "무측정 실패 보정 적용(신형식)"),
    ("측정 공백 연속이 아니므로",         "무측정 실패 보정 생략(공백 연속 아님)"),
    ("보정 방향 근거가 없어",            "무측정 실패 보정 생략(방향 근거 없음)"),
    ("정지위치 보정이 이미 반영되어",      "실패 탭에 측정 보정 반영(강제 상향 생략)"),
    # 2프레임 정지 실측 + 실패 확정 재조준 (26.07-16 저녁 세션 판독 반영)
    ("2프레임 정지 확정",               "2프레임 정지 확정(실측 채택)"),
    ("2프레임 감속 실측",               "2프레임 감속시간 역산"),
    ("2프레임 역행",                    "2프레임 폐기(역행: 신규 커서)"),
    ("감속시간 해 없음",                "2프레임 폐기(감속 해 없음)"),
    ("후프레임 커서 불특정",             "2프레임 폐기(후프레임 커서 불특정)"),
    ("반사 개입 가능 구간",              "2프레임 폐기(반사 가드)"),
    ("후프레임 사용 불가",               "2프레임 불가(단일 외삽 유지)"),
    ("전프레임 사용 불가",               "2프레임 불가(후프레임 외삽)"),
    ("정지 실측 확정 → 재조준",          "실패 확정 재조준 적용"),
    ("추가 재조준은 생략",               "실패 확정 재조준 생략(이미 수렴)"),
]


def q(vals, p):
    if not vals:
        return float("nan")
    s = sorted(vals)
    i = min(len(s) - 1, max(0, int(round(p * (len(s) - 1)))))
    return s[i]


def parse_logs(log_dir):
    data = dict(results=[], taps_new=[], taps_old=[], taplogs=[], offsets=[],
                snaps=[], press=[], cap_s=[], cap_p=[], dts=[], skips={},
                chance_scores={}, cc=dict(ok=0, fail=0, ded={}, hours={}),
                counts={label: 0 for _, label in COUNT_KEYS},
                narrow=[], tap_widths=[])
    files = sorted(glob.glob(os.path.join(log_dir, "log_*.txt")))
    cur_tag, prev_t, last_speed = None, None, None
    # pending: 직전 '개봉 탭'의 목표구간 폭(pw*속도, px). 다음 게임 판정(무차감/sim/탭 실패)
    # 이 나오면 그 폭에 성적을 귀속시킨다. 차감 인식 라인(N->N-1)은 판정 확정이 아니라
    # 뒤따르는 '탭 실패' 라인이 확정이므로(이중 계상 방지와 동일 규약) pending 을 유지한다.
    pending = None
    for lf in files:
        try:
            fh = open(lf, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                # 마커 카운트는 어떤 정규식 continue 보다 먼저 수행한다
                # (예: "보정 생략" 계열은 RE_SKIP 이 continue 하므로 뒤에 두면 도달 불가).
                for key, label in COUNT_KEYS:
                    if key in line:
                        data["counts"][label] += 1
                m = RE_START.search(line)
                if m:
                    cur_tag, prev_t = m.group(1), None
                    continue
                m = RE_SAMPLE.search(line)
                if m:
                    t = float(m.group(1))
                    if prev_t is not None and 0 < t - prev_t < 3.0:
                        data["dts"].append(t - prev_t)
                    prev_t = t
                    continue
                m = RE_TAPLOG.search(line)
                if m:
                    rec = dict(center=float(m.group(1)), pw=float(m.group(3)),
                               speed=float(m.group(4)),
                               press=(float(m.group(5)) if m.group(5) else None),
                               lead=(float(m.group(6)) if m.group(6) else None))
                    data["taplogs"].append(rec)
                    last_speed = rec["speed"]
                    if pending is not None:
                        data["tap_widths"].append(dict(w=pending, outcome=None))
                    pending = rec["pw"] * rec["speed"]
                    continue
                m = RE_NARROW.search(line)
                if m:
                    data["narrow"].append(float(m.group(1)))
                    continue
                m = RE_TAP_NEW.search(line)
                if m:
                    data["taps_new"].append(dict(hit=m.group(5), tag=cur_tag))
                    continue
                m = RE_TAP_OLD.search(line)
                if m:
                    data["taps_old"].append(dict(hit=m.group(4), tag=cur_tag))
                    continue
                m = RE_OFFSET.search(line)
                if m:
                    data["offsets"].append(dict(px=int(m.group(1)), adj=float(m.group(3)),
                                                speed=last_speed))
                    continue
                m = RE_SNAP.search(line)
                if m:
                    data["snaps"].append(dict(ema=m.group(1), lead=float(m.group(2)),
                                              adj=float(m.group(3)), grab=float(m.group(4)),
                                              stop_time=float(m.group(5))))
                    continue
                m = RE_PRESS.search(line)
                if m:
                    data["press"].append(float(m.group(2)))
                    continue
                m = RE_CAP_S.search(line)
                if m:
                    data["cap_s"].append(float(m.group(1)))
                    continue
                m = RE_CAP_P.search(line)
                if m:
                    data["cap_p"].append(float(m.group(1)))
                    continue
                m = RE_SKIP.search(line)
                if m:
                    # 사유 문자열의 가변 수치(Δpx, 시간 범위, 후보 개수)를 정규화해
                    # 발생 건별 고유 키로 단편화되는 것을 막는다.
                    r = re.sub(r"[-+]?\d+(?:\.\d+)?", "N", m.group(1).strip())
                    data["skips"][r] = data["skips"].get(r, 0) + 1
                    continue
                m = RE_CHANCE.search(line)
                if m:
                    for pair in m.group(1).split():
                        k, _, sv = pair.partition("=")
                        try:
                            data["chance_scores"].setdefault(k, []).append(float(sv))
                        except ValueError:
                            pass
                    continue
                m = RE_CC_NC.search(line)
                if m or RE_CC_SIM.search(line) or RE_CC_FAIL.search(line):
                    hr = data["cc"]["hours"].setdefault(line[11:13], [0, 0])
                    outcome = None
                    if RE_CC_FAIL.search(line):
                        data["cc"]["fail"] += 1
                        hr[1] += 1
                        outcome = "fail"
                    elif m is None or m.group(1) == m.group(2):
                        data["cc"]["ok"] += 1
                        hr[0] += 1
                        outcome = "ok"
                    else:
                        k = "{}->{}".format(m.group(1), m.group(2))
                        data["cc"]["ded"][k] = data["cc"]["ded"].get(k, 0) + 1
                    if outcome and pending is not None:
                        data["tap_widths"].append(dict(w=pending, outcome=outcome))
                        pending = None
                    continue
                m = RE_RESULT.search(line)
                if m:
                    data["results"].append(dict(result=m.group(1),
                                                taps=int(m.group(4)), tag=m.group(5)))
                    if pending is not None:
                        data["tap_widths"].append(dict(w=pending, outcome=None))
                        pending = None
                    cur_tag, prev_t = None, None
    return data


def analyze_images(img_dir):
    labels = {"hit": 0, "miss": 0, "unk": 0}
    errs = []
    end_frames = []
    try:
        import cv2
        import numpy as np
    except ImportError:
        cv2 = None
    for f in sorted(glob.glob(os.path.join(img_dir, "disarm_*.png"))):
        base = os.path.basename(f)
        if base.endswith("_end.png"):
            end_frames.append(base)
            continue
        m = re.match(r"disarm_\d+_\d+_(\d+)_(hit|miss|unk)\.png", base)
        if not m:
            continue
        labels[m.group(2)] += 1
        if cv2 is None:
            continue
        img = cv2.imread(f)
        if img is None:
            continue
        # 오버레이 선은 상단 180px 에만 그어진다(신형 260px 저장본은 하단 80px 이
        # 기회 표시 원본). 판정선 검출은 상단 180px 기준으로 신구 저장본 모두 호환.
        img = img[0:180]
        b = img[:, :, 0].astype(int); g = img[:, :, 1].astype(int); r = img[:, :, 2].astype(int)
        H = img.shape[0]

        def full_cols(mask):
            cols = np.where(mask.sum(axis=0) >= H * 0.8)[0]
            if len(cols) == 0:
                return None
            return int(cols.mean())
        center = full_cols((b < 60) & (g > 200) & (r > 200))            # 노랑: 목표중심
        judged = full_cols((b < 60) & (g < 60) & (r > 200))             # 빨강: 빗나감 판정선
        if judged is None:
            judged = full_cols((b < 60) & (g > 200) & (r < 60))         # 초록: 적중 판정선
        if center is not None and judged is not None:
            errs.append(abs(judged - center))
    return labels, errs, end_frames


def main():
    ap = argparse.ArgumentParser(description="smart_disarm audit 평가")
    ap.add_argument("--logs", default=os.path.join(REPO_ROOT, "logs"))
    ap.add_argument("--img", default=os.path.join(REPO_ROOT, "audit", "smart_disarm"))
    args = ap.parse_args()

    d = parse_logs(args.logs)
    labels, errs, ends = analyze_images(args.img)

    print("=" * 62)
    print("스마트 개봉 audit 평가  (기준선: 적중 27%, dt 0.806s)")
    print("게임 판정 정직 기준선: 07-19 58% / 07-28 41%")
    print("('81%'는 차감 인식 불능기의 과대 측정 - 과거 비교는 구식 환산 지표로만)")
    print("=" * 62)

    print("\n[1] 호출 결과")
    res_cnt = {}
    for r in d["results"]:
        key = r["result"].split(":")[0].split("(")[0].strip()
        res_cnt[key] = res_cnt.get(key, 0) + 1
    if res_cnt:
        for k, v in sorted(res_cnt.items(), key=lambda x: -x[1]):
            print(f"  {k}: {v}회")
    else:
        print("  데이터 없음")
    for label, v in d["counts"].items():
        if v:
            print(f"  {label}: {v}회")

    print("\n[2] 탭 적중률")
    for name, taps in (("신형식(정지 위치 기준)", d["taps_new"]),
                       ("구형식(개선 전 기록)", d["taps_old"])):
        if taps:
            o = sum(1 for t in taps if t["hit"] == "O")
            x = sum(1 for t in taps if t["hit"] == "X")
            u = len(taps) - o - x
            base = o + x
            rate = (100.0 * o / base) if base else float("nan")
            print(f"  {name}: O {o} / X {x} / ? {u}  적중 {rate:.0f}%")
        else:
            print(f"  {name}: 데이터 없음")
    total_img = sum(labels.values())
    if total_img:
        judged = labels["hit"] + labels["miss"]
        rate = (100.0 * labels["hit"] / judged) if judged else float("nan")
        print(f"  이미지 라벨: hit {labels['hit']} / miss {labels['miss']} / unk {labels['unk']}"
              f"  적중 {rate:.0f}%")
    if errs:
        print(f"  이미지 |판정선-목표| 오차: median {q(errs,0.5):.0f}px"
              f" (p25 {q(errs,0.25):.0f} / p75 {q(errs,0.75):.0f}, n={len(errs)})")
    if d["chance_scores"]:
        parts = []
        for k in ["4", "3", "2", "1"]:
            vs = d["chance_scores"].get(k)
            if vs:
                parts.append(f"{k}: med {q(vs,0.5):.2f} max {max(vs):.2f} (n={len(vs)})")
        print("  기회 템플릿 매칭 최고점(문턱 0.85): " + " | ".join(parts))
    cc = d["cc"]
    cc_total = cc["ok"] + cc["fail"]
    if cc_total:
        print(f"  게임 판정(ChallengeCheck) 기준: 성공 {cc['ok']} / 실패 {cc['fail']}"
              f"  성공률 {100.0 * cc['ok'] / cc_total:.0f}%")
        parts = [f"{hh}시 {100 * o // (o + x)}%({o}/{x})"
                 for hh, (o, x) in sorted(cc["hours"].items()) if o + x]
        print("  시간대별: " + " ".join(parts))
        ded_n = sum(cc["ded"].values())
        if ded_n:
            parts = " ".join(f"{k} {v}건" for k, v in sorted(cc["ded"].items(), reverse=True))
            print(f"  차감 인식: {ded_n}건 ({parts})")
        # 구식 환산: smallgame_3 미스매치로 차감을 못 세던 시절(<= 07-18 새벽 '81%')과
        # 같은 척도. 실패에서 차감 인식분을 제외해 당시 계측을 재현한다.
        legacy_fail = max(0, cc["fail"] - ded_n)
        legacy_total = cc["ok"] + legacy_fail
        if legacy_total:
            print(f"  구식 환산(차감 인식 제외): 성공 {cc['ok']} / 실패 {legacy_fail}"
                  f"  성공률 {100.0 * cc['ok'] / legacy_total:.0f}%"
                  f"  <- 07-18 이전 세션('81%')과 비교는 이 값으로")

    tw = [t for t in d["tap_widths"] if t["outcome"]]
    if tw or d["narrow"]:
        print("\n[2b] 폭별 성적(게임 판정, 목표구간 폭=pw*속도)")
    if tw:
        bands = [(0, 134), (134, 160), (160, 220), (220, 400), (400, float("inf"))]
        for lo, hi in bands:
            grp = [t for t in tw if lo <= t["w"] < hi]
            if not grp:
                continue
            okn = sum(1 for t in grp if t["outcome"] == "ok")
            label = f"{lo:.0f}~{hi:.0f}px" if hi != float("inf") else f"{lo:.0f}px+"
            print(f"  {label}: 판정 {len(grp)}건  성공률 {100.0 * okn / len(grp):.0f}%"
                  f" (성공 {okn} / 실패 {len(grp) - okn})")
        unj = len(d["tap_widths"]) - len(tw)
        if unj:
            print(f"  판정 미연결 탭: {unj}건 (탭 후 판정 라인 없이 종료)")
    if d["narrow"]:
        nv = d["narrow"]
        print(f"  협소 우회(폴백행, 판정 표본 제외): {len(nv)}건"
              f"  {min(nv):.0f}~{max(nv):.0f}px median {q(nv, 0.5):.0f}px"
              f"  (이산 분포가 연속화되면 게임 패치 신호)")

    print("\n[3] 보정 궤적")
    if d["snaps"]:
        s0, s1 = d["snaps"][0], d["snaps"][-1]
        print(f"  보정 스냅숏 {len(d['snaps'])}건: press EMA {s0['ema']} -> {s1['ema']},"
              f" 리드 {s0['lead']:.3f}s(adj {s0['adj']:+.3f}) -> {s1['lead']:.3f}s(adj {s1['adj']:+.3f})")
        stop_time = s1["stop_time"]
    else:
        print("  보정 스냅숏: 데이터 없음(다음 세션에서 수집)")
        stop_time = None
    if d["press"]:
        print(f"  press EMA 최종 {d['press'][-1]:.3f}s (표본 {len(d['press'])}건)")
    if d["offsets"]:
        px = [o["px"] for o in d["offsets"]]
        lag = [o["px"] / o["speed"] for o in d["offsets"] if o["speed"]]
        print(f"  정지위치 오프셋: median {q(px,0.5):+.0f}px"
              f" (p25 {q(px,0.25):+.0f} / p75 {q(px,0.75):+.0f}, n={len(px)})")
        if lag:
            ml = q(lag, 0.5)
            print(f"  시간 환산 지연: median {ml:+.3f}s")
            if stop_time is not None and abs(ml) > 0.05 and len(lag) >= 5:
                print(f"  제안: stop_time {stop_time:.2f} -> {stop_time + 2*ml:.2f}s"
                      f" (오프셋 중앙값이 0.05s 초과)")
        adj_last = d["offsets"][-1]["adj"]
        if abs(adj_last) >= 0.30:
            print(f"  주의: 리드 누적 보정 {adj_last:+.3f}s가 상한(0.35s) 부근. stop_time 재설정 필요.")
    else:
        print("  정지위치 오프셋: 데이터 없음")
    taps_total = len(d["taps_new"]) or None
    if taps_total and d["offsets"]:
        print(f"  측정 커버리지: {len(d['offsets'])}/{taps_total}탭"
              f" ({100.0*len(d['offsets'])/taps_total:.0f}%)")
    if d["skips"]:
        for r, v in sorted(d["skips"].items(), key=lambda x: -x[1]):
            print(f"  보정 생략({r}): {v}회")

    print("\n[4] 캡처 성능")
    if d["dts"]:
        print(f"  샘플 dt: median {q(d['dts'],0.5):.3f}s"
              f" (p10 {q(d['dts'],0.10):.3f} / p90 {q(d['dts'],0.90):.3f}, n={len(d['dts'])})"
              f"  [기준선 0.806s]")
    else:
        print("  샘플 dt: 데이터 없음")
    if d["cap_s"]:
        print(f"  소켓 캡처: median {q(d['cap_s'],0.5):.3f}s (n={len(d['cap_s'])})")
    if d["cap_p"]:
        print(f"  서브프로세스 폴백: median {q(d['cap_p'],0.5):.3f}s (n={len(d['cap_p'])})")

    print("\n[5] 종료 프레임(실제 함정 발동 여부 수동 라벨링 대상)")
    if ends:
        print(f"  {len(ends)}장 저장됨. 최근 5장:")
        for f in ends[-5:]:
            print(f"    {f}")
    else:
        print("  없음(다음 세션에서 수집)")
    print()


if __name__ == "__main__":
    main()
