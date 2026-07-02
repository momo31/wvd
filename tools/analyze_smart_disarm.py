# -*- coding: utf-8 -*-
"""스마트 상자 개봉(smart_disarm) audit 평가 스크립트.

파밍 세션 후 실행하면 logs/ 와 audit/smart_disarm/ 을 읽어 개선 효과를 집계한다.

    python tools/analyze_smart_disarm.py            (저장소 루트 기준 기본 경로)
    python tools/analyze_smart_disarm.py --logs <로그폴더> --img <이미지폴더>

집계 항목:
  1. 호출 결과 분포(종료/중단 사유), 스턱 가드 발동, 무막대 즉시 반환 빈도
  2. 탭 적중률 - 신형식(정지 위치 기준)과 구형식(개선 전 기준) 분리, 이미지 라벨 대조
  3. 보정 궤적 - press EMA, 정지 리드 adj, 정지위치 오프셋 분포와 stop_time 조정 제안,
     측정 커버리지(보정이 실제 작동한 탭 비율)와 생략 사유
  4. 캡처 성능 - 샘플 간격 dt, [cap] 소켓/서브프로세스 캡처 시간 (개선 전 기준선 0.806s)
  5. 종료 프레임(_end.png) 인벤토리 - 실제 함정 발동 여부의 수동 라벨링 대상

개선 전 기준선(2026-07-01~02 실측): 탭 적중 27%(구 기준), 샘플 dt median 0.806s.
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
RE_OFFSET  = re.compile(r"정지위치 오프셋 ([+-]?\d+)px.*리드 보정 ([+-][\d.]+)s \(누적 ([+-][\d.]+)s\)")
RE_SNAP    = re.compile(r"보정 상태: press EMA=(.+?), 정지리드=([\d.]+)s\(adj ([+-][\d.]+)\), "
                        r"grab_frac=([\d.]+), stop_time=([\d.]+)s")
RE_PRESS   = re.compile(r"press 지연 실측 ([\d.]+)s \(EMA ([\d.]+)s\)")
RE_CAP_S   = re.compile(r"\[cap\] socket ([\d.]+)s")
RE_CAP_P   = re.compile(r"\[cap\] subprocess ([\d.]+)s")
RE_SKIP    = re.compile(r"\[측정\] (.+?)(?:→| -) 보정 생략")

COUNT_KEYS = [
    ("상자 처리 300초 초과",            "상자 300초 가드 재시작"),
    ("스마트 개봉 연속",                "연속 실패 가드 재시작"),
    ("구식 연타 방식으로 전환",          "구식 연타 강등 발동"),
    ("개봉 가능한 캐릭터가 없습니다",     "전원 공포로 상자 포기"),
    ("막대 미검출(비게임 화면 추정)",     "무막대 즉시 반환"),
    ("추정 검증 실패(4점 fold",         "4점 검증으로 추정 폐기"),
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
                counts={label: 0 for _, label in COUNT_KEYS})
    files = sorted(glob.glob(os.path.join(log_dir, "log_*.txt")))
    cur_tag, prev_t, last_speed = None, None, None
    for lf in files:
        try:
            fh = open(lf, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
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
                    r = m.group(1).strip()
                    data["skips"][r] = data["skips"].get(r, 0) + 1
                    continue
                m = RE_RESULT.search(line)
                if m:
                    data["results"].append(dict(result=m.group(1),
                                                taps=int(m.group(4)), tag=m.group(5)))
                    cur_tag, prev_t = None, None
                for key, label in COUNT_KEYS:
                    if key in line:
                        data["counts"][label] += 1
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
