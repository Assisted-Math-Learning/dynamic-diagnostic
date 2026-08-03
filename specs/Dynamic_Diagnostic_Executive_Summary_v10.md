# The AML Dynamic Diagnostic

### Executive summary

**Version 10 (engine 0.10.0)  |  July 2026**

---

## The short version

The AML programme is building a smarter way to find out what maths each learner already understands. Instead of giving every learner the same fixed test, the **dynamic diagnostic** chooses each question based on how that learner has answered so far. It reaches a confident picture of a learner's skills, knows how sure it is about that learner, and works in low-connectivity settings (it needs a connection only briefly at the start, not during the test itself).

Measured against learners' real mastery records (question responses simulated), it is **more accurate on the skills it commits to, at least as safe overall, and reduces follow-up testing** compared with the fixed test used today. The engineering to connect it into the AML app is well defined, and the recommended next step is that integration followed by a monitored pilot.

A few terms used below: a **skill** is the smallest thing measured (for example, "2-digit addition with carry"); the **static diagnostic** is today's fixed-question test; **MainD** is the deeper follow-up test a learner takes per skill, which can be skipped when the engine is confident that learner has already mastered the skill.

---

## Why change the current approach

Today's static diagnostic asks every learner the same questions regardless of their answers. That is simple, but it cannot adapt: it spends questions on skills a learner has clearly mastered, and it has too few questions to judge many individual skills confidently - so it reports at a coarser level and, where it does decide, commits to a yes-or-no even when the evidence about that learner is thin. The dynamic diagnostic works differently: it spends questions where they are most informative for that learner, gives a verdict at the individual-skill level, and holds back from a confident call when it is not sure.

Under the hood it uses well-established methods rather than anything experimental: it maintains a probability that the learner has mastered each skill and revises that probability with each answer (a standard Bayesian update), drawing on questions whose difficulty has been statistically calibrated beforehand. It can also attach a specific **misconception** tag to a wrong answer, so practice can target the exact mistake.

---

## What it improves

Measured by replaying learners' real mastery records (with simulated question responses) through the current engine:

- **More accurate where it acts, through calibrated abstention.** When the engine commits to a confident verdict, it is right 93% of the time online and 96% offline, against 87% for the static test. The reason it can be that accurate is that it only commits on the skills it is sure about - about 92% of a learner's skills online, and about 80% offline - and routes the rest to the follow-up test rather than guessing. (The static test, by contrast, has more than one question for only about 47% of individual skills, so it can reliably judge only about half of them at that level.) Counting every skill like-for-like, the accuracy edge over static is smaller (about 89% online, 87% offline, versus 87%); the engine's distinctive strength is that it knows when it does not know, and abstains instead of committing to a wrong answer. When it does say "mastered," the learner has actually mastered the skill 97 to 98% of the time.
- **At least as safe overall, with Grade 2 the exception to watch.** A "false skip" means wrongly telling a learner they can skip practice on a skill they have not mastered. Across all skills the dynamic diagnostic makes no more of these than the static test, and fewer offline: 3.4% online and 2.1% offline, against 3.8% static. The exception is Grade 2, where both modes are slightly higher than static (2.3% online, 1.7% offline, versus 1.4%). The gap is small, but it falls on the youngest learners, so it is a deliberate watch-item for the pilot rather than something to average away.
- **Less follow-up testing.** For each skill the engine confidently finds a learner has mastered, the learner skips that skill's follow-up questions: roughly 26 to 27 fewer per learner, 96 to 98% of them correctly. Counting the diagnostic and the follow-up together, a learner answers on the order of 30 fewer questions overall than under the static approach - almost all of it from the follow-up saving, since the diagnostic itself is only modestly shorter.

![Skills each diagnostic can assess reliably](img/coverage_comparison.png)

![Dynamic vs static: accuracy and false skips](img/performance_comparison.png)

It is worth being clear about what does **not** change much: the dynamic diagnostic does not mainly shorten the diagnostic itself. Those direct savings are modest (about 8% on average online, and near zero offline, because the offline mode deliberately uses its question budget for thorough coverage). The value is accuracy, safety, and the combined follow-up saving above.

---

## It works online and offline

AML learners are often in places with weak or no internet, so the same engine runs two ways. Online, a server picks each next question live. Offline, the device follows a question map prepared in advance using the same logic, so no live connection is needed while the learner is answering - though the device does need a brief connected moment at the start to download the map and the questions it might use. Both modes produce the same kind of result. A learner's test is not locked to one mode: it runs online while there is a connection, carries on offline from exactly where it was if the connection drops, and hands back to the server when it returns - any number of times, always as one continuous test with one set of results. When an offline stretch is later synced, the server scores the whole test together, so a session split across online and offline reaches the same verdicts as a fully-online one. A small safeguard also lets a question be pulled from the app at short notice (a broken image, say) without changing how any answer is scored. The offline mode is a little more cautious by design (it leaves about one in five of a learner's skills "uncertain," versus about one in twelve online), which also makes it the safer of the two on false skips.

![One engine, two ways to run it](img/online_vs_offline.png)

![Mixed-mode: one session across online and offline](img/mixed_mode_handoff.png)

---

## What's next

The results above come from a strong test (replaying learners' real mastery records, with simulated question responses), and the path from here is well defined:

- **Integrate, then pilot.** Connecting the engine into the AML app is a scoped piece of engineering, sequenced as online mode first, then offline. The first classroom rollout should be a monitored pilot at pilot scale (a single engine instance comfortably handles a few hundred learners testing at once; a large simultaneous rollout later is a standard scaling step). The pilot both confirms the simulated gains in the field and produces the live data that sharpens the engine further.
- **Watch Grade 2 closely.** Grade 2 is the engine's weakest grade today - the slightly higher false-skip rate above, plus two buckets (Grade 2 subtraction and Grade 4 addition) where it currently commits and is wrong more often than the static test. These are named watch-items and the first targets for calibration work.
- **Sharpen with more regions' data.** The current estimates are calibrated on Delhi data. As data from other regions arrives (Telangana next), the estimates are refreshed and the offline question maps are rebuilt, which is expected to lift offline coverage in particular.
- **Turn on misconception-targeted practice.** The misconception classifier is built and verified in testing (it is not yet running in production, because nothing in this system is live yet); the pilot is the point at which that signal can begin steering targeted practice.

Each of these makes the diagnostic better over time; none of them blocks the pilot.

---

## Bottom line

The dynamic diagnostic gives more trustworthy, better-calibrated results than the fixed test - accurate where it commits, honest about when it is unsure - keeps learners at least as safe from skipping needed practice (with Grade 2 the one grade to watch), and cuts follow-up testing, while working in low-connectivity settings, all on well-established methods and validated against learners' real mastery records (with simulated question responses). The recommended next step is to integrate it into the AML app and run a monitored pilot.
