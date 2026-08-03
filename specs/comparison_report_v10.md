# Static vs Dynamic Diagnostic: Engine Comparison

**Engine version:** 0.10.0 (outcomes measured on the verdict-neutral 0.9.0 baseline)
**Sample:** 500 learners per grade (G2 to G5), 3 replicates each, the same learners across all arms
**Scored skill-rows (with entry ground truth):** 42,693 (G2 5,364; G3 9,969; G4 12,375; G5 14,985)
**Date of run:** June 2026

This report measures the static diagnostic against the dynamic diagnostic engine (0.9.0), using the engine's own verdicts replayed over learners' real entry mastery records (with question responses simulated from a fixed 0.90/0.15 model; see the method note in §2). The engine's internal scoring uses per-question calibrated slip and guess values estimated by a two-class DINA calibration (a label-free item-difficulty model); the per-skill belief update itself is a standard Bayesian update. This run uses the 667-item calibration that ships with the engine. The engine has since moved to **0.10.0**, adding mixed-mode online/offline switching and a deactivation failsafe; both are verdict-neutral (they change how and when questions are delivered, never how an answer is scored), so this comparison - run on 0.9.0 - is unchanged at 0.10.0.

---

## 1. Headline answer

When the engine commits to a confident verdict, it is **more accurate than the static diagnostic** (93% online, 96% offline, versus 87% static) and **safer on false skips** (skipping a not-yet-mastered skill: 3.4% online, 2.1% offline, versus 3.8% static). Its calibration is strong: when it says "mastered," the learner has actually mastered the skill 97 to 98% of the time.

The value is **not** in cutting diagnostic questions. Direct-question savings are modest and shrink with grade (about 8% overall online, from 15% at G2 to 4% at G5), and the offline path saves almost nothing directly because it deliberately fills the question budget for coverage. The real saving is downstream: the engine lets each learner **skip about 27 MainD (main diagnostic) questions** on skills it confidently masters, with only 2 to 4% of those skips being mistakes.

