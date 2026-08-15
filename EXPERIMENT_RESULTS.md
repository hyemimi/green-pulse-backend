# 코드 실행 결과 요약

## 1. Specialist별 결과

| Specialist | Test episode | Normal false / reactor-day | Episode delay | ≤30m |
|---|---:|---:|---|---:|
| F1/F3 thermal Stage1 | 4 | 176.215 | 2 / 5 / 11 / 5m | 4/4 |
| F2 final | 2 | 1.014 | 24 / 15m | 2/2 |
| F4 final | 3 | 1.005 | 15 / 20 / 11m | 3/3 |

Thermal은 단독 final alarm이 아니라 **provisional evidence**로 사용한다.

## 2. F2 EDA → 모델 개선 결과

- Stage1 `h=8`: 약 26.72 false/day, delays 24/10m
- 20m negative-bias + 5m confirmation: 약 6.09 false/day, delays 24/15m
- feed mean-z + coolant slope LR: 약 **1.014 false/day**, delays **24/15m**

즉 조기 탐지 시간을 유지하면서 false alarm을 약 `26.7 → 1.0/day`까지 줄였다.

## 3. F4 EDA → 모델 개선 결과

recommended model: vibration + current + power Logistic Regression, threshold 0.93

- calibration false/day: 1.0
- test false/day: 1.005
- test delays: 15 / 20 / 11m
- median: 15m
- 3/3 within 30m

## 4. 통합 전후

### 단순 통합 v1

- test 9 episodes: 9/9 within 30m
- 7/9 within 15m
- median delay 11m
- wrong-before-correct: 66.7%
- normal false union: 약 178/day

### thermal arbitration v2, hold=0

- test 9 episodes: **9/9 within 30m**
- **7/9 within 15m**
- median delay: **11m**
- wrong-before-correct: **22.2%**
- normal false: **21.97/day**

| Episode | Fault | Reactor | Correct delay | Wrong-before-correct |
|---:|---|---|---:|---|
| 17 | F1 | A_R2 | 2m | No |
| 19 | F4 | A_R2 | 15m | No |
| 32 | F1 | A_R3 | 8m | No |
| 49 | F4 | B_R1 | 20m | No |
| 51 | F1 | B_R1 | 11m | No |
| 60 | F3 | B_R2 | 5m | Yes (F4 at +4m) |
| 71 | F2 | B_R3 | 24m | Yes (thermal at +6m) |
| 73 | F4 | B_R3 | 11m | No |
| 75 | F2 | B_R3 | 15m | No |

## 5. 현재 최종 해석

현재 파이프라인은 **조기 fault identification** 관점에서는 좋은 coverage와 delay를 보인다. 반면 thermal provisional false alarm 때문에 전체 alarm burden은 production deployment 기준으로 높다.

따라서 현재 결과를 표현할 때는:

> “held-out test fault 9개를 모두 30분 이내 진단했으며 median delay 11분을 달성했다. F2/F4는 약 1 false alarm/reactor-day까지 줄였으나, 초기 thermal signal은 정상 변동과 겹쳐 전체 false alarm 약 21.97/day가 남아 있어 operational alarm layer의 추가 개선이 필요하다.”

라고 정리하는 것이 가장 정확하다.

## 6. 원본 결과 파일

세부 수치는 `results/*.csv`를 참고한다. 특히:

- `final_consolidated_metrics.csv`
- `thermal_test_episode_results.csv`
- `f2_stage3_ablation.csv`
- `f4_1day_ablation_summary.csv`
- `final_arbitration_summary.csv`
- `final_episode_results_hold0.csv`