Glossary of terms used below:
- **Static diagnostic:** the fixed-question battery used in Delhi in April to May 2026. Every learner answers the same set per grade.
- **Dynamic online:** the engine running fully adaptively (it picks each next question from live probability estimates).
- **Dynamic offline:** the engine running from pre-built decision trees on-device (for learners without connectivity).
- **Verdict bands:** the engine labels each skill `confident_mastered`, `confident_not_mastered`, or `uncertain`.
- **Ground truth:** `entry_mastered` (a yes/no mastery flag per learner-skill from the learner's entry track record).
- **MainD:** the deeper main diagnostic that follows; a confidently-mastered skill can skip its MainD questions.

---

## 2. Method

| Component | Setting |
|---|---|
| Static arm | Delhi battery from `delhi_diagnostic_coverage.xlsx`; Numbers operation and Place Value Chart excluded |
| Ground truth | `entry_mastered` (binary) from `entry_mastery_cells.parquet` |
| Answer model | Fixed: a learner answers correctly with probability 0.90 if the skill is mastered, 0.15 if not (slip 0.10, guess 0.15), identical across all three arms |
| Dynamic online | engine 0.9.0: `start_session` + `select_next_coverage` + `record_response` + `compute_verdicts` |
| Dynamic offline | engine 0.9.0: `base_first_follow` (three-pass capped walk) + `score_history`; locked allowances G2 +3 / G3 +4 / G4 +4 / G5 +3; hard budget cap 25 / 42 / 59 / 76 |
| Engine internal scoring | Per-question calibrated slip/guess from the 667-item calibration (true production behaviour) |
| Skill denominator | Engine scope equals the static battery skills (minus PVC/Numbers) at every grade: 12 / 21 / 30 / 39. All three arms compare on the same skills |

Metric definitions (held fixed across the comparison):
1. **Static binarisation:** a skill counts as mastered if fraction-correct on its battery questions is at least 0.75 (the project's `MASTERY_THRESHOLD`).
2. **Per-skill accuracy with "uncertain":** headline accuracy is computed on confident decisions only, with coverage (the share of skills the engine commits on) reported alongside. An "all-skills" view (uncertain treated as not-mastered) is also given.
3. **Answer-versus-scoring mismatch:** the simulated answers carry uniform 0.10/0.15 noise while the engine scores with its calibrated slip/guess. This deliberate mismatch measures the engine as it actually behaves, and makes the dynamic accuracy a conservative estimate.
4. **MainD saved:** per learner, the sum of MainD question counts (`maind_question_counts.csv`) over skills the engine verdicts `confident_mastered`, split into correctly-saved and false-saved.

---

## 3. Per-skill accuracy

Accuracy is the share of skills where the predicted mastery (mastered / not mastered) matches the ground truth. For the dynamic arms, the headline figure counts only skills where the engine made a confident call; "coverage" is the share of skills it committed on.

| Grade | Static | Online (confident) | Online coverage | Offline (confident) | Offline coverage |
|---|---|---|---|---|---|
| G2 | 0.846 | 0.927 | 0.901 | 0.959 | 0.867 |
| G3 | 0.877 | 0.922 | 0.941 | 0.961 | 0.780 |
| G4 | 0.871 | 0.934 | 0.935 | 0.960 | 0.843 |
| G5 | 0.869 | 0.941 | 0.912 | 0.959 | 0.758 |
| **Overall** | **0.869** | **0.933** | **0.924** | **0.960** | **0.801** |

All-skills view (uncertain treated as not-mastered, so every skill gets a decision, directly comparable to static):

| Grade | Static | Online (all) | Offline (all) |
|---|---|---|---|
| G2 | 0.846 | 0.845 | 0.855 |
| G3 | 0.877 | 0.893 | 0.862 |
| G4 | 0.871 | 0.900 | 0.887 |
| G5 | 0.869 | 0.895 | 0.879 |
| **Overall** | **0.869** | **0.890** | **0.874** |

Reading it: the offline engine is the most accurate when it commits (96%) but the most cautious (it commits on about 80% of skills, leaving the rest uncertain). The online engine commits far more often (92% coverage) at a slightly lower per-call accuracy (93%). Under the all-skills view, where uncertainty is forced into a "not mastered / keep" decision, the dynamic arms land level with or above static; the gain over static lives in the confident decisions.

**Static coverage at the individual (L2.5) skill level.** The accuracy and false-skip figures score the static arm over every in-scope skill, binarising each skill's battery at 0.75 (§2), so in that scoring sense static "commits" on 100% of skills. But the static battery asks only 1 to 4 questions per skill, and for many skills it asks a single question - which cannot separate a slip or lucky guess from genuine mastery. Counting only skills the battery asks more than one question about as reliably assessable at the L2.5 level:

| Grade | In-scope L2.5 skills | Reliably assessable (>1 question) | Coverage |
|---|---|---|---|
| G2 | 12 | 6 | 50% |
| G3 | 21 | 10 | 48% |
| G4 | 30 | 14 | 47% |
| G5 | 39 | 18 | 46% |
| **Overall** | **102** | **48** | **47%** |

So at the fine skill level the static battery can reliably assess only about 47% of skills - the reason the operational static diagnostic reports at grade + L1-skill level rather than per L2.5 skill. The dynamic engine gives a confident per-skill verdict on far more (92.4% online, 80.1% offline). This is a coverage measure only: the static accuracy above is still computed over all skills, which if anything flatters static, since its single-question verdicts are the noisiest. (Source: `delhi_diagnostic_coverage.xlsx`, "L2.5 Skill Coverage" sheet; Numbers and Place Value Chart excluded, matching the arm definitions in §2.)

---

## 4. Direct question savings

Questions asked by the diagnostic itself, against the static budget (which equals the hard cap).

| Grade | Static budget | Online q-mean | Online saved | Online saved % | Offline q-mean | Offline saved | Offline saved % | Offline q-max |
|---|---|---|---|---|---|---|---|---|
| G2 | 25 | 21.2 | 3.8 | 15.2 | 24.7 | 0.3 | 1.1 | 25 |
| G3 | 42 | 36.4 | 5.6 | 13.4 | 41.1 | 0.9 | 2.2 | 42 |
| G4 | 59 | 55.2 | 3.8 | 6.4 | 58.0 | 1.0 | 1.7 | 59 |
| G5 | 76 | 72.8 | 3.2 | 4.2 | 70.9 | 5.1 | 6.7 | 76 |
| **Overall** | **50.5** | **46.4** | **4.1** | **8.1** | **48.6** | **1.8** | **3.6** | **76** |

Reading it: online savings are real but small and fall as the grade (and skill count) rises. Offline savings are near zero by design: the three-pass walk adds misconception backfill (always on) and skill harvest up to the allowance, so it uses most of the budget for coverage rather than returning questions. The `q-max` column confirms the hard cap holds exactly at every grade (no session exceeds the budget).

---

## 5. MainD questions saved

Per learner, the MainD questions skipped on skills the engine confidently masters, split into correctly-saved (truly mastered) and false-saved (a false skip). Computed over skills with entry ground truth.

| Grade | Arm | MainD saved | Correctly saved | False saved | False share % |
|---|---|---|---|---|---|
| G2 | Online | 16.1 | 15.7 | 0.4 | 2.6 |
| G2 | Offline | 15.9 | 15.6 | 0.3 | 1.7 |
| G3 | Online | 24.1 | 22.7 | 1.3 | 5.5 |
| G3 | Offline | 21.5 | 21.1 | 0.5 | 2.2 |
| G4 | Online | 30.6 | 29.3 | 1.3 | 4.2 |
| G4 | Offline | 28.9 | 28.1 | 0.8 | 2.7 |
| G5 | Online | 37.3 | 36.1 | 1.2 | 3.1 |
| G5 | Offline | 36.2 | 35.4 | 0.8 | 2.2 |
| **Overall** | **Online** | **27.0** | **25.9** | **1.1** | **3.9** |
| **Overall** | **Offline** | **25.6** | **25.0** | **0.6** | **2.3** |

Reading it: this is the main efficiency gain. A learner skips roughly 27 (online) or 26 (offline) MainD questions, almost all of them correctly. The offline arm saves slightly fewer MainD questions (it is more cautious) but with a lower error rate. These figures are a lower bound on the true per-learner saving, because each learner has entry ground truth for only a subset of in-scope skills (see caveats); the engine would also skip confidently-mastered skills that have no ground-truth row here.

---

## 6. Three-band calibration

For each verdict band: the share of all skill-decisions that fall in it, and the actual ground-truth mastery rate among them. A well-calibrated engine puts near-1.0 mastery in `confident_mastered`, near-0.0 in `confident_not_mastered`, and something intermediate in `uncertain`.

**Online**

| Grade | CM share | CM actual mastery | Unc share | Unc actual mastery | CN share | CN actual mastery |
|---|---|---|---|---|---|---|
| G2 | 0.711 | 0.977 | 0.099 | 0.904 | 0.190 | 0.262 |
| G3 | 0.558 | 0.951 | 0.059 | 0.567 | 0.382 | 0.122 |
| G4 | 0.553 | 0.962 | 0.065 | 0.590 | 0.382 | 0.106 |
| G5 | 0.560 | 0.973 | 0.088 | 0.588 | 0.353 | 0.108 |
| **Overall** | **0.577** | **0.966** | **0.076** | **0.637** | **0.348** | **0.121** |

**Offline**

| Grade | CM share | CM actual mastery | Unc share | Unc actual mastery | CN share | CN actual mastery |
|---|---|---|---|---|---|---|
| G2 | 0.713 | 0.983 | 0.133 | 0.828 | 0.154 | 0.151 |
| G3 | 0.495 | 0.979 | 0.220 | 0.489 | 0.285 | 0.070 |
| G4 | 0.524 | 0.976 | 0.157 | 0.501 | 0.319 | 0.066 |
| G5 | 0.535 | 0.980 | 0.242 | 0.370 | 0.223 | 0.092 |
| **Overall** | **0.545** | **0.979** | **0.199** | **0.469** | **0.257** | **0.082** |

(CM = confident_mastered, Unc = uncertain, CN = confident_not_mastered. CM actual mastery equals `1 - false-skip`. Shares and mastery rates are measured over all 42,693 scored skill-rows.)

Reading it: both arms are well-calibrated at the confident ends. A `confident_mastered` verdict carries 95 to 98% true mastery, and a `confident_not_mastered` verdict is correct about 88% of the time online and 92% offline overall (CN actual mastery 0.121 and 0.082); at G3 to G5 the not-mastered calls are cleaner still (CN mastery 0.07 to 0.12), with G2 the one band where a larger share of not-mastered calls are actually mastered. The `uncertain` band sits in between as it should (actual mastery around 0.5 to 0.6 at G3 to G5), confirming the engine reserves that label for genuinely ambiguous skills rather than dumping hard cases into it. The offline arm parks more skills in `uncertain` (about 20% versus 8% online), the cost of having no live cross-operation data on-device.

---

## 7. False-skip rate

The probability that a skill flagged `confident_mastered` is actually not mastered. This is the safety-critical metric, because a false skip removes practice the learner needed.

| Grade | Static | Online | Offline |
|---|---|---|---|
| G2 | 0.014 | 0.023 | 0.017 |
| G3 | 0.042 | 0.049 | 0.021 |
| G4 | 0.045 | 0.038 | 0.024 |
| G5 | 0.039 | 0.027 | 0.020 |
| **Overall** | **0.038** | **0.034** | **0.021** |

Reading it: the dynamic arms are at least as safe as the static diagnostic, and the offline arm is the safest (2.1%), because its extra caution (more `uncertain`) keeps borderline skills out of the skip set.

---

## 8. Findings and caveats

1. **Direct diagnostic-question savings are modest, not the headline.** Online saves about 8% of questions overall (15% at G2, falling to 4% at G5); offline saves almost nothing directly because it spends the budget on coverage. The efficiency case rests on accuracy and MainD savings.
2. **The MainD saving is the real gain:** about 26 to 27 questions per learner skipped on confidently-mastered skills, 96 to 98% of them correctly.
3. **Dynamic confident decisions beat static accuracy** (93% online, 96% offline, versus 87%) and are at least as safe on false skips.
4. **Online versus offline is a coverage-versus-caution trade.** Online commits on about 92% of skills; offline commits on about 80% but is more accurate and safer when it does. The offline `uncertain` share is the cost of having no live cross-operation data on-device; those skills are not wrong, they pass to MainD rather than being resolved early.
5. **These accuracy figures are conservative.** The simulated answers carry uniform 0.10/0.15 noise while the engine scores with its calibrated slip/guess (metric definition 3). A self-consistent run would likely score the dynamic arms higher.
6. **Ground-truth coverage is partial.** Each learner has entry ground truth for only 3.6 (G2) to 10.2 (G5) of the in-scope skills, so all metrics are measured on that subset, and the per-learner MainD saving is a lower bound.
7. **Offline trees use Delhi-derived priors today.** As per-tenant data arrives (Telangana next), the offline trees are regenerated and the offline figures refresh; the `uncertain` share is expected to fall as local priors sharpen the trees.
8. **Static threshold is a lever.** Static accuracy and false-skip depend on the 0.75 binarisation; a lower threshold would raise static "mastered" calls and its false-skip rate.

---

## 9. Reproduction

- `v8_compare.py <grade>` builds the offline trees for the grade and runs all three arms over the sampled learners, writing `records_g<grade>.csv` and `sessions_g<grade>.csv`.
- `v8_aggregate.py` reads all grades and produces every table above plus `metrics_summary.csv`.
- Inputs: the engine at `diagnostic_engine_v9/` (with the 667-item `question_parameters.csv`), `entry_mastery_cells.parquet`, `delhi_diagnostic_coverage.xlsx`, `maind_question_counts.csv`, and the engine's canonical data files.
- **Validation gate:** before this run, the same procedure was executed against the 638-item calibration and reproduced the prior `metrics_summary.csv` exactly, every grade and overall, confirming the only change here is the calibration the engine scores with.
- **Scorer determinism:** under the 667-item calibration, the offline history scorer reproduced the online engine's verdicts exactly across 420 sessions / 8,820 skill comparisons (0 mismatches).

*The `v8_*` aggregation scripts and the `diagnostic_engine_v9/` folder named above are the names used in the June 2026 run, kept here as the record of that 0.9.0 measurement; the current bundle ships the engine as `diagnostic_engine`.*
